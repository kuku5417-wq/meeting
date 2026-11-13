"""app/settings.py — meeting 앱 설정 (DB 위치·LLM 체인·업무 설정).

망 감지·프록시·.env 로드는 루트의 `app_config`(전 repo 동일본)가 맡고,
경로는 `path_config` 가 맡는다. 이 파일은 그 둘을 모아 앱이 쓰는 값만 내놓는다.

※ 파일명이 `config.py` 가 아닌 이유: 공통지침 — `import config` 가 형제 앱의 `config/` 패키지와
  충돌한다. 앱 코드에서 `load_dotenv` 를 직접 부르지 않는다(사내 프록시가 사외망에 주입된다).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # meeting/
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))                      # 자기 폴더 최우선 — 형제 앱 app_config 오인 방지

import app_config  # noqa: E402,F401  (import 부수효과: .env 로드 + 프록시 정책)
import path_config as pc  # noqa: E402

APP_TITLE = "커미셔닝팀 주간보고"
PORT = 8600


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, "") or default)
    except ValueError:  # noqa: PERF203 — 잘못된 값 → 기본값
        return default


def database_url() -> str:
    """SQLAlchemy URL. `MEETING_DATABASE_URL` 로 덮어쓸 수 있다(운영 PostgreSQL 전환 대비)."""
    ov = os.getenv("MEETING_DATABASE_URL", "")
    if ov:
        return ov
    return f"sqlite:///{pc.db_path().as_posix()}"


# ── 저장(결정 ①) ─
DB_BUSY_TIMEOUT_MS = _int("MEETING_DB_BUSY_TIMEOUT_MS", 5000)   # 다른 PC 가 쓰는 중일 때 기다리는 시간
DB_BACKUP_KEEP = _int("MEETING_DB_BACKUP_KEEP", 14)             # 매일 백업 몇 개를 남기나

# ── LLM ─────────────────────────────────────────────────
# 앞에서부터 시도하는 공급자 목록 — 결정 ④(2026-11-13): SOLA·GPT 두 개. Upstage 뺌, Mock 은 테스트 전용(사용자 체인에 넣지 않음).
# 둘 다 실패하면 공급자별 사유를 보여 주고 메모는 그대로 남는다 — 이슈는 사람이 직접 쓴다.
# ⚠ openai 는 외부 API 다. 원칙 9(사내 LLM 으로만)의 테스트 단계 예외 — 실제 회사 메모를 넣기 전에 sola 하나로 줄일지 다시 정한다.
#   외부로 보내지 않으려면 secret/.env 에 MEETING_LLM_CHAIN=sola 를 둔다.
LLM_CHAIN_DEFAULT = "sola,openai"
LLM_CHAIN = [s.strip().lower() for s in os.getenv("MEETING_LLM_CHAIN", LLM_CHAIN_DEFAULT).split(",")
             if s.strip()]
LLM_TIMEOUT_SEC = _int("MEETING_LLM_TIMEOUT_SEC", 60)

# ── 업무 설정 ───────────────────────────────────────────
LONG_OPEN_WEEKS = _int("MEETING_LONG_OPEN_WEEKS", 4)   # 장기 미결 기준 주 수(로드맵 「미정」, 기본 4)

# ── 메일 수집(M13, F22) — 서버 PC 의 클래식 Outlook(COM)에서 읽는다. pywin32·Outlook 이 없으면 휴면 ──
# 결정 ③(2026-11-13): 메일함·DRM 엑셀(Outlook·Excel COM)은 1차 판에서 끈다 — 각자 PC 실행이라 「서버 PC 한 대」 전제가 없어짐.
# 코드는 그대로 두고 MEETING_COM_IMPORTS=on 일 때만 켠다(2차에서 어느 PC 에서 켤지 다시 정함).
COM_IMPORTS = os.getenv("MEETING_COM_IMPORTS", "off").strip().lower() in ("on", "1", "true", "yes")
MAIL_FOLDER = os.getenv("MEETING_MAIL_FOLDER", "").strip()     # 받은편지함 아래 경로(예: 회의자료). 비면 메일함 입구가 꺼진다
MAIL_DAYS = _int("MEETING_MAIL_DAYS", 14)                       # 「메일함에서 가져오기」가 보는 기간(일)
IMPORT_MAX_MB = _int("MEETING_IMPORT_MAX_MB", 30)               # 올리는 파일 한 개 크기 한도

ENV_LABEL = pc.get_env_label()
