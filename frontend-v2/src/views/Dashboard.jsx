import { useState, useCallback, useRef } from 'react';
import { post, api, colorTone, buildTone, defaultCacheRoot, fmtBytes } from '../api.js';
import { useToast, useJenkinsCfg, useJob } from '../App.jsx';
import StatusBadge from '../components/StatusBadge.jsx';

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
  while (true) {
    if (signal?.aborted) throw new Error('AbortError');
    await new Promise(r => setTimeout(r, 2500));
    const data = await api(`/api/scm/impact-job/${encodeURIComponent(jobId)}`);
    const job = data?.job || {};
    if (job.message) onMsg(job.message);
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

  const setStep = (id, state, msg = '') => {
    setStepStates(p => ({ ...p, [id]: state }));
    if (msg) setStepMsgs(p => ({ ...p, [id]: msg }));
  };

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

    try {
      /* ── Step 1: Artifact sync (job_id polling) ── */
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

      /* ── Step 2: Report data + artifact list ── */
      setStep('report', 'active', '빌드 정보 수집 중...');
      try {
        const raw = await post('/api/jenkins/report/summary', {
          job_url: jobUrl,
          cache_root: cacheRoot,
          build_selector: buildSelector,
        });
        // flatten kpis.build → top-level for UI compatibility
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
        // extract artifact list from summary
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
        // non-fatal: continue
      }

      /* ── Step 3: SCM list ── */
      setStep('scm', 'active', 'SCM 조회 중...');
      try {
        const scmData = await api('/api/scm/list');
        scmList = Array.isArray(scmData) ? scmData : (scmData.items ?? scmData.registries ?? []);
        setStep('scm', 'done', `${scmList.length}개 등록`);
      } catch (e) {
        setStep('scm', 'error', e.message);
      }

      /* ── Step 4: Impact analysis (job_id polling) ── */
      if (scmList.length > 0) {
        setStep('impact', 'active', '영향도 분석 시작 중...');
        const scm = scmList[0];
        try {
          const triggerRes = await post('/api/jenkins/impact/trigger-async', {
            scm_id: scm.id,
            build_number: reportData?.build_number ?? 0,
            job_url: jobUrl,
            targets: ['uds', 'suts', 'sits', 'sts', 'sds'],
          });

          if (!triggerRes?.job_id) throw new Error('impact job_id를 받지 못했습니다.');

          impactData = await pollImpactJob(triggerRes.job_id, {
            signal,
            onMsg: msg => setStep('impact', 'active', msg),
          });
          // attach linked_docs from SCM for display
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

      const final = { artifacts, reportData, scmList, impactData, jobUrl, cacheRoot };
      setResult(final);
      setAnalysisResult(final);
      toast('success', '분석이 완료되었습니다.');
    } catch (e) {
      if (e.message !== 'AbortError') {
        toast('error', `분석 중 오류: ${e.message}`);
      }
    } finally {
      setRunning(false);
    }
  }, [selectedJob, cfg, toast, setAnalysisResult]);

  const stopAnalysis = () => {
    abortRef.current?.abort();
    setRunning(false);
  };

  const jobName = (j) => j.name || j.fullName || '';
  const filtered = jobs.filter(j =>
    !filter || jobName(j).toLowerCase().includes(filter.toLowerCase())
  );

  /* ── Stats ── */
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
          style={{ width: 200 }}
        />
        <div className="toolbar-spacer" />
        <button onClick={loadJobs} disabled={jobsLoading}>
          {jobsLoading ? <><span className="spinner" style={{ display: 'inline-block', marginRight: 6 }} /> 조회 중...</> : '📋 Job 목록 불러오기'}
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
              }}
            />
          ))}
        </div>
      ) : (
        !jobsLoading && (
          <div className="empty-state">
            <div className="empty-icon">{jobs.length === 0 ? '🔧' : '🔍'}</div>
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
                ▶ 동기화 &amp; 분석 실행
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

/* ── Job card ─────────────────────────────────────────────────────── */
function JobCard({ job, selected, onClick }) {
  const tone = colorTone(job.color);
  const lb = job.lastBuild;
  const label = tone === 'success' ? 'SUCCESS'
    : tone === 'danger'  ? 'FAILURE'
    : tone === 'running' ? 'RUNNING'
    : tone === 'warning' ? 'UNSTABLE' : 'NONE';

  return (
    <div className={`job-card${selected ? ' selected' : ''}`} onClick={onClick}>
      <div className="job-card-header">
        <span className="job-card-name">{job.name || job.fullName}</span>
        <StatusBadge tone={tone}>{label}</StatusBadge>
      </div>
      <div className="job-card-meta">
        {lb ? (
          <>
            <span>🔢 빌드 #{lb.number}</span>
            {lb.result && <span>📊 {lb.result}</span>}
            {lb.timestamp && (
              <span>🕐 {new Date(lb.timestamp).toLocaleDateString('ko-KR')}</span>
            )}
          </>
        ) : (
          <span className="text-muted">빌드 이력 없음</span>
        )}
      </div>
    </div>
  );
}

/* ── Result panel ─────────────────────────────────────────────────── */
function ResultPanel({ result, onGoDetail }) {
  const { artifacts, reportData, impactData } = result;

  return (
    <div>
      <div className="divider" />
      <div className="result-grid">
        {/* Artifacts */}
        <div className="panel" style={{ boxShadow: 'none', background: 'var(--bg)' }}>
          <div className="panel-header">
            <span className="panel-title">📦 Jenkins 아티팩트 현황</span>
            {reportData?.build_number && (
              <StatusBadge tone={buildTone(reportData?.result)}>
                #{reportData.build_number} {reportData.result}
              </StatusBadge>
            )}
          </div>
          {reportData && (
            <div style={{ marginBottom: 8 }}>
              <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
                {reportData.branch && <span className="pill pill-info">🌿 {reportData.branch}</span>}
                {reportData.commit && (
                  <span className="pill pill-neutral" style={{ fontFamily: 'monospace' }}>
                    {reportData.commit?.slice(0, 8)}
                  </span>
                )}
              </div>
            </div>
          )}
          <ArtifactList artifacts={artifacts} reportData={reportData} />
          {artifacts.length === 0 && !reportData?.artifact_list?.length && (
            <div className="text-muted text-sm mt-2">아티팩트 없음</div>
          )}
        </div>

        {/* Impact */}
        <div className="panel" style={{ boxShadow: 'none', background: 'var(--bg)' }}>
          <div className="panel-header">
            <span className="panel-title">📄 문서 영향도</span>
          </div>
          <ImpactPanel impactData={impactData} />
        </div>
      </div>

      <div className="row mt-3" style={{ justifyContent: 'flex-end' }}>
        <button onClick={onGoDetail}>세부 데이터 보기 →</button>
      </div>
    </div>
  );
}

function ArtifactList({ artifacts, reportData }) {
  // artifacts from summary: [{type, name, path, title}, ...]
  // fallback to reportData.artifacts (object keyed by type) if needed
  let files = artifacts;
  if (!files.length && reportData?.artifacts && typeof reportData.artifacts === 'object' && !Array.isArray(reportData.artifacts)) {
    files = Object.entries(reportData.artifacts).flatMap(([type, list]) =>
      (Array.isArray(list) ? list : []).map(f => ({
        type,
        name: (f.path ?? f.title ?? '').split(/[\\/]/).pop(),
        path: f.path,
        title: f.title,
      }))
    );
  }

  if (!files.length) return null;

  const TYPE_ICON = { html: '🌐', xlsx: '📊', json: '📄', csv: '📈', md: '📝', pdf: '📋' };
  const icon = (f) => {
    if (f.type && TYPE_ICON[f.type]) return TYPE_ICON[f.type];
    const ext = String(f.name || '').split('.').pop().toLowerCase();
    return TYPE_ICON[ext] || '📄';
  };

  return (
    <div className="artifact-list">
      {files.slice(0, 30).map((f, i) => {
        const name = typeof f === 'string' ? f : (f.name || f.title || f.filename || '');
        const dlPath = typeof f === 'object' ? f.path : null;
        return (
          <div key={i} className="artifact-item">
            <span className="artifact-icon">{icon(f)}</span>
            <span className="artifact-name" title={typeof f === 'object' ? (f.title || name) : name}>
              {name.length > 55 ? `...${name.slice(-52)}` : name}
            </span>
            {f.type && <span className="pill pill-neutral" style={{ fontSize: 10 }}>{f.type.toUpperCase()}</span>}
          </div>
        );
      })}
      {files.length > 20 && (
        <div className="text-muted text-sm mt-2">외 {files.length - 20}개 파일</div>
      )}
    </div>
  );
}

const _CHANGE_TYPE_KO = {
  SIGNATURE: '시그니처', BODY: '본문', NEW: '신규', DELETE: '삭제',
  VARIABLE: '변수', HEADER: '헤더',
};

const _DOC_STATUS = {
  completed: { color: 'var(--color-success)', label: '완료' },
  auto:      { color: 'var(--color-success)', label: '자동 반영' },
  flagged:   { color: 'var(--color-warning)', label: '수동 검토 필요' },
  flag:      { color: 'var(--color-warning)', label: '수동 검토 필요' },
  skipped:   { color: 'var(--text-muted)',    label: '건너뜀' },
  error:     { color: 'var(--color-danger)',   label: '오류' },
};

function ImpactPanel({ impactData }) {
  const [openDoc, setOpenDoc] = useState(null);

  if (!impactData) {
    return (
      <div className="text-muted text-sm">
        SCM이 등록되어 있지 않거나 영향도 분석 결과가 없습니다.<br />
        설정 탭에서 SCM을 등록하면 문서 영향도를 확인할 수 있습니다.
      </div>
    );
  }

  const changedFiles = Array.isArray(impactData.changed_files) ? impactData.changed_files : [];
  const changedFunctions = impactData.changed_functions ?? impactData.changed_function_types ?? {};
  const changedFnEntries = typeof changedFunctions === 'object' && !Array.isArray(changedFunctions)
    ? Object.entries(changedFunctions) : [];
  const impact = impactData.impact || {};
  const counts = impactData.impact_counts || {
    direct: Array.isArray(impact.direct) ? impact.direct.length : (impact.direct ?? undefined),
    indirect_1hop: Array.isArray(impact.indirect_1hop) ? impact.indirect_1hop.length : (impact.indirect_1hop ?? undefined),
    indirect_2hop: Array.isArray(impact.indirect_2hop) ? impact.indirect_2hop.length : (impact.indirect_2hop ?? undefined),
  };
  const docs = impactData.documents && typeof impactData.documents === 'object' ? impactData.documents : {};
  const warnings = Array.isArray(impactData.warnings) ? impactData.warnings : [];
  const linkedDocs = impactData._linked_docs || {};
  const scmName = impactData._scm_name || '';
  const DOC_ORDER = ['uds', 'suts', 'sits', 'sts', 'sds'];
  const DOC_LABEL = { uds: 'UDS', suts: 'SUTS', sits: 'SITS', sts: 'STS', sds: 'SDS', srs: 'SRS', hsis: 'HSIS' };

  return (
    <div>
      {/* Summary badges */}
      {/* SCM info */}
      {scmName && <div className="text-sm" style={{ marginBottom: 6, fontWeight: 600 }}>SCM: {scmName}</div>}

      <div className="row" style={{ gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
        <span className="pill pill-info">파일 {changedFiles.length}</span>
        <span className="pill pill-info">함수 {changedFnEntries.length}</span>
        {counts.direct != null && (
          <span className="pill pill-warning">
            직접 {counts.direct} / 1hop {counts.indirect_1hop || 0} / 2hop {counts.indirect_2hop || 0}
          </span>
        )}
      </div>

      {/* Changed files */}
      {changedFiles.length > 0 && (
        <details style={{ marginBottom: 10 }}>
          <summary className="text-sm" style={{ cursor: 'pointer', fontWeight: 600, marginBottom: 4 }}>
            변경 파일 ({changedFiles.length})
          </summary>
          <div style={{ maxHeight: 120, overflow: 'auto' }}>
            {changedFiles.slice(0, 20).map((f, i) => (
              <div key={i} style={{ fontSize: 11, fontFamily: 'monospace', padding: '1px 0' }}>{f}</div>
            ))}
            {changedFiles.length > 20 && <div className="text-muted text-sm">외 {changedFiles.length - 20}개</div>}
          </div>
        </details>
      )}

      {/* Changed functions */}
      {changedFnEntries.length > 0 && (
        <details style={{ marginBottom: 10 }}>
          <summary className="text-sm" style={{ cursor: 'pointer', fontWeight: 600, marginBottom: 4 }}>
            변경된 함수 ({changedFnEntries.length})
          </summary>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, maxHeight: 120, overflow: 'auto' }}>
            {changedFnEntries.slice(0, 50).map(([name, type]) => (
              <span key={name} style={{ fontSize: 11, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 4, padding: '1px 6px', fontFamily: 'monospace' }}>
                {name}
                <span className="text-muted" style={{ marginLeft: 4, fontSize: 10 }}>
                  {_CHANGE_TYPE_KO[String(type).toUpperCase()] || type}
                </span>
              </span>
            ))}
          </div>
        </details>
      )}

      {/* Document-level impact */}
      {DOC_ORDER.some(k => docs[k]) ? (
        <div style={{ border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
          <div style={{ padding: '6px 8px', background: 'var(--bg)', fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', borderBottom: '1px solid var(--border)' }}>
            문서별 영향
          </div>
          {DOC_ORDER.map(k => docs[k] ? (
            <ImpactDocRow
              key={k}
              docKey={k}
              doc={docs[k]}
              open={openDoc === k}
              onToggle={() => setOpenDoc(prev => prev === k ? null : k)}
            />
          ) : null)}
        </div>
      ) : changedFiles.length === 0 && changedFnEntries.length === 0 && Object.keys(linkedDocs).length === 0 ? (
        <div className="text-muted text-sm">영향받는 항목 없음</div>
      ) : null}

      {/* Linked documents from SCM */}
      {Object.keys(linkedDocs).length > 0 && (
        <div style={{ marginTop: 10, border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
          <div style={{ padding: '6px 8px', background: 'var(--bg)', fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', borderBottom: '1px solid var(--border)' }}>
            연결된 문서 ({Object.keys(linkedDocs).length})
          </div>
          {Object.entries(linkedDocs).map(([key, path]) => {
            if (!path) return null;
            const filename = String(path).split(/[\\/]/).pop();
            return (
              <div key={key} className="row" style={{ padding: '5px 8px', gap: 8, borderBottom: '1px solid var(--border)', alignItems: 'center' }}>
                <span style={{ fontWeight: 700, width: 44, textTransform: 'uppercase', fontSize: 12, color: 'var(--accent)' }}>
                  {DOC_LABEL[key] || key.toUpperCase()}
                </span>
                <span style={{ fontSize: 11, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={path}>
                  {filename}
                </span>
                <span className="pill pill-neutral" style={{ fontSize: 9 }}>
                  {filename.split('.').pop()?.toUpperCase()}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Warnings */}
      {warnings.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary className="text-sm" style={{ cursor: 'pointer', fontWeight: 600, color: 'var(--color-warning)' }}>
            경고 ({warnings.length})
          </summary>
          <div style={{ fontSize: 11, whiteSpace: 'pre-wrap', maxHeight: 100, overflow: 'auto', marginTop: 4 }}>
            {warnings.join('\n')}
          </div>
        </details>
      )}
    </div>
  );
}

function ImpactDocRow({ docKey, doc, open, onToggle }) {
  const st = _DOC_STATUS[doc?.status] || { color: 'var(--text-muted)', label: doc?.status || '-' };
  const summary = doc?.summary || {};
  const fns = Array.isArray(doc?.flagged_functions) ? doc.flagged_functions
    : Array.isArray(doc?.changed_functions) ? doc.changed_functions.map(f => f?.function || f?.name || String(f))
    : Array.isArray(doc?.changed_cases) ? doc.changed_cases.map(f => f?.function || String(f))
    : [];
  const hasDetail = fns.length > 0;

  const metaItems = [];
  if (docKey === 'uds' && summary.changed_functions) metaItems.push(`${summary.changed_functions}개 함수 재생성`);
  if (docKey === 'suts') {
    if (summary.changed_cases != null) metaItems.push(`TC ${summary.before_cases ?? '?'}→${summary.changed_cases}`);
    if (summary.changed_sequences != null) metaItems.push(`Seq ${summary.before_sequences ?? '?'}→${summary.changed_sequences}`);
  }
  if (docKey === 'sits') {
    if (summary.test_case_count != null) metaItems.push(`TC ${summary.before_test_case_count ?? '?'}→${summary.test_case_count}`);
    if (summary.delta_cases != null) metaItems.push(`Δ${summary.delta_cases >= 0 ? '+' : ''}${summary.delta_cases} TC`);
  }
  if ((docKey === 'sts' || docKey === 'sds') && summary.flagged_functions) {
    metaItems.push(`${summary.flagged_functions}개 함수 수동 검토 필요`);
  }

  return (
    <div style={{ borderBottom: '1px solid var(--border)' }}>
      <div
        className="row"
        style={{ padding: '7px 8px', gap: 8, alignItems: 'center', cursor: hasDetail ? 'pointer' : 'default' }}
        onClick={hasDetail ? onToggle : undefined}
      >
        <span style={{ fontWeight: 700, width: 44, textTransform: 'uppercase', fontSize: 12 }}>{docKey}</span>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: st.color, flexShrink: 0 }} />
        <span style={{ color: st.color, fontSize: 12, fontWeight: 600, minWidth: 90 }}>{st.label}</span>
        <span className="text-muted" style={{ flex: 1, fontSize: 11 }}>{metaItems.join('  ·  ') || '-'}</span>
        {hasDetail && <span className="text-muted" style={{ fontSize: 11 }}>{open ? '▲' : '▼'} {fns.length}개</span>}
      </div>
      {open && hasDetail && (
        <div style={{ padding: '4px 8px 10px 60px' }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>
            {docKey === 'sts' || docKey === 'sds' ? '검토 필요 함수' : '변경 함수'}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
            {fns.slice(0, 40).map((fn, i) => (
              <span key={i} style={{ fontSize: 11, background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 4, padding: '1px 6px', fontFamily: 'monospace' }}>
                {String(fn)}
              </span>
            ))}
            {fns.length > 40 && <span className="text-muted" style={{ fontSize: 11 }}>+{fns.length - 40}개 더</span>}
          </div>
        </div>
      )}
    </div>
  );
}
