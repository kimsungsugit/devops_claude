import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { api, post } from '../../api.js';
import { useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';

/**
 * QualityGateSection — 품질 게이트 **세부**. 이력 · 추세 · 정책.
 *
 * ## 왜 새로 만들었나 (두 벌 UI 해소)
 *
 * 같은 데이터를 보는 화면이 둘이었고 **서로 다른 판정을 냈다**:
 *
 *   `views/QualityDashboard.jsx`  최상위 Quality 탭. `gate_pass ?? (score >= 70)` 로
 *                                 서버 판정이 없을 때 **점수만 보고 PASS 를 지어냈다**.
 *   `sections/GateReviewSection`  Detail 의 🚦 탭. 서버값 그대로 PASS/FAIL/판정 없음.
 *
 * 같은 run 이 한쪽에서 PASS, 다른 쪽에서 판정 없음이었다. 이 파일이 **한 벌**로 두
 * 진입(프로젝트 상세 / 전역 관제)을 모두 처리한다 — `analysisResult` 가 있으면
 * 그 프로젝트로 좁히고, 없으면 전체다.
 *
 * ## GateReviewSection 에서 이식한 정직성 자산 (전부 유지)
 *
 * - 서버 판정 그대로. `gate_pass === null` 은 **판정 없음**이지 통과가 아니다.
 * - `gated_metric_count` 부재는 "검사 규모 미기록 — 판별 불가"로 명시(가짜라는 뜻이 아님).
 * - `gate_definition:` 마커 부재는 "게이트 정의 미상"(같은 컬럼에 두 정의가 섞여 있다).
 * - 비게이트 지표는 임계 칸에 `—(비게이트)`.
 * - 200+`error` 응답을 성공으로 삼키지 않는다(`api.js` 가 `res.ok` 만 보므로 한 번 더).
 *
 * ## 고친 것
 *
 * - **CSS 가 실재한다.** 옛 파일은 `.section`/`.data-table`/`.alert` 를 썼는데 그 넷은
 *   `index.css` 에 정의가 **없어** 브라우저 기본 `<table>` 로 렌더됐다 — 테두리도 배경도
 *   없이. 그게 "품질 게이트 UI 가 와닿지 않는다" 의 물리적 1순위 원인이었다.
 * - 로컬 `Pill`(색 하드코딩, 다크모드 대비 규약 밖) 대신 `StatusBadge`.
 * - WAI-ARIA 키보드 네비게이션(옛 파일엔 `tabIndex` 도 `onKeyDown` 도 없었다).
 * - **추세 차트에서 임계선 70 을 지웠다.** `overall_score` 는 임계 있는 지표의 평균이라
 *   게이트 판정과 **다른 척도**다. 70 은 어디에도 근거가 없는 숫자였고, 선을 그으면
 *   "이 선 위면 통과" 로 읽힌다. 막대 색은 서버 `gate_pass` 로만 칠한다.
 */

const SUBS = [
  { id: 'runs', label: '실행 이력' },
  { id: 'trend', label: '점수 추세' },
  { id: 'policy', label: '정책값' },
];
const VALID_SUB = new Set(SUBS.map((s) => s.id));

const DOC_TYPES = [
  { value: '', label: '전체' },
  { value: 'uds', label: 'UDS' }, { value: 'sts', label: 'STS' },
  { value: 'suts', label: 'SUTS' }, { value: 'sits', label: 'SITS' },
  // 레벨별로 산출물이 셋이고 **평가기가 셋 다 다르다** — 커버리지 축(swut/swit) vs
  // 실행률·통과율(sutr/sitr) vs 종합(swutcr/switcr, 분모 키가 `total_tcs`). 한 항목으로
  // 합치면 지표가 섞인다. 목록에서 빠지면 '전체' 로만 보이고 개별 조회가 안 된다.
  { value: 'swut', label: 'SwUTCV(커버리지)' }, { value: 'swit', label: 'SwITCV(커버리지)' },
  { value: 'sutr', label: 'SUTR' }, { value: 'sitr', label: 'SITR' },
  { value: 'swutcr', label: 'SwUTCR' }, { value: 'switcr', label: 'SwITCR' },
  { value: 'swsa', label: 'SwSA' }, { value: 'swreport', label: '통합 Summary' },
];

/** 서버 판정을 **그대로** — 프론트 재계산 금지(`?? (score>=70)` 을 되살리지 말 것). */
function gateLabel(gatePass) {
  if (gatePass === true) return { text: 'PASS', tone: 'success' };
  if (gatePass === false) return { text: 'FAIL', tone: 'danger' };
  return { text: '판정 없음', tone: 'neutral' };
}

/** scores 에서 검사 규모/정의 마커/사유를 뽑는다. 없으면 `null`(= 미기록). */
function readRunMeta(run) {
  const rows = Array.isArray(run?.scores) ? run.scores : [];
  const gatedRow = rows.find((s) => s?.metric_name === 'gated_metric_count');
  const defRow = rows.find((s) => String(s?.metric_name || '').startsWith('gate_definition:'));
  return {
    gatedCount: gatedRow ? Number(gatedRow.value) : null,
    definition: defRow ? String(defRow.metric_name).slice('gate_definition:'.length) : null,
    reason: run?.gate_reason || null,
  };
}

const fmtWhen = (iso) => (iso ? new Date(iso).toLocaleString('ko-KR') : '—');

/**
 * 점수 추세 (SVG, 라이브러리 없음).
 *
 * ⚠ 막대 간격은 **균일**하다 — 시간 간격을 나타내지 않는다. "3주 공백" 과 "10분 간격
 * 5회" 가 같은 폭으로 보이므로 X축 라벨에 날짜를 넣고 그 사실을 캡션에 밝힌다.
 */
function TrendChart({ data }) {
  if (!Array.isArray(data) || data.length === 0) {
    return <div className="empty-state">추세 데이터가 없습니다.</div>;
  }
  const W = 640, H = 190, padT = 16, padB = 34, padL = 34, padR = 12;
  const cw = W - padL - padR, ch = H - padT - padB;
  const gap = 2;
  const bw = Math.max(4, Math.min(26, (cw - gap * data.length) / data.length));
  const offX = padL + (cw - (bw + gap) * data.length) / 2;

  const toneOf = (gp) => (gp === true ? 'var(--color-success)'
    : gp === false ? 'var(--color-danger)' : 'var(--text-muted)');

  return (
    <>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="품질 점수 추세"
        style={{ width: '100%', height: 'auto' }}>
        {[0, 25, 50, 75, 100].map((v) => {
          const y = padT + ch * (1 - v / 100);
          return (
            <g key={v}>
              <line x1={padL} x2={W - padR} y1={y} y2={y} stroke="var(--border)" strokeWidth="1" />
              <text x={padL - 4} y={y + 3} textAnchor="end"
                fontSize="9" fill="var(--text-muted)">{v}</text>
            </g>
          );
        })}
        {data.map((d, i) => {
          const score = Number(d.overall_score ?? 0);
          const barH = Math.max(1, (score / 100) * ch);
          const x = offX + i * (bw + gap);
          const y = padT + ch - barH;
          const when = d.created_at ? new Date(d.created_at) : null;
          const stamp = when ? `${when.getMonth() + 1}/${when.getDate()}` : `#${d.run_id}`;
          return (
            <g key={`${d.run_id}-${i}`}>
              <rect x={x} y={y} width={bw} height={barH} rx="2" fill={toneOf(d.gate_pass)}>
                <title>
                  {`#${d.run_id} ${d.doc_type || ''} ${score.toFixed(1)}점 · `}
                  {d.gate_pass === true ? 'PASS' : d.gate_pass === false ? 'FAIL' : '판정 없음'}
                  {d.created_at ? ` · ${fmtWhen(d.created_at)}` : ''}
                </title>
              </rect>
              {(data.length <= 10 || i % Math.ceil(data.length / 10) === 0) && (
                <text x={x + bw / 2} y={H - 8} textAnchor="middle"
                  fontSize="9" fill="var(--text-muted)">{stamp}</text>
              )}
            </g>
          );
        })}
      </svg>
      <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', margin: '4px 0 0' }}>
        막대 색은 <strong>서버 게이트 판정</strong>이다(회색 = 판정 없음). 높이는
        <code> overall_score</code> 이고 이 값은 임계 있는 지표의 평균이라
        <strong> 게이트 통과선과 다른 척도</strong>다 — 그래서 기준선을 긋지 않는다.
        막대 간격은 균일하며 <strong>시간 간격을 나타내지 않는다</strong>.
      </p>
    </>
  );
}

export default function QualityGateSection({ analysisResult, onSubChange, initialSub }) {
  const toast = useToast();

  // 프로젝트 스코프. Dashboard 가 매칭한 SCM(수동 override 포함)만 쓴다 —
  // `scmList[0]` 폴백은 남의 프로젝트 이력을 그린다.
  const scmId = analysisResult?.matchedScm?.id || '';
  const scmName = analysisResult?.matchedScm?.name || scmId;

  const [sub, setSub] = useState('runs');
  const [mounted, setMounted] = useState(() => new Set(['runs']));
  const selectSub = useCallback((id) => {
    if (!VALID_SUB.has(id)) return;
    setMounted((prev) => (prev.has(id) ? prev : new Set(prev).add(id)));
    setSub(id);
  }, []);

  // 렌더 중 조정 — effect 로 하면 한 프레임 다른 서브가 보인다
  // (`ProjectSummarySection.jsx` 와 같은 패턴).
  const [seenInitialSub, setSeenInitialSub] = useState(null);
  if (initialSub && initialSub !== seenInitialSub) {
    setSeenInitialSub(initialSub);
    if (VALID_SUB.has(initialSub)) {
      setMounted((prev) => (prev.has(initialSub) ? prev : new Set(prev).add(initialSub)));
      setSub(initialSub);
    }
  }

  useEffect(() => {
    const active = SUBS.find((s) => s.id === sub);
    if (active && onSubChange) onSubChange(active.id, active.label);
  }, [sub, onSubChange]);

  const onKeyDown = (e) => {
    const idx = SUBS.findIndex((s) => s.id === sub);
    let next = null;
    if (e.key === 'ArrowRight') next = (idx + 1) % SUBS.length;
    else if (e.key === 'ArrowLeft') next = (idx - 1 + SUBS.length) % SUBS.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = SUBS.length - 1;
    if (next == null) return;
    e.preventDefault();
    const id = SUBS[next].id;
    document.getElementById(`qgate-tab-${id}`)?.focus();
    selectSub(id);
  };

  const [docType, setDocType] = useState('');
  const [runs, setRuns] = useState([]);
  const [total, setTotal] = useState(0);
  const [runsErr, setRunsErr] = useState('');
  const [runsBusy, setRunsBusy] = useState(false);
  const [openId, setOpenId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailErr, setDetailErr] = useState('');
  const [detailBusy, setDetailBusy] = useState(false);
  const [trend, setTrend] = useState([]);
  const [trendErr, setTrendErr] = useState('');
  const [policy, setPolicy] = useState(null);
  const [policyErr, setPolicyErr] = useState('');
  const loadSeq = useRef(0);

  const scopeQuery = useCallback((extra = {}) => {
    const qs = new URLSearchParams(extra);
    if (scmId) qs.set('scm_id', scmId);
    if (docType) qs.set('doc_type', docType);
    return qs.toString();
  }, [scmId, docType]);

  /** 403 은 장애가 아니라 **권한 상태**다 — 고칠 수 없는 오류를 토스트로 반복하지 않는다. */
  const describeError = (e, what) => (e?.status === 403
    ? '권한이 없어 품질 데이터를 볼 수 없습니다.'
    : `${what}: ${e?.message || e}`);

  const loadRuns = useCallback(async () => {
    const seq = ++loadSeq.current;   // 필터 빠른 전환 시 out-of-order 응답 폐기
    setRunsBusy(true); setRunsErr('');
    try {
      const d = await api(`/api/quality/runs?${scopeQuery({ limit: '50' })}`);
      if (seq !== loadSeq.current) return;
      // quality 모듈 부재는 200 + {error} — 안 보면 "이력 0건" 과 "조회 실패" 가 같아 보인다.
      if (d?.error) throw new Error(String(d.error));
      setRuns(Array.isArray(d?.runs) ? d.runs : []);
      setTotal(Number(d?.total) || 0);
    } catch (e) {
      if (seq !== loadSeq.current) return;
      setRuns([]); setTotal(0);
      setRunsErr(describeError(e, '실행 이력을 불러오지 못했습니다'));
    } finally {
      if (seq === loadSeq.current) setRunsBusy(false);
    }
  }, [scopeQuery]);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- 마운트/필터 변경 시 조회 (콜백 첫 줄의 로딩 플래그 setState)
  useEffect(() => { loadRuns(); }, [loadRuns]);

  const loadTrend = useCallback(async () => {
    setTrendErr('');
    try {
      const d = await api(`/api/quality/trend?${scopeQuery({ last_n: '30' })}`);
      if (d?.error) throw new Error(String(d.error));
      setTrend(Array.isArray(d?.trend) ? d.trend : []);
    } catch (e) {
      setTrend([]);
      setTrendErr(describeError(e, '추세를 불러오지 못했습니다'));
    }
  }, [scopeQuery]);

  // 추세 서브탭을 **연 뒤에만** 조회한다(lazy) — 안 보는 화면 때문에 요청을 늘리지 않는다.
  // eslint-disable-next-line react-hooks/set-state-in-effect -- lazy 조회 (콜백 첫 줄의 에러 초기화 setState)
  useEffect(() => { if (mounted.has('trend')) loadTrend(); }, [mounted, loadTrend]);

  const openRun = useCallback(async (runId) => {
    if (openId === runId) { setOpenId(null); setDetail(null); return; }
    setOpenId(runId); setDetail(null); setDetailErr(''); setDetailBusy(true);
    try {
      const d = await api(`/api/quality/runs/${runId}`);
      if (d?.error) throw new Error(String(d.error));   // 옛 200+error 계약 방어
      setDetail({ run: d, meta: readRunMeta(d) });
    } catch (e) {
      setDetailErr(describeError(e, '상세를 불러오지 못했습니다'));
    } finally {
      setDetailBusy(false);
    }
  }, [openId]);

  const loadPolicy = useCallback(async () => {
    setPolicyErr('');
    try {
      setPolicy(await api('/api/quality/policy'));
    } catch (e) {
      setPolicy(null);
      setPolicyErr(describeError(e, '정책값을 불러오지 못했습니다'));
    }
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- 정책 서브탭 첫 방문 시 1회 조회
  useEffect(() => { if (mounted.has('policy') && !policy && !policyErr) loadPolicy(); },
    [mounted, policy, policyErr, loadPolicy]);

  const advise = useCallback(async (runId) => {
    try {
      const d = await post(`/api/quality/runs/${runId}/advice`, {});
      if (d?.error) throw new Error(String(d.error));
      const n = Number(d?.suggestion_count ?? (d?.suggestions || []).length);
      setDetail((prev) => (prev && prev.run?.id === runId ? { ...prev, advice: d } : prev));
      toast('info', d?.summary || (n ? `개선 제안 ${n}건` : '개선 제안이 없습니다.'));
    } catch (e) {
      toast('error', `개선 제안 실패: ${e?.message || e}`);
    }
  }, [toast]);

  // 판정이 없는 run 비율 — 사실만 표시한다(가짜라는 뜻이 아니라 판별 불가).
  const verdictNote = useMemo(() => {
    if (!runs.length) return null;
    const withVerdict = runs.filter(
      (r) => r?.summary && r.summary.gate_pass !== null && r.summary.gate_pass !== undefined
    ).length;
    return { shown: runs.length, withVerdict };
  }, [runs]);

  return (
    <div className="quality-gate-section">
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">🚦 품질 게이트</span>
          <span style={{ marginLeft: 'auto', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
            {scmId ? `프로젝트 ${scmName}` : '전체 프로젝트'}
          </span>
        </div>
        <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', margin: '0 0 var(--sp-3)' }}>
          이미 기록된 게이트 근거를 <strong>조회</strong>합니다. 이 화면은 판정을 새로
          계산하지 않습니다 — 서버가 낸 값을 그대로 보여 줍니다.
        </p>

        <nav className="subnav" role="tablist" aria-label="품질 게이트 영역" onKeyDown={onKeyDown}>
          {SUBS.map((s) => (
            <button key={s.id} id={`qgate-tab-${s.id}`} type="button" role="tab"
              aria-selected={sub === s.id} aria-controls={`qgate-panel-${s.id}`}
              tabIndex={sub === s.id ? 0 : -1}
              className={`tab-item${sub === s.id ? ' active' : ''}`}
              onClick={() => selectSub(s.id)}>
              {s.label}
            </button>
          ))}
        </nav>

        {/* ── 실행 이력 ── */}
        <div role="tabpanel" id="qgate-panel-runs" aria-labelledby="qgate-tab-runs"
          tabIndex={sub === 'runs' ? 0 : -1}
          style={{ display: sub === 'runs' ? 'block' : 'none' }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: 'var(--sp-3) 0' }}>
            <label htmlFor="qgate-doc-type" style={{ fontSize: 'var(--text-sm)' }}>문서 종류</label>
            <select id="qgate-doc-type" value={docType} onChange={(e) => setDocType(e.target.value)}>
              {DOC_TYPES.map((t) => <option key={t.value || 'all'} value={t.value}>{t.label}</option>)}
            </select>
            <button type="button" className="btn-secondary btn-sm" onClick={loadRuns} disabled={runsBusy}>
              {runsBusy ? '조회 중…' : '새로고침'}
            </button>
            <span style={{ color: 'var(--text-muted)', fontSize: 'var(--text-xs)' }}>
              총 {total}건 중 {runs.length}건 표시
            </span>
          </div>

          {runsErr && (
            <div role="alert" style={{ color: 'var(--color-danger)', fontSize: 'var(--text-sm)', marginBottom: 'var(--sp-2)' }}>
              {runsErr}
            </div>
          )}

          {!runsErr && verdictNote && verdictNote.withVerdict < verdictNote.shown && (
            <div role="status" style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--sp-2)' }}>
              표시된 {verdictNote.shown}건 중 {verdictNote.shown - verdictNote.withVerdict}건은
              요약이 없어 <strong>판정 없음</strong>입니다 — 통과도 실패도 아닙니다.
            </div>
          )}

          <div style={{ overflowX: 'auto' }}>
            <table className="board-table">
              <thead>
                <tr>
                  <th>run</th><th>문서</th>
                  {!scmId && <th>프로젝트</th>}
                  <th>생성 시각</th>
                  <th style={{ textAlign: 'right' }}>점수</th>
                  <th>게이트</th><th aria-label="작업" />
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => {
                  const g = gateLabel(r?.summary?.gate_pass ?? null);
                  return (
                    <tr key={r.id}>
                      <td>#{r.id}</td>
                      <td>{r.doc_type}</td>
                      {!scmId && (
                        <td style={{ fontSize: 'var(--text-xs)' }}>
                          {r.scm_id || <span style={{ color: 'var(--text-muted)' }}>미상</span>}
                        </td>
                      )}
                      <td style={{ fontSize: 'var(--text-xs)' }}>{fmtWhen(r.created_at)}</td>
                      <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                        {r?.summary ? Number(r.summary.overall_score).toFixed(1) : '—'}
                      </td>
                      <td><StatusBadge tone={g.tone}>{g.text}</StatusBadge></td>
                      <td>
                        <button type="button" className="btn-secondary btn-sm"
                          onClick={() => openRun(r.id)} aria-expanded={openId === r.id}>
                          {openId === r.id ? '접기' : '근거 보기'}
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {!runs.length && !runsBusy && !runsErr && (
                  <tr>
                    <td colSpan={scmId ? 6 : 7} style={{ color: 'var(--text-muted)' }}>
                      이력이 없습니다.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {openId != null && (
            <div className="panel" style={{ marginTop: 'var(--sp-3)' }}>
              {detailBusy && <div>불러오는 중…</div>}
              {detailErr && (
                <div role="alert" style={{ color: 'var(--color-danger)', fontSize: 'var(--text-sm)' }}>{detailErr}</div>
              )}
              {detail && (
                <>
                  <h3 style={{ marginTop: 0 }}>run #{detail.run.id} 게이트 근거</h3>
                  <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                    {detail.meta.gatedCount == null
                      ? '⚠ 검사 규모 미기록 — 몇 개 항목을 검사했는지 복원할 수 없습니다(가짜라는 뜻이 아니라 판별 불가입니다).'
                      : `게이트 대상 지표 ${detail.meta.gatedCount}개`}
                    {' · '}
                    {detail.meta.definition == null
                      ? '⚠ 게이트 정의 미상 — 이 행이 어느 판정 규칙으로 나왔는지 기록이 없습니다.'
                      : `판정 정의: ${detail.meta.definition}`}
                    {detail.meta.reason && ` · 판정 사유: ${detail.meta.reason}`}
                  </p>
                  <div style={{ overflowX: 'auto' }}>
                    <table className="board-table">
                      <thead><tr><th>지표</th><th style={{ textAlign: 'right' }}>값</th><th style={{ textAlign: 'right' }}>임계</th><th>판정</th></tr></thead>
                      <tbody>
                        {(detail.run.scores || []).map((s, i) => {
                          const g = gateLabel(s?.gate_pass ?? null);
                          return (
                            <tr key={`${s.metric_name}-${i}`}>
                              <td>{s.metric_name}</td>
                              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                                {s.value == null ? '—' : Number(s.value).toFixed(2)}
                              </td>
                              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                                {s.threshold == null ? '—(비게이트)' : Number(s.threshold).toFixed(2)}
                              </td>
                              <td><StatusBadge tone={g.tone}>{g.text}</StatusBadge></td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <button type="button" className="btn-secondary btn-sm" style={{ marginTop: 'var(--sp-2)' }}
                    onClick={() => advise(detail.run.id)}>
                    개선 제안 생성
                  </button>
                  {detail.advice?.suggestions?.length > 0 && (
                    <ol style={{ marginTop: 'var(--sp-2)', paddingLeft: '1.2em', fontSize: 'var(--text-xs)', lineHeight: 1.7 }}>
                      {detail.advice.suggestions.map((s, i) => (
                        <li key={`${s.metric}-${i}`}>
                          <strong>{s.label || s.metric}</strong>
                          {s.advice && <> — {s.advice}</>}
                        </li>
                      ))}
                    </ol>
                  )}
                </>
              )}
            </div>
          )}
        </div>

        {/* ── 점수 추세 ── */}
        <div role="tabpanel" id="qgate-panel-trend" aria-labelledby="qgate-tab-trend"
          tabIndex={sub === 'trend' ? 0 : -1}
          style={{ display: sub === 'trend' ? 'block' : 'none' }}>
          {mounted.has('trend') && (
            <div style={{ marginTop: 'var(--sp-3)' }}>
              {trendErr && (
                <div role="alert" style={{ color: 'var(--color-danger)', fontSize: 'var(--text-sm)' }}>{trendErr}</div>
              )}
              {!trendErr && <TrendChart data={trend} />}
            </div>
          )}
        </div>

        {/* ── 정책값 ── */}
        <div role="tabpanel" id="qgate-panel-policy" aria-labelledby="qgate-tab-policy"
          tabIndex={sub === 'policy' ? 0 : -1}
          style={{ display: sub === 'policy' ? 'block' : 'none' }}>
          {mounted.has('policy') && (
            <div style={{ marginTop: 'var(--sp-3)' }}>
              {policyErr && (
                <div role="alert" style={{ color: 'var(--color-danger)', fontSize: 'var(--text-sm)' }}>{policyErr}</div>
              )}
              {policy?.notes?.length > 0 && (
                <ul style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                  {policy.notes.map((n) => <li key={n}>{n}</li>)}
                </ul>
              )}
              {(policy?.tables || []).map((t) => (
                <div key={t.key} style={{ marginBottom: 'var(--sp-5)' }}>
                  <h3 style={{ marginBottom: 4, display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                    <span>{t.label}</span>
                    <StatusBadge tone={t.status === 'applied' ? 'success' : 'neutral'}>
                      {t.status_label}
                    </StatusBadge>
                    <StatusBadge tone={t.adjustable === 'env' ? 'info' : 'neutral'}>
                      {t.adjustable_label}
                    </StatusBadge>
                  </h3>
                  <div style={{ overflowX: 'auto' }}>
                    <table className="board-table">
                      <thead><tr><th>키</th><th>값</th><th>환경변수</th></tr></thead>
                      <tbody>
                        {(t.entries || []).map((e) => (
                          <tr key={e.key}>
                            <td>{e.key}</td>
                            <td>{typeof e.value === 'object' ? JSON.stringify(e.value) : String(e.value)}</td>
                            <td>{e.env_name || '—'}{e.env_set ? ' (설정됨)' : ''}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
