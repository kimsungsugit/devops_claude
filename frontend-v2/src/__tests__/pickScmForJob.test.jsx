/**
 * pickScmForJob 단위 테스트
 *
 * Dashboard가 여러 SCM registry 중 현재 jobUrl에 맞는 엔트리를 어떻게 고르는지
 * 검증한다. 핵심 계약은 "확신이 없을 때 null을 반환"하는 것 — 그래야 백엔드가
 * repo_url 기반 자동 매칭으로 안전하게 fallback 한다.
 */
import { describe, it, expect } from 'vitest';
import { pickScmForJob } from '../views/Dashboard.jsx';

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
});
