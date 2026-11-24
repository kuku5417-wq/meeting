// 자유 편집(결정 ⑦ 15-2) — 회의자료 한 장을 개체로 자유 배치한다.
// 좌표는 슬라이드와 같은 1920×1080. 캔버스는 .v-stage 가 scale 로 줄여 그리므로,
// 끌기·크기 조절은 화면 픽셀을 그 배율로 나눠 1920×1080 좌표로 되돌린다.
//
// 1차 필수로 고친 시안 버그 두 가지 (agent_trans 케이스 F2·F3)
//   - 되돌리기: **모든 변경**(옮기기·크기·서식·글·지우기)을 이력에 넣는다. Ctrl+Z / Ctrl+Shift+Z.
//   - 저장: 서버가 받았다고 답한 뒤에만 「저장됨」을 띄운다. 가짜 「저장됨」을 쓰지 않는다.
import {esc} from './slides.js';

const TONE = {fg: 'var(--slide-fg)', muted: 'var(--slide-muted)', decide: 'var(--slide-decide)',
  problem: 'var(--slide-problem)', issue: 'var(--slide-issue)', ok: 'var(--slide-ok)'};
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, Math.round(v)));
const W = 1920, H = 1080, MIN_W = 40, MIN_H = 24;

export const objects = (it) => (it.free?.objects || []).map((o) => ({...o, style: {...o.style}}));

function objHtml(o, i, selId) {
  const st = o.style || {};
  const base = `position:absolute;left:${o.x}px;top:${o.y}px;width:${o.w}px;height:${o.h}px;overflow:hidden;`;
  const on = o.id === selId ? ' on' : '';
  if (o.type === 'photo') {
    const img = o.photo ? `<img src="/photos/${esc(o.photo)}/render?block=${esc(o.block || '')}&w=1100" alt="${esc(o.label || '사진')}" style="width:100%;height:100%;object-fit:cover">`
      : '<span style="color:var(--slide-muted)">사진 없음</span>';
    return `<div class="fo${on}" data-o="${esc(o.id)}" data-i="${i}" style="${base}">${img}${o.id === selId ? '<b class="fh" data-h="1"></b>' : ''}</div>`;
  }
  const text = `font-size:${st.size || 30}px;font-weight:${st.bold ? 700 : 400};text-align:${st.align || 'left'};color:${TONE[st.tone] || TONE.fg};line-height:1.35;white-space:pre-wrap;`;
  const label = o.label ? `<i class="fol">${esc(o.label)}</i>` : '';
  return `<div class="fo${on}" data-o="${esc(o.id)}" data-i="${i}" style="${base}">${label}<div class="fot" style="${text}">${esc(o.text)}</div>${o.id === selId ? '<b class="fh" data-h="1"></b>' : ''}</div>`;
}

/** 장 하나를 개체로 그린 HTML (읽기·편집 공용). */
export function freeStage(it, selId) {
  const list = objects(it);
  if (!list.length) return '<div class="sb"><div class="st1">개체가 없습니다 — 속성에서 「자유 편집」을 다시 켜면 지금 형태로 초안을 만듭니다.</div></div>';
  return `<div class="fstage">${list.map((o, i) => objHtml(o, i, selId)).join('')}</div>`;
}

/** 넘친 개체 id 목록 — 글이 상자를 넘으면 회의 화면에서 사라진다(케이스 E3). */
export function overflowing(root) {
  return [...root.querySelectorAll('.fo')].filter((el) => {
    const t = el.querySelector('.fot');
    return t && t.scrollHeight > el.clientHeight + 2;
  }).map((el) => el.dataset.o);
}

/**
 * 편집 붙이기. frame 안의 .v-stage 를 편집기로 만든다.
 * opts: {save(objects, rev) -> Promise<rev|null>, onChange(objects), status(el)}
 */
export function mount(frame, it, opts) {
  const stage = frame.querySelector('.v-stage');
  if (!stage) return null;
  let list = objects(it);
  let selId = list[0]?.id || '';
  let rev = it.free?.rev ?? 0;
  const past = [], future = [];
  let timer = null, saving = false;

  const scale = () => (stage.getBoundingClientRect().width / W) || 1;
  const find = (id) => list.find((o) => o.id === id);

  function paint() {
    stage.innerHTML = freeStage({free: {objects: list}}, selId);
    const over = overflowing(stage);
    over.forEach((id) => stage.querySelector(`[data-o="${CSS.escape(id)}"]`)?.classList.add('over'));
    frame.querySelectorAll('.fo-over').forEach((el) => { el.textContent = over.length ? `넘침 ${over.length}` : ''; el.hidden = !over.length; });
    opts.onChange?.(list, selId, over);
  }

  function push() {                       // 바꾸기 전에 현재 판을 이력에 — 서식 변경도 포함(버그 F2)
    past.push(JSON.stringify(list));
    if (past.length > 100) past.shift();
    future.length = 0;
  }

  function setStatus(txt, bad) {
    const el = frame.querySelector('.fo-save') || opts.status;
    if (el) { el.textContent = txt; el.classList.toggle('bad', !!bad); }
  }

  async function flush() {
    if (saving) return;
    saving = true;
    setStatus('저장 중…');
    const got = await opts.save(list, rev);
    saving = false;
    if (got == null) { setStatus('저장 실패 — 다시 시도합니다', true); schedule(2000); return; }
    rev = got;
    setStatus('저장됨');
  }
  function schedule(ms = 800) { clearTimeout(timer); timer = setTimeout(flush, ms); }

  function change(fn) { push(); fn(); paint(); schedule(); }

  function undo(redo) {
    const from = redo ? future : past, to = redo ? past : future;
    if (!from.length) return;
    to.push(JSON.stringify(list));
    list = JSON.parse(from.pop());
    if (!find(selId)) selId = list[0]?.id || '';
    paint(); schedule(300);
  }

  // 고르기 · 옮기기 · 크기
  let dragging = false;
  stage.addEventListener('pointerdown', onDown);
  stage.addEventListener('mousedown', (e) => { if (!dragging) onDown(e); });
  function onDown(e) {
    const el = e.target.closest('.fo');
    if (!el) { selId = ''; paint(); return; }
    const o = find(el.dataset.o);
    if (!o) return;
    selId = o.id;
    const handle = e.target.classList.contains('fh');
    const k = scale(), x0 = e.clientX, y0 = e.clientY, b = {x: o.x, y: o.y, w: o.w, h: o.h};
    let moved = false;
    paint();
    const move = (ev) => {
      const dx = (ev.clientX - x0) / k, dy = (ev.clientY - y0) / k;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 2) return;
      if (!moved) { push(); moved = true; }
      const t = find(selId); if (!t) return;
      if (handle) { t.w = clamp(b.w + dx, MIN_W, W - t.x); t.h = clamp(b.h + dy, MIN_H, H - t.y); }
      else { t.x = clamp(b.x + dx, 0, W - t.w); t.y = clamp(b.y + dy, 0, H - t.h); }
      paint();
    };
    const up = () => {
      // 창 전체에서 듣는다 — 끌다가 개체·캔버스 밖으로 나가도 놓치지 않는다
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseup', up);
      if (moved) schedule();
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('mousemove', move);     // 포인터 이벤트가 오지 않는 환경 대비
    window.addEventListener('mouseup', up);
    dragging = true;
    setTimeout(() => { dragging = false; }, 0);
    e.preventDefault();
  }

  // 글 고치기 — 두 번 누르면 그 자리에서
  stage.addEventListener('dblclick', (e) => {
    const el = e.target.closest('.fo'); const o = el && find(el.dataset.o);
    if (!o || o.type === 'photo') return;
    const t = el.querySelector('.fot');
    t.contentEditable = 'true'; t.focus();
    const before = o.text;
    const done = () => {
      t.contentEditable = 'false';
      const now = t.innerText.replace(/ /g, ' ').trimEnd();
      if (now !== before) change(() => { o.text = now; });
      else paint();
    };
    t.addEventListener('blur', done, {once: true});
  });

  const api = {
    get list() { return list; },
    get sel() { return find(selId) || null; },
    select(id) { selId = id; paint(); },
    style(k, v) { const o = find(selId); if (!o) return; change(() => { o.style = {...o.style, [k]: v}; }); },
    text(v) { const o = find(selId); if (!o) return; change(() => { o.text = v; }); },
    label(v) { const o = find(selId); if (!o) return; change(() => { o.label = v; }); },
    add() {
      change(() => {
        const id = 'o' + (Date.now() % 100000);
        list.push({id, type: 'text', x: 200, y: 200, w: 600, h: 120, text: '새 글', label: '', link: null,
          style: {size: 30, bold: false, align: 'left', tone: 'fg'}});
        selId = id;
      });
    },
    remove() { const o = find(selId); if (!o) return; change(() => { list = list.filter((x) => x !== o); selId = list[0]?.id || ''; }); },
    copy() {
      // 케이스 A5 — 복사본은 **연결 없는 자유 글**. 한 칸에 개체 둘이 연결되면 어느 쪽이 정답인지 모호해진다.
      const o = find(selId); if (!o) return;
      change(() => {
        const id = 'o' + (Date.now() % 100000);
        list.push({...o, id, link: null, x: Math.min(o.x + 40, 1920 - o.w), y: Math.min(o.y + 40, 1080 - o.h), style: {...o.style}});
        selId = id;
      });
    },
    undo: () => undo(false),
    redo: () => undo(true),
    canUndo: () => past.length > 0,
    flush,
    destroy() { clearTimeout(timer); },
  };

  function keys(e) {
    if (e.target.isContentEditable || /^(INPUT|TEXTAREA)$/.test(e.target.tagName)) return;
    const z = (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z';
    if (z) { e.preventDefault(); e.shiftKey ? api.redo() : api.undo(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); api.redo(); return; }
    if (e.key === 'Delete' && selId) { e.preventDefault(); api.remove(); }
  }
  document.addEventListener('keydown', keys);
  const _destroy = api.destroy;
  api.destroy = () => { document.removeEventListener('keydown', keys); _destroy(); };

  paint();
  return api;
}
