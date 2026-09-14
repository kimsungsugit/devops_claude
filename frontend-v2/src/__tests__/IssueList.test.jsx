import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';

/**
 * (R48-b) 문제 목록 컴포넌트.
 * - actual/potential 을 갈라 그리고, 서버 값(severity·source·code·facts)을 그대로 보인다.
 * - 빈 목록은 "문제 없음" 이 아닐 수 있다 — 근거 없는 축을 적는다.
 * - Gemini 설명은 버튼으로만 · `generated_by` 를 숨기지 않는다(룰 폴백이면 그렇게 적는다).
 */
const { default: IssueList } = await import('../components/IssueList.jsx');

const ISSUES = [
  { code: 'gate_fail:traceability_rate', severity: 'error', kind: 'actual', source: 'gate_report', message: '게이트 미달: traceability_rate', facts: { gate: 'traceability_rate' } },
  { code: 'tbd_residual:asil_tbd', severity: 'warning', kind: 'potential', source: 'gate_report', message: 'ASIL TBD 29 / 169', facts: { count: 29, total: 169 } },
  { code: 'report_timeout:accuracy', severity: 'warning', kind: 'actual', source: 'generation', stage: 'reports', message: 'accuracy 리포트 300초 타임아웃', facts: {} },
];

describe('IssueList', () => {
  it('actual / potential 을 가르고 건수·심각도·출처·코드를 서버 값 그대로 적는다', () => {
    render(<IssueList issues={ISSUES} counts={{ by_severity: { error: 1, warning: 2, risk: 0 } }} />);
    expect(screen.getByTestId('issue-counts')).toHaveTextContent('문제가 된 것 2 · 문제가 될 수 있는 것 1');
    expect(screen.getByTestId('issue-counts')).toHaveTextContent('오류 1 · 경고 2 · 주의 0');
    expect(screen.getByText(/문제가 된 것 \(2\)/)).toBeInTheDocument();
    expect(screen.getByText(/문제가 될 수 있는 것 \(1\)/)).toBeInTheDocument();
    expect(screen.getByText('gate_fail:traceability_rate')).toBeInTheDocument();
    expect(screen.getAllByText(/게이트 리포트 · /)).toHaveLength(2);   // gate_report 출처 2건
    expect(screen.getByText(/생성 중 · reports/)).toBeInTheDocument();
    expect(screen.getByText('count=29 total=169')).toBeInTheDocument();
    expect(screen.queryByRole('button')).toBeNull();   // onExplain 없으면 버튼 없음
  });

  it('빈 목록: 근거 없는 축이 있으면 "잰 것이 없음" 을 말한다', () => {
    render(<IssueList issues={[]} sources={{ generation: false, gate_report: false, docx_validate: true }} />);
    const s = screen.getByTestId('issue-empty');
    expect(s).toHaveTextContent(/관측된 문제가 없습니다/);
    expect(s).toHaveTextContent(/근거가 없는 축이 있습니다: 게이트 리포트/);
    expect(s).toHaveTextContent(/잰 것이 없음/);
    expect(screen.getByText(/생성 중 수집 기록이 없는 run/)).toBeInTheDocument();
  });

  it('Gemini 설명은 버튼으로만 부르고, 응답의 출처(generated_by·model)를 그대로 보인다', async () => {
    const user = userEvent.setup();
    const onExplain = vi.fn().mockResolvedValue({
      generated_by: 'llm', model: 'gemini-3.5-flash-lite', summary: '요약 문장',
      items: [{ code: 'gate_fail:traceability_rate', explanation: '왜', action: '어떻게' }],
      items_shown: 3, items_total: 3,
    });
    render(<IssueList issues={ISSUES} onExplain={onExplain} />);
    expect(onExplain).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Gemini 로 풀어 설명' }));
    await waitFor(() => expect(screen.getByTestId('issue-explain')).toHaveTextContent('요약 문장'));
    expect(screen.getByTestId('issue-explain')).toHaveTextContent(/Gemini · gemini-3.5-flash-lite/);
    expect(screen.getByText(/↳ 왜/)).toBeInTheDocument();
    expect(screen.getByText(/→ 어떻게/)).toBeInTheDocument();
    expect(onExplain).toHaveBeenCalledTimes(1);
  });

  it('룰 폴백이면 LLM 이 아니라고 적고 사유를 보인다', async () => {
    const user = userEvent.setup();
    const onExplain = vi.fn().mockResolvedValue({ generated_by: 'rule', model: null, llm_reason: 'LLM 이 설정되지 않았다', summary: '룰 요약', items: [], items_shown: 3, items_total: 3 });
    render(<IssueList issues={ISSUES} onExplain={onExplain} />);
    await user.click(screen.getByRole('button', { name: 'Gemini 로 풀어 설명' }));
    const box = await screen.findByTestId('issue-explain');
    expect(box).toHaveTextContent(/룰 문장\(LLM 미사용\)/);
    expect(box).toHaveTextContent(/LLM 이 설정되지 않았다/);
    expect(box.textContent).not.toMatch(/Gemini ·/);
  });

  it('설명 실패는 alert 로, 목록은 그대로 남는다', async () => {
    const user = userEvent.setup();
    const onExplain = vi.fn().mockRejectedValue(new Error('503'));
    render(<IssueList issues={ISSUES} onExplain={onExplain} />);
    await user.click(screen.getByRole('button', { name: 'Gemini 로 풀어 설명' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/설명 생성 실패: 503/);
    expect(within(screen.getByTestId('issue-list')).getByText('gate_fail:traceability_rate')).toBeInTheDocument();
  });
});
