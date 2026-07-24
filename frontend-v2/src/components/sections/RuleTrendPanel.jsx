/**
 * RuleTrendPanel — PRQA 룰 다빌드 트렌드(분류 배지 + 스파크라인) + fix 근거 작성 예시.
 * POST /api/jenkins/prqa-rule-trend(on-mount, RCR 디스크캐시 재사용) 소비.
 * decreasing/resolved 규칙 행 확장 → 감소 파일별 "작성 예시 생성"(on-demand Gemini —
 * POST /api/summary/rule-fix-example). correlation_note(상관≠인과)는 상시 노출.
 *
 * ISO 정직성: 미분석 빌드 자리는 null → 스파크라인 분절('0' 위장 금지), insufficient_data면
 * 분류 배지 없음, 미지 reason도 원문 노출(침묵 금지).
 */
import { Fragment, useEffect, useState } from 'react';
import { post } from '../../api.js';
import { TrendLine } from '../charts.jsx';

const CLASS_META = {
  increasing: { label: '증가', color: 'var(--color-danger)' },
  new_recent: { label: '신규 발생', color: 'var(--color-danger)' },
  persistent: { label: '지속 발생', color: 'var(--color-warning)' },
  decreasing: { label: '감소', color: 'var(--color-info)' },
  resolved: { label: '해소', color: 'var(--color-success)' },
};
const FIX_REASON_KO = {
  file_unchanged_between_builds: '이 구간에서 파일 내용이 변하지 않았습니다 — 위반 감소가 이 파일 수정 때문이 아닐 수 있습니다',
  file_not_in_snapshot: '소스 스냅샷에서 파일을 찾지 못했습니다',
  file_ambiguous_in_snapshot: '동일 이름 파일이 여러 개라 특정할 수 없습니다',
  snapshot_missing: '해당 빌드에 소스 스냅샷이 없습니다',
  build_not_cached: '해당 빌드가 캐시에 없습니다',
};

const xs = { fontSize: 'var(--text-xs)' };

function ClassBadge({ cls }) {
  const meta = CLASS_META[cls];
  if (!meta) return <span style={{ ...xs, color: 'var(--text-muted)' }}>—</span>;
  return (
    <span style={{
      display: 'inline-block', padding: '1px 7px', borderRadius: 'var(--radius-sm)',
      fontSize: 'var(--text-xs)', fontWeight: 600, color: '#fff', background: meta.color,
    }}>{meta.label}</span>
  );
}

function FixExampleCard({ jobUrl, cacheRoot, rule, file }) {
  const [state, setState] = useState('idle'); // idle | loading | done | error
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const generate = async (force) => {
    setState('loading');
    setError('');
    try {
      const resp = await post('/api/summary/rule-fix-example', {
        job_url: jobUrl, cache_root: cacheRoot, rule,
        file: file.path, from_build: file.from_build, to_build: file.to_build,
        ...(force ? { force: true } : {}),
      });
      setData(resp);
      setState('done');
    } catch (e) {
      setError(String(e?.message || e));
      setState('error');
    }
  };
  const mono = {
    whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 'var(--text-xs)',
    background: 'var(--bg-elevated, var(--hover))', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)', padding: '4px 8px', margin: '2px 0', overflowX: 'auto',
  };
  return (
    <div style={{ borderLeft: '3px solid var(--color-info)', padding: '4px 8px', marginTop: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={xs}>{file.path} <b>{file.delta}</b> (#{file.from_build}→#{file.to_build})</span>
        {state !== 'done' && (
          <button type="button" onClick={() => generate(false)} disabled={state === 'loading'}
            style={{ ...xs, padding: '1px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}>
            {state === 'loading' ? '생성 중…' : '작성 예시 생성'}
          </button>
        )}
        {state === 'done' && data?.available !== false && (
          <button type="button" onClick={() => generate(true)}
            style={{ ...xs, padding: '1px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}>
            재생성
          </button>
        )}
      </div>
      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>예시 생성 오류: {error}</div>}
      {state === 'done' && data && (
        data.available === false ? (
          <div style={{ ...xs, color: 'var(--text-muted)' }}>{FIX_REASON_KO[data.reason] || `예시를 만들 수 없습니다 (${data.reason})`}</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
            <div style={{ ...xs, color: 'var(--text-muted)' }}>⚖ {data.correlation_note}</div>
            {data.evidence?.text && (
              <details>
                <summary style={{ ...xs, cursor: 'pointer' }}>실제 변경 diff 증거 {data.evidence.truncated ? '(발췌 — 절단됨)' : ''}</summary>
                <pre style={mono}>{data.evidence.text}</pre>
              </details>
            )}
            {data.example ? (
              <>
                {data.example.explanation && <div style={xs}>{data.example.explanation}</div>}
                {data.example.avoid_pattern && (
                  <div>
                    <div style={{ ...xs, color: 'var(--color-danger)' }}>피해야 할 작성</div>
                    <pre style={mono}>{data.example.avoid_pattern}</pre>
                  </div>
                )}
                {data.example.compliant_pattern && (
                  <div>
                    <div style={{ ...xs, color: 'var(--color-success)' }}>위반하지 않는 작성</div>
                    <pre style={mono}>{data.example.compliant_pattern}</pre>
                  </div>
                )}
                <div style={{ ...xs, color: 'var(--text-muted)' }}>확신도 {data.example.confidence} · {data.model || 'AI 미사용'}{data.cached ? ' · 캐시됨' : ''}</div>
              </>
            ) : (
              <div style={{ ...xs, color: 'var(--text-muted)' }}>
                AI 예시 미생성({data.enrich_reason || 'llm_unavailable'}) — 위 diff가 실제 변경 증거입니다.
              </div>
            )}
          </div>
        )
      )}
    </div>
  );
}

export default function RuleTrendPanel({ jobUrl, cacheRoot }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [expandedRule, setExpandedRule] = useState(null);
  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const resp = await post('/api/jenkins/prqa-rule-trend', { job_url: jobUrl, cache_root: cacheRoot, limit: 15 });
        if (!cancelled) { setData(resp); setError(''); }
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot]);

  const th = { ...xs, textAlign: 'left', padding: '4px 8px', color: 'var(--text-muted)', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
  const td = { ...xs, padding: '4px 8px', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };

  return (
    <div className="panel" style={{ padding: 'var(--sp-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>룰 트렌드 (빌드별 위반 변화)</div>
        {data?.available && (
          <span style={{ ...xs, color: 'var(--text-muted)' }}>
            {(data.builds || []).filter((b) => b.analyzed).length}개 빌드 관측
            {data.insufficient_data ? ' · 관측 부족(분류 없음)' : ''}
          </span>
        )}
        {!data && !error && <span className="spinner" />}
      </div>

      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>룰 트렌드 조회 오류: {error}</div>}
      {data && data.available === false && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          {data.reason === 'no_cached_build' ? '캐시된 빌드가 없습니다.'
            : data.reason === 'no_rcr_in_cached_builds' ? '캐시된 빌드에 PRQA(RCR) 리포트가 없습니다.'
            : `룰 트렌드를 계산할 수 없습니다 (${data.reason})`}
        </div>
      )}

      {data?.available && (
        <>
          {data.summary && !data.insufficient_data && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 'var(--sp-2)' }}>
              {Object.keys(CLASS_META).map((cls) => (
                (data.summary[cls] || 0) > 0 && (
                  <span key={cls} style={{ ...xs }}>
                    <ClassBadge cls={cls} /> {data.summary[cls]}
                  </span>
                )
              ))}
            </div>
          )}
          <div style={{ overflowX: 'auto' }}>
            <table style={{ borderCollapse: 'collapse', width: '100%' }}>
              <thead>
                <tr>
                  <th style={th}>규칙</th><th style={th}>분류</th><th style={th}>추이 (#{(data.builds || [])[0]?.build_number} → #{(data.builds || [])[(data.builds || []).length - 1]?.build_number})</th>
                  <th style={th}>최신</th><th style={th}>순변화</th><th style={th}>상세</th>
                </tr>
              </thead>
              <tbody>
                {(data.rules || []).map((r) => {
                  const expandable = (r.decreased_files || []).length > 0;
                  const expanded = expandedRule === r.rule;
                  return (
                    <Fragment key={r.rule}>
                      <tr>
                        <td style={td} title={r.rule}>{r.rule}</td>
                        <td style={td}><ClassBadge cls={r.classification} /></td>
                        <td style={{ ...td, minWidth: 140 }}>
                          <TrendLine width={140} height={26}
                            color={CLASS_META[r.classification]?.color || 'var(--accent)'}
                            points={(r.counts || []).map((v, i) => ({ label: `#${(data.builds || [])[i]?.build_number}`, value: v }))}
                            ariaLabel={`${r.rule} 빌드별 위반 추이`} />
                        </td>
                        <td style={td}>{r.latest ?? '—'}</td>
                        <td style={{ ...td, fontWeight: 600, color: (r.net || 0) > 0 ? 'var(--color-danger)' : (r.net || 0) < 0 ? 'var(--color-success)' : 'var(--text-muted)' }}>
                          {r.net == null ? '—' : r.net > 0 ? `+${r.net}` : r.net}
                        </td>
                        <td style={td}>
                          {expandable && (
                            <button type="button" onClick={() => setExpandedRule(expanded ? null : r.rule)}
                              aria-expanded={expanded}
                              style={{ ...xs, padding: '1px 7px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}>
                              {expanded ? '▾ 예시' : '▸ 예시'}
                            </button>
                          )}
                        </td>
                      </tr>
                      {expanded && (
                        <tr>
                          <td colSpan={6} style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>
                            <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 2 }}>
                              위반이 줄어든 파일 — 실제 변경을 근거로 "위반하지 않는 작성 예시"를 생성합니다.
                            </div>
                            {(r.decreased_files || []).map((f) => (
                              <FixExampleCard key={f.path} jobUrl={jobUrl} cacheRoot={cacheRoot} rule={r.rule} file={f} />
                            ))}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
            {(data.rules_omitted || 0) > 0 && (
              <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 4 }}>표시 상한으로 {data.rules_omitted}개 규칙 생략</div>
            )}
          </div>
          <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 'var(--sp-1)' }}>
            * {data.scope_note} · 미분석 빌드 자리는 선이 끊겨 표시됩니다(0 아님)
          </div>
        </>
      )}
    </div>
  );
}
