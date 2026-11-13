"""회의 · 회의자료 스튜디오 — M10(2026-10-23) 시험, **M11(2026-10-23) 공식** (최종 시안 design/mockups/v2m-meetings · v2m-studio · v2m-meeting-view).

- 회의는 주차당 여러 개: 부서 자료(부서마다) · 부서 현안 공유회 · 팀장 정보회의 + 수시(호선별·리뷰).
  정기 회의는 처음 볼 때 자동으로 만든다(`ensure_week_meetings`, 중복 없음).
- 회의자료 = report_item 줄들. 회의용 한 줄·형태·머리표·순서는 **표현**이라 항목에만 남고, 사실(원인·조치·결정 필요)은 이슈에 바로 반영(issues.save_field).
- 요약 항목은 report_item_block 으로 이슈 여러 개를 잇는다. 풀면 이슈마다 한 장으로 돌아간다(이슈는 그대로).
- 부서 자료 시작: 지난주 이어받기(지난 부서 자료의 이슈 중 열린 것 + 새 초안) / 빈 자료. 고른 방식은 부서별로 다음에 기본값.
- **공유회는 부서 자료의 제출판을 참조로 모은다**(복사하지 않는다). 팀 스텝은 부서 순서·미제출 부서 「원장으로 채우기」만 하고,
  장 내용은 부서 자료에서 고친다. 종결 요청 이슈는 자동으로 들어간다(발행 전까지).
- **제출·발행은 판으로 고정한다**(meeting_version.snapshot_json). 사실 반영은 이슈와 발행 전 자료까지 — 발행본은 그대로 두고
  바뀐 장만 「변경」으로 보이며, 다시 발행하면 다음 판(docs/06 §2-1, docs/08).
- 화면·PPT·발행본이 같은 모양을 쓰도록 `deck()` 이 회의자료 전체를 사전 하나로 만든다.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m
from app import settings
from app.services import carry_over as co
from app.services import central
from app.services import weeks
from app.services import writing as w

KINDS = {"dept": "부서 회의자료", "share": "부서 현안 공유회", "exec": "팀장 정보회의", "hull": "호선별 회의", "review": "문제점·장비 리뷰"}
EDITABLE = ("dept", "share", "exec", "hull", "review")   # M11: 모든 갈래를 스튜디오에서 고친다
PUBLISHES = ("share", "exec", "hull", "review")           # 발행하는 갈래(부서 자료는 「제출」)
FORMS = {"detail": "상세 한 장", "card": "카드", "photo": "사진 강조", "line": "한 줄"}
DEFAULT_FORM = {"dept": "card", "share": "card", "exec": "line", "hull": "photo", "review": "card"}
LINE_MAX = 300
FACTS = {"title": "제목", "status": "상태", "body": "현상", "cause": "원인", "act": "조치", "dec": "결정 필요"}   # 발행 뒤 「변경」을 보는 칸


class StudioError(w.WriteError):
    """화면에 그대로 보여줄 한국어 사유."""


# ── 회의 ────────────────────────────────────────────────
def ensure_week_meetings(s: Session, week_id: str) -> None:
    """정기 회의 — 부서 자료(부서마다) · 공유회 · 팀장 정보회의. 이미 있으면 두고, 제목이 비면 채운다."""
    w.ensure_week(s, weeks.from_id(week_id))
    have = list(s.scalars(select(m.Meeting).where(m.Meeting.week_id == week_id)))
    def has(kind: str, dept: str | None = None) -> m.Meeting | None:
        return next((x for x in have if x.kind == kind and (dept is None or x.owner_dept_id == dept)), None)
    for d in s.scalars(select(m.Department).order_by(m.Department.order_no)):
        if has("dept", d.id) is None:
            s.add(m.Meeting(week_id=week_id, kind="dept", owner_dept_id=d.id, title=f"{week_id[-3:]} {d.name} 회의자료"))
    sh = has("share")
    if sh is None:
        s.add(m.Meeting(week_id=week_id, kind="share", title=f"{week_id[-3:]} 부서 현안 공유회"))
    elif not sh.title:
        sh.title = f"{week_id[-3:]} 부서 현안 공유회"
    if has("exec") is None:
        s.add(m.Meeting(week_id=week_id, kind="exec", title=f"{week_id[-3:]} 팀장 정보회의"))
    for d in s.scalars(select(m.Department)):          # 열린 이슈를 이번 주로 이어 둔다(신규 → 진행, 메모 업데이트 맞추기) — M13: 옛 작성 화면이 하던 일
        co.carry_over(s, week_id, d.id)
    s.flush()


def week_meetings(s: Session, week_id: str) -> list[m.Meeting]:
    order = {"dept": 0, "share": 1, "exec": 2, "hull": 3, "review": 4}
    dept_order = {d.id: d.order_no for d in s.scalars(select(m.Department))}
    xs = list(s.scalars(select(m.Meeting).where(m.Meeting.week_id == week_id)))
    return sorted(xs, key=lambda x: (order.get(x.kind, 9), dept_order.get(x.owner_dept_id or "", 0), x.id))


def past_meetings(s: Session, week_id: str, limit: int = 12) -> list[m.Meeting]:
    return list(s.scalars(select(m.Meeting).where(m.Meeting.week_id < week_id, m.Meeting.kind != "dept")
                          .order_by(m.Meeting.week_id.desc(), m.Meeting.id).limit(limit)))


def week_meeting(s: Session, week_id: str, kind: str, dept_id: str | None = None) -> m.Meeting | None:
    q = select(m.Meeting).where(m.Meeting.week_id == week_id, m.Meeting.kind == kind)
    if dept_id is not None:
        q = q.where(m.Meeting.owner_dept_id == dept_id)
    return s.scalar(q.order_by(m.Meeting.id).limit(1))


def create_adhoc(s: Session, week_id: str, kind: str, hull_id: str = "", held_on: date | None = None) -> m.Meeting:
    """수시 회의 — 호선별(호선 필수)·리뷰."""
    if kind not in ("hull", "review"):
        raise StudioError("수시 회의는 호선별 회의 또는 문제점·장비 리뷰만 만들 수 있습니다.")
    if kind == "hull" and not hull_id:
        raise StudioError("호선별 회의는 호선을 골라주세요.")
    w.ensure_week(s, weeks.from_id(week_id))
    title = f"{hull_id} 호선별 회의" if kind == "hull" else f"{week_id[-3:]} 문제점·장비 리뷰"
    mt = m.Meeting(week_id=week_id, kind=kind, title=title, hull_id=hull_id or None, held_on=held_on)
    s.add(mt)
    s.flush()
    return mt


def items(s: Session, mt: m.Meeting) -> list[m.ReportItem]:
    """이 회의가 직접 가진 장(공유회면 종결 요청·원장 채움 장만 — 부서 장은 참조라 여기 없다)."""
    return list(s.scalars(select(m.ReportItem).where(m.ReportItem.meeting_id == mt.id).order_by(m.ReportItem.order_no, m.ReportItem.id)))


def item_ids(s: Session, it: m.ReportItem) -> list[str]:
    """그 장이 잇는 이슈 ID — 요약이면 여럿."""
    if it.kind == "summary":
        return list(s.scalars(select(m.ReportItemBlock.block_id).where(m.ReportItemBlock.item_id == it.id).order_by(m.ReportItemBlock.order_no)))
    return [it.block_id] if it.block_id else []


def _require_editable(mt: m.Meeting) -> None:
    if mt.kind not in EDITABLE:
        raise StudioError("이 회의는 스튜디오에서 고치지 않습니다.")
    if mt.status == "종료":
        raise StudioError("끝난 회의의 자료는 고칠 수 없습니다.")


def _touched(mt: m.Meeting) -> None:
    """제출·발행한 뒤 고치면 「수정됨」 — 다시 제출·발행하면 판이 오른다(이미 나간 판은 그대로)."""
    if mt.status in ("제출", "발행"):
        mt.status = "수정됨"


def prev_dept_meeting(s: Session, mt: m.Meeting) -> m.Meeting | None:
    return s.scalar(select(m.Meeting).where(m.Meeting.kind == "dept", m.Meeting.owner_dept_id == mt.owner_dept_id,
                                            m.Meeting.week_id < mt.week_id).order_by(m.Meeting.week_id.desc()).limit(1))


def suggested_start(s: Session, mt: m.Meeting) -> str:
    """부서별로 지난번에 고른 시작 방식(없으면 이어받기)."""
    last = s.scalar(select(m.Meeting.start_mode).where(m.Meeting.kind == "dept", m.Meeting.owner_dept_id == mt.owner_dept_id,
                                                       m.Meeting.start_mode.is_not(None), m.Meeting.id != mt.id)
                    .order_by(m.Meeting.week_id.desc()).limit(1))
    return last or "carry"


# ── 판(제출·발행) ───────────────────────────────────────
def latest_version(s: Session, mt: m.Meeting | None) -> m.MeetingVersion | None:
    if mt is None:
        return None
    return s.scalar(select(m.MeetingVersion).where(m.MeetingVersion.meeting_id == mt.id).order_by(m.MeetingVersion.version.desc()).limit(1))


def version_deck(v: m.MeetingVersion | None) -> dict | None:
    return json.loads(v.snapshot_json) if v is not None else None


def deck_block_ids(d: dict) -> list[str]:
    return [b["id"] for sec in d["sections"] for it in sec["items"] for b in it["blocks"]]


# ── 공유회 부서 칸 ──────────────────────────────────────
def dept_order(s: Session, mt: m.Meeting) -> list[m.Department]:
    """공유회 부서 순서 — 팀 스텝이 바꾼 순서(order_json), 없으면 기준정보 순서. 새로 생긴 부서는 뒤에."""
    depts = list(s.scalars(select(m.Department).order_by(m.Department.order_no)))
    try:
        saved = [x for x in json.loads(mt.order_json or "[]") if isinstance(x, str)]
    except ValueError:  # noqa: PERF203 — 손상된 순서는 기준정보 순서로
        saved = []
    by = {d.id: d for d in depts}
    out = [by[x] for x in saved if x in by]
    return out + [d for d in depts if d not in out]


def move_dept(s: Session, mt: m.Meeting, dept_id: str, step: int) -> None:
    _require_editable(mt)
    if mt.kind != "share":
        raise StudioError("부서 순서는 부서 현안 공유회에서만 바꿉니다.")
    ids = [d.id for d in dept_order(s, mt)]
    if dept_id not in ids:
        raise StudioError("없는 부서입니다. 화면을 새로 고쳐주세요.")
    i = ids.index(dept_id)
    j = max(0, min(len(ids) - 1, i + (1 if step > 0 else -1)))
    ids[i], ids[j] = ids[j], ids[i]
    mt.order_json = json.dumps(ids)
    _touched(mt)
    s.flush()


def _submitted(s: Session, mt: m.Meeting, dept_id: str) -> tuple[m.Meeting | None, m.MeetingVersion | None]:
    dm = week_meeting(s, mt.week_id, "dept", dept_id)
    return dm, latest_version(s, dm)


def sync_share(s: Session, mt: m.Meeting) -> int:
    """종결 요청 이슈를 공유회에 자동으로 넣는다(발행·종료 뒤에는 그대로). 넣은 수."""
    if mt.kind != "share" or mt.status in ("발행", "종료"):
        return 0
    have = set(deck_block_ids(deck(s, mt)))
    n = 0
    for b in s.scalars(select(m.Block).where(m.Block.status == "종결요청", m.Block.block_type.in_(w.TRACKED)).order_by(m.Block.id)):
        if b.id in have:
            continue
        s.add(m.ReportItem(meeting_id=mt.id, kind="single", block_id=b.id, line=_default_line(s, b), form="card",
                           order_no=_next_order(s, mt), src="종결 요청", dept_id=b.owner_department_id))
        n += 1
    if n:
        s.flush()
    return n


def fill_from_ledger(s: Session, mt: m.Meeting, dept_id: str) -> int:
    """제출하지 않은 부서 — 그 부서의 열린 이슈를 한 줄로 채운다(제출 마감이 지나도 회의가 빠지지 않게)."""
    _require_editable(mt)
    if mt.kind != "share":
        raise StudioError("원장으로 채우기는 부서 현안 공유회에서만 합니다.")
    dm, v = _submitted(s, mt, dept_id)
    if v is not None:
        raise StudioError("이미 제출한 부서입니다. 고칠 것은 그 부서 자료에서 고쳐주세요.")
    have = set(deck_block_ids(deck(s, mt)))
    n = 0
    for b in s.scalars(select(m.Block).where(m.Block.owner_department_id == dept_id, m.Block.block_type.in_(w.TRACKED),
                                             m.Block.status.in_(("신규", "진행", "종결요청"))).order_by(m.Block.id)):
        if b.id in have:
            continue
        s.add(m.ReportItem(meeting_id=mt.id, kind="single", block_id=b.id, line=_default_line(s, b), form="line",
                           order_no=_next_order(s, mt), src="원장 채움", dept_id=dept_id))
        n += 1
    if not n:
        raise StudioError("넣을 열린 이슈가 없습니다. 그 부서 원장에 진행 중인 이슈가 없으면 빈 칸으로 둬도 됩니다.")
    _touched(mt)
    s.flush()
    return n


# ── 후보 ────────────────────────────────────────────────
def _open(b: m.Block) -> bool:
    return b.block_type in w.TRACKED and b.status not in ("종결",)


def _used(s: Session, mt: m.Meeting) -> set[str]:
    if mt.kind == "share":
        return set(deck_block_ids(deck(s, mt)))
    return {bid for it in items(s, mt) for bid in item_ids(s, it)}


def candidates(s: Session, mt: m.Meeting) -> list[tuple[str, list[m.Block]]]:
    """갈래별 후보 묶음 — 이미 들어간 이슈는 뺀다."""
    used = _used(s, mt)
    from app.services import alerts as al          # 순환 import 회피
    if mt.kind in ("dept", "share", "hull"):        # F21 「일정 임박」 묶음을 맨 앞에 — 그 부서·호선 것만
        soon = [b for b, _ in al.due_blocks(s, mt.owner_dept_id if mt.kind == "dept" else None, mt.hull_id if mt.kind == "hull" else None)
                if b.id not in used]
        used = used | {b.id for b in soon}
        rest = _candidates(s, mt, used)
        return ([("일정 임박 — ~전 해결 목표가 가까움", soon)] if soon else []) + rest
    return _candidates(s, mt, used)


def _candidates(s: Session, mt: m.Meeting, used: set[str]) -> list[tuple[str, list[m.Block]]]:
    if mt.kind == "dept":
        pool = [b for b in s.scalars(select(m.Block).where(m.Block.owner_department_id == mt.owner_dept_id).order_by(m.Block.id)) if _open(b) and b.id not in used]
        prev = prev_dept_meeting(s, mt)
        last = {bid for it in items(s, prev) for bid in item_ids(s, it)} if prev else set()
        return [("새 초안 — 초안 완료", [b for b in pool if b.draft_state == "ok" and b.id not in last]),
                ("지난주 자료에 있던 것", [b for b in pool if b.id in last]),
                ("초안 작성 중 — 넣으면 경고만", [b for b in pool if b.draft_state != "ok" and b.id not in last])]
    if mt.kind == "hull":
        pool = [b for b in s.scalars(select(m.Block).order_by(m.Block.id)) if _open(b) and b.id not in used and w.block_hull(s, b.id) == mt.hull_id]
        return [(f"{mt.hull_id} 열린 이슈", pool)]
    if mt.kind == "review":
        pool = [b for b in s.scalars(select(m.Block).where(m.Block.block_type == "problem").order_by(m.Block.id)) if _open(b) and b.id not in used]
        return [("열린 문제점", pool)]
    if mt.kind == "share":
        pool = [b for b in s.scalars(select(m.Block).where(m.Block.block_type.in_(w.TRACKED)).order_by(m.Block.id)) if _open(b) and b.id not in used]
        return [("원장 직접 — 부서 자료에 없는 열린 이슈", pool)]
    if mt.kind == "exec":
        return exec_candidates(s, mt, used)
    return []


def exec_candidates(s: Session, mt: m.Meeting, used: set[str]) -> list[tuple[str, list[m.Block]]]:
    """팀장 정보회의 후보 — 공유회에 실린 것 · 중요 표시 · 장기 미결 · 이번 주 종결 · 원장 직접(앞 묶음에 나온 것은 뒤에서 뺀다)."""
    seen = set(used)
    def take(bs) -> list[m.Block]:
        out = [b for b in bs if b is not None and b.id not in seen]
        seen.update(b.id for b in out)
        return out
    sh = week_meeting(s, mt.week_id, "share")
    v = latest_version(s, sh)
    share_ids = deck_block_ids(version_deck(v)) if v else (deck_block_ids(deck(s, sh)) if sh else [])
    label = f"공유회 자료(발행 {v.version}판)" if v else "공유회 자료(발행 전)"
    open_ = [b for b in s.scalars(select(m.Block).where(m.Block.block_type.in_(w.TRACKED)).order_by(m.Block.id)) if _open(b)]
    closed = [s.get(m.Block, c.block_id) for c in s.scalars(select(m.Closure).where(
        m.Closure.decision == "승인", m.Closure.decided_week_id == mt.week_id).order_by(m.Closure.id))]
    return [(label, take(s.get(m.Block, x) for x in dict.fromkeys(share_ids))),
            ("중요 표시", take(b for b in open_ if b.important)),
            ("장기 미결", take(b for b in open_ if co.long_open(s, b, mt.week_id))),
            ("이번 주 종결", take(closed)),
            ("원장 직접", take(open_))]


# ── 장 넣기·고치기·빼기 ────────────────────────────────────
def _default_line(s: Session, b: m.Block) -> str:
    rows = [r for r in co.history(s, b.id) if (r.note or "").strip()]
    return (rows[-1].note if rows else b.title)[:LINE_MAX]


def _next_order(s: Session, mt: m.Meeting) -> int:
    return (s.scalar(select(func.max(m.ReportItem.order_no)).where(m.ReportItem.meeting_id == mt.id)) or 0) + 10


def add_item(s: Session, mt: m.Meeting, block_id: str, src: str = "원장") -> m.ReportItem:
    _require_editable(mt)
    b = s.get(m.Block, block_id)
    if b is None:
        raise StudioError(f"{block_id}: 없는 이슈입니다.")
    if block_id in _used(s, mt):
        raise StudioError(f"{block_id} 는 이미 이 회의자료에 있습니다.")
    form = "detail" if b.decision_needed and mt.kind != "exec" else DEFAULT_FORM.get(mt.kind, "card")
    it = m.ReportItem(meeting_id=mt.id, kind="single", block_id=b.id, line=_default_line(s, b), form=form,
                      order_no=_next_order(s, mt), src=src, dept_id=b.owner_department_id if mt.kind == "share" else None)
    s.add(it)
    _touched(mt)
    s.flush()
    return it


def start(s: Session, mt: m.Meeting, mode: str) -> list[m.ReportItem]:
    """부서 자료 시작 — carry 지난주 이어받기(지난 자료의 열린 이슈 + 새 초안) / blank 빈 자료."""
    _require_editable(mt)
    if mt.kind != "dept":
        raise StudioError("시작 방식은 부서 회의자료에서만 고릅니다.")
    if items(s, mt):
        raise StudioError("이미 장이 있습니다. 시작 방식은 빈 자료일 때만 고릅니다.")
    if mode not in ("carry", "blank"):
        raise StudioError("시작 방식을 골라주세요.")
    mt.start_mode = mode
    out = []
    if mode == "carry":
        groups = dict(candidates(s, mt))
        for b in groups.get("지난주 자료에 있던 것", []):
            out.append(add_item(s, mt, b.id, "지난주"))
        for b in groups.get("새 초안 — 초안 완료", []):
            out.append(add_item(s, mt, b.id, "새 초안"))
    s.flush()
    return out


def update_item(s: Session, it: m.ReportItem, field: str, value) -> None:
    mt = s.get(m.Meeting, it.meeting_id)
    _require_editable(mt)
    if field == "line":
        value = str(value or "").strip()
        if len(value) > LINE_MAX:
            raise StudioError(f"회의용 한 줄은 {LINE_MAX}자 이내로 적어주세요.")
        it.line = value
    elif field == "form":
        if value not in FORMS:
            raise StudioError("형태는 상세 한 장·카드·사진 강조·한 줄 중에서 골라주세요.")
        it.form = value
    elif field == "tag_on":
        it.tag_on = bool(value)
    else:
        raise StudioError(f"고칠 수 없는 항목입니다: {field}")
    _touched(mt)
    s.flush()


def reorder(s: Session, mt: m.Meeting, ids: list[int]) -> None:
    _require_editable(mt)
    if mt.kind == "share":
        raise StudioError("공유회는 부서 순서만 바꿉니다. 장 순서는 그 부서 자료에서 바꿔주세요.")
    mine = {it.id: it for it in items(s, mt)}
    if set(ids) != set(mine):
        raise StudioError("장 목록이 바뀌었습니다. 화면을 새로 고친 뒤 다시 옮겨주세요.")
    for n, iid in enumerate(ids):
        mine[iid].order_no = (n + 1) * 10
    _touched(mt)
    s.flush()


def snapshot(s: Session, it: m.ReportItem) -> dict:
    return {"kind": it.kind, "block_id": it.block_id, "line": it.line, "tag_on": it.tag_on, "form": it.form,
            "order_no": it.order_no, "src": it.src, "dept_id": it.dept_id, "ids": item_ids(s, it)}


def _drop_links(s: Session, it: m.ReportItem) -> None:
    """요약 연결 행을 먼저 지우고 flush — 관계 정의가 없어 한 번에 지우면 FK 순서가 꼬인다."""
    for rb in s.scalars(select(m.ReportItemBlock).where(m.ReportItemBlock.item_id == it.id)):
        s.delete(rb)
    s.flush()


def remove_item(s: Session, it: m.ReportItem) -> dict:
    """장 빼기 — 되돌리기용 스냅숏을 돌려준다(이슈는 그대로)."""
    mt = s.get(m.Meeting, it.meeting_id)
    _require_editable(mt)
    snap = snapshot(s, it)
    _drop_links(s, it)
    s.delete(it)
    _touched(mt)
    s.flush()
    return snap


def restore(s: Session, mt: m.Meeting, snap: dict) -> m.ReportItem:
    _require_editable(mt)
    it = m.ReportItem(meeting_id=mt.id, kind=snap.get("kind", "single"), block_id=snap.get("block_id"), line=snap.get("line", ""),
                      tag_on=bool(snap.get("tag_on", True)), form=snap.get("form", "card"), order_no=int(snap.get("order_no", _next_order(s, mt))),
                      src=snap.get("src", ""), dept_id=snap.get("dept_id"))
    s.add(it)
    s.flush()
    if it.kind == "summary":
        for n, bid in enumerate(snap.get("ids", [])):
            s.add(m.ReportItemBlock(item_id=it.id, block_id=bid, order_no=n))
    _touched(mt)
    s.flush()
    return it


def add_metric_item(s: Session, mt: m.Meeting) -> m.ReportItem:
    """부서 회의자료에 「지표 요약」 장(F16) — 그 부서의 주간 지표·기간 표. 하나만."""
    _require_editable(mt)
    if mt.kind != "dept":
        raise StudioError("지표 요약 장은 부서 회의자료에 넣습니다(공유회에는 제출판으로 실린다).")
    if any(it.kind == "metric" for it in items(s, mt)):
        raise StudioError("이미 지표 요약 장이 있습니다.")
    it = m.ReportItem(meeting_id=mt.id, kind="metric", form="card", tag_on=False, line="이번 주 지표", order_no=_next_order(s, mt),
                      src="지표", dept_id=mt.owner_dept_id)
    s.add(it)
    _touched(mt)
    s.flush()
    return it


def add_table_item(s: Session, mt: m.Meeting, table_id: int) -> m.ReportItem:
    """부서 회의자료에 「기간 표」 장 — 그 주 날짜별 계획/실적과 기간 합계·차이 사유. 표마다 한 장."""
    _require_editable(mt)
    if mt.kind != "dept":
        raise StudioError("기간 표 장은 부서 회의자료에 넣습니다(공유회에는 제출판으로 실린다).")
    t = s.get(m.MetricTable, table_id)
    if t is None or t.department_id != mt.owner_dept_id:
        raise StudioError("이 부서의 기간 표가 아닙니다 — 지표 화면에서 표를 먼저 만들어주세요.")
    if any(it.kind == "table" and it.table_id == t.id for it in items(s, mt)):
        raise StudioError(f"'{t.name}' 기간 표 장이 이미 있습니다.")
    it = m.ReportItem(meeting_id=mt.id, kind="table", form="card", tag_on=False, line=t.name, order_no=_next_order(s, mt),
                      src="기간 표", dept_id=mt.owner_dept_id, table_id=t.id)
    s.add(it)
    _touched(mt)
    s.flush()
    return it


def summarize(s: Session, mt: m.Meeting, item_ids_: list[int]) -> m.ReportItem:
    """여러 장 → 요약 한 장. 원래 장들은 빠지고, 이슈들은 report_item_block 으로 이어진다(이슈는 그대로)."""
    _require_editable(mt)
    picked = [it for it in items(s, mt) if it.id in set(item_ids_) and it.kind in ("single", "summary")]
    if len(picked) < 2:
        raise StudioError("요약하려면 장을 두 개 이상 골라주세요.")
    ids = [bid for it in picked for bid in item_ids(s, it)]
    hulls = sorted({h for h in (w.block_hull(s, b) for b in ids) if h})
    summ = m.ReportItem(meeting_id=mt.id, kind="summary", block_id=ids[0], form="card", tag_on=False, order_no=picked[0].order_no,
                        line=f"{len(ids)}건 묶음 — {'·'.join(hulls) or '여러 호선'} 같은 원인 검토", src=f"요약 · 이슈 {len(ids)}개",
                        dept_id=picked[0].dept_id)
    for it in picked:
        _drop_links(s, it)
        s.delete(it)
    s.add(summ)
    s.flush()
    for n, bid in enumerate(ids):
        s.add(m.ReportItemBlock(item_id=summ.id, block_id=bid, order_no=n))
    _touched(mt)
    s.flush()
    return summ


def unsummarize(s: Session, it: m.ReportItem) -> list[m.ReportItem]:
    mt = s.get(m.Meeting, it.meeting_id)
    _require_editable(mt)
    if it.kind != "summary":
        raise StudioError("요약 장이 아닙니다.")
    ids, base, dept = item_ids(s, it), it.order_no, it.dept_id
    _drop_links(s, it)
    s.delete(it)
    s.flush()
    out = []
    for n, bid in enumerate(ids):
        b = s.get(m.Block, bid)
        x = m.ReportItem(meeting_id=mt.id, kind="single", block_id=bid, line=_default_line(s, b), form=DEFAULT_FORM.get(mt.kind, "card"),
                         order_no=base + n, src="요약에서 풂", dept_id=dept)
        s.add(x)
        out.append(x)
    _touched(mt)
    s.flush()
    return out


def _freeze(s: Session, mt: m.Meeting, status: str) -> m.MeetingVersion:
    if mt.status == status and latest_version(s, mt) is not None and not changes(s, mt):
        raise StudioError(f"이미 {status}한 {mt.version}판과 같습니다. 고친 것이 생기면 다시 {status}해주세요.")
    mt.version = (mt.version or 0) + 1
    mt.status = status
    d = deck(s, mt)
    d["meeting"].update(status=status, version=mt.version)
    v = m.MeetingVersion(meeting_id=mt.id, version=mt.version, published_at=datetime.now(), snapshot_json=json.dumps(d, ensure_ascii=False, default=str))
    s.add(v)
    s.flush()
    return v


def submit(s: Session, mt: m.Meeting) -> m.MeetingVersion:
    """부서 자료 제출 — 판으로 고정해 공유회가 참조한다. 다시 제출하면 판이 오른다."""
    _require_editable(mt)
    if mt.kind != "dept":
        raise StudioError("제출은 부서 회의자료에서 합니다. 이 회의는 「발행」을 눌러주세요.")
    if not items(s, mt):
        raise StudioError("장이 없습니다. 후보에서 이슈를 넣은 뒤 제출해주세요.")
    return _freeze(s, mt, "제출")


def publish(s: Session, mt: m.Meeting) -> m.MeetingVersion:
    """발행 — 그 시점 장·사실 전체를 판으로 고정. 막지 않는다(미제출 부서는 표지에 남는다). 다시 발행하면 다음 판."""
    _require_editable(mt)
    if mt.kind not in PUBLISHES:
        raise StudioError("부서 회의자료는 「제출」합니다.")
    sync_share(s, mt)
    if not deck_block_ids(deck(s, mt)):
        raise StudioError("장이 없습니다. 후보에서 이슈를 넣거나 부서 제출을 기다린 뒤 발행해주세요.")
    return _freeze(s, mt, "발행")


def changes(s: Session, mt: m.Meeting) -> list[dict]:
    """마지막 판 이후 이슈 사실이 바뀐 장 — [{block_id, title, fields}]. 판이 없으면 빈 목록."""
    snap = version_deck(latest_version(s, mt))
    if snap is None:
        return []
    names = _dept_names(s)
    out, seen = [], set()
    for sec in snap["sections"]:
        for it in sec["items"]:
            for old in it["blocks"]:
                if old["id"] in seen:
                    continue
                seen.add(old["id"])
                b = s.get(m.Block, old["id"])
                if b is None:
                    continue
                new = _block_json(s, b, snap["meeting"]["week"], names)
                diff = [label for k, label in FACTS.items() if (old.get(k) or "") != (new.get(k) or "")]
                if diff:
                    out.append({"block_id": b.id, "title": b.title, "fields": diff})
    return out


def published_blocks(s: Session, week_id: str) -> dict[str, list[str]] | None:
    """공유회 최신 발행본의 부서별 안건(이슈 ID 순서) — 옛 회의 진행 화면이 M12 까지 읽는다. 발행 전이면 None."""
    sh = week_meeting(s, week_id, "share")
    v = latest_version(s, sh)
    if v is None:
        return None
    out: dict[str, list[str]] = {}
    for sec in version_deck(v)["sections"]:
        ids = out.setdefault(sec.get("dept_id") or "", [])
        for it in sec["items"]:
            ids += [b["id"] for b in it["blocks"] if b["id"] not in ids]
    return out


# ── 회의자료 전체(화면·PPT·발행본 공통) ─────────────────
def ptag(s: Session, b: m.Block, week_id: str) -> str:
    """회의용 한 줄 머리표 — 종결 > 종결 요청 > 결정필요(+n주 미결) > 장기 미결 > 공유."""
    lo = co.long_open(s, b, week_id)
    long_ = f"{lo}주 미결" if lo else ""
    if b.status == "종결":
        return "종결"
    if b.status == "종결요청":
        return "종결승인 대기"
    from app.services import alerts as al          # 순환 import 회피
    st = al.state(s, b)
    alert = st["chip"] if st and st["level"] in al.LEVELS else ""
    if st and st["level"] == "기한 지남":
        return alert
    if (b.decision_needed or "").strip():
        return " · ".join(x for x in ("결정필요", alert or long_) if x)
    if alert:
        return alert
    if long_:
        return long_
    if b.block_type == "share":
        return "공유"
    return ""


def _dept_names(s: Session) -> dict[str, str]:
    return {d.id: d.name for d in s.scalars(select(m.Department))}


def _block_json(s: Session, b: m.Block, week_id: str, dept_names: dict) -> dict:
    from app.services import photos as ph          # 순환 import 회피(photos 가 writing 을 쓴다)
    hull = w.block_hull(s, b.id)
    br = central.hull_brief(hull) if hull else None
    nx = br["next"] if br else None
    pics = [p.id for lk, p in ph.block_photos(s, b.id) if lk.role in ("main", "after")][:1] or [p.id for _, p in ph.block_photos(s, b.id)][:1]
    return {"id": b.id, "type": b.block_type, "title": b.title, "status": b.status, "dept": dept_names.get(b.owner_department_id, b.owner_department_id),
            "hull": hull or "", "ev": f"{nx['code']} {nx['date'].strftime('%m/%d')}" if nx else "", "dd": br["dday"] if br and nx else None,
            "body": b.body or "", "cause": b.cause_text or "", "act": b.action_text or "", "dec": b.decision_needed or "",
            "draft": b.draft_state, "ptag": ptag(s, b, week_id), "photo": pics[0] if pics else ""}


def metric_json(s: Session, dept_id: str, week_id: str, names: dict) -> dict:
    """「지표 요약」 장의 내용 — 주간 지표(이탈·코멘트 먼저) + 그 주에 걸친 기간 표 합계. 발행·제출판에 그대로 고정된다."""
    from app.services import metrics as mt          # 순환 import 회피
    wk = weeks.from_id(week_id)
    tabs = []
    for t in mt.tables(s, dept_id):
        if t.end_date < wk.start or t.start_date > wk.end + timedelta(days=2):
            continue
        tv = mt.table_view(s, t)
        tabs.append({"name": t.name, "unit": t.unit, "period": f"{t.start_date:%m/%d}–{t.end_date:%m/%d}", "plan": tv["plan"], "actual": tv["actual"],
                     "rows": [{"name": r["name"], "plan": r["plan"], "actual": r["actual"], "diff": r["diff"], "note": r["note"]} for r in tv["rows"]]})
    return {"dept": names.get(dept_id, dept_id), "dept_id": dept_id, "metrics": mt.summary(s, dept_id, week_id), "tables": tabs}


_WD = "월화수목금토일"


def table_json(s: Session, t: m.MetricTable, week_id: str, names: dict) -> dict:
    """「기간 표」 장의 내용 — 그 주(월~일)에 걸친 날짜의 계획/실적 + 기간 전체 합계·차이·사유. 그 주 날짜가 없으면 기간 끝 7일."""
    from app.services import metrics as mtx          # 순환 import 회피
    wk = weeks.from_id(week_id)
    tv = mtx.table_view(s, t)
    ds = tv["days"]
    idx = [i for i, d in enumerate(ds) if wk.start <= d <= wk.start + timedelta(days=6)] or list(range(max(0, len(ds) - 7), len(ds)))
    return {"dept": names.get(t.department_id, t.department_id), "dept_id": t.department_id, "table_id": t.id, "name": t.name,
            "unit": t.unit, "period": f"{t.start_date:%m/%d}–{t.end_date:%m/%d}", "plan": tv["plan"], "actual": tv["actual"],
            "days": [f"{ds[i]:%m/%d}({_WD[ds[i].weekday()]})" for i in idx],
            "rows": [{"name": r["name"], "cells": [[r["cells"][i]["plan"], r["cells"][i]["actual"]] for i in idx],
                      "plan": r["plan"], "actual": r["actual"], "diff": r["diff"], "note": r["note"]} for r in tv["rows"]]}


def _item_json(s: Session, it: m.ReportItem, week_id: str, names: dict) -> dict:
    blocks = [_block_json(s, b, week_id, names) for b in (s.get(m.Block, x) for x in item_ids(s, it)) if b is not None]
    out = {"id": it.id, "kind": it.kind, "line": it.line, "form": it.form, "tag_on": it.tag_on, "src": it.src, "blocks": blocks, "ref": None}
    if it.kind == "metric" and it.dept_id:
        out["metric"] = metric_json(s, it.dept_id, week_id, names)
    if it.kind == "table":
        t = s.get(m.MetricTable, it.table_id) if it.table_id else None
        out["table"] = table_json(s, t, week_id, names) if t else None
    return out


def _ref_items(s: Session, dm: m.Meeting, v: m.MeetingVersion, week_id: str, names: dict) -> list[dict]:
    """부서 제출판의 장 — 표현(한 줄·형태·순서)은 제출판 그대로, 사실은 지금 이슈 값(발행 전 자료는 사실을 바로 따른다)."""
    out = []
    for sec in version_deck(v)["sections"]:
        for it in sec["items"]:
            blocks = [_block_json(s, b, week_id, names) for b in (s.get(m.Block, x["id"]) for x in it["blocks"]) if b is not None]
            if blocks or it.get("kind") in ("metric", "table"):   # 지표 요약·기간 표는 제출판의 값 그대로(그 주에 부서가 낸 숫자)
                out.append({**{k: it.get(k) for k in ("kind", "line", "form", "tag_on", "src", "metric", "table")}, "id": None, "blocks": blocks, "ref": dm.id})
    return out


def _cover(s: Session, mt: m.Meeting, sections: list[dict]) -> dict:
    bs = [b for sec in sections for it in sec["items"] for b in it["blocks"]]
    cov = {"n": sum(len(sec["items"]) for sec in sections), "dec": sum(1 for b in bs if b["dec"]),
           "closing": sum(1 for b in bs if b["status"] == "종결요청"), "long": sum(1 for b in bs if "주 미결" in (b["ptag"] or ""))}
    if mt.kind == "share":
        sub = [sec for sec in sections if sec["state"].startswith("제출")]
        cov["submit"] = f"{len(sub)}/{len(sections)}"
        cov["left"] = [sec["dept"] for sec in sections if not sec["state"].startswith("제출")]
    if mt.kind == "exec":
        cov["closed"] = s.scalar(select(func.count()).select_from(m.Closure).where(
            m.Closure.decision == "승인", m.Closure.decided_week_id == mt.week_id)) or 0
    return cov


def deck(s: Session, mt: m.Meeting) -> dict:
    """회의자료 전체 — {meeting, sections:[{dept_id, dept, state, ref, items}], cover}. 공유회는 부서 칸마다, 나머지는 칸 하나."""
    names = _dept_names(s)
    own = items(s, mt)
    if mt.kind == "share":
        sections = []
        for d in dept_order(s, mt):
            dm, v = _submitted(s, mt, d.id)
            mine = [_item_json(s, it, mt.week_id, names) for it in own
                    if (it.dept_id or (s.get(m.Block, it.block_id).owner_department_id if it.block_id and s.get(m.Block, it.block_id) else None)) == d.id]
            refs = _ref_items(s, dm, v, mt.week_id, names) if v else []
            ref_ids = {b["id"] for it in refs for b in it["blocks"]}
            mine = [it for it in mine if not any(b["id"] in ref_ids for b in it["blocks"])] if refs else mine
            if v:
                state = f"제출 {v.version}판" + (" · 뒤에 수정됨" if dm.status == "수정됨" else "")
            else:
                state = "미제출" + (" · 원장으로 채움" if any(it["src"] == "원장 채움" for it in mine) else "")
            sections.append({"dept_id": d.id, "dept": d.name, "state": state, "ref": dm.id if dm else None, "items": refs + mine})
    else:
        sections = [{"dept_id": mt.owner_dept_id, "dept": names.get(mt.owner_dept_id or "", ""), "state": "", "ref": None,
                     "items": [_item_json(s, it, mt.week_id, names) for it in own]}]
    meta = {"id": mt.id, "kind": mt.kind, "kind_label": KINDS.get(mt.kind, mt.kind), "title": mt.title, "status": mt.status,
            "version": mt.version, "week": mt.week_id, "dept": names.get(mt.owner_dept_id or "", ""), "hull": mt.hull_id or ""}
    from app.services import run as rn            # 순환 import 회피(run 이 이 모듈을 쓴다)
    return {"meeting": meta, "sections": sections, "cover": _cover(s, mt, sections), "forms": FORMS,
            "directives": rn.directives_for(s, mt)}


def view(s: Session, mt: m.Meeting) -> dict:
    """회의자료 보기 — 발행·제출판이 있으면 그 판(고정) + 바뀐 장 표시, 없으면 지금 구성(「구성 중」)."""
    v = latest_version(s, mt)
    if v is None:
        return {"deck": deck(s, mt), "published": False, "published_at": "", "changes": [], "long_weeks": settings.LONG_OPEN_WEEKS}
    ch = changes(s, mt)
    d = version_deck(v)
    changed = {c["block_id"]: c["fields"] for c in ch}
    for sec in d["sections"]:
        for it in sec["items"]:
            it["changed"] = sorted({f for b in it["blocks"] for f in changed.get(b["id"], [])})
    return {"deck": d, "published": True, "published_at": v.published_at.strftime("%m/%d %H:%M"), "changes": ch,
            "long_weeks": settings.LONG_OPEN_WEEKS}


def state(s: Session, mt: m.Meeting) -> dict:
    """스튜디오 상태 — deck 을 장 목록 하나로 펴고(공유회는 부서 칸 표시), 후보·판·변경을 붙인다."""
    d = deck(s, mt)
    flat = []
    for n, sec in enumerate(d["sections"]):
        for it in sec["items"]:
            flat.append({**it, "sec": n, "ro": it["ref"] is not None})
    names = _dept_names(s)
    cands = [{"group": g, "blocks": [_block_json(s, b, mt.week_id, names) for b in bs]} for g, bs in candidates(s, mt)]
    v = latest_version(s, mt)
    meta = {**d["meeting"], "editable": mt.kind in EDITABLE and mt.status != "종료",
            "started": bool(flat) or mt.start_mode is not None or mt.kind != "dept",
            "suggest": suggested_start(s, mt) if mt.kind == "dept" else "", "publishes": mt.kind in PUBLISHES,
            "published_at": v.published_at.strftime("%m/%d %H:%M") if v else "", "changes": len(changes(s, mt)) if v else 0}
    secs = [{k: sec[k] for k in ("dept_id", "dept", "state", "ref")} | {"n": len(sec["items"])} for sec in d["sections"]]
    used = {it.table_id for it in items(s, mt) if it.kind == "table"}
    ptables = [{"id": t.id, "name": t.name, "period": f"{t.start_date:%m/%d}–{t.end_date:%m/%d}"}
               for t in s.scalars(select(m.MetricTable).where(m.MetricTable.department_id == mt.owner_dept_id,
                                                              m.MetricTable.hidden.is_(False)).order_by(m.MetricTable.start_date.desc()))
               if t.id not in used] if mt.kind == "dept" and mt.owner_dept_id else []
    return {"meeting": meta, "items": flat, "sections": secs if mt.kind == "share" else [], "cover": d["cover"], "ptables": ptables,
            "candidates": cands, "forms": FORMS, "long_weeks": settings.LONG_OPEN_WEEKS, "directives": d["directives"]}
