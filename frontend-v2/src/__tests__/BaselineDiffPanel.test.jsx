/**
 * BaselineDiffPanel — 기본 쌍(최고령→최신)·change-log 비의존 캡션·ASIL 강조·prqa-delta 병행·정직 실패.
 */
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockDiff;
let mockDelta;

vi.mock('../api.js', () => ({
  post: vi.fn((url) => {
    const u = String(url);
    if (u.includes('baseline-diff')) return Promise.resolve(mockDiff);
    if (u.includes('prqa-delta')) return Promise.resolve(mockDelta);
    return Promise.resolve({});
  }),
}));

const { default: BaselineDiffPanel } = await import('../components/sections/BaselineDiffPanel.jsx');
const { post } = await import('../api.js');

const DIFF = {
  ok: true, available: true, reason: null, independent_of_change_log: true, cached: false,
  baseline: { build_number: 122 }, target: { build_number: 125 },
  files: {
    added: ['APP/added.c'], deleted: [],
    modified: [{ path: 'APP/a.c', lines_added: 3, lines_removed: 1 }],
    unchanged: 67, total_baseline: 70, total_target: 71,
    // N3: 파일 → 함수 트리(위험 우선 정렬 결과)
    changed_detail: [
      {
        path: 'APP/a.c', change_kind: 'modified', lines_added: 3, lines_removed: 1,
        functions: [
          { name: 'safe_fn', kind: 'SIGNATURE', asil: 'C', asil_source: 'uds_link',
            before: 'void safe_fn(int a)', after: 'void safe_fn(int a, int b)',
            statement: 0.0, branch: 0.0, ccn: 7, metric_source: 'ut' },
          { name: 'body_fn', kind: 'BODY', asil: null, asil_source: null,
            statement: 0.6, branch: 0.5, ccn: 3, metric_source: 'ut' },
          { name: 'new_fn', kind: 'NEW', asil: null, asil_source: null,
            statement: null, branch: null, ccn: null, metric_source: null },
        ],
        functions_omitted: 0,
        counts: { new: 1, deleted: 0, signature: 1, body: 1 },
        asil_max: 'C', worst_statement: 0.0, coverage_matched: 2,
      },
      {
        path: 'APP/added.c', change_kind: 'added', lines_added: null, lines_removed: null,
        functions: [{ name: 'added_file_fn', kind: 'NEW', asil: null, asil_source: null,
                      statement: 1.0, branch: 1.0, ccn: 1, metric_source: 'it' }],
        functions_omitted: 0,
        counts: { new: 1, deleted: 0, signature: 0, body: 0 },
        asil_max: null, worst_statement: 1.0, coverage_matched: 1,
      },
    ],
    changed_detail_omitted: 0,
  },
  functions: {
    new: [{ name: 'new_fn', file: 'APP/a.c', asil: null }], deleted: [],
    signature_changed: [{ name: 'safe_fn', file: 'APP/a.c', before: 'void safe_fn(int a)', after: 'void safe_fn(int a, int b)', asil: 'C' }],
    body_changed: [{ name: 'body_fn', file: 'APP/a.c', asil: null }],
    counts: { new: 1, deleted: 0, signature: 1, body: 1 },
    gap_summary: { changed_functions: 4, with_coverage: 3, uncovered: 1, below_full: 1,
                   asil_touched: 1, coverage_unmatched: 1 },
  },
  asil_touched: [{ name: 'safe_fn', file: 'APP/a.c', asil: 'C', change_kind: 'SIGNATURE' }],
  coverage_join: { injected: true, functions_in_index: 3, matched: 3, unmatched: 1 },
  asil_join: { injected: true, functions_in_index: 385 },
  join_sources: { coverage: 'scm_vcast_job', asil_counts: { total: 385, uds_link: 385, comment_asil: 0, both: 0, conflict: 0 } },
  method: {},
};
const DELTA = { ok: true, available: true, totals: { cur: 562, base: 552, delta: 10 } };

// controlled — builds/baseline/target은 부모(ProjectSummarySection)가 소유한다.
// 아래 매트릭스 패널과 기준을 공유해야 해서 자체 조회를 없앴다(폴백 fetch도 없음).
const SRC_BUILDS = [
  { build_number: 125, has_source: true, timestamp_iso: '2026-07-24T13:00:11', revision: '1075' },
  { build_number: 122, has_source: true, timestamp_iso: '2026-06-25T13:00:00', revision: '1053' },
];
const PROPS = {
  jobUrl: 'http://jenkins/job/KJ/', cacheRoot: '.devops_pro_cache',
  builds: SRC_BUILDS, baseline: '122', target: '125',
  onChangeBaseline: () => {}, onChangeTarget: () => {},
};

describe('BaselineDiffPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockDiff = DIFF;
    mockDelta = DELTA;
  });

  it('기본 쌍(has_source 최고령 122 → 최신 125)으로 자동 비교 + 비의존 캡션', async () => {
    render(<BaselineDiffPanel {...PROPS} />);
    expect(await screen.findByText(/신규 1/)).toBeInTheDocument();
    expect(screen.getByText(/영향분석 이력\(change-log\)과 무관/)).toBeInTheDocument();
    const call = post.mock.calls.find(([u]) => String(u).includes('baseline-diff'));
    expect(call[1]).toMatchObject({ baseline_build: 122, target_build: 125 });
    // has_source:false인 124는 콤보에 없음
    expect(screen.queryByRole('option', { name: '#124' })).toBeNull();
  });

  it('ASIL 함수 변경 경고 + 펼친 함수 행의 시그니처 before/after', async () => {
    const user = userEvent.setup();
    render(<BaselineDiffPanel {...PROPS} />);
    expect(await screen.findByText(/ASIL 주석 보유 함수 변경 1건/)).toBeInTheDocument();
    expect(screen.getByText(/safe_fn\(C\/SIGNATURE\)/)).toBeInTheDocument();
    // O5: 최상단(위험 1위) 파일은 기본 펼침이라 시그니처 diff가 바로 보인다
    expect(screen.getByText('- void safe_fn(int a)')).toBeInTheDocument();
    expect(screen.getByText('+ void safe_fn(int a, int b)')).toBeInTheDocument();
    // 접으면 사라지고, 다시 펼치면 돌아온다(토글 계약)
    await user.click(screen.getByLabelText('APP/a.c 변경 함수 접기'));
    expect(screen.queryByText('- void safe_fn(int a)')).toBeNull();
    await user.click(screen.getByLabelText('APP/a.c 변경 함수 펼치기'));
    expect(screen.getByText('- void safe_fn(int a)')).toBeInTheDocument();
  });

  // ── N3: 파일 → 함수 트리 ──
  it('변경 함수 갭 요약 — 미커버/부분/미조인과 조인 출처', async () => {
    render(<BaselineDiffPanel {...PROPS} />);
    expect(await screen.findByText(/변경 함수 4개 중/)).toBeInTheDocument();
    expect(screen.getByText('미커버 1')).toBeInTheDocument();
    expect(screen.getByText('부분 커버 1')).toBeInTheDocument();
    expect(screen.getByText(/커버리지 출처 SCM 입력 문서/)).toBeInTheDocument();
    expect(screen.getByText(/ASIL 확보 385함수\(역전파 385\)/)).toBeInTheDocument();
  });

  it('O5: 최상단 파일은 기본 펼침 + 함수 행에 트리 커넥터', async () => {
    render(<BaselineDiffPanel {...PROPS} />);
    // 위험 우선 정렬 1위(APP/a.c)가 열린 채로 그려져 파일→함수 구조가 첫 화면에 보인다
    expect(await screen.findByLabelText('APP/a.c 변경 함수 접기')).toBeInTheDocument();
    expect(screen.getByLabelText('APP/added.c 변경 함수 펼치기')).toBeInTheDocument();
    // 자식 행임이 드러나는 커넥터(├─ 중간 / └─ 마지막)
    const rows = screen.getAllByText(/^[├└]─$/);
    expect(rows.length).toBe(3);                        // a.c의 함수 3개
    expect(rows[rows.length - 1]).toHaveTextContent('└─');
    // 파일 행은 '—' 대신 집계를 보여 빈칸으로 보이지 않는다
    expect(screen.getByText('함수 3개')).toBeInTheDocument();
  });

  it('펼치면 함수별 커버리지·ASIL이 붙고 미조인은 —(0% 위장 금지)', async () => {
    render(<BaselineDiffPanel {...PROPS} />);
    await screen.findByText('APP/a.c');
    const row = screen.getByText('body_fn').closest('tr');
    expect(row).toHaveTextContent('60%');   // statement 0.6
    expect(row).toHaveTextContent('50%');   // branch 0.5
    expect(row).toHaveTextContent('3');     // ccn
    const newRow = screen.getByText('new_fn').closest('tr');
    expect(newRow).toHaveTextContent('—');  // 커버리지 미조인 → 0%가 아니라 —
    // ASIL 출처가 역전파여도 등급이 표시된다
    const safeRow = screen.getByText('safe_fn').closest('tr');
    expect(safeRow).toHaveTextContent('C');
  });

  it('필터 — ASIL 함수만 고르면 해당 파일만 남는다', async () => {
    const user = userEvent.setup();
    render(<BaselineDiffPanel {...PROPS} />);
    await screen.findByText('APP/a.c');
    expect(screen.getByText('APP/added.c')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'ASIL 함수만' }));
    expect(screen.getByText('APP/a.c')).toBeInTheDocument();
    expect(screen.queryByText('APP/added.c')).toBeNull();
  });

  it('구 캐시 응답(changed_detail 없음)은 재비교 안내', async () => {
    mockDiff = { ...DIFF, files: { ...DIFF.files, changed_detail: undefined } };
    render(<BaselineDiffPanel {...PROPS} />);
    expect(await screen.findByText(/함수 트리는 이 응답\(구 캐시\)에 없습니다/)).toBeInTheDocument();
  });

  it('같은 쌍 prqa-delta 병행 표시(위반 552→562 +10)', async () => {
    render(<BaselineDiffPanel {...PROPS} />);
    expect(await screen.findByText(/위반 552 → 562/)).toBeInTheDocument();
    expect(screen.getByText('(+10)')).toBeInTheDocument();
    const call = post.mock.calls.find(([u]) => String(u).includes('prqa-delta'));
    expect(call[1]).toMatchObject({ build_number: 125, baseline_build_number: 122 });
  });

  it('delta 실패는 부가정보라 코드 변화 표시 유지(silent 아님 — 미표시일 뿐)', async () => {
    mockDelta = null;
    render(<BaselineDiffPanel {...PROPS} />);
    expect(await screen.findByText(/신규 1/)).toBeInTheDocument();
    expect(screen.queryByText(/위반/)).toBeNull();
  });

  it('스냅샷 1개뿐이면 백필 안내', async () => {
    render(<BaselineDiffPanel {...PROPS} builds={[{ build_number: 125, has_source: true }]} baseline="" target="" />);
    expect(await screen.findByText(/2개 이상 필요합니다\(현재 1개\)/)).toBeInTheDocument();
  });

  it('동일 스냅샷 — 빈 화면이 아니라 경고 + 사유(ASIL 과소보고 침묵 방지)', async () => {
    mockDiff = {
      ...DIFF,
      baseline: { build_number: 111, checkout_lag_days: 69.0, source_checked_out_at: '2026-07-27T09:24:27' },
      target: { build_number: 125, checkout_lag_days: 0.0 },
      baseline_auto_reason: 'all_identical',
      snapshot_groups: [{ builds: [123, 121, 120, 111], count: 4 }],
      files: { added: [], deleted: [], modified: [], unchanged: 147, identical_snapshot: true, changed_detail: [] },
      functions: { counts: { new: 0, deleted: 0, signature: 0, body: 0 } },
      asil_touched: [],
    };
    render(<BaselineDiffPanel {...PROPS} />);
    expect(await screen.findByRole('alert')).toHaveTextContent(/소스 스냅샷이 완전히 동일/);
    expect(screen.getByText(/빌드 당시 코드가 아닐 수 있습니다/)).toBeInTheDocument();
    expect(screen.getByText(/동일 트리 재사용: #123 · #121 · #120 · #111/)).toBeInTheDocument();
    // 구 코드는 `&&` 폴백이라 여기서 아무것도 렌더되지 않았다(빈 화면 = '변경 없음' 오독).
    expect(screen.getByText(/두 스냅샷이 동일해 비교할 변경이 없습니다/)).toBeInTheDocument();
  });

  it('정상 스냅샷이면 신뢰 배너를 띄우지 않는다', async () => {
    mockDiff = { ...DIFF, baseline: { build_number: 122, checkout_lag_days: 0.1 }, target: { build_number: 125, checkout_lag_days: 0 }, snapshot_groups: [] };
    render(<BaselineDiffPanel {...PROPS} />);
    await screen.findByText(/APP\/a\.c/);
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText(/동일 트리 재사용/)).toBeNull();
  });

  it('빌드 선택 라벨에 날짜·리비전을 표기(번호만으론 어느 시점인지 모른다)', async () => {
    render(<BaselineDiffPanel {...PROPS} />);
    const sel = await screen.findByLabelText('베이스라인 빌드');
    expect(within(sel).getByText('#122 · 06/25 r1053')).toBeInTheDocument();
    expect(within(sel).getByText('#125 · 07/24 r1075')).toBeInTheDocument();
  });

  it('available:false reason 한국어 매핑', async () => {
    mockDiff = { ok: true, available: false, reason: 'snapshot_missing_baseline' };
    render(<BaselineDiffPanel {...PROPS} />);
    expect(await screen.findByText(/베이스라인 빌드에 소스 스냅샷이 없습니다/)).toBeInTheDocument();
  });

  it('select 변경은 부모에게 통지만 한다(controlled) — 값 소유자는 부모', async () => {
    // 아래 매트릭스 패널과 기준을 공유하므로 이 패널이 스스로 baseline을 바꾸면 안 된다.
    const user = userEvent.setup();
    const onChangeBaseline = vi.fn();
    const onChangeTarget = vi.fn();
    render(<BaselineDiffPanel {...PROPS} onChangeBaseline={onChangeBaseline} onChangeTarget={onChangeTarget} />);
    await screen.findByText(/신규 1/);
    await user.selectOptions(screen.getByLabelText('베이스라인 빌드'), '125');
    expect(onChangeBaseline).toHaveBeenCalledWith('125');
    await user.selectOptions(screen.getByLabelText('대상 빌드'), '122');
    expect(onChangeTarget).toHaveBeenCalledWith('122');
  });

  it('부모가 쌍을 바꾸면 새 쌍으로 자동 재비교(같은 쌍은 1회만)', async () => {
    const { rerender } = render(<BaselineDiffPanel {...PROPS} />);
    await screen.findByText(/신규 1/);
    const before = post.mock.calls.filter(([u]) => String(u).includes('baseline-diff')).length;
    rerender(<BaselineDiffPanel {...PROPS} />);          // 같은 쌍 리렌더 — 재요청 없음
    expect(post.mock.calls.filter(([u]) => String(u).includes('baseline-diff')).length).toBe(before);
    rerender(<BaselineDiffPanel {...PROPS} baseline="125" target="122" />);
    await vi.waitFor(() => {
      const calls = post.mock.calls.filter(([u]) => String(u).includes('baseline-diff'));
      expect(calls[calls.length - 1][1]).toMatchObject({ baseline_build: 125, target_build: 122 });
    });
  });
});
