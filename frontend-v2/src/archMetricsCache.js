import { post } from './api.js';

/**
 * `/api/summary/architecture-metrics` **요청 공유(dedup)** — 장기 캐시가 아니다.
 *
 * 왜 필요한가: `ArchitectureMetricsPanel` 과 `ArchitectureGraphPanel` 이 **글자 그대로 같은 body**로
 * 각자 POST 하고 있었다. 서버는 빌드별 락으로 계산 자체는 1회만 하지만, 요청·직렬화·전송은
 * 두 번 나가고 응답(수 MB 급 스냅샷 메트릭)도 두 벌이 메모리에 남았다. 두 패널은 같은 서브탭에
 * 있어 거의 동시에 마운트하므로, in-flight promise 하나를 공유하면 그대로 해결된다.
 *
 * ⚠ **결과를 오래 들고 있으면 안 된다.** 이 Map 은 모듈 레벨이라 컴포넌트 생명주기를 넘어 산다.
 *   `Detail.jsx` 는 `key={jobKey::sectionId}` 로 job 전환 시 섹션을 통째로 **재마운트**하므로,
 *   Job A → B → A 왕복 사이에 백필로 새 스냅샷이 생겨도 두 패널만 옛 빌드를 계속 보여주고
 *   `arch-improvement`(이 캐시를 안 쓴다)는 새 빌드를 보여줘 **한 탭 안에서 기준 빌드가 갈라진다**.
 *   그래서 응답이 도착한 뒤에는 `SETTLED_TTL_MS` 만 유효하다 — 동시 마운트를 덮을 만큼만 짧다.
 *   ⚠ in-flight 는 TTL 대상이 아니다(콜드 파싱이 30초 넘게 걸린다 — TTL 로 끊으면 dedup 이 깨진다).
 *
 * ⚠ 실패는 캐시하지 않는다 — 실패를 캐시하면 재시도가 영구히 같은 오류를 되받는다.
 */

const MAX_ENTRIES = 4;
/** 응답 도착 후 유효 기간. 두 패널의 동시 마운트만 덮으면 되므로 짧게. */
const SETTLED_TTL_MS = 60_000;
const cache = new Map();   // key -> { promise, settledAt: number|null }

function keyOf(jobUrl, cacheRoot) {
  // ⚠ 구분자에 공백을 쓰지 않는다 — cacheRoot 는 Windows 경로라 공백을 포함할 수 있고
  //   (예: `… - 복사본/…`) 그러면 서로 다른 (job, root) 쌍이 같은 키로 뭉개진다.
  return JSON.stringify([jobUrl || '', cacheRoot || '']);
}

export function fetchArchMetrics(jobUrl, cacheRoot) {
  const key = keyOf(jobUrl, cacheRoot);
  const hit = cache.get(key);
  if (hit && (hit.settledAt == null || Date.now() - hit.settledAt < SETTLED_TTL_MS)) {
    return hit.promise;
  }

  const entry = { promise: null, settledAt: null };
  entry.promise = post('/api/summary/architecture-metrics', { job_url: jobUrl, cache_root: cacheRoot });
  // ⚠ 삭제 전 신원 확인 — LRU 축출 후 같은 키로 새 요청이 들어왔는데 옛 요청이 늦게 실패하면
  //   건강한 새 엔트리를 지운다(dedup 손실).
  entry.promise.then(
    () => { entry.settledAt = Date.now(); },
    () => { if (cache.get(key) === entry) cache.delete(key); },
  );
  cache.set(key, entry);
  // 삽입 순서 기준으로 오래된 항목부터 버린다(Map은 삽입 순서를 보존한다).
  while (cache.size > MAX_ENTRIES) cache.delete(cache.keys().next().value);
  return entry.promise;
}

/** 강제 재조회 — 소스 스냅샷이 바뀌는 작업(백필) 직후, 그리고 테스트 격리용. 인자 없으면 전체 비움. */
export function clearArchMetricsCache(jobUrl, cacheRoot) {
  if (jobUrl === undefined) cache.clear();
  else cache.delete(keyOf(jobUrl, cacheRoot));
}
