/**
 * VectorCAST RAG 수집 — 동기 블로킹 호출을 **백그라운드 잡 + 폴링**으로 대체하는 drop-in.
 *
 * 반환 shape 은 동기 `/api/jenkins/report/vectorcast-rag` 와 **동일**하다
 * (`{ok, data, comparison, source}` 또는 `{ok:false, error, parse_warnings}`).
 * 그래서 호출부는 `await post(...)` 를 `await runVectorcastRagJob(...)` 로 바꾸기만 하면 된다.
 *
 * ## 왜 필요한가
 *
 * 백엔드는 이미 `-async` 를 만들어 두고 docstring 에 이렇게 적어 놨다:
 *
 * > "동기 호출은 원격 IPC 직렬 파싱으로 4~5분 블로킹 → 브라우저/프록시 타임아웃·탭 전환
 * >  abort로 '에러처럼' 보였다. 잡으로 돌리고 기존 폴링을 재사용한다."
 *
 * 그런데 **호출처 3곳 중 `AnalysisSection` 하나만** 옮겨졌다. 매트릭스 경로 둘
 * (`SrsSdsSection.loadMatrix`, `traceMatrix.buildTraceMatrix`)은 sync 그대로였다.
 *
 * 단순히 느린 게 아니라 **데이터가 조용히 빠진다**: sync 호출이 프록시 타임아웃으로 끊기면
 * 매트릭스는 VectorCAST 없이 만들어지고, 캐시 저장은 무조건이라(`SrsSdsSection` :609-621,
 * 의도된 결정) 그 반쪽짜리가 그대로 굳는다. 경고는 함께 저장돼 재노출되므로 완전 침묵은
 * 아니지만, 사용자가 알아채고 강제 새로고침해야 한다.
 *
 * 폴링은 요청 하나하나가 짧아 프록시/브라우저 타임아웃에 걸리지 않는다 — 그게 핵심 이득이다.
 *
 * ## `AnalysisSection.pollJob` 과 왜 합치지 않았나
 *
 * 거기는 **remount·새로고침을 넘겨 잡을 이어받는** 게 요구사항이라 localStorage 영속 +
 * focus/visibilitychange 복구가 붙어 있다. 여기는 `await` 로 이어지는 선형 흐름 안이라
 * 그 장치가 필요 없고, 억지로 한 모양으로 묶으면 양쪽이 다 복잡해진다.
 * ⚠ 대신 **폴링 계약(상태 필드·완료/실패 판정·타임아웃)은 같아야 한다** — 한쪽만 바뀌면
 *   같은 잡을 두 화면이 다르게 읽는다. 바꿀 땐 둘 다 볼 것.
 */
import { api, post } from './api.js';

export const VCAST_JOB_TIMEOUT_MS = 12 * 60 * 1000;  // AnalysisSection.pollJob 과 동일 상한
export const VCAST_JOB_POLL_MS = 3000;
/** 연속 조회 실패 허용 횟수 — 4분짜리 잡이 네트워크 깜빡임 한 번에 죽지 않게. */
export const VCAST_JOB_MAX_TRANSIENT = 3;

const _sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** 잡이 사라진 경우(서버 재시작·프룬)는 재시도해도 소용없다 — 즉시 포기. */
function _isGone(err) {
  return /not found|404/i.test(String(err?.message || ''));
}

function _fail(error, reason) {
  // sync 엔드포인트의 실패 shape 과 동일하게 — 호출부의 기존 경고 경로가 그대로 탄다.
  return { ok: false, error, parse_warnings: [reason] };
}

/**
 * VectorCAST RAG 를 백그라운드 잡으로 실행하고 완료까지 폴링한다.
 *
 * @param {object} body  sync 엔드포인트와 동일한 요청 body
 * @param {object} [opts]
 * @param {(msg:string)=>void} [opts.onProgress]     진행 표시(초 단위 경과 포함)
 * @param {()=>boolean} [opts.shouldContinue]        false 를 반환하면 폴링 중단(언마운트 등)
 * @param {()=>number}  [opts.now]                   테스트 주입용 시계
 * @param {(ms:number)=>Promise<void>} [opts.sleep]  테스트 주입용 대기
 * @returns {Promise<object>} sync 응답과 동일 shape
 * @throws 잡 **생성** 실패 시에만 throw — 호출부의 기존 catch 가 사유를 표면화한다.
 */
export async function runVectorcastRagJob(body, opts = {}) {
  const {
    onProgress,
    shouldContinue,
    now = () => Date.now(),
    sleep = _sleep,
  } = opts;
  const alive = () => (shouldContinue ? shouldContinue() !== false : true);

  const start = await post('/api/jenkins/report/vectorcast-rag-async', body);
  const jobId = start?.job_id;
  if (!jobId) {
    // 잡 id 가 없으면 폴링할 대상이 없다. 조용히 빈 결과를 만들지 말고 사유를 올린다.
    throw new Error('VectorCAST 잡 생성 실패 — 응답에 job_id 가 없습니다.');
  }

  const t0 = now();
  let transient = 0;
  while (alive()) {
    let st;
    try {
      st = await api(`/api/scm/impact-job/${jobId}`);
      transient = 0;
    } catch (e) {
      if (_isGone(e)) return _fail('job_missing', `VectorCAST 잡을 찾을 수 없습니다(${jobId}) — 서버 재시작 가능`);
      if (++transient > VCAST_JOB_MAX_TRANSIENT) {
        return _fail('poll_failed', `VectorCAST 상태 조회가 ${transient}회 연속 실패: ${e.message}`);
      }
      // 깜빡임 — 다음 주기에 다시 본다.
      if (!alive()) break;
      await sleep(VCAST_JOB_POLL_MS);
      continue;
    }

    const job = st?.job || {};
    if (job.status === 'completed') {
      // sync 와 동일 shape 그대로 넘긴다.
      // ⚠ `job.result || _fail(...)` 로는 부족하다 — `{}` 는 truthy 라 그대로 통과하고,
      //   호출부에선 test_rows 도 parse_warnings 도 없어 **사유 없는 빈손**이 된다
      //   (경고 게이트가 `!rows.length && warnings.length` 라 발화조차 안 한다).
      //   백엔드 계약상 결과엔 `ok` 또는 `data` 가 반드시 있으므로 그걸로 판별한다.
      const r = job.result;
      if (r && (r.ok !== undefined || r.data !== undefined)) return r;
      return _fail('empty_result', 'VectorCAST 잡이 완료됐으나 결과가 비어 있습니다.');
    }
    if (job.status === 'failed') {
      const why = job.error?.title || job.error?.detail || 'unknown';
      return _fail('job_failed', `VectorCAST 잡 실패: ${why}`);
    }

    const elapsed = now() - t0;
    if (elapsed > VCAST_JOB_TIMEOUT_MS) {
      return _fail(
        'timeout',
        `VectorCAST 로딩 시간 초과(${Math.round(VCAST_JOB_TIMEOUT_MS / 60000)}분) — 다시 시도하면 캐시로 빨라집니다.`,
      );
    }
    onProgress?.(`VectorCAST 원격 파싱 중… ${Math.round(elapsed / 1000)}초 경과`);
    if (!alive()) break;
    await sleep(VCAST_JOB_POLL_MS);
  }
  // shouldContinue 가 끊었다 — 빈 결과를 성공으로 위장하지 않는다.
  return _fail('aborted', 'VectorCAST 수집이 중단되었습니다(화면 이동).');
}
