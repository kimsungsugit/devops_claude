import { useState } from 'react';
import StatusBadge from './StatusBadge.jsx';

/**
 * (R48-b) 생성 문제 목록 — "이미 문제가 된 것(actual)" 과 "문제가 될 수 있는 것(potential)" 을 갈라 보인다.
 *
 * - 서버 값 그대로: `severity`(error/warning/risk)·`kind`·`source`·`message`·`facts`. 판정 계산 0.
 * - 빈 목록은 "문제 없음" 이 아닐 수 있다 — `sources` 에 근거가 없는 축이 있으면 그 사실을 적는다.
 * - Gemini 설명은 **버튼**으로만 부른다(`onExplain` 이 있을 때). 응답의 `generated_by` 와 `model` 을 그대로 보인다 —
 *   룰 폴백이면 "룰 문장" 이라고 적는다(문장의 출처를 숨기지 않는다).
 */
const SEVERITY_TONE = Object.freeze({ error: 'danger', warning: 'warning', risk: 'neutral' });
const SEVERITY_LABEL = Object.freeze({ error: '오류', warning: '경고', risk: '주의' });
const KIND_LABEL = Object.freeze({ actual: '문제가 된 것', potential: '문제가 될 수 있는 것' });
const SOURCE_LABEL = Object.freeze({
  generation: '생성 중', gate_report: '게이트 리포트', docx_validate: '구조 검증', confidence: '신뢰도',
  reference: '참조 SwUDS', scores: '기록 점수', evidence: '근거',
});

function severityTone(sev) { return SEVERITY_TONE[sev] || 'neutral'; }

function IssueRow({ it, explained }) {
  const facts = it.facts && Object.keys(it.facts).length ? it.facts : null;
  return (
    <li style={{ marginBottom: 6 }}>
      <StatusBadge tone={severityTone(it.severity)}>{SEVERITY_LABEL[it.severity] || it.severity}</StatusBadge>{' '}
      <span>{it.message}</span>
      <span style={{ color: 'var(--text-muted)', marginLeft: 6, fontSize: '0.9em' }}>
        [{SOURCE_LABEL[it.source] || it.source || '—'}{it.stage ? ` · ${it.stage}` : ''} · <code>{it.code}</code>]
      </span>
      {facts && (
        <span style={{ color: 'var(--text-muted)', marginLeft: 6, fontSize: '0.85em', fontFamily: 'monospace' }}>
          {Object.entries(facts).filter(([, v]) => v != null && typeof v !== 'object').map(([k, v]) => `${k}=${v}`).join(' ')}
        </span>
      )}
      {explained && (
        <div style={{ marginLeft: 8, marginTop: 2, fontSize: '0.95em' }}>
          {explained.explanation && <div>↳ {explained.explanation}</div>}
          {explained.action && <div style={{ color: 'var(--accent)' }}>→ {explained.action}</div>}
        </div>
      )}
    </li>
  );
}

export default function IssueList({ issues, counts, sources, onExplain, compact = false, title = '문제 목록' }) {
  const [explain, setExplain] = useState(null);     // 서버 응답 그대로
  const [explaining, setExplaining] = useState(false);
  const [explainErr, setExplainErr] = useState('');
  const list = Array.isArray(issues) ? issues : [];
  const actual = list.filter((i) => i.kind === 'actual');
  const potential = list.filter((i) => i.kind !== 'actual');
  const byCode = new Map((explain?.items || []).map((i) => [i.code, i]));
  const missingSources = sources
    ? Object.entries(sources).filter(([k, v]) => v === false && k !== 'generation').map(([k]) => SOURCE_LABEL[k] || k)
    : [];

  const runExplain = async () => {
    if (!onExplain) return;
    setExplaining(true); setExplainErr('');
    try {
      const d = await onExplain();
      if (!d || typeof d.summary !== 'string') throw new Error('설명 응답 형식이 다릅니다');
      setExplain(d);
    } catch (e) {
      setExplainErr(`설명 생성 실패: ${e?.message || e}`);
    } finally {
      setExplaining(false);
    }
  };

  return (
    <div data-testid="issue-list" style={{ fontSize: compact ? 'var(--text-xs)' : 'var(--text-sm)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
        <strong>{title}</strong>
        <span data-testid="issue-counts">
          문제가 된 것 <strong>{actual.length}</strong> · 문제가 될 수 있는 것 <strong>{potential.length}</strong>
          {counts?.by_severity && (
            <> · 오류 {counts.by_severity.error ?? 0} · 경고 {counts.by_severity.warning ?? 0} · 주의 {counts.by_severity.risk ?? 0}</>
          )}
        </span>
        {onExplain && list.length > 0 && (
          <button type="button" className="btn-sm" onClick={runExplain} disabled={explaining}>
            {explaining ? 'Gemini 설명 생성 중…' : (explain ? 'Gemini 로 다시 설명' : 'Gemini 로 풀어 설명')}
          </button>
        )}
      </div>
      {sources && sources.generation === false && (
        <div style={{ color: 'var(--text-muted)' }}>생성 중 수집 기록이 없는 run 입니다(R48 이전 또는 다른 경로) — 아래는 사후 근거에서 파생한 항목만입니다.</div>
      )}
      {list.length === 0 && (
        <div data-testid="issue-empty" style={{ color: 'var(--text-muted)' }}>
          관측된 문제가 없습니다.
          {missingSources.length > 0 && <> 단, 근거가 없는 축이 있습니다: {missingSources.join(', ')} — "문제 없음" 이 아니라 "잰 것이 없음" 입니다.</>}
        </div>
      )}
      {explainErr && <div role="alert" style={{ color: 'var(--color-danger)' }}>{explainErr}</div>}
      {explain && (
        <div data-testid="issue-explain" style={{ margin: '6px 0', padding: 8, border: '1px solid var(--border)', borderRadius: 6 }}>
          <div style={{ marginBottom: 4 }}>
            <StatusBadge tone={explain.generated_by === 'llm' ? 'success' : 'neutral'}>
              {explain.generated_by === 'llm' ? `Gemini${explain.model ? ` · ${explain.model}` : ''}` : '룰 문장(LLM 미사용)'}
            </StatusBadge>
            {explain.generated_by !== 'llm' && explain.llm_reason && (
              <span style={{ color: 'var(--text-muted)', marginLeft: 6 }}>{explain.llm_reason}</span>
            )}
            {explain.items_total > explain.items_shown && (
              <span style={{ color: 'var(--text-muted)', marginLeft: 6 }}>({explain.items_total}건 중 {explain.items_shown}건만 설명에 실었습니다)</span>
            )}
          </div>
          <div style={{ whiteSpace: 'pre-wrap' }}>{explain.summary}</div>
        </div>
      )}
      {actual.length > 0 && (
        <div style={{ marginTop: 4 }}>
          <div style={{ fontWeight: 600 }}>{KIND_LABEL.actual} ({actual.length})</div>
          <ul style={{ margin: 0, paddingLeft: '1.1em' }}>
            {actual.map((it, i) => <IssueRow key={`${it.code}-${i}`} it={it} explained={byCode.get(it.code)} />)}
          </ul>
        </div>
      )}
      {potential.length > 0 && (
        <div style={{ marginTop: 4 }}>
          <div style={{ fontWeight: 600 }}>{KIND_LABEL.potential} ({potential.length})</div>
          <ul style={{ margin: 0, paddingLeft: '1.1em' }}>
            {potential.map((it, i) => <IssueRow key={`${it.code}-${i}`} it={it} explained={byCode.get(it.code)} />)}
          </ul>
        </div>
      )}
    </div>
  );
}
