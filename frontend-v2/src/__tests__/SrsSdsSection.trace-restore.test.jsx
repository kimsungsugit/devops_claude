/**
 * SrsSdsSection — 추적성 매트릭스 마운트 복원 상태기계 테스트
 *
 * 왜 필요한가: 이 영역은 두 번 Critical이 났고(751984c·d8ce4d1) **둘 다 스토어가 아니라
 * 마운트 effect의 상태전이**에서였다. traceMatrixStore.test.js는 순수 함수 계층만 덮으므로,
 * clean/stale/무복원 배지가 실제 렌더에서 맞게 나오는지는 여기서 컴포넌트로 검증한다(reviewer W3).
 *
 * 핵심 안전 불변식: 정확 키 일치만 "💾 저장된 결과"(current)로 표시하고, binding만 일치(입력
 * 드리프트)하면 반드시 "⚠ 입력 변경됨"(stale)으로 폭로하며, 다른 프로젝트 저장분은 절대 새지 않는다.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { saveTraceMatrix, clearTraceMatrix } from '../traceMatrixStore.js';

const mockToast = vi.fn();

vi.mock('../App.jsx', () => ({
  useJenkinsCfg: () => ({
    cfg: { baseUrl: 'http://jenkins', username: 'u', token: 't', cacheRoot: '.cache' },
    update: vi.fn(),
  }),
  useToast: () => mockToast,
}));

// api('/api/scm/list')는 {} 반환 → 매칭 없음 → 마운트 effect가 linkedDocs를 prop(activeScm.linked_docs)
// 그대로 유지 → 키가 결정적. post는 안 불림(traceFocus 미전달 → auto-load 없음).
vi.mock('../api.js', () => ({
  api: vi.fn(async () => ({})),
  post: vi.fn(async () => ({})),
  getUsername: vi.fn(() => 'tester'),
  authHeaders: vi.fn(() => ({})),
  buildUrl: vi.fn((p) => p),
  defaultCacheRoot: vi.fn(() => '.cache'),
}));

const { default: SrsSdsSection } = await import('../components/sections/SrsSdsSection.jsx');

const JOB = { name: 'test-job', url: 'http://jenkins/job/test-job/' };
const LINKED = { srs: 'S.docx', sds: 'D.docx', hsis: 'H.xlsx', sts: 'T.xlsm', suts: 'U.xlsm' };
const SCM = { id: 'scm-1', name: 'MyRepo', source_root: '', linked_docs: LINKED };

// 컴포넌트 buildCacheKey/buildBinding(W1 sentinel 반영)와 **정확히 같은 SHAPE**로 미러링.
// 여기가 컴포넌트와 어긋나면 테스트가 깨져 shape drift를 잡아준다(reviewer I1 의도).
const keyOf = (over = {}) => {
  const d = { ...LINKED, ...over };
  return JSON.stringify({
    srs: d.srs || '', sds: d.sds || '', hsis: d.hsis || '',
    jobUrl: JOB.url, sourceRoot: '',
    sts: d.sts || '', suts: d.suts || '', sits: d.sits || '', syts: d.syts || '', syits: d.syits || '',
    vcast: (Array.isArray(d.vectorcast) ? d.vectorcast.filter(Boolean) : []).join(','),
  });
};
const bindingOf = (over = {}) => {
  const d = { ...LINKED, ...over };
  return JSON.stringify({ jobUrl: JOB.url, sourceRoot: '', srs: d.srs || '', sds: d.sds || '', hsis: d.hsis || '' });
};

const mkMatrix = () => ({ rows: [], summary: {} });

const mkResult = (over = {}) => ({
  cacheRoot: '.cache',
  jobUrl: JOB.url,
  scmList: [SCM],
  matchedScm: SCM,
  matchedScmSource: 'manual',
  reportData: {},
  impactData: null,
  ...over,
});

describe('SrsSdsSection — 추적성 매트릭스 마운트 복원', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearTraceMatrix();
    localStorage.clear();
  });

  it('정확 키 일치 → 💾 저장된 결과(current) 배지, stale 문구 없음', async () => {
    saveTraceMatrix(keyOf(), bindingOf(), mkMatrix());   // 현재 입력과 완전 일치
    render(<SrsSdsSection job={JOB} analysisResult={mkResult()} />);

    expect(await screen.findByText(/💾\s*저장된 결과/)).toBeInTheDocument();
    expect(screen.queryByText(/입력 변경됨/)).not.toBeInTheDocument();
  });

  it('시험문서 드리프트(binding만 일치) → ⚠ 입력 변경됨(stale) 배지', async () => {
    // 저장은 옛 SUTS(U_old) 기준 → cacheKey는 다르지만 binding(설계문서+job)은 동일.
    saveTraceMatrix(keyOf({ suts: 'U_old.xlsm' }), bindingOf(), mkMatrix());
    render(<SrsSdsSection job={JOB} analysisResult={mkResult()} />);

    // 마지막 결과가 보이되(사용자 요구), 최신 아님을 크게 폭로한다.
    expect(await screen.findByText(/입력 변경됨/)).toBeInTheDocument();
    expect(screen.getByText(/새로고침으로 재생성/)).toBeInTheDocument();
    // stale은 clean(💾)으로 위장되지 않는다 — Critical 재발 방지의 핵심.
    expect(screen.queryByText(/💾\s*저장된 결과/)).not.toBeInTheDocument();
  });

  it('다른 프로젝트(jobUrl 상이) 저장분은 복원하지 않는다 — binding 누수 차단', async () => {
    const otherKey = JSON.stringify({
      srs: LINKED.srs, sds: LINKED.sds, hsis: LINKED.hsis,
      jobUrl: 'http://jenkins/job/OTHER/', sourceRoot: '',
      sts: LINKED.sts, suts: LINKED.suts, sits: '', syts: '', syits: '', vcast: '',
    });
    const otherBinding = JSON.stringify({
      jobUrl: 'http://jenkins/job/OTHER/', sourceRoot: '',
      srs: LINKED.srs, sds: LINKED.sds, hsis: LINKED.hsis,
    });
    saveTraceMatrix(otherKey, otherBinding, mkMatrix());
    render(<SrsSdsSection job={JOB} analysisResult={mkResult()} />);

    // 마운트 effect가 정착할 시간을 준 뒤 어떤 복원 배지도 없어야 한다.
    await screen.findByText('추적성 매트릭스');   // 패널은 항상 렌더
    await waitFor(() => expect(screen.queryByText(/저장된 결과/)).not.toBeInTheDocument());
  });

  it('저장분이 없으면 복원 배지가 없다(생성 전 상태)', async () => {
    render(<SrsSdsSection job={JOB} analysisResult={mkResult()} />);

    await screen.findByText('추적성 매트릭스');
    await waitFor(() => expect(screen.queryByText(/저장된 결과/)).not.toBeInTheDocument());
  });
});
