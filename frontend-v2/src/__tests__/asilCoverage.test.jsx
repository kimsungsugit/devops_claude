/**
 * 안전 요구(ASIL A~D) 커버리지 — **분모 0 은 0% 가 아니다**.
 *
 * 이 지표는 원래 `/api/local/traceability`(호출자 0인 죽은 경로) 안에만 있었고 분모가
 * `max(safety_total, 1)` 이었다. 그대로 배선했으면 ASIL 등급이 붙은 요구가 없는
 * 프로젝트에서 **"안전 요구 커버리지 0%"** 라는 없는 경보가 떴을 것이다.
 *
 * 아래 테스트의 절반은 **음성 대조군**이다 — "0% 라고 쓰지 않는가", "미상을 감추지
 * 않는가". 백엔드 쪽 대응 테스트는 `tests/unit/test_trace_safety_coverage.py`.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';

import { deriveSafetyCoverage, safetyCoverageText, SAFETY_GRADES } from '../asilCoverage.js';

vi.mock('../api.js', () => ({
  buildTone: () => 'neutral',
  post: vi.fn(() => Promise.resolve(null)),
}));

const { default: ResultPanel } = await import('../components/ResultPanel.jsx');
const { post } = await import('../api.js');

afterEach(() => {
  post.mockReset();
  post.mockImplementation(() => Promise.resolve(null));
});

const dist = (o) => Object.fromEntries(
  Object.entries(o).map(([g, [total, covered]]) => [g, { total, covered }]),
);

/* ── 파생 규칙 ─────────────────────────────────────────────────────────────── */

describe('deriveSafetyCoverage — 분모 0', () => {
  it('ASIL A~D 가 0건이면 pct 는 null 이다 (0 이 아니다)', () => {
    const sc = deriveSafetyCoverage(dist({ QM: [3, 3], UNKNOWN: [2, 1] }));
    expect(sc.total).toBe(0);
    expect(sc.pct).toBeNull();
    expect(sc.pct).not.toBe(0);
  });

  it('진짜 0%(안전 요구는 있는데 하나도 추적 안 됨)와 구별된다', () => {
    const realZero = deriveSafetyCoverage(dist({ C: [4, 0] }));
    const noTarget = deriveSafetyCoverage(dist({ QM: [4, 0] }));
    expect(realZero.pct).toBe(0);
    expect(noTarget.pct).toBeNull();
  });

  it('빈 입력은 hasData=false — 화면이 아무것도 안 그리게', () => {
    for (const empty of [null, undefined, {}, []]) {
      expect(deriveSafetyCoverage(empty).hasData).toBe(false);
    }
  });
});

describe('deriveSafetyCoverage — 무엇을 세는가', () => {
  it('QM(비안전)과 미상(판단 불가)은 분모에서 빠진다', () => {
    const sc = deriveSafetyCoverage(dist({ D: [2, 2], A: [2, 1], QM: [5, 5], UNKNOWN: [3, 3] }));
    expect(sc.total).toBe(4);
    expect(sc.covered).toBe(3);
    expect(sc.pct).toBe(75);
  });

  it('미상은 빼되 **건수는 돌려준다** — 100% 가 "전부 검증됨" 으로 읽히면 안 된다', () => {
    const sc = deriveSafetyCoverage(dist({ A: [62, 62], QM: [2, 2], UNKNOWN: [4, 4] }));
    expect(sc.pct).toBe(100);
    expect(sc.unknown).toBe(4);          // 실측 KJPDS02_PV 형태
  });

  it("백엔드 'UNKNOWN' 과 상세탭 '미상' 두 철자를 모두 센다", () => {
    expect(deriveSafetyCoverage(dist({ A: [1, 1], UNKNOWN: [7, 0] })).unknown).toBe(7);
    expect(deriveSafetyCoverage(dist({ A: [1, 1], 미상: [7, 0] })).unknown).toBe(7);
  });

  it('object 형태와 asilRows 배열 형태가 같은 결과를 낸다 (두 표면 lockstep)', () => {
    const asObject = deriveSafetyCoverage(dist({ D: [3, 2], QM: [1, 1], UNKNOWN: [2, 0] }));
    const asRows = deriveSafetyCoverage([
      { grade: 'D', total: 3, covered: 2 },
      { grade: 'QM', total: 1, covered: 1 },
      { grade: '미상', total: 2, covered: 0 },
    ]);
    expect(asRows).toEqual(asObject);
  });

  it('안전 등급 4개가 전부 세어진다 — 하나라도 빠지면 그 등급이 통째로 사라진다', () => {
    for (const g of SAFETY_GRADES) {
      expect(deriveSafetyCoverage(dist({ [g]: [1, 1] })).total).toBe(1);
    }
  });
});

/* ── 화면 문구 ─────────────────────────────────────────────────────────────── */

describe('safetyCoverageText — 모르는 걸 좋게 그리지 않는다', () => {
  it('미측정이면 값이 `—` 이고 "0% 아님" 을 명시한다', () => {
    const t = safetyCoverageText(deriveSafetyCoverage(dist({ QM: [2, 2] })));
    expect(t.value).toBe('—');
    expect(t.unmeasured).toBe(true);
    expect(t.detail).toMatch(/0% 아님/);
    expect(t.value).not.toMatch(/0/);
  });

  it('미상이 있으면 분모 밖이라는 사실을 note 로 낸다', () => {
    const t = safetyCoverageText(deriveSafetyCoverage(dist({ A: [10, 10], UNKNOWN: [3, 3] })));
    expect(t.value).toBe('100%');
    expect(t.note).toMatch(/미상 3건/);
    expect(t.note).toMatch(/분모 밖/);
  });

  it('미상이 없으면 note 는 빈 문자열 — 없는 경고를 만들지 않는다', () => {
    expect(safetyCoverageText(deriveSafetyCoverage(dist({ A: [10, 9] }))).note).toBe('');
  });

  it('데이터가 없으면 null — 화면이 빈 카드를 그리지 않는다', () => {
    expect(safetyCoverageText(deriveSafetyCoverage({}))).toBeNull();
  });
});

/* ── 실제 화면에 닿는가 (구조 검사가 아니라 렌더 결과로) ──────────────────── */

const mountWithTrace = (summary) => {
  post.mockImplementation((url) => (
    url === '/api/jenkins/uds/trace-summary'
      ? Promise.resolve({ has_data: true, ...summary })
      : Promise.resolve(null)
  ));
  return render(<ResultPanel result={{ jobUrl: 'http://ci/job/X', reportData: { kpis: {} }, artifacts: [] }} />);
};

describe('ResultPanel — 안전 커버리지가 화면에 나온다', () => {
  it('등급 분포가 있으면 안전 커버리지 줄을 그린다', async () => {
    mountWithTrace({
      total_requirements: 68, covered: 68, partial: 0, uncovered: 0, coverage_pct: 100,
      asil_distribution: dist({ A: [62, 62], QM: [2, 2], UNKNOWN: [4, 4] }),
    });
    // ⚠ 화면 전체에서 '100%' 를 찾으면 안 된다 — 등급 칩(A 62건 · 100%)도 같은
    //   문자열을 그려 매치가 여러 개다. 안전 커버리지 **줄 안에서만** 본다.
    const box = (await screen.findByText(/안전 요구\(ASIL A~D\) 커버리지/)).parentElement;
    expect(within(box).getByText('100%')).toBeInTheDocument();
    // 미상 4건을 감추면 100% 가 "안전 요구는 전부 검증됨" 으로 읽힌다.
    expect(within(box).getByText(/미상 4건은 분모 밖/)).toBeInTheDocument();
  });

  it('ASIL 요구가 0건이면 0% 가 아니라 `—` 로 그린다', async () => {
    mountWithTrace({
      total_requirements: 5, covered: 5, partial: 0, uncovered: 0, coverage_pct: 100,
      asil_distribution: dist({ QM: [3, 3], UNKNOWN: [2, 2] }),
    });
    const box = (await screen.findByText(/안전 요구\(ASIL A~D\) 커버리지/)).parentElement;
    expect(within(box).getByText('—')).toBeInTheDocument();
    expect(within(box).getByText(/0% 아님/)).toBeInTheDocument();
    // 음성 대조군: **값**으로 '0%' 를 쓰지 않는다.
    // ⚠ 박스 전체 텍스트에 정규식을 걸면 안 된다 — 설명 문구 "(0% 아님)" 자체가
    //   걸려서 이 단언이 **항상 실패**한다(첫 판이 그랬다). 값 노드 하나만 본다.
    expect(within(box).queryByText('0%')).toBeNull();
  });

  it('구버전 캐시(분포 없음)에서는 아무것도 그리지 않는다', async () => {
    mountWithTrace({ total_requirements: 5, covered: 5, partial: 0, uncovered: 0, coverage_pct: 100 });
    await waitFor(() => expect(post).toHaveBeenCalled());
    expect(screen.queryByText(/안전 요구\(ASIL A~D\) 커버리지/)).toBeNull();
  });
});
