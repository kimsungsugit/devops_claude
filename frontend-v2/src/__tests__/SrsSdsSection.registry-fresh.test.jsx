/**
 * 입력 문서 현황은 **레지스트리 최신본**을 보여야 한다 — 분석 시점 스냅샷이 아니라.
 *
 * 사용자 보고(2026-08-06): "다른 데는 변경되는데 SUTS만 안 바뀐다."
 *
 * ## 원인
 *
 * `SrsSdsSection` 에는 SCM 문서 출처가 **둘**이다:
 *
 *   scmLinked  (64행)  = `analysisResult.matchedScm.linked_docs` — **분석 시점 스냅샷**(고정)
 *   linkedDocs (76행)  = `/api/scm/list` 레지스트리 — effect(86~109행)가 재조회해 갱신
 *
 * 86~109행 주석이 이 문제를 이미 서술한다: *"관리/Settings에서 경로가 갱신돼도 프론트가
 * 옛 경로를 고집해 '파일을 찾을 수 없습니다'가 나고 새로고침·분석 재실행으로도 안
 * 고쳐졌다"*. 그런데 그 수정은 `loadMatrix` 쪽만 `linkedDocs` 를 쓰게 했고,
 * **'입력 문서 현황' 패널(708행)은 여전히 `scmLinked`(스냅샷)** 를 읽는다.
 * 같은 결함을 한쪽만 고친 것 — 이 저장소의 1순위 재발 패턴이다.
 *
 * ## 왜 하필 SUTS 였나
 *
 * 패널은 `localDocPaths[key] || scmLinked[key]` 순으로 고른다. Settings(localStorage)에
 * 넣어 둔 문서는 첫 항에서 잡히므로 최신으로 보이고, **localStorage 에 없는 문서만**
 * 스냅샷으로 떨어진다. 사용자가 레지스트리에서 SUTS 경로를 바꿨는데 그 키는
 * localStorage 에 없었으므로, SUTS 만 옛 경로로 남았다.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockApi = vi.fn();

vi.mock('../App.jsx', () => ({
  useJenkinsCfg: () => ({
    cfg: { baseUrl: 'http://jenkins', username: 'u', token: 't', cacheRoot: '.cache' },
    update: vi.fn(),
  }),
  useToast: () => vi.fn(),
}));

vi.mock('../api.js', () => ({
  api: (...a) => mockApi(...a),
  post: vi.fn(async () => ({})),
  getUsername: vi.fn(() => 'tester'),
  authHeaders: vi.fn(() => ({})),
  buildUrl: vi.fn((p) => p),
  defaultCacheRoot: vi.fn(() => '.cache'),
}));

const { default: SrsSdsSection } = await import('../components/sections/SrsSdsSection.jsx');

const JOB = { name: 'kjpds02-pv', url: 'http://jenkins/job/kjpds02-pv/' };

const OLD_SUTS = 'U:/proj/01.SwUTS/(KJPDS02_PV_SwUTS) Unit Test Spec_v1.03_260721.xlsm';
const NEW_SUTS = 'U:/proj/01.SwUTS/PV_v2631/(KJPDS02_PV_SwUTS) Unit Test Spec_v1.02_260615.xlsm';

/** 분석 시점 스냅샷 — 옛 SUTS 경로를 담고 있다(사용자가 그 뒤에 레지스트리를 고쳤다). */
const SNAPSHOT = { id: 'kjpds02_pv', name: 'KJPDS02_PV', linked_docs: { suts: OLD_SUTS } };

/** 레지스트리(단일 진실원) — 사용자가 방금 고친 최신 경로. */
const REGISTRY = { id: 'kjpds02_pv', name: 'KJPDS02_PV', linked_docs: { suts: NEW_SUTS } };

const RESULT = {
  cacheRoot: '.cache',
  jobUrl: JOB.url,
  scmList: [SNAPSHOT],
  matchedScm: SNAPSHOT,
  matchedScmSource: 'manual',
  reportData: {},
  impactData: null,
};

beforeEach(() => {
  localStorage.clear();
  mockApi.mockReset();
  mockApi.mockImplementation(async (path) => {
    if (String(path).includes('/api/scm/list')) return { items: [REGISTRY] };
    return {};
  });
});

describe('입력 문서 현황 — 레지스트리 최신본 우선', () => {
  it('스냅샷이 옛 SUTS 를 갖고 있어도 레지스트리 최신 경로를 보여준다', async () => {
    render(<SrsSdsSection job={JOB} analysisResult={RESULT} />);

    // 레지스트리 재조회(effect)가 끝나면 새 파일명이 보여야 한다.
    await waitFor(() => {
      expect(
        screen.getByText('(KJPDS02_PV_SwUTS) Unit Test Spec_v1.02_260615.xlsm'),
      ).toBeInTheDocument();
    });

    // 옛 스냅샷 파일명은 남아 있으면 안 된다 — 그게 "안 바뀐다" 의 실체였다.
    expect(
      screen.queryByText('(KJPDS02_PV_SwUTS) Unit Test Spec_v1.03_260721.xlsm'),
    ).not.toBeInTheDocument();
  });

  it('Settings(localStorage) 값이 있으면 그쪽이 계속 우선한다', async () => {
    const { saveDocPaths } = await import('../sharedInputs.js');
    saveDocPaths({ suts: 'U:/manual/OVERRIDE_SUTS.xlsm' });

    render(<SrsSdsSection job={JOB} analysisResult={RESULT} />);

    await waitFor(() => {
      expect(screen.getByText('OVERRIDE_SUTS.xlsm')).toBeInTheDocument();
    });
    // 사용자가 직접 지정한 값을 레지스트리가 덮으면 안 된다(기존 우선순위 계약).
    expect(
      screen.queryByText('(KJPDS02_PV_SwUTS) Unit Test Spec_v1.02_260615.xlsm'),
    ).not.toBeInTheDocument();
  });

  it('SUTS·SITS·STS 가 함께 갱신된다 (한 키만 고쳐지지 않는다)', async () => {
    const OLD = { suts: 'U:/old/A_SUTS.xlsm', sits: 'U:/old/A_SITS.xlsm', sts: 'U:/old/A_STS.xlsm' };
    const NEW = { suts: 'U:/new/B_SUTS.xlsm', sits: 'U:/new/B_SITS.xlsm', sts: 'U:/new/B_STS.xlsm' };
    mockApi.mockImplementation(async (path) => {
      if (String(path).includes('/api/scm/list')) {
        return { items: [{ id: 'kjpds02_pv', name: 'KJPDS02_PV', linked_docs: NEW }] };
      }
      return {};
    });
    const snap = { id: 'kjpds02_pv', name: 'KJPDS02_PV', linked_docs: OLD };
    render(<SrsSdsSection job={JOB} analysisResult={{ ...RESULT, scmList: [snap], matchedScm: snap }} />);

    await waitFor(() => {
      for (const n of ['B_SUTS.xlsm', 'B_SITS.xlsm', 'B_STS.xlsm']) {
        expect(screen.getByText(n)).toBeInTheDocument();
      }
    });
    for (const n of ['A_SUTS.xlsm', 'A_SITS.xlsm', 'A_STS.xlsm']) {
      expect(screen.queryByText(n)).not.toBeInTheDocument();
    }
  });

  it('레지스트리 조회가 실패하면 스냅샷으로 폴백한다(빈 화면 금지)', async () => {
    mockApi.mockImplementation(async (path) => {
      if (String(path).includes('/api/scm/list')) throw new Error('network');
      return {};
    });

    render(<SrsSdsSection job={JOB} analysisResult={RESULT} />);

    await waitFor(() => {
      expect(
        screen.getByText('(KJPDS02_PV_SwUTS) Unit Test Spec_v1.03_260721.xlsm'),
      ).toBeInTheDocument();
    });
  });
});
