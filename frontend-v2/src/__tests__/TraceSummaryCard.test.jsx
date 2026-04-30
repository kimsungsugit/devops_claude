/**
 * TraceSummaryCard의 Quality Gate / Coverage Donut 단위 테스트
 *
 * 핵심 계약:
 *  - classifyGate(pct) ISO 26262 임계값에 맞춰 'pass'/'warn'/'fail' 반환
 *  - QualityGateBadge 해당 레이블 출력
 *  - CoverageDonut total=0이면 렌더 안 함 (nothing to show)
 */
import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';

// api.js 의존성 (ResultPanel 기본 import 체인 때문에 필요)
import { vi } from 'vitest';
vi.mock('../api.js', () => ({
  buildTone: () => 'neutral',
  post: vi.fn(),
}));

const { classifyGate, QualityGateBadge, CoverageDonut } = await import(
  '../components/ResultPanel.jsx'
);

describe('classifyGate', () => {
  it('임계값 경계를 지킨다 (80 PASS, 50 WARN)', () => {
    expect(classifyGate(100)).toBe('pass');
    expect(classifyGate(80)).toBe('pass');
    expect(classifyGate(79.9)).toBe('warn');
    expect(classifyGate(50)).toBe('warn');
    expect(classifyGate(49.9)).toBe('fail');
    expect(classifyGate(0)).toBe('fail');
  });
});

describe('QualityGateBadge', () => {
  it('PASS 라벨 표시', () => {
    const { getByText } = render(<QualityGateBadge pct={85} />);
    expect(getByText(/PASS/)).toBeInTheDocument();
  });

  it('WARN 라벨 표시', () => {
    const { getByText } = render(<QualityGateBadge pct={65} />);
    expect(getByText(/WARN/)).toBeInTheDocument();
  });

  it('FAIL 라벨 표시', () => {
    const { getByText } = render(<QualityGateBadge pct={30} />);
    expect(getByText(/FAIL/)).toBeInTheDocument();
  });
});

describe('CoverageDonut', () => {
  it('total=0이면 아무것도 렌더하지 않는다', () => {
    const { container } = render(
      <CoverageDonut covered={0} partial={0} uncovered={0} pct={0} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('값이 있으면 SVG와 중앙 % 텍스트를 렌더한다', () => {
    const { container, getByText } = render(
      <CoverageDonut covered={40} partial={10} uncovered={50} pct={40} />,
    );
    expect(container.querySelector('svg')).toBeTruthy();
    expect(getByText('40%')).toBeInTheDocument();
  });
});
