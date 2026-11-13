// 작성 화면 붙이기 도우미 — 사진(바로 올리기·끌어다 놓기·Ctrl+V), 표 붙여넣기 미리보기, 근거 줄 이동, 선택칸 자동 제출.
// JS 가 없어도 각 폼은 그대로 동작한다(점진적 향상). 표 나누기 규칙은 app/services/tables.py parse_paste 와 같다.

document.documentElement.classList.add('js');

const MAX_ROWS = 20, MAX_COLS = 8;
const IMAGE = /^image\/(jpeg|png|webp)$/;

// ── 선택칸 바꾸면 바로 제출 (사진 칸 옮기기 등) ──
document.addEventListener('change', (e) => {
  const el = e.target.closest('[data-autosubmit]');
  if (el && el.form) el.form.requestSubmit();
});

// ── 사진 올리기 ──
function hintOf(card) { return card.querySelector('.attach-hint'); }

async function upload(blockId, files) {
  const card = document.getElementById(blockId);
  const list = [...files].filter((f) => IMAGE.test(f.type));
  const hint = card && hintOf(card);
  if (!list.length) {
    if (hint) hint.textContent = '사진 파일(JPG·PNG·WEBP)만 올릴 수 있습니다';
    return;
  }
  let last = null;
  for (const [i, f] of list.entries()) {
    if (hint) hint.textContent = `사진 올리는 중 ${i + 1}/${list.length} …`;
    const fd = new FormData();
    fd.append('file', f, f.name || `붙여넣은사진${i + 1}.png`);
    fd.append('role', 'main');
    try {
      last = await fetch(`/blocks/${encodeURIComponent(blockId)}/photos`, { method: 'POST', body: fd });
    } catch (err) {
      if (hint) hint.textContent = `사진을 올리지 못했습니다 — 네트워크를 확인해주세요 (${err.name})`;
      return;
    }
  }
  // 서버가 돌려준 화면(메시지 포함)으로 이동 — 같은 카드로 돌아온다
  // fetch 의 최종 URL 에는 #앵커가 빠지므로 카드 앵커를 다시 붙인다
  location.href = `${last && last.url ? last.url.split('#')[0] : location.pathname}#${blockId}`;
}

document.querySelectorAll('form[data-upload]').forEach((form) => {
  const input = form.querySelector('input[type=file]');
  input.addEventListener('change', () => { if (input.files.length) upload(form.dataset.upload, input.files); });
});

document.querySelectorAll('[data-attach]').forEach((card) => {
  card.addEventListener('dragover', (e) => {
    if ([...e.dataTransfer.types].includes('Files')) { e.preventDefault(); card.classList.add('drop-on'); }
  });
  card.addEventListener('dragleave', (e) => { if (!card.contains(e.relatedTarget)) card.classList.remove('drop-on'); });
  card.addEventListener('drop', (e) => {
    if (!e.dataTransfer.files.length) return;
    e.preventDefault();
    card.classList.remove('drop-on');
    upload(card.dataset.attach, e.dataTransfer.files);
  });
});

document.addEventListener('paste', (e) => {
  const files = [...(e.clipboardData?.files || [])].filter((f) => IMAGE.test(f.type));
  if (!files.length) return;
  const card = (e.target.closest && e.target.closest('[data-attach]')) || document.activeElement?.closest?.('[data-attach]');
  if (!card) return;                       // 카드 밖에서 붙여넣으면 아무것도 하지 않는다
  e.preventDefault();
  upload(card.dataset.attach, files);
});

// ── 표 붙여넣기 미리보기 ──
export function parsePaste(text) {
  let lines = (text || '').replace(/\r\n?/g, '\n').split('\n').filter((l) => l.trim());
  if (!lines.length) return { rows: [], cutRows: 0, cutCols: 0 };
  const sep = lines.some((l) => l.includes('\t')) ? '\t' : (lines.some((l) => l.includes('|')) ? '|' : ',');
  const rows = [];
  for (const l of lines) {
    let cells = l.split(sep).map((c) => c.trim());
    if (sep === '|') {
      if (cells[0] === '') cells = cells.slice(1);
      if (cells[cells.length - 1] === '') cells = cells.slice(0, -1);
      if (cells.every((c) => /^[-:\s]*$/.test(c))) continue;
    }
    rows.push(cells);
  }
  let width = Math.max(...rows.map((r) => r.length));
  const cutCols = Math.max(0, width - MAX_COLS), cutRows = Math.max(0, rows.length - MAX_ROWS);
  width = Math.min(width, MAX_COLS);
  return { rows: rows.slice(0, MAX_ROWS).map((r) => [...r, ...Array(width).fill('')].slice(0, width)), cutRows, cutCols };
}

const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function renderPreview(src) {
  const box = src.form.querySelector('[data-table-preview]');
  if (!box) return;
  const p = parsePaste(src.value);
  if (p.rows.length < 2) {
    box.innerHTML = src.value.trim() ? '<p class="muted small">머리글 포함 두 줄 이상이어야 표가 됩니다</p>' : '';
    return;
  }
  const [head, ...body] = p.rows;
  const cut = [p.cutRows && `${p.cutRows}행`, p.cutCols && `${p.cutCols}열`].filter(Boolean).join('·');
  box.innerHTML = `<p class="muted small">미리보기 — ${body.length}행 × ${head.length}열${cut ? ` · 최대 ${MAX_ROWS}행×${MAX_COLS}열이라 ${cut}은 빠집니다` : ''}</p>`
    + `<div class="tablewrap"><table><thead><tr>${head.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead>`
    + `<tbody>${body.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

document.querySelectorAll('[data-table-src]').forEach((src) => {
  src.addEventListener('input', () => renderPreview(src));
  // 탭 키로 칸을 나눌 수 있게 (붙여넣지 않고 직접 칠 때)
  src.addEventListener('keydown', (e) => {
    if (e.key === 'Tab' && !e.shiftKey && !e.ctrlKey && !e.altKey) {
      e.preventDefault();
      const { selectionStart: a, selectionEnd: b } = src;
      src.setRangeText('\t', a, b, 'end');
      renderPreview(src);
    }
  });
  const det = src.closest('details');
  if (det) det.addEventListener('toggle', () => { if (det.open) { renderPreview(src); src.focus(); } });
  renderPreview(src);
});

// ── 근거 「메모 N행」 → 지금 열린 메모면 새로 불러오지 않고 그 줄로 ──
const memoPanel = document.getElementById('memo');
document.addEventListener('click', (e) => {
  const a = e.target.closest('a.ev-link');
  if (!a || !memoPanel) return;
  const url = new URL(a.href);
  if (url.searchParams.get('memo') !== memoPanel.dataset.memo) return;   // 다른 메모 → 그대로 이동
  e.preventDefault();
  const line = document.getElementById(url.hash.slice(1));
  if (!line) return;
  history.replaceState(null, '', url.hash);
  document.querySelectorAll('.memo-lines li.hit').forEach((x) => x.classList.remove('hit'));
  line.classList.add('hit');
  memoPanel.scrollIntoView({ block: 'start', behavior: 'smooth' });
  line.scrollIntoView({ block: 'nearest' });
});

// ── 이슈 안 사진: 큰 사진 1장 + 썸네일 줄 — 누르면 페이지 이동 없이 바꾸고 ?photo= 로 기억 ──
document.querySelectorAll('[data-gallery]').forEach((g) => {
  g.addEventListener('click', (e) => {
    const t = e.target.closest('[data-show]');
    if (!t) return;
    const key = t.dataset.show;
    g.querySelectorAll('[data-ph]').forEach((f) => f.toggleAttribute('data-off', f.dataset.ph !== key));
    g.querySelectorAll('[data-show]').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.show === key)));
    const u = new URL(location.href);
    u.searchParams.set('photo', key);
    u.searchParams.delete('msg'); u.searchParams.delete('err');
    history.replaceState(null, '', u);
  });
});
