"""modules/nas.py — 전환 지점: NAS 접속 (계획 단계 5, 2026-11-24).

shi 규약: NAS 접속은 이 파일 밖에 쓰지 않는다.
  - 사외망(`net=external`)에서는 **아무것도 하지 않는다** — 데이터는 형제 폴더에 둔다.
  - 사내망에서는 **도메인 로그인 먼저**(지금 로그인한 계정으로 붙여 본다) → 안 되면 아이디·비번을 받아
    Windows API `WNetAddConnection2` 로 붙는다. 재시도는 **3회**까지(앱을 다시 켜면 초기화).
  - 비밀번호는 **저장하지 않고 명령줄에도 넣지 않는다** — `net use` 를 쓰지 않는 이유다.
    받은 값은 API 에 넘긴 뒤 버리고, 로그·DB·화면에 남기지 않는다.
  - 붙지 못하면 **쓰기를 막는다** — 판정은 이 파일이 하고, 막는 일은 `app/main.py` 의 미들웨어가 한다.
    (사내망에서 로컬 폴더로 조용히 쓰는 일이 없어야 한다 — `config/paths.py` 도 폴백하지 않는다)

Windows 가 아니거나 `mpr.dll` 이 없으면 접속을 시도하지 않고 사유만 돌려준다(시험·리눅스 환경).
"""
from __future__ import annotations

import os
from pathlib import Path

from config import settings as cfg

MAX_RETRY = 3                      # 아이디·비번 재시도 한도 (앱을 다시 켜면 0 으로)

# 이 프로세스 동안의 시도 기록 — **비밀번호는 담지 않는다**
_state: dict[str, object] = {"tries": 0, "last_error": "", "connected_as": ""}

RESOURCETYPE_DISK = 0x00000001

# WNetAddConnection2 오류 코드 → 사람이 읽을 한 줄
_ERRORS = {
    5: "접근이 거부되었습니다 — 이 계정에 공유 폴더 권한이 있는지 담당자에게 확인하세요",
    53: "경로를 찾을 수 없습니다 — 서버 이름을 확인하세요(NAS_BASE_PATH)",
    65: "네트워크 접근이 거부되었습니다",
    67: "공유 이름을 찾을 수 없습니다 — NAS_BASE_PATH 의 공유 폴더 이름을 확인하세요",
    86: "비밀번호가 맞지 않습니다",
    1203: "네트워크 경로 형식이 올바르지 않습니다",
    1219: "이미 다른 계정으로 연결되어 있습니다 — 탐색기에서 그 연결을 끊고 다시 시도하세요",
    1326: "아이디 또는 비밀번호가 맞지 않습니다",
    1331: "계정이 사용 중지되었습니다",
    1909: "계정이 잠겼습니다 — 잠시 뒤 다시 시도하거나 담당자에게 문의하세요",
}


def is_configured() -> bool:
    """`NAS_BASE_PATH` 가 설정돼 있나 — 값은 돌려주지 않는다."""
    return bool(cfg.value("NAS_BASE_PATH"))


def base_path() -> Path | None:
    """NAS base 경로 (사내망이고 설정이 있을 때만). 보이는지는 보지 않는다."""
    if not cfg.is_internal():
        return None
    nas = cfg.value("NAS_BASE_PATH")
    return Path(nas) if nas else None


def share_root(p: Path | None = None) -> str:
    r"""연결할 공유 뿌리 — `\\서버\공유`. UNC 가 아니면 빈 문자열."""
    p = p or base_path()
    if p is None:
        return ""
    s = str(p).replace("/", "\\")
    if not s.startswith("\\\\"):
        return ""
    parts = [x for x in s[2:].split("\\") if x]
    if len(parts) < 2:
        return ""
    return "\\\\" + parts[0] + "\\" + parts[1]


def is_available() -> bool:
    """지금 NAS 경로가 보이나 (접속 시도 없음)."""
    p = base_path()
    if p is None:
        return False
    try:
        return p.exists()
    except Exception:  # noqa: BLE001 — UNC 접근 불가 → 아직 연결되지 않은 것으로 본다
        return False


def _wnet_add(remote: str, user: str, password: str) -> int:
    """`WNetAddConnection2` 호출. 0 이면 성공. 드라이브 문자를 쓰지 않고 공유만 연결한다."""
    import ctypes
    from ctypes import wintypes

    class NETRESOURCE(ctypes.Structure):
        _fields_ = [("dwScope", wintypes.DWORD), ("dwType", wintypes.DWORD),
                    ("dwDisplayType", wintypes.DWORD), ("dwUsage", wintypes.DWORD),
                    ("lpLocalName", wintypes.LPWSTR), ("lpRemoteName", wintypes.LPWSTR),
                    ("lpComment", wintypes.LPWSTR), ("lpProvider", wintypes.LPWSTR)]

    mpr = ctypes.WinDLL("mpr", use_last_error=True)
    nr = NETRESOURCE()
    nr.dwType = RESOURCETYPE_DISK
    nr.lpRemoteName = remote
    # 비번·아이디는 여기서만 쓰이고 돌아가면서 사라진다. 빈 값 → 지금 로그인한 계정(도메인 로그인)
    return int(mpr.WNetAddConnection2W(ctypes.byref(nr), password or None, user or None, 0))


def _reason(code: int) -> str:
    return _ERRORS.get(code, f"연결 실패 (Windows 오류 {code})")


def _after_connect(ok: bool, who: str) -> None:
    """경로 캐시를 비운다 — 방금 붙은 폴더를 다시 보게."""
    if ok:
        _state["tries"] = 0
        _state["last_error"] = ""
        _state["connected_as"] = who
        from config import paths as pc
        pc.invalidate_cache()


def connect(user: str, password: str, _connector=None) -> tuple[bool, str]:
    """아이디·비번으로 붙는다. (붙었나, 보여 줄 한 줄).

    `_connector` 는 시험용 — 넣지 않으면 Windows API 를 쓴다.
    비밀번호는 이 함수 밖으로 나가지 않는다(로그·반환값·상태에 담지 않는다).
    """
    if not cfg.is_internal():
        return False, "사외망에서는 NAS 에 연결하지 않습니다"
    if not is_configured():
        return False, "NAS 위치가 설정되지 않았습니다 — secret/.env 의 NAS_BASE_PATH 를 채워 주세요"
    if int(_state["tries"]) >= MAX_RETRY:                                  # type: ignore[arg-type]
        return False, (f"{MAX_RETRY}번 연결에 실패했습니다 — 아이디·비밀번호를 확인한 뒤 "
                       "앱을 다시 켜고 시도하세요")
    remote = share_root()
    if not remote:
        return False, "NAS_BASE_PATH 가 공유 경로(\\\\서버\\공유)가 아닙니다 — secret/.env 를 확인하세요"
    fn = _connector or _wnet_add
    if _connector is None and os.name != "nt":
        return False, "NAS 연결은 Windows 에서만 됩니다"
    _state["tries"] = int(_state["tries"]) + 1                             # type: ignore[arg-type]
    try:
        code = fn(remote, user or "", password or "")
    except Exception as e:  # noqa: BLE001 — mpr.dll 부재·호출 실패도 사유로 돌려준다
        _state["last_error"] = f"호출 실패({type(e).__name__})"
        return False, f"연결을 시도할 수 없습니다({type(e).__name__})"
    if code != 0:
        _state["last_error"] = _reason(code)
        left = MAX_RETRY - int(_state["tries"])                            # type: ignore[arg-type]
        tail = f" (남은 시도 {left}번)" if left > 0 else " — 앱을 다시 켜고 시도하세요"
        return False, _state["last_error"] + tail                          # type: ignore[operator]
    _after_connect(True, user or "도메인 로그인")
    if not is_available():
        return False, "연결은 됐지만 폴더가 보이지 않습니다 — NAS_BASE_PATH 하위 경로를 확인하세요"
    return True, "NAS 에 연결했습니다"


def ensure_connected(_connector=None) -> tuple[bool, str]:
    """(쓸 수 있나, 보여 줄 한 줄). 사외망이면 아무것도 하지 않고 통과.

    사내망에서는 ① 이미 보이면 그대로 ② 아니면 **도메인 로그인**으로 한 번 붙여 보고
    ③ 그래도 안 되면 아이디·비번이 필요하다고 알린다(이 시도는 재시도 횟수에 세지 않는다).
    """
    if not cfg.is_internal():
        return True, "사외망 — NAS 를 쓰지 않습니다"
    if not is_configured():
        return False, "NAS 위치가 설정되지 않았습니다 — secret/.env 의 NAS_BASE_PATH 를 채워 주세요"
    if is_available():
        return True, "NAS 에 연결되어 있습니다"
    remote = share_root()
    if not remote:
        return False, "NAS_BASE_PATH 가 공유 경로(\\\\서버\\공유)가 아닙니다 — secret/.env 를 확인하세요"
    fn = _connector or _wnet_add
    if _connector is None and os.name != "nt":
        return False, "NAS 연결은 Windows 에서만 됩니다"
    try:
        code = fn(remote, "", "")          # 도메인 로그인(지금 계정)
    except Exception as e:  # noqa: BLE001 — 시도 자체가 안 되면 사유만 남긴다
        return False, f"연결을 시도할 수 없습니다({type(e).__name__})"
    if code == 0 and is_available():
        _after_connect(True, "도메인 로그인")
        return True, "NAS 에 연결했습니다 (도메인 로그인)"
    _state["last_error"] = _reason(code) if code else "폴더가 보이지 않습니다"
    return False, ("NAS 에 연결되지 않았습니다 — 설정 화면의 「NAS 연결」에서 아이디·비밀번호를 넣어 주세요"
                   f" ({_state['last_error']})")


def status() -> dict:
    """설정 화면·`check_env.py` 가 쓰는 요약. **값(경로·비번)은 담지 않는다.**"""
    return {
        "net": cfg.net(),
        "internal": cfg.is_internal(),
        "configured": is_configured(),
        "share": share_root(),            # 서버·공유 이름은 비밀이 아니다(경로 전체는 담지 않는다)
        "available": is_available(),
        "tries": int(_state["tries"]),    # type: ignore[arg-type]
        "max_retry": MAX_RETRY,
        "last_error": _state["last_error"],
        "connected_as": _state["connected_as"],
    }


def reset_tries() -> None:
    """재시도 횟수 초기화 — 사람이 아이디를 고쳐 다시 시작할 때."""
    _state["tries"] = 0
    _state["last_error"] = ""
