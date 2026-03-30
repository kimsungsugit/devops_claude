import { useEffect, useMemo, useRef, useState } from "react";
import {
  RelatedList,
  LocalReportSummaryPanel,
  DashboardStatusCards,
  RiskScorePanel,
} from "../components/dashboard";
import { normalizePct, formatPct, toneForStatus } from "../utils/ui";

const LocalDashboard = ({
  status,
  summary,
  findings,
  logs,
  history,
  complexityRows,
  loadComplexity,
  detailTabs,
  detailTab,
  onDetailTabChange,
  handleCardClick,
  staticCounts,
  config,
  onOpenEditorFile,
  onWorkflowTabChange,
  localReportSummaries,
  loadLocalReportSummary,
  localReportComparisons,
  kbEntries,
  loadKbEntries,
}) => {
  const stat = staticCounts();
  const impact = summary?.change_impact || {};
  const preflight = summary?.preflight || {};
  const health = summary?.report_health || {};
  const tests = summary?.tests || {};
  const coverage = summary?.coverage || {};
  const agent = summary?.agent || {};
  const scm = summary?.scm || {};

  const kbAutoLoadedRef = useRef(false);
  const [kbSearch, setKbSearch] = useState("");
  const [kbCatFilter, setKbCatFilter] = useState("all");

  useEffect(() => {
    kbAutoLoadedRef.current = false;
  }, [config?.project_root, config?.report_dir]);

  // 지식베이스 로드
  useEffect(() => {
    if (!loadKbEntries) return;
    if (!config?.project_root || !config?.report_dir) return;
    if (kbAutoLoadedRef.current) return;
    if (!kbEntries || kbEntries.length === 0) {
      kbAutoLoadedRef.current = true;
      loadKbEntries();
    }
  }, [loadKbEntries, kbEntries, config?.project_root, config?.report_dir]);

  const activeDetail = detailTabs.find((tab) => tab.key === detailTab);
  const coverageLine = Number(coverage.line_rate_pct || 0);
  const coverageBranch = Number(coverage.branch_rate_pct || 0);
  const coverageFunc = Number(coverage.function_rate_pct || coverage.function_rate || coverage.func_rate || 0);
  const coverageWarnThreshold = Number(config?.coverage_warn_pct ?? 80);
  const coverageFailThreshold = Number(config?.coverage_fail_pct ?? 50);
  const testsMinCount = Number(config?.tests_min_count ?? 1);
  const requireTestsEnabled = config?.require_tests_enabled !== false;
  const buildOk = summary?.build?.ok;
  const syntaxOk = summary?.syntax?.ok;
  const testsEnabled = !!tests.enabled;
  const testsCount = Number(tests.total || tests.count || 0);
  const [metricFilters, setMetricFilters] = useState({
    build: true,
    tests: true,
    coverage: true,
    static: true,
  });
  const riskWeights = {
    error: 6,
    warning: 2,
    buildFail: 20,
    syntaxFail: 10,
    testsOff: 10,
    healthWarning: 2,
    healthMissing: 4,
  };

  const classifySeverity = (item) => {
    const raw = String(
      item?.severity ||
        item?.level ||
        item?.priority ||
        item?.kind ||
        item?.type ||
        "",
    ).toLowerCase();
    if (raw.includes("error") || raw.includes("critical")) return "error";
    if (raw.includes("warn")) return "warning";
    return "info";
  };

  const severityCounts = useMemo(() => (findings || []).reduce(
    (acc, item) => {
      const sev = classifySeverity(item);
      acc[sev] += 1;
      return acc;
    },
    { error: 0, warning: 0, info: 0 },
  ), [findings]);
  const warningsCount = severityCounts.warning;
  const errorsCount = severityCounts.error;

  const topComplexity = useMemo(() => {
    if (!Array.isArray(complexityRows) || complexityRows.length === 0)
      return [];
    return [...complexityRows]
      .map((row) => ({
        file: row?.file || "",
        func: row?.function || row?.func || "",
        ccn: Number(row?.ccn || 0),
        nloc: Number(row?.nloc || 0),
        line:
          Number(
            row?.line ||
              row?.line_number ||
              row?.location?.line ||
              row?.start_line ||
              0,
          ) || null,
      }))
      .filter((row) => row.file && row.func)
      .sort((a, b) => b.ccn - a.ccn)
      .slice(0, 10);
  }, [complexityRows]);

  // 복잡도 히트맵 데이터 (파일별 그룹화)
  const complexityHeatmap = useMemo(() => {
    if (!Array.isArray(complexityRows) || complexityRows.length === 0)
      return [];
    const fileMap = new Map();
    complexityRows.forEach((row) => {
      const file = row?.file || "";
      if (!file) return;
      const ccn = Number(row?.ccn || 0);
      if (!fileMap.has(file)) {
        fileMap.set(file, {
          file,
          maxCcn: 0,
          avgCcn: 0,
          count: 0,
          totalCcn: 0,
        });
      }
      const entry = fileMap.get(file);
      entry.maxCcn = Math.max(entry.maxCcn, ccn);
      entry.totalCcn += ccn;
      entry.count += 1;
      entry.avgCcn = entry.totalCcn / entry.count;
    });
    return Array.from(fileMap.values())
      .sort((a, b) => b.maxCcn - a.maxCcn)
      .slice(0, 20); // 상위 20개 파일
  }, [complexityRows]);

  // Code Quality 메트릭 (정적 분석 도구별)
  const codeQualityMetrics = useMemo(() => {
    const staticTools = summary?.static || {};
    const cppcheck = staticTools.cppcheck || {};
    const clangTidy = staticTools.clang_tidy || {};
    const semgrep = staticTools.semgrep || {};

    return {
      cppcheck: {
        ok: cppcheck.ok,
        issues: cppcheck.data?.issues?.length || cppcheck.issues?.length || 0,
        errors: (cppcheck.data?.issues || cppcheck.issues || []).filter((i) =>
          String(i?.severity || "")
            .toLowerCase()
            .includes("error"),
        ).length,
        warnings: (cppcheck.data?.issues || cppcheck.issues || []).filter((i) =>
          String(i?.severity || "")
            .toLowerCase()
            .includes("warn"),
        ).length,
      },
      clangTidy: {
        ok: clangTidy.ok,
        issues: clangTidy.data?.issues?.length || clangTidy.issues?.length || 0,
        errors: (clangTidy.data?.issues || clangTidy.issues || []).filter((i) =>
          String(i?.severity || "")
            .toLowerCase()
            .includes("error"),
        ).length,
        warnings: (clangTidy.data?.issues || clangTidy.issues || []).filter(
          (i) =>
            String(i?.severity || "")
              .toLowerCase()
              .includes("warn"),
        ).length,
      },
      semgrep: {
        ok: semgrep.ok,
        issues: semgrep.data?.issues?.length || semgrep.issues?.length || 0,
        errors: (semgrep.data?.issues || semgrep.issues || []).filter((i) =>
          String(i?.severity || "")
            .toLowerCase()
            .includes("error"),
        ).length,
        warnings: (semgrep.data?.issues || semgrep.issues || []).filter((i) =>
          String(i?.severity || "")
            .toLowerCase()
            .includes("warn"),
        ).length,
      },
    };
  }, [summary]);

  const complexityThreshold = Number(config?.complexity_threshold ?? 10);

  const metricCards = useMemo(() => {
    const build = summary?.build || {};
    const testsOk = build?.data?.tests_ok ?? summary?.tests?.ok;
    const testRounds = build?.data?.ctest_results?.length || 0;
    const testsValue =
      testsOk === true
        ? "성공"
        : testsOk === false
          ? "실패"
          : testRounds > 0
            ? "실행됨"
            : testsEnabled
              ? "실행됨"
              : "없음";
    const testsTone =
      testsOk === true ? "success" : testsOk === false ? "failed" : "info";

    const coverageValue = formatPct(
      coverage.line_rate || coverage.line_rate_pct || coverageLine,
    );
    const coverageTone = coverage?.enabled
      ? coverage?.below_threshold
        ? "failed"
        : coverage?.ok === false
          ? "warning"
          : "success"
      : "info";

    const staticTools = Object.values(summary?.static || {});
    const staticTotal = staticTools.length;
    const staticFailures = staticTools.filter(
      (tool) => tool?.ok === false,
    ).length;
    const staticValue = staticTotal
      ? `${staticTotal - staticFailures}/${staticTotal}`
      : "-";
    const staticTone =
      staticFailures > 0 ? "warning" : staticTotal > 0 ? "success" : "info";

    const issueTotal =
      severityCounts.error + severityCounts.warning + severityCounts.info;
    const issueTone =
      severityCounts.error > 0
        ? "failed"
        : severityCounts.warning > 0
          ? "warning"
          : issueTotal > 0
            ? "success"
            : "info";
    const maxCcn = topComplexity[0]?.ccn;

    const complexityTone = Number.isFinite(maxCcn)
      ? maxCcn >= complexityThreshold
        ? "warning"
        : "success"
      : "info";

    return [
      {
        label: "빌드",
        value:
          build?.ok === true ? "성공" : build?.ok === false ? "실패" : "없음",
        tone:
          build?.ok === false
            ? "failed"
            : build?.ok === true
              ? "success"
              : "info",
        category: "build",
        navigate: "logs",
      },
      {
        label: "테스트",
        value: testsValue,
        tone: testsTone,
        hint: testRounds ? `${testRounds} 라운드` : "",
        category: "tests",
        navigate: "testing",
        progressPct: testsOk === true ? 100 : testsOk === false ? 30 : null,
      },
      {
        label: "커버리지",
        value: coverageValue,
        tone: coverageTone,
        hint:
          coverage?.threshold != null
            ? `기준 ${formatPct(coverage.threshold)}`
            : "",
        category: "coverage",
        navigate: "testing",
        progressPct: coverageLine != null ? coverageLine : null,
        threshold: coverage?.threshold != null ? Number(coverage.threshold) : null,
      },
      {
        label: "정적분석",
        value: staticValue,
        tone: staticTone,
        hint: staticTotal ? "성공/전체" : "도구 없음",
        category: "static",
        navigate: "quality",
        progressPct: staticTotal ? ((staticTotal - staticFailures) / staticTotal) * 100 : null,
      },
      {
        label: "이슈",
        value: issueTotal ? `${issueTotal}건` : "없음",
        tone: issueTone,
        hint: issueTotal
          ? `E${severityCounts.error} W${severityCounts.warning}`
          : "",
        category: "issues",
        navigate: "quality",
        stackBars: issueTotal > 0 ? [
          { pct: (severityCounts.error / issueTotal) * 100, cls: 'bar-fill-error' },
          { pct: (severityCounts.warning / issueTotal) * 100, cls: 'bar-fill-warn' },
          { pct: (severityCounts.info / issueTotal) * 100, cls: 'bar-fill-info' },
        ] : null,
      },
      {
        label: "복잡도",
        value: Number.isFinite(maxCcn) ? `최대 ${maxCcn}` : "-",
        tone: complexityTone,
        hint: Number.isFinite(maxCcn) ? `경고 ${complexityThreshold}+` : "",
        category: "complexity",
        navigate: "complexity",
        progressPct: Number.isFinite(maxCcn) ? Math.min(100, (maxCcn / Math.max(complexityThreshold * 2, 1)) * 100) : null,
      },
    ];
  }, [
    complexityThreshold,
    coverage,
    coverageLine,
    severityCounts.error,
    severityCounts.warning,
    severityCounts.info,
    summary,
    testsEnabled,
    topComplexity,
  ]);

  const metricGroupForKey = (key) => {
    if (!key) return null;
    const lower = String(key).toLowerCase();
    if (lower.includes(".build") || lower.includes(".syntax")) return "build";
    if (lower.includes(".tests") || lower.includes(".qemu")) return "tests";
    if (lower.includes(".coverage")) return "coverage";
    if (lower.includes(".static")) return "static";
    return null;
  };

  const metricDetails = useMemo(() => {
    const entries = [];
    const maxEntries = 220;
    const maxDepth = 4;
    const maxString = 120;
    const omitFragments = ["log", "stderr", "stdout", "trace", "stack"];
    const add = (key, value) => {
      if (entries.length >= maxEntries) return;
      entries.push({ key, value });
    };
    const walk = (value, path, depth) => {
      if (entries.length >= maxEntries) return;
      if (value == null) {
        add(path, "-");
        return;
      }
      if (typeof value === "string") {
        const trimmed = value.replace(/\s+/g, " ").trim();
        if (!trimmed && trimmed !== "") return;
        add(
          path,
          trimmed.length > maxString
            ? `${trimmed.slice(0, maxString)}…`
            : trimmed,
        );
        return;
      }
      if (typeof value === "number" || typeof value === "boolean") {
        add(path, String(value));
        return;
      }
      if (Array.isArray(value)) {
        if (value.length === 0) {
          add(path, "[]");
          return;
        }
        const isPrimitive = value.every(
          (item) =>
            item == null ||
            ["string", "number", "boolean"].includes(typeof item),
        );
        if (isPrimitive && value.length <= 8) {
          add(path, value.map((item) => String(item)).join(", "));
          return;
        }
        add(path, `[${value.length}]`);
        return;
      }
      if (typeof value === "object") {
        if (depth >= maxDepth) {
          add(path, "{...}");
          return;
        }
        Object.entries(value).forEach(([key, val]) => {
          const next = path ? `${path}.${key}` : key;
          const lower = key.toLowerCase();
          if (
            omitFragments.some((frag) => lower.includes(frag)) &&
            typeof val === "string" &&
            val.length > maxString
          ) {
            return;
          }
          walk(val, next, depth + 1);
        });
      }
    };
    walk({ status, summary }, "report", 0);
    return entries;
  }, [status, summary]);

  const filteredMetricDetails = useMemo(
    () =>
      metricDetails.filter((item) => {
        const group = metricGroupForKey(item.key);
        if (!group) return true;
        return metricFilters[group];
      }),
    [metricDetails, metricFilters],
  );

  const visibleMetricCards = useMemo(
    () =>
      metricCards.filter((card) => {
        if (["build", "tests", "coverage", "static"].includes(card.category)) {
          return metricFilters[card.category];
        }
        return true;
      }),
    [metricCards, metricFilters],
  );

  const metricSummaryItems = useMemo(() => {
    const labelMap = {
      정적분석: "정적",
    };
    const navigateMap = metricCards.reduce((acc, card) => {
      acc[card.label] = card.navigate || null;
      return acc;
    }, {});
    return metricCards
      .filter((card) =>
        ["빌드", "테스트", "커버리지", "정적분석", "복잡도"].includes(
          card.label,
        ),
      )
      .map((card) => ({
        label: labelMap[card.label] || card.label,
        value: card.value,
        tone: card.tone,
        navigate: navigateMap[card.label],
      }));
  }, [metricCards]);

  const maxMetricChips = 5;
  const visibleMetricChips = metricSummaryItems.slice(0, maxMetricChips);
  const extraMetricCount = Math.max(
    0,
    metricSummaryItems.length - maxMetricChips,
  );

  const ruleGroupOf = (item) => {
    const candidate = [
      item?.rule_id,
      item?.rule,
      item?.check_id,
      item?.check,
      item?.id,
      item?.code,
      item?.pattern_id,
      item?.title,
    ]
      .map((v) => (typeof v === "string" ? v.trim() : ""))
      .find((v) => v);
    if (!candidate) return "misc";
    if (candidate.includes("/")) return candidate.split("/")[0];
    if (candidate.includes(":")) return candidate.split(":")[0];
    if (candidate.includes("."))
      return candidate.split(".").slice(0, 2).join(".");
    return candidate.slice(0, 24);
  };

  const toolBuckets = useMemo(() => (findings || []).reduce((acc, item) => {
    const tool =
      String(item?.tool || "unknown")
        .toLowerCase()
        .trim() || "unknown";
    acc[tool] = acc[tool] || { error: 0, warning: 0, info: 0, total: 0 };
    const sev = classifySeverity(item);
    acc[tool][sev] += 1;
    acc[tool].total += 1;
    return acc;
  }, {}), [findings]);

  const toolRuleBuckets = useMemo(() => (findings || []).reduce((acc, item) => {
    const tool =
      String(item?.tool || "unknown")
        .toLowerCase()
        .trim() || "unknown";
    const group = ruleGroupOf(item);
    acc[tool] = acc[tool] || {};
    acc[tool][group] = (acc[tool][group] || 0) + 1;
    return acc;
  }, {}), [findings]);

  const ruleGroupTotals = useMemo(() => (findings || []).reduce((acc, item) => {
    const group = ruleGroupOf(item);
    acc[group] = (acc[group] || 0) + 1;
    return acc;
  }, {}), [findings]);

  const topTools = useMemo(() => Object.entries(toolBuckets)
    .sort((a, b) => b[1].total - a[1].total)
    .slice(0, 5), [toolBuckets]);

  const topRuleGroups = useMemo(() => Object.entries(ruleGroupTotals)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([key]) => key), [ruleGroupTotals]);

  const maxRuleCell = useMemo(() => Math.max(
    1,
    ...topTools.flatMap(([tool]) =>
      topRuleGroups.map((group) => toolRuleBuckets[tool]?.[group] || 0),
    ),
  ), [topTools, topRuleGroups, toolRuleBuckets]);

  const parseTimestamp = (value) => {
    if (!value) return null;
    const raw = String(value);
    const bracket = raw.match(/\[(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\]/);
    const plain = raw.match(/(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})/);
    const candidate = (bracket && bracket[1]) || (plain && plain[1]);
    if (!candidate) return null;
    const dt = new Date(candidate.replace(" ", "T"));
    return Number.isNaN(dt.getTime()) ? null : dt;
  };

  const extractEntryTime = (entry) => {
    if (!entry) return null;
    if (typeof entry === "string") return parseTimestamp(entry);
    return (
      parseTimestamp(entry.time) ||
      parseTimestamp(entry.timestamp) ||
      parseTimestamp(entry.created_at) ||
      parseTimestamp(entry.generated_at)
    );
  };

  const buildHourlySeries = (items, limit = 12) => {
    const now = new Date();
    const buckets = Array.from({ length: limit }, (_, idx) => {
      const d = new Date(now.getTime() - (limit - 1 - idx) * 60 * 60 * 1000);
      const label = `${String(d.getHours()).padStart(2, "0")}:00`;
      return { label, count: 0, start: d.getTime() };
    });
    const startAt = buckets[0]?.start || 0;
    for (const entry of items || []) {
      const dt = extractEntryTime(entry);
      if (!dt) continue;
      const time = dt.getTime();
      if (time < startAt) continue;
      const diff = Math.floor((time - startAt) / (60 * 60 * 1000));
      if (diff >= 0 && diff < buckets.length) buckets[diff].count += 1;
    }
    return buckets;
  };

  const logSeries = useMemo(() => buildHourlySeries(logs, 12), [logs]);
  const maxLogCount = useMemo(() => Math.max(1, ...logSeries.map((item) => item.count)), [logSeries]);

  const classifyRunState = (entry) => {
    const rawState = String(
      entry?.state || entry?.status || entry?.phase || "",
    ).toLowerCase();
    if (rawState.includes("run")) return "running";
    if (rawState.includes("success") || rawState.includes("complete"))
      return "success";
    if (rawState.includes("fail") || rawState.includes("error")) return "fail";
    if (entry?.build_ok === true || entry?.exit_code === 0) return "success";
    if (entry?.build_ok === false || Number(entry?.exit_code || 0) > 0)
      return "fail";
    return "running";
  };

  const buildStatusSeries = (items, limit = 12) => {
    const now = new Date();
    const buckets = Array.from({ length: limit }, (_, idx) => {
      const d = new Date(now.getTime() - (limit - 1 - idx) * 60 * 60 * 1000);
      const label = `${String(d.getHours()).padStart(2, "0")}:00`;
      return { label, running: 0, success: 0, fail: 0, start: d.getTime() };
    });
    const startAt = buckets[0]?.start || 0;
    for (const entry of items || []) {
      const dt = extractEntryTime(entry);
      if (!dt) continue;
      const time = dt.getTime();
      if (time < startAt) continue;
      const diff = Math.floor((time - startAt) / (60 * 60 * 1000));
      if (diff >= 0 && diff < buckets.length) {
        const state = classifyRunState(entry);
        buckets[diff][state] += 1;
      }
    }
    return buckets;
  };

  const statusSeries = useMemo(() => buildStatusSeries(history, 12), [history]);
  const maxStatusCount = useMemo(() => Math.max(
    1,
    ...statusSeries.map((item) => item.running + item.success + item.fail),
  ), [statusSeries]);

  const riskBreakdown = useMemo(() => {
    const items = [
      { label: "Error 이슈", penalty: severityCounts.error * riskWeights.error, count: severityCounts.error },
      { label: "Warning 이슈", penalty: severityCounts.warning * riskWeights.warning, count: severityCounts.warning },
      { label: "빌드 실패", penalty: buildOk === false ? riskWeights.buildFail : 0 },
      { label: "구문 오류", penalty: syntaxOk === false ? riskWeights.syntaxFail : 0 },
      { label: "테스트 미활성", penalty: testsEnabled ? 0 : riskWeights.testsOff },
      { label: "Health 경고", penalty: (health.warnings || []).length * riskWeights.healthWarning, count: (health.warnings || []).length },
      { label: "Health 누락", penalty: (health.missing || []).length * riskWeights.healthMissing, count: (health.missing || []).length },
    ];
    const totalPenalty = items.reduce((sum, i) => sum + i.penalty, 0);
    const score = Math.max(0, Math.min(100, 100 - totalPenalty));
    const activeItems = items.filter((i) => i.penalty > 0).sort((a, b) => b.penalty - a.penalty);
    return { score, totalPenalty, items: activeItems, allItems: items };
  }, [severityCounts, buildOk, syntaxOk, testsEnabled, health, riskWeights]);
  const riskScore = riskBreakdown.score;

  const toneForStatic = () => {
    if (errorsCount > 0) return "failed";
    if (warningsCount > 0) return "warning";
    return "success";
  };

  const toneForPreflight = () => {
    if ((preflight.missing || []).length > 0) return "failed";
    if ((preflight.warnings || []).length > 0) return "warning";
    return "success";
  };

  const toneForHealth = () => {
    if ((health.missing || []).length > 0) return "failed";
    if ((health.warnings || []).length > 0) return "warning";
    return "success";
  };

  const toneForBuild = () => {
    if (buildOk === false || syntaxOk === false) return "failed";
    if (buildOk === true && syntaxOk === true) return "success";
    return "warning";
  };

  const toneForTests = () => {
    if (requireTestsEnabled && !testsEnabled) return "warning";
    if (testsCount < testsMinCount) return "warning";
    if (coverageLine >= coverageWarnThreshold) return "success";
    if (coverageLine >= coverageFailThreshold) return "warning";
    return "failed";
  };

  const toneForImpact = () => (impact.total ? "info" : "success");

  const detailInsights = (key) => {
    switch (key) {
      case "status":
        return [
          {
            label: "상태",
            value: status.state || "-",
            tone: toneForStatus(status.state),
            tab: "status",
          },
          {
            label: "단계",
            value: status.phase || "-",
            tone: "info",
            tab: "status",
          },
          {
            label: "종료 코드",
            value: status.exit_code ?? "-",
            tone: status.exit_code ? "failed" : "success",
            tab: "status",
          },
        ];
      case "static":
        return [
          {
            label: "Error",
            value: errorsCount,
            tone: errorsCount ? "failed" : "success",
            tab: "static",
          },
          {
            label: "Warning",
            value: warningsCount,
            tone: warningsCount ? "warning" : "success",
            tab: "static",
          },
          {
            label: "Top Tools",
            value: topTools.map(([tool]) => tool).join(", ") || "-",
            tone: "info",
            tab: "quality",
          },
        ];
      case "preflight":
        return [
          {
            label: "누락",
            value: (preflight.missing || []).length,
            tone: (preflight.missing || []).length ? "failed" : "success",
            tab: "preflight",
          },
          {
            label: "경고",
            value: (preflight.warnings || []).length,
            tone: (preflight.warnings || []).length ? "warning" : "success",
            tab: "preflight",
          },
        ];
      case "change-impact":
        return [
          {
            label: "변경 파일",
            value: impact.total || 0,
            tone: toneForImpact(),
            tab: "change-impact",
          },
          {
            label: "테스트 포함",
            value: impact.has_tests ? "Y" : "N",
            tone: impact.has_tests ? "success" : "warning",
            tab: "change-impact",
          },
          {
            label: "빌드 파일",
            value: impact.has_build_files ? "Y" : "N",
            tone: impact.has_build_files ? "warning" : "info",
            tab: "change-impact",
          },
        ];
      case "report-health":
        return [
          {
            label: "누락",
            value: (health.missing || []).length,
            tone: (health.missing || []).length ? "failed" : "success",
            tab: "report-health",
          },
          {
            label: "경고",
            value: (health.warnings || []).length,
            tone: (health.warnings || []).length ? "warning" : "success",
            tab: "report-health",
          },
        ];
      case "build":
        return [
          {
            label: "빌드",
            value: buildOk ? "OK" : "FAIL",
            tone: buildOk ? "success" : "failed",
            tab: "build",
          },
          {
            label: "문법 검사",
            value: syntaxOk ? "OK" : "FAIL",
            tone: syntaxOk ? "success" : "failed",
            tab: "build",
          },
          {
            label: "사유",
            value: summary?.build?.reason || "-",
            tone: "info",
            tab: "build",
          },
        ];
      case "tests":
        return [
          {
            label: "테스트 활성",
            value: testsEnabled ? "ON" : "OFF",
            tone: testsEnabled ? "success" : "warning",
            tab: "tests",
          },
          {
            label: "케이스 수",
            value: testsCount || "-",
            tone: testsCount ? "info" : "warning",
            tab: "tests",
          },
          {
            label: "라인 커버리지",
            value: coverageLine ? `${coverageLine.toFixed(1)}%` : "-",
            tone: toneForTests(),
            tab: "tests",
          },
        ];
      case "agent":
        return [
          {
            label: "에이전트",
            value: agent.enabled ? "ON" : "OFF",
            tone: agent.enabled ? "success" : "warning",
            tab: "agent",
          },
          {
            label: "실행 횟수",
            value: (summary?.agent_runs || []).length,
            tone: "info",
            tab: "agent",
          },
        ];
      case "scm":
        return [
          { label: "모드", value: scm.mode || "-", tone: "info", tab: "scm" },
          {
            label: "변경 파일",
            value: scm.changed_files || 0,
            tone: "info",
            tab: "scm",
          },
          {
            label: "브랜치",
            value: scm.branch || "-",
            tone: "info",
            tab: "scm",
          },
        ];
      default:
        return [];
    }
  };

  const renderRelatedList = (items, lbl, fmt) => (
    <RelatedList items={items} emptyLabel={lbl} formatter={fmt} />
  );

  const formatPreflightWarning = (item) => {
    const map = {
      semgrep_missing_disabled: "semgrep 미설치: 비활성화됨",
    };
    return map[item] || String(item);
  };

  const formatValue = (value) => {
    if (value === null || value === undefined || value === "") return "-";
    if (Array.isArray(value)) return `${value.length}개`;
    if (typeof value === "object") return "객체";
    if (typeof value === "boolean") return value ? "Y" : "N";
    return String(value);
  };

  const reportSummaries = Array.isArray(localReportSummaries)
    ? localReportSummaries
    : [];
  const reportComparisons = Array.isArray(localReportComparisons)
    ? localReportComparisons
    : [];

  const detailRows = (key, data) => {
    if (!data || typeof data !== "object") return [];
    switch (key) {
      case "status":
        return [
          { label: "상태", value: data.state },
          { label: "단계", value: data.phase },
          { label: "메시지", value: data.message },
          { label: "종료 코드", value: data.exit_code },
        ];
      case "static":
        return [
          {
            label: "Cppcheck",
            value:
              data.cppcheck?.data?.issues?.length ??
              data.cppcheck?.issues?.length,
          },
          {
            label: "Clang-Tidy",
            value:
              data.clang_tidy?.data?.issues?.length ??
              data.clang_tidy?.issues?.length,
          },
          {
            label: "Semgrep",
            value:
              data.semgrep?.data?.issues?.length ??
              data.semgrep?.issues?.length,
          },
        ];
      case "preflight":
        return [
          { label: "상태", value: data.status },
          { label: "누락", value: data.missing?.length },
          { label: "경고", value: data.warnings?.length },
        ];
      case "change-impact":
        return [
          { label: "변경 파일", value: data.total },
          { label: "테스트 포함", value: data.has_tests },
          { label: "설정 포함", value: data.has_configs },
          { label: "빌드 파일", value: data.has_build_files },
        ];
      case "report-health":
        return [
          { label: "상태", value: data.status },
          { label: "누락", value: data.missing?.length },
          { label: "경고", value: data.warnings?.length },
        ];
      case "build":
        return [
          { label: "빌드 OK", value: data.build?.ok ?? data.ok },
          { label: "사유", value: data.build?.reason ?? data.reason },
          { label: "문법 OK", value: data.syntax?.ok },
        ];
      case "tests":
        return [
          { label: "테스트 활성", value: data.tests?.enabled ?? data.enabled },
          { label: "케이스 수", value: data.tests?.total ?? data.total },
          {
            label: "라인 커버리지",
            value: data.coverage?.line_rate_pct
              ? `${data.coverage.line_rate_pct.toFixed(1)}%`
              : data.line_rate_pct,
          },
          {
            label: "브랜치 커버리지",
            value: data.coverage?.branch_rate_pct
              ? `${data.coverage.branch_rate_pct.toFixed(1)}%`
              : data.branch_rate_pct,
          },
        ];
      case "agent":
        return [
          {
            label: "에이전트 활성",
            value: data.agent?.enabled ?? data.enabled,
          },
          {
            label: "중지 사유",
            value: data.agent?.stop_reason ?? data.stop_reason,
          },
          {
            label: "실행 횟수",
            value:
              data.runs?.length ??
              data.runs_count ??
              (data.runs ? data.runs.length : undefined),
          },
        ];
      case "scm":
        return [
          { label: "모드", value: data.mode },
          { label: "변경 파일", value: data.changed_files },
          { label: "브랜치", value: data.branch },
          { label: "리비전", value: data.revision },
        ];
      default:
        return Object.entries(data)
          .slice(0, 6)
          .map(([label, value]) => ({ label, value }));
    }
  };

  return (
    <div className="dashboard-grid view-root">
      <div className="dashboard-main">
        <section className="tri-panel dashboard-top">
          <DashboardStatusCards
            status={status}
            stat={stat}
            preflight={preflight}
            impact={impact}
            health={health}
            summary={summary}
            tests={tests}
            coverage={coverage}
            agent={agent}
            scm={scm}
            handleCardClick={handleCardClick}
            statusTone={toneForStatus(status.state)}
            staticTone={toneForStatic()}
            preflightTone={toneForPreflight()}
            impactTone={toneForImpact()}
            healthTone={toneForHealth()}
            buildTone={toneForBuild()}
            testsTone={toneForTests()}
          />
          <div className="summary-chart">
            <div className="summary-title">오류/경고 분포</div>
            <div className="bar-row">
              <span className="bar-label">Error</span>
              <div className="bar">
                <div
                  className="bar-fill bar-fill-error"
                  style={{
                    width: `${Math.min(100, severityCounts.error * 3)}%`,
                  }}
                />
              </div>
              <span className="bar-value">{severityCounts.error}</span>
            </div>
            <div className="bar-row">
              <span className="bar-label">Warn</span>
              <div className="bar">
                <div
                  className="bar-fill bar-fill-warn"
                  style={{
                    width: `${Math.min(100, severityCounts.warning * 3)}%`,
                  }}
                />
              </div>
              <span className="bar-value">{severityCounts.warning}</span>
            </div>
            <div className="bar-row">
              <span className="bar-label">Info</span>
              <div className="bar">
                <div
                  className="bar-fill bar-fill-info"
                  style={{
                    width: `${Math.min(100, severityCounts.info * 1.5)}%`,
                  }}
                />
              </div>
              <span className="bar-value">{severityCounts.info}</span>
            </div>
          </div>
          <div className="summary-chart">
            <div className="summary-title">메트릭 요약</div>
            <div className="metric-chip-row metric-chip-compact">
              {visibleMetricChips.map((item) => (
                <button
                  key={`${item.label}-${item.value}`}
                  type="button"
                  className={`metric-chip tone-${item.tone} ${item.navigate ? "clickable" : ""}`}
                  onClick={() =>
                    item.navigate && onWorkflowTabChange
                      ? onWorkflowTabChange(item.navigate)
                      : null
                  }
                >
                  {item.label} {item.value}
                </button>
              ))}
              {extraMetricCount > 0 && (
                <span className="metric-chip metric-chip-more">
                  +{extraMetricCount}
                </span>
              )}
              {metricSummaryItems.length === 0 && (
                <span className="empty">메트릭 요약 없음</span>
              )}
            </div>
          </div>

          {/* Code Quality 차트 */}
          <div className="summary-chart">
            <div className="summary-title">Code Quality (정적 분석)</div>
            <div className="quality-chart">
              {["cppcheck", "clangTidy", "semgrep"].map((tool) => {
                const metrics = codeQualityMetrics[tool];
                const total = metrics.issues || 0;
                const maxIssues = Math.max(
                  1,
                  codeQualityMetrics.cppcheck.issues,
                  codeQualityMetrics.clangTidy.issues,
                  codeQualityMetrics.semgrep.issues,
                );
                return (
                  <div key={tool} className="quality-tool-row">
                    <span className="quality-tool-label">{tool}</span>
                    <div className="quality-bar-container">
                      <div className="quality-bar">
                        <div
                          className="quality-bar-fill quality-bar-error"
                          style={{
                            width: `${(metrics.errors / maxIssues) * 100}%`,
                            height: "8px",
                          }}
                          title={`Errors: ${metrics.errors}`}
                        />
                        <div
                          className="quality-bar-fill quality-bar-warn"
                          style={{
                            width: `${(metrics.warnings / maxIssues) * 100}%`,
                            height: "8px",
                            marginLeft: "2px",
                          }}
                          title={`Warnings: ${metrics.warnings}`}
                        />
                      </div>
                    </div>
                    <span className="quality-tool-value">
                      {metrics.ok ? "✓" : "✗"} {total}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {/* 지식베이스 표시 */}
          {kbEntries && kbEntries.length > 0 && (() => {
            const kbCategories = [...new Set(kbEntries.map((e) => e.category).filter(Boolean))];
            const filteredKb = kbEntries.filter((entry) => {
              if (kbCatFilter !== "all" && entry.category !== kbCatFilter) return false;
              if (kbSearch) {
                const q = kbSearch.toLowerCase();
                const text = (entry.error_raw || entry.error_clean || entry.title || "").toLowerCase();
                if (!text.includes(q)) return false;
              }
              return true;
            });
            return (
            <div className="panel">
              <div className="row">
                <div className="summary-title">
                  지식베이스 ({filteredKb.length}/{kbEntries.length}개 항목)
                </div>
                {loadKbEntries && (
                  <button type="button" onClick={loadKbEntries}>
                    새로고침
                  </button>
                )}
              </div>
              <div className="kb-filter-bar">
                <input
                  placeholder="검색..."
                  value={kbSearch}
                  onChange={(e) => setKbSearch(e.target.value)}
                />
                <button type="button" className={`kb-cat-btn ${kbCatFilter === "all" ? "active" : ""}`} onClick={() => setKbCatFilter("all")}>전체</button>
                {kbCategories.map((cat) => (
                  <button key={cat} type="button" className={`kb-cat-btn ${kbCatFilter === cat ? "active" : ""}`} onClick={() => setKbCatFilter(cat)}>{cat}</button>
                ))}
              </div>
              <div className="kb-grid">
                {filteredKb.slice(0, 20).map((entry, idx) => (
                  <div key={entry.id || idx} className="kb-card">
                    <div className="kb-card-title">
                      <span>{entry.error_raw || entry.error_clean || entry.title || `Entry ${idx + 1}`}</span>
                      {entry.category && <span className="kb-card-cat">{entry.category}</span>}
                    </div>
                    {entry.tags && Array.isArray(entry.tags) && entry.tags.length > 0 && (
                      <div className="kb-tags">
                        {entry.tags.slice(0, 5).map((tag) => (
                          <span key={tag} className="kb-card-cat kb-tag">{tag}</span>
                        ))}
                      </div>
                    )}
                    {entry.timestamp && (
                      <div className="hint kb-timestamp">
                        {new Date(entry.timestamp).toLocaleString("ko-KR")}
                      </div>
                    )}
                    {(entry.fix_suggestion || entry.solution) && (
                      <div className="kb-card-body">{entry.fix_suggestion || entry.solution}</div>
                    )}
                  </div>
                ))}
              </div>
              {filteredKb.length > 20 && (
                <div className="hint kb-overflow-hint">
                  ... 외 {filteredKb.length - 20}개 항목
                </div>
                )}
              </div>
            );
          })()}
        </section>
        <div className="dashboard-bottom">
          <section className="tri-panel dashboard-detail-panel">
            <div className="slide-panel dashboard-detail">
              <div id="detail-tabs" className="detail-tabs tabs">
                {detailTabs.map((tab) => {
                  let badge = null;
                  let dot = null;
                  const d = tab.data;
                  if (tab.key === "static") {
                    const cnt = errorsCount + warningsCount;
                    if (cnt > 0) badge = cnt;
                    if (errorsCount > 0) dot = "dot-error";
                    else if (warningsCount > 0) dot = "dot-warning";
                  } else if (tab.key === "preflight") {
                    const pf = d;
                    if (pf && typeof pf === "object") {
                      const vals = Object.values(pf);
                      const failCount = vals.filter((v) => v === false || v === "FAIL").length;
                      badge = vals.length || null;
                      if (failCount > 0) dot = "dot-error";
                    }
                  } else if (tab.key === "tests") {
                    const t = d?.tests;
                    if (t) {
                      badge = t.total || t.count || null;
                      if (t.ok === false) dot = "dot-error";
                    }
                  } else if (tab.key === "agent") {
                    const ag = d?.agent || d;
                    const runs = d?.runs;
                    if (Array.isArray(runs)) badge = runs.length;
                    else if (ag?.runs_count) badge = ag.runs_count;
                  } else if (tab.key === "scm") {
                    if (d?.changed_files) badge = d.changed_files;
                  }
                  return (
                  <button
                    key={tab.key}
                    className={detailTab === tab.key ? "active" : ""}
                    onClick={() => onDetailTabChange(tab.key)}
                  >
                    {tab.label}
                    {badge != null && <span className="detail-tab-badge">{badge}</span>}
                    {dot && <span className={`detail-tab-dot ${dot}`} />}
                  </button>
                  );
                })}
              </div>
              <div className="detail-panel">
                <div
                  key={activeDetail?.key || "detail"}
                  className="slide-panel-content"
                >
                  <h4>{activeDetail?.label || "Detail"}</h4>
                  {(() => { const ins = detailInsights(activeDetail?.key); return ins.length > 0 ? (
                    <div className="insight-grid">
                      {ins.map((item) => (
                        <div
                          key={item.label}
                          className={`insight-card tone-${item.tone || "info"} clickable`}
                          onClick={() =>
                            item.tab && onDetailTabChange(item.tab)
                          }
                        >
                          <div className="insight-label">{item.label}</div>
                          <div className="insight-value">
                            {formatValue(item.value)}
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : null; })()}
                  {activeDetail?.key === "preflight" ? (
                    <div className="detail-related">
                      <div>
                        <div className="hint">누락 항목</div>
                        {renderRelatedList(preflight.missing, "누락 없음")}
                      </div>
                      <div>
                        <div className="hint">경고 항목</div>
                        {renderRelatedList(
                          preflight.warnings,
                          "경고 없음",
                          formatPreflightWarning,
                        )}
                      </div>
                    </div>
                  ) : null}
                  {activeDetail?.key === "report-health" ? (
                    <div className="detail-related">
                      <div>
                        <div className="hint">누락 항목</div>
                        {renderRelatedList(health.missing, "누락 없음")}
                      </div>
                      <div>
                        <div className="hint">경고 항목</div>
                        {renderRelatedList(health.warnings, "경고 없음")}
                      </div>
                    </div>
                  ) : null}
                  {activeDetail?.key === "local-report" ? (
                    <LocalReportSummaryPanel
                      reportSummaries={reportSummaries}
                      reportComparisons={reportComparisons}
                      loadLocalReportSummary={loadLocalReportSummary}
                      onOpenEditorFile={onOpenEditorFile}
                    />
                  ) : activeDetail?.key === "metrics" ? (
                    <div className="metric-detail">
                      <div className="row metric-filters">
                        <span className="hint">메트릭 필터</span>
                        {[
                          { key: "build", label: "빌드" },
                          { key: "tests", label: "테스트" },
                          { key: "coverage", label: "커버리지" },
                          { key: "static", label: "정적분석" },
                        ].map((item) => (
                          <button
                            key={item.key}
                            type="button"
                            className={`metric-filter-btn ${metricFilters[item.key] ? "active" : ""}`}
                            onClick={() =>
                              setMetricFilters((prev) => ({
                                ...prev,
                                [item.key]: !prev[item.key],
                              }))
                            }
                          >
                            {item.label}
                          </button>
                        ))}
                      </div>
                      <div className="metric-grid">
                        {visibleMetricCards.map((card) => (
                          <div
                            key={card.label}
                            className={`metric-card tone-${card.tone} ${card.navigate ? "clickable" : ""}`}
                            onClick={() =>
                              card.navigate && onWorkflowTabChange
                                ? onWorkflowTabChange(card.navigate)
                                : null
                            }
                          >
                            <div className="metric-label">{card.label}</div>
                            <div className="metric-value">{card.value}</div>
                            {card.hint ? (
                              <div className="metric-hint">{card.hint}</div>
                            ) : null}
                            {card.progressPct != null && (
                              <div className="metric-progress-bar">
                                <div
                                  className={`metric-progress-fill tone-${card.tone}`}
                                  style={{ width: `${Math.min(100, Math.max(0, card.progressPct))}%` }}
                                />
                                {card.threshold != null && (
                                  <div className="metric-progress-threshold" style={{ left: `${Math.min(100, card.threshold)}%` }} />
                                )}
                              </div>
                            )}
                            {card.stackBars && (
                              <div className="metric-stack-bar">
                                {card.stackBars.map((seg) => (
                                  <div key={seg.cls} className={`metric-stack-seg ${seg.cls}`} style={{ width: `${seg.pct}%` }} />
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                      <div className="metric-section">
                        <div className="row">
                          <span className="hint">복잡도 상위 (CCN)</span>
                          {loadComplexity ? (
                            <button type="button" onClick={loadComplexity}>
                              복잡도 로드
                            </button>
                          ) : null}
                        </div>
                        <div className="list">
                          {topComplexity.map((row) => (
                            <button
                              key={`${row.file}:${row.func}`}
                              className={`list-item ${row.ccn >= complexityThreshold ? "is-warning" : ""}`}
                              onClick={() =>
                                onOpenEditorFile
                                  ? onOpenEditorFile(row.file, row.line)
                                  : null
                              }
                            >
                              <span className="list-text">{row.func}</span>
                              <span className="list-snippet">
                                {row.file} · CCN {row.ccn} · NLOC {row.nloc}
                              </span>
                            </button>
                          ))}
                          {topComplexity.length === 0 && (
                            <div className="empty">복잡도 데이터 없음</div>
                          )}
                        </div>
                      </div>
                      <div className="metric-section">
                        <div className="hint">전체 메트릭</div>
                        <div className="metric-list">
                          {filteredMetricDetails.map((item) => (
                            <div key={item.key} className="metric-row">
                              <span className="metric-key">{item.key}</span>
                              <span className="metric-value">{item.value}</span>
                            </div>
                          ))}
                          {filteredMetricDetails.length === 0 && (
                            <div className="empty">표시할 메트릭 없음</div>
                          )}
                        </div>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="detail-grid">
                        {detailRows(activeDetail?.key, activeDetail?.data).map(
                          (row) => (
                            <div key={row.label} className="detail-row">
                              <span className="detail-label">{row.label}</span>
                              <span className="detail-value">
                                {formatValue(row.value)}
                              </span>
                            </div>
                          ),
                        )}
                      </div>
                      <details className="detail-raw">
                        <summary>원본 JSON 보기</summary>
                        <pre className="json">
                          {JSON.stringify(activeDetail?.data || {}, null, 2)}
                        </pre>
                      </details>
                    </>
                  )}
                </div>
              </div>
            </div>
          </section>
          <section className="tri-panel dashboard-side">
            <div className="panel">
              <h3>상세 차트</h3>
              {activeDetail?.key === "tests" ? (
                <>
                <div className="summary-chart">
                  <div className="bar-row">
                    <span className="bar-label">Line</span>
                    <div className="bar">
                      <div
                        className="bar-fill"
                        style={{
                          width: `${Math.min(100, Math.max(0, coverageLine || 0))}%`,
                        }}
                      />
                    </div>
                    <span className="bar-value">
                      {coverageLine ? `${coverageLine.toFixed(1)}%` : "-"}
                    </span>
                  </div>
                  <div className="bar-row">
                    <span className="bar-label">Branch</span>
                    <div className="bar">
                      <div
                        className="bar-fill"
                        style={{
                          width: `${Math.min(100, Math.max(0, coverageBranch || 0))}%`,
                        }}
                      />
                    </div>
                    <span className="bar-value">
                      {coverageBranch ? `${coverageBranch.toFixed(1)}%` : "-"}
                    </span>
                  </div>
                  <div className="bar-row">
                    <span className="bar-label">Func</span>
                    <div className="bar">
                      <div
                        className="bar-fill"
                        style={{
                          width: `${Math.min(100, Math.max(0, coverageFunc || 0))}%`,
                        }}
                      />
                    </div>
                    <span className="bar-value">
                      {coverageFunc ? `${coverageFunc.toFixed(1)}%` : "-"}
                    </span>
                  </div>
                </div>
                {(() => {
                  const covPackages = coverage?.packages || coverage?.files || [];
                  const covRows = (Array.isArray(covPackages) ? covPackages : Object.entries(covPackages).map(([name, data]) => ({ name, ...data })));
                  if (covRows.length === 0) return null;
                  const sorted = [...covRows].sort((a, b) => {
                    const aRate = Number(a.line_rate_pct ?? a.line_rate ?? 100);
                    const bRate = Number(b.line_rate_pct ?? b.line_rate ?? 100);
                    return aRate - bRate;
                  }).slice(0, 10);
                  return (
                    <div className="cov-lowest-panel">
                      <h5>커버리지 하위 10 파일</h5>
                      <div className="list">
                        {sorted.map((row, i) => {
                          const name = row.name || row.filename || row.file || `file-${i}`;
                          const lp = Number(row.line_rate_pct ?? row.line_rate ?? 0);
                          const cls = lp < 50 ? "cov-low" : lp < 80 ? "cov-mid" : "cov-high";
                          return (
                            <div key={name} className="list-item">
                              <span className="list-text text-ellipsis" title={name}>{name.split(/[/\\]/).pop()}</span>
                              <span className={cls}>{lp.toFixed(1)}%</span>
                              <span className="coverage-mini-bar"><span className={`cov-bar-fill ${cls}`} style={{ width: `${lp}%` }} /></span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })()}
                </>
              ) : activeDetail?.key === "static" ? (
                <div>
                  <div className="summary-chart">
                    <div className="bar-row">
                      <span className="bar-label">Error</span>
                      <div className="bar">
                        <div
                          className="bar-fill bar-fill-error"
                          style={{ width: `${Math.min(100, errorsCount * 3)}%` }}
                        />
                      </div>
                      <span className="bar-value">{errorsCount}</span>
                    </div>
                    <div className="bar-row">
                      <span className="bar-label">Warn</span>
                      <div className="bar">
                        <div
                          className="bar-fill bar-fill-warn"
                          style={{
                            width: `${Math.min(100, warningsCount * 3)}%`,
                          }}
                        />
                      </div>
                      <span className="bar-value">{warningsCount}</span>
                    </div>
                  </div>
                  {(findings || []).length > 0 && (
                    <div className="issue-section">
                      <h5 className="issue-section-title">이슈 목록 ({findings.length}건)</h5>
                      <div className="detail-grid issue-scroll">
                        {(findings || []).slice(0, 100).map((f, idx) => {
                          const sev = classifySeverity(f);
                          const filePath = f.file || f.path || f.location?.file || "";
                          const lineNo = f.line || f.location?.line || null;
                          return (
                            <div key={idx} className="quality-issue-row">
                              <span className={`quality-sev-dot sev-${sev}`} />
                              <span className="text-ellipsis" title={f.message || f.msg || f.description || ""}>
                                {f.message || f.msg || f.description || "(메시지 없음)"}
                              </span>
                              <span className="hint quality-file-path">{String(f.tool || "").toLowerCase()}</span>
                              {filePath && (
                                <button
                                  type="button"
                                  className="issue-open-editor"
                                  onClick={() => onOpenEditorFile && onOpenEditorFile(filePath, lineNo)}
                                  title={`${filePath}${lineNo ? `:${lineNo}` : ""}`}
                                >
                                  📂 열기
                                </button>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="empty">상세 탭을 선택하세요</div>
              )}
            </div>
            <div className="panel">
              <div className="row">
                <h3>복잡도 히트맵 (파일별 최대 CCN)</h3>
                {loadComplexity && (
                  <button type="button" onClick={loadComplexity}>
                    새로고침
                  </button>
                )}
              </div>
              {complexityHeatmap.length > 0 ? (
                <div className="heatmap">
                  <div className="heatmap-header">
                    <span className="heatmap-label">파일</span>
                    {[0, 5, 10, 15, 20, 25, 30].map((threshold) => (
                      <span key={threshold} className="heatmap-label">
                        {threshold}+
                      </span>
                    ))}
                    <span className="heatmap-label">CCN</span>
                  </div>
                  {complexityHeatmap.slice(0, 15).map((item) => {
                    const intensity = Math.min(100, (item.maxCcn / 30) * 100)
                    const cellClass =
                      item.maxCcn >= 20
                        ? "heatmap-danger"
                        : item.maxCcn >= 10
                          ? "heatmap-warn"
                          : "heatmap-info"
                    return (
                      <div key={item.file} className="heatmap-row">
                        <span className="heatmap-label" title={item.file}>
                          {item.file.split(/[/\\]/).pop()}
                        </span>
                        {[0, 5, 10, 15, 20, 25, 30].map((threshold) => (
                          <span
                            key={threshold}
                            className={`heatmap-cell ${item.maxCcn >= threshold ? cellClass : ""}`}
                            style={{
                              opacity:
                                item.maxCcn >= threshold
                                  ? Math.max(0.3, intensity / 100)
                                  : 0.1,
                            }}
                            title={`${item.file}: 최대 CCN ${item.maxCcn}`}
                          />
                        ))}
                        <span className="heatmap-value">{item.maxCcn}</span>
                      </div>
                    )
                  })}
                </div>
              ) : (
                <div className="empty">복잡도 데이터 없음</div>
              )}
            </div>
          </section>
        </div>
      </div>
      <section className="tri-panel tri-right">
        <div className="panel">
          <h3>Top N 요약</h3>
          <div className="panel-grid">
            <div>
              <div className="hint">이슈 그룹</div>
              {renderRelatedList(topRuleGroups, "그룹 없음")}
            </div>
            <div>
              <div className="hint">도구 Top</div>
              {renderRelatedList(
                topTools.map(([tool]) => tool),
                "도구 없음",
              )}
            </div>
            <div>
              <div className="hint">최근 로그</div>
              {renderRelatedList((logs || []).slice(-5), "로그 없음")}
            </div>
          </div>
        </div>
        <div className="panel">
          <h3>시간대별 로그/상태 추이</h3>
          <div className="trend-grid">
            <div className="trend-card">
              <div className="summary-title">로그 이벤트</div>
              <div className="mini-chart">
                {logSeries.map((item) => (
                  <div key={`log-${item.label}`} className="mini-bar">
                    <div
                      className="mini-bar-fill"
                      style={{
                        height: `${Math.round((item.count / maxLogCount) * 100)}%`,
                      }}
                    />
                    <span className="mini-bar-label">{item.label}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="trend-card">
              <div className="summary-title">상태 이벤트</div>
              <div className="mini-chart">
                {statusSeries.map((item) => {
                  const total = item.running + item.success + item.fail;
                  const scale = total
                    ? Math.round((total / maxStatusCount) * 100)
                    : 0;
                  const runningPct = total
                    ? Math.round((item.running / total) * 100)
                    : 0;
                  const successPct = total
                    ? Math.round((item.success / total) * 100)
                    : 0;
                  const failPct = total
                    ? Math.max(0, 100 - runningPct - successPct)
                    : 0;
                  return (
                    <div key={`history-${item.label}`} className="mini-bar">
                      <div
                        className="mini-bar-stack"
                        style={{ height: `${scale}%` }}
                      >
                        <span
                          className="mini-bar-segment mini-bar-running"
                          style={{ height: `${runningPct}%` }}
                        />
                        <span
                          className="mini-bar-segment mini-bar-success"
                          style={{ height: `${successPct}%` }}
                        />
                        <span
                          className="mini-bar-segment mini-bar-fail"
                          style={{ height: `${failPct}%` }}
                        />
                      </div>
                      <span className="mini-bar-label">{item.label}</span>
                    </div>
                  );
                })}
              </div>
              <div className="trend-legend">
                <span className="legend-dot legend-running" /> running
                <span className="legend-dot legend-success" /> success
                <span className="legend-dot legend-fail" /> fail
              </div>
            </div>
          </div>
        </div>
        <div className="panel">
          <h3>히트맵 / 리스크 점수</h3>
          <RiskScorePanel riskBreakdown={riskBreakdown} riskScore={riskScore} />

          {/* CTest 결과 상세 */}
          {(() => {
            const ctestResults = summary?.build?.data?.ctest_results || [];
            if (ctestResults.length === 0) return null;
            const sorted = [...ctestResults].sort((a, b) => {
              const statusOrder = { FAIL: 0, TIMEOUT: 1, SKIP: 2, PASS: 3 };
              return (statusOrder[a.status] ?? 4) - (statusOrder[b.status] ?? 4);
            });
            return (
              <div className="ctest-detail-panel">
                <h4>CTest 결과 ({ctestResults.length}건)</h4>
                <table className="coverage-detail-table">
                  <thead>
                    <tr>
                      <th>테스트 이름</th>
                      <th>상태</th>
                      <th>실행 시간</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((t, idx) => {
                      const st = String(t.status || "").toUpperCase();
                      const tone = st === "PASS" ? "success" : st === "FAIL" ? "failed" : st === "SKIP" ? "info" : "warning";
                      return (
                        <tr key={idx} className={st === "FAIL" ? "ctest-fail-row" : ""}>
                          <td className="cell-ellipsis" title={t.name || t.test}>{t.name || t.test || `Test ${idx + 1}`}</td>
                          <td><span className={`status-chip tone-${tone}`}>{st || "-"}</span></td>
                          <td>{t.duration != null ? `${Number(t.duration).toFixed(2)}s` : t.time || "-"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            );
          })()}

          <div className="heatmap">
            <div
              className="heatmap-header"
              style={{
                gridTemplateColumns: `1.4fr repeat(${Math.max(1, topRuleGroups.length)}, 1fr)`,
              }}
            >
              <span>Tool</span>
              {(topRuleGroups.length ? topRuleGroups : ["misc"]).map(
                (group) => (
                  <span key={`head-${group}`}>{group}</span>
                ),
              )}
            </div>
            {topTools.length === 0 && <div className="empty">데이터 없음</div>}
            {topTools.map(([tool]) => (
              <div
                key={tool}
                className="heatmap-row"
                style={{
                  gridTemplateColumns: `1.4fr repeat(${Math.max(1, topRuleGroups.length)}, 1fr)`,
                }}
              >
                <span className="heatmap-label">{tool}</span>
                {(topRuleGroups.length ? topRuleGroups : ["misc"]).map(
                  (group) => {
                    const value = toolRuleBuckets[tool]?.[group] || 0;
                    return (
                      <span
                        key={`${tool}-${group}`}
                        className="heatmap-cell heatmap-info"
                        style={{ opacity: value / maxRuleCell }}
                      >
                        {value}
                      </span>
                    );
                  },
                )}
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
};

export default LocalDashboard;
