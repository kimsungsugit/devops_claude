/**
 * ResultPanel 컴포넌트 단위 테스트
 *
 * 요구사항 추적: SRS-UI-RESULTPANEL
 * - 분석 결과(KPI, 빌드 정보, 아티팩트 수) 표시
 * - impactData 없을 때 안내 메시지 표시
 * - impactData 유무에 따른 변경 파일 카드 표시
 */
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';

// api.js 의존성 mock — post는 기본 null(트레이스/SCM 요약 요청 무해 처리), 테스트에서 override.
vi.mock('../api.js', () => ({
  buildTone: (result) => {
    if (!result) return 'neutral';
    if (result === 'SUCCESS') return 'success';
    if (result === 'FAILURE') return 'danger';
    return 'neutral';
  },
  post: vi.fn(() => Promise.resolve(null)),
}));

const { default: ResultPanel } = await import('../components/ResultPanel.jsx');
const { post } = await import('../api.js');

afterEach(() => {
  post.mockReset();
  post.mockImplementation(() => Promise.resolve(null));
});

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

  // ── VectorCAST 결과값 카드 (빌드 & 아티팩트 요약) ─────────────────────
  const withVcast = (vc, extra = {}) => {
    const base = makeResult();
    return makeResult({
      reportData: { ...base.reportData, tester: { vectorcast: vc } },
      ...extra,
    });
  };

  it('빌드 산출물 VectorCAST 합부(통과/실패)를 표시한다', () => {
    // jobUrl 없음 → SCM fetch 미발생 → 빌드 산출물 summary 사용.
    const result = withVcast({
      test_rows_count: 100, ut_reports: [1, 2, 3], it_reports: [1],
      summary: { total: 100, passed: 98, failed: 2, skipped: 0, unknown: 0, pass_rate: 0.98 },
    });
    render(<ResultPanel result={result} />);
    expect(screen.getByText(/통과 98/)).toBeInTheDocument();
    expect(screen.getByText(/실패 2/)).toBeInTheDocument();
    expect(screen.getByText('(빌드)')).toBeInTheDocument();
  });

  it('빌드 산출물이 전부 미분류면 통과율 대신 미분류 건수를 정직하게 표시한다', () => {
    // HDPDM01 실측: 판정 컬럼 부재로 전부 unknown → "통과율 0%" 위장 금지, "미분류 N" 표시.
    const result = withVcast({
      test_rows_count: 2149, ut_reports: [1, 2, 3], it_reports: [1, 2, 3],
      summary: { total: 2149, passed: 0, failed: 0, skipped: 0, unknown: 2149, pass_rate: 0.0 },
    });
    render(<ResultPanel result={result} />);
    expect(screen.getByText(/미분류 2,149/)).toBeInTheDocument();
    expect(screen.queryByText(/통과 \d/)).not.toBeInTheDocument();
  });

  it('SCM 로드 이력이 있으면 SCM 결과값(출처·통과/실패)을 우선 표시한다', async () => {
    // 빌드 경로가 비어도(KJPDS02_PV) SCM 이력의 진짜 합부를 폴백 표시.
    post.mockImplementation((url) =>
      url === '/api/jenkins/scm-vcast-summary'
        ? Promise.resolve({
            available: true, total: 7502, ut_total: 6886, it_total: 616,
            passed: 7480, failed: 22, skipped: 0, unknown: 0, pass_rate: 0.9971,
            line_rate: 0.7073, branch_rate: null,
          })
        : Promise.resolve(null));
    const result = withVcast(
      { test_rows_count: 0, ut_reports: [], it_reports: [],
        summary: { total: 0, passed: 0, failed: 0, skipped: 0, unknown: 0, pass_rate: 0 } },
      { jobUrl: 'http://192.168.110.40:7000/job/KJPDS02_PV/' },
    );
    render(<ResultPanel result={result} />);
    expect(await screen.findByText('(SCM 이력)')).toBeInTheDocument();
    expect(screen.getByText(/통과 7,480/)).toBeInTheDocument();
    expect(screen.getByText(/실패 22/)).toBeInTheDocument();
    // W1 회귀 가드: pass_rate 0.9971은 실패 22건이 있으므로 반올림 "100%"가 아닌 내림 "99%"여야 한다.
    expect(screen.getByText(/· 99%/)).toBeInTheDocument();
    expect(screen.queryByText(/100%/)).not.toBeInTheDocument();
  });

  it('통과·실패가 있어도 미분류가 남아 있으면 함께 표시한다(은폐 방지)', () => {
    // W2: passed>0·failed=0·unknown>0 혼합 — 통과만 보이고 미분류가 사라지면 갭 오해.
    const result = withVcast({
      test_rows_count: 2100, ut_reports: [1], it_reports: [1],
      summary: { total: 2100, passed: 100, failed: 0, skipped: 0, unknown: 2000, pass_rate: 100 / 2100 },
    });
    render(<ResultPanel result={result} />);
    expect(screen.getByText(/통과 100/)).toBeInTheDocument();
    expect(screen.getByText(/미분류 2,000/)).toBeInTheDocument();
  });

});
