import { useState, useEffect } from 'react';
import { useJob } from '../App.jsx';
import BuildInfoSection from '../components/sections/BuildInfoSection.jsx';
import ScmSection from '../components/sections/ScmSection.jsx';
import AnalysisSection from '../components/sections/AnalysisSection.jsx';
import SrsSdsSection from '../components/sections/SrsSdsSection.jsx';
import DocGenSection from '../components/sections/DocGenSection.jsx';
import AiAssistSection from '../components/sections/AiAssistSection.jsx';
import ReportGenSection from '../components/sections/ReportGenSection.jsx';
import ImpactGuideSection from '../components/sections/ImpactGuideSection.jsx';
import ProjectSetupSection from '../components/sections/ProjectSetupSection.jsx';

const SECTIONS = [
  { id: 'build',   icon: '🔨', label: '빌드 정보',    Component: BuildInfoSection },
  { id: 'scm',     icon: '🌿', label: 'SCM',          Component: ScmSection },
  { id: 'analysis',icon: '📊', label: '프로젝트 분석', Component: AnalysisSection },
  { id: 'setup',   icon: '⚙️', label: '프로젝트 설정', Component: ProjectSetupSection },
  { id: 'impact',  icon: '🔍', label: '변경 영향 가이드', Component: ImpactGuideSection },
  { id: 'srssds',  icon: '📋', label: 'SRS/SDS 매핑', Component: SrsSdsSection },
  { id: 'docgen',  icon: '📝', label: '문서 생성',     Component: DocGenSection },
  { id: 'reports', icon: '📈', label: '리포트 생성',   Component: ReportGenSection },
  { id: 'ai',      icon: '🤖', label: 'AI 어시스턴트', Component: AiAssistSection },
];

export default function Detail() {
  const { selectedJob, analysisResult } = useJob();
  const [activeSection, setActiveSection] = useState('build');

  // Allow external section navigation (from Dashboard)
  useEffect(() => {
    window.__detailSection = (section) => {
      if (SECTIONS.some(s => s.id === section)) setActiveSection(section);
    };
    return () => { delete window.__detailSection; };
  }, []);

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
  const { Component } = current;

  return (
    <div>
      {/* Breadcrumb */}
      <div className="row" style={{ marginBottom: 12, fontSize: 12, color: 'var(--text-muted)' }}>
        <span>대시보드</span>
        <span>›</span>
        <span style={{ color: 'var(--text)', fontWeight: 600 }}>{selectedJob.name}</span>
        <span>›</span>
        <span style={{ color: 'var(--accent)' }}>{current.label}</span>
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

        {/* Right content */}
        <div className="detail-content">
          <Component
            job={selectedJob}
            analysisResult={analysisResult}
          />
        </div>
      </div>
    </div>
  );
}
