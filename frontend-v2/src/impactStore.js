/* 변경 영향 평가 결과의 새로고침 생존 영속.
 *
 * 원본 impactData는 App.jsx JobProvider(Context)에 있어 탭 전환에는 살아남지만 새로고침이면
 * 사라진다. '상세 가이드'(함수별 가이드 + AI 위험요약)는 ImpactGuideSection의 로컬 useState라
 * 프로젝트 전환/새로고침에 소실돼 매번 문서 추출 5회 + AI 호출을 다시 강요했다. 여기에 미러링해
 * 둘 다 복원한다.
 *
 * AnalysisSection의 VCAST 잡 영속(devops_v2_vcast_jobs)과 같은 계열이지만 저장 대상이 '잡
 * 포인터'가 아니라 '결과 본문'이라 quota를 신경 써야 한다 → 현재 보고 있는 1건만 보관한다.
 * 이력 목록 자체는 매번 백엔드(/api/scm/impact-jobs?summary=1)에서 fresh로 받으므로 로컬에
 * 쌓을 이유가 없다.
 */
const IMPACT_KEY = 'devops_v2_impact_current';
// 저장 payload 스키마 버전. 없거나 다르면 폐기한다 — 구 스키마 엔트리 1건이 남아 있으면
// 렌더가 `guide.summary.impactedReqs` 같은 필드를 무가드로 읽다가 매 마운트마다 탭을 크래시시키고,
// hydrate가 계속 재주입해 자가 치유가 되지 않는다.
export const STORE_VERSION = 1;

/** 가이드가 렌더 가능한 최소 형태인가 — 깨진 저장분이 화면을 죽이지 않게 load 시점에 거른다. */
function isRenderableGuide(value) {
  return Boolean(value)
    && Array.isArray(value.details)
    && Boolean(value.summary)
    && typeof value.summary === 'object';
}

/** 결과 식별자 — 어느 SCM의 어느 빌드/리비전, 어느 실행(job)인지.
 *  상세 가이드 하이드레이트 게이트(sameImpactTarget)의 입력이다. */
export function impactIdentity(impactData, jobId) {
  const meta = impactData?.trigger?.metadata || {};
  return {
    job_id: String(jobId || impactData?._job_id || ''),
    scm_id: String(impactData?.trigger?.scm_id || ''),
    // 어느 Jenkins Job에서 나온 결과인지 — 저장분이 '지금 열린 프로젝트'의 것인지 대조하는 근거.
    job_url: String(meta.job_url || ''),
    build_number: Number(meta.build_number) || 0,
    build_revision: String(meta.build_revision || ''),
    baseline_revision: String(meta.baseline_revision || ''),
    changed_files_source: String(meta.changed_files_source || ''),
  };
}

/** 식별자를 문자열 키로 — 상세 가이드를 '생성된 대상'에 결속시키는 데 쓴다. */
export function identityKey(id) {
  if (!id) return '';
  return [id.job_id || '', id.scm_id || '', id.build_number || 0, id.build_revision || ''].join('|');
}

/** impactData → 대상 키(위 identityKey의 단축형). */
export function impactKeyOf(impactData, jobId) {
  return impactData ? identityKey(impactIdentity(impactData, jobId)) : '';
}

/** Jenkins Job URL 비교용 정규화(후행 슬래시 차이 흡수). */
export function sameJobUrl(a, b) {
  const norm = (u) => String(u || '').trim().replace(/\/+$/, '');
  return Boolean(norm(a)) && norm(a) === norm(b);
}

/** 두 식별자가 '같은 분석 대상'인가.
 *
 * ISO 26262 관점의 안전 게이트다 — 빌드 A의 상세 가이드(ASIL/커버리지 판정 포함)를 빌드 B의
 * 데이터 위에 얹으면 안전 오보고가 된다. 그래서 확정 근거가 있을 때만 true를 준다:
 * job_id 일치(같은 실행이면 확정) → SCM+빌드번호 → SCM+빌드리비전. 아무 근거도 없으면
 * '모르니까 같다'가 아니라 false(가이드 폐기)로 간다.
 */
export function sameImpactTarget(a, b) {
  if (!a || !b) return false;
  if (a.job_id && b.job_id) return a.job_id === b.job_id;
  if (!a.scm_id || String(a.scm_id) !== String(b.scm_id)) return false;
  if (a.build_number && b.build_number) return a.build_number === b.build_number;
  if (a.build_revision && b.build_revision) return a.build_revision === b.build_revision;
  return false;
}

// 용량 압박 시 덜어낼 순서. impactData는 job_id로 백엔드에서 다시 받을 수 있으므로 먼저 버리고,
// guide/aiGuide는 재생성 비용(문서 추출 5회 + AI 호출)이 커서 가장 오래 붙든다.
// job_id가 없으면 impactData가 유일한 복원원이라 버리지 않는다.
const DROP_ORDER_WITH_JOB = ['impactData', 'guide', 'aiGuide'];
const DROP_ORDER_NO_JOB = ['guide', 'aiGuide'];

/** 현재 보고 있는 결과를 저장한다. quota 초과면 단계적으로 덜어내고 재시도.
 *  @returns {boolean} 무엇이든 저장에 성공했는지 (호출측이 '영속 안 됨'을 알 수 있게) */
export function saveImpactCurrent(entry) {
  if (!entry || (!entry.impactData && !entry.jobId)) return false;
  const payload = { ...entry, v: STORE_VERSION, savedAt: Date.now() };
  const dropOrder = entry.jobId ? DROP_ORDER_WITH_JOB : DROP_ORDER_NO_JOB;
  for (let i = 0; i <= dropOrder.length; i += 1) {
    try {
      localStorage.setItem(IMPACT_KEY, JSON.stringify(payload));
      return true;
    } catch {
      // QuotaExceededError — 한 단계 덜어내고 재시도.
      if (i === dropOrder.length) break;
      delete payload[dropOrder[i]];
    }
  }
  // 전부 실패. 반쯤 남은 stale 엔트리를 남기면 다음 하이드레이트가 그걸 최신으로 오인한다.
  try { localStorage.removeItem(IMPACT_KEY); } catch { /* best-effort */ }
  return false;
}

/** 저장된 결과를 읽는다. impactData가 quota로 빠졌어도 jobId가 있으면 백엔드에서 재조회 가능. */
export function loadImpactCurrent() {
  try {
    const raw = JSON.parse(localStorage.getItem(IMPACT_KEY) || 'null');
    if (!raw || typeof raw !== 'object') return null;
    if (raw.v !== STORE_VERSION) return null;          // 구/미상 스키마는 폐기
    if (!raw.impactData && !raw.jobId) return null;    // 복원 근거가 없는 엔트리
    // 가이드만 깨져 있으면 결과까지 버리지는 않고 가이드만 떨군다(재생성 가능).
    return isRenderableGuide(raw.guide) ? raw : { ...raw, guide: null };
  } catch {
    return null;
  }
}

export function clearImpactCurrent() {
  try { localStorage.removeItem(IMPACT_KEY); } catch { /* best-effort */ }
}
