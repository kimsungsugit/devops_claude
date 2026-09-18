/**
 * swBuilderForms — 빌더 탭과 생성 현황 보드가 **같은 payload** 를 만드는지.
 *
 * 이 모듈이 생긴 이유는 조립 로직이 두 곳으로 갈라졌기 때문이다. 갈라진 채로 두면
 * 두 경로가 서로 다른 문서를 내고, 그 차이는 xlsx 를 열기 전엔 보이지 않는다.
 *
 * 아래 테스트 중 절반은 **음성 대조군**이다:
 *   - UI 전용 키가 payload 에 남지 않는가 (남으면 backend `extra='forbid'` 로 422)
 *   - 빈 배열을 **보내지 않는가** (보내면 "명시적으로 0개" 가 되어 config fallback 이 죽는다)
 *   - swreport 의 `template_path` 를 마이그레이션 대상으로 오해해 지우지 않는가
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('../sharedInputs.js', () => ({
  // 공유 입력은 이 테스트의 관심사가 아니다 — prefill 없이 폼 자체만 본다.
  loadSharedInputs: () => ({}),
  sharedDefaultsFor: () => ({}),
  applySharedDefaults: (base) => base,
  resolveTouched: () => new Set(),
}));

const {
  BUILDER_SPECS, loadBuilderForm, toBuildPayload, parseListField,
  missingRequiredFields, todayIso,
} = await import('../swBuilderForms.js');

beforeEach(() => localStorage.clear());

describe('loadBuilderForm — 기본값 + 저장값', () => {
  it('저장값이 기본값을 이긴다', () => {
    localStorage.setItem(BUILDER_SPECS.swut.storageKey,
      JSON.stringify({ project_id: 'KJPDS02', release_sw_version: '2.02' }));
    const f = loadBuilderForm('swut');
    expect(f.project_id).toBe('KJPDS02');
    expect(f.release_sw_version).toBe('2.02');
    expect(f.asil_level).toBe('ASIL A');     // 미저장 필드는 기본값 유지
  });

  it('test_date 는 저장값이 없으면 오늘로 채워진다', () => {
    expect(loadBuilderForm('swut').test_date).toBe(todayIso());
  });

  it('저장값이 깨져 있어도 기본값으로 복구한다 (빈 폼으로 두지 않는다)', () => {
    localStorage.setItem(BUILDER_SPECS.swit.storageKey, '{not json');
    const f = loadBuilderForm('swit');
    expect(f.project_id).toBe('HDPDM01');
    expect(f.asil_level).toBe('ASIL B');
  });

  it('알 수 없는 종류는 조용히 빈 폼을 내지 않고 throw 한다', () => {
    expect(() => loadBuilderForm('nope')).toThrow(/빌더 종류/);
  });
});

describe('legacy template_path 마이그레이션', () => {
  it('swut: 구 template_path 를 coverage_template_path 로 옮기고 원본 키는 제거한다', () => {
    localStorage.setItem(BUILDER_SPECS.swut.storageKey,
      JSON.stringify({ template_path: 'X:/old.xlsx' }));
    const f = loadBuilderForm('swut');
    expect(f.coverage_template_path).toBe('X:/old.xlsx');
    expect('template_path' in f).toBe(false);   // 남으면 backend 422
  });

  it('swut: 신규 키가 이미 있으면 덮어쓰지 않는다', () => {
    localStorage.setItem(BUILDER_SPECS.swut.storageKey, JSON.stringify({
      template_path: 'X:/old.xlsx', sutr_template_path: 'X:/new.xlsm',
    }));
    expect(loadBuilderForm('swut').coverage_template_path).toBe('');
  });

  it('swreport: template_path 는 현행 유효 필드다 — 지우면 안 된다', () => {
    localStorage.setItem(BUILDER_SPECS.swreport.storageKey,
      JSON.stringify({ template_path: 'X:/ES95411.xlsm' }));
    const f = loadBuilderForm('swreport');
    expect(f.template_path).toBe('X:/ES95411.xlsm');
  });
});

describe('toBuildPayload — UI 전용 키 strip + 배열 변환', () => {
  it('swut: log_folders_text 는 사라지고 log_folders 배열이 생긴다', () => {
    const form = { ...loadBuilderForm('swut'), log_folders_text: ' A \n\n B \n' };
    const p = toBuildPayload('swut', form);
    expect('log_folders_text' in p).toBe(false);
    expect(p.log_folders).toEqual(['A', 'B']);
  });

  it('비어 있으면 배열 키 자체를 보내지 않는다 (빈 배열 ≠ 미지정)', () => {
    const p = toBuildPayload('swut', { ...loadBuilderForm('swut'), log_folders_text: '  \n ' });
    expect('log_folders' in p).toBe(false);
  });

  it('swreport: source_paths_text → source_paths', () => {
    const form = { ...loadBuilderForm('swreport'), source_paths_text: 'p1\np2' };
    const p = toBuildPayload('swreport', form);
    expect('source_paths_text' in p).toBe(false);
    expect(p.source_paths).toEqual(['p1', 'p2']);
  });

  it('원본 폼을 변형하지 않는다 (호출부가 같은 form 을 재사용한다)', () => {
    const form = { ...loadBuilderForm('swit'), log_folders_text: 'A' };
    toBuildPayload('swit', form);
    expect(form.log_folders_text).toBe('A');
  });
});

describe('parseListField / missingRequiredFields', () => {
  it('공백 줄과 앞뒤 공백을 제거한다', () => {
    expect(parseListField('swit', { log_folders_text: ' a \n\n  \n b' })).toEqual(['a', 'b']);
  });

  it('공백만 든 필수값은 채워진 것으로 보지 않는다', () => {
    expect(missingRequiredFields({ project_id: 'P', release_sw_version: '   ', test_date: '' }))
      .toEqual(['release_sw_version', 'test_date']);
  });

  it('세 개가 다 차면 빈 배열', () => {
    expect(missingRequiredFields({ project_id: 'P', release_sw_version: '1.0', test_date: '2026-08-07' }))
      .toEqual([]);
  });
});
