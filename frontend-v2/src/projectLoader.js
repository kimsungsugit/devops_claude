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
  return pickScmForJobWithSource(scmList, jobUrl).entry;
}

/**
 * pickScmForJob과 같은 판정을 하되 '무엇을 근거로 골랐는지'를 함께 돌려준다.
 *
 * 근거를 버리면 소비자가 'job URL과 토큰이 정확히 일치해서 고른 것'과 '후보가 하나뿐이라
 * URL을 읽지도 않고 승인한 것'을 구분할 수 없다. 후자는 추론이지 증거가 아니라서,
 * 'SCM 1개 × Jenkins Job N개' 환경에서 무관한 Job의 changeSet으로 그 SCM을 분석하게 되고
 * update_baseline=True 경로에서 MC/DC baseline과 감사기록이 덮어써진다.
 *
 * 반환 entry는 pickScmForJob과 항상 동일하다(기존 동작 보존) — 토큰 증거를 먼저 찾고,
 * 없을 때만 '후보가 하나'라는 약한 근거로 폴백하되 그 사실을 source로 표시한다.
 *
 * @returns {{entry: object|null, source: 'exact'|'substring'|'sole'|null}}
 *   exact     — Jenkins job 이름(URL 말단 세그먼트)이 토큰과 정확히 일치 (증거·강)
 *   substring — job URL 문자열에 토큰이 포함, 최장 우선 (증거·중)
 *   sole      — 후보가 하나뿐이라 승인. job URL과의 접점 없음 (증거 아님)
 *   null      — 매칭 실패
 */
export function pickScmForJobWithSource(scmList, jobUrl) {
  if (!Array.isArray(scmList) || scmList.length === 0) return { entry: null, source: null };
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
      if (seg && t === seg) return { entry, source: 'exact' };  // exact job-name match is decisive
      if (jobStr.includes(t) && t.length > bestLen) {
        best = entry;
        bestLen = t.length;
      }
    }
  }
  if (best) return { entry: best, source: 'substring' };
  // 토큰 증거가 전혀 없을 때만 '후보가 하나'라는 약한 근거로 폴백한다. 체크아웃 자동해결에는
  // 이걸로 충분하지만(그래서 기존 동작을 그대로 보존한다) provenance 판정에는 쓰면 안 된다.
  if (scmList.length === 1) return { entry: scmList[0], source: 'sole' };
  return { entry: null, source: null };
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
 * @returns {Promise<object>} { artifacts, reportData, scmList, matchedScm, matchedScmSource, impactData:null, jobUrl, cacheRoot, _offline:true }
 */
export async function loadProjectFromCache(jobUrl, cfg) {
  const cacheRoot = defaultCacheRoot(jobUrl) || cfg?.cacheRoot || '';
  const buildSelector = cfg?.buildSelector || 'lastSuccessfulBuild';
  let scmList = [];
  try {
    const d = await api('/api/scm/list');
    scmList = Array.isArray(d) ? d : (d.items ?? d.registries ?? []);
  } catch { scmList = []; }
  const { entry: matchedScm, source: matchedScmSource } = pickScmForJobWithSource(scmList, jobUrl);
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
  return { artifacts, reportData, scmList, matchedScm, matchedScmSource, impactData: null, jobUrl, cacheRoot, _offline: true };
}
