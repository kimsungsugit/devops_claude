import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  impactIdentity, identityKey, impactKeyOf, sameImpactTarget, sameJobUrl,
  saveImpactCurrent, loadImpactCurrent, clearImpactCurrent, STORE_VERSION,
} from '../impactStore.js';

const KEY = 'devops_v2_impact_current';

const mkImpact = ({ scm = 'hdpdm01', build = 412, rev = '1042', base = '527', jobId = '' } = {}) => ({
  _job_id: jobId,
  trigger: {
    scm_id: scm,
    metadata: {
      build_number: build, build_revision: rev, baseline_revision: base,
      changed_files_source: 'svn_revision_range',
    },
  },
});

/** 실제 buildGuide 산출물과 같은 형태 — details 배열 + summary 객체.
 *  렌더가 guide.summary.impactedReqs / guide.details.length를 무가드로 읽으므로 이 둘이 계약이다. */
const mkGuide = (fn = 'g_MotorCtrl') => ({
  details: [{ function: fn, changeType: 'BODY' }],
  fetchFailures: [],
  summary: {
    impactedReqs: 0, impactedStsTCs: 0, impactedSitsTCs: 0,
    stsTcReason: '', sitsTcReason: '',
  },
});

/** quota를 흉내내는 localStorage 스텁을 전역에 끼운다.
 *
 * happy-dom의 localStorage는 프로토타입 메서드 spy가 먹지 않아(내부 Proxy) 전역 자체를
 * 갈아끼운다. impactStore는 호출 시점에 전역 식별자로 해석하므로 그대로 적용된다.
 * setItem은 앞의 failFirstN회까지 throw하고 그 뒤부터 정상 저장한다.
 * @returns {Map} 스텁의 내부 저장소(직접 seed/검증용)
 */
function stubQuotaStorage(failFirstN) {
  const data = new Map();
  let calls = 0;
  vi.stubGlobal('localStorage', {
    setItem(k, v) {
      calls += 1;
      if (calls <= failFirstN) throw new Error('QuotaExceededError');
      data.set(k, String(v));
    },
    getItem(k) { return data.has(k) ? data.get(k) : null; },
    removeItem(k) { data.delete(k); },
    clear() { data.clear(); },
  });
  return data;
}

describe('impactStore — 결과 식별자', () => {
  it('trigger.metadata에서 SCM/빌드/리비전/변경출처를 뽑는다', () => {
    expect(impactIdentity(mkImpact())).toMatchObject({
      scm_id: 'hdpdm01', build_number: 412, build_revision: '1042',
      baseline_revision: '527', changed_files_source: 'svn_revision_range',
    });
  });

  it('명시 jobId가 impactData._job_id보다 우선한다', () => {
    expect(impactIdentity(mkImpact({ jobId: 'old' }), 'new').job_id).toBe('new');
    expect(impactIdentity(mkImpact({ jobId: 'old' })).job_id).toBe('old');
  });

  it('메타가 비어도 안전한 기본값으로 정규화된다', () => {
    const id = impactIdentity({ trigger: { scm_id: 'x' } });
    expect(id.build_number).toBe(0);
    expect(id.build_revision).toBe('');
    expect(id.job_url).toBe('');
    expect(impactIdentity(null).scm_id).toBe('');
  });

  it('job_url을 식별자에 싣는다 — 저장분이 어느 프로젝트 것인지 대조하는 근거', () => {
    const impactData = mkImpact();
    impactData.trigger.metadata.job_url = 'http://j/job/PDS/';
    expect(impactIdentity(impactData).job_url).toBe('http://j/job/PDS/');
  });
});

describe('impactStore — 대상 키 / Job URL 비교', () => {
  it('identityKey는 대상이 다르면 다른 키를 준다', () => {
    const a = identityKey(impactIdentity(mkImpact({ build: 410 })));
    const b = identityKey(impactIdentity(mkImpact({ build: 412 })));
    expect(a).not.toBe(b);
    expect(identityKey(impactIdentity(mkImpact({ build: 410 })))).toBe(a);  // 결정적
    expect(identityKey(null)).toBe('');
  });

  it('impactKeyOf는 impactData가 없으면 빈 키 — 데모 모드(결과 없음)와 실제 결과를 구분한다', () => {
    expect(impactKeyOf(null)).toBe('');
    expect(impactKeyOf(undefined)).toBe('');
    expect(impactKeyOf(mkImpact())).not.toBe('');
  });

  it('sameJobUrl은 후행 슬래시 차이를 흡수하고 빈 값은 불일치로 본다', () => {
    expect(sameJobUrl('http://j/job/A/', 'http://j/job/A')).toBe(true);
    expect(sameJobUrl('http://j/job/A', 'http://j/job/B')).toBe(false);
    expect(sameJobUrl('', 'http://j/job/A')).toBe(false);
    expect(sameJobUrl('', '')).toBe(false);
  });
});

describe('impactStore — sameImpactTarget (상세 가이드 하이드레이트 안전 게이트)', () => {
  // 이 게이트가 느슨해지면 빌드 A의 가이드(ASIL/커버리지 판정 포함)가 빌드 B 데이터 위에 얹힌다.
  it('같은 job_id면 같은 대상 — 실행 단위로 확정', () => {
    expect(sameImpactTarget({ job_id: 'j1', scm_id: 'a' }, { job_id: 'j1', scm_id: 'b' })).toBe(true);
  });

  it('job_id가 다르면 SCM·빌드가 같아도 다른 대상', () => {
    expect(sameImpactTarget(
      { job_id: 'j1', scm_id: 'a', build_number: 412 },
      { job_id: 'j2', scm_id: 'a', build_number: 412 },
    )).toBe(false);
  });

  it('job_id가 없으면 SCM+빌드번호로 판단', () => {
    expect(sameImpactTarget({ scm_id: 'a', build_number: 412 }, { scm_id: 'a', build_number: 412 })).toBe(true);
    expect(sameImpactTarget({ scm_id: 'a', build_number: 412 }, { scm_id: 'a', build_number: 413 })).toBe(false);
  });

  it('SCM이 다르면 항상 다른 대상', () => {
    expect(sameImpactTarget({ scm_id: 'a', build_number: 412 }, { scm_id: 'b', build_number: 412 })).toBe(false);
  });

  it('빌드번호가 없으면 빌드 리비전으로 판단', () => {
    expect(sameImpactTarget({ scm_id: 'a', build_revision: '1042' }, { scm_id: 'a', build_revision: '1042' })).toBe(true);
    expect(sameImpactTarget({ scm_id: 'a', build_revision: '1042' }, { scm_id: 'a', build_revision: '1030' })).toBe(false);
  });

  it('식별 근거가 하나도 없으면 false — 모르는 것을 같다고 단정하지 않는다', () => {
    expect(sameImpactTarget({ scm_id: 'a' }, { scm_id: 'a' })).toBe(false);
    expect(sameImpactTarget({}, {})).toBe(false);
    expect(sameImpactTarget(null, { scm_id: 'a', build_number: 1 })).toBe(false);
  });
});

describe('impactStore — 영속 저장/복원', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it('저장한 결과와 상세 가이드를 그대로 복원한다', () => {
    const impactData = mkImpact();
    const ok = saveImpactCurrent({
      id: impactIdentity(impactData), jobId: 'j1', impactData,
      guide: mkGuide(), aiGuide: { ai_enriched: true },
    });

    expect(ok).toBe(true);
    const loaded = loadImpactCurrent();
    expect(loaded.impactData.trigger.scm_id).toBe('hdpdm01');
    expect(loaded.guide).toEqual(mkGuide());
    expect(loaded.aiGuide).toEqual({ ai_enriched: true });
    expect(loaded.jobId).toBe('j1');
    expect(loaded.savedAt).toBeTypeOf('number');
  });

  it('impactData도 jobId도 없으면 저장하지 않는다', () => {
    expect(saveImpactCurrent({ id: {} })).toBe(false);
    expect(saveImpactCurrent(null)).toBe(false);
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it('quota 초과 시 jobId가 있으면 본문을 먼저 버리고 비싼 가이드를 지킨다', () => {
    // 본문(impactData)은 job_id로 서버에서 되받을 수 있지만, 가이드는 문서 추출 5회 + AI 호출을
    // 다시 치러야 한다 → 덜어내는 순서가 뒤집히면 사용자가 비싼 재생성을 강요당한다.
    stubQuotaStorage(1);

    const impactData = mkImpact();
    const ok = saveImpactCurrent({
      id: impactIdentity(impactData), jobId: 'j1', impactData,
      guide: mkGuide('fn_a'), aiGuide: null,
    });
    expect(ok).toBe(true);

    const loaded = loadImpactCurrent();
    expect(loaded.impactData).toBeUndefined();      // 버려짐 — jobId로 재조회 가능
    expect(loaded.guide).toEqual(mkGuide('fn_a')); // 살아남음
    expect(loaded.jobId).toBe('j1');
  });

  it('끝까지 실패하면 stale 엔트리를 남기지 않고 false를 준다', () => {
    // 반쯤 남은 이전 엔트리를 그대로 두면 다음 하이드레이트가 그걸 최신으로 오인한다.
    const data = stubQuotaStorage(Number.POSITIVE_INFINITY);
    data.set(KEY, JSON.stringify({ jobId: 'stale-old' }));

    const impactData = mkImpact();
    const ok = saveImpactCurrent({ id: impactIdentity(impactData), jobId: 'j1', impactData });

    expect(ok).toBe(false);
    expect(data.has(KEY)).toBe(false);  // removeItem으로 정리됨
  });

  it('깨진 JSON / 빈 엔트리는 null로 처리한다', () => {
    localStorage.setItem(KEY, '{not json');
    expect(loadImpactCurrent()).toBeNull();

    localStorage.setItem(KEY, JSON.stringify({ id: {}, savedAt: 1 }));
    expect(loadImpactCurrent()).toBeNull();  // impactData도 jobId도 없으면 쓸모없음
  });

  it('버전이 없거나 다른 저장분은 폐기한다 — 구 스키마 1건이 탭을 매번 크래시시키는 것 방지', () => {
    const impactData = mkImpact();
    saveImpactCurrent({ id: impactIdentity(impactData), jobId: 'j1', impactData, guide: mkGuide() });
    expect(loadImpactCurrent()).not.toBeNull();

    const raw = JSON.parse(localStorage.getItem(KEY));
    localStorage.setItem(KEY, JSON.stringify({ ...raw, v: STORE_VERSION + 1 }));
    expect(loadImpactCurrent()).toBeNull();

    delete raw.v;  // 버전 도입 이전 엔트리
    localStorage.setItem(KEY, JSON.stringify(raw));
    expect(loadImpactCurrent()).toBeNull();
  });

  it('가이드만 깨져 있으면 가이드만 떨구고 결과는 살린다', () => {
    // guide.summary가 없으면 렌더가 TypeError로 죽는다 — 결과까지 버릴 이유는 없으니 분리 처리.
    const impactData = mkImpact();
    saveImpactCurrent({
      id: impactIdentity(impactData), jobId: 'j1', impactData,
      guide: { details: [] },  // summary 없음 = 렌더 불가
    });

    const loaded = loadImpactCurrent();
    expect(loaded).not.toBeNull();
    expect(loaded.impactData.trigger.scm_id).toBe('hdpdm01');
    expect(loaded.guide).toBeNull();
  });

  it('clearImpactCurrent가 키를 지운다', () => {
    saveImpactCurrent({ id: {}, jobId: 'j1' });
    expect(localStorage.getItem(KEY)).not.toBeNull();
    clearImpactCurrent();
    expect(localStorage.getItem(KEY)).toBeNull();
  });
});
