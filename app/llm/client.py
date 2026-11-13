"""app/llm/client.py — LLM 어댑터 + 폴백 체인 (docs/04 §1). 서비스 코드는 공급자를 모른다.

체인: `settings.LLM_CHAIN` 순서(기본 sola → upstage → openai → mock, 공통지침 3단 + Mock).
형제 앱 `costplan/llm_client.py`(2026-10-20 확인)의 검증된 호출 규칙을 옮겼다:
  - **단일 클라이언트로 축약하지 않는다** — 공급자별 실패 사유를 누적해 조용한 실패를 드러낸다.
  - SOLA: 프록시 우회 `proxies={"http": None, "https": None}`(None 은 안 된다), `verify=False`,
    `stream`·토큰 상한(`max_tokens`)을 **보내지 않는다**(400 또는 200+"please check parameter").
  - 응답의 `<think>…</think>`·코드펜스를 지운 뒤 JSON 파싱.
  - requests 사용 — 사내 MITM 프록시에서 httpx 행(hang) 실측.
그 위에 이 앱의 규칙을 얹는다:
  - 응답은 JSON 스키마로 검증하고, 검증 실패는 같은 공급자로 1번 더 시도 후 다음 공급자로(총 2회).
  - 호출마다 `llm_call_log` 한 줄(공급자·모델·소요·성공·오류). **본문은 저장하지 않는다.**
  - 키가 없는 공급자는 네트워크를 타지 않고 「미설정」으로 바로 넘어간다.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema

from app import settings

import app_config as ac  # noqa: E402  (settings 가 sys.path·.env 를 준비한 뒤)

MOCK_DIR = settings.ROOT / "data" / "samples"
MOCK_FILES = {"extract_blocks": "mock_extraction.json", "extract_meeting_items": "mock_meeting_items.json"}


class ProviderError(Exception):
    """공급자 하나의 실패 — 사유는 한국어로."""


@dataclass
class LLMResult:
    data: dict | None
    provider: str | None = None
    model: str | None = None
    errors: list[str] = field(default_factory=list)   # 앞선 공급자들의 실패 사유 (화면에 보여준다)

    @property
    def ok(self) -> bool:
        return self.data is not None


# ── 응답 정리 ───────────────────────────────────────────
def parse_json_text(content: str) -> dict:
    content = re.sub(r"<think>.*?</think>", "", content or "", flags=re.DOTALL).strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            return json.loads(m.group())
        raise ProviderError(f"JSON 이 아닌 응답: {content[:80]!r}") from None


# ── 공급자 ──────────────────────────────────────────────
def _error_reason(resp, api_key: str) -> str:
    """오류 응답의 사유 한 줄(예: invalid model ID · insufficient credit). 키는 가리고 120자로 자른다."""
    try:
        err = resp.json().get("error")
        msg = err.get("message") if isinstance(err, dict) else err
    except (ValueError, AttributeError):
        msg = None
    if not msg:
        return ""
    msg = str(msg).replace(api_key, "***") if api_key else str(msg)
    return f" — {' '.join(msg.split())[:120]}"


def _chat(base_url: str, api_key: str, model: str | None, system: str, user: str, *,
          proxies: dict | None, verify: bool, timeout: float, response_format: dict | None = None,
          temperature: float | None = 0.1) -> str:
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    body: dict = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    if temperature is not None:
        body["temperature"] = temperature
    if model:
        body["model"] = model
    if response_format:
        body["response_format"] = response_format
    # ⚠ max_tokens·stream 은 넣지 않는다 (공통지침 절대 규칙 5)
    try:
        resp = requests.post(base_url.rstrip("/") + "/chat/completions",
                             headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                             json=body, proxies=proxies, timeout=timeout, verify=verify)
    except requests.RequestException as e:
        raise ProviderError(f"접속 실패({type(e).__name__})") from e
    except UnicodeEncodeError as e:     # 헤더(키)에 한글·특수 하이픈 등 비ASCII 가 섞이면 requests 가 여기서 멈춘다
        raise ProviderError("키에 한글·특수문자가 섞여 있음 — secret/.env 값 확인") from e
    if resp.status_code >= 400:
        raise ProviderError(f"HTTP {resp.status_code}{_error_reason(resp, api_key)}")
    try:
        content = resp.json()["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError) as e:
        raise ProviderError("응답 형식이 OpenAI 호환이 아님") from e
    if "please check parameter" in content.lower():      # SOLA 의 조용한 실패
        raise ProviderError("SOLA 가 파라미터를 거부함(please check parameter)")
    return content


def _call_sola(task: str, system: str, user: str, timeout: float) -> tuple[str, str | None]:
    if not (ac.LLM_SOLAR_API_URL and ac.LLM_SOLAR_API_KEY):
        raise ProviderError("미설정(LLM_SOLAR_API_URL/KEY)")
    model = ac.LLM_SOLAR_MODEL or None
    return _chat(ac.LLM_SOLAR_API_URL, ac.LLM_SOLAR_API_KEY, model, system, user,
                 proxies={"http": None, "https": None}, verify=False, timeout=timeout,
                 response_format={"type": "json_object"}), model


def _call_upstage(task: str, system: str, user: str, timeout: float) -> tuple[str, str | None]:
    if not ac.LLM_UPSTAGE_API_KEY:
        raise ProviderError("미설정(LLM_UPSTAGE_API_KEY)")
    return _chat(ac.LLM_UPSTAGE_BASE_URL, ac.LLM_UPSTAGE_API_KEY, ac.LLM_UPSTAGE_MODEL, system, user,
                 proxies=ac.proxies(), verify=ac.SSL_VERIFY, timeout=timeout), ac.LLM_UPSTAGE_MODEL


def _call_openai(task: str, system: str, user: str, timeout: float) -> tuple[str, str | None]:
    if not ac.LLM_OPENAI_API_KEY:
        raise ProviderError("미설정(LLM_OPENAI_API_KEY)")
    model = (ac.LLM_OPENAI_MODEL or "").strip()
    # gpt-5·o 계열(추론 모델)은 temperature 기본값(1)만 받는다 — 보내면 HTTP 400 (2026-10-21 실측)
    fixed_temp = model.lower().startswith(("gpt-5", "o1", "o3", "o4"))
    return _chat("https://api.openai.com/v1", ac.LLM_OPENAI_API_KEY, model, system, user,
                 proxies=ac.proxies(), verify=ac.SSL_VERIFY, timeout=timeout,
                 temperature=None if fixed_temp else 0.1), model


def _mock_answer(user: str) -> str:
    """answer_knowledge 용 Mock — 고정 파일 대신, 프롬프트에 실린 사례만으로 요약한다(인용 규칙 시험용)."""
    m = re.search(r"<cases>(.*?)</cases>", user, re.DOTALL)
    cases = json.loads(m.group(1)) if m else []
    if not cases:
        return json.dumps({"answer": "", "citations": [], "insufficient": True}, ensure_ascii=False)
    by_cause: dict[str, list[dict]] = {}
    for c in cases:
        by_cause.setdefault(c.get("cause_group") or c["cause"], []).append(c)
    parts = []
    for cause, cs in sorted(by_cause.items(), key=lambda kv: -len(kv[1])):
        refs = "".join(f"[{c['id']}]" for c in cs)
        parts.append(f"{cause} {len(cs)}건 — 조치: {cs[0]['action']} {refs}")
    answer = f"관련 사례 {len(cases)}건입니다. " + " / ".join(parts)
    return json.dumps({"answer": answer, "citations": [c["id"] for c in cases], "insufficient": False}, ensure_ascii=False)


def _call_mock(task: str, system: str, user: str, timeout: float) -> tuple[str, str | None]:
    if task == "answer_knowledge":
        return _mock_answer(user), "mock"
    name = MOCK_FILES.get(task)
    if not name:
        raise ProviderError(f"Mock 샘플이 없는 작업: {task}")
    return Path(MOCK_DIR / name).read_text(encoding="utf-8"), "mock"


PROVIDERS = {"sola": _call_sola, "upstage": _call_upstage, "openai": _call_openai, "mock": _call_mock}
LABELS = {"sola": "사내 SOLA", "upstage": "Upstage", "openai": "OpenAI", "mock": "Mock"}


def _log(session, task: str, provider: str, model: str | None, started: float, ok: bool, error: str | None) -> None:
    if session is None:
        return
    from app.models import LlmCallLog
    session.add(LlmCallLog(task=task, provider=provider, model=model, ok=ok, error=error,
                           duration_ms=int((time.perf_counter() - started) * 1000)))


def complete_json(task: str, system: str, user: str, schema: dict, *, session=None,
                  chain: list[str] | None = None, timeout: float | None = None) -> LLMResult:
    """체인 순서로 시도해 스키마를 통과한 첫 응답을 돌려준다. 전부 실패하면 data=None + 사유 목록.

    결정 ① 4-b: AI 응답을 기다리는 동안 NAS 잠금을 쥐지 않는다 — 세션에 쓰기 대기(잠금 보유·새/바뀐 행)가 있으면
    먼저 commit 해 잠금을 풀고 부른다. 그래서 메모 같은 앞 단계 저장은 AI 가 실패해도 남는다.
    호출 로그(llm_call_log)는 add 만 하고 flush 하지 않으므로 응답 대기 중 잠금을 다시 잡지 않는다."""
    if session is not None and (session.info.get("nas_lock") or session.new or session.dirty or session.deleted):
        session.commit()
    errors: list[str] = []
    for name in chain or settings.LLM_CHAIN:
        fn = PROVIDERS.get(name)
        if fn is None:
            errors.append(f"{name}: 알 수 없는 공급자")
            continue
        retry_note = ""
        for attempt in (1, 2):                      # 스키마 검증 실패만 한 번 더
            started = time.perf_counter()
            model = None
            try:
                content, model = fn(task, system, user + retry_note, timeout or settings.LLM_TIMEOUT_SEC)
                data = parse_json_text(content)
                jsonschema.validate(data, schema)
            except jsonschema.ValidationError as e:
                msg = f"스키마 불일치({'/'.join(str(p) for p in e.absolute_path) or '최상위'})"
                _log(session, task, name, model, started, False, msg)
                if attempt == 1:
                    # 같은 틀림을 되풀이하지 않게 무엇이 틀렸는지 알려 주고 다시 받는다
                    # (사내 Gemma 가 blocks[0] 에 키 이름 배열을 넣는 사례 실측, 2026-10-21)
                    found = sorted(jsonschema.Draft202012Validator(schema).iter_errors(data),
                                   key=lambda x: list(map(str, x.absolute_path)))[:3]
                    detail = " / ".join(f"{'/'.join(map(str, x.absolute_path)) or '최상위'}: {x.message[:120]}"
                                        for x in found) or e.message[:200]
                    retry_note = (f"\n\n[앞 응답 오류] 스키마 불일치 — {detail}\n"
                                  "출력 형식과 예시를 정확히 따라 JSON 하나만 다시 출력한다. "
                                  "blocks 의 각 원소는 값이 채워진 객체이고, questions 는 없으면 [] 로 넣는다.")
                    continue
                errors.append(f"{LABELS.get(name, name)}: {msg}")
                break
            except ProviderError as e:
                _log(session, task, name, model, started, False, str(e))
                errors.append(f"{LABELS.get(name, name)}: {e}")
                break
            except Exception as e:  # noqa: BLE001 — 어떤 공급자 오류도 다음 공급자로 넘긴다
                _log(session, task, name, model, started, False, type(e).__name__)
                errors.append(f"{LABELS.get(name, name)}: {type(e).__name__}")
                break
            _log(session, task, name, model, started, True, None)
            return LLMResult(data=data, provider=name, model=model, errors=errors)
    return LLMResult(data=None, errors=errors)
