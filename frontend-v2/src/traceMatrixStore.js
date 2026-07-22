/* 추적성 매트릭스 결과의 재진입/새로고침 생존 영속.
 *
 * SrsSdsSection의 matrix는 컴포넌트-로컬 useState/useRef라, Detail.jsx/App.jsx의 keep-alive가
 * 평범한 탭 전환은 보존하지만 (a) 프로젝트/Job 전환 왕복(섹션 key=jobUrl remount)과
 * (b) 페이지 새로고침에서는 소멸해 매번 재생성(문서 추출 다수 + 매트릭스 조립)을 강요했다.
 * impactStore.js(변경영향평가 결과 영속)와 같은 계열로, 마지막 매트릭스를 유지해 두 경우 모두
 * 복원한다.
 *
 * 2층 구조:
 *  - 모듈 레벨 Map(_mem): 같은 세션 프로젝트 왕복을 즉시 복원(크기 무제한·직렬화 불필요). 주 캐시.
 *  - localStorage 미러(현재 1건): 새로고침 생존. 매트릭스는 단일 blob이라 impactStore식 부분
 *    drop이 불가 → 크기 초과 시 localStorage skip(모듈캐시만, 재생성 가능하므로 안전 degrade).
 */
const TRACE_KEY = 'devops_v2_trace_matrix_current';
// 저장 payload 스키마 버전. 없거나 다르면 폐기(구 스키마가 렌더를 크래시시키는 것 방지 —
// impactStore.js:14-16과 동일 사유).
export const TRACE_STORE_VERSION = 1;
// localStorage 직렬화 상한(~2MB). 초과 시 localStorage 저장을 건너뛰고 모듈캐시만 유지한다.
// 매트릭스가 수천 행이면 quota(≈5MB)를 압박하므로 방어. 새로고침 생존만 포기, 세션 내 왕복은 유지.
const MAX_LS_BYTES = 2_000_000;
// 모듈캐시 상한 — 프로젝트 여러 개 왕복 대비, 무한성장 방지(삽입순서 LRU).
const MEM_CAP = 8;

const _mem = new Map();  // cacheKey -> { data, binding, savedAt }

/** 렌더 가능한 매트릭스 형태인가 — 깨진 저장분이 화면을 죽이지 않게 load 시점에 거른다.
 *  SrsSdsSection 렌더(1429-1430)의 `inner = data.matrix ?? data; rows = inner.rows ?? inner.items`
 *  접근과 정확히 일치시킨다. */
function isRenderableMatrix(data) {
  if (!data || typeof data !== 'object') return false;
  const inner = data.matrix ?? data;
  return Boolean(inner) && typeof inner === 'object'
    && (Array.isArray(inner.rows) || Array.isArray(inner.items));
}

/** 프로젝트 결속 키 — 마운트 하이드레이트(hydrateTraceMatrix)의 대조 근거.
 *  binding = 마운트 시점 확보 가능한 부분키. sourceRoot 포함(구 소스트리 stale 복원 차단). */
function bindingKey(b) {
  if (!b || typeof b !== 'object') return '';
  const parts = [b.srs, b.sds, b.hsis, b.jobUrl, b.sourceRoot].map((x) => String(x || ''));
  return parts.some(Boolean) ? parts.join('|') : '';
}

function _readLS() {
  try {
    const raw = JSON.parse(localStorage.getItem(TRACE_KEY) || 'null');
    if (!raw || typeof raw !== 'object') return null;
    if (raw.v !== TRACE_STORE_VERSION) return null;       // 구/미상 스키마 폐기
    if (!isRenderableMatrix(raw.data)) return null;        // 깨진 저장분 폐기
    return raw;  // { v, key, binding, data, savedAt }
  } catch {
    return null;
  }
}

/** 매트릭스 결과를 저장한다(모듈캐시 + localStorage 미러).
 *  @param cacheKey loadMatrix의 full cacheKey(입력 전체) — exact 재생성 판정용.
 *  @param binding  마운트 확보 가능한 부분키 {srs,sds,hsis,jobUrl,sourceRoot} — 하이드레이트용.
 *  @returns {boolean} 모듈캐시에 저장됐는지(localStorage 실패와 무관하게 세션 내 복원 가능 여부). */
export function saveTraceMatrix(cacheKey, binding, data) {
  if (!cacheKey || !isRenderableMatrix(data)) return false;
  const savedAt = Date.now();
  // 모듈캐시(삽입순서 LRU: 재삽입으로 최신화, cap 초과 시 가장 오래된 것 제거).
  _mem.delete(cacheKey);
  _mem.set(cacheKey, { data, binding: binding || null, savedAt });
  while (_mem.size > MEM_CAP) {
    _mem.delete(_mem.keys().next().value);
  }
  // localStorage 미러(크기 가드). 초과·실패 시 구 엔트리를 제거해 stale 오인 방지.
  try {
    const payload = JSON.stringify({ v: TRACE_STORE_VERSION, key: cacheKey, binding: binding || null, data, savedAt });
    if (payload.length <= MAX_LS_BYTES) {
      localStorage.setItem(TRACE_KEY, payload);
    } else {
      localStorage.removeItem(TRACE_KEY);
    }
  } catch {
    try { localStorage.removeItem(TRACE_KEY); } catch { /* best-effort */ }
  }
  return true;
}

/** full cacheKey 완전일치 조회 — loadMatrix 캐시-히트 판정(입력 전체 동일할 때만).
 *  localStorage에서만 살아있던 경우(새로고침 후) 모듈캐시에도 채워 다음 조회를 가속한다. */
export function loadTraceMatrixByKey(cacheKey) {
  if (!cacheKey) return null;
  const m = _mem.get(cacheKey);
  if (m) return { data: m.data, savedAt: m.savedAt };
  const ls = _readLS();
  if (ls && ls.key === cacheKey) {
    _mem.set(cacheKey, { data: ls.data, binding: ls.binding, savedAt: ls.savedAt });
    return { data: ls.data, savedAt: ls.savedAt };
  }
  return null;
}

/** 마운트 하이드레이트 — binding(프로젝트 결속)만 일치하면 즉시 복원(exact key 불필요).
 *  remount(프로젝트 왕복·새로고침) 직후 마지막 매트릭스를 표시하는 용도. 여러 후보 중 최신(savedAt)
 *  을 고른다. exact 재생성 판정은 loadMatrix의 loadTraceMatrixByKey가 담당하므로, 여기서 다소
 *  느슨히 복원해도 "재실행 필요 시 재생성"은 그대로 성립한다. */
export function hydrateTraceMatrix(binding) {
  const bk = bindingKey(binding);
  if (!bk) return null;
  let best = null;
  // _mem은 삽입순서(오래된→최신) — 동률 savedAt(같은 ms 저장)일 땐 나중 삽입(최신)이 이기도록
  // `>=`. Date.now()가 단조증가라 삽입순서=저장순서라서 마지막 매칭이 항상 최신.
  for (const v of _mem.values()) {
    if (bindingKey(v.binding) === bk && (!best || v.savedAt >= best.savedAt)) best = v;
  }
  const ls = _readLS();
  if (ls && bindingKey(ls.binding) === bk && (!best || ls.savedAt > best.savedAt)) {
    _mem.set(ls.key, { data: ls.data, binding: ls.binding, savedAt: ls.savedAt });
    best = { data: ls.data, savedAt: ls.savedAt };
  }
  return best ? { data: best.data, savedAt: best.savedAt } : null;
}

export function clearTraceMatrix() {
  _mem.clear();
  try { localStorage.removeItem(TRACE_KEY); } catch { /* best-effort */ }
}
