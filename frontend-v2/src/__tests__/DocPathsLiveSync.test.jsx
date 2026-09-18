/**
 * 설정에서 문서 경로를 저장하면 프로젝트 탭이 **같은 세션에서** 갱신된다 (2026-08-05).
 *
 * ## 사용자 보고
 *
 * "설정에서 경로저장을 하면 저장이 제대로 되어서 프로젝트 탭에서 모든 문서들이
 *  업데이트 되어야하는데 안되는거같다"
 *
 * ## 원인 (세 겹)
 *
 * 1. Settings 의 `setDoc`/`fillFromScm` 이 `localStorage.setItem` 만 하고
 *    **아무 통지도 하지 않았다.** 같은 탭에서는 `storage` 이벤트가 발화하지 않는다.
 * 2. 소비처가 **마운트 시 1회만** 읽었다 —
 *    `SrsSdsSection`: `useMemo(() => JSON.parse(localStorage…), [])`
 *    `DocGenSection`: `useState(() => …)`
 * 3. App(뷰)과 Detail(섹션)이 **양쪽 다 keep-alive**(display:none)라 탭을 오가도
 *    재마운트되지 않는다.
 *
 * → 전체 새로고침 전까지 옛 경로가 그대로 쓰였다. `SrsSdsSection` 의 값은
 *   `activeDocs` → 추적성 매트릭스 입력으로 흘러가므로, 사용자가 바꾼 문서가 아니라
 *   **옛 문서로 매트릭스가 만들어졌다.**
 *
 * ## 왜 이런 모양이 됐나 (판정 복제)
 *
 * 저장소는 같은 Settings 화면의 **다른 절반**(Sw* 양식/로그/메타)을 위해 이미
 * `SHARED_EVENT` + `useSharedInputSync` 라는 라이브 동기화를 만들어 뒀다. 그 훅의
 * docstring 이 문자 그대로 *"keep-alive로 마운트 유지되는 생성 섹션이 Settings의
 * 공유 입력 변경을 같은 세션에서 즉시 반영하도록 하는 훅"* 이다. 그런데
 * `sharedInputs.js` 상단 주석이 **"문서 경로는 본 모듈 밖"** 이라고 선을 그어,
 * 문서 경로만 그 메커니즘을 못 받았다.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';

import {
  DOC_PATHS_KEY, DOC_PATHS_EVENT, loadDocPaths, saveDocPaths, useDocPathsSync,
} from '../sharedInputs.js';

beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

/** 통지는 150ms 디바운스 — 타이머를 진행시킨다. */
function flushNotify() {
  act(() => { vi.advanceTimersByTime(200); });
}

describe('saveDocPaths / useDocPathsSync', () => {
  it('저장하면 keep-alive 구독자가 같은 세션에서 새 경로를 받는다', () => {
    saveDocPaths({ srs: 'U:/old/SRS.docx' });

    // 프로젝트 탭 섹션이 마운트된 상태(재마운트 없음)를 흉내낸다.
    const seen = [];
    renderHook(() => useDocPathsSync((next) => seen.push(next)));

    // 사용자가 설정 화면에서 경로를 바꿔 저장.
    saveDocPaths({ srs: 'U:/new/SRS_v2.docx', sds: 'U:/new/SDS.docx' });
    flushNotify();

    expect(seen.length).toBeGreaterThan(0);
    const last = seen[seen.length - 1];
    expect(last.srs).toBe('U:/new/SRS_v2.docx');
    expect(last.sds).toBe('U:/new/SDS.docx');
  });

  it('구독 해제 후에는 더 이상 받지 않는다(누수 방지)', () => {
    const seen = [];
    const { unmount } = renderHook(() => useDocPathsSync((n) => seen.push(n)));
    unmount();
    saveDocPaths({ srs: 'x' });
    flushNotify();
    expect(seen).toHaveLength(0);
  });

  it('다른 탭의 storage 이벤트도 반영하되, 무관한 키에는 반응하지 않는다', () => {
    const seen = [];
    renderHook(() => useDocPathsSync((n) => seen.push(n)));

    localStorage.setItem(DOC_PATHS_KEY, JSON.stringify({ srs: 'U:/other-tab.docx' }));
    act(() => {
      const e = new Event('storage');
      e.key = DOC_PATHS_KEY;
      window.dispatchEvent(e);
    });
    expect(seen.at(-1).srs).toBe('U:/other-tab.docx');

    const before = seen.length;
    act(() => {
      const e = new Event('storage');
      e.key = 'devops_v2_shared_inputs';   // 무관한 키
      window.dispatchEvent(e);
    });
    expect(seen.length).toBe(before);
  });

  it('손상된 JSON 이 저장돼 있어도 빈 객체로 복구한다', () => {
    localStorage.setItem(DOC_PATHS_KEY, '{not json');
    expect(loadDocPaths()).toEqual({});
    localStorage.setItem(DOC_PATHS_KEY, '[1,2]');   // 배열은 경로 맵이 아니다
    expect(loadDocPaths()).toEqual({});
  });

  it('쿼터 초과면 false 를 주고 통지하지 않는다', () => {
    const seen = [];
    renderHook(() => useDocPathsSync((n) => seen.push(n)));
    const spy = vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
      const e = new Error('quota'); e.name = 'QuotaExceededError'; throw e;
    });
    try {
      expect(saveDocPaths({ srs: 'x' })).toBe(false);
    } finally {
      spy.mockRestore();
    }
    flushNotify();
    expect(seen).toHaveLength(0);
  });
});

describe('두 알림 채널이 서로를 지우지 않는다', () => {
  it('문서 경로 저장이 Sw* 공유입력 통지를 삼키지 않는다', async () => {
    const { saveSharedInputs, SHARED_EVENT } = await import('../sharedInputs.js');
    const docHits = [];
    const sharedHits = [];
    const onDoc = () => docHits.push(1);
    const onShared = () => sharedHits.push(1);
    window.addEventListener(DOC_PATHS_EVENT, onDoc);
    window.addEventListener(SHARED_EVENT, onShared);
    try {
      // 디바운스 창 안에서 두 종류를 연달아 저장한다.
      saveSharedInputs({ project_id: 'HDPDM01' });
      saveDocPaths({ srs: 'U:/a.docx' });
      flushNotify();
      // 타이머를 공유하면 뒤쪽 저장이 앞쪽 통지를 clearTimeout 으로 지운다.
      expect(sharedHits.length).toBeGreaterThan(0);
      expect(docHits.length).toBeGreaterThan(0);
    } finally {
      window.removeEventListener(DOC_PATHS_EVENT, onDoc);
      window.removeEventListener(SHARED_EVENT, onShared);
    }
  });
});

describe('모든 쓰기 입구가 saveDocPaths 를 거친다', () => {
  it('docGenHelpers.persistDocPaths 도 통지한다', async () => {
    const { persistDocPaths } = await import('../docGenHelpers.js');
    const seen = [];
    renderHook(() => useDocPathsSync((n) => seen.push(n)));
    expect(persistDocPaths({ uds: 'U:/from-docgen.docx' }, vi.fn())).toBe(true);
    flushNotify();
    expect(seen.at(-1).uds).toBe('U:/from-docgen.docx');
  });

  it('Settings 소스에 직접 setItem(DOC_KEY) 가 남아 있지 않다', async () => {
    // 한 입구라도 직접 쓰면 그 경로로 저장한 값만 갱신되지 않는다 —
    // 사용자에게는 "어떤 건 되고 어떤 건 안 된다"로 보이는 가장 짚기 어려운 형태다.
    // jsdom 에서 import.meta.url 은 file: 스킴이 아니라 URL 로 못 연다 — cwd 기준 경로.
    const [fs, path] = await Promise.all([import('fs'), import('path')]);
    const src = fs.readFileSync(
      path.join(process.cwd(), 'src', 'views', 'Settings.jsx'), 'utf-8');
    expect(src).not.toMatch(/localStorage\.setItem\(\s*DOC_KEY/);
    expect(src).toMatch(/saveDocPaths\(/);
  });
});

describe('waitFor 로 실제 비동기 전파도 확인', () => {
  it('실시간 타이머에서도 구독자가 갱신된다', async () => {
    vi.useRealTimers();
    const seen = [];
    renderHook(() => useDocPathsSync((n) => seen.push(n)));
    saveDocPaths({ sits: 'U:/real.xlsm' });
    await waitFor(() => expect(seen.at(-1)?.sits).toBe('U:/real.xlsm'));
  });
});
