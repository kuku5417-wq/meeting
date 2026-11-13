"""app/db.py — SQLAlchemy 엔진·세션·Base.

DB 는 SQLite 단일 파일이고 위치만 망에 따라 바뀐다(`path_config.db_path`).
테이블 생성은 `init_db()` 의 `create_all` — 기존 테이블은 건드리지 않는다(비파괴).
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app import settings


class Base(DeclarativeBase):
    pass


def _make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        eng = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(eng, "connect")
        def _fk_on(dbapi_conn, _rec):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys = ON")
            # 결정 ①(2026-11-13): NAS(SMB) 위 SQLite 하나를 여러 PC 가 쓴다 — WAL 은 네트워크 드라이브에서 깨지므로
            # 롤백 저널(DELETE)로 고정하고, 다른 PC 가 쓰는 중이면 잠깐 기다린다. 쓰기 순서는 앱 잠금 파일이 맡는다(4-b).
            cur.execute("PRAGMA journal_mode = DELETE")
            cur.execute(f"PRAGMA busy_timeout = {settings.DB_BUSY_TIMEOUT_MS}")
            cur.close()

        return eng
    return create_engine(url)


engine = _make_engine(settings.database_url())
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def lock_path():
    import path_config as pc
    return pc.get_data_dir() / "meeting.lock"


if settings.DB_LOCK and settings.database_url().startswith("sqlite"):
    from app.services import nas_lock as _nas_lock
    _nas_lock.install(SessionLocal, lock_path)      # 결정 ① 4-b — 쓰기 트랜잭션은 NAS 잠금 파일을 잡고


def init_db() -> None:
    """모든 모델 테이블 생성(없는 것만)."""
    from app import models  # noqa: F401  — 모델 등록 부수효과

    Base.metadata.create_all(engine)
    _add_missing_columns()


# create_all 은 이미 있는 표에 열을 더하지 않는다 — 나중에 생긴 열은 여기서 비파괴로 보강한다(SQLite 전용)
_LATER_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("memo", "revises_id", "VARCHAR(24) REFERENCES memo(id)"),     # 2026-10-21 원문 수정본
    ("photo_link", "caption", "VARCHAR(80) NOT NULL DEFAULT ''"),  # 2026-10-21 사진 이름
    ("photo_link", "note", "TEXT NOT NULL DEFAULT ''"),            # 2026-10-21 사진 설명
    ("block_tag", "dismissed", "BOOLEAN NOT NULL DEFAULT 0"),      # 2026-10-21 사람이 뺀 태그
    ("hull", "title", "VARCHAR(128)"),                             # 2026-10-21 pjtlist 동기화
    ("hull", "dock", "VARCHAR(32)"),
    ("hull", "ship_class", "VARCHAR(32)"),
    ("hull", "source", "VARCHAR(16)"),
    ("block", "draft_state", "VARCHAR(8) NOT NULL DEFAULT 'none'"),   # 2026-10-23 M9 이슈 원장
    ("block", "cause_text", "TEXT NOT NULL DEFAULT ''"),
    ("block", "action_text", "TEXT NOT NULL DEFAULT ''"),
    ("block", "decision_needed", "TEXT NOT NULL DEFAULT ''"),
    ("block", "important", "BOOLEAN NOT NULL DEFAULT 0"),
    ("meeting", "kind", "VARCHAR(8) NOT NULL DEFAULT 'share'"),          # 2026-10-23 M10 회의마다 따로
    ("meeting", "title", "VARCHAR(128) NOT NULL DEFAULT ''"),
    ("meeting", "owner_dept_id", "VARCHAR(16)"),
    ("meeting", "held_on", "DATE"),
    ("meeting", "status", "VARCHAR(8) NOT NULL DEFAULT '구성 중'"),
    ("meeting", "start_mode", "VARCHAR(8)"),
    ("meeting", "version", "INTEGER NOT NULL DEFAULT 0"),
    ("meeting", "hull_id", "VARCHAR(16)"),
    ("meeting", "order_json", "TEXT NOT NULL DEFAULT ''"),               # 2026-10-23 M11 공유회 부서 순서
    ("report_item", "dept_id", "VARCHAR(16)"),                           # M11 공유회 부서 칸
    ("meeting_comment", "kind", "VARCHAR(8) NOT NULL DEFAULT 'comment'"), # 2026-10-23 M12 코멘트 / 결정
    ("meeting_comment", "created_at", "DATETIME"),
    ("block", "due_event", "VARCHAR(8) NOT NULL DEFAULT ''"),           # 2026-10-23 F21 일정 경보
    ("block", "due_date", "DATE"),
    ("block", "alert_days", "INTEGER"),
    ("block", "alert_off_reason", "TEXT NOT NULL DEFAULT ''"),
    ("block", "alert_off_at", "DATETIME"),
    ("block", "alert_off_date", "DATE"),
    ("metric_def", "hidden", "BOOLEAN NOT NULL DEFAULT 0"),            # F16 숨기기
    ("metric_value", "human", "BOOLEAN NOT NULL DEFAULT 0"),           # F16 사람 값(블록 없이 넣어도 AI 가 덮지 않게)
    ("report_item", "table_id", "INTEGER REFERENCES metric_table(id)"),  # 2026-10-29 기간 표 단독 장
)


def _add_missing_columns(eng: Engine | None = None) -> None:
    eng = eng or engine
    if eng.dialect.name != "sqlite":
        return
    from sqlalchemy import text
    with eng.begin() as conn:
        for table, col, ddl in _LATER_COLUMNS:
            have = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))}
            if have and col not in have:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))


def get_session() -> Iterator[Session]:
    """FastAPI 의존성 — 요청당 세션 1개."""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
