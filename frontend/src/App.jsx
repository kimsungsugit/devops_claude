import { useEffect, useMemo, useRef, useState, useCallback, lazy, Suspense } from "react";
import "./App.css";
import AppHeader from "./components/AppHeader";
import PrimaryNav from "./components/PrimaryNav";
import StatusPill from "./components/StatusPill";
import SimpleMarkdown from "./components/SimpleMarkdown";
import ToastContainer from "./components/Toast";
import ConfirmDialog from "./components/ConfirmDialog";
import ErrorBoundary from "./components/ErrorBoundary";
import {
  copyToClipboard,
  splitList,
  joinList,
  jumpTo,
  escapeRegExp,
  parseSearch,
  searchMatch,
  parseGitStatus,
  parseDiffRows,
  buildChatHistory,
  getInitialTheme,
} from "./utils/helpers";

const JenkinsDashboard = lazy(() => import("./views/JenkinsDashboard"));
const JenkinsWorkflow = lazy(() => import("./views/JenkinsWorkflow"));
const LocalDashboard = lazy(() => import("./views/LocalDashboard"));
const LocalEditor = lazy(() => import("./views/LocalEditor"));
const LocalWorkflow = lazy(() => import("./views/LocalWorkflow"));
const SettingsPanel = lazy(() => import("./views/SettingsPanel"));
const UdsAnalyzerView = lazy(() => import("./views/UdsAnalyzerView"));
const VCastReportGenerator = lazy(() => import("./views/VCastReportGenerator"));

import { useJenkinsConfig, useChat, useUDS } from "./contexts/AppContexts.jsx";
export { useToast, useConfirm, useUI, useSession, useJenkinsConfig, useChat, useUDS } from "./contexts/AppContexts.jsx";

const isDev = import.meta.env.DEV;
const devLog = (...args) => { if (isDev) console.log(...args); };
const devErr = (...args) => { if (isDev) console.error(...args); };

const api = async (path, options = {}) => {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    let msg = text || `HTTP ${res.status}`;
    try {
      const j = JSON.parse(text);
      if (j && typeof j.detail === "string") msg = j.detail;
      else if (j && typeof j.message === "string") msg = j.message;
    } catch (_) {}
    throw new Error(msg);
  }
  return res.json();
};

const postSseJson = async (path, payload, { onEvent } = {}) => {
  const res = await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  if (!res.body) {
    throw new Error("?ㅽ듃由??묐떟 蹂몃Ц???놁뒿?덈떎.");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  const emitEvent = (raw) => {
    const lines = String(raw || "")
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim());
    if (!lines.length) return;
    const text = lines.join("\n");
    if (!text) return;
    let payloadObj = null;
    try {
      payloadObj = JSON.parse(text);
    } catch (_) {
      payloadObj = { type: "message", text };
    }
    if (typeof onEvent === "function") onEvent(payloadObj);
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      emitEvent(chunk);
      boundary = buffer.indexOf("\n\n");
    }

    if (done) break;
  }

  if (buffer.trim()) emitEvent(buffer);
};

const injectBaseHref = (html, href) => {
  const baseTag = `<base href="${href}">`;
  if (/<base\s/i.test(html)) return html;
  if (/<head[^>]*>/i.test(html)) {
    return html.replace(/<head[^>]*>/i, (m) => `${m}\n${baseTag}`);
  }
  return `${baseTag}\n${html}`;
};


const STORAGE_KEYS = {
  SESSION_ID: "devops_session_id",
  JENKINS: "devops_jenkins",
};

let toastId = 0;

function App() {
  const [toasts, setToasts] = useState([]);
  const showToast = useCallback((type, message, duration) => {
    const id = ++toastId;
    setToasts((prev) => [...prev, { id, type, message, duration }]);
  }, []);
  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const [confirmState, setConfirmState] = useState(null);
  const askConfirm = useCallback((opts) => {
    return new Promise((resolve) => {
      setConfirmState({ ...opts, resolve });
    });
  }, []);
  const handleConfirmOk = useCallback(() => {
    confirmState?.resolve(true);
    setConfirmState(null);
  }, [confirmState]);
  const handleConfirmCancel = useCallback(() => {
    confirmState?.resolve(false);
    setConfirmState(null);
  }, [confirmState]);

  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState(() => {
    if (typeof window === "undefined") return "";
    return window.localStorage.getItem(STORAGE_KEYS.SESSION_ID) || "";
  });
  const [sessionName, setSessionName] = useState("");
  const [config, setConfig] = useState(null);
  const [options, setOptions] = useState({});
  const [summary, setSummary] = useState({});
  const [findings, setFindings] = useState([]);
  const [history, setHistory] = useState([]);
  const [status, setStatus] = useState({});
  const [logs, setLogs] = useState([]);
  const [exports, setExports] = useState([]);
  const [profiles, setProfiles] = useState([]);
  const [selectedProfile, setSelectedProfile] = useState("");
  const [profileName, setProfileName] = useState("");
  const [showProfileDelete, setShowProfileDelete] = useState(false);
  const [mode, setMode] = useState("local");
  const [primaryView, setPrimaryView] = useState("dashboard");
  const [localPrimaryView, setLocalPrimaryView] = useState("dashboard");
  const [jenkinsPrimaryView, setJenkinsPrimaryView] = useState("dashboard");
  const [activeTab, setActiveTab] = useState("overview");
  const [activeJenkinsTab, setActiveJenkinsTab] = useState("project");
  const [detailTab, setDetailTab] = useState("status");
  const [filterTool, setFilterTool] = useState("all");
  const [searchTerm, setSearchTerm] = useState("");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [runMeta, setRunMeta] = useState({
    active: false,
    pid: null,
    startedAt: "",
    logPath: "",
    statusPath: "",
  });
  const [lastLogAt, setLastLogAt] = useState("");
  const [preflight, setPreflight] = useState(null);
  const [preflightError, setPreflightError] = useState("");
  const [preflightLoading, setPreflightLoading] = useState(false);
  const preflightConfigKey = useMemo(() => {
    if (!config) return "";
    const key = {
      project_root: config.project_root || "",
      git_incremental: !!config.git_incremental,
      do_build: !!config.do_build,
      do_asan: !!config.do_asan,
      do_coverage: !!config.do_coverage,
      enable_test_gen: !!config.enable_test_gen,
      auto_run_tests: !!config.auto_run_tests,
      do_clang_tidy: !!config.do_clang_tidy,
      enable_semgrep: !!config.enable_semgrep,
      do_syntax_check: config.do_syntax_check !== false,
      do_qemu: !!config.do_qemu,
      do_docs: !!config.do_docs,
      do_fuzz: !!config.do_fuzz,
      cppcheck_levels: Array.isArray(config.cppcheck_levels)
        ? config.cppcheck_levels
        : config.cppcheck_enable || [],
    };
    try {
      return JSON.stringify(key);
    } catch (_) {
      return String(Date.now());
    }
  }, [config]);
  const workflowLeftDefault = 260;
  const workflowRightDefault = 320;
  const [workflowLeftWidth, setWorkflowLeftWidth] =
    useState(workflowLeftDefault);
  const [workflowRightWidth, setWorkflowRightWidth] =
    useState(workflowRightDefault);
  const [workflowDragging, setWorkflowDragging] = useState(null);
  const workflowSplitRef = useRef(null);
  const [complexityRows, setComplexityRows] = useState([]);
  const [docsHtml, setDocsHtml] = useState("");
  const [kbEntries, setKbEntries] = useState([]);
  const kbLoadInFlightRef = useRef(false);
  const [logFiles, setLogFiles] = useState({});
  const [selectedLogPath, setSelectedLogPath] = useState("");
  const [logContent, setLogContent] = useState("");
  const [kbDeleteKey, setKbDeleteKey] = useState("");
  const [theme, setTheme] = useState(getInitialTheme);
  const [isInitialLoad, setIsInitialLoad] = useState(true);
  const [pickerBusy, setPickerBusy] = useState(false);
  const [pickerLabel, setPickerLabel] = useState("");
  const pickerTimerRef = useRef(null);
  const pickerHintTimerRef = useRef(null);
  const localReportSummaryInFlightRef = useRef(false);
  const [editorPath, setEditorPath] = useState("");
  const [editorText, setEditorText] = useState("");
  const [editorStartLine, setEditorStartLine] = useState(1);
  const [editorEndLine, setEditorEndLine] = useState(1);
  const [editorFocusRequest, setEditorFocusRequest] = useState(null);
  const [scmMode, setScmMode] = useState("git");
  const [scmWorkdir, setScmWorkdir] = useState(".");
  const [scmRepoUrl, setScmRepoUrl] = useState("");
  const [scmBranch, setScmBranch] = useState("");
  const [scmDepth, setScmDepth] = useState(0);
  const [scmRevision, setScmRevision] = useState("");
  const [scmOutput, setScmOutput] = useState("");
  const {
    jenkinsBaseUrl, setJenkinsBaseUrl,
    jenkinsJobUrl, setJenkinsJobUrl,
    jenkinsUsername, setJenkinsUsername,
    jenkinsToken, setJenkinsToken,
    jenkinsVerifyTls, setJenkinsVerifyTls,
    jenkinsCacheRoot, setJenkinsCacheRoot,
    jenkinsBuildSelector, setJenkinsBuildSelector,
    jenkinsServerRoot, setJenkinsServerRoot,
    jenkinsServerRelPath, setJenkinsServerRelPath,
    jenkinsScmType, setJenkinsScmType,
    jenkinsScmUrl, setJenkinsScmUrl,
    jenkinsScmUsername, setJenkinsScmUsername,
    jenkinsScmPassword, setJenkinsScmPassword,
    jenkinsScmBranch, setJenkinsScmBranch,
    jenkinsScmRevision, setJenkinsScmRevision,
  } = useJenkinsConfig();
  const [jenkinsJobs, setJenkinsJobs] = useState([]);
  const [jenkinsJobsLoading, setJenkinsJobsLoading] = useState(false);
  const [jenkinsBuilds, setJenkinsBuilds] = useState([]);
  const [jenkinsData, setJenkinsData] = useState(null);
  const [jenkinsLogs, setJenkinsLogs] = useState({});
  const [jenkinsLogPath, setJenkinsLogPath] = useState("");
  const [jenkinsLogContent, setJenkinsLogContent] = useState("");
  const [jenkinsComplexityRows, setJenkinsComplexityRows] = useState([]);
  const [jenkinsDocsHtml, setJenkinsDocsHtml] = useState("");
  const [jenkinsSourceDownload, setJenkinsSourceDownload] = useState({
    loading: false,
    ok: null,
    message: "",
    path: "",
  });
  const [jenkinsReportAnchor, setJenkinsReportAnchor] = useState("");
  const [sessionReportFiles, setSessionReportFiles] = useState({
    files: [],
    ext_counts: {},
  });
  const [localReports, setLocalReports] = useState([]);
  const [localReportsLoading, setLocalReportsLoading] = useState(false);
  const [localReportsError, setLocalReportsError] = useState("");
  const [jenkinsReportFiles, setJenkinsReportFiles] = useState({
    files: [],
    ext_counts: {},
  });
  const [jenkinsServerFiles, setJenkinsServerFiles] = useState([]);
  const [jenkinsServerFilesLoading, setJenkinsServerFilesLoading] =
    useState(false);
  const [jenkinsServerFilesError, setJenkinsServerFilesError] = useState("");
  const [localReportSummaries, setLocalReportSummaries] = useState([]);
  const [localReportComparisons, setLocalReportComparisons] = useState([]);
  const [jenkinsReportSummary, setJenkinsReportSummary] = useState(null);
  const [jenkinsCallTree, setJenkinsCallTree] = useState(null);
  const [jenkinsCallTreeReport, setJenkinsCallTreeReport] = useState("");
  const [jenkinsCallTreePreviewHtml, setJenkinsCallTreePreviewHtml] =
    useState("");
  const [jenkinsVcastRag, setJenkinsVcastRag] = useState(null);
  const [jenkinsVcastLoading, setJenkinsVcastLoading] = useState(false);
  const [autoPublishReports, setAutoPublishReports] = useState(false);
  const [jenkinsSourceRoot, setJenkinsSourceRoot] = useState("");
  const [analyzerSourceRoot, setAnalyzerSourceRoot] = useState("");
  const [jenkinsSourceRootRemote, setJenkinsSourceRootRemote] = useState("");
  const [jenkinsSourceCandidates, setJenkinsSourceCandidates] = useState([]);
  const [jenkinsArtifactUrl, setJenkinsArtifactUrl] = useState("");
  // Jenkins SCM and config states are now provided by JenkinsConfigContext
  const [autoSelectJenkinsSource, setAutoSelectJenkinsSource] = useState(true);
  const {
    udsTemplatePath, setUdsTemplatePath,
    udsUploading, setUdsUploading,
    udsGenerating, setUdsGenerating,
    udsResultUrl, setUdsResultUrl,
    udsVersions, setUdsVersions,
    udsPreviewHtml, setUdsPreviewHtml,
    udsPlaceholders, setUdsPlaceholders,
    udsSourceOnly, setUdsSourceOnly,
    udsReqPreview, setUdsReqPreview,
    udsReqMapping, setUdsReqMapping,
    udsReqCompare, setUdsReqCompare,
    udsReqFunctionMapping, setUdsReqFunctionMapping,
    udsReqTraceability, setUdsReqTraceability,
    udsReqTraceMatrix, setUdsReqTraceMatrix,
    udsDiff, setUdsDiff,
  } = useUDS();
  const [ragStatus, setRagStatus] = useState(null);
  const [ragIngestResult, setRagIngestResult] = useState(null);
  const [localRagQuery, setLocalRagQuery] = useState("");
  const [localRagCategory, setLocalRagCategory] = useState("all");
  const [localRagResults, setLocalRagResults] = useState([]);
  const [localRagLoading, setLocalRagLoading] = useState(false);
  const [jenkinsRagQuery, setJenkinsRagQuery] = useState("");
  const [jenkinsRagCategory, setJenkinsRagCategory] = useState("all");
  const [jenkinsRagResults, setJenkinsRagResults] = useState([]);
  const [jenkinsRagLoading, setJenkinsRagLoading] = useState(false);
  const [explorerRoot, setExplorerRoot] = useState(".");
  const [explorerMap, setExplorerMap] = useState({});
  const [expandedPaths, setExpandedPaths] = useState([]);
  const [explorerLoading, setExplorerLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [replaceQuery, setReplaceQuery] = useState("");
  const [replaceValue, setReplaceValue] = useState("");
  const [gitStatus, setGitStatus] = useState("");
  const [gitDiff, setGitDiff] = useState("");
  const [gitDiffStaged, setGitDiffStaged] = useState("");
  const [gitLog, setGitLog] = useState("");
  const [gitBranches, setGitBranches] = useState("");
  const [gitBranchName, setGitBranchName] = useState("");
  const [gitCommitMessage, setGitCommitMessage] = useState("");
  const [gitPathInput, setGitPathInput] = useState("");
  const {
    chatInput, setChatInput,
    chatMessages, setChatMessages,
    chatPending, setChatPending,
    chatSidebarOpen, setChatSidebarOpen,
    chatDrawerOpen, setChatDrawerOpen,
    chatEndRef, lastChatQuestion,
  } = useChat();
  const [showShortcutHelp, setShowShortcutHelp] = useState(false);

  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: "smooth" }); }, [chatMessages, chatEndRef]);

  useEffect(() => {
    const views = ["dashboard", "workflow", "editor", "analyzer", "settings"];
    const handler = (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.isContentEditable) return;
      if (e.ctrlKey && e.key >= "1" && e.key <= "5") {
        e.preventDefault();
        setPrimaryView(views[parseInt(e.key) - 1]);
      }
      if (e.ctrlKey && e.key === "/") {
        e.preventDefault();
        setChatSidebarOpen((p) => !p);
      }
      if (e.key === "F1") {
        e.preventDefault();
        setShowShortcutHelp((p) => !p);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);


  const callTreeExternalMap = useMemo(() => {
    const raw = config?.call_tree_external_map;
    if (Array.isArray(raw)) return raw;
    if (!raw) return [];
    if (typeof raw === "string") {
      try {
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
      } catch (e) {
        return [];
      }
    }
    return [];
  }, [config?.call_tree_external_map]);
  const callTreeHtmlTemplate =
    typeof config?.call_tree_html_template === "string"
      ? config.call_tree_html_template
      : "";

  const currentSession = useMemo(
    () => sessions.find((s) => s.id === sessionId),
    [sessions, sessionId]
  );

  const statusTone = useMemo(() => {
    const state = String(status?.state || "").toLowerCase();
    if (!state) return "neutral";
    if (state.includes("run")) return "running";
    if (state.includes("fail") || state.includes("error")) return "error";
    if (state.includes("complete") || state.includes("success"))
      return "success";
    return "neutral";
  }, [status]);

  const sessionLabel = useMemo(() => {
    if (!sessionId) return "?몄뀡 ?놁쓬";
    return currentSession?.name || sessionId;
  }, [currentSession, sessionId]);

  const headerSub = useMemo(() => {
    if (mode === "jenkins") {
      return jenkinsJobUrl
        ? `Jenkins: ${jenkinsJobUrl}`
        : "Jenkins 프로젝트 선택";
    }
    const when = currentSession?.generated_at || "-";
    return `세션 생성: ${when}`;
  }, [mode, jenkinsJobUrl, currentSession]);

  const headerTitle = useMemo(() => {
    if (mode === "jenkins") {
      if (primaryView === "settings") return "Settings";
      if (primaryView === "analyzer") return "Analyzer";
      return primaryView === "workflow"
        ? "Jenkins Workflow"
        : "Jenkins Dashboard";
    }
    if (primaryView === "settings") return "Settings";
    if (primaryView === "analyzer") return "Analyzer";
    if (primaryView === "editor") return "Editor Workspace";
    if (primaryView === "workflow") return "Workflow Studio";
    return "Information Dashboard";
  }, [mode, primaryView]);

  const breadcrumbs = useMemo(() => {
    const modeLabel = mode === "jenkins" ? "Jenkins" : "Local";
    const viewLabel =
      primaryView === "workflow"
        ? "Workflow"
        : primaryView === "editor"
          ? "Editor"
          : primaryView === "analyzer"
            ? "Analyzer"
          : primaryView === "settings"
            ? "Settings"
            : "Dashboard";
    return ["Devops", modeLabel, viewLabel];
  }, [mode, primaryView]);

  useEffect(() => {
    if (typeof document !== "undefined") {
      document.body.dataset.theme = theme;
    }
    if (typeof window !== "undefined") {
      window.localStorage.setItem("devops_theme", theme);
    }
  }, [theme]);

  useEffect(() => {
    if (mode === "jenkins" && jenkinsSourceRoot) {
      setExplorerRoot(".");
      setExplorerMap({});
      setExpandedPaths([]);
    }
  }, [mode, jenkinsSourceRoot]);

  useEffect(() => {
    if (!jenkinsJobUrl || typeof window === "undefined") return;
    const key = `devops_jenkins_source_root:${jenkinsJobUrl}`;
    const saved = window.localStorage.getItem(key);
    if (saved) {
      setJenkinsSourceRoot(saved);
    }
  }, [jenkinsJobUrl]);

  useEffect(() => {
    if (!jenkinsJobUrl || typeof window === "undefined") return;
    const key = `devops_jenkins_source_root:${jenkinsJobUrl}`;
    if (jenkinsSourceRoot) {
      window.localStorage.setItem(key, jenkinsSourceRoot);
    } else {
      window.localStorage.removeItem(key);
    }
  }, [jenkinsJobUrl, jenkinsSourceRoot]);

  useEffect(() => {
    if (mode === "jenkins" && primaryView === "editor") {
      setActiveJenkinsTab("dashboard");
      loadJenkinsSourceRoot();
    }
  }, [mode, primaryView]);

  useEffect(() => {
    if (mode === "local") {
      setPrimaryView(localPrimaryView);
    } else if (mode === "jenkins") {
      setPrimaryView(jenkinsPrimaryView);
    }
  }, [mode]);

  const handlePrimaryChange = (next) => {
    setPrimaryView(next);
    if (mode === "local") {
      setLocalPrimaryView(next);
    } else {
      setJenkinsPrimaryView(next);
    }
    if (mode === "local") {
      if (next === "dashboard") setActiveTab("overview");
      if (next === "editor") setActiveTab("editor");
      if (next === "workflow") {
        setActiveTab((prev) =>
          prev === "overview" || prev === "editor" ? "quality" : prev
        );
        setWorkflowLeftWidth(workflowLeftDefault);
        setWorkflowRightWidth(workflowRightDefault);
        setWorkflowDragging(null);
      }
      return;
    }
    if (next === "dashboard") setActiveJenkinsTab("dashboard");
    if (next === "workflow") setActiveJenkinsTab("project");
  };

  const handleJenkinsSourceSelect = (path) => {
    if (!path) return;
    devLog("[jenkins] select source root ->", path);
    setEditorPath("");
    setEditorText("");
    setEditorStartLine(1);
    setEditorEndLine(1);
    setEditorFocusRequest(null);
    setSearchQuery("");
    setSearchResults([]);
    setReplaceQuery("");
    setReplaceValue("");
    setJenkinsSourceRoot(path);
    if (!jenkinsSourceRootRemote) {
      setJenkinsSourceRootRemote("");
    }
    handlePrimaryChange("editor");
    setActiveTab("editor");
    setExplorerRoot(".");
    setExplorerMap({});
    setExpandedPaths([]);
    loadExplorerRoot(path, ".");
  };

  const goToJenkinsTab = (tab, anchor) => {
    setPrimaryView("workflow");
    if (tab) setActiveJenkinsTab(tab);
    if (anchor) setJenkinsReportAnchor(anchor);
  };

  const toggleTheme = () => {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  };

  useEffect(() => {
    // bootstrap怨?loadSessions瑜?蹂묐젹濡??ㅽ뻾
    const initApp = async () => {
      try {
        // bootstrap: 3媛쒖쓽 ?낅┰?곸씤 API瑜?蹂묐젹濡??몄텧
        const [defaults, opt, prof] = await Promise.all([
          api("/api/config/defaults"),
          api("/api/config/options"),
          api("/api/profiles"),
        ]);
        setConfig(defaults);
        setOptions(opt || {});
        setProfiles(prof.names || []);
        setSelectedProfile(prof.last_profile || "");
        setProfileName(prof.last_profile || "");
      } catch (e) {
        setMessage(`?ㅼ젙 湲곕낯媛?濡쒕뱶 ?ㅽ뙣: ${e.message}`);
      }
    };

    const loadSessions = async () => {
      try {
        const data = await api("/api/sessions");
        setSessions(data);
        const savedSessionId =
          typeof window !== "undefined"
            ? window.localStorage.getItem(STORAGE_KEYS.SESSION_ID)
            : null;
        if (data.length > 0) {
          const exists =
            savedSessionId && data.some((s) => s.id === savedSessionId);
          const selectedId = exists ? savedSessionId : data[0].id;
          setSessionId(selectedId);

          // ?몄뀡 ?곗씠?곕룄 利됱떆 濡쒕뱶
          try {
            const sessionData = await api(`/api/sessions/${selectedId}/data`);
            setSummary(sessionData.summary || {});
            setFindings(sessionData.findings || []);
            setHistory(sessionData.history || []);
            setStatus(sessionData.status || {});
            const session = data.find((s) => s.id === selectedId);
            setSessionName(session?.name || "");
          } catch (e) {
            // ?몄뀡 ?곗씠??濡쒕뱶 ?ㅽ뙣??臾댁떆 (???몄뀡?닿굅???곗씠?곌? ?놁쓣 ???덉쓬)
          }
        } else {
          // ?몄뀡???놁쑝硫??곗씠??珥덇린??
          setSummary({});
          setFindings([]);
          setHistory([]);
          setStatus({});
          setSessionName("");
        }
      } catch (e) {
        setMessage(`?몄뀡 紐⑸줉 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
      }
    };

    // bootstrap怨?loadSessions瑜?蹂묐젹濡??ㅽ뻾
    Promise.all([initApp(), loadSessions()]).catch(() => {
      // 媛쒕퀎 ?먮윭 泥섎━??媛??⑥닔?먯꽌 ?섑뻾
    });
  }, []);

  // ?몄뀡 ID 蹂寃???localStorage?????(濡쒖뺄 ?ㅼ젙?먯꽌 ?좏깮???몄뀡 ?좎?)
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (sessionId) {
      window.localStorage.setItem(STORAGE_KEYS.SESSION_ID, sessionId);
    } else {
      window.localStorage.removeItem(STORAGE_KEYS.SESSION_ID);
    }
  }, [sessionId]);

  // Jenkins config persistence is now handled by JenkinsConfigContext

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const tab = params.get("tab");
    const tool = params.get("tool");
    const search = params.get("search");
    const detail = params.get("detail");
    if (tab) setActiveTab(tab);
    if (tool) setFilterTool(tool);
    if (search) setSearchTerm(search);
    if (detail) setDetailTab(detail);
  }, []);

  useEffect(() => {
    // 珥덇린 濡쒕뱶 ?쒖뿉??URL ?낅뜲?댄듃 ?ㅽ궢 (遺덊븘?뷀븳 ?묒뾽 ?쒓굅)
    if (isInitialLoad) {
      setIsInitialLoad(false);
      return;
    }
    const params = new URLSearchParams(window.location.search);
    params.set("tab", activeTab);
    if (filterTool) params.set("tool", filterTool);
    if (searchTerm) params.set("search", searchTerm);
    else params.delete("search");
    if (detailTab) params.set("detail", detailTab);
    const url = `${window.location.pathname}?${params.toString()}`;
    window.history.replaceState(null, "", url);
  }, [activeTab, filterTool, searchTerm, detailTab, isInitialLoad]);

  useEffect(() => {
    if (!workflowDragging) return;
    const minLeft = 220;
    const minRight = 240;
    const minCenter = 520;
    const splitterWidth = 6;
    const handleMove = (event) => {
      if (!workflowSplitRef.current) return;
      const rect = workflowSplitRef.current.getBoundingClientRect();
      if (workflowDragging === "left") {
        const maxLeft =
          rect.width - workflowRightWidth - minCenter - splitterWidth * 2;
        const next = Math.max(
          minLeft,
          Math.min(event.clientX - rect.left, Math.max(minLeft, maxLeft))
        );
        setWorkflowLeftWidth(next);
        return;
      }
      if (workflowDragging === "right") {
        const maxRight =
          rect.width - workflowLeftWidth - minCenter - splitterWidth * 2;
        const next = Math.max(
          minRight,
          Math.min(rect.right - event.clientX, Math.max(minRight, maxRight))
        );
        setWorkflowRightWidth(next);
      }
    };
    const handleUp = () => setWorkflowDragging(null);
    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
    return () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };
  }, [workflowDragging, workflowLeftWidth, workflowRightWidth]);

  const refreshSession = useCallback(async () => {
    if (!sessionId) return;
    try {
      const data = await api(`/api/sessions/${sessionId}/data`);
      setSummary(data.summary || {});
      setFindings(data.findings || []);
      setHistory(data.history || []);
      setStatus(data.status || {});
      // ?몄뀡 ?대쫫???낅뜲?댄듃
      if (data.session?.name) {
        setSessionName(data.session.name);
      }
      return data;
    } catch (e) {
      setMessage(`?몄뀡 ?곗씠??濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
    return null;
  }, [sessionId]);

  const refreshLogs = useCallback(async () => {
    if (!sessionId) return;
    try {
      const data = await api(`/api/sessions/${sessionId}/log`);
      setLogs(data.lines || []);
      setLastLogAt(new Date().toLocaleTimeString());
    } catch (e) {
      setMessage(`濡쒓렇 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  }, [sessionId]);

  const refreshExports = useCallback(async () => {
    try {
      const data = await api(
        "/api/exports" + (sessionId ? `?session_id=${sessionId}` : "")
      );
      setExports(data || []);
    } catch (e) {
      setMessage(`諛깆뾽 紐⑸줉 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  }, [sessionId]);

  useEffect(() => {
    if (!config) return;
    setPreflight(null);
    setPreflightError("");
  }, [preflightConfigKey]);

  useEffect(() => {
    if (mode !== "local" || primaryView !== "workflow" || !config) return;
    if (preflight) return;
    loadPreflight(true);
  }, [mode, primaryView, preflightConfigKey]);

  useEffect(() => {
    if (!runMeta.active || !sessionId) return;

    let pollInterval = 3000;
    let consecutiveErrors = 0;
    const maxErrors = 3;

    const poll = async () => {
      try {
        await refreshLogs();
        const data = await refreshSession();
        const state = data?.status?.state;

        // ?깃났 ???먮윭 移댁슫??由ъ뀑
        consecutiveErrors = 0;
        pollInterval = 3000;

        // ?ㅽ뻾???꾨즺?섎㈃ ?대쭅 以묒?
        if (state && state !== "running") {
          setRunMeta((prev) => ({ ...prev, active: false }));
          return false;
        }
        return true;
      } catch (error) {
        consecutiveErrors++;
        // ?먮윭媛 ?곗냽?쇰줈 諛쒖깮?섎㈃ 媛꾧꺽???섎┝
        if (consecutiveErrors >= maxErrors) {
          pollInterval = Math.min(pollInterval * 1.5, 10000);
        }
        // ?먮윭媛 ?덈Т 留롮쑝硫??대쭅 以묒?
        if (consecutiveErrors >= maxErrors * 2) {
          setRunMeta((prev) => ({ ...prev, active: false }));
          return false;
        }
        return true;
      }
    };

    // 利됱떆 ??踰??ㅽ뻾
    let shouldContinue = true;
    poll().then((continuePolling) => {
      shouldContinue = continuePolling;
    });

    const scheduleNext = () => {
      if (!shouldContinue || !runMeta.active) return;
      const timer = setTimeout(async () => {
        const continuePolling = await poll();
        if (continuePolling && runMeta.active) {
          scheduleNext();
        }
      }, pollInterval);
      return () => clearTimeout(timer);
    };

    const cleanup = scheduleNext();
    return () => {
      shouldContinue = false;
      if (cleanup) cleanup();
    };
  }, [runMeta.active, sessionId, refreshLogs, refreshSession]);

  useEffect(() => {
    const state = status?.state;
    if (!state) return;
    if (state === "running" && !runMeta.active) {
      setRunMeta((prev) => ({ ...prev, active: true }));
    }
    if (state !== "running" && runMeta.active) {
      setRunMeta((prev) => ({ ...prev, active: false }));
    }
  }, [status?.state]);

  // sessionId媛 蹂寃쎈릺硫??몄뀡 ?곗씠???먮룞 濡쒕뱶
  useEffect(() => {
    if (!sessionId) {
      // ?몄뀡???놁쑝硫??곗씠??珥덇린??
      setSummary({});
      setFindings([]);
      setHistory([]);
      setStatus({});
      setSessionName("");
      return;
    }
    const loadSessionData = async () => {
      try {
        const data = await api(`/api/sessions/${sessionId}/data`);
        setSummary(data.summary || {});
        setFindings(data.findings || []);
        setHistory(data.history || []);
        setStatus(data.status || {});
        const session = sessions.find((s) => s.id === sessionId);
        setSessionName(session?.name || "");
        // refreshExports瑜?鍮꾨룞湲곕줈 泥섎━?섏뿬 ?몄뀡 ?곗씠??濡쒕뱶 釉붾줈??諛⑹?
        refreshExports().catch(() => {
          // ?먮윭??臾댁떆 (?대? refreshExports ?대??먯꽌 硫붿떆吏 泥섎━)
        });
      } catch (e) {
        setMessage(`?몄뀡 ?곗씠??濡쒕뱶 ?ㅽ뙣: ${e.message}`);
      }
    };
    loadSessionData();
  }, [sessionId, sessions, refreshExports]);

  const loadComplexity = async () => {
    if (!sessionId) return;
    try {
      const data = await api(`/api/sessions/${sessionId}/report/complexity`);
      setComplexityRows(data.rows || []);
    } catch (e) {
      setMessage(`蹂듭옟??濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  };

  const loadKbEntries = useCallback(async () => {
    const projectRoot = config?.project_root || "";
    const reportDir = config?.report_dir || "";
    if (!sessionId || !projectRoot || !reportDir) return;
    if (kbLoadInFlightRef.current) return;
    kbLoadInFlightRef.current = true;
    try {
      const data = await api("/api/local/kb/list", {
        method: "POST",
        body: JSON.stringify({
          project_root: projectRoot,
          report_dir: reportDir,
        }),
      });
      setKbEntries(data.entries || []);
    } catch (e) {
      // 吏?앸쿋?댁뒪媛 ?놁쓣 ?섎룄 ?덉쑝誘濡??먮윭??議곗슜??臾댁떆
    } finally {
      kbLoadInFlightRef.current = false;
    }
  }, [sessionId, config?.project_root, config?.report_dir]);

  const loadDocs = async () => {
    if (!sessionId) return;
    try {
      const data = await api(`/api/sessions/${sessionId}/report/docs`);
      if (data.ok && data.html) {
        const baseHref = `/api/sessions/${sessionId}/report/docs/static/`;
        setDocsHtml(injectBaseHref(data.html, baseHref));
      } else {
        setDocsHtml("");
      }
    } catch (e) {
      setMessage(`臾몄꽌 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  };

  const loadLogList = async () => {
    if (!sessionId) return;
    try {
      const data = await api(`/api/sessions/${sessionId}/report/logs`);
      setLogFiles(data.logs || {});
    } catch (e) {
      setMessage(`濡쒓렇 紐⑸줉 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  };

  const loadSessionReportFiles = async () => {
    if (!sessionId) return;
    try {
      const data = await api(`/api/sessions/${sessionId}/report/files`);
      setSessionReportFiles(data || { files: [], ext_counts: {} });
    } catch (e) {
      setMessage(`由ы룷???뚯씪 紐⑸줉 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  };

  const loadLocalReports = useCallback(async () => {
    const reportDir = currentSession?.path || config?.report_dir || "";
    if (!reportDir) {
      setLocalReports([]);
      return;
    }
    setLocalReportsLoading(true);
    setLocalReportsError("");
    try {
      const data = await api(
        `/api/local/reports?report_dir=${encodeURIComponent(reportDir)}`
      );
      setLocalReports(Array.isArray(data) ? data : []);
    } catch (e) {
      setLocalReports([]);
      setLocalReportsError(`濡쒖뺄 由ы룷??紐⑸줉 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    } finally {
      setLocalReportsLoading(false);
    }
  }, [currentSession, config]);

  const generateLocalReports = useCallback(
    async (formats = ["docx", "xlsx"]) => {
      const reportDir = currentSession?.path || config?.report_dir || "";
      if (!reportDir) {
        setMessage("由ы룷??寃쎈줈媛 ?놁뒿?덈떎.");
        return;
      }
      try {
        const data = await api("/api/local/reports/generate", {
          method: "POST",
          body: JSON.stringify({
            report_dir: reportDir,
            formats,
          }),
        });
        if (data?.ok) {
          setMessage("濡쒖뺄 由ы룷???앹꽦 ?꾨즺");
          loadLocalReports();
        } else {
          setMessage("濡쒖뺄 由ы룷???앹꽦 ?ㅽ뙣");
        }
      } catch (e) {
        setMessage(`濡쒖뺄 由ы룷???앹꽦 ?ㅽ뙣: ${e.message}`);
      }
    },
    [currentSession, config, loadLocalReports]
  );

  const downloadLocalReport = useCallback(
    (filename) => {
      const reportDir = currentSession?.path || config?.report_dir || "";
      if (!filename || !reportDir) return;
      const url = `/api/local/reports/download/${encodeURIComponent(
        filename
      )}?report_dir=${encodeURIComponent(reportDir)}`;
      window.open(url, "_blank");
    },
    [currentSession, config]
  );

  const loadLocalReportSummary = useCallback(async () => {
    if (localReportSummaryInFlightRef.current) return;
    localReportSummaryInFlightRef.current = true;
    try {
      const data = await api("/api/reports/local/summary");
      setLocalReportSummaries(data.reports || []);
      setLocalReportComparisons(data.comparisons || []);
    } catch (e) {
      setMessage(`濡쒖뺄 由ы룷???붿빟 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    } finally {
      localReportSummaryInFlightRef.current = false;
    }
  }, []);

  const downloadSessionReportZip = async (paths = []) => {
    if (!sessionId) return;
    try {
      const res =
        paths.length > 0
          ? await fetch(
              `/api/sessions/${sessionId}/report/files/download/zip/select`,
              {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ paths }),
              }
            )
          : await fetch(`/api/sessions/${sessionId}/report/files/download/zip`);
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const disposition = res.headers.get("content-disposition") || "";
      const match = disposition.match(/filename="?([^"]+)"?/i);
      const filename = match?.[1] || "session_reports.zip";
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      setMessage(`由ы룷??ZIP ?ㅼ슫濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  };

  const readLog = async (path) => {
    if (!sessionId || !path) return;
    try {
      const data = await api(
        `/api/sessions/${sessionId}/report/logs/read?path=${encodeURIComponent(path)}`
      );
      setLogContent(data.text || "");
      setSelectedLogPath(path);
    } catch (e) {
      setMessage(`濡쒓렇 ?쎄린 ?ㅽ뙣: ${e.message}`);
    }
  };

  const requestEditorGuide = async ({
    question,
    filePath,
    startLine,
    endLine,
    excerpt,
  }) => {
    const reportDir = currentSession?.path || config?.report_dir || "";
    const payload = {
      mode: "local",
      question,
      session_id: sessionId || undefined,
      report_dir: reportDir || undefined,
      llm_model: config?.llm_model || undefined,
      oai_config_path: config?.oai_config_path || undefined,
      ui_context: {
        editor: {
          file_path: filePath,
          start_line: startLine,
          end_line: endLine,
          excerpt,
        },
        summary: summary || {},
        status: status || {},
      },
    };
    let finalAnswer = "";
    await postSseJson("/api/chat/stream", payload, {
      onEvent: (event) => {
        if (event?.type === "message") {
          finalAnswer = event.answer || "";
        }
      },
    });
    return finalAnswer;
  };

  const formatCCode = async ({ text, filename }) => {
    const data = await api("/api/local/format-c", {
      method: "POST",
      body: JSON.stringify({
        text,
        filename: filename || "temp.c",
      }),
    });
    return data;
  };

  const runScm = async (action) => {
    if (!config?.project_root) return;
    try {
      const body = {
        mode: scmMode,
        project_root: config.project_root,
        workdir_rel: scmWorkdir,
        action,
        repo_url: scmRepoUrl,
        branch: scmBranch,
        depth: Number(scmDepth || 0),
        revision: scmRevision,
      };
      const data = await api("/api/local/scm", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setScmOutput(data.output || "");
    } catch (e) {
      setMessage(`SCM ?ㅽ뻾 ?ㅽ뙣: ${e.message}`);
    }
  };

  const loadKb = useCallback(async () => {
    const projectRoot = config?.project_root || "";
    const reportDir = config?.report_dir || "";
    if (!projectRoot || !reportDir) return;
    if (kbLoadInFlightRef.current) return;
    kbLoadInFlightRef.current = true;
    try {
      const data = await api("/api/local/kb/list", {
        method: "POST",
        body: JSON.stringify({
          project_root: projectRoot,
          report_dir: reportDir,
        }),
      });
      setKbEntries(data.entries || []);
    } catch (e) {
      setMessage(`吏?앸쿋?댁뒪 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    } finally {
      kbLoadInFlightRef.current = false;
    }
  }, [config?.project_root, config?.report_dir]);

  const deleteKb = async () => {
    if (!kbDeleteKey || !config?.report_dir || !config?.project_root) return;
    const ok = await askConfirm({ title: "吏?앸쿋?댁뒪 ??젣", message: `"${kbDeleteKey}" ??ぉ????젣?섏떆寃좎뒿?덇퉴?`, confirmLabel: "??젣", danger: true });
    if (!ok) return;
    try {
      const data = await api("/api/local/kb/delete", {
        method: "POST",
        body: JSON.stringify({
          project_root: config.project_root,
          report_dir: config.report_dir,
          entry_key: kbDeleteKey,
        }),
      });
      setMessage(data.message || "??젣 ?꾨즺");
      loadKb();
    } catch (e) {
      setMessage(`吏?앸쿋?댁뒪 ??젣 ?ㅽ뙣: ${e.message}`);
    }
  };

  const editorRead = async () => {
    const editorRoot =
      mode === "jenkins" ? jenkinsSourceRoot : config?.project_root;
    if (!editorPath || !editorRoot) return;
    try {
      const data = await api("/api/local/editor/read", {
        method: "POST",
        body: JSON.stringify({
          project_root: editorRoot,
          rel_path: editorPath,
        }),
      });
      if (data.ok) {
        setEditorText(data.text || "");
      } else {
        setMessage("?뚯씪 ?쎄린 ?ㅽ뙣");
      }
    } catch (e) {
      setMessage(`?뚯씪 ?쎄린 ?ㅽ뙣: ${e.message}`);
    }
  };

  const editorReadPath = async (path) => {
    const editorRoot =
      mode === "jenkins" ? jenkinsSourceRoot : config?.project_root;
    if (!path || !editorRoot) return;
    try {
      const data = await api("/api/local/editor/read", {
        method: "POST",
        body: JSON.stringify({
          project_root: editorRoot,
          rel_path: path,
        }),
      });
      if (data.ok) {
        setEditorPath(path);
        setEditorText(data.text || "");
      } else {
        setMessage("?뚯씪 ?쎄린 ?ㅽ뙣");
      }
    } catch (e) {
      setMessage(`?뚯씪 ?쎄린 ?ㅽ뙣: ${e.message}`);
    }
  };

  const editorReadAbsPath = async (path) => {
    if (!path) return;
    try {
      const data = await api("/api/local/editor/read-abs", {
        method: "POST",
        body: JSON.stringify({ path }),
      });
      if (data.ok) {
        setEditorPath(path);
        setEditorText(data.text || "");
      } else {
        setMessage("?뚯씪 ?쎄린 ?ㅽ뙣");
      }
    } catch (e) {
      setMessage(`?뚯씪 ?쎄린 ?ㅽ뙣: ${e.message}`);
    }
  };

  const editorWrite = async () => {
    const editorRoot =
      mode === "jenkins" ? jenkinsSourceRoot : config?.project_root;
    if (!editorPath || !editorRoot) {
      setMessage(
        mode === "jenkins"
          ? "Jenkins ?뚯뒪 猷⑦듃媛 鍮꾩뼱?덉뒿?덈떎."
          : "?꾨줈?앺듃 猷⑦듃媛 鍮꾩뼱?덉뒿?덈떎."
      );
      return;
    }
    try {
      const data = await api("/api/local/editor/write", {
        method: "POST",
        body: JSON.stringify({
          project_root: editorRoot,
          rel_path: editorPath,
          content: editorText,
          make_backup: true,
        }),
      });
      if (data.ok) setMessage("?뚯씪 ????꾨즺");
    } catch (e) {
      setMessage(`?뚯씪 ????ㅽ뙣: ${e.message}`);
    }
  };

  const editorReplace = async () => {
    const editorRoot =
      mode === "jenkins" ? jenkinsSourceRoot : config?.project_root;
    if (!editorPath || !editorRoot) {
      setMessage(
        mode === "jenkins"
          ? "Jenkins ?뚯뒪 猷⑦듃媛 鍮꾩뼱?덉뒿?덈떎."
          : "?꾨줈?앺듃 猷⑦듃媛 鍮꾩뼱?덉뒿?덈떎."
      );
      return;
    }
    try {
      const data = await api("/api/local/editor/replace", {
        method: "POST",
        body: JSON.stringify({
          project_root: editorRoot,
          rel_path: editorPath,
          start_line: Number(editorStartLine),
          end_line: Number(editorEndLine),
          content: editorText,
        }),
      });
      if (data.ok) setMessage("?쇱씤 援먯껜 ?꾨즺");
    } catch (e) {
      setMessage(`?쇱씤 援먯껜 ?ㅽ뙣: ${e.message}`);
    }
  };

  const loadJenkinsJobs = async () => {
    if (!jenkinsBaseUrl) {
      setMessage("Jenkins Base URL???낅젰?댁＜?몄슂.");
      return;
    }
    if (!jenkinsUsername) {
      setMessage("Jenkins Username???낅젰?댁＜?몄슂.");
      return;
    }
    if (!jenkinsToken) {
      setMessage("Jenkins API Token???낅젰?댁＜?몄슂.");
      return;
    }
    try {
      setJenkinsJobsLoading(true);
      setMessage("Jenkins ?꾨줈?앺듃 紐⑸줉??遺덈윭?ㅻ뒗 以?..");

      const base_url = String(jenkinsBaseUrl || "").trim();
      const username = String(jenkinsUsername || "").trim();
      const api_token = String(jenkinsToken || "").trim();

      if (!api_token) {
        setJenkinsJobsLoading(false);
        setMessage(
          "Jenkins API Token??鍮꾩뼱 ?덉뒿?덈떎. ?좏겙???ㅼ떆 ?낅젰?댁＜?몄슂."
        );
        return;
      }

      const payload = {
        base_url,
        username,
        api_token,
        recursive: true,
        max_depth: 2,
        verify_tls: !!jenkinsVerifyTls,
      };
      devLog("Jenkins ?꾨줈?앺듃 濡쒕뱶 ?붿껌:", {
        base_url,
        username,
        api_token_len: api_token.length,
        verify_tls: payload.verify_tls,
      });

      const data = await api("/api/jenkins/jobs", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      // 諛깆뿏?쒕뒗 {"jobs": [{"name": "...", "url": "...", ...}]} ?뺥깭濡?諛섑솚
      const rawJobs = data.jobs || [];
      devLog("Jenkins ?꾨줈?앺듃 濡쒕뱶 ?깃났 - ?먮낯 ?곗씠??", {
        count: rawJobs.length,
        sample: rawJobs[0],
        allKeys: rawJobs[0] ? Object.keys(rawJobs[0]) : [],
      });

      // ?먮낯 ?곗씠?곕? 洹몃?濡??ъ슜 (諛깆뿏?쒓? ?대? ?щ컮瑜??뺤떇?쇰줈 諛섑솚)
      const jobs = Array.isArray(rawJobs) ? rawJobs : [];
      setJenkinsJobs(jobs);
      if (jobs.length === 0) {
        setMessage("Jenkins ?꾨줈?앺듃瑜?李얠쓣 ???놁뒿?덈떎.");
      } else {
        setMessage(
          `Jenkins ?꾨줈?앺듃 ${jobs.length}媛쒕? 遺덈윭?붿뒿?덈떎. Job URL?먯꽌 ?좏깮?섏꽭??`
        );
      }
    } catch (e) {
      devErr("Jenkins ?꾨줈?앺듃 濡쒕뱶 ?ㅻ쪟 ?곸꽭:", {
        error: e,
        name: e.name,
        message: e.message,
        stack: e.stack,
      });

      const errorMsg = e.message || String(e) || "?????녿뒗 ?ㅻ쪟";
      let userMessage = "";

      if (
        e.name === "AbortError" ||
        errorMsg.includes("timeout") ||
        errorMsg.includes("aborted")
      ) {
        userMessage =
          "?붿껌??以묐떒?섏뿀?듬땲?? ?섏씠吏瑜??덈줈 怨좎튇 ???ㅼ떆 ?쒕룄?섍굅?? Jenkins URL쨌?ㅽ듃?뚰겕瑜??뺤씤?댁＜?몄슂.";
      } else if (
        errorMsg.includes("401") ||
        errorMsg.includes("Unauthorized")
      ) {
        userMessage = "?몄쬆 ?ㅽ뙣: Username ?먮뒗 API Token???щ컮瑜댁? ?딆뒿?덈떎.";
      } else if (errorMsg.includes("403") || errorMsg.includes("Forbidden")) {
        userMessage =
          "?묎렐 嫄곕?: ?대떦 怨꾩젙??Jenkins ?꾨줈?앺듃 紐⑸줉 議고쉶 沅뚰븳???놁뒿?덈떎.";
      } else if (errorMsg.includes("404") || errorMsg.includes("Not Found")) {
        userMessage =
          "Jenkins URL??李얠쓣 ???놁뒿?덈떎. Base URL???щ컮瑜몄? ?뺤씤?댁＜?몄슂.";
      } else if (
        errorMsg.includes("ECONNREFUSED") ||
        errorMsg.includes("NetworkError")
      ) {
        userMessage =
          "?ㅽ듃?뚰겕 ?곌껐 ?ㅽ뙣: Jenkins ?쒕쾭???곌껐?????놁뒿?덈떎. URL怨??ы듃瑜??뺤씤?댁＜?몄슂.";
      } else if (
        errorMsg.includes("CORS") ||
        errorMsg.includes("CORS policy")
      ) {
        userMessage = "CORS ?ㅻ쪟: Jenkins ?쒕쾭??CORS ?ㅼ젙???뺤씤?댁＜?몄슂.";
      } else if (errorMsg.includes("SSL") || errorMsg.includes("certificate")) {
        userMessage =
          "SSL ?몄쬆???ㅻ쪟: Verify TLS ?듭뀡???댁젣?섍굅???몄쬆?쒕? ?뺤씤?댁＜?몄슂.";
      } else {
        // 諛깆뿏?쒖뿉??諛섑솚???곸꽭 ?먮윭 硫붿떆吏 ?쒖떆
        const detailMatch = errorMsg.match(
          /Jenkins ?꾨줈?앺듃 紐⑸줉 議고쉶 ?ㅽ뙣: (.+)/
        );
        if (detailMatch) {
          userMessage = `Jenkins ?꾨줈?앺듃 濡쒕뱶 ?ㅽ뙣: ${detailMatch[1]}`;
        } else {
          userMessage = `Jenkins ?꾨줈?앺듃 濡쒕뱶 ?ㅽ뙣: ${errorMsg}`;
        }
      }

      setMessage(userMessage);
      setJenkinsJobs([]); // ?먮윭 ??鍮?諛곗뿴濡?珥덇린??
    } finally {
      setJenkinsJobsLoading(false);
    }
  };

  const [jenkinsBuildsLoading, setJenkinsBuildsLoading] = useState(false);
  const [jenkinsSyncFastMode, setJenkinsSyncFastMode] = useState(false);
  const [jenkinsSyncLoading, setJenkinsSyncLoading] = useState(false);
  const [jenkinsPublishLoading, setJenkinsPublishLoading] = useState(false);
  const [jenkinsProgress, setJenkinsProgress] = useState({
    sync: null,
    publish: null,
    uds: null,
  });
  const [jenkinsOpsQueue, setJenkinsOpsQueue] = useState([]);
  const jenkinsOpsIndexRef = useRef({ sync: null, publish: null, uds: null });
  const jenkinsProgressTimerRef = useRef({
    sync: null,
    publish: null,
    uds: null,
  });
  const udsAbortRef = useRef(null);
  const [jenkinsProgressJobIds, setJenkinsProgressJobIds] = useState({
    sync: "",
    publish: "",
    uds: "",
  });
  const jenkinsProgressHandledRef = useRef({ sync: "", publish: "", uds: "" });
  const [jenkinsLastSyncDoneId, setJenkinsLastSyncDoneId] = useState("");

  const loadJenkinsBuilds = async () => {
    const job_url = String(jenkinsJobUrl || "").trim();
    const username = String(jenkinsUsername || "").trim();
    const api_token = String(jenkinsToken || "").trim();
    if (!job_url) {
      setMessage("Job URL??癒쇱? ?좏깮?댁＜?몄슂.");
      return;
    }
    if (!username || !api_token) {
      setMessage("Username怨?API Token???낅젰?댁＜?몄슂.");
      return;
    }
    try {
      setJenkinsBuildsLoading(true);
      setMessage("Jenkins 鍮뚮뱶 紐⑸줉??遺덈윭?ㅻ뒗 以?..");
      const data = await api("/api/jenkins/builds", {
        method: "POST",
        body: JSON.stringify({
          job_url,
          username,
          api_token,
          limit: 30,
          verify_tls: !!jenkinsVerifyTls,
        }),
      });
      const builds = Array.isArray(data.builds) ? data.builds : [];
      setJenkinsBuilds(builds);
      if (builds.length === 0) {
        setMessage("?대떦 Job??鍮뚮뱶媛 ?놁뒿?덈떎.");
      } else {
        setMessage(`Jenkins 鍮뚮뱶 ${builds.length}媛쒕? 遺덈윭?붿뒿?덈떎.`);
      }
    } catch (e) {
      setMessage(`Jenkins 鍮뚮뱶 濡쒕뱶 ?ㅽ뙣: ${e.message || String(e)}`);
      setJenkinsBuilds([]);
    } finally {
      setJenkinsBuildsLoading(false);
    }
  };

  const loadJenkinsReportFiles = useCallback(async () => {
    if (!jenkinsJobUrl) return;
    try {
      const data = await api("/api/jenkins/report/files", {
        method: "POST",
        body: JSON.stringify({
          job_url: jenkinsJobUrl,
          cache_root: jenkinsCacheRoot,
          build_selector: jenkinsBuildSelector,
        }),
      });
      setJenkinsReportFiles(data || { files: [], ext_counts: {} });
    } catch (e) {
      setMessage(`Jenkins 由ы룷???뚯씪 紐⑸줉 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  }, [jenkinsJobUrl, jenkinsCacheRoot, jenkinsBuildSelector]);

  const loadJenkinsServerFiles = useCallback(
    async (root, relPath = "") => {
      const targetRoot = root || jenkinsServerRoot;
      const targetRel = relPath || jenkinsServerRelPath || "";
      if (!targetRoot) {
        setJenkinsServerFilesError("?쒕쾭 猷⑦듃媛 鍮꾩뼱 ?덉뒿?덈떎.");
        return;
      }
      setJenkinsServerFilesLoading(true);
      setJenkinsServerFilesError("");
      try {
        const data = await api("/api/jenkins/server/files", {
          method: "POST",
          body: JSON.stringify({
            root: targetRoot,
            rel_path: targetRel,
            exts: [],
            max_files: 8000,
          }),
        });
        setJenkinsServerFiles(Array.isArray(data?.files) ? data.files : []);
      } catch (e) {
        setJenkinsServerFiles([]);
        const raw = e?.message || String(e);
        const hint =
          raw.includes("HTTP 404") || raw.toLowerCase().includes("not found")
            ? "?쒕쾭 ?뚯씪 ?ㅼ틪 API瑜?李얠? 紐삵뻽?듬땲?? 諛깆뿏?쒕? ?ъ떆?묓빐 二쇱꽭??"
            : raw;
        setJenkinsServerFilesError(
          `?쒕쾭 ?뚯씪 ?ㅼ틪 ?ㅽ뙣: ${hint} (root=${targetRoot}, rel=${targetRel || "."})`
        );
      } finally {
        setJenkinsServerFilesLoading(false);
      }
    },
    [jenkinsServerRoot, jenkinsServerRelPath]
  );

  const loadJenkinsReportSummary = useCallback(async () => {
    if (!jenkinsJobUrl) return;
    try {
      const data = await api("/api/jenkins/report/summary", {
        method: "POST",
        body: JSON.stringify({
          job_url: jenkinsJobUrl,
          cache_root: jenkinsCacheRoot,
          build_selector: jenkinsBuildSelector,
        }),
      });
      setJenkinsReportSummary(data || null);
    } catch (e) {
      setMessage(`Jenkins ?붿빟 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  }, [jenkinsJobUrl, jenkinsCacheRoot, jenkinsBuildSelector]);

  const loadJenkinsSourceRoot = useCallback(async () => {
    const job_url = String(jenkinsJobUrl || "").trim();
    const cache_root = String(jenkinsCacheRoot || "").trim();
    const build_selector = String(
      jenkinsBuildSelector || "lastSuccessfulBuild"
    ).trim();
    if (!job_url) {
      setMessage("Job URL??癒쇱? ?좏깮?댁＜?몄슂.");
      return;
    }
    try {
      setMessage("소스 루트 탐색 중...");
      const data = await api("/api/jenkins/source-root", {
        method: "POST",
        body: JSON.stringify({
          job_url,
          cache_root: cache_root || "",
          build_selector,
        }),
      });
      devLog("[jenkins] source-root candidates:", data);
      const candidates = Array.isArray(data.candidates) ? data.candidates : [];
      setJenkinsSourceCandidates(candidates);
      if (candidates.length > 0) {
        setJenkinsSourceRootRemote(String(candidates[0].path || ""));
      } else if (data.root) {
        setJenkinsSourceRootRemote(String(data.root));
      } else {
        setJenkinsSourceRootRemote("");
      }
      if (candidates.length > 0) {
        const best = candidates.reduce(
          (acc, item) => (item.score > acc.score ? item : acc),
          candidates[0]
        );
        const hasCurrent = candidates.some(
          (item) => item.path === jenkinsSourceRoot
        );
        if (autoSelectJenkinsSource && !hasCurrent) {
          setJenkinsSourceRoot(best.path || data.root || "");
        }
        setMessage(`소스 루트 후보 ${candidates.length}개를 불러왔습니다.`);
      } else if (data.root) {
        if (autoSelectJenkinsSource && !jenkinsSourceRoot) {
          setJenkinsSourceRoot(data.root || "");
        }
        setMessage("소스 루트 후보를 불러왔습니다.");
      } else {
        setMessage(
          "?숆린?붾? 癒쇱? ?ㅽ뻾?????ㅼ떆 ?쒕룄?댁＜?몄슂. (罹먯떆??鍮뚮뱶 ?꾩슂)"
        );
      }
    } catch (e) {
      const msg = e.message || String(e);
      if (msg.includes("cached build not found") || msg.includes("404")) {
        setMessage("캐시된 빌드가 없습니다. 먼저 동기화를 실행해 주세요.");
      } else {
        setMessage(`Jenkins ?뚯뒪 猷⑦듃 濡쒕뱶 ?ㅽ뙣: ${msg}`);
      }
    }
  }, [
    jenkinsJobUrl,
    jenkinsCacheRoot,
    jenkinsBuildSelector,
    autoSelectJenkinsSource,
    jenkinsSourceRoot,
  ]);

  const downloadJenkinsSourceRoot = useCallback(
    async (sourceRoot) => {
      const job_url = String(jenkinsJobUrl || "").trim();
      const username = String(jenkinsUsername || "").trim();
      const api_token = String(jenkinsToken || "").trim();
      const cache_root = String(jenkinsCacheRoot || "").trim();
      const build_selector = String(
        jenkinsBuildSelector || "lastSuccessfulBuild"
      ).trim();
      if (!job_url) {
        setMessage("Job URL??癒쇱? ?좏깮?댁＜?몄슂.");
        return;
      }
      if (!username || !api_token) {
        setMessage("Username怨?API Token???낅젰?댁＜?몄슂.");
        return;
      }
      try {
        setMessage("?뚯뒪 ?ㅼ슫濡쒕뱶 以?..");
        setJenkinsSourceDownload({
          loading: true,
          ok: null,
          message: "?뚯뒪 ?ㅼ슫濡쒕뱶 以?..",
          path: "",
        });
        setJenkinsSourceRootRemote(sourceRoot || "");
        devLog("[jenkins] source download request:", {
          job_url,
          cache_root: cache_root || "",
          build_selector,
          source_root: sourceRoot || "",
        });
        const data = await api("/api/jenkins/source-root/download", {
          method: "POST",
          body: JSON.stringify({
            job_url,
            username,
            api_token,
            cache_root: cache_root || "",
            build_selector,
            verify_tls: !!jenkinsVerifyTls,
            source_root: sourceRoot || "",
            scm_type: jenkinsScmType,
            scm_url: jenkinsScmUrl,
            scm_username: jenkinsScmUsername,
            scm_password: jenkinsScmPassword,
            scm_branch: jenkinsScmBranch,
            scm_revision: jenkinsScmRevision,
          }),
        });
        const nextPath = data?.path || "";
        devLog("[jenkins] source download response:", data);
        if (data?.ok === false) {
          console.warn("[jenkins] source download failed:", data);
          const artifactNote = data?.artifact?.path
            ? ` 쨌 ?꾪떚?⑺듃 ??? ${data.artifact.path}`
            : data?.artifact?.error
              ? ` 쨌 ?꾪떚?⑺듃 ?ㅻ쪟: ${data.artifact.error}`
              : "";
          setMessage(
            `?뚯뒪 ?ㅼ슫濡쒕뱶 ?ㅽ뙣: ${data.error || "source_dir_missing"} (scm=${data.scm || "-"})${artifactNote}`
          );
          setJenkinsSourceDownload({
            loading: false,
            ok: false,
            message: `?뚯뒪 ?ㅼ슫濡쒕뱶 ?ㅽ뙣: ${data.error || "source_dir_missing"}`,
            path: "",
          });
          if (data.checkout_error || data.checkout_output) {
            devErr("[jenkins] scm checkout error:", {
              error: data.checkout_error,
              output: data.checkout_output,
              repo_url: data.repo_url,
              branch: data.branch,
              revision: data.revision,
            });
          }
          return;
        }
        if (nextPath) {
          handleJenkinsSourceSelect(nextPath);
          devLog("[jenkins] source root set to:", nextPath);
          setMessage(`?뚯뒪 ?ㅼ슫濡쒕뱶 ?꾨즺: ${nextPath}`);
          setJenkinsSourceDownload({
            loading: false,
            ok: true,
            message: "?뚯뒪 ?ㅼ슫濡쒕뱶 ?꾨즺",
            path: nextPath,
          });
        } else {
          setMessage("?뚯뒪 ?ㅼ슫濡쒕뱶 ?ㅽ뙣: 寃쎈줈 ?놁쓬");
          setJenkinsSourceDownload({
            loading: false,
            ok: false,
            message: "?뚯뒪 ?ㅼ슫濡쒕뱶 ?ㅽ뙣: 寃쎈줈 ?놁쓬",
            path: "",
          });
        }
      } catch (e) {
        setMessage(`?뚯뒪 ?ㅼ슫濡쒕뱶 ?ㅽ뙣: ${e.message || String(e)}`);
        setJenkinsSourceDownload({
          loading: false,
          ok: false,
          message: `?뚯뒪 ?ㅼ슫濡쒕뱶 ?ㅽ뙣: ${e.message || String(e)}`,
          path: "",
        });
      }
    },
    [
      jenkinsJobUrl,
      jenkinsUsername,
      jenkinsToken,
      jenkinsCacheRoot,
      jenkinsBuildSelector,
      jenkinsVerifyTls,
      jenkinsSourceRootRemote,
      handleJenkinsSourceSelect,
      jenkinsScmType,
      jenkinsScmUrl,
      jenkinsScmUsername,
      jenkinsScmPassword,
      jenkinsScmBranch,
      jenkinsScmRevision,
    ]
  );

  const uploadUdsTemplate = useCallback(
    async (file) => {
      const job_url = String(jenkinsJobUrl || "").trim();
      const cache_root = String(jenkinsCacheRoot || "").trim();
      const build_selector = String(
        jenkinsBuildSelector || "lastSuccessfulBuild"
      ).trim();
      if (!job_url) {
        setMessage("Job URL??癒쇱? ?좏깮?댁＜?몄슂.");
        return;
      }
      if (!file) {
        setMessage("?쒗뵆由??뚯씪???좏깮?댁＜?몄슂.");
        return;
      }
      setUdsUploading(true);
      try {
        const form = new FormData();
        form.append("job_url", job_url);
        form.append("cache_root", cache_root || "");
        form.append("build_selector", build_selector);
        form.append("file", file);
        const res = await fetch("/api/jenkins/uds/template-upload", {
          method: "POST",
          body: form,
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const data = await res.json();
        setUdsTemplatePath(data?.template_path || "");
        setMessage("UDS ?쒗뵆由??낅줈???꾨즺");
      } catch (e) {
        setMessage(`UDS ?쒗뵆由??낅줈???ㅽ뙣: ${e.message || String(e)}`);
      } finally {
        setUdsUploading(false);
      }
    },
    [jenkinsJobUrl, jenkinsCacheRoot, jenkinsBuildSelector]
  );

  const publishUdsToDocs = useCallback(
    async (filename) => {
      const job_url = String(jenkinsJobUrl || "").trim();
      const cache_root = String(jenkinsCacheRoot || "").trim();
      if (!job_url || !filename) return;
      try {
        const res = await fetch("/api/jenkins/uds/publish", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job_url,
            cache_root,
            filename,
            target_dir: "docs",
          }),
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        await res.json();
        setMessage("UDS ?앹꽦蹂몄쓣 docs ?대뜑??蹂듭궗?덉뒿?덈떎.");
      } catch (e) {
        setMessage(`UDS docs 蹂듭궗 ?ㅽ뙣: ${e.message || String(e)}`);
      }
    },
    [jenkinsJobUrl, jenkinsCacheRoot]
  );

  const loadUdsVersions = useCallback(async () => {
    const job_url = String(jenkinsJobUrl || "").trim();
    const cache_root = String(jenkinsCacheRoot || "").trim();
    if (!job_url) return;
    try {
      const data = await api(
        `/api/jenkins/uds/list?job_url=${encodeURIComponent(job_url)}&cache_root=${encodeURIComponent(cache_root)}`
      );
      setUdsVersions(Array.isArray(data?.items) ? data.items : []);
      setUdsPlaceholders(
        Array.isArray(data?.placeholders) ? data.placeholders : []
      );
    } catch (e) {
      setMessage(`UDS 踰꾩쟾 紐⑸줉 濡쒕뱶 ?ㅽ뙣: ${e.message || String(e)}`);
    }
  }, [jenkinsJobUrl, jenkinsCacheRoot]);

  const loadUdsPreview = useCallback(async (previewUrl) => {
    if (!previewUrl) {
      setUdsPreviewHtml("");
      return;
    }
    try {
      const res = await fetch(previewUrl);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setUdsPreviewHtml(String(data?.html || ""));
    } catch (e) {
      setMessage(`UDS 誘몃━蹂닿린 濡쒕뱶 ?ㅽ뙣: ${e.message || String(e)}`);
    }
  }, []);

  const previewUdsRequirements = useCallback(
    async (reqFiles, reqPaths, sourceRoot, traceMapFiles, traceMapPaths) => {
      const hasFiles = Array.isArray(reqFiles) && reqFiles.length > 0;
      const hasPaths = Array.isArray(reqPaths) && reqPaths.length > 0;
      if (!hasFiles && !hasPaths) {
        setMessage("?붽뎄?ы빆 臾몄꽌瑜??좏깮?댁＜?몄슂.");
        return;
      }
      try {
        const form = new FormData();
        if (Array.isArray(reqFiles)) {
          reqFiles.forEach((f) => {
            if (f) form.append("req_files", f);
          });
        }
        if (Array.isArray(reqPaths) && reqPaths.length > 0) {
          form.append("req_paths", JSON.stringify(reqPaths));
        }
        if (sourceRoot) {
          form.append("source_root", String(sourceRoot));
        }
        if (Array.isArray(traceMapFiles)) {
          traceMapFiles.forEach((f) => {
            if (f) form.append("trace_map_files", f);
          });
        }
        if (Array.isArray(traceMapPaths) && traceMapPaths.length > 0) {
          form.append("trace_map_paths", JSON.stringify(traceMapPaths));
        }
        const res = await fetch("/api/jenkins/uds/requirements-preview", {
          method: "POST",
          body: form,
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const data = await res.json();
        setUdsReqPreview(data?.preview || null);
        setUdsReqMapping(Array.isArray(data?.mapping) ? data.mapping : []);
        setUdsReqCompare(data?.compare || null);
        setUdsReqFunctionMapping(data?.function_mapping || null);
        setUdsReqTraceability(data?.traceability || null);
        try {
          const matrixPayload = {
            requirement_items: data?.preview?.items || [],
            mapping_pairs: data?.traceability?.mapping_pairs || [],
            vcast_rows: jenkinsVcastRag?.test_rows || [],
          };
          const matrixRes = await api("/api/jenkins/uds/traceability-matrix", {
            method: "POST",
            body: JSON.stringify(matrixPayload),
          });
          setUdsReqTraceMatrix(matrixRes?.matrix || null);
        } catch (_) {
          setUdsReqTraceMatrix(null);
        }
        setMessage("?붽뎄?ы빆 異붿텧 誘몃━蹂닿린 ?꾨즺");
      } catch (e) {
        setMessage(`?붽뎄?ы빆 誘몃━蹂닿린 ?ㅽ뙣: ${e.message || String(e)}`);
      }
    },
    [jenkinsVcastRag]
  );

  const checkRagStatus = useCallback(async () => {
    try {
      const data = await api("/api/local/rag/status", {
        method: "POST",
        body: JSON.stringify({
          config: config || {},
          report_dir: config?.report_dir || "",
        }),
      });
      setRagStatus(data || null);
      setMessage("RAG ?곹깭瑜??뺤씤?덉뒿?덈떎.");
    } catch (e) {
      setMessage(`RAG ?곹깭 ?뺤씤 ?ㅽ뙣: ${e.message || String(e)}`);
    }
  }, [config]);

  const runRagIngest = useCallback(async () => {
    try {
      const data = await api("/api/local/rag/ingest", {
        method: "POST",
        body: JSON.stringify({
          config: config || {},
          report_dir: config?.report_dir || "",
        }),
      });
      setRagIngestResult(data?.result || null);
      setMessage("RAG ?몄젣?ㅽ듃 ?꾨즺");
    } catch (e) {
      setMessage(`RAG ?몄젣?ㅽ듃 ?ㅽ뙣: ${e.message || String(e)}`);
    }
  }, [config]);

  const runRagIngestFiles = useCallback(
    async (files, category, tags, options = {}) => {
      const hasFiles = Array.isArray(files) && files.length > 0;
      if (!hasFiles) {
        setMessage("RAG ?몄젣?ㅽ듃 ?뚯씪???좏깮?댁＜?몄슂.");
        return;
      }
      try {
        const form = new FormData();
        files.forEach((f) => {
          if (f) form.append("files", f);
        });
        form.append("category", String(category || "general"));
        form.append("tags", String(tags || ""));
        form.append("report_dir", String(config?.report_dir || ""));
        if (options?.chunk_size)
          form.append("chunk_size", String(options.chunk_size));
        if (options?.chunk_overlap)
          form.append("chunk_overlap", String(options.chunk_overlap));
        if (options?.max_chunks)
          form.append("max_chunks", String(options.max_chunks));
        const res = await fetch("/api/local/rag/ingest-files", {
          method: "POST",
          body: form,
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const data = await res.json();
        setRagIngestResult(data || null);
        setMessage(`RAG 파일 인제스트 완료 (추가 ${data?.added || 0}건)`);
        return data;
      } catch (e) {
        setMessage(`RAG ?뚯씪 ?몄젣?ㅽ듃 ?ㅽ뙣: ${e.message || String(e)}`);
        return null;
      }
    },
    [config]
  );

  const generateLocalUds = useCallback(
    async ({
      sourceRoot,
      reqFiles,
      reqTypes,
      templateFile,
      componentList,
      aiEnabled,
      aiDetailed,
      expand,
      ragTopK,
      ragCategories,
    }) => {
      try {
        const form = new FormData();
        if (sourceRoot) form.append("source_root", String(sourceRoot));
        if (Array.isArray(reqFiles)) {
          reqFiles.forEach((f) => {
            if (f) form.append("req_files", f);
          });
        }
        if (Array.isArray(reqTypes) && reqTypes.length > 0) {
          form.append("req_types", reqTypes.join(","));
        }
        if (templateFile) {
          form.append("template_file", templateFile);
        }
        if (componentList) {
          form.append("component_list", componentList);
        }
        if (aiEnabled) form.append("ai_enable", "true");
        if (aiDetailed != null)
          form.append("ai_detailed", aiDetailed ? "true" : "false");
        if (expand) form.append("expand", "true");
        if (ragTopK) form.append("rag_top_k", String(ragTopK));
        if (ragCategories) form.append("rag_categories", String(ragCategories));
        if (config?.report_dir) {
          form.append("report_dir", String(config.report_dir));
        }
        const res = await fetch("/api/local/uds/generate", {
          method: "POST",
          body: form,
        });
        if (!res.ok) {
          let errMsg = `HTTP ${res.status}`;
          try {
            const body = await res.json();
            errMsg = body?.detail || body?.message || JSON.stringify(body);
          } catch {
            const text = await res.text();
            errMsg = text || errMsg;
          }
          throw new Error(errMsg);
        }
        return await res.json();
      } catch (e) {
        setMessage(`濡쒖뺄 UDS ?앹꽦 ?ㅽ뙣: ${e.message || String(e)}`);
        return null;
      }
    },
    [config?.report_dir]
  );

  const generateLocalSts = useCallback(
    async ({ sourceRoot, srsPath, sdsPath, hsisPath, udsPath, stpPath, templatePath, projectId, version, asilLevel, maxTc }) => {
      try {
        const form = new FormData();
        if (sourceRoot) form.append("source_root", String(sourceRoot));
        if (srsPath) form.append("srs_path", String(srsPath));
        if (sdsPath) form.append("sds_path", String(sdsPath));
        if (hsisPath) form.append("hsis_path", String(hsisPath));
        if (udsPath) form.append("uds_path", String(udsPath));
        if (stpPath) form.append("stp_path", String(stpPath));
        if (templatePath) form.append("template_path", String(templatePath));
        if (projectId) form.append("project_id", String(projectId));
        if (version) form.append("version", String(version));
        if (asilLevel) form.append("asil_level", String(asilLevel));
        if (maxTc) form.append("max_tc_per_req", String(maxTc));
        if (config?.report_dir) form.append("report_dir", String(config.report_dir));
        const res = await fetch("/api/local/sts/generate", { method: "POST", body: form });
        if (!res.ok) {
          let errMsg = `HTTP ${res.status}`;
          try { const body = await res.json(); errMsg = body?.detail || body?.message || JSON.stringify(body); } catch { errMsg = (await res.text()) || errMsg; }
          throw new Error(errMsg);
        }
        return await res.json();
      } catch (e) {
        setMessage(`STS 생성 실패: ${e.message || String(e)}`);
        return null;
      }
    },
    [config?.report_dir]
  );

  const generateLocalSuts = useCallback(
    async ({ sourceRoot, srsPath, sdsPath, hsisPath, udsPath, templatePath, projectId, version, asilLevel, maxSeq }) => {
      try {
        const form = new FormData();
        if (sourceRoot) form.append("source_root", String(sourceRoot));
        if (srsPath) form.append("srs_path", String(srsPath));
        if (sdsPath) form.append("sds_path", String(sdsPath));
        if (hsisPath) form.append("hsis_path", String(hsisPath));
        if (udsPath) form.append("uds_path", String(udsPath));
        if (templatePath) form.append("template_path", String(templatePath));
        if (projectId) form.append("project_id", String(projectId));
        if (version) form.append("version", String(version));
        if (asilLevel) form.append("asil_level", String(asilLevel));
        if (maxSeq) form.append("max_sequences", String(maxSeq));
        if (config?.report_dir) form.append("report_dir", String(config.report_dir));
        const res = await fetch("/api/local/suts/generate", { method: "POST", body: form });
        if (!res.ok) {
          let errMsg = `HTTP ${res.status}`;
          try { const body = await res.json(); errMsg = body?.detail || body?.message || JSON.stringify(body); } catch { errMsg = (await res.text()) || errMsg; }
          throw new Error(errMsg);
        }
        return await res.json();
      } catch (e) {
        setMessage(`SUTS 생성 실패: ${e.message || String(e)}`);
        return null;
      }
    },
    [config?.report_dir]
  );

  const switchRagToPgvector = useCallback(async () => {
    try {
      const data = await api("/api/local/rag/use-pgvector", {
        method: "POST",
        body: JSON.stringify({
          storage: "pgvector",
          pgvector_dsn: config?.pgvector_dsn || "",
          pgvector_url: config?.pgvector_url || "",
          report_dir: config?.report_dir || "",
        }),
      });
      setRagStatus((prev) => ({ ...(prev || {}), ...data }));
      if (data?.pgvector_ready) {
        setMessage("PGVector濡??꾪솚 ?꾨즺");
      } else {
        setMessage("PGVector ?꾪솚 ?ㅽ뙣: ?곌껐 ?곹깭瑜??뺤씤?섏꽭??");
      }
    } catch (e) {
      setMessage(`PGVector ?꾪솚 ?ㅽ뙣: ${e.message || String(e)}`);
    }
  }, [config]);

  const runLocalRagQuery = useCallback(async () => {
    const query = String(localRagQuery || "").trim();
    if (!query) {
      setMessage("RAG 寃?됱뼱瑜??낅젰?댁＜?몄슂.");
      return;
    }
    setLocalRagLoading(true);
    try {
      const data = await api("/api/local/rag/query", {
        method: "POST",
        body: JSON.stringify({
          query,
          top_k: 5,
          categories: localRagCategory === "all" ? [] : [localRagCategory],
          config: config || {},
          report_dir: config?.report_dir || "",
        }),
      });
      setLocalRagResults(Array.isArray(data?.items) ? data.items : []);
    } catch (e) {
      setMessage(`RAG 寃???ㅽ뙣: ${e.message || String(e)}`);
    } finally {
      setLocalRagLoading(false);
    }
  }, [localRagQuery, localRagCategory, config]);

  const runJenkinsRagQuery = useCallback(async () => {
    const query = String(jenkinsRagQuery || "").trim();
    if (!query) {
      setMessage("RAG 寃?됱뼱瑜??낅젰?댁＜?몄슂.");
      return;
    }
    if (!jenkinsJobUrl) {
      setMessage("Job URL??癒쇱? ?좏깮?댁＜?몄슂.");
      return;
    }
    setJenkinsRagLoading(true);
    try {
      const data = await api("/api/jenkins/rag/query", {
        method: "POST",
        body: JSON.stringify({
          job_url: jenkinsJobUrl,
          cache_root: jenkinsCacheRoot || "",
          build_selector: jenkinsBuildSelector || "lastSuccessfulBuild",
          query,
          top_k: 5,
          categories: jenkinsRagCategory === "all" ? [] : [jenkinsRagCategory],
        }),
      });
      setJenkinsRagResults(Array.isArray(data?.items) ? data.items : []);
    } catch (e) {
      setMessage(`RAG 寃???ㅽ뙣: ${e.message || String(e)}`);
    } finally {
      setJenkinsRagLoading(false);
    }
  }, [
    jenkinsJobUrl,
    jenkinsCacheRoot,
    jenkinsBuildSelector,
    jenkinsRagQuery,
    jenkinsRagCategory,
  ]);

  const loadUdsDiff = useCallback(
    async (filenameA, filenameB) => {
      const job_url = String(jenkinsJobUrl || "").trim();
      const cache_root = String(jenkinsCacheRoot || "").trim();
      if (!job_url || !filenameA || !filenameB) return;
      try {
        const res = await fetch("/api/jenkins/uds/diff", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job_url,
            cache_root,
            filename_a: filenameA,
            filename_b: filenameB,
          }),
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const data = await res.json();
        setUdsDiff(data?.diff || null);
        setMessage("UDS 踰꾩쟾 diff ?꾨즺");
      } catch (e) {
        setMessage(`UDS diff ?ㅽ뙣: ${e.message || String(e)}`);
      }
    },
    [jenkinsJobUrl, jenkinsCacheRoot]
  );

  const updateUdsLabel = useCallback(
    async (filename, label) => {
      const job_url = String(jenkinsJobUrl || "").trim();
      const cache_root = String(jenkinsCacheRoot || "").trim();
      if (!job_url || !filename) return;
      try {
        const res = await fetch("/api/jenkins/uds/label", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job_url,
            cache_root,
            filename,
            label: String(label || ""),
          }),
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const data = await res.json();
        setUdsVersions((prev) =>
          prev.map((item) =>
            item.filename === filename
              ? { ...item, label: data?.label ?? label ?? "" }
              : item
          )
        );
        setMessage("UDS ?쇰꺼 ????꾨즺");
      } catch (e) {
        setMessage(`UDS ?쇰꺼 ????ㅽ뙣: ${e.message || String(e)}`);
      }
    },
    [jenkinsJobUrl, jenkinsCacheRoot]
  );

  const updateUdsLabelDraft = useCallback((filename, label) => {
    if (!filename) return;
    setUdsVersions((prev) =>
      prev.map((item) =>
        item.filename === filename
          ? { ...item, label: String(label || "") }
          : item
      )
    );
  }, []);

  const deleteUdsVersion = useCallback(
    async (filename) => {
      const job_url = String(jenkinsJobUrl || "").trim();
      const cache_root = String(jenkinsCacheRoot || "").trim();
      if (!job_url || !filename) return;
      const ok = await askConfirm({ title: "UDS 踰꾩쟾 ??젣", message: `"${filename}" UDS 踰꾩쟾????젣?섏떆寃좎뒿?덇퉴?`, confirmLabel: "??젣", danger: true });
      if (!ok) return;
      try {
        const res = await fetch("/api/jenkins/uds/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_url, cache_root, filename }),
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        await res.json();
        setUdsPreviewHtml("");
        loadUdsVersions();
        setMessage("UDS 踰꾩쟾 ??젣 ?꾨즺");
      } catch (e) {
        setMessage(`UDS 踰꾩쟾 ??젣 ?ㅽ뙣: ${e.message || String(e)}`);
      }
    },
    [jenkinsJobUrl, jenkinsCacheRoot, loadUdsVersions]
  );

  const stopJenkinsProgress = useCallback((action) => {
    const timer = jenkinsProgressTimerRef.current[action];
    if (timer) {
      clearInterval(timer);
      jenkinsProgressTimerRef.current[action] = null;
    }
  }, []);

  const enqueueJenkinsOp = useCallback((type, message) => {
    const id = `${type}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const started_at = new Date().toISOString();
    setJenkinsOpsQueue((prev) =>
      [
        {
          id,
          type,
          status: "started",
          message,
          started_at,
          updated_at: started_at,
        },
        ...prev,
      ].slice(0, 50)
    );
    return id;
  }, []);

  const updateJenkinsOp = useCallback((id, patch) => {
    if (!id) return;
    const updated_at = new Date().toISOString();
    setJenkinsOpsQueue((prev) =>
      prev.map((item) =>
        item.id === id ? { ...item, ...patch, updated_at } : item
      )
    );
  }, []);

  const fetchJenkinsProgress = useCallback(
    async (action) => {
      if (!jenkinsJobUrl) return;
      const jobId = jenkinsProgressJobIds[action] || "";
      try {
        const data = await api(
          `/api/jenkins/progress?action=${encodeURIComponent(
            action
          )}&job_url=${encodeURIComponent(
            jenkinsJobUrl
          )}&build_selector=${encodeURIComponent(
            jenkinsBuildSelector || "lastSuccessfulBuild"
          )}&job_id=${encodeURIComponent(jobId)}`
        );
        const progress = data?.progress || null;
        setJenkinsProgress((prev) => ({ ...prev, [action]: progress }));
        if (progress?.done || progress?.error) {
          const currentJobId = progress?.job_id || jobId || "";
          const handled = jenkinsProgressHandledRef.current[action];
          if (currentJobId && handled !== currentJobId) {
            jenkinsProgressHandledRef.current[action] = currentJobId;
            if (action === "sync") {
              if (progress?.error) {
                const errText = String(progress.error || "");
                const firstLine = errText.split(/\r?\n/)[0] || errText;
                setMessage(
                  `Jenkins ?숆린???ㅽ뙣: ${firstLine} (?먯꽭???댁슜? F12 肄섏넄 ?뺤씤)`
                );
                updateJenkinsOp(jenkinsOpsIndexRef.current.sync, {
                  status: "failed",
                  message: firstLine,
                });
                if (progress?.error_detail) {
                  devErr(
                    "Jenkins sync error detail:",
                    progress.error_detail
                  );
                } else if (progress?.error) {
                  devErr("Jenkins sync error:", progress.error);
                }
              } else {
                loadJenkinsReportSummary();
                loadJenkinsReportFiles();
                loadJenkinsSourceRoot();
                loadJenkinsBuilds();
                setJenkinsLastSyncDoneId(currentJobId);
                updateJenkinsOp(jenkinsOpsIndexRef.current.sync, {
                  status: "done",
                  message: "동기화 완료",
                });
              }
              setJenkinsSyncLoading(false);
            }
            if (action === "publish") {
              if (progress?.error) {
                setMessage(`由ы룷???낅줈???ㅽ뙣: ${progress.error}`);
                updateJenkinsOp(jenkinsOpsIndexRef.current.publish, {
                  status: "failed",
                  message: String(progress.error || ""),
                });
              } else {
                loadJenkinsReportSummary();
                updateJenkinsOp(jenkinsOpsIndexRef.current.publish, {
                  status: "done",
                  message: "업로드 완료",
                });
              }
              setJenkinsPublishLoading(false);
            }
            if (action === "uds") {
              if (progress?.error) {
                setMessage(`UDS ?앹꽦 ?ㅽ뙣: ${progress.error}`);
                updateJenkinsOp(jenkinsOpsIndexRef.current.uds, {
                  status: "failed",
                  message: String(progress.error || ""),
                });
              } else if (progress?.result) {
                const result = progress.result;
                if (result?.download_url) setUdsResultUrl(result.download_url);
                if (result?.filename) {
                  publishUdsToDocs(result.filename);
                }
                if (result?.preview_url) {
                  loadUdsPreview(result.preview_url);
                }
                loadUdsVersions();
                setMessage("UDS ?앹꽦 ?꾨즺");
                updateJenkinsOp(jenkinsOpsIndexRef.current.uds, {
                  status: "done",
                  message: "UDS ?앹꽦 ?꾨즺",
                });
              }
              setUdsGenerating(false);
            }
          }
          stopJenkinsProgress(action);
        }
      } catch (_) {
        // 吏꾪뻾瑜?議고쉶 ?ㅽ뙣??臾댁떆
      }
    },
    [
      jenkinsJobUrl,
      jenkinsBuildSelector,
      jenkinsProgressJobIds,
      stopJenkinsProgress,
      loadJenkinsReportSummary,
      loadJenkinsReportFiles,
      loadJenkinsSourceRoot,
      loadUdsPreview,
      loadUdsVersions,
      publishUdsToDocs,
      updateJenkinsOp,
    ]
  );

  const startJenkinsProgress = useCallback(
    (action) => {
      stopJenkinsProgress(action);
      fetchJenkinsProgress(action);
      jenkinsProgressTimerRef.current[action] = setInterval(() => {
        fetchJenkinsProgress(action);
      }, 600);
    },
    [fetchJenkinsProgress, stopJenkinsProgress]
  );

  const generateUdsDocx = useCallback(
    async (
      files,
      reqFiles,
      logicFiles,
      reqPaths,
      logicSource,
      aiEnabled,
      aiExampleFile,
      aiExamplePath,
      aiDetailed,
      logicMaxChildren,
      logicMaxGrandchildren,
      logicMaxDepth,
      globalsFormatOrder,
      globalsFormatSep,
      globalsFormatWithLabels,
      componentList
    ) => {
      const job_url = String(jenkinsJobUrl || "").trim();
      const cache_root = String(jenkinsCacheRoot || "").trim();
      const build_selector = String(
        jenkinsBuildSelector || "lastSuccessfulBuild"
      ).trim();
      if (!job_url) {
        setMessage("Job URL??癒쇱? ?좏깮?댁＜?몄슂.");
        return;
      }
      if (udsSourceOnly && !jenkinsSourceRoot) {
        setMessage("?뚯뒪肄붾뱶 湲곕컲 ?앹꽦? ?뚯뒪 猷⑦듃媛 ?꾩슂?⑸땲??");
        return;
      }
      const opId = enqueueJenkinsOp("uds", "UDS ?앹꽦 ?쒖옉");
      jenkinsOpsIndexRef.current.uds = opId;
      setUdsGenerating(true);
      try {
        const form = new FormData();
        form.append("job_url", job_url);
        form.append("cache_root", cache_root || "");
        form.append("build_selector", build_selector);
        if (udsTemplatePath) {
          form.append("template_path", udsTemplatePath);
        }
        if (jenkinsSourceRoot) {
          form.append("source_root", jenkinsSourceRoot);
        }
        form.append("source_only", udsSourceOnly ? "true" : "false");
        if (Array.isArray(reqFiles)) {
          const typesArr = [];
          reqFiles.forEach((item) => {
            const f = item?.file || item;
            const t = item?.type || "req";
            if (f) {
              form.append("req_files", f);
              typesArr.push(t);
            }
          });
          if (typesArr.length > 0) {
            form.append("req_types", typesArr.join(","));
          }
        }
        if (Array.isArray(reqPaths) && reqPaths.length > 0) {
          form.append("req_paths", JSON.stringify(reqPaths));
        }
        if (Array.isArray(logicFiles)) {
          logicFiles.forEach((f) => {
            if (f) form.append("logic_files", f);
          });
        }
        if (logicSource) {
          form.append("logic_source", String(logicSource));
        }
        if (logicMaxChildren != null) {
          form.append("logic_max_children", String(logicMaxChildren));
        }
        if (logicMaxGrandchildren != null) {
          form.append("logic_max_grandchildren", String(logicMaxGrandchildren));
        }
        if (logicMaxDepth != null) {
          form.append("logic_max_depth", String(logicMaxDepth));
        }
        if (globalsFormatOrder) {
          form.append("globals_format_order", String(globalsFormatOrder));
        }
        if (globalsFormatSep) {
          form.append("globals_format_sep", String(globalsFormatSep));
        }
        if (globalsFormatWithLabels != null) {
          form.append(
            "globals_format_with_labels",
            globalsFormatWithLabels ? "true" : "false"
          );
        }
        if (componentList) {
          form.append("component_list", componentList);
        }
        if (Array.isArray(files)) {
          files.forEach((f) => {
            if (f) form.append("files", f);
          });
        }
        if (aiEnabled) {
          form.append("ai_enable", "true");
        }
        if (aiExampleFile) {
          form.append("ai_example_file", aiExampleFile);
        }
        if (aiExamplePath) {
          form.append("ai_example_path", aiExamplePath);
        }
        if (aiDetailed != null) {
          form.append("ai_detailed", aiDetailed ? "true" : "false");
        }
        if (aiEnabled) {
          const ragTopK = Number(config?.uds_rag_top_k);
          if (Number.isFinite(ragTopK) && ragTopK > 0) {
            form.append("rag_top_k", String(ragTopK));
          }
          const ragCats = Array.isArray(config?.uds_rag_categories)
            ? config.uds_rag_categories
            : [];
          if (ragCats.length > 0) {
            form.append("rag_categories", ragCats.join(","));
          }
        }
        const controller = new AbortController();
        udsAbortRef.current = controller;
        const res = await fetch("/api/jenkins/uds/generate-async", {
          method: "POST",
          body: form,
          signal: controller.signal,
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const data = await res.json();
        setJenkinsProgressJobIds((prev) => ({
          ...prev,
          uds: data?.job_id || "",
        }));
        updateJenkinsOp(opId, {
          status: "running",
          message: "UDS 생성 진행 중",
        });
        startJenkinsProgress("uds");
        setMessage("UDS 생성 시작...");
      } catch (e) {
        if (e?.name === "AbortError") {
          setMessage("UDS ?앹꽦??痍⑥냼?섏뿀?듬땲??");
          updateJenkinsOp(opId, {
            status: "cancelled",
            message: "?ъ슜??痍⑥냼",
          });
          setUdsGenerating(false);
          return;
        }
        setMessage(`UDS DOCX ?앹꽦 ?ㅽ뙣: ${e.message || String(e)}`);
        updateJenkinsOp(opId, {
          status: "failed",
          message: e.message || String(e),
        });
        setUdsGenerating(false);
      } finally {
        // ?꾨즺 泥섎━??吏꾪뻾瑜?肄쒕갚?먯꽌 ?섑뻾
        udsAbortRef.current = null;
      }
    },
    [
      jenkinsJobUrl,
      jenkinsCacheRoot,
      jenkinsBuildSelector,
      udsTemplatePath,
      jenkinsSourceRoot,
      udsSourceOnly,
      config?.uds_rag_top_k,
      config?.uds_rag_categories,
      startJenkinsProgress,
      enqueueJenkinsOp,
      updateJenkinsOp,
    ]
  );

  const cancelUdsDocx = useCallback(() => {
    const controller = udsAbortRef.current;
    if (controller) {
      controller.abort();
      udsAbortRef.current = null;
    }
    const opId = jenkinsOpsIndexRef.current.uds;
    if (opId) {
      updateJenkinsOp(opId, { status: "cancelled", message: "?ъ슜??痍⑥냼" });
    }
    stopJenkinsProgress("uds");
    setUdsGenerating(false);
  }, [stopJenkinsProgress, updateJenkinsOp]);

  const syncJenkins = async () => {
    const job_url = String(jenkinsJobUrl || "").trim();
    const username = String(jenkinsUsername || "").trim();
    const api_token = String(jenkinsToken || "").trim();
    const cache_root = String(jenkinsCacheRoot || "").trim();
    const build_selector = String(
      jenkinsBuildSelector || "lastSuccessfulBuild"
    ).trim();
    if (!job_url) {
      setMessage("Job URL??癒쇱? ?좏깮?댁＜?몄슂.");
      return;
    }
    if (!username || !api_token) {
      setMessage("Username怨?API Token???낅젰?댁＜?몄슂.");
      return;
    }
    if (jenkinsSyncLoading) return;
    const opId = enqueueJenkinsOp("sync", "Jenkins 동기화 시작");
    jenkinsOpsIndexRef.current.sync = opId;
    setJenkinsSyncLoading(true);
    try {
      setMessage("Jenkins 동기화 시작...");
      const scan_mode = jenkinsSyncFastMode ? "report_only" : "build_root";
      const scan_max_files = jenkinsSyncFastMode ? 1500 : undefined;
      const data = await api("/api/jenkins/sync-async", {
        method: "POST",
        body: JSON.stringify({
          job_url,
          username,
          api_token,
          cache_root: cache_root || "",
          build_selector,
          patterns: [],
          verify_tls: !!jenkinsVerifyTls,
          scan_mode,
          scan_max_files,
        }),
      });
      setJenkinsProgressJobIds((prev) => ({
        ...prev,
        sync: data?.job_id || "",
      }));
      updateJenkinsOp(opId, { status: "running", message: "동기화 진행 중" });
      startJenkinsProgress("sync");
    } catch (e) {
      setMessage(`Jenkins 동기화 실패: ${e.message || String(e)}`);
      updateJenkinsOp(opId, {
        status: "failed",
        message: e.message || String(e),
      });
      setJenkinsSyncLoading(false);
    }
  };

  const loadJenkinsLogs = async () => {
    if (!jenkinsJobUrl) return;
    try {
      const data = await api("/api/jenkins/report/logs", {
        method: "POST",
        body: JSON.stringify({
          job_url: jenkinsJobUrl,
          cache_root: jenkinsCacheRoot,
          build_selector: jenkinsBuildSelector,
        }),
      });
      setJenkinsLogs(data.logs || {});
    } catch (e) {
      setMessage(`Jenkins 濡쒓렇 紐⑸줉 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  };

  const loadJenkinsScmInfo = async () => {
    if (!jenkinsScmUrl) {
      setMessage("SCM URL???낅젰?댁＜?몄슂.");
      return;
    }
    try {
      const data = await api("/api/jenkins/scm-info", {
        method: "POST",
        body: JSON.stringify({
          scm_type: jenkinsScmType,
          scm_url: jenkinsScmUrl,
          scm_username: jenkinsScmUsername,
          scm_password: jenkinsScmPassword,
        }),
      });
      if (data && data.revision !== undefined) {
        const nextRevision = String(data.revision ?? "");
        setJenkinsScmRevision(nextRevision);
        setMessage(
          nextRevision
            ? `SVN 由щ퉬??議고쉶?? ${nextRevision}`
            : "SVN 由щ퉬???뺣낫媛 鍮꾩뼱 ?덉뒿?덈떎."
        );
      } else {
        setMessage("SVN 由щ퉬???뺣낫瑜?李얠? 紐삵뻽?듬땲??");
      }
    } catch (e) {
      setMessage(`SCM ?뺣낫 議고쉶 ?ㅽ뙣: ${e.message || String(e)}`);
    }
  };
  const readJenkinsLog = async (path) => {
    if (!jenkinsJobUrl || !path) return;
    try {
      const data = await api(
        `/api/jenkins/report/logs/read?path=${encodeURIComponent(path)}`,
        {
          method: "POST",
          body: JSON.stringify({
            job_url: jenkinsJobUrl,
            cache_root: jenkinsCacheRoot,
            build_selector: jenkinsBuildSelector,
          }),
        }
      );
      setJenkinsLogContent(data.text || "");
      setJenkinsLogPath(path);
    } catch (e) {
      setMessage(`Jenkins 濡쒓렇 ?쎄린 ?ㅽ뙣: ${e.message}`);
    }
  };

  const loadJenkinsComplexity = async () => {
    if (!jenkinsJobUrl) return;
    try {
      const data = await api("/api/jenkins/report/complexity", {
        method: "POST",
        body: JSON.stringify({
          job_url: jenkinsJobUrl,
          cache_root: jenkinsCacheRoot,
          build_selector: jenkinsBuildSelector,
        }),
      });
      setJenkinsComplexityRows(data.rows || []);
    } catch (e) {
      setMessage(`Jenkins 蹂듭옟??濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  };

  const loadJenkinsDocs = async () => {
    if (!jenkinsJobUrl) return;
    try {
      const data = await api("/api/jenkins/report/docs", {
        method: "POST",
        body: JSON.stringify({
          job_url: jenkinsJobUrl,
          cache_root: jenkinsCacheRoot,
          build_selector: jenkinsBuildSelector,
        }),
      });
      setJenkinsDocsHtml(data.ok ? data.html : "");
    } catch (e) {
      setMessage(`Jenkins 臾몄꽌 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  };

  const loadJenkinsVcastRag = async () => {
    if (!jenkinsJobUrl) return;
    setJenkinsVcastLoading(true);
    try {
      const data = await api("/api/jenkins/report/vectorcast-rag", {
        method: "POST",
        body: JSON.stringify({
          job_url: jenkinsJobUrl,
          cache_root: jenkinsCacheRoot,
          build_selector: jenkinsBuildSelector,
        }),
      });
      setJenkinsVcastRag(data || null);
    } catch (e) {
      setMessage(`TResultParser 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    } finally {
      setJenkinsVcastLoading(false);
    }
  };

  const loadJenkinsCallTree = async ({
    entry,
    maxDepth = 5,
    includePaths = [],
    excludePaths = [],
    maxFiles = 2000,
    includeExternal = false,
    compileCommandsPath = "",
    externalMap = [],
  }) => {
    if (!jenkinsJobUrl || !entry) return;
    try {
      const data = await api("/api/jenkins/call-tree", {
        method: "POST",
        body: JSON.stringify({
          job_url: jenkinsJobUrl,
          cache_root: jenkinsCacheRoot,
          build_selector: jenkinsBuildSelector,
          source_root: jenkinsSourceRoot || undefined,
          entry,
          max_depth: maxDepth,
          include_paths: includePaths,
          exclude_paths: excludePaths,
          max_files: maxFiles,
          include_external: includeExternal,
          compile_commands_path: compileCommandsPath || undefined,
          external_map: externalMap,
        }),
      });
      setJenkinsCallTree(data || null);
    } catch (e) {
      setMessage(`Jenkins 肄??몃━ ?앹꽦 ?ㅽ뙣: ${e.message}`);
    }
  };

  const saveJenkinsCallTree = async ({
    entry,
    maxDepth = 5,
    includePaths = [],
    excludePaths = [],
    maxFiles = 2000,
    includeExternal = false,
    compileCommandsPath = "",
    outputFormat = "json",
    externalMap = [],
    htmlTemplate = "",
  }) => {
    if (!jenkinsJobUrl || !entry) return;
    try {
      const data = await api("/api/jenkins/call-tree/save", {
        method: "POST",
        body: JSON.stringify({
          job_url: jenkinsJobUrl,
          cache_root: jenkinsCacheRoot,
          build_selector: jenkinsBuildSelector,
          source_root: jenkinsSourceRoot || undefined,
          entry,
          max_depth: maxDepth,
          include_paths: includePaths,
          exclude_paths: excludePaths,
          max_files: maxFiles,
          include_external: includeExternal,
          compile_commands_path: compileCommandsPath || undefined,
          output_format: outputFormat,
          external_map: externalMap,
          html_template: htmlTemplate,
        }),
      });
      setJenkinsCallTreeReport(data?.filename || "");
      setMessage(`肄??몃━ 由ы룷????? ${data?.filename || "OK"}`);
    } catch (e) {
      setMessage(`肄??몃━ 由ы룷??????ㅽ뙣: ${e.message}`);
    }
  };

  const previewJenkinsCallTreeHtml = async (htmlTemplate) => {
    if (!jenkinsCallTree) {
      setMessage("肄??몃━ 寃곌낵媛 ?놁뒿?덈떎.");
      return;
    }
    try {
      const data = await api("/api/jenkins/call-tree/preview-html", {
        method: "POST",
        body: JSON.stringify({
          call_tree: jenkinsCallTree,
          html_template: htmlTemplate || "",
        }),
      });
      setJenkinsCallTreePreviewHtml(data?.html || "");
    } catch (e) {
      setMessage(`肄??몃━ ?쒗뵆由?誘몃━蹂닿린 ?ㅽ뙣: ${e.message}`);
    }
  };

  const downloadJenkinsCallTreeReport = async (filename) => {
    if (!jenkinsJobUrl || !filename) return;
    try {
      const res = await fetch(
        `/api/jenkins/call-tree/download?job_url=${encodeURIComponent(jenkinsJobUrl)}&cache_root=${encodeURIComponent(jenkinsCacheRoot)}&filename=${encodeURIComponent(filename)}`,
        { method: "GET" }
      );
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      setMessage(`肄??몃━ 由ы룷???ㅼ슫濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  };

  const publishJenkinsReports = useCallback(
    async (sourceDir) => {
      const job_url = String(jenkinsJobUrl || "").trim();
      const cache_root = String(jenkinsCacheRoot || "").trim();
      const build_selector = String(
        jenkinsBuildSelector || "lastSuccessfulBuild"
      ).trim();
      if (!job_url) {
        setMessage("Job URL??癒쇱? ?좏깮?댁＜?몄슂.");
        return;
      }
      if (jenkinsPublishLoading) return;
      const opId = enqueueJenkinsOp("publish", "由ы룷???낅줈???쒖옉");
      jenkinsOpsIndexRef.current.publish = opId;
      setJenkinsPublishLoading(true);
      try {
        setMessage("濡쒖뺄 由ы룷???낅줈???쒖옉...");
        const data = await api("/api/jenkins/report/publish-async", {
          method: "POST",
          body: JSON.stringify({
            job_url,
            cache_root: cache_root || "",
            build_selector,
            source_dir: sourceDir
              ? String(sourceDir).trim() || undefined
              : undefined,
          }),
        });
        setJenkinsProgressJobIds((prev) => ({
          ...prev,
          publish: data?.job_id || "",
        }));
        updateJenkinsOp(opId, { status: "running", message: "배포 진행 중" });
        startJenkinsProgress("publish");
      } catch (e) {
        const msg = e.message || String(e);
        if (msg.includes("cached build not found") || msg.includes("404")) {
          setMessage("罹먯떆??鍮뚮뱶媛 ?놁뒿?덈떎. 癒쇱? '?숆린??瑜??ㅽ뻾?댁＜?몄슂.");
        } else if (msg.includes("local report folder not found")) {
          setMessage(
            "濡쒖뺄 由ы룷???대뜑瑜?李얠쓣 ???놁뒿?덈떎. source_dir??吏?뺥븯嫄곕굹 ?꾨줈?앺듃 ??由ы룷???대뜑瑜??뺤씤?댁＜?몄슂."
          );
        } else {
          setMessage(`由ы룷???낅줈???ㅽ뙣: ${msg}`);
        }
        updateJenkinsOp(opId, { status: "failed", message: msg });
        setJenkinsPublishLoading(false);
      }
    },
    [
      jenkinsJobUrl,
      jenkinsCacheRoot,
      jenkinsBuildSelector,
      jenkinsPublishLoading,
      startJenkinsProgress,
      enqueueJenkinsOp,
      updateJenkinsOp,
    ]
  );

  const jenkinsAutoPublishHandledRef = useRef("");
  useEffect(() => {
    if (!autoPublishReports) return;
    if (!jenkinsLastSyncDoneId) return;
    if (jenkinsAutoPublishHandledRef.current === jenkinsLastSyncDoneId) return;
    jenkinsAutoPublishHandledRef.current = jenkinsLastSyncDoneId;
    publishJenkinsReports();
  }, [autoPublishReports, jenkinsLastSyncDoneId, publishJenkinsReports]);

  const downloadJenkinsReportFile = async (path) => {
    if (!jenkinsJobUrl || !path) return;
    try {
      const res = await fetch(
        `/api/jenkins/report/files/download?path=${encodeURIComponent(path)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            job_url: jenkinsJobUrl,
            cache_root: jenkinsCacheRoot,
            build_selector: jenkinsBuildSelector,
          }),
        }
      );
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const filename = String(path).split(/[\\/]/).pop() || "report_file";
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      setMessage(`Jenkins ?뚯씪 ?ㅼ슫濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  };

  const downloadJenkinsReportZip = async (paths = []) => {
    if (!jenkinsJobUrl) return;
    try {
      const endpoint =
        paths.length > 0
          ? "/api/jenkins/report/files/download/zip/select"
          : "/api/jenkins/report/files/download/zip";
      const body =
        paths.length > 0
          ? {
              job_url: jenkinsJobUrl,
              cache_root: jenkinsCacheRoot,
              build_selector: jenkinsBuildSelector,
              paths,
            }
          : {
              job_url: jenkinsJobUrl,
              cache_root: jenkinsCacheRoot,
              build_selector: jenkinsBuildSelector,
            };
      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const disposition = res.headers.get("content-disposition") || "";
      const match = disposition.match(/filename="?([^"]+)"?/i);
      const filename = match?.[1] || "jenkins_reports.zip";
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      setMessage(`Jenkins ZIP ?ㅼ슫濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  };

  const openLocalFile = async (path) => {
    if (!path) return;
    try {
      await api("/api/local/open-file", {
        method: "POST",
        body: JSON.stringify({ path }),
      });
    } catch (e) {
      setMessage(`?뚯씪 ?닿린 ?ㅽ뙣: ${e.message}`);
    }
  };

  const openLocalFolder = async (path) => {
    if (!path) return;
    try {
      await api("/api/local/open-folder", {
        method: "POST",
        body: JSON.stringify({ path }),
      });
    } catch (e) {
      setMessage(`?대뜑 ?닿린 ?ㅽ뙣: ${e.message}`);
    }
  };

  const refreshProfiles = async () => {
    try {
      const prof = await api("/api/profiles");
      setProfiles(prof.names || []);
      if (prof.last_profile) {
        setSelectedProfile(prof.last_profile);
        setProfileName(prof.last_profile);
      }
    } catch (e) {
      setMessage(`?꾨줈?뚯씪 紐⑸줉 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  };

  useEffect(() => {
    if (!selectedProfile) return;
    const saveLast = async () => {
      try {
        await api("/api/profiles/last", {
          method: "POST",
          body: JSON.stringify({ name: selectedProfile }),
        });
      } catch (e) {
        setMessage(`?꾨줈?뚯씪 last ????ㅽ뙣: ${e.message}`);
      }
    };
    saveLast();
  }, [selectedProfile]);

  const createSession = async () => {
    try {
      const data = await api("/api/sessions/new", { method: "POST" });
      setSessions((prev) => [data, ...prev]);
      setSessionId(data.id);
      setMessage("???몄뀡 ?앹꽦 ?꾨즺");
    } catch (e) {
      setMessage(`?몄뀡 ?앹꽦 ?ㅽ뙣: ${e.message}`);
    }
  };

  const updateSessionName = async () => {
    if (!sessionId) return;
    try {
      await api(`/api/sessions/${sessionId}/name`, {
        method: "POST",
        body: JSON.stringify({ name: sessionName }),
      });
      setMessage("?몄뀡 ?대쫫 ??λ맖");
    } catch (e) {
      setMessage(`?몄뀡 ?대쫫 ????ㅽ뙣: ${e.message}`);
    }
  };

  const deleteSession = async () => {
    if (!sessionId) return;
    const ok = await askConfirm({ title: "?몄뀡 ??젣", message: "?꾩옱 ?몄뀡????젣?섏떆寃좎뒿?덇퉴? ???묒뾽? ?섎룎由????놁뒿?덈떎.", confirmLabel: "??젣", danger: true });
    if (!ok) return;
    try {
      await api(`/api/sessions/${sessionId}`, { method: "DELETE" });
      setSessions((prev) => prev.filter((s) => s.id !== sessionId));
      setSessionId("");
      setMessage("?몄뀡 ??젣 ?꾨즺");
    } catch (e) {
      setMessage(`?몄뀡 ??젣 ?ㅽ뙣: ${e.message}`);
    }
  };

  const runPipeline = async () => {
    if (!sessionId || !currentSession || !config) {
      setMessage("?몄뀡 ?먮뒗 ?ㅼ젙???놁뒿?덈떎.");
      return;
    }
    const preflightRes = await loadPreflight(true);
    const resolvedRoot = preflightRes?.resolved?.root || config.project_root;
    if (!resolvedRoot) {
      setMessage("?꾨줈?앺듃 猷⑦듃媛 鍮꾩뼱?덉뒿?덈떎.");
      return;
    }
    setLoading(true);
    setMessage("");
    try {
      const parsed = {
        ...config,
        report_dir: currentSession.path,
        project_root: resolvedRoot,
      };
      const data = await api(`/api/sessions/${sessionId}/run`, {
        method: "POST",
        body: JSON.stringify({
          project_root: parsed.project_root,
          config: parsed,
        }),
      });
      setRunMeta((prev) => ({
        ...prev,
        active: true,
        pid: data?.pid ?? prev.pid,
        logPath: data?.log_path ?? prev.logPath,
        statusPath: data?.status_path ?? prev.statusPath,
        startedAt: new Date().toLocaleString(),
      }));
      setMessage("파이프라인 실행 시작");
      refreshLogs();
    } catch (e) {
      setMessage(`?ㅽ뻾 ?ㅽ뙣: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  const stopPipeline = async () => {
    if (!runMeta.pid) {
      setMessage("以묒????꾨줈?몄뒪媛 ?놁뒿?덈떎.");
      return;
    }
    try {
      await api("/api/run/stop", {
        method: "POST",
        body: JSON.stringify({
          pid: runMeta.pid,
          status_path: runMeta.statusPath,
        }),
      });
      setRunMeta((prev) => ({ ...prev, active: false }));
      setMessage("파이프라인 중지 요청");
      refreshSession();
    } catch (e) {
      setMessage(`以묒? ?ㅽ뙣: ${e.message}`);
    }
  };

  const exportSession = async () => {
    if (!sessionId) return;
    try {
      if (config) {
        await api(`/api/sessions/${sessionId}/config`, {
          method: "POST",
          body: JSON.stringify({ config }),
        });
      }
      const data = await api(`/api/sessions/${sessionId}/export`, {
        method: "POST",
      });
      setMessage(`諛깆뾽 ?앹꽦: ${data.file}`);
      refreshExports();
    } catch (e) {
      setMessage(`諛깆뾽 ?앹꽦 ?ㅽ뙣: ${e.message}`);
    }
  };

  const loadSessionConfig = useCallback(
    async (id) => {
      if (!id) return;
      try {
        const data = await api(`/api/sessions/${id}/config`);
        const cfg = data?.config || {};
        if (cfg && Object.keys(cfg).length > 0) {
          setConfig((prev) => ({ ...(prev || {}), ...cfg }));
          setMessage("?몄뀡 ?ㅼ젙???곸슜?덉뒿?덈떎.");
        } else {
          setMessage("?몄뀡 ?ㅼ젙???놁뒿?덈떎.");
        }
      } catch (e) {
        setMessage(`?몄뀡 ?ㅼ젙 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
      }
    },
    [setConfig]
  );

  const deleteExport = async (file) => {
    const ok = await askConfirm({ title: "諛깆뾽 ??젣", message: `"${file}" 諛깆뾽????젣?섏떆寃좎뒿?덇퉴?`, confirmLabel: "??젣", danger: true });
    if (!ok) return;
    try {
      await api(`/api/exports/${encodeURIComponent(file)}`, {
        method: "DELETE",
      });
      setMessage(`諛깆뾽 ??젣?? ${file}`);
      refreshExports();
    } catch (e) {
      setMessage(`諛깆뾽 ??젣 ?ㅽ뙣: ${e.message}`);
    }
  };

  const restoreExport = async (file) => {
    try {
      const data = await api(
        `/api/exports/restore/${encodeURIComponent(file)}`,
        {
          method: "POST",
        }
      );
      setMessage(`諛깆뾽 蹂듭썝 ?꾨즺: ${data.session_id}`);
      const sessionsData = await api("/api/sessions");
      setSessions(sessionsData);
      if (data.session_id) {
        setSessionId(data.session_id);
        loadSessionConfig(data.session_id);
      }
      refreshExports();
    } catch (e) {
      setMessage(`諛깆뾽 蹂듭썝 ?ㅽ뙣: ${e.message}`);
    }
  };

  const cleanupExports = async (days) => {
    try {
      const res = await api(`/api/exports/cleanup?days=${days}`, {
        method: "POST",
      });
      setMessage(`백업 정리 완료: ${res.deleted}개`);
      refreshExports();
    } catch (e) {
      setMessage(`諛깆뾽 ?뺣━ ?ㅽ뙣: ${e.message}`);
    }
  };

  const updateConfig = (key, value) => {
    setConfig((prev) => ({ ...(prev || {}), [key]: value }));
  };

  const updatePreset = (preset) => {
    if (!preset || !options.quality_presets_map) {
      updateConfig("quality_preset", preset);
      return;
    }
    const presetCfg = options.quality_presets_map[preset] || {};
    updateConfig("quality_preset", preset);
    if (preset !== "custom") {
      updateConfig("do_clang_tidy", !!presetCfg.clang_tidy);
      updateConfig("enable_semgrep", !!presetCfg.semgrep);
      updateConfig("semgrep_config", presetCfg.semgrep_config || "p/default");
    }
  };


  const pickDirectory = async (title) => {
    if (pickerTimerRef.current) {
      clearTimeout(pickerTimerRef.current);
    }
    if (pickerHintTimerRef.current) {
      clearTimeout(pickerHintTimerRef.current);
    }
    pickerTimerRef.current = setTimeout(() => {
      setPickerBusy(true);
      setPickerLabel(title || "");
    }, 350);
    pickerHintTimerRef.current = setTimeout(() => {
      setMessage(
        "?대뜑 ?좏깮 李쎌씠 ?ㅻ옒 嫄몃┰?덈떎. 李쎌씠 ?붾㈃ ?ㅼ뿉 ?덉쓣 ???덉뒿?덈떎."
      );
    }, 6000);
    try {
      const data = await api("/api/local/pick-directory", {
        method: "POST",
        body: JSON.stringify({ title }),
      });
      if (data.path) return data.path;
      if (data.error && data.error !== "cancelled") {
        const hint = data.error.includes("tkinter_unavailable")
          ? "?대뜑 ?좏깮 李쎌쓣 ?????놁뒿?덈떎. Tkinter ?먮뒗 Windows ?대뜑 ?좏깮 李쎌쓣 ?뺤씤?섏꽭??"
          : `?대뜑 ?좏깮 ?ㅽ뙣: ${data.error}`;
        setMessage(hint);
      }
      return "";
    } catch (e) {
      setMessage(`?대뜑 ?좏깮 ?ㅽ뙣: ${e.message}`);
      return "";
    } finally {
      if (pickerTimerRef.current) {
        clearTimeout(pickerTimerRef.current);
        pickerTimerRef.current = null;
      }
      if (pickerHintTimerRef.current) {
        clearTimeout(pickerHintTimerRef.current);
        pickerHintTimerRef.current = null;
      }
      setPickerBusy(false);
      setPickerLabel("");
    }
  };

  const pickFile = async (title) => {
    if (pickerTimerRef.current) {
      clearTimeout(pickerTimerRef.current);
    }
    if (pickerHintTimerRef.current) {
      clearTimeout(pickerHintTimerRef.current);
    }
    pickerTimerRef.current = setTimeout(() => {
      setPickerBusy(true);
      setPickerLabel(title || "");
    }, 350);
    pickerHintTimerRef.current = setTimeout(() => {
      setMessage(
        "?뚯씪 ?좏깮 李쎌씠 ?ㅻ옒 嫄몃┰?덈떎. 李쎌씠 ?붾㈃ ?ㅼ뿉 ?덉쓣 ???덉뒿?덈떎."
      );
    }, 6000);
    try {
      const data = await api("/api/local/pick-file", {
        method: "POST",
        body: JSON.stringify({ title }),
      });
      if (data.path) return data.path;
      if (data.error && data.error !== "cancelled") {
        const hint = data.error.includes("tkinter_unavailable")
          ? "?뚯씪 ?좏깮 李쎌쓣 ?????놁뒿?덈떎. Tkinter ?먮뒗 Windows ?뚯씪 ?좏깮 李쎌쓣 ?뺤씤?섏꽭??"
          : `?뚯씪 ?좏깮 ?ㅽ뙣: ${data.error}`;
        setMessage(hint);
      }
      return "";
    } catch (e) {
      setMessage(`?뚯씪 ?좏깮 ?ㅽ뙣: ${e.message}`);
      return "";
    } finally {
      if (pickerTimerRef.current) {
        clearTimeout(pickerTimerRef.current);
        pickerTimerRef.current = null;
      }
      if (pickerHintTimerRef.current) {
        clearTimeout(pickerHintTimerRef.current);
        pickerHintTimerRef.current = null;
      }
      setPickerBusy(false);
      setPickerLabel("");
    }
  };

  const loadPreflight = async (silent = false) => {
    if (!config) return null;
    const projectRoot =
      mode === "jenkins" ? jenkinsSourceRoot : config.project_root || "";
    if (!silent) {
      setPreflightLoading(true);
      setPreflightError("");
    }
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);
    try {
      const data = await api("/api/local/preflight", {
        method: "POST",
        body: JSON.stringify({
          project_root: projectRoot,
          config,
        }),
        signal: controller.signal,
      });
      setPreflight(data || null);
      setPreflightError("");
      return data;
    } catch (e) {
      if (e.name === "AbortError") {
        setPreflightError(
          "?ъ쟾 ?먭? ?묐떟??吏?곕릺怨??덉뒿?덈떎. ?좎떆 ???ㅼ떆 ?쒕룄??二쇱꽭??"
        );
      } else {
        setPreflightError(`?ъ쟾 ?먭? ?ㅽ뙣: ${e.message}`);
      }
      return null;
    } finally {
      clearTimeout(timeoutId);
      if (!silent) setPreflightLoading(false);
    }
  };

  const appendConfigList = (key, value) => {
    if (!value) return;
    setConfig((prev) => {
      const current = Array.isArray(prev?.[key]) ? prev[key] : [];
      return { ...(prev || {}), [key]: [...current, value] };
    });
  };

  const toRelativePath = (absolutePath) => {
    if (!absolutePath || !config?.project_root) return absolutePath;
    const root = String(config.project_root).replace(/\//g, "\\");
    const target = String(absolutePath).replace(/\//g, "\\");
    const rootLower = root.toLowerCase();
    const targetLower = target.toLowerCase();
    if (targetLower.startsWith(rootLower + "\\")) {
      return target.slice(root.length + 1);
    }
    return absolutePath;
  };

  const explorerRootOptions = useMemo(() => {
    const rootEntries = explorerMap?.["."] || [];
    const dirs = rootEntries
      .filter((entry) => entry?.is_dir)
      .map((entry) => entry.path)
      .filter(Boolean);
    return Array.from(new Set([".", ...dirs]));
  }, [explorerMap]);

  const loadExplorerRoot = async (rootOverride, relPathOverride) => {
    const isEventLike =
      rootOverride &&
      typeof rootOverride === "object" &&
      "nativeEvent" in rootOverride;
    const safeRoot = isEventLike ? undefined : rootOverride;
    const editorRoot =
      safeRoot ||
      (mode === "jenkins" ? jenkinsSourceRoot : config?.project_root);
    if (!editorRoot) {
      setMessage(
        mode === "jenkins"
          ? "Jenkins ?뚯뒪 猷⑦듃媛 鍮꾩뼱?덉뒿?덈떎. ?뚰겕?뚮줈?곗뿉???뚯뒪 猷⑦듃瑜?癒쇱? ?좏깮?댁＜?몄슂."
          : "?꾨줈?앺듃 猷⑦듃媛 鍮꾩뼱?덉뒿?덈떎."
      );
      return;
    }
    try {
      setExplorerLoading(true);
      const relPathRaw = relPathOverride || explorerRoot || ".";
      const relPath =
        typeof relPathRaw === "string" &&
        (/^[A-Za-z]:[\\/]/.test(relPathRaw) ||
          relPathRaw.startsWith("\\") ||
          relPathRaw.startsWith("/"))
          ? "."
          : relPathRaw;
      if (relPath !== relPathRaw) {
        setMessage("?먯깋湲?寃쎈줈???꾨줈?앺듃 猷⑦듃 湲곗? ?곷? 寃쎈줈留??덉슜?⑸땲??");
      }
      const data = await api("/api/local/list-dir", {
        method: "POST",
        body: JSON.stringify({
          project_root: editorRoot,
          rel_path: relPath,
        }),
      });
      if (data?.ok === false) {
        setMessage(`?먯깋湲?濡쒕뱶 ?ㅽ뙣: ${data.error || "unknown_error"}`);
        return;
      }
      const rootPath = data.path || explorerRoot || ".";
      setExplorerRoot(rootPath);
      setExplorerMap((prev) => ({ ...prev, [rootPath]: data.entries || [] }));
      setExpandedPaths([rootPath]);
      setMessage(`?먯깋湲?濡쒕뱶 ?꾨즺: ${rootPath}`);
    } catch (e) {
      setMessage(`?먯깋湲?濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    } finally {
      setExplorerLoading(false);
    }
  };

  // ?뚯뒪 猷⑦듃媛 蹂寃쎈릺怨??먮뵒??酉곗씪 ???먯깋湲??먮룞 濡쒕뱶
  useEffect(() => {
    if (mode === "jenkins" && jenkinsSourceRoot && primaryView === "editor") {
      const timer = setTimeout(() => {
        setExplorerRoot(".");
        setExplorerMap({});
        setExpandedPaths([]);
        loadExplorerRoot(jenkinsSourceRoot, ".");
      }, 200);
      return () => clearTimeout(timer);
    }
  }, [mode, jenkinsSourceRoot, primaryView]);

  const ensureDirLoaded = async (path) => {
    const editorRoot =
      mode === "jenkins" ? jenkinsSourceRoot : config?.project_root;
    if (!editorRoot || explorerMap[path]) return;
    try {
      const data = await api("/api/local/list-dir", {
        method: "POST",
        body: JSON.stringify({
          project_root: editorRoot,
          rel_path: path || ".",
        }),
      });
      setExplorerMap((prev) => ({
        ...prev,
        [data.path || path]: data.entries || [],
      }));
    } catch (e) {
      setMessage(`?먯깋湲?濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  };

  const toggleExplorerPath = async (path) => {
    if (!path) return;
    if (expandedPaths.includes(path)) {
      setExpandedPaths((prev) => prev.filter((p) => p !== path));
      return;
    }
    await ensureDirLoaded(path);
    setExpandedPaths((prev) => [...prev, path]);
  };

  const runSearch = async () => {
    const editorRoot =
      mode === "jenkins" ? jenkinsSourceRoot : config?.project_root;
    if (!editorRoot || !searchQuery) return;
    try {
      const data = await api("/api/local/search", {
        method: "POST",
        body: JSON.stringify({
          project_root: editorRoot,
          rel_path: explorerRoot || ".",
          query: searchQuery,
          max_results: 200,
        }),
      });
      setSearchResults(data.results || []);
    } catch (e) {
      setMessage(`寃???ㅽ뙣: ${e.message}`);
    }
  };

  const runReplaceText = async () => {
    const editorRoot =
      mode === "jenkins" ? jenkinsSourceRoot : config?.project_root;
    if (!editorRoot || !editorPath || !replaceQuery) return;
    try {
      const data = await api("/api/local/replace-text", {
        method: "POST",
        body: JSON.stringify({
          project_root: editorRoot,
          rel_path: editorPath,
          search: replaceQuery,
          replace: replaceValue,
        }),
      });
      setMessage(data.changed ? "移섑솚 ?꾨즺" : "移섑솚 ????놁쓬");
    } catch (e) {
      setMessage(`移섑솚 ?ㅽ뙣: ${e.message}`);
    }
  };

  const loadGitStatus = async () => {
    if (!config?.project_root) return;
    const body = {
      project_root: config.project_root,
      workdir_rel: scmWorkdir || ".",
    };
    const data = await api("/api/local/git/status", {
      method: "POST",
      body: JSON.stringify(body),
    });
    setGitStatus(data.output || "");
  };

  const loadGitDiff = async (staged = false) => {
    if (!config?.project_root) return;
    const body = {
      project_root: config.project_root,
      workdir_rel: scmWorkdir || ".",
      staged,
      path: gitPathInput,
    };
    const data = await api("/api/local/git/diff", {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (staged) setGitDiffStaged(data.output || "");
    else setGitDiff(data.output || "");
  };

  const loadGitLog = async () => {
    if (!config?.project_root) return;
    const data = await api("/api/local/git/log", {
      method: "POST",
      body: JSON.stringify({
        project_root: config.project_root,
        workdir_rel: scmWorkdir || ".",
        max_count: 30,
      }),
    });
    setGitLog(data.output || "");
  };

  const loadGitBranches = async () => {
    if (!config?.project_root) return;
    const data = await api("/api/local/git/branches", {
      method: "POST",
      body: JSON.stringify({
        project_root: config.project_root,
        workdir_rel: scmWorkdir || ".",
      }),
    });
    setGitBranches(data.output || "");
  };

  const runGitStage = async (unstage = false) => {
    if (!config?.project_root) return;
    const body = {
      project_root: config.project_root,
      workdir_rel: scmWorkdir || ".",
      paths: gitPathInput ? [gitPathInput] : [],
    };
    const url = unstage ? "/api/local/git/unstage" : "/api/local/git/stage";
    const data = await api(url, { method: "POST", body: JSON.stringify(body) });
    setMessage(data.output || "?꾨즺");
    loadGitStatus();
  };

  const runGitCommit = async () => {
    if (!config?.project_root || !gitCommitMessage) return;
    const data = await api("/api/local/git/commit", {
      method: "POST",
      body: JSON.stringify({
        project_root: config.project_root,
        workdir_rel: scmWorkdir || ".",
        message: gitCommitMessage,
      }),
    });
    setMessage(data.output || "而ㅻ컠 ?꾨즺");
    loadGitStatus();
  };

  const runGitCheckout = async (create = false) => {
    if (!config?.project_root || !gitBranchName) return;
    const url = create
      ? "/api/local/git/create-branch"
      : "/api/local/git/checkout";
    const data = await api(url, {
      method: "POST",
      body: JSON.stringify({
        project_root: config.project_root,
        workdir_rel: scmWorkdir || ".",
        branch: gitBranchName,
      }),
    });
    setMessage(data.output || "?꾨즺");
    loadGitBranches();
  };


  const loadProfile = async () => {
    if (!selectedProfile) return;
    try {
      const prof = await api(
        `/api/profiles/${encodeURIComponent(selectedProfile)}`
      );
      setConfig((prev) => ({ ...(prev || {}), ...prof }));
      if (prof.jenkins_base_url !== undefined) setJenkinsBaseUrl(prof.jenkins_base_url || "");
      if (prof.jenkins_username !== undefined) setJenkinsUsername(prof.jenkins_username || "");
      if (prof.jenkins_api_token !== undefined) setJenkinsToken(prof.jenkins_api_token || "");
      if (prof.jenkins_verify_tls !== undefined) setJenkinsVerifyTls(prof.jenkins_verify_tls !== false);
      if (prof.jenkins_cache_root !== undefined) setJenkinsCacheRoot(prof.jenkins_cache_root || "");
      if (prof.jenkins_build_selector !== undefined) setJenkinsBuildSelector(prof.jenkins_build_selector || "latest");
      if (prof.jenkins_server_root !== undefined) setJenkinsServerRoot(prof.jenkins_server_root || "");
      if (prof.jenkins_server_rel_path !== undefined) setJenkinsServerRelPath(prof.jenkins_server_rel_path || "");
      setMessage(`?꾨줈?뚯씪 濡쒕뱶: ${selectedProfile}`);
    } catch (e) {
      setMessage(`?꾨줈?뚯씪 濡쒕뱶 ?ㅽ뙣: ${e.message}`);
    }
  };

  const saveProfile = async () => {
    if (!profileName || !config) return;
    try {
      const payload = {
        ...config,
        jenkins_base_url: jenkinsBaseUrl,
        jenkins_username: jenkinsUsername,
        jenkins_api_token: jenkinsToken,
        jenkins_verify_tls: jenkinsVerifyTls,
        jenkins_cache_root: jenkinsCacheRoot,
        jenkins_build_selector: jenkinsBuildSelector,
        jenkins_server_root: jenkinsServerRoot,
        jenkins_server_rel_path: jenkinsServerRelPath,
      };
      await api(`/api/profiles/${encodeURIComponent(profileName)}`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setMessage(`?꾨줈?뚯씪 ??? ${profileName}`);
      refreshProfiles();
    } catch (e) {
      setMessage(`?꾨줈?뚯씪 ????ㅽ뙣: ${e.message}`);
    }
  };

  const deleteProfile = async () => {
    if (!selectedProfile) return;
    try {
      await api(`/api/profiles/${encodeURIComponent(selectedProfile)}`, {
        method: "DELETE",
      });
      setMessage(`?꾨줈?뚯씪 ??젣: ${selectedProfile}`);
      setSelectedProfile("");
      setProfileName("");
      setShowProfileDelete(false);
      refreshProfiles();
    } catch (e) {
      setMessage(`?꾨줈?뚯씪 ??젣 ?ㅽ뙣: ${e.message}`);
    }
  };

  const staticCounts = () => {
    const cpp = summary?.static?.cppcheck?.data?.issues?.length || 0;
    const tidy = summary?.static?.clang_tidy?.data?.issues?.length || 0;
    const sem = summary?.static?.semgrep?.data?.issues?.length || 0;
    return { cpp, tidy, sem, total: cpp + tidy + sem };
  };

  const filteredFindings = useMemo(() => {
    const search = parseSearch(searchTerm);
    return (findings || []).filter((item) => {
      const tool = String(item?.tool || "").toLowerCase();
      if (filterTool !== "all" && tool !== filterTool) return false;
      if (search.mode === "none") return true;
      return searchMatch(JSON.stringify(item), search);
    });
  }, [findings, filterTool, searchTerm]);

  const toolOptions = useMemo(() => {
    const set = new Set();
    for (const item of findings || []) {
      const tool = String(item?.tool || "")
        .toLowerCase()
        .trim();
      if (tool) set.add(tool);
    }
    return ["all", ...Array.from(set).sort()];
  }, [findings]);

  const toolCounts = useMemo(() => {
    const counts = {};
    const bySeverity = {};
    for (const item of findings || []) {
      const tool =
        String(item?.tool || "unknown")
          .toLowerCase()
          .trim() || "unknown";
      counts[tool] = (counts[tool] || 0) + 1;
      const sevRaw = String(
        item?.severity ||
          item?.level ||
          item?.priority ||
          item?.kind ||
          item?.type ||
          ""
      ).toLowerCase();
      const sev =
        sevRaw.includes("error") || sevRaw.includes("critical")
          ? "error"
          : sevRaw.includes("warn")
            ? "warning"
            : "info";
      bySeverity[tool] = bySeverity[tool] || { error: 0, warning: 0, info: 0 };
      bySeverity[tool][sev] += 1;
    }
    return { counts, bySeverity };
  }, [findings]);

  const detailTabs = [
    { key: "status", label: "상태", data: status },
    { key: "static", label: "정적 분석", data: summary?.static },
    { key: "preflight", label: "Preflight", data: summary?.preflight },
    {
      key: "change-impact",
      label: "Change Impact",
      data: summary?.change_impact,
    },
    {
      key: "report-health",
      label: "Report Health",
      data: summary?.report_health,
    },
    {
      key: "build",
      label: "Build & Syntax",
      data: { build: summary?.build, syntax: summary?.syntax },
    },
    {
      key: "tests",
      label: "Tests & Coverage",
      data: { tests: summary?.tests, coverage: summary?.coverage },
    },
    { key: "metrics", label: "메트릭 상세", data: { summary, status } },
    {
      key: "local-report",
      label: "로컬 리포트",
      data: { reports: localReportSummaries },
    },
    {
      key: "agent",
      label: "Agent",
      data: { agent: summary?.agent, runs: summary?.agent_runs },
    },
    { key: "scm", label: "SCM", data: summary?.scm },
  ];

  const goToWorkflowTab = (tab) => {
    setPrimaryView("workflow");
    if (tab) setActiveTab(tab);
    if (tab === "logs") refreshLogs();
    if (tab === "complexity") loadComplexity();
  };

  const handleCardClick = (key) => {
    if (key === "static") {
      setFilterTool("all");
      goToWorkflowTab("quality");
      return;
    }
    if (key === "tests") {
      goToWorkflowTab("testing");
      return;
    }
    if (key === "build" || key === "logs") {
      goToWorkflowTab("logs");
      return;
    }
    setActiveTab("overview");
    setDetailTab(key);
    jumpTo("detail-tabs");
  };

  const openEditorAt = (path, line, query = "") => {
    if (!path) return;
    const editorRoot =
      mode === "jenkins" ? jenkinsSourceRoot : config?.project_root;
    if (!editorRoot) {
      setMessage(
        mode === "jenkins"
          ? "Jenkins ?뚯뒪 猷⑦듃媛 鍮꾩뼱?덉뒿?덈떎."
          : "?꾨줈?앺듃 猷⑦듃媛 鍮꾩뼱?덉뒿?덈떎."
      );
      return;
    }
    setPrimaryView("editor");
    setActiveTab("editor");
    const rawPath = String(path);
    const isAbs = /^[a-zA-Z]:[\\/]/.test(rawPath) || rawPath.startsWith("/");
    if (isAbs) {
      editorReadAbsPath(rawPath);
    } else {
      editorReadPath(rawPath);
    }
    if (line) {
      setEditorStartLine(line);
      setEditorEndLine(line);
    }
    setEditorFocusRequest({ path, line: line || 0, query: String(query || ""), ts: Date.now() });
  };

  const goToAnalyzerArtifact = (artifact, preferredSourceRoot = "") => {
    if (preferredSourceRoot) setAnalyzerSourceRoot(preferredSourceRoot);
    handlePrimaryChange("analyzer");
    try {
      window.localStorage.setItem("analyzer_preferred_artifact", String(artifact || ""));
      window.dispatchEvent(new CustomEvent("analyzer:preferred-artifact", { detail: { artifact: String(artifact || "") } }));
    } catch (_) {
      // ignore storage/event failures
    }
  };

  const renderHighlightedJson = (data) => {
    const text = JSON.stringify(data, null, 2);
    const search = parseSearch(searchTerm);
    if (search.mode === "none") return text;
    if (search.mode === "regex") {
      const parts = text.split(search.regex);
      const matches = text.match(search.regex) || [];
      const out = [];
      for (let i = 0; i < parts.length; i += 1) {
        out.push(parts[i]);
        if (matches[i]) {
          out.push(
            <span key={`m-${i}`} className="highlight">
              {matches[i]}
            </span>
          );
        }
      }
      return out;
    }
    const tokens = search.tokens || [];
    const regex = new RegExp(tokens.map(escapeRegExp).join("|"), "ig");
    const parts = text.split(regex);
    const matches = text.match(regex) || [];
    const out = [];
    for (let i = 0; i < parts.length; i += 1) {
      out.push(parts[i]);
      if (matches[i]) {
        out.push(
          <span key={`m-${i}`} className="highlight">
            {matches[i]}
          </span>
        );
      }
    }
    return out;
  };

  const preflightMissing = preflight?.preflight?.missing || [];
  const preflightReady = !!preflight?.ready;
  const preflightWarnings = preflight?.preflight?.warnings || [];
  const preflightWarningLabels = useMemo(() => {
    const map = {
      semgrep_missing_disabled: "semgrep 미설치 비활성화",
    };
    return preflightWarnings.map((item) => map[item] || item);
  }, [preflightWarnings]);
  const preflightSourceLabel = preflight?.resolved?.root
    ? `${preflight.resolved.root} 쨌 ${preflight.resolved.source || "cfg"}`
    : "미확인";

  const handleChatSend = async (overrideText) => {
    const text = (overrideText || chatInput).trim();
    if (!text) return;
    lastChatQuestion.current = text;
    const historyPayload = buildChatHistory(chatMessages);
    setChatMessages((prev) => [
      ...prev,
      { role: "user", text, ts: Date.now() },
      { role: "assistant", text: "__loading__", ts: Date.now() },
    ]);
    setChatInput("");
    setChatPending(true);
    try {
      const reportDir = currentSession?.path || config?.report_dir || "";
      const uiContext =
        mode === "jenkins"
          ? {
              mode,
              current_view: primaryView,
              job_url: jenkinsJobUrl,
              cache_root: jenkinsCacheRoot,
              build_selector: jenkinsBuildSelector,
              summary: jenkinsReportSummary || jenkinsData?.summary || {},
              status: jenkinsReportSummary?.kpis?.build || jenkinsData?.status || {},
            }
          : {
              mode,
              current_view: primaryView,
              session_id: sessionId,
              project_root: config?.project_root || "",
              workdir_rel: ".",
              summary: summary || {},
              status: status || {},
              findings_count: Array.isArray(findings) ? findings.length : 0,
              history_count: Array.isArray(history) ? history.length : 0,
            };
      const payload = {
        mode,
        question: text,
        session_id: sessionId || undefined,
        report_dir: reportDir || undefined,
        llm_model: config?.llm_model || undefined,
        oai_config_path: config?.oai_config_path || undefined,
        history: historyPayload,
        ui_context: uiContext,
        jenkins:
          mode === "jenkins"
            ? {
                job_url: jenkinsJobUrl,
                cache_root: jenkinsCacheRoot,
                build_selector: jenkinsBuildSelector,
              }
            : undefined,
      };
      await postSseJson("/api/chat/stream", payload, {
        onEvent: (event) => {
          if (!event || event.type === "started" || event.type === "keepalive" || event.type === "done") {
            return;
          }
          if (event.type === "error") {
            throw new Error(event.detail || "채팅 스트림 오류");
          }
          if (event.type === "graph_node_started" || event.type === "graph_node_finished" || event.type === "tool_started" || event.type === "tool_finished" || event.type === "degraded_mode") {
            const label = (() => {
              if (event.type === "graph_node_started") return `graph: ${event.payload?.node || "node"} 시작`;
              if (event.type === "graph_node_finished") return `graph: ${event.payload?.node || "node"} 완료`;
              if (event.type === "tool_started") return `tool: ${event.payload?.tool_name || "tool"} 시작`;
              if (event.type === "tool_finished") return `tool: ${event.payload?.tool_name || "tool"} 완료`;
              if (event.type === "degraded_mode") return `fallback: ${event.payload?.reason || "degraded"}`;
              return "";
            })();
            if (!label) return;
            setChatMessages((prev) => {
              const next = [...prev];
              const last = next[next.length - 1] || {};
              next[next.length - 1] = {
                ...last,
                role: "assistant",
                text: "__loading__",
                ts: last.ts || Date.now(),
                progress: [...(Array.isArray(last.progress) ? last.progress : []), label].slice(-8),
              };
              return next;
            });
            return;
          }
          if (event.type !== "message") {
            return;
          }
          setChatMessages((prev) => {
            const next = [...prev];
            next[next.length - 1] = {
              role: "assistant",
              text: event.answer || "응답이 비어 있습니다.",
              ts: Date.now(),
              sources: event.sources || [],
              citations: event.citations || [],
              evidence: event.evidence || [],
              next_steps: event.next_steps || [],
              structured: event.structured || null,
            };
            return next;
          });
        },
      });
    } catch (e) {
      setChatMessages((prev) => {
        const next = [...prev];
        next[next.length - 1] = {
          role: "assistant",
          text: `오류: ${e.message}`,
          ts: Date.now(),
          error: true,
        };
        return next;
      });
    } finally {
      setChatPending(false);
    }
  };

  const normalizeChatSources = (sources) => {
    if (!Array.isArray(sources)) return [];
    return sources.map((s) => {
      if (typeof s === "string" || typeof s === "number") return String(s);
      if (s && typeof s === "object") {
        if (s.label) return String(s.label);
        if (s.source) return String(s.source);
        if (s.model) return String(s.model);
        try {
          return JSON.stringify(s);
        } catch {
          return "[object]";
        }
      }
      return String(s);
    });
  };

  const normalizeChatCitations = (citations) => {
    if (!Array.isArray(citations)) return [];
    return citations
      .map((item) => {
        if (!item || typeof item !== "object") return "";
        return String(item.label || item.uri || item.path || "").trim();
      })
      .filter(Boolean);
  };

  const normalizeChatEvidence = (evidence) => {
    if (!Array.isArray(evidence)) return [];
    return evidence
      .map((item, idx) => {
        if (!item || typeof item !== "object") return null;
        const title = String(item.title || item.label || item.source || `evidence-${idx + 1}`).trim();
        const sourceType = String(item.source_type || item.sourceType || "context").trim();
        const snippet = String(item.snippet || "").trim();
        const location = String(item.path || item.uri || "").trim();
        return {
          key: `${title}-${idx}`,
          title,
          sourceType,
          snippet,
          location,
          raw: item,
        };
      })
      .filter(Boolean);
  };

  const normalizeChatSteps = (steps) => {
    if (!Array.isArray(steps)) return [];
    return steps.map((item) => String(item || "").trim()).filter(Boolean);
  };

  const resolveChatOpenTarget = (item) => {
    if (!item || typeof item !== "object") return "";
    const rawPath = String(item.path || "").trim();
    const rawUri = String(item.uri || "").trim();
    const sourceType = String(item.source_type || item.sourceType || "").trim().toLowerCase();
    if (rawPath) {
      if (/^[a-zA-Z]:[\\/]/.test(rawPath) || rawPath.startsWith("/")) return rawPath;
      if (sourceType === "doc") return `docs/${rawPath}`;
      return rawPath;
    }
    if (rawUri.startsWith("code://file/")) return rawUri.slice("code://file/".length);
    if (rawUri.startsWith("docs://file/")) return `docs/${rawUri.slice("docs://file/".length)}`;
    return "";
  };

  const handleChatContextOpen = (item) => {
    const target = resolveChatOpenTarget(item);
    if (!target) return;
    openEditorAt(target);
  };

  const renderChatSupport = (msg, idx, keyPrefix = "") => {
    const sources = normalizeChatSources(msg.sources).slice(0, 5);
    const citations = Array.isArray(msg.citations) ? msg.citations.slice(0, 5) : [];
    const evidence = normalizeChatEvidence(msg.evidence).slice(0, 4);
    const nextSteps = normalizeChatSteps(msg.next_steps || msg.structured?.next_steps).slice(0, 4);
    return (
      <>
        <div className="chat-bubble-meta">
          {msg.ts && <span className="chat-ts">{new Date(msg.ts).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}</span>}
          {msg.role === "assistant" && msg.text !== "__loading__" && (
            <>
              <button type="button" className="chat-action-btn" onClick={() => copyToClipboard(msg.text)} title="복사">복사</button>
              {msg.error && <button type="button" className="chat-action-btn" onClick={handleChatRetry} title="다시 시도">재시도</button>}
            </>
          )}
          {idx > 0 && <button type="button" className="chat-action-btn chat-delete-btn" onClick={() => handleChatDeleteMsg(idx)} title="삭제">삭제</button>}
        </div>
        {sources.length > 0 && (
          <div className="chat-sources">
            {sources.map((s, i) => (
              <span key={`${keyPrefix}src-${s}-${i}`} className="chat-source-badge">{s}</span>
            ))}
          </div>
        )}
        {citations.length > 0 && (
          <div className="chat-sources">
            {citations.map((item, i) => {
              const label = String(item?.label || item?.uri || item?.path || "").trim();
              const target = resolveChatOpenTarget(item);
              return (
                <button
                  key={`${keyPrefix}cite-${label}-${i}`}
                  type="button"
                  className={`chat-source-badge chat-source-link ${target ? "is-openable" : ""}`}
                  onClick={() => target && handleChatContextOpen(item)}
                  disabled={!target}
                  title={target ? "관련 위치 열기" : label}
                >
                  {label}
                </button>
              );
            })}
          </div>
        )}
        {nextSteps.length > 0 && (
          <div className="chat-next-steps">
            <div className="chat-next-steps-title">다음 단계</div>
            <ol>
              {nextSteps.map((step, i) => (
                <li key={`${keyPrefix}step-${i}`}>{step}</li>
              ))}
            </ol>
          </div>
        )}
        {evidence.length > 0 && (
          <div className="chat-evidence-list">
            {evidence.map((item) => {
              const raw = item.raw || null;
              const target = raw ? resolveChatOpenTarget(raw) : "";
              return (
                <button
                  key={`${keyPrefix}${item.key}`}
                  type="button"
                  className={`chat-evidence-card ${target ? "is-openable" : ""}`}
                  onClick={() => raw && target && handleChatContextOpen(raw)}
                  disabled={!target}
                  title={target ? "관련 위치 열기" : item.title}
                >
                  <div className="chat-evidence-head">
                    <span className="chat-evidence-title">{item.title}</span>
                    <span className="chat-evidence-type">{item.sourceType}</span>
                  </div>
                  {item.snippet && <div className="chat-evidence-snippet">{item.snippet}</div>}
                  {item.location && <div className="chat-evidence-path">{item.location}</div>}
                </button>
              );
            })}
          </div>
        )}
      </>
    );
  };

  const handleChatRetry = () => {
    if (lastChatQuestion.current) {
      setChatMessages((prev) => prev.slice(0, -1));
      handleChatSend(lastChatQuestion.current);
    }
  };

  const handleChatClear = () => {
    setChatMessages([{ role: "assistant", text: "대화를 시작합니다. 무엇을 도와드릴까요?", ts: Date.now() }]);
    lastChatQuestion.current = "";
  };

  const handleChatExport = () => {
    const md = chatMessages
      .map(
        (m) =>
          `**${m.role === "user" ? "사용자" : "도우미"}** (${new Date(m.ts || 0).toLocaleTimeString("ko-KR")}):\n${m.text}`
      )
      .join("\n\n---\n\n");
    const blob = new Blob([md], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `chat_export_${new Date().toISOString().slice(0, 10)}.md`;
    a.click(); URL.revokeObjectURL(url);
  };

  const handleChatDeleteMsg = (idx) => {
    setChatMessages((prev) => prev.filter((_, i) => i !== idx));
  };

  const insertChatCodeToEditor = (code) => {
    if (primaryView !== "editor" || !editorText) {
      showToast("warning", "?먮뵒??酉곗뿉???뚯씪???댁뼱??肄붾뱶瑜??쎌엯?????덉뒿?덈떎.");
      return;
    }
    setEditorText((prev) => prev + "\n" + code);
  };

  const footerViewLabel =
    primaryView === "workflow"
      ? "Workflow"
      : primaryView === "editor"
        ? "Editor"
        : primaryView === "analyzer"
          ? "Analyzer"
        : "Dashboard";

  return (
    <div className="app">
      {loading && <div className="top-progress-bar" />}
      <ToastContainer toasts={toasts} removeToast={removeToast} />
      {confirmState && (
        <ConfirmDialog
          title={confirmState.title}
          message={confirmState.message}
          confirmLabel={confirmState.confirmLabel}
          danger={confirmState.danger}
          onConfirm={handleConfirmOk}
          onCancel={handleConfirmCancel}
        />
      )}
      {showShortcutHelp && (
        <div className="shortcut-help-overlay" onClick={() => setShowShortcutHelp(false)}>
          <div className="shortcut-help" onClick={(e) => e.stopPropagation()}>
            <h3>빠른 단축키</h3>
            <div className="shortcut-row"><span>대시보드</span><span className="shortcut-key">Ctrl+1</span></div>
            <div className="shortcut-row"><span>워크플로우</span><span className="shortcut-key">Ctrl+2</span></div>
            <div className="shortcut-row"><span>에디터</span><span className="shortcut-key">Ctrl+3</span></div>
            <div className="shortcut-row"><span>Analyzer</span><span className="shortcut-key">Ctrl+4</span></div>
            <div className="shortcut-row"><span>설정</span><span className="shortcut-key">Ctrl+5</span></div>
            <div className="shortcut-row"><span>채팅 토글</span><span className="shortcut-key">Ctrl+/</span></div>
            <div className="shortcut-row"><span>도움말</span><span className="shortcut-key">F1</span></div>
            <div style={{ marginTop: 12, textAlign: "right" }}>
              <button onClick={() => setShowShortcutHelp(false)}>닫기</button>
            </div>
          </div>
        </div>
      )}
      <div className="global-mode-bar">
        <div className="segmented">
          <button
            className={`segmented-btn ${mode === "local" ? "active" : ""}`}
            onClick={() => setMode("local")}
          >
            로컬
          </button>
          <button
            className={`segmented-btn ${mode === "jenkins" ? "active" : ""}`}
            onClick={() => setMode("jenkins")}
          >
            Jenkins
          </button>
        </div>
      </div>
      <div className="app-body">
        <main className="main">
          <div className="main-content">
            <AppHeader
              title={headerTitle}
              subtitle={headerSub}
              breadcrumbs={breadcrumbs}
              statusTone={statusTone}
              status={status}
              loading={loading}
              sessionLabel={sessionLabel}
              sessionId={sessionId}
              onRefreshSession={refreshSession}
              onRefreshLogs={refreshLogs}
              theme={theme}
              onToggleTheme={toggleTheme}
            />
            <PrimaryNav value={primaryView} onChange={handlePrimaryChange} />
            {mode === "local" && (
              <div className="row">
                <StatusPill tone="neutral">로컬 모드</StatusPill>
                {status?.state ? (
                  <StatusPill tone={statusTone}>{status.state}</StatusPill>
                ) : null}
              </div>
            )}
            <ErrorBoundary name="메인 뷰">
            <Suspense fallback={<div className="loading-spinner">로딩 중...</div>}>
            {primaryView === "settings" && (
              <SettingsPanel
                mode={mode}
                setMode={setMode}
                selectedProfile={selectedProfile}
                setSelectedProfile={setSelectedProfile}
                profiles={profiles}
                loadProfile={loadProfile}
                refreshProfiles={refreshProfiles}
                profileName={profileName}
                setProfileName={setProfileName}
                saveProfile={saveProfile}
                setShowProfileDelete={setShowProfileDelete}
                sessions={sessions}
                sessionId={sessionId}
                setSessionId={setSessionId}
                createSession={createSession}
                deleteSession={deleteSession}
                sessionName={sessionName}
                setSessionName={setSessionName}
                updateSessionName={updateSessionName}
                config={config}
                updateConfig={updateConfig}
                options={options}
                updatePreset={updatePreset}
                splitList={splitList}
                joinList={joinList}
                pickDirectory={pickDirectory}
                pickFile={pickFile}
                appendConfigList={appendConfigList}
                runPipeline={runPipeline}
                loading={loading}
                ragStatus={ragStatus}
                ragIngestResult={ragIngestResult}
                checkRagStatus={checkRagStatus}
                runRagIngest={runRagIngest}
                runRagIngestFiles={runRagIngestFiles}
                switchRagToPgvector={switchRagToPgvector}
                exportSession={exportSession}
                refreshExports={refreshExports}
                cleanupExports={cleanupExports}
                exports={exports}
                deleteExport={deleteExport}
                restoreExport={restoreExport}
                pickerBusy={pickerBusy}
                pickerLabel={pickerLabel}
                message={message}
                jenkinsBaseUrl={jenkinsBaseUrl}
                setJenkinsBaseUrl={setJenkinsBaseUrl}
                jenkinsUsername={jenkinsUsername}
                setJenkinsUsername={setJenkinsUsername}
                jenkinsToken={jenkinsToken}
                setJenkinsToken={setJenkinsToken}
                jenkinsVerifyTls={jenkinsVerifyTls}
                setJenkinsVerifyTls={setJenkinsVerifyTls}
                jenkinsCacheRoot={jenkinsCacheRoot}
                setJenkinsCacheRoot={setJenkinsCacheRoot}
                jenkinsBuildSelector={jenkinsBuildSelector}
                setJenkinsBuildSelector={setJenkinsBuildSelector}
                jenkinsServerRoot={jenkinsServerRoot}
                setJenkinsServerRoot={setJenkinsServerRoot}
                jenkinsServerRelPath={jenkinsServerRelPath}
                setJenkinsServerRelPath={setJenkinsServerRelPath}
              />
            )}
            {primaryView === "analyzer" && (
              <UdsAnalyzerView
                mode={mode}
                reportDir={config?.report_dir || ""}
                jenkinsJobUrl={jenkinsJobUrl}
                setJenkinsJobUrl={setJenkinsJobUrl}
                jenkinsCacheRoot={jenkinsCacheRoot}
                setJenkinsCacheRoot={setJenkinsCacheRoot}
                jenkinsBuildSelector={jenkinsBuildSelector}
                setJenkinsBuildSelector={setJenkinsBuildSelector}
                sourceRoot={analyzerSourceRoot}
                setSourceRoot={setAnalyzerSourceRoot}
                pickDirectory={pickDirectory}
                pickFile={pickFile}
                preferredArtifactType={typeof window !== "undefined" ? window.localStorage.getItem("analyzer_preferred_artifact") || "" : ""}
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
            )}
            {mode === "local" && primaryView === "dashboard" && (
              <LocalDashboard
                status={status}
                summary={summary}
                findings={findings}
                logs={logs}
                history={history}
                complexityRows={complexityRows}
                loadComplexity={loadComplexity}
                detailTabs={detailTabs}
                detailTab={detailTab}
                onDetailTabChange={setDetailTab}
                handleCardClick={handleCardClick}
                staticCounts={staticCounts}
                config={config}
                onOpenEditorFile={openEditorAt}
                onWorkflowTabChange={goToWorkflowTab}
                localReportSummaries={localReportSummaries}
                loadLocalReportSummary={loadLocalReportSummary}
                localReportComparisons={localReportComparisons}
                kbEntries={kbEntries}
                loadKbEntries={loadKbEntries}
              />
            )}
            {mode === "local" && primaryView === "workflow" && (
              <div ref={workflowSplitRef} className="workflow-split">
                <section
                  className="workflow-panel"
                  style={{ width: `${workflowLeftWidth}px` }}
                >
                  <div className="section-title">
                    <h3>Run 준비</h3>
                    <span
                      className={`run-indicator ${runMeta.active ? "running" : "idle"}`}
                    />
                  </div>
                  <div className="hint">소스: {preflightSourceLabel}</div>
                  <div className="workflow-guide">
                    <div className="workflow-guide-title">실행 가이드</div>
                    <ol>
                      <li>
                        설정에서 프로젝트 루트와 리포트 경로를 먼저 확인합니다.
                      </li>
                      <li>
                        필요하면 테스트 우선순위와 로컬 테스트 경로를 추가합니다.
                      </li>
                      <li>
                        사전 점검을 실행해서 필수 도구와 누락 항목을 확인합니다.
                      </li>
                      <li>준비가 끝나면 분석 시작 버튼으로 파이프라인을 실행합니다.</li>
                      <li>실행 중에는 우측 로그 패널에서 진행 상황을 확인합니다.</li>
                    </ol>
                  </div>
                  <div className="row">
                    <button
                      onClick={() => loadPreflight()}
                      disabled={!config || preflightLoading}
                    >
                      {preflightLoading ? "점검 중..." : "사전 점검"}
                    </button>
                    <button
                      onClick={runPipeline}
                      disabled={loading || !sessionId || !config}
                    >
                      {loading ? "실행 중..." : "분석 시작"}
                    </button>
                    <button onClick={stopPipeline} disabled={!runMeta.active}>
                      실행 중지
                    </button>
                  </div>
                  {preflightError ? (
                    <div className="error">{preflightError}</div>
                  ) : null}
                  {preflight ? (
                    <>
                      <div
                        className={`preflight-status ${preflightReady ? "ok" : "warn"}`}
                      >
                        {preflightReady ? "준비 완료" : "준비 필요"}
                      </div>
                      {preflightMissing.length > 0 ? (
                        <div className="error">
                          필수 도구 누락: {preflightMissing.join(", ")}
                        </div>
                      ) : null}
                      {preflightWarnings.length > 0 ? (
                        <div className="hint">
                          경고: {preflightWarningLabels.join(", ")}
                        </div>
                      ) : null}
                      <pre className="json">
                        {JSON.stringify(preflight.preflight, null, 2)}
                      </pre>
                    </>
                  ) : (
                    <div className="empty">사전 점검 결과 없음</div>
                  )}
                </section>
                <div
                  className="splitter"
                  onMouseDown={() => setWorkflowDragging("left")}
                />
                <section className="workflow-center">
                  <LocalWorkflow
                    activeTab={activeTab}
                    setActiveTab={setActiveTab}
                    refreshLogs={refreshLogs}
                    loadComplexity={loadComplexity}
                    loadDocs={loadDocs}
                    filteredFindings={filteredFindings}
                    toolCounts={toolCounts}
                    toolOptions={toolOptions}
                    filterTool={filterTool}
                    setFilterTool={setFilterTool}
                    searchTerm={searchTerm}
                    setSearchTerm={setSearchTerm}
                    renderHighlightedJson={renderHighlightedJson}
                    summary={summary}
                    history={history}
                    logs={logs}
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
                    kbEntries={kbEntries}
                    loadKb={loadKb}
                    kbDeleteKey={kbDeleteKey}
                    setKbDeleteKey={setKbDeleteKey}
                    deleteKb={deleteKb}
                    complexityRows={complexityRows}
                    docsHtml={docsHtml}
                    logFiles={logFiles}
                    selectedLogPath={selectedLogPath}
                    setSelectedLogPath={setSelectedLogPath}
                    loadLogList={loadLogList}
                    readLog={readLog}
                    logContent={logContent}
                    sessionId={sessionId}
                    hasReportDir={!!config?.report_dir}
                    reportDir={currentSession?.path || config?.report_dir || ""}
                    onOpenEditorFile={openEditorAt}
                    reportFiles={sessionReportFiles}
                    loadReportFiles={loadSessionReportFiles}
                    downloadReportZip={downloadSessionReportZip}
                    config={config}
                    localReports={localReports}
                    localReportsLoading={localReportsLoading}
                    localReportsError={localReportsError}
                    loadLocalReports={loadLocalReports}
                    generateLocalReports={generateLocalReports}
                    downloadLocalReport={downloadLocalReport}
                    ragStatus={ragStatus}
                    ragIngestResult={ragIngestResult}
                    checkRagStatus={checkRagStatus}
                    runRagIngest={runRagIngest}
                    runRagIngestFiles={runRagIngestFiles}
                    updateConfig={updateConfig}
                    localRagQuery={localRagQuery}
                    setLocalRagQuery={setLocalRagQuery}
                    localRagCategory={localRagCategory}
                    setLocalRagCategory={setLocalRagCategory}
                    localRagResults={localRagResults}
                    localRagLoading={localRagLoading}
                    runLocalRagQuery={runLocalRagQuery}
                    pickDirectory={pickDirectory}
                    pickFile={pickFile}
                    generateLocalUds={generateLocalUds}
                    generateLocalSts={generateLocalSts}
                    generateLocalSuts={generateLocalSuts}
                    onGoAnalyzer={() => handlePrimaryChange("analyzer")}
                  />
                </section>
                <div
                  className="splitter"
                  onMouseDown={() => setWorkflowDragging("right")}
                />
                <section
                  className="workflow-panel"
                  style={{ width: `${workflowRightWidth}px` }}
                >
                  <div className="section-title">
                    <h3>Run 濡쒓렇</h3>
                    <span
                      className={`run-indicator ${runMeta.active ? "running" : "idle"}`}
                    />
                  </div>
                  <div className="hint">
                    ?곹깭: {status?.state || "idle"}{" "}
                    {lastLogAt ? `쨌 ?낅뜲?댄듃 ${lastLogAt}` : ""}
                  </div>
                  <div className="row">
                    <button onClick={refreshLogs} disabled={!sessionId}>
                      濡쒓렇 ?덈줈怨좎묠
                    </button>
                    <button onClick={refreshSession} disabled={!sessionId}>
                      ?곹깭 ?덈줈怨좎묠
                    </button>
                    <button onClick={stopPipeline} disabled={!runMeta.active}>
                      ?ㅽ뻾 以묒?
                    </button>
                  </div>
                  <pre className="json">{logs.join("\n")}</pre>
                </section>
              </div>
            )}
            {primaryView === "editor" && (
              <LocalEditor
                editorPath={editorPath}
                setEditorPath={setEditorPath}
                onPickFile={async () => {
                  const path = await pickFile("?몄쭛???뚯씪 ?좏깮");
                  if (path) setEditorPath(toRelativePath(path));
                }}
                onOpenFile={(path, line) => {
                  if (!path) return;
                  editorReadPath(path);
                  if (line) {
                    setEditorStartLine(line);
                    setEditorEndLine(line);
                  }
                }}
                mode={mode}
                jenkinsSourceRoot={jenkinsSourceRoot}
                explorerRoot={explorerRoot}
                setExplorerRoot={setExplorerRoot}
                explorerMap={explorerMap}
                expandedPaths={expandedPaths}
                explorerLoading={explorerLoading}
                explorerRootOptions={explorerRootOptions}
                message={message}
                loadExplorerRoot={loadExplorerRoot}
                toggleExplorerPath={toggleExplorerPath}
                searchQuery={searchQuery}
                setSearchQuery={setSearchQuery}
                searchResults={searchResults}
                runSearch={runSearch}
                replaceQuery={replaceQuery}
                setReplaceQuery={setReplaceQuery}
                replaceValue={replaceValue}
                setReplaceValue={setReplaceValue}
                runReplaceText={runReplaceText}
                gitStatusInfo={parseGitStatus(gitStatus)}
                gitDiffRows={parseDiffRows(gitDiff)}
                gitDiffStagedRows={parseDiffRows(gitDiffStaged)}
                gitLog={gitLog}
                gitBranches={gitBranches}
                gitBranchName={gitBranchName}
                setGitBranchName={setGitBranchName}
                gitCommitMessage={gitCommitMessage}
                setGitCommitMessage={setGitCommitMessage}
                gitPathInput={gitPathInput}
                setGitPathInput={setGitPathInput}
                loadGitStatus={loadGitStatus}
                loadGitDiff={loadGitDiff}
                loadGitLog={loadGitLog}
                loadGitBranches={loadGitBranches}
                runGitStage={runGitStage}
                runGitCommit={runGitCommit}
                runGitCheckout={runGitCheckout}
                editorRead={editorRead}
                editorWrite={editorWrite}
                editorStartLine={editorStartLine}
                editorEndLine={editorEndLine}
                setEditorStartLine={setEditorStartLine}
                setEditorEndLine={setEditorEndLine}
                editorReplace={editorReplace}
                editorText={editorText}
                setEditorText={setEditorText}
                summary={summary}
                status={status}
                sessionId={sessionId}
                focusRequest={editorFocusRequest}
                logFiles={logFiles}
                logContent={logContent}
                selectedLogPath={selectedLogPath}
                setSelectedLogPath={setSelectedLogPath}
                loadLogList={loadLogList}
                readLog={readLog}
                refreshSession={refreshSession}
                onGoWorkflow={() => handlePrimaryChange("workflow")}
                onRequestAiGuide={requestEditorGuide}
                onFormatCCode={formatCCode}
                findings={findings}
                reportDir={currentSession?.path || config?.report_dir || ""}
                onOpenEditorFile={openEditorAt}
                onSendToChat={(question) => handleChatSend(question)}
              />
            )}
            {mode === "jenkins" && primaryView === "dashboard" && (
              <JenkinsDashboard
                jenkinsData={jenkinsData}
                jenkinsBuilds={jenkinsBuilds}
                config={config}
                onOpenReportFile={openLocalFile}
                onOpenReportFolder={openLocalFolder}
                onJenkinsTabChange={goToJenkinsTab}
                reportSummary={jenkinsReportSummary}
                onLoadSummary={loadJenkinsReportSummary}
                onOpenEditorFile={openEditorAt}
              />
            )}
            {mode === "jenkins" && primaryView === "workflow" && (
              <JenkinsWorkflow
                activeJenkinsTab={activeJenkinsTab}
                setActiveJenkinsTab={setActiveJenkinsTab}
                jenkinsBaseUrl={jenkinsBaseUrl}
                setJenkinsBaseUrl={setJenkinsBaseUrl}
                jenkinsJobUrl={jenkinsJobUrl}
                setJenkinsJobUrl={setJenkinsJobUrl}
                jenkinsUsername={jenkinsUsername}
                setJenkinsUsername={setJenkinsUsername}
                jenkinsToken={jenkinsToken}
                setJenkinsToken={setJenkinsToken}
                jenkinsVerifyTls={jenkinsVerifyTls}
                setJenkinsVerifyTls={setJenkinsVerifyTls}
                jenkinsCacheRoot={jenkinsCacheRoot}
                setJenkinsCacheRoot={setJenkinsCacheRoot}
                jenkinsJobs={jenkinsJobs}
                jenkinsJobsLoading={jenkinsJobsLoading}
                jenkinsBuilds={jenkinsBuilds}
                jenkinsBuildsLoading={jenkinsBuildsLoading}
                jenkinsSyncLoading={jenkinsSyncLoading}
                jenkinsPublishLoading={jenkinsPublishLoading}
                jenkinsProgress={jenkinsProgress}
                jenkinsOpsQueue={jenkinsOpsQueue}
                jenkinsSyncFastMode={jenkinsSyncFastMode}
                setJenkinsSyncFastMode={setJenkinsSyncFastMode}
                jenkinsBuildSelector={jenkinsBuildSelector}
                setJenkinsBuildSelector={setJenkinsBuildSelector}
                jenkinsData={jenkinsData}
                jenkinsLogs={jenkinsLogs}
                jenkinsLogPath={jenkinsLogPath}
                setJenkinsLogPath={setJenkinsLogPath}
                jenkinsLogContent={jenkinsLogContent}
                jenkinsComplexityRows={jenkinsComplexityRows}
                jenkinsDocsHtml={jenkinsDocsHtml}
                jenkinsSourceDownload={jenkinsSourceDownload}
                loadJenkinsJobs={loadJenkinsJobs}
                loadJenkinsBuilds={loadJenkinsBuilds}
                syncJenkins={syncJenkins}
                loadJenkinsLogs={loadJenkinsLogs}
                readJenkinsLog={readJenkinsLog}
                loadJenkinsComplexity={loadJenkinsComplexity}
                loadJenkinsDocs={loadJenkinsDocs}
                message={message}
                setMessage={setMessage}
                reportAnchor={jenkinsReportAnchor}
                onReportAnchorHandled={() => setJenkinsReportAnchor("")}
                reportFiles={jenkinsReportFiles}
                loadReportFiles={loadJenkinsReportFiles}
                downloadReportFile={downloadJenkinsReportFile}
                downloadReportZip={downloadJenkinsReportZip}
                jenkinsServerRoot={jenkinsServerRoot}
                setJenkinsServerRoot={setJenkinsServerRoot}
                jenkinsServerRelPath={jenkinsServerRelPath}
                setJenkinsServerRelPath={setJenkinsServerRelPath}
                jenkinsServerFiles={jenkinsServerFiles}
                jenkinsServerFilesLoading={jenkinsServerFilesLoading}
                jenkinsServerFilesError={jenkinsServerFilesError}
                loadJenkinsServerFiles={loadJenkinsServerFiles}
                reportSummary={jenkinsReportSummary}
                loadReportSummary={loadJenkinsReportSummary}
                vcastRag={jenkinsVcastRag}
                loadVcastRag={loadJenkinsVcastRag}
                vcastLoading={jenkinsVcastLoading}
                callTree={jenkinsCallTree}
                loadCallTree={loadJenkinsCallTree}
                callTreeReport={jenkinsCallTreeReport}
                saveCallTree={saveJenkinsCallTree}
                downloadCallTreeReport={downloadJenkinsCallTreeReport}
                callTreeExternalMap={callTreeExternalMap}
                callTreeHtmlTemplate={callTreeHtmlTemplate}
                callTreePreviewHtml={jenkinsCallTreePreviewHtml}
                previewCallTreeHtml={previewJenkinsCallTreeHtml}
                publishReports={publishJenkinsReports}
                autoPublishReports={autoPublishReports}
                setAutoPublishReports={setAutoPublishReports}
                jenkinsSourceRoot={jenkinsSourceRoot}
                jenkinsSourceRootRemote={jenkinsSourceRootRemote}
                setJenkinsSourceRoot={setJenkinsSourceRoot}
                jenkinsArtifactUrl={jenkinsArtifactUrl}
                setJenkinsArtifactUrl={setJenkinsArtifactUrl}
                jenkinsScmType={jenkinsScmType}
                setJenkinsScmType={setJenkinsScmType}
                jenkinsScmUrl={jenkinsScmUrl}
                setJenkinsScmUrl={setJenkinsScmUrl}
                jenkinsScmUsername={jenkinsScmUsername}
                setJenkinsScmUsername={setJenkinsScmUsername}
                jenkinsScmPassword={jenkinsScmPassword}
                setJenkinsScmPassword={setJenkinsScmPassword}
                jenkinsScmBranch={jenkinsScmBranch}
                setJenkinsScmBranch={setJenkinsScmBranch}
                jenkinsScmRevision={jenkinsScmRevision}
                setJenkinsScmRevision={setJenkinsScmRevision}
                loadJenkinsScmInfo={loadJenkinsScmInfo}
                jenkinsSourceCandidates={jenkinsSourceCandidates}
                loadJenkinsSourceRoot={loadJenkinsSourceRoot}
                downloadJenkinsSourceRoot={downloadJenkinsSourceRoot}
                autoSelectJenkinsSource={autoSelectJenkinsSource}
                setAutoSelectJenkinsSource={setAutoSelectJenkinsSource}
                onSelectSourceRoot={handleJenkinsSourceSelect}
                udsTemplatePath={udsTemplatePath}
                udsUploading={udsUploading}
                udsGenerating={udsGenerating}
                udsResultUrl={udsResultUrl}
                udsVersions={udsVersions}
                udsPreviewHtml={udsPreviewHtml}
                udsPlaceholders={udsPlaceholders}
                udsSourceOnly={udsSourceOnly}
                setUdsSourceOnly={setUdsSourceOnly}
                udsReqPreview={udsReqPreview}
                udsReqMapping={udsReqMapping}
                udsReqCompare={udsReqCompare}
                udsReqFunctionMapping={udsReqFunctionMapping}
                udsReqTraceability={udsReqTraceability}
                udsReqTraceMatrix={udsReqTraceMatrix}
                udsDiff={udsDiff}
                uploadUdsTemplate={uploadUdsTemplate}
                generateUdsDocx={generateUdsDocx}
                cancelUdsDocx={cancelUdsDocx}
                loadUdsVersions={loadUdsVersions}
                loadUdsPreview={loadUdsPreview}
                previewUdsRequirements={previewUdsRequirements}
                loadUdsDiff={loadUdsDiff}
                updateUdsLabel={updateUdsLabel}
                updateUdsLabelDraft={updateUdsLabelDraft}
                deleteUdsVersion={deleteUdsVersion}
                pickFile={pickFile}
                jenkinsRagQuery={jenkinsRagQuery}
                setJenkinsRagQuery={setJenkinsRagQuery}
                jenkinsRagCategory={jenkinsRagCategory}
                setJenkinsRagCategory={setJenkinsRagCategory}
                jenkinsRagResults={jenkinsRagResults}
                jenkinsRagLoading={jenkinsRagLoading}
                runJenkinsRagQuery={runJenkinsRagQuery}
                runRagIngestFiles={runRagIngestFiles}
                enqueueJenkinsOp={enqueueJenkinsOp}
                updateJenkinsOp={updateJenkinsOp}
                openEditorAt={openEditorAt}
                onGoAnalyzerArtifact={goToAnalyzerArtifact}
                onGoAnalyzer={() => handlePrimaryChange("analyzer")}
              />
            )}
            </Suspense>
            </ErrorBoundary>
          </div>
        </main>
        {chatSidebarOpen && (
        <aside className="chat-sidebar">
          <div className="chat-header">
            <h4>분석 도우미</h4>
            <div className="chat-header-actions">
              <button type="button" className="btn-xs" onClick={handleChatExport} title="내보내기">내보내기</button>
              <button type="button" className="btn-xs" onClick={handleChatClear} title="대화 초기화">초기화</button>
              <button type="button" className="btn-xs" onClick={() => setChatSidebarOpen(false)} title="닫기">닫기</button>
            </div>
          </div>
          <div className="chat-quick-presets">
            {["현재 상태 요약해줘", "이슈 우선순위 추천해줘", "커버리지 개선 방법", "다음 해야 할 작업은?", "실패 원인 분석해줘"].map((q) => (
              <button key={q} type="button" className="chat-preset-chip" onClick={() => handleChatSend(q)} disabled={chatPending}>{q}</button>
            ))}
          </div>
          <div className="chat-messages">
            {chatMessages.map((msg, idx) => (
              <div key={`${msg.role}-${idx}`} className={`chat-bubble chat-${msg.role}${msg.error ? " chat-error" : ""}`}>
                {msg.text === "__loading__" ? (
                  <>
                    <span className="chat-typing"><span /><span /><span /></span>
                    {Array.isArray(msg.progress) && msg.progress.length > 0 && (
                      <div className="chat-sources">
                        {msg.progress.slice(-4).map((s, i) => (
                          <span key={`${s}-${i}`} className="chat-source-badge">{s}</span>
                        ))}
                      </div>
                    )}
                  </>
                ) : msg.role === "assistant" ? (
                  <SimpleMarkdown text={msg.text} onInsertCode={insertChatCodeToEditor} />
                ) : (
                  msg.text
                )}
                {renderChatSupport(msg, idx, "sidebar-")}
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>
          <div className="chat-input">
            <textarea
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleChatSend(); } }}
              placeholder="질문을 입력하세요 (Enter 전송, Shift+Enter 줄바꿈)"
              rows={2}
            />
            <button
              onClick={() => handleChatSend()}
              disabled={!chatInput.trim() || chatPending}
            >
              전송
            </button>
          </div>
        </aside>
        )}
        {!chatSidebarOpen && (
          <button type="button" className="chat-toggle-btn" onClick={() => setChatSidebarOpen(true)} title="분석 도우미 열기">열기</button>
        )}
        <button type="button" className={`chat-fab ${chatDrawerOpen ? "fab-active" : ""}`} onClick={() => setChatDrawerOpen(!chatDrawerOpen)} title="분석 도우미 토글">채팅</button>
        {chatDrawerOpen && (
          <div className="chat-drawer-overlay" onClick={() => setChatDrawerOpen(false)}>
            <div className="chat-drawer" onClick={(e) => e.stopPropagation()}>
              <div className="chat-header">
                <h4>분석 도우미</h4>
                <div className="chat-header-actions">
                  <button type="button" className="btn-xs" onClick={handleChatClear}>초기화</button>
                  <button type="button" className="btn-xs" onClick={() => setChatDrawerOpen(false)}>닫기</button>
                </div>
              </div>
              <div className="chat-messages">
                {chatMessages.map((msg, idx) => (
                  <div key={`d-${msg.role}-${idx}`} className={`chat-bubble chat-${msg.role}`}>
                    {msg.text === "__loading__" ? (
                      <>
                        <span className="chat-typing"><span /><span /><span /></span>
                        {Array.isArray(msg.progress) && msg.progress.length > 0 && (
                          <div className="chat-sources">
                            {msg.progress.slice(-4).map((s, i) => (
                              <span key={`d-${s}-${i}`} className="chat-source-badge">{s}</span>
                            ))}
                          </div>
                        )}
                      </>
                    ) : msg.role === "assistant" ? (
                      <SimpleMarkdown text={msg.text} onInsertCode={insertChatCodeToEditor} />
                    ) : (
                      msg.text
                    )}
                    {renderChatSupport(msg, idx, "drawer-")}
                  </div>
                ))}
                <div ref={chatEndRef} />
              </div>
              <div className="chat-input">
                <textarea
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleChatSend(); } }}
                  placeholder="질문을 입력하세요"
                  rows={2}
                />
                <button onClick={() => handleChatSend()} disabled={!chatInput.trim() || chatPending}>전송</button>
              </div>
            </div>
          </div>
        )}
      </div>
      <footer className="app-footer">
        <div className="footer-meta">
          <span className="footer-title">Devops</span>
          <span>
            {mode === "jenkins" ? "Jenkins" : "로컬"} / {footerViewLabel}
          </span>
          <span>세션: {sessionLabel}</span>
          <span>상태: {status?.state || "idle"}</span>
          {lastLogAt ? <span>로그 업데이트: {lastLogAt}</span> : null}
        </div>
        <div className="footer-actions">
          <button onClick={refreshSession} disabled={!sessionId}>
            상태 새로고침
          </button>
          <button onClick={refreshLogs} disabled={!sessionId}>
            로그 새로고침
          </button>
          <button onClick={toggleTheme}>테마 전환</button>
        </div>
      </footer>
      {showProfileDelete && (
        <div
          className="modal-backdrop"
          onClick={() => setShowProfileDelete(false)}
        >
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h4>?꾨줈?뚯씪 ??젣</h4>
            <p>?좏깮???꾨줈?뚯씪????젣?좉퉴?? ???묒뾽? ?섎룎由????놁뒿?덈떎.</p>
            <div className="row">
              <button
                className="btn-outline"
                onClick={() => setShowProfileDelete(false)}
              >
                痍⑥냼
              </button>
              <button className="btn-danger" onClick={deleteProfile}>
                ??젣
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
