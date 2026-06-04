/**
 * SwSABuildSection 단위 테스트.
 *
 * SwUT/SwIT 패턴 복제 — SwSA 도구별 차이(단일 /api/swsa/report/build endpoint /
 * X-SwSA-* 헤더 / template_path 필수 검증 / log_folder 미지정 info) 위주.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const toastSpy = vi.fn();
vi.mock('../App.jsx', () => ({ useToast: () => toastSpy }));
vi.mock('../api.js', () => ({
  getUsername: () => 'tester',
  authHeaders: () => ({ 'X-User': 'tester' }),
}));
vi.mock('../contexts/AdminContext.jsx', () => ({
  useAdminMode: () => ({ isAdmin: true, username: 'tester', authenticated: true, loading: false }),
  AdminProvider: ({ children }) => children,
}));

const { default: SwSABuildSection } = await import(
  '../components/sections/SwSABuildSection.jsx'
);

function setInput(name, value) {
  const el = document.getElementById(`swsa-${name}`);
  fireEvent.change(el, { target: { value } });
}

describe('SwSABuildSection', () => {
  beforeEach(() => {
    toastSpy.mockReset();
    localStorage.clear();
    localStorage.setItem('devops_admin_mode', 'true');
    global.URL.createObjectURL = vi.fn(() => 'blob://mock');
    global.URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it('renders SwSA heading + build button + key fields', () => {
    render(<SwSABuildSection />);
    expect(screen.getByRole('heading', { name: /SwSA 빌드/ })).toBeTruthy();
    expect(screen.getByText(/SwSA Report 빌드/)).toBeTruthy();
    expect(document.getElementById('swsa-log_folder')).toBeTruthy();
    expect(document.getElementById('swsa-template_path')).toBeTruthy();
  });

  it('template_path 미지정 시 빌드 차단 + warning', () => {
    render(<SwSABuildSection />);
    setInput('release_sw_version', '2631.00');
    fireEvent.click(screen.getByText(/SwSA Report 빌드/));
    expect(toastSpy).toHaveBeenCalledWith('warning', expect.stringMatching(/template_path/));
  });

  it('성공 빌드 → /api/swsa/report/build 호출 + X-User + X-SwSA-Summary 파싱 + 다운로드', async () => {
    const mockBlob = new Blob([new Uint8Array([0x50, 0x4b])], {
      type: 'application/vnd.ms-excel.sheet.macroEnabled.12',
    });
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({
        'Content-Disposition': "attachment; filename=\"(KJPDS02_SwSA).xlsm\"",
        'X-SwSA-Summary': JSON.stringify({ sheets_filled: ['Cover', '1.ST101'], filled_cells: 23, user_input_cells: 1, vba_preserved: true, logs_discovered: 5, modules: ['APP', 'BOOT'] }),
        'X-SwSA-Warnings': JSON.stringify(['2.ST201: 무소스 메트릭 skip']),
      }),
      blob: async () => mockBlob,
    });

    render(<SwSABuildSection />);
    setInput('release_sw_version', '2631.00');
    setInput('template_path', 'U:/x/(XXXX_SwSA)_v0.10.xlsm');
    setInput('log_folder', 'U:/x/01.Log/PV');
    fireEvent.click(screen.getByText(/SwSA Report 빌드/));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const [url, opts] = fetchSpy.mock.calls[0];
    expect(url).toMatch(/\/api\/swsa\/report\/build$/);
    expect(opts.headers['X-User']).toBe('tester');
    const body = JSON.parse(opts.body);
    expect(body.project_id).toBe('KJPDS02');
    expect(body.template_path).toMatch(/SwSA/);
    // extra='forbid' 호환 — UI 전용 여분 키 없음
    expect(body).not.toHaveProperty('building');

    await waitFor(() => expect(screen.getByText(/마지막 빌드 결과/)).toBeTruthy());
    expect(screen.getByText(/Cover, 1.ST101/)).toBeTruthy();
    await waitFor(() => expect(screen.getByText(/무소스 메트릭 skip/)).toBeTruthy());
    expect(toastSpy).toHaveBeenCalledWith('success', expect.stringMatching(/다운로드 완료/));
  });

  it('log_folder 미지정 → info 안내 후에도 빌드 진행', async () => {
    const mockBlob = new Blob([new Uint8Array([0x50, 0x4b])], { type: 'application/octet-stream' });
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true, headers: new Headers({}), blob: async () => mockBlob,
    });
    render(<SwSABuildSection />);
    setInput('release_sw_version', '2631.00');
    setInput('template_path', 'U:/x/tpl.xlsm');
    fireEvent.click(screen.getByText(/SwSA Report 빌드/));
    expect(toastSpy).toHaveBeenCalledWith('info', expect.stringMatching(/노란 표시/));
    await waitFor(() => expect(toastSpy).toHaveBeenCalledWith('success', expect.anything()));
  });

  it('422 detail 배열 → 사람 친화 메시지 error toast', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      headers: new Headers({ 'Content-Type': 'application/json' }),
      json: async () => ({ detail: [{ loc: ['body', 'release_sw_version'], msg: 'string does not match pattern' }] }),
    });
    render(<SwSABuildSection />);
    setInput('release_sw_version', 'abc');
    setInput('template_path', 'U:/x/tpl.xlsm');
    fireEvent.click(screen.getByText(/SwSA Report 빌드/));
    await waitFor(() => expect(toastSpy).toHaveBeenCalledWith(
      'error', expect.stringMatching(/release_sw_version/)));
  });
});
