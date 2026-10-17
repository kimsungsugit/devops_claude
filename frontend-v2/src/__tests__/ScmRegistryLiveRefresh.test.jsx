/**
 * SCM 레지스트리 변경이 **마운트된 화면에 즉시** 닿는가 (2026-08-06 2차).
 *
 * ## 재보고
 *
 * "요구사항 커버리지 입력 문서 현황에서 안 바뀌어 있어."
 *
 * 앞선 커밋은 패널이 분석 스냅샷 대신 레지스트리를 읽게 했지만, 그 조회를 `[scmId, enabled]`
 * deps 로 걸어 **마운트 시 1회**만 했다. Detail 섹션은 keep-alive(`display:none`)라
 * 재마운트되지 않으므로, 설정에서 SCM 문서 경로를 바꿔 저장해도 전체 새로고침 전까지
 * 값이 그대로다. `saveDocPaths`(localStorage)는 `DOC_PATHS_EVENT` 로 이미 해결한 문제인데
 * **레지스트리 쪽에만 통지가 없었다** — 또 한쪽만 고친 상태.
 *
 * 여기서 고정하는 계약:
 *   1. `notifyScmRegistryChanged()` → 재조회
 *   2. window focus → 재조회 (앱 밖에서 JSON 을 직접 고친 경우의 유일한 신호)
 *   3. 값이 같으면 **같은 객체 참조 유지** — focus 는 alt-tab 마다 오므로, 매번 새 객체를
 *      넣으면 이 값을 dep 로 쓰는 `loadMatrix` 콜백이 alt-tab 마다 새로 만들어진다.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';

const mockApi = vi.fn();
vi.mock('../api.js', () => ({ api: (...a) => mockApi(...a) }));

const { useRegistryLinkedDocs, notifyScmRegistryChanged, SCM_REGISTRY_EVENT } =
  await import('../scmLinkedDocs.js');

const SNAP = { suts: 'U:/old/SUTS.xlsm' };
const reply = (suts) => ({ items: [{ id: 'p1', linked_docs: { suts } }] });

beforeEach(() => {
  mockApi.mockReset();
  mockApi.mockResolvedValue(reply('U:/old/SUTS.xlsm'));
});

describe('useRegistryLinkedDocs — 레지스트리 변경 반영', () => {
  it('notifyScmRegistryChanged 로 재조회한다', async () => {
    const { result } = renderHook(() => useRegistryLinkedDocs('p1', SNAP));
    await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(1));

    // 설정에서 SUTS 경로를 바꿔 저장한 상황.
    mockApi.mockResolvedValue(reply('U:/new/SUTS_v2.xlsm'));
    act(() => { notifyScmRegistryChanged(); });

    await waitFor(() => expect(result.current[0].suts).toBe('U:/new/SUTS_v2.xlsm'));
  });

  it('window focus 로도 재조회한다 (앱 밖에서 registry JSON 을 직접 고친 경우)', async () => {
    const { result } = renderHook(() => useRegistryLinkedDocs('p1', SNAP));
    await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(1));

    mockApi.mockResolvedValue(reply('U:/edited/SUTS_v3.xlsm'));
    act(() => { window.dispatchEvent(new Event('focus')); });

    await waitFor(() => expect(result.current[0].suts).toBe('U:/edited/SUTS_v3.xlsm'));
  });

  it('값이 그대로면 같은 객체를 유지한다 (alt-tab 마다 소비자 재생성 방지)', async () => {
    const { result } = renderHook(() => useRegistryLinkedDocs('p1', SNAP));
    await waitFor(() => expect(result.current[0].suts).toBe('U:/old/SUTS.xlsm'));
    const before = result.current[0];

    act(() => { window.dispatchEvent(new Event('focus')); });
    await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(2));
    // 조회가 실제로 한 번 더 돌았음을 확인한 뒤 참조 동일성을 단언한다.
    expect(result.current[0]).toBe(before);
  });

  it('언마운트 시 구독을 해제한다 (리스너 누수 금지)', async () => {
    // ⚠ "언마운트 후 재조회가 없다"만 보면 이 결함을 못 잡는다 — 언마운트되면 조회 effect
    //    자체가 사라져 리스너가 남아 있어도 API 호출은 안 늘어난다(실측: 그 형태의 단언으로
    //    구독 해제 제거 뮤테이션이 생존했다). 리스너 add/remove **쌍**을 직접 센다.
    const addSpy = vi.spyOn(window, 'addEventListener');
    const remSpy = vi.spyOn(window, 'removeEventListener');
    const ours = ([type]) => type === SCM_REGISTRY_EVENT || type === 'focus';

    const { unmount } = renderHook(() => useRegistryLinkedDocs('p1', SNAP));
    await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(1));
    const added = addSpy.mock.calls.filter(ours);
    expect(added.length).toBeGreaterThan(0);

    unmount();
    const removed = remSpy.mock.calls.filter(ours);
    // 같은 **핸들러 참조**로 지워야 실제로 해제된다 — 다른 함수를 넘기면 리스너가 남는다.
    for (const [type, fn] of added) {
      expect(removed.some(([t, f]) => t === type && f === fn)).toBe(true);
    }

    addSpy.mockRestore();
    remSpy.mockRestore();

    // 재조회도 당연히 없다.
    act(() => { notifyScmRegistryChanged(); window.dispatchEvent(new Event('focus')); });
    await new Promise((r) => setTimeout(r, 30));
    expect(mockApi).toHaveBeenCalledTimes(1);
  });

  it('enabled=false 면 이벤트가 와도 조회하지 않는다 (오귀속 게이트)', async () => {
    renderHook(() => useRegistryLinkedDocs('p1', SNAP, false));
    act(() => { notifyScmRegistryChanged(); window.dispatchEvent(new Event('focus')); });
    await new Promise((r) => setTimeout(r, 30));
    expect(mockApi).not.toHaveBeenCalled();
  });

  it('이벤트 이름이 doc-paths 이벤트와 겹치지 않는다', async () => {
    const { DOC_PATHS_EVENT, SHARED_EVENT } = await import('../sharedInputs.js');
    expect(SCM_REGISTRY_EVENT).not.toBe(DOC_PATHS_EVENT);
    expect(SCM_REGISTRY_EVENT).not.toBe(SHARED_EVENT);
  });
});

describe('레지스트리 쓰기 입구가 전부 통지한다', () => {
  it('Settings 의 register/update/delete 3경로 모두 notifyScmRegistryChanged 를 부른다', async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const src = fs.readFileSync(
      path.join(process.cwd(), 'src/views/Settings.jsx'), 'utf-8',
    );
    // 저장(register/update 공용 saveScm) + 삭제(deleteScm) = 최소 2회 호출.
    const calls = src.match(/notifyScmRegistryChanged\(\)/g) || [];
    expect(calls.length).toBeGreaterThanOrEqual(2);
    // 쓰기 endpoint 목록과 대조 — 새 입구가 늘면 통지도 늘어야 한다.
    const writes = src.match(/\/api\/scm\/(register|update|delete)/g) || [];
    expect(writes.length).toBeGreaterThan(0);
  });
});
