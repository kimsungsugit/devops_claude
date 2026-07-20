import { api } from './api.js';

/** abort 검사 단일 지점.
 *
 * 폴링 루프는 **대기 중**과 **요청 왕복 중**에 취소를 받는다. 루프 선두에서만 검사하면 취소
 * 이후에도 조회 1회 + 후속 요청 1회가 나가고, 호출측이 그 결과를 '정상 완료'로 받아 이미
 * 떠난 화면의 전역 상태에 써 넣는다. 그래서 모든 await 경계마다 이 함수를 통과시킨다.
 *
 * `name`을 'AbortError'로 세팅하는 이유: 네이티브 fetch 는 abort 시 `.name === 'AbortError'`
 * 인 DOMException 을 던지고, 저장소의 SwUT·SwIT·SwSA·SwReport·AiAssist 가 그 규약으로
 * 판별한다(그쪽은 `api.js postSse` 가 signal 을 fetch 에 넘겨 실제로 취소가 동작한다).
 * 여기서 `.message` 만 'AbortError' 인 평범한 Error 를 던지면 `.name` 은 'Error' 라 그 판별을
 * 통과하지 못한다 — 이 폴러를 그쪽에서 재사용하는 순간 정상 취소가 에러 토스트로 오보고된다.
 * `.message` 도 같은 값으로 두는 건 사람이 로그에서 읽기 위해서다(판별에는 안 쓴다).
 */
export function throwIfAborted(signal) {
  if (signal?.aborted) {
    const err = new Error('AbortError');
    err.name = 'AbortError';
    throw err;
  }
}

/** abort 로 끝난 예외인지 — 저장소 전체의 단일 판별식.
 *
 * `.name` 만 본다. 웹 플랫폼 표준(네이티브 fetch 의 DOMException)이자, 위 throwIfAborted 가
 * 합성 에러에도 `.name` 을 세팅하므로 이 하나로 두 계열이 모두 잡힌다.
 *
 * `.message === 'AbortError'` 도 받도록 넓히고 싶어지는데(예전에 그랬다) **하지 않는다**:
 * `.name` 세팅 이후로 그 조건이 추가로 잡아내는 진짜 abort 는 0건이고, 백엔드 오류 문구가
 * 우연히 그 문자열이면 **진짜 실패를 취소로 오인해 조용히 삼키는** 표면만 남는다
 * (api.js `_toError` 가 서버 detail/message 를 그대로 Error 로 감싼다).
 */
export function isAbortError(e) {
  return e?.name === 'AbortError';
}

/** 영향도 잡을 완료/실패까지 폴링하고 result를 돌려준다.
 *
 * Dashboard(최초 분석 파이프라인 4단계)와 '변경 영향 평가' 탭(빌드별 재실행)이 공유한다.
 * 두 진입점이 각자 복사본을 들면 폴링 주기·경과 표기·실패 문구가 갈라지므로 단일 출처로 둔다.
 */
export async function pollImpactJob(jobId, { onMsg, signal } = {}) {
  const t0 = Date.now();
  while (true) {
    throwIfAborted(signal);
    await new Promise(r => setTimeout(r, 3000));
    throwIfAborted(signal);
    const data = await api(`/api/scm/impact-job/${encodeURIComponent(jobId)}`);
    throwIfAborted(signal);
    const job = data?.job || {};
    const elapsed = Math.round((Date.now() - t0) / 1000);
    const timeStr = elapsed > 60 ? `${Math.floor(elapsed / 60)}분 ${elapsed % 60}초` : `${elapsed}초`;
    const msg = job.message || job.stage || '';
    onMsg?.(`${msg} (${timeStr} 경과)`);
    if (job.status === 'completed') {
      const resultData = await api(`/api/scm/impact-job/${encodeURIComponent(jobId)}/result`);
      throwIfAborted(signal);  // 결과를 호출측에 넘기기 직전 최종 확인
      return resultData?.result || {};
    }
    if (job.status === 'failed') {
      const err = job.error?.title || job.error?.detail || '영향도 분석 실패';
      throw new Error(err);
    }
  }
}
