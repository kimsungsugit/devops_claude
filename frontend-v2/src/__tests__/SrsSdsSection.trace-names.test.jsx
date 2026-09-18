/**
 * SrsSdsSection — SDS 이름 대조(라운드113) 렌더 계약 테스트
 *
 * 왜 필요한가: 이 기능의 Critical 2건이 백엔드 단위테스트 7개를 **전부 통과하고 살아남았다**.
 *   C1 표시 캡이 임의의 N개를 조용히 고름(총량 미표기)
 *   C2 필드 부재(구 응답·구 저장분)를 "이름 미발견"이라는 **단정**으로 렌더 → 626행 거짓 음성
 * 둘 다 표시 계층 결함이라 컴포넌트 렌더로만 잡힌다. traceMatrixStore.test.js 는 순수 함수만,
 * test_traceability_sds_bridge.py 는 백엔드 집계만 덮는다.
 *
 * 고정하는 계약:
 *  ① 4상태 렌더 — △(요구ID 연결) / ≈(이름만 일치) / '이름 미발견'(조회했고 없음) / —(미계산)
 *  ② 절단 표면화 — 캡 초과 시 '+N'
 *  ③ 중립 채널 — 이름일치는 설계 공백이 아니므로 amber/red 금지
 *  ④ CSV 열 정렬 불변식 — 헤더 필드 수 == 각 데이터 행 필드 수(전 열 밀림 방지)
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clearTraceMatrix, saveTraceMatrix } from '../traceMatrixStore.js';

const mockToast = vi.fn();

vi.mock('../App.jsx', () => ({
  useJenkinsCfg: () => ({
    cfg: { baseUrl: 'http://jenkins', username: 'u', token: 't', cacheRoot: '.cache' },
    update: vi.fn(),
  }),
  useToast: () => mockToast,
}));

vi.mock('../api.js', () => ({
  api: vi.fn(async () => ({})),
  post: vi.fn(async () => ({})),
  getUsername: vi.fn(() => 'tester'),
  authHeaders: vi.fn(() => ({})),
  buildUrl: vi.fn((p) => p),
  defaultCacheRoot: vi.fn(() => '.cache'),
}));

const { default: SrsSdsSection } = await import('../components/sections/SrsSdsSection.jsx');

const JOB = { name: 'test-job', url: 'http://jenkins/job/test-job/' };
const LINKED = { srs: 'S.docx', sds: 'D.docx', hsis: 'H.xlsx', sts: 'T.xlsm', suts: 'U.xlsm' };
const SCM = { id: 'scm-1', name: 'MyRepo', source_root: '', linked_docs: LINKED };

// 컴포넌트 buildCacheKey/buildBinding 과 동일 SHAPE 미러링(어긋나면 shape drift 를 잡아준다).
const keyOf = () => JSON.stringify({
  srs: LINKED.srs, sds: LINKED.sds, hsis: LINKED.hsis,
  jobUrl: JOB.url, sourceRoot: '',
  sts: LINKED.sts, suts: LINKED.suts, sits: '', syts: '', syits: '',
  vcast: '',
});
const bindingOf = () => JSON.stringify({
  jobUrl: JOB.url, sourceRoot: '', srs: LINKED.srs, sds: LINKED.sds, hsis: LINKED.hsis,
});

const mkResult = (over = {}) => ({
  cacheRoot: '.cache',
  jobUrl: JOB.url,
  scmList: [SCM],
  matchedScm: SCM,
  matchedScmSource: 'manual',
  reportData: {},
  impactData: null,
  ...over,
});

/** 미추적 항목 1건. over 로 SDS 이름 대조 필드를 갈아끼운다. */
const mkUnmapped = (over = {}) => ({
  subprogram: 'SwUFn_0200',
  result: 'pass',
  testcase: 't1',
  unit: '',
  resolved_funcs: ['g_drift_fn'],
  category: 'suts_tested',
  sds_reqs: [],
  uds_funcs: [],
  in_uds: false,
  safety: false,
  layer: 'APP_LEAF',
  sds_name_hits: [],
  sds_name_hits_total: 0,
  sds_name_match: '',
  sds_name_ambiguous: false,
  ...over,
});

// 매트릭스가 렌더되려면 요구사항 행이 최소 1개 있어야 한다(없으면 'SRS 경로를 확인하세요' 안내로 대체).
// 배열 필드는 컴포넌트가 .map 하므로 전부 채워 둔다.
const mkRow = () => ({
  requirement_id: 'SwTR_0101', requirement_name: 'R1', asil: 'A', confidence: 'low',
  sds_components: [], sds_functions: [], hsis_signals: [],
  source_ids: [], source_ids_direct: [],
  tests: [], test_ids: [], sts_tests: [], suts_tests: [], sits_tests: [],
  syts_tests: [], syits_tests: [], syrs_parents: [],
  test_count: 0, pass_count: 0, fail_count: 0, vcast_count: 0,
  sts_count: 0, suts_count: 0, sits_count: 0, syts_count: 0, syits_count: 0,
  sts_direct: 0, suts_direct: 0, suts_indirect: 0, sits_direct: 0, sits_indirect: 0,
});

const mkMatrix = (unmapped, summary = {}) => ({
  rows: [mkRow()],
  summary: {
    vcast_input_rows: 1, vcast_traced_rows: 0, unmapped_vcast_count: unmapped.length,
    unmapped_layer_app_leaf: unmapped.length,
    ...summary,
  },
  unmapped_vcast: unmapped,
});

/** 복원 렌더 → 트리 뷰 → '역추적 안 된 시험 함수 표시' 체크 → 미추적 루트·버킷 expand. */
async function openUnmappedTable(matrix) {
  saveTraceMatrix(keyOf(), bindingOf(), matrix);
  const view = render(<SrsSdsSection job={JOB} analysisResult={mkResult()} />);
  await screen.findByText(/💾\s*저장된 결과/);
  fireEvent.click(screen.getByTitle('ID 기준 추적성 트리 보기'));
  // label 이 input 을 감싸므로 checkbox 를 직접 집는다(라벨 텍스트에 개수가 붙어 정규식 불안정).
  const cb = view.container.querySelector('input[type="checkbox"]');
  expect(cb).toBeTruthy();
  fireEvent.click(cb);
  // 미추적 루트 → 의미 버킷 순으로 펼친다(표는 버킷 내부에 있다).
  fireEvent.click(await screen.findByText(/시험은 했으나 이 SRS 요구사항에 안 닿는/));
  fireEvent.click(await screen.findByText(/단위시험까지 한 미추적 함수/));
  return view;
}

describe('SrsSdsSection — SDS 이름 대조 표시 계약', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearTraceMatrix();
    localStorage.clear();
  });

  it('요구ID까지 연결되면 △ 로 표기한다(기존 동작 불변)', async () => {
    await openUnmappedTable(mkMatrix([mkUnmapped({ sds_reqs: ['SWST_08'] })]));
    expect(await screen.findByText(/△\s*SWST_08/)).toBeInTheDocument();
  });

  it('이름만 일치하면 ≈ + 티어 라벨로 표기하고 설계 공백 색을 쓰지 않는다', async () => {
    await openUnmappedTable(mkMatrix([mkUnmapped({
      sds_name_hits: ['s_drift_fn'], sds_name_hits_total: 1, sds_name_match: 'ret_prefix',
    })]));
    const cell = (await screen.findByText(/≈\s*s_drift_fn/)).closest('td');
    expect(cell).toBeTruthy();
    // 티어를 표시 표면에 노출한다(백엔드 '티어 항상 노출' 계약).
    expect(cell.textContent).toMatch(/반환형 접두사 차이/);
    // 중립색 — red(uncovered)·amber(partial) 계열이면 설계 공백으로 오인된다.
    expect(cell.getAttribute('style')).toMatch(/var\(--text-muted\)/);
  });

  it('core 티어는 ambiguous 가 아니어도 "별개 함수일 수 있음" 헤지를 붙인다', async () => {
    // s_ ↔ g_ 는 헝가리안 규약상 다른 객체일 개연이 높아, 단일 히트일수록 오히려 위험하다.
    await openUnmappedTable(mkMatrix([mkUnmapped({
      sds_name_hits: ['g_drift_fn'], sds_name_hits_total: 1,
      sds_name_match: 'core', sds_name_ambiguous: false,
    })]));
    const cell = (await screen.findByText(/≈\s*g_drift_fn/)).closest('td');
    expect(cell.getAttribute('title')).toMatch(/별개 함수일 수 있음/);
  });

  it('표시 캡을 넘으면 +N 으로 절단을 표면화한다(침묵 절단 금지)', async () => {
    await openUnmappedTable(mkMatrix([mkUnmapped({
      sds_name_hits: ['a_1', 'a_2', 'a_3', 'a_4', 'a_5', 'a_6', 'a_7', 'a_8'],
      sds_name_hits_total: 11, sds_name_match: 'core', sds_name_ambiguous: true,
    })]));
    const cell = (await screen.findByText(/≈\s*a_1/)).closest('td');
    expect(cell.textContent).toMatch(/\+3/);   // 11 − 8
  });

  it('조회했고 없으면 "이름 미발견"으로 표기한다', async () => {
    await openUnmappedTable(mkMatrix([mkUnmapped({ sds_name_hits: [] })]));
    expect(await screen.findByText('이름 미발견')).toBeInTheDocument();
  });

  it('★C2 pin: 필드가 없으면(구 응답·구 저장분) 단정 대신 중립 — 로 표기한다', async () => {
    // 계산이 돌지 않은 상태를 '못 찾았다'로 렌더하면 전 행이 거짓 음성이 된다. 배포 직후
    // 구 localStorage 복원 경로에서 반드시 밟히므로(STORE_VERSION 유지) 이 pin 이 필수다.
    const legacy = mkUnmapped();
    delete legacy.sds_name_hits;
    delete legacy.sds_name_hits_total;
    delete legacy.sds_name_match;
    delete legacy.sds_name_ambiguous;
    await openUnmappedTable(mkMatrix([legacy]));
    expect(screen.queryByText('이름 미발견')).not.toBeInTheDocument();
    const dash = screen.getAllByTitle(/SDS 이름 대조 정보 없음/);
    expect(dash.length).toBeGreaterThan(0);
    expect(dash[0].textContent).toBe('—');
  });

  it('뱃지는 variant 가 있을 때만 뜨고 중립색이며 SDS부분 뱃지와 상호배타다', async () => {
    await openUnmappedTable(mkMatrix([
      mkUnmapped({ subprogram: 'SwUFn_0201', sds_name_hits: ['s_x'], sds_name_hits_total: 1, sds_name_match: 'ret_prefix' }),
      mkUnmapped({ subprogram: 'SwUFn_0202', sds_reqs: ['SWST_08'], sds_name_hits: ['bar'], sds_name_hits_total: 1, sds_name_match: 'exact' }),
    ], { unmapped_vcast_count: 2, unmapped_layer_app_leaf: 2 }));
    const badge = await screen.findByText(/1 SDS이름일치/);
    expect(badge.getAttribute('style')).toMatch(/var\(--text-muted\)/);
    // sds_reqs 가 있는 항목은 SDS부분 쪽에만 세어져야 한다(같은 항목 이중 계상 금지).
    expect(screen.getByText(/1 SDS부분/)).toBeInTheDocument();
  });

  it('CSV 미추적 섹션의 헤더 필드 수와 데이터 행 필드 수가 일치한다(전 열 밀림 방지)', async () => {
    const captured = [];
    const origCreate = URL.createObjectURL;
    URL.createObjectURL = vi.fn(() => 'blob:mock');
    const origBlob = global.Blob;
    global.Blob = class {
      constructor(parts) { captured.push(String(parts.join(''))); }
    };
    try {
      saveTraceMatrix(keyOf(), bindingOf(), mkMatrix([
        mkUnmapped({ sds_name_hits: ['s_x'], sds_name_hits_total: 3, sds_name_match: 'core', sds_name_ambiguous: true }),
        mkUnmapped({ subprogram: 'SwUFn_0202', sds_reqs: ['SWST_08'] }),
      ], { unmapped_vcast_count: 2, unmapped_layer_app_leaf: 2 }));
      render(<SrsSdsSection job={JOB} analysisResult={mkResult()} />);
      await screen.findByText(/💾\s*저장된 결과/);
      fireEvent.click(screen.getByTitle('CSV 내보내기'));

      expect(captured.length).toBeGreaterThan(0);
      const lines = captured[0].split('\n');
      const hi = lines.findIndex(l => l.startsWith('Subprogram,'));
      expect(hi).toBeGreaterThan(-1);
      const nHeader = lines[hi].split(',').length;
      // 헤더 다음 줄부터 미추적 데이터 행(빈 줄/다음 섹션 전까지)
      for (let i = hi + 1; i < lines.length && lines[i].trim() && !lines[i].startsWith('#'); i++) {
        expect(lines[i].split(',').length).toBe(nHeader);
      }
      // 이름일치 열이 티어와 절단 총량을 싣는다
      expect(captured[0]).toMatch(/core: s_x \+2/);
    } finally {
      URL.createObjectURL = origCreate;
      global.Blob = origBlob;
    }
  });
});
