/**
 * ArchitectureImprovementPanel — 아키텍처 개선(To-Be) 제안(Q3).
 * POST /api/summary/arch-improvement 소비.
 *
 * 두 층: ①결정론 후보(LLM 없이 항상 — 순환 끊기·계층 정돈·집중 파일 분할 + 테스트 용이성 3종)
 * ②AI 목표 구조(on-demand). As-Is와 To-Be를 **같은 형식으로 나란히** 놓아 무엇이 바뀌는지 본다.
 *
 * 정직성: note(제안≠검증된 설계)는 서버 고정값을 그대로 노출하고, 폐기된 노드 수도 표기한다.
 * X9: raw fetch 금지 — post 헬퍼만.
 */
import { useEffect, useState } from 'react';
import { post } from '../../api.js';

const xs = { fontSize: 'var(--text-xs)' };
const btn = {
  ...xs, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
  background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)',
};

const KIND_KO = {
  break_cycle: { label: '순환 끊기', color: 'var(--color-danger)' },
  layer_violation: { label: '계층 정돈', color: 'var(--color-warning)' },
  split_god_file: { label: '집중 파일 분할', color: 'var(--color-warning)' },
  extract_pure: { label: '순수 함수 추출', color: 'var(--color-info)' },
  inject_global: { label: '전역 주입화', color: 'var(--color-info)' },
  seam_for_pointer: { label: '시임 명시', color: 'var(--color-info)' },
};
const EFFORT_KO = { low: '낮음', medium: '보통', high: '높음' };
const TESTABILITY = new Set(['extract_pure', 'inject_global', 'seam_for_pointer']);

const REASON_KO = {
  no_candidates: '개선 후보가 없어 목표 구조를 만들지 않았습니다(현 구조에 임계 초과 항목 없음).',
  llm_unavailable: 'LLM 미설정 — 결정론 후보만 표시합니다.',
  llm_error: 'AI 호출 실패 — 결정론 후보만 표시합니다.',
  llm_empty_or_invalid: 'AI 응답이 무효였습니다 — 결정론 후보만 표시합니다.',
  all_nodes_filtered: 'AI가 제안한 모듈이 전부 입력 심볼 밖이라 폐기했습니다(환각 방지).',
  not_generated: '아직 생성하지 않았습니다 — 버튼을 눌러 목표 구조를 만드세요.',
};

/** 모듈 구조 목록 — As-Is/To-Be를 같은 형식으로 그려 비교 가능하게 한다. */
function StructureList({ title, nodes, edges, isTarget }) {
  return (
    <div style={{ flex: 1, minWidth: 260 }}>
      <div style={{ ...xs, fontWeight: 700, marginBottom: 4 }}>{title}</div>
      {(nodes || []).length === 0 && <div style={{ ...xs, color: 'var(--text-muted)' }}>표시할 모듈이 없습니다.</div>}
      {(nodes || []).map((n) => (
        <div key={n.module} style={{
          ...xs, border: '1px solid var(--border)', borderLeft: `3px solid ${n.is_new ? 'var(--color-success)' : 'var(--border)'}`,
          borderRadius: 'var(--radius-sm)', padding: '3px 8px', marginBottom: 3,
        }}>
          <b>{n.module}</b>
          {n.is_new && <span style={{ color: 'var(--color-success)' }}> · 신설</span>}
          {isTarget
            ? <>{n.role && <span style={{ color: 'var(--text-muted)' }}> — {n.role}</span>}
                {(n.members || []).length > 0 && (
                  <div style={{ color: 'var(--text-muted)' }}>구성: {(n.members || []).join(', ')}</div>
                )}</>
            : <span style={{ color: 'var(--text-muted)' }}> · 파일 {n.files} · 함수 {n.functions}</span>}
        </div>
      ))}
      {(edges || []).length > 0 && (
        <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 4 }}>
          의존: {(edges || []).slice(0, 8).map((e) => `${e.from}→${e.to}${e.calls != null ? `(${e.calls})` : ''}`).join(' · ')}
        </div>
      )}
    </div>
  );
}

export default function ArchitectureImprovementPanel({ jobUrl, cacheRoot }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState('all');

  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        // probe — 결정론 후보는 즉시(LLM 0회), AI 목표 구조는 캐시가 있을 때만 딸려온다.
        const resp = await post('/api/summary/arch-improvement', { job_url: jobUrl, cache_root: cacheRoot, probe: true });
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
      const resp = await post('/api/summary/arch-improvement', {
        job_url: jobUrl, cache_root: cacheRoot, ...(force ? { force: true } : {}),
      });
      setData(resp);
    } catch (e) {
      setError(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const th = { ...xs, textAlign: 'left', padding: '4px 8px', color: 'var(--text-muted)', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
  const td = { ...xs, padding: '4px 8px', borderBottom: '1px solid var(--border)' };
  const cands = (data?.candidates || []).filter((c) => (
    filter === 'all' ? true : filter === 'test' ? TESTABILITY.has(c.kind) : !TESTABILITY.has(c.kind)
  ));
  const td2 = data?.target_design;

  return (
    <div className="panel" style={{ padding: 'var(--sp-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>아키텍처 개선 제안 (To-Be)</div>
        {data?.available && (
          <span style={{ ...xs, color: 'var(--text-muted)' }}>
            빌드 #{data.build_number} · 후보 {data.summary?.total ?? 0}건
            (구조 {data.summary?.structural ?? 0} · 테스트 용이성 {data.summary?.testability ?? 0})
            {(data.summary?.omitted ?? 0) > 0 && ` · 표시 상한으로 ${data.summary.omitted}건 생략`}
          </span>
        )}
        {busy && <span className="spinner" />}
        {data?.available && (data.summary?.total ?? 0) > 0 && (
          <button type="button" style={{ ...btn, marginLeft: 'auto' }} onClick={() => generate(Boolean(td2))} disabled={busy}>
            {busy ? '생성 중…' : td2 ? '목표 구조 재생성' : '목표 구조 생성 (AI)'}
          </button>
        )}
      </div>

      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>개선 제안 오류: {error}</div>}
      {data && data.available === false && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          {data.reason === 'no_source_snapshot' ? '캐시 빌드에 소스 스냅샷이 없어 제안을 만들 수 없습니다.'
            : `개선 제안을 만들 수 없습니다 (${data.reason})`}
        </div>
      )}

      {data?.available && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
          {(data.summary?.total ?? 0) === 0 ? (
            <div style={{ ...xs, color: 'var(--text-muted)' }}>
              임계를 넘는 개선 후보가 없습니다 — 순환·집중 파일·계층 역방향·테스트 갭 모두 관측되지 않았습니다.
            </div>
          ) : (
            <>
              <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {[['all', '전체'], ['structure', '구조'], ['test', '테스트 용이성']].map(([k, label]) => (
                  <button key={k} type="button" onClick={() => setFilter(k)} aria-pressed={filter === k}
                    style={{
                      ...btn,
                      border: `1px solid ${filter === k ? 'var(--accent)' : 'var(--border)'}`,
                      background: filter === k ? 'var(--accent)' : 'transparent',
                      color: filter === k ? '#fff' : 'var(--text-muted)',
                    }}>
                    {label}
                  </button>
                ))}
                <span style={{ ...xs, color: 'var(--text-muted)' }}>표시 {cands.length}건</span>
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                  <thead>
                    <tr><th style={th}>종류</th><th style={th}>대상</th><th style={th}>조치</th><th style={th}>근거</th><th style={th}>비용</th></tr>
                  </thead>
                  <tbody>
                    {cands.map((c) => (
                      <tr key={`${c.kind}:${c.target}`}>
                        <td style={td}>
                          <span style={{ fontWeight: 600, color: KIND_KO[c.kind]?.color || 'var(--text-muted)' }}>
                            {KIND_KO[c.kind]?.label || c.kind}
                          </span>
                        </td>
                        <td style={{ ...td, fontFamily: 'monospace', whiteSpace: 'nowrap' }} title={(c.files || []).join(', ')}>{c.target}</td>
                        <td style={{ ...td, whiteSpace: 'normal' }}>{c.action}</td>
                        <td style={{ ...td, color: 'var(--text-muted)', whiteSpace: 'normal' }}>{c.basis}</td>
                        <td style={td}>{EFFORT_KO[c.effort] || c.effort}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {/* As-Is ↔ To-Be 병렬 — 같은 형식으로 놓아야 무엇이 바뀌는지 보인다 */}
          {td2 ? (
            <div>
              <div style={{ display: 'flex', gap: 'var(--sp-4)', flexWrap: 'wrap' }}>
                <StructureList title="현재 (As-Is)" nodes={data.as_is?.nodes} edges={data.as_is?.edges} />
                <StructureList title="제안 (To-Be)" nodes={td2.nodes} edges={td2.edges} isTarget />
              </div>
              {(td2.rationale || []).map((r, i) => (
                <div key={i} style={{ ...xs, color: 'var(--text-muted)' }}>· {r}</div>
              ))}
              {(td2.dropped_nodes || 0) > 0 && (
                <div style={{ ...xs, color: 'var(--text-muted)' }}>
                  * 입력 심볼 밖이라 폐기한 제안 모듈 {td2.dropped_nodes}개(환각 필터)
                </div>
              )}
            </div>
          ) : (
            <div style={{ ...xs, color: 'var(--text-muted)' }}>
              {REASON_KO[data.enrich_reason] || data.enrich_reason || '목표 구조가 아직 없습니다.'}
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
    </div>
  );
}
