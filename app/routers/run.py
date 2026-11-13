"""회의 진행 · 종결 · 지시사항 — JSON 동작 엔드포인트(M12). 화면(GET /meetings/{id}/run)은 main.py 의 _page 로 그린다.

진행 화면의 동작은 바뀐 뒤의 진행 상태 전체(`run.state`)를 돌려준다. 홈의 종결 승인·보류는 폼 POST → 303(홈으로).
오류는 고치는 법을 담은 한국어 문장(400).
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import models as m
from app.db import get_session
from app.llm import client as llm
from app.services import meeting as mts
from app.services import promotion
from app.services import run as rn
from app.services import weeks
from app.services import writing as w

router = APIRouter()


def _meeting(s: Session, mid: int) -> m.Meeting:
    mt = s.get(m.Meeting, mid)
    if mt is None:
        raise HTTPException(404, "없는 회의입니다. 회의 목록에서 다시 골라주세요.")
    return mt


def _run(s: Session, mt: m.Meeting, fn, extra=None):
    try:
        out = fn()
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    s.refresh(mt)
    try:
        st_ = rn.state(s, mt)
    except w.WriteError:          # 발행 전 회의(회의 중 등록·회의록만 쓴 경우) — 진행 상태 없이 돌려준다
        st_ = None
    body = {"ok": True, "state": st_}
    if extra is not None:
        body.update(extra(out))
    return body


@router.get("/api/run/{mid}")
def api_state(mid: int, s: Session = Depends(get_session)):
    mt = _meeting(s, mid)
    try:
        return {"ok": True, "state": rn.state(s, mt)}
    except w.WriteError as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)


@router.post("/api/run/{mid}/record")
async def api_record(mid: int, request: Request, s: Session = Depends(get_session)):
    """한 안건 기록 — {block_id, comment, decision, directive:{text, dept_id, due}, close: ok|hold, cause}."""
    mt, d = _meeting(s, mid), await request.json()
    return _run(s, mt, lambda: rn.record(s, mt, str(d.get("block_id", "")), str(d.get("comment", "")), str(d.get("decision", "")),
                                         d.get("directive") if isinstance(d.get("directive"), dict) else None,
                                         str(d.get("close", "")), str(d.get("cause", ""))), lambda done: {"done": done})


@router.post("/api/run/{mid}/undo-close")
async def api_undo_close(mid: int, request: Request, s: Session = Depends(get_session)):
    mt, d = _meeting(s, mid), await request.json()
    return _run(s, mt, lambda: rn.undo_close(s, str(d.get("block_id", "")), mt.week_id))


@router.post("/api/run/{mid}/finish")
def api_finish(mid: int, s: Session = Depends(get_session)):
    mt = _meeting(s, mid)
    return _run(s, mt, lambda: rn.finish(s, mt))


@router.post("/api/run/{mid}/register")
async def api_register(mid: int, request: Request, s: Session = Depends(get_session)):
    """회의 중 새 이슈 — 다음 주 그 부서 회의자료 후보에 나온다."""
    mt, d = _meeting(s, mid), await request.json()
    return _run(s, mt, lambda: mts.register(s, mt.week_id, str(d.get("title", "")), str(d.get("dept_id", "")), str(d.get("block_type", "issue"))),
                lambda b: {"block_id": b.id})


@router.post("/api/run/{mid}/minutes")
async def api_minutes(mid: int, request: Request, s: Session = Depends(get_session)):
    """회의록 메모 → 후보(새 이슈 / 기존 이슈 연결). 근거가 메모와 맞지 않는 것은 버린다."""
    mt, d = _meeting(s, mid), await request.json()
    try:
        out = mts.extract_minutes(s, mt.week_id, str(d.get("raw_text", "")), mt)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    if not out.result.ok:
        return JSONResponse({"ok": False, "err": "회의록 추출에 실패했습니다 — " + " / ".join(out.result.errors)}, status_code=400)
    return {"ok": True, "added": len(out.added), "dropped": out.dropped, "provider": llm.LABELS.get(out.result.provider, out.result.provider),
            "candidates": candidates_json(s, mt)}


def candidates_json(s: Session, mt: m.Meeting) -> list[dict]:
    return [{"id": c.id, "raw": c.raw_text, "title": c.suggested_title, "dept_id": c.suggested_department_id or "",
             "link": c.linked_block_id or "", "state": c.state} for c in mts.candidates(s, mt.week_id, mt)]


@router.post("/api/run/{mid}/candidates/{cid}/{action}")
async def api_candidate(mid: int, cid: int, action: str, request: Request, s: Session = Depends(get_session)):
    mt, d = _meeting(s, mid), await request.json()
    c = s.get(m.MeetingCandidate, cid)
    if c is None or c.meeting_id != mt.id:
        raise HTTPException(404, "후보를 찾을 수 없습니다.")
    try:
        if action == "register":
            b = mts.candidate_register(s, c, mt.week_id, str(d.get("title", "")), str(d.get("dept_id", "")))
            msg = f"후보 → {b.id} 등록"
        elif action == "link":
            b = mts.candidate_link(s, c, mt.week_id, str(d.get("block_id", "")))
            msg = f"후보 → {b.id} 에 연결 (회의 기록으로 남김)"
        elif action == "drop":
            mts.candidate_drop(s, c)
            msg = "후보를 버렸습니다"
        else:
            raise HTTPException(404, "없는 동작입니다.")
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    return {"ok": True, "msg": msg, "candidates": candidates_json(s, mt)}


# ── 지시사항 ────────────────────────────────────────────
def _directive(s: Session, did: int) -> m.Directive:
    dv = s.get(m.Directive, did)
    if dv is None:
        raise HTTPException(404, "없는 지시사항입니다. 화면을 새로 고쳐주세요.")
    return dv


@router.post("/api/directives/{did}/done")
async def api_directive_done(did: int, request: Request, s: Session = Depends(get_session)):
    dv, d = _directive(s, did), await request.json()
    try:
        rn.complete_directive(s, dv, str(d.get("note", "")), weeks.current().id)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    return {"ok": True, "directive": rn.directive_json(s, dv, weeks.current().id)}


@router.post("/api/directives/{did}/reopen")
def api_directive_reopen(did: int, s: Session = Depends(get_session)):
    dv = _directive(s, did)
    rn.reopen_directive(s, dv)
    s.commit()
    return {"ok": True, "directive": rn.directive_json(s, dv, weeks.current().id)}


# ── 홈(기획 주관자)의 종결 승인·보류 ─────────────────────
def _home(msg: str = "", err: str = "") -> RedirectResponse:
    q = "&".join(x for x in ("role=p", f"msg={quote(msg)}" if msg else "", f"err={quote(err)}" if err else "") if x)
    return RedirectResponse(f"/home?{q}#closures", status_code=303)


@router.post("/closures/{cid}/approve")
def post_approve(cid: int, cause_text: str = Form(""), s: Session = Depends(get_session)):
    c = s.get(m.Closure, cid)
    if c is None:
        raise HTTPException(404, "종결 요청을 찾을 수 없습니다.")
    b = s.get(m.Block, c.block_id)
    try:
        card = promotion.approve(s, c, weeks.current().id, cause_text or (b.cause_text if b else ""))
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _home(err=str(e))
    return _home(msg=f"{c.block_id} 종결 승인 → 사례 카드 {card.id} 가 지식창고에 등록됐습니다")


@router.post("/closures/{cid}/hold")
def post_hold(cid: int, reason: str = Form(""), s: Session = Depends(get_session)):
    c = s.get(m.Closure, cid)
    if c is None:
        raise HTTPException(404, "종결 요청을 찾을 수 없습니다.")
    try:
        promotion.hold(s, c, weeks.current().id, reason)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _home(err=str(e))
    return _home(msg=f"{c.block_id} 보류 — 진행으로 돌아가 다음 주에 다시 봅니다")
