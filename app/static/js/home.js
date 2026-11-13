// M9 홈 — 이번 주 한 줄을 여기서 저장(Enter·저장·변동 없음)하고 다음 칸으로. 다 끝나면 「마쳤습니다」.
const $$ = (s) => [...document.querySelectorAll(s)];
async function saveLine(row, text) {
  const inp = row.querySelector('[data-line]');
  const r = await fetch(`/api/issues/${inp.dataset.id}/line`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({text})});
  const j = await r.json();
  const fin = row.querySelector('.v-fin');
  if (!j.ok) { fin.hidden = false; fin.textContent = j.err; fin.classList.add('bad'); inp.focus(); return; }
  row.classList.add('fin'); fin.hidden = false; fin.classList.remove('bad'); fin.textContent = `✓ 이번 주 한 줄 저장 — 「${text}」`;
  row.querySelector('.v-line').hidden = true;
  const next = $$('[data-line]').find((x) => !x.closest('.fin'));
  if (next) next.focus();
  const left = $$('.v-task').filter((x) => !x.classList.contains('fin')).length;
  document.getElementById('qN').textContent = left;
  if (!left) document.getElementById('allDone').hidden = false;
}
$$('.v-task').forEach((row) => {
  const inp = row.querySelector('[data-line]');
  if (!inp) return;
  inp.addEventListener('keydown', (e) => { if (e.key === 'Enter' && inp.value.trim()) { e.preventDefault(); saveLine(row, inp.value.trim()); } });
  row.querySelector('[data-save]').addEventListener('click', () => (inp.value.trim() ? saveLine(row, inp.value.trim()) : inp.focus()));
  row.querySelector('[data-same]').addEventListener('click', () => saveLine(row, '변동 없음'));
});
$$('[data-line]')[0]?.focus({preventScroll: true});
