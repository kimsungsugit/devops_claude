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
import { Fragment, useEffect, useState } from 'react';
import { post } from '../../api.js';
import SummaryPanel from './SummaryPanel.jsx';
import * as T from './summaryTable.js';
import { TABLE, SCROLL } from './summaryTable.js';

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

const code = {
  ...xs, fontFamily: 'monospace', whiteSpace: 'pre', overflowX: 'auto',
  background: 'var(--bg-subtle)', border: '1px solid var(--border)',
  borderRadius: 'var(--radius-sm)', padding: '6px 8px', margin: 0, lineHeight: 1.5,
};

/** 상세 개선안 — "무엇을"만 있던 후보에 "어디를 어떻게"를 붙인다(서버 결정론 산출). */
function PlaybookDetail({ detail }) {
  if (!detail) return null;
  const { steps = [], sketch, stub_plan: stub, split_proposal: split, impact, caveats = [] } = detail;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-2)', padding: 'var(--sp-2) 0' }}>
      <div style={{ ...xs, fontWeight: 600 }}>{detail.summary}</div>

      {steps.length > 0 && (
        <ol style={{ ...xs, margin: 0, paddingLeft: '1.4em', lineHeight: 1.7 }}>
          {steps.map((s, i) => <li key={i}>{s}</li>)}
        </ol>
      )}

      {/* 분할 제안 — 어느 함수가 어느 파일로 가는지가 이 후보의 본체다 */}
      {(split || []).length > 0 && (
        <div>
          <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 3 }}>분할 제안</div>
          {split.map((p) => (
            <div key={p.file} style={{
              ...xs, border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
              padding: '3px 8px', marginBottom: 3,
            }}>
              <b style={{ fontFamily: 'monospace' }}>{p.file}</b>
              <span style={{ color: 'var(--text-muted)' }}> · 함수 {p.size}개</span>
              {(p.functions || []).length > 0 && (
                <div style={{ color: 'var(--text-muted)', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                  {p.functions.join(', ')}{p.size > p.functions.length ? ` … 외 ${p.size - p.functions.length}개` : ''}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {sketch && (
        <div>
          <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 3 }}>
            코드 스케치 <span style={{ color: 'var(--color-warning)' }}>— {sketch.note}</span>
          </div>
          <div style={{ display: 'flex', gap: 'var(--sp-2)', flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 280 }}>
              <div style={{ ...xs, color: 'var(--text-muted)' }}>현재</div>
              <pre style={code}>{sketch.before}</pre>
            </div>
            <div style={{ flex: 1, minWidth: 280 }}>
              <div style={{ ...xs, color: 'var(--color-success)' }}>제안</div>
              <pre style={{ ...code, borderColor: 'var(--color-success)' }}>{sketch.after}</pre>
            </div>
          </div>
        </div>
      )}

      {stub && (
        <div style={{ ...xs, border: '1px solid var(--border)', borderLeft: '3px solid var(--color-info)',
          borderRadius: 'var(--radius-sm)', padding: '4px 8px' }}>
          <b>시험 스텁 계획</b>
          <ul style={{ margin: '2px 0', paddingLeft: '1.2em' }}>
            {(stub.what || []).map((w, i) => <li key={i} style={{ fontFamily: 'monospace' }}>{w}</li>)}
          </ul>
          <div style={{ color: 'var(--text-muted)' }}>{stub.gain}</div>
        </div>
      )}

      {impact && Object.keys(impact).length > 0 && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          영향 — {Object.entries(impact)
            .filter(([, v]) => v != null && !(Array.isArray(v) && v.length === 0))
            .map(([k, v]) => `${IMPACT_KO[k] || k} ${Array.isArray(v) ? v.join(' · ') : v}`)
            .join(' | ')}
        </div>
      )}

      {caveats.map((c, i) => (
        <div key={i} style={{ ...xs, color: 'var(--color-warning)' }}>⚠ {c}</div>
      ))}
    </div>
  );
}

const IMPACT_KO = {
  files_in_cycle: '순환 파일', edge_call_sites: '이 간선 호출',
  other_pairs: '같은 간선의 다른 호출', functions: '함수',
  components: '내부 덩어리', largest_component_share: '최대 덩어리 비중',
  axis: '분할 축', groups: '군집', cut_calls: '군집 간 호출',
  max_share: '최대 군집 비중', cover: '설명 범위', basis: '근거',
  file: '파일', caller_file: '호출 파일', reverse_pairs_total: '역방향',
  sample_functions: '참조 함수', pointer_symbols: '포인터', ref_functions: '참조 함수',
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

export default function ArchitectureImprovementPanel({ jobUrl, cacheRoot, defaultOpen = true, reloadToken = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState('all');
  // 여러 행을 동시에 펼쳐 비교할 수 있게 Set — 후보끼리 조치가 겹치는지 보려면 나란히 봐야 한다.
  const [expanded, setExpanded] = useState(() => new Set());
  const toggle = (key) => setExpanded((prev) => {
    const next = new Set(prev);
    if (!next.delete(key)) next.add(key);
    return next;
  });

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
    // ⚠ reloadToken — 백필로 소스 스냅샷이 바뀌면 부모가 올린다. keep-alive 라 이 패널은
    //   언마운트되지 않아, 이게 없으면 캐시를 비워도 화면이 옛 빌드에 영구히 멈춘다.
  }, [jobUrl, cacheRoot, reloadToken]);

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

  // ⚠ 예전 로컬 td 에는 nowrap 이 없어 '대상/조치/근거'가 폭에 따라 두세 줄로 접히고
  //   행 높이가 제각각이 됐다. 공통 규약으로 축을 나눈다: 식별자=말줄임, 문장=폭 제한 줄바꿈.
  const { th, td } = T;
  const cands = (data?.candidates || []).filter((c) => (
    filter === 'all' ? true : filter === 'test' ? TESTABILITY.has(c.kind) : !TESTABILITY.has(c.kind)
  ));
  const td2 = data?.target_design;

  return (
    <SummaryPanel
      title="아키텍처 개선 제안 (To-Be)"
      defaultOpen={defaultOpen}
      meta={<>
        {data?.available && (
          <span style={{ ...xs, color: 'var(--text-muted)' }}>
            빌드 #{data.build_number} · 후보 {data.summary?.total ?? 0}건
            (구조 {data.summary?.structural ?? 0} · 테스트 용이성 {data.summary?.testability ?? 0})
            {(data.summary?.omitted ?? 0) > 0 && ` · 표시 상한으로 ${data.summary.omitted}건 생략`}
          </span>
        )}
        {busy && <span className="spinner" />}
      </>}
      actions={data?.available && (data.summary?.total ?? 0) > 0 ? (
        <button type="button" style={btn} onClick={() => generate(Boolean(td2))} disabled={busy}>
          {busy ? '생성 중…' : td2 ? '목표 구조 재생성' : '목표 구조 생성 (AI)'}
        </button>
      ) : undefined}
    >
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
              {/* 사용자가 표만 보고 "뭘 하라는 건지 모르겠다"고 한 지점 — 상세가 어디 있는지 먼저 알린다 */}
              <div style={{ ...xs, color: 'var(--text-muted)' }}>
                왼쪽 <b>▸</b>를 누르면 <b>어느 함수를 어떻게 바꾸는지</b> — 단계·코드 스케치·시험 스텁 계획이 나옵니다.
                {data.playbook && data.playbook.without_detail > 0
                  && ` (${data.playbook.total}건 중 ${data.playbook.without_detail}건은 상세 재료 없음)`}
              </div>
              <div style={SCROLL}>
                <table style={TABLE}>
                  <thead>
                    <tr>
                      <th style={{ ...th, width: 24 }} aria-label="상세" />
                      <th style={th}>종류</th><th style={th}>대상</th><th style={th}>조치</th><th style={th}>근거</th><th style={{ ...th, textAlign: 'center' }}>비용</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cands.map((c) => {
                      const key = `${c.kind}:${c.target}`;
                      const open = expanded.has(key);
                      return (
                        <Fragment key={key}>
                          <tr>
                            <td style={{ ...td, padding: '4px 2px' }}>
                              {c.detail ? (
                                /* 기호(▸)는 스크린리더에 무의미하다 — 이름을 aria-label 로 준다 */
                                <button type="button" onClick={() => toggle(key)} aria-expanded={open}
                                  aria-label={open ? `${c.target} 상세 접기` : `${c.target} 상세 개선안 펼치기`}
                                  title={open ? '상세 접기' : '상세 개선안 펼치기'}
                                  style={{ ...btn, padding: '0 4px', border: 'none' }}>
                                  {open ? '▾' : '▸'}
                                </button>
                              ) : (
                                /* 재료가 없어 상세를 못 만든 후보 — 빈 상세를 지어내지 않는다 */
                                <span style={{ ...xs, color: 'var(--text-muted)' }} title="상세를 만들 재료가 없습니다(스냅샷 재분석 필요)">–</span>
                              )}
                            </td>
                            <td style={td}>
                              <span style={{ fontWeight: 600, color: KIND_KO[c.kind]?.color || 'var(--text-muted)' }}>
                                {KIND_KO[c.kind]?.label || c.kind}
                              </span>
                            </td>
                            <td style={{ ...T.nameTd(230), fontFamily: 'monospace' }}
                              title={`${c.target}${(c.files || []).length ? ` — ${(c.files || []).join(', ')}` : ''}`}>{c.target}</td>
                            <td style={T.textTd(300)}>{c.action}</td>
                            <td style={{ ...T.textTd(280), color: 'var(--text-muted)' }}>{c.basis}</td>
                            <td style={{ ...td, textAlign: 'center' }}>{EFFORT_KO[c.effort] || c.effort}</td>
                          </tr>
                          {open && (
                            <tr>
                              <td colSpan={6} style={{ ...td, background: 'var(--bg-subtle)' }}>
                                <PlaybookDetail detail={c.detail} />
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
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
    </SummaryPanel>
  );
}
