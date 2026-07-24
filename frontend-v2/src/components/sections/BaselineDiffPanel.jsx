/**
 * BaselineDiffPanel — 베이스라인→최신 소스 스냅샷 직접 비교(영향분석 이력 완전 비의존).
 * POST /api/summary/baseline-diff(파일 sha1 + 함수 파서 권위 분류) + 같은 쌍
 * POST /api/jenkins/prqa-delta(1차 확장 API의 baseline_build_number 재사용) 병행 표시.
 *
 * ISO: ASIL 주석 보유 함수의 변경(asil_touched)은 경고 강조 — 안전 함수 변경 리뷰 의무.
 */
import { useCallback, useEffect, useState } from 'react';
import { post } from '../../api.js';

const xs = { fontSize: 'var(--text-xs)' };

const REASON_KO = {
  no_source_snapshot: '캐시 빌드에 소스 스냅샷이 없습니다.',
  single_build_cached: '소스 스냅샷 빌드가 1개뿐이라 비교 쌍을 만들 수 없습니다.',
  snapshot_missing_baseline: '베이스라인 빌드에 소스 스냅샷이 없습니다.',
  snapshot_missing_target: '대상 빌드에 소스 스냅샷이 없습니다.',
  same_build_pair: '베이스라인과 대상이 같은 빌드입니다.',
};

function Pill({ text, color }) {
  return (
    <span style={{
      display: 'inline-block', padding: '1px 7px', borderRadius: 'var(--radius-sm)',
      fontSize: 'var(--text-xs)', fontWeight: 600, color: '#fff', background: color, marginRight: 4,
    }}>{text}</span>
  );
}

export default function BaselineDiffPanel({ jobUrl, cacheRoot }) {
  const [builds, setBuilds] = useState(null);      // has_source 캐시 빌드 목록
  const [baseline, setBaseline] = useState('');    // 선택 빌드 번호(문자열)
  const [target, setTarget] = useState('');
  const [data, setData] = useState(null);
  const [delta, setDelta] = useState(null);        // 같은 쌍 PRQA 위반 delta
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

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

  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const resp = await post('/api/jenkins/cached-builds-meta', { job_url: jobUrl, cache_root: cacheRoot });
        if (cancelled) return;
        const rows = (resp?.builds || []).filter((b) => b.has_source);
        setBuilds(rows);
        if (rows.length >= 2) {
          const tgt = String(rows[0].build_number);
          const base = String(rows[rows.length - 1].build_number);
          setTarget(tgt);
          setBaseline(base);
          // 초기 1회 자동 비교(서버 캐시라 저비용) — async 흐름 내 호출(effect 동기 setState 아님).
          runCompare(base, tgt);
        }
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot, runCompare]);

  const sel = { fontSize: 'var(--text-xs)', padding: '2px 6px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'var(--panel)', color: 'var(--text)' };
  const th = { ...xs, textAlign: 'left', padding: '4px 8px', color: 'var(--text-muted)', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' };
  const td = { ...xs, padding: '4px 8px', borderBottom: '1px solid var(--border)' };
  const fns = data?.functions || {};
  const files = data?.files || {};

  return (
    <div className="panel" style={{ padding: 'var(--sp-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--sp-2)', marginBottom: 'var(--sp-1)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>베이스라인 → 최신 변화</div>
        {builds && builds.length >= 2 && (
          <>
            <select aria-label="베이스라인 빌드" value={baseline} onChange={(e) => { setBaseline(e.target.value); setData(null); }} style={sel}>
              {builds.map((b) => <option key={b.build_number} value={b.build_number}>#{b.build_number}</option>)}
            </select>
            <span style={{ ...xs, color: 'var(--text-muted)' }}>→</span>
            <select aria-label="대상 빌드" value={target} onChange={(e) => { setTarget(e.target.value); setData(null); }} style={sel}>
              {builds.map((b) => <option key={b.build_number} value={b.build_number}>#{b.build_number}</option>)}
            </select>
            <button type="button" onClick={compare} disabled={busy}
              style={{ ...xs, padding: '2px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'transparent', cursor: busy ? 'wait' : 'pointer', color: 'var(--text-muted)' }}>
              {busy ? '비교 중…' : '비교'}
            </button>
          </>
        )}
      </div>
      <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 'var(--sp-2)' }}>
        영향분석 이력(change-log)과 무관 — 소스 스냅샷 직접 비교
      </div>

      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>비교 오류: {error}</div>}
      {builds && builds.length < 2 && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>소스 스냅샷 빌드가 2개 이상 필요합니다(현재 {builds.length}개) — '과거 빌드 가져오기'로 채울 수 있습니다.</div>
      )}
      {data && data.available === false && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>{REASON_KO[data.reason] || `비교할 수 없습니다 (${data.reason})`}</div>
      )}

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

          {/* ASIL 함수 변경 경고 */}
          {(data.asil_touched || []).length > 0 && (
            <div style={{ ...xs, color: 'var(--color-danger)' }}>
              ⚠ ASIL 주석 보유 함수 변경 {(data.asil_touched || []).length}건 — 안전 함수 변경은 리뷰 필수:
              {' '}{(data.asil_touched || []).slice(0, 5).map((f) => `${f.name}(${f.asil}/${f.change_kind})`).join(' · ')}
            </div>
          )}

          {/* 시그니처 변경 before/after */}
          {(fns.signature_changed || []).length > 0 && (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                <thead>
                  <tr><th style={th}>시그니처 변경 함수</th><th style={th}>이전 → 이후</th><th style={th}>ASIL</th></tr>
                </thead>
                <tbody>
                  {(fns.signature_changed || []).slice(0, 10).map((f) => (
                    <tr key={`${f.file}:${f.name}`}>
                      <td style={{ ...td, whiteSpace: 'nowrap' }} title={f.file}>{f.name}</td>
                      <td style={td}>
                        <div style={{ fontFamily: 'monospace', color: 'var(--color-danger)' }}>- {f.before}</div>
                        <div style={{ fontFamily: 'monospace', color: 'var(--color-success)' }}>+ {f.after}</div>
                      </td>
                      <td style={{ ...td, whiteSpace: 'nowrap' }}>{f.asil || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* 수정 파일 상위 */}
          {(files.modified || []).length > 0 && (
            <details>
              <summary style={{ ...xs, cursor: 'pointer' }}>수정 파일 {(files.modified || []).length}개 (라인 증감)</summary>
              <div style={{ overflowX: 'auto' }}>
                <table style={{ borderCollapse: 'collapse', width: '100%' }}>
                  <thead><tr><th style={th}>파일</th><th style={th}>+ 추가</th><th style={th}>− 삭제</th></tr></thead>
                  <tbody>
                    {(files.modified || []).slice(0, 20).map((m) => (
                      <tr key={m.path}>
                        <td style={td}>{m.path}</td>
                        <td style={{ ...td, color: 'var(--color-success)' }}>{m.lines_added ?? '—'}</td>
                        <td style={{ ...td, color: 'var(--color-danger)' }}>{m.lines_removed ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
