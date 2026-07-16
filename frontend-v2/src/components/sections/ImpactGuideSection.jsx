import { useState, useCallback, useMemo, useEffect, useRef } from 'react';
import { post } from '../../api.js';
import { useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';

const CHANGE_TYPE_KO = { BODY: '본문', HEADER: '헤더', SIGNATURE: '시그니처', NEW: '신규', DELETE: '삭제', VARIABLE: '변수' };
const CHANGE_TYPE_TONE = { NEW: 'success', DELETE: 'danger', SIGNATURE: 'warning', BODY: 'info', HEADER: 'neutral', VARIABLE: 'neutral' };
// 변경 유형 툴팁 설명 — 리스트에서 hover 시 무엇인지 즉시 파악(모달 안 열어도).
const CHANGE_TYPE_DESC = {
  BODY: '함수 내부 로직(본문) 변경', HEADER: '헤더(매크로/타입 정의) 변경',
  SIGNATURE: '함수 시그니처(파라미터/리턴타입) 변경', NEW: '신규 함수 추가',
  DELETE: '함수 삭제', VARIABLE: '전역/정적 변수 변경',
};
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
// SITS req→TC(SwRS 허브 키). 데모는 sdsPairs가 비어 UDS-경로 union(funcToReqs→SwRS_*)으로 조인된다.
const DEMO_SITS_TCS = [
  { requirement_id: 'SwRS_1001', testcase: 'SITS_DrvIn_Integ_001' },
  { requirement_id: 'SwRS_1002', testcase: 'SITS_MotorSpd_Integ_005' },
  { requirement_id: 'SwRS_1010', testcase: 'SITS_DoorState_Integ_012' },
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
      ? <code key={i} style={{ fontFamily: 'var(--font-mono, monospace)', background: 'var(--bg)', padding: '0 3px', borderRadius: 3, overflowWrap: 'anywhere' }}>{p.slice(1, -1)}</code>
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
  const key = JSON.stringify([before || '', after || '']);
  let v = _sigDiffCache.get(key);
  if (v === undefined) {
    v = diffSignatureParams(before, after);
    if (_sigDiffCache.size < 4000) _sigDiffCache.set(key, v);  // 무한 성장 방지(실전 함수 수 << 4000)
  }
  return v;
}

// ── 함수 본문 diff에서 실제 변경 요소 추출(BODY/VARIABLE 문서 카드 구체화용, 결정론) ──
// 전역/정적 변수 write(LHS)·전처리 매크로를 부호별(added/removed)로 수집한다. AI 무관·즉시.
const EMPTY_DIFF_ELEMS = Object.freeze({
  changedGlobals: { added: [], removed: [] },
  macros: { added: [], removed: [] },
  addedLines: 0, removedLines: 0, hunks: 0, truncated: false, noSemanticChange: false,
});
// 전역/정적 명명 규약: (u|s)+숫자 타입 prefix + g_/s_ 또는 bare g_/s_. 타입 prefix를 실제 토큰으로
// 앵커해 msg_/flag_group/cfg_mode 류 오탐 방지([a-z]{0,3} 백트래킹 과매칭 수정, reviewer #1/#2).
const _GLOBALISH = /^(?:[us]\d{1,2})?g_/;
const _STATICISH = /^(?:[us]\d{1,2})?s_/;
// LHS write: 식별자 + (배열첨자|멤버접근 .f/->f)* + 대입/복합대입(=(?!=)로 ==, 알파벳 op로 <=/>=/!= 제외).
// 멤버 write(g_X.mode=…, g_H->cnt=…)도 base 전역을 잡는다(reviewer #6/#7).
const _WRITE_LHS = /^\s*([A-Za-z_]\w*)(?:\[[^\]]*\]|(?:\.|->)\w+)*\s*(?:=(?!=)|[-+*/%|&^]=|<<=|>>=)/;
// 전처리: ifdef/ifndef/define/undef는 직접 매크로명, #if/#elif는 defined(X)의 X만 캡처한다.
// pragma/include는 조건부 컴파일이 아니므로 매크로로 잡지 않는다(reviewer #3/#8).
const _PREPROC_DIRECT = /^\s*#\s*(?:ifdef|ifndef|define|undef)\s+([A-Za-z_]\w*)/;
const _PREPROC_COND = /^\s*#\s*(?:if|elif)\b/;
const _DEFINED_RE = /defined\s*\(?\s*([A-Za-z_]\w*)/g;
export function extractDiffElements(fd) {
  if (!fd) return EMPTY_DIFF_ELEMS;
  const gAdd = new Set(), gRem = new Set(), mAdd = new Set(), mRem = new Set();
  let addedLines = 0, removedLines = 0, hunks = 0, truncated = false;
  const minusSeq = [], plusSeq = [];  // -/+ 본문 라인(순서 보존·trim) — 포맷/이동만(의미 변경 없음) 판정용
  for (const raw of String(fd).split('\n')) {
    if (!raw) continue;
    if (raw.startsWith('@@ ')) { hunks++; continue; }
    if (raw.startsWith('+++') || raw.startsWith('---')) continue;
    if (raw.includes('줄 생략)')) { truncated = true; continue; }  // extract_function_diffs 절단 마커
    const sign = raw[0];
    if (sign !== '+' && sign !== '-') continue;
    const body = raw.slice(1);
    if (sign === '+') { addedLines++; plusSeq.push(body.trim()); }
    else { removedLines++; minusSeq.push(body.trim()); }
    const gSet = sign === '+' ? gAdd : gRem;
    const mSet = sign === '+' ? mAdd : mRem;
    const wm = _WRITE_LHS.exec(body);  // 1) 전역/정적 write target(멤버 write는 base 전역)
    if (wm && (_GLOBALISH.test(wm[1]) || _STATICISH.test(wm[1]))) gSet.add(wm[1]);
    const pd = _PREPROC_DIRECT.exec(body);  // 2) 전처리 매크로
    if (pd) mSet.add(pd[1]);
    else if (_PREPROC_COND.test(body)) {
      _DEFINED_RE.lastIndex = 0;
      let dm;
      while ((dm = _DEFINED_RE.exec(body)) !== null) mSet.add(dm[1]);  // #if defined(X) → X
    }
  }
  // 포맷/이동만(의미 변경 없음): -/+ 본문이 순서·내용(공백 정규화) 동일 → 블록 이동·재들여쓰기.
  // ⚠ 순서 비교(멀티셋 아님)라 문장 재정렬(a=1;b=a;→b=a;a=1;)은 다르게 나와 실변경으로 유지(오탐 방지).
  //   truncated diff(60줄/400KB 상한)는 안 보이는 부분에 실변경 가능 → 판정 보류(false).
  const noSemanticChange = !truncated && minusSeq.length > 0
    && minusSeq.length === plusSeq.length
    && minusSeq.every((v, i) => v === plusSeq[i]);
  // cap 없이 전체 반환 — 개수를 정확히 표시(백엔드 60줄 cap이 1차 상한, 카드 표시는 listVars가 4개로 cap). reviewer #5.
  return {
    changedGlobals: { added: [...gAdd], removed: [...gRem] },
    macros: { added: [...mAdd], removed: [...mRem] },
    addedLines, removedLines, hunks, truncated, noSemanticChange,
  };
}
// diffElems 캐시 — 모달 재렌더(검색 타이핑 등) 시 재계산 회피(_sigDiffCache 동일 패턴).
const _diffElemCache = new Map();
function extractDiffElementsCached(fd) {
  if (!fd) return EMPTY_DIFF_ELEMS;
  let v = _diffElemCache.get(fd);
  if (v === undefined) {
    v = extractDiffElements(fd);
    if (_diffElemCache.size < 4000) _diffElemCache.set(fd, v);
  }
  return v;
}

// 절대 소스경로(Windows) → file_diffs(백엔드 extract_file_diffs의 정규화 상대경로 키) 경계 suffix 매칭.
// basename 충돌은 '/' 경계 + 최장(가장 구체적) 매칭으로 완화(백엔드 _in_line_classified 규약과 대칭).
export function matchFileDiff(absFile, fileDiffs) {
  if (!absFile || !fileDiffs) return '';
  const abs = String(absFile).replace(/\\/g, '/').toLowerCase();
  if (fileDiffs[abs]) return fileDiffs[abs];
  let bestKey = '';
  for (const k of Object.keys(fileDiffs)) {
    if ((abs === k || abs.endsWith('/' + k)) && k.length > bestKey.length) bestKey = k;
  }
  return bestKey ? fileDiffs[bestKey] : '';
}

// 함수 변경을 각 문서(UDS/STS/SUTS/SITS/SDS)의 '구체 편집 액션'으로 변환한다.
// 매개변수 diff(pdiff)가 정상이면 실제 파라미터명을 넣어 "무엇을 어느 섹션에" 수준으로 구체화하고,
// 원문이 없으면(pdiff null/failed) change_type 기반의 일반 액션으로 폴백한다. 순수·결정론(LLM 무관).
// 참고: 백엔드 workflow/impact_ai_guide.py의 _DOC_CHANGE_SENSITIVITY도 변경유형→문서 매핑을
//   'AI 영향도 분석 가이드' 패널용으로 독립 유지한다(파라미터 단위 아님) — 한쪽 수정 시 다른 쪽도 검토.
// 반환: { uds:[{section,text,tone}], sts:[...], suts:[...], sits:[...], sds:[...] }
export function buildDocumentActions(d, pdiff, diffElems = EMPTY_DIFF_ELEMS) {
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
  const sitsN = d.sitsTestCases?.length || 0;
  const A = (section, text, tone = 'neutral', title = '') => ({ section, text, tone, title });

  // ── 본문 diff에서 추출한 실제 변경 요소(전역 변수·전처리) — BODY/VARIABLE 구체화 근거 ──
  const de = diffElems || EMPTY_DIFF_ELEMS;
  const _gAset = new Set(de.changedGlobals.added), _gRset = new Set(de.changedGlobals.removed);
  const gRemoved = de.changedGlobals.removed.filter(v => !_gAset.has(v));  // 초기화 제거(제거만)
  const gAdded = de.changedGlobals.added.filter(v => !_gRset.has(v));      // 초기화 추가(추가만)
  const gChanged = de.changedGlobals.added.filter(v => _gRset.has(v));     // 값 변경(양쪽 등장)
  const condMacros = [...new Set([...de.macros.removed, ...de.macros.added])];
  const hasGlobals = !!(gRemoved.length || gAdded.length || gChanged.length);
  const truncNote = de.truncated ? ' (diff 일부 생략 — 원문 확인)' : '';
  const listVars = (arr, cap = 4) => ({
    text: arr.slice(0, cap).map(v => `\`${v}\``).join(', ') + (arr.length > cap ? ` +${arr.length - cap}개` : ''),
    title: arr.join(', '),
  });
  const globalsSummary = () => {
    const parts = [], tp = [];
    if (gRemoved.length) { const l = listVars(gRemoved); parts.push(`제거 ${gRemoved.length}개(${l.text})`); tp.push(`제거: ${l.title}`); }
    if (gAdded.length) { const l = listVars(gAdded); parts.push(`추가 ${gAdded.length}개(${l.text})`); tp.push(`추가: ${l.title}`); }
    if (gChanged.length) { const l = listVars(gChanged); parts.push(`값변경 ${gChanged.length}개(${l.text})`); tp.push(`값변경: ${l.title}`); }
    return { text: parts.join(' · '), title: tp.join(' / ') };
  };
  const macroSummary = condMacros.length
    ? { text: `조건부 컴파일 ${listVars(condMacros, 3).text} 변경`, title: condMacros.join(', ') }
    : null;
  const bodyish = (ct === 'BODY' || ct === 'VARIABLE');  // 분류 경계가 모호한 reset류는 동일 처리
  const useDiff = bodyish && (hasGlobals || !!macroSummary);  // 전역 또는 전처리 변경이 있으면 구체화(reviewer #4)

  const uds = [], sts = [], suts = [], sits = [], sds = [];

  // 간접 영향(직접 변경 아님): 문서 본문 수정이 아니라 '계약 유지 확인 + 회귀'가 핵심.
  if (!changed) {
    uds.push(A('영향 확인', `직접 변경 아님(${d.hop}) — 호출 인터페이스 계약 유지 시 문서 수정 없음`, 'neutral'));
    sts.push(A('회귀', stsN ? `${stsN}개 관련 TC 재실행 판단` : '직접 매핑 TC 없음', 'neutral'));
    suts.push(A('회귀', sutsN ? `${sutsN}개 단위 TC 재실행` : '관련 단위 TC 없음', 'neutral'));
    sits.push(A('회귀', sitsN ? `${sitsN}개 관련 통합 TC 재실행 판단` : '통합 콜체인 재실행 — 계약 유지 확인', 'neutral'));
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
  } else if (bodyish) {
    if (useDiff) {
      if (hasGlobals) {
        const g = globalsSummary();
        uds.push(A('Used Globals (Global/Static)', `전역 ${g.text} — Used Globals 목록·모듈 표 Reset Value 재확인${truncNote}`, gRemoved.length ? 'danger' : 'warning', g.title));
      }
      uds.push(macroSummary
        ? A('Description', `${macroSummary.text} 반영`, 'info', macroSummary.title)
        : A('Description', '변경된 로직/변수를 Description·의사코드에 반영', 'info'));
    } else {
      // diff 미확보 폴백(일반 문구)
      uds.push(A('Used Globals (Global/Static)', ct === 'VARIABLE' ? '전역/정적 변수 정의·모듈 표 Reset Value 갱신' : '사용 전역 변수·호출 함수 관계 재확인', 'warning'));
      uds.push(A('Description', ct === 'VARIABLE' ? '변수 변경에 따른 동작 반영' : '변경된 로직을 Description/의사코드에 반영', 'info'));
    }
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
    } else if (bodyish && useDiff) {
      if (hasGlobals) {
        const g = globalsSummary();
        sts.push(A('Pre-condition', `초기화 변경 전역의 초기 조건 재검토 — ${g.text}`, 'warning', g.title));
        sts.push(A('Expected Result', `${stsN}개 TC의 해당 전역 기대 상태 재확인`, 'info'));
      } else {
        sts.push(A('Pre-condition', `${macroSummary.text} 반영 — ${stsN}개 TC 재검토`, 'warning', macroSummary.title));
      }
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
  } else if (bodyish && useDiff) {
    if (hasGlobals) {
      const g = globalsSummary();
      suts.push(A('Expected(Output) Variables', `변경 전역의 reset 기대값 케이스 재확인/삭제 — ${g.text} (변수별 SwUTC 기대출력)`, gRemoved.length ? 'danger' : 'warning', g.title));
    } else {
      suts.push(A('Expected(Output) Variables', `${macroSummary.text} — 경계값·기대출력 재확인`, 'warning', macroSummary.title));
    }
  } else if (ct === 'BODY') {
    suts.push(A('Expected(Output) Variables', sutsN ? `${sutsN}개 TC 경계값·기대출력 재계산` : '로직 변경 — TC 없음, 신규 생성 권장', sutsN ? 'info' : 'warning'));
  } else if (ct === 'NEW') {
    suts.push(A('신규 TC', '단위 TC 신규 작성 — 경계값 분석(ABV: MIN/MID/MAX/INV)', 'success'));
  } else if (ct === 'DELETE') {
    suts.push(A('TC 정리', sutsN ? `${sutsN}개 관련 단위 TC 비활성화` : '관련 단위 TC 없음', 'danger'));
  } else if (ct === 'VARIABLE') {
    suts.push(A('Input/Output Variables', '변경 전역의 입출력 매핑·기대값 확인', 'warning'));
  } else {
    suts.push(A('확인', sutsN ? `${sutsN}개 단위 TC 검토` : '관련 단위 TC 없음', 'neutral'));
  }

  // ── SITS (SW 통합시험) — Data Flow 전용 컬럼 없음 → Call Chain / Input·Expected Param ──
  if (ct === 'SIGNATURE') {
    sits.push(A('Call Chain', `${d.function}의 콜체인 인자 전달 재검증(호출·피호출 양방향)`, 'warning'));
    if (added.length) sits.push(A('Input·Expected Param', `통합 입력/기대 Param에 ${listAfter(added)} 반영`, 'success'));
  } else if (bodyish && useDiff) {
    if (hasGlobals) {
      const g = globalsSummary();
      sits.push(A('Precondition', `변경 전역 초기화가 통합 진입 상태(Precondition/env)에 주는 영향 확인 — ${g.text}`, 'warning', g.title));
    } else {
      sits.push(A('Precondition', `${macroSummary.text}이 통합 진입 상태/분기에 주는 영향 확인`, 'warning', macroSummary.title));
    }
  } else if (ct === 'BODY') {
    sits.push(A('시나리오', '통합 시나리오 기대값 재확인', 'info'));
  } else if (ct === 'VARIABLE') {
    sits.push(A('Precondition', '변경 전역이 통합 진입 상태에 주는 영향 확인', 'warning'));
  } else if (ct === 'NEW') {
    sits.push(A('Call Chain', '신규 함수의 콜체인 포함 여부 및 통합 케이스 확인', 'success'));
  } else if (ct === 'DELETE') {
    sits.push(A('Call Chain', '콜체인 단절/대체 경로 확인', 'danger'));
  } else if (ct === 'HEADER') {
    sits.push(A('의존성', '헤더 변경이 콜체인 인터페이스 의존성에 주는 영향 확인', 'neutral'));
  } else {
    sits.push(A('확인', '통합 콜체인·Param 영향 확인', 'neutral'));
  }
  // SwRS 허브 브리지로 조인된 실제 SITS TC가 있으면 재검증 대상으로 정량 표기(STS/SUTS와 대칭).
  if (sitsN) sits.push(A('통합 TC', `${sitsN}개 관련 SITS TC 재검증`, 'info'));

  // ── SDS (SW 아키텍처 설계 — 파서, 고정 섹션명 없음: 함수/모듈 매칭으로 서술) ──
  if (ct === 'SIGNATURE') {
    sds.push(A('관련 함수/모듈 매칭', `\`${d.function}\` 매칭 항목의 인터페이스(포트/파라미터)에 시그니처 변경 반영 — 원본 heading 확인`, 'warning'));
  } else if (bodyish && useDiff) {
    const g = hasGlobals ? globalsSummary() : macroSummary;
    sds.push(A('관련 함수/모듈 매칭', `\`${d.function}\` 매칭 항목에 ${hasGlobals ? '전역 ' : ''}${g.text} 반영 — 고정 섹션 아님(원본 heading·relatedModules 확인)`, 'warning', g.title));
  } else if (ct === 'BODY') {
    sds.push(A('관련 함수/모듈 매칭', `\`${d.function}\` 동작 설명 갱신 — 원본 heading 확인`, 'info'));
  } else if (ct === 'VARIABLE') {
    sds.push(A('관련 함수/모듈 매칭', `\`${d.function}\` 관련 데이터/인터페이스 갱신 — 원본 heading 확인`, 'warning'));
  } else if (ct === 'NEW') {
    sds.push(A('설계 추가', '신규 컴포넌트/함수 아키텍처 반영', 'success'));
  } else if (ct === 'DELETE') {
    sds.push(A('설계 제거', '아키텍처에서 컴포넌트/함수 제거', 'danger'));
  } else {
    sds.push(A('관련 함수/모듈 매칭', 'relatedFunctions/relatedModules·changeTypes 기준 영향 확인', 'neutral'));
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

// 무정보(파일영향) 판정 — 단일 출처. BODY/VARIABLE인데 function_diff(본문 hunk)·change_details(선언
// 원문) 둘 다 없음 = 직접 변경 증거 없이 파일 단위 보수 분류(fatten)로 딸려온 함수. 전처리(#ifdef)만
// 바뀐 파일의 안 바뀐 getter류가 여기 해당. "변경 함수" 집계를 부풀리므로 옵션(showFileImpact)으로만 노출.
function functionHasNoEvidence(fn, kind, changeDetails, functionDiffs, functionMeta) {
  const k = String(kind || '').toUpperCase();
  if (k !== 'BODY' && k !== 'VARIABLE') return false;
  const lf = String(fn).toLowerCase();
  // 1차: 백엔드 function_meta.evidence(단일 출처, "line" | "file_fatten").
  // function_diffs 부재로 '증거 없음'을 추론하면, diff 400KB 상한 절단이나 diff 미제공 경로에서
  // **실제 변경된 함수**(ASIL D 포함 가능)가 '파일영향'으로 오분류돼 기본 집계에서 숨는다
  // (ISO 26262 under-report). 그래서 백엔드가 판정한 사실을 우선한다.
  const meta = functionMeta && (functionMeta[fn] ?? functionMeta[lf]);
  const ev = meta && meta.evidence;
  if (ev === 'file_fatten') return true;
  if (ev === 'line') return false;
  // 2차(구 페이로드 호환): evidence 필드가 없는 이전 job → 기존 추론으로 폴백.
  const cd = changeDetails && changeDetails[lf];
  return !(functionDiffs && functionDiffs[lf]) && !(cd && (cd.before || cd.after));
}

// 함수별 영향 가이드 리스트의 '변경' 셀 — 유형 뱃지(유형별 색상+툴팁 설명)와, SIGNATURE면
// 파라미터 변화 요약(＋int b 등)까지 표시해 모달을 열지 않고도 무슨 변경인지 파악하게 한다.
function renderChangeSummaryCell(d, changeDetails, functionDiffs = {}, functionMeta = {}) {
  if (!d.changed) {
    return <span className="pill pill-neutral" style={{ fontSize: 9 }} title="직접 변경 아님 — 변경 함수의 호출 관계로 영향받는 간접 함수">영향</span>;
  }
  const kind = (d.changeType || '').toUpperCase();
  const cd = changeDetails[String(d.function).toLowerCase()];
  // 무정보(파일영향): 직접 변경 증거 없이 파일 단위 보수 포함(fatten) — 단일 출처 functionHasNoEvidence.
  const cellNoEvidence = functionHasNoEvidence(d.function, kind, changeDetails, functionDiffs, functionMeta);
  // 포맷/이동만(의미 변경 없음) — 본문 diff가 코드 이동/공백/포맷만(순서 보존 -/+ 동일). 파일영향과 배타.
  const cellFormatOnly = !cellNoEvidence && extractDiffElementsCached(functionDiffs[String(d.function).toLowerCase()] || '').noSemanticChange;
  const pdiff = (kind === 'SIGNATURE' && cd && (cd.before || cd.after)) ? diffSignatureParamsCached(cd.before, cd.after) : null;
  const sig = summarizeSignatureChange(pdiff);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'flex-start' }}>
      <span className={`pill pill-${CHANGE_TYPE_TONE[kind] || 'neutral'}`} style={{ fontSize: 9 }} title={CHANGE_TYPE_DESC[kind] || kind}>
        {CHANGE_TYPE_KO[kind] || kind}
      </span>
      {cellNoEvidence && (
        <span className="pill pill-neutral" style={{ fontSize: 8 }} title="직접 변경 증거 없음(function_diff·change_details 모두 없음) — 같은 파일의 다른 변경으로 보수적 포함(파일 단위 영향)">파일영향</span>
      )}
      {cellFormatOnly && (
        <span className="pill pill-neutral" style={{ fontSize: 8 }} title="본문 diff가 코드 이동·공백·포맷만 — 의미(로직) 변경 없음(재정렬 아님)">포맷/이동</span>
      )}
      {sig.hasChange && (
        <span style={{ display: 'flex', gap: 2, flexWrap: 'wrap', alignItems: 'center' }} title="매개변수/반환 변화">
          {sig.positional && <span title="위치 추정 — 삽입/삭제 위치가 다를 수 있음" style={{ fontSize: 8 }}>⚠</span>}
          {sig.badges.slice(0, 3).map((b, j) => (
            <span key={j} className={`pill pill-${b.tone}`} style={{ fontSize: 8, fontFamily: 'var(--font-mono, monospace)' }}>{b.label}</span>
          ))}
          {sig.badges.length > 3 && <span className="text-muted" style={{ fontSize: 8 }}>+{sig.badges.length - 3}</span>}
        </span>
      )}
    </div>
  );
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
    <span title={`${metricKo} 커버리지 ${pct} (목표 100%)${typeof d === 'number' ? `, 직전 대비 ${(d * 100).toFixed(0)}%p` : ''}${cov.collision_worst_copy ? ' — 이름충돌 함수의 여러 copy 중 최악(worst-copy) 값' : ''}`}>
      <span className={`pill ${cov.meets_target ? 'pill-success' : 'pill-danger'}`} style={{ fontSize: 9 }}>
        {metricKo} {pct}
      </span>
      {cov.collision_worst_copy && (
        <span className="pill pill-neutral" style={{ fontSize: 8, marginLeft: 3 }}
          title="이름충돌(동명 다른 함수)의 여러 copy 중 최악 copy 커버리지 — 변경 copy를 이름만으로 특정 못 해 gap을 안전측으로 노출(어느 copy에 gap이 있어도 재검증 대상 유지)">충돌 최악</span>
      )}
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

// 문서별 상세 탭 — 문서 5종 메타(마스터 목록 아이콘/라벨). buildDocumentActions 반환 키와 lockstep.
const DOC_KEYS = ['uds', 'sts', 'suts', 'sits', 'sds'];
const DOC_META = {
  uds: { label: 'UDS', icon: '📘', desc: '단위 상세 설계' },
  sts: { label: 'STS', icon: '📗', desc: 'SW 요구 기반 시험' },
  suts: { label: 'SUTS', icon: '📙', desc: 'SW 단위시험' },
  sits: { label: 'SITS', icon: '📕', desc: 'SW 통합시험' },
  sds: { label: 'SDS', icon: '📋', desc: 'SW 아키텍처 설계' },
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
  // 파일영향(무정보 fatten 함수) 표시 토글 — 기본 숨김(집계·리스트에서 제외해 실변경 규모를 정직 표시).
  const [showFileImpact, setShowFileImpact] = useState(false);
  const [hideFormatOnly, setHideFormatOnly] = useState(false);
  // Track 2: AI 요약 ↔ 함수별 상세 탭. aiGuide 있으면 기본 'ai'(서머리 우선), 없으면 렌더 시 'fn' 강등.
  const [activeTab, setActiveTab] = useState('ai');
  // 문서별 상세 탭: 좌측에서 선택한 문서(uds/sts/suts/sits/sds). null이면 렌더 시 첫 '영향 있는' 문서로 확정.
  const [selectedDoc, setSelectedDoc] = useState(null);
  // 회귀시험 패널 '전체 보기' 토글 — 기본은 상위 N개만(잘림), true면 절단 없이 전체 노출(스크롤).
  const [regShowAll, setRegShowAll] = useState(false);

  // Impact data from analysis
  const changedFiles = impact?.trigger?.changed_files ?? impact?.changed_files ?? [];
  const changedFunctions = impact?.changed_function_types ?? {};
  const changedFnEntries = Object.entries(changedFunctions);
  const actions = impact?.actions ?? impact?.documents ?? {};
  // F2(wrong-pick 방지): scmList 폴백 시 [0](= registry 첫 entry, 타 프로젝트 규격일 수 있음)을
  // 무조건 집지 말고 job의 scm_id(trigger.scm_id)로 매칭한다. 매칭 실패 시에만 [0] 최후 폴백.
  const _jobScmId = impact?.trigger?.scm_id || '';
  const _scmListMatch = (_jobScmId && Array.isArray(analysisResult?.scmList))
    ? analysisResult.scmList.find(s => s?.id === _jobScmId)
    : null;
  const linkedDocs = impact?._linked_docs
    ?? analysisResult?.matchedScm?.linked_docs
    ?? _scmListMatch?.linked_docs
    ?? analysisResult?.scmList?.[0]?.linked_docs
    ?? {};
  const impactGroups = impact?.impact ?? {};
  // 분류 정밀도(백엔드 classification). "file"=파일단위 보수 분류 → "변경 함수" 수가
  // "변경 파일 내 전체 함수"의 과대추정(실제 수정 함수는 더 적음). "line"=라인 diff 정밀.
  const classification = impact?.classification ?? null;
  // 'file' = 전부 파일단위 보수(증거 혼재 없음) → 토글 대신 '(보수 추정)' 캡션.
  // 'mixed' = 일부만 라인증거 → isConservativeCount는 false로 두고 파일영향 토글(evidence split)로
  //           정직하게 분리한다(빈 표 방지 + 실변경/보수 전환). 'line' = 전부 라인증거(정밀).
  const isConservativeCount = classification?.granularity === 'file';
  // "line"=전 함수 라인 diff 정밀 분류(SIGNATURE/NEW/DELETE 함수단위 판별) — 'mixed'는 미포함(정직).
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
  // reviewer Finding#6: AI 요약 함수명 클릭 해석을 O(1)로. 매 렌더 guide.details를 함수 참조마다
  // 선형 2회 스캔하던 것을(안전함수/문서별/테스트제안 ~33개 × 2 × N) 소문자→canonical Map으로 대체.
  const guideFnByLc = useMemo(() => {
    const m = new Map();
    for (const d of (guide?.details || [])) m.set(String(d.function).toLowerCase(), d.function);
    return m;
  }, [guide]);
  // 소문자 함수명 → guide.details 항목(전체). renderDocContent(sts/sits)이 함수의 TC ID 목록
  // (stsTestCases/sitsTestCases)을 O(1)로 찾아 doc_content(sts_by_tc/sits_by_tc)와 조인하는 데 쓴다.
  const guideDetailByLc = useMemo(() => {
    const m = new Map();
    for (const d of (guide?.details || [])) m.set(String(d.function).toLowerCase(), d);
    return m;
  }, [guide]);
  // 회귀시험 선정: 영향 함수 → 재실행 대상 SUTS TC / SITS call-chain(ISO 26262 증거).
  const regressionSet = impact?.regression_test_set ?? null;
  // 프론트 SwUFn 브리지로 산출된 함수별 SITS TC({fn: [SwITC_SwUFn_N]}). 백엔드 regression_test_set.sits는
  // SITS VectorCAST 중간파일(빌더 산출물) 부재 시 0이지만(cloudium 읽기전용), 함수별 상세(buildGuide)는
  // testcase의 SwUFn을 SUTS unit으로 풀어 SITS를 직접 조인한다 → 회귀 패널에도 이 파생값을 표면화한다.
  const guideSitsMap = useMemo(() => {
    const m = {};
    for (const d of (guide?.details || [])) {
      if (d.sitsTestCases && d.sitsTestCases.length) m[d.function] = d.sitsTestCases;
    }
    return m;
  }, [guide]);
  // 콜그래프 탐색 절단 — 변경 함수가 상한을 넘으면 2-hop이 '미계산'인데 빈 배열로 나와
  // "2-hop 영향 없음"으로 오독될 수 있다(백엔드 impact_traversal이 사실을 알려줌).
  const traversal = impact?.impact_traversal ?? null;

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
  // 함수별 본문 diff 원문(AI 설명용) — BODY 등 선언 미변경 함수도 실제 코드 근거를 Gemini에 전달.
  const functionDiffs = impact?.function_diffs ?? {};
  // 파일레벨 원문 폴백(#3) — 함수 자체 diff 없는 함수(파일영향)의 '파일 전체 변경 보기'용. 정규화 상대경로 키.
  const fileDiffs = impact?.file_diffs ?? {};
  // 실제 문서 내용(예측 대신 실 파싱본) — 백엔드 doc_content{uds,suts,sds}(함수명 lower 키). 파일영향
  // 함수도 문서 내용은 실 파싱이라 유효. 구 job(필드 없음)은 {}로 폴백 → 내용 블록만 미표시(무해).
  const docContent = impact?.doc_content ?? {};
  const docContentFor = (fn, key) => (docContent?.[key] ?? {})[String(fn || '').toLowerCase()];
  // STS/SITS 실 내용은 TC-ID 키(함수 키 아님) — 프론트가 함수별 stsTestCases/sitsTestCases(ID)로 조인한다.
  // 백엔드 sts_by_tc/sits_by_tc는 _normalize_req_id(공백제거+대문자)로 키를 정규화하므로 조회 전 동일 정규화.
  const stsByTc = docContent?.sts_by_tc ?? {};
  const sitsByTc = docContent?.sits_by_tc ?? {};
  const _normTcId = (r) => String(r || '').replace(/\s+/g, '').toUpperCase();
  // 문서 카드의 "실제 문서 내용" 블록 — 예측 텍스트와 별개로, 백엔드가 파싱한 실 문서 내용을 표시.
  // uds/suts/sds만(범위). 내용 없으면 '미파싱' 정직 표기(과대 추정 금지). key='sts'/'sits'는 null(범위 외).
  const _dcBox = { fontSize: 10, marginTop: 4, padding: '4px 6px', background: 'var(--bg)', borderRadius: 4, borderLeft: '2px solid var(--color-info)' };
  const _dcHdr = { fontWeight: 600, fontSize: 9, color: 'var(--color-info)', marginBottom: 2 };
  const _dcMiss = (t) => <div className="text-muted" style={{ fontSize: 9, marginTop: 4 }}>· {t}</div>;
  const renderDocContent = (fn, key) => {
    const c = docContentFor(fn, key);
    if (key === 'uds') {
      if (!c) return _dcMiss('UDS 문서 내용 미파싱(사이드카/문서 미연동)');
      return (
        <div style={_dcBox}>
          <div style={_dcHdr}>📄 실제 UDS 내용</div>
          {c.heading && <div className="text-muted" style={{ fontSize: 9 }}>{c.heading}</div>}
          {c.description && <div style={{ overflowWrap: 'anywhere' }}>{c.description}</div>}
          {c.prototype && <div style={{ fontFamily: 'monospace', fontSize: 9, overflowWrap: 'anywhere' }}>{c.prototype}</div>}
          {(c.globals || []).length > 0 && <div style={{ fontSize: 9 }}><span className="text-muted">Used Globals: </span>{c.globals.join(', ')}</div>}
          {(c.calls || []).length > 0 && <div style={{ fontSize: 9 }}><span className="text-muted">Called: </span>{c.calls.join(', ')}</div>}
        </div>
      );
    }
    if (key === 'suts') {
      if (!c || !c.length) return _dcMiss('SUTS TC 내용 미파싱(문서 미연동/유닛 불일치)');
      return (
        <div style={_dcBox}>
          <div style={_dcHdr}>📄 실제 SUTS 시험 내용</div>
          {c.map((tc, i) => {
            // action/precondition은 문서 포맷에 따라 값(0x0)·변수명으로 나올 수 있어 prose(공백 포함)만
            // 노출(노이즈 억제). 실 입력/기대값(header=value)은 항상 노출(핵심 실 내용).
            const _prose = (s) => (typeof s === 'string' && /\s/.test(s.trim()) && s.trim().length > 3 ? s.trim() : '');
            const _act = _prose(tc.action); const _pre = _prose(tc.precondition);
            return (
              <div key={i} style={{ marginBottom: 3 }}>
                <div style={{ fontFamily: 'monospace', fontSize: 9, fontWeight: 600 }}>{tc.tc_id}</div>
                {_act && <div style={{ overflowWrap: 'anywhere' }}><span className="text-muted">Action: </span>{_act}</div>}
                {_pre && <div style={{ fontSize: 9 }}><span className="text-muted">Pre: </span>{_pre}</div>}
                {Object.keys(tc.inputs || {}).length > 0 && <div style={{ fontSize: 9, overflowWrap: 'anywhere' }}><span className="text-muted">In: </span>{Object.entries(tc.inputs).map(([k, v]) => `${k}=${v}`).join(', ')}</div>}
                {Object.keys(tc.expected || {}).length > 0 && <div style={{ fontSize: 9, overflowWrap: 'anywhere' }}><span className="text-muted">Exp: </span>{Object.entries(tc.expected).map(([k, v]) => `${k}=${v}`).join(', ')}</div>}
              </div>
            );
          })}
        </div>
      );
    }
    if (key === 'sds') {
      if (!c) return _dcMiss('SDS 컴포넌트 설명 미파싱(문서 미연동/매칭 없음)');
      return (
        <div style={_dcBox}>
          <div style={_dcHdr}>📄 실제 SDS 내용</div>
          <div style={{ overflowWrap: 'anywhere' }}>{c}</div>
        </div>
      );
    }
    if (key === 'sts' || key === 'sits') {
      // 함수의 TC ID 목록(브리지 산출)을 백엔드 TC-ID 키 내용 맵과 조인. ID만 있고 내용 0이면 정직 미파싱.
      const dd = guideDetailByLc.get(String(fn || '').toLowerCase());
      const tcIds = ((key === 'sts' ? dd?.stsTestCases : dd?.sitsTestCases) || []);
      if (!tcIds.length) return _dcMiss(key === 'sts' ? 'STS 매칭 TC 없음(요구/SDS 브리지 0)' : 'SITS 매칭 TC 없음(요구/SwUFn 브리지 0)');
      const byTc = key === 'sts' ? stsByTc : sitsByTc;
      const rows = tcIds.map((t) => [t, byTc[_normTcId(t)]]);
      if (!rows.some(([, cc]) => cc)) {
        return _dcMiss(key === 'sts'
          ? 'STS TC 내용 미파싱(문서 미연동/전용 파서 부재)'
          : 'SITS TC 내용 미파싱(중간파일 부재·cloudium)');
      }
      const _prose = (s) => (typeof s === 'string' && /\s/.test(s.trim()) && s.trim().length > 3 ? s.trim() : '');
      return (
        <div style={_dcBox}>
          <div style={_dcHdr}>📄 실제 {key.toUpperCase()} 시험 내용</div>
          {rows.slice(0, 6).map(([t, cc], i) => (
            <div key={i} style={{ marginBottom: 3 }}>
              <div style={{ fontFamily: 'monospace', fontSize: 9, fontWeight: 600 }}>{t}</div>
              {!cc && <span className="text-muted" style={{ fontSize: 9 }}>· 내용 미파싱</span>}
              {cc && _prose(cc.description) && <div style={{ overflowWrap: 'anywhere' }}>{_prose(cc.description)}</div>}
              {cc && cc.unit_name && <div style={{ fontSize: 9 }}><span className="text-muted">Unit: </span>{cc.unit_name}</div>}
              {cc && _prose(cc.precondition) && <div style={{ fontSize: 9 }}><span className="text-muted">Pre: </span>{_prose(cc.precondition)}</div>}
              {cc && cc.test_method && <div style={{ fontSize: 9 }}><span className="text-muted">Method: </span>{cc.test_method}</div>}
              {/* STS 'Test Action(Sequence)'/'Expected Result' — cc.expected는 STS에선 string(SITS/SUTS의 kv dict 아님) → 직접 렌더(Object.entries 금지). 짧은 값(0x1)도 노출 위해 _prose 미적용. */}
              {cc && _prose(cc.test_action) && <div style={{ overflowWrap: 'anywhere' }}><span className="text-muted">Action: </span>{_prose(cc.test_action)}</div>}
              {cc && cc.expected && <div style={{ fontSize: 9, overflowWrap: 'anywhere' }}><span className="text-muted">Exp: </span>{cc.expected}</div>}
              {cc && cc.call_chain && <div style={{ fontSize: 9, fontFamily: 'monospace', overflowWrap: 'anywhere' }}><span className="text-muted">Chain: </span>{cc.call_chain}</div>}
              {cc && (cc.sub_cases || []).slice(0, 3).map((sc, j) => (
                <div key={j} style={{ marginTop: 2, paddingLeft: 6, borderLeft: '1px solid var(--border)' }}>
                  {_prose(sc.precondition) && <div style={{ fontSize: 9 }}><span className="text-muted">Pre: </span>{_prose(sc.precondition)}</div>}
                  {Object.keys(sc.inputs || {}).length > 0 && <div style={{ fontSize: 9, overflowWrap: 'anywhere' }}><span className="text-muted">In: </span>{Object.entries(sc.inputs).map(([k, v]) => `${k}=${v}`).join(', ')}</div>}
                  {Object.keys(sc.expected || {}).length > 0 && <div style={{ fontSize: 9, overflowWrap: 'anywhere' }}><span className="text-muted">Exp: </span>{Object.entries(sc.expected).map(([k, v]) => `${k}=${v}`).join(', ')}</div>}
                </div>
              ))}
            </div>
          ))}
          {rows.length > 6 && <div className="text-muted" style={{ fontSize: 9 }}>+{rows.length - 6}개 TC 더</div>}
        </div>
      );
    }
    return null;
  };
  // 변경종류 요약(신규/삭제/시그니처/본문/헤더/변수 개수) — 데모 포함(activeFnEntries 기준, 전체).
  const changeSummary = { NEW: 0, DELETE: 0, SIGNATURE: 0, BODY: 0, HEADER: 0, VARIABLE: 0 };
  for (const [, k] of activeFnEntries) { if (k in changeSummary) changeSummary[k] += 1; }

  // ── 파일영향(무정보) 분리 — 직접 변경 증거 없이 fatten으로 딸려온 함수를 집계/리스트에서 옵션 처리 ──
  // "변경 함수" 수를 부풀리므로 기본 숨김. 라인 diff 분류(isLineClassified)이면서 증거 有/無가 혼재할
  // 때만 토글 제공(hasEvidenceSplit). 전부 보수 분류거나 전부 증거면 분리가 무의미 → 토글 없이 전체 표시.
  const evidencedFnEntries = activeFnEntries.filter(([fn, k]) => !functionHasNoEvidence(fn, k, changeDetails, functionDiffs, functionMeta));
  const noEvidenceCount = activeFnEntries.length - evidencedFnEntries.length;
  // 데모(합성 데이터, change_details/function_diffs 없음)는 전부 무정보로 잡히므로 분리 제외 — 데모가 텅 비지 않게.
  const hasEvidenceSplit = !demoMode && !isConservativeCount && noEvidenceCount > 0 && evidencedFnEntries.length > 0;
  const hideFileImpact = hasEvidenceSplit && !showFileImpact;
  // 포맷/이동만(의미 변경 없음) 함수 — 본문 diff가 코드 이동/공백/포맷만이라 실 변경으로 오인되기 쉬움. 필터 제공.
  const formatOnlyCount = useMemo(
    () => (guide?.details || []).filter(
      (d) => d.changed && extractDiffElementsCached(functionDiffs[String(d.function).toLowerCase()] || '').noSemanticChange,
    ).length,
    [guide, functionDiffs],
  );
  const visibleFnEntries = hideFileImpact ? evidencedFnEntries : activeFnEntries;
  const visibleChangeSummary = { NEW: 0, DELETE: 0, SIGNATURE: 0, BODY: 0, HEADER: 0, VARIABLE: 0 };
  for (const [, k] of visibleFnEntries) { if (k in visibleChangeSummary) visibleChangeSummary[k] += 1; }

  // ── 파일영향 분리를 요약 전 패널로 전파 — impact.direct·actions[doc].functions·coverage_gap.functions는
  // 모두 함수명(소문자) 리스트. changed_function_types 키는 대소문자 혼용이라 소문자 kind 맵으로 조회한다. ──
  const changedKindLower = {};
  for (const [fn, k] of activeFnEntries) changedKindLower[String(fn).toLowerCase()] = k;
  const nameIsNoEvidence = (name) => {
    const lf = String(name).toLowerCase();
    const kind = changedKindLower[lf];
    if (!kind) return false;  // 변경 함수 목록에 없음(간접/기타) → 파일영향 아님(유지)
    return functionHasNoEvidence(name, kind, changeDetails, functionDiffs, functionMeta);
  };
  // hideFileImpact면 무정보(파일영향) 함수명을 제외한 리스트. 아니면 원본.
  const visibleNameList = (list) => (hideFileImpact ? (list || []).filter((n) => !nameIsNoEvidence(n)) : (list || []));
  // 직접 영향 = 변경 함수와 동일 집합(소문자) — 실변경만 세고 파일영향은 분리.
  const directAll = activeImpactGroups.direct || [];
  const directVisibleCount = visibleNameList(directAll).length;
  const directHiddenCount = directAll.length - directVisibleCount;
  // 커버리지 — 파일영향(무변경) 함수는 이 변경이 유발한 갭이 아니므로 기본 제외(오귀속 방지).
  // 전체 표시(토글 ON·분리 없음·제외분 0)면 백엔드 summary를 그대로 사용(재계산 divergence 방지),
  // 파일영향을 제외할 때만 함수 리스트에서 재집계한다.
  const covView = (() => {
    if (!coverageGap?.available || !coverageGap.summary) return null;
    const s = coverageGap.summary;
    // 미매칭/미검증 지표(백엔드 coverage_gap.py가 "증거 부재를 '충족'으로 위장 금지"로 산출).
    // unmatched 함수는 functions[] rows에 없으므로(매칭 실패 → continue) 파일영향 필터로 재집계
    // 불가 → summary 값을 그대로 노출하고 "전체 영향 함수 기준"임을 명시한다(무표시 = 위장).
    const evid = {
      unmatched: s.unmatched ?? 0,
      unmatchedSafety: s.unmatched_safety ?? 0,
      unmeasuredSafety: s.unmeasured_safety ?? 0,
      unknownAsil: s.unknown_asil ?? 0,
      // Δ 신뢰도: (a) baseline이 같은 빌드 → delta≡0, (b) revision 미상(로컬 diff 등) → 같은 빌드인지
      // 알 수 없음, (c) baseline이 더 최신(과거 빌드 분석) → 개선분이 음수 Δ로 뒤집혀 유령 회귀.
      // 셋 중 하나라도 참이면 "회귀 N"을 수치로 단정하지 않는다(위장 방지).
      sameRevBaseline: !!s.baseline_same_revision,
      deltaUntrusted: !!(s.baseline_same_revision || s.baseline_revision_unknown || s.baseline_newer_than_build),
      deltaUntrustReason: s.baseline_same_revision ? '같은 빌드 — Δ 비교 불가'
        : s.baseline_newer_than_build ? '직전 스냅샷이 더 최신 빌드 — Δ 신뢰 불가(유령 회귀)'
          : s.baseline_revision_unknown ? '스냅샷 빌드 미상 — Δ 신뢰 불가' : '',
      baselineRevision: s.baseline_revision || '',
      // 이름충돌로 worst-copy(최악 copy) rate를 노출한 함수 수(백엔드 collision_worst_copy) — 전역
      // max 병합의 gap 은폐를 안전측으로 대체했음을 표면화(0이면 충돌 영향 없음/단일 copy).
      collisionWorstCopy: s.collision_worst_copy ?? 0,
    };
    const base = { evaluated: s.evaluated ?? 0, below: s.below_target ?? 0, unmeasured: s.unmeasured ?? 0, regressed: s.regressed ?? 0, hidden: 0, hadBaseline: s.had_baseline, ...evid };
    const fns = coverageGap.functions || [];
    if (!hideFileImpact || !fns.length) return base;
    const vis = fns.filter((f) => !nameIsNoEvidence(f.function));
    const hidden = fns.length - vis.length;
    if (!hidden) return base;
    return {
      evaluated: vis.length,
      below: vis.filter((f) => f.meets_target === false && !f.unmeasured_target).length,
      unmeasured: vis.filter((f) => f.unmeasured_target).length,
      regressed: vis.filter((f) => typeof f.delta === 'number' && f.delta < 0).length,
      hidden,
      hadBaseline: s.had_baseline,
      ...evid,
    };
  })();

  // ── 문서별 상세 탭 (함수-우선 → 문서-우선 전치) ──────────────────────────────────────────
  // 멤버십은 권위 백엔드 actions[doc].functions(파일영향 제외), 편집 액션은 함수 상세 모달과 동일한
  // 결정론 헬퍼 buildDocumentActions(d)[doc]. 신규 fetch·백엔드 변경 없음(순수 재피벗).
  const docCounts = {};
  for (const k of DOC_KEYS) docCounts[k] = visibleNameList(actions[k]?.functions || []).length;
  // 최초 미선택(null)일 때만 첫 '영향 있는' 문서로 폴백. 사용자가 명시적으로 고른 문서는 0-count여도
  // 존중해 '이 문서에 영향 없음' 빈 상태를 보여준다(reviewer W7: 0-count면 조용히 튕기던 wrong-pick 제거).
  const effSelectedDoc = selectedDoc || (DOC_KEYS.find(k => docCounts[k] > 0) || 'uds');
  // 우측 함수행 하단 칩 — 문서 성격에 맞는 매핑만(UDS=요구, STS/SUTS=해당 TC).
  const docChips = (doc, d) => (doc === 'uds' ? (d.requirements || []) : doc === 'sts' ? (d.stsTestCases || []) : doc === 'suts' ? (d.sutsTestCases || []) : doc === 'sits' ? (d.sitsTestCases || []) : []);
  // 선택 문서의 함수 행(direct 우선 정렬). activeTab==='doc'일 때만 계산 — buildDocumentActions ×N 회피.
  const docRows = useMemo(() => {
    if (!guide || activeTab !== 'doc') return [];
    const byLc = new Map();
    for (const dd of guide.details) byLc.set(String(dd.function).toLowerCase(), dd);
    let rows = (actions[effSelectedDoc]?.functions || []).map((name) => {
      const d = byLc.get(String(name).toLowerCase()) || null;
      if (!d) return { name, d: null, acts: [] };
      const cd = changeDetails[String(d.function).toLowerCase()] || {};
      const fd = functionDiffs[String(d.function).toLowerCase()] || '';
      const pdiff = (cd.before || cd.after) ? diffSignatureParamsCached(cd.before, cd.after) : null;
      const acts = buildDocumentActions(d, pdiff, extractDiffElementsCached(fd))[effSelectedDoc] || [];
      return { name: d.function, d, acts };
    });
    // 파일영향(직접 변경·증거 없음) 제외 — filteredGuide(L778)와 동일 규칙(간접은 유지).
    if (hideFileImpact) rows = rows.filter(r => !(r.d?.changed && functionHasNoEvidence(r.d.function, r.d.changeType, changeDetails, functionDiffs, functionMeta)));
    if (hideFormatOnly) rows = rows.filter(r => !(r.d?.changed && extractDiffElementsCached(functionDiffs[String(r.d.function).toLowerCase()] || '').noSemanticChange));
    rows.sort((a, b) => {
      const ac = a.d?.changed ? 0 : 1; const bc = b.d?.changed ? 0 : 1;
      if (ac !== bc) return ac - bc;                                   // 직접 변경 우선
      const ao = CHANGE_ORDER[a.d?.changeType] || 0; const bo = CHANGE_ORDER[b.d?.changeType] || 0;
      if (ao !== bo) return bo - ao;                                    // 구조적 변경(시그니처/신규/삭제) 우선
      return String(a.name).localeCompare(String(b.name));
    });
    return rows;
  }, [guide, activeTab, effSelectedDoc, actions, changeDetails, functionDiffs, functionMeta, hideFileImpact, hideFormatOnly]);

  const filteredGuide = useMemo(() => {
    if (!guide) return [];
    let items = guide.details;
    // 파일영향(무정보) 숨김 — 직접 변경이나 증거 없는(fatten) 함수 제외. 간접(changed=false)은 유지.
    if (hideFileImpact) items = items.filter(d => !(d.changed && functionHasNoEvidence(d.function, d.changeType, changeDetails, functionDiffs, functionMeta)));
    if (hideFormatOnly) items = items.filter(d => !(d.changed && extractDiffElementsCached(functionDiffs[String(d.function).toLowerCase()] || '').noSemanticChange));
    if (hopFilter !== 'all') items = items.filter(d => d.hop === hopFilter);
    if (docFilter === 'has_reqs') items = items.filter(d => d.requirements.length > 0);
    else if (docFilter === 'has_sts') items = items.filter(d => d.stsTestCases.length > 0);
    else if (docFilter === 'has_suts') items = items.filter(d => d.sutsTestCases.length > 0);
    // '매핑 없음'은 요구사항·STS·SUTS TC가 모두 없을 때만 — SUTS TC만 있는 함수를 '매핑 없음'으로
    // 오분류하던 버그 수정(SUTS TC도 실제 매핑 증거).
    else if (docFilter === 'no_mapping') items = items.filter(d => d.requirements.length === 0 && d.stsTestCases.length === 0 && d.sutsTestCases.length === 0 && (d.sitsTestCases || []).length === 0);
    if (searchTerm.trim()) {
      const q = searchTerm.trim().toLowerCase();
      items = items.filter(d =>
        d.function.toLowerCase().includes(q) ||
        d.requirements.some(r => r.toLowerCase().includes(q)) ||
        d.stsTestCases.some(tc => tc.toLowerCase().includes(q)) ||
        d.sutsTestCases.some(tc => tc.toLowerCase().includes(q)) ||
        (d.sitsTestCases || []).some(tc => tc.toLowerCase().includes(q))
      );
    }
    return items;
  }, [guide, hopFilter, docFilter, searchTerm, hideFileImpact, hideFormatOnly, changeDetails, functionDiffs, functionMeta]);

  // Build detailed guide
  const buildGuide = useCallback(async () => {
    if (!activeFnEntries.length) {
      toast('info', '변경된 함수가 없습니다.');
      return;
    }
    setLoading(true);
    // reviewer Finding#4: 이전 분석의 AI 요약 오염 방지. AI fetch 실패는 catch로 삼켜(L930) 성공 시에만
    // setAiGuide되므로, 새 분석 시작 시 초기화하지 않으면 직전 분석의 위험도/안전함수/테스트제안이
    // 함수별 상세(새 데이터)와 뒤섞여 표시된다(ISO 위험 요약 cross-analysis 오염).
    setAiGuide(null);
    try {
      // 추출 API 실패를 삼키지 않고 수집 — '매핑 없음'(실제 부재)과 '조회 실패'(403/500/네트워크)를
      // 구분해 사용자에게 표면화한다. 과거 catch(_){}로 실패해도 성공 토스트가 뜨던 silent 버그 방지.
      const fetchFailures = [];
      let udsMapping = [];
      let stsTCs = [];
      let sutsTCs = [];
      let sdsPairs = [];   // SDS 함수↔SwRS요구 브리지(SwRS 허브 경유 — STS/SITS TC 조인의 핵심)
      let sitsTCs = [];    // SITS req→TC (SwRS 허브 키)
      // Track 1a: 검토 TC(STS 조인) = 0일 때 사유를 정직 표시하기 위한 진단 플래그.
      let stsSheetUnrecognized = false;

      if (demoMode) {
        // 데모: 실제 추출 API를 데모 함수명으로 호출하면 매핑이 항상 비므로 데모 매핑을 직접 주입해
        // 요구사항/STS/SUTS TC가 채워진 완전한 시나리오를 보여준다(과거엔 빈 가이드만 나왔다).
        udsMapping = DEMO_UDS_MAPPING;
        stsTCs = DEMO_STS_TCS;
        sutsTCs = DEMO_SUTS_TCS;
        sitsTCs = DEMO_SITS_TCS;
        // sdsPairs는 데모에서 비움 — STS/SITS 조인은 UDS-경로(funcToReqs→SwRS_*) union으로 성립.
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
            if (!stsTCs.length && Array.isArray(d?.available_sheets)) {
              stsSheetUnrecognized = true;
              if (typeof toast === 'function') toast('warning', `STS 시트 미인식. 사용 가능한 시트: ${d.available_sheets.join(', ')}`);
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

        // 4. SDS 함수↔SwRS요구 브리지(SwRS 허브) — STS TC 매칭 0의 근본 해결. UDS 설계요구(SwSTR)와
        //    STS TC 요구(SwEI)가 계열이 달라 직접 조인 0이므로, SDS의 함수명↔SW요구 매핑으로 우회한다.
        if (linkedDocs.sds) {
          try {
            const d = await post('/api/jenkins/sds/extract-mapping', { sds_path: linkedDocs.sds });
            sdsPairs = d?.sds_pairs ?? [];
          } catch (e) { fetchFailures.push({ doc: 'SDS', msg: e?.message || '조회 실패' }); }
        }

        // 5. SITS req→TC — 같은 SwRS 허브 경유로 per-function SITS TC 조인.
        if (linkedDocs.sits) {
          try {
            const d = await post('/api/jenkins/sits/extract-traceability', { path: linkedDocs.sits });
            sitsTCs = d?.vcast_rows ?? [];
          } catch (e) { fetchFailures.push({ doc: 'SITS', msg: e?.message || '조회 실패' }); }
        }
      }

      // Build per-function guide
      // F1(검토 TC=0 근본): STS extract-traceability는 requirement_id를 _normalize_req_id로
      // 대문자화(+Sy→Sw)해 방출하지만, UDS extract-mapping은 raw regex 매치(원본 케이스)를 방출한다.
      // 정규화 없이 조인하면 STS 키 'SWTR_1' vs UDS rid 'SwTR_1'이 영구 미스 → 검토 TC=0.
      // 조인 키만 정규화하고, 표시용(details.requirements)은 UDS 원본 케이스를 보존한다.
      const _normReq = (r) => String(r || '').replace(/\s+/g, '').toUpperCase();
      // SDS 컴포넌트/함수명 → bridge 키 정규화. 백엔드 _sds_comp_key(report_gen/requirements.py:86)를
      // 완전 포팅: 소문자화 → 선행 '행번호+탭' 표 아티팩트 제거 → '(' 이전만 → 배열첨자 제거 후 재trim
      // → 선행 '_' 제거 → 순수 C 식별자만 반환(아니면 '' 폐기 — 한글 설명문 등 거짓 bridge 차단).
      const _sdsKey = (c) => {
        let s = String(c || '').trim().toLowerCase();
        if (!s) return '';
        s = s.replace(/^\d+\s*\t/, '');          // 표 파싱 아티팩트(행번호+탭)
        s = s.split('(')[0];                      // 시그니처 조각 제거
        s = s.replace(/\[[^\]]*\]/g, '').trim();  // 배열첨자 제거 후 재trim(공백 잔류 방지)
        s = s.replace(/^_+/, '');                 // 선행 '_'(_entrypoint↔entrypoint)
        return /^[a-z_][a-z0-9_]*$/.test(s) ? s : '';
      };
      // 반환형 헝가리안 접두사 제거(백엔드 _strip_ret_type_prefix:115). SDS 'u16s_X' ↔ 테스트 's_X'
      // 불일치 보정용 — 완전키는 보존하고, 충돌 안전한 base만 alias로 추가(아래 sdsFuncToReqs 참조).
      const _stripRet = (s) => s.replace(/^(?:u8|u16|u32|s8|s16|s32)(?=[sgl]_)/, '');
      // F3(reviewer sweep): funcToReqs 키는 UDS source_ids(문서 "Name" 셀 원본 케이스 — backend가
      // 소문자화하지 않는다, jenkins.py:4025 func_name 원본 보존). 반면 guide fn은 backend by_name
      // 정규화로 소문자다. 정규화 없이 조회하면 mixed-case 함수명(예 'EEPROM_SetByte')은
      // funcToReqs[소문자] 미스 → 요구사항·STS TC가 통째로 0 → ISO 26262 검토범위 under-report
      // (kjpds02는 all-lowercase라 미발현, hdpdm01/NE_GN7 CamelCase에서 발현). fnToSutsTCs와 동일하게
      // 조인 키만 양측 소문자화하고, 표시용 requirement_id는 원본을 보존한다.
      const funcToReqs = {};
      for (const mp of udsMapping) {
        for (const fn of (mp.source_ids || [])) {
          const fk = String(fn || '').trim().toLowerCase();
          if (!fk) continue;
          if (!funcToReqs[fk]) funcToReqs[fk] = new Set();
          funcToReqs[fk].add(mp.requirement_id);
        }
      }

      const reqToStsTCs = {};
      for (const row of stsTCs) {
        const rid = _normReq(row.requirement_id);
        if (!reqToStsTCs[rid]) reqToStsTCs[rid] = new Set();
        reqToStsTCs[rid].add(row.testcase);
      }

      // F1-parallel(reviewer Finding#1): SUTS unit 컬럼도 원본 케이스 → 소문자 guide fn과 조인하려면
      // 양측 정규화 필요. 안 하면 per-function SUTS TC가 조용히 0이 되어 ISO 회귀 증거가 과소보고된다.
      // ⚠ 스코프 주의: 이 함수-테이블 SUTS는 추적성 '3.SW Test Spec' 시트(unit 컬럼) 기준 = 전체 영향
      //   함수의 '보유 시험'이다. 회귀 패널 SUTS(regression_test_set.suts)는 백엔드 '2.SW Unit Test Spec'
      //   시트의 TC 블록(base_tc_id) 보유 기준 = '재실행 대상'이라, 다른 시트·다른 기준이므로 두 수치는
      //   구조적으로 다를 수 있다(과거 "회귀 패널과 일치해야" 단언은 오류 — 시트가 달라 일치 보장 불가).
      const fnToSutsTCs = {};
      for (const row of sutsTCs) {
        const uk = String(row.unit || '').trim().toLowerCase();
        if (!uk) continue;
        if (!fnToSutsTCs[uk]) fnToSutsTCs[uk] = new Set();
        fnToSutsTCs[uk].add(row.testcase);
      }

      // SwRS 허브 브리지: 함수(정규화) → SW요구(SwRS) 집합. SDS sds_pairs.component_ids는 컴포넌트+
      // 인터페이스 함수명을 모두 담고(백엔드가 _sds_comp_key로 정규화), requirement_id는 SwRS 계열.
      // _normFn으로 반환형 접두사를 수렴시켜 impact 함수명과 매칭한다.
      // 전체 SDS 키 선스캔 후, 반환형 접두사 base가 ①단 하나의 접두사형에서만 파생되고 ②그 base가
      // 별도 SDS 키가 아닐 때만 alias 등록(백엔드 _alias_safe, requirements.py:2078-2103). 충돌형
      // (u8g_X·s8g_X — 반환형 다른 별개 함수)이 같은 base로 모이면 alias를 안 만들어 오귀속을 막는다.
      const _allSdsKeys = new Set();
      for (const p of sdsPairs) for (const c of (p.component_ids || [])) { const k = _sdsKey(c); if (k) _allSdsKeys.add(k); }
      const _prefBaseCount = {};
      for (const k of _allSdsKeys) { const b = _stripRet(k); if (b !== k) _prefBaseCount[b] = (_prefBaseCount[b] || 0) + 1; }
      const _aliasSafe = new Set();
      for (const [b, cnt] of Object.entries(_prefBaseCount)) if (cnt === 1 && !_allSdsKeys.has(b)) _aliasSafe.add(b);
      const sdsFuncToReqs = {};
      for (const p of sdsPairs) {
        const rid = _normReq(p.requirement_id);
        for (const c of (p.component_ids || [])) {
          const key = _sdsKey(c);
          if (!key) continue;
          const keys = [key];                                  // 완전키는 항상 등록
          const alias = _stripRet(key);
          if (alias !== key && _aliasSafe.has(alias)) keys.push(alias);  // 안전 base만 alias 추가
          for (const kk of keys) {
            if (!sdsFuncToReqs[kk]) sdsFuncToReqs[kk] = new Set();
            sdsFuncToReqs[kk].add(rid);
          }
        }
      }
      // SITS req→TC — reqToStsTCs와 동일 패턴(SwRS 허브 키).
      const reqToSitsTCs = {};
      for (const row of sitsTCs) {
        const rid = _normReq(row.requirement_id);
        if (!reqToSitsTCs[rid]) reqToSitsTCs[rid] = new Set();
        reqToSitsTCs[rid].add(row.testcase);
      }
      // SITS는 요구가 아니라 단위(SwUFn) 기반이다 — 실 kjpds02 SITS TC는 SYSTEMTM 네임스페이스 요구만
      // 참조해 SwRS 허브로는 0이지만, testcase ID(SwITC_SwUFn_0112)에 SwUFn(단위함수) ID를 품는다.
      // SUTS TC(SwUTC_SwUFn_N, unit=함수명)로 SwUFn→함수명 맵을 만들어 SITS TC를 함수에 직접 연결한다
      // (백엔드 트레이스 매트릭스의 SITS 2-hop과 동일 원리, report_gen/requirements.py:2203).
      // 백엔드 _SWUFN_RE(requirements.py:29)·jenkins.py:1082와 동일 — SwUFn_(단위)·SwIFn_(통합) +
      // SwFn_(Fault Injection, SwITC_FI_SwFn_*)까지. 과거 /Sw[UI]Fn_/는 FI TC를 통째로 탈락시켰다.
      const _SWUFN_RE = /Sw[UI]?Fn_\d+/ig;
      const swufnToFn = {};
      for (const row of sutsTCs) {
        const unit = String(row.unit || '').trim().toLowerCase();
        if (!unit) continue;
        for (const m of String(row.testcase || '').match(_SWUFN_RE) || []) {
          const k = m.toUpperCase();
          if (!swufnToFn[k]) swufnToFn[k] = new Set();
          swufnToFn[k].add(unit);
        }
      }
      const fnToSitsTCs = {};  // 함수명(lower) → Set<SITS TC>  (SwUFn 단위 경로 + 콜체인 경로)
      for (const row of sitsTCs) {
        const tc = String(row.testcase || '');
        // (1) SwUFn 단위 경로 — testcase의 SwUFn/SwIFn/SwFn을 SUTS unit 맵으로 함수에 연결(entry).
        for (const m of tc.match(_SWUFN_RE) || []) {
          for (const fn of (swufnToFn[m.toUpperCase()] || [])) {
            if (!fnToSitsTCs[fn]) fnToSitsTCs[fn] = new Set();
            fnToSitsTCs[fn].add(tc);
          }
        }
        // (2) 콜체인 경로 — 백엔드가 파싱한 "Interface : A -> B -> ..." 체인 함수(깊은 callee 포함)에 TC 귀속.
        //     entry SwUFn뿐 아니라 체인 상 모든 함수가 그 통합시험 커버리지를 인정받는다(g_drvin 0 해소).
        for (const cf of (row.chain_fns || [])) {
          const fn = String(cf || '').trim().toLowerCase();
          if (!fn) continue;
          if (!fnToSitsTCs[fn]) fnToSitsTCs[fn] = new Set();
          fnToSitsTCs[fn].add(tc);
        }
      }

      const details = [];
      const allReqs = new Set();
      const allStsTcs = new Set();
      const allSitsTcs = new Set();

      // 가이드 행 = 변경(직접) 함수 ∪ 간접 영향 함수(1/2hop). 과거엔 changed 함수만 순회해서
      // 모든 행의 hop이 'direct'로 고정 → 1-hop/2-hop 필터가 영구히 죽고, 간접 영향 ASIL 함수가
      // 가이드에서 통째로 누락(ISO 26262 under-report)됐다. 간접 함수는 변경종류 없음(changed=false)으로
      // 구분 표기하되, backend function_meta의 ASIL·커버리지·요구/시험 매핑은 동일하게 조인한다.
      const changedMap = new Map(activeFnEntries.map(([fn, k]) => [fn, k]));
      // NOTE(F3 검토 반영): 대소문자 무관 dedup은 정상 경로에선 no-op(백엔드가 changed_types를
      // by_name 기준 소문자로 정규화 → impact-group과 케이스 동일)이고, source_root 미해결 edge
      // 경로에선 오히려 ASIL이 해석되는 소문자 사본을 버리고 ASIL 공백인 원본 케이스만 남겨
      // ASIL 가시성을 떨어뜨릴 수 있어(reviewer Finding #1) 도입하지 않는다. 정확한 처리는
      // function_meta/coverage 소문자 폴백 lookup으로 한다(아래 details.asil/coverage의 _fnLc 폴백, 해소됨).
      const guideFns = [...new Set([
        ...changedMap.keys(),
        ...(activeImpactGroups.direct || []),
        ...(activeImpactGroups.indirect_1hop || []),
        ...(activeImpactGroups.indirect_2hop || []),
      ].filter(Boolean))];

      for (const fn of guideFns) {
        const changeType = changedMap.get(fn) || '';
        const isChanged = changedMap.has(fn);
        // 조인은 소문자 정규화 키로(funcToReqs·fnToSutsTCs 양측 소문자화 — mixed-case 함수명
        // under-report 방지). 표시용 이름(details.function)은 원본 fn을 그대로 보존한다.
        const _fnLc = String(fn).toLowerCase();
        const reqs = funcToReqs[_fnLc] ? [...funcToReqs[_fnLc]] : [];
        reqs.forEach(r => allReqs.add(r));

        // STS/SITS TC 조인 요구집합 = UDS 설계요구(정규화) ∪ SDS 브리지 SwRS요구(함수→SwRS).
        // 순수 가산(최대 recall) — UDS 경로는 데모/타 프로젝트에서 SwRS 직접 참조 시 유효, 실 kjpds02는
        // SDS 브리지가 실효. 두 계열이 disjoint라 겹침 없음.
        const _fk = _sdsKey(fn);
        const joinReqs = new Set([...reqs.map(_normReq), ...(sdsFuncToReqs[_fk] || [])]);
        const stsTcSet = new Set();
        const sitsTcSet = new Set();
        for (const rid of joinReqs) {
          (reqToStsTCs[rid] || new Set()).forEach(tc => { stsTcSet.add(tc); allStsTcs.add(tc); });
          (reqToSitsTCs[rid] || new Set()).forEach(tc => { sitsTcSet.add(tc); allSitsTcs.add(tc); });
        }
        // SITS 단위(SwUFn) 경로 — 요구 경로와 union. SITS는 통합-단위 기반이라 실데이터에선 이 경로가 실효.
        (fnToSitsTCs[_fnLc] || new Set()).forEach(tc => { sitsTcSet.add(tc); allSitsTcs.add(tc); });

        const sutsTcList = fnToSutsTCs[_fnLc] ? [...fnToSutsTCs[_fnLc]] : [];
        const hop = (activeImpactGroups.direct || []).includes(fn) ? 'direct'
          : (activeImpactGroups.indirect_1hop || []).includes(fn) ? '1-hop'
          : (activeImpactGroups.indirect_2hop || []).includes(fn) ? '2-hop'
          : (isChanged ? 'direct' : '1-hop');

        details.push({
          function: fn,
          changeType,
          changed: isChanged,
          // function_meta/coverage는 backend by_name(소문자) 키 — CamelCase 프로젝트(hdpdm01 계열)에서
          // 원본 fn 직접조회가 미스해 알려진 ASIL이 공백=under-report 됐다(위 주석의 '별도 라운드' 해소).
          // 조인부(_fnLc)와 동일 폴백. by_name은 소문자 max-merge라 폴백이 낮은등급 오선택 안 함(안전측).
          asil: (functionMeta[fn] || functionMeta[_fnLc])?.asil || '',
          coverage: coverageByFn[fn] || coverageByFn[_fnLc] || null,
          hop,
          requirements: reqs,
          stsTestCases: [...stsTcSet],
          sutsTestCases: sutsTcList,
          sitsTestCases: [...sitsTcSet],
        });
      }
      // 직접(변경) → 1-hop → 2-hop 순으로 정렬(변경 함수 우선 노출), 동일 hop은 함수명순.
      const HOP_RANK = { direct: 0, '1-hop': 1, '2-hop': 2 };
      details.sort((a, b) => (HOP_RANK[a.hop] - HOP_RANK[b.hop]) || a.function.localeCompare(b.function));

      // Track 1a: 검토 TC=0을 bare 0 대신 사유로 정직 표시(silent 0 금지). 연동/시트/브리지 단계 구분.
      // STS/SITS TC는 이제 SwRS 허브(SDS 함수↔SW요구 브리지) 경유로 조인되므로, 0의 사유도 STS 시트
      // 단계 → SDS 브리지 단계 순으로 좁혀 표기한다. (과거 '요구 유형 상이 … 허브 경유 필요' 힌트는
      // 실제로 허브를 경유하게 됐으므로 제거.)
      const _sdsBridgeReason = () => {
        if (!linkedDocs.sds) return 'SDS 미연동 (SwRS 허브 브리지 불가)';
        if (fetchFailures.some(f => f.doc === 'SDS')) return 'SDS 조회 실패 (SwRS 허브 브리지 불가)';
        if (sdsPairs.length === 0) return 'SDS 매핑 0 (함수↔SW요구 브리지 없음)';
        return null;
      };
      let stsTcReason = null;
      if (!demoMode && allStsTcs.size === 0) {
        if (!linkedDocs.sts) stsTcReason = 'STS 미연동';
        else if (fetchFailures.some(f => f.doc === 'STS')) stsTcReason = 'STS 조회 실패';
        else if (stsSheetUnrecognized) stsTcReason = 'STS 시트 미인식';
        // reviewer Finding#7: 시트를 못 찾은 경우(available_sheets 반환)만 '미인식'. 시트는 인식됐으나
        // 매핑 행이 0인 경우는 별도 사유로 구분(정직성).
        else if (stsTCs.length === 0) stsTcReason = 'STS 매핑 0 (시트 인식·행 없음)';
        else stsTcReason = _sdsBridgeReason() || 'SDS 브리지 매핑 0 (영향 함수가 SDS 컴포넌트 미포함)';
      }
      // SITS TC 사유 — STS와 대칭(같은 SwRS 브리지). 0이어도 통합 콜체인(회귀 패널)이 보완.
      let sitsTcReason = null;
      if (!demoMode && allSitsTcs.size === 0) {
        if (!linkedDocs.sits) sitsTcReason = 'SITS 미연동';
        else if (fetchFailures.some(f => f.doc === 'SITS')) sitsTcReason = 'SITS 조회 실패';
        else if (sitsTCs.length === 0) sitsTcReason = 'SITS 매핑 0 (시트 인식·행 없음)';
        // SITS는 SwRS 허브(요구) ∪ SwUFn(단위) 이중 브리지로 조인. 둘 다 0이면 통합케이스가 영향 함수와
        // 무관(요구가 시스템 네임스페이스거나 단위 불일치) — 통합 콜체인이 보완 신호.
        else sitsTcReason = '영향 함수에 매칭되는 SITS 통합케이스 없음 — 통합 콜체인 참조';
      }
      setGuide({
        details,
        fetchFailures,
        summary: {
          impactedReqs: allReqs.size,
          impactedStsTCs: allStsTcs.size,
          impactedSitsTCs: allSitsTcs.size,
          stsTcReason,
          sitsTcReason,
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
    const noEvExport = activeFnEntries.filter(([fn, kind]) => functionHasNoEvidence(fn, kind, changeDetails, functionDiffs, functionMeta)).length;
    if (noEvExport > 0) L.push(`  - 이 중 파일영향(직접 변경 증거 없음, 파일 단위 보수 포함): ${noEvExport}개 → 실 수정 함수 약 ${activeFnEntries.length - noEvExport}개`);
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
      // 미매칭(측정 자체 없음)은 '충족'이 아니라 증거 부재 — 리포트에서도 감추지 않는다.
      if (s.unmatched) L.push(`- ⚠ 미매칭(커버리지 데이터 없음): ${s.unmatched}개${s.unmatched_safety ? ` (ASIL C/D ${s.unmatched_safety}개 미검증)` : ''}`);
      if (s.unmeasured_safety) L.push(`- ⚠ ASIL C/D 미측정: ${s.unmeasured_safety}개 (타깃 메트릭 데이터 없음)`);
      if (s.unknown_asil) L.push(`- ⚠ ASIL 미상: ${s.unknown_asil}개 (최저 기준 위장 평가 금지 — 수동 확인)`);
    }
    if (regressionSet?.summary) {
      L.push('', '## 회귀시험 선정 (재실행 대상)');
      L.push(`- SUTS 재실행 TC: ${regressionSet.summary.suts_tc_count ?? 0} / SITS 영향 체인: ${regressionSet.summary.sits_chain_count ?? 0}`);
    }
    L.push('', '## 변경 함수');
    for (const [fn, kind] of activeFnEntries) {
      const noEvMark = functionHasNoEvidence(fn, kind, changeDetails, functionDiffs, functionMeta) ? ' (파일영향 — 직접 변경 증거 없음)' : '';
      L.push(`- \`${fn}\` : ${CHANGE_TYPE_KO[kind] || kind}${noEvMark}`);
    }
    if (guide?.details?.length) {
      L.push('', '## 함수별 영향 가이드 (직접 변경 + 간접 영향)');
      L.push('| 함수 | 변경 | ASIL | 영향 | 요구사항 | STS TC | SUTS TC | SITS TC |');
      L.push('|------|------|------|------|----------|--------|---------|---------|');
      for (const d of guide.details) {
        const chLabel = d.changed ? (CHANGE_TYPE_KO[d.changeType] || d.changeType) : '영향(간접)';
        L.push(`| \`${d.function}\` | ${chLabel} | ${d.asil || '미상'} | ${d.hop} | ${(d.requirements || []).join(' ') || '-'} | ${(d.stsTestCases || []).length} | ${(d.sutsTestCases || []).length} | ${(d.sitsTestCases || []).length} |`);
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
  }, [activeFnEntries, activeChangedFiles, changeSummary, activeImpactGroups, asilInfo, coverageGap, regressionSet, guide, aiGuide, demoMode, changeDetails, functionDiffs, toast]);

  // 선택 함수의 변경을 Gemini로 설명(선언 원문 before/after 포함). LLM 미설정이면 ok=false로 폴백.
  const fetchExplanation = useCallback(async (d) => {
    if (!d) return;
    const cd = changeDetails[String(d.function).toLowerCase()] || {};
    const fd = functionDiffs[String(d.function).toLowerCase()] || '';
    setExplain({ fn: d.function, text: '', loading: true, error: '' });
    try {
      const res = await post('/api/impact/explain-change', {
        function: d.function,
        change_type: d.changeType || '',
        before: cd.before || '',
        after: cd.after || '',
        function_diff: fd,  // 본문 diff 원문 — BODY 함수도 실제 코드 근거로 AI 설명
        asil: d.asil || '',
        // function_meta 키는 guideFns의 fn과 항상 같은 케이스(정상 경로=소문자, source_root 미해결
        // edge=원본 케이스로 상호 일관 — impact_orchestrator.py:1404 sorted(_changed_set|_impacted_all)).
        // 그래서 d.function 그대로 조회하고 소문자화하지 않는다(edge 경로에선 소문자화가 조회 실패
        // 유발). 원본 케이스 표시명이 필요하면 functionMeta[fn].display_name 사용.
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
  }, [changeDetails, functionDiffs, functionMeta]);

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

  // Track 2/문서별 상세: AI 요약 ↔ 함수별 상세 ↔ 문서별 상세 탭. aiGuide 없으면 함수 탭으로 강등,
  // doc 탭은 guide 필요(없으면 기존 체인으로 강등 — 기존 동작/테스트 회귀 최소화).
  const effTab = (activeTab === 'ai' && aiGuide) ? 'ai'
    : (activeTab === 'doc' && guide) ? 'doc'
      : (guide ? 'fn' : 'ai');
  // AI 요약의 함수명 → 기존 상세 모달. guide.details의 정규(canonical) 이름으로 해석해야
  // 모달 IIFE의 exact-match find가 성립한다(미해석 이름이면 무시 = no-op, 크래시 방지).
  const resolveFnName = (name) => {
    if (!name) return null;
    return guideFnByLc.get(String(name).toLowerCase()) || null;
  };
  const openFnDetail = (name) => {
    const canonical = resolveFnName(name);
    if (canonical) setSelectedFn(canonical);
  };
  // AI 요약 함수명 렌더 — guide.details에 있으면 클릭 가능한 버튼, 없으면 일반 텍스트.
  const renderFnRef = (name, extraStyle) => {
    const canonical = resolveFnName(name);
    if (!canonical) return <span style={extraStyle}>{name}</span>;
    return (
      <button
        type="button"
        onClick={() => openFnDetail(name)}
        title="함수별 상세(시그니처·본문 diff·문서 영향·AI 설명) 열기"
        style={{ background: 'none', border: 'none', padding: 0, color: 'var(--accent)', cursor: 'pointer', textDecoration: 'underline', font: 'inherit', ...extraStyle }}
      >{name}</button>
    );
  };
  // 탭 바 — 렌더되는 패널(한 번에 하나)의 헤더에 삽입 → 통합 패널처럼 보인다.
  const tabBar = (
    <div className="panel-header" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
      {aiGuide && (
        <button type="button" onClick={() => setActiveTab('ai')}
          style={{ background: 'none', border: 'none', padding: '4px 10px', cursor: 'pointer', font: 'inherit',
            fontWeight: effTab === 'ai' ? 700 : 400, color: effTab === 'ai' ? 'var(--accent)' : 'var(--text-muted)',
            borderBottom: effTab === 'ai' ? '2px solid var(--accent)' : '2px solid transparent' }}>AI 요약</button>
      )}
      {guide && (
        <button type="button" onClick={() => setActiveTab('fn')}
          style={{ background: 'none', border: 'none', padding: '4px 10px', cursor: 'pointer', font: 'inherit',
            fontWeight: effTab === 'fn' ? 700 : 400, color: effTab === 'fn' ? 'var(--accent)' : 'var(--text-muted)',
            borderBottom: effTab === 'fn' ? '2px solid var(--accent)' : '2px solid transparent' }}>함수별 상세 ({guide.details.length})</button>
      )}
      {guide && (
        <button type="button" onClick={() => setActiveTab('doc')}
          title="문서별(UDS/STS/SUTS/SITS/SDS)로 어떤 함수가 어떤 편집을 요구하는지 — 함수별 상세를 문서 관점으로 전치"
          style={{ background: 'none', border: 'none', padding: '4px 10px', cursor: 'pointer', font: 'inherit',
            fontWeight: effTab === 'doc' ? 700 : 400, color: effTab === 'doc' ? 'var(--accent)' : 'var(--text-muted)',
            borderBottom: effTab === 'doc' ? '2px solid var(--accent)' : '2px solid transparent' }}>문서별 상세 ({DOC_KEYS.filter(k => docCounts[k] > 0).length})</button>
      )}
      <span style={{ flex: 1 }} />
      {effTab === 'ai' && aiGuide && (
        <span className="text-muted text-sm">{aiGuide.ai_enriched ? 'AI-enriched' : 'deterministic'}</span>
      )}
      {effTab === 'fn' && guide && (
        <span className="text-muted text-sm" title="변경(직접) 함수와 그 호출 관계로 영향받는 간접(1/2-hop) 함수를 함께 표시합니다. '영향' 필터로 hop을 좁힐 수 있습니다.">직접 변경 + 간접 영향(1/2-hop) 포함</span>
      )}
    </div>
  );

  return (
    <div>
      {/* 백엔드 경고 표면화 — 과소보고/cloudium degrade/revision 불일치/ASIL escalation 등.
          0 영향을 '영향 없음'으로 오인하지 않도록 안전 신호를 의사결정 화면에 노출. */}
      {impactWarnings.length > 0 && (
        <div className="panel" style={{ marginBottom: 12, borderLeft: '3px solid var(--color-warning)' }}>
          <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>⚠️ 분석 경고 ({impactWarnings.length})</div>
          {impactWarnings.map((w, i) => {
            const danger = /under-reported|empty|escalation|미상|과소|MC\/DC|unavailable|회귀|재실행/i.test(String(w));
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
      {covView && (
        <div className="panel" style={{ marginBottom: 12,
          borderLeft: `3px solid ${(covView.below || covView.regressed) ? 'var(--color-danger)' : 'var(--color-success)'}` }}>
          <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>
            🎯 커버리지 (ASIL 타깃 대비)
          </div>
          <div className="stats-row">
            <div className="stat-card">
              <div className="text-muted text-sm">평가된 영향 함수</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{covView.evaluated}</div>
            </div>
            <div className="stat-card">
              <div className="text-muted text-sm">목표 미달</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: covView.below ? 'var(--color-danger)' : undefined }}>
                {covView.below}
              </div>
            </div>
            <div className="stat-card" title="매칭됐으나 해당 ASIL 타깃 메트릭(예: MC/DC) 데이터가 리포트에 없는 함수 — 증거 부재(시험 실패 아님)">
              <div className="text-muted text-sm">미측정</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: covView.unmeasured ? 'var(--color-warning)' : undefined }}>
                {covView.unmeasured}
              </div>
            </div>
            <div className="stat-card"
              title={covView.deltaUntrusted
                ? `Δ(회귀) 신뢰 불가: ${covView.deltaUntrustReason}. 수치를 '회귀 없음/있음'으로 읽지 마십시오.`
                : '직전 분석 스냅샷 대비 커버리지가 하락한 함수 수.'}>
              <div className="text-muted text-sm">직전 대비 회귀</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: (!covView.deltaUntrusted && covView.regressed) ? 'var(--color-danger)' : undefined }}>
                {covView.deltaUntrusted ? '—' : covView.regressed}
              </div>
              {covView.deltaUntrusted && (
                <div style={{ fontSize: 9, color: 'var(--color-warning)', marginTop: 2, lineHeight: 1.3, overflowWrap: 'anywhere' }}>⚠ {covView.deltaUntrustReason}</div>
              )}
            </div>
            {/* 미매칭 = VectorCAST 커버리지 데이터에 함수가 아예 없음(증거 부재). 백엔드는 이를
                'unmatched'로 산출하며 "미검증을 안전 통과로 위장 금지"를 명시 — UI가 감추면 그 위장이
                발생하므로 반드시 노출한다. ASIL C/D 미검증은 danger. */}
            <div className="stat-card" title="영향 함수인데 VectorCAST 커버리지 데이터에 매칭되지 않음(측정 자체 없음) — '충족'이 아니라 증거 부재입니다. 전체 영향 함수 기준(파일영향 필터 미적용).">
              <div className="text-muted text-sm">미매칭(측정 없음)</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: covView.unmatchedSafety ? 'var(--color-danger)' : (covView.unmatched ? 'var(--color-warning)' : undefined) }}>
                {covView.unmatched}
              </div>
              {covView.unmatchedSafety > 0 && (
                <div style={{ fontSize: 9, color: 'var(--color-danger)', marginTop: 2 }}>⚠ ASIL C/D {covView.unmatchedSafety}개 미검증</div>
              )}
            </div>
          </div>
          {(covView.unmeasuredSafety > 0 || covView.unknownAsil > 0) && (
            <div className="text-sm" style={{ marginTop: 4, color: 'var(--color-warning)' }}>
              {covView.unmeasuredSafety > 0 && <span>⚠ ASIL C/D 미측정 {covView.unmeasuredSafety}개(타깃 메트릭 데이터 없음) </span>}
              {covView.unknownAsil > 0 && <span>⚠ ASIL 미상 {covView.unknownAsil}개 — 최저 기준(구문)으로 위장 평가하지 않음(수동 확인 필요)</span>}
            </div>
          )}
          {covView.hidden > 0 && (
            <div className="text-muted text-sm" style={{ marginTop: 4 }}
              title="파일영향(무변경) 함수는 이 변경이 유발한 커버리지 갭이 아니므로 기본 제외 — 위 토글로 포함하면 전체가 반영됩니다.">
              ⓘ 실변경 함수 기준 — 파일영향(무변경) {covView.hidden}개 제외(이 변경이 유발한 갭이 아님)
            </div>
          )}
          {!covView.hadBaseline && (
            <div className="text-muted text-sm" style={{ marginTop: 4 }}>직전 스냅샷 없음 — 이번 실행을 기준으로 저장(다음 분석부터 Δ 표시).</div>
          )}
          {covView.collisionWorstCopy > 0 && (
            <div className="text-muted text-sm" style={{ marginTop: 4 }}
              title="이름충돌(동명 다른 함수)은 여러 copy 중 최악 copy 커버리지로 표시합니다 — 변경 copy를 이름만으로 특정할 수 없어, 어느 copy에 gap이 있어도 재검증 대상으로 남깁니다(전역 max 병합의 gap 은폐 방지, 안전측).">
              ⓘ 이름충돌 {covView.collisionWorstCopy}개 함수는 여러 copy 중 <b>최악(worst-copy)</b> 커버리지로 표시(gap 은폐 방지)
            </div>
          )}
        </div>
      )}
      {/* 회귀시험 선정 — 영향 함수에 매핑된 기존 SUTS TC / SITS call-chain(재실행 대상 증거, ISO 26262).
          백엔드 SITS 콜체인이 0이어도(빌더 미실행) 프론트 SwUFn 파생 SITS(guideSitsMap)가 있으면 표시. */}
      {regressionSet?.summary && ((regressionSet.summary.suts_tc_count || 0) > 0 || (regressionSet.summary.sits_chain_count || 0) > 0 || Object.keys(guideSitsMap).length > 0) && (
        <div className="panel" style={{ marginBottom: 12, borderLeft: '3px solid var(--color-info)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <span className="text-sm" style={{ fontWeight: 700 }}>🔁 회귀시험 선정 (재실행 대상)</span>
            <span style={{ flex: 1 }} />
            {(Object.keys(regressionSet.suts || {}).length > 12 || Object.keys(regressionSet.sits || {}).length > 10 || Object.keys(guideSitsMap).length > 12
              // reviewer W1: 함수-개수뿐 아니라 함수당 TC/체인-개수 절단(6/4/6 초과)도 버튼 노출 조건에 포함
              // — 소수 함수에 TC가 몰려 "+N" 힌트만 뜨고 해제 버튼이 없는 dead-end 방지.
              || Object.values(regressionSet.suts || {}).some(v => (v || []).length > 6)
              || Object.values(regressionSet.sits || {}).some(v => (v || []).length > 4)
              || Object.values(guideSitsMap).some(v => (v || []).length > 6)) && (
              <button className="btn-sm" style={{ fontSize: 10, padding: '1px 6px' }}
                onClick={() => setRegShowAll(v => !v)}
                title="함수별 재실행 TC/체인 목록의 절단을 해제해 전체를 봅니다(스크롤).">
                {regShowAll ? '접기 ⌃' : '전체 보기 ⌄'}
              </button>
            )}
          </div>
          <div className="stats-row">
            <div className="stat-card">
              <div className="text-muted text-sm">영향 함수</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{regressionSet.summary.impacted_function_count ?? 0}</div>
            </div>
            <div className="stat-card" title="재실행 대상 = 영향 함수 중 기존 SUTS 단위 TC('2.SW Unit Test Spec' 시트의 TC 블록)를 보유한 함수. 함수별 상세의 'SUTS TC' 컬럼은 추적성('3.SW Test Spec') 시트 기준이라 더 넓을 수 있습니다(다른 시트·기준).">
              <div className="text-muted text-sm">SUTS 재실행 TC</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{regressionSet.summary.suts_tc_count ?? 0}</div>
            </div>
            <div className="stat-card" title="백엔드 통합 콜체인(SITS VectorCAST 중간파일 기반) 수. cloudium 읽기전용 등으로 SITS 빌더 산출물이 없으면 0 — 이 경우 함수별 SwUFn 브리지(아래) 참조.">
              <div className="text-muted text-sm">SITS 영향 체인</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{regressionSet.summary.sits_chain_count ?? 0}</div>
              {Object.keys(guideSitsMap).length > 0 && (
                <div className="text-muted" style={{ fontSize: 9, marginTop: 2, color: 'var(--color-info)' }}>+ SwUFn TC {Object.keys(guideSitsMap).length}함수</div>
              )}
            </div>
          </div>
          {Object.keys(regressionSet.suts || {}).length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>SUTS 재실행 TC (함수별)</div>
              <div style={{ maxHeight: regShowAll ? 360 : 120, overflow: 'auto' }}>
                {Object.entries(regressionSet.suts).slice(0, regShowAll ? undefined : 12).map(([fn, tcs]) => (
                  <div key={fn} style={{ fontSize: 10, padding: '2px 0' }}>
                    <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{fn}</span>
                    <span className="text-muted"> — {(tcs || []).length} TC </span>
                    {(tcs || []).slice(0, regShowAll ? undefined : 6).map((tc, i) => (
                      <span key={i} className="pill pill-neutral" style={{ fontSize: 8, margin: 1 }}>{tc}</span>
                    ))}
                    {!regShowAll && (tcs || []).length > 6 && <span className="text-muted" style={{ fontSize: 8 }}> +{(tcs || []).length - 6}</span>}
                  </div>
                ))}
                {!regShowAll && Object.keys(regressionSet.suts).length > 12 && (
                  <div className="text-muted" style={{ fontSize: 9 }}>+{Object.keys(regressionSet.suts).length - 12}개 함수 더 · 상단 &lsquo;전체 보기&rsquo;</div>
                )}
              </div>
            </div>
          )}
          {Object.keys(regressionSet.sits || {}).length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>SITS 영향 call-chain (함수별)</div>
              <div style={{ maxHeight: regShowAll ? 360 : 140, overflow: 'auto' }}>
                {Object.entries(regressionSet.sits).slice(0, regShowAll ? undefined : 10).map(([fn, chains]) => (
                  <div key={fn} style={{ fontSize: 10, padding: '2px 0' }}>
                    <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{fn}</span>
                    <span className="text-muted"> — {(chains || []).length} 체인</span>
                    <div style={{ marginLeft: 10 }}>
                      {(chains || []).slice(0, regShowAll ? undefined : 4).map((c, i) => (
                        <div key={i} title={c} style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: 'monospace', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>↳ {c}</div>
                      ))}
                      {!regShowAll && (chains || []).length > 4 && <div className="text-muted" style={{ fontSize: 9 }}>+{(chains || []).length - 4}개 더</div>}
                    </div>
                  </div>
                ))}
                {!regShowAll && Object.keys(regressionSet.sits).length > 10 && (
                  <div className="text-muted" style={{ fontSize: 9 }}>+{Object.keys(regressionSet.sits).length - 10}개 함수 더 · 상단 &lsquo;전체 보기&rsquo;</div>
                )}
              </div>
            </div>
          )}
          {/* 프론트 SwUFn 브리지 파생 SITS TC — 백엔드 통합 콜체인이 0(빌더 미실행)이어도 함수별 상세가
              testcase의 SwUFn을 SUTS unit으로 풀어 SITS를 직접 조인한다. 함수 테이블 'SITS TC'와 동일 소스. */}
          {Object.keys(guideSitsMap).length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>SITS 재실행 TC (함수별 · SwUFn 브리지)</div>
              <div style={{ maxHeight: regShowAll ? 360 : 120, overflow: 'auto' }}>
                {Object.entries(guideSitsMap).slice(0, regShowAll ? undefined : 12).map(([fn, tcs]) => (
                  <div key={fn} style={{ fontSize: 10, padding: '2px 0' }}>
                    <span style={{ fontFamily: 'monospace', fontWeight: 600 }}>{fn}</span>
                    <span className="text-muted"> — {(tcs || []).length} TC </span>
                    {(tcs || []).slice(0, regShowAll ? undefined : 6).map((tc, i) => (
                      <span key={i} className="pill pill-neutral" style={{ fontSize: 8, margin: 1 }}>{tc}</span>
                    ))}
                    {!regShowAll && (tcs || []).length > 6 && <span className="text-muted" style={{ fontSize: 8 }}> +{(tcs || []).length - 6}</span>}
                  </div>
                ))}
                {!regShowAll && Object.keys(guideSitsMap).length > 12 && (
                  <div className="text-muted" style={{ fontSize: 9 }}>+{Object.keys(guideSitsMap).length - 12}개 함수 더 · 상단 &lsquo;전체 보기&rsquo;</div>
                )}
              </div>
            </div>
          )}
          {/* silent-0 금지: 백엔드 통합 콜체인 0의 사유(SITS 빌더 미실행 등)를 표면화. */}
          {(regressionSet.summary.sits_chain_count || 0) === 0 && (() => {
            const r = impactWarnings.find(w => /SITS/i.test(w) && /(미생성|미실행|미집계|중간파일|체인)/.test(w));
            return (
              <div className="text-muted" style={{ fontSize: 9, marginTop: 6, color: 'var(--color-warning)' }}>
                ⓘ SITS 통합 콜체인 0: {r || '백엔드 SITS VectorCAST 중간파일 미생성(빌더 미실행)'}{Object.keys(guideSitsMap).length > 0 ? ' — 함수별 SwUFn 브리지 TC로 보완(위)' : ''}
              </div>
            );
          })()}
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
            {hasEvidenceSplit && (
              <button className="btn-sm" onClick={() => setShowFileImpact(v => !v)}
                title="파일영향 = 직접 변경 증거(본문 diff·선언 변경) 없이 파일 단위 보수 분류로 포함된 함수(실제 수정 아님). 모든 집계(변경 함수·직접 영향·문서별·커버리지)에서 제외/포함을 함께 전환합니다.">
                {showFileImpact ? `파일영향 ${noEvidenceCount}개 숨기기` : `파일영향 ${noEvidenceCount}개 보기`}
              </button>
            )}
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
            <div className="stat-value">{visibleFnEntries.length}</div>
            <div className="stat-label">
              변경 함수
              {isConservativeCount && <span className="text-muted" style={{ fontSize: 9, marginLeft: 3 }}>(보수 추정)</span>}
              {isLineClassified && <span className="pill pill-success" style={{ fontSize: 8, marginLeft: 3 }}>정밀</span>}
              {hasEvidenceSplit && (
                <span className="text-muted" style={{ fontSize: 9, marginLeft: 3 }}
                  title="파일영향 = 직접 변경 증거 없이 파일 단위 보수 분류로 포함된 함수(실제 수정 아님). 아래 '변경 상세'에서 표시/숨김 전환.">
                  {showFileImpact ? `(파일영향 ${noEvidenceCount} 포함)` : `+${noEvidenceCount} 파일영향`}
                </span>
              )}
            </div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{directVisibleCount}</div>
            <div className="stat-label">
              직접 영향
              {hideFileImpact && directHiddenCount > 0 && (
                <span className="text-muted" style={{ fontSize: 9, marginLeft: 3 }}
                  title="직접 영향 = 실제 변경된 함수. 파일영향(무변경, 파일 단위 보수 포함)은 제외 — 토글로 포함.">
                  +{directHiddenCount} 파일영향
                </span>
              )}
            </div>
          </div>
          <div className="stat-card"
            title={traversal?.truncated
              ? `콜그래프 탐색이 상한(${traversal.max_impacted_functions})에서 중단돼 ${traversal.truncated_at_hop}-hop까지만 계산했습니다. 그 이상 hop은 '영향 없음'이 아니라 '미계산'입니다.`
              : undefined}>
            <div className="stat-value">{(activeImpactGroups.indirect_1hop || []).length + (activeImpactGroups.indirect_2hop || []).length}</div>
            <div className="stat-label">
              간접 영향
              {!demoMode && traversal?.truncated && (
                <span style={{ fontSize: 9, marginLeft: 3, color: 'var(--color-warning)' }}>
                  ⚠ {traversal.truncated_at_hop}-hop까지만 계산
                </span>
              )}
            </div>
          </div>
          {/* reviewer Finding#2: 함수명 기준으로 실제 조인되는 회귀 지표를 헤드라인으로 표면화.
              STS 요구기반 조인(아래 'STS 요구 TC')은 문서 요구 유형이 다르면 구조적으로 0이 될 수
              있어(주 신호로 오해 소지) 함수 단위 회귀 SUTS/SITS를 함께 앞세운다. */}
          {regressionSet?.summary && (
            <>
              <div className="stat-card" style={{ borderLeft: '3px solid var(--color-success)' }}
                title="변경/영향 함수에 직접 매핑된 기존 SUTS 단위시험 TC(함수명 기준 = 재실행 대상). STS 요구기반 조인과 달리 함수 단위로 정확 매칭.">
                <div className="stat-value">{regressionSet.summary.suts_tc_count ?? 0}</div>
                <div className="stat-label">회귀 SUTS TC</div>
              </div>
              <div className="stat-card" style={{ borderLeft: '3px solid var(--color-success)' }}
                title="변경/영향 함수가 진입점인 SITS 통합시험 콜체인(재확인 대상). 0이면 SITS VectorCAST 중간파일 미생성일 수 있음.">
                <div className="stat-value">{regressionSet.summary.sits_chain_count ?? 0}</div>
                <div className="stat-label">회귀 SITS 체인</div>
              </div>
            </>
          )}
          {guide && (
            <>
              <div className="stat-card" style={{ borderLeft: '3px solid var(--color-warning)' }}>
                <div className="stat-value">{guide.summary.impactedReqs}</div>
                <div className="stat-label">영향 요구사항</div>
              </div>
              <div className="stat-card" style={{ borderLeft: '3px solid var(--color-info)' }}
                title={guide.summary.stsTcReason ? `STS 요구 TC 0 사유: ${guide.summary.stsTcReason} (함수 단위 회귀는 회귀 SUTS/SITS 참조)` : 'STS 요구 기반 시험 TC — SDS(SwRS 허브) 브리지로 함수→SW요구→STS TC를 조인. 0이면 사유 표기.'}>
                <div className="stat-value">{guide.summary.impactedStsTCs}</div>
                <div className="stat-label">STS 요구 TC</div>
                {guide.summary.impactedStsTCs === 0 && guide.summary.stsTcReason && (
                  <div className="text-muted" style={{ fontSize: 9, marginTop: 2, color: 'var(--color-warning)' }}>⚠ {guide.summary.stsTcReason}</div>
                )}
              </div>
              <div className="stat-card" style={{ borderLeft: '3px solid var(--color-info)' }}
                title={guide.summary.sitsTcReason ? `SITS 영향 TC 0 사유: ${guide.summary.sitsTcReason} (통합 콜체인은 위 회귀 SITS 체인 참조)` : 'SITS 통합시험 TC — SwRS 허브(함수→SW요구) 브리지 ∪ SwUFn 단위 브리지(testcase의 SwUFn→SUTS unit)로 조인. 통합 콜체인은 회귀 SITS 체인 참조.'}>
                <div className="stat-value">{guide.summary.impactedSitsTCs ?? 0}</div>
                <div className="stat-label">SITS 영향 TC</div>
                {(guide.summary.impactedSitsTCs ?? 0) === 0 && guide.summary.sitsTcReason && (
                  <div className="text-muted" style={{ fontSize: 9, marginTop: 2, color: 'var(--color-warning)' }}>⚠ {guide.summary.sitsTcReason}</div>
                )}
              </div>
            </>
          )}
        </div>

        {/* Document impact status */}
        {(() => {
          // 카운트는 문서별 상세 탭과 동일한 단일 출처(docCounts = 권위 actions[doc].functions, 파일영향
          // 제외)로 계산 — 요약 카드 클릭→탭 이동 시 숫자 불일치 방지(reviewer W6). 과거 docStats(요구/TC
          // 조인 성사 여부 기반)는 join-underreport라 탭 멤버십과 어긋났다. 카드 count = 탭 함수행 수.
          const docEntries = [
            { key: 'uds', label: 'UDS', count: docCounts.uds, status: actions.uds?.status },
            { key: 'sts', label: 'STS', count: docCounts.sts, status: actions.sts?.status, extra: guide ? `${guide.summary.impactedStsTCs} TC` : '' },
            { key: 'suts', label: 'SUTS', count: docCounts.suts, status: actions.suts?.status },
            { key: 'sits', label: 'SITS', count: docCounts.sits, status: actions.sits?.status, extra: guide ? `${guide.summary.impactedSitsTCs ?? 0} TC` : '' },
            { key: 'sds', label: 'SDS', count: docCounts.sds, status: actions.sds?.status },
          ];
          return (
            <div style={{ marginTop: 10 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 6 }}>
                문서별 영향
                {hideFileImpact && noEvidenceCount > 0 && <span className="text-muted" style={{ fontSize: 10, fontWeight: 400, marginLeft: 4 }}>· 실변경 함수 기준(파일영향 제외)</span>}
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {docEntries.map(d => {
                  const hasImpact = d.count > 0;
                  const st = d.status ? (DOC_STATUS[d.status] || { tone: 'neutral', label: d.status })
                    : (hasImpact ? { tone: 'warning', label: '검토 필요' } : { tone: 'neutral', label: '영향 없음' });
                  return (
                    <div key={d.key}
                      role={guide ? 'button' : undefined}
                      tabIndex={guide ? 0 : undefined}
                      aria-label={guide ? `${d.label} 문서별 상세 보기` : undefined}
                      onClick={guide ? () => { setActiveTab('doc'); setSelectedDoc(d.key); } : undefined}
                      onKeyDown={guide ? (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setActiveTab('doc'); setSelectedDoc(d.key); } } : undefined}
                      title={guide ? '문서별 상세 탭에서 이 문서의 함수·편집 액션 보기' : undefined}
                      style={{ padding: '6px 10px', borderRadius: 6, border: `1px solid ${hasImpact ? 'var(--color-warning)' : 'var(--border)'}`, background: 'var(--bg)', minWidth: 100, cursor: guide ? 'pointer' : 'default' }}>
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
            <span className="panel-title">
              변경 상세 ({visibleFnEntries.length}개 함수)
              {hideFileImpact && <span className="text-muted" style={{ fontSize: 10, fontWeight: 400, marginLeft: 4 }}>{`· 파일영향 ${noEvidenceCount}개 숨김`}</span>}
            </span>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
              {visibleChangeSummary.NEW > 0 && <span className="pill pill-success" style={{ fontSize: 10 }}>🟢 신규 {visibleChangeSummary.NEW}</span>}
              {visibleChangeSummary.DELETE > 0 && <span className="pill pill-danger" style={{ fontSize: 10 }}>🔴 삭제 {visibleChangeSummary.DELETE}</span>}
              {visibleChangeSummary.SIGNATURE > 0 && <span className="pill pill-warning" style={{ fontSize: 10 }}>🟠 시그니처 {visibleChangeSummary.SIGNATURE}</span>}
              {visibleChangeSummary.BODY > 0 && <span className="pill pill-info" style={{ fontSize: 10 }}>🔵 본문 {visibleChangeSummary.BODY}</span>}
              {visibleChangeSummary.HEADER > 0 && <span className="pill" style={{ fontSize: 10 }}>헤더 {visibleChangeSummary.HEADER}</span>}
              {visibleChangeSummary.VARIABLE > 0 && <span className="pill" style={{ fontSize: 10 }}>변수 {visibleChangeSummary.VARIABLE}</span>}
              {hasEvidenceSplit && (
                <button className="btn-sm" onClick={() => setShowFileImpact(v => !v)}
                  title="파일영향 = 직접 변경 증거(본문 diff·선언 변경)가 없이 파일 단위 보수 분류로 포함된 함수. 실제 수정이 아닐 수 있어 기본 숨김입니다.">
                  {showFileImpact ? `파일영향 ${noEvidenceCount}개 숨기기` : `파일영향 ${noEvidenceCount}개 보기`}
                </button>
              )}
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
                {[...visibleFnEntries]
                  .sort((a, b) => (CHANGE_ORDER[b[1]] || 0) - (CHANGE_ORDER[a[1]] || 0))
                  .map(([fn, kind]) => (
                    <tr key={fn} style={{ borderBottom: '1px solid var(--border-subtle, var(--border))' }}>
                      <td style={{ padding: '6px 8px', fontFamily: 'var(--font-mono, monospace)', wordBreak: 'break-all' }}>{functionMeta[fn]?.display_name || fn}</td>
                      <td style={{ padding: '6px 8px' }}>
                        <StatusBadge tone={CHANGE_TYPE_TONE[kind] || 'neutral'}>{CHANGE_TYPE_KO[kind] || kind}</StatusBadge>
                        {!demoMode && functionHasNoEvidence(fn, kind, changeDetails, functionDiffs, functionMeta) && (
                          <span className="pill pill-neutral" style={{ fontSize: 8, marginLeft: 3 }} title="직접 변경 증거 없음(function_diff·change_details 모두 없음) — 파일 단위 영향(fatten, 보수적 포함). 클릭 시 본문 원문 없음이 정상.">파일영향</span>
                        )}
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

      {/* AI 요약 + 함수별 상세 — 탭 통합 (Track 2). 한 번에 한 탭만 렌더돼 통합 패널처럼 보인다. */}
      {effTab === 'ai' && aiGuide && (
        <div className="panel" style={{ marginBottom: 12 }}>
          {tabBar}

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
                {aiGuide.risk.affected_safety_functions.map((sf, i) => {
                  const canonical = resolveFnName(sf);
                  return canonical ? (
                    <button key={i} type="button" onClick={() => setSelectedFn(canonical)}
                      className="pill pill-danger" title="함수별 상세 열기"
                      style={{ fontSize: 9, cursor: 'pointer', border: 'none' }}>{sf}</button>
                  ) : (
                    <span key={i} className="pill pill-danger" style={{ fontSize: 9 }}>{sf}</span>
                  );
                })}
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
                      {items.slice(0, 3).map((imp, i) => {
                        const m = String(imp).match(/^\[([^\]]+)\]/);
                        const canonical = m ? resolveFnName(m[1]) : null;
                        return (
                          <div key={i} style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 2 }}>
                            {canonical ? (<>
                              <button type="button" onClick={() => setSelectedFn(canonical)} title="함수별 상세 열기"
                                style={{ background: 'none', border: 'none', padding: 0, color: 'var(--accent)', cursor: 'pointer', textDecoration: 'underline', font: 'inherit' }}>[{m[1]}]</button>
                              {String(imp).slice(m[0].length)}
                            </>) : imp}
                          </div>
                        );
                      })}
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
                      <td style={{ padding: '3px 6px', fontFamily: 'monospace', fontWeight: 600 }}>{renderFnRef(rec.function)}</td>
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

      {/* 함수별 상세 탭 (Track 2) — AI 요약과 탭 통합. 패널은 effTab==='fn'일 때만,
          상세 모달은 guide만 있으면(탭 무관) 렌더돼 AI 요약에서 함수 클릭 시에도 뜬다. */}
      {guide && (
        <>
        {effTab === 'fn' && (
        <div className="panel">
          {tabBar}

          {/* 추출 실패 표면화 — 매핑이 실제보다 적게 보일 수 있음을 지속 노출(토스트는 사라짐) */}
          {guide.fetchFailures?.length > 0 && (
            <div className="text-sm" style={{ margin: '4px 0 8px', padding: '6px 10px', borderLeft: '3px solid var(--color-warning)', background: 'var(--bg)', borderRadius: 4 }}>
              ⚠️ {guide.fetchFailures.map(f => f.doc).join(', ')} 매핑 조회 실패 — 아래 요구사항/STS/SUTS/SITS TC 매핑(및 SDS SwRS 허브 브리지)이 실제보다 적게 보일 수 있습니다('매핑 없음' ≠ 확정 부재). 문서 경로/권한을 확인 후 다시 생성하세요.
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
            {hasEvidenceSplit && (
              <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--text-muted)', cursor: 'pointer' }}
                title="직접 변경 증거 없이 파일 단위 보수 분류로 포함된 함수(파일영향)를 목록에 포함합니다.">
                <input type="checkbox" checked={showFileImpact} onChange={e => setShowFileImpact(e.target.checked)} />
                {`파일영향 포함 (${noEvidenceCount})`}
              </label>
            )}
            {formatOnlyCount > 0 && (
              <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--text-muted)', cursor: 'pointer' }}
                title="본문 diff가 코드 이동·공백·포맷만이고 의미(로직) 변경이 없는 함수를 목록에서 숨깁니다.">
                <input type="checkbox" checked={hideFormatOnly} onChange={e => setHideFormatOnly(e.target.checked)} />
                {`포맷/이동만 숨기기 (${formatOnlyCount})`}
              </label>
            )}
            <span className="text-muted text-sm">{filteredGuide.length}/{guide.details.length}건</span>
          </div>

          <table className="impact-table" style={{ fontSize: 11 }}>
            <thead>
              <tr>
                <th style={{ width: 150 }}>함수</th>
                <th style={{ width: 120 }}>변경</th>
                <th style={{ width: 50 }}>ASIL</th>
                <th style={{ width: 50 }}>영향</th>
                <th style={{ width: 96 }} title="ASIL 타깃 구조 커버리지(D=MC/DC, C/B=분기, A/QM=구문) 대비. Δ=직전 대비 변화">커버리지</th>
                <th>요구사항</th>
                <th>STS TC</th>
                <th title="전체 영향 함수 기준 보유 SUTS 시험(추적성 '3.SW Test Spec' 시트, unit 컬럼). 변경 함수 '재실행 대상'(기존 TC 블록 보유)은 위 회귀 패널 참조 — 다른 시트·기준이라 수치가 더 넓을 수 있음.">SUTS TC</th>
                <th title="전체 영향 함수 기준 보유 SITS 시험(SwUFn 브리지: testcase의 SwUFn→SUTS unit). SITS는 통합시험이라 데이터가 희소할 수 있음(요구 참조가 시스템 네임스페이스면 함수 매칭 없음).">SITS TC</th>
                <th style={{ width: 50 }}></th>
              </tr>
            </thead>
            <tbody>
              {filteredGuide.map((d, i) => (
                <tr key={i} style={{ background: d.hop === 'direct' ? 'var(--bg)' : undefined }}>
                  <td style={{ fontFamily: 'monospace', fontSize: 10, fontWeight: 600 }}>{d.function}</td>
                  <td>{renderChangeSummaryCell(d, changeDetails, functionDiffs, functionMeta)}</td>
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
                  <td style={{ fontSize: 10 }}>
                    {(d.sitsTestCases || []).length > 0
                      ? <span className="pill pill-info" style={{ fontSize: 9 }}>{d.sitsTestCases.length} TC</span>
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
        </div>
        )}

        {/* 문서별 상세 탭 — 좌우 마스터-디테일. actions[doc] 멤버십 × buildDocumentActions 편집 액션(전치).
            함수명 클릭은 공유 상세 모달(아래)을 연다. */}
        {effTab === 'doc' && (
        <div className="panel">
          {tabBar}
          <div className="text-muted text-sm" style={{ margin: '2px 0 8px' }}>
            문서별로 어떤 함수가 어떤 편집을 요구하는지 — 좌측 문서 선택, 우측 상세(함수명 클릭 시 함수별 상세 모달).
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(130px, 190px) 1fr', gap: 12, alignItems: 'start' }}>
            {/* 좌: 문서 마스터 목록 */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {DOC_KEYS.map((k) => {
                const meta = DOC_META[k];
                const cnt = docCounts[k];
                const st = DOC_STATUS[actions[k]?.status] || { tone: cnt ? 'warning' : 'neutral', label: cnt ? '검토 필요' : '영향 없음' };
                const sel = effSelectedDoc === k;
                return (
                  <button key={k} type="button" onClick={() => setSelectedDoc(k)}
                    aria-label={`${meta.label} 문서 선택`} aria-pressed={sel}
                    style={{ textAlign: 'left', padding: '7px 9px', borderRadius: 6, cursor: 'pointer', font: 'inherit',
                      border: sel ? '2px solid var(--accent)' : '1px solid var(--border)',
                      background: sel ? 'var(--panel)' : 'var(--bg)', opacity: cnt ? 1 : 0.55 }}>
                    <div style={{ fontWeight: 700, fontSize: 12 }}>{meta.icon} {meta.label}</div>
                    <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>{meta.desc}</div>
                    <div style={{ marginTop: 3, display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
                      <StatusBadge tone={st.tone}>{st.label}</StatusBadge>
                      <span className="text-muted" style={{ fontSize: 10 }}>{cnt} 함수</span>
                    </div>
                  </button>
                );
              })}
            </div>
            {/* 우: 선택 문서 상세 */}
            <div style={{ minWidth: 0 }}>
              {(() => {
                const meta = DOC_META[effSelectedDoc];
                const a = actions[effSelectedDoc] || {};
                const st = DOC_STATUS[a.status] || null;
                const sitsReason = impactWarnings.find(w => /SITS/i.test(w) && /(미집계|미생성|미실행|체인|통합)/.test(w)) || '';
                return (
                  <div>
                    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8, paddingBottom: 6, borderBottom: '1px solid var(--border)' }}>
                      <span style={{ fontWeight: 700, fontSize: 14 }}>{meta.icon} {meta.label}</span>
                      <span className="text-muted text-sm">{meta.desc}</span>
                      {st && <StatusBadge tone={st.tone}>{st.label}</StatusBadge>}
                      {a.mode && a.mode !== '-' && (
                        <span className={`pill ${a.mode === 'AUTO' ? 'pill-success' : 'pill-warning'}`} style={{ fontSize: 9 }}
                          title={a.mode === 'AUTO' ? '자동 반영 대상' : '검토 후 수동 반영(FLAG)'}>{a.mode}</span>
                      )}
                      <span style={{ flex: 1 }} />
                      <span className="text-muted text-sm">{docRows.length} 함수</span>
                    </div>
                    {effSelectedDoc === 'sits' && docRows.length > 0 && (
                      <div className="text-muted" style={{ fontSize: 10, marginBottom: 6, color: 'var(--color-warning)' }}>
                        ⓘ 통합 영향(cross-module) 함수 기준 — &lsquo;문서 갱신 검토 대상&rsquo;이며, 실제 SITS 시험 보유는 희소합니다(함수별 &lsquo;SITS TC&rsquo; 컬럼·회귀 패널 SwUFn 참조).
                      </div>
                    )}
                    {docRows.length === 0 ? (
                      <div className="text-muted text-sm" style={{ padding: 12 }}>
                        이 문서에 영향 없음.
                        {effSelectedDoc === 'sits' && sitsReason && <div style={{ marginTop: 4, color: 'var(--color-warning)' }}>ⓘ {sitsReason}</div>}
                      </div>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: '62vh', overflow: 'auto' }}>
                        {docRows.map((row) => {
                          const chips = row.d ? docChips(effSelectedDoc, row.d) : [];
                          return (
                            <div key={row.name} style={{ padding: 8, border: '1px solid var(--border)', borderRadius: 6, background: row.d?.changed ? 'var(--bg)' : 'transparent' }}>
                              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: row.acts.length ? 5 : 0 }}>
                                <span style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 600 }}>{renderFnRef(row.name)}</span>
                                {row.d?.changed
                                  ? <span className={`pill pill-${CHANGE_TYPE_TONE[row.d.changeType] || 'neutral'}`} style={{ fontSize: 8 }} title={CHANGE_TYPE_DESC[row.d.changeType] || ''}>{CHANGE_TYPE_KO[row.d.changeType] || row.d.changeType}</span>
                                  : <span className="pill pill-neutral" style={{ fontSize: 8 }} title="직접 변경 아님 — 간접 영향(계약 유지 확인)">{row.d?.hop || '간접'}</span>}
                                {row.d?.asil && /^[A-D]$/.test(row.d.asil) && (
                                  <span className={`pill ${/[CD]/.test(row.d.asil) ? 'pill-danger' : 'pill-warning'}`} style={{ fontSize: 8 }}>ASIL {row.d.asil}</span>
                                )}
                              </div>
                              {row.acts.length > 0 ? (
                                <ul style={{ fontSize: 11, margin: 0, padding: 0, listStyle: 'none' }}>
                                  {row.acts.map((act, j) => (
                                    <li key={j} style={{ marginBottom: 4, display: 'flex', gap: 5, alignItems: 'baseline' }}>
                                      <span className={`pill pill-${act.tone}`} style={{ fontSize: 8, flexShrink: 0, whiteSpace: 'nowrap' }}>{act.section}</span>
                                      <span style={{ lineHeight: 1.4, minWidth: 0, overflowWrap: 'anywhere' }} title={act.title || undefined}>{renderInlineCode(act.text)}</span>
                                    </li>
                                  ))}
                                </ul>
                              ) : row.d ? (
                                <div className="text-sm text-muted">특이 액션 없음</div>
                              ) : (
                                <div className="text-sm text-muted">요구/TC 매핑 미조회(함수 상세 없음)</div>
                              )}
                              {chips.length > 0 && (
                                <div style={{ marginTop: 4 }}>
                                  {chips.slice(0, 10).map(tc => <span key={tc} className="pill pill-neutral" style={{ fontSize: 8, margin: 1 }}>{tc}</span>)}
                                  {chips.length > 10 && <span className="text-muted" style={{ fontSize: 8 }}> +{chips.length - 10}개</span>}
                                </div>
                              )}
                              {renderDocContent(row.name, effSelectedDoc)}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          </div>
        </div>
        )}

          {/* Detail modal — 공유(탭 무관 오버레이). AI 요약/함수별 상세 어느 탭에서 클릭해도 표시. */}
          {selectedFn && (() => {
            const d = guide.details.find(x => x.function === selectedFn);
            if (!d) return null;
            const ct = (d.changeType || '').toUpperCase();
            const cd = changeDetails[String(d.function).toLowerCase()] || {};
            const fd = functionDiffs[String(d.function).toLowerCase()] || '';
            const hasRaw = !!(cd.before || cd.after);
            const pdiff = hasRaw ? diffSignatureParamsCached(cd.before, cd.after) : null;
            const sigSummary = summarizeSignatureChange(pdiff);
            const diffElems = extractDiffElementsCached(fd);  // 본문 diff에서 변경 전역·전처리 추출(BODY/VARIABLE 구체화)
            const hasDirectEvidence = hasRaw || !!fd;  // 선언 원문(cd) 또는 본문 hunk(fd) 존재
            // 권위 evidence(백엔드 function_meta) 소비 — 리스트(functionHasNoEvidence)와 판정 일치.
            // 'file_fatten'=파일 단위 영향(직접 변경 아님) · 'line'=실 라인 변경(원문은 400KB 절단·로컬/cloudium
            // diff 경로에서 생략될 수 있음) · ''=간접/레거시 job. 옛 추론(fd/cd 유무)은 절단된 실변경을 fatten으로
            // 오표기했다 → evidence로 구분. evidence 없는 구 job은 아래 식이 기존 동작(‖!hasDirectEvidence)로 폴백.
            const _fnMeta = functionMeta[String(d.function).toLowerCase()] ?? functionMeta[d.function] ?? {};
            const evKind = _fnMeta.evidence || '';
            const isFatten = evKind === 'file_fatten';
            const isTruncated = evKind === 'line' && !hasDirectEvidence;  // 실 변경이나 원문 절단/미수집(파일영향 아님)
            const noEvidence = d.changed && (isFatten || (!evKind && !hasDirectEvidence));  // 파일영향(권위) — 절단 실변경 제외
            const isFormatOnly = d.changed && diffElems.noSemanticChange;  // 본문 diff가 이동/공백/포맷만 — 의미 변경 없음
            // 파일레벨 원문 폴백(#3) — 함수 자체 diff가 없으면(파일영향/원문절단) 그 파일의 전체 변경을 폴백 표시.
            const fileDiffFallback = (!fd && _fnMeta.file) ? matchFileDiff(_fnMeta.file, fileDiffs) : '';
            // 문서별 구체 편집 액션(결정론) — 파라미터 diff·본문 변경 요소·요구사항·TC 반영. LLM 무관·즉시.
            const docActions = buildDocumentActions(d, pdiff, diffElems);
            const DOC_CARDS = [
              { key: 'uds', icon: '📘', title: 'UDS 업데이트', note: d.requirements.length ? `관련 요구사항: ${d.requirements.slice(0, 5).join(', ')}${d.requirements.length > 5 ? ` +${d.requirements.length - 5}개` : ''}` : '' },
              { key: 'sts', icon: '📗', title: 'STS 검토', chips: d.stsTestCases },
              { key: 'suts', icon: '📙', title: 'SUTS 업데이트', chips: d.sutsTestCases },
              { key: 'sits', icon: '📕', title: 'SITS 검토', chips: d.sitsTestCases || [], note: '통합 콜체인·Input/Expected Param' },
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
                      {noEvidence && <span className="pill pill-neutral" style={{ fontSize: 10 }} title="직접 변경 증거 없음 — 파일 단위 영향(hunk/선언 미감지, 보수적 포함)">파일영향</span>}
                      {isFormatOnly && <span className="pill pill-neutral" style={{ fontSize: 10 }} title="본문 diff가 코드 이동/공백/포맷만 — 의미(로직) 변경 없음(재정렬 아님)">포맷/이동</span>}
                      {isTruncated && <span className="pill pill-warning" style={{ fontSize: 10 }} title="실 라인 변경이나 본문 원문이 크기 상한(60줄/400KB)을 넘어 생략됨 — 파일영향 아님(변경 판정은 유효)">원문 절단</span>}
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
                                  <td style={{ padding: '3px 6px', fontFamily: 'monospace', color: r.before ? 'var(--color-danger)' : 'var(--text-muted)', wordBreak: 'break-word' }}>{r.before || '—'}</td>
                                  <td style={{ padding: '3px 6px', fontFamily: 'monospace', color: r.after ? 'var(--color-success)' : 'var(--text-muted)', wordBreak: 'break-word' }}>{r.after || '—'}</td>
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

                {/* 🔧 본문 변경 원문(function diff) — BODY 등 선언 미변경 함수의 실제 코드 변경(AI 근거) */}
                {fd && (
                  <div style={{ marginBottom: 12, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
                    <details>
                      <summary style={{ padding: '6px 10px', background: 'var(--bg)', fontWeight: 700, fontSize: 12, cursor: 'pointer' }}>
                        🔧 본문 변경 원문 <span className="text-muted" style={{ fontWeight: 400, fontSize: 10 }}>(svn diff — AI 설명 근거)</span>
                      </summary>
                      <pre style={{ margin: 0, padding: 10, fontSize: 11, fontFamily: 'var(--font-mono, monospace)', whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 320, overflow: 'auto' }}>
                        {fd.split('\n').map((ln, i) => {
                          const color = (ln.startsWith('+') && !ln.startsWith('+++')) ? 'var(--color-success)'
                            : (ln.startsWith('-') && !ln.startsWith('---')) ? 'var(--color-danger)'
                            : ln.startsWith('@@') ? 'var(--accent)' : 'var(--text-muted)';
                          return <div key={i} style={{ color }}>{ln || ' '}</div>;
                        })}
                      </pre>
                    </details>
                  </div>
                )}
                {fileDiffFallback && (
                  <div style={{ marginBottom: 12, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
                    <details>
                      <summary style={{ padding: '6px 10px', background: 'var(--bg)', fontWeight: 700, fontSize: 12, cursor: 'pointer' }}>
                        📄 파일 전체 변경 보기 <span className="text-muted" style={{ fontWeight: 400, fontSize: 10 }}>(이 함수는 자체 diff 없음 — 같은 파일의 구조 변경으로 보수 포함)</span>
                      </summary>
                      <pre style={{ margin: 0, padding: 10, fontSize: 11, fontFamily: 'var(--font-mono, monospace)', whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 320, overflow: 'auto' }}>
                        {fileDiffFallback.split('\n').map((ln, i) => {
                          const color = (ln.startsWith('+') && !ln.startsWith('+++')) ? 'var(--color-success)'
                            : (ln.startsWith('-') && !ln.startsWith('---')) ? 'var(--color-danger)'
                            : (ln.startsWith('@@') || ln.startsWith('Index:') || ln.startsWith('===')) ? 'var(--accent)' : 'var(--text-muted)';
                          return <div key={i} style={{ color }}>{ln || ' '}</div>;
                        })}
                      </pre>
                    </details>
                  </div>
                )}
                {noEvidence && (ct === 'BODY' || ct === 'VARIABLE') && (
                  <div className="text-muted" style={{ fontSize: 11, marginBottom: 12, padding: '6px 10px', background: 'var(--bg)', borderRadius: 6, borderLeft: '3px solid var(--border)' }}>
                    직접 변경 아님 — 파일 단위 영향입니다. 같은 파일의 다른 변경(전처리·선언 등)으로 검토 대상에 보수적으로 포함됐으며, 본문 변경 원문이 없는 것이 정상입니다. AI 설명도 추정입니다.
                  </div>
                )}
                {isTruncated && (
                  <div className="text-muted" style={{ fontSize: 11, marginBottom: 12, padding: '6px 10px', background: 'var(--bg)', borderRadius: 6, borderLeft: '3px solid var(--color-warning)' }}>
                    실제 라인 변경이 있으나 본문 원문이 크기 상한(함수당 60줄·전체 400KB)을 넘어 생략됐습니다. <strong>파일영향이 아니며</strong> 실 변경이므로 Description·Test Action·Expected Result를 재검토하세요.
                  </div>
                )}
                {isFormatOnly && (
                  <div className="text-muted" style={{ fontSize: 11, marginBottom: 12, padding: '6px 10px', background: 'var(--bg)', borderRadius: 6, borderLeft: '3px solid var(--border)' }}>
                    본문 diff가 <strong>코드 이동·공백·포맷만</strong>이고 의미(로직) 변경은 없습니다(재정렬 아님). 관련 문서(Description·Test Action·Expected) 재검토가 불필요할 수 있습니다 — AI 설명으로 확인하세요.
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
                  {exp.text && <div style={{ padding: 10, fontSize: 12, whiteSpace: 'pre-wrap', lineHeight: 1.6, overflowWrap: 'anywhere' }}>{exp.text}</div>}
                  {exp.error && <div style={{ padding: 10, fontSize: 11, color: 'var(--text-muted)' }}>⚠ {exp.error}</div>}
                </div>

                {/* Change description */}
                <div style={{ padding: '8px 10px', background: 'var(--bg)', borderRadius: 6, marginBottom: 12, fontSize: 12, borderLeft: `3px solid ${noEvidence ? 'var(--border)' : 'var(--color-warning)'}` }}>
                  {!d.changed && `이 함수는 직접 변경되지 않았으나, 변경 함수와의 호출 관계(${d.hop})로 영향받는 간접 함수입니다. 인터페이스 계약이 유지되는지, 회귀 시험(SUTS/SITS) 재실행이 필요한지 확인하세요.`}
                  {ct === 'BODY' && (noEvidence
                    ? '이 함수의 직접 변경(hunk/선언)은 감지되지 않았습니다. 같은 파일의 다른 변경(전처리·선언 등)으로 영향 검토 대상에 보수적으로 포함된 함수입니다(파일 단위 영향).'
                    : isFormatOnly
                      ? '본문 diff가 코드 이동·공백·포맷만이고 의미(로직) 변경은 없습니다(재정렬 아님). 관련 문서 재검토가 불필요할 수 있습니다 — AI 설명으로 확인하세요.'
                      : '함수 본문(로직)이 변경되었습니다. 동작 변경으로 인해 관련 문서의 Description, Test Action, Expected Result를 모두 재검토해야 합니다.')}
                  {ct === 'SIGNATURE' && '함수 시그니처(파라미터/리턴타입)가 변경되었습니다. 호출하는 모든 함수와 Input/Output Parameters, Pre-condition을 업데이트해야 합니다.'}
                  {ct === 'HEADER' && '헤더 파일이 변경되었습니다. 매크로/타입 정의 변경으로 이 헤더를 include하는 모든 소스 파일의 함수에 영향이 있을 수 있습니다.'}
                  {ct === 'VARIABLE' && '글로벌 변수가 변경되었습니다. 이 변수를 읽고 쓰는 모든 함수의 동작을 확인해야 합니다.'}
                  {ct === 'NEW' && '신규 함수가 추가되었습니다. UDS에 Function Information 항목을 추가하고, 관련 TC를 작성해야 합니다.'}
                  {ct === 'DELETE' && '함수가 삭제되었습니다. UDS에서 해당 함수를 제거하고, 관련 TC를 비활성화해야 합니다.'}
                </div>

                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6 }}>
                  각 문서에 <strong>무엇을 어느 섹션에</strong> 반영해야 하는지 — 실제 매개변수 변화 기반(결정론).
                </div>
                {noEvidence && (
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 6, padding: '4px 8px', background: 'var(--bg)', borderRadius: 4 }}>
                    ※ 직접 변경 증거는 없으나(파일 단위 보수 포함) 아래 <strong>📄 실제 문서 내용</strong>은 파싱본입니다 — 편집 <em>액션</em>만 파일 변경 맥락 기준 일반 가이드.
                  </div>
                )}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))', gap: 10 }}>
                  {DOC_CARDS.map(card => {
                    const acts = docActions[card.key] || [];
                    const chips = card.chips || [];
                    return (
                      <div key={card.key} style={{ padding: 10, border: '1px solid var(--border)', borderRadius: 6, minWidth: 0 }}>
                        <div style={{ fontWeight: 600, fontSize: 12, marginBottom: 6, color: 'var(--accent)' }}>{card.icon} {card.title}</div>
                        {acts.length > 0 ? (
                          <ul style={{ fontSize: 11, margin: '0 0 4px 0', padding: 0, listStyle: 'none' }}>
                            {acts.map((a, i) => (
                              <li key={i} style={{ marginBottom: 5, display: 'flex', gap: 5, alignItems: 'baseline' }}>
                                <span className={`pill pill-${a.tone}`} style={{ fontSize: 8, flexShrink: 0, whiteSpace: 'nowrap' }}>{a.section}</span>
                                <span style={{ lineHeight: 1.4, minWidth: 0, overflowWrap: 'anywhere' }} title={a.title || undefined}>{renderInlineCode(a.text)}</span>
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
                        {renderDocContent(d.function, card.key)}
                        {card.note && <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>{card.note}</div>}
                      </div>
                    );
                  })}
                </div>
                </div>
              </div>
            );
          })()}
        </>
      )}
    </div>
  );
}
