/**
 * 정적분석 라운드 — 프론트 확정 결함 4건의 회귀 가드 (2026-08-05).
 *
 * 1. DocGenSection SCM 폴백이 `/api/scm/list` 를 **무한 재요청**했다.
 *    같은 본문이 이 파일 안에 두 벌 있었고 한쪽만 deps `[scm]` 이었다. 응답의
 *    items[0] 은 매번 새 객체라 setScm 이 항상 리렌더를 유발하고, source_root 가
 *    빈 registry entry 가 첫 항목이면 가드가 계속 참이라 루프가 끝나지 않는다.
 *    DocGenHubSection 은 keep-alive 라 다른 서브탭으로 옮겨도 계속 돈다.
 *
 * 2. 문서 경로 override 의 localStorage 실패를 빈 catch 로 삼킨 **직후 성공 토스트**.
 *    F5 하면 override 가 사라져 사용자가 지정한 것과 다른 문서로 생성된다.
 *
 * 3. ScmSection 이 `!selectedId` 가드 때문에 재분석 후에도 옛 SCM 을 계속 표시.
 *
 * 4. ReportGenSection QAC 목록 조회 실패를 완전 침묵 → '산출물 0건' 으로 오독.
 *
 * ⚠ 여기서는 **함수 단위**로 검증한다. 세 컴포넌트를 통째로 렌더하려면 Detail/App
 *   컨텍스트 전체가 필요해 테스트가 취약해지고, 잡으려는 성질(요청 횟수·토스트
 *   조건·재도출 조건)은 로직에 있지 마크업에 있지 않다.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

const apiMock = vi.fn();

vi.mock('../api.js', () => ({
  api: (...a) => apiMock(...a),
  post: vi.fn(),
  defaultCacheRoot: vi.fn(() => ''),
  getUsername: () => 'testuser',
}));
vi.mock('../App.jsx', () => ({
  useJenkinsCfg: vi.fn(() => ({ cfg: {}, update: vi.fn() })),
  useToast: vi.fn(() => vi.fn()),
}));

const { persistDocPaths, useScmFallback } = await import('../docGenHelpers.js');

beforeEach(() => {
  apiMock.mockReset();
  localStorage.clear();
});

// ---------------------------------------------------------------------------
// 1. SCM 폴백 무한 루프
// ---------------------------------------------------------------------------
describe('useScmFallback', () => {
  it('source_root 가 빈 entry 를 받아도 /api/scm/list 를 한 번만 부른다', async () => {
    // 이것이 정확한 결함 조건이다: 응답 첫 항목의 source_root 가 비어 있으면
    // 가드(`!scm?.source_root`)가 setScm 이후에도 계속 참이다.
    apiMock.mockImplementation(async () => ({ items: [{ id: 'a', source_root: '' }] }));

    const { result } = renderHook(() => useScmFallback({}));
    await waitFor(() => expect(result.current[0]).not.toBeNull());
    // 루프가 있으면 이 시점 이후로도 호출이 계속 늘어난다 — 잠깐 기다렸다 다시 센다.
    const first = apiMock.mock.calls.length;
    await act(() => new Promise(r => setTimeout(r, 60)));

    expect(first).toBe(1);
    expect(apiMock.mock.calls.length).toBe(1);
  });

  it('이미 source_root 가 있으면 아예 조회하지 않는다', async () => {
    renderHook(() => useScmFallback({ matchedScm: { id: 'x', source_root: 'C:/src' } }));
    await act(() => new Promise(r => setTimeout(r, 40)));
    expect(apiMock).not.toHaveBeenCalled();
  });

  it('조회가 실패해도 재시도로 폭주하지 않는다', async () => {
    apiMock.mockRejectedValue(new Error('boom'));
    renderHook(() => useScmFallback({}));
    await act(() => new Promise(r => setTimeout(r, 60)));
    expect(apiMock.mock.calls.length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// 2. 저장 실패를 성공으로 위장하지 않는다
// ---------------------------------------------------------------------------
describe('persistDocPaths', () => {
  it('정상 저장 시 true 와 함께 값이 남는다', () => {
    const toast = vi.fn();
    expect(persistDocPaths({ srs: 'C:/a.docx' }, toast)).toBe(true);
    expect(JSON.parse(localStorage.getItem('devops_v2_doc_paths')).srs).toBe('C:/a.docx');
    expect(toast).not.toHaveBeenCalled();
  });

  it('쿼터 초과 시 false 를 주고 경고한다 — 성공 토스트가 뜨면 안 된다', () => {
    const toast = vi.fn();
    // ⚠ Storage.prototype 에 걸면 안 된다 — 테스트 setup 이 globalThis.localStorage 를
    //   Storage 인스턴스가 아닌 평범한 객체로 갈아끼우면 prototype spy 가 무시되고
    //   테스트가 조용히 통과한다(실측: 이 방식으로 처음엔 true 가 나왔다).
    const spy = vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
      const e = new Error('quota'); e.name = 'QuotaExceededError'; throw e;
    });
    try {
      expect(persistDocPaths({ srs: 'C:/a.docx' }, toast)).toBe(false);
    } finally {
      spy.mockRestore();
    }
    expect(toast).toHaveBeenCalledTimes(1);
    const [level, msg] = toast.mock.calls[0];
    expect(level).toBe('warning');
    expect(msg).toContain('QuotaExceededError');
    // 실패 사실이 사용자 언어로 드러나야 한다 — '세션에서만' / '되돌아' 중 하나.
    expect(msg).toMatch(/세션|되돌아|사라/);
  });
});
