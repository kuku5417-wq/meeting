"""modules/nas.py — 전환 지점: NAS 접속. **지금은 뼈대다**(계획 단계 2-b).

shi 규약: NAS 접속은 이 파일 밖에 쓰지 않는다. 사외망에서는 아무것도 하지 않고,
사내망에서만 도메인 로그인 → 실패 시 아이디·비번 입력 → Windows API(`WNetAddConnection2`) 로 붙는다.
비밀번호는 **저장하지 않고 명령줄에도 넣지 않는다**(`net use` 를 쓰지 않는 이유). 재시도는 3회까지.

지금 들어 있는 것(단계 2-b)
  - 창구 두 개(`is_configured`·`ensure_connected`)와 「사외망이면 무동작」 규칙
  - 사내망에서 경로가 보이는지까지만 확인 — 접속을 **시도하지 않는다**

단계 5 에서 채울 것
  - `_connect(user, password)` — `WNetAddConnection2`(mpr.dll), 3회, 실패 사유를 한국어로
  - 아이디·비번 입력 화면(설정 화면 또는 시작 시 1회)
  - 접속 실패 시 **쓰기 차단** — `services/db_guard.py`·`services/nas_lock.py` 가 이 함수를 보고 막는다
    (지금은 `config/paths.py` 가 NAS 가 안 보이면 로컬로 폴백한다 — 사내망에서 그러면 안 되므로 단계 5 에서 함께 고친다)
"""
from __future__ import annotations

from pathlib import Path

from config import settings as cfg

MAX_RETRY = 3          # 아이디·비번 재시도 한도 (단계 5)


def is_configured() -> bool:
    """`.env` 에 `NAS_BASE_PATH` 가 있나 — 값은 돌려주지 않는다."""
    return bool(cfg.secret("NAS_BASE_PATH"))


def base_path() -> Path | None:
    """NAS base 경로 (사내망이고 설정이 있을 때만). 존재 여부는 보지 않는다."""
    if not cfg.is_internal():
        return None
    nas = cfg.secret("NAS_BASE_PATH")
    return Path(nas) if nas else None


def is_available() -> bool:
    """지금 NAS 경로가 보이나(접속 시도 없음)."""
    p = base_path()
    if p is None:
        return False
    try:
        return p.exists()
    except Exception:  # noqa: BLE001 — UNC 접근 불가 → 아직 연결되지 않은 것으로 본다
        return False


def ensure_connected() -> tuple[bool, str]:
    """(붙었나, 사람에게 보여 줄 한 줄).

    사외망에서는 **아무것도 하지 않고** True — 데이터는 형제 폴더에 둔다.
    """
    if not cfg.is_internal():
        return True, "사외망 — NAS 를 쓰지 않습니다"
    if not is_configured():
        return False, "NAS 위치가 설정되지 않았습니다 — secret/.env 의 NAS_BASE_PATH 를 채워 주세요"
    if is_available():
        return True, "NAS 에 연결되어 있습니다"
    return False, "NAS 에 연결되지 않았습니다 — 접속(도메인 로그인·아이디 입력)은 아직 준비 중입니다(단계 5)"
