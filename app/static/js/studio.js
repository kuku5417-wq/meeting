// 회의자료 스튜디오(M10 → M11 공식) — 서버 상태(JSON)를 받아 장 목록·캔버스(장 프레임 + 다른 형태 변형)·속성을 그린다.
// 바꾸는 동작은 모두 /api/studio/… 로 보내고, 돌아온 상태로 다시 그린다. 사실(원인·조치·결정 필요)은 /api/issues/{id}/field.
// 공유회는 부서 칸마다 부서 자료 제출판을 참조로 보여 준다 — 그 장은 읽기 전용(사실만 고칠 수 있다), 부서 순서·원장으로 채우기만 여기서.
import {esc, KIND, slide as draw, cover, divider, directivesSlide, fit, pageTitle, isData} from './slides.js';

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
let S = JSON.parse($('#stState').textContent);
let sel = 0, zoom = 1;
const multi = new Set();
const mid = S.meeting.id;
const share = () => S.meeting.kind === 'share';
const ctx = () => ({title: S.meeting.title, forms: S.forms});

// ── 서버 호출 ────────────────────────────────────────
async function api(url, body) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  const j = await r.json();
  if (!j.ok) { toast(j.err); return null; }
  if (j.state) { S = j.state; }
  return j;
}
let tt;
function toast(msg, undo) {
  const t = $('#toast');
  t.innerHTML = `<span>${esc(msg)}</span>` + (undo ? '<button type="button">되돌리기</button>' : '');
  t.hidden = false;
  if (undo) t.querySelector('button').onclick = () => { t.hidden = true; undo(); };
  clearTimeout(tt); tt = setTimeout(() => { t.hidden = true; }, 6000);
}

// 쪽 번호 — 표지 1, (지난 지시사항), 공유회는 부서 구분 장도 센다
const dirs = () => S.directives || [];
function pages() {
  let n = dirs().length ? 2 : 1; const at = [], div = [];
  S.items.forEach((it, i) => { if (share() && (i === 0 || S.items[i - 1].sec !== it.sec)) div[it.sec] = ++n; at[i] = ++n; });
  if (share()) S.sections.forEach((sec, k) => { if (div[k] == null) div[k] = ++n; });
  return {at, div, total: n};
}
const W = () => Math.round(520 * zoom);
const frame = (html, label, cls, attrs, w) => `<div class="st-frame ${cls}" ${attrs} style="width:${w || W()}px"><span class="lbl">${label}</span><div class="v-stage-wrap"><div class="v-stage">${html}</div></div></div>`;
addEventListener('resize', () => fit());

function renderCanvas() {
  const c = $('#canvas');
  if (!S.meeting.started) {
    c.innerHTML = `<div class="st-start"><b>이번 주 자료를 어떻게 시작할까요?</b><div class="row"><button class="btn primary" type="button" data-start="carry">지난주 이어받기</button><button class="btn" type="button" data-start="blank">빈 자료에서</button></div><span class="small muted">지난주 자료의 열린 이슈 + 새로 초안을 마친 이슈가 들어갑니다. 지난번 고른 방식: ${S.meeting.suggest === 'blank' ? '빈 자료' : '지난주 이어받기'}</span></div>`;
    return;
  }
  const P = pages();
  let h = `<div class="st-row">${frame(cover(S.meeting, S.cover, P.total, S.long_weeks), '<b>1 · 표지</b>', 'static', '')}</div>`;
  if (dirs().length) h += `<div class="st-row">${frame(directivesSlide(dirs(), 2, P.total, S.meeting.title), `<b>2 · 지난 지시사항</b><span>${dirs().length}건</span>`, 'static', '')}</div>`;
  const secRow = (k) => { const sec = S.sections[k]; return `<div class="st-row">${frame(divider(sec, P.div[k], P.total, S.meeting.title), `<b>${P.div[k]} · ${esc(sec.dept)}</b><span>${esc(sec.state)}</span>`, 'static', '', Math.round(W() * 0.6))}</div>`; };
  let lastSec = -1;
  S.items.forEach((it, i) => {
    if (share() && it.sec !== lastSec) { for (let k = lastSec + 1; k <= it.sec; k++) h += secRow(k); lastSec = it.sec; }
    const on = i === sel, n = P.at[i];
    h += `<div class="st-row" data-row="${i}">${frame(draw(it, n, P.total, null, ctx()), `<b>${n} · ${esc(pageTitle(it).slice(0, 26))}</b><span>${it.ro ? '부서 제출판' : it.kind === 'metric' ? '지표' : it.kind === 'table' ? '기간 표' : esc(S.forms[it.form])}</span>`, on ? 'on' : multi.has(i) ? 'multi' : '', `data-f="${i}"`)}`;
    if (on && !it.ro && multi.size < 2 && it.kind !== 'summary' && !isData(it)) h += '<span class="st-vh">다른 형태</span>' + Object.keys(S.forms).filter((k) => k !== it.form).map((k) => frame(draw(it, n, P.total, k, ctx()), `<b>${esc(S.forms[k])}</b> 로 바꾸기`, 'var', `data-var="${k}"`, Math.round(W() * 0.55))).join('');
    h += '</div>';
  });
  if (share()) for (let k = lastSec + 1; k < S.sections.length; k++) h += secRow(k);
  if (!S.items.length) h += `<div class="st-start"><b>장이 없습니다</b><span class="small muted">${share() ? '부서가 제출하면 여기 모입니다. 미제출 부서는 왼쪽에서 「원장으로 채우기」.' : '왼쪽 「후보」에서 ＋ 를 누르면 장이 생깁니다.'}</span></div>`;
  c.innerHTML = h; fit(c);
}

function layerRow(it, i, n) {
  const b = it.blocks[0] || {};
  return `<div class="v-row st-lyr ${i === sel ? 'on' : multi.has(i) ? 'multi' : ''}" data-l="${i}" draggable="${!share()}"><span class="n">${n}</span><span class="t">${it.kind === 'summary' ? '<span class="v-tl dashboard">요약</span> ' + esc(it.line) : it.kind === 'metric' ? '<span class="v-tl dashboard">지표</span> 지표 요약' : it.kind === 'table' ? `<span class="v-tl dashboard">표</span> ${esc(it.table?.name || it.line)}` : `<span class="v-tl ${b.type}">${KIND[b.type] || ''}</span> ${esc(b.title)}`}</span><span class="f">${isData(it) ? '' : esc(S.forms[it.form])}</span>${it.src ? `<span class="src">${esc(it.src)}</span>` : ''}</div>`;
}
function renderLeft() {
  const P = pages();
  let h = '<div class="v-row st-lyr"><span class="n">1</span><span class="t">표지</span><span></span></div>';
  if (dirs().length) {
    const mine = S.meeting.kind === 'dept';
    h += `<div class="st-sec"><span class="t"><b>지난 지시사항</b> <span class="small muted">${dirs().filter((d) => d.status === '완료').length}/${dirs().length} 완료</span></span></div>`
      + dirs().map((d) => `<div class="st-dir${d.late ? ' late' : ''}"><span class="small"><b>${esc(d.text)}</b> · ${esc(d.dept)} · 기한 ${esc(d.due.slice(-3))}${d.late ? ' · <span class="v-late">기한 지남</span>' : ''}</span>`
        + (d.status === '완료' ? `<span class="small ok-text">완료 — ${esc(d.done_note)}</span>${mine ? `<button class="btn sm" type="button" data-dv-reopen="${d.id}">다시 열기</button>` : ''}`
          : mine ? `<span class="row"><label class="sr" for="dv-${d.id}">완료 보고</label><input type="text" id="dv-${d.id}" placeholder="완료 보고 한 줄"><button class="btn sm" type="button" data-dv-done="${d.id}">완료</button></span>` : '<span class="small muted">진행 중 — 담당 부서가 완료 보고</span>')
        + '</div>').join('');
  }
  if (share()) {
    S.sections.forEach((sec, k) => {
      const late = sec.state.startsWith('미제출');
      h += `<div class="st-sec"><span class="t"><b>${esc(sec.dept)}</b> <span class="small ${late ? 'v-late' : 'muted'}">${esc(sec.state)}</span></span>
        <span class="row">${late ? `<button class="btn sm" type="button" data-fill="${esc(sec.dept_id)}">원장으로 채우기</button>` : ''}${sec.ref ? `<a class="btn sm" href="/studio/${sec.ref}">부서 자료</a>` : ''}<button class="btn sm" type="button" data-mv="${esc(sec.dept_id)}" data-step="-1" aria-label="${esc(sec.dept)} 위로">▲</button><button class="btn sm" type="button" data-mv="${esc(sec.dept_id)}" data-step="1" aria-label="${esc(sec.dept)} 아래로">▼</button></span></div>`;
      S.items.forEach((it, i) => { if (it.sec === k) h += layerRow(it, i, P.at[i]); });
    });
  } else S.items.forEach((it, i) => { h += layerRow(it, i, P.at[i]); });
  if (S.meeting.kind === 'dept' && S.meeting.editable && !S.items.some((x) => x.kind === 'metric')) h += '<button class="btn sm" type="button" id="addMetric">＋ 지표 요약 장</button>';
  if (S.meeting.kind === 'dept' && S.meeting.editable && S.ptables?.length) h += `<div class="row"><select id="ptSel" aria-label="장으로 넣을 기간 표">${S.ptables.map((t) => `<option value="${t.id}">${esc(t.name)} · ${esc(t.period)}</option>`).join('')}</select><button class="btn sm" type="button" id="addTable">＋ 기간 표 장</button></div>`;
  $('#layers').innerHTML = h;
  $('#cands').innerHTML = S.candidates.map((g) => g.blocks.length ? `<p class="v-sec">${esc(g.group)} ${g.blocks.length}</p><div class="v-list">` + g.blocks.map((b) => `<div class="v-row st-cand"><span class="t"><span class="v-tl ${b.type}">${KIND[b.type] || ''}</span> ${esc(b.title)}</span><button class="btn sm" type="button" data-add="${b.id}" aria-label="${b.id} 장으로 넣기">＋</button><span class="m">${esc(b.id)} · ${esc(b.dept)}${b.draft !== 'ok' ? ' · 초안 미완료' : ''}</span></div>`).join('') + '</div>' : '').join('') || '<p class="muted small">넣을 후보가 없습니다</p>';
  $('#nL').textContent = P.total;
  $('#nC').textContent = S.candidates.reduce((a, g) => a + g.blocks.length, 0);
  $('#lyrHint').textContent = share() ? '부서 칸은 ▲▼ 로 순서 · 장은 부서 자료에서 고칩니다' : '끌어서 순서 · Shift+클릭으로 여러 장';
}

const MINI = {detail: '<i></i><i class="s"></i><i class="b"></i><i class="b"></i>', card: '<i></i><i class="s"></i><i class="b" style="width:40%;justify-self:end;height:22px"></i>', photo: '<i></i><i class="b" style="height:30px;width:60%"></i>', line: '<i style="margin-top:12px"></i><i class="s"></i>'};
const KEYS = '<p class="st-keys"><kbd>↑</kbd><kbd>↓</kbd> 장 고르기 · <kbd>1</kbd>~<kbd>4</kbd> 형태 · <kbd>Delete</kbd> 빼기</p>';
function facts(b) {
  if (S.meeting.kind === 'exec') return '';
  return `<p class="v-sec">● 사실 — 여기서 고치면 이슈에 반영 · 변경 기록에 남음</p><div class="st-fact"><label class="f">원인<input type="text" data-fact="cause_text" data-id="${esc(b.id)}" value="${esc(b.cause)}" placeholder="조사 중"></label><label class="f">조치 · 계획<input type="text" data-fact="action_text" data-id="${esc(b.id)}" value="${esc(b.act)}"></label><label class="f">결정 필요<input type="text" data-fact="decision_needed" data-id="${esc(b.id)}" value="${esc(b.dec)}"></label></div>`;
}
function renderProps() {
  const p = $('#props'), P = pages();
  if (multi.size >= 2) { p.innerHTML = `<b>${multi.size}장 골랐습니다</b><span class="small muted">같은 원인·장비라면 한 장으로 묶어 보여 줄 수 있습니다. 각 이슈는 그대로입니다.</span><button class="btn primary" type="button" id="sumBtn">고른 ${multi.size}장 한 장으로 요약</button><button class="btn" type="button" id="clrM">고르기 풀기</button>` + KEYS; return; }
  const it = S.items[sel];
  if (!it) { p.innerHTML = `<p class="muted small">${share() ? '장을 고르면 여기서 사실을 고치거나 그 부서 자료로 갑니다.' : '장을 고르면 여기서 형태·한 줄·사실을 고칩니다.'}</p>` + KEYS; return; }
  const b = it.blocks[0] || {}, n = P.at[sel];
  if (it.kind === 'table') {
    const T = it.table;
    p.innerHTML = `<span class="small muted">${n}장 · 기간 표${it.ro ? ' · 부서 제출판' : ''}</span><b>${esc(T ? T.name : it.line)}</b>
      <p class="small">${T ? `${esc(T.period)} · 그 주 날짜의 계획/실적과 기간 합계·차이 사유를 그립니다. 값·사유는 지표 화면에서 고치고, 제출하면 그때 값이 판에 고정됩니다.` : '이 표는 지워졌습니다 — 장을 빼주세요.'}</p>
      ${T ? `<a class="btn sm primary" href="/metrics/${esc(T.dept_id)}?week=${esc(S.meeting.week)}#tables">지표 화면 →</a>` : ''}${it.ro ? '' : '<div class="row"><button class="btn sm" type="button" id="drop">이 장 빼기</button></div>'}`;
    return;
  }
  if (it.kind === 'metric') {
    const M = it.metric || {};
    p.innerHTML = `<span class="small muted">${n}장 · 지표 요약${it.ro ? ' · 부서 제출판' : ''}</span><b>${esc(M.dept || '')} 지표</b>
      <p class="small">값·코멘트(차이 사유)·기간 표는 지표 화면에서 고칩니다. 제출하면 그때 값이 판에 고정됩니다.</p>
      <a class="btn sm primary" href="/metrics/${esc(M.dept_id || '')}?week=${esc(S.meeting.week)}">지표 화면 →</a>${it.ro ? '' : '<div class="row"><button class="btn sm" type="button" id="drop">이 장 빼기</button></div>'}`;
    return;
  }
  if (it.ro) {
    const sec = S.sections[it.sec] || {};
    p.innerHTML = `<span class="small muted">${n}장 · ${esc(b.id)} · ${esc(sec.dept)} 부서 자료</span><b>${esc(it.kind === 'summary' ? it.line : b.title)}</b>
      <p class="small">이 장은 <b>${esc(sec.dept)}</b> 부서 자료의 제출판에서 왔습니다. 한 줄·형태·순서는 부서 자료에서 고치고 다시 제출하면 여기 반영됩니다.</p>
      <a class="btn sm primary" href="/studio/${it.ref}">부서 자료에서 수정 →</a>${it.kind === 'summary' ? '' : facts(b)}<div class="row"><a class="btn sm" href="/issues?id=${esc(b.id)}">이슈 열기</a></div>`;
    return;
  }
  if (it.kind === 'summary') { p.innerHTML = `<span class="small muted">${n}장 · 요약</span><b>이슈 ${it.blocks.length}건 묶음</b><span class="small">${it.blocks.map((x) => `<a href="/issues?id=${esc(x.id)}">${esc(x.id)}</a>`).join(' ')}</span><p class="v-sec">요약 문장 — 이 자료에만</p><input type="text" id="ln" value="${esc(it.line)}"><div class="row"><button class="btn sm" type="button" id="unsum">요약 풀기</button><button class="btn sm" type="button" id="drop">이 장 빼기</button></div>` + KEYS; return; }
  p.innerHTML = `<span class="small muted">${n}장 · ${esc(b.id)}${it.src ? ' · ' + esc(it.src) : ''}</span><b>${esc(b.title)}</b><span class="small muted">${esc(b.dept)}${b.hull ? ' · ' + esc(b.hull) : ''}${b.draft !== 'ok' ? ' · <span class="v-late">초안 미완료</span>' : ''}</span>
    <p class="v-sec">형태 — 캔버스 옆 변형을 눌러도 됩니다</p><div class="st-vgrid">${Object.entries(S.forms).map(([k, v], i) => `<button type="button" data-form="${k}" aria-pressed="${k === it.form}"><span class="mini">${MINI[k]}</span>${i + 1}. ${esc(v)}</button>`).join('')}</div>
    <p class="v-sec">○ 회의용 한 줄 — 이 자료에만</p>${b.ptag ? `<button class="st-ptag" type="button" id="tag" aria-pressed="${it.tag_on}">[${esc(b.ptag)}]</button>` : ''}<input type="text" id="ln" value="${esc(it.line)}">
    ${facts(b)}<div class="row"><a class="btn sm" href="/issues?id=${esc(b.id)}">이슈 열기</a><button class="btn sm" type="button" id="drop">이 장 빼기</button></div>` + KEYS;
}
function renderBar() {
  const m = S.meeting, P = pages();
  $('#stSub').textContent = ` · ${m.kind_label} · ${m.status}${m.version ? ' · ' + m.version + '판' : ''} · 장 ${P.total}`;
  const btn = $('#submitBtn');
  if (m.publishes) btn.textContent = m.status === '발행' && !m.changes ? `발행함 ✓ ${m.version}판` : m.version ? `다시 발행(${m.version + 1}판)` : '발행';
  else btn.textContent = m.status === '제출' ? '제출함 ✓' : m.status === '수정됨' ? '다시 제출' : '제출';
  const note = $('#stNote');
  note.hidden = !(m.version && (m.status === '수정됨' || m.changes));
  if (note.hidden) { note.innerHTML = ''; return; }
  note.innerHTML = `${m.version}판(${esc(m.published_at)}) 뒤에 ${m.changes ? `이슈 사실이 바뀐 장 <b>${m.changes}</b>` : ''}${m.changes && m.status === '수정됨' ? ' · ' : ''}${m.status === '수정됨' ? '자료를 고쳤습니다' : ''} — 이미 나간 판은 그대로이고, ${m.publishes ? '다시 발행' : '다시 제출'}하면 ${m.version + 1}판이 됩니다.`;
}
function all() { if (sel >= S.items.length) sel = Math.max(0, S.items.length - 1); renderLeft(); renderCanvas(); renderProps(); renderBar(); }
function pick(i, scroll = true) { multi.clear(); sel = Math.max(0, Math.min(S.items.length - 1, i)); all(); if (scroll) document.querySelector(`[data-row="${sel}"]`)?.scrollIntoView({block: 'center', behavior: 'smooth'}); }

// ── 동작 ────────────────────────────────────────────
async function setForm(k) {
  const it = S.items[sel]; if (!it || it.ro || it.kind === 'summary' || isData(it) || it.form === k) return;
  const before = it.form, iid = it.id, n = pages().at[sel];
  if (await api(`/api/studio/items/${iid}`, {field: 'form', value: k})) { all(); toast(`${n}장을 「${S.forms[k]}」로 바꿨습니다`, async () => { await api(`/api/studio/items/${iid}`, {field: 'form', value: before}); all(); }); }
}
async function drop() {
  const it = S.items[sel]; if (!it) return;
  if (it.ro) { toast('부서 제출판의 장은 여기서 뺄 수 없습니다 — 부서 자료에서 빼고 다시 제출해주세요'); return; }
  const at = sel, j = await api(`/api/studio/items/${it.id}/remove`);
  if (!j) return;
  all(); toast('장을 뺐습니다 — 이슈는 그대로입니다', async () => { if (await api(`/api/studio/${mid}/restore`, {snapshot: j.snapshot})) pick(at); });
}
async function finish() {
  const m = S.meeting;
  if (m.publishes) {
    const j = await api(`/api/studio/${mid}/publish`);
    if (j) { all(); toast(`발행했습니다(${j.version}판) — 판이 고정돼 회의에서 본 그대로 남습니다`); }
  } else {
    const j = await api(`/api/studio/${mid}/submit`);
    if (j) { all(); toast(`제출했습니다(${j.version}판) — 부서 현안 공유회 자료에 이 판이 실립니다`); }
  }
}
document.addEventListener('click', async (e) => {
  const st = e.target.closest('[data-start]'), v = e.target.closest('[data-var]'), f = e.target.closest('[data-f]'), l = e.target.closest('[data-l]'), fm = e.target.closest('[data-form]'), add = e.target.closest('[data-add]'), tab = e.target.closest('[data-tab]');
  const fill = e.target.closest('[data-fill]'), mv = e.target.closest('[data-mv]'), dvd = e.target.closest('[data-dv-done]'), dvr = e.target.closest('[data-dv-reopen]');
  if (dvd || dvr) {
    const id = (dvd || dvr).dataset.dvDone || (dvd || dvr).dataset.dvReopen;
    const r = await fetch(`/api/directives/${id}/${dvd ? 'done' : 'reopen'}`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({note: dvd ? $(`#dv-${id}`).value : ''})});
    const j = await r.json(); if (!j.ok) { toast(j.err); return; }
    const s2 = await (await fetch(`/api/studio/${mid}`)).json(); if (s2.ok) S = s2.state; all();
    toast(dvd ? '지시 완료 — 회의에서 완료 보고가 보입니다' : '지시를 다시 열었습니다'); return;
  }
  if (st) { const j = await api(`/api/studio/${mid}/start`, {mode: st.dataset.start}); if (j) { sel = 0; all(); toast(st.dataset.start === 'carry' ? `지난주 이어받기 — ${j.added}장으로 시작했습니다` : '빈 자료로 시작했습니다 — 「후보」에서 넣으세요'); } return; }
  if (fill) { const j = await api(`/api/studio/${mid}/fill`, {dept_id: fill.dataset.fill}); if (j) { all(); toast(`원장으로 ${j.added}장을 채웠습니다 — 한 줄 형태`); } return; }
  if (mv) { if (await api(`/api/studio/${mid}/dept-move`, {dept_id: mv.dataset.mv, step: +mv.dataset.step})) all(); return; }
  if (v) return setForm(v.dataset.var);
  if ((f || l) && e.shiftKey && !share()) { const i = +(f ? f.dataset.f : l.dataset.l); if (!multi.size) multi.add(sel); multi.has(i) ? multi.delete(i) : multi.add(i); all(); return; }
  if (f) return pick(+f.dataset.f, false);
  if (l) return pick(+l.dataset.l);
  if (fm) return setForm(fm.dataset.form);
  if (add) { const j = await api(`/api/studio/${mid}/items`, {block_id: add.dataset.add, src: '원장'}); if (j) { pick(S.items.findIndex((x) => x.id === j.item_id)); toast('장으로 넣었습니다', async () => { await api(`/api/studio/items/${j.item_id}/remove`); all(); }); } return; }
  if (tab) { $$('[data-tab]').forEach((b) => b.setAttribute('aria-pressed', b === tab)); $$('[data-p]').forEach((p) => (p.hidden = p.dataset.p !== tab.dataset.tab)); return; }
  if (e.target.id === 'tag') { const it = S.items[sel]; if (await api(`/api/studio/items/${it.id}`, {field: 'tag_on', value: !it.tag_on})) all(); return; }
  if (e.target.id === 'drop') return drop();
  if (e.target.id === 'clrM') { multi.clear(); all(); return; }
  if (e.target.id === 'sumBtn') { const ids = [...multi].map((i) => S.items[i].id); const j = await api(`/api/studio/${mid}/summary`, {ids}); if (j) { multi.clear(); pick(S.items.findIndex((x) => x.id === j.item_id)); toast(`${ids.length}장을 한 장으로 묶었습니다 — 각 이슈는 그대로입니다`); } return; }
  if (e.target.id === 'unsum') { if (await api(`/api/studio/items/${S.items[sel].id}/unsummary`)) all(); return; }
  if (e.target.id === 'submitBtn') return finish();
  if (e.target.id === 'addTable') { const j = await api(`/api/studio/${mid}/table-item`, {table_id: Number($('#ptSel').value)}); if (j) { pick(S.items.findIndex((x) => x.id === j.item_id)); toast('기간 표 장을 넣었습니다 — 값은 지표 화면에서'); } return; }
  if (e.target.id === 'addMetric') { const j = await api(`/api/studio/${mid}/metric-item`); if (j) { pick(S.items.findIndex((x) => x.id === j.item_id)); toast('지표 요약 장을 넣었습니다 — 값은 지표 화면에서'); } return; }
});
let lt;
document.addEventListener('input', (e) => {
  if (e.target.id === 'ln') { const it = S.items[sel], v = e.target.value; it.line = v; renderCanvas(); clearTimeout(lt); lt = setTimeout(async () => { await api(`/api/studio/items/${it.id}`, {field: 'line', value: v}); renderBar(); renderLeft(); }, 500); }
  if (e.target.dataset.fact) {
    const el = e.target, b = S.items[sel].blocks[0], key = {cause_text: 'cause', action_text: 'act', decision_needed: 'dec'}[el.dataset.fact];
    b[key] = el.value; renderCanvas();
    clearTimeout(el._t); el._t = setTimeout(async () => {
      const r = await fetch(`/api/issues/${el.dataset.id}/field`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({field: el.dataset.fact, value: el.value, meeting_id: mid})});
      const j = await r.json(); toast(j.ok ? `● ${el.dataset.id} 이슈에 반영했습니다 — 이슈 변경 기록에 남습니다` : j.err);
      const s2 = await (await fetch(`/api/studio/${mid}`)).json(); if (s2.ok) { S = s2.state; renderBar(); }
    }, 600);
  }
});
addEventListener('keydown', (e) => {
  if (e.target.closest?.('input,textarea,select')) return;
  if (e.key === 'ArrowDown') { e.preventDefault(); pick(sel + 1); }
  if (e.key === 'ArrowUp') { e.preventDefault(); pick(sel - 1); }
  if (['1', '2', '3', '4'].includes(e.key)) setForm(Object.keys(S.forms)[+e.key - 1]);
  if (e.key === 'Delete') { e.preventDefault(); drop(); }
});
// 장 끌어서 순서(공유회 제외)
let dragI = null;
document.addEventListener('dragstart', (e) => { const l = e.target.closest('[data-l]'); if (l && !share()) dragI = +l.dataset.l; });
document.addEventListener('dragover', (e) => { if (dragI !== null && e.target.closest('[data-l]')) e.preventDefault(); });
document.addEventListener('drop', async (e) => {
  const l = e.target.closest('[data-l]'); if (!l || dragI === null) return; e.preventDefault();
  const ids = S.items.map((x) => x.id), to = +l.dataset.l, [x] = ids.splice(dragI, 1); ids.splice(to, 0, x); dragI = null;
  if (await api(`/api/studio/${mid}/reorder`, {ids})) pick(to);
});
const setZ = (z) => { zoom = Math.max(0.5, Math.min(1.6, z)); $('#zv').textContent = Math.round(zoom * 100) + '%'; renderCanvas(); };
$('#zIn').onclick = () => setZ(zoom + 0.2); $('#zOut').onclick = () => setZ(zoom - 0.2);
all();
