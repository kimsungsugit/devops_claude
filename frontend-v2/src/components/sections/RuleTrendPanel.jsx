/**
 * RuleTrendPanel — PRQA 룰 다빌드 트렌드(분류 배지 + 스파크라인) + fix 근거 작성 예시.
 * POST /api/jenkins/prqa-rule-trend(on-mount, RCR 디스크캐시 재사용) 소비.
 * decreasing/resolved 규칙 행 확장 → 감소 파일별 "작성 예시 생성"(on-demand Gemini —
 * POST /api/summary/rule-fix-example). correlation_note(상관≠인과)는 상시 노출.
 *
 * ISO 정직성: 미분석 빌드 자리는 null → 스파크라인 분절('0' 위장 금지), insufficient_data면
 * 분류 배지 없음, 미지 reason도 원문 노출(침묵 금지).
 */
import { Fragment, useEffect, useMemo, useState } from 'react';
import { post } from '../../api.js';
import { TrendLine } from '../charts.jsx';
import SummaryPanel from './SummaryPanel.jsx';
import * as T from './summaryTable.js';
import {
  CrossModuleBadge,
  RuleDefinitionCard,
  UnresolvedEvidenceCard,
  WindowChangesCard,
} from './RuleEvidenceCards.jsx';

// 미해소 분류 — 구간 증거(변경에도 위반 유지 vs 무변경 잔존) 확장 대상(J2).
const UNRESOLVED_CLASSES = new Set(['increasing', 'persistent', 'new_recent']);
// 증가/발생 구간 증거를 보여줄 분류 — '언제 늘었나'가 조치 판단의 핵심인 쪽.
const ONSET_CLASSES = new Set(['increasing', 'new_recent']);

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
  cross_module_scope: '모듈 간 분석(RCMA) 집계입니다 — 특정 파일에 귀속되지 않아 파일 diff가 없습니다',
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
    background: 'var(--bg-subtle)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)', padding: '4px 8px', margin: '2px 0', overflowX: 'auto',
  };
  const crossModule = file?.scope === 'cross_module';
  return (
    <div style={{ borderLeft: '3px solid var(--color-info)', padding: '4px 8px', marginTop: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={xs}>{file.path} <b>{file.delta}</b> (#{file.from_build}→#{file.to_build})</span>
        {crossModule && <CrossModuleBadge />}
        {/* 파일 실체가 없으면 LLM 호출 자체가 무의미 — 버튼을 숨기고 사유만 노출한다.
            단 "그럼 볼 수 있는 게 없나"에는 답이 있다: 그 구간에 바뀐 파일은 실재한다. */}
        {crossModule && (
          <span style={{ ...xs, color: 'var(--text-muted)' }}>{FIX_REASON_KO.cross_module_scope}</span>
        )}
        {!crossModule && state !== 'done' && (
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

export default function RuleTrendPanel({ jobUrl, cacheRoot, defaultOpen = true }) {
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

  // 규칙셋 변동(#N에서 규칙 수가 바뀜) — '신규 발생'이 코드 악화가 아니라 검사 범위 확대일 수
  // 있음을 각주로 알린다. 값이 하나뿐이면 null(불필요한 문구 억제).
  const rulesetChange = useMemo(() => {
    const sizes = (data?.ruleset_sizes || []).filter((n) => n != null);
    if (sizes.length < 2) return null;
    const min = Math.min(...sizes);
    const max = Math.max(...sizes);
    return min === max ? null : { min, max };
  }, [data]);

  // 표 서식은 summaryTable 공통 규약 — 본문 11px · 숫자 우측정렬(tabular-nums) ·
  // 식별자는 줄바꿈 대신 말줄임. 패널마다 따로 정의하면 한 탭 안에서 표가 서로 달라 보인다.
  const { th, td } = T;

  return (
    <SummaryPanel
      title="룰 트렌드 (빌드별 위반 변화)"
      defaultOpen={defaultOpen}
      meta={<>
        {data?.available && (
          <span style={{ ...xs, color: 'var(--text-muted)' }}>
            {(data.builds || []).filter((b) => b.analyzed).length}개 빌드 관측
            {data.insufficient_data ? ' · 관측 부족(분류 없음)' : ''}
          </span>
        )}
        {!data && !error && <span className="spinner" />}
      </>}
      /* ⚠ 접으면 본문의 오류·불가 안내가 화면에서 사라진다 — 헤더에 신호를 남긴다(없으면 null) */
      problem={error ? <span style={{ ...xs, color: 'var(--color-danger)' }}>⚠ 조회 실패 — {error}</span>
        : data?.available === false ? <span style={{ ...xs, color: 'var(--color-warning)' }}>관측 없음</span>
        : null}
    >
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
                  const decFiles = r.decreased_files || [];
                  const incFiles = r.increased_files || [];
                  const range = data.observed_range;
                  // 감소 근거는 분류와 무관하게 노출한다 — 총량이 늘어난 규칙 안에도 줄어든
                  // 파일이 있고, 그것이 "위반하지 않는 작성" 예시의 유일한 실코드 근거다.
                  const hasFix = decFiles.length > 0;
                  const hasOnset = ONSET_CLASSES.has(r.classification) && incFiles.length > 0;
                  // 규칙이 구간 도중 적용됐으면 그 빌드가 비교 기준. from==to면 diff가 성립하지 않는다.
                  const unresolvedFrom = r.applied_from_build ?? range?.from_build;
                  const hasUnresolved = UNRESOLVED_CLASSES.has(r.classification)
                    && (r.files_latest || []).length > 0
                    && !!range && unresolvedFrom != null && unresolvedFrom !== range.to_build;
                  const expandable = hasFix || hasOnset || hasUnresolved;
                  const expanded = expandedRule === r.rule;
                  return (
                    <Fragment key={r.rule}>
                      <tr>
                        <td style={td} title={r.description?.title ? `${r.rule} — ${r.description.title}` : r.rule}>
                          {r.rule}
                          {r.description?.title && (
                            <div style={{ ...xs, color: 'var(--text-muted)', fontWeight: 400, maxWidth: 240, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                              {r.description.title}
                            </div>
                          )}
                          {/* 규칙셋 확장으로 도중 적용된 규칙 — '신규 발생'(코드 악화)과 구분해야 한다. */}
                          {r.scope_narrowed && r.applied_from_build != null && (
                            <div style={{ ...xs, color: 'var(--text-muted)', fontWeight: 400 }}
                              title="이전 빌드에는 이 규칙이 규칙셋에 없어(또는 비활성) 검사되지 않았습니다 — 그 구간은 '위반 0'이 아니라 미측정입니다">
                              #{r.applied_from_build}부터 규칙 적용
                            </div>
                          )}
                        </td>
                        <td style={td}>
                          <ClassBadge cls={r.classification} />
                          {r.classification_reason === 'insufficient_observations' && (
                            <div style={{ ...xs, color: 'var(--text-muted)' }} title="이 규칙이 적용된 빌드가 1개뿐 — 단일 관측으로 추세를 단정하지 않습니다">
                              관측 1개
                            </div>
                          )}
                        </td>
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
                              {(expanded ? '▾ ' : '▸ ') + (hasFix ? '예시' : hasOnset ? '발생' : '증거')}
                            </button>
                          )}
                        </td>
                      </tr>
                      {expanded && (
                        <tr>
                          <td colSpan={6} style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>
                            {hasFix && (
                              <>
                                <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 2 }}>
                                  위반이 줄어든 파일
                                  {/* 규칙 총계 delta가 아니라 아래 목록의 합(file_delta) — 같은 구간에
                                      늘어난 파일이 섞이면 총계와 달라 목록과 어긋나 보인다. */}
                                  {r.decrease_window ? ` — 감소 구간 #${r.decrease_window.from_build}→#${r.decrease_window.to_build} (파일 합 ${r.decrease_window.file_delta ?? r.decrease_window.delta}건)` : ''}
                                  . 실제 변경을 근거로 "위반하지 않는 작성 예시"를 생성합니다.
                                </div>
                                {decFiles.map((f) => (
                                  <FixExampleCard key={f.path} jobUrl={jobUrl} cacheRoot={cacheRoot} rule={r.rule} file={f} />
                                ))}
                                {/* 감소분이 전부 파일 귀속 불가면 파일 diff가 하나도 안 나온다 —
                                    그 구간에 바뀐 파일 목록이 유일하게 남는 코드 증거다. */}
                                {r.decrease_window && decFiles.every((f) => f.scope === 'cross_module') && (
                                  <WindowChangesCard jobUrl={jobUrl} cacheRoot={cacheRoot} rule={r.rule}
                                    fromBuild={r.decrease_window.from_build} toBuild={r.decrease_window.to_build} />
                                )}
                              </>
                            )}
                            {hasOnset && (
                              <>
                                <div style={{ ...xs, color: 'var(--text-muted)', margin: hasFix ? '6px 0 2px' : '0 0 2px' }}>
                                  위반이 늘어난 파일
                                  {r.increase_window ? ` — ${r.classification === 'new_recent' ? '발생' : '증가'} 구간 #${r.increase_window.from_build}→#${r.increase_window.to_build} (파일 합 +${r.increase_window.file_delta ?? r.increase_window.delta}건)` : ''}
                                  . 그 구간의 실제 스냅샷 변경을 확인합니다.
                                </div>
                                {incFiles.map((f) => (
                                  <UnresolvedEvidenceCard key={f.path} jobUrl={jobUrl} cacheRoot={cacheRoot}
                                    rule={r.rule} file={{ ...f, count: f.count_to }}
                                    fromBuild={f.from_build} toBuild={f.to_build}
                                    countSuffix={`(+${f.delta})`} accent="var(--color-danger)"
                                    changedLabel="파일 변경됨 — 위반 증가"
                                    unchangedLabel="파일 무변경 — 위반 증가(설정·타 파일 영향 가능)" />
                                ))}
                              </>
                            )}
                            {hasUnresolved && (
                              <>
                                <div style={{ ...xs, color: 'var(--text-muted)', margin: (hasFix || hasOnset) ? '6px 0 2px' : '0 0 2px' }}>
                                  미해소 위반 파일 — 관측 구간(#{unresolvedFrom}→#{range.to_build})의 실제 스냅샷으로
                                  "변경에도 위반 유지"인지 "파일 무변경(위반 잔존)"인지 확인합니다.
                                </div>
                                {/* 규칙이 구간 도중 적용됐으면 그 빌드가 from — 검사조차 없던 빌드를
                                    비교 기준으로 삼으면 '그때부터 위반'이라는 잘못된 인상을 준다. */}
                                {(r.files_latest || []).map((f) => (
                                  <UnresolvedEvidenceCard key={f.path} jobUrl={jobUrl} cacheRoot={cacheRoot}
                                    rule={r.rule} file={f}
                                    fromBuild={unresolvedFrom} toBuild={range.to_build} />
                                ))}
                                {/* 미해소분이 전부 파일 귀속 불가여도 구간 변경 파일은 볼 수 있다. */}
                                {(r.files_latest || []).every((f) => f.scope === 'cross_module') && (
                                  <WindowChangesCard jobUrl={jobUrl} cacheRoot={cacheRoot} rule={r.rule}
                                    fromBuild={unresolvedFrom} toBuild={range.to_build} />
                                )}
                              </>
                            )}
                            <RuleDefinitionCard jobUrl={jobUrl} cacheRoot={cacheRoot} rule={r.rule} />
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
            * {data.scope_note} · 미분석 빌드와 규칙 미적용 구간은 선이 끊겨 표시됩니다(0 아님)
            {rulesetChange && ` · 관측 구간에서 규칙셋이 ${rulesetChange.min}→${rulesetChange.max}개로 변동 — 도중 추가된 규칙은 '#N부터 규칙 적용'으로 표기`}
          </div>
        </>
      )}
    </SummaryPanel>
  );
}
