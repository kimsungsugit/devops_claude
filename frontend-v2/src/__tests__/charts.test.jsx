/** charts.jsx 프리미티브 — 렌더 + ISO 정직성(null→'—') */
import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { HorizontalBar, DonutChart, RingGauge, MiniTrend, TrendLine } from '../components/charts.jsx';

describe('charts', () => {
  it('HorizontalBar: 라벨 + toLocaleString 값', () => {
    const { getByText } = render(<HorizontalBar label="LOC" value={64805} max={100000} color="red" />);
    expect(getByText('LOC')).toBeInTheDocument();
    expect(getByText('64,805')).toBeInTheDocument();
  });

  it('RingGauge: % 표시, null이면 "—"(0% 위장 금지)', () => {
    const { getByText, rerender } = render(<RingGauge value={99.45} color="green" label="UT" />);
    expect(getByText('99%')).toBeInTheDocument();
    rerender(<RingGauge value={null} color="green" label="UT" />);
    expect(getByText('—')).toBeInTheDocument();
  });

  it('MiniTrend: 데이터당 막대, 빈 배열이면 null', () => {
    const { container } = render(<MiniTrend data={[{ label: '#1', v: 5 }, { label: '#2', v: 8 }]} valueKey="v" />);
    expect(container.querySelectorAll('rect').length).toBe(2);
    const { container: c2 } = render(<MiniTrend data={[]} valueKey="v" />);
    expect(c2.querySelector('svg')).toBeNull();
  });

  it('DonutChart: 중앙 라벨/서브 파라미터화', () => {
    const { getByText } = render(<DonutChart segments={[{ value: 3, color: 'a' }]} centerLabel="X" centerSub="sub" />);
    expect(getByText('X')).toBeInTheDocument();
    expect(getByText('sub')).toBeInTheDocument();
  });

  it('TrendLine: 연속 값은 polyline 1개', () => {
    const { container } = render(<TrendLine points={[{ label: 'a', value: 1 }, { label: 'b', value: 3 }, { label: 'c', value: 2 }]} />);
    expect(container.querySelectorAll('polyline').length).toBe(1);
  });

  it('TrendLine: null은 선을 분절한다(0으로 잇지 않음 — ISO 정직성)', () => {
    const { container } = render(<TrendLine points={[
      { label: 'a', value: 5 }, { label: 'b', value: 4 },
      { label: 'c', value: null },
      { label: 'd', value: 2 }, { label: 'e', value: 1 },
    ]} />);
    expect(container.querySelectorAll('polyline').length).toBe(2); // 2세그먼트
  });

  it('TrendLine: 전부 null이면 렌더하지 않음(빈 0 라인 위장 금지)', () => {
    const { container } = render(<TrendLine points={[{ label: 'a', value: null }]} />);
    expect(container.querySelector('svg')).toBeNull();
  });

  it('TrendLine: 고립 관측 1개는 점으로 표시', () => {
    const { container } = render(<TrendLine points={[
      { label: 'a', value: null }, { label: 'b', value: 7 }, { label: 'c', value: null },
    ]} />);
    expect(container.querySelectorAll('polyline').length).toBe(0);
    expect(container.querySelectorAll('circle').length).toBe(1);
  });
});
