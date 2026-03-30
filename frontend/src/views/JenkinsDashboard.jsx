import { useState, useEffect } from "react";
import { normalizePct } from "../utils/ui";

const JenkinsDashboard = ({
  jenkinsData,
  jenkinsBuilds,
  config,
  onOpenReportFile,
  onOpenReportFolder,
  onJenkinsTabChange,
  reportSummary,
  onLoadSummary,
  onOpenEditorFile,
}) => {
  // reportSummary가 없으면 자동으로 로드
  useEffect(() => {
    if (!reportSummary && onLoadSummary) {
      onLoadSummary();
    }
  }, [reportSummary, onLoadSummary]);
  const hasReportSummary =
    reportSummary && Object.keys(reportSummary).length > 0;
  const report = hasReportSummary ? reportSummary : jenkinsData?.summary || {};
  const reportKpis = report.kpis || {};

  const summary = jenkinsData?.summary || jenkinsData || {};
  const findings = jenkinsData?.findings || summary?.findings || [];
  const statusSource =
    jenkinsData?.status || summary?.status || jenkinsData?.jenkins || reportKpis?.build || {};
  const buildOk = summary?.build?.ok ?? reportKpis?.build?.ok;
  const syntaxOk = summary?.syntax?.ok ?? reportKpis?.build?.syntax_ok;
  const testsEnabled = summary?.tests?.enabled ?? summary?.tests?.ok;
  const issues =
    (summary?.static?.cppcheck?.data?.issues?.length || 0) +
    (summary?.static?.clang_tidy?.data?.issues?.length || 0) +
    (summary?.static?.semgrep?.data?.issues?.length || 0);
  const coverage = summary?.coverage || reportKpis?.coverage || {};
  const jenkinsScan = summary?.jenkins_scan || reportKpis?.scan || {};
  const vectorcast = summary?.vectorcast || reportKpis?.vectorcast || {};
  const prqa = summary?.prqa || reportKpis?.prqa || {};
  const jenkinsMeta = summary?.jenkins || reportKpis?.build || {};

  const statusState =
    statusSource?.state ||
    (statusSource?.building ? "running" : null) ||
    statusSource?.result ||
    "-";
  const statusSub =
    statusSource?.phase ||
    statusSource?.message ||
    statusSource?.build_url ||
    statusSource?.buildUrl ||
    "-";

  const toneForBuild = () => {
    if (buildOk === false || syntaxOk === false) return "failed";
    if (buildOk === true && syntaxOk === true) return "success";
    return "warning";
  };

  const testsMinCount = Number(config?.tests_min_count ?? 1);
  const requireTestsEnabled = config?.require_tests_enabled !== false;
  const toneForTests = () => {
    if (requireTestsEnabled && !testsEnabled) return "warning";
    if (Number(summary?.tests?.total || 0) < testsMinCount) return "warning";
    return "success";
  };
  const toneForStatic = () => (issues > 0 ? "warning" : "success");

  const coverageLine = normalizePct(
    coverage.line_rate ?? coverage.line_rate_pct,
  );
  const coverageTone = coverage?.enabled
    ? coverage?.ok === false || coverage?.below_threshold
      ? "failed"
      : "success"
    : "info";
  const tokenTotal =
    Number(jenkinsScan.FAIL_token || 0) +
    Number(jenkinsScan.ERROR_token || 0) +
    Number(jenkinsScan.WARN_token || 0);
  const tokenScaleMax = Math.max(
    1,
    Number(jenkinsScan.FAIL_token || 0),
    Number(jenkinsScan.ERROR_token || 0),
    Number(jenkinsScan.WARN_token || 0),
  );

  const buildReportStats = (data) => {
    if (!data || typeof data !== "object") return { total: 0, ok: 0, fail: 0 };
    const entries = Object.values(data);
    const total = entries.length;
    const ok = entries.filter((item) => item?.ok === true).length;
    const fail = entries.filter((item) => item?.ok === false).length;
    return { total, ok, fail };
  };

  const renderReportChart = (label, data) => {
    const stats = buildReportStats(data);
    if (!stats.total) return null;
    const okPct = Math.round((stats.ok / stats.total) * 100);
    return (
      <div className="panel">
        <h3>{label} 차트</h3>
        <div
          className="bar-row clickable"
          onClick={() =>
            onJenkinsTabChange &&
            onJenkinsTabChange("reports", "jenkins-reports")
          }
        >
          <span className="bar-label">OK</span>
          <div className="bar">
            <div className="bar-fill" style={{ width: `${okPct}%` }} />
          </div>
          <span className="bar-value">
            {stats.ok}/{stats.total}
          </span>
        </div>
      </div>
    );
  };

  const renderReportList = (label, data) => {
    if (!data || typeof data !== "object") return null;
    const entries = Object.entries(data);
    if (entries.length === 0) return null;
    return (
      <div className="panel">
        <h3>{label}</h3>
        <div className="detail-grid">
          {entries.map(([key, item]) => {
            const folderPath = item?.path
              ? String(item.path).replace(/[\\/][^\\/]+$/, "")
              : "";
            return (
              <div key={key} className="detail-row">
                <span className="detail-label">{key}</span>
                <span className="detail-value">
                  {item?.ok === true
                    ? "OK"
                    : item?.ok === false
                      ? `FAIL(${item?.reason || "-"})`
                      : "-"}
                </span>
                <span className="detail-value">{item?.path || "-"}</span>
                <span className="detail-value">
                  {item?.path ? (
                    <div className="row">
                      <button
                        type="button"
                        className="btn-outline"
                        onClick={() =>
                          onOpenReportFile && onOpenReportFile(item.path)
                        }
                      >
                        파일 열기
                      </button>
                      <button
                        type="button"
                        className="btn-outline"
                        onClick={() =>
                          onOpenReportFolder && onOpenReportFolder(folderPath)
                        }
                        disabled={!folderPath}
                      >
                        폴더 열기
                      </button>
                    </div>
                  ) : (
                    "-"
                  )}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  const reportScan = reportKpis.scan || jenkinsScan || {};
  const reportDev = report.developer || {};
  const reportTester = report.tester || {};
  const reportMgr = report.manager || {};
  const topScanFiles = Array.isArray(reportDev.top_scan_files)
    ? reportDev.top_scan_files
    : [];
  const reportFiles = reportKpis.files || {};
  const reportSource = report.source || {};
  const reportTypes = report.report_types || {};
  const reportPrqa = reportKpis.prqa || {};
  const reportVectorcast = reportKpis.vectorcast || {};
  const reportBuild = reportKpis.build || {};
  const prqaTopRules = Array.isArray(reportPrqa.top_rules)
    ? reportPrqa.top_rules
    : [];
  const prqaTopFiles = Array.isArray(reportPrqa.top_files)
    ? reportPrqa.top_files
    : [];
  const vcastUtModules = Array.isArray(reportVectorcast.ut?.modules)
    ? reportVectorcast.ut.modules
    : [];
  const vcastItModules = Array.isArray(reportVectorcast.it?.modules)
    ? reportVectorcast.it.modules
    : [];
  const [roleTab, setRoleTab] = useState("manager");
  const [scanFilter, setScanFilter] = useState("all");
  const [itSort, setItSort] = useState("coverage");
  const [buildSummaryCount, setBuildSummaryCount] = useState(20);

  const filteredTopScan = topScanFiles.filter((item) => {
    if (scanFilter === "all") return true;
    if (scanFilter === "fail") return Number(item.fail || 0) > 0;
    if (scanFilter === "error") return Number(item.error || 0) > 0;
    if (scanFilter === "warn") return Number(item.warn || 0) > 0;
    return true;
  });
  const buildRows = Array.isArray(jenkinsBuilds)
    ? jenkinsBuilds.slice(0, buildSummaryCount)
    : [];
  const buildSummary = buildRows.reduce(
    (acc, item) => {
      acc.total += 1;
      const result = String(item?.result || item?.status || "").toUpperCase();
      if (result === "SUCCESS") acc.success += 1;
      else if (result === "FAILURE") acc.fail += 1;
      else if (result === "UNSTABLE") acc.unstable += 1;
      else acc.other += 1;
      return acc;
    },
    { total: 0, success: 0, fail: 0, unstable: 0, other: 0 },
  );
  const buildIsSuccess = String(jenkinsMeta?.result || "")
    .toLowerCase()
    .includes("success");
  const renderTable = (rows) => (
    <div className="detail-grid">
      {rows.map((row) => (
        <div key={row.label} className="detail-row compact">
          <span className="detail-label">{row.label}</span>
          <span className="detail-value">{row.value}</span>
        </div>
      ))}
    </div>
  );
  const buildSummaryBars = [
    { label: "Success", value: buildSummary.success, tone: "bar-fill" },
    { label: "Fail", value: buildSummary.fail, tone: "bar-fill-warn" },
    {
      label: "Unstable",
      value: buildSummary.unstable,
      tone: "bar-fill-unstable",
    },
    { label: "Other", value: buildSummary.other, tone: "bar-fill-info" },
  ];
  const sortedItModules = [...vcastItModules].sort((a, b) => {
    if (itSort === "name") {
      return String(a.name || "").localeCompare(String(b.name || ""));
    }
    if (itSort === "branch") {
      const aRate = Number(a.branch_rate ?? 101);
      const bRate = Number(b.branch_rate ?? 101);
      return aRate - bRate;
    }
    const aRate = Number(a.line_rate ?? 101);
    const bRate = Number(b.line_rate ?? 101);
    return aRate - bRate;
  });

  return (
    <div className="view-root jenkins-dashboard">
      <h3>Jenkins 프로젝트 대시보드</h3>
      <div className="help-box">
        <h4>사용 방법</h4>
        <ul>
          <li>프로젝트 전체 현황을 보는 대시보드입니다.</li>
          <li>워크플로우에서 동기화가 완료되면 최신 상태가 반영됩니다.</li>
        </ul>
      </div>
      <div className="panel">
        <div className="row">
          <h3>리포트 요약</h3>
          <button
            type="button"
            onClick={onLoadSummary}
            disabled={!onLoadSummary}
          >
            {hasReportSummary ? "요약 새로고침" : "요약 로드"}
          </button>
          {!hasReportSummary && (
            <span
              className="hint"
              style={{ marginLeft: "10px", color: "var(--text-muted)" }}
            >
              리포트 요약이 없습니다. "요약 로드" 버튼을 클릭하거나
              워크플로우에서 동기화를 실행하세요.
            </span>
          )}
        </div>
        {/* 빌드 이력 타임라인 차트 */}
        {buildRows.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <h4 style={{ margin: "0 0 4px", fontSize: 13 }}>빌드 이력 ({buildRows.length}건)</h4>
            <div className="build-timeline">
              {buildRows.map((b, idx) => {
                const result = String(b?.result || b?.status || "").toUpperCase();
                const cls = result === "SUCCESS" ? "bar-success"
                  : result === "FAILURE" ? "bar-failure"
                  : result === "ABORTED" ? "bar-aborted"
                  : "bar-building";
                const duration = b?.duration || b?.durationMillis || 0;
                const maxDur = Math.max(...buildRows.map((r) => r?.duration || r?.durationMillis || 1));
                const heightPct = Math.max(15, (duration / Math.max(maxDur, 1)) * 100);
                return (
                  <div key={b?.number || idx} className={`build-bar ${cls}`} style={{ height: `${heightPct}%` }}>
                    <div className="build-bar-tooltip">
                      #{b?.number || idx+1} {result || "?"}<br/>
                      {duration > 0 ? `${(duration / 1000).toFixed(0)}s` : ""}
                    </div>
                  </div>
                );
              })}
            </div>
            <div style={{ display: "flex", gap: 12, fontSize: 11, color: "var(--muted)", marginTop: 4 }}>
              {buildSummaryBars.map((bs) => (
                <span key={bs.label}>{bs.label}: {bs.value}</span>
              ))}
            </div>
          </div>
        )}

        <div className="row tabs">
          {[
            { key: "manager", label: "관리자" },
            { key: "tester", label: "테스터" },
            { key: "developer", label: "개발자" },
          ].map((tab) => (
            <button
              key={tab.key}
              type="button"
              className={roleTab === tab.key ? "active" : ""}
              onClick={() => setRoleTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="summary-grid">
          {roleTab === "manager" ? (
            <>
              <div className="summary-card">
                <div className="summary-title">빌드 결과</div>
                <div className="summary-value">{reportMgr.result || "-"}</div>
                <div className="summary-sub">
                  failure {reportMgr.failure_stage || "-"}
                </div>
              </div>
              <div className="summary-card">
                <div className="summary-title">PRQA 준수율</div>
                <div className="summary-value">
                  {reportPrqa.project_compliance_index || "-"}
                </div>
                <div className="summary-sub">
                  rule violations {reportPrqa.rule_violation_count || "-"}
                </div>
              </div>
              <div className="summary-card">
                <div className="summary-title">리포트 파일</div>
                <div className="summary-value">
                  {reportScan.files_total ?? "-"}
                </div>
                <div className="summary-sub">
                  html {reportFiles.html ?? 0} · xlsx {reportFiles.xlsx ?? 0}
                </div>
              </div>
              {renderTable([
                {
                  label: "Build",
                  value:
                    reportBuild.build_number ?? reportBuild.buildNumber ?? "-",
                },
                { label: "Result", value: reportBuild.result || "-" },
                {
                  label: "Project Index",
                  value: reportPrqa.project_compliance_index || "-",
                },
                {
                  label: "Violations",
                  value: reportPrqa.rule_violation_count || "-",
                },
              ])}
            </>
          ) : null}
          {roleTab === "tester" ? (
            <>
              <div className="summary-card">
                <div className="summary-title">커버리지</div>
                <div className="summary-value">
                  {reportTester.coverage_line != null
                    ? `${(Number(reportTester.coverage_line) * 100).toFixed(1)}%`
                    : "-"}
                </div>
                <div className="summary-sub">
                  VectorCAST avg {reportVectorcast.metrics_avg_pct ?? "-"}%
                </div>
              </div>
              <div className="summary-card">
                <div className="summary-title">VectorCAST UT/IT</div>
                <div className="summary-value">
                  {reportVectorcast.ut?.line_rate ?? "-"}%
                </div>
                <div className="summary-sub">
                  IT {reportVectorcast.it?.line_rate ?? "-"}%
                </div>
              </div>
              <div className="summary-card">
                <div className="summary-title">UT/IT 리포트</div>
                <div className="summary-value">
                  {reportTester.vectorcast?.ut_reports?.length || 0}
                </div>
                <div className="summary-sub">
                  IT {reportTester.vectorcast?.it_reports?.length || 0}
                </div>
              </div>
              {renderTable([
                {
                  label: "Coverage Line",
                  value:
                    reportTester.coverage_line != null
                      ? `${(Number(reportTester.coverage_line) * 100).toFixed(1)}%`
                      : "-",
                },
                {
                  label: "Coverage Branch",
                  value:
                    reportKpis.coverage?.branch_rate != null
                      ? `${(Number(reportKpis.coverage.branch_rate) * 100).toFixed(1)}%`
                      : "-",
                },
                {
                  label: "UT Line",
                  value:
                    reportVectorcast.ut?.line_rate != null
                      ? `${reportVectorcast.ut.line_rate}%`
                      : "-",
                },
                {
                  label: "UT Branch",
                  value:
                    reportVectorcast.ut?.branch_rate != null
                      ? `${reportVectorcast.ut.branch_rate}%`
                      : "-",
                },
                {
                  label: "IT Line",
                  value:
                    reportVectorcast.it?.line_rate != null
                      ? `${reportVectorcast.it.line_rate}%`
                      : "-",
                },
                {
                  label: "IT Branch",
                  value:
                    reportVectorcast.it?.branch_rate != null
                      ? `${reportVectorcast.it.branch_rate}%`
                      : "-",
                },
              ])}
            </>
          ) : null}
          {roleTab === "developer" ? (
            <>
              <div className="summary-card">
                <div className="summary-title">스캔 경고</div>
                <div className="summary-value">
                  {reportDev.warnings_total ?? "-"}
                </div>
                <div className="summary-sub">
                  error {reportDev.errors_total ?? "-"} · fail{" "}
                  {reportDev.fail_total ?? "-"}
                </div>
              </div>
              <div className="summary-card">
                <div className="summary-title">PRQA 위반</div>
                <div className="summary-value">
                  {reportDev.prqa_rule_violations ?? "-"}
                </div>
                <div className="summary-sub">
                  VectorCAST avg {reportDev.vectorcast_metrics_avg_pct ?? "-"}
                </div>
              </div>
              {renderTable([
                { label: "Top Rule", value: prqaTopRules[0]?.rule || "-" },
                { label: "Top File", value: prqaTopFiles[0]?.file || "-" },
                { label: "Scan Warn", value: reportDev.warnings_total ?? "-" },
                { label: "Scan Error", value: reportDev.errors_total ?? "-" },
              ])}
            </>
          ) : null}
        </div>
        <div className="row">
          <span className="hint">소스: {reportSource.path || "-"}</span>
        </div>
        {Object.keys(reportTypes).length > 0 ? (
          <div className="row">
            <span className="hint">
              유형:{" "}
              {Object.entries(reportTypes)
                .map(([k, v]) => `${k}:${v}`)
                .join(" · ")}
            </span>
          </div>
        ) : null}
        <div className="row">
          {[
            { key: "all", label: "전체" },
            { key: "fail", label: "FAIL" },
            { key: "error", label: "ERROR" },
            { key: "warn", label: "WARN" },
          ].map((btn) => (
            <button
              key={btn.key}
              type="button"
              className={scanFilter === btn.key ? "active" : ""}
              onClick={() => setScanFilter(btn.key)}
            >
              {btn.label}
            </button>
          ))}
        </div>
        <details className="panel-collapsible" open={false}>
          <summary>
            <div className="summary-row-5">
              <div className="summary-card">
                <div className="summary-title">Files</div>
                <div className="summary-value">
                  {jenkinsScan.files_total ?? "-"}
                </div>
              </div>
              <div className="summary-card">
                <div className="summary-title">FAIL</div>
                <div className="summary-value">
                  {jenkinsScan.FAIL_token ?? 0}
                </div>
              </div>
              <div className="summary-card">
                <div className="summary-title">ERROR</div>
                <div className="summary-value">
                  {jenkinsScan.ERROR_token ?? 0}
                </div>
              </div>
              <div className="summary-card">
                <div className="summary-title">WARN</div>
                <div className="summary-value">
                  {jenkinsScan.WARN_token ?? 0}
                </div>
              </div>
              <div className="summary-card">
                <div className="summary-title">Total</div>
                <div className="summary-value">{tokenTotal}</div>
              </div>
            </div>
          </summary>
          <div className="panel-body">
            <div className="detail-grid compact-table">
              <div className="detail-row table-row header compact">
                <span className="detail-label">파일</span>
                <span className="detail-value">FAIL</span>
                <span className="detail-value">ERROR</span>
                <span className="detail-value">WARN</span>
              </div>
              {filteredTopScan.map((item) => (
                <div key={item.path} className="detail-row table-row compact">
                  <span className="detail-label">{item.path}</span>
                  <span className="detail-value">{item.fail}</span>
                  <span className="detail-value">{item.error}</span>
                  <span className="detail-value">{item.warn}</span>
                </div>
              ))}
              {filteredTopScan.length === 0 && (
                <div className="empty">스캔 경고 파일 없음</div>
              )}
            </div>
          </div>
        </details>
        {roleTab === "developer" || roleTab === "tester" ? (
          <>
            <details className="panel-collapsible" open={false}>
              <summary>
                <div className="summary-row-5">
                  <div className="summary-card">
                    <div className="summary-title">UT Line</div>
                    <div className="summary-value">
                      {reportVectorcast.ut?.line_rate ?? "-"}%
                    </div>
                  </div>
                  <div className="summary-card">
                    <div className="summary-title">UT Branch</div>
                    <div className="summary-value">
                      {reportVectorcast.ut?.branch_rate ?? "-"}%
                    </div>
                  </div>
                  <div className="summary-card">
                    <div className="summary-title">IT Line</div>
                    <div className="summary-value">
                      {reportVectorcast.it?.line_rate ?? "-"}%
                    </div>
                  </div>
                  <div className="summary-card">
                    <div className="summary-title">IT Branch</div>
                    <div className="summary-value">
                      {reportVectorcast.it?.branch_rate ?? "-"}%
                    </div>
                  </div>
                  <div className="summary-card">
                    <div className="summary-title">AVG</div>
                    <div className="summary-value">
                      {reportVectorcast.metrics_avg_pct ?? "-"}
                    </div>
                  </div>
                </div>
              </summary>
              <div className="panel-body">
                <div className="row">
                  <span className="hint">VectorCAST 모듈별(UT) 커버리지</span>
                </div>
                <div className="detail-grid">
                  <div className="detail-row table-row header">
                    <span className="detail-label">모듈</span>
                    <span className="detail-value">Line</span>
                    <span className="detail-value">Branch</span>
                    <span className="detail-value">-</span>
                  </div>
                  {vcastUtModules.map((item) => (
                    <div key={item.name} className="detail-row table-row">
                      <span className="detail-label">{item.name}</span>
                      <span className="detail-value">
                        {item.line_rate ?? "-"}%
                      </span>
                      <span className="detail-value">
                        {item.branch_rate ?? "-"}%
                      </span>
                      <span className="detail-value">UT</span>
                    </div>
                  ))}
                  {vcastUtModules.length === 0 && (
                    <div className="empty">모듈 커버리지 없음</div>
                  )}
                </div>
                <div className="row">
                  <span className="hint">VectorCAST 모듈별(IT) 커버리지</span>
                  <div className="row">
                    <button
                      type="button"
                      className={itSort === "coverage" ? "active" : ""}
                      onClick={() => setItSort("coverage")}
                    >
                      낮은 커버리지
                    </button>
                    <button
                      type="button"
                      className={itSort === "name" ? "active" : ""}
                      onClick={() => setItSort("name")}
                    >
                      이름순
                    </button>
                    <button
                      type="button"
                      className={itSort === "branch" ? "active" : ""}
                      onClick={() => setItSort("branch")}
                    >
                      브랜치 낮은순
                    </button>
                  </div>
                </div>
                <div className="detail-grid">
                  <div className="detail-row table-row header">
                    <span className="detail-label">모듈</span>
                    <span className="detail-value">Line</span>
                    <span className="detail-value">Branch</span>
                    <span className="detail-value">-</span>
                  </div>
                  {sortedItModules.map((item) => (
                    <div key={item.name} className="detail-row table-row">
                      <span className="detail-label">{item.name}</span>
                      <span className="detail-value">
                        {item.line_rate ?? "-"}%
                      </span>
                      <span className="detail-value">
                        {item.branch_rate ?? "-"}%
                      </span>
                      <span className="detail-value">IT</span>
                    </div>
                  ))}
                  {sortedItModules.length === 0 && (
                    <div className="empty">모듈 커버리지 없음</div>
                  )}
                </div>
              </div>
            </details>
            <details className="panel-collapsible" open={false}>
              <summary>
                <div className="summary-row-5">
                  <div className="summary-card">
                    <div className="summary-title">PRQA Violations</div>
                    <div className="summary-value">
                      {reportPrqa.rule_violation_count || "-"}
                    </div>
                  </div>
                  <div className="summary-card">
                    <div className="summary-title">Violated Rules</div>
                    <div className="summary-value">
                      {reportPrqa.violated_rules || "-"}
                    </div>
                  </div>
                  <div className="summary-card">
                    <div className="summary-title">Project Index</div>
                    <div className="summary-value">
                      {reportPrqa.project_compliance_index || "-"}
                    </div>
                  </div>
                  <div className="summary-card">
                    <div className="summary-title">Top Rule</div>
                    <div className="summary-value">
                      {prqaTopRules[0]?.rule || "-"}
                    </div>
                  </div>
                  <div className="summary-card">
                    <div className="summary-title">Top File</div>
                    <div className="summary-value">
                      {prqaTopFiles[0]?.file || "-"}
                    </div>
                  </div>
                </div>
              </summary>
              <div className="panel-body">
                <div className="row">
                  <span className="hint">PRQA 상위 규칙</span>
                </div>
                <div className="detail-grid">
                  <div className="detail-row table-row header">
                    <span className="detail-label">규칙</span>
                    <span className="detail-value">Count</span>
                    <span className="detail-value">-</span>
                    <span className="detail-value">-</span>
                  </div>
                  {prqaTopRules.map((item) => (
                    <div key={item.rule} className="detail-row table-row">
                      <span className="detail-label">{item.rule}</span>
                      <span className="detail-value">{item.count}</span>
                      <span className="detail-value">-</span>
                      <span className="detail-value">-</span>
                    </div>
                  ))}
                  {prqaTopRules.length === 0 && (
                    <div className="empty">상위 규칙 없음</div>
                  )}
                </div>
                <div className="row">
                  <span className="hint">PRQA 상위 파일</span>
                </div>
                <div className="detail-grid">
                  <div className="detail-row table-row header">
                    <span className="detail-label">파일</span>
                    <span className="detail-value">Count</span>
                    <span className="detail-value">-</span>
                    <span className="detail-value">Action</span>
                  </div>
                  {prqaTopFiles.map((item) => (
                    <div key={item.file} className="detail-row table-row">
                      <span className="detail-label">{item.file}</span>
                      <span className="detail-value">{item.count}</span>
                      <span className="detail-value">-</span>
                      <span className="detail-value">
                        {item.path ? (
                          <button
                            type="button"
                            className="btn-outline"
                            onClick={() =>
                              onOpenEditorFile && onOpenEditorFile(item.path)
                            }
                          >
                            에디터 이동
                          </button>
                        ) : (
                          "-"
                        )}
                      </span>
                    </div>
                  ))}
                  {prqaTopFiles.length === 0 && (
                    <div className="empty">상위 파일 없음</div>
                  )}
                </div>
              </div>
            </details>
          </>
        ) : null}
      </div>
      <div className="panel">
        <h3>리포트 스캔</h3>
        <div className="detail-grid">
          <div className="detail-row">
            <span className="detail-label">Files</span>
            <span className="detail-value">
              {jenkinsScan.files_total ?? "-"}
            </span>
          </div>
          <div className="detail-row">
            <span className="detail-label">HTML</span>
            <span className="detail-value">{jenkinsScan.html_count ?? 0}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">XLSX</span>
            <span className="detail-value">{jenkinsScan.xlsx_count ?? 0}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">LOG</span>
            <span className="detail-value">{jenkinsScan.log_count ?? 0}</span>
          </div>
          <div className="detail-row">
            <span className="detail-label">FAIL/ERROR/WARN</span>
            <span className="detail-value">
              {jenkinsScan.FAIL_token ?? 0} / {jenkinsScan.ERROR_token ?? 0} /{" "}
              {jenkinsScan.WARN_token ?? 0}
            </span>
          </div>
          <div className="detail-row">
            <span className="detail-label">총합 / 스케일</span>
            <span className="detail-value">{tokenTotal}</span>
            <span className="detail-value">max {tokenScaleMax}</span>
          </div>
        </div>
        <div className="heatmap">
          <div className="heatmap-header">
            <span>Token</span>
            <span>FAIL</span>
            <span>ERROR</span>
            <span>WARN</span>
          </div>
          <div className="heatmap-row">
            <span className="heatmap-label">Count</span>
            {[
              { key: "FAIL_token", className: "heatmap-danger" },
              { key: "ERROR_token", className: "heatmap-danger" },
              { key: "WARN_token", className: "heatmap-warn" },
            ].map((item) => {
              const value = Number(jenkinsScan[item.key] || 0);
              return (
                <span
                  key={item.key}
                  className={`heatmap-cell ${item.className}`}
                  style={{ opacity: Math.min(1, value / tokenScaleMax) }}
                >
                  {value}
                </span>
              );
            })}
          </div>
        </div>
      </div>
      {renderReportChart("VectorCAST", vectorcast)}
      {renderReportChart("PRQA", prqa)}
      {renderReportList("VectorCAST", vectorcast)}
      {renderReportList("PRQA", prqa)}
      <details className="detail-raw">
        <summary>원본 JSON 보기</summary>
        <pre className="json">{JSON.stringify(hasReportSummary ? reportSummary : jenkinsData || {}, null, 2)}</pre>
      </details>
    </div>
  );
};

export default JenkinsDashboard;
