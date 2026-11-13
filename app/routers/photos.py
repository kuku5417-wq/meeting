"""사진 — 업로드·연결 해제·원본·합성 미리보기·편집기·주석 저장 API (기능 8)."""
from __future__ import annotations

import io
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app import models as m
from app.db import get_session
from app.routers.write import _block_back, _issue_back
from app.services import photos as ph
from app.services import weeks
from app.services import writing as w

router = APIRouter()


def _photo_or_404(s: Session, photo_id: str) -> m.Photo:
    p = s.get(m.Photo, photo_id)
    if p is None or not ph.original_path(p).exists():
        raise HTTPException(404, f"사진 {photo_id} 를 찾을 수 없습니다.")
    return p


@router.post("/blocks/{block_id}/photos")
async def post_photo(block_id: str, role: str = Form("main"), file: UploadFile = File(...),
                     s: Session = Depends(get_session)):
    b, sec = _block_back(s, block_id)
    data = await file.read(ph.MAX_BYTES + 1)
    try:
        photo, new = ph.store(s, data)
        ph.link(s, photo, b, role)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(block_id, err=f"{block_id}: {e}")
    note = "" if new else " (같은 사진이 이미 있어 그 원본을 연결했습니다)"
    return _issue_back(block_id, photo=f"{photo.id}-{role}",
                 msg=f"{block_id} {ph.ROLES[role]} 칸에 {photo.id} 연결{note}")


@router.post("/blocks/{block_id}/photos/{photo_id}/unlink")
def post_unlink(block_id: str, photo_id: str, role: str = Form("main"), s: Session = Depends(get_session)):
    _, sec = _block_back(s, block_id)
    try:
        ph.unlink(s, photo_id, block_id, role)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(block_id, err=str(e))
    return _issue_back(block_id, msg=f"{photo_id} 연결을 뗐습니다 (원본은 보관)")


@router.post("/blocks/{block_id}/photos/{photo_id}/role")
def post_photo_role(block_id: str, photo_id: str, role: str = Form("main"), to_role: str = Form("main"),
                    s: Session = Depends(get_session)):
    """사진 구분 바꾸기(사진 ↔ 조치 전/후) — 연결만 옮기고 원본·마킹·이름·설명은 그대로."""
    b, sec = _block_back(s, block_id)
    if role == to_role:
        return _issue_back(block_id)
    try:
        lk = s.get(m.PhotoLink, (photo_id, block_id, role))
        ph.update_info(s, photo_id, b, role, to_role, lk.caption if lk else "", lk.note if lk else "")
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(block_id, err=str(e))
    return _issue_back(block_id, msg=f"{photo_id} 를 {ph.ROLES.get(to_role, to_role)} 칸으로 옮겼습니다")


@router.post("/blocks/{block_id}/photos/{photo_id}/info")
def post_photo_info(block_id: str, photo_id: str, role: str = Form("main"), to_role: str = Form(""),
                    caption: str = Form(""), note: str = Form(""), back: str = Form(""),
                    s: Session = Depends(get_session)):
    """사진 구분·이름·설명 저장. back=edit 면 편집기로 돌아간다."""
    b, sec = _block_back(s, block_id)
    to_role = to_role or role
    try:
        ph.update_info(s, photo_id, b, role, to_role, caption, note)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        if back == "edit":
            return RedirectResponse(f"/photos/{photo_id}/edit?block={block_id}&role={role}&err={quote(str(e))}",
                                    status_code=303)
        return _issue_back(block_id, err=str(e))
    if back == "edit":
        done = quote("사진 정보를 저장했습니다")
        return RedirectResponse(f"/photos/{photo_id}/edit?block={block_id}&role={to_role}&msg={done}", status_code=303)
    return _issue_back(block_id, photo=f"{photo_id}-{to_role}", msg=f"{photo_id} 사진 정보를 저장했습니다")


@router.post("/blocks/{block_id}/photos/{photo_id}/move")
def post_photo_move(block_id: str, photo_id: str, role: str = Form("main"), dir: str = Form("down"),
                    s: Session = Depends(get_session)):
    _, sec = _block_back(s, block_id)
    step = -1 if dir == "up" else 1
    try:
        moved = ph.move(s, photo_id, block_id, role, step)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(block_id, err=str(e))
    where = "앞으로" if step < 0 else "뒤로"
    return _issue_back(block_id, photo=f"{photo_id}-{role}", msg=f"{photo_id} 순서를 {where} 옮겼습니다" if moved else "")


@router.get("/photos/{photo_id}/original")
def get_original(photo_id: str, s: Session = Depends(get_session)):
    p = _photo_or_404(s, photo_id)
    return FileResponse(ph.original_path(p))


@router.get("/photos/{photo_id}/render")
def get_render(photo_id: str, block: str | None = Query(None), w_: int | None = Query(None, alias="w", ge=40, le=4000),
               s: Session = Depends(get_session)):
    """원본 + 주석 합성 PNG (출력용 미리보기). block 이 없으면 주석 없이."""
    p = _photo_or_404(s, photo_id)
    if not block:
        # 주석 없는 원본 축소본(편집기 작업용 사진) — 원본이 바뀌지 않으므로 JPEG 로 가볍게, 캐시해도 된다
        buf = io.BytesIO()
        ph.compose(p, None, w_).save(buf, format="JPEG", quality=88)
        return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
    doc = ph.load_doc(s, photo_id, block)
    return Response(ph.render_png(p, doc, w_), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/api/photos/{photo_id}/annotation")
def post_annotation(photo_id: str, block: str = Query(...), doc: dict = Body(...), s: Session = Depends(get_session)):
    p = _photo_or_404(s, photo_id)
    b = s.get(m.Block, block)
    if b is None:
        raise HTTPException(404, f"블록 {block} 를 찾을 수 없습니다.")
    try:
        ann = ph.save_annotation(s, p, b, doc)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    return {"ok": True, "annotation_id": ann.id, "markers": len(ph.load_doc(s, photo_id, block)["markers"]),
            "missing_part": ph.markers_missing_part(s, block)}


def render_editor(request: Request, s: Session, photo_id: str, block_id: str, page):
    p = _photo_or_404(s, photo_id)
    b, sec = _block_back(s, block_id)
    if not any(x.id == p.id for _, x in ph.block_photos(s, block_id)):
        raise HTTPException(404, f"{photo_id} 는 {block_id} 에 연결된 사진이 아닙니다.")
    links = ph.block_photos(s, block_id)
    want = request.query_params.get("role", "")
    idx = next((i for i, (lk, x) in enumerate(links) if x.id == p.id and (not want or lk.role == want)),
               next(i for i, (_, x) in enumerate(links) if x.id == p.id))
    nav = [{"photo": x.id, "role": lk.role} for lk, x in links]
    # 편집기 작업용 사진 — 긴 변 WORK_MAX 이하로 줄인 것(좌표는 원본 픽셀 그대로, 편집기가 늘려 그림)
    long_side = max(p.width or 0, p.height or 0)
    work_src = (f"/photos/{p.id}/render?w={max(1, round((p.width or 1) * ph.WORK_MAX / long_side))}"
                if long_side > ph.WORK_MAX else f"/photos/{p.id}/original")
    return page(request, "photo_edit.html", "write", weeks.from_id(sec.week_id),
                photo=p, block=b, section=sec, doc=ph.load_doc(s, photo_id, block_id),
                components=ph.component_options(s, block_id), colors=ph.COLORS,
                readonly=False, work_src=work_src, link=links[idx][0], idx=idx, nav=nav, roles=ph.ROLES,
                msg=request.query_params.get("msg", ""), err=request.query_params.get("err", ""))
