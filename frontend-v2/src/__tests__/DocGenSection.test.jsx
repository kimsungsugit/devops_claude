/**
 * DocGenSection 컴포넌트 단위 테스트
 *
 * 요구사항 추적: SRS-SECTION-DOCGEN
 * - 문서 현황 패널 렌더링
 * - 4종 문서 생성 버튼(UDS/STS/SUTS/SITS) 존재 확인
 * - VectorCAST 패키지 관리 패널 렌더링
 * - 문서 생성 패널 제목 확인
 *
 * 외부 의존성:
 * - useJenkinsCfg, useToast: App.jsx mock
 * - api.js (api, post, getUsername, defaultCacheRoot): mock
 * - fetch: globalThis mock
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { post } from '../api.js';

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
  api: vi.fn().mockResolvedValue({ items: [] }),
  post: vi.fn(),
  defaultCacheRoot: vi.fn(() => ''),
  getUsername: vi.fn(() => 'testuser'),
}));

// fetch mock (VectorCAST 패키지 목록 등 fetch 호출 대비)
globalThis.fetch = vi.fn(() =>
  Promise.resolve({ ok: true, json: () => Promise.resolve({ packages: [] }) })
);

const { default: DocGenSection } = await import('../components/sections/DocGenSection.jsx');


/* ── 픽스처 ── */
const makeJob = () => ({
  name: 'test-job',
  url: 'http://jenkins/job/test-job/',
});

const makeAnalysisResult = () => ({
  cacheRoot: '.cache',
  scmList: [{ id: 'scm1', name: 'MyRepo', source_root: '/src', linked_docs: {} }],
});

describe('DocGenSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // localStorage 초기화
    localStorage.clear();
  });

  // ── 기본 렌더링 ───────────────────────────────────────────────────

  it('"문서 현황" 패널 제목을 렌더링한다', async () => {
    // Arrange & Act
    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText('문서 현황')).toBeInTheDocument();
    });
  });

  it('"문서 생성" 패널 제목을 렌더링한다', async () => {
    // Arrange & Act
    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText('문서 생성')).toBeInTheDocument();
    });
  });

  // ── 생성 버튼 존재 확인 ───────────────────────────────────────────

  it('UDS 생성 버튼이 존재한다', async () => {
    // Arrange & Act
    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText(/UDS 생성/)).toBeInTheDocument();
    });
  });

  it('STS 생성 버튼이 존재한다', async () => {
    // Arrange & Act
    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText(/STS 생성/)).toBeInTheDocument();
    });
  });

  it('SUTS 생성 버튼이 존재한다', async () => {
    // Arrange & Act
    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText(/SUTS 생성/)).toBeInTheDocument();
    });
  });

  it('SITS 생성 버튼이 존재한다', async () => {
    // Arrange & Act
    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText(/SITS 생성/)).toBeInTheDocument();
    });
  });

  // ── VectorCAST 패키지 관리 ───────────────────────────────────────

  it('VectorCAST 패키지 관리 패널 제목을 렌더링한다', async () => {
    // Arrange & Act
    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText('VectorCAST 패키지 관리')).toBeInTheDocument();
    });
  });

  it('SUTS 패키지 등록 버튼이 존재한다', async () => {
    // Arrange & Act
    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText(/SUTS 패키지 등록/)).toBeInTheDocument();
    });
  });

  it('SITS 패키지 등록 버튼이 존재한다', async () => {
    // Arrange & Act
    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText(/SITS 패키지 등록/)).toBeInTheDocument();
    });
  });

  // ── 문서 현황 테이블 ──────────────────────────────────────────────

  it('문서 현황 테이블에 SDS 행을 포함한다', async () => {
    // Arrange & Act
    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText('SDS')).toBeInTheDocument();
    });
  });

  it('문서 현황 테이블에 UDS 행을 포함한다', async () => {
    // Arrange & Act
    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

    // Assert
    await waitFor(() => {
      expect(screen.getAllByText('UDS').length).toBeGreaterThanOrEqual(1);
    });
  });

  // ── 미리보기 서버 페이지네이션(refetch) ──────────────────────────
  it('미리보기에서 "다음" 클릭 시 다음 page로 서버에 재요청한다', async () => {
    // Arrange — STS 경로가 있는 SCM, post는 has_more=true 미리보기 반환
    const user = userEvent.setup();
    post.mockResolvedValue({
      ok: true,
      filename: 'sts.xlsm',
      sheets: [{ name: 'Spec', headers: ['ID', 'Val'], rows: [['1', 'a'], ['2', 'b']], has_more: true, total_rows: 250, total_cols: 2 }],
      sheet_names: ['Spec'],
    });
    const ar = {
      cacheRoot: '.cache',
      scmList: [{ id: 'scm1', name: 'R', source_root: '/src', linked_docs: { sts: '/docs/sts.xlsm' } }],
    };

    // Act — STS 행의 "보기" 클릭 → page 0 로드
    render(<DocGenSection job={makeJob()} analysisResult={ar} />);
    const viewBtns = await screen.findAllByText('보기');
    await user.click(viewBtns[0]);

    // Assert — page 0, page_size 100으로 요청
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/preview-excel', expect.objectContaining({ page: 0, page_size: 100 }),
    ));

    // "다음 ›" 클릭 → page 1 재요청 (client slice가 아니라 서버 refetch)
    const next = await screen.findByText('다음 ›');
    post.mockClear();
    await user.click(next);
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/preview-excel', expect.objectContaining({ path: '/docs/sts.xlsm', page: 1 }),
    ));
  });

  it('미리보기 has_more=false면 "다음" 버튼이 비활성(유령 페이지 방지)', async () => {
    // Arrange
    const user = userEvent.setup();
    post.mockResolvedValue({
      ok: true,
      filename: 'sts.xlsm',
      sheets: [{ name: 'Spec', headers: ['ID', 'Val'], rows: [['1', 'a']], has_more: false, total_rows: 1, total_cols: 2 }],
      sheet_names: ['Spec'],
    });
    const ar = {
      cacheRoot: '.cache',
      scmList: [{ id: 'scm1', name: 'R', source_root: '/src', linked_docs: { sts: '/docs/sts.xlsm' } }],
    };

    // Act
    render(<DocGenSection job={makeJob()} analysisResult={ar} />);
    const viewBtns = await screen.findAllByText('보기');
    await user.click(viewBtns[0]);
    // 미리보기 패널 로드 대기('크게보기'는 미리보기 패널 고유 버튼)
    await screen.findByText('크게보기');

    // Assert — 단일 페이지(has_more=false, page 0): 페이저 자체가 렌더되지 않음
    expect(screen.queryByText('다음 ›')).toBeNull();
  });
});
