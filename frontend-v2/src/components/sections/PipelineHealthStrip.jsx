/**
 * PipelineHealthStrip — SDS(아키텍처)→UDS→소스/정적→SUTS(UT)→SITS(IT)→STS 파이프라인 헬스.
 * 프로젝트 요약탭 상단에서 V-model 좌→우 흐름의 단계별 상태를 한 줄로 조망하고,
 * 노드 클릭 시 해당 상세 탭으로 딥링크한다(window.__detailSection).
 * 상태 도출 로직은 pipelineHealth.js(derivePipelineNodes — 순수 함수) 참조.
 */
import { derivePipelineNodes } from '../../pipelineHealth.js';

const STATE_COLOR = {
  ok: 'var(--color-success)',
  warn: 'var(--color-warning)',
  danger: 'var(--color-danger)',
  muted: 'var(--text-muted)',
};
const STATE_LABEL = { ok: '정상', warn: '주의', danger: '문제', muted: '미확인' };

export default function PipelineHealthStrip({ trace, prqa, scmVcast, rollup, latestViolationsDelta, onNavigate }) {
  const nodes = derivePipelineNodes({ trace, prqa, scmVcast, rollup, latestViolationsDelta });
  const go = (section) => {
    if (onNavigate) return onNavigate(section);
    if (typeof window.__detailSection === 'function') window.__detailSection(section);
    return undefined;
  };
  return (
    <div className="panel" style={{ padding: 'var(--sp-3)' }}>
      <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600, marginBottom: 'var(--sp-2)' }}>
        파이프라인 헬스 (설계 → 테스트)
        <span style={{ fontSize: 'var(--text-xs)', fontWeight: 400, color: 'var(--text-muted)', marginLeft: 'var(--sp-2)' }}>
          (시험 합부는 SCM 스냅샷 · 클릭 시 해당 탭)
        </span>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'stretch', gap: 'var(--sp-1)' }}>
        {nodes.map((n, i) => (
          <div key={n.id} style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-1)' }}>
            {i > 0 && <span aria-hidden="true" style={{ color: 'var(--text-muted)', padding: '0 2px' }}>→</span>}
            <button
              type="button"
              onClick={() => go(n.section)}
              title={n.title}
              aria-label={`${n.label}: ${STATE_LABEL[n.state]} — ${n.detail}`}
              style={{
                display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2,
                padding: '6px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
                background: 'transparent', cursor: 'pointer', textAlign: 'left', minWidth: 120,
              }}>
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 'var(--text-xs)', fontWeight: 700, color: 'var(--text)' }}>
                <span aria-hidden="true" style={{
                  width: 8, height: 8, borderRadius: '50%', background: STATE_COLOR[n.state], display: 'inline-block',
                }} />
                {n.label}
              </span>
              <span style={{ fontSize: 'var(--text-xs)', color: n.state === 'danger' ? 'var(--color-danger)' : 'var(--text-muted)' }}>
                {n.detail}
              </span>
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
