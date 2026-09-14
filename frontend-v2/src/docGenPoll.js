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
/**
 * (R48-b) 진행 응답에 실린 **생성 중 문제 목록**을 호출자에게 넘긴다.
 * 서버(`report_gen/gen_issues.py`)가 `issues`(배열)·`issue_counts` 를 매 진행마다 통째로 싣는다 — 누적은 서버 몫이라
 * 여기서는 마지막 값을 그대로 전달한다. 배열이 아니면(구 서버·다른 경로) 부르지 않는다: 빈 배열로 접으면
 * "문제 0건" 으로 읽힌다.
 */
function emitIssues(p, onIssues) {
  if (typeof onIssues === 'function' && Array.isArray(p?.issues)) onIssues(p.issues, p.issue_counts || null);
}

export async function pollProgress(jobUrl, buildSelector, jobId, action, { onMsg, onIssues, signal }) {
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
    emitIssues(p, onIssues);
    if (p.message || p.stage) onMsg(p.message || p.stage);
    // ⚠ 서버가 넣는 필드는 `percent` 다(`helpers/uds.py::_set_progress`, `jenkins.py`).
    // 여기서 `p.progress` 만 읽던 탓에 이 줄은 **한 번도 발화한 적이 없고**, 화면의 %는
    // `DocGenSection::resolveProgress` 가 메시지 문자열을 stageMap 으로 역추론한
    // 추정치였다. percent 우선 + progress 폴백으로 실제 값을 흘린다.
    const pct = p.percent != null ? p.percent : p.progress;
    if (pct != null) onMsg(`${p.message || ''} (${pct}%)`);
    if (p.done || p.error) return p;
  }
}

export async function pollStsProgress(jobId, action, jobUrl, { onMsg, onIssues, signal, prefix = '/api/jenkins' } = {}) {
  while (true) {
    throwIfAborted(signal);
    await new Promise(r => setTimeout(r, 3000));
    throwIfAborted(signal);
    const qs = `job_id=${encodeURIComponent(jobId)}&job_url=${encodeURIComponent(jobUrl || '')}`;
    const data = await api(`${prefix}/${action}/progress?${qs}`);
    throwIfAborted(signal);  // 요청 왕복 중 도착한 '중단' (return 지점이 3개라 창이 더 넓다)
    const p = data?.progress || data || {};
    emitIssues(p, onIssues);
    if (p.message || p.stage) onMsg(p.message || p.stage);
    // UDS 폴러와 동일 — 서버 필드는 `percent`(위 주석 참조).
    const pct = p.percent != null ? p.percent : p.progress;
    if (pct != null) onMsg(`${p.message || ''} (${pct}%)`);
    if (p.done || p.error) return p;
    if (p.status === 'completed' || p.status === 'done') return { done: true, ...p };
    if (p.status === 'failed' || p.status === 'error') return { error: p.error || p.message || '실패', ...p };
  }
}
