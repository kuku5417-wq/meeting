// 대시보드 지표 즉시 갱신 — 값을 바꾸면 추이·막대·평소 범위 표시·슬라이드 KPI 가 바로 바뀐다(저장은 폼).
// 좌표 규칙은 app/services/metrics.py 의 spark_svg / bar_svg 와 같다. 한쪽을 바꾸면 다른 쪽도 고친다.

const SPARK_W = 90, SPARK_H = 24, SPARK_PAD = 3, BAR_W = 220, BAR_H = 120;
const num = (s) => (s === '' || s == null ? null : Number(s));
const fmt = (v) => String(Number(v.toPrecision(6)));

function scale(series, extra = []) {
  const nums = [...series, ...extra].filter((v) => v != null);
  if (!nums.length) return [0, 1];
  let lo = Math.min(...nums), hi = Math.max(...nums);
  if (lo === hi) { lo -= 1; hi += 1; }
  return [lo, hi];
}

function sparkSvg(series, flag) {
  const [lo, hi] = scale(series);
  const step = (SPARK_W - 2 * SPARK_PAD) / Math.max(series.length - 1, 1);
  const pts = [];
  series.forEach((v, i) => { if (v != null) pts.push([SPARK_PAD + i * step, SPARK_H - SPARK_PAD - ((v - lo) / (hi - lo)) * (SPARK_H - 2 * SPARK_PAD)]); });
  const color = flag ? 'var(--danger)' : 'var(--accent)';
  const poly = pts.length > 1 ? `<polyline points="${pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')}" fill="none" stroke="var(--muted)" stroke-width="1.5"/>` : '';
  const last = series[series.length - 1] != null && pts.length ? `<circle cx="${pts[pts.length - 1][0].toFixed(1)}" cy="${pts[pts.length - 1][1].toFixed(1)}" r="2.6" fill="${color}"/>` : '';
  return `<svg class="spark" viewBox="0 0 ${SPARK_W} ${SPARK_H}" aria-hidden="true">${poly}${last}</svg>`;
}

function barSvg(labels, series, low, high) {
  const left = 26, bottom = BAR_H - 18, top = 8;
  let [lo, hi] = scale(series, [low, high]);
  if (lo >= 0) lo = Math.min(lo, 0);
  const n = series.length, slot = (BAR_W - left - 4) / Math.max(n, 1);
  const y = (v) => bottom - ((v - lo) / (hi - lo)) * (bottom - top);
  const parts = [`<line x1="${left}" y1="${bottom}" x2="${BAR_W - 2}" y2="${bottom}" stroke="var(--line)"/>`,
    `<text x="${left - 4}" y="${top + 8}" text-anchor="end">${fmt(hi)}</text>`,
    `<text x="${left - 4}" y="${bottom}" text-anchor="end">${fmt(lo)}</text>`];
  if (low != null && high != null) parts.push(`<rect x="${left}" y="${y(high).toFixed(1)}" width="${BAR_W - left - 2}" height="${Math.max(y(low) - y(high), 0).toFixed(1)}" fill="var(--ok-soft)"/>`);
  series.forEach((v, i) => {
    const x = left + i * slot + slot * 0.2;
    parts.push(`<text x="${(x + slot * 0.3).toFixed(1)}" y="${BAR_H - 4}" text-anchor="middle">${labels[i]}</text>`);
    if (v == null) return;
    const out = (high != null && v > high) || (low != null && v < low);
    const fill = out ? 'var(--danger)' : (i === n - 1 ? 'var(--accent)' : 'var(--muted)');
    parts.push(`<rect x="${x.toFixed(1)}" y="${y(v).toFixed(1)}" width="${(slot * 0.6).toFixed(1)}" height="${Math.max(bottom - y(v), 0).toFixed(1)}" fill="${fill}"/>`);
  });
  return `<svg class="chart" viewBox="0 0 ${BAR_W} ${BAR_H}" role="img" aria-label="주차별 막대 차트">${parts.join('')}</svg>`;
}

document.querySelectorAll('tr[data-metric]').forEach((tr) => {
  const id = tr.dataset.metric;
  const past = JSON.parse(tr.dataset.series);
  const labels = JSON.parse(tr.dataset.labels);
  const low = num(tr.dataset.low), high = num(tr.dataset.high);
  const input = tr.querySelector('.num-in');
  const flagEl = tr.querySelector('.flag');
  const name = tr.querySelector('[data-show-bar]').textContent.trim();
  const unit = tr.children[2].textContent.trim();
  const redraw = () => {
    const v = num(input.value);
    const series = [...past, Number.isFinite(v) ? v : null];
    const cur = series[series.length - 1];
    const flag = cur == null ? '' : (high != null && cur > high ? '높음' : (low != null && cur < low ? '낮음' : ''));
    tr.querySelector('.spark-cell').innerHTML = sparkSvg(series, flag);
    const box = document.querySelector(`[data-bar="${id}"] .bar-svg`);
    if (box) box.innerHTML = barSvg(labels, series, low, high);
    flagEl.hidden = !flag;
    flagEl.textContent = flag ? `평소보다 ${flag}` : '';
    const needs = tr.querySelector('.needs'), cm = tr.querySelector('.cm');
    if (needs) needs.hidden = !(flag && !cm.value.trim());     // F16: 평소 범위를 벗어났는데 차이 사유가 비면
    const kpi = document.getElementById('kpi');
    if (kpi) {
      let span = kpi.querySelector(`[data-kpi="${id}"]`);
      if (cur == null) { if (span) span.remove(); return; }
      if (!span) { kpi.querySelectorAll('.muted').forEach((x) => x.remove()); span = document.createElement('span'); span.dataset.kpi = id; kpi.appendChild(span); }
      span.innerHTML = `${name} <b>${fmt(cur)}</b>${unit}`;
    }
  };
  input.addEventListener('input', redraw);
  tr.querySelector('.cm')?.addEventListener('input', redraw);
});

document.querySelectorAll('[data-show-bar]').forEach((b) => b.addEventListener('click', () => {
  document.querySelectorAll('[data-bar]').forEach((x) => { x.hidden = x.dataset.bar !== b.dataset.showBar; });
}));

// 기간 표(F16) — 칸을 바꾸면 행 합계·차이·「사유를 적어주세요」를 바로
document.querySelectorAll('tr[data-prow]').forEach((tr) => {
  const sum = (sel) => { const xs = [...tr.querySelectorAll(sel)].map((i) => num(i.value)).filter((v) => v != null && Number.isFinite(v)); return xs.length ? xs.reduce((a, b) => a + b, 0) : null; };
  const note = tr.querySelector('input[name^="n_"]');
  const redraw = () => {
    const p = sum('[data-p]'), a = sum('[data-a]'), d = p != null || a != null ? (a || 0) - (p || 0) : null;
    tr.querySelector('[data-sp]').textContent = p != null ? fmt(p) : '';
    tr.querySelector('[data-sa]').textContent = a != null ? fmt(a) : '';
    const sd = tr.querySelector('[data-sd]');
    sd.textContent = d ? (d > 0 ? '+' : '') + fmt(d) : '';
    sd.classList.toggle('v-late', !!d);
    note.classList.toggle('needs-in', !!d && !note.value.trim());
    note.placeholder = d && !note.value.trim() ? '사유를 적어주세요' : '';
    tr.querySelectorAll('.pt-c').forEach((td) => { const pp = num(td.querySelector('[data-p]').value), aa = num(td.querySelector('[data-a]').value); td.querySelector('[data-a]').classList.toggle('off', pp != null && aa != null && pp !== aa); });
  };
  tr.querySelectorAll('input').forEach((i) => i.addEventListener('input', redraw));
});
