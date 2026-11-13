"""이슈 원장 · 홈 — 저장·동작 엔드포인트 (M9). 화면(GET /home · /issues)은 main.py 의 _page 로 그린다.

자동 저장은 JSON(`/api/issues/...`)으로 받고, 버튼 동작(초안 완료·종결 요청·일괄)은 폼 POST → 303 으로 돌아간다.
오류는 고치는 법을 담은 한국어 문장으로 돌려준다(writing.WriteError).
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import models as m
from app.db import get_session
from app.services import carry_over as co
from app.services import closure as cl
from app.services import issues as iss
from app.services import weeks
from app.services import writing as w

router = APIRouter()


def _block(s: Session, block_id: str) -> m.Block:
    b = s.get(m.Block, block_id)
    if b is None:
        raise HTTPException(404, f"{block_id} 이슈가 없습니다. 이슈 원장에서 다시 골라주세요.")
    return b


def _to(block_id: str = "", msg: str = "", err: str = "", extra: str = "") -> RedirectResponse:
    q = [f"id={quote(block_id)}"] if block_id else []
    if msg:
        q.append("msg=" + quote(msg))
    if err:
        q.append("err=" + quote(err))
    if extra:
        q.append(extra)
    return RedirectResponse("/issues" + ("?" + "&".join(q) if q else ""), status_code=303)


@router.post("/api/issues/{block_id}/field")
async def api_field(block_id: str, request: Request, s: Session = Depends(get_session)):
    """작업대 자동 저장 — {field, value}."""
    data = await request.json()
    b = _block(s, block_id)
    try:
        mid = data.get("meeting_id")
        changed = iss.save_field(s, b, str(data.get("field", "")), str(data.get("value", "")),
                                 meeting_id=int(mid) if str(mid or "").isdigit() else None)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    return {"ok": True, "changed": changed, "draft_state": b.draft_state, "draft_label": iss.DRAFT_LABEL[b.draft_state]}


@router.post("/api/issues/{block_id}/line")
async def api_line(block_id: str, request: Request, s: Session = Depends(get_session)):
    """이번 주 한 줄 — 홈·작업대에서. 「변동 없음」도 한 줄로 남긴다."""
    data = await request.json()
    b = _block(s, block_id)
    try:
        co.update_line(s, b, weeks.current().id, str(data.get("text", "")))
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    return {"ok": True}


@router.post("/issues/{block_id}/draft-done")
def post_draft_done(block_id: str, s: Session = Depends(get_session)):
    b = _block(s, block_id)
    try:
        nxt = iss.draft_done(s, b)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _to(block_id, err=f"{block_id}: {e}")
    if nxt is None:
        return _to(block_id, msg=f"{block_id} 초안 완료 — 초안이 남은 이슈가 없습니다", extra="done=1")
    return _to(nxt.id, msg=f"{block_id} 초안 완료 — 다음 초안 {nxt.id}")


@router.post("/issues/{block_id}/close-request")
def post_close(block_id: str, action_text: str = Form(""), s: Session = Depends(get_session)):
    b = _block(s, block_id)
    try:
        if action_text.strip() and action_text.strip() != (b.action_text or "").strip():
            iss.save_field(s, b, "action_text", action_text)
        cl.request(s, b, weeks.current().id, action_text or b.action_text)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _to(block_id, err=f"{block_id}: {e}")
    return _to(block_id, msg=f"{block_id} 종결 요청 — 부서 현안 공유회에서 승인됩니다")


@router.post("/issues/bulk")
async def post_bulk(request: Request, s: Session = Depends(get_session)):
    form = await request.form()
    ids = [str(x) for x in form.getlist("ids")]
    action, value, back = str(form.get("action", "")), str(form.get("value", "")), str(form.get("back", ""))
    if not ids:
        return _to(back, err="고른 이슈가 없습니다. 목록에서 체크한 뒤 다시 눌러주세요.")
    try:
        done = iss.bulk(s, ids, action, value, weeks.current().id)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _to(back, err=f"한꺼번에 바꾸지 못했습니다 — {e} (아무것도 바뀌지 않았습니다)")
    label = {"transfer": "부서 이관", "status": "상태 변경", "adopt": "회의자료에 넣기"}.get(action, action)
    return _to(back, msg=f"{len(done)}건 {label} — 이력이 남았습니다")


# ── F21 일정 경보 ───────────────────────────────────────
@router.post("/issues/{block_id}/due")
def post_due(block_id: str, event: str = Form(""), due: str = Form(""), days: str = Form(""), s: Session = Depends(get_session)):
    from app.services import alerts as al
    b = _block(s, block_id)
    try:
        al.set_due(s, b, event, due, days)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _to(block_id, err=f"{block_id}: {e}")
    st = al.state(s, b)
    return _to(block_id, msg=f"{block_id} 「~전 해결」 " + (st["chip"] if st else "목표 없음"))


@router.post("/issues/{block_id}/alert-off")
def post_alert_off(block_id: str, reason: str = Form(""), s: Session = Depends(get_session)):
    from app.services import alerts as al
    b = _block(s, block_id)
    try:
        al.dismiss(s, b, reason)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _to(block_id, err=f"{block_id}: {e}")
    return _to(block_id, msg=f"{block_id} 경보 해제 — 날짜가 당겨지거나 목표를 바꾸면 다시 켜집니다")


@router.post("/issues/{block_id}/alert-on")
def post_alert_on(block_id: str, s: Session = Depends(get_session)):
    from app.services import alerts as al
    b = _block(s, block_id)
    al.undismiss(s, b)
    s.commit()
    return _to(block_id, msg=f"{block_id} 경보를 다시 켰습니다")
