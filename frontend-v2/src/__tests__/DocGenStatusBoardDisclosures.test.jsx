/**
 * DocGenStatusBoard — **생성 공시** 표면 (R77 N110).
 *
 * STS/SUTS/SITS 생성기는 "무엇을 자르고·비우고·못 했는가" 를 `quality_report` 에 계속 늘려
 * 적었는데, 2026-09-20 실측으로 `frontend-v2/src` 에서 그 키를 읽는 곳이 **0건**이었다 —
 * 원시 JSON 을 여는 사람에게만 말하는 공시는 절반만 된 공시다.
 *
 * 이 파일이 겨누는 것은 두 가지다:
 *   1. 서버가 준 label/value/note 를 **그대로** 그리는가 (프론트가 문구·판정을 복제하면
 *      두 출처가 갈린다 — 이 저장소가 게이트 판정에서 이미 겪었다).
 *   2. 부재·빈 목록·경고를 서로 다르게 말하는가. `items: []` 는 "손실 없음" 이 아니라
 *      "이 산출물이 아무 축도 기록하지 않았음" 이고, `present:false` 는 또 다른 사실이다.
 */
import { render, screen, waitFor, within, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockApi = vi.fn();
const mockPost = vi.fn();
const mockToast = vi.fn();

vi.mock('../api.js', () => ({
  api: (...a) => mockApi(...a),
  post: (...a) => mockPost(...a),
  buildUrl: (p) => p,
  authHeaders: () => ({ Authorization: 'Bearer T', 'X-User': 'u' }),
  resolveCacheRoot: (ar, job, cfg) =>
    ar?.cacheRoot || (job?.url ? '.devops_pro_cache/u' : '') || cfg?.cacheRoot || '',
}));
vi.mock('../App.jsx', () => ({
  useToast: () => mockToast,
  useJenkinsCfg: () => ({ cfg: { cacheRoot: '.cache', buildSelector: 'lastSuccessfulBuild' }, update: () => {} }),
}));

const { default: DocGenStatusBoard } = await import('../components/sections/DocGenStatusBoard.jsx');

const JOB = { url: 'http://ci/job/X', name: 'X' };
const ANALYSIS = { matchedScm: { id: 'kjpds02_pv', name: 'KJPDS02_PV' } };

const rowOf = (label) => screen.getByText(new RegExp(`^${label}$`)).closest('tr')
  || screen.getByText(label).closest('tr');

function run(over = {}) {
  return {
    id: 1, doc_type: 'suts', scm_id: 'kjpds02_pv', project_root: 'D:/src',
    created_at: '2026-09-20T01:00:00+00:00', output_path: 'X:/out/suts.xlsm',
    meta: null, error_msg: null, gate_reason: null,
    summary: { overall_score: 88.0, gate_pass: true, score_delta: null, prev_run_id: 0, fn_count: 933 },
    scores: [{ metric_name: 'gated_metric_count', value: 5, gate_pass: null, threshold: null }],
    ...over,
  };
}

/** 근거 응답 — 공시 외 섹션은 전부 부재(이 파일의 관심 밖). */
const evidenceWith = (generation, docType = 'suts') => ({
  run_id: 1, output_path_present: true, sidecars_expected: false,
  expected_sidecars: {
    gate_report: false, confidence: false, docx_validate: true, reference: false,
    generation: docType !== 'uds',
  },
  gate_report: { present: false, reason: 'x' },
  confidence: { present: false, reason: 'x' },
  docx_validate: { present: false, reason: 'x' },
  reference: { present: false, reason: 'x' },
  generation,
});

/** 실측(2026-09-20) SUTS payload 를 서버가 번역한 모양. 문구는 서버 소유라 그대로 옮긴다. */
const SUTS_ITEMS = [
  { key: 'tc_profile', label: '시험 물량 프로파일', value: '정본 규모(기본)', tone: 'info',
    note: '정본과 같은 규모로만 만든 문서다 — 아래 상한에 걸린 시험은 이 문서에 없다.' },
  { key: 'suts_unknown_type_slots', label: '타입을 몰라 비운 칸', value: '146칸 (94개 unit)', tone: 'info',
    note: '빠뜨린 게 아니라 지어내지 않은 것이고, 이 칸은 사람이 채운다.' },
  { key: 'suts_range_conflicts', label: '범위 충돌', value: '7건', tone: 'warning',
    note: '설계서와 소스 중 한쪽이 틀렸다는 뜻이라 값을 고르지 않고 타입 폭으로 시험했다.' },
];

async function openEvidence(generation, docType = 'suts', label = '📙 SUTS') {
  mockApi.mockImplementation((path) => (String(path).includes('/evidence')
    ? Promise.resolve(evidenceWith(generation, docType))
    : Promise.resolve({ runs: [run({ id: 1, doc_type: docType })], total: 1 })));
  const user = userEvent.setup();
  render(<DocGenStatusBoard job={JOB} analysisResult={ANALYSIS} genState={null} />);
  const tr = await waitFor(() => rowOf(label));
  await user.click(within(tr).getByRole('button', { name: '근거' }));
  return await screen.findByTestId('generation-disclosures');
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  mockApi.mockResolvedValue({ runs: [], total: 0 });
  mockPost.mockResolvedValue({ suggestions: [] });
});

describe('DocGenStatusBoard — 생성 공시 (R77 N110)', () => {
  it('서버가 준 label·value·note 를 그대로 그린다', async () => {
    const panel = await openEvidence({ present: true, doc_type_hint: 'suts', items: SUTS_ITEMS });
    expect(panel.textContent).toContain('타입을 몰라 비운 칸');
    expect(panel.textContent).toContain('146칸 (94개 unit)');
    // 뜻이 값 옆에 없으면 "비운 칸 146" 은 결함으로 읽힌다.
    expect(panel.textContent).toContain('지어내지 않은 것');
    expect(panel.textContent).toContain('범위 충돌');
    expect(panel.textContent).toContain('7건');
    expect(within(panel).getAllByRole('listitem')).toHaveLength(3);
  });

  it('warning tone 만 경고 색을 쓴다 — 비운 칸은 결함이 아니다', async () => {
    const panel = await openEvidence({ present: true, doc_type_hint: 'suts', items: SUTS_ITEMS });
    const warn = within(panel).getByText('범위 충돌').closest('li');
    const info = within(panel).getByText('타입을 몰라 비운 칸').closest('li');
    expect(warn.style.color).toBe('var(--color-warning)');
    expect(info.style.color).toBe('');
  });

  it('항목 0건은 "손실 없음" 이 아니라 기록하지 않았다고 말한다', async () => {
    const panel = await openEvidence({ present: true, doc_type_hint: 'sts', items: [] });
    expect(panel.textContent).toContain('하나도 기록하지 않았다');
    expect(panel.textContent).toContain('손실이 0 이라는 뜻이 아니다');
    expect(within(panel).queryAllByRole('listitem')).toHaveLength(0);
  });

  it('공시가 없으면 사유를 붙인다 — 빈 칸으로 두지 않는다', async () => {
    const panel = await openEvidence({
      present: false, reason: 'payload 에 quality_report 기록 없음(공시를 남기기 전 생성기)',
    });
    expect(panel.textContent).toContain('생성 공시 없음');
    expect(panel.textContent).toContain('quality_report 기록 없음');
    expect(panel.textContent).not.toContain('사유 미상');
  });

  it('공시를 만들지 않는 문서 종류면 꼬리표를 붙인다 — 없는 파일을 찾게 만들지 않는다 (리뷰 W4)', async () => {
    // 양성: expected_sidecars.generation === false
    const panel = await openEvidence(
      { present: false, reason: 'payload 사이드카 없음 (doc.payload.json)' }, 'uds', '📘 UDS');
    expect(panel.textContent).toContain('이 문서 종류는 생성 공시를 만들지 않는다');
    cleanup();
    // 음성 대조군: 공시를 **만드는** 종류인데 사이드카가 없는 것은 다른 일이다(찾아볼 파일이 있다)
    const panel2 = await openEvidence(
      { present: false, reason: 'payload 사이드카 없음 (doc.payload.json)' }, 'suts');
    expect(panel2.textContent).toContain('payload 사이드카 없음');
    expect(panel2.textContent).not.toContain('만들지 않는다');
  });

  it('UDS 처럼 해당 없는 산출물은 서버 사유를 그대로 보인다', async () => {
    const panel = await openEvidence({
      present: false, reason: '생성 공시는 XLSM/XLSX 산출물(STS·SUTS·SITS)만 남긴다 — .docx 산출물엔 해당 없음',
    }, 'uds', '📘 UDS');
    expect(panel.textContent).toContain('해당 없음');
  });

  it('서버가 generation 섹션 자체를 안 내면(구 백엔드) 사이드카 부재와 다르게 말한다', async () => {
    const panel = await openEvidence(undefined);
    expect(panel.textContent).toContain('서버 응답에 generation 섹션이 없다');
    expect(panel.textContent).not.toContain('사유 미상');
  });

  it('items 가 배열이 아니어도 죽지 않는다 (R2 null guard)', async () => {
    const panel = await openEvidence({ present: true, doc_type_hint: 'sts', items: null });
    expect(panel.textContent).toContain('하나도 기록하지 않았다');
    cleanup();
    const panel2 = await openEvidence({ present: true, items: { a: 1 } });
    expect(panel2.textContent).toContain('하나도 기록하지 않았다');
  });

  it('프론트는 판정 문구를 지어내지 않는다 — 서버가 안 준 말은 화면에도 없다', async () => {
    // 음성 대조군: value 만 오고 note 가 비면 그 자리는 비어야지, 프론트가 설명을 만들면 안 된다.
    const panel = await openEvidence({
      present: true, doc_type_hint: 'sits',
      items: [{ key: 'sits_flows', label: '통합 흐름', value: '120 / 173 (제외 53)', note: '', tone: 'warning' }],
    });
    expect(panel.textContent).toContain('120 / 173 (제외 53)');
    expect(panel.textContent).not.toContain('상한');
    expect(panel.textContent).not.toContain('정상');
  });
});
