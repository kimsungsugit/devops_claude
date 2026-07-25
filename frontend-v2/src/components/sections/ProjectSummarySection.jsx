import { Fragment, useState, useEffect, useMemo, useCallback } from 'react';
import { post, api, defaultCacheRoot } from '../../api.js';
import { useToast, useJenkinsCfg } from '../../App.jsx';
import { pickScmForJob } from '../../projectLoader.js';
import { targetConsistent } from '../../impactGuard.js';
import { HorizontalBar, RingGauge, TrendLine } from '../charts.jsx';
import { CoverageDonut, QualityGateBadge, classifyGate } from '../ResultPanel.jsx';
import { buildTraceMatrix } from '../../traceMatrix.js';
import PipelineHealthStrip from './PipelineHealthStrip.jsx';
import BuildDeltaDrilldown from './BuildDeltaDrilldown.jsx';
import SummaryAiInsightPanel from './SummaryAiInsightPanel.jsx';
import RuleTrendPanel from './RuleTrendPanel.jsx';
import ArchitectureMetricsPanel from './ArchitectureMetricsPanel.jsx';
import ArchitectureGraphPanel from './ArchitectureGraphPanel.jsx';
import BaselineDiffPanel from './BaselineDiffPanel.jsx';
import FunctionCoveragePanel from './FunctionCoveragePanel.jsx';
import TestDesignPanel from './TestDesignPanel.jsx';

/**
 * ProjectSummarySection — "📈 프로젝트 분석" 탭 (구 '프로젝트 요약'. 탭 id는 'summary' 유지 — Detail.jsx 주석 참조).
 *
 * 구성: 문제점 배너 · AI 인사이트를 최상단에 두고, 나머지를 3그룹으로 나눈다.
 *   ① 🏗 SW 아키텍처   — 아키텍처 메트릭 · 다이어그램
 *   ② 📄 소스코드       — PRQA 트렌드 · 정적분석 위반 상세 · 룰 트렌드 · 함수별 커버리지
 *   ③ 🔨 빌드별 변경 영향 — 베이스라인→최신 변화 · 빌드 타임라인(전체 빌드)
 *
 * 숨김(사용자 결정, 삭제 아님 — 복원은 아래 각 HIDDEN 주석 블록 해제): 파이프라인 헬스 스트립 ·
 * 정적·동적 분석 현황(차트) · 추적성 현황(SW 밴드) · 테스트 설계 어드바이저.
 * ⚠ 추적성 **패널**만 숨기고 trace fetch/자동생성 effect는 유지한다 — 문제점 배너와 AI 인사이트가
 *   trace를 소비하므로 같이 지우면 배너가 조용히 비어 '이상 없음'으로 위장된다.
 *
 * 데이터는 캐시 기반 소비라 "한번 생성하면 다음에 그대로" 유지(추적성만 캐시 없을 때 1회 자동생성).
 * ISO 정직성: 커버리지 null→'—', VectorCAST는 SCM 스냅샷(빌드별 트렌드 금지), PRQA만 빌드별 트렌드,
 * ASIL 미상≠QM, MC/DC 미측정≠미달.
 */

const BASIS_LABEL = {
  it_statement: 'IT 구문', it_functions: 'IT 함수',
  combined_statement: 'UT+IT 합산', build_line: '빌드 라인커버', ut_statement: 'UT 구문',
};
const ASIL_COLOR = {
  D: 'var(--color-danger)', C: 'var(--color-warning)', B: 'var(--color-info)',
  A: 'var(--text-muted)', QM: 'var(--text-muted)', unknown: 'var(--text-muted)',
};
// SW 레벨 밴드만(시스템 문서 SyRS/SyTS/SyITS + HSIS 제외 — 사용자 결정).
const TRACE_BANDS = ['SDS', 'UDS', 'STS', 'SUTS', 'SITS', 'VectorCAST'];

/**
 * 패널 표시 스위치(사용자 결정으로 숨긴 항목) — **코드는 살려 두고 플래그만 false**.
 * 되살리려면 해당 값을 true로. JSX 주석 처리 대신 플래그를 쓰는 이유: 주석 블록은 내부에
 * 닫는 시퀀스가 섞이면 깨지고, 참조가 끊긴 변수·import가 lint 오류로 번져 복원 비용이 커진다.
 * ⚠ traceability를 false로 둬도 trace fetch/자동생성 effect는 유지해야 한다 —
 *   문제점 배너와 AI 인사이트가 trace를 소비하므로, 같이 지우면 배너가 조용히 빈다.
 */
const SHOW = {
  pipelineHealth: false,
  staticDynamic: false,
  traceability: false,
  testDesign: false,
};

function fmtInt(n) {
  return (n == null || Number.isNaN(Number(n))) ? '—' : Number(n).toLocaleString();
}
function pctOrNull(r) { return r == null || Number.isNaN(Number(r)) ? null : Number(r) * 100; }

function Kpi({ label, value, sub, tone }) {
  return (
    <div className="panel" style={{ boxShadow: 'none', padding: 'var(--sp-2) var(--sp-3)' }}>
      <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ fontSize: 'var(--text-lg, 18px)', fontWeight: 700, color: tone || 'var(--text)' }}>{value}</div>
      {sub && <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}
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

// 차트/KPI가 잘리지 않도록 반응형 그리드(auto-fit + minmax). flex-wrap은 좁은 폭에서 클립됐음.
const CHART_GRID = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 'var(--sp-3)', alignItems: 'start' };
const PANEL = { padding: 'var(--sp-3)' };

/** 그룹 구분 헤딩 — 패널이 세로로 길게 쌓이는 탭에서 어디부터 무슨 주제인지 표시. */
function GroupHeading({ icon, title, desc }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'baseline', gap: 'var(--sp-2)', flexWrap: 'wrap',
      borderTop: '2px solid var(--border)', paddingTop: 'var(--sp-2)', marginTop: 'var(--sp-2)',
    }}>
      <h3 style={{ margin: 0, fontSize: 'var(--text-md, 14px)', fontWeight: 700 }}>{icon} {title}</h3>
      {desc && <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{desc}</span>}
    </div>
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

  // ── 빌드 타임라인(전체 빌드) ──
  const [timeline, setTimeline] = useState(null);
  const [tlError, setTlError] = useState('');
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
        if (data && data.ok !== false) { setTimeline(data); setTlError(''); }
        else { setTimeline({ rows: [], rollup: {} }); setTlError('타임라인 조회 실패'); }
      } catch (e) {
        if (!cancelled) setTlError(String(e?.message || e));
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
  const [scmVcast, setScmVcast] = useState(null);
  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const data = await post('/api/jenkins/scm-vcast-summary', { job_url: jobUrl });
        if (!cancelled) setScmVcast(data?.available ? data : null);
      } catch { /* best-effort */ }
    })();
    return () => { cancelled = true; };
  }, [jobUrl]);

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
  const [prqaTrend, setPrqaTrend] = useState(null);
  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const data = await post('/api/jenkins/prqa-trend', { job_url: jobUrl, cache_root: cacheRoot, limit: 30 });
        if (!cancelled) setPrqaTrend(data || null);
      } catch { /* best-effort */ }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot]);

  // ── 빌드별 PRQA delta(트렌드 응답의 인접 delta) + 드릴다운 확장 상태 ──
  const [expandedBuild, setExpandedBuild] = useState(null);
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

  // 분석된 빌드(timeline change-log) + 전체 Jenkins 빌드(allBuilds) 병합 — 미분석은 analyzed:false 행.
  const rows = useMemo(() => {
    // deep-review W2: 동일 build_number 재분석 시 최신 실행을 채택한다. rows는 최신순이라
    // '첫 등장 우선' = 최신 우선 — 이전 last-write-wins는 구 분석이 최신을 가렸다.
    const analyzed = [];
    {
      const seen = new Set();
      for (const r of timeline?.rows || []) {
        const key = r.build_number != null ? String(r.build_number) : null;
        if (key != null) {
          if (seen.has(key)) continue;
          seen.add(key);
        }
        analyzed.push(r);
      }
    }
    if (!Array.isArray(allBuilds) || allBuilds.length === 0) return analyzed;
    const byNum = new Map();
    for (const r of analyzed) if (r.build_number != null) byNum.set(String(r.build_number), r);
    const merged = [];
    const used = new Set();
    for (const b of allBuilds) {
      const num = b?.number;
      if (num == null) continue;
      const a = byNum.get(String(num));
      if (a) {
        used.add(String(num));
        // 서버 캐시 병합 행(analyzed:false, cached:true)을 analyzed로 승격하지 않는다 —
        // Jenkins 목록에 있다고 분석된 것이 아니다(분석 여부는 change-log 행만이 증거).
        merged.push({ ...a, build_result: b.result || a.build_result, build_revision: a.build_revision || b.revision, analyzed: a.analyzed !== false });
      } else {
        merged.push({
          run_id: `__build_${num}`, analyzed: false, build_number: num,
          build_revision: b.revision, build_result: b.result,
          timestamp: b.timestamp ? new Date(b.timestamp).toISOString() : '',
          impact_counts: {}, max_asil_bucket: 'unknown',
        });
      }
    }
    for (const r of analyzed) {  // Jenkins 목록에 없는 분석 행(build_number null 등)도 유지
      const key = r.build_number != null ? String(r.build_number) : null;
      if (key == null || !used.has(key)) merged.push(r);
    }
    merged.sort((x, y) => (Number(y.build_number) || 0) - (Number(x.build_number) || 0));
    return merged;
  }, [timeline, allBuilds]);
  const rollup = useMemo(() => timeline?.rollup || {}, [timeline]);
  const asilDist = rollup.asil_distribution || {};
  const revRange = rollup.revision_range || {};
  const tlBusy = !!scmId && timeline == null && !tlError;

  // ── 문제점 집계(SW 추적성 + timeline rollup + coverage 게이트) ──
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
    return list;
  }, [trace, rollup]);

  // ── 과거 빌드 백필(sync-backfill) — Jenkins 연결 시에만 의미. 미도달은 서버가 정직 실패. ──
  const [backfill, setBackfill] = useState(null); // {job_id,total,completed,state} | {error}
  const backfillBusy = backfill?.state === 'running';
  const reloadTimeline = useCallback(() => {
    setTimeline(null); setTlError('');
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
        cache_root: cacheRoot, verify_tls: cfg?.verifyTls, count: 10, scm_id: scmId,
      });
      if (!resp?.available) {
        const why = resp?.reason === 'jenkins_unreachable' ? 'Jenkins에 연결할 수 없습니다(캐시 기반 표시는 유지)'
          : resp?.reason === 'nothing_to_backfill' ? '가져올 새 빌드가 없습니다(최근 빌드 전부 캐시됨)'
          : resp?.reason === 'backfill_already_running' ? '이미 백필이 실행 중입니다'
          : `백필 시작 실패 (${resp?.reason || 'unknown'})`;
        toast?.('info', why);
        return;
      }
      setBackfill({ job_id: resp.job_id, total: resp.total, completed: 0, state: 'running' });
      const poll = async () => {
        try {
          const st = await api(`/api/jenkins/sync-backfill-status/${resp.job_id}`);
          if (st?.available) {
            setBackfill(st);
            if (st.state === 'running') { setTimeout(poll, 3000); return; }
            const errs = (st.per_build || []).filter((b) => b.status === 'error').length;
            toast?.(errs ? 'warn' : 'success', errs ? `백필 완료 — ${errs}개 빌드 실패(상태 참조)` : `백필 완료 — ${st.completed}개 빌드 캐시됨`);
            reloadTimeline();
          }
        } catch { setTimeout(poll, 5000); }
      };
      setTimeout(poll, 2500);
    } catch (e) {
      toast?.('error', `백필 요청 실패: ${String(e?.message || e)}`);
    }
  }, [jobUrl, cfg, cacheRoot, scmId, toast, reloadTimeline]);

  const openInImpact = useCallback((row) => {
    if (row.analyzed === false) return;  // 미분석 빌드는 열 상세가 없음
    try {
      localStorage.setItem('devops_v2_impact_focus_build', JSON.stringify({ build_number: row.build_number, scm_id: scmId, ts: Date.now() }));
      window.dispatchEvent(new CustomEvent('devops:impact-focus-build'));
    } catch { /* ignore */ }
    if (typeof window.__detailSection === 'function') window.__detailSection('impact');
    else toast?.('info', '변경 영향 평가 탭으로 이동할 수 없습니다');
  }, [scmId, toast]);

  const utCov = pctOrNull(scmVcast?.line_rate);
  const brCov = pctOrNull(scmVcast?.branch_rate);
  const compliance = prqa?.project_compliance_index;
  const th = { textAlign: 'left', padding: '6px 8px', fontSize: 'var(--text-xs)', color: 'var(--text-muted)', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
  const td = { padding: '6px 8px', fontSize: 'var(--text-xs)', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
      {/* 헤더 + 문제 요약 */}
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
      </div>

      {/* 파이프라인 헬스 스트립 — 설계(SDS)→테스트(STS)까지 단계 상태 + 탭 딥링크 */}
      {SHOW.pipelineHealth && (
        <PipelineHealthStrip trace={trace} prqa={prqa} scmVcast={scmVcast} rollup={rollup}
          latestViolationsDelta={latestViolationsDelta} />
      )}

      {/* AI 인사이트(Gemini) — on-demand(버튼) + 빌드별 디스크 캐시(probe 자동 표시) */}
      <SummaryAiInsightPanel jobUrl={jobUrl} cacheRoot={cacheRoot} scmId={scmId} trace={trace} />

      {/* 정적·동적 현황 (그리드) */}
      {SHOW.staticDynamic && (
      <div className="panel" style={PANEL}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 'var(--sp-2)' }}>
          정적·동적 분석 현황
          <span style={{ fontSize: 'var(--text-xs)', fontWeight: 400, color: 'var(--text-muted)', marginLeft: 'var(--sp-2)' }}>
            (동적 VectorCAST는 현재 SCM 스냅샷)
          </span>
        </div>
        <div style={CHART_GRID}>
          <RingGauge value={utCov} color={(utCov ?? 0) >= 80 ? 'var(--color-success)' : 'var(--color-warning)'} label="구문 커버리지(UT)" />
          <RingGauge value={brCov} color="var(--color-info)" label="분기 커버리지" />
          <RingGauge value={compliance == null ? null : Number(compliance)}
            color={(compliance ?? 0) >= 90 ? 'var(--color-success)' : (compliance ?? 0) >= 70 ? 'var(--color-warning)' : 'var(--color-danger)'} label="PRQA 준수율" />
          <Kpi label="UT 테스트" value={scmVcast ? `${fmtInt(scmVcast.ut_passed)}/${fmtInt(scmVcast.ut_total)}` : '—'} sub="통과/전체" />
          <Kpi label="IT 테스트" value={scmVcast ? `${fmtInt(scmVcast.it_passed)}/${fmtInt(scmVcast.it_total)}` : '—'} sub="통과/전체" />
          <Kpi label="PRQA 위반 / 진단" value={`${fmtInt(prqa.rule_violation_count)} / ${fmtInt(prqa.diagnostic_count)}`} />
          <Kpi label="코드규모(파일)" value={fmtInt(cm.code_files)} sub={cm.source ? `출처 ${cm.source === 'qac' ? 'Helix QAC' : cm.source}` : undefined} />
          <Kpi label="함수 / LOC" value={`${fmtInt(cm.functions)} / ${fmtInt(cm.nloc)}`} />
        </div>
        {scmVcast?.coverage_basis && scmVcast.coverage_basis !== 'ut_statement' && (
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 'var(--sp-1)' }}>
            * 구문 커버리지 UT 기준 미산출 → <b>{BASIS_LABEL[scmVcast.coverage_basis] || scmVcast.coverage_basis}</b> 대체
          </div>
        )}
      </div>
      )}

      {/* 추적성 현황 (SW 밴드만) — 패널만 숨기고 trace fetch는 유지(문제점 배너·AI 인사이트 근거) */}
      {SHOW.traceability && (
      <div className="panel" style={PANEL}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
          <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>추적성 현황 (SW)</div>
          {traceBusy && <span className="spinner" />}
          <button onClick={reloadTrace} disabled={traceBusy}
            style={{ marginLeft: 'auto', fontSize: 'var(--text-xs)', padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: traceBusy ? 'wait' : 'pointer', color: 'var(--text-muted)' }}>
            새로고침
          </button>
        </div>
        {!trace ? (
          traceBusy ? <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>추적성 생성/로딩 중…</div> : null
        ) : !trace.has_data ? (
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>
            {trace.reason || '추적성 매트릭스가 아직 생성되지 않았습니다.'}
          </div>
        ) : (
          <>
            <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: 'var(--sp-4)', alignItems: 'start' }}>
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6 }}>
                <CoverageDonut covered={trace.covered} partial={trace.partial} uncovered={trace.uncovered} pct={trace.coverage_pct} />
                <QualityGateBadge pct={trace.coverage_pct} />
                <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>요구 {fmtInt(trace.total_requirements)}개</div>
              </div>
              <div style={{ minWidth: 200 }}>
                <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 4 }}>SW 밴드별 연결 요구 수</div>
                {(() => {
                  const bc = trace.band_counts || {};
                  const total = Math.max(trace.total_requirements || 0, ...TRACE_BANDS.map(b => bc[b] || 0), 1);
                  return TRACE_BANDS.filter(b => (bc[b] || 0) > 0).map(b => (
                    <HorizontalBar key={b} label={b} value={bc[b] || 0} max={total} color="var(--accent)" />
                  ));
                })()}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 6 }}>
                <Kpi label="미추적 요구" value={fmtInt(trace.uncovered)} tone={(trace.uncovered || 0) > 0 ? 'var(--color-warning)' : undefined} />
                <Kpi label="ASIL 시험 미달" value={fmtInt(trace.asil_gap_count)} tone={(trace.asil_gap_count || 0) > 0 ? 'var(--color-danger)' : undefined} />
                <Kpi label="ASIL 미상" value={fmtInt(trace.asil_unknown_count)} tone={(trace.asil_unknown_count || 0) > 0 ? 'var(--color-warning)' : undefined} />
                <Kpi label="ID 정합성" value={fmtInt((trace.integrity_collision_count || 0) + (trace.integrity_dangling_count || 0))} />
                <Kpi label="VectorCAST 미매칭" value={fmtInt(trace.summary_raw?.unmapped_vcast_count ?? trace.unmapped_vcast_count)} />
              </div>
            </div>
            {trace.generated_at && (
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 'var(--sp-2)' }}>생성 시각: {String(trace.generated_at).replace('T', ' ').slice(0, 19)}</div>
            )}
          </>
        )}
      </div>
      )}

      {/* ━━ 그룹 ① SW 아키텍처 ━━ */}
      <GroupHeading icon="🏗" title="SW 아키텍처" desc="소스 스냅샷 기준 구조 — 결정론 메트릭·모듈 관계" />

      {/* 아키텍처 메트릭 — 핫스팟/결합도/대형 함수 + v4 4축(간섭·전역·사분면·간접호출) */}
      <ArchitectureMetricsPanel jobUrl={jobUrl} cacheRoot={cacheRoot} />

      {/* 아키텍처 다이어그램 — 모듈 관계·순환·핫스팟 산포 (K2) */}
      <ArchitectureGraphPanel jobUrl={jobUrl} cacheRoot={cacheRoot} />

      {/* ━━ 그룹 ② 소스코드 ━━ */}
      <GroupHeading icon="📄" title="소스코드" desc="정적분석 위반·룰 변화·함수별 커버리지" />

      {/* PRQA 빌드별 트렌드 */}
      <div className="panel" style={PANEL}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 'var(--sp-2)' }}>
          PRQA 정적분석 빌드별 트렌드
          <span style={{ fontSize: 'var(--text-xs)', fontWeight: 400, color: 'var(--text-muted)', marginLeft: 'var(--sp-2)' }}>
            (VectorCAST 동적은 SCM 스냅샷이라 빌드별 변동 없음)
          </span>
        </div>
        {prqaTrend?.available && (prqaTrend.builds || []).length > 0 ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 'var(--sp-4)' }}>
            {[
              { key: 'violations', label: '위반', color: 'var(--color-warning)' },
              { key: 'diagnostics', label: '진단', color: 'var(--color-info)' },
              { key: 'compliance', label: '준수율(%)', color: 'var(--color-success)', threshold: 90 },
            ].map(({ key, label, color }) => {
              const builds = prqaTrend.builds || [];
              const points = builds.map((b) => ({ label: `#${b.build_number}`, value: b[key] ?? null }));
              const latest = builds.length ? builds[builds.length - 1][key] : null;
              const deltaKey = `${key}_delta`;
              const latestDelta = builds.length ? builds[builds.length - 1][deltaKey] : null;
              return (
                <div key={key}>
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                    <span>{label}</span>
                    <span>
                      <b style={{ fontSize: 'var(--text-md, 13px)', color: 'var(--text)' }}>{fmtInt(latest)}</b>
                      {latestDelta != null && (
                        <b style={{ marginLeft: 4, color: latestDelta > 0 ? 'var(--color-danger)' : latestDelta < 0 ? 'var(--color-success)' : 'var(--text-muted)' }}>
                          {latestDelta > 0 ? `+${latestDelta}` : latestDelta === 0 ? '±0' : latestDelta}
                        </b>
                      )}
                    </span>
                  </div>
                  {/* TrendLine 상위호환 — 결측 빌드는 선 분절(0 위장 금지), area로 추이 가독성 강화 */}
                  <TrendLine points={points} width={220} height={56} color={color} showArea showDots={points.length <= 20}
                    ariaLabel={`${label} 빌드별 추이`} />
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', textAlign: 'right' }}>{points[0]?.label} → {points[points.length - 1]?.label}</div>
                </div>
              );
            })}
          </div>
        ) : (
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
            {prqaTrend ? '빌드 캐시에 PRQA 지표가 없습니다.' : 'PRQA 트렌드 불러오는 중…'}
          </div>
        )}
      </div>

      {/* 정적분석 위반 상세 — kpis.prqa(상세탭과 동일 소스, 추가 fetch 없음) */}
      <div className="panel" style={PANEL}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
          <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>정적분석 위반 상세 (PRQA/MISRA)</div>
          <button type="button"
            onClick={() => { if (typeof window.__detailSection === 'function') window.__detailSection('analysis'); }}
            style={{ marginLeft: 'auto', fontSize: 'var(--text-xs)', padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}>
            테스트 결과 탭에서 전체 보기
          </button>
        </div>
        {(Array.isArray(prqa.top_rules) && prqa.top_rules.length > 0) || (Array.isArray(prqa.top_files) && prqa.top_files.length > 0) ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 'var(--sp-4)' }}>
            <div>
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 4 }}>위반 상위 규칙</div>
              {(() => {
                const rules = (prqa.top_rules || []).slice(0, 6);
                const max = Math.max(...rules.map((r) => r.count || 0), 1);
                return rules.map((r) => <HorizontalBar key={r.rule} label={r.rule} value={r.count || 0} max={max} color="var(--color-warning)" />);
              })()}
            </div>
            <div>
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 4 }}>위반 상위 파일</div>
              {(() => {
                const files = (prqa.top_files || []).slice(0, 6);
                const max = Math.max(...files.map((f) => f.count || 0), 1);
                return files.map((f) => <HorizontalBar key={f.path || f.file} label={f.file} value={f.count || 0} max={max} color="var(--color-danger)" />);
              })()}
            </div>
          </div>
        ) : (
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>빌드 캐시에 PRQA 위반 상세(RCR)가 없습니다.</div>
        )}
        {prqa.rule_violation_count != null && prqa.violations_attributed_total != null
          && Number(prqa.rule_violation_count) > Number(prqa.violations_attributed_total) && (
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 'var(--sp-1)' }}>
            * 총 위반 {fmtInt(prqa.rule_violation_count)} 중 {fmtInt(prqa.violations_attributed_total)}건만 파일에 귀속 — 나머지는 원본 QAC 리포트가 파일 미귀속으로 집계
          </div>
        )}
      </div>

      {/* 룰 트렌드 — 빌드별 위반 변화 분류 + 실제 fix 근거 작성 예시 */}
      <RuleTrendPanel jobUrl={jobUrl} cacheRoot={cacheRoot} />

      {/* 함수별 커버리지 + 실패 테스트 — 빌드 산출물 → SCM 입력 문서 폴백(N1) */}
      <FunctionCoveragePanel jobUrl={jobUrl} cacheRoot={cacheRoot} />

      {/* 테스트 설계 어드바이저 — 기법 권고·설계-시험 갭 (L2) */}
      {SHOW.testDesign && <TestDesignPanel jobUrl={jobUrl} cacheRoot={cacheRoot} />}

      {/* ━━ 그룹 ③ 빌드별 변경 영향 ━━ */}
      <GroupHeading icon="🔨" title="빌드별 변경 영향" desc="베이스라인 대비 코드 변화 · 빌드 타임라인" />

      {/* 베이스라인 → 최신 변화 — 소스 스냅샷 직접 비교(영향분석 이력 비의존) */}
      <BaselineDiffPanel jobUrl={jobUrl} cacheRoot={cacheRoot} />

      {/* 빌드 타임라인 (전체 빌드) */}
      <div className="panel" style={PANEL}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
          <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>빌드별 변경 영향 (전체 빌드)</div>
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>최신순 · 분석된 빌드는 클릭</span>
          {tlBusy && <span className="spinner" />}
          {backfillBusy && (
            <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-info)' }}>
              백필 중 {backfill.completed}/{backfill.total}{backfill.current_build ? ` (#${backfill.current_build})` : ''}…
            </span>
          )}
          <button type="button" onClick={startBackfill} disabled={backfillBusy || !jobUrl}
            title="Jenkins에서 최근 10개 빌드 산출물을 캐시로 가져옵니다(이미 캐시된 빌드는 건너뜀). Jenkins 미연결 시 안내만 표시됩니다."
            style={{ marginLeft: 'auto', fontSize: 'var(--text-xs)', padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: backfillBusy ? 'wait' : 'pointer', color: 'var(--text-muted)' }}>
            과거 빌드 가져오기
          </button>
        </div>

        {rows.length > 0 && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 'var(--sp-2)', marginBottom: 'var(--sp-3)' }}>
            <Kpi label="누적 변경 함수" value={fmtInt(rollup.distinct_changed_functions)} sub="distinct" />
            <Kpi label="누적 변경 파일" value={fmtInt(rollup.distinct_changed_files)} sub="distinct" />
            <Kpi label="재생성(AUTO)" value={fmtInt(rollup.cumulative_auto_docs)} sub="문서 누적" />
            <Kpi label="검토(FLAG)" value={fmtInt(rollup.cumulative_flag_docs)} tone={(rollup.cumulative_flag_docs || 0) > 0 ? 'var(--color-warning)' : undefined} />
            <Kpi label="MC/DC 회귀" value={fmtInt(rollup.cumulative_coverage_regressed)} tone={(rollup.cumulative_coverage_regressed || 0) > 0 ? 'var(--color-danger)' : undefined} />
            <Kpi label="ASIL 분포" value={
              <span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
                {['D', 'C', 'B', 'A', 'QM', 'unknown'].filter(k => (asilDist[k] || 0) > 0).map(k => (
                  <Pill key={k} text={`${k === 'unknown' ? '미상' : k} ${asilDist[k]}`} color={ASIL_COLOR[k]} />
                ))}
                {['D', 'C', 'B', 'A', 'QM', 'unknown'].every(k => (asilDist[k] || 0) === 0) && '—'}
              </span>
            } />
          </div>
        )}

        {tlError && <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)', marginBottom: 'var(--sp-2)' }}>타임라인 조회 오류: {tlError}</div>}
        {timeline?.enrich_note && <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--sp-2)' }}>ℹ {timeline.enrich_note}</div>}

        {!scmId ? (
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>SCM이 연결되지 않아 타임라인을 표시할 수 없습니다.</div>
        ) : rows.length > 0 ? (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 760 }}>
              <thead>
                <tr>
                  <th style={th}>빌드</th><th style={th}>리비전</th><th style={th}>결과</th><th style={th}>시각</th>
                  <th style={th}>변경 파일</th><th style={th}>변경 함수</th><th style={th}>영향(직접/1h/2h)</th>
                  <th style={th}>max ASIL</th><th style={th}>MC/DC</th><th style={th}>재생성/검토</th><th style={th}>상태</th>
                  <th style={th} title="직전 캐시 빌드 대비 PRQA 위반 증감">Δ위반</th><th style={th}>상세</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const analyzed = r.analyzed !== false;
                  const bucket = r.max_asil_bucket || 'unknown';
                  const rowTrend = r.build_number != null ? deltaByBuild.get(String(r.build_number)) : null;
                  const rowDelta = rowTrend?.violations_delta ?? null;
                  const expanded = r.build_number != null && expandedBuild != null && String(expandedBuild) === String(r.build_number);
                  return (
                    <Fragment key={r.run_id}>
                    <tr
                      onClick={() => openInImpact(r)}
                      onKeyDown={(e) => { if (e.target === e.currentTarget && analyzed && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openInImpact(r); } }}
                      role={analyzed ? 'button' : undefined} tabIndex={analyzed ? 0 : undefined}
                      aria-label={analyzed ? `빌드 #${r.build_number ?? '?'} 변경 영향 평가 열기` : undefined}
                      style={{ cursor: analyzed ? 'pointer' : 'default', opacity: analyzed ? 1 : 0.6 }}
                      title={analyzed ? '클릭 → 변경 영향 평가 탭에서 이 빌드 열기' : '미분석 빌드'}>
                      <td style={td}>{r.build_number != null ? `#${r.build_number}` : '—'}</td>
                      <td style={td}>
                        r{r.build_revision || '—'}
                        {r.build_revision_is_head && <span title="HEAD 미확인" style={{ color: 'var(--color-warning)' }}> ⚠</span>}
                      </td>
                      <td style={td}>{r.build_result ? <Pill text={r.build_result} color={r.build_result === 'SUCCESS' ? 'var(--color-success)' : (String(r.build_result).includes('FAIL') ? 'var(--color-danger)' : 'var(--text-muted)')} /> : '—'}</td>
                      <td style={td}>{String(r.timestamp || '').replace('T', ' ').slice(0, 16) || '—'}</td>
                      <td style={td}>{analyzed ? fmtInt(r.changed_files_count) : '—'}</td>
                      <td style={td}>{analyzed ? fmtInt(r.changed_functions_count) : '—'}</td>
                      <td style={td}>{analyzed ? `${r.impact_counts?.direct ?? 0}/${r.impact_counts?.indirect_1hop ?? 0}/${r.impact_counts?.indirect_2hop ?? 0}` : '—'}</td>
                      <td style={td}>{analyzed ? <Pill text={bucket === 'unknown' ? '미상' : bucket} color={ASIL_COLOR[bucket]} /> : '—'}</td>
                      <td style={td}>{analyzed && r.mcdc_required ? <Pill text="필수" color="var(--color-info)" /> : '—'}</td>
                      <td style={td}>
                        {analyzed
                          ? <><span style={{ color: 'var(--color-success)' }}>{r.auto_docs || 0}</span>{' / '}<span style={{ color: (r.flag_docs || 0) > 0 ? 'var(--color-warning)' : 'var(--text)' }}>{r.flag_docs || 0}</span></>
                          : '—'}
                      </td>
                      <td style={td}>
                        {!analyzed ? <Pill text={r.cached ? '캐시 · 미분석' : '미분석'} color="var(--text-muted)" title={r.cached ? '캐시에 산출물 존재 — 영향 분석은 미실행' : undefined} />
                          : r.partial_failure ? <Pill text="부분실패" color="var(--color-warning)" />
                          : (r.coverage_regressed || 0) > 0 ? <Pill text="커버리지 회귀" color="var(--color-danger)" />
                          : (r.coverage_unmeasured_safety || 0) > 0 ? <Pill text="MC/DC 미측정" color="var(--color-warning)" />
                          : !r.coverage_measured ? <Pill text="커버리지 미측정" color="var(--text-muted)" />
                          : <span style={{ color: 'var(--color-success)', fontWeight: 600 }}>정상</span>}
                      </td>
                      <td style={td}>
                        {rowDelta == null
                          ? <span style={{ color: 'var(--text-muted)' }}>—</span>
                          : <span style={{ fontWeight: 600, color: rowDelta > 0 ? 'var(--color-danger)' : rowDelta < 0 ? 'var(--color-success)' : 'var(--text-muted)' }}>
                              {rowDelta > 0 ? `+${rowDelta}` : rowDelta === 0 ? '±0' : rowDelta}
                            </span>}
                      </td>
                      <td style={td}>
                        {r.build_number != null && (
                          <button type="button"
                            onClick={(e) => { e.stopPropagation(); setExpandedBuild(expanded ? null : r.build_number); }}
                            aria-expanded={expanded}
                            aria-label={`빌드 #${r.build_number} PRQA 위반 delta 상세 ${expanded ? '접기' : '펼치기'}`}
                            title="직전 빌드 대비 위반 규칙/파일 delta 드릴다운"
                            style={{ fontSize: 'var(--text-xs)', padding: '1px 7px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}>
                            {expanded ? '▾' : '▸'}
                          </button>
                        )}
                      </td>
                    </tr>
                    {expanded && (
                      <tr>
                        <td colSpan={13} style={{ padding: 0, borderBottom: '1px solid var(--border)' }}>
                          <BuildDeltaDrilldown jobUrl={jobUrl} cacheRoot={cacheRoot} scmId={scmId}
                            buildNumber={Number(r.build_number)}
                            onOpenImpact={analyzed ? () => openInImpact(r) : undefined} />
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (!tlBusy && !tlError) ? (
          <div style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>표시할 빌드가 없습니다.</div>
        ) : null}
      </div>
    </div>
  );
}
