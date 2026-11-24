"""config/paths.py — 전환 지점: 저장 위치 (meeting 주간 회의자료·지식화).

shi 규약(전환 지점 네 곳)의 첫 번째. **경로 리터럴은 이 파일에만 둔다**(공통지침 1: 경로 하드코딩 금지).
옛 이름 `path_config.py` 는 이 파일을 부르는 얇은 래퍼로 남아 있다(import 13곳을 한꺼번에 고치지 않기 위해 —
래퍼 제거는 계획 단계 11).

이 앱의 데이터(SQLite DB·사진 원본·내보낸 PPT)는 중앙 parquet 폴더를 오염시키지 않도록 `<base>/meeting` 에 둔다.
이 앱은 parquet 을 **생산하지 않는다**(공통규칙 2: 단일 생산자 = data_manager_F). 중앙 parquet 은
`pjtlist`·`milestone` 만 **읽는다**(2026-10-21, `app/services/central.py`).

결정 ⑤(2026-11-13) — **경로 존재로 망을 판정하지 않는다.** 사내망/사외망은 `config.settings.net()`
(`.claude/shi.json` 의 `net`) 하나로 정하고, NAS 는 사내망일 때만 쓴다.
비밀(.env) 읽기는 `config.settings` 가 맡는다.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from config import settings as cfg

BASE_DIR = cfg.ROOT                             # meeting/
CODE_DIR = BASE_DIR.parent                      # code_N/
DATA_LOCAL = CODE_DIR / "data"                  # code_N/data (폴백 base)

DATA_SUBDIR = "meeting"
DB_NAME = "meeting.db"

_ensured: set[Path] = set()


def _ensure(d: Path) -> Path:
    """디렉토리 생성 (프로세스당 1회만 시도)."""
    if d not in _ensured:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001 — 권한/NAS 미가용 → 실제 저장 시점에 표면화
            pass
        _ensured.add(d)
    return d


@lru_cache(maxsize=1)
def _nas_base() -> Path | None:
    """NAS base 경로 — **사내망일 때만**(결정 ⑤: 경로 존재로 망을 추론하지 않는다).

    사내망인데 아직 접속이 안 돼 경로가 보이지 않으면 None 을 돌려준다. 그때 쓰기를 막는 일은
    `modules/nas.py`(계획 단계 5)가 맡는다 — 지금은 로컬로 폴백한다.
    """
    if not cfg.is_internal():
        return None
    nas = cfg.secret("NAS_BASE_PATH")
    if not nas:
        return None
    p = Path(nas)
    try:
        if p.exists():
            return p
    except Exception:  # noqa: BLE001 — UNC 접근 불가 → 아직 연결되지 않은 것으로 본다
        pass
    return None


def is_internal() -> bool:
    """사내망인가 — `.claude/shi.json` 의 `net` 하나로 정한다(자동 감지 없음)."""
    return cfg.is_internal()


def _local_base() -> Path:
    base = cfg.secret("DATA_PATH")
    return Path(base) if base else DATA_LOCAL


def get_central_parquet_dir() -> Path:
    """중앙 parquet 폴더 — pjtlist·milestone 을 **읽기만** 한다(쓰지 않음).

    우선순위(pjtcost 와 같은 규칙): 환경변수 MEETING_CENTRAL_PARQUET(개발·시험용) → .env 같은 키
    → NAS(`NAS_PARQUET_PATH` 또는 `NAS_BASE_PATH/parquet`) → `<DATA_PATH 또는 code_N/data>/parquet`.
    """
    ov = os.getenv("MEETING_CENTRAL_PARQUET", "") or cfg.secret("MEETING_CENTRAL_PARQUET")
    if ov:
        return Path(ov)
    nas = _nas_base()
    if nas:
        p = cfg.secret("NAS_PARQUET_PATH")
        return Path(p) if p else (nas / "parquet")
    return _local_base() / "parquet"


def central_parquet(name: str) -> Path:
    return get_central_parquet_dir() / f"{name}.parquet"


def get_data_dir() -> Path:
    """앱 데이터 루트 (DB·사진·내보내기).

    우선순위: 환경변수 MEETING_DATA_PATH → .env MEETING_DATA_PATH → <NAS or DATA_PATH>/meeting
    → code_N/data/meeting.
    환경변수를 .env 보다 먼저 보는 이유: `_smoke.py` 가 임시폴더를 주입해 실 DB 를 건드리지 않게 하려고.
    """
    return _ensure(data_dir_choice()[0])


def _expand(raw: str) -> Path:
    """`%LOCALAPPDATA%/meeting`·`~/meeting` 같은 표기를 풀어 준다. 상대경로는 secret 폴더 기준."""
    p = Path(os.path.expanduser(os.path.expandvars(raw.strip())))
    return p if p.is_absolute() else (cfg.SECRET_ENV.parent / p)


def data_dir_choice() -> tuple[Path, str]:
    """(데이터 폴더, 어느 규칙으로 정해졌는지) — check_env·서버 시작 로그가 함께 쓴다."""
    env = os.getenv("MEETING_DATA_PATH", "")
    sec = cfg.secret("MEETING_DATA_PATH")
    if env:                                   # .env 를 환경변수로 올리지 않으므로 이건 진짜 환경변수다(단계 2-c)
        return _expand(env), "환경변수 MEETING_DATA_PATH"
    if sec:
        return _expand(sec), ".env MEETING_DATA_PATH"
    nas = _nas_base()
    if nas:
        return nas / DATA_SUBDIR, "NAS_BASE_PATH/meeting (사내망 기본)"
    if cfg.secret("DATA_PATH"):
        return _local_base() / DATA_SUBDIR, "DATA_PATH/meeting"
    return DATA_LOCAL / DATA_SUBDIR, "기본값 code_N/data/meeting"


def is_network_path(p: Path) -> bool:
    """UNC(서버 공유 경로) 또는 네트워크 드라이브(Z: 등)면 True — SQLite 를 두기엔 위험한 곳."""
    s = str(p)
    if s.startswith(("\\\\", "//")):
        return True
    if os.name == "nt" and len(s) >= 2 and s[1] == ":":
        try:
            import ctypes
            return ctypes.windll.kernel32.GetDriveTypeW(s[:2] + "\\") == 4   # DRIVE_REMOTE
        except Exception:  # noqa: BLE001 — 판정 불가 → 로컬로 본다
            return False
    return False


def db_path() -> Path:
    """SQLite DB 파일."""
    return get_data_dir() / DB_NAME


def get_photo_dir() -> Path:
    """사진 원본 저장소. **원본 불변** — 덮어쓰기·삭제하지 않는다(CLAUDE.md 원칙 1)."""
    return _ensure(get_data_dir() / "photos")


def get_import_dir() -> Path:
    """가져온 외부 자료 원본(PPT·HTML·메일과 첨부). **원본 불변** — 원칙 1."""
    return _ensure(get_data_dir() / "imports")


def get_export_dir() -> Path:
    """내보낸 PPT 저장소."""
    return _ensure(get_data_dir() / "exports")


def get_backup_dir() -> Path:
    """DB 백업(매일 첫 실행, 결정 ①). 데이터 폴더 안 backups/ — 정본 DB 를 덮어쓰지 않는다."""
    return _ensure(get_data_dir() / "backups")


def get_env_label() -> str:
    """현재 환경 레이블 (UI 표시용)."""
    return cfg.env_label()


def invalidate_cache() -> None:
    """경로 캐시 무효화 (NAS 재연결·망 설정 변경 시 사용)."""
    _nas_base.cache_clear()
    _ensured.clear()
