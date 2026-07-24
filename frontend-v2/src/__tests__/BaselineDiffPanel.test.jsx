/**
 * BaselineDiffPanel — 기본 쌍(최고령→최신)·change-log 비의존 캡션·ASIL 강조·prqa-delta 병행·정직 실패.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockMeta;
let mockDiff;
let mockDelta;

vi.mock('../api.js', () => ({
  post: vi.fn((url) => {
    const u = String(url);
    if (u.includes('cached-builds-meta')) return Promise.resolve(mockMeta);
    if (u.includes('baseline-diff')) return Promise.resolve(mockDiff);
    if (u.includes('prqa-delta')) return Promise.resolve(mockDelta);
    return Promise.resolve({});
  }),
}));

const { default: BaselineDiffPanel } = await import('../components/sections/BaselineDiffPanel.jsx');
const { post } = await import('../api.js');

const META = {
  ok: true, available: true,
  builds: [
    { build_number: 125, has_source: true }, { build_number: 124, has_source: false }, { build_number: 122, has_source: true },
  ],
};
const DIFF = {
  ok: true, available: true, reason: null, independent_of_change_log: true, cached: false,
  baseline: { build_number: 122 }, target: { build_number: 125 },
  files: { added: ['APP/added.c'], deleted: [], modified: [{ path: 'APP/a.c', lines_added: 3, lines_removed: 1 }], unchanged: 67, total_baseline: 70, total_target: 71 },
  functions: {
    new: [{ name: 'new_fn', file: 'APP/a.c', asil: null }], deleted: [],
    signature_changed: [{ name: 'safe_fn', file: 'APP/a.c', before: 'void safe_fn(int a)', after: 'void safe_fn(int a, int b)', asil: 'C' }],
    body_changed: [{ name: 'body_fn', file: 'APP/a.c', asil: null }],
    counts: { new: 1, deleted: 0, signature: 1, body: 1 },
  },
  asil_touched: [{ name: 'safe_fn', file: 'APP/a.c', asil: 'C', change_kind: 'SIGNATURE' }],
  method: {},
};
const DELTA = { ok: true, available: true, totals: { cur: 562, base: 552, delta: 10 } };

const PROPS = { jobUrl: 'http://jenkins/job/KJ/', cacheRoot: '.devops_pro_cache' };

describe('BaselineDiffPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockMeta = META;
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

  it('ASIL 함수 변경 경고 + 시그니처 before/after 렌더', async () => {
    render(<BaselineDiffPanel {...PROPS} />);
    expect(await screen.findByText(/ASIL 주석 보유 함수 변경 1건/)).toBeInTheDocument();
    expect(screen.getByText(/safe_fn\(C\/SIGNATURE\)/)).toBeInTheDocument();
    expect(screen.getByText('- void safe_fn(int a)')).toBeInTheDocument();
    expect(screen.getByText('+ void safe_fn(int a, int b)')).toBeInTheDocument();
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
    mockMeta = { ok: true, available: true, builds: [{ build_number: 125, has_source: true }] };
    render(<BaselineDiffPanel {...PROPS} />);
    expect(await screen.findByText(/2개 이상 필요합니다\(현재 1개\)/)).toBeInTheDocument();
  });

  it('available:false reason 한국어 매핑', async () => {
    mockDiff = { ok: true, available: false, reason: 'snapshot_missing_baseline' };
    render(<BaselineDiffPanel {...PROPS} />);
    expect(await screen.findByText(/베이스라인 빌드에 소스 스냅샷이 없습니다/)).toBeInTheDocument();
  });

  it('쌍 변경 후 비교 버튼 → 새 쌍으로 요청', async () => {
    const user = userEvent.setup();
    render(<BaselineDiffPanel {...PROPS} />);
    await screen.findByText(/신규 1/);
    await user.selectOptions(screen.getByLabelText('베이스라인 빌드'), '125');
    await user.selectOptions(screen.getByLabelText('대상 빌드'), '122');
    await user.click(screen.getByText('비교'));
    const calls = post.mock.calls.filter(([u]) => String(u).includes('baseline-diff'));
    expect(calls[calls.length - 1][1]).toMatchObject({ baseline_build: 125, target_build: 122 });
  });
});
