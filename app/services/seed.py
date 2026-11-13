"""기준정보 시드 — `data/samples/masters/*.csv` → DB (docs/03 §6).

- **다시 실행해도 중복 없음**: PK 가 있는 표는 `merge`(있으면 갱신), `alias` 는 (표기·대상 종류·호선 범위)로 찾아 갱신.
- 호선 컬럼은 전부 `ensure_sn` 을 거친다(공통 규칙 3) — CSV 에 `2511`·`S2511` 이 섞여 와도 `SN2511` 로 모인다.
- 별칭 대상이 기준정보에 없으면 넣지 않고 경고로 돌려준다(끊긴 연결을 만들지 않는다).
- 실제 데이터로 바꿀 때는 CSV 만 교체한다.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from sn_util import ensure_sn

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "samples" / "masters"

# (파일, 모델, 호선 컬럼, 정수 컬럼, 날짜 컬럼, 자기참조 부모 컬럼) — FK 순서대로
_TABLES: tuple[tuple[str, type, tuple[str, ...], tuple[str, ...], tuple[str, ...], str | None], ...] = (
    ("department", m.Department, (), ("order_no",), (), None),
    ("ship_type", m.ShipType, (), (), (), None),
    ("owner", m.Owner, (), (), (), None),
    ("sister_group", m.SisterGroup, (), (), (), None),
    ("maker", m.Maker, (), (), (), None),
    ("system", m.System, (), (), (), "parent_id"),
    ("symptom_code", m.SymptomCode, (), (), (), "parent_id"),
    ("cause_code", m.CauseCode, (), (), (), "parent_id"),
    ("hull", m.Hull, ("id",), (), ("delivery_date",), None),
    ("equipment_model", m.EquipmentModel, (), (), (), None),
    ("installed_equipment", m.InstalledEquipment, ("hull_id",), ("unit_no",), (), None),
    ("component", m.Component, (), (), (), None),
    ("test_item", m.TestItem, (), (), (), None),
)

# 별칭 target_kind → 대상 모델
ALIAS_TARGETS: dict[str, type] = {
    "hull": m.Hull, "installed_equipment": m.InstalledEquipment, "system": m.System,
    "component": m.Component, "test_item": m.TestItem, "symptom": m.SymptomCode,
    "cause": m.CauseCode, "equipment_model": m.EquipmentModel,
}


@dataclass
class SeedReport:
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def _parents_first(rows: list[dict[str, str]], parent_col: str) -> list[dict[str, str]]:
    """자기참조 표(system 등)는 부모 행을 먼저 넣어야 FK 가 깨지지 않는다."""
    done: set[str] = set()
    out: list[dict[str, str]] = []
    pending = list(rows)
    while pending:
        progressed = False
        for r in list(pending):
            p = r.get(parent_col) or ""
            if not p or p in done or p not in {x["id"] for x in rows}:
                out.append(r)
                done.add(r["id"])
                pending.remove(r)
                progressed = True
        if not progressed:      # 순환 — 남은 행은 그대로 넣고 DB 가 판단하게 한다
            out.extend(pending)
            break
    return out


def _coerce(row: dict[str, str], hull_cols, int_cols, date_cols) -> dict:
    out: dict = {}
    for k, v in row.items():
        if k in hull_cols:
            out[k] = ensure_sn(v) or None
        elif k in int_cols:
            out[k] = int(v) if v else None
        elif k in date_cols:
            out[k] = date.fromisoformat(v) if v else None
        else:
            out[k] = v or None
    return out


def seed_masters(s: Session, src: Path = DEFAULT_DIR) -> SeedReport:
    rep = SeedReport()
    for name, model, hull_cols, int_cols, date_cols, parent_col in _TABLES:
        path = src / f"{name}.csv"
        if not path.exists():
            rep.warnings.append(f"{name}.csv 가 없어 건너뜀")
            continue
        rows = _read(path)
        if parent_col:
            rows = _parents_first(rows, parent_col)
        for r in rows:
            s.merge(model(**_coerce(r, hull_cols, int_cols, date_cols)))
            s.flush()
        rep.counts[name] = len(rows)

    n = 0
    for r in _read(src / "alias.csv") if (src / "alias.csv").exists() else []:
        kind, target, scope = r["target_kind"], r["target_id"], ensure_sn(r.get("scope_hull_id")) or None
        if kind == "hull":
            target = ensure_sn(target)
        tm = ALIAS_TARGETS.get(kind)
        if tm is None or s.get(tm, target) is None:
            rep.warnings.append(f"별칭 '{r['text']}' 의 대상 {kind}:{target} 이 기준정보에 없어 넣지 않음")
            continue
        row = s.scalar(select(m.Alias).where(
            m.Alias.text == r["text"], m.Alias.target_kind == kind,
            m.Alias.scope_hull_id.is_(None) if scope is None else m.Alias.scope_hull_id == scope))
        if row is None:
            s.add(m.Alias(text=r["text"], target_kind=kind, target_id=target,
                          scope_hull_id=scope, source=r.get("source") or "seed"))
        else:
            row.target_id = target
        n += 1
    s.flush()
    rep.counts["alias"] = n
    s.commit()
    return rep
