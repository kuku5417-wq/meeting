"""블록에 붙이는 표 — 이슈·문제점 블록의 측정값·점검 목록 (2026-10-21).

입력은 엑셀·한글 표에서 복사한 글을 그대로 받는다(탭 구분). 탭이 없으면 `|` → 쉼표 순으로 나눈다.
첫 행은 머리글. 크기는 MAX_ROWS × MAX_COLS 로 자르고 넘친 사실을 돌려준다(조용히 버리지 않는다).
PPT·미리보기는 `services/slides.py` 의 「표」 쪽이 같은 데이터를 쓴다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m
from app.services import writing as w

MAX_ROWS, MAX_COLS = 20, 8
TABLE_TYPES = ("issue", "problem")


@dataclass
class Parsed:
    rows: list[list[str]]
    cut_rows: int = 0
    cut_cols: int = 0


def parse_paste(text: str) -> Parsed:
    lines = [ln for ln in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln.strip()]
    if not lines:
        return Parsed([])
    sep = "\t" if any("\t" in ln for ln in lines) else ("|" if any("|" in ln for ln in lines) else ",")
    rows = []
    for ln in lines:
        cells = [c.strip() for c in ln.split(sep)]
        if sep == "|":                                   # | a | b | 형식의 앞뒤 빈 칸
            cells = cells[1:] if cells and cells[0] == "" else cells
            cells = cells[:-1] if cells and cells[-1] == "" else cells
            if all(set(c) <= set("-: ") for c in cells):  # 마크다운 구분줄
                continue
        rows.append(cells)
    width = max(len(r) for r in rows)
    cut_cols = max(0, width - MAX_COLS)
    cut_rows = max(0, len(rows) - MAX_ROWS)
    width = min(width, MAX_COLS)
    rows = [(r + [""] * width)[:width] for r in rows[:MAX_ROWS]]
    return Parsed(rows, cut_rows, cut_cols)


def to_tsv(rows: list[list[str]]) -> str:
    return "\n".join("\t".join(r) for r in rows)


def rows_of(t: m.BlockTable) -> list[list[str]]:
    try:
        rows = json.loads(t.rows_json or "[]")
    except ValueError:  # noqa: PERF203 — 깨진 값은 빈 표로
        return []
    return rows if isinstance(rows, list) else []


def block_tables(s: Session, block_id: str) -> list[m.BlockTable]:
    return list(s.scalars(select(m.BlockTable).where(m.BlockTable.block_id == block_id)
                          .order_by(m.BlockTable.order_no, m.BlockTable.id)))


def _guard(s: Session, block: m.Block) -> None:
    if block.block_type not in TABLE_TYPES:
        raise w.WriteError("표는 이슈·문제점 블록에만 붙일 수 있습니다. 숫자 지표는 대시보드 블록의 지표 표를 쓰세요.")


def _checked(text: str) -> Parsed:
    p = parse_paste(text)
    if len(p.rows) < 2:
        raise w.WriteError("표로 읽을 내용이 없습니다. 엑셀에서 머리글 포함 두 줄 이상을 복사해 붙여넣어주세요.")
    return p


def add(s: Session, block: m.Block, title: str, text: str) -> tuple[m.BlockTable, Parsed]:
    _guard(s, block)
    p = _checked(text)
    order = (s.scalar(select(func.max(m.BlockTable.order_no)).where(m.BlockTable.block_id == block.id)) or 0) + 1
    t = m.BlockTable(block_id=block.id, title=(title or "").strip()[:128], order_no=order,
                     rows_json=json.dumps(p.rows, ensure_ascii=False))
    s.add(t)
    s.flush()
    return t, p


def update(s: Session, t: m.BlockTable, title: str, text: str) -> Parsed:
    _guard(s, s.get(m.Block, t.block_id))
    p = _checked(text)
    t.title, t.rows_json = (title or "").strip()[:128], json.dumps(p.rows, ensure_ascii=False)
    s.flush()
    return p


def delete(s: Session, t: m.BlockTable) -> None:
    _guard(s, s.get(m.Block, t.block_id))
    s.delete(t)
    s.flush()


def cut_note(p: Parsed) -> str:
    parts = []
    if p.cut_rows:
        parts.append(f"{p.cut_rows}행")
    if p.cut_cols:
        parts.append(f"{p.cut_cols}열")
    return f" · 최대 {MAX_ROWS}행×{MAX_COLS}열이라 {'·'.join(parts)}은 넣지 않았습니다" if parts else ""
