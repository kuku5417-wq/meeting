// 사진 마킹 편집기 (기능 8) — Konva 로 그리고, 저장은 이 앱의 작은 JSON 으로 한다(app/services/photos.py 설명 참고).
// 좌표는 전부 「EXIF 회전을 적용한 원본」 픽셀 좌표. 원본 파일은 건드리지 않는다.
// 2026-10-21: 선택·이동·크기 조정·삭제, 자르기 영역 조정, 글자 바로 입력·고치기, 다시 실행, 단축키, 저장하고 돌아가기.
// 같은 날 속도 보정: 줄인 작업용 사진(data.src, 좌표는 원본 픽셀 그대로) + 레이어 3장(사진·도형·그리기 미리보기)
//   — 4000×3000 사진에서 끄는 동안 사진을 매번 다시 그리고, 고칠 때마다 원본 크기로 cache 하던 것을 없앴다.
/* global Konva */

const data = JSON.parse(document.getElementById('ped-data').textContent);
const W = data.width, H = data.height;
const doc = structuredClone(data.doc);
doc.base = Object.assign({ rotate: 0, crop: null, brightness: 0 }, doc.base || {});
doc.shapes = doc.shapes || [];
doc.markers = doc.markers || [];

const LINE = Math.max(3, Math.round(Math.min(W, H) / 150));      // 선 굵기 — 사진 크기에 비례
const TEXT = Math.max(16, Math.round(Math.min(W, H) / 18));
const MARK_R = Math.max(14, Math.round(Math.min(W, H) / 30));     // 서버 합성(compose)과 같은 반지름
const MARK_COLOR = '#d4402a';
const HIT = LINE * 5;                                              // 가는 선도 잡기 쉽게
const MIN = Math.min(W, H) * 0.01;
const DRAG_TOOLS = new Set(['arrow', 'circle', 'rect', 'free', 'mosaic', 'inset', 'crop']);

let tool = 'marker';
let color = data.colors[0];
let dirty = false;
let sel = null;                 // { kind: 'shape' | 'marker', idx }
let pendingCrop = null;         // 자르기 도구에서 맞추는 중인 영역 [x, y, w, h]
const undo = [], redo = [];

const $ = (id) => document.getElementById(id);
const msg = (t, tone = 'ok') => {
  const m = $('msg'); m.textContent = t;
  m.style.color = { ok: 'var(--ok)', bad: 'var(--danger)', warn: 'var(--signal)' }[tone];
};
const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
const snapshot = () => { undo.push(JSON.stringify(doc)); if (undo.length > 100) undo.shift(); redo.length = 0; };
const changed = () => { dirty = true; $('saveBtn').textContent = '마킹 저장 •'; msg('저장하지 않은 변경이 있습니다', 'warn'); };

// ── 무대 ─────────────────────────────────────────────
const holder = $('stage');
const stage = new Konva.Stage({ container: holder, width: 10, height: 10 });
const bgLayer = new Konva.Layer({ listening: false });      // 사진 — 회전·밝기·창 크기가 바뀔 때만 다시 그림
const layer = new Konva.Layer();                             // 도형·마커·손잡이
const draftLayer = new Konva.Layer({ listening: false });   // 끄는 동안의 미리보기 — 이것만 자주 다시 그림
stage.add(bgLayer, layer, draftLayer);
const bg = new Konva.Group(), content = new Konva.Group(), draft = new Konva.Group();
bgLayer.add(bg); layer.add(content); draftLayer.add(draft);
const imgEl = new Image();
let imageNode = null;
let K = 1;                            // 작업용 사진 픽셀 / 원본 픽셀 (모자이크·인셋 잘라 쓰기 좌표에 곱한다)
const marks = new Konva.Group();      // 도형·마커·자르기 표시 — 다시 그릴 때 통째로 비운다
content.add(marks);
const tr = new Konva.Transformer({
  rotateEnabled: false, flipEnabled: false, ignoreStroke: true, keepRatio: false,
  anchorSize: 14, anchorCornerRadius: 3, borderStroke: '#0b6e78', anchorStroke: '#0b6e78', anchorStrokeWidth: 2,
  boundBoxFunc: (oldB, newB) => (Math.abs(newB.width) < 8 || Math.abs(newB.height) < 8 ? oldB : newB),
});
layer.add(tr);
let scale = 1;

function fit() {
  const r = doc.base.rotate % 360;
  const sideways = r === 90 || r === 270;
  const cw = holder.clientWidth || 600;
  const maxH = Math.max(320, window.innerHeight * 0.75);          // 사진 전체가 한 화면에 들어오게
  scale = Math.min(cw / (sideways ? H : W), maxH / (sideways ? W : H));
  stage.size({ width: (sideways ? H : W) * scale, height: (sideways ? W : H) * scale });
  const pos = { 0: { x: 0, y: 0 }, 90: { x: H * scale, y: 0 }, 180: { x: W * scale, y: H * scale }, 270: { x: 0, y: W * scale } }[r];
  [bg, content, draft].forEach((g) => { g.scale({ x: scale, y: scale }); g.rotation(r); g.position(pos); });
  applyBright();
  stage.batchDraw();
}

function applyBright() {
  // 밝기 필터는 cache 가 있어야 동작한다 — 화면 크기 해상도로만 만든다(원본 크기 cache 금지)
  if (!imageNode) return;
  const b = doc.base.brightness || 0;
  if (b) {
    imageNode.cache({ pixelRatio: Math.min(1, scale * (window.devicePixelRatio || 1)) });
    imageNode.filters([Konva.Filters.Brighten]);
    imageNode.brightness(b);
  } else { imageNode.clearCache(); imageNode.filters([]); }
  bgLayer.batchDraw();
}

function pointer() {
  const p = content.getRelativePointerPosition();
  return { x: clamp(p.x, 0, W), y: clamp(p.y, 0, H) };
}

// ── 그리기 ───────────────────────────────────────────
function shapeNode(sh) {
  const stroke = { stroke: sh.color, strokeWidth: sh.width, lineCap: 'round', lineJoin: 'round', hitStrokeWidth: HIT };
  switch (sh.type) {
    case 'arrow': { const p = sh.points; return new Konva.Arrow({ points: [p[0], p[1], p[p.length - 2], p[p.length - 1]], fill: sh.color, pointerLength: sh.width * 4, pointerWidth: sh.width * 4, ...stroke }); }
    case 'free': return new Konva.Line({ points: sh.points, tension: 0.3, ...stroke });
    case 'circle': return new Konva.Circle({ x: sh.x, y: sh.y, radius: sh.r, fill: 'rgba(0,0,0,0)', ...stroke });   // 안쪽도 잡히게
    case 'rect': return new Konva.Rect({ x: sh.x, y: sh.y, width: sh.w, height: sh.h, fill: 'rgba(0,0,0,0)', ...stroke });
    case 'text': return new Konva.Text({ x: sh.x, y: sh.y, text: sh.text, fontSize: sh.size, fill: sh.color, fontStyle: 'bold', stroke: '#ffffff', strokeWidth: Math.max(1, sh.size / 14), fillAfterStrokeEnabled: true, fontFamily: 'Meeting Sans KR, Malgun Gothic, sans-serif' });
    case 'mosaic': {
      const n = new Konva.Image({ image: imgEl, x: sh.x, y: sh.y, width: sh.w, height: sh.h, crop: { x: sh.x * K, y: sh.y * K, width: sh.w * K, height: sh.h * K } });
      n.cache(); n.filters([Konva.Filters.Pixelate]); n.pixelSize(Math.max(6, Math.round(Math.min(sh.w, sh.h) / 8)));
      return n;
    }
    case 'inset': {
      const [sx, sy, sw, shh] = sh.src, [dx, dy, dw, dh] = sh.dst;
      const g = new Konva.Group();
      g.add(new Konva.Line({ points: [sx + sw / 2, sy + shh / 2, dx + dw / 2, dy + dh / 2], stroke: sh.color, strokeWidth: 2, dash: [8, 6], listening: false }));
      g.add(new Konva.Rect({ name: 'src', x: sx, y: sy, width: sw, height: shh, stroke: sh.color, strokeWidth: 2, hitStrokeWidth: HIT }));
      const d = new Konva.Group({ name: 'dst', x: dx, y: dy });
      d.add(new Konva.Image({ image: imgEl, x: 0, y: 0, width: dw, height: dh, crop: { x: sx * K, y: sy * K, width: sw * K, height: shh * K } }));
      d.add(new Konva.Rect({ x: 0, y: 0, width: dw, height: dh, stroke: sh.color, strokeWidth: sh.width }));
      g.add(d);
      return g;
    }
  }
  return null;
}

function markerNode(mk) {
  const g = new Konva.Group({ x: mk.x, y: mk.y });
  g.add(new Konva.Circle({ radius: MARK_R, fill: MARK_COLOR, stroke: '#ffffff', strokeWidth: Math.max(2, MARK_R / 6) }));
  g.add(new Konva.Text({ text: String(mk.no), fontSize: MARK_R * 1.2, fill: '#ffffff', fontStyle: 'bold', width: MARK_R * 2, height: MARK_R * 2, offsetX: MARK_R, offsetY: MARK_R, align: 'center', verticalAlign: 'middle' }));
  return g;
}

function cropOverlay(c) {
  const g = new Konva.Group({ listening: false });
  const [x, y, w, h] = c;
  const dim = { fill: 'rgba(0,0,0,0.45)' };
  g.add(new Konva.Rect({ x: 0, y: 0, width: W, height: y, ...dim }));
  g.add(new Konva.Rect({ x: 0, y: y + h, width: W, height: H - y - h, ...dim }));
  g.add(new Konva.Rect({ x: 0, y, width: x, height: h, ...dim }));
  g.add(new Konva.Rect({ x: x + w, y, width: W - x - w, height: h, ...dim }));
  g.add(new Konva.Rect({ x, y, width: w, height: h, stroke: '#ffffff', strokeWidth: LINE / 2, dash: [10, 6] }));
  return g;
}

// ── 선택·이동·크기 → doc 에 되쓰기 ─────────────────────
const isSel = (kind, idx) => sel && sel.kind === kind && sel.idx === idx;

function nodeToShape(sh, n) {
  const sx = n.scaleX(), sy = n.scaleY(), x = n.x(), y = n.y();
  switch (sh.type) {
    case 'rect': case 'mosaic': {
      const w = Math.abs(n.width() * sx), h = Math.abs(n.height() * sy);
      sh.x = clamp(Math.min(x, x + n.width() * sx), 0, W); sh.y = clamp(Math.min(y, y + n.height() * sy), 0, H);
      sh.w = Math.min(w, W - sh.x); sh.h = Math.min(h, H - sh.y);
      break;
    }
    case 'circle': sh.x = clamp(x, 0, W); sh.y = clamp(y, 0, H); sh.r = Math.max(MIN, n.radius() * Math.max(Math.abs(sx), Math.abs(sy))); break;
    case 'text': sh.x = clamp(x, 0, W); sh.y = clamp(y, 0, H); sh.size = Math.round(clamp(sh.size * Math.abs(sy), 8, 400)); break;
    case 'free': case 'arrow': {
      const pts = n.points();
      const out = [];
      for (let i = 0; i < pts.length; i += 2) out.push(clamp(pts[i] * sx + x, 0, W), clamp(pts[i + 1] * sy + y, 0, H));
      if (sh.type === 'arrow') { const old = sh.points; sh.points = old.length > 4 ? [out[0], out[1], ...old.slice(2, -2), out[2], out[3]] : out; } else sh.points = out;
      break;
    }
  }
}

// 누르는 순간 바로 끌 수 있게: 선택 도구에서는 모든 개체가 끌리고, 선택 표시는 손을 뗄 때 그린다
let selDirty = false;
let lastDown = { idx: -1, t: 0 };

function grab(e, kind, idx) {
  if (tool === 'crop') return false;
  if (tool !== 'select' && !isSel(kind, idx)) return false;
  e.cancelBubble = true;
  if (!isSel(kind, idx)) { sel = { kind, idx }; selDirty = true; }
  return true;
}

function makeEditable(n, kind, idx) {
  n.draggable(tool === 'select' || isSel(kind, idx));
  n.on('pointerdown', (e) => {
    if (!grab(e, kind, idx)) return;
    if (kind === 'shape' && doc.shapes[idx].type === 'text') {           // 글자는 두 번 눌러 고치기
      const now = Date.now();
      if (lastDown.idx === idx && now - lastDown.t < 450) { lastDown = { idx: -1, t: 0 }; selDirty = false; editText(idx); return; }
      lastDown = { idx, t: now };
    }
  });
  n.on('dragstart', () => snapshot());
  n.on('dragend', () => {
    selDirty = false;
    if (kind === 'marker') { const mk = doc.markers[idx]; mk.x = clamp(n.x(), 0, W); mk.y = clamp(n.y(), 0, H); }
    else nodeToShape(doc.shapes[idx], n);
    render(); changed();
  });
}

function attachInset(g, idx) {
  // 확대본(dst)은 이동·크기, 원본 위치 상자(src)는 이동만
  const sh = doc.shapes[idx];
  const dst = g.findOne('.dst'), src = g.findOne('.src');
  [dst, src].forEach((part) => {
    part.on('pointerdown', (e) => { grab(e, 'shape', idx); });
    part.draggable(tool === 'select' || isSel('shape', idx));
    part.on('dragstart', () => snapshot());
  });
  dst.on('dragend transformend', () => {
    sh.dst = [clamp(dst.x(), 0, W), clamp(dst.y(), 0, H), Math.max(MIN, sh.dst[2] * Math.abs(dst.scaleX())), Math.max(MIN, sh.dst[3] * Math.abs(dst.scaleY()))];
    render(); changed();
  });
  dst.on('transformstart', () => snapshot());
  src.on('dragend', () => { sh.src = [clamp(src.x(), 0, W - sh.src[2]), clamp(src.y(), 0, H - sh.src[3]), sh.src[2], sh.src[3]]; render(); changed(); });
  return dst;
}

function arrowHandles(n, idx) {
  // 화살표는 양 끝점 손잡이로 고친다
  const sh = doc.shapes[idx];
  const p = sh.points, ends = [[0, 1], [p.length - 2, p.length - 1]];
  ends.forEach(([ix, iy]) => {
    const h = new Konva.Circle({ x: p[ix], y: p[iy], radius: 9 / scale, fill: '#ffffff', stroke: '#0b6e78', strokeWidth: 2 / scale, draggable: true });
    h.on('pointerdown', (e) => { e.cancelBubble = true; });
    h.on('dragstart', () => snapshot());
    h.on('dragmove', () => {
      const pts = n.points();
      if (ix === 0) { pts[0] = h.x(); pts[1] = h.y(); } else { pts[2] = h.x(); pts[3] = h.y(); }
      n.points(pts); layer.batchDraw();
    });
    h.on('dragend', () => { sh.points[ix] = clamp(h.x(), 0, W); sh.points[iy] = clamp(h.y(), 0, H); render(); changed(); });
    marks.add(h);
  });
}

let pendingRect = null;

function render() {
  marks.destroyChildren();
  tr.nodes([]);
  let trNode = null;
  const order = doc.shapes.map((s, i) => i).sort((a, b) => (doc.shapes[a].type === 'mosaic' ? -1 : 0) - (doc.shapes[b].type === 'mosaic' ? -1 : 0));
  order.forEach((i) => {                                   // 모자이크 먼저(아래), 나머지는 그린 순서
    const sh = doc.shapes[i];
    const n = shapeNode(sh);
    if (!n) return;
    marks.add(n);
    if (sh.type === 'inset') { const dst = attachInset(n, i); if (isSel('shape', i)) trNode = dst; return; }
    makeEditable(n, 'shape', i);
    if (isSel('shape', i)) {
      if (sh.type === 'arrow') arrowHandles(n, i);
      else trNode = n;
      n.on('transformstart', () => snapshot());
      n.on('transformend', () => { nodeToShape(sh, n); render(); changed(); });
    }
  });
  doc.markers.forEach((mk, i) => {
    mk.no = i + 1;
    const g = markerNode(mk);
    if (isSel('marker', i)) g.add(new Konva.Circle({ radius: MARK_R * 1.35, stroke: '#0b6e78', strokeWidth: 3 / scale, dash: [6 / scale, 4 / scale] }));
    makeEditable(g, 'marker', i);
    marks.add(g);
  });
  if (tool === 'crop') {
    const c = pendingCrop || doc.base.crop;
    if (c) {
      marks.add(cropOverlay(c));
      pendingRect = new Konva.Rect({ x: c[0], y: c[1], width: c[2], height: c[3], stroke: '#ffffff', strokeWidth: 1, draggable: true, fill: 'rgba(255,255,255,0.01)' });
      const sync = () => {
        const s2 = [pendingRect.x(), pendingRect.y(), pendingRect.width() * pendingRect.scaleX(), pendingRect.height() * pendingRect.scaleY()];
        pendingCrop = [clamp(s2[0], 0, W), clamp(s2[1], 0, H), Math.min(Math.abs(s2[2]), W - clamp(s2[0], 0, W)), Math.min(Math.abs(s2[3]), H - clamp(s2[1], 0, H))];
      };
      pendingRect.on('pointerdown', (e) => { e.cancelBubble = true; });
      pendingRect.on('dragend transformend', () => { sync(); render(); });
      marks.add(pendingRect);
      trNode = pendingRect;
    }
  } else if (doc.base.crop) marks.add(cropOverlay(doc.base.crop));
  if (trNode) {
    const t = trNode.className === 'Text' || trNode.className === 'Circle';
    tr.keepRatio(t);
    tr.enabledAnchors(t ? ['top-left', 'top-right', 'bottom-left', 'bottom-right'] : ['top-left', 'top-center', 'top-right', 'middle-right', 'bottom-right', 'bottom-center', 'bottom-left', 'middle-left']);
    tr.nodes([trNode]);
    tr.moveToTop();
  }
  $('uncropBtn').hidden = !doc.base.crop;
  $('cropbar').hidden = tool !== 'crop';
  $('bright').value = doc.base.brightness || 0;
  $('delBtn').disabled = !sel;
  layer.batchDraw();
  renderList();
}

function select(kind, idx) { sel = kind ? { kind, idx } : null; render(); }

function deleteSel() {
  if (!sel) return;
  snapshot();
  if (sel.kind === 'marker') doc.markers.splice(sel.idx, 1); else doc.shapes.splice(sel.idx, 1);
  sel = null; render(); changed();
}

// ── 마커 목록 ────────────────────────────────────────
function renderList() {
  const box = $('mlist');
  if (box.contains(document.activeElement) && document.activeElement.tagName === 'INPUT') return;   // 입력 중엔 다시 그리지 않음
  box.innerHTML = '';
  doc.markers.forEach((mk, i) => {
    const row = document.createElement('div');
    row.className = 'mrow' + (isSel('marker', i) ? ' on' : '');
    const opts = ['<option value="">부위 고르기 (목록에 없으면 설명만 적기)</option>'].concat(
      data.components.map(([id, name]) => `<option value="${id}"${mk.component_id === id ? ' selected' : ''}>${name}</option>`)).join('');
    row.innerHTML = `<button type="button" class="num" aria-label="마커 ${i + 1} 선택">${i + 1}</button>
      <label class="sr" for="ml${i}">마커 ${i + 1} 설명</label><input id="ml${i}" type="text" maxlength="100" placeholder="설명 (예: 씰 하우징 누유)">
      <label class="sr" for="mc${i}">마커 ${i + 1} 부위</label><select id="mc${i}" class="${mk.component_id || (mk.label || '').trim() ? '' : 'need'}">${opts}</select>
      <button class="btn sm" type="button" aria-label="마커 ${i + 1} 지우기">지우기</button>`;
    const [pick, input, select_, del] = [row.querySelector('.num'), row.querySelector('input'), row.querySelector('select'), row.querySelector('.btn')];
    input.value = mk.label || '';
    pick.addEventListener('click', () => select('marker', i));
    const need = () => { select_.className = mk.component_id || (mk.label || '').trim() ? '' : 'need'; };   // 부위나 설명 중 하나면 통과
    input.addEventListener('input', () => { mk.label = input.value; need(); changed(); });
    select_.addEventListener('change', () => { snapshot(); mk.component_id = select_.value || null; need(); changed(); });
    del.addEventListener('click', () => { snapshot(); doc.markers.splice(i, 1); sel = null; render(); changed(); });
    box.appendChild(row);
  });
}

// ── 글자: 누른 자리에서 바로 입력, 두 번 눌러 고치기 ─────
let editor = null;

function textBox(x, y, value, done) {
  if (editor) editor.remove();
  const abs = content.getAbsoluteTransform().point({ x, y });
  const box = holder.getBoundingClientRect();
  const el = document.createElement('input');
  el.type = 'text'; el.maxLength = 100; el.value = value; el.className = 'ped-textin';
  el.setAttribute('aria-label', '넣을 글자 (Enter 확정, Esc 취소)');
  el.style.left = `${box.left + window.scrollX + abs.x}px`;
  el.style.top = `${box.top + window.scrollY + abs.y}px`;
  document.body.appendChild(el);
  editor = el;
  el.focus(); el.select();
  let closed = false;
  const close = (ok) => { if (closed) return; closed = true; const v = el.value.trim(); el.remove(); editor = null; done(ok ? v : null); };
  el.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); close(true); } else if (e.key === 'Escape') close(false); e.stopPropagation(); });
  el.addEventListener('blur', () => close(true));
}

function editText(idx) {
  const sh = doc.shapes[idx];
  textBox(sh.x, sh.y, sh.text, (v) => {
    if (v === null || v === sh.text) return;
    snapshot();
    if (!v) { doc.shapes.splice(idx, 1); sel = null; } else sh.text = v;
    render(); changed();
  });
}

// ── 입력 ─────────────────────────────────────────────
let start = null;
let freePts = null;

function draftShape(a, b) {
  const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y), w = Math.abs(a.x - b.x), h = Math.abs(a.y - b.y);
  switch (tool) {
    case 'arrow': return { type: 'arrow', points: [a.x, a.y, b.x, b.y], color, width: LINE };
    case 'free': return { type: 'free', points: freePts.slice(), color, width: LINE };
    case 'circle': return { type: 'circle', x: a.x, y: a.y, r: Math.hypot(b.x - a.x, b.y - a.y), color, width: LINE };
    case 'rect': return { type: 'rect', x, y, w, h, color, width: LINE };
    case 'mosaic': return { type: 'mosaic', x, y, w, h };
    case 'crop': return { type: 'crop', x, y, w, h };
    case 'inset': {
      const k = Math.min(2.5, (0.4 * W) / Math.max(w, 1), (0.4 * H) / Math.max(h, 1));
      const dw = w * k, dh = h * k, m = Math.round(Math.min(W, H) * 0.03);
      const dx = x + w / 2 < W / 2 ? W - dw - m : m;        // 고른 곳 반대편 위쪽에 확대본
      return { type: 'inset', src: [x, y, w, h], dst: [dx, m, dw, dh], color, width: LINE };
    }
  }
  return null;
}

function big(sh) {
  if (!sh) return false;
  if (sh.type === 'arrow') return Math.hypot(sh.points[2] - sh.points[0], sh.points[3] - sh.points[1]) > MIN;
  if (sh.type === 'free') return sh.points.length >= 6;
  if (sh.type === 'circle') return sh.r > MIN;
  if (sh.type === 'inset') return sh.src[2] > MIN && sh.src[3] > MIN;
  return sh.w > MIN && sh.h > MIN;
}

stage.on('pointerdown', (e) => {
  if (e.target.getParent && e.target.getParent() === tr) return;     // 크기 손잡이
  const p = pointer();
  if (tool === 'select') { if (sel) select(null); return; }
  if (sel) { sel = null; render(); }
  if (tool === 'marker') {
    snapshot(); doc.markers.push({ no: doc.markers.length + 1, x: p.x, y: p.y, label: '', component_id: null });
    render(); changed();
    return;
  }
  if (tool === 'text') {
    textBox(p.x, p.y, '', (v) => {
      if (!v) return;
      snapshot(); doc.shapes.push({ type: 'text', x: p.x, y: p.y, text: v, size: TEXT, color });
      sel = { kind: 'shape', idx: doc.shapes.length - 1 }; render(); changed();
    });
    return;
  }
  if (DRAG_TOOLS.has(tool)) {
    start = p; freePts = [p.x, p.y];
    window.addEventListener('pointermove', drawMove);
    window.addEventListener('pointerup', drawEnd, { once: true });
  }
});

function windowPointer(ev) {
  stage.setPointersPositions(ev);                 // 캔버스 밖 좌표도 받아서 사진 안으로 맞춘다
  return pointer();
}

stage.on('pointerup', () => { if (selDirty && !Konva.isDragging()) { selDirty = false; render(); } });   // 누른 개체 선택 표시(끄는 중이면 dragend 가 그린다)

function drawMove(ev) {
  if (!start) return;
  const p = windowPointer(ev);
  if (tool === 'free') freePts.push(p.x, p.y);
  draft.destroyChildren();
  const sh = draftShape(start, p);
  if (sh && sh.type === 'crop') draft.add(cropOverlay([sh.x, sh.y, Math.max(sh.w, 1), Math.max(sh.h, 1)]));
  else if (sh && sh.type !== 'mosaic') { const n = shapeNode(sh); if (n) draft.add(n); }
  else if (sh) draft.add(new Konva.Rect({ x: sh.x, y: sh.y, width: sh.w, height: sh.h, stroke: '#ffffff', strokeWidth: LINE / 2, dash: [6, 4] }));
  draftLayer.batchDraw();
}

function drawEnd(ev) {
  window.removeEventListener('pointermove', drawMove);
  if (!start) return;
  const sh = draftShape(start, windowPointer(ev));
  start = null; draft.destroyChildren(); draftLayer.batchDraw();
  if (!big(sh)) return;
  if (sh.type === 'crop') { pendingCrop = [sh.x, sh.y, sh.w, sh.h]; render(); return; }   // 적용 전까지는 조정 가능
  snapshot();
  doc.shapes.push(sh);
  sel = { kind: 'shape', idx: doc.shapes.length - 1 };      // 방금 그린 것은 바로 고칠 수 있게 선택
  render(); changed();
}

function setTool(t) {
  if (tool === 'crop' && t !== 'crop') pendingCrop = null;
  tool = t;
  document.querySelectorAll('[data-tool]').forEach((x) => x.setAttribute('aria-pressed', String(x.dataset.tool === t)));
  holder.style.cursor = { select: 'default', marker: 'copy', text: 'text' }[t] || 'crosshair';
  if (t !== 'select') sel = null;
  render();
}

document.querySelectorAll('[data-tool]').forEach((b) => b.addEventListener('click', () => setTool(b.dataset.tool)));
document.querySelectorAll('[data-color]').forEach((b) => b.addEventListener('click', () => {
  color = b.dataset.color;
  document.querySelectorAll('[data-color]').forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
  if (sel && sel.kind === 'shape' && doc.shapes[sel.idx].color) { snapshot(); doc.shapes[sel.idx].color = color; render(); changed(); }   // 고른 개체 색 바꾸기
}));
$('rotBtn').addEventListener('click', () => { snapshot(); doc.base.rotate = (doc.base.rotate + 90) % 360; render(); fit(); changed(); });
let brightSnap = false;
$('bright').addEventListener('input', (e) => { if (!brightSnap) { snapshot(); brightSnap = true; } doc.base.brightness = Number(e.target.value); applyBright(); changed(); });
$('bright').addEventListener('change', () => { brightSnap = false; });
$('cropApply').addEventListener('click', () => {
  if (!pendingCrop) { msg('사진 위를 끌어서 자를 영역을 먼저 잡아주세요', 'bad'); return; }
  snapshot(); doc.base.crop = pendingCrop.map((v) => Math.round(v)); pendingCrop = null; setTool('select'); changed();
});
$('cropCancel').addEventListener('click', () => { pendingCrop = null; setTool('select'); });
$('uncropBtn').addEventListener('click', () => { snapshot(); doc.base.crop = null; pendingCrop = null; render(); changed(); });
$('delBtn').addEventListener('click', deleteSel);
$('clearBtn').addEventListener('click', () => {
  if (!doc.shapes.length && !doc.markers.length) { msg('지울 마킹이 없습니다', 'bad'); return; }
  if (!window.confirm('그린 도형과 번호 마커를 모두 지웁니다. 원본 사진·자르기·회전은 그대로입니다. (되돌리기로 복구 가능)')) return;
  snapshot(); doc.shapes = []; doc.markers = []; sel = null; render(); changed();
});
function doUndo() {
  if (!undo.length) { msg('되돌릴 것이 없습니다', 'bad'); return; }
  redo.push(JSON.stringify(doc)); Object.assign(doc, JSON.parse(undo.pop())); sel = null; render(); fit(); changed();
}
function doRedo() {
  if (!redo.length) { msg('다시 실행할 것이 없습니다', 'bad'); return; }
  undo.push(JSON.stringify(doc)); Object.assign(doc, JSON.parse(redo.pop())); sel = null; render(); fit(); changed();
}
$('undoBtn').addEventListener('click', doUndo);
$('redoBtn').addEventListener('click', doRedo);

// ── 키보드 ───────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
  const k = e.key.toLowerCase();
  if ((e.ctrlKey || e.metaKey) && k === 's') { e.preventDefault(); save(); return; }
  if (typing) return;
  if ((e.ctrlKey || e.metaKey) && k === 'z' && !e.shiftKey) { e.preventDefault(); doUndo(); }
  else if ((e.ctrlKey || e.metaKey) && (k === 'y' || (k === 'z' && e.shiftKey))) { e.preventDefault(); doRedo(); }
  else if (e.key === 'Delete' || e.key === 'Backspace') { if (sel) { e.preventDefault(); deleteSel(); } }
  else if (e.key === 'Escape') { if (tool === 'crop') { pendingCrop = null; setTool('select'); } else if (sel) select(null); }
  else if (k === 'v' && !e.ctrlKey && !e.metaKey) setTool('select');
});

// ── 저장 ─────────────────────────────────────────────
async function save() {
  const btn = $('saveBtn');
  btn.disabled = true;
  try {
    const r = await fetch(`/api/photos/${encodeURIComponent(data.photo)}/annotation?block=${encodeURIComponent(data.block)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(doc),
    });
    const j = await r.json();
    if (!r.ok || !j.ok) { msg(j.error || j.detail || `저장하지 못했습니다 (HTTP ${r.status})`, 'bad'); return false; }
    dirty = false;
    btn.textContent = '마킹 저장';
    msg(`저장했습니다 · 마커 ${j.markers}개` + (j.missing_part ? ` · 부위 안 고른 마커 ${j.missing_part}개` : ''));
    return true;
  } catch (e) {
    msg('저장하지 못했습니다 — 서버에 연결되지 않습니다. 잠시 후 다시 눌러주세요.', 'bad');
    return false;
  } finally {
    btn.disabled = false;
  }
}
$('saveBtn').addEventListener('click', save);
$('saveBackBtn').addEventListener('click', async () => { if (!dirty || await save()) location.href = data.back; });

// 이전/다음 사진·사진 정보 저장 — 마킹을 먼저 저장하고 넘어간다
document.querySelectorAll('[data-nav]').forEach((el) => el.addEventListener('click', async (e) => {
  if (!dirty) return;
  e.preventDefault();
  if (!(await save())) return;
  if (el.tagName === 'A') location.href = el.href; else el.form.requestSubmit();
}));
window.addEventListener('beforeunload', (e) => { if (dirty) { e.preventDefault(); e.returnValue = ''; } });
window.addEventListener('resize', fit);

imgEl.onload = () => {
  K = imgEl.naturalWidth / W;
  imageNode = new Konva.Image({ image: imgEl, x: 0, y: 0, width: W, height: H });   // 작업용 사진을 원본 크기 좌표로 늘려 그림
  bg.add(imageNode);
  render();
  fit();
  msg('');
};
imgEl.onerror = () => msg('사진을 불러오지 못했습니다. 페이지를 새로 고쳐주세요.', 'bad');
imgEl.src = data.src;
