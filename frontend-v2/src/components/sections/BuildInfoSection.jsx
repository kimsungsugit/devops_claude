import { useState, useCallback, useMemo, useEffect } from 'react';
import { post } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';
import { buildTone, defaultCacheRoot } from '../../api.js';
import { pickScmForJob } from '../../projectLoader.js';

/** Format milliseconds into a human-readable duration string */
function fmtDuration(ms) {
  if (!ms || ms <= 0) return '-';
  const totalSec = Math.round(ms / 1000);
  if (totalSec < 60) return `${totalSec}s`;
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  if (m < 60) return s > 0 ? `${m}m ${s}s` : `${m}m`;
  const h = Math.floor(m / 60);
  const rm = m % 60;
  return rm > 0 ? `${h}h ${rm}m` : `${h}h`;
}

/** Build a short trend string from recent builds (most recent first) */
function buildTrendIndicator(builds, max = 8) {
  if (!builds || builds.length === 0) return null;
  const icons = builds.slice(0, max).map(b => {
    const r = String(b.result ?? '').toUpperCase();
    if (r === 'SUCCESS') return '\u2705';
    if (r === 'FAILURE') return '\u274C';
    if (r === 'UNSTABLE') return '\u26A0\uFE0F';
    if (r === 'ABORTED') return '\u23F9\uFE0F';
    return '\u23F3'; // in progress / unknown
  });
  return icons.join(' ');
}

/** Highlight search matches in a text string, returning React nodes */
function highlightMatches(text, term) {
  if (!term) return text;
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const regex = new RegExp(`(${escaped})`, 'gi');
  const parts = text.split(regex);
  return parts.map((part, i) =>
    regex.test(part) ? (
      <mark key={i} style={{ background: 'var(--warning)', color: 'var(--text)', borderRadius: 2, padding: '0 1px' }}>{part}</mark>
    ) : part
  );
}

export default function BuildInfoSection({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const [builds, setBuilds] = useState([]);
  const [loading, setLoading] = useState(false);
  const [logContent, setLogContent] = useState('');
  const [logLoading, setLogLoading] = useState(false);
  const [logSearch, setLogSearch] = useState('');

  const rd = analysisResult?.reportData;
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;
  // scm_id — 빌드 목록에 per-build SVN revision을 붙이려면 백엔드가 SCM(svn_url/creds)을 알아야
  // 한다. 결과에 담긴 matchedScm 우선, 없으면 job↔registry 매칭·impact 메타 순으로 해석.
  const scmId = analysisResult?.matchedScm?.id
    || pickScmForJob(analysisResult?.scmList, job?.url)?.id
    || analysisResult?.impactData?.trigger?.scm_id
    || '';

  // Build steps from reportData (support multiple possible paths)
  const buildSteps = rd?.kpis?.build?.steps ?? rd?.steps ?? rd?.stages ?? null;

  // Build URL: try reportData.url, fall back to job.url with build number
  const buildUrl = rd?.url || (rd?.build_number && job?.url
    ? `${job.url.replace(/\/$/, '')}/${rd.build_number}/`
    : null);

  const [buildPage, setBuildPage] = useState(0);
  const PAGE_SIZE = 10;

  const loadBuilds = useCallback(async () => {
    setLoading(true);
    try {
      const data = await post('/api/jenkins/builds', {
        job_url: job.url,
        username: cfg.username,
        api_token: cfg.token,
        // scm_id를 주면 백엔드가 빌드별 SVN revision(빌드 시각→svn 날짜-revision)을 붙여준다.
        scm_id: scmId,
        limit: 100,
        verify_tls: cfg.verifyTls,
      });
      setBuilds(Array.isArray(data) ? data : (data.builds ?? []));
      setBuildPage(0);
    } catch (e) {
      toast('error', `빌드 목록 조회 실패: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [job, cfg, toast, scmId]);

  // Auto-load builds on mount
  useEffect(() => {
    if (job?.url && cfg.username && cfg.token && builds.length === 0) {
      loadBuilds();
    }
  }, [job?.url]); // eslint-disable-line react-hooks/exhaustive-deps

  const pagedBuilds = builds.slice(buildPage * PAGE_SIZE, (buildPage + 1) * PAGE_SIZE);
  const totalPages = Math.ceil(builds.length / PAGE_SIZE);

  // 빌드 히스토리 결과 서머리(롤업) — 성공/실패 집계 + 리비전 범위·고유 종수. distinct===1이면
  // 모든 빌드가 같은 revision으로 잡힌 것(리비전 해석 문제 신호)이라 경고한다.
  const rollup = useMemo(() => {
    const revs = builds.map(b => Number(b?.revision)).filter(n => Number.isFinite(n));
    let success = 0, failure = 0;
    for (const b of builds) {
      const r = String(b?.result ?? '').toUpperCase();
      if (r === 'SUCCESS') success += 1;
      else if (r === 'FAILURE') failure += 1;
    }
    return {
      total: builds.length, success, failure,
      hasRev: revs.length > 0,
      minRev: revs.length ? Math.min(...revs) : null,
      maxRev: revs.length ? Math.max(...revs) : null,
      distinct: new Set(revs).size,
    };
  }, [builds]);

  const loadLog = useCallback(async () => {
    setLogLoading(true);
    try {
      // Use report/summary's source path to read analysis_summary as log
      const data = await post('/api/jenkins/report/summary', {
        job_url: job.url,
        cache_root: cacheRoot,
        build_selector: cfg.buildSelector || 'lastSuccessfulBuild',
      });
      // Build a readable log from status data
      const status = data?.kpis?.build || {};
      const steps = status.steps || [];
      const lines = [];
      lines.push(`=== 빌드 정보 ===`);
      lines.push(`Job: ${job.url}`);
      lines.push(`빌드 번호: #${status.build_number || '?'}`);
      lines.push(`결과: ${status.result || '?'}`);
      lines.push(`일시: ${status.timestamp ? new Date(status.timestamp).toLocaleString('ko-KR') : '?'}`);
      lines.push(`빌드 URL: ${status.build_url || ''}`);
      lines.push('');
      if (steps.length > 0) {
        lines.push(`=== 빌드 단계 (${steps.length}개) ===`);
        steps.forEach((s, i) => {
          lines.push(`  [${i + 1}] ${s.name || s.step_id || '?'} → ${s.status || '?'} ${s.note ? `(${s.note})` : ''}`);
        });
        lines.push('');
      }
      // Add scan/coverage/test summary
      const cov = data?.kpis?.coverage || {};
      const tests = data?.kpis?.tests || {};
      const scan = data?.kpis?.scan || {};
      const prqa = data?.kpis?.prqa || {};
      lines.push('=== 품질 지표 ===');
      if (cov.line_rate != null) lines.push(`  Line Coverage: ${Math.round(cov.line_rate * 100)}%`);
      if (cov.branch_rate != null) lines.push(`  Branch Coverage: ${Math.round(cov.branch_rate * 100)}%`);
      if (tests.ok != null) lines.push(`  테스트: ${tests.ok ? 'PASS' : 'FAIL'}`);
      if (scan.files_total != null) lines.push(`  스캔 파일: ${scan.files_total}개 (FAIL:${scan.fail || 0} ERROR:${scan.error || 0} WARN:${scan.warn || 0})`);
      if (prqa.rule_violation_count != null) lines.push(`  PRQA 위반: ${prqa.rule_violation_count}건 (준수율: ${prqa.project_compliance_index ?? '?'}%)`);
      lines.push('');
      // Artifacts
      const arts = data?.artifacts || {};
      const artCount = Object.values(arts).reduce((s, v) => s + (Array.isArray(v) ? v.length : 0), 0);
      if (artCount > 0) {
        lines.push(`=== 아티팩트 (${artCount}개) ===`);
        Object.entries(arts).forEach(([type, list]) => {
          if (Array.isArray(list)) list.forEach(f => {
            const name = (f.path || f.title || '').split(/[\\/]/).pop();
            lines.push(`  [${type.toUpperCase()}] ${name}`);
          });
        });
      }
      setLogContent(lines.join('\n'));
    } catch (e) {
      toast('error', `로그 조회 실패: ${e.message}`);
    } finally {
      setLogLoading(false);
    }
  }, [job, cfg, cacheRoot, toast]);

  /** Filter log lines by search term */
  const filteredLogLines = useMemo(() => {
    if (!logContent) return [];
    const lines = logContent.split('\n');
    if (!logSearch.trim()) return lines;
    const term = logSearch.trim().toLowerCase();
    return lines.filter(line => line.toLowerCase().includes(term));
  }, [logContent, logSearch]);

  /** Download log content as a text file */
  const downloadLog = useCallback(() => {
    if (!logContent) return;
    const blob = new Blob([logContent], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `build-${rd?.build_number ?? 'log'}.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [logContent, rd?.build_number]);

  /** Resolve step status CSS class */
  const stepClass = (status) => {
    const s = String(status ?? '').toUpperCase();
    if (s === 'SUCCESS' || s === 'COMPLETED' || s === 'DONE') return 'step-done';
    if (s === 'FAILURE' || s === 'FAILED' || s === 'ERROR') return 'step-error';
    if (s === 'IN_PROGRESS' || s === 'RUNNING' || s === 'ACTIVE') return 'step-active';
    return '';
  };

  const stepIcon = (status) => {
    const s = String(status ?? '').toUpperCase();
    if (s === 'SUCCESS' || s === 'COMPLETED' || s === 'DONE') return '\u2705';
    if (s === 'FAILURE' || s === 'FAILED' || s === 'ERROR') return '\u274C';
    if (s === 'IN_PROGRESS' || s === 'RUNNING' || s === 'ACTIVE') return '\u23F3';
    if (s === 'SKIPPED') return '\u23ED\uFE0F';
    return '\u2B1C';
  };

  const trend = buildTrendIndicator(builds);

  return (
    <div>
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">{'\uD83D\uDD28'} 빌드 정보</span>
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
              { label: '빌드 소요 시간', value: rd.duration ? fmtDuration(rd.duration) : undefined },
            ].filter(f => f.value != null).map(({ label, value, mono }) => (
              <div className="field" key={label}>
                <label>{label}</label>
                <div style={{ fontSize: 13, fontFamily: mono ? 'monospace' : undefined, wordBreak: 'break-all' }}>{value}</div>
              </div>
            ))}

            {/* Build URL as clickable link */}
            {buildUrl && (
              <div className="field">
                <label>빌드 URL</label>
                <div style={{ fontSize: 13, wordBreak: 'break-all' }}>
                  <a href={buildUrl} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent)', textDecoration: 'underline' }}>
                    {buildUrl}
                  </a>
                </div>
              </div>
            )}
          </div>
        ) : (
          <div className="text-muted text-sm">대시보드에서 분석을 먼저 실행하세요.</div>
        )}
      </div>

      {/* Build stages/steps */}
      {buildSteps && Array.isArray(buildSteps) && buildSteps.length > 0 && (
        <div className="panel mt-3">
          <div className="panel-header">
            <span className="panel-title">빌드 단계</span>
            <span className="text-muted text-sm">{buildSteps.length}개 단계</span>
          </div>
          <div className="pipeline-steps">
            {buildSteps.map((step, idx) => (
              <div className={`pipeline-step ${stepClass(step.status ?? step.result)}`} key={step.name ?? idx}>
                <span className="step-icon">{stepIcon(step.status ?? step.result)}</span>
                <span className="step-label">{step.name ?? step.displayName ?? `Step ${idx + 1}`}</span>
                {step.duration != null && (
                  <span className="step-msg">{fmtDuration(step.duration ?? step.durationMillis)}</span>
                )}
                {!step.duration && step.durationMillis != null && (
                  <span className="step-msg">{fmtDuration(step.durationMillis)}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Build history */}
      <div className="panel mt-3">
        <div className="panel-header">
          <span className="panel-title">빌드 이력</span>
          <button onClick={loadBuilds} disabled={loading} className="btn-sm">
            {loading ? <span className="spinner" /> : '불러오기'}
          </button>
        </div>

        {/* Trend indicator */}
        {trend && (
          <div style={{ padding: '6px 0 2px', fontSize: 'var(--text-md)' }}>
            <span className="text-muted text-sm" style={{ marginRight: 6 }}>최근 트렌드:</span>
            <span style={{ letterSpacing: 2 }}>{trend}</span>
          </div>
        )}

        {/* 결과 서머리 롤업 — 성공/실패 + 리비전 범위·고유 종수(빌드별 SVN revision) */}
        {rollup.total > 0 && (
          <div className="text-sm" style={{ padding: '2px 0 6px' }}>
            <span className="text-muted">총 {rollup.total}빌드</span>
            <span style={{ margin: '0 6px', color: 'var(--color-success, #16a34a)' }}>성공 {rollup.success}</span>
            <span style={{ marginRight: 6, color: 'var(--color-danger, #dc2626)' }}>실패 {rollup.failure}</span>
            {rollup.hasRev && (
              <span className="text-muted">· 리비전 r{rollup.minRev}→r{rollup.maxRev} · 고유 {rollup.distinct}종</span>
            )}
            {rollup.hasRev && rollup.distinct === 1 && (
              <span style={{ color: 'var(--color-warning)', marginLeft: 6 }}>⚠ 모든 빌드가 같은 리비전 — 리비전 해석 확인 필요</span>
            )}
          </div>
        )}

        {builds.length > 0 ? (
          <>
            <table className="impact-table">
              <thead>
                <tr><th>#</th><th>리비전</th><th>결과</th><th>일시</th><th>소요 시간</th></tr>
              </thead>
              <tbody>
                {pagedBuilds.map(b => (
                  <tr key={b.number}>
                    <td style={{ fontWeight: 700 }}>#{b.number}</td>
                    <td className="text-sm" style={{ fontFamily: 'monospace' }} title="빌드 시각 기준 실제 checkout SVN revision">{b.revision ? `r${b.revision}` : '—'}</td>
                    <td><StatusBadge tone={buildTone(b.result)}>{b.result ?? 'IN PROGRESS'}</StatusBadge></td>
                    <td className="text-sm">{b.timestamp ? new Date(b.timestamp).toLocaleString('ko-KR') : '-'}</td>
                    <td className="text-sm">{fmtDuration(b.duration)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {/* Pagination */}
            {totalPages > 1 && (
              <div className="row" style={{ justifyContent: 'center', gap: 6, marginTop: 8 }}>
                <button className="btn-sm" onClick={() => setBuildPage(0)} disabled={buildPage === 0}>«</button>
                <button className="btn-sm" onClick={() => setBuildPage(p => p - 1)} disabled={buildPage === 0}>‹</button>
                <span className="text-sm" style={{ padding: '4px 8px' }}>
                  {buildPage + 1} / {totalPages} ({builds.length}건)
                </span>
                <button className="btn-sm" onClick={() => setBuildPage(p => p + 1)} disabled={buildPage >= totalPages - 1}>›</button>
                <button className="btn-sm" onClick={() => setBuildPage(totalPages - 1)} disabled={buildPage >= totalPages - 1}>»</button>
              </div>
            )}
          </>
        ) : (
          <div className="text-muted text-sm">불러오기 버튼을 클릭하세요.</div>
        )}
      </div>

      {/* Build log */}
      <div className="panel mt-3">
        <div className="panel-header">
          <span className="panel-title">빌드 로그</span>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            {logContent && (
              <button onClick={downloadLog} className="btn-sm" title="로그 다운로드">
                {'\u2B07\uFE0F'} 다운로드
              </button>
            )}
            <button onClick={loadLog} disabled={logLoading} className="btn-sm">
              {logLoading ? <span className="spinner" /> : '로그 보기'}
            </button>
          </div>
        </div>

        {/* Log search/filter */}
        {logContent && (
          <div style={{ marginTop: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
            <input
              type="text"
              placeholder="로그 검색 (필터링)..."
              value={logSearch}
              onChange={e => setLogSearch(e.target.value)}
              style={{ maxWidth: 360, fontSize: 'var(--text-sm)' }}
            />
            {logSearch.trim() && (
              <span className="text-muted text-sm" style={{ marginLeft: 8 }}>
                {filteredLogLines.length}건 일치
              </span>
            )}
          </div>
        )}

        {logContent ? (
          <div className="log-box">
            {filteredLogLines.map((line, i) => (
              <div key={i}>{logSearch.trim() ? highlightMatches(line, logSearch.trim()) : line}</div>
            ))}
            {logSearch.trim() && filteredLogLines.length === 0 && (
              <div className="text-muted">검색 결과가 없습니다.</div>
            )}
          </div>
        ) : (
          <div className="text-muted text-sm">로그 보기 버튼을 클릭하세요.</div>
        )}
      </div>
    </div>
  );
}
