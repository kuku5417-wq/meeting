// 최종 시안 스튜디오 공통(2026-10-23) — 도구줄 메뉴, 장(슬라이드) 형태별 그리기, 캔버스 프레임, 형태 썸네일.
// v2b.js(toast·fitStages·keys·esc)와 v2b-data.js(가상 데이터·itemSlide·coverSlide·ptag) 위에 얹는다.
import {esc} from './v2b.js';
import {KIND, ptag, byId, itemSlide} from './v2b-data.js';

export const FORMS = {detail: '상세 한 장', card: '카드', photo: '사진 강조', line: '한 줄'};
const MENU = [['home', '홈', 'v2s-home.html'], ['issue', '이슈', 'v2s-issue.html'], ['meet', '회의', 'v2s-meetings.html'], ['metric', '지표', 'v2-metrics.html'], ['know', '지식창고', '#'], ['hub', '장비 허브', '#']];
// 도구줄 — 메뉴 탭 · 제목 · 동작(각 화면이 #act 를 채운다) · B안 비교 링크
export function toolbar(active, bLink) {
  const tb = document.getElementById('tb');
  tb.innerHTML = `<a class="brand" href="v2s-home.html">회의·지식</a><nav class="menu" aria-label="메뉴">${MENU.map(([k, l, h]) => `<a href="${h}"${k === active ? ' aria-current="page"' : ''}>${l}</a>`).join('')}</nav>
    <div class="ttl"><b id="title"></b><span id="sub"></span></div><div class="act" id="act"></div>${bLink ? `<a class="ab" href="${bLink}">B안 보기</a>` : ''}`;
}
// 장 한 장(1920 좌표) — 형태: 상세 한 장 · 카드 · 사진 강조 · 한 줄. 요약 항목(ids)은 연결 이슈 목록
export function slide(it, n, total, title) {
  const d = byId(it.id), p = ptag(d), pre = p && it.tag !== false ? `<b style="color:var(--t-decide)">[${esc(p)}]</b> ` : '';
  const head = `<div class="sh"><span>${esc(title)}</span><span>${esc(it.ids ? '요약 · ' + it.ids.length + '건' : d.dept)}</span></div>`;
  const foot = `<div class="sf"><span>${n} / ${total} · ${esc(it.ids ? it.ids.map((x) => byId(x).hull).join('·') : d.hull + ' · ' + d.ev + (d.dd !== null ? ' D-' + d.dd : ''))}</span><span>${esc(FORMS[it.form] || '')}</span></div>`;
  if (it.ids) return head + `<div class="sb"><div class="st1">${esc(it.line)}</div>${it.ids.map((x) => { const e = byId(x); return `<div class="li ${e.t}"><b>${esc(e.title)}</b>${esc(e.wk || e.last)}</div>`; }).join('')}</div>` + foot;
  const t = `<div class="st1"><span class="lab" style="background:var(--t-${d.t})">${KIND[d.t]}</span>${esc(d.title)}</div>`;
  const dec = d.dec ? `<div class="decide"><b>결정 필요</b> ${esc(d.dec)}</div>` : '';
  if (it.form === 'detail') return itemSlide({d, line: it.line}, n, total, null, title).replace(/<div style="font-size:30px">[^]*?<\/div>/, `<div style="font-size:30px">${pre}${esc(it.line)}</div>`);
  if (it.form === 'photo') return head + `<div class="sb">${t}<div style="display:grid;grid-template-columns:1.3fr 1fr;gap:32px"><div style="background:#e3e8ef;border-radius:16px;min-height:520px;display:grid;place-items:center;color:#5d6e86;font-size:30px">사진 · 마커</div><div style="display:grid;gap:20px;align-content:start;font-size:30px">${pre}${esc(it.line)}${dec}</div></div></div>` + foot;
  if (it.form === 'line') return head + `<div class="sb" style="align-content:center">${t}<div style="font-size:40px;line-height:1.4">${pre}${esc(it.line)}</div></div>` + foot;
  return head + `<div class="sb">${t}<div style="display:grid;grid-template-columns:1fr 360px;gap:28px"><div style="display:grid;gap:16px;font-size:30px;align-content:start">${pre}${esc(it.line)}<div class="grid4"><div><b>담당</b>${esc(d.dept)}</div><div><b>상태</b>${d.st === 'req' ? '종결 요청' : '진행'}</div></div></div><div style="background:#e3e8ef;border-radius:16px;min-height:300px"></div></div>${dec}</div>` + foot;
}
// 캔버스 프레임 — 라벨 + 1920 좌표 슬라이드(폭 w px 로 축소)
export const frame = (html, label, cls = '', attrs = '', w = 560) => `<div class="frame ${cls}" ${attrs} style="width:${w}px"><span class="lbl">${label}</span><div class="stage-wrap"><div class="stage">${html}</div></div></div>`;
// 형태 썸네일(속성 칸)
export const mini = (k) => ({detail: '<i></i><i class="s"></i><i class="b"></i><i class="b"></i>', card: '<i></i><i class="s"></i><i class="b" style="width:40%;justify-self:end;height:22px"></i>', photo: '<i></i><i class="b" style="height:30px;width:60%"></i>', line: '<i style="margin-top:12px"></i><i class="s"></i>'}[k]);
export const formPicker = (cur) => `<div class="vgrid">${Object.entries(FORMS).map(([k, v], n) => `<button type="button" data-form="${k}" aria-pressed="${k === cur}"><span class="mini">${mini(k)}</span>${n + 1}. ${v}</button>`).join('')}</div>`;
