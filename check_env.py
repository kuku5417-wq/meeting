"""check_env.py — 가동 전 환경 점검 (doctor).

실행: python check_env.py            전체 점검
      python check_env.py --quick    쓰기 프로브·네트워크 생략

섹션 순서는 전 앱 공통이다: Python/venv → 패키지 → 시크릿/경로 → 데이터 → 프록시/네트워크.
**시크릿 값은 절대 출력하지 않는다** — `_mask()` 로 "설정됨 / 미설정" 만 찍는다.
FAIL 이 하나라도 있으면 종료코드 1.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")      # 콘솔 CP949 에서 한글 깨짐 방지
except Exception:  # noqa: BLE001 — 구버전 파이썬/리다이렉트 환경
    pass

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

_fail = 0
_warn = 0


def _head(t: str) -> None:
    print("\n" + "=" * 64 + f"\n{t}\n" + "=" * 64)


def ok(m: str) -> None:
    print(f"[PASS] {m}")


def info(m: str) -> None:
    print(f"[INFO] {m}")


def warn(m: str, hint: str = "") -> None:
    global _warn
    _warn += 1
    print(f"[WARN] {m}")
    if hint:
        print(f"       -> {hint}")


def fail(m: str, hint: str = "") -> None:
    global _fail
    _fail += 1
    print(f"[FAIL] {m}")
    if hint:
        print(f"       -> {hint}")


def _mask(v: str | None) -> str:
    """값을 절대 노출하지 않는다."""
    return "설정됨" if (v or "").strip() else "미설정"


def main() -> int:
    quick = "--quick" in sys.argv

    # ── 1. Python / venv ────────────────────────────────
    _head("1. Python / venv")
    v = sys.version_info
    bits = struct.calcsize("P") * 8
    if (v.major, v.minor) == (3, 12):
        ok(f"Python {v.major}.{v.minor}.{v.micro}")
    else:
        fail(f"Python {v.major}.{v.minor} — 3.12 가 필요합니다",
             "64비트 Python 3.12 를 설치하고 setup_env.bat 을 다시 실행하세요.")
    if bits == 64:
        ok("64비트 인터프리터")
    else:
        fail("32비트 인터프리터입니다", "C 확장 휠이 없어 소스빌드로 넘어가 MSVC 없이 실패합니다.")
    exe = Path(sys.executable).resolve()
    info(f"실행 파일: {exe}")
    if str(exe).startswith("\\\\") or str(exe).startswith("//"):
        fail("venv 가 UNC(네트워크) 경로에 있습니다",
             r"%LOCALAPPDATA%\venvs\meeting 처럼 로컬 C: 에 만드세요.")
    elif "venvs" in str(exe) or ".venv" in str(exe):
        ok("venv 가 로컬 디스크에 있습니다")
    else:
        warn("venv 밖의 파이썬으로 보입니다", "setup_env.bat 으로 만든 venv 를 쓰세요.")

    # ── 2. 패키지 ───────────────────────────────────────
    _head("2. 패키지")
    for mod, why in (("fastapi", ""), ("uvicorn", "서버 실행"), ("sqlalchemy", "DB"),
                     ("jinja2", "화면 템플릿"), ("dotenv", "app_config 의 .env 로드"),
                     ("httpx", "_smoke.py TestClient")):
        try:
            __import__(mod)
            ok(mod + (f" — {why}" if why else ""))
        except Exception as e:  # noqa: BLE001
            fail(f"{mod} 없음 ({e})", "uv sync --locked 를 실행하세요.")

    # ── 3. 시크릿 / 경로 ────────────────────────────────
    _head("3. 시크릿 / 경로")
    try:
        import path_config as pc
    except Exception as e:  # noqa: BLE001
        fail(f"path_config 를 불러오지 못했습니다 ({e})")
        return 1
    info(f"secret/.env: {pc.SECRET_ENV} -> {_mask('x' if pc.SECRET_ENV.exists() else '')}")
    info(f"환경: {pc.get_env_label()}")
    info(f"NAS_BASE_PATH: {_mask(pc.read_secret('NAS_BASE_PATH'))}"
         f" · DATA_PATH: {_mask(pc.read_secret('DATA_PATH'))}"
         f" · MEETING_DATA_PATH: {_mask(pc.read_secret('MEETING_DATA_PATH'))}")
    d = pc.get_data_dir()
    _, source = pc.data_dir_choice()
    if d.exists():
        ok(f"데이터 폴더: {d}  ({source})")
    else:
        fail(f"데이터 폴더를 만들지 못했습니다: {d}  ({source})",
             "드라이브·폴더 이름과 쓰기 권한을 확인하세요. 위치는 secret/.env 의 MEETING_DATA_PATH 로 정합니다.")
    if pc.read_secret("MEETING_DATA_PATH") and pc.is_network_path(d):
        warn("MEETING_DATA_PATH 가 네트워크 경로입니다 — SQLite 는 로컬 디스크에 두는 것이 안전합니다",
             "예: MEETING_DATA_PATH=D:\\meeting_data (운영 PC 로컬). 다른 PC 는 브라우저로 접속합니다.")

    # ── 4. 데이터(DB) ───────────────────────────────────
    _head("4. 데이터")
    try:
        from sqlalchemy import inspect

        from app.db import engine, init_db
        init_db()
        n = len(inspect(engine).get_table_names())
        ok(f"DB 연결·테이블 생성 확인 ({n}개 테이블) — {pc.db_path().name}")
    except Exception as e:  # noqa: BLE001
        fail(f"DB 를 열지 못했습니다 ({e})", "데이터 폴더 권한을 확인하세요.")

    # ── 5. 쓰기 권한 ────────────────────────────────────
    if quick:
        _head("5. 쓰기 권한 — 생략 (--quick)")
    else:
        _head("5. 쓰기 권한")
        try:
            probe = pc.get_photo_dir() / ".probe.tmp"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            ok("사진 폴더에 쓸 수 있습니다")
        except Exception as e:  # noqa: BLE001
            fail(f"사진 폴더에 쓸 수 없습니다 ({e})", "폴더 권한 또는 NAS 연결을 확인하세요.")

    # ── 6. 프록시 / 네트워크 ────────────────────────────
    if quick:
        _head("6. 프록시 / 네트워크 — 생략 (--quick)")
    else:
        _head("6. 프록시 / 네트워크")
        try:
            import app_config as ac
            info(f"환경: {ac.ENV_LABEL} · VDI: {ac.IS_VDI}")
            info(f"HTTP_PROXY: {_mask(os.getenv('HTTP_PROXY') or ac.HTTP_PROXY or '')}"
                 f" · 프록시 사용: {ac.USE_PROXY} · SSL 검증: {ac.SSL_VERIFY}")
            ok("app_config 로드 성공 (LLM 은 아직 mock — 외부 호출 없음)")
        except Exception as e:  # noqa: BLE001
            warn(f"app_config 를 불러오지 못했습니다 ({e})")

    print("\n" + "-" * 64)
    if _fail:
        print(f"[FAIL] {_fail}건 · [WARN] {_warn}건 — 위 [FAIL] 항목을 먼저 해결하세요.")
        return 1
    print(f"[PASS] 모든 필수 항목 통과 · [WARN] {_warn}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
