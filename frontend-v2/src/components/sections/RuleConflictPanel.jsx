/**
 * RuleConflictPanel — "이 룰을 고치면 저 룰에 걸린다" + 판단이 필요한 애매한 지점.
 *
 * 데이터는 부모(`SummarySourceTab`)가 `POST /api/summary/rule-conflicts` 로 **한 번만**
 * 받아 내려준다 — 이 패널과 룰 트렌드 표가 같은 값을 써야 하고, 각자 부르면 같은 탭에서
 * `compute_rule_trend` 가 여러 번 도는 낭비가 생긴다. 지침 생성(LLM)만 카드가 직접 호출한다.
 *
 * ISO 정직성:
 * - 증거 등급(tier)을 배지로 **항상** 노출한다. '구간 실측'과 '규칙이 활성이라 가능성 있음'을
 *   같은 무게로 보여주면 지식 테이블이 측정처럼 위장된다.
 * - 상대 규칙이 규칙셋에 없어 걸러진 항목은 감추지 않고 '제외됨'으로 남긴다.
 * - 규칙 설정(RCFInfo)이 없는 빌드는 '활성 미확인'을 헤더 meta 에 상시 표기 — 증거 부재를
 *   위험 없음으로 읽히게 하지 않는다.
 * - 서버 고정 note(상충은 가능성이지 인과가 아님)와 지식 테이블 출처를 접힘과 무관하게 노출.
 */
import { Fragment, useEffect, useRef, useState } from 'react';
import { post } from '../../api.js';
import SummaryPanel from './SummaryPanel.jsx';
import * as T from './summaryTable.js';

const xs = { fontSize: 'var(--text-xs)' };

/**
 * 증거 등급 — 강할수록 진한 색. 순서는 백엔드 TIER_ORDER 와 lockstep.
 * ⚠ 상수는 export 하지 않는다(react-refresh 는 컴포넌트만 내보내는 파일에서 동작한다) —
 *   다른 패널은 아래 `TierBadge` 컴포넌트를 가져다 쓸 것.
 */
const TIER_META = {
  window: { label: '구간 실측', color: 'var(--color-danger)' },
  cooccurrence: { label: '동시 위반', color: 'var(--color-warning)' },
  metric_headroom: { label: '메트릭 여유 없음', color: 'var(--color-info)' },
  ruleset_active: { label: '규칙 활성', color: 'var(--text-muted)' },
  ruleset_unknown: { label: '활성 미확인', color: 'var(--text-muted)' },
};

const KIND_LABEL = {
  fix_induces: '고치면 유발',
  mutually_exclusive: '동시 만족 불가',
  process_tension: '프로세스 긴장',
};

/** MISRA 등급 — 예외(deviation) 여지를 한 눈에. */
const CATEGORY_LABEL = {
  mandatory: '필수(예외 불가)',
  required: '요구(예외 승인 필요)',
  advisory: '권고',
};

const MEASURE_LABEL = {
  ruleset_change: '규칙셋 변동',
  unattributed: '파일 미귀속 위반',
  ruleset_unknown: '규칙 설정 없음',
  single_observation: '관측 1개',
  residual: '규칙 미분해 잔여',
  file_unattributed: '리포트 총계 불일치',
};

const ADVICE_REASON_KO = {
  no_code_evidence: '이 상충의 코드 증거(동시 위반 파일·구간 diff)를 찾지 못해 지침을 만들지 않았습니다 — 일반론 지침은 만들지 않습니다',
  cross_module_only: '이 규칙의 위반이 전부 모듈 간 분석(RCMA) 집계라 특정 파일에 귀속되지 않습니다 — 스냅샷 발췌가 원리적으로 불가능합니다(스냅샷 누락이 아닙니다)',
  // ⚠ 위 두 사유와 **조치가 정반대**다. 여기서는 위반도 파일도 멀쩡히 있는데 소스만 없다 —
  //    빌드를 다시 받으면 해결된다. 예전엔 이 경우도 no_code_evidence 로 나가 "도구 한계"로 읽혔다.
  no_source_snapshot: '이 빌드에 소스 스냅샷(source/)이 없어 코드 발췌를 만들 수 없습니다 — 증거가 없는 게 아니라 소스를 아직 안 받은 것입니다(빌드 재수집으로 해결됩니다)',
  latest_build_not_cached: '기준 빌드가 캐시에 없어 소스를 읽을 수 없습니다',
  conflict_not_found: '이 상충이 현재 후보 목록에 없습니다 (빌드가 바뀌었을 수 있습니다)',
  params_required: '필수 파라미터가 없습니다',
  mandatory_deviation_suggested: '생성된 지침이 예외 불가(mandatory) 규칙을 예외 후보로 지목해 폐기했습니다',
  hallucinated_identifiers: '생성된 코드가 실제 증거에 없는 식별자를 써서 폐기했습니다',
};

/** 메트릭 축을 못 본 사유 — 빈 목록을 '여유 있음'으로 읽히게 하지 않는다. */
const METRIC_AXIS_REASON_KO = {
  no_hmr: '이 빌드에 HIS 메트릭 리포트(HMR)가 없습니다',
  hmr_empty: 'HIS 메트릭 리포트에서 함수를 읽지 못했습니다',
  latest_build_not_cached: '기준 빌드가 캐시에 없습니다',
  no_attributed_file: '이 규칙의 위반이 특정 파일에 귀속되지 않아 함수를 특정할 수 없습니다',
};

const mono = {
  whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 'var(--text-xs)',
  background: 'var(--bg-subtle)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius-sm)', padding: '4px 8px', margin: '2px 0', overflowX: 'auto',
};

const btn = {
  ...xs, padding: '1px 8px', border: '1px solid var(--border)',
  borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer',
  color: 'var(--text-muted)',
};

export function TierBadge({ tier }) {
  const meta = TIER_META[tier];
  if (!meta) return <span style={{ ...xs, color: 'var(--text-muted)' }}>—</span>;
  return (
    <span style={{
      display: 'inline-block', padding: '1px 7px', borderRadius: 'var(--radius-sm)',
      fontSize: 'var(--text-xs)', fontWeight: 600, color: '#fff', background: meta.color,
    }}>{meta.label}</span>
  );
}

/**
 * 이 상충의 위반 중 **손댈 수 없는 자동 생성 파일 몫**.
 *
 * 왜 표 본문인가 — 실측 HDPDM01 `Rule-5.4` 는 파일 귀속 256건이 **256건 모두** 자동 생성
 * 파일(lin_cfg.h)인데, 정렬이 위반 수 내림차순이라 "고쳐라" 목록 맨 위에 있었다.
 * ⚠ 마커 확인이 불가능했던 상태(스냅샷 없음)의 0은 '없음'이 아니라 '못 봄'이다.
 */
function GeneratedShare({ generated }) {
  const g = generated || {};
  const total = g.attributed_total || 0;
  const n = g.violations || 0;
  const probeBlind = g.probe && g.probe.available === false;
  if (n === 0) {
    return (
      <span style={{ ...xs, color: 'var(--text-muted)' }}
        title={probeBlind ? '소스 스냅샷이 없어 파일 내 생성 마커를 확인하지 못했습니다 — 경로 규칙으로 판별된 것만 반영됐습니다' : undefined}>
        {probeBlind ? '— (마커 미확인)' : '—'}
      </span>
    );
  }
  const pct = total > 0 ? Math.round((n / total) * 100) : 0;
  const heavy = pct >= 50;
  return (
    <span style={{ ...xs, color: heavy ? 'var(--color-warning)' : 'var(--text-muted)', fontWeight: heavy ? 600 : 400 }}
      title={`파일에 귀속된 위반 ${total}건 중 ${n}건이 자동 생성 파일 — 직접 수정하면 재생성 시 되돌아옵니다`}>
      {n}/{total} ({pct}%)
    </span>
  );
}

/** 규칙 하나 — ID + 위반 수 + 등급. 공식 제목은 title 속성으로(행 높이 균일). */
function RuleChip({ meta }) {
  const cat = CATEGORY_LABEL[meta.category];
  return (
    <span title={[meta.rule, meta.title, cat && `등급: ${cat}`].filter(Boolean).join(' — ')}>
      <b>{meta.rule}</b>
      {meta.count > 0 && <span style={{ color: 'var(--text-muted)' }}> {meta.count}</span>}
      {meta.category === 'mandatory' && (
        <span style={{ color: 'var(--color-danger)' }} title="예외(deviation) 신청 불가">*</span>
      )}
    </span>
  );
}

/**
 * 해결 지침 카드 — `POST /api/summary/rule-conflict-advice`(LLM on-demand).
 * mount 시 probe만 한다(LLM 0회) — 캐시가 있으면 바로 보여주고, 없으면 생성 버튼.
 */
function ConflictAdviceCard({ jobUrl, cacheRoot, conflict }) {
  // 서버가 이미 '증거가 없어 지침을 못 만든다'를 판정해 두었다 — 그러면 probe 요청조차
  // 보내지 않는다(누르고 나서야 알게 하는 대신 미리 사유를 보여준다).
  const blocked = conflict.advice?.available === false ? conflict.advice : null;
  const [state, setState] = useState(blocked ? 'blocked' : 'probing');
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  const call = async (body, next) => {
    try {
      const resp = await post('/api/summary/rule-conflict-advice', {
        job_url: jobUrl, cache_root: cacheRoot, conflict_id: conflict.id, ...body,
      });
      setData(resp);
      setState(resp.available === false ? 'done' : next);
      return resp;
    } catch (e) {
      setError(String(e?.message || e));
      setState('error');
      return null;
    }
  };

  // ⚠ probe 착수는 **effect** 여야 한다 — 렌더 중에 발사하면 StrictMode 의 이중 렌더에서
  //   요청이 두 번 나간다(렌더는 순수해야 한다). 카드 자체가 행을 펼쳤을 때만 마운트되므로
  //   마운트가 곧 사용자의 의도이고, deps 는 조회 대상 3개면 충분하다.
  useEffect(() => {
    if (blocked) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const resp = await post('/api/summary/rule-conflict-advice', {
          job_url: jobUrl, cache_root: cacheRoot, conflict_id: conflict.id, probe: true,
        });
        if (cancelled) return;
        setData(resp);
        setState(resp.available === false ? 'done' : 'ready');
      } catch (e) {
        if (!cancelled) { setError(String(e?.message || e)); setState('error'); }
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot, conflict.id, blocked]);

  const generate = (force) => {
    setState('loading');
    setError('');
    call(force ? { force: true } : {}, 'done');
  };

  const advice = data?.advice;
  // probe 가 캐시를 물고 오면 그 자리에서 지침이 이미 있다 — 그때 버튼은 '생성'이 아니라
  // '재생성'이어야 한다(눌러도 같은 캐시가 돌아와 아무 일도 안 일어나는 죽은 버튼 방지).
  const settled = state === 'ready' || state === 'done';
  const canAct = settled && data?.available !== false;
  return (
    <div style={{ borderLeft: '3px solid var(--accent)', padding: '4px 8px', marginTop: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ ...xs, fontWeight: 600 }}>해결 지침</span>
        {blocked && (
          <span style={{ ...xs, color: 'var(--text-muted)' }}>
            {ADVICE_REASON_KO[blocked.reason] || `생성 불가 (${blocked.reason})`}
            {blocked.unattributed != null && ` (위반 ${blocked.unattributed}/${blocked.total}건이 미귀속)`}
          </span>
        )}
        {state === 'probing' && <span style={{ ...xs, color: 'var(--text-muted)' }}>확인 중…</span>}
        {state === 'loading' && <span style={{ ...xs, color: 'var(--text-muted)' }}>생성 중…</span>}
        {canAct && (
          <button type="button" style={btn} onClick={() => generate(!!advice)}>
            {advice ? '재생성' : '지침 생성'}
          </button>
        )}
        {/* 근거의 **성격**을 밝힌다 — 예방적 지침을 '이미 걸려 있다'로 읽으면 안 된다. */}
        {conflict.advice?.basis === 'fixing_only' && !blocked && (
          <span style={{ ...xs, color: 'var(--color-info)' }}
            title="상대 규칙은 이 빌드에서 아직 위반이 없습니다 — 지침은 '고치면 그때 걸린다'는 예측입니다">
            예방적 — 상대 규칙 아직 미발생
          </span>
        )}
        {data?.evidence_used && (
          <span style={{ ...xs, color: 'var(--text-muted)' }}>
            근거: 코드 발췌 {data.evidence_used.cooccurrence_excerpts ?? 0}건 · 구간 diff {data.evidence_used.window_diffs ?? 0}건
          </span>
        )}
      </div>
      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>지침 생성 오류: {error}</div>}
      {data?.available === false && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          {ADVICE_REASON_KO[data.reason] || `지침을 만들 수 없습니다 (${data.reason})`}
        </div>
      )}
      {advice && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginTop: 4 }}>
          <div style={{ ...xs, color: 'var(--text-muted)' }}>⚖ {data.note}</div>
          {advice.tradeoff && <div style={xs}><b>부딪히는 지점</b> — {advice.tradeoff}</div>}
          {advice.both_satisfying_pattern && (
            <div>
              <div style={{ ...xs, color: 'var(--color-success)' }}>둘 다 만족하는 작성</div>
              <pre style={mono}>{advice.both_satisfying_pattern}</pre>
            </div>
          )}
          {advice.recommended_order && <div style={xs}><b>처리 순서</b> — {advice.recommended_order}</div>}
          {advice.deviation_candidate && <div style={xs}><b>예외 신청 후보</b> — {advice.deviation_candidate}</div>}
          {advice.residual_risk && (
            <div style={{ ...xs, color: 'var(--color-warning)' }}>남는 위험 — {advice.residual_risk}</div>
          )}
          <div style={{ ...xs, color: 'var(--text-muted)' }}>
            확신도 {advice.confidence} · {data.model || 'AI 미사용'}{data.cached ? ' · 캐시됨' : ''}
            {(data.evidence_files || []).length > 0 && ` · 근거 파일 ${data.evidence_files.map((f) => String(f).split('/').pop()).join(', ')}`}
          </div>
        </div>
      )}
      {state === 'done' && data?.available !== false && !advice && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          AI 지침 미생성({ADVICE_REASON_KO[data.enrich_reason] || data.enrich_reason || 'llm_unavailable'}) —
          아래 &lsquo;알려진 해소 방향&rsquo;은 지식 테이블 값이라 AI 없이도 유효합니다.
        </div>
      )}
    </div>
  );
}

/**
 * 상한에 잘린 사실 — "이게 전부"로 읽히지 않게 목록 바로 아래 붙인다.
 * 서버가 표시분과 **전체 건수**를 함께 주므로 프론트가 세지 않는다(두 계층이 각자 세면 갈린다).
 */
function MoreNote({ shown, total, unit = '건' }) {
  if (!(total > shown)) return null;
  return (
    <div style={{ ...xs, color: 'var(--text-muted)' }}>
      … 표시 상한으로 {total - shown}{unit} 더 있음 (전체 {total}{unit})
    </div>
  );
}

/** 상충 1건의 펼침 내용 — 메커니즘 → 실측 증거 → 해소 방향 → 지침(LLM). */
function ConflictDetail({ jobUrl, cacheRoot, conflict }) {
  const ev = conflict.evidence || {};
  const et = conflict.evidence_totals || {};
  const gen = conflict.generated || {};
  const genTotal = gen.attributed_total || 0;
  const genShare = genTotal > 0 ? (gen.violations || 0) / genTotal : 0;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {conflict.mechanism && <div style={xs}><b>왜 걸리나</b> — {conflict.mechanism}</div>}
      <div style={{ ...xs, color: 'var(--text-muted)' }}>{conflict.tier_note}</div>

      {/* 손댈 수 없는 몫 — 이걸 안 보이면 "고쳐라"라고 내민 항목이 사실 전부 생성 코드일 수 있다. */}
      {(gen.violations || 0) > 0 && (
        <div style={{ ...xs, color: genShare >= 0.5 ? 'var(--color-warning)' : 'var(--text-muted)' }}>
          {genShare >= 1
            ? '⚠ 이 규칙의 파일 귀속 위반이 전부 자동 생성 파일입니다 — 손으로 고칠 코드가 없습니다.'
            : `⚠ 이 규칙 위반 ${genTotal}건 중 ${gen.violations}건(${Math.round(genShare * 100)}%)이 자동 생성 파일입니다.`}
          {' 직접 수정하면 재생성 시 되돌아옵니다 — 생성기 설정·템플릿 또는 예외 신청 대상입니다'}
          {(gen.files || []).length > 0 && ` (${gen.files.map((f) => String(f).split('/').pop()).join(', ')})`}.
        </div>
      )}

      {(ev.windows || []).length > 0 && (
        <div>
          <div style={T.figTitle}>구간 실측 — 한쪽이 줄고 다른 쪽이 늘어난 관측</div>
          {ev.windows.map((w) => (
            <div key={`${w.file}-${w.from_build}-${w.to_build}-${w.rule_up}`} style={xs}>
              #{w.from_build}→#{w.to_build} · {String(w.file).split('/').pop()} ·{' '}
              <b>{w.rule_down}</b> {w.delta_down} / <b>{w.rule_up}</b> +{w.delta_up}
            </div>
          ))}
          <MoreNote shown={ev.windows.length} total={et.windows} />
        </div>
      )}

      {(ev.cooccurrence || []).length > 0 && (
        <div>
          <div style={T.figTitle}>동시 위반 파일</div>
          {ev.cooccurrence.map((c) => (
            <div key={c.file} style={xs} title={c.file}>
              {String(c.file).split('/').pop()}
              {c.scope === 'cross_module' && <span style={{ color: 'var(--text-muted)' }}> (모듈 간 집계)</span>}
              {c.generated && <span style={{ color: 'var(--color-warning)' }}> (자동 생성)</span>}
              {' — 고칠 대상 '}
              {Object.entries(c.fixing_counts || {}).map(([r, n]) => `${r} ${n}`).join(', ')}
              {' / 걸릴 수 있음 '}
              {Object.entries(c.risk_counts || {}).map(([r, n]) => `${r} ${n}`).join(', ')}
            </div>
          ))}
          <MoreNote shown={ev.cooccurrence.length} total={et.cooccurrence} unit="파일" />
        </div>
      )}

      {/* 예방적 근거(상대 규칙 미발생)일 때의 조치 대상 파일 — 예전엔 서버가 주는데도
          화면에 전혀 안 나와, 지침의 근거가 무엇인지 볼 방법이 없었다. */}
      {(ev.cooccurrence || []).length === 0 && (conflict.fixing_files || []).length > 0 && (
        <div>
          <div style={T.figTitle}>고칠 규칙이 위반 중인 파일 — 상대 규칙은 아직 미발생</div>
          {conflict.fixing_files.map((f) => (
            <div key={f.file} style={xs} title={f.file}>
              {String(f.file).split('/').pop()} — {f.count}건
              {f.generated && <span style={{ color: 'var(--color-warning)' }}> (자동 생성)</span>}
            </div>
          ))}
          <MoreNote shown={conflict.fixing_files.length} total={et.fixing_files} unit="파일" />
        </div>
      )}

      {/* 메트릭 축 — 빈 목록의 뜻을 서버 판정(metric_axis)으로 확정한다.
          '봤는데 여유 있음'과 '못 봄'을 같은 화면으로 두면 후자가 안전으로 읽힌다. */}
      {conflict.metric_axis?.applicable && (
        <div>
          <div style={T.figTitle}>메트릭 여유 — 이 수정이 밴드를 넘길 수 있는 함수</div>
          {conflict.metric_axis.checked === false ? (
            <div style={{ ...xs, color: 'var(--color-warning)' }}>
              ⚠ 확인하지 못했습니다 — {METRIC_AXIS_REASON_KO[conflict.metric_axis.reason] || conflict.metric_axis.reason}.
              이 수정은 {(conflict.metric_risk || []).join('·')} 를 밀어올릴 수 있으나 그 여유를 측정하지 못했습니다.
            </div>
          ) : (ev.metric_headroom || []).length === 0 ? (
            <div style={T.note}>
              이 규칙 위반 파일의 함수 {conflict.metric_axis.files_checked}개 파일을 확인했고,
              {' '}{(conflict.metric_risk || []).join('·')} 여유가 {conflict.metric_axis.threshold}단 이하인 함수는 없습니다.
            </div>
          ) : (
            <>
              {ev.metric_headroom.map((m) => (
                <div key={`${m.file}-${m.function}-${m.metric}`} style={{ ...xs, color: 'var(--color-warning)' }}>
                  {m.function} · {m.label} {m.value} — <b>여유 {m.headroom}단</b>, 넘으면 {m.st_id} 판정이{' '}
                  {m.verdict}({m.band}) → <b>{m.next_verdict}({m.next_band})</b>
                </div>
              ))}
              <MoreNote shown={ev.metric_headroom.length} total={et.metric_headroom} unit="개 함수" />
            </>
          )}
        </div>
      )}

      {(conflict.resolutions || []).length > 0 && (
        <div>
          <div style={T.figTitle}>알려진 해소 방향</div>
          <ul style={{ margin: 0, paddingLeft: 16 }}>
            {conflict.resolutions.map((r) => <li key={r} style={xs}>{r}</li>)}
          </ul>
        </div>
      )}
      {conflict.deviation_hint && (
        <div style={xs}><b>예외(deviation) 판단</b> — {conflict.deviation_hint}</div>
      )}
      {(conflict.risk_filtered || []).length > 0 && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          이 프로젝트 규칙셋에 없어 제외: {conflict.risk_filtered.map((f) => f.rule).join(', ')}
        </div>
      )}
      {(conflict.refs || []).length > 0 && (
        <div style={T.note}>출처: {conflict.refs.join(' · ')}</div>
      )}

      <ConflictAdviceCard jobUrl={jobUrl} cacheRoot={cacheRoot} conflict={conflict} />
    </div>
  );
}

/**
 * 함께 해소될 수 있는 규칙 — 상충의 **반대편**.
 *
 * "고치면 걸린다"만 보여주면 질문의 반쪽만 답하는 것이다. 실측에서 MISRA `Rule-2.2`와
 * 회사 규칙 `C-POS-012`("Remove 'Dead Code'")가 파일별 카운트까지 일치했다 — 한쪽을
 * 고치면 다른 쪽도 함께 줄고, 위반 총계에는 같은 코드가 두 번 들어가 있다.
 * ⚠ 줄 정보가 없어 '같은 코드'라고 단정하지 않는다(서버 note 상시 노출).
 */
function CoResolutionList({ items, note }) {
  if (!items?.length) {
    return <div style={T.note}>파일별 위반 수가 일치하는 규칙 쌍이 없습니다.</div>;
  }
  return (
    <>
      <div style={T.SCROLL}>
        <table style={T.TABLE}>
          <thead>
            <tr>
              <th style={T.th}>규칙 쌍</th><th style={T.numTh}>겹침(상한)</th>
              <th style={T.th}>근거</th><th style={T.th}>규칙 내용</th>
            </tr>
          </thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.rules.join('~')}>
                <td style={T.nameTd(200)}>
                  <b>{e.rules[0]}</b> ≡ <b>{e.rules[1]}</b>
                  {/* 3-state — null 은 '같은 규칙셋'이 아니라 '규칙 설명이 없어 모름'이다. */}
                  {e.cross_ruleset === true && (
                    <div style={{ ...xs, color: 'var(--color-info)' }}
                      title={`서로 다른 규칙셋(${(e.groups || []).join(' / ')})이 같은 코드를 각각 세고 있을 가능성`}>
                      규칙셋 교차 {(e.groups || []).filter(Boolean).join(' / ')}
                    </div>
                  )}
                  {e.cross_ruleset == null && (
                    <div style={{ ...xs, color: 'var(--text-muted)' }}
                      title="이 빌드에 규칙 설정(RCFInfo)이 없어 두 규칙이 같은 규칙셋인지 확인하지 못했습니다">
                      규칙셋 미상
                    </div>
                  )}
                </td>
                <td style={T.numTd}>
                  {e.overlap_upper_bound}
                  <div style={{ ...xs, color: 'var(--text-muted)', fontWeight: 400 }}>
                    총 {e.totals[e.rules[0]]}/{e.totals[e.rules[1]]}
                  </div>
                </td>
                <td style={T.td}
                  title={(e.sample_files || []).map((s) => `${String(s.file).split('/').pop()}: ${e.rules[0]}=${s[e.rules[0]]} ${e.rules[1]}=${s[e.rules[1]]}`).join('\n')}>
                  공존 {e.files}파일 중 <b>{e.identical_files}</b>개에서 수치 일치
                </td>
                <td style={T.textTd(300)}>
                  {e.titles.filter(Boolean).length === 0
                    ? <span style={{ color: 'var(--text-muted)' }}>이 빌드 리포트에 규칙 설명이 없습니다</span>
                    : e.titles.map((t, i) => <div key={e.rules[i]}>{t || '—'}</div>)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {note && <div style={T.note}>⚖ {note}</div>}
    </>
  );
}

/**
 * 자동 생성 마커 확인이 **얼마나 완전한가**.
 *
 * 두 상태를 구분한다: ①스냅샷이 없어 한 건도 못 봄 ②상한에 걸려 일부만 봄.
 * ⚠ 예전엔 숫자 하나(`generated_unprobed`)뿐이라, 스냅샷이 아예 없어 0건 확인한 상태도
 *   `0`(= 전부 확인함)으로 나갔다 — 같은 0이 정반대를 뜻했다.
 */
function ProbeNote({ probe, unprobed }) {
  if (probe && probe.available === false) {
    return (
      <div style={{ ...xs, color: 'var(--color-warning)' }}>
        ⚠ 이 빌드에 소스 스냅샷(source/)이 없어 <b>파일 내 생성 마커를 한 건도 확인하지 못했습니다</b>
        {(probe.candidates || 0) > 0 && ` (확인 대상 ${probe.candidates}개 전부)`} —
        아래 목록은 경로 규칙(Generated_Code/·*_Cfg.c 등)으로 잡힌 것뿐이라 완전하지 않습니다.
      </div>
    );
  }
  const left = probe?.unprobed ?? unprobed ?? 0;
  if (left > 0) {
    return (
      <div style={{ ...xs, color: 'var(--color-warning)' }}>
        ⚠ 파일 {left}개는 검사 상한({probe?.cap ?? '—'}개)에 걸려 생성 마커를 확인하지 못했습니다 —
        이 목록은 완전하지 않습니다 (위반이 많은 파일부터 확인했습니다).
      </div>
    );
  }
  return null;
}

/** 측정 근거가 불확실한 지점 — 숫자를 그대로 믿으면 안 되는 곳. */
function MeasurementList({ items }) {
  if (!items?.length) {
    return <div style={T.note}>이 빌드에서 측정 근거가 불확실한 항목은 없습니다.</div>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
      {items.map((m, i) => (
        <div key={`${m.kind}-${m.from_build ?? i}`} style={xs}>
          <b>{MEASURE_LABEL[m.kind] || m.kind}</b>
          {m.kind === 'ruleset_change' && (
            <> — #{m.from_build}→#{m.to_build}에서 규칙 {m.from_size}→{m.to_size}개
              {m.affected_total > 0 && ` (측정 범위가 바뀐 규칙 ${m.affected_total}종: ${m.affected_rules.join(', ')}${m.affected_total > m.affected_rules.length ? ' …' : ''})`}
            </>
          )}
          {m.kind === 'unattributed' && (
            <> — {(m.rules || []).map((r) => `${r.rule} ${r.unattributed}/${r.total}건`).join(', ')}</>
          )}
          {m.kind === 'single_observation' && <> — {m.total}종 ({(m.rules || []).join(', ')})</>}
          {m.kind === 'residual' && <> — {m.count}건</>}
          {m.kind === 'file_unattributed' && <> — 총 {m.total} vs 파일 합계 {m.attributed} (차이 {m.gap}건)</>}
          <div style={T.note}>{m.detail}</div>
        </div>
      ))}
    </div>
  );
}

export default function RuleConflictPanel({
  jobUrl, cacheRoot, data, error, onRetry, defaultOpen = false, focusId = '',
}) {
  // focusId 는 룰 트렌드 표에서 넘어온 상충 — 그 행을 펼친 채 시작한다(부모가 key 로
  // 재마운트하므로 이 초기값이 곧 화면 상태다).
  const [expanded, setExpanded] = useState(focusId || null);
  const bodyRef = useRef(null);
  useEffect(() => {
    if (focusId && bodyRef.current) {
      bodyRef.current.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [focusId]);
  const conflicts = data?.conflicts || [];
  const amb = data?.ambiguities || {};
  const omitted = data?.conflicts_omitted || 0;
  const rulesetUnknown = data?.available && data?.ruleset?.available === false;

  // ⚠ 문제가 없으면 반드시 null — 항상 truthy 인 프래그먼트를 넘기면 패널이 영구 펼침이 된다.
  let problem = null;
  if (error) {
    problem = <span style={{ ...xs, color: 'var(--color-danger)' }}>⚠ 조회 실패 — {error}</span>;
  } else if (data && data.available === false) {
    problem = (
      <span style={{ ...xs, color: 'var(--color-warning)' }}>
        {data.reason === 'table_missing' ? '⚠ 상충 지식 테이블(config/misra_rule_conflicts.json)이 없습니다'
          : data.reason === 'table_unreadable' || data.reason === 'table_invalid' ? `⚠ 상충 지식 테이블을 읽을 수 없습니다 (${data.reason})`
          : data.reason === 'no_cached_build' ? '캐시된 빌드가 없습니다'
          : data.reason === 'no_rcr_in_cached_builds' ? '캐시된 빌드에 PRQA(RCR) 리포트가 없습니다'
          : `상충을 계산할 수 없습니다 (${data.reason})`}
      </span>
    );
  } else if (data?.available && data?.snapshot?.available === false) {
    // 스냅샷이 없으면 **해결 지침 전체**와 자동 생성 마커 확인이 통째로 막힌다 —
    // 행을 펼쳐야만 알게 되면 사용자는 버튼을 누르고 나서야 실패를 본다.
    problem = (
      <span style={{ ...xs, color: 'var(--color-warning)' }}>
        ⚠ 소스 스냅샷 없음 — 해결 지침·생성 마커 확인 불가
      </span>
    );
  } else if (omitted > 0) {
    problem = <span style={{ ...xs, color: 'var(--color-warning)' }}>⚠ 표시 상한으로 {omitted}건 생략</span>;
  }

  return (
    <SummaryPanel
      title="룰 상충·판단 지점"
      defaultOpen={defaultOpen}
      caption="한 규칙을 고칠 때 걸릴 수 있는 다른 규칙과, 숫자만으로 판단하면 안 되는 지점을 모았습니다."
      meta={<>
        {data?.available && (
          <span style={{ ...xs, color: 'var(--text-muted)' }}>
            #{data.build_number} 기준 · 상충 {conflicts.length}건
            {rulesetUnknown && ' · 규칙 활성 미확인'}
          </span>
        )}
        {!data && !error && <span className="spinner" />}
      </>}
      problem={problem}
      actions={error && onRetry ? (
        <button type="button" style={btn} onClick={onRetry}>다시 시도</button>
      ) : undefined}
    >
      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>룰 상충 조회 오류: {error}</div>}

      {data?.available && (
        <div ref={bodyRef} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
          <div style={T.note}>⚖ {data.note}</div>
          {rulesetUnknown && (
            <div style={{ ...xs, color: 'var(--color-warning)' }}>
              ⚠ 이 빌드의 RCR에 규칙 설정(RCFInfo)이 없어 <b>상대 규칙이 실제로 검사되는지 확인하지 못했습니다</b> —
              아래 후보 중 일부는 그 규칙이 꺼져 있어 실제로는 걸리지 않을 수 있습니다.
            </div>
          )}
          {/* 메트릭 축 부재는 RCFInfo 부재와 같은 급의 침묵이다 — 상충별 표시와 별개로
              패널 상단에도 낸다(모든 행을 펼쳐야 알 수 있으면 안 된다). */}
          {data.metrics && data.metrics.available === false && (
            <div style={{ ...xs, color: 'var(--color-warning)' }}>
              ⚠ HIS 메트릭(HMR)을 읽지 못했습니다 —{' '}
              {METRIC_AXIS_REASON_KO[data.metrics.reason] || data.metrics.reason}.
              복잡도·중첩을 밀어올리는 수정(단일 exit 변환, 재귀 제거 등)의 <b>여유 판정이 빠진 상태</b>입니다.
            </div>
          )}

          {/* 소스 스냅샷 축 — RCR·메트릭과 같은 급. 이게 없으면 코드 근거를 쓰는 모든 것이
              막히는데, 예전엔 응답에 필드조차 없어 화면이 '지침 생성 가능'을 거짓으로 말했다. */}
          {data.snapshot && data.snapshot.available === false && (
            <div style={{ ...xs, color: 'var(--color-warning)' }}>
              ⚠ 이 빌드에 <b>소스 스냅샷(source/)이 없습니다</b> —{' '}
              {ADVICE_REASON_KO[data.snapshot.reason] || data.snapshot.reason}.
              상충 판정 자체는 위반 리포트만으로 하므로 유효하지만, <b>해결 지침(코드 발췌)과
              자동 생성 마커 확인은 만들 수 없습니다</b>.
            </div>
          )}

          {/* 위반 표를 못 읽었으면 '상충 없음'이 아니라 측정 실패다 — 좋은 소식으로 위장 금지. */}
          {data.latest_rcr_reason && (
            <div style={{ ...xs, color: 'var(--color-warning)' }}>
              ⚠ 최신 빌드의 위반 상세(RCR)를 읽지 못했습니다 (
              {data.latest_rcr_reason === 'latest_build_not_cached' ? '해당 빌드가 캐시에 없음' : '리포트 부재 또는 파싱 실패'}
              ) — 아래 결과는 위반 데이터 없이 산출된 것이라 완전하지 않습니다.
            </div>
          )}
          {conflicts.length === 0 ? (
            <div style={{ ...xs, color: 'var(--text-muted)' }}>
              이 빌드의 위반 규칙 중 지식 테이블에 등재된 상충 관계에 해당하는 것이 없습니다
              (테이블 {data.table?.total ?? 0}쌍 대조).
            </div>
          ) : (
            <div style={T.SCROLL}>
              <table style={T.TABLE}>
                <thead>
                  <tr>
                    <th style={T.th}>고치려는 규칙</th>
                    <th style={T.th}>걸릴 수 있는 규칙</th>
                    <th style={T.th}>근거</th>
                    {/* 조치 가능성을 표 본문에 둔다 — 펼쳐야만 보이면 "고쳐라" 목록 맨 위가
                        사실은 손댈 수 없는 파일이라는 걸 아무도 모른다. */}
                    <th style={T.th}>자동 생성 몫</th>
                    <th style={T.th}>관계</th>
                    <th style={T.th}>확신도</th>
                    <th style={T.th}>상세</th>
                  </tr>
                </thead>
                <tbody>
                  {conflicts.map((c) => {
                    const open = expanded === c.id;
                    return (
                      <Fragment key={c.id}>
                        <tr>
                          {/* 배열 접근은 전부 `|| []` 를 거친다 — 서버 필드가 하나만 비어도
                              `.length` 에서 표 전체가 크래시하고, 그러면 다른 상충까지 사라진다. */}
                          <td style={T.nameTd(200)}>
                            {(c.fixing || []).map((m, i) => (
                              <Fragment key={m.rule}>{i > 0 && ' · '}<RuleChip meta={m} /></Fragment>
                            ))}
                          </td>
                          <td style={T.nameTd(220)}>
                            {(c.risk || []).length === 0
                              ? <span style={{ color: 'var(--text-muted)' }}>규칙 아닌 요구와 충돌</span>
                              : c.risk.map((m, i) => (
                                <Fragment key={m.rule}>{i > 0 && ' · '}<RuleChip meta={m} /></Fragment>
                              ))}
                          </td>
                          <td style={T.td}><TierBadge tier={c.tier} /></td>
                          <td style={T.td}><GeneratedShare generated={c.generated} /></td>
                          <td style={T.td}>{KIND_LABEL[c.kind] || c.kind}</td>
                          <td style={T.td}>{c.confidence}</td>
                          <td style={T.td}>
                            <button type="button" style={btn} aria-expanded={open}
                              onClick={() => setExpanded(open ? null : c.id)}>
                              {(open ? '▾ ' : '▸ ') + '보기'}
                            </button>
                          </td>
                        </tr>
                        {open && (
                          <tr>
                            <td colSpan={7} style={{ padding: '6px 8px', borderBottom: '1px solid var(--border)' }}>
                              <ConflictDetail jobUrl={jobUrl} cacheRoot={cacheRoot} conflict={c} />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          <div>
            <div style={T.figTitle}>함께 해소될 수 있는 규칙 — 같은 코드를 두 규칙이 셌을 가능성</div>
            <div style={T.note}>
              한쪽을 고치면 다른 쪽도 함께 줄어듭니다. 조치 우선순위를 정할 때와,
              위반 총계를 읽을 때(같은 코드가 두 번 들어가 있습니다) 함께 보세요.
            </div>
            <CoResolutionList items={data.co_resolution} note={data.co_resolution_note} />
          </div>

          <div>
            <div style={T.figTitle}>측정 근거가 불확실한 지점</div>
            <MeasurementList items={amb.measurement} />
          </div>

          <div>
            <div style={T.figTitle}>자동 생성 코드의 위반</div>
            {/* ⚠ 마커 확인의 완전성은 목록 유무와 **무관하게** 먼저 말한다. 스냅샷이 없으면
                한 건도 못 본 것이고, 예전엔 그 상태가 "확인했고 없음"으로 보였다. */}
            <ProbeNote probe={amb.generated_probe} unprobed={amb.generated_unprobed} />
            {(amb.generated || []).length === 0 ? (
              <div style={T.note}>자동 생성으로 판별된 위반 파일이 없습니다.</div>
            ) : (
              <>
                <div style={T.note}>
                  직접 고치면 재생성 시 되돌아옵니다 — 생성기 설정·템플릿 또는 예외 신청 대상입니다.
                  {/* 분모 없이 파일 목록만 주면 "몇 개뿐이네"로 읽힌다 — 실측 HDPDM01은
                      파일 2개가 전체 파일 귀속 위반의 68.8%였다. */}
                  {(amb.generated_share?.attributed_total || 0) > 0 && (
                    <> <b>파일에 귀속된 위반 {amb.generated_share.attributed_total}건 중{' '}
                      {amb.generated_share.violations}건({Math.round(
                        (amb.generated_share.violations / amb.generated_share.attributed_total) * 100)}%)
                    </b>이 여기 있습니다.</>
                  )}
                </div>
                <div style={T.SCROLL}>
                  <table style={T.TABLE}>
                    <thead>
                      <tr>
                        <th style={T.th}>파일</th><th style={T.numTh}>위반</th>
                        <th style={T.th}>규칙</th><th style={T.th}>판별 근거</th>
                      </tr>
                    </thead>
                    <tbody>
                      {amb.generated.map((g) => (
                        <tr key={g.file}>
                          <td style={T.nameTd(240)} title={g.file}>{String(g.file).split('/').pop()}</td>
                          <td style={T.numTd}>{g.violations}</td>
                          <td style={T.nameTd(200)} title={g.rules.join(', ')}>{g.rules.join(', ')}</td>
                          <td style={T.td}>{g.basis === 'path' ? '경로 규칙' : '파일 내 생성 마커'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>

          {/* 대조 결과가 자립해야 한다 — 34쌍 중 3건만 보이는 이유를 화면이 말하지 않으면
              "상충이 거의 없다"로 잘못 읽힌다. */}
          <div style={T.note}>
            * 지식 테이블 {data.table?.total ?? 0}쌍 대조 — 표시 {conflicts.length}건 ·
            {/* 상한 절단을 각주에도 넣어야 합이 total 이 된다 — problem 슬롯에만 있으면
                각주 산수가 안 맞는데 화면은 아무 말도 안 한다. */}
            {omitted > 0 && <> 표시 상한으로 생략 {omitted}건 ·</>}
            {' '}해당 규칙 위반이 없어 제외 {data.table?.skipped_no_violation ?? 0}건
            {(data.table?.excluded || []).length > 0 && (
              <> · 상대 규칙이 이 프로젝트 규칙셋에 없어 성립하지 않음 {data.table.excluded.length}건
                {' ('}{data.table.excluded.map((e) => `${(e.fixing || []).join('/')}→${(e.inactive || []).join('/') || '상대 규칙 미정의'}`).join(', ')}{')'}
              </>
            )}
          </div>
          {data.table?.source_note && <div style={T.note}>* {data.table.source_note}</div>}
          {data.table?.category_note && <div style={T.note}>* {data.table.category_note}</div>}
        </div>
      )}
    </SummaryPanel>
  );
}
