"""pytest 공통 — 저장소 루트를 import 경로에 넣는다.

환경 주입(임시 데이터 폴더·오늘 날짜 고정·Outlook 끔·LLM 키 비움)은 `_smoke.py` 맨 위에서 한다.
`_smoke` 를 **app 보다 먼저** import 해야 엔진이 임시 DB 를 잡는다 — test_smoke_groups.py 가 그렇게 한다.
결정 ②(2026-11-13): _smoke 검사를 pytest 로 옮기는 중. 1-a = 묶음 단위로 돌리기, 1-b = 영역별 파일로 쪼개기.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
