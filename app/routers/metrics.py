"""지표 화면(F16) — 주간 지표(값·코멘트·숨기기·순서·평소 범위) · 기간 표(행 × 날짜 × 계획/실적). 폼 POST → 303(지표 화면으로).

화면(GET /metrics/{부서})은 main.py 가 `render_metrics` 로 그린다. 값은 블록 없이 (지표, 주차) 에 쌓는다(M13 까지는 대시보드 블록에 붙어 있었다).
"""
from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.db import get_session
from app.services import metrics as mt
from app.services import weeks
from app.services import writing as w

router = APIRouter()


def _back(dept_id: str, week_id: str, anchor: str = "", **q: str) -> RedirectResponse:
    qs = urlencode({k: v for k, v in {"week": week_id, **q}.items() if v})
    return RedirectResponse(f"/metrics/{dept_id}?{qs}" + (f"#{anchor}" if anchor else ""), status_code=303)


def _week(week_id: str) -> str:
    return week_id if weeks.parse(week_id or "") else weeks.current().id


def _dept(s: Session, dept_id: str) -> m.Department:
    d = s.get(m.Department, dept_id)
    if d is None:
        raise HTTPException(404, f"부서 {dept_id} 가 기준정보에 없습니다.")
    return d


def render_metrics(request: Request, s: Session, dept_id: str, page):
    dept = _dept(s, dept_id)
    wk = weeks.parse(request.query_params.get("week", "")) or weeks.current()
    return page(request, "metrics.html", "metrics", wk, dept_id=dept_id, dept_name=dept.name,
                metrics=mt.views(s, dept_id, wk.id), hidden=[d for d in mt.defs(s, dept_id) if d.hidden],
                tables=[mt.table_view(s, t) for t in mt.tables(s, dept_id)], hidden_tables=[t for t in mt.tables(s, dept_id, True) if t.hidden],
                depts=list(s.scalars(select(m.Department).order_by(m.Department.order_no))),
                prev_week=weeks.shift(wk.id, -1).id, next_week=weeks.shift(wk.id, 1).id, range_weeks=mt.range_weeks(s),
                msg=request.query_params.get("msg", ""), err=request.query_params.get("err", ""))


# ── 주간 지표 ───────────────────────────────────────────
@router.post("/metrics/{dept_id}/values")
async def post_values(dept_id: str, request: Request, s: Session = Depends(get_session)):
    _dept(s, dept_id)
    form = await request.form()
    wk = _week(str(form.get("week", "")))
    try:
        n = mt.save_values(s, dept_id, wk, form)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _back(dept_id, wk, "weekly", err=f"지표: {e}")
    return _back(dept_id, wk, "weekly", msg=f"지표 저장 — 바뀐 값 {n}개" if n else "지표 — 바뀐 값이 없습니다")


@router.post("/metrics/{dept_id}/defs")
def post_def(dept_id: str, name: str = Form(""), unit: str = Form(""), low: str = Form(""), high: str = Form(""),
             week: str = Form(""), s: Session = Depends(get_session)):
    _dept(s, dept_id)
    try:
        d = mt.add_def(s, dept_id, name, unit, low, high)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _back(dept_id, _week(week), "weekly", err=f"지표 추가: {e}")
    return _back(dept_id, _week(week), "weekly", msg=f"지표 '{d.name}' 추가")


def _def(s: Session, def_id: int) -> m.MetricDef:
    d = s.get(m.MetricDef, def_id)
    if d is None:
        raise HTTPException(404, "지표를 찾을 수 없습니다.")
    return d


@router.post("/metric-defs/{def_id}/update")
def post_def_update(def_id: int, week_id: str = Form(""), unit: str = Form(""), low: str = Form(""), high: str = Form(""),
                    s: Session = Depends(get_session)):
    d = _def(s, def_id)
    try:
        mt.update_def(s, d, unit, low, high)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _back(d.department_id, _week(week_id), "manage", err=str(e))
    return _back(d.department_id, _week(week_id), "manage", msg=f"지표 '{d.name}' 저장")


@router.post("/metric-defs/{def_id}/delete")
def post_def_delete(def_id: int, week_id: str = Form(""), s: Session = Depends(get_session)):
    d = _def(s, def_id)
    dept_id, name = d.department_id, d.name
    try:
        mt.delete_def(s, d)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _back(dept_id, _week(week_id), "manage", err=str(e))
    return _back(dept_id, _week(week_id), "manage", msg=f"지표 '{name}' 지움")


@router.post("/metric-defs/{def_id}/hide")
def post_def_hide(def_id: int, hidden: str = Form("1"), week_id: str = Form(""), s: Session = Depends(get_session)):
    d = _def(s, def_id)
    mt.set_hidden(s, d, hidden == "1")
    s.commit()
    return _back(d.department_id, _week(week_id), "manage", msg=f"지표 '{d.name}' {'숨김 — 값은 남습니다' if d.hidden else '다시 보임'}")


@router.post("/metric-defs/{def_id}/move")
def post_def_move(def_id: int, step: int = Form(1), week_id: str = Form(""), s: Session = Depends(get_session)):
    d = _def(s, def_id)
    mt.move_def(s, d, step)
    s.commit()
    return _back(d.department_id, _week(week_id), "weekly")


# ── 기간 표 ─────────────────────────────────────────────
@router.post("/metrics/{dept_id}/tables")
def post_table(dept_id: str, name: str = Form(""), unit: str = Form(""), start: str = Form(""), end: str = Form(""),
               rows: str = Form(""), week: str = Form(""), s: Session = Depends(get_session)):
    _dept(s, dept_id)
    try:
        t = mt.save_table(s, dept_id, name, unit, start, end, rows)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _back(dept_id, _week(week), "tables", err=f"기간 표: {e}")
    return _back(dept_id, _week(week), f"t{t.id}", msg=f"기간 표 '{t.name}' 만들었습니다 — 칸에 계획·실적을 넣어주세요")


def _table(s: Session, tid: int) -> m.MetricTable:
    t = s.get(m.MetricTable, tid)
    if t is None:
        raise HTTPException(404, "기간 표를 찾을 수 없습니다.")
    return t


@router.post("/metric-tables/{tid}/update")
def post_table_update(tid: int, name: str = Form(""), unit: str = Form(""), start: str = Form(""), end: str = Form(""),
                      rows: str = Form(""), week: str = Form(""), s: Session = Depends(get_session)):
    t = _table(s, tid)
    try:
        mt.save_table(s, t.department_id, name, unit, start, end, rows, t)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _back(t.department_id, _week(week), f"t{tid}", err=f"기간 표: {e}")
    return _back(t.department_id, _week(week), f"t{tid}", msg=f"기간 표 '{t.name}' 고쳤습니다(바뀐 행·날짜 밖의 값은 남아 있습니다)")


@router.post("/metric-tables/{tid}/cells")
async def post_cells(tid: int, request: Request, s: Session = Depends(get_session)):
    t = _table(s, tid)
    form = await request.form()
    wk = _week(str(form.get("week", "")))
    try:
        n = mt.save_cells(s, t, form)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _back(t.department_id, wk, f"t{tid}", err=f"{t.name}: {e}")
    return _back(t.department_id, wk, f"t{tid}", msg=f"{t.name} 저장 — 바뀐 칸 {n}개" if n else f"{t.name} — 바뀐 칸이 없습니다")


@router.post("/metric-tables/{tid}/hide")
def post_table_hide(tid: int, hidden: str = Form("1"), week: str = Form(""), s: Session = Depends(get_session)):
    t = _table(s, tid)
    t.hidden = hidden == "1"
    s.commit()
    return _back(t.department_id, _week(week), "tables", msg=f"기간 표 '{t.name}' {'숨김' if t.hidden else '다시 보임'}")


@router.post("/metric-tables/{tid}/delete")
def post_table_delete(tid: int, week: str = Form(""), s: Session = Depends(get_session)):
    t = _table(s, tid)
    dept_id, name = t.department_id, t.name
    try:
        mt.delete_table(s, t)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _back(dept_id, _week(week), f"t{tid}", err=str(e))
    return _back(dept_id, _week(week), "tables", msg=f"기간 표 '{name}' 지움")
