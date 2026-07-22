import { describe, it, expect, beforeEach } from 'vitest';
import {
  saveTraceMatrix, loadTraceMatrixByKey, hydrateTraceMatrix, clearTraceMatrix,
  TRACE_STORE_VERSION,
} from '../traceMatrixStore.js';

const KEY = 'devops_v2_trace_matrix_current';

const mkBinding = (over = {}) => ({
  srs: 'U:/srs.docx', sds: 'U:/sds.docx', hsis: 'U:/hsis.xlsx',
  jobUrl: 'http://j/job/KJPDS02_PV/', sourceRoot: 'D:/src', ...over,
});
// 렌더 가능한 매트릭스 형태 — SrsSdsSection 렌더가 `inner.rows`/`inner.items`를 읽으므로 그게 계약.
const mkMatrix = (n = 1) => ({ rows: Array.from({ length: n }, (_, i) => ({ requirement_id: `SwEI_0${i + 1}` })), summary: { covered: n } });
const mkFullKey = (b) => JSON.stringify({ ...b, sts: 'U:/sts.xlsm', suts: 'U:/suts.xlsm' });

describe('traceMatrixStore — 저장/조회 (모듈캐시)', () => {
  beforeEach(() => { clearTraceMatrix(); localStorage.clear(); });

  it('저장한 매트릭스를 full cacheKey로 그대로 복원한다', () => {
    const b = mkBinding(); const key = mkFullKey(b); const data = mkMatrix(3);
    expect(saveTraceMatrix(key, b, data)).toBe(true);
    const hit = loadTraceMatrixByKey(key);
    expect(hit).not.toBeNull();
    expect(hit.data).toEqual(data);
    expect(hit.savedAt).toBeTypeOf('number');
  });

  it('cacheKey가 다르면 히트 없음 — 입력이 바뀌면 재생성(캐시 미스)', () => {
    const b = mkBinding(); saveTraceMatrix(mkFullKey(b), b, mkMatrix());
    expect(loadTraceMatrixByKey(mkFullKey(mkBinding({ sourceRoot: 'D:/other' })))).toBeNull();
  });

  it('렌더 불가 데이터(rows/items 없음)는 저장하지 않는다', () => {
    const b = mkBinding();
    expect(saveTraceMatrix(mkFullKey(b), b, { summary: {} })).toBe(false);
    expect(saveTraceMatrix(mkFullKey(b), b, null)).toBe(false);
    expect(saveTraceMatrix('', b, mkMatrix())).toBe(false);
  });

  it('data.matrix.rows 중첩 형태도 렌더 가능으로 인정한다(SrsSdsSection inner 접근 계약)', () => {
    const b = mkBinding(); const data = { matrix: { rows: [{ requirement_id: 'SwTR_0101' }] } };
    expect(saveTraceMatrix(mkFullKey(b), b, data)).toBe(true);
    expect(loadTraceMatrixByKey(mkFullKey(b)).data).toEqual(data);
  });
});

describe('traceMatrixStore — 마운트 하이드레이트(binding 결속)', () => {
  beforeEach(() => { clearTraceMatrix(); localStorage.clear(); });

  it('binding만 맞으면 exact key 없이도 복원한다(프로젝트 왕복 재진입)', () => {
    const b = mkBinding(); saveTraceMatrix(mkFullKey(b), b, mkMatrix(5));
    const hit = hydrateTraceMatrix(mkBinding());  // 같은 프로젝트 결속
    expect(hit).not.toBeNull();
    expect(hit.data.rows).toHaveLength(5);
  });

  it('다른 프로젝트(jobUrl/sourceRoot 상이)면 복원 안 함 — 타 프로젝트 결과 오적용 방지', () => {
    const b = mkBinding(); saveTraceMatrix(mkFullKey(b), b, mkMatrix());
    expect(hydrateTraceMatrix(mkBinding({ jobUrl: 'http://j/job/OTHER/' }))).toBeNull();
    expect(hydrateTraceMatrix(mkBinding({ sourceRoot: 'D:/stale_tree' }))).toBeNull();
  });

  it('같은 binding 후보가 여러 개면 가장 최신(savedAt)을 고른다', () => {
    const b = mkBinding();
    saveTraceMatrix(mkFullKey(b), b, mkMatrix(1));                       // sts/suts 조합 A
    const keyB = JSON.stringify({ ...b, sts: 'U:/sts.xlsm', suts: 'U:/suts_v2.xlsm' });
    saveTraceMatrix(keyB, b, mkMatrix(9));                               // 더 나중 저장(같은 binding)
    expect(hydrateTraceMatrix(mkBinding()).data.rows).toHaveLength(9);   // 최신
  });

  it('빈 binding은 복원하지 않는다', () => {
    expect(hydrateTraceMatrix({})).toBeNull();
    expect(hydrateTraceMatrix(null)).toBeNull();
  });
});

describe('traceMatrixStore — localStorage 미러(새로고침 생존)', () => {
  beforeEach(() => { clearTraceMatrix(); localStorage.clear(); });

  it('저장 시 localStorage에도 미러링된다', () => {
    const b = mkBinding(); saveTraceMatrix(mkFullKey(b), b, mkMatrix());
    const raw = JSON.parse(localStorage.getItem(KEY));
    expect(raw.v).toBe(TRACE_STORE_VERSION);
    expect(raw.key).toBe(mkFullKey(b));
    expect(Array.isArray(raw.data.rows)).toBe(true);
  });

  it('모듈캐시가 비어도(새로고침 시뮬레이션) localStorage에서 exact key 복원', () => {
    const b = mkBinding(); const key = mkFullKey(b);
    // localStorage에 직접 seed 후 clear로 모듈캐시만 비운 상태를 재현할 수 없으므로,
    // 유효 payload를 직접 심고 조회 → _mem 미스 → localStorage 폴백 경로 검증.
    localStorage.setItem(KEY, JSON.stringify({ v: TRACE_STORE_VERSION, key, binding: b, data: mkMatrix(2), savedAt: 111 }));
    const hit = loadTraceMatrixByKey(key);
    expect(hit.data.rows).toHaveLength(2);
    expect(hit.savedAt).toBe(111);
  });

  it('모듈캐시 비어도 localStorage에서 binding 하이드레이트', () => {
    const b = mkBinding();
    localStorage.setItem(KEY, JSON.stringify({ v: TRACE_STORE_VERSION, key: mkFullKey(b), binding: b, data: mkMatrix(4), savedAt: 222 }));
    expect(hydrateTraceMatrix(mkBinding()).data.rows).toHaveLength(4);
  });

  it('버전이 없거나 다른 저장분은 폐기한다(구 스키마 크래시 방지)', () => {
    const b = mkBinding();
    localStorage.setItem(KEY, JSON.stringify({ v: TRACE_STORE_VERSION + 1, key: mkFullKey(b), binding: b, data: mkMatrix(), savedAt: 1 }));
    expect(loadTraceMatrixByKey(mkFullKey(b))).toBeNull();
    expect(hydrateTraceMatrix(mkBinding())).toBeNull();
    const noV = JSON.stringify({ key: mkFullKey(b), binding: b, data: mkMatrix(), savedAt: 1 });
    localStorage.setItem(KEY, noV);
    expect(loadTraceMatrixByKey(mkFullKey(b))).toBeNull();
  });

  it('깨진 JSON / 렌더불가 저장분은 null', () => {
    localStorage.setItem(KEY, '{not json');
    expect(hydrateTraceMatrix(mkBinding())).toBeNull();
    const b = mkBinding();
    localStorage.setItem(KEY, JSON.stringify({ v: TRACE_STORE_VERSION, key: mkFullKey(b), binding: b, data: { summary: {} }, savedAt: 1 }));
    expect(loadTraceMatrixByKey(mkFullKey(b))).toBeNull();  // rows/items 없음
  });

  it('과대 매트릭스는 localStorage skip, 모듈캐시는 유지(안전 degrade)', () => {
    const b = mkBinding();
    const huge = mkMatrix(80000);  // 직렬화 > 2MB
    expect(JSON.stringify(huge).length).toBeGreaterThan(2_000_000);
    expect(saveTraceMatrix(mkFullKey(b), b, huge)).toBe(true);   // 모듈캐시엔 저장
    expect(localStorage.getItem(KEY)).toBeNull();               // localStorage는 skip
    expect(loadTraceMatrixByKey(mkFullKey(b)).data.rows).toHaveLength(80000);  // 세션 내 복원 가능
  });

  it('clearTraceMatrix가 모듈캐시와 localStorage를 모두 비운다', () => {
    const b = mkBinding(); saveTraceMatrix(mkFullKey(b), b, mkMatrix());
    expect(localStorage.getItem(KEY)).not.toBeNull();
    clearTraceMatrix();
    expect(localStorage.getItem(KEY)).toBeNull();
    expect(loadTraceMatrixByKey(mkFullKey(b))).toBeNull();
    expect(hydrateTraceMatrix(mkBinding())).toBeNull();
  });
});
