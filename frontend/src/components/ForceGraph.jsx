import { useEffect, useMemo, useRef, useState, useCallback } from "react";

const toStr = (v) => String(v ?? "").trim();

const MAX_SIM_NODES = 150;

const ForceGraph = ({
  edges = [],
  focusNode = "",
  onNodeClick,
  height = 480,
}) => {
  const svgRef = useRef(null);
  const animRef = useRef(null);
  const nodesMapRef = useRef(new Map());
  const [positions, setPositions] = useState([]);
  const [edgePositions, setEdgePositions] = useState([]);
  const [viewBox, setViewBox] = useState({ x: 0, y: 0, w: 800, h: 480 });
  const [isPanning, setIsPanning] = useState(false);
  const panStart = useRef(null);
  const [hoveredId, setHoveredId] = useState("");

  const { nodeIds, edgePairs } = useMemo(() => {
    const set = new Set();
    const pairs = [];
    (edges || []).forEach((e) => {
      const s = toStr(e?.source);
      const t = toStr(e?.target);
      if (s) set.add(s);
      if (t) set.add(t);
      if (s && t) pairs.push([s, t]);
    });
    return { nodeIds: Array.from(set), edgePairs: pairs };
  }, [edges]);

  useEffect(() => {
    if (nodeIds.length === 0) return;
    const n = Math.min(nodeIds.length, MAX_SIM_NODES);
    const ids = nodeIds.slice(0, n);
    const W = 800;
    const H = height;
    const cx = W / 2;
    const cy = H / 2;

    const map = new Map();
    ids.forEach((id, i) => {
      const angle = (2 * Math.PI * i) / n;
      const r = Math.min(W, H) * 0.32;
      map.set(id, {
        id,
        x: id === focusNode ? cx : cx + r * Math.cos(angle) + (Math.random() - 0.5) * 20,
        y: id === focusNode ? cy : cy + r * Math.sin(angle) + (Math.random() - 0.5) * 20,
        vx: 0,
        vy: 0,
      });
    });
    nodesMapRef.current = map;

    const simEdges = edgePairs.filter(([s, t]) => map.has(s) && map.has(t));
    const maxTick = Math.min(300, 80 + n);
    let tick = 0;

    const step = () => {
      const nodes = Array.from(map.values());
      const REP = n > 60 ? 2500 : 4500;
      const ATT = n > 60 ? 0.004 : 0.007;
      const CTR = 0.01;
      const DAMP = 0.82;

      for (const nd of nodes) {
        nd.vx = 0;
        nd.vy = 0;
      }

      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const a = nodes[i],
            b = nodes[j];
          const dx = b.x - a.x,
            dy = b.y - a.y;
          const d2 = dx * dx + dy * dy || 1;
          const d = Math.sqrt(d2);
          const f = REP / d2;
          const fx = (dx / d) * f,
            fy = (dy / d) * f;
          a.vx -= fx;
          a.vy -= fy;
          b.vx += fx;
          b.vy += fy;
        }
      }

      for (const [sId, tId] of simEdges) {
        const s = map.get(sId),
          t = map.get(tId);
        if (!s || !t) continue;
        const dx = t.x - s.x,
          dy = t.y - s.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const f = d * ATT;
        s.vx += (dx / d) * f;
        s.vy += (dy / d) * f;
        t.vx -= (dx / d) * f;
        t.vy -= (dy / d) * f;
      }

      let maxV = 0;
      for (const nd of nodes) {
        nd.vx += (cx - nd.x) * CTR;
        nd.vy += (cy - nd.y) * CTR;
        nd.vx *= DAMP;
        nd.vy *= DAMP;
        nd.x += nd.vx;
        nd.y += nd.vy;
        maxV = Math.max(maxV, Math.abs(nd.vx), Math.abs(nd.vy));
      }
      tick++;

      setPositions(nodes.map(({ id, x, y }) => ({ id, x, y, isFocus: id === focusNode })));
      setEdgePositions(
        simEdges.map(([s, t]) => ({
          sx: map.get(s)?.x || 0,
          sy: map.get(s)?.y || 0,
          tx: map.get(t)?.x || 0,
          ty: map.get(t)?.y || 0,
        }))
      );

      if (tick < maxTick && maxV > 0.3) {
        animRef.current = requestAnimationFrame(step);
      }
    };

    animRef.current = requestAnimationFrame(step);
    return () => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
    };
  }, [nodeIds, edgePairs, focusNode, height]);

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const handler = (e) => {
      e.preventDefault();
      const factor = e.deltaY > 0 ? 1.1 : 0.9;
      setViewBox((prev) => {
        const nw = prev.w * factor;
        const nh = prev.h * factor;
        return { x: prev.x - (nw - prev.w) / 2, y: prev.y - (nh - prev.h) / 2, w: nw, h: nh };
      });
    };
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, []);

  const handlePointerDown = useCallback(
    (e) => {
      if (e.target.closest(".fg-node")) return;
      setIsPanning(true);
      panStart.current = { cx: e.clientX, cy: e.clientY, vb: { ...viewBox } };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [viewBox]
  );

  const handlePointerMove = useCallback(
    (e) => {
      if (!isPanning || !panStart.current) return;
      const rect = svgRef.current?.getBoundingClientRect();
      if (!rect) return;
      const sx = viewBox.w / rect.width;
      const sy = viewBox.h / rect.height;
      setViewBox({
        ...panStart.current.vb,
        x: panStart.current.vb.x - (e.clientX - panStart.current.cx) * sx,
        y: panStart.current.vb.y - (e.clientY - panStart.current.cy) * sy,
      });
    },
    [isPanning, viewBox.w, viewBox.h]
  );

  const handlePointerUp = useCallback(() => {
    setIsPanning(false);
    panStart.current = null;
  }, []);

  const resetView = useCallback(() => {
    setViewBox({ x: 0, y: 0, w: 800, h: 480 });
  }, []);

  if (nodeIds.length === 0) return <div className="hint">그래프 데이터가 없습니다.</div>;

  return (
    <div className="force-graph-wrap">
      <div className="force-graph-toolbar">
        <span className="hint">
          노드 {nodeIds.length}
          {nodeIds.length > MAX_SIM_NODES ? ` (표시 ${MAX_SIM_NODES})` : ""} / 엣지 {edgePairs.length}
        </span>
        <button type="button" className="btn-outline btn-xs" onClick={resetView}>
          뷰 초기화
        </button>
      </div>
      <svg
        ref={svgRef}
        className="force-graph-svg"
        width="100%"
        height={height}
        viewBox={`${viewBox.x} ${viewBox.y} ${viewBox.w} ${viewBox.h}`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
        style={{ cursor: isPanning ? "grabbing" : "grab", touchAction: "none" }}
      >
        <defs>
          <marker
            id="fg-arrow"
            viewBox="0 0 10 10"
            refX="32"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M0 0L10 5L0 10z" fill="var(--text-muted)" />
          </marker>
        </defs>
        {edgePositions.map((e, i) => (
          <line
            key={i}
            x1={e.sx}
            y1={e.sy}
            x2={e.tx}
            y2={e.ty}
            stroke="var(--text-muted)"
            strokeWidth="1"
            opacity="0.35"
            markerEnd="url(#fg-arrow)"
          />
        ))}
        {positions.map((n) => {
          const active = n.isFocus || hoveredId === n.id;
          const label = n.id.length > 18 ? n.id.slice(0, 16) + ".." : n.id;
          const rw = Math.max(64, label.length * 6.5 + 18);
          return (
            <g
              key={n.id}
              className="fg-node"
              transform={`translate(${n.x},${n.y})`}
              onClick={() => onNodeClick?.(n.id)}
              onPointerEnter={() => setHoveredId(n.id)}
              onPointerLeave={() => setHoveredId("")}
              style={{ cursor: "pointer" }}
            >
              <rect
                x={-rw / 2}
                y={-15}
                width={rw}
                height={30}
                rx="7"
                fill={n.isFocus ? "var(--accent-soft)" : "var(--panel)"}
                stroke={active ? "var(--accent)" : "var(--border)"}
                strokeWidth={active ? 2 : 1}
              />
              <text
                x="0"
                y="4"
                textAnchor="middle"
                fontSize="10"
                fill="var(--text)"
                fontWeight={n.isFocus ? 600 : 400}
              >
                {label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
};

export default ForceGraph;
