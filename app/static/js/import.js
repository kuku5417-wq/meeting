// 가져오기 — 조각 판정(M13). 왼쪽 조각 목록 · 가운데 원본(글·그림) · 오른쪽 판정(후보·한 줄·부서). 판정하면 다음 조각으로,
// 끝나면 「반영하기」 한 번. 모든 동작은 바뀐 뒤 상태 전체를 받아 다시 그린다.
const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? '').replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
let S = JSON.parse($('#imState').textContent);
let cur = Math.max(0, S.pieces.findIndex((p) => !p.decision && !p.applied));
let tt;
function toast(msg) { const t = $('#toast'); t.innerHTML = `<span>${esc(msg)}</span>`; t.hidden = false; clearTimeout(tt); tt = setTimeout(() => { t.hidden = true; }, 6000); }
async function post(url, body) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})});
  const j = await r.json();
  if (!j.ok) { toast(j.err); return null; }
  S = j.state; return j;
}
const badge = (p) => p.applied ? `<span class="small ok-text">반영함${p.result ? ' → ' + esc(p.result) : ''}</span>` : p.decision ? `<span class="small">${esc(S.decisions[p.decision])}</span>` : '<span class="small muted">미판정</span>';

function draw() {
  const p = S.pieces[cur] || null, todo = S.pieces.filter((x) => x.decision && !x.applied && x.decision !== '').length;
  const decided = S.pieces.filter((x) => x.decision || x.applied).length;
  let h = `<div class="st-bar"><div class="st-ttl"><b>${esc(S.job.title)}</b><span class="small muted"> · ${esc(S.job.kind_label)}${S.job.received_at ? ' · ' + esc(S.job.received_at) : ''} · ${esc(S.job.status)} · 판정 ${decided}/${S.pieces.length}</span></div>
    <a class="btn sm" href="/import/${S.job.id}/original">원본</a><button class="btn primary" type="button" id="applyBtn"${todo ? '' : ' disabled'}>반영하기 ${todo}건</button></div>`;
  h += '<div class="im-grid"><nav class="st-pane" aria-label="조각"><div class="v-list">' + S.pieces.map((x, i) => `<button type="button" class="v-row im-pc${i === cur ? ' on' : ''}" data-i="${i}"${i === cur ? ' aria-current="true"' : ''}><span class="t"><span class="mono small">${x.no}</span> ${esc(x.title)}</span>${badge(x)}</button>`).join('') + '</div></nav>';
  if (!p) { $('#imp').innerHTML = h + '<p class="muted">조각이 없습니다.</p></div>'; return; }
  const imgs = p.images.map((k) => `<img src="/import/files/${esc(k)}" alt="${esc(p.title)} 그림" loading="lazy">`).join('');
  h += `<article class="panel im-orig" aria-label="원본"><span class="small muted">${p.no} · ${esc({slide: 'PPT 장', section: 'HTML 절', page: 'PDF 쪽', sheet: '엑셀 시트', mail: '메일 본문'}[p.kind] || p.kind)}</span><b>${esc(p.title)}</b>
    <pre class="im-text">${esc(p.text) || '<span class="muted">(글 없음)</span>'}</pre>${imgs ? `<div class="im-imgs">${imgs}</div><span class="small muted">그림은 반영할 때 그 이슈의 사진으로 붙습니다.</span>` : ''}</article>`;
  if (p.applied) {
    h += `<aside class="panel im-dec"><b>반영함</b>${p.result ? `<a class="btn sm" href="/issues?id=${esc(p.result)}">${esc(p.result)} 열기</a>` : '<span class="small muted">건너뜀</span>'}</aside></div>`;
    $('#imp').innerHTML = h; return;
  }
  const cands = p.candidates.map((c, k) => `<label class="im-cand"><input type="radio" name="cand" value="${esc(c.id)}"${(p.block_id ? p.block_id === c.id : k === 0) ? ' checked' : ''}><span><b>${esc(c.id)}</b> ${esc(c.title)} <span class="small muted">· ${esc(c.dept)}</span><br><span class="small muted">근거: ${esc(c.why.join(' · '))}</span></span></label>`).join('');
  h += `<aside class="panel im-dec" aria-label="판정"><b>이 조각을 어떻게 할까요?</b>
    <p class="v-sec">기존 이슈에 붙이기 — 후보 ${p.candidates.length}</p>${cands || '<p class="small muted">근거가 있는 후보가 없습니다. 이슈 ID 를 직접 적거나 새 이슈로 만드세요.</p>'}
    <label class="f">이슈 ID 직접<input type="text" id="bid" placeholder="ISS-2026-0001" value="${p.block_id && !p.candidates.some((c) => c.id === p.block_id) ? esc(p.block_id) : ''}"></label>
    <label class="f">이번 주 한 줄(붙일 때)<input type="text" id="line" value="${esc(p.line || p.title)}"></label>
    <button class="btn primary" type="button" data-d="link">붙이기</button>
    <p class="v-sec">새 이슈 — 조각 글을 메모로 저장하고 AI 정리</p>
    <label class="f">담당 부서<select id="dept">${S.depts.map((d) => `<option value="${esc(d.id)}"${d.id === (p.dept_id || S.job.dept_id) ? ' selected' : ''}>${esc(d.name)}</option>`).join('')}</select></label>
    <div class="row"><button class="btn" type="button" data-d="new">새 이슈로</button><button class="btn" type="button" data-d="skip">건너뛰기</button>${p.decision ? '<button class="btn sm" type="button" data-d="">판정 풀기</button>' : ''}</div>
    <span class="small muted">지금 판정: ${p.decision ? esc(S.decisions[p.decision]) : '없음'}</span></aside></div>`;
  $('#imp').innerHTML = h;
}
document.addEventListener('click', async (e) => {
  const pc = e.target.closest('[data-i]'), d = e.target.closest('[data-d]');
  if (pc) { cur = +pc.dataset.i; draw(); return; }
  if (d) {
    const p = S.pieces[cur], dec = d.dataset.d;
    const bid = ($('#bid')?.value || '').trim() || (document.querySelector('input[name=cand]:checked')?.value || '');
    const j = await post(`/api/import/pieces/${p.id}/decide`, {decision: dec, block_id: bid, line: $('#line')?.value || '', dept_id: $('#dept')?.value || ''});
    if (!j) return;
    if (dec) { const nx = S.pieces.findIndex((x, i) => i > cur && !x.decision && !x.applied); cur = nx >= 0 ? nx : cur; }
    draw(); return;
  }
  if (e.target.id === 'applyBtn') {
    const j = await post(`/api/import/${S.job.id}/apply`);
    if (!j) return;
    toast(`반영함 — 붙이기 ${j.linked.length} · 새 이슈 ${j.created.length} · 건너뜀 ${j.skipped}` + (j.errors.length ? ` · 못 한 것: ${j.errors.join(' / ')}` : ''));
    draw();
  }
});
addEventListener('keydown', (e) => {
  if (e.target.closest?.('input,textarea,select')) return;
  if (e.key === 'ArrowDown') { cur = Math.min(S.pieces.length - 1, cur + 1); draw(); }
  if (e.key === 'ArrowUp') { cur = Math.max(0, cur - 1); draw(); }
});
draw();
