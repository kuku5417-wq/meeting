"""부서 이름 바로잡기 — M0 자리표시(「부서 1」~「부서 8」)가 남은 DB 를 department.csv 의 실제 이름으로 (2026-10-29).

운영 DB 가 실제 부서 반영(2026-10-21) 전에 만들어져 이름이 자리표시로 남은 경우에 쓴다.
- 부서(department)만 고친다 — 다른 기준정보 CSV(가상 데이터)는 건드리지 않는다(seed_masters.py 를 운영에서 돌리지 않는 이유).
- 이미 만든 부서 회의자료 제목 「W44 부서 1 회의자료」도 새 이름으로 바꾼다(제목을 사람이 고친 것은 그대로).
- 다시 실행해도 바뀔 것이 없으면 아무것도 하지 않는다. --dry-run 이면 보여주기만.

    uv run python scripts/fix_department_names.py --dry-run
    uv run python scripts/fix_department_names.py
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

import path_config as pc  # noqa: E402
from app import models as m  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402

CSV = Path(__file__).resolve().parents[1] / "data" / "samples" / "masters" / "department.csv"
_OLD_TITLE = re.compile(r"^(W\d{2}) 부서 \d+ 회의자료$")


def main(dry: bool) -> int:
    print(f"DB: {pc.db_path()}")
    init_db()
    rows = list(csv.DictReader(CSV.open(encoding="utf-8-sig")))
    n_dept = n_title = 0
    with SessionLocal() as s:
        for r in rows:
            d = s.get(m.Department, r["id"])
            want = (r["code"], r["name"], int(r["order_no"]))
            if d is None:
                print(f"[추가] {r['id']} {r['name']}")
                if not dry:
                    s.add(m.Department(id=r["id"], code=want[0], name=want[1], order_no=want[2]))
                n_dept += 1
            elif (d.code, d.name, d.order_no) != want:
                print(f"[이름] {d.id} {d.name} → {want[1]}")
                if not dry:
                    d.code, d.name, d.order_no = want
                n_dept += 1
        names = {r["id"]: r["name"] for r in rows}
        for mt in s.scalars(select(m.Meeting).where(m.Meeting.kind == "dept")):
            hit = _OLD_TITLE.match(mt.title or "")
            if hit and mt.owner_dept_id in names:
                new = f"{hit.group(1)} {names[mt.owner_dept_id]} 회의자료"
                print(f"[제목] {mt.title} → {new}")
                if not dry:
                    mt.title = new
                n_title += 1
        if not dry:
            s.commit()
    print(("미리보기(저장 안 함)" if dry else "저장함") + f" — 부서 {n_dept} · 회의 제목 {n_title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--dry-run" in sys.argv))
