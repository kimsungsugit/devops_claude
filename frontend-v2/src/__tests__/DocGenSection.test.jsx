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

/* ── VectorCAST 패키지 패널 ─────────────────────────────────────────────
 * 실측(2026-08-07): 이 패널은 세 가지가 동시에 고장 나 있었고 **아무도 몰랐다**.
 *   1. 목록이 cache 경로를 `report_dir` 로 보내 403 → `catch` 가 삼켜
 *      화면엔 "등록된 패키지가 없습니다" (403 이 '없음'으로 위장)
 *   2. 등록 경로가 두 갈래인데 목록은 한쪽만 봐서 반대쪽 등록물이 안 보임
 *   3. 다운로드가 `<a href download>` 라 Authorization 이 안 실려 401
 * 백엔드 계약은 `tests/unit/test_vectorcast_package_endpoints.py`.
 */
describe('DocGenSection — VectorCAST 패키지 목록이 실패를 숨기지 않는다', () => {
  const VCAST_URL = '/api/local/vectorcast/list';
  let vcastResponse;
  let vcastError;

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    vcastResponse = { ok: true, packages: [], warnings: [], scanned_roots: [] };
    vcastError = null;
    // ⚠ url 별 분기 — 전역 mockResolvedValue 로 덮으면 같은 컴포넌트의 다른 조회까지
    //   같은 응답을 받아 테스트가 엉뚱한 이유로 통과한다.
    api.mockImplementation(async (url) => {
      if (String(url).startsWith(VCAST_URL)) {
        if (vcastError) throw vcastError;
        return vcastResponse;
      }
      return { items: [] };
    });
  });

  afterEach(() => {
    // 원래 구현으로 되돌린다 — 특정 값으로 고정하지 않는다.
    api.mockReset();
    api.mockResolvedValue({ items: [] });
  });

  const renderPanel = () =>
    render(<DocGenSection job={makeJob()} analysisResult={makeAnalysisResult()} />);

  it('조회 실패를 "패키지가 없습니다"로 위장하지 않는다', async () => {
    vcastError = new Error('403: package_path not allowed');
    renderPanel();

    expect(await screen.findByText(/목록을 불러오지 못했습니다/)).toBeInTheDocument();
    expect(screen.queryByText(/등록된 VectorCAST 패키지가 없습니다/)).toBeNull();
  });

  it('백엔드가 루트를 제외했으면 그 사유를 화면에 올린다', async () => {
    vcastResponse = {
      ok: true, packages: [], scanned_roots: [],
      warnings: ['report_dir 무시됨(report_dir not allowed) — 기본 리포트 루트로 대체'],
    };
    renderPanel();

    expect(await screen.findByText(/report_dir 무시됨/)).toBeInTheDocument();
  });

  it('cache_root 로 조회한다 — report_dir 로 보내면 백엔드가 403 을 낸다', async () => {
    renderPanel();

    await waitFor(() => {
      const call = api.mock.calls.find(([u]) => String(u).startsWith(VCAST_URL));
      expect(call).toBeTruthy();
      expect(call[0]).toContain('cache_root=');
      expect(call[0]).not.toContain('report_dir=');
    });
  });

  it('0건이면 어느 위치를 봤는지 밝힌다 (미등록 ≠ 경로 오설정)', async () => {
    vcastResponse = {
      ok: true, packages: [], warnings: [],
      scanned_roots: [
        { source: 'reports', path: 'R:/reports/vectorcast', exists: true, count: 0 },
        { source: 'jenkins_cache', path: 'C:/cache/exports/vectorcast', exists: false, count: 0 },
      ],
    };
    renderPanel();

    const note = await screen.findByText(/조회한 위치:/);
    expect(note.textContent).toContain('R:/reports/vectorcast');
    expect(note.textContent).toContain('C:/cache/exports/vectorcast (없음)');
  });

  it('이름이 같아도 루트가 다르면 둘 다 보인다 (key 충돌로 한쪽이 사라지지 않는다)', async () => {
    vcastResponse = {
      ok: true, warnings: [], scanned_roots: [],
      packages: [
        { name: 'suts_pkg', path: '/a/suts_pkg', source: 'reports', doc_type: 'suts', file_count: 3, files: [], summary: {}, created: null },
        { name: 'suts_pkg', path: '/b/suts_pkg', source: 'jenkins_cache', doc_type: 'suts', file_count: 4, files: [], summary: {}, created: null },
      ],
    };
    // ⚠ 행 개수만 세면 부족하다 — React 는 key 가 겹쳐도 **첫 렌더는 두 행을 그린다**.
    //   그래서 `key={pkg.name}` 으로 되돌린 뮤턴트가 생존했다. 충돌 자체를 단언한다:
    //   갱신 시 엉뚱한 행이 남는 사고는 이 경고가 나온 뒤에 생긴다.
    const errors = [];
    const spy = vi.spyOn(console, 'error').mockImplementation((...a) => { errors.push(a.join(' ')); });
    try {
      renderPanel();
      await waitFor(() => expect(screen.getAllByText('suts_pkg')).toHaveLength(2));
      expect(screen.getByText('(빌드 캐시)')).toBeInTheDocument();
      expect(errors.filter((m) => /same key/i.test(m))).toEqual([]);
    } finally {
      spy.mockRestore();
    }
  });

  it('다운로드가 인증 헤더를 붙이고, 실패를 조용히 넘기지 않는다', async () => {
    vcastResponse = {
      ok: true, warnings: [], scanned_roots: [],
      packages: [
        { name: 'dl_pkg', path: '/a/dl_pkg', source: 'reports', doc_type: 'suts', file_count: 1, files: [], summary: {}, created: null },
      ],
    };
    const savedFetch = globalThis.fetch;
    const savedCreate = URL.createObjectURL;
    const savedRevoke = URL.revokeObjectURL;
    // ⚠ 401 을 준다 — 예전 `<a href download>` 는 헤더를 못 실어 실제로 이 응답을 받았고,
    //   그 401 본문이 그대로 파일로 저장돼 "열리지 않는 파일"이 됐다.
    // ⚠ 응답 mock 은 **완전해야** 한다. 처음엔 `blob` 을 빼먹었더니 `res.ok` 검사를
    //   지운 뮤턴트가 `res.blob is not a function` 으로 죽어 **엉뚱한 이유로** 에러
    //   토스트가 났고, 그래서 그 뮤턴트가 생존했다(가드가 아니라 mock 이 잡은 것).
    globalThis.fetch = vi.fn(async () => ({
      ok: false,
      status: 401,
      text: async () => 'Authorization Bearer token 필요',
      blob: async () => new Blob(['Authorization Bearer token 필요']),
    }));
    URL.createObjectURL = vi.fn(() => 'blob:mock');
    URL.revokeObjectURL = vi.fn();
    try {
      renderPanel();
      await userEvent.click(await screen.findByText(/📥 다운로드/));

      await waitFor(() => {
        const call = globalThis.fetch.mock.calls.find(([u]) =>
          String(u).startsWith('/api/local/vectorcast/download'));
        expect(call).toBeTruthy();
        expect(call[1]?.headers).toBeTruthy();          // authHeaders() 미부착이면 undefined
        expect(mockToast).toHaveBeenCalledWith('error', expect.stringContaining('다운로드 실패'));
      });
      // 관측량: 실패했으면 **파일 저장이 시작되면 안 된다**. 토스트만 보면
      // "에러도 내고 파일도 받는" 상태를 놓친다(그게 예전 401 저장 사고였다).
      expect(URL.createObjectURL).not.toHaveBeenCalled();
    } finally {
      globalThis.fetch = savedFetch;
      URL.createObjectURL = savedCreate;
      URL.revokeObjectURL = savedRevoke;
    }
  });

  it('삭제도 cache_root 를 함께 보낸다 (목록과 같은 루트로 판정돼야 지워진다)', async () => {
    vcastResponse = {
      ok: true, warnings: [], scanned_roots: [],
      packages: [
        { name: 'del_pkg', path: '/a/del_pkg', source: 'reports', doc_type: 'suts', file_count: 1, files: [], summary: {}, created: null },
      ],
    };
    const savedConfirm = globalThis.confirm;
    globalThis.confirm = vi.fn(() => true);
    try {
      renderPanel();
      await userEvent.click(await screen.findByText('🗑'));

      await waitFor(() => {
        const call = api.mock.calls.find(([u]) =>
          String(u).startsWith('/api/local/vectorcast/delete'));
        expect(call).toBeTruthy();
        expect(call[0]).toContain('cache_root=');
        expect(call[0]).toContain('package_path=');
      });
    } finally {
      globalThis.confirm = savedConfirm;
    }
  });
});
