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
from app.services import locks as lk
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


def _editor(request: Request | None) -> str:
    """편집 중인 브라우저 표(`X-Editor`). 누구인지·어디인지는 받지 않는다(최소수집)."""
    return request.headers.get("x-editor", "")[:40] if request is not None else ""


def _run(request: Request | None, s: Session, mt: m.Meeting, fn, extra: dict | None = None):
    tok = _editor(request)
    try:
        lk.require(s, mt.id, tok)          # 15-7 — 자료 하나는 한 명씩. 내 것이면 시각을 새로 찍는다
        out = fn()
        s.commit()
    except lk.Locked as e:
        s.rollback()
        return JSONResponse({"ok": False, "err": str(e), "lock": lk.state(s, mt.id, tok)}, status_code=409)
    except w.WriteError as e:
        s.rollback()
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    s.refresh(mt)
    body = {"ok": True, "state": st.state(s, mt), "lock": lk.state(s, mt.id, tok)}
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
def api_state(mid: int, request: Request, s: Session = Depends(get_session)):
    mt = _meeting(s, mid)
    if st.sync_share(s, mt):          # 종결 요청 자동 채택(공유회, 발행 전)
        s.commit()
    return {"ok": True, "state": st.state(s, mt), "lock": lk.state(s, mid, _editor(request))}


@router.post("/api/studio/{mid}/claim")
def api_claim(mid: int, request: Request, s: Session = Depends(get_session)):
    """편집 잡기 (결정 ⑦ 15-7) — 편집 화면을 열 때와 「내가 편집」을 누를 때.

    남이 쥐고 있으면 **빼앗지 않고** 상태만 돌려준다(읽기 전용으로 보여 준다).
    """
    mt = _meeting(s, mid)
    out = lk.claim(s, mt.id, _editor(request))
    s.commit()
    return {"ok": True, "lock": out}


@router.post("/api/studio/{mid}/release")
async def api_release(mid: int, request: Request, s: Session = Depends(get_session)):
    """편집 놓기 — 창을 닫을 때. 못 받아도 10분 뒤 저절로 풀린다."""
    _meeting(s, mid)
    tok = _editor(request)
    if not tok:                                   # 창을 닫을 때는 헤더를 못 붙이기도 한다 — 본문으로도 받는다
        try:
            tok = str((await request.json()).get("token", ""))[:40]
        except Exception:  # noqa: BLE001 — 본문이 없거나 JSON 이 아니면 놓을 표가 없다
            tok = ""
    lk.release(s, mid, tok)
    s.commit()
    return {"ok": True}


@router.post("/api/studio/{mid}/start")
async def api_start(mid: int, request: Request, s: Session = Depends(get_session)):
    mt, data = _meeting(s, mid), await request.json()
    return _run(request, s, mt, lambda: st.start(s, mt, str(data.get("mode", ""))), lambda out: {"added": len(out)})


@router.post("/api/studio/{mid}/items")
async def api_add(mid: int, request: Request, s: Session = Depends(get_session)):
    mt, data = _meeting(s, mid), await request.json()
    return _run(request, s, mt, lambda: st.add_item(s, mt, str(data.get("block_id", "")), str(data.get("src", "원장"))), lambda it: {"item_id": it.id})


@router.post("/api/studio/items/{iid}")
async def api_update(iid: int, request: Request, s: Session = Depends(get_session)):
    it, data = _item(s, iid), await request.json()
    mt = s.get(m.Meeting, it.meeting_id)
    return _run(request, s, mt, lambda: st.update_item(s, it, str(data.get("field", "")), data.get("value")))


@router.post("/api/studio/items/{iid}/free")
async def api_free(iid: int, request: Request, s: Session = Depends(get_session)):
    """자유 편집 켜기/끄기 (결정 ⑦ 15-2). 처음 켤 때만 지금 형태대로 개체 초안을 만든다."""
    it, data = _item(s, iid), await request.json()
    mt = _meeting(s, it.meeting_id)
    from app.services import freeform as ff
    return _run(request, s, mt, lambda: ff.set_on(it, st.item_json(s, it, mt), bool(data.get("on"))),
                lambda _objs: {"free": ff.json_with(s, it, st.item_json(s, it, mt))})


@router.post("/api/studio/items/{iid}/objects")
async def api_objects(iid: int, request: Request, s: Session = Depends(get_session)):
    """개체 자동 저장. 판 번호(rev)가 다르면 거절한다 — 다른 창의 작업을 덮지 않는다.

    화면은 응답의 rev 를 받은 뒤에만 「저장됨」을 띄운다(시안 버그 #4: 가짜 「저장됨」 금지).
    """
    it, data = _item(s, iid), await request.json()
    mt = _meeting(s, it.meeting_id)
    from app.services import freeform as ff
    base = data.get("rev")
    before = ff.load(it)

    def go():
        rev = ff.save(it, data.get("objects"), None if base is None else int(base))
        from app.services import events
        for ch in ff.changed_links(before, ff.load(it)):          # 연결 개체의 **글**이 바뀌면 자료수정으로 남긴다
            if s.get(m.Block, ch["block"]) is not None:
                # 칸 이름은 **이슈 사실 칸 이름**으로 적는다(cause → cause_text) —
                # 기록 라벨과 「사실로 채택」(15-6)이 같은 이름을 쓴다.
                events.record(s, ch["block"], "자료수정", field=ff.FACT_BY_FIELD.get(ch["field"], ch["field"]),
                              before=ch["before"], after=ch["after"], meeting_id=mt.id)
        return rev

    return _run(request, s, mt, go, lambda _rev: {"free": ff.json_with(s, it, st.item_json(s, it, mt))})


@router.post("/api/studio/items/{iid}/link")
async def api_link(iid: int, request: Request, s: Session = Depends(get_session)):
    """연결·갈래 다루기 (결정 ⑦ 15-3·15-4) — op: apply(이슈에도 반영) · pull(다시 가져오기) ·
    unlink · relink · add(장에 없는 칸) · pick(더한 개체의 갈래 칩).

    **기본은 이 자료만 바뀐다.** 이슈의 사실을 바꾸는 것은 `apply` 와 `pick`(scope=사실) 뿐이고,
    그때만 이슈 변경 기록에 「사실변경」이 남는다(케이스 A3 — 줄여 쓰기와 오타 고치기는 손동작이 같아서
    한 번 더 누르게 한다). `pick`(scope=새이슈)은 이슈를 새로 떼어낸다.
    """
    it, data = _item(s, iid), await request.json()
    mt = _meeting(s, it.meeting_id)
    from app.services import freeform as ff
    op, oid, field = str(data.get("op", "")), str(data.get("oid", "")), str(data.get("field", ""))
    scope = str(data.get("scope", ""))

    def go():
        item = st.item_json(s, it, mt)
        if op == "pull":
            return ff.pull(s, it, item, oid)
        if op == "unlink":
            return ff.unlink(it, oid)
        if op == "relink":
            return ff.relink(s, it, item, oid, field, str(data.get("block", "")))
        if op == "add":
            return ff.add_field(it, item, field)
        if op == "apply":
            return ff.apply_to_issue(s, it, item, oid, mt)
        if op == "pick":
            return ff.pick(s, it, item, oid, scope, field, mt)
        raise ff.FreeError("모르는 동작입니다. 화면을 새로 고쳐주세요.")

    return _run(request, s, mt, go, lambda out: {"free": ff.json_with(s, it, st.item_json(s, it, mt)),
                                        "new_block": out if isinstance(out, str) else ""})


@router.post("/api/studio/items/{iid}/undo-form")
def api_undo_form(iid: int, request: Request, s: Session = Depends(get_session)):
    """형태 바꾸기 되돌리기 (케이스 B1) — 한 단계."""
    it = _item(s, iid)
    mt = _meeting(s, it.meeting_id)
    from app.services import freeform as ff
    return _run(request, s, mt, lambda: ff.undo_form(it), lambda _objs: {"free": ff.json_with(s, it, st.item_json(s, it, mt))})


@router.post("/api/studio/{mid}/reorder")
async def api_reorder(mid: int, request: Request, s: Session = Depends(get_session)):
    mt, data = _meeting(s, mid), await request.json()
    return _run(request, s, mt, lambda: st.reorder(s, mt, [int(x) for x in data.get("ids", [])]))


@router.post("/api/studio/items/{iid}/remove")
def api_remove(iid: int, request: Request, s: Session = Depends(get_session)):
    it = _item(s, iid)
    mt = s.get(m.Meeting, it.meeting_id)
    return _run(request, s, mt, lambda: st.remove_item(s, it), lambda snap: {"snapshot": snap})


@router.post("/api/studio/{mid}/restore")
async def api_restore(mid: int, request: Request, s: Session = Depends(get_session)):
    mt, data = _meeting(s, mid), await request.json()
    return _run(request, s, mt, lambda: st.restore(s, mt, data.get("snapshot") or {}), lambda it: {"item_id": it.id})


@router.post("/api/studio/{mid}/summary")
async def api_summary(mid: int, request: Request, s: Session = Depends(get_session)):
    mt, data = _meeting(s, mid), await request.json()
    return _run(request, s, mt, lambda: st.summarize(s, mt, [int(x) for x in data.get("ids", [])]), lambda it: {"item_id": it.id})


@router.post("/api/studio/items/{iid}/unsummary")
def api_unsummary(iid: int, request: Request, s: Session = Depends(get_session)):
    it = _item(s, iid)
    mt = s.get(m.Meeting, it.meeting_id)
    return _run(request, s, mt, lambda: st.unsummarize(s, it))


@router.post("/api/studio/{mid}/submit")
def api_submit(mid: int, request: Request, s: Session = Depends(get_session)):
    mt = _meeting(s, mid)
    return _run(request, s, mt, lambda: st.submit(s, mt), lambda v: {"version": v.version})


@router.post("/api/studio/{mid}/publish")
def api_publish(mid: int, request: Request, s: Session = Depends(get_session)):
    mt = _meeting(s, mid)
    return _run(request, s, mt, lambda: st.publish(s, mt), lambda v: {"version": v.version})


@router.post("/api/studio/{mid}/fill")
async def api_fill(mid: int, request: Request, s: Session = Depends(get_session)):
    """공유회 — 미제출 부서를 원장으로 채우기."""
    mt, data = _meeting(s, mid), await request.json()
    return _run(request, s, mt, lambda: st.fill_from_ledger(s, mt, str(data.get("dept_id", ""))), lambda n: {"added": n})


@router.post("/api/studio/{mid}/dept-move")
async def api_dept_move(mid: int, request: Request, s: Session = Depends(get_session)):
    """공유회 — 부서 순서 위(-1)·아래(+1)."""
    mt, data = _meeting(s, mid), await request.json()
    return _run(request, s, mt, lambda: st.move_dept(s, mt, str(data.get("dept_id", "")), int(data.get("step", 1))))


@router.post("/api/studio/{mid}/table-item")
async def api_table_item(mid: int, request: Request, s: Session = Depends(get_session)):
    """부서 회의자료에 「기간 표」 장 넣기(F16) — 표마다 한 장."""
    mt, data = _meeting(s, mid), await request.json()
    try:
        tid = int(data.get("table_id"))
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "err": "넣을 기간 표를 골라주세요."}, status_code=400)
    return _run(request, s, mt, lambda: st.add_table_item(s, mt, tid), lambda it: {"item_id": it.id})


@router.post("/api/studio/{mid}/metric-item")
def api_metric_item(mid: int, request: Request, s: Session = Depends(get_session)):
    """부서 회의자료에 「지표 요약」 장 넣기(F16)."""
    mt = _meeting(s, mid)
    return _run(request, s, mt, lambda: st.add_metric_item(s, mt), lambda it: {"item_id": it.id})
