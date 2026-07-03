/**
 * Detail 뷰 단위 테스트
 *
 * 요구사항 추적: SRS-VIEW-DETAIL
 * - selectedJob 없을 때 빈 상태 메시지 표시
 * - selectedJob 있을 때 섹션 네비게이션 렌더링
 * - 섹션 탭 클릭 시 활성 상태 전환
 * - 브레드크럼 Job 이름 표시
 *
 * 외부 의존성 전략:
 * - useJob: App.jsx mock
 * - 모든 Section 컴포넌트: mock (단위 격리)
 */
import { render, screen, act, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Context mock ──────────────────────────────────────────────────────
let mockSelectedJob = null;
let mockAnalysisResult = null;
let mockCfg = {};
let mockJobsResponse = [];
const mockLoadProject = vi.fn(() =>
  Promise.resolve({ reportData: { build_number: 1 }, artifacts: [], scmList: [], matchedScm: null, _offline: true }),
);

vi.mock('../App.jsx', () => ({
  useJob: () => ({
    selectedJob: mockSelectedJob,
    analysisResult: mockAnalysisResult,
    setSelectedJob: () => {},
    setAnalysisResult: () => {},
  }),
  // Detail이 브레드크럼 프로젝트 선택기용으로 추가 소비 — creds 없는 cfg면 job fetch effect가 early return.
  useJenkinsCfg: () => ({ cfg: mockCfg }),
  useToast: () => () => {},
}));
// 브레드크럼 선택기: job 목록 fetch(post) + 전환 로드(loadProjectFromCache) mock.
vi.mock('../api.js', () => ({
  post: vi.fn((url) => (url === '/api/jenkins/jobs' ? Promise.resolve(mockJobsResponse) : Promise.resolve({}))),
  api: vi.fn(() => Promise.resolve([])),
  defaultCacheRoot: () => '',
}));
vi.mock('../projectLoader.js', () => ({
  loadProjectFromCache: (...a) => mockLoadProject(...a),
}));

// ── Section 컴포넌트 일괄 mock ─────────────────────────────────────
vi.mock('../components/sections/BuildInfoSection.jsx', () => ({
  default: () => <div data-testid="section-build">BuildInfo</div>,
}));
vi.mock('../components/sections/ScmSection.jsx', () => ({
  default: () => <div data-testid="section-scm">SCM</div>,
}));
vi.mock('../components/sections/AnalysisSection.jsx', () => ({
  default: () => <div data-testid="section-analysis">Analysis</div>,
}));
vi.mock('../components/sections/SrsSdsSection.jsx', () => ({
  default: () => <div data-testid="section-srssds">SrsSds</div>,
}));
// 통합 후 Detail은 6개 생성 섹션 대신 DocGenHubSection 하나만 import한다.
// onSubChange 콜백 + initialSub 라우팅 경로 검증을 위한 경량 mock(hook 미사용 — 호이스팅 안전).
let mockCapturedInitialSubs = [];
vi.mock('../components/sections/DocGenHubSection.jsx', () => ({
  default: ({ onSubChange, initialSub }) => {
    mockCapturedInitialSubs.push(initialSub);
    return (
      <div data-testid="section-docgen">
        DocGenHub
        <button onClick={() => onSubChange?.('swit', 'SwIT')}>__setsub</button>
      </div>
    );
  },
}));
vi.mock('../components/sections/AiAssistSection.jsx', () => ({
  default: () => <div data-testid="section-ai">AiAssist</div>,
}));
vi.mock('../components/sections/ImpactGuideSection.jsx', () => ({
  default: () => <div data-testid="section-impact">ImpactGuide</div>,
}));
vi.mock('../components/sections/ProjectSetupSection.jsx', () => ({
  default: () => <div data-testid="section-setup">ProjectSetup</div>,
}));

const { default: Detail } = await import('../views/Detail.jsx');

describe('Detail', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSelectedJob = null;
    mockAnalysisResult = null;
    mockCapturedInitialSubs = [];
    mockCfg = {};
    mockJobsResponse = [];
  });

  // ── selectedJob 없을 때 빈 상태 ────────────────────────────────

  it('selectedJob이 없으면 "프로젝트를 선택하세요" 메시지를 표시한다', () => {
    // Arrange & Act
    render(<Detail />);

    // Assert
    expect(screen.getByText('프로젝트를 선택하세요')).toBeInTheDocument();
  });

  it('selectedJob이 없으면 섹션 네비게이션을 렌더링하지 않는다', () => {
    // Arrange & Act
    render(<Detail />);

    // Assert
    expect(screen.queryByText('빌드 정보')).toBeNull();
  });

  it('selectedJob이 없으면 대시보드 안내 메시지를 포함한다', () => {
    // Arrange & Act
    render(<Detail />);

    // Assert
    expect(screen.getByText(/대시보드에서 Jenkins Job을 선택하고/)).toBeInTheDocument();
  });

  // ── selectedJob 있을 때 ─────────────────────────────────────────

  it('selectedJob이 있으면 섹션 네비게이션을 렌더링한다', () => {
    // Arrange
    mockSelectedJob = { name: 'my-job', url: 'http://jenkins/job/my-job/' };

    // Act
    render(<Detail />);

    // Assert — 통합 탭 레이블 "빌드 & 입력 데이터 정보"(브레드크럼+accordion 중복) + 다른 탭.
    // SCM은 더 이상 별도 탭이 아니라 빌드 탭에 통합됨.
    expect(screen.getAllByText(/빌드 & 입력 데이터 정보/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('문서 생성')).toBeInTheDocument();
    expect(screen.getByText('프로젝트 분석')).toBeInTheDocument();
  });

  it('selectedJob이 있으면 브레드크럼에 Job 이름을 표시한다', () => {
    // Arrange
    mockSelectedJob = { name: 'my-job', url: 'http://jenkins/job/my-job/' };

    // Act
    render(<Detail />);

    // Assert
    expect(screen.getByText('my-job')).toBeInTheDocument();
  });

  it('기본 활성 섹션은 "빌드 정보"이다', () => {
    // Arrange
    mockSelectedJob = { name: 'my-job', url: 'http://jenkins/job/my-job/' };

    // Act
    render(<Detail />);

    // Assert
    expect(screen.getByTestId('section-build')).toBeInTheDocument();
  });

  // ── 섹션 탭 네비게이션 ─────────────────────────────────────────

  it('빌드 정보 탭에 SCM 섹션이 통합되어 함께 표시된다', () => {
    // Arrange — build가 기본 활성. 통합 래퍼(BuildInfoWithScmSection)가 BuildInfo + SCM을 함께 렌더.
    mockSelectedJob = { name: 'my-job', url: 'http://jenkins/job/my-job/' };

    // Act
    render(<Detail />);

    // Assert — 별도 SCM 탭 없이 build 탭 안에서 section-build와 section-scm이 공존(빌드 로그 아래 배치)
    expect(screen.getByTestId('section-build')).toBeInTheDocument();
    expect(screen.getByTestId('section-scm')).toBeInTheDocument();
  });

  it('문서 생성 탭 클릭 시 DocGen 컴포넌트를 표시한다', async () => {
    // Arrange
    const user = userEvent.setup();
    mockSelectedJob = { name: 'my-job', url: 'http://jenkins/job/my-job/' };

    // Act
    render(<Detail />);
    await user.click(screen.getByText('문서 생성'));

    // Assert
    expect(screen.getByTestId('section-docgen')).toBeInTheDocument();
  });

  // ── 통합 허브 sub breadcrumb / 레거시 라우팅 ──────────────────

  it('docgen 허브의 onSubChange가 breadcrumb에 서브 라벨을 추가한다', async () => {
    // Arrange
    const user = userEvent.setup();
    mockSelectedJob = { name: 'my-job', url: 'http://jenkins/job/my-job/' };

    // Act
    render(<Detail />);
    await user.click(screen.getByText('문서 생성'));   // activeSection = docgen
    await user.click(screen.getByText('__setsub'));     // onSubChange('swit', 'SwIT')

    // Assert — breadcrumb 끝에 sub 라벨(SwIT)이 추가 렌더
    expect(screen.getByText('SwIT')).toBeInTheDocument();
  });

  it('레거시 생성 탭 id로 외부 네비게이션 시 docgen 허브로 라우팅 + initialSub 전달', async () => {
    // Arrange
    mockSelectedJob = { name: 'my-job', url: 'http://jenkins/job/my-job/' };
    render(<Detail />);

    // Act — 통합 전 'swut' id로 진입
    act(() => { window.__detailSection('swut'); });

    // Assert — docgen 섹션 활성화 + 허브에 initialSub='swut' 전달(소비-초기화 전)
    expect(screen.getByTestId('section-docgen')).toBeInTheDocument();
    await waitFor(() => expect(mockCapturedInitialSubs).toContain('swut'));
  });

  it('keep-alive: 탭을 전환해도 이전 방문 섹션이 마운트 유지된다(결과 보존)', async () => {
    // Arrange
    const user = userEvent.setup();
    mockSelectedJob = { name: 'my-job', url: 'http://jenkins/job/my-job/' };
    render(<Detail />);

    // Act — build(기본, BuildInfo+SCM 통합 탭) → 프로젝트 분석 방문
    expect(screen.getByTestId('section-scm')).toBeInTheDocument(); // 통합 탭에 SCM 포함
    await user.click(screen.getByText('프로젝트 분석'));

    // Assert — 활성(analysis) + 이전 방문(build 통합=build/scm)이 모두 DOM에 유지(언마운트 X = 상태 보존)
    expect(screen.getByTestId('section-analysis')).toBeInTheDocument();
    expect(screen.getByTestId('section-scm')).toBeInTheDocument();
    expect(screen.getByTestId('section-build')).toBeInTheDocument();
    // 미방문 섹션은 아직 마운트되지 않음(불필요 초기 요청 회피)
    expect(screen.queryByTestId('section-ai')).toBeNull();
  });

  it('탭 클릭 시 브레드크럼 섹션 레이블이 업데이트된다', async () => {
    // Arrange
    const user = userEvent.setup();
    mockSelectedJob = { name: 'my-job', url: 'http://jenkins/job/my-job/' };

    // Act
    render(<Detail />);
    await user.click(screen.getByText('프로젝트 분석'));

    // Assert — 브레드크럼에서도 활성 섹션 라벨이 나타남(네비 라벨 + 브레드크럼 = 2회 이상)
    expect(screen.getAllByText('프로젝트 분석').length).toBeGreaterThanOrEqual(2);
  });

  // ── 브레드크럼 프로젝트 선택기 ─────────────────────────────────────

  it('Jenkins creds가 없으면 선택기 대신 프로젝트 이름만 표시한다', () => {
    // Arrange — cfg에 creds 없음(기본)
    mockSelectedJob = { name: 'job-a', url: 'http://jenkins/job/job-a/' };

    // Act
    render(<Detail />);

    // Assert — select(combobox) 없음, 이름 span만
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(screen.getByText('job-a')).toBeInTheDocument();
  });

  it('creds가 있으면 브레드크럼에 프로젝트 선택기(select)를 렌더한다', async () => {
    // Arrange
    mockSelectedJob = { name: 'job-a', url: 'http://jenkins/job/job-a/' };
    mockCfg = { baseUrl: 'http://jenkins', username: 'u', token: 't' };
    mockJobsResponse = [
      { name: 'job-a', url: 'http://jenkins/job/job-a/' },
      { name: 'job-b', url: 'http://jenkins/job/job-b/' },
    ];

    // Act
    render(<Detail />);

    // Assert — 비동기 job fetch 완료 후 select 등장(옵션 2개)
    const select = await screen.findByRole('combobox');
    const options = within(select).getAllByRole('option');
    expect(options.length).toBe(2);
  });

  it('선택기에서 다른 프로젝트를 고르면 loadProjectFromCache로 캐시 로드한다', async () => {
    // Arrange
    const user = userEvent.setup();
    mockSelectedJob = { name: 'job-a', url: 'http://jenkins/job/job-a/' };
    mockCfg = { baseUrl: 'http://jenkins', username: 'u', token: 't' };
    mockJobsResponse = [
      { name: 'job-a', url: 'http://jenkins/job/job-a/' },
      { name: 'job-b', url: 'http://jenkins/job/job-b/' },
    ];
    render(<Detail />);
    const select = await screen.findByRole('combobox');

    // Act — job-b 선택
    await user.selectOptions(select, 'http://jenkins/job/job-b/');

    // Assert — 캐시 로더가 선택 URL로 호출됨
    expect(mockLoadProject).toHaveBeenCalledWith('http://jenkins/job/job-b/', expect.any(Object));
  });
});
