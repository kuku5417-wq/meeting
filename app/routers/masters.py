"""기준정보 조회 API (읽기 전용) — /api/masters/..., /api/alias/resolve, /api/equipment/{id}/card."""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.services import alias as alias_svc
from app.services import masters as ms

router = APIRouter(prefix="/api", tags=["masters"])


def _kind_or_404(kind: str) -> str:
    if kind not in ms.KINDS:
        raise HTTPException(404, f"없는 기준정보 종류입니다: {kind}. 가능한 값: {', '.join(ms.KINDS)}")
    return kind


@router.get("/masters")
def kinds() -> dict:
    return {"kinds": list(ms.KINDS)}


@router.get("/masters/{kind}")
def list_kind(kind: str, s: Session = Depends(get_session)) -> list[dict]:
    return ms.list_kind(s, _kind_or_404(kind))


@router.get("/masters/{kind}/{key}")
def get_kind(kind: str, key: str, s: Session = Depends(get_session)) -> dict:
    row = ms.get_kind(s, _kind_or_404(kind), key)
    if row is None:
        raise HTTPException(404, f"{kind} 에 {key} 가 없습니다.")
    return row


@router.get("/alias/resolve")
def resolve(q: str = Query(..., min_length=1, description="현장 표기 (예: 2511 DG2)"),
            hull: str | None = Query(None, description="문맥 호선 (예: SN2511)"),
            s: Session = Depends(get_session)) -> dict:
    r = alias_svc.resolve(s, q, hull)
    return {**asdict(r), "linked": r.linked}


@router.get("/alias/conflicts")
def conflicts(s: Session = Depends(get_session)) -> list[dict]:
    return [{"normalized": k, "scope_hull_id": h, "targets": t} for k, h, t in alias_svc.conflicts(s)]


@router.get("/equipment/{eq_id}/card")
def equipment_card(eq_id: str, s: Session = Depends(get_session)) -> dict:
    card = ms.equipment_card(s, eq_id)
    if card is None:
        raise HTTPException(404, f"탑재 장비 {eq_id} 가 기준정보에 없습니다.")
    return card
