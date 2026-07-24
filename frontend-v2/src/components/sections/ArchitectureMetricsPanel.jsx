/**
 * ArchitectureMetricsPanel — 소스 아키텍처 결정론 메트릭(LLM 없이 항상 표시).
 * POST /api/summary/architecture-metrics 소비: 핫스팟(fan_in×복잡도)·파일 결합도·
 * 사이즈 아웃라이어. 복잡도 출처(vcast_ccn 측정 vs loc_proxy 추정)를 구분 표기(정직성).
 */
import { useEffect, useState } from 'react';
import { post } from '../../api.js';
import { HorizontalBar } from '../charts.jsx';

const xs = { fontSize: 'var(--text-xs)' };

export default function ArchitectureMetricsPanel({ jobUrl, cacheRoot }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const resp = await post('/api/summary/architecture-metrics', { job_url: jobUrl, cache_root: cacheRoot });
        if (!cancelled) { setData(resp); setError(''); }
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot]);

  const th = { ...xs, textAlign: 'left', padding: '4px 8px', color: 'var(--text-muted)', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
  const td = { ...xs, padding: '4px 8px', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
  const coupling = data?.coupling || {};

  return (
    <div className="panel" style={{ padding: 'var(--sp-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>아키텍처 메트릭 (소스 스냅샷)</div>
        {data?.available && data?.snapshot && (
          <span style={{ ...xs, color: 'var(--text-muted)' }}>
            빌드 #{data.build_number} · 파일 {data.snapshot.files} · 함수 {data.snapshot.functions}
          </span>
        )}
        {!data && !error && <span className="spinner" />}
      </div>

      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>아키텍처 메트릭 오류: {error}</div>}
      {data && data.available === false && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          {data.reason === 'no_source_snapshot' ? '캐시 빌드에 소스 스냅샷이 없어 계산할 수 없습니다.'
            : `아키텍처 메트릭을 계산할 수 없습니다 (${data.reason})`}
        </div>
      )}

      {data?.available && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 'var(--sp-4)' }}>
          <div>
            <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>
              핫스팟 (fan-in × 복잡도) — 변경 파급이 큰 함수
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                <thead>
                  <tr><th style={th}>함수</th><th style={th}>fan-in</th><th style={th}>복잡도</th><th style={th}>점수</th></tr>
                </thead>
                <tbody>
                  {(data.hotspots || []).slice(0, 8).map((h) => (
                    <tr key={h.function}>
                      <td style={td} title={h.file}>{h.function}</td>
                      <td style={td}>{h.fan_in}</td>
                      <td style={td}>
                        {h.complexity}
                        <span style={{ color: 'var(--text-muted)' }} title={h.complexity_source === 'vcast_ccn' ? 'VectorCAST 측정 순환복잡도' : '본문 라인수 추정(측정 아님)'}>
                          {h.complexity_source === 'vcast_ccn' ? '' : '≈'}
                        </span>
                      </td>
                      <td style={{ ...td, fontWeight: 600 }}>{h.score}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 2 }}>≈ 표시는 복잡도 추정(라인수 프록시 — VectorCAST 미측정 함수)</div>
          </div>
          <div>
            <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>
              파일 간 결합 — cross-file 호출 비율 {coupling.cross_file_call_ratio != null ? `${Math.round(coupling.cross_file_call_ratio * 100)}%` : '—'}
              {coupling.edges != null && ` (${coupling.cross_edges}/${coupling.edges} 호출)`}
            </div>
            {(() => {
              const pairs = (coupling.top_pairs || []).slice(0, 6);
              const max = Math.max(...pairs.map((p) => p.calls || 0), 1);
              return pairs.map((p) => (
                <HorizontalBar key={`${p.from_file}->${p.to_file}`}
                  label={`${String(p.from_file).split('/').pop()} → ${String(p.to_file).split('/').pop()}`}
                  value={p.calls || 0} max={max} color="var(--color-purple, var(--accent))" />
              ));
            })()}
            <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 'var(--sp-2)', marginBottom: 4 }}>대형 함수 (본문 라인)</div>
            {(() => {
              const rows = (data.size_outliers || []).slice(0, 5);
              const max = Math.max(...rows.map((r) => r.lines || 0), 1);
              return rows.map((r) => (
                <HorizontalBar key={r.function} label={r.function} value={r.lines || 0} max={max} color="var(--color-warning)" />
              ));
            })()}
          </div>
        </div>
      )}
    </div>
  );
}
