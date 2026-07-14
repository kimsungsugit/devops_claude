import { render, screen, waitFor, within } from '@testing-library/react';
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

const { default: ImpactGuideSection, extractDiffElements, buildDocumentActions } = await import('../components/sections/ImpactGuideSection.jsx');

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
      expect(screen.getByText(/함수별 상세 \(2\)/)).toBeInTheDocument();
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
        classification: { granularity: 'line', source: '', signature_distinguished: true, line_classified_file_count: 2, narrow_removed_count: 5 },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    expect(screen.queryByText(/\(보수 추정\)/)).not.toBeInTheDocument();
    expect(screen.queryByText(/파일단위 보수 분류/)).not.toBeInTheDocument();
    // 정밀 분류 긍정 신호 노출
    expect(screen.getByText('정밀')).toBeInTheDocument();
  });

  // STS-IMPACT-015: 상세 모달 — SIGNATURE 함수의 매개변수 변화(추가) diff 표시
  it('상세 모달: SIGNATURE 함수 상세 클릭 시 매개변수 변화 diff와 원문이 모달로 뜬다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { foo: 'SIGNATURE' },
        actions: {},
        impact: { direct: ['foo'] },
        function_meta: { foo: { asil: 'B' } },
        // A(svn diff)가 채운 before/after 선언 원문 — 매개변수 diff 근거
        change_details: { foo: { before: 'int foo(int a)', after: 'int foo(int a, int b)' } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText(/함수별 상세/)).toBeInTheDocument());
    // 가이드 표의 '상세' 버튼(정확 매칭 — '상세 가이드 생성'과 구분)
    await user.click(screen.getByRole('button', { name: '상세' }));
    // 모달: 매개변수 변화 섹션 + '추가'(매개변수 pill + 문서 액션 다중) + 변경 후 원문
    expect(screen.getByText(/시그니처·매개변수 변화/)).toBeInTheDocument();
    expect(screen.getAllByText(/추가/).length).toBeGreaterThan(0);  // 매개변수 diff pill + 문서 액션
    // 문서별 구체 액션 카드 — SITS 포함 5문서 + 실제 파라미터명(int b) 액션에 반영(결정론)
    expect(screen.getByText(/SITS 검토/)).toBeInTheDocument();
    expect(screen.getAllByText(/int b/).length).toBeGreaterThanOrEqual(2);  // 요약 뱃지+테이블+문서 액션
    // 변경 후 원문(변경상세 패널 + 모달 접기 양쪽 노출 — 최소 1개 이상)
    expect(screen.getAllByText(/int foo\(int a, int b\)/).length).toBeGreaterThanOrEqual(1);
    // AI 설명 버튼 노출
    expect(screen.getByRole('button', { name: /AI로 설명 생성/ })).toBeInTheDocument();
  });

  // STS-IMPACT-017: 목록 '변경 상세' 셀 — SIGNATURE는 원문 raw 대신 매개변수 요약 뱃지(＋int b)
  it('변경 상세 셀: SIGNATURE는 매개변수 요약 뱃지로 표시된다(원문 raw 아님)', () => {
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { foo: 'SIGNATURE' },
        impact: { direct: ['foo'] },
        function_meta: { foo: { asil: 'B' } },
        change_details: { foo: { before: 'int foo(int a)', after: 'int foo(int a, int b)' } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    // '변경 상세' 패널은 가이드 생성 없이 항상 렌더 — 셀에 '＋int b' 요약 뱃지가 뜬다
    expect(screen.getAllByText('＋int b').length).toBeGreaterThanOrEqual(1);
  });

  // STS-IMPACT-016: 함수포인터 매개변수(내부 콤마) — depth 인식 분할로 콜백만 변경 표시(flag 오보고 없음)
  it('상세 모달: 함수포인터 파라미터의 내부 콤마를 오분할하지 않는다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { reg: 'SIGNATURE' },
        actions: {},
        impact: { direct: ['reg'] },
        function_meta: { reg: { asil: 'B' } },
        change_details: { reg: {
          before: 'void reg(void (*cb)(int,int), int flag)',
          after: 'void reg(void (*cb)(int,int,int), int flag)',
        } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText(/함수별 상세/)).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: '상세' }));
    // 콜백 param(내부 콤마 포함)이 하나로 파싱돼 변경행에 노출 — flag는 불변이라 추가/삭제 행 없음
    expect(screen.getAllByText(/void \(\*cb\)\(int,int,int\)/).length).toBeGreaterThanOrEqual(1);
    // flag가 '추가'/'삭제' pill과 함께 오보고되지 않음(변화 없는 매개변수)
    expect(screen.queryByText('추가')).not.toBeInTheDocument();
    expect(screen.queryByText('삭제')).not.toBeInTheDocument();
  });

  // STS-IMPACT-018: 배열 파라미터 앞 삽입 — 이름 매칭으로 삽입분만 '추가'(Critical #1 회귀 방지)
  it('상세 모달: 배열 파라미터 앞 삽입 시 삽입분만 추가로 귀속(위치 오귀속 없음)', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { s_CopyBuf: 'SIGNATURE' },
        impact: { direct: ['s_CopyBuf'] },
        function_meta: { s_CopyBuf: { asil: 'B' } },
        // change_details 키는 소문자(백엔드 .lower() 관례)
        change_details: { s_copybuf: {
          before: 'void s_CopyBuf(U8 src[8], U8 dst[8])',
          after: 'void s_CopyBuf(U8 len, U8 src[8], U8 dst[8])',
        } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText(/함수별 상세/)).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: '상세' }));
    // 삽입된 'U8 len'만 추가 뱃지로 귀속 — 배열 src/dst는 이름 매칭돼 오귀속되지 않음
    expect(screen.getAllByText('＋U8 len').length).toBeGreaterThanOrEqual(1);
    // 위치 강등 증상(기존 배열 파라미터가 '변경'으로 오보고)이 없음
    expect(screen.queryByText(/U8 src\[8\].*→.*U8 len/)).not.toBeInTheDocument();
  });

  // STS-IMPACT-019: 이름 매칭 불가 매개변수(함수포인터) → 위치 추정 경고 배너 노출
  it('상세 모달: 이름 매칭 불가 매개변수는 위치 추정 경고 배너를 표시한다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { reg2: 'SIGNATURE' },
        impact: { direct: ['reg2'] },
        function_meta: { reg2: { asil: 'B' } },
        change_details: { reg2: {
          before: 'void reg2(void (*cb)(int))',
          after: 'void reg2(void (*cb)(int), int flag)',
        } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText(/함수별 상세/)).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: '상세' }));
    // 위치 추정 경고 배너(모달 시그니처 섹션)
    expect(screen.getByText('위치 기반')).toBeInTheDocument();
  });

  // STS-IMPACT-020: 함수별 영향 가이드 리스트 — 모달 열기 전에도 변경 유형+파라미터 요약 표시
  it('가이드 리스트: 모달 열기 전에도 변경 유형과 파라미터 변화가 표시된다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { foo: 'SIGNATURE', gone: 'DELETE' },
        impact: { direct: ['foo', 'gone'] },
        function_meta: { foo: { asil: 'B' }, gone: { asil: 'A' } },
        change_details: { foo: { before: 'int foo(int a)', after: 'int foo(int a, int b)' } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText(/함수별 상세/)).toBeInTheDocument());
    // 리스트 셀에 유형 뱃지(시그니처/삭제)와 SIGNATURE 파라미터 요약(＋int b) — 상세 클릭 없이
    expect(screen.getAllByText('시그니처').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('삭제').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('＋int b').length).toBeGreaterThanOrEqual(1);
  });

  // STS-IMPACT-021: VARIABLE 함수 + function_diffs → 문서 카드에 실제 전역 변수명·Used Globals 표시
  it('상세 모달: VARIABLE 함수는 본문 diff의 실제 전역 변수를 문서 카드에 구체 표시한다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { g_reset: 'VARIABLE' },
        impact: { direct: ['g_reset'] },
        function_meta: { g_reset: { asil: 'A' } },
        // function_diffs 키는 소문자(백엔드 extract_function_diffs 규약)
        function_diffs: { g_reset: [
          '@@ -10,5 +10,2 @@ void g_reset(void)',
          '-#ifdef TESTCODE_FOR_VEHICLE',
          '-    u8g_ApiIn_LinRx_AsstVentilationLevel = u8g_VENTILATION_OFF;',
          '-#endif',
        ].join('\n') },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText(/함수별 상세/)).toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: '상세' }));
    // UDS 카드에 실제 전역 변수명 + Used Globals 섹션(결정론 구체화)
    expect(screen.getAllByText(/u8g_ApiIn_LinRx_AsstVentilationLevel/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/Used Globals/).length).toBeGreaterThanOrEqual(1);
    // SITS 카드에 'Data Flow' 섹션 라벨 없음(정정 확인)
    expect(screen.queryByText('Data Flow')).not.toBeInTheDocument();
  });

  // STS-IMPACT-022: 무정보 BODY(function_diff·change_details 둘 다 없음) — 파일영향 정직 표시
  it('상세 모달: 직접 변경 증거 없는 BODY는 "파일영향"으로 표시하고 본문 변경 단정 안 함', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { g_getter: 'BODY' },
        impact: { direct: ['g_getter'] },
        function_meta: { g_getter: { asil: 'A' } },
        // change_details·function_diffs 둘 다 없음 (파일 단위 보수 fatten)
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText(/함수별 상세/)).toBeInTheDocument());
    expect(screen.getAllByText('파일영향').length).toBeGreaterThanOrEqual(1);  // 리스트 칩
    await user.click(screen.getByRole('button', { name: '상세' }));
    // 직접 변경 감지 안 됨 안내 + 본문 변경 단정 없음 + 본문 원문 없음 안내
    expect(screen.getByText(/직접 변경\(hunk\/선언\)은 감지되지 않았습니다/)).toBeInTheDocument();
    expect(screen.queryByText(/함수 본문\(로직\)이 변경되었습니다/)).not.toBeInTheDocument();
    expect(screen.getByText(/본문 변경 원문 없음/)).toBeInTheDocument();
  });

  // STS-IMPACT-023: hunk 있는 BODY(function_diffs 있음) — 기존 단정 유지, 파일영향 없음(과발화 가드)
  it('상세 모달: 본문 diff 있는 BODY는 기존 "본문 변경" 단정 유지, 파일영향 칩 없음', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { g_real: 'BODY' },
        impact: { direct: ['g_real'] },
        function_meta: { g_real: { asil: 'A' } },
        function_diffs: { g_real: '@@ -1,2 +1,2 @@ void g_real(void)\n-    x = 1;\n+    x = 2;' },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText(/함수별 상세/)).toBeInTheDocument());
    expect(screen.queryByText('파일영향')).not.toBeInTheDocument();  // hunk 있음 → 칩 없음
    await user.click(screen.getByRole('button', { name: '상세' }));
    expect(screen.getByText(/함수 본문\(로직\)이 변경되었습니다/)).toBeInTheDocument();  // 기존 단정 유지
    expect(screen.queryByText(/직접 변경\(hunk\/선언\)은 감지되지 않았습니다/)).not.toBeInTheDocument();
  });

  // STS-IMPACT-024: 변경 상세 집계 — 파일영향(무정보 BODY)은 기본 숨김, 토글로 표시/집계 분리
  it('변경 상세 집계: 파일영향(무정보 BODY)은 기본 숨김이고 토글로 표시/집계 분리된다', async () => {
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        // g_real=증거 있음(function_diffs), g_getter1/2=무정보(fd·cd 둘 다 없음)
        changed_function_types: { g_real: 'BODY', g_getter1: 'BODY', g_getter2: 'BODY' },
        impact: { direct: ['g_real', 'g_getter1', 'g_getter2'] },
        function_meta: {},
        function_diffs: { g_real: '@@ -1,2 +1,2 @@ void g_real(void)\n-    x = 1;\n+    x = 2;' },
        classification: { granularity: 'line', line_classified_file_count: 1 },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    // 기본: 파일영향 2개 숨김 — 토글 버튼(상단+변경상세)·숨김 캡션·스탯 부기(변경함수+직접영향) 노출
    expect(screen.getAllByRole('button', { name: /파일영향 2개 보기/ }).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/파일영향 2개 숨김/)).toBeInTheDocument();
    expect(screen.getAllByText('+2 파일영향').length).toBeGreaterThanOrEqual(1);   // 스탯 부기(집계 분리)
    expect(screen.queryByText('g_getter1')).not.toBeInTheDocument();
    expect(screen.queryByText('g_getter2')).not.toBeInTheDocument();
    expect(screen.getByText('g_real')).toBeInTheDocument();
    // 토글 → 무정보 함수 표시, 버튼 라벨 전환
    await user.click(screen.getAllByRole('button', { name: /파일영향 2개 보기/ })[0]);
    expect(screen.getByText('g_getter1')).toBeInTheDocument();
    expect(screen.getByText('g_getter2')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /파일영향 2개 숨기기/ }).length).toBeGreaterThanOrEqual(1);
  });

  // STS-IMPACT-025: 함수별 영향 가이드 리스트도 파일영향 기본 숨김 + 체크박스로 포함
  it('가이드 리스트: 파일영향(무정보)은 기본 숨김이고 체크박스로 목록에 포함된다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { g_real: 'BODY', g_getter1: 'BODY', g_getter2: 'BODY' },
        impact: { direct: ['g_real', 'g_getter1', 'g_getter2'] },
        function_meta: {},
        function_diffs: { g_real: '@@ -1,2 +1,2 @@ void g_real(void)\n-    x = 1;\n+    x = 2;' },
        classification: { granularity: 'line', line_classified_file_count: 1 },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText(/함수별 상세/)).toBeInTheDocument());
    // 가이드 필터에 '파일영향 포함' 체크박스 노출, 기본 미체크 → 무정보 함수 목록 미표시
    expect(screen.getByText(/파일영향 포함 \(2\)/)).toBeInTheDocument();
    const cb = screen.getByRole('checkbox');
    expect(cb).not.toBeChecked();
    expect(screen.queryByText('g_getter1')).not.toBeInTheDocument();
    // 체크 → 무정보 함수가 목록(변경 상세·가이드 양쪽)에 표시
    await user.click(cb);
    expect(cb).toBeChecked();
    expect(screen.getAllByText('g_getter1').length).toBeGreaterThanOrEqual(1);
  });

  // STS-IMPACT-026: 보수 분류(granularity=file)면 전부 무정보라도 분리 토글 없음(빈 표 방지 가드)
  it('가드: 보수 분류(file)에서는 파일영향 토글이 없고 모든 함수가 그대로 표시된다', () => {
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { foo: 'BODY', bar: 'BODY' },
        impact: { direct: ['foo', 'bar'] },
        function_meta: {},
        classification: { granularity: 'file' },  // 전부 무정보지만 보수 분류 → 분리 무의미
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    // 토글 버튼/캡션 없음 + 두 함수 모두 표시(숨기면 빈 표가 되므로 분리하지 않음)
    expect(screen.queryByRole('button', { name: /파일영향/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/파일영향.*숨김/)).not.toBeInTheDocument();
    expect(screen.getByText('foo')).toBeInTheDocument();
    expect(screen.getByText('bar')).toBeInTheDocument();
  });

  // STS-IMPACT-027: 요약 전 패널 전파 — 커버리지·직접 영향도 파일영향을 기본 제외(오귀속 방지), 토글로 포함
  it('요약 전파: 커버리지·직접 영향도 파일영향을 기본 제외하고 토글로 포함한다', async () => {
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { g_real: 'BODY', g_getter1: 'BODY', g_getter2: 'BODY' },
        impact: { direct: ['g_real', 'g_getter1', 'g_getter2'] },
        function_meta: {},
        function_diffs: { g_real: '@@ -1,2 +1,2 @@ void g_real(void)\n-    x = 1;\n+    x = 2;' },
        classification: { granularity: 'line', line_classified_file_count: 1 },
        coverage_gap: {
          available: true,
          summary: { evaluated: 3, below_target: 2, unmeasured: 0, regressed: 0, had_baseline: true },
          functions: [
            // g_real=실변경(증거), g_getter1/2=파일영향(무변경 fatten). g_getter1 미달은 이 변경 무관 오귀속
            { function: 'g_real', meets_target: false, unmeasured_target: false, delta: 0 },
            { function: 'g_getter1', meets_target: false, unmeasured_target: false, delta: 0 },
            { function: 'g_getter2', meets_target: true, unmeasured_target: false, delta: 0 },
          ],
        },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    // 커버리지: 파일영향 2개(무변경) 제외 근거 note + 직접 영향/변경 함수 스탯 부기
    expect(screen.getByText(/파일영향\(무변경\) 2개 제외/)).toBeInTheDocument();
    expect(screen.getAllByText('+2 파일영향').length).toBeGreaterThanOrEqual(1);
    // 토글 ON → 커버리지 제외 note 사라짐(전체 포함 반영)
    await user.click(screen.getAllByRole('button', { name: /파일영향 2개 보기/ })[0]);
    expect(screen.queryByText(/파일영향\(무변경\) 2개 제외/)).not.toBeInTheDocument();
  });

  // STS-IMPACT-028: AI 요약 ↔ 함수별 상세 탭 통합 — aiGuide 있으면 기본 AI 요약, 탭 클릭 시 함수 표
  it('탭 통합: aiGuide가 있으면 기본 AI 요약이고 함수별 상세 탭 클릭 시 함수 표가 보인다', async () => {
    const { post } = await import('../api.js');
    const aiGuide = {
      ai_enriched: true,
      risk: { grade: 'HIGH', score: 55, max_asil: 'A', justification: '위험 근거', affected_safety_functions: [] },
      review_checklist: [],
      test_recommendations: [{ function: 'g_changed', test_type: 'BV', description: '경계값 검증' }],
      cross_doc_impacts: {},
    };
    post.mockImplementation((url) => (url === '/api/impact/ai-guide'
      ? Promise.resolve({ ok: true, guide: aiGuide })
      : Promise.resolve({ ok: false })));
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { g_changed: 'BODY' },
        actions: {},
        impact: { direct: ['g_changed'] },
        function_meta: { g_changed: { asil: 'A' } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    // 기본 AI 요약 탭: 테스트 추가 제안 노출, 함수 표 subtitle(직접 변경 + 간접 영향)은 미노출
    await waitFor(() => expect(screen.getByText(/테스트 추가 제안/)).toBeInTheDocument());
    expect(screen.queryByText(/직접 변경 \+ 간접 영향/)).not.toBeInTheDocument();
    // '함수별 상세 (1)' 탭 클릭 → 함수 표 노출
    await user.click(screen.getByRole('button', { name: /함수별 상세 \(1\)/ }));
    expect(screen.getByText(/직접 변경 \+ 간접 영향/)).toBeInTheDocument();
  });

  // STS-IMPACT-029: AI 요약의 함수명 클릭 → 기존 함수별 상세 모달(공유 오버레이, 탭 무관)
  it('탭 통합: AI 요약의 테스트 제안 함수명을 클릭하면 상세 모달이 열린다', async () => {
    const { post } = await import('../api.js');
    const aiGuide = {
      ai_enriched: true,
      risk: { grade: 'HIGH', score: 55, max_asil: 'A', justification: 'x', affected_safety_functions: [] },
      review_checklist: [],
      test_recommendations: [{ function: 'g_changed', test_type: 'BV', description: '경계값' }],
      cross_doc_impacts: {},
    };
    post.mockImplementation((url) => (url === '/api/impact/ai-guide'
      ? Promise.resolve({ ok: true, guide: aiGuide })
      : Promise.resolve({ ok: false })));
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { g_changed: 'BODY' },
        actions: {},
        impact: { direct: ['g_changed'] },
        function_meta: { g_changed: { asil: 'A' } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    // AI 요약 탭의 테스트 제안 표에서 함수명은 클릭 가능한 버튼(renderFnRef)
    const fnBtn = await screen.findByRole('button', { name: 'g_changed' });
    await user.click(fnBtn);
    // 공유 상세 모달 열림 — AI 요약 탭에서 클릭해도 오버레이로 표시
    await waitFor(() => expect(screen.getByText(/✕ 닫기/)).toBeInTheDocument());
  });

  // STS-IMPACT-030: guide.details에 없는 함수명은 클릭 불가(일반 텍스트) — 미해석 이름 no-op 가드
  it('탭 통합: guide에 없는 테스트 제안 함수명은 버튼이 아닌 일반 텍스트로 표시된다', async () => {
    const { post } = await import('../api.js');
    const aiGuide = {
      ai_enriched: true,
      risk: { grade: 'LOW', score: 10, max_asil: 'QM', justification: 'x', affected_safety_functions: [] },
      review_checklist: [],
      test_recommendations: [{ function: 'g_ghost', test_type: 'NORMAL', description: '유령' }],
      cross_doc_impacts: {},
    };
    post.mockImplementation((url) => (url === '/api/impact/ai-guide'
      ? Promise.resolve({ ok: true, guide: aiGuide })
      : Promise.resolve({ ok: false })));
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { g_changed: 'BODY' },
        actions: {},
        impact: { direct: ['g_changed'] },
        function_meta: {},
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    // g_ghost는 guide.details(변경/영향 함수)에 없음 → 일반 텍스트(버튼 아님), 클릭 no-op
    await waitFor(() => expect(screen.getByText('g_ghost')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'g_ghost' })).not.toBeInTheDocument();
  });

  // STS-IMPACT-031: 검토 TC=0 정직 사유 — STS 미연동이면 bare 0 대신 사유 배지(silent 0 금지)
  it('검토 TC 사유: STS 미연동이면 0 대신 사유(⚠ STS 미연동)를 표시한다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false }); // ai-guide 스킵 + linkedDocs 없어 STS fetch도 스킵
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { g_changed: 'BODY' },
        actions: {},
        impact: { direct: ['g_changed'] },
        function_meta: {},
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    // 검토 TC 스탯은 요약 패널(탭 무관)에 상시 노출 — 0 대신 사유 배지
    await waitFor(() => expect(screen.getByText('STS 요구 TC')).toBeInTheDocument());
    expect(screen.getByText(/⚠ STS 미연동/)).toBeInTheDocument();
  });

  // STS-IMPACT-032: 검토 TC 조인 근본(F1) — UDS 원본케이스 요구ID ↔ STS 대문자 요구ID 정규화 조인
  it('검토 TC 조인: UDS 원본케이스와 STS 대문자 요구ID가 정규화되어 조인된다(F1)', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      if (url === '/api/jenkins/uds/extract-mapping') {
        return Promise.resolve({ mapping_pairs: [{ requirement_id: 'SwTR_1', source_ids: ['g_changed'] }] });
      }
      if (url === '/api/jenkins/sts/extract-traceability') {
        // STS 엔드포인트는 _normalize_req_id로 대문자화해 방출 → 'SWTR_1'
        return Promise.resolve({ vcast_rows: [{ requirement_id: 'SWTR_1', testcase: 'TC_01' }] });
      }
      return Promise.resolve({ ok: false }); // ai-guide skip
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'], scm_id: 'kjpds02' },
        changed_function_types: { g_changed: 'BODY' },
        actions: {},
        impact: { direct: ['g_changed'] },
        function_meta: { g_changed: { asil: 'A' } },
        _linked_docs: { uds: 'U:/uds.docx', sts: 'U:/sts.xlsm' },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText('STS 요구 TC')).toBeInTheDocument());
    // 대소문자만 다른 요구ID가 정규화 조인돼 검토 TC=1 (정규화 없으면 0 + ⚠사유 배지)
    const card = screen.getByText('STS 요구 TC').closest('.stat-card');
    expect(within(card).getByText('1')).toBeInTheDocument();
    expect(screen.queryByText(/⚠ STS|요구ID 매칭 0/)).not.toBeInTheDocument();
  });

  // STS-IMPACT-033: 라이브 kjpds02 재현 — UDS(SwSTR)·STS(SwEI) 요구 유형이 달라 직접 조인은 0이지만
  //  SDS(SwRS 허브) 브리지(함수→SW요구)로 조인이 성립한다. 과거엔 '요구 유형 상이' 힌트만 떴다.
  it('검토 TC 해결: UDS(SwSTR)·STS(SwEI) 유형이 달라도 SDS(SwRS 허브) 브리지로 STS TC가 조인된다', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      if (url === '/api/jenkins/uds/extract-mapping') {
        return Promise.resolve({ mapping_pairs: [{ requirement_id: 'SwSTR_01', source_ids: ['g_changed'] }] });
      }
      if (url === '/api/jenkins/sts/extract-traceability') {
        return Promise.resolve({ vcast_rows: [{ requirement_id: 'SWEI_01', testcase: 'SwTC_SwEI_01_01' }] });
      }
      // SDS 브리지: 함수 g_changed ↔ SW요구 SwEI_01 (STS TC가 참조하는 SwRS 계열)
      if (url === '/api/jenkins/sds/extract-mapping') {
        return Promise.resolve({ sds_pairs: [{ requirement_id: 'SwEI_01', component_ids: ['g_changed'] }] });
      }
      return Promise.resolve({ ok: false });
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'], scm_id: 'kjpds02' },
        changed_function_types: { g_changed: 'BODY' },
        actions: {},
        impact: { direct: ['g_changed'] },
        function_meta: { g_changed: { asil: 'A' } },
        _linked_docs: { uds: 'U:/uds.docx', sts: 'U:/sts.xlsm', sds: 'U:/sds.docx' },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText('STS 요구 TC')).toBeInTheDocument());
    // SDS 브리지로 g_changed→SwEI_01→SwTC_SwEI_01_01 조인 → STS 요구 TC=1, 사유 배지·요구유형상이 힌트 없음
    const stsCard = screen.getByText('STS 요구 TC').closest('.stat-card');
    expect(within(stsCard).getByText('1')).toBeInTheDocument();
    expect(screen.queryByText(/요구 유형 상이|⚠ STS|⚠ SDS/)).not.toBeInTheDocument();
  });

  // STS-IMPACT-034: SUTS unit 조인 casing(reviewer Finding#1) — 032의 SUTS 대응
  it('SUTS 조인: SUTS unit 원본케이스와 소문자 함수명이 정규화되어 조인된다', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      if (url === '/api/jenkins/sts/extract-traceability') {
        // suts 경로 호출 → unit은 SUTS 문서 원본 케이스(S_MotorSpd), 함수는 소문자(s_motorspd)
        return Promise.resolve({ vcast_rows: [{ unit: 'S_MotorSpd', testcase: 'SUTS_01' }] });
      }
      return Promise.resolve({ ok: false }); // ai-guide skip → 함수별 상세 탭 기본
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'], scm_id: 'kjpds02' },
        changed_function_types: { s_motorspd: 'BODY' },
        actions: {},
        impact: { direct: ['s_motorspd'] },
        function_meta: {},
        _linked_docs: { suts: 'U:/suts.xlsm' }, // suts만 연동(sts 없음 → STS 컬럼 '-')
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText(/함수별 상세/)).toBeInTheDocument());
    // 대소문자만 다른 unit이 정규화 조인돼 함수별 상세 SUTS 컬럼에 1 TC (정규화 없으면 '-')
    expect(screen.getByText('1 TC')).toBeInTheDocument();
  });

  // STS-IMPACT-035: 증거 판정은 백엔드 function_meta.evidence가 1차 소스 —
  // function_diff가 없어도 evidence='line'이면 '파일영향'으로 숨기지 않는다(under-report 방지).
  it('증거 판정: function_diff가 없어도 evidence=line이면 실변경으로 집계한다', () => {
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        // g_real: diff 없음(400KB 절단 시나리오)이지만 백엔드가 line 증거 확인
        // g_fat : 파일단위 보수 포함(fatten)
        changed_function_types: { g_real: 'BODY', g_fat: 'BODY' },
        impact: { direct: ['g_real', 'g_fat'] },
        function_meta: {
          g_real: { asil: 'D', evidence: 'line' },
          g_fat: { asil: 'QM', evidence: 'file_fatten' },
        },
        function_diffs: {},   // diff 원문 없음 — 과거 로직이면 둘 다 '증거 없음'으로 오판
        change_details: {},
        classification: { granularity: 'mixed', evidenced_function_count: 1, fattened_function_count: 1 },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    // 변경 함수 = 1(g_real만) + '+1 파일영향' 부기. 과거 추론이면 0 + '+2 파일영향'이 됐을 것.
    expect(screen.getAllByText('+1 파일영향').length).toBeGreaterThanOrEqual(1);
    // 파일영향 토글 노출(증거 혼재) — evidence 기반 분리가 동작
    expect(screen.getAllByRole('button', { name: /파일영향 1개 보기/ }).length).toBeGreaterThanOrEqual(1);
  });

  // STS-IMPACT-036: 콜그래프 탐색 절단(2-hop 미계산)을 '영향 없음'으로 오독하지 않게 표시
  it('탐색 절단: impact_traversal.truncated면 간접 영향에 미계산 경고를 표시한다', () => {
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { g_a: 'BODY' },
        impact: { direct: ['g_a'], indirect_1hop: ['g_b'], indirect_2hop: [] },
        function_meta: {},
        impact_traversal: { truncated: true, truncated_at_hop: 1, max_impacted_functions: 50, max_hop: 2 },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    expect(screen.getByText(/1-hop까지만 계산/)).toBeInTheDocument();
  });

  // STS-IMPACT-037: baseline이 같은 빌드면 Δ=0이라 '회귀 없음'이 아니라 '비교 불가'
  it('커버리지 Δ: baseline이 같은 빌드면 회귀 0 대신 비교 불가로 표시한다', () => {
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['a.c'] },
        changed_function_types: { g_a: 'BODY' },
        impact: { direct: ['g_a'] },
        function_meta: { g_a: { asil: 'A', evidence: 'line' } },
        coverage_gap: {
          available: true,
          summary: {
            evaluated: 1, below_target: 0, unmeasured: 0, regressed: 0, had_baseline: true,
            unmatched: 0, baseline_revision: '1053', build_revision: '1053',
            baseline_same_revision: true,
          },
          functions: [{ function: 'g_a', meets_target: true, delta: 0 }],
        },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    expect(screen.getByText(/같은 빌드 — Δ 비교 불가/)).toBeInTheDocument();
    // 회귀 수치를 0으로 단정하지 않는다(—)
    expect(screen.getByText('직전 대비 회귀').closest('.stat-card').textContent).toContain('—');
  });

  // STS-IMPACT-038: funcToReqs 조인 casing(F3) — UDS source_ids 원본케이스 ↔ 소문자 함수명 정규화
  //  032가 요구ID 케이싱을 다뤘다면 이건 함수명 케이싱. UDS "Name" 셀은 원본 케이스로 방출되고
  //  (jenkins.py func_name 원본) impact 함수명은 backend by_name 정규화로 소문자다. 정규화 없이
  //  조인하면 mixed-case 함수(EEPROM_SetByte)의 요구/STS TC가 통째로 0 → 검토범위 under-report.
  it('검토 TC 조인: UDS source_ids 원본케이스와 소문자 함수명이 정규화되어 조인된다(F3)', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      if (url === '/api/jenkins/uds/extract-mapping') {
        // UDS "Name" 셀 원본 케이스(mixed) — backend가 소문자화하지 않음
        return Promise.resolve({ mapping_pairs: [{ requirement_id: 'SwTR_1', source_ids: ['EEPROM_SetByte'] }] });
      }
      if (url === '/api/jenkins/sts/extract-traceability') {
        return Promise.resolve({ vcast_rows: [{ requirement_id: 'SwTR_1', testcase: 'TC_EEP_01' }] });
      }
      return Promise.resolve({ ok: false }); // ai-guide skip
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['EEPROM.c'], scm_id: 'kjpds02' },
        // impact 함수명은 backend 정규화로 소문자
        changed_function_types: { eeprom_setbyte: 'BODY' },
        actions: {},
        impact: { direct: ['eeprom_setbyte'] },
        function_meta: { eeprom_setbyte: { asil: 'B' } },
        _linked_docs: { uds: 'U:/uds.docx', sts: 'U:/sts.xlsm' },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText('STS 요구 TC')).toBeInTheDocument());
    // 함수명 케이스만 달라도 정규화 조인 → 영향 요구사항=1, STS 요구 TC=1
    // (정규화 없으면 funcToReqs['eeprom_setbyte'] 미스 → 둘 다 0 + ⚠사유 배지)
    const reqCard = screen.getByText('영향 요구사항').closest('.stat-card');
    expect(within(reqCard).getByText('1')).toBeInTheDocument();
    const stsCard = screen.getByText('STS 요구 TC').closest('.stat-card');
    expect(within(stsCard).getByText('1')).toBeInTheDocument();
    expect(screen.queryByText(/⚠ STS|요구ID 매칭 0/)).not.toBeInTheDocument();
  });

  // STS-IMPACT-039: 이름충돌 worst-copy 커버리지 표면화(R5 백엔드 collision_worst_copy의 프론트 절반)
  it('커버리지: collision_worst_copy가 있으면 최악(worst-copy) 표면화 노트를 표시한다', () => {
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Eeprom.c'] },
        changed_function_types: { eeprom_setbyte: 'BODY' },
        actions: {},
        impact: { direct: ['eeprom_setbyte'] },
        function_meta: { eeprom_setbyte: { asil: 'D', evidence: 'line' } },
        coverage_gap: {
          available: true,
          functions: [{ function: 'eeprom_setbyte', asil: 'D', target_metric: 'mcdc', current_rate: 0.6, meets_target: false, collision_worst_copy: true }],
          summary: { evaluated: 1, below_target: 1, regressed: 0, had_baseline: true, collision_worst_copy: 1 },
        },
      },
    };
    render(<ImpactGuideSection job={mockJob} analysisResult={analysisResult} />);
    // 커버리지 요약 카드에 이름충돌 worst-copy 노트(전역 max 병합의 gap 은폐 방지 표면화)
    expect(screen.getByText(/이름충돌 1개 함수는 여러 copy 중/)).toBeInTheDocument();
    expect(screen.getByText(/최악\(worst-copy\)/)).toBeInTheDocument();
  });

  // STS-IMPACT-040: 문서별 상세 탭 — 함수-우선 데이터의 문서-우선 전치. 좌측 문서 선택 → 우측
  // 함수·편집 액션(buildDocumentActions), 함수명 클릭 → 공유 함수 상세 모달(백엔드 변경 없음).
  it('문서별 상세: 탭 전환·문서 선택 시 함수·편집 액션이 보이고 함수명 클릭으로 상세 모달이 열린다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false }); // ai-guide/uds/sts extract 스킵 → guide만(백엔드 fetch 없이)
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { g_sig_changed: 'SIGNATURE' },
        change_details: { g_sig_changed: { before: 'void g_sig_changed(void)', after: 'void g_sig_changed(uint8_t speed)' } },
        impact: { direct: ['g_sig_changed'] },
        // 문서별 멤버십(권위 backend) — uds/suts에 함수 배치
        actions: {
          uds: { mode: 'AUTO', status: 'review_required', function_count: 1, functions: ['g_sig_changed'] },
          suts: { mode: 'AUTO', status: 'review_required', function_count: 1, functions: ['g_sig_changed'] },
        },
        function_meta: { g_sig_changed: { asil: 'C', evidence: 'line' } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    // 문서별 상세 (2) 탭 — uds/suts 2개 문서에 영향
    const docTab = await screen.findByRole('button', { name: /문서별 상세 \(2\)/ });
    await user.click(docTab);
    // 기본 선택 = 첫 영향 문서(UDS) → SIGNATURE 편집 액션(Prototype) 노출
    expect(screen.getByText(/함수 선언을 새 시그니처로 교체/)).toBeInTheDocument();
    // 좌측 SUTS 선택 → 우측이 SUTS 편집 액션(단위시험 관점)으로 전환(마스터-디테일)
    await user.click(screen.getByRole('button', { name: 'SUTS 문서 선택' }));
    expect(screen.getByText(/단위 TC 신규 필요/)).toBeInTheDocument();
    // 함수명 클릭 → 공유 함수 상세 모달(탭 무관 오버레이)
    await user.click(screen.getByRole('button', { name: 'g_sig_changed' }));
    await waitFor(() => expect(screen.getByText(/✕ 닫기/)).toBeInTheDocument());
  });

  // STS-IMPACT-041: 문서별 상세 — 명시적으로 고른 0-영향 문서는 조용히 튕기지 않고 빈 상태를
  // 보여준다(reviewer W7 wrong-pick 폴백 제거). effSelectedDoc은 null(최초)일 때만 폴백.
  it('문서별 상세: 영향 0 문서를 직접 선택하면 다른 문서로 튕기지 않고 "영향 없음"을 보여준다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { g_sig_changed: 'SIGNATURE' },
        change_details: { g_sig_changed: { before: 'void g_sig_changed(void)', after: 'void g_sig_changed(uint8_t speed)' } },
        impact: { direct: ['g_sig_changed'] },
        actions: { uds: { mode: 'AUTO', status: 'review_required', function_count: 1, functions: ['g_sig_changed'] } }, // sds 없음 → 0-영향
        function_meta: { g_sig_changed: { asil: 'C' } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    // uds만 영향 → 문서별 상세 (1)
    await user.click(await screen.findByRole('button', { name: /문서별 상세 \(1\)/ }));
    expect(screen.getByText(/함수 선언을 새 시그니처로 교체/)).toBeInTheDocument(); // 기본 UDS
    // 0-영향 SDS 직접 선택 → uds로 튕기지 않고 빈 상태(W7 fix)
    await user.click(screen.getByRole('button', { name: 'SDS 문서 선택' }));
    expect(screen.getByText(/이 문서에 영향 없음/)).toBeInTheDocument();
    expect(screen.queryByText(/함수 선언을 새 시그니처로 교체/)).not.toBeInTheDocument(); // uds로 안 튕김
  });

  // STS-IMPACT-042: SDS 미연동이면 STS 요구 TC 0을 'SDS 미연동' 사유로 정직 표기(silent-0 금지).
  //  SwRS 허브 브리지 없이는 SwSTR↔SwEI 유형 상이로 조인 불가함을 새 진단 문구로 표면화.
  it('검토 TC 사유: SDS 미연동이면 STS 요구 TC 0을 SDS 미연동 사유로 표기한다(요구유형상이 힌트 제거)', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      if (url === '/api/jenkins/uds/extract-mapping') {
        return Promise.resolve({ mapping_pairs: [{ requirement_id: 'SwSTR_01', source_ids: ['g_changed'] }] });
      }
      if (url === '/api/jenkins/sts/extract-traceability') {
        return Promise.resolve({ vcast_rows: [{ requirement_id: 'SWEI_01', testcase: 'SwTC_SwEI_01_01' }] });
      }
      return Promise.resolve({ ok: false }); // sds 미연동(mock 없음) + ai-guide skip
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'], scm_id: 'kjpds02' },
        changed_function_types: { g_changed: 'BODY' },
        actions: {},
        impact: { direct: ['g_changed'] },
        function_meta: { g_changed: { asil: 'A' } },
        _linked_docs: { uds: 'U:/uds.docx', sts: 'U:/sts.xlsm' }, // sds 미연동
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText('STS 요구 TC')).toBeInTheDocument());
    const stsCard = screen.getByText('STS 요구 TC').closest('.stat-card');
    expect(within(stsCard).getByText('0')).toBeInTheDocument();
    expect(within(stsCard).getByText(/SDS 미연동/)).toBeInTheDocument();
    // 옛 '요구 유형 상이' 힌트는 제거됨(허브 경유로 대체)
    expect(screen.queryByText(/요구 유형 상이/)).not.toBeInTheDocument();
  });

  // STS-IMPACT-043: SITS — 같은 SwRS 허브 브리지(SDS 함수→SW요구 → SITS TC)로 per-function SITS TC가
  //  함수 상세 SITS 컬럼·SITS 영향 TC 카드·함수 상세 모달 칩에 표시된다(과거엔 함수별 SITS 부재).
  it('SITS: SwRS 브리지로 per-function SITS TC가 SITS 카드와 함수 상세 모달 칩에 표시된다', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      if (url === '/api/jenkins/sds/extract-mapping') {
        return Promise.resolve({ sds_pairs: [{ requirement_id: 'SwEI_01', component_ids: ['g_changed'] }] });
      }
      if (url === '/api/jenkins/sits/extract-traceability') {
        return Promise.resolve({ vcast_rows: [{ requirement_id: 'SwEI_01', testcase: 'SITS_TC_01' }] });
      }
      return Promise.resolve({ ok: false });
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'], scm_id: 'kjpds02' },
        changed_function_types: { g_changed: 'BODY' },
        actions: {},
        impact: { direct: ['g_changed'] },
        function_meta: { g_changed: { asil: 'A' } },
        _linked_docs: { sds: 'U:/sds.docx', sits: 'U:/sits.xlsm' },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText('SITS 영향 TC')).toBeInTheDocument());
    // SwRS 허브(SDS g_changed→SwEI_01) → SITS(SwEI_01→SITS_TC_01) 브리지로 SITS TC=1
    const sitsCard = screen.getByText('SITS 영향 TC').closest('.stat-card');
    expect(within(sitsCard).getByText('1')).toBeInTheDocument();
    // 함수 상세 모달의 SITS 검토 카드에 실제 TC id 칩 노출
    await user.click(screen.getByRole('button', { name: '상세' }));
    await waitFor(() => expect(screen.getByText('SITS_TC_01')).toBeInTheDocument());
  });

  // STS-IMPACT-044: SITS 미연동이면 SITS 영향 TC 0을 사유로 정직 표기(통합 콜체인 참조 안내).
  it('SITS 사유: SITS 미연동이면 SITS 영향 TC 0을 SITS 미연동 사유로 표기한다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'], scm_id: 'kjpds02' },
        changed_function_types: { g_changed: 'BODY' },
        actions: {},
        impact: { direct: ['g_changed'] },
        function_meta: { g_changed: { asil: 'A' } },
        _linked_docs: { uds: 'U:/uds.docx', sts: 'U:/sts.xlsm' }, // sits/sds 미연동
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText('SITS 영향 TC')).toBeInTheDocument());
    const sitsCard = screen.getByText('SITS 영향 TC').closest('.stat-card');
    expect(within(sitsCard).getByText('0')).toBeInTheDocument();
    expect(within(sitsCard).getByText(/SITS 미연동/)).toBeInTheDocument();
  });

  // STS-IMPACT-045: SITS SwUFn(단위) 브리지 — 실 kjpds02 재현. SITS TC는 요구가 SYSTEMTM 네임스페이스라
  //  SwRS 허브로 0이지만, testcase(SwITC_SwUFn_0127)의 SwUFn을 SUTS TC(SwUTC_SwUFn_0127, unit=함수명)로
  //  풀어 함수에 연결한다. 이것이 실데이터에서 SITS를 채우는 유일 경로.
  it('SITS: 요구가 SYSTEMTM이어도 testcase의 SwUFn을 SUTS unit으로 풀어 함수에 SITS TC를 연결한다', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      // suts 경로(doc_type suts) — SwUFn을 품은 SUTS TC로 SwUFn→함수명 맵 구성
      if (url === '/api/jenkins/sts/extract-traceability') {
        return Promise.resolve({ vcast_rows: [{ unit: 's_hash', testcase: 'SwUTC_SwUFn_0127' }] });
      }
      // SITS TC 요구는 SYSTEMTM(SwRS 허브 미매칭)이지만 testcase에 SwUFn_0127 포함
      if (url === '/api/jenkins/sits/extract-traceability') {
        return Promise.resolve({ vcast_rows: [{ requirement_id: 'SYSTEMTM_5', testcase: 'SwITC_SwUFn_0127' }] });
      }
      return Promise.resolve({ ok: false });
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'], scm_id: 'kjpds02' },
        changed_function_types: { s_hash: 'BODY' },
        actions: {},
        impact: { direct: ['s_hash'] },
        function_meta: { s_hash: { asil: 'A' } },
        _linked_docs: { suts: 'U:/suts.xlsm', sits: 'U:/sits.xlsm' }, // sts/sds 없이도 SwUFn 경로로 조인
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText('SITS 영향 TC')).toBeInTheDocument());
    // SwUFn 단위 브리지로 SITS TC=1 (요구 경로는 SYSTEMTM이라 0, 단위 경로가 실효)
    const sitsCard = screen.getByText('SITS 영향 TC').closest('.stat-card');
    expect(within(sitsCard).getByText('1')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '상세' }));
    await waitFor(() => expect(screen.getByText('SwITC_SwUFn_0127')).toBeInTheDocument());
  });

  // STS-IMPACT-046: SwIFn(통합함수) 토큰도 매칭(reviewer W1) — 백엔드 _SWUFN_RE=Sw[UI]Fn_ parity.
  //  SwUFn만 매칭하면 testcase에 SwIFn이 박힌 SITS TC가 조용히 누락된다.
  it('SITS: testcase의 SwIFn(통합함수) 토큰도 SUTS unit으로 풀어 함수에 연결한다(Sw[UI]Fn parity)', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      if (url === '/api/jenkins/sts/extract-traceability') {
        return Promise.resolve({ vcast_rows: [{ unit: 's_integ_fn', testcase: 'SwUTC_SwIFn_0050' }] });
      }
      if (url === '/api/jenkins/sits/extract-traceability') {
        return Promise.resolve({ vcast_rows: [{ requirement_id: 'SYSTEMTM_1', testcase: 'SwITC_SwIFn_0050' }] });
      }
      return Promise.resolve({ ok: false });
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'], scm_id: 'kjpds02' },
        changed_function_types: { s_integ_fn: 'BODY' },
        actions: {},
        impact: { direct: ['s_integ_fn'] },
        function_meta: { s_integ_fn: { asil: 'A' } },
        _linked_docs: { suts: 'U:/suts.xlsm', sits: 'U:/sits.xlsm' },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText('SITS 영향 TC')).toBeInTheDocument());
    // SwIFn_0050이 양변에서 매칭돼 SITS TC=1 (SwUFn만 매칭했다면 0)
    const sitsCard = screen.getByText('SITS 영향 TC').closest('.stat-card');
    expect(within(sitsCard).getByText('1')).toBeInTheDocument();
  });

  // STS-IMPACT-047: 반환형 접두사 충돌(u8g_/s8g_ 같은 base로 수렴하는 별개 함수)은 alias를 만들지 않아
  //  오귀속하지 않는다(reviewer W3, 백엔드 _alias_safe parity). 무조건 strip이면 두 함수 req가 union됨.
  it('STS: 반환형 접두사가 충돌하는 별개 함수는 alias 미생성으로 서로의 TC가 섞이지 않는다(_alias_safe)', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      if (url === '/api/jenkins/sds/extract-mapping') {
        return Promise.resolve({ sds_pairs: [
          { requirement_id: 'SwEI_01', component_ids: ['u8g_foo'] },
          { requirement_id: 'SwEI_02', component_ids: ['s8g_foo'] },
        ] });
      }
      if (url === '/api/jenkins/sts/extract-traceability') {
        return Promise.resolve({ vcast_rows: [
          { requirement_id: 'SwEI_01', testcase: 'TC_FOO_A' },
          { requirement_id: 'SwEI_02', testcase: 'TC_FOO_B' },
        ] });
      }
      return Promise.resolve({ ok: false });
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'], scm_id: 'kjpds02' },
        changed_function_types: { u8g_foo: 'BODY' },
        actions: {},
        impact: { direct: ['u8g_foo'] },
        function_meta: { u8g_foo: { asil: 'A' } },
        _linked_docs: { sts: 'U:/sts.xlsm', sds: 'U:/sds.docx' },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText('STS 요구 TC')).toBeInTheDocument());
    // u8g_foo는 자기 TC_FOO_A만(=1). 충돌 base g_foo alias가 생겼다면 s8g_foo의 TC_FOO_B까지 2가 됨.
    const stsCard = screen.getByText('STS 요구 TC').closest('.stat-card');
    expect(within(stsCard).getByText('1')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: '상세' }));
    await waitFor(() => expect(screen.getByText('TC_FOO_A')).toBeInTheDocument());
    expect(screen.queryByText('TC_FOO_B')).not.toBeInTheDocument();
  });

  // STS-IMPACT-048: 회귀시험 패널 '전체 보기' 토글 — 12개 초과 함수 목록의 절단을 해제(사용자 요청).
  it('회귀 더보기: SUTS 재실행 함수가 12개 초과면 절단됐다가 "전체 보기"로 전부 노출된다', async () => {
    const user = userEvent.setup();
    const suts = {};
    for (let i = 1; i <= 15; i++) suts[`fn_regr_${i}`] = [`SwUTC_${i}`];
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: {},
        impact: {},
        function_meta: {},
        regression_test_set: {
          suts, sits: {},
          summary: { suts_tc_count: 15, sits_chain_count: 0, impacted_function_count: 15 },
        },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    // 초기: 12개만(fn_regr_13은 절단) + "전체 보기" 토글 노출
    expect(screen.getByText('fn_regr_12')).toBeInTheDocument();
    expect(screen.queryByText('fn_regr_13')).not.toBeInTheDocument();
    expect(screen.getByText(/3개 함수 더/)).toBeInTheDocument();
    // 전체 보기 → 13~15 노출, "더" 표기 사라짐
    await user.click(screen.getByRole('button', { name: /전체 보기/ }));
    expect(screen.getByText('fn_regr_13')).toBeInTheDocument();
    expect(screen.getByText('fn_regr_15')).toBeInTheDocument();
    expect(screen.queryByText(/개 함수 더/)).not.toBeInTheDocument();
  });

  // STS-IMPACT-049: 회귀 패널 SITS — 백엔드 통합 콜체인 0(빌더 미실행)이어도 프론트 SwUFn 파생 SITS TC를
  //  표시하고, 0의 사유를 표면화한다(사용자 A안 + silent-0 금지).
  it('회귀 SITS: 백엔드 체인 0이어도 SwUFn 파생 SITS TC를 회귀 패널에 표시하고 미집계 사유를 표기한다', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      if (url === '/api/jenkins/sts/extract-traceability') {
        return Promise.resolve({ vcast_rows: [{ unit: 's_hash', testcase: 'SwUTC_SwUFn_0127' }] });
      }
      if (url === '/api/jenkins/sits/extract-traceability') {
        return Promise.resolve({ vcast_rows: [{ requirement_id: 'SYSTEMTM_1', testcase: 'SwITC_SwUFn_0127' }] });
      }
      return Promise.resolve({ ok: false });
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'], scm_id: 'kjpds02' },
        changed_function_types: { s_hash: 'BODY' },
        impact: { direct: ['s_hash'] },
        actions: {},
        function_meta: { s_hash: { asil: 'A' } },
        warnings: ['회귀 체인: SITS VectorCAST 중간파일 미생성(SITS 빌더 미실행) — 통합 체인 미집계'],
        _linked_docs: { suts: 'U:/suts.xlsm', sits: 'U:/sits.xlsm' },
        // 회귀 패널이 렌더되려면 summary 필요(백엔드 SITS 체인은 0)
        regression_test_set: { suts: {}, sits: {}, summary: { suts_tc_count: 0, sits_chain_count: 0, impacted_function_count: 1 } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    // 생성 전: 백엔드 카운트 0(suts/sits) + guideSitsMap 비어 게이트 false → 회귀 패널 자체가 미노출
    expect(screen.queryByText(/회귀시험 선정/)).not.toBeInTheDocument();
    await user.click(screen.getByText(/상세 가이드 생성/));
    // 생성 후: SwUFn 파생 SITS 섹션 + 실 TC id + 미집계 사유
    await waitFor(() => expect(screen.getByText(/SITS 재실행 TC \(함수별 · SwUFn 브리지\)/)).toBeInTheDocument());
    expect(screen.getByText('SwITC_SwUFn_0127')).toBeInTheDocument();
    expect(screen.getByText(/SITS 통합 콜체인 0/)).toBeInTheDocument();
  });

  // STS-IMPACT-050: 회귀 더보기 버튼은 함수 수뿐 아니라 함수당 TC 수 절단(>6)에도 노출된다(reviewer W1).
  //  단일 함수에 TC가 8개 몰리면(함수 수 1≤12) 과거엔 "+2"만 뜨고 해제 버튼이 없는 dead-end였다.
  it('회귀 더보기: 단일 함수에 TC가 6개 초과 몰려도 "전체 보기" 버튼이 노출되고 전체 TC를 편다', async () => {
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: {}, impact: {}, function_meta: {},
        regression_test_set: {
          suts: { s_multi: ['tc1', 'tc2', 'tc3', 'tc4', 'tc5', 'tc6', 'tc7', 'tc8'] }, sits: {},
          summary: { suts_tc_count: 8, sits_chain_count: 0, impacted_function_count: 1 },
        },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    // 함수 1개(≤12)지만 함수당 TC 8개(>6)라 버튼 노출 + tc7/tc8 절단
    expect(screen.getByRole('button', { name: /전체 보기/ })).toBeInTheDocument();
    expect(screen.queryByText('tc7')).not.toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /전체 보기/ }));
    expect(screen.getByText('tc7')).toBeInTheDocument();
    expect(screen.getByText('tc8')).toBeInTheDocument();
  });
});

describe('extractDiffElements (순수 함수)', () => {
  it('전역 write·매크로 추출, RHS 상수·로컬·비교 배제', () => {
    const fd = [
      '@@ -1,5 +1,4 @@ f(void)',
      '-#ifdef TESTCODE_FOR_VEHICLE',
      '-    u8g_Asst = u8g_VENTILATION_OFF;',
      '-    u8g_Rear = u8g_VENTILATION_OFF;',
      '-#endif',
      '     if (u8g_State == u8g_ON) {',   // 비교 — write 아님
      '-    tmp = 1;',                       // 로컬 — 배제
      '+    u8g_Arr[3] = 5;',               // 배열 write — base
    ].join('\n');
    const r = extractDiffElements(fd);
    expect(r.changedGlobals.removed).toContain('u8g_Asst');
    expect(r.changedGlobals.removed).toContain('u8g_Rear');
    expect(r.changedGlobals.added).toContain('u8g_Arr');            // 배열첨자 strip
    expect(r.changedGlobals.removed).not.toContain('u8g_VENTILATION_OFF');  // RHS 상수 미포착
    expect(r.changedGlobals.removed).not.toContain('tmp');          // 로컬 배제
    expect(r.changedGlobals.removed).not.toContain('u8g_State');    // 비교 무포착
    expect(r.macros.removed).toContain('TESTCODE_FOR_VEHICLE');
  });

  it('빈/undefined는 EMPTY, 절단 마커는 truncated', () => {
    expect(extractDiffElements('').changedGlobals.removed).toEqual([]);
    expect(extractDiffElements(undefined).changedGlobals.removed).toEqual([]);
    const r = extractDiffElements('@@ -1,1 +1,1 @@ f(void)\n-    u8g_X = 0;\n… (+40줄 생략)');
    expect(r.truncated).toBe(true);
  });

  it('reviewer 반례: 전역 아닌 변수(msg_len 등) 배제, 정상 전역/정적 채택', () => {
    for (const v of ['msg_len', 'flag_group', 'cfg_mode', 'reg_val', 'org_id']) {
      const r = extractDiffElements(`@@ -1,1 +1,1 @@ f(void)\n-    ${v} = 1;`);
      expect(r.changedGlobals.removed).not.toContain(v);
    }
    for (const v of ['u8g_X', 's16g_Y', 'g_Z', 'u8s_T', 's_M']) {
      const r = extractDiffElements(`@@ -1,1 +1,1 @@ f(void)\n-    ${v} = 1;`);
      expect(r.changedGlobals.removed).toContain(v);
    }
  });

  it('reviewer 반례: 구조체/포인터 멤버 write, #if defined(X), #pragma 제외', () => {
    const rm = extractDiffElements('@@ -1,2 +1,2 @@ f(void)\n-    g_DoorState.mode = 1;\n+    g_Handle->count = 0;');
    expect(rm.changedGlobals.removed).toContain('g_DoorState');   // 멤버 write → base 전역
    expect(rm.changedGlobals.added).toContain('g_Handle');
    const rd = extractDiffElements('@@ -1,1 +1,1 @@ f(void)\n-#if defined(FOO_ENABLED)\n+#if defined(BAR_ENABLED)');
    expect(rd.macros.removed).toContain('FOO_ENABLED');           // defined(X) → X
    expect(rd.macros.added).toContain('BAR_ENABLED');
    expect(rd.macros.removed).not.toContain('defined');
    const rp = extractDiffElements('@@ -1,1 +1,1 @@ f(void)\n-#pragma pack(1)\n+#pragma pack(2)');
    expect(rp.macros.added).toEqual([]);                          // #pragma는 조건부 컴파일 아님
    expect(rp.macros.removed).toEqual([]);
  });

  it('reviewer 반례: cap 제거로 개수 정확(15개)', () => {
    const many = Array.from({ length: 15 }, (_, i) => `-    g_Var${i} = 0;`).join('\n');
    const r = extractDiffElements('@@ -1,15 +1,0 @@ f(void)\n' + many);
    expect(r.changedGlobals.removed.length).toBe(15);
  });
});

describe('buildDocumentActions BODY/VARIABLE 구체화 (순수 함수)', () => {
  const de = extractDiffElements([
    '@@ -1,3 +1,1 @@ void g_reset(void)',
    '-#ifdef TESTCODE_FOR_VEHICLE',
    '-    u8g_Asst = u8g_VENTILATION_OFF;',
    '-#endif',
  ].join('\n'));
  const d = { function: 'g_reset', changeType: 'VARIABLE', changed: true, requirements: [], stsTestCases: [], sutsTestCases: [] };

  it('UDS는 실제 변수명 + Used Globals(Reset Value), SITS는 Data Flow 아님, SDS는 관련 함수/모듈 매칭', () => {
    const r = buildDocumentActions(d, null, de);
    const udsStr = JSON.stringify(r.uds);
    expect(udsStr).toContain('u8g_Asst');
    expect(udsStr).toContain('Used Globals');
    expect(udsStr).toContain('Reset Value');
    expect(JSON.stringify(r.sits)).not.toContain('Data Flow');
    expect(r.sds[0].section).toBe('관련 함수/모듈 매칭');
    expect(JSON.stringify(r.uds)).toContain('TESTCODE_FOR_VEHICLE');  // 전처리 매크로 반영
  });

  it('diffElems 없으면 일반 폴백(변수명 없음, 크래시 없음)', () => {
    const r = buildDocumentActions(d, null);  // diffElems 기본값(EMPTY)
    expect(r.uds.length).toBeGreaterThan(0);
    expect(JSON.stringify(r.uds)).not.toContain('u8g_Asst');
  });

  it('reviewer #4: 전역 없이 매크로만 바뀐 BODY도 구체화(일반 폴백 아님)', () => {
    const deMacro = extractDiffElements([
      '@@ -1,3 +1,1 @@ void g_f(void)',
      '-#ifdef FEATURE_X',
      '-    DoSomething();',
      '-#endif',
    ].join('\n'));
    const dMacro = { function: 'g_f', changeType: 'BODY', changed: true, requirements: [], stsTestCases: [], sutsTestCases: [] };
    const r = buildDocumentActions(dMacro, null, deMacro);
    // 전역 write 없어도 매크로(FEATURE_X)가 UDS Description·SDS에 반영 — 일반 폴백으로 후퇴하지 않음
    expect(JSON.stringify(r.uds)).toContain('FEATURE_X');
    expect(JSON.stringify(r.sds)).toContain('FEATURE_X');
  });
});
