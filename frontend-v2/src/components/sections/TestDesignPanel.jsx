/**
 * TestDesignPanel — 테스트 설계 어드바이저(L2). POST /api/summary/test-design(결정론) 소비.
 * ①MC/DC 미측정 배너(미측정≠미달) ②기법 권고 테이블(ASIL×커버리지×ccn — ISO 26262-6 표
 * 참조 가이드, 심사 판정 아님) ③설계-시험 갭(band_missing이면 열거 억제 — 증거부재≠갭)
 * ④기법 카탈로그 범례. coverage_join 캡션으로 SwUFn-키 조인 함정을 표면화.
 */
import { useEffect, useState } from 'react';
import { post } from '../../api.js';

const xs = { fontSize: 'var(--text-xs)' };

const GAP_KO = {
  uncovered: { label: '미커버', color: 'var(--color-danger)' },
  unmeasured_metric: { label: 'MC/DC 미측정', color: 'var(--color-warning)' },
  below_target: { label: '목표 미달', color: 'var(--color-danger)' },
  branch_gap: { label: '분기 갭', color: 'var(--color-warning)' },
  statement_gap: { label: '구문 갭', color: 'var(--color-warning)' },
};

function AsilPill({ asil }) {
  if (!asil) return <span style={{ ...xs, color: 'var(--text-muted)' }}>미상</span>;
  const hot = asil === 'C' || asil === 'D';
  return (
    <span style={{
      ...xs, padding: '0 6px', borderRadius: 'var(--radius-sm)', fontWeight: 700,
      color: '#fff', background: hot ? 'var(--color-danger)' : 'var(--color-info)',
    }}>{asil}</span>
  );
}

export default function TestDesignPanel({ jobUrl, cacheRoot }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [showCatalog, setShowCatalog] = useState(false);
  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const resp = await post('/api/summary/test-design', { job_url: jobUrl, cache_root: cacheRoot });
        if (!cancelled) { setData(resp); setError(''); }
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot]);

  const th = { ...xs, textAlign: 'left', padding: '4px 8px', color: 'var(--text-muted)', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
  const td = { ...xs, padding: '4px 8px', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
  const tech = data?.technique_recommendations;
  const gap = data?.design_test_gap;
  const catalog = data?.catalog || {};
  const techLabel = (id) => catalog[id]?.label || id;

  return (
    <div className="panel" style={{ padding: 'var(--sp-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>테스트 설계 어드바이저 (ISO 26262-6 기법 가이드)</div>
        {data?.available && <span style={{ ...xs, color: 'var(--text-muted)' }}>빌드 #{data.build_number} · 심사 판정 아님</span>}
        {!data && !error && <span className="spinner" />}
      </div>

      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>테스트 설계 조회 오류: {error}</div>}
      {data && data.available === false && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          {data.reason === 'no_cached_build' ? '캐시된 빌드가 없습니다.' : `계산할 수 없습니다 (${data.reason})`}
        </div>
      )}

      {data?.available && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
          {data.mcdc_note && (
            <div style={{ ...xs, borderLeft: '3px solid var(--color-warning)', padding: '4px 8px', color: 'var(--text-muted)' }}>
              ⚠ {data.mcdc_note}
            </div>
          )}

          <div>
            {tech?.available ? (
              <>
                <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>
                  기법 권고 — 갭 {(
                    (tech.summary?.uncovered || 0) + (tech.summary?.unmeasured_metric || 0)
                    + (tech.summary?.below_target || 0)
                  )}건 관측
                  {' · '}커버리지 {tech.coverage_join?.entries}행 중 ASIL 조인 {tech.coverage_join?.with_asil}건
                  (미상 {tech.coverage_join?.asil_unknown} — 미상은 QM 단정 안 함)
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                    <thead>
                      <tr><th style={th}>함수</th><th style={th}>유닛</th><th style={th}>ASIL</th><th style={th}>갭</th><th style={th}>권고 기법</th><th style={th}>근거</th></tr>
                    </thead>
                    <tbody>
                      {(tech.items || []).slice(0, 15).map((i) => (
                        <tr key={`${i.unit}:${i.function}`}>
                          <td style={td}>{i.function}</td>
                          <td style={{ ...td, color: 'var(--text-muted)' }}>{i.unit}</td>
                          <td style={td}><AsilPill asil={i.asil} /></td>
                          <td style={td}>
                            <span style={{ ...xs, fontWeight: 600, color: GAP_KO[i.gap_kind]?.color || 'var(--text-muted)' }}>
                              {GAP_KO[i.gap_kind]?.label || i.gap_kind}
                            </span>
                          </td>
                          <td style={{ ...td, whiteSpace: 'normal' }}>
                            {(i.techniques || []).map((t) => (
                              <span key={t} title={`${catalog[t]?.iso_ref || ''} — ${catalog[t]?.when || ''}`}
                                style={{ ...xs, display: 'inline-block', margin: '1px 3px 1px 0', padding: '0 6px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}>
                                {techLabel(t)}
                              </span>
                            ))}
                          </td>
                          <td style={{ ...td, color: 'var(--text-muted)' }}>{i.basis}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {(tech.items_omitted || 0) > 0 && (
                  <div style={{ ...xs, color: 'var(--text-muted)' }}>표시 상한으로 {tech.items_omitted}건 생략</div>
                )}
              </>
            ) : (
              <div style={{ ...xs, color: 'var(--text-muted)' }}>이 빌드에 함수단위 커버리지가 없어 기법 권고를 만들 수 없습니다.</div>
            )}
          </div>

          <div>
            {gap?.available ? (
              <>
                <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>
                  설계-시험 갭 — UDS 설계 요구 {gap.totals?.targets_with_uds} · 설계 함수 {gap.totals?.uds_functions_distinct}
                  · SUTS 시험 {gap.totals?.suts_tests_distinct} · VCAST 실행 {gap.totals?.vcast_functions_distinct}
                </div>
                {gap.band_missing?.suts ? (
                  <div style={{ ...xs, color: 'var(--text-muted)' }}>
                    SUTS 링크 밴드 자체가 없음 — 갭이 아니라 증거 부재라 요구별 열거를 하지 않습니다.
                  </div>
                ) : (
                  <div style={xs}>
                    UDS 설계는 있는데 SUTS 시험 링크 없음: <b>{(gap.targets_with_uds_no_suts || []).length}</b>건
                    {(gap.no_suts_omitted || 0) > 0 && ` (+${gap.no_suts_omitted} 생략)`}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 2 }}>
                      {(gap.targets_with_uds_no_suts || []).slice(0, 20).map((t) => (
                        <span key={t.target_id} title={`UDS 함수 ${t.uds_count}개`}
                          style={{ ...xs, padding: '0 6px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}>
                          {t.target_id}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {(gap.targets_with_uds_no_any_test || []).length > 0 && (
                  <div style={{ ...xs, marginTop: 4 }}>
                    존재하는 시험 밴드 기준, 어떤 시험 링크도 없음: <b>{gap.targets_with_uds_no_any_test.length}</b>건
                    {(gap.no_any_omitted || 0) > 0 && ` (+${gap.no_any_omitted} 생략)`}
                  </div>
                )}
                <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 2 }}>* {gap.note}</div>
              </>
            ) : (
              <div style={{ ...xs, color: 'var(--text-muted)' }}>이 빌드에 추적성 링크 테이블(trace_link_table)이 없어 설계-시험 갭을 판정하지 않습니다.</div>
            )}
          </div>

          <div>
            <button type="button" onClick={() => setShowCatalog(!showCatalog)}
              style={{ ...xs, padding: '1px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}>
              {showCatalog ? '▾' : '▸'} 기법 카탈로그 (ISO 26262-6 참조)
            </button>
            {showCatalog && (
              <table style={{ borderCollapse: 'collapse', marginTop: 4 }}>
                <tbody>
                  {Object.entries(catalog).map(([id, c]) => (
                    <tr key={id}>
                      <td style={{ ...td, fontWeight: 600 }}>{c.label}</td>
                      <td style={{ ...td, color: 'var(--text-muted)' }}>{c.iso_ref}</td>
                      <td style={{ ...td, whiteSpace: 'normal', color: 'var(--text-muted)' }}>{c.when}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
