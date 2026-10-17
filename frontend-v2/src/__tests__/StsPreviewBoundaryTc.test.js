import { describe, it, expect } from 'vitest';
import { STS_PREVIEW_TC_LIMIT, stsPreviewTcs, reconcileSuts } from '../impactDocDraft.js';

// (R76 N93) 영향도 가이드 STS 카드는 생성기 TC 를 앞에서 4건만 보였다. 경계값 TC 는 분기 TC **뒤 마지막 자리**에 서므로
// 분기가 4개 이상인 함수에선 구조적으로 안 보였다(총량은 공시됐지만 "무슨 시험이 빠졌는지" 는 안 보였다).
const tc = (label) => [{ action: label, expected: 'ok' }];
const many = (n) => Array.from({ length: n }, (_, i) => tc(`branch ${i}`));

describe('stsPreviewTcs — 경계값 TC 는 미리보기 절단에 먼저 잘리지 않는다', () => {
  it('경계값 TC 가 상한 밖이면 마지막 칸을 받는다(번호는 원래 순번)', () => {
    const list = [...many(5), tc('입력 설정 (경계 최솟값): a = 0')];
    const shown = stsPreviewTcs(list, 5);
    expect(shown).toHaveLength(STS_PREVIEW_TC_LIMIT);
    expect(shown.map((s) => s.no)).toEqual([1, 2, 3, 6]);
    expect(shown[3].boundary).toBe(true);
    expect(shown[3].tc[0].action).toContain('경계 최솟값');
    expect(shown.slice(0, 3).every((s) => s.boundary === false)).toBe(true);
  });

  it('상한 바로 다음 자리(다섯째)의 경계값 TC 도 마지막 칸을 받는다 — 경계 한 칸 차이', () => {
    const shown = stsPreviewTcs([...many(4), tc('입력 설정 (경계 최솟값): a = 0')], STS_PREVIEW_TC_LIMIT);
    expect(shown.map((s) => s.no)).toEqual([1, 2, 3, 5]);
    expect(shown[3].boundary).toBe(true);
    // 넷째 자리(상한 안의 마지막)는 바꾸지 않는다
    const inside = stsPreviewTcs([...many(3), tc('입력 설정 (경계 최솟값): a = 0'), ...many(1)], STS_PREVIEW_TC_LIMIT - 1);
    expect(inside.map((s) => s.no)).toEqual([1, 2, 3, 4]);
    expect(inside.map((s) => s.boundary)).toEqual([false, false, false, true]);
  });

  it('상한 안에 있으면 순서를 건드리지 않고 표시만 단다', () => {
    const list = [...many(2), tc('입력 설정 (경계 최솟값): a = 0')];
    const shown = stsPreviewTcs(list, 2);
    expect(shown.map((s) => s.no)).toEqual([1, 2, 3]);
    expect(shown.map((s) => s.boundary)).toEqual([false, false, true]);
  });

  it.each([[undefined], [null], [-1], [99], ['5'], [1.5]])('자리를 모르면(%s) 예전처럼 앞에서 자른다', (idx) => {
    const shown = stsPreviewTcs(many(6), idx);
    expect(shown.map((s) => s.no)).toEqual([1, 2, 3, 4]);
    expect(shown.some((s) => s.boundary)).toBe(false);
  });

  it('목록이 배열이 아니면 빈 배열', () => {
    expect(stsPreviewTcs(null, 0)).toEqual([]);
    expect(stsPreviewTcs(undefined, undefined)).toEqual([]);
  });
});

// (R76 N94) 타입 출처 라벨이 `globals_map_typedef` 로 늘었다 — 판정 로직은 라벨을 보지 않으므로 결과가 같아야 한다.
describe('typeSource — 새 라벨이 판정을 바꾸지 않는다', () => {
  const cols = ['g_Speed'];
  const args = (source) => ({
    docRows: [{ tc_id: 'T', inputs: { g_Speed: '0x0' }, expected: { g_Speed: '0x0' } }],
    docColumns: { inputs: cols, expected: cols, sheet: 's' },
    varTypes: { g_Speed: { type: 'uint16_t', source } },
    diffElems: [{ kind: 'modified', name: 'g_Speed' }],
  });

  it('globals_map 과 globals_map_typedef 는 같은 행을 내고 라벨만 다르다', () => {
    const a = reconcileSuts(args('globals_map'));
    const b = reconcileSuts(args('globals_map_typedef'));
    const strip = (r) => JSON.parse(JSON.stringify(r, (k, v) => (k === 'typeSource' ? undefined : v)));
    expect(strip(b)).toEqual(strip(a));
    const sources = (r) => JSON.stringify(r).match(/"typeSource":"[^"]*"/g) || [];
    expect(sources(b).every((s) => s.includes('globals_map_typedef'))).toBe(true);
    expect(sources(b).length).toBe(sources(a).length);
  });
});
