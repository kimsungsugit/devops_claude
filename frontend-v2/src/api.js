/** User identification (not auth — internal network) */
const USER_KEY = 'devops_v2_user';
export function getUsername() { return localStorage.getItem(USER_KEY) || ''; }
export function setUsername(name) { localStorage.setItem(USER_KEY, (name || '').trim()); }

/**
 * 45차 C1 — JWT 토큰 저장 (사용자 결정: localStorage).
 * Access token: 60분 만료. Refresh token: 7일 만료. logout 시 모두 삭제.
 * XSS 노출 위험은 internal network 환경 + CSP로 차단. 외부 노출 시 httpOnly cookie 검토.
 */
const ACCESS_TOKEN_KEY = 'devops_v2_access_token';
const REFRESH_TOKEN_KEY = 'devops_v2_refresh_token';

export function getAccessToken() { return localStorage.getItem(ACCESS_TOKEN_KEY) || ''; }
export function getRefreshToken() { return localStorage.getItem(REFRESH_TOKEN_KEY) || ''; }
export function setTokens({ access, refresh }) {
  if (access) localStorage.setItem(ACCESS_TOKEN_KEY, access);
  if (refresh) localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
}
export function clearTokens() {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

/** 45차 C1 — auth 헤더 빌더. Authorization Bearer 우선 + X-User fallback (DEV 모드 backend). */
function _authHeaders() {
  const headers = {};
  const access = getAccessToken();
  if (access) headers.Authorization = `Bearer ${access}`;
  const user = getUsername();
  if (user) headers['X-User'] = user;
  return headers;
}

/** 50차 — raw fetch가 필요한 component (binary blob 응답)에서도 동일 auth 헤더 사용. */
export function authHeaders() {
  return _authHeaders();
}

/**
 * 47차 I5 — 자동 token refresh queue (single-flight).
 *
 * 동작:
 *   1. fetch 응답이 401 + (TOKEN_EXPIRED|TOKEN_INVALID) → refreshAccess() 호출
 *   2. 동시 다발 401 → 같은 _refreshingPromise 대기 (single-flight)
 *   3. refresh 성공 → 원 요청 재시도 1회
 *   4. refresh 실패 또는 refresh 없음 → clearTokens + 'auth-logout' event dispatch
 *
 * 미적용:
 *   - TOKEN_REVOKED (W35) — server-side revoke, refresh도 거부됨 → logout
 *   - USER_REVOKED — 사용자 삭제 → logout
 *   - AUTH_REQUIRED — 토큰 자체 없음 → logout
 */
let _refreshingPromise = null;

async function _refreshAccessToken() {
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
}

async function _refreshAccessTokenSingleFlight() {
  if (_refreshingPromise) return _refreshingPromise;
  _refreshingPromise = _refreshAccessToken().finally(() => {
    _refreshingPromise = null;
  });
  return _refreshingPromise;
}

/** 401 응답이 refresh 가능한 경우 (TOKEN_EXPIRED / TOKEN_INVALID) 여부. */
function _isRefreshableError(status, code) {
  if (status !== 401) return false;
  return code === 'TOKEN_EXPIRED' || code === 'TOKEN_INVALID' || code === 'AUTH_HEADER_MALFORMED';
}

function _dispatchLogout() {
  clearTokens();
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event('auth-logout'));
  }
}

/**
 * API base URL resolution (priority):
 * 1. window.__ARIA_API_BASE__ (runtime injected, e.g. by config.js)
 * 2. VITE_API_BASE_URL build-time env
 * 3. Empty string (relative path — same-origin proxy)
 */
const API_BASE = (typeof window !== 'undefined' && window.__ARIA_API_BASE__) || import.meta.env?.VITE_API_BASE_URL || '';

export function buildUrl(path) {
  if (!API_BASE) return path;
  if (path.startsWith('http://') || path.startsWith('https://')) return path;
  return API_BASE.replace(/\/$/, '') + path;
}

/** 응답을 파싱해 throw할 Error 생성 (code/message 정규화). */
async function _toError(res) {
  const text = await res.text();
  let msg = text || `HTTP ${res.status}`;
  let code = `HTTP_${res.status}`;
  try {
    const j = JSON.parse(text);
    if (j?.error?.message) {
      msg = j.error.message;
      code = j.error.code || code;
    } else if (typeof j.detail === 'string') {
      msg = j.detail;
    } else if (j?.detail && typeof j.detail === 'object') {
      // 방어선. 이 앱의 자체 HTTPException 은 `http_exception_handler`
      // (`backend/error_handler.py:84`)가 dict `detail` 을 `error.{code,message}` 로
      // 바꿔 주므로 **위 첫 분기**가 잡는다. 여기까지 오는 건 그 핸들러를 안 타는
      // 경로(starlette 기본 처리 등)뿐이고, 그때 원시 JSON 이 뜨는 걸 막는다.
      if (typeof j.detail.message === 'string') msg = j.detail.message;
      if (typeof j.detail.code === 'string') code = j.detail.code;
    } else if (typeof j.message === 'string') {
      msg = j.message;
    } else if (j?.error?.code) {
      code = j.error.code;
    }
  } catch (_) {}
  const err = new Error(msg);
  err.status = res.status;
  err.code = code;
  return err;
}

/** Generic JSON fetch helper.
 *
 * 45차 C1: Authorization Bearer + X-User 헤더 자동 부착.
 * 47차 I5: 401 + (TOKEN_EXPIRED|TOKEN_INVALID) 시 refresh + 재시도 1회. TOKEN_REVOKED /
 * USER_REVOKED는 즉시 logout event dispatch.
 */
export async function api(path, options = {}, _retried = false) {
  const res = await fetch(buildUrl(path), {
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json', ..._authHeaders(), ...(options.headers || {}) },
    ...options,
  });
  if (res.ok) return res.json();

  const err = await _toError(res);

  // 47차 I5: 401 refresh-able + 아직 재시도 안 함 → single-flight refresh + 1회 재시도
  if (_isRefreshableError(err.status, err.code) && !_retried) {
    const ok = await _refreshAccessTokenSingleFlight();
    if (ok) {
      return api(path, options, true);  // 재시도 1회 (recursion 차단)
    }
    // refresh 실패 — logout 신호
    _dispatchLogout();
  } else if (err.status === 401 && (err.code === 'TOKEN_REVOKED' || err.code === 'USER_REVOKED')) {
    // server-side revocation — refresh 시도 무의미
    _dispatchLogout();
  }

  throw err;
}

/** POST with JSON body */
export function post(path, body) {
  return api(path, { method: 'POST', body: JSON.stringify(body) });
}

/**
 * POST SSE streaming — calls onEvent(type, data) for each server-sent event.
 * Resolves when the stream ends.
 */
export async function postSse(path, body, opts = {}) {
  return _postSseInternal(path, body, opts, false);
}

async function _postSseInternal(path, body, { onEvent, signal } = {}, _retried = false) {
  const res = await fetch(buildUrl(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ..._authHeaders() },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    // 48차 C7: postSse도 single-flight refresh + 재시도 1회 적용 (api()와 동일).
    const err = await _toError(res);
    if (_isRefreshableError(err.status, err.code) && !_retried) {
      const ok = await _refreshAccessTokenSingleFlight();
      if (ok) return _postSseInternal(path, body, { onEvent, signal }, true);
      _dispatchLogout();
    } else if (err.status === 401 && (err.code === 'TOKEN_REVOKED' || err.code === 'USER_REVOKED')) {
      _dispatchLogout();
    }
    throw err;
  }
  if (!res.body) throw new Error('스트리밍 응답을 받을 수 없습니다.');

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  const emit = (raw) => {
    if (!onEvent) return;
    const lines = String(raw || '').split('\n');
    let evType = 'message';
    let evData = '';
    for (const line of lines) {
      if (line.startsWith('event:')) evType = line.slice(6).trim();
      else if (line.startsWith('data:')) evData = line.slice(5).trim();
    }
    if (!evData) return;
    let parsed = evData;
    try { parsed = JSON.parse(evData); } catch (_) {}
    onEvent(evType, parsed);
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop() ?? '';
    for (const part of parts) emit(part);
  }
  if (buffer.trim()) emit(buffer);
}

/** Theme helpers */
export const getInitialTheme = () =>
  (typeof window !== 'undefined' && localStorage.getItem('devops_v2_theme')) || 'light';

export const saveTheme = (t) => localStorage.setItem('devops_v2_theme', t);

/** Jenkins config — 토큰 포함 전부 localStorage 영속 (재시작·탭 닫기 후에도 유지).
 *  과거에는 토큰만 sessionStorage(탭 닫으면 소멸)였으나 사용자 요구로 영속화.
 *  보안 트레이드오프: Jenkins API 토큰이 localStorage에 남으므로 공용 PC에서는
 *  사용 후 설정 초기화 권장. (서버 영속 `/api/config/jenkins`는 admin 전용 별도 경로) */
const JENKINS_KEY = 'devops_v2_jenkins';
const JENKINS_TOKEN_KEY = 'devops_v2_jenkins_token';

export function loadJenkinsConfig() {
  try {
    const raw = localStorage.getItem(JENKINS_KEY);
    const cfg = raw ? JSON.parse(raw) : {};
    let token = localStorage.getItem(JENKINS_TOKEN_KEY);
    if (!token) {
      // 과거 sessionStorage 저장분 1회 migrate → localStorage 영속
      const legacy = sessionStorage.getItem(JENKINS_TOKEN_KEY);
      if (legacy) {
        localStorage.setItem(JENKINS_TOKEN_KEY, legacy);
        try { sessionStorage.removeItem(JENKINS_TOKEN_KEY); } catch (_) { /* noop */ }
        token = legacy;
      }
    }
    cfg.token = token || cfg.token || '';
    return cfg;
  } catch (_) { return {}; }
}

export function saveJenkinsConfig(cfg) {
  // 토큰을 localStorage에 영속 (재시작 후에도 유지). 빈 토큰이면 키 제거.
  if (cfg.token) {
    localStorage.setItem(JENKINS_TOKEN_KEY, cfg.token);
  } else {
    localStorage.removeItem(JENKINS_TOKEN_KEY);
  }
  // 과거 sessionStorage 키 정리 (잔존분 제거)
  try { sessionStorage.removeItem(JENKINS_TOKEN_KEY); } catch (_) { /* noop */ }
  // localStorage(JENKINS_KEY)에는 토큰 제외하고 저장
  const { token, ...rest } = cfg;
  localStorage.setItem(JENKINS_KEY, JSON.stringify(rest));
}

/**
 * Server-managed Jenkins config (shared across all users).
 * Admin writes via UI → saved to config/jenkins_server_config.json on the server.
 * All users fetch on startup — prevents individual users from editing.
 */
export async function fetchServerJenkinsConfig() {
  try {
    const data = await api('/api/config/jenkins');
    return data || null;
  } catch (_) {
    return null;
  }
}

export async function saveServerJenkinsConfig(cfg) {
  return post('/api/config/jenkins', {
    baseUrl: cfg.baseUrl || '',
    username: cfg.username || '',
    token: cfg.token || '',
    cacheRoot: cfg.cacheRoot || '.devops_pro_cache',
    buildSelector: cfg.buildSelector || 'lastSuccessfulBuild',
    verifyTls: cfg.verifyTls !== false,
  });
}

/**
 * Server-managed UDS docx template (admin only).
 * GET returns {template_path, effective_path, exists, default_path, last_saved_at}.
 * POST persists a path override. Empty path clears the override (→ env default).
 */
export async function fetchServerUdsTemplate() {
  try { return await api('/api/config/uds-template'); } catch (_) { return null; }
}

export async function saveServerUdsTemplate(templatePath) {
  return post('/api/config/uds-template', { template_path: templatePath || '' });
}

/** Upload a .docx template file and set it as the active server template. */
export async function uploadServerUdsTemplate(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(buildUrl('/api/config/uds-template/upload'), {
    method: 'POST',
    headers: _authHeaders(),
    body: form,
  });
  if (!res.ok) {
    const text = await res.text();
    let msg = text || `HTTP ${res.status}`;
    try { const j = JSON.parse(text); if (j?.detail) msg = j.detail; } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
}

/** Cache root helper — per-user isolation only.
 * Backend appends its own jenkins/{job_slug}/build_N path — so we avoid
 * duplicating the job slug here (which used to push Windows paths over MAX_PATH=260).
 */
export function defaultCacheRoot(jobUrl) {
  if (!jobUrl) return '';
  const user = getUsername() || 'default';
  const safeUser = user.replace(/[^\w-]/g, '_');
  return `.devops_pro_cache/${safeUser}`;
}

/** Build status → pill tone */
export function buildTone(result) {
  if (!result) return 'neutral';
  const r = String(result).toUpperCase();
  if (r === 'SUCCESS') return 'success';
  if (r === 'FAILURE' || r === 'FAILED') return 'danger';
  if (r === 'UNSTABLE') return 'warning';
  if (r === 'ABORTED') return 'neutral';
  if (r.includes('PROGRESS') || r.includes('RUN')) return 'running';
  return 'info';
}

/** Job color (Jenkins) → tone */
export function colorTone(color) {
  if (!color) return 'neutral';
  if (color.includes('blue')) return 'success';
  if (color.includes('red')) return 'danger';
  if (color.includes('yellow')) return 'warning';
  if (color.includes('anime') || color.includes('building')) return 'running';
  return 'neutral';
}

/** Human-readable file size */
export function fmtBytes(bytes) {
  if (!bytes) return '';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
