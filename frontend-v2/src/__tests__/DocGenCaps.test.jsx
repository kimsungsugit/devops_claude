import { describe, it, expect, beforeEach, vi } from 'vitest';
import { docGenCapsScope } from '../docGenHelpers.js';
import {
  DOCGEN_CAPS_KEY, DOCGEN_CAPS_EVENT, capsKeyFor,
  loadDocGenCaps, saveDocGenCap, saveDocGenChoice,
} from '../sharedInputs.js';

/**
 * 생성 상한 저장 — **미설정과 0 을 구분하는지**가 이 파일의 본체다.
 *
 * 키가 없으면 서버에 아무것도 보내지 않아 생성기 기본값이 쓰인다. `0` 을 보내면
 * "흐름을 하나도 만들지 마라" 가 되어 뜻이 정반대다.
 */
describe('docgen caps', () => {
  beforeEach(() => localStorage.removeItem(DOCGEN_CAPS_KEY));

  it('미설정이면 빈 객체 — 서버로 아무것도 안 보낸다', () => {
    expect(loadDocGenCaps()).toEqual({});
  });

  it('값을 저장하고 읽는다', () => {
    saveDocGenCap('max_flows', 200);
    expect(loadDocGenCaps().max_flows).toBe(200);
  });

  it('빈 값은 키를 지운다 — 생성기 기본값으로 되돌린다', () => {
    saveDocGenCap('max_flows', 200);
    saveDocGenCap('max_flows', '');
    expect(loadDocGenCaps().max_flows).toBeUndefined();
  });

  it('0 과 음수는 저장하지 않는다 — "하나도 만들지 마라" 가 되면 안 된다', () => {
    saveDocGenCap('max_flows', 0);
    expect(loadDocGenCaps().max_flows).toBeUndefined();
    saveDocGenCap('max_flows', -5);
    expect(loadDocGenCaps().max_flows).toBeUndefined();
  });

  it('소수는 잘라서 정수로 — 상한은 개수다', () => {
    saveDocGenCap('max_flows', '150.7');
    expect(loadDocGenCaps().max_flows).toBe(150);
  });

  it('숫자가 아니면 저장하지 않는다', () => {
    saveDocGenCap('max_flows', 'abc');
    expect(loadDocGenCaps().max_flows).toBeUndefined();
  });

  it('다른 상한을 건드리지 않는다', () => {
    saveDocGenCap('max_flows', 200);
    saveDocGenCap('max_subcases', 14);
    expect(loadDocGenCaps()).toEqual({ max_flows: 200, max_subcases: 14 });
    saveDocGenCap('max_flows', '');
    expect(loadDocGenCaps()).toEqual({ max_subcases: 14 });
  });

  it('손상된 저장값은 빈 객체로 — 화면이 죽지 않는다', () => {
    localStorage.setItem(DOCGEN_CAPS_KEY, '{not json');
    expect(loadDocGenCaps()).toEqual({});
  });
});


/**
 * 상한 저장 칸은 **프로젝트마다** 따로다.
 *
 * 오래 평면 키 하나였다. A 에서 `max_sequences` 를 낮추거나 `suts_scope='source'` 로
 * 바꾸면 프로젝트를 B 로 바꿔도 그 값이 그대로 따라가, **B 의 문서가 조용히 다른
 * 규칙으로** 만들어졌다. 상한은 소스 규모를 보고 정하는 값이라 프로젝트를 넘어가는
 * 순간 근거를 잃는다.
 */
describe('생성 상한 — 프로젝트 격리', () => {
  const A = 'http://ci/job/a';
  const B = 'http://ci/job/b';

  beforeEach(() => localStorage.clear());

  it('스코프가 다르면 서로 안 보인다', () => {
    saveDocGenCap('max_flows', 200, A);
    expect(loadDocGenCaps(A).max_flows).toBe(200);
    expect(loadDocGenCaps(B).max_flows).toBeUndefined();
  });

  it('스코프가 비면 평면 키로 동작한다 — 프로젝트 미정 화면에서 값을 잃지 않는다', () => {
    saveDocGenCap('max_flows', 5);
    expect(localStorage.getItem(DOCGEN_CAPS_KEY)).toBeTruthy();
    expect(loadDocGenCaps().max_flows).toBe(5);
  });

  it('평면 키의 옛 값은 첫 조회 때 현재 프로젝트로 이관되고 평면 키는 사라진다', () => {
    localStorage.setItem(DOCGEN_CAPS_KEY, JSON.stringify({ max_flows: 42 }));
    expect(loadDocGenCaps(A).max_flows).toBe(42);
    // 남겨 두면 **다음 프로젝트가 또 상속**받아 원래 결함이 되살아난다.
    expect(localStorage.getItem(DOCGEN_CAPS_KEY)).toBeNull();
    expect(loadDocGenCaps(B).max_flows).toBeUndefined();
  });

  it('이관은 스코프 칸이 비어 있을 때만 — 이미 정한 값을 덮지 않는다', () => {
    saveDocGenCap('max_flows', 7, A);
    localStorage.setItem(DOCGEN_CAPS_KEY, JSON.stringify({ max_flows: 999 }));
    expect(loadDocGenCaps(A).max_flows).toBe(7);
  });

  it('빈 평면 키는 이관하지 않는다 — `{}` 를 옮기면 진짜 값을 가려 버린다', () => {
    localStorage.setItem(DOCGEN_CAPS_KEY, '{}');
    expect(loadDocGenCaps(A)).toEqual({});
    expect(localStorage.getItem(DOCGEN_CAPS_KEY)).toBe('{}');
  });

  it('문자열 선택지도 같은 칸을 쓴다', () => {
    saveDocGenChoice('template_source', 'standard', A);
    expect(loadDocGenCaps(A).template_source).toBe('standard');
    expect(loadDocGenCaps(B).template_source).toBeUndefined();
  });

  it('저장하면 같은 탭에 통지가 간다 — 게이트가 바뀐 값으로 다시 판정해야 한다', async () => {
    const seen = vi.fn();
    window.addEventListener(DOCGEN_CAPS_EVENT, seen);
    saveDocGenCap('max_flows', 1, A);
    // 디바운스 150ms — 통지가 아예 없으면 형제 행이 옛 판정을 그대로 들고 있다.
    await new Promise(r => setTimeout(r, 250));
    window.removeEventListener(DOCGEN_CAPS_EVENT, seen);
    expect(seen).toHaveBeenCalled();
  });

  it('키 계산이 단일 출처다 — 화면과 생성이 갈리면 다른 칸을 본다', () => {
    expect(capsKeyFor(A)).toBe(`${DOCGEN_CAPS_KEY}::${A}`);
    expect(capsKeyFor('')).toBe(DOCGEN_CAPS_KEY);
    expect(docGenCapsScope({ url: 'http://CI/job/A/' })).toBe('http://ci/job/a');
    expect(docGenCapsScope(null)).toBe('');
  });
});
