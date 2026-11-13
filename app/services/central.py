"""중앙 parquet 읽기 — pjtlist(호선 목록)·milestone(이벤트 날짜) → 호선 기준정보 동기화 (2026-10-21).

**읽기만 한다**(공통 규칙 2 — parquet 생산자는 data_manager_F). 경로는 `path_config.central_parquet`.
pandas 없이 pyarrow 로 읽어 dict 목록으로 다룬다.

마일스톤 날짜 규칙(pjtcost/modules/central_io.py 에서 옮김):
- 열 이름은 **접두가 앞** — `PERFDL`·`PROSDL`·`PLANDL` (`DLPLAN` 아님).
- 이벤트 날짜는 **호선(행)마다** 실적 → 전망 → 계획 순서로 처음 있는 값을 쓴다. 열 하나를 골라 전 호선에
  쓰지 않는다(costplan 에서 18척 중 14척 날짜가 빠진 사고).
- `GT` 는 Gas Trial(가스시운전)이지 총톤수가 아니다.
파일이 없거나 깨지면 None + 사유 — 앱은 그대로 뜬다(공통 규칙 4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

import path_config as pc
from app import models as m
from app.services import weeks
from sn_util import ensure_sn

_PRE = (("PERF", "실적"), ("PROS", "전망"), ("PLAN", "계획"))

# (코드, 표시명, 시작 열 접미, 끝 열 접미|None) — 순서는 esg DATA_ACCESS.md 의 이벤트 순서
EVENTS: tuple[tuple[str, str, str, str | None], ...] = (
    ("LC", "L/C 진수", "LC", None),
    ("SP", "S/P On", "SP", None),
    ("BT", "B/T", "BT", None),
    ("GT", "G/T 가스시운전", "GT", None),
    ("CMR", "CMR", "CMR", None),
    ("MT", "M/T", "MT", None),
    ("IE", "I/E 경사시험", "IE", None),
    ("AC", "A/C 앵카링", "ACFROM", "ACTO"),
    ("ST", "S/T 해상시운전", "STFROM", "STTO"),
    ("GAS", "Gas T", "GASFROM", "GASTO"),
    ("COLD", "Cold T 안벽", "COLDFROM", "COLDTO"),
    ("WF", "W/F", "WF", None),
    ("DL", "D/L 인도", "DL", None),
)

_cache: dict[str, tuple[tuple, list[dict] | None, str]] = {}
LAST_SYNC: dict = {}                  # 마지막 동기화 시각·결과 (설정 화면 표시용, 프로세스 메모리)


def _read(name: str) -> tuple[list[dict] | None, str]:
    """parquet 한 개 → dict 목록. 파일 mtime·크기가 같으면 다시 읽지 않는다."""
    p = pc.central_parquet(name)
    try:
        st = p.stat()
    except OSError:
        return None, f"{p} 파일이 없습니다"
    stamp = (str(p), st.st_mtime_ns, st.st_size)
    hit = _cache.get(name)
    if hit and hit[0] == stamp:
        return hit[1], hit[2]
    try:
        import pyarrow.parquet as pq
        rows = pq.read_table(p).to_pylist()
        reason = ""
    except Exception as e:  # noqa: BLE001 — 깨진 파일·잠금 → 미연계로 보고 앱은 뜬다
        rows, reason = None, f"{p.name} 을 읽지 못했습니다 ({type(e).__name__})"
    _cache[name] = (stamp, rows, reason)
    return rows, reason


def _keyed(rows: list[dict] | None, *keys: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows or []:
        sn = ""
        for k in keys:
            sn = ensure_sn(r.get(k))
            if sn:
                break
        if sn:
            out[sn] = r
    return out


def load_pjtlist() -> dict[str, dict] | None:
    rows, _ = _read("pjtlist")
    return None if rows is None else _keyed(rows, "SHIPNUM")


def load_milestone() -> dict[str, dict] | None:
    rows, _ = _read("milestone")
    return None if rows is None else _keyed(rows, "project", "SHIPNUM")


def _day(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return None


def _chain(row: dict, suffix: str) -> tuple[date | None, str]:
    for pre, label in _PRE:
        d = _day(row.get(pre + suffix))
        if d:
            return d, label
    return None, ""


def hull_events(sn: str) -> list[dict]:
    """한 호선의 이벤트 날짜 — [{code, label, date, end, src}], 날짜순 (날짜 없는 이벤트는 뺀다)."""
    ms = load_milestone() or {}
    row = ms.get(ensure_sn(sn) or "")
    if not row:
        return []
    out = []
    for code, label, start, end in EVENTS:
        d, src = _chain(row, start)
        e = _chain(row, end)[0] if end else None
        if d:
            out.append({"code": code, "label": label, "date": d, "end": e, "src": src})
    return sorted(out, key=lambda x: x["date"])          # 계획 순서와 실제 날짜 순서가 다를 수 있다(I/E 가 M/T 보다 먼저 등)


def hull_brief(sn: str, today: date | None = None) -> dict | None:
    """칩 한 줄용 — 다음 이벤트(오늘 이후 첫 이벤트)·남은 날·인도일·전체 이벤트.
    다음 이벤트가 없으면 delivered 로 인도 실적 여부를 알린다(전망·계획 날짜만 지났으면 「인도 완료」가 아니다)."""
    evs = hull_events(sn)
    if not evs:
        return None
    today = today or weeks.today()
    nxt = next((e for e in evs if (e["end"] or e["date"]) >= today), None)
    dl = next((e for e in evs if e["code"] == "DL"), None)
    return {"next": nxt, "dday": (nxt["date"] - today).days if nxt else None, "delivery": dl, "events": evs,
            "delivered": bool(dl and dl["src"] == "실적" and dl["date"] <= today)}


def stage_of(sn: str, today: date | None = None) -> str | None:
    """마일스톤으로 본 호선 단계 — 실적 날짜만 지난 일로 본다."""
    evs = {e["code"]: e for e in hull_events(sn)}
    if not evs:
        return None
    today = today or weeks.today()

    def done(code: str) -> bool:
        e = evs.get(code)
        return bool(e and e["src"] == "실적" and e["date"] <= today)
    if done("DL"):
        return "인도"
    if done("ST"):
        return "해상시운전"
    if done("LC"):
        return "진수 후"
    return "진수 전"


@dataclass
class SyncReport:
    ok: bool
    reason: str = ""
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    not_in_pjtlist: list[str] = field(default_factory=list)
    relinked: int = 0


def _clean(v) -> str:
    return str(v).strip() if v is not None else ""


def sync_hulls(s: Session) -> SyncReport:
    """pjtlist → hull(+선종·선주·자매선). 만들거나 고치기만 하고 지우지 않는다."""
    pj = load_pjtlist()
    if pj is None:
        return SyncReport(False, _read("pjtlist")[1] or "pjtlist 를 읽지 못했습니다")
    rep = SyncReport(True)
    for sn, r in sorted(pj.items()):
        tm, own, main = _clean(r.get("TYPEMODEL")), _clean(r.get("REGOWNER")), ensure_sn(r.get("MAINHULLNUM"))
        st_id = f"ST-{tm}"[:32] if tm else None
        if st_id and s.get(m.ShipType, st_id) is None:
            s.add(m.ShipType(id=st_id, code=tm[:32], name=tm))
        ow_id = f"OW-{own}"[:32] if own else None
        if ow_id and s.get(m.Owner, ow_id) is None:
            s.add(m.Owner(id=ow_id, code=own[:32], name=own))
        sg_id = f"SG-{main}" if main else None
        if sg_id and s.get(m.SisterGroup, sg_id) is None:
            s.add(m.SisterGroup(id=sg_id, name=f"{main} 시리즈" + (f" ({tm})" if tm else "")))
        s.flush()
        dl = next((e["date"] for e in hull_events(sn) if e["code"] == "DL"), None) or _day(r.get("WORKFINISH"))
        vals = {"ship_type_id": st_id, "owner_id": ow_id, "sister_group_id": sg_id, "delivery_date": dl,
                "stage": stage_of(sn), "title": _clean(r.get("TITLE"))[:128] or None,
                "dock": _clean(r.get("DOCK"))[:32] or None, "ship_class": _clean(r.get("SHIPCLASS"))[:32] or None,
                "source": "pjtlist"}
        h = s.get(m.Hull, sn)
        if h is None:
            s.add(m.Hull(id=sn, **vals))
            rep.created.append(sn)
        else:
            if any(getattr(h, k) != v for k, v in vals.items()):
                rep.updated.append(sn)
            for k, v in vals.items():
                setattr(h, k, v)
    s.flush()
    rep.not_in_pjtlist = sorted(h for h in s.scalars(select(m.Hull.id)) if h not in pj)
    from app.services import masters as ms
    rep.relinked = ms.relink_unregistered(s)
    return rep


def status() -> dict:
    """설정 화면용 — 파일 위치·수정 시각·행 수·사유."""
    out = {"dir": str(pc.get_central_parquet_dir())}
    for name in ("pjtlist", "milestone"):
        p = pc.central_parquet(name)
        rows, reason = _read(name)
        try:
            mt = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            mt = ""
        out[name] = {"path": str(p), "mtime": mt, "rows": len(rows) if rows is not None else None, "reason": reason}
    return out
