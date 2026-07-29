// 문서 작성급 초안 — 원문(문서에 지금 있는 것) ↔ 제안(있어야 하는 것) 대조 판정.
//
// 이 모듈이 이 기능의 핵심 가치다. 예전 수정안은 시그니처 파라미터(u16t_Data)의 경계값 pill
// 세 개가 전부였는데, 정작 원문은 다른 변수(g_sys_error_his[0..4])를 다루고 있었다. 즉 제안이
// 원문에 grounding되어 있지 않았다. 여기서는 **컬럼 집합을 원문에서** 가져와 그 불일치를
// 구조적으로 없애고, 각 경계값이 문서에 이미 있는지(유지) 없는지(신규추가)를 판정한다.
//
// ⚠ 정직성 규약 (이 파일에서 가장 중요한 부분)
//   - 타입 미상(varTypes에 키 없음) → **숫자를 만들지 않는다**. '[검증 필요] 타입 미상'.
//     여기서 U8 기본값 같은 걸 쓰면 U16 변수에 MAX=0xFF를 제안하는 환각이 된다.
//   - `값수정`은 **하드 근거가 있을 때만** 발행한다(아래 VERDICT 주석). 근거 없이 "고쳐라"는
//     0x87E7이 U16 범위 안인데도 수정을 요구하는 오판이다.
//   - 값 비교가 불가능하면(비수치) 판정을 **보류**한다. 문자열 비교로 강등하지 않는다.
//   - 행 번호·TC ID는 원문에 있을 때만 붙인다(날조 금지).
//
// 컴포넌트와 분리(react-refresh/only-export-components) + 순수 함수라 단위 테스트 용이.

import { cTypeBoundaries } from './impactBoundary.js';

export const VERDICT = {
  KEEP: '유지',
  RECHECK: '유지(기대값 재확인)',
  MODIFY: '값수정',
  ADD: '신규추가',
  UNKNOWN: '검증필요',
  // SITS 원문 TC 판정 전용 — "이 값을 유지/수정하라"가 아니라 "이 통합 TC를 다시 돌려라"다.
  // KEEP/RECHECK 라벨을 재사용하면 "유지"로 읽혀 재검증 지시가 정반대로 전달된다.
  REVERIFY: '재검증',
};

// 배열 첨자를 뗀 기본 변수명. 표시·컬럼은 첨자를 보존하고 **타입 조회만** base로 한다
// (백엔드 workflow/impact_doc_draft.py의 base_var와 같은 규약 — var_types 키가 base다).
export function baseVar(name) {
  const s = String(name ?? '').trim();
  if (!s) return '';
  return s.replace(/(?:\[[^\]]*\])+$/, '').trim();
}

// '0x0' | '0' | '0x0000' | '-128' → Number ; 비수치(문자열 상태값 등)는 null.
// 진법이 달라도 같은 값이면 같게 봐야 한다 — 원문은 hex, 일부 제안은 10진이라 문자열
// 비교로는 0x0과 0을 다른 값으로 오판해 멀쩡한 케이스를 '신규추가'로 요구하게 된다.
export function normalizeNumeric(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  let s = String(v).trim();
  if (!s) return null;
  s = s.split('(')[0].trim();          // '0x100(범위초과)' → '0x100'
  s = s.replace(/[uUlL]+$/, '');       // C 리터럴 접미사(0xFFu, 100UL)
  let neg = false;
  if (s.startsWith('+')) s = s.slice(1);
  else if (s.startsWith('-')) { neg = true; s = s.slice(1); }
  let n = null;
  if (/^0[xX][0-9a-fA-F]+$/.test(s)) n = parseInt(s.slice(2), 16);
  else if (/^0[bB][01]+$/.test(s)) n = parseInt(s.slice(2), 2);
  else if (/^\d+$/.test(s)) n = parseInt(s, 10);
  else if (/^\d*\.\d+$/.test(s)) n = parseFloat(s);
  if (n === null || !Number.isFinite(n)) return null;
  return neg ? -n : n;
}

// 두 값이 같은가. 수치는 진법 무관 비교, **양쪽이 비수치면 문자열 완전 일치만** 참으로 본다.
//
// ⚠ "문자열 비교로 강등하지 않는다"는 규약은 `'0'`과 `'0x0'`을 다른 값으로 보지 말라는 뜻이지,
//   `'NULL'`과 `'NULL'`을 비교하지 말라는 뜻이 아니다. 완전 일치는 모호하지 않다 — 이걸 막았더니
//   포인터/ENUM 입력(`NULL`·`IDLE`)이 문서에 그대로 있는데도 매칭이 안 돼 전부 '신규추가'가 됐다
//   (이미 있는 TC를 중복 작성하라는 지시). 다르면 여전히 null(보류) — 표기 차이일 수 있다.
// 값 문자열 정규화 — 앞뒤/내부 공백을 접고 대소문자를 무시한다. 시트는 사람이 적어서
// `TRUE`/`true`, `MODE_A` / `MODE_A ` 같은 표기 흔들림이 흔한데, 그걸 '다른 값'이라 하면
// 없는 차이를 신규추가로 단정하게 된다.
function _vnorm(v) {
  return String(v ?? '').trim().replace(/\s+/g, ' ').toUpperCase();
}

function sameValue(a, b) {
  const na = normalizeNumeric(a);
  const nb = normalizeNumeric(b);
  if (na !== null && nb !== null) return na === nb;
  if (na === null && nb === null) {
    // ⚠ "문자열 비교로 강등하지 않는다"는 규칙은 `'0'` vs `'0x0'` 을 문자열로 갈라 보지
    //   말라는 뜻이다 — 그 경우는 위 수치 분기가 이미 잡는다. 여기까지 온 건 **양쪽 다
    //   수치가 아닌** 값이라, 같으면 같다고 하고 다르면 다르다고 하는 게 맞다.
    //   예전엔 둘 다 null(보류)로 돌려보내, 문서에 `mode=IDLE` 이 있는데 생성기가 `mode=RUN`
    //   을 제안하면 그 변수를 **비교에서 빼버려** 나머지 한 변수만 맞아도 '유지'가 됐다
    //   (= 문서에 없는 케이스를 "이미 있으니 두라"고 지시 — 거짓 유지).
    const sa = _vnorm(a);
    const sb = _vnorm(b);
    if (sa && sb) return sa === sb;
  }
  // 한쪽만 수치이거나 한쪽이 비었으면 진짜 모호하다(`'NULL'` vs `'0'`) → 판정 보류.
  return null;
}

// 변경 전역 분류 — buildDocumentActions와 동일 근거(added∩removed = 값 변경).
function globalSets(diffElems) {
  const de = diffElems || {};
  const g = de.changedGlobals || {};
  const added = new Set(g.added || []);
  const removed = new Set(g.removed || []);
  const changed = new Set([...added].filter((v) => removed.has(v)));
  const touched = new Set([...added, ...removed]);
  return { changed, touched };
}

// TC 위치 앵커 문자열(있는 필드만 — 행 번호 날조 금지). impactBoundary.formatSutsLoc과 동일 규약이나
// TC ID까지 합쳐 한 줄로 만든다.
function evidenceOf(row) {
  if (!row) return '';
  const parts = [];
  if (row.tc_id) parts.push(`TC ${row.tc_id}`);
  const loc = row.loc;
  if (loc && typeof loc === 'object') {
    if (loc.sheet) parts.push(`${loc.sheet} 시트`);
    if (loc.tc_row !== null && loc.tc_row !== undefined && loc.tc_row !== '') parts.push(`행 ${loc.tc_row}`);
  }
  return parts.join(' · ');
}

// 실제 SUTS 시트는 Input 그룹(C14~C62)과 Expected Result 그룹(C63~C148)이 **별도 열**이고
// 같은 변수명이 양쪽에 온다. 그래서 컬럼을 side로 네임스페이스한다 — 예전엔 하나로 합쳐
// `inputs[v] ?? expected[v]`로 읽는 바람에 입력값이 있으면 **기대값이 통째로 사라졌다**.
const SIDE = { IN: 'input', EXP: 'expected' };
const colKey = (side, name) => `${side}:${name}`;

// 원문 TC 행에서 컬럼(side+name)의 값.
function docValue(row, col) {
  if (!row || typeof row !== 'object' || !col) return undefined;
  const bag = col.side === SIDE.EXP ? (row.expected || {}) : (row.inputs || {});
  return Object.prototype.hasOwnProperty.call(bag, col.name) ? bag[col.name] : undefined;
}

// 열 순서 = 문서 컬럼(시트 헤더 원문) 우선 → 행 키 → 생성 시퀀스 키. Input 그룹 먼저, 그다음 Expected.
function orderedColumns(docColumns, docRows, genSeqs) {
  const bySide = { [SIDE.IN]: [], [SIDE.EXP]: [] };
  const seen = new Set();
  const add = (side, x) => {
    const name = String(x ?? '').trim();
    if (!name) return;
    const k = colKey(side, name);
    if (seen.has(k)) return;
    seen.add(k);
    bySide[side].push({ key: k, name, side });
  };
  const dc = docColumns || {};
  (dc.inputs || []).forEach((v) => add(SIDE.IN, v));
  (dc.expected || []).forEach((v) => add(SIDE.EXP, v));
  const scan = (list) => (list || []).forEach((r) => {
    if (r && typeof r === 'object') {
      Object.keys(r.inputs || {}).forEach((v) => add(SIDE.IN, v));
      Object.keys(r.expected || {}).forEach((v) => add(SIDE.EXP, v));
    }
  });
  scan(docRows);
  scan(genSeqs);
  return [...bySide[SIDE.IN], ...bySide[SIDE.EXP]];
}

// 행이 어느 축에서 잘렸는가. 백엔드 `kv_truncated`는 inputs **또는** expected 중 하나만 넘쳐도
// 켜지는데, 매칭은 **입력 축으로만** 한다 — SUTS 템플릿의 Expected 열은 최대 86개라 기대 축은
// 거의 항상 절단되고, 그걸로 판정을 뒤집으면 입력이 8/8 완전 대조인 행까지 `검증필요`가 되어
// 판정 열이 통째로 붕괴한다(실측). 기대 축 절단은 판정이 아니라 **노트**다.
function truncAxis(row) {
  if (!row || !row.kv_truncated) return { inputs: false, expected: false };
  const t = row.kv_total || {};
  const inShown = Object.keys(row.inputs || {}).length;
  const expShown = Object.keys(row.expected || {}).length;
  return {
    // kv_total이 없는 구 job은 어느 축인지 알 수 없다 → 안전측으로 입력 절단 취급.
    inputs: Number.isFinite(t.inputs) ? t.inputs > inShown : true,
    expected: Number.isFinite(t.expected) ? t.expected > expShown : false,
  };
}

// 입력 축이 잘렸는가(= 매칭 근거가 불완전한가). 판정 승격을 막는 유일한 기준.
function isPartialMatch(row) {
  return truncAxis(row).inputs;
}

// 절단 사유 문구. 입력 축은 "단정 불가", 기대 축은 표시 한계만 밝힌다(판정 불변).
function truncNote(row) {
  const ax = truncAxis(row);
  const t = (row && row.kv_total) || {};
  const parts = [];
  if (ax.inputs) {
    parts.push(`원문 입력 ${t.inputs ?? '?'}개 중 ${Object.keys(row.inputs || {}).length}개만 대조`
      + ' — 나머지는 문서에서 확인(단정 불가)');
  }
  if (ax.expected) {
    parts.push(`기대값 ${t.expected}개 중 ${Object.keys(row.expected || {}).length}개만 표시`);
  }
  return parts.join(' · ');
}

// 컬럼 목록 → 고유 변수명(양쪽 side 중복 제거, 등장 순서 보존).
function uniqueNames(columns) {
  const out = [];
  const seen = new Set();
  (columns || []).forEach((c) => {
    if (c && c.name && !seen.has(c.name)) { seen.add(c.name); out.push(c.name); }
  });
  return out;
}

// 타입 조회 — varTypes 키는 base_var. 없으면 null(숫자 제안 금지).
function typeOf(varTypes, v) {
  const t = (varTypes || {})[baseVar(v)];
  return t && t.type ? t : null;
}

/**
 * SUTS 초안 판정.
 *
 * 두 모드가 있다 — 데이터가 무엇을 줄 수 있느냐로 갈린다:
 *  - `sequence`  : 백엔드 생성기 시퀀스(genSeqs)가 있을 때. 행 = 제안 TC 시퀀스(전략별
 *                  Input/Expected 완본)라 그대로 문서에 옮겨 쓸 수 있다.
 *  - `boundary`  : 생성기가 없을 때(cloudium). 행 = 변수 × 경계 라벨. 원문 값과 대조해
 *                  어떤 경계가 이미 커버됐고 어떤 게 빠졌는지만 정직하게 말한다.
 *
 * @returns {{mode, columns, rows, unknownTypes, newColumns, totals, notes}}
 */
export function reconcileSuts({ docRows, docColumns, genSeqs, varTypes, diffElems, sigParams, docTotal } = {}) {
  const rows = Array.isArray(docRows) ? docRows.filter((r) => r && typeof r === 'object') : [];
  const seqs = Array.isArray(genSeqs) ? genSeqs.filter((s) => s && typeof s === 'object') : [];
  const columns = orderedColumns(docColumns, rows, seqs);
  const names = uniqueNames(columns);
  const { changed, touched } = globalSets(diffElems);
  // ⚠ 타입 미상은 **경계값 모드에서만** 문제다 — 그때만 타입으로 경계값을 유도하기 때문이다.
  //   시퀀스 모드는 생성기가 구체값을 주므로 타입이 없어도 아쉬울 게 없는데, 모드와 무관하게
  //   세면 "경계값 자동 유도 불가"라는 **없는 문제**를 매번 경고한다(cry wolf). 입력 축만 센다.
  const unknownTypes = seqs.length ? [] : uniqueNames(columns.filter((c) => c.side === SIDE.IN))
    .filter((n) => !typeOf(varTypes, n));

  // 문서에 없는 시그니처 파라미터 — 원문 컬럼과 **섞지 않고** 따로 표기한다.
  // (섞으면 "원문은 g_sys_error_his인데 제안은 u16t_Data" 불일치가 그대로 재발한다.)
  const colSet = new Set(names.map(baseVar));
  const newColumns = (Array.isArray(sigParams) ? sigParams : [])
    .filter((p) => p && p.name && !colSet.has(baseVar(p.name)))
    .map((p) => ({ name: p.name, type: p.type || '', cases: cTypeBoundaries(p.type) }));

  // 변경 전역이 이 함수의 변수집합에 걸리는지 — 판정 승격의 근거(행마다 재계산하지 않는다).
  const anyChanged = names.some((n) => changed.has(baseVar(n)));
  const anyTouched = names.some((n) => touched.has(baseVar(n)));
  // ⚠ 백엔드가 행당 변수 수를 잘랐으면(`kv_truncated`) 잘린 변수는 대조에서 `undefined`라
  //   **판정에서 제외**된다. 그 상태의 일치는 "같다"가 아니라 "일부만 봤다"이므로 `유지`로
  //   승격하면 실제로는 값이 다른 TC를 "그대로 두라"고 지시하게 된다(거짓 유지).
  const partial = isPartialMatch;
  const promote = (matched) => {
    if (!matched) return VERDICT.ADD;
    if (partial(matched)) return VERDICT.UNKNOWN;   // 부분 대조 — 단정 금지
    if (anyChanged) return VERDICT.MODIFY;   // added∩removed = 값 변경(하드 근거)
    if (anyTouched) return VERDICT.RECHECK;  // 초기화 추가/제거만 = 기대값 재확인
    return VERDICT.KEEP;
  };
  const partialNote = truncNote;

  const out = [];
  if (seqs.length) {
    seqs.forEach((s, i) => {
      const cells = {};
      let matchedRow = null;
      let cmpNote = '';
      // 원문 TC 중 "제안 입력과 모든 비교 가능한 변수가 일치"하는 게 있으면 이미 커버된 것.
      // ⚠ 몇 개를 비교했는지도 센다 — 3변수 TC에 1변수만 우연히 맞은 것을 "같은 TC"라 단정하면
      //   안 된다. 판정은 유지하되 **비교 근거의 폭**을 노트로 밝힌다.
      for (const r of rows) {
        let ok = null;
        let cmp = 0;
        for (const [k, v] of Object.entries(s.inputs || {})) {
          const dv = docValue(r, { name: k, side: SIDE.IN });
          if (dv === undefined) continue;
          const eq = sameValue(v, dv);
          if (eq === null) continue;      // 비수치 → 이 변수는 판정에서 제외(보류)
          cmp += 1;
          ok = ok === null ? eq : (ok && eq);
        }
        if (ok === true) {
          matchedRow = r;
          const docIn = Object.keys(r.inputs || {}).length;
          if (docIn > cmp) cmpNote = `입력 ${docIn}개 중 ${cmp}개만 비교 — 동일 TC 여부 미확정`;
          break;
        }
      }
      // 같은 입력인데 **기대값이 다르면** '유지'가 아니다. 문서는 X를, 생성기는 Y를 말하는
      // 실질 불일치이므로 단정(값수정) 대신 실행 검증 대상으로 올린다(생성기 기대값은 추론값).
      let expConflict = '';
      if (matchedRow) {
        for (const [k, v] of Object.entries(s.expected || {})) {
          const dv = docValue(matchedRow, { name: k, side: SIDE.EXP });
          if (dv === undefined) continue;
          if (sameValue(v, dv) === false) {
            expConflict = `동일 입력에 기대값 상이(문서 ${dv} / 추론 ${v}) — 실행 검증 필요`;
            break;
          }
        }
      }
      columns.forEach((c) => {
        const bag = c.side === SIDE.EXP ? (s.expected || {}) : (s.inputs || {});
        const proposed = bag[c.name];
        // 매칭된 원문 행이 없으면 '현재값'은 **없다**. 임의로 rows[0]을 끌어다 쓰면
        // "이 행이 지금 X다"라고 거짓을 말하게 된다(silent wrong-pick).
        const current = matchedRow ? docValue(matchedRow, c) : undefined;
        cells[c.key] = {
          current: current === undefined ? '' : String(current),
          proposed: proposed === undefined ? '' : String(proposed),
        };
      });
      out.push({
        key: `seq-${i}`,
        strategy: String(s.strategy || ''),
        // 생성기의 사람이 읽는 라벨(description 첫 줄). 없으면 전략 코드 그대로.
        label: String(s.description || '').split('\n')[0].trim(),
        seqNum: s.seq_num ?? i + 1,
        // 기대값이 어긋나면 '유지'로 단정하지 않는다(셀은 변경을 그리는데 판정이 유지면 자기모순).
        verdict: expConflict ? VERDICT.UNKNOWN : promote(matchedRow),
        evidence: evidenceOf(matchedRow),
        note: [partialNote(matchedRow), expConflict, cmpNote].filter(Boolean).join(' · '),
        cells,
      });
    });
  } else {
    // 경계값 모드 — **입력 변수** × 경계 라벨. 경계값은 입력 축이고 기대값은 사용자가 판정할
    // 대상이라, 같은 변수를 Expected 쪽으로 한 번 더 돌리면 같은 행이 두 번 나온다.
    const inputNames = uniqueNames(columns.filter((c) => c.side === SIDE.IN));
    const targets = inputNames.length ? inputNames : names;
    targets.forEach((n) => {
      const t = typeOf(varTypes, n);
      if (!t) {
        out.push({
          key: `unk-${n}`,
          variable: n,
          type: '',
          boundary: '',
          proposed: '',
          current: '',
          verdict: VERDICT.UNKNOWN,
          evidence: '',
          note: '타입 미상 — 원문 타입 정의 확인(경계값 자동 유도 불가)',
        });
        return;
      }
      const inCol = { name: n, side: SIDE.IN };
      // ⚠ 원문 값이 비수치(ENUM/상태 토큰 'ACTIVE' 등)면 경계 커버 여부를 **대조할 수 없다**.
      //   그걸 "문서에 없다"로 읽어 전 경계를 '신규추가'로 요구하면, 실제로는 커버돼 있을 수 있는
      //   케이스를 중복 작성하라는 지시가 된다(모듈 상단 규약: 비교 불가는 판정 보류).
      //   단 판정 기준은 "**쓸 만한 수치가 하나도 없을 때**"다. "한 행이라도 텍스트면"으로 하면
      //   8행 중 1행만 'N/A'인 흔한 경우에 정당한 신규추가 제안이 통째로 사라진다(과잉 보류).
      let sawNumeric = false;
      let sawText = false;
      for (const r of rows) {
        const dv = docValue(r, inCol);
        if (dv === undefined || String(dv).trim() === '') continue;
        if (normalizeNumeric(dv) === null) sawText = true; else sawNumeric = true;
      }
      const nonNumericDoc = sawText && !sawNumeric;
      const cases = cTypeBoundaries(t.type);
      if (!cases.length) {
        // 타입은 해상됐는데 경계값 테이블에 없는 계열(예: generators의 'bit'). 예전엔 행 자체가
        // 안 생기고 unknownTypes에도 안 들어가 **표에서 흔적 없이 사라졌다**(무언 소실).
        out.push({
          key: `nobound-${n}`,
          variable: n,
          type: t.type,
          typeSource: t.source || '',
          boundary: '',
          proposed: '',
          current: '',
          verdict: VERDICT.UNKNOWN,
          evidence: '',
          note: `타입 '${t.type}' 경계값 자동 유도 불가 — 유효값·경계를 직접 확인`,
        });
        return;
      }
      cases.forEach((bc) => {
        let hit = null;
        for (const r of rows) {
          const dv = docValue(r, inCol);
          if (dv === undefined) continue;
          if (sameValue(bc.value, dv) === true) { hit = r; break; }
        }
        out.push({
          key: `bv-${n}-${bc.label}`,
          variable: n,
          type: t.type,
          typeSource: t.source || '',
          boundary: bc.label,
          proposed: bc.value,
          current: hit ? String(docValue(hit, inCol)) : '',
          // 기대값은 원문에서 그대로 가져오지 않는다 — 경계값이 바뀌면 기대값도 다시 판정해야 한다.
          expectedCurrent: hit ? String(docValue(hit, { name: n, side: SIDE.EXP }) ?? '') : '',
          // 매칭 실패 + 원문이 비수치 = "없다"가 아니라 "대조 불가"다.
          verdict: (!hit && nonNumericDoc) ? VERDICT.UNKNOWN : promote(hit),
          evidence: evidenceOf(hit),
          note: [
            partialNote(hit),
            (!hit && nonNumericDoc) ? '원문 값이 비수치 — 경계 커버 여부 대조 불가' : '',
          ].filter(Boolean).join(' · '),
        });
      });
    });
  }

  return {
    mode: seqs.length ? 'sequence' : 'boundary',
    columns,
    rows: out,
    unknownTypes,
    newColumns,
    totals: {
      docShown: rows.length,
      docTotal: Number.isFinite(docTotal) ? docTotal : rows.length,
      proposed: out.length,
    },
  };
}

/**
 * SITS 초안 판정 — 통합 서브케이스(케이스 라벨 + Input/Expected)를 원문과 대조.
 * 콜체인은 판정 대상이 아니라 컨텍스트(표 위 메타로 표시).
 */
export function reconcileSits({ docTcs, gen, varTypes, diffElems } = {}) {
  const g = gen && typeof gen === 'object' ? gen : {};
  const subs = Array.isArray(g.sub_cases) ? g.sub_cases.filter((s) => s && typeof s === 'object') : [];
  // 원문 SITS TC들의 서브케이스를 평탄화 — 대조 대상.
  // ⚠ `doc_content.sits_by_tc`에는 **두 가지 shape**이 온다:
  //    (a) `_load_sits_fn_chains`(중간 JSON) → sub_cases 있음 → 대조 가능
  //    (b) `_load_testspec_by_tc`(원본 xlsm 폴백) → description/test_action/expected 문자열만,
  //        **sub_cases 없음**. SITS 빌더를 아직 돌리지 않아 중간 JSON이 없으면 이쪽이다.
  //  (b)에서 그냥 대조하면 docSubs가 비어 **전 행이 '신규추가'**가 되고, 헤더는 "문서 있음"이라
  //  이미 문서에 있는 통합 케이스를 중복 작성하라는 지시가 된다 → 판정 자체를 보류한다.
  const tcs = (Array.isArray(docTcs) ? docTcs : []).filter((t) => t && typeof t === 'object');
  const docSubs = [];
  tcs.forEach((tc) => {
    (tc.sub_cases || []).forEach((sc) => {
      if (sc && typeof sc === 'object') docSubs.push({ ...sc, tc_id: tc.tc_id || '' });
    });
  });
  // 대조 완전성 — 3값이어야 한다. 예전엔 "전부 미파싱"만 잡아서, TC 3건 중 1건만 파싱돼도
  // 나머지 2건을 "문서에 없다"로 단정해 **이미 있는 통합 TC를 중복 작성하라**고 지시했다.
  const tcsUnparsed = tcs.filter((tc) => !(tc.sub_cases || []).length).length;
  // 백엔드가 실은 절단 전 총량(`sub_total`)보다 적게 로드됐는지도 같은 불완전이다.
  const subShort = tcs.some(
    (tc) => Number.isFinite(tc.sub_total) && tc.sub_total > (tc.sub_cases || []).length,
  );
  const docUnparsed = tcs.length > 0 && docSubs.length === 0;          // 전부 미파싱
  const docPartial = !docUnparsed && (tcsUnparsed > 0 || subShort);     // 일부만 확보
  // 해당하는 축만 말한다 — 예전엔 미파싱이 0건인데도 "원문 TC 1건 중 0건 미파싱"이라 적었다.
  const incompleteNote = docUnparsed
    ? '원문 서브케이스 미파싱(SITS 중간파일 부재) — 신규/유지 판정 불가'
    : (docPartial
      ? [
        tcsUnparsed ? `원문 TC ${tcs.length}건 중 ${tcsUnparsed}건 미파싱` : '',
        subShort ? '서브케이스가 원문보다 적게 로드됨' : '',
      ].filter(Boolean).join(' · ') + ' — 문서에 없다고 단정 불가'
      : '');
  const columns = orderedColumns(null, docSubs, subs);
  const names = uniqueNames(columns);
  const { changed, touched } = globalSets(diffElems);
  const unknownTypes = names.filter((n) => !typeOf(varTypes, n));
  const anyChanged = names.some((n) => changed.has(baseVar(n)));
  const anyTouched = names.some((n) => touched.has(baseVar(n)));
  // ⚠ SUTS와 동일한 부분-대조 가드. `_shrink_doc_content`가 SITS 서브케이스의 변수도 자르며
  //   `kv_truncated`를 붙이는데, 이걸 안 보면 변수 20개 중 5개만 일치한 것을 '유지'로 단정한다.
  const partial = isPartialMatch;
  const partialNote = truncNote;
  // 원문 서브케이스 총량(절단 전). 백엔드 `sub_total`을 합산해 '총 N건 중 M건'을 살린다 —
  // 예전엔 docTotal=docSubs.length라 truncated 판정이 **구조적으로 항상 false**였다.
  const docSubTotal = tcs.reduce(
    (a, tc) => a + (Number.isFinite(tc.sub_total) ? tc.sub_total : (tc.sub_cases || []).length), 0,
  );

  const rows = subs.map((sc, i) => {
    const cells = {};
    let matched = null;
    for (const d of docSubs) {
      let ok = null;
      for (const [k, v] of Object.entries(sc.inputs || {})) {
        const dv = docValue(d, { name: k, side: SIDE.IN });
        if (dv === undefined) continue;
        const eq = sameValue(v, dv);
        if (eq === null) continue;
        ok = ok === null ? eq : (ok && eq);
      }
      if (ok === true) { matched = d; break; }
    }
    columns.forEach((c) => {
      const bag = c.side === SIDE.EXP ? (sc.expected || {}) : (sc.inputs || {});
      const proposed = bag[c.name];
      const current = matched ? docValue(matched, c) : undefined;
      cells[c.key] = {
        current: current === undefined ? '' : String(current),
        proposed: proposed === undefined ? '' : String(proposed),
      };
    });
    // 원문이 **불완전**(전부 또는 일부 미파싱)하면 '신규추가'로 단정하지 않는다 — 문서에 이미
    // 있는지 알 수 없는 상태다. 없는 근거로 중복 TC 작성을 지시하는 것보다 보류가 정직하다.
    let verdict = (docUnparsed || docPartial) ? VERDICT.UNKNOWN : VERDICT.ADD;
    if (matched) {
      // 부분 대조는 단정하지 않는다(SUTS `promote`와 동일 규약).
      verdict = partial(matched) ? VERDICT.UNKNOWN
        : (anyChanged ? VERDICT.MODIFY : (anyTouched ? VERDICT.RECHECK : VERDICT.KEEP));
    }
    return {
      key: `sub-${i}`,
      label: String(sc.case_label || '').trim(),
      caseNum: sc.case_num ?? i + 1,
      precondition: String(sc.precondition || ''),
      verdict,
      evidence: matched && matched.tc_id ? `TC ${matched.tc_id}` : '',
      // 매칭된 행이 있으면 그 행의 부분대조 사유가, 없으면 원문 불완전 사유가 판정의 근거다.
      note: matched ? partialNote(matched) : incompleteNote,
      cells,
    };
  });

  return {
    mode: 'subcase',
    columns,
    rows,
    unknownTypes,
    newColumns: [],
    // `->` 는 표시 단계에서 `→`로 바꾼다(기존 카드 표기와 동일).
    callChain: String(g.call_chain || '').replace(/\s*->\s*/g, ' → '),
    docUnparsed,
    docPartial,
    // 생성기 축 절단(백엔드 `total`/`truncated`) — 예전엔 프론트가 안 읽어 "제안 6건"이 확정
    // 수치처럼 보였다. SUTS엔 있는 표기가 SITS에만 없던 비대칭.
    genTotal: Number.isFinite(g.total) ? g.total : null,
    genTruncated: !!g.truncated,
    // docTotal은 **절단 전** 원문 서브케이스 수. 예전엔 docShown과 같은 값이라
    // '총 N건 중 M건' 배너가 구조적으로 절대 뜨지 않았다(SUTS엔 있는 안전장치가 SITS엔 없었다).
    totals: { docShown: docSubs.length, docTotal: docSubTotal || docSubs.length, proposed: rows.length },
  };
}

// SITS 원문 TC의 콜체인 텍스트. `_load_sits_fn_chains`(중간 JSON)는 `call_chain`을 주지만,
// 원본 xlsm 폴백(`_load_testspec_by_tc`)은 "Interface : a -> b -> c"를 description/test_action에
// 담아 온다 — 실사용에서는 이 폴백이 흔하다(SITS 빌더 미실행 시).
// 절단 여부는 **백엔드가 명시한 플래그**를 쓴다. 길이로 되짚으면 정확히 캡 길이인 완전한
// 원문을 절단으로 오판한다(실측: 250자 완전 체인이 절단으로 찍혔다). 플래그가 없는 구 job만
// 길이 휴리스틱으로 폴백한다(그 시절 캡: call_chain 200 / description·test_action 300).
const SITS_LEGACY_CAP = { call_chain: 200, description: 300, test_action: 300 };

function sitsChainOf(tc) {
  if (!tc || typeof tc !== 'object') return { chain: '', truncated: false };
  const pick = (field, raw) => {
    const s = String(raw || '');
    const flag = tc[`${field === 'call_chain' ? 'chain' : field}_truncated`];
    const truncated = flag === undefined ? s.length >= SITS_LEGACY_CAP[field] : !!flag;
    const m = s.match(/interface\s*:?\s*(.+)/is);
    const chain = (m && m[1].includes('->')) ? m[1].trim() : (s.includes('->') ? s.trim() : '');
    return chain ? { chain, truncated } : null;
  };
  return pick('call_chain', tc.call_chain)
    || pick('description', tc.description)
    || pick('test_action', tc.test_action)
    || { chain: '', truncated: false };
}

// 콜체인 텍스트에서 함수명 토큰 추출(대소문자 무시 비교용).
function chainFns(chain) {
  return new Set(String(chain || '').split(/\s*->\s*/).map((x) => x.trim().toLowerCase()).filter(Boolean));
}

// 변경 종류별로 이 통합 TC에서 **무엇을 봐야 하는가**. 일반론이 아니라 축을 특정한다.
const SITS_FOCUS = {
  HEADER: '헤더 타입·매크로 변경 — 콜체인 경계의 인터페이스 의존성(호출 규약·크기·정렬) 확인',
  SIGNATURE: '시그니처 변경 — 콜체인 상위 호출부의 인자 계약 확인',
  BODY: '본문 변경 — 콜체인 하위 산출이 만드는 통합 기대값 재확인',
  VARIABLE: '전역/변수 변경 — 통합 진입 상태(Precondition)와 전파 경로 확인',
  NEW: '신규 함수 — 이 콜체인에 편입되는지, 편입되면 통합 케이스 추가 필요',
  DELETE: '삭제 함수 — 콜체인에서 제거되는 경로와 대체 경로 확인',
};

/**
 * SITS 초안(원문 TC 기반) — 생성기 서브케이스가 없을 때.
 *
 * 실사용에서 흔한 조합이다: 문서에는 통합 TC가 여럿 있고 콜체인·Method도 적혀 있는데,
 * SITS 빌더를 안 돌려 중간 JSON이 없어 서브케이스(입력/기대값)가 없다. 예전엔 이 경우
 * **원문을 통째로 무시하고** "`<fn>` 통합 콜체인 확인" 두 줄만 냈다.
 *
 * 여기서는 조인된 TC마다 **무엇을 왜 다시 봐야 하는지**를 원문 근거로 말한다.
 * ⚠ 콜체인 텍스트는 백엔드가 200~300자로 자른다 — 변경 함수가 안 보인다고 "영향 없음"이라
 *   단정하지 않는다(절단된 뒤쪽에 있을 수 있다). 그 경우는 '확인 필요'로 남긴다.
 */
export function reconcileSitsDocTcs({ docTcs, fn, changeType, diffElems, join, normTc } = {}) {
  const tcs = (Array.isArray(docTcs) ? docTcs : []).filter((t) => t && typeof t === 'object');
  const target = String(fn || '').trim().toLowerCase();
  const { touched } = globalSets(diffElems);
  const focus = SITS_FOCUS[String(changeType || '').toUpperCase()] || '변경 반영 여부 확인';
  // 추적성 조인 근거 — 백엔드가 파싱한 **전체 콜체인**(`chain_fns`) 기준이라 절단이 없다.
  // 화면용 텍스트로 재추론하면 300자 뒤의 함수를 못 찾아 전부 '검증필요'가 된다(실측).
  const byChain = (join && join.chain) || new Set();
  const byUnit = (join && join.unit) || new Set();
  const norm = typeof normTc === 'function' ? normTc : ((s) => String(s || '').replace(/\s+/g, '').toUpperCase());

  const rows = tcs.map((tc, i) => {
    const { chain, truncated } = sitsChainOf(tc);
    const fns = chainFns(chain);
    const nk = norm(tc.tc_id);
    // 우선순위: 추적성 조인(정확) → 표시 텍스트 매칭(보조) → 전역 → 미확정
    const joinedByChain = byChain.has(nk);
    const joinedByUnit = byUnit.has(nk);
    const inChain = !!target && fns.has(target);
    const gHit = [...touched].filter((g) => chain.toLowerCase().includes(String(g).toLowerCase()));
    let verdict;
    let evidence;
    if (joinedByChain) {
      verdict = VERDICT.REVERIFY;
      evidence = '콜체인에 변경 함수 포함(추적성 전체 체인 기준)';
    } else if (joinedByUnit) {
      verdict = VERDICT.REVERIFY;
      evidence = '이 통합시험의 단위(SwUFn) 진입 함수';
    } else if (inChain) {
      verdict = VERDICT.REVERIFY;
      evidence = '콜체인에 변경 함수 포함';
    } else if (gHit.length) {
      verdict = VERDICT.REVERIFY;
      evidence = `콜체인에 변경 전역 포함(${gHit.slice(0, 2).join(', ')})`;
    } else {
      verdict = VERDICT.UNKNOWN;
      evidence = truncated
        ? '콜체인 원문이 절단됨 — 포함 여부 미확정'
        : '요구 경유로 조인 — 콜체인에서 직접 확인 불가';
    }
    return {
      key: `tc-${i}`,
      tcId: String(tc.tc_id || ''),
      chain: chain.replace(/\s*->\s*/g, ' → '),
      method: String(tc.test_method || ''),
      precondition: String(tc.precondition || ''),
      unit: String(tc.unit_name || ''),
      verdict,
      evidence,
      focus,
      note: truncated ? '콜체인 원문 절단(백엔드 표시 상한) — 전체는 문서에서 확인' : '',
    };
  });

  return {
    mode: 'tc',
    columns: [],
    rows,
    unknownTypes: [],
    newColumns: [],
    totals: { docShown: rows.length, docTotal: rows.length, proposed: rows.length },
  };
}

/**
 * UDS 초안 — 원문 → 변경안의 항목 단위 diff(Prototype / Used Globals / Calls / Logic Flow).
 * 산문(Description)은 결정론 근거가 없어 값을 만들지 않고 `descriptionPending`으로만 표시한다.
 *
 * 항목은 두 부류다 — 섞으면 안 된다:
 *  - `verdict` 있는 항목 = **대조해서 차이를 찾은 것**(Prototype 변경, 전역 추가/제거)
 *  - `echo: true` 항목 = 대조하지 않고 **그대로 보여주는 참고값**(호출 함수·Precondition).
 *    예전엔 이쪽에도 `유지`를 붙였는데, 문서와 비교한 적이 없으므로 "그대로 두라"고 말할
 *    근거가 없다(오늘 SUTS 쪽에서 고친 '근거 없는 유지'와 같은 부류).
 *
 * `changeAfter`: SIGNATURE 변경의 변경 후 선언. `doc_proposal.uds` 노드가 없는 구 job에서도
 * Prototype 짝을 만들 수 있게 호출부가 `change_details[fn].after` 를 직접 넘긴다.
 */
export function reconcileUds({ udsContent, proposal, diffElems, changeAfter } = {}) {
  const c = udsContent && typeof udsContent === 'object' ? udsContent : {};
  const p = proposal && typeof proposal === 'object' ? proposal : {};
  const de = diffElems || {};
  const gAdd = (de.changedGlobals && de.changedGlobals.added) || [];
  const gRem = (de.changedGlobals && de.changedGlobals.removed) || [];
  const addSet = new Set(gAdd);
  const remSet = new Set(gRem);
  const items = [];

  // ⚠ '원문'으로 보여주는 값은 **문서 원문(udsContent)** 이 먼저다. proposal 은 소스에서
  //   파생된 값이라, 그걸 "원문:"이라 이름 붙여 그리면 소스 추론값을 문서 내용으로 위장한다.
  const before = String(c.prototype || p.prototype || '');
  const after = String(changeAfter || p.prototype_after || '');
  if (after && after !== before) {
    items.push({ field: 'Prototype', before, after, verdict: VERDICT.MODIFY });
  }

  const curGlobals = ((c.globals && c.globals.length ? c.globals : (p.globals || [])) || []).map(String);
  const addOnly = gAdd.filter((v) => !remSet.has(v));
  const remOnly = gRem.filter((v) => !addSet.has(v));
  if (addOnly.length || remOnly.length) {
    items.push({
      field: 'Used Globals',
      before: curGlobals.join(', '),
      added: addOnly.map(String),
      removed: remOnly.map(String),
      verdict: VERDICT.MODIFY,
    });
  }

  // 아래는 대조 결과가 아니라 **작성 재료**다 — 백엔드가 소스에서 뽑아둔 것을 화면에 전달만 한다.
  const flow = (p.logic_flow || []).map(String);
  if (flow.length) items.push({ field: 'Logic Flow (의사코드 개요)', before: '', after: flow.join('\n'), verdict: VERDICT.ADD });
  const calls = ((p.calls && p.calls.length ? p.calls : (c.calls || [])) || []).map(String);
  if (calls.length) items.push({ field: 'Called Functions', before: calls.join(', '), after: '', verdict: '', echo: true });
  if (p.precondition) items.push({ field: 'Precondition', before: String(p.precondition), after: '', verdict: '', echo: true });

  return {
    items,
    // 산문은 결정론 불가 — 백엔드가 'ai_required'로 표기한 것을 그대로 전달한다(창작 금지).
    descriptionPending: p.description_source === 'ai_required',
    currentDescription: String(c.description || ''),
  };
}

// TSV 셀 정규화 — Excel 붙여넣기에서 탭/개행은 셀·행을 쪼갠다. 값 자체를 잃지 않도록 공백 치환.
function tsvCell(v) {
  return String(v ?? '').replace(/[\t\r\n]+/g, ' ');
}

/**
 * Excel 붙여넣기용 TSV. 열 순서는 **호출부가 넘긴 columns 그대로**(백엔드 문서 컬럼).
 * JS에 열 순서를 하드코딩하지 않는다 — 템플릿마다 다르고, 틀리면 붙여넣기가 통째로 밀린다.
 */
export function buildTsv(columns, rows) {
  const cols = (Array.isArray(columns) ? columns : []).map((c) => (typeof c === 'string' ? { key: c, label: c } : c))
    .filter((c) => c && c.key !== undefined);
  if (!cols.length) return '';
  const head = cols.map((c) => tsvCell(c.label ?? c.key)).join('\t');
  const body = (Array.isArray(rows) ? rows : []).map(
    (r) => cols.map((c) => tsvCell((r || {})[c.key])).join('\t'),
  );
  return [head, ...body].join('\n');
}
