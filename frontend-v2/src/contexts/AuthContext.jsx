/**
 * 45차 C1 — JWT 인증 Context.
 *
 * 로그인 상태 + access/refresh token 관리. localStorage 저장 (사용자 결정).
 * 만료 시 refresh 자동 시도 → 실패 시 logout + Login 화면 redirect.
 *
 * AdminContext와 분리: Auth는 "로그인 했는가?" + "토큰 발급/갱신",
 * Admin은 "관리자인가?" + admin 모드 토글. AdminContext가 Auth 토큰을 사용해 /me 호출.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { clearTokens, getAccessToken, getRefreshToken, setTokens, setUsername } from '../api.js';

const API_BASE = (typeof window !== 'undefined' && window.__ARIA_API_BASE__)
  || import.meta.env?.VITE_API_BASE_URL || '';

function buildUrl(path) {
  if (!API_BASE) return path;
  return API_BASE.replace(/\/$/, '') + path;
}

const AuthCtx = createContext({
  authenticated: false,
  loading: true,
  username: null,
  mustChangePassword: false,
  login: async () => ({ ok: false }),
  logout: () => {},
  changePassword: async () => ({ ok: false }),
});

export function AuthProvider({ children }) {
  const [state, setState] = useState({
    authenticated: false,
    loading: true,
    username: null,
    mustChangePassword: false,
  });
  // 43차 W20: StrictMode safe
  const isMountedRef = useRef(true);

  /** 토큰이 있으면 /api/auth/me 호출하여 사용자 상태 확인. */
  const validateSession = useCallback(async () => {
    const access = getAccessToken();
    if (!access) {
      if (isMountedRef.current) {
        setState({ authenticated: false, loading: false, username: null, mustChangePassword: false });
      }
      return;
    }
    try {
      const res = await fetch(buildUrl('/api/auth/me'), {
        cache: 'no-store',
        headers: { Authorization: `Bearer ${access}` },
      });
      if (!isMountedRef.current) return;
      if (!res.ok) {
        // 토큰 만료/무효 — refresh 시도
        const refreshed = await _attemptRefresh();
        if (!refreshed) {
          clearTokens();
          setState({ authenticated: false, loading: false, username: null, mustChangePassword: false });
          return;
        }
        // refresh 성공 후 재확인
        return validateSession();
      }
      const data = await res.json();
      if (!isMountedRef.current) return;
      setState({
        authenticated: !!data.authenticated,
        loading: false,
        username: data.username || null,
        mustChangePassword: !!data.must_change_password,
      });
    } catch (e) {
      if (!isMountedRef.current) return;
      clearTokens();
      setState({ authenticated: false, loading: false, username: null, mustChangePassword: false });
    }
  }, []);

  /** refresh token으로 새 access token 발급 시도. */
  const _attemptRefresh = async () => {
    const refresh = getRefreshToken();
    if (!refresh) return false;
    try {
      const res = await fetch(buildUrl('/api/auth/refresh'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!res.ok) return false;
      const data = await res.json();
      setTokens({ access: data.access_token });
      return true;
    } catch (_) {
      return false;
    }
  };

  /** 사용자명/PW로 로그인 → 토큰 저장 + state 갱신. */
  const login = useCallback(async (username, password) => {
    try {
      const res = await fetch(buildUrl('/api/auth/login'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        const msg = data?.error?.message || data?.detail || '로그인 실패';
        return { ok: false, error: msg, code: data?.error?.code };
      }
      setTokens({ access: data.access_token, refresh: data.refresh_token });
      setUsername(data.username);  // X-User 헤더용 (legacy + display)
      if (isMountedRef.current) {
        setState({
          authenticated: true,
          loading: false,
          username: data.username,
          mustChangePassword: !!data.must_change_password,
        });
      }
      return { ok: true, mustChangePassword: !!data.must_change_password };
    } catch (e) {
      return { ok: false, error: e.message || '네트워크 오류' };
    }
  }, []);

  /** 로그아웃 — 토큰 제거 + state 초기화. */
  const logout = useCallback(() => {
    clearTokens();
    if (isMountedRef.current) {
      setState({ authenticated: false, loading: false, username: null, mustChangePassword: false });
    }
    // 다른 컨텍스트 (AdminContext)에 알림
    window.dispatchEvent(new Event('admin-mode-changed'));
  }, []);

  /** PW 변경 (must_change_password 후 또는 사용자 자발). */
  const changePassword = useCallback(async (newPassword) => {
    const access = getAccessToken();
    if (!access) return { ok: false, error: '인증 필요' };
    try {
      const res = await fetch(buildUrl('/api/auth/change-password'), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${access}`,
        },
        body: JSON.stringify({ new_password: newPassword }),
      });
      const data = await res.json();
      if (!res.ok) {
        return { ok: false, error: data?.error?.message || 'PW 변경 실패' };
      }
      if (isMountedRef.current) {
        setState((s) => ({ ...s, mustChangePassword: false }));
      }
      return { ok: true };
    } catch (e) {
      return { ok: false, error: e.message || '네트워크 오류' };
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    validateSession();
    // 47차 I5: api.js의 refresh 실패 시 'auth-logout' event → AuthContext logout
    const onAuthLogout = () => {
      if (!isMountedRef.current) return;
      setState({ authenticated: false, loading: false, username: null, mustChangePassword: false });
    };
    window.addEventListener('auth-logout', onAuthLogout);
    return () => {
      isMountedRef.current = false;
      window.removeEventListener('auth-logout', onAuthLogout);
    };
  }, [validateSession]);

  return (
    <AuthCtx.Provider value={{ ...state, login, logout, changePassword, refresh: validateSession }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth() {
  return useContext(AuthCtx);
}
