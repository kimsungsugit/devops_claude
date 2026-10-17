/**
 * 탭 표시 권한의 출처 — §6 후보 24 파생 정책 결정.
 *
 * 예전엔 `quality`/`settings` 둘 다 `adminOnly: true` 로 묶여 **localStorage 토글**
 * (Ctrl+Shift+A) 하나가 판정했다. 실권한은 backend `admin_users.json` 이라 양방향으로
 * 어긋난다. 통째로 backend 로 옮기는 것도 오답이라 **탭별로** 가른다:
 *
 *   quality  → backend `is_admin`  (호출 3종이 전부 라우터 레벨 `require_admin` 이라
 *                                   비관리자에게 여는 건 100% false affordance)
 *   settings → localStorage        (`health.py:233-239` 가 "비-admin 이 직접 전환해야
 *                                   한다" 고 명시한 file-mode 를 담고 있다)
 *
 * ⚠ 계획서는 "표시 authority 변경 → 백엔드 장애 시 admin 이 UI 에서 잠긴다" 를 우려로
 *   적었는데, 실측하면 그 우려가 성립하는 건 **설정 탭 쪽**이고 Quality 는 반대다.
 * ⚠ 보안 경계가 아니라 UX/일관성 결정이다 — 실제 방어선은 backend `require_admin` 이고
 *   이 변경은 그걸 건드리지 않는다.
 */
import { render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

vi.mock('../api.js', () => ({
  getInitialTheme: () => 'light',
  saveTheme: vi.fn(),
  loadJenkinsConfig: () => ({}),
  saveJenkinsConfig: vi.fn(),
  getUsername: () => 'testuser',
  setUsername: vi.fn(),
  fetchServerJenkinsConfig: () => Promise.resolve(null),
  saveServerJenkinsConfig: vi.fn(() => Promise.resolve({ ok: true })),
  // ⚠ `AdminContext.jsx:11` 이 이걸 import 한다. 빠뜨리면 provider 가 죽어
  //    "비관리자" 기대가 **엉뚱한 이유로** 통과한다(공허 통과).
  //    (2026-08-06: getAccessToken 직접 조립 → authHeaders() 단일 출처로 이관)
  authHeaders: () => ({ 'X-User': 'testuser' }),
}));

vi.mock('../views/Dashboard.jsx', () => ({
  default: () => <div data-testid="dashboard">Dashboard</div>,
}));
vi.mock('../views/Detail.jsx', () => ({
  default: () => <div data-testid="detail">Detail</div>,
}));
vi.mock('../views/Settings.jsx', () => ({
  default: () => <div data-testid="settings">Settings</div>,
}));
vi.mock('../components/sections/QualityGateSection.jsx', () => ({
  default: () => <div data-testid="quality">Quality</div>,
}));

const { AdminProvider } = await import('../contexts/AdminContext.jsx');
const App = (await import('../App.jsx')).default;

/** `/api/auth/me` 응답만 제어하고 나머지는 통과시킨다. */
function mockAuthMe({ isAdmin, fail = false, delayMs = 0 }) {
  globalThis.fetch = vi.fn((url) => {
    if (String(url).includes('/api/auth/me')) {
      if (fail) return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) });
      const body = { is_admin: isAdmin, username: 'testuser', authenticated: true };
      const res = { ok: true, json: () => Promise.resolve(body) };
      return delayMs
        ? new Promise((r) => setTimeout(() => r(res), delayMs))
        : Promise.resolve(res);
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}), text: () => Promise.resolve('') });
  });
}

function renderApp() {
  return render(<AdminProvider><App /></AdminProvider>);
}

const tab = (label) => screen.queryByRole('tab', { name: label });

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});
afterEach(() => {
  localStorage.clear();
});

describe('탭별 권한 출처 — 4조합 진리표', () => {
  it('localStorage=F, backend=F → 둘 다 숨김', async () => {
    mockAuthMe({ isAdmin: false });
    renderApp();
    await waitFor(() => expect(tab('품질 관제')).toBeNull());
    expect(tab('설정')).toBeNull();
  });

  it('localStorage=T, backend=F → 설정만 보인다 (Quality 는 false affordance 였다)', async () => {
    localStorage.setItem('devops_admin_mode', 'true');
    mockAuthMe({ isAdmin: false });
    renderApp();
    await waitFor(() => expect(tab('품질 관제')).toBeNull());
    expect(tab('설정')).not.toBeNull();
  });

  it('localStorage=F, backend=T → Quality 만 보인다', async () => {
    mockAuthMe({ isAdmin: true });
    renderApp();
    await waitFor(() => expect(tab('품질 관제')).not.toBeNull());
    expect(tab('설정')).toBeNull();
  });

  it('localStorage=T, backend=T → 둘 다 보인다', async () => {
    localStorage.setItem('devops_admin_mode', 'true');
    mockAuthMe({ isAdmin: true });
    renderApp();
    await waitFor(() => expect(tab('품질 관제')).not.toBeNull());
    expect(tab('설정')).not.toBeNull();
  });
});

describe('백엔드 장애 시', () => {
  it('설정 탭은 잠기지 않는다 — localStorage 가 authority', async () => {
    localStorage.setItem('devops_admin_mode', 'true');
    mockAuthMe({ isAdmin: false, fail: true });
    renderApp();
    // `/api/auth/me` 401 → AdminContext 는 isAdmin:false 로 접는다.
    await waitFor(() => expect(tab('품질 관제')).toBeNull());
    expect(tab('설정')).not.toBeNull();
  });
});

describe('loading 축', () => {
  it('응답 전에는 localStorage 힌트를 쓴다 — 진짜 admin 이 탭 튐을 겪지 않게', async () => {
    localStorage.setItem('devops_admin_mode', 'true');
    mockAuthMe({ isAdmin: true, delayMs: 50 });
    renderApp();
    // 아직 loading — 힌트로 이미 보인다
    expect(tab('품질 관제')).not.toBeNull();
    await waitFor(() => expect(tab('품질 관제')).not.toBeNull());
  });

  it('힌트가 틀렸으면 응답 후 정정된다', async () => {
    localStorage.setItem('devops_admin_mode', 'true');
    mockAuthMe({ isAdmin: false, delayMs: 20 });
    renderApp();
    expect(tab('품질 관제')).not.toBeNull();      // 힌트
    await waitFor(() => expect(tab('품질 관제')).toBeNull());  // 확정
  });

  it('힌트가 없으면 응답 전에는 보이지 않는다', async () => {
    // ⚠ 이 대조군이 없으면 "loading 중 무조건 표시" 도 통과한다(뮤테이션 M4 로 확인).
    //    그건 비관리자에게 한 프레임 동안 admin 탭을 보여 주는 것이고, 후보 24 가
    //    없앤 false affordance 가 축소된 형태로 되살아난다.
    mockAuthMe({ isAdmin: true, delayMs: 50 });
    renderApp();
    expect(tab('품질 관제')).toBeNull();          // 힌트 없음 → 표시 안 함
    await waitFor(() => expect(tab('품질 관제')).not.toBeNull());  // 확정 후 표시
  });
});

describe('권한이 사라지면 보고 있던 뷰도 닫힌다', () => {
  it('Quality 를 보는 중 backend 권한이 false 로 뒤집히면 대시보드로 돌아간다', async () => {
    localStorage.setItem('devops_admin_mode', 'true');
    mockAuthMe({ isAdmin: true });
    renderApp();
    await waitFor(() => expect(tab('품질 관제')).not.toBeNull());

    const { default: userEvent } = await import('@testing-library/user-event');
    await userEvent.click(tab('품질 관제'));
    expect(screen.getByTestId('quality')).toBeVisible();

    // 토큰 만료·백엔드 재기동 — AdminContext 가 isAdmin:false 로 접는다
    mockAuthMe({ isAdmin: false });
    await act(async () => {
      window.dispatchEvent(new Event('admin-mode-changed'));
    });

    await waitFor(() => expect(tab('품질 관제')).toBeNull());
    // ⚠ 탭 버튼만 사라지고 화면이 남으면 안 된다 — 렌더 중 조정으로 활성 탭을 돌린다.
    await waitFor(() => expect(screen.getByTestId('quality')).not.toBeVisible());
    expect(screen.getByTestId('dashboard')).toBeVisible();
  });
});
