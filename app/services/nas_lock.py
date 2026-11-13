"""NAS 잠금 파일 — 한 번에 한 PC 만 DB 에 쓴다 (결정 ① 4-b, 2026-11-13).

NAS(SMB) 위 SQLite 의 파일 잠금은 믿을 수 없어서 앱이 직접 막는다.
- 쓰기 트랜잭션이 시작될 때(첫 flush) `meeting.lock` 을 **단독 생성**(O_EXCL)하고, 트랜잭션이 끝나면(commit·rollback) 지운다.
- 파일에는 PC 이름·프로세스·시각을 적어 「누가 쓰는 중인지」 알린다.
- 기다림 한도(DB_LOCK_WAIT_SEC)를 넘으면 LockBusy — 화면은 「잠시 뒤 다시 저장」 안내.
- STALE_SEC 넘은 잠금은 주인 없는 것으로 보고 정리한다(PC 가 꺼지는 등).
쓰기는 짧게: AI 호출·파일 변환·PPT 만들기는 잠금 밖에서 하는 것이 원칙이다(메모 저장과 AI 정리를 나누는 일은 후속).
"""
from __future__ import annotations

import os
import socket
import time
from pathlib import Path

from app import settings


class LockBusy(Exception):
    pass


def _holder(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8").strip() or "알 수 없음"
    except OSError:
        return "알 수 없음"


def acquire(path: Path, wait_sec: float | None = None, stale_sec: float | None = None) -> None:
    wait_sec = settings.DB_LOCK_WAIT_SEC if wait_sec is None else wait_sec
    stale_sec = settings.DB_LOCK_STALE_SEC if stale_sec is None else stale_sec
    me = f"{socket.gethostname()} pid={os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')}"
    end = time.monotonic() + wait_sec
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(me)
            return
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except FileNotFoundError:
                continue                                  # 방금 풀림 — 다시 시도
            if age > stale_sec:                           # 주인 없는 잠금 정리
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() >= end:
                raise LockBusy(f"다른 PC 가 저장하는 중입니다({_holder(path)}). 잠시 뒤 다시 저장해주세요.") from None
            time.sleep(0.05)


def release(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def install(session_factory, lock_path_fn) -> None:
    """세션 공장에 이벤트를 단다 — 첫 flush 에서 잡고, 바깥 트랜잭션이 끝나면 푼다."""
    from sqlalchemy import event

    @event.listens_for(session_factory, "before_flush")
    def _take(session, _ctx, _inst):  # noqa: ANN001
        if not session.info.get("nas_lock"):
            p = lock_path_fn()
            acquire(p)
            session.info["nas_lock"] = p

    @event.listens_for(session_factory, "after_transaction_end")
    def _drop(session, transaction):  # noqa: ANN001
        if transaction.parent is None and session.info.get("nas_lock"):
            release(session.info.pop("nas_lock"))
