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
import { post, api } from '../api.js';

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
  authHeaders: vi.fn(() => ({ 'X-User': 'testuser' })),
}));

// fetch mock (VectorCAST 패키지 목록 등 fetch 호출 대비)
globalThis.fetch = vi.fn(() =>
  Promise.resolve({ ok: true, json: () => Promise.resolve({ packages: [] }) })
);

const { default: DocGenSection } = await import('../components/sections/DocGenSection.jsx');
// 폴러는 별도 모듈 — 컴포넌트 파일에서 export 하면 Fast Refresh 가 깨진다.
const { pollProgress, pollStsProgress } = await import('../docGenPoll.js');


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

  // ── 빌더 산출물 바로가기 버튼 (onNavigateSub) ─────────────────────

  it('onNavigateSub 미전달 시 빌더 바로가기 버튼(SwUT 등)은 렌더되지 않는다', async () => {
    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} />);
    await waitFor(() => expect(screen.getByText(/UDS 생성/)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /SwUT/ })).toBeNull();
  });

  it('onNavigateSub 전달 시 SwUT/SwIT/SwSA/통합 결과 바로가기 버튼을 렌더한다', async () => {
    const onNavigateSub = vi.fn();
    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} onNavigateSub={onNavigateSub} />);
    await waitFor(() => expect(screen.getByRole('button', { name: /SwUT/ })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /SwIT/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /SwSA/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /통합 결과/ })).toBeInTheDocument();
  });

  it('빌더 바로가기 버튼 클릭 시 해당 서브탭 id로 onNavigateSub를 호출한다', async () => {
    const user = userEvent.setup();
    const onNavigateSub = vi.fn();
    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} onNavigateSub={onNavigateSub} />);
    await waitFor(() => expect(screen.getByRole('button', { name: /SwUT/ })).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: /SwUT/ }));
    expect(onNavigateSub).toHaveBeenCalledWith('swut');
    await user.click(screen.getByRole('button', { name: /통합 결과/ }));
    expect(onNavigateSub).toHaveBeenCalledWith('swreport');
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

/* 취소가 '생성 완료'로 위장되지 않는가 (abort 계약)
 *
 * 예전엔 pollProgress/pollStsProgress 가 abort 시 null 을 돌려줬는데, 호출측의
 * `progress?.error` 가 optional chaining 이라 null 을 무해하게 통과시켜 그대로
 * 진행률 100% + "생성 완료" + 성공 토스트 + success:true 로 흘렀다. signal:null
 * 하드코딩 덕에 도달 불가한 잠복 결함이었지만, ISO 26262 산출물 생성 경로에서
 * 취소가 성공으로 위장되는 건 치명적이므로 계약을 throw 로 통일했다.
 *
 * 여기서는 폴러가 의존하는 progress 응답을 조작해 두 축을 고정한다:
 *  (1) 진행 상태를 못 받으면(falsy) 성공 분기로 못 간다
 *  (2) abort 예외는 실패 토스트도 내지 않는다(사용자 오류가 아님)
 */
describe('DocGenSection — 취소/이상응답이 성공으로 위장되지 않는다', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('취소는 "생성 완료" 성공 토스트를 내지 않는다', async () => {
    // 이게 원래 결함의 본체다. 폴러가 abort 시 null 을 돌려주던 시절, 호출측의
    // `progress?.error` 가 optional chaining 이라 null 을 무해하게 통과시켜 그대로
    // 진행률 100% + "생성 완료" + success:true 로 흘렀다.
    const user = userEvent.setup();
    globalThis.fetch = vi.fn(async (url) => ({
      ok: true,
      json: async () => (String(url).includes('/generate-async') ? { job_id: 'j1' } : { packages: [] }),
      text: async () => '',
    }));
    api.mockImplementation(async (url) => {
      if (String(url).includes('/progress')) {
        throw new DOMException('The operation was aborted.', 'AbortError');
      }
      return { items: [] };
    });

    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} />);
    await user.click(await screen.findByRole('button', { name: /UDS/ }));

    // ⚠ 폴러의 첫 대기가 2000ms 다. 그 전에 단언하면 아무 일도 안 일어난 상태를
    // '토스트 없음'으로 읽는 공허한 테스트가 된다 — 반드시 판정에 도달시킨다.
    await waitFor(() => expect(api).toHaveBeenCalledWith(expect.stringContaining('/progress')), { timeout: 6000 });
    await new Promise(r => setTimeout(r, 200));
    const successCalls = mockToast.mock.calls.filter(c => c[0] === 'success');
    expect(successCalls, JSON.stringify(mockToast.mock.calls)).toHaveLength(0);
  }, 20000);

  it('abort 예외는 실패 토스트로 보고하지 않는다', async () => {
    // isAbortError 로 걸러지는지 — 계약이 name/message 어느 쪽이든 통과해야 한다.
    const user = userEvent.setup();
    globalThis.fetch = vi.fn(async (url) => ({
      ok: true,
      json: async () => (String(url).includes('/generate-async') ? { job_id: 'j1' } : { packages: [] }),
      text: async () => '',
    }));
    api.mockImplementation(async (url) => {
      if (String(url).includes('/progress')) {
        throw new DOMException('The operation was aborted.', 'AbortError');
      }
      return { items: [] };
    });

    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} />);
    const btn = await screen.findByRole('button', { name: /UDS/ });
    await user.click(btn);

    // 동일 — 폴러가 실제로 api() 를 때려 abort 예외가 catch 에 도달해야 의미가 있다.
    await waitFor(() => expect(api).toHaveBeenCalledWith(expect.stringContaining('/progress')), { timeout: 6000 });
    await new Promise(r => setTimeout(r, 200));
    const errorCalls = mockToast.mock.calls.filter(c => c[0] === 'error');
    expect(errorCalls, JSON.stringify(mockToast.mock.calls)).toHaveLength(0);
  }, 20000);
});

/* 폴러 abort 계약 — signal 을 **실제로** 넘겨 검증
 *
 * 위 컴포넌트 레벨 테스트는 signal 을 넘기지 않아(이 화면엔 취소 UI 가 없다) 폴러의
 * throwIfAborted 가 항상 no-op 이고, 실제로는 `api()` 가 던지는 경로만 친다. 즉 폴러를
 * 옛 `return null` 계약으로 통째로 되돌려도 통과한다 = 계약 자체가 무커버리지였다.
 * 여기서는 폴러를 직접 불러 signal 을 넘긴다.
 *
 * 특히 **`await api()` 왕복 중 도착한 중단**을 고정한다. 루프 선두와 sleep 뒤에만 검사하면
 * done:true 응답이 그대로 return 돼 호출측이 "생성 완료 + success:true" 로 기록한다 —
 * ISO 26262 산출물 생성 경로에서 취소가 성공으로 위장되는 창이다.
 */
describe('DocGenSection 폴러 — abort 계약 (signal 실배선)', () => {
  beforeEach(() => { vi.clearAllMocks(); });

  it('pollProgress: api() 왕복 중 중단되면 done:true 를 반환하지 않고 throw 한다', async () => {
    const controller = new AbortController();
    api.mockImplementation(async () => {
      controller.abort();                       // 왕복 '중'에 중단이 도착한 상황
      return { progress: { done: true, output_path: 'x.docx' } };
    });

    await expect(
      pollProgress('http://j/job/x/', 'lastSuccessfulBuild', 'j1', 'uds', { onMsg: () => {} , signal: controller.signal })
    ).rejects.toMatchObject({ name: 'AbortError' });
  }, 20000);

  it('pollStsProgress: api() 왕복 중 중단되면 throw 한다 (return 지점 3개 전부 차단)', async () => {
    const controller = new AbortController();
    api.mockImplementation(async () => {
      controller.abort();
      return { status: 'completed', xlsm_path: 'y.xlsm' };   // done 플래그가 아닌 경로
    });

    await expect(
      pollStsProgress('j1', 'sts', 'http://j/job/x/', { onMsg: () => {}, signal: controller.signal })
    ).rejects.toMatchObject({ name: 'AbortError' });
  }, 20000);

  it('pollProgress: 대기 중 중단되면 api 를 아예 부르지 않는다', async () => {
    const controller = new AbortController();
    controller.abort();
    api.mockResolvedValue({ progress: { done: true } });

    await expect(
      pollProgress('http://j/job/x/', 'sel', 'j1', 'uds', { onMsg: () => {}, signal: controller.signal })
    ).rejects.toMatchObject({ name: 'AbortError' });
    expect(api).not.toHaveBeenCalled();
  }, 20000);

  it('중단이 없으면 정상적으로 진행 결과를 돌려준다 (과차단 방지)', async () => {
    api.mockResolvedValue({ progress: { done: true, output_path: 'ok.docx' } });
    const r = await pollProgress('http://j/job/x/', 'sel', 'j1', 'uds', { onMsg: () => {} });
    expect(r.output_path).toBe('ok.docx');
  }, 20000);
});
