/**
 * AggregateCharts — CSS/SVG-based charts for aggregate project statistics.
 * Renders only when 2+ projects are available.
 */

import { HorizontalBar, DonutChart } from './charts.jsx';

export default function AggregateCharts({ projects, buildStats }) {
  if (!projects || projects.length < 1) return null;

  const maxCov = 100;
  const maxDiag = Math.max(...projects.map(p => p.diagnostics || 0), 1);
  const maxLoc = Math.max(...projects.map(p => p.loc || 0), 1);

  const bs = buildStats || {};
  const buildCounts = {
    success: bs.successCount ?? projects.filter(p => p.result === 'SUCCESS').length,
    fail: bs.failCount ?? projects.filter(p => (p.result || '').includes('FAIL')).length,
    unstable: bs.unstableCount ?? 0,
    disabled: bs.disabledCount ?? 0,
    total: bs.total ?? projects.length,
    other: 0,
  };
  buildCounts.other = buildCounts.total - buildCounts.success - buildCounts.fail - buildCounts.unstable - buildCounts.disabled;

  // Projects with actual analysis data (have coverage or test or prqa data)
  const analyzedProjects = projects.filter(p => p.line_rate != null || p.ut_total > 0 || p.diagnostics > 0);
  const totalRequested = buildCounts.total || projects.length;

  return (
    <div>
      {analyzedProjects.length < totalRequested && (
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--sp-2)', padding: '0 var(--sp-1)' }}>
          {totalRequested}개 프로젝트 중 {analyzedProjects.length}개만 분석 데이터 있음 — Job 선택 후 동기화 & 분석을 실행하면 데이터가 추가됩니다
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 'var(--sp-3)', margin: '0 0 var(--sp-3)' }}>

      {/* 1. Build result donut + legend */}
      <div className="panel" style={{ boxShadow: 'none', padding: 'var(--sp-3)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 'var(--sp-2)', color: 'var(--text-muted)' }}>빌드 결과 분포</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-4)' }}>
          <DonutChart
            segments={[
              { value: buildCounts.success, color: 'var(--color-success)', label: '성공' },
              { value: buildCounts.unstable, color: 'var(--color-warning)', label: '불안정' },
              { value: buildCounts.fail, color: 'var(--color-danger)', label: '실패' },
              { value: buildCounts.disabled + buildCounts.other, color: 'var(--text-muted)', label: '기타' },
            ].filter(s => s.value > 0)}
            size={80}
            strokeWidth={12}
            centerSub="프로젝트"
          />
          <div>
            {buildCounts.success > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-1)', fontSize: 'var(--text-xs)' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--color-success)', flexShrink: 0 }} /> 성공: {buildCounts.success}
              </div>
            )}
            {buildCounts.fail > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-1)', fontSize: 'var(--text-xs)' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--color-danger)', flexShrink: 0 }} /> 실패: {buildCounts.fail}
              </div>
            )}
            {buildCounts.unstable > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-1)', fontSize: 'var(--text-xs)' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--color-warning)', flexShrink: 0 }} /> 불안정: {buildCounts.unstable}
              </div>
            )}
            {(buildCounts.disabled + buildCounts.other) > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-1)', fontSize: 'var(--text-xs)' }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: 'var(--text-muted)', flexShrink: 0 }} /> 기타: {buildCounts.disabled + buildCounts.other}
              </div>
            )}
          </div>
        </div>
        {/* Status distribution bar */}
        {buildCounts.total > 0 && (
          <div style={{ marginTop: 'var(--sp-2)' }}>
            <div style={{ display: 'flex', height: 8, borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
              {buildCounts.success > 0 && <div title={`성공: ${buildCounts.success}`} style={{ flex: buildCounts.success, background: 'var(--color-success)', transition: 'flex 0.3s' }} />}
              {buildCounts.unstable > 0 && <div title={`불안정: ${buildCounts.unstable}`} style={{ flex: buildCounts.unstable, background: 'var(--color-warning)', transition: 'flex 0.3s' }} />}
              {buildCounts.fail > 0 && <div title={`실패: ${buildCounts.fail}`} style={{ flex: buildCounts.fail, background: 'var(--color-danger)', transition: 'flex 0.3s' }} />}
              {(buildCounts.disabled + buildCounts.other) > 0 && <div title={`기타: ${buildCounts.disabled + buildCounts.other}`} style={{ flex: buildCounts.disabled + buildCounts.other, background: 'var(--border)', transition: 'flex 0.3s' }} />}
            </div>
            {bs.recentBuilds != null && (
              <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 'var(--sp-1)' }}>
                최근 7일: {bs.recentBuilds}개 빌드 중 {bs.recentSuccess ?? 0}개 성공
              </div>
            )}
          </div>
        )}
      </div>

      {/* 2. Coverage comparison */}
      <div className="panel" style={{ boxShadow: 'none', padding: 'var(--sp-3)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 'var(--sp-2)', color: 'var(--text-muted)' }}>구문 커버리지 (UT 기준, %)</div>
        {projects.map(p => (
          <HorizontalBar
            key={p.job_url}
            label={p.name || '?'}
            value={Math.round((p.line_rate || 0) * 100)}
            max={maxCov}
            color={(p.line_rate || 0) >= 0.8 ? 'var(--color-success)' : 'var(--color-warning)'}
            suffix="%"
          />
        ))}
        {/* 구문 커버리지는 UT 기준(coverage_basis='ut_statement')이 대시보드 표준값. 빌드는 vcast_ut_statements,
            SCM은 coverage_ut를 씀. UT 구문을 못 뽑아 다른 기준으로 대체된 프로젝트만 폭로한다(침묵 혼재 방지 —
            과거 'scm_vcast 지표 상이' 상시 각주를 basis 조건부로 대체). */}
        {(() => {
          const BASIS_LABEL = {
            it_statement: 'IT 구문', it_functions: 'IT 함수',
            combined_statement: 'UT+IT 합산', build_line: '빌드 라인커버',
          };
          const nonUt = projects.filter(p => p.coverage_source != null && p.coverage_basis && p.coverage_basis !== 'ut_statement');
          if (nonUt.length === 0) return null;
          return (
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 'var(--sp-1)' }}>
              * <b>{nonUt.map(p => `${p.name || '?'}(${BASIS_LABEL[p.coverage_basis] || p.coverage_basis})`).join(', ')}</b> — UT 구문 커버리지 미산출로 대체 지표 표시, 절대 비교 주의
            </div>
          );
        })()}
        {/* 커버리지가 빌드·SCM 이력 모두 없어 0으로 뜨면 '진짜 0'과 구분(침묵 0 방지).
            빌드 line_rate가 0.0 플레이스홀더면 null이 아니라 coverage_source가 null이므로 그걸로 판정. */}
        {projects.some(p => p.coverage_source == null) && (
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 'var(--sp-1)' }}>
            † 일부 프로젝트는 커버리지 미집계(빌드·SCM 로드 이력 모두 없음)로 <b>0 표시</b> — 실제 0 아님
          </div>
        )}
      </div>

      {/* 3. PRQA diagnostics comparison */}
      <div className="panel" style={{ boxShadow: 'none', padding: 'var(--sp-3)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 'var(--sp-2)', color: 'var(--text-muted)' }}>PRQA 진단 건수</div>
        {projects.map(p => (
          <HorizontalBar
            key={p.job_url}
            label={p.name || '?'}
            value={p.diagnostics || 0}
            max={maxDiag}
            color={(p.diagnostics || 0) > 100 ? 'var(--color-warning)' : 'var(--color-success)'}
          />
        ))}
      </div>

      {/* 4. Test cases comparison (UT/IT stacked) */}
      <div className="panel" style={{ boxShadow: 'none', padding: 'var(--sp-3)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 'var(--sp-2)', color: 'var(--text-muted)' }}>테스트 케이스 수</div>
        {(() => { const maxTC = Math.max(...projects.map(pp => (pp.ut_total || 0) + (pp.it_total || 0)), 1); return projects.map(p => {
          const ut = p.ut_total || 0;
          const it = p.it_total || 0;
          const total = ut + it;
          return (
            <div key={p.job_url} style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', marginBottom: 'var(--sp-1)' }}>
              <span
                style={{ width: 120, fontSize: 'var(--text-xs)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 0 }}
                title={p.name}
              >
                {p.name}
              </span>
              <div style={{ flex: 1, height: 16, background: 'var(--border)', borderRadius: 'var(--radius-sm)', overflow: 'hidden', display: 'flex' }}>
                {ut > 0 && <div title={`UT: ${ut}`} style={{ width: `${(ut / maxTC) * 100}%`, background: 'var(--color-info)', transition: 'width 0.4s' }} />}
                {it > 0 && <div title={`IT: ${it}`} style={{ width: `${(it / maxTC) * 100}%`, background: 'var(--color-purple)', transition: 'width 0.4s' }} />}
              </div>
              <span style={{ width: 60, textAlign: 'right', fontSize: 'var(--text-xs)', fontWeight: 600, flexShrink: 0 }}>
                {total.toLocaleString()}
              </span>
            </div>
          );
        }); })()}
        <div style={{ display: 'flex', gap: 'var(--sp-3)', marginTop: 'var(--sp-1)', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
          <span><span style={{ display: 'inline-block', width: 8, height: 8, background: 'var(--color-info)', borderRadius: 2, marginRight: 4 }} />UT</span>
          <span><span style={{ display: 'inline-block', width: 8, height: 8, background: 'var(--color-purple)', borderRadius: 2, marginRight: 4 }} />IT</span>
        </div>
        {/* 빌드에 TC가 없어 SCM 로드 이력(VectorCAST)에서 회수한 개수임을 표기. */}
        {projects.some(p => p.tests_source === 'scm_vcast') && (
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 'var(--sp-1)' }}>
            * 일부 프로젝트 TC 수는 SCM 로드 이력의 <b>VectorCAST UT/IT 개수</b>
          </div>
        )}
      </div>

      {/* 5. Code size comparison */}
      <div className="panel" style={{ boxShadow: 'none', padding: 'var(--sp-3)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 'var(--sp-2)', color: 'var(--text-muted)' }}>코드 규모 (LOC)</div>
        {projects.map(p => (
          <HorizontalBar
            key={p.job_url}
            label={p.name || '?'}
            value={p.loc || 0}
            max={maxLoc}
            color="var(--accent)"
          />
        ))}
        {/* lizard NLOC(순수)과 QAC LOC(헤더 포함)이 섞이면 프로젝트 간 절대 비교가 부정확 — 정직 표기(silent 혼재 방지). */}
        {projects.some(p => p.code_metrics_source === 'qac') && (
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 'var(--sp-1)' }}>
            * 일부 프로젝트는 lizard 미산출로 <b>QAC LOC(헤더 포함)</b>으로 대체 — 절대 비교 주의
          </div>
        )}
        {/* 완전 부재(lizard·QAC 둘 다 없음) 프로젝트는 0으로 뜨는데 '진짜 0'과 구분되도록 사유를 명시(침묵 0 방지). */}
        {projects.some(p => p.code_metrics_reason) && (
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 'var(--sp-1)' }}>
            † 일부 프로젝트는 코드 규모 산출물이 없어 <b>0(미집계)</b>으로 표시 — 실제 0 아님
          </div>
        )}
      </div>

      {/* 6. PRQA compliance rate comparison */}
      <div className="panel" style={{ boxShadow: 'none', padding: 'var(--sp-3)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 'var(--sp-2)', color: 'var(--text-muted)' }}>PRQA 준수율 (%)</div>
        {projects.map(p => {
          const ci = p.rcr_compliance_index || 0;
          return (
            <HorizontalBar
              key={p.job_url}
              label={p.name || '?'}
              value={ci}
              max={100}
              color={ci >= 90 ? 'var(--color-success)' : ci >= 70 ? 'var(--color-warning)' : 'var(--color-danger)'}
              suffix="%"
            />
          );
        })}
      </div>
      </div>
    </div>
  );
}
