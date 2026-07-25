/**
 * RuleEvidenceCards — 룰 워크벤치 카드 2종(J2/J3).
 * ① UnresolvedEvidenceCard: POST /api/summary/rule-unresolved-evidence(결정론, LLM 0회) —
 *    라인 레벨 위반 데이터가 없으므로(RCR=파일×규칙 카운트가 최상세) 코드 수준 근거는
 *    빌드 스냅샷 diff가 유일 경로다.
 * ② RuleDefinitionCard: POST /api/summary/rule-definition — 팀 코딩 룰 초안(LLM on-demand,
 *    mount 시 probe만 — 캐시 히트면 자동 표시, 미스면 생성 버튼. 자동 LLM 호출 0).
 *
 * ISO 정직성: '파일 무변경'은 실패가 아니라 유효 증거(위반 잔존 + 구간 내 미수정) — muted 배지.
 * note(관측≠인과·초안≠확정 룰)는 서버 고정 주입 값을 상시 노출. counts 결측(no_rcr)은
 * '—'로 표기(0 위장 금지). 증거 0건 규칙은 no_code_evidence로 초안 자체를 만들지 않는다.
 */
import { useEffect, useState } from 'react';
import { post } from '../../api.js';

const REASON_KO = {
  file_not_in_snapshot: '소스 스냅샷에서 파일을 찾지 못했습니다',
  file_ambiguous_in_snapshot: '동일 이름 파일이 여러 개라 특정할 수 없습니다',
  snapshot_missing: '해당 빌드에 소스 스냅샷이 없습니다',
  snapshot_read_failed: '스냅샷 파일을 읽지 못했습니다',
  build_not_cached: '해당 빌드가 캐시에 없습니다',
  params_required: '필수 파라미터가 없습니다',
};

const xs = { fontSize: 'var(--text-xs)' };
const btn = {
  ...xs, padding: '1px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
  background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)',
};
const mono = {
  whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 'var(--text-xs)',
  background: 'var(--bg-elevated, var(--hover))', border: '1px solid var(--border)',
  borderRadius: 'var(--radius-sm)', padding: '4px 8px', margin: '2px 0', overflowX: 'auto',
};

function cnt(v) {
  return v == null ? '—' : v;
}

export function UnresolvedEvidenceCard({ jobUrl, cacheRoot, rule, file, fromBuild, toBuild }) {
  const [state, setState] = useState('idle'); // idle | loading | done | error
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const load = async () => {
    setState('loading');
    setError('');
    try {
      const resp = await post('/api/summary/rule-unresolved-evidence', {
        job_url: jobUrl, cache_root: cacheRoot, rule,
        file: file.path, from_build: fromBuild, to_build: toBuild,
      });
      setData(resp);
      setState('done');
    } catch (e) {
      setError(String(e?.message || e));
      setState('error');
    }
  };
  return (
    <div style={{ borderLeft: '3px solid var(--color-warning)', padding: '4px 8px', marginTop: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={xs}>{file.path} <b>{file.count}</b>건 (최신)</span>
        {state !== 'done' && (
          <button type="button" onClick={load} disabled={state === 'loading'} style={btn}>
            {state === 'loading' ? '조회 중…' : `구간 증거 보기 (#${fromBuild}→#${toBuild})`}
          </button>
        )}
      </div>
      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>구간 증거 조회 오류: {error}</div>}
      {state === 'done' && data && (
        data.available === false ? (
          <div style={{ ...xs, color: 'var(--text-muted)' }}>
            {REASON_KO[data.reason] || `구간 증거를 만들 수 없습니다 (${data.reason})`}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={xs}>
                위반 {cnt(data.counts?.from)} → {cnt(data.counts?.to)}건
                {data.counts_reason === 'no_rcr' ? ' (일부 빌드 RCR 없음)' : ''}
              </span>
              {data.file_changed ? (
                <span style={{ ...xs, padding: '1px 7px', borderRadius: 'var(--radius-sm)', fontWeight: 600, color: '#fff', background: 'var(--color-warning)' }}>
                  파일 변경됨 — 위반 유지
                </span>
              ) : (
                <span style={{ ...xs, padding: '1px 7px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                  파일 무변경 — 위반 잔존
                </span>
              )}
            </div>
            {data.diff?.text && (
              <details>
                <summary style={{ ...xs, cursor: 'pointer' }}>
                  구간 변경 diff {data.diff.truncated ? '(발췌 — 절단됨)' : ''}
                </summary>
                <pre style={mono}>{data.diff.text}</pre>
              </details>
            )}
            <div style={{ ...xs, color: 'var(--text-muted)' }}>⚖ {data.note}</div>
          </div>
        )
      )}
    </div>
  );
}

function buildDefinitionMarkdown(data) {
  const d = data.definition || {};
  const lines = [
    `## ${data.rule} — 팀 코딩 룰 초안 (검토 전)`,
    `> ${data.note || ''}`,
    '',
  ];
  if (data.description?.title) lines.push(`**공식 설명**: ${data.description.title}`, '');
  if (d.intent) lines.push('### 의도', d.intent, '');
  if (d.rationale) lines.push('### 근거', d.rationale, '');
  if (d.avoid_pattern) lines.push('### 피해야 할 작성', '```c', d.avoid_pattern, '```', '');
  if (d.comply_pattern) lines.push('### 준수 작성', '```c', d.comply_pattern, '```', '');
  if ((d.exceptions || []).length) {
    lines.push('### 예외 후보 (팀 검토 필요)', ...d.exceptions.map((e) => `- ${e}`), '');
  }
  if (d.evidence_basis) lines.push(`근거 데이터: ${d.evidence_basis}`);
  lines.push(`확신도: ${d.confidence || '—'} · 생성 모델: ${data.model || '—'}`);
  return lines.join('\n');
}

export function RuleDefinitionCard({ jobUrl, cacheRoot, rule }) {
  const [state, setState] = useState('probing'); // probing | idle | loading | done | unavailable | error
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const resp = await post('/api/summary/rule-definition', {
          job_url: jobUrl, cache_root: cacheRoot, rule, probe: true,
        });
        if (cancelled) return;
        if (resp?.available === false) { setData(resp); setState('unavailable'); return; }
        if (resp?.cached) { setData(resp); setState('done'); return; } // 캐시 히트 — LLM 0회
        setData(resp); setState('idle');
      } catch (e) {
        if (!cancelled) { setError(String(e?.message || e)); setState('error'); }
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot, rule]);
  const generate = async (force) => {
    setState('loading');
    setError('');
    try {
      const resp = await post('/api/summary/rule-definition', {
        job_url: jobUrl, cache_root: cacheRoot, rule, ...(force ? { force: true } : {}),
      });
      setData(resp);
      setState(resp?.available === false ? 'unavailable' : 'done');
    } catch (e) {
      setError(String(e?.message || e));
      setState('error');
    }
  };
  const copyMd = async () => {
    try {
      await navigator.clipboard.writeText(buildDefinitionMarkdown(data));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };
  if (state === 'probing') return <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 4 }}>룰 초안 캐시 확인 중…</div>;
  if (state === 'unavailable') {
    return (
      <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 4 }}>
        {data?.reason === 'no_code_evidence'
          ? '팀 룰 초안: 이 규칙의 코드 증거(해소 diff·미해소 발췌)가 없어 초안을 만들지 않습니다 (일반론 방지).'
          : `팀 룰 초안을 만들 수 없습니다 (${data?.reason})`}
      </div>
    );
  }
  const d = data?.definition;
  return (
    <div style={{ borderLeft: '3px solid var(--accent)', padding: '4px 8px', marginTop: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ ...xs, fontWeight: 600 }}>팀 코딩 룰 초안</span>
        {state !== 'done' && (
          <button type="button" onClick={() => generate(false)} disabled={state === 'loading'} style={btn}>
            {state === 'loading' ? '생성 중…' : '팀 룰 초안 생성'}
          </button>
        )}
        {state === 'done' && (
          <>
            <button type="button" onClick={copyMd} style={btn}>{copied ? '복사됨 ✓' : 'Markdown 복사'}</button>
            <button type="button" onClick={() => generate(true)} style={btn}>재생성</button>
          </>
        )}
      </div>
      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>룰 초안 오류: {error}</div>}
      {state === 'idle' && data?.evidence_used && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          증거 준비됨 — 해소 diff {data.evidence_used.fix_diffs}건 · 미해소 발췌 {data.evidence_used.unresolved_excerpts}건
        </div>
      )}
      {state === 'done' && data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
          <div style={{ ...xs, color: 'var(--text-muted)' }}>⚖ {data.note}</div>
          {d ? (
            <>
              {d.intent && <div style={xs}><b>의도</b> — {d.intent}</div>}
              {d.rationale && <div style={xs}><b>근거</b> — {d.rationale}</div>}
              {d.avoid_pattern && (
                <div>
                  <div style={{ ...xs, color: 'var(--color-danger)' }}>피해야 할 작성</div>
                  <pre style={mono}>{d.avoid_pattern}</pre>
                </div>
              )}
              {d.comply_pattern && (
                <div>
                  <div style={{ ...xs, color: 'var(--color-success)' }}>준수 작성</div>
                  <pre style={mono}>{d.comply_pattern}</pre>
                </div>
              )}
              {(d.exceptions || []).length > 0 && (
                <div style={xs}>
                  <b>예외 후보 (팀 검토 필요)</b>
                  <ul style={{ margin: '2px 0 0 16px' }}>
                    {d.exceptions.map((e) => <li key={e}>{e}</li>)}
                  </ul>
                </div>
              )}
              <div style={{ ...xs, color: 'var(--text-muted)' }}>
                {d.evidence_basis ? `근거: ${d.evidence_basis} · ` : ''}확신도 {d.confidence} · {data.model || 'AI 미사용'}{data.cached ? ' · 캐시됨' : ''}
              </div>
            </>
          ) : (
            <div style={{ ...xs, color: 'var(--text-muted)' }}>
              AI 초안 미생성({data.enrich_reason || 'llm_unavailable'}) — 증거(해소 diff·발췌)는 위 카드에서 확인하십시오.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default UnresolvedEvidenceCard;
