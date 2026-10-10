import { useEffect, useMemo, useState } from 'react';
import { post } from '../../api.js';
import { HorizontalBar, TrendLine } from '../charts.jsx';
import SummaryPanel from './SummaryPanel.jsx';
import RuleTrendPanel from './RuleTrendPanel.jsx';
import RuleConflictPanel from './RuleConflictPanel.jsx';
import CodingRulebookPanel from './CodingRulebookPanel.jsx';
import FunctionCoveragePanel from './FunctionCoveragePanel.jsx';
import TestDesignPanel from './TestDesignPanel.jsx';
import { SHOW, fmtInt } from './summaryCommon.js';

/**
 * 소스코드 서브탭 — 정적분석 위반·룰 변화·룰 상충·함수별 커버리지.
 *
 * PRQA 트렌드와 위반 상세는 별도 컴포넌트가 아니라 여기 인라인이다(부모가 이미 받아 둔
 * `prqaTrend`·`kpis.prqa` 를 쓰므로 추가 조회가 없다).
 *
 * ⚠ 트렌드 조회 실패를 로딩으로 위장하지 않는다 — 예전엔 catch 가 침묵이라 실패하면
 *   "PRQA 트렌드 불러오는 중…" 이 영구히 남아, 사용자는 영원히 기다렸다.
 *
 * ⚠ **룰 상충은 여기서 한 번만 조회한다.** 룰 트렌드 표의 '이 룰을 고치면' 인라인과 상충
 *   패널이 같은 값을 써야 하고, 각자 부르면 서버에서 `compute_rule_trend` 가 두 번 돈다
 *   (이 탭은 이미 그 낭비를 백로그로 남긴 적이 있다). 조회는 이 탭에 두되 — 소스코드 탭
 *   전용 데이터라 다른 탭의 배너를 비우지 않는다 — 에러 상태도 **함께** 내려보낸다.
 *   안 내려보내면 패널이 '값 없음'과 '못 읽음'을 구분하지 못한다.
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

  const [conflicts, setConflicts] = useState(null);
  const [conflictsError, setConflictsError] = useState('');
  const [conflictsToken, setConflictsToken] = useState(0);
  // 룰 트렌드 행에서 '상충 패널에서 보기'를 누르면 그 상충을 펼친 채로 패널을 연다.
  // nonce 를 함께 올린다 — id 만 쓰면 사용자가 패널을 접은 뒤 **같은** 버튼을 다시 눌렀을 때
  // key 가 그대로라 아무 반응이 없는 죽은 버튼이 된다.
  const [focus, setFocus] = useState({ id: '', nonce: 0 });

  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const resp = await post('/api/summary/rule-conflicts', {
          job_url: jobUrl, cache_root: cacheRoot, limit: 15,
        });
        if (!cancelled) { setConflicts(resp); setConflictsError(''); }
      } catch (e) {
        if (!cancelled) setConflictsError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot, conflictsToken]);

  // 규칙 → 그 규칙을 고칠 때 걸릴 수 있는 것들. 룰 트렌드 표가 행마다 조회하는 인덱스라
  // 서버 by_rule(규칙→상충 id)만으로는 부족하다(위험 규칙 이름과 등급까지 필요).
  const conflictHints = useMemo(() => {
    const out = {};
    for (const c of conflicts?.conflicts || []) {
      for (const m of c.fixing || []) {
        if (!out[m.rule]) out[m.rule] = [];
        out[m.rule].push({
          id: c.id, tier: c.tier, kind: c.kind,
          risk: (c.risk || []).map((r) => r.rule),
          metricRisk: c.metric_risk || [],
        });
      }
    }
    return out;
  }, [conflicts]);

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
      <RuleTrendPanel jobUrl={jobUrl} cacheRoot={cacheRoot} defaultOpen={false}
        conflictHints={conflictHints}
        onFocusConflict={(id) => setFocus((f) => ({ id, nonce: f.nonce + 1 }))} />

      {/* 룰 상충·판단 지점 — 고치면 걸릴 룰 + 숫자만으로 판단하면 안 되는 곳
          ⚠ key 에 focus 를 넣어 '상충 패널에서 보기'가 패널을 펼친 채 재마운트하게 한다.
             SummaryPanel 의 열림은 defaultOpen 초기값이라 외부에서 나중에 열 수 없다.
             데이터는 이 부모가 쥐고 있으므로 재마운트로 재조회가 나지 않는다. */}
      <RuleConflictPanel key={`conflict-${focus.id}-${focus.nonce}`}
        jobUrl={jobUrl} cacheRoot={cacheRoot}
        data={conflicts} error={conflictsError}
        onRetry={() => { setConflictsError(''); setConflictsToken((n) => n + 1); }}
        defaultOpen={!!focus.id} focusId={focus.id} />

      {/* 코딩 룰북 초안 — 위반 규칙을 카테고리로 묶어 문서화 (Q4) */}
      <CodingRulebookPanel jobUrl={jobUrl} cacheRoot={cacheRoot} defaultOpen={false} />

      {/* 함수별 커버리지 + 실패 테스트 — 빌드 산출물 → SCM 입력 문서 폴백(N1) */}
      <FunctionCoveragePanel jobUrl={jobUrl} cacheRoot={cacheRoot} />

      {/* 테스트 설계 어드바이저 — 기법 권고·설계-시험 갭 (L2) */}
      {SHOW.testDesign && <TestDesignPanel jobUrl={jobUrl} cacheRoot={cacheRoot} />}
    </div>
  );
}
