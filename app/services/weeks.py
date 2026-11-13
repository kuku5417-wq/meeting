"""ISO 주차 유틸 — 주차 ID `2026-W42`, 머리글 표기 `2026-W42 · 10.12–10.16`(월~금)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, timedelta

_WEEK_RE = re.compile(r"^(\d{4})-W(\d{2})$")


@dataclass(frozen=True)
class IsoWeek:
    id: str
    start: date   # 월요일
    end: date     # 금요일 (머리글 표기 기준)

    @property
    def label(self) -> str:
        return f"{self.id} · {self.start:%m.%d}–{self.end:%m.%d}"


def from_date(d: date) -> IsoWeek:
    y, w, _ = d.isocalendar()
    return from_id(f"{y}-W{w:02d}")


def today() -> date:
    """오늘. 환경변수 MEETING_TODAY(2026-10-23)가 있으면 그 날 — _smoke.py 가 날짜에 따라 결과가 바뀌지 않게 고정한다(운영에서는 두지 않는다)."""
    v = os.environ.get("MEETING_TODAY", "").strip()
    if v:
        try:
            return date.fromisoformat(v)
        except ValueError:  # noqa: BLE001 — 형식이 틀리면 실제 오늘
            pass
    return date.today()


def current() -> IsoWeek:
    return from_date(today())


def parse(week_id: str) -> IsoWeek | None:
    """형식이 틀리거나 존재하지 않는 주차면 None."""
    m = _WEEK_RE.match(week_id or "")
    if not m:
        return None
    try:
        start = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    except ValueError:  # noqa: PERF203 — 53주가 없는 해의 W53 등
        return None
    return IsoWeek(week_id, start, start + timedelta(days=4))


def shift(week_id: str, n: int) -> IsoWeek:
    """n 주 뒤(음수면 앞) 주차."""
    return from_date(from_id(week_id).start + timedelta(weeks=n))


def between(a: str, b: str) -> int:
    """a → b 사이 주 수 (b 가 뒤면 양수)."""
    return (from_id(b).start - from_id(a).start).days // 7


def from_id(week_id: str) -> IsoWeek:
    w = parse(week_id)
    if w is None:
        raise ValueError(f"주차 형식이 아닙니다: {week_id!r} (예: 2026-W42)")
    return w
