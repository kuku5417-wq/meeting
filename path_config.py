"""path_config.py — meeting(주간 회의자료·지식화) 경로 관리.

이 앱의 데이터(SQLite DB·사진 원본·내보낸 PPT)는 중앙 parquet 폴더를 오염시키지 않도록
별도 디렉토리 `<base>/meeting` 에 둔다. 이 앱은 parquet 을 생산하지 않는다
(공통규칙 2: 단일 생산자 = data_manager_F). 중앙 parquet 은 pjtlist·milestone 만 **읽는다**(2026-10-21, `central_parquet`).

data_manager 와 동일한 secret/.env 를 재사용해 NAS(사내망)/로컬(사외망) 자동 전환.
**경로 리터럴은 이 파일에만 둔다**(공통규칙 1: 경로 하드코딩 금지).
시그니처는 shi-app-env §5 규약(`_nas_base`·`is_internal`·`get_env_label`·`invalidate_cache`)을 따른다.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent      # meeting/
CODE_DIR = BASE_DIR.parent                      # code_N/
DATA_LOCAL = CODE_DIR / "data"                  # code_N/data (폴백 base)

DATA_SUBDIR = "meeting"
DB_NAME = "meeting.db"


def _find_secret_env() -> Path:
    """secret/.env 위치를 포터블하게 탐색 (app_config._find_env_file 과 동일 규칙).

    우선순위: 환경변수 SHI_ENV_FILE → 이 파일 위치에서 위로 올라가며 첫 secret/.env
    → 기본값(CODE_DIR/secret/.env, 없어도 무해).
    """
    ov = os.getenv("SHI_ENV_FILE")
    if ov and Path(ov).exists():
        return Path(ov)
    for d in (BASE_DIR, *BASE_DIR.parents):
        cand = d / "secret" / ".env"
        if cand.exists():
            return cand
    return CODE_DIR / "secret" / ".env"


SECRET_ENV = _find_secret_env()


def read_secret(key: str) -> str:
    """secret/.env 에서 KEY= 값 읽기 (없으면 빈 문자열). 값은 로그·화면에 노출 금지."""
    try:
        if not SECRET_ENV.exists():
            return ""
        text = SECRET_ENV.read_text(encoding="utf-8-sig")   # 메모장 저장본의 BOM 대비
        m = re.search(rf"^{re.escape(key)}[ \t]*=[ \t]*([^\n]*)$", text, re.MULTILINE)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    except Exception:  # noqa: BLE001 — .env 없음/깨짐 → 미설정으로 본다
        pass
    return ""


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
    """NAS base 경로 (사내망이고 실제 접근 가능할 때만)."""
    nas = read_secret("NAS_BASE_PATH")
    if not nas:
        return None
    p = Path(nas)
    try:
        if p.exists():
            return p
    except Exception:  # noqa: BLE001 — UNC 접근 불가 → 사외망으로 본다
        pass
    return None


def is_internal() -> bool:
    return _nas_base() is not None


def _local_base() -> Path:
    base = read_secret("DATA_PATH")
    return Path(base) if base else DATA_LOCAL


def get_central_parquet_dir() -> Path:
    """중앙 parquet 폴더 — pjtlist·milestone 을 **읽기만** 한다(쓰지 않음).

    우선순위(pjtcost 와 같은 규칙): 환경변수 MEETING_CENTRAL_PARQUET(개발·시험용) → .env 같은 키
    → NAS(`NAS_PARQUET_PATH` 또는 `NAS_BASE_PATH/parquet`) → `<DATA_PATH 또는 code_N/data>/parquet`.
    """
    ov = os.getenv("MEETING_CENTRAL_PARQUET", "") or read_secret("MEETING_CENTRAL_PARQUET")
    if ov:
        return Path(ov)
    nas = _nas_base()
    if nas:
        p = read_secret("NAS_PARQUET_PATH")
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
    return p if p.is_absolute() else (SECRET_ENV.parent / p)


def data_dir_choice() -> tuple[Path, str]:
    """(데이터 폴더, 어느 규칙으로 정해졌는지) — check_env·서버 시작 로그가 함께 쓴다."""
    env = os.getenv("MEETING_DATA_PATH", "")
    sec = read_secret("MEETING_DATA_PATH")
    # app_config 가 .env 를 환경변수로 올리므로, 값이 .env 와 같으면 .env 에서 온 것으로 표시한다
    if env and env.strip() != sec:
        return _expand(env), "환경변수 MEETING_DATA_PATH"
    if sec:
        return _expand(sec), ".env MEETING_DATA_PATH"
    nas = _nas_base()
    if nas:
        return nas / DATA_SUBDIR, "NAS_BASE_PATH/meeting (사내망 기본)"
    if read_secret("DATA_PATH"):
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
    return "사내망" if is_internal() else "사외망"


def invalidate_cache() -> None:
    """경로 캐시 무효화 (NAS 재연결 시 사용)."""
    _nas_base.cache_clear()
    _ensured.clear()
