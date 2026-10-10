import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AttributionDetail } from '../components/sections/DocGenStatusBoard.jsx';

/**
 * 원인 귀속 표시 — **두 시점을 섞지 않는지**가 이 파일의 본체다.
 *
 * 기여 건수는 생성 당시, 가용성은 지금이다. 섞으면 "이미 고쳤는데 왜 아직 비어 있나"
 * 라는 오독이 생기고, 반대로 "지금 없음" 을 생성 당시로 읽으면 없는 원인을 지목한다.
 */

const field = (over = {}) => ({
  field: 'asil', label: 'ASIL 등급',
  grounded_total: 0, ungrounded_total: 435,
  rows: [
    { source: 'comment', input: 'source_comment', input_label: '소스 주석',
      count: 0, contributed: false, grounded: true, have_now: false },
    { source: 'sds', input: 'swds', input_label: 'SwDS(설계서)',
      count: 0, contributed: false, grounded: true, have_now: true },
    { source: 'srs', input: 'swrs', input_label: 'SwRS(요구사항)',
      count: 0, contributed: false, grounded: true, have_now: null },
    { source: 'default', input: null, input_label: '',
      count: 435, contributed: true, grounded: false, have_now: null },
  ],
  ...over,
});

const data = (over = {}) => ({
  ok: true, available: true, total_functions: 435, grade: 'D',
  fields: [field()],
  timing_note: '출처 분포는 **생성 당시** 값이고 입력 가용성은 **지금** 입니다',
  ...over,
});

describe('AttributionDetail', () => {
  it('근거와 자리채움을 나눠 보인다 — 합치면 근거 없는 문서가 완성본으로 보인다', () => {
    render(<AttributionDetail data={data()} error="" />);
    expect(screen.getByText(/근거 0 · 자리채움 435/)).toBeInTheDocument();
  });

  it('근거 없는 출처(default 등)는 사슬 목록에 섞지 않는다', () => {
    render(<AttributionDetail data={data()} error="" />);
    expect(screen.getByText('comment')).toBeInTheDocument();
    // `default` 는 입력이 필요 없는 자리 채움이라 "무엇을 준비하라" 목록이 아니다.
    expect(screen.queryByText('default')).toBeNull();
  });

  it('지금은 연결됐지만 생성 당시엔 없던 출처를 구분해 말한다', () => {
    render(<AttributionDetail data={data()} error="" />);
    expect(screen.getByText(/지금은 연결됨\(재생성하면 반영\)/)).toBeInTheDocument();
  });

  it('지금도 없는 출처와 확인하지 않은 출처를 구분한다', () => {
    render(<AttributionDetail data={data()} error="" />);
    expect(screen.getByText(/지금도 없음/)).toBeInTheDocument();
    expect(screen.getByText(/현재 상태 확인 안 함/)).toBeInTheDocument();
  });

  it('시점이 다르다는 사실을 화면이 밝힌다', () => {
    render(<AttributionDetail data={data()} error="" />);
    expect(screen.getByText(/생성 당시.*지금/)).toBeInTheDocument();
  });

  it('사이드카가 없으면 사유를 말한다 — 빈 칸은 "원인 없음" 으로 읽힌다', () => {
    render(<AttributionDetail data={{ ok: true, available: false, reason: '사이드카 없음' }} error="" />);
    expect(screen.getByText(/분석 불가 — 사이드카 없음/)).toBeInTheDocument();
  });

  it('조회 실패는 alert 으로 드러낸다', () => {
    render(<AttributionDetail data={null} error="원인 분석 실패" />);
    expect(screen.getByRole('alert')).toHaveTextContent('원인 분석 실패');
  });

  it('데이터가 없으면 아무것도 그리지 않는다(빈 섹션 방지)', () => {
    const { container } = render(<AttributionDetail data={null} error="" />);
    expect(container.firstChild).toBeNull();
  });

  it('기여한 출처는 건수를 보인다', () => {
    const d = data({
      fields: [field({
        grounded_total: 40,
        rows: [{ source: 'sds', input: 'swds', input_label: 'SwDS(설계서)',
                 count: 40, contributed: true, grounded: true, have_now: true }],
      })],
    });
    render(<AttributionDetail data={d} error="" />);
    expect(screen.getByText('40건')).toBeInTheDocument();
  });
});
