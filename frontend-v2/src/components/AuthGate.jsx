/**
 * 45차 C1 — Auth Gate.
 *
 * AuthContext.authenticated가 false면 Login 화면 렌더, true면 children (App) 렌더.
 * loading 중에는 splash 표시. must_change_password=true도 Login이 PW 변경 화면 처리.
 */
import { useAuth } from '../contexts/AuthContext.jsx';
import Login from '../views/Login.jsx';

export default function AuthGate({ children }) {
  const { authenticated, loading, mustChangePassword } = useAuth();

  if (loading) {
    return (
      <div className="auth-splash" aria-label="loading">
        <div className="auth-splash-inner">
          <div className="brand-icon" />
          <p>인증 확인 중...</p>
        </div>
      </div>
    );
  }

  if (!authenticated || mustChangePassword) {
    return <Login />;
  }

  return children;
}
