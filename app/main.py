"""meeting FastAPI 앱 — 화면 4개(작성/회의/지식창고/장비 허브) + /healthz.

실행:  uv run uvicorn app.main:app --port 8600 --reload   (운영은 run.bat)
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from contextlib import asynccontextmanager
from urllib.parse import quote, urlencode

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app import settings
from app.db import get_session, init_db
from app.models import Block, CaseCard, Department, Hull, InstalledEquipment, ShipType
from app.routers import masters as masters_router
from app.routers import export as export_router
from app.routers import issues as issues_router
from app.routers import importer as importer_router
from app.routers import metrics as metrics_router
from app.routers import run as run_router
from app.routers import studio as studio_router
from app.routers import photos as photos_router
from app.routers import write as write_router
from app.services import alerts as alerts_svc
from app.services import alias as alias_svc
from app.services import masters as masters_svc
from app.services import answer as answer_svc
from app.services import carry_over as co_svc
from app.services import knowledge as knowledge_svc
from app.services import central
from app.services import settings_svc
from app.services import weeks
from app.services import issues as issues_svc
from app.services import photos as photos_svc
from app.services import studio as studio_svc
from app.services import writing as write_svc

APP_DIR = settings.ROOT / "app"
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
# 정적 파일 주소에 버전(가장 최근 수정 시각)을 붙여, 배포 뒤 브라우저가 옛 CSS·JS 를 쓰지 않게 한다
templates.env.globals["hull_brief"] = central.hull_brief   # 마일스톤 칩(_ms.html)
templates.env.globals["asset_v"] = int(max((p.stat().st_mtime for p in (APP_DIR / "static").rglob("*") if p.is_file()),
                                           default=0))

# 머리글 탭 — (키, 라벨, 기본 경로)
TABS = (
    ("home", "홈", "/home"),                 # M9(2026-10-23) 이번 주 할 일
    ("issue", "이슈", "/issues"),            # M9 이슈 원장 작업대
    ("studio", "회의", "/meetings"),          # M10 회의 · 스튜디오 → M11(2026-10-23) 공식
    ("import", "가져오기", "/import"),        # M13 메모·PPT·HTML·메일함 → 이슈(옛 작성 화면을 대신한다)
    ("metrics", "지표", "/metrics"),          # M13 대시보드 지표 입력(옛 작성 화면에서 옮김)
    ("knowledge", "지식창고", "/knowledge"),
    ("hub", "장비 허브", "/hub"),
    ("settings", "설정", "/settings"),
)
FALLBACK_DEPT = "D1"   # 부서 기준정보가 아직 없을 때(M1 시드 전) 작성 화면 기본 부서


def _sync_hulls_on_start() -> None:
    """서버 시작 때 pjtlist → 호선 동기화(읽기 전용). 실패해도 앱은 뜬다."""
    from app.db import SessionLocal
    try:
        with SessionLocal() as s:
            rep = central.sync_hulls(s)
            s.commit()
        central.LAST_SYNC.update(at=datetime.now(), report=rep)
        msg = (f"새로 {len(rep.created)} · 갱신 {len(rep.updated)} · pjtlist 에 없는 호선 {len(rep.not_in_pjtlist)}"
               if rep.ok else rep.reason)
        print(f"[meeting] 호선 동기화(pjtlist): {msg}", flush=True)
    except Exception as e:  # noqa: BLE001 — 중앙 parquet 문제로 앱이 안 뜨면 안 된다
        print(f"[meeting] 호선 동기화 건너뜀: {type(e).__name__}", flush=True)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    import path_config as pc
    d, source = pc.data_dir_choice()
    print(f"[meeting] 데이터 폴더: {d}  ({source})", flush=True)   # 어느 DB·사진 폴더를 쓰는지 서버 창에서 바로 확인
    init_db()
    _sync_hulls_on_start()
    yield


app = FastAPI(title=settings.APP_TITLE, lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")


@app.middleware("http")
async def _revalidate_code(request: Request, call_next):
    """JS·CSS 는 매번 바뀌었는지 묻게 한다(ETag 로 304). 모듈이 서로를 ?v 없이 import 해서(slides.js 등) 업데이트 뒤 옛 파일이 남는 것을 막는다."""
    resp = await call_next(request)
    if request.url.path.startswith(("/static/js/", "/static/css/")):
        resp.headers["Cache-Control"] = "no-cache"
    return resp
app.include_router(masters_router.router)
app.include_router(write_router.router)
app.include_router(photos_router.router)
app.include_router(export_router.router)
app.include_router(issues_router.router)
app.include_router(studio_router.router)
app.include_router(run_router.router)
app.include_router(importer_router.router)
app.include_router(metrics_router.router)


def _week_or_404(week_id: str) -> weeks.IsoWeek:
    w = weeks.parse(week_id)
    if w is None:
        raise HTTPException(404, f"주차 형식이 맞지 않습니다: {week_id}. 2026-W42 처럼 입력해주세요.")
    return w


def _page(request: Request, tpl: str, tab: str, week: weeks.IsoWeek | None = None, **ctx) -> HTMLResponse:
    w = week or weeks.current()
    return templates.TemplateResponse(request, tpl, {
        "tabs": TABS, "active": tab, "week": w, "env_label": settings.ENV_LABEL,
        "app_title": settings.APP_TITLE, **ctx,
    })


@app.get("/healthz")
def healthz(s: Session = Depends(get_session)) -> dict:
    s.execute(text("SELECT 1"))
    return {"ok": True, "env": settings.ENV_LABEL, "week": weeks.current().id}


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse("/home", status_code=307)


@app.get("/home", response_class=HTMLResponse)
def home_page(request: Request, role: str = "w", dept: str = "", s: Session = Depends(get_session)):
    """홈 — 역할별 이번 주 할 일(로그인 없음: 역할·부서는 고른다). 한 줄은 여기서 Enter 로 저장하고 다음 칸."""
    role = role if role in ("w", "d", "p") else "w"
    depts = list(s.scalars(select(Department).order_by(Department.order_no)))
    dept = dept or (depts[0].id if depts else FALLBACK_DEPT)
    wk = weeks.current()
    studio_svc.ensure_week_meetings(s, wk.id)      # 부서 편집자의 부서 자료·기획의 공유회 연결용
    s.commit()
    return _page(request, "home.html", "home", role=role, dept=dept, depts=depts,
                 tasks=issues_svc.home_tasks(s, role, dept, wk.id), statuses=_dept_submissions(s, wk.id))


def _dept_submissions(s: Session, week_id: str) -> list[dict]:
    """이번 주 부서 회의자료 제출 현황(M12 — 옛 섹션 확정 대신)."""
    out = []
    for mt in studio_svc.week_meetings(s, week_id):
        if mt.kind != "dept":
            continue
        d = s.get(Department, mt.owner_dept_id)
        done = mt.status in ("제출", "수정됨") and mt.version > 0
        state = f"제출 {mt.version}판" + (" · 뒤에 수정" if mt.status == "수정됨" else "") if done else ("구성 중" if mt.start_mode or mt.version else "시작 전")
        out.append({"id": mt.owner_dept_id, "name": d.name if d else mt.owner_dept_id, "state": state, "done": done})
    return out


@app.get("/issues", response_class=HTMLResponse)
def issues_page(request: Request, id: str = "", dept: str = "", f: str = "", q: str = "", s: Session = Depends(get_session)):
    """이슈 원장 작업대 — 왼쪽 원장 · 가운데 이슈 하나(칸 자동 저장) · 1차 초안 미리보기."""
    wk = weeks.current()
    cur = s.get(Block, id) if id else None
    depts = list(s.scalars(select(Department).order_by(Department.order_no)))
    if dept == "" and cur is not None:
        dept = cur.owner_department_id
    dept = dept if dept in {d.id for d in depts} | {"all"} else (depts[0].id if depts else FALLBACK_DEPT)
    dkey = "" if dept == "all" else dept
    rows = issues_svc.ledger(s, wk.id, dkey, f, q)
    if cur is None and rows:
        cur = rows[0].b
    view = None
    if cur is not None:
        r = issues_svc._row(s, cur, wk.id)
        view = {"r": r, "maps": issues_svc.map_cells(s, cur), "history": co_svc.history(s, cur.id)[-6:],
                "human": write_svc.human_fields(s, cur.id), "section": write_svc.block_section(s, cur.id),
                "dept_name": next((d.name for d in depts if d.id == cur.owner_department_id), cur.owner_department_id),
                "attach": write_router.attach_view(s, cur), "records": _meeting_records(s, cur.id),
                "due_options": alerts_svc.options(), "due_suggest": alerts_svc.suggest(s, cur) if not cur.due_event else "",
                "similar": knowledge_svc.similar_cases(s, cur.id) if cur.block_type in write_svc.TRACKED and cur.status != "종결" else None}
    q_ = request.query_params
    studio_svc.ensure_week_meetings(s, wk.id)
    s.commit()
    adopt_to = [x for x in studio_svc.week_meetings(s, wk.id) if x.kind in studio_svc.EDITABLE]
    return _page(request, "issues.html", "issue", rows=rows, cur=cur, view=view, dept=dept, depts=depts, chip=f, q=q, adopt_to=adopt_to,
                 chips=[(k, l, n) for (k, l), n in zip(issues_svc.CHIPS, issues_svc.chip_counts(s, wk.id, dkey).values())],
                 draft_label=issues_svc.DRAFT_LABEL, type_label=write_svc.TYPE_LABEL, photo_roles=photos_svc.ROLES, photo_sel=q_.get("photo", ""),
                 msg=q_.get("msg", ""), err=q_.get("err", ""), all_done=q_.get("done") == "1")


def _meeting_records(s: Session, block_id: str) -> list[dict]:
    """이슈에 쌓인 회의 기록(M12) — 코멘트·결정·지시. 주간 한 줄과 섞지 않고 따로 보인다."""
    from app import models as _m
    out = []
    for c, mt in s.execute(select(_m.MeetingComment, _m.Meeting).join(_m.Meeting, _m.Meeting.id == _m.MeetingComment.meeting_id)
                           .where(_m.MeetingComment.block_id == block_id).order_by(_m.MeetingComment.id)):
        out.append({"week": mt.week_id, "label": f"{mt.title or '회의'} {'결정' if c.kind == 'decision' else '코멘트'}", "text": c.text})
    for d, mt in s.execute(select(_m.Directive, _m.Meeting).join(_m.Meeting, _m.Meeting.id == _m.Directive.meeting_id)
                           .where(_m.Directive.block_id == block_id).order_by(_m.Directive.id)):
        out.append({"week": mt.week_id, "label": f"{mt.title or '회의'} 지시({d.status})", "text": d.text + (f" — {d.done_note}" if d.done_note else "")})
    from app.services import importer as _im
    out += _im.records_for(s, block_id)
    return sorted(out, key=lambda x: x["week"])[-8:]


@app.get("/meetings", response_class=HTMLResponse)
def meetings_page(request: Request, s: Session = Depends(get_session)):
    """회의 목록 — 이번 주 정기 회의는 처음 볼 때 만든다. 카드는 그 회의의 다음 할 일로(구성 중 → 스튜디오, 제출·발행 → 보기)."""
    wk = weeks.current()
    studio_svc.ensure_week_meetings(s, wk.id)
    s.commit()
    mts = studio_svc.week_meetings(s, wk.id)
    counts = {mt.id: sum(len(sec["items"]) for sec in studio_svc.deck(s, mt)["sections"]) for mt in mts}
    hulls = sorted({h for h in s.scalars(select(Hull.id))})
    return _page(request, "meetings.html", "studio", meetings=mts, past=studio_svc.past_meetings(s, wk.id), counts=counts,
                 kinds=studio_svc.KINDS, hulls=hulls,
                 depts={d.id: d.name for d in s.scalars(select(Department))}, err=request.query_params.get("err", ""))


def _meeting_or_404(s: Session, mid: int):
    from app import models as _m
    mt = s.get(_m.Meeting, mid)
    if mt is None:
        raise HTTPException(404, "없는 회의입니다. 회의 목록에서 다시 골라주세요.")
    return mt


def _script_json(v) -> str:
    import json as _json
    return _json.dumps(v, ensure_ascii=False, default=str).replace("</", "<\\/")   # <script> 안 — 글에 </script> 가 있어도 깨지지 않게


@app.get("/meetings/{mid}", response_class=HTMLResponse)
def meeting_view_page(request: Request, mid: int, s: Session = Depends(get_session)):
    """회의자료 보기(M11) — 제출·발행판이 있으면 그 판, 없으면 지금 구성. 쪽을 세로로 읽는다."""
    mt = _meeting_or_404(s, mid)
    if studio_svc.sync_share(s, mt):
        s.commit()
    v = studio_svc.view(s, mt)
    return _page(request, "meeting_view.html", "studio", mt=mt, v=v, view_json=_script_json(v))


@app.get("/meetings/{mid}/run", response_class=HTMLResponse)
def run_page(request: Request, mid: int, view: str = "", s: Session = Depends(get_session)):
    """회의 진행(M12) — 진행자 화면 / ?view=present 발표 화면(진행자 쪽을 따라감). 발행 전이면 보기로 돌려보낸다."""
    from app.services import run as run_svc
    mt = _meeting_or_404(s, mid)
    if studio_svc.latest_version(s, mt) is None:
        from urllib.parse import quote
        return RedirectResponse(f"/meetings/{mt.id}?err=" + quote("아직 발행하지 않은 회의입니다. 스튜디오에서 발행한 뒤 회의를 시작해주세요."), status_code=303)
    if view != "present":
        run_svc.start(s, mt)
        s.commit()
    return _page(request, "run.html", "studio", mt=mt, present=view == "present", run_json=_script_json(run_svc.state(s, mt)))


@app.get("/studio/{mid}", response_class=HTMLResponse)
def studio_page(request: Request, mid: int, s: Session = Depends(get_session)):
    """회의자료 스튜디오 — 왼쪽 장/후보 · 가운데 캔버스 · 오른쪽 속성. 상태는 JSON 으로 받아 그린다."""
    mt = _meeting_or_404(s, mid)
    if mt.kind not in studio_svc.EDITABLE:
        return RedirectResponse(f"/meetings/{mt.id}", status_code=303)
    if studio_svc.sync_share(s, mt):
        s.commit()
    return _page(request, "studio.html", "studio", mt=mt, state_json=_script_json(studio_svc.state(s, mt)))


@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request, s: Session = Depends(get_session)):
    """가져오기(M13) — 메모 붙여넣기 · PPT·HTML 올리기 · 메일함 → 조각 판정 → 반영하기."""
    return importer_router.render_import(request, s, _page)


@app.get("/metrics")
def metrics_default(s: Session = Depends(get_session)) -> RedirectResponse:
    first = s.scalar(select(Department.id).order_by(Department.order_no).limit(1))
    return RedirectResponse(f"/metrics/{first or FALLBACK_DEPT}", status_code=307)


@app.get("/metrics/{dept_id}", response_class=HTMLResponse)
def metrics_page(request: Request, dept_id: str, s: Session = Depends(get_session)):
    return metrics_router.render_metrics(request, s, dept_id, _page)


@app.get("/write")
@app.get("/write/{week_id}/{dept_id}")
def legacy_write(request: Request, week_id: str = "", dept_id: str = "") -> RedirectResponse:
    """옛 작성 화면 주소(M13 에서 없앰) — 메모는 가져오기, 이슈는 이슈 원장, 대시보드는 지표로."""
    q = request.query_params
    if q.get("block", "").startswith("DSH-") and dept_id:
        return RedirectResponse(f"/metrics/{dept_id}?week={week_id}", status_code=307)
    if q.get("block"):
        return RedirectResponse(f"/issues?id={q['block']}", status_code=307)
    if q.get("memo") and q["memo"] != "new":
        return RedirectResponse(f"/import?memo={q['memo']}", status_code=307)
    return RedirectResponse("/import?entry=memo" + (f"&dept={dept_id}" if dept_id else ""), status_code=307)


@app.get("/photos/{photo_id}/edit", response_class=HTMLResponse)
def photo_edit_page(request: Request, photo_id: str, block: str, s: Session = Depends(get_session)):
    return photos_router.render_editor(request, s, photo_id, block, _page)


@app.get("/meeting")
@app.get("/meeting/{week_id}")
@app.get("/meeting/{week_id}/present")
def legacy_meeting(request: Request, week_id: str = "", s: Session = Depends(get_session)) -> RedirectResponse:
    """옛 「회의 · 팀 보고서」·발표 주소(M12 에서 없앰) — 그 주 공유회 보기 / 진행으로 보낸다(즐겨찾기 보호)."""
    wk = weeks.parse(week_id) if week_id else weeks.current()
    if wk is None:
        raise HTTPException(404, f"주차 형식이 맞지 않습니다: {week_id}. 2026-W42 처럼 입력해주세요.")
    studio_svc.ensure_week_meetings(s, wk.id)
    s.commit()
    sh = studio_svc.week_meeting(s, wk.id, "share")
    tail = "/run" if request.url.path.endswith("/present") and studio_svc.latest_version(s, sh) else ""
    return RedirectResponse(f"/meetings/{sh.id}{tail}", status_code=307)


@app.get("/knowledge", response_class=HTMLResponse)
def knowledge_page(request: Request, q: str = "", kind: str = "all", period: str = "all", case: str = "",
                   hull: str = "", system: str = "", ship_type: str = "", dept: str = "", ask: str = "", s: Session = Depends(get_session)):
    """지식창고 — 「찾기」는 검색만, 「질문하기」(ask=1)만 AI 가 근거 사례를 인용해 답한다(M13, F15 — 찾을 때마다 LLM 을 부르지 않게)."""
    kind = kind if kind in knowledge_svc.KINDS else "all"
    period = period if period in knowledge_svc.PERIODS else "all"
    filters = {"hull": hull, "system": system, "ship_type": ship_type, "dept": dept}
    res = knowledge_svc.search(s, q, kind, filters, period, weeks.current().id)
    ans = answer_svc.ask(s, q, res.cases) if q.strip() and ask else None
    s.commit()                                         # 답변 호출 로그
    params = {"q": q, "kind": kind, "period": period, "case": case, **filters}

    def qs(**changes) -> str:
        cur = {**params, **changes}
        return "?" + urlencode({k: v for k, v in cur.items() if v and not (k in ("kind", "period") and v == "all")})

    sel = s.get(CaseCard, case) if case else None
    detail = None
    if sel:
        detail = {**knowledge_svc.case_view(s, sel), "history": co_svc.history(s, sel.block_id),
                  "similar": knowledge_svc.similar_cases(s, sel.block_id, 4)}
    return _page(request, "knowledge.html", "knowledge", res=res, ans=ans, params=params, qs=qs, filters=filters,
                 kinds=knowledge_svc.KINDS, periods=knowledge_svc.PERIODS, facet_keys=knowledge_svc.FACET_KEYS,
                 detail=detail, case_views={d.key: knowledge_svc.case_view(s, d.obj) for d in res.results if d.kind == "case"})


def _resolve_view(s: Session, q: str) -> dict | None:
    """「현장 표기로 찾기」 결과 줄 — 화면 표시용 값만."""
    if not q:
        return None
    r = alias_svc.resolve(s, q)
    eq = s.get(InstalledEquipment, r.target_id) if r.target_kind == "installed_equipment" else None
    return {"r": r, "eq": eq}


@app.get("/hub", response_class=HTMLResponse)
def hub_page(request: Request, q: str = "", s: Session = Depends(get_session)):
    q = q.strip()
    res = _resolve_view(s, q)
    if res and res["eq"] is not None:          # 찾았으면 그 장비 화면으로 (표기는 그대로 넘겨 다시 보여준다)
        return RedirectResponse(f"/hub/equipment/{res['eq'].id}?q={quote(q)}", status_code=303)
    return _page(request, "hub.html", "hub", q=q, res=res, card=None,
                 has_masters=s.scalar(select(InstalledEquipment.id).limit(1)) is not None,
                 unreg=masters_svc.unregistered(s), msg=request.query_params.get("msg", ""))


@app.post("/hub/relink")
def hub_relink(s: Session = Depends(get_session)):
    """미등록 표기를 기준정보·별칭으로 다시 이어 보기 (기준정보 CSV 를 고치고 시드를 돌린 뒤)."""
    n = masters_svc.relink_unregistered(s)
    s.commit()
    msg = f"미등록 표기 {n}건을 기준정보에 이었습니다" if n else "새로 이어진 표기가 없습니다 — 기준정보 CSV 에 먼저 넣어주세요"
    return RedirectResponse(f"/hub?msg={quote(msg)}#unreg", status_code=303)


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, s: Session = Depends(get_session)):
    """설정 — 부서 이름·순서, 호선(pjtlist)·마일스톤 연계 상태."""
    return _settings(request, s, msg=request.query_params.get("msg", ""))


def _settings(request: Request, s: Session, **over) -> HTMLResponse:
    last = central.LAST_SYNC
    from app.services import alerts as _al
    ctx = dict(depts=settings_svc.departments(s), usage=settings_svc.usage(s), errs=[], msg="", alert_defaults=_al.defaults(s),
               range_weeks=metrics_range(s),
               central=central.status(), last=last,
               not_in=last["report"].not_in_pjtlist if last.get("report") else [],
               hull_n=s.scalar(select(func.count()).select_from(Hull)) or 0,
               hull_pj=s.scalar(select(func.count()).select_from(Hull).where(Hull.source == "pjtlist")) or 0)
    ctx.update(over)
    return _page(request, "settings.html", "settings", **ctx)


@app.post("/settings/alerts")
async def settings_alerts(request: Request, s: Session = Depends(get_session)):
    """F21 이벤트별 기본 경보 일수(D-n). 이슈마다 따로 고친 값이 먼저다."""
    from app.services import alerts as _al
    try:
        n = _al.set_defaults(s, await request.form())
        s.commit()
    except write_svc.WriteError as e:
        s.rollback()
        return RedirectResponse(f"/settings?msg={quote(str(e))}#alerts", status_code=303)
    return RedirectResponse(f"/settings?msg={quote(f'경보 일수 {n}개를 바꿨습니다' if n else '바뀐 값이 없습니다')}#alerts", status_code=303)


def metrics_range(s: Session) -> int:
    from app.services import metrics as _mt
    return _mt.range_weeks(s)


@app.post("/settings/metrics")
async def settings_metrics(request: Request, s: Session = Depends(get_session)):
    """F16 지표 평소 범위 — 정의한 범위가 없는 지표를 최근 n주 값으로 판단한다."""
    from app.services import metrics as _mt
    try:
        changed = _mt.set_range_weeks(s, (await request.form()).get("range_weeks"))
        s.commit()
    except write_svc.WriteError as e:
        s.rollback()
        return RedirectResponse(f"/settings?msg={quote(str(e))}#metric-range", status_code=303)
    return RedirectResponse(f"/settings?msg={quote('평소 범위 기간을 바꿨습니다' if changed else '바뀐 값이 없습니다')}#metric-range", status_code=303)


@app.post("/settings/departments", response_class=HTMLResponse)
async def settings_departments(request: Request, s: Session = Depends(get_session)):
    f = await request.form()
    ids, names, codes, orders = (f.getlist(k) for k in ("id", "name", "code", "order_no"))
    rows = []
    for i in range(len(names)):
        try:
            order = int(str(orders[i]).strip() or 0)
        except ValueError:
            order = (i + 1) * 10       # 숫자가 아니면 줄 순서대로
        rows.append(settings_svc.DeptRow(str(ids[i]) if i < len(ids) else "", str(names[i]),
                                         str(codes[i]) if i < len(codes) else "", order))
    errs = settings_svc.update_departments(s, rows)
    if errs:
        s.rollback()
        return _settings(request, s, errs=errs, posted=rows)
    s.commit()
    return RedirectResponse(f"/settings?msg={quote('부서를 저장했습니다 — 작성·회의 화면에 바로 반영됩니다')}", status_code=303)


@app.post("/settings/sync")
def settings_sync(s: Session = Depends(get_session)):
    """pjtlist·milestone 을 지금 다시 읽어 호선 기준정보를 맞춘다(중앙 parquet 은 읽기만)."""
    rep_ = central.sync_hulls(s)
    s.commit()
    central.LAST_SYNC.update(at=datetime.now(), report=rep_)
    if rep_.ok:
        msg = f"호선 동기화 — 새로 {len(rep_.created)} · 갱신 {len(rep_.updated)}"
        if rep_.relinked:
            msg += f" · 미등록 표기 {rep_.relinked}건 연결"
    else:
        msg = f"동기화하지 못했습니다 — {rep_.reason}"
    return RedirectResponse(f"/settings?msg={quote(msg)}#hulls", status_code=303)


@app.get("/hub/equipment/{eq_id}", response_class=HTMLResponse)
def hub_equipment_page(request: Request, eq_id: str, q: str = "", s: Session = Depends(get_session)):
    card = masters_svc.equipment_card(s, eq_id)
    if card is None:
        raise HTTPException(404, f"탑재 장비 {eq_id} 가 기준정보에 없습니다. 장비 허브에서 현장 표기로 다시 찾아주세요.")
    q = q.strip()
    eq = s.get(InstalledEquipment, eq_id)
    hull = s.get(Hull, eq.hull_id)
    st = s.get(ShipType, hull.ship_type_id) if hull and hull.ship_type_id else None
    hub = {"open": knowledge_svc.open_issues(s, eq_id), "history": knowledge_svc.equipment_history(s, eq_id),
           "same": knowledge_svc.same_model(s, eq_id), "precedents": knowledge_svc.sister_precedents(s, eq_id),
           "causes": knowledge_svc.cause_ranking(s, eq.equipment_model_id),
           "photos": knowledge_svc.component_photos(s, eq.equipment_model_id), "ship_code": st.code if st else ""}
    return _page(request, "hub.html", "hub", q=q, res=_resolve_view(s, q), card=card, hub=hub, has_masters=True)
