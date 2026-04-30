/**
 * UncoveredTopList 단위 테스트
 *
 * 매트릭스 행에서 uncovered만 골라내고, Top N까지만 보여주며, 클릭 시
 * onPick 콜백이 올바른 reqId로 호출되는지 검증한다.
 *
 * 경계 조건: uncovered가 0개면 컴포넌트 자체를 렌더하지 않는다 (null 반환).
 */
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { UncoveredTopList, deriveStatus } from '../components/sections/SrsSdsSection.jsx';

const mkRow = (id, opts = {}) => ({
  requirement_id: id,
  sds_components: opts.design ? ['SDS-X'] : [],
  source_ids: opts.source ? ['fn_x'] : [],
  tests: opts.tests ? [{ source: 'STS' }] : [],
});

describe('UncoveredTopList', () => {
  it('uncovered 행이 없으면 렌더하지 않는다', () => {
    const rows = [
      mkRow('R1', { design: true, tests: true }),  // covered
      mkRow('R2', { design: true }),                // partial
    ];
    const { container } = render(<UncoveredTopList rows={rows} onPick={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('uncovered 행만 골라서 표시한다', () => {
    const rows = [
      mkRow('R_COV', { design: true, tests: true }),
      mkRow('R_PART', { design: true }),
      mkRow('R_UNC1'),
      mkRow('R_UNC2'),
    ];
    render(<UncoveredTopList rows={rows} onPick={() => {}} />);
    expect(screen.getByText('R_UNC1')).toBeInTheDocument();
    expect(screen.getByText('R_UNC2')).toBeInTheDocument();
    expect(screen.queryByText('R_COV')).toBeNull();
    expect(screen.queryByText('R_PART')).toBeNull();
  });

  it('10개 초과 시 "+ N개 더" 문구를 표시한다', () => {
    const rows = Array.from({ length: 13 }, (_, i) => mkRow(`R${i + 1}`));
    render(<UncoveredTopList rows={rows} onPick={() => {}} />);
    // 10건 표시
    expect(screen.getByText('R1')).toBeInTheDocument();
    expect(screen.getByText('R10')).toBeInTheDocument();
    expect(screen.queryByText('R11')).toBeNull();
    expect(screen.getByText(/\+\s*3개 더/)).toBeInTheDocument();
    expect(screen.getByText(/총 13건/)).toBeInTheDocument();
  });

  it('항목 클릭 시 onPick이 reqId로 호출된다', () => {
    const onPick = vi.fn();
    const rows = [mkRow('REQ-42')];
    render(<UncoveredTopList rows={rows} onPick={onPick} />);
    fireEvent.click(screen.getByRole('button', { name: /REQ-42/ }));
    expect(onPick).toHaveBeenCalledWith('REQ-42');
  });

  /* D3 회귀 방지: backend가 numeric id (예: r.id = 42)를 반환할 때
   * _rowReqId가 String 변환을 거쳐야 matrix table reqId(L1006)와 타입 일치.
   * 통일 안 되면 expandedReqId('42') === reqId(42)가 false → drill-down dead click.
   * ASIL D 추적성에 직접 영향. */
  it('numeric id row를 String으로 변환하여 표시·전달한다', () => {
    const onPick = vi.fn();
    const rows = [{
      id: 42,
      sds_components: [],
      source_ids: [],
      tests: [],
    }];
    render(<UncoveredTopList rows={rows} onPick={onPick} />);
    expect(screen.getByText('42')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /42/ }));
    expect(onPick).toHaveBeenCalledWith('42');
    expect(typeof onPick.mock.calls[0][0]).toBe('string');
  });

  it('빈 requirement_id이지만 유효한 id가 있을 때 표시 가능 여부', () => {
    const rows = [{
      requirement_id: '',
      id: 'REQ-77',
      sds_components: [],
      source_ids: [],
      tests: [],
    }];
    render(<UncoveredTopList rows={rows} onPick={() => {}} />);
    /* 현재 _rowReqId 구현은 nullish coalescing(`??`)이라 빈 string은 falsy이지만
     * nullish 아님 → 빈 requirement_id가 우선되어 anonymous 처리됨.
     * 이 동작이 의도라면 "anonymous" 카운트로만 보여야 함. */
    expect(screen.queryByText('REQ-77')).toBeNull();
  });

  it('누락 사유를 배지에 표시한다', () => {
    const rows = [
      mkRow('R_NONE'),                     // 설계·테스트 없음
      mkRow('R_NO_DESIGN', { tests: true }), // deriveStatus=partial → 제외
      mkRow('R_NO_TEST', { design: true }),  // deriveStatus=partial → 제외
    ];
    render(<UncoveredTopList rows={rows} onPick={() => {}} />);
    // 둘 다 없는 경우만 uncovered이므로 해당 배지만 나타남
    expect(screen.getByText('설계·테스트 없음')).toBeInTheDocument();
  });
});

/* ── deriveStatus / 백엔드 _cache_trace_summary 동치성 ─────────────────
 * 백엔드(jenkins.py _cache_trace_summary)와 프론트는 동일한 설계·테스트
 * 필드 집합을 봐야 한다. 여기서 비기본 필드(functions/mapping/sds/…,
 * sts_tests/…) 통해 판정되는 row를 테스트하여 불일치가 발생하면 CI에서
 * 바로 잡히도록 한다. */
describe('deriveStatus (backend 동치성)', () => {
  it('functions만 있으면 design으로 인식 (partial)', () => {
    expect(deriveStatus({ functions: ['fn_a'] })).toBe('partial');
  });

  it('mapping 객체만 있으면 design으로 인식 (partial)', () => {
    expect(deriveStatus({ mapping: { a: 1 } })).toBe('partial');
  });

  it('sts_tests만 있으면 test로 인식 (partial)', () => {
    expect(deriveStatus({ sts_tests: [{ source: 'STS' }] })).toBe('partial');
  });

  it('functions + suts_tests 조합은 covered', () => {
    expect(deriveStatus({
      functions: ['fn_a'],
      suts_tests: [{ source: 'SUTS' }],
    })).toBe('covered');
  });

  it('빈 배열은 "없음"으로 취급 (uncovered)', () => {
    expect(deriveStatus({
      sds_components: [],
      source_ids: [],
      tests: [],
      functions: [],
    })).toBe('uncovered');
  });

  it('아무 필드도 없으면 uncovered', () => {
    expect(deriveStatus({ requirement_id: 'R1' })).toBe('uncovered');
  });
});
