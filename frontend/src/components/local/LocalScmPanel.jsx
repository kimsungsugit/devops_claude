import { useEffect, useMemo, useState } from "react";
import ExcelArtifactViewer from "../ExcelArtifactViewer";
import ReportMarkdownPreview from "../ReportMarkdownPreview";

const ACTION_ORDER = ["uds", "suts", "sits", "sts", "sds"];

const toneForAction = (info) => {
  const mode = String(info?.mode || "-").toUpperCase();
  const status = String(info?.status || "").toLowerCase();
  if (status === "failed") return "failed";
  if (mode === "AUTO" && status === "completed") return "success";
  if (mode === "AUTO") return "check";
  if (mode === "FLAG") return "warning";
  return "neutral";
};

const summarizeLinkedDocs = (linkedDocs) =>
  ACTION_ORDER.map((key) => {
    const value = String(linkedDocs?.[key] || "").trim();
    if (!value) return null;
    return { key, value };
  }).filter(Boolean);

const basename = (value) => {
  const raw = String(value || "").trim();
  if (!raw) return "-";
  const parts = raw.split(/[\\/]/);
  return parts[parts.length - 1] || raw;
};

const readErrorMessage = async (res) => {
  let raw = "";
  try {
    raw = await res.text();
  } catch {
    raw = "";
  }
  if (!raw) return `HTTP ${res.status}`;
  try {
    const parsed = JSON.parse(raw);
    return parsed?.detail || parsed?.message || raw || `HTTP ${res.status}`;
  } catch {
    return raw || `HTTP ${res.status}`;
  }
};

const normalizeErrorPayload = (value) => {
  if (!value) return null;
  if (typeof value === "string") {
    return { title: value, detail: "", retryable: false, code: "" };
  }
  if (typeof value === "object") {
    const title = String(value.title || value.message || value.code || "실패").trim();
    const detail = String(value.detail || "").trim();
    return {
      title,
      detail,
      retryable: Boolean(value.retryable),
      code: String(value.code || "").trim(),
    };
  }
  return { title: String(value), detail: "", retryable: false, code: "" };
};

const REVIEW_TABS = [
  { key: "summary", label: "Summary" },
  { key: "functions", label: "Changed Functions" },
  { key: "requirements", label: "Requirements" },
  { key: "checklist", label: "Checklist" },
];

const parseReviewSections = (text) => {
  const src = String(text || "");
  if (!src.trim()) {
    return { summary: "", functions: "", requirements: "", checklist: "", sourceFiles: "" };
  }
  const lines = src.split(/\r?\n/);
  const sections = { summary: [], functions: [], requirements: [], checklist: [], sourceFiles: [] };
  let current = "summary";
  for (const line of lines) {
    const trimmed = line.trim();
    if (trimmed === "## Changed Functions") {
      current = "functions";
    } else if (trimmed === "## Context") {
      current = "requirements";
    } else if (trimmed === "## Review Checklist") {
      current = "checklist";
    } else if (trimmed === "## Changed Files") {
      current = "sourceFiles";
    }
    sections[current].push(line);
  }
  return {
    summary: sections.summary.join("\n").trim(),
    functions: sections.functions.join("\n").trim(),
    requirements: sections.requirements.join("\n").trim(),
    checklist: sections.checklist.join("\n").trim(),
    sourceFiles: sections.sourceFiles.join("\n").trim(),
  };
};

const buildRunSnapshot = (result, label) => {
  if (!result) return null;
  const changedFiles = Array.isArray(result?.trigger?.changed_files)
    ? result.trigger.changed_files
    : Array.isArray(result?.changed_files)
      ? result.changed_files
      : [];
  const changedFunctions = result?.changed_function_types || result?.changed_functions || {};
  const actions = result?.actions || {};
  return {
    label,
    changedFiles,
    changedFunctionKeys: Object.keys(changedFunctions).sort(),
    actions,
    warnings: Array.isArray(result?.warnings) ? result.warnings : [],
  };
};

const compareRuns = (current, baseline) => {
  if (!current || !baseline) return null;
  const currentFiles = new Set(current.changedFiles || []);
  const baselineFiles = new Set(baseline.changedFiles || []);
  const currentFunctions = new Set(current.changedFunctionKeys || []);
  const baselineFunctions = new Set(baseline.changedFunctionKeys || []);
  const actionTargets = Array.from(new Set([...Object.keys(current.actions || {}), ...Object.keys(baseline.actions || {})])).sort();

  return {
    currentLabel: current.label,
    baselineLabel: baseline.label,
    addedFiles: [...currentFiles].filter((x) => !baselineFiles.has(x)),
    removedFiles: [...baselineFiles].filter((x) => !currentFiles.has(x)),
    addedFunctions: [...currentFunctions].filter((x) => !baselineFunctions.has(x)),
    removedFunctions: [...baselineFunctions].filter((x) => !currentFunctions.has(x)),
    changedActions: actionTargets
      .map((target) => {
        const currentMode = String(current.actions?.[target]?.mode || "-").toUpperCase();
        const baselineMode = String(baseline.actions?.[target]?.mode || "-").toUpperCase();
        const currentStatus = String(current.actions?.[target]?.status || "-").toLowerCase();
        const baselineStatus = String(baseline.actions?.[target]?.status || "-").toLowerCase();
        if (currentMode === baselineMode && currentStatus === baselineStatus) return null;
        return {
          target,
          currentMode,
          baselineMode,
          currentStatus,
          baselineStatus,
        };
      })
      .filter(Boolean),
  };
};

const summarizeUdsDiff = (row) => {
  if (!row) return "-";
  const before = row.before || {};
  const after = row.after || {};
  return `calls ${before.calls_count || 0} -> ${after.calls_count || 0}, globals ${before.globals_count || 0} -> ${after.globals_count || 0}, outputs ${before.output_count || 0} -> ${after.output_count || 0}`;
};

const copyText = async (value) => {
  const text = String(value || "").trim();
  if (!text) return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
};

const actionReason = (target, info) => {
  const mode = String(info?.mode || "-").toUpperCase();
  if (mode === "AUTO") return `${target.toUpperCase()} 자동 재생성`;
  if (mode === "FLAG") return `${target.toUpperCase()} 검토 필요`;
  return `${target.toUpperCase()} 영향 없음`;
};

const LocalScmPanel = ({
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
  onImpactComplete,
}) => {
  const [registryItems, setRegistryItems] = useState([]);
  const [registryLoading, setRegistryLoading] = useState(false);
  const [selectedScmId, setSelectedScmId] = useState("");
  const [statusLoading, setStatusLoading] = useState(false);
  const [statusData, setStatusData] = useState(null);
  const [impactLoading, setImpactLoading] = useState(false);
  const [impactResult, setImpactResult] = useState(null);
  const [impactError, setImpactError] = useState("");
  const [impactErrorInfo, setImpactErrorInfo] = useState(null);
  const [autoGenerate, setAutoGenerate] = useState(false);
  const [auditItems, setAuditItems] = useState([]);
  const [auditLoading, setAuditLoading] = useState(false);
  const [changeHistoryItems, setChangeHistoryItems] = useState([]);
  const [changeHistoryLoading, setChangeHistoryLoading] = useState(false);
  const [selectedChangeRunId, setSelectedChangeRunId] = useState("");
  const [selectedChangeDetail, setSelectedChangeDetail] = useState(null);
  const [manualChangedFiles, setManualChangedFiles] = useState("");
  const [targets, setTargets] = useState(["uds", "suts", "sits", "sts", "sds"]);
  const [artifactPreview, setArtifactPreview] = useState({ path: "", text: "", truncated: false });
  const [artifactPreviewLoading, setArtifactPreviewLoading] = useState(false);
  const [reviewTab, setReviewTab] = useState("summary");
  const [compareAuditPath, setCompareAuditPath] = useState("");
  const [udsViewLoading, setUdsViewLoading] = useState(false);
  const [udsViewData, setUdsViewData] = useState(null);
  const [sutsViewLoading, setSutsViewLoading] = useState(false);
  const [sutsViewData, setSutsViewData] = useState(null);
  const [sutsPreviewData, setSutsPreviewData] = useState(null);
  const [sutsPreviewSheet, setSutsPreviewSheet] = useState(0);
  const [sitsViewLoading, setSitsViewLoading] = useState(false);
  const [sitsViewData, setSitsViewData] = useState(null);
  const [sitsPreviewData, setSitsPreviewData] = useState(null);
  const [sitsPreviewSheet, setSitsPreviewSheet] = useState(0);
  const [panelNotice, setPanelNotice] = useState("");
  const [runStage, setRunStage] = useState("");
  const [runStartedAt, setRunStartedAt] = useState(null);
  const [runElapsedSec, setRunElapsedSec] = useState(0);
  const [activeJobId, setActiveJobId] = useState("");
  const [activeJob, setActiveJob] = useState(null);
  const [registryForm, setRegistryForm] = useState({
    id: "",
    name: "",
    scm_type: "svn",
    scm_url: "",
    scm_username: "",
    scm_password_env: "",
    branch: "",
    base_ref: "",
    source_root: "",
  });
  const [registrySaving, setRegistrySaving] = useState(false);
  const [showAdvancedPanels, setShowAdvancedPanels] = useState(false);

  const selectedRegistry = useMemo(
    () => registryItems.find((item) => item.id === selectedScmId) || null,
    [registryItems, selectedScmId]
  );
  const changedFiles = useMemo(
    () =>
      String(manualChangedFiles || "")
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean),
    [manualChangedFiles]
  );
  const changedFunctionEntries = useMemo(
    () => Object.entries(impactResult?.changed_function_types || {}),
    [impactResult]
  );
  const impactGroups = impactResult?.impact || {};
  const activeUdsOutputPath = String(impactResult?.actions?.uds?.output_path || "").trim();
  const activeSutsOutputPath = String(impactResult?.actions?.suts?.output_path || "").trim();
  const activeSitsOutputPath = String(impactResult?.actions?.sits?.output_path || "").trim();
  const currentChangeSummary = impactResult?.change_log?.summary || {};
  const selectedUdsDiff = Array.isArray(selectedChangeDetail?.documents?.uds?.changed_functions)
    ? selectedChangeDetail.documents.uds.changed_functions
    : [];
  const selectedSutsDiff = Array.isArray(selectedChangeDetail?.documents?.suts?.changed_cases)
    ? selectedChangeDetail.documents.suts.changed_cases
    : [];
  const selectedSitsDiff = Array.isArray(selectedChangeDetail?.documents?.sits?.changed_cases)
    ? selectedChangeDetail.documents.sits.changed_cases
    : [];
  const selectedReviewReasons = {
    sts: Array.isArray(selectedChangeDetail?.documents?.sts?.flagged_functions)
      ? selectedChangeDetail.documents.sts.flagged_functions
      : [],
    sds: Array.isArray(selectedChangeDetail?.documents?.sds?.flagged_functions)
      ? selectedChangeDetail.documents.sds.flagged_functions
      : [],
  };
  const linkedDocItems = useMemo(
    () => summarizeLinkedDocs(selectedRegistry?.linked_docs),
    [selectedRegistry]
  );
  const registryHealthItems = useMemo(() => {
    const status = statusData?.status || {};
    return [
      { label: "SCM tool", ok: Boolean(status.tool_available), text: status.tool_available ? "available" : "missing" },
      { label: "source_root", ok: Boolean(status.source_root_exists), text: status.source_root_exists ? "ready" : "missing" },
      { label: "repo", ok: Boolean(status.repo_detected), text: status.repo_detected ? "detected" : "not detected" },
      { label: "linked docs", ok: linkedDocItems.length > 0, text: `${linkedDocItems.length} connected` },
    ];
  }, [statusData, linkedDocItems]);
  const reviewSections = useMemo(() => parseReviewSections(artifactPreview.text), [artifactPreview.text]);
  const reviewTabContent = useMemo(() => {
    if (reviewTab === "functions") return reviewSections.functions || reviewSections.summary;
    if (reviewTab === "requirements") {
      return [reviewSections.requirements, reviewSections.sourceFiles].filter(Boolean).join("\n\n");
    }
    if (reviewTab === "checklist") return reviewSections.checklist || reviewSections.summary;
    return reviewSections.summary;
  }, [reviewSections, reviewTab]);
  const reviewCounts = useMemo(() => {
    const countBulletLines = (value) =>
      String(value || "")
        .split(/\r?\n/)
        .filter((line) => line.trim().startsWith("- "))
        .length;
    return {
      functions: countBulletLines(reviewSections.functions),
      requirements: countBulletLines(reviewSections.requirements),
      checklist: countBulletLines(reviewSections.checklist),
      sourceFiles: countBulletLines(reviewSections.sourceFiles),
    };
  }, [reviewSections]);
  const selectedCompareAudit = useMemo(
    () => auditItems.find((item) => item.path === compareAuditPath) || auditItems[0] || null,
    [auditItems, compareAuditPath]
  );
  const runComparison = useMemo(() => {
    const current = buildRunSnapshot(impactResult, impactResult?.dry_run ? "Current Dry Run" : "Current Run");
    const baseline = buildRunSnapshot(selectedCompareAudit, selectedCompareAudit ? `Baseline ${selectedCompareAudit.filename}` : "");
    return compareRuns(current, baseline);
  }, [impactResult, selectedCompareAudit]);
  const busy = registryLoading || statusLoading || impactLoading || auditLoading;
  const runSummary = useMemo(() => {
    if (impactLoading) return runStage || "Impact 실행 중";
    if (statusLoading) return "SCM 상태 확인 중";
    if (registryLoading) return "SCM registry 로딩 중";
    if (auditLoading) return "최근 실행 이력 로딩 중";
    return "";
  }, [impactLoading, statusLoading, registryLoading, auditLoading, runStage]);
  const slowRunHint = useMemo(() => {
    if (!impactLoading) return "";
    if (runElapsedSec >= 180) return "이 프로젝트의 dry-run은 실제로 3~5분 이상 걸릴 수 있습니다.";
    if (runElapsedSec >= 20) return "변경 파일 수가 많을수록 분석 시간이 길어집니다.";
    return "";
  }, [impactLoading, runElapsedSec]);
  const activeJobStatus = String(activeJob?.status || "").toLowerCase();
  const recommendedNextStep = useMemo(() => {
    if (impactErrorInfo) {
      if (impactErrorInfo.code === "svn_connection_error") return "다음 추천 액션: SVN working copy 경로의 연결 상태를 먼저 확인하세요.";
      if (impactErrorInfo.code === "file_not_found") return "다음 추천 액션: source_root 및 linked_docs 경로를 확인하세요.";
      if (impactErrorInfo.retryable) return "다음 추천 액션: 원인 확인 후 다시 시도하세요.";
    }
    if (!impactResult) return "";
    if (impactResult.dry_run) {
      const actions = impactResult.actions || {};
      const autoTargets = ACTION_ORDER.filter((key) => String(actions?.[key]?.mode || "").toUpperCase() === "AUTO");
      const flagTargets = ACTION_ORDER.filter((key) => String(actions?.[key]?.mode || "").toUpperCase() === "FLAG");
      if (autoTargets.length > 0) {
        return `다음 추천 액션: ${autoTargets.map((item) => item.toUpperCase()).join(", ")} 자동 갱신을 실행하세요.`;
      }
      if (flagTargets.length > 0) {
        return `다음 추천 액션: ${flagTargets.map((item) => item.toUpperCase()).join(", ")} review artifact를 먼저 확인하세요.`;
      }
      return "다음 추천 액션: 현재 영향 범위가 없으므로 실행 없이 완료됩니다.";
    }
    if (activeUdsOutputPath || activeSutsOutputPath) {
      return "다음 추천 액션: 생성된 UDS/SUTS 결과와 STS/SDS review artifact를 확인하세요.";
    }
    return "";
  }, [impactResult, activeUdsOutputPath, activeSutsOutputPath, impactErrorInfo]);

  const persistActiveJob = (jobId, scmId) => {
    try {
      if (!jobId) {
        window.localStorage.removeItem("scmImpactActiveJob");
        return;
      }
      window.localStorage.setItem("scmImpactActiveJob", JSON.stringify({ jobId, scmId }));
    } catch {
      // ignore localStorage failures
    }
  };

  const clearActiveJob = () => {
    setActiveJobId("");
    setActiveJob(null);
    persistActiveJob("", "");
  };

  const loadRegistry = async (attempt = 0) => {
    setRegistryLoading(true);
    setImpactError("");
    setImpactErrorInfo(null);
    setRunStage("SCM registry 로딩 중");
    try {
      const res = await fetch("/api/scm/list");
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      const items = Array.isArray(data?.items) ? data.items : [];
      setRegistryItems(items);
      setSelectedScmId((prev) => {
        if (prev && items.some((item) => item.id === prev)) return prev;
        return items[0]?.id || "";
      });
    } catch (e) {
      if (attempt < 1) {
        await new Promise((resolve) => setTimeout(resolve, 900));
        return loadRegistry(attempt + 1);
      }
      setImpactError(`SCM registry 조회 실패: ${e.message}`);
      setImpactErrorInfo(normalizeErrorPayload({ title: "SCM registry 조회 실패", detail: e.message, retryable: true, code: "registry_load_failed" }));
    } finally {
      setRegistryLoading(false);
      setRunStage("");
    }
  };

  const loadAudit = async (scmId) => {
    if (!scmId) {
      setAuditItems([]);
      return;
    }
    setAuditLoading(true);
    setRunStage("최근 실행 이력 로딩 중");
    try {
      const res = await fetch(`/api/scm/audit/${encodeURIComponent(scmId)}?limit=10`);
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      const items = Array.isArray(data?.items) ? data.items : [];
      setAuditItems(items);
      setCompareAuditPath((prev) => prev || items[0]?.path || "");
    } catch (e) {
      setPanelNotice(`Audit 조회 실패: ${e.message}`);
    } finally {
      setAuditLoading(false);
      setRunStage("");
    }
  };

  const loadChangeHistory = async (scmId) => {
    if (!scmId) {
      setChangeHistoryItems([]);
      setSelectedChangeRunId("");
      setSelectedChangeDetail(null);
      return;
    }
    setChangeHistoryLoading(true);
    try {
      const res = await fetch(`/api/scm/change-history/${encodeURIComponent(scmId)}?limit=10`);
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      const items = Array.isArray(data?.items) ? data.items : [];
      setChangeHistoryItems(items);
      setSelectedChangeRunId((prev) => prev || items[0]?.run_id || "");
    } catch (e) {
      setPanelNotice(`Change history 조회 실패: ${e.message}`);
    } finally {
      setChangeHistoryLoading(false);
    }
  };

  const loadChangeDetail = async (runId) => {
    if (!runId) {
      setSelectedChangeDetail(null);
      return;
    }
    try {
      const res = await fetch(`/api/scm/change-history/detail/${encodeURIComponent(runId)}`);
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setSelectedChangeDetail(data?.item || null);
    } catch (e) {
      setPanelNotice(`Change detail 조회 실패: ${e.message}`);
    }
  };

  useEffect(() => {
    loadRegistry();
  }, []);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem("scmImpactActiveJob");
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (parsed?.jobId) {
        setActiveJobId(String(parsed.jobId));
        if (parsed?.scmId) setSelectedScmId(String(parsed.scmId));
      }
    } catch {
      // ignore restore failures
    }
  }, []);

  useEffect(() => {
    if (!selectedRegistry) return;
    setScmMode(selectedRegistry.scm_type || "git");
    setScmWorkdir(selectedRegistry.source_root || ".");
    setScmRepoUrl(selectedRegistry.scm_url || "");
    setScmBranch(selectedRegistry.branch || "");
    setScmRevision(selectedRegistry.base_ref || "");
    setRegistryForm({
      id: selectedRegistry.id || "",
      name: selectedRegistry.name || "",
      scm_type: selectedRegistry.scm_type || "svn",
      scm_url: selectedRegistry.scm_url || "",
      scm_username: selectedRegistry.scm_username || "",
      scm_password_env: selectedRegistry.scm_password_env || "",
      branch: selectedRegistry.branch || "",
      base_ref: selectedRegistry.base_ref || "",
      source_root: selectedRegistry.source_root || "",
    });
  }, [
    selectedRegistry,
    setScmMode,
    setScmWorkdir,
    setScmRepoUrl,
    setScmBranch,
    setScmRevision,
  ]);

  const resetRegistryForm = () => {
    setRegistryForm({
      id: "",
      name: "",
      scm_type: "svn",
      scm_url: "",
      scm_username: "",
      scm_password_env: "",
      branch: "",
      base_ref: "",
      source_root: "",
    });
  };

  useEffect(() => {
    if (!selectedScmId) {
      setStatusData(null);
      setAuditItems([]);
      return;
    }
    const run = async () => {
      setStatusLoading(true);
      try {
        const res = await fetch(`/api/scm/status/${encodeURIComponent(selectedScmId)}`);
        if (!res.ok) throw new Error(await readErrorMessage(res));
        setStatusData(await res.json());
      } catch (e) {
        setStatusData({ ok: false, error: e.message });
      } finally {
        setStatusLoading(false);
      }
    };
    run();
    loadAudit(selectedScmId);
    loadChangeHistory(selectedScmId);
  }, [selectedScmId]);

  useEffect(() => {
    if (!selectedChangeRunId) {
      setSelectedChangeDetail(null);
      return;
    }
    loadChangeDetail(selectedChangeRunId);
  }, [selectedChangeRunId]);

  useEffect(() => {
    if (!impactLoading || !runStartedAt) {
      setRunElapsedSec(0);
      return;
    }
    setRunElapsedSec(Math.max(0, Math.floor((Date.now() - runStartedAt) / 1000)));
    const timer = window.setInterval(() => {
      setRunElapsedSec(Math.max(0, Math.floor((Date.now() - runStartedAt) / 1000)));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [impactLoading, runStartedAt]);

  useEffect(() => {
    if (!activeJobId) return undefined;
    let cancelled = false;
    let timer = null;

    const poll = async () => {
      try {
        const res = await fetch(`/api/scm/impact-job/${encodeURIComponent(activeJobId)}`);
        if (!res.ok) throw new Error(await readErrorMessage(res));
        const data = await res.json();
        const job = data?.job || null;
        if (!job || cancelled) return;
        setActiveJob(job);
        setImpactLoading(["queued", "running"].includes(String(job.status || "").toLowerCase()));
        setRunStage(String(job.message || "").trim() || "Impact 실행 중");
        if (!runStartedAt && (job.started_at || job.created_at)) {
          const ts = Date.parse(String(job.started_at || job.created_at));
          if (!Number.isNaN(ts)) setRunStartedAt(ts);
        }

        const status = String(job.status || "").toLowerCase();
        if (status === "completed") {
          const resultRes = await fetch(`/api/scm/impact-job/${encodeURIComponent(activeJobId)}/result`);
          if (!resultRes.ok) throw new Error(await readErrorMessage(resultRes));
          const resultData = await resultRes.json();
          if (cancelled) return;
          setImpactResult(resultData?.result || null);
          setImpactError("");
          setPanelNotice(job.dry_run ? "Dry run 완료" : "Impact 실행 완료");
          setImpactLoading(false);
          setRunStage("");
          setRunStartedAt(null);
          clearActiveJob();
          await loadRegistry();
          await loadAudit(selectedScmId || job.scm_id || "");
          await loadChangeHistory(selectedScmId || job.scm_id || "");
          if (typeof onImpactComplete === "function") onImpactComplete(selectedScmId || job.scm_id || "");
          return;
        }
        if (status === "failed") {
          const error = job.error || {};
          const title = String(normalized?.title || "Impact 실행 실패");
          const detail = String(normalized?.detail || "").trim();
          setImpactError(detail ? `${title}: ${detail}` : title);
          setImpactErrorInfo(normalized);
          setImpactResult(null);
          setImpactLoading(false);
          setRunStage("");
          setRunStartedAt(null);
          clearActiveJob();
          await loadAudit(selectedScmId || job.scm_id || "");
          await loadChangeHistory(selectedScmId || job.scm_id || "");
          return;
        }
      } catch (e) {
        if (!cancelled) {
          setImpactError(e.message);
          setImpactErrorInfo(normalizeErrorPayload({ title: "Job 상태 조회 실패", detail: e.message, retryable: true, code: "job_status_failed" }));
          setImpactLoading(false);
          setRunStage("");
        }
      }
      if (!cancelled) {
        timer = window.setTimeout(poll, 2500);
      }
    };

    poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [activeJobId]);

  useEffect(() => {
    if (!impactResult || impactResult.dry_run) return;
    if (activeUdsOutputPath && !udsViewData && !udsViewLoading) {
      loadUdsView(activeUdsOutputPath);
    }
  }, [impactResult, activeUdsOutputPath, udsViewData, udsViewLoading]);

  useEffect(() => {
    if (!impactResult || impactResult.dry_run) return;
    if (activeSutsOutputPath && !sutsViewData && !sutsViewLoading) {
      loadSutsView(activeSutsOutputPath);
    }
  }, [impactResult, activeSutsOutputPath, sutsViewData, sutsViewLoading]);

  useEffect(() => {
    if (!impactResult || impactResult.dry_run) return;
    if (activeSitsOutputPath && !sitsViewData && !sitsViewLoading) {
      loadSitsView(activeSitsOutputPath);
    }
  }, [impactResult, activeSitsOutputPath, sitsViewData, sitsViewLoading]);

  const refreshStatus = async () => {
    if (!selectedScmId) return;
    setStatusLoading(true);
    setRunStage("SCM 상태 확인 중");
    try {
      const res = await fetch(`/api/scm/status/${encodeURIComponent(selectedScmId)}`);
      if (!res.ok) throw new Error(await readErrorMessage(res));
      setStatusData(await res.json());
    } catch (e) {
      setPanelNotice(`상태 확인 실패: ${e.message}`);
    } finally {
      setStatusLoading(false);
      setRunStage("");
    }
  };

  const openFile = async (path) => {
    if (!path) return;
    try {
      const res = await fetch("/api/local/open-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
    } catch (e) {
      setPanelNotice(`파일 열기 실패: ${e.message}`);
    }
  };

  const openFolder = async (path) => {
    if (!path) return;
    try {
      const res = await fetch("/api/local/open-folder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
    } catch (e) {
      setPanelNotice(`폴더 열기 실패: ${e.message}`);
    }
  };

  const copyPath = async (path, label) => {
    const ok = await copyText(path);
    setPanelNotice(ok ? `${label} 경로를 복사했습니다.` : `${label} 경로 복사에 실패했습니다.`);
  };

  const previewArtifact = async (path) => {
    if (!path) return;
    setArtifactPreviewLoading(true);
    setReviewTab("summary");
    try {
      const res = await fetch("/api/local/preview-text", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, max_chars: 16000 }),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      setArtifactPreview({
        path: data?.path || path,
        text: data?.text || "",
        truncated: !!data?.truncated,
      });
    } catch (e) {
      setPanelNotice(`리뷰 미리보기 실패: ${e.message}`);
    } finally {
      setArtifactPreviewLoading(false);
    }
  };

  const loadUdsView = async (path) => {
    const filename = basename(path);
    if (!filename || filename === "-") return;
    setUdsViewLoading(true);
    try {
      const res = await fetch(`/api/local/uds/view/${encodeURIComponent(filename)}`);
      if (!res.ok) throw new Error(await readErrorMessage(res));
      setUdsViewData(await res.json());
    } catch (e) {
      setPanelNotice(`UDS 미리보기 실패: ${e.message}`);
    } finally {
      setUdsViewLoading(false);
    }
  };

  const loadSutsView = async (path) => {
    const filename = basename(path);
    if (!filename || filename === "-") return;
    setSutsViewLoading(true);
    try {
      const [viewRes, previewRes] = await Promise.all([
        fetch(`/api/local/suts/view/${encodeURIComponent(filename)}`),
        fetch(`/api/local/suts/preview/${encodeURIComponent(filename)}`),
      ]);
      if (!viewRes.ok) throw new Error(await readErrorMessage(viewRes));
      if (!previewRes.ok) throw new Error(await readErrorMessage(previewRes));
      setSutsViewData(await viewRes.json());
      setSutsPreviewData(await previewRes.json());
      setSutsPreviewSheet(0);
    } catch (e) {
      setPanelNotice(`SUTS 미리보기 실패: ${e.message}`);
    } finally {
      setSutsViewLoading(false);
    }
  };

  const loadSitsView = async (path) => {
    const filename = basename(path);
    if (!filename || filename === "-") return;
    setSitsViewLoading(true);
    try {
      const [viewRes, previewRes] = await Promise.all([
        fetch(`/api/local/sits/view/${encodeURIComponent(filename)}`),
        fetch(`/api/local/sits/preview/${encodeURIComponent(filename)}`),
      ]);
      if (!viewRes.ok) throw new Error(await readErrorMessage(viewRes));
      if (!previewRes.ok) throw new Error(await readErrorMessage(previewRes));
      setSitsViewData(await viewRes.json());
      setSitsPreviewData(await previewRes.json());
      setSitsPreviewSheet(0);
    } catch (e) {
      setPanelNotice(`SITS 미리보기 실패: ${e.message}`);
    } finally {
      setSitsViewLoading(false);
    }
  };

  const previewAuditItem = (item) => {
    if (!item) return;
    setReviewTab("summary");
    const changedFiles = Array.isArray(item.changed_files) && item.changed_files.length > 0
      ? item.changed_files.map((value) => `- \`${value}\``).join("\n")
      : "- none";
    const changedFunctions = Object.entries(item.changed_functions || {}).length > 0
      ? Object.entries(item.changed_functions || {}).map(([name, kind]) => `- \`${name}\` : \`${kind}\``).join("\n")
      : "- none";
    const md = [
      "# Impact Audit Summary",
      "",
      `- Run: \`${item.filename || "-"}\``,
      `- Trigger: \`${item.trigger || "-"}\``,
      `- Dry run: \`${item.dry_run ? "true" : "false"}\``,
      `- AUTO: \`${item.auto_count || 0}\``,
      `- FLAG: \`${item.flag_count || 0}\``,
      "",
      "## Changed Files",
      changedFiles,
      "",
      "## Changed Functions",
      changedFunctions,
    ].join("\n");
    setArtifactPreview({
      path: item.path || item.filename || "",
      text: md,
      truncated: false,
    });
  };

  const triggerImpact = async (dryRun) => {
    if (!selectedScmId) {
      setImpactError("SCM registry ??ぉ??癒쇱? ?좏깮?섏꽭??");
      return;
    }
    setImpactLoading(true);
    setImpactError("");
    setImpactErrorInfo(null);
    setPanelNotice("");
    setRunStage(dryRun ? "Dry run 분석 중" : "자동 갱신 실행 중");
    setRunStartedAt(Date.now());
    setArtifactPreview({ path: "", text: "", truncated: false });
    try {
      const payload = {
        scm_id: selectedScmId,
        base_ref: selectedRegistry?.base_ref || "",
        dry_run: !!dryRun,
        auto_generate: !dryRun && autoGenerate,
        targets,
        manual_changed_files: changedFiles,
      };
      const res = await fetch("/api/local/impact/trigger-async", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error(await readErrorMessage(res));
      const data = await res.json();
      const jobId = String(data?.job_id || "");
      if (!jobId) {
        throw new Error("job_id missing");
      }
      setImpactResult(null);
      setActiveJob(data?.job || null);
      setActiveJobId(jobId);
      persistActiveJob(jobId, selectedScmId);
      if (!dryRun) {
        setUdsViewData(null);
        setSutsViewData(null);
        setSutsPreviewData(null);
      }
      setPanelNotice(dryRun ? "Dry run job이 시작되었습니다." : "Impact 실행 job이 시작되었습니다.");
    } catch (e) {
      setImpactError(e.message);
      setImpactErrorInfo(normalizeErrorPayload({ title: "Impact job 시작 실패", detail: e.message, retryable: true, code: "job_start_failed" }));
      setImpactResult(null);
      setActiveJob(null);
      clearActiveJob();
      setImpactLoading(false);
      setRunStage("");
      setRunStartedAt(null);
    } finally {
    }
  };

  const toggleTarget = (target) => {
    setTargets((prev) =>
      prev.includes(target) ? prev.filter((item) => item !== target) : [...prev, target]
    );
  };

  const updateRegistryForm = (key, value) => {
    setRegistryForm((prev) => ({ ...prev, [key]: value }));
  };

  const saveRegistry = async (mode) => {
    const isUpdate = mode === "update";
    if (!registryForm.id.trim()) {
      setPanelNotice("Registry ID is required.");
      return;
    }
    if (!registryForm.name.trim()) {
      setPanelNotice("Registry name is required.");
      return;
    }
    setRegistrySaving(true);
    try {
      const payload = {
        id: registryForm.id.trim(),
        name: registryForm.name.trim(),
        scm_type: registryForm.scm_type || "svn",
        scm_url: registryForm.scm_url.trim(),
        scm_username: registryForm.scm_username.trim(),
        scm_password_env: registryForm.scm_password_env.trim(),
        branch: registryForm.branch.trim(),
        base_ref: registryForm.base_ref.trim(),
        source_root: registryForm.source_root.trim(),
      };
      const endpoint = isUpdate
        ? `/api/scm/update/${encodeURIComponent(payload.id)}`
        : "/api/scm/register";
      const res = await fetch(endpoint, {
        method: isUpdate ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
      await loadRegistry();
      setSelectedScmId(payload.id);
      setPanelNotice(isUpdate ? "Registry updated." : "Registry registered.");
    } catch (e) {
      setPanelNotice(`Registry save failed: ${e.message}`);
    } finally {
      setRegistrySaving(false);
    }
  };

  const deleteRegistry = async () => {
    if (!selectedRegistry?.id) return;
    setRegistrySaving(true);
    try {
      const res = await fetch(`/api/scm/delete/${encodeURIComponent(selectedRegistry.id)}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
      await loadRegistry();
      resetRegistryForm();
      setPanelNotice("Registry deleted.");
    } catch (e) {
      setPanelNotice(`Registry delete failed: ${e.message}`);
    } finally {
      setRegistrySaving(false);
    }
  };

  return (
    <div className="scm-impact-page">
      <div className="scm-impact-top-grid">
        <div className="scm-impact-hero">
          <div>
            <h3>SCM Impact Console</h3>
            <p className="hint">
              변경 파일, 영향 함수, 자동 재생성 결과와 검토 필요 문서를 한 화면에서 확인합니다.
            </p>
          </div>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <button type="button" className="btn-outline" onClick={loadRegistry} disabled={busy}>
              {registryLoading ? "Registry..." : "Registry 새로고침"}
            </button>
            <button type="button" className="btn-outline" onClick={refreshStatus} disabled={!selectedScmId || busy}>
              {statusLoading ? "상태 확인..." : "연결 상태 확인"}
            </button>
          </div>
        </div>

        <section className="panel scm-impact-card">
          <div className="scm-impact-card-header">
            <h4>Operations</h4>
            <span className={`status-chip tone-${activeJobStatus === "running" ? "check" : activeJobStatus === "failed" ? "failed" : "info"}`}>
              {activeJobStatus ? activeJobStatus.toUpperCase() : "IDLE"}
            </span>
          </div>
          <div className="scm-impact-grid scm-impact-results-grid">
            <div className="scm-impact-subcard">
              <h5>Registry Health</h5>
              <div className="scm-health-grid">
                {registryHealthItems.map((item) => (
                  <div key={item.label} className="scm-health-card">
                    <div className="hint">{item.label}</div>
                    <div className={`status-chip tone-${item.ok ? "check" : "warning"}`}>{item.text}</div>
                  </div>
                ))}
              </div>
            </div>
            <div className="scm-impact-subcard">
              <h5>Active Run</h5>
              {activeJob ? (
                <div className="list compact">
                  <div className="list-item"><span className="status-chip tone-info">job</span><span className="list-text text-ellipsis">{activeJob.job_id}</span></div>
                  <div className="list-item"><span className="status-chip tone-info">stage</span><span className="list-text">{activeJob.stage || "-"}</span></div>
                  <div className="list-item"><span className="status-chip tone-info">message</span><span className="list-text">{activeJob.message || "-"}</span></div>
                </div>
              ) : (
                <div className="empty">현재 실행 중인 impact job이 없습니다.</div>
              )}
            </div>
          </div>
        </section>
      </div>

      <section className="panel scm-impact-card">
        <div className="scm-impact-card-header">
          <h4>고급 패널</h4>
          <button type="button" className="btn-outline" onClick={() => setShowAdvancedPanels((prev) => !prev)}>
            {showAdvancedPanels ? "고급 패널 숨기기" : "고급 패널 보기"}
          </button>
        </div>
        <div className="hint">Registry 편집, SCM 상세 상태, 수동 Impact Trigger는 필요할 때만 열어보면 됩니다.</div>
      </section>

      {showAdvancedPanels ? (
      <>
      <section className="panel scm-impact-card">
        <div className="scm-impact-card-header">
          <h4>Registry Editor</h4>
          <span className="hint">{selectedRegistry ? `editing ${selectedRegistry.id}` : "new entry"}</span>
        </div>
        <div className="form-grid-2 compact">
          <label>ID</label>
          <input
            value={registryForm.id}
            onChange={(e) => updateRegistryForm("id", e.target.value)}
            placeholder="hdpdm01"
            disabled={registrySaving}
          />
          <label>Name</label>
          <input
            value={registryForm.name}
            onChange={(e) => updateRegistryForm("name", e.target.value)}
            placeholder="HDPDM01 PDS64_RD"
            disabled={registrySaving}
          />
          <label>SCM Type</label>
          <select
            value={registryForm.scm_type}
            onChange={(e) => updateRegistryForm("scm_type", e.target.value)}
            disabled={registrySaving}
          >
            <option value="svn">SVN</option>
            <option value="git">Git</option>
          </select>
          <label>SCM URL</label>
          <input
            value={registryForm.scm_url}
            onChange={(e) => updateRegistryForm("scm_url", e.target.value)}
            placeholder="svn://..."
            disabled={registrySaving}
          />
          <label>Username</label>
          <input
            value={registryForm.scm_username}
            onChange={(e) => updateRegistryForm("scm_username", e.target.value)}
            disabled={registrySaving}
          />
          <label>Password Env</label>
          <input
            value={registryForm.scm_password_env}
            onChange={(e) => updateRegistryForm("scm_password_env", e.target.value)}
            placeholder="SCM_PASSWORD_HDPDM01"
            disabled={registrySaving}
          />
          <label>Base Ref</label>
          <input
            value={registryForm.base_ref}
            onChange={(e) => updateRegistryForm("base_ref", e.target.value)}
            placeholder="SVN working copy면 비워둘 수 있습니다"
            disabled={registrySaving}
          />
          <label>Source Root</label>
          <input
            value={registryForm.source_root}
            onChange={(e) => updateRegistryForm("source_root", e.target.value)}
            placeholder="D:/Project/Ados/PDS64_RD"
            disabled={registrySaving}
          />
        </div>
        <div className="row" style={{ gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <button type="button" className="btn-outline" onClick={resetRegistryForm} disabled={registrySaving}>
            New
          </button>
          <button type="button" className="btn-outline" onClick={() => saveRegistry("create")} disabled={registrySaving}>
            {registrySaving ? "Saving..." : "Register"}
          </button>
          <button type="button" onClick={() => saveRegistry("update")} disabled={registrySaving || !selectedRegistry}>
            {registrySaving ? "Saving..." : "Update"}
          </button>
          <button type="button" className="btn-outline" onClick={deleteRegistry} disabled={registrySaving || !selectedRegistry}>
            Delete
          </button>
        </div>
      </section>

      <div className="scm-impact-grid">
        <section className="panel scm-impact-card">
          <div className="scm-impact-card-header">
            <h4>Registry / SCM 상태</h4>
            <span className={`status-chip tone-${statusData?.status?.ok ? "success" : "info"}`}>
              {statusData?.status?.ok ? "Connected" : "Pending"}
            </span>
          </div>
          <div className="form-grid-2 compact">
            <label>등록 항목</label>
            <select value={selectedScmId} onChange={(e) => setSelectedScmId(e.target.value)} disabled={registryLoading}>
              <option value="">선택하세요</option>
              {registryItems.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} ({item.scm_type})
                </option>
              ))}
            </select>
            <label>SCM</label>
            <input value={selectedRegistry?.scm_type || scmMode || "-"} readOnly />
            <label>Source Root</label>
            <input value={selectedRegistry?.source_root || scmWorkdir || ""} readOnly />
            <label>Repo URL</label>
            <input value={selectedRegistry?.scm_url || scmRepoUrl || ""} readOnly />
            <label>Base Ref</label>
            <input value={selectedRegistry?.base_ref || scmRevision || ""} readOnly />
          </div>
          {!registryLoading && registryItems.length === 0 && (
            <div className="empty" style={{ marginTop: 12 }}>
              등록된 SCM 항목이 없습니다. registry를 먼저 등록해야 dry-run과 실행을 사용할 수 있습니다.
            </div>
          )}
          {statusData?.status && (
            <div className="scm-kpi-grid">
              <div className="scm-kpi-card">
                <div className="scm-kpi-label">Tool</div>
                <div className="scm-kpi-value">{statusData.status.tool_available ? "Available" : "Missing"}</div>
              </div>
              <div className="scm-kpi-card">
                <div className="scm-kpi-label">Working Copy</div>
                <div className="scm-kpi-value">{statusData.status.repo_detected ? "Detected" : "Not Detected"}</div>
              </div>
              <div className="scm-kpi-card">
                <div className="scm-kpi-label">Source Root</div>
                <div className="scm-kpi-value">{statusData.status.source_root_exists ? "Exists" : "Missing"}</div>
              </div>
              <div className="scm-kpi-card">
                <div className="scm-kpi-label">Password Env</div>
                <div className="scm-kpi-value">
                  {statusData.status.password_env_present ? "Present" : "Optional/Empty"}
                </div>
              </div>
            </div>
          )}
          {linkedDocItems.length > 0 && (
            <div className="scm-linked-list">
              <div className="detail-label">Linked Docs</div>
              {linkedDocItems.map((item) => (
                <div key={item.key} className="scm-linked-row">
                  <span className="status-chip tone-info">{item.key.toUpperCase()}</span>
                  <span className="list-text text-ellipsis">{basename(item.value)}</span>
                  <button type="button" className="btn-link" onClick={() => openFile(item.value)}>
                    열기
                  </button>
                  <button type="button" className="btn-link" onClick={() => copyPath(item.value, `${item.key.toUpperCase()} linked doc`)}>
                    복사
                  </button>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="panel scm-impact-card">
          <div className="scm-impact-card-header">
            <h4>Impact Trigger</h4>
            {impactLoading && <span className="status-chip tone-check">Running</span>}
          </div>
          <div className="row" style={{ gap: 12, flexWrap: "wrap", marginBottom: 10 }}>
            {ACTION_ORDER.map((target) => (
              <label key={target} className="row-inline">
                <input
                  type="checkbox"
                  checked={targets.includes(target)}
                  onChange={() => toggleTarget(target)}
                  disabled={impactLoading}
                />
                {target.toUpperCase()}
              </label>
            ))}
          </div>
          <label className="detail-label">수동 changed files</label>
          <textarea
            className="scm-impact-textarea"
            rows={7}
            value={manualChangedFiles}
            onChange={(e) => setManualChangedFiles(e.target.value)}
            disabled={impactLoading}
            placeholder={"Sources/APP/Ap_BuzzerCtrl_PDS.c\nSources/APP/Ap_BuzzerCtrl_it_PDS.h"}
          />
          <div className="hint">
            SVN working copy가 깨끗하면 여기에서 검증용 changed files를 직접 넣을 수 있습니다.
          </div>
          <div className="row" style={{ alignItems: "center", gap: 10, marginTop: 12 }}>
            <label style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", userSelect: "none" }}>
              <input
                type="checkbox"
                checked={autoGenerate}
                onChange={(e) => setAutoGenerate(e.target.checked)}
                disabled={impactLoading}
              />
              <span>자동 생성</span>
            </label>
            <span className="hint" style={{ fontSize: "0.78rem" }}>
              {autoGenerate ? "UDS/SUTS/SITS를 자동으로 재생성합니다" : "플래그만 세우고 문서는 재생성하지 않습니다"}
            </span>
          </div>
          <div className="row" style={{ gap: 8, marginTop: 8, flexWrap: "wrap" }}>
            <button type="button" className="btn-outline" disabled={impactLoading || !selectedScmId} onClick={() => triggerImpact(true)}>
              {impactLoading ? "분석 중..." : "Dry Run"}
            </button>
            <button type="button" disabled={impactLoading || !selectedScmId} onClick={() => triggerImpact(false)}>
              {impactLoading ? "실행 중..." : "실행"}
            </button>
          </div>
          {panelNotice && <div className="hint" style={{ marginTop: 10 }}>{panelNotice}</div>}
          {recommendedNextStep ? <div className="hint" style={{ marginTop: 6 }}>{recommendedNextStep}</div> : null}
          {impactError && <div className="scm-impact-error">{impactError}</div>}
          {impactErrorInfo ? (
            <div className="scm-warning-box" style={{ marginTop: 8 }}>
              <div><strong>{impactErrorInfo.title}</strong></div>
              {impactErrorInfo.detail ? <div style={{ marginTop: 4, whiteSpace: "pre-wrap" }}>{impactErrorInfo.detail}</div> : null}
              <div style={{ marginTop: 4 }} className="hint">
                {impactErrorInfo.retryable ? "재시도 가능" : "설정 확인 필요"}
                {impactErrorInfo.code ? ` 쨌 code: ${impactErrorInfo.code}` : ""}
              </div>
            </div>
          ) : null}
        </section>
      </div>
      </>
      ) : null}

      <section className="panel scm-impact-card">
        <div className="scm-impact-card-header">
          <h4>Dry Run / 실행 결과</h4>
          <span className={`status-chip tone-${impactResult?.dry_run ? "info" : "success"}`}>
            {impactResult ? (impactResult.dry_run ? "Dry Run" : "Real Run") : "Idle"}
          </span>
        </div>
        <div className="scm-kpi-grid">
          <div className="scm-kpi-card">
            <div className="scm-kpi-label">Changed Files</div>
            <div className="scm-kpi-value">{impactResult?.trigger?.changed_files?.length || changedFiles.length || 0}</div>
          </div>
          <div className="scm-kpi-card">
            <div className="scm-kpi-label">Changed Functions</div>
            <div className="scm-kpi-value">{changedFunctionEntries.length}</div>
          </div>
          <div className="scm-kpi-card">
            <div className="scm-kpi-label">Direct Impact</div>
            <div className="scm-kpi-value">{impactGroups.direct?.length || 0}</div>
          </div>
          <div className="scm-kpi-card">
            <div className="scm-kpi-label">Indirect</div>
            <div className="scm-kpi-value">
              {(impactGroups.indirect_1hop?.length || 0) + (impactGroups.indirect_2hop?.length || 0)}
            </div>
          </div>
        </div>

        {Array.isArray(impactResult?.warnings) && impactResult.warnings.length > 0 && (
          <div className="scm-warning-box">
            {impactResult.warnings.map((warning, idx) => (
              <div key={`${warning}-${idx}`}>- {warning}</div>
            ))}
          </div>
        )}

        <div className="scm-action-grid">
          {ACTION_ORDER.map((target) => {
            const info = impactResult?.actions?.[target] || { mode: "-", status: "skipped", function_count: 0 };
            const outputPath = info.output_path || info.result?.output_path || "";
            const artifactPath = info.artifact_path || "";
            return (
              <div key={target} className={`scm-action-card tone-${toneForAction(info)}`}>
                <div className="scm-action-head">
                  <strong>{target.toUpperCase()}</strong>
                  <span className={`status-chip tone-${toneForAction(info)}`}>
                    {String(info.mode || "-").toUpperCase()} / {String(info.status || "skipped")}
                  </span>
                </div>
                <div className="hint">{actionReason(target, info)}</div>
                <div className="detail-value">대상 함수: {info.function_count || 0}</div>
                {outputPath ? (
                  <div className="scm-path-row">
                    <span className="list-text text-ellipsis">{basename(outputPath)}</span>
                    <div className="row" style={{ gap: 6 }}>
                      <button type="button" className="btn-link" onClick={() => openFile(outputPath)} disabled={busy}>열기</button>
                      <button type="button" className="btn-link" onClick={() => openFolder(outputPath.replace(/[\\/][^\\/]+$/, ""))} disabled={busy}>폴더</button>
                    </div>
                  </div>
                ) : null}
                {artifactPath ? (
                  <div className="scm-path-row">
                    <span className="list-text text-ellipsis">{basename(artifactPath)}</span>
                    <div className="row" style={{ gap: 6 }}>
                      <button type="button" className="btn-link" onClick={() => previewArtifact(artifactPath)} disabled={busy}>미리보기</button>
                      <button type="button" className="btn-link" onClick={() => openFile(artifactPath)} disabled={busy}>열기</button>
                    </div>
                  </div>
                ) : null}
                {info.error && <div className="scm-impact-error">{info.error}</div>}
              </div>
            );
          })}
        </div>

        <div className="scm-impact-grid scm-impact-results-grid">
          <div className="scm-impact-subcard">
            <h5>Changed Functions</h5>
            <div className="list compact">
              {changedFunctionEntries.length > 0 ? (
                changedFunctionEntries.map(([func, kind]) => (
                  <div key={func} className="list-item">
                    <span className={`status-chip tone-${kind === "HEADER" ? "warning" : "info"}`}>{kind}</span>
                    <span className="list-text text-ellipsis">{func}</span>
                  </div>
                ))
              ) : (
                <div className="empty">변경 함수 정보 없음</div>
              )}
            </div>
          </div>
          <div className="scm-impact-subcard">
            <h5>Impact Groups</h5>
            <div className="list compact">
              {["direct", "indirect_1hop", "indirect_2hop"].map((key) => (
                <div key={key} className="list-item">
                  <span className="status-chip tone-info">{key}</span>
                  <span className="list-text">{impactGroups[key]?.length || 0} functions</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {(impactResult?.change_log?.summary || selectedChangeDetail?.summary) ? (
          <div className="scm-impact-grid scm-impact-results-grid" style={{ marginTop: 12 }}>
            <div className="scm-impact-subcard">
              <h5>Document Change Summary</h5>
              <div className="list compact">
                <div className="list-item">
                  <span className="status-chip tone-check">UDS</span>
                  <span className="list-text">{currentChangeSummary.uds_changed_functions || 0} functions changed</span>
                </div>
                <div className="list-item">
                  <span className="status-chip tone-check">SUTS</span>
                  <span className="list-text">
                    {currentChangeSummary.suts_changed_cases || 0} cases / {currentChangeSummary.suts_changed_sequences || 0} sequences
                  </span>
                </div>
                <div className="list-item">
                  <span className="status-chip tone-check">SITS</span>
                  <span className="list-text">
                    {currentChangeSummary.sits_test_cases || 0} TCs / {currentChangeSummary.sits_sub_cases || 0} sub-cases
                    {currentChangeSummary.sits_delta_cases ? ` (Δ${currentChangeSummary.sits_delta_cases > 0 ? "+" : ""}${currentChangeSummary.sits_delta_cases})` : ""}
                  </span>
                </div>
                <div className="list-item">
                  <span className="status-chip tone-warning">STS</span>
                  <span className="list-text">{currentChangeSummary.sts_flagged || 0} flagged</span>
                </div>
                <div className="list-item">
                  <span className="status-chip tone-warning">SDS</span>
                  <span className="list-text">{currentChangeSummary.sds_flagged || 0} flagged</span>
                </div>
              </div>
            </div>
            <div className="scm-impact-subcard">
              <h5>Change Log</h5>
              {impactResult?.change_log?.path ? (
                <div className="list compact">
                  <div className="list-item">
                    <span className="status-chip tone-info">run</span>
                    <span className="list-text text-ellipsis">{impactResult?.change_log?.run_id || "-"}</span>
                  </div>
                  <div className="list-item">
                    <span className="status-chip tone-info">file</span>
                    <span className="list-text text-ellipsis">{basename(impactResult?.change_log?.path)}</span>
                  </div>
                  <div className="row" style={{ gap: 8, marginTop: 8 }}>
                    <button type="button" className="btn-link" onClick={() => openFile(impactResult.change_log.path)} disabled={busy}>열기</button>
                    <button type="button" className="btn-link" onClick={() => copyPath(impactResult.change_log.path, "Change log")} disabled={busy}>복사</button>
                  </div>
                </div>
              ) : (
                <div className="empty">이번 실행의 change log가 아직 없습니다.</div>
              )}
            </div>
          </div>
        ) : null}
      </section>

      {(udsViewLoading || udsViewData || sutsViewLoading || sutsViewData || sitsViewLoading || sitsViewData) ? (
        <section className="panel scm-impact-card">
          <div className="scm-impact-card-header">
            <h4>AUTO Result Preview</h4>
            <span className="hint">{udsViewLoading || sutsViewLoading || sitsViewLoading ? "loading..." : "ready"}</span>
          </div>

          {activeUdsOutputPath ? (
            <div className="scm-impact-subcard" style={{ marginBottom: 16 }}>
              <div className="scm-impact-card-header">
                <h5>UDS</h5>
                <span className="hint">{basename(activeUdsOutputPath)}</span>
              </div>
              {udsViewLoading ? (
                <div className="empty">UDS preview loading...</div>
              ) : udsViewData ? (
                <>
                  <div className="scm-kpi-grid">
                    <div className="scm-kpi-card">
                      <div className="scm-kpi-label">Functions</div>
                      <div className="scm-kpi-value">
                        {udsViewData?.meta?.functions_total || udsViewData?.functions?.length || 0}
                      </div>
                    </div>
                    <div className="scm-kpi-card">
                      <div className="scm-kpi-label">Traceability</div>
                      <div className="scm-kpi-value">
                        {Array.isArray(udsViewData?.traceability) ? udsViewData.traceability.length : 0}
                      </div>
                    </div>
                    <div className="scm-kpi-card">
                      <div className="scm-kpi-label">Preview</div>
                      <div className="scm-kpi-value">{udsViewData?.preview_url ? "HTML" : "-"}</div>
                    </div>
                  </div>
                  <div className="row" style={{ gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                    {udsViewData?.download_url ? (
                      <a href={udsViewData.download_url} target="_blank" rel="noreferrer" className="btn-outline">
                        DOCX
                      </a>
                    ) : null}
                    {udsViewData?.preview_url ? (
                      <a href={udsViewData.preview_url} target="_blank" rel="noreferrer" className="btn-outline">
                        HTML Preview
                      </a>
                    ) : null}
                    {udsViewData?.accuracy_path ? (
                      <button type="button" className="btn-outline" onClick={() => previewArtifact(udsViewData.accuracy_path)}>
                        Accuracy
                      </button>
                    ) : null}
                    {udsViewData?.quality_gate_path ? (
                      <button type="button" className="btn-outline" onClick={() => previewArtifact(udsViewData.quality_gate_path)}>
                        Quality Gate
                      </button>
                    ) : null}
                    {udsViewData?.residual_tbd_report_path ? (
                      <button type="button" className="btn-outline" onClick={() => previewArtifact(udsViewData.residual_tbd_report_path)}>
                        Residual
                      </button>
                    ) : null}
                  </div>
                  {udsViewData?.preview_url ? (
                    <div className="scm-preview-frame-wrap">
                      <iframe title="uds-preview" src={udsViewData.preview_url} className="scm-preview-frame" />
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="empty">UDS output preview unavailable.</div>
              )}
            </div>
          ) : null}

          {activeSutsOutputPath ? (
            <div className="scm-impact-subcard">
              <div className="scm-impact-card-header">
                <h5>SUTS</h5>
                <span className="hint">{basename(activeSutsOutputPath)}</span>
              </div>
              {sutsViewLoading ? (
                <div className="empty">SUTS preview loading...</div>
              ) : sutsViewData ? (
                <ExcelArtifactViewer
                  artifactType="suts"
                  title="SUTS Generated Result"
                  viewData={sutsViewData}
                  previewData={sutsPreviewData}
                  previewLoading={sutsViewLoading}
                  previewSheet={sutsPreviewSheet}
                  onPreviewSheetChange={setSutsPreviewSheet}
                  onLoadPreview={() => loadSutsView(activeSutsOutputPath)}
                  files={[]}
                  filesLoading={false}
                  onRefreshFiles={() => loadSutsView(activeSutsOutputPath)}
                  onOpenFile={() => {}}
                />
              ) : (
                <div className="empty">SUTS output preview unavailable.</div>
              )}
            </div>
          ) : null}

          {activeSitsOutputPath ? (
            <div className="scm-impact-subcard">
              <div className="scm-impact-card-header">
                <h5>SITS</h5>
                <span className="hint">{basename(activeSitsOutputPath)}</span>
              </div>
              {sitsViewLoading ? (
                <div className="empty">SITS preview loading...</div>
              ) : sitsViewData ? (
                <ExcelArtifactViewer
                  artifactType="sits"
                  title="SITS Generated Result"
                  viewData={sitsViewData}
                  previewData={sitsPreviewData}
                  previewLoading={sitsViewLoading}
                  previewSheet={sitsPreviewSheet}
                  onPreviewSheetChange={setSitsPreviewSheet}
                  onLoadPreview={() => loadSitsView(activeSitsOutputPath)}
                  files={[]}
                  filesLoading={false}
                  onRefreshFiles={() => loadSitsView(activeSitsOutputPath)}
                  onOpenFile={() => {}}
                />
              ) : (
                <div className="empty">SITS output preview unavailable.</div>
              )}
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="panel scm-impact-card">
        <div className="scm-impact-card-header">
          <h4>Document Change History</h4>
          <span className="hint">{changeHistoryLoading ? "loading..." : `${changeHistoryItems.length} items`}</span>
        </div>
        <div className="scm-impact-grid scm-impact-results-grid">
          <div className="scm-impact-subcard">
            <div className="list compact">
              {changeHistoryItems.length > 0 ? (
                changeHistoryItems.map((item) => (
                  <div key={item.run_id} className="list-item">
                    <span className={`status-chip tone-${item.dry_run ? "info" : "success"}`}>{item.dry_run ? "DRY" : "RUN"}</span>
                    <span className="list-text text-ellipsis">{item.run_id}</span>
                    <span className="list-snippet">
                      UDS {item.summary?.uds_changed_functions || 0} / SUTS {item.summary?.suts_changed_cases || 0} / SITS {item.summary?.sits_test_cases || 0}
                    </span>
                    <button
                      type="button"
                      className="btn-link"
                      onClick={() => setSelectedChangeRunId(item.run_id)}
                      disabled={busy}
                    >
                      상세
                    </button>
                  </div>
                ))
              ) : (
                <div className="empty">문서 변경 이력이 없습니다.</div>
              )}
            </div>
          </div>
          <div className="scm-impact-subcard">
            <h5>Selected Change Detail</h5>
            {selectedChangeDetail ? (
              <div className="list compact">
                <div className="list-item">
                  <span className="status-chip tone-info">run</span>
                  <span className="list-text text-ellipsis">{selectedChangeDetail.run_id || "-"}</span>
                </div>
                <div className="list-item">
                  <span className="status-chip tone-check">UDS</span>
                  <span className="list-text">{selectedChangeDetail.summary?.uds_changed_functions || 0} functions changed</span>
                </div>
                <div className="list-item">
                  <span className="status-chip tone-check">SUTS</span>
                  <span className="list-text">
                    {selectedChangeDetail.summary?.suts_changed_cases || 0} cases / {selectedChangeDetail.summary?.suts_changed_sequences || 0} sequences
                  </span>
                </div>
                <div className="list-item">
                  <span className="status-chip tone-check">SITS</span>
                  <span className="list-text">
                    {selectedChangeDetail.summary?.sits_test_cases || 0} TCs / {selectedChangeDetail.summary?.sits_sub_cases || 0} sub-cases
                  </span>
                </div>
                <div className="list-item">
                  <span className="status-chip tone-warning">STS</span>
                  <span className="list-text">{selectedChangeDetail.summary?.sts_flagged || 0} flagged</span>
                </div>
                <div className="list-item">
                  <span className="status-chip tone-warning">SDS</span>
                  <span className="list-text">{selectedChangeDetail.summary?.sds_flagged || 0} flagged</span>
                </div>
                <div className="list-item">
                  <span className="status-chip tone-info">files</span>
                  <span className="list-text">{Array.isArray(selectedChangeDetail.changed_files) ? selectedChangeDetail.changed_files.length : 0}</span>
                </div>
                <div className="row" style={{ gap: 8, marginTop: 8 }}>
                  <button
                    type="button"
                    className="btn-link"
                    onClick={() => {
                      const changedFiles = Array.isArray(selectedChangeDetail.changed_files) && selectedChangeDetail.changed_files.length > 0
                        ? selectedChangeDetail.changed_files.map((value) => `- \`${value}\``).join("\n")
                        : "- 없음";
                      const changedFunctions = Object.entries(selectedChangeDetail.changed_functions || {}).length > 0
                        ? Object.entries(selectedChangeDetail.changed_functions || {}).map(([name, kind]) => `- \`${name}\` : \`${kind}\``).join("\n")
                        : "- 없음";
                      const md = [
                        "# Document Change Detail",
                        "",
                        `- Run: \`${selectedChangeDetail.run_id || "-"}\``,
                        `- Trigger: \`${selectedChangeDetail.trigger || "-"}\``,
                        "",
                        "## Changed Files",
                        changedFiles,
                        "",
                        "## Changed Functions",
                        changedFunctions,
                      ].join("\n");
                      setReviewTab("summary");
                      setArtifactPreview({ path: selectedChangeDetail.run_id || "", text: md, truncated: false });
                    }}
                    disabled={busy}
                  >
                    미리보기
                  </button>
                </div>
              </div>
            ) : (
              <div className="empty">선택된 변경 이력이 없습니다.</div>
            )}
          </div>
        </div>
      </section>

      <section className="panel scm-impact-card">
        <div className="scm-impact-card-header">
          <h4>Document Diff Preview</h4>
          <span className="hint">{selectedChangeDetail?.run_id || "select change history item"}</span>
        </div>
        {selectedChangeDetail ? (
          <>
            <div className="scm-impact-grid scm-impact-results-grid">
              <div className="scm-impact-subcard">
                <h5>UDS Diff</h5>
                <div className="list compact">
                  {selectedUdsDiff.length > 0 ? (
                    selectedUdsDiff.map((row) => (
                      <div key={`uds-${row.name}`} className="list-item">
                        <span className="status-chip tone-check">{(row.fields_changed || []).length} fields</span>
                        <span className="list-text text-ellipsis">{row.name}</span>
                        <span className="list-snippet">{(row.fields_changed || []).join(", ") || "-"}</span>
                      </div>
                    ))
                  ) : (
                    <div className="empty">UDS diff 정보가 없습니다.</div>
                  )}
                </div>
                {selectedUdsDiff.length > 0 ? (
                  <div className="list compact" style={{ marginTop: 8 }}>
                    {selectedUdsDiff.slice(0, 5).map((row) => (
                      <div key={`uds-summary-${row.name}`} className="list-item">
                        <span className="status-chip tone-info">summary</span>
                        <span className="list-text text-ellipsis">{row.name}</span>
                        <span className="list-snippet">{summarizeUdsDiff(row)}</span>
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
              <div className="scm-impact-subcard">
                <h5>SUTS Diff</h5>
                <div className="list compact">
                  {selectedSutsDiff.length > 0 ? (
                    selectedSutsDiff.map((row, idx) => (
                      <div key={`suts-${row.function || idx}`} className="list-item">
                        <span className="status-chip tone-check">{row.change_type || "updated"}</span>
                        <span className="list-text text-ellipsis">{row.function || "-"}</span>
                      </div>
                    ))
                  ) : (
                    <div className="empty">SUTS diff 정보가 없습니다.</div>
                  )}
                </div>
              </div>
            </div>
            <div className="scm-impact-subcard" style={{ marginTop: 12 }}>
              <h5>Review Reason</h5>
              <div className="list compact">
                <div className="list-item">
                  <span className="status-chip tone-warning">STS</span>
                  <span className="list-text">{selectedReviewReasons.sts.length > 0 ? selectedReviewReasons.sts.join(", ") : "없음"}</span>
                </div>
                <div className="list-item">
                  <span className="status-chip tone-warning">SDS</span>
                  <span className="list-text">{selectedReviewReasons.sds.length > 0 ? selectedReviewReasons.sds.join(", ") : "없음"}</span>
                </div>
              </div>
            </div>
          </>
        ) : (
          <div className="empty">먼저 Document Change History에서 실행 이력을 선택하세요.</div>
        )}
      </section>

      <section className="panel scm-impact-card">
        <div className="scm-impact-card-header">
          <h4>Recent Runs</h4>
          <span className="hint">{auditLoading ? "loading..." : `${auditItems.length} items`}</span>
        </div>
        <div className="list compact">
          {auditItems.length > 0 ? (
            auditItems.map((item) => (
              <div key={item.path} className="list-item">
                <span className={`status-chip tone-${item.dry_run ? "info" : item.failed_count > 0 ? "failed" : item.flag_count > 0 ? "warning" : "success"}`}>
                  {item.dry_run ? "DRY" : "RUN"}
                </span>
                <span className="list-text text-ellipsis">
                  {item.filename} · files {Array.isArray(item.changed_files) ? item.changed_files.length : 0}
                </span>
                <span className="list-snippet">AUTO {item.auto_count} / FLAG {item.flag_count}</span>
                <div className="row" style={{ gap: 6 }}>
                  <button type="button" className="btn-link" onClick={() => setCompareAuditPath(item.path)} disabled={busy}>비교기준</button>
                  <button type="button" className="btn-link" onClick={() => previewAuditItem(item)} disabled={busy}>요약</button>
                  <button type="button" className="btn-link" onClick={() => openFile(item.path)} disabled={busy}>열기</button>
                </div>
              </div>
            ))
          ) : (
            <div className="empty">최근 실행 이력이 없습니다.</div>
          )}
        </div>
      </section>

      {runComparison ? (
        <section className="panel scm-impact-card">
          <div className="scm-impact-card-header">
            <h4>Run Comparison</h4>
            <span className="hint">{runComparison.currentLabel} vs {runComparison.baselineLabel}</span>
          </div>
          <div className="scm-impact-grid scm-impact-results-grid">
            <div className="scm-impact-subcard">
              <h5>Files</h5>
              <div className="list compact">
                {runComparison.addedFiles.length > 0 ? runComparison.addedFiles.map((item) => (
                  <div key={`add-file-${item}`} className="list-item">
                    <span className="status-chip tone-check">added</span>
                    <span className="list-text text-ellipsis">{item}</span>
                  </div>
                  )) : <div className="empty">추가 파일 없음</div>}
                {runComparison.removedFiles.map((item) => (
                  <div key={`remove-file-${item}`} className="list-item">
                    <span className="status-chip tone-warning">removed</span>
                    <span className="list-text text-ellipsis">{item}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="scm-impact-subcard">
              <h5>Changed Functions</h5>
              <div className="list compact">
                {runComparison.addedFunctions.length > 0 ? runComparison.addedFunctions.map((item) => (
                  <div key={`add-func-${item}`} className="list-item">
                    <span className="status-chip tone-check">added</span>
                    <span className="list-text text-ellipsis">{item}</span>
                  </div>
                )) : <div className="empty">추가 함수 없음</div>}
                {runComparison.removedFunctions.map((item) => (
                  <div key={`remove-func-${item}`} className="list-item">
                    <span className="status-chip tone-warning">removed</span>
                    <span className="list-text text-ellipsis">{item}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="scm-impact-subcard" style={{ marginTop: 12 }}>
            <h5>Action Changes</h5>
            <div className="list compact">
              {runComparison.changedActions.length > 0 ? runComparison.changedActions.map((item) => (
                <div key={`action-${item.target}`} className="list-item">
                  <span className="status-chip tone-info">{item.target.toUpperCase()}</span>
                  <span className="list-text">
                    {item.baselineMode}/{item.baselineStatus} → {item.currentMode}/{item.currentStatus}
                  </span>
                </div>
              )) : <div className="empty">액션 차이 없음</div>}
            </div>
          </div>
        </section>
      ) : null}

      <section className="panel scm-impact-card">
        <div className="scm-impact-card-header">
          <h4>Review Artifact Preview</h4>
          {artifactPreview.path ? <span className="hint">{basename(artifactPreview.path)}</span> : null}
        </div>
        {artifactPreviewLoading ? (
          <div className="empty">리뷰 문서를 불러오는 중...</div>
        ) : artifactPreview.text ? (
          <>
            <div className="scm-review-toolbar">
              <div className="scm-review-tabs">
                {REVIEW_TABS.map((tab) => (
                  <button
                    key={tab.key}
                    type="button"
                    className={`btn-link scm-review-tab ${reviewTab === tab.key ? "active" : ""}`}
                    onClick={() => setReviewTab(tab.key)}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              <div className="scm-review-meta">
                <span className="status-chip tone-info">Functions {reviewCounts.functions}</span>
                <span className="status-chip tone-warning">Requirements {reviewCounts.requirements}</span>
                <span className="status-chip tone-check">Checklist {reviewCounts.checklist}</span>
              </div>
            </div>
            <div className="scm-impact-grid scm-impact-results-grid" style={{ marginBottom: 12 }}>
              <div className="scm-impact-subcard">
                <h5>Quick Jump</h5>
                <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                  <button type="button" className="btn-outline" onClick={() => setReviewTab("functions")}>Changed Functions</button>
                  <button type="button" className="btn-outline" onClick={() => setReviewTab("requirements")}>Requirements</button>
                  <button type="button" className="btn-outline" onClick={() => setReviewTab("checklist")}>Checklist</button>
                </div>
              </div>
              <div className="scm-impact-subcard">
                <h5>Review Scope</h5>
                <div className="list compact">
                  <div className="list-item"><span className="status-chip tone-info">files</span><span className="list-text">{reviewCounts.sourceFiles}</span></div>
                  <div className="list-item"><span className="status-chip tone-warning">req</span><span className="list-text">{reviewCounts.requirements}</span></div>
                  <div className="list-item"><span className="status-chip tone-check">check</span><span className="list-text">{reviewCounts.checklist}</span></div>
                </div>
              </div>
            </div>
            <ReportMarkdownPreview text={reviewTabContent || artifactPreview.text} />
            {artifactPreview.truncated && <div className="hint">미리보기는 일부만 표시됩니다.</div>}
          </>
        ) : (
          <div className="empty">STS/SDS review artifact가 생성되면 여기에서 바로 확인할 수 있습니다.</div>
        )}
      </section>

      <details className="panel scm-impact-card" open={false}>
        <summary>Legacy SCM Commands</summary>
        <div className="form-grid-2 compact" style={{ marginTop: 12 }}>
          <label>SCM</label>
          <select value={scmMode} onChange={(e) => setScmMode(e.target.value)}>
            <option value="git">Git</option>
            <option value="svn">SVN</option>
          </select>
          <label>작업 디렉터리</label>
          <input value={scmWorkdir} onChange={(e) => setScmWorkdir(e.target.value)} placeholder="작업 디렉터리" />
          <label>Repo URL</label>
          <input value={scmRepoUrl} onChange={(e) => setScmRepoUrl(e.target.value)} />
          {scmMode === "git" ? (
            <>
              <label>Branch</label>
              <input value={scmBranch} onChange={(e) => setScmBranch(e.target.value)} />
              <label>Depth</label>
              <input type="number" min={0} value={scmDepth} onChange={(e) => setScmDepth(Number(e.target.value))} />
            </>
          ) : (
            <>
              <label>Revision</label>
              <input value={scmRevision} onChange={(e) => setScmRevision(e.target.value)} />
              <span />
              <span />
            </>
          )}
        </div>
        <div className="row" style={{ marginTop: 12, flexWrap: "wrap" }}>
          {scmMode === "git" && (
            <>
              <button onClick={() => runScm("clone")}>Clone</button>
              <button onClick={() => runScm("fetch")}>Fetch</button>
              <button onClick={() => runScm("pull")}>Pull</button>
              <button onClick={() => runScm("checkout")}>Checkout</button>
            </>
          )}
          {scmMode === "svn" && (
            <>
              <button onClick={() => runScm("checkout")}>Checkout</button>
              <button onClick={() => runScm("update")}>Update</button>
              <button onClick={() => runScm("info")}>Info</button>
            </>
          )}
        </div>
        <pre className="json">{scmOutput || ""}</pre>
      </details>
    </div>
  );
};

export default LocalScmPanel;

