/**
 * Dashboard 뷰 단위 테스트
 *
 * 요구사항 추적: SRS-VIEW-DASHBOARD
 * - Job 목록 그리드 렌더링
 * - Jenkins 설정 없을 때 빈 상태 표시
 * - Job 목록 불러오기 버튼 노출 확인
 * - 필터 입력 필드 존재 확인
 *
 * 외부 의존성 전략:
 * - useToast, useJenkinsCfg, useJob: App.jsx mock
 * - api.js (post/api): 전체 mock
 * - JobCard, ResultPanel: mock (단위 격리)
 */
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

// ── Context mock ──────────────────────────────────────────────────────
const mockToast = vi.fn();
const mockSetSelectedJob = vi.fn();
const mockSetAnalysisResult = vi.fn();

let mockCfg = { baseUrl: '', username: '', token: '', cacheRoot: '.cache', buildSelector: 'lastSuccessfulBuild', verifyTls: true };
let mockSelectedJob = null;

vi.mock('../App.jsx', () => ({
  useToast: () => mockToast,
  useJenkinsCfg: () => ({ cfg: mockCfg, update: vi.fn() }),
  useJob: () => ({
    selectedJob: mockSelectedJob,
    setSelectedJob: mockSetSelectedJob,
    analysisResult: null,
    setAnalysisResult: mockSetAnalysisResult,
  }),
}));

// ── api.js mock ───────────────────────────────────────────────────────
vi.mock('../api.js', () => ({
  post: vi.fn(),
  api: vi.fn(),
  defaultCacheRoot: vi.fn(() => ''),
}));

// ── 자식 컴포넌트 mock (단위 격리) ───────────────────────────────────
vi.mock('../components/JobCard.jsx', () => ({
  default: ({ job, selected, onClick }) => (
    <div
      data-testid="job-card"
      data-selected={selected}
      onClick={onClick}
      role="button"
    >
      {job.name}
    </div>
  ),
}));

vi.mock('../components/ResultPanel.jsx', () => ({
  default: () => <div data-testid="result-panel">ResultPanel</div>,
}));

const { default: Dashboard } = await import('../views/Dashboard.jsx');

describe('Dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockCfg = { baseUrl: '', username: '', token: '', cacheRoot: '.cache', buildSelector: 'lastSuccessfulBuild', verifyTls: true };
    mockSelectedJob = null;
  });

  // ── 기본 렌더링 ───────────────────────────────────────────────────

  it('툴바 제목 "Jenkins 프로젝트"를 렌더링한다', () => {
    // Arrange & Act
    render(<Dashboard onGoDetail={vi.fn()} />);

    // Assert
    expect(screen.getByText('Jenkins 프로젝트')).toBeInTheDocument();
  });

  it('"Job 목록 불러오기" 버튼을 렌더링한다', () => {
    // Arrange & Act
    render(<Dashboard onGoDetail={vi.fn()} />);

    // Assert
    expect(screen.getByText('Job 목록 불러오기')).toBeInTheDocument();
  });

  it('Job 이름 필터 입력 필드를 렌더링한다', () => {
    // Arrange & Act
    render(<Dashboard onGoDetail={vi.fn()} />);

    // Assert
    expect(screen.getByPlaceholderText('Job 이름 필터...')).toBeInTheDocument();
  });

  // ── 빈 상태 (Jenkins 미설정) ────────────────────────────────────────

  it('Job이 없을 때 "Jenkins Job 없음" 빈 상태를 표시한다', () => {
    // Arrange & Act
    render(<Dashboard onGoDetail={vi.fn()} />);

    // Assert
    expect(screen.getByText('Jenkins Job 없음')).toBeInTheDocument();
  });

  it('Jenkins 설정이 없을 때 설정 안내 메시지를 표시한다', () => {
    // Arrange & Act
    render(<Dashboard onGoDetail={vi.fn()} />);

    // Assert
    expect(screen.getByText(/설정 탭에서 Jenkins 연결 정보를 입력한 후/)).toBeInTheDocument();
  });

  // ── selectedJob 없을 때 분석 패널 비표시 ─────────────────────────

  it('selectedJob이 없으면 분석 실행 패널을 렌더링하지 않는다', () => {
    // Arrange & Act
    render(<Dashboard onGoDetail={vi.fn()} />);

    // Assert
    expect(screen.queryByText('동기화 & 분석 실행')).toBeNull();
  });

  // ── selectedJob 있을 때 분석 패널 표시 ──────────────────────────

  it('selectedJob이 있으면 분석 실행 버튼을 렌더링한다', () => {
    // Arrange
    mockSelectedJob = { name: 'test-job', url: 'http://jenkins/job/test-job/' };

    // Act
    render(<Dashboard onGoDetail={vi.fn()} />);

    // Assert
    expect(screen.getByText('동기화 & 분석 실행')).toBeInTheDocument();
  });

  it('selectedJob이 있으면 선택된 프로젝트 이름을 표시한다', () => {
    // Arrange
    mockSelectedJob = { name: 'test-job', url: 'http://jenkins/job/test-job/' };

    // Act
    render(<Dashboard onGoDetail={vi.fn()} />);

    // Assert
    expect(screen.getByText(/선택된 프로젝트: test-job/)).toBeInTheDocument();
  });
});

/* D1 회귀 방지 (정적 검증)
 * runAnalysis 는 useCallback이고 본문에서 manualScmId를 참조한다.
 * deps 배열에서 manualScmId가 빠지면 stale closure 발생 → 사용자가 SCM 드롭다운에서
 * manual 선택해도 첫 mount 시점의 값으로 고정됨 (ASIL D source 매칭 영향).
 *
 * useCallback의 deps를 런타임에 외부에서 inspect할 방법이 없으므로 (React가
 * 노출하지 않음) 소스 파일 자체를 정적으로 grep해서 회귀를 막는다. ESLint
 * react-hooks/exhaustive-deps 룰을 도입하면 이 테스트는 대체 가능. */
describe('Dashboard (정적 회귀 방지)', () => {
  const __filename = fileURLToPath(import.meta.url);
  const __dirname = dirname(__filename);
  const dashboardSrc = readFileSync(
    resolve(__dirname, '../views/Dashboard.jsx'),
    'utf8',
  );

  it('runAnalysis useCallback deps에 manualScmId가 포함되어 있다 (D1)', () => {
    const m = dashboardSrc.match(
      /const runAnalysis = useCallback\(async [\s\S]*?\n\s*\}, \[([^\]]*)\]\);/,
    );
    expect(m, 'runAnalysis useCallback 블록을 찾지 못함').not.toBeNull();
    const deps = m[1];
    expect(deps, `runAnalysis deps에 manualScmId 누락 — D1 stale closure 회귀 위험. 현재 deps: [${deps}]`).toMatch(/\bmanualScmId\b/);
  });

  it('runAnalysis 본문에서 manualScmId를 참조한다 (sanity check)', () => {
    /* deps 검증이 의미를 가지려면 본문이 실제로 manualScmId를 사용해야 한다.
     * 본문에서 사라졌는데 deps에만 남아있는 dead reference는 별개 문제. */
    expect(dashboardSrc).toMatch(/const runAnalysis = useCallback[\s\S]*?\bmanualScmId\b[\s\S]*?\}, \[/);
  });
});
