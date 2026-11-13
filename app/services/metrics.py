"""지표 — 부서별 지표 정의(metric_def), 주차 값(metric_value), 추이·평소 범위, SVG 차트 (기능 9 → F16, 2026-10-23).

F16: 값은 블록 없이 (지표, 주차) 에 바로 쌓인다(대시보드 블록은 옛 기록·AI 출처로만). 숨기기·순서, 이탈인데 사유가 비면
「사유를 적어주세요」, **기간 표**(행 × 날짜 × 계획/실적 — 행 이름은 표마다 자유, 2026-10-23 사용자 결정), 회의자료 「지표 요약」 장.

- 값은 (지표, 주차) 한 칸. 주차가 쌓이면 6주 추이·막대 차트가 그대로 나온다.
- 「평소 범위」: 정의에 하한·상한을 적었으면 그것, 없으면 **이전 주 값(3개 이상)의 평균 ± 2σ**.
  벗어나면 표시만 한다(값을 막지 않는다).
- AI 가 메모에서 읽은 지표는 같은 이름의 정의에 넣고, 없으면 정의를 만든다. 사람이 고친 값은 덮지 않는다.
- 차트는 서버에서 SVG 문자열로 그린다. 화면의 즉시 갱신(`static/js/metrics.js`)도 같은 좌표 규칙을 쓴다 —
  한쪽을 바꾸면 다른 쪽도 함께 고친다.
"""
from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app import models as m
from app.services import weeks
from app.services import writing as w

TREND_WEEKS = 6
RANGE_WEEKS = 8            # 평소 범위(정의가 없을 때) = 최근 n주 값의 평균 ± 2σ. 설정 화면에서 바꾼다(app_setting metric_range_weeks)
RANGE_WEEKS_MIN, RANGE_WEEKS_MAX = 3, 52
SPARK_W, SPARK_H, SPARK_PAD = 90, 24, 3
BAR_W, BAR_H = 220, 120


def _norm(name: str) -> str:
    return re.sub(r"\s+", "", (name or "")).lower()


# ── 정의 ────────────────────────────────────────────────
def defs(s: Session, dept_id: str, include_hidden: bool = True) -> list[m.MetricDef]:
    q = select(m.MetricDef).where(m.MetricDef.department_id == dept_id)
    if not include_hidden:
        q = q.where(m.MetricDef.hidden.is_(False))
    return list(s.scalars(q.order_by(m.MetricDef.order_no, m.MetricDef.id)))


def set_hidden(s: Session, d: m.MetricDef, hidden: bool) -> None:
    d.hidden = bool(hidden)
    s.flush()


def move_def(s: Session, d: m.MetricDef, step: int) -> None:
    """순서 위(-1)·아래(+1) — 보이는 지표끼리."""
    xs = defs(s, d.department_id)
    i = xs.index(d)
    j = max(0, min(len(xs) - 1, i + (1 if step > 0 else -1)))
    xs[i], xs[j] = xs[j], xs[i]
    for n, x in enumerate(xs, 1):
        x.order_no = n
    s.flush()


def _float_or_none(v) -> float | None:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise w.WriteError(f"숫자가 아닙니다: {v}") from None


def add_def(s: Session, dept_id: str, name: str, unit: str = "", low=None, high=None) -> m.MetricDef:
    name = (name or "").strip()
    if not name:
        raise w.WriteError("지표 이름을 적어주세요.")
    if any(_norm(d.name) == _norm(name) for d in defs(s, dept_id)):
        raise w.WriteError(f"'{name}' 지표가 이미 있습니다.")
    lo, hi = _float_or_none(low), _float_or_none(high)
    if lo is not None and hi is not None and lo > hi:
        raise w.WriteError("평소 범위의 하한이 상한보다 큽니다.")
    order = (s.scalar(select(func.max(m.MetricDef.order_no)).where(m.MetricDef.department_id == dept_id)) or 0) + 1
    d = m.MetricDef(department_id=dept_id, name=name[:128], unit=(unit or "").strip()[:16], order_no=order,
                    normal_low=lo, normal_high=hi)
    s.add(d)
    s.flush()
    return d


def update_def(s: Session, d: m.MetricDef, unit: str, low, high) -> None:
    lo, hi = _float_or_none(low), _float_or_none(high)
    if lo is not None and hi is not None and lo > hi:
        raise w.WriteError(f"{d.name}: 평소 범위의 하한이 상한보다 큽니다.")
    d.unit, d.normal_low, d.normal_high = (unit or "").strip()[:16], lo, hi
    s.flush()


def delete_def(s: Session, d: m.MetricDef) -> None:
    n = s.scalar(select(func.count()).select_from(m.MetricValue).where(m.MetricValue.metric_def_id == d.id,
                                                                       m.MetricValue.value.is_not(None)))
    if n:
        raise w.WriteError(f"'{d.name}' 은 쌓인 값이 {n}주 있어 지울 수 없습니다(추이가 끊깁니다).")
    s.execute(delete(m.MetricValue).where(m.MetricValue.metric_def_id == d.id))
    s.delete(d)
    s.flush()


# ── 값 ──────────────────────────────────────────────────
def value_row(s: Session, def_id: int, week_id: str) -> m.MetricValue | None:
    return s.scalar(select(m.MetricValue).where(m.MetricValue.metric_def_id == def_id, m.MetricValue.week_id == week_id))


def _human_set(s: Session, block_id: str | None, def_id: int) -> bool:
    if not block_id:
        return False
    return s.scalar(select(m.AiFieldLog.id).where(m.AiFieldLog.block_id == block_id,
                                                  m.AiFieldLog.field == f"metric:{def_id}",
                                                  m.AiFieldLog.human_value.is_not(None)).limit(1)) is not None


def set_value(s: Session, d: m.MetricDef, week_id: str, value, comment: str = "", block_id: str | None = None,
              human: bool = True, model: str | None = None) -> bool:
    """값 1칸. 바뀌면 True. 사람 입력은 ai_field_log(사람 값)로 남겨 AI 가 다시 덮지 못하게 한다."""
    v = _float_or_none(value)
    w.ensure_week(s, weeks.from_id(week_id))               # 지난 주차 값을 넣어도 주차 행이 있게 (FK)
    row = value_row(s, d.id, week_id)
    if not human and ((row is not None and row.human) or _human_set(s, block_id, d.id)):
        return False                                       # 사람이 넣은 값은 AI 가 건드리지 않는다
    if row is None:
        if v is None and not (comment or "").strip():
            return False
        row = m.MetricValue(metric_def_id=d.id, week_id=week_id, value=None, comment="", block_id=block_id)
        s.add(row)
    before = (row.value, row.comment or "")
    row.value, row.comment = v, (comment or "").strip()[:500]
    row.block_id = block_id or row.block_id
    changed = before != (row.value, row.comment)
    if changed and human:
        row.human = True
    if changed and block_id:
        s.add(m.AiFieldLog(block_id=block_id, field=f"metric:{d.id}",
                           ai_value=None if human else _fmt(v), human_value=_fmt(v) if human else None, model=model))
    s.flush()
    return changed


def apply_ai_metrics(s: Session, dept_id: str, week_id: str, block_id: str, items: list[dict], model: str | None) -> int:
    """AI 가 읽은 지표 → 같은 이름 정의(없으면 만든다)의 이번 주 값. 넣은 개수."""
    n = 0
    have = {_norm(d.name): d for d in defs(s, dept_id)}
    for it in items:
        d = have.get(_norm(it["name"]))
        if d is None:
            d = add_def(s, dept_id, it["name"], it.get("unit", ""))
            have[_norm(d.name)] = d
        if set_value(s, d, week_id, it["value"], block_id=block_id, human=False, model=model):
            n += 1
    return n


def _fmt(v: float | None) -> str | None:
    return None if v is None else (f"{v:g}")


# ── 추이 · 평소 범위 ────────────────────────────────────
@dataclass
class MetricView:
    d: m.MetricDef
    value: float | None
    comment: str
    weeks: list[str]                       # 오래된 → 이번 주
    series: list[float | None]
    low: float | None = None
    high: float | None = None
    range_src: str = ""                    # 정의 / 지난 값
    flag: str = ""                         # 높음 / 낮음 / ""
    spark: str = ""
    needs_note: bool = False               # 평소 범위를 벗어났는데 코멘트(차이 사유)가 비었다
    bar: str = ""
    extra: dict = field(default_factory=dict)


def range_weeks(s: Session) -> int:
    v = s.get(m.AppSetting, "metric_range_weeks")
    try:
        n = int(v.value) if v and v.value.strip() else RANGE_WEEKS
    except ValueError:
        return RANGE_WEEKS
    return min(max(n, RANGE_WEEKS_MIN), RANGE_WEEKS_MAX)


def set_range_weeks(s: Session, raw) -> bool:
    """설정 화면 — 평소 범위를 잡는 최근 주 수. 바뀌었으면 True."""
    try:
        n = int(str(raw or "").strip())
    except ValueError:
        raise w.WriteError("평소 범위 기간은 숫자(주)로 적어주세요.") from None
    if not RANGE_WEEKS_MIN <= n <= RANGE_WEEKS_MAX:
        raise w.WriteError(f"평소 범위 기간은 {RANGE_WEEKS_MIN}~{RANGE_WEEKS_MAX}주로 적어주세요.")
    row = s.get(m.AppSetting, "metric_range_weeks")
    if row is None:
        s.add(m.AppSetting(key="metric_range_weeks", value=str(n)))
    elif row.value == str(n):
        return False
    else:
        row.value = str(n)
    s.flush()
    return True


def normal_range(d: m.MetricDef, past: list[float]) -> tuple[float | None, float | None, str]:
    if d.normal_low is not None or d.normal_high is not None:
        return d.normal_low, d.normal_high, "정의"
    if len(past) >= 3:
        mu, sd = statistics.fmean(past), statistics.pstdev(past)
        return mu - 2 * sd, mu + 2 * sd, f"최근 {len(past)}주 값"
    return None, None, ""


def view(s: Session, d: m.MetricDef, week_id: str) -> MetricView:
    wks = [weeks.shift(week_id, -i).id for i in range(TREND_WEEKS - 1, -1, -1)]
    vals = {r.week_id: r for r in s.scalars(select(m.MetricValue).where(m.MetricValue.metric_def_id == d.id,
                                                                        m.MetricValue.week_id.in_(wks)))}
    series = [vals[x].value if x in vals else None for x in wks]
    past = [r.value for r in s.scalars(select(m.MetricValue).where(
        m.MetricValue.metric_def_id == d.id, m.MetricValue.week_id < week_id, m.MetricValue.value.is_not(None))
        .order_by(m.MetricValue.week_id.desc()).limit(range_weeks(s)))]
    lo, hi, src = normal_range(d, past)
    cur = vals.get(week_id)
    v = cur.value if cur else None
    flag = ""
    if v is not None and hi is not None and v > hi:
        flag = "높음"
    elif v is not None and lo is not None and v < lo:
        flag = "낮음"
    mv = MetricView(d=d, value=v, comment=(cur.comment if cur else "") or "", weeks=wks, series=series,
                    low=lo, high=hi, range_src=src, flag=flag)
    mv.needs_note = bool(flag) and not mv.comment.strip()
    mv.extra["labels"] = [x[-3:] for x in wks]           # 막대 아래 표기 (W42)
    mv.spark = spark_svg(series, flag)
    mv.bar = bar_svg(mv.extra["labels"], series, lo, hi)
    return mv


def views(s: Session, dept_id: str, week_id: str, include_hidden: bool = False) -> list[MetricView]:
    return [view(s, d, week_id) for d in defs(s, dept_id, include_hidden)]


def save_values(s: Session, dept_id: str, week_id: str, form) -> int:
    """지표 화면의 한 번 저장 — v_<id>·c_<id>. 블록 없이 (지표, 주차) 에 쌓는다. 바뀐 칸 수."""
    n = 0
    for d in defs(s, dept_id):
        if f"v_{d.id}" in form or f"c_{d.id}" in form:
            n += set_value(s, d, week_id, form.get(f"v_{d.id}"), form.get(f"c_{d.id}", ""))
    return n


def missing(s: Session, dept_id: str, week_id: str) -> list[str]:
    """이번 주 값이 빈 (보이는) 지표 이름 — 홈 할 일."""
    out = []
    for d in defs(s, dept_id, include_hidden=False):
        r = value_row(s, d.id, week_id)
        if r is None or r.value is None:
            out.append(d.name)
    return out


def summary(s: Session, dept_id: str, week_id: str) -> list[dict]:
    """회의자료 「지표 요약」 장 — 이탈·코멘트가 있는 지표 먼저. 발행본에 그대로 고정된다."""
    out = []
    for mv in views(s, dept_id, week_id):
        out.append({"name": mv.d.name, "unit": mv.d.unit, "value": mv.value, "labels": mv.extra["labels"], "series": mv.series,
                    "low": mv.low, "high": mv.high, "flag": mv.flag, "comment": mv.comment})
    return sorted(out, key=lambda x: (not x["flag"], not x["comment"]))


# ── 기간 표 ─────────────────────────────────────────────
TABLE_MAX_DAYS, TABLE_MAX_ROWS = 62, 20


def _rows_of(text: str) -> list[str]:
    rows, seen = [], set()
    for r in re.split(r"[\n,]", text or ""):
        r = r.strip()[:64]
        if r and r not in seen:
            seen.add(r)
            rows.append(r)
    return rows


def _date(v: str, label: str) -> date:
    try:
        return date.fromisoformat((v or "").strip())
    except ValueError:
        raise w.WriteError(f"{label}을 2026-10-23 처럼 적어주세요.") from None


def tables(s: Session, dept_id: str, include_hidden: bool = False) -> list[m.MetricTable]:
    q = select(m.MetricTable).where(m.MetricTable.department_id == dept_id)
    if not include_hidden:
        q = q.where(m.MetricTable.hidden.is_(False))
    return list(s.scalars(q.order_by(m.MetricTable.start_date.desc(), m.MetricTable.id.desc())))


def save_table(s: Session, dept_id: str, name: str, unit: str, start: str, end: str, rows_text: str,
               t: m.MetricTable | None = None) -> m.MetricTable:
    """기간 표 만들기·고치기 — 행 이름은 줄 또는 쉼표로(1과·2과, 호선, 작업조…). 기간은 62일까지."""
    name = (name or "").strip()
    if not name:
        raise w.WriteError("기간 표 이름을 적어주세요(예: 특근 인원).")
    a, b = _date(start, "시작일"), _date(end, "끝날")
    if b < a:
        raise w.WriteError("끝날이 시작일보다 앞입니다.")
    if (b - a).days + 1 > TABLE_MAX_DAYS:
        raise w.WriteError(f"기간은 {TABLE_MAX_DAYS}일까지입니다. 표를 나눠주세요.")
    rows = _rows_of(rows_text)
    if not rows:
        raise w.WriteError("행 이름을 한 줄에 하나씩 적어주세요(예: 1과, 2과).")
    if len(rows) > TABLE_MAX_ROWS:
        raise w.WriteError(f"행은 {TABLE_MAX_ROWS}개까지입니다.")
    if t is None:
        t = m.MetricTable(department_id=dept_id, name=name[:128])
        s.add(t)
    t.name, t.unit, t.start_date, t.end_date = name[:128], (unit or "").strip()[:16], a, b
    t.rows_json = json.dumps(rows, ensure_ascii=False)
    s.flush()
    return t


def delete_table(s: Session, t: m.MetricTable) -> None:
    n = s.scalar(select(func.count()).select_from(m.MetricCell).where(m.MetricCell.table_id == t.id,
                                                                      (m.MetricCell.plan.is_not(None)) | (m.MetricCell.actual.is_not(None))))
    if n:
        raise w.WriteError(f"'{t.name}' 에 값이 {n}칸 있어 지울 수 없습니다 — 숨기기를 쓰세요.")
    s.execute(delete(m.MetricCell).where(m.MetricCell.table_id == t.id))
    s.execute(update(m.ReportItem).where(m.ReportItem.table_id == t.id).values(table_id=None))   # 그 표를 그리던 장은 「지워짐」으로
    s.delete(t)
    s.flush()


def days_of(t: m.MetricTable) -> list[date]:
    return [t.start_date + timedelta(days=i) for i in range((t.end_date - t.start_date).days + 1)]


def save_cells(s: Session, t: m.MetricTable, form) -> int:
    """p_<행번호>_<yyyymmdd>·a_…·n_<행번호>(차이 사유). 바뀐 칸 수."""
    rows = json.loads(t.rows_json or "[]")
    have = {(c.row, c.day): c for c in s.scalars(select(m.MetricCell).where(m.MetricCell.table_id == t.id))}
    n = 0
    for ri, row in enumerate(rows):
        for d in days_of(t):
            key = d.strftime("%Y%m%d")
            if f"p_{ri}_{key}" not in form and f"a_{ri}_{key}" not in form:
                continue
            p, a = _float_or_none(form.get(f"p_{ri}_{key}")), _float_or_none(form.get(f"a_{ri}_{key}"))
            c = have.get((row, d))
            if c is None:
                if p is None and a is None:
                    continue
                c = m.MetricCell(table_id=t.id, row=row, day=d)
                s.add(c)
            if (c.plan, c.actual) != (p, a):
                c.plan, c.actual = p, a
                n += 1
    notes = json.loads(t.notes_json or "{}")
    for ri, row in enumerate(rows):
        if f"n_{ri}" in form:
            v = (form.get(f"n_{ri}") or "").strip()[:300]
            if notes.get(row, "") != v:
                notes[row] = v
                n += 1
    t.notes_json = json.dumps(notes, ensure_ascii=False)
    s.flush()
    return n


def table_view(s: Session, t: m.MetricTable) -> dict:
    """화면·회의자료용 — 행마다 날짜별 계획/실적·합계·차이, 차이가 있는데 사유가 비면 needs_note."""
    rows = json.loads(t.rows_json or "[]")
    notes = json.loads(t.notes_json or "{}")
    cells = {(c.row, c.day): c for c in s.scalars(select(m.MetricCell).where(m.MetricCell.table_id == t.id))}
    ds = days_of(t)
    out = []
    for ri, row in enumerate(rows):
        cs = []
        for d in ds:
            c = cells.get((row, d))
            p, a = (c.plan, c.actual) if c else (None, None)
            cs.append({"day": d, "key": d.strftime("%Y%m%d"), "plan": p, "actual": a,
                       "diff": (a - p) if (a is not None and p is not None) else None})
        ps, as_ = sum(x["plan"] or 0 for x in cs), sum(x["actual"] or 0 for x in cs)
        has = any(x["plan"] is not None or x["actual"] is not None for x in cs)
        diff = as_ - ps if has else None
        out.append({"i": ri, "name": row, "cells": cs, "plan": ps if has else None, "actual": as_ if has else None, "diff": diff,
                    "note": notes.get(row, ""), "needs_note": bool(diff) and not notes.get(row, "").strip()})
    return {"t": t, "days": ds, "rows": out, "plan": sum(r["plan"] or 0 for r in out), "actual": sum(r["actual"] or 0 for r in out)}


# ── SVG (metrics.js 와 같은 좌표 규칙) ──────────────────
def _scale(series: list[float | None], extra: list[float | None] = ()) -> tuple[float, float]:
    nums = [v for v in [*series, *extra] if v is not None]
    if not nums:
        return 0.0, 1.0
    lo, hi = min(nums), max(nums)
    if lo == hi:
        lo, hi = lo - 1, hi + 1
    return lo, hi


def spark_svg(series: list[float | None], flag: str = "") -> str:
    lo, hi = _scale(series)
    n = len(series)
    step = (SPARK_W - 2 * SPARK_PAD) / max(n - 1, 1)
    pts = [(SPARK_PAD + i * step, SPARK_H - SPARK_PAD - (v - lo) / (hi - lo) * (SPARK_H - 2 * SPARK_PAD))
           for i, v in enumerate(series) if v is not None]
    color = "var(--danger)" if flag else "var(--accent)"
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    last = series[-1] is not None and pts
    dot = f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="2.6" fill="{color}"/>' if last else ""
    poly = f'<polyline points="{line}" fill="none" stroke="var(--muted)" stroke-width="1.5"/>' if len(pts) > 1 else ""
    return (f'<svg class="spark" viewBox="0 0 {SPARK_W} {SPARK_H}" aria-hidden="true">{poly}{dot}</svg>')


def bar_svg(labels: list[str], series: list[float | None], low: float | None = None, high: float | None = None) -> str:
    left, bottom, top = 26, BAR_H - 18, 8
    lo, hi = _scale(series, [low, high])
    lo = min(lo, 0) if lo >= 0 else lo
    n = len(series)
    slot = (BAR_W - left - 4) / max(n, 1)
    y = lambda v: bottom - (v - lo) / (hi - lo) * (bottom - top)   # noqa: E731
    parts = [f'<line x1="{left}" y1="{bottom}" x2="{BAR_W - 2}" y2="{bottom}" stroke="var(--line)"/>',
             f'<text x="{left - 4}" y="{top + 8}" text-anchor="end">{hi:g}</text>',
             f'<text x="{left - 4}" y="{bottom}" text-anchor="end">{lo:g}</text>']
    if low is not None and high is not None:
        parts.append(f'<rect x="{left}" y="{y(high):.1f}" width="{BAR_W - left - 2}" height="{max(y(low) - y(high), 0):.1f}" '
                     f'fill="var(--ok-soft)"/>')
    for i, (lab, v) in enumerate(zip(labels, series)):
        x = left + i * slot + slot * 0.2
        parts.append(f'<text x="{x + slot * 0.3:.1f}" y="{BAR_H - 4}" text-anchor="middle">{lab}</text>')
        if v is None:
            continue
        out = (high is not None and v > high) or (low is not None and v < low)
        fill = "var(--danger)" if out else ("var(--accent)" if i == n - 1 else "var(--muted)")
        parts.append(f'<rect x="{x:.1f}" y="{y(v):.1f}" width="{slot * 0.6:.1f}" height="{max(bottom - y(v), 0):.1f}" fill="{fill}"/>')
    return (f'<svg class="chart" viewBox="0 0 {BAR_W} {BAR_H}" role="img" aria-label="주차별 막대 차트">{"".join(parts)}</svg>')


def ensure_dashboard_block(s: Session, section: m.Section) -> m.Block:
    """이번 주 섹션의 대시보드 블록 — 없으면 만든다(값을 넣을 자리)."""
    for b in w.section_blocks(s, section):
        if b.block_type == "dashboard":
            return b
    dept = s.get(m.Department, section.department_id)
    b = m.Block(id=w.new_block_id(s, "dashboard", int(section.week_id[:4])), block_type="dashboard",
                title=f"{dept.name if dept else section.department_id} 시운전 지표", body="", status=w.POSTED,
                owner_department_id=section.department_id, created_week_id=section.week_id, origin="manual")
    s.add(b)
    s.add(m.SectionBlock(section_id=section.id, block_id=b.id, order_no=len(w.section_blocks(s, section))))
    s.flush()
    return b
