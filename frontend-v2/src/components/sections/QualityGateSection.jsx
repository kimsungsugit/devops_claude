import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { api, post, getUsername } from '../../api.js';
import { useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';
import {
  verdictOf, trendVerdictOf, metricVerdictOf, TONE_COLOR,
  reviewVerdictOf, reviewErrorText, reviewFreshnessOf, reviewDecisionTone, REVIEW_DECISIONS, REVIEW_DECISION_LABEL,
  hashReasonText, basisReasonText, reviewBlockText, emptyOutputText,
} from '../../gateVerdict.js';

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
  // (R35 C-3) 검토 기록 감사 이력 — `/api/review/history`. 챗 승인 감사와 별개다.
  { id: 'reviews', label: '검토 이력' },
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

// (R31 Q-6) run 판정은 `gateVerdict.js::verdictOf` 단일 출처 — 예전엔 여기 로컬 `gateLabel` 이
// `summary.gate_pass` 만 봐서 검사 0건(no_gated_metric) run 을 보드는 "판정 불가", 이 목록은 "FAIL" 로
// 그렸다. 프론트 재계산 금지(`?? (score>=70)` 을 되살리지 말 것)는 그 모듈이 지킨다.

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

  // 막대 색·툴팁 라벨은 목록과 **같은 판정기**에서 — `/trend` 가 `gate_reason`·`gated_metric_count` 를
  // 실으므로 검사 0건은 빨강이 아니라 경고색 "판정 불가" 다(캡션 약속과 일치).
  const verdictOfBar = (d) => trendVerdictOf(d);

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
              <rect x={x} y={y} width={bw} height={barH} rx="2"
                fill={TONE_COLOR[verdictOfBar(d).tone] || TONE_COLOR.neutral}
                data-verdict={verdictOfBar(d).label}>
                <title>
                  {`#${d.run_id} ${d.doc_type || ''} ${score.toFixed(1)}점 · `}
                  {verdictOfBar(d).label}
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
        막대 색은 <strong>서버 게이트 판정</strong>이다(회색 = 판정 없음 · 경고색 = 판정 불가, 검사 항목 0개). 높이는
        <code> overall_score</code> 이고 이 값은 임계 있는 지표의 평균이라
        <strong> 게이트 통과선과 다른 척도</strong>다 — 그래서 기준선을 긋지 않는다.
        막대 간격은 균일하며 <strong>시간 간격을 나타내지 않는다</strong>.
      </p>
    </>
  );
}

/**
 * (R35 C-3) 검토 기록 패널 — run 하나. 어휘는 '검토 기록'('승인' 은 실행을 뜻하지 않는다, S14).
 *
 * - 판정·라벨·오류 문구는 `gateVerdict.js` 한 곳(복제 금지 가드가 잰다).
 * - 해시 없는 run 은 **검토 잠금** — 폼을 그리지 않는다(S6). 빈칸이 아니라 잠금 사유를 적는다.
 * - `expected_sha256` 은 서버가 준 run 해시를 **그대로** 되돌려 보낸다(프론트 계산 0). 갱신은 내 기록의 `version`.
 * - 성공 토스트는 **2xx 뒤에만**. 409 `STALE`/`VERSION_CONFLICT` 는 상태를 다시 받는다.
 * - `can_review` 는 서버 값 — admin 1명 = 단독 검토임을 문구로 밝힌다(§8 #8). **쓰기 endpoint 와 같은 조건**
 *   (admin **그리고** Bearer)이라 이 폼이 보이면 저장이 통과한다. 못 쓰는 사유는 `review_block_reason`.
 */
function ReviewPanel({ runId, onSaved }) {
  const toast = useToast();
  const [state, setState] = useState(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [decision, setDecision] = useState('');
  const [comment, setComment] = useState('');
  const [saving, setSaving] = useState(false);
  const seq = useRef(0);
  const me = getUsername();

  const load = useCallback(async () => {
    const my = ++seq.current;
    setBusy(true); setErr('');
    try {
      const d = await api(`/api/review/runs/${runId}`);
      if (my !== seq.current) return;
      if (d?.error) throw new Error(String(d.error));   // 200+error 방어(계약상 없다)
      setState(d);
      const mine = (d.reviews || []).find((r) => r.reviewer === me);
      setDecision(mine?.decision || '');
      setComment(mine?.comment || '');
    } catch (e) {
      if (my !== seq.current) return;
      setState(null);
      setErr(e?.status === 403 ? '권한이 없어 검토 기록을 볼 수 없습니다.' : `검토 기록을 불러오지 못했습니다: ${e?.message || e}`);
    } finally {
      if (my === seq.current) setBusy(false);
    }
  }, [runId, me]);

  // eslint-disable-next-line react-hooks/set-state-in-effect -- run 이 바뀔 때 조회 (콜백 첫 줄의 로딩 플래그 setState)
  useEffect(() => { load(); }, [load]);

  const mine = state ? (state.reviews || []).find((r) => r.reviewer === me) : null;

  const save = async () => {
    if (!state || !decision) return;
    setSaving(true);
    try {
      const body = { decision, comment: comment.trim() ? comment : null, expected_sha256: state.output_sha256 };
      if (mine) body.version = mine.version;
      const d = await post(`/api/review/runs/${runId}`, body);
      if (d?.error) throw new Error(String(d.error));
      toast('success', d?.created ? '검토 기록을 저장했습니다.' : '검토 기록을 갱신했습니다.');
      await load();
      if (onSaved) onSaved();
    } catch (e) {
      toast('error', reviewErrorText(e));
      // 산출물이 바뀌었거나 남이 먼저 저장했다 — 지금 값을 다시 받아야 다음 저장이 뜻을 갖는다.
      if (e?.code === 'STALE' || e?.code === 'VERSION_CONFLICT') await load();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="panel" style={{ marginTop: 'var(--sp-3)' }} data-testid="review-panel">
      <h3 style={{ marginTop: 0 }}>run #{runId} 검토 기록</h3>
      {busy && <div>불러오는 중…</div>}
      {err && <div role="alert" style={{ color: 'var(--color-danger)', fontSize: 'var(--text-sm)' }}>{err}</div>}
      {state && (
        <>
          {state.hash_unavailable ? (
            <p role="status" style={{ fontSize: 'var(--text-sm)' }}>
              <StatusBadge tone="neutral">검토 잠금</StatusBadge>{' '}
              산출물 해시가 없어 무엇을 검토했는지 고정할 수 없습니다 — 기록을 받지 않습니다.
              {' '}사유: {state.hash_reason
                ? <><code>{state.hash_reason}</code> — {hashReasonText(state.hash_reason)}</>
                : <span>미기록 (해시 기록 이전의 구 run)</span>}
              . 문서를 다시 생성하면 새 run 에 해시가 남습니다.
            </p>
          ) : (
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
              산출물 해시 <code>{String(state.output_sha256).slice(0, 12)}…</code>
              {' · '}
              {state.stale === true && <strong style={{ color: 'var(--color-warning)' }}>⚠ 지금 파일이 이 run 의 기록과 다릅니다 — 검토는 기록된 산출물에 붙습니다.</strong>}
              {state.stale === false && '지금 파일과 일치'}
              {state.stale == null && (basisReasonText(state.current_basis_reason) || '파일 기준으로 다시 잴 수 없습니다')}
              {' · '}
              {/* (R36 실측) openpyxl 이 `docProps/core.xml` 에 **초 단위** 저장 시각을 쓴다 — 같은 초 안 6회는 해시가 같고
                  1.1초를 넘기면 달라졌다. "생성마다 다르다" 는 반례가 있어 단정하지 않는다(리뷰 W4). */}
              다시 생성하면 대개 해시가 달라집니다(문서에 저장 시각이 들어갑니다) — 해시가 같아도 같은 run 이라는 뜻은 아닙니다.
              {' '}내려받은 파일과 대조하려면 PowerShell <code>Get-FileHash &lt;파일&gt; -Algorithm SHA256</code>.
            </p>
          )}
          {state.superseded_by && (
            <p role="status" style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
              더 새로운 run <strong>#{state.superseded_by.run_id}</strong>
              {state.superseded_by.created_at ? ` (${fmtWhen(state.superseded_by.created_at)})` : ''} 이 같은 프로젝트·문서에 있습니다 —
              이 검토는 그 run 을 대상으로 하지 않습니다.
            </p>
          )}
          {/* (R37 리뷰 C1) 빈 산출물은 **잴 대상이 0건**(해당 없음)이지 "기록이 안 됐다"(미측정)가 아니다.
              아래 '검사 규모 미기록' 문구는 *구 run* 을 뜻하므로, 여기서 갈라 두지 않으면 원인을 틀리게 댄다.
              승인 자체는 막지 않는다 — 대상은 바이트이고 해시가 있다. 다만 무엇을 승인하는지는 말한다. */}
          {state.status === 'empty_output' && (
            <p role="status" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-warning)' }}>
              ⚠ 이 run 은 <strong>산출물에 담을 내용이 0건</strong>이라 점수가 없습니다 —
              승인하면 <strong>빈 문서에 대한 승인</strong>이 됩니다.
              {emptyOutputText(state) ? ` ${emptyOutputText(state)}` : ''}
            </p>
          )}
          {state.status !== 'empty_output' && state.gated_metric_count == null && (
            <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
              ⚠ 검사 규모 미기록 run 입니다 — 검토는 허용되지만 몇 개 항목을 검사했는지는 복원할 수 없습니다.
            </p>
          )}

          {(state.reviews || []).length > 0 ? (
            <div style={{ overflowX: 'auto' }}>
              <table className="board-table">
                <thead><tr><th>검토자</th><th>판정</th><th>사유</th><th>최신성</th><th>갱신</th></tr></thead>
                <tbody>
                  {state.reviews.map((r) => {
                    const f = reviewFreshnessOf(r);
                    return (
                      <tr key={r.id}>
                        <td>{r.reviewer}{r.reviewer === me ? ' (나)' : ''}</td>
                        <td><StatusBadge tone={reviewDecisionTone(r.decision)}>{REVIEW_DECISION_LABEL[r.decision] || r.decision}</StatusBadge></td>
                        <td style={{ whiteSpace: 'pre-wrap', fontSize: 'var(--text-xs)' }}>{r.comment || <span style={{ color: 'var(--text-muted)' }}>—</span>}</td>
                        <td><StatusBadge tone={f.tone}>{f.label}</StatusBadge></td>
                        <td style={{ fontSize: 'var(--text-xs)' }}>{fmtWhen(r.updated_at)} · v{r.version}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-muted)' }}>검토 기록이 없습니다(미검토).</p>
          )}

          {!state.hash_unavailable && state.can_review === true && (
            <form onSubmit={(e) => { e.preventDefault(); save(); }} style={{ marginTop: 'var(--sp-3)' }} aria-label="검토 기록 입력">
              <fieldset style={{ border: 0, padding: 0, margin: 0 }}>
                <legend style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>{mine ? '내 검토 갱신' : '검토 기록'}</legend>
                <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', margin: '6px 0' }}>
                  {REVIEW_DECISIONS.map((d) => (
                    <label key={d} style={{ fontSize: 'var(--text-sm)' }}>
                      <input type="radio" name={`review-decision-${runId}`} value={d}
                        checked={decision === d} onChange={() => setDecision(d)} />{' '}
                      {REVIEW_DECISION_LABEL[d]}
                    </label>
                  ))}
                </div>
                <textarea aria-label="검토 사유" value={comment} maxLength={2000} rows={3}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="사유(선택, 2000자 이내)" style={{ width: '100%', boxSizing: 'border-box' }} />
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6 }}>
                  <button type="submit" className="btn-primary btn-sm" disabled={saving || !decision}>
                    {saving ? '저장 중…' : (mine ? '갱신' : '저장')}
                  </button>
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                    JWT 로그인한 admin 만 기록합니다(현재 admin 은 단독 검토입니다). 검토는 게이트 판정을 바꾸지 않습니다.
                    {' '}검토자 이름은 admin 과 본인에게만 그대로 보입니다.
                  </span>
                </div>
              </fieldset>
            </form>
          )}
          {!state.hash_unavailable && state.can_review !== true && (
            <p role="status" style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 'var(--sp-2)' }}>
              {/* (R37 D-1) 사유를 서버가 갈라 준다 — '권한 없음' 과 '토큰 만료' 는 벗어나는 길이 다르다. */}
              {reviewBlockText(state.review_block_reason)}
            </p>
          )}
        </>
      )}
    </div>
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
  // (R35) 목록 '검토' 열 — 해시 있는 run 만 배치 조회한다(해시 없는 run 은 목록 값만으로 '검토 잠금').
  const [reviewStates, setReviewStates] = useState({});
  // 서버가 "없다" 고 답한 id(리뷰 W1) — '조회 중' 으로 남기지 않는다. `done` 은 배치가 끝났다는 사실.
  const [reviewMissing, setReviewMissing] = useState(() => new Set());
  const [reviewDone, setReviewDone] = useState(false);
  const [reviewStatesErr, setReviewStatesErr] = useState('');
  const [reviewHistory, setReviewHistory] = useState(null);
  const [historyErr, setHistoryErr] = useState('');
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
      const list = Array.isArray(d?.runs) ? d.runs : [];
      setRuns(list);
      setTotal(Number(d?.total) || 0);
      // 검토 열 — 목록과 같은 세대(seq)로 묶는다. 실패는 열에 '조회 실패' 로 드러낸다(빈칸 금지).
      const ids = list.filter((r) => r?.output_sha256 != null).map((r) => r.id);
      setReviewStates({}); setReviewMissing(new Set()); setReviewDone(false); setReviewStatesErr('');
      if (ids.length) {
        try {
          const st = await api(`/api/review/states?run_ids=${ids.join(',')}`);
          if (seq !== loadSeq.current) return;
          if (st?.error) throw new Error(String(st.error));
          setReviewStates(st?.states || {});
          setReviewMissing(new Set((Array.isArray(st?.missing) ? st.missing : []).map(String)));
          setReviewDone(true);
        } catch (e) {
          if (seq !== loadSeq.current) return;
          setReviewStatesErr(describeError(e, '검토 상태를 불러오지 못했습니다'));
        }
      }
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

  const loadHistory = useCallback(async () => {
    setHistoryErr('');
    try {
      const d = await api(`/api/review/history?${scopeQuery({ limit: '50' })}`);
      if (d?.error) throw new Error(String(d.error));
      setReviewHistory(d);
    } catch (e) {
      setReviewHistory(null);
      setHistoryErr(describeError(e, '검토 이력을 불러오지 못했습니다'));
    }
  }, [scopeQuery]);

  // 검토 이력 서브탭을 **연 뒤에만** 조회한다(lazy) — 스코프(프로젝트/문서)가 바뀌면 다시.
  // eslint-disable-next-line react-hooks/set-state-in-effect -- lazy 조회 (콜백 첫 줄의 에러 초기화 setState)
  useEffect(() => { if (mounted.has('reviews')) loadHistory(); }, [mounted, loadHistory]);

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
  // (R37 리뷰 W2) 빈 산출물은 따로 센다. 같은 표의 배지는 '산출물 비어 있음' 인데 이 줄만 "요약이 없어
  // 판정 없음" 이라고 하면 한 화면이 같은 질문에 두 답을 내고, 원인도 틀리게 귀속된다.
  const verdictNote = useMemo(() => {
    if (!runs.length) return null;
    const empty = runs.filter((r) => verdictOf(r).code === 'EMPTY_OUTPUT').length;
    const withVerdict = runs.filter(
      (r) => verdictOf(r).code !== 'EMPTY_OUTPUT'
        && r?.summary && r.summary.gate_pass !== null && r.summary.gate_pass !== undefined
    ).length;
    return { shown: runs.length, withVerdict, empty };
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

          {!runsErr && reviewStatesErr && (
            <div role="alert" style={{ color: 'var(--color-danger)', fontSize: 'var(--text-xs)', marginBottom: 'var(--sp-2)' }}>
              검토 열: {reviewStatesErr}
            </div>
          )}

          {!runsErr && verdictNote && verdictNote.withVerdict < verdictNote.shown && (
            <div role="status" style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginBottom: 'var(--sp-2)' }}>
              표시된 {verdictNote.shown}건 중{' '}
              {verdictNote.shown - verdictNote.withVerdict - verdictNote.empty > 0 && (
                <>{verdictNote.shown - verdictNote.withVerdict - verdictNote.empty}건은 요약이 없어{' '}
                  <strong>판정 없음</strong>{verdictNote.empty > 0 ? ', ' : '입니다 — 통과도 실패도 아닙니다.'}</>
              )}
              {verdictNote.empty > 0 && (
                <>{verdictNote.empty}건은 <strong>산출물에 담을 내용이 0건</strong>이라 점수가 없습니다.</>
              )}
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
                  <th>게이트</th><th>검토</th><th aria-label="작업" />
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => {
                  const g = verdictOf(r);
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
                      <td><StatusBadge tone={g.tone}>{g.label}</StatusBadge></td>
                      <td data-testid={`review-cell-${r.id}`}>
                        {(() => {
                          const id = String(r.id);
                          const hashed = r?.output_sha256 != null;
                          // 배치가 끝났는데 states 에도 missing 에도 없으면 계약 위반이다 — '조회 중' 이 아니라 실패로.
                          const absent = hashed && reviewDone && !reviewStates[id] && !reviewMissing.has(id);
                          const rv = reviewVerdictOf(r, reviewStates[id], {
                            error: hashed && reviewStatesErr ? reviewStatesErr : (absent ? '배치 응답에 이 run 이 없습니다' : null),
                            missing: hashed && reviewMissing.has(id),
                          });
                          return <StatusBadge tone={rv.tone} title={rv.title}>{rv.label}</StatusBadge>;
                        })()}
                      </td>
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
                    <td colSpan={scmId ? 7 : 8} style={{ color: 'var(--text-muted)' }}>
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
                          const g = metricVerdictOf(s?.gate_pass ?? null);
                          return (
                            <tr key={`${s.metric_name}-${i}`}>
                              <td>{s.metric_name}</td>
                              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                                {s.value == null ? '—' : Number(s.value).toFixed(2)}
                              </td>
                              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                                {s.threshold == null ? '—(비게이트)' : Number(s.threshold).toFixed(2)}
                              </td>
                              <td><StatusBadge tone={g.tone}>{g.label}</StatusBadge></td>
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
          {/* key 로 remount — run 을 갈아탈 때 옛 state·해시·version 이 새 run 의 POST 에 실리지 않게(리뷰 C1). */}
          {openId != null && <ReviewPanel key={openId} runId={openId} onSaved={loadRuns} />}
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
                      {/* 역할 열은 서버가 주는 라벨 그대로 — "적용됨" 표 안에서도 판정식에 없는
                          키(사유 전용)가 있다(R29 Q-3). 프론트가 역할을 계산하지 않는다.
                          미사용 표엔 열을 내지 않는다 — 전 행 '—' 면 "역할 미상" 과 "표 미사용" 이 안 갈린다. */}
                      <thead><tr><th>키</th><th>값</th><th>환경변수</th>{t.status === 'applied' && <th>역할</th>}</tr></thead>
                      <tbody>
                        {(t.entries || []).map((e) => (
                          <tr key={e.key}>
                            <td>{e.key}</td>
                            <td>{typeof e.value === 'object' ? JSON.stringify(e.value) : String(e.value)}</td>
                            <td>{e.env_name || '—'}{e.env_set ? ' (설정됨)' : ''}</td>
                            {t.status === 'applied' && <td>{e.role_label || '—'}</td>}
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

        {/* ── 검토 이력 (R35) ── */}
        <div role="tabpanel" id="qgate-panel-reviews" aria-labelledby="qgate-tab-reviews"
          tabIndex={sub === 'reviews' ? 0 : -1}
          style={{ display: sub === 'reviews' ? 'block' : 'none' }}>
          {mounted.has('reviews') && (
            <div style={{ marginTop: 'var(--sp-3)' }}>
              <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                검토 기록의 <strong>감사 이력</strong>입니다(생성·갱신 한 줄씩, 최신순). 검토는 게이트 판정을 바꾸지 않습니다.
                {reviewHistory ? ` 총 ${reviewHistory.total}건 중 ${(reviewHistory.items || []).length}건 표시.` : ''}
              </p>
              {historyErr && (
                <div role="alert" style={{ color: 'var(--color-danger)', fontSize: 'var(--text-sm)' }}>{historyErr}</div>
              )}
              {reviewHistory && (
                <div style={{ overflowX: 'auto' }}>
                  <table className="board-table">
                    <thead>
                      <tr><th>시각</th><th>run</th><th>문서</th>{!scmId && <th>프로젝트</th>}<th>검토자</th><th>동작</th><th>판정</th><th>해시</th></tr>
                    </thead>
                    <tbody>
                      {(reviewHistory.items || []).map((h) => (
                        <tr key={h.id}>
                          <td style={{ fontSize: 'var(--text-xs)' }}>{fmtWhen(h.created_at)}</td>
                          <td>#{h.run_id}</td>
                          <td>{h.doc_type}</td>
                          {!scmId && <td style={{ fontSize: 'var(--text-xs)' }}>{h.scm_id || <span style={{ color: 'var(--text-muted)' }}>미상</span>}</td>}
                          <td>{h.reviewer}</td>
                          <td>{h.action === 'create' ? '생성' : h.action === 'update' ? '갱신' : h.action}</td>
                          <td>{REVIEW_DECISION_LABEL[h.decision] || h.decision}</td>
                          <td><code style={{ fontSize: 'var(--text-xs)' }}>{String(h.output_sha256 || '').slice(0, 12)}</code></td>
                        </tr>
                      ))}
                      {!(reviewHistory.items || []).length && (
                        <tr><td colSpan={scmId ? 7 : 8} style={{ color: 'var(--text-muted)' }}>검토 이력이 없습니다.</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
