import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { post, api } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';
import { defaultCacheRoot } from '../../api.js';

export default function AnalysisSection({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;

  const [complexity, setComplexity] = useState(null);
  const [complexityLoading, setComplexityLoading] = useState(false);
  const [compSort, setCompSort] = useState('complexity');
  const [compFilter, setCompFilter] = useState('');
  // SCM 등록 VectorCAST 경로 지연 로드(빌드 산출물에 결과가 없을 때). 무거운 cloudium 폴더
  // 파싱(~100s)이라 analyze 임계경로에 넣지 않고 사용자 명시 클릭 시에만 /report/vectorcast-rag
  // (build→cloudium 폴백 내장)를 호출한다.
  const [scmVcast, setScmVcast] = useState(null);
  const [scmVcastLoading, setScmVcastLoading] = useState(false);
  // 언마운트 후 폴링 루프가 setState/네트워크를 계속 돌지 않도록 가드(W2). 잡 자체는 서버에서
  // 계속 실행되며 결과는 TTL 캐시되므로, 재진입 시 재클릭하면 빠르게 받는다.
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  const loadComplexity = useCallback(async () => {
    setComplexityLoading(true);
    try {
      const data = await post('/api/jenkins/report/complexity', {
        job_url: job.url, cache_root: cacheRoot, build_selector: cfg.buildSelector,
      });
      setComplexity(data ?? { rows: [] });
      // 빈 결과를 placeholder로 silent 되돌리지 않고 명시 안내(데이터 미동기화 vs 미클릭 구분).
      const n = (data?.rows ?? data?.functions ?? []).length;
      if (n === 0) toast('info', '이 빌드에 complexity.csv가 없습니다 (복잡도 데이터 미동기화).');
    } catch (e) {
      toast('error', `복잡도 조회 실패: ${e.message}`);
    } finally {
      setComplexityLoading(false);
    }
  }, [job, cfg, cacheRoot, toast]);

  const loadScmVcast = useCallback(async () => {
    const paths = analysisResult?.matchedScm?.linked_docs?.vectorcast || [];
    if (!paths.length) { toast('info', 'SCM에 등록된 VectorCAST 경로가 없습니다.'); return; }
    setScmVcastLoading(true);
    try {
      // 원격 cloudium 폴더 파싱은 수 분 걸려 동기 호출 시 4~5분 블로킹(타임아웃/언마운트 abort로
      // '에러'처럼 보임) → 백그라운드 잡으로 던지고 폴링한다. 백엔드 TTL 캐시(30분)로 2회차+ 즉시.
      const start = await post('/api/jenkins/report/vectorcast-rag-async', {
        job_url: job.url, cache_root: cacheRoot, build_selector: cfg.buildSelector,
        vcast_log_paths: paths,
      });
      const jobId = start?.job_id;
      if (!jobId) throw new Error('잡 생성에 실패했습니다.');
      toast('info', 'VectorCAST 원격 로그 파싱을 시작했습니다 (수 분 소요될 수 있습니다).');
      const t0 = Date.now();
      const TIMEOUT_MS = 12 * 60 * 1000;   // 12분 상한(최악 다폴더 파싱 + 여유)
      while (mountedRef.current) {
        if (Date.now() - t0 > TIMEOUT_MS) {
          toast('warning', 'VectorCAST 로딩 시간 초과 — 잠시 후 다시 시도하세요(캐시되어 빨라집니다).');
          return;
        }
        await new Promise(r => setTimeout(r, 3000));
        if (!mountedRef.current) return;   // 대기 중 언마운트 → 폴링 중단(잡은 서버에서 계속)
        const st = await api(`/api/scm/impact-job/${jobId}`);
        const status = st?.job?.status;
        if (status === 'completed') {
          const data = st.job.result;
          if (!mountedRef.current) return;
          if (data?.ok && data.data) {
            setScmVcast(data);
            toast('success', `VectorCAST ${data.data.test_rows_count ?? 0}건 로드 (출처: ${data.source || 'cloudium'})`);
          } else {
            toast('warning', 'SCM 등록 경로에서 VectorCAST 결과를 찾지 못했습니다 (경로/레이아웃 확인).');
          }
          return;
        }
        if (status === 'failed') {
          toast('error', `VectorCAST 로드 실패: ${st.job?.error?.title || st.job?.error?.detail || 'unknown'}`);
          return;
        }
        // queued/running → 계속 폴링
      }
    } catch (e) {
      if (mountedRef.current) toast('error', `VectorCAST 로드 실패: ${e.message}`);
    } finally {
      if (mountedRef.current) setScmVcastLoading(false);
    }
  }, [analysisResult, job, cfg, cacheRoot, toast]);

  const rd = analysisResult?.reportData;
  const kpis = rd?.kpis || {};
  const cov = kpis.coverage || {};
  const prqa = kpis.prqa || {};
  const hmr = prqa.hmr_stats || {};
  const cm = kpis.code_metrics || {};
  const vc = kpis.vectorcast || {};
  const tester = rd?.tester || {};
  // VectorCAST 표시용 — SCM 지연로드 결과가 있으면 그걸, 없으면 빌드 산출물(tester.vectorcast).
  const scmVcastPaths = analysisResult?.matchedScm?.linked_docs?.vectorcast || [];
  const buildVcast = tester?.vectorcast || {};
  const buildHasVcast = (buildVcast.test_rows_count || 0) > 0
    || (buildVcast.ut_reports || []).length > 0 || (buildVcast.it_reports || []).length > 0;
  const effVcast = scmVcast?.data
    ? { test_rows_count: scmVcast.data.test_rows_count, ut_reports: scmVcast.data.ut_reports || [], it_reports: scmVcast.data.it_reports || [], _source: scmVcast.source || 'cloudium' }
    : buildVcast;
  const utCov = vc.ut || {};
  const itCov = vc.it || {};
  const modules = utCov.modules || [];
  const qualityCfg = (() => {
    try { return JSON.parse(localStorage.getItem('devops_v2_quality') || '{}'); } catch (_) { return {}; }
  })();
  const threshold = qualityCfg.complexity ?? 15;

  // Coverage as number
  const covPct = typeof rd?.coverage === 'number' ? rd.coverage
    : (cov.line_rate != null ? Math.round(cov.line_rate * 100) : null);
  const brPct = cov.branch_rate != null ? Math.round(cov.branch_rate * 100) : null;
  // 빌드 산출물에 실제 커버리지가 있는지 — line_rate=0.0(데이터 없음)을 '0% 미검증'으로 오인하지
  // 않도록. 이 프로젝트는 일반 커버리지가 아니라 VectorCAST UT/IT 커버리지를 쓰며 그 데이터는
  // cloudium SCM 로그에 있다(빌드엔 미동기화 → covPct=0).
  const hasAnyCoverage = (covPct != null && covPct > 0) || (brPct != null && brPct > 0)
    || utCov.line_covered != null || utCov.branch_covered != null || modules.length > 0;

  // Complexity table
  const rows = complexity?.rows ?? complexity?.functions ?? [];
  const filteredRows = useMemo(() => {
    let items = [...rows];
    if (compFilter.trim()) {
      const q = compFilter.trim().toLowerCase();
      items = items.filter(r => (r.function ?? r.name ?? '').toLowerCase().includes(q) || (r.file ?? r.path ?? '').toLowerCase().includes(q));
    }
    items.sort((a, b) => {
      if (compSort === 'complexity') return (b.complexity ?? b.cc ?? 0) - (a.complexity ?? a.cc ?? 0);
      if (compSort === 'name') return (a.function ?? a.name ?? '').localeCompare(b.function ?? b.name ?? '');
      return 0;
    });
    return items;
  }, [rows, compFilter, compSort]);

  return (
    <div>
      {/* ── Coverage Detail ── */}
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-header"><span className="panel-title">코드 커버리지</span></div>
        {!hasAnyCoverage ? (
          <div className="text-sm text-muted" style={{ padding: 8 }}>
            이 빌드 산출물에 커버리지 데이터가 없습니다 (line_rate 0). 이 프로젝트의 커버리지는
            VectorCAST 시험 로그(SCM 등록 경로)에 있으며, &apos;SCM 경로에서 불러오기&apos;는 현재 시험
            통과/실패만 로드합니다 — 구문/분기/MC&#47;DC 커버리지 수치 연동은 후속 작업입니다.
          </div>
        ) : (<>
        <div className="stats-row">
          {covPct != null && (
            <div className="stat-card" style={{ borderLeft: `3px solid ${covPct >= 80 ? 'var(--color-success)' : 'var(--color-warning)'}` }}>
              <div className="stat-value" style={{ color: covPct >= 80 ? 'var(--color-success)' : 'var(--color-warning)' }}>{covPct}%</div>
              <div className="stat-label">Line Coverage</div>
            </div>
          )}
          {brPct != null && (
            <div className="stat-card" style={{ borderLeft: `3px solid ${brPct >= 80 ? 'var(--color-success)' : 'var(--color-warning)'}` }}>
              <div className="stat-value" style={{ color: brPct >= 80 ? 'var(--color-success)' : 'var(--color-warning)' }}>{brPct}%</div>
              <div className="stat-label">Branch Coverage</div>
            </div>
          )}
          {utCov.line_covered != null && (
            <div className="stat-card">
              <div className="stat-value">{utCov.line_covered?.toLocaleString()}<span style={{ fontSize: 11, fontWeight: 400 }}>/{utCov.line_total?.toLocaleString()}</span></div>
              <div className="stat-label">UT Statement</div>
            </div>
          )}
          {utCov.branch_covered != null && (
            <div className="stat-card">
              <div className="stat-value">{utCov.branch_covered?.toLocaleString()}<span style={{ fontSize: 11, fontWeight: 400 }}>/{utCov.branch_total?.toLocaleString()}</span></div>
              <div className="stat-label">UT Branch</div>
            </div>
          )}
        </div>

        {/* Module coverage table */}
        {modules.length > 0 && (
          <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>모듈별 커버리지 ({modules.length}개)</summary>
            <div style={{ maxHeight: 250, overflowY: 'auto', marginTop: 6 }}>
              <table className="impact-table" style={{ fontSize: 10 }}>
                <thead><tr><th>모듈</th><th>Line Rate</th><th>Branch Rate</th><th></th></tr></thead>
                <tbody>
                  {[...modules].sort((a, b) => (a.line_rate ?? 100) - (b.line_rate ?? 100)).map((m, i) => (
                    <tr key={i} style={{ background: m.line_rate < 80 ? '#fee2e2' : m.line_rate < 95 ? '#fef9c3' : undefined }}>
                      <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{m.name}</td>
                      <td style={{ textAlign: 'center', fontWeight: 600, color: m.line_rate < 80 ? 'var(--color-danger)' : m.line_rate < 95 ? 'var(--color-warning)' : 'var(--color-success)' }}>
                        {m.line_rate?.toFixed(1)}%
                      </td>
                      <td style={{ textAlign: 'center', fontWeight: 600, color: (m.branch_rate ?? 100) < 80 ? 'var(--color-danger)' : (m.branch_rate ?? 100) < 95 ? 'var(--color-warning)' : 'var(--color-success)' }}>
                        {m.branch_rate?.toFixed(1)}%
                      </td>
                      <td style={{ width: 100 }}>
                        <div style={{ height: 6, borderRadius: 3, background: '#e5e7eb', overflow: 'hidden' }}>
                          <div style={{ width: `${m.line_rate}%`, height: '100%', background: m.line_rate < 80 ? 'var(--color-danger)' : m.line_rate < 95 ? 'var(--color-warning)' : 'var(--color-success)' }} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}
        </>)}
      </div>

      {/* ── VectorCAST Detail ── */}
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-header">
          <span className="panel-title">VectorCAST 테스트</span>
          {/* 빌드 산출물에 결과가 없고 SCM에 경로가 등록돼 있으면 그 경로에서 지연 로드. */}
          {!buildHasVcast && !scmVcast && scmVcastPaths.length > 0 && (
            <button className="btn-sm" onClick={loadScmVcast} disabled={scmVcastLoading}
              title="Jenkins 빌드 산출물에 VectorCAST 결과가 없어, SCM 연결 문서 경로에 등록한 VectorCAST 로그에서 직접 불러옵니다(원격 폴더 파싱은 수십 초 소요).">
              {scmVcastLoading ? <span className="spinner" /> : 'SCM 경로에서 불러오기'}
            </button>
          )}
        </div>
        {effVcast._source && (
          <div className="text-sm text-muted" style={{ marginBottom: 6 }}>
            출처: SCM 연결 경로({effVcast._source}) — Jenkins 빌드 산출물 외부 결과
          </div>
        )}
        {!buildHasVcast && !scmVcast && (
          <div className="text-sm text-muted" style={{ marginBottom: 6 }}>
            {scmVcastPaths.length > 0
              ? '이 빌드 산출물에 VectorCAST 결과가 없습니다. SCM에 등록한 경로에서 불러오려면 위 버튼을 클릭하세요.'
              : '이 빌드 산출물에 VectorCAST 결과가 없습니다. (설정 > SCM 연결 문서 경로에 VectorCAST 로그 폴더를 등록하면 여기서 불러올 수 있습니다.)'}
          </div>
        )}
        <div className="stats-row">
          {effVcast.test_rows_count != null && (
            <div className="stat-card">
              <div className="stat-value">{effVcast.test_rows_count.toLocaleString()}</div>
              <div className="stat-label">테스트 케이스</div>
            </div>
          )}
          <div className="stat-card">
            <div className="stat-value">{(effVcast.ut_reports || []).length}</div>
            <div className="stat-label">UT 리포트</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{(effVcast.it_reports || []).length}</div>
            <div className="stat-label">IT 리포트</div>
          </div>
          {tester?.vectorcast_ut_line_rate != null && (
            <div className="stat-card">
              <div className="stat-value" style={{ color: tester.vectorcast_ut_line_rate >= 95 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                {tester.vectorcast_ut_line_rate.toFixed(1)}%
              </div>
              <div className="stat-label">UT Line Rate</div>
            </div>
          )}
          {tester?.vectorcast_ut_branch_rate != null && (
            <div className="stat-card">
              <div className="stat-value" style={{ color: tester.vectorcast_ut_branch_rate >= 95 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                {tester.vectorcast_ut_branch_rate.toFixed(1)}%
              </div>
              <div className="stat-label">UT Branch Rate</div>
            </div>
          )}
          {vc.metrics_avg_pct != null && (
            <div className="stat-card">
              <div className="stat-value">{vc.metrics_avg_pct.toFixed(1)}%</div>
              <div className="stat-label">메트릭 평균</div>
            </div>
          )}
        </div>
      </div>

      {/* ── Code Metrics ── */}
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-header"><span className="panel-title">코드 메트릭</span></div>
        <div className="stats-row">
          {cm.code_files != null && <div className="stat-card"><div className="stat-value">{cm.code_files}</div><div className="stat-label">소스 파일</div></div>}
          {cm.functions != null && <div className="stat-card"><div className="stat-value">{cm.functions}</div><div className="stat-label">함수 수</div></div>}
          {cm.nloc != null && <div className="stat-card"><div className="stat-value">{cm.nloc.toLocaleString()}</div><div className="stat-label">NLOC</div></div>}
          {hmr.functions_total != null && <div className="stat-card"><div className="stat-value">{hmr.functions_total}</div><div className="stat-label">PRQA 분석 함수</div></div>}
        </div>
      </div>

      {/* ── PRQA Detail ── */}
      {prqa.rule_violation_count != null && (
        <div className="panel" style={{ marginBottom: 12 }}>
          <div className="panel-header"><span className="panel-title">PRQA 정적분석 상세</span></div>

          {/* Compliance bar */}
          {prqa.project_compliance_index != null && (
            <div style={{ marginBottom: 10 }}>
              <div className="row" style={{ justifyContent: 'space-between', marginBottom: 4 }}>
                <span className="text-sm" style={{ fontWeight: 600 }}>프로젝트 준수율</span>
                <span style={{ fontWeight: 700, color: prqa.project_compliance_index >= 90 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                  {prqa.project_compliance_index}%
                </span>
              </div>
              <div style={{ height: 8, borderRadius: 4, background: '#e5e7eb', overflow: 'hidden' }}>
                <div style={{ width: `${prqa.project_compliance_index}%`, height: '100%', borderRadius: 4,
                  background: prqa.project_compliance_index >= 90 ? 'var(--color-success)' : prqa.project_compliance_index >= 70 ? 'var(--color-warning)' : 'var(--color-danger)' }} />
              </div>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8, marginBottom: 10 }}>
            <div style={{ textAlign: 'center', padding: 8, background: 'var(--bg)', borderRadius: 6 }}>
              <div style={{ fontSize: 18, fontWeight: 700, color: prqa.rule_violation_count > 0 ? 'var(--color-warning)' : 'var(--color-success)' }}>{prqa.rule_violation_count}</div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>위반 건수</div>
            </div>
            <div style={{ textAlign: 'center', padding: 8, background: 'var(--bg)', borderRadius: 6 }}>
              <div style={{ fontSize: 18, fontWeight: 700 }}>{prqa.violated_rules ?? '-'}<span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }}>/{(prqa.violated_rules ?? 0) + (prqa.compliant_rules ?? 0)}</span></div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>위반/전체 규칙</div>
            </div>
            <div style={{ textAlign: 'center', padding: 8, background: 'var(--bg)', borderRadius: 6 }}>
              <div style={{ fontSize: 18, fontWeight: 700 }}>{prqa.file_compliance_index ?? '-'}%</div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>파일 준수율</div>
            </div>
            <div style={{ textAlign: 'center', padding: 8, background: 'var(--bg)', borderRadius: 6 }}>
              <div style={{ fontSize: 18, fontWeight: 700 }}>{prqa.diagnostic_count ?? '-'}</div>
              <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>진단 수</div>
            </div>
          </div>

          {/* HMR Complexity */}
          {hmr.functions_total && (
            <div style={{ padding: 10, background: 'var(--bg)', borderRadius: 6 }}>
              <div className="text-sm" style={{ fontWeight: 600, marginBottom: 6 }}>HIS Metrics (복잡도)</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>{hmr.functions_total}</div>
                  <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>분석 함수</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 16, fontWeight: 700, color: hmr.vg_max > threshold ? 'var(--color-danger)' : 'var(--color-success)' }}>{hmr.vg_max}</div>
                  <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>VG Max</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>{hmr.vg_p95}</div>
                  <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>VG P95</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: 16, fontWeight: 700 }}>{hmr.vg_mean?.toFixed(1)}</div>
                  <div style={{ fontSize: 9, color: 'var(--text-muted)' }}>VG 평균</div>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Complexity Table ── */}
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">함수 복잡도 상세</span>
          <button className="btn-sm" onClick={loadComplexity} disabled={complexityLoading}>
            {complexityLoading ? <span className="spinner" /> : '불러오기'}
          </button>
        </div>
        {rows.length > 0 ? (
          <>
            <div className="row" style={{ gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
              <input type="text" placeholder="함수명/파일 검색..." value={compFilter} onChange={e => setCompFilter(e.target.value)}
                style={{ flex: 1, minWidth: 150, padding: '5px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6 }} />
              <select value={compSort} onChange={e => setCompSort(e.target.value)}
                style={{ padding: '5px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6 }}>
                <option value="complexity">복잡도 높은 순</option>
                <option value="name">이름 순</option>
              </select>
              <span className="text-sm text-muted">{filteredRows.length}/{rows.length}건</span>
            </div>
            <div style={{ maxHeight: 350, overflowY: 'auto' }}>
              <table className="impact-table" style={{ fontSize: 10 }}>
                <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
                  <tr style={{ background: 'var(--bg)' }}><th>함수</th><th>파일</th><th>복잡도</th><th></th></tr>
                </thead>
                <tbody>
                  {filteredRows.slice(0, 100).map((r, i) => {
                    const cc = r.complexity ?? r.cc ?? 0;
                    return (
                      <tr key={i} style={{ background: cc > threshold ? '#fee2e2' : cc > threshold * 0.7 ? '#fef9c3' : undefined }}>
                        <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{r.function ?? r.name ?? '-'}</td>
                        <td className="text-sm" style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.file ?? r.path ?? '-'}</td>
                        <td style={{ textAlign: 'center' }}>
                          <StatusBadge tone={cc > threshold ? 'danger' : cc > threshold * 0.7 ? 'warning' : 'success'}>{cc}</StatusBadge>
                        </td>
                        <td style={{ width: 60 }}>
                          <div style={{ height: 6, borderRadius: 3, background: '#e5e7eb' }}>
                            <div style={{ width: `${Math.min(cc / 30 * 100, 100)}%`, height: '100%', borderRadius: 3,
                              background: cc > threshold ? 'var(--color-danger)' : cc > threshold * 0.7 ? 'var(--color-warning)' : 'var(--color-success)' }} />
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {filteredRows.length > 100 && <div className="text-muted text-sm" style={{ padding: 6, textAlign: 'center' }}>{filteredRows.length - 100}건 더 있음</div>}
          </>
        ) : complexity ? (
          <div className="text-muted text-sm" style={{ padding: 12 }}>
            이 빌드에 complexity.csv가 없습니다 — 복잡도 데이터가 동기화되지 않았습니다.
            (PRQA HMR 복잡도는 위 정적분석 상세 패널을 참고하세요.)
          </div>
        ) : (
          <div className="text-muted text-sm" style={{ padding: 12 }}>불러오기 버튼을 클릭하세요.</div>
        )}
      </div>
    </div>
  );
}
