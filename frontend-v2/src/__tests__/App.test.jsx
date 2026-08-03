import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock api.js before importing App
vi.mock('../api.js', () => ({
  getInitialTheme: () => 'light',
  saveTheme: vi.fn(),
  loadJenkinsConfig: () => ({}),
  saveJenkinsConfig: vi.fn(),
  getUsername: () => 'testuser',
  setUsername: vi.fn(),
  fetchServerJenkinsConfig: () => Promise.resolve(null),
  saveServerJenkinsConfig: vi.fn(() => Promise.resolve({ ok: true })),
}));

// Mock child views to keep tests focused
vi.mock('../views/Dashboard.jsx', () => ({
  default: () => <div data-testid="dashboard">Dashboard</div>,
}));
vi.mock('../views/Detail.jsx', () => ({
  default: () => <div data-testid="detail">Detail</div>,
}));
vi.mock('../views/Settings.jsx', () => ({
  default: () => <div data-testid="settings">Settings</div>,
}));
// Quality 뷰는 **마운트 여부 자체**가 검증 대상이라 스파이를 둔다.
// 예전엔 4뷰가 전부 항상 마운트돼, 보이지도 않는 Quality 의 mount effect 가
// admin 전용 endpoint 를 때려 비관리자에게 매 로드마다 403 토스트가 떴다.
const qualityMountSpy = vi.fn();
vi.mock('../views/QualityDashboard.jsx', () => ({
  default: () => {
    qualityMountSpy();
    return <div data-testid="quality">Quality</div>;
  },
}));

// Mock fetch for health check
globalThis.fetch = vi.fn(() => Promise.resolve({
  ok: true,
  json: () => Promise.resolve({ status: 'ok', version: '1.0' }),
}));

const { default: App } = await import('../App.jsx');

describe('App', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    document.body.removeAttribute('data-theme');
  });

  it('renders header with brand name', () => {
    render(<App />);
    expect(screen.getByText('ARIA')).toBeInTheDocument();
  });

  it('renders all tab buttons', () => {
    render(<App />);
    expect(screen.getByText('대시보드')).toBeInTheDocument();
    expect(screen.getByText('프로젝트 결과')).toBeInTheDocument();
    // '설정' 탭은 관리자 전용 — 기본(비관리자)에서는 숨김
    expect(screen.queryByText('설정')).not.toBeInTheDocument();
  });

  it('shows dashboard tab as active by default', () => {
    render(<App />);
    const dashboardTab = screen.getByText('대시보드');
    expect(dashboardTab).toHaveClass('active');
  });

  it('switches tabs on click', async () => {
    const user = userEvent.setup();
    render(<App />);

    // '설정'은 admin-only라 기본 탭 집합에 없음 → '프로젝트 결과'로 대체
    await user.click(screen.getByText('프로젝트 결과'));
    expect(screen.getByText('프로젝트 결과')).toHaveClass('active');
    expect(screen.getByText('대시보드')).not.toHaveClass('active');
  });

  describe('탭 lazy 마운트 (안 열어 본 뷰는 요청하지 않는다)', () => {
    it('처음 렌더에서 Quality 뷰를 마운트하지 않는다', () => {
      render(<App />);
      // 예전엔 여기서 마운트돼 `/api/quality/*` 로 403 을 받고
      // 빨간 '데이터 로드 실패' 패널 + 에러 토스트가 떴다 — 사용자는 아무것도 안 눌렀다.
      expect(qualityMountSpy).not.toHaveBeenCalled();
      expect(screen.queryByTestId('quality')).not.toBeInTheDocument();
    });

    it('안 열어 본 다른 탭(설정)도 마운트하지 않는다', () => {
      render(<App />);
      expect(screen.queryByTestId('settings')).not.toBeInTheDocument();
    });

    it('한 번 연 탭은 벗어나도 마운트를 유지한다 (keep-alive)', async () => {
      const user = userEvent.setup();
      render(<App />);

      await user.click(screen.getByText('프로젝트 결과'));
      expect(screen.getByTestId('detail')).toBeInTheDocument();

      await user.click(screen.getByText('대시보드'));
      // 언마운트되면 오래 걸려 얻은 결과(커버리지·영향 가이드 등)가 날아간다.
      expect(screen.getByTestId('detail')).toBeInTheDocument();
      expect(screen.getByTestId('detail').parentElement).toHaveStyle({ display: 'none' });
    });
  });

  it('toggles theme on button click', async () => {
    const user = userEvent.setup();
    render(<App />);
    const themeBtn = screen.getByTitle('테마 전환');

    await user.click(themeBtn);
    expect(document.body.getAttribute('data-theme')).toBe('dark');

    await user.click(themeBtn);
    expect(document.body.getAttribute('data-theme')).toBe('light');
  });
});
