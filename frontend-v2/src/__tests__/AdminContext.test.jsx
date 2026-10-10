/**
 * 40차 — AdminContext / AdminProvider 회귀.
 *
 * 4 시나리오:
 *   1. mount 시 GET /api/auth/me 호출 → is_admin 응답 반영
 *   2. fetch 실패 → graceful (isAdmin=false, loading=false)
 *   3. custom event 'admin-mode-changed' 발화 시 refresh 재호출 (same-tab C3 fix)
 *   4. non-admin 응답 → isAdmin=false
 */
import { render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../api.js', () => ({
  getUsername: () => 'tester',
  // 45차 C1 은 getAccessToken 을 직접 읽었으나, 2026-08-06 부터 auth 헤더는
  // `authHeaders()` 단일 출처다(raw fetch 12곳이 Bearer 를 빠뜨려 401 이 났던 결함).
  authHeaders: () => ({ 'X-User': 'tester' }),
}));

const { AdminProvider, useAdminMode } = await import('../contexts/AdminContext.jsx');


function TestConsumer() {
  const { isAdmin, username, loading } = useAdminMode();
  return (
    <div>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="isAdmin">{String(isAdmin)}</span>
      <span data-testid="username">{username || 'null'}</span>
    </div>
  );
}


describe('AdminContext', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('fetches /api/auth/me on mount and reflects is_admin=true', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ username: 'tester', is_admin: true, authenticated: true }),
    });

    render(
      <AdminProvider>
        <TestConsumer />
      </AdminProvider>
    );

    await waitFor(() => expect(screen.getByTestId('isAdmin').textContent).toBe('true'));
    expect(screen.getByTestId('username').textContent).toBe('tester');
    expect(screen.getByTestId('loading').textContent).toBe('false');
    const url = fetchSpy.mock.calls[0][0];
    expect(url).toContain('/api/auth/me');
  });

  it('non-admin response sets isAdmin=false', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({ username: 'guest', is_admin: false, authenticated: true }),
    });

    render(
      <AdminProvider>
        <TestConsumer />
      </AdminProvider>
    );

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('isAdmin').textContent).toBe('false');
  });

  it('fetch failure → graceful fallback (isAdmin=false, loading=false)', async () => {
    vi.spyOn(global, 'fetch').mockRejectedValue(new Error('Network down'));

    render(
      <AdminProvider>
        <TestConsumer />
      </AdminProvider>
    );

    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('isAdmin').textContent).toBe('false');
  });

  it('visibilitychange (visible) triggers refresh (41차 W4)', async () => {
    let callCount = 0;
    const responses = [
      { username: 'guest', is_admin: false, authenticated: true },
      { username: 'guest', is_admin: true, authenticated: true },  // admin 추가 후 재방문
    ];
    vi.spyOn(global, 'fetch').mockImplementation(async () => ({
      ok: true,
      json: async () => responses[callCount++] || responses[1],
    }));

    render(
      <AdminProvider>
        <TestConsumer />
      </AdminProvider>
    );
    await waitFor(() => expect(screen.getByTestId('isAdmin').textContent).toBe('false'));

    // 탭 visible 이벤트 발화 — refresh 재호출 → 2번째 응답 반영
    await act(async () => {
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        configurable: true,
      });
      document.dispatchEvent(new Event('visibilitychange'));
    });

    await waitFor(() => expect(screen.getByTestId('isAdmin').textContent).toBe('true'));
  });

  it('W5 debounce: refresh() within 5s without force is skipped (42차)', async () => {
    let callCount = 0;
    vi.spyOn(global, 'fetch').mockImplementation(async () => {
      callCount++;
      return {
        ok: true,
        json: async () => ({ username: 'tester', is_admin: false, authenticated: true }),
      };
    });
    let providerRefresh;
    function Spy() {
      const ctx = useAdminMode();
      providerRefresh = ctx.refresh;
      return null;
    }
    render(
      <AdminProvider>
        <Spy />
      </AdminProvider>
    );
    await waitFor(() => expect(callCount).toBeGreaterThan(0));
    const before = callCount;
    // force=false manual refresh — 5초 내 skip
    await act(async () => {
      await providerRefresh({ force: false });
      await providerRefresh();  // default force=false
    });
    expect(callCount).toBe(before);  // debounce 적용 — fetch 횟수 그대로
  });

  it('W4 retry: fetch failure schedules 30s retry (42차)', async () => {
    // 44차 W25: render + 첫 fetch resolve를 act 안에서 처리 — act warning 차단
    vi.useFakeTimers();
    let callCount = 0;
    vi.spyOn(global, 'fetch').mockImplementation(async () => {
      callCount++;
      if (callCount === 1) throw new Error('Network down');
      return {
        ok: true,
        json: async () => ({ username: 'tester', is_admin: true, authenticated: true }),
      };
    });

    await act(async () => {
      render(
        <AdminProvider>
          <TestConsumer />
        </AdminProvider>
      );
    });
    await act(async () => {
      await vi.waitFor(() => expect(callCount).toBeGreaterThan(0));
    });
    // 첫 fetch 실패 — 30초 retry timer 예약
    expect(callCount).toBe(1);

    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });
    vi.useRealTimers();
    await waitFor(() => expect(callCount).toBeGreaterThanOrEqual(2));
  });

  it('W20 unmount during retry timer skips setState (StrictMode safe, 43차)', async () => {
    // unmount 후 retry timer fire 시 setState 호출 안 되는지 검증.
    // 이전 (42차): timer fire → refresh() → setState → "Can't perform state update on unmounted" warning.
    // 43차 W20 fix: isMountedRef로 setState skip.
    // 44차 W25: render + fetch resolve를 act 안에서 처리 — act warning 차단.
    vi.useFakeTimers();
    let callCount = 0;
    let postUnmountSetState = false;
    vi.spyOn(global, 'fetch').mockImplementation(async () => {
      callCount++;
      throw new Error('Network down');  // 항상 실패 → retry 예약
    });
    // React state update 추적 — unmount 후 setState 호출이 발생하면 콘솔 에러 잡음
    const origError = console.error;
    console.error = (msg) => {
      if (typeof msg === 'string' && msg.includes('unmounted')) {
        postUnmountSetState = true;
      }
      origError(msg);
    };

    let unmount;
    await act(async () => {
      const result = render(
        <AdminProvider>
          <TestConsumer />
        </AdminProvider>
      );
      unmount = result.unmount;
    });
    await act(async () => {
      await vi.waitFor(() => expect(callCount).toBeGreaterThan(0));
    });
    // unmount — retry timer 살아있음
    unmount();
    // 30초 후 timer fire 시뮬레이션
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });
    vi.useRealTimers();
    console.error = origError;
    // unmount 후 setState 호출 0건 (isMountedRef=false로 skip)
    expect(postUnmountSetState).toBe(false);
  });

  it('custom event "admin-mode-changed" triggers refresh (same-tab C3 fix)', async () => {
    let callCount = 0;
    const responses = [
      { username: 'tester', is_admin: false, authenticated: true },
      { username: 'tester', is_admin: true, authenticated: true },
    ];
    vi.spyOn(global, 'fetch').mockImplementation(async () => ({
      ok: true,
      json: async () => responses[callCount++] || responses[1],
    }));

    render(
      <AdminProvider>
        <TestConsumer />
      </AdminProvider>
    );

    await waitFor(() => expect(screen.getByTestId('isAdmin').textContent).toBe('false'));

    // custom event 발화 → refresh → 2번째 응답 (is_admin=true)
    await act(async () => {
      window.dispatchEvent(new Event('admin-mode-changed'));
    });

    await waitFor(() => expect(screen.getByTestId('isAdmin').textContent).toBe('true'));
  });
});
