import { describe, it, expect, beforeEach } from 'vitest';
import {
  saveTraceMatrix, loadTraceMatrixByKey, clearTraceMatrix,
  TRACE_STORE_VERSION,
} from '../traceMatrixStore.js';

const KEY = 'devops_v2_trace_matrix_current';

// 실제 소비자(SrsSdsSection.buildCacheKey)와 같은 SHAPE — 요구/설계/시험 문서 경로 전체 +
// jobUrl + sourceRoot. 복원은 이 전체가 정확히 일치할 때만(시험문서 하나만 바뀌어도 miss).
const mkInputs = (over = {}) => ({
  srs: 'U:/srs.docx', sds: 'U:/sds.docx', hsis: 'U:/hsis.xlsx',
  jobUrl: 'http://j/job/KJPDS02_PV/', sourceRoot: 'D:/src',
  sts: 'U:/sts.xlsm', suts: 'U:/suts.xlsm', sits: '', syts: '', syits: '', vcast: '',
  ...over,
});
const mkKey = (over = {}) => JSON.stringify(mkInputs(over));
const mkMatrix = (n = 1) => ({ rows: Array.from({ length: n }, (_, i) => ({ requirement_id: `SwEI_0${i + 1}` })), summary: { covered: n } });

describe('traceMatrixStore — 저장/조회 (모듈캐시, 정확 키)', () => {
  beforeEach(() => { clearTraceMatrix(); localStorage.clear(); });

  it('저장한 매트릭스를 정확 키로 그대로 복원한다', () => {
    const key = mkKey(); const data = mkMatrix(3);
    expect(saveTraceMatrix(key, data)).toBe(true);
    const hit = loadTraceMatrixByKey(key);
    expect(hit).not.toBeNull();
    expect(hit.data).toEqual(data);
    expect(hit.savedAt).toBeTypeOf('number');
  });

  it('입력이 하나라도 다르면 miss — 정확 키 일치만 복원(stale 표시 차단)', () => {
    saveTraceMatrix(mkKey(), mkMatrix());
    // 시험문서(suts) 경로만 바뀌어도 복원 안 함 → 옛 통과-실패를 current로 표시하지 않음
    // (deep-review Critical: 느슨한 binding이 시험문서 변경을 우회하던 것 차단).
    expect(loadTraceMatrixByKey(mkKey({ suts: 'U:/suts_v1.02.xlsm' }))).toBeNull();
    expect(loadTraceMatrixByKey(mkKey({ sourceRoot: 'D:/other' }))).toBeNull();
    expect(loadTraceMatrixByKey(mkKey({ jobUrl: 'http://j/job/OTHER/' }))).toBeNull();
    expect(loadTraceMatrixByKey(mkKey({ vcast: 'U:/app.html' }))).toBeNull();
  });

  it('렌더 불가 데이터(rows/items 없음)는 저장하지 않는다', () => {
    expect(saveTraceMatrix(mkKey(), { summary: {} })).toBe(false);
    expect(saveTraceMatrix(mkKey(), null)).toBe(false);
    expect(saveTraceMatrix('', mkMatrix())).toBe(false);
  });

  it('data.matrix.rows 중첩 형태도 렌더 가능으로 인정한다(SrsSdsSection inner 접근 계약)', () => {
    const data = { matrix: { rows: [{ requirement_id: 'SwTR_0101' }] } };
    expect(saveTraceMatrix(mkKey(), data)).toBe(true);
    expect(loadTraceMatrixByKey(mkKey()).data).toEqual(data);
  });
});

describe('traceMatrixStore — localStorage 미러(새로고침 생존)', () => {
  beforeEach(() => { clearTraceMatrix(); localStorage.clear(); });

  it('저장 시 localStorage에도 미러링된다', () => {
    saveTraceMatrix(mkKey(), mkMatrix());
    const raw = JSON.parse(localStorage.getItem(KEY));
    expect(raw.v).toBe(TRACE_STORE_VERSION);
    expect(raw.key).toBe(mkKey());
    expect(Array.isArray(raw.data.rows)).toBe(true);
  });

  it('모듈캐시가 비어도(새로고침 시뮬레이션) localStorage에서 정확 키 복원', () => {
    const key = mkKey();
    localStorage.setItem(KEY, JSON.stringify({ v: TRACE_STORE_VERSION, key, data: mkMatrix(2), savedAt: 111 }));
    const hit = loadTraceMatrixByKey(key);
    expect(hit.data.rows).toHaveLength(2);
    expect(hit.savedAt).toBe(111);
  });

  it('버전이 없거나 다른 저장분은 폐기한다(구 스키마·구 binding 엔트리 크래시 방지)', () => {
    const key = mkKey();
    // v1(구 binding 기반)·미상 버전 모두 폐기 — 버전 bump로 자연 무효화.
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
    expect(saveTraceMatrix(key, huge)).toBe(true);   // 모듈캐시엔 저장
    expect(localStorage.getItem(KEY)).toBeNull();     // localStorage는 skip
    expect(loadTraceMatrixByKey(key).data.rows).toHaveLength(80000);  // 세션 내 복원 가능
  });

  it('오버사이즈 저장이 타 프로젝트의 localStorage 미러를 축출하지 않는다(deep-review Warning)', () => {
    const keyA = mkKey({ jobUrl: 'http://j/job/A/' });
    saveTraceMatrix(keyA, mkMatrix(2));                       // 작은 A → localStorage = A
    expect(JSON.parse(localStorage.getItem(KEY)).key).toBe(keyA);
    const keyB = mkKey({ jobUrl: 'http://j/job/B/' });
    saveTraceMatrix(keyB, mkMatrix(80000));                   // 오버사이즈 B(저장 불가)
    // B는 저장 못하지만 A의 미러를 지우지 않는다 — A는 새로고침 후에도 복원 가능해야.
    const raw = JSON.parse(localStorage.getItem(KEY));
    expect(raw).not.toBeNull();
    expect(raw.key).toBe(keyA);
  });

  it('자기 자신이 오버사이즈로 커지면 옛 미러(같은 키)는 정리한다(stale 방지)', () => {
    const key = mkKey();
    saveTraceMatrix(key, mkMatrix(2));                        // 작을 때 저장 → 미러 존재
    expect(localStorage.getItem(KEY)).not.toBeNull();
    saveTraceMatrix(key, mkMatrix(80000));                    // 같은 키가 오버사이즈로
    expect(localStorage.getItem(KEY)).toBeNull();             // 자기 옛 미러는 제거
  });
});

describe('traceMatrixStore — clear', () => {
  beforeEach(() => { clearTraceMatrix(); localStorage.clear(); });

  it('clearTraceMatrix가 모듈캐시와 localStorage를 모두 비운다', () => {
    saveTraceMatrix(mkKey(), mkMatrix());
    expect(localStorage.getItem(KEY)).not.toBeNull();
    clearTraceMatrix();
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(loadTraceMatrixByKey(mkKey())).toBeNull();
  });
});
