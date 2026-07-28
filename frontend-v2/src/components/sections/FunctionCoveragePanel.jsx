/**
 * FunctionCoveragePanel — 함수(subprogram)단위 커버리지 + 실패 TC.
 * POST /api/summary/quality-detail 소비 — 소스는 vectorcast_detail(구 규약) →
 * vectorcast.ut/it_metrics → **SCM 입력 문서 로드 이력**(N1) 순 폴백, source로 출처 표기.
 * 섹션별 available:false 분리 렌더(증거부재≠0). IT 축은 소스마다 달라(빌드=진입/호출,
 * SCM=구문/분기/호출) metrics_present 기준으로 컬럼을 동적 구성한다.
 */
import { useEffect, useState } from 'react';
import { post } from '../../api.js';

const xs = { fontSize: 'var(--text-xs)' };

// IT 축 — 응답의 metrics_present에 있는 축만 렌더(부재 축을 0%로 위장하지 않는다).
const IT_AXES = [
  { key: 'functions', label: '진입' },
  { key: 'statements', label: '구문' },
  { key: 'branches', label: '분기' },
  { key: 'function_calls', label: '호출' },
];

const SOURCE_KO = {
  vectorcast_detail: '빌드 산출물(detail)',
  vectorcast_metrics: '빌드 산출물(UT/IT metrics)',
  scm_vcast_job: 'SCM 입력 문서',
};

function ratePct(st) {
  const r = st?.rate;
  if (r == null || Number.isNaN(Number(r))) return null;
  const n = Number(r);
  return n <= 1 ? n * 100 : n;  // 0~1 비율/0~100 퍼센트 양쪽 수용(파서 포맷 편차 방어)
}

/**
 * 반복 측정 접힘 각주 — VectorCAST가 같은 함수를 환경마다 다시 측정해 entries에 중복으로
 * 실린다. 서버가 (unit, subprogram)으로 접은 사실을 숨기면 "왜 항목 수가 줄었나"를 답할 수
 * 없다(접기 전 712 → 후 259). 접힘이 없으면 렌더하지 않는다.
 */
function FoldNote({ fold }) {
  if (!fold || !(fold.duplicated_keys > 0)) return null;
  return (
    <span title={`${fold.note} · 원본 ${fold.raw_entries}행 → ${fold.folded_entries}함수 · 측정값이 환경마다 다른 함수 ${fold.divergent_keys}개`}>
      {' · '}환경 반복 측정 {fold.raw_entries - fold.folded_entries}행 접음
      {fold.divergent_keys > 0 && ` (환경별 상이 ${fold.divergent_keys})`}
    </span>
  );
}

/** 반복 측정된 함수 표시 — 표의 수치가 '최대 커버' 기준임을 행 단위로 알린다. */
function Measurements({ e }) {
  if (!(e?.measurements > 1)) return null;
  return (
    <span style={{ color: 'var(--text-muted)' }}
      title={`환경 ${e.measurements}곳에서 측정 — 표시값은 최대 커버 기준${e.divergent ? ' (환경마다 결과가 다릅니다)' : ''}`}>
      {e.divergent ? ' ⚠' : ' *'}{e.measurements}
    </span>
  );
}

function SourceBadge({ source, detail, buildNumber }) {
  if (!source) return null;
  const isScm = source === 'scm_vcast_job';
  const when = String(detail?.generated_at || '').replace('T', ' ').slice(0, 16);
  return (
    <span
      aria-label="커버리지 출처"
      title={isScm
        ? `설정 > 연결 문서 경로 > VectorCAST 로드 결과${detail?.job_file ? ` (${detail.job_file})` : ''} — 빌드 산출물이 아닙니다`
        : `빌드 #${buildNumber ?? '?'} 산출물에서 직접 읽음`}
      style={{
        ...xs, padding: '1px 7px', borderRadius: 'var(--radius-sm)', fontWeight: 600, color: '#fff',
        background: isScm ? 'var(--color-info)' : 'var(--text-muted)',
      }}
    >
      {SOURCE_KO[source] || source}{isScm && when ? ` · ${when} 로드` : ''}
    </span>
  );
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
  const itc = data?.it_coverage;
  // 보유 축만 렌더 — metrics_present가 정본이고, 구 응답(필드 부재)은 totals 존재로 폴백한다.
  const itAxes = IT_AXES.filter((a) => (
    itc?.metrics_present ? !!itc.metrics_present[a.key] : !!itc?.totals?.[a.key]
  ));

  return (
    <div className="panel" style={{ padding: 'var(--sp-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>함수별 커버리지 · 실패 테스트</div>
        {data?.build_number != null && <span style={{ ...xs, color: 'var(--text-muted)' }}>빌드 #{data.build_number}</span>}
        <SourceBadge source={data?.coverage_source} detail={data?.coverage_source_detail} buildNumber={data?.build_number} />
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
                  {fc.totals.branches?.rate != null && ` · 분기 ${fc.totals.branches.rate}%`}
                  {fc.source && ` · 출처 ${SOURCE_KO[fc.source] || fc.source}`}
                  <FoldNote fold={fc.fold} />
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                    <thead><tr><th style={th}>함수</th><th style={th}>유닛</th><th style={th}>구문</th><th style={th}>분기</th><th style={th}>ccn</th></tr></thead>
                    <tbody>
                      {(fc.worst || []).map((e, i) => {
                        const sp = ratePct(e.statements);
                        const bp = ratePct(e.branches);
                        return (
                          // 인덱스 동반 key — 백엔드 폴딩으로 중복은 사라졌지만, 새 소스가
                          // 축 없는 중복을 다시 실어도 렌더가 조용히 행을 삼키지 않게 한다.
                          <tr key={`${e.unit}:${e.subprogram}:${i}`}>
                            <td style={td}>
                              {e.subprogram}
                              <Measurements e={e} />
                            </td>
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
              <div style={{ ...xs, color: 'var(--text-muted)' }}>
                함수단위 커버리지 소스가 없습니다 — 빌드 산출물(vectorcast detail/metrics)에도, SCM 입력 문서 로드 이력에도 없습니다.
                설정 &gt; 연결 문서 경로 &gt; VectorCAST를 지정하고 한 번 불러오면 여기에 표시됩니다.
              </div>
            )}
          </div>
          <div>
            {itc?.available ? (
              <>
                <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>
                  통합(IT) 커버리지 — 함수 {itc.totals.entries}
                  {itAxes.map((a) => (
                    <span key={a.key}> · {a.label} {itc.totals[a.key]?.rate ?? '—'}%</span>
                  ))}
                  <FoldNote fold={itc.fold} />
                  {itc.metrics_present?.functions ? (
                    <span title="IT의 함수 진입/호출 커버리지는 UT 구문·분기와 기준이 달라 직접 비교할 수 없습니다"> · 구문·분기와 비교 불가</span>
                  ) : (
                    <span title="같은 구문·분기 척도지만 통합 시험 실행 기준이라 단위(UT) 수치와 합산하면 안 됩니다"> · UT와 합산 금지</span>
                  )}
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                    <thead>
                      <tr>
                        <th style={th}>함수</th><th style={th}>유닛</th>
                        {itAxes.map((a) => <th key={a.key} style={th}>{a.label}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {(itc.worst || []).slice(0, 8).map((e, i) => (
                        <tr key={`${e.unit}:${e.subprogram}:${i}`}>
                          <td style={td}>
                            {e.subprogram}
                            <Measurements e={e} />
                          </td>
                          <td style={{ ...td, color: 'var(--text-muted)' }}>{e.unit}</td>
                          {itAxes.map((a) => (
                            <td key={a.key} style={td}>
                              {ratePct(e[a.key]) == null ? '—' : `${Math.round(ratePct(e[a.key]))}%`}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <div style={{ ...xs, color: 'var(--text-muted)' }}>통합(IT) 메트릭이 없습니다(빌드 산출물·SCM 입력 문서 모두).</div>
            )}
          </div>
          <div>
            {ft?.available ? (
              <>
                <div style={{ ...xs, color: ft.count > 0 ? 'var(--color-danger)' : 'var(--text-muted)', marginBottom: 4 }}>
                  실패 테스트케이스 {ft.count}건
                  {ft.test_summary?.total != null && (
                    <> · 전체 {ft.test_summary.total}
                      {ft.test_summary.passed != null && ` · 통과 ${ft.test_summary.passed}`}
                      {ft.test_summary.ut_rows != null && ` (UT ${ft.test_summary.ut_rows}`}
                      {ft.test_summary.it_rows != null && ` · IT ${ft.test_summary.it_rows})`}
                    </>
                  )}
                </div>
                {(ft.items || []).slice(0, 12).map((f, i) => (
                  <div key={i} style={{ ...xs, borderLeft: '3px solid var(--color-danger)', padding: '2px 8px', marginBottom: 4 }}>
                    {String(f.testcase || f.subprogram || f.name || JSON.stringify(f)).slice(0, 120)}
                  </div>
                ))}
                {ft.count === 0 && <div style={{ ...xs, color: 'var(--color-success)' }}>실패 없음</div>}
                {ft.source_path && (
                  <div style={{ ...xs, color: 'var(--text-muted)' }} title={ft.source_path}>
                    출처: …{String(ft.source_path).replace(/\\/g, '/').split('/').slice(-2).join('/')}
                  </div>
                )}
                {ft.source === 'scm_vcast_job' && (
                  <div style={{ ...xs, color: 'var(--text-muted)' }}>
                    출처: SCM 입력 문서{ft.generated_at ? ` · ${String(ft.generated_at).replace('T', ' ').slice(0, 16)} 로드` : ''}
                  </div>
                )}
              </>
            ) : (
              <div style={{ ...xs, color: 'var(--text-muted)' }}>테스트 실행 로그가 없습니다(빌드 vectorcast_rag·SCM 입력 문서 모두).</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
