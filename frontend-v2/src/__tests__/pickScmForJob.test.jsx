/**
 * pickScmForJob 단위 테스트
 *
 * Dashboard가 여러 SCM registry 중 현재 jobUrl에 맞는 엔트리를 어떻게 고르는지
 * 검증한다. 핵심 계약은 "확신이 없을 때 null을 반환"하는 것 — 그래야 백엔드가
 * repo_url 기반 자동 매칭으로 안전하게 fallback 한다.
 */
import { describe, it, expect } from 'vitest';
// 정본 경로 — 구현은 projectLoader 에 있다(예전엔 views/Dashboard 의 re-export 를 탔다).
import { pickScmForJob } from '../projectLoader.js';

describe('pickScmForJob', () => {
  it('빈 리스트면 null', () => {
    expect(pickScmForJob([], 'http://x/job/foo')).toBeNull();
    expect(pickScmForJob(null, 'http://x/job/foo')).toBeNull();
  });

  it('단일 엔트리면 그대로 반환', () => {
    const list = [{ id: 'only', name: 'Only', scm_username: 'u' }];
    expect(pickScmForJob(list, 'http://x/job/anything')).toBe(list[0]);
  });

  it('jobUrl에 id가 포함된 엔트리를 선택', () => {
    const list = [
      { id: 'alpha', name: 'Alpha' },
      { id: 'hdpdm01', name: 'HDPDM01' },
      { id: 'beta', name: 'Beta' },
    ];
    const picked = pickScmForJob(list, 'https://jenkins/job/HDPDM01_Build/');
    expect(picked?.id).toBe('hdpdm01');
  });

  it('jobUrl에 name이 포함된 엔트리를 선택', () => {
    const list = [
      { id: 'p1', name: 'UpperCasedProject' },
      { id: 'p2', name: 'OtherProject' },
    ];
    const picked = pickScmForJob(list, 'https://jenkins/job/UPPERCASEDPROJECT/');
    expect(picked?.id).toBe('p1');
  });

  it('매칭 확신이 없으면 null (잘못된 자격증명 주입 방지)', () => {
    const list = [
      { id: 'alpha', name: 'Alpha' },
      { id: 'beta', name: 'Beta' },
    ];
    expect(pickScmForJob(list, 'https://jenkins/job/unrelated/')).toBeNull();
  });

  it('id/name이 너무 짧으면 우연의 일치로 매칭하지 않음', () => {
    const list = [
      { id: 'a', name: 'A' },
      { id: 'bb', name: 'B' },
    ];
    // 짧은 토큰이 흔한 단어에 끼어 매칭되는 것을 막음
    expect(pickScmForJob(list, 'https://jenkins/job/anything/')).toBeNull();
  });

  // 회귀: 짧은 prefix id가 긴 형제 id를 가리는 버그(kjpds02 vs kjpds02_pv).
  // "kjpds02_pv" job URL은 "kjpds02"도 부분포함하므로, 첫 매치 승리 방식은
  // 리스트 앞의 짧은 kjpds02를 잘못 골라 다른 프로젝트 규격으로 분석했다.
  it('짧은 prefix가 앞에 있어도 정확한 형제(kjpds02_pv)를 고른다', () => {
    const list = [
      { id: 'hdpdm01', name: 'HDPDM01 PDS_64_RD' },
      { id: 'kjpds02', name: 'KJPDS02 NE1AW PORTING ToolDev' },
      { id: 'kjpds02_pv', name: 'KJPDS02_PV' },
    ];
    expect(pickScmForJob(list, 'https://jenkins/job/KJPDS02_PV/')?.id).toBe('kjpds02_pv');
  });

  it('등록 순서가 뒤바뀌어(kjpds02_pv 먼저)도 정확 매치가 이긴다', () => {
    const list = [
      { id: 'kjpds02_pv', name: 'KJPDS02_PV' },
      { id: 'kjpds02', name: 'KJPDS02 NE1AW PORTING ToolDev' },
    ];
    expect(pickScmForJob(list, 'https://jenkins/job/KJPDS02_PV/')?.id).toBe('kjpds02_pv');
  });

  it('반대 방향: 짧은 job(kjpds02)은 긴 id(kjpds02_pv)에 오매칭되지 않는다', () => {
    const list = [
      { id: 'kjpds02_pv', name: 'KJPDS02_PV' },
      { id: 'kjpds02', name: 'KJPDS02 NE1AW PORTING ToolDev' },
    ];
    // "kjpds02" job URL은 "kjpds02_pv"를 부분포함하지 않으므로 kjpds02만 매칭.
    expect(pickScmForJob(list, 'https://jenkins/job/KJPDS02/')?.id).toBe('kjpds02');
  });

  it('정확 세그먼트 매치가 없으면 최장 부분문자열이 이긴다(kjpds02_pv_build)', () => {
    const list = [
      { id: 'kjpds02', name: 'KJPDS02 NE1AW PORTING ToolDev' },
      { id: 'kjpds02_pv', name: 'KJPDS02_PV' },
    ];
    expect(pickScmForJob(list, 'https://jenkins/job/KJPDS02_PV_Build/')?.id).toBe('kjpds02_pv');
  });
});
