"""원천·작성 + 태그 모델 — docs/03 §3 「원천·작성」「태그」.

- `memo.raw_text` 는 **수정 금지**(원칙 1). 갱신 API 를 만들지 않는다.
  고칠 때는 새 판(Memo)을 만들고 `revises_id` 로 앞 판을 가리킨다 — 옛 판은 그대로 남는다(2026-10-21).
- 블록 ID 는 최초 등록 유형 접두어(ISS/PRB/SHR/DSH)로 발급하고, 유형·부서가 바뀌어도 유지한다.
- 상태값은 문서의 한국어 표기를 그대로 저장한다(신규/진행/종결요청/종결, 작성중/확정, 승인/보류/대기).
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _now() -> datetime:
    return datetime.now()


class Week(Base):
    __tablename__ = "week"
    id: Mapped[str] = mapped_column(String(8), primary_key=True)    # ISO 주차 2026-W42
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)


class Section(Base):
    """주차 × 부서 1행."""
    __tablename__ = "section"
    __table_args__ = (UniqueConstraint("week_id", "department_id", name="uq_section_week_dept"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_id: Mapped[str] = mapped_column(ForeignKey("week.id"))
    department_id: Mapped[str] = mapped_column(ForeignKey("department.id"))
    status: Mapped[str] = mapped_column(String(8), default="작성중")   # 작성중 / 확정
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Memo(Base):
    __tablename__ = "memo"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)   # MEMO-2026-00412
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    raw_text: Mapped[str] = mapped_column(Text)                      # 수정 금지
    revises_id: Mapped[str | None] = mapped_column(ForeignKey("memo.id"))   # 원문 수정본이면 앞 판 ID
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Block(Base):
    __tablename__ = "block"
    id: Mapped[str] = mapped_column(String(24), primary_key=True)   # ISS-2026-0142
    block_type: Mapped[str] = mapped_column(String(16))              # share / problem / issue / dashboard
    title: Mapped[str] = mapped_column(String(256), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="신규")
    owner_department_id: Mapped[str] = mapped_column(ForeignKey("department.id"))   # 이관 시 이것만 변경
    created_week_id: Mapped[str] = mapped_column(ForeignKey("week.id"))
    valid_until: Mapped[date | None] = mapped_column(Date)           # 공유정보 만료일
    origin: Mapped[str] = mapped_column(String(16), default="memo")  # memo / meeting / manual
    # M9 이슈 원장(2026-10-23) — body 는 「현상」, 아래 세 칸이 1차 초안 「상세 한 장」을 채운다
    draft_state: Mapped[str] = mapped_column(String(8), default="none")  # none 없음 / wip 작성 중 / ok 초안 완료
    cause_text: Mapped[str] = mapped_column(Text, default="")            # 원인(글) — 원인 코드 매핑은 block_tag(cause)
    action_text: Mapped[str] = mapped_column(Text, default="")           # 조치 · 계획
    decision_needed: Mapped[str] = mapped_column(Text, default="")       # 결정 필요(비우면 없음)
    important: Mapped[bool] = mapped_column(Boolean, default=False)      # 상위 보고용 중요 표시
    # F21 일정 경보(2026-10-23) — 「~전 해결」 목표: 마일스톤 이벤트(코드) 또는 직접 날짜. 날짜는 매번 마일스톤(실적→전망→계획)에서 다시 잡는다
    due_event: Mapped[str] = mapped_column(String(8), default="")       # "" 없음 / ST·GT·DL… / DATE 직접 날짜
    due_date: Mapped[date | None] = mapped_column(Date)                  # DATE 일 때만
    alert_days: Mapped[int | None] = mapped_column(Integer)              # 이 이슈만의 경보 일수(비우면 이벤트 기본값)
    alert_off_reason: Mapped[str] = mapped_column(Text, default="")      # 경보 해제 사유(비면 켜짐)
    alert_off_at: Mapped[datetime | None] = mapped_column(DateTime)
    alert_off_date: Mapped[date | None] = mapped_column(Date)            # 해제할 때의 목표 날짜 — 더 당겨지면 다시 켜진다
    created_by: Mapped[int | None] = mapped_column(ForeignKey("person.id"))


class SectionBlock(Base):
    """주차별 섹션에 어떤 블록이 실렸는지."""
    __tablename__ = "section_block"
    section_id: Mapped[int] = mapped_column(ForeignKey("section.id"), primary_key=True)
    block_id: Mapped[str] = mapped_column(ForeignKey("block.id"), primary_key=True)
    order_no: Mapped[int] = mapped_column(Integer, default=0)
    carried_over: Mapped[bool] = mapped_column(Boolean, default=False)


class BlockHistory(Base):
    __tablename__ = "block_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    block_id: Mapped[str] = mapped_column(ForeignKey("block.id"), index=True)
    week_id: Mapped[str] = mapped_column(ForeignKey("week.id"))
    department_id: Mapped[str] = mapped_column(ForeignKey("department.id"))
    status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class SourceSpan(Base):
    """AI 필드의 근거 구간 — 없으면 그 필드를 표시하지 않는다(원칙 3)."""
    __tablename__ = "source_span"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    block_id: Mapped[str] = mapped_column(ForeignKey("block.id"), index=True)
    field: Mapped[str] = mapped_column(String(32))
    memo_id: Mapped[str] = mapped_column(ForeignKey("memo.id"))
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text, default="")


class AiFieldLog(Base):
    """AI 값 vs 사람 값(원칙 2)."""
    __tablename__ = "ai_field_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    block_id: Mapped[str] = mapped_column(ForeignKey("block.id"), index=True)
    field: Mapped[str] = mapped_column(String(32))
    ai_value: Mapped[str | None] = mapped_column(Text)
    human_value: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Closure(Base):
    """종결 요청/결정 — 승인은 회의에서만(원칙 7)."""
    __tablename__ = "closure"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    block_id: Mapped[str] = mapped_column(ForeignKey("block.id"), index=True)
    action_text: Mapped[str] = mapped_column(Text)                   # 필수
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    requested_week_id: Mapped[str] = mapped_column(ForeignKey("week.id"))
    decision: Mapped[str] = mapped_column(String(8), default="대기")  # 승인 / 보류 / 대기
    decided_week_id: Mapped[str | None] = mapped_column(ForeignKey("week.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)


class BlockTable(Base):
    """블록에 붙인 표(측정값·점검 목록 등) — 이슈·문제점 블록. rows_json 은 [[머리글…], [값…], …] (2026-10-21)."""
    __tablename__ = "block_table"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    block_id: Mapped[str] = mapped_column(ForeignKey("block.id"), index=True)
    title: Mapped[str] = mapped_column(String(128), default="")
    rows_json: Mapped[str] = mapped_column(Text, default="[]")
    order_no: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class BlockTag(Base):
    """블록 ↔ 기준정보. target_id 가 비고 raw_text 만 있으면 미연결 태그.

    미연결인데 confirmed=True 면 「미등록」(기준정보에 없다고 사람이 확인, 2026-10-21).
    dismissed=True 는 사람이 뺀 태그 — 행은 남겨 다시 정리해도 되살아나지 않게 하고, 화면·출력에서는 뺀다.
    """
    __tablename__ = "block_tag"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    block_id: Mapped[str] = mapped_column(ForeignKey("block.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))   # hull, installed_equipment, system, component, test_item, symptom, cause, owner_person, next_action
    target_id: Mapped[str | None] = mapped_column(String(48))
    raw_text: Mapped[str | None] = mapped_column(String(256))
    confidence: Mapped[float | None] = mapped_column(Float)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
