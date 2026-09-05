/**
 * ArchitectureMetricsPanel — 소스 아키텍처 결정론 메트릭(LLM 없이 항상 표시).
 * POST /api/summary/architecture-metrics 소비.
 *
 * Q1: 6블록을 auto-fit 그리드에 늘어놓으니 넓은 화면에서 4열로 벌어져 표가 잘리고, 무엇부터
 * 볼지도 알 수 없었다 → **요약 스트립(숫자 한 줄) + 아코디언 4섹션**으로 재구성한다.
 * 기본 펼침은 '테스트 투자 우선순위' — 유일하게 바로 실행 가능한 목록이기 때문.
 *
 * 정직성: 복잡도 출처(vcast_ccn 측정 vs loc_proxy 추정) 구분 표기, 계층/간섭/전역은 각 note로
 * 한계를 고지(추정≠선언, 사용≠쓰기, 검토 후보≠위반).
 */
import { useEffect, useState } from 'react';
import { fetchArchMetrics } from '../../archMetricsCache.js';
import { HorizontalBar } from '../charts.jsx';
import SummaryPanel from './SummaryPanel.jsx';
import * as T from './summaryTable.js';
import { TABLE, SCROLL } from './summaryTable.js';

const xs = { fontSize: 'var(--text-xs)' };

/** 요약 스트립의 숫자 한 칸. */
function Stat({ label, value, tone, title }) {
  return (
    <div title={title} style={{ minWidth: 88 }}>
      <div style={{ ...xs, color: 'var(--text-muted)' }}>{label}</div>
      {/* 예전엔 `var(--text-md, 14px)` 였는데 --text-md 가 실제 13px 이라 폴백 14px 는 영구히
          발동하지 않았다 → 실제 렌더되던 값(13px)을 그대로 명시한다. 폴백을 살려 14px 로 올리면
          패널 제목 h3(13px)보다 커져 위계가 뒤집힌다. */}
      <div style={{ fontSize: 'var(--text-md)', fontWeight: 700, color: tone || 'var(--text)' }}>{value}</div>
    </div>
  );
}

/** 접이식 상세 섹션 — details/summary라 키보드·스크린리더 동작이 기본 제공된다. */
function Section({ title, desc, defaultOpen, children }) {
  return (
    <details open={defaultOpen} style={{ borderTop: '1px solid var(--border)', paddingTop: 'var(--sp-2)', marginTop: 'var(--sp-2)' }}>
      {/* 섹션 제목이 표 본문(11px)보다 작으면 위계가 뒤집힌다 — 12px/700 로 한 단 올린다
          (패널 h3 13px > 섹션 12px > 표 본문 11px > 각주 10px). */}
      <summary style={{ cursor: 'pointer', fontSize: 'var(--text-base)', fontWeight: 700 }}>
        {title}
        {desc && <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}> — {desc}</span>}
      </summary>
      <div style={{ marginTop: 'var(--sp-2)' }}>{children}</div>
    </details>
  );
}

const COLS = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 'var(--sp-4)' };

export default function ArchitectureMetricsPanel({ jobUrl, cacheRoot, defaultOpen = true, reloadToken = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        // 다이어그램 패널과 **같은 요청**이라 공유 캐시를 거친다(예전엔 두 패널이 각자 POST 했다).
        const resp = await fetchArchMetrics(jobUrl, cacheRoot);
        if (!cancelled) { setData(resp); setError(''); }
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
    // ⚠ reloadToken — 백필로 소스 스냅샷이 바뀌면 부모가 올린다. keep-alive 라 이 패널은
    //   언마운트되지 않아, 이게 없으면 캐시를 비워도 화면이 옛 빌드에 영구히 멈춘다.
  }, [jobUrl, cacheRoot, reloadToken]);

  // 표 서식은 summaryTable 공통 규약 — 본문 11px, 숫자는 우측정렬 tabular-nums,
  // 식별자는 줄바꿈 대신 말줄임(행 높이 균일).
  const { th, td } = T;
  const coupling = data?.coupling || {};
  // v4~v6 블록 — 구 캐시 응답엔 없으므로 옵셔널 접근 후 정직 안내로 폴백한다.
  const intf = data?.asil_interference;
  const gcoup = data?.global_coupling;
  const cc = data?.coverage_complexity;
  const ind = data?.indirect_calls;
  const enc = data?.encapsulation;
  const lay = data?.layer_graph;
  const cycles = (data?.cycles?.file_sccs || []).length;

  return (
    <SummaryPanel
      title="아키텍처 메트릭 (소스 스냅샷)"
      defaultOpen={defaultOpen}
      meta={<>
        {data?.available && data?.snapshot && (
          <span style={{ ...xs, color: 'var(--text-muted)' }}>
            빌드 #{data.build_number} · 파일 {data.snapshot.files} · 함수 {data.snapshot.functions}
          </span>
        )}
        {!data && !error && <span className="spinner" />}
      </>}
    >
      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>아키텍처 메트릭 오류: {error}</div>}
      {data && data.available === false && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          {data.reason === 'no_source_snapshot' ? '캐시 빌드에 소스 스냅샷이 없어 계산할 수 없습니다.'
            : `아키텍처 메트릭을 계산할 수 없습니다 (${data.reason})`}
        </div>
      )}

      {data?.available && (
        <>
          {/* 요약 스트립 — 먼저 숫자만 한 줄로 주고, 상세는 아래 아코디언에서 필요한 것만 연다. */}
          <div style={{
            display: 'flex', flexWrap: 'wrap', gap: 'var(--sp-3)',
            padding: 'var(--sp-2)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
          }}>
            <Stat label="핫스팟" value={(data.hotspots || []).length} />
            <Stat label="파일 간 결합" value={coupling.cross_file_call_ratio != null ? `${Math.round(coupling.cross_file_call_ratio * 100)}%` : '—'} />
            <Stat label="순환" value={cycles} tone={cycles > 0 ? 'var(--color-warning)' : undefined} />
            <Stat label="계층 역방향" value={lay?.available ? lay.reverse_total : '—'}
              tone={(lay?.reverse_total ?? 0) > 0 ? 'var(--color-warning)' : undefined}
              title="하위 계층이 상위를 호출 — 계층화 검토 후보(위반 단정 아님)" />
            <Stat label="ASIL 간섭" value={intf?.available ? intf.edges_total : '—'}
              title="등급이 다른 함수 간 호출 — freedom from interference 검토 후보" />
            <Stat label="모듈경계 공유 전역" value={gcoup?.available ? gcoup.cross_module_globals : '—'} />
            <Stat label="고복잡×저커버" value={cc?.available ? (cc.counts?.high_complex_low_cov ?? 0) : '—'}
              tone={(cc?.counts?.high_complex_low_cov ?? 0) > 0 ? 'var(--color-danger)' : undefined} />
          </div>

          {/* ② 기본 펼침 — 유일하게 바로 실행 가능한 목록 */}
          <Section title="테스트 투자 우선순위" desc="고복잡도 × 저커버리지" defaultOpen>
            {cc?.available ? (
              <>
                <div style={{ ...xs, marginBottom: 4 }}>
                  조인 {cc.joined}함수(미조인 {cc.unjoined}) · 임계 복잡도 {cc.complexity_threshold}
                  {cc.complexity_basis === 'loc_proxy' && <span title="측정 ccn이 없어 라인수 프록시 기준"> (추정 기준)</span>}
                  {' · '}고복잡·저커버 <b style={{ color: 'var(--color-danger)' }}>{cc.counts?.high_complex_low_cov ?? 0}</b>
                </div>
                <div style={SCROLL}>
                  <table style={TABLE}>
                    <thead><tr><th style={th}>함수</th><th style={T.numTh}>구문</th><th style={T.numTh}>복잡도</th></tr></thead>
                    <tbody>
                      {(cc.priority || []).slice(0, 10).map((p) => (
                        <tr key={p.function}>
                          <td style={T.nameTd(240)} title={`${p.function} — ${p.file}`}>{p.function}</td>
                          <td style={{ ...T.numTd, color: 'var(--color-danger)', fontWeight: 600 }}>{Math.round(p.statement * 100)}%</td>
                          <td style={T.numTd}>{p.complexity}{p.complexity_source === 'vcast_ccn' ? '' : '≈'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 2 }}>* {cc.note}</div>
              </>
            ) : (
              <div style={{ ...xs, color: 'var(--text-muted)' }}>함수 커버리지 인덱스가 없어 사분면을 낼 수 없습니다.</div>
            )}
          </Section>

          {/* ① 핫스팟 · 대형 함수 */}
          <Section title="핫스팟 · 대형 함수" desc="변경 파급이 큰 함수">
            <div style={COLS}>
              <div>
                <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>핫스팟 (fan-in × 복잡도)</div>
                <div style={SCROLL}>
                  <table style={TABLE}>
                    <thead>
                      <tr><th style={th}>함수</th><th style={T.numTh}>fan-in</th><th style={T.numTh}>복잡도</th><th style={T.numTh}>점수</th></tr>
                    </thead>
                    <tbody>
                      {(data.hotspots || []).slice(0, 8).map((h) => (
                        <tr key={h.function}>
                          <td style={T.nameTd(240)} title={`${h.function} — ${h.file}`}>{h.function}</td>
                          <td style={T.numTd}>{h.fan_in}</td>
                          <td style={T.numTd}>
                            {h.complexity}
                            <span style={{ color: 'var(--text-muted)' }} title={h.complexity_source === 'vcast_ccn' ? 'VectorCAST 측정 순환복잡도' : '본문 라인수 추정(측정 아님)'}>
                              {h.complexity_source === 'vcast_ccn' ? '' : '≈'}
                            </span>
                          </td>
                          <td style={{ ...T.numTd, fontWeight: 600 }}>{h.score}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 2 }}>≈ 표시는 복잡도 추정(라인수 프록시 — VectorCAST 미측정 함수)</div>
              </div>
              <div>
                <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>대형 함수 (본문 라인)</div>
                {(() => {
                  const rows = (data.size_outliers || []).slice(0, 6);
                  const max = Math.max(...rows.map((r) => r.lines || 0), 1);
                  return rows.map((r) => (
                    <HorizontalBar key={r.function} label={r.function} value={r.lines || 0} max={max} color="var(--color-warning)" />
                  ));
                })()}
              </div>
            </div>
          </Section>

          {/* ③ 결합도 · 공유 전역 */}
          <Section title="결합도 · 공유 전역" desc="파일 간 호출과 모듈 경계를 넘는 데이터">
            <div style={COLS}>
              <div>
                <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>
                  파일 간 결합 — cross-file 호출 비율 {coupling.cross_file_call_ratio != null ? `${Math.round(coupling.cross_file_call_ratio * 100)}%` : '—'}
                  {coupling.edges != null && ` (${coupling.cross_edges}/${coupling.edges} 호출)`}
                </div>
                {(() => {
                  const pairs = (coupling.top_pairs || []).slice(0, 6);
                  const max = Math.max(...pairs.map((p) => p.calls || 0), 1);
                  return pairs.map((p) => (
                    <HorizontalBar key={`${p.from_file}->${p.to_file}`}
                      label={`${String(p.from_file).split('/').pop()} → ${String(p.to_file).split('/').pop()}`}
                      value={p.calls || 0} max={max} color="var(--color-purple, var(--accent))" />
                  ));
                })()}
              </div>
              <div>
                <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>공유 전역 데이터 (모듈 경계 넘는 참조)</div>
                {gcoup?.available ? (
                  <>
                    <div style={{ ...xs, marginBottom: 4 }}>
                      전역 {gcoup.distinct_globals}개 중 <b>{gcoup.cross_module_globals}</b>개가 2개 이상 모듈에서 참조
                    </div>
                    {(() => {
                      const rows = (gcoup.top || []).slice(0, 6);
                      const max = Math.max(...rows.map((r) => r.functions || 0), 1);
                      return rows.map((r) => (
                        <HorizontalBar key={r.global} label={`${r.global} (${r.modules}모듈)`}
                          value={r.functions || 0} max={max} color="var(--color-info)" />
                      ));
                    })()}
                    <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 2 }}>* {gcoup.note}</div>
                  </>
                ) : (
                  <div style={{ ...xs, color: 'var(--text-muted)' }}>전역 참조가 관측되지 않았습니다.</div>
                )}
              </div>
            </div>
          </Section>

          {/* ④ ASIL 간섭 · 콜그래프 완전성 */}
          <Section title="ASIL 간섭 · 콜그래프 완전성" desc="안전 등급 상이 호출과 그래프 한계">
            <div style={COLS}>
              <div>
                <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>ASIL 간섭 검토 후보 (freedom from interference)</div>
                {intf?.available ? (
                  <>
                    <div style={{ ...xs, marginBottom: 4 }}>
                      등급 보유 함수 {intf.graded_functions} · 등급 상이 호출 <b>{intf.edges_total}</b>건
                      {' · '}등급 혼재 모듈 <b>{intf.mixed_modules}</b>개
                    </div>
                    <div style={SCROLL}>
                      <table style={TABLE}>
                        <thead><tr><th style={th}>상위 등급</th><th style={th}>→ 하위/미상</th><th style={th}>모듈 경계</th></tr></thead>
                        <tbody>
                          {(intf.edges || []).slice(0, 6).map((e) => (
                            <tr key={`${e.caller}->${e.callee}`}>
                              <td style={T.nameTd(220)} title={`${e.caller} — ${e.caller_file}`}>{e.caller} <b>{e.caller_asil || '미상'}</b></td>
                              <td style={T.nameTd(220)} title={`${e.callee} — ${e.callee_file}`}>{e.callee} <b>{e.callee_asil || '미상'}</b></td>
                              <td style={td}>{e.cross_module ? '넘음' : '내부'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 2 }}>* {intf.note}</div>
                  </>
                ) : (
                  <div style={{ ...xs, color: 'var(--text-muted)' }}>
                    함수 ASIL 등급 정보가 없어 간섭 검토 후보를 낼 수 없습니다(주석·요구 역전파 모두 부재).
                  </div>
                )}
              </div>
              <div>
                <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>콜그래프 완전성 · 캡슐화</div>
                {/* ⚠ 원시 탐지량(func_ref_*)을 '함수포인터 보유'로 읽으면 안 된다 — 실측 2,708건 중
                    실제 함수는 2건이고 나머지는 DDRADL 같은 MCU 레지스터다. 걸러낸 값을 앞세우고
                    원시량은 오탐 규모와 함께 뒤에 둔다. v6 이하 캐시는 걸러낸 값이 없어 구 표기로 폴백. */}
                {ind && (ind.resolved_ref_functions != null ? (
                  <div style={{ ...xs, marginBottom: 4 }}>
                    간접 호출 사이트 보유 함수 <b>{ind.pointer_call_functions}</b>
                    {' · '}함수 주소 참조 <b>{ind.resolved_ref_functions}</b>
                    {' — '}<span style={{ color: 'var(--color-warning)' }}>위 fan-in/사이클에 미반영</span>
                    <div style={{ color: 'var(--text-muted)' }}>
                      * 원시 탐지 {ind.func_ref_functions}함수/{ind.reference_edges}건 중{' '}
                      {ind.unresolved_ref_edges}건은 레지스터·변수 참조(함수 아님)라 시임 후보에서 제외
                    </div>
                  </div>
                ) : (
                  <div style={{ ...xs, marginBottom: 4 }}>
                    함수포인터/간접 호출 보유 함수 <b>{ind.functions_with_indirect}</b>
                    {' · '}참조 엣지 {ind.reference_edges}건 — <span style={{ color: 'var(--color-warning)' }}>위 fan-in/사이클에 미반영</span>
                  </div>
                ))}
                {(ind?.top || []).slice(0, 4).map((t) => (
                  <div key={t.function} style={{ ...xs, color: 'var(--text-muted)' }} title={t.file}>
                    · {t.function}
                    {(t.pointer_symbols || []).length > 0
                      ? <> — <span style={{ fontFamily: 'monospace' }}>{t.pointer_symbols.join(', ')}</span></>
                      : (t.ref_functions || []).length > 0
                        ? <> — <span style={{ fontFamily: 'monospace' }}>{t.ref_functions.join(', ')}</span></>
                        : ` — 참조 ${t.func_refs} / 간접호출 ${t.pointer_calls}`}
                  </div>
                ))}
                {enc && (
                  <div style={{ ...xs, marginTop: 'var(--sp-2)' }}>
                    함수 {enc.functions} · 헤더 정의 {enc.header_defined_functions}
                    {enc.documented_ratio != null && ` · 문서화 ${Math.round(enc.documented_ratio * 100)}%`}
                    <div style={{ color: 'var(--text-muted)' }}>* {enc.note}</div>
                  </div>
                )}
              </div>
            </div>
          </Section>
        </>
      )}
    </SummaryPanel>
  );
}
