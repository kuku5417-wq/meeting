# CLAUDE.md — 커미셔닝팀 주간 회의자료 · 지식화 시스템

이 파일은 Claude Code가 이 저장소에서 작업할 때 먼저 읽는 안내서다.
작업 전에 이 파일과 `docs/05_개발로드맵.md`의 현재 마일스톤을 확인하고 시작한다.

> **`trans` 브랜치 = 사내망 전환 작업본(2026-11-13~).** `main`은 원본 그대로 두고 여기서만 고친다.
> - `requirements.md` 5장 **결정 ①~⑨가 아래 옛 규칙보다 우선**한다(⑨ 지식 그래프 = 6장). 특히 ② 테스트는 pytest로 옮긴다, ③ 메일·DRM은 1차에서 끈다, ④ LLM은 `sola,openai`(Mock은 테스트 전용), ⑤ `app_config.py`·`_netcheck.py`는 shi 전환 지점으로 대신한다, ⑦ 캔버스 편집은 자료에만·사실은 사실 칸/「사실로 채택」.
> - **이어서 할 일: `workinglog.md` 맨 아래 「남은 일 전체 계획」 표**(단계 0~13). 옮기기 전까지 아래 옛 규칙(`_smoke.py`, `app_config.py` 등)은 지금 코드 기준이다.
> - 결정 근거·검토 문서: GitHub `kuku5417-wq/agent_trans`의 `사례/meeting*.md`.
> - 다른 PC에서 받아 이어가는 방법: `이어서_하기.md`.

## 1. 무엇을 만드는가

커미셔닝팀 8개 부서가 매주 쓰는 주간 회의자료(현재 PPT)를 **웹 입력 → 자동 보고서 생성** 방식으로 바꾸고,
작성과 동시에 내용을 **구조화 데이터(AI-ready)** 로 쌓아 지식창고·지식 그래프·사내 챗봇에서 쓰게 한다.

- 작성자는 메모를 붙여넣고, AI가 블록(공유정보/문제점/이슈/대시보드)으로 정리하고, 사람은 검토·수정만 한다.
- 결과물은 **편집 가능한 PPT** 와 **웹 회의 화면** 두 가지.
- 이슈·문제점은 **부서 현안 공유회**에서(또는 **기획 주관자**가) **종결 승인**하면 **사례 카드**로 승격되어 지식창고에 들어간다.
- 모든 블록은 **기준정보(호선·탑재 장비·장비 모델·시스템·부서)** 에 ID로 연결된다.

배경과 결정 사항 전체: `docs/01_기획서.md`

## 2. 문서 지도

| 파일 | 내용 | 언제 읽나 |
|---|---|---|
| **`requirements.md`** | **정본** — 목적·역할·업무 흐름·화면 지도·기능·업무 규칙·전환 지점·결정 기록. 다른 문서와 다르면 이것이 이긴다 | **매 작업 시작 시 먼저** |
| `docs/00_스토리보드.md` · `docs/storyboard.html` | 처음 보는 사람용 장면별 설명(가상 인물·데이터) — html 은 같은 내용의 **발표 슬라이드**(16:9·장면 애니메이션·ppt-executive 디자인, 단일 파일, 외부 요청 없음) | 설명·소개할 때 — 화면이 바뀌면 **둘 다** 고친다 |
| `docs/01_기획서.md` | 배경, 결정 사항, 지식창고 구성, 연결고리 | 방향이 헷갈릴 때 |
| `docs/02_화면설계.md` | 옛 1단계 화면 기록(지식창고·장비 허브 절은 참고) — 지금 화면은 requirements.md 0-4 | 참고만 |
| `docs/03_데이터모델.md` | 테이블, ID 규칙, 상태 전이, ER | DB·API 작업 전 |
| `docs/04_AI처리.md` | 메모→블록 추출, 별칭 매핑, 프롬프트, 검증 | AI 기능 작업 전 |
| `docs/05_개발로드맵.md` | 마일스톤 M0~M8, 작업 목록, 완료 기준 | 매 작업 시작 시 |
| `docs/06_재설계안.md` | **재설계(시안 단계)** — 이슈 기록·지식 매핑과 회의자료 채택·구성 분리, 회의 종류·템플릿, M9~ | 다음 구조를 정할 때 |
| `docs/07_기능_업무흐름_기획서.md` | 목적·역할·업무 흐름·기능 F1~F23·결과물·사용자 논의 결정 | 기능 범위를 정할 때 |
| `docs/08_벤치마킹_샘플2.md` | 외부 샘플(`docs/v2_sample_2_light.html`, 참고 전용)과 우리 시안 비교 — 가져올 것·안 되는 것 | 시안을 고칠 때 |
| `design/mockups/*.html` | 확정된 화면 시안 (브라우저로 열기) | UI 구현 시 그대로 참고 |
| `design/tokens.css` · `docs/디자인_규칙.md` | **토큰 정본**(원시 → 의미 → 옛 이름 3층, 라이트/다크) · 색 쓰는 규칙·컴포넌트 방식 | 모든 CSS의 출발점, 화면 작업 전 |
| `schema/extraction.schema.json` | AI 추출 결과 JSON 스키마 | LLM 출력 검증 |
| `data/samples/` | 예시 메모, Mock AI 결과, 기준정보 CSV(`masters/`) | 개발용 시드 데이터 |
| `.claude/commands/` | `/next` 다음 작업 진행, `/check-mockup` 시안 비교 | 반복 작업 |

## 3. 기술 스택 (1단계)

> **code_N 공통지침이 이 파일보다 우선한다**(2026-10-19 결정). 번들 원본의 venv+pip·`F:\code\secret\.env`·
> `app/config.py`·pytest·포트 8000 은 공통지침(uv·`secret/.env` 상향 탐색·`app_config.py`·`_smoke.py`·포트 8600)으로 바꿨다.
> 원본 번들은 `_bundle.tgz`(git 제외)에 그대로 있다.

- **Python 3.12 (64비트)**, **FastAPI**, **SQLAlchemy 2.x**, **Pydantic v2**, **SQLite** (운영 전환 시 PostgreSQL 고려)
- 화면: **Jinja2 템플릿 + 바닐라 JS(ES modules)**, CSS는 `design/tokens.css` 기반
  - 기획서 초안의 Streamlit은 쓰지 않는다. 3단 편집기·사진 편집기·회의 모드가 Streamlit 구조와 맞지 않기 때문.
- 글꼴: **로컬 서브셋** `app/static/fonts/`(Meeting Sans KR · Meeting Mono = IBM Plex 서브셋, OFL). 외부 글꼴 CDN 을 쓰지 않는다. 2026-10-22 본문 글꼴 하나로 통일 — 제목도 Meeting Sans KR(굵기 600), Gothic A1 은 쓰지 않는다. PPT 는 맑은 고딕
- 글자 크기 5단계 `--fs-1`~`--fs-5`(13·14·15·19·28, 2026-11-13 v2m 시안 값으로 통일), 화면 최소 13px — CSS 에 px 글자 크기를 직접 쓰지 않는다(슬라이드 미리보기·발표 좌표 예외). 색은 **`design/tokens.css` 정본**(앱 사본 `app/static/css/tokens.css` 와 같아야 함) — 상태 3색(회색·파랑 #0963c4·빨강) + 분류 5색, 흰 사이드바(2026-11-13 결정 ⑥⑧). 규칙은 `docs/디자인_규칙.md`
- 사진 편집기: **Konva.js 9.3.6** — `app/static/vendor/konva.min.js` 사본(출처·sha256 은 그 폴더 README). 합성은 **Pillow**
- 차트: 직접 SVG (시안과 동일 방식). 필요 시 Chart.js vendor
- PPT 출력: **python-pptx**, 템플릿 `.pptx`는 `app/export/templates/`
- LLM: 사내 LLM/챗봇 API (OpenAI 호환 가정), 어댑터 뒤에 숨긴다 (`app/llm/`)
- 테스트: **`uv run pytest -q tests`**(영역별 파일 test_00~test_10 + 검사 수 확인 test_99, 세션 하나로 순서대로 — 2026-11-13) · `uv run python _smoke.py`(같은 검사). 검사 함수 정본은 아직 `_smoke.py`, 새 검사는 그 묶음에 더하고 `tests/test_99_count.py` 의 개수를 올린다

## 4. 환경 규칙

- **uv + 64비트 Python 3.12**, venv 는 **`%LOCALAPPDATA%\venvs\meeting`** (로컬 C:). 의존성은 `pyproject.toml` + `uv.lock`.
  ```
  setup_env.bat                  # 설치(망 자동감지·uv sync --locked) → check_env → 실행
  run.bat                        # 운영 PC 에서 서버만 실행 (포트 8600, 0.0.0.0)
  uv run python _smoke.py        # 회귀 확인 — 통과해야 끝난 것
  uv run python check_env.py --quick
  ```
  개발 중 직접 실행: `uv run uvicorn app.main:app --port 8600 --reload`
  (환경변수 `UV_PROJECT_ENVIRONMENT=%LOCALAPPDATA%\venvs\meeting` 를 두면 `uv run` 이 같은 venv 를 쓴다)
- 비밀값은 상위 폴더의 **`secret/.env` 하나**(위로 올라가며 첫 파일, `SHI_ENV_FILE` 로 강제 가능). 키 이름은 `.env.template`.
  앱 전용 키는 `MEETING_` 접두어(`MEETING_DATA_PATH`·`MEETING_LLM_CHAIN`·`MEETING_LONG_OPEN_WEEKS` 등).
- 망 감지·프록시는 루트 **`app_config.py`(전 repo 동일본, 수정 금지)**, 경로는 **`path_config.py`** 만 경유한다.
- 중앙 parquet 은 **`pjtlist`·`milestone` 두 개만 읽는다**(2026-10-21, `app/services/central.py`, pyarrow — pandas 없음). 쓰지 않는다(공통 규칙 2).
  - 호선은 **pjtlist 가 정본** — 서버 시작·설정 화면 「지금 다시 읽기」·`seed_masters.py` 끝에서 `hull` 을 만들거나 고치고, 지우지 않는다.
  - 마일스톤 날짜는 **행(호선)마다** 실적(PERF) → 전망(PROS) → 계획(PLAN). 열 이름은 접두가 앞(`PLANDL`). `GT` = 가스시운전.
  - 폴더는 `MEETING_CENTRAL_PARQUET` → NAS → `DATA_PATH\parquet`. 파일이 없으면 동기화만 건너뛰고 앱은 뜬다.
  앱 설정은 `app/settings.py` 에 모은다(`config.py` 금지 — 형제 앱 `config/` 패키지와 충돌).
- 데이터(SQLite·사진 원본·내보내기)는 **`<NAS_BASE_PATH 또는 DATA_PATH>/meeting`** — git 밖이니 파일 백업 대상이다.
- LLM 호출은 **폴백 체인**으로 설정한다. 순서는 `.env`의 `MEETING_LLM_CHAIN`(기본 `sola,openai` — 결정 ④, Mock 은 테스트 전용. 둘 다 실패하면 사유 안내, 메모는 남고 사람이 쓴다).
  mock 은 `data/samples/mock_extraction.json`을 돌려준다. **실제 API 없이도 전 기능이 돌아가야 한다.**
  공급자별 실패 사유는 화면 알림과 `llm_call_log` 에 남는다(본문은 저장하지 않는다). 원칙 9 와의 충돌은 6장 참고.

## 5. 폴더 구조 (만들어 갈 모양)

```
app_config.py        전 repo 동일본 (.env 로드·망 감지·프록시) — 고치지 않는다
path_config.py       경로 계층 (<base>/meeting, DB·사진·내보내기)
sn_util.py           ensure_sn — 호선 SN2511 정규화 (dcost 동일본 스냅샷, pandas 제거)
_netcheck.py         설치 시점 망 감지 (setup_env.bat 이 호출, 전 repo 동일본)
check_env.py         가동 전 점검      _smoke.py   회귀 확인
setup_env.bat / run.bat   (ASCII + CRLF)
app/
  main.py            FastAPI 앱, 라우터 등록
  settings.py        앱 설정 (DB URL·LLM 체인·업무 설정)
  db.py              엔진, 세션
  models/            SQLAlchemy 모델 (docs/03 기준) — masters / writing / others
  schemas/           Pydantic 입출력
  routers/           write(메모·블록·지표 동작), photos, issues, studio, run(회의 진행·지시·종결), importer(가져오기), masters, export
  services/          extract.py, alias.py, carry_over.py, closure.py, promotion.py, search.py
  llm/               client.py(어댑터·폴백), prompts/*.md
  export/            pptx_builder.py, templates/
  templates/         Jinja2 (base · home · issues · meetings · studio · meeting_view · run · import · metrics · knowledge · hub …)
  static/            css/, js/, vendor/
scripts/             seed_masters.py (CSV → DB, 다시 실행해도 중복 없음), seed_demo.py (시연용 가상 사례 — 운영 DB 금지),
                     migrate_sections.py (옛 섹션 → 회의자료 판, --dry-run 먼저, 다시 실행해도 중복 없음),
                     fix_department_names.py (자리표시 「부서 1」~ → department.csv 실제 이름 + 부서 회의자료 제목, 부서만 — 운영 DB 용)
```
데이터는 저장소 밖 `<base>/meeting/` (meeting.db, photos/, exports/).
```

## 6. 꼭 지킬 원칙 (도메인 규칙)

1. **원본은 바꾸지 않는다.** 원본 메모(`memo.raw_text`)와 사진 원본 파일은 수정·삭제하지 않는다. 메모 원문을 고칠 때는 **새 판**으로 저장하고(`memo.revises_id`) 옛 판은 남긴다. 마킹은 사진 위에 굽지 않고 **좌표 JSON** 으로 따로 저장하고, 출력할 때만 합성한다.
2. **AI 값과 사람 값을 둘 다 남긴다.** AI가 채운 필드를 사람이 고치면 `ai_field_log`에 (AI 값, 사람 값)을 기록한다.
3. **근거 없는 AI 값은 표시하지 않는다.** 추출된 각 필드는 메모 안의 근거 구간(source span)을 가져야 한다. 근거가 없으면 빈 칸으로 두고 질문으로 되묻는다.
4. **질문은 2~3개 이내.** 빈 칸 질문은 필수 항목(제목, 상태, 문제점의 원인)만.
5. **기준정보 ID로 연결한다.** 태그는 자유 문자열이 아니라 마스터 ID를 가리킨다. 매핑 못 한 표기는 `raw_text`로 보관하고 검토 화면에서 사람이 고르면 **별칭 사전에 추가**한다.
6. **장비 모델과 탑재 장비를 구분한다.** 이슈는 탑재 장비(EQ-…)에 연결하고, 탑재 장비가 장비 모델을 가리킨다.
7. **종결은 부서 현안 공유회 또는 기획 주관자만.** 부서는 "종결 요청"(조치 내용 필수)까지. 승인은 부서 현안 공유회의 회의 진행 화면(`/meetings/{id}/run`)에서, 또는 기획 주관자가 언제든(홈 「종결 요청」의 승인·보류). 승인 시 사례 카드로 승격. 「종결」은 이슈에 쓰는 말이고, 회의자료는 부서가 「제출」한다(2026-10-21 결정, 재설계 v2 — `docs/06`).
8. **ID는 사람이 읽을 수 있게.** `ISS-2026-0142` 같은 규칙은 `docs/03` 참고. ID는 블록이 부서를 옮겨도 바뀌지 않는다.
9. **민감정보.** 보고 내용은 사내 LLM으로만 보낸다. 사진 모자이크 기능 유지.
   ⚠ **테스트 단계 예외(2026-10-20 사용자 결정)**: 체인이 공통지침 3단(SOLA → Upstage → OpenAI → Mock)이라 외부 API 호출 코드가 있다.
   운영 전에 다시 정한다 — 그때까지 실제 회사 메모는 넣지 않고, 외부를 막으려면 `MEETING_LLM_CHAIN=sola`. (2026-11-13 결정 ④로 기본 체인은 `sola,openai`)

## 7. 화면 구현 규칙

- 시안(`design/mockups/`)이 정답이다. 레이아웃·문구·색 토큰을 그대로 따른다. 다르게 해야 하면 이유를 남긴다.
- UI 문구는 한국어, 짧은 평서문. 버튼은 실제 동작을 쓴다 ("부서 섹션 확정", "종결 승인").
- 오류 메시지는 무엇이 문제고 어떻게 고치는지 말한다 ("카고펌프 블록의 원인 칸을 채워주세요").
- 라이트/다크 모두 `tokens.css` 변수만 사용한다. 색을 직접 쓰지 않는다.
- 폭 400px 휴대폰 화면에서도 깨지지 않게 한다 (현장 확인용).

## 8. 작업 방식

- 마일스톤 단위로 작업한다. 시작할 때 `docs/05_개발로드맵.md`에서 해당 마일스톤의 작업과 완료 기준을 읽고, 끝나면 체크박스를 갱신한다.
- 기능마다 `_smoke.py` 검사를 같이 쓴다. 특히 `services/` 로직(별칭 매핑, 이어받기, 상태 전이, 승격)은 검사 필수.
- 코드 수정 후에는 commit + push (공통지침, 한국어 메시지).
- 스키마를 바꾸면 `docs/03_데이터모델.md`도 같이 고친다.
- 사내 API 사양이 아직 미정인 부분은 어댑터 인터페이스만 만들고 Mock으로 진행한다. 추측한 사양을 하드코딩하지 않는다.
- 실제 회사 데이터는 저장소에 넣지 않는다. `data/samples/`는 가상 데이터만.

## 9. 용어

| 용어 | 뜻 |
|---|---|
| 블록 | 보고서의 한 단위. 공유정보 / 문제점 / 이슈 / 대시보드 |
| 부서 섹션 | 한 주차·한 부서의 블록 묶음(옛 흐름). M11 부터 확정하지 않고 M12 에서 확정 개념을 지웠다 — 지금은 메모 넣기(옛 화면)가 메모를 붙이는 자리. 지난 주차는 이전 스크립트로 회의자료 판이 된다 |
| 지표 · 기간 표 | 부서 주간 지표(이번 주만 입력, 평소 범위 = 정한 값 또는 최근 n주 평균 ± 2σ, 이탈이면 차이 사유)와 기간 표(행 × 날짜 × 계획/실적, 행 이름 자유). 회의자료에는 「지표 요약」 장과 표마다 「기간 표」 장으로 |
| 일정 경보 | 이슈의 「~전 해결」 목표(마일스톤 이벤트 또는 날짜)가 D-n 이내면 「일정 임박」. 해제는 사유와 함께, 날짜가 당겨지면 다시 켜짐 |
| 지시사항 | 회의 중 지시(내용·담당 부서·기한). 다음 주 그 부서 회의자료 맨 위에 나오고, 한 줄 보고로 완료. 다음 회의 첫머리에서 점검 |
| 이어받기 | 진행 중인 이슈·문제점이 다음 주 섹션에 자동으로 다시 올라오는 것 |
| 이관 | 블록 담당 부서를 바꾸는 것. ID 유지 |
| 종결 요청 / 승인 | 부서가 조치 내용과 함께 요청 → 부서 현안 공유회에서, 또는 기획 주관자가 승인·보류 |
| 1차 초안 | 과장·호선 담당자가 이슈마다 만드는 회의용 초안. 이슈 칸에서 「상세 한 장」이 자동으로 그려지고, PPT 한 장으로 대신할 수도 있다 |
| 부서 회의자료 | 부장·부서 스텝이 초안을 골라 고친 그 주 부서 자료. 고친 사실은 이슈에 바로 반영(작성자 알림), 표현은 자료에만 |
| 제출 | 부서 회의자료를 부서 현안 공유회로 넘기는 것. 판으로 고정되고 공유회가 그 판을 참조한다. 막지 않고 미업데이트 수만 표시 |
| 발행 · 판 | 공유회·팀장 정보회의 등 회의자료를 판으로 고정하는 것(meeting_version). 발행 뒤 이슈 사실이 바뀌면 「변경」만 표시, 다시 발행하면 다음 판 |
| 외부 자료 가져오기 | 시스템 밖 PPT·HTML·PDF·엑셀·메모를(DRM 엑셀·메일함은 결정 ③으로 1차에서 끔 — `MEETING_COM_IMPORTS=on` 이면 켬) 조각으로 나눠 이슈에 붙이거나 새 이슈로 반영. 원본은 보관, 메일 발신자는 저장하지 않음 |
| 부서 현안 공유회 · 팀장 정보회의 | 주간 정기 회의 2종. 부서장들이 부서 이슈 공유 / 팀장이 본부장에게 보고 |
| 사례 카드 | 종결 승인된 이슈·문제점에서 만들어지는 지식 단위 (증상·원인·조치) |
| 기준정보 | 호선, 선종, 선주, 자매선 그룹, 시스템, 장비 모델, 탑재 장비, 부위, 시운전 항목, 증상·원인 코드, 부서 |
| 별칭 사전 | 현장 표기("DG2")를 기준정보 ID로 바꾸는 표 |
