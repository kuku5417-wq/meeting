"""config/settings.py — 전환 지점: 망 구분 · 비밀 읽기 · 프록시 · LLM 키.

shi 규약(전환 지점 네 곳)의 두 번째. 망이 사외망/사내망에 따라 달라지는 값은 **이 파일 하나**를 거친다.

결정 ⑤(2026-11-13) — 코드가 망을 스스로 알아내지 않는다.
  - 망은 `.claude/shi.json` 의 `net` 한 줄(`external` | `internal`). 파일이 없으면 `external` 로 본다
    (폴백 원칙 — 설정이 없어도 앱은 뜬다). 환경변수 `SHI_NET` 이 덮는다(`setup_env.bat` 이 이미 쓰는 이름,
    `corporate` 도 사내망으로 읽는다).
  - `shi.json` 은 PC 마다 다르므로 커밋하지 않는다(2026-11-24 결정, `.gitignore`).
    사내망 판에서 파일이 빠지면 조용히 사외망으로 돌 수 있으므로 `check_env.py` 가 읽은 값과 출처를 찍는다.

`.env` 는 **직접 읽고 환경변수로 올리지 않는다.** `load_dotenv` 를 부르면 사내 프록시 값이 사외망 프로세스에
주입돼 모든 외부 호출이 실패한다(공통지침에 적힌 실제 사고). 그래서 값은 함수로만 꺼낸다.

프록시는 **사내망일 때만** 돌려준다. 인터넷으로 나가는 호출만 프록시를 타고, 사내 서버는 직접 접속한다
(`modules/llm_client.py` 의 SOLA 호출은 `proxies={"http": None, "https": None}` 로 우회 — `None` 단독은 안 된다).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # meeting/
SHI_JSON = ROOT / ".claude" / "shi.json"

_INTERNAL_WORDS = ("internal", "corporate", "사내망")
_EXTERNAL_WORDS = ("external", "outside", "사외망")


# ── 비밀(.env) ───────────────────────────────────────────
def _find_secret_env() -> Path:
    """secret/.env 위치를 포터블하게 탐색.

    우선순위: 환경변수 `SHI_ENV_FILE` → 이 파일 위치에서 위로 올라가며 첫 `secret/.env`
    → 기본값(`<repo 상위>/secret/.env`, 없어도 무해).
    """
    ov = os.getenv("SHI_ENV_FILE")
    if ov and Path(ov).exists():
        return Path(ov)
    for d in (ROOT, *ROOT.parents):
        cand = d / "secret" / ".env"
        if cand.exists():
            return cand
    return ROOT.parent / "secret" / ".env"


SECRET_ENV = _find_secret_env()


def secret(key: str) -> str:
    """`secret/.env` 에서 `KEY=` 값 읽기 (없으면 빈 문자열). 값은 로그·화면에 노출 금지."""
    try:
        if not SECRET_ENV.exists():
            return ""
        text = SECRET_ENV.read_text(encoding="utf-8-sig")   # 메모장 저장본의 BOM 대비
        m = re.search(rf"^{re.escape(key)}[ \t]*=[ \t]*([^\n]*)$", text, re.MULTILINE)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001 — .env 없음/깨짐 → 미설정으로 본다
        pass
    return ""


def value(key: str) -> str:
    """환경변수가 **있으면**(빈 값이어도) 그것, 없으면 `.env`.

    빈 문자열도 「일부러 비운 것」으로 존중한다 — 시험이 키를 비워 네트워크를 타지 않게 하는 방식
    (`_smoke._offline_llm`)을 깨지 않기 위해서다.
    """
    v = os.environ.get(key)
    return v.strip() if v is not None else secret(key)


# ── 망 ───────────────────────────────────────────────────
def net_source() -> tuple[str, str]:
    """(망, 어디서 읽었나) — check_env·진단이 함께 쓴다."""
    ov = (os.getenv("SHI_NET") or "").strip().lower()
    if ov:
        if ov in _INTERNAL_WORDS:
            return "internal", "환경변수 SHI_NET"
        if ov in _EXTERNAL_WORDS:
            return "external", "환경변수 SHI_NET"
    try:
        raw = str(json.loads(SHI_JSON.read_text(encoding="utf-8")).get("net", "")).strip().lower()
    except Exception:  # noqa: BLE001 — shi.json 없음/깨짐 → 사외망으로 본다
        raw = ""
    if raw in _INTERNAL_WORDS:
        return "internal", ".claude/shi.json"
    if raw in _EXTERNAL_WORDS:
        return "external", ".claude/shi.json"
    return "external", "기본값(.claude/shi.json 없음)"


def net() -> str:
    return net_source()[0]


def is_internal() -> bool:
    return net() == "internal"


def env_label() -> str:
    """화면 표시용 — 「사내망」/「사외망」."""
    return "사내망" if is_internal() else "사외망"


# ── 프록시 ───────────────────────────────────────────────
def _normalize_proxy(v: str) -> str:
    """`host:port` 처럼 스킴이 없는 값에 `http://` 를 붙인다."""
    v = (v or "").strip()
    if not v:
        return ""
    return v if "://" in v else "http://" + v


def proxies() -> dict | None:
    """requests 용 프록시 — **사내망일 때만**. 값이 없으면 None.

    사외망에서 None 을 돌려주는 것이 이 함수의 핵심이다(사내 프록시가 사외망으로 새지 않는다).
    """
    if not is_internal():
        return None
    http = _normalize_proxy(value("HTTP_PROXY"))
    https = _normalize_proxy(value("HTTPS_PROXY"))
    if not (http or https):
        return None
    return {"http": http or https, "https": https or http}


def use_proxy() -> bool:
    return proxies() is not None


def ssl_verify() -> bool:
    """프록시를 쓰면 사내 MITM 인증서 때문에 검증을 끈다(공통지침 `SSL_VERIFY = not USE_PROXY`)."""
    return not use_proxy()


# ── LLM 키 ───────────────────────────────────────────────
def llm_keys() -> dict[str, dict[str, str]]:
    """공급자별 접속값. 비어 있으면 그 공급자는 「미설정」으로 건너뛴다(폴백 체인).

    `modules/llm_client.py`(단계 2-b) 가 쓴다. 값은 돌려주기만 하고 로그·화면에 찍지 않는다.
    """
    return {
        "sola": {"url": value("LLM_SOLAR_API_URL"),
                 "key": value("LLM_SOLAR_API_KEY"),
                 "model": value("LLM_SOLAR_MODEL")},
        "upstage": {"url": value("LLM_UPSTAGE_BASE_URL") or "https://api.upstage.ai/v1",
                    "key": value("LLM_UPSTAGE_API_KEY"),
                    "model": value("LLM_UPSTAGE_MODEL") or "solar-pro"},
        "openai": {"url": "https://api.openai.com/v1",
                   "key": value("LLM_OPENAI_API_KEY"),
                   "model": value("LLM_OPENAI_MODEL") or "gpt-4o-mini"},
    }
