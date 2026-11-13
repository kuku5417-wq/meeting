"""부서 표기 → 부서 ID — 회의록 후보의 담당 부서 추천(기능 9)에 쓴다.

현장에서는 정식 이름(시운전3부·친환경실증Lab)보다 줄임말(3부·해운·기술팀·실증랩)을 더 많이 쓴다.
순서대로 시도하고 **한 부서로 좁혀질 때만** 연결한다 — 여럿이 걸리면(예: 「시운전」) 고르지 않고 None.
  1. 정규화: 공백 제거·대문자·전각→반각, `랩`→`LAB`, 끝의 조사(에서·가·는…) 제거
  2. 정식 이름·코드·ID 와 같으면 그 부서
  3. 표기 안에 정식 이름이 통째로 있으면 그 부서(「시운전기술부」→ 시운전기술)
  4. 표기가 한 부서 이름의 일부면 그 부서(「3부」→ 시운전3부, 「해운」→ 해운부)
  5. 끝의 부서·팀·그룹·실·부 를 떼고 3~4 다시(「기술팀」→ 기술 → 시운전기술)
두 글자 미만 표기는 부분 일치를 하지 않는다(「전」 같은 한 글자가 아무 데나 걸리지 않게).
부서는 실제 이름이 정해져 있어(department.csv) 별칭 표 대신 이 규칙으로 처리한다.
"""
from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m

_PARTICLE = re.compile(r"(에서|으로|에게|한테|이|가|은|는|을|를|와|과|로|에|의|쪽|측|담당)$")
_SUFFIX = re.compile(r"(부서|팀|그룹|실|부)$")
_DEPT_WORD = re.compile(r"(부서|부|팀|그룹|LAB)$")      # 줄 전체에서 볼 때는 이렇게 끝나는 낱말만
_WORD = re.compile(r"[0-9A-Za-z가-힣]+")


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "").upper()
    return re.sub(r"\s+", "", t).replace("랩", "LAB")


def _strip_particles(key: str) -> list[str]:
    """「3부에서」→ ["3부에서", "3부"] — 원형부터 시도하려고 순서를 지킨다."""
    out = [key]
    for _ in range(2):
        nxt = _PARTICLE.sub("", out[-1])
        if nxt == out[-1] or not nxt:
            break
        out.append(nxt)
    return out


def _contain(key: str, names: dict[str, str]) -> str | None:
    if len(key) < 2:
        return None
    inside = [d for d, n in names.items() if n in key]
    if inside:
        return max(inside, key=lambda d: len(names[d]))      # 「시운전기술부」는 더 긴 이름 쪽
    part = [d for d, n in names.items() if key in n]
    return part[0] if len(part) == 1 else None


def resolve(s: Session, hint: str | None) -> str | None:
    """부서 표기 하나(AI 가 준 department_hint 등) → 부서 ID. 못 좁히면 None."""
    if not (hint or "").strip():
        return None
    depts = list(s.scalars(select(m.Department).order_by(m.Department.order_no)))
    names = {d.id: _norm(d.name) for d in depts}
    keys = _strip_particles(_norm(hint))
    for k in keys:
        for d in depts:
            if k in (names[d.id], _norm(d.code), _norm(d.id)):
                return d.id
    for k in keys:
        hit = _contain(k, names)
        if hit:
            return hit
        base = _SUFFIX.sub("", k)
        if base != k and len(base) >= 2:
            hit = _contain(base, names)
            if hit:
                return hit
    return None


def find_in_text(s: Session, text: str | None) -> str | None:
    """메모 한 줄에서 담당 부서 찾기 — AI 가 부서를 못 짚었을 때의 보조.

    줄에는 부서와 무관한 낱말이 많아 「…부·팀·그룹·Lab·랩」으로 끝나는 낱말만 본다
    (「기술 검토」의 「기술」은 부서로 보지 않는다). 서로 다른 부서가 둘 이상이면 None.
    """
    hits: set[str] = set()
    for word in _WORD.findall(unicodedata.normalize("NFKC", text or "")):
        w = _strip_particles(_norm(word))[-1]
        if _DEPT_WORD.search(w):
            d = resolve(s, w)
            if d:
                hits.add(d)
    return hits.pop() if len(hits) == 1 else None


def names_line(s: Session) -> str:
    """AI 프롬프트에 넣는 부서 목록 한 줄 — 「기획운영, 시운전기술, …」."""
    return ", ".join(d.name for d in s.scalars(select(m.Department).order_by(m.Department.order_no)))
