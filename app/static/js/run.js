// 회의 진행(M12) — 진행자: 지금 장 + 「이 안건 기록」 카드, 「기록하고 다음」(Enter) 한 번에 코멘트·결정·지시·종결을 남긴다.
// 발표 화면(?view=present)은 장만 그리고 BroadcastChannel 로 진행자 쪽 쪽 번호를 따라간다(서버 왕복 없음). 안건 = 최신 발행본.
import {esc, pageList, renderPage, fit, pageTitle, isData} from './slides.js';

const $ = (s) => document.querySelector(s);
let S = JSON.parse($('#rnState0').textContent);
const mid = S.meeting.id, present = new URLSearchParams(location.search).get('view') === 'present';
const D = S.deck, P = pageList(D), total = P.length;
const ch = 'BroadcastChannel' in window ? new BroadcastChannel('meeting-run-' + mid) : null;
let pg = 0;
try { pg = Math.min(total - 1, +(sessionStorage.getItem('run-pg-' + mid) || 0)); } catch (e) { /* 저장소 없음 — 첫 쪽부터 */ }

function drawStage() { $('#stage').innerHTML = renderPage(P[pg], pg + 1, total, D, S.long_weeks); fit(document); }

if (present) {
  document.body.classList.add('present');
  const set = (n) => { pg = n; drawStage(); };
  if (ch) ch.onmessage = (e) => { if (e.data?.pg != null) set(e.data.pg); };
  addEventListener('resize', () => fit(document));
  addEventListener('keydown', (e) => { if (e.key === 'ArrowRight') set(Math.min(total - 1, pg + 1)); if (e.key === 'ArrowLeft') set(Math.max(0, pg - 1)); });
  set(pg);
} else {
  let tt;
  const toast = (msg, undo) => {
    const t = $('#toast');
    t.innerHTML = `<span>${esc(msg)}</span>` + (undo ? '<button type="button">되돌리기</button>' : '');
    t.hidden = false;
    if (undo) t.querySelector('button').onclick = () => { t.hidden = true; undo(); };
    clearTimeout(tt); tt = setTimeout(() => { t.hidden = true; }, 7000);
  };
  const post = async (url, body) => {
    const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
    const j = await r.json();
    if (!j.ok) { toast(j.err); return null; }
    if (j.state) S = j.state;
    return j;
  };
  const target = () => { const p = P[pg]; if (p.t !== 'item') return null; const sel = $('#tgt'); return sel ? sel.value : p.it.blocks[0]?.id; };
  const blockOf = (id) => P[pg].it.blocks.find((b) => b.id === id) || {};
  const done = (id) => { const r = S.records[id]; return r && (r.comments.length || r.decision || r.directives.length || r.close); };

  function drawThumbs() {
    $('#thumbs').innerHTML = P.map((p, i) => {
      const label = p.t === 'cover' ? '표지' : p.t === 'dir' ? '지난 지시' : p.t === 'div' ? p.sec.dept : pageTitle(p.it);
      const ok = p.t === 'item' && p.it.blocks.some((b) => done(b.id));
      return `<button type="button" class="rn-th${i === pg ? ' on' : ''}${p.t === 'div' ? ' sec' : ''}" data-pg="${i}"${i === pg ? ' aria-current="true"' : ''}><span class="n">${i + 1}</span><span class="t">${esc(label)}</span>${ok ? '<span class="ok" aria-label="기록함">✓</span>' : ''}</button>`;
    }).join('');
    $('#thumbs .on')?.scrollIntoView({block: 'nearest', inline: 'center'});
  }
  function drawCard() {
    const p = P[pg], c = $('#card');
    if (p.t === 'cover') { c.innerHTML = `<b>${esc(S.meeting.title)}</b><span class="small muted">발행 ${S.meeting.version}판 · ${esc(S.meeting.published_at)} · 쪽 ${total}</span><p class="small">안건마다 오른쪽 칸에 코멘트·결정·지시를 남기고 <b>Enter</b> 로 넘어갑니다. 「발표 화면 열기」로 띄운 창은 이 화면을 따라갑니다.</p>`; return; }
    if (p.t === 'dir') { c.innerHTML = `<b>지난 지시 점검 ${D.directives.length}건</b>` + D.directives.map((d) => `<div class="st-dir${d.late ? ' late' : ''}"><span class="small"><b>${esc(d.text)}</b> · ${esc(d.dept)} · 기한 ${esc(d.due.slice(-3))}</span><span class="small ${d.status === '완료' ? 'ok-text' : 'muted'}">${d.status === '완료' ? '완료 — ' + esc(d.done_note) : d.late ? '기한 지남 — 담당 부서 확인' : '진행 중'}</span></div>`).join(''); return; }
    if (p.t === 'div') { c.innerHTML = `<b>${esc(p.sec.dept)}</b><span class="small muted">${esc(p.sec.state)} · 안건 ${p.sec.items.length}</span>`; return; }
    if (isData(p.it)) { c.innerHTML = `<b>${esc((p.it.metric || p.it.table)?.dept || '')} ${esc(pageTitle(p.it))}</b><span class="small muted">기록할 이슈가 없는 장입니다 — Enter 로 넘어갑니다</span>`; return; }
    const bs = p.it.blocks, id = target() || bs[0]?.id, b = bs.find((x) => x.id === id) || bs[0] || {}, r = S.records[b.id] || {comments: [], directives: []};
    const tgt = bs.length > 1 ? `<label class="f">기록할 이슈<select id="tgt">${bs.map((x) => `<option value="${esc(x.id)}"${x.id === b.id ? ' selected' : ''}>${esc(x.id)} ${esc(x.title)}</option>`).join('')}</select></label>` : '';
    const prev = [...r.comments.map((x) => `<li>코멘트 — ${esc(x)}</li>`), r.decision ? `<li class="dec">결정 — ${esc(r.decision)}</li>` : '', ...r.directives.map((x) => `<li>지시 — ${esc(x)}</li>`)].join('');
    let close = '';
    if (r.closure_id && S.can_close) close = `<div class="rn-close"><b class="small">종결 요청 — 승인하면 사례 카드</b>${b.cause ? `<span class="small muted">원인: ${esc(b.cause)}</span>` : '<label class="f">원인(사례 카드에 필요)<input type="text" id="cause" placeholder="원인을 적어야 승인됩니다"></label>'}<span class="row"><button class="btn sm primary" type="button" data-close="ok">종결 승인</button><button class="btn sm" type="button" data-close="hold">보류</button></span></div>`;
    else if (r.closure_id) close = '<p class="small muted">종결 요청 중 — 승인·보류는 부서 현안 공유회에서 합니다.</p>';
    else if (r.close) close = `<div class="rn-close"><span class="small"><b>${esc(r.close)}</b> — 이 회의에서 결정</span><button class="btn sm" type="button" id="undoClose">되돌리기</button></div>`;
    c.innerHTML = `<span class="small muted">${pg + 1} / ${total} · ${esc(b.id)} · ${esc(b.dept)}</span><b>${esc(b.title)}</b>${b.ptag ? `<span class="st-ptag" aria-pressed="true">[${esc(b.ptag)}]</span>` : ''}${tgt}
      ${prev ? `<ul class="rn-prev">${prev}</ul>` : ''}
      <label class="f">코멘트<textarea id="cm" rows="3" placeholder="회의에서 나온 말 — 이슈에 회의 기록으로 쌓입니다"></textarea></label>
      <label class="f rn-dec">결정${b.dec ? ` — 결정 필요: ${esc(b.dec)}` : ''}<input type="text" id="dec" placeholder="${b.dec ? '결정을 남기면 결정 필요 칸이 비워집니다' : '정한 것이 있으면'}"></label>
      <details id="act"><summary class="small">＋ 지시 남기기 — 다음 주 담당 부서 회의자료 맨 위에 나옵니다</summary>
        <div class="rn-act"><input type="text" id="actT" placeholder="지시 내용"><span class="row"><select id="actD" aria-label="담당 부서">${S.depts.map((d) => `<option value="${esc(d.id)}"${d.name === b.dept ? ' selected' : ''}>${esc(d.name)}</option>`).join('')}</select><input type="text" id="actW" value="${esc(S.next_week)}" aria-label="기한 주차" style="width:96px"></span></div></details>
      ${close}<a class="small" href="/issues?id=${esc(b.id)}" target="_blank" rel="noopener">이슈 열기 ↗</a>`;
    $('#cm').focus({preventScroll: true});
  }
  function drawBar() {
    const items = P.filter((p) => p.t === 'item'), rec = items.filter((p) => p.it.blocks.some((b) => done(b.id))).length;
    const decLeft = items.filter((p) => p.it.blocks.some((b) => b.dec && !S.records[b.id]?.decision)).length;
    $('#rnState').textContent = `기록한 안건 ${rec}/${items.length}` + (decLeft ? ` · 결정이 남은 안건 ${decLeft}` : ' · 남은 결정 없음');
    $('#rnSub').textContent = ` · 발행 ${S.meeting.version}판 · ${S.meeting.status === '종료' ? '끝난 회의' : '진행 중'}`;
    $('#next').textContent = pg === 0 ? '첫 안건 →' : pg === total - 1 ? '기록하고 회의 마치기' : '기록하고 다음 →';
    $('#prev').disabled = pg === 0;
  }
  function draw() { drawStage(); drawThumbs(); drawCard(); drawBar(); if (ch) ch.postMessage({pg}); try { sessionStorage.setItem('run-pg-' + mid, pg); } catch (e) { /* 저장소 없음 — 무시 */ } }
  const go = (n) => { pg = Math.max(0, Math.min(total - 1, n)); draw(); };

  async function save() {
    const id = target(); if (!id) return true;
    const body = {block_id: id, comment: $('#cm').value, decision: $('#dec').value};
    const at = $('#actT')?.value.trim();
    if (at) body.directive = {text: at, dept_id: $('#actD').value, due: $('#actW').value.trim()};
    if (!body.comment.trim() && !body.decision.trim() && !at) return true;
    const j = await post(`/api/run/${mid}/record`, body);
    if (!j) return false;
    toast(`${id} — ${j.done.join('·')} 기록`);
    return true;
  }
  async function next() {
    if (!(await save())) return;
    if (pg === total - 1) { if (await post(`/api/run/${mid}/finish`)) { draw(); toast('회의를 마쳤습니다 — 기록은 이슈마다 남았습니다'); } return; }
    go(pg + 1);
  }
  $('#next').onclick = next;
  $('#prev').onclick = () => go(pg - 1);
  $('#openP').onclick = () => window.open(`/meetings/${mid}/run?view=present`, 'meeting-present-' + mid, 'width=1280,height=720');
  $('#finishBtn').onclick = async () => { if (await post(`/api/run/${mid}/finish`)) { draw(); toast('회의를 마쳤습니다'); } };
  document.addEventListener('click', async (e) => {
    const t = e.target.closest('[data-pg]'), c = e.target.closest('[data-close]');
    if (t) { if (await save()) go(+t.dataset.pg); return; }
    if (c) {
      const id = target(), b = blockOf(id);
      if (!(await save())) return;
      const j = await post(`/api/run/${mid}/record`, {block_id: id, close: c.dataset.close, cause: $('#cause')?.value || ''});
      if (!j) return;
      toast(c.dataset.close === 'ok' ? `${id} 종결 승인 — 사례 카드를 만들었습니다` : `${id} 보류 — 진행으로 돌아갑니다`, async () => { if (await post(`/api/run/${mid}/undo-close`, {block_id: id})) { draw(); toast(`${b.title || id} 종결 결정을 되돌렸습니다`); } });
      go(pg + 1); return;
    }
    if (e.target.id === 'undoClose') { const id = target(); if (await post(`/api/run/${mid}/undo-close`, {block_id: id})) { draw(); toast('되돌렸습니다 — 다시 종결 요청 상태'); } }
  });
  document.addEventListener('change', (e) => { if (e.target.id === 'tgt') drawCard(); });
  addEventListener('keydown', (e) => {
    const inField = e.target.closest?.('input,textarea,select');
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && (!inField || e.target.id === 'cm' || e.target.id === 'dec')) { if (e.target.closest?.('#more')) return; e.preventDefault(); next(); return; }
    if (inField) return;
    if (e.key === 'ArrowRight') go(pg + 1);
    if (e.key === 'ArrowLeft') go(pg - 1);
  });
  addEventListener('resize', () => fit(document));

  // 회의 중 등록 · 회의록
  $('#regDept').innerHTML = S.depts.map((d) => `<option value="${esc(d.id)}">${esc(d.name)}</option>`).join('');
  const drawCands = (cs) => { $('#cands').innerHTML = cs.filter((c) => c.state === '제안').map((c) => `<div class="v-row rn-cand"><span class="t"><b>${esc(c.title)}</b> <span class="small muted">${esc(c.raw)}</span></span><span class="row">${c.link ? `<button class="btn sm" type="button" data-cand="${c.id}" data-act="link" data-block="${esc(c.link)}">${esc(c.link)} 에 연결</button>` : ''}<button class="btn sm" type="button" data-cand="${c.id}" data-act="register" data-dept="${esc(c.dept_id)}">새 이슈</button><button class="btn sm" type="button" data-cand="${c.id}" data-act="drop">버리기</button></span></div>`).join(''); };
  $('#regForm').onsubmit = async (e) => { e.preventDefault(); const f = new FormData(e.target); const j = await post(`/api/run/${mid}/register`, Object.fromEntries(f)); if (j) { e.target.reset(); toast(`${j.block_id} 등록 — 다음 주 그 부서 회의자료 후보에 나옵니다`); draw(); } };
  $('#minForm').onsubmit = async (e) => { e.preventDefault(); const j = await post(`/api/run/${mid}/minutes`, {raw_text: e.target.raw_text.value}); if (j) { drawCands(j.candidates); toast(`회의록에서 후보 ${j.added}건 — ${j.provider}${j.dropped.length ? ` · 근거 없어 버림 ${j.dropped.length}` : ''}`); } };
  document.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-cand]'); if (!b) return;
    const j = await post(`/api/run/${mid}/candidates/${b.dataset.cand}/${b.dataset.act}`, {block_id: b.dataset.block || '', dept_id: b.dataset.dept || ''});
    if (j) { drawCands(j.candidates); toast(j.msg); }
  });
  draw();
}
