"""설정 화면 — 부서 이름·순서·코드 고치기 (2026-10-21).

부서 ID(D1~)는 바꾸지 않는다. 블록·섹션·사람이 ID 로 이어져 있어 이름만 바꾸면 기존 기록이 그대로 새 이름으로 보인다.
기준정보 CSV 시드를 다시 돌리지 않은 PC(「부서 1~8」 그대로)도 화면에서 바로 고칠 수 있게 하려는 것이다.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m


@dataclass
class DeptRow:
    id: str            # 빈 값 = 새 부서
    name: str
    code: str
    order_no: int


def departments(s: Session) -> list[m.Department]:
    return list(s.scalars(select(m.Department).order_by(m.Department.order_no, m.Department.id)))


def _next_id(s: Session) -> str:
    n = 0
    for did in s.scalars(select(m.Department.id)):
        if did[:1] == "D" and did[1:].isdigit():
            n = max(n, int(did[1:]))
    return f"D{n + 1}"


def update_departments(s: Session, rows: list[DeptRow]) -> list[str]:
    """부서 표를 저장한다. 문제가 있으면 아무것도 바꾸지 않고 고칠 점 목록을 돌려준다(빈 목록 = 저장됨)."""
    errs: list[str] = []
    rows = [DeptRow(r.id.strip(), r.name.strip(), r.code.strip(), r.order_no) for r in rows]
    rows = [r for r in rows if r.id or r.name or r.code]          # 비워 둔 「새 부서」 줄은 무시
    names: dict[str, int] = {}
    codes: dict[str, int] = {}
    for i, r in enumerate(rows, 1):
        label = r.id or f"새 부서({i}번째 줄)"
        if not r.name:
            errs.append(f"{label}: 부서 이름이 비어 있습니다. 이름을 넣어주세요.")
        elif r.name in names:
            errs.append(f"{label}: 「{r.name}」 이름이 다른 부서와 같습니다. 다른 이름으로 바꿔주세요.")
        names.setdefault(r.name, i)
        code = r.code or r.name
        if code in codes:
            errs.append(f"{label}: 코드 「{code}」 가 다른 부서와 같습니다. 코드를 바꾸거나 비워주세요(비우면 이름을 씁니다).")
        codes.setdefault(code, i)
        if r.id and s.get(m.Department, r.id) is None:
            errs.append(f"{r.id}: 없는 부서입니다. 화면을 새로 고친 뒤 다시 저장해주세요.")
    if errs:
        return errs
    # code 는 unique — 서로 맞바꾸는 경우를 위해 먼저 임시 값으로 비운다
    for r in rows:
        if r.id:
            s.get(m.Department, r.id).code = f"__tmp_{r.id}"
    s.flush()
    for r in rows:
        if r.id:
            d = s.get(m.Department, r.id)
        else:
            d = m.Department(id=_next_id(s))
            s.add(d)
        d.name, d.code, d.order_no = r.name[:64], (r.code or r.name)[:32], r.order_no
        s.flush()
    return []


def usage(s: Session) -> dict[str, int]:
    """부서별 블록 수 — 표에 「기록 n건」으로 보여 준다(이름을 바꿔도 기록은 그대로라는 안내)."""
    return dict(s.execute(select(m.Block.owner_department_id, func.count()).group_by(m.Block.owner_department_id)).all())
