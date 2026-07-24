import { render, screen, waitFor, within, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { STORE_VERSION } from '../impactStore.js';

// Mock api.js
vi.mock('../api.js', () => ({
  post: vi.fn(),
  api: vi.fn(),
  defaultCacheRoot: vi.fn(() => '.devops_cache'),
}));

// Mock App.jsx contexts.
// 훅 반환값은 팩토리 클로저에 고정한다 — 매 호출 새 참조를 주면 useCallback/useEffect 체인이
// 렌더마다 갱신돼 자동 조회가 무한 루프가 된다.
vi.mock('../App.jsx', () => {
  const toast = vi.fn();
  const setAnalysisResult = vi.fn();
  const cfg = {
    username: 'admin',
    token: 'token123',
    cacheRoot: '.devops_pro_cache',
    buildSelector: 'lastSuccessfulBuild',
  };
  const jobCtx = { setAnalysisResult };
  const cfgCtx = { cfg };
  return {
    useJenkinsCfg: vi.fn(() => cfgCtx),
    useToast: vi.fn(() => toast),
    useJob: vi.fn(() => jobCtx),
  };
});

// Mock StatusBadge
vi.mock('../components/StatusBadge.jsx', () => ({
  default: ({ children, tone }) => (
    <span data-testid="status-badge" data-tone={tone}>{children}</span>
  ),
}));

const { default: ImpactGuideSection, extractDiffElements, buildDocumentActions, matchFileDiff } = await import('../components/sections/ImpactGuideSection.jsx');

describe('ImpactGuideSection', () => {
  const mockJob = { url: 'http://jenkins.example.com/job/test-job/' };

  beforeEach(() => {
    vi.clearAllMocks();
    // 영속 스토어(devops_v2_impact_current)가 테스트 간 새어나가면 다음 테스트가 이전 결과를
    // 하이드레이트해 버린다 — 매 테스트 격리.
    localStorage.clear();
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
  // SHOW_ASIL_COVERAGE=false (사용자 요청 2026-07): 🎯커버리지 패널은 숨겨진다.
  // 백엔드 coverage_gap 계산은 유지되나 프론트에서 렌더 게이팅됨.
  it('렌더링: coverage_gap이 있어도 커버리지(ASIL 타깃 대비) 패널은 숨겨진다(SHOW_ASIL_COVERAGE=false)', () => {
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

    // Assert: 커버리지 카드가 렌더되지 않음
    expect(screen.queryByText(/커버리지 \(ASIL 타깃 대비\)/)).not.toBeInTheDocument();
  });

  // SHOW_ASIL_COVERAGE=false: 🛡️ASIL 차등 검증 패널도 숨겨진다.
  it('렌더링: impact.asil이 있어도 ASIL 차등 검증 strip은 숨겨진다(SHOW_ASIL_COVERAGE=false)', () => {
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

    // Assert: ASIL 차등 strip이 렌더되지 않음
    expect(screen.queryByText(/ASIL 차등 검증/)).not.toBeInTheDocument();
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

  // STS-IMPACT-062: CamelCase 프로젝트 — function_meta/coverage는 backend by_name(소문자) 키라,
  //  가이드 표의 ASIL 표시가 원본 CamelCase fn 직접조회로 미스하면 알려진 등급이 공백=under-report.
  //  _fnLc 소문자 폴백으로 해소(W1). kjpds02(소문자)엔 무해, hdpdm01 계열에 영향.
  it('가이드: CamelCase 함수의 ASIL이 소문자 function_meta 폴백으로 표시된다(under-report fix)', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Eeprom.c'] },
        changed_function_types: { EEPROM_SetByte: 'BODY' },   // 화면 fn = CamelCase(소스 원본 케이스)
        actions: {},
        impact: { direct: ['EEPROM_SetByte'] },
        function_meta: { eeprom_setbyte: { asil: 'D' } },      // backend by_name = 소문자
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    // 함수명은 변경상세·영향가이드 양쪽에 등장 → getAllByText로 확인.
    await waitFor(() => expect(screen.getAllByText('EEPROM_SetByte').length).toBeGreaterThan(0));
    // 폴백 없으면 d.asil=''(공백)→ ASIL 'D' pill 미표시(0건). 폴백으로 가이드에 D pill 표시.
    expect(screen.getAllByText('D').length).toBeGreaterThan(0);
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
    // AI 원문→제안 버튼 노출(라벨 'AI 문장 재작성'으로 변경)
    expect(screen.getByRole('button', { name: /AI 문장 재작성/ })).toBeInTheDocument();
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
    expect(screen.getByText(/본문 변경 원문이 없는 것이 정상/)).toBeInTheDocument();  // 정직화된 fatten 안내(구 '본문 변경 원문 없음')
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

  // STS-IMPACT-027: 요약 전 패널 전파 — 직접 영향 파일영향을 기본 제외(오귀속 방지), 토글로 포함.
  // (커버리지 패널은 SHOW_ASIL_COVERAGE=false로 숨겨졌으므로 직접영향 전파만 검증.)
  it('요약 전파: 직접 영향도 파일영향을 기본 제외하고 토글로 포함한다', async () => {
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
    // 직접 영향 스탯: 파일영향 2개(무변경) 기본 제외 부기('+2 파일영향')
    expect(screen.getAllByText('+2 파일영향').length).toBeGreaterThanOrEqual(1);
    // 토글 ON → '+N 파일영향' → '(파일영향 N 포함)'로 전환(전체 포함 반영)
    await user.click(screen.getAllByRole('button', { name: /파일영향 2개 보기/ })[0]);
    expect(screen.queryByText('+2 파일영향')).not.toBeInTheDocument();
    expect(screen.getAllByText(/파일영향 2 포함/).length).toBeGreaterThanOrEqual(1);
  });

  // STS-IMPACT-028: 'AI 요약' 탭은 SHOW_AI_GUIDE_TAB=false로 숨겨진다 — ai-guide fetch도 skip되고
  // 함수별 상세가 기본 노출된다(탭 버튼·AI 콘텐츠 미노출). 백엔드 ai-guide 엔드포인트는 유지.
  it('탭 통합: AI 요약 탭이 숨겨지고 함수별 상세가 기본 노출된다(SHOW_AI_GUIDE_TAB=false)', async () => {
    const { post } = await import('../api.js');
    const aiGuideCalls = [];
    post.mockImplementation((url) => {
      if (url === '/api/impact/ai-guide') aiGuideCalls.push(url);
      return Promise.resolve({ ok: false });
    });
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
    // 함수별 상세가 기본 노출(직접 변경 + 간접 영향), 'AI 요약' 탭 버튼·콘텐츠 미노출
    await waitFor(() => expect(screen.getByText(/직접 변경 \+ 간접 영향/)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /^AI 요약/ })).not.toBeInTheDocument();
    expect(screen.queryByText(/테스트 추가 제안/)).not.toBeInTheDocument();
    // ai-guide LLM 호출 자체가 skip됨(불필요 비용 제거)
    expect(aiGuideCalls.length).toBe(0);
  });

  // (제거) STS-IMPACT-029/030: 'AI 요약' 탭 내부 테스트제안 함수명 클릭(renderFnRef) 검증 2건은
  //  SHOW_AI_GUIDE_TAB=false로 해당 탭이 렌더되지 않아 삭제. 공유 상세 모달 열림은 STS-IMPACT-015
  //  ('상세' 버튼 → ✕ 닫기)에서 계속 커버된다.
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
      if (url === '/api/jenkins/suts/extract-traceability') {
        // suts 전용 엔드포인트 → unit은 SUTS 문서 원본 케이스(S_MotorSpd), 함수는 소문자(s_motorspd)
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
    // SHOW_ASIL_COVERAGE=false: 커버리지 패널(Δ 비교불가·회귀 stat 포함)은 숨겨진다.
    expect(screen.queryByText(/같은 빌드 — Δ 비교 불가/)).not.toBeInTheDocument();
    expect(screen.queryByText('직전 대비 회귀')).not.toBeInTheDocument();
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

  // STS-IMPACT-039: 이름충돌 worst-copy 커버리지 노트 — 커버리지 패널 내부라 SHOW_ASIL_COVERAGE=false로 숨겨진다.
  it('커버리지: collision_worst_copy 노트는 커버리지 패널과 함께 숨겨진다(SHOW_ASIL_COVERAGE=false)', () => {
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
    // 커버리지 요약 카드(worst-copy 노트 포함)가 렌더되지 않음
    expect(screen.queryByText(/이름충돌 1개 함수는 여러 copy 중/)).not.toBeInTheDocument();
    expect(screen.queryByText(/커버리지 \(ASIL 타깃 대비\)/)).not.toBeInTheDocument();
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
      // suts 경로 — 전용 /suts 엔드포인트가 SwUFn을 품은 SUTS TC로 SwUFn→함수명 맵 구성
      if (url === '/api/jenkins/suts/extract-traceability') {
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
      if (url === '/api/jenkins/suts/extract-traceability') {
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
      if (url === '/api/jenkins/suts/extract-traceability') {
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

  // STS-IMPACT-051: 문서 카드에 예측 대신 백엔드 doc_content의 실제 문서 내용(UDS/SUTS/SDS)이 표시된다.
  it('실제 문서 내용: 모달 DOC_CARDS에 doc_content의 UDS/SUTS/SDS 실 내용이 표시된다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_foo: 'BODY' },
        change_details: { s_foo: { before: 'void s_foo(void)' } },
        impact: { direct: ['s_foo'] },
        function_meta: { s_foo: { asil: 'A', evidence: 'line' } },
        doc_content: {
          uds: { s_foo: { description: 'Foo controls the motor speed', prototype: 'void s_foo(uint8 x)', globals: ['g_State'], calls: ['s_helper'] } },
          suts: { s_foo: [{ tc_id: 'SwUTC_SwUFn_0215', action: 'Call s_foo boundary', precondition: 'init', inputs: { x: '1' }, expected: { ret: '42' } }] },
          sds: { s_foo: 'SDS: foo handles motor control loop' },
        },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    await waitFor(() => expect(screen.getByText('📄 실제 UDS 내용')).toBeInTheDocument());
    expect(screen.getByText('Foo controls the motor speed')).toBeInTheDocument();       // 실 UDS 설명
    expect(screen.getByText('📄 실제 SUTS 시험 내용')).toBeInTheDocument();
    expect(screen.getByText(/Call s_foo boundary/)).toBeInTheDocument();                // 실 Test Action
    expect(screen.getByText('SwUTC_SwUFn_0215')).toBeInTheDocument();
    expect(screen.getByText('📄 실제 SDS 내용')).toBeInTheDocument();
    expect(screen.getByText(/foo handles motor control loop/)).toBeInTheDocument();     // 실 SDS 설명
  });

  // STS-IMPACT-052: doc_content 없는 문서는 "미파싱" 정직 표기(과대 추정 금지). 있는 문서는 실 내용.
  it('실제 문서 내용: doc_content 없는 문서는 "미파싱" 표기, 있는 문서(SDS)는 실 내용을 표시', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_bar: 'BODY' },
        change_details: { s_bar: { before: 'void s_bar(void)' } },
        impact: { direct: ['s_bar'] },
        function_meta: { s_bar: { asil: 'A', evidence: 'line' } },
        doc_content: { uds: {}, suts: {}, sds: { s_bar: 'SDS desc for bar' } }, // sds만 존재
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    await waitFor(() => expect(screen.getByText('📄 실제 SDS 내용')).toBeInTheDocument());
    expect(screen.getByText('SDS desc for bar')).toBeInTheDocument();
    // UDS/SUTS는 doc_content 비어 정직하게 '미파싱'
    expect(screen.getByText(/UDS 문서 내용 미파싱/)).toBeInTheDocument();
    expect(screen.getByText(/SUTS TC 내용 미파싱/)).toBeInTheDocument();
  });

  // STS-IMPACT-053: STS 카드도 예측이 아닌 실 파싱 내용(doc_content.sts_by_tc). 함수별 TC ID(SDS 브리지)를
  //  TC-ID 정규화 후 백엔드 내용 맵과 조인해 모달에 표시.
  it('실제 STS 내용: 모달 STS 카드에 sts_by_tc의 실 시험 설명이 TC-ID 조인으로 표시된다', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      if (url === '/api/jenkins/sds/extract-mapping') return Promise.resolve({ sds_pairs: [{ requirement_id: 'SwEI_01', component_ids: ['g_changed'] }] });
      if (url === '/api/jenkins/sts/extract-traceability') return Promise.resolve({ vcast_rows: [{ requirement_id: 'SwEI_01', testcase: 'SwTC_STS_01' }] });
      return Promise.resolve({ ok: false });
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'], scm_id: 'kjpds02' },
        changed_function_types: { g_changed: 'BODY' },
        impact: { direct: ['g_changed'] },
        function_meta: { g_changed: { asil: 'A', evidence: 'line' } },
        _linked_docs: { sts: 'U:/sts.xlsm', sds: 'U:/sds.docx' },
        // 백엔드 키는 정규화(공백제거+대문자). 프론트가 TC 'SwTC_STS_01'을 동일 정규화해 조인.
        doc_content: { sts_by_tc: { SWTC_STS_01: { description: 'STS verifies boundary handling', precondition: 'system initialized', test_method: 'REQ' } } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(within(dialog).getByText('📄 실제 STS 시험 내용')).toBeInTheDocument());
    expect(within(dialog).getByText('STS verifies boundary handling')).toBeInTheDocument();
  });

  // STS-IMPACT-053b: UDS 카드 '원문 → 변경안'(결정론) — SIGNATURE의 Prototype(현재→cd.after)을 짝짓는다.
  it('원문→변경안: SIGNATURE UDS 카드에 Prototype 현재값→변경후값이 결정론으로 표시된다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_foo: 'SIGNATURE' },
        change_details: { s_foo: { before: 'void s_foo(void)', after: 'void s_foo(uint8 x)' } },
        impact: { direct: ['s_foo'] },
        function_meta: { s_foo: { asil: 'A', evidence: 'line' } },
        doc_content: { uds: { s_foo: { description: 'foo', prototype: 'void s_foo(void)', globals: [] } } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    const dialog = await screen.findByRole('dialog');
    // '✏ 원문 → 변경안 (결정론)' 블록 + Prototype 현재(−)·변경후(＋)
    await waitFor(() => expect(within(dialog).getByText(/원문 → 변경안 \(결정론\)/)).toBeInTheDocument());
    expect(within(dialog).getAllByText(/− void s_foo\(void\)/).length).toBeGreaterThanOrEqual(1);
    expect(within(dialog).getAllByText(/＋ void s_foo\(uint8 x\)/).length).toBeGreaterThanOrEqual(1);
  });

  // STS-IMPACT-053b2: 링크(cloudium) UDS의 prototype(백엔드 fallback 파서가 표에서 추출)이
  //  UDS 카드에 실 선언으로 표시되고, SIGNATURE 원문→변경안의 '− 원문' 기준선으로도 쓰인다.
  it('원문→변경안: 링크 UDS prototype이 카드 실 내용 + 원문 기준선으로 표시된다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_foo: 'SIGNATURE' },
        change_details: { s_foo: { before: 'void s_foo(void)', after: 'void s_foo(uint8 x)' } },
        impact: { direct: ['s_foo'] },
        function_meta: { s_foo: { asil: 'A', evidence: 'line' } },
        // 링크 문서: globals/calls 없이 description+prototype만(fallback 파서 산출)
        doc_content: { uds: { s_foo: { description: 'foo', prototype: 'void s_foo(void)' } } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(within(dialog).getByText('📄 실제 UDS 내용')).toBeInTheDocument());
    // prototype이 UDS 카드 실 내용으로 표시(renderDocContent) + 원문→변경안 기준선(− prototype)
    expect(within(dialog).getAllByText(/void s_foo\(void\)/).length).toBeGreaterThanOrEqual(2);
    expect(within(dialog).getByText(/원문 → 변경안 \(결정론\)/)).toBeInTheDocument();
    expect(within(dialog).getAllByText(/＋ void s_foo\(uint8 x\)/).length).toBeGreaterThanOrEqual(1);
  });

  // STS-IMPACT-054: 미파싱(문서 내용 없음) → 막다른 '미파싱' 대신 결정론 작성 골격 + 경계값 TC.
  //  UDS 카드는 Name/Prototype 신규 골격, SUTS 카드는 파라미터 타입에서 유도한 실제 경계값(U16→65535).
  it('작성 제안: 미파싱 UDS/SUTS에 결정론 작성 골격 + 경계값(U16→65535)이 표시된다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_bar: 'SIGNATURE' },
        change_details: { s_bar: { before: 'void s_bar(void)', after: 'void s_bar(U16 idx)' } },
        impact: { direct: ['s_bar'] },
        function_meta: { s_bar: { asil: 'B', evidence: 'line' } },
        // doc_content 없음 → uds/suts/sds 전부 미파싱 → 작성 골격이 대신 뜬다
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    const dialog = await screen.findByRole('dialog');
    // UDS: 신규 작성 골격(문서에 현재 없음) + Prototype 골격
    await waitFor(() => expect(within(dialog).getByText(/UDS 작성 제안/)).toBeInTheDocument());
    expect(within(dialog).getAllByText(/void s_bar\(U16 idx\)/).length).toBeGreaterThanOrEqual(1);
    // SUTS: 파라미터 U16 idx에서 유도한 실제 경계값(결정론, 일반 문구 아님)
    expect(within(dialog).getByText(/SUTS 작성 제안 \(경계값 TC 골격\)/)).toBeInTheDocument();
    expect(within(dialog).getByText('MAX=65535')).toBeInTheDocument();
    expect(within(dialog).getByText('MIN=0')).toBeInTheDocument();
  });

  // STS-IMPACT-055: 요구 매핑 없는 함수의 STS는 가짜 TC를 만들지 않고 '작성 대상 아님'을 정직 표기(ISO 정직성).
  it('작성 제안: 요구 매핑 없는 함수의 STS는 가짜 TC 대신 정직 표기', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { prv_helper: 'BODY' },
        change_details: { prv_helper: { before: '' } },
        impact: { direct: ['prv_helper'] },
        function_meta: { prv_helper: { asil: 'A', evidence: 'line' } },
        // 요구/문서 매핑 없음(static private 헬퍼)
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(within(dialog).getByText(/요구 매핑 없음 — STS.*작성 대상 아님/)).toBeInTheDocument());
    // SDS도 static private 가능성 정직 노트
    expect(within(dialog).getByText(/설계상 없을 수 있음\(정상\)/)).toBeInTheDocument();
  });

  // STS-IMPACT-056: 간접(직접 변경 아님) 함수 모달엔 작성 골격·경계값을 제안하지 않는다 —
  //  '직접 변경 아님·문서 수정 없음'(편집 액션)과 모순 방지. UDS content가 있어도(유혹) 비변경이면 제안 없음.
  it('작성 제안: 간접(비변경) 함수엔 작성 골격·경계값을 제안하지 않는다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_changed: 'SIGNATURE' },
        change_details: { s_changed: { before: 'void s_changed(void)', after: 'void s_changed(U16 idx)' } },
        impact: { direct: ['s_changed'], indirect_1hop: ['g_indirect'], indirect_2hop: [] },
        impact_paths: { g_indirect: { hop: 1, via: 's_changed', seed: 's_changed' } },
        function_meta: { s_changed: { asil: 'A' }, g_indirect: { asil: 'B' } },
        doc_content: { uds: { g_indirect: { prototype: 'void g_indirect(U16 n)' } } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    const rows = await screen.findAllByRole('button', { name: '상세' });
    await user.click(rows[rows.length - 1]);  // g_indirect(간접)
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(within(dialog).getAllByText(/계약|직접 변경 아님/).length).toBeGreaterThanOrEqual(1));
    expect(within(dialog).queryByText(/작성 제안/)).toBeNull();      // 작성 골격 없음
    expect(within(dialog).queryByText('MAX=65535')).toBeNull();       // 경계값 골격 없음
  });

  // STS-IMPACT-057: DELETE(삭제) 함수엔 경계값 작성 골격을 제안하지 않는다 — 삭제는 '작성'이 아니라
  //  '제거'(편집 액션 패널 담당). 삭제된 함수에 '이 경계값 TC를 작성' 제안은 오지시.
  it('작성 제안: DELETE 함수엔 경계값 작성 골격을 제안하지 않는다(제거 대상)', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_gone: 'DELETE' },
        change_details: { s_gone: { before: 'void s_gone(U16 idx)' } },
        impact: { direct: ['s_gone'] },
        function_meta: { s_gone: { asil: 'A', evidence: 'line' } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(within(dialog).getByText(/해당 함수 항목 제거/)).toBeInTheDocument());  // 제거 안내(편집 액션)
    expect(within(dialog).queryByText(/작성 제안/)).toBeNull();
    expect(within(dialog).queryByText('MAX=65535')).toBeNull();
  });

  // STS-IMPACT-058: 공개 함수(g_)의 SDS/STS 부재는 '정상'이 아니라 실 갭일 수 있으므로 '정상' 안심을
  //  붙이지 않는다(은폐 방지). static(s_/prv_)만 '설계상 대상 아님' 정직 노트.
  it('작성 제안: 공개 함수(g_)의 SDS/STS 부재엔 "정상" 안심을 붙이지 않는다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { g_public: 'BODY' },
        change_details: { g_public: { before: 'void g_public(void)' } },
        impact: { direct: ['g_public'] },
        function_meta: { g_public: { asil: 'B', evidence: 'line' } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    const dialog = await screen.findByRole('dialog');
    // 공개 함수: STS는 '확인 필요'(갭 가능성), '설계상 대상 아님(정상)' 오안심 없어야
    await waitFor(() => expect(within(dialog).getByText(/STS 요구 매핑 확인 필요/)).toBeInTheDocument());
    expect(within(dialog).queryByText(/설계상 없을 수 있음\(정상\)/)).toBeNull();
  });

  // STS-IMPACT-053c: fetchExplanation 페이로드에 doc_content(현재 문서 원문)가 실린다 — LLM '원문→제안' 근거.
  it('원문→제안: AI 문장 재작성 요청 시 doc_content(현재 UDS/SDS 원문)가 페이로드에 실린다', async () => {
    const { post } = await import('../api.js');
    const calls = [];
    post.mockImplementation((url, body) => {
      if (url === '/api/impact/explain-change') { calls.push(body); return Promise.resolve({ ok: true, explanation: '원문→제안' }); }
      return Promise.resolve({ ok: false });
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_foo: 'BODY' },
        change_details: { s_foo: { before: 'void s_foo(void)' } },
        impact: { direct: ['s_foo'] },
        function_meta: { s_foo: { asil: 'A', evidence: 'line' } },
        doc_content: {
          uds: { s_foo: { description: '튜닝값 읽기', prototype: 'void s_foo(void)', globals: ['g_State'] } },
          sds: { s_foo: 'SDS: foo 컴포넌트' },
        },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    await user.click(await screen.findByRole('button', { name: /AI 문장 재작성/ }));
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(1));
    const body = calls[calls.length - 1];
    expect(body.doc_content).toBeTruthy();
    expect(body.doc_content.uds.description).toBe('튜닝값 읽기');   // 현재 UDS 원문 전달
    expect(body.doc_content.sds).toBe('SDS: foo 컴포넌트');          // 현재 SDS 원문 전달
  });

  // STS-IMPACT-053d: STS TC 원문이 페이로드에 실린다 — buildDocContentForFn은 guide→guideDetailByLc에
  //  의존하므로, fetchExplanation deps에 buildDocContentForFn이 없으면(stale closure, deep-review Critical)
  //  guide 채워지기 전 빈 guideDetailByLc에 영구 결속돼 STS/SITS TC가 영구 누락된다. 이 테스트가 회귀 가드.
  it('원문→제안: STS TC 원문이 doc_content.sts로 페이로드에 실린다(stale closure 회귀 가드)', async () => {
    const { post } = await import('../api.js');
    const calls = [];
    post.mockImplementation((url, body) => {
      if (url === '/api/impact/explain-change') { calls.push(body); return Promise.resolve({ ok: true, explanation: 'x' }); }
      // SDS 브리지: 함수→요구, STS: 요구→TC (guide.details의 stsTestCases 채움)
      if (url === '/api/jenkins/sds/extract-mapping') return Promise.resolve({ sds_pairs: [{ requirement_id: 'SwEI_9', component_ids: ['s_foo'] }] });
      if (url === '/api/jenkins/sts/extract-traceability') return Promise.resolve({ vcast_rows: [{ requirement_id: 'SwEI_9', testcase: 'SwTC_STS_9' }] });
      return Promise.resolve({ ok: false });
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'], scm_id: 'kjpds02' },
        changed_function_types: { s_foo: 'BODY' },
        change_details: { s_foo: { before: 'void s_foo(void)' } },
        // ⚠ function_diffs 제공 필수 — 없으면 functionDiffs=`?? {}`가 매 렌더 새 객체라
        // fetchExplanation이 매 렌더 재생성돼 stale closure 버그가 가려진다(deep-review가 지적한
        // 053c 테스트 갭). 세 deps를 전부 안정 참조로 만들어야 buildDocContentForFn 누락이 드러남.
        function_diffs: { s_foo: '@@ -1 +1 @@\n-a\n+b' },
        impact: { direct: ['s_foo'] },
        function_meta: { s_foo: { asil: 'A', evidence: 'line' } },
        _linked_docs: { sts: 'U:/sts.xlsm', sds: 'U:/sds.docx' },
        doc_content: {
          uds: { s_foo: { description: 'foo' } },
          sts_by_tc: { SWTC_STS_9: { description: 'STS 경계 시험', test_method: 'REQ' } },
        },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    await user.click(await screen.findByRole('button', { name: /AI 문장 재작성/ }));
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(1));
    const body = calls[calls.length - 1];
    // guide 채워진 뒤의 buildDocContentForFn이 STS TC를 조인해 페이로드에 실어야 함(stale면 빈 배열→누락)
    expect(Array.isArray(body.doc_content.sts)).toBe(true);
    expect(body.doc_content.sts.length).toBeGreaterThanOrEqual(1);
    expect(body.doc_content.sts[0].description).toBe('STS 경계 시험');
  });

  // STS-IMPACT-053e: 간접영향 함수 모달에 "왜 간접인지"(via/seed 콜체인 근거)가 표시된다.
  it('간접영향 근거: 간접 함수 모달에 경유 노드(via)·변경함수(seed)가 표시된다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_changed: 'BODY' },
        change_details: { s_changed: { before: 'void s_changed(void)' } },
        // g_indirect는 변경 안 됐지만 s_changed→g_via 경유로 2-hop 영향
        impact: { direct: ['s_changed'], indirect_1hop: ['g_via'], indirect_2hop: ['g_indirect'] },
        impact_paths: {
          g_via: { hop: 1, via: 's_changed', seed: 's_changed' },
          g_indirect: { hop: 2, via: 'g_via', seed: 's_changed' },
        },
        function_meta: { s_changed: { asil: 'A' }, g_indirect: { asil: 'B' } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    // 간접 함수 g_indirect 행의 '상세' 클릭 → 모달에 seed/via 근거
    const rows = await screen.findAllByRole('button', { name: '상세' });
    // g_indirect 행 찾기(2-hop) — 함수명으로 모달 열기
    await user.click(rows[rows.length - 1]);
    const dialog = await screen.findByRole('dialog');
    // 간접영향 근거: 변경함수 s_changed가 모달에 노출(뱃지 + 안내문 여러 곳)
    expect(within(dialog).getAllByText(/s_changed/).length).toBeGreaterThanOrEqual(1);
    // '왜 간접인지' 안내에 경유/호출 관계 문구 + 경유 노드 g_via
    expect(within(dialog).getAllByText(/호출 관계/).length).toBeGreaterThanOrEqual(1);
    expect(within(dialog).getAllByText(/g_via/).length).toBeGreaterThanOrEqual(1);
  });

  // STS-IMPACT-053f: 간접 함수 AI 재작성 시 impact_path(경로 근거)가 페이로드에 실린다.
  it('간접영향 근거: 간접 함수 AI 요청 시 impact_path(via/seed)가 페이로드에 실린다', async () => {
    const { post } = await import('../api.js');
    const calls = [];
    post.mockImplementation((url, body) => {
      if (url === '/api/impact/explain-change') { calls.push(body); return Promise.resolve({ ok: true, explanation: 'x' }); }
      return Promise.resolve({ ok: false });
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_changed: 'BODY' },
        change_details: { s_changed: { before: 'void s_changed(void)' } },
        impact: { direct: ['s_changed'], indirect_1hop: ['g_indirect'], indirect_2hop: [] },
        impact_paths: { g_indirect: { hop: 1, via: 's_changed', seed: 's_changed' } },
        function_meta: { s_changed: { asil: 'A' }, g_indirect: { asil: 'B' } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    const rows = await screen.findAllByRole('button', { name: '상세' });
    await user.click(rows[rows.length - 1]);  // g_indirect(간접)
    await user.click(await screen.findByRole('button', { name: /AI 문장 재작성/ }));
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(1));
    const body = calls[calls.length - 1];
    expect(body.impact_path).toBeTruthy();
    expect(body.impact_path.seed).toBe('s_changed');
    expect(body.impact_path.hop).toBe('1-hop');
  });

  // STS-IMPACT-061: STS 카드에 Test Action(시험 절차)·Expected Result(기대결과)가 표시된다(라운드 후속).
  //  ⚠ STS expected는 string(SITS/SUTS의 kv dict 아님) → 직접 렌더(Object.entries 금지 → [object Object] 방지).
  it('실제 STS 내용: test_action(Action)·expected(Exp, string)가 모달에 표시된다', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      if (url === '/api/jenkins/sds/extract-mapping') return Promise.resolve({ sds_pairs: [{ requirement_id: 'SwEI_02', component_ids: ['g_changed'] }] });
      if (url === '/api/jenkins/sts/extract-traceability') return Promise.resolve({ vcast_rows: [{ requirement_id: 'SwEI_02', testcase: 'SwTC_STS_02' }] });
      return Promise.resolve({ ok: false });
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'], scm_id: 'kjpds02' },
        changed_function_types: { g_changed: 'BODY' },
        impact: { direct: ['g_changed'] },
        function_meta: { g_changed: { asil: 'A', evidence: 'line' } },
        _linked_docs: { sts: 'U:/sts.xlsm', sds: 'U:/sds.docx' },
        doc_content: { sts_by_tc: { SWTC_STS_02: {
          description: 'overvoltage cutoff verify',
          test_action: '1) apply 5.5V to input 2) wait 100ms',
          expected: 'relay OFF, DTC 0xC101 set',
        } } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(within(dialog).getByText('📄 실제 STS 시험 내용')).toBeInTheDocument());
    expect(within(dialog).getByText('1) apply 5.5V to input 2) wait 100ms')).toBeInTheDocument();  // Action(_prose 통과)
    expect(within(dialog).getByText('relay OFF, DTC 0xC101 set')).toBeInTheDocument();               // Exp(string 직접 렌더)
    expect(within(dialog).queryByText(/\[object Object\]/)).toBeNull();                                // string 오처리(dict화) 방지
  });

  // STS-IMPACT-054: SITS 카드 실 내용(doc_content.sits_by_tc) — SwUFn 브리지 TC ID를 정규화 조인해
  //  중간 JSON의 sub_case(사전조건/기대값)를 표시.
  it('실제 SITS 내용: 모달 SITS 카드에 sits_by_tc의 sub_case 사전조건/기대값이 표시된다', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      if (url === '/api/jenkins/suts/extract-traceability') return Promise.resolve({ vcast_rows: [{ unit: 's_hash', testcase: 'SwUTC_SwUFn_0127' }] });
      if (url === '/api/jenkins/sits/extract-traceability') return Promise.resolve({ vcast_rows: [{ requirement_id: 'SYSTEMTM_1', testcase: 'SwITC_SwUFn_0127' }] });
      return Promise.resolve({ ok: false });
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'], scm_id: 'kjpds02' },
        changed_function_types: { s_hash: 'BODY' },
        impact: { direct: ['s_hash'] },
        function_meta: { s_hash: { asil: 'A', evidence: 'line' } },
        _linked_docs: { suts: 'U:/suts.xlsm', sits: 'U:/sits.xlsm' },
        doc_content: { sits_by_tc: { SWITC_SWUFN_0127: { call_chain: 's_hash -> s_crc', sub_cases: [{ precondition: 'buffer ready', inputs: { len: '8' }, expected: { crc: '0xAB' } }] } } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(within(dialog).getByText('📄 실제 SITS 시험 내용')).toBeInTheDocument());
    expect(within(dialog).getByText('buffer ready')).toBeInTheDocument();      // sub_case 사전조건(prose)
    expect(within(dialog).getByText(/crc=0xAB/)).toBeInTheDocument();          // 실 기대값
  });

  // STS-IMPACT-055: TC는 매칭되나 내용 맵이 비면 과대추정 없이 정직 '미파싱' 표기.
  it('정직 미파싱: STS TC는 매칭되나 sts_by_tc 내용이 없으면 "미파싱"으로 표기한다', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      if (url === '/api/jenkins/sds/extract-mapping') return Promise.resolve({ sds_pairs: [{ requirement_id: 'SwEI_01', component_ids: ['g_changed'] }] });
      if (url === '/api/jenkins/sts/extract-traceability') return Promise.resolve({ vcast_rows: [{ requirement_id: 'SwEI_01', testcase: 'SwTC_STS_01' }] });
      return Promise.resolve({ ok: false });
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'], scm_id: 'kjpds02' },
        changed_function_types: { g_changed: 'BODY' },
        impact: { direct: ['g_changed'] },
        function_meta: { g_changed: { asil: 'A', evidence: 'line' } },
        _linked_docs: { sts: 'U:/sts.xlsm', sds: 'U:/sds.docx' },
        doc_content: { sts_by_tc: {} },   // TC는 매칭되나 내용 없음(파서 미매칭/미연동)
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(within(dialog).getByText(/STS TC 내용 미파싱/)).toBeInTheDocument());
  });

  // STS-IMPACT-056: BODY인데 evidence='file_fatten'(파일 단위 영향)이면 모달이 권위 evidence를 소비해
  //  '파일영향' 꼬리표 + 파일 단위 영향 안내를 표시(옛 fd/cd 추론과 무관, 리스트와 일치).
  it('BODY 무증거: file_fatten 함수는 모달에 "파일영향" 꼬리표와 파일 단위 영향 안내를 표시한다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_fatten: 'BODY' },
        impact: { direct: ['s_fatten'] },
        function_meta: { s_fatten: { asil: 'A', evidence: 'file_fatten' } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(within(dialog).getByText('파일영향')).toBeInTheDocument());
    expect(within(dialog).getByText(/본문 변경 원문이 없는 것이 정상/)).toBeInTheDocument();  // fatten 안내(고유)
    expect(within(dialog).queryByText('원문 절단')).not.toBeInTheDocument();
  });

  // STS-IMPACT-057: BODY evidence='line'인데 본문 원문이 없으면(400KB 절단·로컬/cloudium diff) fatten이
  //  아니라 '원문 절단'으로 구분 표기 — 옛 추론은 이를 fatten으로 오표기했다.
  it('BODY 원문절단: evidence=line인데 원문 없으면 "원문 절단"으로 표기하고 파일영향으로 오표기하지 않는다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_trunc: 'BODY' },
        impact: { direct: ['s_trunc'] },
        function_meta: { s_trunc: { asil: 'A', evidence: 'line' } },   // 실 변경이나 원문(diff/details) 없음
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    const dialog = await screen.findByRole('dialog');
    await waitFor(() => expect(within(dialog).getByText('원문 절단')).toBeInTheDocument());
    expect(within(dialog).getByText(/크기 상한/)).toBeInTheDocument();   // #2: 절단 원인을 크기 상한으로 정직화
    expect(within(dialog).queryByText('파일영향')).not.toBeInTheDocument();   // fatten 아님
  });

  // STS-IMPACT-058: 데모 모드는 합성 함수(evidence 없음)라 functionHasNoEvidence가 true지만, 데모는
  //  '탐지 예시'이므로 변경 상세 목록의 '파일영향' 배지를 억제한다(reviewer W1 — 게이트 제거 부작용 방지).
  it('데모 모드: 변경 상세 목록에 "파일영향" 배지가 뜨지 않는다(데모는 탐지 예시)', async () => {
    const user = userEvent.setup();
    render(<ImpactGuideSection job={mockJob} analysisResult={null} />);
    await user.click(screen.getByText(/데모 시나리오로 보기/));
    await waitFor(() => expect(screen.getByText(/변경 영향도 요약/)).toBeInTheDocument());
    expect(screen.queryByText('파일영향')).not.toBeInTheDocument();
  });

  // STS-IMPACT-059: 콜체인 채굴 — SITS TC의 chain_fns(Interface 콜체인)에 등장하는 깊은 callee가 entry
  //  SwUFn이 아니어도 그 SITS TC를 획득한다(g_drvin 같은 함수의 SITS 0 해소).
  it('SITS 콜체인: chain_fns의 깊은 callee가 그 SITS TC를 획득한다', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      if (url === '/api/jenkins/sits/extract-traceability') return Promise.resolve({ vcast_rows: [
        { requirement_id: 'SYSTEMTM_1', testcase: 'SwITC_SwUFn_0112', chain_fns: ['main', 's_sysmain_init', 'g_drvin_drv8706sq_init'] },
      ] });
      return Promise.resolve({ ok: false });
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['DrvIn.c'], scm_id: 'kjpds02' },
        changed_function_types: { g_drvin_drv8706sq_init: 'BODY' },
        impact: { direct: ['g_drvin_drv8706sq_init'] },
        function_meta: { g_drvin_drv8706sq_init: { asil: 'A' } },
        _linked_docs: { sits: 'U:/sits.xlsm' },   // suts 없이도 콜체인 경로로 조인(entry SwUFn 무관)
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText('SITS 영향 TC')).toBeInTheDocument());
    const sitsCard = screen.getByText('SITS 영향 TC').closest('.stat-card');
    expect(within(sitsCard).getByText('1')).toBeInTheDocument();   // 콜체인으로 1 TC(entry 아닌 깊은 callee)
    await user.click(screen.getByRole('button', { name: '상세' }));
    await waitFor(() => expect(screen.getByText('SwITC_SwUFn_0112')).toBeInTheDocument());
  });

  // STS-IMPACT-060: FI TC(SwITC_FI_SwFn_*)의 SwFn 토큰도 인식(_SWUFN_RE parity) — 과거 /Sw[UI]Fn_/는 탈락.
  it('SITS FI: testcase의 SwFn(Fault Injection) 토큰도 SUTS unit으로 풀어 함수에 연결한다', async () => {
    const { post } = await import('../api.js');
    post.mockImplementation((url) => {
      if (url === '/api/jenkins/suts/extract-traceability') return Promise.resolve({ vcast_rows: [{ unit: 's_fi_target', testcase: 'SwUTC_SwFn_34' }] });
      if (url === '/api/jenkins/sits/extract-traceability') return Promise.resolve({ vcast_rows: [{ requirement_id: 'SYSTEMTM_1', testcase: 'SwITC_FI_SwFn_34' }] });
      return Promise.resolve({ ok: false });
    });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Fi.c'], scm_id: 'kjpds02' },
        changed_function_types: { s_fi_target: 'BODY' },
        impact: { direct: ['s_fi_target'] },
        function_meta: { s_fi_target: { asil: 'A' } },
        _linked_docs: { suts: 'U:/suts.xlsm', sits: 'U:/sits.xlsm' },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await waitFor(() => expect(screen.getByText('SITS 영향 TC')).toBeInTheDocument());
    // SwFn_34가 양변(SUTS unit·SITS testcase)에서 매칭돼 SITS TC=1 (구 /Sw[UI]Fn_/였다면 0)
    const sitsCard = screen.getByText('SITS 영향 TC').closest('.stat-card');
    expect(within(sitsCard).getByText('1')).toBeInTheDocument();
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

describe('extractDiffElements noSemanticChange (포맷/이동만 — 의미 변경 없음)', () => {
  it('블록 이동(-/+ 동일)은 true', () => {
    const fd = [
      '@@ -10,4 +50,4 @@ void host(void)',
      '-static void s_Foo( U8 a );',
      '-{',
      '-    do_work(a);',
      '-}',
      '+static void s_Foo( U8 a );',
      '+{',
      '+    do_work(a);',
      '+}',
    ].join('\n');
    expect(extractDiffElements(fd).noSemanticChange).toBe(true);
  });

  it('단일 선언 이동(-proto; +proto; 동일)은 true', () => {
    const fd = '@@ -5,1 +9,1 @@\n-static void s_Calc( S16 *p );\n+static void s_Calc( S16 *p );';
    expect(extractDiffElements(fd).noSemanticChange).toBe(true);
  });

  it('재들여쓰기(공백만 다름)는 true(trim 정규화)', () => {
    const fd = '@@ -1,2 +1,2 @@ void f(void)\n-    x = 1;\n+  x = 1;';
    expect(extractDiffElements(fd).noSemanticChange).toBe(true);
  });

  it('실 로직 변경은 false', () => {
    const fd = '@@ -1,1 +1,1 @@ void f(void)\n-    return a;\n+    return a + 1;';
    expect(extractDiffElements(fd).noSemanticChange).toBe(false);
  });

  it('문장 재정렬(멀티셋 동일·순서 다름)은 false(오탐 방지)', () => {
    const fd = '@@ -1,2 +1,2 @@ void f(void)\n-    a = 1;\n-    b = a;\n+    b = a;\n+    a = 1;';
    expect(extractDiffElements(fd).noSemanticChange).toBe(false);
  });

  it('truncated diff(…줄 생략)는 판정 보류(false)', () => {
    const fd = '@@ -1,1 +1,1 @@ void f(void)\n-    x = 1;\n+    x = 1;\n… (+40줄 생략)';
    expect(extractDiffElements(fd).noSemanticChange).toBe(false);
  });

  it('추가만(신규)·삭제만은 false', () => {
    expect(extractDiffElements('@@ -1,0 +1,2 @@\n+void n(void)\n+{}').noSemanticChange).toBe(false);
    expect(extractDiffElements('@@ -1,2 +1,0 @@\n-void o(void)\n-{}').noSemanticChange).toBe(false);
  });
});

describe('matchFileDiff (#3 파일레벨 폴백 경로 매칭)', () => {
  const fileDiffs = {
    'sources/app/foo.c': 'DIFF_FOO',
    'lib/bar.h': 'DIFF_BAR',
    'sources/led.c': 'DIFF_LED',
  };
  it('절대 Windows 경로 → 정규화 상대 키 suffix 매칭', () => {
    expect(matchFileDiff('C:\\Project\\Ados\\NE1AW\\Sources\\APP\\Foo.c', fileDiffs)).toBe('DIFF_FOO');
    expect(matchFileDiff('D:/x/Lib/Bar.h', fileDiffs)).toBe('DIFF_BAR');
  });
  it('경계 없는 suffix 오매칭 방지(/ 경계)', () => {
    expect(matchFileDiff('C:\\x\\Sources\\myled.c', fileDiffs)).toBe('');   // myled.c ≠ led.c
  });
  it('최장(가장 구체적) 매칭', () => {
    const fd = { 'foo.c': 'SHORT', 'app/foo.c': 'LONG' };
    expect(matchFileDiff('C:\\x\\app\\foo.c', fd)).toBe('LONG');
  });
  it('미매칭·빈 입력은 빈 문자열', () => {
    expect(matchFileDiff('', fileDiffs)).toBe('');
    expect(matchFileDiff('C:\\x\\nope.c', fileDiffs)).toBe('');
    expect(matchFileDiff('C:\\x\\foo.c', null)).toBe('');
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

/* ── 빌드/리비전 소스 바 + 결과 영속 ─────────────────────────────────────── */
describe('ImpactGuideSection — 빌드/리비전 소스 바 & 결과 영속', () => {
  const IMPACT_KEY = 'devops_v2_impact_current';
  const mockJob = { url: 'http://jenkins.example.com/job/test-job/' };

  const mkImpact = ({ scm = 'hdpdm01', build = 412, rev = '1042', base = '527' } = {}) => ({
    trigger: {
      scm_id: scm,
      changed_files: ['Ap_MotorCtrl.c'],
      metadata: {
        build_number: build, build_revision: rev, baseline_revision: base,
        changed_files_source: 'svn_revision_range', job_url: mockJob.url,
      },
    },
    changed_function_types: { g_MotorCtrl: 'BODY' },
    actions: {},
    impact: { direct: ['g_MotorCtrl'], indirect_1hop: [], indirect_2hop: [] },
  });

  // 실제 buildGuide 산출물 형태 — summary가 없으면 스토어가 렌더 불가로 판단해 떨군다.
  const mkGuide = (fn) => ({
    details: [{ function: fn, changeType: 'BODY' }],
    fetchFailures: [],
    summary: { impactedReqs: 0, impactedStsTCs: 0, impactedSitsTCs: 0, stsTcReason: '', sitsTcReason: '' },
  });

  // 저장분은 반드시 현재 스키마 버전을 달아야 한다 — 안 달면 loadImpactCurrent가 폐기해
  // 테스트가 '아무 일도 안 일어나서' 통과하는 vacuous pass가 된다.
  const seedStore = (entry) => localStorage.setItem(
    IMPACT_KEY, JSON.stringify({ v: STORE_VERSION, savedAt: Date.now(), ...entry }),
  );

  const historyItem = (over = {}) => ({
    job_id: 'impact_1', status: 'completed', created_at: '2026-07-19T10:00:00',
    metadata: { build_number: 410, build_revision: '1030' },
    summary: { changed_files: 3 },
    ...over,
  });

  let api;
  let post;

  beforeEach(async () => {
    vi.clearAllMocks();  // setAnalysisResult 등 App.jsx mock의 호출 이력도 테스트 간 격리
    ({ api, post } = await import('../api.js'));
    // clearAllMocks는 구현(mockResolvedValue)을 지우지 않아 앞 테스트가 새어나온다 → reset 후 기본값.
    api.mockReset();
    post.mockReset();
    localStorage.clear();
    api.mockResolvedValue({ items: [] });
    post.mockResolvedValue({});
  });

  it('빈 상태에서도 소스 바(분석 이력·빌드 선택)가 렌더된다', () => {
    // 결과가 없을 때야말로 '이력에서 불러오기'가 필요하므로 빈 상태에서 사라지면 안 된다.
    render(<ImpactGuideSection job={mockJob} analysisResult={null} />);

    expect(screen.getByText(/변경 영향도 분석 결과가 없습니다/)).toBeInTheDocument();
    expect(screen.getByLabelText('분석 이력')).toBeInTheDocument();
    expect(screen.getByLabelText('빌드')).toBeInTheDocument();
  });

  it('결과가 있으면 빌드/리비전/변경출처가 라벨로 표시된다', () => {
    render(<ImpactGuideSection job={mockJob} analysisResult={{ impactData: mkImpact() }} />);

    const label = screen.getByTestId('impact-target-label');
    expect(label).toHaveTextContent('hdpdm01');
    expect(label).toHaveTextContent('빌드 #412');
    expect(label).toHaveTextContent('r1042');
    expect(label).toHaveTextContent('기준 r527');
    expect(screen.getByText('SVN 리비전 범위')).toBeInTheDocument();
  });

  it('빌드 시각 revision 미확인(HEAD 폴백)이면 라벨에 경고를 표시한다', () => {
    // build_revision_is_head=true → r값이 '이 빌드가 실제 빌드한 revision'이 아니라 현재
    // HEAD임을 명시(침묵 fail-open 대체). 이 표식이 사라지면 옛 오보고가 되살아난다.
    const impact = mkImpact({ rev: '1077' });
    impact.trigger.metadata.build_revision_is_head = true;
    render(<ImpactGuideSection job={mockJob} analysisResult={{ impactData: impact }} />);

    const label = screen.getByTestId('impact-target-label');
    expect(label).toHaveTextContent('r1077');
    expect(label).toHaveTextContent(/HEAD/);
    expect(label).toHaveTextContent(/빌드 리비전 미확인/);
  });

  it('빌드 선택 콤보박스 옵션에 per-build SVN 리비전이 표시되고 scm_id로 조회한다', async () => {
    post.mockImplementation((path) => {
      if (path === '/api/jenkins/builds') {
        return Promise.resolve({ builds: [{ number: 122, result: 'SUCCESS', revision: '1053' }] });
      }
      return Promise.resolve({});
    });
    render(<ImpactGuideSection job={mockJob} analysisResult={{ impactData: mkImpact() }} />);

    fireEvent.focus(screen.getByLabelText('빌드'));  // onFocus → loadBuildsOnce
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/jenkins/builds', expect.objectContaining({ scm_id: 'hdpdm01' })));
    expect(await screen.findByText(/#122 · r1053 · SUCCESS/)).toBeInTheDocument();
  });

  it('SCM이 바뀌면 빌드 캐시를 버려 새 SCM 리비전으로 재조회한다 (I4: stale 리비전 고착 방지)', async () => {
    // buildsReqRef 가드는 마운트당 1회 로드다. 리셋 effect가 jobUrl만 감시하면 scmId ''→실값
    // (또는 SCM 전환) 시 가드가 안 풀려 빌드가 옛 scm_id(또는 revision 없음)로 고착된다.
    post.mockImplementation((path) => (path === '/api/jenkins/builds'
      ? Promise.resolve({ builds: [{ number: 122, result: 'SUCCESS', revision: '1053' }] })
      : Promise.resolve({})));
    const { rerender } = render(
      <ImpactGuideSection job={mockJob} analysisResult={{ impactData: mkImpact({ scm: 'hdpdm01' }) }} />);
    fireEvent.focus(screen.getByLabelText('빌드'));
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/jenkins/builds', expect.objectContaining({ scm_id: 'hdpdm01' })));

    post.mockClear();
    rerender(<ImpactGuideSection job={mockJob} analysisResult={{ impactData: mkImpact({ scm: 'kjpds02_pv' }) }} />);
    fireEvent.focus(screen.getByLabelText('빌드'));
    // 가드가 풀려야 새 SCM으로 재조회된다(수정 전엔 재조회 없이 옛 SCM 빌드가 남음).
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/jenkins/builds', expect.objectContaining({ scm_id: 'kjpds02_pv' })));
  });

  it('이력 조회는 SCM id로 summary 모드를 호출한다', async () => {
    render(<ImpactGuideSection job={mockJob} analysisResult={{ impactData: mkImpact() }} />);

    await waitFor(() => expect(api).toHaveBeenCalledWith(
      expect.stringContaining('/api/scm/impact-jobs/hdpdm01?summary=1'),
    ));
  });

  it('이력 항목을 고르면 저장된 결과를 서버에서 불러온다', async () => {
    const user = userEvent.setup();
    api.mockImplementation(async (url) => {
      if (String(url).includes('/impact-jobs/')) return { items: [historyItem()] };
      if (String(url).includes('/result')) return { result: mkImpact({ build: 410, rev: '1030' }) };
      return {};
    });

    render(<ImpactGuideSection job={mockJob} analysisResult={{ impactData: mkImpact() }} />);

    const select = screen.getByLabelText('분석 이력');
    await waitFor(() => expect(within(select).getAllByRole('option').length).toBeGreaterThan(1));
    // 라벨에 빌드/리비전이 실려 어떤 실행인지 구분 가능해야 한다
    expect(within(select).getByText(/빌드 #410 · r1030/)).toBeInTheDocument();

    await user.selectOptions(select, 'impact_1');

    await waitFor(() => expect(api).toHaveBeenCalledWith(
      expect.stringContaining('/api/scm/impact-job/impact_1/result'),
    ));
  });

  it('영속: 로드된 결과가 빌드/리비전 식별자와 함께 localStorage에 저장된다', async () => {
    render(<ImpactGuideSection job={mockJob} analysisResult={{ impactData: mkImpact() }} />);

    await waitFor(() => {
      const saved = JSON.parse(localStorage.getItem(IMPACT_KEY) || 'null');
      expect(saved?.id?.build_number).toBe(412);
      expect(saved?.id?.build_revision).toBe('1042');
      expect(saved?.impactData?.trigger?.scm_id).toBe('hdpdm01');
    });
  });

  it('하이드레이트: Context가 비어 있어도 저장분에서 결과를 복원한다', async () => {
    const { useJob } = await import('../App.jsx');
    const { setAnalysisResult } = useJob();
    seedStore({
      id: { job_id: '', scm_id: 'hdpdm01', build_number: 412, build_revision: '1042' },
      jobId: '', impactData: mkImpact(), guide: null, aiGuide: null,
    });

    render(<ImpactGuideSection job={mockJob} analysisResult={null} />);

    // 새로고침 후 재분석 없이 Context로 결과가 되살아난다
    await waitFor(() => expect(setAnalysisResult).toHaveBeenCalled());
  });

  it('하이드레이트: 본문이 quota로 빠졌으면 자동 재요청 대신 복원 버튼을 준다', async () => {
    seedStore({
      id: { job_id: 'impact_9', scm_id: 'hdpdm01', build_number: 412 },
      jobId: 'impact_9', guide: mkGuide('g_fn'), aiGuide: null,
    });

    // 저장분에 job_url이 없으므로 SCM 대조로 검증된다 → 현재 프로젝트의 SCM을 알려준다.
    render(<ImpactGuideSection job={mockJob} analysisResult={{ matchedScm: { id: 'hdpdm01' } }} />);

    const btn = await screen.findByRole('button', { name: /마지막 결과 복원/ });
    expect(btn).toHaveTextContent('빌드 #412');
    // 마운트만으로 결과 본문을 자동 조회하지는 않는다(의도치 않은 왕복 방지)
    expect(api).not.toHaveBeenCalledWith(expect.stringContaining('/result'));
  });

  it('안전: 다른 Jenkins Job의 저장분은 현재 프로젝트에 주입하지 않는다', async () => {
    // Detail은 selectedJob.url이 바뀌면 remount하고 캐시 로드는 impactData=null이라, 프로젝트를
    // 전환하면 hydrate가 항상 '결과 없음' 경로를 탄다. 대조 없이 주입하면 프로젝트 A의
    // 변경함수/ASIL/커버리지가 B 화면 전체(영향·추적성·SCM 탭)에 A의 라벨로 뜬다.
    const { useJob } = await import('../App.jsx');
    const { setAnalysisResult } = useJob();
    const otherProject = mkImpact({ scm: 'kjpds02' });
    otherProject.trigger.metadata.job_url = 'http://jenkins.example.com/job/OTHER-job/';
    seedStore({
      id: {
        job_id: 'impact_other', scm_id: 'kjpds02', build_number: 412,
        job_url: 'http://jenkins.example.com/job/OTHER-job/',
      },
      jobId: 'impact_other', impactData: otherProject,
      guide: mkGuide('other_fn'), aiGuide: null,
    });

    render(<ImpactGuideSection job={mockJob} analysisResult={null} />);

    await waitFor(() => expect(screen.getByText(/변경 영향도 분석 결과가 없습니다/)).toBeInTheDocument());
    expect(setAnalysisResult).not.toHaveBeenCalled();
    // 복원 버튼으로도 열어주지 않는다 — 타 프로젝트 결과는 이 화면의 선택지가 아니다
    expect(screen.queryByRole('button', { name: /마지막 결과 복원/ })).not.toBeInTheDocument();
  });

  it('안전: 다른 빌드의 상세 가이드는 현재 빌드에 얹히지도, 현재 빌드 신원으로 저장되지도 않는다', async () => {
    // 가이드 세탁(laundering) 방지: 빌드 410에서 만든 가이드(ASIL/커버리지 판정 포함)가
    // 빌드 412 데이터 위에 남으면, 영속 계층이 그것을 '412의 신원'으로 각인해 다음 하이드레이트의
    // 안전 게이트(sameImpactTarget)를 통과시킨다. 라벨은 412를 가리키므로 사용자는 알 수 없다.
    seedStore({
      id: {
        job_id: '', scm_id: 'hdpdm01', build_number: 410, build_revision: '1030',
        job_url: mockJob.url,
      },
      jobId: '', impactData: mkImpact({ build: 410, rev: '1030' }),
      guide: mkGuide('stale_fn_410'), aiGuide: null,
    });

    // 화면에는 빌드 412가 떠 있는 상태에서 마운트(저장분은 410) — 같은 프로젝트라 C1 게이트는 통과
    render(<ImpactGuideSection job={mockJob} analysisResult={{ impactData: mkImpact({ build: 412 }) }} />);

    await waitFor(() => expect(screen.getByTestId('impact-target-label')).toHaveTextContent('빌드 #412'));
    // 410의 가이드가 렌더되지 않는다(렌더됐다면 함수별 상세 탭이 생긴다)
    expect(screen.queryByText(/stale_fn_410/)).not.toBeInTheDocument();
    expect(screen.queryByText(/함수별 상세/)).not.toBeInTheDocument();
    // 그리고 412 신원으로 410 가이드가 각인되지 않는다
    await waitFor(() => {
      const saved = JSON.parse(localStorage.getItem(IMPACT_KEY) || 'null');
      expect(saved?.id?.build_number).toBe(412);
      expect(saved?.guide).toBeFalsy();
    });
  });

  it('이미 분석된 빌드를 고르면 재실행하지 않고 저장된 결과를 연다', async () => {
    const user = userEvent.setup();
    api.mockImplementation(async (url) => {
      if (String(url).includes('/impact-jobs/')) {
        return {
          items: [historyItem({
            metadata: { build_number: 412, build_revision: '1042', job_url: mockJob.url },
          })],
        };
      }
      if (String(url).includes('/result')) return { result: mkImpact() };
      return {};
    });
    post.mockResolvedValue({ builds: [{ number: 412, result: 'SUCCESS' }] });

    // 아직 결과는 없지만 대시보드가 SCM은 고른 상태 — 여기서 빌드를 골라 여는 흐름
    render(<ImpactGuideSection job={mockJob} analysisResult={{ matchedScm: { id: 'hdpdm01', base_ref: '527' } }} />);

    const buildSelect = screen.getByLabelText('빌드');
    buildSelect.focus();                                   // onFocus lazy load
    await waitFor(() => expect(within(buildSelect).getAllByRole('option').length).toBeGreaterThan(1));
    await user.selectOptions(buildSelect, '412');
    await user.click(screen.getByRole('button', { name: '분석' }));

    await waitFor(() => expect(api).toHaveBeenCalledWith(
      expect.stringContaining('/api/scm/impact-job/impact_1/result'),
    ));
    // 재실행(trigger-async)은 일어나지 않아야 한다 — 이력 재사용이 이 기능의 핵심
    expect(post).not.toHaveBeenCalledWith('/api/jenkins/impact/trigger-async', expect.anything());
  });

  it('안전: job_url이 없는 결과는 SCM 증거 없이 트리거·이력 조회를 허용하지 않는다', async () => {
    // /api/local/impact/trigger 결과는 metadata에 job_url이 없다. job_url 대조만 하면 이 경우
    // 검사가 통째로 단락돼(vacuous true) scm_id=A × job_url=B 조합이 백엔드로 나가고,
    // update_baseline=True 라 A의 MC/DC baseline이 B의 빌드로 덮어써진다.
    const localImpact = mkImpact({ scm: 'scmA' });
    delete localImpact.trigger.metadata.job_url;   // 로컬 트리거 산출물

    render(<ImpactGuideSection job={mockJob} analysisResult={{ impactData: localImpact }} />);

    // 현재 Job이 scmA의 Job이라는 증거가 없다 → 잠금 배너 + 이력 조회 자체를 하지 않는다
    expect(screen.getByText(/이력 조회·실행을 잠갔습니다/)).toBeInTheDocument();
    await waitFor(() => expect(api).not.toHaveBeenCalledWith(expect.stringContaining('/impact-jobs/')));
  });

  // ⚠ 아래 두 건이 덮는 것은 **matchedScm이 없을 때의 scmList 갈래뿐**이다.
  // 프로덕션의 matchedScm writer(Dashboard·projectLoader)는 느슨한 pickScmForJob 결과를 그대로
  // 싣기 때문에, matchedScm이 있는 경로에서는 strictScmIdForJob이 아예 발화하지 않는다.
  // 즉 "SCM 1개 환경에서 항상 증거를 요구한다"는 시스템 속성은 아직 성립하지 않는다 —
  // 구조적 해법은 생산자가 매칭 근거(수동/토큰일치/유일후보)를 함께 기록하는 것이며 후속 과제다.
  it('matchedScm이 없을 때: SCM이 하나뿐이어도 Job URL과 무관하면 증거로 인정하지 않는다', async () => {
    // pickScmForJob은 후보가 하나면 job URL을 읽지 않고 승인한다(체크아웃 자동해결용 설계).
    // 그걸 provenance 증거로 그대로 쓰면 'SCM 1개 × Jenkins Job N개' 환경에서 무관한 Job의
    // changeSet으로 그 SCM을 분석하게 되고, update_baseline=True라 MC/DC baseline이 덮어써진다.
    const localImpact = mkImpact({ scm: 'totally-unrelated' });
    delete localImpact.trigger.metadata.job_url;

    render(<ImpactGuideSection job={mockJob} analysisResult={{
      impactData: localImpact,
      scmList: [{ id: 'totally-unrelated', name: 'totally-unrelated' }],  // 단일 등록
    }} />);

    expect(screen.getByText(/이력 조회·실행을 잠갔습니다/)).toBeInTheDocument();
    await waitFor(() => expect(api).not.toHaveBeenCalledWith(expect.stringContaining('/impact-jobs/')));
  });

  it('matchedScm이 없을 때: SCM이 하나이고 Job URL에 이름이 있으면 증거로 인정한다(과차단 방지)', async () => {
    // mockJob.url = .../job/test-job/ 이므로 id 'test-job'이 토큰 일치한다.
    const localImpact = mkImpact({ scm: 'test-job' });
    delete localImpact.trigger.metadata.job_url;

    render(<ImpactGuideSection job={mockJob} analysisResult={{
      impactData: localImpact, scmList: [{ id: 'test-job', name: 'test-job' }],
    }} />);

    expect(screen.queryByText(/이력 조회·실행을 잠갔습니다/)).not.toBeInTheDocument();
    await waitFor(() => expect(api).toHaveBeenCalledWith(
      expect.stringContaining('/api/scm/impact-jobs/test-job?summary=1'),
    ));
  });

  it('job_url이 없어도 SCM 증거가 있으면 정상 동작한다(과차단 방지)', async () => {
    const localImpact = mkImpact({ scm: 'hdpdm01' });
    delete localImpact.trigger.metadata.job_url;

    render(<ImpactGuideSection job={mockJob} analysisResult={{
      impactData: localImpact,
      matchedScm: { id: 'hdpdm01' },
      // 생산자가 기록한 매칭 근거. 'manual'(사용자가 직접 지정)은 가장 강한 증거다.
      // 이 필드가 없으면 아래 테스트대로 fail-closed 된다 — matchedScm 자체는 증거가 아니다.
      matchedScmSource: 'manual',
    }} />);

    expect(screen.queryByText(/이력 조회·실행을 잠갔습니다/)).not.toBeInTheDocument();
    await waitFor(() => expect(api).toHaveBeenCalledWith(
      expect.stringContaining('/api/scm/impact-jobs/hdpdm01?summary=1'),
    ));
  });

  it('안전: matchedScm이 있어도 매칭 근거가 없으면 SCM 증거로 인정하지 않는다', async () => {
    // W-A. pickScmForJob은 후보가 하나뿐이면 job URL을 읽지도 않고 승인한다('sole').
    // 그 결과를 그대로 실은 matchedScm을 증거로 인정하면 'SCM 1개 × Jenkins Job N개'에서
    // 무관한 Job의 changeSet으로 그 SCM을 분석하게 되고, update_baseline=True 경로가
    // 그 SCM의 MC/DC baseline과 감사기록을 덮어쓴다.
    const localImpact = mkImpact({ scm: 'hdpdm01' });
    delete localImpact.trigger.metadata.job_url;

    render(<ImpactGuideSection job={mockJob} analysisResult={{
      impactData: localImpact,
      matchedScm: { id: 'hdpdm01' },   // 근거(matchedScmSource) 없음 → 증거 아님
    }} />);

    expect(screen.getByText(/이력 조회·실행을 잠갔습니다/)).toBeInTheDocument();
    // 잠긴 상태에서는 이력 조회조차 나가지 않는다.
    expect(api).not.toHaveBeenCalledWith(
      expect.stringContaining('/api/scm/impact-jobs/'),
    );
  });

  it('안전: 근거가 \'sole\'(후보 유일)이면 증거로 인정하지 않는다', async () => {
    // 'manual'/'exact'/'substring'만 강한 근거다. 'sole'은 job URL과 접점이 없다.
    const localImpact = mkImpact({ scm: 'hdpdm01' });
    delete localImpact.trigger.metadata.job_url;

    render(<ImpactGuideSection job={mockJob} analysisResult={{
      impactData: localImpact,
      matchedScm: { id: 'hdpdm01' },
      matchedScmSource: 'sole',
    }} />);

    expect(screen.getByText(/이력 조회·실행을 잠갔습니다/)).toBeInTheDocument();
  });

  it('안전: 어느 Job의 빌드인지 증명 못 하는 이력은 재사용하지 않고 새로 분석한다', async () => {
    // 로컬 트리거 잡은 metadata에 job_url이 없다. 같은 SCM을 두 Jenkins Job이 공유하면
    // 빌드번호만으로는 '이 빌드'임을 증명할 수 없으므로, 증거 부재를 일치로 취급하면 안 된다.
    const user = userEvent.setup();
    api.mockImplementation(async (url) => {
      if (String(url).includes('/impact-jobs/')) {
        return { items: [historyItem({ metadata: { build_number: 412 } })] };  // job_url 없음
      }
      return {};
    });
    post.mockImplementation(async (url) => {
      if (String(url).includes('/builds')) return { builds: [{ number: 412, result: 'SUCCESS' }] };
      if (String(url).includes('trigger-async')) return { job_id: 'impact_fresh' };
      return {};
    });

    render(<ImpactGuideSection job={mockJob} analysisResult={{ matchedScm: { id: 'hdpdm01', base_ref: '527' } }} />);

    const buildSelect = screen.getByLabelText('빌드');
    buildSelect.focus();
    await waitFor(() => expect(within(buildSelect).getAllByRole('option').length).toBeGreaterThan(1));
    await user.selectOptions(buildSelect, '412');
    await user.click(screen.getByRole('button', { name: '분석' }));

    // 저장된 결과를 여는 대신 새로 분석한다
    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/jenkins/impact/trigger-async', expect.objectContaining({ build_number: 412 }),
    ));
    expect(api).not.toHaveBeenCalledWith(expect.stringContaining('/impact-job/impact_1/result'));
  });

  it("'다시 분석'은 이력이 있어도 강제로 재실행한다", async () => {
    const user = userEvent.setup();
    api.mockImplementation(async (url) => {
      if (String(url).includes('/impact-jobs/')) return { items: [historyItem({ metadata: { build_number: 412 } })] };
      return {};
    });
    post.mockImplementation(async (url) => {
      if (String(url).includes('/builds')) return { builds: [{ number: 412, result: 'SUCCESS' }] };
      if (String(url).includes('trigger-async')) return { job_id: 'impact_new' };
      return {};
    });

    render(<ImpactGuideSection job={mockJob} analysisResult={{ matchedScm: { id: 'hdpdm01', base_ref: '527' } }} />);

    const buildSelect = screen.getByLabelText('빌드');
    buildSelect.focus();
    await waitFor(() => expect(within(buildSelect).getAllByRole('option').length).toBeGreaterThan(1));
    await user.selectOptions(buildSelect, '412');
    await user.click(screen.getByRole('button', { name: '다시 분석' }));

    await waitFor(() => expect(post).toHaveBeenCalledWith(
      '/api/jenkins/impact/trigger-async',
      expect.objectContaining({ scm_id: 'hdpdm01', build_number: 412, job_url: mockJob.url }),
    ));
  });

  it('빌드 목록 조회 실패를 조용히 삼키지 않고 표면화한다', async () => {
    post.mockRejectedValue(new Error('Jenkins 연결 실패'));

    render(<ImpactGuideSection job={mockJob} analysisResult={null} />);
    screen.getByLabelText('빌드').focus();

    expect(await screen.findByText(/빌드 목록 조회 실패: Jenkins 연결 실패/)).toBeInTheDocument();
    // 이력 경로는 계속 살아 있어야 한다
    expect(screen.getByLabelText('분석 이력')).toBeInTheDocument();
  });

  // STS-IMPACT-063: 문서별 상세(Surface 2)에도 함수 모달과 동일한 '현재 원문 → 수정안' 통합 블록이
  //  뜬다 — 과거엔 편집 액션+실 내용만 있고 작성 제안(renderAuthoringProposal)이 없던 표면 비대칭 해소.
  it('문서별 상세 통합: 현재 실 내용 + 작성 제안이 한 "현재 원문 → 수정안" 블록으로 표시된다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_foo: 'SIGNATURE' },
        change_details: { s_foo: { before: 'void s_foo(void)', after: 'void s_foo(uint8 x)' } },
        impact: { direct: ['s_foo'] },
        actions: { uds: { mode: 'AUTO', status: 'review_required', function_count: 1, functions: ['s_foo'] } },
        function_meta: { s_foo: { asil: 'A', evidence: 'line' } },
        doc_content: { uds: { s_foo: { description: 'foo', prototype: 'void s_foo(void)', globals: [] } } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: /문서별 상세 \(1\)/ }));
    // 통합 프레임 헤더 + 현재 실 내용(renderDocContent) + 작성 제안(renderAuthoringProposal) 셋 다 문서별 상세에 존재
    await waitFor(() => expect(screen.getByText('현재 원문 → 수정안')).toBeInTheDocument());
    expect(screen.getByText('📄 실제 UDS 내용')).toBeInTheDocument();          // 현재
    expect(screen.getByText(/원문 → 변경안 \(결정론\)/)).toBeInTheDocument();   // 수정안(과거 문서별엔 없었음)
    expect(screen.getByText(/＋ void s_foo\(uint8 x\)/)).toBeInTheDocument();
  });

  // STS-IMPACT-064: 문서별 상세에서도 간접(비변경) 함수는 현재 내용만 보이고 작성 제안·"현재 원문 → 수정안"
  //  헤더가 뜨지 않는다 — 억제 규칙(renderAuthoringProposal 가드)이 양 표면에서 동일(모순 방지).
  it('문서별 상세 억제: 간접 함수 행은 현재 내용만, 작성 제안/통합 헤더 없음', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_changed: 'SIGNATURE' },
        change_details: { s_changed: { before: 'void s_changed(void)', after: 'void s_changed(U16 n)' } },
        impact: { direct: ['s_changed'], indirect_1hop: ['g_indirect'], indirect_2hop: [] },
        impact_paths: { g_indirect: { hop: 1, via: 's_changed', seed: 's_changed' } },
        // uds 문서엔 간접 함수만 배치(억제 검증 격리)
        actions: { uds: { mode: 'AUTO', status: 'review_required', function_count: 1, functions: ['g_indirect'] } },
        function_meta: { s_changed: { asil: 'A' }, g_indirect: { asil: 'B', evidence: 'line' } },
        doc_content: { uds: { g_indirect: { description: 'indirect helper', prototype: 'void g_indirect(U16 n)' } } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: /문서별 상세 \(1\)/ }));
    // 현재 실 내용은 보이되(간접도 문서 맥락 확인 필요), 작성 제안·통합 헤더는 억제
    await waitFor(() => expect(screen.getByText('📄 실제 UDS 내용')).toBeInTheDocument());
    expect(screen.queryByText('현재 원문 → 수정안')).toBeNull();
    expect(screen.queryByText(/원문 → 변경안/)).toBeNull();
    expect(screen.queryByText(/UDS 작성 제안/)).toBeNull();
  });

  // STS-IMPACT-065: SUTS 카드가 실 TC 시트·행 위치(백엔드 loc)를 표시하고, 경계값 제안이 그 TC(행 N)
  //  기준 재계산임을 명시한다 — "이 TC(행 N)를 이렇게 수정" 구체화(백엔드가 파싱하나 과거 버리던 위치).
  it('SUTS 위치: 모달 SUTS 카드에 실 TC 시트·행(loc)과 "TC ... 기준 재계산"이 표시된다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_foo: 'SIGNATURE' },
        change_details: { s_foo: { before: 'void s_foo(void)', after: 'void s_foo(U16 idx)' } },
        impact: { direct: ['s_foo'] },
        function_meta: { s_foo: { asil: 'A', evidence: 'line' } },
        doc_content: { suts: { s_foo: [{ tc_id: 'SwUTC_SwUFn_0001', inputs: { x: '1' }, expected: { ret: '42' }, loc: { sheet: '2.SW Unit Test Spec', tc_row: 42 } }] } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    const dialog = await screen.findByRole('dialog');
    // renderDocContent: 실 위치 라인(백엔드 loc.sheet 그대로 — 하드코딩 아님)
    await waitFor(() => expect(within(dialog).getByText('2.SW Unit Test Spec 시트 · 행 42')).toBeInTheDocument());
    // renderAuthoringProposal: 그 TC(행 N) 기준 재계산 앵커
    expect(within(dialog).getByText(/TC SwUTC_SwUFn_0001 · 2\.SW Unit Test Spec 시트 · 행 42 기준 재계산/)).toBeInTheDocument();
    // 현재 기대값(Exp)도 통합 블록에 함께 표시
    expect(within(dialog).getByText(/ret=42/)).toBeInTheDocument();
  });

  // STS-IMPACT-066: 문서별 상세(Surface 2)의 SUTS 행에도 실 TC 시트·행(loc)이 표시된다(양 표면 동등).
  it('SUTS 위치: 문서별 상세 SUTS 행에도 실 TC 시트·행(loc)이 표시된다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_foo: 'SIGNATURE' },
        change_details: { s_foo: { before: 'void s_foo(void)', after: 'void s_foo(U16 idx)' } },
        impact: { direct: ['s_foo'] },
        actions: { suts: { mode: 'AUTO', status: 'review_required', function_count: 1, functions: ['s_foo'] } },
        function_meta: { s_foo: { asil: 'A', evidence: 'line' } },
        doc_content: { suts: { s_foo: [{ tc_id: 'SwUTC_SwUFn_0001', expected: { ret: '42' }, loc: { sheet: '2.SW Unit Test Spec', tc_row: 42 } }] } },
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: /문서별 상세 \(1\)/ }));
    await waitFor(() => expect(screen.getByText('2.SW Unit Test Spec 시트 · 행 42')).toBeInTheDocument());
  });

  // STS-IMPACT-067: (reviewer Critical fix) 현재 원문이 없는(미파싱) 함수는 '현재 원문 → 수정안' 헤더로
  //  없는 원문을 암시하지 않는다 — 작성 골격(제안)은 그대로 뜨되 before→after 프레임은 걸지 않는다.
  it('정직 프레임: 미파싱 문서는 "현재 원문 → 수정안" 헤더 없이 작성 골격만 표시한다', async () => {
    const { post } = await import('../api.js');
    post.mockResolvedValue({ ok: false });
    const user = userEvent.setup();
    const analysisResult = {
      impactData: {
        trigger: { changed_files: ['Ap.c'] },
        changed_function_types: { s_bar: 'SIGNATURE' },
        change_details: { s_bar: { before: 'void s_bar(void)', after: 'void s_bar(U16 idx)' } },
        impact: { direct: ['s_bar'] },
        function_meta: { s_bar: { asil: 'B', evidence: 'line' } },
        // doc_content 없음 → UDS 미파싱(현재 원문 없음) → 작성 골격만
      },
    };
    render(<ImpactGuideSection analysisResult={analysisResult} />);
    await user.click(screen.getByText(/상세 가이드 생성/));
    await user.click(await screen.findByRole('button', { name: '상세' }));
    const dialog = await screen.findByRole('dialog');
    // 작성 골격(제안)은 표시된다
    await waitFor(() => expect(within(dialog).getByText(/UDS 작성 제안/)).toBeInTheDocument());
    // 없는 '현재 원문'을 암시하는 프레임 헤더는 표시하지 않는다(reviewer Critical)
    expect(within(dialog).queryByText('현재 원문 → 수정안')).toBeNull();
  });
});
