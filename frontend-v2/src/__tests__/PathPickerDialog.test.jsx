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

const { default: PathPickerDialog } = await import('../components/PathPickerDialog.jsx');

describe('PathPickerDialog', () => {
  beforeEach(() => {
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
});
