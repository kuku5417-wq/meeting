// 회의자료 보기(M11·M12) — 발행·제출판(또는 구성 중 자료)을 쪽마다 세로로 그린다. 왼쪽 쪽 목록이 따라온다. 읽기 전용.
import {esc, pageList, renderPage, fit, pageTitle} from './slides.js';

const $ = (s) => document.querySelector(s);
const V = JSON.parse($('#mvState').textContent), D = V.deck;
const P = pageList(D), total = P.length;
let pages = '', toc = '';
P.forEach((p, i) => {
  const n = i + 1, ch = p.t === 'item' && p.it.changed?.length ? `<p class="mv-chg">● 발행 뒤 변경 — ${esc(p.it.changed.join('·'))}</p>` : '';
  pages += `<section id="p${n}" class="stage-wrap">${ch}<div class="v-stage-wrap"><div class="v-stage">${renderPage(p, n, total, D, V.long_weeks)}</div></div></section>`;
  const label = p.t === 'cover' ? '표지' : p.t === 'dir' ? `지난 지시사항 ${D.directives.length}` : p.t === 'div' ? `<b>${esc(p.sec.dept)}</b> <span class="small muted">${esc(p.sec.state)}</span>` : esc(pageTitle(p.it));
  toc += `<a href="#p${n}" class="v-row${p.t === 'div' ? ' mv-sec' : ''}"><span class="n">${n}</span><span class="t">${label}</span>${ch ? '<span class="v-late">변경</span>' : ''}</a>`;
});
$('#pages').innerHTML = pages || '<p class="muted">장이 없습니다.</p>';
$('#toc').innerHTML = toc;
fit($('#pages'));
addEventListener('resize', () => fit($('#pages')));
// 지금 보는 쪽을 목록에 표시
const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) document.querySelectorAll('#toc a').forEach((a) => a.classList.toggle('on', a.getAttribute('href') === '#' + e.target.id)); }), {threshold: 0.5});
document.querySelectorAll('#pages section').forEach((x) => io.observe(x));
