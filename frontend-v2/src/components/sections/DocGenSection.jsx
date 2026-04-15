import { useState, useCallback, useEffect } from 'react';
import { api, post, defaultCacheRoot, getUsername } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';

async function pollProgress(jobUrl, buildSelector, jobId, action, { onMsg, signal }) {
  while (true) {
    if (signal?.aborted) return null;
    await new Promise(r => setTimeout(r, 2000));
    const data = await api(
      `/api/jenkins/progress?action=${encodeURIComponent(action)}` +
      `&job_url=${encodeURIComponent(jobUrl)}` +
      `&build_selector=${encodeURIComponent(buildSelector)}` +
      `&job_id=${encodeURIComponent(jobId)}`
    );
    const p = data?.progress || {};
    if (p.message || p.stage) onMsg(p.message || p.stage);
    if (p.progress != null) onMsg(`${p.message || ''} (${p.progress}%)`);
    if (p.done || p.error) return p;
  }
}

async function pollStsProgress(jobId, action, jobUrl, { onMsg, signal, prefix = '/api/jenkins' } = {}) {
  while (true) {
    if (signal?.aborted) return null;
    await new Promise(r => setTimeout(r, 3000));
    const qs = `job_id=${encodeURIComponent(jobId)}&job_url=${encodeURIComponent(jobUrl || '')}`;
    const data = await api(`${prefix}/${action}/progress?${qs}`);
    const p = data?.progress || data || {};
    if (p.message || p.stage) onMsg(p.message || p.stage);
    if (p.done || p.error) return p;
    if (p.status === 'completed' || p.status === 'done') return { done: true, ...p };
    if (p.status === 'failed' || p.status === 'error') return { error: p.error || p.message || '실패', ...p };
  }
}

const DOC_TYPES = [
  { key: 'uds', label: 'UDS', icon: '📘', desc: 'Unit Design Specification' },
  { key: 'sts', label: 'STS', icon: '📗', desc: 'Software Test Specification' },
  { key: 'suts', label: 'SUTS', icon: '📙', desc: 'Software Unit Test Specification' },
  { key: 'sits', label: 'SITS', icon: '📕', desc: 'Software Integration Test Specification' },
];

export default function DocGenSection({ job, analysisResult }) {
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
      // Get source_root and linked_docs from SCM registry
      let scm = analysisResult?.scmList?.[0];
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
      if (docPaths.template) formData.append('template_path', docPaths.template);
      if (docType === 'uds' && docPaths.template) formData.append('uds_template_path', docPaths.template);
      // Pass linked doc paths
      const srsPath = docPaths.srs || linkedDocs.srs || '';
      const sdsPath = docPaths.sds || linkedDocs.sds || '';
      const hsisPath = linkedDocs.hsis || '';
      const stpPath = linkedDocs.stp || '';
      const udsPath = linkedDocs.uds || '';
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
      if (user) fetchHeaders['X-User'] = user;
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

      if (docType === 'uds') {
        progress = await pollProgress(job.url, cfg.buildSelector || 'lastSuccessfulBuild', data.job_id, 'uds', {
          onMsg: onProgress, signal: null,
        });
      } else {
        const pollPrefix = docType === 'sits' ? '/api/local' : '/api/jenkins';
        progress = await pollStsProgress(data.job_id, docType, job.url, {
          onMsg: onProgress, signal: null, prefix: pollPrefix,
        });
      }

      if (progress?.error) throw new Error(progress.error);

      setGenProgress(100);
      setGenStage(`${label} 생성 완료`);
      setGenResult({ success: true, path: progress?.output_path || progress?.xlsm_path || '' });
      toast('success', `${label} 생성 완료`);
    } catch (e) {
      toast('error', `${label} 생성 실패: ${e.message}`);
      setGenStage(`오류: ${e.message}`);
      setGenResult({ success: false, error: e.message });
    } finally {
      setGenerating(null);
    }
  }, [job, cfg, cacheRoot, docPaths, toast, analysisResult]);

  const [scm, setScm] = useState(analysisResult?.scmList?.[0] || null);
  useEffect(() => {
    if (!scm?.source_root) {
      api('/api/scm/list').then(d => {
        const items = d?.items || (Array.isArray(d) ? d : []);
        if (items.length > 0) setScm(items[0]);
      }).catch(() => {});
    }
  }, [scm]);
  const linkedDocs = scm?.linked_docs || {};
  const localDocPaths = (() => {
    try { return JSON.parse(localStorage.getItem('devops_v2_doc_paths') || '{}'); } catch (_) { return {}; }
  })();

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

  const allDocs = [
    { key: 'sds', label: 'SDS', type: 'input', path: localDocPaths.sds || linkedDocs.sds || '' },
    { key: 'uds', label: 'UDS', type: 'output', path: linkedDocs.uds || '' },
    { key: 'sts', label: 'STS', type: 'output', path: linkedDocs.sts || '' },
    { key: 'suts', label: 'SUTS', type: 'output', path: linkedDocs.suts || '' },
    { key: 'sits', label: 'SITS', type: 'output', path: linkedDocs.sits || '' },
  ];

  const loadDocPreview = useCallback(async (docKey, path) => {
    if (!path) { toast('warning', '문서 경로가 등록되지 않았습니다.'); return; }
    setPreviewLoading(true);
    setDocPreview(null);
    setPreviewSheet(0);
    try {
      const filename = path.split(/[\\/]/).pop();
      // Use generic Excel preview API for all document types
      const data = await post('/api/preview-excel', { path });
      setDocPreview({ key: docKey, label: allDocs.find(d => d.key === docKey)?.label || docKey.toUpperCase(), filename, data, _path: path });
    } catch (e) {
      toast('error', `문서 미리보기 실패: ${e.message}`);
    } finally {
      setPreviewLoading(false);
    }
  }, [toast]);

  return (
    <div>
      {/* Document list - clickable for preview */}
      <div className="panel" style={{ marginBottom: 12 }}>
        <div className="panel-header">
          <span className="panel-title">문서 현황</span>
        </div>
        <table className="impact-table" style={{ fontSize: 11 }}>
          <thead>
            <tr><th style={{ width: 55 }}>문서</th><th>파일명</th><th style={{ width: 60 }}>상태</th><th style={{ width: 60 }}></th></tr>
          </thead>
          <tbody>
            {allDocs.map(d => (
              <tr key={d.key} style={{ cursor: d.path ? 'pointer' : 'default' }}
                  onClick={() => d.path && loadDocPreview(d.key, d.path)}>
                <td><span className={`pill ${d.type === 'input' ? 'pill-info' : 'pill-purple'}`} style={{ fontSize: 9 }}>{d.label}</span></td>
                <td style={{ fontFamily: 'monospace', fontSize: 10 }} title={d.path}>
                  {d.path ? d.path.split(/[\\/]/).pop() : <span className="text-muted">미등록</span>}
                </td>
                <td style={{ textAlign: 'center' }}>
                  {d.path ? <span className="pill pill-success" style={{ fontSize: 9 }}>등록됨</span> : <span className="pill pill-neutral" style={{ fontSize: 9 }}>-</span>}
                </td>
                <td style={{ textAlign: 'center' }}>
                  {d.path && <button className="btn-sm" style={{ fontSize: 9, padding: '1px 6px' }}
                    onClick={e => { e.stopPropagation(); loadDocPreview(d.key, d.path); }}
                    disabled={previewLoading}>보기</button>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Document preview */}
      {docPreview && <DocPreviewPanel
        docPreview={docPreview}
        previewSheet={previewSheet}
        setPreviewSheet={setPreviewSheet}
        fullscreen={fullscreen}
        setFullscreen={setFullscreen}
        onClose={() => { setDocPreview(null); setFullscreen(false); }}
      />}

      {/* Generation controls */}
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">문서 생성</span>
        </div>

        <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
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
  const [scm, setScm] = useState(analysisResult?.scmList?.[0] || null);
  useEffect(() => {
    if (!scm?.source_root) {
      api('/api/scm/list').then(d => {
        const items = d?.items || (Array.isArray(d) ? d : []);
        if (items.length > 0) setScm(items[0]);
      }).catch(() => {});
    }
  }, []);

  // 패키지 목록 조회
  const loadPackages = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api(`/api/local/vectorcast/list?report_dir=${encodeURIComponent(cacheRoot)}`);
      setPackages(data?.packages || []);
    } catch (_) {
      setPackages([]);
    } finally {
      setLoading(false);
    }
  }, [cacheRoot]);

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
      const user = getUsername();
      const endpoint = docType === 'sits' ? '/api/local/sits/export-vectorcast' : `/api/jenkins/${docType}/export-vectorcast`;
      const res = await fetch(endpoint, { method: 'POST', body: formData, headers: user ? { 'X-User': user } : {} });
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

  // 패키지 삭제
  const deletePackage = useCallback(async (pkgPath, pkgName) => {
    if (!window.confirm(`"${pkgName}" 패키지를 삭제하시겠습니까?`)) return;
    try {
      await api(`/api/local/vectorcast/delete?package_path=${encodeURIComponent(pkgPath)}`, { method: 'DELETE' });
      toast('success', `${pkgName} 삭제됨`);
      loadPackages();
    } catch (e) {
      toast('error', `삭제 실패: ${e.message}`);
    }
  }, [toast, loadPackages]);

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
              {packages.map((pkg) => (
                <tr key={pkg.name} style={{ borderTop: '1px solid var(--border)' }}>
                  <td style={{ padding: '6px 8px', fontWeight: 600 }}>{pkg.name}</td>
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
                      <a
                        href={`/api/local/vectorcast/download?package_path=${encodeURIComponent(pkg.path)}`}
                        download
                        className="btn-sm"
                        style={{ textDecoration: 'none', color: 'var(--accent)', fontSize: 11, padding: '2px 8px' }}
                      >
                        📥 다운로드
                      </a>
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

      {packages.length === 0 && !loading && (
        <div className="text-sm text-muted" style={{ padding: 12, textAlign: 'center' }}>
          등록된 VectorCAST 패키지가 없습니다. 위 버튼으로 등록하세요.
        </div>
      )}
      {loading && <div className="text-sm text-muted" style={{ padding: 8 }}>로딩 중...</div>}
    </div>
  );
}

/* ── Document Preview Panel (inline / fullscreen) ── */
function DocPreviewPanel({ docPreview, previewSheet, setPreviewSheet, fullscreen, setFullscreen, onClose }) {
  const sheets = docPreview.data?.sheets || [];
  const sheet = sheets[previewSheet];
  const [page, setPage] = useState(0);
  const pageSize = fullscreen ? 200 : 100;
  const docPath = docPreview.data?.filename ? undefined : undefined; // path from allDocs

  // Reset page when switching sheets
  const switchSheet = (i) => { setPreviewSheet(i); setPage(0); };

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
        const allRows = sheet.rows || [];
        const totalRows = sheet.total_rows ?? allRows.length;
        const rows = allRows.slice(0, pageSize);
        const totalPages = Math.ceil(totalRows / pageSize);

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
            {/* Pagination */}
            {totalRows > pageSize && (
              <div className="row" style={{ justifyContent: 'center', gap: 6, padding: '8px 0' }}>
                <button className="btn-sm" onClick={() => setPage(0)} disabled={page === 0}>«</button>
                <button className="btn-sm" onClick={() => setPage(p => p - 1)} disabled={page === 0}>‹</button>
                <span className="text-sm" style={{ padding: '4px 8px' }}>
                  {page * pageSize + 1}~{Math.min((page + 1) * pageSize, totalRows)} / {totalRows}행
                </span>
                <button className="btn-sm" onClick={() => setPage(p => p + 1)} disabled={page >= totalPages - 1}>›</button>
                <button className="btn-sm" onClick={() => setPage(totalPages - 1)} disabled={page >= totalPages - 1}>»</button>
              </div>
            )}
          </div>
        );
      })() : <div className="text-muted text-sm" style={{ padding: 12 }}>데이터 없음</div>}
    </div>
  );
}

