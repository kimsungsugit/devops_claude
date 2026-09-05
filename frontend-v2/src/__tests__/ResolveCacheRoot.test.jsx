/**
 * `resolveCacheRoot` — 캐시 루트 폴백 사슬의 **단일 출처**.
 *
 * ## 왜 별도 파일인가
 *
 * 이 함수를 쓰는 화면 테스트들은 `vi.mock('../api.js')` 로 api 모듈을 통째로 갈아끼운다.
 * 그래서 **진짜 구현은 어느 화면 테스트에서도 실행되지 않는다** — 폴백 단계를 하나
 * 지워도 전부 초록이었다(뮤테이션 M56 이 그렇게 살아남았다). 모듈을 모의하는 곳에서
 * 그 모듈 자신을 검증할 수는 없으므로, 여기서 **모의 없이** 직접 부른다.
 *
 * ## 무엇이 걸려 있나
 *
 * 빈 문자열을 서버로 보내면 백엔드가 `~/.devops_pro_cache` 로 떨어진다
 * (`backend/helpers/jenkins.py:_normalize_jenkins_cache_root`) — 화면이 실제로 쓰는
 * `.devops_pro_cache/<user>` 와 **다른 폴더**다. 그래서 한 화면만 폴백을 덜 타면 그
 * 화면만 조용히 딴 디렉터리를 본다: 준비 게이트가 UDS 빌드 캐시를 "없음(진행 불가)"
 * 으로 보고하는데 정작 생성은 성공하는, 게이트가 생성과 반대말을 하는 형태다.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ⚠ 모의하지 않는다 — 이 파일의 목적이 진짜 구현을 실행하는 것이다.
const { resolveCacheRoot, defaultCacheRoot } = await import('../api.js');

const JOB = { url: 'http://ci/job/X/' };
const CFG = { cacheRoot: '.settings-cache' };

describe('resolveCacheRoot', () => {
  beforeEach(() => { localStorage.clear(); vi.restoreAllMocks(); });

  it('분석 결과의 값이 가장 먼저다', () => {
    expect(resolveCacheRoot({ cacheRoot: 'X:/explicit' }, JOB, CFG)).toBe('X:/explicit');
  });

  it('분석 결과에 없으면 **job 기반 기본값**을 쓴다 (설정값으로 건너뛰지 않는다)', () => {
    // 이 단계가 사라지면 사용자별 격리 경로 대신 설정의 공용 경로가 나가고,
    // 게이트와 생성이 서로 다른 폴더를 볼 수 있다.
    const got = resolveCacheRoot({}, JOB, CFG);
    expect(got).toBe(defaultCacheRoot(JOB.url));
    expect(got).not.toBe(CFG.cacheRoot);
    expect(got).toMatch(/^\.devops_pro_cache\//);
  });

  it('job 이 없을 때만 설정값으로 내려간다', () => {
    expect(resolveCacheRoot(null, null, CFG)).toBe('.settings-cache');
  });

  it('전부 비면 빈 문자열 — 없는 경로를 지어내지 않는다', () => {
    expect(resolveCacheRoot(null, null, null)).toBe('');
  });

  it('분석 결과가 부분적으로만 채워져 있어도 빈 값을 내지 않는다', () => {
    // 실제로 생기는 형태 — 영향 탭이 `{...(prev || {}), impactData}` 로 만들면
    // `cacheRoot` 없이 객체가 생긴다. 게이트가 이 상태에서 `''` 를 보내고 있었다.
    expect(resolveCacheRoot({ impactData: {} }, JOB, CFG)).toBe(defaultCacheRoot(JOB.url));
  });
});
