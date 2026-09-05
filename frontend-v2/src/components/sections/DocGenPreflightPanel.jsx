// 조회는 이 컴포넌트가 하지 않는다 — 부모(보드)가 행을 펼칠 때 받아 props 로 내린다.
// 이유는 아래 컴포넌트 주석 참조.
import {
  loadDocGenCaps, saveDocGenCap, saveDocGenChoice,
  loadSharedInputs, saveSharedInputs,
} from '../../sharedInputs.js';

/**
 * 생성 상한 입력 — 캡은 **자료 부족이 아니라 사용자 결정**이라 그 자리에서 바꾼다.
 *
 * 비우면 키를 지워 **생성기 기본값**으로 되돌린다(0 을 보내면 "하나도 만들지 마라" 가
 * 되어 뜻이 정반대다). 비제어 입력이라 컴포넌트 상태가 없다 — 저장은 이벤트에서만
 * 일어나므로 effect 안의 setState 문제도 생기지 않는다.
 */
/**
 * 시험 **범위** 선택 — 캡과 마찬가지로 자료 부족이 아니라 사용자 결정이다.
 *
 * 기본은 `suds`(SwUDS 설계 ID 가 있는 함수만). SUTS 는 SwUDS 기반 문서이고 납품
 * 정본도 그 범위다(실측: 정본 1,005 ↔ SwUDS 1,026, 교집합 1,001). 소스에는 그보다
 * 많은 함수가 있어(1,160) 전부 시험하면 정본에 없는 항목이 섞인다.
 *
 * 빈 값을 저장하면 키가 지워져 **서버 기본값**을 쓴다 — 여기서 기본을 복제하지 않는다.
 */
function ChoiceSelect({ name, label, options, scope, onSaved }) {
  const caps = loadDocGenCaps(scope);
  const opts = Array.isArray(options) && options.length > 0 ? options : null;
  // 서버가 옵션을 못 내려주면 **선택기를 그리지 않는다**. 여기서 목록을 지어내면
  // 화면이 서버가 받지 않는 값을 제시하게 되고, 그건 다시 거짓 통제다.
  if (!opts) return null;
  // 값이 같은 옵션이 둘이면 `<select>` 가 첫 항목만 고른다 — 표에서 라벨만 다르게
  // 적었을 때 조용히 한쪽이 사라지므로 값 기준으로 접는다.
  const seen = new Set();
  const uniq = opts.filter(o => (seen.has(o.value) ? false : (seen.add(o.value), true)));
  return (
    <span style={{ whiteSpace: 'nowrap' }}>
      <select
        aria-label={label || name}
        defaultValue={caps[name] ?? ''}
        onChange={(e) => { saveDocGenChoice(name, e.target.value, scope); onSaved?.(); }}
        style={{ fontSize: 'var(--text-xs)' }}
      >
        {uniq.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </span>
  );
}

/** "전부 N" 버튼의 설명. **N 의 출처가 두 가지**라 같은 문장을 쓰면 한쪽이 거짓이 된다.
 *
 * `measured` 는 이 소스를 실제로 센 값이라 "전부 담으려면 최소 N" 이 참이지만,
 * `catalog` 는 생성기 전략 후보의 **이론적 최대**라 그만큼 나오는 함수가 거의 없다.
 * 후자에까지 "측정값 기준" 이라 적으면 재지도 않은 수를 측정치로 파는 셈이다.
 */
function suggestTitle(suggested, basis) {
  return basis === 'catalog'
    ? `생성기 후보 최대 ${suggested}종 — 어떤 함수도 잘리지 않게 하려면 이 값입니다(측정치가 아닙니다)`
    : `측정값 기준 — 전부 담으려면 최소 ${suggested} 이어야 합니다`;
}

/**
 * 프로젝트 ASIL 등급 — **그 자리에서 정한다**.
 *
 * 상한과 달리 이 값은 문서 내용을 바꾼다(요구별 ASIL 빈 칸 역채움 · 안전 관련 시험 갈래).
 * 게이트가 "결정 필요" 라고만 하고 설정 탭으로 보내면, 이 패널이 스스로 세운 원칙
 * ("캡은 그 자리에서 바꾼다 — 다른 탭으로 보내면 결정 흐름이 끊긴다")을 어긴다.
 *
 * ⚠ 빈 값은 **빈 채로** 저장한다. `QM` 을 기본으로 넣으면 근거 없는 등급을 지어내는
 *   것이고, 하류(요구 ASIL 역채움·안전 판정)가 그걸 사실로 쓴다.
 * ⚠ 저장소는 공유 입력(설정 > 공통 메타)과 **같은 칸**이다 — 여기만의 사본을 만들면
 *   Sw* 빌더와 값이 갈린다.
 */
const ASIL_CHOICES = ['ASIL A', 'ASIL B', 'ASIL C', 'ASIL D', 'QM'];

function AsilSelect({ onSaved }) {
  const current = String(loadSharedInputs()?.asil_level || '');
  return (
    <span style={{ whiteSpace: 'nowrap' }}>
      <select
        aria-label="프로젝트 ASIL 등급"
        defaultValue={current}
        onChange={(e) => {
          saveSharedInputs({ ...loadSharedInputs(), asil_level: e.target.value });
          onSaved?.();
        }}
        style={{ fontSize: 'var(--text-xs)' }}
      >
        <option value="">미지정 (등급을 지어내지 않습니다)</option>
        {ASIL_CHOICES.map(v => <option key={v} value={v}>{v}</option>)}
      </select>
    </span>
  );
}

function CapInput({ name, apiDefault, suggested, suggestedBasis, scope, onSaved }) {
  const caps = loadDocGenCaps(scope);
  const current = caps[name];
  return (
    <span style={{ whiteSpace: 'nowrap' }}>
      <input
        /* 비제어 입력이라 `defaultValue` 는 마운트 때만 반영된다. 아래 [전부] 버튼으로
           값을 바꾸면 저장은 되는데 칸은 그대로여서 "안 먹혔다" 로 읽힌다 — key 로
           리마운트해 화면과 저장값을 같게 유지한다. */
        key={`${name}-${current ?? ''}`}
        type="number"
        min="1"
        aria-label={`${name} 상한`}
        defaultValue={current ?? ''}
        placeholder={apiDefault != null ? String(apiDefault) : ''}
        onChange={(e) => saveDocGenCap(name, e.target.value, scope)}
        onBlur={() => onSaved?.()}
        style={{ width: 72, fontSize: 'var(--text-xs)' }}
      />
      {/* 상한을 올리라고만 하고 **얼마로** 올릴지 안 알려주면 사용자는 숫자를 추측한다.
          서버가 실제 측정에서 낸 값이 있을 때만 뜬다(없으면 지어내지 않는다). */}
      {suggested != null && current !== suggested && (
        <button
          type="button"
          className="btn-secondary btn-sm"
          style={{ marginLeft: 4 }}
          title={suggestTitle(suggested, suggestedBasis)}
          onClick={() => { saveDocGenCap(name, suggested, scope); onSaved?.(); }}
        >
          전부 {suggested}
        </button>
      )}
    </span>
  );
}

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

/**
 * phase → 제목. **백엔드 `PHASES` 와 lockstep이다**
 * (`backend/routers/docgen_preflight.py`).
 *
 * ⚠ 아래 `PHASE_ORDER` 에 없는 phase 의 행은 `filter` 에서 **에러도 경고도 없이 사라진다**
 *   — 서버는 행을 냈는데 사용자는 못 본다. 그래서 백엔드가 phase 를 늘리면 여기도 늘려야
 *   하고, 그 드리프트는 `tests/unit/test_docgen_preflight_phases.py` 가 양쪽을 읽어 막는다.
 */
const PHASE_TITLES = {
  access:   '0. 접근',
  input:    '1. 입력 자료',
  material: '2. 재료',
  chain:    '3. 채울 수 있는 경로',
  decision: '4. 결정할 것',
  // 지금의 입력이 아니라 **기록**이다 — 그래서 위 흐름 뒤에 따로 온다.
  history:  '5. 직전 생성 결과',
};
const PHASE_ORDER = ['access', 'input', 'material', 'chain', 'decision', 'history'];

const VERDICT_VIEW = {
  ready:          { tone: 'success', label: '준비 완료' },
  degraded:       { tone: 'warning', label: '부족한 채로 진행 가능' },
  unknown:        { tone: 'neutral', label: '확인하지 못한 항목 있음' },
  needs_decision: { tone: 'info',    label: '결정 필요' },
  blocked:        { tone: 'danger',  label: '진행 불가' },
};

/**
 * 입력 변수가 없는 unit 의 **사유 분해**.
 *
 * ⚠ 사유를 안 나누면 판단이 불가능하다. 입력 0 은 정상일 수도 있고(파라미터도 전역도
 *   없는 함수 — 정본도 1,005 중 172 건) 재료를 놓친 것일 수도 있다. 한 숫자로 합치면
 *   읽는 사람은 전부 결함으로 읽는다.
 * ⚠ 그래서 정상 사유와 결함 사유를 **같은 무게로 그리지 않는다.** 결함 쪽만 강조한다.
 */
const CAUSE_LABELS = {
  no_params_no_globals:   { ko: '파라미터·전역 없음', defect: false },
  // 값을 자동으로 채우지 않는 축 — 사람이 "이 호출을 스텁으로 막고 반환값을 넣는다" 를
  // 결정해야 한다. 결함은 아니지만 정상도 아니라 **결정 필요**로 따로 칠한다.
  stub_return_candidate:  { ko: '스텁 반환값 지정 가능', defect: false, decide: true },
  write_only:             { ko: '전역을 쓰기만 함',   defect: false },
  indirect_only:          { ko: '간접 접근만',        defect: false },
  // 읽는 전역이 전부 `const` — 시험이 **설정할 수 있는 값이 없다**. 정본도 const
  // 전역을 입력·기대 어느 열에도 안 적으므로 입력 0 이 정상이다.
  // ⚠ 라벨이 없으면 아래 폴백이 `defect: true` 로 칠한다 — 의도한 억제가 결함으로 뜬다.
  const_globals_only:     { ko: 'const 전역만 읽음',  defect: false },
  untagged:               { ko: '방향 태그 없음',     defect: true },
  dropped_by_name_filter: { ko: '이름 추출이 버림',   defect: true },
  param_string_unusable:  { ko: '파라미터 문자열 손상', defect: true },
  // ── STS 요구-함수 매핑의 사유 ──────────────────────────────────────────
  // ⚠ 이 둘은 **다른 사람이 고칠 문제**다. 한 숫자로 합치면 조치 가능한 축이 안 보인다.
  //   `unreached_in_sds` 는 SwDS 가 그 요구를 담고 있는데 우리가 그 파티션에 못 닿은
  //   것 = 이쪽 결함. `absent_from_sds` 는 설계 문서가 그 요구를 안 이은 것 =
  //   문서 간 추적 부재라 생성기가 고칠 수 없다 — 지어내지 않고 결정으로 넘긴다.
  unreached_in_sds:       { ko: 'SwDS 엔 있는데 못 닿음', defect: true },
  absent_from_sds:        { ko: 'SwDS 에 요구 자체가 없음', defect: false, decide: true },
  other:                  { ko: '기타',               defect: true },
};

function CauseBreakdown({ causes }) {
  const rows = Object.entries(causes || {}).filter(([, n]) => n > 0);
  if (!rows.length) return null;
  rows.sort((a, b) => b[1] - a[1]);
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      {rows.map(([key, n]) => {
        const meta = CAUSE_LABELS[key] || { ko: key, defect: true };
        const color = meta.defect
          ? 'var(--color-warning)'
          : meta.decide ? 'var(--color-info)' : 'var(--text-muted)';
        return (
          <span
            key={key}
            style={{ color, fontWeight: meta.defect || meta.decide ? 600 : 400 }}
          >
            {meta.ko} {n}
            {meta.defect ? ' ⚠' : ''}
          </span>
        );
      })}
    </div>
  );
}

/**
 * 게이트 문장의 `**강조**` 를 실제 강조로 그린다.
 *
 * 백엔드 사유 문자열은 오래 `**…**` 로 **가장 중요한 절**을 표시해 왔다(preflight 만
 * 141곳). 그런데 화면은 그것을 평문으로 뿌려서 별표가 그대로 보였고, 강조하려던
 * 바로 그 문장이 오히려 읽기 나빠졌다 — "잘린 흐름은 **시험 규격에 존재하지
 * 않습니다**", "이 소스에 **ASIL D 함수가 37개** 있습니다" 같은, 이 패널에서 사람이
 * 반드시 봐야 하는 절들이다.
 *
 * ⚠ 마크다운 렌더러를 들이지 않는다. 이 축 하나만 필요하고, 임의 마크업을 해석하면
 *   서버 문자열이 화면 구조를 바꿀 수 있다. 짝이 안 맞는 `**` 는 그냥 평문으로 남는다.
 */
function Emphasis({ text }) {
  const s = String(text ?? '');
  if (!s.includes('**')) return s;
  const parts = s.split(/\*\*([^*]+)\*\*/g);
  // split 결과는 [평문, 강조, 평문, 강조, …] 로 홀수 인덱스가 캡처분이다.
  return parts.map((p, i) => (i % 2 ? <strong key={i}>{p}</strong> : p));
}

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
  // 직전 생성의 소요와 그 단계 예산. 예산 없이 소요만 있으면 '많은 건지' 알 수 없고,
  // 소요가 없으면(라운드 12 이전 기록) 아무 말도 하지 않는다 — 0 으로 접으면 거짓이다.
  if (m.elapsed_seconds != null) {
    parts.push(m.budget_seconds != null
      ? `소요 ${Math.round(m.elapsed_seconds)}초 / 예산 ${m.budget_seconds}초`
      : `소요 ${Math.round(m.elapsed_seconds)}초`);
  }
  if (m.scanned_files != null) parts.push(`스캔 ${m.scanned_files}파일`);
  if (m.fallback != null) parts.push(`폴백 ${m.fallback}`);
  // SwDS 보강 실적 — 조회는 되는데 산출이 0 인 상태를 드러내려면 세 값이 다 필요하다.
  if (m.lookups != null) parts.push(`조회 ${m.lookups}`);
  if (m.key_hits != null) parts.push(`키매칭 ${m.key_hits}`);
  if (m.map_entries != null) parts.push(`맵 ${m.map_entries}항목`);
  if (m.api_default != null || m.generator_default != null) {
    // ⚠ 이 패널에서 `—` 는 **'재지 못함'** 전용 기호다(상단 화면 규약). 조정할 수 없는
    //   상한은 재지 못한 게 아니라 **확정적으로 알려져 있다** — `현재 —` 로 그리면
    //   "값이 비었다" 로 읽혀 자기 규약을 어긴다.
    if (m.adjustable === false) {
      parts.push(`현재 ${m.generator_default ?? '—'} (고정)`);
    } else if (m.user_value != null) {
      // 정한 값을 되읽어 보인다 — 없으면 200 을 넣어도 화면은 계속 기본값을 "현재"
      // 라고 불러 자기 선택이 반영됐는지 알 수 없다.
      parts.push(`현재 ${m.user_value} (직접 지정) · 생성기 기본 ${m.generator_default ?? '—'}`);
    } else {
      parts.push(`현재 ${m.api_default ?? '—'} · 생성기 기본 ${m.generator_default ?? '—'}`);
    }
  }
  // 정본 기준선 — 건수만 보면 많은 건지 알 수 없다(정본도 17.1%가 입력 0개다).
  if (m.reference_pct != null) parts.push(`정본 ${m.reference_pct}%`);
  if (!parts.length && m.headroom == null) return null;
  return (
    <span style={{ color: 'var(--text-muted)' }}>
      {parts.join(' · ')}
      {/* 캡은 **여유**로 읽어야 한다. '절단 0' 은 경계에 닿은 상태를 숨긴다. */}
      {m.headroom != null && (
        <strong style={{
          marginLeft: parts.length ? 6 : 0,
          color: m.headroom <= 0 ? 'var(--color-warning)' : 'var(--text-muted)',
        }}>
          여유 {m.headroom}
        </strong>
      )}
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
/**
 * 결정 질문 — 게이트가 낸 코드(`proceed_without_swds`)를 사람이 답할 수 있는 문장으로.
 *
 * ⚠ **문장의 출처를 숨기지 않는다.** `generated_by === 'llm'` 이면 AI 가 썼다고 밝힌다.
 * 수치는 서버가 검증한다 — 프롬프트에 없던 숫자가 섞이면 그 응답은 폐기되고 룰 문장이
 * 온다. 그래도 "AI 문장" 표시는 남긴다(읽는 사람이 판단할 몫이다).
 */
function QuestionList({ payload, error }) {
  if (error) {
    return (
      <div role="alert" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>
        {error}
      </div>
    );
  }
  if (!payload) return null;
  const items = payload.questions || [];
  if (!items.length) {
    return (
      <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
        {payload.llm_reason || '결정할 항목이 없습니다'}
      </div>
    );
  }
  return (
    <div className="pipeline-steps">
      {items.map(q => (
        <div key={q.id} className={`pipeline-step ${q.severity === 'high' ? 'step-warn' : ''}`}>
          <span className="step-icon" aria-hidden="true">?</span>
          <span className="step-label">
            {q.title}
            {q.generated_by === 'llm' && (
              <span style={{ marginLeft: 6, fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                (AI 작성)
              </span>
            )}
            <div className="step-msg">
              {q.body}
              {/* ⚠ 이건 **누를 수 있는 선택지가 아니다.** pill 로 그리면 버튼처럼
                  보이는데 클릭 핸들러가 없어 눌러도 아무 일이 없다 — 화면이 없는
                  통제를 약속하는 셈이다. 실제 결정은 [생성]을 누르거나(그대로 진행)
                  자료를 채우는 것이므로, 고를 것이 아니라 **읽을 것**으로 그린다. */}
              {Array.isArray(q.options) && q.options.length > 0 && (
                <div style={{ marginTop: 4, color: 'var(--text-muted)' }}>
                  고를 수 있는 것: {q.options.map(o => o.label).join(' / ')}
                </div>
              )}
            </div>
          </span>
        </div>
      ))}
    </div>
  );
}

export default function DocGenPreflightPanel({
  data, loading, error, questions, questionsError, onReload, onAction, scope,
}) {
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

      {(questions || questionsError) && (
        <div style={{ marginBottom: 'var(--sp-3)' }}>
          <div style={{ fontWeight: 700, fontSize: 'var(--text-xs)', marginBottom: 4 }}>
            결정할 것
          </div>
          <QuestionList payload={questions} error={questionsError} />
        </div>
      )}

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
                      <Emphasis text={s.reason || v.tone} />
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
                      {s.measured?.causes && <CauseBreakdown causes={s.measured.causes} />}
                      {/* 콜체인은 SITS 문서 D열에 그대로 박힌다 — 화면도 실물을 보인다. */}
                      {s.sample?.call_chain && (
                        <div style={{ fontFamily: 'monospace', fontSize: 'var(--text-xs)', opacity: 0.8 }}>
                          예: {s.sample.call_chain}
                          {s.sample.asil && ` (ASIL ${s.sample.asil})`}
                        </div>
                      )}
                      {Array.isArray(s.samples) && s.samples.length > 0 && (
                        <div style={{ opacity: 0.75 }}>예: {s.samples.slice(0, 3).map(x => `"${x}"`).join(' · ')}</div>
                      )}
                      {Array.isArray(s.chain) && s.chain.length > 0 && <ChainRows chain={s.chain} />}
                    </div>
                  </span>
                  {/* 캡은 그 자리에서 바꾼다 — 다른 탭으로 보내면 결정 흐름이 끊긴다.
                      ⚠ 단 **조정할 수 있는 것만** 입력칸을 낸다. 못 바꾸는 상한에
                      입력칸을 그리면 사용자는 고쳤다고 믿는데 문서는 그대로다(그 값은
                      요청에 실리지도 않는다). 어디서 바꾸는지는 `reason` 이 말한다. */}
                  {s.id?.startsWith('cap_') && s.measured?.adjustable !== false && (
                    <CapInput
                      name={s.id.slice(4)}
                      apiDefault={s.measured?.api_default}
                      suggested={s.measured?.suggested}
                      suggestedBasis={s.measured?.suggested_basis}
                      scope={scope}
                      onSaved={onReload}
                    />
                  )}
                  {/* 열거 선택(범위·템플릿 출처)도 그 자리에서 고른다 — 캡과 같은 성격의
                      결정이다. 어떤 행에 무엇을 그릴지는 **서버가 정한다**(`measured.choice`)
                      — 화면이 id 를 손으로 나열하면 새 선택지가 조용히 안 그려진다. */}
                  {s.measured?.choice && (
                    <ChoiceSelect
                      name={s.measured.choice}
                      label={s.label}
                      options={s.measured.options}
                      scope={scope}
                      onSaved={onReload}
                    />
                  )}
                  {/* ASIL 도 그 자리에서 정한다 — 설정 탭으로 보내면 결정 흐름이 끊긴다. */}
                  {s.id === 'asil_level' && <AsilSelect onSaved={onReload} />}
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
  export_comment_targets: '보강 대상 내려받기',
  input_value: '값 지정',
  open_scm: 'SCM 설정',
};
