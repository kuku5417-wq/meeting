// 회의자료 장 그리기(M11) — 스튜디오·회의 보기가 같이 쓴다. 1920×1080 좌표, 본문 26px 이상. PPT(pptx_builder.build_meeting)와 같은 칸 구성.
export const esc = (v) => String(v ?? '').replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
export const KIND = {issue: '이슈', problem: '문제점', share: '공유', dashboard: '지표'};

const pic = (b, big) => b.photo ? `<div class="ph"><img src="/photos/${esc(b.photo)}/render?block=${esc(b.id)}&w=${big ? 1100 : 700}" alt="${esc(b.title)} 사진" loading="lazy"></div>` : `<div class="ph">${big ? '사진 없음' : ''}</div>`;

// it: {kind, line, form, tag_on, blocks:[{id,type,title,status,dept,hull,ev,dd,body,cause,act,dec,ptag,photo}]}, ctx: {title, forms}
const num = (v) => (v == null ? '—' : String(Number(Number(v).toPrecision(6))));

// 지표 요약(F16) — 주간 지표(이탈·코멘트 먼저) + 기간 표 합계. it.metric = {dept, metrics:[…], tables:[…]}
export function metricSlide(it, n, total, ctx) {
  const M = it.metric || {metrics: [], tables: [], dept: ''};
  const rows = M.metrics.slice(0, 8).map((x) => `<tr${x.flag ? ' style="color:#b83a26;font-weight:600"' : ''}><td>${esc(x.name)}</td><td style="text-align:right">${num(x.value)}<span style="font-size:22px;color:#566570"> ${esc(x.unit)}</span></td><td style="font-size:22px;color:#566570">${x.series.map(num).join(' · ')}</td><td style="font-size:24px">${x.flag ? `평소보다 ${esc(x.flag)} — ` : ''}${esc(x.comment || '')}</td></tr>`).join('');
  const tabs = M.tables.map((t) => `<div style="font-size:26px"><b>${esc(t.name)}</b> ${esc(t.period)} · 계획 ${num(t.plan)} · 실적 ${num(t.actual)}${t.unit ? ' ' + esc(t.unit) : ''}${t.rows.filter((r) => r.diff).map((r) => ` · ${esc(r.name)} ${r.diff > 0 ? '+' : ''}${num(r.diff)}${r.note ? ' (' + esc(r.note) + ')' : ''}`).join('')}</div>`).join('');
  return `<div class="sh"><span>${esc(ctx.title)}</span><span>${esc(M.dept)} 지표</span></div><div class="sb"><div class="st1"><span class="lab dashboard">지표</span>${esc(it.line || '이번 주 지표')}</div>
    <table style="width:100%;border-collapse:collapse;font-size:28px"><thead><tr style="color:#566570;font-size:22px;text-align:left"><th>지표</th><th style="text-align:right">이번 주</th><th>최근 6주</th><th>코멘트</th></tr></thead><tbody>${rows || '<tr><td colspan="4">지표가 없습니다</td></tr>'}</tbody></table>${tabs}</div><div class="sf"><span>${n} / ${total}</span><span>지표 요약</span></div>`;
}

// 장 이름(목록·쪽 표시용) — 요약 문장 · 지표 요약 · 기간 표 이름 · 대표 이슈 제목
export const pageTitle = (it) => it.kind === 'summary' ? it.line : it.kind === 'metric' ? '지표 요약' : it.kind === 'table' ? `기간 표 · ${it.table?.name || it.line}` : it.blocks[0]?.title || '';
export const isData = (it) => it.kind === 'metric' || it.kind === 'table';   // 이슈가 없는 장(형태 바꾸기·회의 기록 없음)

// 기간 표(F16) — 그 주 날짜별 계획/실적 + 기간 합계·차이·사유. it.table = {dept, name, unit, period, days, plan, actual, rows:[{name, cells:[[계획, 실적]…], plan, actual, diff, note}]}
export function tableSlide(it, n, total, ctx) {
  const T = it.table;
  const head = `<div class="sh"><span>${esc(ctx.title)}</span><span>${esc(T?.dept || '')} 기간 표</span></div>`;
  const foot = `<div class="sf"><span>${n} / ${total}${T ? ' · ' + esc(T.period) : ''}</span><span>기간 표</span></div>`;
  if (!T) return head + `<div class="sb"><div class="st1"><span class="lab dashboard">기간 표</span>${esc(it.line)}</div><div style="font-size:28px">기간 표가 지워졌습니다 — 이 장을 빼주세요.</div></div>` + foot;
  const red = ' style="color:#b83a26;font-weight:600"';
  const cell = ([p, a]) => (p == null && a == null ? '<td style="color:#8a96a0">·</td>' : `<td${p != null && a != null && a !== p ? red : ''}>${num(p)} / ${num(a)}</td>`);
  const sgn = (v) => (v ? (v > 0 ? '+' : '') + num(v) : '—');
  const rows = T.rows.slice(0, 10).map((r) => `<tr style="border-top:1px solid #d5dce3"><td style="text-align:left"><b>${esc(r.name)}</b></td>${r.cells.map(cell).join('')}<td>${num(r.plan)}</td><td>${num(r.actual)}</td><td${r.diff ? red : ''}>${sgn(r.diff)}</td><td style="text-align:left;font-size:22px">${esc(r.note || '')}</td></tr>`).join('');
  const more = T.rows.length > 10 ? `<div style="font-size:22px;color:#566570">외 ${T.rows.length - 10}행 — 지표 화면에서 봅니다</div>` : '';
  const tot = T.actual - T.plan;
  return head + `<div class="sb"><div class="st1"><span class="lab dashboard">기간 표</span>${esc(it.line || T.name)}<span style="font-size:24px;color:#566570;font-weight:400"> · ${esc(T.period)}${T.unit ? ' · ' + esc(T.unit) : ''} · 칸 = 계획 / 실적</span></div>
    <table class="ptab" style="width:100%;border-collapse:collapse;font-size:30px;text-align:right"><thead><tr style="color:#566570;font-size:22px"><th style="text-align:left">행</th>${T.days.map((d) => `<th>${esc(d)}</th>`).join('')}<th>기간 계획</th><th>실적</th><th>차이</th><th style="text-align:left">사유</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="${T.days.length + 5}" style="text-align:left">행이 없습니다</td></tr>`}<tr style="border-top:3px solid #2C4566"><td style="text-align:left"><b>합계</b></td>${T.days.map(() => '<td></td>').join('')}<td><b>${num(T.plan)}</b></td><td><b>${num(T.actual)}</b></td><td${tot ? red : ''}>${sgn(tot)}</td><td></td></tr></tbody></table>${more}</div>` + foot;
}

export function slide(it, n, total, form, ctx) {
  if (it.kind === 'metric') return metricSlide(it, n, total, ctx);
  if (it.kind === 'table') return tableSlide(it, n, total, ctx);
  const b = it.blocks[0] || {}, f = form || it.form;
  const pre = it.tag_on && b.ptag && it.kind !== 'summary' ? `<b style="color:#6a35c4">[${esc(b.ptag)}]</b> ` : '';
  const head = `<div class="sh"><span>${esc(ctx.title)}</span><span>${esc(it.kind === 'summary' ? '요약 · ' + it.blocks.length + '건' : b.dept)}</span></div>`;
  const where = it.kind === 'summary' ? [...new Set(it.blocks.map((x) => x.hull).filter(Boolean))].join('·') : [b.hull, b.ev, b.dd != null ? 'D-' + b.dd : ''].filter(Boolean).join(' · ');
  const foot = `<div class="sf"><span>${n} / ${total}${where ? ' · ' + esc(where) : ''}</span><span>${esc(ctx.forms[f] || '')}</span></div>`;
  if (it.kind === 'summary') return head + `<div class="sb"><div class="st1">${esc(it.line)}</div>${it.blocks.map((x) => `<div class="li ${x.type}"><b>${esc(x.title)}</b>${esc(x.ptag || x.status || '')}</div>`).join('')}</div>` + foot;
  const t = `<div class="st1"><span class="lab ${b.type}">${KIND[b.type] || ''}</span>${esc(b.title)}</div>`;
  const dec = b.dec ? `<div class="dec"><b>결정 필요</b> ${esc(b.dec)}</div>` : '';
  if (f === 'detail') return head + `<div class="sb">${t}<div style="font-size:30px">${pre}${esc(it.line)}</div><div class="g4"><div><b>현상</b>${esc(b.body || '—')}</div><div><b>원인</b>${esc(b.cause || '조사 중')}</div><div style="grid-column:1/-1"><b>조치 · 계획</b>${esc(b.act || '—')}</div></div>${dec}</div>` + foot;
  if (f === 'photo') return head + `<div class="sb">${t}<div style="display:grid;grid-template-columns:1.3fr 1fr;gap:32px">${pic(b, true)}<div style="display:grid;gap:20px;align-content:start;font-size:30px">${pre}${esc(it.line)}${dec}</div></div></div>` + foot;
  if (f === 'line') return head + `<div class="sb" style="align-content:center">${t}<div style="font-size:40px;line-height:1.4">${pre}${esc(it.line)}</div></div>` + foot;
  return head + `<div class="sb">${t}<div style="display:grid;grid-template-columns:1fr 360px;gap:28px"><div style="display:grid;gap:16px;font-size:30px;align-content:start">${pre}${esc(it.line)}<div class="g4"><div><b>담당</b>${esc(b.dept)}</div><div><b>상태</b>${esc(b.status)}</div></div></div>${pic(b, false)}</div>${dec}</div>` + foot;
}

// meeting: {title, week, kind, kind_label, version, status}, cov: {n, dec, closing, long, submit?, left?, closed?}
export function cover(meeting, cov, total, longWeeks) {
  const box = (lab, v, col) => `<div><b>${esc(lab)}</b><span style="font-size:56px;font-weight:600${col ? ';color:' + col : ''}">${v}</span></div>`;
  const boxes = [box('안건', cov.n), box('결정 필요', cov.dec, '#6a35c4')]
    .concat(meeting.kind === 'exec' ? [box(`장기 미결(${longWeeks}주+)`, cov.long, '#b83a26'), box('이번 주 종결', cov.closed ?? 0, '#276d43')]
      : [box('종결 승인 대기', cov.closing, '#9a5a00'), box(`장기 미결(${longWeeks}주+)`, cov.long, '#b83a26')]);
  const sub = cov.submit ? `<div style="font-size:30px">부서 제출 <b>${esc(cov.submit)}</b>${cov.left?.length ? ` · <span style="color:#b83a26">미제출 ${esc(cov.left.join('·'))}</span>` : ' · 전 부서 제출'}</div>` : '';
  return `<div class="sh"><span>커미셔닝팀</span><span>${esc(meeting.week)}</span></div><div class="sb" style="align-content:center;gap:36px"><div style="font-size:64px;font-weight:600">${esc(meeting.title)}</div><div class="g4" style="grid-template-columns:repeat(4,1fr)">${boxes.join('')}</div>${sub}</div><div class="sf"><span>1 / ${total}</span><span>${esc(meeting.kind_label)}</span></div>`;
}

// 공유회 부서 구분 장
export function divider(sec, n, total, title) {
  return `<div class="sh"><span>${esc(title)}</span><span>${esc(sec.dept)}</span></div><div class="sb" style="align-content:center;justify-items:center;gap:24px"><div style="font-size:72px;font-weight:600">${esc(sec.dept)}</div><div style="font-size:30px;color:#566570">${esc(sec.state)} · 안건 ${sec.n ?? sec.items?.length ?? 0}</div></div><div class="sf"><span>${n} / ${total}</span><span>부서</span></div>`;
}

// 지난 지시사항(M12) — 표지 다음 한 장. rows: [{text, dept, due, late, status, done_note}]
export function directivesSlide(rows, n, total, title) {
  const li = rows.map((d) => `<div class="li ${d.status === '완료' ? 'share' : d.late ? 'problem' : 'issue'}"><b>${esc(d.text)}</b>${esc(d.dept)} · 기한 ${esc(d.due.slice(-3))}${d.status === '완료' ? ' · 완료 — ' + esc(d.done_note) : d.late ? ' · 기한 지남' : ' · 진행 중'}</div>`).join('');
  return `<div class="sh"><span>${esc(title)}</span><span>지난 지시사항</span></div><div class="sb"><div class="st1">지난 지시사항 ${rows.length}건 — 완료 ${rows.filter((d) => d.status === '완료').length}</div>${li}</div><div class="sf"><span>${n} / ${total}</span><span>지시 점검</span></div>`;
}

// 쪽 순서 — 표지 · (지난 지시사항) · (공유회면 부서 구분 장) · 장. 보기·진행·PPT 가 같은 순서
export function pageList(D) {
  const out = [{t: 'cover'}];
  if (D.directives?.length) out.push({t: 'dir'});
  const share = D.meeting.kind === 'share';
  D.sections.forEach((sec) => { if (share) out.push({t: 'div', sec}); sec.items.forEach((it) => out.push({t: 'item', it, sec})); });
  return out;
}
export function renderPage(p, n, total, D, longWeeks) {
  if (p.t === 'cover') return cover(D.meeting, D.cover, total, longWeeks);
  if (p.t === 'dir') return directivesSlide(D.directives, n, total, D.meeting.title);
  if (p.t === 'div') return divider(p.sec, n, total, D.meeting.title);
  return slide(p.it, n, total, null, {title: D.meeting.title, forms: D.forms});
}

export function fit(root = document) { root.querySelectorAll('.v-stage-wrap').forEach((w) => { const st = w.querySelector('.v-stage'); if (st) st.style.transform = `scale(${w.clientWidth / 1920})`; }); }
