/** User identification (not auth — internal network) */
const USER_KEY = 'devops_v2_user';
export function getUsername() { return localStorage.getItem(USER_KEY) || ''; }
export function setUsername(name) { localStorage.setItem(USER_KEY, (name || '').trim()); }

/** Generic JSON fetch helper */
export async function api(path, options = {}) {
  const user = getUsername();
  const res = await fetch(path, {
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
  const res = await fetch(path, {
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

/** Cache root helper — derived from job_url slug */
export function defaultCacheRoot(jobUrl) {
  if (!jobUrl) return '';
  const slug = jobUrl.replace(/https?:\/\//, '').replace(/[^\w-]/g, '_').slice(0, 60);
  return `.devops_pro_cache/${slug}`;
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
