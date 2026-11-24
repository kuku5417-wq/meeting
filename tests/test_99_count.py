"""검사 수 확인 — _smoke.py 와 같은 수를 돌았는지(빠진 묶음이 없는지)."""
import _smoke as sm

EXPECTED_MIN_CHECKS = 540   # 2026-11-24 단계 2(13)+5(11)+11(7)+⑦15-2(12)+15-3(11)+15-4(14)+15-5(16) → 456 → 540


def test_check_count():
    n = len(sm._results)
    assert n >= EXPECTED_MIN_CHECKS, f"검사 수 {n} < {EXPECTED_MIN_CHECKS} — 빠진 묶음이 있다"


def test_all_groups_have_a_file():
    """_smoke.GROUPS 의 묶음이 모두 tests/ 어딘가에서 불린다."""
    from pathlib import Path
    text = "".join(p.read_text(encoding="utf-8") for p in Path(__file__).parent.glob("test_*.py"))
    missing = [g.__name__ for g in sm.GROUPS if f"sm.{g.__name__}" not in text]
    assert not missing, f"파일이 없는 묶음: {missing}"
