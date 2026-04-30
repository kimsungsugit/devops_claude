/**
 * ResultPanel 컴포넌트 단위 테스트
 *
 * 요구사항 추적: SRS-UI-RESULTPANEL
 * - 분석 결과(KPI, 빌드 정보, 아티팩트 수) 표시
 * - impactData 없을 때 안내 메시지 표시
 * - impactData 유무에 따른 변경 파일 카드 표시
 */
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

// api.js 의존성 mock
vi.mock('../api.js', () => ({
  buildTone: (result) => {
    if (!result) return 'neutral';
    if (result === 'SUCCESS') return 'success';
    if (result === 'FAILURE') return 'danger';
    return 'neutral';
  },
}));

const { default: ResultPanel } = await import('../components/ResultPanel.jsx');

/* ── 테스트 픽스처 ── */
const makeResult = (overrides = {}) => ({
  artifacts: [],
  reportData: {
    build_number: 10,
    result: 'SUCCESS',
    kpis: {
      build: { build_number: 10, result: 'SUCCESS' },
      coverage: {},
      tests: { ok: true },
      scan: {},
      files: {},
      prqa: {},
    },
  },
  impactData: null,
  scmList: [],
  ...overrides,
});

describe('ResultPanel', () => {
  // ── 기본 렌더링 ───────────────────────────────────────────────────

  it('빌드 결과 KPI 카드를 렌더링한다', () => {
    // Arrange
    const result = makeResult();

    // Act
    render(<ResultPanel result={result}  />);

    // Assert
    expect(screen.getByText('빌드 결과')).toBeInTheDocument();
  });

  it('아티팩트 수를 표시한다', () => {
    // Arrange
    const result = makeResult({
      artifacts: [
        { type: 'html', name: 'report.html', path: '/cache/report.html' },
        { type: 'xlsx', name: 'data.xlsx', path: '/cache/data.xlsx' },
      ],
    });

    // Act
    render(<ResultPanel result={result}  />);

    // Assert
    expect(screen.getByText('아티팩트')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('테스트 통과 시 PASS 표시한다', () => {
    // Arrange
    const result = makeResult();

    // Act
    render(<ResultPanel result={result}  />);

    // Assert
    expect(screen.getByText('PASS')).toBeInTheDocument();
  });

  it('테스트 실패 시 FAIL 표시한다', () => {
    // Arrange
    const result = makeResult({
      reportData: {
        ...makeResult().reportData,
        kpis: {
          ...makeResult().reportData.kpis,
          tests: { ok: false },
        },
      },
    });

    // Act
    render(<ResultPanel result={result}  />);

    // Assert
    expect(screen.getByText('FAIL')).toBeInTheDocument();
  });

  it('Line Coverage가 있을 때 Coverage 카드를 표시한다', () => {
    // Arrange
    const result = makeResult({
      reportData: {
        ...makeResult().reportData,
        kpis: {
          ...makeResult().reportData.kpis,
          coverage: { line_rate: 0.85, ok: true },
        },
      },
    });

    // Act
    render(<ResultPanel result={result}  />);

    // Assert
    expect(screen.getByText('Line Cov')).toBeInTheDocument();
    expect(screen.getByText('85%')).toBeInTheDocument();
  });

  // ── impactData 없을 때 ────────────────────────────────────────────

  it('impactData가 null이면 SCM 미등록 안내를 표시한다', () => {
    // Arrange
    const result = makeResult({ impactData: null, scmList: [] });

    // Act
    render(<ResultPanel result={result}  />);

    // Assert
    expect(screen.getByText(/SCM이 등록되어 있지 않거나/)).toBeInTheDocument();
  });

  it('impactData 없으면 변경 파일 카드를 표시하지 않는다', () => {
    // Arrange
    const result = makeResult({ impactData: null, scmList: [] });

    // Act
    render(<ResultPanel result={result}  />);

    // Assert
    expect(screen.queryByText('변경 파일')).not.toBeInTheDocument();
  });

});
