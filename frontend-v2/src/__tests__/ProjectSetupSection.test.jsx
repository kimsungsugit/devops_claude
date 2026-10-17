import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// useToast 컨텍스트 mock — ProjectSetupSection은 toast prop이 아닌 useToast()로 토스트를 얻는다.
const mockToast = vi.fn();
vi.mock('../App.jsx', () => ({ useToast: () => mockToast }));

// fetch mock — ProjectSetupSection은 직접 fetch를 사용한다
globalThis.fetch = vi.fn();

// (R97 리뷰3 W1) 실서버 오류 본문 = 전역 핸들러 봉투(`backend/error_handler.py` `http_exception_handler`).
//   예전 mock 은 FastAPI 기본 `{detail:{…}}` 이라 실서버에서 사유 · 표지가 사라지는 결함을 못 봤다. 봉투 키는 백엔드 계약 시험
//   (`tests/unit/test_project_maps.py::TestSetupErrorEnvelope`)이 같은 이름으로 고정한다.
const envelope = (status, message, detail) => ({
  ok: false, error: { code: `HTTP_${status}`, message, ...(detail ? { detail } : {}) },
});
const errRes = (status, statusText, body) => ({
  ok: false, status, statusText,
  text: () => Promise.resolve(JSON.stringify(body)),
  json: () => Promise.resolve(body),
});
const statusOk = () => ({ ok: true, json: () => Promise.resolve({ component_map: { exists: false }, override: { exists: false } }) });

const { default: ProjectSetupSection } = await import('../components/sections/ProjectSetupSection.jsx');

describe('ProjectSetupSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // 기본 상태 API 응답
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        component_map: { exists: false },
        override: { exists: false },
      }),
    });
  });

  // STS-PROJSETUP-001: 기본 렌더링
  it('렌더링: 프로젝트 설정 제목이 표시된다', async () => {
    // Arrange & Act
    render(<ProjectSetupSection toast={mockToast} />);

    // Assert
    expect(screen.getByText(/프로젝트 설정/)).toBeInTheDocument();
    expect(screen.getByText(/ISO 26262/)).toBeInTheDocument();
  });

  // STS-PROJSETUP-002: Component Map 생성 섹션 렌더링
  it('렌더링: Component Map 생성 섹션이 표시된다', () => {
    // Arrange & Act
    render(<ProjectSetupSection toast={mockToast} />);

    // Assert: h4 + 버튼 두 곳에 텍스트가 있으므로 getAllByText 사용
    const mapMatches = screen.getAllByText(/Component Map 생성/);
    expect(mapMatches.length).toBeGreaterThanOrEqual(1);
    // SDS 기반 텍스트도 여러 곳에 있을 수 있다
    const sdsMatches = screen.getAllByText(/SDS 기반/);
    expect(sdsMatches.length).toBeGreaterThanOrEqual(1);
  });

  // STS-PROJSETUP-003: Override Map 생성 섹션 렌더링
  it('렌더링: Override Map 생성 섹션이 표시된다', () => {
    // Arrange & Act
    render(<ProjectSetupSection toast={mockToast} />);

    // Assert: h4 + 버튼 두 곳에 텍스트가 있으므로 getAllByText 사용
    const matches = screen.getAllByText(/Override Map 생성/);
    expect(matches.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/레퍼런스 UDS 기반/)).toBeInTheDocument();
  });

  // STS-PROJSETUP-004: 빈 상태 — 미생성 표시
  it('빈 상태: component_map이 미생성이면 상태가 표시된다', async () => {
    // Arrange
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        component_map: { exists: false },
        override: { exists: false },
      }),
    });

    // Act
    render(<ProjectSetupSection toast={mockToast} />);

    // Assert
    await waitFor(() => {
      const ungenerated = screen.getAllByText('미생성');
      expect(ungenerated.length).toBeGreaterThanOrEqual(1);
    });
  });

  // STS-PROJSETUP-005: 생성 완료 상태 표시
  it('렌더링: component_map이 생성된 경우 개수가 표시된다', async () => {
    // Arrange
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        component_map: { exists: true, entries: 42, verify_o: 30, verify_x: 12 },
        override: { exists: true, functions: 100, with_asil: 20, swcom_count: 5 },
      }),
    });

    // Act
    render(<ProjectSetupSection toast={mockToast} />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText('42개')).toBeInTheDocument();
      expect(screen.getByText('100개')).toBeInTheDocument();
    });
  });

  // STS-PROJSETUP-006: SDS 경로 미입력 시 경고 toast
  it('인터랙션: SDS 경로 미입력 시 Component Map 생성 버튼이 경고를 표시한다', async () => {
    // Arrange
    const user = userEvent.setup();
    render(<ProjectSetupSection toast={mockToast} />);

    // Act
    const generateBtn = screen.getByText('Component Map 생성');
    await user.click(generateBtn);

    // Assert
    expect(mockToast).toHaveBeenCalledWith('warning', expect.stringContaining('SDS 경로'));
  });

  // STS-PROJSETUP-007: 레퍼런스 UDS 경로 미입력 시 경고 toast
  it('인터랙션: UDS 경로 미입력 시 Override Map 생성 버튼이 경고를 표시한다', async () => {
    // Arrange
    const user = userEvent.setup();
    render(<ProjectSetupSection toast={mockToast} />);

    // Act
    const overrideBtn = screen.getByText('Override Map 생성');
    await user.click(overrideBtn);

    // Assert
    expect(mockToast).toHaveBeenCalledWith('warning', expect.stringContaining('레퍼런스 UDS'));
  });

  // STS-PROJSETUP-008: Component Map 생성 — 입력 후 API 호출
  it('인터랙션: SDS/소스 경로 입력 후 Component Map 생성 버튼이 API를 호출한다', async () => {
    // Arrange
    const user = userEvent.setup();
    // 두 번째 fetch는 생성 결과
    globalThis.fetch
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ component_map: { exists: false }, override: { exists: false } }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ stats: { matched: 10 } }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ component_map: { exists: true, entries: 10, verify_o: 8, verify_x: 2 }, override: { exists: false } }),
      });

    render(<ProjectSetupSection toast={mockToast} />);

    const sdsInput = screen.getByPlaceholderText(/SDS 문서 경로/);
    const srcInput = screen.getByPlaceholderText(/소스 루트 경로/);

    // Act
    await user.type(sdsInput, 'D:\\docs\\SDS.docx');
    await user.type(srcInput, 'D:\\Project\\Src');
    await user.click(screen.getByText('Component Map 생성'));

    // Assert
    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/local/project-setup/generate-component-map',
        expect.objectContaining({ method: 'POST' })
      );
    });
  });

  // STS-PROJSETUP-009 (R97): override 는 어느 프로젝트의 것인지 정할 소스 루트가 있어야 한다 — 없으면 보내지 않는다
  it('인터랙션: 소스 루트 없이 Override Map 생성을 누르면 경고하고 요청하지 않는다', async () => {
    const user = userEvent.setup();
    render(<ProjectSetupSection toast={mockToast} />);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(1));   // 마운트 상태 조회

    await user.type(screen.getByPlaceholderText(/레퍼런스 UDS 경로/), 'D:\\docs\\UDS.docx');
    await user.click(screen.getByText('Override Map 생성'));

    expect(mockToast).toHaveBeenCalledWith('warning', expect.stringContaining('소스 루트'));
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  });

  // STS-PROJSETUP-010 (R97): 같은 프로젝트에 맵이 있으면(409) 확인 후 overwrite=true 로 한 번 더 보낸다
  it('인터랙션: 409 면 덮어쓰기 확인 후 overwrite=true 로 다시 요청한다', async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    globalThis.fetch
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ component_map: { exists: false }, override: { exists: false } }) })
      .mockResolvedValueOnce(errRes(409, 'Conflict', envelope(409, '프로젝트 kjpds02_pv 에 component_map 맵이 이미 있다',
        { reason_code: 'map_exists', roots_moved: false, key: 'kjpds02_pv' })))
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ method: 'structure_table', stats: { matched: 99 },
        project_map: { key: 'kjpds02_pv' } }) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ component_map: { exists: true, entries: 99, verify_o: 99, verify_x: 0 },
        override: { exists: false, status: 'none' } }) });

    render(<ProjectSetupSection toast={mockToast} />);
    await user.type(screen.getByPlaceholderText(/SDS 문서 경로/), 'D:\\docs\\SDS.docx');
    await user.type(screen.getByPlaceholderText(/소스 루트 경로/), 'C:\\Project\\Ados\\NE1AW_PORTING');
    await user.click(screen.getByText('Component Map 생성'));

    await waitFor(() => expect(mockToast).toHaveBeenCalledWith('success', expect.stringContaining('kjpds02_pv')));
    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('이미 있다'));
    expect(confirmSpy.mock.calls[0][0]).not.toContain("'루트 다시 등록'");   // roots_moved=false — 재등록 권유 없음
    const posts = globalThis.fetch.mock.calls.filter(([u]) => String(u).includes('generate-component-map'));
    expect(posts).toHaveLength(2);
    expect(posts[1][1].body.get('overwrite')).toBe('true');
    // 생성 뒤 상태는 그 소스 루트의 프로젝트로 다시 읽는다
    const statusCalls = globalThis.fetch.mock.calls.filter(([u]) => String(u).includes('project-setup/status'));
    expect(String(statusCalls.at(-1)[0])).toContain('source_root=');
    confirmSpy.mockRestore();
  });

  // STS-PROJSETUP-011 (R97): 맵이 안 걸리면 "미생성" 아래 판정 · 사유를 적는다(남의 맵만 있음 등)
  it('렌더링: 다른 프로젝트 맵만 있으면 그 판정과 사유가 보인다', async () => {
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        component_map: { exists: false, status: 'not_this_project', reason: '등록된 맵은 다른 프로젝트(hdpdm01) 것' },
        override: { exists: false, status: 'none', reason: '' },
        projects: [{ key: 'hdpdm01', scm_id: 'hdpdm01', project: 'HDPDM01',
          maps: { component_map: { status: 'applied' }, override: { status: 'applied' } } }],
      }),
    });
    render(<ProjectSetupSection toast={mockToast} />);
    await waitFor(() => expect(screen.getByText(/다른 프로젝트 맵만 있음/)).toBeInTheDocument());
    expect(screen.getByText(/HDPDM01 \(hdpdm01\)/)).toBeInTheDocument();
  });

  // STS-PROJSETUP-014 (R97 리뷰2 I-i · 리뷰3 W1): 409 의 갈래는 문구가 아니라 서버 표지(roots_moved)로 고른다 — 실서버 봉투에서
  it.each([
    ['실서버 봉투', envelope(409, 'exists', { reason_code: 'map_exists', roots_moved: true, key: 'hdpdm01' })],
    ['FastAPI 기본 detail(폴백)', { detail: { message: 'exists', reason_code: 'map_exists', roots_moved: true } }],
  ])('인터랙션: 409 의 roots_moved 표지가 있으면 문구와 무관하게 루트 재등록을 먼저 권한다 (%s)', async (_label, body) => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    globalThis.fetch
      .mockResolvedValueOnce(statusOk())
      .mockResolvedValueOnce(errRes(409, 'Conflict', body))
      .mockResolvedValue(statusOk());
    render(<ProjectSetupSection toast={mockToast} />);
    await user.type(screen.getByPlaceholderText(/SDS 문서 경로/), 'D:\\docs\\SDS.docx');
    await user.type(screen.getByPlaceholderText(/소스 루트 경로/), 'D:\\new');
    await user.click(screen.getByText('Component Map 생성'));
    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
    expect(confirmSpy.mock.calls[0][0]).toContain("'루트 다시 등록'");
    expect(confirmSpy.mock.calls[0][0]).toContain('exists');            // 서버 사유가 확인 창에 실린다
    // 확인을 거절하면 덮어쓰기 요청을 보내지 않는다
    expect(globalThis.fetch.mock.calls.filter(([u]) => String(u).includes('generate-component-map'))).toHaveLength(1);
    confirmSpy.mockRestore();
  });

  // STS-PROJSETUP-015 (R97 리뷰3 W1): 매니페스트를 못 읽은 409 는 덮어쓰기로 풀리지 않는다 — 확인 창 없이 사유를 알린다
  it('인터랙션: manifest_unreadable 409 는 덮어쓰기를 묻지 않고 사유를 알린다', async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    globalThis.fetch
      .mockResolvedValueOnce(statusOk())
      .mockResolvedValueOnce(errRes(409, 'Conflict', envelope(409, '프로젝트 hdpdm01 의 매니페스트를 읽지 못했다',
        { reason_code: 'manifest_unreadable' })))
      .mockResolvedValue(statusOk());
    render(<ProjectSetupSection toast={mockToast} />);
    await user.type(screen.getByPlaceholderText(/SDS 문서 경로/), 'D:\\docs\\SDS.docx');
    await user.type(screen.getByPlaceholderText(/소스 루트 경로/), 'D:\\Project\\Ados\\PDS64_RD');
    await user.click(screen.getByText('Component Map 생성'));
    await waitFor(() => expect(mockToast).toHaveBeenCalledWith('error', expect.stringContaining('매니페스트를 읽지 못했다')));
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(globalThis.fetch.mock.calls.filter(([u]) => String(u).includes('generate-component-map'))).toHaveLength(1);
    confirmSpy.mockRestore();
  });

  // STS-PROJSETUP-016 (R97 리뷰3 W1): 422 · 400 은 상태 줄이 아니라 서버 사유를 보인다(사용자가 고칠 곳)
  it('인터랙션: 422 면 서버 사유를 알린다', async () => {
    const user = userEvent.setup();
    globalThis.fetch
      .mockResolvedValueOnce(statusOk())
      .mockResolvedValueOnce(errRes(422, 'Unprocessable Entity', envelope(422, '레퍼런스 UDS 를 읽지 못했다(PackageNotFoundError) — .docx 인지 확인할 것',
        { reason_code: 'unreadable_document' })));
    render(<ProjectSetupSection toast={mockToast} />);
    await user.type(screen.getByPlaceholderText(/SDS 문서 경로/), 'D:\\docs\\SDS.pdf');
    await user.type(screen.getByPlaceholderText(/소스 루트 경로/), 'C:\\Project\\Ados\\NE1AW_PORTING');
    await user.click(screen.getByText('Component Map 생성'));
    await waitFor(() => expect(mockToast).toHaveBeenCalledWith('error', expect.stringContaining('.docx 인지 확인할 것')));
  });

  // STS-PROJSETUP-012 (R97 리뷰 W6): 쓰기는 관리자 전용 — 403 은 "생성 실패" 가 아니라 권한 문제라고 말한다
  it('인터랙션: 403 이면 관리자 전용이라고 알린다', async () => {
    const user = userEvent.setup();
    globalThis.fetch
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ component_map: { exists: false }, override: { exists: false } }) })
      .mockResolvedValueOnce(errRes(403, 'Forbidden', envelope(403, 'admin only')));
    render(<ProjectSetupSection toast={mockToast} />);
    await user.type(screen.getByPlaceholderText(/SDS 문서 경로/), 'D:\\docs\\SDS.docx');
    await user.type(screen.getByPlaceholderText(/소스 루트 경로/), 'C:\\Project\\Ados\\NE1AW_PORTING');
    await user.click(screen.getByText('Component Map 생성'));
    await waitFor(() => expect(mockToast).toHaveBeenCalledWith('error', expect.stringContaining('관리자만')));
  });

  // STS-PROJSETUP-013 (R97 리뷰 W7): 매니페스트 루트가 이 루트를 못 담으면 맵이 아니라 루트를 다시 등록하는 길을 보인다
  it('인터랙션: roots_moved 면 경고와 "루트 다시 등록" 이 보이고 update-roots 를 부른다', async () => {
    const user = userEvent.setup();
    const moved = {
      component_map: { exists: false, status: 'not_this_project', reason: 'r' },
      override: { exists: false, status: 'not_this_project', reason: 'r' },
      roots_moved: { key: 'hdpdm01', hint: '소스 루트가 바뀐 것이면 맵을 다시 만들지 말고 루트를 다시 등록할 것' },
      projects: [{ key: 'hdpdm01', project: 'HDPDM01', roots_covered: false, maps: {} }],
    };
    globalThis.fetch
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve(moved) })
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ key: 'hdpdm01', roots_after: ['D:/new'] }) })
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({ component_map: { exists: true, entries: 153, verify_o: 104, verify_x: 49 }, override: { exists: false } }) });
    render(<ProjectSetupSection toast={mockToast} />);
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText(/roots_covered=false/, { selector: 'div' })).toBeInTheDocument();
    await user.type(screen.getByPlaceholderText(/소스 루트 경로/), 'D:\\new');
    await user.click(screen.getByText('루트 다시 등록'));
    await waitFor(() => expect(mockToast).toHaveBeenCalledWith('success', expect.stringContaining('hdpdm01')));
    const posts = globalThis.fetch.mock.calls.filter(([u]) => String(u).includes('update-roots'));
    expect(posts).toHaveLength(1);
    expect(posts[0][1].body.get('source_root')).toBe('D:\\new');
  });
});
