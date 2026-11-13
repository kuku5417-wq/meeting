"""외부 자료 가져오기 — M13 (2026-10-23, F1·F14·F22, 최종 시안 design/mockups/v2m-import).

입구 하나: 메모 붙여넣기 · 파일(.pptx·.html·.pdf·.xlsx) · 메일함. 메모는 지금의 「메모 → AI 정리」를 그대로 쓰고(바로 이슈가 된다),
PPT·HTML·PDF·엑셀·메일은 **조각**(장·절·쪽·시트·메일 본문)으로 나눠 사람이 판정한다 — 기존 이슈에 붙이기 / 새 이슈 / 건너뛰기 → 「반영하기」.

- 원본은 바꾸지 않고 `<base>/meeting/imports/<job>/` 에 보관한다(원칙 1). 조각의 글은 원본에서 뽑은 그대로.
- 연결 후보는 근거가 있는 것만(원칙 3): 이슈 ID 글자 · 호선 · 장비 별칭(별칭 사전) · 제목 낱말. 이유를 함께 보인다.
  (AI 유사도 단계는 사내 LLM 사양이 정해지면 그 뒤에 얹는다 — 지금은 규칙 점수만.)
- 붙이기 = 그 이슈의 이번 주 한 줄(고칠 수 있음) + 조각의 그림을 사진으로. 새 이슈 = 조각 글을 메모로 저장하고 AI 정리
  (근거 줄·별칭·지표 규칙이 메모와 같다). 반영한 조각은 이슈 원장 「주차별 진행」에 「외부 자료」로 보인다.
- 메신저 대화 붙여넣기는 시간·보낸 사람 줄을 걷어내고 저장한다 — 이름은 저장하지 않는다(개인정보 최소수집, 공통 규칙 7).
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from datetime import date, timedelta
from xml.etree import ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

import path_config as pc
from app import models as m
from app import settings
from app.services import alias as alias_svc
from app.services import carry_over as co
from app.services import drm_reader
from app.services import extract as ex
from app.services import photos as ph
from app.services import weeks
from app.services import writing as w
from sn_util import ensure_sn

KINDS = {"pptx": "PPT", "html": "HTML", "pdf": "PDF", "xlsx": "엑셀", "mail": "메일"}
FILE_EXT = {".pptx": "pptx", ".html": "html", ".htm": "html", ".pdf": "pdf", ".xlsx": "xlsx"}
XLSX_CHUNK = 60            # 엑셀 시트는 60행마다 한 조각(판정 단위가 너무 커지지 않게)
PDF_MAX_IMAGES = 4         # PDF 쪽마다 그림은 4개까지(로고·아이콘이 수십 개 붙는 것 방지)
DECISIONS = {"link": "기존 이슈에 붙이기", "new": "새 이슈", "skip": "건너뛰기"}
_ID_RE = re.compile(r"\b(?:ISS|PRB|SHR)-\d{4}-\d{4}\b")
_HULL_RE = re.compile(r"(?<![0-9A-Za-z])(?:SN|S)?(\d{4})(?![0-9])", re.I)
_WORD_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")
_IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}


class ImportError_(w.WriteError):
    """화면에 그대로 보여줄 한국어 사유."""


# ── 메신저 대화 걷어내기(F1) ─────────────────────────────
_MSG_PREFIX = [
    re.compile(r"^\[[^\]]{1,20}\]\s*\[(?:오전|오후)\s*\d{1,2}:\d{2}\]\s*"),                       # [홍길동] [오후 3:12] 내용
    re.compile(r"^(?:\d{4}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}\.?\s*)?(?:오전|오후)?\s*\d{1,2}:\d{2}(?::\d{2})?\s*,?\s*[^:\s][^:]{0,19}\s*:\s+"),  # 2026.10.23 오후 3:12, 홍길동 : 내용
]
_MSG_DROP = [
    re.compile(r"^-*\s*\d{4}년\s*\d{1,2}월\s*\d{1,2}일.*-*\s*$"),                                   # 날짜 머리줄
    re.compile(r"^[^\s:]{2,10}\s+(?:오전|오후)?\s*\d{1,2}:\d{2}\s*$"),                               # 홍길동 오후 3:12 (이름·시간만 있는 줄)
    re.compile(r"님이 (?:들어왔습니다|나갔습니다|초대했습니다)|(?:사진|파일|동영상)을 보냈습니다|삭제된 메시지입니다"),
]


@dataclass
class Cleaned:
    text: str
    removed: int = 0          # 걷어낸 머리줄·시스템 줄 수
    stripped: int = 0         # 앞의 시간·이름을 떼어 낸 줄 수

    @property
    def messenger(self) -> bool:
        return self.removed + self.stripped >= 2


def clean_messenger(text: str) -> Cleaned:
    """메신저 대화처럼 보이면(시간·이름 머리줄이 2줄 이상) 시간·보낸 사람을 걷어낸다. 아니면 그대로."""
    out, removed, stripped = [], 0, 0
    for ln in (text or "").splitlines():
        if any(p.search(ln) for p in _MSG_DROP):
            removed += 1
            continue
        for p in _MSG_PREFIX:
            new = p.sub("", ln, count=1)
            if new != ln:
                stripped += 1
                ln = new
                break
        out.append(ln)
    c = Cleaned("\n".join(out), removed, stripped)
    return c if c.messenger else Cleaned(text or "")


# ── 조각 나누기 ─────────────────────────────────────────
@dataclass
class Piece:
    no: int
    kind: str
    title: str
    text: str
    images: list[tuple[str, bytes]] = field(default_factory=list)


def _shape_texts(shape) -> list[str]:
    out: list[str] = []
    if getattr(shape, "shape_type", None) == 6 and hasattr(shape, "shapes"):          # 그룹
        for sh in shape.shapes:
            out += _shape_texts(sh)
        return out
    if getattr(shape, "has_table", False) and shape.has_table:
        for row in shape.table.rows:
            out.append("\t".join(c.text.strip() for c in row.cells))
    elif getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        out += [p.text.strip() for p in shape.text_frame.paragraphs if p.text.strip()]
    return out


def _shape_images(shape, n: int) -> list[tuple[str, bytes]]:
    out = []
    if getattr(shape, "shape_type", None) == 6 and hasattr(shape, "shapes"):
        for sh in shape.shapes:
            out += _shape_images(sh, n + len(out))
        return out
    if getattr(shape, "shape_type", None) == 13:                                       # 그림
        try:
            out.append((f"img{n + 1}.{shape.image.ext}", shape.image.blob))
        except Exception:  # noqa: BLE001 — 연결만 된 그림(파일 없음) → 건너뜀
            pass
    return out


def parse_pptx(data: bytes) -> list[Piece]:
    """장마다 제목·글·표·그림."""
    from pptx import Presentation
    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001 — 깨진 파일 → 사유 안내
        raise ImportError_(f"PPT 파일을 읽지 못했습니다({type(e).__name__}). PowerPoint 에서 .pptx 로 다시 저장해 올려주세요.") from e
    out = []
    for i, slide in enumerate(prs.slides, 1):
        title = ""
        try:
            if slide.shapes.title is not None:
                title = slide.shapes.title.text.strip()
        except Exception:  # noqa: BLE001 — 제목 자리 없음
            title = ""
        lines, imgs = [], []
        for sh in slide.shapes:
            if title and getattr(sh, "is_placeholder", False) and sh == slide.shapes.title:
                continue
            lines += _shape_texts(sh)
            imgs += _shape_images(sh, len(imgs))
        text = "\n".join(lines).strip()
        if not (title or text or imgs):
            continue
        out.append(Piece(i, "slide", (title or (lines[0] if lines else f"{i}장"))[:200], text, imgs))
    return out


class _HTMLText(HTMLParser):
    """제목(h1~h3)마다 절로 나눈다. script·style 은 버린다. 표는 칸을 탭으로."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[list] = [["", []]]
        self.buf: list[str] = []
        self.skip = 0
        self.head = False
        self.row: list[str] | None = None
        self.cell: list[str] | None = None

    def _flush(self) -> None:
        t = " ".join("".join(self.buf).split())
        self.buf = []
        if t:
            self.sections[-1][1].append(t)

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "title"):
            self.skip += 1
        elif tag in ("h1", "h2", "h3"):
            self._flush()
            self.head = True
        elif tag == "tr":
            self._flush()
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []
        elif tag in ("p", "li", "br", "div", "section", "article"):
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("h1", "h2", "h3") and self.head:
            t = " ".join("".join(self.buf).split())
            self.buf, self.head = [], False
            self.sections.append([t, []])
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if any(self.row):
                self.sections[-1][1].append("\t".join(self.row))
            self.row = None
        elif tag in ("p", "li", "div", "section", "article"):
            self._flush()

    def handle_data(self, data):
        if self.skip:
            return
        if self.cell is not None:
            self.cell.append(data)
        else:
            self.buf.append(data)


def html_text(html: str) -> list[tuple[str, list[str]]]:
    p = _HTMLText()
    p.feed(html or "")
    p._flush()
    return [(t, lines) for t, lines in p.sections if t or lines]


def parse_html(data: bytes) -> list[Piece]:
    raw = data.decode("utf-8", "replace") if b"charset=euc-kr" not in data[:2000].lower() else data.decode("cp949", "replace")
    out = []
    for i, (title, lines) in enumerate(html_text(raw), 1):
        text = "\n".join(lines).strip()
        if not (title or text):
            continue
        out.append(Piece(len(out) + 1, "section", (title or (lines[0] if lines else f"{i}절"))[:200], text))
    return out


def parse_pdf(data: bytes) -> list[Piece]:
    """쪽마다 글·그림. 글이 없는 쪽(스캔본)은 그림만 — 글자 읽기(OCR)는 사내 OCR 사양이 정해진 뒤."""
    from pypdf import PdfReader
    try:
        rd = PdfReader(io.BytesIO(data))
        if rd.is_encrypted and not rd.decrypt(""):
            raise ImportError_("암호가 걸린 PDF 입니다. 암호를 풀어 저장한 뒤 올려주세요.")
        pages = list(rd.pages)
    except ImportError_:
        raise
    except Exception as e:  # noqa: BLE001 — 깨진 파일 → 사유 안내
        raise ImportError_(f"PDF 파일을 읽지 못했습니다({type(e).__name__}). 다른 프로그램에서 PDF 로 다시 저장해 올려주세요.") from e
    out = []
    for i, pg in enumerate(pages, 1):
        try:
            lines = [ln.strip() for ln in (pg.extract_text() or "").splitlines() if ln.strip()]
        except Exception:  # noqa: BLE001 — 글꼴 표가 깨진 쪽 → 글 없이
            lines = []
        imgs = []
        try:
            for k, im in enumerate(pg.images):
                if len(imgs) >= PDF_MAX_IMAGES:
                    break
                if Path(im.name).suffix.lower() in _IMG_EXT and len(im.data) > 2048:   # 아주 작은 그림(점·선)은 버린다
                    imgs.append((f"p{i}_{k}{Path(im.name).suffix.lower()}", im.data))
        except Exception:  # noqa: BLE001 — 그림 필터 미지원 → 글만
            pass
        if not (lines or imgs):
            continue
        title = lines[0] if lines else f"{i}쪽 (글 없음 — 스캔본이면 그림만)"
        out.append(Piece(i, "page", title[:200], "\n".join(lines[1:] if len(lines) > 1 else lines).strip(), imgs))
    return out


_NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
       "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
_DATE_FMT_IDS = set(range(14, 23)) | {45, 46, 47}
_COL_RE = re.compile(r"[A-Z]+")


def _col_no(ref: str) -> int:
    n = 0
    for ch in _COL_RE.match(ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def _xlsx_dates(z: zipfile.ZipFile) -> set[int]:
    """날짜 서식인 셀 스타일 번호(cellXfs 순번) — 숫자 46318 을 2026-10-23 으로 보이게."""
    try:
        st = ET.fromstring(z.read("xl/styles.xml"))
    except KeyError:
        return set()
    custom = {int(f.get("numFmtId")): f.get("formatCode", "") for f in st.iterfind("a:numFmts/a:numFmt", _NS)}
    out = set()
    for i, xf in enumerate(st.iterfind("a:cellXfs/a:xf", _NS)):
        fid = int(xf.get("numFmtId", "0"))
        code = re.sub(r"\[[^\]]*\]|\"[^\"]*\"", "", custom.get(fid, "")).lower()
        if fid in _DATE_FMT_IDS or (fid in custom and ("y" in code or "d" in code)):
            out.add(i)
    return out


def _xlsx_val(c, shared: list[str], dates: set[int]) -> str:
    t, v = c.get("t", "n"), c.find("a:v", _NS)
    if t == "inlineStr":
        return "".join(x.text or "" for x in c.iterfind(".//a:t", _NS))
    if v is None or v.text is None:
        return ""
    if t == "s":
        return shared[int(v.text)] if int(v.text) < len(shared) else ""
    if t == "b":
        return "참" if v.text == "1" else "거짓"
    if t in ("str", "e"):
        return v.text
    try:
        x = float(v.text)
    except ValueError:
        return v.text
    if int(c.get("s", "0")) in dates and 0 < x < 2958466:
        return (date(1899, 12, 30) + timedelta(days=int(x))).isoformat()
    return f"{x:g}" if abs(x) < 1e15 else v.text


def _row_text(vals: dict[int, str]) -> str:
    """칸 번호 → 값 한 행을 탭으로. 처음·끝 빈칸은 걷고 사이 빈칸은 남긴다."""
    return "\t".join(vals.get(k, "") for k in range(min(vals), max(vals) + 1))


def _sheet_pieces(sheets: list[tuple[str, list[str]]]) -> list[Piece]:
    out = []
    for name, rows in sheets:
        name = name or "시트"
        for k in range(0, len(rows), XLSX_CHUNK):
            part = rows[k:k + XLSX_CHUNK]
            label = name if len(rows) <= XLSX_CHUNK else f"{name} · {k + 1}–{k + len(part)}행"
            out.append(Piece(len(out) + 1, "sheet", label[:200], "\n".join(part)))
    return out


def _com_val(v) -> str:
    """Excel(COM) 칸 값 → 글. 날짜는 날짜로(시각이 있으면 분까지), 숫자는 평문 엑셀과 같은 모양."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "참" if v else "거짓"
    if hasattr(v, "year") and hasattr(v, "month"):
        d = date(v.year, v.month, v.day).isoformat()
        hm = (getattr(v, "hour", 0), getattr(v, "minute", 0))
        return d if hm == (0, 0) else f"{d} {hm[0]:02d}:{hm[1]:02d}"
    if isinstance(v, float):
        return f"{v:g}" if abs(v) < 1e15 else str(v)
    return str(v)


def _parse_drm_xlsx(data: bytes) -> list[Piece]:
    """zip 이 아닌 .xlsx = 문서 보안(DRM)이 걸린 파일 → 서버 PC Excel 로 연다(drm_reader). 안 되면 사유 안내.
    결정 ③: 1차 판에서는 열지 않고 안내만(MEETING_COM_IMPORTS=on 이면 연다)."""
    from app import settings
    if not settings.COM_IMPORTS:
        raise ImportError_("문서 보안(DRM)이 걸린 엑셀은 1차 판에서 열지 않습니다(결정 ③) — "
                           "문서 보안을 해제해 저장한 뒤 올려주세요. 일반 엑셀·PPT·PDF·HTML 은 그대로 올릴 수 있습니다.")
    sheets = drm_reader.read_sheets(data)
    if sheets is None:
        raise ImportError_(f"엑셀 파일을 읽지 못했습니다(DRM 복호 불가 — {drm_reader.last_error() or '사유 모름'}). "
                           "문서 보안을 해제해 저장한 뒤 올리거나, Excel 이 깔린 서버 PC 에서 다시 해보세요.")
    texts = []
    for name, rows in sheets:
        lines = []
        for r in rows:
            vals = {i: v for i, c in enumerate(r) if (v := " ".join(_com_val(c).split()))}
            if vals:
                lines.append(_row_text(vals))
        texts.append((name, lines))
    return _sheet_pieces(texts)


def parse_xlsx(data: bytes) -> list[Piece]:
    """시트마다(60행씩 나눔) 행을 칸 탭으로. 숨긴 시트·빈 행은 건너뛴다. 그림·차트는 가져오지 않는다.
    zip 이 아니면 DRM 파일로 보고 Excel(COM)로 연다(2026-10-29)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        return _parse_drm_xlsx(data)
    try:
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iterfind("p:Relationship", _NS)}
    except (KeyError, ET.ParseError) as e:
        raise ImportError_("엑셀 파일을 읽지 못했습니다. 엑셀에서 열어 .xlsx 로 다시 저장해 올려주세요.") from e
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        shared = ["".join(t.text or "" for t in si.iterfind(".//a:t", _NS)) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iterfind("a:si", _NS)]
    dates = _xlsx_dates(z)
    sheets = []
    for sh in wb.iterfind("a:sheets/a:sheet", _NS):
        if sh.get("state") in ("hidden", "veryHidden"):
            continue
        target = rels.get(sh.get(f"{{{_NS['r']}}}id"), "")
        path = target.lstrip("/") if target.startswith("/") else "xl/" + target
        try:
            root = ET.fromstring(z.read(path))
        except (KeyError, ET.ParseError):
            continue
        rows = []
        for r in root.iterfind("a:sheetData/a:row", _NS):
            vals: dict[int, str] = {}
            for c in r.iterfind("a:c", _NS):
                v = " ".join(_xlsx_val(c, shared, dates).split())
                if v and c.get("r"):
                    vals[_col_no(c.get("r"))] = v
            if vals:
                rows.append(_row_text(vals))
        sheets.append((sh.get("name") or "시트", rows))
    return _sheet_pieces(sheets)


def parse_file(name: str, data: bytes) -> list[Piece]:
    kind = FILE_EXT.get(Path(name or "").suffix.lower())
    return {"pptx": parse_pptx, "html": parse_html, "pdf": parse_pdf, "xlsx": parse_xlsx}[kind](data) if kind else []


def mail_pieces(subject: str, html: str, attachments: list[tuple[str, bytes]]) -> list[Piece]:
    """메일 본문 한 조각(메신저 머리줄 걷음, 그림 첨부를 함께) + 첨부 PPT·HTML·PDF·엑셀은 장·절·쪽·시트마다."""
    body = "\n".join(ln for _, lines in html_text(html) for ln in lines)
    body = clean_messenger(body).text.strip()
    imgs = [(n, b) for n, b in attachments if Path(n).suffix.lower() in _IMG_EXT]
    out = [Piece(1, "mail", (subject or "메일")[:200], body, imgs)]
    for name, data in attachments:
        try:
            sub = parse_file(name, data)
        except w.WriteError:
            sub = []
        for p in sub:
            out.append(Piece(len(out) + 1, p.kind, f"{name} · {p.title}"[:200], p.text, p.images))
    return out


# ── 연결 후보 ───────────────────────────────────────────
def hulls_in(s: Session, text: str) -> set[str]:
    out = set()
    for mt in _HULL_RE.finditer(text or ""):
        sn = ensure_sn(mt.group(1))
        if sn and s.get(m.Hull, sn) is not None:
            out.add(sn)
    return out


def candidates(s: Session, text: str, limit: int = 3) -> list[dict]:
    """조각 글에 맞는 열린 이슈 — 근거(이유)가 있는 것만, 점수 순. [{id, title, dept, score, why}]."""
    body = text or ""
    norm = alias_svc.normalize(body)
    ids = set(_ID_RE.findall(body))
    hulls = hulls_in(s, body)
    eq_hit: dict[str, str] = {}
    for a in s.scalars(select(m.Alias).where(m.Alias.target_kind == "installed_equipment")):
        key = alias_svc.normalize(a.text)
        if len(key) >= 2 and key in norm and (a.scope_hull_id is None or not hulls or a.scope_hull_id in hulls):
            eq_hit.setdefault(a.target_id, a.text)
    words = {x for x in _WORD_RE.findall(body)}
    names = {d.id: d.name for d in s.scalars(select(m.Department))}
    out = []
    for b in s.scalars(select(m.Block).where(m.Block.block_type.in_(w.TRACKED), m.Block.status != "종결")):
        score, why = 0, []
        if b.id in ids:
            score += 10
            why.append(f"이슈 ID {b.id}")
        hull = w.block_hull(s, b.id)
        if hull and hull in hulls:
            score += 3
            why.append(f"호선 {hull}")
        eqs = {t.target_id for t in w.block_tags(s, b.id) if t.kind == "installed_equipment" and t.target_id}
        hit = [eq_hit[e] for e in eqs if e in eq_hit]
        if hit:
            score += 4
            why.append(f"장비 「{hit[0]}」")
        common = [x for x in _WORD_RE.findall(b.title or "") if x in words and not x.isdigit()][:4]
        if common:
            score += len(common)
            why.append("제목 낱말 " + "·".join(common))
        if score >= 3:
            out.append({"id": b.id, "title": b.title, "dept": names.get(b.owner_department_id, ""), "score": score, "why": why})
    return sorted(out, key=lambda x: (-x["score"], x["id"]))[:limit]


# ── 가져오기 · 판정 · 반영 ────────────────────────────────
def _store(job: m.ImportJob, name: str, data: bytes) -> str:
    d = pc.get_import_dir() / str(job.id)
    d.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", name)[:80] or "file"
    p = d / safe
    n = 1
    while p.exists():                                  # 원본은 덮어쓰지 않는다
        p = d / f"{p.stem}_{n}{p.suffix}"
        n += 1
    p.write_bytes(data)
    return str(p.relative_to(pc.get_import_dir())).replace("\\", "/")


def _add_pieces(s: Session, job: m.ImportJob, pieces: list[Piece]) -> int:
    for p in pieces:
        keys = [_store(job, f"p{p.no}_{k}{Path(n).suffix.lower()}", b) for k, (n, b) in enumerate(p.images)]
        s.add(m.ImportPiece(job_id=job.id, no=p.no, kind=p.kind, title=p.title, text=p.text,
                            images_json=json.dumps(keys), candidates_json=json.dumps(candidates(s, f"{p.title}\n{p.text}"), ensure_ascii=False),
                            dept_id=job.dept_id))
    s.flush()
    return len(pieces)


def import_file(s: Session, name: str, data: bytes, dept_id: str | None) -> m.ImportJob:
    suf = Path(name or "").suffix.lower()
    if suf not in FILE_EXT:
        raise ImportError_("PPT(.pptx)·HTML·PDF·엑셀(.xlsx) 파일만 가져옵니다. .ppt·.xls 는 PowerPoint·엑셀에서 .pptx·.xlsx 로 저장해 올려주세요.")
    if not data:
        raise ImportError_("빈 파일입니다. 다시 골라주세요.")
    if len(data) > settings.IMPORT_MAX_MB * 1024 * 1024:
        raise ImportError_(f"파일이 {settings.IMPORT_MAX_MB}MB 를 넘습니다. 필요한 장만 남겨 올려주세요.")
    pieces = parse_file(name, data)
    if not pieces:
        raise ImportError_("뽑을 글·그림이 없습니다. 내용이 그림 한 장뿐이면 이슈 원장에서 사진으로 붙여주세요.")
    job = m.ImportJob(kind=FILE_EXT[suf], title=name[:256], sha256=hashlib.sha256(data).hexdigest(),
                      week_id=weeks.current().id, dept_id=dept_id or None)
    s.add(job)
    s.flush()
    job.file_key = _store(job, name, data)
    _add_pieces(s, job, pieces)
    return job


def import_mail(s: Session, mail: dict, dept_id: str | None) -> m.ImportJob | None:
    """메일 한 통 → 가져오기 한 건. 같은 메일(Message-ID)은 한 번만. 발신자·수신자는 저장하지 않는다."""
    sid = mail.get("message_id") or mail.get("entry_id") or ""
    if sid and s.scalar(select(m.ImportJob.id).where(m.ImportJob.source_id == sid)) is not None:
        return None
    job = m.ImportJob(kind="mail", title=(mail.get("subject") or "메일")[:256], source_id=sid, received_at=mail.get("received_at", ""),
                      week_id=weeks.current().id, dept_id=dept_id or None)
    s.add(job)
    s.flush()
    job.file_key = _store(job, "본문.html", (mail.get("html") or "").encode("utf-8"))
    for n, b in mail.get("attachments") or []:
        _store(job, n, b)
    _add_pieces(s, job, mail_pieces(job.title, mail.get("html") or "", mail.get("attachments") or []))
    return job


def decide(s: Session, piece: m.ImportPiece, decision: str, block_id: str = "", line: str = "", dept_id: str = "") -> None:
    if piece.applied:
        raise ImportError_("이미 반영한 조각입니다.")
    if decision not in DECISIONS and decision != "":
        raise ImportError_("판정은 붙이기·새 이슈·건너뛰기 중에서 골라주세요.")
    if decision == "link":
        if s.get(m.Block, block_id or "") is None:
            raise ImportError_("붙일 이슈를 골라주세요(후보에서 고르거나 이슈 ID 를 적어주세요).")
        piece.block_id = block_id
        piece.line = (line or piece.title).strip()[:300]
    if decision == "new":
        if s.get(m.Department, dept_id or piece.dept_id or "") is None:
            raise ImportError_("새 이슈의 담당 부서를 골라주세요.")
        piece.dept_id = dept_id or piece.dept_id
    piece.decision = decision
    s.flush()


@dataclass
class ApplyReport:
    linked: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


def _attach_images(s: Session, piece: m.ImportPiece, b: m.Block) -> int:
    n = 0
    for key in json.loads(piece.images_json or "[]"):
        try:
            data = (pc.get_import_dir() / key).read_bytes()
            photo, _ = ph.store(s, data)
            ph.link(s, photo, b, "main")
            n += 1
        except (OSError, w.WriteError):  # noqa: PERF203 — 그림이 사진 형식이 아니면(EMF 등) 건너뛴다
            continue
    return n


def apply(s: Session, job: m.ImportJob) -> ApplyReport:
    """판정한 조각을 원장에 넣는다. 붙이기 = 이번 주 한 줄 + 그림 → 사진, 새 이슈 = 메모로 저장 + AI 정리. 다시 눌러도 같은 조각은 한 번만."""
    rep = ApplyReport()
    wk = weeks.current().id
    for p in s.scalars(select(m.ImportPiece).where(m.ImportPiece.job_id == job.id, m.ImportPiece.applied.is_(False)).order_by(m.ImportPiece.no)):
        if not p.decision:
            continue
        if p.decision == "skip":
            p.applied = True
            rep.skipped += 1
            continue
        if p.decision == "link":
            b = s.get(m.Block, p.block_id)
            co.update_line(s, b, wk, p.line or p.title)
            _attach_images(s, p, b)
            p.result_block_id, p.applied = b.id, True
            rep.linked.append(b.id)
            continue
        sec = w.get_section(s, wk, p.dept_id, create=True)
        raw = f"{p.title}\n{p.text}".strip() + f"\n(외부 자료: {job.title} {p.no})"
        memo = s.scalar(select(m.Memo).where(m.Memo.section_id == sec.id, m.Memo.raw_text == raw).limit(1)) or w.add_memo(s, sec, raw)   # 다시 눌러도 같은 메모
        out = ex.run_extract(s, memo)
        if not out.ok or not (out.created or out.updated):
            why = " / ".join(out.result.errors) or (f"근거가 글과 맞지 않아 버림 {len(out.dropped)}" if out.dropped else "이슈로 나눌 내용이 없습니다")
            rep.errors.append(f"{p.no}: AI 정리에 실패했습니다 — {why}. 판정을 「붙이기」로 바꾸거나 메모({memo.id})를 고쳐 다시 정리해주세요")
            continue
        bid = (out.created or out.updated)[0]
        _attach_images(s, p, s.get(m.Block, bid))
        p.result_block_id, p.applied = bid, True
        rep.created += out.created or [bid]
    s.flush()                                          # 아래 「남은 조각」 조회가 방금 반영한 것을 보게
    if not s.scalar(select(m.ImportPiece.id).where(m.ImportPiece.job_id == job.id, m.ImportPiece.applied.is_(False)).limit(1)):
        job.status = "반영함"
    s.flush()
    return rep


def piece_json(p: m.ImportPiece) -> dict:
    return {"id": p.id, "no": p.no, "kind": p.kind, "title": p.title, "text": p.text, "images": json.loads(p.images_json or "[]"),
            "candidates": json.loads(p.candidates_json or "[]"), "decision": p.decision, "block_id": p.block_id or "",
            "line": p.line, "dept_id": p.dept_id or "", "applied": p.applied, "result": p.result_block_id or ""}


def job_state(s: Session, job: m.ImportJob) -> dict:
    ps = list(s.scalars(select(m.ImportPiece).where(m.ImportPiece.job_id == job.id).order_by(m.ImportPiece.no)))
    return {"job": {"id": job.id, "kind": job.kind, "kind_label": KINDS.get(job.kind, job.kind), "title": job.title, "status": job.status,
                    "received_at": job.received_at, "week": job.week_id, "dept_id": job.dept_id or ""},
            "pieces": [piece_json(p) for p in ps], "decisions": DECISIONS,
            "depts": [{"id": d.id, "name": d.name} for d in s.scalars(select(m.Department).order_by(m.Department.order_no))]}


def memo_entry(s: Session, dept_id: str, text: str) -> tuple[m.Memo, Cleaned]:
    """메모 입구 — 메신저 머리줄을 걷고 이번 주 그 부서 메모로 저장(AI 정리는 호출부가)."""
    if s.get(m.Department, dept_id or "") is None:
        raise ImportError_("메모를 넣을 부서를 골라주세요.")
    c = clean_messenger(text)
    sec = w.get_section(s, weeks.current().id, dept_id, create=True)
    return w.add_memo(s, sec, c.text), c


def records_for(s: Session, block_id: str) -> list[dict]:
    """이슈 원장 「주차별 진행」에 보일 외부 자료 반영 기록."""
    out = []
    for p, job in s.execute(select(m.ImportPiece, m.ImportJob).join(m.ImportJob, m.ImportJob.id == m.ImportPiece.job_id)
                            .where(m.ImportPiece.result_block_id == block_id, m.ImportPiece.applied.is_(True))):
        out.append({"week": job.week_id, "label": f"외부 자료 {KINDS.get(job.kind, job.kind)} 「{job.title[:40]}」 {p.no}",
                    "text": p.line or p.title})
    return out
