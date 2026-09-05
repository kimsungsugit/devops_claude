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

  it('복원 시 저장된 경고를 재노출한다(zero-warning 게이트 제거의 안전 근거 — silent 은폐 방지)', async () => {
    // 실제 프로젝트는 데이터품질 advisory(SyRS 미매칭·SITS 2-hop 등)가 상시 있어, 과거엔 그 때문에
    // 저장이 통째로 막혔다(재진입/F5마다 소실). 이제 경고를 매트릭스와 함께 저장·복원하므로 캐시해도
    // 은폐가 아니다 — 복원 시 경고가 그대로 보여야 한다.
    saveTraceMatrix(keyOf(), bindingOf(), { ...mkMatrix(), _warnings: ['SITS: 2-hop 의존 경고 XYZ'] });
    render(<SrsSdsSection job={JOB} analysisResult={mkResult()} />);

    expect(await screen.findByText(/💾\s*저장된 결과/)).toBeInTheDocument();
    expect(await screen.findByText(/2-hop 의존 경고 XYZ/)).toBeInTheDocument();
  });

  it('binding-stale 복원도 저장된 경고를 재노출한다(L577 은폐 방지 — 뮤테이션 보증)', async () => {
    // 위 테스트는 exact(L568)만 탄다. 시험문서 드리프트로 stale 복원되는 경로(L577)도 데이터품질
    // 경고를 그대로 보여야 한다(계약#2). 이 경로의 setWarnings 삭제를 잡는 보증(deep-review W2).
    saveTraceMatrix(keyOf({ suts: 'U_old.xlsm' }), bindingOf(), { ...mkMatrix(), _warnings: ['STALE-PATH 경고 QRS'] });
    render(<SrsSdsSection job={JOB} analysisResult={mkResult()} />);
    expect(await screen.findByText(/입력 변경됨/)).toBeInTheDocument();          // stale 배지
    expect(await screen.findByText(/STALE-PATH 경고 QRS/)).toBeInTheDocument();  // 경고 재노출
  });

  it('cache-hit 경로(loadMatrix)도 저장된 경고를 재노출한다(L168 은폐 방지 — traceFocus로 격리)', async () => {
    // traceFocus가 있으면 mount 복원 effect는 skip되고(L553, auto-load가 소유) loadMatrix의 cache-hit
    // 경로(L165-171)가 단독으로 매트릭스+경고를 복원한다 → L168 setWarnings 삭제를 이 경로에서 잡는다.
    saveTraceMatrix(keyOf(), bindingOf(), { ...mkMatrix(), _warnings: ['CACHE-HIT 경고 ABC'] });
    localStorage.setItem('devops_v2_trace_focus', JSON.stringify({ functions: ['fn_a'], ts: Date.now() }));
    render(<SrsSdsSection job={JOB} analysisResult={mkResult()} />);
    expect(await screen.findByText(/💾\s*저장된 결과/)).toBeInTheDocument();
    expect(await screen.findByText(/CACHE-HIT 경고 ABC/)).toBeInTheDocument();
  });

  it('복원 시 저장된 정보성 요약(notices)을 별도 중립 채널로 재노출한다(A1 — 경고 아님)', async () => {
    // 정보성 배너(627 대부분 입도차 등)를 warnings가 아닌 notices 채널로 분리 저장·복원한다.
    // cache-hit 경로(traceFocus로 격리, L168)에서 _notices가 되살아나는지 검증(setNotices 배선 보증).
    saveTraceMatrix(keyOf(), bindingOf(), { ...mkMatrix(), _notices: ['NOTICE 요약 문구 DEF'] });
    localStorage.setItem('devops_v2_trace_focus', JSON.stringify({ functions: ['fn_a'], ts: Date.now() }));
    render(<SrsSdsSection job={JOB} analysisResult={mkResult()} />);
    expect(await screen.findByText(/💾\s*저장된 결과/)).toBeInTheDocument();
    expect(await screen.findByText(/NOTICE 요약 문구 DEF/)).toBeInTheDocument();
    // '경고 발생' 헤더가 아니라 중립 '추적성 요약(참고)' 박스에 떠야 한다(경고 채널과 분리).
    expect(screen.getByText(/추적성 요약 \(참고\)/)).toBeInTheDocument();
    expect(screen.queryByText(/경고가 발생했습니다/)).not.toBeInTheDocument();
  });

  it('clean 복원 매트릭스에 VectorCAST 결과(vcast_input_rows>0)가 있으면 빌드 기준 시점을 화면에 폭로한다(W1/Mechanism A 완화)', async () => {
    // exact 히트라 💾 clean이지만, VectorCAST 합부/커버리지는 저장 시점 빌드(lastSuccessfulBuild) 기준.
    // cacheKey에 빌드번호가 없어(백엔드 결합) 새 빌드 회귀를 exact-hit가 못 거른다 → 프론트는 이를
    // hover가 아닌 화면에 명시(가시 폭로)해 false-clean을 정직화한다(deep-review W1).
    saveTraceMatrix(keyOf(), bindingOf(), { rows: [{ requirement_id: 'X' }], summary: { vcast_input_rows: 42 } });
    render(<SrsSdsSection job={JOB} analysisResult={mkResult()} />);
    expect(await screen.findByText(/💾\s*저장된 결과/)).toBeInTheDocument();
    expect(screen.getByText(/빌드 결과는 저장 시점 기준/)).toBeInTheDocument();
  });

  it('VectorCAST 결과가 없는 순수 문서 추적 매트릭스는 빌드 기준 폭로를 붙이지 않는다(불필요 경고 방지)', async () => {
    saveTraceMatrix(keyOf(), bindingOf(), { rows: [{ requirement_id: 'X' }], summary: {} });
    render(<SrsSdsSection job={JOB} analysisResult={mkResult()} />);
    expect(await screen.findByText(/💾\s*저장된 결과/)).toBeInTheDocument();
    expect(screen.queryByText(/빌드 결과는 저장 시점 기준/)).not.toBeInTheDocument();
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

  it('clean 복원 후 레지스트리 수렴으로 입력이 드리프트하면 clean→stale로 강등한다(stale-as-fresh 차단)', async () => {
    // 실제 운영 시나리오(L84 주석): 매트릭스를 저장한 뒤 관리/Settings에서 설계·시험문서 경로가
    // 갱신되면(예: SUTS v0.10→v1.02), 재진입 시 (a) 마운트 초기엔 prop 스냅샷 키로 exact 히트→💾
    // clean 복원됐다가 (b) 레지스트리 수렴(useEffect [scmId])이 최신 경로를 반영하면 정확 키가
    // 어긋난다. 이때 clean 배지가 잔류하면 옛 매트릭스를 '최신'으로 위장한다(stale-as-fresh).
    // effect가 clean→stale 강등을 해야 ⚠로 폭로된다.
    const { api } = await import('../api.js');
    // 레지스트리는 저장 시점과 다른 SUTS를 반환 → 수렴 후 정확 키 miss 유발.
    api.mockResolvedValueOnce({ items: [{ ...SCM, linked_docs: { ...LINKED, suts: 'U_v1.02.xlsm' } }] });
    saveTraceMatrix(keyOf(), bindingOf(), mkMatrix());   // 저장은 옛 SUTS(U.xlsm) 스냅샷 키 = 초기 exact 히트
    render(<SrsSdsSection job={JOB} analysisResult={mkResult()} />);

    // 레지스트리 수렴(비동기) 후 정확 키가 어긋나 clean이 stale로 강등돼야 한다.
    expect(await screen.findByText(/입력 변경됨/)).toBeInTheDocument();
    // 강등이 없으면 여기서 💾가 잔류해 실패한다(이 fix의 핵심 — clean→stale 다운그레이드).
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
    await screen.findByText(/추적성 매트릭스/);   // 패널은 항상 렌더
    await waitFor(() => expect(screen.queryByText(/저장된 결과/)).not.toBeInTheDocument());
  });

  it('저장분이 없으면 복원 배지가 없다(생성 전 상태)', async () => {
    render(<SrsSdsSection job={JOB} analysisResult={mkResult()} />);

    await screen.findByText(/추적성 매트릭스/);
    await waitFor(() => expect(screen.queryByText(/저장된 결과/)).not.toBeInTheDocument());
  });
});
