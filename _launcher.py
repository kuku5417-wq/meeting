"""_launcher.py — 실행 파일(PyInstaller)의 진입점 (단계 11, 2026-11-24).

`run.bat` 이 하는 일을 파이썬 하나로 한다: **빈 포트 찾기 → 127.0.0.1 로 서버 올리기 → 브라우저 열기.**
파이썬·uv 가 깔리지 않은 PC 에 폴더 하나로 넘기기 위한 것이다(`/shi:package` 대상).

규칙
  - 서버는 **127.0.0.1 에서만** 연다. `--host` 를 받지 않는다(남이 접속하는 서버 금지).
  - 콘솔 출력은 `app.main._safe_console` 과 같은 이유로 ASCII 로만 쓴다 — 실행 파일 창은 CP949 다.
  - 데이터 위치·망·NAS 는 평소와 같다(`config/`·`modules/`). 실행 파일이라고 다르게 굴지 않는다.
"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser
from pathlib import Path


def _base_dir() -> Path:
    """실행 파일 안에서는 _MEIPASS, 소스에서는 이 파일 폴더."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def main() -> int:
    root = _base_dir()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    os.chdir(root)

    from _freeport import find
    port = find()
    if not port:
        print("[FAIL] no free port in 8600-8610. Close other copies and try again.")
        input("Press Enter to close...")
        return 1

    url = f"http://127.0.0.1:{port}"
    print(f"meeting - open: {url}")
    print("stop: close this window or press Ctrl+C")
    threading.Timer(3.0, lambda: webbrowser.open(url)).start()

    import uvicorn

    from app.main import app as fastapi_app   # 문자열("app.main:app")로 주면 실행 파일 안에서 import 가 실패한다
    uvicorn.run(fastapi_app, host="127.0.0.1", port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
