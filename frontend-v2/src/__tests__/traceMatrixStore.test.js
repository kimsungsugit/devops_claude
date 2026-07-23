import { describe, it, expect, beforeEach } from 'vitest';
import {
  saveTraceMatrix, loadTraceMatrixByKey, loadTraceMatrixByBinding, clearTraceMatrix,
  TRACE_STORE_VERSION,
} from '../traceMatrixStore.js';

const KEY = 'devops_v2_trace_matrix_current';

// 실제 소비자(SrsSdsSection.buildCacheKey)와 같은 SHAPE — 요구/설계/시험 문서 경로 전체 +
// jobUrl + sourceRoot. 정확(clean) 복원은 이 전체가 일치할 때만.
const mkInputs = (over = {}) => ({
  srs: 'U:/srs.docx', sds: 'U:/sds.docx', hsis: 'U:/hsis.xlsx',
  jobUrl: 'http://j/job/KJPDS02_PV/', sourceRoot: 'D:/src',
  sts: 'U:/sts.xlsm', suts: 'U:/suts.xlsm', sits: '', syts: '', syits: '', vcast: '',
  ...over,
});
const mkKey = (over = {}) => JSON.stringify(mkInputs(over));
// binding = cacheKey의 안정 접두부(프로젝트 식별). SrsSdsSection.buildBinding와 같은 SHAPE.
// 시험문서(sts/suts/…)·vcast는 제외 → 그것들이 바뀌어도 binding은 그대로(=stale 복원 대상).
const mkBinding = (over = {}) => {
  const i = mkInputs(over);
  return JSON.stringify({ jobUrl: i.jobUrl, sourceRoot: i.sourceRoot, srs: i.srs, sds: i.sds, hsis: i.hsis });
};
const mkMatrix = (n = 1) => ({ rows: Array.from({ length: n }, (_, i) => ({ requirement_id: `SwEI_0${i + 1}` })), summary: { covered: n } });

describe('traceMatrixStore — 정확 키(clean) 저장/조회', () => {
  beforeEach(() => { clearTraceMatrix(); localStorage.clear(); });

  it('저장한 매트릭스를 정확 키로 그대로 복원한다', () => {
    const key = mkKey(); const data = mkMatrix(3);
    expect(saveTraceMatrix(key, mkBinding(), data)).toBe(true);
    const hit = loadTraceMatrixByKey(key);
    expect(hit).not.toBeNull();
    expect(hit.data).toEqual(data);
    expect(hit.savedAt).toBeTypeOf('number');
  });

  it('입력이 하나라도 다르면 정확 키는 miss — clean 복원은 완전일치만', () => {
    saveTraceMatrix(mkKey(), mkBinding(), mkMatrix());
    expect(loadTraceMatrixByKey(mkKey({ suts: 'U:/suts_v1.02.xlsm' }))).toBeNull();
    expect(loadTraceMatrixByKey(mkKey({ sourceRoot: 'D:/other' }))).toBeNull();
    expect(loadTraceMatrixByKey(mkKey({ jobUrl: 'http://j/job/OTHER/' }))).toBeNull();
    expect(loadTraceMatrixByKey(mkKey({ vcast: 'U:/app.html' }))).toBeNull();
  });

  it('렌더 불가 데이터(rows/items 없음)는 저장하지 않는다', () => {
    expect(saveTraceMatrix(mkKey(), mkBinding(), { summary: {} })).toBe(false);
    expect(saveTraceMatrix(mkKey(), mkBinding(), null)).toBe(false);
    expect(saveTraceMatrix('', mkBinding(), mkMatrix())).toBe(false);
  });

  it('data.matrix.rows 중첩 형태도 렌더 가능으로 인정한다(SrsSdsSection inner 접근 계약)', () => {
    const data = { matrix: { rows: [{ requirement_id: 'SwTR_0101' }] } };
    expect(saveTraceMatrix(mkKey(), mkBinding(), data)).toBe(true);
    expect(loadTraceMatrixByKey(mkKey()).data).toEqual(data);
  });
});

describe('traceMatrixStore — binding(stale) 복원: 같은 프로젝트 마지막 결과', () => {
  beforeEach(() => { clearTraceMatrix(); localStorage.clear(); });

  it('시험문서가 바뀌어 정확 키가 miss여도 같은 프로젝트면 마지막 매트릭스를 되살린다', () => {
    // 저장은 suts.xlsm(v0.10) 기준. 이후 SUTS가 v1.02로 교체되면 cacheKey는 달라진다.
    saveTraceMatrix(mkKey(), mkBinding(), mkMatrix(5));
    const drifted = mkKey({ suts: 'U:/suts_v1.02.xlsm' });     // 시험문서 드리프트
    expect(loadTraceMatrixByKey(drifted)).toBeNull();          // 정확 키는 miss(=current 아님)
    // binding(설계문서+job+source)은 그대로라 stale 복원 성공 → 사용자에게 마지막 결과가 보인다.
    const stale = loadTraceMatrixByBinding(mkBinding({ suts: 'U:/suts_v1.02.xlsm' }));
    expect(stale).not.toBeNull();
    expect(stale.data.rows).toHaveLength(5);
    expect(stale.cacheKey).toBe(mkKey());   // 되살린 원본 키를 실어 호출측이 clean/stale 재판정 가능
  });

  it('VectorCAST 빌드(vcast 경로) 드리프트도 binding 복원으로 마지막 결과가 보인다', () => {
    saveTraceMatrix(mkKey({ vcast: 'U:/b101/app.html' }), mkBinding(), mkMatrix(2));
    // 빌드가 넘어가 vcast 경로가 바뀜 → 정확 키 miss, binding 동일.
    expect(loadTraceMatrixByKey(mkKey({ vcast: 'U:/b102/app.html' }))).toBeNull();
    expect(loadTraceMatrixByBinding(mkBinding())).not.toBeNull();
  });

  it('다른 프로젝트(jobUrl/sourceRoot 상이)로는 절대 새지 않는다', () => {
    saveTraceMatrix(mkKey(), mkBinding(), mkMatrix());
    expect(loadTraceMatrixByBinding(mkBinding({ jobUrl: 'http://j/job/OTHER/' }))).toBeNull();
    expect(loadTraceMatrixByBinding(mkBinding({ sourceRoot: 'D:/other' }))).toBeNull();
    // 설계문서가 바뀌어도(다른 요구 베이스) binding 불일치 → 복원 안 함.
    expect(loadTraceMatrixByBinding(mkBinding({ srs: 'U:/srs_v2.docx' }))).toBeNull();
  });

  it('같은 binding에 저장이 여러 번이면 가장 최근 것을 되살린다', () => {
    saveTraceMatrix(mkKey({ suts: 'U:/suts_a.xlsm' }), mkBinding(), mkMatrix(1));  // 먼저
    saveTraceMatrix(mkKey({ suts: 'U:/suts_b.xlsm' }), mkBinding(), mkMatrix(9));  // 나중
    const stale = loadTraceMatrixByBinding(mkBinding({ suts: 'U:/suts_c.xlsm' }));
    expect(stale.data.rows).toHaveLength(9);                  // 최근(b) 것
    expect(stale.cacheKey).toBe(mkKey({ suts: 'U:/suts_b.xlsm' }));
  });

  it('binding이 빈 문자열이면(구 저장분·binding 없음) 절대 매칭하지 않는다', () => {
    saveTraceMatrix(mkKey(), '', mkMatrix());     // binding 없이 저장(구 스키마 시뮬레이션)
    expect(loadTraceMatrixByBinding(mkBinding())).toBeNull();
    expect(loadTraceMatrixByBinding('')).toBeNull();          // 빈 binding 조회도 null(전수 매칭 금지)
    // 단, 정확 키로는 여전히 복원 가능(하위호환).
    expect(loadTraceMatrixByKey(mkKey())).not.toBeNull();
  });

  it('모듈캐시가 비어도(새로고침) localStorage에서 binding 복원', () => {
    localStorage.setItem(KEY, JSON.stringify({
      v: TRACE_STORE_VERSION, key: mkKey(), bindingKey: mkBinding(), data: mkMatrix(4), savedAt: 222,
    }));
    const stale = loadTraceMatrixByBinding(mkBinding({ suts: 'U:/suts_v1.02.xlsm' }));
    expect(stale.data.rows).toHaveLength(4);
    expect(stale.savedAt).toBe(222);
  });
});

describe('traceMatrixStore — localStorage 미러(새로고침 생존)', () => {
  beforeEach(() => { clearTraceMatrix(); localStorage.clear(); });

  it('저장 시 localStorage에 key와 bindingKey가 함께 미러링된다', () => {
    saveTraceMatrix(mkKey(), mkBinding(), mkMatrix());
    const raw = JSON.parse(localStorage.getItem(KEY));
    expect(raw.v).toBe(TRACE_STORE_VERSION);
    expect(raw.key).toBe(mkKey());
    expect(raw.bindingKey).toBe(mkBinding());
    expect(Array.isArray(raw.data.rows)).toBe(true);
  });

  it('모듈캐시가 비어도(새로고침 시뮬레이션) localStorage에서 정확 키 복원', () => {
    const key = mkKey();
    localStorage.setItem(KEY, JSON.stringify({ v: TRACE_STORE_VERSION, key, bindingKey: mkBinding(), data: mkMatrix(2), savedAt: 111 }));
    const hit = loadTraceMatrixByKey(key);
    expect(hit.data.rows).toHaveLength(2);
    expect(hit.savedAt).toBe(111);
  });

  it('버전이 없거나 다른 저장분은 폐기한다(구 스키마 크래시 방지)', () => {
    const key = mkKey();
    localStorage.setItem(KEY, JSON.stringify({ v: TRACE_STORE_VERSION - 1, key, data: mkMatrix(), savedAt: 1 }));
    expect(loadTraceMatrixByKey(key)).toBeNull();
    localStorage.setItem(KEY, JSON.stringify({ key, data: mkMatrix(), savedAt: 1 }));  // v 없음
    expect(loadTraceMatrixByKey(key)).toBeNull();
  });

  it('깨진 JSON / 렌더불가 저장분은 null', () => {
    localStorage.setItem(KEY, '{not json');
    expect(loadTraceMatrixByKey(mkKey())).toBeNull();
    localStorage.setItem(KEY, JSON.stringify({ v: TRACE_STORE_VERSION, key: mkKey(), data: { summary: {} }, savedAt: 1 }));
    expect(loadTraceMatrixByKey(mkKey())).toBeNull();  // rows/items 없음
  });
});

describe('traceMatrixStore — 크기가드·오버사이즈', () => {
  beforeEach(() => { clearTraceMatrix(); localStorage.clear(); });

  it('과대 매트릭스는 localStorage skip, 모듈캐시는 유지(안전 degrade)', () => {
    const key = mkKey();
    const huge = mkMatrix(80000);  // 직렬화 > 2MB
    expect(JSON.stringify(huge).length).toBeGreaterThan(2_000_000);
    expect(saveTraceMatrix(key, mkBinding(), huge)).toBe(true);   // 모듈캐시엔 저장
    expect(localStorage.getItem(KEY)).toBeNull();     // localStorage는 skip
    expect(loadTraceMatrixByKey(key).data.rows).toHaveLength(80000);  // 세션 내 복원 가능
    // 세션 내에서는 binding 복원도 여전히 동작(모듈캐시 기반).
    expect(loadTraceMatrixByBinding(mkBinding({ suts: 'x' })).data.rows).toHaveLength(80000);
  });

  it('오버사이즈 저장이 타 프로젝트의 localStorage 미러를 축출하지 않는다(deep-review Warning)', () => {
    const keyA = mkKey({ jobUrl: 'http://j/job/A/' });
    saveTraceMatrix(keyA, mkBinding({ jobUrl: 'http://j/job/A/' }), mkMatrix(2));   // 작은 A → localStorage = A
    expect(JSON.parse(localStorage.getItem(KEY)).key).toBe(keyA);
    const keyB = mkKey({ jobUrl: 'http://j/job/B/' });
    saveTraceMatrix(keyB, mkBinding({ jobUrl: 'http://j/job/B/' }), mkMatrix(80000));  // 오버사이즈 B(저장 불가)
    const raw = JSON.parse(localStorage.getItem(KEY));
    expect(raw).not.toBeNull();
    expect(raw.key).toBe(keyA);
  });

  it('자기 자신이 오버사이즈로 커지면 옛 미러(같은 키)는 정리한다(stale 방지)', () => {
    const key = mkKey();
    saveTraceMatrix(key, mkBinding(), mkMatrix(2));                        // 작을 때 저장 → 미러 존재
    expect(localStorage.getItem(KEY)).not.toBeNull();
    saveTraceMatrix(key, mkBinding(), mkMatrix(80000));                    // 같은 키가 오버사이즈로
    expect(localStorage.getItem(KEY)).toBeNull();             // 자기 옛 미러는 제거
  });
});

describe('traceMatrixStore — clear', () => {
  beforeEach(() => { clearTraceMatrix(); localStorage.clear(); });

  it('clearTraceMatrix가 모듈캐시와 localStorage를 모두 비운다', () => {
    saveTraceMatrix(mkKey(), mkBinding(), mkMatrix());
    expect(localStorage.getItem(KEY)).not.toBeNull();
    clearTraceMatrix();
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(loadTraceMatrixByKey(mkKey())).toBeNull();
    expect(loadTraceMatrixByBinding(mkBinding())).toBeNull();
  });
});
