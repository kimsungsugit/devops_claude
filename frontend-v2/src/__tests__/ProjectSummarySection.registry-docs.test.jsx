/**
 * 프로젝트 요약 탭의 **자동 추적성 매트릭스**가 레지스트리 최신 문서로 만들어지는가.
 *
 * 사용자 보고(2026-08-06) "SUTS만 안 바뀐다" 의 두 번째 경로. `SrsSdsSection` 은
 * `/api/scm/list` 재조회를 갖고 있었지만 이 섹션은 **아예 없어서**
 * `analysisResult.matchedScm.linked_docs`(분석 시점 스냅샷)로 매트릭스를 만들었다.
 * 사용자가 레지스트리에서 SUTS 경로를 바꿔도 이 탭은 영원히 옛 경로를 썼다.
 *
 * 여기서는 `buildTraceMatrix` 가 **실제로 받는** linkedDocs 를 붙잡아 확인한다 —
 * 화면 텍스트가 아니라 계산 입력을 보는 것이 이 결함의 정확한 표면이다.
 */
import { render, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockApi = vi.fn();
const mockPost = vi.fn();
const mockBuild = vi.fn();

vi.mock('../api.js', () => ({
  api: (...a) => mockApi(...a),
  post: (...a) => mockPost(...a),
  defaultCacheRoot: vi.fn(() => '.cache'),
}));
vi.mock('../App.jsx', () => ({
  useToast: () => vi.fn(),
  useJenkinsCfg: () => ({ cfg: { baseUrl: 'http://jenkins' }, update: vi.fn() }),
}));
vi.mock('../traceMatrix.js', () => ({ buildTraceMatrix: (...a) => mockBuild(...a) }));

const { default: ProjectSummarySection } = await import('../components/sections/ProjectSummarySection.jsx');

const JOB = { name: 'kjpds02-pv', url: 'http://jenkins/job/kjpds02-pv/' };
const OLD_SUTS = 'U:/proj/01.SwUTS/OLD_SwUTS_v1.03.xlsm';
const NEW_SUTS = 'U:/proj/01.SwUTS/PV_v2631/NEW_SwUTS_v1.02.xlsm';

const SNAPSHOT = { id: 'pv1', name: 'KJPDS02_PV', source_root: 'D:/src', linked_docs: { suts: OLD_SUTS } };

const RESULT = {
  cacheRoot: '.cache',
  jobUrl: JOB.url,
  scmList: [SNAPSHOT],
  matchedScm: SNAPSHOT,
  matchedScmSource: 'manual',
  reportData: { kpis: {} },
  impactData: null,
};

beforeEach(() => {
  mockApi.mockReset();
  mockPost.mockReset();
  mockBuild.mockReset();
  localStorage.clear();

  // 레지스트리는 **새** SUTS 를 준다.
  mockApi.mockImplementation(async (path) => {
    if (String(path).includes('/api/scm/list')) {
      return { items: [{ ...SNAPSHOT, linked_docs: { suts: NEW_SUTS } }] };
    }
    return {};
  });
  // 캐시된 요약이 없어야 자동 생성 분기로 간다.
  mockPost.mockImplementation(async () => ({ has_data: false }));
  mockBuild.mockResolvedValue({ ok: false, reason: 'test-stop' });
});

describe('ProjectSummarySection — 자동 매트릭스 입력 문서', () => {
  it('스냅샷이 아니라 레지스트리 최신 SUTS 로 매트릭스를 만든다', async () => {
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);

    await waitFor(() => expect(mockBuild).toHaveBeenCalled());

    // 마지막 호출이 최신 경로여야 한다(초기 스냅샷으로 한 번 불릴 수는 있다).
    const lastArg = mockBuild.mock.calls[mockBuild.mock.calls.length - 1][0];
    await waitFor(() => {
      const arg = mockBuild.mock.calls[mockBuild.mock.calls.length - 1][0];
      expect(arg.linkedDocs?.suts).toBe(NEW_SUTS);
    });
    expect(lastArg).toBeTruthy();
  });

  it('레지스트리 조회가 실패해도 스냅샷으로 생성은 계속된다', async () => {
    mockApi.mockImplementation(async (path) => {
      if (String(path).includes('/api/scm/list')) throw new Error('network');
      return {};
    });
    render(<ProjectSummarySection job={JOB} analysisResult={RESULT} />);
    await waitFor(() => expect(mockBuild).toHaveBeenCalled());
    const arg = mockBuild.mock.calls[mockBuild.mock.calls.length - 1][0];
    expect(arg.linkedDocs?.suts).toBe(OLD_SUTS);
  });
});
