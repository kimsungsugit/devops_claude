import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * (R48-a) 계정·승인자 관리 블록.
 *
 * - 백엔드 admin 이 아니면 폼을 그리지 않고 그 사실을 적는다(localStorage 토글은 권한이 아니다).
 * - 목록은 `/api/auth/users` 서버 값 그대로. 승인자 0명이면 "아직 누구도 승인할 수 없다" 를 말한다.
 * - 생성은 `post()` 헬퍼(X9) — 성공 토스트는 2xx 뒤에만, 409 USER_EXISTS 는 사람이 읽는 문장.
 * - 역할 토글은 PUT, 삭제는 두 번 눌러야 한다.
 */
const mockToast = vi.fn();
vi.mock('../App.jsx', () => ({ useToast: () => mockToast }));

const mockApi = vi.fn();
const mockPost = vi.fn();
vi.mock('../api.js', () => ({ api: (...a) => mockApi(...a), post: (...a) => mockPost(...a) }));

let adminState = { isAdmin: true, loading: false };
vi.mock('../contexts/AdminContext.jsx', () => ({ useAdminMode: () => adminState }));

const { default: Block } = await import('../components/UserRoleAdminBlock.jsx');

function users(list, approvers = [], admins = ['hbrnd2']) {
  return { users: list, approvers, admins };
}

describe('UserRoleAdminBlock', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    adminState = { isAdmin: true, loading: false };
    mockApi.mockResolvedValue(users([
      { username: 'hbrnd2', is_admin: true, is_approver: false, must_change_password: false },
      { username: 'approver01', is_admin: false, is_approver: true, must_change_password: true },
    ], ['approver01']));
  });

  it('백엔드 admin 이 아니면 폼 대신 사유 — 조회도 하지 않는다', async () => {
    adminState = { isAdmin: false, loading: false };
    render(<Block />);
    expect(await screen.findByRole('status')).toHaveTextContent(/백엔드 admin/);
    expect(screen.queryByRole('form', { name: '계정 생성' })).toBeNull();
    expect(mockApi).not.toHaveBeenCalled();
  });

  it('목록은 서버 값 그대로 — 역할·임시 비밀번호 상태·승인자 수', async () => {
    render(<Block />);
    const table = await screen.findByRole('table', { name: '계정 목록' });
    expect(within(table).getByText('approver01')).toBeInTheDocument();
    expect(within(table).getByText(/임시 비밀번호\(변경 대기\)/)).toBeInTheDocument();
    expect(within(table).getByRole('button', { name: 'approver01 승인자 해제' })).toBeInTheDocument();
    expect(within(table).getByRole('button', { name: 'hbrnd2 승인자 부여' })).toBeInTheDocument();
    expect(screen.getByText(/승인자 1명 · admin 1명/)).toBeInTheDocument();
    expect(mockApi).toHaveBeenCalledWith('/api/auth/users');
  });

  it('승인자가 0명이면 4-eyes 가 성립하지 않는다고 말한다', async () => {
    mockApi.mockResolvedValue(users([{ username: 'hbrnd2', is_admin: true, is_approver: false, must_change_password: false }]));
    render(<Block />);
    expect(await screen.findByText(/승인자가 없어 아직 누구도 4-eyes 승인을 남길 수 없습니다/)).toBeInTheDocument();
  });

  it('생성: post 헬퍼로 보내고, 성공 토스트는 서버가 created 를 준 뒤에만', async () => {
    const user = userEvent.setup();
    mockPost.mockResolvedValue({ created: true, user: { username: 'r2', is_approver: true } });
    render(<Block />);
    await screen.findByRole('table', { name: '계정 목록' });
    await user.type(screen.getByLabelText('새 계정 이름'), 'r2');
    await user.type(screen.getByLabelText('임시 비밀번호'), 'temp_password_12');
    await user.click(screen.getByRole('button', { name: '계정 만들기' }));
    await waitFor(() => expect(mockPost).toHaveBeenCalledWith('/api/auth/users', {
      username: 'r2', temp_password: 'temp_password_12', approver: true, admin: false,
    }));
    await waitFor(() => expect(mockToast).toHaveBeenCalledWith('success', expect.stringMatching(/r2/)));
    expect(mockApi).toHaveBeenCalledTimes(2);   // 생성 뒤 재조회
  });

  it('생성 실패(409 USER_EXISTS)는 성공 토스트 없이 사람이 읽는 문장 + alert', async () => {
    const user = userEvent.setup();
    const err = new Error('Conflict'); err.status = 409; err.code = 'USER_EXISTS';
    mockPost.mockRejectedValue(err);
    render(<Block />);
    await screen.findByRole('table', { name: '계정 목록' });
    await user.type(screen.getByLabelText('새 계정 이름'), 'hbrnd2');
    await user.type(screen.getByLabelText('임시 비밀번호'), 'temp_password_12');
    await user.click(screen.getByRole('button', { name: '계정 만들기' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/이미 있는 계정입니다: hbrnd2/);
    expect(mockToast).not.toHaveBeenCalledWith('success', expect.anything());
  });

  it('짧은 임시 비밀번호는 서버에 보내지 않는다', async () => {
    const user = userEvent.setup();
    render(<Block />);
    await screen.findByRole('table', { name: '계정 목록' });
    await user.type(screen.getByLabelText('새 계정 이름'), 'r3');
    await user.type(screen.getByLabelText('임시 비밀번호'), 'short');
    await user.click(screen.getByRole('button', { name: '계정 만들기' }));
    expect(mockPost).not.toHaveBeenCalled();
    expect(mockToast).toHaveBeenCalledWith('warning', expect.stringMatching(/8자/));
  });

  it('역할 토글은 PUT 한 건 — 승인자 해제 → {approver:false}', async () => {
    const user = userEvent.setup();
    render(<Block />);
    const table = await screen.findByRole('table', { name: '계정 목록' });
    await user.click(within(table).getByRole('button', { name: 'approver01 승인자 해제' }));
    await waitFor(() => expect(mockApi).toHaveBeenCalledWith('/api/auth/users/approver01/roles',
      expect.objectContaining({ method: 'PUT', body: JSON.stringify({ approver: false }) })));
  });

  it('SELF_DEMOTE 는 사람이 읽는 문장으로', async () => {
    const user = userEvent.setup();
    mockApi.mockImplementation((path, opts) => {
      if (opts?.method === 'PUT') { const e = new Error('x'); e.code = 'SELF_DEMOTE'; e.status = 409; return Promise.reject(e); }
      return Promise.resolve(users([{ username: 'hbrnd2', is_admin: true, is_approver: false, must_change_password: false }]));
    });
    render(<Block />);
    const table = await screen.findByRole('table', { name: '계정 목록' });
    await user.click(within(table).getByRole('button', { name: 'hbrnd2 admin 해제' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(/자기 자신의 admin 권한은 해제할 수 없습니다/);
  });

  it('삭제는 두 번 — 첫 클릭은 무장만, DELETE 는 두 번째에', async () => {
    const user = userEvent.setup();
    render(<Block />);
    const table = await screen.findByRole('table', { name: '계정 목록' });
    await user.click(within(table).getByRole('button', { name: 'approver01 삭제' }));
    expect(mockApi).not.toHaveBeenCalledWith('/api/auth/users/approver01', expect.anything());
    await user.click(within(table).getByRole('button', { name: 'approver01 정말 삭제' }));
    await waitFor(() => expect(mockApi).toHaveBeenCalledWith('/api/auth/users/approver01', expect.objectContaining({ method: 'DELETE' })));
  });
});
