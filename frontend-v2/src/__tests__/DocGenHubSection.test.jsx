/**
 * DocGenHubSection 단위 테스트
 *
 * 검증:
 * - 6개 생성 종류 옵션 세그먼트 렌더
 * - 기본 서브는 docgen, 나머지는 lazy(미마운트)
 * - 서브 클릭 시 해당 서브 표시 + 이전 서브는 keep-alive(숨김 유지)
 * - initialSub prop으로 외부 서브 지정
 *
 * 6개 자식 섹션은 mock(단위 격리) — useToast/useAdminMode 등 컨텍스트 의존 차단.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../components/sections/DocGenSection.jsx', () => ({ default: () => <div data-testid="sub-docgen">docgen</div> }));
vi.mock('../components/sections/ReportGenSection.jsx', () => ({ default: () => <div data-testid="sub-reports">reports</div> }));
vi.mock('../components/sections/SwUTBuildSection.jsx', () => ({ default: () => <div data-testid="sub-swut">swut</div> }));
vi.mock('../components/sections/SwITBuildSection.jsx', () => ({ default: () => <div data-testid="sub-swit">swit</div> }));
vi.mock('../components/sections/SwSABuildSection.jsx', () => ({ default: () => <div data-testid="sub-swsa">swsa</div> }));
vi.mock('../components/sections/SwReportSummarySection.jsx', () => ({ default: () => <div data-testid="sub-swreport">swreport</div> }));

const { default: DocGenHubSection } = await import('../components/sections/DocGenHubSection.jsx');

describe('DocGenHubSection', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('6개 옵션 세그먼트를 렌더한다', () => {
    render(<DocGenHubSection />);
    ['문서 생성', '리포트', 'SwUT', 'SwIT', 'SwSA', '통합 결과'].forEach(label => {
      expect(screen.getByRole('tab', { name: label })).toBeInTheDocument();
    });
  });

  it('기본 서브는 문서 생성(docgen)이고 다른 서브는 마운트되지 않는다', () => {
    render(<DocGenHubSection />);
    expect(screen.getByTestId('sub-docgen')).toBeVisible();
    expect(screen.queryByTestId('sub-swut')).toBeNull();
    expect(screen.queryByTestId('sub-swreport')).toBeNull();
  });

  it('SwUT 클릭 시 swut 서브를 표시하고 docgen은 숨김 유지한다(keep-alive)', async () => {
    const user = userEvent.setup();
    render(<DocGenHubSection />);
    await user.click(screen.getByRole('tab', { name: 'SwUT' }));
    expect(screen.getByTestId('sub-swut')).toBeVisible();
    // docgen은 unmount되지 않고 DOM에 남아 숨겨진다(빌드/폼 상태 보존).
    expect(screen.getByTestId('sub-docgen')).not.toBeVisible();
  });

  it('서브 전환 후 재방문해도 이전에 연 서브가 유지된다', async () => {
    const user = userEvent.setup();
    render(<DocGenHubSection />);
    await user.click(screen.getByRole('tab', { name: 'SwUT' }));
    await user.click(screen.getByRole('tab', { name: '리포트' }));
    expect(screen.getByTestId('sub-reports')).toBeVisible();
    expect(screen.getByTestId('sub-swut')).not.toBeVisible();   // 마운트 유지(숨김)
    await user.click(screen.getByRole('tab', { name: 'SwUT' }));
    expect(screen.getByTestId('sub-swut')).toBeVisible();
  });

  it('initialSub prop으로 외부에서 서브를 지정하면 해당 서브가 표시된다', () => {
    render(<DocGenHubSection initialSub="swut" />);
    expect(screen.getByTestId('sub-swut')).toBeVisible();
  });

  it('onSubChange로 활성 서브 변경을 부모에 알린다 (초기 + 전환)', async () => {
    const user = userEvent.setup();
    const onSubChange = vi.fn();
    render(<DocGenHubSection onSubChange={onSubChange} />);
    // 초기 마운트 시 docgen 통지
    expect(onSubChange).toHaveBeenCalledWith('docgen', '문서 생성');
    onSubChange.mockClear();
    await user.click(screen.getByRole('tab', { name: 'SwIT' }));
    expect(onSubChange).toHaveBeenCalledWith('swit', 'SwIT');
  });

  it('탭에 ARIA 결합(aria-controls/tabpanel) + roving tabIndex가 적용된다', () => {
    render(<DocGenHubSection />);
    const active = screen.getByRole('tab', { name: '문서 생성' });
    expect(active).toHaveAttribute('aria-controls', 'docgen-panel-docgen');
    expect(active).toHaveAttribute('tabindex', '0');
    const inactive = screen.getByRole('tab', { name: 'SwUT' });
    expect(inactive).toHaveAttribute('tabindex', '-1');
    // 활성 패널은 tabpanel role + 라벨 연결
    const panel = screen.getByRole('tabpanel');
    expect(panel).toHaveAttribute('aria-labelledby', 'docgen-tab-docgen');
  });

  it('ArrowRight 키로 다음 서브로 이동한다', async () => {
    const user = userEvent.setup();
    render(<DocGenHubSection />);
    screen.getByRole('tab', { name: '문서 생성' }).focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByTestId('sub-reports')).toBeVisible();
  });

  it('모든 탭의 aria-controls가 실재하는 tabpanel을 가리킨다 (DGH-1: dangling 방지)', () => {
    render(<DocGenHubSection />);
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(6);
    // 미방문 서브도 패널 컨테이너는 항상 렌더되므로 IDREF가 유효해야 한다.
    tabs.forEach(tab => {
      const panelId = tab.getAttribute('aria-controls');
      expect(panelId).toBeTruthy();
      expect(document.getElementById(panelId)).not.toBeNull();
    });
  });

  it('비활성 패널은 tabIndex=-1, 활성 패널만 0 (DGH-2: roving)', () => {
    render(<DocGenHubSection />);
    expect(document.getElementById('docgen-panel-docgen').getAttribute('tabindex')).toBe('0');
    expect(document.getElementById('docgen-panel-swut').getAttribute('tabindex')).toBe('-1'); // 미방문이어도 패널 존재
  });
});
