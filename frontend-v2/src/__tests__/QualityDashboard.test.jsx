/**
 * QualityDashboard 뷰 단위 테스트
 *
 * 요구사항 추적: SRS-VIEW-QUALITYDASHBOARD
 * - 제목 "Quality Dashboard" 렌더링
 * - 문서 타입 필터 select 렌더링 (전체/STS/SUTS/UDS)
 * - KPI 카드 렌더링 (총 실행수, 평균 점수, 게이트 통과율)
 * - 실행 기록 없을 때 빈 상태 표시
 * - 실행 기록 있을 때 테이블 렌더링
 *
 * 외부 의존성:
 * - useToast: App.jsx mock
 * - api.js (api, post): mock
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Context mock ──────────────────────────────────────────────────────
const mockToast = vi.fn();

vi.mock('../App.jsx', () => ({
  useToast: () => mockToast,
}));

// ── api.js mock ───────────────────────────────────────────────────────
const mockApi = vi.fn();
const mockPost = vi.fn();

vi.mock('../api.js', () => ({
  api: (...args) => mockApi(...args),
  post: (...args) => mockPost(...args),
}));

const { default: QualityDashboard } = await import('../views/QualityDashboard.jsx');

/* ── 픽스처 ──
 * 백엔드 /api/quality/runs 실제 응답 shape를 따른다: 점수/게이트는
 * run.summary.overall_score / run.summary.gate_pass (중첩). score/pass 인자로
 * summary를 구성하며, 나머지 overrides는 top-level 로 펼친다. */
const makeRun = ({ id = 1, doc_type = 'uds', score = 85.0, pass = true, ...rest } = {}) => ({
  id,
  doc_type,
  created_at: '2026-01-01T00:00:00Z',
  summary: { overall_score: score, gate_pass: pass },
  ...rest,
});

describe('QualityDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // 기본적으로 빈 결과 반환
    mockApi.mockResolvedValue({ items: [], runs: [] });
  });

  // ── 기본 렌더링 ───────────────────────────────────────────────────

  it('"Quality Dashboard" 제목을 렌더링한다', async () => {
    // Arrange & Act
    render(<QualityDashboard />);

    // Assert
    expect(screen.getByText('Quality Dashboard')).toBeInTheDocument();
  });

  it('문서 타입 필터 select를 렌더링한다', async () => {
    // Arrange & Act
    render(<QualityDashboard />);

    // Assert
    const select = screen.getByRole('combobox');
    expect(select).toBeInTheDocument();
  });

  it('필터 옵션에 "전체", "STS", "SUTS", "UDS"를 포함한다', () => {
    // Arrange & Act
    render(<QualityDashboard />);

    // Assert
    const select = screen.getByRole('combobox');
    const options = Array.from(select.querySelectorAll('option')).map(o => o.textContent);
    expect(options).toContain('전체');
    expect(options).toContain('STS');
    expect(options).toContain('SUTS');
    expect(options).toContain('UDS');
  });

  it('KPI 카드 "총 실행수"를 렌더링한다', () => {
    // Arrange & Act
    render(<QualityDashboard />);

    // Assert
    expect(screen.getByText('총 실행수')).toBeInTheDocument();
  });

  it('KPI 카드 "평균 점수"를 렌더링한다', () => {
    // Arrange & Act
    render(<QualityDashboard />);

    // Assert
    expect(screen.getByText('평균 점수')).toBeInTheDocument();
  });

  it('KPI 카드 "게이트 통과율"을 렌더링한다', () => {
    // Arrange & Act
    render(<QualityDashboard />);

    // Assert
    expect(screen.getByText('게이트 통과율')).toBeInTheDocument();
  });

  // ── 빈 상태 ──────────────────────────────────────────────────────

  it('실행 기록이 없을 때 "실행 기록이 없습니다" 메시지를 표시한다', async () => {
    // Arrange
    mockApi.mockResolvedValue([]);

    // Act
    render(<QualityDashboard />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText('실행 기록이 없습니다')).toBeInTheDocument();
    });
  });

  // ── 실행 기록 있을 때 ─────────────────────────────────────────────

  it('실행 기록이 있을 때 테이블 헤더를 렌더링한다', async () => {
    // Arrange
    mockApi.mockResolvedValue({ runs: [makeRun()] });

    // Act
    render(<QualityDashboard />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText('점수')).toBeInTheDocument();
      expect(screen.getByText('게이트')).toBeInTheDocument();
    });
  });

  it('실행 기록이 있을 때 PASS 배지를 렌더링한다', async () => {
    // Arrange
    mockApi.mockResolvedValue({ runs: [makeRun({ pass: true })] });

    // Act
    render(<QualityDashboard />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText('PASS')).toBeInTheDocument();
    });
  });

  it('실행 기록이 있을 때 FAIL 배지를 렌더링한다', async () => {
    // Arrange
    mockApi.mockResolvedValue({ runs: [makeRun({ pass: false, score: 50.0 })] });

    // Act
    render(<QualityDashboard />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText('FAIL')).toBeInTheDocument();
    });
  });

  // ── 문서 타입 필터 ────────────────────────────────────────────────

  it('문서 타입 변경 시 api를 재호출한다', async () => {
    // Arrange
    const user = userEvent.setup();
    mockApi.mockResolvedValue([]);
    render(<QualityDashboard />);

    // Act
    const select = screen.getByRole('combobox');
    await user.selectOptions(select, 'sts');

    // Assert — 문서 타입 변경으로 인해 api 재호출
    await waitFor(() => {
      expect(mockApi).toHaveBeenCalledWith(expect.stringContaining('doc_type=sts'));
    });
  });

  // ── 새로고침 버튼 ─────────────────────────────────────────────────

  it('"새로고침" 버튼이 존재한다 (로딩 완료 후)', async () => {
    // Arrange
    mockApi.mockResolvedValue([]);

    // Act
    render(<QualityDashboard />);

    // Assert — 로딩 완료 후 "새로고침" 버튼이 나타남
    await waitFor(() => {
      expect(screen.getByText('새로고침')).toBeInTheDocument();
    });
  });

  it('점수 트렌드 패널 제목을 렌더링한다', () => {
    // Arrange & Act
    render(<QualityDashboard />);

    // Assert
    expect(screen.getByText('점수 트렌드')).toBeInTheDocument();
  });
});
