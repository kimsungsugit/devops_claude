import { useState, useCallback } from 'react';
import { post } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';
import { buildTone, defaultCacheRoot } from '../../api.js';

export default function BuildInfoSection({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const [builds, setBuilds] = useState([]);
  const [loading, setLoading] = useState(false);
  const [logContent, setLogContent] = useState('');
  const [logLoading, setLogLoading] = useState(false);

  const rd = analysisResult?.reportData;
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;

  const loadBuilds = useCallback(async () => {
    setLoading(true);
    try {
      const data = await post('/api/jenkins/builds', {
        job_url: job.url,
        username: cfg.username,
        api_token: cfg.token,
        limit: 10,
        verify_tls: cfg.verifyTls,
      });
      setBuilds(Array.isArray(data) ? data : (data.builds ?? []));
    } catch (e) {
      toast('error', `빌드 목록 조회 실패: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [job, cfg, toast]);

  const loadLog = useCallback(async () => {
    setLogLoading(true);
    try {
      const data = await post('/api/jenkins/report/logs', {
        job_url: job.url,
        cache_root: cacheRoot,
        build_selector: cfg.buildSelector,
      });
      const logs = data?.logs ?? data?.content ?? data;
      setLogContent(typeof logs === 'string' ? logs : JSON.stringify(logs, null, 2));
    } catch (e) {
      toast('error', `로그 조회 실패: ${e.message}`);
    } finally {
      setLogLoading(false);
    }
  }, [job, cfg, cacheRoot, toast]);

  return (
    <div>
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">🔨 빌드 정보</span>
          {rd?.build_number && (
            <StatusBadge tone={buildTone(rd?.result)}>#{rd.build_number} {rd.result}</StatusBadge>
          )}
        </div>

        {rd ? (
          <div className="field-group">
            {[
              { label: '빌드 번호', value: rd.build_number },
              { label: '결과', value: rd.result },
              { label: '브랜치', value: rd.branch },
              { label: '커밋', value: rd.commit, mono: true },
              { label: '빌드 시각', value: rd.timestamp ? new Date(rd.timestamp).toLocaleString('ko-KR') : undefined },
              { label: '빌드 소요 시간', value: rd.duration ? `${Math.round(rd.duration / 1000)}초` : undefined },
            ].filter(f => f.value != null).map(({ label, value, mono }) => (
              <div className="field" key={label}>
                <label>{label}</label>
                <div style={{ fontSize: 13, fontFamily: mono ? 'monospace' : undefined, wordBreak: 'break-all' }}>{value}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-muted text-sm">대시보드에서 분석을 먼저 실행하세요.</div>
        )}
      </div>

      {/* Build history */}
      <div className="panel mt-3">
        <div className="panel-header">
          <span className="panel-title">빌드 이력</span>
          <button onClick={loadBuilds} disabled={loading} className="btn-sm">
            {loading ? <span className="spinner" /> : '불러오기'}
          </button>
        </div>
        {builds.length > 0 ? (
          <table className="impact-table">
            <thead>
              <tr><th>#</th><th>결과</th><th>일시</th><th>소요 시간</th></tr>
            </thead>
            <tbody>
              {builds.map(b => (
                <tr key={b.number}>
                  <td style={{ fontWeight: 700 }}>#{b.number}</td>
                  <td><StatusBadge tone={buildTone(b.result)}>{b.result ?? 'IN PROGRESS'}</StatusBadge></td>
                  <td className="text-sm">{b.timestamp ? new Date(b.timestamp).toLocaleString('ko-KR') : '-'}</td>
                  <td className="text-sm">{b.duration ? `${Math.round(b.duration / 1000)}s` : '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="text-muted text-sm">불러오기 버튼을 클릭하세요.</div>
        )}
      </div>

      {/* Build log */}
      <div className="panel mt-3">
        <div className="panel-header">
          <span className="panel-title">빌드 로그</span>
          <button onClick={loadLog} disabled={logLoading} className="btn-sm">
            {logLoading ? <span className="spinner" /> : '로그 보기'}
          </button>
        </div>
        {logContent ? (
          <div className="log-box">{logContent}</div>
        ) : (
          <div className="text-muted text-sm">로그 보기 버튼을 클릭하세요.</div>
        )}
      </div>
    </div>
  );
}
