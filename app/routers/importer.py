"""가져오기 — 화면(GET /import, main.py 의 _page 로) · 메모·파일·메일함 입구 · 조각 판정·반영 API (M13).

입구 폼은 POST → 303(가져오기 화면으로), 조각 판정·반영은 JSON(바뀐 뒤 상태 전체를 돌려준다). 오류는 고치는 법을 담은 한국어 문장.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import path_config as pc
from app import models as m
from app import settings
from app.db import get_session
from app.routers import write as write_router
from app.services import importer as im
from app.services import outlook_client as oc
from app.services import writing as w

router = APIRouter()


def _to(msg: str = "", err: str = "", **q: str) -> RedirectResponse:
    parts = [f"{k}={quote(str(v))}" for k, v in q.items() if v] + ([f"msg={quote(msg)}"] if msg else []) + ([f"err={quote(err)}"] if err else [])
    return RedirectResponse("/import" + ("?" + "&".join(parts) if parts else ""), status_code=303)


def render_import(request: Request, s: Session, page):
    q = request.query_params
    jobs = list(s.scalars(select(m.ImportJob).order_by(m.ImportJob.id.desc()).limit(30)))
    left = {j.id: s.scalar(select(func.count()).select_from(m.ImportPiece).where(m.ImportPiece.job_id == j.id, m.ImportPiece.applied.is_(False))) or 0
            for j in jobs}
    job = s.get(m.ImportJob, int(q["job"])) if q.get("job", "").isdigit() else None
    memo = s.get(m.Memo, q.get("memo", "")) if q.get("memo") else None
    if memo is not None:                                    # 옛 판 ID 로 열어도 최신 판
        while True:
            newer = s.scalar(select(m.Memo).where(m.Memo.revises_id == memo.id).limit(1))
            if newer is None:
                break
            memo = newer
    mv = write_router.memo_view(s, memo) if memo else None
    depts = list(s.scalars(select(m.Department).order_by(m.Department.order_no)))
    entry = q.get("entry", "") or ("" if (job or memo) else "memo")
    import json as _json
    state = _json.dumps(im.job_state(s, job), ensure_ascii=False).replace("</", "<\\/") if job else ""
    return page(request, "import.html", "import", jobs=jobs, left=left, job=job, state_json=state, memos=write_router.recent_memos(s),
                open_memo=mv, memo_blocks=mv["items"] if mv else [], mweek=mv["week"] if mv else "", mdept=mv["dept"] if mv else "",
                editing=bool(q.get("edit")), entry=entry, depts=depts, dept=q.get("dept", "") or (depts[0].id if depts else ""),
                chain=" → ".join(write_router.llm.LABELS.get(c, c) for c in settings.LLM_CHAIN), kinds=im.KINDS,
                mail_why=oc.why_not(settings.MAIL_FOLDER), mail_folder=settings.MAIL_FOLDER, mail_days=settings.MAIL_DAYS,
                max_mb=settings.IMPORT_MAX_MB, msg=q.get("msg", ""), err=q.get("err", ""))


# ── 입구 ────────────────────────────────────────────────
@router.post("/import/memo")
def post_memo(dept_id: str = Form(""), raw_text: str = Form(""), then: str = Form("extract"), s: Session = Depends(get_session)):
    """메모 입구 — 메신저 대화면 시간·보낸 사람을 걷고 저장, 곧바로 AI 정리(메모 → 이슈)."""
    try:
        memo, cl = im.memo_entry(s, dept_id, raw_text)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _to(err=str(e), entry="memo", dept=dept_id)
    sec = s.get(m.Section, memo.section_id)
    head = f"메모를 저장했습니다({memo.id})" + (f" · 메신저 머리줄 {cl.removed + cl.stripped}줄 걷음(이름 저장 안 함)" if cl.messenger else "")
    if then != "extract":
        return _to(msg=head + " — 「AI 정리」를 눌러 이슈로 나눠주세요", memo=memo.id)
    return write_router._extract_and_back(s, sec.week_id, sec.department_id, memo, head)


@router.post("/import/file")
async def post_file(file: UploadFile = File(...), dept_id: str = Form(""), s: Session = Depends(get_session)):
    data = await file.read(settings.IMPORT_MAX_MB * 1024 * 1024 + 1)
    try:
        job = im.import_file(s, file.filename or "", data, dept_id or None)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _to(err=str(e), entry="file")
    n = s.scalar(select(func.count()).select_from(m.ImportPiece).where(m.ImportPiece.job_id == job.id))
    return _to(msg=f"「{job.title}」을 조각 {n}개로 나눴습니다 — 조각마다 판정한 뒤 「반영하기」", job=str(job.id))


@router.post("/import/mail")
def post_mail(dept_id: str = Form(""), s: Session = Depends(get_session)):
    """메일함에서 가져오기 — 정해진 폴더의 최근 메일 중 아직 안 가져온 것. Outlook·pywin32 가 없으면 안내만."""
    why = oc.why_not(settings.MAIL_FOLDER)
    if why:
        return _to(err=why, entry="mail")
    known = {x for x in s.scalars(select(m.ImportJob.source_id).where(m.ImportJob.kind == "mail")) if x}
    mails = oc.fetch(settings.MAIL_FOLDER, settings.MAIL_DAYS, known)
    if mails is None:
        return _to(err="메일함을 읽지 못했습니다 — " + (" / ".join(oc.LAST_ERRORS) or "Outlook 을 확인해주세요")
                   + ". 서버 PC 에서 클래식 Outlook 이 켜져 있는지, 폴더 이름이 맞는지 확인해주세요.", entry="mail")
    jobs = []
    for mail in mails:
        job = im.import_mail(s, mail, dept_id or None)
        if job is not None:
            jobs.append(job)
    s.commit()
    note = (" · 못 읽은 것: " + " / ".join(oc.LAST_ERRORS[:3])) if oc.LAST_ERRORS else ""
    if not jobs:
        return _to(msg=f"새 메일이 없습니다(최근 {settings.MAIL_DAYS}일 · 「{settings.MAIL_FOLDER}」){note}", entry="mail")
    return _to(msg=f"메일 {len(jobs)}통을 가져왔습니다{note}", job=str(jobs[-1].id))


# ── 조각 판정 · 반영 ─────────────────────────────────────
def _job(s: Session, jid: int) -> m.ImportJob:
    job = s.get(m.ImportJob, jid)
    if job is None:
        raise HTTPException(404, "없는 가져오기입니다. 화면을 새로 고쳐주세요.")
    return job


@router.post("/api/import/pieces/{pid}/decide")
async def api_decide(pid: int, request: Request, s: Session = Depends(get_session)):
    p = s.get(m.ImportPiece, pid)
    if p is None:
        raise HTTPException(404, "없는 조각입니다. 화면을 새로 고쳐주세요.")
    d = await request.json()
    try:
        im.decide(s, p, str(d.get("decision", "")), str(d.get("block_id", "")).strip().upper(), str(d.get("line", "")), str(d.get("dept_id", "")))
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    return {"ok": True, "state": im.job_state(s, _job(s, p.job_id))}


@router.post("/api/import/{jid}/apply")
def api_apply(jid: int, s: Session = Depends(get_session)):
    job = _job(s, jid)
    try:
        rep = im.apply(s, job)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return JSONResponse({"ok": False, "err": str(e)}, status_code=400)
    return {"ok": True, "linked": rep.linked, "created": rep.created, "skipped": rep.skipped, "errors": rep.errors,
            "state": im.job_state(s, job)}


@router.get("/import/files/{jid}/{name}")
def get_file(jid: int, name: str, s: Session = Depends(get_session)):
    """조각의 그림(원본 보관본)."""
    _job(s, jid)
    base = (pc.get_import_dir() / str(jid)).resolve()
    p = (base / name).resolve()
    if base not in p.parents or not p.is_file() or p.suffix.lower() not in im._IMG_EXT:
        raise HTTPException(404, "없는 파일입니다.")
    return FileResponse(p)


@router.get("/import/{jid}/original")
def get_original(jid: int, s: Session = Depends(get_session)):
    """원본 내려받기(PPT·HTML·메일 본문) — 보관본 그대로."""
    job = _job(s, jid)
    p = pc.get_import_dir() / job.file_key
    if not job.file_key or not p.is_file():
        raise HTTPException(404, "원본 파일이 없습니다.")
    return FileResponse(p, filename=Path(job.file_key).name)
