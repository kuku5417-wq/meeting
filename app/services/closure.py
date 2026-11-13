"""종결 요청 (원칙 7 — 종결은 회의 승인으로만).

부서는 「종결 요청」까지만 한다. 조치 내용(`action_text`)이 없으면 요청할 수 없다 —
종결된 이슈가 곧 사례 카드(증상·원인·조치)가 되기 때문이다. 승인·보류는 M6 회의 화면에서 한다.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.services import carry_over as co
from app.services import writing as w


def pending(s: Session, block_id: str) -> m.Closure | None:
    return s.scalar(select(m.Closure).where(m.Closure.block_id == block_id, m.Closure.decision == "대기")
                    .order_by(m.Closure.id.desc()).limit(1))


def request(s: Session, block: m.Block, week_id: str, action_text: str, person_id: int | None = None) -> m.Closure:
    if block.block_type not in w.TRACKED:
        raise w.WriteError("종결 요청은 이슈·문제점만 할 수 있습니다.")
    if block.status == "종결요청" or pending(s, block.id):
        raise w.WriteError("이미 종결 요청한 블록입니다. 회의에서 승인·보류를 기다립니다.")
    action_text = (action_text or "").strip()
    if not action_text:
        raise w.WriteError(f"{block.title or block.id}: 조치 내용을 적어야 종결 요청할 수 있습니다.")
    c = m.Closure(block_id=block.id, action_text=action_text, requested_by=person_id,
                  requested_week_id=week_id, decision="대기")
    s.add(c)
    block.status = "종결요청"
    s.add(m.AiFieldLog(block_id=block.id, field="status", ai_value=None, human_value="종결요청"))
    co.add_history(s, block, week_id, note=f"종결 요청 — {action_text}")
    s.flush()
    return c
