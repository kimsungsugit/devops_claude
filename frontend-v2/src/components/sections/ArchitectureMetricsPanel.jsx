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
  // v4(N5) 블록 — 구 캐시(v3) 응답엔 없으므로 옵셔널 접근 후 정직 안내로 폴백한다.
  const intf = data?.asil_interference;
  const gcoup = data?.global_coupling;
  const cc = data?.coverage_complexity;
  const ind = data?.indirect_calls;
  const enc = data?.encapsulation;

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

          {/* v4(N5) — ASIL 간섭 자유 후보 */}
          <div>
            <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>
              ASIL 간섭 검토 후보 (freedom from interference)
            </div>
            {intf?.available ? (
              <>
                <div style={{ ...xs, marginBottom: 4 }}>
                  등급 보유 함수 {intf.graded_functions} · 등급 상이 호출 <b>{intf.edges_total}</b>건
                  {' · '}등급 혼재 모듈 <b>{intf.mixed_modules}</b>개
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                    <thead><tr><th style={th}>상위 등급</th><th style={th}>→ 하위/미상</th><th style={th}>모듈 경계</th></tr></thead>
                    <tbody>
                      {(intf.edges || []).slice(0, 6).map((e) => (
                        <tr key={`${e.caller}->${e.callee}`}>
                          <td style={td} title={e.caller_file}>{e.caller} <b>{e.caller_asil || '미상'}</b></td>
                          <td style={td} title={e.callee_file}>{e.callee} <b>{e.callee_asil || '미상'}</b></td>
                          <td style={td}>{e.cross_module ? '넘음' : '내부'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 2 }}>* {intf.note}</div>
              </>
            ) : (
              <div style={{ ...xs, color: 'var(--text-muted)' }}>
                함수 ASIL 등급 정보가 없어 간섭 검토 후보를 낼 수 없습니다(주석·요구 역전파 모두 부재).
              </div>
            )}
          </div>

          {/* v4(N5) — 전역 결합 */}
          <div>
            <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>공유 전역 데이터 (모듈 경계 넘는 참조)</div>
            {gcoup?.available ? (
              <>
                <div style={{ ...xs, marginBottom: 4 }}>
                  전역 {gcoup.distinct_globals}개 중 <b>{gcoup.cross_module_globals}</b>개가 2개 이상 모듈에서 참조
                </div>
                {(() => {
                  const rows = (gcoup.top || []).slice(0, 6);
                  const max = Math.max(...rows.map((r) => r.functions || 0), 1);
                  return rows.map((r) => (
                    <HorizontalBar key={r.global}
                      label={`${r.global} (${r.modules}모듈)`}
                      value={r.functions || 0} max={max} color="var(--color-info)" />
                  ));
                })()}
                <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 2 }}>* {gcoup.note}</div>
              </>
            ) : (
              <div style={{ ...xs, color: 'var(--text-muted)' }}>전역 참조가 관측되지 않았습니다.</div>
            )}
          </div>

          {/* v4(N5) — 커버리지 × 복잡도 우선순위 */}
          <div>
            <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>테스트 투자 우선순위 (고복잡도 × 저커버리지)</div>
            {cc?.available ? (
              <>
                <div style={{ ...xs, marginBottom: 4 }}>
                  조인 {cc.joined}함수(미조인 {cc.unjoined}) · 임계 복잡도 {cc.complexity_threshold}
                  {cc.complexity_basis === 'loc_proxy' && <span title="측정 ccn이 없어 라인수 프록시 기준"> (추정 기준)</span>}
                  {' · '}고복잡·저커버 <b style={{ color: 'var(--color-danger)' }}>{cc.counts?.high_complex_low_cov ?? 0}</b>
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                    <thead><tr><th style={th}>함수</th><th style={th}>구문</th><th style={th}>복잡도</th></tr></thead>
                    <tbody>
                      {(cc.priority || []).slice(0, 6).map((p) => (
                        <tr key={p.function}>
                          <td style={td} title={p.file}>{p.function}</td>
                          <td style={{ ...td, color: 'var(--color-danger)', fontWeight: 600 }}>{Math.round(p.statement * 100)}%</td>
                          <td style={td}>{p.complexity}{p.complexity_source === 'vcast_ccn' ? '' : '≈'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 2 }}>* {cc.note}</div>
              </>
            ) : (
              <div style={{ ...xs, color: 'var(--text-muted)' }}>
                함수 커버리지 인덱스가 없어 사분면을 낼 수 없습니다.
              </div>
            )}
          </div>

          {/* v4(N5) — 간접 호출 · 캡슐화 */}
          <div>
            <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>콜그래프 완전성 · 캡슐화</div>
            {ind && (
              <div style={{ ...xs, marginBottom: 4 }}>
                함수포인터/간접 호출 보유 함수 <b>{ind.functions_with_indirect}</b>
                {' · '}참조 엣지 {ind.reference_edges}건 — <span style={{ color: 'var(--color-warning)' }}>위 fan-in/사이클에 미반영</span>
              </div>
            )}
            {(ind?.top || []).slice(0, 4).map((t) => (
              <div key={t.function} style={{ ...xs, color: 'var(--text-muted)' }} title={t.file}>
                · {t.function} — 참조 {t.func_refs} / 간접호출 {t.pointer_calls}
              </div>
            ))}
            {enc && (
              <div style={{ ...xs, marginTop: 'var(--sp-2)' }}>
                함수 {enc.functions} · 헤더 정의 {enc.header_defined_functions}
                {enc.documented_ratio != null && ` · 문서화 ${Math.round(enc.documented_ratio * 100)}%`}
                <div style={{ color: 'var(--text-muted)' }}>* {enc.note}</div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
