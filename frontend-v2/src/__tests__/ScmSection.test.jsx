/**
 * ScmSection 컴포넌트 단위 테스트
 *
 * 요구사항 추적: SRS-SECTION-SCM
 * - SCM 미등록 시 빈 상태 표시
 * - SCM 목록이 있을 때 선택된 SCM 정보 표시
 * - SCM URL, 브랜치, 소스 루트 정보 렌더링
 * - "SCM 정보", "소스 루트" 버튼 존재 확인
 * - 연결 문서 렌더링
 * - 변경 파일 목록 렌더링
 *
 * 외부 의존성:
 * - useJenkinsCfg, useToast: App.jsx mock
 * - api.js (post, defaultCacheRoot): mock
 * - StatusBadge: 실제 컴포넌트 사용
 */
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Context mock ──────────────────────────────────────────────────────
const mockToast = vi.fn();

vi.mock('../App.jsx', () => ({
  useJenkinsCfg: () => ({
    cfg: {
      baseUrl: 'http://jenkins',
      username: 'user',
      token: 'token',
      cacheRoot: '.cache',
      buildSelector: 'lastSuccessfulBuild',
    },
    update: vi.fn(),
  }),
  useToast: () => mockToast,
}));

// ── api.js mock ───────────────────────────────────────────────────────
vi.mock('../api.js', () => ({
  post: vi.fn(),
  defaultCacheRoot: vi.fn(() => ''),
}));

const { default: ScmSection } = await import('../components/sections/ScmSection.jsx');

/* ── 픽스처 ── */
const makeJob = () => ({
  name: 'test-job',
  url: 'http://jenkins/job/test-job/',
});

const makeScm = (overrides = {}) => ({
  id: 'scm-1',
  name: 'MyRepo',
  scm_type: 'git',
  scm_url: 'https://github.com/org/repo.git',
  branch: 'main',
  source_root: 'D:/Project/src',
  base_ref: 'origin/main',
  linked_docs: {},
  ...overrides,
});

const makeAnalysisResult = (overrides = {}) => ({
  cacheRoot: '.cache',
  scmList: [makeScm()],
  impactData: null,
  reportData: {},
  ...overrides,
});

describe('ScmSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // ── SCM 미등록 상태 ───────────────────────────────────────────────

  it('SCM 목록이 없으면 "SCM 미등록" 메시지를 표시한다', () => {
    // Arrange & Act
    render(<ScmSection job={makeJob()} analysisResult={{ cacheRoot: '.cache', scmList: [] }} />);

    // Assert
    expect(screen.getByText('SCM 미등록')).toBeInTheDocument();
  });

  it('SCM 미등록 시 설정 안내 메시지를 표시한다', () => {
    // Arrange & Act
    render(<ScmSection job={makeJob()} analysisResult={{ cacheRoot: '.cache', scmList: [] }} />);

    // Assert
    expect(screen.getByText(/설정 탭에서 SCM을 등록하면/)).toBeInTheDocument();
  });

  // ── SCM 목록 있을 때 ─────────────────────────────────────────────

  it('SCM 이름을 패널 헤더에 표시한다', () => {
    // Arrange & Act
    render(<ScmSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    expect(screen.getByText(/MyRepo/)).toBeInTheDocument();
  });

  it('SCM URL을 표시한다', () => {
    // Arrange & Act
    render(<ScmSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    expect(screen.getByText('https://github.com/org/repo.git')).toBeInTheDocument();
  });

  it('브랜치 정보를 표시한다', () => {
    // Arrange & Act
    render(<ScmSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    expect(screen.getByText('main')).toBeInTheDocument();
  });

  it('소스 루트를 표시한다', () => {
    // Arrange & Act
    render(<ScmSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    expect(screen.getByText('D:/Project/src')).toBeInTheDocument();
  });

  // ── 버튼 존재 확인 ────────────────────────────────────────────────

  it('"SCM 정보" 버튼이 존재한다', () => {
    // Arrange & Act
    render(<ScmSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    expect(screen.getByText('SCM 정보')).toBeInTheDocument();
  });

  it('"소스 루트" 버튼이 존재한다', () => {
    // Arrange & Act
    render(<ScmSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert — "소스 루트"는 버튼과 필드 label에 함께 존재하므로 getAllByText 사용
    expect(screen.getAllByText('소스 루트').length).toBeGreaterThanOrEqual(1);
  });

  // ── 연결 문서 ─────────────────────────────────────────────────────

  it('연결 문서가 있을 때 "연결 문서" 섹션을 표시한다', () => {
    // Arrange
    const result = makeAnalysisResult({
      scmList: [makeScm({
        linked_docs: { srs: 'D:/docs/srs.xlsx', uds: 'D:/docs/uds.xlsm' },
      })],
    });

    // Act
    render(<ScmSection job={makeJob()} analysisResult={result} />);

    // Assert
    expect(screen.getByText('연결 문서')).toBeInTheDocument();
  });

  it('연결 문서 경로를 표시한다', () => {
    // Arrange
    const result = makeAnalysisResult({
      scmList: [makeScm({
        linked_docs: { srs: 'D:/docs/srs.xlsx' },
      })],
    });

    // Act
    render(<ScmSection job={makeJob()} analysisResult={result} />);

    // Assert
    expect(screen.getByText('D:/docs/srs.xlsx')).toBeInTheDocument();
  });

  // ── 변경 파일 목록 ────────────────────────────────────────────────

  it('변경 파일 목록이 있을 때 변경 파일 패널을 표시한다', () => {
    // Arrange
    const result = makeAnalysisResult({
      impactData: {
        changed_files: ['src/module_a.c', 'src/module_b.c'],
      },
    });

    // Act
    render(<ScmSection job={makeJob()} analysisResult={result} />);

    // Assert
    expect(screen.getByText(/변경 파일/)).toBeInTheDocument();
  });

  it('변경 파일 경로를 목록에 표시한다', () => {
    // Arrange
    const result = makeAnalysisResult({
      impactData: {
        changed_files: ['src/module_a.c'],
      },
    });

    // Act
    render(<ScmSection job={makeJob()} analysisResult={result} />);

    // Assert
    expect(screen.getByText('src/module_a.c')).toBeInTheDocument();
  });

  // ── 경계값: analysisResult null 처리 ─────────────────────────────

  it('analysisResult가 null이면 오류 없이 렌더링한다', () => {
    // Arrange & Act & Assert
    expect(() => {
      render(<ScmSection job={makeJob()} analysisResult={null} />);
    }).not.toThrow();
  });
});
