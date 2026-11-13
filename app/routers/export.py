"""내보내기 — 회의자료 PPT(기능 13, M11 report_item 기반 — 옛 합본·부서 PPT 는 M12 에서 없앴다). 내려준 파일은 `<base>/meeting/exports/<주차>/` 에도 남긴다."""
from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import models as m
from app.db import get_session
from app.export import pptx_builder as pb
from app.services import weeks
import path_config as pc

router = APIRouter()
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _download(data: bytes, week_id: str, name: str) -> Response:
    try:
        d = pc.get_export_dir() / week_id
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{datetime.now():%Y%m%d-%H%M%S}_{name}").write_bytes(data)
    except Exception:  # noqa: BLE001 — 기록 사본 저장 실패는 내려받기를 막지 않는다
        pass
    ascii_name = f"meeting_{week_id}.pptx"
    return Response(data, media_type=PPTX, headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"})


def _week(week_id: str) -> str:
    if weeks.parse(week_id) is None:
        raise HTTPException(404, f"주차 형식이 맞지 않습니다: {week_id}. 2026-W42 처럼 입력해주세요.")
    return week_id


@router.get("/export/meeting/{mid}/pptx")
def export_meeting(mid: int, s: Session = Depends(get_session)):
    """M11 회의자료 PPT — 제출·발행판이 있으면 그 판(회의에서 본 그대로), 없으면 지금 구성(「구성 중」)."""
    from app.services import studio as st
    mt = s.get(m.Meeting, mid)
    if mt is None:
        raise HTTPException(404, "없는 회의입니다. 회의 목록에서 다시 골라주세요.")
    v = st.latest_version(s, mt)
    d = st.version_deck(v) or st.deck(s, mt)
    name = (mt.title or st.KINDS.get(mt.kind, "회의자료")) + (f"_{v.version}판" if v else "_구성중")
    return _download(pb.build_meeting(s, d, v is not None), mt.week_id, f"{name}.pptx")
