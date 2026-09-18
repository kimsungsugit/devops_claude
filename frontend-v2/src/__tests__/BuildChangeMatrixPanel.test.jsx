/**
 * BuildChangeMatrixPanel — 베이스라인 대비 각 빌드의 누적 소스 변화.
 * 파일 축 즉시 · 함수 축 순차(동시성 1) · 동일 트리 그룹 공유 · 미계산은 0이 아니라 —.
 */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockFiles;
let mockFunctions;
let cellResponses;   // target_build → 응답
let cellCalls;       // 호출 순서 기록

vi.mock('../api.js', () => ({
  post: vi.fn((url, body) => {
    const u = String(url);
    if (u.endsWith('/api/summary/change-matrix')) {
      return Promise.resolve(body?.level === 'functions' ? mockFunctions : mockFiles);
    }
    if (u.includes('change-matrix/cell')) {
      cellCalls.push({ target: body?.target_build, at: Date.now() });
      return new Promise((resolve) => {
        setTimeout(() => resolve(cellResponses[body?.target_build]), 5);
      });
    }
    return Promise.resolve({});
  }),
}));

const { default: BuildChangeMatrixPanel } = await import('../components/sections/BuildChangeMatrixPanel.jsx');
const { post } = await import('../api.js');

function row(n, extra = {}) {
  return {
    row_key: `b${n}`, build_number: n, build_result: 'SUCCESS',
    timestamp_iso: `2026-07-${String(n).padStart(2, '0')}T13:00:00`, revision: `10${n}`,
    source_pinned: true, source_revision_source: 'svn_date',
    snapshot_group: { count: 1, members: [n], canonical_build: n },
    is_baseline: false, identical_to_baseline: false,
    files: { added: 0, deleted: 0, modified: 2, changed: 2, unchanged: 145, changed_paths: [{ path: 'APP/a.c', change_kind: 'modified' }] },
    functions: null, asil: null,
    function_state: { state: 'not_computed', reason: 'level_files' },
    cell_id: `base__${n}`, ...extra,
  };
}

const FILES = {
  ok: true, available: true, level: 'files',
  baseline: { build_number: 11, timestamp_iso: '2026-05-19T13:00:08', revision: '1018' },
  rows: [
    row(25),
    row(24),
    // 동일 트리 3개 — 파싱 없이 함수 0 확정
    row(13, { identical_to_baseline: true, snapshot_group: { count: 3, members: [13, 12, 11], canonical_build: 11 },
              files: { added: 0, deleted: 0, modified: 0, changed: 0, unchanged: 147, changed_paths: [] },
              functions: { new: 0, deleted: 0, signature: 0, body: 0, changed: 0 },
              asil: { touched: 0, by_grade: {}, max: null },
              function_state: { state: 'identical', reason: '베이스라인과 소스 트리가 바이트 동일 — 함수 차이는 계산 없이 0으로 확정' } }),
    { row_key: 'b11', build_number: 11, is_baseline: true, revision: '1011', source_pinned: true,
      snapshot_group: { count: 3, members: [13, 12, 11] },
      files: null, functions: null, asil: null, function_state: { state: 'baseline' } },
  ],
  snapshot_trust: { pinned: 4, unpinned: 0, unpinned_builds: [], note: '' },
  pending_cells: [{ cell_id: 'base__25', target_build: 25 }, { cell_id: 'base__24', target_build: 24 }],
  snapshot_groups: [{ content_sha: 'de6809e7', builds: [13, 12, 11], count: 3 }],
  stats: { rows: 4, pairs_total: 3, pairs_distinct: 2 },
  join_scope: { build_number: 25, coverage_functions: 812, asil_functions: 385, note: '최신 빌드 기준' },
  note: '영향분석 실행 이력과 무관한 소스 스냅샷 비교입니다',
};

const PROPS = { jobUrl: 'http://j/', cacheRoot: '.c', baseline: '11', deltaByBuild: new Map() };

describe('BuildChangeMatrixPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockFiles = FILES;
    mockFunctions = { ...FILES, level: 'functions' };
    cellCalls = [];
    cellResponses = {
      25: { ok: true, available: true, cell_id: 'base__25', target: { build_number: 25 },
            shared_with_builds: [25], functions: { new: 1, deleted: 0, signature: 1, body: 3, changed: 5 },
            asil: { touched: 2, by_grade: { C: 1, B: 1 }, max: 'C' }, function_state: { state: 'computed' } },
      24: { ok: true, available: true, cell_id: 'base__24', target: { build_number: 24 },
            shared_with_builds: [24], functions: { new: 0, deleted: 0, signature: 0, body: 2, changed: 2 },
            asil: { touched: 0, by_grade: {}, max: null }, function_state: { state: 'computed' } },
    };
  });

  it('파일 축만으로 전 빌드 행이 즉시 뜨고, 함수/ASIL은 0이 아니라 —', async () => {
    render(<BuildChangeMatrixPanel {...PROPS} />);
    expect(await screen.findByText('#25')).toBeInTheDocument();
    expect(screen.getByText('#24')).toBeInTheDocument();
    expect(screen.getByText('#11 (기준)')).toBeInTheDocument();
    const r25 = screen.getByText('#25').closest('tr');
    expect(within(r25).getByText('2')).toBeInTheDocument();          // 변경 파일
    // ISO 정직성: 미계산은 0이 아니라 —(사유 동반)
    expect(within(r25).getAllByText(/—/).length).toBeGreaterThan(0);
    expect(within(r25).queryByText('0')).toBeNull();
  });

  it('동일 트리 행은 계산 없이 0으로 확정 + 그룹 배지·경고 배너', async () => {
    render(<BuildChangeMatrixPanel {...PROPS} />);
    await screen.findByText('#13');
    const r13 = screen.getByText('#13').closest('tr');
    expect(within(r13).getByText('동일 트리 3')).toBeInTheDocument();
    expect(within(r13).getAllByText('0').length).toBeGreaterThan(0);  // 함수 0이 확정돼 있다
    // '변화 0'을 코드 미변경으로 오독하지 않게 하는 배너
    expect(screen.getByText(/동일 트리라 이 구간의 변화는 0으로 나옵니다/)).toBeInTheDocument();
  });

  it('pending을 동시성 1로 순차 처리하고, 도착 시 행이 채워진다', async () => {
    const user = userEvent.setup();
    render(<BuildChangeMatrixPanel {...PROPS} />);
    await screen.findByText('#25');
    await user.click(screen.getByText(/함수 축 계산 \(2건\)/));
    await vi.waitFor(() => expect(cellCalls.length).toBe(2));
    // 두 번째 호출은 첫 번째가 끝난 뒤여야 한다(동시 발사 금지 — 파서가 겹치면 메모리·CPU 폭증)
    expect(cellCalls[1].at).toBeGreaterThanOrEqual(cellCalls[0].at);
    await vi.waitFor(() => {
      const r25 = screen.getByText('#25').closest('tr');
      expect(within(r25).getByText('5')).toBeInTheDocument();          // 변경 함수
      expect(within(r25).getByText(/\(C1·B1\)/)).toBeInTheDocument();  // ASIL 등급 분해
    });
  });

  it('언마운트하면 순차 계산이 멈춘다(떠난 프로젝트를 계속 계산하지 않는다)', async () => {
    // ⚠ runRef 는 baseline 변경 때만 올라갔다 — 프로젝트를 바꿔 섹션이 remount 돼도
    //   떠난 프로젝트의 셀 계산이 끝까지 돌았다(서버 부하 + 떠난 결과가 화면에 반영).
    const user = userEvent.setup();
    const { unmount } = render(<BuildChangeMatrixPanel {...PROPS} />);
    await screen.findByText('#25');
    await user.click(screen.getByText(/함수 축 계산 \(2건\)/));
    await vi.waitFor(() => expect(cellCalls.length).toBeGreaterThanOrEqual(1));
    unmount();
    const after = cellCalls.length;
    await new Promise((r) => setTimeout(r, 60));
    expect(cellCalls.length).toBe(after);   // 언마운트 후 추가 계산 없음
  });

  it('진행 상태를 부모에 보고한다(탭 밖에서도 보이게)', async () => {
    const user = userEvent.setup();
    const onBusy = vi.fn();
    render(<BuildChangeMatrixPanel {...PROPS} onBusy={onBusy} />);
    await screen.findByText('#25');
    await user.click(screen.getByText(/함수 축 계산 \(2건\)/));
    await vi.waitFor(() => {
      expect(onBusy.mock.calls.some(([k, l]) => k === 'matrix' && /함수 축 계산 중/.test(l || ''))).toBe(true);
    });
    // 끝나면 반드시 해제 — 안 그러면 상단 스트립이 영구히 남는다
    await vi.waitFor(() => {
      expect(onBusy.mock.calls.some(([k, l]) => k === 'matrix' && l === null)).toBe(true);
    });
  });

  it('셀 1건이 같은 스냅샷 그룹의 여러 행을 함께 채운다', async () => {
    cellResponses[25] = { ...cellResponses[25], shared_with_builds: [25, 24] };
    mockFiles = { ...FILES, pending_cells: [{ cell_id: 'base__25', target_build: 25 }] };
    mockFunctions = { ...mockFiles, level: 'functions' };
    const user = userEvent.setup();
    render(<BuildChangeMatrixPanel {...PROPS} />);
    await screen.findByText('#25');
    await user.click(screen.getByText(/함수 축 계산 \(1건\)/));
    await vi.waitFor(() => {
      expect(within(screen.getByText('#25').closest('tr')).getByText('5')).toBeInTheDocument();
      expect(within(screen.getByText('#24').closest('tr')).getByText('5')).toBeInTheDocument();
    });
    expect(cellCalls.length).toBe(1);   // 계산은 1회뿐
  });

  it('행 펼침 — 변경 파일 목록 + 함수 목록 버튼(핸드오프 아님)', async () => {
    const user = userEvent.setup();
    render(<BuildChangeMatrixPanel {...PROPS} />);
    await screen.findByText('#25');
    await user.click(screen.getByLabelText(/빌드 #25 변경 상세 펼치기/));
    expect(screen.getByText('APP/a.c')).toBeInTheDocument();
    expect(screen.getByText('함수 목록 보기')).toBeInTheDocument();
  });

  it('베이스라인은 읽기 전용 에코 — 이 패널에 선택 UI를 두지 않는다', async () => {
    render(<BuildChangeMatrixPanel {...PROPS} />);
    await screen.findByText('#25');
    expect(screen.getByText(/기준 #11/)).toBeInTheDocument();
    expect(screen.getByText(/위 패널에서 변경/)).toBeInTheDocument();
    expect(screen.queryByLabelText('베이스라인 빌드')).toBeNull();   // select 중복 배치 금지
  });

  it('available:false는 사유를 낸다(빈 화면 금지)', async () => {
    mockFiles = { ok: true, available: false, reason: 'no_source_snapshot' };
    render(<BuildChangeMatrixPanel {...PROPS} />);
    expect(await screen.findByText(/소스 스냅샷이 있는 캐시 빌드가 없습니다/)).toBeInTheDocument();
  });

  it('베이스라인이 없으면 조회하지 않는다', async () => {
    render(<BuildChangeMatrixPanel {...PROPS} baseline="" />);
    expect(post).not.toHaveBeenCalled();
  });

  // ── 스냅샷 미고정 표면화 ────────────────────────────────────────────────
  // '동일 트리라 변화 0'만 보여주면 사용자는 코드가 안 바뀐 것으로 읽는다. 실제 원인은
  // 백필이 HEAD를 받아온 것이고, 그 결과 ASIL 함수 변경이 통째로 침묵한다.

  it('고정되지 않은 스냅샷이 있으면 원인과 조치를 배너로 알린다', async () => {
    const unpinned = {
      ...FILES,
      rows: FILES.rows.map((r) => ({ ...r, source_pinned: false, source_revision_source: 'head' })),
      snapshot_trust: { pinned: 0, unpinned: 4, unpinned_builds: [25, 24, 13, 11], note: '' },
    };
    mockFiles = unpinned;
    mockFunctions = { ...unpinned, level: 'functions' };
    render(<BuildChangeMatrixPanel {...PROPS} />);
    await screen.findByText('#25');
    expect(screen.getByText(/빌드 시점으로 고정되지 않았습니다/)).toBeInTheDocument();
    expect(screen.getByText(/코드가 안 바뀐 증거가 아닙니다/)).toBeInTheDocument();
    expect(screen.getByText(/스냅샷 고정/)).toBeInTheDocument();   // 조치 안내
  });

  it('행의 리비전 열이 고정 여부를 구분한다', async () => {
    const mixed = {
      ...FILES,
      rows: [
        { ...FILES.rows[0], source_pinned: true },
        { ...FILES.rows[1], source_pinned: false, source_revision_source: 'head' },
        ...FILES.rows.slice(2),
      ],
      snapshot_trust: { pinned: 3, unpinned: 1, unpinned_builds: [24], note: '' },
    };
    mockFiles = mixed;
    mockFunctions = { ...mixed, level: 'functions' };
    render(<BuildChangeMatrixPanel {...PROPS} />);
    await screen.findByText('#25');
    expect(within(screen.getByText('#25').closest('tr')).getByText('r1025')).toBeInTheDocument();
    // 미고정 행은 revision 값이 있어도 경고 표식이 붙는다(값만 보면 정상으로 오독한다)
    expect(within(screen.getByText('#24').closest('tr')).getByText(/r1024 ⚠/)).toBeInTheDocument();
  });

  it('전부 고정됐으면 미고정 배너를 내지 않는다', async () => {
    render(<BuildChangeMatrixPanel {...PROPS} />);
    await screen.findByText('#25');
    expect(screen.queryByText(/빌드 시점으로 고정되지 않았습니다/)).toBeNull();
  });

  // ── 행 상한 절단 고지 (실측: 캐시 33빌드 / 구 상한 30 → #77·78·79 침묵 손실) ──

  it('상한에 잘린 빌드가 있으면 "표시 N / 전체 M"으로 병기한다', async () => {
    const capped = { ...FILES, row_limit: { limit: 30, shown: 30, available: 33, omitted_builds: [79, 78, 77], baseline_forced_in: true } };
    mockFiles = capped;
    mockFunctions = { ...capped, level: 'functions' };
    render(<BuildChangeMatrixPanel {...PROPS} />);
    await screen.findByText('#25');
    // 절단 고지는 이제 **헤더(problem 슬롯) + 본문** 두 곳에 난다 — 패널을 접어도
    // 잘렸다는 사실이 남아야 하기 때문이다.
    expect(screen.getAllByText(/표시 30 \/ 전체 33/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/#79 · #78 · #77/)).toBeInTheDocument();
    expect(screen.getByText(/기준 빌드는 상한과 무관하게 항상 표시/)).toBeInTheDocument();
  });

  it('절단이 없으면 고지를 내지 않는다', async () => {
    const full = { ...FILES, row_limit: { limit: 100, shown: 4, available: 4, omitted_builds: [], baseline_forced_in: false } };
    mockFiles = full;
    mockFunctions = { ...full, level: 'functions' };
    render(<BuildChangeMatrixPanel {...PROPS} />);
    await screen.findByText('#25');
    expect(screen.queryByText(/표시 \d+ \/ 전체/)).toBeNull();
  });

  // ── 비교 기준 불일치 (부분 재수집 중 필연) ──────────────────────────────

  it('기준이 섞인 행은 수치에 ⚠를 붙인다 — 그 숫자는 "이 빌드의 변화"가 아니다', async () => {
    const mixed = {
      ...FILES,
      rows: [
        { ...FILES.rows[0], source_pinned: true,
          comparison_basis: { state: 'mixed', reason: '베이스라인과 이 빌드의 소스 기준이 다릅니다' },
          functions: { new: 0, deleted: 0, signature: 0, body: 3, changed: 3 } },
        { ...FILES.rows[1], comparison_basis: { state: 'trusted' } },
        ...FILES.rows.slice(2),
      ],
      snapshot_trust: { pinned: 1, unpinned: 3, unpinned_builds: [24, 13, 11], note: '' },
    };
    mockFiles = mixed;
    mockFunctions = { ...mixed, level: 'functions' };
    render(<BuildChangeMatrixPanel {...PROPS} />);
    await screen.findByText('#25');
    const r25 = within(screen.getByText('#25').closest('tr'));
    expect(r25.getByText('2 ⚠')).toBeInTheDocument();   // 변경 파일
    expect(r25.getByText('3 ⚠')).toBeInTheDocument();   // 변경 함수
    // 신뢰 가능한 행은 표식이 붙지 않는다(과잉 경고로 신호가 죽으면 안 된다)
    expect(within(screen.getByText('#24').closest('tr')).getByText('2')).toBeInTheDocument();
    expect(screen.getByText(/기준이 섞인 행 1개는 ⚠로 표시/)).toBeInTheDocument();
  });
});
