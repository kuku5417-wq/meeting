"""pytest 공통 (결정 ②, 2026-11-13) — _smoke.py 검사를 영역별 파일로 나눠 돌린다.

- 환경 주입(임시 데이터 폴더·오늘 날짜 고정·Outlook 끔·LLM 키 비움)은 `_smoke.py` 맨 위에서 한다.
  그래서 여기서 **app 보다 먼저** `_smoke` 를 import 한다.
- 앱 클라이언트는 세션 하나(`client`) — 앞 파일이 만든 데이터를 뒤 파일이 쓴다. 파일 이름 번호(test_00…test_99) 순서로 돈다.
- 검사 함수는 지금 `_smoke.py` 에 그대로 있고(정본), 파일은 묶음을 부르기만 한다. `uv run python _smoke.py` 도 같은 검사를 돈다.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import _smoke as sm  # noqa: E402 — 환경 주입(app import 전)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:      # lifespan(init_db) 실행
        yield c


@pytest.fixture(scope="session")
def run():
    """묶음 하나를 돌리고, 그 묶음에서 FAIL 난 검사 이름을 모두 보여 준다."""
    def _run(fn, *args):
        start = len(sm._results)
        fn(*args)
        failed = [name for ok, name in sm._results[start:] if not ok]
        assert not failed, "FAIL 검사:\n- " + "\n- ".join(failed)
    return _run
