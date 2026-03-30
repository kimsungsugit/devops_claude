import { useState, useCallback } from 'react';
import { post, api, defaultCacheRoot } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';

async function pollUdsProgress(jobUrl, buildSelector, jobId, { onMsg, signal }) {
  while (true) {
    if (signal?.aborted) return null;
    await new Promise(r => setTimeout(r, 2000));
    const data = await api(
      `/api/jenkins/progress?action=uds` +
      `&job_url=${encodeURIComponent(jobUrl)}` +
      `&build_selector=${encodeURIComponent(buildSelector)}` +
      `&job_id=${encodeURIComponent(jobId)}`
    );
    const p = data?.progress || {};
    if (p.message || p.stage) onMsg(p.message || p.stage);
    if (p.progress != null) onMsg(`${p.message || ''} (${p.progress}%)`);
    if (p.done || p.error) return p;
  }
}

export default function DocGenSection({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;

  const [udsList, setUdsList] = useState([]);
  const [stsList, setStsList] = useState([]);
  const [sutsList, setSutsList] = useState([]);
  const [generating, setGenerating] = useState(false);
  const [genLog, setGenLog] = useState('');
  const [genProgress, setGenProgress] = useState(null);

  const docPaths = (() => {
    try { return JSON.parse(localStorage.getItem('devops_v2_doc_paths') || '{}'); } catch (_) { return {}; }
  })();

  const base = { job_url: job?.url, cache_root: cacheRoot, build_selector: cfg.buildSelector || 'lastSuccessfulBuild' };

  const loadLists = useCallback(async () => {
    const qs = `job_url=${encodeURIComponent(job?.url ?? '')}&cache_root=${encodeURIComponent(cacheRoot ?? '')}`;
    const [u, s, su] = await Promise.allSettled([
      api(`/api/jenkins/uds/list?${qs}`),
      api(`/api/jenkins/sts/list?${qs}`),
      api(`/api/jenkins/suts/list?${qs}`),
    ]);
    if (u.status === 'fulfilled') setUdsList(u.value?.files ?? u.value ?? []);
    if (s.status === 'fulfilled') setStsList(s.value?.files ?? s.value ?? []);
    if (su.status === 'fulfilled') setSutsList(su.value?.files ?? su.value ?? []);
  }, [job, cfg, cacheRoot]);

  const generateUds = useCallback(async () => {
    if (!job?.url) { toast('warning', '프로젝트를 먼저 선택하세요.'); return; }
    setGenerating(true);
    setGenLog('UDS 생성 시작...\n');
    setGenProgress(null);

    try {
      const formData = new FormData();
      formData.append('job_url', job.url);
      formData.append('cache_root', cacheRoot);
      formData.append('build_selector', cfg.buildSelector || 'lastSuccessfulBuild');
      if (docPaths.template) formData.append('uds_template_path', docPaths.template);

      const res = await fetch('/api/jenkins/uds/generate-async', {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `HTTP ${res.status}`);
      }
      const data = await res.json();
      if (!data?.job_id) throw new Error('UDS job_id를 받지 못했습니다.');

      setGenLog(prev => prev + `Job ID: ${data.job_id}\n폴링 시작...\n`);

      const progress = await pollUdsProgress(job.url, cfg.buildSelector || 'lastSuccessfulBuild', data.job_id, {
        onMsg: msg => {
          setGenLog(prev => prev + msg + '\n');
          if (msg.includes('%')) {
            const match = msg.match(/(\d+)%/);
            if (match) setGenProgress(Number(match[1]));
          }
        },
        signal: null,
      });

      if (progress?.error) throw new Error(progress.error);

      toast('success', 'UDS 생성 완료');
      setGenLog(prev => prev + '✓ 완료\n');
      loadLists();
    } catch (e) {
      toast('error', `UDS 생성 실패: ${e.message}`);
      setGenLog(prev => prev + `✕ 오류: ${e.message}\n`);
    } finally {
      setGenerating(false);
    }
  }, [job, cfg, cacheRoot, docPaths.template, toast, loadLists]);

  const DocList = ({ title, files }) => (
    <div style={{ marginBottom: 12 }}>
      <div className="row" style={{ marginBottom: 6 }}>
        <span style={{ fontWeight: 700, fontSize: 13 }}>{title}</span>
        <StatusBadge tone={files.length > 0 ? 'success' : 'neutral'}>{files.length}개</StatusBadge>
      </div>
      {files.length > 0 ? (
        <div className="artifact-list">
          {files.slice(0, 10).map((f, i) => {
            const name = typeof f === 'string' ? f : (f.name ?? f.filename ?? f.path ?? String(f));
            return (
              <div key={i} className="artifact-item">
                <span className="artifact-icon">📝</span>
                <span className="artifact-name">{name}</span>
                {typeof f === 'object' && f.version && (
                  <span className="pill pill-info">v{f.version}</span>
                )}
                {typeof f === 'object' && f.quality_score != null && (
                  <span className={`pill ${f.quality_score >= 80 ? 'pill-success' : f.quality_score >= 60 ? 'pill-warning' : 'pill-danger'}`}>
                    Q{f.quality_score}
                  </span>
                )}
                {typeof f === 'object' && f.path && (
                  <a
                    href={`/download/${encodeURIComponent(f.path)}`}
                    download
                    style={{ fontSize: 11, color: 'var(--accent)', textDecoration: 'none' }}
                  >↓</a>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="text-muted text-sm">생성된 {title} 없음</div>
      )}
    </div>
  );

  return (
    <div>
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">📝 문서 생성</span>
          <button className="btn-sm" onClick={loadLists}>목록 새로고침</button>
          <button className="btn-primary btn-sm" onClick={generateUds} disabled={generating}>
            {generating ? <><span className="spinner" style={{ display: 'inline-block', marginRight: 4 }} />생성 중...</> : '▶ UDS 생성'}
          </button>
        </div>

        {generating && (
          <div style={{ marginBottom: 12 }}>
            {genProgress != null && (
              <div className="row" style={{ marginBottom: 6 }}>
                <span className="text-sm">{genProgress}%</span>
                <div className="progress-bar" style={{ flex: 1 }}>
                  <div className="progress-fill" style={{ width: `${genProgress}%` }} />
                </div>
              </div>
            )}
            <div className="log-box" style={{ maxHeight: 200 }}>{genLog}</div>
          </div>
        )}

        <DocList title="UDS" files={udsList} />
        <DocList title="STS" files={stsList} />
        <DocList title="SUTS" files={sutsList} />
      </div>
    </div>
  );
}
