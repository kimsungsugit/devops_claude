/* 추적성 매트릭스 결과의 재진입/새로고침 생존 영속.
 *
 * SrsSdsSection의 matrix는 컴포넌트-로컬 useState/useRef라, Detail.jsx/App.jsx의 keep-alive가
 * 평범한 탭 전환은 보존하지만 (a) 프로젝트/Job 전환 왕복(섹션 key=jobUrl remount)과
 * (b) 페이지 새로고침에서는 소멸해 매번 재생성(문서 추출 다수 + 매트릭스 조립)을 강요했다.
 * impactStore.js(변경영향평가 결과 영속)와 같은 계열로, 마지막 매트릭스를 유지해 두 경우 모두
 * 복원한다.
 *
 * 복원은 **2단**이다(사용자 요구 "들어오면 마지막 결과가 보이게" + ISO 26262 stale 금지를 동시에):
 *  1) **정확 키 일치**(cacheKey = 요구/설계/시험 문서 경로 + jobUrl + sourceRoot 전체) →
 *     입력이 완전히 같으므로 **current**로 간주, "💾 저장된 결과" 배지(clean).
 *  2) 정확 키 miss + **binding 일치**(같은 프로젝트 = jobUrl + sourceRoot + 설계문서) → 마지막
 *     매트릭스를 **보여주되 ⚠ stale 로 명시**(입력이 바뀌었을 수 있음·새로고침으로 재생성).
 *
 * ⚠ 과거 초판(751984c)은 binding 일치를 **clean**으로 복원해(배지는 저장 시각만) 시험문서가
 * 바뀌어도 옛 통과-실패를 current로 위장했다(deep-review Critical, ISO 26262 안전 오보고). 그
 * 대응으로 정확 키만 복원하게 바꿨더니(d8ce4d1) 입력이 조금만 드리프트해도(빌드 이동·문서 경로
 * 변경) **아무것도 안 보여** 사용자가 매번 생성 버튼을 눌러야 했다. 지금은 둘을 분리한다: binding
 * 복원은 유지하되 **stale을 숨기지 않고 크게 폭로**한다 — disclosed-stale은 안전하다(Critical의
 * 본질은 '단서 없는' 위장이었다). 정확 키 일치만 clean 이므로 stale-as-current 는 여전히 불가능.
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

const _mem = new Map();  // cacheKey -> { data, savedAt, bindingKey }

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
 *  @param cacheKey loadMatrix의 full cacheKey(입력 전체) — 정확(clean) 복원 판정용.
 *  @param bindingKey 프로젝트 식별 부분키(jobUrl+sourceRoot+설계문서) 문자열 — stale 복원 판정용.
 *    정확 키가 miss여도 같은 프로젝트면 마지막 결과를 stale로 보여주기 위한 결속. 없으면 ''.
 *  @returns {boolean} 모듈캐시에 저장됐는지(localStorage 실패와 무관하게 세션 내 복원 가능 여부). */
export function saveTraceMatrix(cacheKey, bindingKey, data) {
  if (!cacheKey || !isRenderableMatrix(data)) return false;
  const savedAt = Date.now();
  const bk = bindingKey || '';
  // 모듈캐시(삽입순서 LRU: 재삽입으로 최신화, cap 초과 시 가장 오래된 것 제거).
  _mem.delete(cacheKey);
  _mem.set(cacheKey, { data, savedAt, bindingKey: bk });
  while (_mem.size > MEM_CAP) {
    _mem.delete(_mem.keys().next().value);
  }
  // localStorage 미러(크기 가드).
  try {
    const payload = JSON.stringify({ v: TRACE_STORE_VERSION, key: cacheKey, bindingKey: bk, data, savedAt });
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

/** full cacheKey 완전일치 조회 — loadMatrix 캐시-히트 + 마운트 clean 복원 공용(입력 전체 동일).
 *  localStorage에서만 살아있던 경우(새로고침 후) 모듈캐시에도 채워 다음 조회를 가속한다. */
export function loadTraceMatrixByKey(cacheKey) {
  if (!cacheKey) return null;
  const m = _mem.get(cacheKey);
  if (m) return { data: m.data, savedAt: m.savedAt };
  const ls = _readLS();
  if (ls && ls.key === cacheKey) {
    _mem.set(cacheKey, { data: ls.data, savedAt: ls.savedAt, bindingKey: ls.bindingKey || '' });
    return { data: ls.data, savedAt: ls.savedAt };
  }
  return null;
}

/** binding(같은 프로젝트) 일치의 **마지막** 매트릭스를 조회 — 정확 키 miss일 때 stale 복원용.
 *  cacheKey 전체가 아니라 프로젝트 식별 부분키만 일치하면 되므로, 시험문서/빌드가 드리프트해도
 *  마지막 결과를 되살린다(호출측이 ⚠ stale 로 표시). 반환에 cacheKey 를 실어 호출측이 마운트
 *  키와 대조해 clean/stale 을 재판정할 수 있게 한다.
 *  ⚠ 다른 프로젝트로 새지 않도록 bindingKey 완전일치만 매칭한다(jobUrl+sourceRoot 포함). */
export function loadTraceMatrixByBinding(bindingKey) {
  if (!bindingKey) return null;
  // 모듈캐시: 최신 삽입분부터(역순) 스캔 — 같은 프로젝트의 가장 최근 저장을 고른다.
  const keys = Array.from(_mem.keys());
  for (let i = keys.length - 1; i >= 0; i -= 1) {
    const e = _mem.get(keys[i]);
    if (e && e.bindingKey === bindingKey) {
      return { data: e.data, savedAt: e.savedAt, cacheKey: keys[i] };
    }
  }
  // localStorage 미러(1건) — 새로고침 후 모듈캐시가 비었을 때.
  const ls = _readLS();
  if (ls && ls.key && ls.bindingKey === bindingKey) {
    _mem.set(ls.key, { data: ls.data, savedAt: ls.savedAt, bindingKey: ls.bindingKey });
    return { data: ls.data, savedAt: ls.savedAt, cacheKey: ls.key };
  }
  return null;
}

export function clearTraceMatrix() {
  _mem.clear();
  try { localStorage.removeItem(TRACE_KEY); } catch { /* best-effort */ }
}
