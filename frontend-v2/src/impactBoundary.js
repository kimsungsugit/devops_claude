// 경계값 유도(결정론) — 영향분석 문서 '작성 제안' 골격의 수치 출처.
//
// 변경 영향 평가 모달의 문서 작성 제안(ImpactGuideSection의 renderAuthoringProposal)이
// SUTS/SITS 경계값 TC 골격을 만들 때 쓴다. C 함수 파라미터 타입 → 경계값 케이스로 결정론 변환.
// 컴포넌트 파일과 분리(react-refresh/only-export-components) + 순수 함수라 단위 테스트 용이.
//
// ⚠ 백엔드 workflow/impact_ai_guide.py의 `_c_type_boundaries`가 동일 매핑을 미러링한다
//   (AI 카드의 '경계값' 제안을 같은 실제 값으로 grounding) — 한쪽 수정 시 다른 쪽도 갱신할 것.

// C 타입 문자열 → 경계값 케이스 [{label, value}].
// 프로젝트 표준 Hungarian 타입(U8/U16/U32/S8/S16/S32/boolean) + 일반 C/AUTOSAR 별칭 커버.
// enum/struct/typedef 등 미상 타입은 [](숫자 조작·환각 금지 — 호출부가 '원문 확인' 골격만 표시).
export function cTypeBoundaries(type) {
  if (!type) return [];
  const raw = String(type);
  // 포인터/배열 → 주소/버퍼 경계(NULL·유효). 정수 경계 유도 전에 먼저 판정.
  if (/[*]/.test(raw) || /\[/.test(raw)) {
    return [{ label: 'NULL', value: 'NULL' }, { label: '유효', value: '유효 포인터/버퍼' }];
  }
  const t = raw.replace(/\b(const|volatile|register)\b/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase();
  const FLOAT = new Set(['float', 'f32', 'float32', 'single', 'double', 'f64', 'float64', 'real', 'real32', 'real64', 'float32_t', 'float64_t']);
  if (FLOAT.has(t)) {
    return [{ label: '0', value: '0.0' }, { label: '음수', value: '음의 경계값' }, { label: '양수', value: '양의 경계값' }, { label: '특수', value: 'NaN/±Inf(해당 시)' }];
  }
  const ALIAS = {
    u8: 'u8', uint8: 'u8', uint8_t: 'u8', 'unsigned char': 'u8', uchar: 'u8', byte: 'u8',
    u16: 'u16', uint16: 'u16', uint16_t: 'u16', 'unsigned short': 'u16', 'unsigned short int': 'u16', ushort: 'u16', word: 'u16',
    u32: 'u32', uint32: 'u32', uint32_t: 'u32', 'unsigned int': 'u32', unsigned: 'u32', 'unsigned long': 'u32', uint: 'u32', ulong: 'u32', dword: 'u32',
    s8: 's8', int8: 's8', int8_t: 's8', sint8: 's8', 'signed char': 's8', char: 's8',
    s16: 's16', int16: 's16', int16_t: 's16', sint16: 's16', short: 's16', 'signed short': 's16', 'short int': 's16',
    s32: 's32', int32: 's32', int32_t: 's32', sint32: 's32', int: 's32', 'signed int': 's32', long: 's32', 'signed long': 's32', signed: 's32',
    boolean: 'bool', bool: 'bool', _bool: 'bool', bool_t: 'bool',
  };
  const key = ALIAS[t];
  if (!key) return [];  // 미상 타입 — 숫자 조작 금지
  const TABLE = {
    u8: [['MIN', '0'], ['MID', '128'], ['MAX', '255'], ['INV', '256(범위초과)']],
    u16: [['MIN', '0'], ['MID', '32768'], ['MAX', '65535']],
    u32: [['MIN', '0'], ['MID', '2147483648'], ['MAX', '4294967295']],
    s8: [['MIN', '-128'], ['MID', '0'], ['MAX', '127']],
    s16: [['MIN', '-32768'], ['MID', '0'], ['MAX', '32767']],
    s32: [['MIN', '-2147483648'], ['MID', '0'], ['MAX', '2147483647']],
    bool: [['FALSE', '0'], ['TRUE', '1']],
  };
  return TABLE[key].map(([label, value]) => ({ label, value }));
}

// 파라미터 목록 → 경계값 TC 골격(결정론). params=[{type,name}] (parseSignatureParams 산출).
// 반환 { params:[{param,type,cases,rationale}], branchNote }. 미상 타입은 골격만(가짜 숫자 없음).
// diffElems.macros(변경된 조건부 컴파일)가 있으면 분기 커버 케이스 note 추가.
export function proposeBoundaryTCs(params, diffElems = null) {
  const ps = Array.isArray(params) ? params.filter((p) => p && p.name) : [];
  const out = [];
  for (const p of ps) {
    const cases = cTypeBoundaries(p.type);
    out.push(cases.length
      ? { param: p.name, type: p.type, cases, rationale: `${p.name}(${p.type}) 입력 경계값 — 케이스별 기대출력 판정기준 작성` }
      : { param: p.name, type: p.type, cases: [{ label: '유효/경계', value: '각 유효값·경계' }], rationale: `타입 '${p.type}' 경계 자동 유도 불가 — 원문 타입 정의 확인` });
  }
  const de = diffElems || {};
  const macros = de.macros ? [...new Set([...(de.macros.removed || []), ...(de.macros.added || [])])] : [];
  return { params: out, branchNote: macros.length ? `변경된 조건부 컴파일(${macros.slice(0, 3).join(', ')}) 분기 커버 케이스 추가` : '' };
}

// SUTS TC 실 위치(백엔드 doc_content.suts[fn][i].loc = {sheet, tc_row, sequence_row}) → 표시 문자열.
// "이 TC(행 N)를 이렇게 수정" 앵커용. 존재하는 필드만 이어붙인 정직 표기(행 번호 날조 금지) — 빈/누락은 ''.
// ⚠ sheet 라벨은 백엔드가 넘긴 값만 쓴다(하드코딩 금지 — SUTS 템플릿별 시트명 상이, 예 '2.SW Unit Test Spec').
export function formatSutsLoc(loc) {
  if (!loc || typeof loc !== 'object') return '';
  const parts = [];
  if (loc.sheet) parts.push(`${loc.sheet} 시트`);
  if (loc.tc_row != null && loc.tc_row !== '') parts.push(`행 ${loc.tc_row}`);
  return parts.join(' · ');
}
