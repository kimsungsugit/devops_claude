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
  // 파일 귀속이 원리적으로 없는 항목(RCMA류) — '파일을 못 찾음'과 구분해야 사용자가
  // 스냅샷 누락으로 오독하지 않는다.
  cross_module_scope: '모듈 간 분석(RCMA) 집계입니다 — 특정 파일에 귀속되지 않아 파일 diff가 없습니다',
  // 함수 귀속(HMR) 전용 사유 — RCR(위반)과 별개 산출물이라 없을 수 있다.
  no_hmr: '두 빌드 중 HIS 메트릭 리포트(HMR)가 없는 빌드가 있습니다',
  file_not_in_hmr: 'HIS 메트릭 리포트에 이 파일이 없습니다 (분석 대상 외일 수 있음)',
  file_ambiguous_in_hmr: '같은 이름 파일이 여러 경로에 있어 함수를 특정할 수 없습니다',
  attribution_failed: '함수 단위 메트릭을 읽지 못했습니다',
};

const VERDICT_COLOR = {
  Fail: 'var(--color-danger)',
  Conditional: 'var(--color-warning)',
};

const CHANGE_MARK = { added: '⊕', modified: '±', removed: '⊖' };
const CHANGE_LABEL = { added: '신규', modified: '변경', removed: '삭제' };

/** 메트릭 한 칸 — 'v(G) 3→7'. 신규 함수는 base가 없으므로 값만 표기(0 위장 금지). */
function MetricChip({ m }) {
  return (
    <span style={{ ...xs, color: VERDICT_COLOR[m.verdict] || 'var(--text-muted)' }}>
      {m.label} {m.base == null ? m.cur : `${m.base}→${m.cur}`}
    </span>
  );
}

/**
 * 함수 단위 귀속 — 구간에 바뀐 함수 + HIS 메트릭 변화(HMR 실측).
 *
 * ⚠ 이건 '이 함수가 그 규칙을 위반했다'가 아니다 — RCR은 파일 단위라 규칙의 함수/줄 귀속
 * 정보가 원리적으로 없다. 서버 note를 그대로 노출해 그 경계를 매번 명시한다.
 * 메트릭 값과 밴드 판정(Pass/Conditional/Fail)만 함수 단위 실측이다.
 */
export function FunctionAttribution({ attribution, ruleDeltas }) {
  if (!attribution) return null;
  if (attribution.available === false) {
    return (
      <div style={{ ...xs, color: 'var(--text-muted)' }}>
        함수 단위 귀속: {REASON_KO[attribution.reason] || `조회 불가 (${attribution.reason})`}
      </div>
    );
  }
  const fns = attribution.functions || [];
  const t = attribution.totals || {};
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {(ruleDeltas || []).length > 0 && (
        <div style={xs}>
          이 파일에서 변한 규칙:{' '}
          {ruleDeltas.map((r, i) => (
            <span key={r.rule}>
              {i > 0 && ' · '}
              <b>{r.rule}</b>
              <span style={{ color: r.delta > 0 ? 'var(--color-danger)' : 'var(--color-success)' }}>
                {' '}{r.delta > 0 ? `+${r.delta}` : r.delta}
              </span>
            </span>
          ))}
        </div>
      )}
      <div style={{ ...xs, color: 'var(--text-muted)' }}>
        이 구간에 바뀐 함수 — 신규 {t.added ?? 0} · 변경 {t.modified ?? 0} · 삭제 {t.removed ?? 0}
        {(attribution.omitted || 0) > 0 && ` (표시 상한으로 ${attribution.omitted}개 생략)`}
      </div>
      {/* 한쪽 HMR에만 파일이 있으면 그쪽 함수가 전부 신규/삭제로 보인다 — 사실로 읽히면 안 된다. */}
      {attribution.partial && (
        <div style={{ ...xs, color: 'var(--color-warning)' }}>
          ⚠ {attribution.partial === 'base_missing' ? '이전' : '대상'} 빌드의 HIS 메트릭 리포트에 이 파일이 없어
          {attribution.partial === 'base_missing' ? ' 모든 함수가 신규로' : ' 모든 함수가 삭제로'} 보입니다 —
          파일 신설/삭제인지 그 빌드의 분석 대상에서 빠진 것인지는 구분되지 않습니다.
        </div>
      )}
      {fns.length === 0 ? (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          이 파일의 함수 메트릭에는 변화가 없습니다 — 변경이 메트릭에 잡히지 않는 종류(주석·상수·선언 등)일 수 있습니다.
        </div>
      ) : (
        <ul style={{ margin: '2px 0 0 0', padding: 0, listStyle: 'none' }}>
          {fns.map((f) => (
            <li key={f.function} style={{ marginBottom: 2 }}>
              <div style={{ ...xs, fontFamily: 'monospace', wordBreak: 'break-all' }}>
                <span title={CHANGE_LABEL[f.change]}>{CHANGE_MARK[f.change] || '·'}</span> {f.function}
              </div>
              {(f.metrics || []).length > 0 && (
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', paddingLeft: 14 }}>
                  {f.metrics.map((m) => <MetricChip key={m.metric} m={m} />)}
                </div>
              )}
              {(f.band_crossings || []).map((c) => (
                <div key={c.metric} style={{ ...xs, paddingLeft: 14, color: VERDICT_COLOR[c.to_verdict] || 'var(--text-muted)' }}>
                  ⚠ {c.name} {c.base}→{c.cur} — 판정 {c.from_verdict}({c.from_band}) → <b>{c.to_verdict}({c.to_band})</b>
                </div>
              ))}
            </li>
          ))}
        </ul>
      )}
      {attribution.note && <div style={{ ...xs, color: 'var(--text-muted)' }}>⚖ {attribution.note}</div>}
    </div>
  );
}

/**
 * 구간 변경 파일 — 파일 귀속이 없는 규칙(RCMA류)의 유일한 코드 증거.
 * POST /api/summary/rule-window-changes (결정론, LLM 0회).
 *
 * "이 파일 때문에 위반이 줄었다"가 아니라 "이 구간에 이 파일들이 바뀌었다"만 말한다 —
 * 어느 변경이 원인인지는 QAC 데이터에 없다. 그래서 note를 접힘 여부와 무관하게 노출한다.
 */
export function WindowChangesCard({ jobUrl, cacheRoot, rule, fromBuild, toBuild }) {
  const [state, setState] = useState('idle');
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const load = async () => {
    setState('loading');
    setError('');
    try {
      const resp = await post('/api/summary/rule-window-changes', {
        job_url: jobUrl, cache_root: cacheRoot, rule, from_build: fromBuild, to_build: toBuild,
      });
      setData(resp);
      setState('done');
    } catch (e) {
      setError(String(e?.message || e));
      setState('error');
    }
  };
  const th = { ...xs, textAlign: 'left', padding: '2px 6px', color: 'var(--text-muted)', whiteSpace: 'nowrap' };
  const td2 = { ...xs, padding: '2px 6px', whiteSpace: 'nowrap' };
  return (
    <div style={{ marginTop: 4 }}>
      {state !== 'done' && (
        <button type="button" onClick={load} disabled={state === 'loading'} style={btn}>
          {state === 'loading' ? '조회 중…' : `이 구간 변경 파일 보기 (#${fromBuild}→#${toBuild})`}
        </button>
      )}
      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>구간 변경 파일 조회 오류: {error}</div>}
      {state === 'done' && data && (
        data.available === false ? (
          <div style={{ ...xs, color: 'var(--text-muted)' }}>
            {data.reason === 'identical_snapshot'
              ? '두 빌드의 소스 스냅샷이 동일합니다 — 이 구간에 변경된 파일이 없습니다.'
              : REASON_KO[data.reason] || `구간 변경 파일을 조회할 수 없습니다 (${data.reason})`}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <div style={{ ...xs, color: 'var(--text-muted)' }}>⚖ {data.note}</div>
            <div style={xs}>
              변경 {data.totals?.changed}개 · 헤더 {data.totals?.headers} · 선언 변경 {data.totals?.decl_touched_files} · typedef {data.totals?.typedef_touched_files}
              {(data.omitted || 0) > 0 && ` (표시 상한으로 ${data.omitted}개 생략)`}
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                <thead><tr><th style={th}>파일</th><th style={th}>+/−</th><th style={th}>선언 변경</th><th style={th}>typedef</th></tr></thead>
                <tbody>
                  {(data.changed_files || []).map((f) => (
                    <tr key={f.path}>
                      <td style={{ ...td2, fontFamily: 'monospace' }}>
                        {f.path}
                        {f.is_header && <span style={{ color: 'var(--text-muted)' }} title="헤더 파일">{' [h]'}</span>}
                      </td>
                      <td style={td2}>
                        <span style={{ color: 'var(--color-success)' }}>+{f.lines_added ?? '—'}</span>
                        {' / '}
                        <span style={{ color: 'var(--color-danger)' }}>−{f.lines_removed ?? '—'}</span>
                      </td>
                      <td style={td2}>{f.decl_touched || '—'}</td>
                      <td style={td2}>{f.typedef_touched || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )
      )}
    </div>
  );
}

/** 파일 귀속 불가(RCMA류) 엔트리 배지 — 목록에서 파일 행과 즉시 구분되게 한다. */
export function CrossModuleBadge() {
  return (
    <span style={{
      ...xs, padding: '1px 7px', borderRadius: 'var(--radius-sm)',
      border: '1px dashed var(--border)', color: 'var(--text-muted)',
    }}>모듈 간 분석</span>
  );
}

const xs = { fontSize: 'var(--text-xs)' };
const btn = {
  ...xs, padding: '1px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
  background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)',
};
const mono = {
  whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 'var(--text-xs)',
  background: 'var(--bg-subtle)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius-sm)', padding: '4px 8px', margin: '2px 0', overflowX: 'auto',
};

function cnt(v) {
  return v == null ? '—' : v;
}

/**
 * 구간 증거 카드 — (rule, file)의 from→to 스냅샷 diff + 구간 카운트.
 *
 * 미해소(files_latest)뿐 아니라 **발생 구간**(increased_files) 증거에도 쓰이므로 라벨을
 * props로 받는다. 기본값은 미해소 문구 — 기존 호출부/테스트 계약 유지.
 * cross_module 엔트리는 파일 실체가 없어 diff가 원리적으로 없다(버튼 라벨만 카운트 조회로).
 */
export function UnresolvedEvidenceCard({
  jobUrl, cacheRoot, rule, file, fromBuild, toBuild,
  countSuffix = '(최신)', changedLabel = '파일 변경됨 — 위반 유지',
  unchangedLabel = '파일 무변경 — 위반 잔존', accent = 'var(--color-warning)',
}) {
  const [state, setState] = useState('idle'); // idle | loading | done | error
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const crossModule = file?.scope === 'cross_module';
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
    <div style={{ borderLeft: `3px solid ${accent}`, padding: '4px 8px', marginTop: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={xs}>{file.path} <b>{file.count}</b>건 {countSuffix}</span>
        {crossModule && <CrossModuleBadge />}
        {state !== 'done' && (
          <button type="button" onClick={load} disabled={state === 'loading'} style={btn}>
            {state === 'loading' ? '조회 중…'
              : crossModule ? `구간 카운트 보기 (#${fromBuild}→#${toBuild})`
              : `구간 증거 보기 (#${fromBuild}→#${toBuild})`}
          </button>
        )}
      </div>
      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>구간 증거 조회 오류: {error}</div>}
      {state === 'done' && data && (
        data.available === false ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <div style={{ ...xs, color: 'var(--text-muted)' }}>
              {REASON_KO[data.reason] || `구간 증거를 만들 수 없습니다 (${data.reason})`}
            </div>
            {/* diff가 없어도 구간 카운트는 실재하는 관측 — 버리지 않는다. */}
            {data.counts && (data.counts.from != null || data.counts.to != null) && (
              <span style={xs}>
                위반 {cnt(data.counts.from)} → {cnt(data.counts.to)}건
                {data.counts_reason === 'no_rcr' ? ' (일부 빌드 RCR 없음)' : ''}
              </span>
            )}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              <span style={xs}>
                위반 {cnt(data.counts?.from)} → {cnt(data.counts?.to)}건
                {data.counts_reason === 'no_rcr' ? ' (일부 빌드 RCR 없음)' : ''}
              </span>
              {data.file_changed ? (
                <span style={{ ...xs, padding: '1px 7px', borderRadius: 'var(--radius-sm)', fontWeight: 600, color: '#fff', background: accent }}>
                  {changedLabel}
                </span>
              ) : (
                <span style={{ ...xs, padding: '1px 7px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                  {unchangedLabel}
                </span>
              )}
            </div>
            {/* 함수 단위 귀속을 diff보다 먼저 — diff는 원문이고 이건 '어디를 볼지'다. */}
            <FunctionAttribution attribution={data.attribution} ruleDeltas={data.file_rule_deltas} />
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
          : data?.reason === 'cross_module_only'
          ? '팀 룰 초안: 이 규칙의 위반은 모듈 간 분석(RCMA) 집계에만 있어 파일 단위 코드 증거를 만들 수 없습니다 (일반론 방지).'
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
