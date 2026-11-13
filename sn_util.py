"""sn_util.py — 호선번호 SN 표기 통일 (공통지침 절대 규칙 3).

출처 스냅샷: `dcost/sn_util.py` `ensure_sn` (pjtcost 와 동일본, data_manager_F 정본 이식) · 2026-10-20 확인.
이 앱은 pandas 를 쓰지 않아 NaN 판정만 `math.isnan` 으로 바꿨다. 변환 규칙은 그대로다.

- `SN2601` / `S2601` / `2601` → `SN2601` (SN **부착**)
- 빈값·NaN·`"NAN"`·`"NAT"`·`"NONE"` → `""` (유령 호선 방지 — 이 가드를 빼지 말 것)
- 표시단에서 `f"SN{...}"` 재부착 금지 (`SNSN2601` 중복)
"""
from __future__ import annotations

import math


def ensure_sn(val) -> str:
    """SN2601, S2601, 2601 → 'SN2601'. 빈값/NaN 은 '', 그 외 형태는 원본(대문자) 그대로."""
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    s = str(val).strip().upper()
    if not s or s in ("NAN", "NAT", "NONE"):
        return ""
    if s.startswith("SN"):
        return s
    if s.startswith("S") and s[1:].isdigit():
        return "SN" + s[1:]
    if s.isdigit():
        return "SN" + s
    return s
