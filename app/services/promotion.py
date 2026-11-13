"""종결 승인 / 보류 → 사례 카드 승격 (원칙 7, docs/03 §5 `promote`).

- 승인은 **회의에서만** 한다. 승인하면 블록은 「종결」, `closure` 는 승인, 사례 카드(증상·원인·조치)가 생긴다.
- 사례 카드는 증상·원인·조치가 모두 있어야 만든다(없으면 실패 — 사례 지식이 비지 않게).
  · 증상: 블록의 증상 태그 → 없으면 블록 제목
  · 원인: 블록의 원인 태그 → 없으면 승인할 때 회의에서 적은 원인(그대로 원인 태그로도 남긴다)
  · 조치: 종결 요청의 조치 내용
- 보류: `closure` 는 보류, 블록은 「진행」으로 돌아가 다음 주에 다시 이어온다.
섹션이 확정된 뒤에도 회의는 블록 상태를 바꾼다(확정은 부서 작성의 끝, 회의는 그다음 단계다).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.services import carry_over as co
from app.services import writing as w


def _tag(s: Session, block_id: str, kind: str) -> m.BlockTag | None:
    return s.scalar(select(m.BlockTag).where(m.BlockTag.block_id == block_id, m.BlockTag.kind == kind,
                                             m.BlockTag.dismissed.is_(False))
                    .order_by(m.BlockTag.confirmed.desc(), m.BlockTag.id).limit(1))


def _decide(s: Session, c: m.Closure, decision: str, week_id: str) -> None:
    if c.decision != "대기":
        raise w.WriteError(f"이미 {c.decision}된 종결 요청입니다.")
    c.decision, c.decided_week_id, c.decided_at = decision, week_id, datetime.now()


def approve(s: Session, closure: m.Closure, week_id: str, cause_text: str = "") -> m.CaseCard:
    block = s.get(m.Block, closure.block_id)
    cause_tag = _tag(s, block.id, "cause")
    cause_text = (cause_text or "").strip()
    if cause_tag is None and not cause_text:
        raise w.WriteError(f"{block.title or block.id}: 원인이 없어 사례 카드를 만들 수 없습니다. 원인을 적고 승인해주세요.")
    if not (closure.action_text or "").strip():
        raise w.WriteError(f"{block.title or block.id}: 조치 내용이 없어 승인할 수 없습니다.")
    if cause_tag is None:
        cause_tag = m.BlockTag(block_id=block.id, kind="cause", raw_text=cause_text, confirmed=True)
        s.add(cause_tag)
        s.flush()
    symptom_tag = _tag(s, block.id, "symptom")
    eq_tag = s.scalar(select(m.BlockTag).where(m.BlockTag.block_id == block.id, m.BlockTag.kind == "installed_equipment",
                                               m.BlockTag.target_id.is_not(None)).limit(1))
    _decide(s, closure, "승인", week_id)
    card = m.CaseCard(
        id=w._next_seq(s, m.CaseCard, "CASE-", 4), block_id=block.id,
        symptom_text=w.tag_label(s, symptom_tag) if symptom_tag else block.title,
        cause_text=w.tag_label(s, cause_tag) or cause_tag.raw_text,
        action_text=closure.action_text,
        symptom_code_id=symptom_tag.target_id if symptom_tag else None,
        cause_code_id=cause_tag.target_id if cause_tag and s.get(m.CauseCode, cause_tag.target_id or "") else None,
        installed_equipment_id=eq_tag.target_id if eq_tag else None,
        approved_week_id=week_id, validity="유효")
    s.add(card)
    block.status = "종결"
    co.add_history(s, block, week_id, note=f"회의 종결 승인 → {card.id}")
    s.flush()
    return card


def hold(s: Session, closure: m.Closure, week_id: str, reason: str = "") -> None:
    block = s.get(m.Block, closure.block_id)
    _decide(s, closure, "보류", week_id)
    block.status = "진행"
    co.add_history(s, block, week_id, note="회의 보류" + (f" — {reason.strip()}" if (reason or "").strip() else ""))
    s.flush()


def promote(s: Session, block_id: str, week_id: str, cause_text: str = "") -> m.CaseCard:
    """docs/03 §5 의 이름 — 대기 중인 종결 요청을 승인해 사례 카드를 만든다."""
    c = s.scalar(select(m.Closure).where(m.Closure.block_id == block_id, m.Closure.decision == "대기")
                 .order_by(m.Closure.id.desc()).limit(1))
    if c is None:
        raise w.WriteError(f"{block_id} 에 대기 중인 종결 요청이 없습니다.")
    return approve(s, c, week_id, cause_text)
