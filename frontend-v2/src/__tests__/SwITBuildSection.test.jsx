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

  it('renders SwIT-specific labels and action buttons (Coverage / SITR / SwITCR / Consistency)', () => {
    render(<SwITBuildSection />);
    // 헤더 텍스트는 여러 곳 가능 — section title <h2> 만 검증
    expect(screen.getByRole('heading', { name: /SwIT 빌드/ })).toBeTruthy();
    expect(screen.getByText(/Coverage Report 빌드/)).toBeTruthy();
    expect(screen.getByText(/📝 SITR 빌드/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /SwITCR 빌드/ })).toBeTruthy();
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
    // 13개 path 필드 (log_folder / coverage_template_path / sitr_template_path /
    //                switcr_template_path / switcv_path / switr_path / fault_injection_result_path /
    //                swuds_docx_path / swuts_docx_path [60차 F6-B] /
    //                hmr_html_path [60차 F6-C] / c_source_root + 2 path)
    // F6 Round 7 NF7 fix: SwUT 회귀(SwUTBuildSection.test.jsx)와 대칭 — SwIT도
    // 신규 path field 추가 시 Browse 카운트로 회귀 lock.
    const browseButtons = screen.getAllByText(/📂 Browse/);
    expect(browseButtons.length).toBe(13);
  });

  it('Browse 버튼이 JSX duplicate attribute warning을 발화하지 않음 (F6 Round 9 NW12)', () => {
    // F6 Round 8 deep-reviewer 발견: SwITBuildSection.jsx 659-685 두 곳에서
    // disabled / title 속성이 4줄 중복 → silent inconsistency 위험. Round 9
    // fix로 중복 제거. console.warn capture로 회귀 lock.
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<SwITBuildSection />);
    const dupMessages = [
      ...warnSpy.mock.calls.flat(),
      ...errorSpy.mock.calls.flat(),
    ].filter(m => typeof m === 'string' && /Duplicate.*attribute/i.test(m));
    expect(dupMessages).toEqual([]);
    warnSpy.mockRestore();
    errorSpy.mockRestore();
  });

  it('default asil_level is "ASIL B" (SwIT Integration test convention)', () => {
    render(<SwITBuildSection />);
    const input = screen.getByLabelText(/ASIL Level/);
    expect(input.value).toBe('ASIL B');
  });

  it('includes SwIT template/spec/HMR/source override paths in POST body', async () => {
    const mockBlob = new Blob([new Uint8Array([0x50, 0x4b])], {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    });
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({
        'Content-Disposition': 'attachment; filename="switcv.xlsx"',
        'X-SwIT-Summary': JSON.stringify({ environments: 1 }),
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
    fireEvent.change(screen.getByLabelText(/Coverage Template Path/), {
      target: { value: 'U:/template/switcv.xlsx' },
    });
    fireEvent.change(screen.getByLabelText(/SITR Template Path/), {
      target: { value: 'U:/template/switr.xlsm' },
    });
    fireEvent.change(screen.getByLabelText(/SwITCR Template Path/), {
      target: { value: 'U:/template/switcr.xlsm' },
    });
    fireEvent.change(screen.getByLabelText(/SwITCV Evidence Path/), {
      target: { value: 'U:/evidence/switcv.xlsx' },
    });
    fireEvent.change(screen.getByLabelText(/SwITR Evidence Path/), {
      target: { value: 'U:/evidence/switr.xlsm' },
    });
    fireEvent.change(screen.getByLabelText(/Fault Injection Evidence Path/), {
      target: { value: 'U:/evidence/fault_injection.xlsx' },
    });
    fireEvent.change(screen.getByLabelText(/SwITS Spec Path/), {
      target: { value: 'U:/spec/swits.xlsm' },
    });
    fireEvent.change(screen.getByLabelText(/HMR HTML Path/), {
      target: { value: 'U:/logs/Jenkins_PDSM_IT_metrics_report.html' },
    });
    fireEvent.change(screen.getByLabelText(/C Source Root/), {
      target: { value: 'U:/src/PDS' },
    });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });
    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
    expect(body.coverage_template_path).toBe('U:/template/switcv.xlsx');
    expect(body.sitr_template_path).toBe('U:/template/switr.xlsm');
    expect(body.switcr_template_path).toBe('U:/template/switcr.xlsm');
    expect(body.switcv_path).toBe('U:/evidence/switcv.xlsx');
    expect(body.switr_path).toBe('U:/evidence/switr.xlsm');
    expect(body.fault_injection_result_path).toBe('U:/evidence/fault_injection.xlsx');
    expect(body.swuts_docx_path).toBe('U:/spec/swits.xlsm');
    expect(body.hmr_html_path).toBe('U:/logs/Jenkins_PDSM_IT_metrics_report.html');
    expect(body.c_source_root).toBe('U:/src/PDS');
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

  it('SwITCR build calls /api/swit/switcr/build and downloads xlsm', async () => {
    const mockBlob = new Blob([new Uint8Array([0x50, 0x4b])], {
      type: 'application/vnd.ms-excel.sheet.macroenabled.12',
    });
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers({
        'Content-Disposition': 'attachment; filename="switcr.xlsm"',
        'X-SwIT-Summary': JSON.stringify({ switcr_function_count: 570 }),
        'X-SwIT-Warnings': JSON.stringify([]),
      }),
      blob: async () => mockBlob,
    });
    render(<SwITBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), {
      target: { value: '1.01' },
    });
    fireEvent.change(screen.getByLabelText(/Log Folder/), {
      target: { value: 'C:/fake/log' },
    });
    fireEvent.click(screen.getByRole('button', { name: /SwITCR 빌드/ }));

    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith('success', expect.stringMatching(/다운로드/));
    });
    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toContain('/api/swit/switcr/build');
    expect(init.headers['X-User']).toBe('tester');
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

describe('SwITBuildSection — 라운드 96-보강 다중 로그 폴더 (log_folders)', () => {
  beforeEach(() => {
    toastSpy.mockReset();
    localStorage.clear();
    localStorage.setItem('devops_admin_mode', 'true');
    global.URL.createObjectURL = vi.fn(() => 'blob://mock');
    global.URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('textarea 입력 시 payload에 log_folders 배열 포함 + UI 전용 키 제거', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockRejectedValue(new Error('network mock'));
    render(<SwITBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '0.10' } });
    fireEvent.change(screen.getByTestId('swit-log-folders-text'), {
      target: { value: 'U:/pv/APP\n\n  U:/pv/BOOT/Report  \n' },
    });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
    // 빈 줄 제거 + trim — backend 우선순위: log_folders > log_folder > config
    expect(body.log_folders).toEqual(['U:/pv/APP', 'U:/pv/BOOT/Report']);
    expect(body).not.toHaveProperty('log_folders_text');
  });

  it('8개 초과(9개부터) 입력 시 warning + 빌드 차단 (backend max_length=8 선반영)', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch');
    render(<SwITBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '0.10' } });
    const nine = Array.from({ length: 9 }, (_, i) => `U:/p${i}`).join('\n');
    fireEvent.change(screen.getByTestId('swit-log-folders-text'), { target: { value: nine } });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));
    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith('warning', expect.stringMatching(/최대 8개/));
    });
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('단일 log_folder만 입력 시 분리 로그 안내 note 렌더 / 다중 입력 시 미렌더', () => {
    render(<SwITBuildSection />);
    expect(screen.queryByTestId('swit-single-folder-note')).toBeNull();
    fireEvent.change(screen.getByLabelText(/^Log Folder/), { target: { value: 'C:/one' } });
    expect(screen.getByTestId('swit-single-folder-note')).toBeTruthy();
    fireEvent.change(screen.getByTestId('swit-log-folders-text'), { target: { value: 'C:/a\nC:/b' } });
    expect(screen.queryByTestId('swit-single-folder-note')).toBeNull();
  });

  it('모두 비우면 config fallback 안내(info) 후 빌드 진행', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockRejectedValue(new Error('network mock'));
    render(<SwITBuildSection />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '0.10' } });
    fireEvent.click(screen.getByText(/Coverage Report 빌드/));
    await waitFor(() => {
      expect(toastSpy).toHaveBeenCalledWith('info', expect.stringMatching(/config 기본값/));
    });
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
  });
});
