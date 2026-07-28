import ArchitectureMetricsPanel from './ArchitectureMetricsPanel.jsx';
import ArchitectureGraphPanel from './ArchitectureGraphPanel.jsx';
import ArchitectureImprovementPanel from './ArchitectureImprovementPanel.jsx';

/**
 * 아키텍처 서브탭 — 소스 스냅샷 기준 구조.
 *
 * 다이어그램 패널만 기본 접힘이다: 모듈 SVG + 결합 히트맵(최대 20×20) + DSM(최대 28×28) +
 * 핫스팟 산포도(640×260)가 한 카드에 들어 있어 이 탭에서 압도적으로 길다. 접어도 헤더의
 * `모듈 N · 관계 M` 은 그대로 보이므로 "그림이 사라졌다"로 읽히지 않는다.
 */
export default function SummaryArchTab({ jobUrl, cacheRoot }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
      {/* 아키텍처 메트릭 — 핫스팟/결합도/대형 함수 + v4 4축(간섭·전역·사분면·간접호출) */}
      <ArchitectureMetricsPanel jobUrl={jobUrl} cacheRoot={cacheRoot} />

      {/* 아키텍처 다이어그램 — 모듈 관계·계층·DSM·전역 흐름·핫스팟 산포 (K2·Q2) */}
      <ArchitectureGraphPanel jobUrl={jobUrl} cacheRoot={cacheRoot} defaultOpen={false} />

      {/* 아키텍처 개선 제안(To-Be) — 결정론 후보 + AI 목표 구조 (Q3) */}
      <ArchitectureImprovementPanel jobUrl={jobUrl} cacheRoot={cacheRoot} />
    </div>
  );
}
