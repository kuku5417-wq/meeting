"""사진 — 업로드(원본 불변·sha256 중복 방지)·블록 연결·주석 저장·서버 합성 (기능 8, docs/03 「사진」).

원칙 1: 원본 파일은 **수정·삭제하지 않는다.** 마킹은 사진에 굽지 않고 `annotation.shapes_json` 과
`marker` 행으로 따로 두고, 출력(PPT·미리보기)할 때만 `compose()` 로 합성한다.

주석 좌표는 「EXIF 회전을 적용한 원본」의 픽셀 좌표다(브라우저가 보여주는 방향과 같다).
`shapes_json` 형식 — Konva 직렬화를 그대로 두지 않고 이 앱의 작은 스키마로 저장한다
(서버 합성·검증이 Konva 버전에 묶이지 않게):
  {"version": 1,
   "base": {"rotate": 0|90|180|270, "crop": [x, y, w, h] | null, "brightness": -0.5~0.5},
   "shapes": [{"type": "arrow"|"free", "points": [...]}, {"type": "circle", "x","y","r"},
              {"type": "rect"|"mosaic", "x","y","w","h"}, {"type": "text", "x","y","text","size"},
              {"type": "inset", "src": [x,y,w,h], "dst": [x,y,w,h]}  (+ "color", "width")],
   "markers": [{"no", "x", "y", "label", "component_id"}]}   ← marker 표에도 같은 값
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import uuid
from datetime import datetime
from pathlib import Path

from PIL import ExifTags, Image, ImageDraw, ImageEnhance, ImageFont, ImageOps, UnidentifiedImageError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import models as m
from app import settings
from app.services import writing as w
import path_config as pc

MAX_BYTES = 20 * 1024 * 1024
FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
ROLES = {"main": "사진", "before": "조치 전", "after": "조치 후"}
COLORS = {"#d4402a": "빨강", "#f0b400": "노랑", "#2f6fd6": "파랑"}     # 시안의 마킹 색 3종 (출력 이미지에 구워지는 값)
MAX_SHAPES, MAX_MARKERS = 200, 30
WORK_MAX = 2400          # 편집기 작업용 사진의 긴 변(px) — 큰 원본을 그대로 그리면 끄는 동안 버벅인다
FONT_CANDIDATES = (str(settings.ROOT / "app" / "static" / "fonts" / "MeetingSansKR-SemiBold.woff2"), "malgun.ttf")


# ── 업로드·연결 ─────────────────────────────────────────
def _taken_at(img: Image.Image) -> datetime | None:
    try:
        raw = img.getexif().get_ifd(ExifTags.IFD.Exif).get(ExifTags.Base.DateTimeOriginal)
        return datetime.strptime(raw, "%Y:%m:%d %H:%M:%S") if raw else None
    except Exception:  # noqa: BLE001 — EXIF 가 없거나 깨짐 → 촬영일 모름
        return None


def store(s: Session, data: bytes, uploaded_by: int | None = None) -> tuple[m.Photo, bool]:
    """원본 저장. 같은 파일(sha256)이 이미 있으면 그 사진을 돌려준다 → (사진, 새로 만들었나)."""
    if not data:
        raise w.WriteError("빈 파일입니다. 사진을 다시 골라주세요.")
    if len(data) > MAX_BYTES:
        raise w.WriteError(f"사진이 너무 큽니다({len(data) // 1024 // 1024}MB). 20MB 이하로 줄여주세요.")
    sha = hashlib.sha256(data).hexdigest()
    same = s.scalar(select(m.Photo).where(m.Photo.sha256 == sha))
    if same is not None:
        return same, False
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        img = Image.open(io.BytesIO(data))
        fmt = img.format
        upright = ImageOps.exif_transpose(img)
    except (UnidentifiedImageError, OSError, SyntaxError) as e:
        raise w.WriteError("사진 파일로 읽을 수 없습니다. JPG·PNG·WEBP 사진을 올려주세요.") from e
    if fmt not in FORMATS:
        raise w.WriteError(f"{fmt} 형식은 받지 않습니다. JPG·PNG·WEBP 사진을 올려주세요.")
    rel = Path("photos") / sha[:2] / f"{sha}{FORMATS[fmt]}"
    dest = pc.get_data_dir() / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():                                  # 원본은 한 번 쓰고 다시는 건드리지 않는다
        tmp = dest.with_name(f".{uuid.uuid4().hex}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    photo = m.Photo(id=w._next_seq(s, m.Photo, "PH-", 5), file_path=rel.as_posix(), sha256=sha,
                    width=upright.width, height=upright.height, taken_at=_taken_at(img), uploaded_by=uploaded_by)
    s.add(photo)
    s.flush()
    return photo, True


def original_path(photo: m.Photo) -> Path:
    return pc.get_data_dir() / photo.file_path


def link(s: Session, photo: m.Photo, block: m.Block, role: str) -> m.PhotoLink:
    if role not in ROLES:
        raise w.WriteError("사진 칸이 올바르지 않습니다(사진 / 조치 전 / 조치 후).")
    row = s.get(m.PhotoLink, (photo.id, block.id, role))
    if row is not None:
        return row
    # 같은 구분(조치 전·후 포함)에 여러 장을 둘 수 있다(2026-10-21) — 순서는 order_no
    n = max((lk.order_no for lk, _ in block_photos(s, block.id)), default=-1) + 1
    row = m.PhotoLink(photo_id=photo.id, block_id=block.id, role=role, order_no=n)
    s.add(row)
    s.flush()
    return row


def unlink(s: Session, photo_id: str, block_id: str, role: str) -> None:
    """블록에서 사진을 뗀다. **원본 파일과 photo 행은 남긴다**(다른 블록이 쓸 수 있고, 원본 불변)."""
    s.execute(delete(m.PhotoLink).where(m.PhotoLink.photo_id == photo_id, m.PhotoLink.block_id == block_id,
                                        m.PhotoLink.role == role))
    s.flush()


def update_info(s: Session, photo_id: str, block: m.Block, role: str, to_role: str, caption: str, note: str) -> m.PhotoLink:
    """사진 구분·이름·설명을 한 번에. 구분이 바뀌면 연결 행을 옮긴다(원본·마킹·순서는 그대로)."""
    if to_role not in ROLES:
        raise w.WriteError("사진 구분이 올바르지 않습니다(사진 / 조치 전 / 조치 후).")
    row = s.get(m.PhotoLink, (photo_id, block.id, role))
    if row is None:
        raise w.WriteError(f"{block.id} 에 {ROLES.get(role, role)} 구분으로 연결된 {photo_id} 가 없습니다.")
    if to_role != role:
        if s.get(m.PhotoLink, (photo_id, block.id, to_role)) is not None:
            raise w.WriteError(f"같은 사진이 이미 {ROLES[to_role]} 구분에 있습니다. 하나를 떼고 바꿔주세요.")
        new = m.PhotoLink(photo_id=photo_id, block_id=block.id, role=to_role, order_no=row.order_no,
                          caption=row.caption or "", note=row.note or "")
        s.delete(row)
        s.flush()
        s.add(new)
        row = new
    row.caption = (caption or "").strip()[:80]
    row.note = (note or "").strip()[:500]
    s.flush()
    return row


def move(s: Session, photo_id: str, block_id: str, role: str, step: int) -> bool:
    """사진 순서를 앞(-1)/뒤(+1)로. 끝이면 그대로 두고 False."""
    links = [lk for lk, _ in block_photos(s, block_id)]
    i = next((k for k, lk in enumerate(links) if (lk.photo_id, lk.role) == (photo_id, role)), None)
    if i is None or not (0 <= i + step < len(links)):
        return False
    links[i], links[i + step] = links[i + step], links[i]
    for n, lk in enumerate(links):
        lk.order_no = n
    s.flush()
    return True


def block_photos(s: Session, block_id: str) -> list[tuple[m.PhotoLink, m.Photo]]:
    rows = s.execute(select(m.PhotoLink, m.Photo).join(m.Photo, m.Photo.id == m.PhotoLink.photo_id)
                     .where(m.PhotoLink.block_id == block_id).order_by(m.PhotoLink.order_no)).all()
    return [(a, b) for a, b in rows]


# ── 주석 ────────────────────────────────────────────────
def get_annotation(s: Session, photo_id: str, block_id: str) -> m.Annotation | None:
    return s.scalar(select(m.Annotation).where(m.Annotation.photo_id == photo_id, m.Annotation.block_id == block_id))


def empty_doc() -> dict:
    return {"version": 1, "base": {"rotate": 0, "crop": None, "brightness": 0}, "shapes": [], "markers": []}


def load_doc(s: Session, photo_id: str, block_id: str) -> dict:
    ann = get_annotation(s, photo_id, block_id)
    if ann is None:
        return empty_doc()
    try:
        return json.loads(ann.shapes_json)
    except ValueError:  # noqa: PERF203 — 깨진 JSON → 빈 주석으로 연다(원본은 그대로)
        return empty_doc()


def _num(v, lo: float, hi: float) -> float:
    if not isinstance(v, (int, float)) or isinstance(v, bool) or math.isnan(v):
        raise w.WriteError("주석 좌표가 숫자가 아닙니다.")
    return float(min(max(v, lo), hi))


def clean_doc(s: Session, doc: dict, photo: m.Photo) -> dict:
    """화면에서 온 주석을 검사·정리한다 — 모르는 도형·색·범위 밖 값은 받지 않는다."""
    W, H = photo.width or 1, photo.height or 1
    if not isinstance(doc, dict):
        raise w.WriteError("주석 형식이 올바르지 않습니다.")
    base_in = doc.get("base") or {}
    rot = base_in.get("rotate", 0)
    if rot not in (0, 90, 180, 270):
        raise w.WriteError("회전은 90도 단위만 됩니다.")
    crop = base_in.get("crop")
    if crop is not None:
        x, y = _num(crop[0], 0, W), _num(crop[1], 0, H)
        cw, ch = _num(crop[2], 1, W - x), _num(crop[3], 1, H - y)
        crop = [x, y, cw, ch] if cw >= 8 and ch >= 8 else None
    base = {"rotate": rot, "crop": crop, "brightness": _num(base_in.get("brightness", 0), -0.5, 0.5)}

    shapes_in = doc.get("shapes") or []
    if len(shapes_in) > MAX_SHAPES:
        raise w.WriteError(f"도형이 너무 많습니다({len(shapes_in)}개). {MAX_SHAPES}개 이하로 줄여주세요.")
    shapes = []
    for sh in shapes_in:
        t = sh.get("type")
        color = sh.get("color", "#d4402a")
        if color not in COLORS:
            raise w.WriteError("마킹 색은 빨강·노랑·파랑만 쓸 수 있습니다.")
        width = _num(sh.get("width", 4), 1, 40)
        if t in ("arrow", "free"):
            pts = sh.get("points") or []
            if len(pts) < 4 or len(pts) % 2 or len(pts) > 4000:
                raise w.WriteError("선 좌표가 올바르지 않습니다.")
            pts = [_num(v, 0, W if i % 2 == 0 else H) for i, v in enumerate(pts)]
            shapes.append({"type": t, "points": pts, "color": color, "width": width})
        elif t == "circle":
            shapes.append({"type": t, "x": _num(sh["x"], 0, W), "y": _num(sh["y"], 0, H),
                           "r": _num(sh["r"], 1, max(W, H)), "color": color, "width": width})
        elif t in ("rect", "mosaic"):
            x, y = _num(sh["x"], 0, W), _num(sh["y"], 0, H)
            item = {"type": t, "x": x, "y": y, "w": _num(sh["w"], 1, W - x), "h": _num(sh["h"], 1, H - y)}
            if t == "rect":
                item.update(color=color, width=width)
            shapes.append(item)
        elif t == "text":
            text = str(sh.get("text") or "").strip()[:100]
            if text:
                shapes.append({"type": t, "x": _num(sh["x"], 0, W), "y": _num(sh["y"], 0, H), "text": text,
                               "size": _num(sh.get("size", 28), 8, 200), "color": color})
        elif t == "inset":
            sx, sy = _num(sh["src"][0], 0, W), _num(sh["src"][1], 0, H)
            dx, dy = _num(sh["dst"][0], 0, W), _num(sh["dst"][1], 0, H)
            shapes.append({"type": t, "src": [sx, sy, _num(sh["src"][2], 2, W - sx), _num(sh["src"][3], 2, H - sy)],
                           "dst": [dx, dy, _num(sh["dst"][2], 4, W - dx), _num(sh["dst"][3], 4, H - dy)],
                           "color": color, "width": width})
        else:
            raise w.WriteError(f"모르는 도형입니다: {t}")

    markers_in = doc.get("markers") or []
    if len(markers_in) > MAX_MARKERS:
        raise w.WriteError(f"번호 마커는 {MAX_MARKERS}개까지입니다.")
    markers = []
    for i, mk in enumerate(markers_in, 1):
        comp = mk.get("component_id") or None
        if comp is not None and s.get(m.Component, comp) is None:
            raise w.WriteError(f"마커 {i}의 부위가 기준정보에 없습니다.")
        markers.append({"no": i, "x": _num(mk["x"], 0, W), "y": _num(mk["y"], 0, H),
                        "label": str(mk.get("label") or "").strip()[:100], "component_id": comp})
    return {"version": 1, "base": base, "shapes": shapes, "markers": markers}


def save_annotation(s: Session, photo: m.Photo, block: m.Block, doc: dict) -> m.Annotation:
    if s.get(m.PhotoLink, (photo.id, block.id, "main")) is None and not any(
            p.id == photo.id for _, p in block_photos(s, block.id)):
        raise w.WriteError("이 블록에 연결된 사진이 아닙니다.")
    doc = clean_doc(s, doc, photo)
    ann = get_annotation(s, photo.id, block.id)
    if ann is None:
        ann = m.Annotation(photo_id=photo.id, block_id=block.id)
        s.add(ann)
    ann.shapes_json = json.dumps(doc, ensure_ascii=False)
    ann.updated_at = datetime.now()
    s.flush()
    s.execute(delete(m.Marker).where(m.Marker.annotation_id == ann.id))
    for mk in doc["markers"]:
        s.add(m.Marker(annotation_id=ann.id, no=mk["no"], x=mk["x"], y=mk["y"], label=mk["label"],
                       component_id=mk["component_id"]))
    s.flush()
    return ann


def markers_missing_part(s: Session, block_id: str) -> int:
    """부위도 설명도 없는 마커 수 — 확정 전 체크. 부위 목록에 맞는 게 없으면 설명만 적어도 된다(2026-10-21)."""
    return len(s.scalars(select(m.Marker.id).join(m.Annotation, m.Annotation.id == m.Marker.annotation_id)
                         .where(m.Annotation.block_id == block_id, m.Marker.component_id.is_(None),
                                func.trim(func.coalesce(m.Marker.label, "")) == "")).all())


def component_options(s: Session, block_id: str) -> list[tuple[str, str]]:
    """마커 부위 후보 — 블록 장비의 모델 부위 먼저, 그다음 모델 공통 부위."""
    eq_ids = s.scalars(select(m.BlockTag.target_id).where(m.BlockTag.block_id == block_id,
                                                          m.BlockTag.kind == "installed_equipment",
                                                          m.BlockTag.target_id.is_not(None))).all()
    models = {e.equipment_model_id for e in (s.get(m.InstalledEquipment, i) for i in eq_ids) if e}
    rows = s.scalars(select(m.Component).order_by(m.Component.id)).all()
    first = [(c.id, c.name) for c in rows if c.equipment_model_id in models]
    rest = [(c.id, c.name) for c in rows if c.equipment_model_id not in models]
    return first + rest


# ── 합성 ────────────────────────────────────────────────
def _font(size: int) -> ImageFont.ImageFont:
    for f in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(f, size)
        except OSError:  # noqa: PERF203 — 다음 후보
            continue
    return ImageFont.load_default(size=size)


def _arrow(d: ImageDraw.ImageDraw, x1, y1, x2, y2, color, width) -> None:
    d.line([(x1, y1), (x2, y2)], fill=color, width=int(width))
    ang = math.atan2(y2 - y1, x2 - x1)
    head = max(12.0, width * 4)
    pts = [(x2, y2)] + [(x2 - head * math.cos(ang + s), y2 - head * math.sin(ang + s)) for s in (0.45, -0.45)]
    d.polygon(pts, fill=color)


def compose(photo: m.Photo, doc: dict | None, max_w: int | None = None) -> Image.Image:
    """원본 + 주석 → 출력 이미지(RGB). 원본 파일은 읽기만 한다."""
    with Image.open(original_path(photo)) as raw:
        img = ImageOps.exif_transpose(raw).convert("RGB")
    doc = doc or empty_doc()
    base = doc.get("base") or {}
    if base.get("brightness"):
        img = ImageEnhance.Brightness(img).enhance(1 + float(base["brightness"]))
    shapes = doc.get("shapes") or []
    for sh in shapes:                                      # 모자이크 먼저 — 위에 그리는 표시는 가리지 않는다
        if sh["type"] == "mosaic":
            box = tuple(int(v) for v in (sh["x"], sh["y"], sh["x"] + sh["w"], sh["y"] + sh["h"]))
            region = img.crop(box)
            cell = max(6, int(min(region.size) / 8) or 6)
            small = region.resize((max(1, region.width // cell), max(1, region.height // cell)), Image.Resampling.BILINEAR)
            img.paste(small.resize(region.size, Image.Resampling.NEAREST), box[:2])
    d = ImageDraw.Draw(img)
    for sh in shapes:
        t, c = sh["type"], sh.get("color", "#d4402a")
        if t == "arrow":
            p = sh["points"]
            _arrow(d, p[0], p[1], p[-2], p[-1], c, sh["width"])
        elif t == "free":
            d.line(list(zip(sh["points"][::2], sh["points"][1::2])), fill=c, width=int(sh["width"]), joint="curve")
        elif t == "circle":
            d.ellipse([sh["x"] - sh["r"], sh["y"] - sh["r"], sh["x"] + sh["r"], sh["y"] + sh["r"]], outline=c, width=int(sh["width"]))
        elif t == "rect":
            d.rectangle([sh["x"], sh["y"], sh["x"] + sh["w"], sh["y"] + sh["h"]], outline=c, width=int(sh["width"]))
        elif t == "text":
            d.text((sh["x"], sh["y"]), sh["text"], fill=c, font=_font(int(sh["size"])),
                   stroke_width=max(1, int(sh["size"] / 14)), stroke_fill="#ffffff")
        elif t == "inset":
            sx, sy, sw, sh_ = sh["src"]
            dx, dy, dw, dh = sh["dst"]
            zoom = img.crop((int(sx), int(sy), int(sx + sw), int(sy + sh_))).resize((int(dw), int(dh)), Image.Resampling.LANCZOS)
            d.line([(sx + sw / 2, sy + sh_ / 2), (dx + dw / 2, dy + dh / 2)], fill=c, width=2)
            d.rectangle([sx, sy, sx + sw, sy + sh_], outline=c, width=2)
            img.paste(zoom, (int(dx), int(dy)))
            d.rectangle([dx, dy, dx + dw, dy + dh], outline=c, width=int(sh["width"]))
    r = max(14, int(min(img.size) / 30))
    for mk in doc.get("markers") or []:
        x, y = mk["x"], mk["y"]
        d.ellipse([x - r, y - r, x + r, y + r], fill="#d4402a", outline="#ffffff", width=max(2, r // 6))
        d.text((x, y), str(mk["no"]), fill="#ffffff", font=_font(int(r * 1.2)), anchor="mm")
    if base.get("crop"):
        x, y, cw, ch = base["crop"]
        img = img.crop((int(x), int(y), int(x + cw), int(y + ch)))
    if base.get("rotate"):
        img = img.rotate(-int(base["rotate"]), expand=True)          # 시계 방향
    if max_w and img.width > max_w:
        img = img.resize((max_w, round(img.height * max_w / img.width)), Image.Resampling.LANCZOS)
    return img


def render_png(photo: m.Photo, doc: dict | None, max_w: int | None = None) -> bytes:
    buf = io.BytesIO()
    compose(photo, doc, max_w).save(buf, format="PNG", optimize=True)
    return buf.getvalue()
