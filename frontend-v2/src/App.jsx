import { useState, useCallback, useEffect, createContext, useContext } from 'react';
import { getInitialTheme, saveTheme, loadJenkinsConfig, saveJenkinsConfig, getUsername, setUsername, fetchServerJenkinsConfig } from './api.js';
import Dashboard from './views/Dashboard.jsx';
import Detail from './views/Detail.jsx';
import Settings from './views/Settings.jsx';
import QualityDashboard from './views/QualityDashboard.jsx';
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
      baseUrl: '',
      username: '',
      token: '',
      cacheRoot: '.devops_pro_cache',
      buildSelector: 'lastSuccessfulBuild',
      verifyTls: true,
      ...saved,
    };
  });

  /* On mount: fetch server-managed config (shared across users). Overrides localStorage. */
  useEffect(() => {
    let cancelled = false;
    fetchServerJenkinsConfig().then((serverCfg) => {
      if (cancelled || !serverCfg) return;
      // Only override if server has a non-empty baseUrl
      if (serverCfg.baseUrl) {
        setCfg(prev => ({ ...prev, ...serverCfg }));
        saveJenkinsConfig({ ...serverCfg });
      }
    });
    return () => { cancelled = true; };
  }, []);

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

/* ── Status footer ─────────────────────────────────────────────────── */
function StatusFooter() {
  const { cfg } = useJenkinsCfg();
  const { selectedJob, analysisResult } = useJob();
  const [backendStatus, setBackendStatus] = useState(null);

  useEffect(() => {
    let mounted = true;
    const check = async () => {
      try {
        const res = await fetch('/api/health');
        if (!res.ok) throw new Error();
        const data = await res.json();
        if (mounted) setBackendStatus(data);
      } catch {
        if (mounted) setBackendStatus(null);
      }
    };
    check();
    const iv = setInterval(check, 30000);
    return () => { mounted = false; clearInterval(iv); };
  }, []);

  const jenkinsConnected = !!(cfg.baseUrl && cfg.username && cfg.token);
  const rd = analysisResult?.reportData;
  const kpis = rd?.kpis || {};
  const cov = kpis.coverage || {};
  const build = kpis.build || {};

  return (
    <footer className="app-footer">
      {/* Backend */}
      <div className="footer-item">
        <span className={`footer-dot ${backendStatus ? 'dot-ok' : 'dot-err'}`} />
        <span>Backend {backendStatus?.version ? `v${backendStatus.version}` : 'OFF'}</span>
      </div>

      <div className="footer-sep" />

      {/* Jenkins */}
      <div className="footer-item">
        <span className={`footer-dot ${jenkinsConnected ? 'dot-ok' : 'dot-warn'}`} />
        <span>{jenkinsConnected ? cfg.baseUrl.replace(/^https?:\/\//, '') : 'Jenkins 미연결'}</span>
      </div>

      <div className="footer-sep" />

      {/* Selected job */}
      <div className="footer-item">
        {selectedJob
          ? <span title={selectedJob.url}>{selectedJob.name}</span>
          : <span className="footer-muted">프로젝트 미선택</span>
        }
      </div>

      {/* Analysis result indicators */}
      {rd && (
        <>
          <div className="footer-sep" />
          <div className="footer-item">
            <span className={`footer-dot ${(build.result || rd.result) === 'SUCCESS' ? 'dot-ok' : 'dot-err'}`} />
            <span>#{build.build_number || rd.build_number}</span>
          </div>
          {cov.line_rate != null && (
            <>
              <div className="footer-sep" />
              <div className="footer-item">
                <span>Line {Math.round(cov.line_rate * 100)}%</span>
                {cov.branch_rate != null && <span> / Branch {Math.round(cov.branch_rate * 100)}%</span>}
              </div>
            </>
          )}
        </>
      )}

      <div style={{ flex: 1 }} />

      {/* User */}
      {getUsername() && (
        <>
          <div className="footer-item">
            <span style={{ fontSize: 10 }}>{getUsername()}</span>
          </div>
          <div className="footer-sep" />
        </>
      )}

      {/* Timestamp */}
      <div className="footer-item footer-muted">
        {new Date().toLocaleString('ko-KR', { hour: '2-digit', minute: '2-digit' })}
      </div>
    </footer>
  );
}

/* ── App root ───────────────────────────────────────────────────────── */
const ALL_TABS = [
  { id: 'dashboard', label: '대시보드' },
  { id: 'detail',    label: '프로젝트 결과' },
  { id: 'quality',   label: 'Quality', adminOnly: true },
  { id: 'settings',  label: '설정', adminOnly: true },
];

function isAdminMode() {
  return localStorage.getItem('devops_admin_mode') === 'true';
}

export default function App() {
  const [theme, setTheme] = useState(getInitialTheme);
  const [activeTab, setActiveTab] = useState('dashboard');
  const [userName, setUserName] = useState(getUsername);
  const [userInput, setUserInput] = useState('');
  const [adminMode, setAdminMode] = useState(isAdminMode);

  const TABS = adminMode ? ALL_TABS : ALL_TABS.filter(t => !t.adminOnly);

  useEffect(() => {
    document.body.setAttribute('data-theme', theme);
    saveTheme(theme);
  }, [theme]);

  // 관리자 모드 변경 감지 (Settings에서 토글 시)
  useEffect(() => {
    const onStorage = () => setAdminMode(isAdminMode());
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  // 관리자 모드 키보드 토글 (Ctrl+Shift+A)
  useEffect(() => {
    const onKey = (e) => {
      if (e.ctrlKey && e.shiftKey && (e.key === 'A' || e.key === 'a')) {
        e.preventDefault();
        const current = localStorage.getItem('devops_admin_mode') === 'true';
        const next = !current;
        localStorage.setItem('devops_admin_mode', String(next));
        setAdminMode(next);
        // 40차 C3 fix: same-tab AdminContext 즉시 반영 — custom event dispatch
        window.dispatchEvent(new Event('admin-mode-changed'));

        // 시각 피드백 (우측 상단에 일시적 배지)
        const indicator = document.createElement('div');
        indicator.textContent = next ? '✓ 관리자 모드 ON' : '✕ 관리자 모드 OFF';
        indicator.style.cssText = [
          'position:fixed', 'top:20px', 'right:20px',
          `background:${next ? 'var(--color-success, #22c55e)' : 'var(--text-muted, #6b7280)'}`,
          'color:white', 'padding:10px 18px',
          'border-radius:8px', 'z-index:9999',
          'font-weight:600', 'font-size:14px',
          'box-shadow:0 4px 12px rgba(0,0,0,0.25)',
          'transition:opacity 0.3s, transform 0.3s',
          'transform:translateY(0)',
        ].join(';');
        document.body.appendChild(indicator);
        setTimeout(() => {
          indicator.style.opacity = '0';
          indicator.style.transform = 'translateY(-10px)';
        }, 1800);
        setTimeout(() => { indicator.remove(); }, 2200);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, []);

  const toggleTheme = () => setTheme(t => t === 'light' ? 'dark' : 'light');

  // Show username prompt if not set
  if (!userName) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', background: 'var(--bg, #f5f5f5)' }}>
        <div style={{ background: 'var(--panel, #fff)', border: '1px solid var(--border, #e0e0e0)', borderRadius: 8, padding: 32, width: 360, textAlign: 'center' }}>
          <div style={{ fontSize: 28, marginBottom: 8 }}>ARIA</div>
          <div style={{ fontSize: 13, color: 'var(--text-muted, #666)', marginBottom: 20 }}>사용자 이름을 입력하세요 (내부망 식별용)</div>
          <input
            type="text"
            value={userInput}
            onChange={e => setUserInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && userInput.trim()) {
                setUsername(userInput.trim());
                setUserName(userInput.trim());
              }
            }}
            placeholder="예: hong_gildong"
            autoFocus
            style={{ width: '100%', padding: '10px 12px', fontSize: 14, border: '1px solid var(--border, #ccc)', borderRadius: 6, marginBottom: 12, boxSizing: 'border-box' }}
          />
          <button
            onClick={() => {
              if (userInput.trim()) {
                setUsername(userInput.trim());
                setUserName(userInput.trim());
              }
            }}
            disabled={!userInput.trim()}
            style={{ width: '100%', padding: '10px 0', fontSize: 14, fontWeight: 600, background: 'var(--accent, #0052CC)', color: 'var(--panel, #fff)', border: 'none', borderRadius: 6, cursor: 'pointer' }}
          >
            시작하기
          </button>
        </div>
      </div>
    );
  }

  return (
    <ToastProvider>
      <JenkinsCfgProvider>
        <JobProvider>
          <div className="app">
            <header className="app-header">
              <span className="app-brand">
                <span className="brand-icon" />
                ARIA
              </span>
              <div className="header-spacer" />
              <div className="header-actions">
                <button className="btn-icon" onClick={toggleTheme} title="테마 전환" aria-label="테마 전환">
                  {theme === 'dark' ? '☀️' : '🌙'}
                </button>
              </div>
            </header>

            <nav className="tab-bar" role="tablist">
              {TABS.map(t => (
                <button
                  key={t.id}
                  role="tab"
                  aria-selected={activeTab === t.id}
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
                    <Dashboard onGoDetail={(section) => { setActiveTab('detail'); if (section) setTimeout(() => window.__detailSection?.(section), 100); }} />
                  </div>
                  <div style={{ display: activeTab === 'detail' ? 'block' : 'none' }}>
                    <Detail />
                  </div>
                  <div style={{ display: activeTab === 'quality' ? 'block' : 'none' }}>
                    <QualityDashboard />
                  </div>
                  <div style={{ display: activeTab === 'settings' ? 'block' : 'none' }}>
                    <Settings />
                  </div>
                </ErrorBoundary>
              </div>
            </div>
            <StatusFooter />
          </div>
        </JobProvider>
      </JenkinsCfgProvider>
    </ToastProvider>
  );
}
