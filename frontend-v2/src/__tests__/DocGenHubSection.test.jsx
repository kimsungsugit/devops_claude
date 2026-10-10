/**
 * DocGenHubSection 단위 테스트
 *
 * 검증:
 * - 7개 생성 종류 옵션 세그먼트 렌더 (2026-08-07: '생성 현황' 보드가 맨 앞에 추가)
 * - 기본 서브는 status, docgen 은 **함께 마운트**(숨김), Sw* 는 lazy(미마운트)
 * - 서브 클릭 시 해당 서브 표시 + 이전 서브는 keep-alive(숨김 유지)
 * - initialSub prop으로 외부 서브 지정
 * - 보드 ↔ 생성 탭 배선: 진행 상태 공유(onGenState) + 생성 함수 등록(onRegisterGenerate)
 *
 * 자식 섹션은 mock(단위 격리) — useToast/useAdminMode 등 컨텍스트 의존 차단.
 *
 * ⚠ `docgen` 이 초기 마운트되는 건 **의도**다. 보드의 '생성' 버튼은 DocGenSection 이
 * ref 로 등록한 `generateDoc` 을 호출하는데, 그 컴포넌트가 마운트돼 있지 않으면 등록이
 * 없어 버튼이 죽는다. 이 파일의 `keep-alive` 테스트가 Sw* 로 검증 대상을 옮긴 이유다.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../components/sections/DocGenStatusBoard.jsx', () => ({ default: () => <div data-testid="sub-status">status</div> }));
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

  it('7개 옵션 세그먼트를 렌더한다', () => {
    render(<DocGenHubSection />);
    ['생성 현황', '문서 생성', '리포트', 'SwUT', 'SwIT', 'SwSA', '통합 결과'].forEach(label => {
      expect(screen.getByRole('tab', { name: label })).toBeInTheDocument();
    });
  });

  it('생성 현황이 맨 앞 탭이다 (사용자 요구: 맨 앞에서 생성, 나머지는 세부)', () => {
    render(<DocGenHubSection />);
    expect(screen.getAllByRole('tab')[0]).toHaveTextContent('생성 현황');
  });

  it('기본 서브는 생성 현황이고 Sw* 는 마운트되지 않는다', () => {
    render(<DocGenHubSection />);
    expect(screen.getByTestId('sub-status')).toBeVisible();
    expect(screen.queryByTestId('sub-swut')).toBeNull();
    expect(screen.queryByTestId('sub-swreport')).toBeNull();
  });

  it('docgen 은 첫 렌더부터 마운트되지만 숨겨져 있다 (보드의 생성 버튼 배선)', () => {
    render(<DocGenHubSection />);
    // 마운트는 되어 있어야 generateDoc 등록이 일어난다…
    expect(screen.getByTestId('sub-docgen')).toBeInTheDocument();
    // …하지만 보이면 안 된다(활성 탭은 status).
    expect(screen.getByTestId('sub-docgen')).not.toBeVisible();
  });

  it('SwUT 클릭 시 swut 서브를 표시하고 status는 숨김 유지한다(keep-alive)', async () => {
    const user = userEvent.setup();
    render(<DocGenHubSection />);
    await user.click(screen.getByRole('tab', { name: 'SwUT' }));
    expect(screen.getByTestId('sub-swut')).toBeVisible();
    // status는 unmount되지 않고 DOM에 남아 숨겨진다.
    expect(screen.getByTestId('sub-status')).not.toBeVisible();
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
    // 초기 마운트 시 status 통지
    expect(onSubChange).toHaveBeenCalledWith('status', '생성 현황');
    onSubChange.mockClear();
    await user.click(screen.getByRole('tab', { name: 'SwIT' }));
    expect(onSubChange).toHaveBeenCalledWith('swit', 'SwIT');
  });

  it('탭에 ARIA 결합(aria-controls/tabpanel) + roving tabIndex가 적용된다', () => {
    render(<DocGenHubSection />);
    const active = screen.getByRole('tab', { name: '생성 현황' });
    expect(active).toHaveAttribute('aria-controls', 'docgen-panel-status');
    expect(active).toHaveAttribute('tabindex', '0');
    const inactive = screen.getByRole('tab', { name: 'SwUT' });
    expect(inactive).toHaveAttribute('tabindex', '-1');
    // 활성 패널은 tabpanel role + 라벨 연결
    const panel = screen.getByRole('tabpanel');
    expect(panel).toHaveAttribute('aria-labelledby', 'docgen-tab-status');
  });

  it('ArrowRight 키로 다음 서브로 이동한다', async () => {
    const user = userEvent.setup();
    render(<DocGenHubSection />);
    screen.getByRole('tab', { name: '생성 현황' }).focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByTestId('sub-docgen')).toBeVisible();
  });

  it('모든 탭의 aria-controls가 실재하는 tabpanel을 가리킨다 (DGH-1: dangling 방지)', () => {
    render(<DocGenHubSection />);
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(7);
    // 미방문 서브도 패널 컨테이너는 항상 렌더되므로 IDREF가 유효해야 한다.
    tabs.forEach(tab => {
      const panelId = tab.getAttribute('aria-controls');
      expect(panelId).toBeTruthy();
      expect(document.getElementById(panelId)).not.toBeNull();
    });
  });

  it('비활성 패널은 tabIndex=-1, 활성 패널만 0 (DGH-2: roving)', () => {
    render(<DocGenHubSection />);
    expect(document.getElementById('docgen-panel-status').getAttribute('tabindex')).toBe('0');
    expect(document.getElementById('docgen-panel-swut').getAttribute('tabindex')).toBe('-1'); // 미방문이어도 패널 존재
  });
});

/**
 * 보드 ↔ 생성 탭 배선.
 *
 * 여기서 mock 을 다시 만드는 이유: 위 describe 의 mock 은 props 를 버리는 더미라
 * "보드가 진행 상태를 실제로 받는가" 를 확인할 수 없다. 배선은 화면 배치와 달리
 * **끊어져도 아무 에러가 안 나므로**(버튼이 조용히 죽을 뿐) 별도로 겨눈다.
 */
describe('DocGenHubSection — 보드/생성 탭 배선', () => {
  it('생성 탭이 등록한 함수를 보드의 생성 요청이 호출한다', async () => {
    vi.resetModules();
    const generateSpy = vi.fn();

    vi.doMock('../components/sections/DocGenSection.jsx', () => ({
      default: ({ onRegisterGenerate }) => {
        // 실제 컴포넌트처럼 마운트 시 자기 함수를 등록한다.
        if (onRegisterGenerate) onRegisterGenerate(generateSpy);
        return <div data-testid="sub-docgen">docgen</div>;
      },
    }));
    vi.doMock('../components/sections/DocGenStatusBoard.jsx', () => ({
      default: ({ onGenerate, genState }) => (
        <div data-testid="sub-status">
          <button type="button" onClick={() => onGenerate('uds')}>보드-UDS-생성</button>
          <span data-testid="board-busy">{genState?.docType || 'idle'}</span>
        </div>
      ),
    }));
    for (const [path, id] of [
      ['ReportGenSection', 'reports'], ['SwUTBuildSection', 'swut'],
      ['SwITBuildSection', 'swit'], ['SwSABuildSection', 'swsa'],
      ['SwReportSummarySection', 'swreport'],
    ]) {
      vi.doMock(`../components/sections/${path}.jsx`, () => ({
        default: () => <div data-testid={`sub-${id}`}>{id}</div>,
      }));
    }

    const { default: Hub } = await import('../components/sections/DocGenHubSection.jsx');
    const user = userEvent.setup();
    render(<Hub />);

    await user.click(screen.getByRole('button', { name: '보드-UDS-생성' }));
    expect(generateSpy).toHaveBeenCalledWith('uds');
  });

  it('생성 탭이 올린 진행 상태가 보드로 내려간다', async () => {
    vi.resetModules();

    vi.doMock('../components/sections/DocGenSection.jsx', () => ({
      default: ({ onGenState }) => (
        <div data-testid="sub-docgen">
          <button type="button" onClick={() => onGenState({ docType: 'sts', stage: '진행', progress: 42, result: null })}>
            상태-올리기
          </button>
        </div>
      ),
    }));
    vi.doMock('../components/sections/DocGenStatusBoard.jsx', () => ({
      default: ({ genState }) => <span data-testid="board-busy">{genState?.docType || 'idle'}</span>,
    }));
    for (const [path, id] of [
      ['ReportGenSection', 'reports'], ['SwUTBuildSection', 'swut'],
      ['SwITBuildSection', 'swit'], ['SwSABuildSection', 'swsa'],
      ['SwReportSummarySection', 'swreport'],
    ]) {
      vi.doMock(`../components/sections/${path}.jsx`, () => ({
        default: () => <div data-testid={`sub-${id}`}>{id}</div>,
      }));
    }

    const { default: Hub } = await import('../components/sections/DocGenHubSection.jsx');
    const user = userEvent.setup();
    render(<Hub />);

    expect(screen.getByTestId('board-busy')).toHaveTextContent('idle');
    // docgen 패널은 display:none 이라 getByRole 이 못 찾는다(접근성 트리에서 배제).
    // 실제 사용자도 생성 탭에서 생성을 시작하므로 탭을 전환한 뒤 누른다.
    await user.click(screen.getByRole('tab', { name: '문서 생성' }));
    await user.click(screen.getByRole('button', { name: '상태-올리기' }));
    // 보드는 이제 숨겨져 있지만 마운트는 유지된다(keep-alive) — getByTestId 는 가시성을 안 본다.
    expect(screen.getByTestId('board-busy')).toHaveTextContent('sts');
  });
});
