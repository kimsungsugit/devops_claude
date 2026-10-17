/**
 * SrsSdsSection — 영향분석 결과 오귀속 차단(impactGuard) 배선 테스트
 *
 * 범위: 이 파일은 impactGuard 배선만 다룬다. 이 섹션(요구사항 커버리지)의 추적성 매트릭스
 * 기능 전반은 별도 테스트 대상이며 여기서 다루지 않는다.
 *
 * 왜 필요한가: Dashboard.runAnalysis는 여러 개가 겹쳐 돌 수 있고 서버측 취소 endpoint가 없어
 * 구 실행이 abort 후에도 완주한다. 그래서 Context(analysisResult.impactData)가 지금 보고
 * 있는 Job/SCM의 것이 아닐 수 있다. 이 섹션은 요구사항 커버리지를 다루므로, 대조 없이
 * 그리면 다른 프로젝트의 변경 파일·영향 문서가 이 프로젝트의 추적성 근거로 보인다
 * (ISO 26262 오보고).
 */
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockToast = vi.fn();

vi.mock('../App.jsx', () => ({
  useJenkinsCfg: () => ({
    cfg: { baseUrl: 'http://jenkins', username: 'u', token: 't', cacheRoot: '.cache' },
    update: vi.fn(),
  }),
  useToast: () => mockToast,
}));

vi.mock('../api.js', () => ({
  api: vi.fn(async () => ({})),
  post: vi.fn(async () => ({})),
  getUsername: vi.fn(() => 'tester'),
  authHeaders: vi.fn(() => ({})),
  buildUrl: vi.fn((p) => p),
  defaultCacheRoot: vi.fn(() => '.cache'),
}));

const { default: SrsSdsSection } = await import('../components/sections/SrsSdsSection.jsx');

const JOB = { name: 'test-job', url: 'http://jenkins/job/test-job/' };

const mkResult = (impactData, overrides = {}) => ({
  cacheRoot: '.cache',
  // 실제 생산자(Dashboard.updateResult / loadProjectFromCache)는 jobUrl 을 항상 싣는다.
  // 이 필드가 빠진 픽스처는 형제 필드 축을 통째로 vacuous 하게 만들어 테스트를 공허하게 한다.
  jobUrl: JOB.url,
  scmList: [{ id: 'scm-1', name: 'MyRepo', linked_docs: { srs: 'A_SRS.docx' } }],
  matchedScm: { id: 'scm-1', name: 'MyRepo', linked_docs: { srs: 'A_SRS.docx' } },
  matchedScmSource: 'manual',
  reportData: {},
  impactData,
  ...overrides,
});

/** 실제 결과 형태 — 변경 파일과 영향 문서가 함께 실린다. */
const mkImpact = ({ scm = 'scm-1', jobUrl = JOB.url } = {}) => ({
  trigger: { scm_id: scm, metadata: jobUrl ? { job_url: jobUrl } : {} },
  changed_files: ['src/module_a.c'],
  impacted_docs: [{ doc_type: 'uds', path: 'UDS.docx' }],
});

describe('SrsSdsSection — impactGuard 배선', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('같은 Job·같은 SCM의 결과는 영향 분석 결과 패널에 표시한다 (과차단 방지)', () => {
    render(<SrsSdsSection job={JOB} analysisResult={mkResult(mkImpact())} />);

    expect(screen.getByText('영향 분석 결과')).toBeInTheDocument();
    expect(screen.queryByText(/표시하지 않았습니다/)).not.toBeInTheDocument();
  });

  it('안전: 다른 Job의 결과면 영향 패널을 숨기고 사유를 밝힌다', () => {
    const other = mkImpact({ jobUrl: 'http://jenkins/job/other-job/' });
    render(<SrsSdsSection job={JOB} analysisResult={mkResult(other)} />);

    expect(screen.queryByText('영향 분석 결과')).not.toBeInTheDocument();
    expect(screen.getByText(/다른 Job의 빌드로 실행됐습니다/)).toBeInTheDocument();
  });

  it('안전: 다른 SCM의 결과면 영향 패널을 숨기고 사유를 밝힌다', () => {
    const other = mkImpact({ scm: 'other-scm' });
    render(<SrsSdsSection job={JOB} analysisResult={mkResult(other)} />);

    expect(screen.queryByText('영향 분석 결과')).not.toBeInTheDocument();
    expect(screen.getByText(/다른 SCM의 것입니다/)).toBeInTheDocument();
  });

  it('감춘 사유는 조용히 비우지 않고 반드시 문구로 알린다', () => {
    // 조용히 비우면 사용자는 '영향 없음'으로 오독한다 — 침묵이 곧 오보고다.
    render(<SrsSdsSection job={JOB} analysisResult={mkResult(mkImpact({ scm: 'other-scm' }))} />);

    expect(screen.getByText(/영향 분석 결과를 표시하지 않았습니다/)).toBeInTheDocument();
  });

  // ── 결과 뭉치 전체가 stale인 경우 (contextConflict) ────────────────────
  // 이 섹션에서 오귀속 피해가 가장 큰 건 영향 패널이 아니라 추적성 매트릭스다.
  // activeScm.linked_docs 가 매트릭스(SRS→SDS→UDS→STS→SUTS→SITS)의 입력이기 때문.

  it('안전: 결과 뭉치가 다른 Job의 것이면 impactData가 없어도 최상단에 경고한다', () => {
    // impactData가 null이면 impactConflict는 no_impact로 통과시킨다 — 그래서
    // 이 경로는 contextConflict가 없으면 아무 경고 없이 옛 프로젝트 문서로 그려진다.
    const stale = mkResult(null, { jobUrl: 'http://jenkins/job/project-a/' });
    render(<SrsSdsSection job={JOB} analysisResult={stale} />);

    expect(screen.getByText(/현재 Job의 것이 아닙니다/)).toBeInTheDocument();
  });

  it('안전: stale 상태에서는 옛 프로젝트의 문서 경로를 입력으로 쓰지 않는다', () => {
    const stale = mkResult(null, { jobUrl: 'http://jenkins/job/project-a/' });
    render(<SrsSdsSection job={JOB} analysisResult={stale} />);

    // A의 linked_docs.srs 가 입력 문서로 노출되면 안 된다
    expect(screen.queryByText(/A_SRS\.docx/)).not.toBeInTheDocument();
    expect(screen.getByText(/추적성 매트릭스와 입력 문서를/)).toBeInTheDocument();
  });

  it('안전: 다중 레지스트리에서 자동매칭 실패 시 scmList[0]을 추측하지 않는다', () => {
    const ambiguous = mkResult(null, {
      matchedScm: null,
      matchedScmSource: null,
      scmList: [
        { id: 'scm-1', name: 'RepoOne', linked_docs: { srs: 'A_SRS.docx' } },
        { id: 'scm-2', name: 'RepoTwo', linked_docs: { srs: 'B_SRS.docx' } },
      ],
    });
    render(<SrsSdsSection job={JOB} analysisResult={ambiguous} />);

    expect(screen.getByText(/SCM을 확정하지 못했습니다/)).toBeInTheDocument();
    expect(screen.queryByText(/A_SRS\.docx/)).not.toBeInTheDocument();
  });

  it('단일 레지스트리는 matchedScm이 없어도 그 하나를 쓴다 (과차단 방지)', () => {
    const single = mkResult(null, { matchedScm: null, matchedScmSource: null });
    render(<SrsSdsSection job={JOB} analysisResult={single} />);

    expect(screen.queryByText(/SCM을 확정하지 못했습니다/)).not.toBeInTheDocument();
    expect(screen.queryByText(/현재 Job의 것이 아닙니다/)).not.toBeInTheDocument();
  });
});
