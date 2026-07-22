/* 추적성 매트릭스 결과의 재진입/새로고침 생존 영속.
 *
 * SrsSdsSection의 matrix는 컴포넌트-로컬 useState/useRef라, Detail.jsx/App.jsx의 keep-alive가
 * 평범한 탭 전환은 보존하지만 (a) 프로젝트/Job 전환 왕복(섹션 key=jobUrl remount)과
 * (b) 페이지 새로고침에서는 소멸해 매번 재생성(문서 추출 다수 + 매트릭스 조립)을 강요했다.
 * impactStore.js(변경영향평가 결과 영속)와 같은 계열로, 마지막 매트릭스를 유지해 두 경우 모두
 * 복원한다.
 *
 * ⚠ 복원은 오직 **정확 키 일치**로만 한다(cacheKey = 요구/설계/시험 문서 경로 + jobUrl +
 * sourceRoot 전체). 과거엔 마운트 복원용으로 설계문서만 담은 느슨한 binding을 따로 뒀는데,
 * 그건 cacheKey의 진부분집합이라 **시험문서(STS/SUTS/…)만 바뀌어도 옛 매트릭스를 복원**해
 * stale 통과-실패를 current로 표시했다(deep-review Critical, ISO 26262 안전 오보고). 정확 키
 * 일치는 입력이 하나라도 바뀌면 miss→재생성으로 이어져 "재실행 필요할 때만 재생성"을 지킨다.
 *
 * 2층 구조:
 *  - 모듈 레벨 Map(_mem): 같은 세션 프로젝트 왕복을 즉시 복원(크기 무제한·직렬화 불필요). 주 캐시.
 *  - localStorage 미러(현재 1건): 새로고침 생존. 매트릭스는 단일 blob이라 impactStore식 부분
 *    drop이 불가 → 크기 초과 시 localStorage skip(모듈캐시만, 재생성 가능하므로 안전 degrade).
 */
const TRACE_KEY = 'devops_v2_trace_matrix_current';
// 저장 payload 스키마 버전. 없거나 다르면 폐기(구 스키마가 렌더를 크래시시키는 것 방지 —
// impactStore.js:14-16과 동일 사유).
export const TRACE_STORE_VERSION = 2;
// localStorage 직렬화 상한(~2MB). 초과 시 localStorage 저장을 건너뛰고 모듈캐시만 유지한다.
// 매트릭스가 수천 행이면 quota(≈5MB)를 압박하므로 방어. 새로고침 생존만 포기, 세션 내 왕복은 유지.
const MAX_LS_BYTES = 2_000_000;
// 모듈캐시 상한 — 프로젝트 여러 개 왕복 대비, 무한성장 방지(삽입순서 LRU).
const MEM_CAP = 8;

const _mem = new Map();  // cacheKey -> { data, savedAt }

/** 렌더 가능한 매트릭스 형태인가 — 깨진 저장분이 화면을 죽이지 않게 load 시점에 거른다.
 *  SrsSdsSection 렌더(1465-1466)의 `inner = data.matrix ?? data; rows = inner.rows ?? inner.items`
 *  접근과 정확히 일치시킨다. */
function isRenderableMatrix(data) {
  if (!data || typeof data !== 'object') return false;
  const inner = data.matrix ?? data;
  return Boolean(inner) && typeof inner === 'object'
    && (Array.isArray(inner.rows) || Array.isArray(inner.items));
}

function _readLS() {
  try {
    const raw = JSON.parse(localStorage.getItem(TRACE_KEY) || 'null');
    if (!raw || typeof raw !== 'object') return null;
    if (raw.v !== TRACE_STORE_VERSION) return null;       // 구/미상 스키마 폐기
    if (!isRenderableMatrix(raw.data)) return null;        // 깨진 저장분 폐기
    return raw;  // { v, key, data, savedAt }
  } catch {
    return null;
  }
}

/** 매트릭스 결과를 저장한다(모듈캐시 + localStorage 미러).
 *  @param cacheKey loadMatrix의 full cacheKey(입력 전체) — 정확 재생성/복원 판정용.
 *  @returns {boolean} 모듈캐시에 저장됐는지(localStorage 실패와 무관하게 세션 내 복원 가능 여부). */
export function saveTraceMatrix(cacheKey, data) {
  if (!cacheKey || !isRenderableMatrix(data)) return false;
  const savedAt = Date.now();
  // 모듈캐시(삽입순서 LRU: 재삽입으로 최신화, cap 초과 시 가장 오래된 것 제거).
  _mem.delete(cacheKey);
  _mem.set(cacheKey, { data, savedAt });
  while (_mem.size > MEM_CAP) {
    _mem.delete(_mem.keys().next().value);
  }
  // localStorage 미러(크기 가드).
  try {
    const payload = JSON.stringify({ v: TRACE_STORE_VERSION, key: cacheKey, data, savedAt });
    if (payload.length <= MAX_LS_BYTES) {
      localStorage.setItem(TRACE_KEY, payload);
    } else {
      // 오버사이즈: localStorage 저장 불가(모듈캐시만 = 안전 degrade). 단 기존 미러가 '다른'
      // 키(타 프로젝트)면 지우지 않는다 — 오버사이즈 저장이 무관한 프로젝트의 새로고침 복원까지
      // 파괴하지 않도록(deep-review Warning). 자기 자신의 옛 미러(같은 키)만 정리한다.
      const existing = _readLS();
      if (!existing || existing.key === cacheKey) {
        try { localStorage.removeItem(TRACE_KEY); } catch { /* best-effort */ }
      }
    }
  } catch {
    /* setItem 실패(quota 등): 기존 미러를 능동 삭제하지 않는다 — 실패한 저장이 타 프로젝트의
       미러를 지우면 안 된다. setItem은 실패 시 기존 값을 보존하므로 그대로 둔다. */
  }
  return true;
}

/** full cacheKey 완전일치 조회 — loadMatrix 캐시-히트 + 마운트 복원 공용(입력 전체 동일할 때만).
 *  localStorage에서만 살아있던 경우(새로고침 후) 모듈캐시에도 채워 다음 조회를 가속한다. */
export function loadTraceMatrixByKey(cacheKey) {
  if (!cacheKey) return null;
  const m = _mem.get(cacheKey);
  if (m) return { data: m.data, savedAt: m.savedAt };
  const ls = _readLS();
  if (ls && ls.key === cacheKey) {
    _mem.set(cacheKey, { data: ls.data, savedAt: ls.savedAt });
    return { data: ls.data, savedAt: ls.savedAt };
  }
  return null;
}

export function clearTraceMatrix() {
  _mem.clear();
  try { localStorage.removeItem(TRACE_KEY); } catch { /* best-effort */ }
}
