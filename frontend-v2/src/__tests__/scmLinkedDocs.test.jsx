/**
 * `useRegistryLinkedDocs` — SCM 연결 문서는 **레지스트리 최신본**이 진실원이다.
 *
 * 사용자 보고(2026-08-06) "SUTS만 안 바뀐다" 의 뿌리는 `analysisResult.matchedScm.linked_docs`
 * (= 분석 시점 스냅샷)를 그대로 쓰는 화면들이었다. 스냅샷은 분석을 다시 돌리기 전엔
 * 절대 갱신되지 않는다.
 *
 * `SrsSdsSection` 에는 재조회 effect 가 있었지만 `ProjectSummarySection` 에는 **아예
 * 없었다** — 같은 결함을 한쪽만 고친 상태. 이 훅으로 단일화했고, 여기서 계약을 못 박는다.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

const mockApi = vi.fn();
vi.mock('../api.js', () => ({ api: (...a) => mockApi(...a) }));

const { useRegistryLinkedDocs } = await import('../scmLinkedDocs.js');

const SNAP = { suts: 'U:/old/SUTS.xlsm', vectorcast: ['U:/old/vc'] };
const REG = { suts: 'U:/new/SUTS.xlsm', vectorcast: ['U:/new/vc'] };

beforeEach(() => {
  mockApi.mockReset();
  mockApi.mockResolvedValue({ items: [{ id: 'p1', linked_docs: REG }] });
});

describe('useRegistryLinkedDocs', () => {
  it('레지스트리 값으로 스냅샷을 대체한다', async () => {
    const { result } = renderHook(() => useRegistryLinkedDocs('p1', SNAP));
    // 초기값은 스냅샷 — 빈 화면을 만들지 않는다.
    expect(result.current[0].suts).toBe('U:/old/SUTS.xlsm');
    await waitFor(() => expect(result.current[0].suts).toBe('U:/new/SUTS.xlsm'));
  });

  it('레지스트리 vectorcast 가 비면 스냅샷 것만 보강한다(경로는 레지스트리 최신본)', async () => {
    mockApi.mockResolvedValue({
      items: [{ id: 'p1', linked_docs: { suts: 'U:/new/SUTS.xlsm', vectorcast: [] } }],
    });
    const { result } = renderHook(() => useRegistryLinkedDocs('p1', SNAP));
    await waitFor(() => expect(result.current[0].suts).toBe('U:/new/SUTS.xlsm'));
    expect(result.current[0].vectorcast).toEqual(['U:/old/vc']);
  });

  it('조회 실패는 스냅샷 폴백 — 문서가 통째로 사라지지 않는다', async () => {
    mockApi.mockRejectedValue(new Error('network'));
    const { result } = renderHook(() => useRegistryLinkedDocs('p1', SNAP));
    await waitFor(() => expect(result.current[0].suts).toBe('U:/old/SUTS.xlsm'));
  });

  // ⚠ 아래 두 건은 "값이 **안** 바뀐다"를 단언한다. `waitFor(mockApi 호출됨)` 만으로는
  //   promise 체인이 끝나기 전에 통과해 버려, items[0] 폴백을 넣어도 초록이 된다
  //   (실측: 그 형태로 뮤테이션 M4 가 생존했다). 그래서 **다른 항목이 실제로 반영되는
  //   경로를 한 번 태워** 마이크로태스크가 다 빠졌음을 확인한 뒤 단언한다.
  async function settle() {
    await waitFor(() => expect(mockApi).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));
  }

  it('id 가 안 맞으면 다른 프로젝트 문서를 끌어오지 않는다', async () => {
    mockApi.mockResolvedValue({ items: [{ id: 'OTHER', linked_docs: { suts: 'U:/other/X.xlsm' } }] });
    const { result } = renderHook(() => useRegistryLinkedDocs('p1', SNAP));
    await settle();
    expect(result.current[0].suts).toBe('U:/old/SUTS.xlsm');
    expect(result.current[0].suts).not.toBe('U:/other/X.xlsm');
  });

  it('scmId 가 없으면 다른 프로젝트 문서로 채우지 않는다(items[0] 폴백 금지)', async () => {
    mockApi.mockResolvedValue({ items: [{ id: 'OTHER', linked_docs: { suts: 'U:/other/X.xlsm' } }] });
    const { result } = renderHook(() => useRegistryLinkedDocs('', SNAP));
    await settle();
    expect(result.current[0].suts).toBe('U:/old/SUTS.xlsm');
  });

  it('enabled=false 면 조회도 안 하고 빈 객체다(오귀속 게이트)', async () => {
    const { result } = renderHook(() => useRegistryLinkedDocs('p1', SNAP, false));
    await new Promise((r) => setTimeout(r, 60));
    expect(mockApi).not.toHaveBeenCalled();
    expect(result.current[0]).toEqual({});
  });
});
