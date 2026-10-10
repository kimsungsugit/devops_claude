/**
 * BuildChangeMatrixPanel — 베이스라인 고정 → 각 빌드의 누적 소스 변화.
 * POST /api/summary/change-matrix (파일 축 즉시) + /change-matrix/cell (함수 축 순차).
 *
 * 구 타임라인은 영향분석 **잡 실행 이력**을 읽어, 잡을 돌린 적 없는 빌드가 전부 `—`였고
 * 빌드 번호가 없는 구 레코드 87건이 표를 채웠다(실측 89행 중 88행이 "#—"). 이 패널은 그
 * 이력과 무관하게 소스 스냅샷만 비교한다.
 *
 * ISO 정직성:
 * - 함수 축 미계산은 `0`이 아니라 `—` + 사유(증거부재 ≠ 변경없음)
 * - ASIL은 함수 축이 있을 때만 표시(파일 단위로는 원리적으로 산출 불가)
 * - 동일 트리 그룹을 표면화 — "변화 0"이 코드 미변경이 아니라 백필이 같은 SVN HEAD를 받아온
 *   결과일 수 있고, 그걸 감추면 안전 관련 함수 변경이 과소보고된다
 */
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { post } from '../../api.js';
import SummaryPanel from './SummaryPanel.jsx';
import * as T from './summaryTable.js';
import BuildDeltaDrilldown from './BuildDeltaDrilldown.jsx';

const xs = { fontSize: 'var(--text-xs)' };
const MATRIX_COLS = 10;

const STATE_KO = {
  level_files: '미계산',
  cell_not_cached: '미계산',
};

function fmtLag(days) {
  if (typeof days !== 'number') return null;
  if (days < 1) return null;
  return `빌드 ${days}일 뒤 체크아웃`;
}

/** 함수/ASIL 셀 — null은 절대 0으로 표시하지 않는다. */
function PendingCell({ state, busy }) {
  if (busy) return <span style={{ color: 'var(--text-muted)' }}>계산 중…</span>;
  return (
    <span style={{ color: 'var(--text-muted)' }} title={state?.reason ? `사유: ${state.reason}` : undefined}>
      — {STATE_KO[state?.reason] || ''}
    </span>
  );
}

function AsilCell({ asil }) {
  if (!asil) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  if (!asil.touched) return <span style={{ color: 'var(--text-muted)' }}>0</span>;
  const grades = Object.entries(asil.by_grade || {});
  return (
    <span style={{ fontWeight: 600, color: asil.max === 'D' || asil.max === 'C' ? 'var(--color-danger)' : 'var(--color-info)' }}
      title={grades.map(([g, n]) => `ASIL ${g} ${n}건`).join(' · ')}>
      {asil.touched}
      {grades.length > 0 && (
        <span style={{ ...xs, fontWeight: 400, color: 'var(--text-muted)' }}>
          {' '}({grades.map(([g, n]) => `${g}${n}`).join('·')})
        </span>
      )}
    </span>
  );
}

export default function BuildChangeMatrixPanel({ jobUrl, cacheRoot, baseline, deltaByBuild, prqaTrendError, onBusy, defaultOpen = true }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [cells, setCells] = useState({});          // build_number → 셀 결과
  const [busyCell, setBusyCell] = useState(null);  // 계산 중인 target_build
  const [progress, setProgress] = useState(null);  // {done, total}
  const [expanded, setExpanded] = useState(null);
  const runRef = useRef(0);
  // 중지 플래그는 ref — 순차 루프가 최신 값을 봐야 한다(state면 클로저에 갇혀 영원히 false다).
  const stoppedRef = useRef(false);

  // ⚠ 언마운트/잡 전환에도 순차 루프를 반드시 끊는다. 예전엔 runRef 가 baseline 변경 때만
  //   올라가서, 프로젝트를 바꿔 섹션이 remount 돼도 **떠난 프로젝트의 셀 계산 33건이 끝까지
  //   돌았다**(서버 부하 + 떠난 프로젝트의 완료 상태가 화면에 반영). run 가드를 무효화한다.
  useEffect(() => () => { runRef.current += 1; stoppedRef.current = true; }, []);

  // ── ① 파일 축 즉시 → ② 함수 축 probe(캐시된 셀만) ──
  useEffect(() => {
    if (!jobUrl || !baseline) return undefined;
    let cancelled = false;
    const run = ++runRef.current;
    (async () => {
      // 리셋을 async 안에서 — effect 본문의 동기 setState는 캐스케이딩 렌더를 부른다.
      // ⚠ busyCell 도 반드시 리셋한다 — 계산 중 베이스라인이 바뀌면 루프는 run 가드로 죽는데
      //   `busyCell` 이 남아 헤더가 "계산 중"을 영원히 표시하고, `pending>0 && !busyCell` 가드
      //   때문에 재시작 버튼도 안 나온다(탈출구 없음).
      setData(null); setCells({}); setProgress(null); setBusyCell(null); setExpanded(null);
      stoppedRef.current = false; setError('');
      const body = { job_url: jobUrl, cache_root: cacheRoot, baseline_build: Number(baseline) };
      try {
        const files = await post('/api/summary/change-matrix', { ...body, level: 'files' });
        if (cancelled || run !== runRef.current) return;
        setData(files);
        if (files?.available === false) return;
        const warm = await post('/api/summary/change-matrix', { ...body, level: 'functions' });
        if (cancelled || run !== runRef.current) return;
        setData(warm);
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot, baseline]);

  const pending = useMemo(() => data?.pending_cells || [], [data]);

  // ── ③ pending을 동시성 1로 순차 계산 — 도착 시 같은 스냅샷 그룹 전체를 함께 채운다 ──
  const computePending = useCallback(async () => {
    const run = runRef.current;
    stoppedRef.current = false;
    // 이미 계산된 셀은 건너뛴다 — 중지 후 재개가 1번부터 다시 돌면 "12건 중 5건 했는데
    // 또 12건"이 되어 진행이 되돌아간 것처럼 보인다.
    // (deps 의 `cells` 로 **클릭 시점** 스냅샷을 쓴다. 콜백이 셀마다 재생성돼도 실행 중인
    //  루프는 자기 클로저를 그대로 쓰므로 영향이 없다.)
    const list = pending.filter((c) => !cells[c.target_build]);
    try {
      for (let i = 0; i < list.length; i += 1) {
        if (run !== runRef.current) return;
        setBusyCell(list[i].target_build);
        setProgress({ done: i, total: list.length });
        onBusy?.('matrix', `함수 축 계산 중 ${i + 1}/${list.length} (#${list[i].target_build})`);
        const resp = await post('/api/summary/change-matrix/cell', {
          job_url: jobUrl, cache_root: cacheRoot,
          baseline_build: Number(baseline), target_build: list[i].target_build,
        });
        if (run !== runRef.current) return;
        // 같은 트리를 쓰는 빌드가 여럿이면 한 번의 계산으로 그 행들이 전부 채워진다.
        setCells((prev) => {
          const next = { ...prev };
          for (const b of resp?.shared_with_builds || [resp?.target?.build_number]) next[b] = resp;
          return next;
        });
        // 중지 요청 확인은 각 셀 완료 후 — 진행 중인 요청을 중단하지는 않는다.
        if (stoppedRef.current) break;
      }
    } catch (e) {
      setError(String(e?.message || e));
    } finally {
      // ⚠ finally — 조기 return(run 가드)·예외 어느 경로로 빠져도 "계산 중"을 남기지 않는다.
      if (run === runRef.current) { setBusyCell(null); setProgress(null); }
      onBusy?.('matrix', null);
    }
  }, [pending, cells, jobUrl, cacheRoot, baseline, onBusy]);

  // 표 서식은 summaryTable 공통 규약 — 본문 11px · 숫자 우측정렬(tabular-nums) ·
  // 식별자는 줄바꿈 대신 말줄임. 패널마다 따로 정의하면 한 탭 안에서 표가 서로 달라 보인다.
  const { th, td } = T;
  const rows = data?.rows || [];
  const groups = (data?.snapshot_groups || []).filter((g) => g.count > 1);
  const trust = data?.snapshot_trust;
  const limitInfo = data?.row_limit;
  const mixedCount = rows.filter((r) => r.comparison_basis?.state === 'mixed').length;
  // 헤더 신호 — 접었을 때 본문의 경고·절단 고지가 통째로 사라지는 걸 막는다.
  // 미고정 경고는 "변화 0 = 코드 미변경" 오독을 막는 축이라 특히 숨으면 안 된다.
  const problem = error
    ? <span style={{ ...xs, color: 'var(--color-danger)' }}>⚠ 조회 실패 — {error}</span>
    : data?.available === false
      ? <span style={{ ...xs, color: 'var(--color-warning)' }}>표 생성 불가</span>
      : trust?.unpinned > 0
        ? <span style={{ ...xs, color: 'var(--color-warning)' }}>⚠ 스냅샷 미고정 {trust.unpinned}행 — “변화 0”은 코드 미변경 증거가 아님</span>
        : limitInfo?.omitted_builds?.length > 0
          ? <span style={{ ...xs, color: 'var(--color-warning)' }}>⚠ 표시 {limitInfo.shown} / 전체 {limitInfo.available} — {limitInfo.omitted_builds.length}개 빌드 생략</span>
          : null;

  return (
    <SummaryPanel
      title="빌드별 변경 영향"
      defaultOpen={defaultOpen}
      caption="베이스라인 대비 누적 변화 — 소스 스냅샷 직접 비교(영향분석 실행 이력과 무관)"
      problem={problem}
      meta={<>
        {data?.baseline?.build_number != null && (
          <span style={{ ...xs, color: 'var(--text-muted)' }}>
            기준 #{data.baseline.build_number}
            {data.baseline.timestamp_iso ? ` · ${String(data.baseline.timestamp_iso).slice(0, 10)}` : ''}
            {data.baseline.revision ? ` · r${data.baseline.revision}` : ''}
            {' · '}<span style={{ opacity: 0.8 }}>위 패널에서 변경</span>
          </span>
        )}
        {pending.length > 0 && !busyCell && (
          <button type="button" onClick={computePending}
            style={{ ...xs, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}>
            함수 축 계산 ({pending.length}건)
          </button>
        )}
        {busyCell && (
          <>
            <span style={{ ...xs, color: 'var(--color-info)' }}>
              함수 축 계산 중 {(progress?.done ?? 0) + 1}/{progress?.total ?? pending.length} (#{busyCell})…
            </span>
            <button type="button" onClick={() => { stoppedRef.current = true; }}
              style={{ ...xs, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}>
              중지
            </button>
          </>
        )}
      </>}
    >
      {error && <div style={{ ...xs, color: 'var(--color-danger)', marginBottom: 'var(--sp-2)' }}>매트릭스 조회 오류: {error}</div>}
      {data?.available === false && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          {data.reason === 'no_source_snapshot'
            ? '소스 스냅샷이 있는 캐시 빌드가 없습니다 — 위의 "과거 빌드 가져오기"로 채울 수 있습니다.'
            : `표를 만들 수 없습니다 (${data.reason})`}
        </div>
      )}

      {/* 스냅샷 미고정 경고 — 동일 트리의 **원인**을 짚는다. 이게 없으면 사용자가 '변화 0'을
          코드 미변경으로 읽어 ASIL 함수 변경이 침묵으로 과소보고된다. */}
      {trust?.unpinned > 0 && (
        <div style={{
          ...xs, padding: '4px 8px', borderRadius: 'var(--radius-sm)', marginBottom: 'var(--sp-2)',
          border: '1px solid var(--color-warning)', color: 'var(--color-warning)',
        }}>
          ⚠ {rows.length}개 행 중 {trust.unpinned}개는 소스가 <b>빌드 시점으로 고정되지 않았습니다</b> —
          받아온 날의 HEAD 트리라 아래 “변화 0”은 코드가 안 바뀐 증거가 아닙니다.
          위 “과거 빌드 가져오기”에서 <b>스냅샷 고정</b>을 켜고 다시 가져오면, 각 빌드의 Jenkins
          콘솔 로그에 남은 <b>실제 체크아웃 revision</b>으로 재수집합니다.
          {mixedCount > 0 && ` 재수집이 일부만 끝나 기준이 섞인 행 ${mixedCount}개는 ⚠로 표시됩니다.`}
        </div>
      )}

      {/* 절단 고지 — 잘렸다는 사실을 숨기면 "내 빌드가 왜 없나"에 답할 수 없다 */}
      {limitInfo?.omitted_builds?.length > 0 && (
        <div style={{
          ...xs, padding: '4px 8px', borderRadius: 'var(--radius-sm)', marginBottom: 'var(--sp-2)',
          border: '1px solid var(--border)', color: 'var(--text-muted)',
        }}>
          표시 {limitInfo.shown} / 전체 {limitInfo.available} — 상한({limitInfo.limit})을 넘어
          #{limitInfo.omitted_builds.slice(0, 12).join(' · #')}
          {limitInfo.omitted_builds.length > 12 ? ` 외 ${limitInfo.omitted_builds.length - 12}개` : ''}는 표에 없습니다.
          {limitInfo.baseline_forced_in && ' (기준 빌드는 상한과 무관하게 항상 표시됩니다)'}
        </div>
      )}

      {/* 동일 트리 안내 — 어떤 빌드들이 같은 트리인지 */}
      {groups.length > 0 && (
        <div style={{
          ...xs, padding: '4px 8px', borderRadius: 'var(--radius-sm)', marginBottom: 'var(--sp-2)',
          border: '1px solid var(--border)', color: 'var(--text-muted)',
        }}>
          {rows.length}개 빌드 중 고유 소스 트리는 {(data?.snapshot_groups || []).length + rows.length - groups.reduce((a, g) => a + g.count, 0)}개입니다 —
          {groups.map((g) => ` #${g.builds.join(' · #')} (${g.count}개)`).join(',')}가 동일 트리라 이 구간의 변화는 0으로 나옵니다.
        </div>
      )}

      {rows.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ borderCollapse: 'collapse', width: '100%', minWidth: 720 }}>
            <thead>
              <tr>
                <th style={th} aria-label="펼치기" />
                <th style={th}>빌드</th><th style={th}>결과</th><th style={th}>시각</th><th style={th}>리비전</th>
                <th style={th}>스냅샷</th><th style={T.numTh}>변경 파일</th><th style={T.numTh}>변경 함수</th>
                <th style={th} title="변경된 함수 중 ASIL 등급이 있는 것">ASIL 함수 변경</th>
                {/* ⚠ 트렌드 조회가 실패하면 이 열이 전 행 `—` 가 되는데, 사유가 없으면 "변화 없음"으로
            읽힌다. 열 제목에 실패를 명시한다(증거부재 ≠ 0). */}
        <th style={{ ...T.numTh, color: prqaTrendError ? 'var(--color-warning)' : th.color }}
          title={prqaTrendError ? `PRQA 트렌드 조회 실패 — ${prqaTrendError}` : '직전 캐시 빌드 대비 PRQA 위반 증감'}>
          Δ위반{prqaTrendError ? ' ⚠미조회' : ''}
        </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const cell = cells[r.build_number];
                const fns = cell?.functions || r.functions;
                const asil = cell?.asil || r.asil;
                const open = expanded === r.build_number;
                const lag = fmtLag(r.checkout_lag_days);
                // 기준 불일치 — 숫자는 맞지만 '이 빌드의 변화'가 아니다(부분 재수집 중 필연).
                const mixed = r.comparison_basis?.state === 'mixed';
                const rowDelta = deltaByBuild?.get?.(String(r.build_number))?.violations_delta ?? null;
                return (
                  <Fragment key={r.row_key || `b${r.build_number}`}>
                    <tr style={{ opacity: r.identical_to_baseline || r.is_baseline ? 0.65 : 1 }}>
                      <td style={td}>
                        {!r.is_baseline && (
                          <button type="button" onClick={() => setExpanded(open ? null : r.build_number)}
                            aria-expanded={open} aria-label={`빌드 #${r.build_number} 변경 상세 ${open ? '접기' : '펼치기'}`}
                            style={{ ...xs, padding: '1px 6px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)' }}>
                            {open ? '▾' : '▸'}
                          </button>
                        )}
                      </td>
                      <td style={{ ...T.numTd, fontWeight: r.is_baseline ? 700 : 400 }}>
                        #{r.build_number}{r.is_baseline ? ' (기준)' : ''}
                      </td>
                      <td style={td}>{r.build_result || '—'}</td>
                      <td style={td} title={lag || undefined}>
                        {String(r.timestamp_iso || '').replace('T', ' ').slice(0, 16) || '—'}
                        {lag && <span style={{ color: 'var(--color-warning)' }} title={lag}> ⚠</span>}
                      </td>
                      <td style={td}>
                        {r.source_pinned
                          ? `r${r.revision}`
                          : <span style={{ color: 'var(--color-warning)' }}
                              title="이 빌드의 소스는 빌드 시점 revision으로 고정되지 않았습니다 — 체크아웃한 날의 HEAD 트리입니다.">
                              {r.revision ? `r${r.revision}` : '미고정'} ⚠
                            </span>}
                      </td>
                      <td style={td}>
                        {r.snapshot_group?.count > 1
                          ? <span title={`동일 트리: #${(r.snapshot_group.members || []).join(' · #')}`}
                              style={{ ...xs, padding: '1px 6px', borderRadius: 'var(--radius-sm)', border: '1px dashed var(--border)', color: 'var(--text-muted)' }}>
                              동일 트리 {r.snapshot_group.count}
                            </span>
                          : <span style={{ color: 'var(--text-muted)' }}>·</span>}
                      </td>
                      <td style={T.numTd}>
                        {r.files
                          ? <span title={mixed
                              ? r.comparison_basis.reason
                              : `추가 ${r.files.added} · 삭제 ${r.files.deleted} · 수정 ${r.files.modified} (무변경 ${r.files.unchanged})`}
                              style={mixed ? { color: 'var(--color-warning)', textDecoration: 'underline dotted' } : undefined}>
                              {r.files.changed}{mixed ? ' ⚠' : ''}
                            </span>
                          : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                      </td>
                      <td style={{ ...T.numTd, fontWeight: 600 }}>
                        {fns
                          ? <span title={mixed
                              ? r.comparison_basis.reason
                              : `신규 ${fns.new} · 삭제 ${fns.deleted} · 시그니처 ${fns.signature} · 본문 ${fns.body}`}
                              style={mixed ? { color: 'var(--color-warning)', textDecoration: 'underline dotted' } : undefined}>
                              {fns.changed}{mixed ? ' ⚠' : ''}
                            </span>
                          : <PendingCell state={r.function_state} busy={busyCell === r.build_number} />}
                      </td>
                      <td style={T.numTd}><AsilCell asil={asil} /></td>
                      <td style={T.numTd}>
                        {rowDelta == null
                          ? <span style={{ color: 'var(--text-muted)' }}>—</span>
                          : <span style={{ fontWeight: 600, color: rowDelta > 0 ? 'var(--color-danger)' : rowDelta < 0 ? 'var(--color-success)' : 'var(--text-muted)' }}>
                              {rowDelta > 0 ? `+${rowDelta}` : rowDelta === 0 ? '±0' : rowDelta}
                            </span>}
                      </td>
                    </tr>
                    {open && (
                      <tr>
                        <td colSpan={MATRIX_COLS} style={{ padding: '4px 8px', borderBottom: '1px solid var(--border)' }}>
                          <ExpandedRow row={r} cell={cell} jobUrl={jobUrl} cacheRoot={cacheRoot}
                            baseline={baseline} onComputed={(resp) => setCells((prev) => {
                              const next = { ...prev };
                              for (const b of resp?.shared_with_builds || [resp?.target?.build_number]) next[b] = resp;
                              return next;
                            })} />
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

      {data?.note && <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 'var(--sp-1)' }}>* {data.note}</div>}
      {data?.join_scope && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          * ASIL·커버리지는 빌드 #{data.join_scope.build_number} 인덱스 기준 — {data.join_scope.note}
        </div>
      )}
    </SummaryPanel>
  );
}

/** 행 펼침 — 변경 파일 목록 + (계산됐으면) 변경 함수 + 그 빌드의 PRQA 위반 delta. */
function ExpandedRow({ row, cell, jobUrl, cacheRoot, baseline, onComputed }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const detail = cell?.detail;
  const paths = row.files?.changed_paths || [];

  const loadDetail = async () => {
    setBusy(true); setErr('');
    try {
      const resp = await post('/api/summary/change-matrix/cell', {
        job_url: jobUrl, cache_root: cacheRoot,
        baseline_build: Number(baseline), target_build: row.build_number, detail: true,
      });
      onComputed(resp);
    } catch (e) {
      setErr(String(e?.message || e));
    } finally {
      setBusy(false);
    }
  };

  const mono = { fontFamily: 'monospace', fontSize: 'var(--text-xs)' };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-2)' }}>
      <div>
        <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 2 }}>
          변경 파일 {row.files?.changed ?? 0}개
        </div>
        {paths.length === 0
          ? <div style={{ ...xs, color: 'var(--text-muted)' }}>
              {row.identical_to_baseline
                ? '베이스라인과 소스 트리가 바이트 동일 — 변경된 파일이 없습니다(코드 미변경이 아니라 같은 트리일 수 있습니다).'
                : '변경된 .c/.h 파일이 없습니다.'}
            </div>
          : <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {paths.slice(0, 40).map((p) => (
                <span key={p.path} style={{ ...mono, color: p.change_kind === 'added' ? 'var(--color-success)' : p.change_kind === 'deleted' ? 'var(--color-danger)' : 'var(--text)' }}>
                  {p.path}
                </span>
              ))}
            </div>}
      </div>

      <div>
        <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 2, display: 'flex', gap: 8, alignItems: 'center' }}>
          변경 함수 {cell?.functions ? cell.functions.changed : (row.functions?.changed ?? '—')}
          {!detail && !row.identical_to_baseline && (
            <button type="button" onClick={loadDetail} disabled={busy}
              style={{ ...xs, padding: '1px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: busy ? 'wait' : 'pointer', color: 'var(--text-muted)' }}>
              {busy ? '계산 중…' : '함수 목록 보기'}
            </button>
          )}
        </div>
        {err && <div style={{ ...xs, color: 'var(--color-danger)' }}>{err}</div>}
        {(detail?.asil_touched || []).length > 0 && (
          <div style={{ ...xs, color: 'var(--color-warning)' }}>
            ⚠ ASIL 함수 변경 {detail.asil_touched.length}건 —
            {detail.asil_touched.slice(0, 6).map((f) => ` ${f.name}(${f.asil}/${f.change_kind})`).join(' ·')}
          </div>
        )}
        {(detail?.changed_detail || []).slice(0, 8).map((f) => (
          <div key={f.path} style={{ ...xs, marginTop: 2 }}>
            <span style={mono}>{f.path}</span>
            <span style={{ color: 'var(--text-muted)' }}>
              {' '}— 신규 {f.counts?.new ?? 0} · 삭제 {f.counts?.deleted ?? 0} · 시그니처 {f.counts?.signature ?? 0} · 본문 {f.counts?.body ?? 0}
            </span>
          </div>
        ))}
      </div>

      <BuildDeltaDrilldown jobUrl={jobUrl} cacheRoot={cacheRoot} buildNumber={Number(row.build_number)} />
    </div>
  );
}
