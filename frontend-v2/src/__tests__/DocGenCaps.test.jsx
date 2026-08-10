import { describe, it, expect, beforeEach } from 'vitest';
import {
  DOCGEN_CAPS_KEY, loadDocGenCaps, saveDocGenCap,
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
