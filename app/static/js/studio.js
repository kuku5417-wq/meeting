// 회의자료 스튜디오(M10 → M11 공식) — 서버 상태(JSON)를 받아 장 목록·캔버스(장 프레임 + 다른 형태 변형)·속성을 그린다.
// 바꾸는 동작은 모두 /api/studio/… 로 보내고, 돌아온 상태로 다시 그린다. 사실(원인·조치·결정 필요)은 /api/issues/{id}/field.
// 공유회는 부서 칸마다 부서 자료 제출판을 참조로 보여 준다 — 그 장은 읽기 전용(사실만 고칠 수 있다), 부서 순서·원장으로 채우기만 여기서.
import {esc, KIND, slide as draw, cover, divider, directivesSlide, fit, pageTitle, isData} from './slides.js';
import {freeStage, mount as mountFree} from './freeedit.js';

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
    const on = i === sel, n = P.at[i], free = it.free?.on;
    const body = free ? freeStage(it) : draw(it, n, P.total, null, ctx());
    const badge = free ? `<span>자유 편집<em class="fo-over" hidden></em><em class="fo-save">${on ? '' : '저장됨'}</em></span>`
      : `<span>${it.ro ? '부서 제출판' : it.kind === 'metric' ? '지표' : it.kind === 'table' ? '기간 표' : esc(S.forms[it.form])}</span>`;
    h += `<div class="st-row" data-row="${i}">${frame(body, `<b>${n} · ${esc(pageTitle(it).slice(0, 26))}</b>` + badge, on ? 'on' : multi.has(i) ? 'multi' : '', `data-f="${i}"`)}`;
    if (on && !it.ro && !it.free?.on && multi.size < 2 && it.kind !== 'summary' && !isData(it)) h += '<span class="st-vh">다른 형태</span>' + Object.keys(S.forms).filter((k) => k !== it.form).map((k) => frame(draw(it, n, P.total, k, ctx()), `<b>${esc(S.forms[k])}</b> 로 바꾸기`, 'var', `data-var="${k}"`, Math.round(W() * 0.55))).join('');
    h += '</div>';
  });
  if (share()) for (let k = lastSec + 1; k < S.sections.length; k++) h += secRow(k);
  if (!S.items.length) h += `<div class="st-start"><b>장이 없습니다</b><span class="small muted">${share() ? '부서가 제출하면 여기 모입니다. 미제출 부서는 왼쪽에서 「원장으로 채우기」.' : '왼쪽 「후보」에서 ＋ 를 누르면 장이 생깁니다.'}</span></div>`;
  c.innerHTML = h; fit(c);
  attachFree();
}

// ── 자유 편집(결정 ⑦ 15-2) ──────────────────────────
let FE = null, FEsel = '';            // FEsel — 다시 붙일 때 고른 개체를 그대로 둔다
async function saveObjects(objs, rev) {
  const it = S.items[sel];
  if (!it) return null;
  const r = await fetch(`/api/studio/items/${it.id}/objects`, {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({objects: objs, rev})});
  const j = await r.json();
  if (!j.ok) { toast(j.err); return null; }
  if (j.state) S = j.state;                 // 캔버스는 다시 그리지 않는다 — 편집 중이다
  renderFreeProps();                        // 연결 상태(이슈와 다름·이슈가 바뀜)는 바로 갱신한다
  renderBar();                              // 「갈래 안 고른 개체 n」(15-4)도 더하자마자 보여 준다
  return j.free?.rev ?? null;
}
function attachFree() {
  FE?.destroy(); FE = null;
  const it = S.items[sel];
  if (!it || !it.free?.on || it.ro) return;
  const frame = document.querySelector(`[data-row="${sel}"] .st-frame`);
  if (!frame) return;
  FE = mountFree(frame, it, {sel: FEsel, save: saveObjects,
    onChange: (_l, id) => { FEsel = id; renderFreeProps(); }});
  renderFreeProps();
}
const SIZES = [20, 24, 28, 30, 34, 40, 48, 56];
const TONES = {fg: '본문', muted: '흐리게', decide: '결정', problem: '문제', ok: '완료'};
const LINK_STATE = {same: '', diff: '이슈와 다름', stale: '이슈가 바뀜', gone: '이슈를 찾을 수 없음'};
function linkBox(o, it) {
  // 연결 칩(케이스 A8) — 어느 이슈 어느 칸인지, 지금 이슈 값과 같은지
  if (o.type === 'photo') return '';
  const kin = it.free?.derived || [];                                     // 이 장에서 떼어낸 이슈(15-5)
  const kids = kin.filter((d) => !d.merged);                             // 아직 살아 있는 것만 — 연결·합치기 대상
  const whose = (id) => { const d = kin.find((x) => x.id === id); return !d ? `이슈 ${id}` : d.merged ? `합쳐진 이슈 ${id}` : `떼어낸 이슈 ${id}`; };
  if (!o.link) {
    const fields = it.free?.fields || [];
    const where = kids.length ? `<select id="foBlock" aria-label="연결할 이슈"><option value="">이 장의 이슈</option>${kids.map((d) => `<option value="${esc(d.id)}">${esc(d.id)} · ${esc(d.title)}</option>`).join('')}</select>` : '';
    return `<p class="v-sec">연결 없음 — 이 자료에만 있는 글</p>
      <div class="row">${where}<select id="foField" aria-label="다시 연결할 칸"><option value="">칸 고르기</option>${fields.map((f) => `<option value="${f.field}">${esc(f.label)}</option>`).join('')}</select>
        <button class="btn sm" type="button" id="foRelink">다시 연결</button></div>`;
  }
  const st = LINK_STATE[o.state] || '';
  const warn = o.state === 'diff' ? `<p class="small">이슈 값: ${esc(o.issue_text || '(비어 있음)')} — 이 자료에만 다르게 적혀 있습니다.</p>`
    : o.state === 'stale' ? `<p class="small">이슈가 그 사이 바뀌었습니다 → <b>${esc(o.issue_text || '(비어 있음)')}</b></p>`
      : o.state === 'gone' ? '<p class="small">연결한 이슈를 찾을 수 없습니다 — 연결을 끊고 이 자료의 글로 두세요.</p>' : '';
  const merge = o.other_block && kids.some((d) => d.id === o.other_block)
    ? `<button class="btn sm" type="button" data-merge="${esc(o.other_block)}">${esc(o.other_block)} 를 이 이슈로 합치기</button>` : '';
  // 합쳐진 이슈를 가리키는 연결은 사실을 반영하지 않는다 — 남는 이슈로 연결을 옮기게 한다
  const moved = o.merged_block
    ? `<p class="small">이 이슈는 <b>${esc(o.merged_block)}</b> 로 합쳐졌습니다 — 사실은 그쪽에 남깁니다.</p>`
      + (o.merged_block === it.blocks?.[0]?.id            // 남는 쪽이 이 장의 이슈일 때만 한 번에 옮긴다
        ? `<div class="row"><select id="foField" hidden><option value="${esc(o.link.field)}" selected></option></select>
         <button class="btn sm primary" type="button" id="foRelink">${esc(o.merged_block)} 로 연결 옮기기</button></div>` : '')
    : '';
  return `<p class="v-sec">연결 — ${esc(whose(o.link.block))} ${esc(o.field_label || o.link.field)}${st ? ` <b class="v-late">${st}</b>` : ''}</p>${warn}${moved}
    <div class="row">${o.fact && !o.choice && o.state !== 'gone' && !o.merged_block ? '<button class="btn sm primary" type="button" id="foApply">이슈에도 반영</button>' : ''}
      ${o.state === 'gone' ? '' : '<button class="btn sm" type="button" id="foPull">다시 가져오기</button>'}
      <button class="btn sm" type="button" id="foUnlink">연결 끊기</button>${merge}</div>
    ${o.choice ? '<span class="small muted">「상태」는 고르는 칸입니다 — 이슈 화면에서 고릅니다. 여기 글은 이 자료의 표현으로 남습니다.</span>'
      : o.fact ? '' : '<span class="small muted">이 칸은 자료의 표현입니다 — 이슈 사실은 바뀌지 않습니다.</span>'}`;
}
const SCOPE_LABEL = {미정: '안 고름', 자료만: '이 자료만', 진행: '이번 주 진행', 사실: '이슈 사실', 새이슈: '새 이슈로'};
const SCOPE_DONE = {자료만: '이 자료에만 남습니다 — 이슈 기록에는 「개체 추가」 한 줄만 남았습니다.',
  진행: '이슈의 이번 주 진행 한 줄에 덧붙였습니다.',
  사실: '이슈 사실 칸에 덧붙였습니다 — 이슈 변경 기록에 남았습니다.',
  새이슈: '새 이슈로 떼어냈습니다 — 원래 이슈와 「파생」으로 이어져 있습니다.'};
function scopeBox(o, it) {
  // 개체 추가 칩(결정 ⑦ 15-4) — 더한 개체는 **매번** 갈래를 고른다. 기본값 없음.
  const sc = o.scope || '';
  if (!sc) return '';
  if (sc !== '미정') {
    const where = sc === '새이슈' && o.scope_block ? `<a href="/issues?id=${esc(o.scope_block)}">${esc(o.scope_block)}</a> 로 떼어냈습니다 — 원래 이슈와 「파생」으로 이어져 있습니다.`
      : sc === '사실' && o.scope_field ? `이슈 ${esc((it.free?.pick_fields || []).find((f) => f.field === o.scope_field)?.label || o.scope_field)} 칸에 덧붙였습니다 — 이슈 변경 기록에 남았습니다.`
        : esc(SCOPE_DONE[sc] || '');
    return `<p class="v-sec">갈래 — ${esc(SCOPE_LABEL[sc] || sc)}</p><span class="small muted">${where}</span>`;
  }
  const fields = it.free?.pick_fields || [];
  return `<p class="v-sec">더한 개체 — 어디에 남길까요? <b class="v-late">안 고름</b></p>
    <div class="row">${[['자료만', '이 자료만'], ['진행', '이번 주 진행'], ['새이슈', '새 이슈로']]
      .map(([k, v]) => `<button class="btn sm" type="button" data-scope="${k}">${v}</button>`).join('')}</div>
    <div class="row"><select id="foFactField" aria-label="이슈 사실에 더할 칸"><option value="">칸 고르기</option>${fields.map((f) => `<option value="${f.field}">${esc(f.label)}</option>`).join('')}</select>
      <button class="btn sm" type="button" data-scope="사실">이슈 사실에 더하기</button></div>
    <span class="small muted">고르지 않으면 이 자료에만 남습니다 — 제출 전에 수로 알려 드립니다.</span>`;
}
function renderFreeProps() {
  const box = document.querySelector('#freeProps');
  if (!box || !FE) return;
  const it = S.items[sel] || {};
  const live = (it.free?.objects || []).find((x) => x.id === FE.sel?.id);   // 연결 상태는 서버가 판정한 값
  const o = FE.sel ? {...FE.sel, ...(live ? {state: live.state, issue_text: live.issue_text, field_label: live.field_label,
    fact: live.fact, scope: live.scope, scope_field: live.scope_field, scope_block: live.scope_block,
    other_block: live.other_block, merged_block: live.merged_block, link: live.link} : {})} : null;
  const miss = (it.free?.missing || []);
  const missHtml = miss.length ? `<p class="v-sec">장에 없는 칸 ${miss.length}</p><div class="row">${miss.map((f) => `<button class="btn sm" type="button" data-addfield="${f.field}">＋ ${esc(f.label)}</button>`).join('')}</div>` : '';
  if (!o) { box.innerHTML = '<span class="small muted">개체를 고르면 여기서 글자·색·소제목·연결을 고칩니다. 두 번 누르면 글을 바로 고칠 수 있습니다.</span>' + missHtml; return; }
  // 갈래를 아직 안 고른 개체는 **갈래부터** 묻는다 — 「다시 연결」 칸 고르기와 나란히 두면 어느 쪽인지 헷갈린다
  box.innerHTML = scopeBox(o, it) + (o.scope === '미정' ? '' : linkBox(o, it)) + missHtml + `<p class="v-sec">고른 개체 — ${esc(o.label || (o.type === 'photo' ? '사진' : '글'))}</p>
    <label class="f">소제목<input type="text" id="foLabel" value="${esc(o.label || '')}" placeholder="예: 원인"></label>
    ${o.type === 'photo' ? '' : `<label class="f">글<textarea id="foText" rows="3">${esc(o.text)}</textarea></label>
    <div class="row"><select id="foSize" aria-label="글자 크기">${SIZES.map((s) => `<option value="${s}"${s === (o.style?.size || 30) ? ' selected' : ''}>${s}px</option>`).join('')}</select>
      <button class="btn sm" type="button" id="foBold" aria-pressed="${!!o.style?.bold}">굵게</button>
      ${['left', 'center', 'right'].map((a) => `<button class="btn sm" type="button" data-align="${a}" aria-pressed="${(o.style?.align || 'left') === a}">${a === 'left' ? '왼쪽' : a === 'center' ? '가운데' : '오른쪽'}</button>`).join('')}</div>
    <div class="row">${Object.entries(TONES).map(([k, v]) => `<button class="btn sm" type="button" data-tone="${k}" aria-pressed="${(o.style?.tone || 'fg') === k}">${v}</button>`).join('')}</div>`}
    <div class="row"><button class="btn sm" type="button" id="foAdd">＋ 글 상자</button><button class="btn sm" type="button" id="foCopy">복사</button><button class="btn sm" type="button" id="foDel">개체 지우기</button>
      <button class="btn sm" type="button" id="foUndo">되돌리기</button></div>
    <p class="small muted">바꾼 것은 모두 되돌릴 수 있습니다(Ctrl+Z). 저장은 자동입니다 — 틀 위 「저장됨」이 서버가 받은 표시입니다.</p>`;
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
    <p class="v-sec">자유 편집 — 이 장을 개체로 배치합니다(이 자료에만)</p>
    <div class="row"><button class="btn sm${it.free?.on ? ' primary' : ''}" type="button" id="freeBtn" aria-pressed="${!!it.free?.on}">${it.free?.on ? '자유 편집 끄기' : '자유 편집 켜기'}</button>
      ${it.free?.can_undo ? '<button class="btn sm" type="button" id="freeUndoForm">형태 바꾸기 되돌리기</button>' : ''}</div>
    ${it.free?.on ? '<div id="freeProps"></div>' : '<span class="small muted">켜면 지금 형태대로 개체 초안을 만듭니다. 캔버스에서 끌어 옮기고 크기·글자를 고칠 수 있습니다. 이슈의 사실은 바뀌지 않습니다.</span>'}
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
  const un = m.unchosen || 0;
  note.hidden = !(un || (m.version && (m.status === '수정됨' || m.changes)));
  if (note.hidden) { note.innerHTML = ''; return; }
  const unNote = un ? `갈래를 안 고른 개체 <b>${un}</b> — 개체를 고르면 「이 자료만 · 이번 주 진행 · 이슈 사실 · 새 이슈로」에서 고릅니다.` : '';
  if (!(m.version && (m.status === '수정됨' || m.changes))) { note.innerHTML = unNote; return; }
  note.innerHTML = (un ? unNote + '<br>' : '') + `${m.version}판(${esc(m.published_at)}) 뒤에 ${m.changes ? `이슈 사실이 바뀐 장 <b>${m.changes}</b>` : ''}${m.changes && m.status === '수정됨' ? ' · ' : ''}${m.status === '수정됨' ? '자료를 고쳤습니다' : ''} — 이미 나간 판은 그대로이고, ${m.publishes ? '다시 발행' : '다시 제출'}하면 ${m.version + 1}판이 됩니다.`;
}
function all() {
  if (sel >= S.items.length) sel = Math.max(0, S.items.length - 1);
  renderLeft(); renderCanvas(); renderProps(); renderBar();
  renderFreeProps();     // 속성 패널은 캔버스보다 나중에 그려진다 — 개체 칸을 그때 채운다
}
function pick(i, scroll = true) { multi.clear(); sel = Math.max(0, Math.min(S.items.length - 1, i)); all(); if (scroll) document.querySelector(`[data-row="${sel}"]`)?.scrollIntoView({block: 'center', behavior: 'smooth'}); }

// ── 동작 ────────────────────────────────────────────
async function setForm(k) {
  const it = S.items[sel]; if (!it || it.ro || it.kind === 'summary' || isData(it) || it.form === k) return;
  const before = it.form, iid = it.id, n = pages().at[sel];
  const wasFree = it.free?.on;
  if (await api(`/api/studio/items/${iid}`, {field: 'form', value: k})) {
    all();
    if (wasFree) toast(`${n}장을 「${S.forms[k]}」로 새로 그렸습니다 — 꾸민 것은 되돌리기로 돌아옵니다`,
      async () => { if (await api(`/api/studio/items/${iid}/undo-form`)) all(); });
    else toast(`${n}장을 「${S.forms[k]}」로 바꿨습니다`, async () => { await api(`/api/studio/items/${iid}`, {field: 'form', value: before}); all(); });
  }
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
  const un = m.unchosen || 0;              // 15-4 — 막지 않고 수로 알린다(결정 ⑦)
  if (un && !window.confirm(`갈래를 안 고른 개체가 ${un}개 있습니다. 그대로 두면 이 자료에만 남고 이슈에는 남지 않습니다. `
      + `${m.publishes ? '발행' : '제출'}할까요?`)) return;
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
  // ── 자유 편집(결정 ⑦ 15-2) ──
  if (e.target.id === 'freeBtn') {
    const it = S.items[sel];
    const on = !it.free?.on;
    if (await api(`/api/studio/items/${it.id}/free`, {on})) { all(); toast(on ? '자유 편집을 켰습니다 — 개체를 끌어 옮기고 두 번 눌러 글을 고칩니다' : '자유 편집을 껐습니다 — 꾸민 것은 그대로 남아 있습니다'); }
    return;
  }
  if (e.target.id === 'freeUndoForm') { if (await api(`/api/studio/items/${S.items[sel].id}/undo-form`)) { all(); toast('형태 바꾸기를 되돌렸습니다'); } return; }
  if (e.target.id === 'foAdd') { FE?.add(); return; }
  if (e.target.id === 'foCopy') { FE?.copy(); toast('복사한 개체는 연결 없는 자유 글입니다 — 필요하면 칸에 다시 연결하세요'); return; }
  if (['foApply', 'foPull', 'foUnlink', 'foRelink'].includes(e.target.id) || e.target.closest('[data-addfield]')) {
    const it = S.items[sel], oid = FE?.sel?.id;
    const af = e.target.closest('[data-addfield]');
    const op = af ? 'add' : {foApply: 'apply', foPull: 'pull', foUnlink: 'unlink', foRelink: 'relink'}[e.target.id];
    const field = af ? af.dataset.addfield : (document.querySelector('#foField')?.value || '');
    const block = op === 'relink' ? (document.querySelector('#foBlock')?.value || '') : '';
    if (op === 'relink' && !field) { toast('어느 칸에 연결할지 먼저 골라주세요'); return; }
    await FE?.flush();                                   // 편집 중이던 것을 먼저 저장하고
    const j = await api(`/api/studio/items/${it.id}/link`, {op, oid, field, block});
    if (!j) return;
    all();
    toast(op === 'apply' ? '이슈 사실에 반영했습니다 — 이슈 변경 기록에 남습니다'
      : op === 'pull' ? '이슈의 지금 값을 가져왔습니다'
      : op === 'unlink' ? '연결을 끊었습니다 — 글은 그대로입니다'
      : op === 'add' ? '칸을 개체로 넣었습니다' : '다시 연결했습니다');
    return;
  }
  if (e.target.closest('[data-merge]')) {               // 떼어낸 이슈 되돌려 합치기(15-5)
    const it = S.items[sel], src = e.target.closest('[data-merge]').dataset.merge, dst = it.blocks[0]?.id;
    if (!window.confirm(`${src} 를 ${dst} 로 합칩니다. ${src} 는 목록에서 빠지고 기록으로 남습니다.`)) return;
    const r = await fetch(`/issues/${src}/merge`, {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({into: dst}), redirect: 'follow'});
    const bad = new URL(r.url).searchParams.get('err');
    const s2 = await (await fetch(`/api/studio/${mid}`)).json();
    if (s2.ok) S = s2.state;
    all();
    toast(bad || `${src} 를 ${dst} 로 합쳤습니다 — ${src} 는 기록으로 남습니다`);
    return;
  }
  if (e.target.closest('[data-scope]')) {               // 개체 추가 칩(15-4)
    const it = S.items[sel], oid = FE?.sel?.id;
    const scope = e.target.closest('[data-scope]').dataset.scope;
    const field = scope === '사실' ? (document.querySelector('#foFactField')?.value || '') : '';
    if (scope === '사실' && !field) { toast('어느 사실 칸에 더할지 먼저 골라주세요'); return; }
    await FE?.flush();                                   // 편집 중이던 글을 먼저 저장하고
    const j = await api(`/api/studio/items/${it.id}/link`, {op: 'pick', oid, scope, field});
    if (!j) return;
    all();
    toast(scope === '자료만' ? '이 자료에만 남깁니다 — 이슈 기록에 「개체 추가」 한 줄이 남습니다'
      : scope === '진행' ? '이슈의 이번 주 진행에 덧붙였습니다'
      : scope === '사실' ? '이슈 사실 칸에 덧붙였습니다 — 이슈 변경 기록에 남습니다'
      : `새 이슈 ${j.new_block} 로 떼어냈습니다 — 원래 이슈와 「파생」으로 이어집니다`);
    return;
  }
  if (e.target.id === 'foDel') { FE?.remove(); return; }
  if (e.target.id === 'foUndo') { FE?.undo(); return; }
  if (e.target.id === 'foBold') { FE?.style('bold', !FE.sel?.style?.bold); return; }
  if (e.target.closest('[data-align]')) { FE?.style('align', e.target.closest('[data-align]').dataset.align); return; }
  if (e.target.closest('[data-tone]')) { FE?.style('tone', e.target.closest('[data-tone]').dataset.tone); return; }
  if (e.target.id === 'clrM') { multi.clear(); all(); return; }
  if (e.target.id === 'sumBtn') { const ids = [...multi].map((i) => S.items[i].id); const j = await api(`/api/studio/${mid}/summary`, {ids}); if (j) { multi.clear(); pick(S.items.findIndex((x) => x.id === j.item_id)); toast(`${ids.length}장을 한 장으로 묶었습니다 — 각 이슈는 그대로입니다`); } return; }
  if (e.target.id === 'unsum') { if (await api(`/api/studio/items/${S.items[sel].id}/unsummary`)) all(); return; }
  if (e.target.id === 'submitBtn') return finish();
  if (e.target.id === 'addTable') { const j = await api(`/api/studio/${mid}/table-item`, {table_id: Number($('#ptSel').value)}); if (j) { pick(S.items.findIndex((x) => x.id === j.item_id)); toast('기간 표 장을 넣었습니다 — 값은 지표 화면에서'); } return; }
  if (e.target.id === 'addMetric') { const j = await api(`/api/studio/${mid}/metric-item`); if (j) { pick(S.items.findIndex((x) => x.id === j.item_id)); toast('지표 요약 장을 넣었습니다 — 값은 지표 화면에서'); } return; }
});
let lt, factChain = Promise.resolve();
document.addEventListener('change', (e) => {
  if (e.target.id === 'foSize') FE?.style('size', Number(e.target.value));
});
document.addEventListener('input', (e) => {
  if (e.target.id === 'foText') { FE?.text(e.target.value); return; }
  if (e.target.id === 'foLabel') { FE?.label(e.target.value); return; }
  if (e.target.id === 'ln') { const it = S.items[sel], v = e.target.value; it.line = v; renderCanvas(); clearTimeout(lt); lt = setTimeout(async () => { await api(`/api/studio/items/${it.id}`, {field: 'line', value: v}); renderBar(); renderLeft(); }, 500); }
  if (e.target.dataset.fact) {
    const el = e.target, b = S.items[sel].blocks[0], key = {cause_text: 'cause', action_text: 'act', decision_needed: 'dec'}[el.dataset.fact];
    b[key] = el.value; renderCanvas();
    clearTimeout(el._t); el._t = setTimeout(() => { factChain = factChain.then(async () => {   // 한 번에 하나씩 — 판 번호(결정 ①)
      const r = await fetch(`/api/issues/${el.dataset.id}/field`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({field: el.dataset.fact, value: el.value, meeting_id: mid, base_version: b.ver})});
      const j = await r.json(); if (j.row_version != null) b.ver = j.row_version;
      toast(j.ok ? `● ${el.dataset.id} 이슈에 반영했습니다 — 이슈 변경 기록에 남습니다` : j.err);
      const s2 = await (await fetch(`/api/studio/${mid}`)).json(); if (s2.ok) { S = s2.state; renderBar(); }
    }); }, 600);
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
