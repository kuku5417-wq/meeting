// v2 B안 시안 공통 가상 데이터 (2026-10-23) — 모든 B안 화면이 같은 이슈·회의를 보도록 한 곳에 둔다.
// 실제 구현: ISSUES = block(+매핑·초안 상태), MEETINGS = meeting(+report_item). 오늘 = 2026-10-22(W43).
export const DEPTS = ['기획운영', '시운전기술', '시운전1부', '시운전2부', '시운전3부', '해운부', '안벽의장그룹', '친환경실증Lab'];
export const KIND = {issue: '이슈', problem: '문제점', share: '공유'};
// st: go 진행 · new 신규 · req 종결 요청 · done 종결 · post 게시 / draft: none 미착수 · wip 작성 중 · ok 초안 완료
export const ISSUES = [
  {id: 'ISS-2026-0001', t: 'issue', dept: '시운전1부', hull: 'SN2511', ev: 'S/T 11/03', dd: 12, eq: '발전기 No.2', raw: 'DG2', title: 'SN2511 발전기 No.2 배기온도 편차', wk: '연료밸브 입고 지연, 다음 주 교체', last: '신규 등록 — 3번 실린더 +38℃', map: 4, st: 'go', weeks: 3, draft: 'ok',
    sym: '3번 실린더 배기온도 +38℃ (기준 ±25℃)', cause: '조사 중 — 자매선 SN2510 은 분사밸브 노즐 마모', act: '연료밸브 교체 → 10/25 부하시험', dec: '부하시험을 해상에서 할지 안벽에서 할지 (선주 협의)'},
  {id: 'PRB-2026-0001', t: 'problem', dept: '시운전1부', hull: 'SN2514', ev: 'G/T 10/27', dd: 5, eq: '카고펌프 No.3', raw: '카고펌프 3번', title: 'SN2514 카고펌프 No.3 메카니컬씰 누유', wk: '씰 교체 후 4시간 무누유 확인', last: '씰 교체 완료, 시운전 대기', map: 5, st: 'req', weeks: 2, draft: 'ok',
    sym: '메카니컬씰 누유', cause: '씰 면 손상 — 초기 건운전', act: '씰 교체 → 4시간 무누유 확인(10/21)'},
  {id: 'ISS-2026-0012', t: 'issue', dept: '시운전1부', hull: 'SN2514', ev: 'G/T 10/27', dd: 5, eq: '카고펌프 No.1', raw: '카고 1번', title: 'SN2514 카고펌프 No.1 토출압 변동', wk: '', last: '토출압 ±0.4bar 흔들림', map: 3, st: 'go', weeks: 2, draft: 'wip',
    sym: '토출압 ±0.4bar 변동', cause: '', act: '흡입 스트레이너 점검'},
  {id: 'PRB-2026-0007', t: 'problem', dept: '시운전1부', hull: 'SN2402', ev: '인도 완료', dd: null, eq: null, raw: 'Sterntube', title: 'Sterntube 금속이물질 발견', wk: '', last: '신규', map: 1, st: 'new', weeks: 1, draft: 'none',
    sym: 'Sterntube 오일에서 금속이물질', cause: '', act: ''},
  {id: 'SHR-2026-0001', t: 'share', dept: '시운전1부', hull: 'SN2511', ev: 'S/T 11/03', dd: 12, eq: '조타기 No.1', raw: '조타기', title: 'SN2511 조타기 선급 검사 10/21 → 10/23', wk: '~10/23 유효', last: '일정 변경 공문', map: 5, st: 'post', weeks: 1, draft: 'ok'},
  {id: 'ISS-2026-0004', t: 'issue', dept: '시운전기술', hull: 'SN2512', ev: 'L/C 11/19', dd: 28, eq: '발전기 No.1', raw: 'DG1', title: 'SN2512 발전기 No.1 기동 지연', wk: '', last: '제조사 회신 대기', map: 3, st: 'go', weeks: 5, draft: 'ok',
    sym: '기동 신호 후 12초 지연', cause: '조사 중', act: '제조사 회신 대기', dec: '제조사 현장 점검을 요청할지'},
  {id: 'ISS-2026-0009', t: 'issue', dept: '시운전2부', hull: 'SN2511', ev: 'S/T 11/03', dd: 12, eq: '청수 발생기', raw: 'FWG', title: 'SN2511 청수 발생기 생산량 저하', wk: '세관 세척 예정', last: '생산량 18t/d (정격 25)', map: 5, st: 'go', weeks: 2, draft: 'ok'},
  {id: 'PRB-2026-0011', t: 'problem', dept: '시운전2부', hull: 'SN2513', ev: 'D/L 12/12', dd: 51, eq: '유압펌프', raw: '유압펌프', title: 'SN2513 유압펌프 파손 — 메이커 주장 검토', wk: '메이커 「오일 관리」 주장 반박 자료', last: '파손 확인', map: 2, st: 'go', weeks: 4, draft: 'ok', important: true, dec: '메이커 주장 대응 방침'},
  {id: 'ISS-2026-0015', t: 'issue', dept: '시운전3부', hull: 'SN2515', ev: 'L/C 12/05', dd: 44, eq: '가스감지기 #4', raw: '암모니아 감지기 4번', title: 'SN2515 암모니아 가스감지기 #4 고습도 영점 틀어짐', wk: '펌웨어 v2.4 입고 대기', last: '영점 보정 시험', map: 3, st: 'go', weeks: 3, draft: 'ok'},
];
export const MEETINGS = [
  {id: 'dept', kind: '부서 회의자료', title: 'W43 시운전1부 회의자료', when: '제출 마감 10/22(수) 14:00', owner: '시운전1부 부장·스텝', state: '작성 중', n: 4},
  {id: 'share', kind: '부서 현안 공유회', title: 'W43 부서 현안 공유회', when: '10/23(목) 14:00', owner: '기획(팀 스텝)', state: '취합 중 · 제출 6/8', n: 14},
  {id: 'exec', kind: '팀장 정보회의', title: 'W43 팀장 정보회의', when: '10/27(월) 08:30', owner: '기획 구성 · 팀장 확인', state: '공유회 뒤 구성', n: 5},
  {id: 'hull', kind: '호선별 회의', title: 'SN2511 해상시운전 사전 점검', when: '10/24(금) 10:00', owner: '시운전1부·시운전기술', state: '구성 중', n: 3},
];
export const SUBMIT = {'기획운영': 'ok', '시운전기술': 'ok', '시운전1부': 'wip', '시운전2부': 'ok', '시운전3부': 'wip', '해운부': 'ok', '안벽의장그룹': 'none', '친환경실증Lab': 'ok'};
// 회의용 한 줄 머리표(B6) — 종결 > 종결 요청 > 결정필요(+n주 미결) > 장기 미결 > 공유
export function ptag(d) {
  const long = d.weeks >= 4 && !['done', 'post'].includes(d.st) ? `${d.weeks}주 미결` : '';
  if (d.st === 'done') return '종결';
  if (d.st === 'req') return '종결승인 대기';
  if (d.dec) return ['결정필요', long].filter(Boolean).join(' · ');
  if (long) return long;
  if (d.t === 'share') return '공유';
  return '';
}
export const ST = {go: ['go', '진행'], new: ['new', '신규'], req: ['req', '종결 요청'], done: ['done', '종결'], post: ['go', '게시']};
export const byId = (id) => ISSUES.find((x) => x.id === id);

// 회의 한 건의 항목(보기·진행이 같이 씀). 실제 구현: report_item(회의별 순서·형태·회의용 한 줄)
export function deckOf(m) {
  if (m === 'exec') return ['ISS-2026-0001', 'PRB-2026-0001', 'ISS-2026-0004', 'PRB-2026-0011'].map((id) => ({d: byId(id), line: byId(id).wk || byId(id).last}));
  if (m === 'hull') return ISSUES.filter((d) => d.hull === 'SN2511').map((d) => ({d, line: d.wk || d.last}));
  const order = DEPTS;
  return ISSUES.filter((d) => d.st !== 'done').sort((a, b) => order.indexOf(a.dept) - order.indexOf(b.dept)).map((d) => ({d, line: d.wk || d.last}));
}
export const MEETING = {share: 'W43 부서 현안 공유회', exec: 'W43 팀장 정보회의', hull: 'SN2511 해상시운전 사전 점검'};
// 발표용 한 장(1920 좌표) — 항목 하나 = 한 장. 본문 26px 이상, 「결정 필요」는 아래 굵은 상자
export function itemSlide(it, n, total, next, title) {
  const d = it.d, p = ptag(d), e = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
  return `<div class="sh"><span>${e(title)}</span><span>${e(d.dept)}</span></div>
    <div class="sb"><div class="st1"><span class="lab" style="background:var(--t-${d.t})">${KIND[d.t]}</span>${e(d.title)}</div>
      <div style="font-size:30px">${p ? `<b style="color:var(--t-decide)">[${e(p)}]</b> ` : ''}${e(it.line)}</div>
      ${d.sym ? `<div class="grid4"><div><b>현상</b>${e(d.sym)}</div><div><b>원인</b>${e(d.cause || '조사 중')}</div><div style="grid-column:1/-1"><b>조치 · 계획</b>${e(d.act || '—')}</div></div>` : ''}
      ${d.dec ? `<div class="decide"><b>결정 필요</b> ${e(d.dec)}</div>` : ''}</div>
    <div class="sf"><span>${n} / ${total} · ${e(d.hull)} · ${e(d.ev)}${d.dd !== null ? ' D-' + d.dd : ''}</span><span>${next ? '다음: ' + e(next) : '마지막 장'}</span></div>`;
}
export function coverSlide(title, its, total) {
  const n = (f) => its.filter((x) => f(x.d)).length;
  return `<div class="sh"><span>커미셔닝팀</span><span>2026-W43</span></div>
    <div class="sb" style="align-content:center;gap:40px"><div style="font-size:64px;font-weight:700;line-height:1.2">${title}</div>
      <div class="grid4"><div><b>안건</b><span style="font-size:56px;font-weight:700">${its.length}</span></div><div><b>결정 필요</b><span style="font-size:56px;font-weight:700;color:var(--t-decide)">${n((d) => d.dec)}</span></div><div><b>종결 승인 대기</b><span style="font-size:56px;font-weight:700">${n((d) => d.st === 'req')}</span></div><div><b>장기 미결</b><span style="font-size:56px;font-weight:700;color:var(--t-problem)">${n((d) => d.weeks >= 4)}</span></div></div></div>
    <div class="sf"><span>1 / ${total}</span><span>다음: ${its[0] ? its[0].d.title.replace(/[&<>"]/g, '') : ''}</span></div>`;
}
