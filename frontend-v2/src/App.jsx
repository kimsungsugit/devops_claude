import { useState, useCallback, useEffect, createContext, useContext } from 'react';
import { getInitialTheme, saveTheme, loadJenkinsConfig, saveJenkinsConfig, getUsername, setUsername, fetchServerJenkinsConfig } from './api.js';
import Dashboard from './views/Dashboard.jsx';
import Detail from './views/Detail.jsx';
import Settings from './views/Settings.jsx';
import QualityGateSection from './components/sections/QualityGateSection.jsx';
import ErrorBoundary from './components/ErrorBoundary.jsx';
import { useAdminMode } from './contexts/AdminContext.jsx';

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
  // exit 애니메이션(0.2s)을 위해 제거 전 leaving 단계를 둔다 — 자동 소멸·수동 닫기 공통.
  const [leaving, setLeaving] = useState(false);
  const beginClose = useCallback(() => setLeaving(true), []);
  // 자동 소멸 타이머 — duration 후 exit 시작(beginClose는 안정 참조라 재설정 없음).
  useEffect(() => {
    const timer = setTimeout(beginClose, toast.duration || 3500);
    return () => clearTimeout(timer);
  }, [beginClose, toast.duration]);
  // leaving 진입 시 애니메이션 길이(200ms)만큼 대기 후 부모에서 실제 제거.
  useEffect(() => {
    if (!leaving) return undefined;
    const t = setTimeout(onClose, 200);
    return () => clearTimeout(t);
  }, [leaving, onClose]);
  return (
    <div className={`toast-item toast-${toast.type || 'info'}${leaving ? ' toast-leaving' : ''}`} role="alert">
      <span className="toast-icon">{icons[toast.type] || icons.info}</span>
      <span className="toast-text">{toast.message}</span>
      <button className="toast-close" onClick={beginClose} aria-label="닫기">×</button>
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
/**
 * 탭 표시 권한의 **출처**(§6 후보 24 파생 정책 결정, 2026-08-04).
 *
 * 예전엔 둘 다 `adminOnly: true` 로 묶여 **localStorage 토글(Ctrl+Shift+A)** 하나가
 * 판정했다. 실권한은 backend `admin_users.json` 이라 양방향으로 어긋난다.
 * 통째로 backend 로 옮기는 것(B)도 오답이다 — 두 탭의 성질이 다르다:
 *
 *   `backend` — 품질 관제: **전역**(모든 프로젝트) 이력·추세·정책을 보는 운영 화면이다.
 *               ⚠ 2026-08-07 에 근거가 바뀌었다. 예전 근거는 "`/api/quality/*` 가
 *               라우터 전체 `require_admin` 이라 열어도 403 뿐 = false affordance" 였는데,
 *               그 라우터는 이제 **조회 개방**(`require_user`)이다. 그래도 탭을 admin 에
 *               두는 이유는 다른 데 있다 — 일반 사용자에게 필요한 건 *자기 프로젝트의*
 *               게이트이고 그건 `프로젝트 결과 > 🚦 품질 게이트` 가 (같은 컴포넌트로)
 *               이미 열려 있다. 전 프로젝트 이력을 한 화면에 늘어놓는 건 운영 성격이다.
 *   `local`   — 설정: `health.py:233-239` 가 *"비-admin 이 직접 전환해야 한다"* 고
 *               명시한 file-mode 를 담고 있고, `localStorage` 로만 도는 핸들러도 있다
 *               (doc paths·shared inputs·quality 설정). backend authority 로 옮기면
 *               `/api/auth/me` 가 실패하는 순간(`AdminContext` 는 실패를
 *               `isAdmin:false` 로 접는다) **실제로 쓰이는 기능이 잠긴다**.
 *
 * ⚠ 계획서는 "표시 authority 변경 → 백엔드 장애 시 admin 이 UI 에서 잠긴다" 를 우려로
 *   적었는데, 실측하면 그 우려가 성립하는 건 **설정 탭 쪽**이고 Quality 는 반대다.
 * ⚠ 이건 보안 경계가 아니라 **UX/일관성** 결정이다. 실제 방어선은 backend
 *   `require_admin` 이고 이 커밋은 그걸 건드리지 않는다.
 */
const ALL_TABS = [
  { id: 'dashboard', label: '대시보드' },
  { id: 'detail',    label: '프로젝트 결과' },
  { id: 'quality',   label: '품질 관제', authority: 'backend' },
  { id: 'settings',  label: '설정', authority: 'local' },
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
  // backend 실권한 — `AdminProvider` 는 `main.jsx:11-20` 에서 App **상위**에 있다.
  const { isAdmin: backendIsAdmin, loading: adminLoading } = useAdminMode();

  // ⚠ `adminLoading` 동안 backend 판정을 쓰면 **진짜 admin 도 RTT 만큼 탭이 없다가
  //   튀어나온다**(초기값이 `isAdmin:false, loading:true`). 그동안은 사용자가 직접 켠
  //   localStorage 토글을 힌트로 쓰고, 응답이 오면 backend 로 확정한다.
  //   표시만의 문제다 — 실제 접근은 backend `require_admin` 이 막는다.
  const canSeeBackendAdminTab = adminLoading ? adminMode : backendIsAdmin;
  const TABS = ALL_TABS.filter((t) => {
    if (t.authority === 'backend') return canSeeBackendAdminTab;
    if (t.authority === 'local') return adminMode;
    return true;
  });

  // ⚠ 뷰는 **처음 열어 본 뒤에만** 마운트한다(그 뒤로는 keep-alive — display 토글).
  //
  // 예전엔 4뷰가 전부 **항상 마운트**됐다(조건부 언마운트 0건). 그래서 품질 탭이
  // 보이지 않는 사용자에게도 그 뷰의 mount effect 가 즉시 발화하고, `/api/quality/*` 가
  // 당시엔 라우터 전체 admin 전용이라 403 을 받아 **매 앱 로드마다 빨간 에러 토스트 +
  // '데이터 로드 실패' 패널**이 떴다. 사용자가 아무것도 안 눌렀는데 실패가 보인다.
  //
  // (2026-08-07: 그 라우터는 조회 개방됐지만 lazy 마운트는 그대로 둔다 — 403 이 아니어도
  //  안 보는 화면 때문에 매 로드마다 요청을 두 번 더 보낼 이유가 없다.)
  //
  // Detail 이 섹션에 쓰는 visited-lazy 와 같은 방식이다(`Detail.jsx` 의 visited).
  // 부수 효과로 admin 도 Quality 탭을 안 열면 요청이 0건이 된다.
  // 구현은 `Detail.jsx:67-74`(섹션 keep-alive)와 **같은 패턴**을 쓴다 — 첫 방문에만
  // 한 번 추가되고 `has()` 로 막혀 있어 재렌더가 누적되지 않는다.
  const [visited, setVisited] = useState(() => new Set([activeTab]));
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 활성 탭을 방문 기록에 누적(keep-alive 파생 집합). Detail.jsx:71-74 와 동일 패턴
    setVisited((prev) => (prev.has(activeTab) ? prev : new Set(prev).add(activeTab)));
  }, [activeTab]);

  // ⚠ 탭 목록에서 빠지는 것만으로는 **뷰가 안 닫힌다.** `isMounted` 는 `activeTab` 과
  //   `visited` 만 보고, 렌더 조건도 `display: activeTab === id` 다. 그래서 Quality 를
  //   보고 있는 중에 backend `isAdmin` 이 false 로 뒤집히면(토큰 만료·백엔드 재기동 후
  //   `/api/auth/me` 실패 → `AdminContext` 가 `isAdmin:false` 로 접는다)
  //   **탭 버튼만 사라지고 화면은 그대로 남는다.** 현행 localStorage 판정에선 사용자가
  //   직접 토글해야 생기는 상태지만, backend authority 로 옮기면 조작 없이 발생한다.
  //
  //   ⚠ effect 가 아니라 **렌더 중 조정**이다(React 공식 "prop/파생 변화에 state 맞추기").
  //     effect 로 하면 한 프레임 동안 권한 없는 화면이 그대로 보이고, effect 안 setState 는
  //     캐스케이딩 렌더로 eslint 게이트(`react-hooks/set-state-in-effect`)에도 걸린다.
  //     같은 패턴을 `ProjectSummarySection.jsx:141-151` 이 이미 쓴다.
  if (!TABS.some((t) => t.id === activeTab)) {
    setActiveTab('dashboard');
  }

  const isMounted = (id) => id === activeTab || visited.has(id);

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
                  {isMounted('dashboard') && (
                    <div style={{ display: activeTab === 'dashboard' ? 'block' : 'none' }}>
                      <Dashboard onGoDetail={(section) => { setActiveTab('detail'); if (section) setTimeout(() => window.__detailSection?.(section), 100); }} />
                    </div>
                  )}
                  {isMounted('detail') && (
                    <div style={{ display: activeTab === 'detail' ? 'block' : 'none' }}>
                      <Detail />
                    </div>
                  )}
                  {isMounted('quality') && (
                    <div style={{ display: activeTab === 'quality' ? 'block' : 'none' }}>
                      {/* analysisResult 를 넘기지 않는다 = **전역 스코프**(전 프로젝트).
                          같은 컴포넌트가 `프로젝트 결과 > 🚦 품질 게이트` 에서는
                          analysisResult 를 받아 그 프로젝트로 좁힌다 — 화면 두 벌이
                          서로 다른 판정을 내던 것을 한 벌로 합친 결과다. */}
                      <QualityGateSection />
                    </div>
                  )}
                  {isMounted('settings') && (
                    <div style={{ display: activeTab === 'settings' ? 'block' : 'none' }}>
                      <Settings />
                    </div>
                  )}
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
