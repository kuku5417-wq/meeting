"""이슈 변경 기록(block_event) — 결정 ⑦(2026-11-13).

사실 칸을 어디서 고쳤든(이슈 작업대·부서 자료·공유회·팀장 정보회의) 이전 값·새 값·어디서를 덧붙인다.
덧붙이기만 한다 — **고치거나 지우지 않는다**. 자유 편집(15-2~15-5)·파생·합치기가 모두 이 표에 쌓인다.

15-6(2026-11-24)
  - 「사실로 채택」: 자료에서만 고쳐 둔 것을 나중에 이슈 사실로 올린다. 채택했다는 표시를 **행에 쓰지 않고**
    (덧붙이기만 하는 표다) 「지금 이슈 값과 다른 마지막 자료수정」을 기다리는 것으로 본다 — 사실이 같아지면 저절로 빠진다.
  - 「흐름」: 주차 × 단계(작업대 → 부서 → 공유회 → 팀장 → 회의)로 묶어 보여 준다. 사실 변경만 굵게.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m

KINDS = ("사실변경", "자료수정", "개체추가", "파생", "합치기")
STAGE_BY_MEETING = {"dept": "부서", "share": "공유회", "exec": "팀장"}
FIELD_LABEL = {"title": "제목", "body": "현상", "cause_text": "원인", "action_text": "조치·계획",
               "decision_needed": "결정 필요", "status": "상태", "block_type": "유형"}
LINK_RELATIONS = ("재발", "동일원인", "관련", "참고", "파생", "합쳐짐")   # block_link.relation 허용 값
STAGE_ORDER = ("작업대", "부서", "공유회", "팀장", "회의")
# 자유 편집 칸 이름(cause) → 이슈 사실 칸 이름(cause_text). 옛 기록이 자유 편집 이름으로 남아 있어 둘 다 받는다.
ATTR_BY_FIELD = {"cause": "cause_text", "act": "action_text", "dec": "decision_needed",
                 "body": "body", "title": "title", "status": "status"}
ADOPTABLE = ("title", "body", "cause_text", "action_text", "decision_needed")   # 「사실로 채택」할 수 있는 칸(고르는 칸·표현 제외)


def stage_of(s: Session, meeting_id: int | None) -> str:
    if not meeting_id:
        return "작업대"
    mt = s.get(m.Meeting, meeting_id)
    if mt is None:
        return "작업대"
    return STAGE_BY_MEETING.get(mt.kind, "회의")


def record(s: Session, block_id: str, kind: str, *, field: str = "", before: str = "", after: str = "",
           meeting_id: int | None = None, actor_id: str | None = None) -> m.BlockEvent:
    if kind not in KINDS:
        raise ValueError(f"모르는 기록 종류: {kind}")
    ev = m.BlockEvent(block_id=block_id, kind=kind, stage=stage_of(s, meeting_id),
                      meeting_id=meeting_id if meeting_id and s.get(m.Meeting, meeting_id) else None,
                      actor_id=actor_id, field=field, before=before or "", after=after or "")
    s.add(ev)
    s.flush()
    return ev


def recent(s: Session, block_id: str, n: int = 8) -> list[dict]:
    rows = s.scalars(select(m.BlockEvent).where(m.BlockEvent.block_id == block_id)
                     .order_by(m.BlockEvent.id.desc()).limit(n))
    return [{"when": e.created_at.strftime("%m/%d %H:%M"), "kind": e.kind, "stage": e.stage,
             "field": FIELD_LABEL.get(e.field, e.field), "before": e.before, "after": e.after} for e in rows]


def _attr(field: str) -> str:
    return ATTR_BY_FIELD.get(field, field)


def _norm(v: str) -> str:
    return " ".join(str(v or "").split())


def pending(s: Session, block_id: str) -> list[dict]:
    """「사실로 채택」을 기다리는 것 — 자료에서만 고쳐 둔 값이 지금 이슈 사실과 **아직 다른** 칸.

    칸마다 마지막 자료수정 하나만 본다(같은 칸을 여러 번 고쳤으면 마지막이 그 자료의 글이다).
    채택하거나 사람이 이슈를 그렇게 고치면 값이 같아져 저절로 빠진다 — 표에 표시를 쓰지 않는다.
    """
    b = s.get(m.Block, block_id)
    if b is None:
        return []
    last: dict[str, m.BlockEvent] = {}
    for e in s.scalars(select(m.BlockEvent).where(m.BlockEvent.block_id == block_id,
                                                  m.BlockEvent.kind == "자료수정").order_by(m.BlockEvent.id)):
        if _attr(e.field) in ADOPTABLE:
            last[_attr(e.field)] = e
    out = []
    for attr, e in last.items():
        now = str(getattr(b, attr, "") or "")
        if _norm(now) != _norm(e.after):
            mt = s.get(m.Meeting, e.meeting_id) if e.meeting_id else None
            out.append({"id": e.id, "field": attr, "label": FIELD_LABEL.get(attr, attr),
                        "issue_text": now, "deck_text": e.after, "where": (mt.title if mt else e.stage) or e.stage,
                        "when": e.created_at.strftime("%m/%d %H:%M")})
    return out


def adopt(s: Session, block_id: str, event_id: int) -> dict:
    """「사실로 채택」 — 그 자료수정 기록의 값을 이슈 사실 칸에 올린다(이때 「사실변경」이 남는다).

    1단계에는 로그인이 없어 누가 눌렀는지 적지 못한다 — 작성자·부서 편집자·기획이 쓰는 자리다(결정 ⑦ Q7).
    """
    from app.services import issues as iss
    from app.services import writing as w

    e = s.get(m.BlockEvent, int(event_id))
    if e is None or e.block_id != block_id:
        raise w.WriteError("그 기록을 찾을 수 없습니다. 화면을 새로 고친 뒤 다시 해주세요.")
    if e.kind != "자료수정":
        raise w.WriteError("자료에서 고친 기록만 사실로 채택합니다.")
    attr = _attr(e.field)
    if attr not in ADOPTABLE:
        raise w.WriteError(f"「{FIELD_LABEL.get(attr, attr)}」은(는) 사실로 채택하는 칸이 아닙니다.")
    b = s.get(m.Block, block_id)
    if b is None:
        raise w.WriteError("이슈를 찾을 수 없습니다.")
    before = str(getattr(b, attr, "") or "")
    if _norm(before) == _norm(e.after):
        raise w.WriteError("이미 이슈 사실과 같습니다 — 채택할 것이 없습니다.")
    iss.save_field(s, b, attr, e.after, meeting_id=e.meeting_id)
    return {"field": attr, "label": FIELD_LABEL.get(attr, attr), "before": before, "after": e.after}


def meeting_records(s: Session, block_id: str) -> list[dict]:
    """이슈에 쌓인 회의 기록(M12) — 코멘트·결정·지시. 주간 한 줄과 섞지 않고 따로 보인다."""
    out = []
    for c, mt in s.execute(select(m.MeetingComment, m.Meeting).join(m.Meeting, m.Meeting.id == m.MeetingComment.meeting_id)
                           .where(m.MeetingComment.block_id == block_id).order_by(m.MeetingComment.id)):
        out.append({"week": mt.week_id, "label": f"{mt.title or '회의'} {'결정' if c.kind == 'decision' else '코멘트'}", "text": c.text})
    for d, mt in s.execute(select(m.Directive, m.Meeting).join(m.Meeting, m.Meeting.id == m.Directive.meeting_id)
                           .where(m.Directive.block_id == block_id).order_by(m.Directive.id)):
        out.append({"week": mt.week_id, "label": f"{mt.title or '회의'} 지시({d.status})", "text": d.text + (f" — {d.done_note}" if d.done_note else "")})
    from app.services import importer as im
    out += im.records_for(s, block_id)
    return sorted(out, key=lambda x: x["week"])[-8:]


def _week_of(s: Session, e: m.BlockEvent) -> str:
    from app.services import weeks
    if e.meeting_id:
        mt = s.get(m.Meeting, e.meeting_id)
        if mt is not None:
            return mt.week_id
    return weeks.from_date(e.created_at.date()).id


def flow(s: Session, block_id: str, n_weeks: int = 6) -> list[dict]:
    """이슈 「흐름」 — 주차 × 단계로 묶은 한 줄들(결정 ⑦ 15-6).

    [{"week": "2026-W43", "stages": [{"stage": "부서", "rows": [{kind,label,before,after,text,fact,when}]}]}]
    사실이 바뀐 줄만 `fact` 가 참이다 — 화면에서 굵게 보여 준다.
    """
    by: dict[str, dict[str, list[dict]]] = {}

    def put(week: str, stage: str, row: dict) -> None:
        by.setdefault(week, {}).setdefault(stage, []).append(row)

    for e in s.scalars(select(m.BlockEvent).where(m.BlockEvent.block_id == block_id).order_by(m.BlockEvent.id)):
        attr = _attr(e.field)
        put(_week_of(s, e), e.stage or "작업대",
            {"kind": e.kind, "label": FIELD_LABEL.get(attr, attr), "before": e.before, "after": e.after,
             "text": "", "fact": e.kind == "사실변경", "when": e.created_at.strftime("%m/%d %H:%M")})
    for h in s.scalars(select(m.BlockHistory).where(m.BlockHistory.block_id == block_id).order_by(m.BlockHistory.id)):
        if (h.note or "").strip():
            put(h.week_id, "작업대", {"kind": "한 줄", "label": "", "before": "", "after": "",
                                     "text": h.note, "fact": False, "when": ""})
    for r in meeting_records(s, block_id):
        put(r["week"], "회의", {"kind": "회의", "label": r["label"], "before": "", "after": "",
                               "text": r["text"], "fact": False, "when": ""})

    order = {k: i for i, k in enumerate(STAGE_ORDER)}
    out = [{"week": wk, "stages": [{"stage": st, "rows": rows} for st, rows in
                                   sorted(by[wk].items(), key=lambda kv: order.get(kv[0], 9))]}
           for wk in sorted(by)]
    return out[-n_weeks:]


def changed_this_week(s: Session, week_id: str) -> list[dict]:
    """이번 주 바뀐 이슈 — 기획 홈(결정 ⑦ 15-6). 이슈마다 무엇이 몇 건 바뀌었나.

    합쳐진 이슈는 빼고(15-5), 바뀐 것이 없는 이슈도 뺀다.
    """
    from app.services import derive

    gone = derive.merged_ids(s)
    rows: dict[str, dict] = {}
    for e in s.scalars(select(m.BlockEvent).order_by(m.BlockEvent.id)):
        if e.block_id in gone or _week_of(s, e) != week_id:
            continue
        r = rows.setdefault(e.block_id, {"id": e.block_id, "fact": 0, "deck": 0, "split": 0, "merge": 0})
        if e.kind == "사실변경":
            r["fact"] += 1
        elif e.kind in ("자료수정", "개체추가"):
            r["deck"] += 1
        elif e.kind == "파생":
            r["split"] += 1
        elif e.kind == "합치기":
            r["merge"] += 1
    out = []
    for bid, r in rows.items():
        b = s.get(m.Block, bid)
        if b is None:
            continue
        out.append({**r, "title": b.title or bid, "dept": b.owner_department_id, "wait": len(pending(s, bid))})
    return sorted(out, key=lambda x: (-x["fact"] - x["deck"] - x["split"], x["id"]))
