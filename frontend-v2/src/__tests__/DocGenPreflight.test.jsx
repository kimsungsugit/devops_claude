import { describe, it, expect, vi, beforeEach } from 'vitest';
import { DOCGEN_CAPS_KEY } from '../sharedInputs.js';
import { render, screen, fireEvent } from '@testing-library/react';
import DocGenPreflightPanel from '../components/sections/DocGenPreflightPanel.jsx';

/**
 * 준비 패널 — **모르는 것을 좋게 그리지 않는지**가 이 파일의 본체다.
 *
 * 백엔드가 state 7값을 서로 접지 않고 내려주므로 화면도 접으면 안 된다. 특히
 * `unmeasured`(재지 못함)를 `0` 으로 그리면 "주석이 하나도 없다" 로 읽히고,
 * `degraded`(부족)를 붉게 칠하면 진행 불가로 읽힌다.
 */

const base = (steps, verdict = 'degraded') => ({
  ok: true, doc_type: 'uds', label: 'UDS', verdict, file_mode: 'local', steps,
});

const renderPanel = (data, props = {}) =>
  render(<DocGenPreflightPanel data={data} loading={false} error="" {...props} />);

describe('DocGenPreflightPanel', () => {
  it('unmeasured 는 숫자를 그리지 않고 사유를 보인다', () => {
    renderPanel(base([{
      id: 'comment_coverage', phase: 'material', state: 'unmeasured', label: '소스 주석',
      reason: '아직 측정하지 않았습니다',
    }], 'unknown'));
    expect(screen.getByText(/아직 측정하지 않았습니다/)).toBeInTheDocument();
    // 0 을 그리면 "주석이 하나도 없다" 로 읽힌다.
    expect(screen.queryByText(/함수 0/)).toBeNull();
    expect(screen.queryByText(/설명 0/)).toBeNull();
  });

  it('unmeasured 스텝은 muted 톤이지 error 톤이 아니다', () => {
    const { container } = renderPanel(base([{
      id: 'comment_coverage', phase: 'material', state: 'unmeasured', label: '소스 주석',
      reason: '아직 측정하지 않았습니다',
    }], 'unknown'));
    expect(container.querySelector('.pipeline-step.step-muted')).toBeTruthy();
    expect(container.querySelector('.pipeline-step.step-error')).toBeNull();
  });

  it('degraded 는 경고 톤이지 error 톤이 아니다 — 차단이 아니기 때문', () => {
    const { container } = renderPanel(base([{
      id: 'chain_asil', phase: 'chain', state: 'degraded', label: 'ASIL 등급 출처',
      reason: '근거 있는 출처가 하나도 확보되지 않았습니다',
      chain: [{ source: 'comment', input: 'source_comment', input_label: '소스 주석', have: false, grounded: true }],
    }]));
    expect(container.querySelector('.pipeline-step.step-warn')).toBeTruthy();
    expect(container.querySelector('.pipeline-step.step-error')).toBeNull();
  });

  it('사슬은 단계별 가용성만 보이고 칸 수를 예고하지 않는다', () => {
    renderPanel(base([{
      id: 'chain_asil', phase: 'chain', state: 'degraded', label: 'ASIL 등급 출처',
      chain: [
        { source: 'comment', input: 'source_comment', input_label: '소스 주석', have: false, grounded: true },
        { source: 'sds', input: 'swds', input_label: 'SwDS(설계서)', have: true, grounded: true },
        { source: 'srs', input: 'swrs', input_label: 'SwRS(요구사항)', have: null, grounded: true },
      ],
    }]));
    expect(screen.getByText('comment')).toBeInTheDocument();
    expect(screen.getByText('sds')).toBeInTheDocument();
    // "435칸이 TBD 가 됩니다" 류 단정은 없어야 한다.
    expect(screen.queryByText(/칸.*TBD/)).toBeNull();
    expect(screen.queryByText(/예상/)).toBeNull();
  });

  it('확인하지 않은 출처는 "확인하지 않음" 으로 표시된다 (없음과 구분)', () => {
    renderPanel(base([{
      id: 'chain_asil', phase: 'chain', state: 'degraded', label: 'ASIL 등급 출처',
      chain: [{ source: 'srs', input: 'swrs', input_label: 'SwRS', have: null, grounded: true }],
    }]));
    expect(screen.getByText(/확인하지 않음/)).toBeInTheDocument();
  });

  it('선택 입력은 없을 때의 영향을 함께 보인다', () => {
    renderPanel(base([{
      id: 'swds', phase: 'input', state: 'needed', label: 'SwDS(설계서)',
      reason: '경로가 지정되지 않았습니다',
      effect: 'ASIL·Related·설명의 SwDS 출처가 빠집니다',
    }], 'needs_decision'));
    expect(screen.getByText(/없이 진행하면:/)).toBeInTheDocument();
    expect(screen.getByText(/SwDS 출처가 빠집니다/)).toBeInTheDocument();
  });

  it('stale_path 는 개정본 제안을 보인다', () => {
    renderPanel(base([{
      id: 'swrs', phase: 'input', state: 'stale_path', label: 'SwRS(요구사항)',
      value: 'U:/x/(P_SwRS) spec_v2.03.docx',
      reason: '등록 경로에 파일이 없습니다. 같은 폴더의 개정본으로 보입니다',
      suggestion: '(P_SwRS) spec_v3.01_R.docx',
      actions: [{ kind: 'adopt_suggestion', value: '(P_SwRS) spec_v3.01_R.docx' }],
    }], 'blocked'));
    expect(screen.getByText(/제안: \(P_SwRS\) spec_v3.01_R.docx/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '이 파일로 교체' })).toBeInTheDocument();
  });

  it('액션 버튼이 onAction 으로 배선된다', () => {
    const onAction = vi.fn();
    renderPanel(base([{
      id: 'comment_coverage', phase: 'material', state: 'unmeasured', label: '소스 주석',
      reason: '아직 측정하지 않았습니다',
      actions: [{ kind: 'measure_source' }],
    }], 'unknown'), { onAction });
    fireEvent.click(screen.getByRole('button', { name: '소스 측정' }));
    expect(onAction).toHaveBeenCalledTimes(1);
    expect(onAction.mock.calls[0][0].kind).toBe('measure_source');
  });

  it('알 수 없는 doc_type 은 요구 조건을 지어내지 않는다고 밝힌다', () => {
    renderPanel({ ...base([], 'ready'), unknown_doc_type: true });
    expect(screen.getByText(/지어내지 않습니다/)).toBeInTheDocument();
  });

  it('서버 사유가 있으면 빈 화면 대신 사유를 보인다', () => {
    render(<DocGenPreflightPanel data={null} loading={false} error="모듈을 불러오지 못했습니다" />);
    expect(screen.getByRole('alert')).toHaveTextContent('모듈을 불러오지 못했습니다');
  });

  it('모르는 state 코드는 지어내지 않고 코드 그대로 보인다', () => {
    renderPanel(base([{
      id: 'x', phase: 'input', state: 'brand_new_state', label: '새 항목',
    }]));
    expect(screen.getByText('brand_new_state')).toBeInTheDocument();
  });

  it('캡은 절단 건수가 아니라 여유로 보인다', () => {
    renderPanel(base([{
      id: 'sits_flows', phase: 'material', state: 'ok', label: '통합 흐름',
      measured: { value: 84, of: 120, headroom: 36 },
    }], 'ready'));
    expect(screen.getByText(/여유 36/)).toBeInTheDocument();
  });

  it('여유 0 은 경계 상태로 강조된다 — 절단 0 이어도 안전하지 않다', () => {
    renderPanel(base([{
      id: 'sits_flows', phase: 'material', state: 'degraded', label: '통합 흐름',
      measured: { value: 120, of: 120, headroom: 0 },
      reason: '캡에 닿아 있습니다 — 함수가 늘면 흐름이 잘리기 시작합니다',
    }]));
    expect(screen.getByText(/여유 0/)).toBeInTheDocument();
    expect(screen.getByText(/캡에 닿아 있습니다/)).toBeInTheDocument();
  });

  it('SwDS 보강 0건은 조회·키매칭과 함께 드러난다', () => {
    renderPanel(base([{
      id: 'sits_sds_related', phase: 'material', state: 'degraded',
      label: 'SwDS 기반 Related 보강',
      measured: { value: 0, lookups: 84, key_hits: 38, map_entries: 763 },
      reason: 'SwDS 를 읽었지만 SwCom 을 하나도 얻지 못했습니다',
    }]));
    // 조회는 됐는데 산출이 0 이라는 사실이 세 값으로만 드러난다.
    expect(screen.getByText(/조회 84/)).toBeInTheDocument();
    expect(screen.getByText(/키매칭 38/)).toBeInTheDocument();
    expect(screen.getByText(/맵 763항목/)).toBeInTheDocument();
  });

  it('콜체인 예시를 보인다 — SITS 문서 D열에 그대로 박히는 값이다', () => {
    renderPanel(base([{
      id: 'sits_flows', phase: 'material', state: 'ok', label: '통합 흐름',
      measured: { value: 84, of: 120, headroom: 36 },
      sample: { entry_fn: 'Cpu_LvdStatusChanged', asil: 'QM',
                call_chain: 'Cpu_LvdStatusChanged -> Cpu_OnLvdStatusChanged' },
    }], 'ready'));
    expect(screen.getByText(/Cpu_LvdStatusChanged -> Cpu_OnLvdStatusChanged/)).toBeInTheDocument();
  });

  it('타입 폴백은 건수와 변수 목록을 함께 보인다 — 건수만으론 못 고친다', () => {
    renderPanel(base([{
      id: 'suts_types', phase: 'material', state: 'degraded', label: '입출력 변수 타입 근거',
      measured: { value: 157, of: 206, fallback: 49 },
      reason: '49개가 근거 없이 uint8_t(0~255)로 채워집니다',
      samples: ['[IN] EEPROM_TAddress Addr'],
    }]));
    expect(screen.getByText(/폴백 49/)).toBeInTheDocument();
    expect(screen.getByText(/EEPROM_TAddress/)).toBeInTheDocument();
  });

  it('결정 질문을 보인다', () => {
    renderPanel(base([], 'needs_decision'), {
      questions: {
        questions: [{
          id: 'proceed_without_swds', kind: 'confirm', severity: 'high',
          title: 'SwDS 없이 만들까요?',
          body: 'SwDS 가 연결되지 않았습니다.',
          options: [{ value: 'proceed', label: '이대로 진행' }],
          generated_by: 'rule',
        }],
        llm_used: false, llm_reason: '',
      },
    });
    expect(screen.getByText('SwDS 없이 만들까요?')).toBeInTheDocument();
    // 선택지는 여전히 보인다 — 사용자가 무엇을 결정하는지 알아야 하므로.
    expect(screen.getByText(/이대로 진행/)).toBeInTheDocument();
    // ⚠ 그러나 **누를 수 있는 것처럼 보이면 안 된다.** 예전엔 `pill` 로 그려 버튼처럼
    //   생겼는데 클릭 핸들러가 없어 눌러도 아무 일이 없었다 — 화면이 없는 통제를
    //   약속한 셈이다. 실제 결정은 [생성]을 누르거나 자료를 채우는 것이다.
    expect(screen.queryByRole('button', { name: '이대로 진행' })).toBeNull();
  });

  it('AI 가 쓴 문장은 그 사실을 밝힌다 — 출처를 숨기지 않는다', () => {
    renderPanel(base([], 'needs_decision'), {
      questions: {
        questions: [{
          id: 'q1', kind: 'confirm', severity: 'high', title: '제목',
          body: '본문', options: [], generated_by: 'llm',
        }],
        llm_used: true, llm_reason: '',
      },
    });
    expect(screen.getByText('(AI 작성)')).toBeInTheDocument();
  });

  it('룰 문장에는 AI 표시가 붙지 않는다', () => {
    renderPanel(base([], 'needs_decision'), {
      questions: {
        questions: [{
          id: 'q1', kind: 'confirm', severity: 'high', title: '제목',
          body: '본문', options: [], generated_by: 'rule',
        }],
        llm_used: false, llm_reason: '',
      },
    });
    expect(screen.queryByText('(AI 작성)')).toBeNull();
  });

  it('질문이 없으면 사유를 말한다 — 빈 칸은 "문제 없음" 으로 읽힌다', () => {
    renderPanel(base([], 'ready'), {
      questions: { questions: [], llm_used: false, llm_reason: '결정할 항목이 없습니다' },
    });
    expect(screen.getByText('결정할 항목이 없습니다')).toBeInTheDocument();
  });

  it('질문 조회 실패는 alert 으로 드러나되 준비 패널은 살아 있다', () => {
    renderPanel(base([{
      id: 'swds', phase: 'input', state: 'needed', label: 'SwDS(설계서)',
    }], 'needs_decision'), { questionsError: '질문을 불러오지 못했습니다.' });
    expect(screen.getByRole('alert')).toHaveTextContent('질문을 불러오지 못했습니다.');
    // 준비 단계는 그대로 보여야 한다.
    expect(screen.getByText('SwDS(설계서)')).toBeInTheDocument();
  });

  // ── 입력 변수가 없는 unit — 사유를 나누지 않으면 전부 결함으로 읽힌다 ──────
  //
  // 실측(2026-08-12): 948 TC 중 338 건이 입력 0개. 그런데 정본도 1,005 중 172 건이
  // 0 이다. 한 숫자로 합쳐 그리면 읽는 사람은 338 을 전부 결함으로 읽는다.

  const zeroInputStep = (causes) => ({
    id: 'suts_inputs', phase: 'material', state: 'degraded', label: '입력 변수가 없는 unit',
    measured: { value: 183, of: 750, reference_pct: 17.1, causes },
  });

  it('사유별로 나눠 그린다 — 건수만 내면 판단이 안 된다', () => {
    renderPanel(base([zeroInputStep({ no_params_no_globals: 79, param_string_unusable: 28 })]));
    expect(screen.getByText(/파라미터·전역 없음 79/)).toBeInTheDocument();
    expect(screen.getByText(/파라미터 문자열 손상 28/)).toBeInTheDocument();
  });

  it('정상 사유와 결함 사유를 같은 무게로 그리지 않는다', () => {
    renderPanel(base([zeroInputStep({ no_params_no_globals: 79, dropped_by_name_filter: 5 })]));
    const normal = screen.getByText(/파라미터·전역 없음 79/);
    const defect = screen.getByText(/이름 추출이 버림 5/);
    expect(defect).toHaveTextContent('⚠');
    expect(normal).not.toHaveTextContent('⚠');
    expect(defect.style.fontWeight).toBe('600');
    expect(normal.style.fontWeight).not.toBe('600');
  });

  it('정본 기준선을 함께 보인다 — 건수만으로는 많은지 알 수 없다', () => {
    renderPanel(base([zeroInputStep({ no_params_no_globals: 79 })]));
    expect(screen.getByText(/정본 17\.1%/)).toBeInTheDocument();
  });

  it('결정 필요 축은 결함도 정상도 아닌 제3의 톤으로 그린다', () => {
    // 스텁 반환값은 사람이 정해야 하는 값이다. 결함(⚠)으로 칠하면 고쳐야 할 버그로
    // 읽히고, 정상(muted)으로 칠하면 아무도 안 본다.
    renderPanel(base([zeroInputStep({ stub_return_candidate: 12, no_params_no_globals: 79 })]));
    const decide = screen.getByText(/스텁 반환값 지정 가능 12/);
    expect(decide).not.toHaveTextContent('⚠');
    expect(decide.style.fontWeight).toBe('600');
    expect(decide.style.color).not.toBe(screen.getByText(/파라미터·전역 없음 79/).style.color);
  });

  it('const 전역만 읽는 unit 은 결함으로 칠하지 않는다', () => {
    // 라벨이 없으면 폴백이 `defect: true` 로 칠한다 — **의도한 억제**가 조치항목이 된다.
    // const 전역은 시험이 설정할 수 있는 값이 아니고, 정본도 어느 열에도 안 적는다.
    renderPanel(base([zeroInputStep({ const_globals_only: 9, dropped_by_name_filter: 5 })]));
    const ok = screen.getByText(/const 전역만 읽음 9/);
    expect(ok).not.toHaveTextContent('⚠');
    expect(ok.style.fontWeight).not.toBe('600');
    expect(screen.getByText(/이름 추출이 버림 5/)).toHaveTextContent('⚠');
  });

  // ── STS 요구-함수 매핑의 사유 (2026-08-14) ────────────────────────────────
  //
  // 미매핑 요구를 한 숫자로 합치면 **누가 고칠 문제인지**가 안 보인다. 실측
  // (KJPDS02_PV) 20건 중 16 은 SwDS 가 담고 있는데 우리가 못 닿은 것(= 이쪽 결함),
  // 4 는 SwDS 어디에도 없는 것(= 설계가 안 이은 것, 생성기가 고칠 수 없다).

  const stsMappingStep = (causes) => ({
    id: 'sts_req_mapping', phase: 'material', state: 'degraded', label: '요구-함수 매핑',
    measured: { value: 48, of: 68, causes },
  });

  it('SwDS 에 요구 자체가 없는 축은 결함이 아니라 결정으로 그린다', () => {
    renderPanel(base([stsMappingStep({ unreached_in_sds: 16, absent_from_sds: 4 })]));
    const ours = screen.getByText(/SwDS 엔 있는데 못 닿음 16/);
    const theirs = screen.getByText(/SwDS 에 요구 자체가 없음 4/);
    expect(ours).toHaveTextContent('⚠');
    expect(theirs).not.toHaveTextContent('⚠');
    // 결정 축은 정상(muted)과도 달라야 한다 — muted 로 칠하면 아무도 안 본다.
    expect(theirs.style.fontWeight).toBe('600');
    expect(theirs.style.color).not.toBe(ours.style.color);
  });

  it('사유가 0 건인 축은 그리지 않는다 — 없는 결함을 조치항목으로 만들지 않는다', () => {
    renderPanel(base([zeroInputStep({ no_params_no_globals: 79, dropped_by_name_filter: 0 })]));
    expect(screen.queryByText(/이름 추출이 버림/)).toBeNull();
  });

  it('measured 의 partial 은 절단을 침묵시키지 않는다', () => {
    renderPanel(base([{
      id: 'comment_coverage', phase: 'material', state: 'degraded', label: '소스 주석',
      measured: { functions: 350, filled: 380, substantive: 103, scanned_files: 300, partial: true },
    }]));
    expect(screen.getByText(/일부만 봄\(상한 도달\)/)).toBeInTheDocument();
  });
});

/**
 * 조정할 수 없는 상한에 **입력칸을 그리지 않는지**.
 *
 * 원래 결함: 모든 `cap_*` 스텝에 입력칸과 [값 지정] 버튼이 붙었다. UDS 소스 파일 상한처럼
 * API 가 아예 받지 않는 값도 입력칸이 떠서, 숫자를 넣으면 localStorage 에 저장은 되지만
 * 요청에 실리지 않고 문서도 그대로였다 — 화면이 **없는 통제를 약속**한 것이다.
 * [값 지정] 버튼은 한술 더 떠 "해당 빌더 탭에서 조정합니다"라며 그런 탭이 없는 곳으로
 * 사용자를 보냈다.
 */
describe('DocGenPreflightPanel — 없는 통제를 그리지 않는다', () => {
  const fixed = (extra) => ({
    id: 'cap_max_source_files',
    phase: 'decision',
    state: 'ok',
    label: 'max_source_files',
    // 백엔드가 `effect — adjust_via` 를 합쳐 내리는 실제 형태 그대로.
    reason: '소스 파일 상한 — 환경변수 DEVOPS_UDS_MAX_FILES 로만 조정할 수 있습니다',
    measured: {
      generator_default: 1200,
      adjustable: false,
      adjust_via: '환경변수 DEVOPS_UDS_MAX_FILES 로만 조정할 수 있습니다',
    },
    ...extra,
  });

  it('양성 대조군 — 조정할 수 있는 상한은 입력칸이 있다', () => {
    // 이게 없으면 "CapInput 을 통째로 삭제" 뮤턴트가 아래 음성 단언을 전부 통과한다.
    renderPanel(base([fixed({
      id: 'cap_max_tc_per_req',
      label: 'max_tc_per_req',
      state: 'needed',
      reason: '요구당 시험 케이스 상한',
      measured: { api_default: 5, generator_default: 5, adjustable: true },
    })], 'needs_decision'));
    expect(screen.getByLabelText('max_tc_per_req 상한')).toBeInTheDocument();
  });

  it('조정할 수 없으면 입력칸이 없다', () => {
    renderPanel(base([fixed()]));
    expect(screen.queryByLabelText('max_source_files 상한')).toBeNull();
  });

  it('대신 어디서 바꾸는지 말한다 — 사유 없는 비활성은 고장으로 읽힌다', () => {
    renderPanel(base([fixed()]));
    expect(screen.getByText(/DEVOPS_UDS_MAX_FILES/)).toBeInTheDocument();
  });

  it('현재값을 "—" 로 그리지 않는다 — 이 패널에서 그건 "재지 못함" 전용 기호다', () => {
    renderPanel(base([fixed()]));
    expect(screen.getByText('현재 1200 (고정)')).toBeInTheDocument();
  });

  it('"값 지정" 버튼이 남지 않는다 — 누르면 없는 탭으로 보낸다', () => {
    renderPanel(base([fixed()]));
    expect(screen.queryByRole('button', { name: '값 지정' })).toBeNull();
  });

  it('사용자가 정한 값을 되읽어 보인다 — 없으면 반영됐는지 알 수 없다', () => {
    renderPanel(base([fixed({
      id: 'cap_max_flows',
      label: 'max_flows',
      reason: '통합 흐름 상한',
      measured: { api_default: 120, generator_default: 120, adjustable: true, user_value: 200 },
    })], 'needs_decision'));
    expect(screen.getByText(/현재 200 \(직접 지정\)/)).toBeInTheDocument();
  });
});

/**
 * 상한을 올리라고 말하면서 **얼마로** 올릴지 안 알려주면 사용자는 숫자를 추측한다.
 * 게이트는 이미 재고 있다(SITS 흐름 총수, STS 요구당 최대 함수 수) — 그 값을 원클릭으로.
 */
describe('DocGenPreflightPanel — 얼마로 올려야 하는지 말한다', () => {
  beforeEach(() => localStorage.clear());

  const flowCap = (measured) => ({
    id: 'cap_max_flows', phase: 'decision', state: 'needed', label: 'max_flows',
    reason: '통합 흐름 상한', measured,
  });
  const measured = (extra) => ({
    api_default: 120, generator_default: 120, adjustable: true, ...extra,
  });

  it('측정값이 있으면 전부 담는 값을 원클릭으로 넣어 준다', () => {
    renderPanel(base([flowCap(measured({ suggested: 145 }))], 'needs_decision'));
    fireEvent.click(screen.getByRole('button', { name: /전부 145/ }));
    expect(JSON.parse(localStorage.getItem(DOCGEN_CAPS_KEY)).max_flows).toBe(145);
  });

  it('넣은 값이 입력칸에도 보인다 — 저장만 되고 칸이 그대로면 "안 먹혔다" 로 읽힌다', () => {
    const { rerender } = render(
      <DocGenPreflightPanel data={base([flowCap(measured({ suggested: 145 }))], 'needs_decision')}
        loading={false} error="" />);
    fireEvent.click(screen.getByRole('button', { name: /전부 145/ }));
    rerender(<DocGenPreflightPanel data={base([flowCap(measured({ suggested: 145 }))], 'needs_decision')}
      loading={false} error="" />);
    expect(screen.getByLabelText('max_flows 상한')).toHaveValue(145);
  });

  it('이미 그 값이면 제안하지 않는다 — 없는 조치를 만들지 않는다', () => {
    localStorage.setItem(DOCGEN_CAPS_KEY, JSON.stringify({ max_flows: 145 }));
    renderPanel(base([flowCap(measured({ suggested: 145 }))], 'needs_decision'));
    expect(screen.queryByRole('button', { name: /전부 145/ })).toBeNull();
  });

  it('측정이 없으면 숫자를 지어내지 않는다', () => {
    renderPanel(base([flowCap(measured())], 'needs_decision'));
    expect(screen.queryByRole('button', { name: /전부/ })).toBeNull();
  });
});

/**
 * "전부 N" 버튼의 **N 이 어디서 왔는가**.
 *
 * 실측 축(흐름 145)과 카탈로그 축(전략 후보 최대 30)은 같은 필드로 오지만 주장 강도가
 * 다르다. 후자에까지 "측정값 기준" 이라 적으면 재지도 않은 수를 측정치로 파는 셈이다.
 */
describe('DocGenPreflightPanel — 제안값의 출처', () => {
  beforeEach(() => { localStorage.clear(); });

  const capStep = (measured) => ({
    id: 'cap_max_sequences', phase: 'decision', state: 'needed', label: 'max_sequences',
    measured,
  });

  it('카탈로그 기반 제안은 "측정값" 이라 말하지 않는다', () => {
    render(<DocGenPreflightPanel
      data={base([capStep({ api_default: 24, generator_default: 24, adjustable: true,
        suggested: 30, suggested_basis: 'catalog' })], 'needs_decision')}
      loading={false} error="" />);
    const btn = screen.getByRole('button', { name: /전부 30/ });
    expect(btn.getAttribute('title')).not.toMatch(/측정값/);
    expect(btn.getAttribute('title')).toMatch(/후보 최대/);
  });

  it('실측 기반 제안은 측정값이라고 밝힌다', () => {
    render(<DocGenPreflightPanel
      data={base([capStep({ api_default: 120, generator_default: 120, adjustable: true,
        suggested: 145, suggested_basis: 'measured' })], 'needs_decision')}
      loading={false} error="" />);
    expect(screen.getByRole('button', { name: /전부 145/ }).getAttribute('title'))
      .toMatch(/측정값 기준/);
  });
});

/**
 * 게이트 문장의 `**강조**` — 백엔드가 오래 써 온 표시인데(preflight 만 141곳) 화면이
 * 평문으로 뿌려 별표가 그대로 보였다. 강조하려던 바로 그 절이 오히려 읽기 나빠졌다.
 */
describe('DocGenPreflightPanel — 강조 표시', () => {
  const step = (reason) => ({
    id: 'cap_max_sequences', phase: 'decision', state: 'needed', label: 'max_sequences', reason,
  });

  it('별표를 화면에 남기지 않고 강조로 그린다', () => {
    renderPanel(base([step('이 소스에 **ASIL D 함수가 37개** 있습니다')], 'needs_decision'));
    expect(screen.getByText('ASIL D 함수가 37개').tagName).toBe('STRONG');
    // 별표가 본문에 남으면 강조가 아니라 잡음이다.
    expect(screen.queryByText(/\*\*/)).toBeNull();
  });

  it('짝이 안 맞는 별표는 평문 그대로 둔다 — 문장을 삼키지 않는다', () => {
    renderPanel(base([step('상한 **미완성 강조 문장')], 'needs_decision'));
    expect(screen.getByText(/미완성 강조 문장/)).toBeInTheDocument();
  });

  it('강조가 없는 사유는 그대로 나온다', () => {
    renderPanel(base([step('평범한 사유입니다')], 'needs_decision'));
    expect(screen.getByText(/평범한 사유입니다/)).toBeInTheDocument();
  });
});

/**
 * ASIL 등급 — **그 자리에서 정할 수 있어야** 한다.
 *
 * 게이트가 "결정 필요" 라고만 하고 설정 탭으로 보내면, 상태만 정직해지고 사용자는
 * 아무것도 할 수 없다(이 세션에서 UDS 상한이 정확히 그랬다: `unmeasured` 로 올렸는데
 * 재는 버튼이 없어 verdict 가 영구 고착).
 */
describe('DocGenPreflightPanel — ASIL 등급 결정', () => {
  beforeEach(() => { localStorage.clear(); });

  const asilStep = (value) => ({
    id: 'asil_level', phase: 'decision', state: value ? 'ok' : 'needed',
    label: '프로젝트 ASIL 등급', reason: '등급 사유', measured: { value: value || null },
  });

  it('결정 행에 고를 수단이 함께 있다 (설정 탭으로 보내지 않는다)', () => {
    renderPanel(base([asilStep(null)], 'needs_decision'));
    expect(screen.getByLabelText('프로젝트 ASIL 등급')).toBeInTheDocument();
  });

  it('고르면 공유 입력에 저장되고 재조회가 걸린다 — 다른 칸은 그대로 둔다', () => {
    // ⚠ 이 칸은 설정(공통 메타)과 **같은 저장소**다. 통째로 덮어쓰면 프로젝트 ID·
    //   템플릿 경로·검토자 같은 남의 값이 조용히 사라진다. 뮤테이션이 이 구멍을 잡아냈다.
    localStorage.setItem('devops_v2_shared_inputs', JSON.stringify({
      project_id: 'KJPDS02', tpl_sutr: 'U:/tpl/SwUTR.xlsm', reviewer: '검토자',
    }));
    const onReload = vi.fn();
    renderPanel(base([asilStep(null)], 'needs_decision'), { onReload });
    fireEvent.change(screen.getByLabelText('프로젝트 ASIL 등급'), { target: { value: 'ASIL D' } });
    const saved = JSON.parse(localStorage.getItem('devops_v2_shared_inputs'));
    expect(saved.asil_level).toBe('ASIL D');
    expect(saved).toEqual(expect.objectContaining({
      project_id: 'KJPDS02', tpl_sutr: 'U:/tpl/SwUTR.xlsm', reviewer: '검토자',
    }));
    expect(onReload).toHaveBeenCalled();
  });

  it('기본 선택은 **미지정**이다 — 등급을 지어내지 않는다', () => {
    renderPanel(base([asilStep(null)], 'needs_decision'));
    expect(screen.getByLabelText('프로젝트 ASIL 등급')).toHaveValue('');
    // QM 이 기본으로 잡혀 있으면 근거 없는 등급이 하류로 흘러간다.
    expect(screen.getByLabelText('프로젝트 ASIL 등급')).not.toHaveValue('QM');
  });

  it('이미 정한 값이 칸에 보인다 — 반영됐는지 알 수 있어야 한다', () => {
    localStorage.setItem('devops_v2_shared_inputs', JSON.stringify({ asil_level: 'ASIL C' }));
    renderPanel(base([asilStep('ASIL C')], 'degraded'));
    expect(screen.getByLabelText('프로젝트 ASIL 등급')).toHaveValue('ASIL C');
  });

  it('다른 결정 행에는 ASIL 선택기가 붙지 않는다', () => {
    renderPanel(base([{ id: 'cap_max_flows', phase: 'decision', state: 'needed',
      label: 'max_flows', measured: { api_default: 120, generator_default: 120, adjustable: true } }],
    'needs_decision'));
    expect(screen.queryByLabelText('프로젝트 ASIL 등급')).toBeNull();
  });
});


/**
 * 열거 선택(범위·템플릿 출처) — **옵션의 출처는 서버**다.
 *
 * 예전엔 `ScopeSelect` 가 `<option>` 두 개를 손으로 들고 있었고, `s.id === 'scope'` 라는
 * id 목록도 화면에 손으로 적혀 있었다. 그래서 새 선택지(`template_source`)를 백엔드에
 * 추가했을 때 화면에는 **아무것도 그려지지 않았다** — 오류도 없이 통제만 사라진다.
 */
describe('DocGenPreflightPanel — 선택지', () => {
  const choiceStep = (over = {}) => ({
    id: 'template_source', phase: 'decision', state: 'ok', label: '템플릿 출처',
    value: 'D:/ref/SUDS.docx',
    measured: {
      choice: 'template_source',
      options: [
        { value: '', label: '정본 우선 (기본)' },
        { value: 'standard', label: '표준 템플릿 우선' },
      ],
      picked: '',
    },
    reason: 'UDS 정본을 템플릿으로 사용합니다',
    ...over,
  });

  beforeEach(() => localStorage.clear());

  it('서버가 준 옵션을 그대로 그린다', () => {
    renderPanel(base([choiceStep()]));
    const sel = screen.getByLabelText('템플릿 출처');
    expect([...sel.options].map(o => o.value)).toEqual(['', 'standard']);
  });

  it('고르면 저장되고 재조회가 걸린다', () => {
    const onReload = vi.fn();
    renderPanel(base([choiceStep()]), { onReload, scope: 'job-a' });
    fireEvent.change(screen.getByLabelText('템플릿 출처'), { target: { value: 'standard' } });
    expect(JSON.parse(localStorage.getItem(`${DOCGEN_CAPS_KEY}::job-a`)).template_source)
      .toBe('standard');
    // 재조회가 없으면 방금 고른 값이 판정에 반영되지 않은 화면이 남는다.
    expect(onReload).toHaveBeenCalled();
  });

  it('저장은 **그 프로젝트 칸**에 들어간다', () => {
    renderPanel(base([choiceStep()]), { scope: 'job-b' });
    fireEvent.change(screen.getByLabelText('템플릿 출처'), { target: { value: 'standard' } });
    expect(localStorage.getItem(`${DOCGEN_CAPS_KEY}::job-a`)).toBeNull();
    expect(localStorage.getItem(`${DOCGEN_CAPS_KEY}::job-b`)).toBeTruthy();
  });

  it('서버가 옵션을 안 주면 선택기를 **그리지 않는다**', () => {
    // 여기서 목록을 지어내면 서버가 받지 않는 값을 제시하게 된다 = 다시 거짓 통제.
    renderPanel(base([choiceStep({ measured: { choice: 'template_source', options: null } })]));
    expect(screen.queryByLabelText('템플릿 출처')).toBeNull();
  });

  it('`choice` 가 없는 행에는 선택기가 안 붙는다', () => {
    renderPanel(base([choiceStep({ measured: { options: [{ value: '', label: 'x' }] } })]));
    expect(screen.queryByLabelText('템플릿 출처')).toBeNull();
  });

  it('상한 입력도 그 프로젝트 칸에 저장한다', () => {
    renderPanel(base([{
      id: 'cap_max_flows', phase: 'decision', state: 'needed', label: 'max_flows',
      measured: { adjustable: true, api_default: 120 }, reason: '흐름 상한',
    }]), { scope: 'job-c' });
    fireEvent.change(screen.getByLabelText('max_flows 상한'), { target: { value: '200' } });
    expect(JSON.parse(localStorage.getItem(`${DOCGEN_CAPS_KEY}::job-c`)).max_flows).toBe(200);
  });

  it('저장된 값이 선택기에 반영된다 — 화면과 저장값이 어긋나면 자기모순이다', () => {
    localStorage.setItem(`${DOCGEN_CAPS_KEY}::job-d`,
      JSON.stringify({ template_source: 'standard' }));
    renderPanel(base([choiceStep()]), { scope: 'job-d' });
    // 저장은 'standard' 인데 화면이 기본값을 보이면, 바로 옆 사유 문구("정본을 씁니다")와
    // 선택기가 서로 다른 말을 한다 — `scope` 행이 같은 이유로 `picked` 를 읽는다.
    expect(screen.getByLabelText('템플릿 출처').value).toBe('standard');
  });
});
