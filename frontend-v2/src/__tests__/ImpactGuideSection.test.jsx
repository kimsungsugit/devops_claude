import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock api.js
vi.mock('../api.js', () => ({
  post: vi.fn(),
  api: vi.fn(),
  defaultCacheRoot: vi.fn(() => '.devops_cache'),
}));

// Mock App.jsx contexts
vi.mock('../App.jsx', () => ({
  useJenkinsCfg: vi.fn(() => ({
    cfg: {
      username: 'admin',
      token: 'token123',
      cacheRoot: '.devops_pro_cache',
      buildSelector: 'lastSuccessfulBuild',
    },
  })),
  useToast: vi.fn(() => vi.fn()),
}));

// Mock StatusBadge
vi.mock('../components/StatusBadge.jsx', () => ({
  default: ({ children, tone }) => (
    <span data-testid="status-badge" data-tone={tone}>{children}</span>
  ),
}));

const { default: ImpactGuideSection } = await import('../components/sections/ImpactGuideSection.jsx');

describe('ImpactGuideSection', () => {
  const mockJob = { url: 'http://jenkins.example.com/job/test-job/' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  // STS-IMPACT-001: impact 없을 때 빈 상태 empty-state 렌더링
  it('빈 상태: analysisResult가 없으면 empty-state 안내가 표시된다', () => {
    // Arrange & Act
    render(<ImpactGuideSection job={mockJob} analysisResult={null} />);

    // Assert: impact 없으면 empty-state UI가 표시된다
    expect(screen.getByText(/변경 영향도 분석 결과가 없습니다/)).toBeInTheDocument();
  });

  // STS-IMPACT-002: impact 없을 때 데모 시나리오 버튼 표시
  it('빈 상태: 데모 시나리오 버튼이 표시된다', () => {
    // Arrange & Act
    render(<ImpactGuideSection job={mockJob} analysisResult={null} />);

    // Assert
    expect(screen.getByText(/데모 시나리오로 보기/)).toBeInTheDocument();
  });

  // STS-IMPACT-003: impact가 있으면 요약 패널이 렌더링된다
  it('렌더링: impactData가 있으면 변경 영향도 요약 패널이 표시된다', () => {
    // Arrange
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap_MotorCtrl.c', 'DrvIn_Main_PDS.c'] },
        changed_function_types: {
          'g_DrvIn_Main': 'BODY',
          'g_MotorCtrl': 'SIGNATURE',
        },
        actions: {},
        impact: { direct: ['g_DrvIn_Main'], indirect_1hop: [], indirect_2hop: [] },
      },
    };

    // Act
    render(<ImpactGuideSection job={mockJob} analysisResult={analysisResult} />);

    // Assert: 요약 패널이 표시된다
    expect(screen.getByText(/변경 영향도 요약/)).toBeInTheDocument();
  });

  // STS-IMPACT-004: impact가 있으면 변경 파일 수가 stat-card에 표시된다
  it('렌더링: impactData가 있으면 변경 파일 수가 표시된다', () => {
    // Arrange
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap_MotorCtrl.c', 'DrvIn_Main_PDS.c'] },
        changed_function_types: { 'g_DrvIn_Main': 'BODY' },
        actions: {},
        impact: {},
      },
    };

    // Act
    render(<ImpactGuideSection job={mockJob} analysisResult={analysisResult} />);

    // Assert: 변경 파일 2개가 stat-value에 표시된다
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('변경 파일')).toBeInTheDocument();
  });

  // STS-IMPACT-005: 데모 모드 토글 — 빈 상태에서 버튼 클릭 후 요약 패널 표시
  it('인터랙션: 데모 시나리오 버튼 클릭 시 요약 패널이 표시된다', async () => {
    // Arrange
    const user = userEvent.setup();
    render(<ImpactGuideSection job={mockJob} analysisResult={null} />);

    // Act
    const demoBtn = screen.getByText(/데모 시나리오로 보기/);
    await user.click(demoBtn);

    // Assert: 데모 모드가 활성화되어 요약 패널이 나타난다
    await waitFor(() => {
      expect(screen.getByText(/변경 영향도 요약/)).toBeInTheDocument();
    });
  });

  // STS-IMPACT-006: 상세 가이드 생성 버튼 노출
  it('렌더링: impact가 있으면 상세 가이드 생성 버튼이 표시된다', () => {
    // Arrange
    const analysisResult = {
      impactData: {
        trigger: { changed_files: [] },
        changed_function_types: {},
        actions: {},
        impact: {},
      },
    };

    // Act
    render(<ImpactGuideSection job={mockJob} analysisResult={analysisResult} />);

    // Assert
    expect(screen.getByText(/상세 가이드 생성/)).toBeInTheDocument();
  });

  // STS-IMPACT-007: 추적성 매트릭스 연동 — 영향 함수 집합을 focus로 저장하고 srssds로 이동
  it('인터랙션: "추적성 매트릭스에서 보기" 클릭 시 영향 함수 focus 저장 + srssds 이동', async () => {
    // Arrange
    const user = userEvent.setup();
    window.__detailSection = vi.fn();
    localStorage.removeItem('devops_v2_trace_focus');
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { g_DrvIn_Main: 'BODY', g_MotorCtrl: 'SIGNATURE' },
        actions: {},
        impact: { direct: ['g_DrvIn_Main'], indirect_1hop: ['s_Helper'], indirect_2hop: [] },
      },
    };
    render(<ImpactGuideSection job={mockJob} analysisResult={analysisResult} />);

    // Act
    await user.click(screen.getByText(/추적성 매트릭스에서 보기/));

    // Assert: srssds로 이동 + 영향 함수(직접+간접+변경)가 focus에 저장
    expect(window.__detailSection).toHaveBeenCalledWith('srssds');
    const stored = JSON.parse(localStorage.getItem('devops_v2_trace_focus'));
    expect(stored.functions).toEqual(expect.arrayContaining(['g_DrvIn_Main', 'g_MotorCtrl', 's_Helper']));
    delete window.__detailSection;
  });

  // STS-IMPACT-008: backend 경고(과소보고/ASIL escalation 등)가 경고 카드로 표면화
  it('렌더링: backend warnings가 영향 탭 경고 카드로 표시된다', () => {
    // Arrange
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { foo: 'BODY' },
        actions: {},
        impact: { direct: ['foo'] },
        warnings: [
          'cloudium: source index empty (worker read may have failed) — impact may be under-reported',
          'ASIL escalation: 직접 변경에 ASIL D 함수 포함',
        ],
      },
    };

    // Act
    render(<ImpactGuideSection job={mockJob} analysisResult={analysisResult} />);

    // Assert: 경고 카드 + 개별 경고 노출
    expect(screen.getByText(/분석 경고/)).toBeInTheDocument();
    expect(screen.getByText(/under-reported/)).toBeInTheDocument();
    expect(screen.getByText(/ASIL escalation/)).toBeInTheDocument();
  });
});
