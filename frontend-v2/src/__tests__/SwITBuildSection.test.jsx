/**
 * SwITBuildSection 단위 테스트 (35차 라운드).
 *
 * SwUTBuildSection은 26 회귀로 raw fetch / X-User / Pydantic detail / blob 다운로드
 * 패턴 검증 완료. SwIT는 SwUT 코드 베이스 복제이므로 본 회귀는 SwIT 도구별 차이
 * (3 endpoint / 헤더 명명 / consistency 검증) 위주 8건만.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const toastSpy = vi.fn();
vi.mock('../App.jsx', () => ({
  useToast: () => toastSpy,
}));

vi.mock('../api.js', () => ({
  getUsername: () => 'tester',
  authHeaders: () => ({ 'X-User': 'tester' }),
}));

// 40차: AdminContext mock — 회귀 기본 admin
vi.mock('../contexts/AdminContext.jsx', () => ({
  useAdminMode: () => ({ isAdmin: true, username: 'tester', authenticated: true, loading: false }),
  AdminProvider: ({ children }) => children,
}));

const { default: SwITBuildSection } = await import(
  '../components/sections/SwITBuildSection.jsx'
);


describe('SwITBuildSection', () => {
  beforeEach(() => {
    toastSpy.mockReset();
    localStorage.clear();
    // 39-fix-2: Browse 버튼 admin 가드 — 기존 회귀 통과 위해 admin 모드 활성화
    localStorage.setItem('devops_admin_mode', 'true');
    global.URL.createObjectURL = vi.fn(() => 'blob://mock');
    global.URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders SwIT-specific labels and 3 action buttons (Coverage / SITR / Consistency)', () => {
    render(<SwITBuildSection />);
    // 헤더 텍스트는 여러 곳 가능 — section title <h2> 만 검증
    expect(screen.getByRole('heading', { name: /SwIT 빌드/ })).toBeTruthy();
    expect(screen.getByText(/Coverage Report 빌드/)).toBeTruthy();
    expect(screen.getByText(/📝 SITR 빌드/)).toBeTruthy();
    expect(screen.getByText(/일관성 검증 실행/)).toBeTruthy();
  });

  it('53차 W2 — legacy localStorage template_path → coverage_template_path 마이그레이션', () => {
    // SwIT 52차 C1 fix 검증: 51차 이전 사용자 form 그대로 보존
    localStorage.setItem('devops_v2_swit_form', JSON.stringify({
      template_path: 'U:/legacy/old.xlsx',
      release_sw_version: '2.02',
    }));
    render(<SwITBuildSection />);
    const coverageInput = screen.getByLabelText(/Coverage Template Path/);
    expect(coverageInput.value).toBe('U:/legacy/old.xlsx');
    const sitrInput = screen.getByLabelText(/SITR Template Path/);
    expect(sitrInput.value).toBe('');
  });

  it('renders Browse buttons for path fields (51차 template 분리 + 60차 F6-A/F6-C)', () => {
    render(<SwITBuildSection />);
    // 9개 path 필드 (log_folder / coverage_template_path / sitr_template_path /
    //                swuds_docx_path / swuts_docx_path [60차 F6-B] /
    //                hmr_html_path [60차 F6-C] / c_source_root + 2 path)
    // F6 Round 7 NF7 fix: SwUT 회귀(SwUTBuildSection.test.jsx)와 대칭 — SwIT도
    // 신규 path field 추가 시 Browse 카운트로 회귀 lock.
    const browseButtons = screen.getAllByText(/📂 Browse/);
    expect(browseButtons.length).toBe(9);
  });

  it('default asil_level is "ASIL B" (SwIT Integration test convention)', () => {
    render(<SwITBuildSection />);
    const input = screen.getByLabelText(/ASIL Level/);
    expect(input.value).toBe('ASIL B');
  });

  it('Coverage build calls /api/swit/coverage/build with X-User and X-SwIT-Summary parsed', async () => {
    const mockBlob = new Blob([new Uint8Array([0x50, 0x4b])], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({
        'Content-Disposition': 'attachment; filename="(HDPDM01)SwIT_Coverage.xlsx"',
        'X-SwIT-Summary': JSON.stringify({ environments: 5, total_tcs: 120 }),
        'X-SwIT-Warnings': JSON.stringify([]),
      }),
      blob: async () => mockBlob,
    });

    render(<SwITBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), {
      target: { value: '2.02' },
    });
    fireEvent.change(screen.getByLabelText(/Log Folder/), {
      target: { value: 'C:/fake/log' },
    });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));

    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith('success', expect.stringMatching(/다운로드/));
    });
    // URL + headers 검증
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toContain('/api/swit/coverage/build');
    expect(init.headers['X-User']).toBe('tester');
    // summary 렌더 (X-SwIT-Summary 파싱)
    expect(screen.getByText(/environments/)).toBeTruthy();
  });

  it('SITR build calls /api/swit/sitr/build and defaults filename to .xlsm when Content-Disposition missing', async () => {
    const mockBlob = new Blob([new Uint8Array([0x50, 0x4b])], {
      type: 'application/vnd.ms-excel.sheet.macroenabled.12',
    });
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({}),  // Content-Disposition 없음 → fallback filename
      blob: async () => mockBlob,
    });
    render(<SwITBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), {
      target: { value: '2.02' },
    });
    fireEvent.change(screen.getByLabelText(/Log Folder/), {
      target: { value: 'C:/fake/log' },
    });
    // 📝 prefix로 button 고유 매칭 (heading/desc와 충돌 회피)
    fireEvent.click(screen.getByText(/📝 SITR 빌드/));

    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith('success', expect.stringMatching(/다운로드/));
    });
    const [url] = fetchSpy.mock.calls[0];
    expect(url).toContain('/api/swit/sitr/build');
  });

  it('Consistency check calls /api/swit/consistency/check and renders issue cards', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({ 'Content-Type': 'application/json' }),
      json: async () => ({
        ok: false,
        issues: [
          {
            severity: 'warning',
            category: 'total_tc',
            message: 'Total TC 불일치: Coverage=100, SITR=105',
          },
        ],
        parse_warnings: [],
      }),
    });

    render(<SwITBuildSection />);
    fireEvent.change(screen.getByLabelText(/Coverage Report Path/), {
      target: { value: 'C:/fake/cov.xlsx' },
    });
    fireEvent.change(screen.getByLabelText(/SITR Path/), {
      target: { value: 'C:/fake/sitr.xlsm' },
    });
    fireEvent.click(screen.getByText(/일관성 검증 실행/));

    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith(
        'warning',
        expect.stringMatching(/issue.*1.*건/),
      );
    });
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toContain('/api/swit/consistency/check');
    expect(init.headers['X-User']).toBe('tester');
    // issue 카드 렌더
    expect(screen.getByText(/total_tc/)).toBeTruthy();
    expect(screen.getByText(/Total TC 불일치/)).toBeTruthy();
  });

  it('rejects missing coverage_path in consistency check', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch');
    render(<SwITBuildSection />);
    fireEvent.click(screen.getByText(/일관성 검증 실행/));
    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith(
        'warning',
        expect.stringMatching(/coverage_path/),
      );
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('rejects missing sitr_path in consistency check', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch');
    render(<SwITBuildSection />);
    fireEvent.change(screen.getByLabelText(/Coverage Report Path/), {
      target: { value: 'C:/fake/cov.xlsx' },
    });
    fireEvent.click(screen.getByText(/일관성 검증 실행/));
    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith(
        'warning',
        expect.stringMatching(/sitr_path/),
      );
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  // 38차 W4: log_folder dry-run preview button + panel
  it('preview button calls /api/swit/log-folder/preview and renders candidates panel', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({ 'Content-Type': 'application/json' }),
      json: async () => ({
        input_log_folder: 'C:/fake/01.Log',
        resolved_log_folder: 'C:/fake/01.Log/v2.10_241201',
        auto_resolved: true,
        candidates: [
          { name: 'v2.10_241201', date_suffix: '241201', is_latest: true },
          { name: 'v2.02_240219', date_suffix: '240219', is_latest: false },
        ],
        warnings: ["log_folder auto-resolved: 'v2.10_241201' (2개 후보)"],
      }),
    });

    render(<SwITBuildSection />);
    fireEvent.change(screen.getByLabelText(/Log Folder/), {
      target: { value: 'C:/fake/01.Log' },
    });
    fireEvent.click(screen.getByTestId('swit-preview-button'));

    await waitFor(() => {
      expect(screen.getByTestId('swit-preview-panel')).toBeTruthy();
    });
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toContain('/api/swit/log-folder/preview');
    expect(init.headers['X-User']).toBe('tester');
    // 후보 + 자동 선택 표시 렌더 (resolved_log_folder + candidates 모두 v2.10 포함 — getAllByText)
    expect(screen.getAllByText(/v2.10_241201/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/v2.02_240219/)).toBeTruthy();
    expect(screen.getByText(/이 release 자동 선택/)).toBeTruthy();
  });

  it('preview rejects empty log_folder with toast warning', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch');
    render(<SwITBuildSection />);
    fireEvent.click(screen.getByTestId('swit-preview-button'));
    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith('warning', expect.stringMatching(/log_folder/));
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('localStorage key separation — devops_v2_swit_form (SwUT의 swut_form과 분리)', () => {
    render(<SwITBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), {
      target: { value: '2.02' },
    });
    const saved = JSON.parse(
      localStorage.getItem('devops_v2_swit_form') || '{}',
    );
    expect(saved.release_sw_version).toBe('2.02');
    // SwUT 키와 분리
    expect(localStorage.getItem('devops_v2_swut_form')).toBeNull();
  });

  it('55차 — renders blocked_inferred warning panel when summary flag is true', async () => {
    const mockBlob = new Blob([new Uint8Array([0x50, 0x4b])], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({
        'Content-Disposition': 'attachment; filename="(HDPDM01)SwIT_v202.xlsx"',
        'X-SwIT-Summary': JSON.stringify({
          environments: 1,
          total_tcs: 2,
          tc_stats_blocked_inferred: true,
        }),
        'X-SwIT-Warnings': JSON.stringify([]),
      }),
      blob: async () => mockBlob,
    });

    render(<SwITBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), {
      target: { value: '2.02' },
    });
    fireEvent.change(screen.getByLabelText(/Log Folder/), {
      target: { value: 'C:/fake/log' },
    });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));

    await waitFor(() => {
      expect(screen.getByTestId('swit-blocked-inferred-warning')).toBeTruthy();
    });
    const panel = screen.getByRole('alert');
    expect(panel.textContent).toMatch(/Blocked = 0 \(inferred\)/);
  });

  it('55차 — does not render blocked_inferred panel when flag is false or absent', async () => {
    const mockBlob = new Blob([new Uint8Array([0x50, 0x4b])], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({
        'Content-Disposition': 'attachment; filename="(HDPDM01)SwIT_v301.xlsx"',
        // tc_stats_blocked_inferred 키 부재 (v3.01 양식)
        'X-SwIT-Summary': JSON.stringify({ environments: 1, total_tcs: 2 }),
        'X-SwIT-Warnings': JSON.stringify([]),
      }),
      blob: async () => mockBlob,
    });

    render(<SwITBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), {
      target: { value: '2.02' },
    });
    fireEvent.change(screen.getByLabelText(/Log Folder/), {
      target: { value: 'C:/fake/log' },
    });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));

    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith('success', expect.stringMatching(/다운로드/));
    });
    // 빌드 success 후에도 inferred panel 미렌더
    expect(screen.queryByTestId('swit-blocked-inferred-warning')).toBeNull();
  });
});
