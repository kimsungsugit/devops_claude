import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import App from './App.jsx';
import { AdminProvider } from './contexts/AdminContext.jsx';
import { AuthProvider } from './contexts/AuthContext.jsx';
import AuthGate from './components/AuthGate.jsx';

// 45차 C1: AuthProvider가 AdminProvider 외곽 — 미인증 시 Login 화면 우선 노출.
// AuthGate가 authenticated=false면 <Login> 렌더, true면 children 렌더.
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider>
      <AdminProvider>
        <AuthGate>
          <App />
        </AuthGate>
      </AdminProvider>
    </AuthProvider>
  </StrictMode>
);
