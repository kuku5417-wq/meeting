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
FIELDS = ("title", "line", "body", "cause", "act", "dec", "status", "dept")   # 연결할 수 있는 이슈 칸(15-3 에서 쓴다)


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
    if not isinstance(raw, dict):
        return None
    block = str(raw.get("block") or "").strip()
    field = str(raw.get("field") or "").strip()
    if not block or field not in FIELDS:
        return None
    return {"block": block, "field": field}


def clean_object(raw: Any, n: int) -> dict:
    """개체 하나를 검증해 정규화. 좌표·크기는 캔버스 안으로 자른다."""
    if not isinstance(raw, dict):
        raise FreeError("개체 형식이 올바르지 않습니다. 화면을 새로 고쳐주세요.")
    kind = str(raw.get("type") or "text")
    if kind not in TYPES:
        kind = "text"
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
                     link={"block": bid, "field": "title"} if bid else None))

    if item.get("kind") == "summary":
        out.append(_text("o2", 96, 220, 1728, 90, line, label="요약", size=34))
        for n, x in enumerate(blocks[:6]):
            out.append(_text(f"o{n + 3}", 96, 330 + n * 96, 1728, 80,
                             f"{x.get('title', '')} · {x.get('ptag') or x.get('status') or ''}", label="이슈", size=28))
        return out

    if form == "line":
        out.append(_text("o2", 96, 420, 1728, 200, line, label="한 줄", size=40,
                         link={"block": bid, "field": "line"} if bid else None))
        return out

    if form == "photo":
        if b.get("photo"):
            out.append({"id": "o2", "type": "photo", "x": 96, "y": 230, "w": 1000, "h": 700,
                        "text": "", "label": "사진", "link": None, "photo": str(b.get("photo")), "block": bid,
                        "style": _clean_style({})})
        out.append(_text("o3", 1140, 230, 684, 300, line, label="한 줄", size=30))
        if b.get("dec"):
            out.append(_text("o4", 1140, 560, 684, 200, f"결정 필요 — {b['dec']}", label="결정 필요", size=28, tone="decide",
                             link={"block": bid, "field": "dec"} if bid else None))
        return out

    if form == "detail":
        out.append(_text("o2", 96, 210, 1728, 90, line, label="한 줄", size=30))
        out.append(_text("o3", 96, 320, 840, 220, str(b.get("body") or "—"), label="현상", size=28,
                         link={"block": bid, "field": "body"} if bid else None))
        out.append(_text("o4", 984, 320, 840, 220, str(b.get("cause") or "조사 중"), label="원인", size=28,
                         link={"block": bid, "field": "cause"} if bid else None))
        out.append(_text("o5", 96, 570, 1728, 220, str(b.get("act") or "—"), label="조치 · 계획", size=28,
                         link={"block": bid, "field": "act"} if bid else None))
        if b.get("dec"):
            out.append(_text("o6", 96, 820, 1728, 120, f"결정 필요 — {b['dec']}", label="결정 필요", size=28, tone="decide",
                             link={"block": bid, "field": "dec"} if bid else None))
        return out

    # card (기본)
    out.append(_text("o2", 96, 230, 1180, 240, line, label="한 줄", size=30))
    out.append(_text("o3", 96, 500, 560, 90, f"담당 {b.get('dept') or ''}", label="담당", size=28, tone="muted"))
    out.append(_text("o4", 716, 500, 560, 90, f"상태 {b.get('status') or ''}", label="상태", size=28, tone="muted",
                     link={"block": bid, "field": "status"} if bid else None))
    if b.get("photo"):
        out.append({"id": "o5", "type": "photo", "x": 1320, "y": 230, "w": 504, "h": 360,
                    "text": "", "label": "사진", "link": None, "photo": str(b.get("photo")), "block": bid,
                    "style": _clean_style({})})
    if b.get("dec"):
        out.append(_text("o6", 96, 640, 1728, 140, f"결정 필요 — {b['dec']}", label="결정 필요", size=28, tone="decide",
                         link={"block": bid, "field": "dec"} if bid else None))
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
    """개체 저장(자동 저장). 판 번호가 다르면 거절 — 다른 창에서 고친 것을 덮지 않는다."""
    if not it.free_on:
        raise FreeError("이 장은 자유 편집이 꺼져 있습니다. 먼저 「자유 편집」을 켜주세요.")
    if base_rev is not None and int(base_rev) != int(it.free_rev or 0):
        raise FreeError("다른 곳에서 먼저 고쳤습니다. 화면을 새로 고친 뒤 다시 해주세요.")
    it.objects_json = dump(clean(objects))
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


def json_for(it) -> dict:
    """장 JSON 에 붙이는 자유 편집 정보."""
    return {"on": bool(it.free_on), "rev": int(it.free_rev or 0),
            "objects": load(it), "can_undo": can_undo(it), "max": MAX_OBJECTS}
