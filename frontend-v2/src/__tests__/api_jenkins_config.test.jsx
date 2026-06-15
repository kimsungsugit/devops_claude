/**
 * Jenkins config 영속 회귀 — 토큰이 재시작/탭 닫기 후에도 유지되는지.
 *
 * 과거 토큰은 sessionStorage(탭 닫으면 소멸)였고, 비-admin 사용자는 서버 영속
 * (/api/config/jenkins, admin 전용)을 못 써서 재시작마다 토큰이 사라졌다.
 * 토큰을 localStorage 영속으로 전환 + 과거 sessionStorage 분 1회 migrate.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { loadJenkinsConfig, saveJenkinsConfig } from '../api.js';

const JENKINS_TOKEN_KEY = 'devops_v2_jenkins_token';
const JENKINS_KEY = 'devops_v2_jenkins';

describe('Jenkins config 영속', () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
  });

  it('save 시 토큰을 localStorage에 영속하고 sessionStorage에는 두지 않는다', () => {
    saveJenkinsConfig({ baseUrl: 'http://j', username: 'u', token: 'secret-tok' });
    expect(localStorage.getItem(JENKINS_TOKEN_KEY)).toBe('secret-tok');
    expect(sessionStorage.getItem(JENKINS_TOKEN_KEY)).toBeNull();
    // 나머지 config는 토큰 제외하고 JENKINS_KEY에 저장
    const rest = JSON.parse(localStorage.getItem(JENKINS_KEY));
    expect(rest.baseUrl).toBe('http://j');
    expect(rest.token).toBeUndefined();
  });

  it('save→load 라운드트립으로 토큰이 복원된다 (재시작 시뮬레이션)', () => {
    saveJenkinsConfig({ baseUrl: 'http://j', username: 'u', token: 'tok-123' });
    // load는 fresh 읽기 — localStorage는 재시작 후에도 유지됨
    const cfg = loadJenkinsConfig();
    expect(cfg.token).toBe('tok-123');
    expect(cfg.baseUrl).toBe('http://j');
  });

  it('과거 sessionStorage 토큰을 load 시 localStorage로 1회 migrate한다', () => {
    // 구버전 상태 재현: 토큰이 sessionStorage에만 존재
    localStorage.setItem(JENKINS_KEY, JSON.stringify({ baseUrl: 'http://j' }));
    sessionStorage.setItem(JENKINS_TOKEN_KEY, 'legacy-tok');

    const cfg = loadJenkinsConfig();
    expect(cfg.token).toBe('legacy-tok');
    // migrate 결과: localStorage로 옮겨지고 sessionStorage는 비워짐
    expect(localStorage.getItem(JENKINS_TOKEN_KEY)).toBe('legacy-tok');
    expect(sessionStorage.getItem(JENKINS_TOKEN_KEY)).toBeNull();
  });

  it('빈 토큰으로 save하면 localStorage 토큰 키를 제거한다', () => {
    localStorage.setItem(JENKINS_TOKEN_KEY, 'old');
    saveJenkinsConfig({ baseUrl: 'http://j', token: '' });
    expect(localStorage.getItem(JENKINS_TOKEN_KEY)).toBeNull();
  });
});
