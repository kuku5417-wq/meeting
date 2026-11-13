"""seed_masters.py — 기준정보 CSV → DB (다시 실행해도 중복 없음).

실행: uv run python scripts/seed_masters.py              data/samples/masters 사용
      uv run python scripts/seed_masters.py <CSV 폴더>   실제 데이터 폴더 지정
"""
from __future__ import annotations

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
from app.services.central import sync_hulls  # noqa: E402
from app.services.masters import relink_unregistered  # noqa: E402
from app.services.seed import DEFAULT_DIR, seed_masters  # noqa: E402


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DIR
    if not src.is_dir():
        print(f"[FAIL] CSV 폴더가 없습니다: {src}")
        return 1
    print(f"DB: {path_config.db_path()}")
    init_db()
    with SessionLocal() as s:
        rep = seed_masters(s, src)
        relinked = relink_unregistered(s)      # 미등록으로 두었던 표기가 이번 기준정보로 이어지면 연결
        hull_rep = sync_hulls(s)               # 호선은 pjtlist(중앙 parquet, 읽기 전용)가 정본
        s.commit()
    for name, n in rep.counts.items():
        print(f"[PASS] {name:<20} {n:>4}행")
    for w in rep.warnings:
        print(f"[WARN] {w}")
    if hull_rep.ok:
        print(f"[PASS] 호선 동기화(pjtlist) 새로 {len(hull_rep.created)} · 갱신 {len(hull_rep.updated)}")
    else:
        print(f"[WARN] 호선 동기화 건너뜀 — {hull_rep.reason}")
    if relinked:
        print(f"[PASS] 미등록 표기 {relinked}건을 새 기준정보에 이었습니다")
    print("[완료] 기준정보 저장 끝 — 이 창은 닫아도 됩니다")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    # 저장(commit)은 main 안에서 끝났다. DB 가 NAS(네트워크 폴더)에 있으면 종료 때 연결 정리에서
    # 창이 멈추는 사례가 있어(사내 PC, 2026-10-21) 정리 단계를 건너뛰고 바로 끝낸다.
    os._exit(code)
