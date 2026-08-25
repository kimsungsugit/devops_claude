/**
 * 준비 게이트 사유가 **패널 안에서 접히는지**의 구조 계약.
 *
 * ## 왜 있나
 *
 * 사유에는 파일명이 통째로 들어간다 — 양식이 없을 때 백엔드가 그 폴더의 실제 파일을
 * 함께 내기 때문이다(`docgen_preflight.py::_folder_contents_hint`). 그런데
 * `KJPDS02_DV_Fault_Injection_TestResult_v1.01_251205_R.xlsx` 는 공백이 없는 57자라
 * 기본 줄바꿈으로 안 끊긴다. 260px 폭에서 렌더해 **패널 밖으로 삐져나가는 것**을
 * 확인했다(잘리는 게 아니라 넘쳐서 옆 내용과 겹친다).
 *
 * ⚠ `overflow-wrap: break-word` 로는 안 된다. 그건 min-content 크기를 줄이지 않아
 *   flex 항목(`.step-label { flex: 1 }`)이 여전히 안 줄어든다. `anywhere` 여야 한다.
 *
 * ⚠ **이 테스트가 보는 것은 CSS 원문이지 렌더 결과가 아니다.** jsdom 은 외부
 *   스타일시트를 적용하지 않아 계산된 스타일로는 확인할 수 없다. 시각 확인은
 *   Chrome headless `--screenshot` 로 했고, 여기서는 그 규칙이 사라지는 것만 막는다.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const CSS = readFileSync(
  resolve(dirname(fileURLToPath(import.meta.url)), '../index.css'),
  'utf-8',
);

/** `selector { ... }` 한 덩어리를 꺼낸다. 없으면 null. */
function ruleBody(selector) {
  const i = CSS.indexOf(`${selector} {`);
  if (i < 0) return null;
  const open = CSS.indexOf('{', i);
  const close = CSS.indexOf('}', open);
  return close < 0 ? null : CSS.slice(open + 1, close);
}

describe('준비 게이트 사유 줄바꿈', () => {
  it('.step-msg 규칙이 존재한다', () => {
    // ⚠ 규칙이 사라지면 아래 단언이 조용히 통과한다(null 을 훑어봐야 아무것도 없다).
    expect(ruleBody('.step-msg')).not.toBeNull();
  });

  it('.step-msg 가 긴 파일명을 끊는다', () => {
    expect(ruleBody('.step-msg')).toMatch(/overflow-wrap:\s*anywhere/);
  });

  it('break-word 로 되돌리지 않았다', () => {
    // min-content 를 안 줄이므로 flex 안에서는 효과가 없다 — 고친 척만 하게 된다.
    expect(ruleBody('.step-msg')).not.toMatch(/overflow-wrap:\s*break-word/);
  });

  it('추출기가 엉뚱한 규칙을 집지 않는다', () => {
    // 음성 대조군 — `.step-msg` 가 `.step-msg-foo` 같은 이름에 걸리면 위 단언이 거짓이 된다.
    expect(ruleBody('.step-icon')).toMatch(/flex-shrink:\s*0/);
    expect(ruleBody('.step-label')).toMatch(/flex:\s*1/);
    expect(ruleBody('.no-such-selector-xyz')).toBeNull();
  });
});
