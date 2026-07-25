/**
 * ArchitectureGraphPanel — 아키텍처 다이어그램(K2): 모듈 의존 그래프(SVG)·결합 히트맵·
 * 핫스팟 산포도·순환 의존 목록. POST /api/summary/architecture-metrics(v3, 결정론) 소비.
 *
 * ISO 정직성: 관계는 함수 호출 기반(include 미분석)·모듈은 디렉터리 프록시·파서 엔진을
 * 각주로 상시 표기. 사이클 0건은 "관측 없음"을 명시 렌더(침묵 생략 금지). 산포도 Y축은
 * 복잡도 출처 혼합(vcast_ccn 측정 vs loc_proxy 줄수 추정)이라 마커 모양으로 구분한다.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { post } from '../../api.js';
import { AG, layoutModules } from '../archGraphLayout.js';
import { bezierEdgeH, exportPng, exportSvg } from '../graphPrimitives.jsx';

const xs = { fontSize: 'var(--text-xs)' };
const btn = {
  ...xs, padding: '1px 8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)',
  background: 'transparent', cursor: 'pointer', color: 'var(--text-muted)',
};

const { NODE_W, NODE_H } = AG;

function ModuleDiagram({ moduleGraph, cycles }) {
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
    <div>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 4 }}>
        <span style={{ ...xs, color: 'var(--text-muted)' }}>모듈 의존 다이어그램 (호출 수 라벨 · 순환은 빨강)</span>
        <button type="button" style={btn} onClick={() => exportSvg(svgRef.current, 'architecture-modules.svg')}>SVG 저장</button>
        <button type="button" style={btn} onClick={() => exportPng(svgRef.current, 'architecture-modules.png')}>PNG 저장</button>
      </div>
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
        </div>
      )}
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
  const short = (m) => (m.length > 14 ? `${m.slice(0, 13)}…` : m);
  const tdBase = { ...xs, padding: '2px 6px', border: '1px solid var(--border)', textAlign: 'center' };
  return (
    <div>
      <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>모듈 결합 히트맵 (행→열 호출 수)</div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ borderCollapse: 'collapse' }}>
          <thead>
            <tr>
              <th style={tdBase} />
              {names.map((c) => <th key={c} style={tdBase} title={c}>{short(c)}</th>)}
            </tr>
          </thead>
          <tbody>
            {names.map((r) => (
              <tr key={r}>
                <th style={{ ...tdBase, textAlign: 'left' }} title={r}>{short(r)}</th>
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
      {(moduleGraph?.nodes || []).length > 20 && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>* 함수 수 상위 20개 모듈만 표시</div>
      )}
    </div>
  );
}

function HotspotScatter({ hotspots }) {
  const pts = (hotspots || []).filter((h) => h.fan_in > 0);
  if (!pts.length) return null;
  const W = 320;
  const H = 180;
  const P = 30;
  const maxX = Math.max(...pts.map((p) => p.fan_in), 1);
  const maxY = Math.max(...pts.map((p) => p.complexity), 1);
  const sx = (v) => P + (v / maxX) * (W - P - 10);
  const sy = (v) => H - P - (v / maxY) * (H - P - 12);
  return (
    <div>
      <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>
        핫스팟 산포 — X=fan-in · Y=복잡도 (●측정 ccn / ○줄수 추정 — 축 척도 혼합 주의)
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label="핫스팟 산포도" style={{ maxWidth: '100%' }}>
        <line x1={P} y1={H - P} x2={W - 6} y2={H - P} stroke="var(--border)" />
        <line x1={P} y1={H - P} x2={P} y2={8} stroke="var(--border)" />
        <text x={W - 8} y={H - P + 12} fontSize={9} textAnchor="end" style={{ fill: 'var(--text-muted)' }}>fan-in {maxX}</text>
        <text x={P - 4} y={12} fontSize={9} textAnchor="end" style={{ fill: 'var(--text-muted)' }}>{maxY}</text>
        {pts.map((p) => (
          <circle key={p.function} cx={sx(p.fan_in)} cy={sy(p.complexity)} r={4}
            fill={p.complexity_source === 'vcast_ccn' ? 'var(--accent)' : 'transparent'}
            stroke="var(--accent)" strokeWidth={1.5}>
            <title>{`${p.function} — fan-in ${p.fan_in} · 복잡도 ${p.complexity} (${p.complexity_source === 'vcast_ccn' ? '측정 ccn' : '줄수 추정'})`}</title>
          </circle>
        ))}
      </svg>
    </div>
  );
}

function CycleList({ cycles }) {
  const fileSccs = cycles?.file_sccs || [];
  const mutual = cycles?.mutual_file_pairs || [];
  return (
    <div>
      <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>순환 의존 (파일 간 호출 기준)</div>
      {fileSccs.length === 0 && mutual.length === 0 && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>순환 의존 관측 없음 (파일 간 호출 기준)</div>
      )}
      {fileSccs.map((c) => (
        <div key={c.files.join('|')} style={{ ...xs, marginBottom: 2 }}>
          <span style={{ color: 'var(--color-danger)', fontWeight: 600 }}>순환 {c.size}파일</span>{' '}
          {c.files.join(' ↔ ')}
        </div>
      ))}
      {mutual.map((p) => (
        <div key={`${p.a}|${p.b}`} style={{ ...xs, color: 'var(--text-muted)' }}>
          상호 호출 {p.a} → {p.b} {p.a_to_b}회 · {p.b} → {p.a} {p.b_to_a}회
        </div>
      ))}
    </div>
  );
}

export default function ArchitectureGraphPanel({ jobUrl, cacheRoot }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!jobUrl) return undefined;
    let cancelled = false;
    (async () => {
      try {
        const resp = await post('/api/summary/architecture-metrics', { job_url: jobUrl, cache_root: cacheRoot });
        if (!cancelled) { setData(resp); setError(''); }
      } catch (e) {
        if (!cancelled) setError(String(e?.message || e));
      }
    })();
    return () => { cancelled = true; };
  }, [jobUrl, cacheRoot]);

  return (
    <div className="panel" style={{ padding: 'var(--sp-3)' }}>
      <div style={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 'var(--sp-2)', marginBottom: 'var(--sp-2)' }}>
        <div style={{ fontSize: 'var(--text-sm)', fontWeight: 600 }}>아키텍처 다이어그램 (모듈 관계·순환·핫스팟)</div>
        {data?.available && (
          <span style={{ ...xs, color: 'var(--text-muted)' }}>
            빌드 #{data.build_number} · 모듈 {(data.module_graph?.nodes || []).length} · 관계 {(data.module_graph?.edges || []).length}
          </span>
        )}
        {!data && !error && <span className="spinner" />}
      </div>

      {error && <div style={{ ...xs, color: 'var(--color-danger)' }}>아키텍처 다이어그램 오류: {error}</div>}
      {data && data.available === false && (
        <div style={{ ...xs, color: 'var(--text-muted)' }}>
          {data.reason === 'no_source_snapshot' ? '캐시 빌드에 소스 스냅샷이 없어 다이어그램을 만들 수 없습니다.'
            : `아키텍처 다이어그램을 만들 수 없습니다 (${data.reason})`}
        </div>
      )}

      {data?.available && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-4)' }}>
          <ModuleDiagram moduleGraph={data.module_graph} cycles={data.cycles} />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 'var(--sp-4)' }}>
            <CouplingHeatmap moduleGraph={data.module_graph} />
            <HotspotScatter hotspots={data.hotspots} />
            <CycleList cycles={data.cycles} />
            <div>
              <div style={{ ...xs, color: 'var(--text-muted)', marginBottom: 4 }}>구조 개선 후보 (결정론 관측)</div>
              {(data.refactor_candidates || []).length === 0 && (
                <div style={{ ...xs, color: 'var(--text-muted)' }}>임계를 넘는 후보 관측 없음</div>
              )}
              {(data.refactor_candidates || []).map((c) => (
                <div key={c.kind + (c.file || (c.files || []).join('|'))} style={{ ...xs, marginBottom: 2 }}>
                  <span style={{ fontWeight: 600 }}>{c.kind === 'god_file' ? '집중 파일' : '상호 의존'}</span>{' '}
                  {c.file || (c.files || []).join(' ↔ ')} — {c.basis}
                </div>
              ))}
            </div>
          </div>
          <div style={{ ...xs, color: 'var(--text-muted)' }}>
            * 관계=함수 호출 기반(include 미분석) · 모듈=디렉터리 프록시 · 파서 {data.snapshot?.parser_engine || '—'}
          </div>
        </div>
      )}
    </div>
  );
}
