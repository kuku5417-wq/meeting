"""작성 화면 A — 페이지 + 폼 동작(POST → 원래 화면으로 303). JS 없이 동작한다.

알림은 `?msg=` / `?err=` 로 한 번 보여준다(업무 데이터는 항상 DB, 화면 상태만 URL).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app import settings
from app.db import get_session
from app.llm import client as llm
from app.services import carry_over as co
from app.services import closure as cl
from app.services import extract as ex
from app.services import photos as ph
from app.services import tables as tb
from app.services import weeks
from app.services import writing as w

router = APIRouter()


_BLOCK_ID = re.compile(r"^(ISS|PRB|SHR|DSH)-\d{4}-\d{4}$")


def _back(week_id: str, dept_id: str, anchor: str = "", **q: str) -> RedirectResponse:
    """메모 동작 뒤에는 가져오기 화면의 그 메모로, 지표 동작 뒤에는 지표 화면으로(M13 — 옛 작성 화면을 없앴다)."""
    memo = q.pop("memo", "")
    if memo or anchor in ("memo", "blocks"):
        q = {"entry": "memo", "dept": dept_id, **q} if memo in ("", "new") else {"memo": memo, **q}
        qs = urlencode({k: v for k, v in q.items() if v})
        return RedirectResponse(f"/import?{qs}" + ("#memo" if memo not in ("", "new") else ""), status_code=303)
    qs = urlencode({k: v for k, v in {"week": week_id, **q}.items() if v})
    return RedirectResponse(f"/metrics/{dept_id}?{qs}", status_code=303)       # 메모 밖 동작(옛 지표 주소)은 지표 화면으로


def _week_or_404(week_id: str) -> weeks.IsoWeek:
    wk = weeks.parse(week_id)
    if wk is None:
        raise HTTPException(404, f"주차 형식이 맞지 않습니다: {week_id}. 2026-W42 처럼 입력해주세요.")
    return wk


@dataclass
class _Ctx:
    """블록 동작의 주차·부서 — M12: 섹션이 없어도 된다(이번 주 · 담당 부서)."""
    week_id: str
    department_id: str


def _block_back(s: Session, block_id: str) -> tuple[m.Block, _Ctx]:
    b = s.get(m.Block, block_id)
    if b is None:
        raise HTTPException(404, f"블록 {block_id} 를 찾을 수 없습니다.")
    return b, _Ctx(weeks.current().id, b.owner_department_id)


def _issue_back(block_id: str, anchor: str = "attach", **q: str) -> RedirectResponse:
    """블록 동작(매핑·사진·표·한 줄·이관·종결 요청) 뒤에는 이슈 원장의 그 이슈로 — M12 에서 작성 화면에서 옮겼다."""
    qs = urlencode({k: v for k, v in {"id": block_id, **q}.items() if v})
    return RedirectResponse(f"/issues?{qs}" + (f"#{anchor}" if anchor else ""), status_code=303)


def _evidence(s: Session, block_id: str, memos: dict[str, m.Memo]) -> list[dict]:
    out = []
    for sp in s.scalars(select(m.SourceSpan).where(m.SourceSpan.block_id == block_id,
                                                   m.SourceSpan.field.in_(("block", "body")))
                        .order_by(m.SourceSpan.id)):
        memo = memos.get(sp.memo_id) or s.get(m.Memo, sp.memo_id)
        line = ex._line_of(sp.start, ex.memo_lines(memo.raw_text)) if memo else None
        out.append({"line": line, "quote": sp.quote, "memo_id": sp.memo_id})
    return out


def attach_view(s: Session, b: m.Block) -> dict:
    """이슈에 붙은 것 — 매핑(태그)·근거·사진·표(M12: 이슈 원장 화면이 쓴다. 옛 작성 화면에서 옮겼다)."""
    return {
        "photos": [{"link": lk, "p": p, "role": ph.ROLES[lk.role], "key": f"{p.id}-{lk.role}",
                    "markers": len(d_["markers"]), "shapes": len(d_["shapes"])}
                   for lk, p in ph.block_photos(s, b.id) for d_ in [ph.load_doc(s, p.id, b.id)]],
        "tags": [{"t": t, "kind": w.KIND_LABEL.get(t.kind, t.kind), "label": w.tag_label(s, t),
                  "check": w.tag_needs_check(t), "unlinked": t.kind in w.LINKABLE and not t.target_id,
                  "options": w.link_options(s, t) if (t.kind in w.LINKABLE and not t.target_id) else []}
                 for t in w.block_tags(s, b.id)],
        "evidence": _evidence(s, b.id, {}),
        "tables": [{"t": t, "rows": tb.rows_of(t), "tsv": tb.to_tsv(tb.rows_of(t))} for t in tb.block_tables(s, b.id)],
    }


def memo_view(s: Session, memo: m.Memo) -> dict:
    """메모 하나 보기(가져오기 화면) — 최신 판·이전 판·원문 줄·이 메모에서 나온 이슈."""
    chain = w.memo_chain(s, memo)
    ids = [memo.id, *[x.id for x in chain]]
    blocks = []
    for sp in s.scalars(select(m.SourceSpan).where(m.SourceSpan.memo_id.in_(ids), m.SourceSpan.field == "block").order_by(m.SourceSpan.id)):
        b = s.get(m.Block, sp.block_id)
        if b is not None and b not in [x["b"] for x in blocks]:
            blocks.append({"b": b, "type_label": w.TYPE_LABEL[b.block_type]})
    sec = s.get(m.Section, memo.section_id)
    return {"m": memo, "chain": chain, "lines": [t for t, _ in ex.memo_lines(memo.raw_text)], "blocks": len(blocks),
            "items": blocks, "week": sec.week_id if sec else weeks.current().id, "dept": sec.department_id if sec else ""}


def recent_memos(s: Session, limit: int = 30) -> list[m.Memo]:
    """가져오기 화면 왼쪽 「메모」 — 최신 판만, 새것부터."""
    xs = list(s.scalars(select(m.Memo).order_by(m.Memo.created_at.desc(), m.Memo.id.desc()).limit(limit * 3)))
    replaced = {x.revises_id for x in s.scalars(select(m.Memo).where(m.Memo.revises_id.is_not(None)))}
    return [x for x in xs if x.id not in replaced][:limit]


# ── 폼 동작 ─────────────────────────────────────────────
@router.post("/write/{week_id}/{dept_id}/memo")
def post_memo(week_id: str, dept_id: str, raw_text: str = Form(""), then: str = Form(""),
              s: Session = Depends(get_session)):
    """새 메모 저장. then=extract 면 곧바로 AI 정리까지(「저장하고 AI 정리」)."""
    _week_or_404(week_id)
    try:
        sec = w.get_section(s, week_id, dept_id, create=True)
        memo = w.add_memo(s, sec, raw_text)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _back(week_id, dept_id, "memo", memo="new", err=str(e))
    if then == "extract":
        return _extract_and_back(s, week_id, dept_id, memo, f"메모를 저장했습니다({memo.id})")
    return _back(week_id, dept_id, "memo", memo=memo.id,
                 msg=f"메모를 저장했습니다 ({memo.id}). 「AI 정리」를 눌러 블록으로 나눠주세요.")


@router.post("/write/{week_id}/{dept_id}/memo/{memo_id}/revise")
def post_revise(week_id: str, dept_id: str, memo_id: str, raw_text: str = Form(""), s: Session = Depends(get_session)):
    """원문 수정 — 새 판으로 저장(옛 판 보존)하고 곧바로 AI 다시 정리."""
    memo = s.get(m.Memo, memo_id)
    if memo is None:
        raise HTTPException(404, f"메모 {memo_id} 가 없습니다.")
    try:
        new = w.revise_memo(s, memo, raw_text)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _back(week_id, dept_id, "memo", memo=memo_id, err=str(e))
    head = f"원문을 고쳤습니다({new.id} ← {memo.id}, 이전 판도 남아 있습니다)"
    return _extract_and_back(s, week_id, dept_id, new, head)


@router.post("/write/{week_id}/{dept_id}/memo/{memo_id}/extract")
def post_extract(week_id: str, dept_id: str, memo_id: str, s: Session = Depends(get_session)):
    memo = s.get(m.Memo, memo_id)
    if memo is None:
        raise HTTPException(404, f"메모 {memo_id} 가 없습니다.")
    return _extract_and_back(s, week_id, dept_id, memo, "")


def _extract_and_back(s: Session, week_id: str, dept_id: str, memo: m.Memo, head: str):
    try:
        out = ex.run_extract(s, memo)
    except w.WriteError as e:
        s.rollback()
        return _back(week_id, dept_id, "memo", memo=memo.id, err=(head + " · " if head else "") + str(e))
    s.commit()                                     # 실패해도 호출 로그는 남긴다
    tried = (" · 앞선 공급자: " + " / ".join(out.result.errors)) if out.result.errors else ""
    if not out.ok:
        return _back(week_id, dept_id, "memo", memo=memo.id,
                     err=(head + " · " if head else "") + "AI 정리에 실패했습니다 — " + " / ".join(out.result.errors)
                     + ". 잠시 후 「AI 다시 정리」를 눌러주세요.")
    parts = ([head] if head else []) + [f"AI 정리 완료 — {llm.LABELS.get(out.result.provider, out.result.provider)}",
                                        f"새 블록 {len(out.created)}", f"갱신 {len(out.updated)}"]
    if out.carried:
        parts.append(f"이어온 항목 업데이트 {len(out.carried)}")
    if out.kept:
        parts.append(f"사람이 고친 값 {sum(len(v) for v in out.kept.values())}칸 유지")
    if out.dropped:
        parts.append(f"근거 없어 버림 {len(out.dropped)}")
    if out.retyped:
        parts.append(f"지표 없는 대시보드 {out.retyped}개 → 공유정보")
    if out.left:
        parts.append(f"이전 판에서 나온 블록 {len(out.left)}개는 그대로 둠({', '.join(out.left)})")
    return _back(week_id, dept_id, "blocks", memo=memo.id, msg=" · ".join(parts) + tried)


@router.post("/blocks/{block_id}/edit")
def post_block_edit(block_id: str, block_type: str = Form(...), title: str = Form(""), status: str = Form(""),
                    body: str = Form(""), s: Session = Depends(get_session)):
    b, sec = _block_back(s, block_id)
    try:
        changed = [f for f, v in (("block_type", block_type), ("title", title), ("body", body)) if w.update_block(s, b, f, v)]
        if status and w.update_block(s, b, "status", status if b.block_type in w.TRACKED else w.POSTED):
            changed.append("status")
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(block_id, err=f"{block_id}: {e}")
    return _issue_back(block_id,
                 msg=f"{block_id} 저장 — 고친 칸 {len(changed)}개" if changed else f"{block_id} — 바뀐 내용이 없습니다")


@router.post("/blocks/{block_id}/answer")
def post_answer(block_id: str, field: str = Form(...), value: str = Form(""), s: Session = Depends(get_session)):
    b, sec = _block_back(s, block_id)
    try:
        w.answer_question(s, b, field, value)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(block_id, err=f"{b.title or block_id}: {e}")
    return _issue_back(block_id, msg=f"{b.title or block_id} — 답을 반영했습니다")


@router.post("/blocks/{block_id}/line")
def post_line(block_id: str, text: str = Form(""), s: Session = Depends(get_session)):
    b, sec = _block_back(s, block_id)
    try:
        co.update_line(s, b, sec.week_id, text)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(block_id, err=f"{block_id}: {e}")
    return _issue_back(block_id, msg=f"{block_id} 이번 주 한 줄 저장")


@router.post("/blocks/{block_id}/transfer")
def post_transfer(block_id: str, to_dept: str = Form(""), s: Session = Depends(get_session)):
    b, sec = _block_back(s, block_id)
    try:
        dst = co.transfer(s, b, to_dept, sec.week_id)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(block_id, err=f"{block_id}: {e}")
    dname = s.get(m.Department, dst.department_id).name
    return _issue_back(block_id, msg=f"{block_id} 를 {dname} 로 이관했습니다 (ID 그대로)")


@router.post("/blocks/{block_id}/close-request")
def post_close_request(block_id: str, action_text: str = Form(""), s: Session = Depends(get_session)):
    b, sec = _block_back(s, block_id)
    try:
        cl.request(s, b, sec.week_id, action_text)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(block_id, err=str(e))
    return _issue_back(block_id,
                 msg=f"{block_id} 종결 요청 — 주간회의에서 승인·보류합니다")


# ── 표 붙이기 (이슈·문제점) ─────────────────────────────
@router.post("/blocks/{block_id}/tables")
def post_table_add(block_id: str, title: str = Form(""), text: str = Form(""), s: Session = Depends(get_session)):
    b, sec = _block_back(s, block_id)
    try:
        _, p = tb.add(s, b, title, text)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(block_id, err=f"{block_id}: {e}")
    return _issue_back(block_id,
                 msg=f"{block_id} 에 표를 붙였습니다 ({len(p.rows) - 1}행 × {len(p.rows[0])}열){tb.cut_note(p)}")


def _table_or_404(s: Session, block_id: str, table_id: int) -> m.BlockTable:
    t = s.get(m.BlockTable, table_id)
    if t is None or t.block_id != block_id:
        raise HTTPException(404, f"{block_id} 의 표 {table_id} 를 찾을 수 없습니다.")
    return t


@router.post("/blocks/{block_id}/tables/{table_id}/update")
def post_table_update(block_id: str, table_id: int, title: str = Form(""), text: str = Form(""),
                      s: Session = Depends(get_session)):
    _, sec = _block_back(s, block_id)
    try:
        p = tb.update(s, _table_or_404(s, block_id, table_id), title, text)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(block_id, err=f"{block_id}: {e}")
    return _issue_back(block_id, msg=f"{block_id} 표를 고쳤습니다{tb.cut_note(p)}")


@router.post("/blocks/{block_id}/tables/{table_id}/delete")
def post_table_delete(block_id: str, table_id: int, s: Session = Depends(get_session)):
    _, sec = _block_back(s, block_id)
    try:
        tb.delete(s, _table_or_404(s, block_id, table_id))
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(block_id, err=f"{block_id}: {e}")
    return _issue_back(block_id, msg=f"{block_id} 표를 지웠습니다")


@router.post("/tags/{tag_id}/confirm")
def post_tag_confirm(tag_id: int, s: Session = Depends(get_session)):
    t = s.get(m.BlockTag, tag_id)
    if t is None:
        raise HTTPException(404, "태그를 찾을 수 없습니다.")
    _, sec = _block_back(s, t.block_id)
    try:
        w.confirm_tag(s, t)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(t.block_id, err=str(e))
    return _issue_back(t.block_id, msg=f"태그 '{t.raw_text}' 확인")


@router.post("/tags/{tag_id}/unregistered")
def post_tag_unregistered(tag_id: int, s: Session = Depends(get_session)):
    t = s.get(m.BlockTag, tag_id)
    if t is None:
        raise HTTPException(404, "태그를 찾을 수 없습니다.")
    _, sec = _block_back(s, t.block_id)
    try:
        w.mark_unregistered(s, t)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(t.block_id, err=str(e))
    return _issue_back(t.block_id,
                 msg=f"'{t.raw_text}' 를 미등록으로 두었습니다 — 기준정보 담당자가 장비 허브의 미등록 표기 목록에서 봅니다")


@router.post("/tags/{tag_id}/dismiss")
def post_tag_dismiss(tag_id: int, s: Session = Depends(get_session)):
    t = s.get(m.BlockTag, tag_id)
    if t is None:
        raise HTTPException(404, "태그를 찾을 수 없습니다.")
    _, sec = _block_back(s, t.block_id)
    try:
        w.dismiss_tag(s, t)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(t.block_id, err=str(e))
    return _issue_back(t.block_id, msg=f"태그 '{t.raw_text}' 를 뺐습니다")


@router.post("/tags/{tag_id}/link")
def post_tag_link(tag_id: int, target_id: str = Form(""), s: Session = Depends(get_session)):
    t = s.get(m.BlockTag, tag_id)
    if t is None:
        raise HTTPException(404, "태그를 찾을 수 없습니다.")
    _, sec = _block_back(s, t.block_id)
    try:
        if not target_id:
            raise w.WriteError(f"'{t.raw_text}' 에 연결할 대상을 골라주세요.")
        w.link_tag(s, t, target_id)
        s.commit()
    except w.WriteError as e:
        s.rollback()
        return _issue_back(t.block_id, err=str(e))
    return _issue_back(t.block_id,
                 msg=f"'{t.raw_text}' → {target_id} 연결 · 별칭 사전에 추가했습니다")
