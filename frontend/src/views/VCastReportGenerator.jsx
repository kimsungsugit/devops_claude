import { useState, useCallback, useEffect } from "react";

const api = async (path, options = {}) => {
  const headers =
    options?.body instanceof FormData
      ? {}
      : { "Content-Type": "application/json" };
  const res = await fetch(path, {
    headers,
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
};

export default function VCastReportGenerator({
  jenkinsJobUrl = "",
  jenkinsCacheRoot = "",
  jenkinsBuildSelector = "lastSuccessfulBuild",
  message = "",
  setMessage = () => {},
  enqueueOp,
  updateOp,
}) {
  const [reportType, setReportType] = useState("TestCaseData");
  const [version, setVersion] = useState("Ver2025");
  const [mode, setMode] = useState("TestCase");
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [parsedData, setParsedData] = useState(null);
  const [parsedItems, setParsedItems] = useState([]);
  const [selectedParsedIndex, setSelectedParsedIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [generatedReports, setGeneratedReports] = useState([]);

  const handleFileUpload = useCallback((event) => {
    const files = Array.from(event.target.files || []);
    setUploadedFiles(files);
    setParsedData(null);
    setParsedItems([]);
    setSelectedParsedIndex(0);
  }, []);

  const handleParse = useCallback(async () => {
    if (!uploadedFiles.length) {
      setMessage("파일을 선택해주세요");
      return;
    }

    const opId =
      enqueueOp &&
      enqueueOp("vcast", `VCast 파싱 시작 (${uploadedFiles.length}개)`);
    setLoading(true);
    try {
      const items = [];
      let totalTests = 0;
      let totalPassed = 0;
      for (const file of uploadedFiles) {
        const formData = new FormData();
        formData.append("file", file);
        const data = await api(
          `/api/vcast/parse?report_type=${encodeURIComponent(reportType)}&version=${encodeURIComponent(version)}`,
          {
            method: "POST",
            body: formData,
          }
        );
        if (data?.ok) {
          items.push({ filename: file.name, data });
          if (typeof data.test_count === "number")
            totalTests += data.test_count;
          if (typeof data.passed_count === "number")
            totalPassed += data.passed_count;
        }
      }

      if (items.length > 0) {
        setParsedItems(items);
        setParsedData(items[0].data || null);
        setSelectedParsedIndex(0);
        const countText =
          totalTests > 0
            ? `, ${totalTests}개 테스트 케이스, ${totalPassed}개 통과`
            : "";
        setMessage(`파싱 완료: ${items.length}개 파일${countText}`);
        if (opId && updateOp)
          updateOp(opId, {
            status: "success",
            message: `VCast 파싱 완료 (${items.length}개)`,
          });
      } else {
        setMessage("파싱 실패");
        if (opId && updateOp)
          updateOp(opId, { status: "failed", message: "VCast 파싱 실패" });
      }
    } catch (e) {
      setMessage(`파싱 오류: ${e.message}`);
      if (opId && updateOp)
        updateOp(opId, { status: "failed", message: e.message });
    } finally {
      setLoading(false);
    }
  }, [uploadedFiles, reportType, version, setMessage, enqueueOp, updateOp]);

  const handleGenerateExcel = useCallback(async () => {
    if (!parsedData) {
      setMessage("먼저 리포트를 파싱해주세요");
      return;
    }

    const opId = enqueueOp && enqueueOp("vcast", "Jenkins VCast 처리 시작");
    setLoading(true);
    try {
      // 리포트 타입에 따라 모드 자동 설정
      let excelMode = mode;
      if (reportType === "Metrics" || reportType === "AggregateCoverage") {
        excelMode = "Metrics";
      } else if (reportType === "ExecutionResult") {
        excelMode = "TestResult";
      } else if (reportType === "TestCaseData") {
        excelMode = "TestCase";
      }

      const data = await api("/api/vcast/generate-excel", {
        method: "POST",
        body: JSON.stringify({
          parsed_data: parsedData,
          mode: excelMode,
        }),
      });

      if (data.ok) {
        setMessage("Excel 리포트 생성 완료");
        loadReports();
        if (opId && updateOp)
          updateOp(opId, {
            status: "success",
            message: "VCast Excel 생성 완료",
          });
      } else {
        setMessage("Excel 생성 실패");
        if (opId && updateOp)
          updateOp(opId, {
            status: "failed",
            message: "VCast Excel 생성 실패",
          });
      }
    } catch (e) {
      setMessage(`Excel 생성 오류: ${e.message}`);
      if (opId && updateOp)
        updateOp(opId, { status: "failed", message: e.message });
    } finally {
      setLoading(false);
    }
  }, [parsedData, mode, setMessage, enqueueOp, updateOp]);

  const handleProcessJenkins = useCallback(async () => {
    if (!jenkinsJobUrl || !jenkinsCacheRoot) {
      setMessage("Jenkins 설정이 필요합니다");
      return;
    }

    setLoading(true);
    try {
      const data = await api("/api/vcast/process-jenkins", {
        method: "POST",
        body: JSON.stringify({
          job_url: jenkinsJobUrl,
          cache_root: jenkinsCacheRoot,
          build_selector: jenkinsBuildSelector,
          report_type: reportType,
          version: version,
        }),
      });

      if (data.ok) {
        setMessage(
          `Jenkins 리포트 처리 완료: ${data.test_count}개 테스트 케이스`
        );
        setParsedData({
          ok: true,
          environment: data.environment,
          component_name: data.component_name,
          test_count: data.test_count,
          passed_count: data.passed_count,
        });
        if (opId && updateOp)
          updateOp(opId, {
            status: "success",
            message: "Jenkins VCast 처리 완료",
          });
      } else {
        setMessage(data.message || "Jenkins 처리 실패");
        if (opId && updateOp)
          updateOp(opId, {
            status: "failed",
            message: data.message || "Jenkins 처리 실패",
          });
      }
    } catch (e) {
      setMessage(`Jenkins 처리 오류: ${e.message}`);
      if (opId && updateOp)
        updateOp(opId, { status: "failed", message: e.message });
    } finally {
      setLoading(false);
    }
  }, [
    jenkinsJobUrl,
    jenkinsCacheRoot,
    jenkinsBuildSelector,
    reportType,
    version,
    setMessage,
    enqueueOp,
    updateOp,
  ]);

  const loadReports = useCallback(async () => {
    try {
      const data = await api("/api/vcast/reports");
      if (data.ok) {
        setGeneratedReports(data.reports || []);
      }
    } catch (e) {
      console.error("리포트 목록 로드 실패:", e);
    }
  }, []);

  const downloadReport = useCallback((filename) => {
    window.open(`/api/vcast/reports/${encodeURIComponent(filename)}`, "_blank");
  }, []);

  useState(() => {
    loadReports();
  }, []);

  useEffect(() => {
    loadReports();
  }, [loadReports]);

  return (
    <div style={{ padding: "20px" }}>
      <h2>VectorCAST 리포트 생성기</h2>

      <div style={{ marginBottom: "20px" }}>
        <h3>리포트 설정</h3>
        <div style={{ marginBottom: "10px" }}>
          <label>
            리포트 타입:
            <select
              value={reportType}
              onChange={(e) => setReportType(e.target.value)}
              style={{ marginLeft: "10px" }}
            >
              <option value="TestCaseData">TestCaseData</option>
              <option value="ExecutionResult">ExecutionResult</option>
              <option value="Metrics">Metrics</option>
              <option value="AggregateCoverage">AggregateCoverage</option>
            </select>
          </label>
        </div>
        <div style={{ marginBottom: "10px" }}>
          <label>
            VectorCAST 버전:
            <select
              value={version}
              onChange={(e) => setVersion(e.target.value)}
              style={{ marginLeft: "10px" }}
            >
              <option value="Ver2021">2021</option>
              <option value="Ver2024">2024</option>
              <option value="Ver2025">2025</option>
            </select>
          </label>
        </div>
        <div style={{ marginBottom: "10px" }}>
          <label>
            Excel 모드:
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              style={{ marginLeft: "10px" }}
            >
              <option value="TestCase">TestCase</option>
              <option value="TestResult">TestResult</option>
              <option value="TestReport">TestReport</option>
              <option value="Metrics">Metrics</option>
            </select>
          </label>
        </div>
      </div>

      <div style={{ marginBottom: "20px" }}>
        <h3>로컬 파일 업로드</h3>
        <div style={{ marginBottom: "10px" }}>
          <input
            type="file"
            accept=".html"
            multiple
            onChange={handleFileUpload}
            style={{ marginBottom: "10px" }}
          />
          {uploadedFiles.length > 0 && (
            <div style={{ marginTop: "10px", color: "var(--text-muted)" }}>
              선택된 파일: {uploadedFiles.map((file) => file.name).join(", ")}
            </div>
          )}
        </div>
        {parsedItems.length > 0 && (
          <div style={{ marginBottom: "10px" }}>
            <label>
              파싱 결과 선택:
              <select
                value={selectedParsedIndex}
                onChange={(e) => {
                  const nextIndex = Number(e.target.value);
                  setSelectedParsedIndex(nextIndex);
                  setParsedData(parsedItems[nextIndex]?.data || null);
                }}
                style={{ marginLeft: "10px" }}
              >
                {parsedItems.map((item, idx) => (
                  <option key={`${item.filename || "file"}-${idx}`} value={idx}>
                    {item.filename || `파일 ${idx + 1}`}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
        <button
          onClick={handleParse}
          disabled={uploadedFiles.length === 0 || loading}
          style={{
            padding: "8px 16px",
            backgroundColor: "var(--accent)",
            color: "var(--text-inverse)",
            border: "none",
            borderRadius: "var(--radius-sm)",
            cursor:
              uploadedFiles.length > 0 && !loading ? "pointer" : "not-allowed",
          }}
        >
          {loading ? "파싱 중..." : "리포트 파싱"}
        </button>
      </div>

      <div style={{ marginBottom: "20px" }}>
        <h3>Jenkins 아티팩트에서 처리</h3>
        <button
          onClick={handleProcessJenkins}
          disabled={!jenkinsJobUrl || !jenkinsCacheRoot || loading}
          style={{
            padding: "8px 16px",
            backgroundColor: "var(--color-success)",
            color: "var(--text-inverse)",
            border: "none",
            borderRadius: "var(--radius-sm)",
            cursor:
              jenkinsJobUrl && jenkinsCacheRoot && !loading
                ? "pointer"
                : "not-allowed",
          }}
        >
          {loading ? "처리 중..." : "Jenkins에서 리포트 처리"}
        </button>
        {!jenkinsJobUrl || !jenkinsCacheRoot ? (
          <div style={{ marginTop: "10px", color: "var(--color-danger)" }}>
            Jenkins 설정이 필요합니다 (Settings에서 설정)
          </div>
        ) : null}
      </div>

      {parsedData && (
        <div
          style={{
            marginBottom: "20px",
            padding: "15px",
            backgroundColor: "var(--bg)",
            borderRadius: "var(--radius-sm)",
          }}
        >
          <h3>파싱 결과</h3>
          <div>
            <strong>환경:</strong> {parsedData.environment || "N/A"}
          </div>
          {parsedData.component_name && (
            <div>
              <strong>컴포넌트:</strong> {parsedData.component_name}
            </div>
          )}
          {parsedData.test_count !== undefined && (
            <>
              <div>
                <strong>테스트 케이스 수:</strong> {parsedData.test_count || 0}
              </div>
              <div>
                <strong>통과 수:</strong> {parsedData.passed_count || 0}
              </div>
            </>
          )}
          {parsedData.statement_units !== undefined && (
            <>
              <div>
                <strong>Statement Units:</strong>{" "}
                {parsedData.statement_units || 0}
              </div>
              <div>
                <strong>Functions Units:</strong>{" "}
                {parsedData.functions_units || 0}
              </div>
              {parsedData.sub_functions !== undefined && (
                <div>
                  <strong>Sub Functions:</strong>{" "}
                  {parsedData.sub_functions || 0}
                </div>
              )}
            </>
          )}
          <div style={{ marginTop: "10px" }}>
            <button
              onClick={handleGenerateExcel}
              disabled={loading}
              style={{
                padding: "8px 16px",
                backgroundColor: "var(--accent)",
                color: "var(--text-inverse)",
                border: "none",
                borderRadius: "var(--radius-sm)",
                cursor: !loading ? "pointer" : "not-allowed",
              }}
            >
              {loading ? "생성 중..." : "Excel 리포트 생성"}
            </button>
          </div>
        </div>
      )}

      <div style={{ marginTop: "30px" }}>
        <h3>생성된 리포트 목록</h3>
        {generatedReports.length === 0 ? (
          <div style={{ color: "var(--text-muted)" }}>생성된 리포트가 없습니다</div>
        ) : (
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              marginTop: "10px",
            }}
          >
            <thead>
              <tr style={{ backgroundColor: "var(--sidebar)" }}>
                <th
                  style={{
                    padding: "10px",
                    textAlign: "left",
                    border: "1px solid var(--border)",
                  }}
                >
                  파일명
                </th>
                <th
                  style={{
                    padding: "10px",
                    textAlign: "left",
                    border: "1px solid var(--border)",
                  }}
                >
                  크기
                </th>
                <th
                  style={{
                    padding: "10px",
                    textAlign: "left",
                    border: "1px solid var(--border)",
                  }}
                >
                  생성일
                </th>
                <th
                  style={{
                    padding: "10px",
                    textAlign: "left",
                    border: "1px solid var(--border)",
                  }}
                >
                  작업
                </th>
              </tr>
            </thead>
            <tbody>
              {generatedReports.map((report, idx) => (
                <tr key={idx}>
                  <td style={{ padding: "10px", border: "1px solid var(--border)" }}>
                    {report.filename}
                  </td>
                  <td style={{ padding: "10px", border: "1px solid var(--border)" }}>
                    {(report.size / 1024).toFixed(2)} KB
                  </td>
                  <td style={{ padding: "10px", border: "1px solid var(--border)" }}>
                    {new Date(report.created).toLocaleString("ko-KR")}
                  </td>
                  <td style={{ padding: "10px", border: "1px solid var(--border)" }}>
                    <button
                      onClick={() => downloadReport(report.filename)}
                      style={{
                        padding: "4px 8px",
                        backgroundColor: "var(--accent)",
                        color: "var(--text-inverse)",
                        border: "none",
                        borderRadius: "var(--radius-sm)",
                        cursor: "pointer",
                      }}
                    >
                      다운로드
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
