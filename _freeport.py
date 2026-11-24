"""_freeport.py — 빈 포트 찾기 (run.bat 이 서버를 띄우기 전에 부른다).

단계 11(2026-11-24): 서버는 **127.0.0.1 에서만** 연다(남이 접속하는 서버 금지 — shi 규약·사내 정책).
그래서 포트가 겹쳐도 다른 사람에게 영향이 없고, 쓰고 있는 포트면 다음 번호를 쓰면 된다.

표준 라이브러리만 쓴다 — venv 없이 시스템 파이썬으로도 돌아야 한다.

사용:
    python _freeport.py            # 빈 포트 하나를 출력 (없으면 종료코드 1)
    python _freeport.py 8600 11    # 8600 부터 11개 안에서 찾기
"""
from __future__ import annotations

import socket
import sys

START = 8600
COUNT = 11          # 8600~8610


def is_free(port: int, host: str = "127.0.0.1") -> bool:
    """그 포트에 bind 할 수 있나 — 열어 보고 바로 닫는다."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def find(start: int = START, count: int = COUNT, host: str = "127.0.0.1") -> int:
    """빈 포트 번호. 없으면 0."""
    for p in range(start, start + count):
        if is_free(p, host):
            return p
    return 0


def main() -> int:
    start = int(sys.argv[1]) if len(sys.argv) > 1 else START
    count = int(sys.argv[2]) if len(sys.argv) > 2 else COUNT
    port = find(start, count)
    if not port:
        print(f"[FAIL] {start}~{start + count - 1} 사이에 빈 포트가 없습니다", file=sys.stderr)
        return 1
    print(port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
