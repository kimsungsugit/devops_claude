/**
 * DocGenStatusBoard — **정직성 규약** 회귀.
 *
 * 이 보드가 위험한 이유는 한 화면에서 여러 종류의 "모름" 을 다루기 때문이다.
 * 모르는 걸 좋게 그리면 그게 곧 거짓 증거다(ISO 26262 산출물 화면). 아래 테스트의
 * 절반은 **음성 대조군** 이다 — "PASS 라고 쓰지 않는가", "0 이라고 쓰지 않는가".
 *
 * 특히 첫 두 개는 실제로 있었던 결함을 겨눈다:
 *   - `QualityDashboard` 가 `gate_pass ?? (score >= 70)` 로 **통과를 지어냈다**.
 *   - 백엔드가 `all([])`=True 라 **검사 0건을 PASS 로 기록**했다(fail-closed 로 수정).
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

const { default: DocGenStatusBoard } = await import('../components/sections/DocGenStatusBoard.jsx');

const JOB = { url: 'http://ci/job/X', name: 'X' };
const ANALYSIS = { matchedScm: { id: 'kjpds02_pv', name: 'KJPDS02_PV' } };

/** include_scores=true 응답 형태의 run. */
function run(over = {}) {
  return {
    id: 1, doc_type: 'uds', scm_id: 'kjpds02_pv', project_root: 'D:/src',
    created_at: '2026-08-07T01:00:00+00:00', output_path: 'X:/out/spec.docx',
    meta: null, error_msg: null, gate_reason: null,
    summary: { overall_score: 92.4, gate_pass: true, score_delta: 1.2, prev_run_id: 0, fn_count: 169 },
    scores: [{ metric_name: 'gated_metric_count', value: 7, gate_pass: null, threshold: null }],
    ...over,
  };
}

const rowOf = (label) => screen.getByText(new RegExp(`^${label}$`)).closest('tr')
  || screen.getByText(label).closest('tr');

function mountBoard(props = {}) {
  return render(
    <DocGenStatusBoard job={JOB} analysisResult={ANALYSIS} genState={null}
      onGenerate={props.onGenerate} onNavigateSub={props.onNavigateSub} {...props} />
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApi.mockResolvedValue({ runs: [], total: 0 });
  mockPost.mockResolvedValue({ suggestions: [] });
});

describe('DocGenStatusBoard — 판정을 지어내지 않는다', () => {
  it('gate_pass=null 이면 점수가 높아도 PASS 라고 쓰지 않는다', async () => {
    mockApi.mockResolvedValue({
      runs: [run({ summary: { overall_score: 95.0, gate_pass: null, score_delta: null } })],
      total: 1,
    });
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    expect(within(tr).getByText('판정 없음')).toBeInTheDocument();
    expect(within(tr).queryByText('PASS')).toBeNull();
  });

  it('검사 항목이 0개면 판정 불가다 (PASS/FAIL 어느 쪽도 아님)', async () => {
    mockApi.mockResolvedValue({
      runs: [run({
        gate_reason: 'no_gated_metric',
        summary: { overall_score: 0, gate_pass: false, score_delta: null },
        scores: [{ metric_name: 'gated_metric_count', value: 0, gate_pass: null, threshold: null }],
      })],
      total: 1,
    });
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    expect(within(tr).getByText('판정 불가')).toBeInTheDocument();
    expect(within(tr).queryByText('FAIL')).toBeNull();
    expect(within(tr).getByText(/검사 항목이 0개/)).toBeInTheDocument();
  });

  it('gated_metric_count 가 0 이면 사유가 없어도 판정 불가다', async () => {
    // 구 run 은 `gate_reason` 이 없다 — 지표 값만으로도 잡아야 한다.
    mockApi.mockResolvedValue({
      runs: [run({
        gate_reason: null,
        summary: { overall_score: 0, gate_pass: true, score_delta: null },
        scores: [{ metric_name: 'gated_metric_count', value: 0, gate_pass: null, threshold: null }],
      })],
      total: 1,
    });
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    expect(within(tr).getByText('판정 불가')).toBeInTheDocument();
  });

  it('생성한 적 없는 문서는 미생성이고 점수가 0 이 아니다', async () => {
    mockApi.mockResolvedValue({ runs: [], total: 0 });
    mountBoard();
    const tr = await waitFor(() => rowOf('📕 SITS'));
    expect(within(tr).getByText('미생성')).toBeInTheDocument();
    expect(within(tr).getByText(/아직 생성하지 않음/)).toBeInTheDocument();
    // 점수 칸이 '0' 이나 '0.0' 이면 "0점을 받았다" 로 읽힌다 → 반드시 대시
    expect(within(tr).queryByText('0.0')).toBeNull();
    expect(within(tr).getAllByText('—').length).toBeGreaterThan(0);
  });
});

describe('DocGenStatusBoard — 왜 이 점수인가', () => {
  it('FAIL 이면 임계와 격차가 가장 큰 지표를 이유로 든다', async () => {
    mockApi.mockResolvedValue({
      runs: [run({
        doc_type: 'sts',
        summary: { overall_score: 61.0, gate_pass: false, score_delta: -3.1 },
        scores: [
          { metric_name: 'completeness_pct', value: 78.0, gate_pass: false, threshold: 80.0 },   // gap 2
          { metric_name: 'requirement_coverage_pct', value: 52.0, gate_pass: false, threshold: 70.0 }, // gap 18 ← 최악
          { metric_name: 'gated_metric_count', value: 2, gate_pass: null, threshold: null },
        ],
      })],
      total: 1,
    });
    mountBoard();
    const tr = await waitFor(() => rowOf('📗 STS'));
    expect(within(tr).getByText(/요구 커버리지 52.0% < 70.0%/)).toBeInTheDocument();
    expect(within(tr).getByText(/외 1건/)).toBeInTheDocument();
  });

  it('FAIL 인데 실패 지표가 없으면 그 사실을 말한다 (빈 칸으로 두지 않는다)', async () => {
    mockApi.mockResolvedValue({
      runs: [run({
        summary: { overall_score: 40, gate_pass: false, score_delta: null },
        scores: [{ metric_name: 'gated_metric_count', value: 3, gate_pass: null, threshold: null }],
      })],
      total: 1,
    });
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    expect(within(tr).getByText(/실패 지표가 기록되지 않음/)).toBeInTheDocument();
  });

  it('PASS 는 검사 규모를 함께 말한다', async () => {
    mockApi.mockResolvedValue({
      runs: [run({
        scores: [
          { metric_name: 'called_pct', value: 99, gate_pass: true, threshold: 95 },
          { metric_name: 'asil_pct', value: 82, gate_pass: true, threshold: 50 },
          { metric_name: 'gated_metric_count', value: 2, gate_pass: null, threshold: null },
        ],
      })],
      total: 1,
    });
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    expect(within(tr).getByText(/게이트 2개 항목 전부 통과/)).toBeInTheDocument();
  });
});

describe('DocGenStatusBoard — 근거(evidence)', () => {
  it('사이드카가 없으면 "근거 없음"과 사유를 보이고 양호로 그리지 않는다', async () => {
    mockApi.mockImplementation((path) => {
      if (String(path).includes('/evidence')) {
        return Promise.resolve({
          run_id: 1, output_path_present: false, sidecars_expected: true,
          gate_report: { present: false, reason: '사이드카 없음 (.quality_gate.md)' },
          confidence: { present: false, reason: '사이드카 없음 (.field_confidence.md)' },
          docx_validate: { present: false, reason: '사이드카 없음 (.validation.md)' },
        });
      }
      return Promise.resolve({ runs: [run()], total: 1 });
    });
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    await user.click(within(tr).getByRole('button', { name: '근거' }));

    await waitFor(() => expect(screen.getByText(/게이트 근거 파일 없음/)).toBeInTheDocument());
    expect(screen.getByText(/사이드카 없음 \(\.quality_gate\.md\)/)).toBeInTheDocument();
    expect(screen.getByText(/출처 신뢰도 근거 없음/)).toBeInTheDocument();
  });

  it('사이드카가 있으면 TBD 잔여·설명 출처·신뢰도를 보여준다', async () => {
    mockApi.mockImplementation((path) => {
      if (String(path).includes('/evidence')) {
        return Promise.resolve({
          run_id: 1, output_path_present: true, sidecars_expected: true,
          gate_report: {
            present: true, gates_passed: 10, gates_total: 13, total_functions: 169,
            tbd_residual: { asil_tbd: { count: 29, total: 169 }, related_tbd: { count: 12, total: 169 } },
            description_quality: { high: { count: 120 }, medium: { count: 40 }, low: { count: 9 } },
          },
          confidence: { present: true, grade: 'B', overall_score: 0.712 },
          docx_validate: { present: true, ok: false, issues: ['x'], missing_from_docx: 9 },
        });
      }
      return Promise.resolve({ runs: [run()], total: 1 });
    });
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    await user.click(within(tr).getByRole('button', { name: '근거' }));

    await waitFor(() => expect(screen.getByText(/게이트 항목 10 \/ 13 통과/)).toBeInTheDocument());
    expect(screen.getByText(/ASIL 미상\(TBD\)/)).toBeInTheDocument();
    expect(screen.getByText(/출처 신뢰도/)).toBeInTheDocument();
    expect(screen.getByText(/문서에 빠진 함수 9개/)).toBeInTheDocument();
  });

  it('근거 조회가 실패해도 조용히 비우지 않고 알린다', async () => {
    mockApi.mockImplementation((path) => {
      if (String(path).includes('/evidence')) return Promise.reject(new Error('503 unavailable'));
      return Promise.resolve({ runs: [run()], total: 1 });
    });
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    await user.click(within(tr).getByRole('button', { name: '근거' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/503 unavailable/));
  });
});

describe('DocGenStatusBoard — 프로젝트 스코프와 진행', () => {
  it('scm_id 를 쿼리에 실어 이 프로젝트 이력만 본다', async () => {
    mountBoard();
    await waitFor(() => expect(mockApi).toHaveBeenCalled());
    const url = String(mockApi.mock.calls[0][0]);
    expect(url).toContain('scm_id=kjpds02_pv');
    expect(url).toContain('include_scores=true');
  });

  it('SCM 매칭이 없으면 전체 이력임을 경고한다 (남의 프로젝트가 섞일 수 있음)', async () => {
    render(<DocGenStatusBoard job={JOB} analysisResult={{}} genState={null} />);
    await waitFor(() => expect(screen.getByText(/전체 이력/)).toBeInTheDocument());
    expect(String(mockApi.mock.calls[0][0])).not.toContain('scm_id=');
  });

  it('생성 중이면 진행률을 보이고 점수를 지어내지 않는다', async () => {
    mockApi.mockResolvedValue({ runs: [run()], total: 1 });
    render(
      <DocGenStatusBoard job={JOB} analysisResult={ANALYSIS}
        genState={{ docType: 'uds', stage: 'DOCX 작성', progress: 45, result: null }} />
    );
    const tr = await waitFor(() => rowOf('📘 UDS'));
    expect(within(tr).getByText('생성 중')).toBeInTheDocument();
    expect(within(tr).getByText('45%')).toBeInTheDocument();
    expect(within(tr).getByText(/DOCX 작성/)).toBeInTheDocument();
    // 진행 중엔 직전 run 의 점수를 그대로 보이면 "지금 그 점수" 로 오독된다
    expect(within(tr).queryByText('92.4')).toBeNull();
  });

  it('생성 버튼이 부모의 생성 함수를 호출한다', async () => {
    const onGenerate = vi.fn();
    const user = userEvent.setup();
    mountBoard({ onGenerate });
    const tr = await waitFor(() => rowOf('📗 STS'));
    await user.click(within(tr).getByRole('button', { name: '생성' }));
    expect(onGenerate).toHaveBeenCalledWith('sts');
  });

  it('생성이 끝나면 이력을 다시 읽는다', async () => {
    const { rerender } = render(
      <DocGenStatusBoard job={JOB} analysisResult={ANALYSIS}
        genState={{ docType: 'uds', stage: '진행', progress: 50, result: null }} />
    );
    await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(1));
    rerender(
      <DocGenStatusBoard job={JOB} analysisResult={ANALYSIS}
        genState={{ docType: null, stage: '완료', progress: 100, result: { success: true } }} />
    );
    await waitFor(() => expect(mockApi.mock.calls.length).toBeGreaterThan(1));
  });

  it('목록 조회가 실패하면 알린다 (빈 표를 "이력 없음" 으로 위장하지 않는다)', async () => {
    mockApi.mockRejectedValue(new Error('500 서버 오류'));
    mountBoard();
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/500 서버 오류/));
  });

  it('모듈 부재(200+error)도 오류로 다룬다', async () => {
    mockApi.mockResolvedValue({ runs: [], total: 0, error: 'quality module not available' });
    mountBoard();
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(/quality module not available/));
  });
});
