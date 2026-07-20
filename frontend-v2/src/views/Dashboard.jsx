import { useState, useCallback, useRef, useEffect } from 'react';
import { post, api, defaultCacheRoot } from '../api.js';
import { useToast, useJenkinsCfg, useJob } from '../App.jsx';
import { pickScmForJob, loadProjectFromCache } from '../projectLoader.js';
import { pollImpactJob, throwIfAborted } from '../impactPoll.js';
import JobCard from '../components/JobCard.jsx';
import ResultPanel from '../components/ResultPanel.jsx';
import AggregateCharts from '../components/AggregateCharts.jsx';

// pickScmForJob은 projectLoader로 이관됨 — 기존 import 경로(views/Dashboard) 호환 위해 re-export.
export { pickScmForJob };

/* ── Step definitions ─────────────────────────────────────────────── */
const STEPS = [
  { id: 'sync',   label: '아티팩트 동기화' },
  { id: 'report', label: '빌드 정보 수집' },
  { id: 'scm',    label: 'SCM 목록 조회' },
  { id: 'impact', label: '문서 영향도 분석' },
];

function stepIcon(state) {
  if (state === 'done')  return '✓';
  if (state === 'error') return '✕';
  return '○';
}

/** Poll jenkins progress until done or error */
async function pollJenkinsProgress(jobUrl, buildSelector, jobId, action, { onMsg, signal }) {
  while (true) {
    throwIfAborted(signal);
    await new Promise(r => setTimeout(r, 2000));
    throwIfAborted(signal);  // 대기 중 도착한 '중단'
    const data = await api(
      `/api/jenkins/progress?action=${encodeURIComponent(action)}` +
      `&job_url=${encodeURIComponent(jobUrl)}` +
      `&build_selector=${encodeURIComponent(buildSelector)}` +
      `&job_id=${encodeURIComponent(jobId)}`
    );
    throwIfAborted(signal);  // 요청 왕복 중 도착한 '중단'
    const p = data?.progress || {};
    if (p.message || p.stage) onMsg(p.message || p.stage);
    if (p.done || p.error) return p;
  }
}

/* pollImpactJob은 impactPoll.js로 이관 — '변경 영향 평가' 탭의 빌드별 재실행과 공유한다. */

/* ── Dashboard ────────────────────────────────────────────────────── */
export default function Dashboard({ onGoDetail }) {
  const toast = useToast();
  const { cfg } = useJenkinsCfg();
  const { selectedJob, setSelectedJob, setAnalysisResult } = useJob();

  const [jobs, setJobs] = useState([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [aggStats, setAggStats] = useState(null);
  const [aggLoading, setAggLoading] = useState(false);
  const [filter, setFilter] = useState('');
  const [offlineUrl, setOfflineUrl] = useState('');   // 오프라인 캐시 보기 Job URL 입력
  const filterInputName = useRef(`job-filter-${Math.random().toString(36).slice(2, 10)}`).current;
  const [favorites, setFavorites] = useState(() => {
    try { return JSON.parse(localStorage.getItem('devops_fav_jobs') || '[]'); } catch { return []; }
  });
  const [showFavOnly, setShowFavOnly] = useState(() => {
    try { return JSON.parse(localStorage.getItem('devops_fav_jobs') || '[]').length > 0; } catch { return false; }
  });

  const toggleFavorite = useCallback((jobUrl) => {
    setFavorites(prev => {
      const next = prev.includes(jobUrl) ? prev.filter(u => u !== jobUrl) : [...prev, jobUrl];
      try { localStorage.setItem('devops_fav_jobs', JSON.stringify(next)); } catch { /* quota exceeded or private mode */ }
      return next;
    });
  }, []);

  const loadAggregateStats = useCallback(async () => {
    const targetJobs = showFavOnly ? jobs.filter(j => favorites.includes(j.url)) : jobs;
    if (targetJobs.length === 0) return;
    setAggLoading(true);
    try {
      const data = await post('/api/jenkins/aggregate-stats', {
        job_urls: targetJobs.map(j => j.url),
        cache_root: cfg.cacheRoot || '.devops_pro_cache',
      });
      setAggStats(data);
    } catch (e) {
      console.debug('Aggregate stats failed:', e.message);
    } finally {
      setAggLoading(false);
    }
  }, [jobs, favorites, showFavOnly, cfg.cacheRoot]);

  useEffect(() => {
    // Re-fetch when the filtered job set changes. Debounced ~200ms so toggling
    // several favorites in quick succession collapses into one
    // /aggregate-stats request instead of N. We always list `favorites` as a
    // dep — `loadAggregateStats` already closes over it, and a conditional
    // null/array dep breaks React's reference equality and trips exhaustive-deps.
    if (jobs.length === 0) return;
    const timer = setTimeout(() => { loadAggregateStats(); }, 200);
    return () => clearTimeout(timer);
  }, [jobs, showFavOnly, favorites, loadAggregateStats]);

  const [running, setRunning] = useState(false);
  const [stepStates, setStepStates] = useState({});
  const [stepMsgs, setStepMsgs] = useState({});
  const [result, setResult] = useState(null);
  // SCM registry choices for the manual override dropdown (populated at sync time).
  const [scmChoices, setScmChoices] = useState([]);
  // User-selected scm_id override. Empty string = auto (backend picks by URL).
  const [manualScmId, setManualScmId] = useState('');
  // Checkout outcome from the last sync run — drives the warning badge.
  const [checkoutStatus, setCheckoutStatus] = useState(null);
  const abortRef = useRef(null);
  const autoRunRef = useRef(null);

  /* Load Jenkins job list */
  const loadJobs = useCallback(async () => {
    if (!cfg.baseUrl || !cfg.username || !cfg.token) {
      toast('warning', '설정 탭에서 Jenkins 연결 정보를 먼저 입력하세요.');
      return;
    }
    setJobsLoading(true);
    try {
      const data = await post('/api/jenkins/jobs', {
        base_url: cfg.baseUrl,
        username: cfg.username,
        api_token: cfg.token,
        recursive: true,
        max_depth: 2,
        verify_tls: cfg.verifyTls,
      });
      setJobs(Array.isArray(data) ? data : (data.jobs ?? []));
    } catch (e) {
      toast('error', `Job 목록 조회 실패: ${e.message}`);
    } finally {
      setJobsLoading(false);
    }
  }, [cfg, toast]);

  // Auto-load jobs on mount if credentials exist
  useEffect(() => {
    if (cfg.baseUrl && cfg.username && cfg.token && jobs.length === 0) {
      loadJobs();
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const setStep = (id, state, msg = '') => {
    setStepStates(p => ({ ...p, [id]: state }));
    if (msg) setStepMsgs(p => ({ ...p, [id]: msg }));
  };

  /* Analysis result cache keyed by jobUrl + buildNumber */
  const cacheRef = useRef({});

  /* One-button automation */
  const runAnalysis = useCallback(async () => {
    if (!selectedJob) return;
    if (!cfg.baseUrl || !cfg.username || !cfg.token) {
      toast('warning', '설정 탭에서 Jenkins 연결 정보를 먼저 입력하세요.');
      return;
    }

    setRunning(true);
    setResult(null);
    setStepStates({});
    setStepMsgs({});

    const jobUrl = selectedJob.url;
    const cacheRoot = defaultCacheRoot(jobUrl) || cfg.cacheRoot;
    const buildSelector = cfg.buildSelector || 'lastSuccessfulBuild';

    abortRef.current = new AbortController();
    const { signal } = abortRef.current;

    let artifacts = [];
    let reportData = null;
    let scmList = [];
    let matchedScm = null;
    let impactData = null;

    const updateResult = () => {
      const current = { artifacts, reportData, scmList, matchedScm, impactData, jobUrl, cacheRoot };
      setResult(current);
      setAnalysisResult(current);
    };

    try {
      /* Prefetch SCM registry so the sync endpoint can resolve SVN credentials
         from the matching entry (scm_id/scm_username + scm_password_env). */
      try {
        const scmData = await api('/api/scm/list');
        scmList = Array.isArray(scmData)
          ? scmData
          : (scmData.items ?? scmData.registries ?? []);
      } catch (_prefetchErr) {
        scmList = [];
      }
      setScmChoices(scmList);
      // Manual override wins; otherwise fall back to the heuristic.
      const manual = manualScmId ? scmList.find(e => e.id === manualScmId) : null;
      matchedScm = manual || pickScmForJob(scmList, jobUrl);

      /* Step 1: Artifact sync */
      // trigger-async와 같은 이유로 발사 직전에 확인한다 — sync-async는 아티팩트 다운로드 +
      // SVN 체크아웃을 수행하는 부작용 요청이고, 서버측 취소 endpoint가 없어 한번 뜨면 완주한다.
      throwIfAborted(signal);
      setStep('sync', 'active', '동기화 시작 중...');
      setCheckoutStatus(null);
      const syncRes = await post('/api/jenkins/sync-async', {
        job_url: jobUrl,
        username: cfg.username,
        api_token: cfg.token,
        cache_root: cacheRoot,
        build_selector: buildSelector,
        verify_tls: cfg.verifyTls,
        patterns: [],
        // Only pass scm_id when confident; otherwise the backend auto-matches by repo_url.
        scm_id: matchedScm?.id || '',
        scm_username: matchedScm?.scm_username || '',
      });

      if (!syncRes?.job_id) throw new Error('sync job_id를 받지 못했습니다.');

      const syncProgress = await pollJenkinsProgress(jobUrl, buildSelector, syncRes.job_id, 'sync', {
        signal,
        onMsg: msg => setStep('sync', 'active', msg),
      });

      if (syncProgress.error) throw new Error(`동기화 실패: ${syncProgress.error}`);
      // The backend publishes checkout_ok / checkout_error on the final
      // progress event — surface that so a "sync done 100%" with an empty
      // source dir doesn't pass silently.
      const checkoutOk = syncProgress.checkout_ok !== false;
      setCheckoutStatus({
        ok: checkoutOk,
        error: checkoutOk ? '' : (syncProgress.checkout_error || 'unknown'),
      });
      setStep('sync', 'done', checkoutOk ? '동기화 완료' : `동기화 완료 (SCM 실패: ${syncProgress.checkout_error || 'unknown'})`);

      /* Cache check */
      try {
        const buildInfo = await post('/api/jenkins/build-info', {
          job_url: jobUrl,
          username: cfg.username,
          api_token: cfg.token,
          verify_tls: cfg.verifyTls,
        });
        const currentBuild = buildInfo?.number ?? buildInfo?.build_number;
        const cached = cacheRef.current[jobUrl];
        // Include scm_id in the cache identity: switching the selected
        // registry for the same jobUrl/build must refresh rather than
        // replay a stale run bound to a different SCM.
        const cacheScmId = matchedScm?.id || '';
        if (
          cached
          && cached.buildNumber === currentBuild
          && cached.scmId === cacheScmId
          && cached.result
        ) {
          setStep('report', 'done', `빌드 #${currentBuild} (캐시)`);
          setStep('scm', 'done', '캐시 사용');
          setStep('impact', 'done', '캐시 사용');
          setResult(cached.result);
          setAnalysisResult(cached.result);
          toast('success', `빌드 #${currentBuild} 변경 없음 — 캐시된 결과를 불러왔습니다.`);
          setRunning(false);
          return;
        }
      } catch (e) {
        console.debug('Build info cache check skipped:', e.message);
      }

      /* Step 2: Report data + artifact list */
      setStep('report', 'active', '빌드 정보 수집 중...');
      try {
        const raw = await post('/api/jenkins/report/summary', {
          job_url: jobUrl,
          cache_root: cacheRoot,
          build_selector: buildSelector,
        });
        reportData = {
          ...raw,
          build_number: raw?.kpis?.build?.build_number ?? raw?.build_number,
          result: raw?.kpis?.build?.result ?? raw?.result,
          branch: raw?.kpis?.build?.branch ?? raw?.branch,
          commit: raw?.kpis?.build?.commit ?? raw?.commit,
          coverage: raw?.kpis?.coverage?.line_rate != null
            ? Math.round(raw.kpis.coverage.line_rate * 100)
            : (typeof raw?.coverage === 'number' ? raw.coverage : null),
        };
        const artMap = raw?.artifacts ?? {};
        artifacts = Object.entries(artMap).flatMap(([type, list]) =>
          (Array.isArray(list) ? list : []).map(f => ({
            type,
            name: (f.path ?? f.title ?? '').split(/[\\/]/).pop(),
            path: f.path,
            title: f.title,
            ...(f.rows != null ? { rows: f.rows } : {}),
            ...(f.sheets ? { sheets: f.sheets } : {}),
          }))
        );
        setStep('report', 'done', `빌드 #${reportData.build_number ?? '?'} (${artifacts.length}개 파일)`);
      } catch (e) {
        setStep('report', 'error', e.message);
      }
      updateResult();

      /* Step 3: SCM list (reuse prefetched result when available) */
      setStep('scm', 'active', 'SCM 조회 중...');
      try {
        if (!scmList.length) {
          const scmData = await api('/api/scm/list');
          scmList = Array.isArray(scmData) ? scmData : (scmData.items ?? scmData.registries ?? []);
        }
        setStep('scm', 'done', `${scmList.length}개 등록`);
      } catch (e) {
        setStep('scm', 'error', e.message);
      }
      updateResult();

      /* Step 4: Impact analysis
         Use the same registry entry we picked for sync (matchedScm) so Impact
         runs against the project actually selected — not scmList[0], which
         would silently analyse the wrong project whenever multiple registries
         exist. When the heuristic can't pick one, skip rather than guess. */
      if (matchedScm) {
        // '중단' 이후에 트리거가 나가면 서버는 체크아웃·문서생성·커버리지 baseline 갱신·감사기록을
        // 모두 수행하는데 화면엔 아무 것도 안 뜬다(취소 후 침묵 실행). 부작용을 만드는 요청이므로
        // 발사 직전에 반드시 확인한다.
        throwIfAborted(signal);
        setStep('impact', 'active', '영향도 분석 시작 중...');
        try {
          const triggerRes = await post('/api/jenkins/impact/trigger-async', {
            scm_id: matchedScm.id,
            build_number: reportData?.build_number ?? 0,
            job_url: jobUrl,
            base_ref: matchedScm.base_ref || '',
            targets: ['uds', 'suts', 'sits', 'sts', 'sds'],
          });

          if (!triggerRes?.job_id) throw new Error('impact job_id를 받지 못했습니다.');

          impactData = await pollImpactJob(triggerRes.job_id, {
            signal,
            onMsg: msg => setStep('impact', 'active', msg),
          });
          // 실행 식별자 — 영향 탭의 영속/하이드레이트가 '같은 실행인지'를 확정하는 근거이자,
          // localStorage quota로 본문이 빠졌을 때 백엔드에서 재조회할 열쇠(impactStore 참조).
          impactData._job_id = triggerRes.job_id;
          impactData._linked_docs = matchedScm.linked_docs || {};
          impactData._scm_name = matchedScm.name || matchedScm.id;
          // 부분 실패(분석은 성공, 일부 문서 자동 생성 실패)를 '완료'로 위장하지 않는다.
          // 백엔드가 job을 completed로 내려주되 partial_failure/actions[t].status='failed'로 표시.
          const _failedDocs = Object.entries(impactData.actions || {})
            .filter(([, a]) => a && a.status === 'failed')
            .map(([t]) => t.toUpperCase());
          if (impactData.partial_failure || _failedDocs.length) {
            const _list = _failedDocs.join(', ') || '일부 대상';
            setStep('impact', 'done', `분석 완료 · ${_list} 문서 생성 실패`);
            toast('warning', `영향 분석은 완료했으나 ${_list} 문서 자동 생성에 실패했습니다. 분석 결과는 유효합니다.`);
          } else {
            setStep('impact', 'done', '완료');
          }
        } catch (e) {
          if (e.message === 'AbortError') throw e;
          setStep('impact', 'error', e.message);
          impactData = null;
        }
      } else if (scmList.length > 0) {
        setStep('impact', 'done', 'SCM 자동매칭 실패 — 설정에서 드롭다운으로 선택 후 재시도');
      } else {
        setStep('impact', 'done', 'SCM 미등록 — 건너뜀');
      }

      updateResult();

      const bn = reportData?.build_number;
      if (bn) {
        cacheRef.current[jobUrl] = {
          buildNumber: bn,
          scmId: matchedScm?.id || '',
          result: { artifacts, reportData, scmList, matchedScm, impactData, jobUrl, cacheRoot },
          timestamp: Date.now(),
        };
      }
      // 부분 실패는 위에서 warning 토스트로 이미 알렸다 — 성공으로 덮어쓰지 않는다(위장 방지).
      if (!impactData?.partial_failure) {
        toast('success', '분석이 완료되었습니다.');
      }
    } catch (e) {
      if (e.message !== 'AbortError') {
        toast('error', `분석 중 오류: ${e.message}`);
      }
    } finally {
      setRunning(false);
    }
  }, [selectedJob, cfg, toast, setAnalysisResult, manualScmId]);

  // 오프라인 캐시 보기 — Jenkins 미연결/다운 시, 이전에 분석돼 캐시된 빌드를 sync 없이 report/summary로 바로 조회한다.
  // 분석 흐름(sync→report)의 sync(Jenkins 의존) 단계를 건너뛰고 캐시된 리포트만 읽으므로 Jenkins 라이브 연결이 불필요하다.
  const loadFromCache = useCallback(async (rawUrl) => {
    if (!rawUrl || !rawUrl.trim()) { toast('info', 'Job URL을 입력하세요.'); return; }
    const jobUrl = rawUrl.trim().replace(/\/+$/, '') + '/';
    const name = jobUrl.split('/').filter(Boolean).pop();
    setSelectedJob({ name, url: jobUrl });
    try {
      toast('info', `캐시에서 '${name}' 불러오는 중...`);
      // 캐시 로드 로직은 projectLoader.loadProjectFromCache로 단일화(Detail 브레드크럼 전환과 공유).
      const result = await loadProjectFromCache(jobUrl, cfg);
      setAnalysisResult(result);
      toast('success', `캐시 로드 완료 — 빌드 #${result.reportData?.build_number ?? '?'} (Jenkins 미연결)`);
      onGoDetail?.();
    } catch (e) {
      toast('error', `캐시 로드 실패: ${e.message} — 이 Job의 캐시가 없을 수 있습니다.`);
    }
  }, [cfg, toast, setSelectedJob, setAnalysisResult, onGoDetail]);

  autoRunRef.current = runAnalysis;

  const stopAnalysis = () => {
    abortRef.current?.abort();
    setRunning(false);
  };

  const jobName = (j) => j.name || j.fullName || '';
  const filtered = jobs.filter(j => {
    if (showFavOnly && !favorites.includes(j.url)) return false;
    return !filter || jobName(j).toLowerCase().includes(filter.toLowerCase());
  });

  /* Stats — computed from filtered (respects favorites & search filter) */
  const statsPool = filtered;
  const successCount = statsPool.filter(j => (j.color || '').includes('blue')).length;
  const failCount    = statsPool.filter(j => (j.color || '').includes('red')).length;
  const unstableCount = statsPool.filter(j => (j.color || '').includes('yellow')).length;
  const runningCount = statsPool.filter(j => (j.color || '').endsWith('_anime')).length;
  const disabledCount = statsPool.filter(j => (j.color || '').includes('disabled') || (j.color || '').includes('notbuilt')).length;
  const healthRate = statsPool.length > 0 ? Math.round((successCount / statsPool.length) * 100) : 0;

  /* Build activity — recent builds from last 7 days */
  const now = Date.now();
  const WEEK = 7 * 24 * 60 * 60 * 1000;
  const recentBuilds = statsPool.filter(j => j.lastBuild?.timestamp && (now - j.lastBuild.timestamp) < WEEK);
  const recentSuccess = recentBuilds.filter(j => (j.color || '').includes('blue')).length;

  return (
    <div>
      {/* Stats */}
      {jobs.length > 0 && (
        <div>
          <div className="stats-row">
            <div className="stat-card">
              <div className="stat-value">{statsPool.length}</div>
              <div className="stat-label">{showFavOnly ? '★ 즐겨찾기' : '전체'} Job</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{ color: 'var(--color-success)' }}>{successCount}</div>
              <div className="stat-label">성공</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{ color: 'var(--color-danger)' }}>{failCount}</div>
              <div className="stat-label">실패</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{ color: 'var(--color-warning)' }}>{unstableCount}</div>
              <div className="stat-label">불안정</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{runningCount}</div>
              <div className="stat-label">실행 중</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{ color: healthRate >= 80 ? 'var(--color-success)' : healthRate >= 50 ? 'var(--color-warning)' : 'var(--color-danger)' }}>
                {healthRate}%
              </div>
              <div className="stat-label">빌드 성공률</div>
            </div>
          </div>

          {/* Build health bar removed — merged into AggregateCharts donut card */}
        </div>
      )}

      {/* Aggregate analysis stats */}
      {aggLoading && (
        <div style={{ textAlign: 'center', padding: 'var(--sp-2)', color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>
          <span className="spinner" style={{ display: 'inline-block', marginRight: 6 }} /> 분석 통계 로딩 중...
        </div>
      )}
      {/* Aggregate number cards removed — data shown in AggregateCharts below */}
      {aggStats?.projects?.length >= 1 && (
        <AggregateCharts projects={aggStats.projects} buildStats={{ successCount, failCount, unstableCount, disabledCount, total: statsPool.length, recentBuilds: recentBuilds.length, recentSuccess }} />
      )}

      {/* 오프라인 캐시 보기 — Jenkins 목록을 못 불러온 경우(미연결/다운) 캐시된 빌드를 sync 없이 직접 조회 */}
      {!jobsLoading && jobs.length === 0 && (
        <div className="panel" style={{ marginBottom: 12, borderLeft: '3px solid var(--color-warning)' }}>
          <div className="panel-header"><span className="panel-title">⚡ 오프라인 캐시 보기</span></div>
          <div className="text-sm text-muted" style={{ marginBottom: 8, lineHeight: 1.5 }}>
            Jenkins 프로젝트 목록을 불러오지 못했습니다(미연결/다운). 이전에 분석돼 <b>캐시된 빌드</b>는 Jenkins 없이 바로 볼 수 있습니다 —
            동기화를 건너뛰고 캐시된 리포트만 읽어 프로젝트 결과 화면을 엽니다.
          </div>
          {favorites.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>★ 즐겨찾기에서 바로 보기</div>
              <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
                {favorites.map((url) => (
                  <button key={url} className="btn-sm" onClick={() => loadFromCache(url)}>
                    {url.split('/').filter(Boolean).pop()}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
            <input type="text" value={offlineUrl} onChange={e => setOfflineUrl(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && offlineUrl.trim()) loadFromCache(offlineUrl); }}
              placeholder="Job URL (예: http://192.168.110.40:7000/job/HDPDM01_PDS64_RD/)"
              style={{ flex: 1, minWidth: 260, padding: '6px 10px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6 }} />
            <button className="btn-primary" onClick={() => loadFromCache(offlineUrl)} disabled={!offlineUrl.trim()}>
              캐시에서 보기
            </button>
          </div>
        </div>
      )}

      {/* Toolbar */}
      <div className="toolbar">
        <span className="toolbar-title">Jenkins 프로젝트</span>
        <input
          type="search"
          role="searchbox"
          name={filterInputName}
          id={filterInputName}
          placeholder="Job 이름 필터..."
          value={filter}
          onChange={e => setFilter(e.target.value)}
          autoComplete="off"
          autoCorrect="off"
          autoCapitalize="off"
          spellCheck="false"
          data-form-type="other"
          data-lpignore="true"
          data-1p-ignore="true"
          aria-label="Job 이름 필터"
          style={{ width: 200 }}
        />
        {favorites.length > 0 && (
          <button
            className={showFavOnly ? 'btn-primary' : ''}
            onClick={() => setShowFavOnly(p => !p)}
            title={showFavOnly ? '전체 보기' : '즐겨찾기만 보기'}
          >
            {showFavOnly ? '★ 즐겨찾기' : '☆ 즐겨찾기'} ({favorites.length})
          </button>
        )}
        <div className="toolbar-spacer" />
        <button onClick={loadJobs} disabled={jobsLoading}>
          {jobsLoading ? <><span className="spinner" style={{ display: 'inline-block', marginRight: 6 }} /> 조회 중...</> : 'Job 목록 불러오기'}
        </button>
      </div>

      {/* Job cards — horizontal scroll */}
      {filtered.length > 0 ? (
        <div className="job-scroll">
          {filtered.map(job => (
            <JobCard
              key={job.url || job.name}
              job={job}
              selected={selectedJob?.url === job.url}
              isFavorite={favorites.includes(job.url)}
              onToggleFavorite={(e) => { e.stopPropagation(); toggleFavorite(job.url); }}
              onClick={() => {
                setSelectedJob(job);
                setResult(null);
                setStepStates({});
                setStepMsgs({});
                setTimeout(() => autoRunRef.current?.(), 100);
              }}
            />
          ))}
        </div>
      ) : (
        !jobsLoading && (
          <div className="empty-state">
            <div className="empty-icon">{jobs.length === 0 ? '?' : '?'}</div>
            <div className="empty-title">
              {jobs.length === 0 ? 'Jenkins Job 없음' : '검색 결과 없음'}
            </div>
            <div className="empty-desc">
              {jobs.length === 0
                ? <>설정 탭에서 Jenkins 연결 정보를 입력한 후<br />'Job 목록 불러오기' 버튼을 클릭하세요.</>
                : `'${filter}' 에 해당하는 Job이 없습니다.`}
            </div>
          </div>
        )
      )}

      {/* Selected job + run panel */}
      {selectedJob && (
        <div className="panel mt-4">
          <div className="panel-header">
            <span className="panel-title">선택된 프로젝트: {selectedJob.name || selectedJob.fullName}</span>
            {running ? (
              <button onClick={stopAnalysis} style={{ color: 'var(--danger)', borderColor: 'var(--danger)' }}>
                중단
              </button>
            ) : (
              <button className="btn-primary" onClick={runAnalysis}>
                동기화 & 분석 실행
              </button>
            )}
          </div>

          {/* Manual SCM override: only shown when >1 registry exists so the
              user can disambiguate. Default (empty string) = auto-match. */}
          {scmChoices.length > 1 && (
            <div style={{ padding: 'var(--sp-2)', display: 'flex', alignItems: 'center', gap: 8, fontSize: 'var(--text-sm)' }}>
              <label htmlFor="scm-override" style={{ color: 'var(--text-muted)' }}>SCM 매핑:</label>
              <select
                id="scm-override"
                value={manualScmId}
                onChange={e => setManualScmId(e.target.value)}
                disabled={running}
                style={{ minWidth: 200 }}
              >
                <option value="">자동 감지 (repo_url 기반)</option>
                {scmChoices.map(s => (
                  <option key={s.id} value={s.id}>{s.name || s.id}</option>
                ))}
              </select>
            </div>
          )}

          {/* Checkout failure badge — highlighted so a quiet failure doesn't
              get lost inside the progress text. */}
          {checkoutStatus && checkoutStatus.ok === false && (
            <div
              role="alert"
              style={{
                margin: 'var(--sp-2)',
                padding: 'var(--sp-2) var(--sp-3)',
                background: 'var(--color-danger-bg, #fde8e8)',
                color: 'var(--color-danger, #c81e1e)',
                border: '1px solid var(--color-danger, #c81e1e)',
                borderRadius: 4,
                fontSize: 'var(--text-sm)',
              }}
            >
              ⚠ SCM 체크아웃 실패: <strong>{checkoutStatus.error}</strong>
              {' '}— 소스 디렉토리가 비어 있어 이후 단계에서 실패할 수 있습니다.
              설정 탭에서 DEVOPS_SCM_PASSWORD 또는 해당 레지스트리의 scm_password_env를 확인하세요.
            </div>
          )}

          {/* Pipeline steps — horizontal progress bar */}
          {(running || Object.keys(stepStates).length > 0) && (
            <div className="sync-progress">
              {STEPS.map(s => {
                const state = stepStates[s.id] || 'pending';
                return (
                  <div
                    key={s.id}
                    className={`sync-segment${
                      state === 'done'   ? ' seg-done'   :
                      state === 'active' ? ' seg-active' :
                      state === 'error'  ? ' seg-error'  : ''
                    }`}
                    title={stepMsgs[s.id] || s.label}
                  >
                    <span className="seg-icon">
                      {state === 'active'
                        ? <span className="spinner" style={{ display: 'inline-block', width: 12, height: 12 }} />
                        : stepIcon(state)}
                    </span>
                    <span className="seg-label">{s.label}</span>
                  </div>
                );
              })}
            </div>
          )}

          {/* Results */}
          {result && <ResultPanel result={result} />}
        </div>
      )}
    </div>
  );
}
