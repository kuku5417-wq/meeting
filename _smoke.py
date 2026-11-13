"""_smoke.py — 회귀 확인 (공통지침: pytest 대신 이 스크립트).

실행: uv run python _smoke.py     (실패가 하나라도 있으면 종료코드 1)

임시 폴더를 MEETING_DATA_PATH 로 주입하므로 실제 DB·사진 폴더는 건드리지 않는다.
화면 라벨 문자열(탭 이름 등)에 의존하는 검사는 **계약**이다 — 문구를 바꾸면 여기도 고친다.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — 리다이렉트 환경
    pass

_TMP = tempfile.mkdtemp(prefix="meeting_smoke_")
os.environ["MEETING_DATA_PATH"] = _TMP          # ★ app import 전에 주입해야 엔진이 임시 DB 를 잡는다
os.environ.pop("MEETING_DATABASE_URL", None)
os.environ["MEETING_CENTRAL_PARQUET"] = str(Path(_TMP) / "central")   # 공용 data/parquet 은 읽지 않는다(시험용 작은 파일)
os.environ["MEETING_LLM_CHAIN"] = "sola,upstage,openai,mock"   # 3단 체인 — 키는 아래에서 비워 네트워크를 타지 않는다
os.environ["MEETING_TODAY"] = "2026-10-23"           # 오늘 고정 — 주차(W43)·D-n 이 실행 날짜에 따라 바뀌지 않게
os.environ["MEETING_NO_OUTLOOK"] = "1"                # 메일함 — 켜진 Outlook 에 붙지 않게(휴면으로 시험)
sys.path.insert(0, str(Path(__file__).resolve().parent))

_results: list[tuple[bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    _results.append((bool(cond), name))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


# docs/03 §3 의 테이블 전체 — 모델을 바꾸면 문서와 이 목록을 함께 고친다.
EXPECTED_TABLES = {
    "department", "person", "week", "section", "memo", "block", "section_block", "block_history", "block_event",
    "source_span", "ai_field_log", "closure", "block_tag", "block_table",
    "photo", "photo_link", "annotation", "marker",
    "metric_def", "metric_value",
    "meeting", "meeting_comment", "meeting_candidate", "report_item", "report_item_block", "meeting_version", "directive", "import_job", "import_piece", "app_setting", "metric_table", "metric_cell",
    "case_card", "block_link", "llm_call_log",
    "ship_type", "owner", "sister_group", "hull", "system", "maker", "equipment_model",
    "installed_equipment", "component", "test_item", "symptom_code", "cause_code", "alias",
}


def t_paths() -> None:
    import path_config as pc
    check("데이터 폴더 = 주입한 임시 폴더", pc.get_data_dir() == Path(_TMP), str(pc.get_data_dir()))
    check("DB 파일이 데이터 폴더 안", pc.db_path().parent == Path(_TMP))


def t_tokens() -> None:
    root = Path(__file__).resolve().parent
    a, b = root / "design" / "tokens.css", root / "app" / "static" / "css" / "tokens.css"
    check("토큰 사본 일치 (design/tokens.css = app/static/css/tokens.css)", a.read_bytes() == b.read_bytes())


def t_weeks() -> None:
    from datetime import date

    from app.services import weeks
    w = weeks.from_date(date(2026, 10, 14))
    check("ISO 주차 계산 2026-10-14 → 2026-W42", w.id == "2026-W42", w.id)
    check("머리글 표기 = 시안과 동일", w.label == "2026-W42 · 10.12–10.16", w.label)
    check("잘못된 주차는 None", weeks.parse("2026-42") is None and weeks.parse("2026-W99") is None)


def t_app() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:      # with → lifespan(init_db) 실행
        t_base(c)
        for fn in GROUPS:             # 한 묶음이 죽어도 다음 묶음은 돌린다(앞 묶음이 만든 데이터에 기대는 검사는 그 자리에서 FAIL)
            try:
                fn(c)
            except Exception as e:  # noqa: BLE001 — 묶음 단위 실패를 결과로 남긴다
                import traceback
                traceback.print_exc()
                check(f"{getattr(fn, '__name__', 'llm')} 실행", False, repr(e))


def t_base(c) -> None:
    """앱 공통 — 표 생성·화면 탭·기준정보 시드·글꼴. 뒤 묶음들이 이 데이터를 쓴다(tests/test_01_base.py)."""
    from sqlalchemy import inspect

    from app.db import engine
    from app.services import weeks
    if True:
        tables = set(inspect(engine).get_table_names())
        missing = EXPECTED_TABLES - tables
        check(f"create_all — docs/03 테이블 {len(EXPECTED_TABLES)}개 생성", not missing, f"누락 {sorted(missing)}")

        r = c.get("/healthz")
        check("/healthz 200 + ok", r.status_code == 200 and r.json().get("ok") is True, r.text[:200])

        r = c.get("/hub")
        check("시드 전 장비 허브 — 기준정보 없음 안내", r.status_code == 200 and "seed_masters.py" in r.text)

        t_seed_and_alias()          # ← 여기서부터 기준정보가 들어 있다

        wk = weeks.current().id
        r = c.get("/write", follow_redirects=False)
        check("M13 — 옛 /write → 가져오기(메모)", r.status_code == 307
              and r.headers["location"] == "/import?entry=memo", r.headers.get("location", ""))

        pages = {
            "가져오기": "/import",
            "회의": "/meetings",
            "지식창고": "/knowledge",
            "장비 허브": "/hub",
            "장비 허브(장비)": "/hub/equipment/EQ-SN2511-GE-02",
        }
        for name, url in pages.items():
            r = c.get(url)
            body = r.text
            ok = (r.status_code == 200 and ">가져오기<" in body and ">지표<" in body and ">회의<" in body and "메모 넣기(옛)" not in body
                  and "지식창고" in body and "장비 허브" in body and 'aria-current="page"' in body)
            check(f"화면 {name} {url} — 탭 4개·현재 탭 표시", ok, f"status {r.status_code}")

        r = c.get("/meeting/2026-42")
        check("잘못된 주차 → 404 + 고치는 법 안내(옛 회의 주소)", r.status_code == 404 and "2026-W42" in r.text, r.text[:200])
        r = c.get(f"/meeting/{wk}", follow_redirects=False)
        check("M12 — 옛 「회의 · 팀 보고서」 주소 → 그 주 공유회 보기", r.status_code == 307 and r.headers["location"].startswith("/meetings/"), r.headers.get("location", ""))
        r = c.get("/static/css/tokens.css")
        check("tokens.css 서빙", r.status_code == 200 and "--accent" in r.text)

        # 로컬 글꼴 — fonts.css 가 가리키는 woff2 가 전부 있어야 사내망에서도 시안 글꼴로 보인다
        import re
        r = c.get("/static/css/fonts.css")
        urls = re.findall(r'url\("\.\./fonts/([^"]+)"\)', r.text)
        missing = [u for u in urls if c.get(f"/static/fonts/{u}").status_code != 200]
        check(f"로컬 글꼴 {len(urls)}개 서빙", r.status_code == 200 and len(urls) == 5 and not missing, f"없음 {missing}")
        check("base.html 이 fonts.css 를 불러온다", "css/fonts.css" in c.get("/knowledge").text)
        check("외부 글꼴 CDN 미사용", "fonts.googleapis.com" not in c.get("/knowledge").text)



def t_save_and_extract(c) -> None:
    """작성 화면 재배치(2026-10-21) — 「저장하고 AI 정리」 한 번에."""
    from app.db import SessionLocal
    from app.services import writing as w
    wk = "2026-W45"
    memo_text = (Path(__file__).parent / "data" / "samples" / "memo_W42_dept3.txt").read_text(encoding="utf-8")
    r = c.post(f"/write/{wk}/D6/memo", data={"raw_text": memo_text, "then": "extract"})
    with SessionLocal() as s:
        sec6 = w.get_section(s, wk, "D6")
        n6 = len(w.section_blocks(s, sec6)) if sec6 else 0
        mid = w.latest_memos(s, sec6)[0].id if sec6 else ""
    check("「저장하고 AI 정리」 한 번에 메모 저장 + 블록 생성 + 그 메모를 연 채로", "메모를 저장했습니다" in r.text
          and "AI 정리 완료" in r.text and n6 >= 3 and f'data-memo="{mid}"' in r.text, str(n6))


def t_unregistered(c) -> None:
    """기준정보에 없는 장비·호선·부위 — 미등록으로 두기·태그 빼기·마커 설명만·미등록 목록·다시 연결 (2026-10-21)."""
    from sqlalchemy import select

    from app import models as m
    from app.db import SessionLocal
    from app.services import masters as ms
    from app.services import photos as ph
    from app.services import writing as w
    wk, dept = "2026-W46", "D7"
    memo_text = (Path(__file__).parent / "data" / "samples" / "memo_W42_dept3.txt").read_text(encoding="utf-8")
    c.post(f"/write/{wk}/{dept}/memo", data={"raw_text": memo_text, "then": "extract"})
    with SessionLocal() as s:
        sec = w.get_section(s, wk, dept)
        blk = next(b for b in w.section_blocks(s, sec) if b.block_type == "problem")
        for t in w.block_tags(s, blk.id):                 # 이 시험과 무관한 확인 대기는 먼저 정리
            if w.tag_needs_check(t):
                t.confirmed = True
        unk = m.BlockTag(block_id=blk.id, kind="installed_equipment", raw_text="Sterntube", confidence=0.9, confirmed=False)
        sysx = m.BlockTag(block_id=blk.id, kind="system", raw_text="선미관 계통", confidence=0.9, confirmed=False)
        bad = m.BlockTag(block_id=blk.id, kind="hull", raw_text="2696", confidence=0.5, confirmed=False)
        s.add_all([unk, sysx, bad])
        s.commit()
        unk_id, sys_id, bad_id, blk_id = unk.id, sysx.id, bad.id, blk.id
        left = sum(1 for t in w.block_tags(s, blk_id) if w.tag_needs_check(t))
        sys_opts = w.link_options(s, sysx)
    check("미연결 장비·시스템·호선 → 확인할 태그로 남음", left == 3, repr(left))
    check("시스템 태그도 연결 후보가 나온다", len(sys_opts) > 0)
    r = c.get(f"/issues?id={blk_id}")
    check("M12 이슈 원장 매핑 칸 — 미등록으로 두기·빼기 버튼", f'/tags/{unk_id}/unregistered' in r.text and f'/tags/{bad_id}/dismiss' in r.text)
    r = c.post(f"/tags/{unk_id}/unregistered")
    c.post(f"/tags/{sys_id}/unregistered")
    r2 = c.post(f"/tags/{bad_id}/dismiss")
    with SessionLocal() as s:
        sec = w.get_section(s, wk, dept)
        left = sum(1 for t in w.block_tags(s, blk_id) if w.tag_needs_check(t))
        shown = [t.raw_text for t in w.block_tags(s, blk_id)]
    check("미등록으로 두기 → 확인할 태그에서 빠짐·회색 「미등록」 표시", not left and "미등록으로 두었습니다" in r.text and "unreg-l" in r.text, repr(left))
    check("태그 빼기 → 화면·목록에서 사라짐", "2696" not in shown and "뺐습니다" in r2.text, repr(shown))
    c.post(f"/write/{wk}/{dept}/memo/{w.latest_memos(SessionLocal(), w.get_section(SessionLocal(), wk, dept))[0].id}/extract")
    with SessionLocal() as s:
        rows = {t.raw_text: (t.confirmed, t.target_id, t.dismissed) for t in s.scalars(select(m.BlockTag).where(m.BlockTag.block_id == blk_id))}
    check("다시 정리해도 미등록 유지·뺀 태그는 되살아나지 않음", rows.get("Sterntube") == (True, None, False) and rows.get("2696") == (True, None, True),
          repr({k: v for k, v in rows.items() if k in ("Sterntube", "2696")}))
    # 마커 부위 — 목록에 없으면 설명만 적어도 통과
    with SessionLocal() as s:
        ann = m.Annotation(photo_id=s.scalars(select(m.Photo.id)).first(), block_id=blk_id, shapes_json="[]")
        s.add(ann)
        s.flush()
        s.add_all([m.Marker(annotation_id=ann.id, no=1, x=10, y=10, label="선미관 씰 손상", component_id=None),
                   m.Marker(annotation_id=ann.id, no=2, x=20, y=20, label="  ", component_id=None)])
        s.commit()
        miss = ph.markers_missing_part(s, blk_id)
    check("마커 — 부위 없이 설명만 있으면 통과, 둘 다 비면 남음", miss == 1, str(miss))
    with SessionLocal() as s:
        s.query(m.Marker).filter(m.Marker.label.like(" %")).delete(synchronize_session=False)
        s.commit()
        sec = w.get_section(s, wk, dept)
        left_all = sum(1 for t in w.block_tags(s, blk_id) if w.tag_needs_check(t)) + ph.markers_missing_part(s, blk_id)
    check("미등록·설명만 마커로 확인할 것(태그·마커) 0", left_all == 0, repr(left_all))
    # 미등록 목록 · 다시 연결
    r = c.get("/hub")
    with SessionLocal() as s:
        lst = ms.unregistered(s)
    check("장비 허브 — 기준정보에 없는 표기 목록", any(g["text"] == "Sterntube" and g["kind"] == "installed_equipment" for g in lst)
          and 'id="unreg"' in r.text and "Sterntube" in r.text, repr([(g["kind"], g["text"]) for g in lst]))
    with SessionLocal() as s:
        eq = s.scalars(select(m.InstalledEquipment).order_by(m.InstalledEquipment.id)).first()
        s.add(m.Alias(text="Sterntube", target_kind="installed_equipment", target_id=eq.id, scope_hull_id=None, source="seed"))
        s.commit()
        eq_id = eq.id
    r = c.post("/hub/relink")
    with SessionLocal() as s:
        t = s.get(m.BlockTag, unk_id)
    check("기준정보·별칭에 넣은 뒤 「다시 이어 보기」 → 미등록 태그가 연결됨", t.target_id == eq_id and "1건을 기준정보에 이었습니다" in r.text,
          repr(t.target_id))
    with SessionLocal() as s:
        sec = w.get_section(s, wk, dept)
        from datetime import datetime
        sec.status, sec.confirmed_at = "확정", datetime.now()
        s.commit()
    r = c.post(f"/tags/{sys_id}/dismiss")
    check("확정 섹션이어도 태그(매핑)는 고침 — M11 사실 잠금 풀림", "확정 후에는 고칠 수 없습니다" not in r.text and r.status_code == 200)


def t_dashboard_report(c) -> None:
    """블록이 보고서에서 조용히 빠지지 않게 — 지표 없는 대시보드 (2026-10-21, 사용자 D1 사례)."""
    import json as _json

    from sqlalchemy import select

    from app import models as m
    from app.db import SessionLocal
    from app.services import writing as w
    llm = _offline_llm()
    prompt = (Path(__file__).parent / "app" / "llm" / "prompts" / "extract_blocks.md").read_text(encoding="utf-8")
    check("추출 프롬프트에 규칙 문단이 남아 있음(근거·없는 내용 금지·대시보드 기준)",
          "메모에 없는 내용은 만들지 않는다" in prompt and "근거를 단다" in prompt and "dashboard 는 metrics" in prompt
          and "carried_block_ref" in prompt and prompt.index("규칙") < prompt.index("출력 형식"))
    wk, dept = "2026-W47", "D1"
    memo = "Sterntube 금속이물질 발견   SN2402,2510\n안전사고 예방 캠페인 실시 10/6~10/30\n"
    c.post(f"/write/{wk}/{dept}/memo", data={"raw_text": memo})
    with SessionLocal() as s:
        memo_id = w.latest_memos(s, w.get_section(s, wk, dept))[0].id

    def fake(task, system, user, timeout):     # 사용자 사례: 일정 줄을 지표 없는 대시보드로 분류한 응답
        return _json.dumps({"blocks": [
            {"block_type": "problem", "title": "Sterntube 금속이물질 발견", "body": "SN2402, SN2510 Sterntube 금속이물질", "status": "신규",
             "tags": [], "evidence": [{"line": 1, "quote": "Sterntube 금속이물질 발견"}]},
            {"block_type": "dashboard", "title": "안전사고 예방 캠페인 일정", "body": "캠페인 10/6~10/30", "metrics": [],
             "tags": [], "evidence": [{"line": 2, "quote": "안전사고 예방 캠페인 실시 10/6~10/30"}]}], "questions": []},
            ensure_ascii=False), "fake"
    llm.PROVIDERS["fake"] = fake
    saved = list(llm.settings.LLM_CHAIN)
    llm.settings.LLM_CHAIN[:] = ["fake"]
    try:
        r = c.post(f"/write/{wk}/{dept}/memo/{memo_id}/extract")
    finally:
        llm.settings.LLM_CHAIN[:] = saved
        llm.PROVIDERS.pop("fake")
    with SessionLocal() as s:
        types = sorted(b.block_type for b in w.section_blocks(s, w.get_section(s, wk, dept)))
    check("지표 없는 대시보드(AI) → 공유정보로 저장·알림", types == ["problem", "share"] and "지표 없는 대시보드 1개 → 공유정보" in r.text,
          repr(types))
    r = c.get(f"/metrics/{dept}")
    check("F16 — 지표는 블록 없이 지표 화면에서(대시보드 블록을 만들 필요 없음)", r.status_code == 200 and "+ 지표 추가" in r.text and "지표 칸 만들기" not in r.text)


def _offline_llm():
    """공급자 키를 비워 sola·upstage·openai 가 「미설정」으로 바로 넘어가게 한다(네트워크 없음)."""
    from app.llm import client as llm
    for k in ("LLM_SOLAR_API_URL", "LLM_SOLAR_API_KEY", "LLM_UPSTAGE_API_KEY", "LLM_OPENAI_API_KEY"):
        setattr(llm.ac, k, "")
    return llm


def t_llm() -> None:
    import json as _json

    from app.db import SessionLocal
    from app.models import LlmCallLog
    llm = _offline_llm()
    schema = _json.loads((Path(__file__).parent / "schema" / "extraction.schema.json").read_text(encoding="utf-8"))
    check("체인 기본값 = SOLA → Upstage → OpenAI → Mock", llm.settings.LLM_CHAIN == ["sola", "upstage", "openai", "mock"],
          repr(llm.settings.LLM_CHAIN))
    with SessionLocal() as s:
        r = llm.complete_json("extract_blocks", "sys", "user", schema, session=s)
        check("3단 모두 미설정 → Mock 으로 폴백 + 실패 사유 3개 누적",
              r.ok and r.provider == "mock" and len(r.errors) == 3 and all("미설정" in e for e in r.errors), repr(r.errors))
        calls = {"n": 0}

        def bad(task, system, user, timeout):
            calls["n"] += 1
            return '<think>생각</think>{"blocks": "아님", "questions": []}', "bad-model"
        llm.PROVIDERS["bad"] = bad
        r = llm.complete_json("extract_blocks", "sys", "user", schema, session=s, chain=["bad", "mock"])
        check("스키마 불일치 → 같은 공급자 2회 후 다음 공급자", r.provider == "mock" and calls["n"] == 2
              and "스키마 불일치" in r.errors[0], repr(r.errors))
        r = llm.complete_json("extract_blocks", "sys", "user", schema, session=s, chain=["bad"])
        check("전부 실패 → data 없음 + 사유", not r.ok and r.errors)
        llm.PROVIDERS.pop("bad")
        # 사내 Gemma 실측 형태: blocks[0] = 키 이름 배열, questions 없음 → 오류를 알려 준 재시도에서 바로잡으면 통과
        seen_users: list[str] = []
        good = _json.loads((Path(__file__).parent / "data" / "samples" / "mock_extraction.json").read_text(encoding="utf-8"))

        def gemma(task, system, user, timeout):
            seen_users.append(user)
            if len(seen_users) == 1:
                return '{"blocks": [["block_type", "type_confidence", "title"], {"block_type": "share"}]}', "gemma"
            return _json.dumps(good, ensure_ascii=False), "gemma"
        llm.PROVIDERS["gemma"] = gemma
        r = llm.complete_json("extract_blocks", "sys", "user", schema, session=s, chain=["gemma", "mock"])
        llm.PROVIDERS.pop("gemma")
        check("스키마 불일치 재시도 — 무엇이 틀렸는지 알려 주고 같은 공급자로 통과",
              r.provider == "gemma" and len(seen_users) == 2 and "blocks/0:" in seen_users[1] and "questions" in seen_users[1]
              and "[앞 응답 오류]" not in seen_users[0], repr(seen_users[-1][-160:]))
        prompt = (Path(__file__).parent / "app" / "llm" / "prompts" / "extract_blocks.md").read_text(encoding="utf-8")
        ex_json = _json.loads(prompt[prompt.index("출력:") + 3:])
        try:
            llm.jsonschema.validate(ex_json, schema)
            ex_ok = True
        except llm.jsonschema.ValidationError:
            ex_ok = False
        check("프롬프트 예시가 실제 값이 든 객체이고 스키마를 통과", ex_ok and isinstance(ex_json["blocks"][0], dict))
        check("think 태그·코드펜스 제거 후 파싱",
              llm.parse_json_text('<think>x</think>```json\n{"a": 1}\n```') == {"a": 1})
        s.flush()
        logs = s.query(LlmCallLog).all()
        check("호출 로그가 남는다(본문 컬럼 없음)", len(logs) >= 6 and not hasattr(LlmCallLog, "prompt"), str(len(logs)))
        s.rollback()


def t_write_flow(c) -> None:
    from sqlalchemy import select

    from app import models as m
    from app.db import SessionLocal
    from app.services import extract as ex
    from app.services import writing as w
    llm = _offline_llm()

    wk, dept = "2026-W42", "D3"
    memo_text = (Path(__file__).parent / "data" / "samples" / "memo_W42_dept3.txt").read_text(encoding="utf-8")
    memo_text_with_trailing = memo_text + "   \n"          # 원문 그대로 남는지 — 끝 공백까지
    r = c.post(f"/write/{wk}/{dept}/memo", data={"raw_text": "   "}, follow_redirects=False)
    check("빈 메모 → 저장 안 함 + 안내", r.status_code == 303 and "err=" in r.headers["location"])
    r = c.post(f"/write/{wk}/{dept}/memo", data={"raw_text": memo_text_with_trailing})
    check("메모 저장 → 작성 화면", r.status_code == 200 and "MEMO-" in r.text and "AI 정리" in r.text)
    with SessionLocal() as s:
        memo = s.scalars(select(m.Memo)).first()
        check("메모 원문 불변(끝 공백 포함)", memo.raw_text == memo_text_with_trailing)
        memo_id = memo.id

    r = c.post(f"/write/{wk}/{dept}/memo/{memo_id}/extract")
    body = r.text
    check("AI 정리(3단 → Mock) → 메모 화면에 「이 메모에서 나온 이슈」 4개(카드는 고를 때만)", r.status_code == 200
          and body.count('class="chip-link"') == 4 and body.count('class="block"') == 0
          and "AI 정리 완료 — Mock" in body and "사내 SOLA: 미설정" in body, f"status {r.status_code}")
    r = c.get(f"/write/{wk}/{dept}?block=ISS-2026-0001", follow_redirects=False)
    check("M13 — 옛 작성 주소 ?block=이슈 → 이슈 원장", r.status_code == 307 and r.headers["location"] == "/issues?id=ISS-2026-0001", r.headers.get("location", ""))
    body = c.get("/issues?id=ISS-2026-0001").text
    check("M12 — 이슈 원장에 근거·별칭 연결 표시(매핑 칸)", "근거 · 메모" in body and "← DG2" in body and 'id="attach"' in body)
    with SessionLocal() as s:
        qs_ = w.questions(s, [s.get(m.Block, "PRB-2026-0001")]).get("PRB-2026-0001", [])
    check("빈 칸 질문 — 문제점 원인 1개", len(qs_) == 1 and "원인이 확인됐나요" in qs_[0].text, repr([q.text for q in qs_]))

    with SessionLocal() as s:
        sec = w.get_section(s, wk, dept)
        blocks = w.section_blocks(s, sec)
        ids = [b.id for b in blocks]
        check("블록 ID 규칙 ISS/PRB/SHR/DSH-2026-NNNN", ids == ["ISS-2026-0001", "PRB-2026-0001",
              "SHR-2026-0001", "DSH-2026-0001"], repr(ids))
        tags = {(t.kind, t.raw_text): t.target_id for t in w.block_tags(s, "ISS-2026-0001")}
        check("태그 ID 는 별칭 사전으로 확정 (DG2 → EQ-SN2511-GE-02)", tags.get(("installed_equipment", "DG2")) == "EQ-SN2511-GE-02")
        spans = s.scalars(select(m.SourceSpan).where(m.SourceSpan.block_id == "ISS-2026-0001",
                                                     m.SourceSpan.field == "block")).all()
        check("source_span 위치가 원문과 일치", spans and memo_text_with_trailing[spans[0].start:spans[0].end] == spans[0].quote)
        from app.services import metrics as mt
        dash = s.get(m.Block, "DSH-2026-0001")
        got = {d.name: (mt.value_row(s, d.id, wk).value, d.unit) for d in mt.defs(s, dept)}
        check("대시보드 지표 → metric_def·metric_value (본문 아님)", got == {"시운전 항목 완료율": (74, "%"),
              "신규 펀치": (18, "건"), "미결 펀치": (41, "건")} and "74" not in dash.body, repr(got))
        n_tags = sum(1 for b in blocks for t in w.block_tags(s, b.id) if w.tag_needs_check(t))
        check("확인할 태그 3개(이슈 원장 매핑 칸에서 연결·확인)", n_tags == 3, str(n_tags))

        # 근거 검증 — quote 가 메모에 없으면 그 블록을 버린다
        lines = ex.memo_lines(memo_text)
        check("근거 검증 — 줄 범위·글자 그대로", ex._ev_ok({"line": 1, "quote": "DG2 배기온도"}, lines)
              and not ex._ev_ok({"line": 1, "quote": "없는 문장"}, lines) and not ex._ev_ok({"line": 99, "quote": "DG2"}, lines))

    r = c.post(f"/write/{wk}/{dept}/confirm", follow_redirects=False)
    check("M12 — 섹션 확정 동작 없음", r.status_code in (404, 405), str(r.status_code))

    # 사람 수정 → ai_field_log → 다시 정리해도 유지
    r = c.post("/blocks/ISS-2026-0001/edit", data={"block_type": "issue", "title": "DG2 배기온도 편차 (사람 수정)",
                                                    "status": "진행", "body": "사람이 쓴 본문"})
    with SessionLocal() as s:
        log = s.scalars(select(m.AiFieldLog).where(m.AiFieldLog.block_id == "ISS-2026-0001",
                                                   m.AiFieldLog.field == "title", m.AiFieldLog.human_value.is_not(None))).first()
        check("사람 수정 → ai_field_log(AI 값, 사람 값)", log is not None and log.ai_value == "SN2511 발전기 No.2 배기온도 편차"
              and log.human_value == "DG2 배기온도 편차 (사람 수정)")
    r = c.post(f"/write/{wk}/{dept}/memo/{memo_id}/extract")
    with SessionLocal() as s:
        b = s.get(m.Block, "ISS-2026-0001")
        check("다시 정리 — 사람 값 보존·새 블록 없음", b.title == "DG2 배기온도 편차 (사람 수정)" and b.body == "사람이 쓴 본문"
              and len(w.section_blocks(s, w.get_section(s, wk, dept))) == 4 and "사람이 고친 값 2칸 유지" in r.text, b.title)

    # 원문 수정 — 새 판으로 저장(옛 판 불변), 자동 재정리는 같은 블록을 이어받는다
    r = c.post(f"/write/{wk}/{dept}/memo/{memo_id}/revise", data={"raw_text": memo_text_with_trailing})
    check("원문 수정 — 바뀐 내용 없으면 거부", "바뀐 내용이 없습니다" in r.text)
    r = c.post(f"/write/{wk}/{dept}/memo/{memo_id}/revise", data={"raw_text": "  "})
    check("원문 수정 — 빈 내용 거부", "고친 원문이 비어 있습니다" in r.text)
    rev1_text = memo_text.replace("정비업체 일정 조율중", "정비업체 일정 조율 중, 금요일 확정") + "- 냉각수 압력 정상\n"
    r = c.post(f"/write/{wk}/{dept}/memo/{memo_id}/revise", data={"raw_text": rev1_text})
    with SessionLocal() as s:
        old = s.get(m.Memo, memo_id)
        rev1 = s.scalars(select(m.Memo).where(m.Memo.revises_id == memo_id)).first()
        sec = w.get_section(s, wk, dept)
        check("원문 수정 → 새 판(revises_id 연결)·옛 판 원문 불변", rev1 is not None and rev1.raw_text == rev1_text
              and old.raw_text == memo_text_with_trailing)
        b = s.get(m.Block, "ISS-2026-0001")
        n_blocks = len(w.section_blocks(s, sec))
        sp = s.scalars(select(m.SourceSpan).where(m.SourceSpan.block_id == "ISS-2026-0001", m.SourceSpan.field == "block")).first()
        check("수정본 자동 재정리 — 새 블록 없이 같은 ID 갱신·사람 값 유지",
              n_blocks == 4 and b.title == "DG2 배기온도 편차 (사람 수정)" and "새 블록 0" in r.text and "갱신 4" in r.text
              and "원문을 고쳤습니다" in r.text, f"{n_blocks} {b.title}")
        check("근거가 새 판 원문 위치를 가리킴", sp is not None and sp.memo_id == rev1.id and rev1_text[sp.start:sp.end] == sp.quote)
        check("화면 — 최신 판만·수정본 표시·이전 판 보기·새 메모 추가 구분",
              f'<span class="id">{rev1.id}</span>' in r.text and f"수정본 ← {memo_id}" in r.text and "이전 판 보기 (1)" in r.text
              and "메모 붙여넣기" in r.text and "원문 수정" in r.text and f'href="?memo={memo_id}#memo"' not in r.text)
        rev1_id = rev1.id
    r = c.post(f"/write/{wk}/{dept}/memo/{memo_id}/revise", data={"raw_text": rev1_text + "x"})
    check("옛 판은 고칠 수 없음 — 최신 판으로 안내", f"이미 {rev1_id} 로 고쳐졌습니다" in r.text)
    rev2_text = rev1_text.replace("- 선급 검사 일정 변경 : 2511 조타기 검사 10/21 → 10/23", "- 선급 일정은 추후 공지")
    r = c.post(f"/write/{wk}/{dept}/memo/{rev1_id}/revise", data={"raw_text": rev2_text})
    with SessionLocal() as s:
        check("줄을 바꿔 대응 블록이 없으면 지우지 않고 「그대로 둠」",
              "이전 판에서 나온 블록 1개는 그대로 둠(SHR-2026-0001)" in r.text and s.get(m.Block, "SHR-2026-0001") is not None
              and len(w.section_blocks(s, w.get_section(s, wk, dept))) == 4, r.text[:0])
    # 기존 DB 보강 — revises_id 열이 없던 DB 도 init 때 열이 생긴다
    import sqlite3
    import tempfile

    from sqlalchemy import create_engine

    from app.db import _add_missing_columns
    with tempfile.TemporaryDirectory() as td:
        dbf = Path(td) / "old.db"
        con = sqlite3.connect(dbf)
        con.execute("CREATE TABLE memo (id VARCHAR(24) PRIMARY KEY, section_id INTEGER, author_id INTEGER, raw_text TEXT, created_at DATETIME)")
        con.execute("CREATE TABLE photo_link (photo_id VARCHAR(16), block_id VARCHAR(24), role VARCHAR(8), order_no INTEGER)")
        con.execute("INSERT INTO photo_link VALUES ('PH-1', 'ISS-1', 'main', 0)")
        con.execute("CREATE TABLE block_tag (id INTEGER PRIMARY KEY, block_id VARCHAR(24), kind VARCHAR(32), target_id VARCHAR(48), raw_text VARCHAR(256), confidence FLOAT, confirmed BOOLEAN, confirmed_by INTEGER)")
        con.commit()
        con.close()
        eng = create_engine(f"sqlite:///{dbf}")
        _add_missing_columns(eng)
        _add_missing_columns(eng)                       # 두 번 불러도 문제없음
        with eng.connect() as conn:
            cols = [r_[1] for r_ in conn.exec_driver_sql("PRAGMA table_info(memo)")]
            pcols = [r_[1] for r_ in conn.exec_driver_sql("PRAGMA table_info(photo_link)")]
            prow = conn.exec_driver_sql("SELECT caption, note FROM photo_link").fetchone()
            tcols = [r_[1] for r_ in conn.exec_driver_sql("PRAGMA table_info(block_tag)")]
        eng.dispose()
        check("기존 DB 보강 — memo.revises_id 열 추가(비파괴·반복 안전)", "revises_id" in cols, repr(cols))
        check("기존 DB 보강 — photo_link.caption·note 열(기존 행은 빈 값)", {"caption", "note"} <= set(pcols)
              and tuple(prow) == ("", ""), repr(pcols))
        check("기존 DB 보강 — block_tag.dismissed 열", "dismissed" in tcols, repr(tcols))
    with tempfile.TemporaryDirectory() as td:
        dbf = Path(td) / "old_hull.db"
        con = sqlite3.connect(dbf)
        con.execute("CREATE TABLE hull (id VARCHAR(16) PRIMARY KEY, ship_type_id VARCHAR(32), owner_id VARCHAR(32), "
                    "sister_group_id VARCHAR(32), stage VARCHAR(32), delivery_date DATE)")
        con.execute("INSERT INTO hull (id, stage) VALUES ('SN2511', '시운전')")
        con.commit()
        con.close()
        eng = create_engine(f"sqlite:///{dbf}")
        _add_missing_columns(eng)
        with eng.connect() as conn:
            hcols = [r_[1] for r_ in conn.exec_driver_sql("PRAGMA table_info(hull)")]
            hrow = conn.exec_driver_sql("SELECT id, stage, source FROM hull").fetchone()
        eng.dispose()
        check("기존 DB 보강 — hull.title·dock·ship_class·source 열(기존 호선 유지)",
              {"title", "dock", "ship_class", "source"} <= set(hcols) and tuple(hrow) == ("SN2511", "시운전", None), repr(hcols))

    # 작성 화면 재배치(2026-10-21) — 메모 목록·메모 하나 열기·저장하고 AI 정리
    import io

    from sqlalchemy import func

    with SessionLocal() as s:
        cur_memo = w.latest_memos(s, w.get_section(s, wk, dept))[0].id
    r = c.get(f"/import?memo={cur_memo}")
    check("M13 가져오기 — 메모 하나: 원문 근거 줄·AI 다시 정리·원문 수정, 왼쪽 메모 목록",
          'class="memo-lines"' in r.text and 'id="L1"' in r.text and "AI 다시 정리" in r.text and "원문 수정" in r.text and f'?memo={cur_memo}' in r.text)
    check("M13 가져오기 — 메모에서 나온 이슈는 이슈 원장, 대시보드는 지표 화면 링크",
          'href="/issues?id=ISS-2026-0001"' in r.text and f'href="/metrics/{dept}"' in r.text)
    r = c.post("/blocks/SHR-2026-0001/edit", data={"block_type": "share", "title": "SN2511 조타기 선급 검사 10/21 → 10/23", "body": ""},
               follow_redirects=False)
    check("M12 — 블록 저장 뒤 이슈 원장의 그 이슈로", r.headers.get("location", "").startswith("/issues?id=SHR-2026-0001"), r.headers.get("location", ""))
    r = c.get(f"/write/{wk}/{dept}?memo=new")
    check("M13 — 옛 ?memo=new → 가져오기 메모 입구(저장하고 AI 정리 / 저장만)",
          "저장하고 AI 정리" in r.text and "저장만" in r.text and 'class="memo-lines"' not in r.text)
    with SessionLocal() as s:
        latest_id = w.latest_memos(s, w.get_section(s, wk, dept))[0].id
    r = c.get(f"/write/{wk}/{dept}?memo={memo_id}")
    check("재배치 — 옛 판 ID 로 열어도 최신 판이 열림", f'data-memo="{latest_id}"' in r.text and latest_id != memo_id)
    # 표 붙이기 — 이슈·문제점 블록
    from app.services import tables as tb_
    p1 = tb_.parse_paste("실린더\t배기온도\t편차\n1\t352\t-4\n\n3\t394\t+38\n")
    p2 = tb_.parse_paste("| 항목 | 값 |\n|---|---|\n| 압력 | 3.2 |")
    p3 = tb_.parse_paste("\n".join("\t".join(str(c_) for c_ in range(10)) for _ in range(25)))
    check("표 붙여넣기 파싱 — 탭·마크다운·크기 제한(20×8)",
          p1.rows == [["실린더", "배기온도", "편차"], ["1", "352", "-4"], ["3", "394", "+38"]]
          and p2.rows == [["항목", "값"], ["압력", "3.2"]]
          and (len(p3.rows), len(p3.rows[0]), p3.cut_rows, p3.cut_cols) == (20, 8, 5, 2), repr(p2.rows))
    tsv = "실린더\t배기온도(℃)\t편차\n1\t352\t-4\n3\t394\t+38"
    r = c.post("/blocks/PRB-2026-0001/tables", data={"title": "실린더 배기온도", "text": tsv})
    check("표 저장 → 카드에 표로 표시", "표를 붙였습니다 (2행 × 3열)" in r.text and "<th>배기온도(℃)</th>" in r.text
          and "<td>+38</td>" in r.text)
    r = c.post("/blocks/PRB-2026-0001/tables", data={"title": "", "text": "한 줄뿐"})
    check("표 — 두 줄 미만이면 거부", "표로 읽을 내용이 없습니다" in r.text)
    r = c.post("/blocks/DSH-2026-0001/tables", data={"title": "x", "text": tsv})
    check("표 — 대시보드 블록에는 거부(지표 표 안내)", "이슈·문제점 블록에만" in r.text)
    with SessionLocal() as s:
        tid = s.scalars(select(m.BlockTable).where(m.BlockTable.block_id == "PRB-2026-0001")).first().id
    r = c.get("/issues?id=PRB-2026-0001")
    check("M12 — 이슈 원장에 표가 보이고 고치기·추가 칸", "<td>+38</td>" in r.text and "표 고치기" in r.text and "표 추가" in r.text)
    r = c.post(f"/blocks/PRB-2026-0001/tables/{tid}/update", data={"title": "실린더 배기온도(수정)", "text": tsv + "\n4\t360\t+4"})
    check("표 고치기", "표를 고쳤습니다" in r.text and "<td>360</td>" in r.text and "실린더 배기온도(수정)" in r.text)
    r = c.post(f"/blocks/PRB-2026-0001/tables/{tid}/delete")
    with SessionLocal() as s:
        left_t = s.scalar(select(func.count()).select_from(m.BlockTable))
    check("표 지우기", "표를 지웠습니다" in r.text and left_t == 0, str(left_t))

    # 빈 칸 답 · 태그 확인 · 연결 → 확정
    r = c.post("/blocks/PRB-2026-0001/answer", data={"field": "cause", "value": "조사 중"})
    with SessionLocal() as s:
        sec = w.get_section(s, wk, dept)
        pending = [t for b in w.section_blocks(s, sec) for t in w.block_tags(s, b.id) if w.tag_needs_check(t)]
        pending_ids = [t.id for t in pending]
    for tid in pending_ids:
        r = c.post(f"/tags/{tid}/confirm", follow_redirects=False)
    check("M12 — 태그 확인 뒤 이슈 원장 매핑 칸으로", r.headers.get("location", "").startswith("/issues?id=") and r.headers["location"].endswith("#attach"))
    with SessionLocal() as s:          # 옛 확정 섹션(기록)이 남은 DB 를 흉내 낸다 — 이전 스크립트·사실 수정 검사가 쓴다
        sec_ = w.get_section(s, wk, dept)
        sec_.status = "확정"
        s.commit()
    r = c.post("/blocks/SHR-2026-0001/edit", data={"block_type": "share", "title": "바꿔 보기", "body": ""})
    with SessionLocal() as s:
        logged = s.scalar(select(m.AiFieldLog).where(m.AiFieldLog.block_id == "SHR-2026-0001", m.AiFieldLog.field == "title",
                                                     m.AiFieldLog.human_value == "바꿔 보기")) is not None
    check("M11 — 확정 섹션이어도 사실은 고침 + 수정 이력(ai_field_log)", "확정 후에는 고칠 수 없습니다" not in r.text and logged)
    with SessionLocal() as s:
        latest = w.latest_memos(s, w.get_section(s, wk, dept))[0].id
    r = c.post(f"/write/{wk}/{dept}/memo/{latest}/revise", data={"raw_text": "확정 뒤 고치기"})
    check("M12 — 옛 확정 섹션이어도 메모 원문은 새 판으로 고침(잠금 없음)", "확정 후에는 고칠 수 없습니다" not in r.text and "원문을 고쳤습니다" in r.text)
    r = c.post("/blocks/PRB-2026-0001/tables", data={"title": "x", "text": "a\tb\n1\t2"})
    check("M11 — 확정 섹션이어도 표 붙이기(사실) 됨", "확정 후에는 고칠 수 없습니다" not in r.text)
    r = c.get(f"/write/{wk}/D1")
    check("부서 바꾸기 — 부서 목록(확정 표시 없음)", r.status_code == 200 and "시운전1부" in r.text and "p-ok\">확정" not in r.text)

    # 사람이 대상을 고르면 별칭 사전에 추가된다 (다른 부서·새 메모로)
    c.post(f"/write/{wk}/D4/memo", data={"raw_text": "- 2511 2번 제너레이터 진동 큼"})
    with SessionLocal() as s:
        memo4 = s.scalars(select(m.Memo).order_by(m.Memo.id.desc())).first()
        sec4 = w.get_section(s, wk, "D4")
        b = m.Block(id="ISS-2026-0099", block_type="issue", title="발전기 진동", status="신규",
                    owner_department_id="D4", created_week_id=wk, origin="manual")
        s.add(b)
        s.add(m.SectionBlock(section_id=sec4.id, block_id=b.id, order_no=0))
        s.add(m.BlockTag(block_id=b.id, kind="hull", target_id="SN2511", raw_text="2511", confidence=0.9))
        t = m.BlockTag(block_id=b.id, kind="installed_equipment", raw_text="2번 제너레이터", confidence=0.4)
        s.add(t)
        s.commit()
        tid = t.id
    r = c.post(f"/tags/{tid}/link", data={"target_id": "EQ-SN2511-GE-02"})
    with SessionLocal() as s:
        a = s.scalars(select(m.Alias).where(m.Alias.text == "2번 제너레이터")).first()
        check("태그 연결 → 별칭 사전 추가(source=user, 호선 범위)", a is not None and a.source == "user"
              and a.scope_hull_id == "SN2511" and a.target_id == "EQ-SN2511-GE-02")
    from app.services import alias as alias_svc
    with SessionLocal() as s:
        check("추가된 별칭으로 다음부터 자동 연결", alias_svc.resolve(s, "2511 2번 제너레이터").target_id == "EQ-SN2511-GE-02")
    _ = llm, memo4


def t_sn() -> None:
    from sn_util import ensure_sn
    cases = {"2511": "SN2511", "S2511": "SN2511", "sn2511": "SN2511", " SN2511 ": "SN2511",
             None: "", float("nan"): "", "nan": "", "NaT": "", "None": "", "": "", "ABC": "ABC"}
    bad = {k: ensure_sn(k) for k, v in cases.items() if ensure_sn(k) != v}
    check("ensure_sn — 정상 변환 + NAN/NAT/NONE 유령 호선 차단", not bad, repr(bad))


def t_seed_and_alias() -> None:
    from sqlalchemy import func, select

    from app import models as m
    from app.db import SessionLocal
    from app.services import alias
    from app.services.seed import seed_masters

    with SessionLocal() as s:
        rep1 = seed_masters(s)
        n1 = {t.__tablename__: s.scalar(select(func.count()).select_from(t))
              for t in (m.Hull, m.InstalledEquipment, m.Alias, m.System, m.Department)}
        rep2 = seed_masters(s)      # 두 번째 실행 — 늘어나면 안 된다
        n2 = {t.__tablename__: s.scalar(select(func.count()).select_from(t))
              for t in (m.Hull, m.InstalledEquipment, m.Alias, m.System, m.Department)}
        check("시드 — 호선 8·탑재 장비 9·별칭 14·부서 8", n1 == {"hull": 8, "installed_equipment": 9,
              "alias": 14, "system": 7, "department": 8}, repr(n1))
        check("시드 — 다시 실행해도 중복 없음", n1 == n2, f"{n1} → {n2}")
        check("시드 — 경고 없음", not rep1.warnings and not rep2.warnings, repr(rep1.warnings))
        check("시드 — 호선 ID 가 전부 SN 형식",
              all(h.startswith("SN") for h in s.scalars(select(m.Hull.id))))

        eq2 = "EQ-SN2511-GE-02"
        for text in ("DG2", "D/G #2", "2번 발전기", "G/E No.2"):     # 로드맵 M1 완료 조건
            r = alias.resolve(s, text, hull_id="SN2511")
            check(f"별칭 '{text}' + 문맥 SN2511 → {eq2}", r.target_id == eq2 and r.via == "alias-hull",
                  f"{r.target_id} via {r.via}")
        r = alias.resolve(s, "2511 D/G #2")
        check("연결 표시는 입력과 같은 별칭 (← D/G #2)", r.alias_text == "D/G #2", repr(r.alias_text))
        r = alias.resolve(s, "DG2")
        check("별칭 'DG2' — 호선 문맥 없으면 미연결", not r.linked and r.hull_id is None, f"{r.target_id}")
        r = alias.resolve(s, "DG2", hull_id="SN2510")
        check("별칭 'DG2' — 다른 호선 범위 별칭은 쓰지 않는다", not r.linked, f"{r.target_id}")
        for text in ("2511 DG2", "SN2511 D/G #2", "H2511 2번 발전기", "s2511 G/E No.2"):
            r = alias.resolve(s, text)
            check(f"입력 속 호선 '{text}' → {eq2}", r.hull_id == "SN2511" and r.target_id == eq2,
                  f"{r.hull_id} {r.target_id}")
        r = alias.resolve(s, "GE2", hull_id="SN2510")
        check("패턴 GE2 + SN2510 → EQ-SN2510-GE-02", r.target_id == "EQ-SN2510-GE-02" and r.via == "pattern",
              f"{r.target_id} via {r.via}")
        r = alias.resolve(s, "씰")
        check("전역 별칭 '씰' → 부위 CP-CP-MSEAL", r.target_kind == "component" and r.target_id == "CP-CP-MSEAL")
        r = alias.resolve(s, "2599 DG2")
        check("기준정보에 없는 호선 → 호선 미확인·미연결", r.hull_id is None and not r.linked)
        r = alias.resolve(s, "eq-sn2511-ge-02")
        check("ID 를 그대로 입력 → 그 장비", r.target_id == eq2 and r.via == "id")

        # 충돌: 같은 표기가 같은 범위에서 다른 장비를 가리키면 고르지 않는다
        s.add(m.Alias(text="D/G 2", target_kind="installed_equipment", target_id="EQ-SN2511-GE-01",
                      scope_hull_id="SN2511", source="user"))
        s.flush()
        r = alias.resolve(s, "DG2", hull_id="SN2511")
        check("충돌 표기 → 미연결 + 후보 2개", r.conflict and not r.linked and len(r.candidates) == 2,
              f"{r.conflict} {r.candidates}")
        check("충돌 목록에 잡힌다", any(k == "DG2" for k, _, _ in alias.conflicts(s)))
        s.rollback()                # 시드 상태로 되돌린다


def t_masters_api(c) -> None:
    r = c.get("/api/masters/hull")
    check("API /api/masters/hull — 8행", r.status_code == 200 and len(r.json()) == 8, r.text[:120])
    r = c.get("/api/masters/installed_equipment/EQ-SN2511-GE-02")
    check("API 탑재 장비 1건", r.status_code == 200 and r.json().get("hull_id") == "SN2511")
    r = c.get("/api/masters/nope")
    check("API 없는 종류 → 404 + 가능한 값 안내", r.status_code == 404 and "hull" in r.text)
    r = c.get("/api/alias/resolve", params={"q": "2511 DG2"})
    j = r.json()
    check("API 별칭 확인 2511 DG2", r.status_code == 200 and j["linked"] and j["target_id"] == "EQ-SN2511-GE-02")
    r = c.get("/api/equipment/EQ-SN2511-GE-02/card")
    j = r.json()
    check("API 기준정보 카드 — 시스템 계층·자매선·별칭",
          j.get("system_path") == ["기관", "발전 시스템", "주발전기"]
          and j.get("sisters") == ["SN2510", "SN2511", "SN2512"] and "DG2" in j.get("aliases", []), repr(j)[:200])


def t_hub(c) -> None:
    r = c.get("/hub", params={"q": "2511 DG2"}, follow_redirects=False)
    check("장비 허브 찾기 2511 DG2 → 장비 화면으로 이동",
          r.status_code == 303 and r.headers["location"].startswith("/hub/equipment/EQ-SN2511-GE-02"),
          r.headers.get("location", ""))
    r = c.get(r.headers.get("location", "/hub"))
    body = r.text
    check("장비 화면 — 제목·연결 결과·기준정보 카드",
          r.status_code == 200 and "SN2511 발전기 No.2" in body and "별칭 사전으로 연결됨" in body
          and "기준정보" in body and "주발전기" in body and "LNG 운반선" in body, f"status {r.status_code}")
    check("장비 화면 — SN 중복 부착 없음", "SNSN" not in body)
    r = c.get("/hub", params={"q": "2599 DG2"})
    check("못 찾으면 호선·장비 미확인 표시", r.status_code == 200 and "호선 미확인" in r.text and "장비 미확인" in r.text)
    r = c.get("/hub", params={"q": ""})
    check("빈 입력 → 입력 안내", "찾을 장비 표기를 입력하세요" in r.text)
    r = c.get("/hub/equipment/EQ-NOPE")
    check("없는 장비 → 404 + 다시 찾는 법 안내", r.status_code == 404 and "현장 표기로" in r.text)


def t_carry(c) -> None:
    """M3 — W42 에 만든 이슈·문제점이 W43 섹션에 자동으로 올라오고 이력이 이어진다."""
    import json as _json

    from sqlalchemy import select

    from app import models as m
    from app.db import SessionLocal
    from app.services import carry_over as co
    from app.services import writing as w
    llm = _offline_llm()
    nxt, dept = "2026-W43", "D3"

    from app.services import studio as st_
    with SessionLocal() as s:                      # M13: 정기 회의를 볼 때(홈·이슈·회의) 이어받는다 — 두 번 불러도 중복 없어야 한다
        st_.ensure_week_meetings(s, nxt)
        st_.ensure_week_meetings(s, nxt)
        s.commit()
    with SessionLocal() as s:
        sec = w.get_section(s, nxt, dept)
        ids = [b.id for b in w.section_blocks(s, sec)] if sec else []
        check("이어받기 — 열린 이슈·문제점만 W43 으로 (공유정보·대시보드 제외)",
              ids == ["ISS-2026-0001", "PRB-2026-0001"], repr(ids))
        check("이어받기 — 같은 ID·carried_over 표시", all(x.carried_over for x in s.scalars(
            select(m.SectionBlock).where(m.SectionBlock.section_id == sec.id))))
        nb = m.Block(id="ISS-2026-0098", block_type="issue", title="이어받기 시험", status="신규", owner_department_id="D8",
                     created_week_id="2026-W42", origin="manual")
        s.add(nb)
        s.add(m.SectionBlock(section_id=w.get_section(s, "2026-W42", "D8", create=True).id, block_id=nb.id, order_no=0))
        s.flush()
        co.carry_over(s, nxt, "D8")
        check("이어받기 — 신규 → 진행 자동", s.get(m.Block, "ISS-2026-0098").status == "진행")
        s.rollback()
        hist = [(h.week_id, h.note) for h in co.history(s, "ISS-2026-0001")]
        check("이력 — W42 신규 등록 + W43 행", hist[0] == ("2026-W42", "신규 등록") and hist[-1][0] == nxt, repr(hist))
        check("이어온 항목 — 이번 주 한 줄 없음 2개(홈·이슈 원장 「한 줄 없음」)", sum(1 for b in co.carried_blocks(s, sec) if co.needs_line(s, b, nxt)) == 2)
    r = c.get("/issues", params={"dept": dept, "f": "line"})
    check("이슈 원장 「한 줄 없음」에 이어온 이슈", "PRB-2026-0001" in r.text)

    # 메모에 업데이트가 있으면 새 블록 대신 그 블록의 이번 주 한 줄로
    memo = "- 2514 카고펌프 No.3 메카니컬씰 교체 완료, 재시운전 예정"
    c.post(f"/write/{nxt}/{dept}/memo", data={"raw_text": memo})
    with SessionLocal() as s:
        memo_id = s.scalars(select(m.Memo).order_by(m.Memo.id.desc())).first().id

    def fake(task, system, user, timeout):
        assert "PRB-2026-0001" in user        # 이어온 블록 목록이 프롬프트에 들어간다
        return _json.dumps({"blocks": [{"block_type": "problem", "title": "카고펌프 씰", "body": "메카니컬씰 교체 완료, 재시운전 예정",
                                        "status": "진행", "carried_block_ref": "PRB-2026-0001", "tags": [],
                                        "evidence": [{"line": 1, "quote": "메카니컬씰 교체 완료"}]}], "questions": []}), "fake"
    llm.PROVIDERS["fake"] = fake
    saved = list(llm.settings.LLM_CHAIN)
    llm.settings.LLM_CHAIN[:] = ["fake"]
    try:
        r = c.post(f"/write/{nxt}/{dept}/memo/{memo_id}/extract")
    finally:
        llm.settings.LLM_CHAIN[:] = saved
        llm.PROVIDERS.pop("fake")
    with SessionLocal() as s:
        sec = w.get_section(s, nxt, dept)
        row = co.week_row(s, "PRB-2026-0001", nxt)
        check("메모 업데이트 매칭 — 새 블록 없이 이번 주 한 줄로", len(w.section_blocks(s, sec)) == 2
              and row is not None and "교체 완료" in row.note and "이어온 항목 업데이트 1" in r.text, row.note if row else "")

    r = c.post("/blocks/ISS-2026-0001/line", data={"text": ""}, follow_redirects=False)
    check("한 줄 빈칸 → 안내", "err=" in r.headers["location"])
    c.post("/blocks/ISS-2026-0001/line", data={"text": "밸브 입고 지연, 다음 주 교체"})
    with SessionLocal() as s:
        sec = w.get_section(s, nxt, dept)
        check("한 줄 저장 → 「한 줄 없음」에서 빠짐", not co.needs_line(s, s.get(m.Block, "ISS-2026-0001"), nxt))

    # 종결 요청 — 조치 내용 필수
    r = c.post("/blocks/PRB-2026-0001/close-request", data={"action_text": "  "})
    check("종결 요청 — 조치 내용 없으면 거부", "조치 내용을 적어야" in r.text)
    c.post("/blocks/PRB-2026-0001/close-request", data={"action_text": "메카니컬씰 교체, 누유 없음 확인"})
    with SessionLocal() as s:
        b = s.get(m.Block, "PRB-2026-0001")
        cl = s.scalars(select(m.Closure).where(m.Closure.block_id == b.id)).first()
        check("종결 요청 → 상태 종결요청 + closure(대기)", b.status == "종결요청" and cl and cl.decision == "대기"
              and cl.action_text.startswith("메카니컬씰"))

    # 이관 — ID 유지, 이력, 받는 부서 섹션으로
    r = c.post("/blocks/ISS-2026-0001/transfer", data={"to_dept": "D5"})
    with SessionLocal() as s:
        b = s.get(m.Block, "ISS-2026-0001")
        d3 = [x.id for x in w.section_blocks(s, w.get_section(s, nxt, "D3"))]
        d5 = [x.id for x in w.section_blocks(s, w.get_section(s, nxt, "D5"))]
        last = co.history(s, b.id)[-1]
        check("이관 — 담당 부서 변경·ID 그대로·섹션 이동", b.owner_department_id == "D5" and "ISS-2026-0001" in d5
              and "ISS-2026-0001" not in d3, f"{d3} {d5}")
        check("이관 — 이력에 「시운전1부 → 시운전3부 이관」", last.note == "시운전1부 → 시운전3부 이관" and last.department_id == "D5")
    r = c.post("/blocks/PRB-2026-0001/transfer", data={"to_dept": "D5"})
    with SessionLocal() as s:
        owner = s.get(m.Block, "PRB-2026-0001").owner_department_id
    check("종결 요청 중 블록 — 이관 버튼 없음 + 서버도 거부", 'action="/blocks/PRB-2026-0001/transfer"' not in r.text
          and "이관할 수 없습니다" in r.text and owner == "D3", owner)

    # 장기 미결 — 진행 상태로 N주(기본 4) 이상 업데이트 없음 → 표시만
    with SessionLocal() as s:
        b = s.get(m.Block, "ISS-2026-0099")
        b.status = "진행"
        s.flush()
        n45, n46 = co.long_open(s, b, "2026-W45"), co.long_open(s, b, "2026-W46")
        check("장기 미결 — W42 생성 → W45 아님 · W46 4주", n45 is None and n46 == 4, f"{n45} {n46}")
        s.rollback()


def t_photos(c) -> None:
    """M4 — 업로드(원본 불변·중복 방지)·주석 저장·마커·서버 합성·편집기 화면."""
    import hashlib
    import io

    from PIL import Image
    from sqlalchemy import func, select

    import path_config as pc
    from app import models as m
    from app.db import SessionLocal
    from app.services import writing as w

    vend = Path(__file__).parent / "app" / "static" / "vendor" / "konva.min.js"
    check("Konva vendor 사본(9.3.6) — CDN 없이", vend.exists() and vend.stat().st_size > 100_000
          and "v9.3.6" in vend.read_text(encoding="utf-8", errors="ignore")[:400])

    # EXIF 방향 6(시계 90°) — 저장된 원본은 400×300, 보이는 방향은 300×400
    raw = Image.new("RGB", (400, 300), (120, 140, 150))
    exif = Image.Exif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    raw.save(buf, format="JPEG", exif=exif, quality=90)
    jpg = buf.getvalue()
    blk = "ISS-2026-0001"                              # W43 · 시운전3부 (열린 섹션)
    r = c.post(f"/blocks/{blk}/photos", data={"role": "main"}, files={"file": ("a.jpg", jpg, "image/jpeg")})
    check("사진 업로드 → 블록에 연결", r.status_code == 200 and "PH-00001" in r.text and "마킹 편집" in r.text, r.text[-200:] if r.status_code != 200 else "")
    c.post(f"/blocks/{blk}/photos", data={"role": "before"}, files={"file": ("same.jpg", jpg, "image/jpeg")})
    r = c.post(f"/blocks/{blk}/photos", data={"role": "main"}, files={"file": ("x.txt", b"not image", "text/plain")},
               follow_redirects=False)
    check("사진이 아닌 파일 → 거부 + 안내", "err=" in r.headers.get("location", ""))
    with SessionLocal() as s:
        photos = s.scalars(select(m.Photo)).all()
        p = photos[0]
        path = pc.get_data_dir() / p.file_path
        n_files = len(list((pc.get_data_dir() / "photos").rglob("*.jpg")))
        check("같은 사진 두 번 → photo 1행·파일 1개(sha256)", len(photos) == 1 and n_files == 1, f"{len(photos)} {n_files}")
        check("보이는 방향 크기 저장(EXIF 적용 300×400)", (p.width, p.height) == (300, 400), f"{p.width}x{p.height}")
        links = s.scalar(select(func.count()).select_from(m.PhotoLink).where(m.PhotoLink.block_id == blk))
        check("조치 전 칸에도 같은 원본 연결", links == 2, str(links))
        pid_ = p.id
    r = c.post(f"/blocks/{blk}/photos/{pid_}/role", data={"role": "main", "to_role": "after"})
    with SessionLocal() as s:
        roles_ = sorted(x.role for x in s.scalars(select(m.PhotoLink).where(m.PhotoLink.block_id == blk)))
    check("사진 칸 옮기기(사진 → 조치 후) — 원본 그대로", roles_ == ["after", "before"] and "조치 후 칸으로 옮겼습니다" in r.text, repr(roles_))
    c.post(f"/blocks/{blk}/photos/{pid_}/role", data={"role": "after", "to_role": "main"})

    # 한 이슈 여러 장 — 같은 구분 여러 장·이름·설명·순서 (2026-10-21)
    from app.services import photos as ph

    def _jpg(rgb):
        b_ = io.BytesIO()
        Image.new("RGB", (320, 240), rgb).save(b_, format="JPEG")
        return b_.getvalue()
    c.post(f"/blocks/{blk}/photos", data={"role": "before"}, files={"file": ("b2.jpg", _jpg((200, 60, 60)), "image/jpeg")})
    r = c.post(f"/blocks/{blk}/photos", data={"role": "after"}, files={"file": ("a1.jpg", _jpg((60, 200, 60)), "image/jpeg")})
    with SessionLocal() as s:
        lk_ = [(x.photo_id, x.role) for x, _ in ph.block_photos(s, blk)]
    check("같은 구분 여러 장 — 조치 전 2장이 서로 바꾸지 않음", [r_ for _, r_ in lk_].count("before") == 2 and len(lk_) == 4, repr(lk_))
    after_id = next(pid for pid, r_ in lk_ if r_ == "after")
    r = c.post(f"/blocks/{blk}/photos/{after_id}/info", data={"role": "after", "to_role": "after",
                                                              "caption": "교체 후 씰 면", "note": "4시간 운전 후 누유 없음"})
    with SessionLocal() as s:
        row_ = s.get(m.PhotoLink, (after_id, blk, "after"))
    check("사진 이름·설명 저장 → 카드 캡션", row_.caption == "교체 후 씰 면" and row_.note == "4시간 운전 후 누유 없음"
          and "교체 후 씰 면" in r.text and "4시간 운전 후 누유 없음" in r.text)
    r = c.post(f"/blocks/{blk}/photos/{pid_}/info", data={"role": "main", "to_role": "before", "caption": "", "note": ""})
    check("같은 사진이 이미 그 구분에 있으면 거부", "이미 조치 전 구분에 있습니다" in r.text)
    r = c.post(f"/blocks/{blk}/photos/{after_id}/move", data={"role": "after", "dir": "up"})
    with SessionLocal() as s:
        order_ = [(x.photo_id, x.role) for x, _ in ph.block_photos(s, blk)]
    check("사진 순서 앞으로", order_.index((after_id, "after")) == 2 and "앞으로 옮겼습니다" in r.text, repr(order_))
    r = c.get(f"/photos/{after_id}/edit?block={blk}&role=after")
    check("편집기 — 사진 정보 폼·이전/다음 사진·선택/지우기/다시 실행 도구", r.status_code == 200 and 'id="pi-cap"' in r.text
          and "교체 후 씰 면" in r.text and "사진 3/4" in r.text and "이전 사진" in r.text and "다음 사진" in r.text
          and 'data-tool="select"' in r.text and 'id="redoBtn"' in r.text and 'id="clearBtn"' in r.text
          and 'id="saveBackBtn"' in r.text and 'id="cropApply"' in r.text)
    r = c.post(f"/blocks/{blk}/photos/{after_id}/info", data={"role": "after", "to_role": "after", "caption": "교체 후 씰 면",
                                                              "note": "4시간 운전 후 누유 없음", "back": "edit"}, follow_redirects=False)
    check("편집기에서 정보 저장 → 편집기로 돌아감", r.status_code == 303 and r.headers["location"].startswith(f"/photos/{after_id}/edit"))
    r = c.get(f"/issues?id={blk}&photo={after_id}-after")
    figs = r.text.count('data-ph="')
    check("이슈 사진 — 큰 사진 1장(나머지 숨김) + 썸네일 줄, ?photo= 로 고른 사진", figs == 4 and r.text.count("data-off") == 3
          and r.text.count('class="thumb"') == 4 and f'data-ph="{after_id}-after">' in r.text, str(figs))
    _wm = ph.WORK_MAX
    ph.WORK_MAX = 200                                   # 시험 사진(400×300)도 작업용 축소본을 쓰게
    r = c.get(f"/photos/{after_id}/edit?block={blk}&role=after")
    ph.WORK_MAX = _wm
    rw = c.get(f"/photos/{after_id}/render", params={"w": 200})
    check("편집기 — 큰 사진은 줄인 작업용 사진(JPEG)을 쓰고 좌표는 원본 크기", f"/photos/{after_id}/render?w=200" in r.text
          and '"width": 320' in r.text and rw.headers["content-type"] == "image/jpeg")
    with SessionLocal() as s:
        sha_before = hashlib.sha256(path.read_bytes()).hexdigest()

    doc = {"base": {"rotate": 90, "crop": [10, 20, 200, 300], "brightness": 0.1},
           "shapes": [{"type": "arrow", "points": [10, 10, 100, 100], "color": "#d4402a", "width": 4},
                      {"type": "circle", "x": 150, "y": 150, "r": 30, "color": "#f0b400", "width": 4},
                      {"type": "rect", "x": 20, "y": 20, "w": 60, "h": 40, "color": "#2f6fd6", "width": 4},
                      {"type": "free", "points": [5, 5, 30, 40, 60, 20], "color": "#d4402a", "width": 3},
                      {"type": "text", "x": 30, "y": 300, "text": "누유 지점", "size": 24, "color": "#d4402a"},
                      {"type": "mosaic", "x": 200, "y": 300, "w": 80, "h": 60},
                      {"type": "inset", "src": [140, 140, 40, 40], "dst": [200, 10, 90, 90], "color": "#d4402a", "width": 3}],
           "markers": [{"x": 150, "y": 150, "label": "씰 하우징", "component_id": "CP-GE-INJ"},
                       {"x": 60, "y": 260, "label": "", "component_id": None}]}   # 부위·설명 둘 다 없음 → 체크에 남음
    r = c.post("/api/photos/PH-00001/annotation", params={"block": blk}, json=doc)
    j = r.json()
    check("주석 저장 — 도형 7종·마커 2·부위·설명 없는 마커 1", r.status_code == 200 and j["ok"] and j["markers"] == 2
          and j["missing_part"] == 1, repr(j))
    bad = dict(doc, shapes=[{"type": "rect", "x": 1, "y": 1, "w": 5, "h": 5, "color": "#00ff00"}])
    r = c.post("/api/photos/PH-00001/annotation", params={"block": blk}, json=bad)
    check("허용하지 않은 색 → 400 + 안내", r.status_code == 400 and "빨강·노랑·파랑" in r.json()["error"])
    with SessionLocal() as s:
        mk = s.scalars(select(m.Marker).order_by(m.Marker.no)).all()
        check("marker 행 = 번호·좌표·부위", [(x.no, x.component_id) for x in mk] == [(1, "CP-GE-INJ"), (2, None)])
        check("마커 부위 미지정 1개(이슈 원장 사진 칸에서 보임)", ph.markers_missing_part(s, blk) == 1)
        check("원본 파일 불변(주석 저장 후 sha256 동일)", hashlib.sha256(path.read_bytes()).hexdigest() == sha_before)

    r = c.get("/photos/PH-00001/render", params={"block": blk})
    out = Image.open(io.BytesIO(r.content))
    check("서버 합성 — 자르기 200×300 후 회전 90° → 300×200 PNG", r.headers["content-type"] == "image/png"
          and out.size == (300, 200), str(out.size))
    r = c.get("/photos/PH-00001/render", params={"block": blk, "w": 150})
    check("합성 축소본(w=150)", Image.open(io.BytesIO(r.content)).size[0] == 150)
    r = c.get("/photos/PH-00001/original")
    check("원본 내려받기 = 올린 바이트 그대로", r.content == jpg)
    with SessionLocal() as s:
        check("합성 후에도 원본 불변", hashlib.sha256(path.read_bytes()).hexdigest() == sha_before)

    r = c.get("/photos/PH-00001/edit", params={"block": blk})
    check("편집기 화면 — Konva·도구·주석 데이터", r.status_code == 200 and "vendor/konva.min.js" in r.text
          and "확대 인셋" in r.text and "모자이크" in r.text and '"markers"' in r.text)
    r = c.get("/photos/PH-00001/edit", params={"block": "SHR-2026-0001"})
    check("연결 안 된 블록으로 편집기 → 404", r.status_code == 404)

    c.post(f"/blocks/{blk}/photos/PH-00001/unlink", data={"role": "before"})
    with SessionLocal() as s:
        left = s.scalar(select(func.count()).select_from(m.PhotoLink).where(m.PhotoLink.block_id == blk))
        check("떼기 → 연결만 지우고 원본·photo 행은 남김", left == 3 and path.exists() and s.get(m.Photo, "PH-00001") is not None)


def t_metrics(c) -> None:
    """M5 → F16 — 지표 정의·주차 값(블록 없이)·추이·평소 범위·차이 사유·숨기기·순서·사람 값 보호."""
    from sqlalchemy import select

    from app import models as m
    from app.db import SessionLocal
    from app.services import metrics as mt
    nxt, dept = "2026-W43", "D3"

    r = c.get(f"/metrics/{dept}", params={"week": nxt})
    check("F16 지표 화면 — 블록 없이 바로 표·6주 추이(W42 값 포함)", r.status_code == 200 and "6주 추이" in r.text
          and 'class="spark"' in r.text and "시운전 항목 완료율" in r.text and "지표 칸 만들기" not in r.text)
    with SessionLocal() as s:
        ids = {d.name: d.id for d in mt.defs(s, dept)}
    done, new, opn = ids["시운전 항목 완료율"], ids["신규 펀치"], ids["미결 펀치"]

    # 평소 범위 — 정의값(완료율 70~90) / 지난 값 평균 ± 2σ(미결 펀치)
    c.post(f"/metric-defs/{done}/update", data={"week_id": nxt, "unit": "%", "low": "70", "high": "90"})
    with SessionLocal() as s:
        for wid, v in (("2026-W38", 40), ("2026-W39", 42), ("2026-W40", 41), ("2026-W41", 43)):
            mt.set_value(s, s.get(m.MetricDef, opn), wid, v, human=True)
        s.commit()
    r = c.post(f"/metrics/{dept}/values", data={"week": nxt, f"v_{done}": "95", f"c_{done}": "시운전 막바지",
                                                f"v_{new}": "12", f"v_{opn}": "80"})
    check("지표 저장 → 바뀐 값 3개(블록 없이)", "바뀐 값 3개" in r.text)
    check("평소 범위 벗어남 표시(정의 범위·지난 값 범위 둘 다)", r.text.count("평소보다 높음") == 2, str(r.text.count("평소보다 높음")))
    body = r.text
    i0, i1 = body.index(f'data-metric="{opn}"'), body.index("</tr>", body.index(f'data-metric="{opn}"'))
    j0, j1 = body.index(f'data-metric="{done}"'), body.index("</tr>", body.index(f'data-metric="{done}"'))
    check("F16 — 이탈인데 사유가 비면 「사유를 적어주세요」, 코멘트가 있으면 없음",
          '<span class="pill p-issue needs">' in body[i0:i1] and '<span class="pill p-issue needs" hidden>' in body[j0:j1])
    check("막대 차트에 평소 범위 띠", 'fill="var(--ok-soft)"' in r.text)
    check("지표 표에 이번 주 값", f'id="v-{done}"' in r.text and 'value="95"' in r.text)
    with SessionLocal() as s:
        mv = mt.view(s, s.get(m.MetricDef, opn), nxt)
        check("6주 추이 = W38~W43 순서·값", mv.weeks[0] == "2026-W38" and mv.series == [40, 42, 41, 43, 41, 80],
              repr(mv.series))
        check("지난 값 범위 출처 표시(최근 n주, 처음 8주)", mv.range_src == "최근 5주 값" and mv.flag == "높음" and mv.needs_note
              and mt.range_weeks(s) == 8, mv.range_src)
        d = s.get(m.MetricDef, done)
        changed = mt.set_value(s, d, nxt, 50, block_id=None, human=False)
        check("F16 — 화면에서 넣은 사람 값은 AI 가 덮지 않는다(블록 없이도)", not changed and mt.value_row(s, done, nxt).value == 95)
        s.rollback()
        miss = mt.missing(s, dept, nxt)
    check("F16 — 이번 주 미입력 지표 목록(모두 넣었으면 0)", miss == [], repr(miss))
    r = c.post("/settings/metrics", data={"range_weeks": "2"}, follow_redirects=False)
    check("F16 — 평소 범위 기간 3주 미만 → 거부", "3~52" in unquote(r.headers["location"]))
    r = c.post("/settings/metrics", data={"range_weeks": "3"}, follow_redirects=False)
    with SessionLocal() as s:
        mv3 = mt.view(s, s.get(m.MetricDef, opn), nxt)
    check("F16 — 평소 범위 기간 3주로 → 최근 3주 값으로 판단", "바꿨습니다" in unquote(r.headers["location"])
          and mv3.range_src == "최근 3주 값" and mt.range_weeks(SessionLocal()) == 3, mv3.range_src)
    r = c.get("/settings")
    check("F16 — 설정 화면 평소 범위 기간 칸", 'name="range_weeks" value="3"' in r.text)
    c.post("/settings/metrics", data={"range_weeks": "8"})

    r = c.post(f"/metrics/{dept}/defs", data={"name": "신규  펀치", "unit": "건", "week": nxt}, follow_redirects=False)
    check("같은 이름 지표 추가 → 거부", "err=" in r.headers["location"])
    r = c.post(f"/metric-defs/{opn}/delete", data={"week_id": nxt}, follow_redirects=False)
    check("값이 쌓인 지표 지우기 → 거부(추이 보호)", "err=" in r.headers["location"])
    c.post(f"/metrics/{dept}/defs", data={"name": "안전 점검", "unit": "회", "week": nxt})
    with SessionLocal() as s:
        sid = next(d.id for d in mt.defs(s, dept) if d.name == "안전 점검")
    r = c.get("/home", params={"role": "d", "dept": dept})
    check("F16 — 홈(부서 편집자) 「이번 주 지표 미입력」", "이번 주 지표 미입력 1" in r.text and f"/metrics/{dept}" in r.text)
    c.post(f"/metric-defs/{sid}/move", data={"step": "-1", "week_id": nxt})
    with SessionLocal() as s:
        names = [d.name for d in mt.defs(s, dept)]
    check("F16 — 지표 순서 위로", names.index("안전 점검") == len(names) - 2, repr(names))
    c.post(f"/metric-defs/{opn}/hide", data={"hidden": "1", "week_id": nxt})
    r = c.get(f"/metrics/{dept}", params={"week": nxt})
    with SessionLocal() as s:
        kept = mt.value_row(s, opn, nxt).value
    check("F16 — 숨기기: 표에서 빠지고 값은 남음·다시 보이기", f'data-metric="{opn}"' not in r.text and "(숨김)" in r.text and kept == 80)
    c.post(f"/metric-defs/{opn}/hide", data={"hidden": "0", "week_id": nxt})
    r = c.post(f"/metric-defs/{sid}/delete", data={"week_id": nxt}, follow_redirects=False)
    check("값 없는 지표는 지울 수 있다", "msg=" in r.headers["location"])
    # 기간 표 — 행 이름 자유(1과·2과), 날짜 × 계획/실적, 차이 사유
    r = c.post(f"/metrics/{dept}/tables", data={"name": "특근 인원", "unit": "명", "start": "2026-10-19", "end": "2026-10-23",
                                                "rows": "1과\n2과, 2과\n작업조 A", "week": nxt}, follow_redirects=False)
    with SessionLocal() as s:
        t = s.scalars(select(m.MetricTable).where(m.MetricTable.department_id == dept)).first()
        tid, rows_ = t.id, __import__("json").loads(t.rows_json)
    check("F16 기간 표 — 만들기(행 이름 자유·중복 제거)", rows_ == ["1과", "2과", "작업조 A"] and "msg=" in r.headers["location"], repr(rows_))
    r = c.post(f"/metrics/{dept}/tables", data={"name": "x", "start": "2026-10-01", "end": "2026-12-31", "rows": "a", "week": nxt})
    check("F16 기간 표 — 62일 넘으면 거부", "62일까지" in r.text)
    r = c.post(f"/metric-tables/{tid}/cells", data={"week": nxt, "p_0_20261019": "3", "a_0_20261019": "5", "p_1_20261020": "2", "a_1_20261020": "2",
                                                     "n_0": "", "n_1": ""})
    with SessionLocal() as s:
        tv = mt.table_view(s, s.get(m.MetricTable, tid))
    r0, r1 = tv["rows"][0], tv["rows"][1]
    check("F16 기간 표 — 계획/실적 저장·행 합계·차이", "바뀐 칸 2개" in r.text and (r0["plan"], r0["actual"], r0["diff"]) == (3, 5, 2) and r1["diff"] == 0
          and tv["plan"] == 5 and tv["actual"] == 7, repr((r0["plan"], r0["actual"], r0["diff"])))
    check("F16 기간 표 — 차이가 있는데 사유가 비면 표시", r0["needs_note"] and not r1["needs_note"] and 'class="needs-in"' in r.text)
    c.post(f"/metric-tables/{tid}/cells", data={"week": nxt, "n_0": "선주 검사 대응 추가 투입"})
    with SessionLocal() as s:
        tv = mt.table_view(s, s.get(m.MetricTable, tid))
    check("F16 기간 표 — 사유 저장 → 표시 사라짐", tv["rows"][0]["note"] == "선주 검사 대응 추가 투입" and not tv["rows"][0]["needs_note"])
    r = c.post(f"/metric-tables/{tid}/delete", data={"week": nxt})
    check("F16 기간 표 — 값이 있으면 지우지 못하고 숨기기 안내", "숨기기를 쓰세요" in r.text)
    r = c.get("/static/js/metrics.js")
    check("즉시 갱신 스크립트 서빙(추이·기간 표 합계)", r.status_code == 200 and "sparkSvg" in r.text and "data-prow" in r.text)
    check("SVG 좌표 규칙 — 서버 막대 폭", mt.bar_svg(["W1"], [1.0]).count("<rect") == 1)


def t_meeting(c) -> None:
    """M6 → M12 — 종결 승인 → 사례 카드·보류(기획 주관자 홈)·회의 중 등록·회의록 추출(진행 화면 API)."""
    from sqlalchemy import select

    from app import models as m
    from app.db import SessionLocal
    from app.services import carry_over as co
    from app.services import studio as st
    from app.services import writing as w
    _offline_llm()
    wk = "2026-W43"
    with SessionLocal() as s:
        st.ensure_week_meetings(s, wk)
        s.commit()
        share_id = st.week_meeting(s, wk, "share").id

    r = c.get("/home", params={"role": "p"})
    check("홈(기획) — 종결 요청 PRB-2026-0001 승인·보류 버튼", r.status_code == 200 and "PRB-2026-0001" in r.text and "/approve" in r.text and "보류" in r.text)

    # 승인 → 사례 카드 (원인 태그 「조사 중」 + 조치 내용)
    with SessionLocal() as s:
        cid = s.scalars(select(m.Closure.id).where(m.Closure.block_id == "PRB-2026-0001")).first()
    r = c.post(f"/closures/{cid}/approve", data={})
    with SessionLocal() as s:
        card = s.scalars(select(m.CaseCard).where(m.CaseCard.block_id == "PRB-2026-0001")).first()
        b = s.get(m.Block, "PRB-2026-0001")
        cl = s.get(m.Closure, cid)
        check("종결 승인 → 사례 카드(증상·원인·조치)", card is not None and card.id == "CASE-0001"
              and card.cause_text == "조사 중" and card.action_text.startswith("메카니컬씰")
              and card.installed_equipment_id == "EQ-SN2514-CP-03", repr(card and (card.symptom_text, card.cause_text)))
        check("승인 → 블록 종결·closure 승인·이력", b.status == "종결" and cl.decision == "승인"
              and co.history(s, b.id)[-1].note.startswith("회의 종결 승인"))
    check("승인 뒤 홈으로 · 안내", "사례 카드 CASE-0001" in r.text)
    r = c.post(f"/closures/{cid}/approve", data={}, follow_redirects=False)
    check("같은 요청 두 번 승인 → 거부", "err=" in r.headers["location"])
    r = c.get("/knowledge")
    check("지식창고에 사례 카드가 나타난다", "CASE-0001" in r.text and "조사 중" in r.text and "메카니컬씰" in r.text)

    # 원인이 없으면 승인 실패 → 원인을 적으면 승인(이슈의 원인 칸도 쓴다)
    c.post("/blocks/ISS-2026-0001/close-request", data={"action_text": "연료분사밸브 교체 후 편차 해소"})
    with SessionLocal() as s:
        cid2 = s.scalars(select(m.Closure.id).where(m.Closure.block_id == "ISS-2026-0001")).first()
        s.get(m.Block, "ISS-2026-0001").cause_text = ""
        s.commit()
    r = c.post(f"/closures/{cid2}/approve", data={})
    check("원인 없으면 승인 실패 + 안내", "원인이 없어 사례 카드를 만들 수 없습니다" in r.text)
    c.post(f"/closures/{cid2}/approve", data={"cause_text": "분사밸브 노즐 막힘"})
    with SessionLocal() as s:
        card2 = s.scalars(select(m.CaseCard).where(m.CaseCard.block_id == "ISS-2026-0001")).first()
        check("적은 원인으로 승인 → 사례 카드·원인 태그", card2 is not None and card2.cause_text == "분사밸브 노즐 막힘"
              and any(t.kind == "cause" and t.raw_text == "분사밸브 노즐 막힘" for t in w.block_tags(s, "ISS-2026-0001")))

    # 보류 → 진행으로
    c.post("/blocks/ISS-2026-0099/close-request", data={"action_text": "진동 측정 재실시"})
    with SessionLocal() as s:
        cid3 = s.scalars(select(m.Closure.id).where(m.Closure.block_id == "ISS-2026-0099")).first()
    c.post(f"/closures/{cid3}/hold", data={"reason": "측정 데이터 부족"})
    with SessionLocal() as s:
        b = s.get(m.Block, "ISS-2026-0099")
        check("보류 → 블록 진행·closure 보류·이력 사유", b.status == "진행" and s.get(m.Closure, cid3).decision == "보류"
              and co.history(s, b.id)[-1].note == "회의 보류 — 측정 데이터 부족")

    # 회의 중 바로 등록 → 다음 주 그 부서 회의자료 후보
    r = c.post(f"/api/run/{share_id}/register", json={"title": "SN2512 발전기 No.1 기동 지연 확인", "dept_id": "D2"})
    with SessionLocal() as s:
        reg = s.scalars(select(m.Block).where(m.Block.origin == "meeting")).first()
        check("회의 중 등록 → origin=meeting 블록", r.json().get("ok") is not False and reg is not None and reg.owner_department_id == "D2"
              and reg.created_week_id == wk, r.text[:200])
        reg_id = reg.id
        st.ensure_week_meetings(s, "2026-W44")
        s.commit()
        nxt = st.week_meeting(s, "2026-W44", "dept", "D2")
        cand = {b_.id for _, bs in st.candidates(s, nxt) for b_ in bs}
    check("다음 주(W44) 시운전기술 회의자료 후보에 등장", reg_id in cand)

    # 회의록 추출 (3단 → Mock)
    minutes = (Path(__file__).parent / "data" / "samples" / "minutes_W42.txt").read_text(encoding="utf-8")
    j = c.post(f"/api/run/{share_id}/minutes", json={"raw_text": minutes}).json()
    titles = [x["title"] for x in j.get("candidates", [])]
    check("회의록 추출 → 후보 2건(Mock)", j.get("added") == 2 and "동일 모델 카고펌프 타 호선 점검" in titles
          and any(x["link"] == "ISS-2026-0001" for x in j["candidates"]), repr(j)[:200])
    j = c.post(f"/api/run/{share_id}/minutes", json={"raw_text": "전혀 다른 회의 내용"}).json()
    check("근거가 맞지 않는 후보는 버림", j.get("added") == 0 and len(j.get("dropped", [])) == 2, repr(j)[:200])
    with SessionLocal() as s:
        cands = s.scalars(select(m.MeetingCandidate).order_by(m.MeetingCandidate.id)).all()
        new_c, link_c = cands[0].id, cands[1].id
        check("후보 부서 힌트(줄임말 「3부」) → 시운전3부", cands[0].suggested_department_id == "D5")
        from app.services import departments as dp
        abbr = {"시운전3부에서": "D5", "2부가": "D4", "해운": "D6", "기술팀": "D2", "시운전기술부": "D2",
                "기획": "D1", "의장": "D7", "실증랩": "D8", "친환경 실증 Lab": "D8", "COM1": "D3",
                "시운전": None, "전": None, "기계팀": None}
        got = {k: dp.resolve(s, k) for k in abbr}
        check("부서 줄임말 연결 — 한 부서로 좁혀질 때만", got == abbr, repr({k: v for k, v in got.items() if v != abbr[k]}))
        lines_ = {"동일 모델 점검 필요. 3부에서 확인하기로.": "D5", "실증랩이 시료 채취": "D8",
                  "기술 검토 필요, 내부 일정 조율": None, "해운부와 안벽의장그룹 협의": None}
        got = {k: dp.find_in_text(s, k) for k in lines_}
        check("메모 줄에서 부서 찾기 — …부·팀·Lab 낱말만, 둘이면 안 고름", got == lines_, repr(got))
    c.post(f"/api/run/{share_id}/candidates/{link_c}/link", json={"block_id": "ISS-2026-0001"})
    c.post(f"/api/run/{share_id}/candidates/{new_c}/register", json={"title": "동일 모델 카고펌프 타 호선 점검", "dept_id": "D5"})
    with SessionLocal() as s:
        last = co.history(s, "ISS-2026-0001")[-2:]
        check("후보 연결 → 그 블록 이력에 「회의: …」", any(h.note.startswith("회의: 발전기 배기온도") for h in last), repr([h.note for h in last]))
        cs = {x.id: (x.state, x.linked_block_id) for x in s.scalars(select(m.MeetingCandidate))}
        check("후보 등록 → 새 블록·상태 등록", cs[new_c][0] == "등록" and cs[new_c][1] and cs[link_c] == ("연결", "ISS-2026-0001"))
    r = c.post(f"/api/run/{share_id}/candidates/{new_c}/drop", json={})
    check("처리한 후보 다시 처리 → 거부", r.status_code == 400 and "이미 처리한 후보" in r.json()["err"])


def t_export(c) -> None:
    """M7 → M12 — 회의자료 PPT(build_meeting): 16:9·사진 강조 장에 마킹 합성 그림·내려받기 사본·원본 사진 불변."""
    import hashlib
    import io

    from pptx import Presentation
    from sqlalchemy import select

    import path_config as pc
    from app import models as m
    from app.db import SessionLocal

    wk = "2026-W43"
    r = c.post(f"/meetings/{wk}/adhoc", data={"kind": "review"}, follow_redirects=False)
    rid = int(r.headers["location"].rsplit("/", 1)[1])
    with SessionLocal() as s:
        pb_id = s.scalars(select(m.PhotoLink.block_id).order_by(m.PhotoLink.block_id)).first()
    j = c.post(f"/api/studio/{rid}/items", json={"block_id": pb_id}).json()
    c.post(f"/api/studio/items/{j['item_id']}", json={"field": "form", "value": "photo"})
    r = c.get(f"/export/meeting/{rid}/pptx")
    check("회의자료 PPT 내려받기", r.status_code == 200 and r.headers["content-type"].startswith(
          "application/vnd.openxmlformats-officedocument.presentationml") and "filename*=UTF-8''" in r.headers["content-disposition"])
    prs = Presentation(io.BytesIO(r.content))
    slides = list(prs.slides)
    check("16:9 · 표지 + 장", round(prs.slide_width / prs.slide_height, 2) == 1.78 and len(slides) == 2)
    check("사진 강조 장 — 마킹 합성 그림(편집 가능한 PPT 그림)", any(sh.shape_type == 13 for sh in slides[1].shapes))
    check("내려준 파일 사본을 exports/<주차>/ 에 남김", any((pc.get_export_dir() / wk).glob("*.pptx")))
    with SessionLocal() as s:
        p = s.get(m.Photo, "PH-00001")
        orig = (pc.get_data_dir() / p.file_path).read_bytes()
    check("원본 사진 불변(PPT 를 만든 뒤에도 sha256 = DB 값)", hashlib.sha256(orig).hexdigest() == p.sha256)
    r = c.get(f"/export/{wk}/pptx")
    check("M12 — 옛 합본 PPT 주소 없음", r.status_code == 404)


def t_knowledge(c) -> None:
    """M8 — 검색·필터·인용 답변·장비 허브 전체·작성 중 유사 사례. 완료 기준 질문에 근거 사례로 답한다."""
    import json as _json

    from sqlalchemy import select

    from app import models as m
    from app.db import SessionLocal
    from app.services import answer as ans
    from app.services import demo
    from app.services import knowledge as kn
    llm = _offline_llm()

    with SessionLocal() as s:
        r1 = demo.seed_demo_cases(s)
        r2 = demo.seed_demo_cases(s)
    check("데모 사례 시드 — 4건+진행 1건, 다시 실행해도 중복 없음", r1 == {"cases": 4, "open": 1} and r2 == {"cases": 0, "open": 0}, f"{r1} {r2}")

    question = "LNGC 발전기 배기온도 편차 조치 이력"
    check("낱말 — 불용어(조치·이력) 제거", kn.tokens(question) == ["LNGC", "발전기", "배기온도", "편차"], repr(kn.tokens(question)))
    check("낱말 — 조사 떼기", kn.tokens("발전기의 배기온도를") == ["발전기", "배기온도"])
    with SessionLocal() as s:
        res = kn.search(s, question)
        ids = [d.key for d in res.cases]
        check("완료 기준 질문 → LNGC 발전기 배기온도 사례가 앞에", set(ids[:4]) >= {"CASE-0298", "CASE-0311", "CASE-0287"}
              and "CASE-0001" not in ids[:4], repr(ids))
        a = ans.ask(s, question, res.cases)
        check("인용 답변 — 근거 사례만 인용", a.ok and set(a.citations) <= set(ids[:ans.TOP_K]) and "[CASE-0311]" in a.text, a.problem or a.text[:80])
        r = kn.search(s, "DG 배기온도")
        check("별칭 넓히기 — 「DG」 → 발전기", any(d.key == "CASE-0311" for d in r.cases))
        r = kn.search(s, "", filters={"hull": "SN2433"})
        check("필터 호선 SN2433 → 그 호선 사례만", {d.key for d in r.results if d.kind == "case"} == {"CASE-0311", "CASE-0352"},
              repr([d.key for d in r.results]))
        r = kn.search(s, "배기온도")
        check("필터 개수 — 선종 LNG 운반선", dict(r.facets["ship_type"]).get("LNG 운반선", 0) >= 4, repr(r.facets["ship_type"]))
        r = kn.search(s, "연료분사밸브", kind="photo")
        check("사진 검색 — 마커 부위(연료분사밸브)", r.counts["photo"] >= 1 and all(d.kind == "photo" for d in r.results))
        r = kn.search(s, "", period="8", now_week="2026-W43")
        check("기간 — 최근 8주(2025 사례 제외)", "CASE-0311" not in {d.key for d in r.results})

        # 근거 밖 인용은 보여주지 않는다
        def liar(task, system, user, timeout):
            return _json.dumps({"answer": "원인은 밸브입니다 [CASE-9999]", "citations": ["CASE-9999"]}), "liar"
        llm.PROVIDERS["liar"] = liar
        saved = list(llm.settings.LLM_CHAIN)
        llm.settings.LLM_CHAIN[:] = ["liar"]
        try:
            bad = ans.ask(s, question, res.cases)
        finally:
            llm.settings.LLM_CHAIN[:] = saved
            llm.PROVIDERS.pop("liar")
        check("근거 목록 밖 사례 인용 → 답 숨김", not bad.ok and "CASE-9999" in bad.problem, bad.problem)
        empty = ans.ask(s, "아무것도 없는 질문", [])
        check("맞는 사례가 없으면 답하지 않음", not empty.ok and "사례가 없어" in empty.problem)
        s.rollback()

    r = c.get("/knowledge", params={"q": question})
    check("M13 — 「찾기」는 검색만(AI 요약 없음)·「질문하기」 버튼", r.status_code == 200 and "AI 요약" not in r.text and "질문하기" in r.text and "CASE-0311" in r.text)
    r = c.get("/knowledge", params={"q": question, "ask": "1"})
    check("지식창고 화면 — 질문하기 → AI 요약·인용 링크·사례 카드", r.status_code == 200 and "AI 요약 · 사례" in r.text
          and 'class="cite"' in r.text and "CASE-0311" in r.text and "연료분사밸브 노즐 마모" in r.text)
    r = c.get("/knowledge", params={"q": question, "case": "CASE-0311"})
    check("사례 선택 → 이력 타임라인(부서 이관 포함)", 'id="detail"' in r.text and "시운전1부 → 시운전3부 이관" in r.text)
    r = c.get("/knowledge", params={"kind": "share"})
    check("종류 — 공유정보", "SHR-2026-0001" in r.text and "CASE-0311" not in r.text)

    # 장비 허브 전체
    r = c.get("/hub/equipment/EQ-SN2511-GE-02")
    t = r.text
    check("허브 — 연결 지도(노드 9)", r.status_code == 200 and t.count('class="node ') == 9 and "n-center" in t)
    check("허브 — 자매선 같은 위치 선행 사례 알림(SN2510 · CASE-0298)", "선행 사례" in t and "SN2510" in t and "CASE-0298" in t)
    check("허브 — 동일 모델 표(자매선·같은 위치 강조, SN2512 진행)", 'class="sister"' in t and "같은 위치" in t and "기동 실패" in t)
    check("허브 — 원인 순위 1위 연료분사밸브 불량", "주요 원인 1위" in t and t.index("연료분사밸브 불량") < t.index("센서 오차"))
    check("허브 — 이 장비의 이력(ISS-2026-0001)", "이 장비의 이력" in t and "ISS-2026-0001" in t)
    check("허브 — 부위별 사진(마커 부위 연료분사밸브)", "부위별 사진" in t and "<b>연료분사밸브</b>" in t)
    with SessionLocal() as s:
        rank = kn.cause_ranking(s, "EM-GE6L")
        check("원인 순위 — 코드 이름으로 묶음", rank[0] == ("연료분사밸브 불량", 3), repr(rank))

    # 작성 중 유사 사례 (기능 10)
    with SessionLocal() as s:
        b = s.scalars(select(m.Block).where(m.Block.origin == "meeting", m.Block.owner_department_id == "D2")).first()
        s.add(m.BlockTag(block_id=b.id, kind="installed_equipment", target_id="EQ-SN2512-GE-01", raw_text="DG1", confirmed=True))
        s.add(m.BlockTag(block_id=b.id, kind="symptom", target_id="SY-EXH-DEV", raw_text="배기온도 편차", confirmed=True))
        s.commit()
        bid = b.id
        sim = kn.similar_cases(s, bid)
        check("유사 사례 — 같은 모델·자매선·같은 증상 순", sim and sim[0]["c"].id == "CASE-0298" and sim[0]["sister"], repr([(x["c"].id, x["why"]) for x in sim]))
    r = c.get("/issues", params={"id": bid})
    check("M12 이슈 원장 — 유사 사례 패널·자매선 표시", 'id="similar"' in r.text and "CASE-0298" in r.text and "자매선" in r.text)


def t_settings(c) -> None:
    """설정 화면 — 부서 이름·순서 고치기(ID 유지), 빈 이름·중복 거부."""
    from app.db import SessionLocal
    from app.models import Department
    from app.services import weeks
    r = c.get("/settings")
    check("설정 화면 — 탭 「설정」·부서 표·호선 연계", r.status_code == 200 and 'href="/settings" aria-current="page"' in r.text
          and "부서 저장" in r.text and "지금 다시 읽기" in r.text, f"status {r.status_code}")
    with SessionLocal() as s:
        rows = [(d.id, d.name, d.code, d.order_no) for d in s.query(Department).order_by(Department.order_no)]

    def post(rows_, new=("", "", "")):
        all_ = list(rows_) + [("", new[0], new[1], new[2] or "999")]
        data = {k: [str(r_[i]) for r_ in all_] for i, k in enumerate(("id", "name", "code", "order_no"))}
        return c.post("/settings/departments", data=data, follow_redirects=True)

    r = post([(rows[0][0], "", rows[0][2], rows[0][3])] + rows[1:])
    check("부서 — 빈 이름 거부·무엇을 고칠지 안내", "저장하지 않았습니다" in r.text and "부서 이름이 비어 있습니다" in r.text,
          f"{r.status_code} {r.text[r.text.find('<main>'):][:300]!r}")
    r = post([(rows[0][0], rows[1][1], rows[0][2], rows[0][3])] + rows[1:])
    check("부서 — 중복 이름 거부", "이름이 다른 부서와 같습니다" in r.text)
    with SessionLocal() as s:
        check("거부하면 아무것도 바뀌지 않음", s.get(Department, rows[0][0]).name == rows[0][1])
    renamed = [(rows[0][0], "기획운영팀", rows[1][2], 900), (rows[1][0], rows[1][1], rows[0][2], rows[1][3])] + rows[2:]
    r = post(renamed, new=("신규검증부", "", "950"))
    with SessionLocal() as s:
        d0 = s.get(Department, rows[0][0])
        news = s.query(Department).filter(Department.name == "신규검증부").all()
        ok = (d0.name == "기획운영팀" and d0.order_no == 900 and d0.code == rows[1][2]
              and s.get(Department, rows[1][0]).code == rows[0][2] and len(news) == 1 and news[0].code == "신규검증부")
        check("부서 — 이름·순서 저장(ID 유지)·코드 맞바꾸기·새 부서 추가(코드 비우면 이름)", ok and "부서를 저장했습니다" in r.text,
              repr((d0.name, d0.code, d0.order_no, [n.id for n in news])))
    r = c.get(f"/write/{weeks.current().id}/{rows[0][0]}")
    check("바꾼 부서 이름이 작성 화면에 반영", "기획운영팀" in r.text)
    post(rows)                                       # 이름은 원래대로(새 부서는 남는다 — 지우지 않는 규칙)


def _write_central(folder: Path) -> None:
    """시험용 pjtlist·milestone — 실적이 없는 칸은 전망, 그것도 없으면 계획."""
    from datetime import datetime as dt

    import pyarrow as pa
    import pyarrow.parquet as pq
    folder.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist([
        {"SHIPNUM": "SN2701", "TITLE": "174K LNGC", "TYPEMODEL": "LNGC174", "SHIPCLASS": "DNV", "DOCK": "D3",
         "REGOWNER": "OWNER-A", "MAINHULLNUM": "SN2701", "WORKFINISH": dt(2027, 12, 1)},
        {"SHIPNUM": "2702", "TITLE": "174K LNGC", "TYPEMODEL": "LNGC174", "SHIPCLASS": "DNV", "DOCK": "D3",
         "REGOWNER": "OWNER-A", "MAINHULLNUM": "SN2701", "WORKFINISH": dt(2028, 3, 1)},
        {"SHIPNUM": None, "TITLE": "빈 호선", "TYPEMODEL": "X", "SHIPCLASS": None, "DOCK": None,
         "REGOWNER": None, "MAINHULLNUM": None, "WORKFINISH": None},
    ]), folder / "pjtlist.parquet")
    pq.write_table(pa.Table.from_pylist([
        {"project": "SN2701", "PERFLC": dt(2026, 3, 2), "PROSLC": None, "PLANLC": dt(2026, 3, 1),
         "PERFSTFROM": None, "PROSSTFROM": dt(2026, 11, 3), "PLANSTFROM": dt(2026, 11, 1),
         "PERFSTTO": None, "PROSSTTO": dt(2026, 11, 8), "PLANSTTO": None,
         "PERFDL": None, "PROSDL": None, "PLANDL": dt(2027, 1, 15)},
        {"project": "SN2702", "PERFLC": None, "PROSLC": None, "PLANLC": dt(2026, 12, 1),
         "PERFSTFROM": None, "PROSSTFROM": None, "PLANSTFROM": None, "PERFSTTO": None, "PROSSTTO": None, "PLANSTTO": None,
         "PERFDL": None, "PROSDL": None, "PLANDL": None},
    ]), folder / "milestone.parquet")


def t_central(c) -> None:
    """pjtlist → 호선 동기화, 마일스톤 날짜(행별 실적 → 전망 → 계획), 파일 없을 때 None."""
    from datetime import date

    from app import models as m
    from app.db import SessionLocal
    from app.services import central
    folder = Path(os.environ["MEETING_CENTRAL_PARQUET"])
    check("pjtlist 파일 없음 → None + 사유(앱은 뜬다)",
          central.load_pjtlist() is None and "파일이 없습니다" in central._read("pjtlist")[1])
    r = c.get("/settings")
    check("설정 화면 — 못 읽음 표시", "못 읽음" in r.text)
    with SessionLocal() as s:
        rep_ = central.sync_hulls(s)
        check("파일 없으면 동기화 안 함", not rep_.ok and bool(rep_.reason))
        before = {h.id for h in s.query(m.Hull)}
    _write_central(folder)
    r = c.post("/settings/sync", follow_redirects=True)
    check("「지금 다시 읽기」 → 새로 2 (빈 SHIPNUM 행 제외, 「2702」 → SN2702)", "새로 2" in r.text)
    with SessionLocal() as s:
        h1, h2 = s.get(m.Hull, "SN2701"), s.get(m.Hull, "SN2702")
        ok = (h1 and h2 and h1.source == "pjtlist" and h1.title == "174K LNGC" and h1.dock == "D3" and h1.ship_class == "DNV"
              and h1.ship_type_id == "ST-LNGC174" and h1.owner_id == "OW-OWNER-A"
              and h1.sister_group_id == h2.sister_group_id == "SG-SN2701"
              and s.get(m.SisterGroup, "SG-SN2701").name == "SN2701 시리즈 (LNGC174)")
        check("동기화 — 선종·선주·자매선·프로젝트명·도크·선급", bool(ok))
        check("인도일 — milestone D/L(계획), 없으면 WORKFINISH", h1.delivery_date == date(2027, 1, 15)
              and h2.delivery_date == date(2028, 3, 1), repr((h1.delivery_date, h2.delivery_date)))
        check("pjtlist 에 없는 기존 호선은 지우지 않음", "SN2511" in before and before <= {h.id for h in s.query(m.Hull)})
    ev = {e["code"]: e for e in central.hull_events("SN2701")}
    check("행별 날짜 체인 — 실적 있으면 실적, 없으면 전망, 그다음 계획",
          ev["LC"]["date"] == date(2026, 3, 2) and ev["LC"]["src"] == "실적"
          and ev["ST"]["date"] == date(2026, 11, 3) and ev["ST"]["src"] == "전망" and ev["ST"]["end"] == date(2026, 11, 8)
          and ev["DL"]["src"] == "계획", repr(ev))
    hb = central.hull_brief("SN2701", today=date(2026, 10, 22))
    check("칩 — 다음 이벤트 S/T · D-12 · 인도일", hb["next"]["code"] == "ST" and hb["dday"] == 12
          and hb["delivery"]["date"] == date(2027, 1, 15))
    check("단계 — 실적 진수만 지남 → 진수 후", central.stage_of("SN2701", date(2026, 10, 22)) == "진수 후")
    check("milestone 없는 호선 → 칩 없음", central.hull_brief("SN2511") is None)
    late = central.hull_brief("SN2701", today=date(2027, 2, 1))
    check("인도 전망·계획 날짜만 지남 → 「인도 완료」 아님", late["next"] is None and not late["delivered"])
    check("이벤트는 날짜순", [e["date"] for e in central.hull_events("SN2701")] == sorted(e["date"] for e in central.hull_events("SN2701")))
    r = c.post("/settings/sync", follow_redirects=True)
    check("다시 읽기 — 바뀐 게 없으면 새로 0 · 갱신 0", "새로 0 · 갱신 0" in r.text)
    r = c.get("/settings")
    check("설정 화면 — 읽음·pjtlist 에 없는 호선 목록", "읽음" in r.text and "pjtlist 에 없는 호선" in r.text and "SN2511" in r.text)
    with SessionLocal() as s:                         # 작성 화면 이슈 카드의 호선 칩
        sb = s.query(m.SectionBlock).first()
        sec = s.get(m.Section, sb.section_id)
        s.add(m.BlockTag(block_id=sb.block_id, kind="hull", target_id="SN2701", raw_text="2701", confirmed=True))
        s.commit()
        url = f"/write/{sec.week_id}/{sec.department_id}?block={sb.block_id}"
    r = c.get(url)
    check("작성 화면 — 호선 태그 옆 마일스톤 칩(펼치면 이벤트 표)", 'class="ms-chip"' in r.text and "S/T 해상시운전" in r.text, url)


def t_m9(c) -> None:
    """M9 홈·이슈 원장 — 자동 저장·초안 완료·한 줄·종결 요청·일괄·확정 잠금·기존 DB 보강."""
    import sqlite3
    import tempfile as tf

    from sqlalchemy import create_engine, select

    from app import models as m
    from app.db import SessionLocal, _add_missing_columns
    from app.services import weeks

    r = c.get("/", follow_redirects=False)
    check("M9 — / 는 홈으로", r.status_code == 307 and r.headers["location"] == "/home", r.headers.get("location", ""))
    for role in ("w", "d", "p"):
        r = c.get(f"/home?role={role}&dept=D2")
        check(f"M9 — 홈 역할 {role} 200 · 메뉴 「홈」 현재", r.status_code == 200 and "이번 주 할 일" in r.text and 'href="/home" aria-current="page"' in r.text, f"status {r.status_code}")
    wk = weeks.current().id
    with SessionLocal() as ss:
        open_secs = {x.id for x in ss.scalars(select(m.Section).where(m.Section.status != "확정"))}
        cand = [b for b in ss.scalars(select(m.Block).where(m.Block.block_type.in_(("issue", "problem")), m.Block.status.in_(("신규", "진행"))).order_by(m.Block.id))
                if (sec := __import__("app.services.writing", fromlist=["x"]).block_section(ss, b.id)) is not None and sec.id in open_secs]
        ids = [b.id for b in cand[:3]]
        locked = ss.scalar(select(m.SectionBlock.block_id).join(m.Section, m.Section.id == m.SectionBlock.section_id).where(m.Section.status == "확정").limit(1))
    check("M9 — 시험용 열린 이슈 2건 이상", len(ids) >= 2, repr(ids))
    if len(ids) < 2:
        return
    a, b2 = ids[0], ids[1]
    with SessionLocal() as ss:
        owner_a = ss.get(m.Block, a).owner_department_id
    r = c.get(f"/issues?id={a}&dept=all")
    check("M9 — 이슈 작업대 200 · 원장·내용 칸·1차 초안", r.status_code == 200 and 'data-field="cause_text"' in r.text and "1차 초안" in r.text and f'value="{a}"' in r.text, f"status {r.status_code}")
    r = c.post(f"/api/issues/{a}/field", json={"field": "cause_text", "value": "흡입 스트레이너 막힘"})
    with SessionLocal() as ss:
        bb = ss.get(m.Block, a)
        log = ss.scalar(select(m.AiFieldLog).where(m.AiFieldLog.block_id == a, m.AiFieldLog.field == "cause_text").order_by(m.AiFieldLog.id.desc()))
        check("M9 — 자동 저장(원인) → 반영·초안 작성 중·사람 값 기록", r.json().get("ok") and bb.cause_text == "흡입 스트레이너 막힘" and bb.draft_state in ("wip", "ok") and log and log.human_value == "흡입 스트레이너 막힘", r.text[:200])
    r = c.post(f"/api/issues/{a}/field", json={"field": "owner_department_id", "value": "D1"})
    check("M9 — 고칠 수 없는 칸은 400 + 안내", r.status_code == 400 and "고칠 수 없는 항목" in r.json()["err"])
    r = c.post(f"/api/issues/{a}/field", json={"field": "title", "value": ""})
    check("M9 — 빈 제목 거부", r.status_code == 400 and "제목" in r.json()["err"])
    r = c.post(f"/api/issues/{a}/line", json={"text": ""})
    check("M9 — 빈 한 줄 거부 + 「변동 없음」 안내", r.status_code == 400 and "변동 없음" in r.json()["err"])
    r = c.post(f"/api/issues/{a}/line", json={"text": "스트레이너 청소 후 재측정"})
    with SessionLocal() as ss:
        row = __import__("app.services.carry_over", fromlist=["x"]).week_row(ss, a, wk)   # 이번 주 마지막 행(화면이 쓰는 것)
        check("M9 — 이번 주 한 줄 저장(이력 행)", r.json().get("ok") and row is not None and row.note == "스트레이너 청소 후 재측정", r.text[:200])
    c.post(f"/api/issues/{a}/field", json={"field": "body", "value": ""})
    r = c.post(f"/issues/{a}/draft-done", follow_redirects=True)
    check("M9 — 현상이 비면 초안 완료 거부", "「현상」 칸을 채워야" in r.text)
    c.post(f"/api/issues/{a}/field", json={"field": "body", "value": "토출압 ±0.4bar 변동"})
    r = c.post(f"/issues/{a}/draft-done", follow_redirects=False)
    with SessionLocal() as ss:
        ok = ss.get(m.Block, a).draft_state == "ok"
    loc = r.headers.get("location", "")
    check("M9 — 초안 완료 → 다음 초안으로(또는 남은 것 없음)", r.status_code == 303 and ok and ("done=1" in loc or (f"id={a}" not in loc and "id=" in loc)), loc)
    r = c.post(f"/issues/{b2}/close-request", data={"action_text": ""}, follow_redirects=True)
    with SessionLocal() as ss:
        before = ss.get(m.Block, b2).action_text
    if not (before or "").strip():
        check("M9 — 조치 없이 종결 요청 거부", "조치 내용을 적어야" in r.text)
    r = c.post(f"/issues/{b2}/close-request", data={"action_text": "씰 교체 후 4시간 무누유"}, follow_redirects=True)
    with SessionLocal() as ss:
        bb = ss.get(m.Block, b2)
        check("M9 — 종결 요청(조치 칸도 채움)", bb.status == "종결요청" and bb.action_text == "씰 교체 후 4시간 무누유" and "종결 요청" in r.text, bb.status)
    r = c.post("/issues/bulk", data={"ids": [], "action": "status", "value": "진행"}, follow_redirects=True)
    check("M9 — 일괄: 고른 것 없으면 안내", "고른 이슈가 없습니다" in r.text)
    r = c.post("/issues/bulk", data={"ids": [a], "action": "transfer", "value": "D-없음"}, follow_redirects=True)
    with SessionLocal() as ss:
        same = ss.get(m.Block, a).owner_department_id
    check("M9 — 일괄 이관 실패 → 아무것도 안 바뀜·안내", "아무것도 바뀌지 않았습니다" in r.text and same == owner_a, same)
    if locked:
        r = c.post(f"/api/issues/{locked}/field", json={"field": "cause_text", "value": "x"})
        check("M11 — 확정된 섹션의 이슈도 고침(사실 잠금 풀림)", r.status_code == 200 and r.json()["ok"], r.text[:200])
    with tf.TemporaryDirectory() as td:
        dbf = Path(td) / "old_block.db"
        con = sqlite3.connect(dbf)
        con.execute("CREATE TABLE block (id VARCHAR(24) PRIMARY KEY, block_type VARCHAR(16), title VARCHAR(256), body TEXT, status VARCHAR(16))")
        con.execute("INSERT INTO block VALUES ('ISS-1', 'issue', '옛 이슈', '본문', '진행')")
        con.commit()
        con.close()
        eng = create_engine(f"sqlite:///{dbf}")
        _add_missing_columns(eng)
        with eng.connect() as conn:
            cols = [x[1] for x in conn.exec_driver_sql("PRAGMA table_info(block)")]
            row = conn.exec_driver_sql("SELECT draft_state, cause_text, important FROM block").fetchone()
        eng.dispose()
        check("M9 — 기존 DB 보강: block 초안 상태·원인·조치·결정 필요·중요(옛 행 기본값)",
              {"draft_state", "cause_text", "action_text", "decision_needed", "important"} <= set(cols) and tuple(row) == ("none", "", 0), repr(row))


def t_m10(c) -> None:
    """M10 회의 · 스튜디오(시험 중) — 정기 회의 자동 생성, 시작(이어받기), 장 넣기·형태·한 줄·요약·빼기·되돌리기·순서·제출, 사실 반영, 원장에서 넣기."""
    import sqlite3
    import tempfile as tf

    from sqlalchemy import create_engine, func, select

    from app import models as m
    from app.db import SessionLocal, _add_missing_columns
    from app.services import weeks

    wk = weeks.current().id
    r = c.get("/meetings")
    check("M10·M11 — 회의 목록 200 · 「시험 중」 없음 · 공유회는 취합·발행으로", r.status_code == 200 and "시험 중" not in r.text and "취합·발행 →" in r.text, f"status {r.status_code}")
    c.get("/meetings")
    with SessionLocal() as ss:
        n_dept = ss.scalar(select(func.count()).select_from(m.Department))
        n_mt = ss.scalar(select(func.count()).select_from(m.Meeting).where(m.Meeting.week_id == wk, m.Meeting.kind == "dept"))
        n_share = ss.scalar(select(func.count()).select_from(m.Meeting).where(m.Meeting.week_id == wk, m.Meeting.kind == "share"))
        share = ss.scalar(select(m.Meeting).where(m.Meeting.week_id == wk, m.Meeting.kind == "share"))
        # 부서 자료에 쓸 부서 — 열린 이슈가 가장 많은 부서(장 2개 이상 필요)
        dept = ss.execute(select(m.Block.owner_department_id, func.count()).where(m.Block.block_type.in_(("issue", "problem")), m.Block.status != "종결")
                          .group_by(m.Block.owner_department_id).order_by(func.count().desc()).limit(1)).first()[0]
        mine = [b.id for b in ss.scalars(select(m.Block).where(m.Block.owner_department_id == dept, m.Block.block_type.in_(("issue", "problem")), m.Block.status != "종결"))]
        for bid in mine[:2]:
            ss.get(m.Block, bid).draft_state = "ok"
        ss.commit()
        dmt = ss.scalar(select(m.Meeting).where(m.Meeting.week_id == wk, m.Meeting.kind == "dept", m.Meeting.owner_dept_id == dept))
        mid, share_id = dmt.id, share.id
    check("M10 — 정기 회의: 부서 자료는 부서마다 하나, 두 번 열어도 중복 없음, 공유회 한 줄", n_mt == n_dept and n_share == 1, f"{n_mt}/{n_dept} share {n_share}")
    r = c.get(f"/studio/{share_id}", follow_redirects=False)
    check("M11 — 공유회도 스튜디오에서(옛 화면으로 보내지 않음)", r.status_code == 200 and 'id="stState"' in r.text, f"status {r.status_code}")
    r = c.get(f"/studio/{mid}")
    check("M10 — 부서 자료 스튜디오 200 · 상태 JSON · 제출 버튼", r.status_code == 200 and 'id="stState"' in r.text and ">제출</button>" in r.text, f"status {r.status_code}")
    r = c.post(f"/api/studio/{mid}/start", json={"mode": "carry"})
    j = r.json()
    check("M10 — 지난주 이어받기 → 초안 완료 이슈가 장으로(새 초안)", j.get("ok") and j["added"] >= 1 and all(it["src"] in ("지난주", "새 초안") for it in j["state"]["items"]), r.text[:200])
    r = c.post(f"/api/studio/{mid}/start", json={"mode": "blank"})
    check("M10 — 장이 있으면 시작 방식 다시 못 고름", r.status_code == 400)
    st = c.get(f"/api/studio/{mid}").json()["state"]
    in_ids = {b["id"] for it in st["items"] for b in it["blocks"]}
    extra = [x for x in mine if x not in in_ids]
    if extra:
        r = c.post(f"/api/studio/{mid}/items", json={"block_id": extra[0]})
        check("M10 — 후보에서 장 넣기", r.json().get("ok"), r.text[:200])
    r = c.post(f"/api/studio/{mid}/items", json={"block_id": mine[0]})
    check("M10 — 같은 이슈 두 번 넣기 거부", r.status_code == 400 and "이미" in r.json()["err"])
    st = c.get(f"/api/studio/{mid}").json()["state"]
    items = st["items"]
    check("M10 — 시험용 장 2개 이상", len(items) >= 2, str(len(items)))
    if len(items) < 2:
        return
    i0, i1 = items[0]["id"], items[1]["id"]
    r = c.post(f"/api/studio/items/{i0}", json={"field": "form", "value": "표"})
    check("M10 — 없는 형태 거부", r.status_code == 400)
    r = c.post(f"/api/studio/items/{i0}", json={"field": "form", "value": "detail"})
    check("M10 — 형태 바꾸기(상세 한 장)", r.json()["state"]["items"][0]["form"] == "detail")
    r = c.post(f"/api/studio/items/{i0}", json={"field": "line", "value": "가" * 400})
    check("M10 — 회의용 한 줄 300자 넘으면 거부", r.status_code == 400)
    c.post(f"/api/studio/items/{i0}", json={"field": "line", "value": "밸브 교체 일정 확정"})
    # ● 사실 — 확정 섹션에 든 이슈는 M12 까지 잠겨 있으니, 첫 장의 섹션을 잠시 연다(끝나면 되돌림)
    from app.services import writing as wr
    bid0 = items[0]["blocks"][0]["id"]
    with SessionLocal() as ss:
        sec = wr.block_section(ss, bid0)
        was = sec.status if sec else None
        if sec:
            sec.status = "작성중"
            ss.commit()
    rf = c.post(f"/api/issues/{bid0}/field", json={"field": "cause_text", "value": "분사밸브 노즐 마모"})
    st = c.get(f"/api/studio/{mid}").json()["state"]
    x0 = st["items"][0]
    check("M10 — ● 사실(원인)은 이슈에 반영되어 장에 보임 · 한 줄은 이 자료에만", x0["blocks"][0]["cause"] == "분사밸브 노즐 마모" and x0["line"] == "밸브 교체 일정 확정", rf.text[:120])
    if was:
        with SessionLocal() as ss:
            wr.block_section(ss, bid0).status = was
            ss.commit()
    r = c.post(f"/api/studio/{mid}/reorder", json={"ids": [i1]})
    check("M10 — 순서: 목록이 안 맞으면 거부", r.status_code == 400)
    ids = [it["id"] for it in st["items"]]
    r = c.post(f"/api/studio/{mid}/reorder", json={"ids": ids[::-1]})
    check("M10 — 순서 바꾸기", [it["id"] for it in r.json()["state"]["items"]] == ids[::-1])
    r = c.post(f"/api/studio/{mid}/summary", json={"ids": [i0]})
    check("M10 — 요약은 두 장 이상", r.status_code == 400)
    n_before = len(ids)
    r = c.post(f"/api/studio/{mid}/summary", json={"ids": [i0, i1]})
    j = r.json()
    summ = next(it for it in j["state"]["items"] if it["id"] == j["item_id"])
    with SessionLocal() as ss:
        still = all(ss.get(m.Block, b["id"]) is not None for b in summ["blocks"])
    check("M10 — 두 장 → 요약 한 장(이슈 2개 연결, 이슈는 그대로)", summ["kind"] == "summary" and len(summ["blocks"]) == 2 and len(j["state"]["items"]) == n_before - 1 and still)
    r = c.post(f"/api/studio/items/{summ['id']}/unsummary")
    check("M10 — 요약 풀기 → 다시 두 장", len(r.json()["state"]["items"]) == n_before)
    st = r.json()["state"]
    r = c.post(f"/api/studio/items/{st['items'][0]['id']}/remove")
    j = r.json()
    check("M10 — 장 빼기 → 되돌리기용 스냅숏", j.get("ok") and len(j["state"]["items"]) == n_before - 1 and j["snapshot"]["block_id"])
    r = c.post(f"/api/studio/{mid}/restore", json={"snapshot": j["snapshot"]})
    check("M10 — 되돌리기 → 장이 돌아옴", len(r.json()["state"]["items"]) == n_before)
    r = c.post(f"/api/studio/{mid}/submit")
    check("M10 — 제출 → 1판", r.json()["state"]["meeting"]["status"] == "제출" and r.json()["state"]["meeting"]["version"] == 1)
    r = c.post(f"/api/studio/items/{r.json()['state']['items'][0]['id']}", json={"field": "tag_on", "value": False})
    check("M10 — 제출 뒤 고치면 「수정됨」", r.json()["state"]["meeting"]["status"] == "수정됨")
    with SessionLocal() as ss:
        other = ss.scalar(select(m.Meeting).where(m.Meeting.week_id == wk, m.Meeting.kind == "dept", m.Meeting.id != mid))
        oid = other.id
    r = c.post(f"/api/studio/{oid}/submit")
    check("M10 — 빈 자료 제출 거부", r.status_code == 400 and "장이 없습니다" in r.json()["err"])
    r = c.post("/issues/bulk", data={"ids": [mine[0]], "action": "adopt", "value": str(oid)}, follow_redirects=True)
    with SessionLocal() as ss:
        n_o = ss.scalar(select(func.count()).select_from(m.ReportItem).where(m.ReportItem.meeting_id == oid))
    check("M10 — 이슈 원장에서 「회의자료에 넣기」", n_o == 1 and "회의자료에 넣기" in r.text, str(n_o))
    r = c.post(f"/meetings/{wk}/adhoc", data={"kind": "hull", "hull_id": ""}, follow_redirects=True)
    check("M10 — 수시 호선별 회의는 호선 필수", "호선을 골라주세요" in r.text)
    with tf.TemporaryDirectory() as td:
        dbf = Path(td) / "old_meeting.db"
        con = sqlite3.connect(dbf)
        con.execute("CREATE TABLE meeting (id INTEGER PRIMARY KEY, week_id VARCHAR(8), held_at DATETIME, chair_id INTEGER)")
        con.execute("INSERT INTO meeting (week_id) VALUES ('2026-W40')")
        con.commit()
        con.close()
        eng = create_engine(f"sqlite:///{dbf}")
        _add_missing_columns(eng)
        with eng.connect() as conn:
            row = conn.exec_driver_sql("SELECT kind, status, version, order_json FROM meeting").fetchone()
        eng.dispose()
        check("M10·M11 — 기존 DB 보강: 옛 주차 회의는 공유회·구성 중·0판·부서 순서 빈 값", tuple(row) == ("share", "구성 중", 0, ""), repr(row))


def t_f16_f21(c) -> None:
    """F16 지표 요약 장(스튜디오·판·PPT 차트) · F21 일정 경보(목표·D-n·해제·다시 켜짐·기한 지남·이슈별 일수·기본값·묶음·머리표·홈)."""
    import io as _io
    from datetime import date, timedelta

    from pptx import Presentation
    from sqlalchemy import select

    from app import models as m
    from app.db import SessionLocal
    from app.services import alerts as al
    from app.services import studio as st
    from app.services import weeks
    from app.services import writing as w

    wk = weeks.current().id
    today = weeks.today()          # MEETING_TODAY 고정값
    # ── F16 지표 요약 장 ──
    with SessionLocal() as s:
        st.ensure_week_meetings(s, wk)
        s.commit()
        dm = st.week_meeting(s, wk, "dept", "D3")
        mid = dm.id
        dm.status = "구성 중"                          # 앞 시험이 제출해 둔 자료여도 편집할 수 있게
        s.commit()
    r = c.post(f"/api/studio/{mid}/metric-item")
    j = r.json()
    it = next((x for x in j.get("state", {}).get("items", []) if x["kind"] == "metric"), None)
    check("F16 — 부서 자료에 「지표 요약」 장(지표·기간 표 합계)", j.get("ok") and it is not None and it["metric"]["dept"]
          and any(x["name"] == "시운전 항목 완료율" for x in it["metric"]["metrics"]) and any(t["name"] == "특근 인원" for t in it["metric"]["tables"]), r.text[:200])
    r = c.post(f"/api/studio/{mid}/metric-item")
    check("F16 — 지표 요약 장은 하나만", r.status_code == 400 and "이미" in r.json()["err"])
    with SessionLocal() as s:
        ex = st.week_meeting(s, wk, "exec")
    r = c.post(f"/api/studio/{ex.id}/metric-item")
    check("F16 — 지표 요약 장은 부서 자료에만", r.status_code == 400)
    flagged = it["metric"]["metrics"][0]
    check("F16 — 이탈·코멘트 있는 지표가 먼저", bool(flagged["flag"] or flagged["comment"]))
    r = c.get(f"/export/meeting/{mid}/pptx")
    shapes = [sh for sl in Presentation(_io.BytesIO(r.content)).slides for sh in sl.shapes]
    check("F16 — PPT 지표 요약 장: 표 + 편집 가능한 차트", any(sh.has_chart for sh in shapes) and any(sh.has_table for sh in shapes))
    # ── 기간 표 단독 장(2026-10-29) ──
    st0 = c.get(f"/api/studio/{mid}").json()["state"]
    pt = next((t for t in st0.get("ptables", []) if t["name"] == "특근 인원"), None)
    check("기간 표 장 — 스튜디오에 넣을 수 있는 표 목록", pt is not None, repr(st0.get("ptables")))
    r = c.post(f"/api/studio/{mid}/table-item", json={"table_id": pt["id"] if pt else 0})
    j = r.json()
    ti = next((x for x in j.get("state", {}).get("items", []) if x["kind"] == "table"), None)
    T = (ti or {}).get("table") or {}
    check("기간 표 장 — 그 주 날짜(월~금 5일)·행·기간 합계", j.get("ok") and len(T.get("days", [])) == 5 and T["days"][0].startswith("10/19")
          and [x["name"] for x in T["rows"]][:2] == ["1과", "2과"] and T["plan"] is not None, r.text[:300])
    check("기간 표 장 — 넣은 표는 목록에서 빠짐", all(t["name"] != "특근 인원" for t in j["state"]["ptables"]))
    r = c.post(f"/api/studio/{mid}/table-item", json={"table_id": pt["id"] if pt else 0})
    check("기간 표 장 — 표마다 한 장", r.status_code == 400 and "이미" in r.json()["err"])
    r = c.post(f"/api/studio/{ex.id}/table-item", json={"table_id": pt["id"] if pt else 0})
    check("기간 표 장 — 부서 자료에만", r.status_code == 400)
    r = c.post(f"/api/studio/{mid}/table-item", json={})
    check("기간 표 장 — 표를 안 고르면 안내", r.status_code == 400 and "골라주세요" in r.json()["err"])
    r = c.get(f"/export/meeting/{mid}/pptx")
    prs = Presentation(_io.BytesIO(r.content))
    tsl = [sl for sl in prs.slides if any(sh.has_text_frame and "[기간 표]" in sh.text_frame.text for sh in sl.shapes)]
    tb = next((sh.table for sl in tsl for sh in sl.shapes if sh.has_table), None)
    check("기간 표 장 — PPT 에 PowerPoint 표(행 × 날짜 + 합계)", tb is not None and tb.cell(0, 1).text.startswith("10/19")
          and tb.cell(len(tb.rows) - 1, 0).text == "합계", str(len(tsl)))
    # ── F21 일정 경보 ──
    with SessionLocal() as s:
        b = s.scalar(select(m.Block).where(m.Block.block_type == "issue", m.Block.status.in_(("신규", "진행")), m.Block.owner_department_id == "D3").order_by(m.Block.id))
        bid = b.id
        s.add(m.BlockTag(block_id=bid, kind="hull", target_id="SN2701", raw_text="2701", confirmed=True)) if w.block_hull(s, bid) is None else None
        s.commit()
        hull = w.block_hull(s, bid)
    r = c.post(f"/issues/{bid}/due", data={"event": "XX"})
    check("F21 — 없는 목표 거부", "골라주세요" in r.text)
    r = c.post(f"/issues/{bid}/due", data={"event": "DATE", "due": "내일"})
    check("F21 — 직접 날짜 형식 안내", "2026-11-05 처럼" in r.text)
    r = c.post(f"/issues/{bid}/due", data={"event": "DATE", "due": (today + timedelta(days=9)).isoformat()})
    with SessionLocal() as s:
        b = s.get(m.Block, bid)
        stt = al.state(s, b)
    check("F21 — 직접 날짜 D-9 → 임박(기본 14일) · 칩", stt["level"] == "임박" and stt["left"] == 9 and stt["chip"] == "목표일 전 D-9" and "목표일 전 D-9" in r.text, repr(stt))
    r = c.get("/issues", params={"dept": "D3", "f": "soon"})
    check("F21 — 이슈 원장 「일정 임박」에 이 이슈·칩", bid in r.text and "목표일 전 D-9" in r.text)
    r = c.get("/home", params={"role": "w", "dept": "D3"})
    check("F21 — 홈 할 일 「일정 임박」", "일정 임박" in r.text and bid in r.text and "일정 보기" in r.text)
    with SessionLocal() as s:
        cands = dict((g, [x.id for x in bs]) for g, bs in st.candidates(s, s.get(m.Meeting, mid)))
        tag = st.ptag(s, s.get(m.Block, bid), wk)
    in_deck = bid in {b_["id"] for it_ in c.get(f"/api/studio/{mid}").json()["state"]["items"] for b_ in it_["blocks"]}
    check("F21 — 부서 자료 후보 맨 앞 「일정 임박」 묶음(이미 장이면 후보에 없음)", in_deck or (list(cands)[0].startswith("일정 임박") and bid in list(cands.values())[0]), repr(list(cands)))
    check("F21 — 머리표에 일정(결정필요 다음)", "목표일 전 D-9" in tag, tag)
    r = c.post(f"/issues/{bid}/alert-off", data={"reason": ""})
    check("F21 — 해제 사유 없으면 거부", "사유를 한 줄" in r.text)
    c.post(f"/issues/{bid}/alert-off", data={"reason": "선주 합의로 인도 뒤 처리"})
    with SessionLocal() as s:
        stt = al.state(s, s.get(m.Block, bid))
        n_due = len(al.due_blocks(s, "D3"))
        ids_due = [x.id for x, _ in al.due_blocks(s, "D3")]
    check("F21 — 해제 → 「해제」·임박 묶음에서 빠짐", stt["level"] == "해제" and bid not in ids_due, repr(stt))
    with SessionLocal() as s:                      # 날짜가 당겨지면 다시 켜진다(같은 목표 유지)
        b = s.get(m.Block, bid)
        b.due_date = today + timedelta(days=5)
        s.commit()
        stt = al.state(s, b)
    check("F21 — 목표 날짜가 당겨지면 다시 켜짐", stt["level"] == "임박" and stt["left"] == 5, repr(stt))
    c.post(f"/issues/{bid}/alert-off", data={"reason": "다음 주 처리"})
    with SessionLocal() as s:
        b = s.get(m.Block, bid)
        b.due_date = today - timedelta(days=2)
        s.commit()
        stt = al.state(s, b)
    check("F21 — 날짜가 지나면 해제와 관계없이 「기한 지남」", stt["level"] == "기한 지남" and stt["chip"] == "목표일 전 기한 지남 D+2", repr(stt))
    c.post(f"/issues/{bid}/due", data={"event": "DATE", "due": (today + timedelta(days=20)).isoformat(), "days": "30"})
    with SessionLocal() as s:
        b = s.get(m.Block, bid)
        stt = al.state(s, b)
    check("F21 — 이슈별 경보 일수(30) · 목표를 바꾸면 해제가 풀림", stt["level"] == "임박" and stt["days"] == 30 and not b.alert_off_reason, repr(stt))
    c.post(f"/issues/{bid}/due", data={"event": "DATE", "due": (today + timedelta(days=20)).isoformat(), "days": ""})
    with SessionLocal() as s:
        stt = al.state(s, s.get(m.Block, bid))
    check("F21 — 이슈별 일수를 비우면 기본 14 → 경보 아님", stt["level"] == "" and stt["days"] == 14)
    r = c.post("/settings/alerts", data={"d_DATE": "21", "d_ST": "abc"})
    check("F21 — 설정 기본 일수: 숫자 아니면 거부", "숫자로" in r.text)
    c.post("/settings/alerts", data={"d_DATE": "21"})
    with SessionLocal() as s:
        stt = al.state(s, s.get(m.Block, bid))
        logs = [x.field for x in s.scalars(select(m.AiFieldLog).where(m.AiFieldLog.block_id == bid, m.AiFieldLog.field.in_(("due", "alert_off"))))]
    check("F21 — 설정 기본값(직접 날짜 21일) → 임박", stt["level"] == "임박" and stt["days"] == 21, repr(stt))
    check("F21 — 목표·해제 바꾼 이력(ai_field_log)", logs.count("due") >= 3 and logs.count("alert_off") >= 2, repr(logs))
    r = c.get("/settings")
    check("F21 — 설정 화면 「이벤트별 기본 경보 일수」", "기본 경보 일수" in r.text and 'name="d_ST"' in r.text and 'value="21"' in r.text)
    # 마일스톤 이벤트 목표(SN2701 S/T 전망 2026-11-03)
    with SessionLocal() as s:
        b = s.get(m.Block, bid)
        if hull != "SN2701":
            for t in w.block_tags(s, bid):
                if t.kind == "hull":
                    t.target_id = "SN2701"
        b.due_event, b.due_date, b.alert_days = "ST", None, None
        s.commit()
        stt = al.state(s, b, today=date(2026, 10, 25))
        sug = al.suggest(s, b)
    check("F21 — 마일스톤 목표: S/T 날짜는 milestone 체인(전망 11/03) · D-9", stt["target"]["date"] == date(2026, 11, 3) and stt["target"]["src"] == "전망"
          and stt["left"] == 9 and stt["chip"] == "S/T 전 D-9", repr(stt))
    with SessionLocal() as s:
        b = s.get(m.Block, bid)
        title0 = b.title
        b.title = "LNG 가스 공급 밸브 점검"
        sug_gas = al.suggest(s, b)
        b.title = "인도 전 도장 보수"
        sug_dl = al.suggest(s, b)
        s.rollback()
    check("F21 — 추천 목표: 가스 → G/T, 인도 → D/L, 아니면 호선 다음 이벤트", sug_gas == "GT" and sug_dl == "DL" and sug in ("ST", "DL", "") and title0, f"{sug_gas} {sug_dl} {sug}")
    r = c.get("/issues", params={"id": bid})
    check("F21 — 이슈 화면 「~전 해결」 칸·목표 날짜 설명", 'id="due"' in r.text and "~전 해결" in r.text and "2026-11-03(전망)" in r.text)


def t_m13(c) -> None:
    """M13 가져오기 — 메신저 머리줄 걷기(이름 미저장)·PPTX/HTML 조각·연결 후보(근거)·판정·반영·원본 보관·메일함 휴면·메일 조각·지표 화면."""
    import hashlib
    import io as _io
    import json as _json

    from PIL import Image
    from pptx import Presentation
    from pptx.util import Inches
    from sqlalchemy import func, select

    import path_config as pc
    from app import models as m
    from app.db import SessionLocal
    from app.services import carry_over as co
    from app.services import importer as im
    from app.services import weeks

    wk = weeks.current().id
    llm = _offline_llm()
    r = c.get("/import")
    check("M13 — 가져오기 화면 200 · 입구 3개(메모·파일·메일함)", r.status_code == 200 and "메모 붙여넣기" in r.text and "PPT·HTML 올리기" in r.text and "메일함" in r.text)
    # 메신저 대화 — 시간·보낸 사람 걷기
    chat = "--------------- 2026년 10월 23일 금요일 ---------------\n[홍길동] [오후 3:12] 2514 카고펌프 씰 누유 재발\n[김철수] [오후 3:15] 사진을 보냈습니다\n[김철수] [오후 3:16] 내일 씰 교체 예정"
    cl = im.clean_messenger(chat)
    check("M13 — 메신저 머리줄·시스템 줄을 걷고 내용만", cl.messenger and "홍길동" not in cl.text and "김철수" not in cl.text
          and cl.text.splitlines() == ["2514 카고펌프 씰 누유 재발", "내일 씰 교체 예정"], repr(cl.text))
    check("M13 — 보통 메모(시간 한 줄)는 건드리지 않음", im.clean_messenger("- 10:30 DG2 점검\n- 펌프 교체").text == "- 10:30 DG2 점검\n- 펌프 교체")
    r = c.post("/import/memo", data={"dept_id": "D5", "raw_text": chat, "then": "save"})
    with SessionLocal() as s:
        mm = s.scalars(select(m.Memo).order_by(m.Memo.created_at.desc(), m.Memo.id.desc())).first()
    check("M13 — 메모 입구: 이름 없이 저장 · 메모 화면으로", "홍길동" not in mm.raw_text and "카고펌프 씰 누유 재발" in mm.raw_text
          and "메신저 머리줄" in r.text and 'class="memo-lines"' in r.text, mm.raw_text[:80])
    r = c.post("/import/memo", data={"dept_id": "", "raw_text": "x"})
    check("M13 — 메모 입구: 부서 없으면 안내", "부서를 골라주세요" in r.text)
    # PPTX — 장마다 조각, 연결 후보는 근거가 있는 것만(열린 이슈 하나를 ID·호선으로 가리킨다)
    from app.services import writing as w
    with SessionLocal() as s:
        tb = next(b for b in s.scalars(select(m.Block).where(m.Block.block_type == "issue", m.Block.status.in_(("신규", "진행"))).order_by(m.Block.id))
                  if w.block_hull(s, b.id))
        tid, thull = tb.id, w.block_hull(s, tb.id)
    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[1])
    s1.shapes.title.text = f"{tid} {thull} 발전기 배기온도"
    s1.placeholders[1].text = "3번 실린더 노즐 교체 후 편차 해소 확인"
    buf = _io.BytesIO()
    Image.new("RGB", (80, 60), (200, 40, 40)).save(buf, "PNG")
    buf.seek(0)
    s1.shapes.add_picture(buf, Inches(5), Inches(4))
    s2 = prs.slides.add_slide(prs.slide_layouts[1])
    s2.shapes.title.text = "선미관 씰 점검 필요"
    s2.placeholders[1].text = "SN2618 선미관 씰 오일 누유 흔적"
    s3 = prs.slides.add_slide(prs.slide_layouts[5])
    s3.shapes.title.text = "공지 — 안전 교육"
    out = _io.BytesIO()
    prs.save(out)
    data = out.getvalue()
    r = c.post("/import/file", files={"file": ("주간_외부자료.pptx", data, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
               data={"dept_id": "D3"}, follow_redirects=False)
    jid = int(r.headers["location"].split("job=")[1].split("&")[0]) if "job=" in r.headers.get("location", "") else 0
    with SessionLocal() as s:
        job = s.get(m.ImportJob, jid)
        ps = list(s.scalars(select(m.ImportPiece).where(m.ImportPiece.job_id == jid).order_by(m.ImportPiece.no)))
        orig = (pc.get_import_dir() / job.file_key).read_bytes() if job else b""
        c1 = _json.loads(ps[0].candidates_json) if ps else []
        imgs = _json.loads(ps[0].images_json) if ps else []
    check("M13 PPTX — 장 3개 → 조각 3개 · 원본 보관(sha256 같음) · 그림 보관", len(ps) == 3 and hashlib.sha256(orig).hexdigest() == job.sha256 == hashlib.sha256(data).hexdigest()
          and len(imgs) == 1 and (pc.get_import_dir() / imgs[0]).is_file(), f"{len(ps)} {imgs}")
    check("M13 — 연결 후보: 이슈 ID·호선 근거", c1 and c1[0]["id"] == tid and any("이슈 ID" in x for x in c1[0]["why"]) and any(f"호선 {thull}" in x for x in c1[0]["why"]), repr(c1[:1]))
    r = c.get("/import", params={"job": jid})
    check("M13 — 조각 판정 화면(상태 JSON·원본 링크)", r.status_code == 200 and 'id="imState"' in r.text and "주간_외부자료.pptx" in r.text)
    r = c.get(f"/import/files/{imgs[0]}") if imgs else None
    check("M13 — 조각 그림 보기", r is not None and r.status_code == 200 and r.headers["content-type"].startswith("image/"))
    r = c.get(f"/import/files/{jid}/..%2F..%2Fmeeting.db")
    check("M13 — 보관 폴더 밖 파일은 내주지 않음", r.status_code == 404)
    pid1, pid2, pid3 = ps[0].id, ps[1].id, ps[2].id
    r = c.post(f"/api/import/pieces/{pid1}/decide", json={"decision": "link", "block_id": ""})
    check("M13 — 붙이기는 대상 이슈 필수", r.status_code == 400 and "붙일 이슈" in r.json()["err"])
    c.post(f"/api/import/pieces/{pid1}/decide", json={"decision": "link", "block_id": tid, "line": "외부 PPT — 노즐 교체 후 편차 해소"})
    c.post(f"/api/import/pieces/{pid2}/decide", json={"decision": "new", "dept_id": "D3"})
    j = c.post(f"/api/import/pieces/{pid3}/decide", json={"decision": "skip"}).json()
    check("M13 — 판정 3개(붙이기·새 이슈·건너뛰기)", [p_["decision"] for p_ in j["state"]["pieces"]] == ["link", "new", "skip"])
    with SessionLocal() as s:
        n_ph0 = s.scalar(select(func.count()).select_from(m.PhotoLink).where(m.PhotoLink.block_id == tid))

    def fake(task, system, user, timeout):          # 새 이슈 — 조각 글 첫 줄을 근거로
        return _json.dumps({"blocks": [{"block_type": "problem", "title": "선미관 씰 오일 누유", "body": "SN2618 선미관 씰 오일 누유 흔적", "status": "신규",
                                        "tags": [], "evidence": [{"line": 1, "quote": "선미관 씰 점검 필요"}]}], "questions": []}, ensure_ascii=False), "fake"
    llm.PROVIDERS["fake"] = fake
    saved = list(llm.settings.LLM_CHAIN)
    llm.settings.LLM_CHAIN[:] = ["fake"]
    try:
        j = c.post(f"/api/import/{jid}/apply").json()
    finally:
        llm.settings.LLM_CHAIN[:] = saved
        llm.PROVIDERS.pop("fake")
    with SessionLocal() as s:
        row = co.week_row(s, tid, wk)
        n_ph1 = s.scalar(select(func.count()).select_from(m.PhotoLink).where(m.PhotoLink.block_id == tid))
        newb = s.get(m.Block, j["created"][0]) if j.get("created") else None
        st_ = s.get(m.ImportJob, jid).status
    check("M13 반영 — 붙이기: 이번 주 한 줄 + 그림 → 사진", j.get("ok") and j["linked"] == [tid] and row is not None
          and row.note == "외부 PPT — 노즐 교체 후 편차 해소" and n_ph1 == n_ph0 + 1, repr(j)[:200])
    check("M13 반영 — 새 이슈: 조각 글을 메모로 AI 정리(근거 있음)", newb is not None and newb.title == "선미관 씰 오일 누유" and newb.owner_department_id == "D3"
          and j["skipped"] == 1 and st_ == "반영함", repr((newb and (newb.title, newb.owner_department_id), j["skipped"], st_)))
    j2 = c.post(f"/api/import/{jid}/apply").json()
    check("M13 — 다시 반영해도 같은 조각은 한 번만", not j2["linked"] and not j2["created"] and j2["skipped"] == 0)
    r = c.get("/issues", params={"id": tid})
    check("M13 — 이슈 원장 「주차별 진행」에 외부 자료 반영", "외부 자료 PPT" in r.text and "노즐 교체 후 편차 해소" in r.text)
    r = c.get(f"/import/{jid}/original")
    check("M13 — 원본 내려받기 = 올린 파일 그대로", r.status_code == 200 and r.content == data)
    # HTML · 잘못된 파일
    html = "<html><body><h2>SN2511 DG2 점검</h2><p>배기온도 정상화</p><h2>공지</h2><ul><li>안전 교육</li></ul></body></html>".encode()
    r = c.post("/import/file", files={"file": ("report.html", html, "text/html")}, data={"dept_id": "D3"}, follow_redirects=False)
    hj = int(r.headers["location"].split("job=")[1].split("&")[0])
    with SessionLocal() as s:
        titles = [p_.title for p_ in s.scalars(select(m.ImportPiece).where(m.ImportPiece.job_id == hj).order_by(m.ImportPiece.no))]
    check("M13 HTML — 제목마다 조각", titles == ["SN2511 DG2 점검", "공지"], repr(titles))
    r = c.post("/import/file", files={"file": ("x.xls", b"\xd0\xcf\x11\xe0", "application/vnd.ms-excel")}, data={"dept_id": "D3"})
    check("M13 — .xls 등은 .xlsx 로 저장 안내", ".xlsx 로 저장" in r.text)
    r = c.post("/import/file", files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}, data={"dept_id": "D3"})
    check("PDF — 깨진 파일은 사유 안내", "PDF 파일을 읽지 못했습니다" in r.text)

    # PDF — 쪽마다 조각(첫 줄 = 제목). 글꼴 Helvetica 라 영문만
    def _pdf(pages: list[list[str]]) -> bytes:
        objs = ["<< /Type /Catalog /Pages 2 0 R >>", "", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
        kids = []
        for lines in pages:
            body = "BT /F1 12 Tf 72 720 Td 14 TL " + " ".join(f"({ln}) Tj T*" for ln in lines) + " ET"
            objs.append(f"<< /Length {len(body)} >>\nstream\n{body}\nendstream")
            objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {len(objs)} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
            kids.append(f"{len(objs)} 0 R")
        objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
        out, offs = b"%PDF-1.4\n", []
        for i, o in enumerate(objs, 1):
            offs.append(len(out))
            out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
        x = len(out)
        out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
        return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF".encode()

    r = c.post("/import/file", files={"file": ("weekly.pdf", _pdf([["SN2511 DG2 exhaust temp high", "nozzle check planned"], ["Notice", "drill on Friday"]]), "application/pdf")},
               data={"dept_id": "D3"}, follow_redirects=False)
    pj = int(r.headers["location"].split("job=")[1].split("&")[0]) if "job=" in r.headers.get("location", "") else 0
    with SessionLocal() as s:
        pps = list(s.scalars(select(m.ImportPiece).where(m.ImportPiece.job_id == pj).order_by(m.ImportPiece.no)))
        pjob = s.get(m.ImportJob, pj)
        pinfo = [(x.title, x.text, x.kind) for x in pps]
        pkind = pjob.kind if pjob else ""
    check("PDF — 쪽마다 조각·첫 줄이 제목", pkind == "pdf" and [t for t, _, _ in pinfo] == ["SN2511 DG2 exhaust temp high", "Notice"]
          and "nozzle check planned" in pinfo[0][1] and pinfo[0][2] == "page", repr(pinfo))

    # 엑셀 — 시트마다(60행씩), 숨긴 시트 제외, 날짜 서식은 날짜로
    import xlsxwriter
    from datetime import date as _d
    xb = _io.BytesIO()
    wb_ = xlsxwriter.Workbook(xb, {"in_memory": True})
    ws = wb_.add_worksheet("현안")
    ws.write_row(0, 0, ["호선", "장비", "내용", "기한"])
    ws.write_row(1, 0, ["SN2511", "DG2", "배기온도 편차"])
    ws.write_datetime(1, 3, _d(2026, 11, 5), wb_.add_format({"num_format": "yyyy-mm-dd"}))
    ws.write_row(2, 0, ["", "", ""])
    ws.write(3, 1, 42)
    big = wb_.add_worksheet("점검 목록")
    for i in range(70):
        big.write_row(i, 0, [f"항목 {i + 1}", "완료"])
    hid = wb_.add_worksheet("숨김")
    hid.write(0, 0, "비밀")
    hid.hide()
    wb_.close()
    r = c.post("/import/file", files={"file": ("현안.xlsx", xb.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
               data={"dept_id": "D3"}, follow_redirects=False)
    xj = int(r.headers["location"].split("job=")[1].split("&")[0]) if "job=" in r.headers.get("location", "") else 0
    with SessionLocal() as s:
        xps = [(x.title, x.text, x.kind) for x in s.scalars(select(m.ImportPiece).where(m.ImportPiece.job_id == xj).order_by(m.ImportPiece.no))]
    check("엑셀 — 시트마다 조각, 60행 넘으면 나눔, 숨긴 시트 제외", [t for t, _, _ in xps] == ["현안", "점검 목록 · 1–60행", "점검 목록 · 61–70행"], repr([t for t, _, _ in xps]))
    check("엑셀 — 칸은 탭·날짜 서식은 날짜·빈 행 건너뜀", bool(xps) and xps[0][1].split("\n") == ["호선\t장비\t내용\t기한", "SN2511\tDG2\t배기온도 편차\t2026-11-05", "42"]
          and xps[0][2] == "sheet", repr(xps[:1]))
    # DRM 엑셀 — zip 이 아니면 Excel(COM)로 연다. 회귀에서는 Excel 을 띄우지 않고 drm_reader 를 갈아 끼운다
    from datetime import datetime as _dt
    from app.services import drm_reader as _drm
    _orig_read = _drm.read_sheets
    _drm.read_sheets = lambda data, suffix=".xlsx": [("보안 현안", [[None, None, None], [None, "호선", "기한"], [None, "SN2511", _dt(2026, 11, 5)],
                                                                  [None, 3.0, True], [None, None, None]])]
    r = c.post("/import/file", files={"file": ("보안.xlsx", b"DRM-ENCRYPTED-BLOB", "application/octet-stream")},
               data={"dept_id": "D3"}, follow_redirects=False)
    dj = int(r.headers["location"].split("job=")[1].split("&")[0]) if "job=" in r.headers.get("location", "") else 0
    with SessionLocal() as s:
        dps = [(x.title, x.text, x.kind) for x in s.scalars(select(m.ImportPiece).where(m.ImportPiece.job_id == dj).order_by(m.ImportPiece.no))]
    check("DRM 엑셀 — Excel 로 연 값이 시트 조각으로(빈 행·앞 빈칸 걷음, 날짜·숫자·참)",
          dps == [("보안 현안", "호선\t기한\nSN2511\t2026-11-05\n3\t참", "sheet")], repr(dps))
    _drm.read_sheets = lambda data, suffix=".xlsx": None
    _drm._LAST_ERR = "테스트 사유"
    r = c.post("/import/file", files={"file": ("drm.xlsx", b"DRM-ENCRYPTED-BLOB", "application/octet-stream")}, data={"dept_id": "D3"})
    check("DRM 엑셀 — 못 열면 사유를 함께 안내", "DRM 복호 불가" in r.text and "테스트 사유" in r.text)
    _drm.read_sheets = _orig_read
    # 메일함 — 휴면 · 메일 조각
    r = c.post("/import/mail", data={"dept_id": "D3"})
    check("M13 메일함 — Outlook·폴더 설정이 없으면 휴면 안내(앱은 그대로)", r.status_code == 200 and ("MEETING_MAIL_FOLDER" in r.text or "pywin32" in r.text))
    mail = {"message_id": "<m13-test@x>", "subject": "FW: 2514 카고펌프 현장 사진", "received_at": "2026-10-23 09:10",
            "html": "<p>[홍길동] [오후 3:12] 2514 카고펌프 씰 누유 재발</p><p>[김철수] [오후 3:16] 내일 씰 교체 예정</p>",
            "attachments": [("현장.png", buf.getvalue()), ("보고.pptx", data)]}
    with SessionLocal() as s:
        mj = im.import_mail(s, mail, "D5")
        again = im.import_mail(s, mail, "D5")
        mps = list(s.scalars(select(m.ImportPiece).where(m.ImportPiece.job_id == mj.id).order_by(m.ImportPiece.no)))
        body, n_img = mps[0].text, len(_json.loads(mps[0].images_json))
        s.commit()
    check("M13 메일 — 본문 한 조각(이름 걷음·그림 첨부) + 첨부 PPT 장마다", len(mps) == 4 and "홍길동" not in body and "카고펌프 씰 누유 재발" in body and n_img == 1
          and mps[1].title.startswith("보고.pptx · "), f"{len(mps)} {body[:60]}")
    check("M13 메일 — 같은 메일은 두 번 가져오지 않음", again is None)
    # 지표 화면 · 옛 주소
    r = c.get("/metrics", follow_redirects=False)
    check("M13 — /metrics → 첫 부서 지표", r.status_code == 307 and r.headers["location"].startswith("/metrics/"))
    r = c.get(f"/write/{wk}/D5?memo={mm.id}", follow_redirects=False)
    check("M13 — 옛 메모 주소 → 가져오기의 그 메모", r.status_code == 307 and r.headers["location"] == f"/import?memo={mm.id}")


def t_m12(c) -> None:
    """M12 회의 진행(기록하고 다음·결정·지시·종결 승인/되돌리기·마치기) · 지시사항 · 이슈에 쌓인 회의 기록 · 옛 섹션 이전."""
    import io as _io

    from pptx import Presentation
    from sqlalchemy import func, select

    from app import models as m
    from app.db import SessionLocal
    from app.services import migrate as mg
    from app.services import run as rn
    from app.services import studio as st
    from app.services import weeks

    wk = weeks.current().id
    nxt = rn.next_week(wk)
    with SessionLocal() as ss:
        sh = st.week_meeting(ss, wk, "share")
        ex = st.week_meeting(ss, wk, "exec")
        sid, eid = sh.id, ex.id
        d = st.version_deck(st.latest_version(ss, sh))
        ids = st.deck_block_ids(d)
        pend = [x for x in ids if ss.get(m.Block, x).status == "종결요청"]
        plain = next(x for x in ids if ss.get(m.Block, x).status in ("신규", "진행"))
        ss.get(m.Block, plain).decision_needed = "선주 협의로 일정 확정"
        ss.commit()
        held0 = ss.get(m.Meeting, sid).held_at
    # 발행 전이면 진행하지 않는다
    r = c.post(f"/meetings/{wk}/adhoc", data={"kind": "review"}, follow_redirects=False)
    aid = int(r.headers["location"].rsplit("/", 1)[1])
    r = c.get(f"/meetings/{aid}/run", follow_redirects=False)
    check("M12 — 발행 전 회의는 진행 화면 대신 보기로 + 안내", r.status_code == 303 and r.headers["location"].startswith(f"/meetings/{aid}?err="))
    r = c.get(f"/meetings/{sid}/run")
    with SessionLocal() as ss:
        held = ss.get(m.Meeting, sid).held_at
    check("M12 — 진행 화면 200 · 발표 화면 열기 · 기록하고 다음 · 회의 시작 시각", r.status_code == 200 and "발표 화면 열기" in r.text
          and "기록하고 다음" in r.text and held is not None, repr(held0))
    r = c.get(f"/meetings/{sid}/run", params={"view": "present"})
    check("M12 — 발표 화면(?view=present) 은 장만", r.status_code == 200 and "rn-present" in r.text and 'id="card"' not in r.text)
    # 코멘트 · 결정
    r = c.post(f"/api/run/{sid}/record", json={"block_id": plain, "comment": "도면 회신 대기", "decision": "다음 주 선주와 일정 확정"})
    j = r.json()
    with SessionLocal() as ss:
        b = ss.get(m.Block, plain)
        kinds = [x.kind for x in ss.scalars(select(m.MeetingComment).where(m.MeetingComment.meeting_id == sid, m.MeetingComment.block_id == plain))]
        hist_notes = [h.note for h in ss.scalars(select(m.BlockHistory).where(m.BlockHistory.block_id == plain))]
        log = ss.scalar(select(m.AiFieldLog).where(m.AiFieldLog.block_id == plain, m.AiFieldLog.field == "decision_needed").order_by(m.AiFieldLog.id.desc()))
    check("M12 — 코멘트·결정 기록 → 이슈의 「결정 필요」 칸 비움(이력 남김)", j.get("ok") and j["done"] == ["코멘트", "결정"] and b.decision_needed == ""
          and sorted(kinds) == ["comment", "decision"] and log is not None and log.human_value == "", r.text[:200])
    check("M12 — 회의 기록은 주간 한 줄(이력)에 섞지 않음", not any("도면 회신 대기" in (n or "") for n in hist_notes))
    rec = j["state"]["records"][plain]
    check("M12 — 진행 상태에 기록 표시(✓)", rec["comments"] == ["도면 회신 대기"] and rec["decision"].startswith("다음 주 선주와 일정 확정"))
    r = c.get("/issues", params={"id": plain})
    check("M12 — 이슈 원장 「주차별 진행」에 회의 결정·코멘트", "결정 — 다음 주 선주와 일정 확정" in r.text and "도면 회신 대기" in r.text)
    r = c.post(f"/api/run/{sid}/record", json={"block_id": "ISS-9999-0001", "comment": "x"})
    check("M12 — 안건이 아닌 이슈 기록 거부", r.status_code == 400 and "안건이 아닌" in r.json()["err"])
    # 지시 → 다음 주 담당 부서 회의자료 맨 위
    r = c.post(f"/api/run/{sid}/record", json={"block_id": plain, "directive": {"text": "선주 회신 받아 공유", "dept_id": "D3", "due": nxt}})
    with SessionLocal() as ss:
        dv = ss.scalar(select(m.Directive).where(m.Directive.meeting_id == sid))
        st.ensure_week_meetings(ss, nxt)
        ss.commit()
        dmn = st.week_meeting(ss, nxt, "dept", "D3")
        dmn_id, dv_id = dmn.id, dv.id
    check("M12 — 지시 기록(내용·부서·기한·이슈)", r.json()["done"] == ["지시"] and dv.dept_id == "D3" and dv.due_week_id == nxt and dv.block_id == plain)
    sj = c.get(f"/api/studio/{dmn_id}").json()["state"]
    check("M12 — 다음 주 담당 부서 회의자료 맨 위 「지난 지시사항」", [x["id"] for x in sj["directives"]] == [dv_id] and sj["directives"][0]["status"] == "열림")
    r = c.get("/home", params={"role": "d", "dept": "D3"})
    check("M12 — 홈(부서 편집자)에 지시사항 할 일", "선주 회신 받아 공유" in r.text and "완료 보고하러" in r.text)
    r = c.post(f"/api/directives/{dv_id}/done", json={"note": " "})
    check("M12 — 완료 보고 없으면 거부", r.status_code == 400 and "한 줄" in r.json()["err"])
    r = c.post(f"/api/directives/{dv_id}/done", json={"note": "선주 회신 10/28 공유 완료"})
    sj = c.get(f"/api/studio/{dmn_id}").json()["state"]
    check("M12 — 지시 완료 → 열린 지시에서 빠짐(이번 주 완료분만 회의자료에)", r.json()["directive"]["status"] == "완료"
          and all(x["id"] != dv_id or x["status"] == "완료" for x in sj["directives"]))
    c.post(f"/api/directives/{dv_id}/reopen")
    r = c.get(f"/export/meeting/{dmn_id}/pptx")
    texts = ["".join(sh_.text_frame.text for sh_ in sl.shapes if sh_.has_text_frame) for sl in Presentation(_io.BytesIO(r.content)).slides]
    check("M12 — 부서 자료 PPT 에 「지난 지시사항」 장(표지 다음)", len(texts) >= 2 and "지난 지시사항" in texts[1] and "선주 회신 받아 공유" in texts[1])
    with SessionLocal() as ss:
        nxt_share = st.week_meeting(ss, nxt, "share")
        dirs_next = rn.directives_for(ss, nxt_share)
    check("M12 — 다음 주 공유회 첫머리 「지난 지시 점검」", any(x["id"] == dv_id for x in dirs_next))
    # 종결 승인 · 되돌리기 · 보류
    if pend:
        bid = pend[0]
        r = c.post(f"/api/run/{eid}/record", json={"block_id": bid, "close": "ok", "cause": "씰 마모"})
        check("M12 — 종결 승인은 공유회에서만(팀장 정보회의 거부)", r.status_code == 400 and "공유회" in r.json()["err"])
        r = c.post(f"/api/run/{sid}/record", json={"block_id": bid, "close": "ok", "cause": "씰 마모"})
        with SessionLocal() as ss:
            n_card = ss.scalar(select(func.count()).select_from(m.CaseCard).where(m.CaseCard.block_id == bid))
            st_ = ss.get(m.Block, bid).status
        check("M12 — 진행 화면 종결 승인 → 사례 카드", r.json().get("ok") and n_card == 1 and st_ == "종결" and r.json()["state"]["records"][bid]["close"] == "승인", r.text[:200])
        r = c.post(f"/api/run/{sid}/undo-close", json={"block_id": bid})
        with SessionLocal() as ss:
            n_card = ss.scalar(select(func.count()).select_from(m.CaseCard).where(m.CaseCard.block_id == bid))
            st_ = ss.get(m.Block, bid).status
            dec = ss.scalar(select(m.Closure.decision).where(m.Closure.block_id == bid).order_by(m.Closure.id.desc()))
        check("M12 — 되돌리기 → 사례 카드 지움·종결 요청 상태", n_card == 0 and st_ == "종결요청" and dec == "대기", f"{n_card} {st_} {dec}")
        c.post(f"/api/run/{sid}/record", json={"block_id": bid, "close": "hold", "comment": "재시운전 결과 보고 뒤"})
        with SessionLocal() as ss:
            st_ = ss.get(m.Block, bid).status
        check("M12 — 보류 → 진행으로", st_ == "진행")
    else:
        check("M12 — 시험용 종결 요청 안건", False, "공유회 발행본에 종결 요청이 없음")
    # 마치기
    r = c.post(f"/api/run/{sid}/finish")
    check("M12 — 회의 마치기 → 종료", r.json()["state"]["meeting"]["status"] == "종료")
    r = c.post(f"/api/run/{sid}/record", json={"block_id": plain, "comment": "늦은 기록"})
    check("M12 — 끝난 회의엔 기록 거부", r.status_code == 400 and "끝난 회의" in r.json()["err"])
    r = c.post(f"/api/studio/{sid}/publish")
    check("M12 — 끝난 회의 자료는 고칠 수 없음", r.status_code == 400 and "끝난 회의" in r.json()["err"])
    r = c.get(f"/meetings/{sid}")
    check("M12 — 끝난 회의 보기 → 「회의 기록 보기」", "회의 기록 보기" in r.text)
    # 옛 섹션 이전(dry-run 성격: 같은 세션에서 두 번 → 두 번째는 건너뜀)
    with SessionLocal() as ss:
        sec = ss.scalar(select(m.Section).where(m.Section.week_id < wk, m.Section.status == "확정").order_by(m.Section.week_id))
        swk, sdept = (sec.week_id, sec.department_id) if sec else ("", "")
        rep1 = mg.migrate(ss, wk)
        ss.commit()
        rep2 = mg.migrate(ss, wk)
        ss.commit()
        dm = st.week_meeting(ss, swk, "dept", sdept) if sec else None
        n_items = len(st.items(ss, dm)) if dm else 0
        v = st.latest_version(ss, dm)
        shv = st.latest_version(ss, st.week_meeting(ss, swk, "share")) if sec else None
        mig = st.version_deck(v)["meeting"].get("migrated") if v else None
    check("M12 이전 — 확정 섹션 → 부서 자료(장)·제출 1판·공유회 발행 1판·이전 표시", sec is not None and n_items > 0 and v is not None and v.version == 1
          and shv is not None and mig is True, f"{swk} {sdept} {n_items} {rep1.dept_decks[:3]}")
    check("M12 이전 — 다시 실행해도 중복 없음", rep1.dept_decks and not rep2.dept_decks and not rep2.shares, f"{len(rep1.dept_decks)} {len(rep2.dept_decks)}")
    r = c.get(f"/meetings/{shv.meeting_id}") if shv else None
    check("M12 이전 — 지난 공유회도 「보기」로 열림", r is not None and r.status_code == 200 and "발행 1판" in r.text)


def t_m11(c) -> None:
    """M11 공유회 취합(참조)·종결 요청 자동·원장으로 채우기·부서 순서·발행 판 고정·변경 n·2판·팀장 정보회의·보기·PPT·옛 진행 화면 안건."""
    import io as _io

    from pptx import Presentation
    from sqlalchemy import func, select

    from app import models as m
    from app.db import SessionLocal
    from app.services import studio as st
    from app.services import weeks

    wk = weeks.current().id
    with SessionLocal() as ss:
        share = st.week_meeting(ss, wk, "share")
        exe = st.week_meeting(ss, wk, "exec")
        dm = ss.scalar(select(m.Meeting).where(m.Meeting.week_id == wk, m.Meeting.kind == "dept", m.Meeting.version >= 1).order_by(m.Meeting.id))
        sid, eid, did, ddept = share.id, exe.id, dm.id, dm.owner_dept_id
        other = ss.scalar(select(m.Department.id).where(m.Department.id != ddept, m.Department.id.in_(
            select(m.Block.owner_department_id).where(m.Block.block_type.in_(("issue", "problem")), m.Block.status.in_(("신규", "진행"))))).limit(1))
    # 1) 공유회 = 부서 제출판 참조
    sstate = c.get(f"/api/studio/{sid}").json()["state"]
    sec = next(x for x in sstate["sections"] if x["dept_id"] == ddept)
    refs = [it for it in sstate["items"] if it["ref"] == did]
    check("M11 — 공유회 부서 칸 = 그 부서 제출판(참조·읽기 전용)", sec["state"].startswith("제출 1판") and refs and all(it["ro"] for it in refs), repr(sec))
    check("M11 — 제출 뒤 부서가 고치면 공유회 칸에 「뒤에 수정됨」", "뒤에 수정됨" in sec["state"], sec["state"])
    sub_lines = [it["line"] for it in refs]
    dst = c.get(f"/api/studio/{did}").json()["state"]
    own0 = dst["items"][0]
    c.post(f"/api/studio/items/{own0['id']}", json={"field": "line", "value": "제출 뒤 고친 한 줄"})
    sstate = c.get(f"/api/studio/{sid}").json()["state"]
    check("M11 — 제출 뒤 고친 한 줄은 다시 제출 전까지 공유회에 안 보임(판 고정)",
          "제출 뒤 고친 한 줄" not in [it["line"] for it in sstate["items"] if it["ref"] == did] and [it["line"] for it in sstate["items"] if it["ref"] == did] == sub_lines)
    # 사실은 발행 전 자료까지 바로 따른다
    rb = refs[0]["blocks"][0]["id"]
    c.post(f"/api/issues/{rb}/field", json={"field": "action_text", "value": "M11 조치 반영"})
    sstate = c.get(f"/api/studio/{sid}").json()["state"]
    check("M11 — 이슈 사실(조치)은 발행 전 공유회 장에 바로 반영", any(b["act"] == "M11 조치 반영" for it in sstate["items"] for b in it["blocks"] if b["id"] == rb))
    # 2) 종결 요청 자동 채택
    in_deck = {b["id"] for it in sstate["items"] for b in it["blocks"]}
    with SessionLocal() as ss:
        cl = ss.scalar(select(m.Block).where(m.Block.block_type == "issue", m.Block.status.in_(("신규", "진행")), m.Block.id.not_in(in_deck)).order_by(m.Block.id.desc()))
        cl_id = cl.id
    c.post(f"/issues/{cl_id}/close-request", data={"action_text": "교체 완료"})
    sstate = c.get(f"/api/studio/{sid}").json()["state"]
    auto = [it for it in sstate["items"] if it["src"] == "종결 요청" and it["blocks"][0]["id"] == cl_id]
    check("M11 — 종결 요청 이슈는 공유회에 자동으로 들어감(머리표 종결승인 대기)", len(auto) == 1 and auto[0]["blocks"][0]["ptag"] == "종결승인 대기", repr([it["src"] for it in sstate["items"]]))
    c.get(f"/api/studio/{sid}")
    n_auto = len([it for it in c.get(f"/api/studio/{sid}").json()["state"]["items"] if it["src"] == "종결 요청" and it["blocks"][0]["id"] == cl_id])
    check("M11 — 자동 채택은 두 번 열어도 한 번만", n_auto == 1, str(n_auto))
    # 3) 원장으로 채우기 · 부서 순서
    r = c.post(f"/api/studio/{sid}/fill", json={"dept_id": ddept})
    check("M11 — 제출한 부서는 원장으로 채우기 거부", r.status_code == 400 and "이미 제출한" in r.json()["err"])
    if other:
        r = c.post(f"/api/studio/{sid}/fill", json={"dept_id": other})
        j = r.json()
        osec = next(x for x in j["state"]["sections"] if x["dept_id"] == other) if j.get("ok") else {}
        check("M11 — 미제출 부서 「원장으로 채우기」 → 한 줄 장 · 칸 상태", j.get("ok") and j["added"] >= 1 and "원장으로 채움" in osec.get("state", "")
              and all(it["form"] == "line" for it in j["state"]["items"] if it["src"] == "원장 채움"), r.text[:200])
    order0 = [x["dept_id"] for x in sstate["sections"]]
    r = c.post(f"/api/studio/{sid}/dept-move", json={"dept_id": order0[1], "step": -1})
    order1 = [x["dept_id"] for x in r.json()["state"]["sections"]]
    check("M11 — 부서 순서 위로", order1[:2] == [order0[1], order0[0]], repr(order1[:3]))
    r = c.post(f"/api/studio/{sid}/reorder", json={"ids": []})
    check("M11 — 공유회는 장 순서를 직접 못 바꿈(부서 자료에서)", r.status_code == 400)
    # 4) 발행 → 판 고정
    r = c.post(f"/api/studio/{sid}/publish")
    j = r.json()
    with SessionLocal() as ss:
        nv = ss.scalar(select(func.count()).select_from(m.MeetingVersion).where(m.MeetingVersion.meeting_id == sid))
    check("M11 — 공유회 발행 → 1판 · 판 기록", j.get("ok") and j["version"] == 1 and j["state"]["meeting"]["status"] == "발행" and nv == 1, r.text[:200])
    r = c.get(f"/meetings/{sid}")
    check("M11 — 회의자료 보기: 발행 1판 · 회의 시작 · PPT", r.status_code == 200 and "발행 1판" in r.text and "회의 시작" in r.text and f"/export/meeting/{sid}/pptx" in r.text)
    r = c.get(f"/meeting/{wk}")
    check("M12 — 옛 회의 주소 → 공유회 보기(발행 1판)", str(r.url).endswith(f"/meetings/{sid}") and "발행 1판" in r.text)
    with SessionLocal() as ss:
        pub = st.published_blocks(ss, wk)
        b_title = ss.get(m.Block, rb).title
    r = c.get(f"/meeting/{wk}/present", params={"d": ddept})
    check("M12 — 옛 발표 주소 → 새 진행 화면 · 안건 = 발행본", str(r.url).endswith(f"/meetings/{sid}/run") and pub is not None
          and rb in pub.get(ddept, []) and b_title in r.text and 'id="rnState0"' in r.text)
    # 5) 발행 뒤 사실 변경 → 「변경」, 발행본은 그대로
    c.post(f"/api/issues/{rb}/field", json={"field": "action_text", "value": "발행 뒤 바뀐 조치"})
    sj = c.get(f"/api/studio/{sid}").json()["state"]
    r = c.get(f"/meetings/{sid}")
    with SessionLocal() as ss:
        snap = st.version_deck(st.latest_version(ss, ss.get(m.Meeting, sid)))
    frozen = [b["act"] for sec_ in snap["sections"] for it in sec_["items"] for b in it["blocks"] if b["id"] == rb]
    check("M11 — 발행 뒤 사실이 바뀌면 「변경 n」 · 발행본은 그대로", sj["meeting"]["changes"] >= 1 and "발행 뒤 변경" not in r.text.split("mvState")[0] and "이슈 사실이 바뀐 장" in r.text
          and frozen == ["M11 조치 반영"], repr(frozen))
    with SessionLocal() as ss:
        ch = st.changes(ss, ss.get(m.Meeting, sid))
    check("M11 — 변경 목록에 무엇이 바뀌었는지(조치)", any(x["block_id"] == rb and "조치" in x["fields"] for x in ch), repr(ch[:2]))
    r = c.post(f"/api/studio/{sid}/publish")
    j = r.json()
    check("M11 — 다시 발행 → 2판 · 변경 0", j["version"] == 2 and j["state"]["meeting"]["changes"] == 0)
    r = c.post(f"/api/studio/{sid}/publish")
    check("M11 — 바뀐 것 없이 다시 발행하면 거부(판이 헛되이 오르지 않음)", r.status_code == 400 and "2판과 같습니다" in r.json()["err"])
    # 6) 팀장 정보회의
    ex = c.get(f"/api/studio/{eid}").json()["state"]
    groups = {g["group"]: [b["id"] for b in g["blocks"]] for g in ex["candidates"]}
    g0 = next((k for k in groups if k.startswith("공유회 자료(발행 2판)")), None)
    check("M11 — 팀장 정보회의 후보: 공유회 발행본·중요·장기 미결·이번 주 종결·원장 직접", g0 and rb in groups[g0]
          and set(groups) >= {"중요 표시", "장기 미결", "이번 주 종결", "원장 직접"}, repr(list(groups)))
    r = c.post(f"/api/studio/{eid}/items", json={"block_id": rb})
    check("M11 — 팀장 정보회의 장 기본 형태 = 한 줄", r.json()["state"]["items"][0]["form"] == "line")
    r = c.get(f"/export/meeting/{eid}/pptx")
    texts = ["".join(sh.text_frame.text for sh in sl.shapes if sh.has_text_frame) for sl in Presentation(_io.BytesIO(r.content)).slides]
    check("M11 — 발행 전 PPT 는 「구성 중」 · 표지 + 장", r.status_code == 200 and len(texts) == 2 and "구성 중" in texts[0] and "이번 주 종결" in texts[0], repr(len(texts)))
    r = c.post(f"/api/studio/{eid}/submit")
    check("M11 — 팀장 정보회의는 「제출」이 아니라 「발행」", r.status_code == 400 and "발행" in r.json()["err"])
    r = c.post(f"/api/studio/{eid}/publish")
    check("M11 — 팀장 정보회의 발행", r.json().get("ok") and r.json()["version"] == 1)
    # 7) 공유회 PPT — 발행본 그대로: 표지 + 부서 구분 장 + 장
    r = c.get(f"/export/meeting/{sid}/pptx")
    texts = ["".join(sh.text_frame.text for sh in sl.shapes if sh.has_text_frame) for sl in Presentation(_io.BytesIO(r.content)).slides]
    with SessionLocal() as ss:
        snap = st.version_deck(st.latest_version(ss, ss.get(m.Meeting, sid)))
    want = 1 + sum(1 + len(x["items"]) for x in snap["sections"])
    check("M11 — 공유회 PPT = 표지 + 부서 구분 장 + 장(발행본) · 「구성 중」 없음", len(texts) == want and not any("구성 중" in t for t in texts)
          and "부서 제출" in texts[0], f"{len(texts)}/{want}")
    # 8) 홈 · 목록
    r = c.get("/home", params={"role": "p"})
    check("M11 — 홈(기획): 공유회 자료 · 팀장 정보회의 자료 → 스튜디오", f"/studio/{sid}" in r.text and f"/studio/{eid}" in r.text and "부서 제출" in r.text)
    r = c.get("/meetings")
    check("M11 — 회의 목록: 발행한 회의는 「보기 →」", f'href="/meetings/{sid}"' in r.text and "보기 →" in r.text)
    r = c.get("/meetings/999999")
    check("M11 — 없는 회의 보기는 404", r.status_code == 404)


def t_events(c) -> None:
    """결정 ⑦ 첫 조각 — 사실 칸 변경은 block_event 에 이전→이후·어디서(작업대/부서/공유회/팀장)로 남는다."""
    from sqlalchemy import select
    from app import models as m
    from app.db import SessionLocal
    from app.services import events
    with SessionLocal() as s:
        b = s.scalar(select(m.Block).where(m.Block.block_type.in_(("issue", "problem"))).limit(1))
        mt = s.scalar(select(m.Meeting).where(m.Meeting.kind == "dept").limit(1))
        bid, mid = b.id, (mt.id if mt else None)
        n0 = len(s.scalars(select(m.BlockEvent).where(m.BlockEvent.block_id == bid)).all())
    r = c.post(f"/api/issues/{bid}/field", json={"field": "cause_text", "value": "결정7 원인 A"})
    check("결정⑦ — 작업대에서 원인 저장", r.status_code == 200 and r.json().get("ok"), r.text[:120])
    r = c.post(f"/api/issues/{bid}/field", json={"field": "cause_text", "value": "결정7 원인 B", "meeting_id": mid})
    check("결정⑦ — 스튜디오 사실 칸에서 원인 저장", r.status_code == 200 and r.json().get("ok"), r.text[:120])
    c.post(f"/api/issues/{bid}/field", json={"field": "cause_text", "value": "결정7 원인 B", "meeting_id": mid})   # 같은 값
    with SessionLocal() as s:
        evs = s.scalars(select(m.BlockEvent).where(m.BlockEvent.block_id == bid).order_by(m.BlockEvent.id)).all()[n0:]
        check("결정⑦ — 바뀐 2번만 기록(같은 값은 기록 안 함)", len(evs) == 2, str(len(evs)))
        if len(evs) == 2:
            a, z = evs
            check("결정⑦ — 첫 기록: 작업대 · 사실변경 · 원인", (a.stage, a.kind, a.field) == ("작업대", "사실변경", "cause_text"), f"{a.stage} {a.kind} {a.field}")
            check("결정⑦ — 둘째 기록: 부서 단계 · 회의 id · 이전→이후", z.stage == ("부서" if mid else "작업대") and z.meeting_id == mid
                  and z.before == "결정7 원인 A" and z.after == "결정7 원인 B", f"{z.stage} {z.meeting_id} {z.before}→{z.after}")
        check("결정⑦ — 관계 값에 파생·합쳐짐", {"파생", "합쳐짐"} <= set(events.LINK_RELATIONS))
        try:
            events.record(s, bid, "엉뚱함"); ok = False
        except ValueError:
            ok = True
        check("결정⑦ — 모르는 기록 종류는 거부", ok)
        s.rollback()
    page = c.get(f"/issues?id={bid}").text
    check("결정⑦ — 이슈 화면 「변경 기록」에 보임", "변경 기록" in page and "결정7 원인 B" in page)



def t_llm_c(c) -> None:
    t_llm()


# 묶음 순서 = 실행 순서. 앞 묶음이 만든 데이터를 뒤 묶음이 쓴다. tests/test_NN_*.py 도 이 순서를 따른다
GROUPS = (t_masters_api, t_hub, t_llm_c, t_write_flow, t_carry, t_photos, t_metrics, t_meeting, t_export,
          t_knowledge, t_save_and_extract,          # 블록 ID 를 새로 쓰므로 뒤쪽에
          t_unregistered, t_dashboard_report, t_settings, t_central, t_m9, t_m10, t_m11, t_m12, t_m13, t_f16_f21, t_events)


def main() -> int:
    for fn in (t_paths, t_tokens, t_weeks, t_sn, t_app):
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — 한 묶음이 죽어도 나머지는 돌린다
            import traceback; traceback.print_exc()
            check(f"{fn.__name__} 실행", False, repr(e))
    n_fail = sum(1 for ok, _ in _results if not ok)
    print("-" * 64)
    print(f"{'[FAIL]' if n_fail else '[PASS]'} {len(_results) - n_fail}/{len(_results)} 통과")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
