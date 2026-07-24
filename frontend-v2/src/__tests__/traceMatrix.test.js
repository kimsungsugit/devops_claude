/** traceMatrix.buildTraceMatrix — orchestration(입력 수집 → 서버 traceability-matrix) */
import { describe, it, expect, vi, beforeEach } from 'vitest';

let mockPost;
vi.mock('../api.js', () => ({
  post: (...a) => mockPost(...a),
  getUsername: () => 'u',
  buildUrl: (p) => p,
}));

const { buildTraceMatrix } = await import('../traceMatrix.js');

describe('buildTraceMatrix', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
    mockPost = vi.fn(() => Promise.resolve({}));
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

  it('requirements-preview HTTP 실패도 흡수(경고) — matrix 미호출', async () => {
    global.fetch.mockResolvedValue({ ok: false, status: 500 });
    const r = await buildTraceMatrix({ linkedDocs: { srs: 'x' }, jobUrl: 'j' });
    expect(r.ok).toBe(false);
    expect(r.warnings.some(w => /요구사항 미리보기 실패/.test(w))).toBe(true);
  });
});
