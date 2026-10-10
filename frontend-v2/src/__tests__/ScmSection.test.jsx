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
  // 실제 생산자는 jobUrl 을 항상 싣는다. 빠뜨리면 impactGuard 의 형제 필드 축이
  // vacuous 해져 그 축의 회귀를 테스트가 못 잡는다.
  jobUrl: makeJob().url,
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

  it('연결 문서를 파일명만 표시하고 전체 경로는 title로 노출한다', () => {
    // Arrange
    const result = makeAnalysisResult({
      scmList: [makeScm({
        linked_docs: { srs: 'D:/docs/srs.xlsx' },
      })],
    });

    // Act
    render(<ScmSection job={makeJob()} analysisResult={result} />);

    // Assert — 파일명만 표시(전체 경로 텍스트 아님)
    expect(screen.getByText('srs.xlsx')).toBeInTheDocument();
    expect(screen.queryByText('D:/docs/srs.xlsx')).not.toBeInTheDocument();
    // 전체 경로는 칩의 title(hover) 속성으로 보존
    expect(screen.getByTitle('D:/docs/srs.xlsx')).toBeInTheDocument();
  });

  it('연결 문서 값이 배열(복수 경로)이면 각 파일명을 개별 칩으로 표시한다', () => {
    // Arrange — vectorcast 등 list 값
    const result = makeAnalysisResult({
      scmList: [makeScm({
        linked_docs: { vectorcast: ['U:/vc/APP_IT.html', 'U:/vc/BOOT_IT.html'] },
      })],
    });

    // Act
    render(<ScmSection job={makeJob()} analysisResult={result} />);

    // Assert
    expect(screen.getByText('APP_IT.html')).toBeInTheDocument();
    expect(screen.getByText('BOOT_IT.html')).toBeInTheDocument();
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

  // ── 오귀속 차단 (impactGuard 배선) ──────────────────────────────────
  // Dashboard.runAnalysis는 여러 개가 겹쳐 돌 수 있고 서버측 취소가 없어 구 실행이 완주한다.
  // 그래서 Context의 impactData가 지금 보고 있는 Job/SCM의 것이 아닐 수 있다. 대조 없이
  // 그리면 다른 프로젝트의 변경 파일을 이 프로젝트 것으로 표시하게 된다(ISO 26262 오보고).

  it('안전: 다른 SCM의 분석 결과면 변경 파일을 표시하지 않고 사유를 밝힌다', () => {
    // Arrange — 화면은 scm-1을 보고 있는데 결과는 other-scm의 것
    const result = makeAnalysisResult({
      impactData: {
        trigger: { scm_id: 'other-scm' },
        changed_files: ['src/module_a.c'],
      },
    });

    // Act
    render(<ScmSection job={makeJob()} analysisResult={result} />);

    // Assert
    expect(screen.queryByText('src/module_a.c')).not.toBeInTheDocument();
    expect(screen.getByText(/다른 SCM의 것입니다/)).toBeInTheDocument();
  });

  it('안전: 다른 Job의 분석 결과면 변경 파일을 표시하지 않고 사유를 밝힌다', () => {
    // Arrange
    const result = makeAnalysisResult({
      impactData: {
        trigger: { scm_id: 'scm-1', metadata: { job_url: 'http://jenkins/job/other-job/' } },
        changed_files: ['src/module_a.c'],
      },
    });

    // Act
    render(<ScmSection job={makeJob()} analysisResult={result} />);

    // Assert
    expect(screen.queryByText('src/module_a.c')).not.toBeInTheDocument();
    expect(screen.getByText(/다른 Job의 빌드로 실행됐습니다/)).toBeInTheDocument();
  });

  it('안전: 결과 뭉치가 다른 Job의 것이면 (나머지 축이 vacuous여도) 차단한다', () => {
    // 로컬 트리거 결과는 trigger.metadata.job_url 이 없어 축 2가 vacuous하고,
    // selectedId 는 같은 analysisResult 에서 seed 되므로 축 3도 vacuous하다.
    // 형제 필드 축이 유일 방어인 상황.
    const result = makeAnalysisResult({
      jobUrl: 'http://jenkins/job/project-a/',
      impactData: {
        trigger: { scm_id: 'scm-1', metadata: {} },
        changed_files: ['src/module_a.c'],
      },
    });

    render(<ScmSection job={makeJob()} analysisResult={result} />);

    expect(screen.queryByText('src/module_a.c')).not.toBeInTheDocument();
    expect(screen.getByText(/다른 Job의 것입니다/)).toBeInTheDocument();
  });

  it('같은 SCM·같은 Job의 결과는 정상 표시한다 (과차단 방지)', () => {
    // Arrange
    const result = makeAnalysisResult({
      impactData: {
        trigger: { scm_id: 'scm-1', metadata: { job_url: makeJob().url } },
        changed_files: ['src/module_a.c'],
      },
    });

    // Act
    render(<ScmSection job={makeJob()} analysisResult={result} />);

    // Assert
    expect(screen.getByText('src/module_a.c')).toBeInTheDocument();
    expect(screen.queryByText(/표시하지 않았습니다/)).not.toBeInTheDocument();
  });

  // ── 경계값: analysisResult null 처리 ─────────────────────────────

  it('analysisResult가 null이면 오류 없이 렌더링한다', () => {
    // Arrange & Act & Assert
    expect(() => {
      render(<ScmSection job={makeJob()} analysisResult={null} />);
    }).not.toThrow();
  });
});
