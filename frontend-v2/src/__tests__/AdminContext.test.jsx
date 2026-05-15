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
