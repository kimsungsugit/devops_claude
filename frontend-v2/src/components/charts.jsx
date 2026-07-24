/**
 * charts.jsx — 자작 CSS/SVG 차트 프리미티브(외부 차트 라이브러리 없음).
 * AggregateCharts.jsx에서 HorizontalBar/DonutChart를 추출하고(라벨 파라미터화),
 * RingGauge(도넛 arc 재사용)·MiniTrend(빌드별 막대)를 추가한다. 프로젝트 요약 탭 재설계 공유.
 */

// 가로 막대 — label(120px) + 트랙 + 값(55px). value가 숫자면 toLocaleString.
export function HorizontalBar({ label, value, max, color, suffix = '' }) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)', marginBottom: 'var(--sp-1)' }}>
      <span
        style={{ width: 120, fontSize: 'var(--text-xs)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 0 }}
        title={label}
      >
        {label}
      </span>
      <div style={{ flex: 1, height: 16, background: 'var(--border)', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 'var(--radius-sm)', transition: 'width 0.4s' }} />
      </div>
      <span style={{ width: 55, textAlign: 'right', fontSize: 'var(--text-xs)', fontWeight: 600, flexShrink: 0 }}>
        {typeof value === 'number' && !suffix ? value.toLocaleString() : value}{suffix}
      </span>
    </div>
  );
}

// 도넛(SVG circle + strokeDasharray). 중앙 라벨/서브라벨 파라미터화(과거 "프로젝트" 하드코딩 제거).
export function DonutChart({ segments, size = 100, strokeWidth = 16, centerLabel, centerSub }) {
  const total = segments.reduce((s, seg) => s + seg.value, 0);
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;

  // 오프셋 사전계산(렌더 중 변형 회피).
  const arcs = segments.reduce((acc, seg) => {
    const pct = total > 0 ? seg.value / total : 0;
    const dashLen = pct * circumference;
    const prevOffset = acc.length > 0 ? acc[acc.length - 1].offset + acc[acc.length - 1].dashLen : 0;
    acc.push({ ...seg, dashLen, offset: prevOffset });
    return acc;
  }, []);

  return (
    <div style={{ position: 'relative', width: size, height: size }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        {arcs.map((arc, i) => (
          <circle
            key={i}
            cx={size / 2}
            cy={size / 2}
            r={radius}
            fill="none"
            stroke={arc.color}
            strokeWidth={strokeWidth}
            strokeDasharray={`${arc.dashLen} ${circumference - arc.dashLen}`}
            strokeDashoffset={-arc.offset}
          />
        ))}
      </svg>
      <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%,-50%)', textAlign: 'center' }}>
        <div style={{ fontSize: 'var(--text-xl)', fontWeight: 700 }}>{centerLabel ?? total}</div>
        {centerSub != null && <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>{centerSub}</div>}
      </div>
    </div>
  );
}

// 링 게이지 — 0~100(%) 단일값을 도넛(값 arc + 트랙)으로. null이면 '—'(0% 위장 금지 — ISO 정직성).
export function RingGauge({ value, size = 96, strokeWidth = 12, color, label, suffix = '%', track = 'var(--border)' }) {
  const v = value == null || Number.isNaN(Number(value)) ? null : Math.max(0, Math.min(100, Number(value)));
  const segments = v == null
    ? [{ value: 1, color: track }]
    : [{ value: v, color }, { value: 100 - v, color: track }];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
      <DonutChart segments={segments} size={size} strokeWidth={strokeWidth}
        centerLabel={v == null ? '—' : `${Math.round(v)}${suffix}`} />
      {label && <div style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', textAlign: 'center' }}>{label}</div>}
    </div>
  );
}

// 미니 트렌드 — 빌드별 막대(SVG viewBox 100x40, preserveAspectRatio none로 가로 스케일).
// data=[{...}] 오래된→최신 순, valueKey로 값 선택. threshold 있으면 점선. 빈 데이터면 null.
export function MiniTrend({ data, valueKey, height = 90, color = 'var(--accent)', threshold }) {
  if (!Array.isArray(data) || data.length === 0) return null;
  const vals = data.map(d => Number(d?.[valueKey]) || 0);
  const maxV = Math.max(...vals, threshold || 0, 1);
  const barW = 100 / data.length;
  const thY = threshold != null ? 40 - (Math.min(threshold, maxV) / maxV) * 38 : null;
  return (
    <svg viewBox="0 0 100 40" preserveAspectRatio="none" style={{ width: '100%', height, display: 'block' }}>
      {thY != null && (
        <line x1="0" y1={thY} x2="100" y2={thY} stroke="var(--color-warning)" strokeWidth="0.4" strokeDasharray="1.5 1.5" />
      )}
      {data.map((d, i) => {
        const v = Number(d?.[valueKey]) || 0;
        const h = (v / maxV) * 38;
        return (
          <rect key={i} x={i * barW + barW * 0.15} y={40 - h} width={barW * 0.7} height={Math.max(h, 0.5)} fill={color}>
            <title>{`${d?.label ?? i}: ${v}`}</title>
          </rect>
        );
      })}
    </svg>
  );
}
