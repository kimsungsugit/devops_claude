/**
 * SCM 연결 문서(linked_docs)의 **단일 진실원 접근** — 레지스트리 우선, 스냅샷 폴백.
 *
 * ## 왜 이 모듈이 있나
 *
 * `analysisResult.matchedScm.linked_docs` 는 **분석을 돌린 시점의 스냅샷**이다. 사용자가
 * 그 뒤에 설정/레지스트리에서 문서 경로를 바꿔도 이 값은 절대 갱신되지 않는다. 그래서
 * 스냅샷을 그대로 쓰는 화면은 "경로를 바꿨는데 안 바뀐다"가 된다 —
 * 실제 사용자 보고(2026-08-06): *"다른 데는 변경되는데 SUTS만 안 바뀐다."*
 *
 * `SrsSdsSection` 은 이 문제를 알고 `/api/scm/list` 재조회를 넣었지만(그 파일 주석:
 * *"옛 경로를 고집해 … 새로고침·분석 재실행으로도 안 고쳐졌다"*), 같은 스냅샷을 쓰는
 * **다른 소비자들은 안 고쳐졌다**:
 *   - `SrsSdsSection` 의 '입력 문서 현황' 패널 (스냅샷 직독)
 *   - `ProjectSummarySection` (자동 추적성 매트릭스 — 재조회 경로가 **아예 없다**)
 *
 * 복제된 구현을 각자 고치면 또 갈라지므로 여기 하나로 모은다.
 *
 * ## 계약
 *
 * - 반환값은 항상 객체(레지스트리 → 스냅샷 → `{}` 순).
 * - 레지스트리 `vectorcast` 가 비었는데 스냅샷에만 있으면 **그것만** 스냅샷에서 보강한다.
 *   분석 스냅샷이 vectorcast 등록 직후 캡처돼 레지스트리보다 나은 경우가 있어서다
 *   (P/F 공백의 직접 원인이었던 지점 — 원 동작 보존).
 * - 조회 실패는 조용히 스냅샷 폴백. 문서 경로는 화면의 **부가 정보**라, 못 가져왔다고
 *   빈 화면을 만드는 편이 더 나쁘다.
 *
 * ## 재조회 계약 (2026-08-06 2차 — 첫 판의 구멍)
 *
 * 첫 판은 `[scmId, enabled]` 만 deps 로 걸어 **마운트 시 1회**만 조회했다. Detail 섹션은
 * keep-alive(`display:none`)라 재마운트되지 않으므로, 설정에서 SCM 연결 문서 경로를 바꿔
 * 저장해도 **전체 새로고침 전까지** 이 값이 갱신되지 않는다 — 사용자 재보고:
 * *"요구사항 커버리지 입력 문서 현황에서 안 바뀌어 있어."*
 *
 * `saveDocPaths`(localStorage)는 `DOC_PATHS_EVENT` 로 이 문제를 이미 풀어 뒀는데,
 * **레지스트리 쪽에는 같은 통지가 없었다** — 또 한쪽만 고친 상태였다. 두 경로를 맞춘다:
 *   1. 앱 안에서의 저장 → `notifyScmRegistryChanged()` (설정의 SCM 등록/수정/삭제)
 *   2. 앱 **밖**에서의 변경(`config/scm_registry.json` 직접 편집 등) → `window` focus
 *
 * 값이 실제로 달라졌을 때만 setState 한다 — focus 는 alt-tab 마다 오므로, 매번 새 객체를
 * 넣으면 이 값을 dep 로 쓰는 `loadMatrix` 콜백이 alt-tab 마다 새로 만들어진다.
 */
import { useEffect, useState } from 'react';

import { api } from './api.js';

/** SCM 레지스트리가 바뀌었음을 같은 탭에 알리는 이벤트 (다른 탭은 focus 로 수렴). */
export const SCM_REGISTRY_EVENT = 'aria-scm-registry-changed';

/**
 * 레지스트리 변경 통지. **레지스트리를 쓰는 모든 입구는 여기를 거친다.**
 * 한 곳이라도 빠뜨리면 그 경로로 저장한 값만 화면에 안 나타난다 — 사용자에게는
 * "어떤 건 되고 어떤 건 안 된다"로 보이는, 원인을 짚기 가장 어려운 형태다.
 */
export function notifyScmRegistryChanged() {
  try { window.dispatchEvent(new Event(SCM_REGISTRY_EVENT)); } catch { /* no-window */ }
}

/**
 * @param {string} scmId    이 화면이 대상으로 삼은 SCM 항목 id ('' 면 조회하지 않는다)
 * @param {object} snapshot `analysisResult.matchedScm.linked_docs` (분석 시점 스냅샷)
 * @param {boolean} enabled false 면 조회를 건너뛰고 `{}` 를 유지한다(오귀속 게이트용)
 * @returns {[object, Function]} [linkedDocs, setLinkedDocs]
 */
export function useRegistryLinkedDocs(scmId, snapshot, enabled = true) {
  const [fetched, setFetched] = useState(() => snapshot || {});
  // 재조회 트리거. 이벤트/focus 가 올릴 때마다 아래 조회 effect 가 다시 돈다.
  const [reloadTick, setReloadTick] = useState(0);

  useEffect(() => {
    if (!enabled) return undefined;
    const bump = () => setReloadTick((t) => t + 1);
    window.addEventListener(SCM_REGISTRY_EVENT, bump);
    // 앱 밖에서 `config/scm_registry.json` 을 직접 고친 경우엔 이벤트가 없다. 창으로
    // 돌아오는 시점이 유일하게 잡을 수 있는 신호다(값이 같으면 아래에서 no-op).
    window.addEventListener('focus', bump);
    return () => {
      window.removeEventListener(SCM_REGISTRY_EVENT, bump);
      window.removeEventListener('focus', bump);
    };
  }, [enabled]);

  useEffect(() => {
    // 게이트가 닫혀 있으면 조회 자체를 하지 않는다. 값은 아래 반환부에서 파생하므로
    // 여기서 setState 를 부르지 않는다(effect 내 동기 setState = 연쇄 렌더).
    if (!enabled) return undefined;
    let cancelled = false;
    // 값이 **실제로 달라졌을 때만** 갱신 — focus 재조회가 alt-tab 마다 새 객체를 넣으면
    // 이 값을 dep 로 쓰는 소비자(loadMatrix useCallback 등)가 매번 새로 만들어진다.
    const apply = (next) => {
      if (cancelled) return;
      setFetched((prev) => (JSON.stringify(prev) === JSON.stringify(next) ? prev : next));
    };
    const fallback = () => { if (snapshot) apply(snapshot); };

    api('/api/scm/list').then((d) => {
      if (cancelled) return;
      const items = d?.items || (Array.isArray(d) ? d : []);
      // ⚠ id 로만 찾는다. items[0] 폴백은 다중 레지스트리에서 **다른 프로젝트 문서**를
      //   조용히 끌어오므로 쓰지 않는다(Dashboard·ImpactGuideSection 과 정책 통일).
      const matched = scmId ? items.find((it) => it.id === scmId) : null;
      if (!matched?.linked_docs) { fallback(); return; }

      const reg = matched.linked_docs;
      const regVcast = Array.isArray(reg.vectorcast) ? reg.vectorcast.filter(Boolean) : [];
      const snapVcast = Array.isArray(snapshot?.vectorcast) ? snapshot.vectorcast.filter(Boolean) : [];
      apply(
        regVcast.length === 0 && snapVcast.length > 0
          ? { ...reg, vectorcast: snapshot.vectorcast }
          : reg,
      );
    }).catch(fallback);

    return () => { cancelled = true; };
    // snapshot 은 매 렌더 새 객체일 수 있어 deps 에 넣으면 무한 루프가 된다 — scmId 로만 건다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scmId, enabled, reloadTick]);

  // 게이트가 닫히면 **빈 객체** — 다른 Job 의 문서로 매트릭스를 만드는 오귀속 차단.
  return [enabled ? fetched : EMPTY, setFetched];
}

const EMPTY = {};
