import { useState, useMemo } from "react";
import VCastReportGenerator from "../../views/VCastReportGenerator";

const VCAST_PAGE_SIZE = 50;

const JenkinsVCastPanel = ({
  vcastRag,
  loadVcastRag,
  vcastLoading,
  jenkinsJobUrl,
  jenkinsCacheRoot,
  jenkinsBuildSelector,
  message,
  setMessage,
  enqueueOp,
  updateOp,
}) => {
  const [vcastQuery, setVcastQuery] = useState("");
  const [vcastResultFilter, setVcastResultFilter] = useState("all");
  const [vcastPage, setVcastPage] = useState(1);

  const vcastPayload = vcastRag?.data || {};
  const vcastSummary = vcastPayload.summary || {};
  const vcastFailures = Array.isArray(vcastPayload.failures)
    ? vcastPayload.failures
    : [];
  const vcastErrors = Array.isArray(vcastPayload.parse_errors)
    ? vcastPayload.parse_errors
    : [];
  const vcastRows = Array.isArray(vcastPayload.test_rows)
    ? vcastPayload.test_rows
    : [];
  const vcastComparison = vcastRag?.comparison || {};
  const vcastRowsTruncated = !!vcastPayload.rows_truncated;

  const filteredVcastRows = useMemo(() => {
    const query = vcastQuery.trim().toLowerCase();
    return vcastRows.filter((row) => {
      const result = String(row.result || "").toLowerCase();
      if (vcastResultFilter !== "all") {
        if (!result.includes(vcastResultFilter)) return false;
      }
      if (!query) return true;
      return [
        row.testcase,
        row.requirement_id,
        row.unit,
        row.subprogram,
        row.result,
        row.report,
        row.source,
      ]
        .filter(Boolean)
        .some((val) => String(val).toLowerCase().includes(query));
    });
  }, [vcastRows, vcastQuery, vcastResultFilter]);

  const vcastTotalPages = Math.max(
    1,
    Math.ceil(filteredVcastRows.length / VCAST_PAGE_SIZE)
  );
  const vcastPageSafe = Math.min(vcastPage, vcastTotalPages);
  const vcastPageRows = filteredVcastRows.slice(
    (vcastPageSafe - 1) * VCAST_PAGE_SIZE,
    vcastPageSafe * VCAST_PAGE_SIZE
  );

  return (
    <div>
      <div className="row">
        <button
          type="button"
          onClick={loadVcastRag}
          disabled={!jenkinsJobUrl || vcastLoading}
        >
          {vcastLoading ? "로딩 중..." : "TResultParser 결과 로드"}
        </button>
        {vcastRowsTruncated && (
          <span className="hint">
            표시 제한으로 일부 행만 로드되었습니다.
          </span>
        )}
      </div>
      {!vcastRag && <div className="empty">리포트를 로드해 주세요.</div>}
      {vcastRag && vcastRag.ok === false && (
        <div className="empty">TResultParser 결과가 없습니다.</div>
      )}
      {vcastRag && vcastRag.ok && (
        <>
          <div className="cards">
            <div className="card">
              <div className="card-title">총 테스트</div>
              <div className="card-value">{vcastSummary.total ?? "-"}</div>
            </div>
            <div className="card">
              <div className="card-title">통과</div>
              <div className="card-value">{vcastSummary.passed ?? "-"}</div>
            </div>
            <div className="card">
              <div className="card-title">실패</div>
              <div className="card-value">{vcastSummary.failed ?? "-"}</div>
            </div>
            <div className="card">
              <div className="card-title">Pass Rate</div>
              <div className="card-value">
                {vcastSummary.pass_rate != null
                  ? `${(vcastSummary.pass_rate * 100).toFixed(1)}%`
                  : "-"}
              </div>
            </div>
          </div>
          {vcastComparison?.current && vcastComparison?.previous && (
            <div className="panel">
              <h4>이전 빌드 비교</h4>
              <div className="detail-grid">
                <div className="detail-row compact">
                  <span className="detail-label">총 테스트</span>
                  <span className="detail-value">
                    {vcastComparison.delta?.total ?? "-"}
                  </span>
                </div>
                <div className="detail-row compact">
                  <span className="detail-label">통과</span>
                  <span className="detail-value">
                    {vcastComparison.delta?.passed ?? "-"}
                  </span>
                </div>
                <div className="detail-row compact">
                  <span className="detail-label">실패</span>
                  <span className="detail-value">
                    {vcastComparison.delta?.failed ?? "-"}
                  </span>
                </div>
                <div className="detail-row compact">
                  <span className="detail-label">Pass Rate</span>
                  <span className="detail-value">
                    {vcastComparison.delta?.pass_rate != null
                      ? `${(vcastComparison.delta.pass_rate * 100).toFixed(1)}%`
                      : "-"}
                  </span>
                </div>
              </div>
            </div>
          )}
          {vcastErrors.length > 0 && (
            <div className="panel">
              <h4>파싱 경고</h4>
              <div className="list">
                {vcastErrors.map((err) => (
                  <div key={err} className="list-item">
                    <span className="list-text">{err}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="panel">
            <h4>실패 목록</h4>
            <div className="list">
              {vcastFailures.map((item, idx) => (
                <div key={`${item.testcase}-${idx}`} className="list-item">
                  <span className="list-text">
                    {item.testcase || item.subprogram || "(이름 없음)"}
                  </span>
                  <span className="list-snippet">
                    {item.result || "-"} · {item.unit || "-"} ·{" "}
                    {item.report || "-"}
                  </span>
                </div>
              ))}
              {vcastFailures.length === 0 && (
                <div className="empty">실패 항목 없음</div>
              )}
            </div>
          </div>
          <div className="panel">
            <h4>테스트케이스</h4>
            <div className="row">
              <input
                placeholder="검색"
                value={vcastQuery}
                onChange={(e) => setVcastQuery(e.target.value)}
              />
              <select
                value={vcastResultFilter}
                onChange={(e) => setVcastResultFilter(e.target.value)}
              >
                <option value="all">전체</option>
                <option value="pass">pass</option>
                <option value="fail">fail</option>
                <option value="skip">skip</option>
              </select>
            </div>
            <div className="list">
              {vcastPageRows.map((row, idx) => (
                <div
                  key={`${row.testcase}-${row.requirement_id}-${idx}`}
                  className="list-item"
                >
                  <span className="list-text">
                    {row.testcase || row.subprogram || "(이름 없음)"}
                  </span>
                  <span className="list-snippet">
                    {row.result || "-"} · {row.unit || "-"} ·{" "}
                    {row.requirement_id || "-"}
                  </span>
                </div>
              ))}
              {vcastPageRows.length === 0 && (
                <div className="empty">데이터 없음</div>
              )}
            </div>
            <div className="row">
              <button
                type="button"
                onClick={() => setVcastPage(Math.max(1, vcastPageSafe - 1))}
                disabled={vcastPageSafe <= 1}
              >
                이전
              </button>
              <span className="hint">
                {vcastPageSafe} / {vcastTotalPages}
              </span>
              <button
                type="button"
                onClick={() =>
                  setVcastPage(Math.min(vcastTotalPages, vcastPageSafe + 1))
                }
                disabled={vcastPageSafe >= vcastTotalPages}
              >
                다음
              </button>
            </div>
          </div>
        </>
      )}
      <VCastReportGenerator
        jenkinsJobUrl={jenkinsJobUrl}
        jenkinsCacheRoot={jenkinsCacheRoot}
        jenkinsBuildSelector={jenkinsBuildSelector}
        message={message}
        setMessage={setMessage}
        enqueueOp={enqueueOp}
        updateOp={updateOp}
      />
    </div>
  );
};

export default JenkinsVCastPanel;
