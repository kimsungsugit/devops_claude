/**
 * 품질 게이트 조회 섹션 — §6-1 후보 22 (G1·G2·G4).
 *
 * 이 파일이 지키는 것은 화면 배치가 아니라 **정직성 규약**이다. 승인/조회 UI 는
 * "미측정을 통과로 바꾸지 않는다" 는 이 저장소 규약을 정면으로 위협한다:
 *
 *   - `gate_pass` 부재는 PASS 도 FAIL 도 아닌 **'판정 없음'** (프론트 재계산 금지)
 *   - `gated_metric_count` 없는 run 은 **'검사 규모 미기록'** (실측 72.9%가 이 상태)
 *   - `gate_definition:` 마커 없는 run 은 **'게이트 정의 미상'** (마커 보유 51/749)
 *
 * ⚠ `QualityDashboard.jsx:24,86` 의 `?? (score >= 70)` 폴백을 **재사용하지 않는다**.
 *   임계 70 을 프론트에 다시 두면 서버 판정과 갈라진다.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const apiMock = vi.fn();
const postMock = vi.fn();
vi.mock('../api.js', () => ({
  api: (...a) => apiMock(...a),
  post: (...a) => postMock(...a),
}));
const toastMock = vi.fn();
vi.mock('../App.jsx', () => ({ useToast: () => toastMock }));

const GateReviewSection = (await import('../components/sections/GateReviewSection.jsx')).default;

const RUN = (over = {}) => ({
  id: 776, doc_type: 'uds', created_at: '2026-08-03T10:00:00+00:00',
  summary: { overall_score: 82.5, gate_pass: true }, ...over,
});

function routeApi({ runs = [RUN()], detail = null, policy = null, detailThrows = null }) {
  apiMock.mockImplementation(async (path) => {
    if (path.startsWith('/api/quality/runs/')) {
      if (detailThrows) throw detailThrows;
      return detail;
    }
    if (path.startsWith('/api/quality/runs')) return { runs, total: runs.length };
    if (path === '/api/quality/policy') return policy || { tables: [], notes: [] };
    throw new Error(`unexpected ${path}`);
  });
}

beforeEach(() => {
  apiMock.mockReset();
  postMock.mockReset();
  toastMock.mockReset();
});

describe('게이트 판정을 프론트에서 다시 계산하지 않는다', () => {
  it('gate_pass=true → PASS', async () => {
    routeApi({ runs: [RUN()] });
    render(<GateReviewSection />);
    await waitFor(() => expect(screen.getByText('PASS')).toBeInTheDocument());
  });

  it('gate_pass=false → FAIL', async () => {
    routeApi({ runs: [RUN({ summary: { overall_score: 40, gate_pass: false } })] });
    render(<GateReviewSection />);
    await waitFor(() => expect(screen.getByText('FAIL')).toBeInTheDocument());
  });

  it('gate_pass=null 인데 점수가 높아도 PASS 로 그리지 않는다', async () => {
    // ⚠ `QualityDashboard` 의 `?? (score >= 70)` 폴백을 재사용했다면 이 케이스가 PASS 다.
    // ⚠ 배너도 같은 문구를 쓰므로 **표 행 안으로 스코프**한다 — 전역 `getByText` 는
    //    "여러 개" 로 실패하고, 완화하면 배너만 보고 통과하는 공허 테스트가 된다.
    routeApi({ runs: [RUN({ summary: { overall_score: 95, gate_pass: null } })] });
    render(<GateReviewSection />);
    const row = await waitFor(() => screen.getByText('#776').closest('tr'));
    expect(within(row).getByText('판정 없음')).toBeInTheDocument();
    expect(within(row).queryByText('PASS')).toBeNull();
  });

  it('summary 자체가 없으면 판정 없음', async () => {
    routeApi({ runs: [RUN({ summary: null })] });
    render(<GateReviewSection />);
    const row = await waitFor(() => screen.getByText('#776').closest('tr'));
    expect(within(row).getByText('판정 없음')).toBeInTheDocument();
  });
});

describe('검사 규모·판정 정의의 부재를 명시한다', () => {
  const openDetail = async (scores) => {
    routeApi({
      runs: [RUN()],
      detail: { id: 776, doc_type: 'uds', scores },
    });
    render(<GateReviewSection />);
    await waitFor(() => expect(screen.getByRole('button', { name: '근거 보기' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: '근거 보기' }));
    return waitFor(() => screen.getByText(/run #776 게이트 근거/));
  };

  it('gated_metric_count 가 없으면 "검사 규모 미기록"', async () => {
    await openDetail([{ metric_name: 'called_fill', value: 90, gate_pass: true, threshold: 95 }]);
    expect(screen.getByText(/검사 규모 미기록/)).toBeInTheDocument();
    // "가짜" 가 아니라 "판별 불가" 라고 말해야 한다
    expect(screen.getByText(/판별 불가/)).toBeInTheDocument();
  });

  it('gated_metric_count 가 있으면 개수를 보인다', async () => {
    await openDetail([
      { metric_name: 'gated_metric_count', value: 11, gate_pass: null, threshold: null },
    ]);
    expect(screen.getByText(/게이트 대상 지표 11개/)).toBeInTheDocument();
    expect(screen.queryByText(/검사 규모 미기록/)).toBeNull();
  });

  it('gate_definition 마커가 없으면 "게이트 정의 미상"', async () => {
    await openDetail([{ metric_name: 'called_fill', value: 90, gate_pass: true, threshold: 95 }]);
    expect(screen.getByText(/게이트 정의 미상/)).toBeInTheDocument();
  });

  it('gate_definition 마커가 있으면 정의를 보인다', async () => {
    await openDetail([
      { metric_name: 'gate_definition:quick_gate_only', value: 1, gate_pass: null, threshold: null },
    ]);
    expect(screen.getByText(/판정 정의: quick_gate_only/)).toBeInTheDocument();
    expect(screen.queryByText(/게이트 정의 미상/)).toBeNull();
  });

  it('비게이트 지표(threshold=null)는 "—(비게이트)" 로 구분한다', async () => {
    await openDetail([
      { metric_name: 'misra_active_violations', value: 3, gate_pass: null, threshold: null },
    ]);
    const row = screen.getByText('misra_active_violations').closest('tr');
    expect(within(row).getByText('—(비게이트)')).toBeInTheDocument();
  });
});

describe('실패를 성공으로 삼키지 않는다', () => {
  it('상세 조회 404 를 사유와 함께 보인다', async () => {
    const err = new Error('run_id 999999 not found');
    err.status = 404;
    routeApi({ runs: [RUN()], detailThrows: err });
    render(<GateReviewSection />);
    await waitFor(() => expect(screen.getByRole('button', { name: '근거 보기' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: '근거 보기' }));
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/상세를 불러오지 못했습니다/));
  });

  it('HTTP 200 + error 키(옛 계약)도 실패로 처리한다', async () => {
    // 백엔드는 404 로 고쳤지만, 구버전과 붙었을 때 조용히 빈 화면이 되면 안 된다.
    routeApi({ runs: [RUN()], detail: { error: 'run_id 776 not found' } });
    render(<GateReviewSection />);
    await waitFor(() => expect(screen.getByRole('button', { name: '근거 보기' })).toBeEnabled());
    await userEvent.click(screen.getByRole('button', { name: '근거 보기' }));
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/상세를 불러오지 못했습니다/));
  });

  it('403 은 장애가 아니라 권한 상태로 말한다', async () => {
    const err = new Error('forbidden');
    err.status = 403;
    apiMock.mockRejectedValue(err);
    render(<GateReviewSection />);
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/관리자 권한이 필요합니다/));
  });

  it('목록 응답의 error 키도 "이력 0건" 으로 위장하지 않는다', async () => {
    apiMock.mockResolvedValue({ runs: [], total: 0, error: 'quality module not available' });
    render(<GateReviewSection />);
    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/quality module not available/));
  });
});

describe('정책값 표시 (G4)', () => {
  const POLICY = {
    tables: [
      {
        key: 'UDS_QUALITY_GATE_THRESHOLDS', label: 'UDS 품질 게이트 임계값',
        status: 'applied', status_label: '적용됨 — 판정에 쓰인다',
        adjustable: 'env', adjustable_label: '키별 환경변수로 조정 가능',
        entries: [{ key: 'called_min', value: 95, env_name: 'UDS_CALLED_MIN', env_set: false }],
      },
      {
        key: 'TEST_QUALITY_GATES_BY_ASIL', label: 'ASIL별 시험 품질 게이트 프로파일',
        status: 'defined_unused', status_label: '정의만 있고 사용처가 없다',
        adjustable: 'code', adjustable_label: '코드 상수 — env 훅 없음',
        entries: [{ key: 'D', value: { pass_rate_min: 100 }, env_name: null, env_set: false }],
      },
    ],
    notes: ['이 화면은 정책값을 **표시만** 한다'],
  };

  it('적용 여부와 조정 가능 여부를 **따로** 라벨한다', async () => {
    // ⚠ "적용됨 / 미사용" 2분법만으로는 "바꾸려면 어디를 고치나" 를 오독한다.
    routeApi({ runs: [], policy: POLICY });
    render(<GateReviewSection />);
    await userEvent.click(screen.getByRole('tab', { name: '정책값' }));
    await waitFor(() => expect(screen.getByText('적용됨 — 판정에 쓰인다')).toBeInTheDocument());
    expect(screen.getByText('키별 환경변수로 조정 가능')).toBeInTheDocument();
    expect(screen.getByText('정의만 있고 사용처가 없다')).toBeInTheDocument();
    expect(screen.getByText('코드 상수 — env 훅 없음')).toBeInTheDocument();
  });

  it('정책 서브탭을 열기 전에는 조회하지 않는다', async () => {
    routeApi({ runs: [], policy: POLICY });
    render(<GateReviewSection />);
    await waitFor(() => expect(apiMock).toHaveBeenCalled());
    expect(apiMock.mock.calls.some(([p]) => p === '/api/quality/policy')).toBe(false);
  });
});
