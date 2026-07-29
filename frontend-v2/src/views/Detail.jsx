import { useState, useEffect, useCallback, useRef, useMemo, Fragment } from 'react';
import { useJob, useJenkinsCfg, useToast } from '../App.jsx';
import { post } from '../api.js';
import { loadProjectFromCache } from '../projectLoader.js';
import BuildInfoWithScmSection from '../components/sections/BuildInfoWithScmSection.jsx';
import AnalysisSection from '../components/sections/AnalysisSection.jsx';
import SrsSdsSection from '../components/sections/SrsSdsSection.jsx';
import DocGenHubSection from '../components/sections/DocGenHubSection.jsx';
import AiAssistSection from '../components/sections/AiAssistSection.jsx';
import ImpactGuideSection from '../components/sections/ImpactGuideSection.jsx';
import ProjectSetupSection from '../components/sections/ProjectSetupSection.jsx';
import ProjectSummarySection from '../components/sections/ProjectSummarySection.jsx';

const SECTIONS = [
  // 빌드 정보 + SCM 통합 — SCM은 빌드 로그 아래에 배치(BuildInfoWithScmSection). **기본 진입 탭**.
  { id: 'build',   icon: '🔨', label: '빌드 & 입력 데이터 정보', Component: BuildInfoWithScmSection },
  // dividerBefore: 진입 탭(위)과 분석/결과 그룹(아래) 분리.
  { id: 'analysis',icon: '📊', label: '테스트 결과', Component: AnalysisSection, dividerBefore: true },
  // 프로젝트 분석 — 아키텍처/소스코드/빌드별 변경 영향 3그룹(구 '프로젝트 요약').
  // ⚠ id는 'summary' 유지 — window.__detailSection 딥링크와 keep-alive visited 키가 이 문자열을
  //   쓰므로 라벨만 바꾼다(라벨 ≠ id). 바꾸려면 App.jsx/Dashboard 호출부까지 함께 손봐야 한다.
  { id: 'summary', icon: '📈', label: '프로젝트 분석', Component: ProjectSummarySection },
  // 프로젝트 설정 탭 일단 숨김(hidden: true) — nav/content/외부네비에서 제외. 되돌리려면 hidden 제거.
  { id: 'setup',   icon: '⚙️', label: '프로젝트 설정', Component: ProjectSetupSection, hidden: true },
  { id: 'impact',  icon: '🔍', label: '변경 영향 평가', Component: ImpactGuideSection },
  { id: 'srssds',  icon: '📋', label: '요구사항 커버리지', Component: SrsSdsSection },
  // 생성 6종(문서/리포트/SwUT/SwIT/SwSA/통합결과)을 단일 탭으로 통합 — 내부 옵션 세그먼트로 전환.
  { id: 'docgen',  icon: '📝', label: '문서 생성',     Component: DocGenHubSection },
  // AI 어시스턴트는 성격이 다른 대화형 도구 — 좌측 nav에서 구분선으로 앞 5개(결과/분석/생성)와 분리.
  { id: 'ai',      icon: '🤖', label: 'AI 어시스턴트', Component: AiAssistSection, dividerBefore: true },
];

// 통합 전 개별 탭 id — 외부 네비게이션 호환용. docgen 허브로 라우팅 후 서브 선택.
const DOCGEN_SUB_IDS = new Set(['docgen', 'reports', 'swut', 'swit', 'swsa', 'swreport']);

// 각 허브의 **첫 서브** — 섹션 라벨과 사실상 같은 뜻이라 breadcrumb 에서 생략한다
// (매번 "문서 생성 › 문서 생성", "프로젝트 분석 › 개요" 가 되면 소음이다).
const FIRST_SUB_IDS = new Set(['docgen', 'overview']);

export default function Detail() {
  const { selectedJob, analysisResult, setSelectedJob, setAnalysisResult } = useJob();
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const [activeSection, setActiveSection] = useState('build');
  // 브레드크럼 프로젝트 전환용 — Jenkins job 목록(선택기 옵션) + 전환 진행 상태.
  const [jobs, setJobs] = useState([]);
  const [switching, setSwitching] = useState(false);
  // 서브탭을 가진 섹션(문서 생성 허브 · 프로젝트 분석)의 활성 서브 — breadcrumb 표기용.
  // ⚠ **섹션별 맵**이지 단일 값이 아니다. 단일 값이면 ①다른 섹션의 라벨이 새거나
  //   ②벗어날 때 지워서 복귀 시 라벨을 잃는다 — keep-alive 라 그 섹션이 언마운트되지 않아
  //   자식의 `useEffect([sub, onSubChange])` 가 재발화하지 않기 때문이다(사용자는 소스코드
  //   탭에 있는데 breadcrumb 만 비어 보인다). 맵 + 렌더 시 activeSection 조회로 둘 다 해결.
  //   job 전환 시 리셋은 불필요 — 섹션 key 에 jobKey 가 있어 remount 되며 즉시 재보고한다.
  const [sectionSubs, setSectionSubs] = useState({});   // {[sectionId]: {id, label}}
  // ⚠ 섹션별 콜백을 **한 번만** 만든다. 매 렌더 새 함수를 넘기면 자식의 위 effect 가 매 렌더
  //   발화하고, 그 안의 setState 가 부모를 다시 렌더시켜 무한 루프가 된다.
  //   같은 값 재설정도 막는다 — 새 객체를 만들면 그 자체로 렌더를 한 번 더 부른다.
  const subHandlers = useMemo(() => Object.fromEntries(SECTIONS.map((s) => [s.id,
    (id, label) => setSectionSubs((prev) => (
      prev[s.id]?.id === id ? prev : { ...prev, [s.id]: { id, label } }
    )),
  ])), []);
  // 외부 라우팅이 지정한 초기 서브(1회 소비). {section, sub}
  const [pendingSub, setPendingSub] = useState(null);
  // keep-alive: 한 번 방문한 탭은 마운트를 유지(display:none)해, 탭을 바꿔도 오래 걸려 얻은
  // 결과(VectorCAST 커버리지·영향 가이드 등 컴포넌트 로컬 상태)가 언마운트로 사라지지 않게 한다.
  const [visited, setVisited] = useState(() => new Set(['build']));
  const jobKey = selectedJob?.url || selectedJob?.name || '';

  // 활성 탭을 방문 기록에 누적 — 이후 숨겨져도 마운트 유지.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 활성 탭을 방문 기록에 누적 — keep-alive 를 위한 파생 집합 갱신
    setVisited((v) => (v.has(activeSection) ? v : new Set(v).add(activeSection)));
  }, [activeSection]);

  // activeSection 최신값을 ref로 추적 — jobKey 변경 effect가 stale closure 없이 현재 탭을 읽도록.
  const activeSectionRef = useRef(activeSection);
  // eslint-disable-next-line react-hooks/refs -- activeSection 최신값 ref 추적 — effect 로 옮기면 jobKey 변경과 동시 발생 시 순서가 갈린다
  activeSectionRef.current = activeSection;

  // job 변경 시 keep-alive 초기화 — 이전 job의 stale 상태/숨은 섹션 재요청 방지(key도 jobKey 포함).
  // activeSection은 ref로 읽어 deps 불필요(매 탭 전환마다 리셋되면 keep-alive 무의미하므로 jobKey만 구독).
  useEffect(() => {
    setVisited(new Set([activeSectionRef.current]));
  }, [jobKey]);

  // Allow external section navigation (from Dashboard)
  useEffect(() => {
    // (section, sub?) — sub 를 주면 그 섹션의 서브탭까지 열어 착지시킨다.
    // 서브탭이 생긴 뒤로 섹션만 지정하면 항상 첫 서브(개요/문서 생성)에 떨어져,
    // "아키텍처를 보라"는 링크가 사용자를 다시 헤매게 만든다.
    window.__detailSection = (section, sub) => {
      // 통합 전 개별 생성 탭 id가 들어오면 docgen 허브로 라우팅 + initialSub prop으로 서브 선택.
      if (DOCGEN_SUB_IDS.has(section)) {
        setActiveSection('docgen');
        setPendingSub({ section: 'docgen', sub: section });
        return;
      }
      if (SECTIONS.some(s => s.id === section && !s.hidden)) {
        setActiveSection(section);
        if (sub) setPendingSub({ section, sub });
      }
    };
    return () => { delete window.__detailSection; };
  }, []);

  // 다른 섹션의 라벨이 새는 건 **렌더 시 activeSection 으로 조회**해서 막는다 —
  // 벗어날 때 지우면 복귀 시(keep-alive라 재보고가 없다) 라벨을 잃는다.

  // initialSub는 허브가 1회 소비 → 즉시 초기화(remount마다 재강제 방지).
  useEffect(() => {
    if (pendingSub != null) setPendingSub(null);
  }, [pendingSub]);

  // 프로젝트(job) 목록 로드 — Jenkins 자격정보가 있을 때만. 없으면 선택기 없이 이름만 표시.
  useEffect(() => {
    if (!cfg?.baseUrl || !cfg?.username || !cfg?.token) return;
    if (jobs.length > 0) return;
    let cancelled = false;
    (async () => {
      try {
        const data = await post('/api/jenkins/jobs', {
          base_url: cfg.baseUrl,
          username: cfg.username,
          api_token: cfg.token,
          recursive: true,
          max_depth: 2,
          verify_tls: cfg.verifyTls,
        });
        if (!cancelled) setJobs(Array.isArray(data) ? data : (data.jobs ?? []));
      } catch { /* creds/네트워크 문제 — 선택기 대신 static 이름 폴백 */ }
    })();
    return () => { cancelled = true; };
  }, [cfg, jobs.length]);

  // 브레드크럼 프로젝트 전환 — 캐시된 결과를 Jenkins 재sync 없이 로드(Dashboard 오프라인 보기와 동일 경로).
  const switchProject = useCallback(async (rawUrl) => {
    const jobUrl = String(rawUrl || '').replace(/\/+$/, '') + '/';
    const curUrl = String(selectedJob?.url || '').replace(/\/+$/, '') + '/';
    if (!rawUrl || jobUrl === curUrl) return;
    const name = jobUrl.split('/').filter(Boolean).pop();
    setSwitching(true);
    setSelectedJob({ name, url: jobUrl });
    try {
      toast('info', `'${name}' 캐시 로드 중...`);
      const result = await loadProjectFromCache(jobUrl, cfg);
      setAnalysisResult(result);
      toast('success', `'${name}' 로드 완료 — 빌드 #${result.reportData?.build_number ?? '?'}`);
    } catch (e) {
      toast('error', `프로젝트 로드 실패: ${e.message} — 이 Job의 캐시가 없을 수 있습니다.`);
    } finally {
      setSwitching(false);
    }
  }, [selectedJob, cfg, toast, setSelectedJob, setAnalysisResult]);

  // 선택기 옵션 — 현재 선택된 job이 목록에 없으면 앞에 끼워 넣어 항상 표시.
  const projectOptions = useMemo(() => {
    const norm = (u) => String(u || '').replace(/\/+$/, '') + '/';
    const opts = jobs
      .map(j => ({ url: norm(j.url), name: j.name || j.fullName || j.url }))
      .filter(o => o.url && o.url !== '/');
    const curUrl = norm(selectedJob?.url);
    if (curUrl && curUrl !== '/' && !opts.some(o => o.url === curUrl)) {
      opts.unshift({ url: curUrl, name: selectedJob?.name || curUrl });
    }
    return opts;
  }, [jobs, selectedJob]);

  if (!selectedJob) {
    return (
      <div className="empty-state">
        <div className="empty-icon">📂</div>
        <div className="empty-title">프로젝트를 선택하세요</div>
        {/* 대시보드에서 job 미선택 상태로 들어와도 여기서 바로 프로젝트를 고를 수 있게 셀렉터 제공.
            Jenkins 자격정보가 있어 job 목록이 로드된 경우에만 노출(없으면 대시보드 안내로 폴백). */}
        {projectOptions.length > 0 && (
          <div className="row" style={{ marginTop: 4, justifyContent: 'center' }}>
            <select
              value=""
              onChange={e => { if (e.target.value) switchProject(e.target.value); }}
              disabled={switching}
              title="프로젝트 선택 (캐시된 결과 로드 — Jenkins 재동기화 없음)"
              style={{
                fontSize: 13, fontWeight: 600, color: 'var(--text)',
                background: 'var(--bg-elevated, var(--bg))', border: '1px solid var(--border)',
                borderRadius: 6, padding: '6px 10px', minWidth: 260, maxWidth: 420,
                cursor: switching ? 'wait' : 'pointer',
              }}
            >
              <option value="" disabled>프로젝트 선택…</option>
              {projectOptions.map(o => (
                <option key={o.url} value={o.url}>{o.name}</option>
              ))}
            </select>
            {switching && <span className="spinner" style={{ marginLeft: 4 }} />}
          </div>
        )}
        <div className="empty-desc">
          {projectOptions.length > 0
            ? '위에서 프로젝트를 고르면 캐시된 결과를 바로 불러옵니다.'
            : (<>대시보드에서 Jenkins Job을 선택하고 분석을 실행하면<br />여기서 프로젝트 결과를 확인할 수 있습니다.</>)}
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
        {projectOptions.length > 1 ? (
          <select
            value={String(selectedJob.url || '').replace(/\/+$/, '') + '/'}
            onChange={e => switchProject(e.target.value)}
            disabled={switching}
            title="프로젝트 전환 (캐시된 결과 로드 — Jenkins 재동기화 없음)"
            style={{
              fontSize: 12, fontWeight: 600, color: 'var(--text)',
              background: 'var(--bg-elevated, var(--bg))', border: '1px solid var(--border)',
              borderRadius: 4, padding: '2px 6px', maxWidth: 340,
              cursor: switching ? 'wait' : 'pointer',
            }}
          >
            {projectOptions.map(o => (
              <option key={o.url} value={o.url}>{o.name}</option>
            ))}
          </select>
        ) : (
          <span style={{ color: 'var(--text)', fontWeight: 600 }}>{selectedJob.name}</span>
        )}
        {switching && <span className="spinner" style={{ marginLeft: 4 }} />}
        <span>›</span>
        <span style={{ color: 'var(--accent)' }}>{current.label}</span>
        {/* 서브탭을 가진 섹션은 어느 서브에 있는지까지 breadcrumb 에 낸다. 첫 서브(docgen/overview)는
            섹션 라벨과 사실상 같은 뜻이라 생략 — 매번 "문서 생성 › 문서 생성"이 되면 소음이다. */}
        {sectionSubs[activeSection]
          && !FIRST_SUB_IDS.has(sectionSubs[activeSection].id) && (
          <>
            <span>›</span>
            <span style={{ color: 'var(--accent)' }}>{sectionSubs[activeSection].label}</span>
          </>
        )}
      </div>

      <div className="detail-layout">
        {/* Left accordion nav */}
        <nav className="accordion-nav">
          {SECTIONS.filter(s => !s.hidden).map(s => (
            <Fragment key={s.id}>
              {s.dividerBefore && (
                <div
                  className="accordion-divider"
                  role="separator"
                  aria-hidden="true"
                  style={{ height: 1, background: 'var(--border)', margin: '8px 12px' }}
                />
              )}
              <div className="accordion-item">
                <div
                  className={`accordion-header${activeSection === s.id ? ' active' : ''}`}
                  onClick={() => setActiveSection(s.id)}
                >
                  <span className="accordion-icon">{s.icon}</span>
                  <span className="accordion-label">{s.label}</span>
                </div>
              </div>
            </Fragment>
          ))}
        </nav>

        {/* Right content — 방문한 섹션은 모두 마운트 유지(비활성은 display:none)해 상태 보존(keep-alive). */}
        <div className="detail-content">
          {SECTIONS.filter(s => !s.hidden).map((s) => {
            const isActive = s.id === activeSection;
            // 아직 방문 안 한 탭은 마운트하지 않음(불필요한 초기 요청 회피). 방문 후엔 숨겨도 유지.
            if (!isActive && !visited.has(s.id)) return null;
            const C = s.Component;
            return (
              <div key={`${jobKey}::${s.id}`} style={isActive ? undefined : { display: 'none' }}>
                <C
                  job={selectedJob}
                  analysisResult={analysisResult}
                  onSubChange={subHandlers[s.id]}
                  initialSub={pendingSub?.section === s.id ? pendingSub.sub : undefined}
                />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
