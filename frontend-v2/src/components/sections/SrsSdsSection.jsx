import React, { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { api, post, getUsername } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';
import { defaultCacheRoot } from '../../api.js';

export default function SrsSdsSection({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;

  const [matrix, setMatrix] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadProgress, setLoadProgress] = useState('');  // step description
  const [warnings, setWarnings] = useState([]);           // partial failure warnings
  const matrixCacheRef = useRef(null);                     // cache key + data

  const localDocPaths = useMemo(() => {
    try { return JSON.parse(localStorage.getItem('devops_v2_doc_paths') || '{}'); } catch (_) { return {}; }
  }, []);

  // Merge: SCM linked_docs takes priority, then localStorage
  const scmLinked = analysisResult?.scmList?.[0]?.linked_docs || {};
  const docPaths = useMemo(() => ({
    srs: localDocPaths.srs || scmLinked.srs || '',
    sds: localDocPaths.sds || scmLinked.sds || '',
    hsis: localDocPaths.hsis || scmLinked.hsis || '',
    stp: localDocPaths.stp || scmLinked.stp || '',
  }), [localDocPaths, scmLinked.srs, scmLinked.sds, scmLinked.hsis, scmLinked.stp]);

  // SCM linked docs (for loadMatrix + UI)
  const [linkedDocs, setLinkedDocs] = useState(analysisResult?.scmList?.[0]?.linked_docs || {});
  useEffect(() => {
    if (!linkedDocs.sts && !linkedDocs.suts) {
      api('/api/scm/list').then(d => {
        const items = d?.items || (Array.isArray(d) ? d : []);
        if (items.length > 0 && items[0].linked_docs) setLinkedDocs(items[0].linked_docs);
      }).catch(() => {});
    }
  }, []);

  const loadMatrix = useCallback(async (forceRefresh = false) => {
    // Ensure linkedDocs is loaded from SCM before proceeding
    let activeDocs = linkedDocs;
    if (!activeDocs.sts && !activeDocs.suts) {
      try {
        const scmData = await api('/api/scm/list');
        const items = scmData?.items || (Array.isArray(scmData) ? scmData : []);
        if (items.length > 0 && items[0].linked_docs) {
          activeDocs = items[0].linked_docs;
          setLinkedDocs(activeDocs);
        }
      } catch (_) {}
    }

    // Debug: log activeDocs state

    // Cache check: skip API calls if inputs haven't changed
    const cacheKey = JSON.stringify({ srs: docPaths.srs, sds: docPaths.sds, jobUrl: job?.url, sts: activeDocs.sts, suts: activeDocs.suts, sits: activeDocs.sits });
    if (!forceRefresh && matrixCacheRef.current?.key === cacheKey && matrixCacheRef.current?.data) {
      setMatrix(matrixCacheRef.current.data);
      toast('info', '캐시된 매트릭스를 사용합니다. 새로고침하려면 버튼을 다시 클릭하세요.');
      return;
    }

    setLoading(true);
    setWarnings([]);
    const stepWarnings = [];
    const dataSources = [];  // track which sources contributed

    try {
      // Step 1: Get requirements from SRS
      setLoadProgress('요구사항 추출 중...');
      const form = new FormData();
      if (docPaths.srs) form.append('req_paths', docPaths.srs);
      const scm = analysisResult?.scmList?.[0];
      if (scm?.source_root) form.append('source_root', scm.source_root);

      let reqItems = [];
      let mappingPairs = [];
      try {
        const user = getUsername();
        const previewRes = await fetch('/api/jenkins/uds/requirements-preview', {
          method: 'POST', body: form,
          headers: user ? { 'X-User': user } : {},
        });
        if (previewRes.ok) {
          const previewData = await previewRes.json();
          reqItems = previewData?.preview?.items || [];
          mappingPairs = previewData?.traceability?.mapping_pairs
            || previewData?.mapping || [];
        }
      } catch (e) {
        stepWarnings.push(`요구사항 미리보기 실패: ${e.message}`);
        toast('warning', `요구사항 미리보기 실패: ${e.message}`);
      }

      // Step 2a: Extract func→req mapping from UDS document
      setLoadProgress('UDS 함수 매핑 추출 중...');
      if (mappingPairs.length === 0 && activeDocs.uds) {
        try {
          const udsMapping = await post('/api/jenkins/uds/extract-mapping', {
            uds_path: activeDocs.uds,
          });
          mappingPairs = udsMapping?.mapping_pairs || [];
          if (mappingPairs.length > 0) {
            toast('info', `UDS에서 ${mappingPairs.length}개 매핑 추출`);
          }
        } catch (e) {
          stepWarnings.push(`UDS 매핑 추출 실패: ${e.message}`);
        }
      }

      // Step 2b: Extract SDS component→requirement mapping
      let sdsPairs = [];
      if (docPaths.sds || activeDocs.sds) {
        setLoadProgress('SDS 컴포넌트 매핑 추출 중...');
        try {
          const sdsData = await post('/api/jenkins/sds/extract-mapping', {
            sds_path: docPaths.sds || activeDocs.sds,
          });
          sdsPairs = sdsData?.sds_pairs || [];
          if (sdsPairs.length > 0) {
            dataSources.push(`SDS: ${sdsPairs.length}개 매핑`);
          }
        } catch (e) {
          stepWarnings.push(`SDS 매핑 추출 실패: ${e.message}`);
        }
      }

      // Step 3: Collect test rows — priority: STS > SUTS > SITS > VectorCAST
      // STS/SUTS/SITS are exact matches; VectorCAST is fuzzy (function-name based)
      let vcastRows = [];
      let sitsRows = [];
      const exactCoveredReqs = new Set();  // all exact-covered reqs (for display)
      const stsSutsCoveredReqs = new Set(); // only STS+SUTS covered (for VectorCAST filter)

      // 3a. STS traceability (요구사항↔TC 직접 매핑 — 가장 정확, confidence=exact)
      if (activeDocs.sts) {
        setLoadProgress('STS 추적성 추출 중...');
        try {
          const stsData = await post('/api/jenkins/sts/extract-traceability', { path: activeDocs.sts, doc_type: 'sts' });
          if (stsData?.vcast_rows?.length) {
            for (const row of stsData.vcast_rows) {
              vcastRows.push({ ...row, source: row.source || 'STS', confidence: 'exact' });
              if (row.requirement_id) {
                exactCoveredReqs.add(row.requirement_id.toUpperCase());
                stsSutsCoveredReqs.add(row.requirement_id.toUpperCase());
              }
            }
            dataSources.push(`STS: ${stsData.vcast_rows.length}건`);
          }
        } catch (e) {
          stepWarnings.push(`STS 추출 실패: ${e.message}`);
        }
      }

      // 3b. SUTS traceability (confidence=exact)
      if (activeDocs.suts) {
        setLoadProgress('SUTS 추적성 추출 중...');
        try {
          const sutsData = await post('/api/jenkins/sts/extract-traceability', { path: activeDocs.suts, doc_type: 'suts' });
          if (sutsData?.vcast_rows?.length) {
            for (const row of sutsData.vcast_rows) {
              vcastRows.push({ ...row, source: row.source || 'SUTS', confidence: 'exact' });
              if (row.requirement_id) {
                exactCoveredReqs.add(row.requirement_id.toUpperCase());
                stsSutsCoveredReqs.add(row.requirement_id.toUpperCase());
              }
            }
            dataSources.push(`SUTS: ${sutsData.vcast_rows.length}건`);
          }
        } catch (e) {
          stepWarnings.push(`SUTS 추출 실패: ${e.message}`);
        }
      }

      // 3c. SITS traceability (통합 테스트, confidence=exact)
      if (activeDocs.sits) {
        setLoadProgress('SITS 추적성 추출 중...');
        try {
          const sitsData = await post('/api/jenkins/sits/extract-traceability', { path: activeDocs.sits });
          if (sitsData?.vcast_rows?.length) {
            sitsRows = sitsData.vcast_rows.map(r => ({ ...r, source: r.source || 'SITS', confidence: 'exact' }));
            for (const row of sitsRows) {
              if (row.requirement_id) exactCoveredReqs.add(row.requirement_id.toUpperCase());
            }
            dataSources.push(`SITS: ${sitsData.vcast_rows.length}건`);
          }
        } catch (e) {
          stepWarnings.push(`SITS 추출 실패: ${e.message}`);
        }
      }

      // 3d. VectorCAST (함수 기반, confidence=fuzzy)
      // Only add VectorCAST rows for req IDs NOT already covered by STS/SUTS/SITS
      setLoadProgress('VectorCAST 데이터 수집 중...');
      try {
        const ragData = await post('/api/jenkins/report/vectorcast-rag', {
          job_url: job.url,
          cache_root: cacheRoot,
          build_selector: cfg.buildSelector || 'lastSuccessfulBuild',
        });
        const rawRows = ragData?.data?.test_rows || [];

        const funcToReqs = {};
        for (const mp of mappingPairs) {
          for (const fn of (mp.source_ids || [])) {
            if (!funcToReqs[fn]) funcToReqs[fn] = [];
            funcToReqs[fn].push(mp.requirement_id);
          }
        }

        let vcastAdded = 0;
        for (const row of rawRows) {
          const fn = row.subprogram || '';
          const reqs = funcToReqs[fn] || [];
          for (const rid of reqs) {
            if (stsSutsCoveredReqs.has((rid || '').toUpperCase())) continue;
            vcastRows.push({ ...row, requirement_id: rid, testcase: fn, source: 'VectorCAST', confidence: 'fuzzy' });
            vcastAdded++;
          }
        }
        if (vcastAdded > 0) dataSources.push(`VectorCAST: ${vcastAdded}건`);
      } catch (e) {
        stepWarnings.push(`VectorCAST 수집 실패: ${e.message}`);
      }

      // Warn if no data sources contributed
      if (reqItems.length === 0) {
        stepWarnings.push('SRS에서 요구사항을 추출하지 못했습니다. SRS 경로를 확인하세요.');
      }
      if (vcastRows.length === 0 && sitsRows.length === 0 && mappingPairs.length === 0 && sdsPairs.length === 0) {
        stepWarnings.push('설계/테스트 매핑 데이터가 없습니다. SDS/UDS/STS/SUTS/SITS/VectorCAST 연결을 확인하세요.');
      }

      // Step 4: Generate full traceability matrix (V-model 6-level)
      setLoadProgress(`매트릭스 생성 중 (${reqItems.length}개 요구사항)...`);
      const data = await post('/api/jenkins/uds/traceability-matrix', {
        requirement_items: reqItems,
        mapping_pairs: mappingPairs,
        vcast_rows: vcastRows,
        sds_pairs: sdsPairs,
        sits_rows: sitsRows,
      });
      // Attach metadata
      data._dataSources = dataSources;
      setMatrix(data);
      matrixCacheRef.current = { key: cacheKey, data };
      if (dataSources.length > 0) {
        toast('success', `매트릭스 생성 완료: ${dataSources.join(', ')}`);
      }
    } catch (e) {
      toast('error', `추적성 매트릭스 조회 실패: ${e.message}`);
    } finally {
      setLoading(false);
      setLoadProgress('');
      if (stepWarnings.length > 0) setWarnings(stepWarnings);
    }
  }, [job, cfg, cacheRoot, docPaths, linkedDocs, toast]);

  const impactData = analysisResult?.impactData;
  const impacts = impactData?.impacts ?? impactData?.impact_items ?? [];
  const changedFiles = impactData?.changed_files ?? [];
  const impactedDocs = impactData?.impacted_docs ?? impactData?.impacted_documents ?? [];

  // Linked doc entries for display
  const linkedDocEntries = useMemo(() => {
    if (!linkedDocs || typeof linkedDocs !== 'object') return [];
    return Object.entries(linkedDocs).filter(([, v]) => v);
  }, [linkedDocs]);

  return (
    <div>
      {/* Input doc status */}
      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">입력 문서 현황</span>
        </div>
        <div className="field-group">
          {[
            { label: 'SRS', path: docPaths.srs, fromScm: !localDocPaths.srs && !!scmLinked.srs },
            { label: 'SDS', path: docPaths.sds, fromScm: !localDocPaths.sds && !!scmLinked.sds },
            { label: 'HSIS', path: docPaths.hsis, fromScm: !localDocPaths.hsis && !!scmLinked.hsis },
            { label: 'STP', path: docPaths.stp, fromScm: !localDocPaths.stp && !!scmLinked.stp },
          ].map(({ label, path, fromScm }) => (
            <div key={label} className="artifact-item" style={{ background: 'var(--bg)' }}>
              <span className="pill pill-purple" style={{ minWidth: 40, textAlign: 'center' }}>{label}</span>
              {path ? (
                <>
                  <span className="artifact-name" title={path}>
                    {path.split(/[\\/]/).pop()}
                  </span>
                  {fromScm && <span className="pill pill-info" style={{ fontSize: 9 }}>SCM</span>}
                  <StatusBadge tone="success">등록됨</StatusBadge>
                </>
              ) : (
                <>
                  <span className="text-muted text-sm">설정 탭 또는 SCM에서 경로를 등록하세요</span>
                  <StatusBadge tone="neutral">미등록</StatusBadge>
                </>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Linked docs from SCM registry */}
      {linkedDocEntries.length > 0 && (
        <div className="panel mt-3">
          <div className="panel-header">
            <span className="panel-title">SCM 연결 문서</span>
            <StatusBadge tone="info">{linkedDocEntries.length}건</StatusBadge>
          </div>
          <div className="field-group">
            {linkedDocEntries.map(([docType, docPath]) => {
              const fileName = typeof docPath === 'string'
                ? docPath.split('/').pop().split('\\').pop()
                : docPath?.name ?? String(docPath);
              const fullPath = typeof docPath === 'string' ? docPath : docPath?.path ?? String(docPath);
              return (
                <div key={docType} className="artifact-item" style={{ background: 'var(--bg)' }}>
                  <span className="pill pill-purple" style={{ minWidth: 44, textAlign: 'center' }}>
                    {docType.toUpperCase()}
                  </span>
                  <span className="artifact-name" title={fullPath}>{fileName}</span>
                  <span className="text-muted text-sm" style={{ marginLeft: 'auto', flexShrink: 0 }}>
                    {fullPath}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Impact data: changed files and impacted documents */}
      {impactData && (changedFiles.length > 0 || impactedDocs.length > 0) && (
        <div className="panel mt-3">
          <div className="panel-header">
            <span className="panel-title">영향 분석 결과</span>
          </div>

          {/* Stats row */}
          <div className="stats-row" style={{ marginBottom: 12 }}>
            <div className="stat-card">
              <div className="text-muted text-sm">변경 파일</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{changedFiles.length}</div>
            </div>
            <div className="stat-card">
              <div className="text-muted text-sm">영향 문서</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{impactedDocs.length}</div>
            </div>
            {impacts.length > 0 && (
              <div className="stat-card">
                <div className="text-muted text-sm">영향 요구사항</div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{impacts.length}</div>
              </div>
            )}
          </div>

          {/* Changed files */}
          {changedFiles.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>변경 파일</div>
              <div className="artifact-list">
                {changedFiles.map((f, i) => {
                  const path = typeof f === 'string' ? f : f.path;
                  const action = typeof f === 'object' ? f.action : undefined;
                  return (
                    <div key={i} className="artifact-item">
                      <span style={{ fontSize: 11, marginRight: 4 }}>
                        {action === 'A' ? '🟢' : action === 'D' ? '🔴' : '🟡'}
                      </span>
                      <span className="artifact-name" style={{ fontFamily: 'monospace', fontSize: 11 }}>{path}</span>
                      {action && <span className="pill pill-neutral">{action}</span>}
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Impacted documents */}
          {impactedDocs.length > 0 && (
            <div>
              <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>영향받는 문서</div>
              <table className="impact-table">
                <thead>
                  <tr><th>문서명</th><th>유형</th><th>상태</th></tr>
                </thead>
                <tbody>
                  {impactedDocs.map((doc, i) => {
                    const name = doc.name ?? doc.doc_name ?? doc.path ?? '-';
                    const type = doc.type ?? doc.doc_type ?? '-';
                    const status = doc.status ?? 'unknown';
                    const tone = status === 'updated' ? 'success'
                      : status === 'outdated' ? 'danger'
                      : status === 'review_needed' ? 'warning'
                      : 'neutral';
                    return (
                      <tr key={i}>
                        <td className="text-sm">{name}</td>
                        <td><span className="pill pill-purple">{type.toUpperCase()}</span></td>
                        <td><StatusBadge tone={tone}>{status}</StatusBadge></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Impact summary - requirement level */}
      {impacts.length > 0 && (
        <div className="panel mt-3">
          <div className="panel-header">
            <span className="panel-title">영향받는 요구사항</span>
            <StatusBadge tone="warning">{impacts.length}건</StatusBadge>
          </div>
          <table className="impact-table">
            <thead>
              <tr><th>요구사항 ID</th><th>설명</th><th>문서</th><th>영향 수준</th></tr>
            </thead>
            <tbody>
              {impacts.map((item, i) => (
                <tr key={i}>
                  <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{item.req_id ?? item.id ?? '-'}</td>
                  <td className="text-sm">{item.description ?? item.desc ?? '-'}</td>
                  <td className="text-sm">{item.doc ?? item.document ?? '-'}</td>
                  <td>
                    <StatusBadge tone={item.level === 'high' ? 'danger' : item.level === 'medium' ? 'warning' : 'info'}>
                      {item.level ?? '-'}
                    </StatusBadge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Traceability matrix */}
      <div className="panel mt-3">
        <div className="panel-header">
          <span className="panel-title">추적성 매트릭스</span>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {loading && loadProgress && (
              <span className="text-muted text-sm">{loadProgress}</span>
            )}
            <button className="btn-sm" onClick={() => loadMatrix(false)} disabled={loading}>
              {loading ? <span className="spinner" /> : '매트릭스 생성'}
            </button>
            {matrix && (
              <button className="btn-sm" onClick={() => loadMatrix(true)} disabled={loading}
                title="캐시를 무시하고 새로 생성" style={{ fontSize: 11 }}>
                새로고침
              </button>
            )}
          </div>
        </div>

        {/* Partial failure warnings */}
        {warnings.length > 0 && (
          <div style={{ margin: '8px 0', padding: '8px 12px', background: '#fef3c7', border: '1px solid #fcd34d', borderRadius: 6, fontSize: 12 }}>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>일부 데이터 소스에서 경고가 발생했습니다:</div>
            {warnings.map((w, i) => <div key={i} style={{ color: '#92400e' }}>• {w}</div>)}
          </div>
        )}

        {matrix ? (
          <TraceMatrix matrix={matrix} />
        ) : (
          <div className="text-muted text-sm">
            SRS/SDS 경로를 설정 탭에서 등록한 후 매트릭스 생성 버튼을 클릭하세요.
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Coverage helpers ── */
const COVERAGE_COLORS = {
  covered:   { bg: '#dcfce7', fg: '#166534', border: '#86efac' },
  partial:   { bg: '#fef9c3', fg: '#854d0e', border: '#fde047' },
  uncovered: { bg: '#fee2e2', fg: '#991b1b', border: '#fca5a5' },
};

function coverageTone(status) {
  if (status === 'covered')   return 'success';
  if (status === 'partial')   return 'warning';
  if (status === 'uncovered') return 'danger';
  return 'neutral';
}

function CoverageBar({ covered, partial, total, onFilter }) {
  if (!total) return null;
  const covPct = Math.round((covered / total) * 100);
  const partPct = Math.round((partial / total) * 100);
  const uncovPct = 100 - covPct - partPct;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 200 }}>
      <div style={{ display: 'flex', height: 12, borderRadius: 4, overflow: 'hidden', background: '#e5e7eb', cursor: 'pointer' }}>
        {covPct > 0 && <div onClick={() => onFilter?.('covered')} title="Covered만 보기" style={{ width: `${covPct}%`, background: COVERAGE_COLORS.covered.border }} />}
        {partPct > 0 && <div onClick={() => onFilter?.('partial')} title="Partial만 보기" style={{ width: `${partPct}%`, background: COVERAGE_COLORS.partial.border }} />}
        {uncovPct > 0 && <div onClick={() => onFilter?.('uncovered')} title="Uncovered만 보기" style={{ width: `${uncovPct}%`, background: COVERAGE_COLORS.uncovered.border }} />}
      </div>
      <div className="text-sm text-muted" style={{ display: 'flex', gap: 10 }}>
        <span style={{ color: COVERAGE_COLORS.covered.fg, cursor: 'pointer' }} onClick={() => onFilter?.('covered')}>Covered {covPct}%</span>
        {partial > 0 && <span style={{ color: COVERAGE_COLORS.partial.fg, cursor: 'pointer' }} onClick={() => onFilter?.('partial')}>Partial {partPct}%</span>}
        <span style={{ color: COVERAGE_COLORS.uncovered.fg, cursor: 'pointer' }} onClick={() => onFilter?.('uncovered')}>Uncovered {uncovPct}%</span>
        <span style={{ cursor: 'pointer', opacity: 0.5 }} onClick={() => onFilter?.('all')}>전체</span>
      </div>
    </div>
  );
}

// Derive coverage status from row data (pure function, shared across useMemo/filters)
function deriveStatus(r) {
  const hasSds = (r.sds_components ?? []).length > 0;
  const hasSrc = (r.source_ids ?? []).length > 0;
  const hasTest = (r.test_ids ?? r.tests ?? []).length > 0;
  // Full: design (SDS or UDS) + test
  if ((hasSds || hasSrc) && hasTest) return 'covered';
  // Partial: any one layer present
  if (hasSds || hasSrc || hasTest) return 'partial';
  if (r.status && r.status !== 'uncovered') return r.status;
  return 'uncovered';
}

const PAGE_SIZES = [30, 50, 100];
const SOURCE_ICONS = { STS: 'S', SUTS: 'U', SITS: 'I', VectorCAST: 'V' };
const SOURCE_COLORS = { STS: '#2563eb', SUTS: '#7c3aed', SITS: '#0891b2', VectorCAST: '#ea580c' };
const CONFIDENCE_LABELS = { exact: 'Exact', direct: 'Direct', indirect: 'Indirect', fuzzy: 'Fuzzy', mixed: 'Mixed' };
const CONFIDENCE_COLORS = { exact: '#16a34a', direct: '#16a34a', indirect: '#d97706', fuzzy: '#9ca3af', mixed: '#2563eb' };

function TraceMatrix({ matrix }) {
  const inner = matrix?.matrix ?? matrix;
  const rows = Array.isArray(inner?.rows) ? inner.rows : (Array.isArray(inner?.items) ? inner.items : []);
  const summary = inner?.summary ?? matrix?.summary;
  const dataSources = matrix?._dataSources || [];

  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [sourceFilter, setSourceFilter] = useState('all');   // STS/SUTS/VectorCAST
  const [reqTypeFilter, setReqTypeFilter] = useState('all'); // SwRS/SwTR/etc
  const [testResultFilter, setTestResultFilter] = useState('all'); // pass/fail/all
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);
  const [currentPage, setCurrentPage] = useState(0);
  const [sortKey, setSortKey] = useState(null);    // 'req_id' | 'func_count' | 'test_count' | 'status'
  const [sortAsc, setSortAsc] = useState(true);
  const [expandedReqId, setExpandedReqId] = useState(null); // expanded row by requirement_id

  // Reset page when rows change (e.g., new matrix data)
  useEffect(() => { setCurrentPage(0); setExpandedReqId(null); }, [rows]);

  // Extract unique requirement types (SwRS, SwTR, SyRS, etc.)
  const reqTypes = useMemo(() => {
    const types = new Set();
    for (const r of rows) {
      const id = r.requirement_id ?? r.req_id ?? r.id ?? '';
      const m = id.match(/^(Sw[A-Z]{1,4}|Sy[A-Z]{1,4})/i);
      if (m) types.add(m[1].toUpperCase());
    }
    return [...types].sort();
  }, [rows]);

  // Extract unique data sources present in rows
  const availableSources = useMemo(() => {
    const srcs = new Set();
    for (const r of rows) {
      for (const t of (r.tests || [])) {
        if (t.source) srcs.add(t.source);
      }
    }
    return [...srcs].sort();
  }, [rows]);

  // Coverage statistics
  const coverage = useMemo(() => {
    if (!rows.length) return null;
    let covered = 0, partial = 0, uncovered = 0;
    let partialWithDesign = 0; // partial 중 설계(SDS/UDS)가 있는 것
    for (const r of rows) {
      const st = deriveStatus(r);
      if (st === 'covered') covered++;
      else if (st === 'partial') {
        partial++;
        const hasSds = (r.sds_components ?? []).length > 0;
        const hasSrc = (r.source_ids ?? []).length > 0;
        if (hasSds || hasSrc) partialWithDesign++;
      }
      else uncovered++;
    }
    const total = rows.length;
    // SW 구현 대상: 설계가 존재하는 요구사항 (covered + partial with design)
    const designTotal = covered + partialWithDesign;
    return { covered, partial, uncovered, total, partialWithDesign, designTotal, pct: Math.round((covered / total) * 100) };
  }, [rows]);

  // Filter + sort
  const filtered = useMemo(() => {
    let result = rows;

    // Status filter
    if (statusFilter !== 'all') {
      result = result.filter(r => deriveStatus(r) === statusFilter);
    }

    // Source filter — show only rows that have tests from the selected source
    if (sourceFilter !== 'all') {
      result = result.filter(r =>
        (r.tests || []).some(t => t.source === sourceFilter)
      );
    }

    // Requirement type filter
    if (reqTypeFilter !== 'all') {
      result = result.filter(r => {
        const id = (r.requirement_id ?? r.req_id ?? r.id ?? '').toUpperCase();
        return id.startsWith(reqTypeFilter);
      });
    }

    // Test result filter
    if (testResultFilter === 'pass') {
      result = result.filter(r => (r.pass_count ?? 0) > 0);
    } else if (testResultFilter === 'fail') {
      result = result.filter(r => (r.fail_count ?? 0) > 0);
    } else if (testResultFilter === 'no_test') {
      result = result.filter(r => (r.test_count ?? 0) === 0);
    }

    // Text search
    if (searchTerm.trim()) {
      const q = searchTerm.trim().toLowerCase();
      result = result.filter(r =>
        (r.requirement_id ?? r.req_id ?? r.id ?? '').toLowerCase().includes(q) ||
        (r.source_ids ?? []).join(' ').toLowerCase().includes(q) ||
        (r.test_ids ?? []).join(' ').toLowerCase().includes(q)
      );
    }

    // Sort
    if (sortKey) {
      result = [...result].sort((a, b) => {
        let va, vb;
        if (sortKey === 'req_id') {
          va = a.requirement_id ?? a.req_id ?? a.id ?? '';
          vb = b.requirement_id ?? b.req_id ?? b.id ?? '';
          return sortAsc ? va.localeCompare(vb) : vb.localeCompare(va);
        }
        if (sortKey === 'func_count') {
          va = (a.source_ids ?? []).length; vb = (b.source_ids ?? []).length;
        } else if (sortKey === 'test_count') {
          va = a.test_count ?? 0; vb = b.test_count ?? 0;
        } else if (sortKey === 'status') {
          const order = { covered: 0, partial: 1, uncovered: 2 };
          va = order[deriveStatus(a)] ?? 3; vb = order[deriveStatus(b)] ?? 3;
        } else {
          va = 0; vb = 0;
        }
        return sortAsc ? va - vb : vb - va;
      });
    }

    return result;
  }, [rows, searchTerm, statusFilter, sourceFilter, reqTypeFilter, testResultFilter, sortKey, sortAsc]);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(currentPage, totalPages - 1);
  const displayedRows = filtered.slice(safePage * pageSize, (safePage + 1) * pageSize);

  // Sort toggle handler
  const toggleSort = (key) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(true); }
  };
  const sortIcon = (key) => sortKey === key ? (sortAsc ? ' \u25B2' : ' \u25BC') : '';

  // CSV export (RFC 4180 compliant)
  const csvEscape = (val) => {
    const s = String(val ?? '');
    return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const exportCSV = () => {
    const header = ['요구사항 ID', 'SDS 컴포넌트(T1)', 'UDS 함수(T2)', '함수 수', 'STS TC(T3)', 'SUTS TC(T4)', 'SITS TC(T5)', 'VectorCAST', '테스트 수', 'Pass', 'Fail', '상태', '신뢰도'];
    const csvRows = [header.join(',')];
    for (const r of filtered) {
      const status = deriveStatus(r);
      const rawTests = Array.isArray(r.tests) ? r.tests : [];
      const stsCount = (r.sts_tests ?? rawTests.filter(t => t.source === 'STS')).length;
      const sutsCount = (r.suts_tests ?? rawTests.filter(t => t.source === 'SUTS')).length;
      const sitsCount = (r.sits_tests ?? rawTests.filter(t => t.source === 'SITS')).length;
      const vcastCount = rawTests.filter(t => t.source === 'VectorCAST').length;
      csvRows.push([
        csvEscape(r.requirement_id ?? ''),
        csvEscape((r.sds_components ?? []).join('; ')),
        csvEscape((r.source_ids ?? []).join('; ')),
        (r.source_ids ?? []).length,
        stsCount,
        sutsCount,
        sitsCount,
        vcastCount,
        r.test_count ?? 0,
        r.pass_count ?? 0,
        r.fail_count ?? 0,
        status,
        r.confidence ?? '-',
      ].join(','));
    }
    const blob = new Blob(['\uFEFF' + csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `traceability_matrix_${new Date().toISOString().slice(0,10)}.csv`;
    a.click(); URL.revokeObjectURL(url);
  };

  if (!rows.length) {
    return (
      <div className="text-muted text-sm" style={{ padding: 12, background: 'var(--bg)', borderRadius: 6 }}>
        매트릭스 데이터에 요구사항이 없습니다. SRS 경로를 확인하세요.
      </div>
    );
  }

  return (
    <div>
      {/* Coverage summary table */}
      {coverage && (
        <div style={{ marginBottom: 16, border: '1px solid var(--border)', borderRadius: 8, overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px', background: 'var(--bg)', borderBottom: '1px solid var(--border)', fontWeight: 600, fontSize: 13, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span>추적성 요약</span>
            {summary?.total_tests > 0 && (
              <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--text-muted)' }}>
                테스트 {summary.total_pass ?? 0} Pass / {summary.total_fail ?? 0} Fail / {summary.total_tests} Total
              </span>
            )}
          </div>

          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr style={{ background: 'var(--bg)' }}>
                <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>구분</th>
                <th style={{ padding: '8px 12px', textAlign: 'center', borderBottom: '1px solid var(--border)', width: 80 }}>건수</th>
                <th style={{ padding: '8px 12px', textAlign: 'center', borderBottom: '1px solid var(--border)', width: 80 }}>비율</th>
                <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>설명</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td style={{ padding: '6px 12px', fontWeight: 600 }}>전체 요구사항 (SRS)</td>
                <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 700, fontSize: 14 }}>{coverage.total}</td>
                <td style={{ padding: '6px 12px', textAlign: 'center' }}>100%</td>
                <td style={{ padding: '6px 12px', color: 'var(--text-muted)' }}>SRS 문서에서 추출된 요구사항</td>
              </tr>
              <tr style={{ background: COVERAGE_COLORS.covered.bg }}>
                <td style={{ padding: '6px 12px', fontWeight: 600, color: COVERAGE_COLORS.covered.fg }}>
                  Covered (설계+테스트 완료)
                </td>
                <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 700, fontSize: 14, color: COVERAGE_COLORS.covered.fg }}>{coverage.covered}</td>
                <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 600, color: COVERAGE_COLORS.covered.fg }}>{coverage.pct}%</td>
                <td style={{ padding: '6px 12px', fontSize: 11 }}>UDS 소스 매핑 + STS/VectorCAST 테스트 매핑 모두 존재</td>
              </tr>
              {coverage.partial > 0 && (
                <tr style={{ background: COVERAGE_COLORS.partial.bg }}>
                  <td style={{ padding: '6px 12px', fontWeight: 600, color: COVERAGE_COLORS.partial.fg }}>
                    Partial (테스트만 존재)
                  </td>
                  <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 700, fontSize: 14, color: COVERAGE_COLORS.partial.fg }}>{coverage.partial}</td>
                  <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 600, color: COVERAGE_COLORS.partial.fg }}>{Math.round(coverage.partial / coverage.total * 100)}%</td>
                  <td style={{ padding: '6px 12px', fontSize: 11 }}>STS 테스트 매핑 있으나 UDS 소스 매핑 없음 (비기능/HW/시스템 레벨 요구사항)</td>
                </tr>
              )}
              {coverage.uncovered > 0 && (
                <tr style={{ background: COVERAGE_COLORS.uncovered.bg }}>
                  <td style={{ padding: '6px 12px', fontWeight: 600, color: COVERAGE_COLORS.uncovered.fg }}>
                    Uncovered (미추적)
                  </td>
                  <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 700, fontSize: 14, color: COVERAGE_COLORS.uncovered.fg }}>{coverage.uncovered}</td>
                  <td style={{ padding: '6px 12px', textAlign: 'center', fontWeight: 600, color: COVERAGE_COLORS.uncovered.fg }}>{Math.round(coverage.uncovered / coverage.total * 100)}%</td>
                  <td style={{ padding: '6px 12px', fontSize: 11 }}>설계 및 테스트 매핑 모두 없음</td>
                </tr>
              )}
            </tbody>
            <tfoot>
              <tr style={{ borderTop: '2px solid var(--border)', background: 'var(--bg)' }}>
                <td style={{ padding: '8px 12px', fontWeight: 700 }}>SW 구현 대상 커버리지</td>
                <td style={{ padding: '8px 12px', textAlign: 'center', fontWeight: 700, fontSize: 16, color: 'var(--color-success)' }}>
                  {coverage.covered}/{coverage.designTotal}
                </td>
                <td style={{ padding: '8px 12px', textAlign: 'center', fontWeight: 700, fontSize: 16, color: 'var(--color-success)' }}>
                  {coverage.designTotal > 0 ? Math.round(coverage.covered / coverage.designTotal * 100) : 0}%
                </td>
                <td style={{ padding: '8px 12px', fontSize: 11, color: 'var(--text-muted)' }}>
                  설계(SDS/UDS) 매핑이 존재하는 요구사항 중 검증 완료 비율
                </td>
              </tr>
              <tr style={{ background: 'var(--bg)' }}>
                <td style={{ padding: '8px 12px', fontWeight: 700 }}>테스트 추적 커버리지</td>
                <td style={{ padding: '8px 12px', textAlign: 'center', fontWeight: 700, fontSize: 16, color: 'var(--color-success)' }}>
                  {summary?.mapped_test_count ?? (coverage.covered + coverage.partial)}/{coverage.total}
                </td>
                <td style={{ padding: '8px 12px', textAlign: 'center', fontWeight: 700, fontSize: 16, color: 'var(--color-success)' }}>
                  {Math.round(((summary?.mapped_test_count ?? (coverage.covered + coverage.partial)) / coverage.total) * 100)}%
                </td>
                <td style={{ padding: '8px 12px', fontSize: 11, color: 'var(--text-muted)' }}>
                  STS/SUTS/VectorCAST 테스트 매핑 기준
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      )}

      {/* Coverage bar */}
      {coverage && (
        <div style={{ marginBottom: 12 }}>
          <CoverageBar covered={coverage.covered} partial={coverage.partial} total={coverage.total}
            onFilter={(status) => { setStatusFilter(status === 'all' ? 'all' : status); setCurrentPage(0); }} />
        </div>
      )}

      {/* Data sources */}
      {summary && (
        <details style={{ marginBottom: 12 }}>
          <summary className="text-sm" style={{ cursor: 'pointer', fontWeight: 600 }}>데이터 소스 상세</summary>
          {(() => {
            const total = coverage.total || 1;
            const traceRows = [
              { label: 'T1: SRS \u2192 SDS', type: '\uC124\uACC4', count: summary.mapped_sds_count, desc: 'SDS SwCom \uB9E4\uD551' },
              { label: 'T2: SDS \u2192 UDS', type: '\uC0C1\uC138\uC124\uACC4', count: summary.mapped_source_count ?? coverage.covered, desc: 'UDS \uD568\uC218 \uB9E4\uD551' },
              { label: 'T3: SRS \u2192 STS', type: '\uC9C1\uC811', count: summary.mapped_sts_count, direct: summary.mapped_sts_direct, desc: 'SW \uD14C\uC2A4\uD2B8' },
              { label: 'T4: UDS \u2192 SUTS', type: '\uC9C1\uC811+\uACBD\uC720', count: summary.mapped_suts_count, direct: summary.mapped_suts_direct, indirect: summary.mapped_suts_indirect, desc: '\uB2E8\uC704 \uD14C\uC2A4\uD2B8' },
              { label: 'T5: SDS \u2192 SITS', type: '\uC9C1\uC811+\uACBD\uC720', count: summary.mapped_sits_count, direct: summary.mapped_sits_direct, indirect: summary.mapped_sits_indirect, desc: '\uD1B5\uD569 \uD14C\uC2A4\uD2B8' },
              { label: '\uC804\uCCB4 \uAC80\uC99D', type: '\uD1B5\uD569', count: summary.mapped_test_count ?? (coverage.covered + coverage.partial), desc: 'STS+SUTS+SITS+VectorCAST' },
            ];
            const statusDot = (pct) => {
              const color = pct > 70 ? '#16a34a' : pct >= 30 ? '#d97706' : '#dc2626';
              return <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: color, marginRight: 4 }} />;
            };
            return (
              <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse', marginTop: 8 }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid var(--border)', background: 'var(--bg)' }}>
                    <th style={{ textAlign: 'left', padding: '6px 8px' }}>{'\uCD94\uC801 \uAD00\uACC4'}</th>
                    <th style={{ textAlign: 'center', padding: '6px 8px' }}>{'\uB9E4\uD551 \uC720\uD615'}</th>
                    <th style={{ textAlign: 'center', padding: '6px 8px' }}>{'\uCEE4\uBC84\uB41C \uC694\uAD6C\uC0AC\uD56D'}</th>
                    <th style={{ textAlign: 'center', padding: '6px 8px' }}>{'\uBE44\uC728'}</th>
                    <th style={{ textAlign: 'center', padding: '6px 8px' }}>{'\uC0C1\uD0DC'}</th>
                  </tr>
                </thead>
                <tbody>
                  {traceRows.map((tr, i) => {
                    const cnt = tr.count ?? 0;
                    const pct = Math.round((cnt / total) * 100);
                    const typeDetail = tr.indirect != null
                      ? `${tr.type} (${tr.direct ?? 0}\uC9C1\uC811 + ${tr.indirect ?? 0}\uACBD\uC720)`
                      : tr.direct != null ? `${tr.type} (${tr.direct}\uC9C1\uC811)` : tr.type;
                    return (
                      <tr key={i} style={{ borderBottom: '1px solid var(--border)', background: i === traceRows.length - 1 ? 'var(--bg)' : undefined }}>
                        <td style={{ padding: '5px 8px', fontWeight: i === traceRows.length - 1 ? 700 : 400 }}>{tr.label}</td>
                        <td style={{ padding: '5px 8px', textAlign: 'center', fontSize: 10 }}>{typeDetail}</td>
                        <td style={{ padding: '5px 8px', textAlign: 'center', fontWeight: 600 }}>{cnt} / {total}</td>
                        <td style={{ padding: '5px 8px', textAlign: 'center', fontWeight: 600 }}>{pct}%</td>
                        <td style={{ padding: '5px 8px', textAlign: 'center' }}>{statusDot(pct)}{pct > 70 ? 'Good' : pct >= 30 ? 'Warn' : 'Low'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            );
          })()}
          {/* Source breakdown */}
          {summary?.source_stats && typeof summary.source_stats === 'object' && Object.keys(summary.source_stats).length > 0 && (
            <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
              {Object.entries(summary.source_stats).map(([src, cnt]) => (
                <div key={src} style={{ padding: '4px 10px', borderRadius: 12, fontSize: 11, fontWeight: 600,
                  background: (SOURCE_COLORS[src] || '#6b7280') + '18', color: SOURCE_COLORS[src] || '#6b7280',
                  border: `1px solid ${SOURCE_COLORS[src] || '#6b7280'}40` }}>
                  {SOURCE_ICONS[src] || src} {src}: {cnt}건
                </div>
              ))}
            </div>
          )}
          {dataSources.length > 0 && (
            <div className="text-muted text-sm" style={{ marginTop: 6 }}>
              수집: {dataSources.join(' | ')}
            </div>
          )}
        </details>
      )}

      {/* Search and filter bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 10, flexWrap: 'wrap', alignItems: 'center' }}>
        <input
          type="text"
          placeholder="요구사항 ID, 함수, 파일 검색..."
          value={searchTerm}
          onChange={e => { setSearchTerm(e.target.value); setCurrentPage(0); }}
          style={{
            flex: 1, minWidth: 160, padding: '6px 10px', fontSize: 13,
            border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)',
            color: 'var(--fg)',
          }}
        />
        <select value={statusFilter} onChange={e => { setStatusFilter(e.target.value); setCurrentPage(0); }}
          style={{ padding: '6px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--fg)' }}>
          <option value="all">전체 상태</option>
          <option value="covered">Covered</option>
          <option value="partial">Partial</option>
          <option value="uncovered">Uncovered</option>
        </select>
        {availableSources.length > 1 && (
          <select value={sourceFilter} onChange={e => { setSourceFilter(e.target.value); setCurrentPage(0); }}
            style={{ padding: '6px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--fg)' }}>
            <option value="all">전체 소스</option>
            {availableSources.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        )}
        {reqTypes.length > 1 && (
          <select value={reqTypeFilter} onChange={e => { setReqTypeFilter(e.target.value); setCurrentPage(0); }}
            style={{ padding: '6px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--fg)' }}>
            <option value="all">전체 타입</option>
            {reqTypes.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        )}
        <select value={testResultFilter} onChange={e => { setTestResultFilter(e.target.value); setCurrentPage(0); }}
          style={{ padding: '6px 8px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)', color: 'var(--fg)' }}>
          <option value="all">테스트 결과</option>
          <option value="pass">Pass 있음</option>
          <option value="fail">Fail 있음</option>
          <option value="no_test">테스트 없음</option>
        </select>
        <button className="btn-sm" onClick={exportCSV} title="CSV 내보내기" style={{ fontSize: 11 }}>
          CSV
        </button>
        <span className="text-muted text-sm">
          {filtered.length}건{filtered.length !== rows.length ? ` / ${rows.length}건` : ''}
        </span>
      </div>

      {/* Matrix table */}
      <div style={{ overflowX: 'auto' }}>
      <table className="impact-table" style={{ minWidth: 950 }}>
        <thead>
          <tr>
            <th rowSpan={2} style={{ verticalAlign: 'middle', width: 100, cursor: 'pointer' }} onClick={() => toggleSort('req_id')}>
              요구사항 ID{sortIcon('req_id')}
            </th>
            <th colSpan={2} style={{ textAlign: 'center', background: '#eff6ff', borderBottom: '1px solid var(--border)', cursor: 'pointer' }} onClick={() => toggleSort('func_count')}>
              설계 (T1,T2){sortIcon('func_count')}
            </th>
            <th colSpan={4} style={{ textAlign: 'center', background: '#f0fdf4', borderBottom: '1px solid var(--border)', cursor: 'pointer' }} onClick={() => toggleSort('test_count')}>
              검증 (T3,T4,T5){sortIcon('test_count')}
            </th>
            <th rowSpan={2} style={{ verticalAlign: 'middle', width: 50, textAlign: 'center' }}>P/F</th>
            <th rowSpan={2} style={{ verticalAlign: 'middle', width: 55, textAlign: 'center' }}>신뢰도</th>
            <th rowSpan={2} style={{ verticalAlign: 'middle', width: 75, cursor: 'pointer' }} onClick={() => toggleSort('status')}>
              상태{sortIcon('status')}
            </th>
          </tr>
          <tr>
            <th style={{ fontSize: 10, background: '#eff6ff' }} title="T1: SRS→SDS">SDS 컴포넌트</th>
            <th style={{ fontSize: 10, background: '#eff6ff' }} title="T2: SDS→UDS">UDS 함수</th>
            <th style={{ fontSize: 10, background: '#f0fdf4' }} title="T3: SRS→STS">STS TC</th>
            <th style={{ fontSize: 10, background: '#f0fdf4' }} title="T4: UDS→SUTS">SUTS TC</th>
            <th style={{ fontSize: 10, background: '#f0fdf4' }} title="T5: SDS→SITS">SITS TC</th>
            <th style={{ fontSize: 10, background: '#f0fdf4' }}>VectorCAST</th>
          </tr>
        </thead>
        <tbody>
          {displayedRows.map((r, idx) => {
            const reqId = r.requirement_id ?? r.req_id ?? r.id ?? `row-${idx}`;
            const status = deriveStatus(r);
            const colors = COVERAGE_COLORS[status] || {};
            const sdsComps = r.sds_components ?? [];
            const srcFuncs = r.source_ids ?? [];
            const rawTests = Array.isArray(r.tests) ? r.tests : [];
            // ISO 26262 추적 관계별 분리: T3(STS), T4(SUTS), T5(SITS)
            const stsOnlyTests = Array.isArray(r.sts_tests) ? r.sts_tests : rawTests.filter(t => t.source === 'STS');
            const sutsOnlyTests = Array.isArray(r.suts_tests) ? r.suts_tests : rawTests.filter(t => t.source === 'SUTS');
            const sitsTests = Array.isArray(r.sits_tests) ? r.sits_tests : rawTests.filter(t => t.source === 'SITS');
            const vcastTests = rawTests.filter(t => t.source === 'VectorCAST');
            const otherTests = rawTests.filter(t => !['STS','SUTS','SITS','VectorCAST'].includes(t.source));
            const stsCount = stsOnlyTests.length;
            const sutsCount = sutsOnlyTests.length;
            const sitsCount = sitsTests.length;
            const vcastCount = vcastTests.length + otherTests.length;
            const passCount = r.pass_count ?? 0;
            const failCount = r.fail_count ?? 0;
            const hasExact = stsCount > 0 || sutsCount > 0 || sitsCount > 0;
            const confidence = r.confidence ?? (hasExact && vcastCount === 0 ? 'exact' : vcastCount > 0 && !hasExact ? 'fuzzy' : hasExact ? 'mixed' : null);
            const isExpanded = expandedReqId === reqId;

            return (
              <React.Fragment key={reqId}>
                <tr style={{ background: colors.bg, cursor: 'pointer' }}
                    onClick={() => setExpandedReqId(isExpanded ? null : reqId)}>
                  <td style={{ fontFamily: 'monospace', fontSize: 11, fontWeight: 600 }}>
                    {isExpanded ? '\u25BC' : '\u25B6'} {reqId}
                  </td>
                  <td style={{ fontSize: 10, maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={sdsComps.join(', ')}>
                    {sdsComps.length > 0
                      ? <><span style={{ fontSize: 9, padding: '1px 5px', borderRadius: 8, background: '#dbeafe', color: '#1e40af', fontWeight: 600 }}>{sdsComps.length}</span> {sdsComps.slice(0, 2).join(', ')}{sdsComps.length > 2 ? '...' : ''}</>
                      : <span className="text-muted">-</span>
                    }
                  </td>
                  <td style={{ fontSize: 10, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={srcFuncs.join(', ')}>
                    {srcFuncs.length > 0
                      ? <><span className="pill pill-info" style={{ fontSize: 9 }}>{srcFuncs.length}</span> {srcFuncs.slice(0, 2).join(', ')}{srcFuncs.length > 2 ? '...' : ''}</>
                      : <span className="text-muted">-</span>
                    }
                  </td>
                  <td style={{ fontSize: 10, textAlign: 'center' }} title="T3: SRS→STS">
                    {stsCount > 0
                      ? <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: SOURCE_COLORS.STS + '20', color: SOURCE_COLORS.STS, fontWeight: 600 }}>{stsCount} TC</span>
                      : <span className="text-muted">-</span>
                    }
                  </td>
                  <td style={{ fontSize: 10, textAlign: 'center' }} title="T4: UDS→SUTS">
                    {sutsCount > 0
                      ? <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: SOURCE_COLORS.SUTS + '20', color: SOURCE_COLORS.SUTS, fontWeight: 600 }} title={`\uC9C1\uC811: ${r.suts_direct || 0}, \uACBD\uC720: ${r.suts_indirect || 0}`}>
                          {sutsCount} TC
                          {r.suts_indirect > 0 && <span style={{ fontSize: 8, color: 'var(--text-muted)' }}> ({r.suts_direct || 0}+{r.suts_indirect || 0})</span>}
                        </span>
                      : <span className="text-muted">-</span>
                    }
                  </td>
                  <td style={{ fontSize: 10, textAlign: 'center' }} title="T5: SDS→SITS">
                    {sitsCount > 0
                      ? <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: SOURCE_COLORS.SITS + '20', color: SOURCE_COLORS.SITS, fontWeight: 600 }} title={`\uC9C1\uC811: ${r.sits_direct || 0}, \uACBD\uC720: ${r.sits_indirect || 0}`}>
                          {sitsCount} TC
                          {r.sits_indirect > 0 && <span style={{ fontSize: 8, color: 'var(--text-muted)' }}> ({r.sits_direct || 0}+{r.sits_indirect || 0})</span>}
                        </span>
                      : <span className="text-muted">-</span>
                    }
                  </td>
                  <td style={{ fontSize: 10, textAlign: 'center' }}>
                    {vcastCount > 0
                      ? <span style={{ fontSize: 9, padding: '1px 6px', borderRadius: 8, background: SOURCE_COLORS.VectorCAST + '20', color: SOURCE_COLORS.VectorCAST, fontWeight: 600 }}>{vcastCount}</span>
                      : <span className="text-muted">-</span>
                    }
                  </td>
                  <td style={{ fontSize: 10, textAlign: 'center' }}>
                    {(passCount > 0 || failCount > 0) ? (
                      <span style={{ fontSize: 9 }}>
                        {passCount > 0 && <span style={{ color: '#16a34a', fontWeight: 600 }}>{passCount}P</span>}
                        {passCount > 0 && failCount > 0 && '/'}
                        {failCount > 0 && <span style={{ color: '#dc2626', fontWeight: 600 }}>{failCount}F</span>}
                      </span>
                    ) : <span className="text-muted">-</span>}
                  </td>
                  <td style={{ fontSize: 9, textAlign: 'center' }}>
                    {confidence && (
                      <span style={{ padding: '1px 5px', borderRadius: 6, fontWeight: 600,
                        color: CONFIDENCE_COLORS[confidence] || '#6b7280',
                        background: (CONFIDENCE_COLORS[confidence] || '#6b7280') + '18' }}>
                        {CONFIDENCE_LABELS[confidence] || confidence}
                      </span>
                    )}
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <StatusBadge tone={coverageTone(status)}>{status}</StatusBadge>
                  </td>
                </tr>

                {/* Expanded detail row — drilldown */}
                {isExpanded && (
                  <tr style={{ background: '#f8fafc' }}>
                    <td colSpan={9} style={{ padding: '10px 16px' }}>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 2fr', gap: 12 }}>
                        {/* SDS components */}
                        <div>
                          <div style={{ fontWeight: 600, fontSize: 11, marginBottom: 6 }}>SDS 컴포넌트 ({sdsComps.length})</div>
                          {sdsComps.length > 0 ? (
                            <div style={{ maxHeight: 150, overflowY: 'auto', fontSize: 11 }}>
                              {sdsComps.map((c, ci) => (
                                <div key={ci} style={{ padding: '2px 0', fontFamily: 'monospace', borderBottom: '1px solid #e5e7eb' }}>{c}</div>
                              ))}
                            </div>
                          ) : <div className="text-muted text-sm">매핑된 컴포넌트 없음</div>}
                        </div>
                        {/* UDS Functions list */}
                        <div>
                          <div style={{ fontWeight: 600, fontSize: 11, marginBottom: 6 }}>UDS 함수 ({srcFuncs.length})</div>
                          {srcFuncs.length > 0 ? (
                            <div style={{ maxHeight: 150, overflowY: 'auto', fontSize: 11 }}>
                              {srcFuncs.map((fn, fi) => (
                                <div key={fi} style={{ padding: '2px 0', fontFamily: 'monospace', borderBottom: '1px solid #e5e7eb' }}>{fn}</div>
                              ))}
                            </div>
                          ) : <div className="text-muted text-sm">매핑된 함수 없음</div>}
                        </div>
                        {/* Tests list */}
                        <div>
                          <div style={{ fontWeight: 600, fontSize: 11, marginBottom: 6 }}>테스트 ({rawTests.length})</div>
                          {rawTests.length > 0 ? (
                            <div style={{ maxHeight: 150, overflowY: 'auto', fontSize: 11 }}>
                              <table style={{ width: '100%', fontSize: 10, borderCollapse: 'collapse' }}>
                                <thead>
                                  <tr style={{ background: '#e5e7eb' }}>
                                    <th style={{ padding: '3px 6px', textAlign: 'left' }}>TC</th>
                                    <th style={{ padding: '3px 6px', textAlign: 'center', width: 45 }}>결과</th>
                                    <th style={{ padding: '3px 6px', textAlign: 'center', width: 55 }}>소스</th>
                                    <th style={{ padding: '3px 6px', textAlign: 'center', width: 45 }}>추적</th>
                                    <th style={{ padding: '3px 6px', textAlign: 'center', width: 45 }}>신뢰</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {rawTests.map((t, ti) => {
                                    const isPass = (t.result || '').toLowerCase().match(/^(pass|passed|true|1)$/);
                                    const isFail = (t.result || '').toLowerCase().match(/^(fail|failed|false|0)$/);
                                    return (
                                      <tr key={ti} style={{ borderBottom: '1px solid #e5e7eb' }}>
                                        <td style={{ padding: '3px 6px', fontFamily: 'monospace' }}>{t.testcase || '-'}</td>
                                        <td style={{ padding: '3px 6px', textAlign: 'center', fontWeight: 600,
                                          color: isPass ? '#16a34a' : isFail ? '#dc2626' : '#6b7280' }}>
                                          {t.result || '-'}
                                        </td>
                                        <td style={{ padding: '3px 6px', textAlign: 'center' }}>
                                          <span style={{ fontSize: 9, padding: '0 4px', borderRadius: 4,
                                            background: (SOURCE_COLORS[t.source] || '#6b7280') + '18',
                                            color: SOURCE_COLORS[t.source] || '#6b7280', fontWeight: 600 }}>
                                            {t.source || '-'}
                                          </span>
                                        </td>
                                        <td style={{ padding: '3px 6px', textAlign: 'center', fontSize: 9,
                                          color: t.trace_type === 'direct' ? '#16a34a' : t.trace_type === 'indirect' ? '#d97706' : '#6b7280' }}>
                                          {t.trace_type === 'direct' ? '\uC9C1\uC811' : t.trace_type === 'indirect' ? '\uACBD\uC720' : '-'}
                                        </td>
                                        <td style={{ padding: '3px 6px', textAlign: 'center', fontSize: 9,
                                          color: CONFIDENCE_COLORS[t.confidence] || '#6b7280' }}>
                                          {t.confidence || '-'}
                                        </td>
                                      </tr>
                                    );
                                  })}
                                </tbody>
                              </table>
                            </div>
                          ) : <div className="text-muted text-sm">매핑된 테스트 없음</div>}
                        </div>
                      </div>
                      {/* V-Model trace path summary */}
                      <div style={{ marginTop: 10, padding: 8, background: 'var(--bg)', borderRadius: 6, borderLeft: '3px solid var(--accent)' }}>
                        <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 4 }}>V-Model {'\uCD94\uC801 \uACBD\uB85C'}</div>
                        <div style={{ fontSize: 10 }}>
                          T1: SDS → {sdsComps.length}{'\uAC1C \uCEF4\uD3EC\uB10C\uD2B8'} | T2: UDS → {srcFuncs.length}{'\uAC1C \uD568\uC218'} | T3: STS → {stsCount} TC ({'\uC9C1\uC811'}) | T4: SUTS → {r.suts_direct || 0} {'\uC9C1\uC811'} + {r.suts_indirect || 0} {'\uACBD\uC720'} | T5: SITS → {r.sits_direct || 0} {'\uC9C1\uC811'} + {r.sits_indirect || 0} {'\uACBD\uC720'}
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
      </div>

      {/* Pagination */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="text-sm text-muted">페이지당</span>
          <select value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setCurrentPage(0); }}
            style={{ padding: '3px 6px', fontSize: 12, border: '1px solid var(--border)', borderRadius: 4, background: 'var(--bg)', color: 'var(--fg)' }}>
            {PAGE_SIZES.map(s => <option key={s} value={s}>{s}건</option>)}
          </select>
          <span className="text-sm text-muted">
            {filtered.length === 0 ? '(0건)' : `(${safePage * pageSize + 1}-${Math.min((safePage + 1) * pageSize, filtered.length)} / ${filtered.length}건)`}
          </span>
        </div>
        {totalPages > 1 && (
          <div style={{ display: 'flex', gap: 4 }}>
            <button className="btn-sm" disabled={safePage === 0} onClick={() => setCurrentPage(0)} style={{ fontSize: 11 }}>&laquo;</button>
            <button className="btn-sm" disabled={safePage === 0} onClick={() => setCurrentPage(p => p - 1)} style={{ fontSize: 11 }}>&lsaquo;</button>
            <span className="text-sm" style={{ padding: '4px 8px', fontWeight: 600 }}>
              {safePage + 1} / {totalPages}
            </span>
            <button className="btn-sm" disabled={safePage >= totalPages - 1} onClick={() => setCurrentPage(p => p + 1)} style={{ fontSize: 11 }}>&rsaquo;</button>
            <button className="btn-sm" disabled={safePage >= totalPages - 1} onClick={() => setCurrentPage(totalPages - 1)} style={{ fontSize: 11 }}>&raquo;</button>
          </div>
        )}
      </div>
    </div>
  );
}
