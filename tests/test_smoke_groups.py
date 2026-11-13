"""_smoke.py 묶음을 pytest 테스트로 (결정 ② 1-a, 2026-11-13).

묶음 순서가 중요하다 — 앞 묶음이 만든 데이터를 뒤 묶음이 쓴다. pytest 는 파일 안 순서대로 돈다.
실패하면 그 묶음에서 FAIL 난 검사 이름을 모두 보여 준다. 마지막 테스트가 검사 개수(_smoke 와 같은 수)를 확인한다.
"""
import _smoke as sm   # ← 환경 주입이 여기서 일어난다(app import 전)

EXPECTED_MIN_CHECKS = 432   # 2026-11-13 _smoke 통과 개수. 검사를 더하면 같이 올린다


def _run(fn):
    start = len(sm._results)
    fn()
    failed = [name for ok, name in sm._results[start:] if not ok]
    assert not failed, "FAIL 검사:\n- " + "\n- ".join(failed)


def test_paths():
    _run(sm.t_paths)


def test_tokens():
    _run(sm.t_tokens)


def test_weeks():
    _run(sm.t_weeks)


def test_sn():
    _run(sm.t_sn)


def test_app_all_groups():
    """t_app — 기준정보 시드부터 M9~M13·F16·F21·결정⑦까지 한 클라이언트로 이어서 돈다(1-b 에서 쪼갠다)."""
    _run(sm.t_app)


def test_check_count():
    n = len(sm._results)
    assert n >= EXPECTED_MIN_CHECKS, f"검사 수 {n} < {EXPECTED_MIN_CHECKS} — 빠진 묶음이 있다"
