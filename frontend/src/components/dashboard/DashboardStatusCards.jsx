const DashboardStatusCards = ({
  status,
  stat,
  preflight,
  impact,
  health,
  summary,
  tests,
  coverage,
  agent,
  scm,
  handleCardClick,
  statusTone,
  staticTone,
  preflightTone,
  impactTone,
  healthTone,
  buildTone,
  testsTone,
}) => (
  <div className="cards">
    <div className={`card clickable status-${statusTone}`} onClick={() => handleCardClick("status")}>
      <div className="card-title">상태</div>
      <div className="card-value">{status.state || "-"}</div>
      <div className="card-sub">{status.phase || status.message || "-"}</div>
    </div>
    <div className={`card clickable status-${staticTone}`} onClick={() => handleCardClick("static")}>
      <div className="card-title">정적 분석</div>
      <div className="card-value">{stat.total}</div>
      <div className="card-sub">cpp:{stat.cpp} tidy:{stat.tidy} sem:{stat.sem}</div>
    </div>
    <div className={`card clickable status-${preflightTone}`} onClick={() => handleCardClick("preflight")}>
      <div className="card-title">Preflight</div>
      <div className="card-value">{preflight.status || "-"}</div>
      <div className="card-sub">missing {(preflight.missing || []).length}</div>
    </div>
    <div className={`card clickable status-${impactTone}`} onClick={() => handleCardClick("change-impact")}>
      <div className="card-title">Change Impact</div>
      <div className="card-value">{impact.total || 0} files</div>
      <div className="card-sub">
        tests:{impact.has_tests ? "Y" : "N"} config:{impact.has_configs ? "Y" : "N"} build:
        {impact.has_build_files ? "Y" : "N"}
      </div>
    </div>
    <div className={`card clickable status-${healthTone}`} onClick={() => handleCardClick("report-health")}>
      <div className="card-title">Report Health</div>
      <div className="card-value">{health.status || "-"}</div>
      <div className="card-sub">missing {(health.missing || []).length} warn {(health.warnings || []).length}</div>
    </div>
    <div className={`card clickable status-${buildTone}`} onClick={() => handleCardClick("build")}>
      <div className="card-title">Build</div>
      <div className="card-value">{summary?.build?.ok ? "OK" : summary?.build?.reason || "-"}</div>
      <div className="card-sub">syntax {summary?.syntax?.ok ? "OK" : "FAIL"}</div>
    </div>
    <div className={`card clickable status-${testsTone}`} onClick={() => handleCardClick("tests")}>
      <div className="card-title">Tests</div>
      <div className="card-value">{tests.enabled ? "ON" : "OFF"}</div>
      <div className="card-sub">coverage {coverage.line_rate_pct ? `${coverage.line_rate_pct.toFixed(1)}%` : "-"}</div>
    </div>
    <div className="card clickable" onClick={() => handleCardClick("agent")}>
      <div className="card-title">Agent</div>
      <div className="card-value">{agent.stop_reason || (agent.enabled ? "ON" : "OFF")}</div>
      <div className="card-sub">runs {(summary?.agent_runs || []).length}</div>
    </div>
    <div className="card clickable" onClick={() => handleCardClick("scm")}>
      <div className="card-title">SCM</div>
      <div className="card-value">{scm.mode || "-"}</div>
      <div className="card-sub">changed {scm.changed_files || 0}</div>
    </div>
  </div>
);

export default DashboardStatusCards;
