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

  // STS-IMPACT-009: coverage_gap(MC/DC delta)이 있으면 커버리지 요약 카드 표시
  it('렌더링: coverage_gap이 있으면 커버리지(ASIL 타깃 대비) 요약 카드가 표시된다', () => {
    // Arrange
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { foo: 'BODY' },
        actions: {},
        impact: { direct: ['foo'] },
        coverage_gap: {
          available: true,
          functions: [{ function: 'foo', asil: 'D', target_metric: 'mcdc', current_rate: 0.85, meets_target: false, delta: -0.1 }],
          summary: { evaluated: 1, below_target: 1, regressed: 1, had_baseline: true },
        },
      },
    };

    // Act
    render(<ImpactGuideSection job={mockJob} analysisResult={analysisResult} />);

    // Assert: 커버리지 카드 + 미달/회귀 통계
    expect(screen.getByText(/커버리지 \(ASIL 타깃 대비\)/)).toBeInTheDocument();
    expect(screen.getByText(/목표 미달/)).toBeInTheDocument();
    expect(screen.getByText(/직전 대비 회귀/)).toBeInTheDocument();
  });

  // STS-IMPACT-010: impact.asil(ASIL 차등) 요약이 결정론적으로 표면화된다
  it('렌더링: impact.asil이 있으면 ASIL 차등 검증 strip(escalation·MC/DC·미상)이 표시된다', () => {
    // Arrange
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { foo: 'BODY' },
        actions: {},
        impact: { direct: ['foo'] },
        asil: { max_changed: 'D', escalation: true, mcdc_required: true, coverage_target: 'MC/DC', unknown_changed_count: 2 },
      },
    };

    // Act
    render(<ImpactGuideSection job={mockJob} analysisResult={analysisResult} />);

    // Assert: ASIL 차등 strip + escalation/MC/DC/미상 표면화
    expect(screen.getByText(/ASIL 차등 검증/)).toBeInTheDocument();
    expect(screen.getByText(/Escalation/)).toBeInTheDocument();
    expect(screen.getByText(/MC\/DC 필수/)).toBeInTheDocument();
    expect(screen.getByText(/ASIL 미상 2개/)).toBeInTheDocument();
  });

  // STS-IMPACT-011: regression_test_set(회귀시험 선정) 카드가 표시된다
  it('렌더링: regression_test_set이 있으면 회귀시험 선정 카드(SUTS TC/SITS 체인)가 표시된다', () => {
    // Arrange
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { foo: 'BODY' },
        actions: {},
        impact: { direct: ['foo'] },
        regression_test_set: {
          suts: { foo: ['TC_001', 'TC_002'] },
          sits: { foo: ['CHAIN_A'] },
          summary: { suts_tc_count: 2, sits_chain_count: 1, impacted_function_count: 1, coverage_target: 'MC/DC', mcdc_required: true },
        },
      },
    };

    // Act
    render(<ImpactGuideSection job={mockJob} analysisResult={analysisResult} />);

    // Assert: 회귀 카드 + 재실행 대상 통계 + 함수별 TC ("재실행 TC"는 stat-card·breakdown 헤더 양쪽 존재)
    expect(screen.getByText(/회귀시험 선정/)).toBeInTheDocument();
    expect(screen.getByText(/SUTS 재실행 TC \(함수별\)/)).toBeInTheDocument();
    expect(screen.getByText(/SITS 영향 체인/)).toBeInTheDocument();
    expect(screen.getByText('TC_001')).toBeInTheDocument();
  });

  // STS-IMPACT-012: 간접 영향(1/2hop) 함수가 가이드 표에 포함된다(죽은 hop 필터 복구, ISO 26262 under-report fix)
  it('가이드: 간접 영향 함수(1-hop)가 함수별 영향 가이드 표에 포함된다', async () => {
    // Arrange: 직접 변경 1개 + 간접 1-hop 1개
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false }); // ai-guide는 스킵(linkedDocs 없어 매핑 fetch도 스킵)
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { g_Changed: 'BODY' },
        actions: {},
        impact: { direct: ['g_Changed'], indirect_1hop: ['s_Indirect'], indirect_2hop: [] },
        function_meta: { g_Changed: { asil: 'D' }, s_Indirect: { asil: 'C' } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);

    // Act: 상세 가이드 생성
    await user.click(screen.getByText(/상세 가이드 생성/));

    // Assert: 가이드 표에 직접(1)+간접(1)=2개, 간접 함수 s_Indirect가 표에 노출된다.
    // (과거엔 변경 함수만 순회 → 간접 함수 누락 + 1-hop 필터 영구 0건)
    await waitFor(() => {
      expect(screen.getByText(/함수별 영향 가이드 \(2개\)/)).toBeInTheDocument();
    });
    // s_Indirect는 '변경 상세'엔 없고 '영향 가이드' 표에만 존재 → 유일 매칭
    expect(screen.getByText('s_Indirect')).toBeInTheDocument();
  });

  // STS-IMPACT-013: classification.granularity='file'이면 "변경 함수" 과대추정 정직화 라벨 노출
  it('렌더링: classification.granularity=file이면 (보수 추정) 캡션과 안내가 표시된다', () => {
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { foo: 'BODY', bar: 'BODY' },
        actions: {},
        impact: { direct: ['foo', 'bar'] },
        classification: { granularity: 'file', source: 'svn_revision_range', signature_distinguished: false },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    // "변경 함수" stat 라벨의 (보수 추정) 캡션 + 변경 상세 패널의 파일단위 안내
    expect(screen.getByText(/\(보수 추정\)/)).toBeInTheDocument();
    expect(screen.getByText(/파일단위 보수 분류/)).toBeInTheDocument();
  });

  // STS-IMPACT-014: granularity='line'이면 정직화 라벨 미노출(정밀 분류)
  it('렌더링: classification.granularity=line이면 (보수 추정) 캡션이 없다', () => {
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { foo: 'SIGNATURE' },
        actions: {},
        impact: { direct: ['foo'] },
        classification: { granularity: 'line', source: '', signature_distinguished: true },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    expect(screen.queryByText(/\(보수 추정\)/)).not.toBeInTheDocument();
    expect(screen.queryByText(/파일단위 보수 분류/)).not.toBeInTheDocument();
  });
});
