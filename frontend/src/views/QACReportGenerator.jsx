import { useCallback, useEffect, useMemo, useState } from "react";
import ReportMarkdownPreview from "../components/ReportMarkdownPreview";

const jsonApi = async (path, options = {}) => {
  const res = await fetch(path, options);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
};

const cardStyle = {
  padding: "10px 12px",
  backgroundColor: "var(--panel)",
  borderRadius: "var(--radius-md)",
  minWidth: "150px",
  border: "1px solid var(--border)",
};

const cellStyle = {
  padding: "8px",
  border: "1px solid var(--border)",
  verticalAlign: "top",
};

const buttonStyle = {
  padding: "8px 14px",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border)",
  cursor: "pointer",
  backgroundColor: "var(--panel)",
  color: "var(--text)",
};

export default function QACReportGenerator({
  onMessage,
  enqueueOp,
  updateOp,
  mode = "local",
  jobUrl = "",
  cacheRoot = "",
  buildSelector = "lastSuccessfulBuild",
  sourceRoot = "",
  onOpenEditor,
  onOpenArtifact,
}) {
  const isJenkinsMode = mode === "jenkins" && String(jobUrl || "").trim();
  const [oldVersion, setOldVersion] = useState(false);
  const [file, setFile] = useState(null);
  const [parsedData, setParsedData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [artifactItems, setArtifactItems] = useState([]);
  const [artifactLoading, setArtifactLoading] = useState(false);
  const [selectedArtifact, setSelectedArtifact] = useState("");
  const [impactLoadingKey, setImpactLoadingKey] = useState("");
  const [impactResult, setImpactResult] = useState(null);
  const [impactCache, setImpactCache] = useState({});
  const [deltaOnly, setDeltaOnly] = useState(false);
  const [batchAnalyzeCount, setBatchAnalyzeCount] = useState(5);
  const [batchRunning, setBatchRunning] = useState(false);
  const [reportPreview, setReportPreview] = useState({ path: "", title: "", text: "", loading: false, error: "" });

  const totals = parsedData?.totals || {};
  const totalRows = Object.values(totals);
  const levelSummary = totalRows.reduce(
    (acc, cur) => {
      acc.level_1 += cur.level_1 || 0;
      acc.level_2 += cur.level_2 || 0;
      acc.level_3 += cur.level_3 || 0;
      return acc;
    },
    { level_1: 0, level_2: 0, level_3: 0 }
  );

  const topMatrices = Object.entries(totals)
    .map(([matrix, levels]) => ({
      matrix,
      total: (levels.level_1 || 0) + (levels.level_2 || 0) + (levels.level_3 || 0),
      ...levels,
    }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 5);

  const sortedItems = useMemo(() => {
    const rows = Array.isArray(parsedData?.items) ? [...parsedData.items] : [];
    const priorityScore = (item) => {
      const severity = Math.max(
        Number(item?.values?.V_G?.warning_level || 0),
        Number(item?.values?.LEVEL?.warning_level || 0),
        Number(item?.values?.CALLING?.warning_level || 0),
        Number(item?.values?.CALLS?.warning_level || 0)
      );
      const impact = impactCache[String(item?.function_name || "")] || {};
      const summary = impact.summary || {};
      return severity * 10 + Number(summary.sts_impacted || 0) * 2 + Number(summary.suts_impacted || 0);
    };
    const score = (item) =>
      Math.max(
        Number(item?.values?.V_G?.warning_level || 0),
        Number(item?.values?.LEVEL?.warning_level || 0),
        Number(item?.values?.CALLING?.warning_level || 0),
        Number(item?.values?.CALLS?.warning_level || 0)
      );
    const filtered = rows.filter((item) => {
      if (!deltaOnly) return true;
      const impact = impactCache[String(item?.function_name || "")] || {};
      const summary = impact.summary || {};
      return Number(summary.sts_delta || 0) !== 0 || Number(summary.suts_delta || 0) !== 0;
    });
    filtered.sort((a, b) => {
      const diffPriority = priorityScore(b) - priorityScore(a);
      if (diffPriority !== 0) return diffPriority;
      const diff = score(b) - score(a);
      if (diff !== 0) return diff;
      return String(a?.function_name || "").localeCompare(String(b?.function_name || ""));
    });
    return filtered.slice(0, 80).map((item) => ({
      ...item,
      severityScore: score(item),
      priorityScore: priorityScore(item),
      impactSummary: (impactCache[String(item?.function_name || "")] || {}).summary || null,
    }));
  }, [parsedData, impactCache, deltaOnly]);

  const selectedArtifactMeta = useMemo(
    () => artifactItems.find((item) => item.rel_path === selectedArtifact) || null,
    [artifactItems, selectedArtifact]
  );

  const batchSummary = useMemo(() => {
    const rows = Object.entries(impactCache || {});
    if (rows.length === 0) {
      return {
        analyzed: 0,
        deltaRows: 0,
        impactedRows: 0,
        totalSts: 0,
        totalSuts: 0,
      };
    }
    let deltaRows = 0;
    let impactedRows = 0;
    let totalSts = 0;
    let totalSuts = 0;
    rows.forEach(([, payload]) => {
      const summary = payload?.summary || {};
      const sts = Number(summary.sts_impacted || 0);
      const suts = Number(summary.suts_impacted || 0);
      const stsDelta = Number(summary.sts_delta || 0);
      const sutsDelta = Number(summary.suts_delta || 0);
      totalSts += sts;
      totalSuts += suts;
      if (sts > 0 || suts > 0) impactedRows += 1;
      if (stsDelta !== 0 || sutsDelta !== 0) deltaRows += 1;
    });
    return {
      analyzed: rows.length,
      deltaRows,
      impactedRows,
      totalSts,
      totalSuts,
    };
  }, [impactCache]);

  const recommendationRows = useMemo(() => {
    return sortedItems
      .filter((item) => item.priorityScore > 0)
      .slice(0, 5)
      .map((item, index) => ({
        rank: index + 1,
        functionName: item.function_name,
        priorityScore: item.priorityScore || 0,
        severityScore: item.severityScore || 0,
        impactSummary: item.impactSummary || {},
        normalizedPath: item.normalized_path || "",
      }));
  }, [sortedItems]);

  const notify = useCallback(
    (text) => {
      setMessage(text);
      if (onMessage) onMessage(text);
    },
    [onMessage]
  );

  const loadArtifacts = useCallback(async () => {
    if (!isJenkinsMode) {
      setArtifactItems([]);
      setSelectedArtifact("");
      return;
    }
    setArtifactLoading(true);
    try {
      const data = await jsonApi(
        `/api/qac/jenkins-artifacts?job_url=${encodeURIComponent(jobUrl)}&cache_root=${encodeURIComponent(
          cacheRoot || ""
        )}&build_selector=${encodeURIComponent(buildSelector || "lastSuccessfulBuild")}`
      );
      const items = Array.isArray(data?.items) ? data.items : [];
      setArtifactItems(items);
      const preferred = items.find((item) => item.can_parse) || items[0] || null;
      setSelectedArtifact(preferred?.rel_path || "");
    } catch (e) {
      notify(`QAC artifact load failed: ${e.message}`);
    } finally {
      setArtifactLoading(false);
    }
  }, [isJenkinsMode, jobUrl, cacheRoot, buildSelector, notify]);

  useEffect(() => {
    loadArtifacts();
  }, [loadArtifacts]);

  const handleFileChange = useCallback((e) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
      setParsedData(null);
      setMessage("");
    }
  }, []);

  const handleParseUpload = useCallback(async () => {
    if (!file) {
      notify("Select a QAC HTML file first.");
      return;
    }
    setLoading(true);
    const opId = enqueueOp && enqueueOp("qac", "QAC parse start");
    try {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`/api/qac/parse?old_version=${oldVersion}`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setParsedData(data);
      notify("QAC parse complete.");
      if (opId && updateOp) updateOp(opId, { status: "success", message: "QAC parse complete" });
    } catch (e) {
      notify(`QAC parse failed: ${e.message}`);
      if (opId && updateOp) updateOp(opId, { status: "failed", message: e.message });
    } finally {
      setLoading(false);
    }
  }, [file, oldVersion, notify, enqueueOp, updateOp]);

  const handleParseCached = useCallback(async () => {
    if (!selectedArtifact) {
      notify("Select a Jenkins QAC artifact first.");
      return;
    }
    setLoading(true);
    const opId = enqueueOp && enqueueOp("qac", "Jenkins QAC parse start");
    try {
      const data = await jsonApi(
        `/api/qac/jenkins-parse?job_url=${encodeURIComponent(jobUrl)}&cache_root=${encodeURIComponent(
          cacheRoot || ""
        )}&build_selector=${encodeURIComponent(buildSelector || "lastSuccessfulBuild")}&rel_path=${encodeURIComponent(
          selectedArtifact
        )}&source_root=${encodeURIComponent(sourceRoot || "")}`
      );
      setParsedData(data);
      if (typeof data?.old_version === "boolean") {
        setOldVersion(Boolean(data.old_version));
      }
      notify("Jenkins QAC parse complete.");
      if (opId && updateOp) updateOp(opId, { status: "success", message: "Jenkins QAC parse complete" });
    } catch (e) {
      notify(`Jenkins QAC parse failed: ${e.message}`);
      if (opId && updateOp) updateOp(opId, { status: "failed", message: e.message });
    } finally {
      setLoading(false);
    }
  }, [selectedArtifact, jobUrl, cacheRoot, buildSelector, sourceRoot, notify, enqueueOp, updateOp]);

  const handleGenerateExcel = useCallback(async () => {
    setLoading(true);
    const opId = enqueueOp && enqueueOp("qac", "QAC Excel generation start");
    try {
      let res;
      if (isJenkinsMode && selectedArtifact) {
        res = await fetch(
          `/api/qac/jenkins-excel?job_url=${encodeURIComponent(jobUrl)}&cache_root=${encodeURIComponent(
            cacheRoot || ""
          )}&build_selector=${encodeURIComponent(buildSelector || "lastSuccessfulBuild")}&rel_path=${encodeURIComponent(
            selectedArtifact
          )}`
        );
      } else {
        if (!file) {
          notify("Select a QAC HTML file first.");
          setLoading(false);
          return;
        }
        const formData = new FormData();
        formData.append("file", file);
        res = await fetch(`/api/qac/generate-excel?old_version=${oldVersion}`, {
          method: "POST",
          body: formData,
        });
      }
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download =
        res.headers.get("Content-Disposition")?.split("filename=")[1]?.replace(/"/g, "") ||
        "qac_report.xlsx";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
      notify("QAC Excel generated.");
      if (opId && updateOp) updateOp(opId, { status: "success", message: "QAC Excel generated" });
    } catch (e) {
      notify(`QAC Excel generation failed: ${e.message}`);
      if (opId && updateOp) updateOp(opId, { status: "failed", message: e.message });
    } finally {
      setLoading(false);
    }
  }, [isJenkinsMode, selectedArtifact, jobUrl, cacheRoot, buildSelector, file, oldVersion, notify, enqueueOp, updateOp]);

  const handleAnalyzeImpact = useCallback(
    async (functionName) => {
      if (!isJenkinsMode || !functionName) return;
      setImpactLoadingKey(functionName);
      try {
        const data = await jsonApi(
          `/api/qac/jenkins-impact?job_url=${encodeURIComponent(jobUrl)}&cache_root=${encodeURIComponent(
            cacheRoot || ""
          )}&build_selector=${encodeURIComponent(buildSelector || "lastSuccessfulBuild")}&function_name=${encodeURIComponent(
            functionName
          )}`
        );
        setImpactResult(data || null);
        setImpactCache((prev) => ({ ...prev, [String(functionName)]: data || {} }));
        notify(`Impact analyzed: ${functionName}`);
      } catch (e) {
        notify(`Impact analysis failed: ${e.message}`);
      } finally {
        setImpactLoadingKey("");
      }
    },
    [isJenkinsMode, jobUrl, cacheRoot, buildSelector, notify]
  );

  const previewImpactReport = useCallback(async (path, title = "QAC Impact Report") => {
    if (!path) return;
    setReportPreview({ path, title, text: "", loading: true, error: "" });
    try {
      const res = await fetch("/api/local/editor/read-abs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, max_bytes: 200000 }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setReportPreview({
        path,
        title,
        text: String(data?.text || ""),
        loading: false,
        error: data?.truncated ? "Report truncated for preview." : "",
      });
    } catch (e) {
      setReportPreview({
        path,
        title,
        text: "",
        loading: false,
        error: e?.message || String(e),
      });
    }
  }, []);

  const handleBatchAnalyzeTop = useCallback(async () => {
    if (!isJenkinsMode || batchRunning) return;
    const limit = Math.max(1, Math.min(20, Number(batchAnalyzeCount || 5)));
    const targets = sortedItems.slice(0, limit).map((item) => String(item?.function_name || "").trim()).filter(Boolean);
    if (targets.length === 0) {
      notify("No QAC rows available for batch analysis.");
      return;
    }
    setBatchRunning(true);
    try {
      for (let i = 0; i < targets.length; i += 1) {
        const functionName = targets[i];
        setImpactLoadingKey(functionName);
        const data = await jsonApi(
          `/api/qac/jenkins-impact?job_url=${encodeURIComponent(jobUrl)}&cache_root=${encodeURIComponent(
            cacheRoot || ""
          )}&build_selector=${encodeURIComponent(buildSelector || "lastSuccessfulBuild")}&function_name=${encodeURIComponent(
            functionName
          )}`
        );
        setImpactCache((prev) => ({ ...prev, [functionName]: data || {} }));
        if (i === 0) setImpactResult(data || null);
        notify(`Batch impact ${i + 1}/${targets.length}: ${functionName}`);
      }
      notify(`Batch impact analysis complete: ${targets.length} functions.`);
    } catch (e) {
      notify(`Batch impact analysis failed: ${e.message}`);
    } finally {
      setImpactLoadingKey("");
      setBatchRunning(false);
    }
  }, [isJenkinsMode, batchRunning, batchAnalyzeCount, sortedItems, jobUrl, cacheRoot, buildSelector, notify]);

  return (
    <div style={{ padding: 20 }}>
      <h2>QAC Report</h2>

      <div style={{ marginBottom: 20 }}>
        <label>
          Version:
          <select
            value={String(oldVersion)}
            onChange={(e) => setOldVersion(e.target.value === "true")}
            style={{ marginLeft: 10 }}
          >
            <option value="false">Helix QAC</option>
            <option value="true">PRQA</option>
          </select>
        </label>
      </div>

      {isJenkinsMode ? (
        <div style={{ marginBottom: 20, padding: 14, border: "1px solid var(--border)", borderRadius: "var(--radius-md)" }}>
          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <strong>Jenkins cached artifacts</strong>
            <button type="button" onClick={loadArtifacts} disabled={artifactLoading} style={buttonStyle}>
              {artifactLoading ? "Refreshing..." : "Refresh"}
            </button>
          </div>
          <div className="hint" style={{ marginTop: 8 }}>
            Build selector: {buildSelector || "lastSuccessfulBuild"}
          </div>
          <div style={{ marginTop: 12 }}>
            <select
              value={selectedArtifact}
              onChange={(e) => setSelectedArtifact(e.target.value)}
              style={{ width: "100%", padding: 10, borderRadius: 8, backgroundColor: "var(--panel)", color: "var(--text)", border: "1px solid var(--border)" }}
            >
              <option value="">Select cached artifact</option>
              {artifactItems.map((item) => (
                <option key={item.rel_path} value={item.rel_path}>
                  {item.name} [{item.kind}] {item.can_parse ? "parse" : "view only"}
                </option>
              ))}
            </select>
          </div>
          {selectedArtifactMeta ? (
            <div style={{ marginTop: 10, fontSize: 12, color: "var(--text-muted)" }}>
              <div>Path: {selectedArtifactMeta.rel_path}</div>
              <div>Modified: {selectedArtifactMeta.modified_at}</div>
              <div>Mode: {selectedArtifactMeta.old_version ? "PRQA" : "Helix/Unknown"}</div>
            </div>
          ) : null}
        </div>
      ) : null}

      <div style={{ marginBottom: 20 }}>
        <label>
          Upload QAC HTML:
          <input type="file" accept=".html" onChange={handleFileChange} style={{ marginLeft: 10 }} />
        </label>
        {file ? <div style={{ marginTop: 6, color: "var(--text-muted)" }}>Selected file: {file.name}</div> : null}
      </div>

      <div style={{ marginBottom: 20, display: "flex", gap: 10, flexWrap: "wrap" }}>
        <button
          type="button"
          onClick={isJenkinsMode ? handleParseCached : handleParseUpload}
          disabled={loading || (isJenkinsMode ? !selectedArtifactMeta?.can_parse : !file)}
          style={{ ...buttonStyle, backgroundColor: "var(--color-success)", color: "var(--text-inverse)", border: "none" }}
        >
          {loading ? "Parsing..." : isJenkinsMode ? "Parse Jenkins artifact" : "Parse upload"}
        </button>
        <button
          type="button"
          onClick={handleGenerateExcel}
          disabled={loading || (!file && !(isJenkinsMode && selectedArtifact))}
          style={{ ...buttonStyle, backgroundColor: "var(--accent)", color: "var(--text-inverse)", border: "none" }}
        >
          {loading ? "Generating..." : "Download Excel"}
        </button>
      </div>

      {isJenkinsMode ? (
        <div style={{ marginBottom: 14, display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <label className="row" style={{ gap: 6 }}>
            <input type="checkbox" checked={deltaOnly} onChange={(e) => setDeltaOnly(Boolean(e.target.checked))} />
            Show analyzed rows with delta only
          </label>
          <label className="row" style={{ gap: 6 }}>
            Top N
            <input
              type="number"
              min="1"
              max="20"
              value={batchAnalyzeCount}
              onChange={(e) => setBatchAnalyzeCount(e.target.value)}
              style={{ width: 64 }}
            />
          </label>
          <button type="button" className="btn-outline" onClick={handleBatchAnalyzeTop} disabled={batchRunning || !parsedData}>
            {batchRunning ? "Batch analyzing..." : "Analyze top N"}
          </button>
          <span className="hint">Priority = severity + STS/SUTS impact count</span>
        </div>
      ) : null}

      {isJenkinsMode && batchSummary.analyzed > 0 ? (
        <div style={{ marginBottom: 20, padding: 15, backgroundColor: "var(--bg)", borderRadius: "var(--radius-sm)" }}>
          <strong>Batch Impact Summary</strong>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 10 }}>
            <div style={cardStyle}>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Analyzed</div>
              <div style={{ fontSize: 18, fontWeight: 600 }}>{batchSummary.analyzed}</div>
            </div>
            <div style={cardStyle}>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Impacted rows</div>
              <div style={{ fontSize: 18, fontWeight: 600 }}>{batchSummary.impactedRows}</div>
            </div>
            <div style={cardStyle}>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Delta rows</div>
              <div style={{ fontSize: 18, fontWeight: 600 }}>{batchSummary.deltaRows}</div>
            </div>
            <div style={cardStyle}>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Total STS hits</div>
              <div style={{ fontSize: 18, fontWeight: 600 }}>{batchSummary.totalSts}</div>
            </div>
            <div style={cardStyle}>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Total SUTS hits</div>
              <div style={{ fontSize: 18, fontWeight: 600 }}>{batchSummary.totalSuts}</div>
            </div>
          </div>
        </div>
      ) : null}

      {isJenkinsMode && recommendationRows.length > 0 ? (
        <div style={{ marginBottom: 20, padding: 15, backgroundColor: "var(--bg)", borderRadius: "var(--radius-sm)" }}>
          <strong>Recommended Fix Order</strong>
          <div className="hint" style={{ marginTop: 6 }}>
            Top functions ranked by severity and current STS/SUTS impact.
          </div>
          <table style={{ marginTop: 10, borderCollapse: "collapse", width: "100%" }}>
            <thead>
              <tr style={{ backgroundColor: "var(--sidebar)" }}>
                <th style={cellStyle}>Rank</th>
                <th style={cellStyle}>Function</th>
                <th style={cellStyle}>Priority</th>
                <th style={cellStyle}>Impact</th>
                <th style={cellStyle}>Action</th>
              </tr>
            </thead>
            <tbody>
              {recommendationRows.map((row) => (
                <tr key={row.functionName}>
                  <td style={cellStyle}>{row.rank}</td>
                  <td style={cellStyle}>
                    <div style={{ fontWeight: 600 }}>{row.functionName}</div>
                    {row.normalizedPath ? (
                      <div className="hint" style={{ marginTop: 4 }}>{row.normalizedPath}</div>
                    ) : null}
                  </td>
                  <td style={cellStyle}>
                    <div style={{ fontWeight: 700 }}>{row.priorityScore}</div>
                    <div className="hint">{`Severity L${row.severityScore}`}</div>
                  </td>
                  <td style={cellStyle}>
                    {`STS ${row.impactSummary.sts_impacted || 0} / SUTS ${row.impactSummary.suts_impacted || 0}`}
                  </td>
                  <td style={cellStyle}>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <button
                        type="button"
                        className="btn-outline"
                        disabled={!row.normalizedPath || typeof onOpenEditor !== "function"}
                        onClick={() => row.normalizedPath && onOpenEditor(row.normalizedPath, 0, row.functionName)}
                      >
                        Open file
                      </button>
                      <button
                        type="button"
                        className="btn-outline"
                        onClick={() => handleAnalyzeImpact(row.functionName)}
                        disabled={impactLoadingKey === row.functionName}
                      >
                        {impactLoadingKey === row.functionName ? "Analyzing..." : "Refresh impact"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {message ? (
        <div
          style={{
            marginBottom: 20,
            padding: 10,
            backgroundColor: message.toLowerCase().includes("failed") ? "var(--color-danger-soft)" : "var(--color-success-soft)",
            borderRadius: "var(--radius-sm)",
          }}
        >
          {message}
        </div>
      ) : null}

      {reportPreview.path ? (
        <div style={{ marginBottom: 20, padding: 15, backgroundColor: "var(--bg)", borderRadius: "var(--radius-sm)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
            <strong>{reportPreview.title}</strong>
            <span className="hint">{reportPreview.path.split(/[\\/]/).pop()}</span>
          </div>
          {reportPreview.loading ? <div className="hint" style={{ marginTop: 8 }}>Loading report...</div> : null}
          {reportPreview.error ? <div className="hint" style={{ marginTop: 8 }}>{reportPreview.error}</div> : null}
          {reportPreview.text ? (
            <ReportMarkdownPreview text={reportPreview.text} style={{ marginTop: 10, maxHeight: 320, overflow: "auto" }} />
          ) : null}
        </div>
      ) : null}

      {parsedData ? (
        <div style={{ marginBottom: 20, padding: 15, backgroundColor: "var(--bg)", borderRadius: "var(--radius-sm)" }}>
          <h3>Parsed Result</h3>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 10 }}>
            <div style={cardStyle}>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Items</div>
              <div style={{ fontSize: 18, fontWeight: 600 }}>{parsedData.item_count || 0}</div>
            </div>
            <div style={cardStyle}>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Level 1</div>
              <div style={{ fontSize: 18, fontWeight: 600 }}>{levelSummary.level_1}</div>
            </div>
            <div style={cardStyle}>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Level 2</div>
              <div style={{ fontSize: 18, fontWeight: 600 }}>{levelSummary.level_2}</div>
            </div>
            <div style={cardStyle}>
              <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Level 3</div>
              <div style={{ fontSize: 18, fontWeight: 600 }}>{levelSummary.level_3}</div>
            </div>
          </div>

          {parsedData.artifact_rel_path ? (
            <div className="hint" style={{ marginTop: 10 }}>
              Artifact: {parsedData.artifact_rel_path}
            </div>
          ) : null}

          <div style={{ marginTop: 16 }}>
            <strong>Totals</strong>
            <table style={{ marginTop: 10, borderCollapse: "collapse", width: "100%" }}>
              <thead>
                <tr style={{ backgroundColor: "var(--sidebar)" }}>
                  <th style={cellStyle}>Matrix</th>
                  <th style={cellStyle}>Level 1</th>
                  <th style={cellStyle}>Level 2</th>
                  <th style={cellStyle}>Level 3</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(totals).map(([matrix, row]) => (
                  <tr key={matrix}>
                    <td style={cellStyle}>{matrix}</td>
                    <td style={cellStyle}>{row.level_1}</td>
                    <td style={cellStyle}>{row.level_2}</td>
                    <td style={cellStyle}>{row.level_3}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {topMatrices.length > 0 ? (
            <div style={{ marginTop: 16 }}>
              <strong>Top warning matrices</strong>
              <table style={{ marginTop: 10, borderCollapse: "collapse", width: "100%" }}>
                <thead>
                  <tr style={{ backgroundColor: "var(--sidebar)" }}>
                    <th style={cellStyle}>Matrix</th>
                    <th style={cellStyle}>Total</th>
                    <th style={cellStyle}>Level 1</th>
                    <th style={cellStyle}>Level 2</th>
                    <th style={cellStyle}>Level 3</th>
                  </tr>
                </thead>
                <tbody>
                  {topMatrices.map((item) => (
                    <tr key={item.matrix}>
                      <td style={cellStyle}>{item.matrix}</td>
                      <td style={cellStyle}>{item.total}</td>
                      <td style={cellStyle}>{item.level_1}</td>
                      <td style={cellStyle}>{item.level_2}</td>
                      <td style={cellStyle}>{item.level_3}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {impactResult ? (
            <div style={{ marginTop: 16 }}>
              <strong>STS/SUTS Impact</strong>
              <div className="hint" style={{ marginTop: 6 }}>
                Function: {impactResult.function_name}
              </div>
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 10 }}>
                <div style={cardStyle}>
                  <div style={{ fontSize: 12, color: "var(--text-muted)" }}>STS hits</div>
                  <div style={{ fontSize: 18, fontWeight: 600 }}>{impactResult.summary?.sts_impacted || 0}</div>
                  <div className="hint">{`Δ ${impactResult.summary?.sts_delta || 0}`}</div>
                </div>
                <div style={cardStyle}>
                  <div style={{ fontSize: 12, color: "var(--text-muted)" }}>SUTS hits</div>
                  <div style={{ fontSize: 18, fontWeight: 600 }}>{impactResult.summary?.suts_impacted || 0}</div>
                  <div className="hint">{`Δ ${impactResult.summary?.suts_delta || 0}`}</div>
                </div>
              </div>
              {impactResult.impact_report_path ? (
                <div style={{ marginTop: 8, display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
                  <span className="hint">Impact report: {impactResult.impact_report_path}</span>
                  <button
                    type="button"
                    className="btn-outline"
                    onClick={() => previewImpactReport(impactResult.impact_report_path, `${impactResult.function_name} Impact Report`)}
                  >
                    Preview report
                  </button>
                </div>
              ) : null}
              {["sts", "suts"].map((kind) => {
                const data = impactResult[kind] || {};
                const compare = impactResult.compare?.[kind] || {};
                const matches = Array.isArray(data.matches) ? data.matches.slice(0, 6) : [];
                const previous = compare.previous || {};
                return (
                  <div key={kind} style={{ marginTop: 12 }}>
                    <div style={{ fontWeight: 600 }}>
                      {kind.toUpperCase()} - {data.filename || "no artifact"}
                    </div>
                    {previous?.filename ? (
                      <div className="hint" style={{ marginTop: 4 }}>
                        Previous: {previous.filename} ({previous.match_count || 0}) / Delta {compare.delta || 0}
                      </div>
                    ) : null}
                    {data.filename && typeof onOpenArtifact === "function" ? (
                      <div style={{ marginTop: 6 }}>
                        <button
                          type="button"
                          className="btn-outline"
                          onClick={() => onOpenArtifact(kind, sourceRoot)}
                        >
                          Open {kind.toUpperCase()} analyzer
                        </button>
                      </div>
                    ) : null}
                    {matches.length > 0 ? (
                      <table style={{ marginTop: 8, borderCollapse: "collapse", width: "100%" }}>
                        <thead>
                          <tr style={{ backgroundColor: "var(--sidebar)" }}>
                            <th style={cellStyle}>Sheet</th>
                            <th style={cellStyle}>Row</th>
                            <th style={cellStyle}>Cells</th>
                          </tr>
                        </thead>
                        <tbody>
                          {matches.map((match, index) => (
                            <tr key={`${kind}-${index}`}>
                              <td style={cellStyle}>{match.sheet}</td>
                              <td style={cellStyle}>{match.row_index}</td>
                              <td style={cellStyle}>{(match.cells || []).filter(Boolean).join(" | ")}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : (
                      <div className="hint" style={{ marginTop: 6 }}>No match in latest {kind.toUpperCase()} artifact.</div>
                    )}
                  </div>
                );
              })}
            </div>
          ) : null}

          {sortedItems.length > 0 ? (
            <div style={{ marginTop: 16 }}>
              <strong>Function rows</strong>
              <div className="hint" style={{ marginTop: 6 }}>
                Rows are sorted by highest warning level. Editor jump focuses near the function name when possible.
              </div>
              <table style={{ marginTop: 10, borderCollapse: "collapse", width: "100%" }}>
                <thead>
                  <tr style={{ backgroundColor: "var(--sidebar)" }}>
                    <th style={cellStyle}>Function</th>
                    <th style={cellStyle}>Severity</th>
                    <th style={cellStyle}>Priority</th>
                    <th style={cellStyle}>File</th>
                    <th style={cellStyle}>v(G)</th>
                    <th style={cellStyle}>LEVEL</th>
                    <th style={cellStyle}>CALLING</th>
                    <th style={cellStyle}>CALLS</th>
                    <th style={cellStyle}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {sortedItems.map((item, index) => {
                    const values = item.values || {};
                    const canOpen = Boolean(item.normalized_path && typeof onOpenEditor === "function");
                    return (
                      <tr key={`${item.function_name || "fn"}-${index}`}>
                        <td style={cellStyle}>{item.function_name || "-"}</td>
                        <td style={cellStyle}>
                          <span className="badge">{`L${item.severityScore || 0}`}</span>
                        </td>
                        <td style={cellStyle}>
                          <div style={{ fontWeight: 600 }}>{item.priorityScore || 0}</div>
                          {item.impactSummary ? (
                            <div className="hint">
                              {`STS ${item.impactSummary.sts_impacted || 0} / SUTS ${item.impactSummary.suts_impacted || 0}`}
                            </div>
                          ) : (
                            <div className="hint">impact n/a</div>
                          )}
                        </td>
                        <td style={cellStyle}>
                          <div>{item.file_name || "-"}</div>
                          {item.normalized_path ? (
                            <div style={{ marginTop: 4, fontSize: 12, color: "var(--text-muted)" }}>{item.normalized_path}</div>
                          ) : null}
                        </td>
                        <td style={cellStyle}>{values.V_G?.value || "-"} / L{values.V_G?.warning_level || 0}</td>
                        <td style={cellStyle}>{values.LEVEL?.value || "-"} / L{values.LEVEL?.warning_level || 0}</td>
                        <td style={cellStyle}>{values.CALLING?.value || "-"} / L{values.CALLING?.warning_level || 0}</td>
                        <td style={cellStyle}>{values.CALLS?.value || "-"} / L{values.CALLS?.warning_level || 0}</td>
                        <td style={cellStyle}>
                          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                            <button
                              type="button"
                              disabled={!canOpen}
                              onClick={() => canOpen && onOpenEditor(item.normalized_path, 0, item.function_name)}
                              style={{ ...buttonStyle, opacity: canOpen ? 1 : 0.5 }}
                            >
                              Open file
                            </button>
                            {isJenkinsMode ? (
                              <button
                                type="button"
                                onClick={() => handleAnalyzeImpact(item.function_name)}
                                disabled={!item.function_name || impactLoadingKey === item.function_name}
                                style={buttonStyle}
                              >
                                {impactLoadingKey === item.function_name ? "Analyzing..." : "Analyze impact"}
                              </button>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
