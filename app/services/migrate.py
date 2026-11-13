"""옛 섹션 → 회의자료 이전(M12, 2026-10-23, docs/06 §5 「이전」).

- 주차×부서 섹션 하나 = 그 주 부서 회의자료 하나. 섹션에 실린 블록 = 장(report_item, src 「옛 섹션」), 순서 그대로.
  회의용 한 줄은 그 주 이력 한 줄(없으면 제목).
- **확정된 섹션 = 제출 1판**. 그 주에 제출판이 하나라도 생기면 공유회도 **발행 1판**으로 고정한다(종결 요청 자동 채택은 하지 않는다 —
  지난 주의 공유회에 지금 대기 중인 요청이 끼면 안 되므로).
- 이미 장이 있거나 판이 있는 회의는 건드리지 않는다 → **다시 실행해도 중복 없음**. 원본(섹션·메모·사진)은 그대로(원칙 1).
- 판에 담기는 사실은 **이전하는 때의 이슈 값**이다(옛 섹션에는 그 주의 사실 사본이 없었다). 이 점은 판의 meeting 에 `migrated` 로 남긴다.
- 기본은 이번 주 **이전** 주차만. 이번 주 섹션은 회의자료 스튜디오에서 이어서 쓴다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.services import carry_over as co
from app.services import studio as st
from app.services import weeks
from app.services import writing as w


@dataclass
class Report:
    dept_decks: list[str] = field(default_factory=list)      # "2026-W40 D3 장 4 · 제출 1판"
    shares: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _line(s: Session, b: m.Block, week_id: str) -> str:
    row = co.week_row(s, b.id, week_id)
    return ((row.note if row and (row.note or "").strip() else "") or b.title or b.id)[:st.LINE_MAX]


def _mark(s: Session, mt: m.Meeting) -> None:
    v = st.latest_version(s, mt)
    d = json.loads(v.snapshot_json)
    d["meeting"]["migrated"] = True
    v.snapshot_json = json.dumps(d, ensure_ascii=False, default=str)


def migrate(s: Session, until_week: str | None = None) -> Report:
    """until_week 이전(그 주 제외) 주차의 섹션을 옮긴다. 기본 = 이번 주."""
    until = until_week or weeks.current().id
    rep = Report()
    week_ids = sorted({x for x in s.scalars(select(m.Section.week_id).where(m.Section.week_id < until))})
    for wk in week_ids:
        st.ensure_week_meetings(s, wk)
        any_submit = False
        for sec in s.scalars(select(m.Section).where(m.Section.week_id == wk).order_by(m.Section.department_id)):
            blocks = w.section_blocks(s, sec)
            dm = st.week_meeting(s, wk, "dept", sec.department_id)
            if dm is None or not blocks:
                continue
            if st.items(s, dm) or dm.version:
                rep.skipped.append(f"{wk} {sec.department_id} — 이미 장·판이 있음")
                any_submit = any_submit or bool(dm.version)
                continue
            for n, b in enumerate(blocks):
                s.add(m.ReportItem(meeting_id=dm.id, kind="single", block_id=b.id, line=_line(s, b, wk),
                                   form="detail" if (b.decision_needed or "").strip() else "card", order_no=(n + 1) * 10, src="옛 섹션"))
            dm.start_mode = "carry"
            s.flush()
            note = ""
            if sec.status == "확정":
                st._freeze(s, dm, "제출")
                _mark(s, dm)
                any_submit, note = True, " · 제출 1판"
            rep.dept_decks.append(f"{wk} {sec.department_id} 장 {len(blocks)}{note}")
        sh = st.week_meeting(s, wk, "share")
        if any_submit and sh is not None and not st.latest_version(s, sh):
            if st.deck_block_ids(st.deck(s, sh)):
                st._freeze(s, sh, "발행")
                _mark(s, sh)
                rep.shares.append(f"{wk} 공유회 발행 1판")
    s.flush()
    return rep
