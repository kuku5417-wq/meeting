"""DB 지키기 — 매일 첫 실행 백업 + 무결성 점검 (결정 ①, 2026-11-13).

NAS 위 SQLite 하나를 여러 PC 가 쓰므로, 하루 첫 실행 때
1) `backups/meeting-YYYYMMDD.db` 로 복사(SQLite 백업 API — 쓰는 중이어도 일관된 사본), 오래된 것은 DB_BACKUP_KEEP 개만 남김
2) `PRAGMA integrity_check` — 깨졌으면 결과를 돌려주고 화면이 알린다(읽기 전용 전환은 4-b 잠금과 함께).
같은 날 두 번째 실행부터는 아무것도 하지 않는다(파일이 이미 있음).
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from app import settings


def daily(db_file: Path, backup_dir: Path, today: date | None = None) -> dict:
    """하루 한 번. 반환: {"backup": 경로 또는 None, "made": 새로 만들었나, "integrity": "ok" 또는 오류 글, "removed": [지운 옛 백업]}."""
    today = today or date.today()
    out = {"backup": None, "made": False, "integrity": "ok", "removed": []}
    if not db_file.exists():
        return out
    target = backup_dir / f"meeting-{today:%Y%m%d}.db"
    out["backup"] = target
    if target.exists():
        return out
    src = sqlite3.connect(str(db_file))
    try:
        row = src.execute("PRAGMA integrity_check").fetchone()
        out["integrity"] = (row[0] if row else "결과 없음") or "결과 없음"
        tmp = target.with_suffix(".tmp")
        dst = sqlite3.connect(str(tmp))
        try:
            src.backup(dst)
        finally:
            dst.close()
        tmp.replace(target)            # 임시 파일 → 이름 바꾸기(반쯤 쓴 백업이 남지 않게)
        out["made"] = True
    finally:
        src.close()
    olds = sorted(backup_dir.glob("meeting-*.db"))
    for p in olds[:-settings.DB_BACKUP_KEEP] if len(olds) > settings.DB_BACKUP_KEEP else []:
        p.unlink(missing_ok=True)
        out["removed"].append(p.name)
    return out
