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
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DOCGEN_CAPS_KEY, saveDocGenCap } from '../sharedInputs.js';

const mockApi = vi.fn();
const mockPost = vi.fn();
const mockToast = vi.fn();

vi.mock('../api.js', () => ({
  api: (...a) => mockApi(...a),
  post: (...a) => mockPost(...a),
  buildUrl: (p) => p,
  // 실제 헤더 조립은 api.js 의 책임 — 여기서는 **붙었는지**만 본다(X9).
  authHeaders: () => ({ Authorization: 'Bearer T', 'X-User': 'u' }),
  // ⚠ 실제 폴백 사슬을 흉내낸다. 빈 문자열로 뭉개면 "게이트가 생성과 같은 캐시 루트를
  //   본다" 는 단언이 vacuous 해진다(둘 다 '' 라 항상 같다).
  resolveCacheRoot: (ar, job, cfg) =>
    ar?.cacheRoot || (job?.url ? '.devops_pro_cache/u' : '') || cfg?.cacheRoot || '',
}));
vi.mock('../App.jsx', () => ({
  useToast: () => mockToast,
  useJenkinsCfg: () => ({ cfg: { cacheRoot: '.cache', buildSelector: 'lastSuccessfulBuild' }, update: () => {} }),
}));

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
  // ⚠ 이 파일의 13곳이 localStorage 에 쓴다(캡 값·doc_paths). 예전엔 clear() 가
  //   **중첩 describe 안에만** 있어서 그 아래 테스트들끼리 값이 샜다 — 앞 테스트가
  //   `전부 145` 를 눌러 저장한 캡이 뒤 테스트의 초기 판정을 바꾼다. 그래서 실패가
  //   **실행마다 다른 테스트로 옮겨 다녔다**(2026-09-02: 같은 파일 안에서 응답 역전 ↔
  //   gate_pass=null 사이를 오감). 오염은 전역에서 끊는다.
  localStorage.clear();
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

  // (R31 Q-8) 라이터가 쓰던 경고 절과 '대조 불가' 가 리더를 거쳐 화면까지 온다.
  it('구조 검증: 대조 불가는 "누락 없음" 이 아니라 미검증으로, 경고 절은 목록으로 보인다', async () => {
    mockApi.mockImplementation((path) => {
      if (String(path).includes('/evidence')) {
        return Promise.resolve({
          run_id: 1, output_path_present: true, sidecars_expected: true,
          gate_report: { present: false, reason: '없음' },
          confidence: { present: false, reason: '없음' },
          docx_validate: {
            present: true, ok: true, issues: [], missing_from_docx: null, uncomparable: true,
            warnings: ['payload 사이드카 없음(spec.payload.json) — 입력 대비 대조 불가(미검증)'],
          },
        });
      }
      return Promise.resolve({ runs: [run()], total: 1 });
    });
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    await user.click(within(tr).getByRole('button', { name: '근거' }));

    await waitFor(() => expect(screen.getByText('입력 대비 대조 불가', { selector: 'strong' })).toBeInTheDocument());
    expect(screen.queryByText(/문서에 빠진 함수/)).toBeNull();
    const list = screen.getByRole('list', { name: '구조 검증 경고' });
    expect(within(list).getAllByRole('listitem')).toHaveLength(1);
    expect(within(list).getByText(/payload 사이드카 없음/)).toBeInTheDocument();
  });

  it('구조 검증: 대조했고 누락 0 이면 0개라고 말한다 (예전엔 줄이 없어 영원히 안 보였다)', async () => {
    mockApi.mockImplementation((path) => {
      if (String(path).includes('/evidence')) {
        return Promise.resolve({
          run_id: 1, output_path_present: true, sidecars_expected: true,
          gate_report: { present: false, reason: '없음' },
          confidence: { present: false, reason: '없음' },
          docx_validate: { present: true, ok: true, issues: [], missing_from_docx: 0,
            headings_without_payload: 0, uncomparable: false, warnings: [] },
        });
      }
      return Promise.resolve({ runs: [run()], total: 1 });
    });
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    await user.click(within(tr).getByRole('button', { name: '근거' }));

    await waitFor(() => expect(screen.getByText(/문서에 빠진 함수 0개/)).toBeInTheDocument());
    expect(screen.getByText(/빈 명세 heading 0개/)).toBeInTheDocument();
    expect(screen.queryByText(/입력 대비 대조 불가/)).toBeNull();
    expect(screen.queryByRole('list', { name: '구조 검증 경고' })).toBeNull();
  });

  // ⚠ 라운드 15 — 분모 0 인 축은 채점하지 않는다. 이 수가 화면에 없으면 "5/11" 이
  //    "6건 미달" 로만 읽혀, 잴 수 없던 축까지 고칠 거리로 보인다.
  it('미측정 게이트가 있으면 개수와 "0% 아님" 을 함께 보인다', async () => {
    mockApi.mockImplementation((path) => {
      if (String(path).includes('/evidence')) {
        return Promise.resolve({
          run_id: 1, output_path_present: true, sidecars_expected: true,
          gate_report: {
            present: true, gates_passed: 5, gates_total: 11, total_functions: 429,
            unmeasured_count: 2,
            unmeasured_gates: ['**input_fill_rate**: 분모가 0'],
          },
          confidence: { present: false, reason: '없음' },
          docx_validate: { present: false, reason: '없음' },
        });
      }
      return Promise.resolve({ runs: [run()], total: 1 });
    });
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    await user.click(within(tr).getByRole('button', { name: '근거' }));

    await waitFor(() => expect(screen.getByText(/미측정 2개/)).toBeInTheDocument());
    expect(screen.getByText(/0% 아님/)).toBeInTheDocument();
  });

  // ⚠ 라운드 29 (Q-4) — 해당 없음은 미측정과 **다른 버킷**이다. 못 잰 게 아니라 잴 대상이
  //    없어 판정 밖이고 Gate pass 를 붙들지 않는다. 같은 문구로 접으면 "못 쟀다" 로 읽힌다.
  it('해당 없음 게이트가 있으면 개수와 "판정 밖(미측정 아님)" 을 함께 보인다', async () => {
    mockApi.mockImplementation((path) => {
      if (String(path).includes('/evidence')) {
        return Promise.resolve({
          run_id: 1, output_path_present: true, sidecars_expected: true,
          gate_report: {
            present: true, gates_passed: 8, gates_total: 8, total_functions: 12,
            unmeasured_count: 0, unmeasured_gates: [],
            not_applicable_count: 2, not_applicable_gates: ['**input_fill_rate**: 대상 0', '**output_fill_rate**: 대상 0'],
            ungated_count: 1, ungated_gates: ['**traceability_rate**: 임계 없음'],
            prototype_unreadable: { count: 408, total: 426 },
            tbd_residual: {
              asil_tbd: { count: 0, total: 426 }, asil_unfilled: { count: 17, total: 426 },
              related_tbd: { count: 372, total: 426 }, related_unfilled: { count: 0, total: 426 },
            },
          },
          confidence: { present: false, reason: '없음' },
          docx_validate: { present: false, reason: '없음' },
        });
      }
      return Promise.resolve({ runs: [run()], total: 1 });
    });
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    await user.click(within(tr).getByRole('button', { name: '근거' }));

    await waitFor(() => expect(screen.getByText(/해당 없음 2개/)).toBeInTheDocument());
    expect(screen.getByText(/판정 밖\(미측정 아님\)/)).toBeInTheDocument();
    expect(screen.queryByText(/미측정 \d+개/)).not.toBeInTheDocument();
    // 리뷰 W4 — 임계 없는 축은 사유 없는 FAIL 이 되지 않게 이름을 단다
    expect(screen.getByText(/임계 없음 1개/)).toBeInTheDocument();
    // 리뷰 W2 — 부분 측정: "8 / 8" 이 426 중 8개만 본 값일 수 있다
    expect(screen.getByText(/Prototype 을 읽지 못한 함수/)).toHaveTextContent(/408/);
    expect(screen.getByText(/나머지 함수로만 잰 값/)).toBeInTheDocument();
    // 리뷰 I3 — TBD 가 0 이어도 미기재는 보인다(그게 asil_non_tbd_rate FAIL 의 사유다)
    expect(screen.getByText(/ASIL 미기재/)).toHaveTextContent(/17/);
    expect(screen.queryByText(/Related ID 미기재/)).not.toBeInTheDocument();   // 0 이면 안 만든다
  });

  // ⚠ 라운드 30 (Q-2) — 무엇을 채점했는가. payload 없음 = 문서 자기 대조(근거 있음 0 이 정상),
  //    payload 있음 = 문서 ∩ payload 만 채점. 이 두 사실이 없으면 "429항목 문서 통과" 로 읽힌다.
  it('payload 가 없으면 "문서 자기 대조" 를, 있으면 문서·payload 차집합을 보인다', async () => {
    const evid = (gate) => Promise.resolve({
      run_id: 1, output_path_present: true, sidecars_expected: true,
      gate_report: { present: true, gates_passed: 8, gates_total: 10, total_functions: 5, ...gate },
      confidence: { present: false, reason: '없음' }, docx_validate: { present: false, reason: '없음' },
    });
    mockApi.mockImplementation((path) => String(path).includes('/evidence')
      ? evid({ payload_present: false, document_entries: 429 })
      : Promise.resolve({ runs: [run()], total: 1 }));
    const user = userEvent.setup();
    const { unmount } = mountBoard();
    let tr = await waitFor(() => rowOf('📘 UDS'));
    await user.click(within(tr).getByRole('button', { name: '근거' }));
    await waitFor(() => expect(screen.getByText(/문서 자기 대조/)).toBeInTheDocument());
    expect(screen.getByText(/payload 사이드카 없음/)).toBeInTheDocument();
    expect(screen.queryByText(/읽기 실패/)).not.toBeInTheDocument();
    expect(screen.queryByText(/payload 에 없음/)).not.toBeInTheDocument();
    unmount();

    // "없음" 과 "있는데 못 읽음" 은 다르다(리뷰 W1) — 후자는 생성 직후 재채점(torn read) 신호
    mockApi.mockImplementation((path) => String(path).includes('/evidence')
      ? evid({ payload_present: false, payload_read_error: 'u.payload.json: JSONDecodeError: x', document_entries: 429 })
      : Promise.resolve({ runs: [run()], total: 1 }));
    const second = mountBoard();
    tr = await waitFor(() => rowOf('📘 UDS'));
    await user.click(within(tr).getByRole('button', { name: '근거' }));
    await waitFor(() => expect(screen.getByText(/읽기 실패/).closest('li')).toHaveTextContent(/JSONDecodeError/));
    expect(screen.queryByText(/payload 사이드카 없음/)).not.toBeInTheDocument();
    second.unmount();

    mockApi.mockImplementation((path) => String(path).includes('/evidence')
      ? evid({ payload_present: true, payload_file: 'u.payload.json', document_entries: 429,
               entries_not_in_payload: { count: 424, total: 429 }, scored_entries: { count: 5, total: 429 },
               payload_not_in_document: { count: 5, total: 5 } })
      : Promise.resolve({ runs: [run()], total: 1 }));
    mountBoard();
    tr = await waitFor(() => rowOf('📘 UDS'));
    await user.click(within(tr).getByRole('button', { name: '근거' }));
    await waitFor(() => expect(screen.getByText(/payload 에 없음/)).toHaveTextContent(/424/));
    // 통과가 무엇에 대한 통과인가 — 채점된 5개 기준, 커버리지 1.2%
    expect(screen.getByText(/payload 에 없음/)).toHaveTextContent(/채점된 5개 기준\(문서 커버리지 1\.2%\)/);
    expect(screen.getByText(/문서에 없음/)).toHaveTextContent(/5 \/ 5/);
    expect(screen.queryByText(/문서 자기 대조/)).not.toBeInTheDocument();
  });

  it('구판 리포트에 임계 없음·부분 측정·미기재 키가 없으면 그 문구를 만들지 않는다', async () => {
    mockApi.mockImplementation((path) => {
      if (String(path).includes('/evidence')) {
        return Promise.resolve({
          run_id: 1, output_path_present: true, sidecars_expected: true,
          gate_report: {
            present: true, gates_passed: 5, gates_total: 13, total_functions: 429,
            tbd_residual: { asil_tbd: { count: 3, total: 429 } },
          },
          confidence: { present: false, reason: '없음' },
          docx_validate: { present: false, reason: '없음' },
        });
      }
      return Promise.resolve({ runs: [run()], total: 1 });
    });
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    await user.click(within(tr).getByRole('button', { name: '근거' }));

    await waitFor(() => expect(screen.getByText(/게이트 항목 5 \/ 13 통과/)).toBeInTheDocument());
    expect(screen.queryByText(/임계 없음/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Prototype 을 읽지 못한 함수/)).not.toBeInTheDocument();
    expect(screen.queryByText(/ASIL 미기재/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Related ID 미기재/)).not.toBeInTheDocument();
  });

  it('구판 리포트(미측정 항목 없음)엔 미측정 문구를 만들지 않는다 (음성 대조군)', async () => {
    mockApi.mockImplementation((path) => {
      if (String(path).includes('/evidence')) {
        return Promise.resolve({
          run_id: 1, output_path_present: true, sidecars_expected: true,
          gate_report: {
            present: true, gates_passed: 5, gates_total: 13, total_functions: 429,
            unmeasured_count: null, unmeasured_gates: [],
          },
          confidence: { present: false, reason: '없음' },
          docx_validate: { present: false, reason: '없음' },
        });
      }
      return Promise.resolve({ runs: [run()], total: 1 });
    });
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    await user.click(within(tr).getByRole('button', { name: '근거' }));

    await waitFor(() => expect(screen.getByText(/게이트 항목 5 \/ 13 통과/)).toBeInTheDocument());
    expect(screen.queryByText(/미측정/)).not.toBeInTheDocument();
  });

  // ⚠ 아래 두 건은 라운드 14 에서 생겼다. `drop` 은 대응 소스가 없는 절을 문서에서
  //    빼므로 "빈 명세 heading" 수가 **줄어든다** — 그 사실이 화면에 없으면 얇아진
  //    문서가 완결된 것처럼 보인다(실측: 빈 heading 4건 → 1건, OK 는 양쪽 다 True).
  it('제거된 절이 있으면 개수와 "남은 것만 센다" 를 함께 보인다', async () => {
    mockApi.mockImplementation((path) => {
      if (String(path).includes('/evidence')) {
        return Promise.resolve({
          run_id: 1, output_path_present: true, sidecars_expected: true,
          gate_report: { present: false, reason: '없음' },
          confidence: { present: false, reason: '없음' },
          docx_validate: {
            present: true, ok: true, issues: [],
            headings_without_payload: 1, dropped_headings: 402,
            unmatched_headings_mode: 'drop',
          },
        });
      }
      return Promise.resolve({ runs: [run()], total: 1 });
    });
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    await user.click(within(tr).getByRole('button', { name: '근거' }));

    await waitFor(() => expect(screen.getByText(/제거된 heading 402개/)).toBeInTheDocument());
    expect(screen.getByText(/빈 명세 heading 1개/)).toBeInTheDocument();
    expect(screen.getByText(/남은 것만 센다/)).toBeInTheDocument();
  });

  it('제거가 0건이면 제거 문구를 만들지 않는다 (음성 대조군)', async () => {
    mockApi.mockImplementation((path) => {
      if (String(path).includes('/evidence')) {
        return Promise.resolve({
          run_id: 1, output_path_present: true, sidecars_expected: true,
          gate_report: { present: false, reason: '없음' },
          confidence: { present: false, reason: '없음' },
          docx_validate: {
            present: true, ok: true, issues: [],
            headings_without_payload: 4, dropped_headings: 0,
            unmatched_headings_mode: 'keep',
          },
        });
      }
      return Promise.resolve({ runs: [run()], total: 1 });
    });
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('📘 UDS'));
    await user.click(within(tr).getByRole('button', { name: '근거' }));

    await waitFor(() => expect(screen.getByText(/빈 명세 heading 4개/)).toBeInTheDocument());
    expect(screen.queryByText(/제거된 heading/)).not.toBeInTheDocument();
    expect(screen.queryByText(/남은 것만 센다/)).not.toBeInTheDocument();
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

  it('한 산출물이 두 표에 동시에 나오지 않는다', async () => {
    // 같은 run 이 두 표에 뜨면 어느 쪽이 최신인지 화면이 **두 번 답한다**. 커버리지 2종은
    // 레벨 표에서 생성까지 되므로 보조 표(`빌더 산출물`)에서 빠져야 한다.
    mockApi.mockResolvedValue({
      runs: [
        run({ doc_type: 'swreport', id: 9 }), run({ doc_type: 'swut', id: 8 }),
        run({ doc_type: 'swit', id: 7 }), run({ doc_type: 'swsa', id: 6 }),
      ],
      total: 4,
    });
    mountBoard();
    await waitFor(() => rowOf('📊 통합 Summary'));
    // 보조 표의 옛 라벨은 사라졌다 — 이력이 있어도(위 runs) 다시 나타나면 안 된다.
    expect(screen.queryByText('SwUT 커버리지')).toBeNull();
    expect(screen.queryByText('SwIT 커버리지')).toBeNull();
    // 정적분석만 남는다(생성 경로가 보드에 없어 여전히 탭 이동 전용).
    expect(screen.getByText('SwSA 정적분석')).toBeInTheDocument();
    // 각 산출물 행은 정확히 한 번.
    for (const label of ['📊 SwUTCV', '📊 SwITCV', '📊 통합 Summary']) {
      expect(screen.getAllByText(new RegExp(`^${label}$`))).toHaveLength(1);
    }
  });

  it('SwUT·SwIT 표가 각각 3행을 낸다 (커버리지·결과·종합결과)', async () => {
    mountBoard();
    await waitFor(() => rowOf('🧪 SUTR'));
    for (const label of ['📊 SwUTCV', '🧪 SUTR', '📚 SwUTCR',
                         '📊 SwITCV', '🔗 SITR', '📚 SwITCR']) {
      expect(rowOf(label)).toBeTruthy();
    }
  });

  it('6종이 각자의 엔드포인트로 나간다 — 한 곳으로 몰리지 않는다', async () => {
    // ⚠ 이 표가 갈리면 SwUTCR 을 눌렀는데 SUTR 이 만들어진다. 라벨은 맞고 산출물만
    //   틀리므로 화면으로는 알 수 없다.
    localStorage.setItem('devops_v2_swut_form', JSON.stringify({
      project_id: 'HDPDM01', release_sw_version: '1.02', test_date: '2026-08-24',
    }));
    localStorage.setItem('devops_v2_swit_form', JSON.stringify({
      project_id: 'HDPDM01', release_sw_version: '1.02', test_date: '2026-08-24',
    }));
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true, status: 200,
      headers: { get: () => null },
      blob: async () => new Blob(['x']),
    });
    vi.stubGlobal('fetch', fetchMock);
    const user = userEvent.setup();
    mountBoard();
    const expected = [
      ['📊 SwUTCV', '/api/swut/coverage/build'],
      ['🧪 SUTR', '/api/swut/sutr/build'],
      ['📚 SwUTCR', '/api/swut/swutcr/build'],
      ['📊 SwITCV', '/api/swit/coverage/build'],
      ['🔗 SITR', '/api/swit/sitr/build'],
      ['📚 SwITCR', '/api/swit/switcr/build'],
    ];
    await waitFor(() => rowOf('📊 SwUTCV'));
    for (const [label, endpoint] of expected) {
      fetchMock.mockClear();
      await user.click(within(rowOf(label)).getByRole('button', { name: '생성' }));
      await waitFor(() => expect(fetchMock).toHaveBeenCalled());
      expect(fetchMock.mock.calls[0][0]).toBe(endpoint);
    }
    vi.unstubAllGlobals();
  });

  it('준비 점검이 빌더 폼을 함께 싣는다 (안 실으면 항상 "필수값 없음")', async () => {
    // 백엔드 `PreflightRequest.form` 은 프론트 판정을 흡수하려고 만든 필드다 — 비면
    // 판정이 두 벌이 되는 게 아니라 **한 벌이 거짓말**을 한다(양식 조회도 project_id 로 시작).
    localStorage.setItem('devops_v2_swut_form', JSON.stringify({
      project_id: 'HDPDM01', release_sw_version: '1.02', test_date: '2026-08-24',
    }));
    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('📚 SwUTCR'));
    await user.click(within(tr).getByRole('button', { name: '준비' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/api/docgen/preflight', expect.objectContaining({ doc_type: 'swutcr' }),
    ));
    const body = mockPost.mock.calls.find(c => c[0] === '/api/docgen/preflight')[1];
    expect(body.form).toEqual(expect.objectContaining({
      project_id: 'HDPDM01', release_sw_version: '1.02', test_date: '2026-08-24',
    }));
  });
});

// ── 재료 측정 요청이 서버 해석에 필요한 것을 싣는가 (2026-08-14 → 2026-08-31) ──
//
// STS 축(요구-함수 매핑)은 SwRS 요구 목록이, 설계-ID 브리지는 SwUDS 가 있어야 켜진다.
// 안 실으면 그 축은 영원히 안 켜진다.
//
// ⚠ 2026-08-31: 예전엔 **화면이 경로를 직접 골랐고**(`paths.sds || linked_docs.sds`)
//   이 자리에 그 소스를 grep 하는 구조 검사가 있었다. 그건 백엔드 우선순위 규칙의
//   복제라, 조금만 갈리면 preflight 의 캐시 조회 키와 어긋나 **측정을 해도 게이트가
//   계속 "아직 재지 않았습니다"** 로 남는다. 이제 해석은 서버(`_resolve_inputs`)가 하고
//   화면은 `scm_id`+`doc_paths` 만 싣는다 — 그래서 **행동 검사**로 바꾼다.
describe('measure-source 요청 본문', () => {
  it('서버가 경로를 해석할 수 있는 두 값을 싣는다 (판정 복제 없이)', async () => {
    localStorage.setItem('devops_v2_doc_paths', JSON.stringify({
      sds: 'U:/docs/SwDS.docx', srs: 'U:/docs/SwRS.docx', uds: 'U:/docs/SwUDS.docx',
    }));
    const user = userEvent.setup();
    mockPost.mockImplementation((url) => {
      if (url === '/api/docgen/preflight') {
        return Promise.resolve({
          ok: true, doc_type: 'sits', label: 'SITS', verdict: 'unknown', file_mode: 'local',
          steps: [{
            id: 'test_materials', phase: 'material', state: 'unmeasured', label: '재료',
            reason: '아직 측정하지 않았습니다', actions: [{ kind: 'measure_source' }],
          }],
        });
      }
      return Promise.resolve({ ok: true });
    });
    mountBoard({ analysisResult: { matchedScm: { id: 'kjpds02_pv', source_root: 'D:/src' } } });
    const tr = await waitFor(() => rowOf('📕 SITS'));
    await user.click(within(tr).getByRole('button', { name: '준비' }));
    await user.click(await screen.findByRole('button', { name: '소스 측정' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/api/docgen/measure-source', expect.objectContaining({ doc_type: 'sits' })));
    const body = mockPost.mock.calls.find(c => c[0] === '/api/docgen/measure-source')[1];
    expect(body.scm_id).toBe('kjpds02_pv');
    expect(body.doc_paths).toEqual(expect.objectContaining({
      sds: 'U:/docs/SwDS.docx', srs: 'U:/docs/SwRS.docx', uds: 'U:/docs/SwUDS.docx',
    }));
    // 화면이 다시 경로를 고르기 시작하면 캐시 키가 갈린다 — 그 회귀를 못 박는다.
    expect(body.sds_path).toBeUndefined();
    expect(body.srs_path).toBeUndefined();
    expect(body.uds_path).toBeUndefined();
  });
});

// ── 늦게 온 옛 판정이 새 판정을 덮는가 (2026-08-30) ──────────────────────────
//
// preflight 비용은 소스 측정 캐시 유무로 수십 배 차이가 나서, 먼저 띄운 요청이 나중에
// 도착하는 일이 실제로 일어난다. 순번 대조가 없으면 늦게 온 **옛 판정**이 새 판정을
// 덮어써서, 상한을 방금 올렸는데 화면은 계속 "아직 정하지 않았습니다" 로 남는다 —
// 이 패널이 없애려던 증상(고른 값이 반영 안 된 것처럼 보임) 그 자체다.
describe('DocGenStatusBoard — 응답 역전', () => {
  it('늦게 도착한 옛 preflight 응답이 새 판정을 덮지 않는다', async () => {
    const capStep = (state, reason) => ({
      id: 'cap_max_flows', phase: 'decision', state, label: 'max_flows', reason,
      measured: { api_default: 120, generator_default: 120, adjustable: true, suggested: 145 },
    });
    const payload = (state, reason) => ({
      ok: true, doc_type: 'sits', label: 'SITS', verdict: 'needs_decision',
      file_mode: 'local', steps: [capStep(state, reason)],
    });

    const pending = [];
    mockPost.mockImplementation((url) => {
      if (url !== '/api/docgen/preflight') return Promise.resolve({ suggestions: [] });
      return new Promise(resolve => pending.push(resolve));
    });

    const user = userEvent.setup();
    mountBoard();
    const tr = await waitFor(() => rowOf('📕 SITS'));
    await user.click(within(tr).getByRole('button', { name: '준비' }));

    // 1) 첫 조회는 정상적으로 도착한다.
    await waitFor(() => expect(pending.length).toBe(1));
    pending[0](payload('needed', '아직 정하지 않아 기본값 120 로 만듭니다'));
    await screen.findByText(/아직 정하지 않아/);

    // 2) 값을 정하고(=재조회) → 그 응답이 아직 안 온 사이에 3) 다시 재조회한다.
    await user.click(screen.getByRole('button', { name: /전부 145/ }));
    await waitFor(() => expect(pending.length).toBe(2));
    // 값이 이미 제안값이라 버튼은 사라진다(없는 조치를 만들지 않는 규약) — 두 번째
    // 재조회는 입력칸 blur 로 낸다. 실제 사용자도 그렇게 낸다.
    fireEvent.blur(screen.getByLabelText('max_flows 상한'));
    await waitFor(() => expect(pending.length).toBeGreaterThanOrEqual(3));

    // 최신이 먼저 도착하고, 옛것(2번)이 뒤늦게 도착한다.
    // 인덱스를 pending[2] 로 못박으면 안 된다: 부하가 높으면 재렌더가 preflight 를 한 번
    // 더 낼 수 있고, 그러면 3번은 이미 **낡은** 요청이라 컴포넌트가 정당하게 무시한다 —
    // 테스트는 findByText 타임아웃으로 죽고 원인은 "느리다" 로 오독된다.
    // 재는 것은 "**최신**이 이기고 옛것이 못 덮는다" 이므로 최신은 항상 마지막 것이다.
    // (2026-09-02: 이 고정 인덱스 탓에 전체 실행에서만 실패했다. 파일 단독은 45/45 통과.)
    pending[pending.length - 1](payload('ok', '145 로 정했습니다 — 전량을 담습니다'));
    await screen.findByText(/전량을 담습니다/);
    pending[1](payload('needed', '아직 정하지 않아 기본값 120 로 만듭니다'));

    // 옛 판정이 되살아나면 안 된다.
    await waitFor(() => expect(screen.getByText(/전량을 담습니다/)).toBeInTheDocument());
    expect(screen.queryByText(/아직 정하지 않아/)).toBeNull();
  });
});

/**
 * 게이트가 판정하는 대상이 **생성이 쓰는 대상과 같은가**.
 *
 * 게이트는 `cache_root` 를 `analysisResult?.cacheRoot || ''` 만 썼는데 생성 요청은
 * `analysisResult?.cacheRoot || defaultCacheRoot(job.url) || cfg.cacheRoot` 세 단계를 탔다.
 * 빈 문자열이면 백엔드가 `~/.devops_pro_cache` 로 떨어져(`_normalize_jenkins_cache_root`)
 * 화면이 쓰는 `.devops_pro_cache/<user>` 와 **다른 폴더**를 본다 → UDS 빌드 캐시를
 * "없음(진행 불가)" 으로 보고하는데 정작 생성은 성공한다. 게이트가 생성과 반대말을 한다.
 */
describe('DocGenStatusBoard — 게이트가 생성과 같은 것을 본다', () => {
  const prepCall = () =>
    mockPost.mock.calls.find(([u]) => String(u).includes('/api/docgen/preflight'));

  it('분석 결과에 캐시 루트가 없어도 빈 값으로 판정하지 않는다', async () => {
    const user = userEvent.setup();
    // cacheRoot 가 없는 analysisResult — 영향 탭이 null 에서 만드는 경로의 형태다.
    render(<DocGenStatusBoard job={JOB} analysisResult={{ matchedScm: { id: 'p', name: 'P' } }}
      genState={null} />);
    await waitFor(() => expect(rowOf('📘 UDS')).toBeTruthy());
    await user.click(within(rowOf('📘 UDS')).getByRole('button', { name: '준비' }));
    await waitFor(() => expect(prepCall()).toBeTruthy());
    expect(prepCall()[1].cache_root).toBe('.devops_pro_cache/u');
  });

  it('분석 결과의 캐시 루트가 있으면 그것이 이긴다', async () => {
    const user = userEvent.setup();
    render(<DocGenStatusBoard job={JOB}
      analysisResult={{ matchedScm: { id: 'p', name: 'P' }, cacheRoot: 'X:/explicit' }}
      genState={null} />);
    await waitFor(() => expect(rowOf('📘 UDS')).toBeTruthy());
    await user.click(within(rowOf('📘 UDS')).getByRole('button', { name: '준비' }));
    await waitFor(() => expect(prepCall()).toBeTruthy());
    expect(prepCall()[1].cache_root).toBe('X:/explicit');
  });

  it('판정에 쓰는 상한은 **그 프로젝트 칸**에서 온다', async () => {
    const user = userEvent.setup();
    localStorage.setItem(
      `${DOCGEN_CAPS_KEY}::${JOB.url.replace(/\/+$/, '').toLowerCase()}`,
      JSON.stringify({ max_flows: 321 }));
    localStorage.setItem(
      `${DOCGEN_CAPS_KEY}::http://ci/job/other`, JSON.stringify({ max_flows: 999 }));
    render(<DocGenStatusBoard job={JOB} analysisResult={{ matchedScm: { id: 'p', name: 'P' } }}
      genState={null} />);
    await waitFor(() => expect(rowOf('📘 UDS')).toBeTruthy());
    await user.click(within(rowOf('📘 UDS')).getByRole('button', { name: '준비' }));
    await waitFor(() => expect(prepCall()).toBeTruthy());
    expect(prepCall()[1].caps.max_flows).toBe(321);
  });

  it('상한이 바뀌면 펼쳐 둔 행을 **다시 판정한다**', async () => {
    const user = userEvent.setup();
    render(<DocGenStatusBoard job={JOB} analysisResult={{ matchedScm: { id: 'p', name: 'P' } }}
      genState={null} />);
    await waitFor(() => expect(rowOf('📘 UDS')).toBeTruthy());
    await user.click(within(rowOf('📘 UDS')).getByRole('button', { name: '준비' }));
    await waitFor(() => expect(prepCall()).toBeTruthy());
    const before = mockPost.mock.calls.filter(
      ([u]) => String(u).includes('/api/docgen/preflight')).length;

    // 다른 화면(패널의 입력칸·다른 탭)에서 상한이 바뀐 상황.
    saveDocGenCap('max_flows', 55, JOB.url.replace(/\/+$/, '').toLowerCase());

    // 통지가 없으면 이 행은 옛 판정을 그대로 들고 있다 — 같은 화면의 두 줄이 다른 말을 한다.
    await waitFor(() => {
      const after = mockPost.mock.calls.filter(
        ([u]) => String(u).includes('/api/docgen/preflight')).length;
      expect(after).toBeGreaterThan(before);
    }, { timeout: 3000 });
  });
});

/**
 * 결과 뭉치가 **통째로 다른 Job 의 것**이면 아래 판정 전부가 남의 프로젝트 얘기다.
 * 생성은 `DocGenSection` 이 같은 판정으로 거부하므로, 보드는 그 사실을 미리 말한다 —
 * 버튼을 눌러 보고서야 알게 되면 안 된다.
 */
describe('DocGenStatusBoard — 다른 Job 의 분석 결과를 조용히 쓰지 않는다', () => {
  it('결과가 다른 Job 의 것이면 경고를 띄운다', async () => {
    render(<DocGenStatusBoard job={JOB}
      analysisResult={{ jobUrl: 'http://ci/job/OTHER', matchedScm: { id: 'p', name: 'P' } }}
      genState={null} />);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/현재 프로젝트의 것이 아닙니다/);
    // 사유만 말하고 해소 방법을 안 주면 사용자는 막힌 채로 남는다.
    expect(alert.textContent).toMatch(/대시보드/);
  });

  it('같은 Job 이면 경고를 띄우지 않는다 (상시 경고는 곧 무시된다)', async () => {
    render(<DocGenStatusBoard job={JOB}
      analysisResult={{ jobUrl: JOB.url, matchedScm: { id: 'p', name: 'P' } }} genState={null} />);
    await waitFor(() => expect(rowOf('📘 UDS')).toBeTruthy());
    expect(screen.queryByText(/현재 프로젝트의 것이 아닙니다/)).toBeNull();
  });
});

// ── 조치 버튼은 서버가 준 레지스트리 키로 교체한다 (2026-09-03 감사 P-1) ─────────
//
// `step.id` 는 입력 키(`swrs`/`swds`/`uds_doc`)이고 `adopt-doc-path` 는 레지스트리 키
// (`srs`/`sds`/`uds`)만 받는다. 보드가 `step.id` 를 보내던 동안 대표 조치 버튼은
// `hsis`/`stp`(두 키가 같은 둘) 빼고 전부 `400 알 수 없는 문서 키` 였다.
describe('adopt_suggestion — doc_key 는 action.target 이다', () => {
  it('step.id(입력 키)가 아니라 action.target(레지스트리 키)을 보낸다', async () => {
    const user = userEvent.setup();
    mockPost.mockImplementation((url) => {
      if (url === '/api/docgen/preflight') {
        return Promise.resolve({
          ok: true, doc_type: 'uds', label: 'UDS', verdict: 'blocked', file_mode: 'local',
          steps: [{
            id: 'swrs', phase: 'input', state: 'stale_path', label: 'SwRS(요구사항)',
            required: true, value: 'U:/docs/SwRS_v2.03.docx', suggestion: 'SwRS_v3.01_R.docx',
            reason: '등록 경로에 파일이 없습니다. 같은 폴더의 개정본으로 보입니다',
            actions: [{ kind: 'adopt_suggestion', value: 'SwRS_v3.01_R.docx', target: 'srs' }],
          }],
        });
      }
      if (url === '/api/docgen/adopt-doc-path') {
        return Promise.resolve({ ok: true, new: 'U:/docs/SwRS_v3.01_R.docx' });
      }
      return Promise.resolve({ ok: true });
    });
    mountBoard({ analysisResult: { matchedScm: { id: 'kjpds02_pv', source_root: 'D:/src' } } });
    const tr = await waitFor(() => rowOf('📘 UDS'));
    await user.click(within(tr).getByRole('button', { name: '준비' }));
    await user.click(await screen.findByRole('button', { name: /이 파일로 교체/ }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/api/docgen/adopt-doc-path', expect.objectContaining({ doc_key: 'srs' })));
    const body = mockPost.mock.calls.find(c => c[0] === '/api/docgen/adopt-doc-path')[1];
    expect(body.scm_id).toBe('kjpds02_pv');
    expect(body.filename).toBe('SwRS_v3.01_R.docx');
    // 입력 키가 새어 나가면 서버가 400 을 낸다 — 그 회귀를 못 박는다.
    expect(body.doc_key).not.toBe('swrs');
  });
});

// ── 통합 Summary 준비 점검은 빌드와 **같은 shape** 을 싣는다 (2026-09-03 감사 P-2) ──
//
// 서버는 라우터와 같은 키 `source_paths`(배열)만 읽는다. 원본 폼(`source_paths_text`
// textarea)을 보내면 레벨별 산출물을 게이트가 영영 못 본다.
describe('통합 Summary 준비 점검 — form.source_paths', () => {
  it('textarea 를 배열 source_paths 로 바꿔 싣고 source_paths_text 는 보내지 않는다', async () => {
    localStorage.setItem('devops_v2_swreport_form', JSON.stringify({
      project_id: 'ES95411', release_sw_version: '1.02',
      source_paths_text: 'U:/out/SwUTCR.xlsm\nU:/out/SwITCR.xlsm\n',
    }));
    const user = userEvent.setup();
    mockPost.mockResolvedValue({ ok: true, doc_type: 'swreport', label: '통합 Summary',
      verdict: 'ready', file_mode: 'local', steps: [] });
    mountBoard({ analysisResult: { matchedScm: { id: 'kjpds02_pv', source_root: 'D:/src' } } });
    const tr = await waitFor(() => rowOf('📊 통합 Summary'));
    await user.click(within(tr).getByRole('button', { name: '준비' }));

    await waitFor(() => expect(mockPost).toHaveBeenCalledWith(
      '/api/docgen/preflight', expect.objectContaining({ doc_type: 'swreport' })));
    const body = mockPost.mock.calls.find(c => c[0] === '/api/docgen/preflight')[1];
    expect(body.form.source_paths).toEqual(['U:/out/SwUTCR.xlsm', 'U:/out/SwITCR.xlsm']);
    expect(body.form.source_paths_text).toBeUndefined();

    // [다시 확인](재조회) 경로도 같은 shape 이어야 한다 — 두 진입이 갈리면 한쪽만 고쳐진다.
    await user.click(await screen.findByRole('button', { name: '다시 확인' }));
    await waitFor(() => expect(
      mockPost.mock.calls.filter(c => c[0] === '/api/docgen/preflight').length).toBe(2));
    const again = mockPost.mock.calls.filter(c => c[0] === '/api/docgen/preflight')[1][1];
    expect(again.form.source_paths).toEqual(['U:/out/SwUTCR.xlsm', 'U:/out/SwITCR.xlsm']);
    expect(again.form.source_paths_text).toBeUndefined();
  });
});
