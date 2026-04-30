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
    expect(screen.getByText('세부 데이터')).toBeInTheDocument();
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

    // '설정'은 admin-only라 기본 탭 집합에 없음 → '세부 데이터'로 대체
    await user.click(screen.getByText('세부 데이터'));
    expect(screen.getByText('세부 데이터')).toHaveClass('active');
    expect(screen.getByText('대시보드')).not.toHaveClass('active');
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
