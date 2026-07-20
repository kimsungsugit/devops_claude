import { api } from './api.js';

/** abort 검사 단일 지점.
 *
 * 폴링 루프는 **대기 중**과 **요청 왕복 중**에 취소를 받는다. 루프 선두에서만 검사하면 취소
 * 이후에도 조회 1회 + 후속 요청 1회가 나가고, 호출측이 그 결과를 '정상 완료'로 받아 이미
 * 떠난 화면의 전역 상태에 써 넣는다. 그래서 모든 await 경계마다 이 함수를 통과시킨다.
 */
export function throwIfAborted(signal) {
  if (signal?.aborted) throw new Error('AbortError');
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
