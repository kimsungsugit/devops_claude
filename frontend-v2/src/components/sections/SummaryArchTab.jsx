import ArchitectureMetricsPanel from './ArchitectureMetricsPanel.jsx';
import ArchitectureGraphPanel from './ArchitectureGraphPanel.jsx';
import ArchitectureImprovementPanel from './ArchitectureImprovementPanel.jsx';

/**
 * 아키텍처 서브탭 — 소스 스냅샷 기준 구조.
 *
 * 3패널 전부 기본 펼침이다. 처음엔 다이어그램을 접었는데(코드 664줄로 이 탭에서 가장 길다)
 * **실측하니 렌더 높이는 그렇지 않았다** — KJPDS02_PV 기준 모듈 8노드 · 결합 히트맵 8×8 ·
 * DSM 28×28(파일 62개 중) · 산포도 640×260 ≈ 1.5화면. 서브탭 분리로 스크롤이 이미 1/3이 된
 * 마당에, 사용자가 '아키텍처'를 눌러 놓고 정작 그림이 접혀 있는 건 과교정이다.
 * (코드 줄 수 ≠ 렌더 높이 — 접힘 기본값은 실측으로 정한다.)
 */
export default function SummaryArchTab({ jobUrl, cacheRoot, reloadToken = 0 }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--sp-3)' }}>
      {/* 아키텍처 메트릭 — 핫스팟/결합도/대형 함수 + v4 4축(간섭·전역·사분면·간접호출) */}
      <ArchitectureMetricsPanel jobUrl={jobUrl} cacheRoot={cacheRoot} reloadToken={reloadToken} />

      {/* 아키텍처 다이어그램 — 모듈 관계·계층·DSM·전역 흐름·핫스팟 산포 (K2·Q2) */}
      <ArchitectureGraphPanel jobUrl={jobUrl} cacheRoot={cacheRoot} reloadToken={reloadToken} />

      {/* 아키텍처 개선 제안(To-Be) — 결정론 후보 + AI 목표 구조 (Q3) */}
      <ArchitectureImprovementPanel jobUrl={jobUrl} cacheRoot={cacheRoot} reloadToken={reloadToken} />
    </div>
  );
}
