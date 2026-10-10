/**
 * graphPrimitives — SVG 다이어그램 공용 프리미티브 (K2).
 *
 * 출처: SrsSdsSection.jsx의 module-private 스캐폴딩(_bez/_graphSvgString/_downloadBlob)을
 * 일반화한 신규 구현 — 344KB 원본은 무접촉(전용 테스트 2본 리스크 회피, 계획서 K2 판정).
 * 원본과 달리 var() 인라인은 특정 3종 치환이 아니라 전 CSS 변수를 computed 값으로 치환한다.
 */

/** 수평 3차 베지어 엣지 path d — 좌→우 층위 배치 그래프의 표준 엣지. */
export function bezierEdgeH(x1, y1, x2, y2) {
  const mx = (x1 + x2) / 2;
  return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
}

/**
 * 내보내기용 SVG 직렬화 — CSS 변수를 현재 테마 computed 값으로 인라인.
 * 다운로드된 SVG/PNG는 앱 CSS 컨텍스트 밖이라 var()가 해석되지 않는다. hover dim
 * (<g opacity>)은 복원하고, 뷰어 흰배경에 다크테마가 묻히지 않게 불투명 배경 rect를 깐다.
 */
export function svgToExportString(svgEl) {
  const clone = svgEl.cloneNode(true);
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
  const cs = getComputedStyle(svgEl);
  clone.querySelectorAll('g[opacity]').forEach((g) => g.setAttribute('opacity', '1'));
  const bg = (cs.getPropertyValue('--bg') || '#ffffff').trim() || '#ffffff';
  const bgRect = clone.ownerDocument.createElementNS('http://www.w3.org/2000/svg', 'rect');
  bgRect.setAttribute('width', '100%');
  bgRect.setAttribute('height', '100%');
  bgRect.setAttribute('fill', bg);
  clone.insertBefore(bgRect, clone.firstChild);
  const s = new XMLSerializer().serializeToString(clone);
  return s.replace(/var\((--[A-Za-z0-9-]+)(?:\s*,\s*([^)]+))?\)/g, (_m, name, fallback) => {
    const v = (cs.getPropertyValue(name) || '').trim();
    return v || (fallback || '').trim() || '#000000';
  });
}

export function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}

export function exportSvg(svgEl, filename) {
  if (!svgEl) return;
  const s = svgToExportString(svgEl);
  downloadBlob(new Blob([s], { type: 'image/svg+xml;charset=utf-8' }), filename);
}

/** SVG → 캔버스 래스터 → PNG 다운로드 (scale 배율, 배경은 현재 테마 --bg 불투명). */
export function exportPng(svgEl, filename, scale = 2) {
  if (!svgEl) return;
  const s = svgToExportString(svgEl);
  const url = URL.createObjectURL(new Blob([s], { type: 'image/svg+xml;charset=utf-8' }));
  const img = new Image();
  img.onload = () => {
    const vb = svgEl.viewBox && svgEl.viewBox.baseVal;
    const w = (vb && vb.width) || svgEl.clientWidth || img.width || 800;
    const h = (vb && vb.height) || svgEl.clientHeight || img.height || 400;
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, Math.round(w * scale));
    canvas.height = Math.max(1, Math.round(h * scale));
    const ctx = canvas.getContext('2d');
    const bg = (getComputedStyle(svgEl).getPropertyValue('--bg') || '#ffffff').trim() || '#ffffff';
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (blob) downloadBlob(blob, filename);
      URL.revokeObjectURL(url);
    }, 'image/png');
  };
  img.onerror = () => URL.revokeObjectURL(url);
  img.src = url;
}
