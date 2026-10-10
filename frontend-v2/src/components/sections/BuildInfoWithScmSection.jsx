import BuildInfoSection from './BuildInfoSection.jsx';
import ScmSection from './ScmSection.jsx';

/**
 * 빌드 정보 + SCM 통합 탭.
 *
 * 빌드 로그(BuildInfoSection의 마지막 패널) 아래에 SCM 정보를 이어 배치해 한 탭으로 통합한다.
 * 두 섹션 컴포넌트는 각각 순수하게 유지하고 여기서 조합만 한다(동일 props 전달). SCM 시작 지점은
 * 상단 구분선 + '🌿 SCM' 헤딩으로 시각적으로 분리한다.
 */
export default function BuildInfoWithScmSection({ job, analysisResult }) {
  return (
    <div>
      <BuildInfoSection job={job} analysisResult={analysisResult} />
      <div
        className="mt-3"
        style={{ borderTop: '2px solid var(--border)', paddingTop: 12, marginTop: 16 }}
      >
        <div className="panel-title" style={{ fontSize: 15, marginBottom: 8 }}>{'🌿'} SCM</div>
        <ScmSection job={job} analysisResult={analysisResult} />
      </div>
    </div>
  );
}
