import { api } from './api.js';
import { throwIfAborted } from './impactPoll.js';

/**
 * 문서 생성(UDS/STS/SUTS/SITS) 진행 폴러.
 *
 * DocGenSection.jsx 안에 있었는데 별도 모듈로 뺐다 — 컴포넌트 파일에서 비컴포넌트를
 * export 하면 Vite Fast Refresh 가 그 파일 전체에 대해 무력화된다
 * (react-refresh/only-export-components). 테스트가 signal 을 실제로 넘기려면 export 가
 * 필요했고, 그 둘을 동시에 만족하는 방법이 모듈 분리다.
 */
// abort 계약: **throw**, 그리고 **모든 await 경계에서** 검사한다(impactPoll 과 동일 규약).
// 예전엔 두 폴러가 null 을 돌려줬는데, 호출측의 `progress?.error` 가 optional chaining 이라
// null 을 무해하게 통과시켜 그대로 "생성 완료" + 성공 토스트 + success:true 로 흘렀다.
// 즉 **취소가 성공으로 위장**됐다(ISO 26262 산출물 생성 경로).
// ⚠ throw 로 바꾸는 것만으로는 부족하다: 루프 선두와 sleep 뒤에만 검사하면 `await api()`
// 왕복 중에 도착한 중단을 놓쳐 `done:true` 응답이 그대로 성공 처리된다. 창을 좁힐 뿐
// 닫지 못한다 — 그래서 api() 직후에도 검사한다.
export async function pollProgress(jobUrl, buildSelector, jobId, action, { onMsg, signal }) {
  while (true) {
    throwIfAborted(signal);
    await new Promise(r => setTimeout(r, 2000));
    throwIfAborted(signal);
    const data = await api(
      `/api/jenkins/progress?action=${encodeURIComponent(action)}` +
      `&job_url=${encodeURIComponent(jobUrl)}` +
      `&build_selector=${encodeURIComponent(buildSelector)}` +
      `&job_id=${encodeURIComponent(jobId)}`
    );
    throwIfAborted(signal);  // 요청 왕복 중 도착한 '중단' — 없으면 done:true 가 그대로 성공 처리된다
    const p = data?.progress || {};
    if (p.message || p.stage) onMsg(p.message || p.stage);
    if (p.progress != null) onMsg(`${p.message || ''} (${p.progress}%)`);
    if (p.done || p.error) return p;
  }
}

export async function pollStsProgress(jobId, action, jobUrl, { onMsg, signal, prefix = '/api/jenkins' } = {}) {
  while (true) {
    throwIfAborted(signal);
    await new Promise(r => setTimeout(r, 3000));
    throwIfAborted(signal);
    const qs = `job_id=${encodeURIComponent(jobId)}&job_url=${encodeURIComponent(jobUrl || '')}`;
    const data = await api(`${prefix}/${action}/progress?${qs}`);
    throwIfAborted(signal);  // 요청 왕복 중 도착한 '중단' (return 지점이 3개라 창이 더 넓다)
    const p = data?.progress || data || {};
    if (p.message || p.stage) onMsg(p.message || p.stage);
    if (p.done || p.error) return p;
    if (p.status === 'completed' || p.status === 'done') return { done: true, ...p };
    if (p.status === 'failed' || p.status === 'error') return { error: p.error || p.message || '실패', ...p };
  }
}
