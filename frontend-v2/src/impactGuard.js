/**
 * 영향분석 결과가 '지금 화면이 보고 있는 Job의 것'인지 판정하는 게이트.
 *
 * 왜 별도 모듈인가 — 이 판정은 원래 ImpactGuideSection 렌더 본문의 파생 불린값이었다.
 * 그래서 같은 Context(analysisResult.impactData)를 읽는 다른 소비처(SrsSdsSection의
 * 변경파일·영향문서 목록, ScmSection의 변경파일 목록)는 재사용할 방법이 없었고 무가드로
 * 남아 있었다. 판정 로직은 순수 함수라 컴포넌트에 있을 이유가 없으므로 여기로 뺀다.
 *
 * 왜 필요한가 — Dashboard.runAnalysis는 여러 개가 겹쳐 돌 수 있고, 서버측 취소 endpoint가
 * 없어 abort 후에도 진행 중인 요청은 완주한다. 세대 가드(Dashboard.runIdRef)가 구 실행의
 * 상태 쓰기를 막지만, 그건 '같은 탭에서 겹친 실행'만 해결한다. Detail.switchProject나
 * loadFromCache 실패처럼 '새 Job + 옛 분석결과'가 영구 지속되는 경로는 따로 남으므로,
 * 소비 시점에도 대조가 필요하다.
 *
 * 안전(ISO 26262) — 영향분석 결과는 문서 재생성 판정과 추적성에 흘러든다. 프로젝트 A의
 * 변경파일/영향문서를 B 화면에 표시하면 안전 오보고이고, 그 상태로 트리거하면
 * scm_id=A × job_url=B 조합이 나가 A의 MC/DC baseline(update_baseline=True)과 감사기록이
 * 덮어써진다. 그래서 정책은 일관되게 '증거 없으면 거부'다.
 */
import { pickScmForJobWithSource } from './projectLoader.js';
import { sameJobUrl } from './impactStore.js';

/** matchedScm을 그대로 신뢰해도 되는 근거들.
 *  'sole'(후보가 하나뿐이라 job URL을 읽지도 않고 승인)은 추론이지 증거가 아니라서 제외한다.
 *  값이 없는 경우(구 세션·캐시 결과에 matchedScmSource가 없음)도 자동으로 제외된다 — fail-closed. */
const STRONG_SCM_SOURCES = new Set(['manual', 'exact', 'substring']);

/**
 * 이 Job이 정말 이 SCM의 Job인지를 '증거'로만 판정한다.
 *
 * pickScmForJob은 후보가 하나면 job URL을 아예 읽지 않고 그대로 승인한다(체크아웃 자동해결
 * 용도의 의도된 설계). 그걸 provenance 판정에 그대로 쓰면 'SCM 1개 × Jenkins Job N개'
 * 환경에서 무관한 Job의 changeSet으로 그 SCM을 분석하게 된다.
 *
 * @returns {string} 증거가 있는 scm_id, 없으면 ''
 */
export function strictScmIdForJob(scmList, jobUrl) {
  const { entry, source } = pickScmForJobWithSource(scmList, jobUrl);
  if (!entry?.id) return '';
  return STRONG_SCM_SOURCES.has(source) ? entry.id : '';
}

/**
 * 현재 Job에 대응하는 scm_id를 증거 기반으로 확정한다.
 *
 * 생산자가 기록한 matchedScmSource가 강한 근거일 때만 matchedScm을 그대로 채택하고,
 * 아니면(= 'sole'이거나 근거 자체가 없으면) scmList + jobUrl로 재판정한다.
 * 이전에는 `matchedScm?.id ||` 가 먼저 와서 strict 판정이 아예 발화하지 않았다.
 */
export function scmIdForJob(analysisResult, jobUrl) {
  const source = analysisResult?.matchedScmSource;
  const matchedId = analysisResult?.matchedScm?.id;
  if (matchedId && STRONG_SCM_SOURCES.has(source)) return matchedId;
  return strictScmIdForJob(analysisResult?.scmList, jobUrl) || '';
}

/** 판정 실패 사유 → 사용자에게 보일 한 줄 설명. */
export const IMPACT_MISMATCH_KO = {
  job_mismatch: '분석 결과가 다른 Job의 것입니다',
  impact_job_mismatch: '영향분석이 다른 Job의 빌드로 실행됐습니다',
  scm_mismatch: '분석 결과가 다른 SCM의 것입니다',
  no_provenance: '이 결과가 현재 프로젝트의 것인지 확인할 수 없습니다',
};

/** 사유별 해소 방법. 화면마다 다른 안내를 하면 서로 모순된 지시가 된다.
 *  job_* 계열은 analysisResult 자체가 옛 Job의 것이라 '영향 탭에서 재분석'으로 풀리지 않는다
 *  — adoptImpact가 `{...prev, impactData}`로 병합해 stale jobUrl을 그대로 보존하기 때문. */
const MISMATCH_REMEDY_KO = {
  job_mismatch: '대시보드에서 이 프로젝트를 다시 불러오세요',
  impact_job_mismatch: '대시보드에서 이 프로젝트를 다시 불러오세요',
  scm_mismatch: "'변경 영향 평가' 탭에서 이 빌드로 다시 분석하세요",
};

/**
 * 감춘 사유를 사용자 문구로 만든다. 사유+해소방법을 한 문장으로 돌려준다.
 *
 * ⚠ 미지의 사유에 빈 문자열을 돌려주면 안 된다 — 호출처가 그걸 '표시할 게 없음'으로 읽어
 * 데이터를 감춘 채 배너도 안 띄우는 침묵 은닉이 된다. 사유가 새로 생겨도 최소한
 * '무언가를 감췄다'는 사실은 반드시 전달되도록 일반 문구로 폴백한다.
 */
export function mismatchText(reason) {
  if (!reason || reason === 'ok' || reason === 'no_impact' || reason === 'no_context') return '';
  const why = IMPACT_MISMATCH_KO[reason] || '현재 화면과 일치하지 않습니다';
  const how = MISMATCH_REMEDY_KO[reason] || '대시보드에서 이 프로젝트를 다시 불러오세요';
  return `${why}. ${how}`;
}

/**
 * analysisResult 객체 **전체**가 지금 보고 있는 Job의 것인지 판정한다.
 *
 * impactConflict가 impactData만 보는 것과 달리, 이건 matchedScm·scmList·linked_docs 같은
 * 형제 필드까지 포함해 '이 결과 뭉치가 통째로 옛 Job의 것인가'를 묻는다.
 *
 * 왜 별도로 필요한가 — Detail.switchProject는 `setSelectedJob(B)`가 await 앞에 있고
 * 뒤이은 `loadProjectFromCache(B)`가 throw하면 catch가 토스트만 띄운다. 그러면
 * `selectedJob=B × analysisResult=A(전부)`가 영구 지속된다. 이때 impactData가 null이면
 * impactConflict는 no_impact로 즉시 통과시키지만, A의 linked_docs로 추적성 매트릭스를
 * 그리는 경로(SrsSdsSection)는 여전히 오귀속이다 — 오히려 피해가 더 크다.
 */
export function contextConflict(analysisResult, jobUrl) {
  if (!analysisResult) return { conflict: false, reason: 'no_context' };
  if (analysisResult.jobUrl && jobUrl && !sameJobUrl(analysisResult.jobUrl, jobUrl)) {
    return { conflict: true, reason: 'job_mismatch' };
  }
  return { conflict: false, reason: 'ok' };
}

/**
 * '표시해도 되는가'를 판정한다 — 증거 부재가 아니라 **모순**만 차단한다.
 *
 * 트리거 게이트(impactMatchesJob)와 정책이 다른 이유:
 *  - 트리거는 파괴적이다. scm_id=A × job_url=B 조합이 나가면 B의 changeSet으로 A를 분석해
 *    A의 MC/DC baseline(update_baseline=True)과 감사기록을 덮어쓴다. 되돌릴 수 없으므로
 *    증거가 없으면 거부해야 한다.
 *  - 표시는 읽기다. 증거 부재까지 차단하면 정상 데이터를 상시로 감추게 된다 — 예컨대
 *    /api/local/impact/trigger 결과에는 job_url이 없고, SCM이 하나뿐인 저장소에서는
 *    job URL 토큰 일치도 기대할 수 없다(그래도 프로젝트는 하나뿐이라 오귀속이 불가능하다).
 *    그래서 여기서는 '다르다고 증명되는' 경우만 막는다.
 *
 * @param {object} analysisResult
 * @param {string} jobUrl        현재 화면의 Job URL
 * @param {string} [displayScmId] 이 화면이 실제로 보여주고 있는 SCM id (있으면 대조)
 * @returns {{conflict: boolean, reason: string}}
 */
export function impactConflict(analysisResult, jobUrl, displayScmId = '') {
  const impact = analysisResult?.impactData;
  if (!impact) return { conflict: false, reason: 'no_impact' };

  // 축 1 — 결과 뭉치 자체가 옛 Job의 것인가. **이게 아래 두 축이 vacuous일 때의 유일 방어**다.
  const ctx = contextConflict(analysisResult, jobUrl);
  if (ctx.conflict) return ctx;

  // 축 2 — impact 자신의 provenance. 단, job_url은 선택 필드다(backend/schemas.py의
  // 기본값 "", /api/local/impact/trigger는 아예 안 싣는다) → 없으면 vacuous.
  const impactJobUrl = impact?.trigger?.metadata?.job_url || '';
  if (impactJobUrl && jobUrl && !sameJobUrl(impactJobUrl, jobUrl)) {
    return { conflict: true, reason: 'impact_job_mismatch' };
  }

  // 축 3 — 이 화면이 보여주는 SCM과 결과를 만든 SCM 대조.
  // ⚠ 이 축은 **stale 검출에는 무력하다**. 호출처 두 곳 모두 displayScmId를 검증 대상과
  // 같은 analysisResult에서 파생하므로(SrsSdsSection의 activeScm, ScmSection의 selectedId
  // 초기 seed 모두 analysisResult.matchedScm 유래), 결과 뭉치가 통째로 stale이면 둘이
  // 항상 일치한다. 실제로 잡는 건 '사용자가 SCM 드롭다운을 다른 값으로 바꾼 경우' 하나다.
  // 독립 증거로 오해하지 말 것 — stale 방어는 축 1이 전담한다.
  const impactScmId = String(impact?.trigger?.scm_id || '');
  if (impactScmId && displayScmId && impactScmId !== displayScmId) {
    return { conflict: true, reason: 'scm_mismatch' };
  }
  return { conflict: false, reason: 'ok' };
}

/**
 * analysisResult.impactData가 지금 보고 있는 Job의 것인지 **증거로** 판정한다.
 * 파괴적 동작(트리거)의 게이트용 — 표시용에는 impactConflict를 쓸 것.
 *
 * 세 축을 모두 요구한다 — 하나라도 어긋나면 거부:
 *  1. analysisResult의 형제 필드 jobUrl ↔ 현재 job.url
 *  2. impact 자신의 provenance(trigger.metadata.job_url) ↔ 현재 job.url
 *  3. job_url 증거가 아예 없는 결과(/api/local/impact/trigger는 job_url을 안 싣는다)는
 *     SCM 축으로 증거를 요구 — 1·2가 모두 vacuous true가 되어 검사가 단락되는 걸 막는다.
 *
 * @returns {{ok: boolean, reason: string}} reason: ok | no_impact | no_job |
 *   job_mismatch | impact_job_mismatch | no_provenance
 */
export function impactMatchesJob(analysisResult, jobUrl) {
  const impact = analysisResult?.impactData;
  if (!impact) return { ok: false, reason: 'no_impact' };
  // Job이 아직 안 정해졌으면 대조할 기준이 없다. 이건 '불일치'가 아니라 '판정 불가'라서
  // 통과시킨다 — Job 없이 결과만 로드하는 화면(영향 탭 이력 조회)이 정상 경로다.
  if (!jobUrl) return { ok: true, reason: 'no_job' };

  if (analysisResult?.jobUrl && !sameJobUrl(analysisResult.jobUrl, jobUrl)) {
    return { ok: false, reason: 'job_mismatch' };
  }
  const impactJobUrl = impact?.trigger?.metadata?.job_url || '';
  if (impactJobUrl) {
    return sameJobUrl(impactJobUrl, jobUrl)
      ? { ok: true, reason: 'ok' }
      : { ok: false, reason: 'impact_job_mismatch' };
  }
  // job_url 증거가 없다 → SCM 축으로 대조.
  const scmForJob = scmIdForJob(analysisResult, jobUrl);
  const impactScmId = String(impact?.trigger?.scm_id || '');
  if (scmForJob && impactScmId && impactScmId === scmForJob) {
    return { ok: true, reason: 'ok' };
  }
  return { ok: false, reason: 'no_provenance' };
}

/**
 * 분석 '대상'이 하나로 확정되는지 판정한다 — 이력 조회·트리거의 fail-closed 조건.
 *
 * impactMatchesJob과 다른 점: 결과가 아직 없는 상태(no_impact)를 통과시킨다. 아직 아무것도
 * 분석 안 한 화면에서 '이 빌드 분석' 버튼이 죽으면 안 되기 때문이다. 대신 그 경우에도
 * 'Job은 새 것인데 analysisResult는 옛 것'인 조합은 계속 거부한다.
 */
export function targetConsistent(analysisResult, jobUrl) {
  const verdict = impactMatchesJob(analysisResult, jobUrl);
  if (verdict.reason !== 'no_impact') return verdict.ok;
  if (analysisResult?.jobUrl && jobUrl && !sameJobUrl(analysisResult.jobUrl, jobUrl)) return false;
  return true;
}
