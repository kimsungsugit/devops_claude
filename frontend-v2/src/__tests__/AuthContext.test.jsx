/**
 * 45차 C1 — AuthContext 회귀.
 *
 * 시나리오:
 *   1. mount 시 토큰 없으면 authenticated=false
 *   2. mount 시 유효 토큰 → /me 호출 → authenticated=true
 *   3. login 성공 → 토큰 저장 + state 갱신
 *   4. login 실패 → 401 + error message
 *   5. logout → 토큰 제거 + state 초기화
 *   6. mustChangePassword=true → state 반영
 *   7. /me 401 응답 → refresh 시도 → 실패 시 logout
 */
import { render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../api.js', async () => {
  const tokens = { access: '', refresh: '' };
  let username = '';
  return {
    getAccessToken: () => tokens.access,
    getRefreshToken: () => tokens.refresh,
    setTokens: ({ access, refresh }) => {
      if (access !== undefined) tokens.access = access || '';
      if (refresh !== undefined) tokens.refresh = refresh || '';
    },
    clearTokens: () => {
      tokens.access = '';
      tokens.refresh = '';
    },
    getUsername: () => username,
    setUsername: (n) => { username = n || ''; },
    __resetForTest: () => {
      tokens.access = '';
      tokens.refresh = '';
      username = '';
    },
  };
});

const apiMock = await import('../api.js');
const { AuthProvider, useAuth } = await import('../contexts/AuthContext.jsx');


function TestConsumer() {
  const { authenticated, loading, username, mustChangePassword, login, logout, changePassword } = useAuth();
  return (
    <div>
      <span data-testid="auth">{String(authenticated)}</span>
      <span data-testid="loading">{String(loading)}</span>
      <span data-testid="user">{username || 'null'}</span>
      <span data-testid="mustChange">{String(mustChangePassword)}</span>
      <button data-testid="login-btn" onClick={() => login('alice', 'pw12345678')}>login</button>
      <button data-testid="logout-btn" onClick={() => logout()}>logout</button>
      <button data-testid="changepw-btn" onClick={() => changePassword('newpw1234')}>change</button>
    </div>
  );
}


describe('AuthContext', () => {
  beforeEach(() => {
    apiMock.__resetForTest();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('mount with no token → authenticated=false', async () => {
    render(<AuthProvider><TestConsumer /></AuthProvider>);
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    expect(screen.getByTestId('auth').textContent).toBe('false');
  });

  it('mount with valid token → /me → authenticated=true', async () => {
    apiMock.setTokens({ access: 'fake.access.token', refresh: 'fake.refresh.token' });
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        authenticated: true,
        username: 'alice',
        is_admin: true,
        must_change_password: false,
      }),
    });
    await act(async () => {
      render(<AuthProvider><TestConsumer /></AuthProvider>);
    });
    await waitFor(() => expect(screen.getByTestId('auth').textContent).toBe('true'));
    expect(screen.getByTestId('user').textContent).toBe('alice');
  });

  it('login success → tokens saved + state updated', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        access_token: 'new.access.token',
        refresh_token: 'new.refresh.token',
        username: 'alice',
        is_admin: true,
        must_change_password: false,
      }),
    });
    await act(async () => {
      render(<AuthProvider><TestConsumer /></AuthProvider>);
    });
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    await act(async () => {
      screen.getByTestId('login-btn').click();
    });
    await waitFor(() => expect(screen.getByTestId('auth').textContent).toBe('true'));
    expect(apiMock.getAccessToken()).toBe('new.access.token');
    expect(apiMock.getRefreshToken()).toBe('new.refresh.token');
  });

  it('login failure → error message + tokens not saved', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({
        ok: false,
        error: { code: 'INVALID_CREDENTIALS', message: '비밀번호 불일치' },
      }),
    });
    await act(async () => {
      render(<AuthProvider><TestConsumer /></AuthProvider>);
    });
    await waitFor(() => expect(screen.getByTestId('loading').textContent).toBe('false'));
    await act(async () => {
      screen.getByTestId('login-btn').click();
    });
    // auth false 유지
    expect(screen.getByTestId('auth').textContent).toBe('false');
    expect(apiMock.getAccessToken()).toBe('');
  });

  it('logout → tokens cleared + state reset', async () => {
    apiMock.setTokens({ access: 'old.token', refresh: 'old.refresh' });
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        authenticated: true,
        username: 'alice',
        is_admin: false,
        must_change_password: false,
      }),
    });
    await act(async () => {
      render(<AuthProvider><TestConsumer /></AuthProvider>);
    });
    await waitFor(() => expect(screen.getByTestId('auth').textContent).toBe('true'));
    await act(async () => {
      screen.getByTestId('logout-btn').click();
    });
    expect(screen.getByTestId('auth').textContent).toBe('false');
    expect(apiMock.getAccessToken()).toBe('');
  });

  it('must_change_password=true reflected in state', async () => {
    apiMock.setTokens({ access: 'fake.token' });
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        authenticated: true,
        username: 'alice',
        is_admin: false,
        must_change_password: true,
      }),
    });
    await act(async () => {
      render(<AuthProvider><TestConsumer /></AuthProvider>);
    });
    await waitFor(() => expect(screen.getByTestId('auth').textContent).toBe('true'));
    expect(screen.getByTestId('mustChange').textContent).toBe('true');
  });

  it('changePassword response updates tokens (48차 C6)', async () => {
    apiMock.setTokens({ access: 'old-access', refresh: 'old-refresh' });
    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      if (String(url).includes('/api/auth/me')) {
        return {
          ok: true,
          json: async () => ({
            authenticated: true,
            username: 'alice',
            is_admin: false,
            must_change_password: true,
          }),
        };
      }
      if (String(url).includes('/api/auth/change-password')) {
        return {
          ok: true,
          json: async () => ({
            changed: true,
            username: 'alice',
            access_token: 'new-access',
            refresh_token: 'new-refresh',
            token_type: 'bearer',
          }),
        };
      }
      return { ok: false, status: 404, json: async () => ({}) };
    });

    await act(async () => {
      render(<AuthProvider><TestConsumer /></AuthProvider>);
    });
    await waitFor(() => expect(screen.getByTestId('mustChange').textContent).toBe('true'));

    await act(async () => {
      screen.getByTestId('changepw-btn').click();
    });
    // 48차 C6: 응답 token 자동 갱신
    expect(apiMock.getAccessToken()).toBe('new-access');
    expect(apiMock.getRefreshToken()).toBe('new-refresh');
    await waitFor(() => expect(screen.getByTestId('mustChange').textContent).toBe('false'));
  });

  it('401 on /me with no refresh → logout', async () => {
    apiMock.setTokens({ access: 'expired.token' });  // no refresh
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ ok: false, error: { code: 'TOKEN_EXPIRED' } }),
    });
    await act(async () => {
      render(<AuthProvider><TestConsumer /></AuthProvider>);
    });
    await waitFor(() => expect(screen.getByTestId('auth').textContent).toBe('false'));
    expect(apiMock.getAccessToken()).toBe('');
  });
});
