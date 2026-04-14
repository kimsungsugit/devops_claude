import { useState, useCallback } from 'react';
import { api, post, defaultCacheRoot, getUsername } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';

const TABS = [
  { key: 'qac', label: '정적 분석 (QAC/PRQA)', icon: '📊' },
  { key: 'vcast', label: '동적 분석 (VectorCAST)', icon: '🧪' },
  // { key: 'compare', label: 'Excel 비교', icon: '🔄' },  // hidden for now
];

export default function ReportGenSection({ job, analysisResult }) {
  const [activeTab, setActiveTab] = useState('qac');

  return (
    <div>
      {/* Tab selector */}
      <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', marginBottom: 12 }}>
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setActiveTab(t.key)}
            style={{
              padding: '8px 16px', border: 'none',
              borderBottom: activeTab === t.key ? '2px solid var(--accent)' : '2px solid transparent',
              background: 'none', fontWeight: activeTab === t.key ? 700 : 400,
              color: activeTab === t.key ? 'var(--accent)' : 'var(--text-muted)',
              cursor: 'pointer', fontSize: 13,
            }}
          >
            {t.icon} {t.label}
          </button>
        ))}
      </div>

      {activeTab === 'qac' && <QACPanel job={job} analysisResult={analysisResult} />}
      {activeTab === 'vcast' && <VCastPanel job={job} analysisResult={analysisResult} />}
      {activeTab === 'compare' && <ExcelComparePanel />}
    </div>
  );
}

/* ── QAC Panel ── */
function QACPanel({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;

  const [artifacts, setArtifacts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [generatedFile, setGeneratedFile] = useState(null);
  const [scanFolder, setScanFolder] = useState('');
  const [reports, setReports] = useState([]);

  const loadReports = useCallback(async () => {
    try {
      const data = await api('/api/qac/reports');
      setReports(data?.reports ?? []);
    } catch (_) {}
  }, []);
  const [scanLoading, setScanLoading] = useState(false);

  const scanFolderFiles = useCallback(async () => {
    if (!scanFolder.trim()) { toast('warning', '폴더 경로를 입력하세요.'); return; }
    setScanLoading(true);
    try {
      const data = await post('/api/qac/scan-folder', { folder: scanFolder.trim() });
      setArtifacts(data?.items ?? []);
      if ((data?.items ?? []).length === 0) toast('info', 'QAC HTML 파일을 찾지 못했습니다.');
      else toast('success', `${data.items.length}개 파일 발견`);
    } catch (e) {
      toast('error', `폴더 스캔 실패: ${e.message}`);
    } finally {
      setScanLoading(false);
    }
  }, [scanFolder, toast]);

  const loadArtifacts = useCallback(async () => {
    setLoading(true);
    try {
      const qs = `job_url=${encodeURIComponent(job?.url ?? '')}&cache_root=${encodeURIComponent(cacheRoot)}`;
      const data = await api(`/api/qac/jenkins-artifacts?${qs}`);
      setArtifacts(data?.artifacts ?? data?.files ?? (Array.isArray(data) ? data : []));
    } catch (e) {
      toast('error', `아티팩트 로드 실패: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [job, cacheRoot, toast]);

  const generateExcel = useCallback(async (artifactPath) => {
    setGenerating(true);
    try {
      // If path is absolute (from folder scan), use path-based API; otherwise Jenkins API
      const isAbsPath = artifactPath.includes(':') || artifactPath.startsWith('/') || artifactPath.startsWith('\\');
      let res;
      if (isAbsPath) {
        const user = getUsername();
        res = await fetch('/api/qac/generate-excel-from-path', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(user ? { 'X-User': user } : {}) },
          body: JSON.stringify({ path: artifactPath }),
        });
      } else {
        const qs = `job_url=${encodeURIComponent(job?.url ?? '')}&cache_root=${encodeURIComponent(cacheRoot)}&rel_path=${encodeURIComponent(artifactPath)}`;
        res = await fetch(`/api/qac/jenkins-excel?${qs}`);
      }
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const blob = await res.blob();
      const filename = res.headers.get('content-disposition')?.match(/filename="?(.+?)"?$/)?.[1]
        || `qac_report_${new Date().toISOString().slice(0,10)}.xlsx`;
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      URL.revokeObjectURL(a.href);
      setGeneratedFile({ filename, artifact_path: artifactPath });
      toast('success', `QAC Excel 생성 완료: ${filename}`);
    } catch (e) {
      toast('error', `Excel 생성 실패: ${e.message}`);
    } finally {
      setGenerating(false);
    }
  }, [job, cacheRoot, toast]);

  // File upload → parse → Excel
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadOldVer, setUploadOldVer] = useState(false);

  const uploadAndGenerate = useCallback(async () => {
    if (!uploadFile) return;
    setGenerating(true);
    try {
      const formData = new FormData();
      formData.append('file', uploadFile);
      const user = getUsername();
      const res = await fetch(`/api/qac/generate-excel?old_version=${uploadOldVer}`, {
        method: 'POST',
        body: formData,
        headers: user ? { 'X-User': user } : {},
      });
      if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);
      const blob = await res.blob();
      const filename = res.headers.get('content-disposition')?.match(/filename="?(.+?)"?$/)?.[1]
        || uploadFile.name.replace(/\.html$/i, '.xlsx');
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      URL.revokeObjectURL(a.href);
      setGeneratedFile({ filename });
      toast('success', `QAC Excel 생성 완료: ${filename}`);
    } catch (e) {
      toast('error', `업로드 생성 실패: ${e.message}`);
    } finally {
      setGenerating(false);
    }
  }, [uploadFile, uploadOldVer, toast]);

  const EXT_ICON = { html: '🌐', xlsx: '📊', csv: '📄' };

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">정적 분석 리포트 (QAC/PRQA)</span>
        <div style={{ display: 'flex', gap: 4 }}>
          <button className="btn-sm" onClick={loadReports}>산출물 목록</button>
          <button className="btn-sm" onClick={loadArtifacts} disabled={loading}>
            {loading ? <span className="spinner" /> : 'Jenkins 아티팩트'}
          </button>
        </div>
      </div>

      {/* Folder scan */}
      <div className="row" style={{ gap: 8, marginBottom: 12, alignItems: 'flex-end' }}>
        <div style={{ flex: 1 }}>
          <label style={{ fontSize: 11, fontWeight: 600 }}>폴더 경로 (하위 폴더 자동 스캔)</label>
          <input type="text" value={scanFolder} onChange={e => setScanFolder(e.target.value)}
            placeholder="D:\path\to\PRQA\reports" style={{ fontSize: 12, width: '100%' }}
            onKeyDown={e => e.key === 'Enter' && scanFolderFiles()} />
        </div>
        <button className="btn-primary btn-sm" onClick={scanFolderFiles} disabled={scanLoading} style={{ height: 34, whiteSpace: 'nowrap' }}>
          {scanLoading ? '스캔 중...' : '폴더 스캔'}
        </button>
      </div>

      {/* PRQA summary from analysis */}
      {analysisResult?.reportData?.kpis?.prqa && (() => {
        const prqa = analysisResult.reportData.kpis.prqa;
        return (
          <div className="stats-row" style={{ marginBottom: 12 }}>
            {prqa.rule_violation_count != null && (
              <div className="stat-card">
                <div className="stat-value" style={{ color: prqa.rule_violation_count > 0 ? 'var(--color-warning)' : 'var(--color-success)' }}>
                  {prqa.rule_violation_count}
                </div>
                <div className="stat-label">위반 건수</div>
              </div>
            )}
            {prqa.project_compliance_index != null && (
              <div className="stat-card">
                <div className="stat-value">{prqa.project_compliance_index}%</div>
                <div className="stat-label">프로젝트 준수율</div>
              </div>
            )}
            {prqa.hmr_stats?.functions_total != null && (
              <div className="stat-card">
                <div className="stat-value">{prqa.hmr_stats.functions_total}</div>
                <div className="stat-label">분석 함수</div>
              </div>
            )}
            {prqa.hmr_stats?.vg_max != null && (
              <div className="stat-card">
                <div className="stat-value">{prqa.hmr_stats.vg_max}</div>
                <div className="stat-label">VG Max</div>
              </div>
            )}
          </div>
        );
      })()}

      {/* Artifact list */}
      {artifacts.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div className="text-sm" style={{ fontWeight: 600, marginBottom: 6 }}>
            PRQA 아티팩트 ({artifacts.length}개)
          </div>
          <div className="artifact-list">
            {artifacts.map((f, i) => {
              const name = typeof f === 'string' ? f : (f.name ?? f.filename ?? f.path ?? '');
              const path = typeof f === 'string' ? f : (f.path ?? f.rel_path ?? name);
              const ext = name.split('.').pop()?.toLowerCase();
              const isHtml = ext === 'html';
              return (
                <div key={i} className="artifact-item" style={{ padding: '6px 8px' }}>
                  <span className="artifact-icon">{EXT_ICON[ext] || '📄'}</span>
                  <span className="artifact-name" style={{ flex: 1 }} title={path}>
                    {name.length > 60 ? `...${name.slice(-57)}` : name}
                  </span>
                  <span className="pill pill-neutral" style={{ fontSize: 10 }}>{ext?.toUpperCase()}</span>
                  {(isHtml && (f.can_parse !== false)) && (
                    <button
                      className="btn-primary btn-sm"
                      onClick={() => generateExcel(path)}
                      disabled={generating}
                      style={{ fontSize: 10, padding: '2px 8px' }}
                    >
                      {generating ? '...' : 'Excel 생성'}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {artifacts.length === 0 && !loading && (
        <div className="text-muted text-sm" style={{ padding: 12 }}>
          Jenkins 아티팩트 조회 또는 아래에서 HTML 파일을 직접 업로드하세요.
        </div>
      )}

      {/* File upload section */}
      <div className="divider" style={{ margin: '12px 0' }} />
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>로컬 파일 업로드</div>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <input type="file" accept=".html" onChange={e => setUploadFile(e.target.files?.[0] || null)} style={{ fontSize: 12 }} />
        </div>
        <label style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 4 }}>
          <input type="checkbox" checked={uploadOldVer} onChange={e => setUploadOldVer(e.target.checked)} />
          PRQA (구버전)
        </label>
        <button className="btn-primary btn-sm" onClick={uploadAndGenerate} disabled={generating || !uploadFile}>
          {generating ? '생성 중...' : '업로드 → Excel 생성'}
        </button>
      </div>

      {/* Generated file */}
      {generatedFile && (
        <div style={{ marginTop: 12, padding: 10, background: 'var(--bg)', borderRadius: 6, border: '1px solid var(--border)' }}>
          <div className="row" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <StatusBadge tone="success">생성 완료</StatusBadge>
              <span style={{ marginLeft: 8, fontSize: 13, fontWeight: 600 }}>
                {generatedFile.filename || generatedFile.output_path?.split(/[\\/]/).pop() || 'qac_report.xlsx'}
              </span>
            </div>
            <a
              href={generatedFile.download_url || `/api/qac/jenkins-excel?job_url=${encodeURIComponent(job?.url ?? '')}&cache_root=${encodeURIComponent(cacheRoot)}&artifact_path=${encodeURIComponent(generatedFile.artifact_path || '')}`}
              download
              className="btn-primary btn-sm"
              style={{ textDecoration: 'none', fontSize: 11 }}
            >
              다운로드
            </a>
          </div>
        </div>
      )}

      {/* Generated reports list */}
      {reports.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div className="text-sm" style={{ fontWeight: 600, marginBottom: 6 }}>생성된 산출물 ({reports.length}개)</div>
          <div className="artifact-list" style={{ maxHeight: 200, overflowY: 'auto' }}>
            {reports.map((f, i) => (
              <div key={i} className="artifact-item" style={{ padding: '5px 8px' }}>
                <span className="artifact-icon">📊</span>
                <span className="artifact-name" style={{ flex: 1, fontSize: 11 }}>{f.name}</span>
                <span className="text-muted" style={{ fontSize: 10 }}>{f.created?.slice(0, 10)}</span>
                <span className="text-muted" style={{ fontSize: 10, marginLeft: 4 }}>{Math.round((f.size || 0) / 1024)}KB</span>
                <a href={`/api/qac/reports/${encodeURIComponent(f.name)}`} download
                  style={{ fontSize: 11, color: 'var(--accent)', textDecoration: 'none', marginLeft: 6 }}>↓</a>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── VectorCAST Panel ── */
function VCastPanel({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;

  const [reportType, setReportType] = useState('TestCaseData');
  const [version, setVersion] = useState('Ver2025');
  const [parsedData, setParsedData] = useState(null);
  const [parsing, setParsing] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [reports, setReports] = useState([]);
  const [scanFolder, setScanFolder] = useState('');
  const [scanFiles, setScanFiles] = useState([]);
  const [scanLoading, setScanLoading] = useState(false);
  const [testSummary, setTestSummary] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);

  const analyzeTests = useCallback(async () => {
    if (!parsedData) return;
    setAnalyzing(true);
    try {
      const data = await post('/api/vcast/test-summary', {
        parsed_data: parsedData?.data ?? parsedData,
        coverage_line: analysisResult?.reportData?.tester?.coverage_line ?? 0,
        coverage_branch: analysisResult?.reportData?.tester?.coverage_branch ?? 0,
      });
      setTestSummary(data);
      toast('success', `테스트 분석 완료 — ${data?.executive_summary?.verdict || 'OK'}`);
    } catch (e) {
      toast('error', `테스트 분석 실패: ${e.message}`);
    } finally {
      setAnalyzing(false);
    }
  }, [parsedData, analysisResult, toast]);

  const scanFolderFiles = useCallback(async () => {
    if (!scanFolder.trim()) { toast('warning', '폴더 경로를 입력하세요.'); return; }
    setScanLoading(true);
    try {
      const data = await post('/api/vcast/scan-folder', { folder: scanFolder.trim() });
      setScanFiles(data?.items ?? []);
      if ((data?.items ?? []).length === 0) toast('info', 'VectorCAST HTML 파일을 찾지 못했습니다.');
      else toast('success', `${data.items.length}개 파일 발견`);
    } catch (e) {
      toast('error', `폴더 스캔 실패: ${e.message}`);
    } finally {
      setScanLoading(false);
    }
  }, [scanFolder, toast]);

  const parseJenkins = useCallback(async () => {
    setParsing(true);
    setParsedData(null);
    try {
      const data = await post('/api/vcast/process-jenkins', {
        job_url: job?.url ?? '',
        cache_root: cacheRoot,
        build_selector: cfg.buildSelector || 'lastSuccessfulBuild',
        report_type: reportType,
        version: version,
      });
      setParsedData(data);
      toast('success', `VectorCAST ${reportType} 파싱 완료`);
    } catch (e) {
      toast('error', `파싱 실패: ${e.message}`);
    } finally {
      setParsing(false);
    }
  }, [job, cfg, cacheRoot, reportType, version, toast]);

  const generateExcel = useCallback(async () => {
    if (!parsedData) {
      toast('warning', '먼저 파싱을 실행하세요.');
      return;
    }
    setGenerating(true);
    try {
      const data = await post('/api/vcast/generate-excel', {
        parsed_data: parsedData?.data ?? parsedData,
        mode: reportType === 'Metrics' ? 'Metrics' : 'TestReport',
        output_filename: `vcast_${reportType.toLowerCase()}_${new Date().toISOString().slice(0,10).replace(/-/g,'')}.xlsx`,
      });
      toast('success', 'VectorCAST Excel 리포트 생성 완료');
      loadReports();
    } catch (e) {
      toast('error', `Excel 생성 실패: ${e.message}`);
    } finally {
      setGenerating(false);
    }
  }, [parsedData, reportType, toast]);

  const loadReports = useCallback(async () => {
    try {
      const data = await api('/api/vcast/reports');
      setReports(data?.reports ?? data?.files ?? (Array.isArray(data) ? data : []));
    } catch (e) {
      console.warn('VCast reports load failed:', e.message);
    }
  }, []);

  // File upload → parse → Excel
  const [uploadFile, setUploadFile] = useState(null);
  const [uploadType, setUploadType] = useState('TestCaseData');

  const uploadAndGenerate = useCallback(async () => {
    if (!uploadFile) return;
    setGenerating(true);
    try {
      const formData = new FormData();
      formData.append('file', uploadFile);
      const user = getUsername();
      // Step 1: Parse
      const parseRes = await fetch(`/api/vcast/parse?report_type=${uploadType}&version=${version}`, {
        method: 'POST', body: formData,
        headers: user ? { 'X-User': user } : {},
      });
      if (!parseRes.ok) throw new Error(await parseRes.text() || `HTTP ${parseRes.status}`);
      const parsed = await parseRes.json();
      setParsedData(parsed);

      // Step 2: Generate Excel
      const mode = uploadType === 'Metrics' ? 'Metrics' : 'TestReport';
      const excelRes = await fetch('/api/vcast/generate-excel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(user ? { 'X-User': user } : {}) },
        body: JSON.stringify({
          parsed_data: parsed?.data ?? parsed,
          mode,
          output_filename: `vcast_${uploadType.toLowerCase()}_${new Date().toISOString().slice(0, 10).replace(/-/g, '')}.xlsx`,
        }),
      });
      if (!excelRes.ok) throw new Error(await excelRes.text() || `HTTP ${excelRes.status}`);
      const blob = await excelRes.blob();
      const filename = excelRes.headers.get('content-disposition')?.match(/filename="?(.+?)"?$/)?.[1]
        || `vcast_${uploadType.toLowerCase()}.xlsx`;
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = filename;
      a.click();
      URL.revokeObjectURL(a.href);
      toast('success', `VCast Excel 생성 완료: ${filename}`);
      loadReports();
    } catch (e) {
      toast('error', `업로드 생성 실패: ${e.message}`);
    } finally {
      setGenerating(false);
    }
  }, [uploadFile, uploadType, version, toast, loadReports]);

  // VectorCAST summary from analysis
  const tester = analysisResult?.reportData?.tester;
  const vc = tester?.vectorcast;

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">동적 분석 리포트 (VectorCAST)</span>
        <button className="btn-sm" onClick={loadReports}>산출물 목록</button>
      </div>

      {/* Folder scan */}
      <div className="row" style={{ gap: 8, marginBottom: 12, alignItems: 'flex-end' }}>
        <div style={{ flex: 1 }}>
          <label style={{ fontSize: 11, fontWeight: 600 }}>폴더 경로 (하위 폴더 자동 스캔)</label>
          <input type="text" value={scanFolder} onChange={e => setScanFolder(e.target.value)}
            placeholder="D:\path\to\VectorCAST\reports" style={{ fontSize: 12, width: '100%' }}
            onKeyDown={e => e.key === 'Enter' && scanFolderFiles()} />
        </div>
        <button className="btn-primary btn-sm" onClick={scanFolderFiles} disabled={scanLoading} style={{ height: 34, whiteSpace: 'nowrap' }}>
          {scanLoading ? '스캔 중...' : '폴더 스캔'}
        </button>
      </div>

      {/* Scan results */}
      {scanFiles.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div className="text-sm" style={{ fontWeight: 600, marginBottom: 6 }}>스캔 결과 ({scanFiles.length}개)</div>
          <div className="artifact-list" style={{ maxHeight: 200, overflowY: 'auto' }}>
            {scanFiles.map((f, i) => (
              <div key={i} className="artifact-item" style={{ padding: '4px 8px' }}>
                <span className="artifact-icon">📄</span>
                <span className="artifact-name" style={{ flex: 1, fontSize: 11 }} title={f.path}>{f.name}</span>
                <span className="pill pill-info" style={{ fontSize: 9 }}>{f.kind}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* VectorCAST summary from analysis */}
      {vc && (
        <div className="stats-row" style={{ marginBottom: 12 }}>
          {vc.test_rows_count != null && (
            <div className="stat-card">
              <div className="stat-value">{vc.test_rows_count?.toLocaleString()}</div>
              <div className="stat-label">테스트 케이스</div>
            </div>
          )}
          {tester?.coverage_line != null && (
            <div className="stat-card">
              <div className="stat-value" style={{ color: tester.coverage_line >= 0.8 ? 'var(--color-success)' : 'var(--color-warning)' }}>
                {Math.round(tester.coverage_line * 100)}%
              </div>
              <div className="stat-label">Line Coverage</div>
            </div>
          )}
          {(vc.ut_reports || []).length > 0 && (
            <div className="stat-card">
              <div className="stat-value">{vc.ut_reports.length}</div>
              <div className="stat-label">UT 리포트</div>
            </div>
          )}
          {(vc.it_reports || []).length > 0 && (
            <div className="stat-card">
              <div className="stat-value">{vc.it_reports.length}</div>
              <div className="stat-label">IT 리포트</div>
            </div>
          )}
        </div>
      )}

      {/* Controls */}
      <div className="row" style={{ gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div className="field" style={{ flex: 1, minWidth: 140 }}>
          <label style={{ fontSize: 11 }}>리포트 유형</label>
          <select value={reportType} onChange={e => setReportType(e.target.value)} style={{ fontSize: 12 }}>
            <option value="TestCaseData">Test Case Data</option>
            <option value="Metrics">Metrics (Coverage)</option>
            <option value="AggregateCoverage">Aggregate Coverage</option>
            <option value="ExecutionResult">Execution Result</option>
          </select>
        </div>
        <div className="field" style={{ flex: 1, minWidth: 120 }}>
          <label style={{ fontSize: 11 }}>VectorCAST 버전</label>
          <select value={version} onChange={e => setVersion(e.target.value)} style={{ fontSize: 12 }}>
            <option value="Ver2025">2025</option>
            <option value="Ver2024">2024</option>
            <option value="Ver2021">2021</option>
          </select>
        </div>
        <button className="btn-primary btn-sm" onClick={parseJenkins} disabled={parsing} style={{ height: 34 }}>
          {parsing ? <><span className="spinner" style={{ display: 'inline-block', marginRight: 4 }} />파싱 중...</> : '아티팩트 파싱'}
        </button>
        <button className="btn-primary btn-sm" onClick={generateExcel} disabled={generating || !parsedData} style={{ height: 34 }}>
          {generating ? '생성 중...' : 'Excel 생성'}
        </button>
        <button className="btn-sm" onClick={loadReports} style={{ height: 34 }}>리포트 목록</button>
      </div>

      {/* Parsed data summary */}
      {parsedData && (
        <div style={{ marginBottom: 12, padding: 8, background: 'var(--bg)', borderRadius: 6, border: '1px solid var(--border)' }}>
          <StatusBadge tone="success">파싱 완료</StatusBadge>
          <span className="text-sm" style={{ marginLeft: 8 }}>
            {parsedData.environment ?? parsedData.data?.environment ?? ''} —
            {reportType === 'Metrics'
              ? `${Object.keys(parsedData.data?.statement_data ?? parsedData.statement_data ?? {}).length} units`
              : `${parsedData.data?.test_count ?? parsedData.test_count ?? '?'} test cases`
            }
          </span>
          <button className="btn-sm" style={{ marginLeft: 8, fontSize: 10 }} onClick={analyzeTests} disabled={analyzing}>
            {analyzing ? '분석 중...' : '테스트 분석'}
          </button>
        </div>
      )}

      {/* Test Summary Panel */}
      {testSummary && (
        <div style={{ marginBottom: 12, padding: 10, background: 'var(--bg)', borderRadius: 6, border: '1px solid var(--border)' }}>
          <div style={{ fontWeight: 700, fontSize: 12, marginBottom: 8 }}>테스트 분석 결과</div>

          {/* Verdict */}
          <div style={{ marginBottom: 8 }}>
            <StatusBadge tone={testSummary.executive_summary?.verdict === 'PASS' ? 'success'
              : testSummary.executive_summary?.verdict === 'FAIL' ? 'danger' : 'warning'}>
              {testSummary.executive_summary?.verdict_text || testSummary.executive_summary?.verdict}
            </StatusBadge>
          </div>

          {/* Metrics */}
          <div className="stats-row" style={{ marginBottom: 8 }}>
            <div className="stat-card">
              <div className="stat-value">{testSummary.test_summary?.total ?? 0}</div>
              <div className="stat-label">전체</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{ color: 'var(--color-success)' }}>{testSummary.test_summary?.passed ?? 0}</div>
              <div className="stat-label">통과</div>
            </div>
            <div className="stat-card">
              <div className="stat-value" style={{ color: testSummary.test_summary?.failed > 0 ? 'var(--color-danger)' : 'var(--color-success)' }}>
                {testSummary.test_summary?.failed ?? 0}
              </div>
              <div className="stat-label">실패</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{testSummary.executive_summary?.metrics?.pass_rate_pct ?? 0}%</div>
              <div className="stat-label">통과율</div>
            </div>
          </div>

          {/* Quality Gates */}
          {testSummary.quality_gates?.gates && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>
                품질 게이트 {testSummary.quality_gates.overall_pass
                  ? <StatusBadge tone="success">PASS</StatusBadge>
                  : <StatusBadge tone="danger">FAIL</StatusBadge>}
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {testSummary.quality_gates.gates.map((g, i) => (
                  <div key={i} style={{
                    padding: '4px 8px', borderRadius: 4, fontSize: 10,
                    border: `1px solid ${g.status === 'pass' ? 'var(--color-success)' : g.status === 'warn' ? 'var(--color-warning)' : 'var(--color-danger)'}`,
                    background: 'var(--bg-secondary)',
                  }}>
                    <span style={{ fontWeight: 600 }}>{g.name}</span>:{' '}
                    {g.name.includes('실패') ? `${g.actual}건 / 최대 ${g.threshold}건` : `${g.actual}% / ${g.threshold}%`}
                    <span style={{ marginLeft: 4 }}>{g.status === 'pass' ? '✓' : g.status === 'warn' ? '⚠' : '✗'}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Failure Categories */}
          {testSummary.failure_categories && Object.values(testSummary.failure_categories).some(v => v > 0) && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>실패 분류</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {Object.entries(testSummary.failure_categories).filter(([,v]) => v > 0).map(([cat, cnt]) => (
                  <span key={cat} className={`pill ${cat === 'crash' ? 'pill-danger' : cat === 'assertion' ? 'pill-warning' : 'pill-info'}`}
                    style={{ fontSize: 10 }}>
                    {cat}: {cnt}건
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Unit Breakdown (top 5 worst) */}
          {testSummary.unit_breakdown?.length > 0 && (
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>유닛별 결과 (실패 상위)</div>
              <table style={{ width: '100%', fontSize: 10, borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)' }}>
                    <th style={{ textAlign: 'left', padding: '3px 6px' }}>유닛</th>
                    <th style={{ textAlign: 'right', padding: '3px 6px' }}>통과</th>
                    <th style={{ textAlign: 'right', padding: '3px 6px' }}>실패</th>
                    <th style={{ textAlign: 'right', padding: '3px 6px' }}>통과율</th>
                  </tr>
                </thead>
                <tbody>
                  {testSummary.unit_breakdown
                    .sort((a, b) => a.pass_rate - b.pass_rate)
                    .slice(0, 8)
                    .map((u, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border-light, var(--border))' }}>
                      <td style={{ padding: '3px 6px', fontFamily: 'monospace' }}>{u.unit_name}</td>
                      <td style={{ textAlign: 'right', padding: '3px 6px', color: 'var(--color-success)' }}>{u.passed}</td>
                      <td style={{ textAlign: 'right', padding: '3px 6px', color: u.failed > 0 ? 'var(--color-danger)' : undefined }}>{u.failed}</td>
                      <td style={{ textAlign: 'right', padding: '3px 6px', fontWeight: 600 }}>{Math.round(u.pass_rate * 100)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Generated reports */}
      {reports.length > 0 && (
        <div>
          <div className="text-sm" style={{ fontWeight: 600, marginBottom: 6 }}>
            생성된 산출물 ({reports.length}개)
          </div>
          <div className="artifact-list" style={{ maxHeight: 200, overflowY: 'auto' }}>
            {reports.map((f, i) => {
              const name = typeof f === 'string' ? f : (f.name ?? f.filename ?? '');
              const size = typeof f === 'object' ? f.size : 0;
              const created = typeof f === 'object' ? (f.created || '') : '';
              return (
                <div key={i} className="artifact-item" style={{ padding: '5px 8px' }}>
                  <span className="artifact-icon">📊</span>
                  <span className="artifact-name" style={{ flex: 1, fontSize: 11 }}>{name}</span>
                  {created && <span className="text-muted" style={{ fontSize: 10 }}>{created.slice(0, 10)}</span>}
                  {size > 0 && <span className="text-muted" style={{ fontSize: 10, marginLeft: 4 }}>{Math.round(size / 1024)}KB</span>}
                  <a
                    href={`/api/vcast/reports/${encodeURIComponent(name)}`}
                    download
                    style={{ fontSize: 11, color: 'var(--accent)', textDecoration: 'none', padding: '2px 6px' }}
                  >
                    ↓
                  </a>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {!parsedData && reports.length === 0 && (
        <div className="text-muted text-sm" style={{ padding: 12 }}>
          Jenkins 아티팩트 파싱 또는 아래에서 HTML 파일을 직접 업로드하세요.
        </div>
      )}

      {/* File upload section */}
      <div className="divider" style={{ margin: '12px 0' }} />
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8 }}>로컬 파일 업로드</div>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <input type="file" accept=".html" onChange={e => setUploadFile(e.target.files?.[0] || null)} style={{ fontSize: 12 }} />
        </div>
        <div className="field" style={{ minWidth: 130 }}>
          <label style={{ fontSize: 11 }}>리포트 유형</label>
          <select value={uploadType} onChange={e => setUploadType(e.target.value)} style={{ fontSize: 11 }}>
            <option value="TestCaseData">Test Case Data</option>
            <option value="ExecutionResult">Execution Result</option>
            <option value="Metrics">Metrics</option>
          </select>
        </div>
        <button className="btn-primary btn-sm" onClick={uploadAndGenerate} disabled={generating || !uploadFile}>
          {generating ? '생성 중...' : '업로드 → Excel 생성'}
        </button>
      </div>
    </div>
  );
}

/* ── Excel Compare Panel ── */
function ExcelComparePanel() {
  const toast = useToast();
  const [sourceFile, setSourceFile] = useState(null);
  const [targetFile, setTargetFile] = useState(null);
  const [comparing, setComparing] = useState(false);
  const [result, setResult] = useState(null);

  const compare = useCallback(async () => {
    if (!sourceFile || !targetFile) {
      toast('warning', '비교할 두 Excel 파일을 선택하세요.');
      return;
    }
    setComparing(true);
    setResult(null);
    try {
      const formData = new FormData();
      formData.append('source', sourceFile);
      formData.append('target', targetFile);
      const user = getUsername();
      const res = await fetch('/api/excel/compare-upload', {
        method: 'POST',
        body: formData,
        headers: user ? { 'X-User': user } : {},
      });
      if (!res.ok) throw new Error(await res.text() || `HTTP ${res.status}`);
      const data = await res.json();
      setResult(data);
      toast('success', '비교 완료');
    } catch (e) {
      toast('error', `비교 실패: ${e.message}`);
    } finally {
      setComparing(false);
    }
  }, [sourceFile, targetFile, toast]);

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Excel 파일 비교</span>
      </div>
      <div className="text-sm text-muted" style={{ marginBottom: 12 }}>
        두 Excel 파일을 업로드하여 셀 단위로 차이점을 비교합니다.
      </div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>원본 파일</label>
          <input type="file" accept=".xlsx,.xls,.xlsm" onChange={e => setSourceFile(e.target.files?.[0] || null)} style={{ fontSize: 12 }} />
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>비교 대상 파일</label>
          <input type="file" accept=".xlsx,.xls,.xlsm" onChange={e => setTargetFile(e.target.files?.[0] || null)} style={{ fontSize: 12 }} />
        </div>
      </div>
      <button className="btn-primary btn-sm" onClick={compare} disabled={comparing || !sourceFile || !targetFile}>
        {comparing ? '비교 중...' : '비교 실행'}
      </button>
      {result && (
        <div style={{ marginTop: 12 }}>
          <div className="stats-row" style={{ marginBottom: 10 }}>
            <div className="stat-card">
              <div className="stat-value">{result.total_diffs ?? result.diff_count ?? (result.diffs || result.differences || []).length}</div>
              <div className="stat-label">차이점</div>
            </div>
          </div>
          {(result.diffs ?? result.differences ?? []).length > 0 ? (
            <table className="impact-table">
              <thead><tr><th>위치</th><th>원본</th><th>변경</th></tr></thead>
              <tbody>
                {(result.diffs ?? result.differences).slice(0, 50).map((d, i) => (
                  <tr key={i}>
                    <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{d.cell ?? `R${d.row}C${d.col}`}</td>
                    <td className="text-sm">{String(d.source_value ?? d.old_value ?? '-').slice(0, 50)}</td>
                    <td className="text-sm">{String(d.target_value ?? d.new_value ?? '-').slice(0, 50)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div style={{ padding: 12, textAlign: 'center', color: 'var(--color-success)', fontWeight: 600 }}>
              차이점 없음 — 두 파일이 동일합니다.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
