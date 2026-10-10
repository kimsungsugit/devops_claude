/**
 * `runVectorcastRagJob` — sync 블로킹 호출을 잡 + 폴링으로 대체한 drop-in.
 *
 * 배경: 백엔드는 `-async` 를 만들고 docstring 에 "동기 호출은 4~5분 블로킹 → 브라우저/프록시
 * 타임아웃·탭 전환 abort로 '에러처럼' 보였다" 라고 적어 놨는데, **호출처 3곳 중 하나만**
 * 옮겨져 있었다. 매트릭스 경로 둘이 sync 로 남아, 프록시 타임아웃에 끊기면 **VectorCAST 없는
 * 매트릭스가 만들어져 그대로 캐시**됐다(캐시 저장은 무조건 — 의도된 결정).
 *
 * 여기서 못 박는 계약:
 *   1. 반환 shape 이 sync 엔드포인트와 **같다** — 안 그러면 호출부가 조용히 빈손이 된다
 *   2. 실패/타임아웃/중단은 **`parse_warnings` 로 사유가 나온다** (빈 결과를 성공으로 위장 금지)
 *   3. 잡이 사라지면 즉시 포기, 네트워크 깜빡임은 재시도 (4분짜리가 한 번 끊겨 죽지 않게)
 *   4. `shouldContinue` 가 false 면 폴링이 **멈춘다** (언마운트 후 12분 폴링 누수 방지)
 *
 * ⚠ 시계·대기는 주입한다 — 12분 타임아웃을 실제로 기다리면 테스트가 게이트를 죽인다.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockApi = vi.fn();
const mockPost = vi.fn();
vi.mock('../api.js', () => ({
  api: (...a) => mockApi(...a),
  post: (...a) => mockPost(...a),
}));

const {
  runVectorcastRagJob, VCAST_JOB_TIMEOUT_MS, VCAST_JOB_MAX_TRANSIENT,
} = await import('../vcastRagJob.js');

/**
 * 실제로 안 자는 sleep + 수동으로 굴리는 시계.
 *
 * ⚠ `await` 만 하고 끝내면 **microtask 만** 돌아 macrotask 큐가 굶는다. 그러면 폴링이
 *   끝나지 않는 상황(타임아웃 로직이 깨진 경우 등)에서 vitest 의 testTimeout 조차 발화하지
 *   못하고 **러너가 통째로 멈춘다** — 실측으로 뮤테이션 하네스를 10분 넘게 얼렸다.
 *   이 저장소에서 "오래 걸림"의 실체는 늘 느림이 아니라 hang 이었다.
 *   `setTimeout(0)` 으로 매 주기 macrotask 를 양보해, 고장은 **FAIL 로** 끝나게 한다.
 */
function harness(startMs = 1_000_000) {
  let t = startMs;
  return {
    now: () => t,
    sleep: async (ms) => { t += ms; await new Promise((r) => setTimeout(r, 0)); },
    advance: (ms) => { t += ms; },
  };
}

const BODY = { job_url: 'http://j/1', cache_root: '.c', vcast_log_paths: ['U:/vc'] };

beforeEach(() => {
  mockApi.mockReset();
  mockPost.mockReset();
  mockPost.mockResolvedValue({ job_id: 'job-1' });
});

describe('runVectorcastRagJob', () => {
  it('완료되면 sync 엔드포인트와 **동일한 shape** 을 그대로 돌려준다', async () => {
    const result = { ok: true, data: { test_rows: [{ subprogram: 'f' }] }, source: 'cloudium' };
    mockApi
      .mockResolvedValueOnce({ job: { status: 'running' } })
      .mockResolvedValueOnce({ job: { status: 'completed', result } });

    const h = harness();
    const out = await runVectorcastRagJob(BODY, h);

    expect(out).toEqual(result);
    expect(mockPost).toHaveBeenCalledWith('/api/jenkins/report/vectorcast-rag-async', BODY);
  });

  it('sync 가 아니라 **async 엔드포인트**를 부른다', async () => {
    mockApi.mockResolvedValue({ job: { status: 'completed', result: { ok: true, data: {} } } });
    await runVectorcastRagJob(BODY, harness());
    const url = mockPost.mock.calls[0][0];
    expect(url).toContain('vectorcast-rag-async');
  });

  it('잡 실패는 사유를 parse_warnings 로 올린다 (빈 결과 위장 금지)', async () => {
    mockApi.mockResolvedValue({ job: { status: 'failed', error: { title: 'worker down' } } });
    const out = await runVectorcastRagJob(BODY, harness());
    expect(out.ok).toBe(false);
    expect(out.parse_warnings.join(' ')).toContain('worker down');
  });

  // `{}` 는 truthy 라 `result || _fail()` 로는 못 걸린다. 그대로 흘리면 호출부에서
  // test_rows 도 parse_warnings 도 없어 **사유 없는 빈손**이 된다(경고 게이트 미발화).
  it.each([
    ['null', null],
    ['undefined', undefined],
    ['빈 객체 {}', {}],
  ])('완료했는데 result 가 %s 면 사유로 남긴다 (조용한 빈손 금지)', async (_label, result) => {
    mockApi.mockResolvedValue({ job: { status: 'completed', result } });
    const out = await runVectorcastRagJob(BODY, harness());
    expect(out.ok).toBe(false);
    expect(out.parse_warnings.join(' ')).toMatch(/결과가 비어/);
  });

  it('ok:false 인 정상 실패 응답은 그대로 통과시킨다 (사유를 덮어쓰지 않는다)', async () => {
    const result = { ok: false, error: 'missing', parse_warnings: ['폴더 부재'] };
    mockApi.mockResolvedValue({ job: { status: 'completed', result } });
    expect(await runVectorcastRagJob(BODY, harness())).toEqual(result);
  });

  it('타임아웃은 무한 폴링 대신 사유와 함께 끝난다', async () => {
    mockApi.mockResolvedValue({ job: { status: 'running' } });
    const h = harness();
    // 폴링 한 번마다 시계를 크게 밀어 상한을 넘긴다.
    const orig = h.sleep;
    h.sleep = async (ms) => { await orig(ms); h.advance(VCAST_JOB_TIMEOUT_MS / 3); };

    const out = await runVectorcastRagJob(BODY, h);
    expect(out.ok).toBe(false);
    expect(out.error).toBe('timeout');
    expect(out.parse_warnings.join(' ')).toMatch(/시간 초과/);
  });

  it('잡이 사라지면(404) 즉시 포기한다 — 되살아나는 무한 폴링 방지', async () => {
    mockApi.mockRejectedValue(new Error('404 not found'));
    const out = await runVectorcastRagJob(BODY, harness());
    expect(out.error).toBe('job_missing');
    expect(mockApi).toHaveBeenCalledTimes(1);
  });

  it('네트워크 깜빡임은 재시도한다 — 4분짜리 잡이 한 번 끊겨 죽지 않게', async () => {
    const result = { ok: true, data: { test_rows: [] } };
    mockApi
      .mockRejectedValueOnce(new Error('network'))
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce({ job: { status: 'completed', result } });

    const out = await runVectorcastRagJob(BODY, harness());
    expect(out).toEqual(result);
  });

  it('연속 실패가 상한을 넘으면 사유와 함께 포기한다', async () => {
    mockApi.mockRejectedValue(new Error('network'));
    const out = await runVectorcastRagJob(BODY, harness());
    expect(out.error).toBe('poll_failed');
    expect(mockApi).toHaveBeenCalledTimes(VCAST_JOB_MAX_TRANSIENT + 1);
  });

  it('shouldContinue 가 false 면 폴링을 멈춘다 (언마운트 누수 방지)', async () => {
    mockApi.mockResolvedValue({ job: { status: 'running' } });
    let alive = true;
    const h = harness();
    const out = await runVectorcastRagJob(BODY, {
      ...h,
      shouldContinue: () => alive,
      onProgress: () => { alive = false; },   // 첫 진행 보고 직후 화면이 사라진 상황
    });
    expect(out.error).toBe('aborted');
    expect(mockApi.mock.calls.length).toBeLessThanOrEqual(2);
  });

  it('job_id 가 없으면 조용히 빈손이 되지 않고 throw 한다', async () => {
    mockPost.mockResolvedValue({});
    await expect(runVectorcastRagJob(BODY, harness())).rejects.toThrow(/job_id/);
  });

  it('진행 상황을 경과 시간과 함께 보고한다', async () => {
    mockApi
      .mockResolvedValueOnce({ job: { status: 'running' } })
      .mockResolvedValueOnce({ job: { status: 'completed', result: { ok: true, data: {} } } });
    const msgs = [];
    await runVectorcastRagJob(BODY, { ...harness(), onProgress: (m) => msgs.push(m) });
    expect(msgs.length).toBeGreaterThan(0);
    expect(msgs[0]).toMatch(/VectorCAST/);
    expect(msgs[0]).toMatch(/초 경과/);
  });
});

describe('호출처가 sync 로 되돌아가지 않았는지 (구조 가드)', () => {
  it('매트릭스 경로 두 곳은 sync /report/vectorcast-rag 를 직접 부르지 않는다', async () => {
    const fs = await import('node:fs');
    const path = await import('node:path');
    const SRC = path.resolve(process.cwd(), 'src');
    const targets = [
      'traceMatrix.js',
      'components/sections/SrsSdsSection.jsx',
    ];
    const offenders = [];
    for (const rel of targets) {
      const src = fs.readFileSync(path.join(SRC, rel), 'utf-8');
      // '-async' 가 아닌 sync 경로 리터럴만 잡는다.
      if (/['"`]\/api\/jenkins\/report\/vectorcast-rag['"`]/.test(src)) offenders.push(rel);
      if (!src.includes('runVectorcastRagJob')) offenders.push(`${rel} (헬퍼 미사용)`);
    }
    expect(offenders, `sync 블로킹 호출로 되돌아갔다: ${offenders.join(', ')}`).toEqual([]);
  });
});
