"""extract_blocks — 메모 → 회의자료 블록 (docs/04 §3).

1. 전처리: 줄 번호(L1…)를 붙이고, 메모 속 호선의 탑재 장비 별칭만 후보로 넣는다.
2. LLM 호출: `app/llm/client.complete_json` (체인·스키마 검증·호출 로그는 거기서).
3. 후처리(코드로 검증 — LLM 을 믿지 않는다):
   - 근거(evidence)의 줄 번호가 범위 안이고 quote 가 그 줄에 **글자 그대로** 있어야 한다.
     근거가 하나도 맞지 않는 블록·태그·지표는 **버린다**(원칙 3 — 근거 없는 AI 값은 표시하지 않는다).
   - 태그 ID 는 LLM 이 준 값이 아니라 `services/alias.py` 로 다시 확정한다.
4. 저장: 블록·태그·`source_span`·`ai_field_log(ai_value)`. 같은 메모를 다시 정리하면
   근거 첫 줄이 같은 블록을 찾아 갱신하되 **사람이 고친 필드와 사람이 확인한 태그는 건드리지 않는다.**
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import models as m
from app import settings
from app.llm import client as llm
from app.services import alias as alias_svc
from app.services import carry_over as co
from app.services import metrics as metrics_svc
from app.services import writing as w
from sn_util import ensure_sn

PROMPT = (settings.ROOT / "app" / "llm" / "prompts" / "extract_blocks.md")
SCHEMA_PATH = settings.ROOT / "schema" / "extraction.schema.json"
_HULL_NUM = re.compile(r"(?<![0-9A-Za-z])(?:SN|S|H)?(\d{4})(?![0-9])", re.IGNORECASE)
# LLM 태그 kind → 별칭 사전 target_kind (없으면 자유 텍스트로 둔다)
ALIAS_KIND = {"installed_equipment": "installed_equipment", "component": "component", "system": "system",
              "test_item": "test_item", "symptom": "symptom", "cause": "cause"}


@dataclass
class ExtractOutcome:
    result: llm.LLMResult
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    carried: list[str] = field(default_factory=list)              # 메모에서 업데이트를 찾은 이어온 블록
    metrics: int = 0                                              # 이번 주 지표 칸에 넣은 값 수
    kept: dict[str, list[str]] = field(default_factory=dict)     # 블록별 지켜 둔 사람 값 필드
    dropped: list[str] = field(default_factory=list)              # 근거가 맞지 않아 버린 것
    left: list[str] = field(default_factory=list)                 # 원문 수정본에서 대응 줄을 못 찾아 그대로 둔 옛 판 블록
    retyped: int = 0                                              # 지표 없는 대시보드 → 공유정보로 바꾼 수

    @property
    def ok(self) -> bool:
        return self.result.ok


def memo_lines(raw: str) -> list[tuple[str, int]]:
    """(줄 내용, 원문에서의 시작 위치) — 원문은 그대로 두고 위치만 계산한다."""
    out, pos = [], 0
    for piece in raw.splitlines(keepends=True):
        out.append((piece.rstrip("\r\n"), pos))
        pos += len(piece)
    return out


def build_user_prompt(s: Session, memo: m.Memo, dept_name: str, week_id: str) -> str:
    lines = memo_lines(memo.raw_text)
    numbered = "\n".join(f"L{i}: {t}" for i, (t, _) in enumerate(lines, 1))
    hulls = sorted({h for h in (ensure_sn(x) for x in _HULL_NUM.findall(memo.raw_text)) if s.get(m.Hull, h)})
    cand = []
    for h in hulls:
        names = [f"{e.name}" for e in s.scalars(select(m.InstalledEquipment).where(m.InstalledEquipment.hull_id == h))]
        al = [f"{a.text}" for a in s.scalars(select(m.Alias).where(m.Alias.scope_hull_id == h))]
        cand.append(f"{h}: 장비 {', '.join(names) or '-'} / 별칭 {', '.join(al) or '-'}")
    sec = s.get(m.Section, memo.section_id)
    carried = [f"{b.id}: {b.title}" for b in co.carried_blocks(s, sec)] if sec else []
    return (f"부서: {dept_name}\n주차: {week_id}\n\n[메모]\n{numbered}\n\n"
            f"[메모 속 호선의 장비·별칭 후보]\n" + ("\n".join(cand) or "(없음)") +
            "\n\n[지난주에서 이어온 블록 — 메모에 같은 건의 업데이트가 있으면 carried_block_ref 에 그 ID]\n" +
            ("\n".join(carried) or "(없음)"))


def _line_of(pos: int, lines: list[tuple[str, int]]) -> int | None:
    """원문 위치 → 줄 번호(1부터)."""
    no = None
    for i, (_, st) in enumerate(lines, 1):
        if st <= pos:
            no = i
        else:
            break
    return no


def _line_by_quote(quote: str, lines: list[tuple[str, int]]) -> int | None:
    """근거 글귀가 그대로 들어 있는 첫 줄 번호 — 원문 수정본에서 옛 판 블록의 자리를 찾을 때."""
    q = (quote or "").strip()
    if not q:
        return None
    return next((i for i, (t, _) in enumerate(lines, 1) if q in t), None)


def _ev_ok(ev: dict | None, lines: list[tuple[str, int]]) -> bool:
    if not ev:
        return False
    n, q = ev.get("line"), (ev.get("quote") or "")
    return isinstance(n, int) and 1 <= n <= len(lines) and bool(q.strip()) and q in lines[n - 1][0]


def _span(block_id: str, fld: str, memo: m.Memo, ev: dict, lines) -> m.SourceSpan:
    text, start = lines[ev["line"] - 1]
    at = start + text.index(ev["quote"])
    return m.SourceSpan(block_id=block_id, field=fld, memo_id=memo.id, start=at, end=at + len(ev["quote"]),
                        quote=ev["quote"])


def _resolve_tag(s: Session, t: dict, hull: str | None) -> str | None:
    if t["kind"] == "hull":
        h = ensure_sn(t.get("normalized") or t["raw_text"]) or ensure_sn(t["raw_text"])
        return h if s.get(m.Hull, h) else None
    kind = ALIAS_KIND.get(t["kind"])
    if kind is None:
        return None
    r = alias_svc.resolve(s, t["raw_text"], hull_id=hull, kinds={kind})
    return r.target_id if r.linked else None


def run_extract(s: Session, memo: m.Memo) -> ExtractOutcome:
    section = s.get(m.Section, memo.section_id)
    dept = s.get(m.Department, section.department_id)
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    res = llm.complete_json("extract_blocks", PROMPT.read_text(encoding="utf-8"),
                            build_user_prompt(s, memo, dept.name if dept else section.department_id, section.week_id),
                            schema, session=s)
    out = ExtractOutcome(result=res)
    if not res.ok:
        s.flush()
        return out
    model_tag = f"{res.provider}:{res.model or ''}".rstrip(":")
    lines = memo_lines(memo.raw_text)
    year = int(section.week_id[:4])

    # 이 메모에서 나온 기존 블록 — 근거 첫 줄로 찾는다
    existing: dict[int, m.Block] = {}
    for sp in s.scalars(select(m.SourceSpan).where(m.SourceSpan.memo_id == memo.id, m.SourceSpan.field == "block")):
        line_no = _line_of(sp.start, lines)
        b = s.get(m.Block, sp.block_id)
        if line_no and b and line_no not in existing:
            existing[line_no] = b
    # 원문 수정본이면 앞 판들에서 나온 블록도 이어받는다 — 같은 글귀가 있는 줄, 없으면 같은 줄 번호
    chain = w.memo_chain(s, memo)
    chain_ids = [memo.id] + [x.id for x in chain]
    old_spans: list[tuple[m.Block, str, int | None]] = []
    for old in chain:                                   # 가까운 판부터
        old_lines = memo_lines(old.raw_text)
        for sp in s.scalars(select(m.SourceSpan).where(m.SourceSpan.memo_id == old.id, m.SourceSpan.field == "block")):
            b = s.get(m.Block, sp.block_id)
            if b is not None and all(b.id != x[0].id for x in old_spans):
                old_spans.append((b, sp.quote, _line_of(sp.start, old_lines)))
    placed = {b.id for b in existing.values()}
    prev_ids = {b.id for b, _, _ in old_spans} - placed
    for b, quote, _ in old_spans:                       # 1차: 글귀로
        no = _line_by_quote(quote, lines)
        if b.id not in placed and no and no not in existing:
            existing[no] = b
            placed.add(b.id)
    for b, _, old_no in old_spans:                      # 2차: 같은 줄 번호로
        if b.id not in placed and old_no and old_no <= len(lines) and old_no not in existing:
            existing[old_no] = b
            placed.add(b.id)
    order = len(w.section_blocks(s, section))
    carried_ids = {b.id for b in co.carried_blocks(s, section)}

    for bi, raw in enumerate(res.data["blocks"]):
        evs = [e for e in raw.get("evidence", []) if _ev_ok(e, lines)]
        if not evs:
            out.dropped.append(f"블록 {bi + 1} '{raw.get('title', '')[:30]}' — 근거가 메모와 맞지 않아 버림")
            continue
        tags = []
        for t in raw.get("tags", []):
            if _ev_ok(t.get("evidence"), lines):
                tags.append(t)
            else:
                out.dropped.append(f"태그 '{t.get('raw_text', '')}' — 근거가 메모와 맞지 않아 버림")
        hull = next((h for h in (_resolve_tag(s, t, None) for t in tags if t["kind"] == "hull") if h), None)

        btype = raw["block_type"]
        ai = {"block_type": btype, "title": (raw.get("title") or "").strip(), "body": raw.get("body") or "",
              "status": (raw.get("status") if raw.get("status") in w.EDITABLE_STATUS else "")
              if btype in w.TRACKED else w.POSTED}
        mets: list[dict] = []
        if btype == "dashboard":                       # 지표는 본문이 아니라 metric_value 로 (M5)
            mets = [x for x in raw.get("metrics", []) if _ev_ok(x.get("evidence"), lines)]
            out.dropped += [f"지표 '{x.get('name')}' — 근거 없음" for x in raw.get("metrics", []) if x not in mets]
            if not mets:
                # 숫자 지표가 없는 대시보드는 보고서 어디에도 안 나간다 → 일정·공지로 보고 공유정보로 둔다(2026-10-21)
                btype = "share"
                ai.update(block_type="share", status=w.POSTED)
                out.retyped += 1
        valid_until = None
        if btype == "share" and raw.get("valid_until"):
            try:
                valid_until = date.fromisoformat(raw["valid_until"])
            except ValueError:  # noqa: PERF203 — 날짜가 아니면 비운다
                valid_until = None

        # 지난주에서 이어온 블록의 업데이트 → 새 블록을 만들지 않고 그 블록의 이번 주 한 줄로
        ref = raw.get("carried_block_ref")
        if ref and ref in carried_ids:
            row = co.week_row(s, ref, section.week_id)
            if row is None:
                row = co.add_history(s, s.get(m.Block, ref), section.week_id)
            if not (row.note or "").strip():              # 사람이 이미 적은 한 줄은 덮지 않는다
                row.note = (ai["body"] or evs[0]["quote"]).strip()[:500]
            s.execute(delete(m.SourceSpan).where(m.SourceSpan.block_id == ref, m.SourceSpan.memo_id.in_(chain_ids),
                                                 m.SourceSpan.field == "carry"))
            s.add(_span(ref, "carry", memo, evs[0], lines))
            out.carried.append(ref)
            s.flush()
            continue

        block = existing.get(evs[0]["line"])
        if block is None:
            block = m.Block(id=w.new_block_id(s, btype, year), owner_department_id=section.department_id,
                            created_week_id=section.week_id, origin="memo", valid_until=valid_until, **ai)
            s.add(block)
            s.add(m.SectionBlock(section_id=section.id, block_id=block.id, order_no=order))
            order += 1
            out.created.append(block.id)
            keep: set[str] = set()
            s.flush()
            co.add_history(s, block, section.week_id, note="신규 등록")
        else:
            keep = w.human_fields(s, block.id)
            for k, v in ai.items():
                if k not in keep:
                    setattr(block, k, v)
            if "valid_until" not in keep:
                block.valid_until = valid_until
            out.updated.append(block.id)
            if keep:
                out.kept[block.id] = sorted(keep)
            # 사람이 확인하지 않은 AI 태그·이 메모의 근거는 새로 쓴다
            s.execute(delete(m.BlockTag).where(m.BlockTag.block_id == block.id, m.BlockTag.confirmed.is_(False)))
            # 근거는 이 판 기준으로 다시 — 앞 판을 가리키던 근거도 지운다(「메모 N행」이 최신 원문을 가리키게)
            s.execute(delete(m.SourceSpan).where(m.SourceSpan.block_id == block.id,
                                                 m.SourceSpan.memo_id.in_(chain_ids)))
        s.flush()

        for k in ("block_type", "title", "body", "status"):
            if k not in keep:
                s.add(m.AiFieldLog(block_id=block.id, field=k, ai_value=ai[k], human_value=None, model=model_tag))
        s.add(_span(block.id, "block", memo, evs[0], lines))
        for e in evs[1:]:
            s.add(_span(block.id, "body", memo, e, lines))

        confirmed = {(t.kind, t.raw_text) for t in w.block_tags(s, block.id)}
        for t in tags:
            if (t["kind"], t["raw_text"]) in confirmed:
                continue
            s.add(m.BlockTag(block_id=block.id, kind=t["kind"], target_id=_resolve_tag(s, t, hull),
                             raw_text=t["raw_text"], confidence=t.get("confidence"), confirmed=False))
            s.add(_span(block.id, f"tag:{t['kind']}", memo, t["evidence"], lines))
        if mets:
            out.metrics += metrics_svc.apply_ai_metrics(s, section.department_id, section.week_id, block.id, mets, model_tag)
            for x in mets:
                s.add(_span(block.id, f"metric:{x['name']}"[:32], memo, x["evidence"], lines))
        s.flush()
    out.left = sorted(prev_ids - set(out.updated) - set(out.carried))
    return out
