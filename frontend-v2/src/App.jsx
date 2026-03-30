import { useState, useCallback, useEffect, createContext, useContext } from 'react';
import { getInitialTheme, saveTheme, loadJenkinsConfig, saveJenkinsConfig } from './api.js';
import Dashboard from './views/Dashboard.jsx';
import Detail from './views/Detail.jsx';
import Settings from './views/Settings.jsx';
import ErrorBoundary from './components/ErrorBoundary.jsx';

/* ── Toast context ─────────────────────────────────────────────────── */
const ToastCtx = createContext(null);
export const useToast = () => useContext(ToastCtx);

function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const show = useCallback((type, message, duration = 3500) => {
    const id = Date.now() + Math.random();
    setToasts(p => [...p, { id, type, message, duration }]);
  }, []);
  const remove = useCallback((id) => setToasts(p => p.filter(t => t.id !== id)), []);

  const ICONS = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };

  return (
    <ToastCtx.Provider value={show}>
      {children}
      <div className="toast-container">
        {toasts.map(t => (
          <ToastItem key={t.id} toast={t} onClose={() => remove(t.id)} icons={ICONS} />
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

function ToastItem({ toast, onClose, icons }) {
  useEffect(() => {
    const timer = setTimeout(onClose, toast.duration || 3500);
    return () => clearTimeout(timer);
  }, [onClose, toast.duration]);
  return (
    <div className={`toast-item toast-${toast.type || 'info'}`} role="alert">
      <span className="toast-icon">{icons[toast.type] || icons.info}</span>
      <span className="toast-text">{toast.message}</span>
      <button className="toast-close" onClick={onClose} aria-label="닫기">×</button>
    </div>
  );
}

/* ── Jenkins config context ─────────────────────────────────────────── */
const JenkinsCfgCtx = createContext(null);
export const useJenkinsCfg = () => useContext(JenkinsCfgCtx);

function JenkinsCfgProvider({ children }) {
  const [cfg, setCfg] = useState(() => {
    const saved = loadJenkinsConfig();
    return {
      baseUrl: 'http://192.168.110.40:7000',
      username: 'hyunbo_it',
      token: '11c2025220b5af349b0b526d7c4d85304c',
      cacheRoot: '.devops_pro_cache',
      buildSelector: 'lastSuccessfulBuild',
      verifyTls: true,
      ...saved,
    };
  });

  const update = useCallback((patch) => {
    setCfg(prev => {
      const next = { ...prev, ...patch };
      saveJenkinsConfig(next);
      return next;
    });
  }, []);

  return (
    <JenkinsCfgCtx.Provider value={{ cfg, update }}>
      {children}
    </JenkinsCfgCtx.Provider>
  );
}

/* ── Selected job context (shared between Dashboard & Detail) ─────── */
const JobCtx = createContext(null);
export const useJob = () => useContext(JobCtx);

function JobProvider({ children }) {
  const [selectedJob, setSelectedJob] = useState(null);
  const [analysisResult, setAnalysisResult] = useState(null);

  return (
    <JobCtx.Provider value={{ selectedJob, setSelectedJob, analysisResult, setAnalysisResult }}>
      {children}
    </JobCtx.Provider>
  );
}

/* ── App root ───────────────────────────────────────────────────────── */
const TABS = [
  { id: 'dashboard', label: '대시보드' },
  { id: 'detail',    label: '세부 데이터' },
  { id: 'settings',  label: '설정' },
];

export default function App() {
  const [theme, setTheme] = useState(getInitialTheme);
  const [activeTab, setActiveTab] = useState('dashboard');

  useEffect(() => {
    document.body.setAttribute('data-theme', theme);
    saveTheme(theme);
  }, [theme]);

  const toggleTheme = () => setTheme(t => t === 'light' ? 'dark' : 'light');

  return (
    <ToastProvider>
      <JenkinsCfgProvider>
        <JobProvider>
          <div className="app">
            <header className="app-header">
              <span className="app-brand">
                <span className="brand-icon" />
                DevOps Release
              </span>
              <div className="header-spacer" />
              <div className="header-actions">
                <button className="btn-icon" onClick={toggleTheme} title="테마 전환">
                  {theme === 'dark' ? '☀️' : '🌙'}
                </button>
              </div>
            </header>

            <nav className="tab-bar">
              {TABS.map(t => (
                <button
                  key={t.id}
                  className={`tab-item${activeTab === t.id ? ' active' : ''}`}
                  onClick={() => setActiveTab(t.id)}
                >
                  {t.label}
                </button>
              ))}
            </nav>

            <div className="app-body">
              <div className="tab-content">
                <ErrorBoundary>
                  <div style={{ display: activeTab === 'dashboard' ? 'block' : 'none' }}>
                    <Dashboard onGoDetail={() => setActiveTab('detail')} />
                  </div>
                  <div style={{ display: activeTab === 'detail' ? 'block' : 'none' }}>
                    <Detail />
                  </div>
                  <div style={{ display: activeTab === 'settings' ? 'block' : 'none' }}>
                    <Settings />
                  </div>
                </ErrorBoundary>
              </div>
            </div>
          </div>
        </JobProvider>
      </JenkinsCfgProvider>
    </ToastProvider>
  );
}
