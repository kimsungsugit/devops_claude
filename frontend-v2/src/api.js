/** User identification (not auth — internal network) */
const USER_KEY = 'devops_v2_user';
export function getUsername() { return localStorage.getItem(USER_KEY) || ''; }
export function setUsername(name) { localStorage.setItem(USER_KEY, (name || '').trim()); }

/**
 * API base URL resolution (priority):
 * 1. window.__ARIA_API_BASE__ (runtime injected, e.g. by config.js)
 * 2. VITE_API_BASE_URL build-time env
 * 3. Empty string (relative path — same-origin proxy)
 */
const API_BASE = (typeof window !== 'undefined' && window.__ARIA_API_BASE__) || import.meta.env?.VITE_API_BASE_URL || '';

function buildUrl(path) {
  if (!API_BASE) return path;
  if (path.startsWith('http://') || path.startsWith('https://')) return path;
  return API_BASE.replace(/\/$/, '') + path;
}

/** Generic JSON fetch helper */
export async function api(path, options = {}) {
  const user = getUsername();
  const res = await fetch(buildUrl(path), {
    cache: 'no-store',   // bypass browser HTTP cache — API responses must be fresh
    headers: { 'Content-Type': 'application/json', ...(user ? { 'X-User': user } : {}) },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    let msg = text || `HTTP ${res.status}`;
    try {
      const j = JSON.parse(text);
      if (j && typeof j.detail === 'string') msg = j.detail;
      else if (j && typeof j.message === 'string') msg = j.message;
    } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
}

/** POST with JSON body */
export function post(path, body) {
  return api(path, { method: 'POST', body: JSON.stringify(body) });
}

/**
 * POST SSE streaming — calls onEvent(type, data) for each server-sent event.
 * Resolves when the stream ends.
 */
export async function postSse(path, body, { onEvent, signal } = {}) {
  const user = getUsername();
  const res = await fetch(buildUrl(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream', ...(user ? { 'X-User': user } : {}) },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
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

/** Jenkins config — 토큰은 sessionStorage (탭 닫으면 삭제), 나머지는 localStorage */
const JENKINS_KEY = 'devops_v2_jenkins';
const JENKINS_TOKEN_KEY = 'devops_v2_jenkins_token';

export function loadJenkinsConfig() {
  try {
    const raw = localStorage.getItem(JENKINS_KEY);
    const cfg = raw ? JSON.parse(raw) : {};
    // 토큰은 sessionStorage에서 로드
    cfg.token = sessionStorage.getItem(JENKINS_TOKEN_KEY) || cfg.token || '';
    return cfg;
  } catch (_) { return {}; }
}

export function saveJenkinsConfig(cfg) {
  // 토큰은 sessionStorage에만 저장 (탭 닫으면 소멸)
  if (cfg.token) {
    sessionStorage.setItem(JENKINS_TOKEN_KEY, cfg.token);
  }
  // localStorage에는 토큰 제외하고 저장
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
  const user = getUsername();
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(buildUrl('/api/config/uds-template/upload'), {
    method: 'POST',
    headers: user ? { 'X-User': user } : {},
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
