import { useEffect, useState } from "react";

const LocalReportSummaryPanel = ({
  reportSummaries,
  reportComparisons,
  loadLocalReportSummary,
  onOpenEditorFile,
}) => {
  const [reportRoleTab, setReportRoleTab] = useState("manager");
  const [itSort, setItSort] = useState("coverage");

  useEffect(() => {
    if (loadLocalReportSummary && reportSummaries.length === 0) {
      loadLocalReportSummary();
    }
  }, [loadLocalReportSummary, reportSummaries.length]);

  return (
    <div className="metric-detail">
      <div className="row">
        <span className="hint">로컬 리포트 요약</span>
        <button type="button" onClick={loadLocalReportSummary}>
          요약 로드
        </button>
      </div>
      <div className="row tabs">
        {[
          { key: "manager", label: "관리자" },
          { key: "tester", label: "테스터" },
          { key: "developer", label: "개발자" },
        ].map((tab) => (
          <button
            key={tab.key}
            type="button"
            className={reportRoleTab === tab.key ? "active" : ""}
            onClick={() => setReportRoleTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {reportComparisons.length > 0 ? (
        <div className="panel">
          <h4>리포트 비교(최근 2회)</h4>
          <div className="detail-grid">
            {reportComparisons.map((cmp) => {
              const renderDelta = (label, metric) => {
                const d = metric?.delta;
                const prev = metric?.prev;
                const cur = metric?.current ?? metric?.cur;
                const num = Number(d);
                const cls = num > 0 ? "delta-up" : num < 0 ? "delta-down" : "delta-zero";
                const arrow = num > 0 ? "▲" : num < 0 ? "▼" : "–";
                return (
                  <span className="detail-value" key={label}>
                    <span className={`delta-badge ${cls}`}>
                      <span className="delta-arrow">{arrow}</span>
                      {label} {d ?? "-"}
                    </span>
                    {(prev != null || cur != null) && (
                      <span className="delta-abs">({prev ?? "?"} → {cur ?? "?"})</span>
                    )}
                  </span>
                );
              };
              return (
                <div key={cmp.job_slug} className="detail-row">
                  <span className="detail-label">{cmp.job_slug}</span>
                  {renderDelta("fail", cmp.metrics?.scan_fail)}
                  {renderDelta("error", cmp.metrics?.scan_error)}
                  {renderDelta("warn", cmp.metrics?.scan_warn)}
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
      {reportSummaries.map((report) => {
        const kpis = report.kpis || {};
        const scan = kpis.scan || {};
        const files = kpis.files || {};
        const dev = report.developer || {};
        const tester = report.tester || {};
        const manager = report.manager || {};
        const reportPrqa = kpis.prqa || {};
        const reportVectorcast = kpis.vectorcast || {};
        const prqaTopRules = Array.isArray(dev.prqa_top_rules)
          ? dev.prqa_top_rules
          : [];
        const prqaTopFiles = Array.isArray(dev.prqa_top_files)
          ? dev.prqa_top_files
          : [];
        const vcastUtModules = Array.isArray(kpis.vectorcast?.ut?.modules)
          ? kpis.vectorcast.ut.modules
          : [];
        const vcastItModules = Array.isArray(kpis.vectorcast?.it?.modules)
          ? kpis.vectorcast.it.modules
          : [];
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
          <div
            key={report.source?.path || report.source?.name}
            className="panel"
          >
            <h4>{report.source?.name || "리포트"}</h4>
            {reportRoleTab === "manager" ? (
              <div className="summary-grid">
                <div className="summary-card">
                  <div className="summary-title">빌드 결과</div>
                  <div className="summary-value">{manager.result || "-"}</div>
                  <div className="summary-sub">
                    failure {manager.failure_stage || "-"}
                  </div>
                </div>
                <div className="summary-card">
                  <div className="summary-title">품질 지표</div>
                  <div className="summary-value">
                    {manager.prqa_project_compliance_index || "-"}
                  </div>
                  <div className="summary-sub">PRQA project compliance</div>
                </div>
                <div className="summary-card">
                  <div className="summary-title">VectorCAST UT/IT</div>
                  <div className="summary-value">
                    {manager.vectorcast_ut_line_rate ?? "-"}%
                  </div>
                  <div className="summary-sub">
                    IT {manager.vectorcast_it_line_rate ?? "-"}%
                  </div>
                </div>
                <div className="summary-card">
                  <div className="summary-title">리포트 파일</div>
                  <div className="summary-value">{scan.files_total ?? "-"}</div>
                  <div className="summary-sub">
                    html {files.html ?? 0} · xlsx {files.xlsx ?? 0}
                  </div>
                </div>
              </div>
            ) : null}
            {reportRoleTab === "tester" ? (
              <div className="summary-grid">
                <div className="summary-card">
                  <div className="summary-title">커버리지</div>
                  <div className="summary-value">
                    {tester.coverage_line != null
                      ? `${(Number(tester.coverage_line) * 100).toFixed(1)}%`
                      : "-"}
                  </div>
                  <div className="summary-sub">
                    VectorCAST avg {tester.vectorcast_metrics_avg_pct ?? "-"}
                  </div>
                </div>
                <div className="summary-card">
                  <div className="summary-title">VectorCAST UT/IT</div>
                  <div className="summary-value">
                    {tester.vectorcast_ut_line_rate ?? "-"}%
                  </div>
                  <div className="summary-sub">
                    IT {tester.vectorcast_it_line_rate ?? "-"}%
                  </div>
                </div>
                <div className="summary-card">
                  <div className="summary-title">UT/IT 리포트</div>
                  <div className="summary-value">
                    {tester.vectorcast?.ut_reports?.length || 0}
                  </div>
                  <div className="summary-sub">
                    IT {tester.vectorcast?.it_reports?.length || 0}
                  </div>
                </div>
              </div>
            ) : null}
            {reportRoleTab === "developer" ? (
              <div className="summary-grid">
                <div className="summary-card">
                  <div className="summary-title">스캔 경고</div>
                  <div className="summary-value">
                    {dev.warnings_total ?? "-"}
                  </div>
                  <div className="summary-sub">
                    error {dev.errors_total ?? "-"} · fail{" "}
                    {dev.fail_total ?? "-"}
                  </div>
                </div>
                <div className="summary-card">
                  <div className="summary-title">PRQA 위반</div>
                  <div className="summary-value">
                    {dev.prqa_rule_violations ?? "-"}
                  </div>
                  <div className="summary-sub">
                    VectorCAST avg {dev.vectorcast_metrics_avg_pct ?? "-"}
                  </div>
                </div>
                <div className="summary-card">
                  <div className="summary-title">상위 경고 파일</div>
                  <div className="summary-value">
                    {dev.top_scan_files?.length || 0}
                  </div>
                  <div className="summary-sub">top 6</div>
                </div>
              </div>
            ) : null}
            <div className="hint">소스: {report.source?.path || "-"}</div>
            {reportRoleTab === "developer" || reportRoleTab === "tester" ? (
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
                      <span className="hint">
                        VectorCAST 모듈별(UT) 커버리지
                      </span>
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
                      <span className="hint">
                        VectorCAST 모듈별(IT) 커버리지
                      </span>
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
                                  onOpenEditorFile &&
                                  onOpenEditorFile(item.path)
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
        );
      })}
      {reportSummaries.length === 0 && (
        <div className="empty">리포트 요약 없음</div>
      )}
    </div>
  );
};

export default LocalReportSummaryPanel;
