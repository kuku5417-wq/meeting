"""일정 경보 — F21 (2026-10-23, 사용자 결정: 「~전 해결」 + D-14 경보, 경보 해제, D-n 일수 수정).

- 이슈마다 「~전 해결」 목표: 마일스톤 이벤트(S/T·G/T·인도…) 또는 직접 날짜. 이벤트 날짜는 **볼 때마다** 중앙 milestone 에서
  실적 → 전망 → 계획 순으로 다시 잡는다(일정이 바뀌면 경보도 따라 움직인다).
- 경보 일수(D-n): 이벤트별 기본값(설정 화면, 처음 14) + 이슈별로 고칠 수 있다.
- 경보 해제: 사유 한 줄 + 그때의 목표 날짜를 남긴다. **목표 날짜가 그보다 당겨지거나 목표를 바꾸면 다시 켜진다.**
  날짜가 지나면 해제와 관계없이 「기한 지남」.
- 바꾼 것(목표·해제)은 ai_field_log 에 사람 값으로 남는다(이력). 추천은 규칙만(가스 → G/T, 인도 → D/L, 아니면 다음 이벤트) —
  AI 추천은 사내 LLM 사양이 정해진 뒤.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.services import central, weeks
from app.services import writing as w

DEFAULT_DAYS = 14
EVENTS = {code: label for code, label, _, _ in central.EVENTS}
LEVELS = ("기한 지남", "임박")                     # 「일정 임박」 묶음에 드는 것


class AlertError(w.WriteError):
    """화면에 그대로 보여줄 한국어 사유."""


def short(code: str) -> str:
    return "목표일" if code == "DATE" else EVENTS.get(code, code).split(" ")[0]


def options() -> list[tuple[str, str]]:
    return [(c, l) for c, l in EVENTS.items()] + [("DATE", "직접 날짜")]


# ── 기본 경보 일수(설정) ────────────────────────────────
def default_days(s: Session, code: str) -> int:
    v = s.get(m.AppSetting, f"alert_days:{code}")
    try:
        return int(v.value) if v and v.value.strip() else DEFAULT_DAYS
    except ValueError:
        return DEFAULT_DAYS


def defaults(s: Session) -> list[dict]:
    return [{"code": c, "label": l, "days": default_days(s, c)} for c, l in options()]


def set_defaults(s: Session, form) -> int:
    n = 0
    for c, _ in options():
        raw = str(form.get(f"d_{c}", "")).strip()
        if raw == "":
            continue
        try:
            days = int(raw)
        except ValueError:
            raise AlertError(f"{short(c)}: 경보 일수는 숫자로 적어주세요.") from None
        if not 0 <= days <= 180:
            raise AlertError(f"{short(c)}: 경보 일수는 0~180일로 적어주세요.")
        row = s.get(m.AppSetting, f"alert_days:{c}")
        if row is None:
            s.add(m.AppSetting(key=f"alert_days:{c}", value=str(days)))
            n += 1
        elif row.value != str(days):
            row.value = str(days)
            n += 1
    s.flush()
    return n


# ── 목표 · 상태 ─────────────────────────────────────────
def target(s: Session, b: m.Block) -> dict | None:
    """목표 날짜 — {code, label, date, src}. 목표가 없거나 마일스톤에 날짜가 없으면 None."""
    if not b.due_event:
        return None
    if b.due_event == "DATE":
        return {"code": "DATE", "label": "직접 날짜", "date": b.due_date, "src": "직접"} if b.due_date else None
    hull = w.block_hull(s, b.id)
    ev = next((e for e in central.hull_events(hull) if e["code"] == b.due_event), None) if hull else None
    return {"code": b.due_event, "label": EVENTS.get(b.due_event, b.due_event), "date": ev["date"], "src": ev["src"]} if ev else None


def state(s: Session, b: m.Block, today: date | None = None) -> dict | None:
    """경보 상태 — {target, left, days, level(기한 지남·임박·해제·""), chip, off_reason}. 목표 없음·종결이면 None."""
    if b.status == "종결" or not b.due_event:
        return None
    t = target(s, b)
    if t is None:
        hull = w.block_hull(s, b.id)
        return {"target": None, "left": None, "days": None, "level": "", "off_reason": b.alert_off_reason or "",
                "chip": f"{short(b.due_event)} 전 — " + ("호선 마일스톤에 날짜 없음" if hull else "호선을 매핑해야 날짜가 잡힘")}
    today = today or weeks.today()
    left = (t["date"] - today).days
    days = b.alert_days if b.alert_days is not None else default_days(s, t["code"])
    off = bool((b.alert_off_reason or "").strip()) and b.alert_off_date is not None and t["date"] >= b.alert_off_date
    level = "기한 지남" if left < 0 else ("해제" if off and left <= days else ("임박" if left <= days else ""))
    chip = f"{short(t['code'])} 전 " + (f"기한 지남 D+{-left}" if left < 0 else f"D-{left}")
    return {"target": t, "left": left, "days": days, "level": level, "chip": chip, "off_reason": b.alert_off_reason or ""}


def suggest(s: Session, b: m.Block) -> str:
    """추천 목표 — 글에 가스 → G/T, 인도 → D/L, 아니면 호선의 다음 이벤트."""
    text = f"{b.title} {b.body}"
    if "가스" in text or "GAS" in text.upper():
        return "GT"
    if "인도" in text:
        return "DL"
    hull = w.block_hull(s, b.id)
    br = central.hull_brief(hull) if hull else None
    return br["next"]["code"] if br and br.get("next") else ""


def set_due(s: Session, b: m.Block, event: str, due: str = "", days: str = "") -> None:
    """목표·경보 일수 바꾸기. 목표가 바뀌면 경보 해제를 푼다(다시 켜짐)."""
    event = (event or "").strip().upper()
    if event and event not in EVENTS and event != "DATE":
        raise AlertError("목표는 마일스톤 이벤트 또는 직접 날짜 중에서 골라주세요.")
    d = None
    if event == "DATE":
        try:
            d = date.fromisoformat((due or "").strip())
        except ValueError:
            raise AlertError("직접 날짜를 2026-11-05 처럼 적어주세요.") from None
    n = None
    if (days or "").strip():
        try:
            n = int(days)
        except ValueError:
            raise AlertError("경보 일수는 숫자로 적어주세요(비우면 이벤트 기본값).") from None
        if not 0 <= n <= 180:
            raise AlertError("경보 일수는 0~180일로 적어주세요.")
    changed = (b.due_event or "", b.due_date) != (event, d)
    b.due_event, b.due_date, b.alert_days = event, d, n
    if changed:
        b.alert_off_reason, b.alert_off_at, b.alert_off_date = "", None, None
    s.add(m.AiFieldLog(block_id=b.id, field="due", ai_value=None,
                       human_value=f"{event or '없음'}{' ' + d.isoformat() if d else ''}{f' · D-{n}' if n is not None else ''}"))
    s.flush()


def dismiss(s: Session, b: m.Block, reason: str) -> None:
    reason = (reason or "").strip()
    if not reason:
        raise AlertError("경보를 끄는 사유를 한 줄 적어주세요.")
    st = state(s, b)
    if not st or st["target"] is None:
        raise AlertError("목표 날짜가 없는 이슈입니다 — 먼저 「~전 해결」 목표를 정해주세요.")
    b.alert_off_reason, b.alert_off_at, b.alert_off_date = reason[:300], datetime.now(), st["target"]["date"]
    s.add(m.AiFieldLog(block_id=b.id, field="alert_off", ai_value=None, human_value=reason[:300]))
    s.flush()


def undismiss(s: Session, b: m.Block) -> None:
    b.alert_off_reason, b.alert_off_at, b.alert_off_date = "", None, None
    s.add(m.AiFieldLog(block_id=b.id, field="alert_off", ai_value=None, human_value=""))
    s.flush()


def due_blocks(s: Session, dept_id: str | None = None, hull: str | None = None) -> list[tuple[m.Block, dict]]:
    """「일정 임박」 묶음 — 기한 지남·임박(해제한 것은 기한이 지나기 전까지 뺀다), 남은 날 순."""
    q = select(m.Block).where(m.Block.due_event != "", m.Block.status != "종결", m.Block.block_type.in_(w.TRACKED))
    if dept_id:
        q = q.where(m.Block.owner_department_id == dept_id)
    out = []
    for b in s.scalars(q):
        if hull and w.block_hull(s, b.id) != hull:
            continue
        st = state(s, b)
        if st and st["level"] in LEVELS:
            out.append((b, st))
    return sorted(out, key=lambda x: (x[1]["left"], x[0].id))
