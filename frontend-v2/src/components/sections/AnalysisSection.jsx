import { useState, useCallback } from 'react';
import { post } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';
import { defaultCacheRoot } from '../../api.js';

export default function AnalysisSection({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;

  const [complexity, setComplexity] = useState(null);
  const [complexityLoading, setComplexityLoading] = useState(false);
  const [docs, setDocs] = useState(null);
  const [docsLoading, setDocsLoading] = useState(false);

  const loadComplexity = useCallback(async () => {
    setComplexityLoading(true);
    try {
      const data = await post('/api/jenkins/report/complexity', {
        job_url: job.url,
        cache_root: cacheRoot,
        build_selector: cfg.buildSelector,
      });
      setComplexity(data);
    } catch (e) {
      toast('error', `복잡도 조회 실패: ${e.message}`);
    } finally {
      setComplexityLoading(false);
    }
  }, [job, cfg, cacheRoot, toast]);

  const loadDocs = useCallback(async () => {
    setDocsLoading(true);
    try {
      const data = await post('/api/jenkins/report/docs', {
        job_url: job.url,
        cache_root: cacheRoot,
        build_selector: cfg.buildSelector,
      });
      setDocs(data);
    } catch (e) {
      toast('error', `문서 목록 조회 실패: ${e.message}`);
    } finally {
      setDocsLoading(false);
    }
  }, [job, cfg, cacheRoot, toast]);

  const rd = analysisResult?.reportData;
  const rows = complexity?.rows ?? complexity?.functions ?? [];
  const qualityCfg = (() => {
    try { return JSON.parse(localStorage.getItem('devops_v2_quality') || '{}'); } catch (_) { return {}; }
  })();
  const threshold = qualityCfg.complexity ?? 15;

  // coverage may be a number (%) or an object {line_rate, branch_rate, ...}
  const coveragePct = (() => {
    const c = rd?.coverage;
    if (c == null) return null;
    if (typeof c === 'number') return c;
    if (typeof c === 'object' && c.line_rate != null) return Math.round(c.line_rate * 100);
    return null;
  })();

  return (
    <div>
      {/* Summary stats from report */}
      {rd && (
        <div className="stats-row">
          {coveragePct != null && (
            <div className="stat-card">
              <div className="stat-value">{coveragePct.toFixed(1)}%</div>
              <div className="stat-label">코드 커버리지</div>
            </div>
          )}
          {rd.qac_violations != null && (
            <div className="stat-card">
              <div className="stat-value" style={{ color: rd.qac_violations > 0 ? 'var(--color-warning)' : 'var(--color-success)' }}>{rd.qac_violations}</div>
              <div className="stat-label">QAC 위반</div>
            </div>
          )}
          {rd.function_count != null && (
            <div className="stat-card">
              <div className="stat-value">{rd.function_count}</div>
              <div className="stat-label">함수 수</div>
            </div>
          )}
        </div>
      )}

      {/* Complexity */}
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">📊 복잡도 분석</span>
          <button className="btn-sm" onClick={loadComplexity} disabled={complexityLoading}>
            {complexityLoading ? <span className="spinner" /> : '불러오기'}
          </button>
        </div>
        {rows.length > 0 ? (
          <table className="impact-table">
            <thead>
              <tr><th>함수</th><th>파일</th><th>복잡도</th></tr>
            </thead>
            <tbody>
              {rows.slice(0, 30).map((r, i) => (
                <tr key={i}>
                  <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{r.function ?? r.name ?? '-'}</td>
                  <td className="text-sm" style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.file ?? r.path ?? '-'}</td>
                  <td>
                    <StatusBadge tone={(r.complexity ?? r.cc ?? 0) > threshold ? 'danger' : (r.complexity ?? r.cc ?? 0) > threshold * 0.7 ? 'warning' : 'success'}>
                      {r.complexity ?? r.cc ?? '-'}
                    </StatusBadge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="text-muted text-sm">불러오기 버튼을 클릭하세요.</div>
        )}
      </div>

      {/* Docs */}
      <div className="panel mt-3">
        <div className="panel-header">
          <span className="panel-title">📄 문서 목록</span>
          <button className="btn-sm" onClick={loadDocs} disabled={docsLoading}>
            {docsLoading ? <span className="spinner" /> : '불러오기'}
          </button>
        </div>
        {docs ? (
          <div className="log-box" style={{ maxHeight: 300 }}>
            {typeof docs === 'string' ? docs : JSON.stringify(docs, null, 2)}
          </div>
        ) : (
          <div className="text-muted text-sm">불러오기 버튼을 클릭하세요.</div>
        )}
      </div>
    </div>
  );
}
