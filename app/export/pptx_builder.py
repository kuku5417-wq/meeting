"""PPT 출력 — 회의자료 deck(`services/studio.deck` · 발행본)을 편집 가능한 PPT 로 그린다 (기능 13, M11~).

- 글은 텍스트 상자, 블록 목록(표 중심)은 PowerPoint 표, 지표는 PowerPoint 차트, 사진은 마킹을 합성한 그림 —
  받은 사람이 PowerPoint 에서 그대로 고칠 수 있게. 사진 원본은 읽기만 한다.
- 배치는 모델이 정한다. 여기서는 위치·색·글꼴만 정한다(미리보기 CSS 와 같은 비율).
- 템플릿: `app/export/templates/base.pptx` 가 있으면 그 파일의 빈 레이아웃 위에 그린다(기존 주간보고 양식을 받으면
  거기 넣는다 — 로드맵 「미정」). 없으면 python-pptx 기본 16:9.
- 발행·제출판이 아니면 머리띠에 「구성 중」. 옛 섹션 기준 합본·부서 PPT 는 M12 에서 없앴다.
"""
from __future__ import annotations

import io
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt
from sqlalchemy.orm import Session

from app import models as m
from app import settings
from app.services import photos as ph

TEMPLATE = settings.ROOT / "app" / "export" / "templates" / "base.pptx"
FONT = "맑은 고딕"
W, H = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.4)
BAND_H = Inches(0.6)
KPI_H = Inches(0.55)
# design/tokens.css 의 --slide-* 값 (2026-11-13 결정 ⑧ — 회색 머리띠·세 색). 출력물은 인쇄·화면 공유용이라 라이트 고정
C = {k: RGBColor.from_string(v) for k, v in {
    "band": "E6E9EF", "band_fg": "111114", "sec": "E6E9EF", "tag": "E5F0FD", "tag_fg": "0857B0",
    "fg": "111114", "muted": "48484D", "line": "CFD8DD", "bg": "EEF1F5", "white": "FFFFFF",
    "issue": "48484D", "problem": "B83A26", "share": "48484D", "ok": "48484D", "signal": "48484D", "danger": "B83A26",
    "decide": "111114", "accent": "0963C4", "soft": "F3F5F8"}.items()}
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


# ── 바탕 ────────────────────────────────────────────────
def _font(run, size: float, bold: bool = False, color: str = "fg") -> None:
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = C[color]
    run.font.name = FONT
    rpr = run._r.get_or_add_rPr()
    ea = rpr.find(qn("a:ea"))
    if ea is None:
        ea = rpr.makeelement(qn("a:ea"), {})
        rpr.append(ea)
    ea.set("typeface", FONT)                      # 한글 글꼴(east asian)도 같은 글꼴로


def _text(slide, x, y, w, h, lines, size=14, bold=False, color="fg", align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    """lines: 문자열 또는 [(글, 크기, 굵게, 색)] 목록. 줄마다 문단 하나."""
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(0.05)
    tf.margin_top = tf.margin_bottom = Inches(0.03)
    if isinstance(lines, str):
        lines = [(lines, size, bold, color)]
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        for part in (ln if isinstance(ln, list) else [ln]):
            txt, sz, b, col = part
            r = p.add_run()
            r.text = txt
            _font(r, sz, b, col)
    return box


def _rect(slide, x, y, w, h, fill: str, line: str | None = None):
    from pptx.enum.shapes import MSO_SHAPE
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    shp.fill.solid()
    shp.fill.fore_color.rgb = C[fill]
    if line:
        shp.line.color.rgb = C[line]
        shp.line.width = Pt(0.75)
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def _blank(prs):
    layout = prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[-1]
    slide = prs.slides.add_slide(layout)
    for ph_ in list(slide.placeholders):          # 템플릿 자리표시자는 쓰지 않는다
        ph_._element.getparent().remove(ph_._element)
    return slide


def _band(slide, left: str, right: str, state: str = "") -> None:
    _rect(slide, 0, 0, W, BAND_H, "band")
    _text(slide, MARGIN, 0, Inches(9), BAND_H, left, 20, True, "band_fg", anchor=MSO_ANCHOR.MIDDLE)
    _text(slide, W - MARGIN - Inches(3), 0, Inches(3), BAND_H, right, 16, True, "band_fg", PP_ALIGN.RIGHT, MSO_ANCHOR.MIDDLE)
    if state and state != "확정":
        tag = _rect(slide, W - MARGIN - Inches(4.6), Inches(0.13), Inches(1.4), Inches(0.34), "white")
        tf = tag.text_frame
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.margin_top = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = state
        _font(r, 12, True, "signal" if state == "작성 중" else "danger")


def _picture(slide, s: Session, photo_id: str, block_id: str, x, y, max_w, max_h):
    photo = s.get(m.Photo, photo_id)
    img = ph.compose(photo, ph.load_doc(s, photo_id, block_id), max_w=1600)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    ratio = min(max_w / img.width, max_h / img.height)
    w_, h_ = int(img.width * ratio), int(img.height * ratio)
    return slide.shapes.add_picture(buf, x + (max_w - w_) // 2, y, w_, h_)


def _new_prs():
    prs = Presentation(str(TEMPLATE)) if Path(TEMPLATE).exists() else Presentation()
    prs.slide_width, prs.slide_height = W, H
    return prs


# ── M11 회의자료(report_item) PPT ───────────────────────
# 스튜디오·회의 보기와 같은 deck(studio.deck / 발행본 snapshot)을 그린다. 형태 4종: 상세 한 장 · 카드 · 사진 강조 · 한 줄.
TYPE_LABEL = {"issue": "이슈", "problem": "문제점", "share": "공유", "dashboard": "지표"}
FORM_LABEL = {"detail": "상세 한 장", "card": "카드", "photo": "사진 강조", "line": "한 줄"}


def _photo_box(slide, s: Session, block_id: str, photo_id: str, x, y, max_w, max_h) -> bool:
    if not photo_id or s.get(m.Photo, photo_id) is None:
        return False
    try:
        _picture(slide, s, photo_id, block_id, x, y, max_w, max_h)
        return True
    except Exception:  # noqa: BLE001 — 사진 원본을 못 읽어도 장은 나간다(사진 칸만 빈다)
        return False


def _m_band(slide, left: str, right: str, state: str) -> None:
    _band(slide, left, right)
    if state:
        tag = _rect(slide, W - MARGIN - Inches(4.6), Inches(0.13), Inches(1.4), Inches(0.34), "white")
        tf = tag.text_frame
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf.margin_top = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = state
        _font(r, 12, True, "signal")


def _m_foot(slide, left: str, right: str) -> None:
    y = H - Inches(0.45)
    _rect(slide, 0, y, W, Emu(9525), "line")
    _text(slide, MARGIN, y, Inches(8), Inches(0.45), left, 11, color="muted", anchor=MSO_ANCHOR.MIDDLE)
    _text(slide, W - MARGIN - Inches(4), y, Inches(4), Inches(0.45), right, 11, color="muted", align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)


def _m_cover(prs, d: dict, state: str) -> None:
    mt, cov = d["meeting"], d["cover"]
    slide = _blank(prs)
    _m_band(slide, settings.APP_TITLE, mt["week"], state)
    _text(slide, MARGIN, Inches(1.0), W - 2 * MARGIN, Inches(0.9), mt["title"] or mt["kind_label"], 32, True)
    ver = f" · {mt['version']}판" if mt.get("version") and mt["status"] in ("발행", "제출") else ""
    _text(slide, MARGIN, Inches(1.85), W - 2 * MARGIN, Inches(0.4), mt["kind_label"] + ver, 14, color="muted")
    boxes = [("안건", cov["n"], "fg"), ("결정 필요", cov["dec"], "decide")]
    if mt["kind"] == "exec":
        boxes += [(f"장기 미결 ({settings.LONG_OPEN_WEEKS}주 이상)", cov["long"], "danger"), ("이번 주 종결", cov.get("closed", 0), "ok")]
    else:
        boxes += [("종결 승인 대기", cov["closing"], "signal"), (f"장기 미결 ({settings.LONG_OPEN_WEEKS}주 이상)", cov["long"], "danger")]
    bw = (W - 2 * MARGIN - Inches(0.3) * 3) // 4
    for i, (lab, val, col) in enumerate(boxes):
        x = MARGIN + i * (bw + Inches(0.3))
        _rect(slide, x, Inches(2.6), bw, Inches(1.3), "white", "line")
        _text(slide, x + Inches(0.15), Inches(2.65), bw - Inches(0.3), Inches(1.2), [[(str(val), 34, True, col)], [(lab, 13, False, "muted")]])
    if "submit" in cov:
        left = cov.get("left") or []
        _text(slide, MARGIN, Inches(4.3), W - 2 * MARGIN, Inches(0.8),
              [[("부서 제출 ", 14, False, "muted"), (cov["submit"], 18, True, "fg")],
               [(("미제출 — " + "·".join(left)) if left else "전 부서 제출", 13, False, "danger" if left else "ok")]])


def _m_divider(prs, d: dict, sec: dict, state: str) -> None:
    slide = _blank(prs)
    _m_band(slide, d["meeting"]["title"], d["meeting"]["week"], state)
    _text(slide, MARGIN, Inches(2.6), W - 2 * MARGIN, Inches(1.0), sec["dept"], 36, True, align=PP_ALIGN.CENTER)
    sub = f"{sec['state']} · 안건 {len(sec['items'])}" if sec["items"] else f"{sec['state']} · 안건 없음"
    _text(slide, MARGIN, Inches(3.6), W - 2 * MARGIN, Inches(0.6), sub, 16, color="muted", align=PP_ALIGN.CENTER)


def _g(v) -> str:
    return "—" if v is None else f"{v:g}"


def _m_metric(slide, d: dict, it: dict, n: int, total: int) -> None:
    """지표 요약(F16) — 왼쪽 표(이번 주·평소·코멘트), 오른쪽 이탈 지표 먼저 최대 2개의 **편집 가능한 막대 차트**(최근 6주), 아래 기간 표 합계."""
    M = it.get("metric") or {"metrics": [], "tables": [], "dept": ""}
    _m_foot(slide, f"{n} / {total}", "지표 요약")
    top, x, cw = BAND_H + Inches(0.3), MARGIN, W - 2 * MARGIN
    _text(slide, x, top, cw, Inches(0.6), [[("[지표] ", 22, True, "accent"), (it.get("line") or "이번 주 지표", 24, True, "fg")]])
    ms = M["metrics"][:8]
    tw = int(cw * 0.55)
    if ms:
        tbl = slide.shapes.add_table(len(ms) + 1, 3, x, top + Inches(0.8), tw, Inches(0.36) * (len(ms) + 1)).table
        for c, head in enumerate(("지표", "이번 주", "평소 · 코멘트")):
            cell = tbl.cell(0, c)
            cell.text = ""
            r = cell.text_frame.paragraphs[0].add_run()
            r.text = head
            _font(r, 12, True, "band_fg")
            cell.fill.solid()
            cell.fill.fore_color.rgb = C["band"]
        for i, mv in enumerate(ms, 1):
            note = (f"평소보다 {mv['flag']} " if mv["flag"] else "") + (mv.get("comment") or "")
            for c, (val, col) in enumerate(((mv["name"], "fg"), (f"{_g(mv['value'])} {mv['unit']}".strip(), "danger" if mv["flag"] else "fg"), (note or " ", "muted"))):
                cell = tbl.cell(i, c)
                cell.text = ""
                r = cell.text_frame.paragraphs[0].add_run()
                r.text = val
                _font(r, 12, c == 1, col)
                cell.fill.solid()
                cell.fill.fore_color.rgb = C["white"] if i % 2 else C["soft"]
    else:
        _text(slide, x, top + Inches(0.8), tw, Inches(0.5), "지표가 없습니다", 14, color="muted")
    cx, chw = x + tw + Inches(0.3), cw - tw - Inches(0.3)
    for k, mv in enumerate(ms[:2]):
        cd = CategoryChartData()
        cd.categories = mv["labels"]
        cd.add_series(f"{mv['name']}({mv['unit']})" if mv["unit"] else mv["name"], [v if v is not None else None for v in mv["series"]])
        gy = top + Inches(0.8) + k * Inches(2.3)
        ch = slide.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, cx, gy, chw, Inches(2.2), cd).chart
        ch.has_legend = True
        ch.legend.position = XL_LEGEND_POSITION.TOP
        ch.legend.include_in_layout = False
        ch.legend.font.size = Pt(11)
        ch.category_axis.tick_labels.font.size = Pt(10)
        ch.value_axis.tick_labels.font.size = Pt(10)
    lines = []
    for t in M.get("tables") or []:
        diffs = " · ".join(f"{r['name']} {r['diff']:+g}" + (f"({r['note']})" if r.get("note") else "") for r in t["rows"] if r.get("diff"))
        lines.append([(f"{t['name']} ", 14, True, "fg"), (f"{t['period']} · 계획 {_g(t['plan'])} · 실적 {_g(t['actual'])} {t['unit']}" + (f" · {diffs}" if diffs else ""), 12, False, "muted")])
    if lines:
        _text(slide, x, H - Inches(1.6), cw, Inches(1.0), lines)


def _m_table(slide, d: dict, it: dict, n: int, total: int) -> None:
    """기간 표(F16) — PowerPoint 표: 행 × 그 주 날짜(계획/실적) + 기간 계획·실적·차이·사유, 맨 아래 합계. 10행까지."""
    T = it.get("table")
    top, x, cw = BAND_H + Inches(0.3), MARGIN, W - 2 * MARGIN
    _m_foot(slide, f"{n} / {total}" + (f" · {T['period']}" if T else ""), "기간 표")
    if not T:
        _text(slide, x, top, cw, Inches(0.6), [[("[기간 표] ", 22, True, "accent"), (it.get("line") or "", 24, True, "fg")]])
        _text(slide, x, top + Inches(0.8), cw, Inches(0.5), "기간 표가 지워졌습니다", 14, color="muted")
        return
    sub = f"   {T['period']}" + (f" · {T['unit']}" if T["unit"] else "") + " · 칸 = 계획 / 실적"
    _text(slide, x, top, cw, Inches(0.6), [[("[기간 표] ", 22, True, "accent"), (it.get("line") or T["name"], 24, True, "fg"), (sub, 13, False, "muted")]])
    rows = T["rows"][:10]
    heads = ["행", *T["days"], "기간 계획", "실적", "차이", "사유"]
    body = [[r["name"], *[("·" if p is None and a is None else f"{_g(p)} / {_g(a)}") for p, a in r["cells"]],
             _g(r["plan"]), _g(r["actual"]), f"{r['diff']:+g}" if r.get("diff") else "—", r.get("note") or " "] for r in rows]
    tot = T["actual"] - T["plan"]
    body.append(["합계", *[" " for _ in T["days"]], _g(T["plan"]), _g(T["actual"]), f"{tot:+g}" if tot else "—", " "])
    tbl = slide.shapes.add_table(len(body) + 1, len(heads), x, top + Inches(0.8), cw, Inches(0.34) * (len(body) + 1)).table
    nd = len(T["days"])
    for c, head in enumerate(heads):
        cell = tbl.cell(0, c)
        cell.text = ""
        r = cell.text_frame.paragraphs[0].add_run()
        r.text = head
        _font(r, 11, True, "band_fg")
        cell.fill.solid()
        cell.fill.fore_color.rgb = C["band"]
    for i, vals in enumerate(body, 1):
        last = i == len(body)
        for c, val in enumerate(vals):
            cell = tbl.cell(i, c)
            cell.text = ""
            r = cell.text_frame.paragraphs[0].add_run()
            r.text = str(val)
            src = rows[i - 1] if not last else None
            off = (src is not None and 1 <= c <= nd and None not in src["cells"][c - 1] and src["cells"][c - 1][0] != src["cells"][c - 1][1])
            red = off or (c == nd + 3 and val not in ("—", " "))
            _font(r, 10 if c == len(heads) - 1 else 11, last or c == 0 or red, "danger" if red else "fg")
            cell.fill.solid()
            cell.fill.fore_color.rgb = C["soft"] if last or i % 2 == 0 else C["white"]
    if len(T["rows"]) > 10:
        _text(slide, x, H - Inches(1.2), cw, Inches(0.4), f"외 {len(T['rows']) - 10}행 — 앱 지표 화면에서 봅니다", 11, color="muted")


def _m_item(prs, s: Session, d: dict, it: dict, n: int, total: int, state: str) -> None:
    slide = _blank(prs)
    if it.get("kind") == "table":
        _m_band(slide, d["meeting"]["title"], f"{(it.get('table') or {}).get('dept', '')} 기간 표", state)
        _m_table(slide, d, it, n, total)
        return
    if it.get("kind") == "metric":
        _m_band(slide, d["meeting"]["title"], f"{(it.get('metric') or {}).get('dept', '')} 지표", state)
        _m_metric(slide, d, it, n, total)
        return
    b = it["blocks"][0] if it["blocks"] else {}
    summary = it["kind"] == "summary"
    _m_band(slide, d["meeting"]["title"], f"요약 · {len(it['blocks'])}건" if summary else b.get("dept", ""), state)
    top, x, cw = BAND_H + Inches(0.3), MARGIN, W - 2 * MARGIN
    if summary:
        where = [h for h in dict.fromkeys(z.get("hull") for z in it["blocks"]) if h]
    else:
        where = [v for v in (b.get("hull"), b.get("ev"), f"D-{b['dd']}" if b.get("dd") is not None else "") if v]
    _m_foot(slide, f"{n} / {total}" + (" · " + " · ".join(where) if where else ""), FORM_LABEL.get(it["form"], ""))
    if summary:
        _text(slide, x, top, cw, Inches(0.8), it["line"], 26, True)
        lines = [[(z["title"], 18, True, "fg"), (f"   {z.get('ptag') or z.get('status')}", 13, False, "muted")] for z in it["blocks"]]
        _text(slide, x, top + Inches(1.0), cw, Inches(4.8), lines)
        return
    pre = [(f"[{b['ptag']}] ", 20, True, "decide")] if it.get("tag_on") and b.get("ptag") else []
    kind_col = b.get("type") if b.get("type") in C else "fg"
    _text(slide, x, top, cw, Inches(0.7), [[(f"[{TYPE_LABEL.get(b.get('type'), '')}] ", 22, True, kind_col), (b.get("title", ""), 24, True, "fg")]])
    y = top + Inches(0.85)
    dec_h = Inches(0.7) if b.get("dec") else 0
    body_bottom = H - Inches(0.6) - dec_h
    form = it["form"]
    if form == "line":
        _text(slide, x, y + Inches(1.0), cw, Inches(2.5), [pre + [(it["line"] or "—", 28, False, "fg")]])
    elif form == "photo":
        pw = int(cw * 0.58)
        if not _photo_box(slide, s, b.get("id", ""), b.get("photo", ""), x, y, pw, body_bottom - y):
            _rect(slide, x, y, pw, body_bottom - y, "soft")
            _text(slide, x, y + (body_bottom - y) // 2 - Inches(0.3), pw, Inches(0.6), "사진 없음", 14, color="muted", align=PP_ALIGN.CENTER)
        _text(slide, x + pw + Inches(0.3), y, cw - pw - Inches(0.3), body_bottom - y, [pre + [(it["line"] or "—", 20, False, "fg")]])
    elif form == "detail":
        _text(slide, x, y, cw, Inches(0.6), [pre + [(it["line"] or "", 18, False, "fg")]])
        gy, gw, gh = y + Inches(0.7), (cw - Inches(0.3)) // 2, (body_bottom - y - Inches(0.8)) // 2
        cells = (("현상", b.get("body") or "—"), ("원인", b.get("cause") or "조사 중"), ("조치 · 계획", b.get("act") or "—"),
                 ("담당 · 상태", f"{b.get('dept', '')} · {b.get('status', '')}"))
        for i, (lab, val) in enumerate(cells):
            cx, cy = x + (i % 2) * (gw + Inches(0.3)), gy + (i // 2) * (gh + Inches(0.1))
            _rect(slide, cx, cy, gw, gh, "soft")
            _text(slide, cx + Inches(0.12), cy + Inches(0.08), gw - Inches(0.24), gh - Inches(0.16), [[(lab, 12, True, "muted")], [(val, 15, False, "fg")]])
    else:   # card
        tw = int(cw * 0.62)
        _text(slide, x, y, tw, body_bottom - y, [pre + [(it["line"] or "—", 20, False, "fg")], [(" ", 8, False, "fg")],
                                                 [("담당 ", 12, False, "muted"), (b.get("dept", ""), 14, True, "fg"),
                                                  ("   상태 ", 12, False, "muted"), (b.get("status", ""), 14, True, "fg")]])
        _photo_box(slide, s, b.get("id", ""), b.get("photo", ""), x + tw + Inches(0.3), y, cw - tw - Inches(0.3), body_bottom - y)
    if b.get("dec"):
        _rect(slide, x, body_bottom + Inches(0.05), Inches(0.08), dec_h - Inches(0.15), "decide")
        _text(slide, x + Inches(0.2), body_bottom + Inches(0.05), cw - Inches(0.2), dec_h - Inches(0.1),
              [[("결정 필요  ", 14, True, "decide"), (b["dec"], 15, False, "fg")]], anchor=MSO_ANCHOR.MIDDLE)


def _m_directives(prs, d: dict, n: int, total: int, state: str) -> None:
    """지난 지시사항(M12) — 표지 다음 한 장."""
    rows = d.get("directives") or []
    slide = _blank(prs)
    _m_band(slide, d["meeting"]["title"], "지난 지시사항", state)
    _m_foot(slide, f"{n} / {total}", "지시 점검")
    done = sum(1 for x in rows if x["status"] == "완료")
    lines = [[(f"지난 지시사항 {len(rows)}건 — 완료 {done}", 22, True, "fg")]]
    for x in rows:
        tail = f"완료 — {x['done_note']}" if x["status"] == "완료" else ("기한 지남" if x.get("late") else "진행 중")
        lines.append([(x["text"], 16, True, "fg"), (f"   {x['dept']} · 기한 {x['due'][-3:]} · {tail}", 12, False,
                                                    "ok" if x["status"] == "완료" else ("danger" if x.get("late") else "muted"))])
    _text(slide, MARGIN, BAND_H + Inches(0.3), W - 2 * MARGIN, H - BAND_H - Inches(1.0), lines)


def build_meeting(s: Session, d: dict, published: bool) -> bytes:
    """회의자료 PPT — 표지 + (공유회면 부서 구분 장) + 장. 제출·발행판이 아니면 머리띠에 「구성 중」."""
    state = "" if published else "구성 중"
    prs = _new_prs()
    _m_cover(prs, d, state)
    share = d["meeting"]["kind"] == "share"
    has_dir = bool(d.get("directives"))
    total = 1 + int(has_dir) + sum(len(sec["items"]) + (1 if share else 0) for sec in d["sections"])
    n = 1
    if has_dir:
        n += 1
        _m_directives(prs, d, n, total, state)
    for sec in d["sections"]:
        if share:
            n += 1
            _m_divider(prs, d, sec, state)
        for it in sec["items"]:
            n += 1
            _m_item(prs, s, d, it, n, total, state)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
