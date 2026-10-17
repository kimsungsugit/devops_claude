import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../api.js', () => ({ api: vi.fn() }));

const { pollImpactJob } = await import('../impactPoll.js');
const { api } = await import('../api.js');

describe('impactPoll — abort 계약', () => {
  beforeEach(() => {
    api.mockReset();
  });

  // abort는 3초 대기 중이나 요청 왕복 중에 도착한다. 루프 선두에서만 검사하면 abort 이후에도
  // status 1회 + result 1회가 나가고, 호출측이 그 결과를 '정상 완료'로 받아 이미 떠난 화면의
  // 전역 상태에 써 넣는다 — 언마운트된 인스턴스의 옛 클로저로 프로젝트 검증까지 통과하면서.
  it('대기 중 abort되면 status도 result도 조회하지 않는다', async () => {
    vi.useFakeTimers();
    try {
      const controller = new AbortController();
      api.mockResolvedValue({ job: { status: 'completed', message: 'done' } });

      const settled = pollImpactJob('impact_1', { signal: controller.signal })
        .then(() => 'resolved', e => e.message);
      controller.abort();                       // 3초 대기 중 도착
      await vi.advanceTimersByTimeAsync(3500);

      expect(await settled).toBe('AbortError');
      expect(api).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('status 조회 왕복 중 abort되면 result를 조회하지 않는다', async () => {
    vi.useFakeTimers();
    try {
      const controller = new AbortController();
      api.mockImplementation(async (url) => {
        if (String(url).includes('/result')) return { result: { trigger: {} } };
        controller.abort();                     // status 응답을 받는 사이에 도착
        return { job: { status: 'completed', message: 'done' } };
      });

      const settled = pollImpactJob('impact_1', { signal: controller.signal })
        .then(() => 'resolved', e => e.message);
      await vi.advanceTimersByTimeAsync(3500);

      expect(await settled).toBe('AbortError');
      const urls = api.mock.calls.map(c => String(c[0]));
      expect(urls.filter(u => u.includes('/result'))).toHaveLength(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('abort가 없으면 완료 시 result를 반환한다(정상 경로 회귀)', async () => {
    vi.useFakeTimers();
    try {
      api.mockImplementation(async (url) => (
        String(url).includes('/result')
          ? { result: { trigger: { scm_id: 'hdpdm01' } } }
          : { job: { status: 'completed', message: '완료되었습니다.' } }
      ));

      const messages = [];
      const promise = pollImpactJob('impact_1', { onMsg: m => messages.push(m) });
      await vi.advanceTimersByTimeAsync(3500);

      await expect(promise).resolves.toEqual({ trigger: { scm_id: 'hdpdm01' } });
      expect(messages.join(' ')).toContain('완료되었습니다.');
    } finally {
      vi.useRealTimers();
    }
  });

  it('실패 잡은 사유를 담은 에러로 던진다', async () => {
    vi.useFakeTimers();
    try {
      api.mockResolvedValue({ job: { status: 'failed', error: { title: '이미 실행 중' } } });

      const settled = pollImpactJob('impact_1', {}).then(() => 'resolved', e => e.message);
      await vi.advanceTimersByTimeAsync(3500);

      expect(await settled).toBe('이미 실행 중');
    } finally {
      vi.useRealTimers();
    }
  });
});

/* isAbortError — 저장소 전체의 단일 abort 판별식
 *
 * 왜 관용적이어야 하는가: 저장소에 두 계열이 공존한다. 네이티브 fetch 는 `.name`이
 * 'AbortError'인 DOMException 을 던지고(SwUT·SwIT·SwSA·SwReport·AiAssist 7곳이 그걸로 판별),
 * impactPoll 은 합성 Error 를 던진다(Dashboard·ImpactGuideSection 3곳). 지금은 api.js 가
 * signal 인자를 안 받아 둘이 만나지 않지만, **api.js 에 signal 을 여는 순간** 네이티브
 * AbortError 가 message 계열 코드에 도달해 정상 취소가 "분석 중 오류: The operation was
 * aborted." 로 오보고된다. 양쪽을 다 받아 그 잠복 결함을 미리 해체한다.
 */
describe('isAbortError — 두 계열 판별', () => {
  it('impactPoll 이 던지는 에러를 abort 로 인식한다', async () => {
    const { isAbortError, throwIfAborted } = await import('../impactPoll.js');
    const controller = new AbortController();
    controller.abort();
    let caught;
    try { throwIfAborted(controller.signal); } catch (e) { caught = e; }
    expect(caught).toBeDefined();
    expect(isAbortError(caught)).toBe(true);
  });

  it('throwIfAborted 가 던지는 에러는 name 도 AbortError 다 (네이티브와 동형)', async () => {
    // `.message` 만 세팅하면 `.name` 은 'Error' 라, 이 폴러를 Sw* 섹션에서 재사용하는 순간
    // 그쪽의 `.name === 'AbortError'` 판별을 통과하지 못해 에러 토스트로 오보고된다.
    const { throwIfAborted } = await import('../impactPoll.js');
    const controller = new AbortController();
    controller.abort();
    let caught;
    try { throwIfAborted(controller.signal); } catch (e) { caught = e; }
    expect(caught.name).toBe('AbortError');
    expect(caught.message).toBe('AbortError');   // 기존 판별식·테스트 호환 유지
  });

  it('네이티브 fetch 의 DOMException 도 abort 로 인식한다', async () => {
    const { isAbortError } = await import('../impactPoll.js');
    // 네이티브 abort 의 실제 형태: name='AbortError', message 는 사람이 읽는 문장
    const native = new DOMException('The operation was aborted.', 'AbortError');
    expect(native.message).not.toBe('AbortError');   // message 만 보면 놓치는 형태임을 고정
    expect(isAbortError(native)).toBe(true);
  });

  it('일반 에러는 abort 로 오분류하지 않는다', async () => {
    const { isAbortError } = await import('../impactPoll.js');
    expect(isAbortError(new Error('네트워크 오류'))).toBe(false);
    expect(isAbortError(new TypeError('Failed to fetch'))).toBe(false);
    expect(isAbortError({ message: 'AbortError 관련 안내' })).toBe(false);  // 부분 일치 금지
    expect(isAbortError(null)).toBe(false);
    expect(isAbortError(undefined)).toBe(false);
  });
});
