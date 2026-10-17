/** traceMatrix.buildTraceMatrix — orchestration(입력 수집 → 서버 traceability-matrix) */
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockPost;
let mockApi;
vi.mock('../api.js', () => ({
  post: (...a) => mockPost(...a),
  // ⚠ vcastRagJob 이 잡 상태 폴링에 api() 를 쓴다. 빠뜨리면 undefined 호출이
  //   'transient 오류'로 삼켜져 **VectorCAST 경로가 통째로 no-op 인 채 테스트가 통과**한다.
  api: (...a) => mockApi(...a),
  authHeaders: () => ({ Authorization: 'Bearer T', 'X-User': 'u' }),
  buildUrl: (p) => p,
}));

const { buildTraceMatrix } = await import('../traceMatrix.js');

describe('buildTraceMatrix', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
    mockPost = vi.fn(() => Promise.resolve({}));
    mockApi = vi.fn(() => Promise.resolve({ job: { status: 'completed', result: {} } }));
  });

  it('SRS 요구사항이 없으면 ok:false(no_requirements) + matrix 미호출', async () => {
    global.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ preview: { items: [] } }) });
    const r = await buildTraceMatrix({ linkedDocs: { srs: 'x' }, jobUrl: 'j' });
    expect(r.ok).toBe(false);
    expect(r.reason).toBe('no_requirements');
    expect(mockPost.mock.calls.some(c => String(c[0]).includes('traceability-matrix'))).toBe(false);
  });

  it('요구사항 있으면 traceability-matrix 호출 + 수집 입력 전달', async () => {
    global.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ preview: { items: [{ id: 'R1' }] }, mapping: [] }) });
    mockPost = vi.fn((url) => {
      if (String(url).includes('traceability-matrix')) return Promise.resolve({ matrix: { rows: [1] } });
      if (String(url).includes('sds/extract')) return Promise.resolve({ sds_pairs: [{ a: 1 }], component_asil: { C1: 'C' } });
      return Promise.resolve({});
    });
    const r = await buildTraceMatrix({ linkedDocs: { srs: 'x', sds: 's' }, jobUrl: 'j', cacheRoot: 'c' });
    expect(r.ok).toBe(true);
    expect(r.matrix).toEqual({ rows: [1] });
    const call = mockPost.mock.calls.find(c => String(c[0]).includes('traceability-matrix'));
    expect(call[1].requirement_items).toEqual([{ id: 'R1' }]);
    expect(call[1].sds_pairs).toEqual([{ a: 1 }]);
    expect(call[1].component_asil).toEqual({ C1: 'C' });
    expect(call[1].job_url).toBe('j');
    expect(call[1].cache_root).toBe('c');
  });

  it('VectorCAST 는 **잡 + 폴링**으로 받고 결과가 vcast_rows 로 흘러든다', async () => {
    // sync 블로킹으로 되돌아가면(= 프록시 타임아웃에 끊겨 VectorCAST 없는 매트릭스가
    // 캐시되던 결함) 여기서 잡힌다.
    global.fetch.mockResolvedValue({
      ok: true, json: () => Promise.resolve({ preview: { items: [{ id: 'R1' }] }, mapping: [] }),
    });
    mockPost = vi.fn((url) => {
      if (String(url).includes('traceability-matrix')) return Promise.resolve({ matrix: { rows: [1] } });
      if (String(url).includes('vectorcast-rag-async')) return Promise.resolve({ job_id: 'J9' });
      return Promise.resolve({});
    });
    mockApi = vi.fn(() => Promise.resolve({
      job: {
        status: 'completed',
        result: { ok: true, data: { test_rows: [{ subprogram: 'Foo', result: 'pass' }] } },
      },
    }));

    await buildTraceMatrix({ linkedDocs: { srs: 'x', vectorcast: ['U:/vc'] }, jobUrl: 'j' });

    // sync 엔드포인트는 부르지 않는다.
    const syncCalls = mockPost.mock.calls.filter(
      c => String(c[0]).endsWith('/api/jenkins/report/vectorcast-rag'),
    );
    expect(syncCalls, 'sync 블로킹 호출로 되돌아갔다').toEqual([]);
    expect(mockPost.mock.calls.some(c => String(c[0]).includes('vectorcast-rag-async'))).toBe(true);
    expect(mockApi.mock.calls.some(c => String(c[0]).includes('impact-job/J9'))).toBe(true);

    // 잡 결과가 실제로 매트릭스 입력에 실린다 — 폴링만 하고 버리면 무의미하다.
    const call = mockPost.mock.calls.find(c => String(c[0]).includes('traceability-matrix'));
    expect(call[1].vcast_rows.some(r => r.subprogram === 'Foo')).toBe(true);
  });

  it('VectorCAST 잡 실패는 사유가 경고로 남는다 (빈손을 성공으로 위장 금지)', async () => {
    global.fetch.mockResolvedValue({
      ok: true, json: () => Promise.resolve({ preview: { items: [{ id: 'R1' }] }, mapping: [] }),
    });
    mockPost = vi.fn((url) => {
      if (String(url).includes('traceability-matrix')) return Promise.resolve({ matrix: { rows: [1] } });
      if (String(url).includes('vectorcast-rag-async')) return Promise.resolve({ job_id: 'J9' });
      return Promise.resolve({});
    });
    mockApi = vi.fn(() => Promise.resolve({ job: { status: 'failed', error: { title: 'worker down' } } }));

    const r = await buildTraceMatrix({ linkedDocs: { srs: 'x', vectorcast: ['U:/vc'] }, jobUrl: 'j' });
    expect(r.warnings.some(w => /VectorCAST/.test(w) && /worker down/.test(w))).toBe(true);
  });

  it('requirements-preview HTTP 실패도 흡수(경고) — matrix 미호출', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 500 });
    const r = await buildTraceMatrix({ linkedDocs: { srs: 'x' }, jobUrl: 'j' });
    expect(r.ok).toBe(false);
    expect(r.warnings.some(w => /요구사항 미리보기 실패/.test(w))).toBe(true);
  });
});
