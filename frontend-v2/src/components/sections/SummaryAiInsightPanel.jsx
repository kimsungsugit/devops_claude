/**
 * SummaryAiInsightPanel — 프로젝트 요약탭 AI 인사이트(Gemini) 패널.
 * POST /api/summary/ai-insight 소비: probe(캐시 조회, LLM 0회) → 캐시 히트면 자동 표시,
 * 미스면 'AI 인사이트 생성' 버튼(on-demand — 기존 AI 기능 관례). 생성 중 중단(AbortController),
 * 재생성(force). ai_enriched:false 섹션은 '결정론 분석(AI 미사용)' 배지 + 사유 표기.
 *
 * ISO 감사 흔적: 푸터에 모델/생성 시각/캐시 여부. 마크다운 라이브러리 금지(pre-wrap).
 * X9: raw fetch 금지 — api/post 헬퍼만(api는 AbortSignal 전달용).
 */
import { useEffect, useRef, useState } from 'react';
import { api, post } from '../../api.js';

const SECTION_REASON_KO = {
  llm_unavailable: 'LLM 미설정 — 결정론 분석만 표시',
  llm_error: 'AI 호출 실패 — 결정론 분석으로 폴백',
  llm_empty_or_invalid: 'AI 응답 무효 — 결정론 분석으로 폴백',
};
const CONF_COLOR = { high: 'var(--color-success)', medium: 'var(--color-warning)', low: 'var(--text-muted)' };

const xs = { fontSize: 'var(--text-xs)' };

function Badge({ text, color }) {
  return (
    <span style={{
      display: 'inline-block', padding: '1px 7px', borderRadius: 'var(--radius-sm)',
      fontSize: 'var(--text-xs)', fontWeight: 600, color: '#fff', background: color,
    }}>{text}</span>
  );
}

function FallbackNote({ section }) {
  if (section?.ai_enriched) return null;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
      <Badge text="결정론 분석(AI 미사용)" color="var(--text-muted)" />
      <span style={{ ...xs, color: 'var(--text-muted)' }}>{SECTION_REASON_KO[section?.reason] || section?.reason || ''}</span>
    </div>
  );
}

function RoleList({ title, items }) {
  return (
    <div style={{ flex: 1, minWidth: 240 }}>
      <div style={{ ...xs, fontWeight: 700, marginBottom: 4 }}>{title}</div>
      {(items || []).map((it, i) => (
        <div key={i} style={{ ...xs, marginBottom: 6 }}>
          <b>{`${it.priority}. ${it.action}`}</b>
          {it.basis && <div style={{ color: 'var(--text-muted)' }}>{`근거: ${it.basis}`}</div>}
        </div>
      ))}
      {(!items || items.length === 0) && <div style={{ ...xs, color: 'var(--text-muted)' }}>권고 없음</div>}
    </div>
  );
}

export default function SummaryAiInsightPanel({ jobUrl, cacheRoot, scmId, trace }) {
  const [data, setData] = useState(null);
  const [phase, setPhase] = useState('probing'); // probing | idle | generating | done | error
  const [error, setError] = useState('');
  const abortRef = useRef(null);

  // 마운트 시 probe — 캐시 있으면 자동 표시(LLM 0회). trace는 스냅샷 전달용이라 deps 제외
  // (변할 때마다 재-probe할 이유 없음 — 생성 시점 값만 실어 보낸다).
  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const resp = await post('/api/summary/ai-insight', { job_url: jobUrl, cache_root: cacheRoot, probe: true });
        if (cancelled) return;
        if (resp?.cached) { setData(resp); setPhase('done'); }
        else setPhase('idle');
      } catch {
        if (!cancelled) setPhase('idle'); // probe 실패는 버튼 표시로 폴백(생성 시 실오류 노출)
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot]);

  const generate = async (force) => {
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setPhase('generating');
    setError('');
    try {
      const body = {
        job_url: jobUrl, cache_root: cacheRoot, scm_id: scmId || '',
        trace_summary: trace?.has_data ? trace : undefined,
        ...(force ? { force: true } : {}),
      };
      // post() 대신 api() 직접 — AbortSignal 전달(중단 버튼). 헤더/재시도는 api()가 처리.
      const resp = await api('/api/summary/ai-insight', { method: 'POST', body: JSON.stringify(body), signal: ctrl.signal });
      setData(resp);
      setPhase('done');
    } catch (e) {
      if (e?.name === 'AbortError') { setPhase(data ? 'done' : 'idle'); return; }
      setError(String(e?.message || e));
      setPhase(data ? 'done' : 'error');
    } finally {
      abortRef.current = null;
    }
  };
  const abort = () => { abortRef.current?.abort(); };

  const sections = data?.sections || {};
  const det = data?.deterministic || {};

  return (
    <div className="panel" style={{ padding: 'var(--sp-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>🤖 AI 인사이트 (Gemini)</div>
        {phase === 'probing' && <span className="spinner" />}
        {phase === 'generating' && (
          <>
            <span className="spinner" />
            <span style={{ ...xs, color: 'var(--text-muted)' }}>생성 중… (위반·delta·실제 코드 발췌 분석)</span>
            <button type="button" onClick={abort}
              style={{ ...xs, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--color-danger)' }}>
              중단
            </button>
          </>
        )}
        {phase === 'idle' && (
          <button type="button" onClick={() => generate(false)}
            style={{ ...xs, padding: '3px 10px', border: '1px solid var(--accent)', borderRadius: 'var(--radius-sm)', background: 'var(--accent)', cursor: 'pointer', color: '#fff', fontWeight: 600 }}>
            AI 인사이트 생성
          </button>
        )}
        {phase === 'done' && (
          <button type="button" onClick={() => generate(true)} disabled={false}
            style={{ ...xs, marginLeft: 'auto', padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}>
            재생성
          </button>
        )}
      </div>

      {phase === 'idle' && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          위반 상위 규칙·빌드간 delta·실제 코드 발췌를 근거로 개발자 실수 패턴과 역할별 권고를 생성합니다 (버튼 클릭 시에만 Gemini 호출 — 결과는 빌드별 캐시).
        </div>
      )}
      {error && <div style={{ ...xs, color: 'var(--color-danger)', marginBottom: 'var(--sp-2)' }}>AI 인사이트 오류: {error}</div>}

      {data && data.available === false && phase !== 'generating' && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          AI 인사이트를 만들 수 없습니다 ({data.reason || 'unknown'}) — 빌드 분석 캐시가 필요합니다.
        </div>
      )}
      {data && data.available !== false && phase !== 'generating' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
          {data.rcr_available === false && (
            <div style={{ ...xs, color: 'var(--color-warning)' }}>⚠ 최신 빌드에 PRQA(RCR) 리포트가 없어 위반 기반 인사이트가 제한됩니다.</div>
          )}

          {/* (a) 위반 룰 해설 */}
          {sections.rules && (
            <div>
              <div style={{ ...xs, fontWeight: 700, marginBottom: 4 }}>위반 룰 해설 — 왜 위험한가</div>
              <FallbackNote section={sections.rules} />
              {(sections.rules.items || []).map((it) => (
                <div key={it.rule} style={{ ...xs, borderLeft: '3px solid var(--color-warning)', padding: '4px 8px', marginBottom: 6 }}>
                  <b>{it.rule}</b>{it.title ? ` — ${it.title}` : ''}
                  {it.why_risky && <div>위험: {it.why_risky}</div>}
                  {it.typical_cause && <div style={{ color: 'var(--text-muted)' }}>전형 원인: {it.typical_cause}</div>}
                  {it.fix_guide && <div>수정: {it.fix_guide}</div>}
                </div>
              ))}
              {sections.rules.ai_enriched === false && (det.top_rules || []).length > 0 && (
                <div style={{ ...xs, color: 'var(--text-muted)' }}>
                  상위 위반: {(det.top_rules || []).slice(0, 5).map((r) => `${r.rule}(${r.count})`).join(' · ')}
                </div>
              )}
            </div>
          )}

          {/* (b) 개발자 실수 패턴 */}
          {sections.mistakes && (
            <div>
              <div style={{ ...xs, fontWeight: 700, marginBottom: 4 }}>반복 실수 패턴 — 실제 코드 근거</div>
              <FallbackNote section={sections.mistakes} />
              {(sections.mistakes.items || []).map((it, i) => (
                <div key={i} style={{ ...xs, borderLeft: '3px solid var(--color-info)', padding: '4px 8px', marginBottom: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                    <b>{it.pattern}</b>
                    <Badge text={`확신도 ${it.confidence || 'low'}`} color={CONF_COLOR[it.confidence] || 'var(--text-muted)'} />
                    {(it.rules || []).map((r) => <Badge key={r} text={r} color="var(--color-warning)" />)}
                  </div>
                  {it.diagnosis && <div>진단: {it.diagnosis}</div>}
                  {it.evidence_quote && (
                    <pre style={{
                      whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: 'var(--text-xs)',
                      background: 'var(--bg-elevated, var(--hover))', border: '1px solid var(--border)',
                      borderRadius: 'var(--radius-sm)', padding: '4px 8px', margin: '4px 0', overflowX: 'auto',
                    }}>{it.evidence_quote}</pre>
                  )}
                  {it.improvement && <div>개선안: {it.improvement}</div>}
                  {(it.files || []).length > 0 && <div style={{ color: 'var(--text-muted)' }}>파일: {(it.files || []).join(', ')}</div>}
                </div>
              ))}
              {sections.mistakes.ai_enriched === false && (
                <div style={{ ...xs, color: 'var(--text-muted)' }}>AI 미사용 상태에서는 패턴 진단이 제공되지 않습니다 — 생성/재생성으로 시도하세요.</div>
              )}
            </div>
          )}

          {/* (c) 역할별 권고 */}
          {sections.roles && (
            <div>
              <div style={{ ...xs, fontWeight: 700, marginBottom: 4 }}>역할별 권고</div>
              <FallbackNote section={sections.roles} />
              <div style={{ display: 'flex', gap: 'var(--sp-4)', flexWrap: 'wrap' }}>
                <RoleList title="👩‍💻 개발자" items={sections.roles.developer} />
                <RoleList title="🧪 테스터" items={sections.roles.tester} />
              </div>
            </div>
          )}

          {/* 감사 푸터 */}
          <div style={{ ...xs, color: 'var(--text-muted)', borderTop: '1px solid var(--border)', paddingTop: 6 }}>
            {data.model ? `모델 ${data.model}` : 'AI 미사용(결정론)'} · 생성 {String(data.generated_at || '').replace('T', ' ')} · {data.cached ? '캐시됨' : '새로 생성'}
            {data.input?.excerpt_files?.length > 0 && ` · 코드 발췌 ${data.input.excerpt_files.length}개`}
          </div>
        </div>
      )}
    </div>
  );
}
