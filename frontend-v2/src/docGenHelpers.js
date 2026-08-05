/**
 * DocGenSection 공용 헬퍼 — 컴포넌트 파일에서 분리한 이유는 두 가지다.
 *
 * 1. 두 헬퍼 모두 **원래 같은 파일 안에 두 벌씩 복제**돼 있었고, 그중 한쪽만
 *    결함이 있었다(아래 각 함수 주석 참조). 단일 출처로 두면 다음 수정이
 *    한쪽에만 반영되는 일이 구조적으로 불가능해진다 — 이 저장소의 1순위
 *    재발 패턴 방어.
 * 2. 컴포넌트 파일에서 비-컴포넌트를 export 하면 `react-refresh/only-export-components`
 *    가 걸린다. 테스트가 로직을 직접 겨냥할 수 있게 여기로 뺀다.
 */
import { useEffect, useRef, useState } from 'react';

import { api } from './api.js';

export const DOC_PATHS_KEY = 'devops_v2_doc_paths';

/**
 * 문서 경로 override 영속. 저장에 성공하면 true.
 *
 * ⚠ 예전엔 호출처 두 곳(경로 지정 / 초기화)이 각각
 *   `try { localStorage.setItem(...) } catch (_) {}` 였고 **그 직후에 성공 토스트**를
 *   띄웠다. 같은 origin 의 traceMatrixStore 가 단일 키에 최대 ~4MB 를 미러하므로
 *   브라우저 5MB 쿼터에 실제로 근접하고, 그 상태에서 QuotaExceededError 가 나면
 *   화면은 성공인데 새로고침 후 override 가 조용히 사라진다 → **사용자가 지정한
 *   것과 다른 요구사항 문서로 UDS/STS 가 생성된다.**
 *   그래서 실패를 반환값으로 알리고, 성공 토스트는 호출처가 true 일 때만 띄운다.
 */
export function persistDocPaths(next, toast) {
  try {
    localStorage.setItem(DOC_PATHS_KEY, JSON.stringify(next));
    return true;
  } catch (e) {
    toast('warning',
      `경로가 저장되지 않았습니다(${e?.name || 'StorageError'}) — 이 세션에서만 적용되고 ` +
      '새로고침하면 SCM 등록 경로로 되돌아갑니다.');
    return false;
  }
}

/**
 * SCM 폴백 — analysisResult 에 source_root 가 없으면 registry 첫 항목으로 채운다.
 *
 * ⚠ 예전엔 같은 본문이 DocGenSection.jsx 안에 두 번 있었고 한쪽 deps 만 `[scm]`
 *   이었다. 그쪽은 **무한 루프**였다: `/api/scm/list` 응답의 items[0] 은 매번 새
 *   객체라 setScm 이 항상 리렌더를 유발하고, source_root 가 빈 registry entry 가
 *   첫 항목이면 가드(`!scm?.source_root`)가 계속 참이라 fetch → setState → fetch
 *   가 끝나지 않는다. backend/schemas.py 에서 source_root 기본값이 "" 라 그런
 *   entry 는 실제로 만들어진다. DocGenHubSection 은 keep-alive(display:none)라
 *   다른 서브탭으로 옮겨도 백그라운드에서 계속 돈다.
 *
 *   `triedRef` 로 **1회만** 시도한다 — 응답이 비었든 실패했든 재요청하지 않는다.
 */
export function useScmFallback(analysisResult) {
  const [scm, setScm] = useState(
    () => analysisResult?.matchedScm || analysisResult?.scmList?.[0] || null,
  );
  const triedRef = useRef(false);
  useEffect(() => {
    if (scm?.source_root || triedRef.current) return;
    triedRef.current = true;
    api('/api/scm/list').then(d => {
      const items = d?.items || (Array.isArray(d) ? d : []);
      if (items.length > 0) setScm(items[0]);
    }).catch(() => {});
  }, [scm]);
  return [scm, setScm];
}
