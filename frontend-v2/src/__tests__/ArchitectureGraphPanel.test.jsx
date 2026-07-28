/** ArchitectureGraphPanel — 층위 배치(순수)·사이클 강조·드릴다운·히트맵·정직 각주. */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockResp;

vi.mock('../api.js', () => ({
  post: vi.fn(() => (mockResp instanceof Error ? Promise.reject(mockResp) : Promise.resolve(mockResp))),
}));

import ArchitectureGraphPanel from '../components/sections/ArchitectureGraphPanel.jsx';
// ⚠ archMetricsCache 는 모듈 레벨 싱글톤이다 — 비우지 않으면 첫 테스트의 응답이
//   같은 (jobUrl, cacheRoot) 키로 뒤 테스트에 그대로 재사용된다(격리 오염).
import { clearArchMetricsCache } from '../archMetricsCache.js';
import { layoutModules } from '../components/archGraphLayout.js';

const METRICS = {
  ok: true, available: true, build_number: 125,
  snapshot: { files: 3, functions: 10, parser_engine: 'tree-sitter' },
  hotspots: [
    { function: 'hub', file: 'APP/a.c', fan_in: 5, complexity: 12, complexity_source: 'vcast_ccn', score: 60 },
    { function: 'big', file: 'APP/b.c', fan_in: 2, complexity: 200, complexity_source: 'loc_proxy', score: 40 },
  ],
  module_graph: {
    nodes: [
      { module: 'APP', files: 2, functions: 6 },
      { module: 'LIB', files: 1, functions: 3 },
      { module: 'IF', files: 1, functions: 1 },
    ],
    edges: [
      { from: 'APP', to: 'LIB', calls: 4 },
      { from: 'LIB', to: 'APP', calls: 1 },
      { from: 'APP', to: 'IF', calls: 2 },
    ],
    truncated: false,
  },
  cycles: {
    file_sccs: [{ files: ['APP/a.c', 'LIB/u.c'], size: 2 }],
    module_sccs: [{ modules: ['APP', 'LIB'], size: 2 }],
    mutual_file_pairs: [{ a: 'APP/a.c', b: 'LIB/u.c', a_to_b: 4, b_to_a: 1 }],
  },
  refactor_candidates: [
    { kind: 'god_file', file: 'APP/a.c', functions: 20, lines: 900, in_files: 3, out_files: 2,
      basis: '함수 20개 · 본문 900줄 · 유입 3파일 · 유출 2파일' },
  ],
  // v5(O3): 모듈 → 파일 드릴다운 재료
  file_graph: {
    nodes: [
      { file: 'APP/a.c', module: 'APP', functions: 4, lines: 900 },
      { file: 'APP/b.c', module: 'APP', functions: 2, lines: 120 },
      { file: 'LIB/u.c', module: 'LIB', functions: 3, lines: 60 },
      { file: 'IF/i.c', module: 'IF', functions: 1, lines: 20 },
    ],
    edges: [
      { from: 'APP/a.c', to: 'APP/b.c', calls: 3 },
      { from: 'APP/b.c', to: 'APP/a.c', calls: 1 },   // 상호 호출
      { from: 'APP/a.c', to: 'LIB/u.c', calls: 4 },   // 외부 유출
      { from: 'LIB/u.c', to: 'APP/a.c', calls: 1 },   // 외부 유입
      { from: 'APP/a.c', to: 'IF/i.c', calls: 2 },
    ],
    truncated: false, total_files: 4, total_edges: 5,
  },
};

const PROPS = { jobUrl: 'http://j/', cacheRoot: '' };

describe('layoutModules (순수)', () => {
  it('SCC 멤버는 같은 레이어(응축), 비순환 후속 모듈은 다음 레이어', () => {
    const L = layoutModules(METRICS.module_graph, METRICS.cycles);
    expect(L.pos.APP.x).toBe(L.pos.LIB.x);            // 사이클 멤버 동일 컬럼
    expect(L.pos.IF.x).toBeGreaterThan(L.pos.APP.x);  // APP→IF는 다음 레이어
    expect(L.cycleModules.has('APP') && L.cycleModules.has('LIB')).toBe(true);
    expect(L.cycleEdges.has('APP→LIB') && L.cycleEdges.has('LIB→APP')).toBe(true);
    expect(L.cycleEdges.has('APP→IF')).toBe(false);
    expect(L.width).toBeGreaterThan(0);
    expect(L.height).toBeGreaterThan(0);
  });

  it('빈 그래프 — 예외 없이 빈 배치', () => {
    const L = layoutModules({ nodes: [], edges: [] }, { module_sccs: [] });
    expect(Object.keys(L.pos)).toHaveLength(0);
  });
});

describe('ArchitectureGraphPanel', () => {
  beforeEach(() => {
    clearArchMetricsCache();
    vi.clearAllMocks();
    mockResp = METRICS;
  });

  it('다이어그램·사이클 강조·개선 후보·정직 각주를 렌더한다', async () => {
    render(<ArchitectureGraphPanel {...PROPS} />);
    expect(await screen.findByRole('img', { name: '모듈 의존 다이어그램' })).toBeInTheDocument();
    // 사이클 참여 모듈은 aria-label에 명시(색 외 접근 수단)
    expect(screen.getByRole('button', { name: /모듈 APP.*순환 의존 참여/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /모듈 IF(?!.*순환)/ })).toBeInTheDocument();
    // 순환 목록은 표다 — 크기 열 + 파일명(전체 경로는 title). 예전엔 전체 경로를
    // `↔` 로 이어 붙인 한 줄이라 8파일 순환이 세 줄로 접혔다.
    // ⚠ 파일명·title 은 상호 호출 표에도 나온다 — SCC 표로 범위를 좁힌다
    const sccTable = screen.getByRole('columnheader', { name: '순환에 묶인 파일' }).closest('table');
    expect(within(sccTable).getByTitle('APP/a.c')).toBeInTheDocument();
    expect(within(sccTable).getByTitle('LIB/u.c')).toBeInTheDocument();
    expect(sccTable).toHaveTextContent('a.c');
    expect(sccTable).toHaveTextContent('u.c');
    // 상호 호출은 별도 표(A→B / B→A 를 열로 분리 — 예전엔 '4회 · 1회' 한 문장이었다)
    const mutualTable = screen.getByRole('columnheader', { name: 'A→B' }).closest('table');
    expect(within(mutualTable).getByText('4')).toBeInTheDocument();
    expect(within(mutualTable).getByText('1')).toBeInTheDocument();
    // 개선 후보(결정론 basis)
    expect(screen.getByText(/집중 파일/)).toBeInTheDocument();
    expect(screen.getByText(/함수 20개 · 본문 900줄/)).toBeInTheDocument();
    // 정직 각주 — 관계 기반·모듈 프록시·파서 엔진
    expect(screen.getByText(/관계=함수 호출 기반\(include 미분석\)/)).toBeInTheDocument();
    expect(screen.getByText(/tree-sitter/)).toBeInTheDocument();
  });

  it('노드 클릭 → 드릴다운(in/out 엣지 + 순환 표기)', async () => {
    render(<ArchitectureGraphPanel {...PROPS} />);
    await screen.findByRole('img', { name: '모듈 의존 다이어그램' });
    await userEvent.click(screen.getByRole('button', { name: /모듈 APP/ }));
    expect(screen.getByText('APP — 연결 관계')).toBeInTheDocument();
    // ^앵커 — SVG 엣지 <title>("APP → IF · …")과의 중복 매치 방지(드릴다운 행은 →/←로 시작)
    expect(screen.getByText(/^→ LIB · 호출 4회 · 순환 참여$/)).toBeInTheDocument();
    expect(screen.getByText(/^← LIB · 호출 1회 · 순환 참여$/)).toBeInTheDocument();
    expect(screen.getByText(/^→ IF · 호출 2회$/)).toBeInTheDocument();
  });

  // ── O3: 모듈 → 파일 드릴다운 ──
  it('모듈 클릭 → 내부 파일 목록 + 파일 간 호출(상호 표기) + 외부 유출입', async () => {
    render(<ArchitectureGraphPanel {...PROPS} />);
    await screen.findByRole('img', { name: '모듈 의존 다이어그램' });
    await userEvent.click(screen.getByRole('button', { name: /모듈 APP/ }));

    // 모듈이 2세그먼트 프록시로 접은 파일을 펼친다
    // ⚠ 파일명은 순환 표에도 나온다 — 드릴다운 래퍼로 범위를 좁힌다
    const drill = screen.getByText(/내부 파일 2개 · 파일 간 호출 2건/).parentElement;
    expect(within(drill).getByTitle('APP/a.c')).toBeInTheDocument();
    expect(within(drill).getByTitle('APP/b.c')).toBeInTheDocument();
    // 양방향은 ⚠상호로 표기(2-사이클 = 리팩토링 신호)
    expect(screen.getAllByText(/⚠상호/).length).toBeGreaterThanOrEqual(1);
    // 모듈 경계를 넘는 호출은 유출/유입으로 집계(LIB 4회 나가고 1회 들어옴, IF 2회 나감)
    expect(screen.getByText(/외부 유출: →LIB 4 · →IF 2/)).toBeInTheDocument();
    expect(screen.getByText(/유입: ←LIB 1/)).toBeInTheDocument();
  });

  it('file_graph 부재(구 캐시) — 정직 안내로 폴백', async () => {
    mockResp = { ...METRICS, file_graph: undefined };
    render(<ArchitectureGraphPanel {...PROPS} />);
    await screen.findByRole('img', { name: '모듈 의존 다이어그램' });
    await userEvent.click(screen.getByRole('button', { name: /모듈 APP/ }));
    expect(screen.getByText(/파일 단위 데이터가 이 응답에 없습니다/)).toBeInTheDocument();
  });

  it('핫스팟 산포에 함수 라벨을 붙인다(전폭 배치)', async () => {
    render(<ArchitectureGraphPanel {...PROPS} />);
    await screen.findByRole('img', { name: '핫스팟 산포도' });
    expect(screen.getByText('hub')).toBeInTheDocument();
    expect(screen.getByText('big')).toBeInTheDocument();
  });

  it('사이클 0건 — "관측 없음" 명시(침묵 생략 금지)', async () => {
    mockResp = {
      ...METRICS,
      cycles: { file_sccs: [], module_sccs: [], mutual_file_pairs: [] },
      refactor_candidates: [],
    };
    render(<ArchitectureGraphPanel {...PROPS} />);
    expect(await screen.findByText(/순환 의존 관측 없음/)).toBeInTheDocument();
    expect(screen.getByText(/임계를 넘는 후보 관측 없음/)).toBeInTheDocument();
  });

  it('available:false reason 렌더', async () => {
    mockResp = { ok: true, available: false, reason: 'no_source_snapshot' };
    render(<ArchitectureGraphPanel {...PROPS} />);
    expect(await screen.findByText(/소스 스냅샷이 없어 다이어그램을 만들 수 없습니다/)).toBeInTheDocument();
  });
});

// ── Q2: 계층 다이어그램 · DSM · 전역 데이터 흐름 ──
describe('ArchitectureGraphPanel — Q2 신규 다이어그램', () => {
  const Q2 = {
    ...METRICS,
    layer_graph: {
      available: true,
      nodes: [
        { layer: 'APP_LEAF', label: 'APP (응용)', rank: 3, functions: 591 },
        { layer: 'BSW_DRIVER', label: 'BSW (드라이버)', rank: 2, functions: 192 },
        { layer: 'LIB_UTIL', label: 'LIB (유틸)', rank: 1, functions: 49 },
      ],
      edges: [
        { from: 'APP_LEAF', to: 'BSW_DRIVER', calls: 64, reverse: false },
        { from: 'BSW_DRIVER', to: 'APP_LEAF', calls: 59, reverse: true },
      ],
      reverse_total: 87, reverse_pairs_omitted: 57,
      reverse_pairs: [{ caller: 'PE_Initialize_Core', caller_layer: 'BSW_DRIVER', caller_file: 'BSW/pe.c',
                        callee: 'BATS_Init', callee_layer: 'APP_LEAF', callee_file: 'APP/bats.c' }],
      excluded_test_artifact: 0, unclassifiable: 0,
      note: '계층은 **함수명 휴리스틱**으로 추정한 값이며 선언된 아키텍처가 아니다 — 역방향 호출은 위반이 아니라 검토 후보다.',
    },
    file_graph: {
      ...METRICS.file_graph,
      // b.c → a.c 는 위상순(a,b,…)에서 위로 되돌아가는 호출 = 순환
      topo_order: ['APP/a.c', 'APP/b.c', 'LIB/u.c', 'IF/i.c'],
    },
    global_coupling: {
      available: true, distinct_globals: 586, cross_module_globals: 1, functions_using_globals: 413,
      top: [{ global: 'g_shared', functions: 39, modules: 2, files: 3, module_names: ['APP', 'LIB'],
              functions_sample: ['hi_fn', 'lo_fn'], functions_omitted: 37 }],
      note: '파서는 읽기/쓰기를 구분하지 않는다 — 사용(참조) 기준이다.',
    },
  };

  beforeEach(() => { clearArchMetricsCache(); vi.clearAllMocks(); mockResp = Q2; });

  // 계층 다이어그램·전역 흐름은 사용자 결정으로 숨김(SHOW 플래그) — 그림만 접었고 데이터 축은
  // 아키텍처 메트릭 요약 스트립과 개선 제안 후보에 그대로 살아 있다.
  it('계층 다이어그램은 숨김 상태다', async () => {
    render(<ArchitectureGraphPanel {...PROPS} />);
    await screen.findByRole('img', { name: '모듈 의존 다이어그램' });
    expect(screen.queryByRole('img', { name: '계층 다이어그램' })).toBeNull();
    expect(screen.queryByText('APP (응용)')).toBeNull();
    expect(screen.queryByRole('button', { name: '함수 쌍 보기' })).toBeNull();
  });

  it('구조 개선 후보를 목록이 아니라 표로 낸다', async () => {
    // 종류/대상/근거 세 축을 한 줄 문장으로 이어 붙이면 눈이 축을 못 잡는다.
    render(<ArchitectureGraphPanel {...PROPS} />);
    await screen.findByRole('img', { name: '모듈 의존 다이어그램' });
    expect(screen.getByRole('columnheader', { name: '종류' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '대상' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: '근거' })).toBeInTheDocument();
  });

  it('DSM — 위상순에서 역행 셀(순환)을 붉게 세고 정렬을 토글한다', async () => {
    render(<ArchitectureGraphPanel {...PROPS} />);
    // topo_order [a,b,u,i] 기준 위로 되돌아가는 호출 2건: b.c→a.c, u.c→a.c (절단 없음)
    expect(await screen.findByText(/붉은 셀이 순환/)).toBeInTheDocument();
    expect(screen.getByText(/2건/)).toBeInTheDocument();
    expect(screen.queryByText(/전체 .*건/)).toBeNull();   // 절단이 없으면 '전체' 병기 안 함
    await userEvent.click(screen.getByRole('button', { name: '위상순' }));
    expect(screen.getByRole('button', { name: '이름순' })).toBeInTheDocument();
    expect(screen.queryByText(/이 순환/)).toBeNull();                            // 이름순이면 순환 강조 없음
  });

  it('DSM — topo_order 부재(구 캐시)는 이름순 폴백을 명시', async () => {
    mockResp = { ...Q2, file_graph: { ...Q2.file_graph, topo_order: [] } };
    render(<ArchitectureGraphPanel {...PROPS} />);
    expect(await screen.findByText(/위상 순서가 이 응답에 없어 이름순으로 표시/)).toBeInTheDocument();
  });

  it('전역 데이터 흐름은 숨김 상태다', async () => {
    render(<ArchitectureGraphPanel {...PROPS} />);
    await screen.findByRole('img', { name: '모듈 의존 다이어그램' });
    expect(screen.queryByRole('img', { name: '전역 데이터 흐름' })).toBeNull();
    expect(screen.queryByText('g_shared')).toBeNull();
  });

  it('숨겨도 DSM은 남는다(순환 가시화는 이 패널의 핵심 축)', async () => {
    render(<ArchitectureGraphPanel {...PROPS} />);
    expect(await screen.findByText(/의존 구조 매트릭스\(DSM\)/)).toBeInTheDocument();
  });
});

// ── 심층 개선: DSM 절단 시 순환 과소 표기 방지 ──
describe('ArchitectureGraphPanel — DSM 절단 정직성', () => {
  beforeEach(() => { clearArchMetricsCache(); vi.clearAllMocks(); });

  it('표시 상한을 넘으면 "표시 N / 전체 M"으로 병기한다(실측 6/14 침묵 사례)', async () => {
    // 40개 파일 체인 + 뒤쪽 파일에서 앞쪽으로 되돌아가는 역행 엣지 → 상한 28에 절단된다
    const nodes = Array.from({ length: 40 }, (_, i) => ({ file: `f${String(i).padStart(2, '0')}.c`, module: 'M', functions: 1, lines: 10 }));
    const order = nodes.map((n) => n.file);
    const edges = [
      ...Array.from({ length: 39 }, (_, i) => ({ from: order[i], to: order[i + 1], calls: 1 })),
      { from: order[5], to: order[1], calls: 1 },    // 표시 범위 안 역행
      { from: order[35], to: order[30], calls: 1 },  // 절단 범위 밖 역행 — 침묵하면 안 된다
    ];
    mockResp = { ...METRICS, file_graph: { nodes, edges, topo_order: order, truncated: false, total_files: 40, total_edges: edges.length } };
    render(<ArchitectureGraphPanel {...PROPS} />);
    expect(await screen.findByText(/표시 1건 \/ 전체 2건/)).toBeInTheDocument();
    expect(screen.getByText(/표시 상한 28개/)).toBeInTheDocument();
  });
});
