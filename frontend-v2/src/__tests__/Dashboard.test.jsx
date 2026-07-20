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
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
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
// 세대 가드 테스트에서 mock 구현을 갈아끼우기 위해 모듈 자체를 잡아 둔다.
const { post: mockPost, api: mockApi } = await import('../api.js');

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

/* 실행 세대(generation) 가드 — 겹친 분석의 last-writer-wins 차단
 *
 * runAnalysis는 여러 개가 겹쳐 돌 수 있다(job 전환·재실행). 서버측 취소 endpoint가 없어
 * 선행 실행은 abort 후에도 진행 중인 fetch를 완주하는데, 그때 구 실행이 setAnalysisResult를
 * 그대로 호출하면 '늦게 끝난 쪽이 이기는' 상태가 된다. 그 결과 다른 프로젝트의 영향분석
 * 결과가 현재 화면의 Context에 실리고, SrsSdsSection·ScmSection이 그걸 이 프로젝트의
 * 추적성 근거로 표시한다(ISO 26262 오보고).
 *
 * abort만으로는 부족하다 — signal을 안 받는 raw post 호출(report/summary 등)은 완주하고,
 * 그 직후의 updateResult()에는 abort 검사 지점이 없다. 그래서 세대 가드가 필요하다. */
describe('Dashboard — 실행 세대 가드', () => {
  const post = mockPost;
  const api = mockApi;
  const JOB_A = { name: 'job-a', url: 'http://jenkins/job/job-a/' };

  /** 수동으로 resolve할 수 있는 promise. */
  const deferred = () => {
    let resolve;
    const promise = new Promise(r => { resolve = r; });
    return { promise, resolve };
  };

  beforeEach(() => {
    vi.clearAllMocks();
    mockCfg = {
      baseUrl: 'http://jenkins', username: 'u', token: 't',
      cacheRoot: '.cache', buildSelector: 'lastSuccessfulBuild', verifyTls: true,
    };
    mockSelectedJob = JOB_A;
  });

  it('선행 실행이 늦게 끝나도 후행 실행을 덮어쓰지 않는다', async () => {
    // Arrange — report/summary에서 각 실행을 멈춰 세운다. 이 지점은 abort 검사가 없어
    // 세대 가드가 없으면 구 실행이 그대로 updateResult()까지 진행한다.
    const summaryCalls = [];
    post.mockImplementation(async (url) => {
      if (url === '/api/jenkins/jobs') return [JOB_A];
      if (url === '/api/jenkins/sync-async') return { job_id: 'sync-1' };
      if (url === '/api/jenkins/build-info') throw new Error('no cache');
      if (url === '/api/jenkins/report/summary') {
        const d = deferred();
        summaryCalls.push(d);
        return d.promise;
      }
      return {};
    });
    api.mockImplementation(async (url) => {
      if (String(url).includes('/api/scm/list')) return { items: [{ id: 'scm-1' }] };
      if (String(url).includes('/api/jenkins/progress')) {
        return { progress: { done: true, checkout_ok: true } };
      }
      return {};
    });

    render(<Dashboard />);
    const card = await screen.findByTestId('job-card');

    // Act — 실행 1 시작 후 report/summary에서 멈출 때까지 대기
    fireEvent.click(card);
    await waitFor(() => expect(summaryCalls.length).toBe(1), { timeout: 10000 });

    // 실행 2 시작 (job 전환에 해당) — 여기서 세대가 올라간다
    fireEvent.click(card);
    await waitFor(() => expect(summaryCalls.length).toBe(2), { timeout: 10000 });

    // 이제 실행 1을 완주시킨다
    summaryCalls[0].resolve({ kpis: {}, artifacts: {}, build_number: 111 });
    await new Promise(r => setTimeout(r, 100));

    // Assert (부정) — 구 실행은 Context에 아무것도 쓰지 않는다
    expect(mockSetAnalysisResult).not.toHaveBeenCalled();

    // Assert (긍정) — 가드가 '전부 차단'으로 망가지지 않았는지 반드시 함께 본다.
    // 부정 단언만 두면 isCurrent()를 상수 false로 바꿔도 테스트가 통과한다(둘 다 안 씀).
    // 그 상태는 finally의 setRunning(false)까지 막아 running이 true로 고착된다.
    summaryCalls[1].resolve({ kpis: {}, artifacts: {}, build_number: 222 });
    await waitFor(() => expect(mockSetAnalysisResult).toHaveBeenCalled(), { timeout: 10000 });
    // 마지막으로 기록된 결과는 후행 실행의 것이어야 한다
    const lastWrite = mockSetAnalysisResult.mock.calls.at(-1)[0];
    expect(lastWrite.reportData?.build_number).toBe(222);
  }, 30000);

  it('중단 후에는 구 실행이 Context에 쓰지 않는다', async () => {
    // abort만으로는 부족하다 — report/summary는 signal을 안 받아 완주하고,
    // 그 직후 updateResult()에는 abort 검사 지점이 없다. stopAnalysis가 세대를 올려야 막힌다.
    const summaryCalls = [];
    post.mockImplementation(async (url) => {
      if (url === '/api/jenkins/jobs') return [JOB_A];
      if (url === '/api/jenkins/sync-async') return { job_id: 'sync-1' };
      if (url === '/api/jenkins/build-info') throw new Error('no cache');
      if (url === '/api/jenkins/report/summary') {
        const d = deferred();
        summaryCalls.push(d);
        return d.promise;
      }
      return {};
    });
    api.mockImplementation(async (url) => {
      if (String(url).includes('/api/scm/list')) return { items: [{ id: 'scm-1' }] };
      if (String(url).includes('/api/jenkins/progress')) {
        return { progress: { done: true, checkout_ok: true } };
      }
      return {};
    });

    render(<Dashboard />);
    fireEvent.click(await screen.findByTestId('job-card'));
    await waitFor(() => expect(summaryCalls.length).toBe(1), { timeout: 10000 });

    // 중단
    fireEvent.click(screen.getByText('중단'));

    // 중단 후 진행 중이던 요청이 완주한다
    summaryCalls[0].resolve({ kpis: {}, artifacts: {}, build_number: 111 });
    await new Promise(r => setTimeout(r, 200));

    expect(mockSetAnalysisResult).not.toHaveBeenCalled();
  }, 30000);
});
