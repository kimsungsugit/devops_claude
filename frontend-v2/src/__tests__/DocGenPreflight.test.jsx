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

  it('measured 의 partial 은 절단을 침묵시키지 않는다', () => {
    renderPanel(base([{
      id: 'comment_coverage', phase: 'material', state: 'degraded', label: '소스 주석',
      measured: { functions: 350, filled: 380, substantive: 103, scanned_files: 300, partial: true },
    }]));
    expect(screen.getByText(/일부만 봄\(상한 도달\)/)).toBeInTheDocument();
  });
});
