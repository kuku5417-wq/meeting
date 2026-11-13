"""데모 데이터 — `data/samples/demo_cases.json` 의 가상 과거 사례를 넣는다(다시 실행해도 중복 없음).

시안(지식창고 C·장비 허브 D)의 예시와 같은 사례라 화면을 시안처럼 확인할 수 있다. 실제 회사 데이터가 아니다.
블록·이력·태그·종결 요청(승인)·사례 카드를 실제 흐름과 같은 모양으로 만든다.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app import settings
from app.services import weeks
from app.services import writing as w

SRC = settings.ROOT / "data" / "samples" / "demo_cases.json"


def _block(s: Session, d: dict, status: str) -> m.Block | None:
    if s.get(m.Block, d["block_id"]) is not None:
        return None                                    # 이미 있음 — 그대로 둔다
    eq = s.get(m.InstalledEquipment, d["eq"])
    if eq is None:
        raise w.WriteError(f"데모 사례의 장비 {d['eq']} 가 기준정보에 없습니다. 기준정보 시드를 먼저 실행해주세요.")
    for wid in {d["created_week"], d.get("approved_week") or d["created_week"]}:
        w.ensure_week(s, weeks.from_id(wid))
    b = m.Block(id=d["block_id"], block_type="issue", title=d["title"], body=d["symptom_text"], status=status,
                owner_department_id=d.get("transfer_to") or d["dept"], created_week_id=d["created_week"], origin="manual")
    s.add(b)
    s.flush()
    s.add(m.BlockHistory(block_id=b.id, week_id=d["created_week"], department_id=d["dept"], status="신규", note="신규 등록"))
    if d.get("transfer_to"):
        dn = {x.id: x.name for x in s.scalars(select(m.Department))}
        s.add(m.BlockHistory(block_id=b.id, week_id=d["created_week"], department_id=d["transfer_to"], status="진행",
                             note=f"{dn[d['dept']]} → {dn[d['transfer_to']]} 이관"))
    for kind, target, raw in (("hull", eq.hull_id, eq.hull_id), ("installed_equipment", eq.id, eq.name),
                              ("symptom", d.get("symptom_code"), d["symptom_text"]), ("cause", d.get("cause_code"), d["cause_text"])):
        s.add(m.BlockTag(block_id=b.id, kind=kind, target_id=target, raw_text=raw, confidence=1.0, confirmed=True))
    s.flush()
    return b


def seed_demo_cases(s: Session, src: Path = SRC) -> dict:
    data = json.loads(src.read_text(encoding="utf-8"))
    n_case = n_open = 0
    for d in data["cases"]:
        b = _block(s, d, "종결")
        if b is None:
            continue
        s.add(m.Closure(block_id=b.id, action_text=d["action_text"], requested_week_id=d["approved_week"],
                        decision="승인", decided_week_id=d["approved_week"]))
        s.add(m.BlockHistory(block_id=b.id, week_id=d["approved_week"], department_id=b.owner_department_id,
                             status="종결", note=f"회의 종결 승인 → {d['case_id']}"))
        s.add(m.CaseCard(id=d["case_id"], block_id=b.id, symptom_text=d["symptom_text"], cause_text=d["cause_text"],
                         action_text=d["action_text"], symptom_code_id=d.get("symptom_code"), cause_code_id=d.get("cause_code"),
                         installed_equipment_id=d["eq"], approved_week_id=d["approved_week"], validity="유효"))
        n_case += 1
    for d in data.get("open", []):
        if _block(s, d, "진행") is not None:
            n_open += 1
    s.commit()
    return {"cases": n_case, "open": n_open}
