"""사진·대시보드·회의·지식·운영 로그 모델 — docs/03 §3 나머지 표.

- 사진 원본은 불변. 마킹은 `annotation.shapes_json`(Konva 직렬화)으로만 저장한다(원칙 1).
- `llm_call_log` 는 본문을 저장하지 않는다(민감정보).
"""
from __future__ import annotations

from datetime import datetime

from datetime import date

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.writing import _now


# ── 사진 ────────────────────────────────────────────────
class Photo(Base):
    __tablename__ = "photo"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)   # PH-00381
    file_path: Mapped[str] = mapped_column(String(512))              # 데이터 폴더 기준 상대경로
    sha256: Mapped[str] = mapped_column(String(64), unique=True)     # 중복 업로드 방지
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("person.id"))


class PhotoLink(Base):
    __tablename__ = "photo_link"
    photo_id: Mapped[str] = mapped_column(ForeignKey("photo.id"), primary_key=True)
    block_id: Mapped[str] = mapped_column(ForeignKey("block.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(8), primary_key=True, default="main")   # main / before / after
    order_no: Mapped[int] = mapped_column(Integer, default=0)
    caption: Mapped[str] = mapped_column(String(80), default="")     # 사진 이름 (2026-10-21)
    note: Mapped[str] = mapped_column(Text, default="")              # 사진 설명


class Annotation(Base):
    __tablename__ = "annotation"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    photo_id: Mapped[str] = mapped_column(ForeignKey("photo.id"), index=True)
    block_id: Mapped[str | None] = mapped_column(ForeignKey("block.id"))
    shapes_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class Marker(Base):
    __tablename__ = "marker"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    annotation_id: Mapped[int] = mapped_column(ForeignKey("annotation.id"), index=True)
    no: Mapped[int] = mapped_column(Integer)
    x: Mapped[float] = mapped_column(Float)
    y: Mapped[float] = mapped_column(Float)
    label: Mapped[str] = mapped_column(String(256), default="")
    component_id: Mapped[str | None] = mapped_column(ForeignKey("component.id"))


# ── 대시보드 ────────────────────────────────────────────
class MetricDef(Base):
    __tablename__ = "metric_def"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("department.id"))
    name: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(16), default="")
    order_no: Mapped[int] = mapped_column(Integer, default=0)
    normal_low: Mapped[float | None] = mapped_column(Float)
    normal_high: Mapped[float | None] = mapped_column(Float)
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)       # F16 숨기기 — 값은 남고 표·회의자료에서만 뺀다


class MetricValue(Base):
    __tablename__ = "metric_value"
    __table_args__ = (UniqueConstraint("metric_def_id", "week_id", name="uq_metric_week"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    metric_def_id: Mapped[int] = mapped_column(ForeignKey("metric_def.id"))
    week_id: Mapped[str] = mapped_column(ForeignKey("week.id"))
    value: Mapped[float | None] = mapped_column(Float)
    comment: Mapped[str] = mapped_column(Text, default="")
    block_id: Mapped[str | None] = mapped_column(ForeignKey("block.id"))
    human: Mapped[bool] = mapped_column(Boolean, default=False)          # F16 사람이 넣은 값 — AI(메모 정리)가 덮지 않는다


# ── 회의 ────────────────────────────────────────────────
class Meeting(Base):
    """회의 한 건. M10(2026-10-23)부터 주차당 여러 개 — kind 로 갈래를 나눈다.
    옛 주차 회의(회의 · 팀 보고서 화면)는 kind=share 한 줄로 남는다(M11 까지 공식 흐름)."""
    __tablename__ = "meeting"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    week_id: Mapped[str] = mapped_column(ForeignKey("week.id"))
    held_at: Mapped[datetime | None] = mapped_column(DateTime)
    chair_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    kind: Mapped[str] = mapped_column(String(8), default="share")      # dept 부서 자료 / share 공유회 / exec 팀장 정보회의 / hull 호선별 / review 리뷰
    title: Mapped[str] = mapped_column(String(128), default="")
    owner_dept_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"))   # 부서 자료면 그 부서, 팀 회의면 비움
    held_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(8), default="구성 중")  # 구성 중 / 제출 / 수정됨 / 발행 / 종료
    start_mode: Mapped[str | None] = mapped_column(String(8))          # carry 지난주 이어받기 / blank 빈 자료 (부서별 기억)
    version: Mapped[int] = mapped_column(Integer, default=0)            # 제출·발행 판(0 = 아직)
    hull_id: Mapped[str | None] = mapped_column(String(16))              # 호선별 회의의 호선
    order_json: Mapped[str] = mapped_column(Text, default="")            # M11 공유회 부서 순서(JSON 부서 ID 목록, 비면 기준정보 순서)


class MeetingVersion(Base):
    """제출·발행 판(M11). 그 시점 회의자료 전체(장·표현·사실)를 JSON 으로 고정 — 회의에서 실제로 본 내용이 남는다."""
    __tablename__ = "meeting_version"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meeting.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    published_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    snapshot_json: Mapped[str] = mapped_column(Text)


class ReportItem(Base):
    """회의자료의 한 장(M10). 이슈 원장(block)과 따로 — 회의용 한 줄·형태·순서는 여기에만(표현), 사실은 이슈에."""
    __tablename__ = "report_item"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meeting.id"), index=True)
    kind: Mapped[str] = mapped_column(String(8), default="single")     # single 이슈 하나 / summary 여러 이슈 요약 / metric 지표 요약 / table 기간 표
    block_id: Mapped[str | None] = mapped_column(ForeignKey("block.id"))   # 대표 이슈(요약이면 첫 이슈)
    line: Mapped[str] = mapped_column(Text, default="")                # 회의용 한 줄(요약이면 요약 문장)
    tag_on: Mapped[bool] = mapped_column(Boolean, default=True)        # 머리표([결정필요] 등) 붙이기
    form: Mapped[str] = mapped_column(String(8), default="card")       # detail 상세 한 장 / card 카드 / photo 사진 강조 / line 한 줄
    order_no: Mapped[int] = mapped_column(Integer, default=0)
    src: Mapped[str] = mapped_column(String(32), default="")            # 지난주 / 새 초안 / 원장 / 요약 / 종결 요청 / 원장 채움
    dept_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"))   # M11 공유회 안에서 어느 부서 칸인지(종결 요청·원장 채움)
    table_id: Mapped[int | None] = mapped_column(ForeignKey("metric_table.id"))  # F16 기간 표 장(kind=table)이 그리는 표
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ReportItemBlock(Base):
    """요약 항목이 잇는 이슈들(M10)."""
    __tablename__ = "report_item_block"
    item_id: Mapped[int] = mapped_column(ForeignKey("report_item.id"), primary_key=True)
    block_id: Mapped[str] = mapped_column(ForeignKey("block.id"), primary_key=True)
    order_no: Mapped[int] = mapped_column(Integer, default=0)


class MeetingComment(Base):
    """회의 기록 한 줄 — 코멘트 또는 결정(M12). 이슈 이력(block_history)에도 같은 줄을 남긴다."""
    __tablename__ = "meeting_comment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meeting.id"), index=True)
    block_id: Mapped[str] = mapped_column(ForeignKey("block.id"))
    text: Mapped[str] = mapped_column(Text)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"))
    kind: Mapped[str] = mapped_column(String(8), default="comment")     # comment 코멘트 / decision 결정(결정 필요 칸을 비운다)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=_now)


class Directive(Base):
    """지시사항(M12, F20) — 회의 중 지시(내용·담당 부서·기한). 다음 주 그 부서 회의자료 맨 위에 나오고, 한 줄 보고로 완료한다."""
    __tablename__ = "directive"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meeting.id"), index=True)
    block_id: Mapped[str | None] = mapped_column(ForeignKey("block.id"))        # 이슈에 걸린 지시면
    dept_id: Mapped[str] = mapped_column(ForeignKey("department.id"))
    text: Mapped[str] = mapped_column(Text)
    due_week_id: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(4), default="열림")              # 열림 / 완료
    done_note: Mapped[str] = mapped_column(Text, default="")
    done_week_id: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class MeetingCandidate(Base):
    """회의록 추출 결과."""
    __tablename__ = "meeting_candidate"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    meeting_id: Mapped[int] = mapped_column(ForeignKey("meeting.id"), index=True)
    raw_text: Mapped[str] = mapped_column(Text)
    suggested_title: Mapped[str] = mapped_column(String(256), default="")
    suggested_department_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"))
    linked_block_id: Mapped[str | None] = mapped_column(ForeignKey("block.id"))
    state: Mapped[str] = mapped_column(String(8), default="제안")   # 제안 / 등록 / 연결 / 버림


# ── 지식 ────────────────────────────────────────────────
class CaseCard(Base):
    """종결 승인 시 생성되는 지식 단위."""
    __tablename__ = "case_card"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)   # CASE-0311
    block_id: Mapped[str] = mapped_column(ForeignKey("block.id"), unique=True)
    symptom_text: Mapped[str] = mapped_column(Text)
    cause_text: Mapped[str] = mapped_column(Text)
    action_text: Mapped[str] = mapped_column(Text)
    symptom_code_id: Mapped[str | None] = mapped_column(ForeignKey("symptom_code.id"))
    cause_code_id: Mapped[str | None] = mapped_column(ForeignKey("cause_code.id"))
    installed_equipment_id: Mapped[str | None] = mapped_column(ForeignKey("installed_equipment.id"))
    approved_week_id: Mapped[str] = mapped_column(ForeignKey("week.id"))
    validity: Mapped[str] = mapped_column(String(8), default="유효")   # 유효 / 보완필요
    view_count: Mapped[int] = mapped_column(Integer, default=0)


class BlockLink(Base):
    __tablename__ = "block_link"
    from_block_id: Mapped[str] = mapped_column(ForeignKey("block.id"), primary_key=True)
    to_block_id: Mapped[str] = mapped_column(ForeignKey("block.id"), primary_key=True)
    relation: Mapped[str] = mapped_column(String(8), primary_key=True)   # 재발 / 동일원인 / 관련 / 참고


# ── 운영 로그 ───────────────────────────────────────────
class LlmCallLog(Base):
    __tablename__ = "llm_call_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ImportJob(Base):
    """외부 자료 가져오기 한 건(M13, F14·F22) — 올린 PPT·HTML 또는 메일함에서 읽은 메일 한 통. 원본은 imports/<id>/ 에 그대로."""
    __tablename__ = "import_job"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))                        # pptx / html / pdf / xlsx / mail
    title: Mapped[str] = mapped_column(String(256), default="")         # 파일 이름 또는 메일 제목
    file_key: Mapped[str] = mapped_column(String(256), default="")      # imports/ 아래 원본 상대 경로
    sha256: Mapped[str] = mapped_column(String(64), default="")
    source_id: Mapped[str] = mapped_column(String(256), default="")     # 메일 Message-ID(같은 메일 두 번 안 가져오게)
    received_at: Mapped[str] = mapped_column(String(16), default="")    # 메일 받은 때(발신자는 저장하지 않는다 — 최소수집)
    week_id: Mapped[str] = mapped_column(String(8))
    dept_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"))   # 새 이슈의 담당 부서(기본)
    status: Mapped[str] = mapped_column(String(8), default="판정 중")    # 판정 중 / 반영함
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ImportPiece(Base):
    """가져온 자료의 조각 — PPT 한 장·HTML 한 절·메일 본문·첨부. 사람이 판정(붙이기·새 이슈·건너뛰기)하고 「반영하기」로 원장에 넣는다."""
    __tablename__ = "import_piece"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("import_job.id"), index=True)
    no: Mapped[int] = mapped_column(Integer)                             # 장·절 번호(1부터)
    kind: Mapped[str] = mapped_column(String(8))                         # slide / section / mail
    title: Mapped[str] = mapped_column(String(256), default="")
    text: Mapped[str] = mapped_column(Text, default="")                  # 뽑은 글(원본 그대로, 메신저 머리줄만 걷음)
    images_json: Mapped[str] = mapped_column(Text, default="[]")         # 조각에 든 그림(imports/ 아래 상대 경로)
    candidates_json: Mapped[str] = mapped_column(Text, default="[]")     # 연결 후보 [{id, title, score, why}]
    decision: Mapped[str] = mapped_column(String(8), default="")         # "" 미판정 / link / new / skip
    block_id: Mapped[str | None] = mapped_column(ForeignKey("block.id"))   # link 대상
    line: Mapped[str] = mapped_column(Text, default="")                  # link 때 이번 주 한 줄(고칠 수 있음)
    dept_id: Mapped[str | None] = mapped_column(ForeignKey("department.id"))   # new 때 담당 부서
    applied: Mapped[bool] = mapped_column(Boolean, default=False)
    result_block_id: Mapped[str | None] = mapped_column(String(24))      # 반영 결과 이슈


class AppSetting(Base):
    """화면에서 바꾸는 업무 설정(키 → 값). 예: alert_days:ST = 14 (F21 이벤트별 경보 일수)."""
    __tablename__ = "app_setting"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class MetricTable(Base):
    """기간 표(F16) — 특근 인원처럼 행 × 날짜 × 계획/실적. 행 이름은 표마다 자유(1과·2과, 호선, 작업조…)."""
    __tablename__ = "metric_table"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    department_id: Mapped[str] = mapped_column(ForeignKey("department.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(16), default="")
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    rows_json: Mapped[str] = mapped_column(Text, default="[]")         # 행 이름 목록
    notes_json: Mapped[str] = mapped_column(Text, default="{}")        # 행 → 차이 사유
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class MetricCell(Base):
    """기간 표 한 칸 — (행, 날짜) 의 계획·실적."""
    __tablename__ = "metric_cell"
    __table_args__ = (UniqueConstraint("table_id", "row", "day", name="uq_metric_cell"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    table_id: Mapped[int] = mapped_column(ForeignKey("metric_table.id"), index=True)
    row: Mapped[str] = mapped_column(String(64))
    day: Mapped[date] = mapped_column(Date)
    plan: Mapped[float | None] = mapped_column(Float)
    actual: Mapped[float | None] = mapped_column(Float)
