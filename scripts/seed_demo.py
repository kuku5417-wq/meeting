"""seed_demo.py — 시연용 가상 데이터: 기준정보 + 과거 사례(data/samples/demo_cases.json). 다시 실행해도 중복 없음.

실행: uv run python scripts/seed_demo.py
⚠ 운영 DB 에는 넣지 않는다 — 시안과 같은 가상 사례로 화면을 확인하기 위한 것이다.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — 리다이렉트 환경
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal, init_db  # noqa: E402
from app.services.demo import seed_demo_cases  # noqa: E402
from app.services.seed import seed_masters  # noqa: E402


def main() -> int:
    init_db()
    with SessionLocal() as s:
        seed_masters(s)
        r = seed_demo_cases(s)
    print(f"[PASS] 가상 사례 {r['cases']}건 · 진행 중 이슈 {r['open']}건 추가 (이미 있던 것은 그대로)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
