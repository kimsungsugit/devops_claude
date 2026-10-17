// (R30) `DocGenStatusBoard.jsx` 에서 옮겼다 — 품질 게이트 run 상세 표(`QualityGateSection.jsx`)도 같은 라벨을 쓴다.
/**
 * 지표 코드 → 한국어 라벨. 생성 현황 보드와 품질 게이트 run 상세 표가 **같은 맵**을 쓴다(R30 — 두 벌이면 갈린다).
 *
 * ⚠ 정본은 백엔드 `workflow/quality/advisor.py` 의 `_*_ADVICE` 표다(지표별 label +
 * 조치문). 여기 있는 건 **접힌 행에 한 줄로 보여줄 때만** 쓰는 축약이고, 행을 펼치면
 * advice API 를 불러 정본 라벨과 조치문을 그대로 쓴다. 그래서 이 맵에 없는 코드는
 * 지어내지 않고 **코드 그대로** 노출한다 — 조용히 빈 칸이 되면 그게 더 나쁘다.
 */
export const METRIC_LABELS = Object.freeze({
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
  // (R30) 생성 근거 — 비게이트 참고지표(정본 라벨은 advisor 표). 공시 보드와 같은 수를 품질 DB 에서 읽는다.
  requirement_boundary_tcs: '요구 원문 경계 TC', requirement_boundary_fact_use_pct: '요구 사실 사용률',
  requirement_boundary_failed: '요구 경계 생성 실패',
  traced_system_boundary_tcs: '시스템 추적 경계 TC', traced_system_documents_read: '읽은 시스템 문서',
  traced_system_documents_unread: '못 읽은 시스템 문서',
  expected_derived_pct: '확정 기대값 비율', expected_derived_cells: '확정 기대값 칸',
  expected_unknown_cells: '기대값 미상 칸', mcdc_designed_pct: 'MC/DC 설계율',
  mcdc_invalidated_pairs: '무효 MC/DC 쌍', source_findings: '소스 소견',
  integration_expected_derived_pct: '통합 확정 기대값 비율', integration_expected_derived_cells: '통합 확정 기대값 칸',
  integration_oracle_evaluated: '통합 기대값 도출 여부', interface_contract_failed: '인터페이스 계약 추출 실패',
});

// 자기 키만 본다 — `constructor`·`toString` 같은 이름이 함수로 새지 않게(R30 review r2 I-5)
export const metricLabel = (code) => (Object.hasOwn(METRIC_LABELS, code) ? METRIC_LABELS[code] : code);
