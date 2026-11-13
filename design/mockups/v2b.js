// v2 B안 시안 공통 (2026-10-23) — 매끄러운 진행을 위한 작은 도구들. 시안 전용, 앱 코드 아님.
//  - toast(msg, undo): 확인 창 대신 「했습니다 · 되돌리기」
//  - fitStages(): 1920×1080 슬라이드(.stage)를 칸 크기에 맞춰 축소
//  - keys({next, prev, save}): J/K 다음·이전, Ctrl+S 저장
//  - esc(): HTML 이스케이프
export const $ = (s, el = document) => el.querySelector(s);
export const $$ = (s, el = document) => [...el.querySelectorAll(s)];
export const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

let tt = null;
export function toast(msg, undo) {
  let t = $('.toast');
  if (!t) { t = document.createElement('div'); t.className = 'toast'; t.setAttribute('role', 'status'); document.body.appendChild(t); }
  t.innerHTML = `<span>${esc(msg)}</span>` + (undo ? '<button type="button">되돌리기</button>' : '');
  t.hidden = false;
  if (undo) t.querySelector('button').onclick = () => { undo(); t.hidden = true; };
  clearTimeout(tt); tt = setTimeout(() => { t.hidden = true; }, 6000);
}

export function fitStages() {
  $$('.stage-wrap').forEach((w) => { const s = w.querySelector('.stage'); if (s) s.style.transform = `scale(${w.clientWidth / 1920})`; });
}
addEventListener('resize', fitStages);

export function keys({next, prev, save}) {
  addEventListener('keydown', (e) => {
    const typing = e.target.closest('input,textarea,select');
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); save && save(); return; }
    if (typing) return;
    if (e.key === 'j' && next) next();
    if (e.key === 'k' && prev) prev();
  });
}

// 머리줄 오른쪽 「A안 비교」 링크 — v2b-x.html ↔ v2-x.html
const a = $('#toA');
if (a) {
  const me = location.pathname.split('/').pop().replace(/^v2m-/, 'v2b-');
  const map = {'v2b-deck-edit.html': 'v2-dept-deck.html', 'v2b-studio.html': 'v2-dept-deck.html', 'v2b-import.html': 'v2-import.html'};
  a.href = map[me] || me.replace('v2b-', 'v2-');
}
