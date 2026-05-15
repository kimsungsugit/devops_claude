/**
 * 40차 — Admin role Context.
 *
 * backend GET /api/auth/me 호출 + is_admin 응답 기반 — localStorage 신뢰 제거.
 * Same-tab admin 토글은 custom event 'admin-mode-changed' 발화 → refresh().
 *
 * C1 fix (localStorage 우회 차단): 진짜 권한은 backend `config/admin_users.json`.
 * C3 fix (same-tab 미반영): storage event + 동일 탭 custom event 둘 다 listen.
 */
import { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { getUsername } from '../api.js';

const API_BASE = (typeof window !== 'undefined' && window.__ARIA_API_BASE__)
  || import.meta.env?.VITE_API_BASE_URL || '';

function buildUrl(path) {
  if (!API_BASE) return path;
  return API_BASE.replace(/\/$/, '') + path;
}

const AdminCtx = createContext({
  isAdmin: false,
  username: null,
  authenticated: false,
  loading: true,
  refresh: () => {},
});

export function AdminProvider({ children }) {
  const [state, setState] = useState({
    isAdmin: false,
    username: null,
    authenticated: false,
    loading: true,
  });

  const refresh = useCallback(async () => {
    const user = getUsername();
    try {
      const res = await fetch(buildUrl('/api/auth/me'), {
        cache: 'no-store',
        headers: user ? { 'X-User': user } : {},
      });
      if (!res.ok) {
        // 401 또는 fetch failure — graceful fallback (isAdmin=false)
        setState({
          isAdmin: false,
          username: user || null,
          authenticated: false,
          loading: false,
        });
        return;
      }
      const data = await res.json();
      setState({
        isAdmin: !!data.is_admin,
        username: data.username || null,
        authenticated: !!data.authenticated,
        loading: false,
      });
    } catch (e) {
      // 네트워크 오류 — graceful (non-admin 가정)
      setState({
        isAdmin: false,
        username: user || null,
        authenticated: false,
        loading: false,
      });
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    // C3 fix: same-tab + 다른 탭 모두 reactive
    const onChange = () => refresh();
    window.addEventListener('admin-mode-changed', onChange);
    window.addEventListener('storage', onChange);
    // 41차 W4: 탭 visible 시 refresh — backend down 후 회복 / 다른 클라이언트의 admin 변경 자동 반영
    const onVisibility = () => {
      if (document.visibilityState === 'visible') refresh();
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('admin-mode-changed', onChange);
      window.removeEventListener('storage', onChange);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [refresh]);

  return (
    <AdminCtx.Provider value={{ ...state, refresh }}>
      {children}
    </AdminCtx.Provider>
  );
}

export function useAdminMode() {
  return useContext(AdminCtx);
}
