import { post, api, defaultCacheRoot } from './api.js';

/**
 * Pick the most likely SCM registry entry for the given Jenkins job URL.
 *
 * Why this matters: the backend resolver treats `scm_id` as an authoritative
 * override (it short-circuits URL auto-matching). If we blindly send
 * `scmList[0]` when multiple projects are registered, a wrong entry's
 * credentials would be used for checkout. So we only assert a match when we
 * have reasonable confidence; otherwise we omit `scm_id` and let the backend
 * auto-resolve by repo_url.
 */
export function pickScmForJob(scmList, jobUrl) {
  if (!Array.isArray(scmList) || scmList.length === 0) return null;
  if (scmList.length === 1) return scmList[0];
  const jobStr = String(jobUrl || '').toLowerCase();
  // Jenkins job name = the URL's terminal path segment. An *exact* token match on
  // it is the strongest signal and must beat a mere substring of a shorter id.
  const seg = jobStr.replace(/\/+$/, '').split('/').filter(Boolean).pop() || '';
  // Otherwise fall back to the LONGEST (most specific) substring hit, not the
  // first in list order. Returning the first match let a shorter id shadow a
  // longer sibling: "kjpds02" is a substring of a "kjpds02_pv" job URL, so
  // whichever was registered first won — analysing the wrong project's specs.
  // Longest-token wins is direction-safe too: a "kjpds02" job URL does NOT
  // contain the longer "kjpds02_pv", so only the correct shorter id matches it.
  let best = null;
  let bestLen = 0;
  for (const entry of scmList) {
    const tokens = [entry.id, entry.name]
      .filter(Boolean)
      .map(s => String(s).toLowerCase())
      .filter(s => s.length >= 3);
    for (const t of tokens) {
      if (seg && t === seg) return entry;            // exact job-name match is decisive
      if (jobStr.includes(t) && t.length > bestLen) {
        best = entry;
        bestLen = t.length;
      }
    }
  }
  return best;
}

/**
 * 캐시된 빌드 분석 결과를 Jenkins 재sync 없이 읽어 analysisResult 형태로 반환한다.
 *
 * 분석 흐름(sync→report)의 sync(Jenkins 라이브 의존) 단계를 건너뛰고 이미 캐시된
 * report/summary만 조회하므로, Dashboard의 "오프라인 캐시 보기"와 Detail의 "브레드크럼
 * 프로젝트 전환" 양쪽에서 재사용한다(단일 출처 — DRY). 에러는 호출자에서 처리하도록 throw.
 *
 * @param {string} jobUrl  정규화된 Job URL(끝에 '/').
 * @param {object} cfg      Jenkins 설정(cacheRoot/buildSelector 사용).
 * @returns {Promise<object>} { artifacts, reportData, scmList, matchedScm, impactData:null, jobUrl, cacheRoot, _offline:true }
 */
export async function loadProjectFromCache(jobUrl, cfg) {
  const cacheRoot = defaultCacheRoot(jobUrl) || cfg?.cacheRoot || '';
  const buildSelector = cfg?.buildSelector || 'lastSuccessfulBuild';
  let scmList = [];
  try {
    const d = await api('/api/scm/list');
    scmList = Array.isArray(d) ? d : (d.items ?? d.registries ?? []);
  } catch { scmList = []; }
  const matchedScm = pickScmForJob(scmList, jobUrl);
  const raw = await post('/api/jenkins/report/summary', {
    job_url: jobUrl, cache_root: cacheRoot, build_selector: buildSelector,
  });
  const reportData = {
    ...raw,
    build_number: raw?.kpis?.build?.build_number ?? raw?.build_number,
    result: raw?.kpis?.build?.result ?? raw?.result,
    coverage: raw?.kpis?.coverage?.line_rate != null
      ? Math.round(raw.kpis.coverage.line_rate * 100)
      : (typeof raw?.coverage === 'number' ? raw.coverage : null),
  };
  const artMap = raw?.artifacts ?? {};
  const artifacts = Object.entries(artMap).flatMap(([type, list]) =>
    (Array.isArray(list) ? list : []).map(f => ({
      type, name: (f.path ?? f.title ?? '').split(/[\\/]/).pop(), path: f.path, title: f.title,
    })));
  return { artifacts, reportData, scmList, matchedScm, impactData: null, jobUrl, cacheRoot, _offline: true };
}
