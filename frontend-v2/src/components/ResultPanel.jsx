import { useCallback, useEffect, useState } from 'react';
import StatusBadge from './StatusBadge.jsx';
import { buildTone, post } from '../api.js';

/* ── Constants ── */
const _CHANGE_TYPE_KO = {
  SIGNATURE: '시그니처', BODY: '본문', NEW: '신규', DELETE: '삭제',
  VARIABLE: '변수', HEADER: '헤더',
};

const _DOC_STATUS = {
  completed:        { color: 'var(--color-success)', label: '완료' },
  auto:             { color: 'var(--color-success)', label: '자동 반영' },
  flagged:          { color: 'var(--color-warning)', label: '수동 검토 필요' },
  flag:             { color: 'var(--color-warning)', label: '수동 검토 필요' },
  review_required:  { color: 'var(--color-warning)', label: '수동 검토 필요' },
  FLAG:             { color: 'var(--color-warning)', label: '수동 검토 필요' },
  skipped:          { color: 'var(--text-muted)',    label: '건너뜀' },
  error:            { color: 'var(--color-danger)',   label: '오류' },
};

const DOC_ORDER = ['uds', 'suts', 'sits', 'sts', 'sds'];

/* ── Quality Gate thresholds ──────────────────────────────────────────
 * ISO 26262 권장 범위에 맞춘 커버리지 기준 (단위 %).
 * Hard-coded for now — 추후 설정 탭에서 프로젝트별 오버라이드를 노출할 수 있다. */
const GATE_PASS = 80;
const GATE_WARN = 50;

export function classifyGate(pct) {
  if (pct >= GATE_PASS) return 'pass';
  if (pct >= GATE_WARN) return 'warn';
  return 'fail';
}

/* ── ResultPanel ── */
export default function ResultPanel({ result }) {
  const { artifacts, reportData, impactData } = result;
  const kpis = reportData?.kpis || {};
  const build = kpis.build || {};
  const cov = kpis.coverage || {};
  const tests = kpis.tests || {};
  const scan = kpis.scan || {};
  const fileTypes = kpis.files || {};
  const prqa = kpis.prqa || {};
  const triggerFiles = Array.isArray(impactData?.changed_files) ? impactData.changed_files
    : Array.isArray(impactData?.trigger?.changed_files) ? impactData.trigger.changed_files : [];

  /* Traceability summary (cached, fetched lazily per jobUrl) */
  const [traceSummary, setTraceSummary] = useState(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceRefreshKey, setTraceRefreshKey] = useState(0);

  const refreshTraceSummary = useCallback(() => {
    setTraceRefreshKey(k => k + 1);
  }, []);

  useEffect(() => {
    const jobUrl = result?.jobUrl;
    if (!jobUrl) {
      setTraceSummary(null);
      return;
    }
    let cancelled = false;
    setTraceLoading(true);
    post('/api/jenkins/uds/trace-summary', {
      job_url: jobUrl,
      cache_root: result?.cacheRoot || '.devops_pro_cache',
    })
      .then((data) => { if (!cancelled) setTraceSummary(data || null); })
      .catch(() => { if (!cancelled) setTraceSummary(null); })
      .finally(() => { if (!cancelled) setTraceLoading(false); });
    return () => { cancelled = true; };
  }, [result?.jobUrl, result?.cacheRoot, traceRefreshKey]);

  /* Re-fetch when dashboard tab becomes visible again (e.g., after generating matrix in SRS section) */
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible' && result?.jobUrl) {
        refreshTraceSummary();
      }
    };
    document.addEventListener('visibilitychange', onVisible);
    window.addEventListener('focus', onVisible);
    return () => {
      document.removeEventListener('visibilitychange', onVisible);
      window.removeEventListener('focus', onVisible);
    };
  }, [result?.jobUrl, refreshTraceSummary]);

  return (
    <div>
      <div className="divider" />

      <div className="result-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}>
        {/* Build & Artifact Summary */}
        <div className="panel" style={{ boxShadow: 'none', background: 'var(--bg)' }}>
          <div className="panel-header">
            <span className="panel-title">빌드 & 아티팩트 요약</span>
          </div>

          {/* Compact KPI row — integrated from top stats */}
          <div style={{ display: 'flex', gap: 'var(--sp-2)', marginBottom: 'var(--sp-3)', flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 auto', minWidth: 110, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>빌드 결과</div>
              <StatusBadge tone={buildTone(build.result || reportData?.result)}>
                #{build.build_number || reportData?.build_number || '?'} {build.result || reportData?.result || '-'}
              </StatusBadge>
            </div>
            {cov.line_rate != null && (
              <div style={{ flex: '1 1 auto', minWidth: 80, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))' }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>Line Cov</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: cov.ok ? 'var(--color-success)' : 'var(--color-danger)' }}>
                  {Math.round(cov.line_rate * 100)}%
                </div>
              </div>
            )}
            {cov.branch_rate != null && (
              <div style={{ flex: '1 1 auto', minWidth: 80, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))' }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>Branch Cov</div>
                <div style={{ fontSize: 16, fontWeight: 700, color: cov.ok ? 'var(--color-success)' : 'var(--color-danger)' }}>
                  {Math.round(cov.branch_rate * 100)}%
                </div>
              </div>
            )}
            <div style={{ flex: '1 1 auto', minWidth: 70, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>테스트</div>
              <div style={{ fontSize: 16, fontWeight: 700, color: tests.ok ? 'var(--color-success)' : 'var(--color-danger)' }}>
                {tests.ok ? 'PASS' : (tests.ok === false ? 'FAIL' : '-')}
              </div>
            </div>
            <div style={{ flex: '1 1 auto', minWidth: 70, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>아티팩트</div>
              <div style={{ fontSize: 16, fontWeight: 700 }}>{scan.files_total ?? artifacts.length ?? 0}</div>
            </div>
            {triggerFiles.length > 0 && (
              <div style={{ flex: '1 1 auto', minWidth: 80, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))' }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>변경 파일</div>
                <div style={{ fontSize: 16, fontWeight: 700 }}>{triggerFiles.length}</div>
              </div>
            )}
            {build.timestamp && (
              <div style={{ flex: '2 1 auto', minWidth: 160, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))' }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 2 }}>빌드 일시</div>
                <div style={{ fontSize: 12, fontWeight: 600 }}>{new Date(build.timestamp).toLocaleString('ko-KR')}</div>
              </div>
            )}
          </div>

          {/* File type bar chart */}
          <FileTypeChart fileTypes={fileTypes} />

          {/* PRQA */}
          <PrqaPanel prqa={prqa} />

          {/* Scan + Code Metrics + VectorCAST row */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {/* Scan */}
            <div style={{ flex: 1, minWidth: 100, padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))' }}>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>스캔 결과</div>
              {(scan.fail > 0 || scan.error > 0 || scan.warn > 0) ? (
                <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                  {scan.fail > 0 && <span className="pill pill-danger" style={{ fontSize: 10 }}>FAIL {scan.fail}</span>}
                  {scan.error > 0 && <span className="pill pill-danger" style={{ fontSize: 10 }}>ERROR {scan.error}</span>}
                  {scan.warn > 0 && <span className="pill pill-warning" style={{ fontSize: 10 }}>WARN {scan.warn}</span>}
                </div>
              ) : (
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-success)' }}>OK</div>
              )}
            </div>

            {/* Code Metrics */}
            {kpis.code_metrics?.code_files && (
              <div style={{ flex: 1, minWidth: 100, padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))' }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>코드 메트릭</div>
                <div style={{ fontSize: 11 }}>
                  <span style={{ fontWeight: 600 }}>{kpis.code_metrics.code_files}</span> 파일 · <span style={{ fontWeight: 600 }}>{kpis.code_metrics.functions}</span> 함수 · <span style={{ fontWeight: 600 }}>{kpis.code_metrics.nloc?.toLocaleString()}</span> LOC
                </div>
              </div>
            )}

            {/* VectorCAST */}
            {reportData?.tester?.vectorcast?.test_rows_count != null && (
              <div style={{ flex: 1, minWidth: 100, padding: '8px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))' }}>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>VectorCAST</div>
                <div style={{ fontSize: 11 }}>
                  <span style={{ fontWeight: 600 }}>{reportData.tester.vectorcast.test_rows_count?.toLocaleString()}</span> TC · UT {(reportData.tester.vectorcast.ut_reports || []).length} / IT {(reportData.tester.vectorcast.it_reports || []).length}
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Traceability Summary — between 빌드 & 문서 */}
        <TraceSummaryCard summary={traceSummary} loading={traceLoading} onRefresh={refreshTraceSummary} />

        {/* Document & Impact Summary */}
        <div className="panel" style={{ boxShadow: 'none', background: 'var(--bg)' }}>
          <div className="panel-header">
            <span className="panel-title">문서 & 영향도 요약</span>
          </div>
          <ImpactPanel impactData={impactData} />
        </div>
      </div>

      {/* Navigation buttons removed — use tabs to access detail/impact views */}
    </div>
  );
}

/* ── TraceSummaryCard ── */
function TraceSummaryCard({ summary, loading, onRefresh }) {
  const refreshBtn = onRefresh ? (
    <button
      onClick={onRefresh}
      title="추적성 매트릭스 요약 새로고침"
      style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 14, color: 'var(--text-muted)', padding: '0 4px' }}
      aria-label="새로고침"
    >
      ↻
    </button>
  ) : null;

  if (loading) {
    return (
      <div className="panel" style={{ boxShadow: 'none', background: 'var(--bg)', padding: 'var(--sp-3)' }}>
        <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>
          추적성 요약 로딩 중...
        </div>
      </div>
    );
  }
  if (!summary || !summary.has_data) {
    const reason = summary?.reason;
    return (
      <div className="panel" style={{ boxShadow: 'none', background: 'var(--bg)', padding: 'var(--sp-3)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className="panel-title">추적성 매트릭스 요약</span>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
              {reason || 'SRS & SDS 섹션에서 매트릭스를 먼저 생성하면 요약이 여기 표시됩니다'}
            </span>
            {refreshBtn}
          </div>
        </div>
      </div>
    );
  }

  const total = summary.total_requirements || 0;
  const covered = summary.covered || 0;
  const partial = summary.partial || 0;
  const uncovered = summary.uncovered || 0;
  const pct = summary.coverage_pct || 0;
  const generatedAt = summary.generated_at ? new Date(summary.generated_at).toLocaleString('ko-KR') : '';

  return (
    <div className="panel" style={{ boxShadow: 'none', background: 'var(--bg)' }}>
      <div className="panel-header">
        <span className="panel-title">추적성 매트릭스 요약</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <QualityGateBadge pct={pct} />
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{generatedAt}</span>
          {refreshBtn}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 'var(--sp-2)', alignItems: 'stretch', flexWrap: 'wrap' }}>
        <CoverageDonut covered={covered} partial={partial} uncovered={uncovered} pct={pct} />
        <div style={{ flex: '1 1 300px', display: 'flex', gap: 'var(--sp-2)', flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 auto', minWidth: 100, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))' }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>전체 요구사항</div>
            <div style={{ fontSize: 18, fontWeight: 700 }}>{total.toLocaleString()}</div>
          </div>
          <div style={{ flex: '1 1 auto', minWidth: 100, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))' }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Covered</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--color-success)' }}>{covered}</div>
          </div>
          <div style={{ flex: '1 1 auto', minWidth: 100, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))' }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Partial</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--color-warning)' }}>{partial}</div>
          </div>
          <div style={{ flex: '1 1 auto', minWidth: 100, padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))' }}>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Uncovered</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--color-danger)' }}>{uncovered}</div>
          </div>
        </div>
      </div>

      {/* ASIL 등급별 분포·커버리지 — 백엔드 _cache_trace_summary가 실어주면 표시(구버전 캐시엔 없어 가드) */}
      {summary.asil_distribution && Object.keys(summary.asil_distribution).length > 0 && (
        <div style={{ marginTop: 'var(--sp-2)', paddingTop: 'var(--sp-2)', borderTop: '1px solid var(--border)' }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>ASIL 등급별 분포 · 커버리지</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {['D', 'C', 'B', 'A', 'QM', 'UNKNOWN'].filter((g) => summary.asil_distribution[g]).map((g) => {
              const c = summary.asil_distribution[g];
              const pct = c.total ? Math.round((c.covered / c.total) * 100) : 0;
              const label = g === 'UNKNOWN' ? '미상' : g === 'QM' ? 'QM' : `ASIL ${g}`;
              const col = pct >= GATE_PASS ? 'var(--color-success)' : pct >= GATE_WARN ? 'var(--color-warning)' : 'var(--color-danger)';
              return (
                <div key={g} title={`${label}: ${c.total}건 중 ${c.covered}건 검증 (${pct}%)`}
                  style={{ padding: '4px 9px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))', fontSize: 11, whiteSpace: 'nowrap' }}>
                  <span style={{ fontWeight: 700 }}>{label}</span>{' '}
                  <span style={{ color: 'var(--text-muted)' }}>{c.total}건 ·</span>{' '}
                  <span style={{ fontWeight: 700, color: col }}>{pct}%</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 밴드별 추적 현황 — 각 V-model 밴드에 연결된 요구사항 수 */}
      {summary.band_counts && Object.keys(summary.band_counts).length > 0 && (
        <div style={{ marginTop: 'var(--sp-2)', paddingTop: 'var(--sp-2)', borderTop: '1px solid var(--border)' }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6 }}>
            밴드별 추적 현황 <span style={{ fontWeight: 400 }}>· 연결된 요구사항 수 (전체 {total})</span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {['SyRS', 'SDS', 'HSIS', 'UDS', 'STS', 'SUTS', 'SITS', 'SyTS', 'SyITS', 'VectorCAST'].map((b) => {
              const n = summary.band_counts[b] || 0;
              const pct = total ? Math.round((n / total) * 100) : 0;
              return (
                <div key={b} title={`${b}: ${n}건 (${pct}%)`}
                  style={{ padding: '4px 9px', borderRadius: 6, border: '1px solid var(--border)', background: n ? 'var(--card-bg, var(--surface))' : 'var(--bg)', fontSize: 11, whiteSpace: 'nowrap', opacity: n ? 1 : 0.55 }}>
                  <span style={{ fontWeight: 600 }}>{b}</span>{' '}
                  <span style={{ color: 'var(--text-muted)' }}>{n} ({pct}%)</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── CoverageDonut ── */
export function CoverageDonut({ covered, partial, uncovered, pct }) {
  const total = covered + partial + uncovered;
  if (total <= 0) return null;
  // SVG donut: r=40, circumference 251.3. Each slice gets a proportional arc.
  const R = 40;
  const C = 2 * Math.PI * R;
  const segCov = (covered / total) * C;
  const segPar = (partial / total) * C;
  const segUnc = (uncovered / total) * C;
  const pctColor =
    pct >= GATE_PASS ? 'var(--color-success)' :
    pct >= GATE_WARN ? 'var(--color-warning)' :
    'var(--color-danger)';
  return (
    <div
      role="img"
      aria-label={`커버리지 ${pct}% (Covered ${covered}, Partial ${partial}, Uncovered ${uncovered})`}
      style={{ flex: '0 0 110px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
    >
      <svg width="96" height="96" viewBox="0 0 96 96">
        {/* Track */}
        <circle cx="48" cy="48" r={R} fill="none" stroke="var(--border, #e5e7eb)" strokeWidth="12" />
        {/* Slices — drawn clockwise from 12 o'clock via rotate(-90) */}
        <g transform="rotate(-90 48 48)">
          {covered > 0 && (
            <circle cx="48" cy="48" r={R} fill="none"
              stroke="var(--color-success)" strokeWidth="12"
              strokeDasharray={`${segCov} ${C - segCov}`} strokeDashoffset="0" />
          )}
          {partial > 0 && (
            <circle cx="48" cy="48" r={R} fill="none"
              stroke="var(--color-warning)" strokeWidth="12"
              strokeDasharray={`${segPar} ${C - segPar}`} strokeDashoffset={-segCov} />
          )}
          {uncovered > 0 && (
            <circle cx="48" cy="48" r={R} fill="none"
              stroke="var(--color-danger)" strokeWidth="12"
              strokeDasharray={`${segUnc} ${C - segUnc}`} strokeDashoffset={-(segCov + segPar)} />
          )}
        </g>
        <text x="48" y="52" textAnchor="middle" fontSize="18" fontWeight="700" fill={pctColor}>
          {pct}%
        </text>
      </svg>
    </div>
  );
}

/* ── QualityGateBadge ── */
export function QualityGateBadge({ pct }) {
  const gate = classifyGate(pct);
  const config = {
    pass: { label: '✓ PASS', bg: '#dcfce7', fg: '#166534', border: '#86efac' },
    warn: { label: '⚠ WARN', bg: '#fef9c3', fg: '#854d0e', border: '#fde047' },
    fail: { label: '✗ FAIL', bg: '#fee2e2', fg: '#991b1b', border: '#fca5a5' },
  }[gate];
  return (
    <span
      title={`Quality Gate: ≥${GATE_PASS}% PASS / ≥${GATE_WARN}% WARN`}
      aria-label={`Quality Gate ${gate.toUpperCase()}`}
      style={{
        fontSize: 11,
        fontWeight: 700,
        padding: '2px 8px',
        borderRadius: 10,
        background: config.bg,
        color: config.fg,
        border: `1px solid ${config.border}`,
        whiteSpace: 'nowrap',
      }}
    >
      {config.label}
    </span>
  );
}

/* ── FileTypeChart ── */
function FileTypeChart({ fileTypes }) {
  const entries = Object.entries(fileTypes);
  if (!entries.length) return null;
  const total = entries.reduce((s, [, c]) => s + c, 0);
  const BAR_COLORS = { html: '#3b82f6', xlsx: '#22c55e', json: '#f59e0b', csv: '#8b5cf6', md: '#64748b', pdf: '#ef4444' };
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{ fontSize: 12, fontWeight: 600 }}>파일 유형 분포</span>
        <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>총 {total}개</span>
      </div>
      {/* Stacked bar */}
      <div style={{ display: 'flex', height: 20, borderRadius: 6, overflow: 'hidden', border: '1px solid var(--border)' }}>
        {entries.map(([ext, cnt]) => (
          <div
            key={ext}
            title={`${ext.toUpperCase()}: ${cnt}`}
            style={{
              width: `${(cnt / total) * 100}%`,
              background: BAR_COLORS[ext] || '#94a3b8',
              minWidth: 12,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 9, fontWeight: 700, color: '#fff',
              cursor: 'default',
            }}
          >
            {cnt >= 2 ? cnt : ''}
          </div>
        ))}
      </div>
      {/* Legend */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 10px', marginTop: 6 }}>
        {entries.map(([ext, cnt]) => (
          <div key={ext} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: BAR_COLORS[ext] || '#94a3b8', flexShrink: 0 }} />
            <span style={{ color: 'var(--text-muted)' }}>{ext.toUpperCase()}</span>
            <span style={{ fontWeight: 600 }}>{cnt}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── PrqaPanel ── */
function PrqaPanel({ prqa }) {
  if (prqa.rule_violation_count == null) return null;
  const complianceRate = prqa.project_compliance_index;
  const hmr = prqa.hmr_stats || {};
  return (
    <div style={{ marginBottom: 10, padding: '10px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--card-bg, var(--surface))' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 600 }}>PRQA 정적분석</span>
        {complianceRate != null && (
          <span className={`pill ${complianceRate >= 90 ? 'pill-success' : complianceRate >= 70 ? 'pill-warning' : 'pill-danger'}`} style={{ fontSize: 11 }}>
            준수율 {complianceRate}%
          </span>
        )}
      </div>
      {/* Compliance bar */}
      {complianceRate != null && (
        <div style={{ height: 6, borderRadius: 3, background: 'var(--border)', marginBottom: 8, overflow: 'hidden' }}>
          <div style={{ height: '100%', width: `${complianceRate}%`, borderRadius: 3, background: complianceRate >= 90 ? 'var(--color-success)' : complianceRate >= 70 ? 'var(--color-warning)' : 'var(--color-danger)', transition: 'width 0.5s' }} />
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 6 }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 16, fontWeight: 700, color: prqa.rule_violation_count > 0 ? 'var(--color-warning)' : 'var(--color-success)' }}>{prqa.rule_violation_count}</div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>위반 건수</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 16, fontWeight: 700 }}>{prqa.violated_rules ?? '-'}<span style={{ fontSize: 10, fontWeight: 400, color: 'var(--text-muted)' }}>/{(prqa.violated_rules ?? 0) + (prqa.compliant_rules ?? 0)}</span></div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>위반 규칙</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 16, fontWeight: 700 }}>{prqa.file_compliance_index ?? '-'}%</div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>파일 준수율</div>
        </div>
      </div>
      {/* HMR complexity stats */}
      {hmr.functions_total && (
        <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border)', display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: 4 }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 13, fontWeight: 700 }}>{hmr.functions_total}</div>
            <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>함수</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: hmr.vg_max > 15 ? 'var(--color-danger)' : hmr.vg_max > 10 ? 'var(--color-warning)' : 'var(--color-success)' }}>{hmr.vg_max}</div>
            <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>VG Max</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 13, fontWeight: 700 }}>{hmr.vg_p95}</div>
            <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>VG P95</div>
          </div>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 13, fontWeight: 700 }}>{hmr.vg_mean?.toFixed(1)}</div>
            <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>VG 평균</div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── ImpactPanel ── */
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

  const trigger = impactData.trigger || {};
  const changedFiles = Array.isArray(impactData.changed_files) ? impactData.changed_files
    : Array.isArray(trigger.changed_files) ? trigger.changed_files : [];
  const changedFunctions = impactData.changed_functions ?? impactData.changed_function_types ?? {};
  const changedFnEntries = typeof changedFunctions === 'object' && !Array.isArray(changedFunctions)
    ? Object.entries(changedFunctions) : [];
  const impact = impactData.impact || {};
  const counts = impactData.impact_counts || {
    direct: Array.isArray(impact.direct) ? impact.direct.length : (impact.direct ?? undefined),
    indirect_1hop: Array.isArray(impact.indirect_1hop) ? impact.indirect_1hop.length : (impact.indirect_1hop ?? undefined),
    indirect_2hop: Array.isArray(impact.indirect_2hop) ? impact.indirect_2hop.length : (impact.indirect_2hop ?? undefined),
  };
  const rawDocs = impactData.documents ?? impactData.actions ?? {};
  const docs = typeof rawDocs === 'object' ? rawDocs : {};
  const warnings = Array.isArray(impactData.warnings) ? impactData.warnings : [];
  const scmName = impactData._scm_name || '';

  return (
    <div>
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
      ) : changedFiles.length === 0 && changedFnEntries.length === 0 ? (
        <div className="text-muted text-sm">영향받는 항목 없음</div>
      ) : null}

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

/* ── ImpactDocRow ── */
function ImpactDocRow({ docKey, doc, open, onToggle }) {
  const st = _DOC_STATUS[doc?.status] || { color: 'var(--text-muted)', label: doc?.status || '-' };
  const summary = doc?.summary || {};
  const fns = Array.isArray(doc?.flagged_functions) ? doc.flagged_functions
    : Array.isArray(doc?.functions) ? doc.functions
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
