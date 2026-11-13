"""회의 진행 · 종결 · 지시사항 — M12 (2026-10-23, F12·F13·F20, 최종 시안 design/mockups/v2m-meeting-run).

- 안건은 그 회의의 **최신 발행본**(meeting_version)이다. 발행 전이면 진행하지 않는다(「먼저 발행」 안내).
- 안건마다 「기록하고 다음」 한 번에 코멘트·결정·지시·종결 승인/보류를 남긴다. 기록은 이슈 쪽에 쌓인다:
  코멘트·결정 = meeting_comment(kind), 결정은 이슈의 「결정 필요」 칸을 비운다(ai_field_log 에 사람 값으로 남음),
  지시 = directive(다음 주 담당 부서 회의자료 맨 위), 종결 승인 = 사례 카드(promotion.approve).
- 이슈의 주간 한 줄(block_history)에는 회의 기록을 섞지 않는다 — 한 줄은 작성자가 쓰는 진행 상황이다.
- 종결 승인은 부서 현안 공유회에서만(원칙 7). 기획 주관자는 홈에서 언제든(같은 approve/hold).
- 확인 창 대신 되돌리기: 종결 승인·보류는 `undo_close` 로 되돌린다(사례 카드 삭제, 요청 상태로).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app import settings
from app.services import closure as cl
from app.services import promotion
from app.services import studio as st
from app.services import weeks
from app.services import writing as w

TEXT_MAX = 1000


class RunError(w.WriteError):
    """화면에 그대로 보여줄 한국어 사유."""


def next_week(week_id: str) -> str:
    return weeks.shift(week_id, 1).id


def published_deck(s: Session, mt: m.Meeting) -> dict:
    d = st.version_deck(st.latest_version(s, mt))
    if d is None:
        raise RunError("아직 발행하지 않은 회의입니다. 스튜디오에서 발행한 뒤 회의를 시작해주세요.")
    return d


def start(s: Session, mt: m.Meeting) -> None:
    """진행 화면을 처음 연 때 = 회의 시작."""
    if mt.held_at is None:
        mt.held_at = datetime.now()
        s.flush()


def _deck_ids(d: dict) -> set[str]:
    return set(st.deck_block_ids(d))


def records(s: Session, mt: m.Meeting, d: dict) -> dict[str, dict]:
    """이 회의에서 이슈마다 남긴 것 — 진행 화면의 ✓ 와 카드 채움에 쓴다."""
    out: dict[str, dict] = {}
    for bid in _deck_ids(d):
        out[bid] = {"comments": [], "decision": "", "directives": [], "close": "", "closure_id": None}
    for c in s.scalars(select(m.MeetingComment).where(m.MeetingComment.meeting_id == mt.id).order_by(m.MeetingComment.id)):
        r = out.get(c.block_id)
        if r is None:
            continue
        if c.kind == "decision":
            r["decision"] = c.text
        else:
            r["comments"].append(c.text)
    for dv in s.scalars(select(m.Directive).where(m.Directive.meeting_id == mt.id).order_by(m.Directive.id)):
        if dv.block_id in out:
            out[dv.block_id]["directives"].append(dv.text)
    for bid, r in out.items():
        c = s.scalar(select(m.Closure).where(m.Closure.block_id == bid).order_by(m.Closure.id.desc()).limit(1))
        if c is None:
            continue
        if c.decision == "대기":
            r["closure_id"] = c.id
        elif c.decided_week_id == mt.week_id:
            r["close"] = c.decision
    return out


def record(s: Session, mt: m.Meeting, block_id: str, comment: str = "", decision: str = "",
           directive: dict | None = None, close: str = "", cause: str = "") -> list[str]:
    """한 안건의 기록을 한 번에 — 남긴 것의 이름 목록(「코멘트」·「결정」·…)."""
    if mt.status == "종료":
        raise RunError("끝난 회의입니다. 기록을 더할 수 없습니다.")
    if close in ("ok", "hold") and mt.kind != "share":
        raise RunError("종결 승인·보류는 부서 현안 공유회에서 합니다(기획 주관자는 홈에서).")
    d = published_deck(s, mt)
    b = s.get(m.Block, block_id)
    if b is None or block_id not in _deck_ids(d):
        raise RunError("이 회의 안건이 아닌 이슈입니다. 화면을 새로 고쳐주세요.")
    done: list[str] = []
    comment, decision = (comment or "").strip(), (decision or "").strip()
    if len(comment) > TEXT_MAX or len(decision) > TEXT_MAX:
        raise RunError(f"코멘트·결정은 {TEXT_MAX}자 이내로 적어주세요.")
    if comment:
        s.add(m.MeetingComment(meeting_id=mt.id, block_id=b.id, text=comment, kind="comment"))
        done.append("코멘트")
    if decision:
        old = (b.decision_needed or "").strip()
        s.add(m.MeetingComment(meeting_id=mt.id, block_id=b.id, kind="decision",
                               text=decision + (f" (결정 필요였던 것: {old})" if old else "")))
        if old:
            w.update_block(s, b, "decision_needed", "")          # 결정하면 칸을 비운다 — 이전 값은 ai_field_log·회의 기록에
        done.append("결정")
    if directive and (directive.get("text") or "").strip():
        add_directive(s, mt, str(directive.get("text")), str(directive.get("dept_id") or b.owner_department_id),
                      str(directive.get("due") or next_week(mt.week_id)), b.id)
        done.append("지시")
    if close in ("ok", "hold"):
        c = cl.pending(s, b.id)
        if c is None:
            raise RunError(f"{b.id} 는 종결 요청이 없습니다.")
        if close == "ok":
            promotion.approve(s, c, mt.week_id, cause or b.cause_text or "")
            done.append("종결 승인")
        else:
            promotion.hold(s, c, mt.week_id, comment)
            done.append("보류")
    s.flush()
    return done


def undo_close(s: Session, block_id: str, week_id: str) -> None:
    """종결 승인·보류 되돌리기 — 요청 상태로 돌리고, 승인으로 만든 사례 카드는 지운다(그 주에 결정한 것만)."""
    c = s.scalar(select(m.Closure).where(m.Closure.block_id == block_id).order_by(m.Closure.id.desc()).limit(1))
    if c is None or c.decision == "대기" or c.decided_week_id != week_id:
        raise RunError("되돌릴 종결 결정이 없습니다.")
    b = s.get(m.Block, block_id)
    if c.decision == "승인":
        for card in s.scalars(select(m.CaseCard).where(m.CaseCard.block_id == block_id, m.CaseCard.approved_week_id == week_id)):
            s.delete(card)
    last = s.scalar(select(m.BlockHistory).where(m.BlockHistory.block_id == block_id, m.BlockHistory.week_id == week_id)
                    .order_by(m.BlockHistory.id.desc()).limit(1))
    if last is not None and (last.note or "").startswith(("회의 종결 승인", "회의 보류")):
        s.delete(last)
    c.decision, c.decided_week_id, c.decided_at = "대기", None, None
    b.status = "종결요청"
    s.flush()


def finish(s: Session, mt: m.Meeting) -> None:
    published_deck(s, mt)
    mt.status = "종료"
    s.flush()


# ── 지시사항 ────────────────────────────────────────────
def add_directive(s: Session, mt: m.Meeting, text: str, dept_id: str, due_week_id: str, block_id: str | None = None) -> m.Directive:
    text = (text or "").strip()
    if not text:
        raise RunError("지시 내용을 적어주세요.")
    if len(text) > 500:
        raise RunError("지시는 500자 이내로 적어주세요.")
    if s.get(m.Department, dept_id) is None:
        raise RunError("지시를 받을 부서를 골라주세요.")
    if weeks.parse(due_week_id) is None:
        raise RunError("기한 주차 형식이 맞지 않습니다. 2026-W44 처럼 적어주세요.")
    dv = m.Directive(meeting_id=mt.id, block_id=block_id, dept_id=dept_id, text=text, due_week_id=due_week_id)
    s.add(dv)
    s.flush()
    return dv


def complete_directive(s: Session, dv: m.Directive, note: str, week_id: str) -> None:
    note = (note or "").strip()
    if not note:
        raise RunError("완료 보고를 한 줄 적어주세요.")
    dv.status, dv.done_note, dv.done_week_id = "완료", note[:500], week_id
    s.flush()


def reopen_directive(s: Session, dv: m.Directive) -> None:
    dv.status, dv.done_note, dv.done_week_id = "열림", "", None
    s.flush()


def directive_json(s: Session, dv: m.Directive, week_id: str) -> dict:
    src = s.get(m.Meeting, dv.meeting_id)
    dept = s.get(m.Department, dv.dept_id)
    return {"id": dv.id, "text": dv.text, "dept_id": dv.dept_id, "dept": dept.name if dept else dv.dept_id, "due": dv.due_week_id,
            "late": dv.status == "열림" and dv.due_week_id < week_id, "status": dv.status, "done_note": dv.done_note,
            "block_id": dv.block_id or "", "src": src.title if src else ""}


def directives_for(s: Session, mt: m.Meeting) -> list[dict]:
    """회의자료 맨 위 「지난 지시사항」 — 부서 자료면 그 부서가 받은 것, 그 밖의 회의면 같은 갈래 지난 회의에서 나온 것.
    열린 것 + 이번 주에 완료한 것(완료 보고를 회의에서 보도록)."""
    q = select(m.Directive).where((m.Directive.status == "열림") | (m.Directive.done_week_id == mt.week_id))
    if mt.kind == "dept":
        q = q.where(m.Directive.dept_id == mt.owner_dept_id)
    else:
        earlier = select(m.Meeting.id).where(m.Meeting.kind == mt.kind, m.Meeting.week_id < mt.week_id)
        q = q.where(m.Directive.meeting_id.in_(earlier))
    return [directive_json(s, dv, mt.week_id) for dv in s.scalars(q.order_by(m.Directive.due_week_id, m.Directive.id))]


def open_directives(s: Session, dept_id: str, week_id: str) -> list[dict]:
    q = select(m.Directive).where(m.Directive.status == "열림", m.Directive.dept_id == dept_id).order_by(m.Directive.due_week_id, m.Directive.id)
    return [directive_json(s, dv, week_id) for dv in s.scalars(q)]


# ── 진행 화면 상태 ──────────────────────────────────────
def state(s: Session, mt: m.Meeting) -> dict:
    d = published_deck(s, mt)
    v = st.latest_version(s, mt)
    return {"deck": d, "meeting": {"id": mt.id, "title": mt.title, "kind": mt.kind, "status": mt.status, "week": mt.week_id,
                                   "version": v.version, "published_at": v.published_at.strftime("%m/%d %H:%M")},
            "records": records(s, mt, d), "can_close": mt.kind == "share", "next_week": next_week(mt.week_id),
            "depts": [{"id": x.id, "name": x.name} for x in s.scalars(select(m.Department).order_by(m.Department.order_no))],
            "long_weeks": settings.LONG_OPEN_WEEKS}
