/** ArchitectureGraphPanel — 층위 배치(순수)·사이클 강조·드릴다운·히트맵·정직 각주. */
import React from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockResp;

vi.mock('../api.js', () => ({
  post: vi.fn(() => (mockResp instanceof Error ? Promise.reject(mockResp) : Promise.resolve(mockResp))),
}));

import ArchitectureGraphPanel from '../components/sections/ArchitectureGraphPanel.jsx';
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
    vi.clearAllMocks();
    mockResp = METRICS;
  });

  it('다이어그램·사이클 강조·개선 후보·정직 각주를 렌더한다', async () => {
    render(<ArchitectureGraphPanel {...PROPS} />);
    expect(await screen.findByRole('img', { name: '모듈 의존 다이어그램' })).toBeInTheDocument();
    // 사이클 참여 모듈은 aria-label에 명시(색 외 접근 수단)
    expect(screen.getByRole('button', { name: /모듈 APP.*순환 의존 참여/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /모듈 IF(?!.*순환)/ })).toBeInTheDocument();
    // 순환 목록 + 상호 호출 수치
    expect(screen.getByText(/순환 2파일/)).toBeInTheDocument();
    expect(screen.getByText(/APP\/a\.c ↔ LIB\/u\.c/)).toBeInTheDocument();
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
    expect(screen.getByText(/내부 파일 2개 · 파일 간 호출 2건/)).toBeInTheDocument();
    expect(screen.getByText('a.c')).toBeInTheDocument();
    expect(screen.getByText('b.c')).toBeInTheDocument();
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
