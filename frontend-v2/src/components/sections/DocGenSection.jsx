import { useState, useCallback, useEffect, useRef } from 'react';
import { api, post, defaultCacheRoot, getUsername, authHeaders } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import { isAbortError } from '../../impactPoll.js';
import { pollProgress, pollStsProgress } from '../../docGenPoll.js';
import { persistDocPaths, useScmFallback } from '../../docGenHelpers.js';
import { loadDocPaths, loadDocGenCaps, useDocPathsSync } from '../../sharedInputs.js';

// 미리보기 서버 페이지네이션 한 페이지 행 수(백엔드 page_size 기본값과 일치).
const PREVIEW_PAGE_SIZE = 100;

const DOC_TYPES = [
  { key: 'uds', label: 'UDS', icon: '📘', desc: 'Unit Design Specification' },
  { key: 'sts', label: 'STS', icon: '📗', desc: 'Software Test Specification' },
  { key: 'suts', label: 'SUTS', icon: '📙', desc: 'Software Unit Test Specification' },
  { key: 'sits', label: 'SITS', icon: '📕', desc: 'Software Integration Test Specification' },
];

// 개별 서브탭을 가진 빌더 산출물 — 첫 탭(문서 생성)에서 UDS/STS/SUTS/SITS 생성 버튼
// 옆에 바로가기 버튼으로 노출한다. 클릭 시 onNavigateSub로 해당 서브탭으로 전환(빌드
// 설정 UI는 각 탭에 있으므로 즉시 생성이 아닌 이동). DocGenHubSection.SUBS의 id와 일치.
const BUILDER_TABS = [
  { id: 'swut', label: 'SwUT', icon: '🔧', desc: 'SW 단위시험 (SwUTCV/SUTR)' },
  { id: 'swit', label: 'SwIT', icon: '🔗', desc: 'SW 통합시험 (SwITCV/SITR)' },
  { id: 'swsa', label: 'SwSA', icon: '🔬', desc: 'SW 정적분석' },
  { id: 'swreport', label: '통합 결과', icon: '📊', desc: '전 레벨 통합 Summary' },
];

export default function DocGenSection({ job, analysisResult, onNavigateSub, onGenState, onRegisterGenerate }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;

  const [generating, setGenerating] = useState(null);
  const [genStage, setGenStage] = useState('');     // current stage text
  const [genProgress, setGenProgress] = useState(0); // 0-100
  const [genResult, setGenResult] = useState(null);  // {success, error, path}

  const docPaths = (() => {
    try { return JSON.parse(localStorage.getItem('devops_v2_doc_paths') || '{}'); } catch (_) { return {}; }
  })();

  const generateDoc = useCallback(async (docType) => {
    if (!job?.url) { toast('warning', '프로젝트를 먼저 선택하세요.'); return; }
    const label = DOC_TYPES.find(d => d.key === docType)?.label || docType.toUpperCase();
    setGenerating(docType);
    setGenStage(`${label} 생성 준비 중...`);
    setGenProgress(5);
    setGenResult(null);

    try {
      // Prefer the Dashboard-matched SCM entry (driven by pickScmForJob /
      // manual dropdown override). Falling back to scmList[0] would silently
      // generate docs against the wrong project's source_root and linked_docs.
      let scm = analysisResult?.matchedScm || analysisResult?.scmList?.[0];
      // Fallback: fetch from SCM API if not in analysisResult
      if (!scm?.source_root) {
        try {
          const scmData = await api('/api/scm/list');
          const items = scmData?.items || (Array.isArray(scmData) ? scmData : []);
          if (items.length > 0) scm = items[0];
        } catch (_) {}
      }
      const linkedDocs = scm?.linked_docs || {};

      const formData = new FormData();
      formData.append('job_url', job.url);
      formData.append('cache_root', cacheRoot);
      formData.append('build_selector', cfg.buildSelector || 'lastSuccessfulBuild');
      if (scm?.source_root) formData.append('source_root', scm.source_root);
      // 템플릿은 **문서마다 형식이 다르다**(UDS .docx / 시험 규격서 .xlsm).
      // 예전엔 설정의 공용 `template` 하나를 두 자리에 같이 보냈다 — 형식이 다르므로
      // 한쪽은 반드시 틀린다. 문서별 키를 먼저 보고 없을 때만 공용으로 폴백한다.
      const TPL_KEY = { uds: 'uds_template', sts: 'sts_template', suts: 'suts_template', sits: 'sits_template' };
      const tplKey = TPL_KEY[docType];
      const templatePath = (tplKey && (docPaths[tplKey] || linkedDocs[tplKey]))
        || docPaths.template || linkedDocs.template || '';
      if (templatePath) formData.append('template_path', templatePath);
      if (docType === 'uds' && templatePath) formData.append('uds_template_path', templatePath);
      // Pass linked doc paths
      const srsPath = docPaths.srs || linkedDocs.srs || '';
      const sdsPath = docPaths.sds || linkedDocs.sds || '';
      // Settings '입력 자료 설정' 경로(docPaths)를 SCM linked_docs보다 우선 폴백으로 사용.
      // (sts는 stp, sits는 hsis/stp/uds를 수용 — 백엔드 미수용 docType에선 무시됨)
      const hsisPath = docPaths.hsis || linkedDocs.hsis || '';
      const stpPath = docPaths.stp || linkedDocs.stp || '';
      const udsPath = docPaths.uds || linkedDocs.uds || '';
      // UDS uses req_paths; STS/SUTS use srs_path/sds_path
      if (docType === 'uds') {
        const reqPaths = [srsPath, sdsPath].filter(Boolean).join(',');
        if (reqPaths) formData.append('req_paths', reqPaths);
      } else {
        if (srsPath) formData.append('srs_path', srsPath);
        if (sdsPath) formData.append('sds_path', sdsPath);
      }
      if (hsisPath) formData.append('hsis_path', hsisPath);
      if (stpPath) formData.append('stp_path', stpPath);
      // 생성 상한 — **설정된 것만** 보낸다. 안 보내면 생성기 기본값이 쓰이고, 그게
      // 단일 출처다(여기서 숫자를 복제하면 생성기 상수와 갈라진다).
      // 실측 kjpds02_pv: 통합 흐름 145 라 기본 120 으로는 25개가 규격에서 빠진다.
      if (docType === 'sits') {
        const caps = loadDocGenCaps();
        if (caps.max_flows) formData.append('max_flows', String(caps.max_flows));
        if (caps.max_subcases) formData.append('max_subcases', String(caps.max_subcases));
      }
      if (udsPath && docType !== 'uds') formData.append('uds_path', udsPath);

      const user = getUsername();
      // SITS uses /api/local/ endpoint with urlencoded; others use /api/jenkins/ with FormData
      const apiPrefix = docType === 'sits' ? '/api/local' : '/api/jenkins';
      let fetchBody, fetchHeaders;
      if (docType === 'sits') {
        const params = new URLSearchParams();
        for (const [k, v] of formData.entries()) params.append(k, v);
        fetchBody = params.toString();
        fetchHeaders = { 'Content-Type': 'application/x-www-form-urlencoded' };
      } else {
        fetchBody = formData;
        fetchHeaders = {};
      }
      // auth 는 authHeaders()(Bearer + X-User) — X-User 만이면 1b6bb99(2026-08-04) 이후 401.
      Object.assign(fetchHeaders, authHeaders());
      const res = await fetch(`${apiPrefix}/${docType}/generate-async`, {
        method: 'POST',
        body: fetchBody,
        headers: fetchHeaders,
      });
      if (!res.ok) {
        const t = await res.text();
        throw new Error(t || `HTTP ${res.status}`);
      }
      const data = await res.json();
      if (!data?.job_id) throw new Error(`${label} job_id를 받지 못했습니다.`);

      setGenStage(`${label} 생성 진행 중...`);
      setGenProgress(10);

      // Stage-to-progress mapping
      const stageMap = {
        'start': 5, 'source_analysis': 15, '소스 코드 분석': 15,
        'requirements': 25, '요구사항': 25, '요구사항 문서 파싱': 25, '요구사항 정리': 30,
        'payload': 40, 'UDS 페이로드': 40, 'UDS 페이로드 생성': 45,
        'docx': 55, 'docx_generation': 55, 'DOCX 생성': 60,
        'quality': 80, 'validation': 85, 'report': 90,
        'done': 100, 'completed': 100, 'success': 100,
      };
      const resolveProgress = (msg) => {
        const m = msg?.match(/(\d+)%/);
        if (m) return Number(m[1]);
        for (const [key, pct] of Object.entries(stageMap)) {
          if (msg?.toLowerCase().includes(key.toLowerCase())) return pct;
        }
        return null;
      };

      let progress;
      const onProgress = (msg) => {
        if (!msg) return;
        // Update stage text (only last message, no scrolling log)
        setGenStage(msg.replace(/\n/g, ' ').trim());
        const pct = resolveProgress(msg);
        if (pct != null) setGenProgress(prev => Math.max(prev, pct));
      };

      // signal 은 넘기지 않는다 — 이 화면엔 취소 UI 가 없어 배선할 컨트롤러가 없다.
      // (죽은 `signal: null` 하드코딩을 남겨두면 "취소가 지원되는 것처럼" 읽힌다.)
      if (docType === 'uds') {
        progress = await pollProgress(job.url, cfg.buildSelector || 'lastSuccessfulBuild', data.job_id, 'uds', {
          onMsg: onProgress,
        });
      } else {
        const pollPrefix = docType === 'sits' ? '/api/local' : '/api/jenkins';
        progress = await pollStsProgress(data.job_id, docType, job.url, {
          onMsg: onProgress, prefix: pollPrefix,
        });
      }

      if (progress?.error) throw new Error(progress.error);
      // 방어선(현재 도달 불가). 두 폴러 모두 `data?.progress || {}` 를 돌려주므로 falsy 가
      // 나올 수 없다 — 하지만 abort 가 null 을 돌려주던 시절엔 정확히 이 자리가 뚫려
      // 취소를 '생성 완료'로 위장했다. 폴러의 반환 계약이 다시 바뀌어도 성공 분기로는
      // 못 새도록 남겨 둔다. (테스트로 도달시킬 수 없으므로 테스트는 두지 않았다.)
      if (!progress) throw new Error('진행 상태를 받지 못했습니다.');

      setGenProgress(100);
      setGenStage(`${label} 생성 완료`);
      setGenResult({ success: true, path: progress?.output_path || progress?.xlsm_path || '' });
      toast('success', `${label} 생성 완료`);
    } catch (e) {
      // 취소는 사용자 오류가 아니다 — 실패로 보고하지 않는다. 다만 조용히 return 만 하면
      // 진행바가 중간값(예: 55% "DOCX 생성")에 고착돼 "아직 도는 중"처럼 보인다.
      if (isAbortError(e)) {
        setGenStage(`${label} 생성을 중단했습니다.`);
        setGenProgress(0);
        return;
      }
      toast('error', `${label} 생성 실패: ${e.message}`);
      setGenStage(`오류: ${e.message}`);
      setGenResult({ success: false, error: e.message });
    } finally {
      setGenerating(null);
    }
  }, [job, cfg, cacheRoot, docPaths, toast, analysisResult]);

  // 생성 현황 보드('생성 현황' 서브탭)가 같은 폴링을 다시 돌리지 않도록 진행 상태를
  // 부모(DocGenHubSection)로 올려보낸다. `result` 는 완료/실패 시에만 새 객체가 되므로
  // 보드가 그 identity 변화를 이력 재조회 트리거로 쓴다.
  useEffect(() => {
    if (!onGenState) return;
    onGenState({ docType: generating, stage: genStage, progress: genProgress, result: genResult });
  }, [generating, genStage, genProgress, genResult, onGenState]);

  // 보드의 '생성' 버튼이 호출할 실제 함수를 등록한다. `generateDoc` 은 이 컴포넌트의
  // 폼 상태(docPaths·cacheRoot·linked_docs)에 묶여 있어 끌어올리면 그게 전부 따라온다 —
  // 등록으로 두면 로직 복제도 이동도 없다.
  useEffect(() => {
    if (!onRegisterGenerate) return;
    onRegisterGenerate(generateDoc);
  }, [onRegisterGenerate, generateDoc]);

  const [scm] = useScmFallback(analysisResult);
  const linkedDocs = scm?.linked_docs || {};
  // Settings 에서 저장한 경로를 **같은 세션에서** 반영한다. 이 섹션도 keep-alive 라
  // 재마운트가 없어, 구독이 없으면 mount 시 스냅샷이 새로고침 전까지 고정된다.
  const [localDocPaths, setLocalDocPaths] = useState(loadDocPaths);
  useDocPathsSync(setLocalDocPaths);

  // path 정규화 — 슬래시 방향 통일
  const _normPath = (p) => (p || '').replace(/\\/g, '/').replace(/\/+$/, '');

  // cloudium 모드일 때 선택한 파일의 부모를 allowed_prefixes에 자동 추가
  const ensureCloudiumPrefix = async (filePath) => {
    try {
      const cfg = await api('/api/file-mode');
      if (cfg.mode !== 'cloudium') return;
      const lastSlash = Math.max(filePath.lastIndexOf('/'), filePath.lastIndexOf('\\'));
      const parent = lastSlash >= 0 ? filePath.slice(0, lastSlash) : filePath;
      const parentNorm = _normPath(parent);
      const existing = Array.isArray(cfg.allowed_prefixes) ? cfg.allowed_prefixes : [];
      if (existing.map(_normPath).some(p => parentNorm === p || parentNorm.startsWith(p + '/'))) return;
      await post('/api/file-mode', {
        mode: 'cloudium',
        allowed_prefixes: [...existing, parent].join(', '),
        gate_process: cfg.gate_process || 'excel_rename_gui_v2.exe',
      });
      toast('info', `클라우디움 허용 디렉토리에 추가: ${parent}`);
    } catch (e) {
      console.warn('allowed_prefixes 자동 갱신 실패:', e.message);
    }
  };

  // 다이얼로그로 doc path 선택 — worker IPC(cloudium) 또는 backend tkinter(local)
  const pickDocPath = async (key, label) => {
    try {
      const picked = await post('/api/file-mode/browse-file', {
        title: `${label} 문서 선택`,
        kind: 'file',
      });
      if (!picked || !picked.ok || !picked.path) {
        if (picked?.error === 'cancelled') return;
        toast('error', `다이얼로그 실패: ${picked?.error || picked?.detail || 'unknown'}`);
        return;
      }
      const next = { ...localDocPaths, [key]: picked.path };
      setLocalDocPaths(next);
      const saved = persistDocPaths(next, toast);
      await ensureCloudiumPrefix(picked.path);
      if (saved) toast('success', `${label} 경로: ${picked.path.split(/[\\/]/).pop()}`);
    } catch (e) {
      toast('error', `다이얼로그 실패: ${e.message}`);
    }
  };

  // 임시 변경 초기화 (linked_docs로 폴백)
  const clearDocPath = (key, label) => {
    const next = { ...localDocPaths };
    delete next[key];
    setLocalDocPaths(next);
    if (persistDocPaths(next, toast)) {
      toast('info', `${label} 임시 경로 초기화 → SCM 등록 경로 사용`);
    }
  };

  // Merge input docs: SCM linked_docs + localStorage
  const inputDocs = [
    { key: 'srs', label: 'SRS', desc: '소프트웨어 요구사항 사양서', path: localDocPaths.srs || linkedDocs.srs || '' },
    { key: 'sds', label: 'SDS', desc: '소프트웨어 설계 사양서', path: localDocPaths.sds || linkedDocs.sds || '' },
    { key: 'hsis', label: 'HSIS', desc: 'HW/SW 인터페이스 사양서', path: linkedDocs.hsis || '' },
    { key: 'stp', label: 'STP', desc: '소프트웨어 시험 계획서', path: linkedDocs.stp || '' },
  ];
  const outputDocs = [
    { key: 'uds', label: 'UDS', desc: 'Unit Design Specification', path: linkedDocs.uds || '' },
    { key: 'sts', label: 'STS', desc: 'Software Test Specification', path: linkedDocs.sts || '' },
    { key: 'suts', label: 'SUTS', desc: 'SW Unit Test Specification', path: linkedDocs.suts || '' },
    { key: 'sits', label: 'SITS', desc: 'SW Integration Test Spec', path: linkedDocs.sits || '' },
  ];

  const [docPreview, setDocPreview] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewSheet, setPreviewSheet] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  // 미리보기 요청 시퀀스 — 동시/연속 요청 시 늦게 도착한 stale 응답이 최신 화면을
  // 덮어쓰는 것 방지(예: 시트전환 fetch 중 다른 문서 클릭 → wrong-document 표시).
  const previewReqRef = useRef(0);

  const allDocs = [
    { key: 'srs', label: 'SRS', type: 'input', path: localDocPaths.srs || linkedDocs.srs || '' },
    { key: 'sds', label: 'SDS', type: 'input', path: localDocPaths.sds || linkedDocs.sds || '' },
    { key: 'hsis', label: 'HSIS', type: 'input', path: localDocPaths.hsis || linkedDocs.hsis || '' },
    { key: 'stp', label: 'STP', type: 'input', path: localDocPaths.stp || linkedDocs.stp || '' },
    { key: 'uds', label: 'UDS', type: 'output', path: localDocPaths.uds || linkedDocs.uds || '' },
    { key: 'sts', label: 'STS', type: 'output', path: localDocPaths.sts || linkedDocs.sts || '' },
    { key: 'suts', label: 'SUTS', type: 'output', path: localDocPaths.suts || linkedDocs.suts || '' },
    { key: 'sits', label: 'SITS', type: 'output', path: localDocPaths.sits || linkedDocs.sits || '' },
  ];

  // page/sheet 변경 시 서버에서 해당 윈도우를 재요청(refetch). 백엔드가 page_size
  // 만큼만 윈도우 read하므로 클라이언트 슬라이스로는 다음 페이지 데이터를 가질 수 없다.
  // resetSheet=true면 새 문서(시트 0부터), false면 같은 문서의 페이지/시트 이동.
  // (라벨은 모든 입력/산출물에서 key 대문자와 동일 — SRS/SDS/HSIS/UDS/STS/SUTS/SITS)
  const loadDocPreview = useCallback(async (docKey, path, page = 0, resetSheet = true) => {
    if (!path) { toast('warning', '문서 경로가 등록되지 않았습니다.'); return; }
    const reqId = ++previewReqRef.current;   // 이 요청의 시퀀스 번호
    setPreviewLoading(true);
    if (resetSheet) setPreviewSheet(0);
    try {
      const filename = path.split(/[\\/]/).pop();
      // Use generic Excel preview API for all document types (server-side pagination)
      const data = await post('/api/preview-excel', { path, page, page_size: PREVIEW_PAGE_SIZE });
      if (reqId !== previewReqRef.current) return;   // 더 새 요청이 시작됨 → stale 응답 폐기
      setDocPreview({ key: docKey, label: docKey.toUpperCase(), filename, data, _path: path, page });
    } catch (e) {
      if (reqId !== previewReqRef.current) return;   // stale 에러 무시
      toast('error', `문서 미리보기 실패: ${e.message}`);
    } finally {
      if (reqId === previewReqRef.current) setPreviewLoading(false);
    }
  }, [toast]);

  // 페이지 이동(같은 시트 유지) — 서버 윈도우 재요청.
  const gotoPreviewPage = useCallback((newPage) => {
    if (!docPreview || newPage < 0) return;
    loadDocPreview(docPreview.key, docPreview._path, newPage, false);
  }, [docPreview, loadDocPreview]);

  // 시트 전환 — 해당 시트를 page 0부터 보여주기 위해 page 0 재요청 + previewSheet 갱신.
  const switchPreviewSheet = useCallback((sheetIdx) => {
    if (!docPreview) return;
    setPreviewSheet(sheetIdx);
    loadDocPreview(docPreview.key, docPreview._path, 0, false);
  }, [docPreview, loadDocPreview]);

  return (
    <div>
      {/* Document list - clickable for preview */}
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-header">
          <span className="panel-title">문서 현황</span>
        </div>
        <table className="impact-table" style={{ fontSize: 11 }}>
          <thead>
            <tr><th style={{ width: 55 }}>문서</th><th>파일명</th><th style={{ width: 60 }}>상태</th><th style={{ width: 130 }}>경로</th></tr>
          </thead>
          <tbody>
            {allDocs.map(d => {
              const isOverride = !!localDocPaths[d.key];
              return (
              <tr key={d.key} style={{ cursor: d.path ? 'pointer' : 'default' }}
                  onClick={() => d.path && loadDocPreview(d.key, d.path)}>
                <td><span className={`pill ${d.type === 'input' ? 'pill-info' : 'pill-purple'}`} style={{ fontSize: 9 }}>{d.label}</span></td>
                <td style={{ fontFamily: 'monospace', fontSize: 10 }} title={d.path}>
                  {d.path ? d.path.split(/[\\/]/).pop() : <span className="text-muted">미등록</span>}
                  {isOverride && <span className="pill pill-warning" style={{ fontSize: 8, marginLeft: 4 }}>임시</span>}
                </td>
                <td style={{ textAlign: 'center' }}>
                  {d.path ? <span className="pill pill-success" style={{ fontSize: 9 }}>등록됨</span> : <span className="pill pill-neutral" style={{ fontSize: 9 }}>-</span>}
                </td>
                <td style={{ textAlign: 'center', display: 'flex', gap: 2, justifyContent: 'center' }} onClick={e => e.stopPropagation()}>
                  {d.path && <button className="btn-sm" style={{ fontSize: 9, padding: '1px 6px' }}
                    onClick={() => loadDocPreview(d.key, d.path)}
                    disabled={previewLoading}>보기</button>}
                  <button type="button" className="btn-sm" style={{ fontSize: 9, padding: '1px 6px' }}
                    title="다이얼로그로 파일 선택 (cloudium 모드면 worker IPC)"
                    onClick={() => pickDocPath(d.key, d.label)}>📂</button>
                  {isOverride && <button type="button" className="btn-sm" style={{ fontSize: 9, padding: '1px 6px' }}
                    title="임시 경로 초기화 (SCM 등록 경로로 폴백)"
                    onClick={() => clearDocPath(d.key, d.label)}>↺</button>}
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Document preview */}
      {docPreview && <DocPreviewPanel
        docPreview={docPreview}
        previewSheet={previewSheet}
        onSwitchSheet={switchPreviewSheet}
        onGotoPage={gotoPreviewPage}
        loading={previewLoading}
        fullscreen={fullscreen}
        setFullscreen={setFullscreen}
        onClose={() => { setDocPreview(null); setFullscreen(false); }}
      />}

      {/* Generation controls */}
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">문서 생성</span>
        </div>

        <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
          {DOC_TYPES.map(dt => (
            <button
              key={dt.key}
              className="btn-primary btn-sm"
              onClick={() => generateDoc(dt.key)}
              disabled={!!generating}
              style={{ minWidth: 120 }}
            >
              {generating === dt.key
                ? <><span className="spinner" style={{ display: 'inline-block', marginRight: 4 }} />생성 중...</>
                : `${dt.icon} ${dt.label} 생성`
              }
            </button>
          ))}
          {/* 개별 탭을 가진 빌더 산출물 바로가기 — UDS/STS/SUTS/SITS 버튼 옆에 배치.
              클릭 시 해당 서브탭으로 이동(빌드 설정 UI가 각 탭에 있음). */}
          {onNavigateSub && (
            <>
              <span aria-hidden="true" style={{ alignSelf: 'stretch', width: 1, background: 'var(--border)', margin: '0 2px' }} />
              {BUILDER_TABS.map(bt => (
                <button
                  key={bt.id}
                  type="button"
                  className="btn-secondary btn-sm"
                  onClick={() => onNavigateSub(bt.id)}
                  title={`${bt.desc} — '${bt.label}' 탭으로 이동`}
                  style={{ minWidth: 110 }}
                >
                  {bt.icon} {bt.label} →
                </button>
              ))}
            </>
          )}
        </div>

        {/* Progress bar + status */}
        {(generating || genResult) && (
          <div style={{ marginBottom: 12, padding: 12, background: 'var(--bg)', borderRadius: 8, border: '1px solid var(--border)' }}>
            {/* Progress bar */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
              <div style={{ flex: 1, height: 8, background: 'var(--border)', borderRadius: 4, overflow: 'hidden' }}>
                <div style={{
                  height: '100%', borderRadius: 4, transition: 'width 0.5s ease',
                  width: `${genProgress}%`,
                  background: genResult?.success ? 'var(--color-success)' :
                    genResult?.error ? 'var(--color-danger)' : 'var(--accent)',
                }} />
              </div>
              <span style={{ fontSize: 12, fontWeight: 700, minWidth: 40, textAlign: 'right' }}>
                {genProgress}%
              </span>
            </div>

            {/* Status text */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {generating && <span className="spinner" style={{ width: 14, height: 14 }} />}
              {genResult?.success && <span style={{ color: 'var(--color-success)', fontSize: 16 }}>✓</span>}
              {genResult?.error && <span style={{ color: 'var(--color-danger)', fontSize: 16 }}>✕</span>}
              <span style={{ fontSize: 12, color: genResult?.error ? 'var(--color-danger)' : 'var(--text)' }}>
                {genStage}
              </span>
            </div>

            {/* Result path */}
            {genResult?.success && genResult.path && (
              <div style={{ marginTop: 6, fontSize: 10, color: 'var(--text-muted)', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                {genResult.path}
              </div>
            )}
          </div>
        )}
      </div>

      {/* VectorCAST Export */}
      <VectorCastExport job={job} analysisResult={analysisResult} cfg={cfg} cacheRoot={cacheRoot} />

    </div>
  );
}

/* ── VectorCAST 패키지 관리 (등록 → 목록 → 다운로드) ── */
function VectorCastExport({ job, analysisResult, cfg, cacheRoot }) {
  const toast = useToast();
  const [registering, setRegistering] = useState(null);
  const [packages, setPackages] = useState([]);
  const [loading, setLoading] = useState(false);
  // ⚠ 조회 실패를 빈 목록으로 접지 않는다. 예전엔 `catch { setPackages([]) }` 라
  //   403 이 "등록된 패키지가 없습니다"로 위장했고, 그래서 아무도 몰랐다.
  const [loadError, setLoadError] = useState('');
  const [scannedRoots, setScannedRoots] = useState([]);
  const [scm] = useScmFallback(analysisResult);

  // 패키지 목록 조회
  // ⚠ `report_dir` 로 cacheRoot 를 보내면 안 된다 — 백엔드는 그 인자를 `reports/` 안으로
  //   confine 하므로 캐시 경로는 403 이었다. 등록(쓰기)이 두 갈래(로컬=reports/,
  //   jenkins=cacheRoot/exports/)라 **양쪽 다** 봐야 하며, 그건 `cache_root` 로 넘긴다.
  const listQuery = useCallback(
    (extra = {}) => new URLSearchParams({ cache_root: cacheRoot || '', ...extra }).toString(),
    [cacheRoot],
  );

  const loadPackages = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api(`/api/local/vectorcast/list?${listQuery()}`);
      setPackages(data?.packages || []);
      setScannedRoots(data?.scanned_roots || []);
      // 백엔드가 일부 루트를 제외했으면 그 사유를 그대로 올린다(부분 성공도 성공이 아니다).
      setLoadError((data?.warnings || []).join(' · '));
    } catch (e) {
      setPackages([]);
      setScannedRoots([]);
      setLoadError(e?.message || '목록을 불러오지 못했습니다');
    } finally {
      setLoading(false);
    }
  }, [listQuery]);

  // 마운트 시 + 등록 후 목록 로드
  useEffect(() => { loadPackages(); }, [loadPackages]);

  // VectorCAST 패키지 등록 (생성)
  const registerVcast = useCallback(async (docType) => {
    setRegistering(docType);
    try {
      const formData = new FormData();
      formData.append('job_url', job?.url || '');
      formData.append('cache_root', cacheRoot);
      formData.append('build_selector', cfg.buildSelector || 'lastSuccessfulBuild');
      if (scm?.source_root) formData.append('source_root', scm.source_root);
      try {
        const qs = `job_url=${encodeURIComponent(job?.url || '')}&cache_root=${encodeURIComponent(cacheRoot)}`;
        const listData = await api(`/api/jenkins/${docType}/list?${qs}`);
        const items = listData?.items || [];
        if (items.length > 0) formData.append('filename', items[0].filename || items[0].name || '');
      } catch (_) {}
      const endpoint = docType === 'sits' ? '/api/local/sits/export-vectorcast' : `/api/jenkins/${docType}/export-vectorcast`;
      const res = await fetch(endpoint, { method: 'POST', body: formData, headers: authHeaders() });
      if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);
      const data = await res.json();
      const summary = data?.manifest?.summary || {};
      toast('success', `VectorCAST 패키지 등록 완료: ${data.package_name || docType} (${summary.unit_count || 0} units, ${summary.test_case_count || 0} TCs)`);
      loadPackages(); // 목록 새로고침
    } catch (e) {
      toast('error', `VectorCAST 등록 실패: ${e.message}`);
    } finally {
      setRegistering(null);
    }
  }, [job, cfg, cacheRoot, scm, toast, loadPackages]);

  // 패키지 삭제 — 백엔드가 `cache_root` 로 허용 루트를 재구성해 경로를 확정한다.
  const deletePackage = useCallback(async (pkgPath, pkgName) => {
    if (!window.confirm(`"${pkgName}" 패키지를 삭제하시겠습니까?`)) return;
    try {
      await api(`/api/local/vectorcast/delete?${listQuery({ package_path: pkgPath })}`, { method: 'DELETE' });
      toast('success', `${pkgName} 삭제됨`);
      loadPackages();
    } catch (e) {
      toast('error', `삭제 실패: ${e.message}`);
    }
  }, [toast, loadPackages, listQuery]);

  // 패키지 다운로드.
  // ⚠ 예전엔 `<a href download>` 였다 — anchor 는 `Authorization` 헤더를 실을 수 없어
  //   `UserContextMiddleware` 에서 **401** 로 끊겼다(`/api/local/*` 은 인증 우회 목록에
  //   없다). 게다가 401 응답이 그대로 파일로 저장돼 사용자에겐 "받아지긴 했는데
  //   열리지 않는 파일"로 보였다. fetch → blob 으로 바꿔 헤더를 붙이고 실패를 드러낸다.
  const downloadPackage = useCallback(async (pkgPath, pkgName) => {
    try {
      const res = await fetch(
        `/api/local/vectorcast/download?${listQuery({ package_path: pkgPath })}`,
        { headers: authHeaders() },
      );
      if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${pkgName}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast('error', `다운로드 실패: ${e.message}`);
    }
  }, [toast, listQuery]);

  return (
    <div className="panel" style={{ marginTop: 12 }}>
      <div className="panel-header">
        <span className="panel-title">VectorCAST 패키지 관리</span>
        <button className="btn-ghost btn-xs" onClick={loadPackages} disabled={loading} title="새로고침">🔄</button>
      </div>

      {/* 등록 버튼 */}
      <div className="text-sm text-muted" style={{ marginBottom: 8 }}>
        SUTS/SITS 문서로 VectorCAST .tst/.env 패키지를 등록합니다.
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <button className="btn-primary btn-sm" onClick={() => registerVcast('suts')} disabled={!!registering}>
          {registering === 'suts' ? '등록 중...' : '📙 SUTS 패키지 등록'}
        </button>
        <button className="btn-primary btn-sm" onClick={() => registerVcast('sits')} disabled={!!registering}>
          {registering === 'sits' ? '등록 중...' : '📕 SITS 패키지 등록'}
        </button>
      </div>

      {/* 등록된 패키지 목록 */}
      {packages.length > 0 && (
        <div style={{ border: '1px solid var(--border)', borderRadius: 6, overflow: 'hidden' }}>
          <table style={{ width: '100%', fontSize: 12, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ background: 'var(--bg-secondary)', textAlign: 'left' }}>
                <th style={{ padding: '6px 8px' }}>패키지</th>
                <th style={{ padding: '6px 8px' }}>유형</th>
                <th style={{ padding: '6px 8px', textAlign: 'center' }}>Units</th>
                <th style={{ padding: '6px 8px', textAlign: 'center' }}>TCs</th>
                <th style={{ padding: '6px 8px', textAlign: 'center' }}>파일</th>
                <th style={{ padding: '6px 8px' }}>등록일</th>
                <th style={{ padding: '6px 8px', textAlign: 'center' }}>액션</th>
              </tr>
            </thead>
            <tbody>
              {/* ⚠ key 는 path — 루트가 둘이라 이름이 같은 패키지가 공존할 수 있다
                  (name 을 key 로 쓰면 React 가 한쪽을 통째로 삼킨다). */}
              {packages.map((pkg) => (
                <tr key={pkg.path} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 8px', fontWeight: 600 }}>
                    {pkg.name}
                    {pkg.source && pkg.source !== 'reports' && (
                      <span className="text-muted" style={{ fontSize: 10, marginLeft: 6 }}>
                        {pkg.source === 'jenkins_cache_legacy' ? '(공유 캐시)' : '(빌드 캐시)'}
                      </span>
                    )}
                    {pkg.error && (
                      <div style={{ fontSize: 10, color: 'var(--danger)' }}>읽기 실패: {pkg.error}</div>
                    )}
                  </td>
                  <td style={{ padding: '6px 8px' }}>
                    <span className={`pill pill-${pkg.doc_type === 'sits' ? 'danger' : 'warning'}`} style={{ fontSize: 10 }}>
                      {pkg.doc_type.toUpperCase()}
                    </span>
                  </td>
                  <td style={{ padding: '6px 8px', textAlign: 'center' }}>{pkg.summary?.unit_count ?? '-'}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'center' }}>{pkg.summary?.test_case_count ?? '-'}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'center' }}>{pkg.file_count}</td>
                  <td style={{ padding: '6px 8px', fontSize: 11, color: 'var(--text-muted)' }}>
                    {pkg.created ? new Date(pkg.created).toLocaleString('ko-KR') : '-'}
                  </td>
                  <td style={{ padding: '6px 8px', textAlign: 'center' }}>
                    <div style={{ display: 'flex', gap: 4, justifyContent: 'center' }}>
                      <button
                        type="button"
                        className="btn-sm"
                        onClick={() => downloadPackage(pkg.path, pkg.name)}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--accent)', fontSize: 11, padding: '2px 8px' }}
                      >
                        📥 다운로드
                      </button>
                      <button
                        className="btn-ghost btn-xs"
                        style={{ color: 'var(--danger)', fontSize: 11 }}
                        onClick={() => deletePackage(pkg.path, pkg.name)}
                      >
                        🗑
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ⚠ 실패를 "없음"으로 표시하지 않는다 — 그게 이 패널이 오래 고장 나 있던 이유다.
          403 이 "등록된 패키지가 없습니다"로 보였고, 아무도 오류를 못 봤다. */}
      {loadError && (
        <div className="text-sm" style={{ padding: 10, color: 'var(--danger)' }}>
          목록을 불러오지 못했습니다 — {loadError}
        </div>
      )}
      {packages.length === 0 && !loading && !loadError && (
        <div className="text-sm text-muted" style={{ padding: 12, textAlign: 'center' }}>
          등록된 VectorCAST 패키지가 없습니다. 위 버튼으로 등록하세요.
          {/* 0건이 **어느 루트에서 온** 0건인지 밝힌다. 안 밝히면 경로 오설정과
              미등록이 화면에서 똑같이 보인다(이번 결함의 재발 경로). */}
          {scannedRoots.length > 0 && (
            <div style={{ fontSize: 10, marginTop: 6, opacity: 0.8 }}>
              조회한 위치: {scannedRoots.map((r) => `${r.path}${r.exists ? '' : ' (없음)'}`).join(' · ')}
            </div>
          )}
        </div>
      )}
      {loading && <div className="text-sm text-muted" style={{ padding: 8 }}>로딩 중...</div>}
    </div>
  );
}

/* ── Document Preview Panel (inline / fullscreen) ──
 * 서버 사이드 페이지네이션: 백엔드가 page_size 윈도우만 반환하고 has_more로 다음
 * 페이지 존재 여부를 알려준다. 페이지/시트 이동은 부모(onGotoPage/onSwitchSheet)가
 * 서버에 재요청. (이전엔 client slice가 page를 무시 + 200행 캡 → "페이지 안넘어감") */
function DocPreviewPanel({ docPreview, previewSheet, onSwitchSheet, onGotoPage, loading, fullscreen, setFullscreen, onClose }) {
  const sheets = docPreview.data?.sheets || [];
  const sheet = sheets[previewSheet];
  const page = docPreview.page ?? 0;

  const switchSheet = (i) => { if (i !== previewSheet) onSwitchSheet(i); };

  const containerStyle = fullscreen ? {
    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 9999,
    background: 'var(--panel, #fff)', display: 'flex', flexDirection: 'column', overflow: 'hidden',
  } : { marginBottom: 12 };

  const tableMaxHeight = fullscreen ? 'calc(100vh - 90px)' : 400;

  return (
    <div className={fullscreen ? '' : 'panel'} style={containerStyle}>
      {/* Header */}
      <div className="panel-header" style={{ flexShrink: 0, padding: fullscreen ? '8px 16px' : undefined }}>
        <span className="panel-title" style={{ fontSize: fullscreen ? 14 : 12 }}>
          {docPreview.label} — {docPreview.filename}
        </span>
        <div style={{ display: 'flex', gap: 4 }}>
          <button className="btn-sm" onClick={() => setFullscreen(!fullscreen)} style={{ fontSize: 10 }}>
            {fullscreen ? '축소' : '크게보기'}
          </button>
          <button className="btn-sm" onClick={onClose} style={{ fontSize: 10 }}>닫기</button>
        </div>
      </div>

      {/* Sheet tabs */}
      {sheets.length > 1 && (
        <div style={{ display: 'flex', gap: 2, borderBottom: '1px solid var(--border)', marginBottom: 4, overflowX: 'auto', flexShrink: 0, padding: '0 8px' }}>
          {sheets.map((sh, i) => (
            <button key={i} onClick={() => switchSheet(i)}
              style={{
                padding: '5px 12px', fontSize: 11, border: 'none',
                borderBottom: previewSheet === i ? '2px solid var(--accent)' : '2px solid transparent',
                background: 'none', fontWeight: previewSheet === i ? 700 : 400,
                color: previewSheet === i ? 'var(--accent)' : 'var(--text-muted)',
                cursor: 'pointer', whiteSpace: 'nowrap',
              }}>
              {sh.name} <span style={{ fontSize: 9, opacity: 0.7 }}>({sh.total_rows ?? sh.rows?.length ?? '?'})</span>
            </button>
          ))}
        </div>
      )}

      {/* Table */}
      {sheet ? (() => {
        const headers = sheet.headers || [];
        // 서버가 이미 요청 페이지 윈도우만 반환 — 클라이언트 슬라이스 없이 그대로 렌더.
        const rows = sheet.rows || [];
        const startRow = page * PREVIEW_PAGE_SIZE;
        const hasMore = !!sheet.has_more;

        const renderCell = (cell, ci) => {
          const val = String(cell ?? '');
          // Render image if cell starts with __IMG__
          if (val.startsWith('__IMG__') && val.length > 7) {
            const imgId = val.slice(7);
            const docPath = docPreview.data?.filename;
            // Find original path from allDocs
            return <img src={`/api/preview-image?path=${encodeURIComponent(docPreview._path || '')}&image_id=${encodeURIComponent(imgId)}`}
                        alt="diagram" style={{ maxWidth: fullscreen ? 400 : 200, maxHeight: fullscreen ? 300 : 150 }}
                        onError={e => { e.target.style.display = 'none'; }} />;
          }
          return val.slice(0, fullscreen ? 200 : 60);
        };

        return (
          <div style={{ overflowX: 'auto', maxHeight: tableMaxHeight, overflowY: 'auto', flex: fullscreen ? 1 : undefined }}>
            <table className="impact-table" style={{ fontSize: fullscreen ? 11 : 10, minWidth: Math.max(headers.length * 100, 400) }}>
              <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
                <tr style={{ background: 'var(--bg)' }}>
                  {headers.map((h, i) => (
                    <th key={i} style={{ whiteSpace: 'nowrap', maxWidth: fullscreen ? 300 : 150, overflow: 'hidden', textOverflow: 'ellipsis', padding: fullscreen ? '6px 10px' : '4px 6px' }}
                        title={h}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row, ri) => (
                  <tr key={ri}>
                    {(Array.isArray(row) ? row : []).map((cell, ci) => (
                      <td key={ci}
                          style={{ maxWidth: fullscreen ? 400 : 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: fullscreen ? 'pre-wrap' : 'nowrap', padding: fullscreen ? '4px 8px' : '2px 4px', fontSize: fullscreen ? 11 : 10, wordBreak: fullscreen ? 'break-word' : undefined }}
                          title={String(cell || '')}>
                        {renderCell(cell, ci)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {/* Pagination — 서버 윈도우(has_more) 기반. 총 행수가 부정확할 수 있어
                표시 범위만 노출하고 '다음'은 has_more로 제어(유령 페이지 방지). */}
            {(page > 0 || hasMore) && (
              <div className="row" style={{ justifyContent: 'center', gap: 6, padding: '8px 0', alignItems: 'center' }}>
                <button className="btn-sm" onClick={() => onGotoPage(0)} disabled={page === 0 || loading}>« 처음</button>
                <button className="btn-sm" onClick={() => onGotoPage(page - 1)} disabled={page === 0 || loading}>‹ 이전</button>
                <span className="text-sm" style={{ padding: '4px 8px' }}>
                  {rows.length > 0 ? `${startRow + 1}~${startRow + rows.length}행` : '데이터 없음'} · {page + 1}페이지
                  {loading && <span className="spinner" style={{ marginLeft: 6, width: 12, height: 12, display: 'inline-block' }} />}
                </span>
                <button className="btn-sm" onClick={() => onGotoPage(page + 1)} disabled={!hasMore || loading}>다음 ›</button>
              </div>
            )}
          </div>
        );
      })() : <div className="text-muted text-sm" style={{ padding: 12 }}>데이터 없음</div>}
    </div>
  );
}

