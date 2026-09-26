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
import { DOC_PATHS_KEY, saveDocPaths } from './sharedInputs.js';

export { DOC_PATHS_KEY };

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
  // 저장 + **같은 탭 통지**는 sharedInputs.saveDocPaths 단일 출처를 거친다.
  // 여기서 직접 setItem 하면 이 입구로 저장한 값만 프로젝트 탭에 반영되지 않는다.
  let err = null;
  if (saveDocPaths(next, (e) => { err = e; })) return true;
  toast('warning',
    `경로가 저장되지 않았습니다(${err?.name || 'StorageError'}) — 이 세션에서만 적용되고 ` +
    '새로고침하면 SCM 등록 경로로 되돌아갑니다.');
  return false;
}

/**
 * 후보가 **정확히 하나일 때만** 그 항목. 여럿이면 `null` — 오귀속이 가능한 순간이다.
 *
 * ⚠ 후보가 여럿인데 하나를 집으면 화면상 아무 증상 없이 **다른 프로젝트의 자료**가
 *   쓰인다(실측: 이 저장소 레지스트리엔 프로젝트가 3개 등록돼 있다). 하나뿐이면
 *   오귀속 자체가 불가능하므로 그대로 쓴다 — `impactGuard` 의 표시/트리거 정책과
 *   같은 결이다("다르다고 증명되는 경우만 막는다" vs "증거 없으면 거부").
 */
/**
 * SCM 폴백 — analysisResult 에 source_root 가 없으면 registry 항목으로 채운다.
 *
 * ⚠ **첫 항목을 집지 않는다.** 예전엔 `scmList?.[0]`·`items[0]` 로 무조건 첫 항목을
 *   집었다 — 그러면 이 훅이 먹이는 '문서 현황' 표가 남의 프로젝트 연결문서를 보여 주고,
 *   `registerVcast` 는 남의 `source_root` 로 패키지를 등록한다. 확정 못 하면 `null` 로
 *   두어 표가 `-` 를 보이게 한다(= 모르는 것을 모른다고 그린다).
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
/**
 * 상한 저장 칸을 가르는 **프로젝트 식별자**.
 *
 * ⚠ 게이트와 생성이 서로 다른 스코프를 쓰면 화면이 보여 준 상한과 실제로 실리는 상한이
 *   갈린다 — `resolveCacheRoot` 를 단일 출처로 만든 것과 같은 사유다. 그래서 두 화면이
 *   모두 이 함수를 쓴다.
 *
 * 기준은 `job.url` 이다. SCM id 가 더 '프로젝트'에 가깝지만 게이트 패널에는 없고,
 * 생성 직전 `contextConflict` 가 job ↔ analysisResult 일치를 이미 보장한다.
 * 정규화는 `normDocPath` 와 같은 결(대소문자·끝 슬래시 흡수)로 맞춘다.
 */
export function docGenCapsScope(job) {
  return String(job?.url || '').trim().replace(/\/+$/, '').toLowerCase();
}

export function soleScmEntry(list) {
  return Array.isArray(list) && list.length === 1 ? list[0] : null;
}

export function useScmFallback(analysisResult) {
  const [scm, setScm] = useState(
    () => analysisResult?.matchedScm || soleScmEntry(analysisResult?.scmList) || null,
  );
  const triedRef = useRef(false);
  useEffect(() => {
    if (scm?.source_root || triedRef.current) return;
    triedRef.current = true;
    api('/api/scm/list').then(d => {
      const items = d?.items || (Array.isArray(d) ? d : []);
      const sole = soleScmEntry(items);
      if (sole) setScm(sole);
    }).catch(() => {});
  }, [scm]);
  return [scm, setScm];
}
