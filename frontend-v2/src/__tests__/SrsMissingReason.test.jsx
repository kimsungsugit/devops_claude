/**
 * "SRS 문서가 있는데 없다고 나온다" — 실패 사유를 갈라 말하는가 (2026-08-06).
 *
 * ## 실체
 *
 * `reqItems.length === 0` 분기가 **세 상태를 한 문장**으로 뭉갰다:
 *   ① SRS 경로 미지정  ② 문서를 못 읽음(백엔드가 사유를 안다)  ③ 읽었으나 요구 ID 0건
 * 셋 다 "SRS 경로를 확인하세요"라고 해서, 문서가 멀쩡히 등록된 사용자에게는
 * **경로를 의심하라**는 엉뚱한 지시가 됐다.
 *
 * 게다가 `if (previewRes.ok)` 의 **else 가 비어 있어** 401/403/500 이 경고 한 줄 없이
 * 사라지고 역시 같은 문장으로 둔갑했다.
 *
 * 실측(KJPDS02): `kjpds02` 항목은 등록 문서 11개 중 8개가 실물 없음 — SRS 는 v2.03 로
 * 등록됐는데 폴더엔 v3.01_R 하나뿐이었다. 판정("없다")은 맞았고 **왜인지를 말하지
 * 않은 것**이 결함이다.
 */
import { render, screen, waitFor } from '@testing-library/react';
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
const { saveDocPaths } = await import('../sharedInputs.js');

const JOB = { name: 'kjpds02-pv', url: 'http://jenkins/job/kjpds02-pv/' };
const SRS = 'U:/proj/01.SwRS/(KJPDS02_SwRS) SRS_v2.03.docx';

function scmWith(linked) {
  const s = { id: 'pv1', name: 'KJPDS02_PV', source_root: 'D:/src', linked_docs: linked };
  return { cacheRoot: '.cache', jobUrl: JOB.url, scmList: [s], matchedScm: s };
}

/** requirements-preview 응답(또는 HTTP 실패)을 지정해 fetch 를 세운다. */
function stubFetch({ status = 200, body = {} } = {}) {
  global.fetch = vi.fn(async () => ({
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
    blob: async () => new Blob(),
  }));
}

beforeEach(() => {
  mockApi.mockReset();
  mockPost.mockReset();
  mockToast.mockReset();
  localStorage.clear();
  mockApi.mockResolvedValue({ items: [] });
  mockPost.mockResolvedValue({});
  stubFetch();
});

async function clickGenerate() {
  const { default: userEvent } = await import('@testing-library/user-event');
  const user = userEvent.setup();
  const btn = await screen.findByRole('button', { name: /생성|매트릭스/ });
  await user.click(btn);
  return user;
}

describe('요구사항 0건 — 사유를 갈라 말한다', () => {
  it('② 백엔드가 준 사유(파일 없음)를 그대로 보여준다 — 경로 탓으로 뭉개지 않는다', async () => {
    saveDocPaths({ srs: SRS });
    stubFetch({ body: {
      preview: { items: [] },
      req_doc_errors: ['(KJPDS02_SwRS) SRS_v2.03.docx: 파일 없음 — 경로가 바뀌었거나 문서가 이동/개정됐을 수 있다'],
    } });
    render(<SrsSdsSection job={JOB} analysisResult={scmWith({})} />);
    await clickGenerate();

    await waitFor(() => expect(
      screen.getByText(/SRS 문서를 읽지 못했습니다/),
    ).toBeInTheDocument());
    expect(screen.getByText(/파일 없음/)).toBeInTheDocument();
    // 옛 문구로 되돌아가면 안 된다.
    expect(screen.queryByText(/^SRS에서 요구사항을 추출하지 못했습니다\. SRS 경로를 확인하세요\.$/)).toBeNull();
  });

  it('① 경로 미지정은 "등록하세요"라고 말한다', async () => {
    stubFetch({ body: { preview: { items: [] } } });
    render(<SrsSdsSection job={JOB} analysisResult={scmWith({})} />);
    await clickGenerate();
    await waitFor(() => expect(
      screen.getByText(/SRS 경로가 지정되지 않았습니다/),
    ).toBeInTheDocument());
  });

  it('③ 읽혔는데 요구 0건이면 "양식 확인"이라고 말한다 (경로 탓 아님)', async () => {
    saveDocPaths({ srs: SRS });
    stubFetch({ body: { preview: { items: [] } } });   // req_doc_errors 없음 = 읽기는 성공
    render(<SrsSdsSection job={JOB} analysisResult={scmWith({})} />);
    await clickGenerate();
    await waitFor(() => expect(
      screen.getByText(/요구사항 ID를 0건 인식했습니다/),
    ).toBeInTheDocument());
  });

  it('HTTP 실패를 삼키지 않는다 — 상태코드를 보여준다', async () => {
    saveDocPaths({ srs: SRS });
    stubFetch({ status: 403, body: 'forbidden' });
    render(<SrsSdsSection job={JOB} analysisResult={scmWith({})} />);
    await clickGenerate();
    await waitFor(() => expect(
      screen.getByText(/요구사항 미리보기 실패: HTTP 403/),
    ).toBeInTheDocument());
  });
});

describe('입력 문서 현황 — 등록됨 ≠ 존재함', () => {
  it('레지스트리 문서가 실물이 없으면 "파일 없음"으로 표시한다', async () => {
    mockApi.mockImplementation(async (p) => {
      if (String(p).includes('/api/scm/list')) {
        return { items: [{ id: 'pv1', linked_docs: { srs: SRS } }] };
      }
      if (String(p).includes('/api/scm/linked-docs-status/')) {
        return { items: { srs: { exists: false, reason: '' } } };
      }
      return {};
    });
    render(<SrsSdsSection job={JOB} analysisResult={scmWith({ srs: SRS })} />);
    expect(await screen.findByText('입력 문서 현황')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('파일 없음')).toBeInTheDocument());
  });

  it('실물이 있으면 "확인됨" — 확인한 것만 확인됐다고 한다', async () => {
    mockApi.mockImplementation(async (p) => {
      if (String(p).includes('/api/scm/list')) {
        return { items: [{ id: 'pv1', linked_docs: { srs: SRS } }] };
      }
      if (String(p).includes('/api/scm/linked-docs-status/')) {
        return { items: { srs: { exists: true, reason: '' } } };
      }
      return {};
    });
    render(<SrsSdsSection job={JOB} analysisResult={scmWith({ srs: SRS })} />);
    expect(await screen.findByText('입력 문서 현황')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('확인됨')).toBeInTheDocument());
    expect(screen.queryByText('파일 없음')).toBeNull();
  });

  it('확인이 실패하면 "확인됨"이라 하지 않는다 (모름 ≠ 있음/없음)', async () => {
    mockApi.mockImplementation(async (p) => {
      if (String(p).includes('/api/scm/list')) {
        return { items: [{ id: 'pv1', linked_docs: { srs: SRS } }] };
      }
      if (String(p).includes('/api/scm/linked-docs-status/')) throw new Error('network');
      return {};
    });
    render(<SrsSdsSection job={JOB} analysisResult={scmWith({ srs: SRS })} />);
    expect(await screen.findByText('입력 문서 현황')).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText('등록됨').length).toBeGreaterThan(0));
    expect(screen.queryByText('확인됨')).toBeNull();
    expect(screen.queryByText('파일 없음')).toBeNull();
  });

  it('설정 직접 입력값은 존재를 단언하지 않는다 (서버가 모르는 경로)', async () => {
    saveDocPaths({ srs: 'U:/manual/MY_SRS.docx' });
    mockApi.mockImplementation(async (p) => {
      if (String(p).includes('/api/scm/list')) return { items: [{ id: 'pv1', linked_docs: {} }] };
      if (String(p).includes('/api/scm/linked-docs-status/')) return { items: {} };
      return {};
    });
    render(<SrsSdsSection job={JOB} analysisResult={scmWith({})} />);
    expect(await screen.findByText('입력 문서 현황')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('MY_SRS.docx')).toBeInTheDocument());
    expect(screen.queryByText('확인됨')).toBeNull();
  });

  it('설정이 가린 행에 SCM 쪽 "파일 없음"을 씌우지 않는다 (다른 파일의 판정이다)', async () => {
    // ⚠ 이 케이스가 없을 때, `fromScm &&` 가드를 지운 뮤테이션이 **생존**했다.
    //   화면에 보이는 값은 설정의 MY_SRS.docx 인데, 없다고 판정된 건 레지스트리의
    //   다른 파일이다 — 그 판정을 이 행에 붙이면 멀쩡한 파일을 없다고 표시한다.
    saveDocPaths({ srs: 'U:/manual/MY_SRS.docx' });
    mockApi.mockImplementation(async (p) => {
      if (String(p).includes('/api/scm/list')) {
        return { items: [{ id: 'pv1', linked_docs: { srs: SRS } }] };
      }
      if (String(p).includes('/api/scm/linked-docs-status/')) {
        return { items: { srs: { exists: false, reason: '' } } };
      }
      return {};
    });
    render(<SrsSdsSection job={JOB} analysisResult={scmWith({ srs: SRS })} />);
    expect(await screen.findByText('입력 문서 현황')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('MY_SRS.docx')).toBeInTheDocument());
    expect(screen.queryByText('파일 없음')).toBeNull();
    expect(screen.getByText('설정 우선')).toBeInTheDocument();   // 대신 가림을 알린다
  });

  it('"파일 없음" 배지에 사유 툴팁이 실제로 붙는다', async () => {
    // ⚠ StatusBadge 가 title prop 을 삼키던 시절엔 사유를 달아 뒀다고 생각한 자리가
    //   실제로는 아무 설명도 없었다 — 뮤테이션 생존으로 드러났다.
    mockApi.mockImplementation(async (p) => {
      if (String(p).includes('/api/scm/list')) {
        return { items: [{ id: 'pv1', linked_docs: { srs: SRS } }] };
      }
      if (String(p).includes('/api/scm/linked-docs-status/')) {
        return { items: { srs: { exists: false, reason: '' } } };
      }
      return {};
    });
    render(<SrsSdsSection job={JOB} analysisResult={scmWith({ srs: SRS })} />);
    const badge = await screen.findByText('파일 없음');
    await waitFor(() => expect(badge.getAttribute('title') || '').toMatch(/파일이 없습니다/));
  });
});
