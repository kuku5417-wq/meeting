"""지식창고 자연어 질문 → 근거 사례 인용 답변 (`answer_knowledge`, 화면 C 「AI 요약」).

인용 필수: 답에 나온 사례 번호는 전부 이번 검색에서 넘긴 사례여야 하고, 하나 이상 인용해야 한다.
아니면 답을 보여주지 않는다(근거 없는 AI 값은 표시하지 않는다 — 원칙 3).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app import settings
from app.llm import client as llm
from app.services import knowledge as kn

PROMPT = settings.ROOT / "app" / "llm" / "prompts" / "answer_knowledge.md"
SCHEMA = settings.ROOT / "schema" / "answer_knowledge.schema.json"
TOP_K = 5
_CASE_RE = re.compile(r"CASE-\d{4}")


@dataclass
class Answer:
    text: str = ""
    citations: list[str] = field(default_factory=list)
    provider: str | None = None
    problem: str = ""                      # 답을 못 보여주는 이유
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.text) and bool(self.citations) and not self.problem


def _cause_group(s: Session, c) -> str:
    """원인 코드 이름(연료분사밸브 불량) — 같은 원인을 다른 말로 적은 사례를 한데 묶을 수 있게."""
    from app.models import CauseCode
    code = s.get(CauseCode, c.cause_code_id) if c.cause_code_id else None
    return code.name if code else c.cause_text


def ask(s: Session, question: str, cases: list[kn.Doc]) -> Answer:
    top = cases[:TOP_K]
    if not top:
        return Answer(problem="질문과 맞는 사례가 없어 답하지 않습니다. 낱말을 바꾸거나 필터를 풀어보세요.")
    payload = [{"id": d.key, "title": d.title, "hull": d.facets.get("hull"), "ship_type": d.facets.get("ship_type"),
                "equipment": d.extra["eq"].name if d.extra.get("eq") else None, "symptom": d.obj.symptom_text,
                "cause": d.obj.cause_text, "cause_group": _cause_group(s, d.obj), "action": d.obj.action_text,
                "week": d.obj.approved_week_id} for d in top]
    user = f"질문: {question}\n\n<cases>{json.dumps(payload, ensure_ascii=False)}</cases>"
    res = llm.complete_json("answer_knowledge", PROMPT.read_text(encoding="utf-8"), user,
                            json.loads(SCHEMA.read_text(encoding="utf-8")), session=s)
    if not res.ok:
        return Answer(problem="AI 답변을 받지 못했습니다 — " + " / ".join(res.errors), errors=res.errors)
    given = {d.key for d in top}
    text = (res.data.get("answer") or "").strip()
    cited_in_text = set(_CASE_RE.findall(text))
    cites = [c for c in res.data.get("citations", []) if c in given]
    out = Answer(text=text, citations=sorted(set(cites) | (cited_in_text & given)), provider=res.provider, errors=res.errors)
    if res.data.get("insufficient") or not text:
        out.problem = "주어진 사례로는 답할 수 없다고 판단했습니다."
    elif cited_in_text - given:
        out.problem = f"근거 목록에 없는 사례({', '.join(sorted(cited_in_text - given))})를 인용해 답을 보여주지 않습니다."
    elif not out.citations:
        out.problem = "인용한 사례가 없어 답을 보여주지 않습니다."
    return out
