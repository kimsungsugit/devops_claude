import { HorizontalBar, RingGauge } from '../charts.jsx';
import { CoverageDonut, QualityGateBadge, classifyGate } from '../ResultPanel.jsx';
import SummaryAiInsightPanel from './SummaryAiInsightPanel.jsx';
import { SHOW, PANEL, fmtInt, pctOrNull } from './summaryCommon.js';

/**
 * 개요 서브탭 — "이 프로젝트 지금 어떤 상태인가"를 한 화면에서 답한다.
 *
 * ⚠ **KPI 6칸은 새 요청이 하나도 없다.** 전부 부모가 이미 받아 둔 값(trace·prqa·code_metrics·
 *   prqaTrend·srcBuilds)을 다시 쓰는 것뿐이다. 개요를 만들려고 조회를 늘리면 "요약 보려다 더
 *   느려지는" 역전이 난다. (탭 전체로는 아래 `SummaryAiInsightPanel` 의 캐시 probe 1건이 있다 —
 *   LLM 호출이 아니라 디스크 캐시 조회다.)
 *
 * 정직성: 미측정은 `0`이 아니라 `—`. 커버리지가 null이면 게이트 판정 자체를 하지 않는다
 * (증거부재 ≠ 미달).
 */

const BASIS_LABEL = {
  it_statement: 'IT 구문', it_functions: 'IT 함수',
  combined_statement: 'UT+IT 합산', build_line: '빌드 라인커버', ut_statement: 'UT 구문',
};
// SW 레벨 밴드만(시스템 문서 SyRS/SyTS/SyITS + HSIS 제외 — 사용자 결정).
const TRACE_BANDS = ['SDS', 'UDS', 'STS', 'SUTS', 'SITS', 'VectorCAST'];
// 차트/KPI가 잘리지 않도록 반응형 그리드(auto-fit + minmax). flex-wrap은 좁은 폭에서 클립됐음.
const CHART_GRID = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 'var(--sp-3)', alignItems: 'start' };
const KPI_GRID = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 'var(--sp-2)' };

/** KPI 한 칸. 값은 --text-2xl(18px)로 크게 — 개요 화면의 유일한 큰 숫자다. */
function Kpi({ label, value, sub, tone }) {
  return (
    <div className="panel" style={{ boxShadow: 'none', padding: 'var(--sp-2) var(--sp-3)' }}>
      <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ fontSize: 'var(--text-2xl)', fontWeight: 700, color: tone || 'var(--text)' }}>{value}</div>
      {sub && <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

/** 소형 KPI(숨긴 상세 블록 전용) — 값이 14px. */
function MiniKpi({ label, value, sub, tone }) {
  return (
    <div className="panel" style={{ boxShadow: 'none', padding: 'var(--sp-2) var(--sp-3)' }}>
      <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ fontSize: 'var(--text-lg)', fontWeight: 700, color: tone || 'var(--text)' }}>{value}</div>
      {sub && <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

function deltaText(d) {
  if (d == null) return undefined;
  return d > 0 ? `직전 빌드 대비 +${d}` : d === 0 ? '직전 빌드 대비 ±0' : `직전 빌드 대비 ${d}`;
}

export default function SummaryOverviewTab({
  jobUrl, cacheRoot, scmId, trace, traceBusy, reloadTrace, scmVcast,
  prqa = {}, codeMetrics = {}, srcBuilds, srcBuildsError, violationsDelta,
}) {
  const cov = trace?.has_data ? trace.coverage_pct : null;
  const covGate = cov == null ? null : classifyGate(cov);
  const compliance = prqa?.project_compliance_index;
  const utCov = pctOrNull(scmVcast?.line_rate);
  const brCov = pctOrNull(scmVcast?.branch_rate);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
      {/* KPI 스트립 — 새 조회 없이 이미 받아 둔 값만 재사용 */}
      <div style={KPI_GRID}>
        <Kpi label="추적 커버리지"
          value={cov == null ? '—' : `${Math.round(cov)}%`}
          sub={cov == null ? (traceBusy ? '생성/로딩 중…' : '미생성') : (covGate === 'fail' ? '미달' : covGate === 'warn' ? '주의' : '양호')}
          tone={covGate === 'fail' ? 'var(--color-danger)' : covGate === 'warn' ? 'var(--color-warning)' : undefined} />
        {/* tone 도 value 와 같은 has_data 가드를 쓴다 — 값이 '—' 인데 색만 경고면 오독을 부른다 */}
        <Kpi label="미추적 요구"
          value={trace?.has_data ? fmtInt(trace.uncovered) : '—'}
          sub={trace?.has_data ? `요구 ${fmtInt(trace.total_requirements)}개 중` : undefined}
          tone={trace?.has_data && (trace.uncovered || 0) > 0 ? 'var(--color-warning)' : undefined} />
        <Kpi label="PRQA 위반"
          value={fmtInt(prqa.rule_violation_count)}
          sub={deltaText(violationsDelta)}
          tone={violationsDelta > 0 ? 'var(--color-danger)' : undefined} />
        <Kpi label="PRQA 준수율"
          value={compliance == null ? '—' : `${Number(compliance).toFixed(1)}%`}
          tone={compliance == null ? undefined
            : Number(compliance) >= 90 ? 'var(--color-success)'
            : Number(compliance) >= 70 ? 'var(--color-warning)' : 'var(--color-danger)'} />
        <Kpi label="코드 규모"
          value={fmtInt(codeMetrics.functions)}
          sub={`함수 · 파일 ${fmtInt(codeMetrics.code_files)}${codeMetrics.source ? ` · 출처 ${codeMetrics.source === 'qac' ? 'Helix QAC' : codeMetrics.source}` : ''}`} />
        {/* 리비전 범위는 헤더 줄이 이미 낸다 — 같은 값을 두 곳에 두면 어느 쪽이 최신인지 물어야 한다.
            ⚠ `—` 하나로 로딩·실패·잡 없음을 뭉개지 않는다(증거부재 ≠ 0). */}
        <Kpi label="비교 가능 빌드"
          value={srcBuilds ? fmtInt(srcBuilds.length) : '—'}
          sub={srcBuildsError ? '조회 실패' : srcBuilds ? '소스 스냅샷 보유분' : '불러오는 중…'}
          tone={srcBuildsError ? 'var(--color-warning)' : undefined} />
      </div>

      {/* AI 인사이트(Gemini) — on-demand(버튼) + 빌드별 디스크 캐시(probe 자동 표시) */}
      <SummaryAiInsightPanel jobUrl={jobUrl} cacheRoot={cacheRoot} scmId={scmId} trace={trace} />

      {/* 정적·동적 현황 (그리드) — 숨김(SHOW.staticDynamic). 삭제가 아니라 플래그다 */}
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
          <MiniKpi label="UT 테스트" value={scmVcast ? `${fmtInt(scmVcast.ut_passed)}/${fmtInt(scmVcast.ut_total)}` : '—'} sub="통과/전체" />
          <MiniKpi label="IT 테스트" value={scmVcast ? `${fmtInt(scmVcast.it_passed)}/${fmtInt(scmVcast.it_total)}` : '—'} sub="통과/전체" />
          <MiniKpi label="PRQA 위반 / 진단" value={`${fmtInt(prqa.rule_violation_count)} / ${fmtInt(prqa.diagnostic_count)}`} />
          <MiniKpi label="코드규모(파일)" value={fmtInt(codeMetrics.code_files)} sub={codeMetrics.source ? `출처 ${codeMetrics.source === 'qac' ? 'Helix QAC' : codeMetrics.source}` : undefined} />
          <MiniKpi label="함수 / LOC" value={`${fmtInt(codeMetrics.functions)} / ${fmtInt(codeMetrics.nloc)}`} />
        </div>
        {scmVcast?.coverage_basis && scmVcast.coverage_basis !== 'ut_statement' && (
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 'var(--sp-1)' }}>
            * 구문 커버리지 UT 기준 미산출 → <b>{BASIS_LABEL[scmVcast.coverage_basis] || scmVcast.coverage_basis}</b> 대체
          </div>
        )}
      </div>
      )}

      {/* 추적성 현황 (SW 밴드만) — 숨김(SHOW.traceability). 패널만 숨기고 trace fetch는 부모가 유지 */}
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
                <MiniKpi label="미추적 요구" value={fmtInt(trace.uncovered)} tone={(trace.uncovered || 0) > 0 ? 'var(--color-warning)' : undefined} />
                <MiniKpi label="ASIL 시험 미달" value={fmtInt(trace.asil_gap_count)} tone={(trace.asil_gap_count || 0) > 0 ? 'var(--color-danger)' : undefined} />
                <MiniKpi label="ASIL 미상" value={fmtInt(trace.asil_unknown_count)} tone={(trace.asil_unknown_count || 0) > 0 ? 'var(--color-warning)' : undefined} />
                <MiniKpi label="ID 정합성" value={fmtInt((trace.integrity_collision_count || 0) + (trace.integrity_dangling_count || 0))} />
                <MiniKpi label="VectorCAST 미매칭" value={fmtInt(trace.summary_raw?.unmapped_vcast_count ?? trace.unmapped_vcast_count)} />
              </div>
            </div>
            {trace.generated_at && (
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 'var(--sp-2)' }}>생성 시각: {String(trace.generated_at).replace('T', ' ').slice(0, 19)}</div>
            )}
          </>
        )}
      </div>
      )}
    </div>
  );
}
