import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock api.js
vi.mock('../api.js', () => ({
  post: vi.fn(),
  api: vi.fn(),
  getInitialTheme: () => 'light',
  saveTheme: vi.fn(),
  loadJenkinsConfig: () => ({}),
  saveJenkinsConfig: vi.fn(),
  getUsername: () => 'testuser',
  setUsername: vi.fn(),
  defaultCacheRoot: vi.fn(() => ''),
}));

// Mock App.jsx contexts
vi.mock('../App.jsx', () => ({
  useJenkinsCfg: vi.fn(() => ({
    cfg: {
      baseUrl: 'http://jenkins.example.com',
      username: 'admin',
      token: 'token123',
      cacheRoot: '.devops_pro_cache',
      buildSelector: 'lastSuccessfulBuild',
      verifyTls: true,
    },
    update: vi.fn(),
  })),
  useToast: vi.fn(() => vi.fn()),
}));

// localStorage mock
const localStorageMock = (() => {
  let store = {};
  return {
    getItem: vi.fn((k) => store[k] ?? null),
    setItem: vi.fn((k, v) => { store[k] = String(v); }),
    removeItem: vi.fn((k) => { delete store[k]; }),
    clear: vi.fn(() => { store = {}; }),
  };
})();
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

// fetch mock for SCM list, file-mode
globalThis.fetch = vi.fn(() =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve([]),
  })
);

const { default: Settings } = await import('../views/Settings.jsx');

describe('Settings', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageMock.clear();
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    });
  });

  // STS-SETTINGS-001: Settings 컴포넌트 렌더링
  it('렌더링: settings-layout 컨테이너가 존재한다', () => {
    // Arrange & Act
    const { container } = render(<Settings />);

    // Assert
    expect(container.querySelector('.settings-layout')).toBeInTheDocument();
  });

  // STS-SETTINGS-002: Jenkins 섹션 노출
  it('렌더링: Jenkins 연결 섹션 타이틀이 표시된다', () => {
    // Arrange & Act
    render(<Settings />);

    // Assert
    expect(screen.getByText(/Jenkins 연결/)).toBeInTheDocument();
  });

  // STS-SETTINGS-003: SCM 레지스트리 섹션 노출
  it('렌더링: SCM 레지스트리 섹션이 표시된다', () => {
    // Arrange & Act
    render(<Settings />);

    // Assert
    expect(screen.getByText(/SCM 레지스트리/)).toBeInTheDocument();
  });

  // STS-SETTINGS-004: 입력 자료 설정 섹션 노출 (문서+템플릿+로그 일원화)
  it('렌더링: 입력 자료 설정 섹션이 표시된다', () => {
    // Arrange & Act
    render(<Settings />);

    // Assert
    expect(screen.getByText(/입력 자료 설정/)).toBeInTheDocument();
  });

  // STS-SETTINGS-005: 품질 기준 섹션 노출
  it('렌더링: 품질 기준 섹션이 표시된다', () => {
    // Arrange & Act
    render(<Settings />);

    // Assert
    expect(screen.getByText(/품질 기준/)).toBeInTheDocument();
  });

  // STS-SETTINGS-006: 관리자 모드 섹션 노출
  it('렌더링: 관리자 모드 섹션이 표시된다', () => {
    // Arrange & Act
    render(<Settings />);

    // Assert: 관리자 모드 텍스트가 하나 이상 존재한다 (타이틀 + 버튼 등 중복 허용)
    const matches = screen.getAllByText(/관리자 모드/);
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });

  // STS-SETTINGS-007: SCM 빈 상태 메시지
  it('빈 상태: SCM 목록이 없을 때 안내 메시지가 표시된다', async () => {
    // Arrange
    globalThis.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve([]),
    });

    // Act
    render(<Settings />);

    // Assert
    await waitFor(() => {
      expect(screen.getByText(/등록된 SCM이 없습니다/)).toBeInTheDocument();
    });
  });

  // STS-SETTINGS-008: 연결 테스트 버튼 인터랙션
  it('인터랙션: 연결 테스트 버튼이 클릭 가능하다', async () => {
    // Arrange
    const user = userEvent.setup();
    const { post: mockPost } = await import('../api.js');
    mockPost.mockResolvedValue({ ok: true });

    render(<Settings />);

    // Act
    const testBtn = screen.getByText('연결 테스트');
    await user.click(testBtn);

    // Assert
    expect(mockPost).toHaveBeenCalledWith('/api/jenkins/jobs', expect.any(Object));
  });

  // STS-SETTINGS-009: SCM 새 등록 폼 토글
  it('인터랙션: 새 SCM 등록 버튼 클릭 시 폼이 표시된다', async () => {
    // Arrange
    const user = userEvent.setup();
    render(<Settings />);

    // Act
    const addBtn = screen.getByText('+ 새 SCM 등록');
    await user.click(addBtn);

    // Assert
    expect(screen.getByPlaceholderText('my-project')).toBeInTheDocument();
  });
});
