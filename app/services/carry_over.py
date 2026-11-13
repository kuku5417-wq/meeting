"""이어받기 · 이력 · 장기 미결 · 부서 이관 (docs/03 §2·§5, 기능 3).

- 이어받기: 이 부서가 담당(owner)인 이슈·문제점 중 열린 것(신규·진행·종결요청)을 이번 주 섹션에
  `carried_over=True` 로 다시 올린다. **같은 ID**, `block_history` 에 이번 주 행을 더한다. 신규 → 진행은 자동.
  지난주에 섹션을 안 냈어도 놓치지 않도록 「이번 주 이전의 아무 주」에 실렸던 블록을 본다(2026-10-20 결정).
- 이력 한 줄: 이번 주 행의 note 가 비어 있으면 「한 줄 없음」(홈·이슈 원장, 종결요청은 회의 대기라 제외). M12 에서 섹션 확정은 없앴다.
- 장기 미결: 진행 상태로 `settings.LONG_OPEN_WEEKS`(기본 4) 주 이상 업데이트 없음 → **표시만**, 상태가 아니다.
- 이관: 담당 부서만 바꾼다. ID 그대로, 이력에 「부서 A → 부서 B 이관」. 이번 주 섹션도 받는 부서로 옮긴다.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app import settings
from app.services import weeks
from app.services import writing as w

OPEN = ("신규", "진행", "종결요청")
NEEDS_LINE = ("신규", "진행")          # 이어왔으면 이번 주 한 줄이 필요한 상태


def add_history(s: Session, block: m.Block, week_id: str, note: str = "", dept_id: str | None = None) -> m.BlockHistory:
    row = m.BlockHistory(block_id=block.id, week_id=week_id, department_id=dept_id or block.owner_department_id,
                         status=block.status, note=note)
    s.add(row)
    s.flush()
    return row


def history(s: Session, block_id: str) -> list[m.BlockHistory]:
    return list(s.scalars(select(m.BlockHistory).where(m.BlockHistory.block_id == block_id)
                          .order_by(m.BlockHistory.week_id, m.BlockHistory.id)))


def week_row(s: Session, block_id: str, week_id: str) -> m.BlockHistory | None:
    return s.scalar(select(m.BlockHistory).where(m.BlockHistory.block_id == block_id, m.BlockHistory.week_id == week_id)
                    .order_by(m.BlockHistory.id.desc()).limit(1))


def candidates(s: Session, week_id: str, dept_id: str) -> list[m.Block]:
    """이번 주 섹션에 아직 없는, 이 부서 담당의 열린 이슈·문제점 (이전 주차에 실렸던 것)."""
    earlier = select(m.SectionBlock.block_id).join(m.Section, m.Section.id == m.SectionBlock.section_id) \
        .where(m.Section.week_id < week_id)
    already = select(m.SectionBlock.block_id).join(m.Section, m.Section.id == m.SectionBlock.section_id) \
        .where(m.Section.week_id == week_id)
    from_meeting = (m.Block.origin == "meeting") & (m.Block.created_week_id < week_id)   # 회의 중 등록 → 다음 주부터
    return list(s.scalars(select(m.Block).where(
        m.Block.owner_department_id == dept_id, m.Block.block_type.in_(w.TRACKED), m.Block.status.in_(OPEN),
        m.Block.id.in_(earlier) | from_meeting, m.Block.id.not_in(already)).order_by(m.Block.id)))


def carry_over(s: Session, week_id: str, dept_id: str) -> list[str]:
    """열린 블록을 이번 주 섹션으로 이어받는다. 다시 불러도 중복되지 않는다. 이어온 블록 ID 목록."""
    blocks = candidates(s, week_id, dept_id)
    if not blocks:
        return []
    sec = w.get_section(s, week_id, dept_id, create=True)
    order = len(w.section_blocks(s, sec))
    for b in blocks:
        if b.status == "신규":
            b.status = "진행"                          # 다음 주 이어받기 시 자동 (docs/03 §2)
        s.add(m.SectionBlock(section_id=sec.id, block_id=b.id, order_no=order, carried_over=True))
        order += 1
        add_history(s, b, week_id)
    s.flush()
    return [b.id for b in blocks]


def carried_blocks(s: Session, section: m.Section) -> list[m.Block]:
    return list(s.scalars(select(m.Block).join(m.SectionBlock, m.SectionBlock.block_id == m.Block.id)
                          .where(m.SectionBlock.section_id == section.id, m.SectionBlock.carried_over.is_(True))
                          .order_by(m.SectionBlock.order_no)))


def needs_line(s: Session, block: m.Block, week_id: str) -> bool:
    if block.status not in NEEDS_LINE:
        return False
    row = week_row(s, block.id, week_id)
    return row is None or not (row.note or "").strip()


def update_line(s: Session, block: m.Block, week_id: str, text: str) -> None:
    """이어온 블록의 이번 주 한 줄."""
    text = (text or "").strip()
    if not text:
        raise w.WriteError("이번 주 진행 상황을 한 줄 적어주세요. 변화가 없으면 \"변동 없음\" 도 됩니다.")
    row = week_row(s, block.id, week_id) or add_history(s, block, week_id)
    row.note, row.status = text, block.status
    s.flush()


def open_weeks(s: Session, block: m.Block, week_id: str) -> int:
    """마지막으로 내용이 적힌 주부터 이번 주까지 주 수."""
    rows = [r for r in history(s, block.id) if (r.note or "").strip() and r.week_id <= week_id]
    since = rows[-1].week_id if rows else block.created_week_id
    return max(0, weeks.between(since, week_id))


def long_open(s: Session, block: m.Block, week_id: str) -> int | None:
    """장기 미결이면 그 주 수, 아니면 None — 표시용."""
    if block.status != "진행":
        return None
    n = open_weeks(s, block, week_id)
    return n if n >= settings.LONG_OPEN_WEEKS else None


def transfer(s: Session, block: m.Block, to_dept: str, week_id: str) -> m.Section:
    """담당 부서 이관 — ID 유지, 이력 기록, 이번 주 섹션도 받는 부서로 옮긴다."""
    if block.block_type not in w.TRACKED:
        raise w.WriteError("이관은 이슈·문제점만 할 수 있습니다.")
    if block.status in ("종결요청", "종결"):
        raise w.WriteError("종결 요청 중이거나 종결된 블록은 이관할 수 없습니다. 회의에서 보류된 뒤 이관해주세요.")
    src_dept = s.get(m.Department, block.owner_department_id)
    dst = s.get(m.Department, to_dept)
    if dst is None:
        raise w.WriteError("받을 부서를 골라주세요.")
    if to_dept == block.owner_department_id:
        raise w.WriteError("지금 담당 부서와 같은 부서입니다.")
    src_sec = w.get_section(s, week_id, block.owner_department_id)
    dst_sec = w.get_section(s, week_id, to_dept, create=True)
    link = s.scalar(select(m.SectionBlock).where(m.SectionBlock.block_id == block.id,
                                                 m.SectionBlock.section_id == src_sec.id)) if src_sec else None
    carried = bool(link and link.carried_over)
    if link is not None:
        s.delete(link)
    s.add(m.SectionBlock(section_id=dst_sec.id, block_id=block.id,
                         order_no=len(w.section_blocks(s, dst_sec)), carried_over=carried))
    block.owner_department_id = to_dept
    add_history(s, block, week_id, note=f"{src_dept.name if src_dept else '?'} → {dst.name} 이관", dept_id=to_dept)
    s.flush()
    return dst_sec
