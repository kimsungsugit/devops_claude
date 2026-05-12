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
});
