"""지식창고 · 장비 허브 질의 (docs/03 §5, 화면 C·D, 기능 10).

검색은 데이터가 작다는 전제의 단순한 방식이다: 문서(사례·공유정보·사진)를 그때그때 모아
낱말이 몇 개 맞는지로 점수를 매긴다. 낱말은 조사·불용어를 떼고, 별칭 사전·선종 코드로 넓힌다
(「DG2」 → 발전기, 「LNGC」 → LNG 운반선). 수천 건을 넘으면 색인(FTS)으로 바꾼다.

- `search()` — 키워드 + 필터(호선·장비/시스템·선종·기간·부서·유형) + 종류(사례/공유정보/사진) 개수
- `similar_cases()` — 작성 중 블록과 비슷한 사례(같은 장비·같은 모델·자매선·같은 증상)
- `same_model()` · `sister_precedents()` · `cause_ranking()` · `equipment_history()` · `component_photos()` — 장비 허브
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m
from app.services import alias as alias_svc
from app.services import carry_over as co
from app.services import masters as ms
from app.services import weeks
from app.services import writing as w

KINDS = {"all": "전체", "case": "사례", "share": "공유정보", "photo": "사진"}
PERIODS = {"all": "전체", "8": "최근 8주", "26": "최근 반년", "104": "최근 2년"}
STOP = {"조치", "이력", "과거", "어떻게", "했나", "했나요", "했어", "알려줘", "알려주세요", "있나", "있나요", "사례", "관련",
        "건", "대한", "무엇", "뭐", "왜", "언제", "어디", "방법", "내용", "있었나", "결과"}
# 「도」「만」은 넣지 않는다 — 온도·배기온도·만 처럼 낱말 끝 글자와 겹친다
PARTICLES = ("에서는", "에서", "으로", "에게", "까지", "부터", "이랑", "하고", "은", "는", "이", "가", "을", "를", "의",
             "에", "로", "와", "과")


# ── 낱말 ────────────────────────────────────────────────
def tokens(q: str) -> list[str]:
    out = []
    for raw in re.split(r"[\s,.?!·/()\[\]\"']+", q or ""):
        t = raw.strip()
        if not t:
            continue
        for p in PARTICLES:
            if len(t) > len(p) + 1 and t.endswith(p):
                t = t[: -len(p)]
                break
        if t and t not in STOP:
            out.append(t)
    return out


def _expand(s: Session, tok: str) -> set[str]:
    """낱말 하나 → 같은 뜻 낱말들(대소문자 무시는 비교할 때)."""
    alts = {tok}
    st = s.scalar(select(m.ShipType).where(func.upper(m.ShipType.code) == tok.upper()))
    if st:
        alts.add(st.name)
    r = alias_svc.resolve(s, tok)
    if r.linked and r.target_kind == "installed_equipment":
        e = s.get(m.InstalledEquipment, r.target_id)
        if e:
            alts.add(re.sub(r"\s*No\.\d+$", "", e.name))
    elif r.linked and r.target_kind in ("component", "symptom"):
        model = m.Component if r.target_kind == "component" else m.SymptomCode
        x = s.get(model, r.target_id)
        if x:
            alts.add(x.name)
    for a in s.scalars(select(m.Alias)):             # 「DG」 처럼 호선 없는 장비 약어
        if alias_svc.normalize(a.text).rstrip("0123456789") == alias_svc.normalize(tok) and a.target_kind == "installed_equipment":
            e = s.get(m.InstalledEquipment, a.target_id)
            if e:
                alts.add(re.sub(r"\s*No\.\d+$", "", e.name))
    return alts


# ── 문서 ────────────────────────────────────────────────
@dataclass
class Doc:
    kind: str
    key: str
    title: str
    strong: str                 # 점수 2배 (제목·증상·원인)
    text: str                   # 그 밖의 글
    facets: dict = field(default_factory=dict)
    obj: object = None
    extra: dict = field(default_factory=dict)
    score: float = 0.0


def _eq_facets(s: Session, eq: m.InstalledEquipment | None, hull_id: str | None = None) -> dict:
    hull = s.get(m.Hull, eq.hull_id if eq else (hull_id or ""))
    st = s.get(m.ShipType, hull.ship_type_id) if hull and hull.ship_type_id else None
    path = ms.system_path(s, eq.system_id) if eq else []
    return {"hull": hull.id if hull else None, "ship_type": st.name if st else None,
            "system": path[-1] if path else None, "path": " ".join(path)}


def _block_eq(s: Session, block_id: str) -> m.InstalledEquipment | None:
    tid = s.scalar(select(m.BlockTag.target_id).where(m.BlockTag.block_id == block_id, m.BlockTag.kind == "installed_equipment",
                                                      m.BlockTag.target_id.is_not(None)).limit(1))
    return s.get(m.InstalledEquipment, tid) if tid else None


def _docs(s: Session) -> list[Doc]:
    docs: list[Doc] = []
    dn = {d.id: d.name for d in s.scalars(select(m.Department))}
    for c in s.scalars(select(m.CaseCard)):
        b = s.get(m.Block, c.block_id)
        eq = s.get(m.InstalledEquipment, c.installed_equipment_id) if c.installed_equipment_id else _block_eq(s, c.block_id)
        f = _eq_facets(s, eq, w.block_hull(s, c.block_id))
        f.update(dept=dn.get(b.owner_department_id), type=b.block_type, week=c.approved_week_id)
        tags = " ".join(t.raw_text or "" for t in w.block_tags(s, b.id))
        docs.append(Doc("case", c.id, b.title, f"{b.title} {c.symptom_text} {c.cause_text}",
                        f"{c.action_text} {tags} {eq.name if eq else ''} {f['path']} {f['ship_type'] or ''} {f['hull'] or ''}",
                        f, c, {"b": b, "eq": eq}))
    for b in s.scalars(select(m.Block).where(m.Block.block_type == "share")):
        hull = w.block_hull(s, b.id)
        f = _eq_facets(s, _block_eq(s, b.id), hull)
        f.update(dept=dn.get(b.owner_department_id), type="share", week=b.created_week_id)
        tags = " ".join(t.raw_text or "" for t in w.block_tags(s, b.id))
        docs.append(Doc("share", b.id, b.title, b.title, f"{b.body} {tags} {f['path']} {f['ship_type'] or ''} {hull or ''}", f, b))
    rows = s.execute(select(m.Marker, m.Annotation).join(m.Annotation, m.Annotation.id == m.Marker.annotation_id)).all()
    for mk, ann in rows:
        b = s.get(m.Block, ann.block_id) if ann.block_id else None
        if b is None:
            continue
        comp = s.get(m.Component, mk.component_id) if mk.component_id else None
        f = _eq_facets(s, _block_eq(s, b.id), w.block_hull(s, b.id))
        f.update(dept=dn.get(b.owner_department_id), type=b.block_type, week=b.created_week_id)
        docs.append(Doc("photo", f"{ann.photo_id}#{mk.no}", f"{b.title} · 마커 {mk.no}", f"{mk.label} {comp.name if comp else ''}",
                        f"{b.title} {f['path']} {f['ship_type'] or ''}", f, mk,
                        {"photo_id": ann.photo_id, "block": b, "comp": comp, "no": mk.no}))
    return docs


@dataclass
class SearchResult:
    q: str
    toks: list[str]
    kind: str
    results: list[Doc]
    counts: dict[str, int]
    facets: dict[str, list[tuple[str, int]]]
    cases: list[Doc]                       # 답변 근거 후보 (필터를 통과한 사례, 점수 순)


FACET_KEYS = (("hull", "호선"), ("system", "장비 · 시스템"), ("ship_type", "선종"), ("dept", "부서"))


def search(s: Session, q: str = "", kind: str = "all", filters: dict | None = None, period: str = "all",
           now_week: str | None = None) -> SearchResult:
    filters = {k: v for k, v in (filters or {}).items() if v}
    toks = tokens(q)
    groups = [{a.lower() for a in _expand(s, t)} for t in toks]
    docs = _docs(s)
    matched = []
    for d in docs:
        if groups:
            strong, text = d.strong.lower(), (d.strong + " " + d.text).lower()
            hits = 0.0
            for g in groups:
                if any(a in strong for a in g):
                    hits += 2
                elif any(a in text for a in g):
                    hits += 1
            need = max(1, (len(groups) + 1) // 2)          # 낱말의 절반 이상은 맞아야
            if sum(1 for g in groups if any(a in text for a in g)) < need:
                continue
            d.score = hits
        matched.append(d)
    if period != "all" and now_week:
        try:
            cut = weeks.shift(now_week, -int(period)).id
            matched = [d for d in matched if (d.facets.get("week") or "") >= cut]
        except ValueError:  # noqa: PERF203 — 모르는 기간 → 전체
            pass
    facets = {}
    for key, _ in FACET_KEYS:
        others = [d for d in matched if all(d.facets.get(k) == v for k, v in filters.items() if k != key)]
        facets[key] = Counter(d.facets.get(key) for d in others if d.facets.get(key)).most_common(8)
    filtered = [d for d in matched if all(d.facets.get(k) == v for k, v in filters.items())]
    counts = {"all": len(filtered), **{k: sum(1 for d in filtered if d.kind == k) for k in KINDS if k != "all"}}
    shown = [d for d in filtered if kind in ("all", d.kind)]
    order = {"case": 0, "share": 1, "photo": 2}
    shown.sort(key=lambda d: (-d.score, order[d.kind], d.facets.get("week") or ""), reverse=False)
    cases = [d for d in sorted(filtered, key=lambda d: -d.score) if d.kind == "case"]
    return SearchResult(q, toks, kind, shown, counts, facets, cases)


# ── 사례 카드 목록 · 이력 ───────────────────────────────
def case_view(s: Session, c: m.CaseCard) -> dict:
    b = s.get(m.Block, c.block_id)
    eq = s.get(m.InstalledEquipment, c.installed_equipment_id) if c.installed_equipment_id else None
    depts = list(s.scalars(select(m.Department.name).join(m.BlockHistory, m.BlockHistory.department_id == m.Department.id)
                           .where(m.BlockHistory.block_id == c.block_id).order_by(m.BlockHistory.id)))
    path = [d for i, d in enumerate(depts) if i == 0 or d != depts[i - 1]]        # 부서 이동 경로
    photos = s.scalar(select(func.count()).select_from(m.PhotoLink).where(m.PhotoLink.block_id == c.block_id))
    return {"c": c, "b": b, "eq": eq, "dept_path": path, "first_week": b.created_week_id if b else c.approved_week_id,
            "photos": photos}


def case_cards(s: Session) -> list[dict]:
    return [case_view(s, c) for c in s.scalars(select(m.CaseCard).order_by(m.CaseCard.approved_week_id.desc(),
                                                                           m.CaseCard.id.desc()))]


# ── 비슷한 사례 (작성 중, 기능 10) ──────────────────────
def _sister_hulls(s: Session, hull_id: str | None) -> set[str]:
    h = s.get(m.Hull, hull_id or "")
    if not h or not h.sister_group_id:
        return set()
    return set(s.scalars(select(m.Hull.id).where(m.Hull.sister_group_id == h.sister_group_id))) - {h.id}


def similar_cases(s: Session, block_id: str, limit: int = 3) -> list[dict]:
    b = s.get(m.Block, block_id)
    if b is None:
        return []
    eq = _block_eq(s, block_id)
    sym = {t.target_id for t in w.block_tags(s, block_id) if t.kind == "symptom" and t.target_id}
    sisters = _sister_hulls(s, eq.hull_id if eq else w.block_hull(s, block_id))
    words = set(tokens(b.title)) - {eq.hull_id if eq else ""}
    out = []
    for c in s.scalars(select(m.CaseCard).where(m.CaseCard.block_id != block_id)):
        ceq = s.get(m.InstalledEquipment, c.installed_equipment_id) if c.installed_equipment_id else None
        score, why = 0, []
        if eq and ceq and ceq.id == eq.id:
            score, why = score + 4, why + ["같은 장비"]
        elif eq and ceq and ceq.equipment_model_id and ceq.equipment_model_id == eq.equipment_model_id:
            score, why = score + 3, why + ["같은 모델"]
        if ceq and ceq.hull_id in sisters:
            score, why = score + 1, why + ["자매선"]
        if c.symptom_code_id and c.symptom_code_id in sym:
            score, why = score + 3, why + ["같은 증상"]
        cb = s.get(m.Block, c.block_id)
        overlap = len(words & set(tokens(f"{cb.title} {c.symptom_text}")))
        score += min(overlap, 3)
        if score >= 3:
            out.append({"c": c, "eq": ceq, "score": score, "why": why, "sister": "자매선" in why})
    out.sort(key=lambda x: (-x["score"], x["c"].id))
    return out[:limit]


# ── 장비 허브 (docs/03 §5) ──────────────────────────────
def equipment_history(s: Session, eq_id: str) -> list[dict]:
    rows = []
    for b in s.scalars(select(m.Block).join(m.BlockTag, m.BlockTag.block_id == m.Block.id)
                       .where(m.BlockTag.kind == "installed_equipment", m.BlockTag.target_id == eq_id).distinct()):
        for h in co.history(s, b.id):
            rows.append({"week": h.week_id, "block": b, "status": h.status, "note": h.note})
    rows.sort(key=lambda r: (r["week"], r["block"].id))
    return rows


def open_issues(s: Session, eq_id: str) -> list[m.Block]:
    return list(s.scalars(select(m.Block).join(m.BlockTag, m.BlockTag.block_id == m.Block.id)
                          .where(m.BlockTag.kind == "installed_equipment", m.BlockTag.target_id == eq_id,
                                 m.Block.status.in_(co.OPEN)).distinct().order_by(m.Block.id)))


def _latest_for_eq(s: Session, eq_id: str) -> dict:
    """그 장비의 가장 최근 사례(있으면) 또는 열린 블록."""
    c = s.scalar(select(m.CaseCard).where(m.CaseCard.installed_equipment_id == eq_id)
                 .order_by(m.CaseCard.approved_week_id.desc()).limit(1))
    if c:
        return {"symptom": c.symptom_text, "cause": c.cause_text, "status": "종결", "ref": c.id}
    ob = open_issues(s, eq_id)
    if ob:
        b = ob[0]
        tags = w.block_tags(s, b.id)
        sym = next((t.raw_text for t in tags if t.kind == "symptom"), b.title)
        cause = next((t.raw_text for t in tags if t.kind == "cause"), "")
        return {"symptom": sym, "cause": cause, "status": b.status, "ref": b.id}
    return {}


def same_model(s: Session, eq_id: str) -> list[dict]:
    eq = s.get(m.InstalledEquipment, eq_id)
    if eq is None or not eq.equipment_model_id:
        return []
    sisters = _sister_hulls(s, eq.hull_id)
    out = []
    for o in s.scalars(select(m.InstalledEquipment).where(m.InstalledEquipment.equipment_model_id == eq.equipment_model_id,
                                                          m.InstalledEquipment.id != eq.id).order_by(m.InstalledEquipment.id)):
        sister = o.hull_id in sisters
        same_pos = sister and o.system_id == eq.system_id and (o.position or "") == (eq.position or "")
        out.append({"eq": o, "sister": sister, "same_pos": same_pos, **_latest_for_eq(s, o.id)})
    out.sort(key=lambda r: (not r["same_pos"], not r["sister"], r["eq"].hull_id, r["eq"].id))
    return out


def sister_precedents(s: Session, eq_id: str) -> list[dict]:
    """자매선의 같은 시스템·같은 위치 장비에서 종결된 사례 → 점검 권장."""
    eq = s.get(m.InstalledEquipment, eq_id)
    if eq is None:
        return []
    sisters = _sister_hulls(s, eq.hull_id)
    out = []
    for o in s.scalars(select(m.InstalledEquipment).where(m.InstalledEquipment.hull_id.in_(sisters),
                                                          m.InstalledEquipment.system_id == eq.system_id)):
        if (o.position or "") != (eq.position or ""):
            continue
        for c in s.scalars(select(m.CaseCard).where(m.CaseCard.installed_equipment_id == o.id)):
            out.append({"eq": o, "c": c})
    out.sort(key=lambda r: r["c"].approved_week_id, reverse=True)
    return out


def cause_ranking(s: Session, model_id: str | None) -> list[tuple[str, int]]:
    if not model_id:
        return []
    eqs = list(s.scalars(select(m.InstalledEquipment.id).where(m.InstalledEquipment.equipment_model_id == model_id)))
    cnt: Counter = Counter()
    for c in s.scalars(select(m.CaseCard).where(m.CaseCard.installed_equipment_id.in_(eqs))):
        code = s.get(m.CauseCode, c.cause_code_id) if c.cause_code_id else None
        cnt[code.name if code else c.cause_text] += 1
    for b_id in s.scalars(select(m.BlockTag.block_id).where(m.BlockTag.kind == "installed_equipment",
                                                            m.BlockTag.target_id.in_(eqs))):
        b = s.get(m.Block, b_id)
        if b and b.status in co.OPEN:                     # 진행 중 이슈의 원인도 센다(시안과 같이)
            t = next((t for t in w.block_tags(s, b_id) if t.kind == "cause"), None)
            if t:
                code = s.get(m.CauseCode, t.target_id or "")
                cnt[code.name if code else t.raw_text] += 1
    return cnt.most_common()


def component_photos(s: Session, model_id: str | None, limit: int = 6) -> list[dict]:
    if not model_id:
        return []
    comps = {c.id: c.name for c in s.scalars(select(m.Component).where(m.Component.equipment_model_id == model_id))}
    if not comps:
        return []
    out = []
    for mk, ann in s.execute(select(m.Marker, m.Annotation).join(m.Annotation, m.Annotation.id == m.Marker.annotation_id)
                             .where(m.Marker.component_id.in_(list(comps)))).all():
        out.append({"photo_id": ann.photo_id, "block_id": ann.block_id, "comp": comps[mk.component_id], "no": mk.no,
                    "label": mk.label})
    return out[:limit]
