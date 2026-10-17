import { useState, useEffect, useCallback, useRef } from 'react';
import DocGenStatusBoard from './DocGenStatusBoard.jsx';
import DocGenSection from './DocGenSection.jsx';
import ReportGenSection from './ReportGenSection.jsx';
import SwUTBuildSection from './SwUTBuildSection.jsx';
import SwITBuildSection from './SwITBuildSection.jsx';
import SwSABuildSection from './SwSABuildSection.jsx';
import SwReportSummarySection from './SwReportSummarySection.jsx';

/**
 * 문서 생성 허브 — 기존 6개 생성 섹션을 하나의 탭으로 통합하고 상단 옵션
 * 세그먼트로 전환한다. 기존 6개 컴포넌트는 수정 없이 그대로 자식으로 렌더.
 *
 * keep-alive lazy 마운트: 한 번 연 서브만 마운트하고 비활성은 display:none으로
 * 숨긴다. → (1) 처음 진입 시 6개 동시 마운트로 인한 on-mount fetch 폭주 방지,
 * (2) Sw* 섹션은 unmount 시 진행 중 빌드를 abort() 하므로, 조건부 unmount 대신
 * 숨김 유지하여 서브 전환 중에도 빌드/폼 상태가 끊기지 않게 한다.
 *
 * ## 첫 서브탭 = 생성 현황 보드 (2026-08-07)
 *
 * 예전엔 '문서 생성' 이 첫 탭이었는데, 그 화면이 답하지 못하는 질문이 있었다 —
 * **"이 프로젝트 문서가 지금 어디까지 갔고 게이트가 어떻게 나왔나"**. 생성 버튼과
 * 방금 누른 1건의 진행바만 있었고, 품질 결과는 다른 탭(그것도 두 벌)에 흩어져 있었다.
 * 보드를 앞에 두고 나머지를 세부로 민다.
 *
 * 보드는 생성을 **직접 실행**한다(이동이 아니라). 그러려면 `DocGenSection` 안에 있는
 * `generateDoc` 이 필요한데, 200줄짜리 로직을 끌어올리면 폼 상태(docPaths·cacheRoot·
 * linked_docs)까지 따라와야 한다. 대신 자식이 자기 함수를 ref 에 **등록**하고 보드가
 * 그걸 호출한다 — 로직 복제도 이동도 없다. 그래서 `docgen` 은 처음부터 마운트한다
 * (등록이 있어야 보드의 생성 버튼이 산다). Sw* 4개는 여전히 방문 시에만 마운트한다.
 *
 * props.onSubChange(id, label): 활성 서브가 바뀔 때 호출 — Detail breadcrumb 반영용.
 */
const SUBS = [
  { id: 'status', label: '생성 현황', Component: DocGenStatusBoard },
  { id: 'docgen', label: '문서 생성', Component: DocGenSection },
  { id: 'reports', label: '리포트', Component: ReportGenSection },
  { id: 'swut', label: 'SwUT', Component: SwUTBuildSection },
  { id: 'swit', label: 'SwIT', Component: SwITBuildSection },
  { id: 'swsa', label: 'SwSA', Component: SwSABuildSection },
  { id: 'swreport', label: '통합 결과', Component: SwReportSummarySection },
];

const VALID = new Set(SUBS.map(s => s.id));

export default function DocGenHubSection({ job, analysisResult, onSubChange, initialSub }) {
  const [sub, setSub] = useState('status');
  // 'docgen' 을 함께 마운트하는 이유는 위 주석 참조(보드의 생성 버튼이 자식의
  // generateDoc 등록에 의존한다). 무거운 on-mount fetch 는 Sw* 쪽이라 비용이 낮다.
  const [mounted, setMounted] = useState(() => new Set(['status', 'docgen']));

  // 자식(DocGenSection)이 올려보내는 생성 진행 상태 — 보드가 같은 폴링을 다시
  // 돌리지 않도록 공유한다(중복 요청 방지).
  const [genState, setGenState] = useState(null);

  const generateRef = useRef(null);
  const registerGenerate = useCallback((fn) => { generateRef.current = fn; }, []);

  const select = useCallback((id) => {
    if (!VALID.has(id)) return;
    setMounted(prev => {
      if (prev.has(id)) return prev;
      const next = new Set(prev);
      next.add(id);
      return next;
    });
    setSub(id);
  }, []);

  // 보드의 '생성' 버튼 → 자식이 등록한 실제 생성 함수. 아직 등록 전이면(이론상
  // 첫 렌더 직후) 조용히 실패하지 않고 생성 탭으로 보낸다.
  const runGenerate = useCallback((docType) => {
    const fn = generateRef.current;
    if (typeof fn === 'function') fn(docType);
    else select('docgen');
  }, [select]);

  // 외부(Detail)가 레거시 탭 id로 라우팅하면 initialSub prop으로 전달 → 해당 서브 선택.
  // prop 기반이라 전역 window 훅이 불필요(마운트/이미 마운트 양쪽 모두 effect로 반영).
  useEffect(() => {
    if (initialSub && VALID.has(initialSub)) select(initialSub);
  }, [initialSub, select]);

  // 활성 서브 변경을 부모(Detail)에 알림 — breadcrumb 표기 동기화.
  useEffect(() => {
    const active = SUBS.find(s => s.id === sub);
    if (active && onSubChange) onSubChange(active.id, active.label);
  }, [sub, onSubChange]);

  // WAI-ARIA tablist 키보드 네비게이션 (ArrowLeft/Right/Home/End + roving tabIndex).
  const onKeyDown = (e) => {
    const idx = SUBS.findIndex(s => s.id === sub);
    let nextIdx = null;
    if (e.key === 'ArrowRight') nextIdx = (idx + 1) % SUBS.length;
    else if (e.key === 'ArrowLeft') nextIdx = (idx - 1 + SUBS.length) % SUBS.length;
    else if (e.key === 'Home') nextIdx = 0;
    else if (e.key === 'End') nextIdx = SUBS.length - 1;
    if (nextIdx == null) return;
    e.preventDefault();
    const id = SUBS[nextIdx].id;
    // 모든 탭 버튼이 항상 렌더되므로 동기 포커스 가능.
    document.getElementById(`docgen-tab-${id}`)?.focus();
    select(id);
  };

  // 서브별 추가 props — 보드는 진행 상태를 받고, 생성 탭은 상태를 올려보낸다.
  const extraProps = (id) => {
    if (id === 'status') return { genState, onGenerate: runGenerate };
    if (id === 'docgen') return { onGenState: setGenState, onRegisterGenerate: registerGenerate };
    return {};
  };

  return (
    <div className="docgen-hub">
      <nav className="docgen-subnav" role="tablist" aria-label="문서 생성 종류" onKeyDown={onKeyDown}>
        {SUBS.map(s => (
          <button
            key={s.id}
            id={`docgen-tab-${s.id}`}
            role="tab"
            type="button"
            aria-selected={sub === s.id}
            aria-controls={`docgen-panel-${s.id}`}
            tabIndex={sub === s.id ? 0 : -1}
            className={`tab-item${sub === s.id ? ' active' : ''}`}
            onClick={() => select(s.id)}
          >
            {s.label}
          </button>
        ))}
      </nav>

      <div className="docgen-hub-body">
        {SUBS.map(s => {
          const { Component } = s;
          const active = sub === s.id;
          return (
            <div
              key={s.id}
              role="tabpanel"
              id={`docgen-panel-${s.id}`}
              aria-labelledby={`docgen-tab-${s.id}`}
              tabIndex={active ? 0 : -1}
              style={{ display: active ? 'block' : 'none' }}
            >
              {/* 패널 컨테이너는 항상 렌더 → 탭 버튼 aria-controls IDREF 유효(dangling 방지).
                  무거운 컴포넌트는 방문한 서브만 마운트(keep-alive: 이후 숨김 유지 → 빌드/폼 보존).
                  onNavigateSub: 첫 탭(문서 생성)의 'SwUT/SwIT/SwSA/통합' 바로가기 버튼이 해당
                  서브탭으로 전환하기 위한 콜백. 다른 서브는 이 prop을 무시한다. */}
              {mounted.has(s.id) && (
                <Component
                  job={job}
                  analysisResult={analysisResult}
                  onNavigateSub={select}
                  {...extraProps(s.id)}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
