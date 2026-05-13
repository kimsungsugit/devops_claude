/**
 * SwUTBuildSection 단위 테스트 (10차 라운드 T148).
 *
 * 핵심 검증:
 * - Form 입력 필드 렌더링
 * - 필수 필드 누락 시 toast warning + fetch 호출 안 함
 * - 빌드 성공 시 blob 다운로드 trigger + summary/warnings 표시
 * - 빌드 실패 시 (HTTP 422 Pydantic detail) 명시적 에러 toast
 * - raw fetch silent failure 회피 — X-User 헤더 명시 + res.ok 검사
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// localStorage / fetch mock
const toastSpy = vi.fn();
vi.mock('../App.jsx', () => ({
  useToast: () => toastSpy,
}));

vi.mock('../api.js', () => ({
  getUsername: () => 'tester',
}));

const { default: SwUTBuildSection } = await import('../components/sections/SwUTBuildSection.jsx');


describe('SwUTBuildSection', () => {
  beforeEach(() => {
    toastSpy.mockReset();
    localStorage.clear();
    // URL.createObjectURL mock (jsdom 미지원)
    global.URL.createObjectURL = vi.fn(() => 'blob://mock');
    global.URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders core form fields and build buttons', () => {
    render(<SwUTBuildSection />);
    expect(screen.getByLabelText(/Project ID/)).toBeTruthy();
    expect(screen.getByLabelText(/Release SW Version/)).toBeTruthy();
    expect(screen.getByText(/Coverage Report 빌드/)).toBeTruthy();
    expect(screen.getByText(/SUTR 빌드/)).toBeTruthy();
  });

  it('rejects missing release_sw_version with toast warning (no fetch)', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch');
    render(<SwUTBuildSection />);
    // release_sw_version 빈 채로 클릭
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));
    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith('warning', expect.stringMatching(/release/));
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('rejects missing log_folder + template_path with toast warning', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch');
    render(<SwUTBuildSection />);
    // 필수 필드 채우되 log_folder / template_path 둘 다 비움
    fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '2.02' } });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));
    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith('warning', expect.stringMatching(/log_folder.*template/));
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('downloads xlsx blob on success + shows summary', async () => {
    const blobContent = new Uint8Array([0x50, 0x4b, 0x03, 0x04]); // ZIP magic
    const mockBlob = new Blob([blobContent], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });

    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({
        'Content-Disposition': 'attachment; filename="(HDPDM01)Cov_v2.02.xlsx"',
        'X-SwUT-Summary': JSON.stringify({ environments: 30, total_tcs: 1941 }),
        'X-SwUT-Warnings': JSON.stringify(['placeholder sheet']),
      }),
      blob: async () => mockBlob,
    });

    render(<SwUTBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '2.02' } });
    fireEvent.change(screen.getByLabelText(/Log Folder/), {
      target: { value: 'C:/fake/log' },
    });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));

    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith('success', expect.stringMatching(/다운로드/));
    });
    // summary 렌더링
    expect(screen.getByText(/environments/)).toBeTruthy();
    expect(global.URL.createObjectURL).toHaveBeenCalled();
  });

  it('propagates Pydantic 422 detail array as toast error', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 422,
      headers: new Headers(),
      json: async () => ({
        detail: [
          { loc: ['body', 'release_sw_version'], msg: 'String should match pattern', type: 'string_pattern_mismatch' },
        ],
      }),
    });

    render(<SwUTBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '2.02' } });
    fireEvent.change(screen.getByLabelText(/Log Folder/), {
      target: { value: 'C:/fake/log' },
    });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));

    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith('error', expect.stringMatching(/release_sw_version/));
    });
    // 11차 W1: loc에서 'body' 제거되고 msg 표시 — 명확한 형식
    const errorCall = toastSpy.mock.calls.find(c => c[0] === 'error');
    expect(errorCall[1]).toContain('release_sw_version: String should match pattern');
    expect(errorCall[1]).not.toContain('body.');
  });

  it('falls back to d.type when Pydantic detail item has no msg (W1)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 422,
      headers: new Headers(),
      json: async () => ({
        detail: [{ loc: ['body', 'doc_id_sequence'], type: 'string_pattern_mismatch' }],
      }),
    });

    render(<SwUTBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '2.02' } });
    fireEvent.change(screen.getByLabelText(/Log Folder/), {
      target: { value: 'C:/fake/log' },
    });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));

    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith('error', expect.stringMatching(/doc_id_sequence/));
    });
    const errorCall = toastSpy.mock.calls.find(c => c[0] === 'error');
    expect(errorCall[1]).toContain('string_pattern_mismatch');
  });

  it('inputs have anti-autocomplete attributes (W2)', () => {
    render(<SwUTBuildSection />);
    const engineerInput = screen.getByLabelText(/Test Engineer/);
    expect(engineerInput.getAttribute('autocomplete')).toBe('off');
    expect(engineerInput.getAttribute('autocorrect')).toBe('off');
    expect(engineerInput.getAttribute('autocapitalize')).toBe('off');
    expect(engineerInput.getAttribute('spellcheck')).toBe('false');
    expect(engineerInput.getAttribute('data-form-type')).toBe('other');
    expect(engineerInput.getAttribute('data-lpignore')).toBe('true');
  });

  it('fetch is called with AbortSignal (W3 — unmount safety)', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({ 'Content-Disposition': 'attachment; filename="x.xlsx"' }),
      blob: async () => new Blob([new Uint8Array([0x50, 0x4b, 0x03, 0x04])]),
    });

    render(<SwUTBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '2.02' } });
    fireEvent.change(screen.getByLabelText(/Log Folder/), {
      target: { value: 'C:/fake/log' },
    });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });
    const opts = fetchSpy.mock.calls[0][1];
    expect(opts.signal).toBeDefined();
    expect(opts.signal.constructor.name).toBe('AbortSignal');
  });

  it('sends X-User header in fetch (raw fetch silent failure 회피)', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({ 'Content-Disposition': 'attachment; filename="x.xlsx"' }),
      blob: async () => new Blob([new Uint8Array([0x50, 0x4b, 0x03, 0x04])]),
    });

    render(<SwUTBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '2.02' } });
    fireEvent.change(screen.getByLabelText(/Log Folder/), {
      target: { value: 'C:/fake/log' },
    });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });
    const opts = fetchSpy.mock.calls[0][1];
    expect(opts.headers['X-User']).toBe('tester');
    expect(opts.method).toBe('POST');
  });

  it('renders swuds_docx_path input field (17차 T174)', () => {
    render(<SwUTBuildSection />);
    const swudsInput = screen.getByLabelText(/SwUDS Docx Path/);
    expect(swudsInput).toBeTruthy();
    expect(swudsInput.getAttribute('name')).toBe('swuds_docx_path');
    // 자동완성 차단 속성 (11차 패턴 그대로)
    expect(swudsInput.getAttribute('autocomplete')).toBe('off');
  });

  it('includes swuds_docx_path in POST body when provided (17차)', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({ 'Content-Disposition': 'attachment; filename="x.xlsx"' }),
      blob: async () => new Blob([new Uint8Array([0x50, 0x4b, 0x03, 0x04])]),
    });

    render(<SwUTBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '2.02' } });
    fireEvent.change(screen.getByLabelText(/Log Folder/), { target: { value: 'C:/fake/log' } });
    fireEvent.change(screen.getByLabelText(/SwUDS Docx Path/), {
      target: { value: 'U:/docs/SwUDS_v3.docx' },
    });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });
    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(body.swuds_docx_path).toBe('U:/docs/SwUDS_v3.docx');
  });

  it('revokes object URL immediately on unmount (F5 — 13차)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({ 'Content-Disposition': 'attachment; filename="x.xlsx"' }),
      blob: async () => new Blob([new Uint8Array([0x50, 0x4b, 0x03, 0x04])]),
    });

    const { unmount } = render(<SwUTBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '2.02' } });
    fireEvent.change(screen.getByLabelText(/Log Folder/), {
      target: { value: 'C:/fake/log' },
    });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));

    await waitFor(() => {
      expect(global.URL.createObjectURL).toHaveBeenCalled();
    });

    // 컴포넌트 unmount — useEffect cleanup이 revokeObjectURL 즉시 호출해야 함
    unmount();
    expect(global.URL.revokeObjectURL).toHaveBeenCalledWith('blob://mock');
  });

  // ── 19차 — Consistency Check UI ──────────────────────────────────────

  it('renders consistency check section + 일관성 검증 button (19차)', () => {
    render(<SwUTBuildSection />);
    expect(screen.getByText(/Coverage ↔ SUTR 일관성 검증/)).toBeTruthy();
    expect(screen.getByLabelText(/Coverage Report Path/)).toBeTruthy();
    expect(screen.getByLabelText(/SUTR Path/)).toBeTruthy();
    expect(screen.getByText(/일관성 검증 실행/)).toBeTruthy();
  });

  it('rejects missing coverage_path with toast warning (19차)', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch');
    render(<SwUTBuildSection />);
    fireEvent.click(screen.getByText(/일관성 검증 실행/));
    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith('warning', expect.stringMatching(/coverage_path/));
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('renders issues from consistency response with severity classes (19차)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers(),
      json: async () => ({
        ok: false,
        issues: [
          { severity: 'warning', category: 'uncovered_mismatch', message: 'SwUFn_0001 mismatch' },
          { severity: 'critical', category: 'total_tc', message: 'TC count mismatch' },
        ],
        parse_warnings: [],
      }),
    });

    render(<SwUTBuildSection />);
    fireEvent.change(screen.getByLabelText(/Coverage Report Path/), {
      target: { value: 'C:/cov.xlsx' },
    });
    fireEvent.change(screen.getByLabelText(/SUTR Path/), {
      target: { value: 'C:/sutr.xlsm' },
    });
    fireEvent.click(screen.getByText(/일관성 검증 실행/));

    await waitFor(() => {
      expect(screen.getByText(/SwUFn_0001 mismatch/)).toBeTruthy();
    });
    expect(screen.getByText(/TC count mismatch/)).toBeTruthy();
    expect(screen.getByText(/issue 2건/)).toBeTruthy();
  });

  it('renders Browse buttons for path fields (21차 + 30차 W21)', () => {
    render(<SwUTBuildSection />);
    // 6개 path 필드 (log_folder / template_path / swuds_docx_path /
    //                c_source_root [30차] / coverage_path / sutr_path)
    const browseButtons = screen.getAllByText(/📂 Browse/);
    expect(browseButtons.length).toBe(6);
  });

  it('renders reviewer/approver/validation_date input fields (26차 W16)', () => {
    render(<SwUTBuildSection />);
    expect(screen.getByLabelText(/^Reviewer$/)).toBeTruthy();
    expect(screen.getByLabelText(/^Approver$/)).toBeTruthy();
    expect(screen.getByLabelText(/^Validation Date$/)).toBeTruthy();
    // hint 가이드 (각 필드 빈 상태면 산출물 노란 강조 안내)
    expect(screen.getAllByText(/노란 강조/).length).toBeGreaterThanOrEqual(3);
  });

  it('includes reviewer_override/approver_override/validation_date in POST body (26차)', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({ 'Content-Disposition': 'attachment; filename="x.xlsx"' }),
      blob: async () => new Blob([new Uint8Array([0x50, 0x4b, 0x03, 0x04])]),
    });

    render(<SwUTBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '2.02' } });
    fireEvent.change(screen.getByLabelText(/Log Folder/), { target: { value: 'C:/log' } });
    fireEvent.change(screen.getByLabelText(/^Reviewer$/), { target: { value: 'KH Park' } });
    fireEvent.change(screen.getByLabelText(/^Approver$/), { target: { value: 'CH In' } });
    fireEvent.change(screen.getByLabelText(/^Validation Date$/), { target: { value: '2024-02-25' } });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });
    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(body.reviewer_override).toBe('KH Park');
    expect(body.approver_override).toBe('CH In');
    expect(body.validation_date).toBe('2024-02-25');
  });

  it('renders hint text for path fields (25차)', () => {
    render(<SwUTBuildSection />);
    // log_folder + template_path + swuds_docx_path 각각 hint 표시
    expect(screen.getByText(/VectorCAST html report/)).toBeTruthy();
    expect(screen.getByText(/회사 v3.01 양식 template/)).toBeTruthy();
    expect(screen.getByText(/SwUDS↔SwUTS 함수 ID 매핑 row 자동 추가/)).toBeTruthy();
    // 메타 hint 일부
    expect(screen.getByText(/노란 강조 표시/)).toBeTruthy();
  });

  it('opens picker dialog when Browse clicked (21차)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers(),
      json: async () => ({
        ok: true, current: '', parent: '',
        dirs: ['C:/folder1'], files: ['C:/file1.xlsx'],
        truncated: false,
      }),
    });

    render(<SwUTBuildSection />);
    const browseButtons = screen.getAllByText(/📂 Browse/);
    // Log folder Browse 버튼 클릭
    fireEvent.click(browseButtons[0]);
    await waitFor(() => {
      expect(screen.getByText(/Log 디렉토리 선택/)).toBeTruthy();
    });
    expect(screen.getByText(/folder1/)).toBeTruthy();
  });

  it('sends X-User header + AbortSignal in consistency fetch (19차)', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers(),
      json: async () => ({ ok: true, issues: [], parse_warnings: [] }),
    });

    render(<SwUTBuildSection />);
    fireEvent.change(screen.getByLabelText(/Coverage Report Path/), {
      target: { value: 'C:/cov.xlsx' },
    });
    fireEvent.change(screen.getByLabelText(/SUTR Path/), {
      target: { value: 'C:/sutr.xlsm' },
    });
    fireEvent.click(screen.getByText(/일관성 검증 실행/));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });
    // 첫 번째 호출 (이전 테스트 빌드 trigger 없으므로 calls[0])
    const consistencyCall = fetchSpy.mock.calls.find(c => c[0].includes('/consistency/check'));
    expect(consistencyCall).toBeTruthy();
    const opts = consistencyCall[1];
    expect(opts.headers['X-User']).toBe('tester');
    expect(opts.method).toBe('POST');
    expect(opts.signal).toBeDefined();
    expect(opts.signal.constructor.name).toBe('AbortSignal');
  });

  // ── 30차 W21 — c_source_root Field + ASIL 분포 패널 + ASIL D 강조 ──

  it('renders c_source_root Field with hint about Doxygen @asil tag', () => {
    render(<SwUTBuildSection />);
    const field = screen.getByLabelText(/C Source Root/);
    expect(field).toBeTruthy();
    // hint 텍스트가 ASIL 추출 + Excel 강조 + UI 분포 패널을 모두 안내
    expect(screen.getByText(/@asil 태그.*ASIL D 함수는 Excel 빨강/)).toBeTruthy();
  });

  it('hides ASIL distribution panel when summary has no asil_distribution', async () => {
    // 빌드 trigger 없으면 lastSummary === null → 패널 미렌더
    render(<SwUTBuildSection />);
    expect(screen.queryByTestId('swut-asil-distribution')).toBeNull();
  });

  it('renders ASIL distribution panel with ASIL D highlighted when summary contains data', async () => {
    // mock fetch 응답에 X-SwUT-Summary 헤더 + asil_distribution + asil_d_function_ids 포함
    const fakeBlob = new Blob(['x'], { type: 'application/octet-stream' });
    const fakeSummary = {
      function_rows: 5,
      asil_distribution: { ASIL_A: 2, ASIL_B: 1, ASIL_D: 2, UNKNOWN: 0 },
      asil_d_function_ids: ['SwUFn_0103', 'SwUFn_0107'],
    };
    const fakeHeaders = new Headers({
      'X-SwUT-Summary': JSON.stringify(fakeSummary),
      'X-SwUT-Warnings': JSON.stringify([]),
      'X-SwUT-Filename': 'cov.xlsx',
    });
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      status: 200,
      headers: fakeHeaders,
      blob: () => Promise.resolve(fakeBlob),
      json: () => Promise.resolve({}),
      text: () => Promise.resolve(''),
    });

    render(<SwUTBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), {
      target: { value: '1.0.0' },
    });
    // log_folder 또는 template_path 중 하나 필수 (client validation 통과용)
    fireEvent.change(screen.getByLabelText(/Log Folder/), {
      target: { value: 'C:/fake/log' },
    });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));

    // 1) fetch 호출 확인 (build trigger 도달)
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });
    // 2) state update 후 패널 렌더
    const panel = await screen.findByTestId('swut-asil-distribution');
    expect(panel).toBeTruthy();
    // 3) ASIL D 항목 강조 — 클래스 'swut-asil-d' 부착
    const asilDItem = panel.querySelector('li[data-asil-bucket="ASIL_D"]');
    expect(asilDItem).toBeTruthy();
    expect(asilDItem.className).toContain('swut-asil-d');
    // 4) ASIL D 함수 ID 노출 — 패널 내부 .swut-asil-d-functions에 한정
    const functionsBox = panel.querySelector('.swut-asil-d-functions');
    expect(functionsBox).toBeTruthy();
    expect(functionsBox.textContent).toContain('SwUFn_0103');
    expect(functionsBox.textContent).toContain('SwUFn_0107');
  });
});
