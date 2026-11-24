"""파생·합치기 (결정 ⑦ 15-5, 2026-11-24) — 이슈를 떼어내고(15-4), 잘못 뗐으면 다시 합친다.

지키는 것
  - **ID 는 지우지 않는다**(원칙 8). 합친 이슈도 그대로 남고, 목록(원장·후보·이어받기)에서만 빠진다.
    그래서 옛 회의자료·사례 카드에 적힌 ID 가 계속 살아 있다.
  - 관계는 `block_link` 한 곳에만 둔다 — 「파생」(원래 → 새 이슈) · 「합쳐짐」(합쳐진 쪽 → 남는 쪽).
    상태(`block.status`)로 흉내 내지 않는다. 「종결」은 종결 승인이라는 다른 뜻이고 사례 카드 승격과 묶여 있다.
  - 합칠 때 **사실을 덮지 않는다** — 현상은 덧붙이고(15-4 와 같은 규칙), 바뀐 것은 이슈 변경 기록에 남긴다.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.services import writing as w

DERIVED = "파생"        # from = 원래 이슈, to = 떼어낸 새 이슈
MERGED = "합쳐짐"       # from = 합쳐진(없어진 셈) 이슈, to = 남는 이슈


def _ids(s: Session, *, frm: str = "", to: str = "", rel: str = "") -> list[str]:
    stmt = select(m.BlockLink)
    if frm:
        stmt = stmt.where(m.BlockLink.from_block_id == frm)
    if to:
        stmt = stmt.where(m.BlockLink.to_block_id == to)
    if rel:
        stmt = stmt.where(m.BlockLink.relation == rel)
    rows = list(s.scalars(stmt))
    return [(r.to_block_id if frm else r.from_block_id) for r in rows]


def children(s: Session, block_id: str) -> list[str]:
    """이 이슈에서 떼어낸 이슈들."""
    return _ids(s, frm=block_id, rel=DERIVED)


def parents(s: Session, block_id: str) -> list[str]:
    """이 이슈가 나온 곳(보통 하나)."""
    return _ids(s, to=block_id, rel=DERIVED)


def merged_into(s: Session, block_id: str) -> str:
    got = _ids(s, frm=block_id, rel=MERGED)
    return got[0] if got else ""


def merged_from(s: Session, block_id: str) -> list[str]:
    """이 이슈로 합쳐 들인 이슈들."""
    return _ids(s, to=block_id, rel=MERGED)


def merged_ids(s: Session) -> set[str]:
    """목록에서 빼는 이슈 — 합쳐진 쪽. 작은 표라 통째로 읽는다."""
    return set(s.scalars(select(m.BlockLink.from_block_id).where(m.BlockLink.relation == MERGED)))


def _brief(s: Session, block_id: str) -> dict:
    b = s.get(m.Block, block_id)
    return {"id": block_id, "title": (b.title if b else "") or block_id, "status": b.status if b else "",
            "merged": merged_into(s, block_id), "href": f"/issues?id={block_id}"}


def chips(s: Session, block_id: str) -> list[dict]:
    """양쪽 화면에 거는 칩 — 어디서 나왔고 어디로 갈라졌는지, 합쳐졌는지."""
    out = []
    for pid in parents(s, block_id):
        out.append({**_brief(s, pid), "rel": "from", "text": "에서 나옴"})
    for cid in children(s, block_id):
        out.append({**_brief(s, cid), "rel": "to", "text": "파생"})
    into = merged_into(s, block_id)
    if into:
        out.append({**_brief(s, into), "rel": "into", "text": "로 합쳐짐"})
    for fid in merged_from(s, block_id):
        out.append({**_brief(s, fid), "rel": "took", "text": "를 합쳐 들임"})
    return out


def can_merge(s: Session, src_id: str, dst_id: str) -> str:
    """합칠 수 없으면 **사람에게 보여 줄 사유**, 합칠 수 있으면 빈 문자열."""
    if src_id == dst_id:
        return "같은 이슈끼리는 합칠 수 없습니다."
    if merged_into(s, src_id):
        return f"{src_id} 는 이미 {merged_into(s, src_id)} 로 합쳐졌습니다."
    if merged_into(s, dst_id):
        return f"{dst_id} 는 이미 {merged_into(s, dst_id)} 로 합쳐졌습니다 — 남아 있는 이슈로 합쳐주세요."
    if dst_id not in parents(s, src_id) + children(s, src_id):
        return "「파생」으로 이어진 이슈끼리만 합칩니다 — 잘못 떼어낸 이슈를 되돌리는 기능입니다."
    return ""


def merge(s: Session, src: m.Block, dst: m.Block, week_id: str, meeting_id: int | None = None) -> dict:
    """`src` 를 `dst` 로 합친다 — 현상은 덧붙이고, 이번 주 한 줄은 이어 붙이고, ID 는 남긴다.

    돌려주는 값: {"body": 현상을 덧붙였나, "line": 한 줄을 덧붙였나}
    """
    from app.services import carry_over as co
    from app.services import events
    from app.services import issues as iss

    why = can_merge(s, src.id, dst.id)
    if why:
        raise w.WriteError(why)

    did = {"body": False, "line": False}
    text = (src.body or "").strip()
    if text and text not in (dst.body or ""):
        cur = (dst.body or "").strip()
        iss.save_field(s, dst, "body", "\n".join([cur, text]) if cur else text, meeting_id=meeting_id)
        did["body"] = True

    row = co.week_row(s, src.id, week_id)
    note = ((row.note if row else "") or "").strip()
    if note:
        drow = co.week_row(s, dst.id, week_id)
        cur = ((drow.note if drow else "") or "").strip()
        if note not in cur:
            co.update_line(s, dst, week_id, f"{cur} / {note}" if cur else note)
            did["line"] = True

    s.add(m.BlockLink(from_block_id=src.id, to_block_id=dst.id, relation=MERGED))
    events.record(s, dst.id, "합치기", after=f"{src.id} 를 합쳐 들였습니다 — {src.title}", meeting_id=meeting_id)
    events.record(s, src.id, "합치기", after=f"{dst.id} 로 합쳤습니다 — 이 ID 는 기록으로 남습니다", meeting_id=meeting_id)
    co.add_history(s, src, week_id, note=f"{dst.id} 로 합쳐짐")
    s.flush()
    return did
