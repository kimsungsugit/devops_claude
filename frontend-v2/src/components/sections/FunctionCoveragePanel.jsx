/**
 * FunctionCoveragePanel — 함수(subprogram)단위 커버리지 + 실패 테스트케이스.
 * POST /api/summary/quality-detail 소비(vectorcast_detail — 기존 미노출 갭 해소).
 * 섹션별 available:false 분리 렌더(증거부재≠0).
 */
import { useEffect, useState } from 'react';
import { post } from '../../api.js';

const xs = { fontSize: 'var(--text-xs)' };

function ratePct(st) {
  const r = st?.rate;
  if (r == null || Number.isNaN(Number(r))) return null;
  const n = Number(r);
  return n <= 1 ? n * 100 : n;  // 0~1 비율/0~100 퍼센트 양쪽 수용(파서 포맷 편차 방어)
}

export default function FunctionCoveragePanel({ jobUrl, cacheRoot }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const resp = await post('/api/summary/quality-detail', { job_url: jobUrl, cache_root: cacheRoot, worst_limit: 12 });
        if (!cancelled) { setData(resp); setError(''); }
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot]);

  const th = { ...xs, textAlign: 'left', padding: '4px 8px', color: 'var(--text-muted)', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
  const td = { ...xs, padding: '4px 8px', whiteSpace: 'nowrap', borderBottom: '1px solid var(--border)' };
  const fc = data?.function_coverage;
  const ft = data?.failed_testcases;

  return (
    <div className="panel" style={{ padding: 'var(--sp-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>함수별 커버리지 · 실패 테스트</div>
        {data?.build_number != null && <span style={{ ...xs, color: 'var(--text-muted)' }}>빌드 #{data.build_number} 산출물</span>}
        {!data && !error && <span className="spinner" />}
      </div>
      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>조회 오류: {error}</div>}
      {data && data.available === false && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>캐시된 빌드가 없습니다.</div>
      )}

      {data?.available && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 'var(--sp-4)' }}>
          <div>
            {fc?.available ? (
              <>
                <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>
                  구문 커버리지 최저 함수 — 전체 {fc.totals.functions}개 중 완전 {fc.totals.fully_covered} · 미커버 {fc.totals.uncovered}
                  {fc.totals.statements?.rate != null && ` · 구문 ${fc.totals.statements.rate}%`}
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                    <thead><tr><th style={th}>함수</th><th style={th}>유닛</th><th style={th}>구문</th><th style={th}>분기</th><th style={th}>ccn</th></tr></thead>
                    <tbody>
                      {(fc.worst || []).map((e) => {
                        const sp = ratePct(e.statements);
                        const bp = ratePct(e.branches);
                        return (
                          <tr key={`${e.unit}:${e.subprogram}`}>
                            <td style={td}>{e.subprogram}</td>
                            <td style={{ ...td, color: 'var(--text-muted)' }}>{e.unit}</td>
                            <td style={{ ...td, fontWeight: 600, color: sp != null && sp < 50 ? 'var(--color-danger)' : sp != null && sp < 80 ? 'var(--color-warning)' : 'var(--text)' }}>
                              {sp == null ? '—' : `${Math.round(sp)}%`}
                              {e.statements?.total != null && ` (${e.statements.covered}/${e.statements.total})`}
                            </td>
                            <td style={td}>{bp == null ? '—' : `${Math.round(bp)}%`}</td>
                            <td style={td}>{e.ccn ?? '—'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <div style={{ ...xs, color: 'var(--text-muted)' }}>이 빌드 산출물에 함수단위 커버리지(vectorcast_detail)가 없습니다.</div>
            )}
          </div>
          <div>
            {ft?.available ? (
              <>
                <div style={{ ...xs, color: ft.count > 0 ? 'var(--color-danger)' : 'var(--text-muted)', marginBottom: 4 }}>
                  실패 테스트케이스 {ft.count}건
                </div>
                {(ft.items || []).slice(0, 12).map((f, i) => (
                  <div key={i} style={{ ...xs, borderLeft: '3px solid var(--color-danger)', padding: '2px 8px', marginBottom: 4 }}>
                    {String(f.testcase || f.subprogram || f.name || JSON.stringify(f)).slice(0, 120)}
                  </div>
                ))}
                {ft.count === 0 && <div style={{ ...xs, color: 'var(--color-success)' }}>실패 없음</div>}
              </>
            ) : (
              <div style={{ ...xs, color: 'var(--text-muted)' }}>이 빌드 산출물에 테스트 실행 로그(vectorcast_rag)가 없습니다.</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
