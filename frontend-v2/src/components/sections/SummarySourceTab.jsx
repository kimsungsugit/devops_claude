import { HorizontalBar, TrendLine } from '../charts.jsx';
import SummaryPanel from './SummaryPanel.jsx';
import RuleTrendPanel from './RuleTrendPanel.jsx';
import CodingRulebookPanel from './CodingRulebookPanel.jsx';
import FunctionCoveragePanel from './FunctionCoveragePanel.jsx';
import TestDesignPanel from './TestDesignPanel.jsx';
import { SHOW, fmtInt } from './summaryCommon.js';

/**
 * 소스코드 서브탭 — 정적분석 위반·룰 변화·함수별 커버리지.
 *
 * PRQA 트렌드와 위반 상세는 별도 컴포넌트가 아니라 여기 인라인이다(부모가 이미 받아 둔
 * `prqaTrend`·`kpis.prqa` 를 쓰므로 추가 조회가 없다).
 *
 * ⚠ 트렌드 조회 실패를 로딩으로 위장하지 않는다 — 예전엔 catch 가 침묵이라 실패하면
 *   "PRQA 트렌드 불러오는 중…" 이 영구히 남아, 사용자는 영원히 기다렸다.
 */

/** 위반 상위 규칙/파일 표시 상한 — 넘으면 총계를 각주로 낸다. */
const TOP_N = 6;

const TREND_SERIES = [
  { key: 'violations', label: '위반', color: 'var(--color-warning)' },
  { key: 'diagnostics', label: '진단', color: 'var(--color-info)' },
  { key: 'compliance', label: '준수율(%)', color: 'var(--color-success)' },
];

export default function SummarySourceTab({
  jobUrl, cacheRoot, prqa = {}, prqaTrend, prqaTrendError, onRetryPrqaTrend,
}) {
  const trendBuilds = prqaTrend?.builds || [];
  const hasTrend = !!prqaTrend?.available && trendBuilds.length > 0;
  const hasViolationDetail = (Array.isArray(prqa.top_rules) && prqa.top_rules.length > 0)
    || (Array.isArray(prqa.top_files) && prqa.top_files.length > 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
      {/* PRQA 빌드별 트렌드 */}
      <SummaryPanel
        title="PRQA 정적분석 빌드별 트렌드"
        meta={<span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
          (VectorCAST 동적은 SCM 스냅샷이라 빌드별 변동 없음)
        </span>}
        actions={prqaTrendError ? (
          <button type="button" onClick={onRetryPrqaTrend}
            style={{ fontSize: 'var(--text-xs)', padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}>
            다시 시도
          </button>
        ) : undefined}
      >
        {hasTrend ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 'var(--sp-4)' }}>
            {TREND_SERIES.map(({ key, label, color }) => {
              const points = trendBuilds.map((b) => ({ label: `#${b.build_number}`, value: b[key] ?? null }));
              const latest = trendBuilds[trendBuilds.length - 1][key];
              const latestDelta = trendBuilds[trendBuilds.length - 1][`${key}_delta`];
              return (
                <div key={key}>
                  <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                    <span>{label}</span>
                    <span>
                      <b style={{ fontSize: 'var(--text-md)', color: 'var(--text)' }}>{fmtInt(latest)}</b>
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
          <div style={{ fontSize: 'var(--text-xs)', color: prqaTrendError ? 'var(--color-warning)' : 'var(--text-muted)' }}>
            {prqaTrendError
              ? `⚠ PRQA 트렌드 조회 실패 — ${prqaTrendError}`
              : prqaTrend ? '빌드 캐시에 PRQA 지표가 없습니다.' : 'PRQA 트렌드 불러오는 중…'}
          </div>
        )}
      </SummaryPanel>

      {/* 정적분석 위반 상세 — kpis.prqa(상세탭과 동일 소스, 추가 fetch 없음) */}
      <SummaryPanel
        title="정적분석 위반 상세 (PRQA/MISRA)"
        actions={
          <button type="button"
            onClick={() => { if (typeof window.__detailSection === 'function') window.__detailSection('analysis'); }}
            style={{ fontSize: 'var(--text-xs)', padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}>
            테스트 결과 탭에서 전체 보기
          </button>
        }
      >
        {hasViolationDetail ? (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 'var(--sp-4)' }}>
            <div>
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 4 }}>위반 상위 규칙</div>
              {(() => {
                const all = prqa.top_rules || [];
                const rules = all.slice(0, TOP_N);
                const max = Math.max(...rules.map((r) => r.count || 0), 1);
                return <>
                  {rules.map((r) => <HorizontalBar key={r.rule} label={r.rule} value={r.count || 0} max={max} color="var(--color-warning)" />)}
                  {/* 절단을 침묵시키지 않는다 — 6개만 보이는데 총계를 안 주면 "이게 전부"로 읽힌다 */}
                  {all.length > TOP_N && (
                    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>* 상위 {TOP_N}개만 표시 (총 {all.length}개)</div>
                  )}
                </>;
              })()}
            </div>
            <div>
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 4 }}>위반 상위 파일</div>
              {(() => {
                const all = prqa.top_files || [];
                const files = all.slice(0, TOP_N);
                const max = Math.max(...files.map((f) => f.count || 0), 1);
                return <>
                  {files.map((f) => <HorizontalBar key={f.path || f.file} label={f.file} value={f.count || 0} max={max} color="var(--color-danger)" />)}
                  {all.length > TOP_N && (
                    <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>* 상위 {TOP_N}개만 표시 (총 {all.length}개)</div>
                  )}
                </>;
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
      </SummaryPanel>

      {/* 룰 트렌드 — 빌드별 위반 변화 분류 + 실제 fix 근거 작성 예시 */}
      <RuleTrendPanel jobUrl={jobUrl} cacheRoot={cacheRoot} defaultOpen={false} />

      {/* 코딩 룰북 초안 — 위반 규칙을 카테고리로 묶어 문서화 (Q4) */}
      <CodingRulebookPanel jobUrl={jobUrl} cacheRoot={cacheRoot} defaultOpen={false} />

      {/* 함수별 커버리지 + 실패 테스트 — 빌드 산출물 → SCM 입력 문서 폴백(N1) */}
      <FunctionCoveragePanel jobUrl={jobUrl} cacheRoot={cacheRoot} />

      {/* 테스트 설계 어드바이저 — 기법 권고·설계-시험 갭 (L2) */}
      {SHOW.testDesign && <TestDesignPanel jobUrl={jobUrl} cacheRoot={cacheRoot} />}
    </div>
  );
}
