import { useState, useEffect, useCallback, useMemo } from 'react';
import { api, post } from '../../api.js';
import { useToast } from '../../App.jsx';

/**
 * GateReviewSection — "🚦 품질 게이트" 탭 (§6-1 후보 22, G1·G2·G4).
 *
 * ## 무엇을 하는 섹션인가
 *
 * 이미 계산·영속되는데 **화면에 못 오던** 게이트 근거를 한 자리에서 조회한다.
 * 신규 판정 로직은 0개다 — 서버가 낸 `gate_pass` 를 그대로 보여 준다.
 *
 * ## 설계상 방어 (이 저장소 규약: "미측정을 통과로 바꾸지 않는다")
 *
 * - **`gate_pass` 를 프론트에서 재계산하지 않는다.** `QualityDashboard.jsx:24,86` 의
 *   `?? (score >= 70)` 폴백을 **재사용하지 않는다** — 임계 70 을 프론트에 다시 두면
 *   서버 판정과 갈라진다. 부재는 PASS 도 FAIL 도 아닌 **'판정 없음'** 이다.
 * - **`gated_metric_count` 가 없는 run 은 '검사 규모 미기록'으로 분리**한다. 실측
 *   72.9%(546/749)가 이 상태이고 그중 `gate_pass=1` 이 182건이다. 가짜라는 뜻이
 *   아니라 **판별 불가**라고 문구에 명시한다.
 * - **`gate_definition:` 마커가 없는 run 은 '게이트 정의 미상'** 으로 표시한다.
 *   같은 컬럼에 두 정의가 섞여 있고(동기 경로만 3중 판정, 나머지 3경로는 bare
 *   quick_gate) 마커 보유는 51/749 뿐이다. 마커 없는 698건을 단일 판정으로 그리면
 *   그 자체가 거짓 증거다.
 * - **`project_root` 로 필터하지 않는다.** UDS run 3건이 전부 NULL 이라
 *   "UDS 는 볼 게 없다" 로 보인다(§6-1 S7).
 *
 * ## 실측으로 고친 계약
 *
 * `GET /api/quality/runs/{id}` 는 미존재 run 에 **HTTP 200 + `{error}`** 를 돌려줬다.
 * `api.js:145` 가 `res.ok` 만 보므로 프론트가 에러를 성공으로 삼킨다 — 백엔드를 404 로
 * 바로잡았고(소비자가 0건이던 지금이 유일하게 무해한 시점), 여기서도 `error` 키를
 * 방어적으로 한 번 더 본다.
 *
 * ## 안 만든 것 (명시적 제외)
 *
 * 검토 **기록(쓰기)** 은 이 파일에 없다 — G5/G6 은 신규 테이블 + 인증 결정(JWT 필수,
 * `X-User` 폴백 거부)이 선행이라 별도 단계다. 여기까지는 **조회 전용**이다.
 */

const SUBS = [
  { id: 'runs', label: '실행 이력' },
  { id: 'policy', label: '정책값' },
];
const VALID_SUB = new Set(SUBS.map((s) => s.id));

const DOC_TYPES = ['', 'uds', 'sts', 'suts', 'sits', 'swut', 'swit', 'swsa', 'swreport'];

/** 서버 판정을 **그대로** 라벨로 — 프론트 재계산 금지. */
function gateLabel(gatePass) {
  if (gatePass === true) return { text: 'PASS', bg: 'var(--color-success)' };
  if (gatePass === false) return { text: 'FAIL', bg: 'var(--color-danger)' };
  return { text: '판정 없음', bg: 'var(--text-muted)' };
}

function Pill({ text, bg, title }) {
  return (
    <span title={title || text} style={{
      display: 'inline-block', padding: '1px 8px', borderRadius: 'var(--radius-sm)',
      fontSize: 'var(--text-xs)', fontWeight: 600, color: '#fff', background: bg,
    }}>{text}</span>
  );
}

/** scores 배열에서 검사 규모/정의 마커를 뽑는다. 없으면 `null`(= 미기록). */
function readRunMeta(scores) {
  const rows = Array.isArray(scores) ? scores : [];
  const gatedRow = rows.find((s) => s?.metric_name === 'gated_metric_count');
  const defRow = rows.find((s) => String(s?.metric_name || '').startsWith('gate_definition:'));
  return {
    gatedCount: gatedRow ? Number(gatedRow.value) : null,
    definition: defRow ? String(defRow.metric_name).slice('gate_definition:'.length) : null,
  };
}

export default function GateReviewSection({ onSubChange, initialSub }) {
  const toast = useToast();
  const [sub, setSub] = useState('runs');
  const [mounted, setMounted] = useState(() => new Set(['runs']));
  const selectSub = useCallback((id) => {
    if (!VALID_SUB.has(id)) return;
    setMounted((prev) => (prev.has(id) ? prev : new Set(prev).add(id)));
    setSub(id);
  }, []);
  // 렌더 중 조정 — effect 로 하면 한 프레임 다른 서브가 보이고 lint 게이트에도 걸린다
  // (`ProjectSummarySection.jsx:141-151` 과 같은 패턴).
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

  const [docType, setDocType] = useState('');
  const [runs, setRuns] = useState([]);
  const [total, setTotal] = useState(0);
  const [runsErr, setRunsErr] = useState('');
  const [runsBusy, setRunsBusy] = useState(false);
  const [openId, setOpenId] = useState(null);
  const [detail, setDetail] = useState(null);      // {run, meta}
  const [detailErr, setDetailErr] = useState('');
  const [detailBusy, setDetailBusy] = useState(false);
  const [policy, setPolicy] = useState(null);
  const [policyErr, setPolicyErr] = useState('');

  const loadRuns = useCallback(async () => {
    setRunsBusy(true); setRunsErr('');
    try {
      const q = docType ? `?doc_type=${encodeURIComponent(docType)}&limit=50` : '?limit=50';
      const d = await api(`/api/quality/runs${q}`);
      // ⚠ 이 endpoint 는 quality 모듈 부재 시 `{runs: [], error}` 를 낸다(200).
      //    `error` 를 안 보면 "이력 0건" 과 "조회 실패" 가 같아 보인다.
      if (d?.error) throw new Error(String(d.error));
      setRuns(Array.isArray(d?.runs) ? d.runs : []);
      setTotal(Number(d?.total) || 0);
    } catch (e) {
      setRuns([]); setTotal(0);
      setRunsErr(e?.status === 403
        ? '관리자 권한이 필요합니다.'
        : `실행 이력을 불러오지 못했습니다: ${e?.message || e}`);
    } finally {
      setRunsBusy(false);
    }
  }, [docType]);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- 마운트/필터 변경 시 이력 조회 — 콜백 첫 줄의 로딩 플래그 setState (AiAssistSection.jsx:125 와 동일 규약)
  useEffect(() => { loadRuns(); }, [loadRuns]);

  const openRun = useCallback(async (runId) => {
    if (openId === runId) { setOpenId(null); setDetail(null); return; }
    setOpenId(runId); setDetail(null); setDetailErr(''); setDetailBusy(true);
    try {
      const d = await api(`/api/quality/runs/${runId}`);
      if (d?.error) throw new Error(String(d.error));   // 옛 200+error 계약 방어
      setDetail({ run: d, meta: readRunMeta(d?.scores) });
    } catch (e) {
      setDetailErr(`상세를 불러오지 못했습니다: ${e?.message || e}`);
    } finally {
      setDetailBusy(false);
    }
  }, [openId]);

  const loadPolicy = useCallback(async () => {
    setPolicyErr('');
    try {
      const d = await api('/api/quality/policy');
      setPolicy(d);
    } catch (e) {
      setPolicy(null);
      setPolicyErr(`정책값을 불러오지 못했습니다: ${e?.message || e}`);
    }
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- 정책 서브탭 첫 방문 시 1회 조회 — 콜백 첫 줄의 에러 초기화 setState
  useEffect(() => { if (mounted.has('policy') && !policy && !policyErr) loadPolicy(); },
    [mounted, policy, policyErr, loadPolicy]);

  const advise = useCallback(async (runId) => {
    try {
      const d = await post(`/api/quality/runs/${runId}/advice`, {});
      if (d?.error) throw new Error(String(d.error));
      toast('info', d?.summary || '개선 제안을 생성했습니다.');
    } catch (e) {
      toast('error', `개선 제안 실패: ${e?.message || e}`);
    }
  }, [toast]);

  // 검사 규모 미기록 비율 — 목록 상단에 사실만 표시한다.
  const unrecordedNote = useMemo(() => {
    if (!runs.length) return null;
    const n = runs.filter((r) => r?.summary && r.summary.gate_pass !== null
      && r.summary.gate_pass !== undefined).length;
    return { shown: runs.length, withVerdict: n };
  }, [runs]);

  return (
    <div className="section">
      <h2 className="section-title">🚦 품질 게이트</h2>
      <p style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)', margin: '4px 0 12px' }}>
        이미 기록된 게이트 근거를 <strong>조회</strong>합니다. 이 화면은 판정을 새로
        계산하지 않습니다 — 서버가 낸 값을 그대로 보여 줍니다.
      </p>

      <nav className="subnav" role="tablist" aria-label="품질 게이트 영역">
        {SUBS.map((s) => (
          <button key={s.id} id={`gate-tab-${s.id}`} type="button" role="tab"
            aria-selected={sub === s.id} aria-controls={`gate-panel-${s.id}`}
            className={`tab-item${sub === s.id ? ' active' : ''}`}
            onClick={() => selectSub(s.id)}>
            {s.label}
          </button>
        ))}
      </nav>

      <div role="tabpanel" id="gate-panel-runs" aria-labelledby="gate-tab-runs"
        style={{ display: sub === 'runs' ? 'block' : 'none' }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', margin: '10px 0' }}>
          <label htmlFor="gate-doc-type" style={{ fontSize: 'var(--text-sm)' }}>문서 종류</label>
          <select id="gate-doc-type" value={docType} onChange={(e) => setDocType(e.target.value)}>
            {DOC_TYPES.map((t) => <option key={t || 'all'} value={t}>{t || '전체'}</option>)}
          </select>
          <button type="button" className="btn-sm" onClick={loadRuns} disabled={runsBusy}>
            {runsBusy ? '조회 중…' : '새로고침'}
          </button>
          <span style={{ color: 'var(--text-muted)', fontSize: 'var(--text-xs)' }}>
            총 {total}건 중 {runs.length}건 표시
          </span>
        </div>

        {runsErr && <div className="alert alert-error" role="alert">{runsErr}</div>}

        {!runsErr && unrecordedNote && unrecordedNote.withVerdict < unrecordedNote.shown && (
          <div className="alert alert-info" role="status">
            표시된 {unrecordedNote.shown}건 중 {unrecordedNote.shown - unrecordedNote.withVerdict}건은
            요약이 없어 <strong>판정 없음</strong>입니다 — 통과도 실패도 아닙니다.
          </div>
        )}

        <table className="data-table">
          <thead>
            <tr>
              <th>run</th><th>문서</th><th>생성 시각</th><th>점수</th><th>게이트</th><th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => {
              const g = gateLabel(r?.summary?.gate_pass ?? null);
              return (
                <tr key={r.id}>
                  <td>#{r.id}</td>
                  <td>{r.doc_type}</td>
                  <td>{r.created_at ? new Date(r.created_at).toLocaleString('ko-KR') : '—'}</td>
                  <td>{r?.summary ? Number(r.summary.overall_score).toFixed(1) : '—'}</td>
                  <td><Pill text={g.text} bg={g.bg} /></td>
                  <td>
                    <button type="button" className="btn-sm" onClick={() => openRun(r.id)}
                      aria-expanded={openId === r.id}>
                      {openId === r.id ? '접기' : '근거 보기'}
                    </button>
                  </td>
                </tr>
              );
            })}
            {!runs.length && !runsBusy && !runsErr && (
              <tr><td colSpan={6} style={{ color: 'var(--text-muted)' }}>이력이 없습니다.</td></tr>
            )}
          </tbody>
        </table>

        {openId != null && (
          <div className="panel" style={{ marginTop: 12 }}>
            {detailBusy && <div>불러오는 중…</div>}
            {detailErr && <div className="alert alert-error" role="alert">{detailErr}</div>}
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
                </p>
                <table className="data-table">
                  <thead><tr><th>지표</th><th>값</th><th>임계</th><th>판정</th></tr></thead>
                  <tbody>
                    {(detail.run.scores || []).map((s, i) => {
                      const g = gateLabel(s?.gate_pass ?? null);
                      return (
                        <tr key={`${s.metric_name}-${i}`}>
                          <td>{s.metric_name}</td>
                          <td>{s.value == null ? '—' : Number(s.value).toFixed(2)}</td>
                          <td>{s.threshold == null ? '—(비게이트)' : Number(s.threshold).toFixed(2)}</td>
                          <td><Pill text={g.text} bg={g.bg} /></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <button type="button" className="btn-sm" onClick={() => advise(detail.run.id)}>
                  개선 제안 생성
                </button>
              </>
            )}
          </div>
        )}
      </div>

      <div role="tabpanel" id="gate-panel-policy" aria-labelledby="gate-tab-policy"
        style={{ display: sub === 'policy' ? 'block' : 'none' }}>
        {mounted.has('policy') && (
          <>
            {policyErr && <div className="alert alert-error" role="alert">{policyErr}</div>}
            {policy?.notes?.length > 0 && (
              <ul style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                {policy.notes.map((n) => <li key={n}>{n}</li>)}
              </ul>
            )}
            {(policy?.tables || []).map((t) => (
              <div key={t.key} style={{ marginBottom: 18 }}>
                <h3 style={{ marginBottom: 4 }}>
                  {t.label}{' '}
                  <Pill text={t.status_label}
                    bg={t.status === 'applied' ? 'var(--color-success)' : 'var(--text-muted)'} />
                  {' '}
                  <Pill text={t.adjustable_label}
                    bg={t.adjustable === 'env' ? 'var(--color-info, #3b82f6)' : 'var(--text-muted)'} />
                </h3>
                <table className="data-table">
                  <thead><tr><th>키</th><th>값</th><th>환경변수</th></tr></thead>
                  <tbody>
                    {(t.entries || []).map((e) => (
                      <tr key={e.key}>
                        <td>{e.key}</td>
                        <td>{typeof e.value === 'object'
                          ? JSON.stringify(e.value) : String(e.value)}</td>
                        <td>
                          {e.env_name || '—'}
                          {e.env_set ? ' (설정됨)' : ''}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </>
        )}
      </div>
    </div>
  );
}
