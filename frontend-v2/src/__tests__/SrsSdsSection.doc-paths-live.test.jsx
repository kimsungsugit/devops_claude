/**
 * SrsSdsSection(요구사항 커버리지) — "입력 문서 현황" 이 설정 저장을 **즉시** 반영하는가
 *
 * 사용자 보고(2026-08-05): "요구사항 커버리지에 입력 문서 현황은 설정에서 저장해도 안바뀐다".
 *
 * 이 섹션은 keep-alive(display:none)라 탭을 오가도 **재마운트되지 않는다**. 그래서
 * 마운트 시 1회만 읽는 구조(`useMemo(…, [])`)였을 때는 전체 새로고침 전까지 옛 경로가
 * 그대로 남았다. 앞선 커밋에서 구독(`useDocPathsSync`)으로 바꿨는데, 그 수정이 **이
 * 패널까지 실제로 닿는지**는 함수 단위 테스트만으로는 증명되지 않는다 —
 * 컴포넌트가 그 state 를 안 쓰거나 다른 출처를 읽고 있으면 여전히 안 바뀐다.
 *
 * 그래서 여기서는 **실제 컴포넌트를 렌더**하고, 재마운트 없이 화면 텍스트가 바뀌는지 본다.
 */
import { render, screen, act, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../App.jsx', () => ({
  useJenkinsCfg: () => ({
    cfg: { baseUrl: 'http://jenkins', username: 'u', token: 't', cacheRoot: '.cache' },
    update: vi.fn(),
  }),
  useToast: () => vi.fn(),
}));

vi.mock('../api.js', () => ({
  api: vi.fn(async () => ({})),
  post: vi.fn(async () => ({})),
  getUsername: vi.fn(() => 'tester'),
  authHeaders: vi.fn(() => ({})),
  buildUrl: vi.fn((p) => p),
  defaultCacheRoot: vi.fn(() => '.cache'),
}));

const { default: SrsSdsSection } = await import('../components/sections/SrsSdsSection.jsx');
const { saveDocPaths } = await import('../sharedInputs.js');

const JOB = { name: 'test-job', url: 'http://jenkins/job/test-job/' };

/** SCM 은 비워 둔다 — localStorage 경로만으로 패널이 그려지는지 보기 위해. */
const RESULT = {
  cacheRoot: '.cache',
  jobUrl: JOB.url,
  scmList: [{ id: 'scm-1', name: 'MyRepo', linked_docs: {} }],
  matchedScm: { id: 'scm-1', name: 'MyRepo', linked_docs: {} },
  matchedScmSource: 'manual',
  reportData: {},
  impactData: null,
};

beforeEach(() => {
  localStorage.clear();
});

describe('입력 문서 현황 — 설정 저장 즉시 반영', () => {
  it('재마운트 없이 새 파일명으로 바뀐다', async () => {
    saveDocPaths({ srs: 'U:/proj/OLD_SRS_v1.docx' });

    render(<SrsSdsSection job={JOB} analysisResult={RESULT} />);

    // 마운트 시점: 옛 파일명이 보인다.
    expect(await screen.findByText('OLD_SRS_v1.docx')).toBeInTheDocument();

    // 사용자가 설정 화면에서 저장 (이 컴포넌트는 그대로 마운트된 상태 — keep-alive).
    await act(async () => {
      saveDocPaths({ srs: 'U:/proj/NEW_SRS_v2.docx' });
      // 통지는 150ms 디바운스.
      await new Promise((r) => setTimeout(r, 250));
    });

    await waitFor(() => {
      expect(screen.getByText('NEW_SRS_v2.docx')).toBeInTheDocument();
    });
    expect(screen.queryByText('OLD_SRS_v1.docx')).not.toBeInTheDocument();
  });

  it('여러 문서 종류가 한 번에 갱신된다', async () => {
    saveDocPaths({});
    render(<SrsSdsSection job={JOB} analysisResult={RESULT} />);

    // 아무 경로도 없으면 '미등록' 이 보인다(패널 자체는 그려진다).
    expect(await screen.findByText('입력 문서 현황')).toBeInTheDocument();

    await act(async () => {
      saveDocPaths({
        srs: 'U:/p/SRS_a.docx',
        sds: 'U:/p/SDS_b.docx',
        uds: 'U:/p/UDS_c.docx',
        sits: 'U:/p/SITS_d.xlsm',
      });
      await new Promise((r) => setTimeout(r, 250));
    });

    await waitFor(() => {
      for (const name of ['SRS_a.docx', 'SDS_b.docx', 'UDS_c.docx', 'SITS_d.xlsm']) {
        expect(screen.getByText(name)).toBeInTheDocument();
      }
    });
  });

  it('경로를 지우면 미등록으로 돌아간다', async () => {
    saveDocPaths({ srs: 'U:/p/SRS_a.docx' });
    render(<SrsSdsSection job={JOB} analysisResult={RESULT} />);
    expect(await screen.findByText('SRS_a.docx')).toBeInTheDocument();

    await act(async () => {
      saveDocPaths({});   // 설정에서 비움
      await new Promise((r) => setTimeout(r, 250));
    });

    await waitFor(() => {
      expect(screen.queryByText('SRS_a.docx')).not.toBeInTheDocument();
    });
  });
});
