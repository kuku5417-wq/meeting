"""자유 편집(결정 ⑦ 15-2, 2026-11-24) — 회의자료 한 장을 개체로 자유 배치한다.

**표현만 담는다.** 캔버스에서 고친 글은 이 자료에만 남고 이슈(block)의 사실은 바뀌지 않는다
(케이스 A2 — 가장 흔한 편집이 사실 훼손이 되면 안 된다). 사실 반영은 15-3 「이슈에도 반영」에서 한다.

좌표는 슬라이드와 같은 **1920×1080**(`app/static/js/slides.js`·`app/export/pptx_builder.py` 와 같은 기준) —
PPT 출력(15-8)이 같은 자리에 그릴 수 있어야 한다.

개체 하나:
    {"id": "o3", "type": "text|photo|box", "x": 96, "y": 180, "w": 900, "h": 120,
     "text": "노즐 마모 추정", "label": "원인",
     "link": {"block": "ISS-2026-0142", "field": "cause"} | None,
     "style": {"size": 30, "bold": false, "align": "left", "tone": "fg|muted|decide|problem"}}

지키는 것
  - 저장되는 값은 모두 여기서 **다시 검증한다**(화면을 믿지 않는다). 모르는 칸은 버린다.
  - 글자 크기는 13~96 (화면 규칙: 최소 13px), 좌표·크기는 캔버스 밖으로 나가지 않게 자른다.
  - 개체 수 한도 60 — 넘으면 거절(사람이 지우게 한다. 조용히 자르지 않는다).
  - 형태(form)를 바꾸면 **새로 그리고** 직전 판을 `prev_json` 에 한 단계 남긴다(케이스 B1 「되돌리기」).
"""
from __future__ import annotations

import json
from typing import Any

from app.services import writing as w

W, H = 1920, 1080
MAX_OBJECTS = 60
MIN_SIZE, MAX_SIZE = 13, 96
MIN_W, MIN_H = 40, 24
TYPES = ("text", "photo", "box")
TONES = ("fg", "muted", "decide", "problem", "issue", "ok")
ALIGNS = ("left", "center", "right")
FIELDS = ("title", "line", "body", "cause", "act", "dec", "status", "dept")   # 개체가 가리킬 수 있는 칸
# 이슈의 **사실** 칸 ↔ 모델 칸 이름 (15-3). line·dept 는 사실이 아니라 표현·기준정보라 여기 없다.
FACT_BY_FIELD = {"title": "title", "body": "body", "cause": "cause_text", "act": "action_text",
                 "dec": "decision_needed", "status": "status"}
CHOICE_FIELDS = ("status",)      # 고르는 칸 — 캔버스 글로 덮지 않는다(이슈 화면에서 고른다)
# 개체 추가 칩(15-4) — **매번 고른다. 기본값 없음**(결정 ⑦). 안 고른 개체는 「미정」으로 남고 제출 전에 수로 알린다.
SCOPES = ("", "미정", "자료만", "진행", "사실", "새이슈")
SCOPE_LABEL = {"미정": "안 고름", "자료만": "이 자료만", "진행": "이번 주 진행",
               "사실": "이슈 사실", "새이슈": "새 이슈로"}
PICK_FIELDS = ("body", "cause", "act", "dec")      # 「이슈 사실」로 덧붙일 수 있는 칸
FIELD_LABEL = {"title": "제목", "line": "회의용 한 줄", "body": "현상", "cause": "원인",
               "act": "조치 · 계획", "dec": "결정 필요", "status": "상태", "dept": "담당"}


class FreeError(w.WriteError):
    """사람에게 그대로 보여 줄 한국어 사유 — 라우터가 400 으로 돌려준다."""


def _i(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def _clean_style(raw: Any) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    tone = str(raw.get("tone") or "fg")
    align = str(raw.get("align") or "left")
    return {
        "size": _i(raw.get("size"), MIN_SIZE, MAX_SIZE, 30),
        "bold": bool(raw.get("bold")),
        "align": align if align in ALIGNS else "left",
        "tone": tone if tone in TONES else "fg",
    }


def _clean_link(raw: Any) -> dict | None:
    """연결 = {어느 이슈, 어느 칸, 가져올 때의 값(snap)}.

    `snap` 은 「이슈가 그 사이 바뀌었나」를 보는 기준이다(케이스 C2) — 값이지 사실의 정본이 아니다.
    """
    if not isinstance(raw, dict):
        return None
    block = str(raw.get("block") or "").strip()
    field = str(raw.get("field") or "").strip()
    if not block or field not in FIELDS:
        return None
    return {"block": block, "field": field, "snap": str(raw.get("snap") or "")[:2000]}


def clean_object(raw: Any, n: int) -> dict:
    """개체 하나를 검증해 정규화. 좌표·크기는 캔버스 안으로 자른다."""
    if not isinstance(raw, dict):
        raise FreeError("개체 형식이 올바르지 않습니다. 화면을 새로 고쳐주세요.")
    kind = str(raw.get("type") or "text")
    if kind not in TYPES:
        kind = "text"
    scope = str(raw.get("scope") or "")
    if scope not in SCOPES:
        scope = ""
    w = _i(raw.get("w"), MIN_W, W, 600)
    h = _i(raw.get("h"), MIN_H, H, 80)
    x = _i(raw.get("x"), 0, W - MIN_W, 96)
    y = _i(raw.get("y"), 0, H - MIN_H, 160)
    out = {
        "id": str(raw.get("id") or f"o{n}")[:16],
        "type": kind,
        "x": x, "y": y,
        "w": min(w, W - x), "h": min(h, H - y),
        "text": str(raw.get("text") or "")[:2000],
        "label": str(raw.get("label") or "")[:40],
        "link": _clean_link(raw.get("link")),
        "style": _clean_style(raw.get("style")),
        "scope": scope,
        "scope_field": str(raw.get("scope_field") or "") if scope == "사실" else "",
        "scope_block": str(raw.get("scope_block") or "")[:24] if scope == "새이슈" else "",
    }
    if kind == "photo":
        out["photo"] = str(raw.get("photo") or "")[:64]
        out["block"] = str(raw.get("block") or "")[:24]
    return out


def clean(objects: Any) -> list[dict]:
    """개체 목록 검증. 수 한도를 넘으면 거절한다(조용히 자르지 않는다)."""
    if not isinstance(objects, list):
        raise FreeError("개체 목록이 올바르지 않습니다. 화면을 새로 고쳐주세요.")
    if len(objects) > MAX_OBJECTS:
        raise FreeError(f"한 장에 개체는 {MAX_OBJECTS}개까지입니다. 필요 없는 개체를 지워주세요.")
    return [clean_object(o, n + 1) for n, o in enumerate(objects)]


def load(it) -> list[dict]:
    """저장된 개체 목록(없으면 빈 목록). 손상된 값은 빈 목록으로 본다."""
    try:
        data = json.loads(it.objects_json or "")
    except ValueError:
        return []
    if isinstance(data, dict):
        data = data.get("objects")
    return data if isinstance(data, list) else []


def dump(objects: list[dict]) -> str:
    return json.dumps({"v": 1, "objects": objects}, ensure_ascii=False)


# ── 초안 만들기 ─────────────────────────────────────────
def _text(oid: str, x: int, y: int, w: int, h: int, text: str, *, label: str = "",
          size: int = 30, bold: bool = False, tone: str = "fg",
          link: dict | None = None) -> dict:
    return {"id": oid, "type": "text", "x": x, "y": y, "w": w, "h": h, "text": text or "",
            "label": label, "link": link, "style": {"size": size, "bold": bold, "align": "left", "tone": tone}}


def draft(item: dict) -> list[dict]:
    """장 하나(studio._item_json 결과)를 보고 지금 형태대로 개체 초안을 만든다.

    슬라이드(`slides.js`)가 그리는 것과 같은 칸 구성이다 — 자유 편집을 켠 순간 화면이 달라 보이면 안 된다.
    """
    form = item.get("form") or "card"
    blocks = item.get("blocks") or []
    b = blocks[0] if blocks else {}
    bid = str(b.get("id") or "")
    line = str(item.get("line") or "")
    out: list[dict] = []
    title = f"{b.get('title') or item.get('line') or '제목'}"
    out.append(_text("o1", 96, 96, 1728, 96, title, label="제목", size=44, bold=True,
                     link={"block": bid, "field": "title", "snap": title} if bid else None))

    if item.get("kind") == "summary":
        out.append(_text("o2", 96, 220, 1728, 90, line, label="요약", size=34))
        for n, x in enumerate(blocks[:6]):
            out.append(_text(f"o{n + 3}", 96, 330 + n * 96, 1728, 80,
                             f"{x.get('title', '')} · {x.get('ptag') or x.get('status') or ''}", label="이슈", size=28))
        return out

    line_link = {"block": bid, "field": "line", "snap": line} if bid else None
    if form == "line":
        out.append(_text("o2", 96, 420, 1728, 200, line, label="한 줄", size=40, link=line_link))
        return out

    if form == "photo":
        if b.get("photo"):
            out.append({"id": "o2", "type": "photo", "x": 96, "y": 230, "w": 1000, "h": 700,
                        "text": "", "label": "사진", "link": None, "photo": str(b.get("photo")), "block": bid,
                        "style": _clean_style({})})
        out.append(_text("o3", 1140, 230, 684, 300, line, label="한 줄", size=30, link=line_link))
        if b.get("dec"):
            out.append(_text("o4", 1140, 560, 684, 200, str(b["dec"]), label="결정 필요", size=28, tone="decide",
                             link={"block": bid, "field": "dec", "snap": issue_value(item, "dec")} if bid else None))
        return out

    if form == "detail":
        out.append(_text("o2", 96, 210, 1728, 90, line, label="한 줄", size=30, link=line_link))
        out.append(_text("o3", 96, 320, 840, 220, str(b.get("body") or "—"), label="현상", size=28,
                         link={"block": bid, "field": "body", "snap": issue_value(item, "body")} if bid else None))
        out.append(_text("o4", 984, 320, 840, 220, str(b.get("cause") or "조사 중"), label="원인", size=28,
                         link={"block": bid, "field": "cause", "snap": issue_value(item, "cause")} if bid else None))
        out.append(_text("o5", 96, 570, 1728, 220, str(b.get("act") or "—"), label="조치 · 계획", size=28,
                         link={"block": bid, "field": "act", "snap": issue_value(item, "act")} if bid else None))
        if b.get("dec"):
            out.append(_text("o6", 96, 820, 1728, 120, str(b["dec"]), label="결정 필요", size=28, tone="decide",
                             link={"block": bid, "field": "dec", "snap": issue_value(item, "dec")} if bid else None))
        return out

    # card (기본)
    out.append(_text("o2", 96, 230, 1180, 240, line, label="한 줄", size=30, link=line_link))
    out.append(_text("o3", 96, 500, 560, 90, str(b.get("dept") or ""), label="담당", size=28, tone="muted"))
    out.append(_text("o4", 716, 500, 560, 90, str(b.get("status") or ""), label="상태", size=28, tone="muted",
                     link={"block": bid, "field": "status", "snap": str(b.get("status") or "")} if bid else None))
    if b.get("photo"):
        out.append({"id": "o5", "type": "photo", "x": 1320, "y": 230, "w": 504, "h": 360,
                    "text": "", "label": "사진", "link": None, "photo": str(b.get("photo")), "block": bid,
                    "style": _clean_style({})})
    if b.get("dec"):
        out.append(_text("o6", 96, 640, 1728, 140, str(b["dec"]), label="결정 필요", size=28, tone="decide",
                         link={"block": bid, "field": "dec", "snap": issue_value(item, "dec")} if bid else None))
    return out


# ── 쓰기 ────────────────────────────────────────────────
def set_on(it, item_json: dict, on: bool) -> list[dict]:
    """자유 편집 켜기/끄기. 처음 켤 때만 초안을 만든다(껐다 켜도 꾸민 것이 살아 있다)."""
    if on and not load(it):
        it.objects_json = dump(draft(item_json))
    it.free_on = bool(on)
    it.free_rev = (it.free_rev or 0) + 1
    return load(it)


def save(it, objects: Any, base_rev: int | None = None) -> int:
    """개체 저장(자동 저장). 판 번호가 다르면 거절 — 다른 창에서 고친 것을 덮지 않는다.

    **새로 더한 개체는 서버가 「미정」으로 표시한다**(15-4) — 화면이 칩을 안 보내도 갈래 고르기를 건너뛸 수 없다.
    초안·「장에 없는 칸」으로 들어온 개체는 이슈에서 온 것이라(연결이 있다) 고를 것이 없다.
    """
    if not it.free_on:
        raise FreeError("이 장은 자유 편집이 꺼져 있습니다. 먼저 「자유 편집」을 켜주세요.")
    if base_rev is not None and int(base_rev) != int(it.free_rev or 0):
        raise FreeError("다른 곳에서 먼저 고쳤습니다. 화면을 새로 고친 뒤 다시 해주세요.")
    had = {o.get("id") for o in load(it)}
    objs = clean(objects)
    for o in objs:
        if o["id"] not in had and not o["link"] and not o["scope"]:
            o["scope"] = "미정"
    it.objects_json = dump(objs)
    it.free_rev = (it.free_rev or 0) + 1
    return it.free_rev


def change_form(it, item_json: dict, form: str) -> list[dict]:
    """형태 바꾸기 — 새 초안으로 **다시 그리고** 직전 판을 한 단계 남긴다(케이스 B1)."""
    it.prev_json = json.dumps({"form": it.form, "objects": load(it)}, ensure_ascii=False)
    it.form = form
    it.objects_json = dump(draft(item_json))
    it.free_rev = (it.free_rev or 0) + 1
    return load(it)


def can_undo(it) -> bool:
    return bool(it.prev_json)


def undo_form(it) -> list[dict]:
    """형태 바꾸기 되돌리기 — 직전 판으로. 한 단계만 돌아간다."""
    try:
        prev = json.loads(it.prev_json or "")
    except ValueError:
        prev = None
    if not isinstance(prev, dict):
        raise FreeError("되돌릴 것이 없습니다.")
    it.form = str(prev.get("form") or it.form)
    it.objects_json = dump(clean(prev.get("objects") or []))
    it.prev_json = ""
    it.free_rev = (it.free_rev or 0) + 1
    return load(it)


# ── 연결(15-3) ──────────────────────────────────────────
def issue_value(item: dict, field: str) -> str:
    """장이 들고 있는 이슈의 지금 값(표현 칸은 장 값)."""
    b = (item.get("blocks") or [{}])[0]
    if field == "line":
        return str(item.get("line") or "")
    key = {"title": "title", "body": "body", "cause": "cause", "act": "act", "dec": "dec",
           "status": "status", "dept": "dept"}.get(field, "")
    return str(b.get(key) or "") if key else ""


def _norm(v: str) -> str:
    return " ".join(str(v or "").split())


def annotate(objects: list[dict], item: dict) -> list[dict]:
    """개체마다 연결 상태를 붙인다 — 화면이 칩으로 보여 준다.

    same   이슈 값과 같다
    diff   이 자료에서 고쳐 **이슈와 다르다**(케이스 A2 — 사실을 덮지 않았다는 표시)
    stale  내가 가져온 뒤 **이슈가 바뀌었다**(케이스 C2 — 「다시 가져오기」)
    """
    out = []
    for o in objects:
        o = dict(o)
        link = o.get("link")
        if link and o.get("type") != "photo":
            cur = issue_value(item, link["field"])
            o["issue_text"] = cur
            o["field_label"] = FIELD_LABEL.get(link["field"], link["field"])
            o["fact"] = link["field"] in FACT_BY_FIELD
            o["choice"] = link["field"] in CHOICE_FIELDS
            if _norm(o.get("text")) == _norm(cur):
                o["state"] = "same"
            elif link.get("snap") and _norm(link["snap"]) != _norm(cur):
                o["state"] = "stale"
            else:
                o["state"] = "diff"
        out.append(o)
    return out


def missing_fields(item: dict, objects: list[dict]) -> list[dict]:
    """장에 올라오지 않은 이슈 칸(케이스 C4). 자동으로 넣지 않고 목록으로만 보여 준다."""
    if item.get("kind") != "single" or not (item.get("blocks") or []):
        return []
    have = {(o.get("link") or {}).get("field") for o in objects}
    out = []
    for f in ("body", "cause", "act", "dec"):
        if f in have:
            continue
        v = issue_value(item, f)
        if v:
            out.append({"field": f, "label": FIELD_LABEL[f], "text": v})
    return out


def _find(objects: list[dict], oid: str) -> dict:
    for o in objects:
        if o.get("id") == oid:
            return o
    raise FreeError("없는 개체입니다. 화면을 새로 고쳐주세요.")


def pull(it, item: dict, oid: str) -> list[dict]:
    """「다시 가져오기」 — 이슈의 지금 값을 개체로(케이스 C2)."""
    objs = load(it)
    o = _find(objs, oid)
    link = o.get("link")
    if not link:
        raise FreeError("연결이 없는 개체입니다. 먼저 칸에 연결해 주세요.")
    cur = issue_value(item, link["field"])
    o["text"] = cur
    link["snap"] = cur
    it.objects_json = dump(clean(objs))
    it.free_rev = (it.free_rev or 0) + 1
    return load(it)


def unlink(it, oid: str) -> list[dict]:
    """연결 끊기 — 글은 그대로 두고 연결만 뗀다(케이스 F1, 되돌리기는 화면 이력)."""
    objs = load(it)
    _find(objs, oid)["link"] = None
    it.objects_json = dump(clean(objs))
    it.free_rev = (it.free_rev or 0) + 1
    return load(it)


def relink(it, item: dict, oid: str, field: str) -> list[dict]:
    """다시 연결 — 어느 칸에 붙일지 사람이 고른다."""
    if item.get("kind") != "single":
        raise FreeError("요약 장의 개체는 이슈 칸에 연결하지 않습니다 — 출처는 장 아래 이슈 목록에 있습니다.")
    if field not in FIELDS:
        raise FreeError("연결할 수 있는 칸이 아닙니다.")
    b = (item.get("blocks") or [{}])[0]
    if not b.get("id"):
        raise FreeError("이 장에는 이슈가 없습니다.")
    objs = load(it)
    o = _find(objs, oid)
    o["link"] = {"block": str(b["id"]), "field": field, "snap": issue_value(item, field)}
    o["label"] = o.get("label") or FIELD_LABEL.get(field, "")
    it.objects_json = dump(clean(objs))
    it.free_rev = (it.free_rev or 0) + 1
    return load(it)


def add_field(it, item: dict, field: str) -> list[dict]:
    """장에 없는 칸을 개체로 넣기(케이스 C4) — 사람이 누를 때만, 빈 아래쪽에 놓는다."""
    objs = load(it)
    if len(objs) >= MAX_OBJECTS:
        raise FreeError(f"한 장에 개체는 {MAX_OBJECTS}개까지입니다.")
    y = min(H - 160, max([int(o.get("y", 0)) + int(o.get("h", 0)) for o in objs] or [200]) + 24)
    b = (item.get("blocks") or [{}])[0]
    o = _text(f"o{len(objs) + 1}_{field}", 96, y, 1728, 140, issue_value(item, field),
              label=FIELD_LABEL.get(field, field), size=28,
              link={"block": str(b.get("id") or ""), "field": field, "snap": issue_value(item, field)} if b.get("id") else None)
    objs.append(o)
    it.objects_json = dump(clean(objs))
    it.free_rev = (it.free_rev or 0) + 1
    return load(it)


def apply_to_issue(s, it, item: dict, oid: str, mt) -> list[dict]:
    """「이슈에도 반영」(케이스 A3) — 이 개체의 글을 이슈 **사실 칸**에 쓴다.

    이 한 번만 사실이 바뀌고, 이슈 변경 기록에 「사실변경 · 어디서」가 남는다(`issues.save_field`).
    표현 칸(회의용 한 줄·담당)과 요약 장은 반영 대상이 아니다.
    """
    from app import models as m
    from app.services import issues as iss

    objs = load(it)
    o = _find(objs, oid)
    link = o.get("link")
    if not link:
        raise FreeError("연결이 없는 개체입니다 — 먼저 어느 칸인지 골라 주세요.")
    field = link["field"]
    if field in CHOICE_FIELDS:
        raise FreeError(f"「{FIELD_LABEL.get(field, field)}」은(는) 고르는 칸입니다 — 이슈 화면에서 골라 주세요. "
                        "캔버스 글은 이 자료의 표현으로 남습니다.")
    if field not in FACT_BY_FIELD:
        raise FreeError(f"「{FIELD_LABEL.get(field, field)}」은(는) 이 자료의 표현입니다 — 이슈에 반영하지 않습니다.")
    b = s.get(m.Block, link["block"])
    if b is None:
        raise FreeError("이슈를 찾을 수 없습니다. 화면을 새로 고쳐주세요.")
    text = str(o.get("text") or "").strip()
    iss.save_field(s, b, FACT_BY_FIELD[field], text, meeting_id=getattr(mt, "id", None))
    link["snap"] = text
    it.objects_json = dump(clean(objs))
    it.free_rev = (it.free_rev or 0) + 1
    return load(it)


def changed_links(before: list[dict], after: list[dict]) -> list[dict]:
    """저장 전후로 **글이 바뀐 연결 개체** — 「자료수정」으로 기록할 것(옮기기·크기는 기록하지 않는다)."""
    old = {o.get("id"): o for o in before}
    out = []
    for o in after:
        p = old.get(o.get("id"))
        link = o.get("link")
        if not link or p is None or p.get("link") is None:
            continue
        if _norm(p.get("text")) != _norm(o.get("text")):
            out.append({"block": link["block"], "field": link["field"],
                        "before": str(p.get("text") or ""), "after": str(o.get("text") or "")})
    return out


# ── 개체 추가 칩(15-4) ──────────────────────────────────
def unchosen(objects: list[dict]) -> list[dict]:
    """갈래를 아직 안 고른 개체 — 막지 않고 제출 전에 수로 알린다(결정 ⑦)."""
    return [o for o in objects if (o.get("scope") or "") == "미정"]


def _issue_of(item: dict):
    return (item.get("blocks") or [{}])[0]


def pick(s, it, item: dict, oid: str, scope: str, field: str, mt) -> str:
    """더한 개체를 **어디에 남길지** 고른다 — 이 자료만 / 이번 주 진행 / 이슈 사실 / 새 이슈로.

    기본값이 없다(결정 ⑦ — 「이 자료만」을 기본으로 두면 진행이 기록에 남지 않는다).
    한 번 고르면 다시 고르지 않는다 — 두 번 누르면 같은 글이 두 번 덧붙는다.

    돌려주는 값: 새로 뗀 이슈 ID(「새 이슈로」일 때), 그 밖에는 빈 문자열.
    """
    from app import models as m
    from app.services import carry_over as co
    from app.services import events
    from app.services import issues as iss
    from app.services import writing as wsvc

    if scope not in ("자료만", "진행", "사실", "새이슈"):
        raise FreeError("어디에 남길지 골라 주세요 — 이 자료만 / 이번 주 진행 / 이슈 사실 / 새 이슈로.")
    objs = load(it)
    o = _find(objs, oid)
    now = o.get("scope") or ""
    if now not in ("", "미정"):
        raise FreeError(f"이 개체는 이미 「{SCOPE_LABEL.get(now, now)}」으로 보냈습니다 — "
                        "다시 보내려면 개체를 새로 더해 주세요.")
    text = str(o.get("text") or "").strip()
    if not text and scope != "자료만":
        raise FreeError("개체에 글을 적은 뒤 골라 주세요.")

    bid = str(_issue_of(item).get("id") or "")
    b = s.get(m.Block, bid) if bid else None
    if scope != "자료만" and b is None:
        raise FreeError("이 장에는 이슈가 없습니다 — 「이 자료만」으로 두세요.")
    week_id = getattr(mt, "week_id", "") or ""
    new_id = ""

    if scope == "자료만":
        if b is not None:
            events.record(s, b.id, "개체추가", after=f"자료에 개체 추가 — {text[:300]}", meeting_id=mt.id)
    elif scope == "진행":
        row = co.week_row(s, b.id, week_id)
        cur = ((row.note if row else "") or "").strip()
        co.update_line(s, b, week_id, f"{cur} / {text}" if cur else text)
        events.record(s, b.id, "개체추가", after=f"이번 주 진행에 덧붙임 — {text[:300]}", meeting_id=mt.id)
    elif scope == "사실":
        if field not in PICK_FIELDS:
            raise FreeError("어느 사실 칸에 더할지 골라 주세요 — 현상 · 원인 · 조치 · 계획 · 결정 필요.")
        key = FACT_BY_FIELD[field]
        cur = str(getattr(b, key, "") or "").strip()
        # 덧붙인다 — 줄여 쓴 글로 **덮지 않는다**(케이스 A2·A4). 사실변경 기록은 save_field 가 남긴다.
        iss.save_field(s, b, key, "\n".join([cur, text]) if cur else text, meeting_id=mt.id)
        o["scope_field"] = field
    else:                                   # 새 이슈로 떼기 — 새 ID · 태그 물려받기 · 「파생」 링크(15-5 가 합치기를 더한다)
        title = text.splitlines()[0][:80]
        nb = m.Block(id=wsvc.new_block_id(s, "issue", int((week_id or "2026")[:4])), block_type="issue",
                     title=title, body=text, status="신규", owner_department_id=b.owner_department_id,
                     created_week_id=week_id, origin="manual")
        s.add(nb)
        s.flush()
        for t in wsvc.block_tags(s, b.id):          # 기준정보 태그 물려받기(원칙 5) — 사람이 뺀 태그는 빼고
            if t.dismissed:
                continue
            s.add(m.BlockTag(block_id=nb.id, kind=t.kind, target_id=t.target_id, raw_text=t.raw_text,
                             confidence=t.confidence, confirmed=t.confirmed))
        s.add(m.BlockLink(from_block_id=b.id, to_block_id=nb.id, relation="파생"))
        co.add_history(s, nb, week_id, note=f"{b.id} 에서 떼어냄")
        events.record(s, b.id, "파생", after=f"{nb.id} 로 떼어냄 — {title}", meeting_id=mt.id)
        events.record(s, nb.id, "파생", before=b.id, after=f"{b.id} 에서 떼어냄", meeting_id=mt.id)
        # 개체는 **연결하지 않고** 새 이슈 ID 만 들고 있는다 — 연결 칩(15-3)은 이 장의 이슈를 기준으로
        # 같음·다름을 재므로, 다른 이슈에 건 연결은 「다시 가져오기」가 엉뚱한 값을 덮는다.
        # 두 이슈를 잇는 양쪽 칩은 15-5(합치기와 함께)에서 제대로 붙인다.
        o["scope_block"] = nb.id
        new_id = nb.id

    o["scope"] = scope
    it.objects_json = dump(clean(objs))
    it.free_rev = (it.free_rev or 0) + 1
    return new_id


def json_for(it) -> dict:
    """장 JSON 에 붙이는 자유 편집 정보."""
    return {"on": bool(it.free_on), "rev": int(it.free_rev or 0),
            "objects": load(it), "can_undo": can_undo(it), "max": MAX_OBJECTS}


def json_with(it, item: dict) -> dict:
    """장 JSON 에 붙이는 자유 편집 정보 + 연결 상태·장에 없는 칸(15-3)."""
    objs = annotate(load(it), item)
    return {"on": bool(it.free_on), "rev": int(it.free_rev or 0), "objects": objs,
            "can_undo": can_undo(it), "max": MAX_OBJECTS, "missing": missing_fields(item, objs),
            "fields": [{"field": f, "label": FIELD_LABEL[f]} for f in FACT_BY_FIELD],
            "unchosen": len(unchosen(objs)),                                   # 15-4 갈래 안 고른 개체 수
            "pick_fields": [{"field": f, "label": FIELD_LABEL[f]} for f in PICK_FIELDS]}
