"""회의 · 팀 보고서 (화면 B) — 요약 4칸, 제출 현황, 회의 중 등록, 회의록 추출, 코멘트, 발표 모드 데이터.

- 회의 중 바로 등록한 이슈는 `origin="meeting"` 블록으로 만들고, **다음 주** 그 부서 섹션에
  「회의 발생」 표시로 이어받는다(`carry_over.candidates` 가 함께 본다).
- 회의록 추출(`extract_meeting_items`)은 작성 화면의 추출과 같은 규칙: 근거가 메모와 글자 그대로 맞지 않으면 버리고,
  연결 제안은 이번 주 블록에 실제로 있는 ID 만 믿는다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m
from app import settings
from app.llm import client as llm
from app.services import carry_over as co
from app.services import departments as dp
from app.services import extract as ex
from app.services import weeks
from app.services import writing as w

PROMPT = settings.ROOT / "app" / "llm" / "prompts" / "extract_meeting_items.md"
SCHEMA = settings.ROOT / "schema" / "meeting_items.schema.json"


def get_meeting(s: Session, week_id: str) -> m.Meeting:
    mt = s.scalar(select(m.Meeting).where(m.Meeting.week_id == week_id, m.Meeting.kind == "share").order_by(m.Meeting.id).limit(1))   # M10: 주차당 여러 회의 — 옛 화면은 공유회
    if mt is None:
        w.ensure_week(s, weeks.from_id(week_id))
        mt = m.Meeting(week_id=week_id, kind="share")
        s.add(mt)
        s.flush()
    return mt


def week_blocks(s: Session, week_id: str) -> list[m.Block]:
    """이번 주 안건 — 공유회 발행본이 있으면 그 판의 부서 순서·장 순서(M11), 없으면 옛 섹션에 실린 블록(부서 순서·섹션 순서)."""
    from app.services import studio as st         # 순환 import 회피
    pub = st.published_blocks(s, week_id)
    if pub is not None:
        return [b for ids in pub.values() for b in (s.get(m.Block, x) for x in ids) if b is not None]
    return list(s.scalars(
        select(m.Block).join(m.SectionBlock, m.SectionBlock.block_id == m.Block.id)
        .join(m.Section, m.Section.id == m.SectionBlock.section_id)
        .join(m.Department, m.Department.id == m.Section.department_id)
        .where(m.Section.week_id == week_id).order_by(m.Department.order_no, m.SectionBlock.order_no)))


def register(s: Session, week_id: str, title: str, dept_id: str, block_type: str = "issue") -> m.Block:
    """회의 중 바로 등록 — 다음 주 그 부서 섹션에 「회의 발생」으로 이어온다."""
    title = (title or "").strip()
    if not title:
        raise w.WriteError("이슈 제목을 적어주세요.")
    if len(title) > 80:
        raise w.WriteError("제목은 80자 이내로 적어주세요.")
    if block_type not in w.TRACKED:
        raise w.WriteError("회의 중 등록은 이슈·문제점만 됩니다.")
    if s.get(m.Department, dept_id) is None:
        raise w.WriteError("담당 부서를 골라주세요.")
    w.ensure_week(s, weeks.from_id(week_id))
    b = m.Block(id=w.new_block_id(s, block_type, int(week_id[:4])), block_type=block_type, title=title, body="",
                status="신규", owner_department_id=dept_id, created_week_id=week_id, origin="meeting")
    s.add(b)
    s.flush()
    co.add_history(s, b, week_id, note="회의 중 등록")
    get_meeting(s, week_id)
    return b


# ── 회의록 추출 ─────────────────────────────────────────
@dataclass
class MinutesOutcome:
    result: llm.LLMResult
    added: list[int] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)


def extract_minutes(s: Session, week_id: str, raw_text: str, meeting: m.Meeting | None = None) -> MinutesOutcome:
    if not (raw_text or "").strip():
        raise w.WriteError("회의록 메모가 비어 있습니다.")
    mt = meeting or get_meeting(s, week_id)
    lines = ex.memo_lines(raw_text)
    numbered = "\n".join(f"L{i}: {t}" for i, (t, _) in enumerate(lines, 1))
    blocks = week_blocks(s, week_id) + [b for b in s.scalars(select(m.Block).where(
        m.Block.status.in_(co.OPEN), m.Block.block_type.in_(w.TRACKED)))]
    seen, listing = set(), []
    for b in blocks:
        if b.id not in seen:
            seen.add(b.id)
            listing.append(f"{b.id}: {b.title}")
    user = (f"주차: {week_id}\n\n[부서 목록]\n{dp.names_line(s)}\n\n[회의록 메모]\n{numbered}\n\n[이번 주 블록]\n"
            + ("\n".join(listing[:80]) or "(없음)"))
    res = llm.complete_json("extract_meeting_items", PROMPT.read_text(encoding="utf-8"), user,
                            json.loads(SCHEMA.read_text(encoding="utf-8")), session=s)
    out = MinutesOutcome(result=res)
    if not res.ok:
        return out
    for it in res.data["items"]:
        if not ex._ev_ok(it.get("evidence"), lines):
            out.dropped.append(f"'{it.get('title', '')[:30]}' — 근거가 메모와 맞지 않아 버림")
            continue
        ref = it.get("link_block_ref")
        linked = ref if ref and ref in seen and s.get(m.Block, ref) else None   # 목록에 있던 실제 블록만
        raw = lines[it["evidence"]["line"] - 1][0]
        # 담당 부서: AI 표기(줄임말 포함) → 못 좁히면 그 메모 줄의 「…부·팀·Lab」 낱말로 한 번 더
        dept = dp.resolve(s, it.get("department_hint")) or dp.find_in_text(s, raw)
        cand = m.MeetingCandidate(meeting_id=mt.id, raw_text=raw,
                                  suggested_title=it["title"].strip()[:256],
                                  suggested_department_id=dept,
                                  linked_block_id=linked, state="제안")
        s.add(cand)
        s.flush()
        out.added.append(cand.id)
    return out


def candidates(s: Session, week_id: str, meeting: m.Meeting | None = None) -> list[m.MeetingCandidate]:
    mt = meeting or s.scalar(select(m.Meeting).where(m.Meeting.week_id == week_id, m.Meeting.kind == "share").order_by(m.Meeting.id).limit(1))   # M10: 주차당 여러 회의 — 옛 화면은 공유회
    if mt is None:
        return []
    return list(s.scalars(select(m.MeetingCandidate).where(m.MeetingCandidate.meeting_id == mt.id)
                          .order_by(m.MeetingCandidate.id)))


def _cand_open(c: m.MeetingCandidate) -> None:
    if c.state != "제안":
        raise w.WriteError(f"이미 처리한 후보입니다({c.state}).")


def candidate_register(s: Session, c: m.MeetingCandidate, week_id: str, title: str, dept_id: str) -> m.Block:
    _cand_open(c)
    b = register(s, week_id, title or c.suggested_title, dept_id or (c.suggested_department_id or ""))
    c.state, c.linked_block_id = "등록", b.id
    s.flush()
    return b


def candidate_link(s: Session, c: m.MeetingCandidate, week_id: str, block_id: str) -> m.Block:
    """기존 블록에 연결 — 그 블록의 이번 주 이력과 회의 코멘트로 남긴다."""
    _cand_open(c)
    b = s.get(m.Block, block_id or (c.linked_block_id or ""))
    if b is None:
        raise w.WriteError("연결할 블록을 골라주세요.")
    co.add_history(s, b, week_id, note=f"회의: {c.raw_text[:200]}")
    s.add(m.MeetingComment(meeting_id=c.meeting_id, block_id=b.id, text=c.raw_text[:500]))
    c.state, c.linked_block_id = "연결", b.id
    s.flush()
    return b


def candidate_drop(s: Session, c: m.MeetingCandidate) -> None:
    _cand_open(c)
    c.state = "버림"
    s.flush()
