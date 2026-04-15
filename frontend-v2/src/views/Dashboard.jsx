import { useState, useCallback, useRef, useEffect } from 'react';
import { post, api, defaultCacheRoot } from '../api.js';
import { useToast, useJenkinsCfg, useJob } from '../App.jsx';
import JobCard from '../components/JobCard.jsx';
import ResultPanel from '../components/ResultPanel.jsx';

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
    if (signal?.aborted) throw new Error('AbortError');
    await new Promise(r => setTimeout(r, 2000));
    const data = await api(
      `/api/jenkins/progress?action=${encodeURIComponent(action)}` +
      `&job_url=${encodeURIComponent(jobUrl)}` +
      `&build_selector=${encodeURIComponent(buildSelector)}` +
      `&job_id=${encodeURIComponent(jobId)}`
    );
    const p = data?.progress || {};
    if (p.message || p.stage) onMsg(p.message || p.stage);
    if (p.done || p.error) return p;
  }
}

/** Poll impact job until completed or failed */
async function pollImpactJob(jobId, { onMsg, signal }) {
  const t0 = Date.now();
  while (true) {
    if (signal?.aborted) throw new Error('AbortError');
    await new Promise(r => setTimeout(r, 3000));
    const data = await api(`/api/scm/impact-job/${encodeURIComponent(jobId)}`);
    const job = data?.job || {};
    const elapsed = Math.round((Date.now() - t0) / 1000);
    const timeStr = elapsed > 60 ? `${Math.floor(elapsed / 60)}분 ${elapsed % 60}초` : `${elapsed}초`;
    const msg = job.message || job.stage || '';
    onMsg(`${msg} (${timeStr} 경과)`);
    if (job.status === 'completed') {
      const resultData = await api(`/api/scm/impact-job/${encodeURIComponent(jobId)}/result`);
      return resultData?.result || {};
    }
    if (job.status === 'failed') {
      const err = job.error?.title || job.error?.detail || '영향도 분석 실패';
      throw new Error(err);
    }
  }
}

/* ── Dashboard ────────────────────────────────────────────────────── */
export default function Dashboard({ onGoDetail }) {
  const toast = useToast();
  const { cfg } = useJenkinsCfg();
  const { selectedJob, setSelectedJob, setAnalysisResult } = useJob();

  const [jobs, setJobs] = useState([]);
  const [jobsLoading, setJobsLoading] = useState(false);
  const [filter, setFilter] = useState('');

  const [running, setRunning] = useState(false);
  const [stepStates, setStepStates] = useState({});
  const [stepMsgs, setStepMsgs] = useState({});
  const [result, setResult] = useState(null);
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
    let impactData = null;

    const updateResult = () => {
      const current = { artifacts, reportData, scmList, impactData, jobUrl, cacheRoot };
      setResult(current);
      setAnalysisResult(current);
    };

    try {
      /* Step 1: Artifact sync */
      setStep('sync', 'active', '동기화 시작 중...');
      const syncRes = await post('/api/jenkins/sync-async', {
        job_url: jobUrl,
        username: cfg.username,
        api_token: cfg.token,
        cache_root: cacheRoot,
        build_selector: buildSelector,
        verify_tls: cfg.verifyTls,
        patterns: [],
      });

      if (!syncRes?.job_id) throw new Error('sync job_id를 받지 못했습니다.');

      const syncProgress = await pollJenkinsProgress(jobUrl, buildSelector, syncRes.job_id, 'sync', {
        signal,
        onMsg: msg => setStep('sync', 'active', msg),
      });

      if (syncProgress.error) throw new Error(`동기화 실패: ${syncProgress.error}`);
      setStep('sync', 'done', '동기화 완료');

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
        if (cached && cached.buildNumber === currentBuild && cached.result) {
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

      /* Step 3: SCM list */
      setStep('scm', 'active', 'SCM 조회 중...');
      try {
        const scmData = await api('/api/scm/list');
        scmList = Array.isArray(scmData) ? scmData : (scmData.items ?? scmData.registries ?? []);
        setStep('scm', 'done', `${scmList.length}개 등록`);
      } catch (e) {
        setStep('scm', 'error', e.message);
      }
      updateResult();

      /* Step 4: Impact analysis */
      if (scmList.length > 0) {
        setStep('impact', 'active', '영향도 분석 시작 중...');
        const scm = scmList[0];
        try {
          const triggerRes = await post('/api/jenkins/impact/trigger-async', {
            scm_id: scm.id,
            build_number: reportData?.build_number ?? 0,
            job_url: jobUrl,
            base_ref: scm.base_ref || '',
            targets: ['uds', 'suts', 'sits', 'sts', 'sds'],
          });

          if (!triggerRes?.job_id) throw new Error('impact job_id를 받지 못했습니다.');

          impactData = await pollImpactJob(triggerRes.job_id, {
            signal,
            onMsg: msg => setStep('impact', 'active', msg),
          });
          impactData._linked_docs = scm.linked_docs || {};
          impactData._scm_name = scm.name || scm.id;
          setStep('impact', 'done', '완료');
        } catch (e) {
          if (e.message === 'AbortError') throw e;
          setStep('impact', 'error', e.message);
          impactData = null;
        }
      } else {
        setStep('impact', 'done', 'SCM 미등록 — 건너뜀');
      }

      updateResult();

      const bn = reportData?.build_number;
      if (bn) {
        cacheRef.current[jobUrl] = {
          buildNumber: bn,
          result: { artifacts, reportData, scmList, impactData, jobUrl, cacheRoot },
          timestamp: Date.now(),
        };
      }
      toast('success', '분석이 완료되었습니다.');
    } catch (e) {
      if (e.message !== 'AbortError') {
        toast('error', `분석 중 오류: ${e.message}`);
      }
    } finally {
      setRunning(false);
    }
  }, [selectedJob, cfg, toast, setAnalysisResult]);

  autoRunRef.current = runAnalysis;

  const stopAnalysis = () => {
    abortRef.current?.abort();
    setRunning(false);
  };

  const jobName = (j) => j.name || j.fullName || '';
  const filtered = jobs.filter(j =>
    !filter || jobName(j).toLowerCase().includes(filter.toLowerCase())
  );

  /* Stats */
  const successCount = jobs.filter(j => (j.color || '').includes('blue')).length;
  const failCount    = jobs.filter(j => (j.color || '').includes('red')).length;

  return (
    <div>
      {/* Stats */}
      {jobs.length > 0 && (
        <div className="stats-row">
          <div className="stat-card">
            <div className="stat-value">{jobs.length}</div>
            <div className="stat-label">전체 Job</div>
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
            <div className="stat-value">{jobs.length - successCount - failCount}</div>
            <div className="stat-label">기타</div>
          </div>
        </div>
      )}

      {/* Toolbar */}
      <div className="toolbar">
        <span className="toolbar-title">Jenkins 프로젝트</span>
        <input
          type="text"
          placeholder="Job 이름 필터..."
          value={filter}
          onChange={e => setFilter(e.target.value)}
          autoComplete="off"
          style={{ width: 200 }}
        />
        <div className="toolbar-spacer" />
        <button onClick={loadJobs} disabled={jobsLoading}>
          {jobsLoading ? <><span className="spinner" style={{ display: 'inline-block', marginRight: 6 }} /> 조회 중...</> : 'Job 목록 불러오기'}
        </button>
      </div>

      {/* Job cards */}
      {filtered.length > 0 ? (
        <div className="job-grid">
          {filtered.map(job => (
            <JobCard
              key={job.url || job.name}
              job={job}
              selected={selectedJob?.url === job.url}
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

          {/* Pipeline steps */}
          {(running || Object.keys(stepStates).length > 0) && (
            <div className="pipeline-steps">
              {STEPS.map(s => {
                const state = stepStates[s.id] || 'pending';
                return (
                  <div
                    key={s.id}
                    className={`pipeline-step${
                      state === 'done'   ? ' step-done'   :
                      state === 'active' ? ' step-active' :
                      state === 'error'  ? ' step-error'  : ''
                    }`}
                  >
                    <span className="step-icon">
                      {state === 'active'
                        ? <span className="spinner" style={{ display: 'inline-block' }} />
                        : stepIcon(state)}
                    </span>
                    <span className="step-label">{s.label}</span>
                    {stepMsgs[s.id] && (
                      <span className="step-msg">{stepMsgs[s.id]}</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* Results */}
          {result && <ResultPanel result={result} onGoDetail={onGoDetail} />}
        </div>
      )}
    </div>
  );
}
