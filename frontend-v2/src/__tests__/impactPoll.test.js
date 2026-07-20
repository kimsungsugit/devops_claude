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
