/**
 * SwUT / SwIT / 통합결과 **탭**이 payload 에 `scm_id` 를 싣는지 (2026-08-25).
 *
 * ## 왜 필요한가 (라이브 실측)
 *
 * 생성 현황 보드는 `analysisResult.matchedScm.id` 를 `scm_id` 로 실어 보낸다. 그런데 같은
 * 문서를 만드는 **탭** 3곳은 props 를 아예 안 받아(`function SwUTBuildSection()`) 그 값을
 * 실을 수 없었다. 결과는 조용하다 — 빌드는 200 으로 성공하고 파일도 내려오는데,
 * quality run 이 프로젝트에 안 붙어 **보드에서는 계속 '미생성'** 으로 남는다. 실패가 아니라
 * "만든 적 없음" 으로 위장하므로 화면만 봐선 원인을 못 찾는다.
 *
 * ## 이 파일이 고정하는 것
 *
 * 구조가 아니라 **나가는 payload** 를 본다. `analysisResult` 를 넘겼을 때 body 에 그 id 가
 * 들어가고, 안 넘겼을 때 키가 사라지지 않고 빈 문자열로 남는지(= 백엔드 schema 의
 * `extra='forbid'` 와 `str` 기본값 계약)까지 확인한다.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const toastSpy = vi.fn();
const postSpy = vi.fn(async () => ({ rows: [], warnings: [], summary: { rows_total: 0 } }));

vi.mock('../App.jsx', () => ({ useToast: () => toastSpy }));
vi.mock('../api.js', () => ({
  getUsername: () => 'tester',
  authHeaders: () => ({ 'X-User': 'tester' }),
  post: (...a) => postSpy(...a),
}));
vi.mock('../contexts/AdminContext.jsx', () => ({
  useAdminMode: () => ({ isAdmin: true, username: 'tester', authenticated: true, loading: false }),
  AdminProvider: ({ children }) => children,
}));

const { default: SwUTBuildSection } = await import('../components/sections/SwUTBuildSection.jsx');
const { default: SwITBuildSection } = await import('../components/sections/SwITBuildSection.jsx');
const { default: SwReportSummarySection } =
  await import('../components/sections/SwReportSummarySection.jsx');

const SCM = { matchedScm: { id: 'kjpds02_pv' } };

function mockBlobFetch() {
  return vi.spyOn(global, 'fetch').mockResolvedValue({
    ok: true,
    headers: new Headers({ 'Content-Disposition': 'attachment; filename="x.xlsx"' }),
    blob: async () => new Blob([new Uint8Array([0x50, 0x4b, 0x03, 0x04])]),
  });
}

describe('빌더 탭이 보드와 같은 SCM 귀속을 싣는다', () => {
  beforeEach(() => {
    toastSpy.mockReset();
    postSpy.mockClear();
    localStorage.clear();
    localStorage.setItem('devops_admin_mode', 'true');
    global.URL.createObjectURL = vi.fn(() => 'blob://mock');
    global.URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => { vi.restoreAllMocks(); });

  // SwUT / SwIT 은 같은 화면 계약(Release SW Version + Log Folder → Coverage Report 빌드)이라
  // 표로 돈다. 한쪽만 고쳐지는 '판정 복제' 를 막는다.
  for (const [name, Comp] of [['SwUT', SwUTBuildSection], ['SwIT', SwITBuildSection]]) {
    it(`${name} 탭 빌드가 body 에 scm_id 를 싣는다`, async () => {
      const fetchSpy = mockBlobFetch();
      render(<Comp analysisResult={SCM} />);
      fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '2.02' } });
      fireEvent.change(screen.getByLabelText(/^Log Folder/), { target: { value: 'C:/fake/log' } });
      fireEvent.click(screen.getByText(/Coverage Report 빌드/));

      await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
      const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
      expect(body.scm_id).toBe('kjpds02_pv');
    });

    // ⚠ 이게 진짜 흐름이다. 탭은 keep-alive 로 **먼저** 마운트되고 `analysisResult` 는
    //    분석이 끝난 뒤 도착한다. 빌드 함수가 `useCallback([form, toast])` 인 채 scmId 를
    //    참조하면 첫 렌더의 빈 값이 굳어 — 위의 '첫 렌더에 prop 을 주는' 시험은 통과하는데
    //    실사용에서만 조용히 틀린다. deps 에 scmId 가 있어야만 이 시험이 통과한다.
    it(`${name} 탭은 분석이 나중에 끝나도 그 시점의 scm_id 를 싣는다 (stale closure)`, async () => {
      const fetchSpy = mockBlobFetch();
      const { rerender } = render(<Comp />);              // 분석 전 마운트
      fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '2.02' } });
      fireEvent.change(screen.getByLabelText(/^Log Folder/), { target: { value: 'C:/fake/log' } });
      rerender(<Comp analysisResult={SCM} />);            // 분석 완료 → prop 도착
      fireEvent.click(screen.getByText(/Coverage Report 빌드/));

      await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
      expect(JSON.parse(fetchSpy.mock.calls[0][1].body).scm_id).toBe('kjpds02_pv');
    });

    it(`${name} 탭은 SCM 미매칭이어도 scm_id 키를 빈 문자열로 유지한다`, async () => {
      const fetchSpy = mockBlobFetch();
      render(<Comp />);           // analysisResult 없음 = SCM 미매칭
      fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '2.02' } });
      fireEvent.change(screen.getByLabelText(/^Log Folder/), { target: { value: 'C:/fake/log' } });
      fireEvent.click(screen.getByText(/Coverage Report 빌드/));

      await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
      const body = JSON.parse(fetchSpy.mock.calls[0][1].body);
      // undefined 면 JSON.stringify 가 키를 통째로 지운다 — 그건 '안 보냈다' 와 구분이 안 된다.
      expect(body).toHaveProperty('scm_id');
      expect(body.scm_id).toBe('');
    });
  }

  it('통합 결과 탭 미리보기가 payload 에 scm_id 를 싣는다', async () => {
    render(<SwReportSummarySection analysisResult={SCM} />);
    fireEvent.change(screen.getByLabelText(/Release SW Version/), { target: { value: '2.02' } });
    fireEvent.click(screen.getByText(/미리보기 \(JSON\)/));

    await waitFor(() => expect(postSpy).toHaveBeenCalled());
    const [url, payload] = postSpy.mock.calls[0];
    expect(url).toContain('/api/swreport/summary/preview');
    expect(payload.scm_id).toBe('kjpds02_pv');
  });
});
