/**
 * QualityGateSection — 정직성 계약 회귀.
 *
 * 이 파일은 폐기된 두 테스트(`GateReviewSection.test.jsx`, `QualityDashboard.test.jsx`)의
 * **계약을 이전**한 것이다. 화면 두 벌을 한 벌로 합쳤으므로 테스트도 합친다.
 *
 * 반드시 살아 있어야 하는 것 (출처 = 폐기된 파일들):
 *   - 서버 판정 그대로: `gate_pass=null` 은 95점이어도 **판정 없음**
 *     (옛 `QualityDashboard` 의 `?? (score >= 70)` 폴백이 되살아나면 즉시 실패)
 *   - `gated_metric_count` 부재 → "검사 규모 미기록 / 판별 불가"
 *   - `gate_definition:` 마커 부재 → "게이트 정의 미상"
 *   - 비게이트 지표의 임계 칸은 `—(비게이트)`
 *   - 에러는 전부 `role="alert"`
 *   - 정책 서브탭을 **열기 전엔** `/api/quality/policy` 를 호출하지 않는다(lazy)
 *   - 403 은 장애가 아니라 권한 상태 — 토스트로 반복하지 않는다
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockApi = vi.fn();
const mockPost = vi.fn();
const mockToast = vi.fn();

vi.mock('../api.js', () => ({
  api: (...a) => mockApi(...a),
  post: (...a) => mockPost(...a),
  getUsername: () => 'tester',
}));
vi.mock('../App.jsx', () => ({ useToast: () => mockToast }));

const { default: QualityGateSection } = await import('../components/sections/QualityGateSection.jsx');

function runRow(over = {}) {
  return {
    id: 776, doc_type: 'uds', scm_id: 'hdpdm01', created_at: '2026-08-07T01:00:00+00:00',
    gate_reason: null, meta: null,
    summary: { overall_score: 95.0, gate_pass: null, score_delta: null },
    ...over,
  };
}

/** 목록 응답만 주는 기본 스텁. 상세/정책/추세는 각 테스트가 덮는다. */
function stubApi({ runs = [runRow()], detail = null, policy = null, trend = null, review = null, states = null, history = null } = {}) {
  mockApi.mockImplementation((path) => {
    const p = String(path);
    // (R35) 검토 API 는 quality API 보다 **먼저** 갈라야 한다 — `/runs/\d+$` 가 둘 다 맞는다.
    if (p.includes('/api/review/states')) return Promise.resolve(states || { states: {}, missing: [] });
    if (p.includes('/api/review/history')) return Promise.resolve(history || { items: [], total: 0 });
    if (p.includes('/api/review/runs/')) return Promise.resolve(review || reviewState());
    if (p.includes('/policy')) return Promise.resolve(policy || { tables: [], notes: [] });
    if (p.includes('/trend')) return Promise.resolve({ trend: trend || [] });
    if (/\/runs\/\d+$/.test(p)) return Promise.resolve(detail || { id: 776, scores: [] });
    if (p.includes('/runs')) return Promise.resolve({ runs, total: runs.length });
    return Promise.resolve({});
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  stubApi();
  mockPost.mockResolvedValue({ suggestions: [], summary: '' });
});

describe('QualityGateSection — 서버 판정을 그대로 쓴다', () => {
  it('gate_pass=null 이면 95점이어도 판정 없음이다', async () => {
    render(<QualityGateSection />);
    const tr = await waitFor(() => screen.getByText('#776').closest('tr'));
    expect(within(tr).getByText('판정 없음')).toBeInTheDocument();
    expect(within(tr).queryByText('PASS')).toBeNull();
  });

  it('gate_pass=true 는 PASS, false 는 FAIL', async () => {
    stubApi({ runs: [
      runRow({ id: 1, summary: { overall_score: 10, gate_pass: true } }),
      runRow({ id: 2, summary: { overall_score: 99, gate_pass: false } }),
    ] });
    render(<QualityGateSection />);
    await waitFor(() => expect(screen.getByText('#1')).toBeInTheDocument());
    expect(within(screen.getByText('#1').closest('tr')).getByText('PASS')).toBeInTheDocument();
    expect(within(screen.getByText('#2').closest('tr')).getByText('FAIL')).toBeInTheDocument();
  });

  it('summary 자체가 없으면 판정 없음이고 점수는 대시다', async () => {
    stubApi({ runs: [runRow({ id: 3, summary: null })] });
    render(<QualityGateSection />);
    const tr = await waitFor(() => screen.getByText('#3').closest('tr'));
    expect(within(tr).getByText('판정 없음')).toBeInTheDocument();
    expect(within(tr).getByText('—')).toBeInTheDocument();
  });

  // (R31 Q-6) 같은 run 을 보드는 "판정 불가", 이 목록은 "FAIL" 로 그렸다 — 판정기를 한 곳으로.
  it('목록: gate_reason=no_gated_metric 이면 gate_pass=false 여도 FAIL 이 아니라 판정 불가다', async () => {
    stubApi({ runs: [runRow({ id: 4, gate_reason: 'no_gated_metric',
      summary: { overall_score: 0, gate_pass: false } })] });
    render(<QualityGateSection />);
    const tr = await waitFor(() => screen.getByText('#4').closest('tr'));
    expect(within(tr).getByText('판정 불가')).toBeInTheDocument();
    expect(within(tr).queryByText('FAIL')).toBeNull();
  });

  it('목록: top-level gated_metric_count=0 (scores 없음)만으로도 판정 불가다', async () => {
    stubApi({ runs: [runRow({ id: 5, gated_metric_count: 0,
      summary: { overall_score: 0, gate_pass: false } })] });
    render(<QualityGateSection />);
    const tr = await waitFor(() => screen.getByText('#5').closest('tr'));
    expect(within(tr).getByText('판정 불가')).toBeInTheDocument();
  });

  it('추세: 검사 0건 막대는 빨강(FAIL)이 아니라 판정 불가 색·라벨이다', async () => {
    stubApi({ trend: [
      { run_id: 11, doc_type: 'uds', created_at: '2026-08-07T01:00:00+00:00', overall_score: 40,
        gate_pass: false, gate_reason: 'no_gated_metric', gated_metric_count: 0 },
      { run_id: 12, doc_type: 'uds', created_at: '2026-08-08T01:00:00+00:00', overall_score: 60,
        gate_pass: false, gate_reason: null, gated_metric_count: 7 },
    ] });
    const user = userEvent.setup();
    const { container } = render(<QualityGateSection />);
    await waitFor(() => expect(mockApi).toHaveBeenCalled());
    await user.click(screen.getByRole('tab', { name: '점수 추세' }));
    await waitFor(() => expect(container.querySelectorAll('rect[data-verdict]').length).toBe(2));
    const bars = [...container.querySelectorAll('rect[data-verdict]')];
    expect(bars.map(b => b.getAttribute('data-verdict'))).toEqual(['판정 불가', 'FAIL']);
    expect(bars[0].getAttribute('fill')).not.toBe(bars[1].getAttribute('fill'));
    expect(bars[0].getAttribute('fill')).not.toMatch(/danger/);
    expect(bars[0].querySelector('title').textContent).toMatch(/판정 불가/);
  });
});

describe('QualityGateSection — 근거의 미기록을 명시한다', () => {
  it('gated_metric_count 가 없으면 "검사 규모 미기록 / 판별 불가"라고 말한다', async () => {
    stubApi({ detail: { id: 776, doc_type: 'uds', scores: [
      { metric_name: 'called_pct', value: 99, gate_pass: true, threshold: 95 },
    ] } });
    const user = userEvent.setup();
    render(<QualityGateSection />);
    await waitFor(() => expect(screen.getByText('#776')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: '근거 보기' }));

    await waitFor(() => expect(screen.getByText(/run #776 게이트 근거/)).toBeInTheDocument());
    expect(screen.getByText(/검사 규모 미기록/)).toBeInTheDocument();
    expect(screen.getByText(/판별 불가/)).toBeInTheDocument();
    expect(screen.getByText(/게이트 정의 미상/)).toBeInTheDocument();
  });

  it('마커가 있으면 검사 규모와 판정 정의를 그대로 보인다', async () => {
    stubApi({ detail: { id: 776, doc_type: 'uds', scores: [
      { metric_name: 'gated_metric_count', value: 11, gate_pass: null, threshold: null },
      { metric_name: 'gate_definition:quick_gate_only', value: 1, gate_pass: null, threshold: null },
    ] } });
    const user = userEvent.setup();
    render(<QualityGateSection />);
    await waitFor(() => expect(screen.getByText('#776')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: '근거 보기' }));

    await waitFor(() => expect(screen.getByText(/게이트 대상 지표 11개/)).toBeInTheDocument());
    expect(screen.getByText(/판정 정의: quick_gate_only/)).toBeInTheDocument();
  });

  it('비게이트 지표의 임계 칸은 —(비게이트) 다 (0 으로 그리지 않는다)', async () => {
    stubApi({ detail: { id: 776, doc_type: 'uds', scores: [
      { metric_name: 'global_pct', value: 33, gate_pass: null, threshold: null },
    ] } });
    const user = userEvent.setup();
    render(<QualityGateSection />);
    await waitFor(() => expect(screen.getByText('#776')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: '근거 보기' }));
    await waitFor(() => expect(screen.getByText('—(비게이트)')).toBeInTheDocument());
  });

  it('게이트 사유가 있으면 함께 보인다 (백엔드 gate_reason)', async () => {
    stubApi({
      runs: [runRow({ gate_reason: 'no_gated_metric' })],
      detail: { id: 776, doc_type: 'uds', gate_reason: 'no_gated_metric', scores: [] },
    });
    const user = userEvent.setup();
    render(<QualityGateSection />);
    await waitFor(() => expect(screen.getByText('#776')).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: '근거 보기' }));
    await waitFor(() => expect(screen.getByText(/판정 사유: no_gated_metric/)).toBeInTheDocument());
  });
});

describe('QualityGateSection — 오류를 침묵시키지 않는다', () => {
  it('목록 조회 실패는 role="alert" 로 알린다', async () => {
    mockApi.mockRejectedValue(new Error('boom'));
    render(<QualityGateSection />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/boom/));
  });

  it('200 + error 응답을 성공으로 삼키지 않는다', async () => {
    mockApi.mockResolvedValue({ runs: [], total: 0, error: 'quality module not available' });
    render(<QualityGateSection />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/quality module not available/));
  });

  it('403 은 권한 안내로 바꾸고 토스트로 반복하지 않는다', async () => {
    const err = new Error('Forbidden');
    err.status = 403;
    mockApi.mockRejectedValue(err);
    render(<QualityGateSection />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/권한이 없어/));
    expect(mockToast).not.toHaveBeenCalled();
  });

  it('판정 없는 run 이 섞이면 그 사실을 표시한다', async () => {
    stubApi({ runs: [
      runRow({ id: 1, summary: { overall_score: 90, gate_pass: true } }),
      runRow({ id: 2, summary: null }),
    ] });
    render(<QualityGateSection />);
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent(/1건은/));
    expect(screen.getByRole('status')).toHaveTextContent(/통과도 실패도 아닙니다/);
  });
});

describe('QualityGateSection — lazy 조회', () => {
  it('정책 서브탭을 열기 전엔 /policy 를 호출하지 않는다', async () => {
    const user = userEvent.setup();
    render(<QualityGateSection />);
    await waitFor(() => expect(mockApi).toHaveBeenCalled());
    expect(mockApi.mock.calls.some(c => String(c[0]).includes('/policy'))).toBe(false);

    await user.click(screen.getByRole('tab', { name: '정책값' }));
    await waitFor(() =>
      expect(mockApi.mock.calls.some(c => String(c[0]).includes('/policy'))).toBe(true));
  });

  it('추세 서브탭을 열기 전엔 /trend 를 호출하지 않는다', async () => {
    const user = userEvent.setup();
    render(<QualityGateSection />);
    await waitFor(() => expect(mockApi).toHaveBeenCalled());
    expect(mockApi.mock.calls.some(c => String(c[0]).includes('/trend'))).toBe(false);

    await user.click(screen.getByRole('tab', { name: '점수 추세' }));
    await waitFor(() =>
      expect(mockApi.mock.calls.some(c => String(c[0]).includes('/trend'))).toBe(true));
  });
});

describe('QualityGateSection — 정책값 역할 열 (R29 Q-3)', () => {
  // "적용됨" 표 안에도 판정식에 없는 키(사유 전용)가 있다. 역할은 서버 라벨 그대로 —
  // 프론트가 키 이름으로 역할을 추측하면 판정식과 공시가 다시 갈린다.
  it('서버가 준 role_label 을 키마다 그대로 보이고, 없으면 — 다', async () => {
    stubApi({
      policy: {
        notes: [],
        tables: [{
          key: 'UDS_QUALITY_GATE_THRESHOLDS', label: 'UDS 품질 게이트 임계값',
          status: 'applied', status_label: '적용됨 — 판정 7 · 신뢰도 판정 3 · 사유 전용 2',
          adjustable: 'env', adjustable_label: '키별 환경변수로 조정 가능',
          entries: [
            { key: 'called_min', value: 95, env_name: 'UDS_CALLED_MIN', env_set: false, role: 'gate', role_label: '판정에 쓰인다' },
            { key: 'global_min', value: 40, env_name: 'UDS_GLOBAL_MIN', env_set: false, role: 'reason_only', role_label: '사유 코드에만 쓰인다 — 판정식에 없다' },
            { key: 'legacy_key', value: 1, env_name: null, env_set: false },
          ],
        }, {
          // 미사용 표 — 역할 열이 붙으면 전 행 '—' 라 "역할 미상" 과 "표 미사용" 이 안 갈린다(리뷰 I5)
          key: 'UDS_QUALITY_WARNING_THRESHOLDS', label: "UDS '주의' 밴드",
          status: 'defined_unused', status_label: '정의만 있고 판정에 안 쓰인다',
          adjustable: 'code', adjustable_label: '코드 상수 — env 훅 없음',
          entries: [{ key: 'called_warn', value: 85, env_name: null, env_set: false }],
        }],
      },
    });
    const user = userEvent.setup();
    render(<QualityGateSection />);
    await user.click(screen.getByRole('tab', { name: '정책값' }));

    await waitFor(() => expect(screen.getByRole('columnheader', { name: '역할' })).toBeInTheDocument());
    const rows = screen.getAllByRole('row');
    const rowOf = (key) => rows.find((r) => within(r).queryByText(key));
    expect(within(rowOf('called_min')).getByText('판정에 쓰인다')).toBeInTheDocument();
    expect(within(rowOf('global_min')).getByText(/사유 코드에만 쓰인다/)).toBeInTheDocument();
    expect(within(rowOf('legacy_key')).getAllByText('—').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/사유 전용 2/)).toBeInTheDocument();
    // 적용 표에만 역할 열 — 미사용 표의 행은 셀이 3개다
    expect(screen.getAllByRole('columnheader', { name: '역할' })).toHaveLength(1);
    expect(within(rowOf('called_warn')).getAllByRole('cell')).toHaveLength(3);
    expect(within(rowOf('called_min')).getAllByRole('cell')).toHaveLength(4);
  });
});

describe('QualityGateSection — 프로젝트 스코프 (두 진입을 한 컴포넌트로)', () => {
  it('analysisResult 가 있으면 그 프로젝트로 좁힌다', async () => {
    render(<QualityGateSection analysisResult={{ matchedScm: { id: 'kjpds02', name: 'KJPDS02' } }} />);
    await waitFor(() => expect(mockApi).toHaveBeenCalled());
    expect(String(mockApi.mock.calls[0][0])).toContain('scm_id=kjpds02');
    expect(screen.getByText(/프로젝트 KJPDS02/)).toBeInTheDocument();
  });

  it('analysisResult 가 없으면 전체 스코프이고 프로젝트 열이 생긴다', async () => {
    render(<QualityGateSection />);
    await waitFor(() => expect(mockApi).toHaveBeenCalled());
    expect(String(mockApi.mock.calls[0][0])).not.toContain('scm_id=');
    expect(screen.getByText('전체 프로젝트')).toBeInTheDocument();
    // 전역에서는 어느 프로젝트의 run 인지 알아야 한다
    expect(screen.getByRole('columnheader', { name: '프로젝트' })).toBeInTheDocument();
  });

  it('프로젝트 스코프에서는 프로젝트 열을 중복 표시하지 않는다', async () => {
    render(<QualityGateSection analysisResult={{ matchedScm: { id: 'kjpds02' } }} />);
    await waitFor(() => expect(screen.getByText('#776')).toBeInTheDocument());
    expect(screen.queryByRole('columnheader', { name: '프로젝트' })).toBeNull();
  });

  it('scm_id 가 없는 run 은 "미상" 으로 표시한다 (빈 칸으로 두지 않는다)', async () => {
    stubApi({ runs: [runRow({ scm_id: null })] });
    render(<QualityGateSection />);
    const tr = await waitFor(() => screen.getByText('#776').closest('tr'));
    expect(within(tr).getByText('미상')).toBeInTheDocument();
  });
});

describe('QualityGateSection — 접근성', () => {
  it('탭에 roving tabIndex 와 ARIA 결합이 있다', async () => {
    render(<QualityGateSection />);
    const active = screen.getByRole('tab', { name: '실행 이력' });
    expect(active).toHaveAttribute('aria-controls', 'qgate-panel-runs');
    expect(active).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('tab', { name: '정책값' })).toHaveAttribute('tabindex', '-1');
  });

  it('ArrowRight 로 다음 서브탭으로 이동한다 (옛 화면엔 키보드 네비가 없었다)', async () => {
    const user = userEvent.setup();
    render(<QualityGateSection />);
    screen.getByRole('tab', { name: '실행 이력' }).focus();
    await user.keyboard('{ArrowRight}');
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: '점수 추세' })).toHaveAttribute('aria-selected', 'true'));
  });
});


// ─────────────────────────────────────────────────────────────────────────────
// (R35 C-3) 검토 기록 — 열 · 패널 · 이력. 라벨은 gateVerdict.js 의 것을 그대로 기대한다.
// ─────────────────────────────────────────────────────────────────────────────

const SHA = 'a'.repeat(64);

function reviewState(over = {}) {
  return {
    run_id: 776, doc_type: 'uds', scm_id: 'hdpdm01', output_path: 'x.docx', output_sha256: SHA,
    hash_reason: null, superseded_by: null, gated_metric_count: 5, reviews: [],
    hash_unavailable: false, current_sha256: SHA, current_basis: 'file', current_basis_reason: null,
    stale: false, can_review: true,
    ...over,
  };
}

function reviewRec(over = {}) {
  return {
    id: 1, run_id: 776, reviewer: 'tester', auth_method: 'jwt', decision: 'approved', comment: 'ok',
    output_sha256: SHA, version: 1, created_at: '2026-09-07T01:00:00+00:00', updated_at: '2026-09-07T01:00:00+00:00',
    stale: false, ...over,
  };
}

const cellOf = (id) => screen.getByTestId(`review-cell-${id}`);
const statesCalls = () => mockApi.mock.calls.filter((c) => String(c[0]).includes('/api/review/states'));

describe('QualityGateSection — 검토 열 (R35)', () => {
  it('해시 없는 run 은 목록 값만으로 검토 잠금이고 배치 조회를 부르지 않는다', async () => {
    stubApi({ runs: [runRow({ id: 1, output_sha256: null })] });
    render(<QualityGateSection />);
    await waitFor(() => expect(cellOf(1)).toHaveTextContent('검토 잠금(해시 없음)'));
    expect(statesCalls()).toHaveLength(0);
  });

  it('해시 있는 run 만 모아 한 번에 조회하고 서버 판정을 그대로 그린다', async () => {
    stubApi({
      runs: [
        runRow({ id: 1, output_sha256: SHA }), runRow({ id: 2, output_sha256: SHA }),
        runRow({ id: 3, output_sha256: SHA }), runRow({ id: 4, output_sha256: SHA }), runRow({ id: 5, output_sha256: null }),
      ],
      states: { states: {
        1: reviewState({ reviews: [reviewRec({ decision: 'approved', stale: false })] }),
        2: reviewState({ reviews: [] }),
        3: reviewState({ reviews: [reviewRec({ decision: 'rejected', stale: true })] }),
        4: reviewState({ reviews: [reviewRec({ decision: 'needs_work', stale: null })], current_basis: 'record' }),
      }, missing: [] },
    });
    render(<QualityGateSection />);
    await waitFor(() => expect(cellOf(1)).toHaveTextContent('승인됨'));
    expect(statesCalls()).toHaveLength(1);
    expect(String(statesCalls()[0][0])).toMatch(/run_ids=1,2,3,4$/);
    expect(cellOf(2)).toHaveTextContent('미검토');
    expect(cellOf(3)).toHaveTextContent('반려 · stale');
    // stale=null 은 최신이 아니다 — '보완 필요' 만 쓰면 판단 불가를 통과처럼 읽는다.
    expect(cellOf(4)).toHaveTextContent('보완 필요 · 최신성 판단 불가');
    expect(cellOf(5)).toHaveTextContent('검토 잠금(해시 없음)');
  });

  it('배치 조회가 실패하면 열은 빈칸이 아니라 "조회 실패" 다(해시 없는 run 은 여전히 잠금)', async () => {
    stubApi({ runs: [runRow({ id: 1, output_sha256: SHA }), runRow({ id: 2, output_sha256: null })] });
    mockApi.mockImplementation((path) => {
      const p = String(path);
      if (p.includes('/api/review/states')) return Promise.reject(new Error('down'));
      if (p.includes('/runs')) return Promise.resolve({ runs: [runRow({ id: 1, output_sha256: SHA }), runRow({ id: 2, output_sha256: null })], total: 2 });
      return Promise.resolve({});
    });
    render(<QualityGateSection />);
    await waitFor(() => expect(cellOf(1)).toHaveTextContent('검토 상태 조회 실패'));
    expect(cellOf(2)).toHaveTextContent('검토 잠금(해시 없음)');
  });
});

describe('QualityGateSection — 검토 패널 (R35)', () => {
  async function openPanel(user) {
    render(<QualityGateSection />);
    await waitFor(() => screen.getByText('#776'));
    await user.click(screen.getByRole('button', { name: '근거 보기' }));
    return waitFor(() => screen.getByTestId('review-panel'));
  }

  it('해시 없는 run 은 검토 잠금 문구 + 사유 미기록을 적고 폼을 그리지 않는다', async () => {
    const user = userEvent.setup();
    stubApi({ review: reviewState({ output_sha256: null, hash_unavailable: true, hash_reason: null, current_basis: null }) });
    const panel = await openPanel(user);
    expect(within(panel).getByRole('status')).toHaveTextContent(/검토 잠금/);
    expect(within(panel).getByRole('status')).toHaveTextContent(/미기록/);
    expect(within(panel).queryByRole('radio')).toBeNull();
  });

  it('해시 사유가 기록된 run 은 토큰과 함께 그 뜻을 보인다', async () => {
    const user = userEvent.setup();
    stubApi({ review: reviewState({ output_sha256: null, hash_unavailable: true, hash_reason: 'file_missing' }) });
    const panel = await openPanel(user);
    expect(within(panel).getByRole('status')).toHaveTextContent('file_missing');
    expect(within(panel).getByRole('status')).toHaveTextContent(/기록된 경로에 파일이 없습니다/);
  });

  it('배선 실패 사유(no_bytes)는 \'정상\' 이 아니라 문제로 읽히게 적는다 (R36 리뷰 W2)', async () => {
    const user = userEvent.setup();
    stubApi({ review: reviewState({ output_sha256: null, hash_unavailable: true, hash_reason: 'no_bytes' }) });
    const panel = await openPanel(user);
    expect(within(panel).getByRole('status')).toHaveTextContent(/기록 배선 문제/);
  });

  it('admin 이면 폼이 있고, 저장은 서버 해시를 그대로 보내며 성공 토스트는 2xx 뒤에만 뜬다', async () => {
    const user = userEvent.setup();
    stubApi({ review: reviewState() });
    let resolvePost;
    mockPost.mockImplementation(() => new Promise((res) => { resolvePost = res; }));
    const panel = await openPanel(user);
    await user.click(within(panel).getByRole('radio', { name: '승인됨' }));
    await user.type(within(panel).getByRole('textbox', { name: '검토 사유' }), 'looks fine');
    await user.click(within(panel).getByRole('button', { name: '저장' }));
    expect(mockPost).toHaveBeenCalledWith('/api/review/runs/776', {
      decision: 'approved', comment: 'looks fine', expected_sha256: SHA,
    });
    expect(mockToast).not.toHaveBeenCalled();   // 아직 응답 전
    const runsBefore = mockApi.mock.calls.filter((c) => /\/api\/quality\/runs\?/.test(String(c[0]))).length;
    resolvePost({ created: true, record: reviewRec() });
    await waitFor(() => expect(mockToast).toHaveBeenCalledWith('success', expect.stringMatching(/저장/)));
    // 목록의 검토 열도 다시 받는다.
    await waitFor(() => expect(
      mockApi.mock.calls.filter((c) => /\/api\/quality\/runs\?/.test(String(c[0]))).length,
    ).toBeGreaterThan(runsBefore));
  });

  it('내 기록이 있으면 version 을 실어 갱신한다', async () => {
    const user = userEvent.setup();
    stubApi({ review: reviewState({ reviews: [reviewRec({ reviewer: 'tester', version: 3, decision: 'needs_work', comment: 'fix' })] }) });
    mockPost.mockResolvedValue({ created: false, record: reviewRec({ version: 4 }) });
    const panel = await openPanel(user);
    expect(within(panel).getByRole('radio', { name: '보완 필요' })).toBeChecked();
    await user.click(within(panel).getByRole('radio', { name: '승인됨' }));
    await user.click(within(panel).getByRole('button', { name: '갱신' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    expect(mockPost.mock.calls[0][1]).toMatchObject({ decision: 'approved', expected_sha256: SHA, version: 3 });
    await waitFor(() => expect(mockToast).toHaveBeenCalledWith('success', expect.stringMatching(/갱신/)));
  });

  it.each([
    ['STALE', 409, /검토 시점과 다릅니다/],
    ['VERSION_CONFLICT', 409, /먼저 반영/],
    ['JWT_REQUIRED', 401, /토큰이 필요/],
    ['DB_BUSY', 503, /잠겨/],
  ])('%s 는 성공 토스트 없이 그 뜻의 문장으로 알린다', async (code, status, re) => {
    const user = userEvent.setup();
    stubApi({ review: reviewState() });
    const err = new Error('server says'); err.status = status; err.code = code;
    mockPost.mockRejectedValue(err);
    const panel = await openPanel(user);
    const getCalls = () => mockApi.mock.calls.filter((c) => String(c[0]) === '/api/review/runs/776').length;
    const before = getCalls();
    await user.click(within(panel).getByRole('radio', { name: '반려' }));
    await user.click(within(panel).getByRole('button', { name: '저장' }));
    await waitFor(() => expect(mockToast).toHaveBeenCalledWith('error', expect.stringMatching(re)));
    expect(mockToast).not.toHaveBeenCalledWith('success', expect.anything());
    if (code === 'STALE' || code === 'VERSION_CONFLICT') {
      // 지금 값을 다시 받아야 다음 저장이 뜻을 갖는다.
      await waitFor(() => expect(getCalls()).toBeGreaterThan(before));
    }
  });

  it('403 은 코드가 없어도 권한 상태 문장이다', async () => {
    const user = userEvent.setup();
    stubApi({ review: reviewState() });
    const err = new Error('Forbidden'); err.status = 403; err.code = 'HTTP_403';
    mockPost.mockRejectedValue(err);
    const panel = await openPanel(user);
    await user.click(within(panel).getByRole('radio', { name: '반려' }));
    await user.click(within(panel).getByRole('button', { name: '저장' }));
    await waitFor(() => expect(mockToast).toHaveBeenCalledWith('error', expect.stringMatching(/권한이 없습니다/)));
  });

  it('can_review=false 면 폼 대신 권한 문구다 (오류가 아니다)', async () => {
    const user = userEvent.setup();
    stubApi({ review: reviewState({ can_review: false, review_block_reason: 'not_admin' }) });
    const panel = await openPanel(user);
    expect(within(panel).queryByRole('radio')).toBeNull();
    expect(within(panel).getByRole('status')).toHaveTextContent(/admin 만/);
    expect(within(panel).queryByRole('alert')).toBeNull();
  });

  it('토큰이 없어서 막힌 것을 권한 문제로 적지 않는다 (R37 D-1)', async () => {
    const user = userEvent.setup();
    stubApi({ review: reviewState({ can_review: false, review_block_reason: 'jwt_required' }) });
    const panel = await openPanel(user);
    const note = within(panel).getByRole('status');
    // 벗어나는 길이 다르다 — 재로그인하면 되는 사람에게 '권한 없음' 을 보이면 관리자를 찾아간다.
    expect(note).toHaveTextContent(/다시 로그인/);
    expect(note).toHaveTextContent(/권한 문제가 아닙니다/);
    expect(note.textContent).not.toMatch(/admin 만 남길/);
  });

  it('superseded_by 와 stale 을 서버 값 그대로 적는다', async () => {
    const user = userEvent.setup();
    stubApi({ review: reviewState({
      stale: true, superseded_by: { run_id: 900, created_at: '2026-09-07T02:00:00+00:00' },
      reviews: [reviewRec({ stale: true })],
    }) });
    const panel = await openPanel(user);
    expect(within(panel).getByText(/#900/)).toBeInTheDocument();
    expect(within(panel).getByText(/지금 파일이 이 run 의 기록과 다릅니다/)).toBeInTheDocument();
    expect(within(panel).getByText(/stale — 지금 파일이 검토 시점과 다릅니다/)).toBeInTheDocument();
    // (R36) 재생성 결정론이 없다는 사실을 화면이 말하되 **단정하지 않는다**(리뷰 W4 — 같은 초 안 재생성은 해시가 같다).
    expect(within(panel).getByText(/다시 생성하면 대개 해시가 달라집니다/)).toBeInTheDocument();
    expect(within(panel).getByText(/같은 run 이라는 뜻은 아닙니다/)).toBeInTheDocument();
    expect(within(panel).queryByText(/생성마다 해시가 다릅니다/)).toBeNull();
  });

  it('레코드 stale=null 은 "일치" 가 아니라 판단 불가다', async () => {
    const user = userEvent.setup();
    stubApi({ review: reviewState({ stale: null, current_basis: 'record', current_basis_reason: 'file_missing',
      reviews: [reviewRec({ stale: null })] }) });
    const panel = await openPanel(user);
    expect(within(panel).getByText(/최신성 판단 불가/)).toBeInTheDocument();
    expect(within(panel).queryByText(/지금 파일과 일치/)).toBeNull();
  });

  it('경로 없는 산출물의 판단 불가는 고장이 아니라 구조라고 적고, 대조 방법을 준다 (리뷰 I6)', async () => {
    const user = userEvent.setup();
    stubApi({ review: reviewState({ stale: null, current_basis: 'record', current_basis_reason: 'no_path' }) });
    const panel = await openPanel(user);
    expect(within(panel).getByText(/사본을 갖고 있지 않아/)).toBeInTheDocument();
    expect(within(panel).getByText(/Get-FileHash/)).toBeInTheDocument();
  });

  it('조회 실패는 role="alert" 다', async () => {
    const user = userEvent.setup();
    stubApi();
    mockApi.mockImplementation((path) => {
      const p = String(path);
      if (p.includes('/api/review/runs/')) return Promise.reject(new Error('boom'));
      if (/\/runs\/\d+$/.test(p)) return Promise.resolve({ id: 776, scores: [] });
      if (p.includes('/runs')) return Promise.resolve({ runs: [runRow()], total: 1 });
      return Promise.resolve({});
    });
    const panel = await openPanel(user);
    await waitFor(() => expect(within(panel).getByRole('alert')).toHaveTextContent(/boom/));
  });

  // ── (R37 리뷰 C1) 빈 산출물 run 의 검토 ──────────────────────────────────
  it('빈 산출물이면 무엇을 승인하는지 말하고, "검사 규모 미기록" 과 갈라 놓는다', async () => {
    const user = userEvent.setup();
    stubApi({
      review: reviewState({
        status: 'empty_output',
        empty_output_reason: 'empty:total_tcs',
        gated_metric_count: null,
        can_review: true,
      }),
    });
    const panel = await openPanel(user);
    // `<strong>` 과 그 부모 둘 다 매치되므로 개수로 본다 — 정확히 어디에 있는지가 아니라 보이는가가 요점.
    expect(within(panel).getAllByText(/담을 내용이 0건/).length).toBeGreaterThan(0);
    expect(within(panel).getAllByText(/빈 문서에 대한 승인/).length).toBeGreaterThan(0);
    // 어느 축이 비었는지·어디를 되짚는지도 같은 자리에서 말한다.
    expect(within(panel).getByText(/시험 케이스가 0건/)).toBeInTheDocument();
    // 원인 오귀속 금지 — 이 문구는 *구 run(기록 이전)* 을 뜻한다.
    expect(within(panel).queryByText(/검사 규모 미기록/)).toBeNull();
    // 잠그는 게 아니라 말하는 것이다 — 해시가 있으면 폼은 열려 있어야 한다.
    expect(within(panel).queryAllByRole('radio').length).toBeGreaterThan(0);
  });

  it('빈 산출물이 아닌 run 의 "검사 규모 미기록" 문구는 그대로다', async () => {
    const user = userEvent.setup();
    stubApi({ review: reviewState({ gated_metric_count: null, can_review: true }) });
    const panel = await openPanel(user);
    expect(within(panel).getByText(/검사 규모 미기록/)).toBeInTheDocument();
    expect(within(panel).queryAllByText(/담을 내용이 0건/)).toHaveLength(0);
  });
});

describe('QualityGateSection — 검토 이력 서브탭 (R35)', () => {
  it('열기 전엔 /history 를 부르지 않고, 열면 스코프대로 부른다', async () => {
    const user = userEvent.setup();
    stubApi({ history: { items: [
      { id: 9, review_id: 1, run_id: 776, doc_type: 'uds', scm_id: 'hdpdm01', reviewer: 'tester', action: 'create',
        decision: 'approved', output_sha256: SHA, created_at: '2026-09-07T01:00:00+00:00' },
    ], total: 1 } });
    render(<QualityGateSection analysisResult={{ matchedScm: { id: 'hdpdm01', name: 'H' } }} />);
    await waitFor(() => expect(mockApi).toHaveBeenCalled());
    expect(mockApi.mock.calls.some((c) => String(c[0]).includes('/api/review/history'))).toBe(false);
    await user.click(screen.getByRole('tab', { name: '검토 이력' }));
    await waitFor(() => expect(mockApi.mock.calls.some((c) => String(c[0]).includes('/api/review/history'))).toBe(true));
    const call = mockApi.mock.calls.find((c) => String(c[0]).includes('/api/review/history'));
    expect(String(call[0])).toMatch(/scm_id=hdpdm01/);
    const panel = screen.getByRole('tabpanel', { name: '검토 이력' });
    await waitFor(() => expect(within(panel).getByText('승인됨')).toBeInTheDocument());
    expect(within(panel).getByText('생성')).toBeInTheDocument();
  });

  it('이력 조회 실패는 role="alert" 다', async () => {
    const user = userEvent.setup();
    stubApi();
    mockApi.mockImplementation((path) => {
      const p = String(path);
      if (p.includes('/api/review/history')) return Promise.reject(new Error('hist down'));
      if (p.includes('/runs')) return Promise.resolve({ runs: [], total: 0 });
      return Promise.resolve({});
    });
    render(<QualityGateSection />);
    await user.click(screen.getByRole('tab', { name: '검토 이력' }));
    const panel = screen.getByRole('tabpanel', { name: '검토 이력' });
    await waitFor(() => expect(within(panel).getByRole('alert')).toHaveTextContent(/hist down/));
  });
});


describe('QualityGateSection — 리뷰 반영 (R35 C1/W1/W2/W5)', () => {
  it('run 을 갈아타면 패널이 새로 조회하고 옛 run 의 해시·version 을 보내지 않는다 (C1)', async () => {
    const user = userEvent.setup();
    const SHA_A = 'a'.repeat(64), SHA_B = 'c'.repeat(64);
    let resolveRun2;
    mockApi.mockImplementation((path) => {
      const p = String(path);
      if (p === '/api/review/runs/1') return Promise.resolve(reviewState({ run_id: 1, output_sha256: SHA_A, reviews: [reviewRec({ run_id: 1, version: 7, output_sha256: SHA_A })] }));
      // #2 는 보류 — 갈아타는 **사이**에 #1 의 state 가 남아 있으면 그게 C1 이다.
      if (p === '/api/review/runs/2') return new Promise((res) => { resolveRun2 = res; });
      if (p.includes('/api/review/states')) return Promise.resolve({ states: {}, missing: [] });
      if (/\/runs\/\d+$/.test(p)) return Promise.resolve({ id: Number(p.split('/').pop()), scores: [] });
      if (p.includes('/runs')) return Promise.resolve({ runs: [runRow({ id: 1, output_sha256: SHA_A }), runRow({ id: 2, output_sha256: SHA_B })], total: 2 });
      return Promise.resolve({});
    });
    mockPost.mockResolvedValue({ created: true, record: reviewRec() });
    render(<QualityGateSection />);
    await waitFor(() => screen.getByText('#1'));
    const buttons = () => screen.getAllByRole('button', { name: '근거 보기' });
    await user.click(buttons()[0]);
    await waitFor(() => expect(screen.getByTestId('review-panel')).toHaveTextContent('run #1 검토 기록'));
    await waitFor(() => expect(within(screen.getByTestId('review-panel')).getByRole('button', { name: '갱신' })).toBeInTheDocument());
    // run #2 로 갈아탄다 — 패널은 #2 를 새로 받아야 하고 #1 의 폼 값이 남으면 안 된다.
    await user.click(screen.getAllByRole('button', { name: /근거 보기|접기/ })[1]);
    await waitFor(() => expect(screen.getByTestId('review-panel')).toHaveTextContent('run #2 검토 기록'));
    // 응답 전: #1 의 기록 표·'갱신' 버튼·(나) 표시가 #2 제목 아래 남아 있으면 안 된다.
    expect(within(screen.getByTestId('review-panel')).queryByRole('button', { name: '갱신' })).toBeNull();
    expect(within(screen.getByTestId('review-panel')).queryByText(/\(나\)/)).toBeNull();
    resolveRun2(reviewState({ run_id: 2, output_sha256: SHA_B, reviews: [] }));
    const panel = screen.getByTestId('review-panel');
    await waitFor(() => expect(within(panel).getByRole('button', { name: '저장' })).toBeInTheDocument());
    expect(within(panel).getByText(/검토 기록이 없습니다/)).toBeInTheDocument();
    await user.click(within(panel).getByRole('radio', { name: '승인됨' }));
    await user.click(within(panel).getByRole('button', { name: '저장' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalled());
    expect(mockPost.mock.calls[0][0]).toBe('/api/review/runs/2');
    expect(mockPost.mock.calls[0][1]).toMatchObject({ expected_sha256: SHA_B });
    expect(mockPost.mock.calls[0][1]).not.toHaveProperty('version');
  });

  it('서버 missing 은 "조회 중" 이 아니라 "run 을 찾을 수 없음" 이고, 응답에서 빠진 id 는 실패다 (W1)', async () => {
    stubApi({
      runs: [runRow({ id: 1, output_sha256: SHA }), runRow({ id: 2, output_sha256: SHA }), runRow({ id: 3, output_sha256: SHA })],
      states: { states: { 1: reviewState({ reviews: [] }) }, missing: [2] },
    });
    render(<QualityGateSection />);
    await waitFor(() => expect(cellOf(1)).toHaveTextContent('미검토'));
    expect(cellOf(2)).toHaveTextContent('run 을 찾을 수 없음');
    expect(cellOf(3)).toHaveTextContent('검토 상태 조회 실패');
    expect(screen.queryByText('조회 중…')).toBeNull();
  });

  it('검토자 판정이 갈리면 열은 대표 1건이 아니라 "판정 갈림" 이다 (W2)', async () => {
    stubApi({
      runs: [runRow({ id: 1, output_sha256: SHA })],
      states: { states: { 1: reviewState({ reviews: [
        reviewRec({ id: 1, reviewer: 'old', decision: 'rejected', updated_at: '2026-09-01T00:00:00+00:00' }),
        reviewRec({ id: 2, reviewer: 'new', decision: 'approved', updated_at: '2026-09-07T00:00:00+00:00' }),
      ] }) }, missing: [] },
    });
    render(<QualityGateSection />);
    await waitFor(() => expect(cellOf(1)).toHaveTextContent('판정 갈림 2종'));
    expect(cellOf(1)).not.toHaveTextContent('승인됨');
  });

  it('배치 조회 실패 사유는 hover 가 아니라 role="alert" 에도 있다 (W5)', async () => {
    mockApi.mockImplementation((path) => {
      const p = String(path);
      if (p.includes('/api/review/states')) { const e = new Error('states down'); e.status = 500; return Promise.reject(e); }
      if (p.includes('/runs')) return Promise.resolve({ runs: [runRow({ id: 1, output_sha256: SHA })], total: 1 });
      return Promise.resolve({});
    });
    render(<QualityGateSection />);
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/states down/));
  });
});

describe('검토 대상 해시는 전체가 보여야 한다 (R39 N3)', () => {
  it('64자 전부를 화면에서 꺼낼 수 있다 — 수동 대조가 유일한 검증 경로인 run 이 있다', async () => {
    const user = userEvent.setup();
    // 서버가 파일 사본을 못 가진 run(`basis='record'`)은 아래 `Get-FileHash` 수동 대조가
    // **유일한** 검증 경로다. 앞판은 앞 12자만 보여 그 경로가 끊겨 있었다(48비트 접두는 증거가 아니다).
    stubApi({ review: reviewState({ current_basis: 'record', current_basis_reason: 'no_path', stale: null }) });
    render(<QualityGateSection />);
    await waitFor(() => screen.getByText('#776'));
    await user.click(screen.getByRole('button', { name: '근거 보기' }));
    const panel = await waitFor(() => screen.getByTestId('review-panel'));
    const code = within(panel).getByTitle(SHA);
    expect(code.textContent).toBe(SHA);
    expect(code.textContent.length).toBe(64);
    // 안내 문구가 가리키는 대조 수단도 함께 있어야 한다 — 값만 있고 방법이 없으면 반쪽이다.
    expect(within(panel).getByText(/Get-FileHash/)).toBeInTheDocument();
  });
});

// (R42 N17) 서버는 제안마다 `gated` 를 실어 보낸다 — 평가기가 그 축으로 판정했는가.
// 화면이 그걸 안 읽으면 게이트가 재지도 않은 축의 임계가 "미달" 로 읽힌다.
describe('개선 제안 — 게이트 축과 참고 축을 구별한다', () => {
  it('gated=false 제안은 참고임을 문구로 밝힌다', async () => {
    const user = userEvent.setup();
    mockPost.mockResolvedValue({
      suggestions: [
        { metric: 'logic_flow_pct', label: '로직 흐름', value: 0, threshold: 40, gated: false, advice: '단순 함수일 수 있습니다' },
        { metric: 'pass_rate_pct', label: '통과율', value: 50, threshold: 100, gated: true, advice: '실패 TC 를 보세요' },
      ],
      summary: '',
    });
    render(<QualityGateSection />);
    await user.click(await screen.findByRole('button', { name: '근거 보기' }));
    await user.click(await screen.findByRole('button', { name: '개선 제안 생성' }));

    const relaxed = await screen.findByText('로직 흐름');
    expect(relaxed.closest('li').textContent).toContain('게이트 항목 아님');
    // 대조군 — 게이트 축엔 그 꼬리표가 붙지 않는다(전부 참고로 보이면 구별이 사라진다).
    expect(screen.getByText('통과율').closest('li').textContent).not.toContain('게이트 항목 아님');
  });
});
