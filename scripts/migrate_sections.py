"""migrate_sections.py — 옛 섹션 → 회의자료(부서 자료·공유회 판) 이전 (M12, 다시 실행해도 중복 없음).

실행: uv run python scripts/migrate_sections.py --dry-run     바꿀 것만 보여 주고 저장하지 않는다(미리보기)
      uv run python scripts/migrate_sections.py               이번 주 이전 주차를 옮기고 저장
      uv run python scripts/migrate_sections.py --until 2026-W40   그 주 이전까지만
규칙은 app/services/migrate.py 첫머리. 원본(섹션·메모·사진)은 그대로 둔다.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 — 리다이렉트 환경
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import path_config  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.services import migrate, weeks  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="옛 섹션 → 회의자료 이전")
    ap.add_argument("--dry-run", action="store_true", help="저장하지 않고 바꿀 것만 보여 준다")
    ap.add_argument("--until", default="", help="이 주차 이전까지(기본: 이번 주)")
    a = ap.parse_args()
    if a.until and weeks.parse(a.until) is None:
        print(f"[FAIL] 주차 형식이 맞지 않습니다: {a.until} — 2026-W40 처럼 적어주세요.")
        return 1
    print(f"DB: {path_config.db_path()}")
    init_db()
    with SessionLocal() as s:
        rep = migrate.migrate(s, a.until or None)
        if a.dry_run:
            s.rollback()
        else:
            s.commit()
    for x in rep.dept_decks:
        print(f"[PASS] 부서 자료 {x}")
    for x in rep.shares:
        print(f"[PASS] {x}")
    for x in rep.skipped:
        print(f"[SKIP] {x}")
    print(f"{'미리보기(저장 안 함)' if a.dry_run else '저장함'} — 부서 자료 {len(rep.dept_decks)} · 공유회 {len(rep.shares)} · 건너뜀 {len(rep.skipped)}")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)     # NAS DB 연결 정리 때 창이 멈추는 사례(seed_masters 와 같음) — 저장은 main 안에서 끝났다
