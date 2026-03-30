import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import VCastReportGenerator from "./VCastReportGenerator";
import QACReportGenerator from "./QACReportGenerator";
import ExcelCompare from "./ExcelCompare";
import UdsViewerWorkspace from "../components/UdsViewerWorkspace";
import {
  JenkinsScmPanel,
  JenkinsComplexityPanel,
  JenkinsLogsPanel,
  JenkinsVCastPanel,
  JenkinsRagIngestPanel,
} from "../components/jenkins";

const JenkinsWorkflow = ({
  activeJenkinsTab,
  setActiveJenkinsTab,
  jenkinsBaseUrl,
  setJenkinsBaseUrl,
  jenkinsJobUrl,
  setJenkinsJobUrl,
  jenkinsUsername,
  setJenkinsUsername,
  jenkinsToken,
  setJenkinsToken,
  jenkinsVerifyTls,
  setJenkinsVerifyTls,
  jenkinsCacheRoot,
  setJenkinsCacheRoot,
  jenkinsJobs,
  jenkinsJobsLoading,
  jenkinsBuilds,
  jenkinsBuildsLoading,
  jenkinsSyncLoading,
  jenkinsPublishLoading,
  jenkinsProgress,
  jenkinsOpsQueue,
  jenkinsSyncFastMode,
  setJenkinsSyncFastMode,
  jenkinsBuildSelector,
  setJenkinsBuildSelector,
  jenkinsData,
  jenkinsLogs,
  jenkinsLogPath,
  setJenkinsLogPath,
  jenkinsLogContent,
  jenkinsComplexityRows,
  jenkinsDocsHtml,
  jenkinsSourceDownload,
  loadJenkinsJobs,
  loadJenkinsBuilds,
  syncJenkins,
  loadJenkinsLogs,
  readJenkinsLog,
  loadJenkinsComplexity,
  loadJenkinsDocs,
  message,
  setMessage,
  reportAnchor,
  onReportAnchorHandled,
  reportFiles,
  loadReportFiles,
  downloadReportFile,
  downloadReportZip,
  jenkinsServerRoot,
  setJenkinsServerRoot,
  jenkinsServerRelPath,
  setJenkinsServerRelPath,
  jenkinsServerFiles,
  jenkinsServerFilesLoading,
  jenkinsServerFilesError,
  loadJenkinsServerFiles,
  reportSummary,
  loadReportSummary,
  vcastRag,
  loadVcastRag,
  vcastLoading,
  callTree,
  loadCallTree,
  callTreeReport,
  saveCallTree,
  downloadCallTreeReport,
  callTreeExternalMap,
  callTreeHtmlTemplate,
  callTreePreviewHtml,
  previewCallTreeHtml,
  publishReports,
  autoPublishReports,
  setAutoPublishReports,
  jenkinsSourceRoot,
  jenkinsSourceRootRemote,
  setJenkinsSourceRoot,
  jenkinsArtifactUrl,
  setJenkinsArtifactUrl,
  jenkinsScmType,
  setJenkinsScmType,
  jenkinsScmUrl,
  setJenkinsScmUrl,
  jenkinsScmUsername,
  setJenkinsScmUsername,
  jenkinsScmPassword,
  setJenkinsScmPassword,
  jenkinsScmBranch,
  setJenkinsScmBranch,
  jenkinsScmRevision,
  setJenkinsScmRevision,
  loadJenkinsScmInfo,
  jenkinsSourceCandidates,
  loadJenkinsSourceRoot,
  downloadJenkinsSourceRoot,
  autoSelectJenkinsSource,
  setAutoSelectJenkinsSource,
  onSelectSourceRoot,
  udsTemplatePath,
  udsUploading,
  udsGenerating,
  udsResultUrl,
  udsVersions,
  udsPreviewHtml,
  udsPlaceholders,
  udsSourceOnly,
  setUdsSourceOnly,
  udsReqPreview,
  udsReqMapping,
  udsReqCompare,
  udsReqFunctionMapping,
  udsReqTraceability,
  udsReqTraceMatrix,
  udsDiff,
  uploadUdsTemplate,
  generateUdsDocx,
  cancelUdsDocx,
  loadUdsVersions,
  loadUdsPreview,
  previewUdsRequirements,
  loadUdsDiff,
  updateUdsLabel,
  updateUdsLabelDraft,
  deleteUdsVersion,
  pickFile,
  jenkinsRagQuery,
  setJenkinsRagQuery,
  jenkinsRagCategory,
  setJenkinsRagCategory,
  jenkinsRagResults,
  jenkinsRagLoading,
  runJenkinsRagQuery,
  runRagIngestFiles,
  enqueueJenkinsOp,
  updateJenkinsOp,
  openEditorAt,
  onGoAnalyzerArtifact,
  onGoAnalyzer,
}) => {
  const [reportExtFilter, setReportExtFilter] = useState("all");
  const [reportQuery, setReportQuery] = useState("");
  const [reportScope, setReportScope] = useState("all");
  const [reportView, setReportView] = useState("list");
  const [reportTreeOpen, setReportTreeOpen] = useState({});
  const [serverTreeOpen, setServerTreeOpen] = useState({});
  const [buildSummaryCount, setBuildSummaryCount] = useState(20);
  const [callEntry, setCallEntry] = useState("");
  const [callDepth, setCallDepth] = useState(5);
  const [callInclude, setCallInclude] = useState("");
  const [callExclude, setCallExclude] = useState("");
  const [callMaxFiles, setCallMaxFiles] = useState(2000);
  const [callIncludeExternal, setCallIncludeExternal] = useState(false);
  const [compileCommandsPath, setCompileCommandsPath] = useState("");
  const [callReportFormat, setCallReportFormat] = useState("json");
  const [callSearch, setCallSearch] = useState("");
  const [callCollapsed, setCallCollapsed] = useState({});
  const [externalFilter, setExternalFilter] = useState("");
  const [showTemplatePreview, setShowTemplatePreview] = useState(false);
  const [udsExtraFiles, setUdsExtraFiles] = useState([]);
  const [udsReqFiles, setUdsReqFiles] = useState([]);
  const [udsRefDoc, setUdsRefDoc] = useState(null);
  const [udsSdsDoc, setUdsSdsDoc] = useState(null);
  const [udsSrsDoc, setUdsSrsDoc] = useState(null);
  const [udsReqPreviewText, setUdsReqPreviewText] = useState({});
  const [udsReqPreviewName, setUdsReqPreviewName] = useState("");
  const [udsReqPreviewContent, setUdsReqPreviewContent] = useState("");
  const [udsReqServerPaths, setUdsReqServerPaths] = useState([]);
  const [udsReqServerPreviewName, setUdsReqServerPreviewName] = useState("");
  const [udsReqServerPreviewContent, setUdsReqServerPreviewContent] =
    useState("");
  const [udsComponentList, setUdsComponentList] = useState(null);
  const [udsTraceMapFiles, setUdsTraceMapFiles] = useState([]);
  const [udsTraceMapServerPaths, setUdsTraceMapServerPaths] = useState([]);
  const [udsLogicSource, setUdsLogicSource] = useState("call_tree");
  const [udsLogicFiles, setUdsLogicFiles] = useState([]);
  const [udsLogicMaxChildren, setUdsLogicMaxChildren] = useState(3);
  const [udsLogicMaxGrandchildren, setUdsLogicMaxGrandchildren] = useState(2);
  const [udsLogicMaxDepth, setUdsLogicMaxDepth] = useState(3);
  const [udsGlobalsFormatOrder, setUdsGlobalsFormatOrder] = useState(
    "Name,Type,File,Range"
  );
  const [udsGlobalsFormatSep, setUdsGlobalsFormatSep] = useState(" | ");
  const [udsGlobalsFormatWithLabels, setUdsGlobalsFormatWithLabels] =
    useState(true);
  const [udsAiEnabled, setUdsAiEnabled] = useState(false);
  const [udsAiExampleFile, setUdsAiExampleFile] = useState(null);
  const [udsAiExamplePath, setUdsAiExamplePath] = useState("");
  const [udsAiDetailed, setUdsAiDetailed] = useState(true);
  const [udsDiffA, setUdsDiffA] = useState("");
  const [udsDiffB, setUdsDiffB] = useState("");
  const [jenkinsUdsView, setJenkinsUdsView] = useState(null);
  const [jenkinsUdsViewLoading, setJenkinsUdsViewLoading] = useState(false);
  const [jenkinsUdsViewError, setJenkinsUdsViewError] = useState("");
  const [jenkinsUdsPickFilename, setJenkinsUdsPickFilename] = useState("");
  const effectiveUdsReqFiles = useMemo(() => {
    const tagged = [
      { file: udsSrsDoc, type: "srs" },
      { file: udsSdsDoc, type: "sds" },
      ...udsReqFiles.map((f) => ({ file: f, type: "req" })),
    ].filter((t) => t.file);
    const out = [];
    const seen = new Set();
    tagged.forEach(({ file, type }) => {
      const key = `${file.name || ""}:${file.size || 0}`;
      if (seen.has(key)) return;
      seen.add(key);
      out.push({ file, type });
    });
    return out;
  }, [udsSrsDoc, udsSdsDoc, udsReqFiles]);
  const effectiveUdsExtraFiles = useMemo(() => {
    const rows = [udsRefDoc, ...udsExtraFiles].filter(Boolean);
    const out = [];
    const seen = new Set();
    rows.forEach((file) => {
      const key = `${file.name || ""}:${file.size || 0}`;
      if (seen.has(key)) return;
      seen.add(key);
      out.push(file);
    });
    return out;
  }, [udsRefDoc, udsExtraFiles]);

  const syncProgress = jenkinsProgress?.sync || null;
  const publishProgress = jenkinsProgress?.publish || null;
  const udsProgress = jenkinsProgress?.uds || null;

  const runTrackedOp = useCallback(
    async (type, message, action) => {
      if (!enqueueJenkinsOp || !updateJenkinsOp) {
        return action();
      }
      const id = enqueueJenkinsOp(type, message);
      try {
        const result = await Promise.resolve(action());
        updateJenkinsOp(id, { status: "success", message: `${message} 완료` });
        return result;
      } catch (e) {
        updateJenkinsOp(id, {
          status: "failed",
          message: e?.message || String(e),
        });
        throw e;
      }
    },
    [enqueueJenkinsOp, updateJenkinsOp]
  );
  const jobsAutoLoadedRef = useRef(false);

  const loadJenkinsUdsView = useCallback(
    async (filename, params = {}) => {
      const name = String(filename || "").trim();
      if (!name) return;
      const jobUrl = String(jenkinsJobUrl || "").trim();
      const cacheRoot = String(jenkinsCacheRoot || "").trim();
      if (!jobUrl || !cacheRoot) {
        setJenkinsUdsViewError("job_url/cache_root가 필요합니다.");
        return;
      }
      setJenkinsUdsViewLoading(true);
      setJenkinsUdsViewError("");
      try {
        const qs = new URLSearchParams({
          job_url: jobUrl,
          cache_root: cacheRoot,
          filename: name,
        });
        Object.entries(params || {}).forEach(([k, v]) => {
          if (v === null || v === undefined || v === "") return;
          qs.set(k, String(v));
        });
        const res = await fetch(`/api/jenkins/uds/view?${qs.toString()}`);
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const data = await res.json();
        setJenkinsUdsView(data || null);
      } catch (e) {
        setJenkinsUdsViewError(e?.message || String(e));
        setJenkinsUdsView(null);
      } finally {
        setJenkinsUdsViewLoading(false);
      }
    },
    [jenkinsJobUrl, jenkinsCacheRoot]
  );
  const formatElapsed = (progress) => {
    if (!progress?.started_at) return "";
    const start = new Date(progress.started_at).getTime();
    if (!Number.isFinite(start)) return "";
    const now = Date.now();
    const sec = Math.max(0, Math.floor((now - start) / 1000));
    const min = Math.floor(sec / 60);
    const rem = sec % 60;
    return `${min}m ${String(rem).padStart(2, "0")}s`;
  };

  // 대시보드 탭이 활성화되면 리포트 요약 자동 로드
  useEffect(() => {
    if (
      activeJenkinsTab === "dashboard" &&
      jenkinsJobUrl &&
      loadReportSummary
    ) {
      loadReportSummary();
    }
  }, [activeJenkinsTab, jenkinsJobUrl, loadReportSummary]);

  const handleReqFilePreview = (files) => {
    const next = {};
    (files || []).forEach((file) => {
      if (!file || !file.name) return;
      const ext = file.name.toLowerCase();
      if (!ext.endsWith(".txt") && !ext.endsWith(".md")) return;
      const reader = new FileReader();
      reader.onload = () => {
        next[file.name] = String(reader.result || "").slice(0, 20000);
        setUdsReqPreviewText((prev) => ({ ...prev, ...next }));
        if (!udsReqPreviewName) {
          setUdsReqPreviewName(file.name);
          setUdsReqPreviewContent(next[file.name] || "");
        }
      };
      reader.readAsText(file);
    });
  };

  const addReqServerPath = async () => {
    if (!pickFile) {
      setMessage("파일 선택 기능이 없습니다.");
      return;
    }
    const path = await pickFile("요구사항 문서 선택");
    if (!path) return;
    setUdsReqServerPaths((prev) =>
      prev.includes(path) ? prev : [...prev, path]
    );
  };

  const addTraceMapServerPath = async () => {
    if (!pickFile) {
      setMessage("파일 선택 기능이 없습니다.");
      return;
    }
    const path = await pickFile("추적성 매핑 테이블 선택");
    if (!path) return;
    setUdsTraceMapServerPaths((prev) =>
      prev.includes(path) ? prev : [...prev, path]
    );
  };

  const previewReqServerPath = async (path) => {
    if (!path) return;
    try {
      const res = await fetch("/api/local/preview-text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, max_chars: 20000 }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setUdsReqServerPreviewName(data?.path || path);
      setUdsReqServerPreviewContent(String(data?.text || ""));
      if (data?.truncated) {
        setMessage("요구사항 문서 미리보기는 일부만 표시됩니다.");
      }
    } catch (e) {
      setMessage(`요구사항 문서 미리보기 실패: ${e.message || String(e)}`);
    }
  };

  const addAiExamplePath = async () => {
    if (!pickFile) {
      setMessage("파일 선택 기능이 없습니다.");
      return;
    }
    const path = await pickFile("UDS AI 예시 파일 선택");
    if (!path) return;
    setUdsAiExamplePath(path);
  };

  useEffect(() => {
    jobsAutoLoadedRef.current = false;
  }, [jenkinsBaseUrl, jenkinsUsername, jenkinsToken]);

  useEffect(() => {
    if (activeJenkinsTab !== "project") return;
    if (!jenkinsBaseUrl || !jenkinsUsername || !jenkinsToken) return;
    if (jenkinsJobsLoading) return;
    if (Array.isArray(jenkinsJobs) && jenkinsJobs.length > 0) return;
    if (jobsAutoLoadedRef.current) return;
    jobsAutoLoadedRef.current = true;
    if (loadJenkinsJobs) loadJenkinsJobs();
  }, [
    activeJenkinsTab,
    jenkinsBaseUrl,
    jenkinsUsername,
    jenkinsToken,
    jenkinsJobsLoading,
    jenkinsJobs,
    loadJenkinsJobs,
  ]);

  const report = reportSummary || {};
  const reportKpis = report.kpis || {};

  const summary = jenkinsData?.summary || jenkinsData || {};
  const jenkinsMeta =
    summary?.jenkins ||
    jenkinsData?.jenkins ||
    jenkinsData?.status ||
    jenkinsData?.build ||
    reportKpis?.build ||
    {};
  const jenkinsScan = summary?.jenkins_scan || reportKpis?.scan || {};
  const reportDir = summary?.reports_dir || jenkinsData?.reports_dir ||
    reportKpis?.build?.reports_dir || "-";
  const buildRoot = summary?.build_root || jenkinsData?.build_root ||
    reportKpis?.build?.build_root || "-";
  const statusState =
    jenkinsMeta?.result ||
    jenkinsMeta?.status ||
    (jenkinsMeta?.building ? "RUNNING" : null) ||
    jenkinsMeta?.state ||
    jenkinsData?.result ||
    jenkinsData?.status ||
    "-";
  const statusTone = (value) => {
    const raw = String(value || "").toLowerCase();
    if (raw.includes("fail") || raw.includes("error")) return "failed";
    if (raw.includes("run")) return "running";
    if (raw.includes("success") || raw.includes("ok")) return "success";
    return "info";
  };

  const scmPresets = [
    { label: "선택 안 함", url: "", username: "", type: "svn" },
    {
      label: "KISS1119_PRJ",
      url: "svn://192.168.110.33/KISS1119_PRJ",
      username: "kss1119",
      type: "svn",
    },
    {
      label: "ADOS",
      url: "svn://192.168.110.33/ADOS",
      username: "kss1119",
      type: "svn",
    },
  ];

  const reportFileRows = Array.isArray(reportFiles?.files)
    ? reportFiles.files
    : [];
  const reportExtOptions = useMemo(() => {
    const counts = reportFiles?.ext_counts || {};
    return ["all", ...Object.keys(counts).sort()];
  }, [reportFiles]);

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
    } else if (reportScope === "source") {
      rows = rows.filter((item) => {
        const rel = String(item.rel_path || item.path || "")
          .replace(/\\/g, "/")
          .toLowerCase();
        return (
          rel.startsWith("source/") ||
          rel.includes("/source/") ||
          rel.startsWith("src/") ||
          rel.includes("/src/") ||
          rel.startsWith("sources/") ||
          rel.includes("/sources/")
        );
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

  const buildTreeFromFiles = (rows) => {
    const root = { name: ".", path: "", children: {}, files: [] };
    (rows || []).forEach((item) => {
      const rel = String(item.rel_path || item.path || "").replace(/\\/g, "/");
      if (!rel) return;
      const parts = rel.split("/").filter(Boolean);
      let node = root;
      parts.forEach((part, idx) => {
        const isFile = idx === parts.length - 1;
        if (isFile) {
          node.files.push({ name: part, rel, item });
        } else {
          if (!node.children[part]) {
            node.children[part] = {
              name: part,
              path: node.path ? `${node.path}/${part}` : part,
              children: {},
              files: [],
            };
          }
          node = node.children[part];
        }
      });
    });
    return root;
  };

  const reportTree = useMemo(
    () => buildTreeFromFiles(filteredReportFiles),
    [filteredReportFiles]
  );

  const serverTree = useMemo(
    () => buildTreeFromFiles(jenkinsServerFiles),
    [jenkinsServerFiles]
  );

  const isTreeOpen = (path) => reportTreeOpen[path] !== false;
  const toggleTreeNode = (path) =>
    setReportTreeOpen((prev) => ({ ...prev, [path]: !isTreeOpen(path) }));

  const isServerTreeOpen = (path) => serverTreeOpen[path] !== false;
  const toggleServerTreeNode = (path) =>
    setServerTreeOpen((prev) => ({ ...prev, [path]: !isServerTreeOpen(path) }));

  const scmDisplay = useMemo(() => {
    const fromJenkins = jenkinsData?.summary?.scm || jenkinsData?.scm ||
      reportSummary?.kpis?.scm || {};
    if (fromJenkins && Object.keys(fromJenkins).length > 0) {
      return fromJenkins;
    }
    return {
      scm_type: jenkinsScmType || "",
      scm_url: jenkinsScmUrl || "",
      scm_username: jenkinsScmUsername || "",
      scm_branch: jenkinsScmBranch || "",
      scm_revision: jenkinsScmRevision || "",
    };
  }, [
    jenkinsData,
    reportSummary,
    jenkinsScmType,
    jenkinsScmUrl,
    jenkinsScmUsername,
    jenkinsScmBranch,
    jenkinsScmRevision,
  ]);
  useEffect(() => {
    if (!reportAnchor || activeJenkinsTab !== "reports") return;
    const el = document.getElementById(reportAnchor);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    if (onReportAnchorHandled) onReportAnchorHandled();
  }, [activeJenkinsTab, onReportAnchorHandled, reportAnchor]);

  const reportScan = reportKpis.scan || {};
  const reportFilesCount = reportKpis.files || {};
  const reportSource = report.source || {};

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
    { total: 0, success: 0, fail: 0, unstable: 0, other: 0 }
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

  const callTreePayload = callTree || {};
  const callTreeStats = callTreePayload.stats || {};
  const callTreeRoots = Array.isArray(callTreePayload.trees)
    ? callTreePayload.trees
    : [];
  const callTreeMissing = Array.isArray(callTreePayload.missing)
    ? callTreePayload.missing
    : [];

  const matchesQuery = (text, query) => {
    if (!query) return true;
    return String(text || "")
      .toLowerCase()
      .includes(String(query).toLowerCase());
  };

  const shouldShowNode = (node, query) => {
    if (!node) return false;
    if (matchesQuery(node.name, query)) return true;
    const childMatch = (node.calls || []).some((child) =>
      shouldShowNode(child, query)
    );
    if (childMatch) return true;
    const extMatch = (node.externals || []).some((ext) =>
      matchesQuery(ext.name, query)
    );
    return extMatch;
  };

  const renderCallTree = (node, depth = 0) => {
    if (!node) return null;
    if (callSearch && !shouldShowNode(node, callSearch)) return null;
    const collapsed = !!callCollapsed[node.name];
    return (
      <div
        key={`${node.name}-${depth}`}
        className="list-item"
        style={{ paddingLeft: `${depth * 14}px` }}
      >
        <span className="list-text">
          {node.name}
          {node.cycle ? " (cycle)" : ""}
          {node.truncated ? " (truncated)" : ""}
        </span>
        <button
          type="button"
          className="btn-link"
          onClick={() =>
            setCallCollapsed((prev) => ({
              ...prev,
              [node.name]: !prev[node.name],
            }))
          }
        >
          {collapsed ? "펼치기" : "접기"}
        </button>
        {callIncludeExternal &&
          Array.isArray(node.externals) &&
          node.externals.length > 0 && (
            <div className="list">
              {node.externals
                .filter((ext) => {
                  if (!externalFilter) return true;
                  const token = externalFilter.toLowerCase();
                  return (
                    String(ext.header || "")
                      .toLowerCase()
                      .includes(token) ||
                    String(ext.library || "")
                      .toLowerCase()
                      .includes(token) ||
                    String(ext.name || "")
                      .toLowerCase()
                      .includes(token)
                  );
                })
                .map((ext) => (
                  <div
                    key={`${node.name}-${ext.name}`}
                    className="list-item"
                    style={{ paddingLeft: `${(depth + 1) * 14}px` }}
                  >
                    <span className="list-text">
                      {ext.name} (external) · {ext.header} · {ext.library}
                    </span>
                  </div>
                ))}
            </div>
          )}
        {!collapsed && Array.isArray(node.calls) && node.calls.length > 0 && (
          <div className="list">
            {node.calls.map((child) => renderCallTree(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  const jobOptions = Array.isArray(jenkinsJobs) ? jenkinsJobs : [];
  const jobUrlInList = jobOptions.some((j) => (j?.url || "") === jenkinsJobUrl);

  return (
    <div className="view-root">
      <div className="help-box">
        <h4>Jenkins 워크플로우 사용 방법</h4>
        <ul>
          <li>
            프로젝트 탭에서 Jenkins 정보를 입력하고 프로젝트/빌드를 로드합니다.
          </li>
          <li>Job URL과 Cache Root를 지정한 뒤 동기화를 실행합니다.</li>
          <li>대시보드는 선택한 빌드 요약을 보여줍니다.</li>
          <li>다른 탭에서 로그/리포트/복잡도 결과를 확인합니다.</li>
        </ul>
      </div>
      {Array.isArray(jenkinsOpsQueue) && jenkinsOpsQueue.length > 0 ? (
        <div className="panel">
          <h4>작업 큐</h4>
          <div className="list">
            {jenkinsOpsQueue.slice(0, 10).map((item) => (
              <div key={item.id} className="list-item">
                <span className="list-text">
                  {item.type} · {item.status}
                </span>
                <span className="list-snippet">{item.message || "-"}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
      <div className="tabs">
        <button
          className={activeJenkinsTab === "project" ? "active" : ""}
          onClick={() => setActiveJenkinsTab("project")}
        >
          프로젝트
        </button>
        <button
          className={activeJenkinsTab === "dashboard" ? "active" : ""}
          onClick={() => setActiveJenkinsTab("dashboard")}
        >
          대시보드
        </button>
        <button
          className={activeJenkinsTab === "scm" ? "active" : ""}
          onClick={() => setActiveJenkinsTab("scm")}
        >
          SCM
        </button>
        <button
          className={activeJenkinsTab === "complexity" ? "active" : ""}
          onClick={() => setActiveJenkinsTab("complexity")}
        >
          복잡도
        </button>
        <button
          className={activeJenkinsTab === "logs" ? "active" : ""}
          onClick={() => setActiveJenkinsTab("logs")}
        >
          로그
        </button>
        <button
          className={activeJenkinsTab === "reports" ? "active" : ""}
          onClick={() => setActiveJenkinsTab("reports")}
        >
          리포트
        </button>
        <button
          className={activeJenkinsTab === "calltree" ? "active" : ""}
          onClick={() => setActiveJenkinsTab("calltree")}
        >
          콜 트리
        </button>
        <button
          className={activeJenkinsTab === "vcast" ? "active" : ""}
          onClick={() => setActiveJenkinsTab("vcast")}
        >
          VCast 리포트
        </button>
        <button
          className={activeJenkinsTab === "qac" ? "active" : ""}
          onClick={() => setActiveJenkinsTab("qac")}
        >
          QAC 리포트
        </button>
        <button
          className={activeJenkinsTab === "excel-compare" ? "active" : ""}
          onClick={() => setActiveJenkinsTab("excel-compare")}
        >
          Excel 비교
        </button>
        <button
          className={activeJenkinsTab === "rag-ingest" ? "active" : ""}
          onClick={() => setActiveJenkinsTab("rag-ingest")}
        >
          RAG 인제스트
        </button>
        <button
          className={activeJenkinsTab === "uds" ? "active" : ""}
          onClick={() => setActiveJenkinsTab("uds")}
        >
          UDS
        </button>
      </div>

      {activeJenkinsTab === "project" && (
        <div className="panel-group">
          <div className="panel">
            <h3>연결 정보</h3>
            <div className="section">
              <label>Jenkins URL</label>
              <input
                value={jenkinsBaseUrl}
                onChange={(e) => setJenkinsBaseUrl(e.target.value)}
              />
              <label>Username</label>
              <input
                value={jenkinsUsername}
                onChange={(e) => setJenkinsUsername(e.target.value)}
              />
              <label>API Token</label>
              <input
                type="password"
                value={jenkinsToken}
                onChange={(e) => setJenkinsToken(e.target.value)}
              />
              <label>Verify TLS</label>
              <input
                type="checkbox"
                checked={jenkinsVerifyTls}
                onChange={(e) => setJenkinsVerifyTls(e.target.checked)}
              />
              <label>Cache Root</label>
              <input
                value={jenkinsCacheRoot}
                onChange={(e) => setJenkinsCacheRoot(e.target.value)}
                placeholder="비워두면 기본 경로(~/.devops_pro_cache) 사용"
              />
              <div className="row">
                <button
                  onClick={loadJenkinsJobs}
                  disabled={!jenkinsBaseUrl || jenkinsJobsLoading}
                >
                  {jenkinsJobsLoading ? "로딩 중..." : "프로젝트 로드"}
                </button>
                <button
                  onClick={loadJenkinsBuilds}
                  disabled={!jenkinsJobUrl || jenkinsBuildsLoading}
                >
                  {jenkinsBuildsLoading ? "로딩 중..." : "빌드 로드"}
                </button>
              </div>
              {!jenkinsBaseUrl && (
                <div
                  className="hint"
                  style={{ color: "var(--color-danger)", marginTop: "5px" }}
                >
                  Base URL을 입력해주세요.
                </div>
              )}
              {jenkinsBaseUrl && !jenkinsUsername && !jenkinsToken && (
                <div
                  className="hint"
                  style={{ marginTop: "5px", color: "var(--text-muted)" }}
                >
                  인증이 필요한 Jenkins라면 Username/Token을 입력하세요.
                </div>
              )}
              <label>자동 리포트 업로드</label>
              <input
                type="checkbox"
                checked={!!autoPublishReports}
                onChange={(e) =>
                  setAutoPublishReports &&
                  setAutoPublishReports(e.target.checked)
                }
              />
              <label>소스 루트 자동 선택</label>
              <input
                type="checkbox"
                checked={!!autoSelectJenkinsSource}
                onChange={(e) =>
                  setAutoSelectJenkinsSource &&
                  setAutoSelectJenkinsSource(e.target.checked)
                }
              />
            </div>
          </div>
          <div className="panel">
            <h3>프로젝트 / 빌드</h3>
            <div className="section">
              <label>Job URL 직접 입력</label>
              <input
                value={jenkinsJobUrl}
                onChange={(e) => setJenkinsJobUrl(e.target.value)}
                placeholder="http://jenkins.local/job/YourJob/"
              />
              <label>
                Job URL 목록{" "}
                {Array.isArray(jenkinsJobs) && jenkinsJobs.length > 0
                  ? `(${jenkinsJobs.length}개)`
                  : ""}
              </label>
              <select
                value={jobUrlInList ? jenkinsJobUrl : ""}
                onChange={(e) => setJenkinsJobUrl(e.target.value)}
              >
                <option value="">(선택)</option>
                {!jobUrlInList && jenkinsJobUrl ? (
                  <option value={jenkinsJobUrl}>
                    직접 입력: {jenkinsJobUrl}
                  </option>
                ) : null}
                {jobOptions.map((j) => {
                  // 백엔드가 반환하는 형식: {name: "...", url: "...", color: "...", class_name: "..."}
                  const url = j.url || "";
                  const name = j.name || url || "(이름 없음)";
                  if (!url) return null;
                  return (
                    <option key={url} value={url}>
                      {name}
                    </option>
                  );
                })}
              </select>
              <label>
                Build Selector
                {Array.isArray(jenkinsBuilds) && jenkinsBuilds.length > 0
                  ? ` (${jenkinsBuilds.length}개)`
                  : " — 빌드 로드 클릭"}
              </label>
              <select
                value={jenkinsBuildSelector}
                onChange={(e) => setJenkinsBuildSelector(e.target.value)}
              >
                <option value="lastSuccessfulBuild">lastSuccessfulBuild</option>
                {(Array.isArray(jenkinsBuilds) ? jenkinsBuilds : []).map(
                  (b) => (
                    <option key={b.number} value={String(b.number)}>
                      #{b.number} {b.result ? `(${b.result})` : ""}
                    </option>
                  )
                )}
              </select>
              <div className="row">
                <button
                  onClick={syncJenkins}
                  disabled={!jenkinsJobUrl || jenkinsSyncLoading}
                >
                  {jenkinsSyncLoading ? "동기화 중..." : "동기화"}
                </button>
                <button
                  onClick={() => publishReports && publishReports()}
                  disabled={!jenkinsJobUrl || jenkinsPublishLoading}
                >
                  {jenkinsPublishLoading
                    ? "업로드 중..."
                    : "로컬 리포트 올리기"}
                </button>
              </div>
              <label className="row">
                <input
                  type="checkbox"
                  checked={!!jenkinsSyncFastMode}
                  onChange={(e) =>
                    setJenkinsSyncFastMode &&
                    setJenkinsSyncFastMode(e.target.checked)
                  }
                />
                빠른 동기화 (리포트 중심/스캔 제한)
              </label>
              {jenkinsSyncFastMode && (
                <div className="hint">
                  report 폴더 위주로 스캔하고 파일 수를 제한해 속도를 올립니다.
                </div>
              )}
              {(syncProgress || publishProgress) && (
                <div className="section">
                  {syncProgress && (
                    <div className="panel">
                      <div className="row">
                        <strong>동기화 진행</strong>
                        <span>
                          {syncProgress.message || syncProgress.stage}
                        </span>
                      </div>
                      <progress
                        value={Number(syncProgress.percent || 0)}
                        max="100"
                      />
                      <div className="hint">
                        {formatElapsed(syncProgress)}
                        {syncProgress.updated_at
                          ? ` · 업데이트 ${syncProgress.updated_at}`
                          : ""}
                      </div>
                      {syncProgress.file && (
                        <div className="hint">{syncProgress.file}</div>
                      )}
                    </div>
                  )}
                  {publishProgress && (
                    <div className="panel">
                      <div className="row">
                        <strong>로컬 리포트 업로드</strong>
                        <span>
                          {publishProgress.message || publishProgress.stage}
                        </span>
                      </div>
                      <progress
                        value={Number(publishProgress.percent || 0)}
                        max="100"
                      />
                      <div className="hint">
                        {formatElapsed(publishProgress)}
                        {publishProgress.updated_at
                          ? ` · 업데이트 ${publishProgress.updated_at}`
                          : ""}
                      </div>
                      {publishProgress.file && (
                        <div className="hint">{publishProgress.file}</div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
          <div className="panel">
            <h3>소스 루트</h3>
            <div className="section">
              <div className="row">
                <button
                  onClick={loadJenkinsSourceRoot}
                  disabled={!jenkinsJobUrl}
                >
                  소스 루트 탐색
                </button>
              </div>
              <label>아티팩트 URL(리포트/소스 ZIP)</label>
              <div className="row">
                <input
                  value={jenkinsArtifactUrl || ""}
                  onChange={(e) => setJenkinsArtifactUrl(e.target.value)}
                  placeholder="http://.../artifact/xxx.zip"
                />
                <button
                  type="button"
                  className="btn-outline"
                  disabled={
                    !jenkinsArtifactUrl ||
                    !downloadJenkinsSourceRoot ||
                    jenkinsSourceDownload?.loading
                  }
                  onClick={() => downloadJenkinsSourceRoot(jenkinsArtifactUrl)}
                >
                  아티팩트 적용
                </button>
              </div>
              {jenkinsSourceDownload?.loading ? (
                <div className="panel">
                  <div className="row">
                    <strong>소스 다운로드 진행</strong>
                    <span>
                      {jenkinsSourceDownload.message || "다운로드 중..."}
                    </span>
                  </div>
                  <progress />
                </div>
              ) : jenkinsSourceDownload?.ok === true ? (
                <div className="hint">
                  소스 다운로드 완료: {jenkinsSourceDownload.path || "-"}
                </div>
              ) : jenkinsSourceDownload?.ok === false ? (
                <div className="hint">
                  소스 다운로드 실패: {jenkinsSourceDownload.message}
                </div>
              ) : null}
              {jenkinsSourceRoot ? (
                <>
                  {jenkinsSourceRootRemote ? (
                    <div className="hint">
                      선택한 원격 소스 후보: {jenkinsSourceRootRemote}
                    </div>
                  ) : null}
                  <div className="hint">
                    현재 소스 루트(로컬 캐시): {jenkinsSourceRoot}
                  </div>
                </>
              ) : (
                <div className="hint">소스 루트 미설정</div>
              )}
              <div className="list">
                {(jenkinsSourceCandidates || []).map((item) => (
                  <div key={item.path} className="list-item">
                    <span className="list-text">{item.path}</span>
                    <span className="list-snippet">
                      score {item.score} · {item.exists ? "로컬" : "원격"}
                    </span>
                    <button
                      type="button"
                      className="btn-outline"
                      disabled={jenkinsSourceDownload?.loading}
                      onClick={() =>
                        downloadJenkinsSourceRoot &&
                        downloadJenkinsSourceRoot(item.path)
                      }
                    >
                      다운로드
                    </button>
                    <button
                      type="button"
                      className="btn-outline"
                      disabled={!item.exists}
                      onClick={() => {
                        if (!item?.path) return;
                        if (onSelectSourceRoot) {
                          onSelectSourceRoot(item.path);
                          setMessage &&
                            setMessage(
                              `소스 루트가 선택되었습니다: ${item.path}`
                            );
                          return;
                        }
                        if (setJenkinsSourceRoot) {
                          setJenkinsSourceRoot(item.path);
                          setMessage &&
                            setMessage(
                              `소스 루트가 선택되었습니다: ${item.path}`
                            );
                        }
                      }}
                    >
                      선택
                    </button>
                  </div>
                ))}
                {(jenkinsSourceCandidates || []).length === 0 && (
                  <div className="empty">후보 없음</div>
                )}
              </div>
            </div>
          </div>
          {message ? <div className="message">{message}</div> : null}
        </div>
      )}

      {activeJenkinsTab === "dashboard" && (
        <div>
          <h3>빌드 대시보드</h3>
          <div className="row">
            <button
              type="button"
              onClick={loadReportSummary}
              disabled={!jenkinsJobUrl}
            >
              리포트 요약 {reportSummary ? "새로고침" : "로드"}
            </button>
            {!reportSummary && jenkinsJobUrl && (
              <span
                className="hint"
                style={{ marginLeft: "10px", color: "var(--text-muted)" }}
              >
                리포트 요약을 로드하면 더 자세한 정보를 볼 수 있습니다.
              </span>
            )}
            {!jenkinsData && !reportSummary && (
              <span
                className="hint"
                style={{ marginLeft: "10px", color: "var(--color-danger)" }}
              >
                Jenkins 데이터가 없습니다. 워크플로우에서 "동기화" 버튼을
                클릭하세요.
              </span>
            )}
          </div>
          <div className="cards">
            <div className={`card status-${statusTone(statusState)}`}>
              <div className="card-title">상태</div>
              <div className="card-value">{statusState}</div>
              <div className="card-sub">
                {jenkinsMeta?.build_url ||
                  jenkinsMeta?.url ||
                  jenkinsData?.build_url ||
                  jenkinsData?.url ||
                  "-"}
              </div>
            </div>
            <div className="card">
              <div className="card-title">빌드 번호</div>
              <div className="card-value">
                {jenkinsMeta?.build_number ??
                  jenkinsMeta?.number ??
                  jenkinsData?.build_number ??
                  jenkinsData?.number ??
                  "-"}
              </div>
              <div className="card-sub">
                {jenkinsMeta?.result ||
                  jenkinsMeta?.status ||
                  jenkinsData?.result ||
                  jenkinsData?.status ||
                  "-"}
              </div>
            </div>
            <div className="card">
              <div className="card-title">리포트 파일</div>
              <div className="card-value">
                {reportScan.files_total ?? jenkinsScan.files_total ?? "-"}
              </div>
              <div className="card-sub">
                HTML {reportFilesCount.html ?? jenkinsScan.html_count ?? 0} ·
                LOG {reportFilesCount.log ?? jenkinsScan.log_count ?? 0}
              </div>
            </div>
            <div className="card">
              <div className="card-title">FAIL/ERROR/WARN</div>
              <div className="card-value">
                {(jenkinsScan.FAIL_token ?? 0) +
                  (jenkinsScan.ERROR_token ?? 0) +
                  (jenkinsScan.WARN_token ?? 0)}
              </div>
              <div className="card-sub">
                {jenkinsScan.FAIL_token ?? 0} / {jenkinsScan.ERROR_token ?? 0} /{" "}
                {jenkinsScan.WARN_token ?? 0}
              </div>
            </div>
          </div>
          <div className="hint">소스: {reportSource.path || "-"}</div>
          <div className="panel">
            <h3>빌드 정보</h3>
            <div className="detail-grid">
              <div className="detail-row">
                <span className="detail-label">Job URL</span>
                <span className="detail-value">
                  {jenkinsMeta?.job_url ||
                    jenkinsMeta?.jobUrl ||
                    jenkinsData?.job_url ||
                    jenkinsData?.jobUrl ||
                    jenkinsJobUrl ||
                    "-"}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Build URL</span>
                <span className="detail-value">
                  {jenkinsMeta?.build_url ||
                    jenkinsMeta?.url ||
                    jenkinsData?.build_url ||
                    jenkinsData?.url ||
                    "-"}
                </span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Report Dir</span>
                <span className="detail-value">{reportDir}</span>
              </div>
              <div className="detail-row">
                <span className="detail-label">Build Root</span>
                <span className="detail-value">{buildRoot}</span>
              </div>
            </div>
            <div className="row">
              <button
                type="button"
                onClick={() => setActiveJenkinsTab("reports")}
              >
                리포트 탭 이동
              </button>
            </div>
          </div>
          {buildSummary.total > 0 ? (
            <div className="panel">
              <h3>프로젝트 빌드 요약</h3>
              <div className="row">
                <label>기간</label>
                <select
                  value={buildSummaryCount}
                  onChange={(e) => setBuildSummaryCount(Number(e.target.value))}
                >
                  {[5, 10, 20, 30].map((count) => (
                    <option key={count} value={count}>
                      최근 {count}개
                    </option>
                  ))}
                </select>
              </div>
              <div className="detail-grid">
                <div className="detail-row compact">
                  <span className="detail-label">Total</span>
                  <span className="detail-value">{buildSummary.total}</span>
                </div>
                <div className="detail-row compact">
                  <span className="detail-label">Success</span>
                  <span className="detail-value">{buildSummary.success}</span>
                </div>
                <div className="detail-row compact">
                  <span className="detail-label">Fail</span>
                  <span className="detail-value">{buildSummary.fail}</span>
                </div>
                <div className="detail-row compact">
                  <span className="detail-label">Unstable</span>
                  <span className="detail-value">{buildSummary.unstable}</span>
                </div>
                <div className="detail-row compact">
                  <span className="detail-label">Other</span>
                  <span className="detail-value">{buildSummary.other}</span>
                </div>
              </div>
              <div className="summary-chart">
                {buildSummaryBars.map((row) => (
                  <div key={row.label} className="bar-row">
                    <span className="bar-label">{row.label}</span>
                    <div className="bar">
                      <div
                        className={`bar-fill ${row.tone}`}
                        style={{
                          width: `${buildSummary.total ? (row.value / buildSummary.total) * 100 : 0}%`,
                        }}
                      />
                    </div>
                    <span className="bar-value">{row.value}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      )}

      {activeJenkinsTab === "scm" && (
        <JenkinsScmPanel
          scmPresets={scmPresets}
          scmDisplay={scmDisplay}
          jenkinsScmUrl={jenkinsScmUrl}
          setJenkinsScmUrl={setJenkinsScmUrl}
          jenkinsScmType={jenkinsScmType}
          setJenkinsScmType={setJenkinsScmType}
          jenkinsScmUsername={jenkinsScmUsername}
          setJenkinsScmUsername={setJenkinsScmUsername}
          jenkinsScmPassword={jenkinsScmPassword}
          setJenkinsScmPassword={setJenkinsScmPassword}
          jenkinsScmBranch={jenkinsScmBranch}
          setJenkinsScmBranch={setJenkinsScmBranch}
          jenkinsScmRevision={jenkinsScmRevision}
          setJenkinsScmRevision={setJenkinsScmRevision}
          loadJenkinsScmInfo={loadJenkinsScmInfo}
          downloadJenkinsSourceRoot={downloadJenkinsSourceRoot}
        />
      )}

      {activeJenkinsTab === "complexity" && (
        <JenkinsComplexityPanel
          loadJenkinsComplexity={loadJenkinsComplexity}
          jenkinsJobUrl={jenkinsJobUrl}
          jenkinsComplexityRows={jenkinsComplexityRows}
        />
      )}

      {activeJenkinsTab === "logs" && (
        <JenkinsLogsPanel
          loadJenkinsLogs={loadJenkinsLogs}
          jenkinsJobUrl={jenkinsJobUrl}
          jenkinsLogPath={jenkinsLogPath}
          setJenkinsLogPath={setJenkinsLogPath}
          readJenkinsLog={readJenkinsLog}
          jenkinsLogs={jenkinsLogs}
          jenkinsLogContent={jenkinsLogContent}
        />
      )}

      {activeJenkinsTab === "reports" && (
        <div>
          <h3 id="jenkins-reports">Jenkins Reports</h3>
          <div className="row">
            <button onClick={loadJenkinsDocs} disabled={!jenkinsJobUrl}>
              문서 로드
            </button>
          </div>
          {jenkinsDocsHtml ? (
            <iframe
              title="jenkins-docs"
              srcDoc={jenkinsDocsHtml}
              className="doc-frame"
            />
          ) : (
            <div className="empty">문서 없음</div>
          )}
          <h4>Summary</h4>
          <pre className="json">
            {JSON.stringify(reportSummary || jenkinsData?.summary || {}, null, 2)}
          </pre>
          <h4>Findings</h4>
          <pre className="json">
            {JSON.stringify(
              jenkinsData?.findings || jenkinsData?.summary?.findings || [],
              null,
              2
            )}
          </pre>
          <h4>History</h4>
          <pre className="json">
            {JSON.stringify(
              jenkinsData?.history || jenkinsData?.summary?.history || [],
              null,
              2
            )}
          </pre>
          <h4>Status</h4>
          <pre className="json">
            {JSON.stringify(
              reportKpis?.build || jenkinsData?.status || jenkinsData?.jenkins || {},
              null,
              2
            )}
          </pre>
          <h4>Report Files</h4>
          <div className="hint">빌드 캐시 루트: {buildRoot}</div>
          <div className="row">
            <button onClick={loadReportFiles} disabled={!jenkinsJobUrl}>
              파일 목록
            </button>
            <button
              onClick={() =>
                downloadReportZip &&
                downloadReportZip(
                  filteredReportFiles.map((item) => item.rel_path || item.path)
                )
              }
              disabled={!jenkinsJobUrl || filteredReportFiles.length === 0}
            >
              ZIP 다운로드(필터 적용)
            </button>
            <select
              value={reportScope}
              onChange={(e) => setReportScope(e.target.value)}
            >
              <option value="all">전체 모드</option>
              <option value="report">리포트 전용(중복 제거)</option>
              <option value="source">소스 전용</option>
            </select>
            <select
              value={reportView}
              onChange={(e) => setReportView(e.target.value)}
            >
              <option value="list">리스트 보기</option>
              <option value="tree">트리 보기</option>
            </select>
            <select
              value={reportExtFilter}
              onChange={(e) => setReportExtFilter(e.target.value)}
            >
              {reportExtOptions.map((opt) => (
                <option key={opt} value={opt}>
                  {opt}
                </option>
              ))}
            </select>
            <input
              placeholder="파일 검색"
              value={reportQuery}
              onChange={(e) => setReportQuery(e.target.value)}
            />
          </div>
          {reportView === "tree" ? (
            <div className="report-tree">
              {(function renderTree(node, depth = 0) {
                const folderKeys = Object.keys(node.children).sort();
                return (
                  <div className="report-tree-node" key={node.path || "."}>
                    {node.path ? (
                      <button
                        type="button"
                        className="report-tree-folder"
                        style={{ paddingLeft: `${depth * 14}px` }}
                        onClick={() => toggleTreeNode(node.path)}
                      >
                        {isTreeOpen(node.path) ? "▾" : "▸"} {node.name}
                      </button>
                    ) : null}
                    {isTreeOpen(node.path) &&
                      folderKeys.map((key) =>
                        renderTree(
                          node.children[key],
                          node.path ? depth + 1 : depth
                        )
                      )}
                    {isTreeOpen(node.path) &&
                      node.files
                        .sort((a, b) => a.name.localeCompare(b.name))
                        .map((file) => (
                          <div
                            key={file.rel}
                            className="report-tree-file"
                            style={{ paddingLeft: `${(depth + 1) * 14}px` }}
                          >
                            <span className="report-tree-label">
                              {file.name}
                            </span>
                            <div className="row">
                              <button
                                type="button"
                                className="btn-outline"
                                onClick={() =>
                                  downloadReportFile &&
                                  downloadReportFile(file.rel)
                                }
                              >
                                다운로드
                              </button>
                            </div>
                          </div>
                        ))}
                  </div>
                );
              })(reportTree)}
              {filteredReportFiles.length === 0 && (
                <div className="empty">
                  {reportScope === "source"
                    ? "소스 폴더 경로가 없습니다."
                    : "파일 없음"}
                </div>
              )}
            </div>
          ) : (
            <div className="list">
              {filteredReportFiles.map((item) => (
                <div key={item.rel_path || item.path} className="list-item">
                  <span className="list-text">
                    {item.rel_path || item.path}
                  </span>
                  <span className="list-snippet">
                    {item.ext} · {item.size}
                  </span>
                  <div className="row">
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={() =>
                        downloadReportFile &&
                        downloadReportFile(item.rel_path || item.path)
                      }
                    >
                      다운로드
                    </button>
                  </div>
                </div>
              ))}
              {filteredReportFiles.length === 0 && (
                <div className="empty">
                  {reportScope === "source"
                    ? "소스 폴더 경로가 없습니다."
                    : "파일 없음"}
                </div>
              )}
            </div>
          )}

          <h4>Jenkins 서버 루트 탐색</h4>
          <div className="hint">
            서버에 접근 가능한 경우에만 표시됩니다. (로컬 백엔드 기준)
          </div>
          <div className="row">
            <label style={{ minWidth: "80px" }}>대상</label>
            <select
              value={jenkinsServerRelPath || ""}
              onChange={(e) =>
                setJenkinsServerRelPath &&
                setJenkinsServerRelPath(e.target.value)
              }
            >
              <option value="workspace">workspace</option>
              <option value="userContent">userContent</option>
              <option value="email-templates">email-templates</option>
              <option value="jobs">jobs</option>
              <option value="">전체</option>
            </select>
            <input
              value={jenkinsServerRelPath || ""}
              onChange={(e) =>
                setJenkinsServerRelPath &&
                setJenkinsServerRelPath(e.target.value)
              }
              placeholder="상대 경로 (예: workspace/프로젝트)"
            />
          </div>
          <div className="row">
            <input
              value={jenkinsServerRoot || ""}
              onChange={(e) => setJenkinsServerRoot(e.target.value)}
              placeholder="C:\\ProgramData\\Jenkins\\.jenkins"
            />
            <button
              type="button"
              onClick={() =>
                loadJenkinsServerFiles &&
                loadJenkinsServerFiles(jenkinsServerRoot, jenkinsServerRelPath)
              }
              disabled={!jenkinsServerRoot || jenkinsServerFilesLoading}
            >
              {jenkinsServerFilesLoading ? "스캔 중..." : "서버 파일 스캔"}
            </button>
          </div>
          {jenkinsServerFilesError ? (
            <div className="error">{jenkinsServerFilesError}</div>
          ) : null}
          <div className="report-tree">
            {(function renderServerTree(node, depth = 0) {
              const folderKeys = Object.keys(node.children).sort();
              return (
                <div className="report-tree-node" key={node.path || "."}>
                  {node.path ? (
                    <button
                      type="button"
                      className="report-tree-folder"
                      style={{ paddingLeft: `${depth * 14}px` }}
                      onClick={() => toggleServerTreeNode(node.path)}
                    >
                      {isServerTreeOpen(node.path) ? "▾" : "▸"} {node.name}
                    </button>
                  ) : null}
                  {isServerTreeOpen(node.path) &&
                    folderKeys.map((key) =>
                      renderServerTree(
                        node.children[key],
                        node.path ? depth + 1 : depth
                      )
                    )}
                  {isServerTreeOpen(node.path) &&
                    node.files
                      .sort((a, b) => a.name.localeCompare(b.name))
                      .map((file) => (
                        <div
                          key={file.rel}
                          className="report-tree-file"
                          style={{ paddingLeft: `${(depth + 1) * 14}px` }}
                        >
                          <span className="report-tree-label">{file.name}</span>
                        </div>
                      ))}
                </div>
              );
            })(serverTree)}
            {jenkinsServerFiles.length === 0 && (
              <div className="empty">파일 없음</div>
            )}
          </div>
        </div>
      )}

      {activeJenkinsTab === "vcast" && (
        <JenkinsVCastPanel
          vcastRag={vcastRag}
          loadVcastRag={loadVcastRag}
          vcastLoading={vcastLoading}
          jenkinsJobUrl={jenkinsJobUrl}
          jenkinsCacheRoot={jenkinsCacheRoot}
          jenkinsBuildSelector={jenkinsBuildSelector}
          message={message}
          setMessage={setMessage}
          enqueueOp={enqueueJenkinsOp}
          updateOp={updateJenkinsOp}
        />
      )}
      {activeJenkinsTab === "qac" && (
        <QACReportGenerator
          mode="jenkins"
          jobUrl={jenkinsJobUrl}
          cacheRoot={jenkinsCacheRoot}
          buildSelector={jenkinsBuildSelector}
          sourceRoot={jenkinsSourceRoot}
          onOpenEditor={openEditorAt}
          onOpenArtifact={onGoAnalyzerArtifact}
          onMessage={setMessage}
          enqueueOp={enqueueJenkinsOp}
          updateOp={updateJenkinsOp}
        />
      )}
      {activeJenkinsTab === "excel-compare" && (
        <ExcelCompare onMessage={setMessage} />
      )}

      {activeJenkinsTab === "rag-ingest" && (
        <JenkinsRagIngestPanel runRagIngestFiles={runRagIngestFiles} />
      )}

      {activeJenkinsTab === "uds" && (
        <div>
          <div className="row">
            <h3>UDS Spec (DOCX)</h3>
            {typeof onGoAnalyzer === "function" ? (
              <button type="button" className="btn-outline" onClick={onGoAnalyzer}>
                Analyzer로 이동
              </button>
            ) : null}
          </div>
          <div className="panel">
            <label>UDS 템플릿(.docx)</label>
            <input
              type="file"
              accept=".docx"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file && uploadUdsTemplate) {
                  uploadUdsTemplate(file);
                }
              }}
            />
            <label>컴포넌트 리스트(선택, 없으면 폴더 기준)</label>
            <input
              type="file"
              accept=".json,.xlsx,.xls,.csv,.tsv,.txt"
              onChange={(e) => setUdsComponentList(e.target.files?.[0] || null)}
            />
            {udsTemplatePath ? (
              <div className="hint">템플릿 경로: {udsTemplatePath}</div>
            ) : (
              <div className="hint">
                템플릿 없이도 기본 양식으로 생성됩니다.
              </div>
            )}
            <label>추가 문서(선택)</label>
            <input
              type="file"
              multiple
              onChange={(e) =>
                setUdsExtraFiles(Array.from(e.target.files || []))
              }
            />
            <label>요구사항 문서(선택)</label>
            <input
              type="file"
              accept=".txt,.md,.doc,.docx,.pdf"
              multiple
              onChange={(e) => {
                const files = Array.from(e.target.files || []);
                setUdsReqFiles(files);
                handleReqFilePreview(files);
              }}
            />
            <label>참조 UDS 문서(옵션)</label>
            <input
              type="file"
              accept=".docx,.pdf,.txt,.md"
              onChange={(e) => setUdsRefDoc(e.target.files?.[0] || null)}
            />
            <label>SDS 문서(권장)</label>
            <input
              type="file"
              accept=".docx,.pdf,.xlsx,.xls,.txt,.md"
              onChange={(e) => setUdsSdsDoc(e.target.files?.[0] || null)}
            />
            <label>SRS 문서(권장)</label>
            <input
              type="file"
              accept=".docx,.pdf,.xlsx,.xls,.txt,.md"
              onChange={(e) => setUdsSrsDoc(e.target.files?.[0] || null)}
            />
            <div className="hint">
              필수: 코드(소스 루트) + (SRS 또는 SDS 1개 이상) / 옵션: 참조 UDS
            </div>
            <div className="row">
              <button
                type="button"
                className="btn-outline"
                onClick={addReqServerPath}
              >
                서버 파일 선택(.txt/.md/.pdf/.docx)
              </button>
            </div>
            <label>추적성 매핑 테이블(선택)</label>
            <input
              type="file"
              accept=".csv,.json,.txt"
              multiple
              onChange={(e) =>
                setUdsTraceMapFiles(Array.from(e.target.files || []))
              }
            />
            {Array.isArray(udsTraceMapFiles) && udsTraceMapFiles.length > 0 ? (
              <div className="hint">
                선택된 매핑 파일:{" "}
                {udsTraceMapFiles.map((f) => f.name).join(", ")}
              </div>
            ) : null}
            <div className="row">
              <button
                type="button"
                className="btn-outline"
                onClick={addTraceMapServerPath}
              >
                서버 매핑 파일 선택(.csv/.json/.txt)
              </button>
            </div>
            {Array.isArray(udsTraceMapServerPaths) &&
            udsTraceMapServerPaths.length > 0 ? (
              <div className="hint">{udsTraceMapServerPaths.join(", ")}</div>
            ) : null}
            <label>Logic Diagram 생성 기준</label>
            <select
              value={udsLogicSource}
              onChange={(e) => setUdsLogicSource(e.target.value)}
            >
              <option value="call_tree">함수 호출 트리 기반</option>
              <option value="state_table">상태 전이 표 기반</option>
              <option value="comment_pattern">주석 패턴 기반</option>
              <option value="">자동 생성 안함</option>
            </select>
            <label>Logic Diagram 이미지(선택)</label>
            <input
              type="file"
              accept=".png,.jpg,.jpeg,.gif,.webp,.svg"
              multiple
              onChange={(e) =>
                setUdsLogicFiles(Array.from(e.target.files || []))
              }
            />
            {Array.isArray(udsLogicFiles) && udsLogicFiles.length > 0 ? (
              <div className="hint">
                선택된 Logic Diagram:{" "}
                {udsLogicFiles.map((f) => f.name).join(", ")}
              </div>
            ) : null}
            <label>Logic Diagram 노드/깊이 설정</label>
            <div className="row">
              <input
                type="number"
                min="1"
                max="8"
                value={udsLogicMaxChildren}
                onChange={(e) =>
                  setUdsLogicMaxChildren(Number(e.target.value || 3))
                }
                placeholder="자식 노드 수"
              />
              <input
                type="number"
                min="1"
                max="6"
                value={udsLogicMaxGrandchildren}
                onChange={(e) =>
                  setUdsLogicMaxGrandchildren(Number(e.target.value || 2))
                }
                placeholder="하위 노드 수"
              />
              <input
                type="number"
                min="2"
                max="4"
                value={udsLogicMaxDepth}
                onChange={(e) =>
                  setUdsLogicMaxDepth(Number(e.target.value || 3))
                }
                placeholder="깊이"
              />
            </div>
            <label>Globals 표시 형식</label>
            <div className="row">
              <input
                type="text"
                value={udsGlobalsFormatOrder}
                onChange={(e) => setUdsGlobalsFormatOrder(e.target.value)}
                placeholder="Name,Type,File,Range"
              />
              <input
                type="text"
                value={udsGlobalsFormatSep}
                onChange={(e) => setUdsGlobalsFormatSep(e.target.value)}
                placeholder=" | "
              />
            </div>
            <label className="row-inline">
              <input
                type="checkbox"
                checked={!!udsGlobalsFormatWithLabels}
                onChange={(e) =>
                  setUdsGlobalsFormatWithLabels(e.target.checked)
                }
              />
              Globals 라벨 포함(Name=, Type=)
            </label>
            <label className="row-inline">
              <input
                type="checkbox"
                checked={!!udsAiEnabled}
                onChange={(e) => setUdsAiEnabled(e.target.checked)}
              />
              UDS AI 강화(요구사항 정제/소스 매칭/섹션 보강/로직 설명)
            </label>
            {udsAiEnabled ? (
              <>
                <label>UDS AI 예시 파일(선택)</label>
                <input
                  type="file"
                  accept=".txt,.md"
                  onChange={(e) =>
                    setUdsAiExampleFile(e.target.files?.[0] || null)
                  }
                />
                <div className="row">
                  <button
                    type="button"
                    className="btn-outline"
                    onClick={addAiExamplePath}
                  >
                    서버 예시 파일 선택
                  </button>
                  {udsAiExamplePath ? (
                    <span className="hint">{udsAiExamplePath}</span>
                  ) : null}
                </div>
                <label className="row-inline">
                  <input
                    type="checkbox"
                    checked={!!udsAiDetailed}
                    onChange={(e) => setUdsAiDetailed(e.target.checked)}
                  />
                  상세 구조 생성
                </label>
              </>
            ) : null}
            <div className="row">
              <label className="row-inline">
                <input
                  type="checkbox"
                  checked={!!udsSourceOnly}
                  onChange={(e) =>
                    setUdsSourceOnly && setUdsSourceOnly(e.target.checked)
                  }
                />
                소스코드 기반 생성(요약 없이)
              </label>
              <button
                type="button"
                onClick={() => {
                  if (!String(jenkinsSourceRoot || "").trim()) {
                    setMessage("코드(소스 루트)를 먼저 선택해주세요.");
                    return;
                  }
                  if (
                    effectiveUdsReqFiles.length === 0 &&
                    (!Array.isArray(udsReqServerPaths) || udsReqServerPaths.length === 0)
                  ) {
                    setMessage("최소 요건: SRS 또는 SDS 문서 1개 이상이 필요합니다.");
                    return;
                  }
                  if (!generateUdsDocx) return;
                  generateUdsDocx(
                    effectiveUdsExtraFiles,
                    effectiveUdsReqFiles,
                    udsLogicFiles,
                    udsReqServerPaths,
                    udsLogicSource,
                    udsAiEnabled,
                    udsAiExampleFile,
                    udsAiExamplePath,
                    udsAiDetailed,
                    udsLogicMaxChildren,
                    udsLogicMaxGrandchildren,
                    udsLogicMaxDepth,
                    udsGlobalsFormatOrder,
                    udsGlobalsFormatSep,
                    udsGlobalsFormatWithLabels,
                    udsComponentList
                  );
                }}
                disabled={udsUploading || udsGenerating}
              >
                {udsGenerating ? "생성 중..." : "UDS 생성"}
              </button>
              {udsGenerating && cancelUdsDocx ? (
                <button
                  type="button"
                  className="btn-outline"
                  onClick={cancelUdsDocx}
                >
                  생성 취소
                </button>
              ) : null}
              {udsResultUrl ? (
                <a
                  className="btn-outline"
                  href={udsResultUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  DOCX 다운로드
                </a>
              ) : null}
              <button
                type="button"
                className="btn-outline"
                onClick={loadUdsVersions}
              >
                버전 새로고침
              </button>
              <button
                type="button"
                className="btn-outline"
                onClick={() =>
                  previewUdsRequirements &&
                  previewUdsRequirements(
                    udsReqFiles,
                    udsReqServerPaths,
                    jenkinsSourceRoot,
                    udsTraceMapFiles,
                    udsTraceMapServerPaths
                  )
                }
              >
                요구사항 미리보기
              </button>
            </div>
            {udsProgress && (
              <div className="panel">
                <div className="row">
                  <strong>UDS 생성 진행</strong>
                  <span>{udsProgress.message || udsProgress.stage}</span>
                </div>
                <progress value={Number(udsProgress.percent || 0)} max="100" />
                <div className="hint">
                  {formatElapsed(udsProgress)}
                  {udsProgress.updated_at
                    ? ` · 업데이트 ${udsProgress.updated_at}`
                    : ""}
                </div>
              </div>
            )}
          </div>
          {Array.isArray(udsReqFiles) && udsReqFiles.length > 0 ? (
            <div className="panel">
              <h4>요구사항 파일(로컬)</h4>
              <div className="list">
                {udsReqFiles.map((file) => (
                  <div key={file.name} className="list-item">
                    <span className="list-text">{file.name}</span>
                    <span className="list-snippet">
                      {file.type || "unknown"}
                    </span>
                    <div className="row">
                      <button
                        type="button"
                        className="btn-outline"
                        onClick={() => {
                          const text = udsReqPreviewText?.[file.name];
                          if (text) {
                            setUdsReqPreviewName(file.name);
                            setUdsReqPreviewContent(text);
                          } else {
                            setMessage(
                              "미리보기는 .txt/.md 파일만 지원합니다."
                            );
                          }
                        }}
                      >
                        미리보기
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              {udsReqPreviewName ? (
                <div className="panel">
                  <h4>선택 파일 미리보기: {udsReqPreviewName}</h4>
                  <pre className="json">{udsReqPreviewContent}</pre>
                </div>
              ) : (
                <div className="empty">미리보기할 파일을 선택해주세요.</div>
              )}
            </div>
          ) : null}
          {Array.isArray(udsReqServerPaths) && udsReqServerPaths.length > 0 ? (
            <div className="panel">
              <h4>요구사항 파일(서버)</h4>
              <div className="list">
                {udsReqServerPaths.map((path) => (
                  <div key={path} className="list-item">
                    <span className="list-text">{path}</span>
                    <div className="row">
                      <button
                        type="button"
                        className="btn-outline"
                        onClick={() => previewReqServerPath(path)}
                      >
                        미리보기
                      </button>
                      <button
                        type="button"
                        className="btn-outline"
                        onClick={() =>
                          setUdsReqServerPaths((prev) =>
                            prev.filter((item) => item !== path)
                          )
                        }
                      >
                        제거
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              {udsReqServerPreviewName ? (
                <div className="panel">
                  <h4>선택 파일 미리보기: {udsReqServerPreviewName}</h4>
                  <pre className="json">{udsReqServerPreviewContent}</pre>
                </div>
              ) : (
                <div className="empty">미리보기할 파일을 선택해주세요.</div>
              )}
            </div>
          ) : null}
          {udsReqPreview?.items?.length ? (
            <div className="panel">
              <h4>요구사항 추출 결과</h4>
              <div className="list">
                {udsReqPreview.items.slice(0, 200).map((item, idx) => (
                  <div key={`${item.id}-${idx}`} className="list-item">
                    <span className="list-text">
                      {item.id || "ID 없음"} {item.name ? `- ${item.name}` : ""}
                    </span>
                    {item.description ? (
                      <span className="list-snippet">{item.description}</span>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {Array.isArray(udsReqMapping) && udsReqMapping.length > 0 ? (
            <div className="panel">
              <h4>요구사항–컴포넌트 매핑</h4>
              <div className="list">
                {udsReqMapping.slice(0, 200).map((row, idx) => (
                  <div
                    key={`${row.requirement_id}-${idx}`}
                    className="list-item"
                  >
                    <span className="list-text">
                      {row.requirement_id} {row.requirement_name || ""}
                    </span>
                    <span className="list-snippet">
                      SwCom: {(row.related_swcom || []).join(", ") || "N/A"} /
                      SwFn: {(row.related_swfn || []).join(", ") || "N/A"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {udsReqFunctionMapping?.items?.length ? (
            <div className="panel">
              <h4>요구사항–함수 매핑(스캔)</h4>
              <div className="list">
                {udsReqFunctionMapping.items.slice(0, 200).map((row, idx) => (
                  <div
                    key={`${row.requirement_id}-${idx}`}
                    className="list-item"
                  >
                    <span className="list-text">
                      {row.requirement_id || "ID 없음"}{" "}
                      {row.requirement_name ? `- ${row.requirement_name}` : ""}
                    </span>
                    <span className="list-snippet">
                      {Array.isArray(row.function_names) &&
                      row.function_names.length > 0
                        ? row.function_names.join(", ")
                        : "매핑 없음"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {udsReqTraceability?.mapping_pairs?.length ? (
            <div className="panel">
              <h4>요구사항–소스 ID 매핑(테이블)</h4>
              <div className="detail-grid">
                <div className="detail-row compact">
                  <span className="detail-label">요구사항 수</span>
                  <span className="detail-value">
                    {udsReqTraceability.total_requirements || 0}
                  </span>
                </div>
                <div className="detail-row compact">
                  <span className="detail-label">매핑 수</span>
                  <span className="detail-value">
                    {Array.isArray(udsReqTraceability.mapping_pairs)
                      ? udsReqTraceability.mapping_pairs.length
                      : 0}
                  </span>
                </div>
              </div>
              <div className="list">
                {udsReqTraceability.mapping_pairs
                  .slice(0, 200)
                  .map((row, idx) => (
                    <div
                      key={`${row.requirement_id}-${idx}`}
                      className="list-item"
                    >
                      <span className="list-text">
                        {row.requirement_id || "ID 없음"}
                      </span>
                      <span className="list-snippet">
                        {Array.isArray(row.source_ids)
                          ? row.source_ids.join(", ")
                          : "-"}
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          ) : null}
          {udsReqTraceMatrix?.rows?.length ? (
            <div className="panel">
              <h4>요구사항–테스트–소스 매트릭스</h4>
              <div className="detail-grid">
                <div className="detail-row compact">
                  <span className="detail-label">요구사항</span>
                  <span className="detail-value">
                    {udsReqTraceMatrix.summary?.requirement_count || 0}
                  </span>
                </div>
                <div className="detail-row compact">
                  <span className="detail-label">소스 매핑</span>
                  <span className="detail-value">
                    {udsReqTraceMatrix.summary?.mapped_source_count || 0}
                  </span>
                </div>
                <div className="detail-row compact">
                  <span className="detail-label">테스트 매핑</span>
                  <span className="detail-value">
                    {udsReqTraceMatrix.summary?.mapped_test_count || 0}
                  </span>
                </div>
              </div>
              <div className="list">
                {udsReqTraceMatrix.rows.slice(0, 200).map((row, idx) => (
                  <div
                    key={`${row.requirement_id}-${idx}`}
                    className="list-item"
                  >
                    <span className="list-text">
                      {row.requirement_id || "ID 없음"}
                    </span>
                    <span className="list-snippet">
                      소스:{" "}
                      {Array.isArray(row.source_ids)
                        ? row.source_ids.join(", ")
                        : "-"}
                      {" / "}
                      테스트:{" "}
                      {Array.isArray(row.test_ids)
                        ? row.test_ids.join(", ")
                        : "-"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {udsReqCompare ? (
            <div className="panel">
              <h4>요구사항–소스 비교</h4>
              <div className="detail-grid">
                <div className="detail-row compact">
                  <span className="detail-label">요구사항 총계</span>
                  <span className="detail-value">
                    {udsReqCompare.total_requirements ?? "-"}
                  </span>
                </div>
                <div className="detail-row compact">
                  <span className="detail-label">소스 매칭</span>
                  <span className="detail-value">
                    {Array.isArray(udsReqCompare.matched)
                      ? udsReqCompare.matched.length
                      : "-"}
                  </span>
                </div>
                <div className="detail-row compact">
                  <span className="detail-label">소스 미매칭</span>
                  <span className="detail-value">
                    {Array.isArray(udsReqCompare.missing)
                      ? udsReqCompare.missing.length
                      : "-"}
                  </span>
                </div>
                <div className="detail-row compact">
                  <span className="detail-label">소스만 존재</span>
                  <span className="detail-value">
                    {Array.isArray(udsReqCompare.source_only)
                      ? udsReqCompare.source_only.length
                      : "-"}
                  </span>
                </div>
              </div>
              {Array.isArray(udsReqCompare.missing) &&
              udsReqCompare.missing.length > 0 ? (
                <details>
                  <summary>미매칭 요구사항 보기</summary>
                  <div className="list">
                    {udsReqCompare.missing.slice(0, 200).map((id) => (
                      <div key={id} className="list-item">
                        <span className="list-text">{id}</span>
                      </div>
                    ))}
                  </div>
                </details>
              ) : null}
              {Array.isArray(udsReqCompare.source_only) &&
              udsReqCompare.source_only.length > 0 ? (
                <details>
                  <summary>소스만 존재하는 ID 보기</summary>
                  <div className="list">
                    {udsReqCompare.source_only.slice(0, 200).map((id) => (
                      <div key={`src-${id}`} className="list-item">
                        <span className="list-text">{id}</span>
                      </div>
                    ))}
                  </div>
                </details>
              ) : null}
            </div>
          ) : null}
          {Array.isArray(udsPlaceholders) && udsPlaceholders.length > 0 ? (
            <div className="panel">
              <h4>템플릿 치환 키</h4>
              <div className="list">
                {udsPlaceholders.map((key) => (
                  <div key={key} className="list-item">
                    <span className="list-text">{key}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {Array.isArray(udsVersions) && udsVersions.length > 0 ? (
            <div className="panel">
              <h4>생성된 버전</h4>
              <div className="list">
                {udsVersions.map((item) => (
                  <div key={item.filename} className="list-item">
                    <span className="list-text">{item.filename}</span>
                    <span className="list-snippet">{item.size} bytes</span>
                    <div className="row">
                      <input
                        className="input"
                        value={item.label || ""}
                        placeholder="라벨"
                        onChange={(e) =>
                          updateUdsLabelDraft &&
                          updateUdsLabelDraft(item.filename, e.target.value)
                        }
                      />
                      <button
                        type="button"
                        className="btn-outline"
                        onClick={() =>
                          updateUdsLabel &&
                          updateUdsLabel(item.filename, item.label || "")
                        }
                      >
                        라벨 저장
                      </button>
                      <button
                        type="button"
                        className="btn-outline"
                        onClick={() =>
                          deleteUdsVersion && deleteUdsVersion(item.filename)
                        }
                      >
                        삭제
                      </button>
                    </div>
                    <div className="row">
                      <a
                        className="btn-outline"
                        href={item.download_url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        다운로드
                      </a>
                      {item.preview_url ? (
                        <button
                          type="button"
                          className="btn-outline"
                          onClick={() =>
                            loadUdsPreview && loadUdsPreview(item.preview_url)
                          }
                        >
                          미리보기
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="btn-outline"
                        onClick={() => loadJenkinsUdsView(item.filename)}
                      >
                        상세 조회
                      </button>
                    </div>
                  </div>
                ))}
              </div>
              <div className="row">
                <select
                  value={udsDiffA}
                  onChange={(e) => setUdsDiffA(e.target.value)}
                >
                  <option value="">Diff A 선택</option>
                  {udsVersions.map((v) => (
                    <option key={v.filename} value={v.filename}>
                      {v.filename}
                    </option>
                  ))}
                </select>
                <select
                  value={udsDiffB}
                  onChange={(e) => setUdsDiffB(e.target.value)}
                >
                  <option value="">Diff B 선택</option>
                  {udsVersions.map((v) => (
                    <option key={v.filename} value={v.filename}>
                      {v.filename}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="btn-outline"
                  onClick={() => loadUdsDiff && loadUdsDiff(udsDiffA, udsDiffB)}
                  disabled={!udsDiffA || !udsDiffB}
                >
                  버전 Diff
                </button>
              </div>
            </div>
          ) : null}
          <UdsViewerWorkspace
            title="Jenkins UDS 상세 뷰"
            files={Array.isArray(udsVersions) ? udsVersions : []}
            selectedFilename={jenkinsUdsPickFilename}
            onSelectedFilenameChange={(name) => setJenkinsUdsPickFilename(name)}
            onRefreshFiles={loadUdsVersions}
            filesLoading={false}
            filesError=""
            onLoadView={async (name, params = {}) => {
              const picked = String(name || "").trim();
              if (!picked) return;
              setJenkinsUdsPickFilename(picked);
              await loadJenkinsUdsView(picked, params);
            }}
            viewData={jenkinsUdsView}
            viewLoading={jenkinsUdsViewLoading}
            viewError={jenkinsUdsViewError}
            urlStateKey="jenkins_uds"
            sourceRoot={jenkinsSourceRoot}
          />
          {udsDiff ? (
            <div className="panel">
              <h4>버전 Diff 결과</h4>
              <div className="list">
                {Object.entries(udsDiff).map(([section, diff]) => (
                  <div key={section} className="list-item">
                    <span className="list-text">{section}</span>
                    <span className="list-snippet">
                      추가: {(diff.added || []).length} / 삭제:{" "}
                      {(diff.removed || []).length}
                    </span>
                    <div className="row">
                      <details>
                        <summary>추가 항목 보기</summary>
                        <div className="list">
                          {(diff.added || []).slice(0, 200).map((item, idx) => (
                            <div
                              key={`add-${section}-${idx}`}
                              className="list-item"
                            >
                              <span className="list-text">{item}</span>
                            </div>
                          ))}
                        </div>
                      </details>
                      <details>
                        <summary>삭제 항목 보기</summary>
                        <div className="list">
                          {(diff.removed || [])
                            .slice(0, 200)
                            .map((item, idx) => (
                              <div
                                key={`del-${section}-${idx}`}
                                className="list-item"
                              >
                                <span className="list-text">{item}</span>
                              </div>
                            ))}
                        </div>
                      </details>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {udsPreviewHtml ? (
            <div className="panel">
              <h4>미리보기</h4>
              <div
                className="html-preview"
                dangerouslySetInnerHTML={{ __html: udsPreviewHtml }}
              />
            </div>
          ) : null}
          <div className="panel">
            <h4>RAG 검색 (Jenkins)</h4>
            <div className="row">
              <input
                placeholder="질문 또는 키워드"
                value={jenkinsRagQuery || ""}
                onChange={(e) =>
                  setJenkinsRagQuery && setJenkinsRagQuery(e.target.value)
                }
              />
              <select
                value={jenkinsRagCategory || "all"}
                onChange={(e) =>
                  setJenkinsRagCategory && setJenkinsRagCategory(e.target.value)
                }
              >
                <option value="all">전체</option>
                <option value="uds">UDS</option>
                <option value="requirements">요구사항</option>
                <option value="code">코드</option>
                <option value="vectorcast">VectorCAST</option>
              </select>
              <button
                type="button"
                className="btn-outline"
                onClick={() => runJenkinsRagQuery && runJenkinsRagQuery()}
                disabled={jenkinsRagLoading}
              >
                {jenkinsRagLoading ? "검색 중..." : "검색"}
              </button>
            </div>
            <div className="list">
              {(jenkinsRagResults || []).map((item, idx) => (
                <div
                  key={`${item.title || "item"}-${idx}`}
                  className="list-item"
                >
                  <span className="list-text">
                    {item.title || item.source_file || "-"}
                  </span>
                  <span className="list-snippet">
                    {item.category || "-"} · score{" "}
                    {Number(item.score || 0).toFixed(3)}
                  </span>
                  {item.snippet ? (
                    <div className="hint">{item.snippet}</div>
                  ) : null}
                </div>
              ))}
              {(jenkinsRagResults || []).length === 0 && (
                <div className="empty">검색 결과 없음</div>
              )}
            </div>
          </div>
        </div>
      )}

      {activeJenkinsTab === "calltree" && (
        <div>
          <h3>Function Call Tree</h3>
          <div className="section">
            <label>엔트리 함수(쉼표/줄바꿈 구분)</label>
            <textarea
              rows={3}
              value={callEntry}
              onChange={(e) => setCallEntry(e.target.value)}
              placeholder="예) main, App_Init, Task_Run"
            />
            <label>검색/필터</label>
            <input
              value={callSearch}
              onChange={(e) => setCallSearch(e.target.value)}
              placeholder="함수 이름 검색"
            />
            <label>최대 깊이</label>
            <input
              type="number"
              min={1}
              max={12}
              value={callDepth}
              onChange={(e) => setCallDepth(Number(e.target.value || 5))}
            />
            <label>compile_commands.json 경로(선택)</label>
            <input
              value={compileCommandsPath}
              onChange={(e) => setCompileCommandsPath(e.target.value)}
              placeholder="비워두면 소스 루트에서 자동 탐색"
            />
            <label>포함 경로(쉼표/줄바꿈 구분)</label>
            <textarea
              rows={2}
              value={callInclude}
              onChange={(e) => setCallInclude(e.target.value)}
              placeholder="예) source, Sources/APP"
            />
            <label>제외 경로(쉼표/줄바꿈 구분)</label>
            <textarea
              rows={2}
              value={callExclude}
              onChange={(e) => setCallExclude(e.target.value)}
              placeholder="예) build, external, vendor"
            />
            <label>최대 파일 수</label>
            <input
              type="number"
              min={100}
              max={20000}
              value={callMaxFiles}
              onChange={(e) => setCallMaxFiles(Number(e.target.value || 2000))}
            />
            <label>외부 라이브러리 함수 표시</label>
            <input
              type="checkbox"
              checked={!!callIncludeExternal}
              onChange={(e) => setCallIncludeExternal(e.target.checked)}
            />
            {callIncludeExternal && (
              <>
                <label>외부 함수 필터(헤더/라이브러리)</label>
                <input
                  value={externalFilter}
                  onChange={(e) => setExternalFilter(e.target.value)}
                  placeholder="예) stdio, string"
                />
              </>
            )}
            <div className="row">
              <button
                onClick={() => {
                  if (!loadCallTree) return;
                  runTrackedOp("calltree", "콜 트리 생성", () =>
                    loadCallTree({
                      entry: callEntry,
                      maxDepth: callDepth,
                      includePaths: callInclude
                        .split(/[\n,]/)
                        .map((s) => s.trim())
                        .filter(Boolean),
                      excludePaths: callExclude
                        .split(/[\n,]/)
                        .map((s) => s.trim())
                        .filter(Boolean),
                      maxFiles: callMaxFiles,
                      includeExternal: callIncludeExternal,
                      compileCommandsPath: compileCommandsPath.trim(),
                      externalMap: callTreeExternalMap || [],
                    })
                  );
                }}
                disabled={!jenkinsJobUrl || !callEntry.trim()}
              >
                콜 트리 생성
              </button>
              <button
                onClick={() => {
                  if (!saveCallTree) return;
                  runTrackedOp("calltree", "콜 트리 리포트 저장", () =>
                    saveCallTree({
                      entry: callEntry,
                      maxDepth: callDepth,
                      includePaths: callInclude
                        .split(/[\n,]/)
                        .map((s) => s.trim())
                        .filter(Boolean),
                      excludePaths: callExclude
                        .split(/[\n,]/)
                        .map((s) => s.trim())
                        .filter(Boolean),
                      maxFiles: callMaxFiles,
                      includeExternal: callIncludeExternal,
                      compileCommandsPath: compileCommandsPath.trim(),
                      outputFormat: callReportFormat,
                      externalMap: callTreeExternalMap || [],
                      htmlTemplate: callTreeHtmlTemplate || "",
                    })
                  );
                }}
                disabled={!jenkinsJobUrl || !callEntry.trim()}
              >
                리포트 저장
              </button>
              <select
                value={callReportFormat}
                onChange={(e) => setCallReportFormat(e.target.value)}
              >
                <option value="json">JSON</option>
                <option value="html">HTML</option>
                <option value="csv">CSV</option>
              </select>
              <button
                onClick={() =>
                  downloadCallTreeReport &&
                  downloadCallTreeReport(callTreeReport)
                }
                disabled={!callTreeReport}
              >
                리포트 다운로드
              </button>
              <button
                onClick={() => {
                  if (!previewCallTreeHtml) return;
                  previewCallTreeHtml(callTreeHtmlTemplate || "");
                  setShowTemplatePreview(true);
                }}
                disabled={!callTree}
              >
                템플릿 미리보기
              </button>
              <span className="hint">
                소스 루트: {jenkinsSourceRoot || "미설정"}
              </span>
            </div>
            {callTreeReport && (
              <div className="hint">저장된 리포트: {callTreeReport}</div>
            )}
          </div>
          {showTemplatePreview && (
            <div className="panel">
              <div className="row">
                <h4>템플릿 미리보기</h4>
                <button
                  type="button"
                  className="btn-link"
                  onClick={() => setShowTemplatePreview(false)}
                >
                  닫기
                </button>
              </div>
              {callTreePreviewHtml ? (
                <iframe
                  title="call-tree-preview"
                  srcDoc={callTreePreviewHtml}
                  className="doc-frame"
                />
              ) : (
                <div className="empty">미리보기 결과 없음</div>
              )}
            </div>
          )}
          <div className="panel">
            <h4>요약</h4>
            <div className="row">
              <span className="hint">
                파일 {callTreeStats.files_scanned ?? "-"}
              </span>
              <span className="hint">
                함수 {callTreeStats.functions ?? "-"}
              </span>
              <span className="hint">간선 {callTreeStats.edges ?? "-"}</span>
            </div>
            {callTreeMissing.length > 0 && (
              <div className="empty">
                미발견 엔트리: {callTreeMissing.join(", ")}
              </div>
            )}
          </div>
          <div className="list">
            {callTreeRoots.map((root) => renderCallTree(root, 0))}
            {callTreeRoots.length === 0 && (
              <div className="empty">콜 트리 결과 없음</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default JenkinsWorkflow;
