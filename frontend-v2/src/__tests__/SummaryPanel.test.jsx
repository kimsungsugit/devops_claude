/**
 * SummaryPanel — '프로젝트 분석' 탭 L1 데이터 카드 공용 래퍼.
 *
 * 고정하는 계약 두 가지:
 *  ① 제목이 진짜 `<h3>` 다 — 예전엔 11개 패널 전부 `<div>` 라 문서 heading 계층이 0이었고
 *     스크린리더로 패널 간 점프가 불가능했다.
 *  ② 접힘은 **CSS 숨김이지 언마운트가 아니다** — 언마운트하면 받아 둔 데이터와 펼친 행이
 *     날아가고 다시 열 때 재요청이 난다.
 */
import { useEffect } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';

import SummaryPanel, { SummaryToolStrip } from '../components/sections/SummaryPanel.jsx';

describe('SummaryPanel', () => {
  it('제목을 h3 heading으로 낸다', () => {
    render(<SummaryPanel title="아키텍처 메트릭"><div>본문</div></SummaryPanel>);
    const h = screen.getByRole('heading', { name: '아키텍처 메트릭' });
    expect(h.tagName).toBe('H3');
  });

  it('meta·actions·caption 슬롯을 모두 렌더한다', () => {
    render(
      <SummaryPanel title="제목" meta={<span>빌드 #125</span>} caption="부연 한 줄"
        actions={<button type="button">재생성</button>}>
        <div>본문</div>
      </SummaryPanel>,
    );
    expect(screen.getByText('빌드 #125')).toBeInTheDocument();
    expect(screen.getByText('부연 한 줄')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '재생성' })).toBeInTheDocument();
  });

  it('접기 버튼이 aria-expanded/aria-controls를 갖고 본문 id를 가리킨다', () => {
    render(<SummaryPanel title="제목"><div>본문</div></SummaryPanel>);
    const btn = screen.getByRole('button', { name: '제목 접기' });
    expect(btn).toHaveAttribute('aria-expanded', 'true');
    const bodyId = btn.getAttribute('aria-controls');
    expect(document.getElementById(bodyId)).toBeTruthy();
  });

  it('접어도 자식은 언마운트되지 않는다(데이터·펼친 행 보존)', async () => {
    const user = userEvent.setup();
    const unmounted = vi.fn();
    function Child() {
      // 언마운트되면 effect cleanup이 돈다 — 돌면 계약 위반(받아 둔 데이터가 날아간다).
      useEffect(() => unmounted, []);
      return <div>본문</div>;
    }
    render(<SummaryPanel title="제목"><Child /></SummaryPanel>);
    await user.click(screen.getByRole('button', { name: '제목 접기' }));
    expect(unmounted).not.toHaveBeenCalled();
    expect(screen.getByText('본문')).toBeInTheDocument();   // DOM에 그대로 남아 있다
    expect(screen.getByRole('button', { name: '제목 펼치기' })).toHaveAttribute('aria-expanded', 'false');
  });

  it('problem 슬롯은 접힘에서도 보인다(실패가 접힘 뒤로 숨으면 안 된다)', () => {
    render(
      <SummaryPanel title="다이어그램" defaultOpen={false}
        problem={<span>⚠ 조회 실패</span>}>
        <div>오류: HTTP 500</div>
      </SummaryPanel>,
    );
    expect(screen.getByText('⚠ 조회 실패')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '다이어그램 펼치기' })).toBeInTheDocument();
  });

  it('defaultOpen=false면 접힌 채로 시작하지만 meta는 계속 보인다', () => {
    // 접었을 때 숫자가 사라지면 "데이터가 없어졌다"로 읽힌다 — meta는 헤더에 남아야 한다.
    render(
      <SummaryPanel title="다이어그램" defaultOpen={false} meta={<span>모듈 8 · 관계 23</span>}>
        <div>본문</div>
      </SummaryPanel>,
    );
    expect(screen.getByRole('button', { name: '다이어그램 펼치기' })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByText('모듈 8 · 관계 23')).toBeInTheDocument();
  });

  it('collapsible=false면 접기 버튼이 없다', () => {
    render(<SummaryPanel title="제목" collapsible={false}><div>본문</div></SummaryPanel>);
    expect(screen.queryByRole('button', { name: /제목 (접기|펼치기)/ })).toBeNull();
    expect(screen.getByText('본문')).toBeInTheDocument();
  });

  it('SummaryToolStrip(L2)은 데이터 카드가 아니다 — .panel 클래스를 쓰지 않는다', () => {
    const { container } = render(<SummaryToolStrip><span>설정 줄</span></SummaryToolStrip>);
    expect(screen.getByText('설정 줄')).toBeInTheDocument();
    expect(container.querySelector('.panel')).toBeNull();
  });
});
