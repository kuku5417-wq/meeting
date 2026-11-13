"""회의자료 스튜디오 — JSON 동작 엔드포인트(M10 시험 → M11 공식). 화면(GET /meetings · /meetings/{id} · /studio/{id})은 main.py 의 _page 로 그린다.

모든 동작은 바뀐 뒤의 스튜디오 상태 전체(`studio.state`)를 돌려준다 — 화면은 그것으로 다시 그린다.
오류는 고치는 법을 담은 한국어 문장(400). 사실(원인·조치·결정 필요) 수정은 이슈 API(`/api/issues/{id}/field`)를 그대로 쓴다.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import models as m
from app.db import get_session
from app.services import studio as st
from app.services import weeks
from app.services import writing as w

router = APIRouter()


def _meeting(s: Session, mid: int) -> m.Meeting:
    mt = s.get(m.Meeting, mid)
    if mt is None:
        raise HTTPException(404, "없는 회의입니다. 회의 목록에서 다시 골라주세요.")
    return mt


def _item(s: Session, iid: int) -> m.ReportItem:
    it = s.get(m.ReportItem, iid)
    if it is None:
        raise HTTPException(404, "없는 장입니다. 화면을 새로 고쳐주세요.")
    return it


def _run(s: Session, mt: m.Meeting, fn, extra: dict | None = None):
    try:
        out = fn()
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    s.refresh(mt)
    body = {"ok": True, "state": st.state(s, mt)}
    if extra is not None:
        body.update(extra(out) if callable(extra) else extra)
    return body


@router.post("/meetings/{week_id}/adhoc")
def post_adhoc(week_id: str, kind: str = Form(""), hull_id: str = Form(""), held_on: str = Form(""), s: Session = Depends(get_session)):
    if weeks.parse(week_id) is None:
        raise HTTPException(404, "주차 형식이 맞지 않습니다. 2026-W43 처럼 입력해주세요.")
    try:
        d = date.fromisoformat(held_on) if held_on else None
    except ValueError:
        d = None
    try:
        mt = st.create_adhoc(s, week_id, kind, hull_id.strip().upper(), d)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        from urllib.parse import quote
        return RedirectResponse(f"/meetings?err={quote(str(e))}", status_code=303)
    return RedirectResponse(f"/studio/{mt.id}", status_code=303)


@router.get("/api/studio/{mid}")
def api_state(mid: int, s: Session = Depends(get_session)):
    mt = _meeting(s, mid)
    if st.sync_share(s, mt):          # 종결 요청 자동 채택(공유회, 발행 전)
        s.commit()
    return {"ok": True, "state": st.state(s, mt)}


@router.post("/api/studio/{mid}/start")
async def api_start(mid: int, request: Request, s: Session = Depends(get_session)):
    mt, data = _meeting(s, mid), await request.json()
    return _run(s, mt, lambda: st.start(s, mt, str(data.get("mode", ""))), lambda out: {"added": len(out)})


@router.post("/api/studio/{mid}/items")
async def api_add(mid: int, request: Request, s: Session = Depends(get_session)):
    mt, data = _meeting(s, mid), await request.json()
    return _run(s, mt, lambda: st.add_item(s, mt, str(data.get("block_id", "")), str(data.get("src", "원장"))), lambda it: {"item_id": it.id})


@router.post("/api/studio/items/{iid}")
async def api_update(iid: int, request: Request, s: Session = Depends(get_session)):
    it, data = _item(s, iid), await request.json()
    mt = s.get(m.Meeting, it.meeting_id)
    return _run(s, mt, lambda: st.update_item(s, it, str(data.get("field", "")), data.get("value")))


@router.post("/api/studio/{mid}/reorder")
async def api_reorder(mid: int, request: Request, s: Session = Depends(get_session)):
    mt, data = _meeting(s, mid), await request.json()
    return _run(s, mt, lambda: st.reorder(s, mt, [int(x) for x in data.get("ids", [])]))


@router.post("/api/studio/items/{iid}/remove")
def api_remove(iid: int, s: Session = Depends(get_session)):
    it = _item(s, iid)
    mt = s.get(m.Meeting, it.meeting_id)
    return _run(s, mt, lambda: st.remove_item(s, it), lambda snap: {"snapshot": snap})


@router.post("/api/studio/{mid}/restore")
async def api_restore(mid: int, request: Request, s: Session = Depends(get_session)):
    mt, data = _meeting(s, mid), await request.json()
    return _run(s, mt, lambda: st.restore(s, mt, data.get("snapshot") or {}), lambda it: {"item_id": it.id})


@router.post("/api/studio/{mid}/summary")
async def api_summary(mid: int, request: Request, s: Session = Depends(get_session)):
    mt, data = _meeting(s, mid), await request.json()
    return _run(s, mt, lambda: st.summarize(s, mt, [int(x) for x in data.get("ids", [])]), lambda it: {"item_id": it.id})


@router.post("/api/studio/items/{iid}/unsummary")
def api_unsummary(iid: int, s: Session = Depends(get_session)):
    it = _item(s, iid)
    mt = s.get(m.Meeting, it.meeting_id)
    return _run(s, mt, lambda: st.unsummarize(s, it))


@router.post("/api/studio/{mid}/submit")
def api_submit(mid: int, s: Session = Depends(get_session)):
    mt = _meeting(s, mid)
    return _run(s, mt, lambda: st.submit(s, mt), lambda v: {"version": v.version})


@router.post("/api/studio/{mid}/publish")
def api_publish(mid: int, s: Session = Depends(get_session)):
    mt = _meeting(s, mid)
    return _run(s, mt, lambda: st.publish(s, mt), lambda v: {"version": v.version})


@router.post("/api/studio/{mid}/fill")
async def api_fill(mid: int, request: Request, s: Session = Depends(get_session)):
    """공유회 — 미제출 부서를 원장으로 채우기."""
    mt, data = _meeting(s, mid), await request.json()
    return _run(s, mt, lambda: st.fill_from_ledger(s, mt, str(data.get("dept_id", ""))), lambda n: {"added": n})


@router.post("/api/studio/{mid}/dept-move")
async def api_dept_move(mid: int, request: Request, s: Session = Depends(get_session)):
    """공유회 — 부서 순서 위(-1)·아래(+1)."""
    mt, data = _meeting(s, mid), await request.json()
    return _run(s, mt, lambda: st.move_dept(s, mt, str(data.get("dept_id", "")), int(data.get("step", 1))))


@router.post("/api/studio/{mid}/table-item")
async def api_table_item(mid: int, request: Request, s: Session = Depends(get_session)):
    """부서 회의자료에 「기간 표」 장 넣기(F16) — 표마다 한 장."""
    mt, data = _meeting(s, mid), await request.json()
    try:
        tid = int(data.get("table_id"))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "err": "넣을 기간 표를 골라주세요."}, status_code=400)
    return _run(s, mt, lambda: st.add_table_item(s, mt, tid), lambda it: {"item_id": it.id})


@router.post("/api/studio/{mid}/metric-item")
def api_metric_item(mid: int, s: Session = Depends(get_session)):
    """부서 회의자료에 「지표 요약」 장 넣기(F16)."""
    mt = _meeting(s, mid)
    return _run(s, mt, lambda: st.add_metric_item(s, mt), lambda it: {"item_id": it.id})
