import { useState, useCallback } from 'react';
import { post } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';
import { defaultCacheRoot } from '../../api.js';

export default function SrsSdsSection({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;

  const [matrix, setMatrix] = useState(null);
  const [loading, setLoading] = useState(false);

  const docPaths = (() => {
    try { return JSON.parse(localStorage.getItem('devops_v2_doc_paths') || '{}'); } catch (_) { return {}; }
  })();

  const loadMatrix = useCallback(async () => {
    setLoading(true);
    try {
      const data = await post('/api/jenkins/uds/traceability-matrix', {
        job_url: job.url,
        cache_root: cacheRoot,
        build_selector: cfg.buildSelector,
        srs_path: docPaths.srs || '',
        sds_path: docPaths.sds || '',
      });
      setMatrix(data);
    } catch (e) {
      toast('error', `추적성 매트릭스 조회 실패: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [job, cfg, cacheRoot, docPaths.srs, docPaths.sds, toast]);

  const impactData = analysisResult?.impactData;
  const impacts = impactData?.impacts ?? impactData?.impact_items ?? [];

  return (
    <div>
      {/* Input doc status */}
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">📋 입력 문서 현황</span>
        </div>
        <div className="field-group">
          {[
            { label: 'SRS', path: docPaths.srs },
            { label: 'SDS', path: docPaths.sds },
          ].map(({ label, path }) => (
            <div key={label} className="artifact-item" style={{ background: 'var(--bg)' }}>
              <span className="pill pill-purple">{label}</span>
              {path ? (
                <span className="artifact-name">{path}</span>
              ) : (
                <span className="text-muted text-sm">설정 탭에서 경로를 입력하세요</span>
              )}
              <StatusBadge tone={path ? 'success' : 'neutral'}>{path ? '등록됨' : '미등록'}</StatusBadge>
            </div>
          ))}
        </div>
      </div>

      {/* Impact summary */}
      {impacts.length > 0 && (
        <div className="panel mt-3">
          <div className="panel-header">
            <span className="panel-title">영향받는 요구사항</span>
            <StatusBadge tone="warning">{impacts.length}건</StatusBadge>
          </div>
          <table className="impact-table">
            <thead>
              <tr><th>요구사항 ID</th><th>설명</th><th>문서</th><th>영향 수준</th></tr>
            </thead>
            <tbody>
              {impacts.map((item, i) => (
                <tr key={i}>
                  <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{item.req_id ?? item.id ?? '-'}</td>
                  <td className="text-sm">{item.description ?? item.desc ?? '-'}</td>
                  <td className="text-sm">{item.doc ?? item.document ?? '-'}</td>
                  <td>
                    <StatusBadge tone={item.level === 'high' ? 'danger' : item.level === 'medium' ? 'warning' : 'info'}>
                      {item.level ?? '-'}
                    </StatusBadge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Traceability matrix */}
      <div className="panel mt-3">
        <div className="panel-header">
          <span className="panel-title">추적성 매트릭스</span>
          <button className="btn-sm" onClick={loadMatrix} disabled={loading}>
            {loading ? <span className="spinner" /> : '매트릭스 생성'}
          </button>
        </div>
        {matrix ? (
          <TraceMatrix matrix={matrix} />
        ) : (
          <div className="text-muted text-sm">
            SRS/SDS 경로를 설정 탭에서 등록한 후 매트릭스 생성 버튼을 클릭하세요.
          </div>
        )}
      </div>
    </div>
  );
}

function TraceMatrix({ matrix }) {
  const rows = matrix?.rows ?? matrix?.items ?? matrix?.matrix ?? [];
  const summary = matrix?.summary;

  if (!rows.length) {
    return <div className="log-box">{JSON.stringify(matrix, null, 2)}</div>;
  }

  return (
    <div>
      {summary && (
        <div className="row" style={{ marginBottom: 8, flexWrap: 'wrap', gap: 6 }}>
          {Object.entries(summary).map(([k, v]) => (
            <span key={k} className="pill pill-info">{k}: {v}</span>
          ))}
        </div>
      )}
      <table className="impact-table">
        <thead>
          <tr>
            <th>요구사항 ID</th>
            <th>함수</th>
            <th>파일</th>
            <th>상태</th>
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 50).map((r, i) => (
            <tr key={i}>
              <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{r.req_id ?? r.id ?? '-'}</td>
              <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{r.function ?? r.func ?? '-'}</td>
              <td className="text-sm">{r.file ?? r.source ?? '-'}</td>
              <td><StatusBadge tone={r.status === 'covered' ? 'success' : 'warning'}>{r.status ?? '-'}</StatusBadge></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
