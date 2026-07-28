/**
 * ArchitectureGraphPanel — 아키텍처 다이어그램(K2): 모듈 의존 그래프(SVG)·결합 히트맵·
 * 핫스팟 산포도·순환 의존 목록. POST /api/summary/architecture-metrics(v3, 결정론) 소비.
 *
 * ISO 정직성: 관계는 함수 호출 기반(include 미분석)·모듈은 디렉터리 프록시·파서 엔진을
 * 각주로 상시 표기. 사이클 0건은 "관측 없음"을 명시 렌더(침묵 생략 금지). 산포도 Y축은
 * 복잡도 출처 혼합(vcast_ccn 측정 vs loc_proxy 줄수 추정)이라 마커 모양으로 구분한다.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchArchMetrics } from '../../archMetricsCache.js';
import { AG, layoutModules } from '../archGraphLayout.js';
import { bezierEdgeH, exportPng, exportSvg } from '../graphPrimitives.jsx';
import SummaryPanel from './SummaryPanel.jsx';
import * as T from './summaryTable.js';
import { TABLE, SCROLL } from './summaryTable.js';

const xs = { fontSize: 'var(--text-xs)' };
const btn = {
  ...xs, padding: '1px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
  background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)',
};

const { NODE_W, NODE_H } = AG;

/**
 * 다이어그램 표시 스위치(사용자 결정으로 숨긴 항목) — 코드는 살려 두고 플래그만 false.
 * 되살리려면 값을 true로. ProjectSummarySection의 SHOW와 같은 규약(주석 처리 대신 플래그).
 *
 * ⚠ 숨겨도 **데이터 축은 죽지 않는다**: 계층 역방향 수는 아키텍처 메트릭 요약 스트립에,
 * 전역 공유는 같은 패널의 '결합도·공유 전역'에 남고, 둘 다 개선 제안(layer_violation·
 * inject_global) 후보의 근거로 계속 쓰인다 — 그림만 접는 것이지 관측이 사라지는 게 아니다.
 */
const SHOW = {
  layerDiagram: false,
  globalFlow: false,
};

const FILE_DRILL_LIMIT = 12;

/**
 * 그림 한 덩어리의 공통 틀 — **제목 / 설명 / 컨트롤 / 본문 / 각주** 다섯 자리를 고정한다.
 *
 * 예전엔 다이어그램·히트맵·DSM·산포도가 전부 **테두리 없는 맨 div** 라 2열 그리드에서
 * 서로 뭉개졌다. 컨트롤 위치도 제각각(모듈 다이어그램만 제목 옆에 저장 버튼)이고 각주는
 * 본문 뒤에 아무렇게나 붙어, 어디까지가 한 그림인지 눈이 못 잡았다.
 */
function Figure({ title, hint, actions, note, children }) {
  return (
    <section style={{
      border: '1px solid var(--border)', borderRadius: 'var(--radius-md)',
      padding: 'var(--sp-2)', minWidth: 0,
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', flexWrap: 'wrap', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
        <span style={{ ...T.figTitle, marginBottom: 0 }}>{title}</span>
        {hint && <span style={T.note}>{hint}</span>}
        {actions && <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>{actions}</span>}
      </div>
      <div style={{ minWidth: 0 }}>{children}</div>
      {note && <div style={{ ...T.note, marginTop: 'var(--sp-1)' }}>{note}</div>}
    </section>
  );
}

/** 색 농도 범례 — 진하기가 무엇을 뜻하는지 없으면 히트맵은 그냥 얼룩이다. */
function ScaleLegend({ max, unit = '회' }) {
  if (!max) return null;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <span style={T.note}>0</span>
      {[0.15, 0.4, 0.65, 0.9].map((a) => (
        <span key={a} style={{ width: 14, height: 10, background: `rgba(37, 99, 235, ${a})`, border: '1px solid var(--border)' }} />
      ))}
      <span style={T.note}>{max}{unit}</span>
    </span>
  );
}


/** 선택 모듈 내부를 파일 단위로 펼친다(v5 file_graph). 모듈은 디렉터리 2세그먼트 프록시라
 *  파일 수십 개가 한 덩어리로 접히는데, 여기서 한 단계 더 내려간다. */
function ModuleFileDrill({ module: mod, fileGraph }) {
  const detail = useMemo(() => {
    const nodes = (fileGraph?.nodes || []).filter((n) => n.module === mod);
    const inside = new Set(nodes.map((n) => n.file));
    const edges = fileGraph?.edges || [];
    const internal = edges.filter((e) => inside.has(e.from) && inside.has(e.to));
    // 상호 호출(양방향) 표시 — 파일 쌍 단위 2-사이클은 리팩토링 신호다.
    const seen = new Set(internal.map((e) => `${e.from}|${e.to}`));
    // 파일→모듈 조회는 Map으로 — 엣지마다 nodes.find를 돌면 캡(400노드×800엣지)에서 O(E×N)이 된다.
    const moduleOf = new Map((fileGraph?.nodes || []).map((n) => [n.file, n.module]));
    const outbound = new Map();
    const inbound = new Map();
    edges.forEach((e) => {
      if (inside.has(e.from) && !inside.has(e.to)) {
        const m = moduleOf.get(e.to) || '(외부)';
        outbound.set(m, (outbound.get(m) || 0) + e.calls);
      } else if (!inside.has(e.from) && inside.has(e.to)) {
        const m = moduleOf.get(e.from) || '(외부)';
        inbound.set(m, (inbound.get(m) || 0) + e.calls);
      }
    });
    return {
      nodes: [...nodes].sort((a, b) => b.functions - a.functions),
      internal: internal
        .map((e) => ({ ...e, mutual: seen.has(`${e.to}|${e.from}`) }))
        .sort((a, b) => b.calls - a.calls),
      outbound: [...outbound.entries()].sort((a, b) => b[1] - a[1]),
      inbound: [...inbound.entries()].sort((a, b) => b[1] - a[1]),
    };
  }, [mod, fileGraph]);

  if (!fileGraph) {
    return (
      <div style={{ ...xs, color: 'var(--text-muted)' }}>
        파일 단위 데이터가 이 응답에 없습니다(구 캐시) — 새로고침하면 표시됩니다.
      </div>
    );
  }
  const base = (f) => String(f).split('/').pop();
  return (
    <div style={{ marginTop: 6 }}>
      <div style={{ ...xs, fontWeight: 600, marginBottom: 2 }}>
        내부 파일 {detail.nodes.length}개 · 파일 간 호출 {detail.internal.length}건
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%' }}>
          <thead>
            <tr>
              <th style={{ ...xs, textAlign: 'left', padding: '2px 6px', color: 'var(--text-muted)' }}>파일</th>
              <th style={{ ...xs, textAlign: 'left', padding: '2px 6px', color: 'var(--text-muted)' }}>함수</th>
              <th style={{ ...xs, textAlign: 'left', padding: '2px 6px', color: 'var(--text-muted)' }}>본문 줄</th>
            </tr>
          </thead>
          <tbody>
            {detail.nodes.slice(0, FILE_DRILL_LIMIT).map((n) => (
              <tr key={n.file}>
                <td style={{ ...xs, padding: '2px 6px' }} title={n.file}>{base(n.file)}</td>
                <td style={{ ...xs, padding: '2px 6px' }}>{n.functions}</td>
                <td style={{ ...xs, padding: '2px 6px', color: 'var(--text-muted)' }}>{n.lines.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {detail.nodes.length > FILE_DRILL_LIMIT && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>* 함수 수 상위 {FILE_DRILL_LIMIT}개만 표시 (총 {detail.nodes.length}개)</div>
      )}
      {detail.internal.length > 0 && (
        <div style={{ marginTop: 4 }}>
          <div style={{ ...xs, fontWeight: 600 }}>내부 호출</div>
          {detail.internal.slice(0, FILE_DRILL_LIMIT).map((e) => (
            <div key={`${e.from}→${e.to}`} style={{ ...xs, color: 'var(--text-muted)' }}>
              {base(e.from)} → {base(e.to)} · {e.calls}회
              {e.mutual && <span style={{ color: 'var(--color-danger)' }}> ⚠상호</span>}
            </div>
          ))}
          {detail.internal.length > FILE_DRILL_LIMIT && (
            <div style={{ ...xs, color: 'var(--text-muted)' }}>* 상위 {FILE_DRILL_LIMIT}건만 표시 (총 {detail.internal.length}건)</div>
          )}
        </div>
      )}
      <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 4 }}>
        외부 유출: {detail.outbound.length ? detail.outbound.map(([m, c]) => `→${m} ${c}`).join(' · ') : '없음'}
        {' / '}유입: {detail.inbound.length ? detail.inbound.map(([m, c]) => `←${m} ${c}`).join(' · ') : '없음'}
      </div>
      {fileGraph.truncated && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>* 파일 그래프 표시 상한으로 일부 파일·관계 생략(총 {fileGraph.total_files}파일)</div>
      )}
    </div>
  );
}

function ModuleDiagram({ moduleGraph, cycles, fileGraph }) {
  const [hover, setHover] = useState(null);
  const [selected, setSelected] = useState(null);
  const svgRef = useRef(null);
  const L = useMemo(() => layoutModules(moduleGraph, cycles), [moduleGraph, cycles]);
  const edges = moduleGraph?.edges || [];
  const nodes = moduleGraph?.nodes || [];
  const neighbors = useMemo(() => {
    const map = new Map();
    (moduleGraph?.nodes || []).forEach((n) => map.set(n.module, new Set([n.module])));
    (moduleGraph?.edges || []).forEach((e) => {
      map.get(e.from)?.add(e.to);
      map.get(e.to)?.add(e.from);
    });
    return map;
  }, [moduleGraph]);
  const focus = hover || selected;
  const dimmed = (m) => (focus ? !(neighbors.get(focus)?.has(m)) : false);
  const selEdges = selected
    ? edges.filter((e) => e.from === selected || e.to === selected)
    : [];
  return (
    <Figure
      title="모듈 의존 다이어그램"
      hint="호출 수 라벨 · 순환은 빨강"
      actions={<>
        <button type="button" style={btn} onClick={() => exportSvg(svgRef.current, 'architecture-modules.svg')}>SVG</button>
        <button type="button" style={btn} onClick={() => exportPng(svgRef.current, 'architecture-modules.png')}>PNG</button>
      </>}
    >
      <div style={{ overflowX: 'auto' }}>
        <svg ref={svgRef} viewBox={`0 0 ${L.width} ${L.height}`} width={L.width} height={L.height}
          role="img" aria-label="모듈 의존 다이어그램" style={{ maxWidth: '100%', height: 'auto' }}>
          <defs>
            <marker id="ag-arrow" viewBox="0 0 8 8" refX={7} refY={4} markerWidth={6} markerHeight={6} orient="auto-start-reverse">
              <path d="M0,0 L8,4 L0,8 Z" fill="var(--text-muted)" />
            </marker>
            <marker id="ag-arrow-cycle" viewBox="0 0 8 8" refX={7} refY={4} markerWidth={6} markerHeight={6} orient="auto-start-reverse">
              <path d="M0,0 L8,4 L0,8 Z" fill="var(--color-danger)" />
            </marker>
          </defs>
          {edges.map((e) => {
            const a = L.pos[e.from];
            const b = L.pos[e.to];
            if (!a || !b) return null;
            const isCycle = L.cycleEdges.has(`${e.from}→${e.to}`);
            const dim = focus && dimmed(e.from) && dimmed(e.to);
            const leftToRight = a.x <= b.x;
            const d = leftToRight
              ? bezierEdgeH(a.x + NODE_W, a.y + NODE_H / 2, b.x, b.y + NODE_H / 2)
              : bezierEdgeH(a.x, a.y + NODE_H / 2, b.x + NODE_W, b.y + NODE_H / 2);
            return (
              <g key={`${e.from}→${e.to}`} opacity={dim ? 0.15 : 1}>
                <path d={d} fill="none"
                  stroke={isCycle ? 'var(--color-danger)' : 'var(--text-muted)'}
                  strokeWidth={Math.min(1 + Math.log2(1 + e.calls), 4)}
                  markerEnd={isCycle ? 'url(#ag-arrow-cycle)' : 'url(#ag-arrow)'}>
                  <title>{`${e.from} → ${e.to} · 호출 ${e.calls}회${isCycle ? ' (순환 참여)' : ''}`}</title>
                </path>
              </g>
            );
          })}
          {nodes.map((n) => {
            const p = L.pos[n.module];
            if (!p) return null;
            const isCycle = L.cycleModules.has(n.module);
            const isSel = selected === n.module;
            return (
              <g key={n.module} transform={`translate(${p.x},${p.y})`} opacity={dimmed(n.module) ? 0.28 : 1}
                style={{ cursor: 'pointer' }} role="button" tabIndex={0}
                aria-label={`모듈 ${n.module} — 파일 ${n.files} · 함수 ${n.functions}${isCycle ? ' · 순환 의존 참여' : ''}`}
                onClick={() => setSelected(isSel ? null : n.module)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelected(isSel ? null : n.module); } }}
                onMouseEnter={() => setHover(n.module)} onMouseLeave={() => setHover(null)}>
                <title>{`${n.module} — 파일 ${n.files} · 함수 ${n.functions}`}</title>
                <rect width={NODE_W} height={NODE_H} rx={6}
                  style={{ fill: 'var(--bg-elevated, #ffffff)' }}
                  stroke={isCycle ? 'var(--color-danger)' : (isSel ? 'var(--accent)' : 'var(--border)')}
                  strokeWidth={isCycle || isSel ? 2.5 : 1.5} />
                <text x={10} y={15} fontSize={11} fontWeight={600} style={{ fill: 'var(--fg)' }}>
                  {n.module.length > 24 ? `${n.module.slice(0, 23)}…` : n.module}
                </text>
                <text x={10} y={29} fontSize={9} style={{ fill: 'var(--text-muted)' }}>
                  {`파일 ${n.files} · 함수 ${n.functions}`}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      {moduleGraph?.truncated && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>* 표시 상한(노드/엣지 캡)으로 일부 모듈·관계 생략</div>
      )}
      {selected && (
        <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: '4px 8px', marginTop: 4 }}>
          <div style={{ ...xs, fontWeight: 600 }}>{selected} — 연결 관계</div>
          {selEdges.length === 0 && <div style={{ ...xs, color: 'var(--text-muted)' }}>표시 범위 내 연결 없음</div>}
          {selEdges.map((e) => (
            <div key={`${e.from}→${e.to}`} style={xs}>
              {e.from === selected ? `→ ${e.to}` : `← ${e.from}`} · 호출 {e.calls}회
              {L.cycleEdges.has(`${e.from}→${e.to}`) ? ' · 순환 참여' : ''}
            </div>
          ))}
          {/* 모듈 = 디렉터리 2세그먼트 프록시라 파일이 접힌다 — 한 단계 더 내려간 뷰(v5) */}
          <ModuleFileDrill module={selected} fileGraph={fileGraph} />
        </div>
      )}
    </Figure>
  );
}

/** 계층 다이어그램 — APP/BSW/LIB/BOOT를 밴드로 쌓고 계층 간 호출을 화살표로.
 *  하위→상위 역방향은 빨간 점선(계층화 **검토 후보** — 위반 단정 아님). */
function LayerDiagram({ layerGraph }) {
  const [openRev, setOpenRev] = useState(false);
  if (!layerGraph) {
    return <div style={{ ...xs, color: 'var(--text-muted)' }}>계층 데이터가 이 응답에 없습니다(구 캐시) — 새로고침하면 표시됩니다.</div>;
  }
  if (!layerGraph.available) {
    return <div style={{ ...xs, color: 'var(--text-muted)' }}>계층을 판정할 수 없습니다 ({layerGraph.reason}).</div>;
  }
  const nodes = layerGraph.nodes || [];
  const BW = 300;
  const BH = 42;
  const GAP = 26;
  const W = 560;
  const H = nodes.length * (BH + GAP) + 20;
  const yOf = (i) => 10 + i * (BH + GAP);
  const idx = new Map(nodes.map((n, i) => [n.layer, i]));
  const maxCalls = Math.max(...(layerGraph.edges || []).map((e) => e.calls), 1);
  return (
    <div>
      <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>
        계층 다이어그램 (상위→하위 정방향 실선 · 하위→상위 역방향 빨간 점선)
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="계층 다이어그램"
        style={{ width: '100%', maxWidth: 640, height: 'auto' }}>
        {(layerGraph.edges || []).map((e) => {
          const i = idx.get(e.from);
          const j = idx.get(e.to);
          if (i == null || j == null) return null;
          const x = e.reverse ? 40 + BW + 30 : 40 + BW - 30;
          const y1 = yOf(i) + BH / 2;
          const y2 = yOf(j) + BH / 2;
          const bow = e.reverse ? 46 : -46;
          return (
            <path key={`${e.from}->${e.to}`}
              d={`M ${x} ${y1} C ${x + bow} ${y1}, ${x + bow} ${y2}, ${x} ${y2}`}
              fill="none" stroke={e.reverse ? 'var(--color-danger)' : 'var(--text-muted)'}
              strokeWidth={Math.min(1 + Math.log2(1 + e.calls / maxCalls * 8), 3.5)}
              strokeDasharray={e.reverse ? '5 3' : undefined}>
              <title>{`${e.from} → ${e.to} · ${e.calls}회${e.reverse ? ' (역방향 — 계층화 검토 후보)' : ''}`}</title>
            </path>
          );
        })}
        {nodes.map((n, i) => (
          <g key={n.layer} transform={`translate(40,${yOf(i)})`}>
            <title>{`${n.label} — 함수 ${n.functions}개`}</title>
            <rect width={BW} height={BH} rx={6} style={{ fill: 'var(--bg-elevated, #ffffff)' }}
              stroke="var(--border)" strokeWidth={1.5} />
            <text x={12} y={19} fontSize={12} fontWeight={700} style={{ fill: 'var(--fg)' }}>{n.label}</text>
            <text x={12} y={34} fontSize={10} style={{ fill: 'var(--text-muted)' }}>{`함수 ${n.functions}개`}</text>
          </g>
        ))}
      </svg>
      <div style={{ ...xs, marginTop: 2 }}>
        역방향 호출 <b style={{ color: layerGraph.reverse_total > 0 ? 'var(--color-danger)' : 'var(--text)' }}>{layerGraph.reverse_total}</b>건
        {layerGraph.reverse_total > 0 && (
          <button type="button" style={{ ...btn, marginLeft: 6 }} onClick={() => setOpenRev(!openRev)} aria-expanded={openRev}>
            {openRev ? '함수 쌍 접기' : '함수 쌍 보기'}
          </button>
        )}
      </div>
      {openRev && (
        <div style={{ marginTop: 4 }}>
          {(layerGraph.reverse_pairs || []).map((p) => (
            <div key={`${p.caller}->${p.callee}`} style={{ ...xs, color: 'var(--text-muted)' }}>
              · <span style={{ fontFamily: 'monospace' }}>{p.caller}</span>({p.caller_layer.split('_')[0]})
              {' → '}<span style={{ fontFamily: 'monospace' }}>{p.callee}</span>({p.callee_layer.split('_')[0]})
            </div>
          ))}
          {(layerGraph.reverse_pairs_omitted || 0) > 0 && (
            <div style={{ ...xs, color: 'var(--text-muted)' }}>* 상위 {(layerGraph.reverse_pairs || []).length}건만 표시 (+{layerGraph.reverse_pairs_omitted} 생략)</div>
          )}
        </div>
      )}
      <div style={{ ...xs, color: 'var(--text-muted)', marginTop: 2 }}>* {layerGraph.note}</div>
    </div>
  );
}

const DSM_MAX = 28;

/** 파일 단위 DSM — 위상정렬 순으로 놓으면 **상삼각에 남는 셀이 곧 순환**이다.
 *  모듈 히트맵(8×8)은 덩어리라 순환이 안 보이므로 파일 레벨로 따로 그린다. */
function DsmMatrix({ fileGraph }) {
  const [topo, setTopo] = useState(true);
  const view = useMemo(() => {
    const edges = fileGraph?.edges || [];
    if (!edges.length) return null;
    const involved = new Set();
    edges.forEach((e) => { involved.add(e.from); involved.add(e.to); });
    const order = topo && (fileGraph.topo_order || []).length
      ? (fileGraph.topo_order || []).filter((f) => involved.has(f))
      : [...involved].sort();
    const shown = order.slice(0, DSM_MAX);
    const pos = new Map(shown.map((f, i) => [f, i]));
    // 전체 순서 기준 역행 엣지도 함께 센다 — 표시분만 세면 절단된 파일의 순환이 침묵한다
    // (실측: 58파일 중 28개만 표시 → 역행 14건 중 6건만 보였다).
    const allPos = new Map(order.map((f, i) => [f, i]));
    const cell = new Map();
    let max = 0;
    let upper = 0;
    let upperAll = 0;
    edges.forEach((e) => {
      if (allPos.has(e.from) && allPos.has(e.to) && allPos.get(e.from) > allPos.get(e.to)) upperAll += 1;
      if (!pos.has(e.from) || !pos.has(e.to)) return;
      cell.set(`${e.from}|${e.to}`, e.calls);
      if (e.calls > max) max = e.calls;
      if (pos.get(e.from) > pos.get(e.to)) upper += 1;   // 정렬 위쪽으로 되돌아가는 호출 = 순환
    });
    return { shown, cell, max, upper, upperAll, omitted: Math.max(0, order.length - DSM_MAX) };
  }, [fileGraph, topo]);

  if (!view) {
    return (
      <Figure title="의존 구조 매트릭스(DSM)">
        <div style={T.note}>파일 간 호출이 관측되지 않아 DSM을 그릴 수 없습니다.</div>
      </Figure>
    );
  }
  // ⚠ 셀을 정사각으로 고정한다 — 값 자릿수에 따라 열 폭이 달라지면 격자가 어긋나 매트릭스로
  //   안 읽힌다(DSM 은 '격자에서 어느 쪽이 위/아래냐'가 정보의 전부다).
  const base = {
    ...xs, padding: 0, border: '1px solid var(--border)', textAlign: 'center', fontSize: 9,
    width: 20, minWidth: 20, height: 20, boxSizing: 'border-box',
  };
  const short = (f) => String(f).split('/').pop().replace(/\.[ch]$/, '');
  const pos = new Map(view.shown.map((f, i) => [f, i]));
  return (
    <Figure
      title="의존 구조 매트릭스(DSM)"
      hint={topo
        ? <>행 → 열 호출 · 위상순이라 <b style={{ color: 'var(--color-danger)' }}>붉은 셀이 순환</b>{view.upperAll > view.upper
            ? ` — 표시 ${view.upper}건 / 전체 ${view.upperAll}건`
            : ` ${view.upper}건`}</>
        : '행 → 열 호출 · 이름순(순환 강조 없음)'}
      actions={<>
        <ScaleLegend max={view.max} />
        <button type="button" style={btn} onClick={() => setTopo(!topo)} aria-pressed={topo}>
          {topo ? '위상순' : '이름순'}
        </button>
      </>}
      note={<>
        열 번호는 왼쪽 행 순서와 같습니다.
        {view.omitted > 0 && ` · 표시 상한 ${DSM_MAX}개 — ${view.omitted}개 파일 생략`}
      </>}
    >
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', tableLayout: 'fixed' }}>
          <thead>
            <tr>
              <th style={{ ...base, width: 'auto', minWidth: 110 }} />
              {view.shown.map((c, i) => <th key={c} style={base} title={c}>{i + 1}</th>)}
            </tr>
          </thead>
          <tbody>
            {view.shown.map((r, ri) => (
              <tr key={r}>
                <th style={{ ...base, textAlign: 'left', whiteSpace: 'nowrap' }} title={r}>{ri + 1}. {short(r)}</th>
                {view.shown.map((c) => {
                  const v = r === c ? null : view.cell.get(`${r}|${c}`);
                  const back = v != null && topo && ri > pos.get(c);
                  const alpha = v && view.max ? (0.15 + 0.7 * (v / view.max)).toFixed(2) : 0;
                  return (
                    <td key={c} title={v ? `${short(r)} → ${short(c)} · ${v}회${back ? ' (순환 — 위상 역행)' : ''}` : undefined}
                      style={{
                        ...base,
                        background: v ? (back ? `rgba(220, 38, 38, ${alpha})` : `rgba(37, 99, 235, ${alpha})`) : undefined,
                        color: v ? '#fff' : 'var(--text-muted)',
                      }}>
                      {r === c ? '·' : (v || '')}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* 절단 고지는 Figure 의 note 로 올라갔다 — 구 캐시 폴백만 여기 남긴다 */}
      {!(fileGraph.topo_order || []).length && (
        <div style={T.note}>* 위상 순서가 이 응답에 없어 이름순으로 표시(구 캐시)</div>
      )}
    </Figure>
  );
}

/** 전역 데이터 흐름 — 모듈 경계를 넘는 상위 전역만 이분 그래프(왼쪽 전역 / 오른쪽 사용 함수). */
function GlobalFlow({ globalCoupling }) {
  const rows = useMemo(() => {
    const top = globalCoupling?.top || [];
    const cross = top.filter((g) => (g.modules || 0) > 1);
    return (cross.length ? cross : top).slice(0, 5).filter((g) => (g.functions_sample || []).length);
  }, [globalCoupling]);
  if (!globalCoupling?.available) {
    return <div style={{ ...xs, color: 'var(--text-muted)' }}>전역 참조가 관측되지 않았습니다.</div>;
  }
  if (!rows.length) {
    return <div style={{ ...xs, color: 'var(--text-muted)' }}>전역별 사용 함수 목록이 이 응답에 없습니다(구 캐시) — 새로고침하면 표시됩니다.</div>;
  }
  const RH = 18;
  const W = 560;
  // 좌표를 렌더 전에 확정한다 — JSX 안에서 카운터를 증가시키면 렌더 순수성이 깨진다(react-hooks/immutability).
  const totalFns = rows.reduce((a, g) => a + g.functions_sample.length, 0);
  const H = Math.max(rows.length, totalFns) * RH + 24;
  const laid = [];
  let cursor = 0;
  for (const g of rows) {
    const fns = g.functions_sample.map((fn, k) => ({ fn, y: 16 + (cursor + k) * RH }));
    // 전역 노드는 자기 함수들의 세로 중앙에 둔다(선이 부채꼴로 퍼져 읽기 쉬움).
    const gy = fns.length ? (fns[0].y + fns[fns.length - 1].y) / 2 : 16 + cursor * RH;
    laid.push({ g, fns, gy });
    cursor += g.functions_sample.length;
  }
  return (
    <div>
      <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>
        전역 데이터 흐름 — 모듈 경계를 넘는 전역과 사용 함수(참조 기준, 읽기/쓰기 미구분)
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="전역 데이터 흐름"
        style={{ width: '100%', maxWidth: 660, height: 'auto' }}>
        {laid.map(({ g, fns, gy }) => (
          <g key={g.global}>
            {fns.map(({ fn, y }) => (
              <g key={`${g.global}|${fn}`}>
                <path d={bezierEdgeH(190, gy, 330, y)} fill="none" stroke="var(--text-muted)" strokeWidth={1} opacity={0.5} />
                <text x={336} y={y + 3} fontSize={9} style={{ fill: 'var(--fg)' }}>{fn.length > 26 ? `${fn.slice(0, 25)}…` : fn}</text>
              </g>
            ))}
            <text x={8} y={gy + 3} fontSize={10} fontWeight={700} style={{ fill: 'var(--fg)' }}>
              {g.global.length > 22 ? `${g.global.slice(0, 21)}…` : g.global}
            </text>
            <text x={8} y={gy + 14} fontSize={8} style={{ fill: 'var(--text-muted)' }}>
              {`${g.modules}모듈 · ${g.functions}함수`}
            </text>
          </g>
        ))}
      </svg>
      {rows.some((g) => (g.functions_omitted || 0) > 0) && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          * 전역당 사용 함수는 상위 8개만 표시 ({rows.map((g) => `${g.global} +${g.functions_omitted || 0}`).filter((s) => !s.endsWith('+0')).join(' · ') || '생략 없음'})
        </div>
      )}
      <div style={{ ...xs, color: 'var(--text-muted)' }}>* {globalCoupling.note}</div>
    </div>
  );
}

function CouplingHeatmap({ moduleGraph }) {
  const nodes = (moduleGraph?.nodes || []).slice(0, 20);
  const names = nodes.map((n) => n.module);
  const edges = moduleGraph?.edges || [];
  const cell = new Map();
  let max = 0;
  edges.forEach((e) => {
    cell.set(`${e.from}|${e.to}`, e.calls);
    if (e.calls > max) max = e.calls;
  });
  if (!names.length) return null;
  // 모듈명은 디렉터리 경로다 — 마지막 세그먼트만 쓰고 전체는 title 로. 예전의 13자 절단은
  // `Sources/LIN/LIN_…` 처럼 **앞부분만 남아 서로 구분이 안 됐다**.
  const short = (m) => String(m).split('/').pop();
  // ⚠ 셀 폭을 고정한다 — padding 만 주면 값(1자리/3자리)에 따라 열 폭이 달라져 격자가 어긋난다.
  const tdBase = {
    ...xs, padding: 0, border: '1px solid var(--border)', textAlign: 'center',
    width: 34, minWidth: 34, height: 22, boxSizing: 'border-box',
  };
  return (
    <Figure
      title="모듈 결합 히트맵"
      hint="행 → 열 호출 수"
      actions={<ScaleLegend max={max} />}
      note={(moduleGraph?.nodes || []).length > 20 ? '* 함수 수 상위 20개 모듈만 표시' : null}
    >
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse', tableLayout: 'fixed' }}>
          <thead>
            <tr>
              <th style={{ ...tdBase, width: 'auto', minWidth: 90 }} />
              {names.map((c) => <th key={c} style={tdBase} title={c}>{short(c)}</th>)}
            </tr>
          </thead>
          <tbody>
            {names.map((r) => (
              <tr key={r}>
                <th style={{ ...tdBase, textAlign: 'left', width: 'auto', minWidth: 90, padding: '0 6px', whiteSpace: 'nowrap' }} title={r}>{short(r)}</th>
                {names.map((c) => {
                  const v = r === c ? null : cell.get(`${r}|${c}`);
                  const alpha = v && max ? (0.15 + 0.75 * (v / max)).toFixed(2) : 0;
                  return (
                    <td key={c} title={v ? `${r} → ${c} · ${v}회` : undefined}
                      style={{ ...tdBase, background: v ? `rgba(37, 99, 235, ${alpha})` : undefined, color: v ? '#fff' : 'var(--text-muted)' }}>
                      {r === c ? '·' : (v || '')}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Figure>
  );
}

function HotspotScatter({ hotspots }) {
  const pts = (hotspots || []).filter((h) => h.fan_in > 0);
  if (!pts.length) return null;
  // 전폭 배치(O4)라 viewBox를 키운다 — 320×180에선 점이 좌하단에 뭉쳐 라벨을 못 붙였다.
  const W = 640;
  const H = 260;
  const P = 38;
  const maxX = Math.max(...pts.map((p) => p.fan_in), 1);
  const maxY = Math.max(...pts.map((p) => p.complexity), 1);
  const sx = (v) => P + (v / maxX) * (W - P - 10);
  const sy = (v) => H - P - (v / maxY) * (H - P - 12);
  return (
    <Figure
      title="핫스팟 산포"
      hint="X=fan-in · Y=복잡도 (●측정 ccn / ○줄수 추정 — 축 척도 혼합 주의)"
    >
      {/* ⚠ maxWidth 760 을 두면 전폭 행에서 오른쪽에 죽은 여백이 남는다.
          viewBox 가 있으니 폭에 맞춰 비율대로 커지게 둔다. */}
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="핫스팟 산포도"
        preserveAspectRatio="xMidYMid meet"
        style={{ width: '100%', height: 'auto', display: 'block' }}>
        <line x1={P} y1={H - P} x2={W - 6} y2={H - P} stroke="var(--border)" />
        <line x1={P} y1={H - P} x2={P} y2={8} stroke="var(--border)" />
        <text x={W - 8} y={H - P + 14} fontSize={10} textAnchor="end" style={{ fill: 'var(--text-muted)' }}>fan-in {maxX}</text>
        <text x={P - 6} y={14} fontSize={10} textAnchor="end" style={{ fill: 'var(--text-muted)' }}>{maxY}</text>
        {pts.map((p) => (
          <g key={p.function}>
            <circle cx={sx(p.fan_in)} cy={sy(p.complexity)} r={5}
              fill={p.complexity_source === 'vcast_ccn' ? 'var(--accent)' : 'transparent'}
              stroke="var(--accent)" strokeWidth={1.5}>
              <title>{`${p.function} — fan-in ${p.fan_in} · 복잡도 ${p.complexity} (${p.complexity_source === 'vcast_ccn' ? '측정 ccn' : '줄수 추정'})`}</title>
            </circle>
            {/* 전폭이라 라벨을 붙일 여유가 생겼다 — 툴팁 없이도 상위 함수를 식별할 수 있게. */}
            <text x={sx(p.fan_in) + 8} y={sy(p.complexity) + 3} fontSize={9}
              style={{ fill: 'var(--text-muted)', pointerEvents: 'none' }}>
              {p.function.length > 22 ? `${p.function.slice(0, 21)}…` : p.function}
            </text>
          </g>
        ))}
      </svg>
    </Figure>
  );
}

/** 경로에서 파일명만. 전체 경로는 title 로 남긴다(같은 이름이 여러 디렉터리에 있을 수 있다). */
const baseName = (f) => String(f).split('/').pop();

const CYCLE_LIMIT = 8;
const MUTUAL_LIMIT = 8;

/**
 * 순환 의존 — **표 2개**. 예전엔 `c.files.join(' ↔ ')` 한 줄이라 8파일 순환이
 * `Generated_Code/Cpu.c ↔ Generated_Code/Events.c ↔ …` 로 세 줄씩 접혔고, 전체 경로가
 * 반복돼 정작 어느 파일들이 묶였는지가 안 보였다. 파일명만 보이고 경로는 title 로 옮긴다.
 */
function CycleList({ cycles }) {
  const fileSccs = cycles?.file_sccs || [];
  const mutual = cycles?.mutual_file_pairs || [];
  return (
    <Figure title="순환 의존" hint="파일 간 호출 기준"
      note={(fileSccs.length > 0 || mutual.length > 0)
        ? '* 파일명만 표시 — 전체 경로는 각 이름에 마우스를 올리면 나옵니다' : null}>
      {fileSccs.length === 0 && mutual.length === 0 && (
        <div style={T.note}>순환 의존 관측 없음</div>
      )}

      {fileSccs.length > 0 && (
        <>
          <div style={SCROLL}>
            <table style={TABLE}>
              <thead><tr><th style={T.numTh}>크기</th><th style={T.th}>순환에 묶인 파일</th></tr></thead>
              <tbody>
                {fileSccs.slice(0, CYCLE_LIMIT).map((c) => (
                  <tr key={c.files.join('|')}>
                    <td style={{ ...T.numTd, color: 'var(--color-danger)', fontWeight: 600, verticalAlign: 'top' }}>
                      {c.size}
                    </td>
                    {/* 여기만 줄바꿈 허용 — 파일이 8개까지 들어오므로 한 줄 고정은 불가능하다.
                        대신 파일명 단위로만 접히게 각 이름을 nowrap 조각으로 낸다. */}
                    <td style={{ ...T.td, whiteSpace: 'normal', lineHeight: 1.6 }}>
                      {c.files.map((f, i) => (
                        <span key={f}>
                          {i > 0 && <span style={{ color: 'var(--text-muted)' }}> ↔ </span>}
                          <span title={f} style={{ whiteSpace: 'nowrap', fontFamily: 'monospace' }}>{baseName(f)}</span>
                        </span>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {fileSccs.length > CYCLE_LIMIT && (
            <div style={T.note}>* 크기 상위 {CYCLE_LIMIT}개만 표시 (총 {fileSccs.length}개)</div>
          )}
        </>
      )}

      {mutual.length > 0 && (
        <>
          <div style={{ ...T.figTitle, marginTop: 'var(--sp-2)' }}>상호 호출 (2-사이클)</div>
          <div style={SCROLL}>
            <table style={TABLE}>
              <thead>
                <tr>
                  <th style={T.th}>파일 A</th><th style={T.th}>파일 B</th>
                  <th style={T.numTh}>A→B</th><th style={T.numTh}>B→A</th>
                </tr>
              </thead>
              <tbody>
                {mutual.slice(0, MUTUAL_LIMIT).map((p) => (
                  <tr key={`${p.a}|${p.b}`}>
                    <td style={{ ...T.nameTd(180), fontFamily: 'monospace' }} title={p.a}>{baseName(p.a)}</td>
                    <td style={{ ...T.nameTd(180), fontFamily: 'monospace' }} title={p.b}>{baseName(p.b)}</td>
                    <td style={T.numTd}>{p.a_to_b}</td>
                    <td style={T.numTd}>{p.b_to_a}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {mutual.length > MUTUAL_LIMIT && (
            <div style={T.note}>* 상위 {MUTUAL_LIMIT}건만 표시 (총 {mutual.length}건)</div>
          )}
        </>
      )}

    </Figure>
  );
}

export default function ArchitectureGraphPanel({ jobUrl, cacheRoot, defaultOpen = true, reloadToken = 0 }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        // 메트릭 패널과 **같은 요청**이라 공유 캐시를 거친다(예전엔 두 패널이 각자 POST 했다).
        const resp = await fetchArchMetrics(jobUrl, cacheRoot);
        if (!cancelled) { setData(resp); setError(''); }
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
    // ⚠ reloadToken — 백필로 소스 스냅샷이 바뀌면 부모가 올린다. keep-alive 라 이 패널은
    //   언마운트되지 않아, 이게 없으면 캐시를 비워도 화면이 옛 빌드에 영구히 멈춘다.
  }, [jobUrl, cacheRoot, reloadToken]);

  // 헤더에 남길 신호 — 오류·산출 불가뿐 아니라 **절단**도 올린다.
  // 절단 고지는 전부 본문 각주라, 패널을 접으면 "58파일 중 28개만 그렸다"는 사실이
  // 화면에서 사라진다. 이 저장소가 SITS 204열 침묵 절단으로 이미 한 번 겪은 축이다.
  const truncated = useMemo(() => {
    if (!data?.available) return null;
    const notes = [];
    const fg = data.file_graph;
    if (fg?.truncated) notes.push(`파일 그래프 ${fg.total_files ?? '?'}개 중 일부`);
    if (data.module_graph?.truncated) notes.push('모듈 그래프 일부');
    const revOmitted = data.layer_graph?.reverse_pairs_omitted || 0;
    if (revOmitted > 0) notes.push(`계층 역방향 ${revOmitted}건`);
    const dsmOmitted = Math.max(0, (fg?.nodes || []).length - DSM_MAX);
    if (dsmOmitted > 0) notes.push(`DSM ${dsmOmitted}개 파일`);
    return notes.length > 0 ? notes.join(' · ') : null;
  }, [data]);

  const problem = error
    ? <span style={{ ...xs, color: 'var(--color-danger)' }}>⚠ 조회 실패 — {error}</span>
    : data?.available === false
      ? <span style={{ ...xs, color: 'var(--color-warning)' }}>다이어그램 미생성</span>
      : truncated
        ? <span style={{ ...xs, color: 'var(--color-warning)' }}>⚠ 표시 상한으로 생략 — {truncated}</span>
        : null;

  return (
    <SummaryPanel
      title="아키텍처 다이어그램 (모듈 관계·순환·핫스팟)"
      defaultOpen={defaultOpen}
      meta={<>
        {data?.available && (
          <span style={{ ...xs, color: 'var(--text-muted)' }}>
            빌드 #{data.build_number} · 모듈 {(data.module_graph?.nodes || []).length} · 관계 {(data.module_graph?.edges || []).length}
          </span>
        )}
        {!data && !error && <span className="spinner" />}
      </>}
      /* ⚠ 접으면 본문의 오류·불가·**절단 고지**가 화면에서 사라진다 — 헤더에 신호를 남긴다.
         문제가 없으면 반드시 null(항상 truthy 인 프래그먼트를 주면 영구히 펼쳐진다). */
      problem={problem}
    >
      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>아키텍처 다이어그램 오류: {error}</div>}
      {data && data.available === false && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          {data.reason === 'no_source_snapshot' ? '캐시 빌드에 소스 스냅샷이 없어 다이어그램을 만들 수 없습니다.'
            : `아키텍처 다이어그램을 만들 수 없습니다 (${data.reason})`}
        </div>
      )}

      {data?.available && (
        /* ⚠ 그림을 세로로만 쌓으니 넓은 화면에서 오른쪽이 통째로 비고 스크롤만 길어졌다
             → 2열 그리드. DSM 만 28×28 이라 폭이 필요해 전폭(`gridColumn: 1/-1`)으로 뺀다.
             `min(100%, 440px)` 이라 좁은 화면에선 자동으로 1열이 된다. */
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 440px), 1fr))',
          gap: 'var(--sp-4)', alignItems: 'start',
        }}>
          <ModuleDiagram moduleGraph={data.module_graph} cycles={data.cycles} fileGraph={data.file_graph} />
          {/* Q2: 계층(ISO 26262-6 관점) → 결합 히트맵 → DSM(순환) → 전역 흐름 → 핫스팟 산포.
              O4에서 정한 '히트맵 위 / 산포 아래' 순서는 유지하고 사이에 신규 3종을 끼운다. */}
          {SHOW.layerDiagram && <LayerDiagram layerGraph={data.layer_graph} />}
          <CouplingHeatmap moduleGraph={data.module_graph} />
          {/* DSM(28×28)·산포도는 전폭이 필요하다 — 산포도는 viewBox 640×260 에 맞춰 만든 것이라
              반폭(≈440px)으로 줄이면 점이 좌하단에 뭉쳐 라벨을 못 붙인다(O4에서 겪은 그 문제).
              배치 결과: [모듈|히트맵] / [DSM] / [산포도] / [순환|개선후보] / [각주] */}
          <div style={{ gridColumn: '1 / -1' }}><DsmMatrix fileGraph={data.file_graph} /></div>
          {SHOW.globalFlow && <GlobalFlow globalCoupling={data.global_coupling} />}
          <div style={{ gridColumn: '1 / -1' }}><HotspotScatter hotspots={data.hotspots} /></div>
          <CycleList cycles={data.cycles} />
          {/* 목록이 아니라 표다 — 종류/대상/근거 세 축이 있는데 한 줄 문장으로 이어 붙이면
              눈이 축을 못 잡는다(같은 데이터를 다른 패널은 이미 표로 낸다). */}
          <Figure title="구조 개선 후보" hint="결정론 관측">
            {(data.refactor_candidates || []).length === 0 ? (
              <div style={T.note}>임계를 넘는 후보 관측 없음</div>
            ) : (
              <div style={SCROLL}>
                <table style={TABLE}>
                  <thead><tr><th style={T.th}>종류</th><th style={T.th}>대상</th><th style={T.th}>근거</th></tr></thead>
                  <tbody>
                    {(data.refactor_candidates || []).map((c) => {
                      const target = c.file || (c.files || []).join(' ↔ ');
                      return (
                        <tr key={c.kind + target}>
                          <td style={{ ...T.td, fontWeight: 600 }}>{c.kind === 'god_file' ? '집중 파일' : '상호 의존'}</td>
                          <td style={T.nameTd(200)} title={target}>{target}</td>
                          <td style={T.textTd(260)}>{c.basis}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Figure>
          <div style={{ gridColumn: '1 / -1', ...xs, color: 'var(--text-muted)' }}>
            * 관계=함수 호출 기반(include 미분석) · 모듈=디렉터리 프록시 · 파서 {data.snapshot?.parser_engine || '—'}
          </div>
        </div>
      )}
    </SummaryPanel>
  );
}
