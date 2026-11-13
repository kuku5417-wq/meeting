// M9 이슈 원장 작업대 — 칸 자동 저장(0.5초 뒤 JSON), 1차 초안 미리보기 즉시 반영, 이번 주 한 줄 Enter, 일괄 줄, J/K·Ctrl+S.
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const state = $('#saveState');
const say = (t, bad) => { if (state) { state.textContent = t; state.classList.toggle('bad', !!bad); } };

// 슬라이드 미리보기(1920×1080 좌표)를 칸 폭에 맞춰 줄인다
function fit() { $$('.v-stage-wrap').forEach((w) => { const st = w.querySelector('.v-stage'); if (st) st.style.transform = `scale(${w.clientWidth / 1920})`; }); }
addEventListener('resize', fit); fit();

// 미리보기 반영
function preview(field, value) {
  const el = $(`[data-pv="${field}"]`);
  if (!el) return;
  const empty = {body: '—', cause_text: '조사 중', action_text: '—', line: '—'}[field] ?? '';
  el.textContent = value.trim() || empty;
  if (field === 'decision_needed') $('#pvDec').hidden = !value.trim();
  if (field === 'action_text' && $('#closeAct')) $('#closeAct').value = value;
}

// 자동 저장 — 한 번에 하나씩(판 번호가 꼬이지 않게), 화면이 본 판 번호를 같이 보낸다(결정 ①)
const timers = new Map();
const verEl = $('#rowVer');
let rowVer = verEl ? Number(verEl.dataset.ver) : null, chain = Promise.resolve();
function save(el) { chain = chain.then(() => saveNow(el)); return chain; }
async function saveNow(el) {
  say('저장 중…');
  try {
    const r = await fetch(`/api/issues/${el.dataset.id}/field`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({field: el.dataset.field, value: el.value, base_version: rowVer})});
    const j = await r.json();
    if (!j.ok) { say(j.err, true); return; }
    if (j.row_version != null) rowVer = j.row_version;
    say('저장됨 · 방금');
    if ($('#draftState')) $('#draftState').textContent = j.draft_label;
  } catch (e) { say('저장하지 못했습니다 — 네트워크를 확인하고 다시 고쳐주세요', true); }
}
$$('[data-field]').forEach((el) => {
  const ev = el.tagName === 'SELECT' ? 'change' : 'input';
  el.addEventListener(ev, () => {
    preview(el.dataset.field, el.value);
    clearTimeout(timers.get(el)); say('저장 중…');
    timers.set(el, setTimeout(() => save(el), ev === 'change' ? 0 : 500));
  });
});

// 이번 주 한 줄 — Enter 로 저장
const line = $('#wkLine');
if (line) line.addEventListener('keydown', async (e) => {
  if (e.key !== 'Enter') return;
  e.preventDefault();
  say('저장 중…');
  const r = await fetch(`/api/issues/${line.dataset.id}/line`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text: line.value})});
  const j = await r.json();
  if (!j.ok) { say(j.err, true); return; }
  say('이번 주 한 줄 저장됨'); preview('line', line.value);
});

// 일괄 줄 — 하나라도 고르면 보인다. 「상태」를 고르면 값 목록을 상태로
const bar = $('#bulkBar'), act = $('#bulkAct'), val = $('#bulkVal');
const adoptOpts = val ? val.innerHTML : '', deptOpts = $('#deptOpts')?.innerHTML || '';
function syncBulk() {
  const n = $$('#bulkForm input[name=ids]:checked').length;
  if (bar) { bar.hidden = !n; $('#bulkN').textContent = `고른 이슈 ${n}건`; }
}
$$('#bulkForm input[name=ids]').forEach((c) => c.addEventListener('change', syncBulk));
if (act) act.addEventListener('change', () => { val.innerHTML = act.value === 'status' ? '<option>신규</option><option>진행</option>' : act.value === 'adopt' ? adoptOpts : deptOpts; });

// J/K 이슈 이동, Ctrl+S 초안 완료
addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); $('#doneForm')?.requestSubmit(); return; }
  if (e.target.closest('input,textarea,select')) return;
  const rows = $$('.v-row'), i = rows.findIndex((r) => r.classList.contains('on'));
  const go = (k) => { const r = rows[k]; if (r) location.href = r.querySelector('.v-row-link').href; };
  if (e.key === 'j') go(i + 1);
  if (e.key === 'k') go(i - 1);
});
