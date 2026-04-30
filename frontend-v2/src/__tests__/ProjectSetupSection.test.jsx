import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// fetch mock — ProjectSetupSection은 직접 fetch를 사용한다
globalThis.fetch = vi.fn();

const { default: ProjectSetupSection } = await import('../components/sections/ProjectSetupSection.jsx');

describe('ProjectSetupSection', () => {
  const mockToast = vi.fn();

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
});
