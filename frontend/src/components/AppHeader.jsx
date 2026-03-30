import StatusPill from "./StatusPill";

const AppHeader = ({
  title,
  subtitle,
  breadcrumbs,
  statusTone,
  status,
  loading,
  sessionLabel,
  sessionId,
  mode,
  onRefreshSession,
  onRefreshLogs,
  theme,
  onToggleTheme,
}) => (
  <header className="app-header">
    <div>
      {Array.isArray(breadcrumbs) && breadcrumbs.length > 0 ? (
        <div className="app-breadcrumbs">
          {breadcrumbs.map((crumb, idx) => (
            <span key={`${crumb}-${idx}`} className="app-crumb">
              {crumb}
            </span>
          ))}
        </div>
      ) : null}
      <div className="app-title">{title}</div>
      <div className="app-sub">{subtitle}</div>
    </div>
    <div className="app-header-meta">
      <StatusPill tone={statusTone}>
        {status?.state || (loading ? "RUNNING" : "READY")}
      </StatusPill>
      {mode === "local" ? <StatusPill tone="neutral">{sessionLabel}</StatusPill> : null}
    </div>
    <div className="app-actions">
      {mode === "local" && (
        <>
          <button onClick={onRefreshSession} disabled={!sessionId} aria-label="세션 새로고침">
            세션 새로고침
          </button>
          <button onClick={onRefreshLogs} disabled={!sessionId} aria-label="로그 새로고침">
            로그 새로고침
          </button>
        </>
      )}
      <button
        className="theme-toggle"
        onClick={onToggleTheme}
        aria-label={theme === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환"}
      >
        {theme === "dark" ? "라이트 모드" : "다크 모드"}
      </button>
    </div>
  </header>
);

export default AppHeader;
