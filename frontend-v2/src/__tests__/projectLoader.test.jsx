/**
 * projectLoader 단위 테스트
 *
 * - pickScmForJob: Dashboard에서 이관된 SCM 매칭(확신 없으면 null).
 * - loadProjectFromCache: 캐시된 report/summary를 Jenkins 재sync 없이 읽어
 *   analysisResult 형태로 변환. Dashboard 오프라인 보기 + Detail 브레드크럼 전환 공용.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockApi = vi.fn();
const mockPost = vi.fn();
vi.mock('../api.js', () => ({
  api: (...a) => mockApi(...a),
  post: (...a) => mockPost(...a),
  defaultCacheRoot: () => 'U:/cache',
}));

const { loadProjectFromCache, pickScmForJob } = await import('../projectLoader.js');

describe('pickScmForJob', () => {
  it('단일 엔트리면 그대로 반환', () => {
    const list = [{ id: 'only' }];
    expect(pickScmForJob(list, 'http://x/job/anything')).toBe(list[0]);
  });
  it('확신 없으면 null (백엔드 repo_url 자동매칭에 위임)', () => {
    expect(pickScmForJob([{ id: 'aaa' }, { id: 'bbb' }], 'http://x/job/zzz')).toBeNull();
  });
  it('토큰이 jobUrl에 포함되면 해당 엔트리', () => {
    const list = [{ id: 'proj_alpha' }, { id: 'proj_beta' }];
    expect(pickScmForJob(list, 'http://x/job/proj_beta/')).toBe(list[1]);
  });
});

describe('loadProjectFromCache', () => {
  beforeEach(() => { mockApi.mockReset(); mockPost.mockReset(); });

  it('report/summary를 읽어 analysisResult(_offline) 형태로 반환한다', async () => {
    mockApi.mockResolvedValue([{ id: 'scm1', name: 'proj' }]);   // /api/scm/list
    mockPost.mockResolvedValue({
      kpis: { build: { build_number: 42, result: 'SUCCESS' }, coverage: { line_rate: 0.83 } },
      artifacts: { uds: [{ path: 'D:/out/uds.docx', title: 'UDS' }] },
    });

    const res = await loadProjectFromCache('http://x/job/proj/', { buildSelector: 'lastSuccessfulBuild' });

    expect(res._offline).toBe(true);
    expect(res.reportData.build_number).toBe(42);
    expect(res.reportData.result).toBe('SUCCESS');
    expect(res.reportData.coverage).toBe(83);              // 0.83 → 83%
    expect(res.artifacts).toEqual([
      { type: 'uds', name: 'uds.docx', path: 'D:/out/uds.docx', title: 'UDS' },
    ]);
    expect(res.matchedScm).toEqual({ id: 'scm1', name: 'proj' });  // 단일 → 그대로
    expect(mockPost).toHaveBeenCalledWith(
      '/api/jenkins/report/summary',
      expect.objectContaining({ job_url: 'http://x/job/proj/' }),
    );
  });

  it('scm/list 실패해도 report는 로드하고 matchedScm=null, scmList=[]', async () => {
    mockApi.mockRejectedValue(new Error('no scm'));
    mockPost.mockResolvedValue({ build_number: 7, result: 'FAILURE' });

    const res = await loadProjectFromCache('http://x/job/p/', {});

    expect(res.matchedScm).toBeNull();
    expect(res.scmList).toEqual([]);
    expect(res.reportData.build_number).toBe(7);
  });

  it('report/summary가 throw하면 그대로 전파(호출자에서 toast)', async () => {
    mockApi.mockResolvedValue([]);
    mockPost.mockRejectedValue(new Error('no cache'));
    await expect(loadProjectFromCache('http://x/job/p/', {})).rejects.toThrow('no cache');
  });
});
