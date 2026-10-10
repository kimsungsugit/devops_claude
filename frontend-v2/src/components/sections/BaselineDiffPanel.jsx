/**
 * BaselineDiffPanel — 베이스라인→최신 소스 스냅샷 직접 비교(영향분석 이력 완전 비의존).
 * POST /api/summary/baseline-diff(파일 sha1 + 함수 파서 권위 분류) + 같은 쌍
 * POST /api/jenkins/prqa-delta(1차 확장 API의 baseline_build_number 재사용) 병행 표시.
 *
 * N3: 수정 파일 행을 펼치면 **그 파일의 변경 함수**가 나오고, 각 함수에 커버리지(주입 조인)와
 * ASIL(주석 + 요구 역전파)이 붙는다. 정렬은 위험 우선(ASIL→저커버→변경량), 필터로 좁힌다.
 * ISO: ASIL 보유 함수의 변경(asil_touched)은 경고 강조 — 안전 함수 변경 리뷰 의무.
 */
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { post } from '../../api.js';
import SummaryPanel from './SummaryPanel.jsx';
import * as T from './summaryTable.js';

const xs = { fontSize: 'var(--text-xs)' };

const REASON_KO = {
  no_source_snapshot: '캐시 빌드에 소스 스냅샷이 없습니다.',
  single_build_cached: '소스 스냅샷 빌드가 1개뿐이라 비교 쌍을 만들 수 없습니다.',
  snapshot_missing_baseline: '베이스라인 빌드에 소스 스냅샷이 없습니다.',
  snapshot_missing_target: '대상 빌드에 소스 스냅샷이 없습니다.',
  same_build_pair: '베이스라인과 대상이 같은 빌드입니다.',
};

const KIND_KO = {
  NEW: { label: '신규', color: 'var(--color-success)' },
  DELETE: { label: '삭제', color: 'var(--color-danger)' },
  SIGNATURE: { label: '시그니처', color: 'var(--color-warning)' },
  BODY: { label: '본문', color: 'var(--color-info)' },
};
const CHANGE_KIND_KO = { modified: '수정', added: '추가', deleted: '삭제' };
const FILTERS = [
  { key: 'all', label: '전체' },
  { key: 'asil', label: 'ASIL 함수만' },
  { key: 'gap', label: '커버리지 미달만' },
  { key: 'signature', label: '시그니처 변경만' },
];

function pct(v) {
  return v == null ? '—' : `${Math.round(Number(v) * 100)}%`;
}

function Pill({ text, color }) {
  return (
    <span style={{
      display: 'inline-block', padding: '1px 7px', borderRadius: 'var(--radius-sm)',
      fontSize: 'var(--text-xs)', fontWeight: 600, color: '#fff', background: color, marginRight: 4,
    }}>{text}</span>
  );
}

/** 함수 행 — 커버리지 미달은 색으로, 미조인은 '—'로(0%로 위장 금지).
 *  파일 아래 자식임이 드러나게 트리 커넥터(└/├)를 붙인다 — 들여쓰기만으론 평평해 보였다. */
function FunctionRow({ fn, td, last }) {
  const st = fn.statement;
  const tone = st == null ? 'var(--text-muted)'
    : st <= 0 ? 'var(--color-danger)'
    : st < 1 ? 'var(--color-warning)' : 'var(--text)';
  const kind = KIND_KO[fn.kind] || { label: fn.kind, color: 'var(--text-muted)' };
  return (
    <tr>
      <td style={{ ...td, paddingLeft: 18 }}>
        <span aria-hidden="true" style={{ fontFamily: 'monospace', color: 'var(--text-muted)', marginRight: 6 }}>
          {last ? '└─' : '├─'}
        </span>
        <Pill text={kind.label} color={kind.color} />
        <span style={{ fontFamily: 'monospace' }}>{fn.name}</span>
      </td>
      <td style={td}>
        {fn.asil
          ? <span title={`출처 ${fn.asil_source || '—'}`}
              style={{ fontWeight: 700, color: fn.asil === 'C' || fn.asil === 'D' ? 'var(--color-danger)' : 'var(--color-info)' }}>
              {fn.asil}
            </span>
          : <span style={{ color: 'var(--text-muted)' }}>미상</span>}
      </td>
      <td style={{ ...td, fontWeight: 600, color: tone }}
        title={fn.metric_source
          ? `${fn.metric_source.toUpperCase()} 측정${fn.measurements > 1 ? ` · 반복 측정 ${fn.measurements}회 중 최악값` : ''}`
          : '커버리지 데이터에 이 함수가 없습니다'}>
        {pct(st)}
        {fn.measurements > 1 && <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>*</span>}
      </td>
      <td style={td}>{pct(fn.branch)}</td>
      <td style={td}>{fn.ccn ?? '—'}</td>
      <td style={{ ...td, whiteSpace: 'normal' }}>
        {fn.kind === 'SIGNATURE' && (
          <>
            <div style={{ fontFamily: 'monospace', color: 'var(--color-danger)' }}>- {fn.before}</div>
            <div style={{ fontFamily: 'monospace', color: 'var(--color-success)' }}>+ {fn.after}</div>
          </>
        )}
      </td>
    </tr>
  );
}

/** 빌드 선택 라벨 — 번호만으론 어느 시점 코드인지 알 수 없어 날짜·리비전을 함께 노출한다. */
function buildLabel(b) {
  const when = String(b?.timestamp_iso || '').slice(5, 10).replace('-', '/');
  const rev = b?.revision ? ` r${b.revision}` : '';
  return `#${b?.build_number}${when ? ` · ${when}` : ''}${rev}`;
}

/**
 * 스냅샷 신뢰도 배너 — 수치를 보기 전에 "이 비교가 성립하는가"를 먼저 알린다.
 *
 * 실측에서 백필로 받아온 10개 빌드가 전부 같은 SVN HEAD라 서로 diff가 0이었고, 화면은
 * 그걸 '2개월간 변경 1건'으로 표시했다(ASIL 함수 변경이 22건 → 1건으로 과소보고).
 * 변경 0을 조용히 빈 화면으로 두면 "안전 함수 변경 없음"으로 읽힌다 — ISO 26262에서
 * 리뷰 의무 누락으로 이어지는 침묵이라 반드시 사유를 낸다.
 */
function SnapshotTrustBanner({ data }) {
  const files = data?.files || {};
  const identical = files.identical_snapshot === true;
  const lagB = data?.baseline?.checkout_lag_days;
  const lagT = data?.target?.checkout_lag_days;
  const stale = [['베이스라인', data?.baseline, lagB], ['대상', data?.target, lagT]]
    .filter(([, , lag]) => typeof lag === 'number' && lag >= 1);
  const groups = (data?.snapshot_groups || []).filter((g) => g.count > 1);
  if (!identical && stale.length === 0 && groups.length === 0) return null;
  const box = {
    ...xs, padding: '4px 8px', borderRadius: 'var(--radius-sm)',
    border: `1px solid ${identical ? 'var(--color-warning)' : 'var(--border)'}`,
    color: identical ? 'var(--color-warning)' : 'var(--text-muted)',
    marginBottom: 'var(--sp-2)', display: 'flex', flexDirection: 'column', gap: 2,
  };
  return (
    <div style={box} role={identical ? 'alert' : undefined}>
      {identical && (
        <div>
          <b>⚠ 두 빌드의 소스 스냅샷이 완전히 동일합니다</b> — 코드가 안 바뀐 것이 아니라
          같은 트리를 받아온 것이라, 이 구간의 변경·ASIL 수치는 실제 변화를 나타내지 않습니다.
        </div>
      )}
      {stale.map(([label, b, lag]) => (
        <div key={label}>
          {label} #{b?.build_number}: 소스를 빌드 <b>{lag}일 뒤</b>에 받았습니다
          ({String(b?.source_checked_out_at || '').replace('T', ' ').slice(0, 16)} 체크아웃)
          — 빌드 당시 코드가 아닐 수 있습니다.
        </div>
      ))}
      {groups.map((g) => (
        <div key={g.builds.join(',')}>
          동일 트리 재사용: #{g.builds.join(' · #')} ({g.count}개 빌드) — 이들끼리는 비교가 성립하지 않습니다.
        </div>
      ))}
    </div>
  );
}

/**
 * ⚠ builds/baseline/target은 **controlled** — 부모(ProjectSummarySection)가 소유한다.
 * 아래 빌드별 변경 매트릭스가 같은 베이스라인을 쓰므로, 두 패널이 각자 조회·선택하면 기준이
 * 갈라져 "어느 쪽이 진짜인가"를 사용자가 물어야 한다. 폴백 자체 fetch도 두지 않는다 —
 * 한 선택에 출처가 둘이면 그게 영구 버그원이다.
 */
export default function BaselineDiffPanel({ jobUrl, cacheRoot, builds, baseline, target, onChangeBaseline, onChangeTarget, defaultOpen = true }) {
  const [data, setData] = useState(null);
  const [delta, setDelta] = useState(null);        // 같은 쌍 PRQA 위반 delta
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(() => new Set());  // 펼친 파일 경로
  const [filter, setFilter] = useState('all');

  const toggle = useCallback((path) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path); else next.add(path);
      return next;  // 새 Set 반환 — 같은 참조를 mutate하면 리렌더가 발생하지 않는다
    });
  }, []);

  // 필터는 파일 행 기준(그 파일이 조건에 맞는 함수를 하나라도 가지면 표시).
  const visibleRows = useMemo(() => {
    const rows = data?.files?.changed_detail || [];
    if (filter === 'asil') return rows.filter((r) => (r.functions || []).some((f) => f.asil));
    if (filter === 'gap') {
      return rows.filter((r) => (r.functions || []).some((f) => f.statement != null && f.statement < 1));
    }
    if (filter === 'signature') return rows.filter((r) => (r.counts?.signature || 0) > 0);
    return rows;
  }, [data, filter]);

  const runCompare = useCallback(async (baseNum, tgtNum) => {
    if (!baseNum || !tgtNum) return;
    setBusy(true);
    setError('');
    setDelta(null);
    try {
      const resp = await post('/api/summary/baseline-diff', {
        job_url: jobUrl, cache_root: cacheRoot,
        baseline_build: Number(baseNum), target_build: Number(tgtNum),
      });
      setData(resp);
      // 최상단(위험 우선 정렬 1위) 파일은 기본 펼침 — 첫 화면에서 파일→함수 트리 구조가 보이게.
      const top = (resp?.files?.changed_detail || [])[0];
      setExpanded(top ? new Set([top.path]) : new Set());
      if (resp?.available) {
        // 같은 쌍의 정적분석 위반 delta 병행(기존 API 재사용 — best-effort).
        try {
          const d = await post('/api/jenkins/prqa-delta', {
            job_url: jobUrl, cache_root: cacheRoot,
            build_number: Number(tgtNum), baseline_build_number: Number(baseNum),
          });
          setDelta(d);
        } catch { /* delta는 부가 정보 — 실패해도 코드 변화는 표시 */ }
      }
    } catch (e) {
      setError(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  }, [jobUrl, cacheRoot]);
  const compare = useCallback(() => runCompare(baseline, target), [runCompare, baseline, target]);

  // 쌍이 갖춰지면 1회 자동 비교(서버 캐시라 저비용). 목록 조회는 부모 소관.
  const autoRef = useRef('');
  useEffect(() => {
    if (!jobUrl || !baseline || !target || baseline === target) return;
    const pair = `${baseline}->${target}`;
    if (autoRef.current === pair) return;   // 같은 쌍 재실행 방지(부모 리렌더에도 1회)
    autoRef.current = pair;
    runCompare(baseline, target);
  }, [jobUrl, baseline, target, runCompare]);

  const sel = { fontSize: 'var(--text-xs)', padding: '2px 6px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'var(--panel)', color: 'var(--text)' };
  // 표 서식은 summaryTable 공통 규약 — 본문 11px · 숫자 우측정렬(tabular-nums) ·
  // 식별자는 줄바꿈 대신 말줄임. 패널마다 따로 정의하면 한 탭 안에서 표가 서로 달라 보인다.
  const { th, td } = T;
  const fns = data?.functions || {};
  const files = data?.files || {};
  const gap = fns.gap_summary || null;

  return (
    <SummaryPanel
      title="베이스라인 → 최신 변화"
      defaultOpen={defaultOpen}
      caption="영향분석 이력(change-log)과 무관 — 소스 스냅샷 직접 비교"
      meta={builds && builds.length >= 2 ? (
        <>
          <select aria-label="베이스라인 빌드" value={baseline} onChange={(e) => { onChangeBaseline?.(e.target.value); setData(null); }} style={sel}>
            {builds.map((b) => <option key={b.build_number} value={b.build_number}>{buildLabel(b)}</option>)}
          </select>
          <span style={{ ...xs, color: 'var(--text-muted)' }}>→</span>
          <select aria-label="대상 빌드" value={target} onChange={(e) => { onChangeTarget?.(e.target.value); setData(null); }} style={sel}>
            {builds.map((b) => <option key={b.build_number} value={b.build_number}>{buildLabel(b)}</option>)}
          </select>
          <button type="button" onClick={compare} disabled={busy}
            style={{ ...xs, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: busy ? 'wait' : 'pointer', color: 'var(--text-muted)' }}>
            {busy ? '비교 중…' : '비교'}
          </button>
        </>
      ) : undefined}
    >
      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>비교 오류: {error}</div>}
      {builds && builds.length < 2 && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>소스 스냅샷 빌드가 2개 이상 필요합니다(현재 {builds.length}개) — '과거 빌드 가져오기'로 채울 수 있습니다.</div>
      )}
      {data && data.available === false && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>{REASON_KO[data.reason] || `비교할 수 없습니다 (${data.reason})`}</div>
      )}

      {data?.available && <SnapshotTrustBanner data={data} />}

      {data?.available && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-2)' }}>
          {/* 요약 스트립 */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--sp-2)', alignItems: 'center' }}>
            <span style={xs}>
              파일 <Pill text={`+${(files.added || []).length}`} color="var(--color-success)" />
              <Pill text={`−${(files.deleted || []).length}`} color="var(--color-danger)" />
              <Pill text={`수정 ${(files.modified || []).length}`} color="var(--color-info)" /> (무변경 {files.unchanged})
            </span>
            <span style={xs}>
              함수 <Pill text={`신규 ${fns.counts?.new ?? 0}`} color="var(--color-success)" />
              <Pill text={`삭제 ${fns.counts?.deleted ?? 0}`} color="var(--color-danger)" />
              <Pill text={`시그니처 ${fns.counts?.signature ?? 0}`} color="var(--color-warning)" />
              <Pill text={`본문 ${fns.counts?.body ?? 0}`} color="var(--color-info)" />
            </span>
            {delta?.available && (
              <span style={xs}>
                위반 {delta.totals?.base ?? '—'} → {delta.totals?.cur ?? '—'}
                {delta.totals?.delta != null && (
                  <b style={{ color: delta.totals.delta > 0 ? 'var(--color-danger)' : delta.totals.delta < 0 ? 'var(--color-success)' : 'var(--text-muted)', marginLeft: 4 }}>
                    ({delta.totals.delta > 0 ? '+' : ''}{delta.totals.delta})
                  </b>
                )}
              </span>
            )}
            {data.cached && <span style={{ ...xs, color: 'var(--text-muted)' }}>캐시됨</span>}
          </div>

          {/* 변경 함수 × 커버리지 갭 — 이번 변화에서 재검증할 것(최상위 신호) */}
          {gap && (
            <div style={{ ...xs, color: 'var(--text-muted)' }}>
              변경 함수 {gap.changed_functions}개 중{' '}
              <b style={{ color: gap.uncovered > 0 ? 'var(--color-danger)' : 'var(--text)' }}>미커버 {gap.uncovered}</b>
              {' · '}<b style={{ color: gap.below_full > 0 ? 'var(--color-warning)' : 'var(--text)' }}>부분 커버 {gap.below_full}</b>
              {' · '}커버리지 데이터 없음 {gap.coverage_unmatched}
              {data.join_sources?.coverage && ` · 커버리지 출처 ${data.join_sources.coverage === 'scm_vcast_job' ? 'SCM 입력 문서' : '빌드 산출물'}`}
              {data.asil_join?.injected && data.join_sources?.asil_counts && (
                ` · ASIL 확보 ${data.join_sources.asil_counts.total}함수(역전파 ${data.join_sources.asil_counts.uds_link})`
              )}
            </div>
          )}

          {/* ASIL 함수 변경 경고 */}
          {(data.asil_touched || []).length > 0 && (
            <div style={{ ...xs, color: 'var(--color-danger)' }}>
              ⚠ ASIL 주석 보유 함수 변경 {(data.asil_touched || []).length}건 — 안전 함수 변경은 리뷰 필수:
              {' '}{(data.asil_touched || []).slice(0, 5).map((f) => `${f.name}(${f.asil}/${f.change_kind})`).join(' · ')}
            </div>
          )}

          {/* 변경 파일 → 함수 트리 (위험 우선 정렬) */}
          {(data.files?.changed_detail || []).length > 0 ? (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 4, marginBottom: 4 }}>
                <span style={{ ...xs, color: 'var(--text-muted)' }}>
                  변경 파일 {(data.files.changed_detail || []).length}개
                  {(data.files.changed_detail_omitted || 0) > 0 && ` (+${data.files.changed_detail_omitted} 생략)`}
                  {' · '}표시 {visibleRows.length}개
                </span>
                {FILTERS.map((f) => (
                  <button key={f.key} type="button" onClick={() => setFilter(f.key)}
                    aria-pressed={filter === f.key}
                    style={{
                      ...xs, padding: '1px 8px', borderRadius: 'var(--radius-sm)', cursor: 'pointer',
                      border: `1px solid ${filter === f.key ? 'var(--accent)' : 'var(--border)'}`,
                      background: filter === f.key ? 'var(--accent)' : 'transparent',
                      color: filter === f.key ? '#fff' : 'var(--text-muted)',
                    }}>
                    {f.label}
                  </button>
                ))}
              </div>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                  <thead>
                    <tr>
                      <th style={th}>파일 / 함수</th><th style={th}>ASIL</th>
                      <th style={th}>구문</th><th style={th}>분기</th><th style={th}>ccn</th>
                      <th style={th}>비고</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.map((row) => {
                      const open = expanded.has(row.path);
                      const fnCount = Object.values(row.counts || {}).reduce((a, b) => a + b, 0);
                      return (
                        <Fragment key={row.path}>
                          <tr>
                            <td style={td}>
                              <button type="button" onClick={() => toggle(row.path)}
                                aria-expanded={open} aria-label={`${row.path} 변경 함수 ${open ? '접기' : '펼치기'}`}
                                style={{ ...xs, border: 'none', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)', padding: '0 4px 0 0' }}>
                                {open ? '▾' : '▸'}
                              </button>
                              <span title={row.path}>{row.path}</span>
                              <span style={{ ...xs, color: 'var(--text-muted)', marginLeft: 6 }}>
                                {CHANGE_KIND_KO[row.change_kind] || row.change_kind} · 함수 {fnCount}
                                {row.lines_added != null && ` · +${row.lines_added}/−${row.lines_removed}`}
                              </span>
                            </td>
                            <td style={td}>
                              {row.asil_max
                                ? <Pill text={row.asil_max} color={row.asil_max === 'C' || row.asil_max === 'D' ? 'var(--color-danger)' : 'var(--color-info)'} />
                                : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                            </td>
                            <td style={{ ...td, fontWeight: 600, color: row.worst_statement == null ? 'var(--text-muted)' : row.worst_statement < 0.8 ? 'var(--color-danger)' : 'var(--text)' }}
                              title="이 파일에서 변경된 함수의 최저 구문 커버리지">
                              {pct(row.worst_statement)}
                            </td>
                            {/* 파일 행은 함수 단위 값이 없다 — '—' 대신 집계를 보여 빈칸처럼 보이지 않게 */}
                            <td style={{ ...td, color: 'var(--text-muted)' }} colSpan={2}
                              title="이 파일에서 변경된 함수 수와 커버리지 조인 성립 수">
                              함수 {fnCount}개
                            </td>
                            <td style={{ ...td, color: 'var(--text-muted)' }}>
                              커버리지 조인 {row.coverage_matched}/{fnCount}
                            </td>
                          </tr>
                          {open && (row.functions || []).map((fn, i, arr) => (
                            <FunctionRow key={`${row.path}:${fn.name}:${fn.kind}`} fn={fn} td={td}
                              last={i === arr.length - 1 && !(row.functions_omitted > 0)} />
                          ))}
                          {open && (row.functions_omitted || 0) > 0 && (
                            <tr><td colSpan={6} style={{ ...td, paddingLeft: 22, color: 'var(--text-muted)' }}>
                              표시 상한으로 {row.functions_omitted}개 함수 생략
                            </td></tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {visibleRows.length === 0 && (
                <div style={{ ...xs, color: 'var(--text-muted)' }}>선택한 필터에 해당하는 파일이 없습니다.</div>
              )}
            </div>
          ) : (files.modified || []).length > 0 ? (
            <div style={{ ...xs, color: 'var(--text-muted)' }}>
              변경 파일 {(files.modified || []).length}개 — 함수 트리는 이 응답(구 캐시)에 없습니다. '비교'를 다시 눌러 갱신하세요.
            </div>
          ) : (
            // 이전엔 `&&` 폴백이라 변경 0이면 **아무것도 렌더되지 않았다** — 빈 화면은
            // "변경 없음"으로 읽히고, 그게 스냅샷 문제일 때 침묵이 된다(위 배너와 한 쌍).
            <div style={{ ...xs, color: 'var(--text-muted)' }}>
              {files.identical_snapshot
                ? `두 스냅샷이 동일해 비교할 변경이 없습니다 — 비교 대상 파일 ${files.unchanged ?? 0}개(위 경고 참조).`
                : `이 구간에 변경된 .c/.h 파일이 없습니다 — 비교 대상 ${files.unchanged ?? 0}개 전부 동일.`}
            </div>
          )}
        </div>
      )}
    </SummaryPanel>
  );
}
