"""자료 하나 = 한 명씩 편집 (결정 ⑦ 15-7, 2026-11-24).

왜 필요한가: 회의자료의 장 순서·회의용 한 줄·개체 배치는 **판 번호로 막을 수 없는 것**이 섞여 있다
(결정 ① 의 `row_version` 은 이슈 사실 칸을, 15-2 의 `free_rev` 는 개체 묶음을 막는다).
두 사람이 같은 자료를 동시에 꾸미면 나중에 저장한 쪽이 앞사람 작업을 조용히 덮는다.

어떻게 가르는가: 로그인이 없으므로 **브라우저 표(token)** 하나를 사람으로 본다.
  - 같은 브라우저의 여러 탭 = 한 사람(표가 `localStorage` 에 있다).
  - 다른 PC·다른 브라우저 = 다른 사람.
  - 표는 그냥 구분용 난수다 — 개인정보가 아니고, 화면에도 보여 주지 않는다.
  - **누가·어디서인지는 담지 않는다**(최소수집, 공통규칙 7). 화면이 쓰는 것은 「남이 쥐고 있나·몇 분 남았나」뿐이다.

언제 풀리는가: **입력이 없으면 10분 뒤**(`settings.EDIT_LOCK_MIN`).
저장할 때마다 `touched_at` 을 새로 찍으므로, 쓰는 동안에는 풀리지 않고 창을 그냥 닫으면 10분 뒤 다음 사람이 가져간다.
읽기만 하는 사람은 아무것도 잡지 않는다 — 잠금은 **쓸 때와 편집 화면을 열 때**만 잡는다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import models as m
from app import settings
from app.services import writing as w


class Locked(w.WriteError):
    """다른 사람이 편집 중 — 라우터가 409 로 돌려주고 화면은 읽기 전용으로 바꾼다."""


def _ttl() -> timedelta:
    return timedelta(minutes=max(1, int(settings.EDIT_LOCK_MIN)))


def _row(s: Session, meeting_id: int) -> m.EditLock | None:
    return s.get(m.EditLock, int(meeting_id))


def _alive(row: m.EditLock | None) -> bool:
    return row is not None and (datetime.now() - row.touched_at) < _ttl()


def _left_min(row: m.EditLock) -> int:
    """몇 분 뒤에 풀리나(올림, 최소 1)."""
    gone = _ttl() - (datetime.now() - row.touched_at)
    return max(1, int(gone.total_seconds() // 60) + 1)


def _since_min(row: m.EditLock) -> int:
    return max(0, int((datetime.now() - row.touched_at).total_seconds() // 60))


def state(s: Session, meeting_id: int, token: str) -> dict:
    """화면에 주는 잠금 상태 — 표 자체는 돌려주지 않는다(다른 사람의 표를 알 이유가 없다)."""
    row = _row(s, meeting_id)
    if not _alive(row):
        return {"held": False, "mine": False, "min_": int(settings.EDIT_LOCK_MIN)}
    return {"held": True, "mine": row.token == (token or ""),
            "since": _since_min(row), "left": _left_min(row), "min_": int(settings.EDIT_LOCK_MIN)}


def claim(s: Session, meeting_id: int, token: str) -> dict:
    """편집을 잡는다(또는 이어 간다). 다른 사람이 쥐고 있으면 잡지 않고 상태만 돌려준다."""
    if not token:
        return state(s, meeting_id, token)
    row = _row(s, meeting_id)
    if _alive(row) and row.token != token:
        return state(s, meeting_id, token)
    if row is None:
        row = m.EditLock(meeting_id=int(meeting_id), token=token)
        s.add(row)
    else:
        row.token = token
    row.touched_at = datetime.now()
    s.flush()
    return state(s, meeting_id, token)


def require(s: Session, meeting_id: int, token: str) -> dict:
    """쓰기 전에 — 내 것이면 시각을 새로 찍고, 남의 것이면 **거절**한다.

    표가 없는 요청(옛 화면·검사 도구)은 막지 않는다 — 잠금은 사람을 돕는 장치이지 문지기가 아니다.
    대신 그런 요청은 잠금을 잡지도 않는다.
    """
    if not token:
        return state(s, meeting_id, token)
    row = _row(s, meeting_id)
    if _alive(row) and row.token != token:
        raise Locked(f"이 자료는 다른 곳에서 편집 중입니다(마지막 입력 {_since_min(row)}분 전). "
                     f"{_left_min(row)}분 안에 입력이 없으면 풀립니다 — 그때 「내가 편집」을 누르세요.")
    return claim(s, meeting_id, token)


def release(s: Session, meeting_id: int, token: str) -> None:
    """내 편집을 놓는다(창을 닫을 때). 남의 것은 건드리지 않는다."""
    row = _row(s, meeting_id)
    if row is not None and row.token == (token or ""):
        s.delete(row)
        s.flush()
