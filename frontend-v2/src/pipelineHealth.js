/**
 * pipelineHealth — 파이프라인 헬스 스트립의 노드 상태 도출(순수 함수).
 * PipelineHealthStrip.jsx에서 분리(react-refresh 규칙: 컴포넌트 파일은 컴포넌트만 export).
 *
 * ISO 정직성: 증거부재(데이터 없음)는 'muted(미확인)' — ok도 danger도 아니다.
 */

function fmtInt(n) {
  return (n == null || Number.isNaN(Number(n))) ? '—' : Number(n).toLocaleString();
}

/**
 * @param {object} p { trace, prqa, scmVcast, rollup, latestViolationsDelta }
 * @returns {Array<{id,label,state:'ok'|'warn'|'danger'|'muted',detail,section,title}>}
 */
export function derivePipelineNodes({ trace, prqa, scmVcast, rollup, latestViolationsDelta }) {
  const t = trace?.has_data ? trace : null;
  const bc = t?.band_counts || {};
  const nodes = [];

  // SDS — SW 아키텍처 설계와 요구의 연결(추적성 밴드).
  {
    const band = bc.SDS;
    const state = t == null ? 'muted' : (band || 0) > 0 ? 'ok' : 'warn';
    nodes.push({
      id: 'sds', label: 'SDS 설계', state, section: 'srssds',
      detail: t == null ? '추적성 없음' : `연결 요구 ${fmtInt(band || 0)}`,
      title: '개발자: SW 아키텍처(SDS)와 요구사항 연결 현황 — 클릭 시 요구사항 커버리지 탭',
    });
  }
  // UDS — 단위 설계 + 검토 대기 문서(FLAG).
  {
    const band = bc.UDS;
    const flags = rollup?.cumulative_flag_docs || 0;
    const state = t == null ? 'muted' : flags > 0 ? 'warn' : (band || 0) > 0 ? 'ok' : 'warn';
    nodes.push({
      id: 'uds', label: 'UDS 상세설계', state, section: 'docgen',
      detail: t == null ? '추적성 없음' : flags > 0 ? `검토 대기 ${fmtInt(flags)}` : `연결 요구 ${fmtInt(band || 0)}`,
      title: '개발자: 단위 상세설계(UDS) 연결 + 변경 후 검토 대기 문서 — 클릭 시 문서 생성 탭',
    });
  }
  // 소스/정적 — PRQA 준수율 + 최신 빌드 위반 delta.
  {
    const compliance = prqa?.project_compliance_index;
    const d = latestViolationsDelta;
    let state = 'muted';
    if (compliance != null) {
      const c = Number(compliance);
      state = c < 70 ? 'danger' : (c < 90 || (d || 0) > 0) ? 'warn' : 'ok';
    }
    const deltaTxt = d == null ? '' : ` · Δ위반 ${d > 0 ? `+${d}` : d}`;
    nodes.push({
      id: 'static', label: '소스/정적분석', state, section: 'analysis',
      // I2: 준수율 결측이어도 Δ위반은 노출 — 위반 급증이 스트립에서 침묵하지 않게(정직성).
      detail: compliance == null ? `준수율 미산출${deltaTxt}` : `준수율 ${Math.round(Number(compliance))}%${deltaTxt}`,
      title: '개발자: MISRA/PRQA 준수율과 최신 빌드 위반 증감 — 클릭 시 테스트 결과 탭',
    });
  }
  // SUTS(UT) / SITS(IT) — VectorCAST 스냅샷 합부. 증거부재는 muted(0/0 통과 위장 금지).
  const mkTest = (id, label, passed, total, roleHint) => {
    const state = scmVcast == null || total == null ? 'muted'
      : (total > 0 && passed === total) ? 'ok'
      : (passed ?? 0) < (total ?? 0) ? 'danger' : 'muted';
    const fail = total != null && passed != null ? total - passed : null;
    return {
      id, label, state, section: 'build',
      // I1: 0/0은 '통과 0/0'(fake-ok 문구)이 아니라 '결과 없음' — muted 점과 문구 일치.
      detail: scmVcast == null || total == null || total === 0 ? '결과 없음'
        : fail > 0 ? `실패 ${fmtInt(fail)}/${fmtInt(total)}` : `통과 ${fmtInt(passed)}/${fmtInt(total)}`,
      title: `${roleHint} (SCM 스냅샷) — 클릭 시 빌드 & 입력 데이터 탭`,
    };
  };
  nodes.push(mkTest('suts', 'SUTS 단위시험', scmVcast?.ut_passed, scmVcast?.ut_total, '테스터: SW 단위시험(UT) 합부'));
  nodes.push(mkTest('sits', 'SITS 통합시험', scmVcast?.it_passed, scmVcast?.it_total, '테스터: SW 통합시험(IT) 합부'));
  // STS — 요구 기반 시험 + ASIL 시험 미달.
  {
    const band = bc.STS;
    const gap = t?.asil_gap_count || 0;
    const state = t == null ? 'muted' : gap > 0 ? 'danger' : (band || 0) > 0 ? 'ok' : 'warn';
    nodes.push({
      id: 'sts', label: 'STS 요구시험', state, section: 'srssds',
      detail: t == null ? '추적성 없음' : gap > 0 ? `ASIL 시험 미달 ${fmtInt(gap)}` : `연결 요구 ${fmtInt(band || 0)}`,
      title: '테스터: SW 요구 기반 시험(STS) 연결 + ASIL 등급 대비 시험 수준 미달 — 클릭 시 요구사항 커버리지 탭',
    });
  }
  return nodes;
}
