import { useState, useEffect, useMemo, useCallback } from 'react';
import { post, api, defaultCacheRoot } from '../../api.js';
import { useToast, useJenkinsCfg } from '../../App.jsx';
import { pickScmForJob } from '../../projectLoader.js';
import { targetConsistent } from '../../impactGuard.js';
import { classifyGate } from '../ResultPanel.jsx';
import { buildTraceMatrix } from '../../traceMatrix.js';
import { clearArchMetricsCache } from '../../archMetricsCache.js';
import PipelineHealthStrip from './PipelineHealthStrip.jsx';
import SummaryOverviewTab from './SummaryOverviewTab.jsx';
import SummaryArchTab from './SummaryArchTab.jsx';
import SummarySourceTab from './SummarySourceTab.jsx';
import SummaryBuildTab from './SummaryBuildTab.jsx';
import { SHOW, PANEL, fmtInt } from './summaryCommon.js';

/**
 * ProjectSummarySection — "📈 프로젝트 분석" 탭 (구 '프로젝트 요약'. 탭 id는 'summary' 유지 — Detail.jsx 주석 참조).
 *
 * 이 컴포넌트는 **서브탭 셸**이다. 화면 요소는 전부 자식 탭에 있고, 여기 남는 건
 *   ① 헤더 줄 ② 문제점/현황 배너 ③ 서브탭 내비 ④ **모든 상태와 조회**다.
 *
 * 왜 이렇게 나눴나: 예전엔 한 화면에 데이터 카드 14장이 항상 펼쳐진 채 세로로 쌓였고
 * (접기·필터·탭 상태가 하나도 없었다) 진입 즉시 16개 요청이 동시에 나갔다. 카드가 전부
 * 같은 무게라 무엇이 결론인지 화면이 말하지 않았다 → 서브탭 4개 + `SummaryPanel`(L1 카드)
 * + 도구 스트립(L2)의 3단 위계로 재구성.
 *
 * ⚠ **조회와 상태는 절대 서브탭으로 내리지 말 것.**
 *   - `cached-builds-meta` → 두 패널의 공유 베이스라인 단일 출처(부모가 정확히 1회만 조회)
 *   - `build-timeline` rollup → 헤더 리비전 범위 + `MC/DC 회귀`·`검토 대기 문서` 배너의 유일한 출처
 *   - `trace-summary` → 추적성 패널을 숨긴 지금도 배너·AI 인사이트가 소비
 *   - `prqa-trend` → 소스코드 탭 차트 **와** 빌드 변경 탭 Δ위반 열이 같이 쓴다
 *   서브탭은 lazy 마운트라, 조회를 내리면 그 탭을 안 연 사용자에게 배너가 조용히 빈다.
 *
 * 데이터는 캐시 기반 소비라 "한번 생성하면 다음에 그대로" 유지(추적성만 캐시 없을 때 1회 자동생성).
 * ISO 정직성: 커버리지 null→'—', VectorCAST는 SCM 스냅샷(빌드별 트렌드 금지), PRQA만 빌드별 트렌드,
 * ASIL 미상≠QM, MC/DC 미측정≠미달.
 */

const SUBS = [
  { id: 'overview', label: '개요' },
  { id: 'arch', label: '아키텍처' },
  { id: 'source', label: '소스코드' },
  { id: 'build', label: '빌드 변경' },
];
const VALID_SUB = new Set(SUBS.map((s) => s.id));

function Pill({ text, color, title }) {
  return (
    <span title={title || text} style={{
      display: 'inline-block', padding: '1px 7px', borderRadius: 'var(--radius-sm)',
      fontSize: 'var(--text-xs)', fontWeight: 600, color: '#fff', background: color,
    }}>{text}</span>
  );
}
function HealthChip({ label, sev }) {
  const bg = sev === 'danger' ? 'var(--color-danger)'
    : sev === 'warn' ? 'var(--color-warning)'
    : sev === 'ok' ? 'var(--color-success)' : 'var(--text-muted)';
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4, padding: '3px 10px',
      borderRadius: 'var(--radius-sm)', fontSize: 'var(--text-xs)', fontWeight: 600, color: '#fff', background: bg,
    }}>{label}</span>
  );
}

export default function ProjectSummarySection({ job, analysisResult }) {
  const toast = useToast();
  const { cfg } = useJenkinsCfg();
  const rd = analysisResult?.reportData || {};
  const kpis = rd.kpis || {};
  const cm = kpis.code_metrics || {};
  const prqa = kpis.prqa || {};

  const jobUrl = job?.url || analysisResult?.jobUrl || '';
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(jobUrl);
  // deep-review W1: analysisResult가 다른 Job의 것으로 증명되면(잡 전환 직후 stale 등)
  // 그 문서 바인딩으로 추적성 매트릭스를 생성·영속하는 오귀속을 차단한다(scmId와 동일 게이트).
  const docsConsistent = targetConsistent(analysisResult, job?.url);
  const linkedDocs = useMemo(
    () => (docsConsistent ? analysisResult?.matchedScm?.linked_docs || {} : {}),
    [analysisResult, docsConsistent],
  );
  const sourceRoot = docsConsistent ? (analysisResult?.matchedScm?.source_root || '') : '';
  const scmId = useMemo(() => {
    if (!targetConsistent(analysisResult, job?.url)) return '';
    return analysisResult?.matchedScm?.id
      || pickScmForJob(analysisResult?.scmList, job?.url)?.id
      || analysisResult?.impactData?.trigger?.scm_id
      || '';
  }, [analysisResult, job]);

  // ── 서브탭 (DocGenHubSection과 동일 규약: 방문한 서브만 마운트, 이후 display:none 유지) ──
  const [sub, setSub] = useState('overview');
  const [mounted, setMounted] = useState(() => new Set(['overview']));
  const selectSub = useCallback((id) => {
    if (!VALID_SUB.has(id)) return;
    setMounted((prev) => (prev.has(id) ? prev : new Set(prev).add(id)));
    setSub(id);
  }, []);
  // WAI-ARIA tablist 키보드 네비게이션 (ArrowLeft/Right/Home/End + roving tabIndex).
  const onSubKeyDown = (e) => {
    const idx = SUBS.findIndex((s) => s.id === sub);
    let nextIdx = null;
    if (e.key === 'ArrowRight') nextIdx = (idx + 1) % SUBS.length;
    else if (e.key === 'ArrowLeft') nextIdx = (idx - 1 + SUBS.length) % SUBS.length;
    else if (e.key === 'Home') nextIdx = 0;
    else if (e.key === 'End') nextIdx = SUBS.length - 1;
    if (nextIdx == null) return;
    e.preventDefault();
    const id = SUBS[nextIdx].id;
    document.getElementById(`summary-tab-${id}`)?.focus();
    selectSub(id);
  };

  // ── 소스 스냅샷 빌드 목록 + 공유 베이스라인 ──
  // BaselineDiffPanel과 BuildChangeMatrixPanel이 **같은 기준**을 써야 한다 — 각자 조회·선택하면
  // 두 패널의 기준이 갈라져 사용자가 "어느 쪽이 진짜인가"를 물어야 한다. 단일 출처로 둔다.
  const [srcBuilds, setSrcBuilds] = useState(null);
  const [srcBuildsError, setSrcBuildsError] = useState('');
  const [baselineBuild, setBaselineBuild] = useState('');
  const [diffTarget, setDiffTarget] = useState('');   // BaselineDiffPanel 전용(매트릭스는 미사용)
  // 조회와 반영을 분리 — 백필 완료 후 재조회에도 같은 반영 규칙을 쓰기 위해서다.
  // ⚠ 실패를 삼키면 `srcBuilds === null` 이 **로딩·실패·잡 없음 3상태를 하나로 뭉갠다** —
  //   BaselineDiffPanel 의 "2개 이상 필요" 안내는 `builds &&` 가드라 null 에선 안 뜨고,
  //   개요 KPI 도 `—` 만 낸다. 실패는 실패로 표시한다(prqa-trend·build-timeline 과 같은 규약).
  const fetchSrcBuilds = useCallback(async () => {
    if (!jobUrl) return null;
    try {
      const resp = await post('/api/jenkins/cached-builds-meta', { job_url: jobUrl, cache_root: cacheRoot });
      setSrcBuildsError('');
      return (resp?.builds || []).filter((b) => b.has_source);
    } catch (e) {
      setSrcBuildsError(String(e?.message || e));
      return null;
    }
  }, [jobUrl, cacheRoot]);
  const applySrcBuilds = useCallback((rows) => {
    if (!rows) return;
    setSrcBuilds(rows);
    if (rows.length < 2) return;
    // 사용자가 이미 고른 기준은 유지한다 — 백필 뒤 재조회가 선택을 되돌리면 방금 만든
    // 비교 캐시와 화면 기준이 어긋나 캐시가 통째로 미스가 된다.
    const has = (n) => rows.some((b) => String(b.build_number) === String(n));
    setDiffTarget((prev) => (has(prev) ? prev : String(rows[0].build_number)));
    setBaselineBuild((prev) => (has(prev) ? prev : String(rows[rows.length - 1].build_number)));
  }, []);
  const reloadSrcBuilds = useCallback(async () => {
    applySrcBuilds(await fetchSrcBuilds());
  }, [fetchSrcBuilds, applySrcBuilds]);
  useEffect(() => {
    let alive = true;
    (async () => {
      const rows = await fetchSrcBuilds();
      if (alive) applySrcBuilds(rows);
    })();
    return () => { alive = false; };
  }, [fetchSrcBuilds, applySrcBuilds]);

  // ── 빌드 타임라인 ──
  // ⚠ 이 fetch는 **표가 아니라 rollup**(문제점 배너·헤더 리비전 범위)을 위해 존재한다.
  //   빌드별 변경 영향 표는 이제 change-matrix(소스 스냅샷 비교)를 쓴다 — 표에서 안 쓴다고
  //   이 fetch를 지우면 배너가 조용히 빈다(회귀 테스트가 이를 고정한다).
  const [timeline, setTimeline] = useState(null);
  const [timelineError, setTimelineError] = useState('');
  useEffect(() => {
    if (!scmId) return undefined;
    let cancelled = false;
    (async () => {
      try {
        // include_all 미전달 → 서버가 Jenkins를 조회하지 않아 항상 빠름. job_url+cache_root 전달로
        // 로컬 캐시 빌드(오프라인 메타 — Jenkins 불필요)를 서버가 병합해 '캐시의 모든 빌드'를 표면화.
        // 전체 Jenkins 빌드는 아래 allBuilds 효과가 비차단 병합(미도달 무영향).
        const qs = new URLSearchParams({ limit: '100', job_url: jobUrl || '', cache_root: cacheRoot || '' });
        const data = await api(`/api/scm/build-timeline/${encodeURIComponent(scmId)}?${qs}`);
        if (cancelled) return;
        if (data && data.ok !== false) { setTimeline(data); setTimelineError(''); }
        else { setTimeline({ rows: [], rollup: {} }); setTimelineError(String(data?.reason || '빌드 이력을 읽지 못했습니다')); }
      } catch (e) {
        // ⚠ 예전엔 여기서 완전 침묵이었다 — rollup이 비면 `MC/DC 회귀`·`검토 대기 문서` 배너
        //   두 개가 통째로 사라지는데 화면상 '문제 없음'과 구분이 안 됐다(증거부재≠정상).
        if (!cancelled) setTimelineError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
  }, [scmId, jobUrl, cacheRoot]);

  // ── 전체 빌드 목록(/api/jenkins/builds) — 비차단. build-timeline과 분리해 타임라인은 즉시 표시하고,
  //    Jenkins가 미도달(연결 타임아웃 ~30s)이면 조용히 분석된 빌드만 유지한다(전체빌드는 best-effort).
  const [allBuilds, setAllBuilds] = useState(null);
  useEffect(() => {
    if (!jobUrl || !cfg?.username || !cfg?.token) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const data = await post('/api/jenkins/builds', {
          job_url: jobUrl, username: cfg.username, api_token: cfg.token,
          scm_id: scmId, limit: 100, verify_tls: cfg.verifyTls,
        });
        const builds = Array.isArray(data) ? data : (Array.isArray(data?.builds) ? data.builds : []);
        if (!cancelled) setAllBuilds(builds);
      } catch { /* Jenkins 미도달 등 — 분석된 빌드만 표시(비차단) */ }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cfg, scmId]);

  // ── 동적(VectorCAST) SCM 스냅샷 ──
  // 소비처가 정적·동적 현황 패널과 파이프라인 헬스 둘뿐이라, 둘 다 숨긴 상태에서는 조회하지 않는다.
  // (이 엔드포인트는 impact_jobs의 수 MB 잡 파일을 읽는다 — 아무도 안 보는 데이터에 쓸 비용이 아니다.)
  const needScmVcast = SHOW.staticDynamic || SHOW.pipelineHealth;
  const [scmVcast, setScmVcast] = useState(null);
  useEffect(() => {
    if (!jobUrl || !needScmVcast) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const data = await post('/api/jenkins/scm-vcast-summary', { job_url: jobUrl });
        if (!cancelled) setScmVcast(data?.available ? data : null);
      } catch { /* best-effort */ }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, needScmVcast]);

  // ── 추적성 요약(캐시) + 없을 때 1회 자동생성 → 디스크 영속(재방문 재생성 없음) ──
  const [trace, setTrace] = useState(null);
  const [traceGen, setTraceGen] = useState(false);
  const [traceTick, setTraceTick] = useState(0);
  const reloadTrace = useCallback(() => { setTrace(null); setTraceTick((t) => t + 1); }, []);
  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        let data = await post('/api/jenkins/uds/trace-summary', { job_url: jobUrl, cache_root: cacheRoot });
        if (cancelled) return;
        if (data?.has_data) { setTrace(data); return; }
        if (!docsConsistent) {
          // W1: stale 문서 바인딩으로는 생성하지 않는다 — analysisResult가 따라잡으면
          // docsConsistent 변화로 이 effect가 재실행되어 정상 생성된다.
          setTrace({ has_data: false, reason: '분석 결과가 현재 Job과 일치하지 않아 자동 생성 보류 — 대시보드에서 이 프로젝트를 다시 불러오세요' });
          return;
        }
        setTraceGen(true);
        const gen = await buildTraceMatrix({ linkedDocs, sourceRoot, jobUrl, cacheRoot, buildSelector: 'lastSuccessfulBuild' });
        if (cancelled) return;
        if (gen.ok) {
          data = await post('/api/jenkins/uds/trace-summary', { job_url: jobUrl, cache_root: cacheRoot });
          if (!cancelled) setTrace(data?.has_data ? data : { has_data: false, reason: '생성했으나 요약 캐시 없음' });
        } else {
          setTrace({ has_data: false, reason: gen.reason === 'no_requirements' ? 'SRS 요구사항을 추출하지 못함 — 문서 경로 확인' : (gen.warnings?.[0] || '매트릭스 생성 실패') });
        }
      } catch (e) {
        if (!cancelled) setTrace({ has_data: false, reason: String(e?.message || e) });
      } finally {
        if (!cancelled) setTraceGen(false);
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot, traceTick, linkedDocs, sourceRoot, docsConsistent]);
  const traceBusy = (!!jobUrl && trace == null) || traceGen;

  // ── PRQA 빌드별 트렌드 ──
  // ⚠ 실패를 침묵으로 두면 `prqaTrend`가 null로 남아 화면에 "불러오는 중…"이 **영구히** 뜬다
  //   (로딩과 실패가 구분 불가). 실패는 실패로 표시하고 재시도를 준다.
  const [prqaTrend, setPrqaTrend] = useState(null);
  const [prqaTrendError, setPrqaTrendError] = useState('');
  const [prqaTick, setPrqaTick] = useState(0);
  const reloadPrqaTrend = useCallback(() => { setPrqaTrend(null); setPrqaTrendError(''); setPrqaTick((t) => t + 1); }, []);
  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const data = await post('/api/jenkins/prqa-trend', { job_url: jobUrl, cache_root: cacheRoot, limit: 30 });
        if (!cancelled) { setPrqaTrend(data || null); setPrqaTrendError(''); }
      } catch (e) {
        if (!cancelled) setPrqaTrendError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot, prqaTick]);

  // ── 빌드별 PRQA delta(트렌드 응답의 인접 delta) — 매트릭스 Δ위반 열이 소비 ──
  const deltaByBuild = useMemo(() => {
    const m = new Map();
    for (const b of prqaTrend?.builds || []) {
      if (b?.build_number != null) m.set(String(b.build_number), b);
    }
    return m;
  }, [prqaTrend]);
  const trendBuilds = prqaTrend?.builds;
  const latestViolationsDelta = trendBuilds?.length
    ? (trendBuilds[trendBuilds.length - 1]?.violations_delta ?? null)
    : null;

  // change-log rows는 더 이상 표를 만들지 않는다(빌드별 변경 영향은 소스 스냅샷 비교로 이동).
  // ⚠ rollup은 계속 소비된다 — 문제점 배너와 헤더 리비전 범위가 여기서 나온다.
  const rollup = useMemo(() => timeline?.rollup || {}, [timeline]);
  const revRange = rollup.revision_range || {};

  // 고정되지 않은 스냅샷 = 비교가 무의미한 빌드. 사용자가 재수집 필요성을 알 수 있게 노출.
  // ⚠ 아래 problems 가 이 값을 쓰므로 **problems 보다 먼저** 선언돼야 한다(TDZ).
  const unpinnedCount = useMemo(
    () => (srcBuilds || []).filter((b) => !b.source_pinned).length,
    [srcBuilds],
  );

  // ── 문제점 집계(SW 추적성 + timeline rollup + coverage 게이트 + 스냅샷 고정) ──
  const problems = useMemo(() => {
    const list = [];
    const t = trace?.has_data ? trace : null;
    if (t) {
      // classifyGate는 소문자('pass'|'warn'|'fail') 반환 — 대문자 비교는 영구 미발동이었다.
      // null 커버리지는 classify 자체를 건너뜀(null이 'fail'로 떨어지는 허위 미달 방지 — 증거부재≠미달).
      if (t.coverage_pct != null) {
        const gate = classifyGate(t.coverage_pct);
        if (gate === 'fail') list.push({ label: `커버리지 미달 ${Math.round(t.coverage_pct)}%`, sev: 'danger' });
        else if (gate === 'warn') list.push({ label: `커버리지 주의 ${Math.round(t.coverage_pct)}%`, sev: 'warn' });
      }
      if ((t.uncovered || 0) > 0) list.push({ label: `미추적 요구 ${t.uncovered}`, sev: 'warn' });
      if ((t.asil_gap_count || 0) > 0) list.push({ label: `ASIL 시험 미달 ${t.asil_gap_count}`, sev: 'danger' });
      if ((t.asil_unknown_count || 0) > 0) list.push({ label: `ASIL 미상 ${t.asil_unknown_count}`, sev: 'warn' });
      const integ = (t.integrity_collision_count || 0) + (t.integrity_dangling_count || 0);
      if (integ > 0) list.push({ label: `ID 정합성 ${integ}`, sev: 'warn' });
      const unmapped = t.summary_raw?.unmapped_vcast_count ?? t.unmapped_vcast_count;
      if ((unmapped || 0) > 0) list.push({ label: `VectorCAST 미매칭 ${unmapped}`, sev: 'warn' });
    }
    if ((rollup.cumulative_coverage_regressed || 0) > 0) list.push({ label: `MC/DC 회귀 ${rollup.cumulative_coverage_regressed}`, sev: 'danger' });
    if ((rollup.cumulative_flag_docs || 0) > 0) list.push({ label: `검토 대기 문서 ${rollup.cumulative_flag_docs}`, sev: 'warn' });
    // 미고정 스냅샷은 '빌드 변경' 탭 안에만 경고가 있는데, 그 탭은 lazy 라 열기 전엔 안 보인다.
    // 이건 "변화 0"을 코드 미변경으로 오독하게 만드는 축(ASIL 함수 변경 과소보고)이라
    // 탭을 안 열어도 보이는 배너에 올린다.
    if (unpinnedCount > 0) list.push({ label: `스냅샷 미고정 빌드 ${unpinnedCount}`, sev: 'warn' });
    return list;
  }, [trace, rollup, unpinnedCount]);

  // ── 과거 빌드 백필(sync-backfill) — Jenkins 연결 시에만 의미. 미도달은 서버가 정직 실패. ──
  const [backfill, setBackfill] = useState(null); // {job_id,total,completed,state,phase,matrix}
  // 스냅샷 고정: 끄면 HEAD 체크아웃이라 과거 빌드가 전부 '받아온 날의 트리'가 된다(실측 33빌드
  // 중 26개 동일 트리 → 변화 0 + ASIL 함수 변경 침묵). 그래서 기본 ON.
  const [pinSource, setPinSource] = useState(true);
  const [warmMatrix, setWarmMatrix] = useState(true);
  const [backfillCount, setBackfillCount] = useState(10);
  const backfillBusy = backfill?.state === 'running';
  const reloadTimeline = useCallback(() => {
    setTimeline(null);
    // scmId/jobUrl deps의 timeline effect는 상태 기반이라 즉시 재조회를 위해 직접 호출.
    (async () => {
      try {
        const qs = new URLSearchParams({ limit: '100', job_url: jobUrl || '', cache_root: cacheRoot || '' });
        const data = await api(`/api/scm/build-timeline/${encodeURIComponent(scmId)}?${qs}`);
        setTimeline(data && data.ok !== false ? data : { rows: [], rollup: {} });
      } catch { setTimeline({ rows: [], rollup: {} }); }
    })();
  }, [scmId, jobUrl, cacheRoot]);
  const startBackfill = useCallback(async () => {
    try {
      const resp = await post('/api/jenkins/sync-backfill', {
        job_url: jobUrl, username: cfg?.username || '', api_token: cfg?.token || '',
        cache_root: cacheRoot, verify_tls: cfg?.verifyTls, count: backfillCount, scm_id: scmId,
        pin_source: pinSource, warm_matrix: warmMatrix,
        // 비교 캐시는 **아래 패널에서 고른 기준**으로 만든다 — 다른 기준으로 만들면 표를 열 때
        // 캐시가 통째로 미스가 되어 토글이 아무 일도 안 한 것처럼 보인다.
        baseline_build: baselineBuild ? Number(baselineBuild) : null,
      });
      if (!resp?.available) {
        const why = resp?.reason === 'jenkins_unreachable' ? 'Jenkins에 연결할 수 없습니다(캐시 기반 표시는 유지)'
          : resp?.reason === 'nothing_to_backfill' ? (pinSource
            ? '가져올 빌드가 없습니다(최근 빌드가 모두 캐시 + 스냅샷 고정 완료)'
            : '가져올 새 빌드가 없습니다(최근 빌드 전부 캐시됨)')
          : resp?.reason === 'backfill_already_running' ? '이미 백필이 실행 중입니다'
          : `백필 시작 실패 (${resp?.reason || 'unknown'})`;
        toast?.('info', why);
        return;
      }
      setBackfill({ job_id: resp.job_id, total: resp.total, completed: 0, state: 'running', phase: 'sync' });
      // 상한(서버 MAX_BACKFILL_COUNT)이 캐시 빌드 수보다 작으면 한 번에 다 못 고친다.
      // 알리지 않으면 "고정했는데 왜 아직 경고가 뜨나"가 된다.
      if (resp.remaining_unpinned > 0) {
        toast?.('info', `이번에 ${resp.total}개를 처리합니다 — 미고정 ${resp.remaining_unpinned}개가 남아 한 번 더 실행해야 합니다`);
      }
      const poll = async () => {
        try {
          const st = await api(`/api/jenkins/sync-backfill-status/${resp.job_id}`);
          if (st?.available) {
            setBackfill(st);
            if (st.state === 'running') { setTimeout(poll, 3000); return; }
            const errs = (st.per_build || []).filter((b) => b.status === 'error').length;
            const pinFails = (st.per_build || []).filter((b) => b.status === 'pin_failed').length;
            const warmed = st.matrix?.completed ?? 0;
            const parts = [`${st.completed}개 빌드 캐시`];
            if (warmed) parts.push(`비교 캐시 ${warmed}건`);
            if (pinFails) parts.push(`revision 고정 실패 ${pinFails}건(HEAD로 진행)`);
            toast?.(errs || pinFails ? 'warn' : 'success',
              errs ? `백필 완료 — ${errs}개 빌드 실패(상태 참조)` : `백필 완료 — ${parts.join(' · ')}`);
            // 백필은 소스 스냅샷을 바꾼다 — 아키텍처 메트릭 공유 캐시를 비우지 않으면
            // 그 탭만 옛 빌드를 계속 보여줘 한 화면 안에서 기준 빌드가 갈라진다.
            clearArchMetricsCache(jobUrl, cacheRoot);
            reloadTimeline();
            reloadSrcBuilds();
          }
        } catch { setTimeout(poll, 5000); }
      };
      setTimeout(poll, 2500);
    } catch (e) {
      toast?.('error', `백필 요청 실패: ${String(e?.message || e)}`);
    }
  }, [jobUrl, cfg, cacheRoot, scmId, toast, reloadTimeline, reloadSrcBuilds,
      pinSource, warmMatrix, backfillCount, baselineBuild]);

  // 행 클릭 → 변경 영향 평가 탭 핸드오프는 제거됐다(사용자 결정): 표가 영향분석 실행 이력이
  // 아니라 소스 스냅샷 비교가 되면서, 잡이 실행된 빌드에만 동작하는 링크는 잡음이었다.
  // 그 자리는 행 펼침(변경 파일·함수 + PRQA delta)이 대신한다.

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
      {/* 헤더 + 문제 요약 — 서브탭 **위**에 둔다. "지금 괜찮은가"는 어느 탭에 있든 보여야 한다 */}
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--sp-2)' }}>
        <div style={{ fontSize: 'var(--text-xl)', fontWeight: 700 }}>📈 {job?.name || '프로젝트'} 분석</div>
        {scmId && <Pill text={`SCM ${scmId}`} color="var(--accent)" />}
        {problems.length > 0
          ? <Pill text={`⚠ 문제 ${problems.length}건`} color="var(--color-danger)" />
          : (trace?.has_data && <Pill text="이상 없음" color="var(--color-success)" />)}
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginLeft: 'auto' }}>
          {/* '분석 N회' — rollup은 실행(run) 단위 집계라 재분석 시 표시 행수(빌드 dedup)와 다를 수 있다(deep-review W-A). */}
          r{revRange.base_ref || '—'} → r{revRange.max_build_revision ?? '—'} · 분석 {fmtInt(rollup.analyzed_build_count)}회
        </span>
      </div>

      {/* 문제점 배너 */}
      <div className="panel" style={PANEL}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 'var(--sp-2)' }}>
          문제점 / 현황 {problems.length > 0 ? `— ⚠ ${problems.length}건` : ''}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--sp-2)' }}>
          {problems.length === 0
            ? <HealthChip label={trace?.has_data ? '이상 없음' : '추적성 로딩/생성 중…'} sev={trace?.has_data ? 'ok' : 'muted'} />
            : problems.map((p, i) => <HealthChip key={i} label={p.label} sev={p.sev} />)}
        </div>
        {/* 추적성 상태 줄 — 추적성 패널을 숨긴 뒤 생성 실패 사유가 갈 곳이 없어졌다. 실패를 조용히
            삼키면 '문제 0건'이 '이상 없음'으로 위장되므로(증거부재≠정상) 여기로 끌어올린다. */}
        {trace && !trace.has_data && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', flexWrap: 'wrap', marginTop: 'var(--sp-2)' }}>
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-warning)' }}>
              ⚠ 추적성 미생성 — {trace.reason || '추적성 매트릭스가 아직 생성되지 않았습니다.'}
            </span>
            <button type="button" onClick={reloadTrace} disabled={traceBusy}
              style={{ fontSize: 'var(--text-xs)', padding: '1px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: traceBusy ? 'wait' : 'pointer', color: 'var(--text-muted)' }}>
              다시 시도
            </button>
            {traceBusy && <span className="spinner" />}
          </div>
        )}
        {/* 빌드 이력 조회 실패 — MC/DC 회귀·검토 대기 문서는 rollup에서만 오므로 조용히 사라진다.
            이 줄이 없으면 "그 문제들이 없는 것"과 "못 읽은 것"이 화면에서 같아진다. */}
        {timelineError && (
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-warning)', marginTop: 'var(--sp-2)' }}>
            ⚠ 빌드 이력 조회 실패 — MC/DC 회귀·검토 대기 문서 지표가 이 목록에 반영되지 않았습니다 ({timelineError})
          </div>
        )}
      </div>

      {/* 파이프라인 헬스 스트립 — 설계(SDS)→테스트(STS)까지 단계 상태 + 탭 딥링크 */}
      {SHOW.pipelineHealth && (
        <PipelineHealthStrip trace={trace} prqa={prqa} scmVcast={scmVcast} rollup={rollup}
          latestViolationsDelta={latestViolationsDelta} />
      )}

      {/* ── 서브탭 ── */}
      <nav className="subnav" role="tablist" aria-label="프로젝트 분석 영역" onKeyDown={onSubKeyDown}>
        {SUBS.map((s) => (
          <button key={s.id} id={`summary-tab-${s.id}`} type="button" role="tab"
            aria-selected={sub === s.id} aria-controls={`summary-panel-${s.id}`}
            tabIndex={sub === s.id ? 0 : -1}
            className={`tab-item${sub === s.id ? ' active' : ''}`}
            onClick={() => selectSub(s.id)}>
            {s.label}
          </button>
        ))}
      </nav>

      {/* 패널 컨테이너는 항상 렌더 → 탭 버튼 aria-controls IDREF 유효(dangling 방지).
          무거운 자식은 방문한 서브만 마운트(keep-alive: 이후 숨김 유지 → 조회 결과·펼친 행 보존). */}
      <div role="tabpanel" id="summary-panel-overview" aria-labelledby="summary-tab-overview"
        tabIndex={sub === 'overview' ? 0 : -1} style={{ display: sub === 'overview' ? 'block' : 'none' }}>
        {mounted.has('overview') && (
          <SummaryOverviewTab jobUrl={jobUrl} cacheRoot={cacheRoot} scmId={scmId}
            trace={trace} traceBusy={traceBusy} reloadTrace={reloadTrace} scmVcast={scmVcast}
            prqa={prqa} codeMetrics={cm} srcBuilds={srcBuilds} srcBuildsError={srcBuildsError}
            violationsDelta={latestViolationsDelta} />
        )}
      </div>

      <div role="tabpanel" id="summary-panel-arch" aria-labelledby="summary-tab-arch"
        tabIndex={sub === 'arch' ? 0 : -1} style={{ display: sub === 'arch' ? 'block' : 'none' }}>
        {mounted.has('arch') && <SummaryArchTab jobUrl={jobUrl} cacheRoot={cacheRoot} />}
      </div>

      <div role="tabpanel" id="summary-panel-source" aria-labelledby="summary-tab-source"
        tabIndex={sub === 'source' ? 0 : -1} style={{ display: sub === 'source' ? 'block' : 'none' }}>
        {mounted.has('source') && (
          <SummarySourceTab jobUrl={jobUrl} cacheRoot={cacheRoot} prqa={prqa}
            prqaTrend={prqaTrend} prqaTrendError={prqaTrendError} onRetryPrqaTrend={reloadPrqaTrend} />
        )}
      </div>

      <div role="tabpanel" id="summary-panel-build" aria-labelledby="summary-tab-build"
        tabIndex={sub === 'build' ? 0 : -1} style={{ display: sub === 'build' ? 'block' : 'none' }}>
        {mounted.has('build') && (
          <SummaryBuildTab jobUrl={jobUrl} cacheRoot={cacheRoot}
            srcBuilds={srcBuilds} srcBuildsError={srcBuildsError} allBuilds={allBuilds}
            baselineBuild={baselineBuild} diffTarget={diffTarget}
            onChangeBaseline={setBaselineBuild} onChangeTarget={setDiffTarget}
            deltaByBuild={deltaByBuild}
            backfill={backfill} backfillBusy={backfillBusy} startBackfill={startBackfill}
            unpinnedCount={unpinnedCount}
            pinSource={pinSource} setPinSource={setPinSource}
            warmMatrix={warmMatrix} setWarmMatrix={setWarmMatrix}
            backfillCount={backfillCount} setBackfillCount={setBackfillCount} />
        )}
      </div>
    </div>
  );
}
