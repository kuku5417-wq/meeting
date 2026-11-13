# meeting — 커미셔닝팀 주간 회의자료 · 지식화 시스템

메모를 붙여넣으면 AI가 회의자료 블록으로 정리하고, 사람은 검토만 한다.
확정된 내용은 편집 가능한 PPT와 웹 회의 화면으로 나가고, 동시에 지식창고에 구조화 데이터로 쌓인다.

## 실행

```
setup_env.bat        # 최초 1회: uv 설치(망 자동감지) → check_env → 실행
run.bat              # 이후: 운영 PC 에서 서버 실행
```

브라우저에서 http://localhost:8600 (다른 PC 는 `http://<운영PC IP>:8600`)

- 64비트 Python 3.12 + uv 필요. venv 는 `%LOCALAPPDATA%\venvs\meeting`
- 비밀값·경로는 상위 폴더 `secret\.env` 하나 — 키 이름은 `.env.template`
- **데이터 저장 위치**(meeting.db·사진·PPT)는 `secret\.env` 의 `MEETING_DATA_PATH` 로 정한다(예: `D:\meeting_data`). 비우면 NAS → `code_N\data\meeting`. 서버 창 첫 줄과 `check_env.py` 에 실제 위치가 나온다
- 회귀 확인 `uv run python _smoke.py` · 가동 전 점검 `uv run python check_env.py --quick`

## 폴더 구조

| 경로 | 내용 |
|---|---|
| `app/` | FastAPI 앱 (main·settings·db·models·services·templates·static) |
| `app_config.py` · `_netcheck.py` | 전 repo 동일본 (망 감지·프록시) — 고치지 않는다 |
| `path_config.py` | 경로 계층 — 데이터는 `<base>/meeting/` (DB·사진·내보내기, git 밖) |
| `design/` | 확정 시안·토큰 · `docs/` 기획·설계 · `data/samples/` 가상 시드 |

## 문서 링크

- **처음이라면: `docs/storyboard.html`** (브라우저로 여는 발표 슬라이드 · F 전체 화면) · 글 버전 `docs/00_스토리보드.md`
- 개발 안내: `CLAUDE.md` (code_N 공통지침 위에 얹힌다)
- 기획서 `docs/01_기획서.md` · 화면 설계 `docs/02_화면설계.md` · 데이터 모델 `docs/03_데이터모델.md`
- AI 처리 `docs/04_AI처리.md` · 개발 로드맵 `docs/05_개발로드맵.md`

## Claude Code로 작업할 때

`/next` — 로드맵에서 아직 안 끝난 가장 앞 마일스톤을 이어서 진행한다.
