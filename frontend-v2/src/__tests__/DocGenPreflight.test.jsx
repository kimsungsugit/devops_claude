import { describe, it, expect, vi } from 'vitest';
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
    expect(screen.getByText('이대로 진행')).toBeInTheDocument();
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
