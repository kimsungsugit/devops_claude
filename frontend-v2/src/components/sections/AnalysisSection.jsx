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

// 복잡도 값 추출 — 빌드 complexity.csv는 ccn을 '문자열'로 반환(read_csv_rows)하므로 Number 강제.
// SCM complexity_rows는 complexity(int). 비유효값은 0. (문자열이면 typeof 필터/비교가 깨져 차트 누락)
function ccOf(r) {
  const v = Number(r?.complexity ?? r?.cc ?? r?.ccn);
  return Number.isFinite(v) ? v : 0;
}

// 복잡도 × 커버리지 산포도 — 各 점=함수, X=구문 커버리지%, Y=CC. 좌상단(高복잡·低커버) = ISO 26262
// MC/DC 보강 1순위 사분면(음영). 단일 변수 막대 분포가 못 보여주는 '복잡한데 안 짜인 테스트'를 한눈에.
// 외부 차트 라이브러리 없이 순수 SVG(프로젝트 규칙: 막대 분포도 div로 그림). props는 join 완료된 points.
function ComplexityScatter({ points, naCount, yMax, threshold }) {
  const [hover, setHover] = useState(null);   // 마우스 올린 포인트 { p, x, y } | null
  const W = 480, H = 200, ML = 36, MR = 12, MT = 12, MB = 26;
  const pw = W - ML - MR, ph = H - MT - MB;
  const ym = yMax || 1;
  const xOf = (cov) => ML + (Math.max(0, Math.min(100, cov)) / 100) * pw;
  const yOf = (cc) => MT + (1 - Math.min(Math.max(cc, 0), ym) / ym) * ph;
  const thY = yOf(threshold);
  const x80 = xOf(80);
  const counts = { danger: 0, warning: 0, success: 0 };
  for (const p of points) counts[p.tone] = (counts[p.tone] || 0) + 1;
  return (
    <div style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="복잡도-커버리지 산포도"
        style={{ maxHeight: 240, display: 'block', overflow: 'visible' }}>
        {/* 위험 사분면(高복잡·低커버) 음영 */}
        <rect x={ML} y={MT} width={Math.max(0, x80 - ML)} height={Math.max(0, thY - MT)}
          fill="var(--color-danger)" opacity="0.07" />
        {/* 임계선(가로) / 80% 선(세로) */}
        <line x1={ML} y1={thY} x2={W - MR} y2={thY} stroke="var(--color-danger)" strokeOpacity="0.5" strokeDasharray="3 3" />
        <line x1={x80} y1={MT} x2={x80} y2={H - MB} stroke="var(--color-warning)" strokeOpacity="0.6" strokeDasharray="3 3" />
        {/* 축 */}
        <line x1={ML} y1={H - MB} x2={W - MR} y2={H - MB} stroke="var(--border)" />
        <line x1={ML} y1={MT} x2={ML} y2={H - MB} stroke="var(--border)" />
        {[0, 25, 50, 75, 100].map(t => (
          <text key={`x${t}`} x={xOf(t)} y={H - MB + 12} fontSize="8" fill="var(--text-muted)" textAnchor="middle">{t}</text>
        ))}
        {[0, threshold, Math.round(ym)].map((t, i) => (
          <text key={`y${i}`} x={ML - 4} y={yOf(t) + 3} fontSize="8" fill="var(--text-muted)" textAnchor="end">{t}</text>
        ))}
        <text x={x80 + 3} y={MT + 9} fontSize="8" fill="var(--color-danger)" opacity="0.85">위험</text>
        {points.map((p, i) => {
          // 정수 격자 과겹침 완화용 결정적 지터(±, Math.random 미사용 → 안정 렌더)
          const jx = (((i * 73) % 5) - 2) * 0.6;
          const jy = (((i * 37) % 5) - 2) * 0.6;
          const isHover = hover?.p === p;
          return (
            <circle key={i} cx={xOf(p.cov) + jx} cy={yOf(p.cc) + jy} r={isHover ? 4.5 : 3}
              fill={`var(--color-${p.tone})`} fillOpacity={isHover ? 0.95 : 0.6}
              stroke={isHover ? 'var(--text, #111)' : 'none'} strokeWidth={isHover ? 0.8 : 0}
              style={{ cursor: 'pointer' }}
              onMouseEnter={(e) => setHover({ p, x: e.clientX, y: e.clientY })}
              onMouseLeave={() => setHover(null)} />
          );
        })}
      </svg>
      <div className="row" style={{ gap: 10, flexWrap: 'wrap', fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>
        <span>X=커버리지(구문%) · Y=복잡도(CC)</span>
        <span style={{ color: 'var(--color-danger)', fontWeight: 600 }}>● 위험 {counts.danger}</span>
        <span style={{ color: 'var(--color-warning)', fontWeight: 600 }}>● 주의 {counts.warning}</span>
        <span style={{ color: 'var(--color-success)', fontWeight: 600 }}>● 양호 {counts.success}</span>
        {naCount > 0 && <span>커버리지 미상 {naCount}(산포 제외)</span>}
      </div>
      {hover && (
        <div data-testid="scatter-tooltip" style={{ position: 'fixed', left: hover.x + 12, top: hover.y + 12,
          zIndex: 50, pointerEvents: 'none', maxWidth: 260, padding: '6px 8px', fontSize: 11,
          background: 'var(--panel, #fff)', border: '1px solid var(--border)', borderRadius: 6,
          boxShadow: '0 2px 8px rgba(0,0,0,0.18)' }}>
          <div style={{ fontWeight: 700, fontFamily: 'monospace', wordBreak: 'break-all' }}>{hover.p.fn}</div>
          <div className="text-muted" style={{ fontSize: 10, wordBreak: 'break-all', marginBottom: 2 }}>{hover.p.file}</div>
          <div>복잡도 <b style={{ color: `var(--color-${hover.p.tone})` }}>{hover.p.cc}</b> · 구문 {hover.p.cov}%
            {hover.p.br != null ? ` · 분기 ${hover.p.br}%` : ''}{hover.p.mc != null ? ` · MC/DC ${hover.p.mc}%` : ''}</div>
        </div>
      )}
    </div>
  );
}

// 진행 중·완료된 SCM VectorCAST 잡을 job_url 단위로 보존한다. 원격 cloudium 파싱은 수 분 걸리는데,
// 그 사이 탭 전환·새로고침·job 변경(remount)·브라우저 백그라운드 throttle로 in-memory 폴링 루프가
// 끊기면 결과가 UI에 영영 안 실리고 스피너만 고착됐다. job_id를 남겨두면 재진입/포커스 복귀 시
// 폴링을 재개(완료면 즉시 적재)해 자동 복구한다.
const VCAST_JOB_KEY = 'devops_v2_vcast_jobs';
function _readVcastJobs() {
  try { return JSON.parse(localStorage.getItem(VCAST_JOB_KEY) || '{}') || {}; }
  catch { return {}; }
}
function saveVcastJob(jobUrl, jobId, startedAt) {
  if (!jobUrl || !jobId) return;
  const m = _readVcastJobs();
  // 실제 시작시각을 보존해야 재진입(remount/새로고침) 후에도 12분 timeout이 '원래 시작' 기준으로
  // 측정된다. 0(falsy)으로 저장하면 pollJob에서 t0가 Date.now()로 리셋돼 timeout이 무력화될 수 있다.
  m[jobUrl] = { jobId, startedAt: startedAt || Date.now() };
  try { localStorage.setItem(VCAST_JOB_KEY, JSON.stringify(m)); } catch { /* quota — best-effort */ }
}
function loadVcastJob(jobUrl) {
  if (!jobUrl) return null;
  const e = _readVcastJobs()[jobUrl];
  return (e && e.jobId) ? e : null;
}
function clearVcastJob(jobUrl) {
  if (!jobUrl) return;
  const m = _readVcastJobs();
  if (m[jobUrl] !== undefined) {
    delete m[jobUrl];
    try { localStorage.setItem(VCAST_JOB_KEY, JSON.stringify(m)); } catch { /* best-effort */ }
  }
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
  // StrictMode(dev)는 effect를 setup→cleanup→setup으로 이중 호출한다. cleanup만 두면 cleanup이
  // mountedRef를 false로 만든 뒤 재-setup이 복원하지 않아, mountedRef가 마운트 직후부터 false로
  // 고정된다 → 폴링 while(mountedRef.current)가 영영 안 돌고(=impact-job 요청 0), finally의
  // setScmVcastLoading(false)도 스킵돼 스피너가 고착된다. setup에서 매번 true로 복원해야 한다.
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  // 동시 폴링 루프 방지 — start/resume/focus 복구가 겹쳐도 한 번에 하나만 돈다.
  const pollingRef = useRef(false);

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

  // 잡 상태를 폴링해 완료 시 결과를 적재한다. 최초 시작과 재진입/포커스 복구가 공용으로 호출한다.
  // poll-first 구조라 '이미 완료된 잡'으로 재진입하면 첫 폴에서 즉시 적재된다(3초 대기 없음).
  // jobUrl은 호출 시점의 job.url을 명시 전달받는다 — 클로저의 job?.url에 의존하면, keep-alive로
  // 같은 인스턴스에서 job prop만 바뀌는(향후 key 구조 변경) 경우 구 job의 보존 잡을 지울 수 있다(X1).
  const pollJob = useCallback(async (jobId, startedAtMs, jobUrl) => {
    if (!jobId || pollingRef.current) return;   // 중복 루프 차단
    pollingRef.current = true;
    if (mountedRef.current) setScmVcastLoading(true);
    const t0 = startedAtMs || Date.now();
    const TIMEOUT_MS = 12 * 60 * 1000;   // 12분 상한(최악 다폴더 파싱 + 여유). 보존된 시작시각 기준.
    try {
      while (mountedRef.current) {
        let st;
        try {
          st = await api(`/api/scm/impact-job/${jobId}`);
        } catch (e) {
          // 404(서버 재시작/프룬으로 잡 유실)·네트워크 오류 → 보존 잡 제거 후 종료(되살아나는 무한 폴링 방지).
          clearVcastJob(jobUrl);
          if (mountedRef.current && !/not found|404/i.test(String(e?.message || ''))) {
            toast('error', `VectorCAST 상태 조회 실패: ${e.message}`);
          }
          return;
        }
        const status = st?.job?.status;
        if (status === 'completed') {
          const data = st.job.result;
          clearVcastJob(jobUrl);
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
          clearVcastJob(jobUrl);
          if (mountedRef.current) toast('error', `VectorCAST 로드 실패: ${st.job?.error?.title || st.job?.error?.detail || 'unknown'}`);
          return;
        }
        if (Date.now() - t0 > TIMEOUT_MS) {
          clearVcastJob(jobUrl);
          if (mountedRef.current) toast('warning', 'VectorCAST 로딩 시간 초과 — 다시 시도하세요(캐시되어 빨라집니다).');
          return;
        }
        await new Promise(r => setTimeout(r, 3000));
        // queued/running → 계속 폴링
      }
    } finally {
      pollingRef.current = false;
      if (mountedRef.current) setScmVcastLoading(false);
    }
  }, [toast]);

  const loadScmVcast = useCallback(async () => {
    const paths = analysisResult?.matchedScm?.linked_docs?.vectorcast || [];
    if (!paths.length) { toast('info', 'SCM에 등록된 VectorCAST 경로가 없습니다.'); return; }
    if (pollingRef.current) return;   // 이미 진행 중 — 중복 잡 생성 방지
    setScmVcastLoading(true);   // 즉시 버튼 비활성/스피너 (POST 왕복 동안 더블클릭 차단)
    let jobId;
    try {
      // 원격 cloudium 폴더 파싱은 수 분 걸려 동기 호출 시 4~5분 블로킹(타임아웃/언마운트 abort로
      // '에러'처럼 보임) → 백그라운드 잡으로 던지고 폴링한다. 백엔드 TTL 캐시(30분)로 2회차+ 즉시.
      const start = await post('/api/jenkins/report/vectorcast-rag-async', {
        job_url: job.url, cache_root: cacheRoot, build_selector: cfg.buildSelector,
        vcast_log_paths: paths,
      });
      jobId = start?.job_id;
      if (!jobId) throw new Error('잡 생성에 실패했습니다.');
    } catch (e) {
      if (mountedRef.current) { toast('error', `VectorCAST 로드 실패: ${e.message}`); setScmVcastLoading(false); }
      return;
    }
    const startedAt = Date.now();
    saveVcastJob(job?.url, jobId, startedAt);   // 새로고침/탭이동/remount에도 재진입 자동복구되도록 보존
    toast('info', 'VectorCAST 원격 로그 파싱을 시작했습니다 (수 분 소요될 수 있습니다).');
    await pollJob(jobId, startedAt, job?.url);
  }, [analysisResult, job, cfg, cacheRoot, toast, pollJob]);

  // 재진입 자동복구(mount·job 변경 remount·새로고침) — 보존된 진행 중/완료 잡이 있으면 폴링 재개.
  // 완료된 잡이면 poll-first로 즉시 결과가 채워져, 사용자가 재클릭하지 않아도 데이터가 뜬다.
  useEffect(() => {
    if (!job?.url || scmVcast || pollingRef.current) return;
    const saved = loadVcastJob(job.url);
    if (saved?.jobId) pollJob(saved.jobId, saved.startedAt, job.url);
  }, [job, scmVcast, pollJob]);

  // 포커스 복구 — keep-alive(언마운트 안 함)에서 브라우저 백그라운드 throttle로 setTimeout 폴링이
  // 멎은 채 탭으로 돌아온 경우, 진행 중 잡을 재확인한다(중복 루프는 pollingRef로 차단).
  useEffect(() => {
    const recover = () => {
      if (document.hidden || scmVcast || pollingRef.current || !job?.url) return;
      const saved = loadVcastJob(job.url);
      if (saved?.jobId) pollJob(saved.jobId, saved.startedAt, job.url);
    };
    window.addEventListener('focus', recover);
    document.addEventListener('visibilitychange', recover);
    return () => {
      window.removeEventListener('focus', recover);
      document.removeEventListener('visibilitychange', recover);
    };
  }, [job, scmVcast, pollJob]);

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
  // threshold 정규화 — localStorage 오염(빈문자/0/음수/문자열)이 버킷 라벨/비교를 깨지 않도록 1~200 클램프.
  let threshold = Number(qualityCfg.complexity);
  if (!Number.isFinite(threshold) || threshold < 1) threshold = 15;
  threshold = Math.min(threshold, 200);

  // Coverage as number
  const covPct = typeof rd?.coverage === 'number' ? rd.coverage
    : (cov.line_rate != null ? Math.round(cov.line_rate * 100) : null);
  const brPct = cov.branch_rate != null ? Math.round(cov.branch_rate * 100) : null;
  // VectorCAST SCM 커버리지(구문/분기/MC-DC)가 표시될 때, 빌드 산출물 기준 Line/Branch가 0%
  // (이 프로젝트는 빌드 라인커버리지 미계측 → 항상 0)이면 그 카드를 숨긴다. 'Line 0%'가
  // 'Statement 70%' 옆에 같이 보여 라인커버리지가 0인 것처럼 오인되는 것을 막는다. 빌드에 실제
  // 커버리지가 있는 프로젝트(0이 아님)는 그대로 표시한다.
  const showBuildLine = covPct != null && !(scmCovHas && covPct === 0);
  const showBuildBranch = brPct != null && !(scmCovHas && brPct === 0);
  // 빌드 산출물에 실제 커버리지가 있는지 — line_rate=0.0(데이터 없음)을 '0% 미검증'으로 오인하지
  // 않도록. 이 프로젝트는 일반 커버리지가 아니라 VectorCAST UT/IT 커버리지를 쓰며 그 데이터는
  // cloudium SCM 로그에 있다(빌드엔 미동기화 → covPct=0).
  const hasAnyCoverage = (covPct != null && covPct > 0) || (brPct != null && brPct > 0)
    || utCov.line_covered != null || utCov.branch_covered != null || modules.length > 0 || scmCovHas;

  // Complexity table — 빌드 complexity.csv가 없으면 SCM VectorCAST 폴더에서 추출한
  // 함수별 복잡도(complexity_rows)로 폴백(async VectorCAST 로드 시 자동 표시).
  // 빌드 complexity 응답이 비어도({rows:[]}) SCM 폴백이 nullish 단락으로 가려지지 않도록 길이 기반 폴백.
  const buildComplexityRows = complexity?.rows ?? complexity?.functions ?? [];
  const rows = buildComplexityRows.length ? buildComplexityRows : (scmVcast?.data?.complexity_rows ?? []);
  const filteredRows = useMemo(() => {
    let items = [...rows];
    if (compFilter.trim()) {
      const q = compFilter.trim().toLowerCase();
      items = items.filter(r => (r.function ?? r.name ?? '').toLowerCase().includes(q) || (r.file ?? r.path ?? '').toLowerCase().includes(q));
    }
    items.sort((a, b) => {
      if (compSort === 'complexity') return ccOf(b) - ccOf(a);
      if (compSort === 'name') return (a.function ?? a.name ?? '').localeCompare(b.function ?? b.name ?? '');
      return 0;
    });
    return items;
  }, [rows, compFilter, compSort]);

  // 복잡도 분포 히스토그램(표 위 차트) — 임계값(threshold) 정렬 4구간, 색상은 표 행과 동일 위험도.
  // ISO 26262 HIS VG 관리 관점에서 임계 초과 함수 비중을 한눈에. 외부 차트 라이브러리 없이 순수 div.
  const compDist = useMemo(() => {
    const ccs = rows.map(ccOf).filter(v => v > 0);   // ccOf가 Number 강제(문자열 ccn도 정상 집계)
    if (!ccs.length) return null;
    const t = threshold;   // 이미 1~200로 정규화됨
    const wEnd = Math.max(1, Math.floor(t * 0.7));   // success 상한(표 행 `cc > t*0.7` 경계와 일치)
    const edges = [
      { label: `1–${wEnd}`, lo: 1, hi: wEnd, tone: 'success' },
      { label: `${wEnd + 1}–${t}`, lo: wEnd + 1, hi: t, tone: 'warning' },
      { label: `${t + 1}–${t * 2}`, lo: t + 1, hi: t * 2, tone: 'danger' },
      { label: `${t * 2 + 1}+`, lo: t * 2 + 1, hi: Infinity, tone: 'danger' },
    ].filter(e => e.lo <= e.hi);   // threshold 경계에서 역전(lo>hi) 버킷 제거
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

  // 산포도 데이터(복잡도 × 커버리지) — complexity_rows(CC)에 함수별 커버리지(vcast_summary.entries)를
  // (unit, function/subprogram) 키로 join. 빌드 complexity.csv 경로엔 entries가 없어 join 0건 → 산포 미가용.
  // X=구문 커버리지%, Y=CC. 색: 高복잡&低커버=danger, 둘 중 하나=warning, 양호=success(임계/80% 경계).
  const compScatter = useMemo(() => {
    const vs = scmVcast?.data?.vcast_summary;
    if (!vs || typeof vs !== 'object') return { points: [], naCount: 0, yMax: 0 };
    // ut/it entries 합치기 → (unit,subprogram) & subprogram-only 두 맵. 중복 키는 statements.total 큰(증거 많은) 쪽.
    const byKey = new Map();   // `${unit} ${fn}` → entry
    const byFn = new Map();    // fn → entry(폴백: unit 표기 불일치 대비)
    const better = (e, prev) => !prev || (e?.statements?.total || 0) > (prev?.statements?.total || 0);
    for (const mk of ['ut_metrics', 'it_metrics']) {
      const arr = vs?.[mk]?.entries;
      if (!Array.isArray(arr)) continue;
      for (const e of arr) {
        const fn = (e?.subprogram ?? '').trim();
        if (!fn) continue;
        const unit = (e?.unit ?? '').trim();
        const k = `${unit} ${fn}`;
        if (better(e, byKey.get(k))) byKey.set(k, e);
        if (better(e, byFn.get(fn))) byFn.set(fn, e);
      }
    }
    const cellPct = (c) => (c && c.total
      ? Math.round((typeof c.rate === 'number' ? c.rate : c.covered / c.total) * 100) : null);
    const points = [];
    let naCount = 0;
    for (const r of rows) {
      const cc = ccOf(r);
      if (cc <= 0) continue;
      const unit = (r.unit ?? r.file ?? '').trim();
      const fn = (r.function ?? r.name ?? '').trim();
      const e = byKey.get(`${unit} ${fn}`) || byFn.get(fn);
      const stPct = cellPct(e?.statements);
      if (stPct == null) { naCount++; continue; }   // 커버리지 미상은 X=0 위장 대신 산포 제외
      const ccBad = cc > threshold;
      const covBad = stPct < 80;
      const tone = ccBad && covBad ? 'danger' : (ccBad || covBad ? 'warning' : 'success');
      points.push({
        fn, file: r.file ?? r.unit ?? '-', cc, cov: stPct,
        br: cellPct(e?.branches), mc: cellPct(e?.pairs), tone,
      });
    }
    // Math.max(...spread)는 수만 함수 규모에서 스택 한계 → reduce로 선형 누적(W2).
    const yMax = points.reduce((m, p) => (p.cc > m ? p.cc : m), points.length ? threshold * 2 : 0);
    return { points, naCount, yMax };
  }, [rows, scmVcast, threshold]);

  const scatterAvailable = compScatter.points.length > 0;

  return (
    <div>
      {/* ── Coverage Detail ── */}
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-header"><span className="panel-title">코드 커버리지</span></div>
        <div className="text-sm text-muted" style={{ padding: '0 0 8px', lineHeight: 1.55 }}>
          테스트가 소스 코드를 실제로 얼마나 실행했는지의 비율입니다. <b>구문</b>=실행된 문장,{' '}
          <b>분기</b>=if·switch 등 분기 경로, <b>MC/DC 커버리지</b>=조건 조합(ASIL C/D 필수).{' '}
          구문/분기/MC-DC 카드는 VectorCAST(SCM 경로), Line/Branch Coverage는 빌드 산출물 기준이며 80% 미만은 주황색으로 강조됩니다.
        </div>
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
          {showBuildLine && (
            <div className="stat-card" style={{ borderLeft: `3px solid ${covPct >= 80 ? 'var(--color-success)' : 'var(--color-warning)'}` }}>
              <div className="stat-value" style={{ color: covPct >= 80 ? 'var(--color-success)' : 'var(--color-warning)' }}>{covPct}%</div>
              <div className="stat-label">Line Coverage</div>
            </div>
          )}
          {showBuildBranch && (
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
        <div className="text-sm text-muted" style={{ padding: '0 0 8px', lineHeight: 1.55 }}>
          VectorCAST 단위시험(UT)·통합시험(IT) 실행 결과입니다. <b>테스트 케이스</b>=총 시험 수,{' '}
          <b>UT/IT 리포트</b>=병합된 리포트 폴더 수, <b>통과·실패·통과율</b>=시험 합부.{' '}
          <b>UT Line/Branch Rate</b>는 단위시험이 달성한 라인·분기 커버리지이며, ASIL C/D는 통과율 100%·무실패가 권장됩니다.
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
        <div className="text-sm text-muted" style={{ padding: '0 0 8px', lineHeight: 1.55 }}>
          코드 규모 지표입니다. <b>소스 파일</b>=분석 대상 파일 수, <b>함수 수</b>=정의된 함수 개수,{' '}
          <b>NLOC</b>=주석·공백을 뺀 순수 코드 라인 수(Non-comment Lines Of Code),{' '}
          <b>PRQA 분석 함수</b>=정적분석(Helix QAC) 대상 함수 수.
        </div>
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
          <div className="text-sm text-muted" style={{ padding: '0 0 8px', lineHeight: 1.55 }}>
            Helix QAC(PRQA) 정적분석 결과입니다. <b>준수율</b>=MISRA-C 등 코딩 규칙 대비 적합 비율(90% 미만 경고),{' '}
            <b>위반 건수</b>=규칙 위반 총량, <b>위반/전체 규칙</b>=위반된 규칙 종류, <b>진단 수</b>=개별 진단 메시지 수.{' '}
            <b>HIS Metrics</b>는 함수 순환복잡도(VG, McCabe)의 최대·P95·평균이며 임계값({threshold}) 초과 시 위험입니다.
          </div>

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
        <div className="text-sm text-muted" style={{ padding: '0 0 8px', lineHeight: 1.55 }}>
          각 함수의 <b>순환복잡도</b>(Cyclomatic Complexity, 독립 실행 경로 수)입니다. 값이 클수록 분기가 많아 테스트·유지보수가 어렵습니다.{' '}
          임계값({threshold}) 초과는 빨강, 임계값의 70% 이상은 주황으로 표시합니다. <b>막대</b>는 복잡도 구간별 함수 수 분포,{' '}
          <b>산포도</b>는 복잡도(세로)×커버리지(가로)로 ‘복잡한데 덜 테스트된’ 위험 함수(좌상단)를 보여줍니다.
        </div>
        {rows.length > 0 ? (
          <>
            {compDist && (
              <div style={{ marginBottom: 10 }}>
                <div className="row" style={{ justifyContent: 'space-between', marginBottom: 8, flexWrap: 'wrap', gap: 6 }}>
                  <span className="text-sm" style={{ fontWeight: 600 }}>복잡도 분포</span>
                  <span className="text-sm text-muted">
                    함수 {compDist.total.toLocaleString()} · 최대 {compDist.max} · 평균 {compDist.avg.toFixed(1)} ·{' '}
                    <span style={{ color: compDist.over > 0 ? 'var(--color-danger)' : 'var(--color-success)', fontWeight: 600 }}>
                      임계(&gt;{threshold}) 초과 {compDist.over}
                    </span>
                  </span>
                </div>
                {/* 막대(좌)·산포도(우) 한 화면 — auto-fit으로 좁으면 세로 적층(인라인 grid가 미디어쿼리 덮어쓰는 문제 회피) */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>
                  <div style={{ padding: 10, background: 'var(--bg)', borderRadius: 6 }}>
                    <div className="text-sm" style={{ fontWeight: 600, marginBottom: 8 }}>구간별 함수 수 (막대)</div>
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
                  <div style={{ padding: 10, background: 'var(--bg)', borderRadius: 6 }}>
                    <div className="text-sm" style={{ fontWeight: 600, marginBottom: 8 }}>복잡도 × 커버리지 (산포도)</div>
                    {scatterAvailable ? (
                      <ComplexityScatter points={compScatter.points} naCount={compScatter.naCount}
                        yMax={compScatter.yMax} threshold={threshold} />
                    ) : (
                      <div className="text-sm text-muted" style={{ padding: 8, lineHeight: 1.5 }}>
                        커버리지가 로드되면 표시됩니다 — 위 ‘VectorCAST 테스트’의 ‘SCM 경로에서 불러오기’를 누르면
                        함수별 복잡도×커버리지가 산포도로 나타납니다.
                      </div>
                    )}
                  </div>
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
                    const cc = ccOf(r);
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
