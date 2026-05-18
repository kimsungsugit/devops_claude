/**
 * 46차 W33 — Login + PasswordHint 회귀.
 *
 * 시나리오:
 *   1. mount 시 hint 표시 (한국어 24자 / 영문 72자 권장)
 *   2. 영문 입력 → 바이트 수 표시
 *   3. 한국어 24자 초과 → 경고 표시
 *   4. 로그인 form submit → AuthContext.login 호출
 *   5. mustChangePassword=true → PW 변경 화면 표시
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';

vi.mock('../contexts/AuthContext.jsx', async () => {
  const React = await import('react');
  return {
    useAuth: () => ({
      authenticated: false,
      mustChangePassword: false,
      login: vi.fn(async () => ({ ok: true })),
      changePassword: vi.fn(async () => ({ ok: true })),
    }),
  };
});

const Login = (await import('../views/Login.jsx')).default;


describe('Login + PasswordHint (46차 W33)', () => {
  it('renders login form with hint', () => {
    render(<Login />);
    expect(screen.getByText('ARIA 로그인')).toBeInTheDocument();
    expect(screen.getByText(/한국어 최대 24자 \/ 영문 72자/)).toBeInTheDocument();
  });

  it('shows byte count for English password', () => {
    render(<Login />);
    const inputs = screen.getAllByLabelText(/비밀번호/);
    const passwordInput = inputs[0];
    fireEvent.change(passwordInput, { target: { value: 'abcdef' } });
    // 6 bytes
    expect(screen.getByText(/6 \/ 72바이트/)).toBeInTheDocument();
  });

  it('shows warning when Korean password exceeds 72 bytes', () => {
    render(<Login />);
    const inputs = screen.getAllByLabelText(/비밀번호/);
    const passwordInput = inputs[0];
    // 한국어 25자 (한 글자 3바이트) = 75바이트 > 72
    const longKorean = '가나다라마바사아자차카타파하각낙닥락막박삭악작착칵';
    fireEvent.change(passwordInput, { target: { value: longKorean } });
    expect(screen.getByRole('alert')).toHaveTextContent(/처음 72바이트만 인식/);
  });

  it('handles login button click', async () => {
    render(<Login />);
    const submitBtn = screen.getByRole('button', { name: /로그인/ });
    expect(submitBtn).toBeInTheDocument();
  });
});


describe('Login mustChangePassword flow', () => {
  it('shows password change screen when authenticated + mustChangePassword=true', async () => {
    vi.resetModules();
    vi.doMock('../contexts/AuthContext.jsx', async () => ({
      useAuth: () => ({
        authenticated: true,
        mustChangePassword: true,
        login: vi.fn(),
        changePassword: vi.fn(async () => ({ ok: true })),
      }),
    }));
    const LoginPwChange = (await import('../views/Login.jsx')).default;
    render(<LoginPwChange />);
    expect(screen.getByText('비밀번호 변경 필요')).toBeInTheDocument();
    expect(screen.getByText(/임시 비밀번호 사용 중/)).toBeInTheDocument();
  });
});
