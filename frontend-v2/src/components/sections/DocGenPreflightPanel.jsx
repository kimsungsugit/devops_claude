// 조회는 이 컴포넌트가 하지 않는다 — 부모(보드)가 행을 펼칠 때 받아 props 로 내린다.
// 이유는 아래 컴포넌트 주석 참조.

/**
 * 생성 **준비** 패널 — 만들기 전에 무엇이 부족한지 단계별로 보인다.
 *
 * 보드의 기존 펼침(`근거`)은 생성 **후** 품질을 말한다. 이 패널은 생성 **전** 조건을
 * 말하는 반대쪽이다. 둘을 한 행에 두면 "왜 이 점수인가" 와 "지금 만들면 어떻게 되는가"
 * 를 같은 자리에서 답할 수 있다.
 *
 * ## 화면 규약 (백엔드 state 7값을 그대로 옮긴다)
 *
 * 백엔드가 `ok / missing / stale_path / error / degraded / unmeasured / needed` 를
 * **서로 접지 않고** 내려주므로 화면도 접지 않는다. 특히:
 *
 *   - `unmeasured` 는 **0이 아니다.** 재지 못한 것이므로 숫자를 그리지 않고 `—` 로 둔다.
 *     (`0` 으로 그리면 "주석이 하나도 없다" 로 읽힌다 — 실제로는 안 재봤을 뿐이다.)
 *   - `degraded` 는 **차단이 아니다.** 실측상 주석·타입 근거가 100% 인 프로젝트가 없어서
 *     막으면 아무도 문서를 못 만든다. 대신 영향 문장을 보인다.
 *   - 사슬은 **단계별 가용성만** 보인다. "ASIL 435칸이 TBD 가 됩니다" 같은 칸 수 예고는
 *     하지 않는다 — 출처는 후보 집합 + 강도 우선 덮어쓰기 구조이고 모듈 상속이
 *     모듈 전체로 번지므로 입력 유무만으로 계산할 수 없다(계산하면 그게 거짓 증거다).
 */

/** state → 아이콘·CSS 클래스·한 줄 뜻. 없는 state 는 **코드 그대로** 보인다(지어내지 않는다). */
const STATE_VIEW = {
  ok:         { icon: '✓', cls: 'step-done',   tone: '확인됨' },
  missing:    { icon: '✗', cls: 'step-error',  tone: '없음' },
  stale_path: { icon: '↻', cls: 'step-warn',   tone: '경로가 낡음' },
  error:      { icon: '⚠', cls: 'step-error',  tone: '오류' },
  degraded:   { icon: '!', cls: 'step-warn',   tone: '부족' },
  unmeasured: { icon: '—', cls: 'step-muted',  tone: '재지 못함' },
  needed:     { icon: '?', cls: 'step-active', tone: '결정 필요' },
};

const PHASE_TITLES = {
  access:   '0. 접근',
  input:    '1. 입력 자료',
  material: '2. 재료',
  chain:    '3. 채울 수 있는 경로',
  decision: '4. 결정할 것',
};
const PHASE_ORDER = ['access', 'input', 'material', 'chain', 'decision'];

const VERDICT_VIEW = {
  ready:          { tone: 'success', label: '준비 완료' },
  degraded:       { tone: 'warning', label: '부족한 채로 진행 가능' },
  unknown:        { tone: 'neutral', label: '확인하지 못한 항목 있음' },
  needs_decision: { tone: 'info',    label: '결정 필요' },
  blocked:        { tone: 'danger',  label: '진행 불가' },
};

/** 측정값 한 줄. **재지 못한 값은 숫자로 그리지 않는다.** */
function Measured({ m }) {
  if (!m) return null;
  const parts = [];
  if (m.value != null && m.of != null) parts.push(`${m.value} / ${m.of}`);
  else if (m.value != null) parts.push(String(m.value));
  if (m.functions != null) parts.push(`함수 ${m.functions}`);
  if (m.filled != null && m.substantive != null) {
    parts.push(`설명 ${m.filled} (실질 ${m.substantive})`);
  }
  if (m.chars != null) parts.push(`본문 ${m.chars.toLocaleString()}자`);
  if (m.scanned_files != null) parts.push(`스캔 ${m.scanned_files}파일`);
  if (m.api_default != null || m.generator_default != null) {
    parts.push(`현재 ${m.api_default ?? '—'} · 생성기 기본 ${m.generator_default ?? '—'}`);
  }
  if (!parts.length) return null;
  return (
    <span style={{ color: 'var(--text-muted)' }}>
      {parts.join(' · ')}
      {m.partial && (
        <strong style={{ color: 'var(--color-warning)' }}> · 일부만 봄(상한 도달)</strong>
      )}
    </span>
  );
}

/** 사슬 한 줄 — 출처별 가용 여부. `have=null` 은 **모름**이지 없음이 아니다. */
function ChainRows({ chain }) {
  return (
    <ul style={{ margin: '4px 0 0', paddingLeft: '1.1em', fontSize: 'var(--text-xs)', lineHeight: 1.8 }}>
      {chain.map((r, i) => {
        const mark = r.have === true ? '✓' : r.have === false ? '✗' : '?';
        const color = r.have === true ? 'var(--color-success)'
          : r.have === false ? 'var(--color-danger)' : 'var(--text-muted)';
        return (
          <li key={`${r.source}-${i}`}>
            <span style={{ color, fontWeight: 700 }}>{mark}</span>{' '}
            <code>{r.source}</code>
            {r.input_label && <> — {r.input_label}</>}
            {r.have === null && (
              <span style={{ color: 'var(--text-muted)' }}> (확인하지 않음)</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * ⚠ **이 컴포넌트는 스스로 조회하지 않는다.**
 *
 * 조회를 `useEffect` 에 두면 effect 안에서 동기 `setState` 가 일어나
 * `react-hooks/set-state-in-effect`(cascading render)에 걸린다. 우회(disable)하는 대신
 * **조회 시점을 이벤트로 옮겼다** — 이 패널은 행을 펼칠 때만 열리므로 부모의 펼침
 * 핸들러가 조회하면 되고, 보드는 이미 `근거` 탭을 정확히 그 방식으로 채운다
 * (`DocGenStatusBoard.toggleExpand`). 결과적으로 표시 전용 순수 컴포넌트가 된다.
 */
export default function DocGenPreflightPanel({ data, loading, error, onReload, onAction }) {
  if (loading && !data) {
    return <div style={{ padding: 'var(--sp-3)', fontSize: 'var(--text-xs)' }}>준비 상태를 확인하는 중…</div>;
  }
  if (error) {
    return (
      <div role="alert" style={{ padding: 'var(--sp-3)', fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>
        {error}
      </div>
    );
  }
  if (!data) return null;

  const verdict = VERDICT_VIEW[data.verdict] || { tone: 'neutral', label: data.verdict };
  const byPhase = PHASE_ORDER
    .map(p => [p, (data.steps || []).filter(s => s.phase === p)])
    .filter(([, rows]) => rows.length > 0);

  return (
    <div style={{ padding: 'var(--sp-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 'var(--sp-2)' }}>
        <span className={`pill pill-${verdict.tone}`}>{verdict.label}</span>
        {data.unknown_doc_type && (
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-warning)' }}>
            알 수 없는 문서 종류 — 요구 조건을 지어내지 않습니다
          </span>
        )}
        <button type="button" className="btn-secondary btn-sm" style={{ marginLeft: 'auto' }}
          onClick={onReload} disabled={loading || !onReload}>
          {loading ? '확인 중…' : '다시 확인'}
        </button>
      </div>

      {byPhase.map(([phase, rows]) => (
        <div key={phase} style={{ marginBottom: 'var(--sp-3)' }}>
          <div style={{ fontWeight: 700, fontSize: 'var(--text-xs)', marginBottom: 4 }}>
            {PHASE_TITLES[phase] || phase}
          </div>
          <div className="pipeline-steps">
            {rows.map(s => {
              const v = STATE_VIEW[s.state] || { icon: '·', cls: '', tone: s.state };
              return (
                <div key={s.id} className={`pipeline-step ${v.cls}`}>
                  <span className="step-icon" aria-hidden="true">{v.icon}</span>
                  <span className="step-label">
                    {s.label}
                    {s.required && <span style={{ color: 'var(--color-danger)' }}> *</span>}
                    <div className="step-msg">
                      {/* 사유가 곧 사용자가 할 일이다. 없으면 상태 뜻이라도 말한다. */}
                      {s.reason || v.tone}
                      {s.effect && (
                        <div style={{ color: 'var(--color-warning)' }}>없이 진행하면: {s.effect}</div>
                      )}
                      {s.value && (
                        <div style={{ fontFamily: 'monospace', wordBreak: 'break-all', opacity: 0.75 }}>
                          {s.value}
                        </div>
                      )}
                      {s.suggestion && (
                        <div style={{ color: 'var(--color-info)' }}>제안: {s.suggestion}</div>
                      )}
                      <Measured m={s.measured} />
                      {Array.isArray(s.samples) && s.samples.length > 0 && (
                        <div style={{ opacity: 0.75 }}>예: {s.samples.slice(0, 3).map(x => `"${x}"`).join(' · ')}</div>
                      )}
                      {Array.isArray(s.chain) && s.chain.length > 0 && <ChainRows chain={s.chain} />}
                    </div>
                  </span>
                  {Array.isArray(s.actions) && s.actions.length > 0 && (
                    <span style={{ whiteSpace: 'nowrap' }}>
                      {s.actions.map((a, i) => (
                        <button
                          key={`${a.kind}-${i}`}
                          type="button"
                          className="btn-secondary btn-sm"
                          style={{ marginLeft: 4 }}
                          onClick={() => onAction?.(a, s)}
                        >
                          {ACTION_LABELS[a.kind] || a.kind}
                        </button>
                      ))}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

const ACTION_LABELS = {
  run_worker: 'Cloudium 워커 실행 안내',
  pick_path: '경로 지정',
  adopt_suggestion: '이 파일로 교체',
  measure_source: '소스 측정',
  input_value: '값 지정',
  open_scm: 'SCM 설정',
};
