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
function stubApi({ runs = [runRow()], detail = null, policy = null, trend = null } = {}) {
  mockApi.mockImplementation((path) => {
    const p = String(path);
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
