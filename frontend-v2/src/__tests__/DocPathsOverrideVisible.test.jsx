/**
 * 설정값이 SCM 최신본을 가릴 때 그 사실이 **화면에 보이는가** (2026-08-06 2차).
 *
 * ## 왜 이게 결함인가
 *
 * '입력 문서 현황'의 우선순위는 `설정(localStorage) > SCM linked_docs` 다. 이건 의도된
 * 정책이다(직접 입력값을 덮지 않는다). 문제는 **그게 안 보인다**는 것:
 *
 *   - 설정의 '빈 칸 채우기'는 SCM 값을 localStorage 로 **복사**한다. 그 순간부터 그 키는
 *     설정값으로 굳어, SCM 을 아무리 고쳐도 화면이 안 바뀐다.
 *   - 그 행에는 `SCM` 배지도 안 붙어서 직접 입력과 구분이 안 된다.
 *
 * 사용자에게는 "설정에서 저장했는데 안 바뀐다"로만 보인다. 침묵이 곧 오보고다.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockApi = vi.fn();
const mockPost = vi.fn();
const mockToast = vi.fn();

vi.mock('../api.js', () => ({
  api: (...a) => mockApi(...a),
  post: (...a) => mockPost(...a),
  getUsername: () => 'tester',
  authHeaders: () => ({}),
  buildUrl: (p) => p,
  defaultCacheRoot: () => '.cache',
}));
vi.mock('../App.jsx', () => ({
  useJenkinsCfg: () => ({ cfg: { baseUrl: 'http://jenkins', cacheRoot: '.cache' } }),
  useToast: () => mockToast,
}));

const { default: SrsSdsSection } = await import('../components/sections/SrsSdsSection.jsx');
const { saveDocPaths, loadDocPaths, docPathsOverridingScm, normDocPath } =
  await import('../sharedInputs.js');

const JOB = { name: 'kjpds02-pv', url: 'http://jenkins/job/kjpds02-pv/' };
const OLD = 'U:/proj/01.SwUTS/OLD_SwUTS_v1.01.xlsm';
const NEW = 'U:/proj/01.SwUTS/PV_v2631/NEW_SwUTS_v1.02.xlsm';
const SCM = { id: 'pv1', name: 'KJPDS02_PV', source_root: 'D:/src', linked_docs: { suts: NEW } };
const RESULT = { cacheRoot: '.cache', jobUrl: JOB.url, scmList: [SCM], matchedScm: SCM };

beforeEach(() => {
  mockApi.mockReset();
  mockPost.mockReset();
  mockToast.mockReset();
  localStorage.clear();
  mockApi.mockImplementation(async (p) => (
    String(p).includes('/api/scm/list') ? { items: [SCM] } : {}
  ));
  mockPost.mockResolvedValue({});
});

describe('docPathsOverridingScm — 판정', () => {
  it('양쪽 값이 다를 때만 가림으로 본다', () => {
    expect(docPathsOverridingScm({ suts: OLD }, { suts: NEW }, ['suts'])).toEqual(['suts']);
    expect(docPathsOverridingScm({ suts: NEW }, { suts: NEW }, ['suts'])).toEqual([]);
    expect(docPathsOverridingScm({}, { suts: NEW }, ['suts'])).toEqual([]);       // SCM만 → 가림 아님
    expect(docPathsOverridingScm({ suts: OLD }, {}, ['suts'])).toEqual([]);       // 설정만 → 가림 아님
  });

  it('슬래시 방향·끝 슬래시·대소문자 차이는 같은 경로로 본다', () => {
    expect(docPathsOverridingScm(
      { sds: 'U:\\proj\\SDS.docx' }, { sds: 'u:/proj/SDS.docx' }, ['sds'],
    )).toEqual([]);
    expect(normDocPath('U:\\a\\b\\')).toBe(normDocPath('U:/a/b'));
  });

  it('UNC 선두 // 는 접지 않는다 — 서버가 다른 경로가 같아 보이면 안 된다', () => {
    expect(normDocPath('//srvA/share/x.docx')).not.toBe(normDocPath('//srvB/share/x.docx'));
    expect(normDocPath('\\\\srv\\share')).toBe('//srv/share');
  });

  it('검사 키 목록에 없는 키는 보지 않는다', () => {
    expect(docPathsOverridingScm({ zzz: 'a' }, { zzz: 'b' }, ['suts'])).toEqual([]);
  });
});

describe('입력 문서 현황 — 가림 표면화', () => {
  it('설정값이 SCM 최신본을 가리면 경고와 해소 버튼을 낸다', async () => {
    saveDocPaths({ suts: OLD });
    render(<SrsSdsSection job={JOB} analysisResult={RESULT} />);

    expect(await screen.findByText('입력 문서 현황')).toBeInTheDocument();
    await waitFor(() => expect(
      screen.getByText(/설정 탭에 직접 저장된 경로가 SCM 최신본을 가리고/),
    ).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /SCM 값 따르기 \(1\)/ })).toBeInTheDocument();
    expect(screen.getByText('설정 우선')).toBeInTheDocument();
  });

  it('해소 버튼은 설정 키를 지워 SCM 값이 흐르게 한다 (복사가 아니라 삭제)', async () => {
    const user = userEvent.setup();
    saveDocPaths({ suts: OLD, srs: 'U:/keep/SRS.docx' });
    render(<SrsSdsSection job={JOB} analysisResult={RESULT} />);

    const btn = await screen.findByRole('button', { name: /SCM 값 따르기/ });
    await user.click(btn);

    // suts 는 **지워져야** 한다 — SCM 값을 복사해 넣으면 그 순간 또 굳어 다음 변경이 안 보인다.
    await waitFor(() => expect(loadDocPaths().suts).toBeUndefined());
    expect(loadDocPaths().srs).toBe('U:/keep/SRS.docx');   // 무관한 키는 보존
    // 해소되면 경고도 사라진다.
    await waitFor(() => expect(
      screen.queryByText(/설정 탭에 직접 저장된 경로가 SCM 최신본을 가리고/),
    ).toBeNull());
  });

  it('경로가 같으면 경고하지 않는다 (거짓 경보 금지)', async () => {
    saveDocPaths({ suts: NEW });
    render(<SrsSdsSection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('입력 문서 현황')).toBeInTheDocument();
    await waitFor(() => expect(mockApi).toHaveBeenCalled());
    expect(screen.queryByText(/SCM 최신본을 가리고/)).toBeNull();
    expect(screen.queryByText('설정 우선')).toBeNull();
  });

  it('설정에 값이 없으면 SCM 값을 그대로 쓰고 SCM 배지를 단다', async () => {
    render(<SrsSdsSection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('입력 문서 현황')).toBeInTheDocument();
    await waitFor(() => expect(
      screen.getByText('NEW_SwUTS_v1.02.xlsm'),
    ).toBeInTheDocument());
    expect(screen.queryByText(/SCM 최신본을 가리고/)).toBeNull();
  });
});
