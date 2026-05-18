/**
 * 40차 — Admin role Context.
 *
 * backend GET /api/auth/me 호출 + is_admin 응답 기반 — localStorage 신뢰 제거.
 * Same-tab admin 토글은 custom event 'admin-mode-changed' 발화 → refresh().
 *
 * C1 fix (localStorage 우회 차단): 진짜 권한은 backend `config/admin_users.json`.
 * C3 fix (same-tab 미반영): storage event + 동일 탭 custom event 둘 다 listen.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { getAccessToken, getUsername } from '../api.js';

// 42차 W5: refresh debounce — 같은 탭에서 visibility/storage event 빠르게 연쇄 시 fetch 1회만
const REFRESH_DEBOUNCE_MS = 5000;

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
  // 42차 W4/W5: retry timer + debounce 추적
  const lastFetchAt = useRef(0);
  const retryTimerRef = useRef(null);
  // 43차 W20: StrictMode 대응 — 첫 mount의 fetch가 두 번째 mount 후 setState 호출하면 race.
  // isMounted=false 시 setState/timer schedule skip하여 메모리 누수 + warning 차단.
  const isMountedRef = useRef(true);

  const refresh = useCallback(async (opts = {}) => {
    const force = !!opts.force;
    // W5 debounce: 5초 이내 fetch했으면 skip (force=true면 강제 호출)
    const now = Date.now();
    if (!force && now - lastFetchAt.current < REFRESH_DEBOUNCE_MS) {
      return;
    }
    lastFetchAt.current = now;

    const user = getUsername();
    // 45차 C1: JWT Authorization 우선 부착, X-User는 backward-compat (DEV 모드 backend).
    const access = getAccessToken();
    const headers = {};
    if (access) headers.Authorization = `Bearer ${access}`;
    if (user) headers['X-User'] = user;
    try {
      const res = await fetch(buildUrl('/api/auth/me'), {
        cache: 'no-store',
        headers,
      });
      // 43차 W20: fetch 동안 unmount 시 무시
      if (!isMountedRef.current) return;
      if (!res.ok) {
        setState({
          isAdmin: false,
          username: user || null,
          authenticated: false,
          loading: false,
        });
        // W4 retry: 401/5xx 후 30초 뒤 1회 재시도
        if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
        retryTimerRef.current = setTimeout(() => {
          // 43차 W20: timer fire 시점 unmount 상태면 skip
          if (isMountedRef.current) refresh({ force: true });
        }, 30_000);
        return;
      }
      const data = await res.json();
      if (!isMountedRef.current) return;
      setState({
        isAdmin: !!data.is_admin,
        username: data.username || null,
        authenticated: !!data.authenticated,
        loading: false,
      });
      // 성공 — 보류 중인 retry 취소
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    } catch (e) {
      // 네트워크 오류 — graceful + W4 retry 예약
      if (!isMountedRef.current) return;
      setState({
        isAdmin: false,
        username: user || null,
        authenticated: false,
        loading: false,
      });
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
      retryTimerRef.current = setTimeout(() => {
        if (isMountedRef.current) refresh({ force: true });
      }, 30_000);
    }
  }, []);

  useEffect(() => {
    // 43차 W20: 매 mount마다 isMounted reset (StrictMode 두 번째 mount 시 첫 unmount가
    // false로 설정한 후 두 번째 mount가 다시 true로 복원).
    isMountedRef.current = true;
    refresh({ force: true });
    // unmount 시 retry timer cleanup + isMounted 플래그 off (42차 W4 + 43차 W20)
    return () => {
      isMountedRef.current = false;
      if (retryTimerRef.current) {
        clearTimeout(retryTimerRef.current);
        retryTimerRef.current = null;
      }
    };
  }, [refresh]);

  useEffect(() => {
    // C3 fix: same-tab + 다른 탭 모두 reactive — 의도적 이벤트는 force (debounce 우회)
    const onChange = () => refresh({ force: true });
    window.addEventListener('admin-mode-changed', onChange);
    window.addEventListener('storage', onChange);
    // 41차 W4: 탭 visible 시 refresh — backend down 후 회복 / 다른 클라이언트의 admin 변경 자동 반영
    // 42차 W5: visibility는 사용자 명시적 행위로 분류 — force=true. debounce는 외부 manual
    // refresh({force: false}) 호출에서 5초 내 중복 차단 (refresh 자체 호출만 보호).
    const onVisibility = () => {
      if (document.visibilityState === 'visible') refresh({ force: true });
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
