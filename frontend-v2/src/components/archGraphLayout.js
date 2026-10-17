/**
 * archGraphLayout — 모듈 의존 다이어그램의 순수 레이아웃 계산 (K2).
 * 컴포넌트 파일(ArchitectureGraphPanel)과 분리: react-refresh 규칙 + 단독 단위테스트 용이.
 */

export const AG = { COL_W: 196, NODE_W: 172, NODE_H: 36, GAP: 10, PAD: 14 };

/**
 * 층위 배치(순수) — 모듈 SCC를 대표 노드로 응축한 DAG의 최장경로 레이어링.
 * 사이클 멤버는 같은 레이어(같은 대표)에 놓이고 cycleModules/cycleEdges로 표시된다.
 * 반환 {pos:{module:{x,y}}, width, height, cycleModules:Set, cycleEdges:Set("A→B")}.
 */
export function layoutModules(moduleGraph, cycles) {
  const nodes = moduleGraph?.nodes || [];
  const edges = moduleGraph?.edges || [];
  const sccOf = {};
  (cycles?.module_sccs || []).forEach((c) => {
    (c.modules || []).forEach((m) => { sccOf[m] = c.modules[0]; });
  });
  const rep = (m) => sccOf[m] || m;
  const names = nodes.map((n) => n.module);
  const nameSet = new Set(names);
  const repSet = new Set(names.map(rep));
  const adj = new Map();
  const indeg = new Map();
  repSet.forEach((r) => { adj.set(r, new Set()); indeg.set(r, 0); });
  edges.forEach((e) => {
    if (!nameSet.has(e.from) || !nameSet.has(e.to)) return; // 캡 절단으로 노드 밖 엣지 방어
    const a = rep(e.from);
    const b = rep(e.to);
    if (a !== b && !adj.get(a).has(b)) {
      adj.get(a).add(b);
      indeg.set(b, indeg.get(b) + 1);
    }
  });
  const layer = new Map();
  const queue = [];
  repSet.forEach((r) => { if (indeg.get(r) === 0) { queue.push(r); layer.set(r, 0); } });
  const remaining = new Map(indeg);
  while (queue.length) {
    const u = queue.shift();
    adj.get(u).forEach((v) => {
      layer.set(v, Math.max(layer.get(v) ?? 0, (layer.get(u) ?? 0) + 1));
      remaining.set(v, remaining.get(v) - 1);
      if (remaining.get(v) === 0) queue.push(v);
    });
  }
  const meta = new Map(nodes.map((n) => [n.module, n]));
  const byLayer = new Map();
  names.forEach((m) => {
    const L = layer.get(rep(m)) ?? 0;
    if (!byLayer.has(L)) byLayer.set(L, []);
    byLayer.get(L).push(m);
  });
  const layerKeys = [...byLayer.keys()].sort((a, b) => a - b);
  const pos = {};
  let maxRows = 1;
  layerKeys.forEach((L, ci) => {
    const col = byLayer.get(L);
    col.sort((a, b) => ((meta.get(b)?.functions || 0) - (meta.get(a)?.functions || 0)) || a.localeCompare(b));
    maxRows = Math.max(maxRows, col.length);
    col.forEach((m, ri) => {
      pos[m] = { x: AG.PAD + ci * AG.COL_W, y: AG.PAD + ri * (AG.NODE_H + AG.GAP) };
    });
  });
  const cycleEdges = new Set();
  edges.forEach((e) => {
    if (nameSet.has(e.from) && nameSet.has(e.to) && e.from !== e.to && rep(e.from) === rep(e.to)) {
      cycleEdges.add(`${e.from}→${e.to}`);
    }
  });
  return {
    pos,
    width: AG.PAD * 2 + Math.max(1, layerKeys.length) * AG.COL_W,
    height: AG.PAD * 2 + maxRows * (AG.NODE_H + AG.GAP),
    cycleModules: new Set(Object.keys(sccOf)),
    cycleEdges,
  };
}
