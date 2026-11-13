"""별칭 매핑 — 현장 표기("DG2", "2511 D/G #2") → 기준정보 ID (docs/04 §4).

순서대로 시도하고 처음 맞는 것을 쓴다.
  1. 정규화: 공백·`#`·`.`·`/`·`-` 제거, 대문자, 전각→반각, `No.2`→`2`, `2번 발전기`→`발전기2`
  2. 문맥 호선이 있으면 그 호선 범위(scope_hull_id) 별칭
  3. 전역 별칭(scope_hull_id 없음)
  4. 패턴 `{시스템약어}{번호}` → 그 호선 탑재 장비에서 system.code · unit_no 로 찾기
  5. 실패 → 미연결 (raw_text 만 남긴다)
같은 단계에서 서로 다른 대상이 둘 이상 나오면 **충돌** — 고르지 않고 후보만 돌려준다(기획부서 검토 대상).

LLM 이 준 ID 는 믿지 않는다 — 태그 확정은 항상 이 모듈을 거친다.
별칭 표는 작아(수백 행) 매 호출 전체를 읽어 파이썬에서 정규화·비교한다. 커지면 정규화 컬럼을 둔다.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from sn_util import ensure_sn

# 메모 속 호선 번호: 2511 · SN2511 · S2511 · 옛 표기 H2511 (앞뒤가 숫자·영문이 아닐 때만)
_HULL_RE = re.compile(r"(?<![0-9A-Za-z])(?:SN|S|H)?\s?(\d{4})(?![0-9])", re.IGNORECASE)
_NO_RE = re.compile(r"NO(?=\d)")                 # GENO2 → GE2 (No.2 표기)
_BEON_RE = re.compile(r"^(\d+)번(.+)$")          # 2번발전기 → 발전기2
_PATTERN_RE = re.compile(r"^([A-Z]+)(\d+)$")      # GE2 · CP3


@dataclass
class Resolution:
    raw: str
    normalized: str
    hull_id: str | None = None          # 문맥 호선 (입력에서 찾았거나 인자로 받은 것)
    target_kind: str | None = None
    target_id: str | None = None
    via: str | None = None              # alias-hull / alias-global / pattern
    alias_text: str | None = None       # 연결에 쓴 별칭 원문 (화면의 "← DG2" 표시용)
    conflict: bool = False
    candidates: list[tuple[str, str]] = field(default_factory=list)   # (kind, id)

    @property
    def linked(self) -> bool:
        return self.target_id is not None


def normalize(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "").upper()
    s = re.sub(r"[\s#./\-]+", "", s)
    s = _NO_RE.sub("", s)
    mb = _BEON_RE.match(s)
    if mb:
        s = mb.group(2) + mb.group(1)
    return s


def split_hull(text: str) -> tuple[str | None, str]:
    """입력에서 호선 번호를 떼어 낸다 → (SN2511, 나머지 표기). 없으면 (None, 원문)."""
    mh = _HULL_RE.search(text or "")
    if not mh:
        return None, (text or "").strip()
    rest = (text[:mh.start()] + " " + text[mh.end():]).strip()
    return ensure_sn(mh.group(1)) or None, rest


def _pick(res: Resolution, hits: list[m.Alias], via: str, typed: str) -> bool:
    targets = sorted({(a.target_kind, a.target_id) for a in hits})
    if not targets:
        return False
    if len(targets) > 1:
        res.conflict, res.candidates, res.via = True, targets, via
        return True
    res.target_kind, res.target_id = targets[0]
    exact = [a for a in hits if a.text.strip().upper() == typed.strip().upper()]   # 입력과 같은 별칭을 우선 표시
    res.via, res.alias_text = via, (exact or hits)[0].text
    return True


def resolve(s: Session, text: str, hull_id: str | None = None, kinds: set[str] | None = None) -> Resolution:
    """표기 하나를 기준정보 ID 로. `hull_id` 는 메모 문맥 호선(입력에 호선이 있으면 그쪽이 우선)."""
    direct = s.get(m.InstalledEquipment, (text or "").strip().upper())
    if direct is not None and (kinds is None or "installed_equipment" in kinds):   # ID 를 그대로 친 경우
        return Resolution(raw=text, normalized=direct.id, hull_id=direct.hull_id,
                          target_kind="installed_equipment", target_id=direct.id, via="id")
    found_hull, rest = split_hull(text)
    hull = found_hull or (ensure_sn(hull_id) or None)
    if hull is not None and s.get(m.Hull, hull) is None:
        hull = None                         # 기준정보에 없는 호선은 문맥으로 쓰지 않는다
    key = normalize(rest)
    res = Resolution(raw=text, normalized=key, hull_id=hull)
    if not key:
        return res

    rows = [a for a in s.scalars(select(m.Alias)) if (kinds is None or a.target_kind in kinds)]
    same = [a for a in rows if normalize(a.text) == key]
    if hull and _pick(res, [a for a in same if a.scope_hull_id == hull], "alias-hull", rest):
        return res
    if _pick(res, [a for a in same if a.scope_hull_id is None], "alias-global", rest):
        return res

    mp = _PATTERN_RE.match(key)
    if hull and mp and (kinds is None or "installed_equipment" in kinds):
        eq = s.scalars(
            select(m.InstalledEquipment).join(m.System, m.System.id == m.InstalledEquipment.system_id)
            .where(m.InstalledEquipment.hull_id == hull, m.System.code == mp.group(1),
                   m.InstalledEquipment.unit_no == int(mp.group(2)))).all()
        if len(eq) == 1:
            res.target_kind, res.target_id, res.via = "installed_equipment", eq[0].id, "pattern"
        elif len(eq) > 1:
            res.conflict, res.via = True, "pattern"
            res.candidates = [("installed_equipment", e.id) for e in eq]
    return res


def conflicts(s: Session) -> list[tuple[str, str | None, list[tuple[str, str]]]]:
    """같은 (정규화 표기, 호선 범위)가 서로 다른 대상을 가리키는 별칭 목록 — 검토 대상."""
    groups: dict[tuple[str, str | None], set[tuple[str, str]]] = {}
    for a in s.scalars(select(m.Alias)):
        groups.setdefault((normalize(a.text), a.scope_hull_id), set()).add((a.target_kind, a.target_id))
    return [(k, h, sorted(t)) for (k, h), t in groups.items() if len(t) > 1]
