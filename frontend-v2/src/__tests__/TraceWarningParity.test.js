/**
 * STS·SUTS·SITS 0건 분기의 **사유 우선순위는 같아야 한다**.
 *
 * 이 저장소가 세 라운드 연속 밟은 결함이 "형제 경로 중 한쪽만 고침" 이다. 여기서도
 * SITS 분기만 `warning || error || '시트 미인식'` 이었고 STS·SUTS 는 `error || '시트 미인식'`
 * 이었다. 백엔드가 '시트는 찾았는데 0행' 사유를 `warning` 에 실어 보내도, 그 두 분기는
 * **"시트 미인식"이라는 거짓 사유**를 붙인다(시트는 멀쩡히 찾았는데).
 *
 * 문구 자체가 아니라 **세 분기가 같은 순서인지**를 단언한다 — 이 결함의 본질이 비대칭이라
 * 한쪽만 보는 검사로는 재발을 못 막는다.
 */
import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const FILE = path.resolve(process.cwd(), 'src/components/sections/SrsSdsSection.jsx');

describe('추적성 0건 분기 사유 우선순위 (형제 대칭)', () => {
  const src = fs.readFileSync(FILE, 'utf-8');

  it.each(['stsData', 'sutsData', 'sitsData'])('%s 는 error 보다 warning 을 먼저 본다', (v) => {
    // `${xData.warning || xData.error || '시트 미인식'}` 형태를 찾는다.
    const re = new RegExp(`\\$\\{${v}\\.warning\\s*\\|\\|\\s*${v}\\.error`);
    expect(
      re.test(src),
      `${v} 0건 분기가 warning 을 안 본다 — '시트는 찾았는데 0행'에 "시트 미인식" 이라는 거짓 사유가 붙는다`,
    ).toBe(true);
  });

  it('세 분기가 모두 존재한다 — 검사가 조용히 0건을 훑고 통과하지 않게', () => {
    for (const v of ['stsData', 'sutsData', 'sitsData']) {
      expect(src.includes(`${v}.available_sheets`), `${v} 분기를 못 찾았다(선택자 갱신 필요)`).toBe(true);
    }
  });
});
