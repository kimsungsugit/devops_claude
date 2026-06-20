/**
 * sharedInputs 단위 테스트 — 입력 일원화 병합/touched 추적/이벤트 동기화.
 *
 * 핵심 회귀 보호:
 * - freezing 방지: touched가 아닌(prefill) 필드는 공유 변경을 따라간다.
 * - RT-1: 사용자가 비운(touched) 필드는 공유 변경/리로드에도 빈값 유지.
 * - 대조: 사용자가 안 건드린 필드는 공유값을 따라간다(핵심 기능).
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import {
  sharedDefaultsFor,
  applySharedDefaults,
  markTouched,
  resolveTouched,
  useSharedInputSync,
  SHARED_KEY,
  SHARED_EVENT,
} from '../sharedInputs.js';

describe('sharedDefaultsFor', () => {
  it('정규 키를 섹션 폼 필드명으로 매핑하고 빈 값은 제외한다', () => {
    const shared = { tpl_coverage: 'A.xlsx', reviewer: '', project_id: 'P1' };
    const mapped = sharedDefaultsFor('swut', shared);
    expect(mapped).toEqual({ coverage_template_path: 'A.xlsx', project_id: 'P1' });
    expect(mapped).not.toHaveProperty('reviewer_override');
  });

  it('미지정 섹션은 빈 매핑을 반환한다', () => {
    expect(sharedDefaultsFor('unknown', { project_id: 'X' })).toEqual({});
  });
});

describe('applySharedDefaults (touched 기준)', () => {
  const mapped = { coverage_template_path: 'SHARED.xlsx', project_id: 'SHARED_P' };

  it('touched가 아닌 필드는 공유값으로 채운다', () => {
    const out = applySharedDefaults(
      { coverage_template_path: '', project_id: '', other: 'keep' }, new Set(), mapped);
    expect(out.coverage_template_path).toBe('SHARED.xlsx');
    expect(out.project_id).toBe('SHARED_P');
    expect(out.other).toBe('keep');   // 비매핑 필드 보존
  });

  it('touched 필드는 사용자값 보존, 미touched는 공유값', () => {
    const out = applySharedDefaults(
      { coverage_template_path: 'USER.xlsx', project_id: '' },
      new Set(['coverage_template_path']), mapped);
    expect(out.coverage_template_path).toBe('USER.xlsx');
    expect(out.project_id).toBe('SHARED_P');
  });

  it('touched로 표시된 빈 필드는 빈값 보존 (RT-1)', () => {
    const out = applySharedDefaults(
      { coverage_template_path: '' }, new Set(['coverage_template_path']), mapped);
    expect(out.coverage_template_path).toBe('');
  });
});

describe('markTouched / resolveTouched', () => {
  const SK = 'devops_v2_swut_form';
  beforeEach(() => localStorage.clear());

  it('markTouched가 touched 세트에 필드를 누적한다', () => {
    markTouched(SK, 'coverage_template_path');
    markTouched(SK, 'sutr_template_path');
    const t = resolveTouched('swut', SK, {});
    expect(t.has('coverage_template_path')).toBe(true);
    expect(t.has('sutr_template_path')).toBe(true);
  });

  it('touched 세트 부재 시 기존 saved의 non-empty 매핑값을 touched로 마이그레이션한다', () => {
    const saved = { coverage_template_path: '/legacy/cov.xlsx', sutr_template_path: '' };
    const t = resolveTouched('swut', SK, saved);
    expect(t.has('coverage_template_path')).toBe(true);   // non-empty 레거시 값 → 보호
    expect(t.has('sutr_template_path')).toBe(false);      // empty → 미touched(공유 따라감)
    // 1회 영속 — 재호출 시 saved 없이도 유지
    expect(resolveTouched('swut', SK, {}).has('coverage_template_path')).toBe(true);
  });
});

describe('useSharedInputSync (touched 기준 이벤트 동기화)', () => {
  const SK = 'devops_v2_swut_form';
  beforeEach(() => localStorage.clear());

  it('touched가 아닌(prefill) 필드만 갱신, touched(사용자) 필드는 보존한다', () => {
    localStorage.setItem(SHARED_KEY, JSON.stringify({ tpl_coverage: 'A.xlsx' }));
    markTouched(SK, 'sutr_template_path');   // 사용자가 sutr 손댐
    let form = { coverage_template_path: 'A.xlsx', sutr_template_path: 'USER.xlsm' };
    const setForm = (u) => { form = typeof u === 'function' ? u(form) : u; };
    renderHook(() => useSharedInputSync('swut', setForm, SK));

    localStorage.setItem(SHARED_KEY, JSON.stringify({ tpl_coverage: 'B.xlsx', tpl_sutr: 'SHARED.xlsm' }));
    act(() => window.dispatchEvent(new Event(SHARED_EVENT)));

    expect(form.coverage_template_path).toBe('B.xlsx');   // untouched → 새 공유값(freezing 없음)
    expect(form.sutr_template_path).toBe('USER.xlsm');     // touched → 보존
  });

  it('사용자가 비워 touched된 필드는 공유 변경 이벤트에도 보존된다 (RT-1)', () => {
    localStorage.setItem(SHARED_KEY, JSON.stringify({ tpl_coverage: 'A.xlsx' }));
    markTouched(SK, 'coverage_template_path');   // 비움도 touched
    let form = { coverage_template_path: '' };
    const setForm = (u) => { form = typeof u === 'function' ? u(form) : u; };
    renderHook(() => useSharedInputSync('swut', setForm, SK));

    localStorage.setItem(SHARED_KEY, JSON.stringify({ tpl_coverage: 'B.xlsx' }));
    act(() => window.dispatchEvent(new Event(SHARED_EVENT)));
    expect(form.coverage_template_path).toBe('');
  });

  it('storage 이벤트는 SHARED_KEY 변경에만 반응한다 (무관 키 무시)', () => {
    localStorage.setItem(SHARED_KEY, JSON.stringify({ tpl_coverage: 'A.xlsx' }));
    let form = { coverage_template_path: 'A.xlsx' };       // 미touched → prefill
    const setForm = (u) => { form = typeof u === 'function' ? u(form) : u; };
    renderHook(() => useSharedInputSync('swut', setForm, SK));

    localStorage.setItem(SHARED_KEY, JSON.stringify({ tpl_coverage: 'B.xlsx' }));
    act(() => window.dispatchEvent(new StorageEvent('storage', { key: SK })));  // 무관 키
    expect(form.coverage_template_path).toBe('A.xlsx');    // 무시

    act(() => window.dispatchEvent(new StorageEvent('storage', { key: SHARED_KEY })));
    expect(form.coverage_template_path).toBe('B.xlsx');    // SHARED_KEY → 반영
  });

  it('unmount 후에는 이벤트가 와도 setForm을 호출하지 않는다', () => {
    localStorage.setItem(SHARED_KEY, JSON.stringify({ tpl_coverage: 'A.xlsx' }));
    const setForm = vi.fn();
    const { unmount } = renderHook(() => useSharedInputSync('swut', setForm, SK));
    unmount();
    localStorage.setItem(SHARED_KEY, JSON.stringify({ tpl_coverage: 'B.xlsx' }));
    act(() => window.dispatchEvent(new Event(SHARED_EVENT)));
    expect(setForm).not.toHaveBeenCalled();
  });
});
