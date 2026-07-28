/**
 * CodingRulebookPanel — 정적분석 위반에서 뽑은 팀 코딩 룰북 초안(Q4).
 * POST /api/summary/coding-rulebook 소비: probe(대상 규칙·증거 수만, LLM 0회) → 생성 버튼.
 *
 * 카테고리(필수/요구/권고/프로젝트 관례) 아코디언 + **Markdown 내보내기**.
 * Markdown은 서버가 조립한 문자열을 그대로 저장한다 — 클라이언트에서 다시 만들면 화면과
 * 파일의 표기가 갈라진다. 저장은 기존 graphPrimitives.downloadBlob 재사용(새 라이브러리 금지).
 *
 * 정직성: 증거 없는 규칙은 룰북에서 빠지며 그 사유를 제외 목록으로 노출한다(빠진 규칙이
 * '문제 없음'으로 읽히면 안 된다). note(초안≠사내 표준)는 서버 고정값을 그대로 표시.
 */
import { useEffect, useState } from 'react';
import { post } from '../../api.js';
import { downloadBlob } from '../graphPrimitives.jsx';
import SummaryPanel from './SummaryPanel.jsx';

const xs = { fontSize: 'var(--text-xs)' };
const btn = {
  ...xs, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
  background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)',
};

const EXCLUDE_KO = {
  no_code_evidence: '코드 증거 없음(일반론 방지)',
  generation_error: '초안 생성 실패',
  llm_unavailable: 'LLM 미설정',
  llm_error: 'AI 호출 실패',
  llm_empty_or_invalid: 'AI 응답 무효',
  hallucinated_identifiers: '증거 밖 식별자(환각 폐기)',
  rule_echo_mismatch: '규칙 번호 불일치',
};
const CONF_COLOR = { high: 'var(--color-success)', medium: 'var(--color-warning)', low: 'var(--text-muted)' };

function RuleCard({ r }) {
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: '6px 8px', marginBottom: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <b style={xs}>{r.rule}</b>
        {r.title && <span style={{ ...xs, color: 'var(--text-muted)' }}>{r.title}</span>}
        <span style={{ ...xs, color: CONF_COLOR[r.confidence] || 'var(--text-muted)' }}>확신도 {r.confidence}</span>
        {r.violations != null && <span style={{ ...xs, color: 'var(--text-muted)' }}>· 최근 위반 {r.violations}</span>}
      </div>
      {r.intent && <div style={xs}><b>의도</b>: {r.intent}</div>}
      {r.rationale && <div style={{ ...xs, color: 'var(--text-muted)' }}><b>근거</b>: {r.rationale}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 6, marginTop: 4 }}>
        {r.avoid_pattern && (
          <div>
            <div style={{ ...xs, color: 'var(--color-danger)' }}>피할 패턴</div>
            <pre style={{
              ...xs, whiteSpace: 'pre-wrap', fontFamily: 'monospace', margin: 0,
              background: 'var(--bg-subtle)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)', padding: '3px 6px', overflowX: 'auto',
            }}>{r.avoid_pattern}</pre>
          </div>
        )}
        {r.comply_pattern && (
          <div>
            <div style={{ ...xs, color: 'var(--color-success)' }}>준수 패턴</div>
            <pre style={{
              ...xs, whiteSpace: 'pre-wrap', fontFamily: 'monospace', margin: 0,
              background: 'var(--bg-subtle)', border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)', padding: '3px 6px', overflowX: 'auto',
            }}>{r.comply_pattern}</pre>
          </div>
        )}
      </div>
      {(r.exceptions || []).length > 0 && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>예외: {(r.exceptions || []).join(' · ')}</div>
      )}
      <div style={{ ...xs, color: 'var(--text-muted)' }}>
        분류 근거: {r.category_basis}
        {r.evidence_used && ` · 증거 diff ${r.evidence_used.fix_diffs}·발췌 ${r.evidence_used.unresolved_excerpts}`}
      </div>
    </div>
  );
}

export default function CodingRulebookPanel({ jobUrl, cacheRoot, defaultOpen = true }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const resp = await post('/api/summary/coding-rulebook', { job_url: jobUrl, cache_root: cacheRoot, probe: true });
        if (!cancelled) { setData(resp); setError(''); }
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot]);

  const generate = async (force) => {
    setBusy(true);
    setError('');
    try {
      const resp = await post('/api/summary/coding-rulebook', {
        job_url: jobUrl, cache_root: cacheRoot, ...(force ? { force: true } : {}),
      });
      setData(resp);
    } catch (e) {
      setError(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const exportMd = () => {
    if (!data?.markdown) return;
    downloadBlob(new Blob([data.markdown], { type: 'text/markdown;charset=utf-8' }), 'coding-rulebook.md');
  };

  const generated = data?.generated;
  const totals = data?.totals || {};

  return (
    <SummaryPanel
      title="코딩 룰북 초안 (위반 → 규칙)"
      defaultOpen={defaultOpen}
      meta={<>
        {generated && (
          <span style={{ ...xs, color: 'var(--text-muted)' }}>
            수록 {totals.included ?? 0}건 · 제외 {totals.excluded ?? 0} · AI {totals.ai_enriched ?? 0}
          </span>
        )}
        {busy && <span className="spinner" />}
      </>}
      /* ⚠ 기본 접힘이라 본문의 오류·불가 안내가 화면에서 사라진다 — 헤더에 신호를 남긴다 */
      problem={<>
        {error && <span style={{ ...xs, color: 'var(--color-danger)' }} title={error}>⚠ 조회 실패</span>}
        {data?.available === false && <span style={{ ...xs, color: 'var(--color-warning)' }}>대상 규칙 없음</span>}
      </>}
      actions={<>
        {generated && data?.markdown && (
          <button type="button" style={btn} onClick={exportMd}>Markdown 저장</button>
        )}
        {data?.available !== false && (
          <button type="button" style={btn} onClick={() => generate(Boolean(generated))} disabled={busy}>
            {busy ? '생성 중…' : generated ? '재생성' : '룰북 생성 (AI)'}
          </button>
        )}
      </>}
    >
      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>룰북 오류: {error}</div>}
      {data && data.available === false && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          {data.reason === 'no_rules_in_trend' ? '위반 규칙 트렌드가 없어 룰북을 만들 수 없습니다.'
            : `룰북을 만들 수 없습니다 (${data.reason})`}
        </div>
      )}

      {data?.available && !generated && (
        <div>
          <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>
            위반 상위 규칙을 코드 증거와 함께 팀 코딩 룰 초안으로 정리합니다(규칙당 Gemini 1회 — 버튼 클릭 시에만).
          </div>
          {(data.candidates || []).map((c) => (
            <div key={c.rule} style={{ ...xs, color: 'var(--text-muted)' }}>
              · {c.rule} — 최근 위반 {c.latest ?? '—'} · 코드 증거 {c.evidence}건
              {c.evidence === 0 && <span style={{ color: 'var(--color-warning)' }}> (증거 없어 제외 예정)</span>}
            </div>
          ))}
        </div>
      )}

      {generated && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-2)' }}>
          {(data.sections || []).length === 0 && (
            <div style={{ ...xs, color: 'var(--text-muted)' }}>수록할 규칙이 없습니다 — 아래 제외 사유를 확인하세요.</div>
          )}
          {(data.sections || []).map((s, i) => (
            <details key={s.category} open={i === 0}>
              <summary style={{ ...xs, cursor: 'pointer', fontWeight: 700 }}>
                {s.label} <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>({s.rules.length}건)</span>
              </summary>
              <div style={{ marginTop: 4 }}>
                {s.rules.map((r) => <RuleCard key={r.rule} r={r} />)}
              </div>
            </details>
          ))}

          {(data.excluded || []).length > 0 && (
            <div>
              <div style={{ ...xs, fontWeight: 700 }}>제외된 규칙 {(data.excluded || []).length}건</div>
              {(data.excluded || []).map((e) => (
                <div key={e.rule} style={{ ...xs, color: 'var(--text-muted)' }}>
                  · {e.rule} — {EXCLUDE_KO[e.reason] || e.reason}
                </div>
              ))}
            </div>
          )}

          <div style={{ ...xs, color: 'var(--text-muted)', borderTop: '1px solid var(--border)', paddingTop: 6 }}>
            ⚠ {data.note}
            {data.model && ` · 모델 ${data.model}`}
            {data.generated_at && ` · 생성 ${String(data.generated_at).replace('T', ' ')}`}
            {data.cached ? ' · 캐시됨' : ''}
          </div>
        </div>
      )}
    </SummaryPanel>
  );
}
