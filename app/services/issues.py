"""이슈 원장 · 홈(이번 주 할 일) — M9 (2026-10-23, 최종 시안 design/mockups/v2m-issue-desk·v2m-home).

이슈 원장은 주차·섹션에 묶이지 않은 이슈·문제점·공유정보 목록이다. 칸 수정은 작성 흐름과 같은 규칙을 쓴다
(`writing.update_block` — ai_field_log 에 AI 값·사람 값, 확정된 섹션이면 거부). 회의자료에 넣기·스튜디오는 M10~11.

- 1차 초안 상태 `draft_state`: none → (칸을 고치면) wip → (「초안 완료」) ok. 초안 칸 = 현상(body)·원인·조치·결정 필요.
- 매핑 5칸: 호선·장비·부위·증상·원인 — block_tag 에 연결(target_id)되거나 미등록으로 둔 것을 채워진 것으로 본다.
- 홈: 역할별 할 일 — 작성자(한 줄 없음·초안 미완료) · 부서 편집자(부서 자료·초안 대기) · 기획(종결 요청·부서 제출).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.services import carry_over as co
from app.services import central
from app.services import closure as cl
from app.services import writing as w

DRAFT = ("none", "wip", "ok")
DRAFT_LABEL = {"none": "초안 없음", "wip": "초안 작성 중", "ok": "초안 완료"}
MAP_KINDS = (("hull", "호선"), ("installed_equipment", "장비"), ("component", "부위"), ("symptom", "증상"), ("cause", "원인"))
FIELDS = {"title", "status", "body", "cause_text", "action_text", "decision_needed"}   # 작업대에서 고치는 칸
CHIPS = (("draft", "초안 미완료"), ("line", "한 줄 없음"), ("map", "매핑 빈 곳"), ("soon", "일정 임박"))


@dataclass
class Row:
    b: m.Block
    hull: str | None
    brief: dict | None
    map_n: int
    needs_line: bool
    long_weeks: int | None
    pending_close: bool
    line: str = ""
    alert: dict | None = None                # F21 일정 경보 상태(목표가 없으면 None)


@dataclass
class Task:
    kind: str                 # line / draft / deck / directive / alert / metrics / nudge / close / share / exec
    group: str
    title: str
    sub: str = ""
    block: m.Block | None = None
    href: str = ""
    extra: dict = field(default_factory=dict)


def map_cells(s: Session, b: m.Block) -> list[dict]:
    """매핑 5칸 — 채워졌으면 이름, 아니면 None."""
    tags = [t for t in w.block_tags(s, b.id) if not t.dismissed]
    out = []
    for kind, label in MAP_KINDS:
        hit = next((t for t in tags if t.kind == kind and (t.target_id or t.confirmed)), None)
        out.append({"kind": kind, "label": label, "value": (w.tag_label(s, hit) if hit.target_id else f"{hit.raw_text} (미등록)") if hit else None})
    return out


def _row(s: Session, b: m.Block, week_id: str) -> Row:
    hull = w.block_hull(s, b.id)
    wr = co.week_row(s, b.id, week_id)
    from app.services import alerts as al          # 순환 import 회피
    return Row(b=b, hull=hull, brief=central.hull_brief(hull) if hull else None,
               map_n=sum(1 for c in map_cells(s, b) if c["value"]), needs_line=co.needs_line(s, b, week_id),
               long_weeks=co.long_open(s, b, week_id), pending_close=cl.pending(s, b.id) is not None,
               line=(wr.note if wr else "") or "", alert=al.state(s, b))


def ledger(s: Session, week_id: str, dept: str = "", chip: str = "", q: str = "", include_closed: bool = False) -> list[Row]:
    """원장 목록 — 담당 부서·걸러 보기·찾기. 대시보드는 지표 화면 몫이라 뺀다."""
    stmt = select(m.Block).where(m.Block.block_type != "dashboard")
    if dept:
        stmt = stmt.where(m.Block.owner_department_id == dept)
    if not include_closed:
        stmt = stmt.where(m.Block.status != "종결")
    rows = [_row(s, b, week_id) for b in s.scalars(stmt.order_by(m.Block.id))]
    if q:
        ql = q.lower().replace(" ", "")
        rows = [r for r in rows if ql in f"{r.b.id}{r.b.title}{r.hull or ''}".lower().replace(" ", "")]
    if chip == "draft":
        rows = [r for r in rows if r.b.draft_state != "ok" and r.b.block_type in w.TRACKED]
    elif chip == "line":
        rows = [r for r in rows if r.needs_line]
    elif chip == "map":
        rows = [r for r in rows if r.map_n < 5 and r.b.block_type in w.TRACKED]
    elif chip == "soon":                     # F21: 이슈의 「~전 해결」 목표 기준(기한 지남·임박, 해제한 것은 기한 전까지 뺀다)
        rows = sorted((r for r in rows if r.alert and r.alert["level"] in ("기한 지남", "임박")), key=lambda r: r.alert["left"])
    return rows


def chip_counts(s: Session, week_id: str, dept: str) -> dict[str, int]:
    return {k: len(ledger(s, week_id, dept, k)) for k, _ in CHIPS}


FACT_FIELDS = ("title", "body", "cause_text", "action_text", "decision_needed", "status", "block_type")


def save_field(s: Session, b: m.Block, field_name: str, value: str, meeting_id: int | None = None) -> bool:
    """자동 저장 — 칸 하나(이슈 작업대, 또는 스튜디오 사실 칸이면 meeting_id). 초안 칸을 처음 고치면 「작성 중」.
    사실 칸이 실제로 바뀌면 block_event 에 이전→이후·어디서를 남긴다(결정 ⑦)."""
    from app.services import events
    if field_name not in FIELDS:
        raise w.WriteError(f"고칠 수 없는 항목입니다: {field_name}")
    before = getattr(b, field_name, "") or ""
    changed = w.update_block(s, b, field_name, value)
    if changed and field_name in FACT_FIELDS:
        events.record(s, b.id, "사실변경", field=field_name, before=str(before),
                      after=str(getattr(b, field_name, "") or ""), meeting_id=meeting_id)
    if changed and b.draft_state == "none" and field_name in ("body", "cause_text", "action_text", "decision_needed", "title"):
        b.draft_state = "wip"
    return changed


def draft_done(s: Session, b: m.Block) -> m.Block | None:
    """「초안 완료」 — 현상이 비면 거부. 같은 부서에서 초안이 남은 다음 이슈를 돌려준다(없으면 None)."""
    if b.block_type not in w.TRACKED:
        raise w.WriteError("1차 초안은 이슈·문제점만 만듭니다.")
    if not (b.body or "").strip():
        raise w.WriteError("「현상」 칸을 채워야 초안을 완료할 수 있습니다.")
    b.draft_state = "ok"
    s.flush()
    return s.scalar(select(m.Block).where(m.Block.owner_department_id == b.owner_department_id,
                                          m.Block.block_type.in_(w.TRACKED), m.Block.status != "종결",
                                          m.Block.draft_state != "ok", m.Block.id != b.id).order_by(m.Block.id).limit(1))


def bulk(s: Session, ids: list[str], action: str, value: str, week_id: str) -> list[str]:
    """여러 이슈 한꺼번에 — 부서 이관(transfer) · 상태(status) · 회의자료에 넣기(adopt, value=회의 id).
    하나라도 실패하면 전부 되돌린다(호출 쪽 rollback)."""
    from app.services import studio as st
    done = []
    mt = None
    if action == "adopt":
        mt = s.get(m.Meeting, int(value)) if str(value).isdigit() else None
        if mt is None:
            raise w.WriteError("넣을 회의자료를 골라주세요.")
    for bid in ids:
        b = s.get(m.Block, bid)
        if b is None:
            raise w.WriteError(f"{bid}: 없는 이슈입니다.")
        if action == "transfer":
            co.transfer(s, b, value, week_id)
        elif action == "status":
            w.update_block(s, b, "status", value)
        elif action == "adopt":
            st.add_item(s, mt, bid, "원장에서")
        else:
            raise w.WriteError("할 수 없는 일괄 작업입니다.")
        done.append(bid)
    return done


def home_tasks(s: Session, role: str, dept: str, week_id: str) -> list[Task]:
    """역할별 이번 주 할 일 — 위에서부터 하면 된다."""
    mine = [r for r in ledger(s, week_id, dept) if r.b.block_type in w.TRACKED]
    soon = [Task("alert", "일정 임박", r.b.title, f"{r.b.id} · {r.alert['chip']}" + (f" · 해제: {r.alert['off_reason']}" if r.alert["off_reason"] else ""),
                 r.b, f"/issues?id={r.b.id}#due") for r in sorted((x for x in mine if x.alert and x.alert["level"] in ("기한 지남", "임박")), key=lambda x: x.alert["left"])]
    if role == "w":
        out = soon + [Task("line", "이번 주 한 줄", r.b.title, f"{r.b.id} · {r.hull or '호선 미확인'}", r.b) for r in mine if r.needs_line]
        out += [Task("draft", "1차 초안 마무리", r.b.title, f"{r.b.id} · {DRAFT_LABEL[r.b.draft_state]}", r.b, f"/issues?id={r.b.id}")
                for r in mine if r.b.draft_state != "ok" and not r.needs_line]
        return out
    if role == "d":
        ok = sum(1 for r in mine if r.b.draft_state == "ok")
        dm = s.scalar(select(m.Meeting).where(m.Meeting.week_id == week_id, m.Meeting.kind == "dept", m.Meeting.owner_dept_id == dept))
        state = f"{dm.status}{f' · {dm.version}판' if dm and dm.version else ''}" if dm else "구성 중"
        out = [Task("deck", "부서 회의자료", "이번 주 부서 회의자료", f"{state} · 초안 완료 {ok} · 미완료 {len(mine) - ok}",
                    href=f"/studio/{dm.id}" if dm else "/meetings")] + soon
        from app.services import metrics as mts           # 순환 import 회피
        miss = mts.missing(s, dept, week_id)
        if miss:
            out.append(Task("metrics", "지표", f"이번 주 지표 미입력 {len(miss)}", " · ".join(miss[:4]) + (" …" if len(miss) > 4 else ""), href=f"/metrics/{dept}"))
        from app.services import run as rn               # 순환 import 회피
        out += [Task("directive", "지시사항", d["text"], f"{d['src']} · 기한 {d['due'][-3:]}" + (" · 기한 지남" if d["late"] else ""),
                     href=f"/studio/{dm.id}" if dm else "/meetings") for d in rn.open_directives(s, dept, week_id)]
        out += [Task("nudge", "초안을 기다리는 이슈", r.b.title, f"{r.b.id} · {DRAFT_LABEL[r.b.draft_state]}", r.b, f"/issues?id={r.b.id}")
                for r in mine if r.b.draft_state != "ok"]
        return out
    out = []
    for c in s.scalars(select(m.Closure).where(m.Closure.decision == "대기").order_by(m.Closure.id)):
        b = s.get(m.Block, c.block_id)
        if b is not None:
            out.append(Task("close", "종결 요청 — 기획 주관자 승인", b.title, f"{b.id} · 조치: {c.action_text[:40]}", b, f"/issues?id={b.id}",
                            extra={"closure_id": c.id, "cause": b.cause_text or ""}))
    from app.services import studio as st            # 순환 import 회피(studio 가 이 모듈을 쓰지 않지만 issues.bulk 가 studio 를 쓴다)
    for kind, label in (("share", "공유회 자료"), ("exec", "팀장 정보회의 자료")):
        mt = st.week_meeting(s, week_id, kind)
        if mt is None:
            continue
        cov = st.deck(s, mt)["cover"]
        sub = f"부서 제출 {cov['submit']}" + (f" · 남음 {'·'.join(cov['left'])}" if cov.get("left") else "") if kind == "share" else f"장 {cov['n']}"
        out.append(Task(kind, label, mt.title, f"{mt.status}{f' · {mt.version}판' if mt.version else ''} · {sub}", href=f"/studio/{mt.id}"))
    return out
