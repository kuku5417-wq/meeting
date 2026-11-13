"""이슈 변경 기록(block_event) — 결정 ⑦(2026-11-13).

사실 칸을 어디서 고쳤든(이슈 작업대·부서 자료·공유회·팀장 정보회의) 이전 값·새 값·어디서를 덧붙인다.
덧붙이기만 한다 — 고치거나 지우지 않는다. 화면: 이슈 「변경 기록」. 다음 조각에서 자유 편집·「사실로 채택」·파생이 같은 표를 쓴다.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m

KINDS = ("사실변경", "자료수정", "개체추가", "파생", "합치기")
STAGE_BY_MEETING = {"dept": "부서", "share": "공유회", "exec": "팀장"}
FIELD_LABEL = {"title": "제목", "body": "현상", "cause_text": "원인", "action_text": "조치·계획",
               "decision_needed": "결정 필요", "status": "상태", "block_type": "유형"}
LINK_RELATIONS = ("재발", "동일원인", "관련", "참고", "파생", "합쳐짐")   # block_link.relation 허용 값


def stage_of(s: Session, meeting_id: int | None) -> str:
    if not meeting_id:
        return "작업대"
    mt = s.get(m.Meeting, meeting_id)
    if mt is None:
        return "작업대"
    return STAGE_BY_MEETING.get(mt.kind, "회의")


def record(s: Session, block_id: str, kind: str, *, field: str = "", before: str = "", after: str = "",
           meeting_id: int | None = None, actor_id: str | None = None) -> m.BlockEvent:
    if kind not in KINDS:
        raise ValueError(f"모르는 기록 종류: {kind}")
    ev = m.BlockEvent(block_id=block_id, kind=kind, stage=stage_of(s, meeting_id),
                      meeting_id=meeting_id if meeting_id and s.get(m.Meeting, meeting_id) else None,
                      actor_id=actor_id, field=field, before=before or "", after=after or "")
    s.add(ev)
    s.flush()
    return ev


def recent(s: Session, block_id: str, n: int = 8) -> list[dict]:
    rows = s.scalars(select(m.BlockEvent).where(m.BlockEvent.block_id == block_id)
                     .order_by(m.BlockEvent.id.desc()).limit(n))
    return [{"when": e.created_at.strftime("%m/%d %H:%M"), "kind": e.kind, "stage": e.stage,
             "field": FIELD_LABEL.get(e.field, e.field), "before": e.before, "after": e.after} for e in rows]
