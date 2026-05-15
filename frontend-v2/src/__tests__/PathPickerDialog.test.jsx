/**
 * PathPickerDialog 단위 테스트 (21차 라운드).
 *
 * 검증:
 * - open=false 시 렌더 안 함
 * - open=true 시 GET /api/swut/browse 호출 + dirs/files 표시
 * - 파일 클릭 시 onSelect 콜백 + onClose 호출
 * - 디렉토리 클릭 시 navigate (재호출)
 * - error 응답 시 에러 메시지 표시
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../api.js', () => ({
  getUsername: () => 'tester',
}));

// 40차: AdminContext mock — 회귀 기본 admin (Browse 활성)
vi.mock('../contexts/AdminContext.jsx', () => ({
  useAdminMode: () => ({ isAdmin: true, username: 'tester', authenticated: true, loading: false }),
  AdminProvider: ({ children }) => children,
}));

const { default: PathPickerDialog } = await import('../components/PathPickerDialog.jsx');

describe('PathPickerDialog', () => {
  beforeEach(() => {
    // 39-fix-2: 일부 버튼 (register/worker browse)이 admin 전용 — 기본 admin ON
    localStorage.setItem('devops_admin_mode', 'true');
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers(),
      json: async () => ({
        ok: true,
        current: 'C:/test',
        parent: 'C:/',
        dirs: ['C:/test/subdir1', 'C:/test/subdir2'],
        files: ['C:/test/a.xlsx', 'C:/test/b.xlsx'],
        truncated: false,
      }),
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('does not render when open=false', () => {
    render(<PathPickerDialog open={false} onClose={() => {}} />);
    expect(screen.queryByText(/경로 선택/)).toBeNull();
  });

  it('renders title + items + parent button when open', async () => {
    render(
      <PathPickerDialog open={true} initialPath="C:/test" pattern="*.xlsx"
        title="Coverage 선택" onClose={() => {}} />
    );
    await waitFor(() => {
      expect(screen.getByText(/subdir1/)).toBeTruthy();
    });
    expect(screen.getByText(/Coverage 선택/)).toBeTruthy();
    expect(screen.getByText(/a\.xlsx/)).toBeTruthy();
    expect(screen.getByText(/상위 디렉토리/)).toBeTruthy();
  });

  it('calls onSelect with full path when file clicked', async () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(
      <PathPickerDialog open={true} initialPath="C:/test"
        onSelect={onSelect} onClose={onClose} />
    );
    await waitFor(() => {
      expect(screen.getByText(/a\.xlsx/)).toBeTruthy();
    });
    fireEvent.click(screen.getByText(/a\.xlsx/));
    expect(onSelect).toHaveBeenCalledWith('C:/test/a.xlsx');
    expect(onClose).toHaveBeenCalled();
  });

  it('navigates into directory on dir click', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch');
    render(
      <PathPickerDialog open={true} initialPath="C:/test" onClose={() => {}} />
    );
    await waitFor(() => {
      expect(screen.getByText(/subdir1/)).toBeTruthy();
    });
    const initialCallCount = fetchSpy.mock.calls.length;
    fireEvent.click(screen.getByText(/subdir1/));
    await waitFor(() => {
      expect(fetchSpy.mock.calls.length).toBeGreaterThan(initialCallCount);
    });
    // 두 번째 호출의 body에 새 path 포함
    const secondCallBody = JSON.parse(fetchSpy.mock.calls[initialCallCount][1].body);
    expect(secondCallBody.path).toBe('C:/test/subdir1');
  });

  it('sends X-User header in browse fetch (raw fetch safety)', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch');
    render(<PathPickerDialog open={true} initialPath="C:/test" onClose={() => {}} />);
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalled();
    });
    const opts = fetchSpy.mock.calls[0][1];
    expect(opts.headers['X-User']).toBe('tester');
    expect(opts.method).toBe('POST');
  });

  it('displays error when backend returns 422 / 404', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 404,
      headers: new Headers(),
      json: async () => ({ error: { message: '경로 접근 실패: FileNotFoundError' } }),
    });
    render(<PathPickerDialog open={true} initialPath="C:/nope" onClose={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText(/FileNotFoundError/)).toBeTruthy();
    });
  });

  it('displays cloudium_hint when backend returns it (22차 T190)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers(),
      json: async () => ({
        ok: true,
        current: 'U:/cloud',
        parent: 'U:/',
        dirs: [],
        files: ['U:/cloud/a.xlsx'],
        truncated: false,
        file_mode: 'cloudium',
        cloudium_hint: 'Cloudium 모드 — backend python이 디렉토리 navigate 권한 없음.',
      }),
    });
    render(<PathPickerDialog open={true} initialPath="U:/cloud" onClose={() => {}} />);
    await waitFor(() => {
      // 39차 prominent 경고 + 22차 inline hint 둘 다 표시 — getAllByText
      expect(screen.getAllByText(/Cloudium 모드/).length).toBeGreaterThanOrEqual(1);
    });
    expect(screen.getByText(/디렉토리 navigate 권한 없음/)).toBeTruthy();
  });

  it('has full 6-attribute autocomplete disabling on path input (22차 T189)', () => {
    render(<PathPickerDialog open={true} initialPath="C:/" onClose={() => {}} />);
    const input = document.querySelector('.picker-path');
    expect(input).toBeTruthy();
    expect(input.getAttribute('autocomplete')).toBe('off');
    expect(input.getAttribute('autocorrect')).toBe('off');
    expect(input.getAttribute('autocapitalize')).toBe('off');
    expect(input.getAttribute('spellcheck')).toBe('false');
    expect(input.getAttribute('data-form-type')).toBe('other');
    expect(input.getAttribute('data-lpignore')).toBe('true');
  });

  it('displays truncated warning when backend reports >2000 items', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers(),
      json: async () => ({
        ok: true,
        current: 'C:/huge',
        parent: 'C:/',
        dirs: [],
        files: Array.from({ length: 1500 }, (_, i) => `C:/huge/f${i}.bin`),
        truncated: true,
      }),
    });
    render(<PathPickerDialog open={true} initialPath="C:/huge" onClose={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText(/2000건 초과/)).toBeTruthy();
    });
  });

  // 39차: cloudium UX 강화 + bookmark + 403 자동 add
  it('renders prominent cloudium 경고 카드 when file_mode=cloudium (39차)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      headers: new Headers(),
      json: async () => ({
        ok: true,
        current: 'U:/cloud',
        parent: 'U:/',
        dirs: [],
        files: [],
        truncated: false,
        file_mode: 'cloudium',
        cloudium_hint: '',
      }),
    });
    render(<PathPickerDialog open={true} initialPath="U:/cloud" onClose={() => {}} />);
    await waitFor(() => {
      expect(screen.getByTestId('picker-cloudium-warning')).toBeTruthy();
    });
    expect(screen.getByText(/디렉토리 navigate를 지원하지 않습니다/)).toBeTruthy();
  });

  it('shows 403 auto-add prompt when backend returns CLOUDIUM_BLOCKED (39차)', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 403,
      headers: new Headers(),
      json: async () => ({
        ok: false,
        error: {
          code: 'CLOUDIUM_BLOCKED',
          message: 'Cloudium 모드: 허용되지 않은 경로 접근 차단됨: U:/forbidden',
        },
      }),
    });
    render(<PathPickerDialog open={true} initialPath="U:/forbidden" onClose={() => {}} />);
    await waitFor(() => {
      expect(screen.getByTestId('picker-add-prompt')).toBeTruthy();
    });
    expect(screen.getByText(/추가 후 재시도/)).toBeTruthy();
  });

  it('calls add-allowed-prefix endpoint when user confirms 403 prompt (39차)', async () => {
    let callCount = 0;
    vi.spyOn(global, 'fetch').mockImplementation(async (url, opts) => {
      callCount++;
      // 첫 호출: browse 403, 두번째: add-prefix 200, 세번째: browse 200
      if (callCount === 1) {
        return {
          ok: false, status: 403,
          headers: new Headers(),
          json: async () => ({
            ok: false,
            error: { code: 'CLOUDIUM_BLOCKED', message: 'Cloudium 차단' },
          }),
        };
      }
      if (url.includes('/api/file-mode/add-allowed-prefix')) {
        return {
          ok: true, status: 200,
          headers: new Headers(),
          json: async () => ({
            ok: true, added: true, prefix: 'U:/forbidden',
            extra_prefixes: ['U:/forbidden'],
          }),
        };
      }
      // 재시도 browse
      return {
        ok: true, status: 200,
        headers: new Headers(),
        json: async () => ({
          ok: true,
          current: 'U:/forbidden',
          parent: 'U:/',
          dirs: [],
          files: ['U:/forbidden/file.xlsx'],
          truncated: false,
          file_mode: 'cloudium',
        }),
      };
    });

    render(<PathPickerDialog open={true} initialPath="U:/forbidden" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('picker-add-prompt')).toBeTruthy());

    fireEvent.click(screen.getByText(/추가 후 재시도/));

    await waitFor(() => {
      // add-allowed-prefix 호출됐는지
      const urls = vi.mocked(global.fetch).mock.calls.map(c => c[0]);
      expect(urls.some(u => u.includes('/api/file-mode/add-allowed-prefix'))).toBe(true);
    });
  });

  it('register button calls add-allowed-prefix with current path (39차 후속 — admin pre-register)', async () => {
    let callCount = 0;
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      callCount++;
      if (callCount === 1) {
        // 첫 browse — cloudium 모드 응답
        return {
          ok: true, status: 200,
          headers: new Headers(),
          json: async () => ({
            ok: true, current: 'U:/admin/pre', parent: 'U:/',
            dirs: [], files: [], truncated: false,
            file_mode: 'cloudium', cloudium_hint: '',
          }),
        };
      }
      if (url.includes('/api/file-mode/add-allowed-prefix')) {
        return {
          ok: true, status: 200,
          headers: new Headers(),
          json: async () => ({
            ok: true, added: true, prefix: 'U:/admin/pre',
            extra_prefixes: ['U:/admin/pre'],
          }),
        };
      }
      return {
        ok: true, status: 200,
        headers: new Headers(),
        json: async () => ({
          ok: true, current: 'U:/admin/pre', parent: 'U:/',
          dirs: [], files: ['U:/admin/pre/x.xlsx'], truncated: false,
          file_mode: 'cloudium',
        }),
      };
    });

    render(<PathPickerDialog open={true} initialPath="U:/admin/pre" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByTestId('picker-register-prefix')).toBeTruthy());

    fireEvent.click(screen.getByTestId('picker-register-prefix'));

    await waitFor(() => {
      const urls = fetchSpy.mock.calls.map(c => c[0]);
      expect(urls.some(u => u.includes('/api/file-mode/add-allowed-prefix'))).toBe(true);
    });
  });

  it('saves bookmark on file select and shows bookmark dropdown (39차)', async () => {
    // 사전: localStorage clear + bookmark 1건 미리 저장
    localStorage.clear();
    localStorage.setItem(
      'devops_v2_cloudium_path_bookmarks',
      JSON.stringify(['U:/preset1', 'U:/preset2']),
    );
    render(<PathPickerDialog open={true} initialPath="C:/test" onClose={() => {}} />);
    await waitFor(() => {
      expect(screen.getByTestId('picker-bookmarks-toggle')).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId('picker-bookmarks-toggle'));
    await waitFor(() => {
      expect(screen.getByTestId('picker-bookmarks-panel')).toBeTruthy();
    });
    expect(screen.getByText(/U:\/preset1/)).toBeTruthy();
    expect(screen.getByText(/U:\/preset2/)).toBeTruthy();
  });
});
