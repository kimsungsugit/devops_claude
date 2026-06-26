import { useState, useEffect, useCallback, useRef } from 'react';
import { useJob } from '../App.jsx';
import BuildInfoSection from '../components/sections/BuildInfoSection.jsx';
import ScmSection from '../components/sections/ScmSection.jsx';
import AnalysisSection from '../components/sections/AnalysisSection.jsx';
import SrsSdsSection from '../components/sections/SrsSdsSection.jsx';
import DocGenHubSection from '../components/sections/DocGenHubSection.jsx';
import AiAssistSection from '../components/sections/AiAssistSection.jsx';
import ImpactGuideSection from '../components/sections/ImpactGuideSection.jsx';
import ProjectSetupSection from '../components/sections/ProjectSetupSection.jsx';

const SECTIONS = [
  { id: 'build',   icon: '🔨', label: '빌드 정보',    Component: BuildInfoSection },
  { id: 'scm',     icon: '🌿', label: 'SCM',          Component: ScmSection },
  { id: 'analysis',icon: '📊', label: '프로젝트 분석', Component: AnalysisSection },
  { id: 'setup',   icon: '⚙️', label: '프로젝트 설정', Component: ProjectSetupSection },
  { id: 'impact',  icon: '🔍', label: '변경 영향 가이드', Component: ImpactGuideSection },
  { id: 'srssds',  icon: '📋', label: '추적성 분석', Component: SrsSdsSection },
  // 생성 6종(문서/리포트/SwUT/SwIT/SwSA/통합결과)을 단일 탭으로 통합 — 내부 옵션 세그먼트로 전환.
  { id: 'docgen',  icon: '📝', label: '문서 생성',     Component: DocGenHubSection },
  { id: 'ai',      icon: '🤖', label: 'AI 어시스턴트', Component: AiAssistSection },
];

// 통합 전 개별 탭 id — 외부 네비게이션 호환용. docgen 허브로 라우팅 후 서브 선택.
const DOCGEN_SUB_IDS = new Set(['docgen', 'reports', 'swut', 'swit', 'swsa', 'swreport']);

export default function Detail() {
  const { selectedJob, analysisResult } = useJob();
  const [activeSection, setActiveSection] = useState('build');
  // 문서 생성 허브의 활성 서브(종류) — breadcrumb 표기용.
  const [docgenSub, setDocgenSub] = useState(null);
  const handleSubChange = useCallback((id, label) => setDocgenSub({ id, label }), []);
  // 레거시 생성 탭 id로 외부 라우팅 시 허브에 전달할 초기 서브(1회 소비).
  const [pendingSub, setPendingSub] = useState(null);
  // keep-alive: 한 번 방문한 탭은 마운트를 유지(display:none)해, 탭을 바꿔도 오래 걸려 얻은
  // 결과(VectorCAST 커버리지·영향 가이드 등 컴포넌트 로컬 상태)가 언마운트로 사라지지 않게 한다.
  const [visited, setVisited] = useState(() => new Set(['build']));
  const jobKey = selectedJob?.url || selectedJob?.name || '';

  // 활성 탭을 방문 기록에 누적 — 이후 숨겨져도 마운트 유지.
  useEffect(() => {
    setVisited((v) => (v.has(activeSection) ? v : new Set(v).add(activeSection)));
  }, [activeSection]);

  // activeSection 최신값을 ref로 추적 — jobKey 변경 effect가 stale closure 없이 현재 탭을 읽도록.
  const activeSectionRef = useRef(activeSection);
  activeSectionRef.current = activeSection;

  // job 변경 시 keep-alive 초기화 — 이전 job의 stale 상태/숨은 섹션 재요청 방지(key도 jobKey 포함).
  // activeSection은 ref로 읽어 deps 불필요(매 탭 전환마다 리셋되면 keep-alive 무의미하므로 jobKey만 구독).
  useEffect(() => {
    setVisited(new Set([activeSectionRef.current]));
  }, [jobKey]);

  // Allow external section navigation (from Dashboard)
  useEffect(() => {
    window.__detailSection = (section) => {
      // 통합 전 개별 생성 탭 id가 들어오면 docgen 허브로 라우팅 + initialSub prop으로 서브 선택.
      if (DOCGEN_SUB_IDS.has(section)) {
        setActiveSection('docgen');
        setPendingSub(section);
        return;
      }
      if (SECTIONS.some(s => s.id === section)) setActiveSection(section);
    };
    return () => { delete window.__detailSection; };
  }, []);

  // docgen 섹션을 벗어나면 stale 서브 라벨 정리 — 복귀 시 hub remount 전 한 프레임 깜빡임 방지.
  useEffect(() => {
    if (activeSection !== 'docgen') setDocgenSub(null);
  }, [activeSection]);

  // initialSub는 허브가 1회 소비 → 즉시 초기화(remount마다 재강제 방지).
  useEffect(() => {
    if (pendingSub != null) setPendingSub(null);
  }, [pendingSub]);

  if (!selectedJob) {
    return (
      <div className="empty-state">
        <div className="empty-icon">📂</div>
        <div className="empty-title">프로젝트를 선택하세요</div>
        <div className="empty-desc">
          대시보드에서 Jenkins Job을 선택하고 분석을 실행하면<br />
          여기서 세부 데이터를 확인할 수 있습니다.
        </div>
      </div>
    );
  }

  const current = SECTIONS.find(s => s.id === activeSection) ?? SECTIONS[0];

  return (
    <div>
      {/* Breadcrumb */}
      <div className="row" style={{ marginBottom: 12, fontSize: 12, color: 'var(--text-muted)' }}>
        <span>대시보드</span>
        <span>›</span>
        <span style={{ color: 'var(--text)', fontWeight: 600 }}>{selectedJob.name}</span>
        <span>›</span>
        <span style={{ color: 'var(--accent)' }}>{current.label}</span>
        {activeSection === 'docgen' && docgenSub && docgenSub.id !== 'docgen' && (
          <>
            <span>›</span>
            <span style={{ color: 'var(--accent)' }}>{docgenSub.label}</span>
          </>
        )}
      </div>

      <div className="detail-layout">
        {/* Left accordion nav */}
        <nav className="accordion-nav">
          {SECTIONS.map(s => (
            <div key={s.id} className="accordion-item">
              <div
                className={`accordion-header${activeSection === s.id ? ' active' : ''}`}
                onClick={() => setActiveSection(s.id)}
              >
                <span className="accordion-icon">{s.icon}</span>
                <span className="accordion-label">{s.label}</span>
              </div>
            </div>
          ))}
        </nav>

        {/* Right content — 방문한 섹션은 모두 마운트 유지(비활성은 display:none)해 상태 보존(keep-alive). */}
        <div className="detail-content">
          {SECTIONS.map((s) => {
            const isActive = s.id === activeSection;
            // 아직 방문 안 한 탭은 마운트하지 않음(불필요한 초기 요청 회피). 방문 후엔 숨겨도 유지.
            if (!isActive && !visited.has(s.id)) return null;
            const C = s.Component;
            return (
              <div key={`${jobKey}::${s.id}`} style={isActive ? undefined : { display: 'none' }}>
                <C
                  job={selectedJob}
                  analysisResult={analysisResult}
                  onSubChange={s.id === 'docgen' ? handleSubChange : undefined}
                  initialSub={s.id === 'docgen' ? pendingSub : undefined}
                />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
