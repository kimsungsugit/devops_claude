/**
 * RuleEvidenceCards — 미해소 규칙의 구간 증거 카드(J2).
 * POST /api/summary/rule-unresolved-evidence(결정론, LLM 0회) 소비 — 라인 레벨 위반 데이터가
 * 없으므로(RCR=파일×규칙 카운트가 최상세) 코드 수준 근거는 빌드 스냅샷 diff가 유일 경로다.
 *
 * ISO 정직성: '파일 무변경'은 실패가 아니라 유효 증거(위반 잔존 + 구간 내 미수정) — muted 배지.
 * note(관측≠인과)는 서버 고정 주입 값을 상시 노출. counts 결측(no_rcr)은 '—'로 표기(0 위장 금지).
 */
import { useState } from 'react';
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

export default UnresolvedEvidenceCard;
