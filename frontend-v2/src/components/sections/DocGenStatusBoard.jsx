import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { api, post, buildUrl, authHeaders, resolveCacheRoot } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import { loadBuilderForm, toBuildPayload, missingRequiredFields } from '../../swBuilderForms.js';
import DocGenPreflightPanel from './DocGenPreflightPanel.jsx';
import { loadDocPaths, loadDocGenCaps, loadSharedInputs, useDocGenCapsSync } from '../../sharedInputs.js';
import { docGenCapsScope } from '../../docGenHelpers.js';
import { notifyScmRegistryChanged } from '../../scmLinkedDocs.js';
import { contextConflict, mismatchText } from '../../impactGuard.js';
import { verdictOf, REASON_TEXT } from '../../gateVerdict.js';

/**
 * 생성 현황 보드 — "이 프로젝트의 문서가 지금 어디까지 갔고, 게이트가 어떻게 나왔고,
 * **왜** 그런가" 를 한 화면에서 답한다. 문서 생성 탭의 첫 서브탭.
 *
 * ## 왜 만들었나
 *
 * 그 답을 주는 화면이 없었다. `DocGenSection` 의 "문서 현황" 표는 생성 이력이 아니라
 * *경로 등록 여부*(`등록됨`/`-`)만 보여줬고, 게이트 결과는 Detail 의 별도 섹션과 최상위
 * Quality 탭 **두 벌**에 흩어져 서로 다른 판정을 냈다.
 *
 * ## 정직성 규약 (이 파일의 핵심)
 *
 * 게이트 화면에서 가장 위험한 건 **모르는 것을 좋게 그리는 것**이다. 세 가지를 지킨다:
 *
 *   1. `gate_pass === null` 은 **판정 없음**이지 통과가 아니다. 점수가 95여도 마찬가지 —
 *      과거 `QualityDashboard` 가 `gate_pass ?? (score >= 70)` 로 통과를 지어냈다.
 *   2. 검사 항목이 0개면 **판정 불가**다. `all([])` 이 True 라 "검사 0건" 이 PASS 로
 *      기록되던 결함을 백엔드가 fail-closed 로 고쳤고, 화면도 같은 말을 해야 한다.
 *   3. 생성한 적 없는 문서는 `—` 이지 0점이 아니다. 근거 파일이 없으면 "근거 없음" 이지
 *      "문제 없음" 이 아니다.
 *
 * 표시할 수 없는 것은 표시하지 않되, **표시하지 않는다는 사실을 표시한다.**
 */

// 주 표 — ISO 26262 문서 4종. `DocGenSection.DOC_TYPES` 와 같은 순서/라벨.
const DOC_ROWS = [
  { key: 'uds', label: 'UDS', icon: '📘', desc: '단위 상세 설계' },
  { key: 'sts', label: 'STS', icon: '📗', desc: 'SW 요구 기반 시험' },
  { key: 'suts', label: 'SUTS', icon: '📙', desc: 'SW 단위시험' },
  { key: 'sits', label: 'SITS', icon: '📕', desc: 'SW 통합시험' },
];

/**
 * 시험 **결과** 문서 — 보드에서 바로 만든다. 레벨(SwUT/SwIT)로 나눈 **6종 + 통합 1종**.
 *
 * ## 왜 레벨별로 나눴나
 *
 * 한 레벨의 셋(커버리지·결과·종합결과)은 **같은 VectorCAST 세션에서 나오는 한 벌**이라
 * 서로를 보며 판단한다 — 종합결과서의 실행률이 낮으면 같은 표의 커버리지 행을 먼저 본다.
 * 7행을 한 표에 늘어놓으면 그 짝이 안 보이고, SwUT 것과 SwIT 것이 섞여 읽힌다.
 *
 * ⚠ 커버리지 행의 `key` 가 `swutcv`/`switcv` 가 **아니라** `swut`/`swit` 인 것은 의도다.
 * Quality DB 가 이미 그 doc_type 으로 이력을 쌓아 왔고(`routers/swut.py` `record_run`),
 * 이 보드는 `latestByType[row.key]` 로 조회한다 — 새 어휘를 만들면 그동안 쌓인 이력이
 * 전부 "미생성" 으로 보인다.
 *
 * 예전엔 이 셋을 만들려면 각자의 서브탭에 들어가 15~20개 필드를 채워야 했다. 그런데
 * 그 값 대부분은 이미 어딘가에 있다(직전 빌드의 저장 폼, 설정>입력 자료 공유값,
 * `config/swut_meta.json` 의 프로젝트별 양식/승인자). 그래서 **디폴트로 채워 한 번에
 * 만들고**, 세부 조정이 필요할 때만 탭으로 간다. 탭은 그대로 남는다.
 *
 * ⚠ `release_sw_version` 만은 디폴트가 없다 — 저장 폼에도 직전 실행에도 없으면
 * **지어내지 않고** 입력을 요구한다. 임의 버전(`1.0.0` 같은)을 찍으면 ISO 26262
 * 납품 문서 표지에 틀린 릴리스가 박힌다.
 *
 * `builder` = swBuilderForms 의 폼 종류, `key` = quality DB 의 doc_type.
 */
const TEST_LEVEL_GROUPS = [
  {
    id: 'swut', title: 'SW 단위시험 (SwUT)',
    hint: '셋 다 같은 VectorCAST 세션에서 나온다 — 순서 제약은 없다',
    rows: [
      {
        key: 'swut', label: 'SwUTCV', icon: '📊', desc: '단위시험 커버리지',
        builder: 'swut', endpoint: '/api/swut/coverage/build', sub: 'swut',
        fallbackName: 'swut_coverage.xlsx',
      },
      {
        key: 'sutr', label: 'SUTR', icon: '🧪', desc: 'SW 단위시험 결과',
        builder: 'swut', endpoint: '/api/swut/sutr/build', sub: 'swut', fallbackName: 'sutr.xlsm',
      },
      {
        key: 'swutcr', label: 'SwUTCR', icon: '📚', desc: '단위시험 종합결과',
        builder: 'swut', endpoint: '/api/swut/swutcr/build', sub: 'swut', fallbackName: 'swutcr.xlsm',
      },
    ],
  },
  {
    id: 'swit', title: 'SW 통합시험 (SwIT)',
    hint: '셋 다 같은 VectorCAST 세션에서 나온다 — 순서 제약은 없다',
    rows: [
      {
        key: 'swit', label: 'SwITCV', icon: '📊', desc: '통합시험 커버리지',
        builder: 'swit', endpoint: '/api/swit/coverage/build', sub: 'swit',
        fallbackName: 'swit_coverage.xlsx',
      },
      {
        key: 'sitr', label: 'SITR', icon: '🔗', desc: 'SW 통합시험 결과',
        builder: 'swit', endpoint: '/api/swit/sitr/build', sub: 'swit', fallbackName: 'sitr.xlsm',
      },
      {
        key: 'switcr', label: 'SwITCR', icon: '📚', desc: '통합시험 종합결과',
        builder: 'swit', endpoint: '/api/swit/switcr/build', sub: 'swit', fallbackName: 'switcr.xlsm',
      },
    ],
  },
  {
    id: 'swreport', title: '통합 결과',
    hint: '레벨별 산출물을 되읽어 합친다 — 없는 산출물은 빈 시트로 나간다',
    rows: [
      {
        key: 'swreport', label: '통합 Summary', icon: '📊', desc: '전 레벨 결과 roll-up',
        builder: 'swreport', endpoint: '/api/swreport/summary/build', sub: 'swreport',
        fallbackName: 'swreport_summary.xlsm',
      },
    ],
  },
];

/** 위 그룹의 평탄화 — 행 계산(`reportRows`)은 그룹과 무관하므로 한 번만 돈다. */
const TEST_REPORT_ROWS = TEST_LEVEL_GROUPS.flatMap(g => g.rows);

// 보조 표 — 커버리지/정적분석 산출물. **이력이 있는 것만** 보여준다(없는 걸 '미생성'
// 으로 줄 세우면 안 쓰는 빌더까지 결함처럼 읽힌다). 각 행은 해당 서브탭으로 이동한다.
// `swreport` 는 위 시험 결과 표로 옮겼다 — 두 표에 같은 행을 두면 어느 쪽이 최신인지
// 화면이 두 번 답하게 된다. **커버리지 2종(`swut`/`swit`)도 같은 이유로 옮겼다** — 이제
// 레벨별 표에서 생성까지 되므로 여기 남겨두면 같은 run 이 두 곳에 뜬다.
const BUILDER_ROWS = [
  { key: 'swsa', label: 'SwSA 정적분석', sub: 'swsa' },
];

/**
 * 지표 코드 → 한국어 라벨.
 *
 * ⚠ 정본은 백엔드 `workflow/quality/advisor.py` 의 `_*_ADVICE` 표다(지표별 label +
 * 조치문). 여기 있는 건 **접힌 행에 한 줄로 보여줄 때만** 쓰는 축약이고, 행을 펼치면
 * advice API 를 불러 정본 라벨과 조치문을 그대로 쓴다. 그래서 이 맵에 없는 코드는
 * 지어내지 않고 **코드 그대로** 노출한다 — 조용히 빈 칸이 되면 그게 더 나쁘다.
 */
const METRIC_LABELS = {
  called_pct: '호출 관계', calling_pct: '피호출 관계',
  input_pct: '입력', output_pct: '출력',
  description_pct: '설명', asil_pct: 'ASIL', related_pct: 'Related ID',
  completeness_pct: '완결성', requirement_coverage_pct: '요구 커버리지',
  function_coverage_pct: '함수 커버리지', io_coverage_pct: 'I/O 커버리지',
  requirement_traceability_pct: '요구 추적성',
  statement_coverage_pct: '구문 커버리지', branch_coverage_pct: '분기 커버리지',
  mcdc_coverage_pct: 'MC/DC 커버리지', pass_rate_pct: '시험 통과율',
  his_pass_pct: 'HIS 메트릭 통과율',
  // 시험 결과 보고서(SUTR/SITR) — 커버리지와 다른 축이다.
  test_execution_pct: '시험 실행률', executed_pass_rate_pct: '실행분 통과율',
  deviation_cases: '편차 건수', tested_tcs: '실행 TC', failed_tcs: '실패 TC',
  // 종합결과서(SwUTCR/SwITCR) 참고지표 — 게이트 대상이 아니라 **규모**다.
  // 백분율이 아니므로 `fmtPct` 로 찍으면 안 된다(소비처는 `EvidenceDetail` 뿐이고
  // 거기서는 threshold 유무로 갈라 표시한다).
  total_tcs: '총 TC', environments: '시험 환경 수', function_rows: '함수 행 수',
  qualified_function_count: '자격 함수 수',
  // SwITCV — 구문/분기가 아니라 **Functions 달성 + Function Calls** 가 이 문서의 축이다
  // (회사 정본 4.Coverage 요약 블록과 같은 값). 위 `statement_coverage_pct` 계열은
  // SwUTCV 전용이다 — SwIT 에는 아예 기록되지 않는다.
  function_achievement_pct: '함수 달성률', function_call_coverage_pct: '함수 호출 커버리지',
  swit_functions_total: '대상 함수 수', swit_functions_fail: '미달성 함수 수',
  swit_function_calls_fail_functions: '호출 미달 함수 수',
  swit_function_calls_na_functions: '호출 없음(N/A) 함수 수',
  vcast_raw_statement_pct: '(참고) 원시 구문 커버리지',
  vcast_raw_branch_pct: '(참고) 원시 분기 커버리지',
  vcast_raw_measured_functions: '(참고) 원시 실측 함수 수',
  // SwUTCV — 문서는 Exception 으로 상쇄해 100% 로 적힌다. 게이트(raw)와의 격차를 보인다.
  doc_reported_statement_pct: '(문서 표기) 구문 커버리지',
  doc_reported_branch_pct: '(문서 표기) 분기 커버리지',
  coverage_fail_statement_functions: '구문 미달 함수 수',
  coverage_fail_branch_functions: '분기 미달 함수 수',
  coverage_exception_statement_functions: '구문 면제 함수 수',
  coverage_exception_branch_functions: '분기 면제 함수 수',
  // UDS 참고지표 — 위 `input_pct`/`output_pct` 와 **다른 질문**이라 라벨을 구분한다.
  //   input_pct      = "입력 칸에 정보를 적었나"    (`[IN] (none)` 도 채움으로 셈)
  //   input_real_pct = "실제로 주고받는 항목이 있나" (`(none)` 은 미채움)
  // 실측 98.3% vs 18.9%. 라벨이 같으면 화면에서 두 수치가 모순으로 읽힌다.
  input_real_pct: '입력(실제 항목)', output_real_pct: '출력(실제 항목)',
  // 근거(신뢰 출처) 축 — "칸이 찼나" 가 아니라 "근거가 있나". 판정은 confidence gate 가 한다.
  description_trusted_pct: '설명 근거율', asil_trusted_pct: 'ASIL 근거율',
  related_trusted_pct: 'Related ID 근거율',
  // 산출물 충실도 — 위 축들이 payload 를 재는 것과 달리 **문서에 실제로 들어간 수**다.
  // payload 가 완벽해도 템플릿에 heading 이 없으면 문서에서 사라지므로, 만점 옆에
  // 이 값이 낮게 뜨는 조합이 실제로 있었다(실측 run 660·661 = 점수 100.0 / 반영률 0.0).
  // 값이 아예 없으면 **미측정**이다 — 0% 로 보이지 않게 생산자가 키를 안 싣는다.
  artifact_match_pct: '문서 반영률',
};

const metricLabel = (code) => METRIC_LABELS[code] || code;

// (R31 Q-6) 판정·사유 문구는 `gateVerdict.js` 단일 출처 — 여기 로컬 `verdictOf` 를 다시 만들면
// 게이트 화면·추세와 갈린다(`__tests__/gateVerdict.test.jsx` 가 막는다).

const fmtPct = (v) => (v == null ? '—' : `${Number(v).toFixed(1)}%`);
const fmtScore = (v) => (v == null ? '—' : Number(v).toFixed(1));

/**
 * "왜 이 점수인가" 한 줄.
 *
 * 우선순위는 화면이 오독을 일으키는 순서대로다 — 판정 불가가 가장 먼저이고(통과로
 * 읽히면 안 되므로), 미생성이 그다음(0점으로 읽히면 안 되므로)이다.
 */
function whyOf(run, verdict) {
  if (!run) return '아직 생성하지 않음';
  if (verdict.label === '판정 불가') {
    return REASON_TEXT[run.gate_reason] || REASON_TEXT.no_gated_metric;
  }
  const scores = run.scores || [];
  if (verdict.label === 'FAIL') {
    // 실패 지표 중 임계와의 격차가 가장 큰 것 하나 — 조치 우선순위가 곧 이유다.
    const failed = scores
      .filter(s => s.gate_pass === false && s.threshold != null && s.value != null)
      .map(s => ({ ...s, gap: Number(s.threshold) - Number(s.value) }))
      .sort((a, b) => b.gap - a.gap);
    if (failed.length) {
      const w = failed[0];
      const more = failed.length > 1 ? ` 외 ${failed.length - 1}건` : '';
      return `${metricLabel(w.metric_name)} ${fmtPct(w.value)} < ${fmtPct(w.threshold)}${more}`;
    }
    return '실패 지표가 기록되지 않음 — 근거 보기로 확인';
  }
  if (verdict.label === 'PASS') {
    const gatedCount = scores.filter(s => s.threshold != null).length;
    return gatedCount ? `게이트 ${gatedCount}개 항목 전부 통과` : '통과 (지표 미기록)';
  }
  // 판정 없음 — 왜 없는지를 말한다(빈 칸으로 두면 '문제 없음' 으로 읽힌다).
  return run.summary ? '서버가 판정을 남기지 않은 실행' : '요약이 기록되지 않은 실행';
}

/** ISO 문자열 → `MM-DD HH:mm`. */
function fmtWhen(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/**
 * 실패 응답을 사람이 읽는 한 줄로.
 *
 * 403 을 그냥 "HTTP 403" 으로 흘리면 사용자는 서버 장애로 읽는다. Sw* 빌더는
 * 관리자 전용이므로(라우터 `dependencies=[Depends(require_admin)]`) **권한 상태**임을
 * 명시한다 — 조회는 되는데 생성만 막히는 상황이 정상 동작이라는 걸 화면이 말해야 한다.
 */
async function describeBuildError(res) {
  if (res.status === 403) return '관리자 전용 빌더입니다 — 조회는 되지만 생성은 관리자 등록이 필요합니다.';
  if (res.status === 401) return '로그인이 필요합니다.';
  let detail = '';
  try {
    const j = await res.json();
    if (Array.isArray(j?.detail)) {
      detail = j.detail
        .map(d => {
          const loc = (d?.loc || []).filter(x => x !== 'body').join('.');
          const msg = d?.msg || d?.type || '';
          return loc ? `${loc}: ${msg}` : msg;
        })
        .join(', ');
    } else if (typeof j?.detail === 'string') detail = j.detail;
    else if (j?.message) detail = j.message;
  } catch (_e) {
    // 비 JSON 본문(502 HTML 등) — status 로 폴백한다.
  }
  return detail || `HTTP ${res.status}`;
}

/** Content-Disposition 에서 파일명. RFC 5987(UTF-8) 우선. */
function filenameFrom(res, fallback) {
  const cd = res.headers.get('Content-Disposition') || '';
  const m = cd.match(/filename\*=UTF-8''([^;]+)/) || cd.match(/filename="([^"]+)"/);
  if (!m) return fallback;
  try { return decodeURIComponent(m[1]); } catch (_e) { return m[1]; }
}

function Pill({ tone, children }) {
  return <span className={`pill pill-${tone}`}>{children}</span>;
}

function DeltaMark({ delta }) {
  if (delta == null) return null;
  const n = Number(delta);
  if (!Number.isFinite(n) || n === 0) return null;
  const up = n > 0;
  return (
    <span
      title={`직전 같은 프로젝트 실행 대비 ${up ? '+' : ''}${n.toFixed(1)}`}
      style={{ marginLeft: 4, fontSize: 'var(--text-xs)', color: up ? 'var(--color-success)' : 'var(--color-danger)' }}
    >
      {up ? '▲' : '▼'}{Math.abs(n).toFixed(1)}
    </span>
  );
}

export default function DocGenStatusBoard({ job, analysisResult, genState, onGenerate, onNavigateSub }) {
  const toast = useToast();
  const { cfg } = useJenkinsCfg();
  const [runs, setRuns] = useState(null);      // null = 미조회, [] = 조회했고 없음
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const [expanded, setExpanded] = useState(null);   // 펼친 doc_type
  const [detail, setDetail] = useState({});         // {docType: {evidence, advice, loading, error}}

  // 프로젝트 축. Dashboard 가 매칭한 SCM(수동 override 포함)을 그대로 쓴다 —
  // `scmList[0]` 폴백은 쓰지 않는다(다중 등록 환경에서 남의 프로젝트 이력을 그린다).
  const scmId = analysisResult?.matchedScm?.id || '';
  const scmName = analysisResult?.matchedScm?.name || analysisResult?.matchedScm?.id || '';
  // 게이트가 보는 캐시 루트 = **생성이 쓰는 캐시 루트**(`resolveCacheRoot` 단일 출처).
  const cacheRoot = resolveCacheRoot(analysisResult, job, cfg);
  // 상한/선택지 저장 칸 — **생성 요청과 같은 함수**로 구한다. 갈리면 게이트가 보여 준
  // 값과 실제로 실리는 값이 달라진다(`resolveCacheRoot` 와 같은 사유).
  const capsScope = docGenCapsScope(job);
  // 결과 뭉치가 지금 보고 있는 Job 의 것인가 — 생성 거부와 **같은 판정**을 쓴다.
  const ctxConflict = contextConflict(analysisResult, job?.url);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const qs = new URLSearchParams({ limit: '40', include_scores: 'true' });
      if (scmId) qs.set('scm_id', scmId);
      const data = await api(`/api/quality/runs?${qs.toString()}`);
      // 모듈 부재는 200 + error 로 온다 — 빈 목록으로 접지 않는다.
      if (data?.error) { setLoadError(String(data.error)); setRuns([]); return; }
      setRuns(Array.isArray(data?.runs) ? data.runs : []);
    } catch (e) {
      setLoadError(e?.message || '품질 이력을 불러오지 못했습니다.');
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }, [scmId]);

  useEffect(() => { load(); }, [load]);

  // 생성이 끝나면 이력을 다시 읽어 방금 결과를 반영한다.
  // 트리거는 `result` **객체 identity** 다 — 생성 완료/실패 시에만 새 객체가 되고
  // 재렌더로는 바뀌지 않는다(부모가 넘기는 genState 는 매번 새 객체라 그걸 보면
  // 렌더 루프가 된다).
  const genResult = genState?.result;
  useEffect(() => {
    if (!genResult) return;
    load();
  }, [genResult, load]);

  /** doc_type → 최신 run (목록은 created_at desc 이므로 처음 만난 것이 최신). */
  const latestByType = useMemo(() => {
    const out = {};
    for (const r of (runs || [])) {
      const k = String(r.doc_type || '').toLowerCase();
      if (k && !(k in out)) out[k] = r;
    }
    return out;
  }, [runs]);

  const docSummary = useMemo(() => {
    let pass = 0, judged = 0;
    for (const row of DOC_ROWS) {
      const v = verdictOf(latestByType[row.key]);
      if (v.label === 'PASS') { pass++; judged++; }
      else if (v.label === 'FAIL') judged++;
    }
    return { pass, judged };
  }, [latestByType]);

  const toggleExpand = useCallback(async (docType) => {
    if (expanded === docType) { setExpanded(null); return; }
    setExpanded(docType);
    const run = latestByType[docType];
    if (!run || detail[docType]) return;   // 이미 받았으면 재요청하지 않는다
    setDetail(prev => ({ ...prev, [docType]: { loading: true } }));
    try {
      // 근거(사이드카)·조치 제안·원인 귀속을 함께. 하나가 실패해도 나머지는 보여준다.
      const [ev, ad, at] = await Promise.allSettled([
        api(`/api/quality/runs/${run.id}/evidence`),
        post(`/api/quality/runs/${run.id}/advice`, {}),
        post('/api/docgen/attribution', {
          run_id: run.id,
          scm_id: scmId || '',
          source_root: analysisResult?.matchedScm?.source_root || '',
          doc_paths: loadDocPaths() || {},
        }),
      ]);
      setDetail(prev => ({
        ...prev,
        [docType]: {
          loading: false,
          evidence: ev.status === 'fulfilled' ? ev.value : null,
          evidenceError: ev.status === 'rejected' ? (ev.reason?.message || '근거 조회 실패') : '',
          advice: ad.status === 'fulfilled' ? ad.value : null,
          adviceError: ad.status === 'rejected' ? (ad.reason?.message || '제안 조회 실패') : '',
          attribution: at.status === 'fulfilled' ? at.value : null,
          attributionError: at.status === 'rejected'
            ? (at.reason?.message || '원인 분석 실패') : '',
        },
      }));
    } catch (e) {
      setDetail(prev => ({ ...prev, [docType]: { loading: false, error: e?.message || '조회 실패' } }));
    }
  }, [expanded, latestByType, detail, scmId, analysisResult]);

  /** 산출물이 **어디에 저장됐는지** 를 화면에서 바로 열게 한다(경로만 보여주면 찾아가야 한다). */
  const handleOpenFolder = useCallback(async (path) => {
    if (!path) { toast('warning', '저장 경로를 알 수 없습니다.'); return; }
    try {
      await post('/api/local/open-folder', { path });
    } catch (e) {
      // 서버가 못 열면 경로라도 알려준다 — 조용히 넘어가면 사용자가 뭘 해야 할지 모른다.
      toast('error', `폴더를 열지 못했습니다: ${e?.message || e} — 경로: ${path}`);
    }
  }, [toast]);

  /**
   * 산출물을 **사용자가 고른 폴더**로 내보낸다.
   *
   * 생성 위치 자체는 신뢰 루트 하위로 confine 돼 있어 바꿀 수 없다(경계이지 결함이
   * 아니다 — `backend/helpers/session.py:95`). 그래서 "경로 선택" 은 완료된 파일의
   * 내보내기로 푼다. 폴더 선택은 이 저장소가 이미 쓰는 worker 네이티브 다이얼로그다.
   */
  const handleSaveAs = useCallback(async (path) => {
    if (!path) { toast('warning', '저장할 파일 경로를 알 수 없습니다.'); return; }
    let dest = '';
    try {
      const picked = await post('/api/file-mode/browse-file', {
        kind: 'directory', title: '문서를 저장할 폴더 선택',
      });
      dest = picked?.path || '';
    } catch (e) {
      toast('error', `폴더 선택 실패: ${e?.message || e}`);
      return;
    }
    if (!dest) return;  // 사용자 취소 — 조용히 끝낸다

    const send = (overwrite) => post('/api/docgen/save-as', { src_path: path, dest_dir: dest, overwrite });
    try {
      const r = await send(false);
      toast('success', `저장했습니다: ${r?.path || dest}`);
    } catch (e) {
      // 같은 이름이 있으면 **묻고** 덮는다. 조용한 덮어쓰기는 되돌릴 수 없다.
      if (e?.code === 'dest_exists') {
        if (!window.confirm(`${e.message}\n덮어쓸까요?`)) return;
        try {
          const r2 = await send(true);
          toast('success', `덮어썼습니다: ${r2?.path || dest}`);
        } catch (e2) {
          toast('error', `저장 실패: ${e2?.message || e2}`);
        }
        return;
      }
      toast('error', `저장 실패: ${e?.message || e}`);
    }
  }, [toast]);

  const handleGenerate = useCallback((docType) => {
    if (!job?.url) { toast('warning', '프로젝트를 먼저 선택하세요.'); return; }
    if (typeof onGenerate === 'function') onGenerate(docType);
    else onNavigateSub?.('docgen');
  }, [job, onGenerate, onNavigateSub, toast]);

  // ── 생성 **준비** 펼침 (근거 펼침과 별개 축: 근거=생성 후, 준비=생성 전) ──────
  //
  // 조회를 자식의 useEffect 가 아니라 **이 펼침 핸들러**에서 한다 — effect 안의 동기
  // setState 는 cascading render 를 만든다(`react-hooks/set-state-in-effect`).
  // 바로 위 `toggleExpand`(근거)도 같은 방식이라 화면 전체가 한 패턴을 쓴다.
  const [prepOpen, setPrepOpen] = useState(null);      // 펼친 doc_type
  const [prep, setPrep] = useState({});                // {docType: {data, loading, error}}

  /**
   * 준비 패널을 **다시** 부를 때 쓸 폼(doc_type → form).
   *
   * `handlePrepAction` 은 `reportRows` 보다 **먼저** 정의된다(아래 blob 유틸의 TDZ 주석과
   * 같은 제약 — deps 배열은 렌더 시점에 평가된다). 그래서 행에서 폼을 끌어올 수 없어
   * ref 로 옮긴다. 안 하면 액션 후 재조회가 폼 없이 돌아 **필수값이 방금 채워졌는데도
   * "값이 필요합니다"** 로 되돌아간다.
   */
  const prepFormRef = useRef({});

  /**
   * 조회 세대 번호(doc_type → n). **응답은 발행 순서대로 오지 않는다.**
   *
   * preflight 비용은 소스 측정 캐시 유무로 수십 배 차이가 나서, 먼저 띄운 요청이
   * 나중에 도착하는 일이 실제로 일어난다. 그러면 늦게 온 **옛 판정**이 새 판정을
   * 덮어쓴다 — 상한을 방금 올렸는데 화면은 계속 "아직 정하지 않았습니다" 다.
   * 이 패널이 없애려던 증상(고른 값이 반영 안 된 것처럼 보임) 그 자체라 그냥 둘 수 없다.
   *
   * 취소(AbortController) 대신 **세대 대조**를 쓴다 — 서버 계산은 이미 끝나 캐시에
   * 남으므로 끊어서 얻을 게 없고, 늦은 응답을 버리기만 하면 된다.
   */
  const prepSeqRef = useRef({});

  /**
   * 결정 질문 — **preflight 와 별도**로 뒤따라 채운다.
   *
   * 문장을 LLM 이 쓰므로 수 초가 걸린다. 한 응답에 묶으면 준비 상태 표시 전체가 그걸
   * 기다린다. 실패해도 준비 패널은 그대로 살아 있어야 하므로 조용히 비운다
   * (서버가 LLM 없이도 룰 문장으로 답하므로 여기까지 오는 실패는 네트워크뿐이다).
   */
  const loadQuestions = useCallback(async (docType, form, seq) => {
    // 질문은 preflight 와 **같은 세대**에 속한다 — 그 사이 재조회가 있었으면 버린다.
    const fresh = () => seq == null || prepSeqRef.current[docType] === seq;
    try {
      const res = await post('/api/docgen/questions', {
        doc_type: docType,
        scm_id: scmId || '',
        source_root: analysisResult?.matchedScm?.source_root || '',
        doc_paths: loadDocPaths() || {},
        // 시험 결과 6종은 폼 필수값(project_id/버전/시험일)이 결정 항목이라 폼 없이 물으면
        // **항상 같은 질문**이 돌아온다. `loadPrep` 과 같은 값을 싣는다.
        form: form || {},
        // 상한도 마찬가지다 — 안 실으면 사용자가 방금 정한 값을 두고도 질문이 계속
        // "조정할까요?" 로 돌아온다.
        caps: loadDocGenCaps(capsScope) || {},
        // 생성이 보내는 것과 **같은 값**이어야 게이트가 같은 문서를 판정한다.
        asil_level: String(loadSharedInputs()?.asil_level || '').trim(),
      });
      if (!fresh()) return;
      setPrep(p => ({ ...p, [docType]: { ...(p[docType] || {}), questions: res } }));
    } catch (e) {
      if (!fresh()) return;
      setPrep(p => ({
        ...p,
        [docType]: { ...(p[docType] || {}), questionsError: e?.message || '질문을 불러오지 못했습니다.' },
      }));
    }
  }, [scmId, analysisResult, capsScope]);

  /**
   * 준비 점검. `form` 은 **시험 결과 6종 전용**이다.
   *
   * ⚠ 안 실으면 게이트가 항상 "필수값 없음" 을 보고한다 — 백엔드
   * `PreflightRequest.form` 은 프론트 `missingRequiredFields` 판정을 흡수해 **판정이
   * 두 벌이 되지 않게** 하려고 만든 필드라, 비면 판정이 두 벌이 되는 게 아니라
   * 한 벌이 거짓말을 한다. 양식 템플릿 조회도 `form.project_id` 로 시작한다.
   */
  const loadPrep = useCallback(async (docType, form) => {
    prepFormRef.current[docType] = form || {};
    const seq = (prepSeqRef.current[docType] || 0) + 1;
    prepSeqRef.current[docType] = seq;
    const fresh = () => prepSeqRef.current[docType] === seq;
    setPrep(p => ({ ...p, [docType]: { ...(p[docType] || {}), loading: true } }));
    try {
      const res = await post('/api/docgen/preflight', {
        doc_type: docType,
        scm_id: scmId || '',
        source_root: analysisResult?.matchedScm?.source_root || '',
        doc_paths: loadDocPaths() || {},
        // UDS 는 Jenkins 빌드 캐시가 있어야 시작한다 — 게이트가 그걸 확인하려면
        // 화면이 보고 있는 job/캐시를 알아야 한다.
        job_url: job?.url || '',
        // ⚠ 생성 요청과 **같은 폴백 사슬**을 타야 한다(`resolveCacheRoot`).
        //   빈 값이면 백엔드가 `~/.devops_pro_cache` 로 떨어져 화면이 쓰는
        //   `.devops_pro_cache/<user>` 와 다른 폴더를 보고, UDS 빌드 캐시를
        //   "없음"(=진행 불가)으로 보고하면서 정작 생성은 성공한다.
        cache_root: cacheRoot,
        form: form || {},
        // 사용자가 이 화면에서 정한 상한. **판정에만** 쓴다(정했는가 / 안 정했는가) —
        // 안 실으면 값을 넣어도 게이트는 계속 "결정 필요" 라 자기 선택이 반영됐는지
        // 알 수 없고, 4개 문서가 영원히 `준비 완료` 에 닿지 못한다.
        caps: loadDocGenCaps(capsScope) || {},
        // 생성이 보내는 것과 **같은 값**이어야 게이트가 같은 문서를 판정한다.
        asil_level: String(loadSharedInputs()?.asil_level || '').trim(),
      });
      // 늦게 온 옛 응답은 버린다 — 새 판정을 덮으면 방금 고른 값이 사라져 보인다.
      if (!fresh()) return;
      // 200 + error 를 성공으로 삼지 않는다.
      if (res?.error) {
        setPrep(p => ({ ...p, [docType]: { loading: false, error: String(res.error) } }));
        return;
      }
      setPrep(p => ({ ...p, [docType]: { loading: false, data: res, error: '' } }));
      // 준비 상태를 먼저 그리고 질문은 뒤따라 채운다(LLM 이라 느리다).
      loadQuestions(docType, form, seq);
    } catch (e) {
      if (!fresh()) return;
      setPrep(p => ({
        ...p,
        [docType]: { loading: false, error: e?.message || '준비 상태를 확인하지 못했습니다.' },
      }));
    }
    // `job` 은 빌드 캐시 확인에 쓰인다 — 빼면 프로젝트를 바꿔도 옛 job 으로 판정한다.
    // `cacheRoot` 는 `cfg` 에서도 오므로 파생값을 직접 구독한다(설정만 바꾸면
    // `analysisResult`·`job` 이 그대로라 옛 캐시 루트로 계속 판정하게 된다).
  }, [scmId, analysisResult, job, cacheRoot, capsScope, loadQuestions]);

  // 상한/선택지가 바뀌면 **펼쳐져 있는 행을 다시 판정**한다.
  //
  // ⚠ 오래 통지가 없었다. 입력칸의 `onSaved` 는 그 행만 되불렀으므로, 같은 상한이
  //   걸린 다른 행(같은 소스를 재는 문서들)은 옛 판정을 그대로 들고 있었다 — 한 화면의
  //   두 줄이 같은 값에 대해 다른 말을 한다. 다른 탭에서 바뀐 경우도 같은 경로로 온다.
  const reloadOpenPrep = useCallback(() => {
    if (!prepOpen) return;
    loadPrep(prepOpen, prepFormRef.current[prepOpen] || {});
  }, [prepOpen, loadPrep]);
  useDocGenCapsSync(reloadOpenPrep);

  const togglePrep = useCallback((docType, form) => {
    if (prepOpen === docType) { setPrepOpen(null); return; }
    setPrepOpen(docType);
    if (!prep[docType]?.data) loadPrep(docType, form);
  }, [prepOpen, prep, loadPrep]);

  // ── blob 다운로드 유틸 ───────────────────────────────────────────────────
  //
  // 시험 결과 섹션(아래)과 준비 패널의 CSV 내보내기가 **둘 다** 쓴다. 그래서 두 소비처
  // 중 **먼저 오는 쪽 앞**에 둔다 — 뒤에 두면 `handlePrepAction` 의 deps 배열이 정의
  // 전에 평가되어 TDZ ReferenceError 가 난다(`react-hooks/exhaustive-deps` 가 그 deps 를
  // 요구하므로 순서를 맞추는 것이 정답이고, deps 를 빼는 건 회피다).
  const blobCleanupRef = useRef([]);

  useEffect(() => () => {
    // 언마운트 시 blob URL 즉시 회수 + 예약 타이머 취소(누수 방지).
    blobCleanupRef.current.forEach(({ timerId, url }) => {
      clearTimeout(timerId);
      try { URL.revokeObjectURL(url); } catch (_e) { /* 이미 회수됨 */ }
    });
    blobCleanupRef.current = [];
  }, []);

  const triggerDownload = useCallback((blob, filename) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    const timerId = setTimeout(() => {
      try { URL.revokeObjectURL(url); } catch (_e) { /* 이미 회수됨 */ }
      blobCleanupRef.current = blobCleanupRef.current.filter(i => i.timerId !== timerId);
    }, 5000);
    blobCleanupRef.current.push({ timerId, url });
  }, []);

  /** 준비 패널의 액션. 실동작이 없는 것은 **조용히 넘기지 않고** 무엇을 해야 하는지 말한다. */
  const handlePrepAction = useCallback(async (action, step) => {
    const kind = action?.kind;
    if (kind === 'measure_source') {
      const root = analysisResult?.matchedScm?.source_root || '';
      if (!root) { toast('warning', '소스 루트가 없습니다 — SCM 설정을 확인하세요.'); return; }
      toast('info', '소스를 측정합니다 — 수십 초 이상 걸릴 수 있습니다.');
      try {
        // 시험 문서(STS/SITS/SUTS)는 요구 매핑·통합 흐름·변수 타입까지, UDS 는 분류별·
        // 파일 스캔 상한의 실제 절단량까지 잰다.
        //
        // ⚠ 어느 문서로 잴지는 **서버가 정한다**(`_resolve_inputs`). 예전엔 여기서
        //   `paths.sds || matchedScm.linked_docs.sds` 로 직접 골랐는데, 그건 백엔드
        //   우선순위 규칙의 복제라 조금만 갈려도 preflight 의 캐시 조회 키와 어긋난다 —
        //   측정을 해도 게이트가 계속 "아직 재지 않았습니다" 로 남는다. `loadPrep` 과
        //   **같은 두 값**만 싣는다.
        await post('/api/docgen/measure-source', {
          source_root: root,
          doc_type: prepOpen || '',
          scm_id: scmId || '',
          doc_paths: loadDocPaths() || {},
        });
        if (prepOpen) loadPrep(prepOpen, prepFormRef.current[prepOpen]);
      } catch (e) {
        toast('error', `소스 측정 실패: ${e?.message || e}`);
      }
      return;
    }
    if (kind === 'run_worker') {
      toast('warning', 'Cloudium worker 가 응답하지 않습니다 — excel_rename_gui_v2.exe 를 실행한 뒤 다시 확인하세요.');
      return;
    }
    if (kind === 'adopt_suggestion') {
      // 설정에 복사하지 않고 **레지스트리를 갱신**한다 — 설정에 복사하면 그 순간 또
      // 굳고, 이번엔 설정이 SCM 을 가려 더 안 보인다.
      if (!scmId) { toast('warning', 'SCM 프로젝트가 매칭되지 않아 교체할 수 없습니다.'); return; }
      try {
        // ⚠ `doc_key` 는 서버가 액션에 실어 준 **레지스트리 키**(`action.target`)다.
        //   `step.id` 는 입력 키(`swrs`/`swds`/`uds_doc`)라 `adopt-doc-path` 가 모른다 —
        //   그걸 보내던 동안 이 버튼은 `hsis`/`stp` 빼고 전부 400 이었다(2026-09-03).
        //   `step.id` 폴백은 두 키가 같은 옛 서버 응답과의 호환일 뿐이다.
        const res = await post('/api/docgen/adopt-doc-path', {
          scm_id: scmId, doc_key: action?.target || step?.id || '', filename: action?.value || '',
        });
        notifyScmRegistryChanged();
        toast('success', `${step?.label || '문서'} 경로를 교체했습니다: ${res?.new || ''}`);
        if (prepOpen) loadPrep(prepOpen, prepFormRef.current[prepOpen]);
      } catch (e) {
        // 403(관리자 전용)은 장애가 아니라 권한 상태다.
        const msg = String(e?.message || e);
        toast('error', /403/.test(msg)
          ? '경로 교체는 관리자만 할 수 있습니다 — 설정 > SCM 에서 변경하세요.'
          : `경로 교체 실패: ${msg}`);
      }
      return;
    }
    if (kind === 'export_comment_targets') {
      const root = analysisResult?.matchedScm?.source_root || '';
      try {
        const res = await post('/api/docgen/comment-targets', { source_root: root });
        if (!res?.ok) { toast('warning', res?.reason || '목록을 만들지 못했습니다.'); return; }
        const rows = [
          ['구분', '파일', '함수', '현재 설명'],
          ...(res.no_comment || []).map(r => ['주석 없음', r.file, r.function, '']),
          ...(res.empty_comment || []).map(r => ['내용 없음', r.file, r.function, r.current || '']),
        ];
        // Excel 이 UTF-8 을 알아보게 BOM 을 붙인다(한글 깨짐 방지).
        const csv = '﻿' + rows
          .map(cols => cols.map(c => `"${String(c ?? '').replace(/"/g, '""')}"`).join(','))
          .join('\r\n');
        triggerDownload(new Blob([csv], { type: 'text/csv;charset=utf-8' }),
          `comment_targets_${scmId || 'project'}.csv`);
        toast('success', `주석 보강 대상 ${res.total_targets}건을 내려받았습니다.`);
      } catch (e) {
        toast('error', `목록 생성 실패: ${e?.message || e}`);
      }
      return;
    }
    if (kind === 'pick_path' || kind === 'open_scm') {
      toast('info', `${step?.label || '입력'} 은 설정 > 입력 자료 또는 SCM 등록에서 지정합니다.`);
      return;
    }
    if (kind === 'input_value') {
      toast('info', `${step?.label || '값'} 은 해당 빌더 탭에서 조정합니다.`);
      return;
    }
    toast('info', `아직 지원하지 않는 동작입니다: ${kind}`);
  }, [analysisResult, scmId, prepOpen, loadPrep, toast, triggerDownload]);

  const builderRows = BUILDER_ROWS.filter(b => latestByType[b.key]);

  // ── 시험 결과 문서 원클릭 생성 ────────────────────────────────────────────
  const [reportState, setReportState] = useState({});      // {key: {busy, error}}
  const [versionEdit, setVersionEdit] = useState({});       // {key: '1.02'} 사용자 직접 입력

  /**
   * 각 행의 실제 빌드 입력. 폼(저장값+공유입력+기본값)에 버전 폴백을 얹는다.
   *
   * 버전 폴백 순서: 사용자가 이 화면에서 입력 > 빌더 탭 저장 폼 > **같은 프로젝트의
   * 직전 실행에 기록된 버전**(백엔드가 meta.release_sw_version 으로 남긴다) > 없음.
   * 마지막이 빈 문자열인 채로 두는 것이 요점이다 — 지어내지 않는다.
   */
  const reportRows = useMemo(() => {
    const runVer = (runs || []).map(r => r?.meta?.release_sw_version).find(Boolean) || '';
    return TEST_REPORT_ROWS.map(row => {
      const form = loadBuilderForm(row.builder);
      const version = versionEdit[row.key] ?? (form.release_sw_version || runVer);
      // SCM 이 지정한 **양식 설정 키**가 있으면 그게 이긴다. 없으면 빌더 폼 값
      // (기본이 `HDPDM01` 로 하드코딩돼 있어 남의 프로젝트 문서가 나오던 자리다).
      // ⚠ 통합 Summary 의 `project_id` 는 프로젝트가 아니라 **마스터 양식 ID** 라
      //   SCM 값으로 덮으면 안 된다 — 덮으면 양식을 못 찾는다.
      const scmBuilderId = row.builder === 'swreport'
        ? '' : String(analysisResult?.matchedScm?.builder_project_id || '').trim();
      const projectId = scmBuilderId || String(form.project_id || '');
      return {
        ...row,
        form,
        version,
        projectId,
        // ⚠ 빌드 payload 와 준비 점검 payload 를 **같은 값**으로 둔다. 갈라지면 게이트가
        //   본 것과 실제로 만들어지는 것이 달라진다 — 그건 게이트가 없는 것보다 나쁘다.
        //
        // ⚠ `scm_id` 를 함께 싣는 이유(2026-08-24 라이브 실측): 안 실으면 백엔드가
        //   `project_id` 에서 프로젝트 축을 **추측**하는데, 문자열 "KJPDS02" 가 SCM entry
        //   `kjpds02` 의 id 이면서 동시에 `kjpds02_pv` 의 builder_project_id 라 추측이
        //   `kjpds02` 로 빗나갔다. 그러면 이 보드(`kjpds02_pv` 로 조회)는 **방금 만든
        //   문서를 영영 "미생성"** 으로 표시한다 — 빌드도 기록도 정상인데 화면만 침묵한다.
        //   문자열만으로 갈리지 않는 모호함이라, 아는 쪽인 화면이 실어 보낸다.
        payloadForm: {
          ...form, release_sw_version: version, project_id: projectId, scm_id: scmId || '',
        },
        versionSource: versionEdit[row.key] != null ? 'input'
          : form.release_sw_version ? 'saved' : (runVer ? 'run' : 'none'),
        // 화면 범위와 빌드 대상이 다르면 다른 프로젝트 문서를 만들게 된다 —
        // 조용히 진행하지 않고 행에 표시한다(자동 교정은 하지 않는다: swut_meta.json
        // 에 등록되지 않은 project_id 로 바꾸면 빌드가 통째로 실패한다).
        // ⚠ `scmId`(SCM 등록 id)와 `project_id`(양식 설정 키)는 **원래 다른 어휘**다 —
        //   실측: SCM `kjpds02_pv` ↔ swut_meta `KJPDS02`. 둘을 문자열 비교하던 옛 판정은
        //   정상 구성에도 "다릅니다" 를 띄웠다(거짓 경고).
        //   진짜 위험은 **양식 키를 아무도 지정하지 않아 빌더 폼 기본값(`HDPDM01`)이
        //   그대로 쓰이는 것**이다 — 그러면 남의 프로젝트 문서가 나온다. 그 상태만 알린다.
        //   통합 Summary 는 `project_id` 가 마스터 양식 ID 라 이 판정 대상이 아니다.
        needsBuilderId: row.builder !== 'swreport' && !!scmId && !scmBuilderId,
      };
    });
    // ⚠ `builder_project_id` 를 deps 에 넣는다 — 빼면 SCM 에서 양식 키를 지정해도
    //   행이 재계산되지 않아 **옛 project_id 로 빌드**된다(표시만 안 바뀌는 게 아니라
    //   `generateReport` 가 `row.projectId` 를 payload 에 싣는다).
  }, [runs, versionEdit, scmId, analysisResult?.matchedScm?.builder_project_id]);

  /** 그룹 렌더가 행 정의를 계산된 행으로 바꿔 끼우려고 쓴다. */
  const reportRowByKey = useMemo(
    () => Object.fromEntries(reportRows.map(r => [r.key, r])),
    [reportRows],
  );

  const generateReport = useCallback(async (row) => {
    // ⚠ `project_id` 를 **payload 에도** 반영한다. 표시만 바꾸고 빌드에 안 넘기면
    //   화면은 KJPDS02 라고 하는데 실제로는 HDPDM01 문서가 나온다 — 표시와 산출물이
    //   갈리는 것이 원래 결함보다 나쁘다.
    const form = row.payloadForm;
    const missing = missingRequiredFields(form);
    if (missing.length) {
      toast('warning', `필수 값이 비어 있습니다: ${missing.join(', ')} — 임의 값으로 채우지 않습니다.`);
      return;
    }
    setReportState(p => ({ ...p, [row.key]: { busy: true, error: '' } }));
    try {
      // xlsm blob 응답이라 raw fetch. authHeaders() + res.ok 검사 명시 (X9).
      const res = await fetch(buildUrl(row.endpoint), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(toBuildPayload(row.builder, form)),
      });
      if (!res.ok) throw new Error(await describeBuildError(res));
      const blob = await res.blob();
      triggerDownload(blob, filenameFrom(res, row.fallbackName));
      setReportState(p => ({ ...p, [row.key]: { busy: false, error: '' } }));
      toast('success', `${row.label} ${(blob.size / 1024).toFixed(0)} KB 다운로드 완료`);
      load();   // 방금 만든 실행이 표에 반영되도록 이력 재조회
    } catch (e) {
      const msg = e?.message || String(e);
      setReportState(p => ({ ...p, [row.key]: { busy: false, error: msg } }));
      toast('error', `${row.label} 생성 실패: ${msg}`);
    }
  }, [toast, triggerDownload, load]);

  return (
    <div className="docgen-status-board">
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">생성 현황</span>
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
            {docSummary.judged > 0 && (
              <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                게이트 {docSummary.pass}/{docSummary.judged} PASS
                <span title="판정이 성립한 문서만 분모에 든다 — 미생성·판정 불가는 제외">
                  {' '}ⓘ
                </span>
              </span>
            )}
            <button type="button" className="btn-secondary btn-sm" onClick={load} disabled={loading}>
              {loading ? '조회 중…' : '새로고침'}
            </button>
          </span>
        </div>

        {/* 결과 뭉치가 **통째로 다른 Job 의 것**이면 아래 모든 판정이 남의 프로젝트 얘기다.
            생성은 `DocGenSection.generateDoc` 이 같은 판정으로 **거부**하므로, 여기서는
            왜 거부되는지를 미리 말한다(버튼을 눌러 보고서야 알게 되면 안 된다). */}
        {ctxConflict.conflict && (
          <div role="alert" style={{
            marginBottom: 'var(--sp-3)', fontSize: 'var(--text-sm)',
            color: 'var(--color-danger)',
          }}>
            ⚠ 이 화면의 분석 결과가 현재 프로젝트의 것이 아닙니다 — {mismatchText(ctxConflict.reason)}.
            아래 준비 점검과 점수는 <strong>다른 프로젝트</strong>의 자료로 계산됐을 수 있고,
            문서 생성은 막혀 있습니다.
          </div>
        )}

        {/* 프로젝트 스코프를 화면이 말해야 한다 — 어느 프로젝트 이력인지 모르면 숫자가 무의미하다 */}
        <div style={{ marginBottom: 'var(--sp-3)', fontSize: 'var(--text-sm)' }}>
          {scmId ? (
            <>프로젝트 <strong>{scmName}</strong> 의 최근 생성 이력</>
          ) : (
            <span style={{ color: 'var(--color-warning)' }}>
              ⚠ SCM 프로젝트가 매칭되지 않아 <strong>전체 이력</strong>을 보여준다 —
              다른 프로젝트의 실행이 섞여 있을 수 있다. (대시보드에서 SCM 매핑을 지정)
            </span>
          )}
        </div>

        {loadError && (
          <div role="alert" style={{ marginBottom: 'var(--sp-3)', color: 'var(--color-danger)', fontSize: 'var(--text-sm)' }}>
            {loadError}
          </div>
        )}

        <div style={{ overflowX: 'auto' }}>
          <table className="board-table">
            <thead>
              <tr>
                <th>문서</th>
                <th>상태</th>
                <th style={{ textAlign: 'right' }}>점수</th>
                <th>왜 이 점수인가</th>
                <th>생성 시각</th>
                <th aria-label="작업" />
              </tr>
            </thead>
            <tbody>
              {DOC_ROWS.map(row => {
                const run = latestByType[row.key];
                const busy = genState?.docType === row.key;
                const v = busy ? { tone: 'info', label: '생성 중' } : verdictOf(run);
                const isOpen = expanded === row.key;
                return (
                  <FragmentRow
                    key={row.key}
                    row={row}
                    run={run}
                    busy={busy}
                    genState={genState}
                    verdict={v}
                    isOpen={isOpen}
                    detail={detail[row.key]}
                    onToggle={() => toggleExpand(row.key)}
                    onGenerate={() => handleGenerate(row.key)}
                    disabled={!!genState?.docType}
                    lastResult={genResult?.docType === row.key ? genResult : null}
                    onOpenFolder={handleOpenFolder}
                    onSaveAs={handleSaveAs}
                    prepIsOpen={prepOpen === row.key}
                    prepState={prep[row.key]}
                    capsScope={capsScope}
                    onTogglePrep={() => togglePrep(row.key)}
                    onPrepReload={() => loadPrep(row.key)}
                    onPrepAction={handlePrepAction}
                  />
                );
              })}
            </tbody>
          </table>
        </div>

        {runs !== null && runs.length === 0 && !loadError && (
          <div className="empty-state" style={{ marginTop: 'var(--sp-3)' }}>
            품질 이력이 없습니다 — 문서를 생성하면 게이트 결과가 여기 쌓입니다.
          </div>
        )}
      </div>

      {/* 릴리스 버전만 사람이 정한다 — 나머지는 이미 어딘가에 있고, 없는 값을 지어내지 않는다. */}
      <div style={{ marginTop: 'var(--sp-4)', fontSize: 'var(--text-sm)' }}>
        <strong>시험 결과 문서</strong>
        <span style={{ marginLeft: 8, fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
          릴리스 버전만 입력하면 나머지는 직전 빌드·공유 설정·프로젝트 config 기본값으로
          만듭니다. 세부 조정은 각 탭에서.
        </span>
      </div>

      {TEST_LEVEL_GROUPS.map(group => (
        <div className="panel" style={{ marginTop: 'var(--sp-2)' }} key={group.id}>
          <div className="panel-header">
            <span className="panel-title">{group.title}</span>
            <span style={{ marginLeft: 'auto', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
              {group.hint}
            </span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className="board-table">
              <thead>
                <tr>
                  <th>문서</th>
                  <th>상태</th>
                  <th style={{ textAlign: 'right' }}>점수</th>
                  <th>왜 이 점수인가</th>
                  <th>릴리스 버전</th>
                  <th>생성 시각</th>
                  <th aria-label="작업" />
                </tr>
              </thead>
              <tbody>
                {group.rows.map(def => {
                  const row = reportRowByKey[def.key];
                  if (!row) return null;
                  return (
                    <TestReportRow
                      key={row.key}
                      row={row}
                      run={latestByType[row.key]}
                      state={reportState[row.key]}
                      scmId={scmId}
                      onVersionChange={v => setVersionEdit(pv => ({ ...pv, [row.key]: v }))}
                      onGenerate={() => generateReport(row)}
                      onNavigateSub={() => onNavigateSub?.(row.sub)}
                      prepIsOpen={prepOpen === row.key}
                      prepState={prep[row.key]}
                    capsScope={capsScope}
                      /* 준비 점검에는 **빌드가 보내는 것과 같은 shape** 을 싣는다 —
                         `toBuildPayload` 가 `source_paths_text`(textarea) 를 `source_paths`
                         배열로 바꾼다. 원본 폼을 보내면 통합 Summary 의 레벨별 산출물을
                         게이트가 영영 못 본다(서버는 라우터와 같은 키 `source_paths` 만 읽는다). */
                      onTogglePrep={() => togglePrep(row.key, toBuildPayload(row.builder, row.payloadForm))}
                      onPrepReload={() => loadPrep(row.key, toBuildPayload(row.builder, row.payloadForm))}
                      onPrepAction={handlePrepAction}
                    />
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      ))}

      {builderRows.length > 0 && (
        <div className="panel" style={{ marginTop: 'var(--sp-4)' }}>
          <div className="panel-header">
            <span className="panel-title">빌더 산출물</span>
            <span style={{ marginLeft: 'auto', fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
              이력이 있는 것만 표시
            </span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className="board-table">
              <thead>
                <tr>
                  <th>산출물</th><th>상태</th>
                  <th style={{ textAlign: 'right' }}>점수</th>
                  <th>왜 이 점수인가</th><th>생성 시각</th><th aria-label="작업" />
                </tr>
              </thead>
              <tbody>
                {builderRows.map(b => {
                  const run = latestByType[b.key];
                  const v = verdictOf(run);
                  return (
                    <tr key={b.key}>
                      <td><strong>{b.label}</strong></td>
                      <td><Pill tone={v.tone}>{v.label}</Pill></td>
                      <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                        {fmtScore(run?.summary?.overall_score)}
                        <DeltaMark delta={run?.summary?.score_delta} />
                      </td>
                      <td style={{ fontSize: 'var(--text-xs)' }}>{whyOf(run, v)}</td>
                      <td style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                        {fmtWhen(run?.created_at)}
                      </td>
                      <td>
                        <button type="button" className="btn-secondary btn-sm"
                          onClick={() => onNavigateSub?.(b.sub)}>
                          탭 →
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * 시험 결과 문서 한 행 + 준비 점검 펼침.
 *
 * `DOC_ROWS` 의 `FragmentRow` 와 형제지만 **열 구성이 다르다**(릴리스 버전 열이 있어
 * 7열 — `colSpan` 을 6 으로 두면 펼침 패널이 표 밖으로 삐져나간다). 근거 펼침은
 * 붙이지 않는다 — 6종의 quality 이력이 쌓인 뒤에 판단할 일이다(범위 밖, 사용자 결정).
 *
 * ⚠ 준비 점검 payload 는 `row.payloadForm` 으로 **빌드와 같은 값**을 쓴다. 게이트가 본
 * 폼과 실제 빌드 폼이 다르면 "준비 완료" 뒤에 400 이 난다.
 *
 * @internal 테스트에서 단독 렌더하려고 내보낸다.
 */
export function TestReportRow({
  row, run, state, scmId, onVersionChange, onGenerate, onNavigateSub,
  prepIsOpen, prepState, onTogglePrep, onPrepReload, onPrepAction, capsScope,
}) {
  const st = state || {};
  const v = st.busy ? { tone: 'info', label: '생성 중' } : verdictOf(run);
  return (
    <>
      <tr>
        <td>
          <strong>{row.icon} {row.label}</strong>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
            {row.desc}
            {/* 통합 Summary 의 값은 프로젝트가 아니라 **마스터 양식 ID** 다. */}
            {row.projectId && (
              <> · {row.builder === 'swreport' ? '양식' : '대상'}{' '}
                <code>{row.projectId}</code></>
            )}
          </div>
          {row.needsBuilderId && (
            <div style={{ fontSize: 'var(--text-xs)', color: 'var(--color-warning)' }}>
              ⚠ {scmId} 에 시험 결과 양식 키가 지정되지 않아 기본값
              <code>{row.projectId}</code> 로 만듭니다 — 설정 &gt; SCM 에서
              builder_project_id 를 지정하세요
            </div>
          )}
          {st.error && (
            <div role="alert" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>
              {st.error}
            </div>
          )}
        </td>
        <td><Pill tone={v.tone}>{v.label}</Pill></td>
        <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
          {fmtScore(run?.summary?.overall_score)}
          <DeltaMark delta={run?.summary?.score_delta} />
        </td>
        <td style={{ fontSize: 'var(--text-xs)' }}>{whyOf(run, v)}</td>
        <td>
          {/* 디폴트가 없는 유일한 필수값. 비어 있으면 지어내지 않고 요구한다. */}
          <input
            type="text"
            aria-label={`${row.label} 릴리스 SW 버전`}
            value={row.version}
            placeholder="예: 1.02"
            onChange={e => onVersionChange(e.target.value)}
            style={{ width: 84, fontSize: 'var(--text-xs)' }}
          />
          <div style={{ fontSize: 'var(--text-xs)', color: row.version ? 'var(--text-muted)' : 'var(--color-warning)' }}>
            {row.version
              ? { input: '직접 입력', saved: '직전 빌드값', run: '직전 실행 기록' }[row.versionSource]
              : '입력 필요'}
          </div>
        </td>
        <td style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
          {fmtWhen(run?.created_at)}
        </td>
        <td style={{ whiteSpace: 'nowrap' }}>
          <button
            type="button" className="btn-primary btn-sm"
            onClick={onGenerate}
            disabled={!!st.busy || !row.version}
            title={row.version ? '' : '릴리스 SW 버전을 입력하세요 — 임의 값으로 채우지 않습니다.'}
          >
            {st.busy ? '생성 중…' : '생성'}
          </button>
          {/* 생성 **전** 조건 — 버전이 비어도 열 수 있어야 한다(무엇이 비었는지 알려주는 게 이 패널의 일). */}
          <button type="button" className="btn-secondary btn-sm" style={{ marginLeft: 4 }}
            onClick={onTogglePrep} aria-expanded={prepIsOpen}>
            {prepIsOpen ? '접기' : '준비'}
          </button>
          <button type="button" className="btn-secondary btn-sm" style={{ marginLeft: 4 }}
            onClick={onNavigateSub}>
            세부 →
          </button>
        </td>
      </tr>
      {prepIsOpen && (
        <tr>
          <td colSpan={7} style={{ background: 'var(--bg)' }}>
            <DocGenPreflightPanel
              data={prepState?.data}
              loading={!!prepState?.loading}
              error={prepState?.error || ''}
              questions={prepState?.questions}
              questionsError={prepState?.questionsError || ''}
              onReload={onPrepReload}
              onAction={onPrepAction}
              scope={capsScope}
            />
          </td>
        </tr>
      )}
    </>
  );
}

/**
 * 한 문서 행 + 두 종류 펼침. `<tbody>` 안이라 Fragment 로 여러 `<tr>` 을 낸다.
 *
 * 펼침이 둘인 이유: **`준비`는 생성 전 조건, `근거`는 생성 후 품질**이라 답하는 질문이
 * 다르다. 한 행에 나란히 두면 "지금 만들면 어떻게 되는가" 와 "왜 이 점수인가" 를 같은
 * 자리에서 볼 수 있다. 동시에 펼쳐도 무방하다(서로 다른 `<tr>`).
 */
/** @internal 테스트에서 단독 렌더하려고 내보낸다(보드 전체 마운트는 이 행을 못 겨눈다). */
export function FragmentRow({
  row, run, busy, genState, verdict, isOpen, detail, onToggle, onGenerate, disabled,
  prepIsOpen, prepState, onTogglePrep, onPrepReload, onPrepAction, capsScope,
  lastResult, onOpenFolder, onSaveAs,
}) {
  const pct = busy ? Number(genState?.progress || 0) : null;
  return (
    <>
      <tr>
        <td>
          <strong>{row.icon} {row.label}</strong>
          <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{row.desc}</div>
        </td>
        <td>
          {busy ? (
            /* 진행바만 두면 (a) 무엇의 진행인지 모호하고 (b) 다른 행은 pill 인데 이 행만
               형태가 달라 열이 무엇을 말하는 열인지 흔들린다 — 라벨을 함께 둔다. */
            <div style={{ minWidth: 96 }}>
              <Pill tone={verdict.tone}>{verdict.label}</Pill>
              <div style={{ height: 6, marginTop: 4, background: 'var(--border)', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{ height: '100%', width: `${pct}%`, background: 'var(--accent)', transition: 'width .4s ease' }} />
              </div>
              <span style={{ fontSize: 'var(--text-xs)' }}>{pct}%</span>
            </div>
          ) : <Pill tone={verdict.tone}>{verdict.label}</Pill>}
        </td>
        <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
          {busy ? '—' : fmtScore(run?.summary?.overall_score)}
          {!busy && <DeltaMark delta={run?.summary?.score_delta} />}
        </td>
        <td style={{ fontSize: 'var(--text-xs)' }}>
          {busy ? (genState?.stage || '진행 중') : whyOf(run, verdict)}
        </td>
        <td style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
          {busy ? '—' : fmtWhen(run?.created_at)}
        </td>
        <td style={{ whiteSpace: 'nowrap' }}>
          <button type="button" className="btn-primary btn-sm" onClick={onGenerate} disabled={disabled}>
            {busy ? '생성 중…' : '생성'}
          </button>
          {/* 준비는 **생성 이력과 무관하게** 항상 물을 수 있어야 한다 — 한 번도 만든 적
              없는 문서일수록 "무엇이 부족한가" 가 더 필요하다. */}
          <button type="button" className="btn-secondary btn-sm" style={{ marginLeft: 4 }}
            onClick={onTogglePrep} aria-expanded={!!prepIsOpen}>
            {prepIsOpen ? '준비 접기' : '준비'}
          </button>
          {run && (
            <button type="button" className="btn-secondary btn-sm" style={{ marginLeft: 4 }}
              onClick={onToggle} aria-expanded={isOpen}>
              {isOpen ? '접기' : '근거'}
            </button>
          )}
        </td>
      </tr>
      {lastResult?.success && (
        <tr>
          <td colSpan={6} style={{ background: 'var(--bg)', fontSize: 'var(--text-xs)' }}>
            {/* "생성 완료" 만으로는 **파일을 찾을 수 없다** — 저장 위치를 같은 자리에서 말한다. */}
            <span style={{ color: 'var(--text-muted)' }}>저장 위치 </span>
            {lastResult.path ? (
              <>
                <code style={{ wordBreak: 'break-all' }}>{lastResult.path}</code>
                <button type="button" className="btn-secondary btn-sm" style={{ marginLeft: 8 }}
                  onClick={() => onOpenFolder?.(lastResult.path)}>폴더 열기</button>
                <button type="button" className="btn-secondary btn-sm" style={{ marginLeft: 4 }}
                  onClick={() => onSaveAs?.(lastResult.path)}>다른 폴더에 저장</button>
              </>
            ) : (
              /* 서버가 경로를 안 준 경우 — 빈칸으로 두면 "저장 안 됨" 으로 오독한다. */
              <em>서버가 경로를 알려주지 않았습니다 (생성은 완료).</em>
            )}
          </td>
        </tr>
      )}
      {prepIsOpen && (
        <tr>
          <td colSpan={6} style={{ background: 'var(--bg)' }}>
            <DocGenPreflightPanel
              data={prepState?.data}
              loading={!!prepState?.loading}
              error={prepState?.error || ''}
              questions={prepState?.questions}
              questionsError={prepState?.questionsError || ''}
              onReload={onPrepReload}
              onAction={onPrepAction}
              scope={capsScope}
            />
          </td>
        </tr>
      )}
      {isOpen && run && (
        <tr>
          <td colSpan={6} style={{ background: 'var(--bg)' }}>
            <EvidenceDetail run={run} detail={detail} />
          </td>
        </tr>
      )}
    </>
  );
}

/**
 * 원인 귀속 — **"이 칸이 왜 비었나"** 를 사슬 단계로 되짚는다.
 *
 * 채움률만 보면 무엇을 해야 할지 알 수 없다. `ASIL 12%` 는 조치가 아니고,
 * "1순위 소스 `@asil` 0건 · 2순위 SwDS 미연결" 이라야 조치가 보인다.
 *
 * ⚠ **두 시점을 섞지 않는다.** 기여 건수는 생성 당시, 가용성(`have_now`)은 지금이다.
 * 지금 SwDS 를 연결해도 이미 만들어진 문서는 달라지지 않으므로 그 사실을 함께 밝힌다.
 */
export function AttributionDetail({ data, error }) {
  if (error) {
    return (
      <div>
        <div style={{ fontWeight: 700, fontSize: 'var(--text-xs)', marginBottom: 4 }}>왜 못 채웠나</div>
        <div role="alert" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>{error}</div>
      </div>
    );
  }
  if (!data) return null;
  if (!data.available) {
    // 부재를 빈 칸으로 두지 않는다 — 빈 칸은 "원인이 없다" 로 읽힌다.
    return (
      <div>
        <div style={{ fontWeight: 700, fontSize: 'var(--text-xs)', marginBottom: 4 }}>왜 못 채웠나</div>
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
          분석 불가 — {data.reason || '사유 미상'}
        </span>
      </div>
    );
  }

  return (
    <div>
      <div style={{ fontWeight: 700, fontSize: 'var(--text-xs)', marginBottom: 4 }}>
        왜 못 채웠나
        {data.total_functions != null && (
          <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>
            {' '}· 함수 {data.total_functions}
            {data.grade && ` · 출처 신뢰도 ${data.grade}`}
          </span>
        )}
      </div>
      {(data.fields || []).map(f => (
        <div key={f.field} style={{ marginBottom: 6, fontSize: 'var(--text-xs)' }}>
          <strong>{f.label}</strong>{' '}
          <span style={{ color: f.grounded_total ? 'var(--text-muted)' : 'var(--color-warning)' }}>
            근거 {f.grounded_total} · 자리채움 {f.ungrounded_total}
          </span>
          <ul style={{ margin: '2px 0 0', paddingLeft: '1.1em', lineHeight: 1.7 }}>
            {(f.rows || []).filter(r => r.grounded).map((r, i) => (
              <li key={`${r.source}-${i}`}>
                <code>{r.source}</code>
                {r.input_label && ` (${r.input_label})`}
                {': '}
                <strong style={{ color: r.contributed ? 'var(--color-success)' : 'var(--color-danger)' }}>
                  {r.contributed ? `${r.count}건` : '0건'}
                </strong>
                {/* 지금 상태는 생성 당시와 다를 수 있다 — 그래서 따로 적는다. */}
                {!r.contributed && r.have_now === true && ' · 지금은 연결됨(재생성하면 반영)'}
                {!r.contributed && r.have_now === false && ' · 지금도 없음'}
                {!r.contributed && r.have_now == null && ' · 현재 상태 확인 안 함'}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {data.timing_note && (
        <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
          ⓘ {data.timing_note.replace(/\*\*/g, '')}
        </div>
      )}
    </div>
  );
}

/** 펼친 근거 — 사이드카(왜 이 품질인가) + 조치 제안. */
function EvidenceDetail({ run, detail }) {
  if (!detail || detail.loading) {
    return <div style={{ padding: 'var(--sp-3)', fontSize: 'var(--text-xs)' }}>근거를 읽는 중…</div>;
  }
  if (detail.error) {
    return <div role="alert" style={{ padding: 'var(--sp-3)', color: 'var(--color-danger)', fontSize: 'var(--text-xs)' }}>{detail.error}</div>;
  }

  const ev = detail.evidence;
  const gate = ev?.gate_report;
  const conf = ev?.confidence;
  const val = ev?.docx_validate;
  const sugg = detail.advice?.suggestions || [];

  return (
    <div style={{ padding: 'var(--sp-3)', display: 'grid', gap: 'var(--sp-3)' }}>
      {/* 1. 문서 품질에 영향을 주는 근거 */}
      <div>
        <div style={{ fontWeight: 700, fontSize: 'var(--text-xs)', marginBottom: 4 }}>문서 품질 근거</div>
        {detail.evidenceError && (
          <div role="alert" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>{detail.evidenceError}</div>
        )}
        {!ev && !detail.evidenceError && <span style={{ fontSize: 'var(--text-xs)' }}>—</span>}
        {ev && (
          <ul style={{ margin: 0, paddingLeft: '1.1em', fontSize: 'var(--text-xs)', lineHeight: 1.7 }}>
            {/* 부재는 반드시 사유와 함께 — 빈 칸은 '문제 없음' 으로 읽힌다 */}
            {gate?.present ? (
              <>
                <li>
                  게이트 항목 {gate.gates_passed ?? '—'} / {gate.gates_total ?? '—'} 통과
                  {gate.total_functions != null && ` · 함수 ${gate.total_functions}개`}
                  {/* 분모 0 인 축은 채점하지 않는다. 이 수가 없으면 "5/11" 이
                      "6건이 미달" 로만 읽혀, 못 잰 축까지 고칠 거리로 보인다. */}
                  {gate.unmeasured_count != null && gate.unmeasured_count > 0 && (
                    <> · <strong>미측정 {gate.unmeasured_count}개</strong>
                      {' — 잴 수 없어 채점에서 뺀 축(0% 아님)'}</>
                  )}
                  {/* (R29 Q-4) 해당 없음은 미측정과 다르다 — 못 잰 게 아니라 잴 대상이 없어
                      판정 밖이고, Gate pass 를 붙들지 않는다. 같은 문구로 접으면 "못 쟀다" 로 읽힌다. */}
                  {gate.not_applicable_count != null && gate.not_applicable_count > 0 && (
                    <> · <strong>해당 없음 {gate.not_applicable_count}개</strong>
                      {' — 잴 대상이 없어 판정 밖(미측정 아님)'}</>
                  )}
                  {/* 잰 값은 있는데 임계 표에 키가 없는 축 — 이게 있으면 Gate pass 는 False 인데
                      "N / N 통과" 만 보이면 사유 없는 FAIL 이 된다(리뷰 W4). */}
                  {gate.ungated_count != null && gate.ungated_count > 0 && (
                    <> · <strong>임계 없음 {gate.ungated_count}개</strong>
                      {' — 쟀지만 판정할 수 없어 Gate pass 가 False'}</>
                  )}
                </li>
                {/* 부분 측정(리뷰 W2): Prototype 을 못 읽은 함수는 입출력 분모에서 빠진 채 나머지로 채점된다.
                    "8 / 8 (100%)" 가 426함수 중 8개만 본 값일 수 있다 — 그 사실을 옆에 둔다. */}
                {gate.prototype_unreadable?.count > 0 && (
                  <li>
                    Prototype 을 읽지 못한 함수 <strong>{gate.prototype_unreadable.count}</strong>
                    {' / '}{gate.prototype_unreadable.total}
                    {' — 입력/출력 채움률은 나머지 함수로만 잰 값'}
                  </li>
                )}
                {gate.tbd_residual?.asil_tbd && (
                  <li>
                    ASIL 미상(TBD) <strong>{gate.tbd_residual.asil_tbd.count}</strong>
                    {' / '}{gate.tbd_residual.asil_tbd.total}
                    {gate.tbd_residual.related_tbd && (
                      <> · Related ID 미상 <strong>{gate.tbd_residual.related_tbd.count}</strong>
                        {' / '}{gate.tbd_residual.related_tbd.total}</>
                    )}
                    {/* (R29 Q-5) 미기재(빈 칸·N/A·-)는 TBD 와 별도 축 — DOCX 경로에선 TBD 가 항상 0 이라
                        이 수가 없으면 asil_non_tbd_rate FAIL 의 사유가 화면에 없다(리뷰 I3). */}
                    {gate.tbd_residual.asil_unfilled?.count > 0 && (
                      <> · ASIL 미기재 <strong>{gate.tbd_residual.asil_unfilled.count}</strong></>
                    )}
                    {gate.tbd_residual.related_unfilled?.count > 0 && (
                      <> · Related ID 미기재 <strong>{gate.tbd_residual.related_unfilled.count}</strong></>
                    )}
                    {' — 미상·미기재가 많을수록 추적성 판정이 약해진다'}
                  </li>
                )}
                {/* (R30 Q-2) 무엇을 채점했는가 — payload 가 없으면 문서를 되읽은 것이라 설명 출처를 알 수 없고
                    (High 0 이 정상), payload 가 있어도 잰 집합은 문서 ∩ payload 다. 이 두 줄이 없으면
                    "429항목 문서 통과" 로 읽힌다. */}
                {gate.payload_present === false && (
                  <li>
                    {/* "없음" 과 "있는데 못 읽음" 은 다르다(리뷰 W1) — 후자는 생성 직후 재채점(torn read) 신호다 */}
                    {gate.payload_read_error
                      ? <>payload 사이드카 <strong>읽기 실패</strong>({gate.payload_read_error})</>
                      : <>payload 사이드카 없음</>}
                    {' — '}<strong>문서 자기 대조</strong>
                    {' (설명 출처를 알 수 없어 근거 있음 0 이 정상, 채움률만 유효)'}
                  </li>
                )}
                {gate.entries_not_in_payload?.count > 0 && (
                  <li>
                    문서 항목 {gate.entries_not_in_payload.total} 중{' '}
                    <strong>{gate.entries_not_in_payload.count}</strong>
                    {'개는 payload 에 없음(생성되지 않은 서식) — 채점 밖'}
                    {/* 통과가 무엇에 대한 통과인가 — 실측: 426 중 18개 채점으로 PASS 가 된 문서가 있다 */}
                    {gate.scored_entries?.total > 0 && (
                      <>{' · 통과/실패는 채점된 '}<strong>{gate.scored_entries.count}</strong>
                        {'개 기준(문서 커버리지 '}
                        {(gate.scored_entries.count / gate.scored_entries.total * 100).toFixed(1)}%)</>
                    )}
                  </li>
                )}
                {gate.payload_not_in_document?.count > 0 && (
                  <li>
                    소스 함수 <strong>{gate.payload_not_in_document.count}</strong>
                    {' / '}{gate.payload_not_in_document.total}
                    {'개가 문서에 없음 — 채점 밖(문서에 없는 함수를 문서 품질로 세지 않는다)'}
                  </li>
                )}
                {gate.description_quality?.high && (
                  <li>
                    설명 출처: 근거 있음 {gate.description_quality.high.count}
                    {' · 키워드 추론 '}{gate.description_quality.medium?.count ?? '—'}
                    {' · 일반 템플릿 '}{gate.description_quality.low?.count ?? '—'}
                    {' — 추론/템플릿 비중이 크면 문서 신뢰도가 낮다'}
                  </li>
                )}
              </>
            ) : (
              <li style={{ color: 'var(--text-muted)' }}>
                게이트 근거 파일 없음 — {gate?.reason || '사유 미상'}
                {ev.sidecars_expected === false && ' (이 문서 종류는 사이드카를 만들지 않는다)'}
              </li>
            )}
            {conf?.present ? (
              <li>
                출처 신뢰도 <strong>{conf.grade ?? '—'}</strong>
                {conf.overall_score != null && ` (${conf.overall_score})`}
                {' — 낮으면 ASIL/Related 가 추론에 기대고 있다는 뜻'}
              </li>
            ) : (
              <li style={{ color: 'var(--text-muted)' }}>출처 신뢰도 근거 없음 — {conf?.reason || '사유 미상'}</li>
            )}
            {val?.present ? (
              <li>
                DOCX 구조 검증 {val.ok === true ? 'OK' : val.ok === false ? '문제 있음' : '판정 불가'}
                {val.issues?.length > 0 && ` · 지적 ${val.issues.length}건`}
                {val.missing_from_docx != null && ` · 문서에 빠진 함수 ${val.missing_from_docx}개`}
                {/* 빈 명세로 나간 heading — "이 문서가 껍데기인가" 의 직접 지표.
                    리더에 대응 키가 없어 여태 화면에 닿은 적이 없었다. */}
                {val.headings_without_payload != null
                  && ` · 빈 명세 heading ${val.headings_without_payload}개`}
                {/* `drop` 으로 통째로 뺀 절. 이걸 안 그리면 위 수치가 **남은 것만**
                    센다는 사실이 사라져, 얇아진 문서가 완결된 것처럼 보인다. */}
                {val.dropped_headings != null && val.dropped_headings > 0 && (
                  <> · <strong>제거된 heading {val.dropped_headings}개</strong>
                    {' — 위 수치는 남은 것만 센다'}</>
                )}
                {/* (R31 Q-8 ②) `대조 불가` 는 리더에서 None 으로 떨어져 **줄이 없는 구판과 같아 보였다** —
                    "빠진 함수 N개" 가 없는 것이 '누락 없음' 이 아니라 '대조 못 함' 인 경우다. */}
                {val.uncomparable === true && (
                  <> · <strong>입력 대비 대조 불가</strong>
                    {' — payload 사이드카 없음/읽기 실패(누락 0건이 아니라 미검증)'}</>
                )}
                {/* (R31 Q-8 ①) 라이터가 `## Warnings (입력 대비)` 에 쓰던 문장들 — "소스 함수 629개가 문서에
                    없다" 같은 공시가 여태 화면에 닿은 적이 없었다. `ok` 를 바꾸지 않는 공시라 목록으로. */}
                {val.warnings?.length > 0 && (
                  <ul style={{ margin: '4px 0 0', paddingLeft: 16, fontSize: 'var(--text-xs)' }}
                    aria-label="구조 검증 경고">
                    {val.warnings.map((w, i) => <li key={i}>{w}</li>)}
                  </ul>
                )}
              </li>
            ) : (
              <li style={{ color: 'var(--text-muted)' }}>구조 검증 근거 없음 — {val?.reason || '사유 미상'}</li>
            )}
          </ul>
        )}
      </div>

      {/* 2. 조치 제안 (백엔드 advisor 의 한국어 label + 조치문 그대로) */}
      <div>
        <div style={{ fontWeight: 700, fontSize: 'var(--text-xs)', marginBottom: 4 }}>
          품질을 올리려면
        </div>
        {detail.adviceError && (
          <div role="alert" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)' }}>{detail.adviceError}</div>
        )}
        {!detail.adviceError && sugg.length === 0 && (
          <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
            {detail.advice?.summary || '제안 없음'}
          </span>
        )}
        {sugg.length > 0 && (
          <ol style={{ margin: 0, paddingLeft: '1.2em', fontSize: 'var(--text-xs)', lineHeight: 1.7 }}>
            {sugg.map((s, i) => (
              <li key={`${s.metric}-${i}`}>
                <strong>{s.label || metricLabel(s.metric)}</strong>
                {s.value != null && s.threshold != null && ` ${fmtPct(s.value)} → 목표 ${fmtPct(s.threshold)}`}
                {s.advice && <> — {s.advice}</>}
              </li>
            ))}
          </ol>
        )}
      </div>

      {/* 3. 원인 귀속 — "이 칸이 왜 비었나" */}
      <AttributionDetail data={detail.attribution} error={detail.attributionError} />

      {/* 4. 실행 메타 */}
      <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
        run #{run.id}
        {run.scm_id && ` · 프로젝트 ${run.scm_id}`}
        {run.meta?.asil_level && ` · ${run.meta.asil_level}`}
        {run.meta?.release_sw_version && ` · v${run.meta.release_sw_version}`}
        {run.output_path && (
          <span style={{ fontFamily: 'monospace', wordBreak: 'break-all' }}> · {run.output_path}</span>
        )}
      </div>
    </div>
  );
}
