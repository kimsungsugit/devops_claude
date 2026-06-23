import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { post, api } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';
import { defaultCacheRoot } from '../../api.js';

// VectorCAST 커버리지 셀({covered,total,rate}) → 통계 카드. rate는 0..1.
function covCard(label, cell) {
  if (!cell || !cell.total) return null;
  const pct = Math.round((typeof cell.rate === 'number' ? cell.rate : cell.covered / cell.total) * 100);
  const color = pct >= 80 ? 'var(--color-success)' : 'var(--color-warning)';
  return (
    <div className="stat-card" style={{ borderLeft: `3px solid ${color}` }}>
      <div className="stat-value" style={{ color }}>{pct}%</div>
      <div className="stat-label">{label}</div>
      <div className="text-muted" style={{ fontSize: 9 }}>{cell.covered?.toLocaleString()}/{cell.total?.toLocaleString()}</div>
    </div>
  );
}

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
    ? {
        test_rows_count: scmVcast.data.test_rows_count,
        ut_reports: scmVcast.data.ut_reports || [],
        it_reports: scmVcast.data.it_reports || [],
        summary: scmVcast.data.summary || null,      // 통과/실패/pass_rate (P2)
        failures: scmVcast.data.failures || [],       // 실패 testcase 목록 (P2)
        _source: scmVcast.source || 'cloudium',
      }
    : buildVcast;
  const utCov = vc.ut || {};
  const itCov = vc.it || {};
  const modules = utCov.modules || [];
  // SCM 경로에서 불러온 VectorCAST 커버리지(구문/분기/MC-DC) — 빌드에 커버리지가 없을 때 표시.
  const scmCov = scmVcast?.data?.coverage || null;        // 전체(UT+IT)
  const scmCovUt = scmVcast?.data?.coverage_ut || null;
  const scmCovIt = scmVcast?.data?.coverage_it || null;
  const scmCovHas = !!(scmCov && (scmCov.statement?.total || scmCov.branch?.total || scmCov.mcdc?.total));
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
    || utCov.line_covered != null || utCov.branch_covered != null || modules.length > 0 || scmCovHas;

  // Complexity table — 빌드 complexity.csv가 없으면 SCM VectorCAST 폴더에서 추출한
  // 함수별 복잡도(complexity_rows)로 폴백(async VectorCAST 로드 시 자동 표시).
  const rows = complexity?.rows ?? complexity?.functions ?? scmVcast?.data?.complexity_rows ?? [];
  const filteredRows = useMemo(() => {
    let items = [...rows];
    if (compFilter.trim()) {
      const q = compFilter.trim().toLowerCase();
      items = items.filter(r => (r.function ?? r.name ?? '').toLowerCase().includes(q) || (r.file ?? r.path ?? '').toLowerCase().includes(q));
    }
    items.sort((a, b) => {
      if (compSort === 'complexity') return (b.complexity ?? b.cc ?? b.ccn ?? 0) - (a.complexity ?? a.cc ?? a.ccn ?? 0);
      if (compSort === 'name') return (a.function ?? a.name ?? '').localeCompare(b.function ?? b.name ?? '');
      return 0;
    });
    return items;
  }, [rows, compFilter, compSort]);

  // 복잡도 분포 히스토그램(표 위 차트) — 임계값(threshold) 정렬 4구간, 색상은 표 행과 동일 위험도.
  // ISO 26262 HIS VG 관리 관점에서 임계 초과 함수 비중을 한눈에. 외부 차트 라이브러리 없이 순수 div.
  const compDist = useMemo(() => {
    const ccs = rows
      .map(r => r.complexity ?? r.cc ?? r.ccn ?? 0)
      .filter(v => typeof v === 'number' && !Number.isNaN(v) && v > 0);
    if (!ccs.length) return null;
    const t = threshold;
    const wEnd = Math.max(1, Math.floor(t * 0.7));   // success 상한(표 행 `cc > t*0.7` 경계와 일치)
    const edges = [
      { label: `1–${wEnd}`, lo: 1, hi: wEnd, tone: 'success' },
      { label: `${wEnd + 1}–${t}`, lo: wEnd + 1, hi: t, tone: 'warning' },
      { label: `${t + 1}–${t * 2}`, lo: t + 1, hi: t * 2, tone: 'danger' },
      { label: `${t * 2 + 1}+`, lo: t * 2 + 1, hi: Infinity, tone: 'danger' },
    ];
    const buckets = edges.map(e => ({ ...e, count: ccs.filter(v => v >= e.lo && v <= e.hi).length }));
    const maxCount = Math.max(1, ...buckets.map(b => b.count));
    const total = ccs.length;
    return {
      buckets, maxCount, total,
      max: Math.max(...ccs),
      avg: ccs.reduce((a, b) => a + b, 0) / total,
      over: ccs.filter(v => v > t).length,
    };
  }, [rows, threshold]);

  return (
    <div>
      {/* ── Coverage Detail ── */}
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-header"><span className="panel-title">코드 커버리지</span></div>
        {!hasAnyCoverage ? (
          <div className="text-sm text-muted" style={{ padding: 8 }}>
            이 빌드 산출물에 커버리지 데이터가 없습니다 (line_rate 0). 이 프로젝트의 커버리지는
            VectorCAST 시험 로그(SCM 등록 경로)에 있습니다 — 아래 &apos;VectorCAST 테스트&apos; 패널의
            &apos;SCM 경로에서 불러오기&apos;를 누르면 구문/분기 커버리지가 여기 표시됩니다(단위시험 로그 기준,
            수 분 소요). 통합시험(IT)은 함수 커버리지라 구문/분기 수치는 없습니다.
          </div>
        ) : (<>
        {scmCovHas && (
          <div style={{ marginBottom: 8 }}>
            <div className="text-sm text-muted" style={{ marginBottom: 4 }}>
              VectorCAST 커버리지 (출처: SCM 경로 — 단위/통합 합산)
            </div>
            <div className="stats-row">
              {covCard('구문(Statement)', scmCov.statement)}
              {covCard('분기(Branch)', scmCov.branch)}
              {covCard('MC/DC', scmCov.mcdc)}
            </div>
          </div>
        )}
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

        {/* 시험 합부(pass/fail) — 백엔드 summary를 표면화(P2). 케이스 건수만 보이고 합부가 안 보이던 결함 수정. */}
        {effVcast.summary && (effVcast.summary.total || 0) > 0 && (
          <div className="stats-row" style={{ marginTop: 8 }}>
            <div className="stat-card" style={{ borderLeft: '3px solid var(--color-success)' }}>
              <div className="stat-value" style={{ color: 'var(--color-success)' }}>{(effVcast.summary.passed ?? 0).toLocaleString()}</div>
              <div className="stat-label">통과</div>
            </div>
            <div className="stat-card" style={{ borderLeft: `3px solid ${(effVcast.summary.failed ?? 0) > 0 ? 'var(--color-danger)' : 'var(--color-success)'}` }}>
              <div className="stat-value" style={{ color: (effVcast.summary.failed ?? 0) > 0 ? 'var(--color-danger)' : 'var(--color-success)' }}>{(effVcast.summary.failed ?? 0).toLocaleString()}</div>
              <div className="stat-label">실패</div>
            </div>
            {(effVcast.summary.skipped ?? 0) > 0 && (
              <div className="stat-card"><div className="stat-value">{effVcast.summary.skipped.toLocaleString()}</div><div className="stat-label">스킵</div></div>
            )}
            {effVcast.summary.pass_rate != null && (
              <div className="stat-card" style={{ borderLeft: `3px solid ${effVcast.summary.pass_rate >= 0.95 ? 'var(--color-success)' : 'var(--color-warning)'}` }}>
                <div className="stat-value" style={{ color: effVcast.summary.pass_rate >= 0.95 ? 'var(--color-success)' : 'var(--color-warning)' }}>{Math.round(effVcast.summary.pass_rate * 100)}%</div>
                <div className="stat-label">통과율</div>
              </div>
            )}
          </div>
        )}
        {(effVcast.failures || []).length > 0 && (
          <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: 'pointer', fontSize: 12, fontWeight: 600, color: 'var(--color-danger)' }}>
              실패 테스트케이스 ({effVcast.failures.length}건)
            </summary>
            <div style={{ maxHeight: 250, overflowY: 'auto', marginTop: 6 }}>
              <table className="impact-table" style={{ fontSize: 10 }}>
                <thead><tr><th>테스트케이스</th><th>함수(subprogram)</th><th>유닛</th><th>출처</th></tr></thead>
                <tbody>
                  {effVcast.failures.slice(0, 100).map((f, i) => (
                    <tr key={i} style={{ background: '#fee2e2' }}>
                      <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{f.testcase ?? '-'}</td>
                      <td style={{ fontFamily: 'monospace', fontSize: 10 }}>{f.subprogram ?? '-'}</td>
                      <td className="text-sm" style={{ maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.unit ?? '-'}</td>
                      <td style={{ textAlign: 'center' }}>{f.source ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {effVcast.failures.length > 100 && <div className="text-muted text-sm" style={{ padding: 6, textAlign: 'center' }}>{effVcast.failures.length - 100}건 더 있음</div>}
          </details>
        )}
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
            {compDist && (
              <div style={{ marginBottom: 10, padding: 10, background: 'var(--bg)', borderRadius: 6 }}>
                <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8, flexWrap: 'wrap', gap: 6 }}>
                  <span className="text-sm" style={{ fontWeight: 600 }}>복잡도 분포</span>
                  <span className="text-sm text-muted">
                    함수 {compDist.total.toLocaleString()} · 최대 {compDist.max} · 평균 {compDist.avg.toFixed(1)} ·{' '}
                    <span style={{ color: compDist.over > 0 ? 'var(--color-danger)' : 'var(--color-success)', fontWeight: 600 }}>
                      임계(&gt;{threshold}) 초과 {compDist.over}
                    </span>
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height: 92 }}>
                  {compDist.buckets.map((b, i) => {
                    const h = Math.round((b.count / compDist.maxCount) * 72);
                    const col = `var(--color-${b.tone})`;
                    const pct = compDist.total ? Math.round((b.count / compDist.total) * 100) : 0;
                    return (
                      <div key={i} title={`${b.label}: ${b.count}개 (${pct}%)`}
                        style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end', height: '100%' }}>
                        <div style={{ fontSize: 10, fontWeight: 700, color: b.count ? col : 'var(--text-muted)', marginBottom: 2 }}>{b.count}</div>
                        <div style={{ width: '100%', height: Math.max(b.count ? 3 : 0, h), background: col, opacity: b.count ? 1 : 0.18, borderRadius: '3px 3px 0 0' }} />
                        <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 3, whiteSpace: 'nowrap' }}>{b.label}</div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
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
                    const cc = r.complexity ?? r.cc ?? r.ccn ?? 0;
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
            {scmVcastPaths.length > 0
              ? ' 위 \'VectorCAST 테스트\' 패널의 \'SCM 경로에서 불러오기\'를 누르면 SCM VectorCAST 함수별 복잡도가 여기 표시됩니다.'
              : ' (PRQA HMR 복잡도는 위 정적분석 상세 패널을 참고하세요.)'}
          </div>
        ) : (
          <div className="text-muted text-sm" style={{ padding: 12 }}>불러오기 버튼을 클릭하세요.</div>
        )}
      </div>
    </div>
  );
}
