import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import UdsViewerWorkspace from "../components/UdsViewerWorkspace";
import StsGeneratorPanel from "../components/StsGeneratorPanel";
import SutsGeneratorPanel from "../components/SutsGeneratorPanel";
import {
  LocalScmPanel,
  LocalComplexityPanel,
  LocalHistoryPanel,
  LocalDocsPanel,
} from "../components/local";
import { normalizePct, formatPct, toneForStatus as statusTone } from "../utils/ui";

const LocalWorkflow = ({
  activeTab,
  setActiveTab,
  refreshLogs,
  loadComplexity,
  loadDocs,
  filteredFindings,
  toolCounts,
  toolOptions,
  filterTool,
  setFilterTool,
  searchTerm,
  setSearchTerm,
  renderHighlightedJson,
  summary,
  history,
  logs,
  scmMode,
  setScmMode,
  scmWorkdir,
  setScmWorkdir,
  scmRepoUrl,
  setScmRepoUrl,
  scmBranch,
  setScmBranch,
  scmDepth,
  setScmDepth,
  scmRevision,
  setScmRevision,
  runScm,
  scmOutput,
  kbEntries,
  loadKb,
  kbDeleteKey,
  setKbDeleteKey,
  deleteKb,
  complexityRows,
  docsHtml,
  logFiles,
  selectedLogPath,
  setSelectedLogPath,
  loadLogList,
  readLog,
  logContent,
  sessionId,
  hasReportDir,
  reportDir,
  onOpenEditorFile,
  reportFiles,
  loadReportFiles,
  downloadReportZip,
  config,
  localReports,
  localReportsLoading,
  localReportsError,
  loadLocalReports,
  generateLocalReports,
  downloadLocalReport,
  ragStatus,
  ragIngestResult,
  checkRagStatus,
  runRagIngest,
  runRagIngestFiles,
  updateConfig,
  localRagQuery,
  setLocalRagQuery,
  localRagCategory,
  setLocalRagCategory,
  localRagResults,
  localRagLoading,
  runLocalRagQuery,
  pickDirectory,
  pickFile,
  generateLocalUds,
  generateLocalSts,
  generateLocalSuts,
  onGoAnalyzer,
}) => {
  const tests = summary?.tests || {};
  const coverage = summary?.coverage || {};
  const qemu = summary?.qemu || {};
  const reportHealth = summary?.report_health || {};
  const missingReports = Array.isArray(reportHealth.missing)
    ? reportHealth.missing
    : [];
  const coverageMissing =
    missingReports.includes("coverage_xml") ||
    missingReports.includes("coverage_html");
  const runConfig = config || {};
  const [localUdsSourceRoot, setLocalUdsSourceRoot] = useState("");
  const [localUdsRefDoc, setLocalUdsRefDoc] = useState(null);
  const [localUdsSdsDoc, setLocalUdsSdsDoc] = useState(null);
  const [localUdsSrsDoc, setLocalUdsSrsDoc] = useState(null);
  const [localUdsReqFiles, setLocalUdsReqFiles] = useState([]);
  const [localUdsTemplate, setLocalUdsTemplate] = useState(null);
  const [localUdsComponentList, setLocalUdsComponentList] = useState(null);
  const [localUdsAiEnabled, setLocalUdsAiEnabled] = useState(true);
  const [localUdsAiDetailed, setLocalUdsAiDetailed] = useState(true);
  const [localUdsExpand, setLocalUdsExpand] = useState(true);
  const [localUdsRagTopK, setLocalUdsRagTopK] = useState(3);
  const [localUdsRagCategories, setLocalUdsRagCategories] = useState(
    "requirements,uds,code"
  );
  const [localUdsTags, setLocalUdsTags] = useState("srs,sds");
  const [localUdsResult, setLocalUdsResult] = useState(null);

  // STS state
  const [stsSrsPath, setStsSrsPath] = useState("");
  const [stsSdsPath, setStsSdsPath] = useState("");
  const [stsHsisPath, setStsHsisPath] = useState("");
  const [stsUdsPath, setStsUdsPath] = useState("");
  const [stsStpPath, setStsStpPath] = useState("");
  const [stsTemplatePath, setStsTemplatePath] = useState("");
  const [stsProjectId, setStsProjectId] = useState("");
  const [stsVersion, setStsVersion] = useState("v1.00");
  const [stsAsilLevel, setStsAsilLevel] = useState("");
  const [stsMaxTc, setStsMaxTc] = useState(5);
  const [stsLoading, setStsLoading] = useState(false);
  const [stsNotice, setStsNotice] = useState("");
  const [stsProgressPct, setStsProgressPct] = useState(0);
  const [stsProgressMsg, setStsProgressMsg] = useState("");
  const [stsFiles, setStsFiles] = useState([]);
  const [stsFilesLoading, setStsFilesLoading] = useState(false);
  const [stsViewData, setStsViewData] = useState(null);
  const [stsPreviewData, setStsPreviewData] = useState(null);
  const [stsPreviewLoading, setStsPreviewLoading] = useState(false);
  const [stsPreviewSheet, setStsPreviewSheet] = useState("");

  // SUTS state
  const [sutsSrsPath, setSutsSrsPath] = useState("");
  const [sutsSdsPath, setSutsSdsPath] = useState("");
  const [sutsHsisPath, setSutsHsisPath] = useState("");
  const [sutsUdsPath, setSutsUdsPath] = useState("");
  const [sutsTemplatePath, setSutsTemplatePath] = useState("");
  const [sutsProjectId, setSutsProjectId] = useState("");
  const [sutsVersion, setSutsVersion] = useState("v1.00");
  const [sutsAsilLevel, setSutsAsilLevel] = useState("");
  const [sutsMaxSeq, setSutsMaxSeq] = useState(6);
  const [sutsLoading, setSutsLoading] = useState(false);
  const [sutsNotice, setSutsNotice] = useState("");
  const [sutsProgressPct, setSutsProgressPct] = useState(0);
  const [sutsProgressMsg, setSutsProgressMsg] = useState("");
  const [sutsFiles, setSutsFiles] = useState([]);
  const [sutsFilesLoading, setSutsFilesLoading] = useState(false);
  const [sutsViewData, setSutsViewData] = useState(null);
  const [sutsPreviewData, setSutsPreviewData] = useState(null);
  const [sutsPreviewLoading, setSutsPreviewLoading] = useState(false);
  const [sutsPreviewSheet, setSutsPreviewSheet] = useState("");
  const [localUdsViewFilename, setLocalUdsViewFilename] = useState("");
  const [localUdsView, setLocalUdsView] = useState(null);
  const [localUdsViewLoading, setLocalUdsViewLoading] = useState(false);
  const [localUdsViewError, setLocalUdsViewError] = useState("");
  const [localUdsFiles, setLocalUdsFiles] = useState([]);
  const [localUdsFilesLoading, setLocalUdsFilesLoading] = useState(false);
  const [localUdsFilesError, setLocalUdsFilesError] = useState("");
  const [localUdsPickFilename, setLocalUdsPickFilename] = useState("");
  const [localUdsLoading, setLocalUdsLoading] = useState(false);
  const [localUdsNotice, setLocalUdsNotice] = useState("");
  const [localRagIngestLoading, setLocalRagIngestLoading] = useState(false);
  const [localRagIngestNotice, setLocalRagIngestNotice] = useState("");
  const [udsWizardStep, setUdsWizardStep] = useState(1);
  const [udsProgress, setUdsProgress] = useState(0);
  const [udsProgressLabel, setUdsProgressLabel] = useState("");
  const [logsRefreshing, setLogsRefreshing] = useState(false);
  const [logListLoading, setLogListLoading] = useState(false);
  const [reportFilesLoading, setReportFilesLoading] = useState(false);
  const [logsSubTab, setLogsSubTab] = useState("realtime");
  const [logSearch, setLogSearch] = useState("");
  const [logAutoFollow, setLogAutoFollow] = useState(true);
  const [findingsPageSize, setFindingsPageSize] = useState(50);
  const logContainerRef = useRef(null);
  const LOG_WINDOW_SIZE = 500;

  const pipelineSteps = useMemo(() => {
    const STEPS = [
      { key: "scm", label: "SCM (Legacy)", icon: "\u{1F4E6}" },
      { key: "build", label: "Build", icon: "\u{1F528}" },
      { key: "tests", label: "Test", icon: "\u{1F9EA}" },
      { key: "coverage", label: "Coverage", icon: "\u{1F4CA}" },
      { key: "static", label: "Analysis", icon: "\u{1F50D}" },
      { key: "agent", label: "Agent", icon: "\u{1F916}" },
    ];
    const getStatus = (k) => {
      if (!summary) return "pending";
      const s = summary;
      if (k === "scm") return s.scm?.ok === true ? "success" : s.scm?.ok === false ? "fail" : "pending";
      if (k === "build") return s.build?.ok === true ? "success" : s.build?.ok === false ? "fail" : "pending";
      if (k === "tests") return s.tests?.ok === true ? "success" : s.tests?.ok === false ? "fail" : "pending";
      if (k === "coverage") return s.coverage?.ok === true ? "success" : s.coverage?.ok === false ? "fail" : "pending";
      if (k === "static") {
        const tools = s.static_tools || {};
        const anyFail = Object.values(tools).some((t) => t && t.ok === false);
        const anyOk = Object.values(tools).some((t) => t && t.ok === true);
        return anyFail ? "fail" : anyOk ? "success" : "pending";
      }
      if (k === "agent") return s.agent?.iterations > 0 ? (s.agent?.stop_reason === "clean" ? "success" : "warning") : "pending";
      return "pending";
    };
    const isRunning = summary?.state === "running";
    if (!isRunning) {
      return STEPS.map((st) => ({ ...st, status: getStatus(st.key) }));
    }
    const firstPendingIdx = STEPS.findIndex((s) => getStatus(s.key) === "pending");
    return STEPS.map((st, idx) => {
      let status;
      if (firstPendingIdx === -1) {
        status = "success";
      } else if (idx < firstPendingIdx) {
        status = "success";
      } else if (idx === firstPendingIdx) {
        status = "running";
      } else {
        status = "pending";
      }
      return { ...st, status };
    });
  }, [summary]);

  const selectedCoreReqFiles = useMemo(() => {
    const tagged = [
      { file: localUdsSrsDoc, type: "srs" },
      { file: localUdsSdsDoc, type: "sds" },
      { file: localUdsRefDoc, type: "ref" },
    ].filter((t) => t.file);
    const unique = [];
    const seen = new Set();
    tagged.forEach(({ file, type }) => {
      const key = `${file.name || ""}:${file.size || 0}`;
      if (seen.has(key)) return;
      seen.add(key);
      unique.push({ file, type });
    });
    return unique;
  }, [localUdsSrsDoc, localUdsSdsDoc, localUdsRefDoc]);

  const formatHistoryCoverage = (entry) => {
    const pct = normalizePct(entry?.coverage);
    if (pct == null) {
      return entry?.coverage_missing ? "리포트 없음" : "-";
    }
    return `${pct.toFixed(1)}%`;
  };

  const loadStsFiles = useCallback(async () => {
    setStsFilesLoading(true);
    try {
      const res = await fetch("/api/local/sts/files");
      if (res.ok) { const data = await res.json(); setStsFiles(data?.files || []); }
    } catch { /* ignore */ } finally { setStsFilesLoading(false); }
  }, []);

  const loadStsPreview = useCallback(async (filename) => {
    if (!filename) return;
    setStsPreviewLoading(true);
    try {
      const res = await fetch(`/api/local/sts/preview/${encodeURIComponent(filename)}`);
      if (res.ok) { const data = await res.json(); setStsPreviewData(data); }
    } catch { /* ignore */ } finally { setStsPreviewLoading(false); }
  }, []);

  const onGenerateSts = useCallback(async () => {
    if (!generateLocalSts) return;
    if (!String(localUdsSourceRoot || "").trim()) { setStsNotice("소스 루트를 선택해주세요."); return; }
    setStsLoading(true);
    setStsNotice("STS 생성 중...");
    setStsProgressPct(5);
    setStsProgressMsg("SRS 분석 중...");
    const timer = setInterval(() => {
      setStsProgressPct((p) => {
        if (p < 30) { setStsProgressMsg("SRS/SDS 분석 중..."); return p + 2; }
        if (p < 70) { setStsProgressMsg("테스트 케이스 생성 중..."); return p + 1; }
        if (p < 90) { setStsProgressMsg("Excel 문서 생성 중..."); return p + 0.5; }
        return p;
      });
    }, 600);
    try {
      const res = await generateLocalSts({
        sourceRoot: localUdsSourceRoot,
        srsPath: stsSrsPath,
        sdsPath: stsSdsPath,
        hsisPath: stsHsisPath,
        udsPath: stsUdsPath,
        stpPath: stsStpPath,
        templatePath: stsTemplatePath,
        projectId: stsProjectId,
        version: stsVersion,
        asilLevel: stsAsilLevel,
        maxTc: stsMaxTc,
      });
      clearInterval(timer);
      if (res?.ok) {
        setStsProgressPct(100);
        setStsProgressMsg("생성 완료!");
        setStsNotice(`STS 생성 완료: ${res.filename || ""}`);
        await loadStsFiles();
        if (res.filename) await loadStsPreview(res.filename);
      } else {
        setStsProgressPct(0);
        setStsNotice("STS 생성 실패 — 서버 로그를 확인하세요.");
      }
    } catch (e) {
      clearInterval(timer);
      setStsProgressPct(0);
      setStsNotice(`STS 생성 오류: ${e?.message || String(e)}`);
    } finally {
      clearInterval(timer);
      setStsLoading(false);
    }
  }, [generateLocalSts, localUdsSourceRoot, stsSrsPath, stsSdsPath, stsHsisPath, stsUdsPath, stsStpPath, stsTemplatePath, stsProjectId, stsVersion, stsAsilLevel, stsMaxTc, loadStsFiles, loadStsPreview]);

  const loadSutsFiles = useCallback(async () => {
    setSutsFilesLoading(true);
    try {
      const res = await fetch("/api/local/suts/files");
      if (res.ok) { const data = await res.json(); setSutsFiles(data?.files || []); }
    } catch { /* ignore */ } finally { setSutsFilesLoading(false); }
  }, []);

  const loadSutsPreview = useCallback(async (filename) => {
    if (!filename) return;
    setSutsPreviewLoading(true);
    try {
      const res = await fetch(`/api/local/suts/preview/${encodeURIComponent(filename)}`);
      if (res.ok) { const data = await res.json(); setSutsPreviewData(data); }
    } catch { /* ignore */ } finally { setSutsPreviewLoading(false); }
  }, []);

  const onGenerateSuts = useCallback(async () => {
    if (!generateLocalSuts) return;
    if (!String(localUdsSourceRoot || "").trim()) { setSutsNotice("소스 루트를 선택해주세요."); return; }
    setSutsLoading(true);
    setSutsNotice("SUTS 생성 중...");
    setSutsProgressPct(5);
    setSutsProgressMsg("소스 코드 분석 중...");
    const timer = setInterval(() => {
      setSutsProgressPct((p) => {
        if (p < 40) { setSutsProgressMsg("함수 분석 중..."); return p + 2; }
        if (p < 75) { setSutsProgressMsg("시퀀스 생성 중..."); return p + 1; }
        if (p < 90) { setSutsProgressMsg("Excel 문서 생성 중..."); return p + 0.5; }
        return p;
      });
    }, 600);
    try {
      const res = await generateLocalSuts({
        sourceRoot: localUdsSourceRoot,
        srsPath: sutsSrsPath,
        sdsPath: sutsSdsPath,
        hsisPath: sutsHsisPath,
        udsPath: sutsUdsPath,
        templatePath: sutsTemplatePath,
        projectId: sutsProjectId,
        version: sutsVersion,
        asilLevel: sutsAsilLevel,
        maxSeq: sutsMaxSeq,
      });
      clearInterval(timer);
      if (res?.ok) {
        setSutsProgressPct(100);
        setSutsProgressMsg("생성 완료!");
        setSutsNotice(`SUTS 생성 완료: ${res.filename || ""}`);
        await loadSutsFiles();
        if (res.filename) await loadSutsPreview(res.filename);
      } else {
        setSutsProgressPct(0);
        setSutsNotice("SUTS 생성 실패 — 서버 로그를 확인하세요.");
      }
    } catch (e) {
      clearInterval(timer);
      setSutsProgressPct(0);
      setSutsNotice(`SUTS 생성 오류: ${e?.message || String(e)}`);
    } finally {
      clearInterval(timer);
      setSutsLoading(false);
    }
  }, [generateLocalSuts, localUdsSourceRoot, sutsSrsPath, sutsSdsPath, sutsHsisPath, sutsUdsPath, sutsTemplatePath, sutsProjectId, sutsVersion, sutsAsilLevel, sutsMaxSeq, loadSutsFiles, loadSutsPreview]);

  const formatHistoryTests = (entry) => {
    if (entry?.tests_enabled === false) return "테스트 비활성";
    const total = entry?.tests_total;
    const generated = entry?.tests_generated;
    const failed = entry?.tests_failed;
    const execCount = entry?.tests_exec_count;
    const execPassed = entry?.tests_exec_passed;
    const compileFailed = entry?.tests_compile_failed;
    const pieces = [];
    if (total != null || generated != null) {
      pieces.push(`생성 ${generated ?? "-"} / ${total ?? "-"}`);
    }
    if (execCount != null || execPassed != null) {
      pieces.push(`실행 ${execPassed ?? "-"} / ${execCount ?? "-"}`);
    }
    if (failed) {
      pieces.push(`실패 ${failed}`);
    }
    if (compileFailed) {
      pieces.push(`컴파일 실패 ${compileFailed}`);
    }
    if (pieces.length === 0) return "테스트 정보 없음";
    return pieces.join(" · ");
  };

  const coverageLine = normalizePct(
    coverage.line_rate_pct ?? coverage.line_rate
  );
  const coverageBranch = normalizePct(
    coverage.branch_rate_pct ?? coverage.branch_rate
  );
  const coverageFunc = normalizePct(
    coverage.function_rate_pct ?? coverage.function_rate ?? coverage.func_rate
  );
  const historyRows = Array.isArray(history)
    ? history.slice(-20).reverse()
    : [];
  const logLines = Array.isArray(logs) ? logs : [];

  const stripEmoji = (text) => {
    const raw = String(text ?? "");
    return raw.replace(/[\p{Extended_Pictographic}\uFE0F]/gu, "");
  };

  const sanitizedLogLines = useMemo(() => logLines.map((line) => stripEmoji(line)), [logLines]);

  useEffect(() => {
    if (logAutoFollow && logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logAutoFollow, sanitizedLogLines.length]);

  const topComplexity = Array.isArray(complexityRows)
    ? [...complexityRows]
        .map((row) => ({
          file: row?.file || row?.filename || "",
          func: row?.function || row?.func || row?.name || "",
          ccn: Number(row?.ccn || 0),
          nloc: Number(row?.nloc || 0),
          line: row?.line || row?.line_number || row?.start_line || "",
        }))
        .filter((row) => row.file && row.func)
        .sort((a, b) => b.ccn - a.ccn)
        .slice(0, 30)
    : [];

  const formatValue = (value) => {
    if (value === null || value === undefined || value === "") return "-";
    if (typeof value === "boolean") return value ? "Y" : "N";
    return String(value);
  };

  const formatAttemptCount = (value) => {
    if (value === null || value === undefined || value === "") return "-";
    if (typeof value === "number") return value;
    if (Array.isArray(value)) return value.length;
    if (typeof value === "object") {
      if (typeof value.count === "number") return value.count;
      if (typeof value.attempts === "number") return value.attempts;
      return 1;
    }
    return String(value);
  };

  const resolveLogPath = (path) => {
    if (!path) return "";
    const raw = String(path);
    const isAbs = /^[a-zA-Z]:[\\/]/.test(raw) || raw.startsWith("/");
    if (isAbs) return raw;
    if (reportDir)
      return `${reportDir.replace(/[\\/]+$/, "")}\\${raw}`.replace(/\\/g, "\\");
    return raw;
  };

  const [reportExtFilter, setReportExtFilter] = useState("all");
  const [reportQuery, setReportQuery] = useState("");
  const [reportScope, setReportScope] = useState("all");
  const [ragSourceExpanded, setRagSourceExpanded] = useState(() => {
    try {
      return localStorage.getItem("ragSourceExpanded") === "1";
    } catch {
      return false;
    }
  });
  const [ragSourceQuery, setRagSourceQuery] = useState("");
  const [ragSourceSort, setRagSourceSort] = useState(() => {
    try {
      return localStorage.getItem("ragSourceSort") || "count";
    } catch {
      return "count";
    }
  });

  const reportFileRows = Array.isArray(reportFiles?.files)
    ? reportFiles.files
    : [];
  const reportExtOptions = useMemo(() => {
    const counts = reportFiles?.ext_counts || {};
    return ["all", ...Object.keys(counts).sort()];
  }, [reportFiles]);

  const ragSourceList = useMemo(() => {
    const list = ragStatus?.stats?.source_list;
    const rows = Array.isArray(list) ? list : [];
    const sorted = [...rows].sort((a, b) => {
      if (ragSourceSort === "recent") {
        const at = String(a?.last_ts || "");
        const bt = String(b?.last_ts || "");
        return bt.localeCompare(at);
      }
      return Number(b?.count || 0) - Number(a?.count || 0);
    });
    return sorted;
  }, [ragStatus, ragSourceSort]);

  const filteredRagSourceList = useMemo(() => {
    const q = String(ragSourceQuery || "")
      .trim()
      .toLowerCase();
    if (!q) return ragSourceList;
    return ragSourceList.filter((row) =>
      String(row?.source || "")
        .toLowerCase()
        .includes(q)
    );
  }, [ragSourceList, ragSourceQuery]);

  useEffect(() => {
    try {
      localStorage.setItem("ragSourceExpanded", ragSourceExpanded ? "1" : "0");
    } catch {
      // ignore
    }
  }, [ragSourceExpanded]);

  useEffect(() => {
    try {
      localStorage.setItem("ragSourceSort", ragSourceSort || "count");
    } catch {
      // ignore
    }
  }, [ragSourceSort]);

  const filteredReportFiles = useMemo(() => {
    let rows = reportFileRows;
    if (reportScope === "report") {
      const tokens = ["jenkins_scan_export", "exports"];
      const seen = new Set();
      rows = rows.filter((item) => {
        const rel = String(item.rel_path || item.path || "")
          .replace(/\\/g, "/")
          .toLowerCase();
        if (
          tokens.some(
            (token) =>
              rel === token ||
              rel.startsWith(`${token}/`) ||
              rel.includes(`/${token}/`)
          )
        ) {
          return false;
        }
        const key = `${String(item.path || item.rel_path || "")
          .toLowerCase()
          .split(/[\\/]/)
          .pop()}::${item.size ?? ""}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });
    }
    return rows.filter((item) => {
      if (reportExtFilter !== "all" && item.ext !== reportExtFilter)
        return false;
      if (reportQuery) {
        return String(item.rel_path || item.path || "")
          .toLowerCase()
          .includes(reportQuery.toLowerCase());
      }
      return true;
    });
  }, [reportExtFilter, reportQuery, reportScope, reportFileRows]);

  const formatBytes = (value) => {
    const num = Number(value);
    if (!Number.isFinite(num)) return "-";
    if (num < 1024) return `${num} B`;
    if (num < 1024 ** 2) return `${(num / 1024).toFixed(1)} KB`;
    if (num < 1024 ** 3) return `${(num / 1024 ** 2).toFixed(1)} MB`;
    return `${(num / 1024 ** 3).toFixed(1)} GB`;
  };

  const formatTime = (value) => {
    const num = Number(value);
    if (!Number.isFinite(num)) return "-";
    return new Date(num * 1000).toLocaleString();
  };

  const flatLogFiles = useMemo(() => {
    if (!logFiles || typeof logFiles !== "object") return [];
    return Object.entries(logFiles).flatMap(([key, values]) => {
      if (!Array.isArray(values)) return [];
      return values.map((path) => ({ group: key, path }));
    });
  }, [logFiles]);

  const loadLocalUdsView = async (filename, params = {}) => {
    const name = String(filename || "").trim();
    if (!name) return;
    setLocalUdsViewLoading(true);
    setLocalUdsViewError("");
    try {
      const reportDir = String(config?.report_dir || "").trim();
      const qs = new URLSearchParams();
      if (reportDir) qs.set("report_dir", reportDir);
      Object.entries(params || {}).forEach(([k, v]) => {
        if (v === null || v === undefined || v === "") return;
        qs.set(k, String(v));
      });
      const query = qs.toString() ? `?${qs.toString()}` : "";
      const res = await fetch(
        `/api/local/uds/view/${encodeURIComponent(name)}${query}`
      );
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setLocalUdsView(data || null);
    } catch (e) {
      setLocalUdsViewError(e?.message || String(e));
      setLocalUdsView(null);
    } finally {
      setLocalUdsViewLoading(false);
    }
  };

  const loadLocalUdsFiles = useCallback(async () => {
    setLocalUdsFilesLoading(true);
    setLocalUdsFilesError("");
    try {
      const reportDir = String(config?.report_dir || "").trim();
      const qs = new URLSearchParams();
      if (reportDir) qs.set("report_dir", reportDir);
      const query = qs.toString() ? `?${qs.toString()}` : "";
      const res = await fetch(`/api/local/uds/files${query}`);
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      const rows = Array.isArray(data) ? data : [];
      setLocalUdsFiles(rows);
      setLocalUdsPickFilename((prev) => {
        if (String(prev || "").trim()) return prev;
        const first = String(rows[0]?.filename || "").trim();
        return first || prev;
      });
    } catch (e) {
      setLocalUdsFiles([]);
      setLocalUdsFilesError(e?.message || String(e));
    } finally {
      setLocalUdsFilesLoading(false);
    }
  }, [config?.report_dir]);

  useEffect(() => {
    if (activeTab !== "uds") return;
    loadLocalUdsFiles();
  }, [activeTab, loadLocalUdsFiles]);

  return (
    <div className="view-root">
      <div className="help-box">
        <h4>워크플로우 사용 방법</h4>
        <ul>
          <li>상단 탭으로 결과(품질/테스트/로그/SCM)를 전환합니다.</li>
          <li>좌측 패널에서 사전 점검 후 분석을 실행합니다.</li>
          <li>좌·우 스플리터로 패널 너비를 조절할 수 있습니다.</li>
        </ul>
      </div>
      <div className="pipeline-stepper">
        {pipelineSteps.map((st, idx) => (
          <div key={st.key} className={`pipeline-step step-${st.status}`}>
            <div className="step-icon">{st.icon}</div>
            <div className="step-label">{st.label}</div>
            {idx < pipelineSteps.length - 1 && <div className="step-connector" />}
          </div>
        ))}
      </div>
      <div className="tabs" role="tablist" aria-label="워크플로우 탭">
        <button
          role="tab"
          aria-selected={activeTab === "quality"}
          className={activeTab === "quality" ? "active" : ""}
          onClick={() => setActiveTab("quality")}
        >
          Code Quality
        </button>
        <button
          role="tab"
          aria-selected={activeTab === "testing"}
          className={activeTab === "testing" ? "active" : ""}
          onClick={() => setActiveTab("testing")}
        >
          Testing
        </button>
        <button
          role="tab"
          aria-selected={activeTab === "history"}
          className={activeTab === "history" ? "active" : ""}
          onClick={() => setActiveTab("history")}
        >
          History
        </button>
        <button
          role="tab"
          aria-selected={activeTab === "logs"}
          className={activeTab === "logs" ? "active" : ""}
          onClick={() => {
            setActiveTab("logs");
            refreshLogs();
          }}
        >
          Logs
        </button>
        <button
          role="tab"
          aria-selected={activeTab === "scm"}
          className={activeTab === "scm" ? "active" : ""}
          onClick={() => setActiveTab("scm")}
        >
          SCM
        </button>
        <button
          role="tab"
          aria-selected={activeTab === "knowledge"}
          className={activeTab === "knowledge" ? "active" : ""}
          onClick={() => setActiveTab("knowledge")}
        >
          Knowledge
        </button>
        <button
          role="tab"
          aria-selected={activeTab === "complexity"}
          className={activeTab === "complexity" ? "active" : ""}
          onClick={() => {
            setActiveTab("complexity");
            loadComplexity();
          }}
        >
          Complexity
        </button>
        <button
          role="tab"
          aria-selected={activeTab === "docs"}
          className={activeTab === "docs" ? "active" : ""}
          onClick={() => {
            setActiveTab("docs");
            loadDocs();
          }}
        >
          Docs
        </button>
        <button
          role="tab"
          aria-selected={activeTab === "uds"}
          className={activeTab === "uds" ? "active" : ""}
          onClick={() => setActiveTab("uds")}
        >
          UDS
        </button>
        <button
          role="tab"
          aria-selected={activeTab === "sts"}
          className={activeTab === "sts" ? "active" : ""}
          onClick={() => setActiveTab("sts")}
        >
          STS
        </button>
        <button
          role="tab"
          aria-selected={activeTab === "suts"}
          className={activeTab === "suts" ? "active" : ""}
          onClick={() => setActiveTab("suts")}
        >
          SUTS
        </button>
      </div>

      {activeTab === "quality" && (
        <div>
          <h3>Findings</h3>
          <div className="tool-cards">
            {Object.keys(toolCounts.counts || {}).length === 0 && (
              <div className="empty-state">
                <div className="empty-state-icon">🔍</div>
                <div className="empty-state-msg">분석 도구 결과가 없습니다</div>
                <div className="empty-state-hint">워크플로우를 실행하면 정적 분석 결과가 여기에 표시됩니다</div>
              </div>
            )}
            {Object.entries(toolCounts.counts || {}).map(([tool, count]) => {
              const sev = toolCounts.bySeverity?.[tool] || {
                error: 0,
                warning: 0,
                info: 0,
              };
              const statusClass =
                sev.error > 0
                  ? "status-error"
                  : sev.warning > 0
                    ? "status-warning"
                    : "status-ok";
              return (
                <div
                  key={tool}
                  className={`tool-card ${statusClass} ${filterTool === tool ? "active" : ""}`}
                  onClick={() => setFilterTool(tool)}
                >
                  <div className="tool-title">{tool}</div>
                  <div className="tool-count">{count}</div>
                </div>
              );
            })}
          </div>
          <div className="row">
            <select
              value={filterTool}
              onChange={(e) => setFilterTool(e.target.value)}
            >
              {toolOptions.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
            <input
              placeholder="검색어"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
            />
          </div>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <div className="hint">필터 결과: {filteredFindings.length}건</div>
            {filteredFindings.length > 0 && (
              <button type="button" className="btn-export" onClick={() => {
                const rows = [["tool", "severity", "file", "line", "message"]];
                (filteredFindings || []).forEach((f) => {
                  rows.push([
                    f.tool || "",
                    f.severity || f.level || "",
                    f.file || f.path || f.location?.file || "",
                    String(f.line || f.location?.line || ""),
                    (f.message || f.msg || f.description || "").replace(/"/g, '""')
                  ]);
                });
                const csv = rows.map((r) => r.map((c) => `"${c}"`).join(",")).join("\n");
                const blob = new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" });
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url; a.download = "findings.csv"; a.click();
                URL.revokeObjectURL(url);
              }}>CSV 내보내기</button>
            )}
          </div>
          {(() => {
            const grouped = {};
            (filteredFindings || []).forEach((f) => {
              const tool = String(f?.tool || "unknown").toLowerCase().trim();
              if (!grouped[tool]) grouped[tool] = [];
              grouped[tool].push(f);
            });
            const classifySev = (item) => {
              const raw = String(item?.severity || item?.level || item?.priority || item?.kind || "").toLowerCase();
              if (/error|critical|fatal|high/.test(raw)) return "error";
              if (/warn|medium/.test(raw)) return "warning";
              return "info";
            };
            return Object.keys(grouped).length > 0 ? (
              <div className="findings-scroll">
                {Object.entries(grouped).map(([tool, items]) => (
                  <details key={tool} className="quality-group" open>
                    <summary className="quality-group-header">
                      <span>{tool} ({items.length})</span>
                      <span className="quality-group-meta">
                        E{items.filter((i) => classifySev(i) === "error").length} W{items.filter((i) => classifySev(i) === "warning").length}
                      </span>
                    </summary>
                    <div className="quality-group-items">
                      {items.slice(0, findingsPageSize).map((f, idx) => {
                        const sev = classifySev(f);
                        const filePath = f.file || f.path || f.location?.file || "";
                        const lineNo = f.line || f.location?.line || null;
                        return (
                          <div key={idx} className="quality-issue-row">
                            <span className={`quality-sev-dot sev-${sev}`} />
                            <span className="text-ellipsis" title={f.message || f.msg || f.description || ""}>
                              {f.message || f.msg || f.description || "(메시지 없음)"}
                            </span>
                            {filePath && (
                              <span className="hint quality-file-path" title={filePath}>
                                {filePath.split(/[/\\]/).pop()}{lineNo ? `:${lineNo}` : ""}
                              </span>
                            )}
                            {filePath && onOpenEditorFile && (
                              <button type="button" className="issue-open-editor" onClick={() => onOpenEditorFile(filePath, lineNo)}>📂 열기</button>
                            )}
                          </div>
                        );
                      })}
                      {items.length > findingsPageSize && (
                        <button type="button" className="btn-load-more" onClick={() => setFindingsPageSize((p) => p + 50)}>
                          더 보기 ({items.length - findingsPageSize}건 남음)
                        </button>
                      )}
                    </div>
                  </details>
                ))}
              </div>
            ) : (
              <div className="empty-state">
                <div className="empty-state-icon">✅</div>
                <div className="empty-state-msg">발견된 이슈가 없습니다</div>
                <div className="empty-state-hint">필터 조건에 해당하는 이슈가 없거나 분석이 아직 실행되지 않았습니다</div>
              </div>
            );
          })()}
        </div>
      )}

      {activeTab === "testing" && (
        <div>
          <h3>Tests/Runtime</h3>
          <div className="summary-grid">
            <div className="summary-card">
              <div className="summary-title">테스트</div>
              <div className="summary-value">
                {tests.ok ? "OK" : tests.ok === false ? "FAIL" : "-"}
              </div>
              <div className="summary-sub">
                cases {tests.total ?? tests.count ?? "-"}
              </div>
            </div>
            <div
              className={`summary-card tone-${tests.ok === false ? "failed" : tests.ok ? "success" : "info"}`}
            >
              <div className="summary-title">Coverage (Line)</div>
              <div className="summary-value">
                {coverageLine != null ? `${coverageLine.toFixed(1)}%` : "-"}
              </div>
              <div className="summary-sub">
                threshold {formatPct(coverage.threshold)}
              </div>
            </div>
            <div
              className={`summary-card tone-${coverage?.ok === false ? "warning" : coverage?.ok ? "success" : "info"}`}
            >
              <div className="summary-title">Coverage (Branch)</div>
              <div className="summary-value">
                {coverageBranch != null ? `${coverageBranch.toFixed(1)}%` : "-"}
              </div>
              <div className="summary-sub">
                enabled {formatValue(coverage.enabled)}
              </div>
            </div>
            <div
              className={`summary-card tone-${qemu.ok === false ? "failed" : qemu.ok ? "success" : "info"}`}
            >
              <div className="summary-title">QEMU</div>
              <div className="summary-value">
                {qemu.ok ? "OK" : qemu.ok === false ? "FAIL" : "-"}
              </div>
              <div className="summary-sub">
                runtime {formatValue(qemu.runtime)}
              </div>
            </div>
          </div>
          {(() => {
            const thresh = coverage?.threshold != null ? Number(coverage.threshold) : null;
            return (
              <div className="summary-chart">
                <div className="bar-row">
                  <span className="bar-label">Line</span>
                  <div className="bar" style={{ position: "relative" }}>
                    <div className="bar-fill" style={{ width: `${Math.min(100, Math.max(0, coverageLine || 0))}%` }} />
                    {thresh != null && <div className="bar-threshold" style={{ left: `${Math.min(100, thresh)}%` }} title={`목표: ${thresh}%`} />}
                  </div>
                  <span className="bar-value">{coverageLine != null ? `${coverageLine.toFixed(1)}%` : "-"}</span>
                </div>
                <div className="bar-row">
                  <span className="bar-label">Branch</span>
                  <div className="bar" style={{ position: "relative" }}>
                    <div className="bar-fill" style={{ width: `${Math.min(100, Math.max(0, coverageBranch || 0))}%` }} />
                    {thresh != null && <div className="bar-threshold" style={{ left: `${Math.min(100, thresh)}%` }} title={`목표: ${thresh}%`} />}
                  </div>
                  <span className="bar-value">{coverageBranch != null ? `${coverageBranch.toFixed(1)}%` : "-"}</span>
                </div>
                <div className="bar-row">
                  <span className="bar-label">Func</span>
                  <div className="bar" style={{ position: "relative" }}>
                    <div className="bar-fill" style={{ width: `${Math.min(100, Math.max(0, coverageFunc || 0))}%` }} />
                    {thresh != null && <div className="bar-threshold" style={{ left: `${Math.min(100, thresh)}%` }} title={`목표: ${thresh}%`} />}
                  </div>
                  <span className="bar-value">{coverageFunc != null ? `${coverageFunc.toFixed(1)}%` : "-"}</span>
                </div>
              </div>
            );
          })()}
          {coverage?.html_report && (
            <div className="hint">
              <a href={coverage.html_report} target="_blank" rel="noopener noreferrer" className="cov-report-link">📊 커버리지 HTML 리포트 열기</a>
            </div>
          )}
          {coverage?.enabled && (coverage?.ok === false || coverageMissing) ? (
            <div className="empty-state tone-warning">
              <div className="empty-state-icon">📊</div>
              <div className="empty-state-msg">커버리지 리포트가 생성되지 않았습니다</div>
              <div className="empty-state-hint">
                {coverage?.reason ? `사유: ${coverage.reason}` : "커버리지 옵션을 활성화한 후 빌드를 다시 실행해 주세요"}
              </div>
            </div>
          ) : null}
          <div className="panel">
            <h4>테스트 생성/실행 요약</h4>
            <div className="test-summary-grid">
              {[
                { label: "Generated", value: tests.generated_count, tone: "info" },
                { label: "OK", value: tests.ok_count, tone: "success" },
                { label: "Failed", value: tests.failed_count, tone: tests.failed_count > 0 ? "failed" : "info" },
                { label: "Compile Failed", value: tests.compile_failed_count, tone: tests.compile_failed_count > 0 ? "failed" : "info" },
                { label: "Syntax Failed", value: tests.syntax_failed_count, tone: tests.syntax_failed_count > 0 ? "warning" : "info" },
                { label: "Missing Main", value: tests.missing_main_count, tone: tests.missing_main_count > 0 ? "warning" : "info" },
                { label: "Invalid Output", value: tests.invalid_output_count, tone: tests.invalid_output_count > 0 ? "warning" : "info" },
                { label: "Plan OK", value: tests.plan_ok_count, tone: "success" },
              ].map((c) => (
                <div key={c.label} className={`test-summary-card tone-${c.tone}`}>
                  <div className="tsc-value">{formatValue(c.value)}</div>
                  <div className="tsc-label">{c.label}</div>
                </div>
              ))}
            </div>
            {tests?.execution && (
              <div className="exec-section">
                <h5 className="exec-section-title">실행 결과</h5>
                <div className="test-summary-grid">
                  {[
                    { label: "Exec OK", value: String(tests.execution.ok ?? "-"), tone: tests.execution.ok ? "success" : "failed" },
                    { label: "Count", value: tests.execution.count, tone: "info" },
                    { label: "Passed", value: tests.execution.passed, tone: "success" },
                    { label: "Failed", value: tests.execution.failed, tone: tests.execution.failed > 0 ? "failed" : "info" },
                  ].map((c) => (
                    <div key={c.label} className={`test-summary-card tone-${c.tone}`}>
                      <div className="tsc-value">{formatValue(c.value)}</div>
                      <div className="tsc-label">{c.label}</div>
                    </div>
                  ))}
                </div>
                {tests.execution.note && (
                  <div className="hint exec-note">Note: {tests.execution.note}</div>
                )}
              </div>
            )}
          </div>
          <div className="panel">
            <h4>실행 설정</h4>
            <div className="run-config-grid">
              {[
                { key: "do_build", label: "Build" },
                { key: "do_coverage", label: "Coverage" },
                { key: "enable_test_gen", label: "Test Gen" },
                { key: "auto_run_tests", label: "Auto Run" },
              ].map((cfg) => (
                <span key={cfg.key} className={`run-config-chip ${runConfig[cfg.key] ? "chip-on" : "chip-off"}`}>
                  <span className="chip-dot" />
                  {cfg.label}
                </span>
              ))}
            </div>
          </div>
          {/* 커버리지 상세 (파일/모듈별) */}
          {(() => {
            const covPackages = coverage?.packages || coverage?.files || [];
            const covRows = (Array.isArray(covPackages) ? covPackages : Object.entries(covPackages).map(([name, data]) => ({ name, ...data }))).slice(0, 50);
            if (covRows.length === 0) return null;
            return (
              <div className="panel">
                <h4>파일/모듈별 커버리지</h4>
                <table className="coverage-detail-table">
                  <thead>
                    <tr>
                      <th>파일/모듈</th>
                      <th>Line %</th>
                      <th>Branch %</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {covRows.map((row, i) => {
                      const name = row.name || row.filename || row.file || `file-${i}`;
                      const lp = normalizePct(row.line_rate_pct ?? row.line_rate ?? row.lineRate);
                      const bp = normalizePct(row.branch_rate_pct ?? row.branch_rate ?? row.branchRate);
                      const lpCls = lp != null ? (lp < 50 ? 'cov-low' : lp < 80 ? 'cov-mid' : 'cov-ok') : '';
                      return (
                        <tr key={name}>
                          <td title={name} className="cell-ellipsis">{name.split(/[/\\]/).pop()}</td>
                          <td>
                            <span className={lpCls}>{lp != null ? `${lp.toFixed(1)}%` : '-'}</span>
                            {lp != null && (
                              <span className="coverage-mini-bar"><span className={`cov-bar-fill ${lp < 50 ? 'cov-low' : lp < 80 ? 'cov-mid' : 'cov-high'}`} style={{ width: `${lp}%` }} /></span>
                            )}
                          </td>
                          <td>{bp != null ? `${bp.toFixed(1)}%` : '-'}</td>
                          <td>
                            {(row.path || row.file || row.filename) && onOpenEditorFile && (
                              <button type="button" className="issue-open-editor" onClick={() => onOpenEditorFile(row.path || row.file || row.filename)}>📂</button>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            );
          })()}
          {/* 테스트 계획서 패널 */}
          <div className="test-plan-panel">
            <h5>테스트 계획서</h5>
            {tests.plan_ok_count > 0 || tests.generated_count > 0 ? (
              <>
                <div className="test-summary-grid test-plan-grid">
                  <div className="test-summary-card tone-success">
                    <div className="tsc-value">{formatValue(tests.plan_ok_count)}</div>
                    <div className="tsc-label">Plan OK</div>
                  </div>
                  <div className="test-summary-card tone-info">
                    <div className="tsc-value">{formatValue(tests.generated_count)}</div>
                    <div className="tsc-label">Generated</div>
                  </div>
                </div>
                {tests.test_plans && Array.isArray(tests.test_plans) && tests.test_plans.length > 0 ? (
                  <ul className="test-plan-list">
                    {tests.test_plans.map((plan, idx) => (
                      <li key={idx}>
                        <span>{plan.name || plan.file || `Plan ${idx + 1}`}</span>
                        {(plan.file || plan.path) && onOpenEditorFile && (
                          <button type="button" className="issue-open-editor" onClick={() => onOpenEditorFile(plan.file || plan.path)}>📂 열기</button>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <div className="hint">개별 테스트 계획 파일 목록은 Analyzer 탭에서 확인할 수 있습니다.</div>
                )}
              </>
            ) : (
              <div className="test-plan-empty">
                테스트 계획이 아직 생성되지 않았습니다.<br />
                테스트 생성 워크플로우를 실행하여 계획을 생성하세요.
              </div>
            )}
          </div>

          {/* 테스트 생성 결과 상세 */}
          {Array.isArray(tests.results) && tests.results.length > 0 && (
            <div className="panel test-gen-detail-panel">
              <h4>테스트 생성 상세 결과</h4>
              <table className="coverage-detail-table">
                <thead>
                  <tr>
                    <th>함수 / 파일</th>
                    <th>계획</th>
                    <th>코드생성</th>
                    <th>컴파일</th>
                    <th>실행</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {tests.results.map((r, idx) => {
                    const label = r.function || r.name || r.test_file || `Test ${idx + 1}`;
                    return (
                      <tr key={idx}>
                        <td title={label} className="cell-ellipsis">{label}</td>
                        <td><span className={`status-chip tone-${r.plan_ok ? "success" : r.plan_ok === false ? "failed" : "info"}`}>{r.plan_ok ? "OK" : r.plan_ok === false ? "FAIL" : "-"}</span></td>
                        <td><span className={`status-chip tone-${r.generated ? "success" : r.generated === false ? "failed" : "info"}`}>{r.generated ? "OK" : r.generated === false ? "FAIL" : "-"}</span></td>
                        <td><span className={`status-chip tone-${r.compile_ok ? "success" : r.compile_ok === false ? "failed" : "info"}`}>{r.compile_ok ? "OK" : r.compile_ok === false ? "FAIL" : "-"}</span></td>
                        <td><span className={`status-chip tone-${r.exec_ok ? "success" : r.exec_ok === false ? "failed" : "info"}`}>{r.exec_ok ? "OK" : r.exec_ok === false ? "FAIL" : "-"}</span></td>
                        <td>
                          {(r.test_file || r.plan_file) && onOpenEditorFile && (
                            <button type="button" className="issue-open-editor" onClick={() => onOpenEditorFile(r.test_file || r.plan_file)}>📂</button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {tests.cmake_generated != null && (
                <div className="hint">CMake 생성: {tests.cmake_generated ? "OK" : "FAIL"}</div>
              )}
            </div>
          )}

          {/* AI Agent 실행 이력 */}
          {summary?.agent && (
            <div className="agent-detail-panel">
              <h4>AI Agent 실행 이력</h4>
              <div className="summary-grid">
                <div className={`summary-card tone-${summary.agent.stop_reason === "clean" ? "success" : summary.agent.iterations > 0 ? "warning" : "info"}`}>
                  <div className="summary-title">Iterations</div>
                  <div className="summary-value">{summary.agent.iterations ?? 0}</div>
                </div>
                <div className="summary-card">
                  <div className="summary-title">Stop Reason</div>
                  <div className="summary-value">{summary.agent.stop_reason || "-"}</div>
                </div>
                <div className="summary-card">
                  <div className="summary-title">Patch Mode</div>
                  <div className="summary-value">{summary.agent.patch_mode || "-"}</div>
                </div>
                <div className="summary-card">
                  <div className="summary-title">Patches</div>
                  <div className="summary-value">{Array.isArray(summary.agent.patch_files) ? summary.agent.patch_files.length : 0}</div>
                </div>
              </div>

              {Array.isArray(summary.agent.history) && summary.agent.history.length > 0 && (
                <div className="agent-history-list">
                  <h5>Iteration 상세</h5>
                  {summary.agent.history.map((h, idx) => (
                    <details key={idx} className="agent-iter-card">
                      <summary className="list-item">
                        <span className={`status-chip tone-${h.fixer?.final_ok ? "success" : "warning"}`}>#{h.iter ?? idx + 1}</span>
                        <span className="list-snippet">{h.fix_mode || "-"}</span>
                        <span className="list-snippet">이슈 {h.issue_count ?? "-"}건</span>
                        <span className="list-snippet">LLM {formatAttemptCount(h.fixer?.llm_attempts)}회</span>
                        <span className={`status-chip tone-${h.fixer?.final_ok ? "success" : "failed"}`}>{h.fixer?.final_ok ? "OK" : "FAIL"}</span>
                      </summary>
                      <div className="agent-iter-detail">
                        {h.planner?.notes_preview && <div className="hint">Planner: {h.planner.notes_preview}</div>}
                        {h.fixer?.plan_b && <div className="hint">Plan B 적용됨</div>}
                      </div>
                    </details>
                  ))}
                </div>
              )}

              {Array.isArray(summary.agent.applied_changes) && summary.agent.applied_changes.length > 0 && (
                <div className="agent-patches">
                  <h5>적용된 패치</h5>
                  <div className="list">
                    {summary.agent.applied_changes.map((ch, idx) => (
                      <div key={idx} className="list-item">
                        <span className={`status-chip tone-${ch.status === "applied" ? "success" : "warning"}`}>{ch.status || "patch"}</span>
                        <span className="list-text text-ellipsis">{ch.file || "-"}</span>
                        {ch.line && <span className="list-snippet">L{ch.line}</span>}
                        {ch.file && onOpenEditorFile && (
                          <button type="button" className="issue-open-editor" onClick={() => onOpenEditorFile(ch.file, ch.line)}>열기</button>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {(!summary.agent.history || summary.agent.history.length === 0) && (!summary.agent.applied_changes || summary.agent.applied_changes.length === 0) && (
                <div className="empty-state">
                  <div className="empty-state-msg">Agent 상세 이력 없음</div>
                  <div className="empty-state-hint">워크플로우 실행 후 Agent가 동작하면 상세 이력이 여기에 표시됩니다</div>
                </div>
              )}
            </div>
          )}

          {/* AI 모델/토큰 사용량 */}
          {(summary?.agent?.model || summary?.agent?.token_usage || summary?.ai_stats) && (() => {
            const aiStats = summary.ai_stats || {};
            const tokenUsage = summary.agent?.token_usage || aiStats.token_usage || {};
            const modelName = summary.agent?.model || aiStats.model || "-";
            const llmCalls = summary.agent?.llm_calls ?? aiStats.llm_calls ?? null;
            return (
              <div className="panel ai-token-panel">
                <h4>AI 모델 / 토큰 사용량</h4>
                <div className="summary-grid">
                  <div className="summary-card">
                    <div className="summary-title">모델</div>
                    <div className="summary-value" style={{ fontSize: "0.9em" }}>{modelName}</div>
                  </div>
                  <div className="summary-card">
                    <div className="summary-title">입력 토큰</div>
                    <div className="summary-value">{tokenUsage.input != null ? tokenUsage.input.toLocaleString() : "-"}</div>
                    {tokenUsage.max_input && <div className="summary-sub">한도: {tokenUsage.max_input.toLocaleString()}</div>}
                  </div>
                  <div className="summary-card">
                    <div className="summary-title">출력 토큰</div>
                    <div className="summary-value">{tokenUsage.output != null ? tokenUsage.output.toLocaleString() : "-"}</div>
                    {tokenUsage.max_output && <div className="summary-sub">한도: {tokenUsage.max_output.toLocaleString()}</div>}
                  </div>
                  {llmCalls != null && (
                    <div className="summary-card">
                      <div className="summary-title">LLM 호출</div>
                      <div className="summary-value">{llmCalls}회</div>
                    </div>
                  )}
                </div>
              </div>
            );
          })()}

          {/* 동적 분석 결과 */}
          {(qemu.ok != null || summary?.asan || summary?.fuzzing) && (
            <div className="dynamic-analysis-panel">
              <h4>동적 분석</h4>
              <div className="summary-grid">
                <div className={`summary-card tone-${qemu.ok === false ? "failed" : qemu.ok ? "success" : "info"}`}>
                  <div className="summary-title">QEMU</div>
                  <div className="summary-value">{qemu.ok ? "OK" : qemu.ok === false ? "FAIL" : "-"}</div>
                  <div className="summary-sub">runtime {qemu.runtime || "-"}</div>
                </div>
                {summary?.asan && (
                  <div className={`summary-card tone-${summary.asan.ok === false ? "failed" : summary.asan.ok ? "success" : "info"}`}>
                    <div className="summary-title">ASan</div>
                    <div className="summary-value">{summary.asan.ok ? "CLEAN" : summary.asan.ok === false ? "DETECTED" : "-"}</div>
                    <div className="summary-sub">{summary.asan.issues_count ? `${summary.asan.issues_count}건` : summary.asan.enabled ? "활성" : "비활성"}</div>
                  </div>
                )}
                {summary?.fuzzing && (
                  <div className={`summary-card tone-${summary.fuzzing.crash ? "failed" : summary.fuzzing.ok ? "success" : "info"}`}>
                    <div className="summary-title">Fuzzing</div>
                    <div className="summary-value">{summary.fuzzing.crash ? "CRASH" : summary.fuzzing.ok ? "OK" : "-"}</div>
                    <div className="summary-sub">{summary.fuzzing.runtime || "-"}</div>
                  </div>
                )}
              </div>
              {qemu.error && <div className="hint">QEMU 에러: {qemu.error}</div>}
              {qemu.elf_file && <div className="hint">ELF: {qemu.elf_file}</div>}
              {Array.isArray(summary?.fuzzing?.crash_files) && summary.fuzzing.crash_files.length > 0 && (
                <div className="agent-patches">
                  <h5>크래시 파일</h5>
                  <div className="list">
                    {summary.fuzzing.crash_files.map((f, idx) => (
                      <div key={idx} className="list-item">
                        <span className="list-text text-ellipsis">{f}</span>
                        {onOpenEditorFile && <button type="button" className="issue-open-editor" onClick={() => onOpenEditorFile(f)}>열기</button>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {activeTab === "history" && (
        <LocalHistoryPanel
          historyRows={historyRows}
          history={history}
          statusTone={statusTone}
          formatValue={formatValue}
          formatHistoryTests={formatHistoryTests}
          formatHistoryCoverage={formatHistoryCoverage}
        />
      )}

      {activeTab === "logs" && (
        <div>
          <h3>Logs</h3>
          <div className="tabs sub-tabs" role="tablist" aria-label="로그 서브탭">
            <button type="button" role="tab" aria-selected={logsSubTab === "realtime"} className={logsSubTab === "realtime" ? "active" : ""} onClick={() => setLogsSubTab("realtime")}>
              실시간 로그
            </button>
            <button type="button" role="tab" aria-selected={logsSubTab === "reports"} className={logsSubTab === "reports" ? "active" : ""} onClick={() => setLogsSubTab("reports")}>
              리포트 파일
            </button>
          </div>

          {logsSubTab === "realtime" && (() => {
            const filtered = logSearch
              ? sanitizedLogLines.filter((l) => l.toLowerCase().includes(logSearch.toLowerCase()))
              : sanitizedLogLines;
            const total = filtered.length;
            const sliced = total > LOG_WINDOW_SIZE ? filtered.slice(total - LOG_WINDOW_SIZE) : filtered;
            const skipped = total - sliced.length;
            return (
              <div>
                <div className="row log-toolbar">
                  <button onClick={async () => { setLogsRefreshing(true); try { await refreshLogs(); } finally { setLogsRefreshing(false); } }} disabled={!sessionId || logsRefreshing}>{logsRefreshing ? "로딩..." : "새로고침"}</button>
                  <input className="log-search-input" placeholder="로그 검색..." value={logSearch} onChange={(e) => setLogSearch(e.target.value)} />
                  <label className="log-follow-label">
                    <input type="checkbox" checked={logAutoFollow} onChange={(e) => setLogAutoFollow(e.target.checked)} />
                    Auto-follow
                  </label>
                  <span className="hint">
                    {logSearch ? `${total}건 일치 / ` : ""}전체 {sanitizedLogLines.length}줄
                  </span>
                </div>
                {skipped > 0 && <div className="hint">... {skipped}줄 생략 (최근 {LOG_WINDOW_SIZE}줄 표시)</div>}
                <div className="log-viewer" ref={logContainerRef}>
                  {sliced.map((line, idx) => {
                    const lower = line.toLowerCase();
                    const level = lower.includes("error") || lower.includes("fail") ? "error"
                      : lower.includes("warn") ? "warn"
                      : lower.includes("success") || lower.includes("pass") ? "success"
                      : "";
                    return (
                      <div key={skipped + idx} className={`log-line ${level ? `log-${level}` : ""}`}>
                        <span className="log-lineno">{skipped + idx + 1}</span>
                        {logSearch && line.toLowerCase().includes(logSearch.toLowerCase())
                          ? (() => {
                              const i = line.toLowerCase().indexOf(logSearch.toLowerCase());
                              return (<><span>{line.slice(0, i)}</span><mark className="log-highlight">{line.slice(i, i + logSearch.length)}</mark><span>{line.slice(i + logSearch.length)}</span></>);
                            })()
                          : <span>{line}</span>
                        }
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })()}

          {logsSubTab === "reports" && (
            <div>
              <div className="row">
                <button onClick={async () => { setLogListLoading(true); try { await loadLogList(); } finally { setLogListLoading(false); } }} disabled={!sessionId || logListLoading}>{logListLoading ? "로딩..." : "로그 목록"}</button>
                <input placeholder="상대 경로" value={selectedLogPath} onChange={(e) => setSelectedLogPath(e.target.value)} />
                <button onClick={() => readLog(selectedLogPath)} disabled={!selectedLogPath}>읽기</button>
              </div>
              <div className="list">
                {flatLogFiles.map((item) => (
                  <button key={`${item.group}-${item.path}`} className="list-item" onClick={() => { readLog(item.path); const resolved = resolveLogPath(item.path); if (onOpenEditorFile && resolved) onOpenEditorFile(resolved); }}>
                    <span className="list-text">{item.group}</span>
                    <span className="list-snippet">{item.path}</span>
                  </button>
                ))}
                {flatLogFiles.length === 0 && (<div className="empty">로그 파일 없음</div>)}
              </div>
              <pre className="json">{logContent}</pre>
              <h4>Report Files</h4>
              <div className="row">
                <button onClick={async () => { setReportFilesLoading(true); try { await loadReportFiles(); } finally { setReportFilesLoading(false); } }} disabled={!sessionId || reportFilesLoading}>{reportFilesLoading ? "로딩..." : "파일 목록"}</button>
                <button onClick={() => downloadReportZip && downloadReportZip(filteredReportFiles.map((item) => item.rel_path || item.path))} disabled={!sessionId || filteredReportFiles.length === 0}>ZIP 다운로드(필터 적용)</button>
                <select value={reportScope} onChange={(e) => setReportScope(e.target.value)}>
                  <option value="all">전체 모드</option>
                  <option value="report">리포트 전용(중복 제거)</option>
                </select>
                <select value={reportExtFilter} onChange={(e) => setReportExtFilter(e.target.value)}>
                  {reportExtOptions.map((opt) => (<option key={opt} value={opt}>{opt}</option>))}
                </select>
                <input placeholder="파일 검색" value={reportQuery} onChange={(e) => setReportQuery(e.target.value)} />
              </div>
              <div className="list">
                {filteredReportFiles.map((item) => (
                  <div key={item.rel_path || item.path} className="list-item">
                    <span className="list-text">{item.rel_path || item.path}</span>
                    <span className="list-snippet">{formatBytes(item.size)} · {formatTime(item.mtime)}</span>
                    <div className="row">
                      <a className="btn-link" href={`/api/sessions/${sessionId}/report/files/download?path=${encodeURIComponent(item.rel_path || item.path)}`}>다운로드</a>
                      <button type="button" className="btn-outline" onClick={() => { const resolved = resolveLogPath(item.rel_path || item.path); if (onOpenEditorFile && resolved) onOpenEditorFile(resolved); }}>에디터 열기</button>
                    </div>
                  </div>
                ))}
                {filteredReportFiles.length === 0 && (<div className="empty">파일 없음</div>)}
              </div>
            </div>
          )}
        </div>
      )}

      {activeTab === "scm" && (
        <div>
          <div className="card" style={{ padding: 14, marginBottom: 12 }}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <strong>SCM Legacy Panel</strong>
              {typeof onGoAnalyzer === "function" ? (
                <button type="button" className="btn-outline" onClick={onGoAnalyzer}>
                  Open Analyzer
                </button>
              ) : null}
            </div>
            <div className="hint" style={{ marginTop: 6 }}>
              변경 감지, 영향 분석, AUTO/FLAG 결과 확인의 기본 진입점은 이제 Analyzer입니다. 이 탭은 기존 흐름 호환을 위해 남겨둔 legacy 패널입니다.
            </div>
          </div>
          <LocalScmPanel
            scmMode={scmMode}
            setScmMode={setScmMode}
            scmWorkdir={scmWorkdir}
            setScmWorkdir={setScmWorkdir}
            scmRepoUrl={scmRepoUrl}
            setScmRepoUrl={setScmRepoUrl}
            scmBranch={scmBranch}
            setScmBranch={setScmBranch}
            scmDepth={scmDepth}
            setScmDepth={setScmDepth}
            scmRevision={scmRevision}
            setScmRevision={setScmRevision}
            runScm={runScm}
            scmOutput={scmOutput}
          />
        </div>
      )}

      {activeTab === "knowledge" && (
        <div>
          <h3>Knowledge Base</h3>
          <div className="panel">
            <h4>RAG 상태</h4>
            <div className="row">
              <button onClick={checkRagStatus} disabled={!checkRagStatus}>
                상태 확인
              </button>
              <button
                onClick={runRagIngest}
                disabled={!hasReportDir || !runRagIngest}
              >
                인제스트 실행
              </button>
            </div>
            <div className="row">
              {Object.entries(config?.rag_stage_enable || {}).map(
                ([key, value]) => (
                  <label key={key} className="full-row">
                    <input
                      type="checkbox"
                      checked={value !== false}
                      onChange={(e) => {
                        if (!updateConfig) return;
                        const next = { ...(config?.rag_stage_enable || {}) };
                        next[key] = e.target.checked;
                        updateConfig("rag_stage_enable", next);
                      }}
                    />
                    RAG {key}
                  </label>
                )
              )}
            </div>
            <div className="row">
              <label className="full-row">
                <input
                  type="checkbox"
                  checked={Boolean(config?.auto_fix_on_fail)}
                  onChange={(e) =>
                    updateConfig &&
                    updateConfig("auto_fix_on_fail", e.target.checked)
                  }
                />
                Auto-fix on fail
              </label>
              <label className="full-row">
                <span className="config-label">Patch mode</span>
                <select
                  value={
                    config?.agent_patch_mode || config?.patch_mode || "auto"
                  }
                  onChange={(e) => {
                    if (!updateConfig) return;
                    updateConfig("agent_patch_mode", e.target.value);
                    updateConfig("patch_mode", e.target.value);
                  }}
                  className="config-input-offset"
                >
                  <option value="auto">auto</option>
                  <option value="review">review</option>
                  <option value="off">off</option>
                </select>
              </label>
              {["build", "tests", "syntax", "static"].map((stage) => {
                const enabled = Array.isArray(config?.auto_fix_on_fail_stages)
                  ? config.auto_fix_on_fail_stages.includes(stage)
                  : ["build", "tests", "syntax", "static"].includes(stage);
                return (
                  <label key={stage} className="full-row">
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(e) => {
                        if (!updateConfig) return;
                        const base = Array.isArray(
                          config?.auto_fix_on_fail_stages
                        )
                          ? [...config.auto_fix_on_fail_stages]
                          : ["build", "tests", "syntax", "static"];
                        const next = e.target.checked
                          ? Array.from(new Set([...base, stage]))
                          : base.filter((s) => s !== stage);
                        updateConfig("auto_fix_on_fail_stages", next);
                      }}
                    />
                    Auto-fix {stage}
                  </label>
                );
              })}
            </div>
            <div className="row">
              {Object.entries(config?.rag_stage_top_k || {}).map(
                ([key, value]) => (
                  <label key={key} className="full-row">
                    <span className="config-label">TopK {key}</span>
                    <input
                      type="number"
                      min={0}
                      max={50}
                      step={1}
                      value={Number.isFinite(Number(value)) ? Number(value) : 0}
                      onChange={(e) => {
                        if (!updateConfig) return;
                        const next = { ...(config?.rag_stage_top_k || {}) };
                        const num = Number(e.target.value);
                        next[key] = Number.isFinite(num) ? num : 0;
                        updateConfig("rag_stage_top_k", next);
                      }}
                      className="config-input-sm"
                    />
                  </label>
                )
              )}
            </div>
            {ragStatus ? (
              <div className="hint">
                storage {ragStatus.kb_storage || "-"} · ingest{" "}
                {String(ragStatus.rag_ingest_enable)} · on_pipeline{" "}
                {String(ragStatus.rag_ingest_on_pipeline)} · agent_rag{" "}
                {String(ragStatus.agent_rag)} · pgvector{" "}
                {ragStatus.pgvector_ready ? "ready" : "not-ready"}
                {ragStatus.kb_dir ? ` · dir ${ragStatus.kb_dir}` : ""}
              </div>
            ) : (
              <div className="hint">RAG 상태를 확인해주세요.</div>
            )}
            {ragStatus?.stats ? (() => {
              const stats = ragStatus.stats;
              const byCat = stats.by_category || {};
              const bySrc = stats.by_source || {};
              const catEntries = Object.entries(byCat).sort((a, b) => b[1] - a[1]);
              const srcEntries = Object.entries(bySrc).sort((a, b) => b[1] - a[1]);
              const maxCat = Math.max(...catEntries.map(([, v]) => v), 1);
              const maxSrc = Math.max(...srcEntries.map(([, v]) => v), 1);
              const catColorMap = { uds: "rag-cat-uds", code: "rag-cat-code", requirements: "rag-cat-req", vectorcast: "rag-cat-vc" };
              return (
                <div className="kb-stats-panel">
                  <div className="summary-grid">
                    <div className="summary-card"><div className="summary-title">총 엔트리</div><div className="summary-value">{stats.total ?? 0}</div></div>
                    <div className="summary-card"><div className="summary-title">카테고리</div><div className="summary-value">{catEntries.length}</div></div>
                    <div className="summary-card"><div className="summary-title">소스</div><div className="summary-value">{srcEntries.length}</div></div>
                  </div>
                  {catEntries.length > 0 && (
                    <div className="kb-chart-section">
                      <h5>카테고리별 분포</h5>
                      <div className="kb-bar-chart">
                        {catEntries.map(([cat, count]) => (
                          <div key={cat} className="kb-bar-row">
                            <span className={`rag-cat-badge ${catColorMap[cat] || "rag-cat-default"}`}>{cat}</span>
                            <div className="kb-bar-track"><div className="kb-bar-fill" style={{ width: `${(count / maxCat) * 100}%` }} /></div>
                            <span className="kb-bar-value">{count}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {srcEntries.length > 0 && (
                    <div className="kb-chart-section">
                      <h5>소스별 엔트리 수</h5>
                      <div className="kb-bar-chart">
                        {srcEntries.slice(0, 10).map(([src, count]) => (
                          <div key={src} className="kb-bar-row">
                            <span className="kb-bar-label text-ellipsis" title={src}>{src.split(/[/\\]/).pop()}</span>
                            <div className="kb-bar-track"><div className="kb-bar-fill" style={{ width: `${(count / maxSrc) * 100}%` }} /></div>
                            <span className="kb-bar-value">{count}</span>
                          </div>
                        ))}
                        {srcEntries.length > 10 && <div className="hint">외 {srcEntries.length - 10}개 소스</div>}
                      </div>
                    </div>
                  )}
                  {Array.isArray(stats.top_applied) && stats.top_applied.length > 0 && (
                    <div className="kb-chart-section">
                      <h5>가장 많이 활용된 KB 항목</h5>
                      <div className="list">
                        {stats.top_applied.slice(0, 5).map((item, idx) => (
                          <div key={idx} className="list-item">
                            <span className="list-text text-ellipsis">{item.title || item.source || "-"}</span>
                            <span className="list-snippet">활용 {item.apply_count ?? 0}회</span>
                            {item.error_count > 0 && <span className="status-chip tone-failed">에러 {item.error_count}</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              );
            })() : null}
            {ragSourceList.length ? (
              <div className="hint">
                <div className="row">
                  <input
                    type="text"
                    value={ragSourceQuery}
                    onChange={(e) => setRagSourceQuery(e.target.value)}
                    placeholder="소스 필터/검색"
                  />
                  <select
                    value={ragSourceSort}
                    onChange={(e) => setRagSourceSort(e.target.value)}
                  >
                    <option value="count">정렬: 건수</option>
                    <option value="recent">정렬: 최근</option>
                  </select>
                  <button
                    type="button"
                    onClick={() => setRagSourceExpanded((v) => !v)}
                  >
                    전체 {ragSourceExpanded ? "접기" : "펼치기"}
                  </button>
                  <span className="hint">
                    {filteredRagSourceList.length} / {ragSourceList.length}
                  </span>
                </div>
                {(ragSourceExpanded
                  ? filteredRagSourceList
                  : filteredRagSourceList.slice(0, 12)
                ).map((row) => (
                  <div key={row.source}>
                    {row.source}:{row.count}
                    {row.last_ts ? ` (${row.last_ts})` : ""}
                  </div>
                ))}
              </div>
            ) : null}
            {ragIngestResult ? (
              <div className="hint">
                인제스트 결과: updated {ragIngestResult.updated ?? 0} / skipped{" "}
                {ragIngestResult.skipped ?? 0}
              </div>
            ) : null}
          </div>
          <div className="panel">
            <h4>RAG 검색</h4>
            <div className="row">
              <input
                placeholder="질문 또는 키워드"
                value={localRagQuery || ""}
                onChange={(e) =>
                  setLocalRagQuery && setLocalRagQuery(e.target.value)
                }
              />
              <select
                value={localRagCategory || "all"}
                onChange={(e) =>
                  setLocalRagCategory && setLocalRagCategory(e.target.value)
                }
              >
                <option value="all">전체</option>
                <option value="uds">UDS</option>
                <option value="requirements">요구사항</option>
                <option value="code">코드</option>
                <option value="vectorcast">VectorCAST</option>
              </select>
              <button
                onClick={() => runLocalRagQuery && runLocalRagQuery()}
                disabled={localRagLoading}
              >
                {localRagLoading ? "검색 중..." : "검색"}
              </button>
            </div>
            <div className="list rag-result-list">
              {(localRagResults || [])
                .slice()
                .sort((a, b) => (Number(b.score) || 0) - (Number(a.score) || 0))
                .map((item, idx) => {
                  const scorePct = Math.min(100, Math.max(0, (Number(item.score) || 0) * 100));
                  const catColorMap = { uds: "rag-cat-uds", code: "rag-cat-code", requirements: "rag-cat-req", vectorcast: "rag-cat-vc" };
                  const catCls = catColorMap[item.category] || "rag-cat-default";
                  const highlightSnippet = (text) => {
                    if (!text || !localRagQuery) return text;
                    const escaped = localRagQuery.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
                    const parts = text.split(new RegExp(`(${escaped})`, "gi"));
                    return parts.map((p, i) =>
                      p.toLowerCase() === (localRagQuery || "").toLowerCase()
                        ? <mark key={i} className="rag-highlight">{p}</mark>
                        : p
                    );
                  };
                  return (
                    <details key={`${item.title || "item"}-${idx}`} className="rag-result-card">
                      <summary className="list-item">
                        <span className={`rag-cat-badge ${catCls}`}>{item.category || "etc"}</span>
                        <span className="list-text text-ellipsis">{item.title || item.source_file || "-"}</span>
                        <span className="rag-score-bar" title={`${scorePct.toFixed(0)}%`}>
                          <span className="rag-score-fill" style={{ width: `${scorePct}%` }} />
                        </span>
                        <span className="rag-score-label">{scorePct.toFixed(0)}%</span>
                      </summary>
                      <div className="rag-result-detail">
                        {item.snippet && <div className="rag-snippet">{highlightSnippet(item.snippet)}</div>}
                        {item.tags && <div className="kb-tags">{(Array.isArray(item.tags) ? item.tags : String(item.tags).split(",")).map((t) => <span key={t} className="kb-tag">{t.trim()}</span>)}</div>}
                        {item.source_file && <div className="hint">소스: {item.source_file}</div>}
                        {item.apply_count != null && <div className="hint">활용 횟수: {item.apply_count}</div>}
                      </div>
                    </details>
                  );
                })}
              {(localRagResults || []).length === 0 && (
                <div className="empty-state">
                  <div className="empty-state-icon">🔍</div>
                  <div className="empty-state-msg">검색 결과 없음</div>
                  <div className="empty-state-hint">질문이나 키워드를 입력한 후 검색 버튼을 클릭하세요</div>
                </div>
              )}
            </div>
          </div>
          <div className="row">
            <button onClick={loadKb} disabled={!hasReportDir}>
              목록 불러오기
            </button>
            <input
              placeholder="entry_key"
              value={kbDeleteKey}
              onChange={(e) => setKbDeleteKey(e.target.value)}
            />
            <button onClick={deleteKb} disabled={!kbDeleteKey}>
              삭제
            </button>
          </div>
          <div className="list">
            {(kbEntries || []).map((entry) => (
              <div
                key={entry?.key || entry?.entry_key || JSON.stringify(entry)}
                className="list-item"
              >
                <span className="list-text">
                  {entry?.key || entry?.entry_key || "-"}
                </span>
                <span className="list-snippet">
                  {entry?.summary || entry?.title || ""}
                </span>
              </div>
            ))}
            {(kbEntries || []).length === 0 && (
              <div className="empty">엔트리 없음</div>
            )}
          </div>
          <details className="detail-raw">
            <summary>원본 JSON 보기</summary>
            <pre className="json">{JSON.stringify(kbEntries, null, 2)}</pre>
          </details>
        </div>
      )}

      {activeTab === "uds" && (
        <div>
          <div className="row">
            <h3>Local UDS Generator</h3>
            {typeof onGoAnalyzer === "function" ? (
              <button type="button" className="btn-outline" onClick={onGoAnalyzer}>
                Analyzer로 이동
              </button>
            ) : null}
          </div>

          {/* Wizard Step Indicator */}
          <div className="uds-wizard-steps" style={{ display: "flex", gap: "4px", marginBottom: "12px", alignItems: "center" }}>
            {[
              { n: 1, label: "소스 선택" },
              { n: 2, label: "문서 업로드" },
              { n: 3, label: "옵션 설정" },
              { n: 4, label: "생성" },
              { n: 5, label: "검토" },
            ].map((s) => (
              <button
                key={s.n}
                type="button"
                onClick={() => setUdsWizardStep(s.n)}
                style={{
                  flex: 1,
                  padding: "8px 4px",
                  border: udsWizardStep === s.n ? "2px solid var(--accent, #4a9eff)" : "1px solid var(--border, #444)",
                  borderRadius: "6px",
                  background: udsWizardStep === s.n ? "var(--accent-bg, #1a3050)" : "transparent",
                  color: udsWizardStep >= s.n ? "var(--fg, #eee)" : "var(--fg-dim, #888)",
                  cursor: "pointer",
                  fontSize: "0.85rem",
                  fontWeight: udsWizardStep === s.n ? 600 : 400,
                  transition: "all 0.2s",
                }}
              >
                {s.n}. {s.label}
              </button>
            ))}
          </div>

          <div className="panel">
            {/* Step 1: Source Selection */}
            {udsWizardStep === 1 && (
              <>
                <label>소스 루트 <span style={{ color: "var(--error, #f44)" }}>*</span></label>
                <div className="row">
                  <input
                    value={localUdsSourceRoot}
                    onChange={(e) => setLocalUdsSourceRoot(e.target.value)}
                    placeholder="예) D:\\Project\\Ados\\PDS_64_RD"
                  />
                  <button
                    type="button"
                    onClick={async () => {
                      if (!pickDirectory) return;
                      const path = await pickDirectory("소스 루트 선택");
                      if (path) setLocalUdsSourceRoot(path);
                    }}
                  >
                    폴더 선택
                  </button>
                </div>
                <div className="hint">
                  분석할 C/C++ 소스 코드가 있는 폴더를 선택하세요.
                </div>
                <div className="row" style={{ justifyContent: "flex-end", marginTop: "12px" }}>
                  <button
                    type="button"
                    disabled={!String(localUdsSourceRoot || "").trim()}
                    onClick={() => setUdsWizardStep(2)}
                  >
                    다음: 문서 업로드 &rarr;
                  </button>
                </div>
              </>
            )}

            {/* Step 2: Document Upload */}
            {udsWizardStep === 2 && (
              <>
                <label>SRS 문서 <span style={{ color: "var(--accent, #4a9eff)" }}>(권장)</span></label>
                <input
                  type="file"
                  accept=".docx,.pdf,.xlsx,.xls,.txt,.md"
                  onChange={(e) => setLocalUdsSrsDoc(e.target.files?.[0] || null)}
                />
                {localUdsSrsDoc && <div className="hint" style={{ color: "var(--success, #4caf50)" }}>선택됨: {localUdsSrsDoc.name}</div>}

                <label>SDS 문서 <span style={{ color: "var(--accent, #4a9eff)" }}>(권장)</span></label>
                <input
                  type="file"
                  accept=".docx,.pdf,.xlsx,.xls,.txt,.md"
                  onChange={(e) => setLocalUdsSdsDoc(e.target.files?.[0] || null)}
                />
                {localUdsSdsDoc && <div className="hint" style={{ color: "var(--success, #4caf50)" }}>선택됨: {localUdsSdsDoc.name}</div>}

                <label>참조 UDS 문서 (선택)</label>
                <input
                  type="file"
                  accept=".docx,.pdf,.txt,.md"
                  onChange={(e) => setLocalUdsRefDoc(e.target.files?.[0] || null)}
                />

                <div className="hint">
                  SRS 또는 SDS 1개 이상 필수. ASIL/요구사항 매핑 정확도 향상을 위해 두 문서 모두 권장합니다.
                </div>
                <label>추가 요구사항 문서</label>
                <input
                  type="file"
                  multiple
                  accept=".pdf,.docx,.xlsx,.txt,.md,.csv"
                  onChange={(e) =>
                    setLocalUdsReqFiles(Array.from(e.target.files || []))
                  }
                />
                {localUdsReqFiles.length > 0 && (
                  <div className="hint">
                    선택됨: {localUdsReqFiles.map((f) => f.name).join(", ")}
                  </div>
                )}
                <div className="row" style={{ justifyContent: "space-between", marginTop: "12px" }}>
                  <button type="button" onClick={() => setUdsWizardStep(1)}>
                    &larr; 이전
                  </button>
                  <button
                    type="button"
                    disabled={!localUdsSdsDoc && !localUdsSrsDoc}
                    onClick={() => setUdsWizardStep(3)}
                  >
                    다음: 옵션 설정 &rarr;
                  </button>
                </div>
              </>
            )}

            {/* Step 3: Options */}
            {udsWizardStep === 3 && (
              <>
                <label>UDS 템플릿 (선택)</label>
                <input
                  type="file"
                  accept=".docx"
                  onChange={(e) => setLocalUdsTemplate(e.target.files?.[0] || null)}
                />
                <label>컴포넌트 리스트 (선택, 없으면 폴더 기준)</label>
                <input
                  type="file"
                  accept=".json,.xlsx,.xls,.csv,.tsv,.txt"
                  onChange={(e) =>
                    setLocalUdsComponentList(e.target.files?.[0] || null)
                  }
                />
                <div className="row" style={{ flexWrap: "wrap", gap: "12px", marginTop: "8px" }}>
                  <label className="row-inline">
                    <input
                      type="checkbox"
                      checked={!!localUdsAiEnabled}
                      onChange={(e) => setLocalUdsAiEnabled(e.target.checked)}
                    />
                    UDS AI 강화
                  </label>
                  <label className="row-inline">
                    <input
                      type="checkbox"
                      checked={!!localUdsAiDetailed}
                      onChange={(e) => setLocalUdsAiDetailed(e.target.checked)}
                    />
                    상세 구조 생성
                  </label>
                  <label className="row-inline">
                    <input
                      type="checkbox"
                      checked={!!localUdsExpand}
                      onChange={(e) => setLocalUdsExpand(e.target.checked)}
                    />
                    분량 확장 모드
                  </label>
                </div>
                <div className="row" style={{ gap: "12px", marginTop: "8px" }}>
                  <label>RAG TopK</label>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    style={{ width: "70px" }}
                    value={localUdsRagTopK}
                    onChange={(e) =>
                      setLocalUdsRagTopK(Number(e.target.value || 3))
                    }
                  />
                  <label>RAG 카테고리</label>
                  <input
                    value={localUdsRagCategories}
                    onChange={(e) => setLocalUdsRagCategories(e.target.value)}
                    placeholder="requirements,uds,code"
                  />
                  <label>RAG 태그</label>
                  <input
                    value={localUdsTags}
                    onChange={(e) => setLocalUdsTags(e.target.value)}
                    placeholder="srs,sds"
                    style={{ width: "120px" }}
                  />
                </div>
                <div className="row" style={{ justifyContent: "space-between", marginTop: "12px" }}>
                  <button type="button" onClick={() => setUdsWizardStep(2)}>
                    &larr; 이전
                  </button>
                  <button type="button" onClick={() => setUdsWizardStep(4)}>
                    다음: 생성 &rarr;
                  </button>
                </div>
              </>
            )}

            {/* Step 4: Generate */}
            {udsWizardStep === 4 && (
              <>
                <div style={{ marginBottom: "12px", padding: "12px", border: "1px solid var(--border, #444)", borderRadius: "8px" }}>
                  <h4 style={{ margin: "0 0 8px 0" }}>생성 설정 요약</h4>
                  <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: "4px 12px", fontSize: "0.9rem" }}>
                    <span style={{ color: "var(--fg-dim, #888)" }}>소스 루트:</span>
                    <span>{localUdsSourceRoot || "-"}</span>
                    <span style={{ color: "var(--fg-dim, #888)" }}>SRS:</span>
                    <span style={{ color: localUdsSrsDoc ? "var(--success, #4caf50)" : "var(--fg-dim, #888)" }}>{localUdsSrsDoc?.name || "미선택"}</span>
                    <span style={{ color: "var(--fg-dim, #888)" }}>SDS:</span>
                    <span style={{ color: localUdsSdsDoc ? "var(--success, #4caf50)" : "var(--fg-dim, #888)" }}>{localUdsSdsDoc?.name || "미선택"}</span>
                    <span style={{ color: "var(--fg-dim, #888)" }}>AI 강화:</span>
                    <span>{localUdsAiEnabled ? "활성" : "비활성"}</span>
                    <span style={{ color: "var(--fg-dim, #888)" }}>상세 생성:</span>
                    <span>{localUdsAiDetailed ? "활성" : "비활성"}</span>
                  </div>
                </div>

                {/* Progress Display */}
                {localUdsLoading && (
                  <div style={{ marginBottom: "12px" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85rem", marginBottom: "4px" }}>
                      <span>{udsProgressLabel || "UDS 생성 중..."}</span>
                      <span>{udsProgress}%</span>
                    </div>
                    <div style={{ width: "100%", height: "8px", background: "var(--bg-alt, #333)", borderRadius: "4px", overflow: "hidden" }}>
                      <div
                        style={{
                          width: `${udsProgress}%`,
                          height: "100%",
                          background: "var(--accent, #4a9eff)",
                          borderRadius: "4px",
                          transition: "width 0.3s ease",
                        }}
                      />
                    </div>
                  </div>
                )}

                <div className="row">
                  <button
                    type="button"
                    disabled={localRagIngestLoading}
                    onClick={async () => {
                      const ragFiles = [
                        ...selectedCoreReqFiles,
                        ...localUdsReqFiles,
                      ];
                  if (!runRagIngestFiles || ragFiles.length === 0) {
                    setLocalRagIngestNotice(
                      "RAG 인제스트할 문서를 선택해주세요."
                    );
                    return;
                  }
                  setLocalRagIngestLoading(true);
                  setLocalRagIngestNotice("RAG 인제스트 중...");
                  const res = await runRagIngestFiles(
                    ragFiles,
                    "requirements",
                    localUdsTags,
                    {}
                  );
                  if (res?.ok) {
                    setLocalRagIngestNotice(
                      `RAG 인제스트 완료 (추가 ${res.added || 0}건)`
                    );
                  } else {
                    setLocalRagIngestNotice("RAG 인제스트 실패");
                  }
                  setLocalRagIngestLoading(false);
                }}
              >
                {localRagIngestLoading ? "인제스트 중..." : "RAG 인제스트"}
              </button>
              <button
                type="button"
                disabled={localUdsLoading || !generateLocalUds}
                onClick={async () => {
                  if (!generateLocalUds) return;
                  if (!String(localUdsSourceRoot || "").trim()) {
                    setLocalUdsNotice("코드(소스 루트)를 선택해주세요.");
                    return;
                  }
                  if (!localUdsSdsDoc && !localUdsSrsDoc) {
                    setLocalUdsNotice(
                      "최소 요건: SRS 또는 SDS 문서 1개 이상이 필요합니다."
                    );
                    return;
                  }
                  setLocalUdsLoading(true);
                  setLocalUdsNotice("UDS 생성 중...");
                  setUdsProgress(0);
                  setUdsProgressLabel("소스 코드 파싱 중...");
                  const progressTimer = setInterval(() => {
                    setUdsProgress((prev) => {
                      if (prev < 20) { setUdsProgressLabel("소스 코드 파싱 중..."); return prev + 2; }
                      if (prev < 40) { setUdsProgressLabel("SRS/SDS 문서 분석 중..."); return prev + 1; }
                      if (prev < 60) { setUdsProgressLabel("함수 정보 추출 및 ASIL 매핑 중..."); return prev + 1; }
                      if (prev < 80) { setUdsProgressLabel("AI 섹션 생성 중..."); return prev + 0.5; }
                      if (prev < 95) { setUdsProgressLabel("DOCX 문서 생성 중..."); return prev + 0.3; }
                      return prev;
                    });
                  }, 800);
                  try {
                    const taggedReqFiles = [
                      ...selectedCoreReqFiles,
                      ...localUdsReqFiles.map((f) => ({ file: f, type: "req" })),
                    ];
                    const reqFilesForGenerate = taggedReqFiles.map((t) => t.file);
                    const reqTypesForGenerate = taggedReqFiles.map((t) => t.type);
                    const res = await generateLocalUds({
                      sourceRoot: localUdsSourceRoot,
                      reqFiles: reqFilesForGenerate,
                      reqTypes: reqTypesForGenerate,
                      templateFile: localUdsTemplate || localUdsRefDoc,
                      componentList: localUdsComponentList,
                      aiEnabled: localUdsAiEnabled,
                      aiDetailed: localUdsAiDetailed,
                      expand: localUdsExpand,
                      ragTopK: localUdsRagTopK,
                      ragCategories: localUdsRagCategories,
                    });
                    clearInterval(progressTimer);
                    setLocalUdsResult(res || null);
                    setLocalUdsView(null);
                    setLocalUdsViewError("");
                    if (res?.ok) {
                      setUdsProgress(100);
                      setUdsProgressLabel("생성 완료!");
                      setLocalUdsNotice("UDS 생성 완료");
                      setUdsWizardStep(5);
                      if (res?.filename) {
                        setLocalUdsViewFilename(res.filename);
                        await loadLocalUdsView(res.filename);
                      }
                    } else {
                      setUdsProgress(0);
                      setUdsProgressLabel("");
                      setLocalUdsNotice("UDS 생성 실패 — 서버 로그를 확인하세요.");
                    }
                  } catch (genErr) {
                    clearInterval(progressTimer);
                    setUdsProgress(0);
                    setUdsProgressLabel("");
                    setLocalUdsNotice(`UDS 생성 오류: ${genErr?.message || String(genErr)}`);
                  } finally {
                    clearInterval(progressTimer);
                    setLocalUdsLoading(false);
                  }
                }}
              >
                {localUdsLoading ? "생성 중..." : "UDS 생성"}
                  </button>
                </div>
                {localRagIngestNotice ? (
                  <div className="hint">{localRagIngestNotice}</div>
                ) : null}
                {localUdsNotice ? (
                  <div className="hint">{localUdsNotice}</div>
                ) : null}
                <div className="row" style={{ justifyContent: "flex-start", marginTop: "12px" }}>
                  <button type="button" onClick={() => setUdsWizardStep(3)}>
                    &larr; 이전
                  </button>
                </div>
              </>
            )}

            {/* Step 5: Review */}
            {udsWizardStep === 5 && (
              <>
                {localUdsResult ? (
                  <div style={{ marginBottom: "12px" }}>
                    <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "8px" }}>
                      <span style={{ fontSize: "1.2rem", color: localUdsResult.ok ? "var(--success, #4caf50)" : "var(--error, #f44)" }}>
                        {localUdsResult.ok ? "\u2714 생성 성공" : "\u2716 생성 실패"}
                      </span>
                    </div>
                    <div className="row" style={{ gap: "8px" }}>
                      {localUdsResult.download_url && (
                        <a href={localUdsResult.download_url} target="_blank" rel="noreferrer" className="btn-outline">
                          DOCX 다운로드
                        </a>
                      )}
                      {localUdsResult.preview_url && (
                        <a href={localUdsResult.preview_url} target="_blank" rel="noreferrer" className="btn-outline">
                          미리보기
                        </a>
                      )}
                      <button type="button" onClick={() => setUdsWizardStep(1)} className="btn-outline">
                        새로 생성
                      </button>
                    </div>
                    {localUdsResult.path && (
                      <div className="hint" style={{ marginTop: "4px" }}>저장 위치: {localUdsResult.path}</div>
                    )}
                  </div>
                ) : (
                  <div className="hint">아직 생성 결과가 없습니다. Step 4에서 생성해주세요.</div>
                )}
              </>
            )}

            {/* UDS Viewer Workspace - always visible */}
            <UdsViewerWorkspace
              title="Local UDS 상세 뷰"
              files={localUdsFiles}
              selectedFilename={localUdsPickFilename}
              onSelectedFilenameChange={(name) => setLocalUdsPickFilename(name)}
              onRefreshFiles={loadLocalUdsFiles}
              filesLoading={localUdsFilesLoading}
              filesError={localUdsFilesError}
              onLoadView={async (name, params = {}) => {
                const picked = String(name || "").trim();
                if (!picked) return;
                setLocalUdsViewFilename(picked);
                await loadLocalUdsView(picked, params);
              }}
              viewData={localUdsView}
              viewLoading={localUdsViewLoading}
              viewError={localUdsViewError}
              urlStateKey="local_uds"
              sourceRoot={localUdsSourceRoot}
            />
            {localUdsResult ? (
              <details className="detail-raw" style={{ marginTop: "8px" }}>
                <summary>원본 JSON 보기</summary>
                <pre className="json">
                  {JSON.stringify(localUdsResult, null, 2)}
                </pre>
              </details>
            ) : null}
          </div>
        </div>
      )}

      {activeTab === "sts" && (
        <StsGeneratorPanel
          sourceRoot={localUdsSourceRoot}
          onSourceRootChange={() => {}}
          pickDirectory={pickDirectory}
          pickFile={pickFile}
          isJenkins={false}
          srsPath={stsSrsPath}
          onSrsPathChange={setStsSrsPath}
          sdsPath={stsSdsPath}
          onSdsPathChange={setStsSdsPath}
          hsisPath={stsHsisPath}
          onHsisPathChange={setStsHsisPath}
          udsPath={stsUdsPath}
          onUdsPathChange={setStsUdsPath}
          stpPath={stsStpPath}
          onStpPathChange={setStsStpPath}
          templatePath={stsTemplatePath}
          onTemplatePathChange={setStsTemplatePath}
          projectId={stsProjectId}
          onProjectIdChange={setStsProjectId}
          version={stsVersion}
          onVersionChange={setStsVersion}
          asilLevel={stsAsilLevel}
          onAsilLevelChange={setStsAsilLevel}
          maxTc={stsMaxTc}
          onMaxTcChange={setStsMaxTc}
          loading={stsLoading}
          notice={stsNotice}
          progressPct={stsProgressPct}
          progressMsg={stsProgressMsg}
          files={stsFiles}
          filesLoading={stsFilesLoading}
          viewData={stsViewData}
          previewData={stsPreviewData}
          previewLoading={stsPreviewLoading}
          previewSheet={stsPreviewSheet}
          onPreviewSheetChange={setStsPreviewSheet}
          onGenerate={onGenerateSts}
          onRefreshFiles={loadStsFiles}
          onOpenFile={(name) => setStsViewData({ filename: name })}
          onLoadPreview={loadStsPreview}
        />
      )}

      {activeTab === "suts" && (
        <SutsGeneratorPanel
          sourceRoot={localUdsSourceRoot}
          onSourceRootChange={() => {}}
          pickDirectory={pickDirectory}
          pickFile={pickFile}
          isJenkins={false}
          jenkinsJobUrl=""
          jenkinsCacheRoot=""
          jenkinsBuildSelector="lastSuccessfulBuild"
          srsPath={sutsSrsPath}
          onSrsPathChange={setSutsSrsPath}
          sdsPath={sutsSdsPath}
          onSdsPathChange={setSutsSdsPath}
          hsisPath={sutsHsisPath}
          onHsisPathChange={setSutsHsisPath}
          udsPath={sutsUdsPath}
          onUdsPathChange={setSutsUdsPath}
          templatePath={sutsTemplatePath}
          onTemplatePathChange={setSutsTemplatePath}
          projectId={sutsProjectId}
          onProjectIdChange={setSutsProjectId}
          version={sutsVersion}
          onVersionChange={setSutsVersion}
          asilLevel={sutsAsilLevel}
          onAsilLevelChange={setSutsAsilLevel}
          maxSeq={sutsMaxSeq}
          onMaxSeqChange={setSutsMaxSeq}
          loading={sutsLoading}
          notice={sutsNotice}
          progressPct={sutsProgressPct}
          progressMsg={sutsProgressMsg}
          files={sutsFiles}
          filesLoading={sutsFilesLoading}
          viewData={sutsViewData}
          previewData={sutsPreviewData}
          previewLoading={sutsPreviewLoading}
          previewSheet={sutsPreviewSheet}
          onPreviewSheetChange={setSutsPreviewSheet}
          onGenerate={onGenerateSuts}
          onRefreshFiles={loadSutsFiles}
          onOpenFile={(name) => setSutsViewData({ filename: name })}
          onLoadPreview={loadSutsPreview}
        />
      )}

      {activeTab === "complexity" && (
        <LocalComplexityPanel
          loadComplexity={loadComplexity}
          topComplexity={topComplexity}
          onOpenEditorFile={onOpenEditorFile}
          complexityRows={complexityRows}
        />
      )}

      {activeTab === "docs" && (
        <LocalDocsPanel
          docsHtml={docsHtml}
          hasReportDir={hasReportDir}
          generateLocalReports={generateLocalReports}
          loadLocalReports={loadLocalReports}
          localReportsLoading={localReportsLoading}
          localReportsError={localReportsError}
          localReports={localReports}
          downloadLocalReport={downloadLocalReport}
        />
      )}

      {/* logs 중복 렌더링 제거 - 위 통합 블록으로 이동됨 */}
    </div>
  );
};

export default LocalWorkflow;
