"""기준정보 조회 — API 와 장비 허브 화면이 함께 쓰는 읽기 전용 함수."""
from __future__ import annotations

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m

# /api/masters/{kind} 로 열어 주는 표 — 이름은 docs/03 테이블명 그대로
KINDS: dict[str, type] = {
    "department": m.Department, "ship_type": m.ShipType, "owner": m.Owner,
    "sister_group": m.SisterGroup, "hull": m.Hull, "system": m.System, "maker": m.Maker,
    "equipment_model": m.EquipmentModel, "installed_equipment": m.InstalledEquipment,
    "component": m.Component, "test_item": m.TestItem, "symptom_code": m.SymptomCode,
    "cause_code": m.CauseCode, "alias": m.Alias,
}


def to_dict(obj) -> dict:
    out = {}
    for c in sa_inspect(obj).mapper.column_attrs:
        v = getattr(obj, c.key)
        out[c.key] = v.isoformat() if hasattr(v, "isoformat") else v
    return out


def list_kind(s: Session, kind: str) -> list[dict]:
    model = KINDS[kind]
    pk = sa_inspect(model).primary_key[0]
    return [to_dict(r) for r in s.scalars(select(model).order_by(pk))]


def get_kind(s: Session, kind: str, key: str) -> dict | None:
    model = KINDS[kind]
    pk_type = sa_inspect(model).primary_key[0].type.python_type
    try:
        obj = s.get(model, pk_type(key))
    except (TypeError, ValueError):  # noqa: PERF203 — 정수 PK 에 문자열 → 없음
        return None
    return to_dict(obj) if obj else None


def system_path(s: Session, system_id: str | None) -> list[str]:
    """시스템 계층 이름 — 최상위부터 (기관 › 발전 시스템 › 주발전기)."""
    names: list[str] = []
    seen: set[str] = set()
    while system_id and system_id not in seen:
        seen.add(system_id)
        node = s.get(m.System, system_id)
        if node is None:
            break
        names.append(node.name)
        system_id = node.parent_id
    return list(reversed(names))


def equipment_card(s: Session, eq_id: str) -> dict | None:
    """장비 허브 「기준정보」 카드. 기준정보에 없는 칸은 None — 화면은 값을 지어내지 않는다."""
    eq = s.get(m.InstalledEquipment, eq_id)
    if eq is None:
        return None
    hull = s.get(m.Hull, eq.hull_id)
    ship_type = s.get(m.ShipType, hull.ship_type_id) if hull and hull.ship_type_id else None
    owner = s.get(m.Owner, hull.owner_id) if hull and hull.owner_id else None
    sisters: list[str] = []
    if hull and hull.sister_group_id:
        sisters = list(s.scalars(select(m.Hull.id).where(m.Hull.sister_group_id == hull.sister_group_id)
                                 .order_by(m.Hull.id)))
    model = s.get(m.EquipmentModel, eq.equipment_model_id) if eq.equipment_model_id else None
    maker = s.get(m.Maker, model.maker_id) if model and model.maker_id else None
    tests = list(s.scalars(select(m.TestItem.name).where(m.TestItem.system_id == eq.system_id)
                           .order_by(m.TestItem.code))) if eq.system_id else []
    aliases = list(s.scalars(select(m.Alias.text).where(
        m.Alias.target_kind == "installed_equipment", m.Alias.target_id == eq.id).order_by(m.Alias.id)))
    return {
        "id": eq.id, "name": eq.name, "position": eq.position,
        "title": f"{eq.hull_id} {eq.name}",
        "hull_id": eq.hull_id, "stage": hull.stage if hull else None,
        "ship_type": ship_type.name if ship_type else None, "owner": owner.name if owner else None,
        "sisters": sisters,
        "system_path": system_path(s, eq.system_id),
        "model": " · ".join(x for x in (maker.name if maker else None, model.name if model else None) if x) or None,
        "model_no": model.model_no if model else None,
        "test_items": tests,
        "aliases": aliases,
    }


# ── 미등록 표기 (2026-10-21) ────────────────────────────
# 작성자가 「미등록으로 두기」 한 태그 — 기준정보에 없는 장비·호선·부위. 담당자가 기준정보 CSV 에 넣고
# 시드를 다시 돌리면(scripts/seed_masters.py) relink_unregistered 가 별칭으로 다시 이어 준다.
def _unreg_rows(s: Session):
    from app.services import writing as w
    return list(s.scalars(select(m.BlockTag).where(
        m.BlockTag.kind.in_(sorted(w.LINKABLE)), m.BlockTag.target_id.is_(None),
        m.BlockTag.confirmed.is_(True), m.BlockTag.dismissed.is_(False)).order_by(m.BlockTag.id)))


def unregistered(s: Session) -> list[dict]:
    """(종류, 표기)별로 묶은 미등록 목록 — 건수·블록·최근 주차·호선."""
    from app.services import writing as w
    groups: dict[tuple[str, str], dict] = {}
    for t in _unreg_rows(s):
        key = (t.kind, (t.raw_text or "").strip())
        g = groups.setdefault(key, {"kind": t.kind, "kind_label": w.KIND_LABEL.get(t.kind, t.kind), "text": key[1],
                                    "count": 0, "blocks": [], "hulls": set(), "week": ""})
        g["count"] += 1
        if t.block_id not in g["blocks"]:
            g["blocks"].append(t.block_id)
        hull = w.block_hull(s, t.block_id)
        if hull:
            g["hulls"].add(hull)
        sec = w.block_section(s, t.block_id)
        if sec and sec.week_id > g["week"]:
            g["week"] = sec.week_id
    out = sorted(groups.values(), key=lambda g: (-g["count"], g["kind"], g["text"]))
    for g in out:
        g["hulls"] = sorted(g["hulls"])
    return out


def relink_unregistered(s: Session) -> int:
    """미등록 태그를 기준정보·별칭으로 다시 이어 본다. 이어진 수를 돌려준다(이어진 태그는 확인된 연결이 된다)."""
    from app.services import alias as alias_svc
    from app.services import writing as w
    from sn_util import ensure_sn
    n = 0
    for t in _unreg_rows(s):
        target = None
        if t.kind == "hull":
            h = ensure_sn(t.raw_text or "")
            target = h if h and s.get(m.Hull, h) is not None else None
        else:
            r = alias_svc.resolve(s, t.raw_text or "", hull_id=w.block_hull(s, t.block_id), kinds={t.kind})
            target = r.target_id if r.linked and not r.conflict else None
        if target:
            t.target_id = target
            n += 1
    s.flush()
    return n

