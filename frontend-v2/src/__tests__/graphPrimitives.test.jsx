/** graphPrimitives — 베지어 path·SVG 직렬화(var 인라인/배경/dim 복원)·다운로드. */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { bezierEdgeH, downloadBlob, svgToExportString } from '../components/graphPrimitives.jsx';

describe('graphPrimitives', () => {
  afterEach(() => vi.restoreAllMocks());

  it('bezierEdgeH — 수평 3차 베지어 d 형식(중점 제어점)', () => {
    expect(bezierEdgeH(10, 20, 100, 40)).toBe('M10,20 C55,20 55,40 100,40');
  });

  it('svgToExportString — var() 인라인(fallback)·배경 rect·g[opacity] 복원', () => {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 100 50');
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('opacity', '0.28'); // hover dim — 내보내기에선 복원돼야 함
    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    rect.setAttribute('fill', 'var(--fg, #123456)');
    g.appendChild(rect);
    svg.appendChild(g);
    document.body.appendChild(svg);
    const s = svgToExportString(svg);
    expect(s).not.toContain('var(');           // 전 CSS 변수 인라인
    expect(s).toContain('#123456');            // jsdom엔 변수값이 없어 fallback 채택
    expect(s).toContain('opacity="1"');        // dim 복원 — 선택 상태로 내보내도 워시아웃 없음
    expect(s.indexOf('<rect')).toBeLessThan(s.indexOf('<g'));  // 배경 rect가 최하단(첫 자식)
    svg.remove();
  });

  it('downloadBlob — 오브젝트 URL 생성/앵커 클릭/해제', () => {
    const created = vi.fn(() => 'blob:mock');
    const revoked = vi.fn();
    vi.stubGlobal('URL', { ...URL, createObjectURL: created, revokeObjectURL: revoked });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    vi.useFakeTimers();
    downloadBlob(new Blob(['x']), 'a.svg');
    expect(created).toHaveBeenCalledTimes(1);
    expect(click).toHaveBeenCalledTimes(1);
    vi.runAllTimers();
    expect(revoked).toHaveBeenCalledWith('blob:mock');
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });
});
