import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { post } from '../../api.js';
import { useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';

const CHANGE_TYPE_KO = { BODY: '본문', HEADER: '헤더', SIGNATURE: '시그니처', NEW: '신규', DELETE: '삭제', VARIABLE: '변수' };
const CHANGE_TYPE_TONE = { NEW: 'success', DELETE: 'danger', SIGNATURE: 'warning', BODY: 'info', HEADER: 'neutral', VARIABLE: 'neutral' };
// 정렬 우선순위 — 구조적 변경(시그니처/신규/삭제)을 위로.
const CHANGE_ORDER = { SIGNATURE: 5, NEW: 4, DELETE: 4, VARIABLE: 3, HEADER: 2, BODY: 1 };
const COVERAGE_METRIC_KO = { mcdc: 'MC/DC', branch: '분기', statement: '구문' };

// 데모 시나리오용 매핑 — 데모 모드에서 실제 추출 API 대신 주입한다. 함수명은 demoFunctions/
// demoImpact와 일치시켜, 조인 결과 요구사항/STS/SUTS TC가 채워진 완전한 데모를 보여준다.
const DEMO_UDS_MAPPING = [
  { requirement_id: 'SwRS_1001', source_ids: ['g_DrvIn_Main', 'g_DrvIn_MotorSpeed'] },
  { requirement_id: 'SwRS_1002', source_ids: ['s_MotorSpdCtrl_AutoClose', 's_MotorSpdCtrl_AutoOpen'] },
  { requirement_id: 'SwRS_1003', source_ids: ['s_AntipinchDetect_Close'] },
  { requirement_id: 'SwRS_1010', source_ids: ['g_Ap_BuzzerCtrl_Func', 's_DoorStateCtrl'] },
];
const DEMO_STS_TCS = [
  { requirement_id: 'SwRS_1001', testcase: 'STS_DrvIn_001' },
  { requirement_id: 'SwRS_1001', testcase: 'STS_DrvIn_002' },
  { requirement_id: 'SwRS_1002', testcase: 'STS_MotorSpd_010' },
  { requirement_id: 'SwRS_1003', testcase: 'STS_Antipinch_021' },
  { requirement_id: 'SwRS_1010', testcase: 'STS_Buzzer_030' },
];
const DEMO_SUTS_TCS = [
  { unit: 'g_DrvIn_Main', testcase: 'SUTS_DrvIn_Main_01' },
  { unit: 's_MotorSpdCtrl_AutoClose', testcase: 'SUTS_AutoClose_01' },
  { unit: 's_MotorSpdCtrl_AutoOpen', testcase: 'SUTS_AutoOpen_01' },
  { unit: 's_AntipinchDetect_Close', testcase: 'SUTS_Antipinch_01' },
  // 간접 전용 함수도 기존 단위 TC가 있어 회귀 재실행 대상이 됨을 데모로 예시.
  { unit: 's_NotifyObserver', testcase: 'SUTS_NotifyObserver_01' },
];

// 브라우저에서 텍스트 파일 다운로드(내보내기). Blob+anchor, CSP 안전(외부 요청 없음).
function downloadTextFile(filename, content, mime = 'text/markdown;charset=utf-8') {
  try {
    const blob = new Blob([content], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (_) { /* 다운로드 실패는 무해하게 무시 */ }
}

// ── 함수 시그니처 매개변수 파싱/diff (change_details before/after 원문 기반, 결정론·정확) ──
// C 함수 선언에서 반환 타입 추출(첫 '(' 앞, 함수명 토큰 제외).
function parseReturnType(sig) {
  if (!sig) return '';
  const head = String(sig).split('(')[0].trim();
  // 저장/링키지 지정자는 반환타입이 아니므로 제거(`static U8 f` → `U8`). 안 그러면
  // 지정자만 추가돼도 반환타입이 바뀐 것처럼 오표시된다(reviewer W3).
  const toks = head.split(/\s+/).filter(Boolean)
    .filter(t => !/^(static|extern|inline|register|auto|__inline|__forceinline)$/.test(t));
  return toks.length > 1 ? toks.slice(0, -1).join(' ') : (toks[0] || head);
}
// 최상위 콤마로만 분리 — 괄호/대괄호/꺾쇠 안의 콤마(함수포인터 `void(*cb)(int,int)`·배열·템플릿)는
// 분리자로 보지 않는다. `.split(',')`은 함수포인터 파라미터 내부 콤마에서 오분할했다(정확성 버그).
function splitTopLevelCommas(s) {
  const out = [];
  let depth = 0, cur = '';
  for (const ch of s) {
    if (ch === '(' || ch === '[' || ch === '{' || ch === '<') depth++;
    else if (ch === ')' || ch === ']' || ch === '}' || ch === '>') depth = Math.max(0, depth - 1);
    if (ch === ',' && depth === 0) { out.push(cur); cur = ''; } else cur += ch;
  }
  out.push(cur);
  return out.map(x => x.trim()).filter(Boolean);
}
// 매개변수 목록 추출 — [{raw, type, name}]. 선언 없음/void/빈 → [](0개), 내용 있으나 괄호 없음 → null(파싱불가).
function parseSignatureParams(sig) {
  if (!sig) return [];  // 빈 측(NEW의 before / DELETE의 after) = 매개변수 0개(파싱실패 아님)
  const m = String(sig).match(/\(([\s\S]*)\)/);
  if (!m) return null;  // 내용은 있으나 괄호 없음 = 파싱 불가(원문 참조 유도)
  const inner = m[1].trim();
  if (!inner || inner.toLowerCase() === 'void') return [];
  return splitTopLevelCommas(inner).map(raw => {
    // 배열 접미사 분리: `U8 src[8]`/`char argv[]` → 이름이 대괄호에 가려지지 않게 base와 분리.
    // 안 하면 last='src[8]'이 식별자 정규식에 안 맞아 name 추출 실패 → named diff가 위치기반으로
    // 강등되고 삽입/삭제 시 매개변수를 서로 오귀속한다(reviewer Critical #1).
    const arrM = raw.match(/^([\s\S]*?)\s*((?:\[[^\]]*\])+)\s*$/);
    const base = arrM ? arrM[1] : raw;
    const arraySuffix = arrM ? arrM[2] : '';
    const toks = base.replace(/\*/g, ' * ').split(/\s+/).filter(Boolean);
    const last = toks[toks.length - 1] || '';
    const hasName = toks.length > 1 && /^[A-Za-z_]\w*$/.test(last);
    const name = hasName ? last : '';
    const type = hasName ? (toks.slice(0, -1).join(' ').replace(/\s+\*/g, '*') + arraySuffix) : raw;
    return { raw, type, name };
  });
}
// before/after 시그니처 매개변수 diff — 이름이 모두 있으면 이름 기준, 아니면 위치 기준.
// 한쪽이라도 파싱 불가(null)면 failed=true로 "구조 파싱 불가"를 알린다(빈 값 0개로 오치환 금지).
function diffSignatureParams(before, after) {
  const bp = parseSignatureParams(before);
  const ap = parseSignatureParams(after);
  const meta = {
    returnBefore: parseReturnType(before),
    returnAfter: parseReturnType(after),
    returnChanged: !!(before && after) && parseReturnType(before) !== parseReturnType(after),
  };
  if (bp === null || ap === null) return { ...meta, failed: true, rows: [], beforeCount: 0, afterCount: 0, positional: false };
  const bb = bp, aa = ap;
  const rows = [];
  const named = (bb.length + aa.length) > 0 && bb.every(p => p.name) && aa.every(p => p.name);
  if (named) {
    const aMap = new Map(aa.map(p => [p.name, p]));
    const bMap = new Map(bb.map(p => [p.name, p]));
    for (const p of bb) {
      const a = aMap.get(p.name);
      if (!a) rows.push({ status: 'removed', before: p.raw, after: '' });
      else if (a.raw !== p.raw) rows.push({ status: 'changed', before: p.raw, after: a.raw });
    }
    for (const p of aa) if (!bMap.has(p.name)) rows.push({ status: 'added', before: '', after: p.raw });
  } else {
    const n = Math.max(bb.length, aa.length);
    for (let i = 0; i < n; i++) {
      const b = bb[i], a = aa[i];
      if (b && a) { if (b.raw !== a.raw) rows.push({ status: 'changed', before: b.raw, after: a.raw }); }
      else if (a) rows.push({ status: 'added', before: '', after: a.raw });
      else if (b) rows.push({ status: 'removed', before: b.raw, after: '' });
    }
  }
  // 위치기반 폴백(이름 매칭 불가한 매개변수 존재)이면서 실제 매개변수가 있으면, 삽입/삭제 시
  // 인덱스 밀림으로 오귀속될 수 있으므로 positional 경고 플래그를 세운다(reviewer Critical #1).
  const positional = !named && (bb.length > 0 || aa.length > 0);
  return { ...meta, failed: false, rows, beforeCount: bb.length, afterCount: aa.length, positional };
}
const PARAM_STATUS = {
  added: { tone: 'success', label: '추가', mark: '＋' },
  removed: { tone: 'danger', label: '삭제', mark: '－' },
  changed: { tone: 'warning', label: '변경', mark: '~' },
};

// 백틱(`...`)으로 감싼 구간을 <code>로 렌더 — 문서 액션 텍스트의 파라미터명을 코드 스타일로.
function renderInlineCode(text) {
  return String(text).split(/(`[^`]+`)/g).map((p, i) =>
    (p.length > 1 && p.startsWith('`') && p.endsWith('`'))
      ? <code key={i} style={{ fontFamily: 'var(--font-mono, monospace)', background: 'var(--bg)', padding: '0 3px', borderRadius: 3 }}>{p.slice(1, -1)}</code>
      : <span key={i}>{p}</span>
  );
}

// 매개변수 diff(diffSignatureParams 결과)를 한눈 요약 뱃지로 — 원문 raw(+/-) 대신
// "＋int flag / 반환 U8→U16"처럼 '무엇이' 바뀌었는지 직접 보여준다. 반환 { badges, hasChange }.
function summarizeSignatureChange(pdiff) {
  if (!pdiff || pdiff.failed) return { badges: [], hasChange: false, positional: false };
  const badges = [];
  if (pdiff.returnChanged) badges.push({ tone: 'warning', label: `반환 ${pdiff.returnBefore || '(void)'}→${pdiff.returnAfter || '(void)'}` });
  for (const r of pdiff.rows) {
    if (r.status === 'added') badges.push({ tone: 'success', label: `＋${r.after}` });
    else if (r.status === 'removed') badges.push({ tone: 'danger', label: `－${r.before}` });
    else if (r.status === 'changed') badges.push({ tone: 'warning', label: `${r.before} → ${r.after}` });
  }
  return { badges, hasChange: badges.length > 0, positional: !!pdiff.positional };
}

// diffSignatureParams 결과를 (before,after) 키로 캐시 — "변경 상세" 표가 SIGNATURE 행마다
// 재계산하는데, 하단 검색창 타이핑 등으로 컴포넌트가 리렌더되면 매번 전량 재계산된다(reviewer W5).
// 모듈 레벨 Map은 리렌더와 무관하게 유지되어 같은 선언쌍은 1회만 파싱한다(순수함수라 안전).
const _sigDiffCache = new Map();
function diffSignatureParamsCached(before, after) {
  const key = `${before || ''} ${after || ''}`;
  let v = _sigDiffCache.get(key);
  if (v === undefined) {
    v = diffSignatureParams(before, after);
    if (_sigDiffCache.size < 4000) _sigDiffCache.set(key, v);  // 무한 성장 방지(실전 함수 수 << 4000)
  }
  return v;
}

// 함수 변경을 각 문서(UDS/STS/SUTS/SITS/SDS)의 '구체 편집 액션'으로 변환한다.
// 매개변수 diff(pdiff)가 정상이면 실제 파라미터명을 넣어 "무엇을 어느 섹션에" 수준으로 구체화하고,
// 원문이 없으면(pdiff null/failed) change_type 기반의 일반 액션으로 폴백한다. 순수·결정론(LLM 무관).
// 참고: 백엔드 workflow/impact_ai_guide.py의 _DOC_CHANGE_SENSITIVITY도 변경유형→문서 매핑을
//   'AI 영향도 분석 가이드' 패널용으로 독립 유지한다(파라미터 단위 아님) — 한쪽 수정 시 다른 쪽도 검토.
// 반환: { uds:[{section,text,tone}], sts:[...], suts:[...], sits:[...], sds:[...] }
function buildDocumentActions(d, pdiff) {
  const ct = (d.changeType || '').toUpperCase();
  const changed = !!d.changed;
  const ok = !!pdiff && !pdiff.failed;
  const added = ok ? pdiff.rows.filter(r => r.status === 'added') : [];
  const removed = ok ? pdiff.rows.filter(r => r.status === 'removed') : [];
  const chg = ok ? pdiff.rows.filter(r => r.status === 'changed') : [];
  const retChanged = ok && pdiff.returnChanged;
  const posWarn = ok && pdiff.positional;  // 이름 매칭 불가 → 파라미터 귀속이 위치 추정(오귀속 주의)
  const listAfter = (rows) => rows.map(r => `\`${r.after || r.before}\``).join(', ');
  const listBefore = (rows) => rows.map(r => `\`${r.before || r.after}\``).join(', ');
  const pairText = (rows) => rows.map(r => `\`${r.before}\`→\`${r.after}\``).join(', ');
  const reqN = d.requirements?.length || 0;
  const stsN = d.stsTestCases?.length || 0;
  const sutsN = d.sutsTestCases?.length || 0;
  const A = (section, text, tone = 'neutral') => ({ section, text, tone });
  const uds = [], sts = [], suts = [], sits = [], sds = [];

  // 간접 영향(직접 변경 아님): 문서 본문 수정이 아니라 '계약 유지 확인 + 회귀'가 핵심.
  if (!changed) {
    uds.push(A('영향 확인', `직접 변경 아님(${d.hop}) — 호출 인터페이스 계약 유지 시 문서 수정 없음`, 'neutral'));
    sts.push(A('회귀', stsN ? `${stsN}개 관련 TC 재실행 판단` : '직접 매핑 TC 없음', 'neutral'));
    suts.push(A('회귀', sutsN ? `${sutsN}개 단위 TC 재실행` : '관련 단위 TC 없음', 'neutral'));
    sits.push(A('회귀', '통합 콜체인 재실행 — 계약 유지 확인', 'neutral'));
    sds.push(A('상호작용', 'Component Interaction(간접 호출 관계) 유효성 확인', 'neutral'));
    return { uds, sts, suts, sits, sds };
  }

  // ── UDS (단위 상세 설계) ──
  if (ct === 'SIGNATURE') {
    if (posWarn) uds.push(A('주의', '매개변수 이름 매칭 불가 — 아래 귀속은 위치 추정(원문 대조 필요)', 'warning'));
    uds.push(A('Prototype', '함수 선언을 새 시그니처로 교체', 'info'));
    if (added.length) uds.push(A('Input/Output Parameters', `${listAfter(added)} 파라미터 행 추가`, 'success'));
    if (removed.length) uds.push(A('Input/Output Parameters', `${listBefore(removed)} 파라미터 행 삭제`, 'danger'));
    if (chg.length) uds.push(A('Input/Output Parameters', `${pairText(chg)} 타입 변경`, 'warning'));
    if (retChanged) uds.push(A('Return Value', `반환타입 \`${pdiff.returnBefore || '(void)'}\`→\`${pdiff.returnAfter || '(void)'}\` 갱신`, 'warning'));
    // 파라미터/반환 분해 결과가 비었을 때: 파싱 실패(구조 분해 불가)와 실질 무변화(공백/본문)를 구분(reviewer W4).
    if (!added.length && !removed.length && !chg.length && !retChanged) {
      uds.push(pdiff && pdiff.failed
        ? A('Input/Output Parameters', '매개변수 구조 파싱 불가 — 원문 대조 후 반영', 'warning')
        : A('Input/Output Parameters', '매개변수 목록 변화 없음 — 본문/주석/공백 변경 가능(원문 확인)', 'neutral'));
    }
    uds.push(A('Calling Function', '호출부 목록의 인자 사용 영향 확인', 'neutral'));
  } else if (ct === 'BODY') {
    uds.push(A('Description', '변경된 로직을 설명/의사코드에 반영', 'info'));
    uds.push(A('Called Function · Used Globals', '호출 함수·사용 전역 변수 관계 재확인', 'neutral'));
  } else if (ct === 'VARIABLE') {
    uds.push(A('Used Globals', '전역/정적 변수 정의 갱신', 'warning'));
    uds.push(A('Description', '변수 변경에 따른 동작 반영', 'info'));
  } else if (ct === 'NEW') {
    uds.push(A('Function Information', '신규 함수 항목 생성 — Prototype/Parameters/Description/Called·Calling', 'success'));
  } else if (ct === 'DELETE') {
    uds.push(A('Function Information', '해당 함수 항목 제거 및 호출부 참조 정리', 'danger'));
  } else if (ct === 'HEADER') {
    uds.push(A('Interface/Dependency', '헤더 타입·매크로 변경이 인터페이스에 주는 영향 확인', 'neutral'));
  } else {
    // 알 수 없는 change_type 방어(다른 4개 문서와 동일하게 catch-all — reviewer Info #8).
    uds.push(A('Function Information', '변경 내용에 맞게 함수 정보 항목 확인·갱신', 'neutral'));
  }
  if (reqN) uds.push(A('추적성', `연관 요구사항 ${reqN}개와의 매핑 유지 확인`, 'neutral'));

  // ── STS (SW 요구 기반 시험) ──
  if (stsN) {
    if (ct === 'SIGNATURE') {
      if (added.length) sts.push(A('Pre-condition', `${listAfter(added)} 입력 초기 조건 추가`, 'success'));
      sts.push(A('Test Action', `${stsN}개 TC의 함수 호출 인자를 새 시그니처로 갱신`, 'warning'));
      if (retChanged) sts.push(A('Expected Result', '반환값 판정 기준 갱신', 'warning'));
    } else if (ct === 'BODY') {
      sts.push(A('Expected Result', `${stsN}개 TC의 기대 동작 재확인`, 'info'));
      sts.push(A('Test Action', '변경 로직에 맞게 시퀀스 재검토', 'info'));
    } else if (ct === 'VARIABLE') {
      sts.push(A('Pre-condition', '변수 초기값/설정 반영', 'warning'));
    } else if (ct === 'DELETE') {
      sts.push(A('커버리지', `${stsN}개 TC의 요구사항 커버리지 재확인`, 'danger'));
    } else {
      sts.push(A('검토', `${stsN}개 TC 영향 확인`, 'neutral'));
    }
  } else {
    sts.push(A('매핑', reqN ? '요구사항은 있으나 STS TC 미매핑 — 수동 확인' : '직접 매핑 요구사항/TC 없음', 'neutral'));
  }

  // ── SUTS (SW 단위시험) ──
  if (ct === 'SIGNATURE') {
    if (added.length) suts.push(A('Input Variables', `${listAfter(added)} 입력 변수 추가 — 경계값(MIN/MID/MAX/INV) 케이스`, 'success'));
    if (removed.length) suts.push(A('Input Variables', `${listBefore(removed)} 입력 변수 제거`, 'danger'));
    if (chg.length) suts.push(A('Input Variables', `${pairText(chg)} — 타입 변경, 경계값 재계산`, 'warning'));
    if (retChanged) suts.push(A('Output Variables', '기대 출력 타입/값 갱신', 'warning'));
    suts.push(A('회귀', sutsN ? `기존 ${sutsN}개 단위 TC 재검증` : '단위 TC 신규 필요', sutsN ? 'neutral' : 'warning'));
  } else if (ct === 'BODY') {
    suts.push(A('Expected', sutsN ? `${sutsN}개 TC 경계값·기대출력 재계산` : '로직 변경 — TC 없음, 신규 생성 권장', sutsN ? 'info' : 'warning'));
  } else if (ct === 'NEW') {
    suts.push(A('신규 TC', '단위 TC 신규 작성 — 경계값 분석(ABV: MIN/MID/MAX/INV)', 'success'));
  } else if (ct === 'DELETE') {
    suts.push(A('TC 정리', sutsN ? `${sutsN}개 관련 단위 TC 비활성화` : '관련 단위 TC 없음', 'danger'));
  } else if (ct === 'VARIABLE') {
    suts.push(A('입출력', '변수 입출력 매핑 확인', 'warning'));
  } else {
    suts.push(A('확인', sutsN ? `${sutsN}개 단위 TC 검토` : '관련 단위 TC 없음', 'neutral'));
  }

  // ── SITS (SW 통합시험) ──
  if (ct === 'SIGNATURE') {
    sits.push(A('Call Chain', `${d.function}의 콜체인 인자 전달 재검증(호출·피호출 양방향)`, 'warning'));
    if (added.length) sits.push(A('Data Flow', `통합 데이터 흐름에 ${listAfter(added)} 반영`, 'success'));
  } else if (ct === 'BODY') {
    sits.push(A('시나리오', '통합 시나리오 기대값 재확인', 'info'));
  } else if (ct === 'NEW') {
    sits.push(A('콜체인', '신규 함수의 콜체인 포함 여부 및 통합 케이스 확인', 'success'));
  } else if (ct === 'DELETE') {
    sits.push(A('콜체인', '콜체인 단절/대체 경로 확인', 'danger'));
  } else if (ct === 'HEADER') {
    sits.push(A('의존성', '헤더 변경이 콜체인 인터페이스 의존성에 주는 영향 확인', 'neutral'));
  } else {
    sits.push(A('확인', '통합 데이터 흐름 영향 확인', 'neutral'));
  }

  // ── SDS (SW 아키텍처 설계) ──
  if (ct === 'SIGNATURE') {
    sds.push(A('Component Interface', `모듈 인터페이스(포트/파라미터)에 ${(added.length || chg.length) ? '변경 파라미터' : '새 시그니처'} 반영`, 'warning'));
  } else if (ct === 'BODY') {
    sds.push(A('Component Description', '컴포넌트 동작 설명 갱신', 'info'));
  } else if (ct === 'VARIABLE') {
    sds.push(A('Data Flow', '데이터 흐름/인터페이스 갱신', 'warning'));
  } else if (ct === 'NEW') {
    sds.push(A('설계 추가', '신규 컴포넌트/함수 아키텍처 반영', 'success'));
  } else if (ct === 'DELETE') {
    sds.push(A('설계 제거', '아키텍처에서 컴포넌트/함수 제거', 'danger'));
  } else {
    sds.push(A('확인', 'Component Description/State Transition 영향 확인', 'neutral'));
  }

  return { uds, sts, suts, sits, sds };
}

// 함수별 '변경 상세' 셀 — 시그니처는 매개변수 단위 요약 뱃지, 신규/삭제는 원문, 본문 등은 설명.
function renderChangeDetailCell(kind, detail) {
  const mono = { fontFamily: 'var(--font-mono, monospace)', fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-all' };
  if (kind === 'SIGNATURE') {
    if (detail && (detail.before || detail.after)) {
      const pdiff = diffSignatureParamsCached(detail.before, detail.after);
      const summary = summarizeSignatureChange(pdiff);
      const posNote = summary.positional ? '\n⚠ 위치 추정 — 이름 매칭 불가 매개변수 존재(삽입/삭제 위치가 다를 수 있음)' : '';
      const rawTitle = `이전: ${detail.before || '(없음)'}\n이후: ${detail.after || '(없음)'}${posNote}`;
      if (summary.hasChange) {
        // 매개변수 단위 요약 뱃지 — '무엇이' 바뀌었는지 직접 표시. 원문은 title 툴팁으로.
        return (
          <div style={{ display: 'flex', gap: 3, flexWrap: 'wrap', alignItems: 'center' }} title={rawTitle}>
            {summary.positional && <span title="위치 기반 추정 — 삽입/삭제 위치가 다를 수 있음" style={{ fontSize: 10 }}>⚠</span>}
            {summary.badges.map((b, i) => (
              <span key={i} className={`pill pill-${b.tone}`} style={{ fontSize: 9, fontFamily: 'var(--font-mono, monospace)' }}>{b.label}</span>
            ))}
          </div>
        );
      }
      // hasChange=false → 파싱 실패(구조 분해 불가)와 파싱 성공+실질 무변화(공백/본문)를 구분(reviewer W4).
      const fbTitle = pdiff?.failed ? '매개변수 구조 파싱 불가 — 원문 대조' : '매개변수 변화 없음(공백/본문 등) — 원문 대조';
      return (
        <div style={mono} title={fbTitle}>
          {detail.before && <div style={{ color: 'var(--color-danger)' }}>− {detail.before}</div>}
          {detail.after && <div style={{ color: 'var(--color-success)' }}>＋ {detail.after}</div>}
        </div>
      );
    }
    return <span className="text-muted" style={{ fontSize: 11 }}>파라미터/리턴타입 변경 (원문 미확보)</span>;
  }
  if (kind === 'NEW') {
    return detail?.after
      ? <span style={{ ...mono, color: 'var(--color-success)' }}>＋ {detail.after}</span>
      : <span className="text-muted" style={{ fontSize: 11 }}>신규 함수 추가</span>;
  }
  if (kind === 'DELETE') {
    return detail?.before
      ? <span style={{ ...mono, color: 'var(--color-danger)' }}>− {detail.before}</span>
      : <span className="text-muted" style={{ fontSize: 11 }}>함수 제거됨</span>;
  }
  if (kind === 'HEADER') return <span className="text-muted" style={{ fontSize: 11 }}>헤더(매크로/타입) 변경</span>;
  if (kind === 'VARIABLE') return <span className="text-muted" style={{ fontSize: 11 }}>전역 변수 변경</span>;
  return <span className="text-muted" style={{ fontSize: 11 }}>본문(로직) 변경</span>;
}

// 함수별 VectorCAST 커버리지 셀 — ASIL 타깃 메트릭 % + 충족 여부 + 직전 대비 Δ.
function renderCoverageCell(cov) {
  if (!cov) return <span className="text-muted">-</span>;
  const cur = cov.current_rate;
  const metricKo = COVERAGE_METRIC_KO[cov.target_metric] || cov.target_metric;
  // 매칭됐으나 타깃 메트릭 미측정(예: 리포트에 MC/DC 컬럼 없음) — 빨강 '미달(실패)'이 아니라
  // 노랑 '미측정(증거 부재)'으로 표시해 false 미달 경보를 막는다.
  if (cov.unmeasured_target) {
    return (
      <span title={`${metricKo} 미측정 — 이 리포트에 ${metricKo} 데이터가 없습니다(증거 부재, 시험 실패 아님). 별도 ${metricKo} 리포트가 필요합니다.`}>
        <span className="pill pill-warning" style={{ fontSize: 9 }}>{metricKo} 미측정</span>
      </span>
    );
  }
  const pct = (typeof cur === 'number') ? `${Math.round(cur * 100)}%` : '—';
  const d = cov.delta;
  let deltaEl = null;
  if (typeof d === 'number' && Math.abs(d) > 1e-9) {
    const down = d < 0;
    deltaEl = (
      <span style={{ color: down ? 'var(--color-danger)' : 'var(--color-success)', marginLeft: 4, fontSize: 9 }}>
        {down ? '▼' : '▲'}{Math.abs(Math.round(d * 100))}
      </span>
    );
  }
  return (
    <span title={`${metricKo} 커버리지 ${pct} (목표 100%)${typeof d === 'number' ? `, 직전 대비 ${(d * 100).toFixed(0)}%p` : ''}`}>
      <span className={`pill ${cov.meets_target ? 'pill-success' : 'pill-danger'}`} style={{ fontSize: 9 }}>
        {metricKo} {pct}
      </span>
      {deltaEl}
    </span>
  );
}

const DOC_STATUS = {
  review_required: { tone: 'warning', label: '검토 필요' },
  completed: { tone: 'success', label: '완료' },
  planned: { tone: 'info', label: '계획됨' },
  skipped: { tone: 'neutral', label: '건너뜀' },
  failed: { tone: 'danger', label: '실패' },
};

export default function ImpactGuideSection({ analysisResult }) {
  const toast = useToast();

  const impact = analysisResult?.impactData;
  const [guide, setGuide] = useState(null);
  const [aiGuide, setAiGuide] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedFn, setSelectedFn] = useState(null);
  // 선택 함수의 Gemini 변경 설명(함수별). fn이 바뀌면 폐기.
  const [explain, setExplain] = useState({ fn: null, text: '', loading: false, error: '' });
  // 현재 선택 함수 ref — fetchExplanation의 늦은 응답이 다른 함수로 전환 후 덮어쓰는 race 방지.
  const selectedFnRef = useRef(null);
  useEffect(() => { selectedFnRef.current = selectedFn; }, [selectedFn]);
  // 상세 모달 열렸을 때 Escape로 닫기(a11y).
  useEffect(() => {
    if (!selectedFn) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') setSelectedFn(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [selectedFn]);
  const [searchTerm, setSearchTerm] = useState('');
  const [hopFilter, setHopFilter] = useState('all');
  const [docFilter, setDocFilter] = useState('all');
  const [demoMode, setDemoMode] = useState(false);

  // Impact data from analysis
  const changedFiles = impact?.trigger?.changed_files ?? impact?.changed_files ?? [];
  const changedFunctions = impact?.changed_function_types ?? {};
  const changedFnEntries = Object.entries(changedFunctions);
  const actions = impact?.actions ?? impact?.documents ?? {};
  const linkedDocs = impact?._linked_docs
    ?? analysisResult?.matchedScm?.linked_docs
    ?? analysisResult?.scmList?.[0]?.linked_docs
    ?? {};
  const impactGroups = impact?.impact ?? {};
  // 분류 정밀도(백엔드 classification). "file"=파일단위 보수 분류 → "변경 함수" 수가
  // "변경 파일 내 전체 함수"의 과대추정(실제 수정 함수는 더 적음). "line"=라인 diff 정밀.
  const classification = impact?.classification ?? null;
  const isConservativeCount = classification?.granularity === 'file';
  // "line"=라인 diff 정밀 분류 적용됨(SIGNATURE/NEW/DELETE 함수단위 판별). 축소 파일/제외 함수 수.
  const isLineClassified = classification?.granularity === 'line';
  // 백엔드 ISO 증거: 함수별 메타(ASIL 등) + 경고(과소보고/cloudium/ASIL escalation 등) + ASIL 요약.
  const functionMeta = impact?.function_meta ?? {};
  const impactWarnings = Array.isArray(impact?.warnings) ? impact.warnings : [];
  const asilInfo = impact?.asil ?? null;
  // MC/DC delta: 영향 함수별 VectorCAST 커버리지(ASIL 타깃 대비 gap + 이력 delta).
  const coverageGap = impact?.coverage_gap ?? null;
  const coverageByFn = useMemo(() => {
    const m = {};
    for (const r of (coverageGap?.functions || [])) { if (r.function) m[r.function] = r; }
    return m;
  }, [coverageGap]);
  // 회귀시험 선정: 영향 함수 → 재실행 대상 SUTS TC / SITS call-chain(ISO 26262 증거).
  const regressionSet = impact?.regression_test_set ?? null;

  // Demo data for testing — simulates real .c file changes
  const demoFunctions = {
    'g_DrvIn_Main': 'BODY',
    'g_DrvIn_MotorSpeed': 'BODY',
    's_MotorSpdCtrl_AutoClose': 'BODY',
    's_MotorSpdCtrl_AutoOpen': 'SIGNATURE',
    's_AntipinchDetect_Close': 'BODY',
    'g_Ap_BuzzerCtrl_Func': 'BODY',
    's_DoorStateCtrl': 'BODY',
    'g_SystemStatusCheck': 'VARIABLE',
  };
  const demoImpact = {
    direct: ['g_DrvIn_Main', 'g_DrvIn_MotorSpeed', 's_MotorSpdCtrl_AutoClose', 's_MotorSpdCtrl_AutoOpen', 's_AntipinchDetect_Close'],
    // s_NotifyObserver는 demoFunctions(변경 목록)에 없음 → 간접 전용(changed=false) 행으로 표시되어
    // 데모만으로 '영향' 배지·1-hop 필터 실동작을 확인할 수 있다(간접 함수 노출 회귀 방지).
    indirect_1hop: ['g_Ap_BuzzerCtrl_Func', 's_DoorStateCtrl', 's_NotifyObserver'],
    indirect_2hop: ['g_SystemStatusCheck'],
  };
  const activeFnEntries = demoMode ? Object.entries(demoFunctions) : changedFnEntries;
  const activeImpactGroups = demoMode ? demoImpact : impactGroups;
  const activeChangedFiles = demoMode ? ['DrvIn_Main_PDS.c', 'Ap_MotorCtrl_PDS.c'] : changedFiles;
  // 함수별 변경 상세(시그니처 이전→이후 원문). 키는 소문자 함수명(백엔드 changed_types와 동일).
  const changeDetails = impact?.change_details ?? {};
  // 변경종류 요약(신규/삭제/시그니처/본문/헤더/변수 개수) — 데모 포함(activeFnEntries 기준).
  const changeSummary = { NEW: 0, DELETE: 0, SIGNATURE: 0, BODY: 0, HEADER: 0, VARIABLE: 0 };
  for (const [, k] of activeFnEntries) { if (k in changeSummary) changeSummary[k] += 1; }

  const filteredGuide = useMemo(() => {
    if (!guide) return [];
    let items = guide.details;
    if (hopFilter !== 'all') items = items.filter(d => d.hop === hopFilter);
    if (docFilter === 'has_reqs') items = items.filter(d => d.requirements.length > 0);
    else if (docFilter === 'has_sts') items = items.filter(d => d.stsTestCases.length > 0);
    else if (docFilter === 'has_suts') items = items.filter(d => d.sutsTestCases.length > 0);
    // '매핑 없음'은 요구사항·STS·SUTS TC가 모두 없을 때만 — SUTS TC만 있는 함수를 '매핑 없음'으로
    // 오분류하던 버그 수정(SUTS TC도 실제 매핑 증거).
    else if (docFilter === 'no_mapping') items = items.filter(d => d.requirements.length === 0 && d.stsTestCases.length === 0 && d.sutsTestCases.length === 0);
    if (searchTerm.trim()) {
      const q = searchTerm.trim().toLowerCase();
      items = items.filter(d =>
        d.function.toLowerCase().includes(q) ||
        d.requirements.some(r => r.toLowerCase().includes(q)) ||
        d.stsTestCases.some(tc => tc.toLowerCase().includes(q)) ||
        d.sutsTestCases.some(tc => tc.toLowerCase().includes(q))
      );
    }
    return items;
  }, [guide, hopFilter, docFilter, searchTerm]);

  // Build detailed guide
  const buildGuide = useCallback(async () => {
    if (!activeFnEntries.length) {
      toast('info', '변경된 함수가 없습니다.');
      return;
    }
    setLoading(true);
    try {
      // 추출 API 실패를 삼키지 않고 수집 — '매핑 없음'(실제 부재)과 '조회 실패'(403/500/네트워크)를
      // 구분해 사용자에게 표면화한다. 과거 catch(_){}로 실패해도 성공 토스트가 뜨던 silent 버그 방지.
      const fetchFailures = [];
      let udsMapping = [];
      let stsTCs = [];
      let sutsTCs = [];

      if (demoMode) {
        // 데모: 실제 추출 API를 데모 함수명으로 호출하면 매핑이 항상 비므로 데모 매핑을 직접 주입해
        // 요구사항/STS/SUTS TC가 채워진 완전한 시나리오를 보여준다(과거엔 빈 가이드만 나왔다).
        udsMapping = DEMO_UDS_MAPPING;
        stsTCs = DEMO_STS_TCS;
        sutsTCs = DEMO_SUTS_TCS;
      } else {
        // 1. UDS func→req mapping
        if (linkedDocs.uds) {
          try {
            const d = await post('/api/jenkins/uds/extract-mapping', { uds_path: linkedDocs.uds });
            udsMapping = d?.mapping_pairs ?? [];
          } catch (e) { fetchFailures.push({ doc: 'UDS', msg: e?.message || '조회 실패' }); }
        }

        // 2. STS req→TC mapping
        if (linkedDocs.sts) {
          try {
            const d = await post('/api/jenkins/sts/extract-traceability', { path: linkedDocs.sts, doc_type: 'sts' });
            stsTCs = d?.vcast_rows ?? [];
            // N21: 외부 형식 SUTS/STS — 시트 미인식 시 사용자에게 명확 안내
            if (!stsTCs.length && Array.isArray(d?.available_sheets) && typeof toast === 'function') {
              toast('warning', `STS 시트 미인식. 사용 가능한 시트: ${d.available_sheets.join(', ')}`);
            }
          } catch (e) { fetchFailures.push({ doc: 'STS', msg: e?.message || '조회 실패' }); }
        }

        // 3. SUTS func→TC mapping
        if (linkedDocs.suts) {
          try {
            const d = await post('/api/jenkins/sts/extract-traceability', { path: linkedDocs.suts, doc_type: 'suts' });
            sutsTCs = d?.vcast_rows ?? [];
            if (!sutsTCs.length && Array.isArray(d?.available_sheets) && typeof toast === 'function') {
              toast('warning', `SUTS 시트 미인식. 사용 가능한 시트: ${d.available_sheets.join(', ')}`);
            }
          } catch (e) { fetchFailures.push({ doc: 'SUTS', msg: e?.message || '조회 실패' }); }
        }
      }

      // Build per-function guide
      const funcToReqs = {};
      for (const mp of udsMapping) {
        for (const fn of (mp.source_ids || [])) {
          if (!funcToReqs[fn]) funcToReqs[fn] = new Set();
          funcToReqs[fn].add(mp.requirement_id);
        }
      }

      const reqToStsTCs = {};
      for (const row of stsTCs) {
        if (!reqToStsTCs[row.requirement_id]) reqToStsTCs[row.requirement_id] = new Set();
        reqToStsTCs[row.requirement_id].add(row.testcase);
      }

      const fnToSutsTCs = {};
      for (const row of sutsTCs) {
        const fn = row.unit || '';
        if (!fnToSutsTCs[fn]) fnToSutsTCs[fn] = new Set();
        fnToSutsTCs[fn].add(row.testcase);
      }

      const details = [];
      const allReqs = new Set();
      const allStsTcs = new Set();

      // 가이드 행 = 변경(직접) 함수 ∪ 간접 영향 함수(1/2hop). 과거엔 changed 함수만 순회해서
      // 모든 행의 hop이 'direct'로 고정 → 1-hop/2-hop 필터가 영구히 죽고, 간접 영향 ASIL 함수가
      // 가이드에서 통째로 누락(ISO 26262 under-report)됐다. 간접 함수는 변경종류 없음(changed=false)으로
      // 구분 표기하되, backend function_meta의 ASIL·커버리지·요구/시험 매핑은 동일하게 조인한다.
      const changedMap = new Map(activeFnEntries.map(([fn, k]) => [fn, k]));
      const guideFns = [...new Set([
        ...changedMap.keys(),
        ...(activeImpactGroups.direct || []),
        ...(activeImpactGroups.indirect_1hop || []),
        ...(activeImpactGroups.indirect_2hop || []),
      ].filter(Boolean))];

      for (const fn of guideFns) {
        const changeType = changedMap.get(fn) || '';
        const isChanged = changedMap.has(fn);
        const reqs = funcToReqs[fn] ? [...funcToReqs[fn]] : [];
        reqs.forEach(r => allReqs.add(r));

        const stsTcSet = new Set();
        for (const rid of reqs) {
          (reqToStsTCs[rid] || new Set()).forEach(tc => { stsTcSet.add(tc); allStsTcs.add(tc); });
        }

        const sutsTcList = fnToSutsTCs[fn] ? [...fnToSutsTCs[fn]] : [];
        const hop = (activeImpactGroups.direct || []).includes(fn) ? 'direct'
          : (activeImpactGroups.indirect_1hop || []).includes(fn) ? '1-hop'
          : (activeImpactGroups.indirect_2hop || []).includes(fn) ? '2-hop'
          : (isChanged ? 'direct' : '1-hop');

        details.push({
          function: fn,
          changeType,
          changed: isChanged,
          asil: functionMeta[fn]?.asil || '',
          coverage: coverageByFn[fn] || null,
          hop,
          requirements: reqs,
          stsTestCases: [...stsTcSet],
          sutsTestCases: sutsTcList,
        });
      }
      // 직접(변경) → 1-hop → 2-hop 순으로 정렬(변경 함수 우선 노출), 동일 hop은 함수명순.
      const HOP_RANK = { direct: 0, '1-hop': 1, '2-hop': 2 };
      details.sort((a, b) => (HOP_RANK[a.hop] - HOP_RANK[b.hop]) || a.function.localeCompare(b.function));

      setGuide({
        details,
        fetchFailures,
        summary: {
          impactedReqs: allReqs.size,
          impactedStsTCs: allStsTcs.size,
        },
      });

      // Fetch AI risk/cross-doc guide (best-effort)
      try {
        const aiData = await post('/api/impact/ai-guide', {
          changed_types: Object.fromEntries(activeFnEntries),
          impact_groups: activeImpactGroups,
          // 함수별 ASIL을 함께 보내 위험평가가 실제 ASIL을 반영(없으면 'ASIL 미상'으로 정직 표시).
          by_name: Object.fromEntries(
            Object.entries(functionMeta).map(([fn, m]) => [fn, { asil: m?.asil || '' }]),
          ),
        });
        if (aiData?.ok) setAiGuide(aiData.guide);
      } catch (_) { /* AI guide is optional */ }

      if (fetchFailures.length) {
        toast('warning', `${fetchFailures.map(f => f.doc).join('/')} 매핑 조회 실패 — 해당 문서의 요구사항/TC 매핑이 누락됐을 수 있습니다('매핑 없음'이 실제 부재가 아닐 수 있음)`);
      } else {
        toast('success', '영향도 가이드 생성 완료');
      }
    } catch (e) {
      toast('error', `가이드 생성 실패: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [activeFnEntries, linkedDocs, actions, activeImpactGroups, demoMode, functionMeta, coverageByFn, toast]);


  // 영향받은 함수 집합(직접+간접+변경)을 추적성 매트릭스 focus로 넘기고 SRS/SDS 탭으로 이동.
  // 기존 추적성 UI(SrsSdsSection의 V-model 매트릭스 + 정/역방향 공백 분석)를 재사용해
  // "이 변경이 어떤 요구사항/시험/커버리지 공백에 닿는지"를 그 화면에서 본다.
  const openInTraceability = useCallback(() => {
    const fns = [...new Set([
      ...activeFnEntries.map(([fn]) => fn),
      ...(activeImpactGroups.direct || []),
      ...(activeImpactGroups.indirect_1hop || []),
      ...(activeImpactGroups.indirect_2hop || []),
    ].filter(Boolean))];
    if (!fns.length) {
      toast('info', '영향받은 함수가 없습니다.');
      return;
    }
    try {
      localStorage.setItem('devops_v2_trace_focus', JSON.stringify({
        functions: fns, label: `변경 영향 함수 ${fns.length}개`, ts: Date.now(),
      }));
    } catch (_) { /* ignore */ }
    if (typeof window.__detailSection === 'function') {
      window.__detailSection('srssds');
    } else {
      toast('info', '추적성 매트릭스 탭으로 이동할 수 없습니다. SRS/SDS 탭을 직접 열어주세요.');
    }
  }, [activeFnEntries, activeImpactGroups, toast]);

  // 현재 영향도 분석 결과를 Markdown 리포트로 내보낸다(브라우저 다운로드, 외부 요청 없음).
  // guide 생성 전에도 요약/변경상세/ASIL/커버리지/회귀는 내보낼 수 있고, guide가 있으면 함수별 표까지 포함.
  const exportGuideMarkdown = useCallback(() => {
    if (!activeFnEntries.length) {
      toast('info', '내보낼 변경 함수가 없습니다.');
      return;
    }
    const stamp = new Date().toISOString().replace('T', ' ').slice(0, 19);
    const L = [];
    L.push('# 변경 영향도 분석 결과');
    L.push('');
    L.push(`- 생성 시각: ${stamp}`);
    if (demoMode) L.push('- ⚠ 데모 시나리오 (시뮬레이션 데이터)');
    L.push(`- 변경 파일: ${activeChangedFiles.length}`);
    L.push(`- 변경 함수: ${activeFnEntries.length} (신규 ${changeSummary.NEW} / 삭제 ${changeSummary.DELETE} / 시그니처 ${changeSummary.SIGNATURE} / 본문 ${changeSummary.BODY} / 헤더 ${changeSummary.HEADER} / 변수 ${changeSummary.VARIABLE})`);
    L.push(`- 직접 영향: ${(activeImpactGroups.direct || []).length} / 간접: ${(activeImpactGroups.indirect_1hop || []).length + (activeImpactGroups.indirect_2hop || []).length}`);
    if (asilInfo && (asilInfo.max_changed || asilInfo.escalation || asilInfo.unknown_changed_count)) {
      L.push('', '## ASIL 차등 검증');
      L.push(`- 변경 최대 ASIL: ${asilInfo.max_changed || '미상'}`);
      if (asilInfo.escalation) L.push('- ⚠ Escalation (ASIL B+ 직접 변경 — AUTO→검토)');
      if (asilInfo.mcdc_required) L.push('- MC/DC 필수');
      if (asilInfo.coverage_target) L.push(`- 커버리지 타깃: ${asilInfo.coverage_target}`);
      if (asilInfo.unknown_changed_count) L.push(`- ASIL 미상 직접변경: ${asilInfo.unknown_changed_count}개 (수동 확인 필요)`);
    }
    if (coverageGap?.available && coverageGap.summary) {
      const s = coverageGap.summary;
      L.push('', '## 커버리지 (ASIL 타깃 대비)');
      L.push(`- 평가 ${s.evaluated ?? 0} / 목표 미달 ${s.below_target ?? 0} / 미측정 ${s.unmeasured ?? 0} / 직전 대비 회귀 ${s.regressed ?? 0}`);
    }
    if (regressionSet?.summary) {
      L.push('', '## 회귀시험 선정 (재실행 대상)');
      L.push(`- SUTS 재실행 TC: ${regressionSet.summary.suts_tc_count ?? 0} / SITS 영향 체인: ${regressionSet.summary.sits_chain_count ?? 0}`);
    }
    L.push('', '## 변경 함수');
    for (const [fn, kind] of activeFnEntries) L.push(`- \`${fn}\` : ${CHANGE_TYPE_KO[kind] || kind}`);
    if (guide?.details?.length) {
      L.push('', '## 함수별 영향 가이드 (직접 변경 + 간접 영향)');
      L.push('| 함수 | 변경 | ASIL | 영향 | 요구사항 | STS TC | SUTS TC |');
      L.push('|------|------|------|------|----------|--------|---------|');
      for (const d of guide.details) {
        const chLabel = d.changed ? (CHANGE_TYPE_KO[d.changeType] || d.changeType) : '영향(간접)';
        L.push(`| \`${d.function}\` | ${chLabel} | ${d.asil || '미상'} | ${d.hop} | ${(d.requirements || []).join(' ') || '-'} | ${(d.stsTestCases || []).length} | ${(d.sutsTestCases || []).length} |`);
      }
    }
    if (aiGuide?.risk) {
      L.push('', '## AI 위험 평가');
      L.push(`- 등급: ${aiGuide.risk.grade} (${aiGuide.risk.score}/100), 최대 ASIL: ${aiGuide.risk.max_asil}`);
      if (aiGuide.risk.justification) L.push(`- 근거: ${aiGuide.risk.justification}`);
    }
    L.push('');
    downloadTextFile(`impact_analysis_${stamp.replace(/[: -]/g, '').slice(0, 14)}.md`, L.join('\n'));
    toast('success', '영향도 분석 결과를 내보냈습니다.');
  }, [activeFnEntries, activeChangedFiles, changeSummary, activeImpactGroups, asilInfo, coverageGap, regressionSet, guide, aiGuide, demoMode, toast]);

  // 선택 함수의 변경을 Gemini로 설명(선언 원문 before/after 포함). LLM 미설정이면 ok=false로 폴백.
  const fetchExplanation = useCallback(async (d) => {
    if (!d) return;
    const cd = changeDetails[String(d.function).toLowerCase()] || {};
    setExplain({ fn: d.function, text: '', loading: true, error: '' });
    try {
      const res = await post('/api/impact/explain-change', {
        function: d.function,
        change_type: d.changeType || '',
        before: cd.before || '',
        after: cd.after || '',
        asil: d.asil || '',
        // function_meta는 원본 케이스 키(impact_orchestrator.py:1326 fn 그대로) — change_details처럼
        // 소문자화하면 대소문자 혼용 함수명(g_DrvIn_Main 등)에서 조회 실패 → module 상시 공백(reviewer W2).
        module: functionMeta[d.function]?.module || '',
        requirements: (d.requirements || []).slice(0, 12),
      });
      // race 가드: 응답 도착 시 사용자가 이미 다른 함수로 전환했으면 결과 폐기(오표시/슬롯 오염 방지).
      if (selectedFnRef.current !== d.function) return;
      if (res?.ok && res.explanation) {
        setExplain({ fn: d.function, text: res.explanation, loading: false, error: '' });
      } else {
        setExplain({ fn: d.function, text: '', loading: false, error: res?.error || 'AI 설명을 가져오지 못했습니다(LLM 미설정일 수 있음).' });
      }
    } catch (e) {
      setExplain({ fn: d.function, text: '', loading: false, error: e?.message || 'AI 설명 요청 실패' });
    }
  }, [changeDetails, functionMeta]);

  if (!impact && !demoMode) {
    return (
      <div className="empty-state">
        <div className="empty-icon">🔍</div>
        <div className="empty-title">변경 영향도 분석 결과가 없습니다</div>
        <div className="empty-desc">대시보드에서 동기화 & 분석을 실행하세요.<br />SCM에 base_ref가 설정되어야 변경 파일을 감지합니다.</div>
        <button className="btn-primary btn-sm" style={{ marginTop: 8 }} onClick={() => setDemoMode(true)}>데모 시나리오로 보기</button>
      </div>
    );
  }

  return (
    <div>
      {/* 백엔드 경고 표면화 — 과소보고/cloudium degrade/revision 불일치/ASIL escalation 등.
          0 영향을 '영향 없음'으로 오인하지 않도록 안전 신호를 의사결정 화면에 노출. */}
      {impactWarnings.length > 0 && (
        <div className="panel" style={{ marginBottom: 12, borderLeft: '3px solid var(--color-warning)' }}>
          <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>⚠️ 분석 경고 ({impactWarnings.length})</div>
          {impactWarnings.map((w, i) => {
            const danger = /under-reported|empty|escalation|미상|과소|MC\/DC|unavailable/i.test(String(w));
            return (
              <div key={i} className="text-sm" style={{ color: danger ? 'var(--color-danger)' : 'var(--text-muted)', padding: '1px 0' }}>
                • {w}
              </div>
            );
          })}
        </div>
      )}
      {/* ASIL 차등 검증 — 직접 변경 함수의 최대 ASIL → 검증강도(escalation·MC/DC 필수·커버리지 타깃)
          를 결정론적으로 표면화(ai-guide 선택 호출과 독립, 항상 노출). 미상은 QM 단정 금지로 경고. */}
      {asilInfo && (asilInfo.max_changed || asilInfo.escalation || (asilInfo.unknown_changed_count || 0) > 0) && (
        <div className="panel" style={{ marginBottom: 12, borderLeft: `3px solid ${asilInfo.escalation ? 'var(--color-danger)' : 'var(--border)'}` }}>
          <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>🛡️ ASIL 차등 검증</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', fontSize: 11 }}>
            <span>변경 최대 ASIL:&nbsp;
              {asilInfo.max_changed && /^[A-D]$/.test(asilInfo.max_changed)
                ? <span className={`pill ${/[CD]/.test(asilInfo.max_changed) ? 'pill-danger' : 'pill-warning'}`} style={{ fontSize: 9 }}>{asilInfo.max_changed}</span>
                : <span className="text-muted">미상</span>}
            </span>
            {asilInfo.escalation && <StatusBadge tone="danger">Escalation (ASIL B+ 직접변경 — AUTO→검토)</StatusBadge>}
            {asilInfo.mcdc_required && <span className="pill pill-danger" style={{ fontSize: 9 }}>MC/DC 필수</span>}
            {asilInfo.coverage_target && <span className="pill pill-info" style={{ fontSize: 9 }}>커버리지 타깃: {asilInfo.coverage_target}</span>}
            {(asilInfo.unknown_changed_count || 0) > 0 && (
              <span className="pill pill-warning" style={{ fontSize: 9 }} title="ASIL 미상 직접변경 — 안전 등급 수동 확인 필요(QM 단정 금지)">
                ASIL 미상 {asilInfo.unknown_changed_count}개
              </span>
            )}
          </div>
        </div>
      )}
      {/* MC/DC delta — VectorCAST 커버리지 ASIL 타깃 대비 gap + 이력 회귀 요약. */}
      {coverageGap?.available && (
        <div className="panel" style={{ marginBottom: 12,
          borderLeft: `3px solid ${(coverageGap.summary?.below_target || coverageGap.summary?.regressed) ? 'var(--color-danger)' : 'var(--color-success)'}` }}>
          <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>
            🎯 커버리지 (ASIL 타깃 대비)
          </div>
          <div className="stats-row">
            <div className="stat-card">
              <div className="text-muted text-sm">평가된 영향 함수</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{coverageGap.summary?.evaluated ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="text-muted text-sm">목표 미달</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: coverageGap.summary?.below_target ? 'var(--color-danger)' : undefined }}>
                {coverageGap.summary?.below_target ?? 0}
              </div>
            </div>
            <div className="stat-card" title="매칭됐으나 해당 ASIL 타깃 메트릭(예: MC/DC) 데이터가 리포트에 없는 함수 — 증거 부재(시험 실패 아님)">
              <div className="text-muted text-sm">미측정</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: coverageGap.summary?.unmeasured ? 'var(--color-warning)' : undefined }}>
                {coverageGap.summary?.unmeasured ?? 0}
              </div>
            </div>
            <div className="stat-card">
              <div className="text-muted text-sm">직전 대비 회귀</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: coverageGap.summary?.regressed ? 'var(--color-danger)' : undefined }}>
                {coverageGap.summary?.regressed ?? 0}
              </div>
            </div>
          </div>
          {!coverageGap.summary?.had_baseline && (
            <div className="text-muted text-sm" style={{ marginTop: 4 }}>직전 스냅샷 없음 — 이번 실행을 기준으로 저장(다음 분석부터 Δ 표시).</div>
          )}
        </div>
      )}
      {/* 회귀시험 선정 — 영향 함수에 매핑된 기존 SUTS TC / SITS call-chain(재실행 대상 증거, ISO 26262). */}
      {regressionSet?.summary && ((regressionSet.summary.suts_tc_count || 0) > 0 || (regressionSet.summary.sits_chain_count || 0) > 0) && (
        <div className="panel" style={{ marginBottom: 12, borderLeft: '3px solid var(--color-info)' }}>
          <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>🔁 회귀시험 선정 (재실행 대상)</div>
          <div className="stats-row">
            <div className="stat-card">
              <div className="text-muted text-sm">영향 함수</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{regressionSet.summary.impacted_function_count ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="text-muted text-sm">SUTS 재실행 TC</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{regressionSet.summary.suts_tc_count ?? 0}</div>
            </div>
            <div className="stat-card">
              <div className="text-muted text-sm">SITS 영향 체인</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{regressionSet.summary.sits_chain_count ?? 0}</div>
            </div>
          </div>
          {Object.keys(regressionSet.suts || {}).length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>SUTS 재실행 TC (함수별)</div>
              <div style={{ maxHeight: 120, overflow: 'auto' }}>
                {Object.entries(regressionSet.suts).slice(0, 12).map(([fn, tcs]) => (
                  <div key={fn} style={{ fontSize: 10, padding: '2px 0' }}>
                    <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{fn}</span>
                    <span className="text-muted"> — {(tcs || []).length} TC </span>
                    {(tcs || []).slice(0, 6).map((tc, i) => (
                      <span key={i} className="pill pill-neutral" style={{ fontSize: 8, margin: 1 }}>{tc}</span>
                    ))}
                    {(tcs || []).length > 6 && <span className="text-muted" style={{ fontSize: 8 }}> +{(tcs || []).length - 6}</span>}
                  </div>
                ))}
                {Object.keys(regressionSet.suts).length > 12 && (
                  <div className="text-muted" style={{ fontSize: 9 }}>+{Object.keys(regressionSet.suts).length - 12}개 함수 더</div>
                )}
              </div>
            </div>
          )}
          {Object.keys(regressionSet.sits || {}).length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>SITS 영향 call-chain (함수별)</div>
              <div style={{ maxHeight: 140, overflow: 'auto' }}>
                {Object.entries(regressionSet.sits).slice(0, 10).map(([fn, chains]) => (
                  <div key={fn} style={{ fontSize: 10, padding: '2px 0' }}>
                    <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{fn}</span>
                    <span className="text-muted"> — {(chains || []).length} 체인</span>
                    <div style={{ marginLeft: 10 }}>
                      {(chains || []).slice(0, 4).map((c, i) => (
                        <div key={i} title={c} style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: 'monospace', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>↳ {c}</div>
                      ))}
                      {(chains || []).length > 4 && <div className="text-muted" style={{ fontSize: 9 }}>+{(chains || []).length - 4}개 더</div>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      {/* Summary */}
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-header">
          <span className="panel-title">변경 영향도 요약</span>
          <div style={{ display: 'flex', gap: 4 }}>
            <button className="btn-primary btn-sm" onClick={buildGuide} disabled={loading}>
              {loading ? '분석 중...' : '상세 가이드 생성'}
            </button>
            <button className="btn-sm" onClick={openInTraceability}
              title="영향받은 함수 집합으로 추적성 매트릭스(SRS↔SDS↔UDS↔STS↔SUTS↔SITS)를 필터해서 봅니다">
              추적성 매트릭스에서 보기
            </button>
            <button className="btn-sm" onClick={exportGuideMarkdown}
              title="현재 영향도 분석 결과를 Markdown 리포트로 다운로드합니다">
              내보내기
            </button>
            <button className="btn-sm" onClick={() => setDemoMode(!demoMode)}>
              {demoMode ? '실제 데이터' : '데모 시나리오'}
            </button>
          </div>
        </div>

        {demoMode && <div className="pill pill-warning" style={{ marginBottom: 8 }}>데모 모드 — 시뮬레이션 데이터</div>}

        <div className="stats-row">
          <div className="stat-card">
            <div className="stat-value">{activeChangedFiles.length}</div>
            <div className="stat-label">변경 파일</div>
          </div>
          <div className="stat-card" title={
            isConservativeCount ? '파일단위 보수 분류 — 변경된 파일에 속한 전체 함수를 집계합니다. 라인 diff가 없어 실제 수정된 함수는 이보다 적을 수 있습니다.'
              : isLineClassified ? `라인 diff 정밀 분류 — 시그니처/신규/삭제를 함수단위로 판별. ${classification?.line_classified_file_count || 0}개 파일을 함수단위로 축소(라인변경 없는 ${classification?.narrow_removed_count || 0}개 함수 제외).`
              : undefined}>
            <div className="stat-value">{activeFnEntries.length}</div>
            <div className="stat-label">
              변경 함수
              {isConservativeCount && <span className="text-muted" style={{ fontSize: 9, marginLeft: 3 }}>(보수 추정)</span>}
              {isLineClassified && <span className="pill pill-success" style={{ fontSize: 8, marginLeft: 3 }}>정밀</span>}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{(activeImpactGroups.direct || []).length}</div>
            <div className="stat-label">직접 영향</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{(activeImpactGroups.indirect_1hop || []).length + (activeImpactGroups.indirect_2hop || []).length}</div>
            <div className="stat-label">간접 영향</div>
          </div>
          {guide && (
            <>
              <div className="stat-card" style={{ borderLeft: '3px solid var(--color-warning)' }}>
                <div className="stat-value">{guide.summary.impactedReqs}</div>
                <div className="stat-label">영향 요구사항</div>
              </div>
              <div className="stat-card" style={{ borderLeft: '3px solid var(--color-info)' }}>
                <div className="stat-value">{guide.summary.impactedStsTCs}</div>
                <div className="stat-label">검토 TC</div>
              </div>
            </>
          )}
        </div>

        {/* Document impact status */}
        {(() => {
          // Build doc stats from guide details or actions
          const docStats = {};
          if (guide) {
            // 가이드 표(직접 변경 + 간접 영향)와 동일 스코프로 집계 — 간접 함수가 특정 문서에
            // 매핑되면 그 문서도 '검토 필요'로 표시한다. 요약 카드의 impactedReqs/impactedStsTCs가
            // 이미 전체(간접 포함) 스코프라, 칩 count도 동일 스코프여야 "영향 없음 + N TC" 모순이 없다.
            for (const d of guide.details) {
              if (d.requirements.length > 0) { docStats.uds = (docStats.uds || 0) + 1; }
              if (d.stsTestCases.length > 0) { docStats.sts = (docStats.sts || 0) + 1; }
              if (d.sutsTestCases.length > 0) { docStats.suts = (docStats.suts || 0) + 1; }
            }
            // SDS/SITS: 영향 함수(직접+간접)가 하나라도 있으면 검토 대상.
            if (guide.details.length > 0) {
              docStats.sds = guide.details.length;
              docStats.sits = guide.details.filter(d => d.stsTestCases.length > 0).length || 0;
            }
          }
          const docEntries = [
            { key: 'uds', label: 'UDS', count: docStats.uds || actions.uds?.function_count || 0, status: actions.uds?.status },
            { key: 'sts', label: 'STS', count: docStats.sts || actions.sts?.function_count || 0, status: actions.sts?.status, extra: guide ? `${guide.summary.impactedStsTCs} TC` : '' },
            { key: 'suts', label: 'SUTS', count: docStats.suts || actions.suts?.function_count || 0, status: actions.suts?.status },
            { key: 'sits', label: 'SITS', count: docStats.sits || actions.sits?.function_count || 0, status: actions.sits?.status },
            { key: 'sds', label: 'SDS', count: docStats.sds || actions.sds?.function_count || 0, status: actions.sds?.status },
          ];
          return (
            <div style={{ marginTop: 10 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 6 }}>문서별 영향</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {docEntries.map(d => {
                  const hasImpact = d.count > 0;
                  const st = d.status ? (DOC_STATUS[d.status] || { tone: 'neutral', label: d.status })
                    : (hasImpact ? { tone: 'warning', label: '검토 필요' } : { tone: 'neutral', label: '영향 없음' });
                  return (
                    <div key={d.key} style={{ padding: '6px 10px', borderRadius: 6, border: `1px solid ${hasImpact ? 'var(--color-warning)' : 'var(--border)'}`, background: 'var(--bg)', minWidth: 100 }}>
                      <div style={{ fontWeight: 700, fontSize: 12, textTransform: 'uppercase' }}>{d.label}</div>
                      <StatusBadge tone={st.tone}>{st.label}</StatusBadge>
                      {d.count > 0 && <span className="text-muted" style={{ fontSize: 10, marginLeft: 4 }}>{d.count} 함수</span>}
                      {d.extra && <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>{d.extra}</div>}
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })()}
      </div>

      {/* 변경 상세 — 함수별 변경종류 + 시그니처 이전→이후 원문 (impactData 기반, 항상 렌더) */}
      {activeFnEntries.length > 0 && (
        <div className="panel" style={{ marginBottom: 12 }}>
          <div className="panel-header">
            <span className="panel-title">변경 상세 ({activeFnEntries.length}개 함수)</span>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {changeSummary.NEW > 0 && <span className="pill pill-success" style={{ fontSize: 10 }}>🟢 신규 {changeSummary.NEW}</span>}
              {changeSummary.DELETE > 0 && <span className="pill pill-danger" style={{ fontSize: 10 }}>🔴 삭제 {changeSummary.DELETE}</span>}
              {changeSummary.SIGNATURE > 0 && <span className="pill pill-warning" style={{ fontSize: 10 }}>🟠 시그니처 {changeSummary.SIGNATURE}</span>}
              {changeSummary.BODY > 0 && <span className="pill pill-info" style={{ fontSize: 10 }}>🔵 본문 {changeSummary.BODY}</span>}
              {changeSummary.HEADER > 0 && <span className="pill" style={{ fontSize: 10 }}>헤더 {changeSummary.HEADER}</span>}
              {changeSummary.VARIABLE > 0 && <span className="pill" style={{ fontSize: 10 }}>변수 {changeSummary.VARIABLE}</span>}
            </div>
          </div>
          {isConservativeCount && (
            <div className="text-muted" style={{ fontSize: 10, marginTop: 4, padding: '4px 8px', background: 'var(--bg)', borderRadius: 4 }}>
              ⚠ 파일단위 보수 분류 — 변경 파일에 속한 전체 함수를 '본문'으로 집계합니다. 라인 diff가 없어 시그니처/신규/삭제가 본문으로 접히며, 실제 수정 함수는 이보다 적을 수 있습니다.
            </div>
          )}
          <div style={{ maxHeight: 420, overflow: 'auto', marginTop: 8 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                  <th style={{ textAlign: 'left', padding: '6px 8px' }}>함수</th>
                  <th style={{ textAlign: 'left', padding: '6px 8px', width: 90 }}>변경</th>
                  <th style={{ textAlign: 'left', padding: '6px 8px' }}>상세 (이전 − → 이후 ＋)</th>
                </tr>
              </thead>
              <tbody>
                {[...activeFnEntries]
                  .sort((a, b) => (CHANGE_ORDER[b[1]] || 0) - (CHANGE_ORDER[a[1]] || 0))
                  .map(([fn, kind]) => (
                    <tr key={fn} style={{ borderBottom: '1px solid var(--border-subtle, var(--border))' }}>
                      <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono, monospace)', wordBreak: 'break-all' }}>{functionMeta[fn]?.display_name || fn}</td>
                      <td style={{ padding: '6px 8px' }}>
                        <StatusBadge tone={CHANGE_TYPE_TONE[kind] || 'neutral'}>{CHANGE_TYPE_KO[kind] || kind}</StatusBadge>
                      </td>
                      <td style={{ padding: '6px 8px' }}>
                        {renderChangeDetailCell(kind, changeDetails[String(fn).toLowerCase()])}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* AI Risk & Cross-Document Impact Guide */}
      {aiGuide && (
        <div className="panel" style={{ marginBottom: 12 }}>
          <div className="panel-header">
            <span className="panel-title">AI 영향도 분석 가이드</span>
            <span className="text-muted text-sm">{aiGuide.ai_enriched ? 'AI-enriched' : 'deterministic'}</span>
          </div>

          {/* Risk Assessment */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 10, alignItems: 'center' }}>
            <div style={{
              padding: '8px 16px', borderRadius: 6, fontWeight: 700, fontSize: 14,
              background: aiGuide.risk?.grade === 'CRITICAL' ? 'var(--color-danger)' :
                aiGuide.risk?.grade === 'HIGH' ? '#e67e22' :
                aiGuide.risk?.grade === 'MEDIUM' ? 'var(--color-warning)' :
                aiGuide.risk?.grade === 'LOW' ? 'var(--color-success)' : '#888',
              color: '#fff',
            }}>
              {aiGuide.risk?.grade} ({aiGuide.risk?.score}/100)
            </div>
            <div style={{ fontSize: 11 }}>
              <div>ASIL: <strong>{aiGuide.risk?.max_asil}</strong></div>
              {aiGuide.risk?.asil_escalation && (
                <StatusBadge tone="danger">ASIL Escalation</StatusBadge>
              )}
            </div>
            <div style={{ flex: 1, fontSize: 10, color: 'var(--text-muted)' }}>
              {aiGuide.risk?.justification}
            </div>
          </div>

          {/* Safety Functions */}
          {aiGuide.risk?.affected_safety_functions?.length > 0 && (
            <div style={{ marginBottom: 10, padding: 8, background: 'var(--bg)', borderRadius: 6, borderLeft: '3px solid var(--color-danger)' }}>
              <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>안전 관련 함수</div>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {aiGuide.risk.affected_safety_functions.map((sf, i) => (
                  <span key={i} className="pill pill-danger" style={{ fontSize: 9 }}>{sf}</span>
                ))}
              </div>
            </div>
          )}

          {/* Cross-Document Impact */}
          {aiGuide.cross_doc_impacts && Object.keys(aiGuide.cross_doc_impacts).length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 6 }}>문서별 변경 영향</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 6 }}>
                {Object.entries(aiGuide.cross_doc_impacts).map(([doc, impacts]) => {
                  const items = Array.isArray(impacts) ? impacts : [];
                  return (
                    <div key={doc} style={{ padding: 8, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)' }}>
                      <div style={{ fontWeight: 700, fontSize: 11, textTransform: 'uppercase', marginBottom: 4, color: 'var(--accent)' }}>{doc}</div>
                      {items.slice(0, 3).map((imp, i) => (
                        <div key={i} style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 2 }}>{imp}</div>
                      ))}
                      {items.length > 3 && <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>+{items.length - 3}건 더</div>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Review Checklist */}
          {aiGuide.review_checklist?.length > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>리뷰 체크리스트</div>
              {aiGuide.review_checklist.map((item, i) => (
                <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '3px 0', fontSize: 11 }}>
                  <span className={`pill ${item.priority === 'CRITICAL' ? 'pill-danger' : item.priority === 'HIGH' ? 'pill-warning' : 'pill-info'}`}
                    style={{ fontSize: 9, minWidth: 60, textAlign: 'center' }}>{item.priority}</span>
                  <span>{item.item}</span>
                </div>
              ))}
            </div>
          )}

          {/* Test Recommendations */}
          {aiGuide.test_recommendations?.length > 0 && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>테스트 추가 제안</div>
              <table style={{ width: '100%', fontSize: 10, borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    <th style={{ textAlign: 'left', padding: '3px 6px' }}>함수</th>
                    <th style={{ textAlign: 'left', padding: '3px 6px' }}>유형</th>
                    <th style={{ textAlign: 'left', padding: '3px 6px' }}>설명</th>
                  </tr>
                </thead>
                <tbody>
                  {aiGuide.test_recommendations.slice(0, 8).map((rec, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border-light, var(--border))' }}>
                      <td style={{ padding: '3px 6px', fontFamily: 'monospace', fontWeight: 600 }}>{rec.function}</td>
                      <td style={{ padding: '3px 6px' }}><span className="pill pill-info" style={{ fontSize: 9 }}>{rec.test_type}</span></td>
                      <td style={{ padding: '3px 6px' }}>{rec.description}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Detailed guide */}
      {guide && (
        <div className="panel">
          <div className="panel-header">
            <span className="panel-title">함수별 영향 가이드 ({guide.details.length}개)</span>
            <span className="text-muted text-sm" title="변경(직접) 함수와 그 호출 관계로 영향받는 간접(1/2-hop) 함수를 함께 표시합니다. '영향' 필터로 hop을 좁힐 수 있습니다.">직접 변경 + 간접 영향(1/2-hop) 포함</span>
          </div>

          {/* 추출 실패 표면화 — 매핑이 실제보다 적게 보일 수 있음을 지속 노출(토스트는 사라짐) */}
          {guide.fetchFailures?.length > 0 && (
            <div className="text-sm" style={{ margin: '4px 0 8px', padding: '6px 10px', borderLeft: '3px solid var(--color-warning)', background: 'var(--bg)', borderRadius: 4 }}>
              ⚠️ {guide.fetchFailures.map(f => f.doc).join(', ')} 매핑 조회 실패 — 아래 요구사항/STS/SUTS TC 매핑이 실제보다 적게 보일 수 있습니다('매핑 없음' ≠ 확정 부재). 문서 경로/권한을 확인 후 다시 생성하세요.
            </div>
          )}

          {/* Search + Filter */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <input type="text" placeholder="함수명, 요구사항 ID 검색..."
              value={searchTerm} onChange={e => setSearchTerm(e.target.value)}
              style={{ flex: 1, minWidth: 180, padding: '6px 10px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)' }} />
            <select value={hopFilter} onChange={e => setHopFilter(e.target.value)}
              style={{ padding: '6px 10px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6 }}>
              <option value="all">전체 영향</option>
              <option value="direct">직접 영향</option>
              <option value="1-hop">1-hop</option>
              <option value="2-hop">2-hop</option>
            </select>
            <select value={docFilter} onChange={e => setDocFilter(e.target.value)}
              style={{ padding: '6px 10px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6 }}>
              <option value="all">전체 문서</option>
              <option value="has_reqs">요구사항 있음</option>
              <option value="has_sts">STS TC 있음</option>
              <option value="has_suts">SUTS TC 있음</option>
              <option value="no_mapping">매핑 없음</option>
            </select>
            <span className="text-muted text-sm">{filteredGuide.length}/{guide.details.length}건</span>
          </div>

          <table className="impact-table" style={{ fontSize: 11 }}>
            <thead>
              <tr>
                <th style={{ width: 150 }}>함수</th>
                <th style={{ width: 60 }}>변경</th>
                <th style={{ width: 50 }}>ASIL</th>
                <th style={{ width: 50 }}>영향</th>
                <th style={{ width: 96 }} title="ASIL 타깃 구조 커버리지(D=MC/DC, C/B=분기, A/QM=구문) 대비. Δ=직전 대비 변화">커버리지</th>
                <th>요구사항</th>
                <th>STS TC</th>
                <th>SUTS TC</th>
                <th style={{ width: 50 }}></th>
              </tr>
            </thead>
            <tbody>
              {filteredGuide.map((d, i) => (
                <tr key={i} style={{ background: d.hop === 'direct' ? 'var(--bg)' : undefined }}>
                  <td style={{ fontFamily: 'monospace', fontSize: 10, fontWeight: 600 }}>{d.function}</td>
                  <td>
                    {d.changed
                      ? <span className="pill pill-warning" style={{ fontSize: 9 }}>{CHANGE_TYPE_KO[d.changeType] || d.changeType}</span>
                      : <span className="pill pill-neutral" style={{ fontSize: 9 }} title="직접 변경 아님 — 변경 함수의 호출 관계로 영향받는 간접 함수">영향</span>}
                  </td>
                  <td>
                    {d.asil && /^[A-D]$/.test(d.asil)
                      ? <span className={`pill ${/[CD]/.test(d.asil) ? 'pill-danger' : 'pill-warning'}`} style={{ fontSize: 9 }}>{d.asil}</span>
                      : <span className="text-muted" style={{ fontSize: 9 }} title="ASIL 미상 — 수동 확인 필요">미상</span>}
                  </td>
                  <td><span className={`pill ${d.hop === 'direct' ? 'pill-danger' : 'pill-info'}`} style={{ fontSize: 9 }}>{d.hop}</span></td>
                  <td style={{ fontSize: 10, whiteSpace: 'nowrap' }}>{renderCoverageCell(d.coverage)}</td>
                  <td style={{ fontSize: 10 }}>
                    {d.requirements.length > 0
                      ? <span title={d.requirements.join(', ')} style={{ cursor: 'pointer', color: 'var(--accent)', textDecoration: 'underline' }}
                          onClick={() => window.__detailSection?.('srssds')}>
                          {d.requirements.length}개 ({d.requirements.slice(0, 2).join(', ')}{d.requirements.length > 2 ? '...' : ''})
                        </span>
                      : <span className="text-muted">-</span>}
                  </td>
                  <td style={{ fontSize: 10 }}>
                    {d.stsTestCases.length > 0
                      ? <span className="pill pill-info" style={{ fontSize: 9 }}>{d.stsTestCases.length} TC</span>
                      : <span className="text-muted">-</span>}
                  </td>
                  <td style={{ fontSize: 10 }}>
                    {d.sutsTestCases.length > 0
                      ? <span className="pill pill-info" style={{ fontSize: 9 }}>{d.sutsTestCases.length} TC</span>
                      : <span className="text-muted">-</span>}
                  </td>
                  <td>
                    <button className="btn-sm" style={{ fontSize: 9, padding: '1px 4px' }}
                      onClick={() => setSelectedFn(selectedFn === d.function ? null : d.function)}>
                      {selectedFn === d.function ? '접기' : '상세'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* Detail modal for selected function — 화면 중앙 오버레이(스크롤 위치 무관 즉시 노출) */}
          {selectedFn && (() => {
            const d = guide.details.find(x => x.function === selectedFn);
            if (!d) return null;
            const ct = (d.changeType || '').toUpperCase();
            const cd = changeDetails[String(d.function).toLowerCase()] || {};
            const hasRaw = !!(cd.before || cd.after);
            const pdiff = hasRaw ? diffSignatureParamsCached(cd.before, cd.after) : null;
            const sigSummary = summarizeSignatureChange(pdiff);
            // 문서별 구체 편집 액션(결정론) — 실제 파라미터 diff·요구사항·TC 반영. LLM 무관·즉시.
            const docActions = buildDocumentActions(d, pdiff);
            const DOC_CARDS = [
              { key: 'uds', icon: '📘', title: 'UDS 업데이트', note: d.requirements.length ? `관련 요구사항: ${d.requirements.slice(0, 5).join(', ')}${d.requirements.length > 5 ? ` +${d.requirements.length - 5}개` : ''}` : '' },
              { key: 'sts', icon: '📗', title: 'STS 검토', chips: d.stsTestCases },
              { key: 'suts', icon: '📙', title: 'SUTS 업데이트', chips: d.sutsTestCases },
              { key: 'sits', icon: '📕', title: 'SITS 검토', note: '통합 콜체인·데이터 흐름' },
              { key: 'sds', icon: '📋', title: 'SDS 확인', note: 'SW 아키텍처 설계' },
            ];
            const exp = explain.fn === d.function ? explain : { text: '', loading: false, error: '' };
            const close = () => setSelectedFn(null);
            return (
              <div onClick={close}
                style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', zIndex: 1000, display: 'flex', alignItems: 'flex-start', justifyContent: 'center', padding: '5vh 16px', overflow: 'auto' }}>
                <div onClick={e => e.stopPropagation()}
                  role="dialog" aria-modal="true" aria-label={`${d.function} 변경 상세`}
                  style={{ background: 'var(--panel)', border: '2px solid var(--accent)', borderRadius: 10, maxWidth: 900, width: '100%', maxHeight: '90vh', overflow: 'auto', padding: 18, boxShadow: '0 10px 40px rgba(0,0,0,0.45)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 12, gap: 8 }}>
                  <div>
                    <span style={{ fontWeight: 700, fontSize: 16, fontFamily: 'monospace', wordBreak: 'break-all' }}>{d.function}</span>
                    <div style={{ marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap', alignItems: 'center' }}>
                      {d.changed
                        ? <span className="pill pill-warning" style={{ fontSize: 10 }}>{CHANGE_TYPE_KO[d.changeType] || d.changeType}</span>
                        : <span className="pill pill-neutral" style={{ fontSize: 10 }} title="직접 변경 아님 — 간접 영향 함수">영향</span>}
                      <span className={`pill ${d.hop === 'direct' ? 'pill-danger' : 'pill-info'}`} style={{ fontSize: 10 }}>{d.hop}</span>
                      {d.asil && /^[A-D]$/.test(d.asil) && <span className={`pill ${/[CD]/.test(d.asil) ? 'pill-danger' : 'pill-warning'}`} style={{ fontSize: 10 }}>ASIL {d.asil}</span>}
                      {d.requirements.length > 0 && <span className="text-muted" style={{ fontSize: 10 }}>요구사항 {d.requirements.length}개</span>}
                    </div>
                  </div>
                  <button className="btn-sm" onClick={close} style={{ flexShrink: 0 }}>✕ 닫기</button>
                </div>

                {/* 🔧 시그니처·매개변수 변화 — svn diff 원문(change_details) 기반 결정론 diff */}
                {hasRaw && (
                  <div style={{ marginBottom: 12, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
                    <div style={{ padding: '6px 10px', background: 'var(--bg)', fontWeight: 700, fontSize: 12, borderBottom: '1px solid var(--border)' }}>
                      🔧 시그니처·매개변수 변화 <span className="text-muted" style={{ fontWeight: 400, fontSize: 10 }}>(변경 원문 기반)</span>
                    </div>
                    <div style={{ padding: 10 }}>
                      {/* 한눈 요약 — 무엇이 추가/삭제/타입변경됐는지 뱃지로(원문 raw 대신 직접 표시) */}
                      {sigSummary.hasChange && (
                        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
                          {sigSummary.badges.map((b, i) => (
                            <span key={i} className={`pill pill-${b.tone}`} style={{ fontSize: 10, fontFamily: 'var(--font-mono, monospace)' }}>{b.label}</span>
                          ))}
                        </div>
                      )}
                      {/* 위치 추정 경고 — 이름 매칭 불가 매개변수(함수포인터 등)로 귀속이 부정확할 수 있음 */}
                      {sigSummary.positional && (
                        <div style={{ fontSize: 10, color: 'var(--color-warning)', marginBottom: 8, padding: '4px 8px', background: 'var(--bg)', borderRadius: 4, borderLeft: '2px solid var(--color-warning)' }}>
                          ⚠ 매개변수 이름을 매칭할 수 없어 <strong>위치 기반</strong>으로 추정했습니다. 삽입/삭제 위치가 실제와 다를 수 있으니 아래 원문을 대조하세요.
                        </div>
                      )}
                      {pdiff?.returnChanged && (
                        <div style={{ fontSize: 11, marginBottom: 8 }}>
                          <strong>반환 타입:</strong>{' '}
                          <span style={{ color: 'var(--color-danger)', fontFamily: 'monospace' }}>{pdiff.returnBefore || '(없음)'}</span>{' → '}
                          <span style={{ color: 'var(--color-success)', fontFamily: 'monospace' }}>{pdiff.returnAfter || '(없음)'}</span>
                        </div>
                      )}
                      {pdiff && pdiff.rows.length > 0 ? (
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, marginBottom: 8 }}>
                          <thead><tr style={{ borderBottom: '1px solid var(--border)' }}>
                            <th style={{ textAlign: 'left', padding: '3px 6px', width: 64 }}>구분</th>
                            <th style={{ textAlign: 'left', padding: '3px 6px' }}>이전</th>
                            <th style={{ textAlign: 'left', padding: '3px 6px' }}>이후</th>
                          </tr></thead>
                          <tbody>
                            {pdiff.rows.map((r, i) => {
                              const st = PARAM_STATUS[r.status] || { tone: 'neutral', label: r.status, mark: '' };
                              return (
                                <tr key={i} style={{ borderBottom: '1px solid var(--border-subtle, var(--border))' }}>
                                  <td style={{ padding: '3px 6px' }}><span className={`pill pill-${st.tone}`} style={{ fontSize: 8 }}>{st.mark} {st.label}</span></td>
                                  <td style={{ padding: '3px 6px', fontFamily: 'monospace', color: r.before ? 'var(--color-danger)' : 'var(--text-muted)' }}>{r.before || '—'}</td>
                                  <td style={{ padding: '3px 6px', fontFamily: 'monospace', color: r.after ? 'var(--color-success)' : 'var(--text-muted)' }}>{r.after || '—'}</td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      ) : (
                        <div className="text-muted" style={{ fontSize: 11, marginBottom: 8 }}>
                          {pdiff?.failed ? '⚠ 매개변수 구조 파싱 불가 — 아래 원문을 직접 대조하세요.' : '매개변수 목록 변화 없음 (본문/기타 변경).'}
                        </div>
                      )}
                      {/* 변경 원문(선언) — 기본 접힘. 요약/테이블로 이해되므로 필요 시만 펼쳐 대조 */}
                      <details>
                        <summary style={{ fontSize: 10, color: 'var(--text-muted)', cursor: 'pointer' }}>변경 원문(선언) 보기</summary>
                        <div style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: 11, whiteSpace: 'pre-wrap', wordBreak: 'break-all', background: 'var(--bg)', borderRadius: 4, padding: '6px 8px', marginTop: 4 }}>
                          {cd.before && <div style={{ color: 'var(--color-danger)' }}>− {cd.before}</div>}
                          {cd.after && <div style={{ color: 'var(--color-success)' }}>＋ {cd.after}</div>}
                        </div>
                      </details>
                    </div>
                  </div>
                )}
                {!hasRaw && d.changed && ['SIGNATURE', 'NEW', 'DELETE'].includes(ct) && (
                  <div className="text-muted" style={{ fontSize: 11, marginBottom: 12, padding: '6px 10px', background: 'var(--bg)', borderRadius: 6 }}>
                    선언 원문 미확보(svn diff 접근 불가 등) — 매개변수 단위 변화는 표시할 수 없습니다. AI 설명으로 보완하세요.
                  </div>
                )}

                {/* 🤖 AI 변경 설명 (Gemini) — 선언 원문 근거 자연어 설명 */}
                <div style={{ marginBottom: 12, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
                  <div style={{ padding: '6px 10px', background: 'var(--bg)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, borderBottom: (exp.text || exp.error) ? '1px solid var(--border)' : 'none' }}>
                    <span style={{ fontWeight: 700, fontSize: 12 }}>🤖 AI 변경 설명 <span className="text-muted" style={{ fontWeight: 400, fontSize: 10 }}>(Gemini)</span></span>
                    <button className="btn-sm" onClick={() => fetchExplanation(d)} disabled={exp.loading} style={{ flexShrink: 0 }}>
                      {exp.loading ? '분석 중...' : (exp.text ? '다시 생성' : 'AI로 설명 생성')}
                    </button>
                  </div>
                  {exp.text && <div style={{ padding: 10, fontSize: 12, whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{exp.text}</div>}
                  {exp.error && <div style={{ padding: 10, fontSize: 11, color: 'var(--text-muted)' }}>⚠ {exp.error}</div>}
                </div>

                {/* Change description */}
                <div style={{ padding: '8px 10px', background: 'var(--bg)', borderRadius: 6, marginBottom: 12, fontSize: 12, borderLeft: '3px solid var(--color-warning)' }}>
                  {!d.changed && `이 함수는 직접 변경되지 않았으나, 변경 함수와의 호출 관계(${d.hop})로 영향받는 간접 함수입니다. 인터페이스 계약이 유지되는지, 회귀 시험(SUTS/SITS) 재실행이 필요한지 확인하세요.`}
                  {ct === 'BODY' && '함수 본문(로직)이 변경되었습니다. 동작 변경으로 인해 관련 문서의 Description, Test Action, Expected Result를 모두 재검토해야 합니다.'}
                  {ct === 'SIGNATURE' && '함수 시그니처(파라미터/리턴타입)가 변경되었습니다. 호출하는 모든 함수와 Input/Output Parameters, Pre-condition을 업데이트해야 합니다.'}
                  {ct === 'HEADER' && '헤더 파일이 변경되었습니다. 매크로/타입 정의 변경으로 이 헤더를 include하는 모든 소스 파일의 함수에 영향이 있을 수 있습니다.'}
                  {ct === 'VARIABLE' && '글로벌 변수가 변경되었습니다. 이 변수를 읽고 쓰는 모든 함수의 동작을 확인해야 합니다.'}
                  {ct === 'NEW' && '신규 함수가 추가되었습니다. UDS에 Function Information 항목을 추가하고, 관련 TC를 작성해야 합니다.'}
                  {ct === 'DELETE' && '함수가 삭제되었습니다. UDS에서 해당 함수를 제거하고, 관련 TC를 비활성화해야 합니다.'}
                </div>

                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
                  각 문서에 <strong>무엇을 어느 섹션에</strong> 반영해야 하는지 — 실제 매개변수 변화 기반(결정론).
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 10 }}>
                  {DOC_CARDS.map(card => {
                    const acts = docActions[card.key] || [];
                    const chips = card.chips || [];
                    return (
                      <div key={card.key} style={{ padding: 10, border: '1px solid var(--border)', borderRadius: 6 }}>
                        <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 6, color: 'var(--accent)' }}>{card.icon} {card.title}</div>
                        {acts.length > 0 ? (
                          <ul style={{ fontSize: 11, margin: '0 0 4px 0', padding: 0, listStyle: 'none' }}>
                            {acts.map((a, i) => (
                              <li key={i} style={{ marginBottom: 5, display: 'flex', gap: 5, alignItems: 'baseline' }}>
                                <span className={`pill pill-${a.tone}`} style={{ fontSize: 8, flexShrink: 0, whiteSpace: 'nowrap' }}>{a.section}</span>
                                <span style={{ lineHeight: 1.4 }}>{renderInlineCode(a.text)}</span>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <div className="text-sm text-muted">특이 액션 없음</div>
                        )}
                        {chips.length > 0 && (
                          <div style={{ fontSize: 10, maxHeight: 56, overflow: 'auto', marginTop: 2 }}>
                            {chips.slice(0, 10).map(tc => (
                              <span key={tc} className="pill pill-neutral" style={{ fontSize: 9, margin: 1 }}>{tc}</span>
                            ))}
                            {chips.length > 10 && <span className="text-muted" style={{ fontSize: 9 }}> +{chips.length - 10}개</span>}
                          </div>
                        )}
                        {card.note && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>{card.note}</div>}
                      </div>
                    );
                  })}
                </div>
                </div>
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}
