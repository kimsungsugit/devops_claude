/**
 * TestDesignPanel — 테스트 설계 어드바이저(L2). POST /api/summary/test-design(결정론) 소비.
 * ①MC/DC 미측정 배너(미측정≠미달) ②기법 권고 테이블(ASIL×커버리지×ccn — ISO 26262-6 표
 * 참조 가이드, 심사 판정 아님) ③설계-시험 갭(band_missing이면 열거 억제 — 증거부재≠갭)
 * ④기법 카탈로그 범례. coverage_join 캡션으로 SwUFn-키 조인 함정을 표면화.
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { post } from '../../api.js';
import * as T from './summaryTable.js';

const xs = { fontSize: 'var(--text-xs)' };

const GAP_KO = {
  changed_uncovered: { label: '변경·미커버', color: 'var(--color-danger)' },
  changed_below_target: { label: '변경·미달', color: 'var(--color-danger)' },
  uncovered: { label: '미커버', color: 'var(--color-danger)' },
  unmeasured_metric: { label: 'MC/DC 미측정', color: 'var(--color-warning)' },
  below_target: { label: '목표 미달', color: 'var(--color-danger)' },
  branch_gap: { label: '분기 갭', color: 'var(--color-warning)' },
  statement_gap: { label: '구문 갭', color: 'var(--color-warning)' },
  // 통합(IT) 축 — 단위 커버리지 목표와 기준이 달라 별도 라벨·중립 색
  it_entry_gap: { label: 'IT 진입 갭', color: 'var(--color-info)' },
  it_not_exercised: { label: 'IT 미실행', color: 'var(--text-muted)' },
  it_partial: { label: 'IT 부분', color: 'var(--text-muted)' },
};

const ROW_FILTERS = [
  { key: 'all', label: '전체' },
  { key: 'changed', label: '변경분만' },
  { key: 'safety', label: 'ASIL C·D만' },
  { key: 'uncovered', label: '미커버만' },
  { key: 'it', label: '통합(IT)만' },
];

/** 케이스 초안 블록 — on-demand 생성 결과(결정론 골격 + AI 케이스 표). */
function CaseDraft({ draft, colSpan, td, th }) {
  if (!draft) return null;
  if (draft.error) {
    return <tr><td colSpan={colSpan} style={{ ...td, color: 'var(--color-danger)' }}>초안 생성 오류: {draft.error}</td></tr>;
  }
  if (draft.available === false) {
    return (
      <tr><td colSpan={colSpan} style={{ ...td, color: 'var(--text-muted)' }}>
        초안을 만들 수 없습니다 ({draft.reason})
        {draft.candidates?.length > 0 && ` — 후보 파일: ${draft.candidates.join(', ')}`}
      </td></tr>
    );
  }
  const det = draft.deterministic || {};
  return (
    <tr>
      <td colSpan={colSpan} style={{ ...td, background: 'var(--hover, transparent)', whiteSpace: 'normal' }}>
        <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>
          {draft.file && <span title="소스 스냅샷 경로">{draft.file} · </span>}
          권고 기법 {(det.techniques || []).map((t) => t.label).join(', ') || '—'}
          {det.suggested_min_cases != null && ` · 분기 커버 최소 TC 추정 ${det.suggested_min_cases}(McCabe 근사, 측정값 아님)`}
          {det.coverage?.mcdc_state === 'unmeasured' && ' · MC/DC 미측정'}
          {draft.dropped_cases > 0 && ` · 근거 부족으로 폐기된 케이스 ${draft.dropped_cases}건`}
        </div>
        {(det.boundary_candidates || []).length > 0 && (
          <div style={{ ...xs, marginBottom: 4 }}>
            경계값 후보: {(det.boundary_candidates || []).map((b) => `${b.param}(${b.candidates.join('/')})`).join(' · ')}
          </div>
        )}
        {(draft.cases || []).length > 0 ? (
          <table style={{ borderCollapse: 'collapse', width: '100%' }}>
            <thead>
              <tr>
                <th style={th}>ID</th><th style={th}>목적</th><th style={th}>전제</th>
                <th style={th}>입력</th><th style={th}>기대</th><th style={th}>커버 대상</th>
              </tr>
            </thead>
            <tbody>
              {draft.cases.map((c) => (
                <tr key={c.id}>
                  <td style={td}>{c.id}</td>
                  <td style={{ ...td, whiteSpace: 'normal' }}>{c.purpose}</td>
                  <td style={{ ...td, whiteSpace: 'normal' }}>{c.preconditions || '—'}</td>
                  <td style={{ ...td, whiteSpace: 'normal', fontFamily: 'monospace' }}>{c.inputs}</td>
                  <td style={{ ...td, whiteSpace: 'normal' }}>{c.expected}</td>
                  <td style={{ ...td, whiteSpace: 'normal', color: 'var(--text-muted)' }}>{c.covers}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div style={{ ...xs, color: 'var(--text-muted)' }}>
            AI 케이스 없음 ({draft.enrich_reason || '사유 미상'}) — 위 결정론 권고를 근거로 직접 설계하세요.
          </div>
        )}
        {(draft.notes || []).map((n, i) => (
          <div key={i} style={{ ...xs, color: 'var(--text-muted)' }}>· {n}</div>
        ))}
        <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 4 }}>
          ⚠ {draft.note}
          {draft.model && ` · 모델 ${draft.model}`}{draft.cached ? ' · 캐시됨' : ''}
        </div>
      </td>
    </tr>
  );
}

function AsilPill({ asil }) {
  if (!asil) return <span style={{ ...xs, color: 'var(--text-muted)' }}>미상</span>;
  const hot = asil === 'C' || asil === 'D';
  return (
    <span style={{
      ...xs, padding: '0 6px', borderRadius: 'var(--radius-sm)', fontWeight: 700,
      color: '#fff', background: hot ? 'var(--color-danger)' : 'var(--color-info)',
    }}>{asil}</span>
  );
}

export default function TestDesignPanel({ jobUrl, cacheRoot }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [showCatalog, setShowCatalog] = useState(false);
  const [rowFilter, setRowFilter] = useState('all');
  const [drafts, setDrafts] = useState({});   // key(unit:function) → 초안 응답 | {loading} | {error}

  // drafts를 deps에 포함 — 토글 판정이 현재 상태를 봐야 한다(stale closure 방지).
  const requestDraft = useCallback(async (item) => {
    const key = `${item.unit || ''}:${item.function}`;
    if (drafts[key]) {                       // 열려 있으면 접는다(재요청 없음 — 캐시는 서버가 관리)
      setDrafts((prev) => {
        const next = { ...prev };
        delete next[key];
        return next;
      });
      return;
    }
    setDrafts((prev) => ({ ...prev, [key]: { loading: true } }));
    try {
      const resp = await post('/api/summary/test-case-draft', {
        job_url: jobUrl, cache_root: cacheRoot, function: item.function, unit: item.unit,
      });
      setDrafts((prev) => ({ ...prev, [key]: resp }));
    } catch (e) {
      setDrafts((prev) => ({ ...prev, [key]: { error: String(e?.message || e) } }));
    }
  }, [jobUrl, cacheRoot, drafts]);

  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const resp = await post('/api/summary/test-design', { job_url: jobUrl, cache_root: cacheRoot });
        if (!cancelled) { setData(resp); setError(''); }
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot]);

  // 표 서식은 summaryTable 공통 규약 — 본문 11px · 숫자 우측정렬(tabular-nums) ·
  // 식별자는 줄바꿈 대신 말줄임. 패널마다 따로 정의하면 한 탭 안에서 표가 서로 달라 보인다.
  const { th, td } = T;
  const tech = data?.technique_recommendations;
  const gap = data?.design_test_gap;
  const visibleItems = useMemo(() => {
    const items = tech?.items || [];
    if (rowFilter === 'changed') return items.filter((i) => i.changed);
    if (rowFilter === 'safety') return items.filter((i) => i.asil === 'C' || i.asil === 'D');
    if (rowFilter === 'uncovered') return items.filter((i) => String(i.gap_kind || '').includes('uncovered'));
    if (rowFilter === 'it') return items.filter((i) => i.metric_set === 'it');
    return items;
  }, [tech, rowFilter]);
  const catalog = data?.catalog || {};
  const techLabel = (id) => catalog[id]?.label || id;

  return (
    <div className="panel" style={{ padding: 'var(--sp-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>테스트 설계 어드바이저 (ISO 26262-6 기법 가이드)</div>
        {data?.available && <span style={{ ...xs, color: 'var(--text-muted)' }}>빌드 #{data.build_number} · 심사 판정 아님</span>}
        {!data && !error && <span className="spinner" />}
      </div>

      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>테스트 설계 조회 오류: {error}</div>}
      {data && data.available === false && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          {data.reason === 'no_cached_build' ? '캐시된 빌드가 없습니다.' : `계산할 수 없습니다 (${data.reason})`}
        </div>
      )}

      {data?.available && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
          {data.mcdc_note && (
            <div style={{ ...xs, borderLeft: '3px solid var(--color-warning)', padding: '4px 8px', color: 'var(--text-muted)' }}>
              ⚠ {data.mcdc_note}
            </div>
          )}

          <div>
            {tech?.available ? (
              <>
                <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>
                  기법 권고 — 단위(UT) 갭 {(
                    (tech.summary?.uncovered || 0) + (tech.summary?.unmeasured_metric || 0)
                    + (tech.summary?.below_target || 0)
                  )}건 관측
                  {(tech.summary?.it_gap || 0) > 0 && (
                    <span title="통합 시나리오에서 실행되지 않은 함수 — 단위 시험 부재와 다른 축입니다">
                      {' · 통합(IT) 축 '}{tech.summary.it_gap}건
                    </span>
                  )}
                  {(tech.summary?.changed_with_gap || 0) > 0 && (
                    <b style={{ color: 'var(--color-danger)' }}> · 변경 함수 갭 {tech.summary.changed_with_gap}건</b>
                  )}
                  {' · '}커버리지 {tech.coverage_join?.entries}행(UT {tech.coverage_join?.ut_rows ?? '—'} / IT {tech.coverage_join?.it_rows ?? '—'})
                  {' 중 ASIL 조인 '}{tech.coverage_join?.with_asil}건
                  (미상 {tech.coverage_join?.asil_unknown} — 미상은 QM 단정 안 함)
                  {tech.asil_source && ` · ASIL 출처 ${tech.asil_source === 'uds_link' ? '요구 역전파' : tech.asil_source}`}
                  {tech.changed_axis?.available
                    ? ` · 변경 축: #${tech.changed_axis.baseline_build}→#${tech.changed_axis.target_build} (${tech.changed_axis.count}함수)`
                    : ' · 변경 축 비활성(베이스라인 비교 캐시 없음)'}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 4 }}>
                  {ROW_FILTERS.map((f) => (
                    <button key={f.key} type="button" onClick={() => setRowFilter(f.key)}
                      aria-pressed={rowFilter === f.key}
                      style={{
                        ...xs, padding: '1px 8px', borderRadius: 'var(--radius-sm)', cursor: 'pointer',
                        border: `1px solid ${rowFilter === f.key ? 'var(--accent)' : 'var(--border)'}`,
                        background: rowFilter === f.key ? 'var(--accent)' : 'transparent',
                        color: rowFilter === f.key ? '#fff' : 'var(--text-muted)',
                      }}>
                      {f.label}
                    </button>
                  ))}
                  <span style={{ ...xs, color: 'var(--text-muted)' }}>표시 {visibleItems.length}건</span>
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                    <thead>
                      <tr><th style={th}>함수</th><th style={th}>유닛</th><th style={th}>ASIL</th><th style={th}>갭</th><th style={th}>권고 기법</th><th style={th}>근거</th><th style={th}>케이스</th></tr>
                    </thead>
                    <tbody>
                      {visibleItems.slice(0, 20).map((i) => {
                        const key = `${i.unit || ''}:${i.function}`;
                        const draft = drafts[key];
                        return (
                          <Fragment key={key}>
                            <tr>
                              <td style={td}>
                                {i.changed && <span title="이번 베이스라인 구간에서 변경된 함수" style={{ color: 'var(--color-danger)', fontWeight: 700 }}>● </span>}
                                {i.function}
                              </td>
                              <td style={{ ...td, color: 'var(--text-muted)' }}>
                                {i.unit}{i.metric_set === 'it' && <span title="통합 시험 측정"> (IT)</span>}
                              </td>
                              <td style={td}><AsilPill asil={i.asil} /></td>
                              <td style={td}>
                                <span style={{ ...xs, fontWeight: 600, color: GAP_KO[i.gap_kind]?.color || 'var(--text-muted)' }}>
                                  {GAP_KO[i.gap_kind]?.label || i.gap_kind}
                                </span>
                              </td>
                              <td style={{ ...td, whiteSpace: 'normal' }}>
                                {(i.techniques || []).map((t) => (
                                  <span key={t} title={`${catalog[t]?.iso_ref || ''} — ${catalog[t]?.when || ''}`}
                                    style={{ ...xs, display: 'inline-block', margin: '1px 3px 1px 0', padding: '0 6px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}>
                                    {techLabel(t)}
                                  </span>
                                ))}
                              </td>
                              <td style={{ ...td, color: 'var(--text-muted)', whiteSpace: 'normal' }}>{i.basis}</td>
                              <td style={td}>
                                <button type="button" onClick={() => requestDraft(i)}
                                  aria-expanded={Boolean(draft)}
                                  aria-label={`${i.function} 케이스 초안 ${draft ? '접기' : '생성'}`}
                                  style={{ ...xs, padding: '1px 7px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}>
                                  {draft?.loading ? '생성 중…' : draft ? '접기' : '케이스 초안'}
                                </button>
                              </td>
                            </tr>
                            {draft && !draft.loading && <CaseDraft draft={draft} colSpan={7} td={td} th={th} />}
                          </Fragment>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {(tech.items_omitted || 0) > 0 && (
                  <div style={{ ...xs, color: 'var(--text-muted)' }}>표시 상한으로 {tech.items_omitted}건 생략</div>
                )}
              </>
            ) : (
              <div style={{ ...xs, color: 'var(--text-muted)' }}>이 빌드에 함수단위 커버리지가 없어 기법 권고를 만들 수 없습니다.</div>
            )}
          </div>

          <div>
            {gap?.available ? (
              <>
                <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>
                  설계-시험 갭 — UDS 설계 요구 {gap.totals?.targets_with_uds} · 설계 함수 {gap.totals?.uds_functions_distinct}
                  · SUTS 시험 {gap.totals?.suts_tests_distinct} · VCAST 실행 {gap.totals?.vcast_functions_distinct}
                </div>
                {gap.band_missing?.suts ? (
                  <div style={{ ...xs, color: 'var(--text-muted)' }}>
                    SUTS 링크 밴드 자체가 없음 — 갭이 아니라 증거 부재라 요구별 열거를 하지 않습니다.
                  </div>
                ) : (
                  <div style={xs}>
                    UDS 설계는 있는데 SUTS 시험 링크 없음: <b>{(gap.targets_with_uds_no_suts || []).length}</b>건
                    {(gap.no_suts_omitted || 0) > 0 && ` (+${gap.no_suts_omitted} 생략)`}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 2 }}>
                      {(gap.targets_with_uds_no_suts || []).slice(0, 20).map((t) => (
                        <span key={t.target_id} title={`UDS 함수 ${t.uds_count}개`}
                          style={{ ...xs, padding: '0 6px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}>
                          {t.target_id}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {(gap.targets_with_uds_no_any_test || []).length > 0 && (
                  <div style={{ ...xs, marginTop: 4 }}>
                    존재하는 시험 밴드 기준, 어떤 시험 링크도 없음: <b>{gap.targets_with_uds_no_any_test.length}</b>건
                    {(gap.no_any_omitted || 0) > 0 && ` (+${gap.no_any_omitted} 생략)`}
                  </div>
                )}
                <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 2 }}>* {gap.note}</div>
              </>
            ) : (
              <div style={{ ...xs, color: 'var(--text-muted)' }}>이 빌드에 추적성 링크 테이블(trace_link_table)이 없어 설계-시험 갭을 판정하지 않습니다.</div>
            )}
          </div>

          <div>
            <button type="button" onClick={() => setShowCatalog(!showCatalog)}
              style={{ ...xs, padding: '1px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}>
              {showCatalog ? '▾' : '▸'} 기법 카탈로그 (ISO 26262-6 참조)
            </button>
            {showCatalog && (
              <table style={{ borderCollapse: 'collapse', marginTop: 4 }}>
                <tbody>
                  {Object.entries(catalog).map(([id, c]) => (
                    <tr key={id}>
                      <td style={{ ...td, fontWeight: 600 }}>{c.label}</td>
                      <td style={{ ...td, color: 'var(--text-muted)' }}>{c.iso_ref}</td>
                      <td style={{ ...td, whiteSpace: 'normal', color: 'var(--text-muted)' }}>{c.when}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
