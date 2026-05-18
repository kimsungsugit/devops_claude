/**
 * 45차 C1 — 로그인 화면.
 *
 * 미인증 시 App.jsx가 이 화면을 우선 렌더. 로그인 성공 → AuthContext가 state 갱신 →
 * App.jsx가 본 화면을 unmount하고 메인 UI 렌더. must_change_password=true면 PW 변경
 * 강제 화면.
 */
import { useState } from 'react';
import { useAuth } from '../contexts/AuthContext.jsx';

// 46차 W33: bcrypt 72-byte limit 정책 — 한국어 24자 / 영문 72자.
// 입력 UTF-8 바이트 수 계산하여 hint 표시 + 경고.
const BCRYPT_BYTE_LIMIT = 72;

function utf8ByteLength(s) {
  // TextEncoder가 jsdom + 모든 모던 브라우저에서 지원
  if (typeof TextEncoder !== 'undefined') {
    return new TextEncoder().encode(s).length;
  }
  // fallback (구형 브라우저): blob 측정
  try {
    return new Blob([s]).size;
  } catch (_) {
    return s.length;  // 추정 (한국어 underestimate)
  }
}

function PasswordHint({ password }) {
  const bytes = utf8ByteLength(password);
  // 47차 I7: 다국어 byte 가이드 tooltip — 입력 안 됐을 때만 노출
  if (!password) {
    return (
      <small
        className="login-hint-detail"
        title={
          'UTF-8 바이트 기준:\n' +
          '  영문/숫자/기호: 1바이트\n' +
          '  한국어/일본어/중국어: 3바이트\n' +
          '  이모지(😀): 4바이트\n' +
          'bcrypt는 72바이트 초과 시 truncate'
        }
      >
        영문 72자 / 한국어·일본어 24자 / 이모지 18자 이하 권장 (bcrypt 정책)
      </small>
    );
  }
  if (bytes > BCRYPT_BYTE_LIMIT) {
    return (
      <small className="login-hint-warn" role="alert">
        ⚠ {bytes}바이트 입력 — 처음 {BCRYPT_BYTE_LIMIT}바이트만 인식됩니다
      </small>
    );
  }
  return (
    <small className="login-hint-detail">
      {bytes} / {BCRYPT_BYTE_LIMIT}바이트
    </small>
  );
}

export default function Login() {
  const { login, mustChangePassword, authenticated, changePassword } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // PW 변경 강제 화면
  if (authenticated && mustChangePassword) {
    const handleChangePw = async (e) => {
      e.preventDefault();
      setError('');
      if (newPassword.length < 8) {
        setError('비밀번호는 8자 이상이어야 합니다');
        return;
      }
      if (newPassword !== confirmPassword) {
        setError('비밀번호 확인이 일치하지 않습니다');
        return;
      }
      setSubmitting(true);
      try {
        const r = await changePassword(newPassword);
        if (!r.ok) setError(r.error || '비밀번호 변경 실패');
      } finally {
        setSubmitting(false);
      }
    };
    return (
      <div className="login-page">
        <div className="login-card">
          <h1 className="login-title">비밀번호 변경 필요</h1>
          <p className="login-subtitle">임시 비밀번호 사용 중 — 새 비밀번호로 변경하세요.</p>
          <form onSubmit={handleChangePw}>
            <label>
              <span>새 비밀번호</span>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                minLength={8}
                maxLength={100}
                required
                autoFocus
                autoComplete="new-password"
              />
              <PasswordHint password={newPassword} />
            </label>
            <label>
              <span>비밀번호 확인</span>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                minLength={8}
                maxLength={100}
                required
                autoComplete="new-password"
              />
            </label>
            {error && <div className="login-error">{error}</div>}
            <button type="submit" disabled={submitting}>
              {submitting ? '변경 중...' : '비밀번호 변경'}
            </button>
          </form>
        </div>
      </div>
    );
  }

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    if (!username.trim() || !password) {
      setError('사용자명과 비밀번호를 입력하세요');
      return;
    }
    setSubmitting(true);
    try {
      const r = await login(username.trim(), password);
      if (!r.ok) {
        setError(r.error || '로그인 실패');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <h1 className="login-title">ARIA 로그인</h1>
        <p className="login-subtitle">사용자명과 비밀번호로 로그인</p>
        <form onSubmit={handleLogin}>
          <label>
            <span>사용자명</span>
            <input
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              autoFocus
              autoComplete="username"
              maxLength={100}
            />
          </label>
          <label>
            <span>비밀번호</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="current-password"
              maxLength={100}
            />
            <PasswordHint password={password} />
          </label>
          {error && <div className="login-error" role="alert">{error}</div>}
          <button type="submit" disabled={submitting}>
            {submitting ? '로그인 중...' : '로그인'}
          </button>
        </form>
        <p className="login-hint">
          첫 사용자: 관리자에게 임시 비밀번호 요청 → 첫 로그인 후 변경
        </p>
      </div>
    </div>
  );
}
