/**
 * 47차 I5 — api.js 자동 token refresh queue 회귀.
 *
 * 시나리오:
 *   1. 401 TOKEN_EXPIRED → refresh → 재시도 성공
 *   2. 401 TOKEN_REVOKED → refresh 시도 없이 즉시 logout event
 *   3. 401 USER_REVOKED → 즉시 logout event
 *   4. refresh 실패 → logout event
 *   5. 동시 다발 401 → single-flight (refresh 1회만 호출)
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

async function setupApi() {
  // module 캐시 초기화 — _refreshingPromise 등 모듈 state 격리
  vi.resetModules();
  return await import('../api.js');
}

describe('api refresh queue (I5)', () => {
  it('401 TOKEN_EXPIRED → refresh → retry success', async () => {
    const apiMod = await setupApi();
    apiMod.setTokens({ access: 'expired', refresh: 'valid-refresh' });

    let call = 0;
    vi.spyOn(global, 'fetch').mockImplementation(async (url, opts) => {
      call++;
      if (String(url).includes('/api/auth/refresh')) {
        return {
          ok: true,
          json: async () => ({ access_token: 'new-access', token_type: 'bearer' }),
          text: async () => '',
        };
      }
      // 첫 fetch: 401 TOKEN_EXPIRED. 재시도: 200.
      const authHeader = opts?.headers?.Authorization || '';
      if (authHeader.includes('expired')) {
        return {
          ok: false,
          status: 401,
          json: async () => ({ ok: false, error: { code: 'TOKEN_EXPIRED' } }),
          text: async () => JSON.stringify({ ok: false, error: { code: 'TOKEN_EXPIRED' } }),
        };
      }
      return {
        ok: true,
        json: async () => ({ data: 'success' }),
        text: async () => JSON.stringify({ data: 'success' }),
      };
    });

    const result = await apiMod.api('/api/test');
    expect(result).toEqual({ data: 'success' });
    expect(apiMod.getAccessToken()).toBe('new-access');
    expect(call).toBeGreaterThanOrEqual(3);  // 첫 호출 + refresh + 재시도
  });

  it('401 TOKEN_REVOKED → immediate logout (no refresh attempt)', async () => {
    const apiMod = await setupApi();
    apiMod.setTokens({ access: 'revoked', refresh: 'any-refresh' });

    const logoutSpy = vi.fn();
    window.addEventListener('auth-logout', logoutSpy);

    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ ok: false, error: { code: 'TOKEN_REVOKED' } }),
      text: async () => JSON.stringify({ ok: false, error: { code: 'TOKEN_REVOKED' } }),
    });

    await expect(apiMod.api('/api/test')).rejects.toThrow();
    expect(logoutSpy).toHaveBeenCalledTimes(1);
    expect(apiMod.getAccessToken()).toBe('');
    window.removeEventListener('auth-logout', logoutSpy);
  });

  it('401 USER_REVOKED → immediate logout', async () => {
    const apiMod = await setupApi();
    apiMod.setTokens({ access: 'any', refresh: 'any' });

    const logoutSpy = vi.fn();
    window.addEventListener('auth-logout', logoutSpy);

    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ ok: false, error: { code: 'USER_REVOKED' } }),
      text: async () => JSON.stringify({ ok: false, error: { code: 'USER_REVOKED' } }),
    });

    await expect(apiMod.api('/api/test')).rejects.toThrow();
    expect(logoutSpy).toHaveBeenCalledTimes(1);
    window.removeEventListener('auth-logout', logoutSpy);
  });

  it('refresh failure → logout', async () => {
    const apiMod = await setupApi();
    apiMod.setTokens({ access: 'expired', refresh: 'invalid-refresh' });

    const logoutSpy = vi.fn();
    window.addEventListener('auth-logout', logoutSpy);

    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      if (String(url).includes('/api/auth/refresh')) {
        return {
          ok: false,
          status: 401,
          json: async () => ({ ok: false, error: { code: 'TOKEN_INVALID' } }),
          text: async () => '',
        };
      }
      return {
        ok: false,
        status: 401,
        json: async () => ({ ok: false, error: { code: 'TOKEN_EXPIRED' } }),
        text: async () => JSON.stringify({ ok: false, error: { code: 'TOKEN_EXPIRED' } }),
      };
    });

    await expect(apiMod.api('/api/test')).rejects.toThrow();
    expect(logoutSpy).toHaveBeenCalledTimes(1);
    expect(apiMod.getAccessToken()).toBe('');
    window.removeEventListener('auth-logout', logoutSpy);
  });

  it('concurrent 401 → single-flight refresh (1 refresh call only)', async () => {
    const apiMod = await setupApi();
    apiMod.setTokens({ access: 'expired', refresh: 'valid-refresh' });

    let refreshCalls = 0;
    let dataCalls = 0;
    vi.spyOn(global, 'fetch').mockImplementation(async (url, opts) => {
      if (String(url).includes('/api/auth/refresh')) {
        refreshCalls++;
        // refresh 느리게 → 다른 호출들이 같은 promise 대기 보장
        await new Promise((r) => setTimeout(r, 50));
        return {
          ok: true,
          json: async () => ({ access_token: 'new-access' }),
          text: async () => '',
        };
      }
      dataCalls++;
      const auth = opts?.headers?.Authorization || '';
      if (auth.includes('expired')) {
        return {
          ok: false,
          status: 401,
          json: async () => ({ ok: false, error: { code: 'TOKEN_EXPIRED' } }),
          text: async () => JSON.stringify({ ok: false, error: { code: 'TOKEN_EXPIRED' } }),
        };
      }
      return {
        ok: true,
        json: async () => ({ ok: true }),
        text: async () => '',
      };
    });

    // 3개 호출 병렬 — 모두 첫 fetch에서 401 → refresh single-flight
    const results = await Promise.all([
      apiMod.api('/api/x1'),
      apiMod.api('/api/x2'),
      apiMod.api('/api/x3'),
    ]);
    expect(results).toHaveLength(3);
    expect(refreshCalls).toBe(1);  // single-flight 검증
  });
});
