import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { cTypeBoundaries, proposeBoundaryTCs, formatSutsLoc } from '../impactBoundary.js';

// 경계값 유도(결정론) — 영향분석 '작성 제안' 골격의 수치 출처. 백엔드 _c_type_boundaries와 미러.
describe('cTypeBoundaries — C 타입 경계값(결정론)', () => {
  it('U16 → 0x0 / 0x8000 / 0xFFFF (unsigned hex)', () => {
    const vals = cTypeBoundaries('U16').map((x) => x.value);
    expect(vals).toContain('0x0');
    expect(vals).toContain('0x8000');
    expect(vals).toContain('0xFFFF');
  });

  it('S8 → -128 / 0 / 127 (signed 10진 유지)', () => {
    expect(cTypeBoundaries('S8').map((x) => x.value)).toEqual(['-128', '0', '127']);
  });

  it('U8 → 0xFF + INV(범위초과) 케이스 (unsigned hex)', () => {
    const b = cTypeBoundaries('U8');
    expect(b.map((x) => x.value)).toContain('0xFF');
    expect(b.find((x) => x.label === 'INV').value).toBe('0x100(범위초과)');
    expect(b.some((x) => x.label === 'INV')).toBe(true);
  });

  it('별칭 매핑(uint8_t / unsigned char → hex, int → s32 10진)', () => {
    expect(cTypeBoundaries('uint8_t').map((x) => x.value)).toContain('0xFF');
    expect(cTypeBoundaries('unsigned char').map((x) => x.value)).toContain('0xFF');
    // int → s32 (signed 10진 유지)
    expect(cTypeBoundaries('int').map((x) => x.value)).toContain('2147483647');
  });

  it('boolean → FALSE=0 / TRUE=1', () => {
    expect(cTypeBoundaries('boolean')).toEqual([{ label: 'FALSE', value: '0' }, { label: 'TRUE', value: '1' }]);
  });

  it('포인터/배열 → NULL + 유효(정수 경계 아님)', () => {
    expect(cTypeBoundaries('const U8*').map((x) => x.label)).toContain('NULL');
    expect(cTypeBoundaries('U8[8]').map((x) => x.label)).toContain('NULL');
  });

  it('const/volatile 수식어 제거 후 매칭', () => {
    expect(cTypeBoundaries('const U16').map((x) => x.value)).toContain('0xFFFF');
  });

  it('float → 특수(NaN/Inf) 케이스 포함', () => {
    expect(cTypeBoundaries('float').some((x) => /NaN/.test(x.value))).toBe(true);
  });

  it('미상 타입(enum/struct/typedef)·빈값 → [] (숫자 환각 금지)', () => {
    expect(cTypeBoundaries('MyEnum_t')).toEqual([]);
    expect(cTypeBoundaries('struct Foo')).toEqual([]);
    expect(cTypeBoundaries('')).toEqual([]);
    expect(cTypeBoundaries(null)).toEqual([]);
  });
});

// 백엔드 workflow/c_type_bounds.py 와의 드리프트 방지. 예전엔 양쪽이 서로를 "미러"라고
// 주석으로만 선언한 복제본이라 한쪽만 고치면 조용히 갈라졌다(경고 없음). 이제 공유 픽스처
// tests/fixtures/c_type_bounds.json 을 Python(test_c_type_bounds_mirror.py)과 여기가 함께
// assert 하므로, 어느 쪽을 고쳐도 픽스처를 재생성하지 않으면 양쪽 테스트가 동시에 깨진다.
describe('cTypeBoundaries ↔ 백엔드 공유 픽스처 정합', () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const fixture = JSON.parse(
    readFileSync(resolve(here, '../../../tests/fixtures/c_type_bounds.json'), 'utf-8'),
  );
  const pairs = (rows) => rows.map(([label, value]) => ({ label, value }));

  it('모든 타입 별칭이 픽스처와 동일한 [{label,value}] 을 낸다', () => {
    const aliasEntries = Object.entries(fixture.alias);
    expect(aliasEntries.length).toBeGreaterThan(0);
    for (const [alias, key] of aliasEntries) {
      expect(cTypeBoundaries(alias), `별칭 '${alias}' 드리프트`).toEqual(pairs(fixture.bounds[key]));
    }
  });

  it('float 계열 전체가 픽스처의 float 케이스와 동일', () => {
    expect(fixture.float_types.length).toBeGreaterThan(0);
    for (const t of fixture.float_types) {
      expect(cTypeBoundaries(t), `float 별칭 '${t}' 드리프트`).toEqual(pairs(fixture.float_cases));
    }
  });

  it('포인터/배열이 픽스처의 포인터 케이스와 동일', () => {
    expect(cTypeBoundaries('U8*')).toEqual(pairs(fixture.pointer));
    expect(cTypeBoundaries('U8[8]')).toEqual(pairs(fixture.pointer));
  });
});

describe('proposeBoundaryTCs — 파라미터별 경계값 TC 골격', () => {
  it('명명 파라미터마다 경계값 케이스', () => {
    const r = proposeBoundaryTCs([{ type: 'U16', name: 'idx' }, { type: 'boolean', name: 'flag' }]);
    expect(r.params).toHaveLength(2);
    expect(r.params[0].param).toBe('idx');
    expect(r.params[0].cases.map((c) => c.value)).toContain('0xFFFF');
    expect(r.params[1].cases.map((c) => c.value)).toEqual(['0', '1']);
  });

  it('미상 타입 파라미터 → 골격만(가짜 숫자 없음)', () => {
    const r = proposeBoundaryTCs([{ type: 'MyEnum_t', name: 'mode' }]);
    expect(r.params[0].cases).toEqual([{ label: '유효/경계', value: '각 유효값·경계' }]);
  });

  it('이름 없는 파라미터는 제외(input=value 귀속 불가)', () => {
    expect(proposeBoundaryTCs([{ type: 'U16', name: '' }]).params).toHaveLength(0);
  });

  it('변경된 조건부 컴파일 매크로 → branchNote 표면화', () => {
    const r = proposeBoundaryTCs([], { macros: { added: ['CFG_X'], removed: [] } });
    expect(r.branchNote).toMatch(/CFG_X/);
  });

  it('빈/비배열 입력 방어', () => {
    expect(proposeBoundaryTCs(null).params).toEqual([]);
    expect(proposeBoundaryTCs(undefined).branchNote).toBe('');
  });
});

describe('formatSutsLoc — SUTS TC 실 위치 표시(정직 표기)', () => {
  it('시트+행 전체 → "시트 · 행 N"', () => {
    expect(formatSutsLoc({ sheet: '2.SW Unit Test Spec', tc_row: 42, sequence_row: 43 }))
      .toBe('2.SW Unit Test Spec 시트 · 행 42');
  });

  it('시트만 있으면 행 생략(존재 필드만)', () => {
    expect(formatSutsLoc({ sheet: '2.SW Unit Test Spec' })).toBe('2.SW Unit Test Spec 시트');
  });

  it('행만 있으면 시트 생략', () => {
    expect(formatSutsLoc({ tc_row: 7 })).toBe('행 7');
  });

  it('빈 객체/누락/null → \'\' (행 번호 날조 금지)', () => {
    expect(formatSutsLoc({})).toBe('');
    expect(formatSutsLoc(null)).toBe('');
    expect(formatSutsLoc(undefined)).toBe('');
    expect(formatSutsLoc({ tc_row: '' })).toBe('');
  });

  it('sheet 라벨은 백엔드 값 그대로(하드코딩 아님)', () => {
    expect(formatSutsLoc({ sheet: '3.SW Test Spec', tc_row: 10 })).toBe('3.SW Test Spec 시트 · 행 10');
  });
});
