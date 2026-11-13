"""작성 흐름 — 주차·섹션·메모, 블록 수정, 태그 확인·연결, 빈 칸 질문. 섹션 확정·확정 전 체크는 M12(2026-10-23)에서 없앴다.

원칙(CLAUDE.md §6)이 코드로 걸리는 자리:
  1. 메모 원문은 저장 후 바꾸지 않는다 — 수정 함수가 없다.
  2. 사람이 AI 값을 고치면 `ai_field_log` 에 (AI 값, 사람 값)을 남긴다 → 재정리 때 그 필드는 건드리지 않는다.
  4. 빈 칸 질문은 필수 항목(제목·상태·문제점의 원인)만, 블록당 2개·섹션 3개 이내.
  5. 사람이 태그 대상을 고르면 별칭 사전에 추가(source=user).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m
from app.services import weeks

PREFIX = {"issue": "ISS", "problem": "PRB", "share": "SHR", "dashboard": "DSH"}
TYPE_LABEL = {"issue": "이슈", "problem": "문제점", "share": "공유정보", "dashboard": "대시보드"}
TRACKED = ("issue", "problem")                  # 상태(신규/진행…)가 있는 유형
POSTED = "게시"                                  # 공유정보·대시보드의 상태
EDITABLE_STATUS = ("신규", "진행")               # 종결 요청은 M3 (조치 내용 필수)
LINKABLE = {"hull", "installed_equipment", "component", "system", "test_item"}   # 미연결이면 확인 대상
LOW_CONFIDENCE = 0.7
KIND_LABEL = {"hull": "호선", "installed_equipment": "장비", "system": "시스템", "component": "부위",
              "test_item": "시운전 항목", "symptom": "증상", "cause": "원인", "action": "조치",
              "next_action": "다음 액션", "related": "분류", "owner_person": "담당"}
QUESTION_TEXT = {
    "title": ("이 블록의 제목을 적어주세요.", "예: SN2514 카고펌프 No.3 씰 누유"),
    "status": ("진행 상태를 골라주세요.", ""),
    "cause": ('원인이 확인됐나요? 모르면 "조사 중"이라고 적어주세요.', "예: 씰 면 손상 / 축 정렬 불량 / 조사 중"),
}
MAX_Q_BLOCK, MAX_Q_SECTION = 2, 3
TEXT_FIELDS = ("body", "cause_text", "action_text", "decision_needed")   # 자유 글 칸(M9: body = 현상)
TEXT_MAX = 2000


class WriteError(ValueError):
    """화면에 그대로 보여줄 한국어 사유."""


# ── 주차·섹션·메모 ──────────────────────────────────────
def ensure_week(s: Session, w: weeks.IsoWeek) -> m.Week:
    row = s.get(m.Week, w.id)
    if row is None:
        row = m.Week(id=w.id, start_date=w.start, end_date=w.end)
        s.add(row)
        s.flush()
    return row


def get_section(s: Session, week_id: str, dept_id: str, create: bool = False) -> m.Section | None:
    sec = s.scalar(select(m.Section).where(m.Section.week_id == week_id, m.Section.department_id == dept_id))
    if sec is None and create:
        if s.get(m.Department, dept_id) is None:
            raise WriteError(f"부서 {dept_id} 가 기준정보에 없습니다. 기준정보 시드를 먼저 실행해주세요.")
        ensure_week(s, weeks.from_id(week_id))
        sec = m.Section(week_id=week_id, department_id=dept_id, status="작성중")
        s.add(sec)
        s.flush()
    return sec


def _next_seq(s: Session, model, prefix: str, width: int) -> str:
    ids = s.scalars(select(model.id).where(model.id.like(f"{prefix}%"))).all()
    n = max((int(i[len(prefix):]) for i in ids if i[len(prefix):].isdigit()), default=0) + 1
    return f"{prefix}{n:0{width}d}"


def new_block_id(s: Session, block_type: str, year: int) -> str:
    return _next_seq(s, m.Block, f"{PREFIX[block_type]}-{year}-", 4)


def add_memo(s: Session, section: m.Section, raw_text: str, author_id: int | None = None) -> m.Memo:
    if not (raw_text or "").strip():
        raise WriteError("메모가 비어 있습니다. 회의자료로 정리할 내용을 붙여넣어주세요.")
    memo = m.Memo(id=_next_seq(s, m.Memo, f"MEMO-{datetime.now().year}-", 5), section_id=section.id,
                  author_id=author_id, raw_text=raw_text)          # 원문 그대로 — 다듬지 않는다
    s.add(memo)
    s.flush()
    return memo


def revise_memo(s: Session, memo: m.Memo, raw_text: str, author_id: int | None = None) -> m.Memo:
    """원문 수정 — 옛 판은 그대로 두고 새 판을 만든다(원칙 1). 최신 판만 고칠 수 있다."""
    if not (raw_text or "").strip():
        raise WriteError("고친 원문이 비어 있습니다. 메모를 지우려는 것이면 내용을 남겨 두고 블록을 정리해주세요.")
    if raw_text == memo.raw_text:
        raise WriteError("바뀐 내용이 없습니다. 원문을 고친 뒤 저장해주세요.")
    newer = s.scalar(select(m.Memo.id).where(m.Memo.revises_id == memo.id).limit(1))
    if newer:
        raise WriteError(f"{memo.id} 는 이미 {newer} 로 고쳐졌습니다. 최신 판에서 고쳐주세요.")
    new = m.Memo(id=_next_seq(s, m.Memo, f"MEMO-{datetime.now().year}-", 5), section_id=memo.section_id,
                 author_id=author_id, raw_text=raw_text, revises_id=memo.id)
    s.add(new)
    s.flush()
    return new


def memo_chain(s: Session, memo: m.Memo) -> list[m.Memo]:
    """앞 판들 — 가까운 판부터 (자기 자신 제외)."""
    out, cur, seen = [], memo, {memo.id}
    while cur.revises_id and cur.revises_id not in seen:
        cur = s.get(m.Memo, cur.revises_id)
        if cur is None:
            break
        seen.add(cur.id)
        out.append(cur)
    return out


def latest_memos(s: Session, section: m.Section) -> list[m.Memo]:
    """화면에 보일 메모 — 다음 판이 없는 것만, 처음 판의 작성 순서대로."""
    memos = list(s.scalars(select(m.Memo).where(m.Memo.section_id == section.id).order_by(m.Memo.created_at, m.Memo.id)))
    replaced = {x.revises_id for x in memos if x.revises_id}
    latest = [x for x in memos if x.id not in replaced]
    first_of = {x.id: (memo_chain(s, x)[-1] if x.revises_id else x) for x in latest}
    return sorted(latest, key=lambda x: (first_of[x.id].created_at, first_of[x.id].id))


# ── 블록 조회·수정 ──────────────────────────────────────
def section_blocks(s: Session, section: m.Section) -> list[m.Block]:
    return list(s.scalars(select(m.Block).join(m.SectionBlock, m.SectionBlock.block_id == m.Block.id)
                          .where(m.SectionBlock.section_id == section.id).order_by(m.SectionBlock.order_no)))


def block_section(s: Session, block_id: str) -> m.Section | None:
    return s.scalar(select(m.Section).join(m.SectionBlock, m.SectionBlock.section_id == m.Section.id)
                    .where(m.SectionBlock.block_id == block_id).order_by(m.Section.week_id.desc()).limit(1))


def human_fields(s: Session, block_id: str) -> set[str]:
    """사람이 한 번이라도 고친 필드 — 재정리가 덮어쓰지 않는다."""
    return set(s.scalars(select(m.AiFieldLog.field).where(
        m.AiFieldLog.block_id == block_id, m.AiFieldLog.human_value.is_not(None))))


def _ai_value(s: Session, block_id: str, field: str) -> str | None:
    return s.scalar(select(m.AiFieldLog.ai_value).where(
        m.AiFieldLog.block_id == block_id, m.AiFieldLog.field == field, m.AiFieldLog.human_value.is_(None))
        .order_by(m.AiFieldLog.id.desc()).limit(1))


def update_block(s: Session, block: m.Block, field: str, value: str) -> bool:
    """사람의 수정 1건. 값이 실제로 바뀌면 ai_field_log 에 (AI 값, 사람 값) 기록. 바뀌었으면 True."""
    value = (value or "").strip() if field != "body" else (value or "")
    if field in TEXT_FIELDS and len(value) > TEXT_MAX:
        raise WriteError(f"{TEXT_MAX}자 이내로 적어주세요.")
    if field == "title":
        if not value:
            raise WriteError("제목은 비울 수 없습니다.")
        if len(value) > 80:
            raise WriteError("제목은 80자 이내로 적어주세요.")
    elif field == "block_type":
        if value not in PREFIX:
            raise WriteError("블록 유형이 올바르지 않습니다.")
    elif field == "status":
        allowed = EDITABLE_STATUS if block.block_type in TRACKED else (POSTED,)
        if value not in allowed:
            raise WriteError(f"상태는 {' / '.join(allowed)} 중에서 골라주세요.")
    elif field not in TEXT_FIELDS:
        raise WriteError(f"고칠 수 없는 항목입니다: {field}")
    if (getattr(block, field) or "") == value:
        return False
    setattr(block, field, value)
    if field == "block_type":               # 유형이 바뀌어도 ID 는 그대로(docs/03 §1), 상태만 유형에 맞춘다
        if value in TRACKED and block.status not in EDITABLE_STATUS:
            block.status = "신규"
        elif value not in TRACKED:
            block.status = POSTED
    s.add(m.AiFieldLog(block_id=block.id, field=field, ai_value=_ai_value(s, block.id, field), human_value=value))
    s.flush()
    return True


# ── 태그 ────────────────────────────────────────────────
def block_tags(s: Session, block_id: str) -> list[m.BlockTag]:
    return list(s.scalars(select(m.BlockTag).where(m.BlockTag.block_id == block_id, m.BlockTag.dismissed.is_(False))
                          .order_by(m.BlockTag.id)))


def block_hull(s: Session, block_id: str) -> str | None:
    return s.scalar(select(m.BlockTag.target_id).where(
        m.BlockTag.block_id == block_id, m.BlockTag.kind == "hull", m.BlockTag.target_id.is_not(None)).limit(1))


def tag_needs_check(t: m.BlockTag) -> bool:
    if t.confirmed:
        return False
    if t.kind in LINKABLE and not t.target_id:
        return True
    return t.confidence is not None and t.confidence < LOW_CONFIDENCE


def confirm_tag(s: Session, tag: m.BlockTag) -> None:
    if tag.kind in LINKABLE and not tag.target_id:
        raise WriteError(f"'{tag.raw_text}' 는 아직 기준정보에 연결되지 않았습니다. 목록에서 대상을 골라주세요.")
    tag.confirmed = True
    s.flush()


def mark_unregistered(s: Session, tag: m.BlockTag) -> None:
    """기준정보에 없는 장비·호선·부위 — 사람이 「미등록」으로 확인. 확정을 막지 않고, 미등록 표기 목록에 모인다."""
    if tag.kind not in LINKABLE or tag.target_id:
        raise WriteError("기준정보에 연결해야 하는 태그만 미등록으로 둘 수 있습니다.")
    tag.confirmed = True
    s.flush()


def dismiss_tag(s: Session, tag: m.BlockTag) -> None:
    """AI 가 잘못 단 태그 빼기 — 행은 남겨(확인됨) 다시 정리해도 같은 태그가 되살아나지 않게 한다."""
    tag.dismissed, tag.confirmed, tag.target_id = True, True, None
    s.flush()


def link_tag(s: Session, tag: m.BlockTag, target_id: str) -> None:
    """사람이 대상을 고른다 → 태그 확정 + 별칭 사전 추가(source=user, 장비면 그 호선 범위)."""
    model = {"installed_equipment": m.InstalledEquipment, "component": m.Component, "hull": m.Hull,
             "system": m.System, "test_item": m.TestItem}.get(tag.kind)
    if model is None or s.get(model, target_id) is None:
        raise WriteError("고른 대상이 기준정보에 없습니다.")
    tag.target_id, tag.confirmed = target_id, True
    scope = block_hull(s, tag.block_id) if tag.kind == "installed_equipment" else None
    if tag.raw_text and tag.kind != "hull":
        exists = s.scalar(select(m.Alias.id).where(
            m.Alias.text == tag.raw_text, m.Alias.target_kind == tag.kind, m.Alias.target_id == target_id,
            m.Alias.scope_hull_id.is_(None) if scope is None else m.Alias.scope_hull_id == scope))
        if exists is None:
            s.add(m.Alias(text=tag.raw_text, target_kind=tag.kind, target_id=target_id,
                          scope_hull_id=scope, source="user"))
    s.flush()


def link_options(s: Session, tag: m.BlockTag) -> list[tuple[str, str]]:
    """미연결 태그에서 고를 수 있는 대상 — 장비는 블록 호선의 탑재 장비만."""
    if tag.kind == "installed_equipment":
        hull = block_hull(s, tag.block_id)
        q = select(m.InstalledEquipment).order_by(m.InstalledEquipment.id)
        if hull:
            q = q.where(m.InstalledEquipment.hull_id == hull)
        return [(e.id, f"{e.hull_id} {e.name}") for e in s.scalars(q)]
    if tag.kind == "component":
        return [(c.id, c.name) for c in s.scalars(select(m.Component).order_by(m.Component.id))]
    if tag.kind == "hull":
        return [(h, h) for h in s.scalars(select(m.Hull.id).order_by(m.Hull.id))]
    if tag.kind == "system":
        return [(x.id, f"{x.code} {x.name}" if x.code else x.name)
                for x in s.scalars(select(m.System).order_by(m.System.id))]
    if tag.kind == "test_item":
        return [(x.id, x.name) for x in s.scalars(select(m.TestItem).order_by(m.TestItem.id))]
    return []


def tag_label(s: Session, t: m.BlockTag) -> str:
    """태그에 보여줄 이름 — 기준정보 이름이 있으면 그것, 없으면 메모 표기."""
    if t.target_id:
        if t.kind == "installed_equipment":
            e = s.get(m.InstalledEquipment, t.target_id)
            return e.name if e else t.target_id
        if t.kind == "component":
            c = s.get(m.Component, t.target_id)
            return c.name if c else t.target_id
        if t.kind == "symptom":
            c = s.get(m.SymptomCode, t.target_id)
            return c.name if c else t.target_id
        if t.kind == "cause":
            c = s.get(m.CauseCode, t.target_id)
            return c.name if c else t.target_id
        return t.target_id
    return t.raw_text or ""


# ── 빈 칸 질문 ──────────────────────────────────────────
@dataclass
class Question:
    block_id: str
    field: str
    text: str
    placeholder: str


def missing_fields(s: Session, b: m.Block) -> list[str]:
    out = []
    if not (b.title or "").strip():
        out.append("title")
    if b.block_type in TRACKED and b.status not in EDITABLE_STATUS + ("종결요청",):
        out.append("status")
    if b.block_type == "problem" and not any(t.kind == "cause" for t in block_tags(s, b.id)):
        out.append("cause")
    return out


def questions(s: Session, blocks: list[m.Block]) -> dict[str, list[Question]]:
    """블록별 빈 칸 질문 — 블록당 2개, 섹션 전체 3개까지(앞 블록부터)."""
    out: dict[str, list[Question]] = {}
    total = 0
    for b in blocks:
        for f in missing_fields(s, b)[:MAX_Q_BLOCK]:
            if total >= MAX_Q_SECTION:
                return out
            text, ph = QUESTION_TEXT[f]
            out.setdefault(b.id, []).append(Question(b.id, f, text, ph))
            total += 1
    return out


def answer_question(s: Session, block: m.Block, field: str, value: str) -> None:
    value = (value or "").strip()
    if not value:
        raise WriteError("답을 적어주세요.")
    if field in ("title", "status"):
        update_block(s, block, field, value)
        return
    if field == "cause":
        s.add(m.BlockTag(block_id=block.id, kind="cause", raw_text=value, confidence=None, confirmed=True))
        s.add(m.AiFieldLog(block_id=block.id, field="cause", ai_value=None, human_value=value))
        s.flush()
        return
    raise WriteError(f"답할 수 없는 항목입니다: {field}")
