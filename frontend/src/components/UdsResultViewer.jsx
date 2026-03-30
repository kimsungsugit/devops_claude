import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph from "./ForceGraph";
import CodeHighlight from "./CodeHighlight";

const PAGE_SIZE = 25;
const TRACE_PAGE_SIZE = 200;

const toText = (v) => (v === null || v === undefined ? "" : String(v));
const toList = (v) => (Array.isArray(v) ? v : []);
const toDisplayList = (v) => {
  if (Array.isArray(v)) return v.map((item) => toText(item).trim()).filter(Boolean);
  const raw = toText(v).trim();
  if (!raw) return [];
  return raw
    .split(/\r?\n|,\s*/)
    .map((item) => toText(item).trim())
    .filter(Boolean);
};
const toSwCom = (fn) => {
  const raw = toText(fn?.swcom || "").trim();
  if (raw) return raw;
  const m = toText(fn?.id || "").match(/SwUFn_(\d{2})/i);
  return m ? `SwCom_${m[1]}` : "UNMAPPED";
};
const countList = (v) => toList(v).filter((x) => toText(x).trim()).length;
const boolFilter = (mode, hasValue) => {
  if (mode === "yes") return hasValue;
  if (mode === "no") return !hasValue;
  return true;
};

const toCsv = (headers, rows) => {
  const esc = (v) => `"${toText(v).replaceAll('"', '""')}"`;
  const lines = [headers.map((h) => esc(h.label)).join(",")];
  rows.forEach((row) => {
    lines.push(headers.map((h) => esc(row[h.key])).join(","));
  });
  return `${lines.join("\n")}\n`;
};

const downloadText = (filename, text) => {
  const blob = new Blob([text], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

const fetchJson = async (url, options = {}) => {
  const timeoutMs = Number(options?.timeoutMs || 120000);
  const { timeoutMs: _omitTimeout, ...rest } = options || {};
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...rest, signal: rest?.signal || controller.signal });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    return res.json();
  } catch (e) {
    if (e?.name === "AbortError") {
      throw new Error(`요청 시간 초과(${Math.round(timeoutMs / 1000)}s)`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
};

const openLocalPath = async (path) => {
  const target = toText(path).trim();
  if (!target) return;
  const res = await fetch("/api/local/open-file", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: target }),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
};

const readUrlState = (prefix, key, fallback = "") => {
  if (typeof window === "undefined") return fallback;
  try {
    const params = new URLSearchParams(window.location.search);
    const v = params.get(`${prefix}${key}`);
    return v === null ? fallback : v;
  } catch {
    return fallback;
  }
};

const readUrlIntState = (prefix, key, fallback = 1) => {
  const raw = readUrlState(prefix, key, String(fallback));
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : fallback;
};

const MiniRelationGraph = ({ fn, fnByName, onNodeClick, activeNodeName = "" }) => {
  if (!fn) return null;
  const active = toText(activeNodeName).trim().toLowerCase();
  const callers = toList(fn?.calling).map((v) => toText(v).trim()).filter(Boolean).slice(0, 10);
  const callees = toList(fn?.called).map((v) => toText(v).trim()).filter(Boolean).slice(0, 10);
  const calleeHop2 = callees.map((name) => {
    const hop1 = fnByName?.get?.(toText(name).trim().toLowerCase());
    return {
      from: name,
      to: toList(hop1?.called).map((v) => toText(v).trim()).filter(Boolean).slice(0, 2),
    };
  });
  const maxRows = Math.max(callers.length, callees.length, 1);
  const rowH = 26;
  const h = 50 + maxRows * rowH;
  const cx = 380;
  const leftX = 130;
  const rightX = 630;
  const right2X = 880;
  const centerY = h / 2;
  const leftBaseY = 28;
  const rightBaseY = 28;

  return (
    <div className="uds-mini-graph">
      <svg width="100%" height={h} viewBox={`0 0 1020 ${h}`} role="img" aria-label="함수 관계 2-hop 그래프">
        {callers.map((_, idx) => {
          const y = leftBaseY + idx * rowH;
          return (
            <line key={`l-${idx}`} x1={leftX + 80} y1={y} x2={cx - 78} y2={centerY} stroke="currentColor" opacity="0.35" />
          );
        })}
        {callees.map((_, idx) => {
          const y = rightBaseY + idx * rowH;
          return (
            <line key={`r-${idx}`} x1={cx + 78} y1={centerY} x2={rightX - 80} y2={y} stroke="currentColor" opacity="0.35" />
          );
        })}
        {calleeHop2.map((row, idx) => {
          const baseY = rightBaseY + idx * rowH;
          return (row.to || []).map((_, j) => {
            const y = baseY + (row.to.length > 1 ? (j === 0 ? -6 : 6) : 0);
            return (
              <line
                key={`r2-${idx}-${j}`}
                x1={rightX + 90}
                y1={baseY}
                x2={right2X - 90}
                y2={y}
                stroke="currentColor"
                opacity="0.45"
                strokeDasharray="5 4"
              />
            );
          });
        })}

        <g
          className={`uds-graph-clickable ${toText(fn?.name).trim().toLowerCase() === active ? "is-active" : ""}`}
          onClick={() => (typeof onNodeClick === "function" ? onNodeClick(toText(fn?.name)) : null)}
        >
          <rect x={cx - 78} y={centerY - 18} width="156" height="36" rx="8" className="uds-graph-center" />
          <text x={cx} y={centerY + 5} textAnchor="middle" className="uds-graph-text-center">
            {toText(fn?.name) || "-"}
          </text>
        </g>

        {callers.map((name, idx) => {
          const y = leftBaseY + idx * rowH;
          return (
            <g
              key={`caller-${idx}`}
              className={`uds-graph-clickable ${toText(name).trim().toLowerCase() === active ? "is-active" : ""}`}
              onClick={() => (typeof onNodeClick === "function" ? onNodeClick(name) : null)}
            >
              <rect x={leftX - 90} y={y - 12} width="180" height="24" rx="6" className="uds-graph-node" />
              <text x={leftX} y={y + 4} textAnchor="middle" className="uds-graph-text">
                {name}
              </text>
            </g>
          );
        })}

        {callees.map((name, idx) => {
          const y = rightBaseY + idx * rowH;
          return (
            <g
              key={`callee-${idx}`}
              className={`uds-graph-clickable ${toText(name).trim().toLowerCase() === active ? "is-active" : ""}`}
              onClick={() => (typeof onNodeClick === "function" ? onNodeClick(name) : null)}
            >
              <rect x={rightX - 90} y={y - 12} width="180" height="24" rx="6" className="uds-graph-node" />
              <text x={rightX} y={y + 4} textAnchor="middle" className="uds-graph-text">
                {name}
              </text>
            </g>
          );
        })}
        {calleeHop2.map((row, idx) => {
          const baseY = rightBaseY + idx * rowH;
          return (row.to || []).map((name, j) => {
            const y = baseY + (row.to.length > 1 ? (j === 0 ? -6 : 6) : 0);
            return (
              <g
                key={`callee2-${idx}-${j}`}
                className={`uds-graph-clickable ${toText(name).trim().toLowerCase() === active ? "is-active" : ""}`}
                onClick={() => (typeof onNodeClick === "function" ? onNodeClick(name) : null)}
              >
                <rect x={right2X - 90} y={y - 12} width="180" height="24" rx="6" className="uds-graph-node uds-graph-node-hop2" />
                <text x={right2X} y={y + 4} textAnchor="middle" className="uds-graph-text">
                  {name}
                </text>
              </g>
            );
          });
        })}
      </svg>
      {(countList(fn?.calling) > callers.length || countList(fn?.called) > callees.length) && (
        <div className="hint">
          표시 제한: Calling {callers.length}/{countList(fn?.calling)}, Called {callees.length}/{countList(fn?.called)}
        </div>
      )}
    </div>
  );
};

const UdsResultViewer = ({
  title = "UDS 상세 조회",
  data,
  loading,
  error,
  onRefresh,
  serverMode = false,
  onRequestData,
  urlStateKey = "uds",
  sourceRoot = "",
  onFetchCallGraph,
  onFetchDependencyMap,
  onFetchCodePreview,
  onRunImpactAnalyze,
  onGenerateTestData,
}) => {
  const listPaneRef = useRef(null);
  const detailPaneRef = useRef(null);
  const tracePaneRef = useRef(null);
  const urlSyncTimerRef = useRef(null);
  const onRequestDataRef = useRef(onRequestData);
  const statePrefix = `uv_${toText(urlStateKey || "uds")}_`;
  const [tab, setTab] = useState(() => readUrlState(statePrefix, "tab", "summary"));
  const [query, setQuery] = useState(() => readUrlState(statePrefix, "q", ""));
  const [swcomFilter, setSwcomFilter] = useState(() => readUrlState(statePrefix, "swcom", "all"));
  const [asilFilter, setAsilFilter] = useState(() => readUrlState(statePrefix, "asil", "all"));
  const [hasInputFilter, setHasInputFilter] = useState(() => readUrlState(statePrefix, "in", "all"));
  const [hasOutputFilter, setHasOutputFilter] = useState(() => readUrlState(statePrefix, "out", "all"));
  const [hasCalledFilter, setHasCalledFilter] = useState(() => readUrlState(statePrefix, "called", "all"));
  const [hasCallingFilter, setHasCallingFilter] = useState(() => readUrlState(statePrefix, "calling", "all"));
  const [sortKey, setSortKey] = useState(() => readUrlState(statePrefix, "sort", "id"));
  const [sortDir, setSortDir] = useState(() => readUrlState(statePrefix, "dir", "asc"));
  const [page, setPage] = useState(() => readUrlIntState(statePrefix, "page", 1));
  const [selectedFnKey, setSelectedFnKey] = useState(() => readUrlState(statePrefix, "fn", ""));
  const [traceQuery, setTraceQuery] = useState(() => readUrlState(statePrefix, "tq", ""));
  const [traceMode, setTraceMode] = useState(() => readUrlState(statePrefix, "tm", "flat"));
  const [traceFocusReq, setTraceFocusReq] = useState(() => readUrlState(statePrefix, "treq", ""));
  const [traceDepth, setTraceDepth] = useState(() => readUrlIntState(statePrefix, "tdepth", 1));
  const [graphActiveName, setGraphActiveName] = useState(() => readUrlState(statePrefix, "gsel", ""));
  const [graphDepth, setGraphDepth] = useState(() => readUrlIntState(statePrefix, "gdepth", 2));
  const [depLevel, setDepLevel] = useState(() => readUrlState(statePrefix, "dlevel", "module"));
  const [impactChangedRaw, setImpactChangedRaw] = useState(() => readUrlState(statePrefix, "ichanged", ""));
  const [testStrategy, setTestStrategy] = useState(() => readUrlState(statePrefix, "tstrat", "boundary"));
  const [callGraphData, setCallGraphData] = useState(null);
  const [depMapData, setDepMapData] = useState(null);
  const [codePreviewData, setCodePreviewData] = useState(null);
  const [impactData, setImpactData] = useState(null);
  const [testData, setTestData] = useState(null);
  const [globalsData, setGlobalsData] = useState(null);
  const [globalsQuery, setGlobalsQuery] = useState("");
  const [globalsScope, setGlobalsScope] = useState("all");
  const [globalsSortKey, setGlobalsSortKey] = useState("name");
  const [globalsSortDir, setGlobalsSortDir] = useState("asc");
  const [globalsPage, setGlobalsPage] = useState(1);
  const [advancedLoading, setAdvancedLoading] = useState(false);
  const [advancedError, setAdvancedError] = useState("");
  const [advancedProgress, setAdvancedProgress] = useState(0);
  const [advancedStep, setAdvancedStep] = useState("대기 중");
  const [advancedLogs, setAdvancedLogs] = useState([]);
  const [callGraphView, setCallGraphView] = useState("graph");
  const [depMapView, setDepMapView] = useState("graph");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [traceBatch, setTraceBatch] = useState(200);

  const renderStructuredValues = (values, emptyText = "N/A") => {
    const rows = toDisplayList(values);
    if (rows.length === 0) return emptyText;
    return (
      <div style={{ display: "grid", gap: 6 }}>
        {rows.map((value, idx) => (
          <div
            key={`${value}-${idx}`}
            className="card"
            style={{ padding: "8px 10px", whiteSpace: "normal", overflowWrap: "anywhere" }}
          >
            {value}
          </div>
        ))}
      </div>
    );
  };

  const pushAdvancedLog = (text) => {
    const line = `[${new Date().toLocaleTimeString()}] ${toText(text)}`;
    setAdvancedLogs((prev) => [line, ...prev].slice(0, 8));
  };

  const functions = useMemo(() => toList(data?.functions), [data]);
  const traceability = useMemo(() => toList(data?.traceability), [data]);
  const meta = data?.meta || {};

  useEffect(() => {
    onRequestDataRef.current = onRequestData;
  }, [onRequestData]);

  useEffect(() => {
    if (!serverMode) return;
    if (typeof onRequestDataRef.current !== "function") return;
    const timer = setTimeout(() => {
      onRequestDataRef.current({
        q: query,
        swcom: swcomFilter,
        asil: asilFilter,
        page,
        page_size: PAGE_SIZE,
        trace_q: traceQuery,
        trace_page: 1,
        trace_page_size: TRACE_PAGE_SIZE,
      });
    }, 250);
    return () => clearTimeout(timer);
  }, [serverMode, query, swcomFilter, asilFilter, page, traceQuery]);

  const swcomOptions = useMemo(() => {
    const set = new Set(["all"]);
    functions.forEach((fn) => set.add(toSwCom(fn)));
    return Array.from(set).sort();
  }, [functions]);

  const asilOptions = useMemo(() => {
    const set = new Set(["all"]);
    functions.forEach((fn) => {
      const asil = toText(fn?.asil).trim();
      if (asil) set.add(asil);
    });
    return Array.from(set);
  }, [functions]);

  const filteredFunctions = useMemo(() => {
    if (serverMode) return functions;
    const token = toText(query).trim().toLowerCase();
    return functions.filter((fn) => {
      if (swcomFilter !== "all" && toSwCom(fn) !== swcomFilter) return false;
      const asil = toText(fn?.asil).trim();
      if (asilFilter !== "all" && asil !== asilFilter) return false;
      if (!boolFilter(hasInputFilter, countList(fn?.inputs) > 0)) return false;
      if (!boolFilter(hasOutputFilter, countList(fn?.outputs) > 0)) return false;
      if (!boolFilter(hasCalledFilter, countList(fn?.called) > 0)) return false;
      if (!boolFilter(hasCallingFilter, countList(fn?.calling) > 0)) return false;
      if (!token) return true;
      return (
        toText(fn?.id).toLowerCase().includes(token) ||
        toText(fn?.name).toLowerCase().includes(token) ||
        toText(fn?.prototype).toLowerCase().includes(token) ||
        toText(fn?.description).toLowerCase().includes(token)
      );
    });
  }, [
    functions,
    query,
    swcomFilter,
    asilFilter,
    hasInputFilter,
    hasOutputFilter,
    hasCalledFilter,
    hasCallingFilter,
    serverMode,
  ]);

  const sortedFunctions = useMemo(() => {
    if (serverMode) return filteredFunctions;
    const dir = sortDir === "desc" ? -1 : 1;
    return [...filteredFunctions].sort((a, b) => {
      const av =
        sortKey === "called_count"
          ? countList(a?.called)
          : sortKey === "calling_count"
            ? countList(a?.calling)
            : sortKey === "swcom"
              ? toSwCom(a)
              : toText(a?.[sortKey] || "");
      const bv =
        sortKey === "called_count"
          ? countList(b?.called)
          : sortKey === "calling_count"
            ? countList(b?.calling)
            : sortKey === "swcom"
              ? toSwCom(b)
              : toText(b?.[sortKey] || "");
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return toText(av).localeCompare(toText(bv), undefined, { sensitivity: "base" }) * dir;
    });
  }, [filteredFunctions, serverMode, sortKey, sortDir]);

  const totalFunctions = Number(serverMode ? meta?.functions_total ?? 0 : sortedFunctions.length);
  const totalPages = Math.max(1, Math.ceil(totalFunctions / PAGE_SIZE));
  const effectivePage = Math.min(Math.max(1, page), totalPages);
  const pageItems = useMemo(() => {
    if (serverMode) return sortedFunctions;
    const offset = (effectivePage - 1) * PAGE_SIZE;
    return sortedFunctions.slice(offset, offset + PAGE_SIZE);
  }, [sortedFunctions, effectivePage, serverMode]);

  const selectedFn = useMemo(() => {
    const key = toText(selectedFnKey);
    if (key) {
      const found = functions.find((fn) => `${toText(fn.id)}::${toText(fn.name)}` === key);
      if (found) return found;
    }
    return pageItems[0] || null;
  }, [selectedFnKey, functions, pageItems]);

  const filteredTraceability = useMemo(() => {
    if (serverMode) return traceability;
    const token = toText(traceQuery).trim().toLowerCase();
    if (!token) return traceability;
    return traceability.filter((row) => {
      const req = toText(row?.requirement_id).toLowerCase();
      const fnId = toText(row?.function_id).toLowerCase();
      const fnName = toText(row?.function_name).toLowerCase();
      return req.includes(token) || fnId.includes(token) || fnName.includes(token);
    });
  }, [traceability, traceQuery, serverMode]);

  const fnByName = useMemo(() => {
    const map = new Map();
    functions.forEach((fn) => {
      const name = toText(fn?.name).trim().toLowerCase();
      if (name) map.set(name, fn);
    });
    return map;
  }, [functions]);

  const groupedTraceability = useMemo(() => {
    if (traceMode === "flat" || traceMode === "reverse_chain") return [];
    const map = new Map();
    filteredTraceability.forEach((row) => {
      const req = toText(row?.requirement_id) || "-";
      const fn = `${toText(row?.function_id) || "-"} / ${toText(row?.function_name) || "-"}`;
      const key = traceMode === "by_requirement" ? req : fn;
      const value = traceMode === "by_requirement" ? fn : req;
      if (!map.has(key)) map.set(key, new Set());
      map.get(key).add(value);
    });
    return Array.from(map.entries()).map(([key, values]) => ({
      key,
      values: Array.from(values).sort(),
      count: values.size,
    }));
  }, [filteredTraceability, traceMode]);

  const reverseTraceRows = useMemo(() => {
    const reqMap = new Map();
    filteredTraceability.forEach((row) => {
      const req = toText(row?.requirement_id).trim();
      const fnName = toText(row?.function_name).trim();
      const fnId = toText(row?.function_id).trim();
      if (!req || !fnName) return;
      if (!reqMap.has(req)) reqMap.set(req, new Map());
      reqMap.get(req).set(fnName, fnId);
    });
    const rows = Array.from(reqMap.entries()).map(([requirementId, fnMap]) => {
      const chains = Array.from(fnMap.entries()).map(([fnName, fnId]) => {
        const fn = fnByName.get(fnName.toLowerCase());
        const called = toList(fn?.called).map((v) => toText(v).trim()).filter(Boolean);
        const called2 =
          traceDepth >= 2
            ? called.map((hop1) => {
                const hopFn = fnByName.get(hop1.toLowerCase());
                const hop2 = toList(hopFn?.called).map((v) => toText(v).trim()).filter(Boolean).slice(0, 12);
                return {
                  from: hop1,
                  to: hop2,
                };
              })
            : [];
        return {
          functionId: fnId || "-",
          functionName: fnName,
          calledChain: called,
          calledChain2: called2,
        };
      });
      return {
        requirementId,
        chains,
      };
    });
    rows.sort((a, b) => a.requirementId.localeCompare(b.requirementId, undefined, { sensitivity: "base" }));
    return rows;
  }, [filteredTraceability, fnByName, traceDepth]);

  const reverseTraceFiltered = useMemo(() => {
    const target = toText(traceFocusReq).trim();
    if (!target) return reverseTraceRows;
    return reverseTraceRows.filter((row) => row.requirementId === target);
  }, [reverseTraceRows, traceFocusReq]);

  const swcomDistribution = useMemo(() => {
    const map = new Map();
    functions.forEach((fn) => {
      const sw = toSwCom(fn);
      map.set(sw, (map.get(sw) || 0) + 1);
    });
    return Array.from(map.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 12);
  }, [functions]);

  const summary = data?.summary || {};
  const summaryMapping = summary?.mapping || {};
  const accuracySummary = data?.accuracy_summary || {};
  const qualitySummary = data?.quality_gate_summary || {};
  const viewerStatus = useMemo(() => {
    if (loading) return { tone: "loading", text: "UDS 뷰 데이터 로딩 중..." };
    if (error) return { tone: "error", text: toText(error) };
    if (!data) return { tone: "idle", text: "조회 가능한 UDS 결과가 없습니다." };
    return { tone: "ready", text: "조회 완료" };
  }, [loading, error, data]);

  const functionStats = useMemo(() => {
    const rows = serverMode ? functions : filteredFunctions;
    const total = rows.length;
    const withInput = rows.filter((fn) => countList(fn?.inputs) > 0).length;
    const withOutput = rows.filter((fn) => countList(fn?.outputs) > 0).length;
    const withCalled = rows.filter((fn) => countList(fn?.called) > 0).length;
    const withCalling = rows.filter((fn) => countList(fn?.calling) > 0).length;
    const asilSources = { comment: 0, srs: 0, sds: 0, inference: 0, module_inherit: 0, default_val: 0 };
    const descSources = { comment: 0, srs: 0, sds: 0, inference: 0 };
    const mappingScopes = { direct: 0, fallback: 0, other: 0, unmapped: 0 };
    const asilNonTbd = rows.filter((fn) => {
      const a = toText(fn?.asil).trim().toUpperCase();
      return a && a !== "TBD" && a !== "N/A";
    }).length;
    const relatedNonTbd = rows.filter((fn) => {
      const r = toText(fn?.related).trim().toUpperCase();
      return r && r !== "TBD" && r !== "N/A" && r !== "-";
    }).length;
    rows.forEach((fn) => {
      const as = toText(fn?.asil_source).trim().toLowerCase();
      if (as === "comment") asilSources.comment++;
      else if (as === "srs") asilSources.srs++;
      else if (as === "sds") asilSources.sds++;
      else if (as === "module_inherit") asilSources.module_inherit++;
      else if (as === "default") asilSources.default_val++;
      else asilSources.inference++;
      const ds = toText(fn?.description_source).trim().toLowerCase();
      if (ds === "comment") descSources.comment++;
      else if (ds === "srs") descSources.srs++;
      else if (ds === "sds") descSources.sds++;
      else descSources.inference++;
      const scope = toText(fn?.sds_match_scope).trim().toLowerCase();
      if (scope === "function") mappingScopes.direct++;
      else if (scope === "swcom") mappingScopes.fallback++;
      else if (scope) mappingScopes.other++;
      else mappingScopes.unmapped++;
    });
    const unresolvedAsilRows = rows
      .filter((fn) => toText(fn?.asil).trim().toUpperCase() === "TBD")
      .map((fn) => {
        const hasSdsMatch = Boolean(toText(fn?.sds_match_key).trim());
        const hasRelated = (() => {
          const related = toText(fn?.related).trim().toUpperCase();
          return related && related !== "TBD" && related !== "N/A" && related !== "-";
        })();
        let reason = "Mapping pending";
        if (!hasSdsMatch && !hasRelated) reason = "No SDS match and no related requirement";
        else if (!hasSdsMatch) reason = "No SDS match";
        else if (!hasRelated) reason = "No related requirement";
        return {
          id: toText(fn?.id),
          name: toText(fn?.name),
          swcom: toSwCom(fn),
          reason,
          sds_match_key: toText(fn?.sds_match_key),
          sds_match_mode: toText(fn?.sds_match_mode),
        };
      });
    const backendResidual = toList(summaryMapping?.residual_tbd_rows).map((row) => ({
      id: toText(row?.id),
      name: toText(row?.name),
      swcom: toText(row?.swcom),
      reason: toText(row?.reason),
      sds_match_key: toText(row?.sds_match_key),
      sds_match_mode: toText(row?.sds_match_mode),
    }));
    return {
      total,
      withInput,
      withOutput,
      withCalled,
      withCalling,
      asilSources,
      descSources,
      mappingScopes: {
        direct: Number(summaryMapping?.direct ?? mappingScopes.direct ?? 0),
        fallback: Number(summaryMapping?.fallback ?? mappingScopes.fallback ?? 0),
        other: Number(summaryMapping?.other ?? mappingScopes.other ?? 0),
        unmapped: Number(summaryMapping?.unmapped ?? mappingScopes.unmapped ?? 0),
      },
      asilNonTbd,
      relatedNonTbd,
      unresolvedAsilRows: backendResidual.length > 0 ? backendResidual : unresolvedAsilRows,
    };
  }, [functions, filteredFunctions, serverMode, summaryMapping]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    if (urlSyncTimerRef.current) {
      clearTimeout(urlSyncTimerRef.current);
      urlSyncTimerRef.current = null;
    }
    const listY = listPaneRef.current?.scrollTop ?? null;
    const detailY = detailPaneRef.current?.scrollTop ?? null;
    const traceY = tracePaneRef.current?.scrollTop ?? null;
    urlSyncTimerRef.current = setTimeout(() => {
      const params = new URLSearchParams(window.location.search);
      const keysToDelete = [];
      for (const [k] of params.entries()) {
        if (k.startsWith(statePrefix)) keysToDelete.push(k);
      }
      keysToDelete.forEach((k) => params.delete(k));
      const put = (k, v, def = "") => {
        const val = toText(v);
        if (val === toText(def)) return;
        params.set(`${statePrefix}${k}`, val);
      };
      put("tab", tab, "summary");
      put("q", query, "");
      put("swcom", swcomFilter, "all");
      put("asil", asilFilter, "all");
      put("in", hasInputFilter, "all");
      put("out", hasOutputFilter, "all");
      put("called", hasCalledFilter, "all");
      put("calling", hasCallingFilter, "all");
      put("sort", sortKey, "id");
      put("dir", sortDir, "asc");
      put("page", page, 1);
      put("fn", selectedFnKey, "");
      put("tq", traceQuery, "");
      put("tm", traceMode, "flat");
      put("treq", traceFocusReq, "");
      put("tdepth", traceDepth, 1);
      put("gsel", graphActiveName, "");
      put("gdepth", graphDepth, 2);
      put("dlevel", depLevel, "module");
      put("ichanged", impactChangedRaw, "");
      put("tstrat", testStrategy, "boundary");
      const qs = params.toString();
      const next = `${window.location.pathname}${qs ? `?${qs}` : ""}${window.location.hash || ""}`;
      window.history.replaceState({}, "", next);
      requestAnimationFrame(() => {
        if (listY != null && listPaneRef.current) listPaneRef.current.scrollTop = listY;
        if (detailY != null && detailPaneRef.current) detailPaneRef.current.scrollTop = detailY;
        if (traceY != null && tracePaneRef.current) tracePaneRef.current.scrollTop = traceY;
      });
    }, 200);
    return () => {
      if (urlSyncTimerRef.current) {
        clearTimeout(urlSyncTimerRef.current);
        urlSyncTimerRef.current = null;
      }
    };
  }, [
    statePrefix,
    tab,
    query,
    swcomFilter,
    asilFilter,
    hasInputFilter,
    hasOutputFilter,
    hasCalledFilter,
    hasCallingFilter,
    sortKey,
    sortDir,
    page,
    selectedFnKey,
    traceQuery,
    traceMode,
    traceFocusReq,
    traceDepth,
    graphActiveName,
    graphDepth,
    depLevel,
    impactChangedRaw,
    testStrategy,
  ]);

  const jumpToFunction = (name) => {
    const target = toText(name).trim().toLowerCase();
    if (!target) return;
    const index = sortedFunctions.findIndex((fn) => toText(fn?.name).trim().toLowerCase() === target);
    if (index < 0) return;
    const targetPage = Math.floor(index / PAGE_SIZE) + 1;
    setPage(targetPage);
    const row = sortedFunctions[index];
    setSelectedFnKey(`${toText(row?.id)}::${toText(row?.name)}`);
    setGraphActiveName(toText(name));
    setTab("functions");
  };

  const exportFunctionCsv = () => {
    const rows = (serverMode ? functions : sortedFunctions).map((fn) => ({
      swcom: toSwCom(fn),
      id: toText(fn?.id),
      name: toText(fn?.name),
      asil: toText(fn?.asil),
      prototype: toText(fn?.prototype),
      input_count: countList(fn?.inputs),
      output_count: countList(fn?.outputs),
      called_count: countList(fn?.called),
      calling_count: countList(fn?.calling),
      description: toText(fn?.description).replaceAll("\n", " "),
    }));
    downloadText(
      "uds_functions.csv",
      toCsv(
        [
          { key: "swcom", label: "SwCom" },
          { key: "id", label: "ID" },
          { key: "name", label: "Function Name" },
          { key: "asil", label: "ASIL" },
          { key: "prototype", label: "Prototype" },
          { key: "input_count", label: "Input Count" },
          { key: "output_count", label: "Output Count" },
          { key: "called_count", label: "Called Count" },
          { key: "calling_count", label: "Calling Count" },
          { key: "description", label: "Description" },
        ],
        rows
      )
    );
  };

  const exportTraceCsv = () => {
    const rows = filteredTraceability.map((row) => ({
      requirement_id: toText(row?.requirement_id),
      function_id: toText(row?.function_id),
      function_name: toText(row?.function_name),
    }));
    downloadText(
      "uds_traceability.csv",
      toCsv(
        [
          { key: "requirement_id", label: "Requirement ID" },
          { key: "function_id", label: "Function ID" },
          { key: "function_name", label: "Function Name" },
        ],
        rows
      )
    );
  };

  const renderMappingBadges = (fn) => {
    const scope = toText(fn?.sds_match_scope).trim().toLowerCase();
    const confidenceRaw = fn?.mapping_confidence;
    const hasScope = Boolean(scope);
    const hasConfidence = confidenceRaw !== null && confidenceRaw !== undefined && confidenceRaw !== "";
    if (!hasScope && !hasConfidence) return null;
    const confidencePct = hasConfidence ? `${Math.round(Number(confidenceRaw) * 100)}%` : "";
    const scopeLabel =
      scope === "function" ? "Direct" : scope === "swcom" ? "SwCom Fallback" : scope || "Mapped";
    const scopeTone = scope === "function" ? "map-direct" : scope === "swcom" ? "map-fallback" : "map-other";
    return (
      <span className="uds-mapping-badges">
        {hasScope ? <span className={`uds-meta-chip uds-map-badge ${scopeTone}`}>{scopeLabel}</span> : null}
        {hasConfidence ? <span className="uds-meta-chip uds-map-badge map-confidence">{confidencePct}</span> : null}
      </span>
    );
  };

  const requestCallGraph = async () => {
    const fnName = toText(selectedFn?.name).trim();
    const root = toText(sourceRoot).trim();
    setAdvancedProgress(10);
    setAdvancedStep("Call Graph 입력 확인");
    pushAdvancedLog("Call Graph 로드 시작");
    if (!root) {
      setAdvancedError("source_root를 입력해주세요.");
      setAdvancedStep("실패: source_root 누락");
      setAdvancedProgress(100);
      return;
    }
    setAdvancedLoading(true);
    setAdvancedError("");
    setAdvancedStep("Call Graph API 요청");
    setAdvancedProgress(40);
    try {
      const payload =
        typeof onFetchCallGraph === "function"
          ? await onFetchCallGraph({ source_root: root, focus_function: fnName, depth: graphDepth })
          : await fetchJson(
              `/api/code/call-graph?${new URLSearchParams({
                source_root: root,
                focus_function: fnName,
                depth: String(graphDepth),
              }).toString()}`
            ,
              { timeoutMs: 600000 }
            );
      setCallGraphData(payload?.graph || payload);
      const count = Number(payload?.graph?.meta?.edge_count ?? payload?.meta?.edge_count ?? 0);
      setAdvancedStep("Call Graph 로드 완료");
      setAdvancedProgress(100);
      pushAdvancedLog(`Call Graph 완료 (edge=${count})`);
    } catch (e) {
      setAdvancedError(e?.message || String(e));
      setAdvancedStep(`Call Graph 실패: ${toText(e?.message || e)}`);
      setAdvancedProgress(100);
      pushAdvancedLog(`Call Graph 실패: ${toText(e?.message || e)}`);
    } finally {
      setAdvancedLoading(false);
    }
  };

  const requestDependencyMap = async () => {
    const root = toText(sourceRoot).trim();
    setAdvancedProgress(10);
    setAdvancedStep("Dependency Map 입력 확인");
    pushAdvancedLog("Dependency Map 로드 시작");
    if (!root) {
      setAdvancedError("source_root를 입력해주세요.");
      setAdvancedStep("실패: source_root 누락");
      setAdvancedProgress(100);
      return;
    }
    setAdvancedLoading(true);
    setAdvancedError("");
    setAdvancedStep("Dependency Map API 요청");
    setAdvancedProgress(40);
    try {
      const payload =
        typeof onFetchDependencyMap === "function"
          ? await onFetchDependencyMap({ source_root: root, level: depLevel })
          : await fetchJson(
              `/api/code/dependency-map?${new URLSearchParams({
                source_root: root,
                level: depLevel,
              }).toString()}`
            ,
              { timeoutMs: 600000 }
            );
      setDepMapData(payload?.dependency_map || payload);
      const count = Number(payload?.dependency_map?.meta?.edge_count ?? payload?.meta?.edge_count ?? 0);
      setAdvancedStep("Dependency Map 로드 완료");
      setAdvancedProgress(100);
      pushAdvancedLog(`Dependency Map 완료 (edge=${count})`);
    } catch (e) {
      setAdvancedError(e?.message || String(e));
      setAdvancedStep(`Dependency Map 실패: ${toText(e?.message || e)}`);
      setAdvancedProgress(100);
      pushAdvancedLog(`Dependency Map 실패: ${toText(e?.message || e)}`);
    } finally {
      setAdvancedLoading(false);
    }
  };

  const requestCodePreview = async () => {
    const root = toText(sourceRoot).trim();
    const fnName = toText(selectedFn?.name).trim();
    setAdvancedProgress(10);
    setAdvancedStep("Code Preview 입력 확인");
    pushAdvancedLog("Code Preview 로드 시작");
    if (!root || !fnName) {
      setAdvancedError("source_root와 함수 선택이 필요합니다.");
      setAdvancedStep("실패: source_root/함수 선택 누락");
      setAdvancedProgress(100);
      return;
    }
    setAdvancedLoading(true);
    setAdvancedError("");
    setAdvancedStep("Code Preview API 요청");
    setAdvancedProgress(40);
    try {
      const payload =
        typeof onFetchCodePreview === "function"
          ? await onFetchCodePreview({ source_root: root, function_name: fnName, include_callees: true })
          : await fetchJson(
              `/api/code/preview/function?${new URLSearchParams({
                source_root: root,
                function_name: fnName,
                include_callees: "true",
              }).toString()}`
            ,
              { timeoutMs: 120000 }
            );
      setCodePreviewData(payload?.preview || payload);
      setAdvancedStep("Code Preview 로드 완료");
      setAdvancedProgress(100);
      pushAdvancedLog(`Code Preview 완료 (${fnName})`);
    } catch (e) {
      setAdvancedError(e?.message || String(e));
      setAdvancedStep(`Code Preview 실패: ${toText(e?.message || e)}`);
      setAdvancedProgress(100);
      pushAdvancedLog(`Code Preview 실패: ${toText(e?.message || e)}`);
    } finally {
      setAdvancedLoading(false);
    }
  };

  const requestGlobals = async () => {
    const root = toText(sourceRoot).trim();
    setAdvancedProgress(10);
    setAdvancedStep("Globals 입력 확인");
    pushAdvancedLog("Globals 로드 시작");
    if (!root) {
      setAdvancedError("source_root를 입력해주세요.");
      setAdvancedStep("실패: source_root 누락");
      setAdvancedProgress(100);
      return;
    }
    setAdvancedLoading(true);
    setAdvancedError("");
    setAdvancedStep("Globals API 요청");
    setAdvancedProgress(40);
    try {
      const payload = await fetchJson(
        `/api/code/globals?${new URLSearchParams({ source_root: root }).toString()}`,
        { timeoutMs: 600000 }
      );
      setGlobalsData(payload);
      const total = (payload?.total_global ?? 0) + (payload?.total_static ?? 0);
      setAdvancedStep("Globals 로드 완료");
      setAdvancedProgress(100);
      pushAdvancedLog(`Globals 완료 (global=${payload?.total_global ?? 0}, static=${payload?.total_static ?? 0}, total=${total})`);
    } catch (e) {
      setAdvancedError(e?.message || String(e));
      setAdvancedStep(`Globals 실패: ${toText(e?.message || e)}`);
      setAdvancedProgress(100);
      pushAdvancedLog(`Globals 실패: ${toText(e?.message || e)}`);
    } finally {
      setAdvancedLoading(false);
    }
  };

  const requestImpactAnalyze = async () => {
    const root = toText(sourceRoot).trim();
    setAdvancedProgress(10);
    setAdvancedStep("Impact 입력 확인");
    pushAdvancedLog("Impact 분석 시작");
    if (!root) {
      setAdvancedError("source_root를 입력해주세요.");
      setAdvancedStep("실패: source_root 누락");
      setAdvancedProgress(100);
      return;
    }
    setAdvancedLoading(true);
    setAdvancedError("");
    setAdvancedStep("Impact API 요청");
    setAdvancedProgress(40);
    try {
      const body = {
        source_root: root,
        changed_raw: impactChangedRaw,
      };
      const payload =
        typeof onRunImpactAnalyze === "function"
          ? await onRunImpactAnalyze(body)
          : await fetchJson("/api/impact/analyze", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
              timeoutMs: 300000,
            });
      setImpactData(payload?.result || payload);
      const impacted = Number(payload?.result?.impacted_function_count ?? payload?.impacted_function_count ?? 0);
      setAdvancedStep("Impact 분석 완료");
      setAdvancedProgress(100);
      pushAdvancedLog(`Impact 완료 (impacted=${impacted})`);
    } catch (e) {
      setAdvancedError(e?.message || String(e));
      setAdvancedStep(`Impact 실패: ${toText(e?.message || e)}`);
      setAdvancedProgress(100);
      pushAdvancedLog(`Impact 실패: ${toText(e?.message || e)}`);
    } finally {
      setAdvancedLoading(false);
    }
  };

  const requestTestGenerate = async () => {
    const root = toText(sourceRoot).trim();
    const fnName = toText(selectedFn?.name).trim();
    setAdvancedProgress(10);
    setAdvancedStep("Test Data 입력 확인");
    pushAdvancedLog("Test Data 생성 시작");
    if (!root || !fnName) {
      setAdvancedError("source_root와 함수 선택이 필요합니다.");
      setAdvancedStep("실패: source_root/함수 선택 누락");
      setAdvancedProgress(100);
      return;
    }
    setAdvancedLoading(true);
    setAdvancedError("");
    setAdvancedStep("Test Data API 요청");
    setAdvancedProgress(40);
    try {
      const body = {
        source_root: root,
        target_function: fnName,
        strategy: testStrategy,
        max_cases: 20,
      };
      const payload =
        typeof onGenerateTestData === "function"
          ? await onGenerateTestData(body)
          : await fetchJson("/api/test/generate", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
              timeoutMs: 120000,
            });
      setTestData(payload);
      setAdvancedStep("Test Data 생성 완료");
      setAdvancedProgress(100);
      pushAdvancedLog(`Test Data 완료 (cases=${toList(payload?.cases).length})`);
    } catch (e) {
      setAdvancedError(e?.message || String(e));
      setAdvancedStep(`Test Data 실패: ${toText(e?.message || e)}`);
      setAdvancedProgress(100);
      pushAdvancedLog(`Test Data 실패: ${toText(e?.message || e)}`);
    } finally {
      setAdvancedLoading(false);
    }
  };

  return (
    <div className="panel uds-viewer">
      <div className="row">
        <h4>{title}</h4>
        {typeof onRefresh === "function" ? (
          <button type="button" className="btn-outline" onClick={onRefresh}>
            새로고침
          </button>
        ) : null}
      </div>

      <div className={`uds-viewer-status tone-${viewerStatus.tone}`} title={viewerStatus.text}>
        {viewerStatus.text}
      </div>

      {data ? (
        <>
          <div className="uds-kpi-grid">
            <div className="uds-kpi-card">
              <div className="uds-kpi-label">Total</div>
              <div className="uds-kpi-value">{summaryMapping?.total ?? summary?.total_functions ?? meta?.functions_total ?? 0}</div>
            </div>
            <div className="uds-kpi-card">
              <div className="uds-kpi-label">Direct</div>
              <div className="uds-kpi-value">{summaryMapping?.direct ?? functionStats.mappingScopes?.direct ?? 0}</div>
            </div>
            <div className="uds-kpi-card">
              <div className="uds-kpi-label">Fallback</div>
              <div className="uds-kpi-value">{summaryMapping?.fallback ?? functionStats.mappingScopes?.fallback ?? 0}</div>
            </div>
            <div className="uds-kpi-card">
              <div className="uds-kpi-label">Unmapped</div>
              <div className="uds-kpi-value">{summaryMapping?.unmapped ?? functionStats.mappingScopes?.unmapped ?? 0}</div>
            </div>
            <div className="uds-kpi-card">
              <div className="uds-kpi-label">Called Accuracy</div>
              <div className="uds-kpi-value">{toText(accuracySummary?.called_exact_match) || "-"}</div>
              {(() => {
                const raw = toText(accuracySummary?.called_exact_match);
                const pct = parseFloat(raw);
                if (!Number.isFinite(pct)) return null;
                return (
                  <div className="uds-kpi-bar">
                    <div className="uds-kpi-bar-fill" style={{ width: `${Math.min(100, pct)}%` }} />
                  </div>
                );
              })()}
            </div>
            <div className="uds-kpi-card">
              <div className="uds-kpi-label">Quality Gate</div>
              <div className="uds-kpi-value">
                {(() => {
                  const raw = qualitySummary?.gate_pass;
                  if (raw === true || raw === "true" || raw === "PASS") {
                    return <span className="uds-gate-badge pass">PASS</span>;
                  }
                  if (raw === false || raw === "false" || raw === "FAIL") {
                    return <span className="uds-gate-badge fail">FAIL</span>;
                  }
                  return toText(raw) || "-";
                })()}
              </div>
            </div>
          </div>

          <div className="row uds-tabs">
            <button type="button" className={tab === "summary" ? "active" : ""} onClick={() => setTab("summary")}>
              <span className="uds-tab-icon">&#931;</span> Summary
            </button>
            <button type="button" className={tab === "functions" ? "active" : ""} onClick={() => setTab("functions")}>
              <span className="uds-tab-icon">&#402;</span> Functions
              {totalFunctions > 0 ? <span className="uds-tab-badge">{totalFunctions}</span> : null}
            </button>
            <button type="button" className={tab === "traceability" ? "active" : ""} onClick={() => setTab("traceability")}>
              <span className="uds-tab-icon">&#8644;</span> Trace
              {traceability.length > 0 ? <span className="uds-tab-badge">{traceability.length}</span> : null}
            </button>
            <button type="button" className={tab === "globals" ? "active" : ""} onClick={() => setTab("globals")}>
              <span className="uds-tab-icon">&#120276;</span> Globals
              {globalsData ? <span className="uds-tab-badge">{toList(globalsData?.globals).length}</span> : null}
            </button>
            <button type="button" className={tab === "call_graph" ? "active" : ""} onClick={() => setTab("call_graph")}>
              <span className="uds-tab-icon">&#9672;</span> Call Graph
            </button>
            <button type="button" className={tab === "dependency_map" ? "active" : ""} onClick={() => setTab("dependency_map")}>
              <span className="uds-tab-icon">&#9638;</span> Dep Map
            </button>
            <button type="button" className={tab === "code_preview" ? "active" : ""} onClick={() => setTab("code_preview")}>
              <span className="uds-tab-icon">&lt;/&gt;</span> Code
            </button>
            <button type="button" className={tab === "impact" ? "active" : ""} onClick={() => setTab("impact")}>
              <span className="uds-tab-icon">&#9889;</span> Impact
            </button>
            <button type="button" className={tab === "test_data" ? "active" : ""} onClick={() => setTab("test_data")}>
              <span className="uds-tab-icon">&#9881;</span> Test
            </button>
          </div>

          <div className="row uds-toolbar">
            <input value={sourceRoot} readOnly placeholder="source_root (상위에서 지정)" />
            {advancedLoading ? <span className="hint">분석 중...</span> : null}
            {advancedError ? <span className="error">{advancedError}</span> : null}
          </div>
          <div className="uds-op-panel">
            <div className="uds-op-row">
              <span className="detail-label">진행 상태</span>
              <span className="detail-value">{advancedStep}</span>
            </div>
            <div className="uds-op-progress">
              <div className="uds-op-progress-bar" style={{ width: `${Math.max(0, Math.min(100, advancedProgress))}%` }} />
            </div>
            <div className="uds-op-log">
              {advancedLogs.length > 0 ? advancedLogs.join("\n") : "버튼 실행 시 작업 로그가 표시됩니다."}
            </div>
          </div>

          {tab === "summary" ? (
            <div className="uds-summary-grid">
              <div className="detail-grid">
                <div className="detail-row compact">
                  <span className="detail-label">파일명</span>
                  <span className="detail-value">{toText(data?.filename) || "-"}</span>
                </div>
                {toText(data?.residual_tbd_report_path) ? (
                  <div className="detail-row compact">
                    <span className="detail-label">Residual TBD</span>
                    <span className="detail-value">
                      <button
                        type="button"
                        className="btn-outline btn-xs"
                        onClick={() => openLocalPath(toText(data?.residual_tbd_report_path)).catch(() => null)}
                      >
                        {toText(data?.residual_tbd_report_path).split(/[\/]/).pop() || "report"}
                      </button>
                    </span>
                  </div>
                ) : null}
              </div>
              <div className="uds-stat-chart-panel">
                <h5>함수 커버리지</h5>
                {[
                  { label: "Input", value: functionStats.withInput },
                  { label: "Output", value: functionStats.withOutput },
                  { label: "Called", value: functionStats.withCalled },
                  { label: "Calling", value: functionStats.withCalling },
                ].map((row) => {
                  const pct = functionStats.total > 0 ? (row.value / functionStats.total) * 100 : 0;
                  return (
                    <div key={row.label} className="uds-stat-row">
                      <span className="uds-stat-label">{row.label}</span>
                      <div className="uds-stat-bar">
                        <div
                          className="uds-stat-bar-fill"
                          style={{ width: `${pct}%` }}
                          title={`${row.value}/${functionStats.total} (${pct.toFixed(1)}%)`}
                        />
                      </div>
                      <span className="uds-stat-num">
                        {row.value}/{functionStats.total}
                      </span>
                    </div>
                  );
                })}
              </div>
              {swcomDistribution.length > 0 ? (
                <div className="uds-stat-chart-panel">
                  <h5>SwCom 분포</h5>
                  <div className="uds-swcom-dist">
                    {swcomDistribution.map(([name, count]) => {
                      const pct = functionStats.total > 0 ? (count / functionStats.total) * 100 : 0;
                      return (
                        <div key={name} className="uds-stat-row">
                          <span className="uds-stat-label" title={name}>
                            {name.length > 14 ? name.slice(0, 12) + ".." : name}
                          </span>
                          <div className="uds-stat-bar swcom">
                            <div className="uds-stat-bar-fill swcom" style={{ width: `${pct}%` }} />
                          </div>
                          <span className="uds-stat-num">{count}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : null}

              <div className="uds-stat-chart-panel">
                <h5>Direct vs Fallback</h5>
                {[
                  { label: "Direct", value: functionStats.mappingScopes?.direct || 0, color: "#2196f3" },
                  { label: "SwCom", value: functionStats.mappingScopes?.fallback || 0, color: "#ff9800" },
                  { label: "Other", value: functionStats.mappingScopes?.other || 0, color: "#ab47bc" },
                  { label: "Unmapped", value: functionStats.mappingScopes?.unmapped || 0, color: "#607d8b" },
                ].map((row) => {
                  const pct = functionStats.total > 0 ? (row.value / functionStats.total) * 100 : 0;
                  return (
                    <div key={row.label} className="uds-stat-row">
                      <span className="uds-stat-label">{row.label}</span>
                      <div className="uds-stat-bar">
                        <div
                          className="uds-stat-bar-fill"
                          style={{ width: `${pct}%`, background: row.color }}
                          title={`${row.value}/${functionStats.total} (${pct.toFixed(1)}%)`}
                        />
                      </div>
                      <span className="uds-stat-num">{row.value}</span>
                    </div>
                  );
                })}
                <div className="uds-summary-chip-row">
                  <span className="uds-meta-chip">Direct {functionStats.mappingScopes?.direct || 0}</span>
                  <span className="uds-meta-chip">Fallback {functionStats.mappingScopes?.fallback || 0}</span>
                  <span className="uds-meta-chip">Unmapped {functionStats.mappingScopes?.unmapped || 0}</span>
                </div>
              </div>

              {/* ASIL Source Distribution */}
              <div className="uds-stat-chart-panel">
                <h5>ASIL 소스 분포</h5>
                {[
                  { label: "주석(@asil)", value: functionStats.asilSources?.comment || 0, color: "#4caf50" },
                  { label: "SRS", value: functionStats.asilSources?.srs || 0, color: "#2196f3" },
                  { label: "SDS", value: functionStats.asilSources?.sds || 0, color: "#ff9800" },
                  { label: "모듈 상속", value: functionStats.asilSources?.module_inherit || 0, color: "#9c27b0" },
                  { label: "추론", value: functionStats.asilSources?.inference || 0, color: "#f44336" },
                  { label: "기본값", value: functionStats.asilSources?.default_val || 0, color: "#757575" },
                ].filter((r) => r.value > 0).map((row) => {
                  const pct = functionStats.total > 0 ? (row.value / functionStats.total) * 100 : 0;
                  return (
                    <div key={row.label} className="uds-stat-row">
                      <span className="uds-stat-label">{row.label}</span>
                      <div className="uds-stat-bar">
                        <div
                          className="uds-stat-bar-fill"
                          style={{ width: `${pct}%`, background: row.color }}
                          title={`${row.value}/${functionStats.total} (${pct.toFixed(1)}%)`}
                        />
                      </div>
                      <span className="uds-stat-num">{row.value}</span>
                    </div>
                  );
                })}
                <div style={{ marginTop: "8px", fontSize: "0.85rem", color: "var(--fg-dim, #888)" }}>
                  ASIL 지정됨: {functionStats.asilNonTbd || 0}/{functionStats.total} |
                  Related 지정됨: {functionStats.relatedNonTbd || 0}/{functionStats.total}
                </div>
                {functionStats.total > 0 && (functionStats.asilSources?.inference || 0) > functionStats.total * 0.5 && (
                  <div style={{ marginTop: "6px", padding: "6px 10px", background: "rgba(255,152,0,0.1)", borderRadius: "6px", fontSize: "0.85rem", color: "#ff9800" }}>
                    ASIL 추론 비율이 높습니다. SRS/SDS 문서를 추가하거나, 코드에 @asil 태그를 추가하면 정확도가 향상됩니다.
                  </div>
                )}
              </div>
              <div className="uds-stat-chart-panel">
                <h5>ASIL TBD Trace</h5>
                <div className="uds-summary-chip-row">
                  <span className="uds-meta-chip">Residual TBD {toList(functionStats.unresolvedAsilRows).length}</span>
                  <span className="uds-meta-chip">Mapped ASIL {functionStats.asilNonTbd || 0}</span>
                </div>
                {toList(functionStats.unresolvedAsilRows).length > 0 ? (
                  <div className="uds-unresolved-list">
                    {toList(functionStats.unresolvedAsilRows).slice(0, 12).map((row) => (
                      <div key={`${row.id}-${row.name}`} className="uds-unresolved-item">
                        <div>
                          <strong>{row.id || "-"}</strong> {row.name || "-"}
                        </div>
                        <div className="hint">{row.swcom || "-"}</div>
                        <div className="hint">{row.reason}</div>
                        {row.sds_match_key || row.sds_match_mode ? (
                          <div className="hint">
                            {row.sds_match_key ? `key=${row.sds_match_key}` : "-"}
                            {row.sds_match_mode ? ` / mode=${row.sds_match_mode}` : ""}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="hint">Current mapping run has no remaining ASIL TBD functions.</div>
                )}
              </div>
            </div>
          ) : null}

          {tab === "functions" ? (
            <>
              <div className="row uds-toolbar">
                <input
                  placeholder="함수 ID/이름/Prototype/Description 검색"
                  value={query}
                  onChange={(e) => {
                    setQuery(e.target.value);
                    setPage(1);
                  }}
                />
                <select value={swcomFilter} onChange={(e) => setSwcomFilter(e.target.value)}>
                  {swcomOptions.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
                <select value={asilFilter} onChange={(e) => setAsilFilter(e.target.value)}>
                  {asilOptions.map((item) => (
                    <option key={item} value={item}>
                      {item}
                    </option>
                  ))}
                </select>
                {!serverMode ? (
                  <button
                    type="button"
                    className="btn-outline btn-xs"
                    onClick={() => setFiltersOpen((p) => !p)}
                  >
                    {filtersOpen ? "필터 접기 ▲" : "필터 펼치기 ▼"}
                  </button>
                ) : null}
                <button type="button" className="btn-outline" onClick={exportFunctionCsv}>
                  함수 CSV
                </button>
              </div>
              {!serverMode && filtersOpen ? (
                <div className="uds-filter-panel">
                  <select value={hasInputFilter} onChange={(e) => setHasInputFilter(e.target.value)}>
                    <option value="all">Input 전체</option>
                    <option value="yes">Input 있음</option>
                    <option value="no">Input 없음</option>
                  </select>
                  <select value={hasOutputFilter} onChange={(e) => setHasOutputFilter(e.target.value)}>
                    <option value="all">Output 전체</option>
                    <option value="yes">Output 있음</option>
                    <option value="no">Output 없음</option>
                  </select>
                  <select value={hasCalledFilter} onChange={(e) => setHasCalledFilter(e.target.value)}>
                    <option value="all">Called 전체</option>
                    <option value="yes">Called 있음</option>
                    <option value="no">Called 없음</option>
                  </select>
                  <select value={hasCallingFilter} onChange={(e) => setHasCallingFilter(e.target.value)}>
                    <option value="all">Calling 전체</option>
                    <option value="yes">Calling 있음</option>
                    <option value="no">Calling 없음</option>
                  </select>
                  <select value={sortKey} onChange={(e) => setSortKey(e.target.value)}>
                    <option value="id">정렬: ID</option>
                    <option value="name">정렬: 함수명</option>
                    <option value="swcom">정렬: SwCom</option>
                    <option value="called_count">정렬: Called 개수</option>
                    <option value="calling_count">정렬: Calling 개수</option>
                  </select>
                  <select value={sortDir} onChange={(e) => setSortDir(e.target.value)}>
                    <option value="asc">오름차순</option>
                    <option value="desc">내림차순</option>
                  </select>
                </div>
              ) : null}

              <div className="hint">
                {totalFunctions}개 함수 / {effectivePage} / {totalPages} 페이지
              </div>

              <div className="uds-table-wrap" ref={listPaneRef}>
                <table className="uds-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Function</th>
                      <th>SwCom</th>
                      <th>ASIL</th>
                      <th>Input</th>
                      <th>Output</th>
                      <th>Called</th>
                      <th>Calling</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pageItems.map((fn) => {
                      const key = `${toText(fn.id)}::${toText(fn.name)}`;
                      const active = selectedFn && key === `${toText(selectedFn.id)}::${toText(selectedFn.name)}`;
                      return (
                        <tr key={key} className={active ? "active" : ""}>
                          <td>{toText(fn.id) || "-"}</td>
                          <td title={toText(fn.prototype) || "-"}>
                            <button
                              type="button"
                              className="uds-table-link"
                              onClick={() => setSelectedFnKey(key)}
                            >
                              {toText(fn.name) || "-"}
                            </button>
                            {renderMappingBadges(fn)}
                          </td>
                          <td>{toSwCom(fn)}</td>
                          <td>{toText(fn.asil) || "-"}</td>
                          <td>{countList(fn?.inputs)}</td>
                          <td>{countList(fn?.outputs)}</td>
                          <td>{countList(fn?.called)}</td>
                          <td>{countList(fn?.calling)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="panel uds-detail-pane" ref={detailPaneRef}>
                <h4>함수 상세</h4>
                {selectedFn ? (
                  <>
                    <div className="detail-row compact">
                      <span className="detail-label">ID</span>
                      <span className="detail-value">{toText(selectedFn.id) || "-"}</span>
                    </div>
                    <div className="detail-row compact">
                      <span className="detail-label">SwCom</span>
                      <span className="detail-value">{toSwCom(selectedFn)}</span>
                    </div>
                    <div className="detail-row compact">
                      <span className="detail-label">Mapping</span>
                      <span className="detail-value">
                        {renderMappingBadges(selectedFn) || "N/A"}
                      </span>
                    </div>
                    <div className="detail-row compact">
                      <span className="detail-label">Prototype</span>
                      <span className="detail-value" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>
                        {toText(selectedFn.prototype) || "-"}
                      </span>
                    </div>
                    <div className="detail-row compact">
                      <span className="detail-label">Description</span>
                      <span className="detail-value" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
                        {toText(selectedFn.description) || "-"}
                      </span>
                    </div>
                    <div className="detail-row compact">
                      <span className="detail-label">Input</span>
                      <span className="detail-value">{renderStructuredValues(selectedFn.inputs)}</span>
                    </div>
                    <div className="detail-row compact">
                      <span className="detail-label">Output</span>
                      <span className="detail-value">{renderStructuredValues(selectedFn.outputs)}</span>
                    </div>
                    <div className="detail-row compact">
                      <span className="detail-label">Global</span>
                      <span className="detail-value">{renderStructuredValues(selectedFn.globals_global)}</span>
                    </div>
                    <div className="detail-row compact">
                      <span className="detail-label">Static</span>
                      <span className="detail-value">{renderStructuredValues(selectedFn.globals_static)}</span>
                    </div>
                    <div className="detail-row compact">
                      <span className="detail-label">Called</span>
                      <span className="detail-value">
                        {toList(selectedFn.called).length > 0
                          ? toList(selectedFn.called).map((name, idx) => (
                              <button
                                key={`${name}-${idx}`}
                                type="button"
                                className="btn-chip"
                                onClick={() => jumpToFunction(name)}
                              >
                                {toText(name)}
                              </button>
                            ))
                          : "N/A"}
                      </span>
                    </div>
                    <div className="detail-row compact">
                      <span className="detail-label">Calling</span>
                      <span className="detail-value">
                        {toList(selectedFn.calling).length > 0
                          ? toList(selectedFn.calling).map((name, idx) => (
                              <button
                                key={`${name}-${idx}`}
                                type="button"
                                className="btn-chip"
                                onClick={() => jumpToFunction(name)}
                              >
                                {toText(name)}
                              </button>
                            ))
                          : "N/A"}
                      </span>
                    </div>
                    <div className="detail-row compact">
                      <span className="detail-label">관계 그래프(1-hop)</span>
                      <span className="detail-value">
                        <MiniRelationGraph
                          fn={selectedFn}
                          fnByName={fnByName}
                          activeNodeName={graphActiveName || toText(selectedFn?.name)}
                          onNodeClick={(name) => {
                            setGraphActiveName(toText(name));
                            jumpToFunction(name);
                          }}
                        />
                      </span>
                    </div>
                  </>
                ) : (
                  <div className="hint">함수를 선택해주세요.</div>
                )}
              </div>

              <div className="uds-pagination">
                <button
                  type="button"
                  className="btn-outline btn-xs"
                  disabled={effectivePage <= 1}
                  onClick={() => setPage(1)}
                >
                  &laquo;
                </button>
                <button
                  type="button"
                  className="btn-outline btn-xs"
                  disabled={effectivePage <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  &lsaquo;
                </button>
                {(() => {
                  const pages = [];
                  const range = 2;
                  let start = Math.max(1, effectivePage - range);
                  let end = Math.min(totalPages, effectivePage + range);
                  if (start > 1) pages.push(<span key="ds" className="uds-page-dots">&hellip;</span>);
                  for (let i = start; i <= end; i++) {
                    pages.push(
                      <button
                        key={i}
                        type="button"
                        className={`btn-outline btn-xs ${i === effectivePage ? "active" : ""}`}
                        onClick={() => setPage(i)}
                      >
                        {i}
                      </button>
                    );
                  }
                  if (end < totalPages) pages.push(<span key="de" className="uds-page-dots">&hellip;</span>);
                  return pages;
                })()}
                <button
                  type="button"
                  className="btn-outline btn-xs"
                  disabled={effectivePage >= totalPages}
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                >
                  &rsaquo;
                </button>
                <button
                  type="button"
                  className="btn-outline btn-xs"
                  disabled={effectivePage >= totalPages}
                  onClick={() => setPage(totalPages)}
                >
                  &raquo;
                </button>
              </div>
            </>
          ) : null}

          {tab === "traceability" ? (
            <>
              <div className="row uds-toolbar">
                <input
                  placeholder="요구사항/함수 ID/함수명 검색"
                  value={traceQuery}
                  onChange={(e) => setTraceQuery(e.target.value)}
                />
                <select value={traceMode} onChange={(e) => setTraceMode(e.target.value)}>
                  <option value="flat">행 단위</option>
                  <option value="by_requirement">요구사항 기준 그룹</option>
                  <option value="by_function">함수 기준 그룹</option>
                  <option value="reverse_chain">역추적 체인</option>
                </select>
                {traceMode === "reverse_chain" ? (
                  <select
                    value={String(traceDepth)}
                    onChange={(e) => setTraceDepth(Math.max(1, Math.min(2, Number(e.target.value) || 1)))}
                  >
                    <option value="1">깊이 1-hop</option>
                    <option value="2">깊이 2-hop</option>
                  </select>
                ) : null}
                <button type="button" className="btn-outline" onClick={exportTraceCsv}>
                  추적성 CSV
                </button>
              </div>

              {traceMode === "flat" ? (
                <div className="list uds-list-pane" ref={tracePaneRef}>
                  {filteredTraceability.slice(0, traceBatch).map((row, idx) => {
                    const prevReq = idx > 0 ? toText(filteredTraceability[idx - 1]?.requirement_id) : null;
                    const curReq = toText(row.requirement_id) || "-";
                    const showHeader = curReq !== prevReq;
                    return (
                      <div key={`${curReq}-${toText(row.function_id)}-${idx}`}>
                        {showHeader ? (
                          <div className="uds-trace-group-header">{curReq}</div>
                        ) : null}
                        <div className="list-item">
                          <span className="list-snippet">
                            {toText(row.function_id) || "-"} / {toText(row.function_name) || "-"}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                  {filteredTraceability.length > traceBatch ? (
                    <button
                      type="button"
                      className="btn-outline"
                      style={{ marginTop: 6, width: "100%" }}
                      onClick={() => setTraceBatch((p) => p + 200)}
                    >
                      더 보기 ({traceBatch}/{filteredTraceability.length})
                    </button>
                  ) : null}
                </div>
              ) : traceMode === "reverse_chain" ? (
                <>
                  <div className="row">
                    <select value={traceFocusReq} onChange={(e) => setTraceFocusReq(e.target.value)}>
                      <option value="">요구사항 전체</option>
                      {reverseTraceRows.map((row) => (
                        <option key={row.requirementId} value={row.requirementId}>
                          {row.requirementId}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="list uds-list-pane" ref={tracePaneRef}>
                    {reverseTraceFiltered.map((row) => (
                      <div key={row.requirementId} className="list-item">
                        <span className="list-text">{row.requirementId}</span>
                        <div className="uds-trace-chain-list">
                          {row.chains.map((c) => (
                            <div key={`${row.requirementId}-${c.functionId}-${c.functionName}`} className="uds-trace-chain-row">
                              <button type="button" className="btn-chip" onClick={() => jumpToFunction(c.functionName)}>
                                {c.functionId}: {c.functionName}
                              </button>
                              <span className="uds-chain-arrow">→</span>
                              <span className="detail-value">
                                {c.calledChain.length > 0 ? c.calledChain.join(", ") : "N/A"}
                              </span>
                              {traceDepth >= 2 && c.calledChain2.length > 0 ? (
                                <div className="uds-trace-hop2">
                                  {c.calledChain2.map((hop2Row) => (
                                    <div key={`${c.functionName}-${hop2Row.from}`} className="uds-trace-chain-row">
                                      <button type="button" className="btn-chip" onClick={() => jumpToFunction(hop2Row.from)}>
                                        {hop2Row.from}
                                      </button>
                                      <span className="uds-chain-arrow">→</span>
                                      <span className="detail-value">
                                        {hop2Row.to.length > 0 ? hop2Row.to.join(", ") : "N/A"}
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="list uds-list-pane" ref={tracePaneRef}>
                  {groupedTraceability.map((row) => (
                    <div className="list-item" key={row.key}>
                      <span className="list-text">{row.key}</span>
                      <span className="list-snippet">{row.count}건</span>
                      <div className="detail-value">{row.values.join(", ")}</div>
                    </div>
                  ))}
                </div>
              )}

              {filteredTraceability.length === 0 ? <div className="empty">추적성 데이터 없음</div> : null}
            </>
          ) : null}

          {tab === "globals" ? (
            (() => {
              const GLOBALS_PAGE_SIZE = 30;
              const allGlobals = toList(globalsData?.globals);
              const token = globalsQuery.trim().toLowerCase();
              const filtered = allGlobals.filter((g) => {
                if (globalsScope !== "all" && g?.scope !== globalsScope) return false;
                if (!token) return true;
                return (
                  toText(g?.name).toLowerCase().includes(token) ||
                  toText(g?.type).toLowerCase().includes(token) ||
                  toText(g?.file).toLowerCase().includes(token) ||
                  toText(g?.desc).toLowerCase().includes(token) ||
                  toList(g?.used_by).some((fn) => toText(fn).toLowerCase().includes(token))
                );
              });
              const dir = globalsSortDir === "desc" ? -1 : 1;
              const sorted = [...filtered].sort((a, b) => {
                const av = globalsSortKey === "used_count" ? toList(a?.used_by).length : toText(a?.[globalsSortKey] || "");
                const bv = globalsSortKey === "used_count" ? toList(b?.used_by).length : toText(b?.[globalsSortKey] || "");
                if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
                return toText(av).localeCompare(toText(bv), undefined, { sensitivity: "base" }) * dir;
              });
              const gTotalPages = Math.max(1, Math.ceil(sorted.length / GLOBALS_PAGE_SIZE));
              const gEffectivePage = Math.min(Math.max(1, globalsPage), gTotalPages);
              const gPageItems = sorted.slice((gEffectivePage - 1) * GLOBALS_PAGE_SIZE, gEffectivePage * GLOBALS_PAGE_SIZE);

              const exportGlobalsCsv = () => {
                const rows = sorted.map((g) => ({
                  name: toText(g?.name),
                  type: toText(g?.type),
                  scope: toText(g?.scope),
                  range: toText(g?.range),
                  init: toText(g?.init),
                  file: toText(g?.file),
                  desc: toText(g?.desc),
                  used_by: toList(g?.used_by).join("; "),
                }));
                downloadText(
                  "uds_globals.csv",
                  toCsv(
                    [
                      { key: "name", label: "Name" },
                      { key: "type", label: "Type" },
                      { key: "scope", label: "Scope" },
                      { key: "range", label: "Range" },
                      { key: "init", label: "Init Value" },
                      { key: "file", label: "File" },
                      { key: "desc", label: "Description" },
                      { key: "used_by", label: "Used By" },
                    ],
                    rows
                  )
                );
              };

              return (
                <>
                  <div className="row uds-toolbar">
                    <input
                      placeholder="변수명, 타입, 파일, 사용함수 검색"
                      value={globalsQuery}
                      onChange={(e) => { setGlobalsQuery(e.target.value); setGlobalsPage(1); }}
                    />
                    <select value={globalsScope} onChange={(e) => { setGlobalsScope(e.target.value); setGlobalsPage(1); }}>
                      <option value="all">전체</option>
                      <option value="global">Global</option>
                      <option value="static">Static</option>
                    </select>
                    <select value={globalsSortKey} onChange={(e) => setGlobalsSortKey(e.target.value)}>
                      <option value="name">정렬: 변수명</option>
                      <option value="type">정렬: 타입</option>
                      <option value="scope">정렬: Scope</option>
                      <option value="file">정렬: 파일</option>
                      <option value="used_count">정렬: 사용 함수 수</option>
                    </select>
                    <select value={globalsSortDir} onChange={(e) => setGlobalsSortDir(e.target.value)}>
                      <option value="asc">오름차순</option>
                      <option value="desc">내림차순</option>
                    </select>
                    <button type="button" className="btn-outline" onClick={requestGlobals} disabled={advancedLoading}>
                      Globals 로드
                    </button>
                    {allGlobals.length > 0 ? (
                      <button type="button" className="btn-outline" onClick={exportGlobalsCsv}>
                        CSV
                      </button>
                    ) : null}
                  </div>

                  {allGlobals.length > 0 ? (
                    <>
                      <div className="uds-globals-kpi-row" style={{ display: "flex", gap: 12, marginBottom: 8 }}>
                        <span className="uds-meta-chip">전체 {allGlobals.length}</span>
                        <span className="uds-meta-chip">Global {globalsData?.total_global ?? 0}</span>
                        <span className="uds-meta-chip">Static {globalsData?.total_static ?? 0}</span>
                        <span className="uds-meta-chip">필터 결과 {filtered.length}</span>
                      </div>
                      <div className="hint">
                        {filtered.length}개 변수 / {gEffectivePage} / {gTotalPages} 페이지
                      </div>
                      <div className="uds-table-wrap">
                        <table className="uds-table">
                          <thead>
                            <tr>
                              <th>Name</th>
                              <th>Type</th>
                              <th>Scope</th>
                              <th>Range</th>
                              <th>Init</th>
                              <th>File</th>
                              <th>Used By</th>
                            </tr>
                          </thead>
                          <tbody>
                            {gPageItems.map((g, idx) => (
                              <tr key={`${toText(g?.name)}-${toText(g?.scope)}-${idx}`}>
                                <td title={toText(g?.desc)}><strong>{toText(g?.name) || "-"}</strong></td>
                                <td><code>{toText(g?.type) || "-"}</code></td>
                                <td>
                                  <span className={`uds-scope-badge ${g?.scope === "static" ? "scope-static" : "scope-global"}`}>
                                    {toText(g?.scope)}
                                  </span>
                                </td>
                                <td>{toText(g?.range) || "-"}</td>
                                <td><code>{toText(g?.init) || "-"}</code></td>
                                <td className="hint" title={toText(g?.file)}>
                                  {(() => {
                                    const f = toText(g?.file);
                                    return f ? f.split(/[\\/]/).pop() : "-";
                                  })()}
                                </td>
                                <td>
                                  {toList(g?.used_by).length > 0
                                    ? toList(g?.used_by).slice(0, 8).map((fn, fi) => (
                                        <button
                                          key={`${fn}-${fi}`}
                                          type="button"
                                          className="btn-chip"
                                          onClick={() => { setTab("functions"); jumpToFunction(fn); }}
                                        >
                                          {toText(fn)}
                                        </button>
                                      ))
                                    : <span className="hint">-</span>}
                                  {toList(g?.used_by).length > 8 ? (
                                    <span className="hint"> +{toList(g?.used_by).length - 8}</span>
                                  ) : null}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      <div className="uds-pagination">
                        <button type="button" className="btn-outline btn-xs" disabled={gEffectivePage <= 1} onClick={() => setGlobalsPage(1)}>&laquo;</button>
                        <button type="button" className="btn-outline btn-xs" disabled={gEffectivePage <= 1} onClick={() => setGlobalsPage((p) => Math.max(1, p - 1))}>&lsaquo;</button>
                        {(() => {
                          const pages = [];
                          const range = 2;
                          let start = Math.max(1, gEffectivePage - range);
                          let end = Math.min(gTotalPages, gEffectivePage + range);
                          if (start > 1) pages.push(<span key="ds" className="uds-page-dots">&hellip;</span>);
                          for (let i = start; i <= end; i++) {
                            pages.push(
                              <button key={i} type="button" className={`btn-outline btn-xs ${i === gEffectivePage ? "active" : ""}`} onClick={() => setGlobalsPage(i)}>{i}</button>
                            );
                          }
                          if (end < gTotalPages) pages.push(<span key="de" className="uds-page-dots">&hellip;</span>);
                          return pages;
                        })()}
                        <button type="button" className="btn-outline btn-xs" disabled={gEffectivePage >= gTotalPages} onClick={() => setGlobalsPage((p) => Math.min(gTotalPages, p + 1))}>&rsaquo;</button>
                        <button type="button" className="btn-outline btn-xs" disabled={gEffectivePage >= gTotalPages} onClick={() => setGlobalsPage(gTotalPages)}>&raquo;</button>
                      </div>
                    </>
                  ) : (
                    <div className="empty">Globals 로드 버튼을 클릭하여 전역/정적 변수를 조회하세요.</div>
                  )}
                </>
              );
            })()
          ) : null}

          {tab === "call_graph" ? (
            <>
              <div className="row uds-toolbar">
                <select value={String(graphDepth)} onChange={(e) => setGraphDepth(Math.max(1, Math.min(6, Number(e.target.value) || 2)))}>
                  <option value="1">Depth 1</option>
                  <option value="2">Depth 2</option>
                  <option value="3">Depth 3</option>
                  <option value="4">Depth 4</option>
                  <option value="5">Depth 5</option>
                  <option value="6">Depth 6</option>
                </select>
                <button type="button" className="btn-outline" onClick={requestCallGraph}>
                  그래프 로드
                </button>
                <div className="uds-view-toggle">
                  <button
                    type="button"
                    className={`btn-outline btn-xs ${callGraphView === "graph" ? "active" : ""}`}
                    onClick={() => setCallGraphView("graph")}
                  >
                    그래프
                  </button>
                  <button
                    type="button"
                    className={`btn-outline btn-xs ${callGraphView === "table" ? "active" : ""}`}
                    onClick={() => setCallGraphView("table")}
                  >
                    테이블
                  </button>
                </div>
              </div>
              <div className="uds-graph-meta-row">
                <span className="uds-meta-chip">노드 {toText(callGraphData?.meta?.node_count) || "0"}</span>
                <span className="uds-meta-chip">엣지 {toText(callGraphData?.meta?.edge_count) || "0"}</span>
              </div>
              {callGraphView === "graph" ? (
                toList(callGraphData?.edges).length > 0 ? (
                  <ForceGraph
                    edges={toList(callGraphData?.edges)}
                    focusNode={toText(selectedFn?.name)}
                    onNodeClick={(name) => jumpToFunction(name)}
                    height={480}
                  />
                ) : (
                  <div className="empty">그래프 로드 버튼을 클릭하여 Call Graph를 생성하세요.</div>
                )
              ) : (
                <div className="compact-table">
                  <table className="compact-table-grid">
                    <thead>
                      <tr>
                        <th>Source</th>
                        <th>Target</th>
                      </tr>
                    </thead>
                    <tbody>
                      {toList(callGraphData?.edges).slice(0, 500).map((row, idx) => (
                        <tr key={`${toText(row?.source)}-${toText(row?.target)}-${idx}`}>
                          <td>{toText(row?.source)}</td>
                          <td>{toText(row?.target)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          ) : null}

          {tab === "dependency_map" ? (
            <>
              <div className="row uds-toolbar">
                <select value={depLevel} onChange={(e) => setDepLevel(e.target.value)}>
                  <option value="module">Module(SwCom)</option>
                  <option value="function">Function</option>
                </select>
                <button type="button" className="btn-outline" onClick={requestDependencyMap}>
                  맵 로드
                </button>
                <div className="uds-view-toggle">
                  <button
                    type="button"
                    className={`btn-outline btn-xs ${depMapView === "graph" ? "active" : ""}`}
                    onClick={() => setDepMapView("graph")}
                  >
                    그래프
                  </button>
                  <button
                    type="button"
                    className={`btn-outline btn-xs ${depMapView === "table" ? "active" : ""}`}
                    onClick={() => setDepMapView("table")}
                  >
                    테이블
                  </button>
                </div>
              </div>
              <div className="uds-graph-meta-row">
                <span className="uds-meta-chip">노드 {toText(depMapData?.meta?.node_count) || "0"}</span>
                <span className="uds-meta-chip">엣지 {toText(depMapData?.meta?.edge_count) || "0"}</span>
              </div>
              {depMapView === "graph" ? (
                toList(depMapData?.edges).length > 0 ? (
                  <ForceGraph
                    edges={toList(depMapData?.edges)}
                    focusNode=""
                    onNodeClick={(name) => jumpToFunction(name)}
                    height={480}
                  />
                ) : (
                  <div className="empty">맵 로드 버튼을 클릭하여 Dependency Map을 생성하세요.</div>
                )
              ) : (
                <div className="compact-table">
                  <table className="compact-table-grid">
                    <thead>
                      <tr>
                        <th>From</th>
                        <th>To</th>
                      </tr>
                    </thead>
                    <tbody>
                      {toList(depMapData?.edges).slice(0, 500).map((row, idx) => (
                        <tr key={`${toText(row?.source)}-${toText(row?.target)}-${idx}`}>
                          <td>{toText(row?.source)}</td>
                          <td>{toText(row?.target)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          ) : null}

          {tab === "code_preview" ? (
            <>
              <div className="row uds-toolbar">
                <button type="button" className="btn-outline" onClick={requestCodePreview}>
                  코드 프리뷰 로드
                </button>
              </div>
              <div className="uds-code-sig">
                <span className="detail-label">함수</span>
                <code className="uds-sig-text">{toText(codePreviewData?.signature) || toText(selectedFn?.name) || "-"}</code>
              </div>
              <CodeHighlight
                code={toText(codePreviewData?.code)}
                language="c"
                maxHeight={560}
              />
            </>
          ) : null}

          {tab === "impact" ? (
            <>
              <div className="row uds-toolbar">
                <input
                  placeholder="changed files (comma/newline)"
                  value={impactChangedRaw}
                  onChange={(e) => setImpactChangedRaw(e.target.value)}
                  style={{ flex: 1 }}
                />
                <button type="button" className="btn-outline" onClick={requestImpactAnalyze}>
                  영향도 분석
                </button>
              </div>
              {impactData ? (
                <div className="uds-impact-result">
                  <div className="uds-impact-kpi-row">
                    <div className="uds-impact-kpi">
                      <div className="uds-impact-kpi-num">{toText(impactData?.seed_function_count) || "0"}</div>
                      <div className="uds-impact-kpi-label">Seed 함수</div>
                    </div>
                    <div className="uds-impact-arrow">&#8594;</div>
                    <div className="uds-impact-kpi accent">
                      <div className="uds-impact-kpi-num">{toText(impactData?.impacted_function_count) || "0"}</div>
                      <div className="uds-impact-kpi-label">영향받는 함수</div>
                    </div>
                    <div className="uds-impact-kpi">
                      <div className="uds-impact-kpi-num">{toList(impactData?.impacted_swcom).length}</div>
                      <div className="uds-impact-kpi-label">SwCom</div>
                    </div>
                  </div>
                  {toList(impactData?.impacted_swcom).length > 0 ? (
                    <div className="uds-impact-swcom-grid">
                      {toList(impactData?.impacted_swcom).map((sw) => (
                        <span key={sw} className="uds-impact-swcom-chip">{sw}</span>
                      ))}
                    </div>
                  ) : null}
                  {toList(impactData?.impacted_functions).length > 0 ? (
                    <div className="uds-impact-table-wrap">
                      <table className="uds-table">
                        <thead>
                          <tr>
                            <th>함수명</th>
                            <th>SwCom</th>
                            <th>영향 경로</th>
                          </tr>
                        </thead>
                        <tbody>
                          {toList(impactData?.impacted_functions).slice(0, 100).map((fn, idx) => (
                            <tr key={`${toText(fn?.name)}-${idx}`}>
                              <td>
                                <button type="button" className="uds-table-link" onClick={() => jumpToFunction(toText(fn?.name))}>
                                  {toText(fn?.name) || "-"}
                                </button>
                              </td>
                              <td>{toText(fn?.swcom) || "-"}</td>
                              <td className="hint">{toText(fn?.path || fn?.reason) || "-"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}
                  {toList(impactData?.seed_functions).length > 0 ? (
                    <details className="uds-impact-details">
                      <summary>Seed 함수 목록 ({toList(impactData?.seed_functions).length})</summary>
                      <div className="uds-impact-seed-list">
                        {toList(impactData?.seed_functions).map((fn, idx) => (
                          <span key={idx} className="btn-chip" onClick={() => jumpToFunction(toText(fn?.name || fn))}>
                            {toText(fn?.name || fn)}
                          </span>
                        ))}
                      </div>
                    </details>
                  ) : null}
                </div>
              ) : (
                <div className="empty">변경 파일을 입력하고 영향도 분석 버튼을 클릭하세요.</div>
              )}
            </>
          ) : null}

          {tab === "test_data" ? (
            <>
              <div className="row uds-toolbar">
                <select value={testStrategy} onChange={(e) => setTestStrategy(e.target.value)}>
                  <option value="boundary">boundary</option>
                  <option value="equivalence">equivalence</option>
                  <option value="stub">stub</option>
                  <option value="domain_ai">domain_ai</option>
                </select>
                <button type="button" className="btn-outline" onClick={requestTestGenerate}>
                  테스트 데이터 생성
                </button>
              </div>
              {toList(testData?.cases).length > 0 ? (
                <div className="uds-test-cases">
                  <div className="uds-test-cases-header">
                    <span className={`uds-strategy-badge strat-${testStrategy}`}>{testStrategy}</span>
                    <span className="hint">{toList(testData?.cases).length}개 케이스</span>
                  </div>
                  <div className="uds-test-case-grid">
                    {toList(testData?.cases).map((tc, idx) => (
                      <div key={idx} className="uds-test-case-card">
                        <div className="uds-test-case-num">#{idx + 1}</div>
                        {toText(tc?.description || tc?.name) ? (
                          <div className="uds-test-case-desc">{toText(tc?.description || tc?.name)}</div>
                        ) : null}
                        {tc?.inputs !== undefined ? (
                          <div className="uds-test-case-row">
                            <span className="uds-test-case-label">Input</span>
                            <span className="uds-test-case-value">
                              {typeof tc.inputs === "object" ? JSON.stringify(tc.inputs) : toText(tc.inputs)}
                            </span>
                          </div>
                        ) : null}
                        {tc?.expected !== undefined || tc?.expected_output !== undefined ? (
                          <div className="uds-test-case-row">
                            <span className="uds-test-case-label">Expected</span>
                            <span className="uds-test-case-value">
                              {typeof (tc.expected ?? tc.expected_output) === "object"
                                ? JSON.stringify(tc.expected ?? tc.expected_output)
                                : toText(tc.expected ?? tc.expected_output)}
                            </span>
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
              {toText(testData?.test_code) ? (
                <CodeHighlight code={toText(testData?.test_code)} language="c" maxHeight={480} />
              ) : testData == null ? (
                <div className="empty">전략을 선택하고 테스트 데이터 생성 버튼을 클릭하세요.</div>
              ) : null}
            </>
          ) : null}
        </>
      ) : null}
    </div>
  );
};

export default UdsResultViewer;
