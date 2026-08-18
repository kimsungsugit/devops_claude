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
import fs from 'node:fs';
import path from 'node:path';

const mockApi = vi.fn();
const mockPost = vi.fn();
const mockToast = vi.fn();

vi.mock('../api.js', () => ({
  api: (...a) => mockApi(...a),
  post: (...a) => mockPost(...a),
  buildUrl: (p) => p,
  // 실제 헤더 조립은 api.js 의 책임 — 여기서는 **붙었는지**만 본다(X9).
  authHeaders: () => ({ Authorization: 'Bearer T', 'X-User': 'u' }),
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

/**
 * 시험 결과 문서(SUTR/SITR/통합 Summary) 원클릭 생성.
 *
 * 여기서 지켜야 할 선은 하나다 — **디폴트로 채우되 지어내지는 않는다.** 릴리스 SW
 * 버전을 임의로 찍으면 ISO 26262 납품 문서 표지에 틀린 릴리스가 박히고, 그건 화면이
 * 조용히 만든 거짓 증거다.
 */
describe('DocGenStatusBoard — 시험 결과 문서 원클릭 생성', () => {
  const okXlsm = () => ({
    ok: true, status: 200,
    headers: { get: (k) => (k === 'Content-Disposition' ? 'attachment; filename="SUTR.xlsm"' : null) },
    blob: async () => new Blob(['x'.repeat(2048)]),
  });

  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn().mockResolvedValue(okXlsm());
    // jsdom 에는 없다 — 다운로드 경로가 여기서 죽으면 테스트가 원인을 가린다.
    global.URL.createObjectURL = vi.fn(() => 'blob:x');
    global.URL.revokeObjectURL = vi.fn();
  });

  it('세 행이 모두 뜨고 각자 생성/세부 버튼을 갖는다', async () => {
    mountBoard();
    for (const label of ['🧪 SUTR', '🔗 SITR', '📊 통합 Summary']) {
      const tr = await waitFor(() => rowOf(label));
      expect(within(tr).getByRole('button', { name: '생성' })).toBeInTheDocument();
      expect(within(tr).getByRole('button', { name: '세부 →' })).toBeInTheDocument();
    }
  });

  it('통합 Summary 는 프로젝트가 아니라 **양식 ID** 로 표시한다', async () => {
    // `ES95411` 은 마스터 양식 문서 ID 다(SWREPORT_DEFAULT_FORM 주석). '대상' 으로
    // 쓰면 사용자가 "이 프로젝트가 왜 여기 있지" 라고 읽는다 — 실제 보고된 혼란.
    mountBoard();
    const tr = await waitFor(() => rowOf('📊 통합 Summary'));
    expect(within(tr).getByText(/양식/)).toBeInTheDocument();
    expect(within(tr).queryByText(/대상/)).toBeNull();
  });

  it('통합 Summary 에는 범위 불일치 경고를 내지 않는다 — 비교 대상이 아니다', async () => {
    mountBoard();
    const tr = await waitFor(() => rowOf('📊 통합 Summary'));
    expect(within(tr).queryByText(/화면 범위/)).toBeNull();
  });

  it('릴리스 버전이 없으면 생성이 막히고 "입력 필요" 라고 말한다', async () => {
    mountBoard();
    const tr = await waitFor(() => rowOf('🧪 SUTR'));
    expect(within(tr).getByRole('button', { name: '생성' })).toBeDisabled();
    expect(within(tr).getByText('입력 필요')).toBeInTheDocument();
    // 음성 대조군 — 임의 버전을 채워 넣지 않는다.
    expect(within(tr).getByLabelText(/릴리스 SW 버전/)).toHaveValue('');
  });

  it('직전 빌드 저장값을 디폴트로 쓴다', async () => {
    localStorage.setItem('devops_v2_swut_form', JSON.stringify({ release_sw_version: '2.02' }));
    mountBoard();
    const tr = await waitFor(() => rowOf('🧪 SUTR'));
    expect(within(tr).getByLabelText(/릴리스 SW 버전/)).toHaveValue('2.02');
    expect(within(tr).getByText('직전 빌드값')).toBeInTheDocument();
  });

  it('저장값이 없으면 직전 실행 기록의 버전으로 폴백한다', async () => {
    mockApi.mockResolvedValue({
      runs: [run({ doc_type: 'swut', meta: { release_sw_version: '1.07' } })], total: 1,
    });
    mountBoard();
    const tr = await waitFor(() => rowOf('🔗 SITR'));
    expect(within(tr).getByLabelText(/릴리스 SW 버전/)).toHaveValue('1.07');
    expect(within(tr).getByText('직전 실행 기록')).toBeInTheDocument();
  });

  it('생성하면 UI 전용 키 없이 POST 하고 인증 헤더를 붙인다', async () => {
    localStorage.setItem('devops_v2_swut_form', JSON.stringify({
      release_sw_version: '2.02', log_folders_text: 'A\nB',
    }));
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('🧪 SUTR'));
    await user.click(within(tr).getByRole('button', { name: '생성' }));

    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    const [url, opt] = global.fetch.mock.calls[0];
    expect(url).toBe('/api/swut/sutr/build');
    expect(opt.headers.Authorization).toBe('Bearer T');       // X9 — 없으면 401 을 삼킨다
    const body = JSON.parse(opt.body);
    expect(body.release_sw_version).toBe('2.02');
    expect(body.log_folders).toEqual(['A', 'B']);
    expect('log_folders_text' in body).toBe(false);           // backend extra='forbid'
  });

  it('성공하면 이력을 다시 읽는다 (방금 만든 실행이 표에 반영돼야 한다)', async () => {
    localStorage.setItem('devops_v2_swreport_form', JSON.stringify({ release_sw_version: '1.00' }));
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('📊 통합 Summary'));
    await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(1));
    await user.click(within(tr).getByRole('button', { name: '생성' }));
    await waitFor(() => expect(mockApi.mock.calls.length).toBeGreaterThan(1));
  });

  it('403 을 서버 장애가 아니라 권한 상태로 말한다', async () => {
    localStorage.setItem('devops_v2_swit_form', JSON.stringify({ release_sw_version: '1.00' }));
    global.fetch = vi.fn().mockResolvedValue({
      ok: false, status: 403, json: async () => ({ detail: 'admin only' }),
      headers: { get: () => null },
    });
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('🔗 SITR'));
    await user.click(within(tr).getByRole('button', { name: '생성' }));
    await waitFor(() => expect(within(tr).getByRole('alert')).toHaveTextContent(/관리자 전용/));
    expect(within(tr).queryByText(/HTTP 403/)).toBeNull();
  });

  it('422 필드 오류를 그대로 보여준다 (사유 없는 "실패" 로 뭉개지 않는다)', async () => {
    localStorage.setItem('devops_v2_swut_form', JSON.stringify({ release_sw_version: '1.00' }));
    global.fetch = vi.fn().mockResolvedValue({
      ok: false, status: 422, headers: { get: () => null },
      json: async () => ({ detail: [{ loc: ['body', 'test_date'], msg: 'string does not match' }] }),
    });
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('🧪 SUTR'));
    await user.click(within(tr).getByRole('button', { name: '생성' }));
    await waitFor(() => expect(within(tr).getByRole('alert')).toHaveTextContent(/test_date/));
  });

  it('양식 키가 지정되지 않으면 조용히 만들지 않고 경고한다', async () => {
    // SCM 에 `builder_project_id` 가 없으면 빌더 폼 기본값(`HDPDM01`)이 그대로 쓰인다
    // — 그러면 KJPDS02_PV 를 보면서 **남의 프로젝트 문서**가 나온다.
    mountBoard();
    const tr = await waitFor(() => rowOf('🧪 SUTR'));
    expect(within(tr).getByText(/양식 키가 지정되지 않아/)).toBeInTheDocument();
    // 어느 값으로 만들어지는지 이름을 밝혀야 한다 — "기본값" 이라고만 하면 못 고친다.
    // (표시 라벨과 경고문 두 곳에 나오므로 `getAllByText`.)
    expect(within(tr).getAllByText('HDPDM01').length).toBeGreaterThan(0);
  });

  it('SCM 이 양식 키를 지정하면 경고하지 않고 그 값을 쓴다', async () => {
    // ⚠ SCM id(`kjpds02_pv`)와 양식 키(`KJPDS02`)는 **다른 어휘**다 — 문자열이 같아야
    //   정상인 게 아니다. 옛 판정은 둘을 비교해 정상 구성에도 경고를 띄웠다.
    localStorage.setItem('devops_v2_swut_form', JSON.stringify({ project_id: 'HDPDM01' }));
    render(<DocGenStatusBoard job={JOB} genState={null}
      analysisResult={{ matchedScm: {
        id: 'kjpds02_pv', name: 'KJPDS02_PV', builder_project_id: 'KJPDS02',
      } }} />);
    const tr = await waitFor(() => rowOf('🧪 SUTR'));
    expect(within(tr).queryByText(/양식 키가 지정되지 않아/)).toBeNull();
    // 표시도 SCM 값을 따라야 한다(표시와 payload 가 갈리면 안 된다).
    expect(within(tr).getByText('KJPDS02')).toBeInTheDocument();
  });

  it('통합 Summary 는 빌더 산출물 표에 중복되지 않는다', async () => {
    mockApi.mockResolvedValue({
      runs: [run({ doc_type: 'swreport', id: 9 }), run({ doc_type: 'swut', id: 8 })], total: 2,
    });
    mountBoard();
    await waitFor(() => rowOf('📊 통합 Summary'));
    // 보조 표에는 커버리지 계열만 남는다.
    expect(screen.getByText('SwUT 커버리지')).toBeInTheDocument();
    expect(screen.queryByText('통합 결과')).toBeNull();
  });
});

// ── 재료 측정 요청에 SwRS 를 싣는가 (2026-08-14) ─────────────────────────────
//
// STS 축(요구-함수 매핑)은 **요구 목록**이 있어야 잰다. 안 보내면 게이트가
// "SwRS 경로가 지정되지 않았습니다" 로 미측정에 머문다 — 조용히 틀리지는 않지만,
// 그 축은 영원히 안 켜진다.
//
// ⚠ 이건 **구조 검사**다. 준비 패널을 열고 액션까지 눌러 재현하는 행동 검사가 더
//   낫지만, 미측정 사유가 화면에 그대로 나오므로(=침묵 아님) 여기서는 요청 본문이
//   두 문서를 다 싣는지만 못 박는다.
describe('measure-source 요청 본문 (구조)', () => {
  const SRC = fs.readFileSync(
    path.join(process.cwd(), 'src/components/sections/DocGenStatusBoard.jsx'), 'utf8');

  it('SwDS 와 SwRS 를 함께 보낸다', () => {
    const call = SRC.slice(SRC.indexOf("'/api/docgen/measure-source'"));
    const body = call.slice(0, call.indexOf('});') + 3);
    expect(body).toMatch(/sds_path:/);
    expect(body).toMatch(/srs_path:/);
    // 경로 출처도 같아야 한다 — 한쪽만 설정(doc_paths)을 보면 두 축이 다른 프로젝트를 잰다.
    expect(body).toMatch(/paths\.sds/);
    expect(body).toMatch(/paths\.srs/);
  });

  // 설계-ID 브리지의 좌측 끝. 안 보내면 브리지가 꺼진 채로 재고, 게이트가 실제
  // 산출물보다 나쁜 숫자를 보고한다(실측 KJPDS02_PV: 요구 48/68 vs 64/68).
  it('SwUDS 도 함께 보낸다 (설계-ID 브리지)', () => {
    const call = SRC.slice(SRC.indexOf("'/api/docgen/measure-source'"));
    const body = call.slice(0, call.indexOf('});') + 3);
    expect(body).toMatch(/uds_path:/);
    expect(body).toMatch(/paths\.uds/);
  });
});
