import { describe, it, expect } from 'vitest';
import {
  VERDICT, baseVar, normalizeNumeric, reconcileSuts, reconcileSits, reconcileUds, buildTsv,
} from '../impactDocDraft.js';

// 사용자가 실제로 본 화면의 데이터. 원문은 g_sys_error_his[0..4]를 다루는데 예전 수정안은
// 시그니처 파라미터 u16t_Data의 경계값만 보여줬다 — 서로 다른 변수를 가리키던 불일치.
const COLS = ['g_sys_error_his[0]', 'g_sys_error_his[1]', 'g_sys_error_his[2]'];
const docColumns = { inputs: COLS, expected: COLS, sheet: '2.SW Unit Test Spec' };
const docRows = [
  {
    tc_id: 'SwUTC_SwUFn_1219',
    loc: { sheet: '2.SW Unit Test Spec', tc_row: 2103 },
    inputs: Object.fromEntries(COLS.map((c) => [c, '0x0'])),
    expected: Object.fromEntries(COLS.map((c) => [c, '0x0'])),
  },
  {
    tc_id: 'SwUTC_SwUFn_1219',
    loc: { sheet: '2.SW Unit Test Spec', tc_row: 2103 },
    inputs: Object.fromEntries(COLS.map((c) => [c, '0x8000'])),
    expected: Object.fromEntries(COLS.map((c) => [c, '0x8000'])),
  },
  {
    tc_id: 'SwUTC_SwUFn_1219',
    loc: { sheet: '2.SW Unit Test Spec', tc_row: 2103 },
    inputs: Object.fromEntries(COLS.map((c) => [c, '0x87E7'])),
    expected: Object.fromEntries(COLS.map((c) => [c, '0x87E7'])),
  },
];
const varTypesU16 = { g_sys_error_his: { type: 'U16', source: 'doc_annotation' } };

describe('normalizeNumeric — 진법 무관 수치 비교', () => {
  it('hex/10진/0패딩이 같은 값으로 정규화', () => {
    expect(normalizeNumeric('0x0')).toBe(0);
    expect(normalizeNumeric('0')).toBe(0);
    expect(normalizeNumeric('0x0000')).toBe(0);
    expect(normalizeNumeric('0xFFFF')).toBe(65535);
    expect(normalizeNumeric(65535)).toBe(65535);
    expect(normalizeNumeric('-128')).toBe(-128);
  });

  it('C 리터럴 접미사·괄호 주석 제거', () => {
    expect(normalizeNumeric('0xFFu')).toBe(255);
    expect(normalizeNumeric('100UL')).toBe(100);
    expect(normalizeNumeric('0x100(범위초과)')).toBe(256);
  });

  it('비수치는 null (문자열 비교로 강등하지 않기 위해)', () => {
    expect(normalizeNumeric('IDLE')).toBeNull();
    expect(normalizeNumeric('유효 포인터/버퍼')).toBeNull();
    expect(normalizeNumeric('')).toBeNull();
    expect(normalizeNumeric(null)).toBeNull();
    expect(normalizeNumeric(undefined)).toBeNull();
    expect(normalizeNumeric(NaN)).toBeNull();
  });
});

describe('baseVar — 첨자는 표시에서 보존, 조회만 base', () => {
  it('배열 첨자 제거', () => {
    expect(baseVar('g_sys_error_his[0]')).toBe('g_sys_error_his');
    expect(baseVar('matrix[1][2]')).toBe('matrix');
    expect(baseVar('u16t_Data')).toBe('u16t_Data');
    expect(baseVar('')).toBe('');
  });
});

describe('reconcileSuts — 경계값 모드(cloudium: 생성기 없음)', () => {
  it('컬럼이 원문에서 온다 — 시그니처 파라미터로 대체되지 않는다', () => {
    const r = reconcileSuts({
      docRows, docColumns, varTypes: varTypesU16,
      sigParams: [{ name: 'u16t_Data', type: 'U16' }],
    });
    expect(r.mode).toBe('boundary');
    // 실제 시트처럼 Input 그룹 먼저, 그다음 Expected Result 그룹
    expect(r.columns.filter((c) => c.side === 'input').map((c) => c.name)).toEqual(COLS);
    expect(r.columns.filter((c) => c.side === 'expected').map((c) => c.name)).toEqual(COLS);
    expect(r.columns.slice(0, 3).every((c) => c.side === 'input')).toBe(true);
    expect(r.columns.map((c) => c.name)).not.toContain('u16t_Data');
    // 문서에 없는 시그니처 파라미터는 원문 컬럼과 섞지 않고 따로 표기
    expect(r.newColumns.map((c) => c.name)).toEqual(['u16t_Data']);
  });

  it('경계값 행은 입력 변수당 한 번만 — Expected 컬럼 때문에 두 배가 되지 않는다', () => {
    const r = reconcileSuts({ docRows, docColumns, varTypes: varTypesU16 });
    const mins = r.rows.filter((x) => x.variable === 'g_sys_error_his[0]' && x.boundary === 'MIN');
    expect(mins).toHaveLength(1);
  });

  it('경계값이 유지여도 그 TC의 현재 기대값을 함께 보여준다(기대값 재판정 근거)', () => {
    const r = reconcileSuts({ docRows, docColumns, varTypes: varTypesU16 });
    const min = r.rows.find((x) => x.variable === 'g_sys_error_his[0]' && x.boundary === 'MIN');
    expect(min.current).toBe('0x0');
    expect(min.expectedCurrent).toBe('0x0');
  });

  it('MIN·MID는 원문에 있으니 유지, MAX는 없으니 신규추가', () => {
    const r = reconcileSuts({ docRows, docColumns, varTypes: varTypesU16 });
    const v0 = r.rows.filter((x) => x.variable === 'g_sys_error_his[0]');
    const byLabel = Object.fromEntries(v0.map((x) => [x.boundary, x]));
    expect(byLabel.MIN.verdict).toBe(VERDICT.KEEP);      // 0x0 존재
    expect(byLabel.MID.verdict).toBe(VERDICT.KEEP);      // 0x8000 존재
    expect(byLabel.MAX.verdict).toBe(VERDICT.ADD);       // 0xFFFF 없음
    expect(byLabel.MAX.proposed).toBe('0xFFFF');
    expect(byLabel.MAX.current).toBe('');                // 없는 현재값을 지어내지 않는다
  });

  it('유지 판정에는 TC·행 근거가 붙는다(없으면 빈 문자열 — 날조 금지)', () => {
    const r = reconcileSuts({ docRows, docColumns, varTypes: varTypesU16 });
    const keep = r.rows.find((x) => x.verdict === VERDICT.KEEP);
    expect(keep.evidence).toBe('TC SwUTC_SwUFn_1219 · 2.SW Unit Test Spec 시트 · 행 2103');
    const add = r.rows.find((x) => x.verdict === VERDICT.ADD);
    expect(add.evidence).toBe('');
  });

  it('근거 없는 값수정을 발행하지 않는다 (0x87E7은 U16 범위 안)', () => {
    const r = reconcileSuts({ docRows, docColumns, varTypes: varTypesU16 });
    expect(r.rows.some((x) => x.verdict === VERDICT.MODIFY)).toBe(false);
  });

  it('전역이 값 변경(added∩removed)일 때만 값수정 — 단순 touch는 재확인', () => {
    const modify = reconcileSuts({
      docRows, docColumns, varTypes: varTypesU16,
      diffElems: { changedGlobals: { added: ['g_sys_error_his'], removed: ['g_sys_error_his'] } },
    });
    expect(modify.rows.filter((x) => x.verdict === VERDICT.MODIFY).length).toBeGreaterThan(0);

    const recheck = reconcileSuts({
      docRows, docColumns, varTypes: varTypesU16,
      diffElems: { changedGlobals: { added: ['g_sys_error_his'], removed: [] } },
    });
    expect(recheck.rows.some((x) => x.verdict === VERDICT.RECHECK)).toBe(true);
    expect(recheck.rows.some((x) => x.verdict === VERDICT.MODIFY)).toBe(false);
  });

  it('타입 미상 컬럼 → 숫자 0건 + 검증필요 (uint8_t 기본값 환각 차단)', () => {
    const r = reconcileSuts({
      docRows: [{ tc_id: 'T1', inputs: { SomeEnum_Mode: 'IDLE' }, expected: {} }],
      docColumns: { inputs: ['SomeEnum_Mode'], expected: [] },
      varTypes: {},
    });
    expect(r.unknownTypes).toEqual(['SomeEnum_Mode']);
    expect(r.rows).toHaveLength(1);
    expect(r.rows[0].verdict).toBe(VERDICT.UNKNOWN);
    expect(r.rows[0].proposed).toBe('');
    expect(JSON.stringify(r.rows)).not.toMatch(/0xFF|0xFFFF/);   // 어떤 경계값도 만들지 않았다
  });

  it('진법이 달라도 같은 값이면 유지 (0x0 ≡ 0)', () => {
    const r = reconcileSuts({
      docRows: [{ tc_id: 'T1', inputs: { u16_v: 0 }, expected: {} }],
      docColumns: { inputs: ['u16_v'], expected: [] },
      varTypes: { u16_v: { type: 'U16' } },
    });
    expect(r.rows.find((x) => x.boundary === 'MIN').verdict).toBe(VERDICT.KEEP);
  });

  it('절단 총계를 보존한다(총 N건 중 M건 표시)', () => {
    const r = reconcileSuts({ docRows, docColumns, varTypes: varTypesU16, docTotal: 12 });
    expect(r.totals).toMatchObject({ docShown: 3, docTotal: 12 });
  });
});

describe('reconcileSuts — 시퀀스 모드(생성기 산출)', () => {
  const genSeqs = [
    { strategy: 'BV_MIN', description: '최소 경계값\nInput: …', seq_num: 1,
      inputs: { 'g_sys_error_his[0]': '0x0' }, expected: { 'g_sys_error_his[0]': '0x0' } },
    { strategy: 'BV_MAX', description: '최대 경계값', seq_num: 2,
      inputs: { 'g_sys_error_his[0]': '0xFFFF' }, expected: { 'g_sys_error_his[0]': '[검증 필요] 3276' } },
  ];

  it('원문에 있는 시퀀스는 유지, 없는 것은 신규추가', () => {
    const r = reconcileSuts({ docRows, docColumns, genSeqs, varTypes: varTypesU16 });
    expect(r.mode).toBe('sequence');
    expect(r.rows[0].verdict).toBe(VERDICT.KEEP);
    expect(r.rows[1].verdict).toBe(VERDICT.ADD);
  });

  it('매칭 실패 행의 현재값은 비어 있다 (임의 행을 끌어다 쓰지 않음)', () => {
    const r = reconcileSuts({ docRows, docColumns, genSeqs, varTypes: varTypesU16 });
    expect(r.rows[1].cells['input:g_sys_error_his[0]'].current).toBe('');
    expect(r.rows[1].cells['input:g_sys_error_his[0]'].proposed).toBe('0xFFFF');
  });

  it('Input과 Expected가 별도 열이라 기대값이 입력값에 가려지지 않는다', () => {
    // 회귀 가드: 예전엔 `inputs[v] ?? expected[v]`로 읽어 같은 변수의 **기대값이 통째로 사라졌다**.
    // 실제 SUTS 시트는 Input(C14~C62)과 Expected Result(C63~C148)가 다른 열이다.
    const r = reconcileSuts({ docRows, docColumns, genSeqs, varTypes: varTypesU16 });
    expect(r.rows[1].cells['input:g_sys_error_his[0]'].proposed).toBe('0xFFFF');
    expect(r.rows[1].cells['expected:g_sys_error_his[0]'].proposed).toBe('[검증 필요] 3276');
  });

  it('전략 라벨(description 첫 줄)을 노출', () => {
    const r = reconcileSuts({ docRows, docColumns, genSeqs, varTypes: varTypesU16 });
    expect(r.rows[0].label).toBe('최소 경계값');
    expect(r.rows[0].strategy).toBe('BV_MIN');
  });
});

describe('reconcileSits — 통합 서브케이스', () => {
  const gen = {
    call_chain: 's_entry -> Hal_Read -> g_State',
    sub_cases: [
      { case_num: 1, case_label: '1 [EC1:무효-하한]', precondition: 'init',
        inputs: { rpm: 0 }, expected: { state: 1 } },
      { case_num: 2, case_label: '2 [EC2:유효-상한]', precondition: 'init',
        inputs: { rpm: 65535 }, expected: { state: 0 } },
    ],
  };
  const docTcs = [{ tc_id: 'SwITC_SwUFn_0101', sub_cases: [{ inputs: { rpm: '0x0' }, expected: { state: '1' } }] }];

  it('콜체인 화살표를 → 로 표시', () => {
    expect(reconcileSits({ gen }).callChain).toBe('s_entry → Hal_Read → g_State');
  });

  it('원문 서브케이스와 대조해 유지/신규추가 판정', () => {
    const r = reconcileSits({ docTcs, gen, varTypes: { rpm: { type: 'U16' }, state: { type: 'U8' } } });
    expect(r.rows[0].verdict).toBe(VERDICT.KEEP);       // rpm 0x0 ≡ 0
    expect(r.rows[0].evidence).toBe('TC SwITC_SwUFn_0101');
    expect(r.rows[1].verdict).toBe(VERDICT.ADD);
    expect(r.rows[1].label).toBe('2 [EC2:유효-상한]');
  });

  it('원문이 없어도 제안은 만들되 근거는 비운다', () => {
    const r = reconcileSits({ docTcs: [], gen, varTypes: {} });
    expect(r.rows).toHaveLength(2);
    expect(r.rows.every((x) => x.verdict === VERDICT.ADD && x.evidence === '')).toBe(true);
  });

  it('빈 입력 방어', () => {
    const r = reconcileSits({});
    expect(r.rows).toEqual([]);
    expect(r.callChain).toBe('');
  });
});

describe('reconcileUds — 항목 단위 원문→변경안', () => {
  it('Prototype 변경을 값수정으로, 전역 Δ를 ±로 표기', () => {
    const r = reconcileUds({
      udsContent: { prototype: 'void s_foo(U16 x)', globals: ['g_a'] },
      proposal: { prototype: 'void s_foo(U16 x)', prototype_after: 'void s_foo(U32 x)', globals: ['g_a'] },
      diffElems: { changedGlobals: { added: ['g_b'], removed: ['g_c'] } },
    });
    const proto = r.items.find((i) => i.field === 'Prototype');
    expect(proto.verdict).toBe(VERDICT.MODIFY);
    expect(proto.after).toBe('void s_foo(U32 x)');
    const globals = r.items.find((i) => i.field === 'Used Globals');
    expect(globals.after).toContain('− g_c');
    expect(globals.after).toContain('＋ g_b');
  });

  it('산문은 만들지 않고 보류 표기만 (동어반복 플레이스홀더 금지)', () => {
    const r = reconcileUds({
      udsContent: { description: '튜닝값 읽기' },
      proposal: { description_source: 'ai_required' },
    });
    expect(r.descriptionPending).toBe(true);
    expect(r.currentDescription).toBe('튜닝값 읽기');
    expect(JSON.stringify(r.items)).not.toMatch(/동작 변경 반영|본문 변경 반영/);
  });

  it('빈 입력이면 항목 없음', () => {
    expect(reconcileUds({}).items).toEqual([]);
  });
});

describe('buildTsv — Excel 붙여넣기', () => {
  it('열 순서는 넘긴 columns 그대로', () => {
    const tsv = buildTsv(['B', 'A'], [{ A: '1', B: '2' }]);
    expect(tsv).toBe('B\tA\n2\t1');
  });

  it('label/key 분리 컬럼 지원', () => {
    const tsv = buildTsv([{ key: 'v', label: 'Safety Related' }], [{ v: 'ASIL C' }]);
    expect(tsv).toBe('Safety Related\nASIL C');
  });

  it('탭·개행은 공백으로 — 셀/행이 쪼개지지 않게', () => {
    const tsv = buildTsv(['a'], [{ a: 'x\ty\nz' }]);
    expect(tsv).toBe('a\nx y z');
  });

  it('빈 셀은 빈 칸으로 보존(열 정렬 유지)', () => {
    expect(buildTsv(['a', 'b'], [{ a: '1' }])).toBe('a\tb\n1\t');
  });

  it('컬럼 없으면 빈 문자열', () => {
    expect(buildTsv([], [{ a: 1 }])).toBe('');
    expect(buildTsv(null, null)).toBe('');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// deep-review Critical 회귀 가드
//   C3 SITS 폴백 shape → 전 행 거짓 '신규추가'
//   C4 kv 절단 행 → 거짓 '유지'
//   W2 경계값 없는 타입(bit) → 무언 소실
// ─────────────────────────────────────────────────────────────────────────────

describe('판정 한계 — 단정하면 안 되는 경우', () => {
  it('C4: 행이 잘렸으면(kv_truncated) 유지로 승격하지 않는다', () => {
    // 원문 14열 중 12열만 실렸다. 잘린 2열은 대조에서 undefined라 판정에서 빠지는데,
    // 그 상태의 일치를 '유지'라 부르면 실제로는 값이 다른 TC를 "그대로 두라"고 지시하게 된다.
    const truncatedRow = {
      tc_id: 'T1', loc: { sheet: 'S', tc_row: 14 },
      inputs: { 'g_a[0]': '0x0' }, expected: { 'g_a[0]': '0x0' },
      kv_truncated: true, kv_total: { inputs: 14, expected: 14 },
    };
    const r = reconcileSuts({
      docRows: [truncatedRow],
      docColumns: { inputs: ['g_a[0]'], expected: ['g_a[0]'] },
      varTypes: { g_a: { type: 'U16' } },
    });
    const min = r.rows.find((x) => x.boundary === 'MIN');
    expect(min.verdict).toBe(VERDICT.UNKNOWN);
    expect(min.verdict).not.toBe(VERDICT.KEEP);
    expect(min.note).toMatch(/원문 입력 14개 중 1개만 대조/);
  });

  it('C4: 잘리지 않은 행은 그대로 유지 판정(과잉 보류 아님)', () => {
    const r = reconcileSuts({
      docRows: [{ tc_id: 'T1', inputs: { 'g_a[0]': '0x0' }, expected: { 'g_a[0]': '0x0' } }],
      docColumns: { inputs: ['g_a[0]'], expected: ['g_a[0]'] },
      varTypes: { g_a: { type: 'U16' } },
    });
    expect(r.rows.find((x) => x.boundary === 'MIN').verdict).toBe(VERDICT.KEEP);
  });

  it('C3: SITS 원문이 폴백 shape(sub_cases 없음)이면 신규추가로 단정하지 않는다', () => {
    // `_load_testspec_by_tc` 폴백은 description/test_action/expected 문자열만 준다.
    // 그대로 대조하면 docSubs가 비어 **전 행이 신규추가** → 이미 있는 통합 케이스를 중복 작성하게 된다.
    const r = reconcileSits({
      docTcs: [{ tc_id: 'SwITC_1', description: 'x', test_action: 'y', expected: 'z' }],
      gen: { call_chain: 'a -> b', sub_cases: [{ case_label: '1 [EC1]', inputs: { rpm: 0 }, expected: { st: 1 } }] },
      varTypes: {},
    });
    expect(r.docUnparsed).toBe(true);
    expect(r.rows[0].verdict).toBe(VERDICT.UNKNOWN);
    expect(r.rows[0].note).toMatch(/원문 서브케이스 미파싱/);
  });

  it('C3: 원문 TC 자체가 없으면(문서 미연동) 종전대로 신규추가', () => {
    const r = reconcileSits({
      docTcs: [],
      gen: { call_chain: 'a -> b', sub_cases: [{ inputs: { rpm: 0 }, expected: { st: 1 } }] },
      varTypes: {},
    });
    expect(r.docUnparsed).toBe(false);
    expect(r.rows[0].verdict).toBe(VERDICT.ADD);
  });

  it('W2: 경계값 테이블에 없는 타입(bit)은 행 자체가 사라지지 않는다', () => {
    // generators의 _TYPE_NAME_PATTERNS는 `_Flag`/`_Sta`/`_Enable` 을 'bit'으로 해상하는데
    // cTypeBoundaries('bit')는 []다. 예전엔 행도 unknownTypes도 없이 표에서 흔적 없이 빠졌다.
    const r = reconcileSuts({
      docRows: [{ tc_id: 'T1', inputs: { Relay_Flag: '0' }, expected: {} }],
      docColumns: { inputs: ['Relay_Flag'], expected: [] },
      varTypes: { Relay_Flag: { type: 'bit', source: 'name_pattern' } },
    });
    expect(r.rows).toHaveLength(1);
    expect(r.rows[0].variable).toBe('Relay_Flag');
    expect(r.rows[0].verdict).toBe(VERDICT.UNKNOWN);
    expect(r.rows[0].note).toMatch(/경계값 자동 유도 불가/);
    expect(r.rows[0].proposed).toBe('');
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// 정직성 감사 P0 — 화면이 **거짓을 말하던** 조합들
// ─────────────────────────────────────────────────────────────────────────────

describe('판정 거짓 — 근거 없이 단정하지 않는다', () => {
  it('F3: 같은 입력인데 기대값이 다르면 "유지"가 아니다', () => {
    // 문서는 r=0x9, 생성기는 r=0x0을 말한다. 셀은 변경 화살표를 그리는데 판정이 '유지'면
    // 한 행이 "고치지 마라"와 "0x9를 0x0으로 고쳐라"를 동시에 말하는 자기모순이 된다.
    const r = reconcileSuts({
      docRows: [{ tc_id: 'UT001', inputs: { a: '0x0', b: '0x1' }, expected: { r: '0x9' } }],
      docColumns: { inputs: ['a', 'b'], expected: ['r'] },
      genSeqs: [{ strategy: 'BV_MIN', inputs: { a: '0x0' }, expected: { r: '0x0' } }],
      varTypes: { a: { type: 'U16' } },
    });
    expect(r.rows[0].verdict).toBe(VERDICT.UNKNOWN);
    expect(r.rows[0].note).toMatch(/기대값 상이\(문서 0x9 \/ 추론 0x0\)/);
  });

  it('F3: 비교한 변수가 원문 입력보다 적으면 근거 폭을 밝힌다', () => {
    const r = reconcileSuts({
      docRows: [{ tc_id: 'UT001', inputs: { a: '0x0', b: '0x1', c: '0x2' }, expected: {} }],
      docColumns: { inputs: ['a', 'b', 'c'], expected: [] },
      genSeqs: [{ strategy: 'BV_MIN', inputs: { a: '0x0' }, expected: {} }],
      varTypes: { a: { type: 'U16' } },
    });
    expect(r.rows[0].note).toMatch(/입력 3개 중 1개만 비교 — 동일 TC 여부 미확정/);
  });

  it('F5: 원문 값이 비수치면 "문서에 없다"로 단정하지 않는다', () => {
    // ENUM/상태 토큰은 경계값과 대조가 불가능하다. 이걸 부재로 읽으면 이미 커버된 케이스를
    // 중복 작성하라는 지시가 된다.
    const r = reconcileSuts({
      docRows: [{ tc_id: 'UT001', inputs: { st: 'ACTIVE' }, expected: {} }],
      docColumns: { inputs: ['st'], expected: [] },
      varTypes: { st: { type: 'uint8_t', source: 'name_pattern' } },
    });
    expect(r.rows.length).toBeGreaterThan(0);
    expect(r.rows.every((x) => x.verdict === VERDICT.UNKNOWN)).toBe(true);
    expect(r.rows[0].note).toMatch(/원문 값이 비수치 — 경계 커버 여부 대조 불가/);
    expect(r.rows.some((x) => x.verdict === VERDICT.ADD)).toBe(false);
  });

  it('F5: 원문이 수치면 종전대로 유지/신규추가 판정(과잉 보류 아님)', () => {
    const r = reconcileSuts({
      docRows: [{ tc_id: 'UT001', inputs: { u16_v: '0x0' }, expected: {} }],
      docColumns: { inputs: ['u16_v'], expected: [] },
      varTypes: { u16_v: { type: 'U16' } },
    });
    expect(r.rows.find((x) => x.boundary === 'MIN').verdict).toBe(VERDICT.KEEP);
    expect(r.rows.find((x) => x.boundary === 'MAX').verdict).toBe(VERDICT.ADD);
  });

  it('F4: SITS 원문이 일부만 파싱돼도 나머지를 "신규추가"로 단정하지 않는다', () => {
    const r = reconcileSits({
      docTcs: [
        { tc_id: 'IT001', sub_cases: [{ inputs: { rpm: '0x0' }, expected: {} }] },
        { tc_id: 'IT002', sub_cases: [] },     // 폴백 shape — 미파싱
      ],
      gen: { call_chain: 'a -> b', sub_cases: [{ case_label: 'max', inputs: { rpm: '0xFFFF' }, expected: {} }] },
      varTypes: {},
    });
    expect(r.docPartial).toBe(true);
    expect(r.rows[0].verdict).toBe(VERDICT.UNKNOWN);
    expect(r.rows[0].note).toMatch(/원문 TC 2건 중 1건 미파싱/);
  });

  it('F4: sub_total보다 적게 로드된 경우도 불완전으로 본다', () => {
    const r = reconcileSits({
      docTcs: [{ tc_id: 'IT001', sub_total: 9, sub_cases: [{ inputs: { rpm: '0x0' }, expected: {} }] }],
      gen: { call_chain: 'a -> b', sub_cases: [{ case_label: 'max', inputs: { rpm: '0xFFFF' }, expected: {} }] },
      varTypes: {},
    });
    expect(r.docPartial).toBe(true);
    expect(r.rows[0].note).toMatch(/서브케이스 일부만 로드/);
    // 절단 전 총량이 배너 근거가 된다(예전엔 docShown과 같아 배너가 구조적으로 안 떴다)
    expect(r.totals.docTotal).toBe(9);
    expect(r.totals.docShown).toBe(1);
  });

  it('F4: 원문이 완전하면 종전대로 신규추가(과잉 보류 아님)', () => {
    const r = reconcileSits({
      docTcs: [{ tc_id: 'IT001', sub_total: 1, sub_cases: [{ inputs: { rpm: '0x0' }, expected: {} }] }],
      gen: { call_chain: 'a -> b', sub_cases: [{ case_label: 'max', inputs: { rpm: '0xFFFF' }, expected: {} }] },
      varTypes: {},
    });
    expect(r.docPartial).toBe(false);
    expect(r.rows[0].verdict).toBe(VERDICT.ADD);
  });

  it('S1: SITS 생성기 절단(total/truncated)을 payload에서 읽어 노출 가능하게 한다', () => {
    const r = reconcileSits({
      docTcs: [],
      gen: { call_chain: 'a -> b', total: 14, truncated: true,
        sub_cases: [{ case_label: 'c1', inputs: { rpm: 0 }, expected: {} }] },
      varTypes: {},
    });
    expect(r.genTotal).toBe(14);
    expect(r.genTruncated).toBe(true);
  });
});

describe('판정 보류가 과잉이 아닌지 — 정상 케이스 오염 방지', () => {
  it('일부 행만 비수치면 나머지 수치 행으로 대조한다(보류 아님)', () => {
    // ⚠ 회귀 가드: "한 행이라도 텍스트면 대조 불가"로 하면 8행 중 1행만 'N/A'인 흔한 경우에
    // 정당한 '신규추가' 제안이 통째로 사라진다(실측 3행 중 2행 소실).
    const docRows = Array.from({ length: 8 }, (_v, i) => ({
      tc_id: `T${i}`, inputs: { v: i === 3 ? 'N/A' : `0x${i}` }, expected: {},
    }));
    const r = reconcileSuts({ docRows, docColumns: { inputs: ['v'], expected: [] }, varTypes: { v: { type: 'U16' } } });
    expect(r.rows.some((x) => x.verdict === VERDICT.UNKNOWN)).toBe(false);
    expect(r.rows.find((x) => x.boundary === 'MIN').verdict).toBe(VERDICT.KEEP);   // 0x0 존재
    expect(r.rows.find((x) => x.boundary === 'MAX').verdict).toBe(VERDICT.ADD);    // 0xFFFF 없음
  });

  it('전 행이 비수치(진짜 ENUM)일 때만 대조 불가', () => {
    const r = reconcileSuts({
      docRows: [{ tc_id: 'T1', inputs: { st: 'ACTIVE' }, expected: {} },
        { tc_id: 'T2', inputs: { st: 'IDLE' }, expected: {} }],
      docColumns: { inputs: ['st'], expected: [] },
      varTypes: { st: { type: 'uint8_t' } },
    });
    expect(r.rows.every((x) => x.verdict === VERDICT.UNKNOWN)).toBe(true);
  });

  it('생성기 기대값이 [검증 필요] 마커면 기대값 충돌로 보지 않는다', () => {
    // 마커는 비수치라 sameValue가 null → 충돌 아님. 이걸 충돌로 치면 생성기 산출 대부분이
    // 검증필요로 뒤집혀 기능이 무용해진다.
    const r = reconcileSuts({
      docRows: [{ tc_id: 'T1', inputs: { x: '0x0' }, expected: { r: '0x5' } }],
      docColumns: { inputs: ['x'], expected: ['r'] },
      genSeqs: [{ strategy: 'BV_MIN', inputs: { x: '0x0' }, expected: { r: '[검증 필요] 3276' } }],
      varTypes: { x: { type: 'U16' } },
    });
    expect(r.rows[0].verdict).toBe(VERDICT.KEEP);
  });
});

describe('절단 축 분리 — 기대 축 절단이 판정을 뒤집지 않는다', () => {
  // ⚠ 회귀 가드(deep-review C4): 백엔드 `kv_truncated`는 inputs **또는** expected 중 하나만
  // 넘쳐도 켜진다. SUTS 템플릿의 Expected 열은 최대 86개라 기대 축은 거의 항상 절단되는데,
  // 그걸로 판정을 뒤집으면 **입력이 완전 대조인 행까지** 검증필요가 되어 판정 열이 붕괴하고
  // "8개 중 8개만 대조"라는 자기모순 노트가 뜬다(실측).
  const inputs = Object.fromEntries(Array.from({ length: 8 }, (_v, i) => [`in${i}`, `0x${i}`]));
  const expected = Object.fromEntries(Array.from({ length: 12 }, (_v, i) => [`ex${i}`, `0x${i}`]));

  it('기대 축만 잘렸으면 판정 유지 + 표시 한계만 노트', () => {
    const r = reconcileSuts({
      docRows: [{ tc_id: 'T1', inputs, expected, kv_truncated: true, kv_total: { inputs: 8, expected: 30 } }],
      docColumns: { inputs: Object.keys(inputs), expected: Object.keys(expected) },
      genSeqs: [{ strategy: 'BV_MIN', inputs, expected }],
      varTypes: {},
    });
    expect(r.rows[0].verdict).toBe(VERDICT.KEEP);
    expect(r.rows[0].note).toMatch(/기대값 30개 중 12개만 표시/);
    expect(r.rows[0].note).not.toMatch(/단정 불가/);
  });

  it('입력 축이 잘렸으면 종전대로 판정 보류', () => {
    const r = reconcileSuts({
      docRows: [{ tc_id: 'T1', inputs, expected, kv_truncated: true, kv_total: { inputs: 40, expected: 12 } }],
      docColumns: { inputs: Object.keys(inputs), expected: Object.keys(expected) },
      genSeqs: [{ strategy: 'BV_MIN', inputs, expected }],
      varTypes: {},
    });
    expect(r.rows[0].verdict).toBe(VERDICT.UNKNOWN);
    expect(r.rows[0].note).toMatch(/원문 입력 40개 중 8개만 대조/);
  });

  it('kv_total이 없는 구 job은 안전측(입력 절단)으로 본다', () => {
    const r = reconcileSuts({
      docRows: [{ tc_id: 'T1', inputs, expected: {}, kv_truncated: true }],
      docColumns: { inputs: Object.keys(inputs), expected: [] },
      genSeqs: [{ strategy: 'BV_MIN', inputs, expected: {} }],
      varTypes: {},
    });
    expect(r.rows[0].verdict).toBe(VERDICT.UNKNOWN);
  });

  it('SITS도 같은 축 분리를 쓴다(SUTS만 고치는 비대칭 금지)', () => {
    const r = reconcileSits({
      docTcs: [{ tc_id: 'IT1', sub_total: 1, sub_cases: [{ inputs: { rpm: '0x0' }, expected: {},
        kv_truncated: true, kv_total: { inputs: 1, expected: 30 } }] }],
      gen: { call_chain: 'a -> b', sub_cases: [{ case_label: 'c', inputs: { rpm: '0x0' }, expected: {} }] },
      varTypes: {},
    });
    expect(r.rows[0].verdict).toBe(VERDICT.KEEP);   // 기대 축만 절단 → 판정 유지
  });
});
