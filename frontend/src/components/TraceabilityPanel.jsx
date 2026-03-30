import { useState, useCallback, useMemo, useRef, useEffect } from "react";

const API = "";

const STATUS_COLORS = {
  covered: "#4caf50",
  partial: "#ff9800",
  uncovered: "#f44336",
};

const STATUS_LABELS = {
  covered: "완전 커버",
  partial: "부분 커버",
  uncovered: "미커버",
};

const ASIL_COLORS = {
  A: "#e3f2fd",
  B: "#fff3e0",
  C: "#fce4ec",
  D: "#f3e5f5",
  QM: "#f5f5f5",
};

// ── Flow Diagram (SRS → UDS → STS / SUTS) ───────────────────────────

function FlowDiagram({ rows }) {
  const svgRef = useRef(null);
  const reqs = rows.filter((r) => r.func_count > 0 || r.tc_count > 0 || (r.suts_tc_count || 0) > 0).slice(0, 40);
  const funcSet = new Set();
  const stsTcSet = new Set();
  const sutsTcSet = new Set();
  reqs.forEach((r) => {
    (r.func_names || []).forEach((f) => funcSet.add(f));
    (r.tc_ids || []).forEach((t) => stsTcSet.add(t));
    (r.suts_tc_ids || []).forEach((t) => sutsTcSet.add(t));
  });
  const funcs = [...funcSet].slice(0, 50);
  const stsTcs = [...stsTcSet].slice(0, 50);
  const sutsTcs = [...sutsTcSet].slice(0, 50);

  const COL_W = 180;
  const ROW_H = 22;
  const PAD = 20;
  const COL_GAP = 100;
  const col0X = PAD;
  const col1X = PAD + COL_W + COL_GAP;
  const col2X = PAD + (COL_W + COL_GAP) * 2;
  const col3X = PAD + (COL_W + COL_GAP) * 3;
  const totalW = col3X + COL_W + PAD;
  const maxRows = Math.max(reqs.length, funcs.length, stsTcs.length, sutsTcs.length, 1);
  const totalH = PAD * 2 + 30 + maxRows * ROW_H;

  const posY = (i) => PAD + 30 + i * ROW_H + ROW_H / 2;

  const funcIdx = Object.fromEntries(funcs.map((f, i) => [f, i]));
  const stsIdx = Object.fromEntries(stsTcs.map((t, i) => [t, i]));
  const sutsIdx = Object.fromEntries(sutsTcs.map((t, i) => [t, i]));

  const lines1 = [];
  const lines2 = [];
  const lines3 = [];
  reqs.forEach((r, ri) => {
    (r.func_names || []).forEach((f) => {
      if (funcIdx[f] !== undefined) {
        lines1.push({ x1: col0X + COL_W, y1: posY(ri), x2: col1X, y2: posY(funcIdx[f]), status: r.status });
      }
    });
    (r.tc_ids || []).forEach((t) => {
      if (stsIdx[t] !== undefined) {
        lines2.push({ x1: col1X + COL_W, y1: posY(ri), x2: col2X, y2: posY(stsIdx[t]), status: r.status });
      }
    });
    (r.suts_tc_ids || []).forEach((t) => {
      if (sutsIdx[t] !== undefined) {
        lines3.push({ x1: col1X + COL_W, y1: posY(ri), x2: col3X, y2: posY(sutsIdx[t]), status: "suts" });
      }
    });
  });

  if (reqs.length === 0) {
    return <div className="empty" style={{ padding: "20px", textAlign: "center", opacity: 0.6 }}>연결된 요구사항이 없습니다. 소스코드를 포함하여 분석해주세요.</div>;
  }

  return (
    <div style={{ overflowX: "auto", overflowY: "auto", maxHeight: "520px", border: "1px solid var(--border, #444)", borderRadius: "6px" }}>
      <svg ref={svgRef} width={totalW} height={totalH} style={{ background: "var(--bg, #0d1117)", display: "block" }}>
        <text x={col0X + COL_W / 2} y={PAD + 12} textAnchor="middle" fill="#aaa" fontSize="12" fontWeight="700">SRS Requirements</text>
        <text x={col1X + COL_W / 2} y={PAD + 12} textAnchor="middle" fill="#aaa" fontSize="12" fontWeight="700">UDS Functions</text>
        <text x={col2X + COL_W / 2} y={PAD + 12} textAnchor="middle" fill="#aaa" fontSize="12" fontWeight="700">STS Test Cases</text>
        <text x={col3X + COL_W / 2} y={PAD + 12} textAnchor="middle" fill="#e91e63" fontSize="12" fontWeight="700">SUTS Unit Tests</text>

        {lines1.map((l, i) => (
          <path key={`l1-${i}`} d={`M${l.x1},${l.y1} C${l.x1 + 50},${l.y1} ${l.x2 - 50},${l.y2} ${l.x2},${l.y2}`}
            fill="none" stroke={STATUS_COLORS[l.status] || "#666"} strokeWidth="1.2" opacity="0.4" />
        ))}
        {lines2.map((l, i) => (
          <path key={`l2-${i}`} d={`M${l.x1},${l.y1} C${l.x1 + 50},${l.y1} ${l.x2 - 50},${l.y2} ${l.x2},${l.y2}`}
            fill="none" stroke={STATUS_COLORS[l.status] || "#666"} strokeWidth="1.2" opacity="0.4" />
        ))}
        {lines3.map((l, i) => (
          <path key={`l3-${i}`} d={`M${l.x1},${l.y1} C${l.x1 + 50},${l.y1} ${l.x2 - 50},${l.y2} ${l.x2},${l.y2}`}
            fill="none" stroke="#e91e63" strokeWidth="1.2" opacity="0.4" />
        ))}

        {reqs.map((r, i) => (
          <g key={`req-${r.req_id}`}>
            <rect x={col0X} y={posY(i) - 9} width={COL_W} height={18} rx="4" fill={STATUS_COLORS[r.status]} opacity="0.15" stroke={STATUS_COLORS[r.status]} strokeWidth="1" />
            <text x={col0X + 6} y={posY(i) + 4} fill={STATUS_COLORS[r.status]} fontSize="10" fontWeight="600">{r.req_id}</text>
            <text x={col0X + COL_W - 6} y={posY(i) + 4} fill="#888" fontSize="9" textAnchor="end">{r.req_name?.slice(0, 14) || ""}</text>
          </g>
        ))}

        {funcs.map((f, i) => (
          <g key={`fn-${f}`}>
            <rect x={col1X} y={posY(i) - 9} width={COL_W} height={18} rx="4" fill="#2196f3" opacity="0.12" stroke="#2196f3" strokeWidth="1" />
            <text x={col1X + 6} y={posY(i) + 4} fill="#64b5f6" fontSize="10">{f.length > 24 ? f.slice(0, 22) + "…" : f}</text>
          </g>
        ))}

        {stsTcs.map((t, i) => (
          <g key={`sts-${t}`}>
            <rect x={col2X} y={posY(i) - 9} width={COL_W} height={18} rx="4" fill="#00bcd4" opacity="0.12" stroke="#00bcd4" strokeWidth="1" />
            <text x={col2X + 6} y={posY(i) + 4} fill="#4dd0e1" fontSize="10">{t}</text>
          </g>
        ))}

        {sutsTcs.map((t, i) => (
          <g key={`suts-${t}`}>
            <rect x={col3X} y={posY(i) - 9} width={COL_W} height={18} rx="4" fill="#e91e63" opacity="0.12" stroke="#e91e63" strokeWidth="1" />
            <text x={col3X + 6} y={posY(i) + 4} fill="#f48fb1" fontSize="10">{t.length > 24 ? t.slice(0, 22) + "…" : t}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

// ── Heatmap Matrix (Req × Status) ────────────────────────────────────

function HeatmapMatrix({ rows }) {
  const types = [...new Set(rows.map((r) => r.req_type || "OTHER"))].sort();
  const grouped = {};
  types.forEach((t) => { grouped[t] = rows.filter((r) => (r.req_type || "OTHER") === t); });

  const cellSize = 18;
  const labelW = 100;
  const topPad = 40;
  const maxCols = Math.max(...types.map((t) => grouped[t].length), 1);
  const svgW = labelW + maxCols * (cellSize + 2) + 20;
  const svgH = topPad + types.length * (cellSize + 6) + 20;

  return (
    <div style={{ overflowX: "auto", overflowY: "auto", maxHeight: "400px", border: "1px solid var(--border, #444)", borderRadius: "6px" }}>
      <svg width={svgW} height={svgH} style={{ background: "var(--bg, #0d1117)", display: "block" }}>
        <text x={labelW / 2} y={20} textAnchor="middle" fill="#aaa" fontSize="11" fontWeight="600">Type</text>
        <text x={labelW + 10} y={20} fill="#aaa" fontSize="11">각 셀 = 요구사항 1개 (색상 = 커버리지 상태)</text>
        {types.map((t, ti) => {
          const y = topPad + ti * (cellSize + 6);
          return (
            <g key={t}>
              <text x={labelW - 6} y={y + cellSize / 2 + 4} textAnchor="end" fill="#ccc" fontSize="11" fontWeight="600">{t}</text>
              {grouped[t].map((r, ri) => (
                <g key={r.req_id}>
                  <rect
                    x={labelW + ri * (cellSize + 2)}
                    y={y}
                    width={cellSize}
                    height={cellSize}
                    rx="3"
                    fill={STATUS_COLORS[r.status]}
                    opacity={0.85}
                  >
                    <title>{`${r.req_id}: ${r.req_name || ""}\nASIL: ${r.asil || "N/A"}\nFunctions: ${r.func_count}\nSTS TCs: ${r.tc_count}\nSUTS TCs: ${r.suts_tc_count || 0}\nStatus: ${STATUS_LABELS[r.status]}`}</title>
                  </rect>
                  {r.asil && r.asil.toUpperCase() !== "QM" && r.asil.toUpperCase() !== "TBD" && (
                    <text
                      x={labelW + ri * (cellSize + 2) + cellSize / 2}
                      y={y + cellSize / 2 + 4}
                      textAnchor="middle"
                      fill="#fff"
                      fontSize="8"
                      fontWeight="700"
                    >{r.asil}</text>
                  )}
                </g>
              ))}
              <text x={labelW + grouped[t].length * (cellSize + 2) + 6} y={y + cellSize / 2 + 4} fill="#888" fontSize="10">{grouped[t].length}</text>
            </g>
          );
        })}
        {/* Legend */}
        {Object.entries(STATUS_LABELS).map(([k, v], i) => (
          <g key={k} transform={`translate(${labelW + i * 90}, ${svgH - 16})`}>
            <rect width="10" height="10" rx="2" fill={STATUS_COLORS[k]} opacity="0.85" />
            <text x="14" y="9" fill="#aaa" fontSize="10">{v}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

// ── Donut Chart ──────────────────────────────────────────────────────

function DonutChart({ covered, partial, uncovered }) {
  const total = covered + partial + uncovered || 1;
  const r = 50;
  const cx = 65;
  const cy = 65;
  const circumference = 2 * Math.PI * r;

  const segments = [
    { value: covered, color: STATUS_COLORS.covered, label: "완전" },
    { value: partial, color: STATUS_COLORS.partial, label: "부분" },
    { value: uncovered, color: STATUS_COLORS.uncovered, label: "미커버" },
  ];

  let offset = 0;
  return (
    <svg width="130" height="130" viewBox="0 0 130 130">
      {segments.map((s, i) => {
        const dash = (s.value / total) * circumference;
        const el = (
          <circle
            key={i}
            cx={cx} cy={cy} r={r}
            fill="none"
            stroke={s.color}
            strokeWidth="16"
            strokeDasharray={`${dash} ${circumference - dash}`}
            strokeDashoffset={-offset}
            transform={`rotate(-90 ${cx} ${cy})`}
            opacity="0.85"
          />
        );
        offset += dash;
        return el;
      })}
      <text x={cx} y={cy - 4} textAnchor="middle" fill="#fff" fontSize="18" fontWeight="700">
        {Math.round((covered / total) * 100)}%
      </text>
      <text x={cx} y={cy + 12} textAnchor="middle" fill="#aaa" fontSize="9">커버리지</text>
    </svg>
  );
}


// ── Main Panel ────────────────────────────────────────────────────────

export default function TraceabilityPanel({ sourceRoot, pickDirectory, pickFile }) {
  const [srsPath, setSrsPath] = useState("");
  const [traceSourceRoot, setTraceSourceRoot] = useState(sourceRoot || "");
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [expandedRow, setExpandedRow] = useState(null);
  const [viewMode, setViewMode] = useState("table");

  const handlePickDir = useCallback(async (setter) => {
    if (!pickDirectory) return;
    const result = await pickDirectory();
    if (result?.path) setter(result.path);
  }, [pickDirectory]);

  const handlePickFile = useCallback(async (setter) => {
    if (!pickFile) return;
    const result = await pickFile("SRS 문서 선택");
    if (result) setter(result);
  }, [pickFile]);

  const loadTraceability = useCallback(async () => {
    if (!srsPath) { setError("SRS 문서 경로를 입력해주세요."); return; }
    setLoading(true);
    setError("");
    setData(null);
    try {
      const form = new FormData();
      form.append("source_root", traceSourceRoot);
      form.append("srs_path", srsPath);
      const res = await fetch(`${API}/api/local/traceability`, {
        method: "POST",
        body: form,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const result = await res.json();
      setData(result);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [srsPath, traceSourceRoot]);

  const filteredRows = useMemo(() => {
    if (!data?.rows) return [];
    let rows = data.rows;
    if (filter !== "all") rows = rows.filter((r) => r.status === filter);
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      rows = rows.filter((r) =>
        r.req_id.toLowerCase().includes(q) ||
        r.req_name.toLowerCase().includes(q) ||
        (r.func_names || []).some((f) => f.toLowerCase().includes(q)) ||
        (r.tc_ids || []).some((t) => t.toLowerCase().includes(q)) ||
        (r.suts_tc_ids || []).some((t) => t.toLowerCase().includes(q))
      );
    }
    return rows;
  }, [data, filter, search]);

  const summary = data?.summary || {};

  return (
    <div style={{ marginTop: "16px" }}>
      <h4 style={{ margin: "0 0 12px" }}>Traceability Analysis</h4>

      {/* Input */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px", marginBottom: "12px" }}>
        <div>
          <label style={{ fontSize: "0.85rem", fontWeight: 600 }}>SRS 문서 경로</label>
          <div className="row" style={{ gap: "4px" }}>
            <input type="text" value={srsPath} onChange={(e) => setSrsPath(e.target.value)} placeholder="D:\docs\SRS.docx" style={{ flex: 1, fontSize: "0.85rem" }} />
            <button type="button" onClick={() => handlePickFile(setSrsPath)} className="btn-outline" style={{ fontSize: "0.8rem" }}>찾기</button>
          </div>
        </div>
        <div>
          <label style={{ fontSize: "0.85rem", fontWeight: 600 }}>소스 코드 루트</label>
          <div className="row" style={{ gap: "4px" }}>
            <input type="text" value={traceSourceRoot} onChange={(e) => setTraceSourceRoot(e.target.value)} placeholder="소스 코드 경로" style={{ flex: 1, fontSize: "0.85rem" }} />
            <button type="button" onClick={() => handlePickDir(setTraceSourceRoot)} className="btn-outline" style={{ fontSize: "0.8rem" }}>찾기</button>
          </div>
        </div>
      </div>
      <button type="button" onClick={loadTraceability} disabled={loading} style={{ marginBottom: "12px" }}>
        {loading ? "분석 중..." : "추적성 분석 실행"}
      </button>

      {error && <div className="hint" style={{ color: "var(--error, #f44)" }}>{error}</div>}

      {data && (
        <>
          {/* Summary Cards + Donut */}
          <div style={{ display: "flex", gap: "16px", marginBottom: "16px", alignItems: "flex-start" }}>
            <DonutChart covered={summary.covered || 0} partial={summary.partial || 0} uncovered={summary.uncovered || 0} />
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: "8px", flex: 1 }}>
              <SummaryCard label="전체 커버리지" value={`${summary.coverage_pct || 0}%`} sub={`${summary.covered || 0} / ${summary.total_requirements || 0}`} color={STATUS_COLORS.covered} />
              <SummaryCard label="부분 커버" value={summary.partial || 0} sub="일부 단계만 존재" color={STATUS_COLORS.partial} />
              <SummaryCard label="미커버" value={summary.uncovered || 0} sub="함수/TC 없음" color={STATUS_COLORS.uncovered} />
              <SummaryCard label="Safety" value={`${summary.safety_pct || 0}%`} sub={`${summary.safety_covered || 0}/${summary.safety_total || 0} ASIL`} color="#9c27b0" />
              <SummaryCard label="소스 함수" value={summary.total_functions || 0} sub="파싱된 함수" color="#2196f3" />
              <SummaryCard label="STS TC" value={summary.total_sts_test_cases || summary.total_test_cases || 0} sub="통합 테스트" color="#00bcd4" />
              <SummaryCard label="SUTS TC" value={summary.total_suts_test_cases || 0} sub="유닛 테스트" color="#e91e63" />
              <SummaryCard label="SUTS 커버리지" value={`${summary.suts_function_coverage_pct || 0}%`} sub={`${summary.suts_function_coverage || 0}/${summary.total_functions || 0} 함수`} color="#ff5722" />
            </div>
          </div>

          {/* V-Model Coverage Bars */}
          <div style={{ marginBottom: "12px" }}>
            <div style={{ fontSize: "0.8rem", fontWeight: 600, marginBottom: "6px" }}>V-Model 추적성 (SRS → UDS → STS / SUTS)</div>
            <div style={{ fontSize: "0.78rem", marginBottom: "3px", display: "flex", justifyContent: "space-between" }}>
              <span>SRS → UDS + STS + SUTS (완전 커버)</span>
              <span>{summary.coverage_pct || 0}%</span>
            </div>
            <div style={{ display: "flex", height: "10px", borderRadius: "5px", overflow: "hidden", background: "#333", marginBottom: "6px" }}>
              <div style={{ width: `${(summary.covered || 0) / Math.max(summary.total_requirements || 1, 1) * 100}%`, background: STATUS_COLORS.covered }} />
              <div style={{ width: `${(summary.partial || 0) / Math.max(summary.total_requirements || 1, 1) * 100}%`, background: STATUS_COLORS.partial }} />
              <div style={{ width: `${(summary.uncovered || 0) / Math.max(summary.total_requirements || 1, 1) * 100}%`, background: STATUS_COLORS.uncovered }} />
            </div>
            {(summary.suts_function_coverage_pct > 0) && (
              <>
                <div style={{ fontSize: "0.78rem", marginBottom: "3px", display: "flex", justifyContent: "space-between" }}>
                  <span>UDS 함수 → SUTS TC 커버리지</span>
                  <span>{summary.suts_function_coverage_pct || 0}%</span>
                </div>
                <div style={{ display: "flex", height: "10px", borderRadius: "5px", overflow: "hidden", background: "#333", marginBottom: "6px" }}>
                  <div style={{ width: `${summary.suts_function_coverage_pct || 0}%`, background: "#e91e63" }} />
                </div>
              </>
            )}
            <div style={{ display: "flex", gap: "16px", marginTop: "4px", fontSize: "0.75rem" }}>
              {Object.entries(STATUS_LABELS).map(([k, v]) => (
                <span key={k} style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                  <span style={{ display: "inline-block", width: "8px", height: "8px", borderRadius: "2px", background: STATUS_COLORS[k] }} />
                  {v}
                </span>
              ))}
              {(summary.total_suts_test_cases > 0) && (
                <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
                  <span style={{ display: "inline-block", width: "8px", height: "8px", borderRadius: "2px", background: "#e91e63" }} />
                  SUTS
                </span>
              )}
            </div>
          </div>

          {/* Type Distribution */}
          {summary.type_distribution && (
            <div style={{ display: "flex", gap: "6px", marginBottom: "12px", flexWrap: "wrap" }}>
              {Object.entries(summary.type_distribution).map(([t, c]) => (
                <span key={t} style={{ fontSize: "0.78rem", padding: "2px 8px", borderRadius: "10px", background: "var(--bg-alt, #2a2a3e)", border: "1px solid var(--border, #444)" }}>{t}: {c}</span>
              ))}
            </div>
          )}

          {/* View Mode Toggle */}
          <div className="row" style={{ gap: "4px", marginBottom: "10px" }}>
            {[
              { id: "table", label: "테이블" },
              { id: "flow", label: "플로우 다이어그램" },
              { id: "heatmap", label: "히트맵 매트릭스" },
            ].map((m) => (
              <button
                key={m.id}
                type="button"
                className={viewMode === m.id ? "" : "btn-outline"}
                style={{ fontSize: "0.8rem", padding: "4px 12px" }}
                onClick={() => setViewMode(m.id)}
              >
                {m.label}
              </button>
            ))}
          </div>

          {/* Table View */}
          {viewMode === "table" && (
            <>
              <div className="row" style={{ gap: "8px", marginBottom: "8px" }}>
                <select value={filter} onChange={(e) => setFilter(e.target.value)} style={{ fontSize: "0.85rem" }}>
                  <option value="all">전체 ({data.rows?.length || 0})</option>
                  <option value="covered">완전 커버 ({summary.covered || 0})</option>
                  <option value="partial">부분 커버 ({summary.partial || 0})</option>
                  <option value="uncovered">미커버 ({summary.uncovered || 0})</option>
                </select>
                <input type="text" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="요구사항/함수/TC 검색..." style={{ flex: 1, fontSize: "0.85rem" }} />
                <span className="hint">{filteredRows.length}건</span>
              </div>
              <div style={{ overflowX: "auto", maxHeight: "500px", overflowY: "auto", border: "1px solid var(--border, #444)", borderRadius: "6px" }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
                  <thead>
                    <tr style={{ position: "sticky", top: 0, background: "var(--bg-alt, #1e1e2e)", zIndex: 1 }}>
                      <th style={thStyle}>상태</th>
                      <th style={thStyle}>Req ID</th>
                      <th style={thStyle}>ASIL</th>
                      <th style={thStyle}>요구사항명</th>
                      <th style={thStyle}>UDS 함수</th>
                      <th style={thStyle}>STS TC</th>
                      <th style={thStyle}>SUTS TC</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredRows.map((row) => (
                      <tr key={row.req_id} onClick={() => setExpandedRow(expandedRow === row.req_id ? null : row.req_id)}
                        style={{ cursor: "pointer", borderBottom: "1px solid var(--border, #333)", background: expandedRow === row.req_id ? "var(--bg-alt, #1e1e2e)" : "transparent" }}>
                        <td style={tdStyle}>
                          <span style={{ display: "inline-block", width: "10px", height: "10px", borderRadius: "50%", background: STATUS_COLORS[row.status], marginRight: "4px" }} />
                          {STATUS_LABELS[row.status]}
                        </td>
                        <td style={{ ...tdStyle, fontWeight: 600, whiteSpace: "nowrap" }}>{row.req_id}</td>
                        <td style={{ ...tdStyle, textAlign: "center" }}>
                          {row.asil ? <span style={{ padding: "1px 6px", borderRadius: "4px", fontSize: "0.75rem", fontWeight: 600, background: ASIL_COLORS[row.asil] || "#eee", color: "#333" }}>{row.asil}</span> : "-"}
                        </td>
                        <td style={tdStyle}>
                          {row.req_name || "-"}
                          {expandedRow === row.req_id && row.func_names?.length > 0 && (
                            <div style={{ marginTop: "4px", fontSize: "0.75rem", opacity: 0.8 }}><strong>UDS 함수:</strong> {row.func_names.join(", ")}{row.func_count > 5 && ` (+${row.func_count - 5})`}</div>
                          )}
                          {expandedRow === row.req_id && row.tc_ids?.length > 0 && (
                            <div style={{ marginTop: "2px", fontSize: "0.75rem", opacity: 0.8 }}><strong>STS TC:</strong> {row.tc_ids.join(", ")}{row.tc_count > 5 && ` (+${row.tc_count - 5})`}</div>
                          )}
                          {expandedRow === row.req_id && row.suts_tc_ids?.length > 0 && (
                            <div style={{ marginTop: "2px", fontSize: "0.75rem", opacity: 0.8, color: "#e91e63" }}><strong>SUTS TC:</strong> {row.suts_tc_ids.join(", ")}{row.suts_tc_count > 5 && ` (+${row.suts_tc_count - 5})`}</div>
                          )}
                        </td>
                        <td style={{ ...tdStyle, textAlign: "center" }}>
                          <span style={{ color: row.func_count > 0 ? STATUS_COLORS.covered : STATUS_COLORS.uncovered, fontWeight: 600 }}>{row.func_count}</span>
                        </td>
                        <td style={{ ...tdStyle, textAlign: "center" }}>
                          <span style={{ color: row.tc_count > 0 ? STATUS_COLORS.covered : STATUS_COLORS.uncovered, fontWeight: 600 }}>{row.tc_count}</span>
                        </td>
                        <td style={{ ...tdStyle, textAlign: "center" }}>
                          <span style={{ color: (row.suts_tc_count || 0) > 0 ? "#e91e63" : STATUS_COLORS.uncovered, fontWeight: 600 }}>{row.suts_tc_count || 0}</span>
                        </td>
                      </tr>
                    ))}
                    {filteredRows.length === 0 && (
                      <tr><td colSpan={7} style={{ ...tdStyle, textAlign: "center", opacity: 0.6 }}>데이터 없음</td></tr>
                    )}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {/* Flow Diagram View */}
          {viewMode === "flow" && <FlowDiagram rows={data.rows || []} />}

          {/* Heatmap View */}
          {viewMode === "heatmap" && <HeatmapMatrix rows={data.rows || []} />}
        </>
      )}
    </div>
  );
}

function SummaryCard({ label, value, sub, color }) {
  return (
    <div style={{ background: "var(--bg-alt, #1e1e2e)", borderRadius: "8px", padding: "10px 12px", borderLeft: `4px solid ${color}` }}>
      <div style={{ fontSize: "0.72rem", opacity: 0.7 }}>{label}</div>
      <div style={{ fontSize: "1.5rem", fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: "0.75rem", opacity: 0.8 }}>{sub}</div>
    </div>
  );
}

const thStyle = {
  padding: "8px 10px",
  textAlign: "left",
  borderBottom: "2px solid var(--border, #555)",
  whiteSpace: "nowrap",
  fontSize: "0.8rem",
};

const tdStyle = {
  padding: "6px 10px",
  verticalAlign: "top",
};
