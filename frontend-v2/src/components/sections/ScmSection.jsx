import { useState, useCallback, useEffect, useMemo } from 'react';
import { post } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';
import { defaultCacheRoot } from '../../api.js';

// 경로에서 파일명(basename)만 추출 — 전체 경로 대신 짧게 표시(전체 경로는 title로 hover 노출).
const docBaseName = (p) => {
  const s = String(p ?? '').replace(/\\/g, '/').replace(/\/+$/, '');
  return s.split('/').filter(Boolean).pop() || s;
};

export default function ScmSection({ job, analysisResult }) {
  const { cfg } = useJenkinsCfg();
  const toast = useToast();
  const [scmList, setScmList] = useState(analysisResult?.scmList ?? []);
  const [selectedId, setSelectedId] = useState('');
  const [scmInfo, setScmInfo] = useState(null);
  const [loadingInfo, setLoadingInfo] = useState(false);
  const [sourceRoot, setSourceRoot] = useState(null);
  const [loadingRoot, setLoadingRoot] = useState(false);
  const [fileFilter, setFileFilter] = useState('');
  const [docStatus, setDocStatus] = useState({});

  const cacheRoot = analysisResult?.cacheRoot || defaultCacheRoot(job?.url) || cfg.cacheRoot;

  useEffect(() => {
    if (analysisResult?.scmList) setScmList(analysisResult.scmList);
  }, [analysisResult]);

  useEffect(() => {
    // Prefer the registry entry that Dashboard matched to this job; fall back
    // to the first entry only when no match was recorded (multi-registry
    // setups would otherwise silently show data for the wrong project).
    if (scmList.length > 0 && !selectedId) {
      const matched = analysisResult?.matchedScm;
      const preferId = matched?.id && scmList.some(s => s.id === matched.id)
        ? matched.id
        : scmList[0].id;
      setSelectedId(preferId);
    }
  }, [scmList, analysisResult, selectedId]);

  /* --- Load SCM info via POST /api/jenkins/scm-info --- */
  const loadScmInfo = useCallback(async () => {
    if (!job?.url) return;
    setLoadingInfo(true);
    try {
      const data = await post('/api/jenkins/scm-info', {
        job_url: job.url,
        cache_root: cacheRoot,
        build_selector: cfg.buildSelector,
      });
      setScmInfo(data);
    } catch (e) {
      toast('error', `SCM 정보 조회 실패: ${e.message}`);
    } finally {
      setLoadingInfo(false);
    }
  }, [job, cfg, cacheRoot, toast]);

  /* --- Load source root via POST /api/jenkins/source-root --- */
  const loadSourceRoot = useCallback(async () => {
    if (!job?.url) return;
    setLoadingRoot(true);
    try {
      const data = await post('/api/jenkins/source-root', {
        job_url: job.url,
        cache_root: cacheRoot,
        build_selector: cfg.buildSelector,
      });
      setSourceRoot(data);
    } catch (e) {
      toast('error', `소스 루트 조회 실패: ${e.message}`);
    } finally {
      setLoadingRoot(false);
    }
  }, [job, cfg, cacheRoot, toast]);

  /* --- Check linked doc existence --- */
  const checkDocStatus = useCallback(async (docs) => {
    if (!docs || !job?.url) return;
    const entries = Object.entries(docs).filter(([, v]) => v);
    if (entries.length === 0) return;
    const result = {};
    for (const [key, docPath] of entries) {
      try {
        const data = await post('/api/file-mode/check-access', { path: docPath });
        result[key] = data?.accessible ? 'found' : 'not_found';
      } catch {
        result[key] = 'unknown';
      }
    }
    setDocStatus(result);
  }, [job, cacheRoot, cfg]);

  const selected = scmList.find(s => s.id === selectedId);
  const changed = analysisResult?.impactData?.changed_files ?? [];

  /* --- Filter changed files --- */
  const filteredFiles = useMemo(() => {
    if (!fileFilter.trim()) return changed;
    const q = fileFilter.toLowerCase();
    return changed.filter(f => {
      const path = typeof f === 'string' ? f : f.path;
      return path?.toLowerCase().includes(q);
    });
  }, [changed, fileFilter]);

  /* --- Revision info from scmInfo or analysisResult --- */
  const revision = scmInfo?.revision ?? scmInfo?.commit ?? analysisResult?.reportData?.commit;
  const revBranch = scmInfo?.branch ?? analysisResult?.reportData?.branch;
  const revAuthor = scmInfo?.author ?? scmInfo?.committer;
  const revMessage = scmInfo?.message ?? scmInfo?.commit_message;
  const revDate = scmInfo?.date ?? scmInfo?.timestamp;

  /* --- Check doc status when selected changes --- */
  useEffect(() => {
    if (selected?.linked_docs) checkDocStatus(selected.linked_docs);
  }, [selected, checkDocStatus]);

  return (
    <div>
      {scmList.length === 0 ? (
        <div className="panel">
          <div className="empty-state" style={{ padding: 24 }}>
            <div className="empty-icon">🌿</div>
            <div className="empty-title">SCM 미등록</div>
            <div className="empty-desc">설정 탭에서 SCM을 등록하면 SCM 정보를 확인할 수 있습니다.</div>
          </div>
        </div>
      ) : (
        <>
          {/* SCM selector */}
          {scmList.length > 1 && (
            <div className="field" style={{ marginBottom: 12 }}>
              <label>SCM 선택</label>
              <select value={selectedId} onChange={e => { setSelectedId(e.target.value); setScmInfo(null); setSourceRoot(null); }}>
                {scmList.map(s => <option key={s.id} value={s.id}>{s.name} ({s.scm_type})</option>)}
              </select>
            </div>
          )}

          {selected && (
            <div className="panel">
              <div className="panel-header">
                <span className="panel-title">🌿 {selected.name}</span>
                <StatusBadge tone="info">{selected.scm_type?.toUpperCase()}</StatusBadge>
                <button className="btn-sm" onClick={loadScmInfo} disabled={loadingInfo}>
                  {loadingInfo ? <span className="spinner" /> : 'SCM 정보'}
                </button>
                <button className="btn-sm" onClick={loadSourceRoot} disabled={loadingRoot} style={{ marginLeft: 4 }}>
                  {loadingRoot ? <span className="spinner" /> : '소스 루트'}
                </button>
              </div>
              <div className="field-group">
                {[
                  { label: 'URL', value: selected.scm_url },
                  { label: '브랜치', value: selected.branch },
                  { label: '소스 루트', value: selected.source_root },
                  { label: 'Base Ref', value: selected.base_ref },
                ].filter(f => f.value).map(({ label, value }) => (
                  <div className="field" key={label}>
                    <label>{label}</label>
                    <div style={{ fontSize: 13, wordBreak: 'break-all' }}>{value}</div>
                  </div>
                ))}
              </div>

              {/* Linked docs with existence status — 전체 경로 대신 파일명만 표시(전체 경로는 hover title),
                  칩을 flex-wrap으로 흘려 한 줄에 여러 파일명이 들어가도록 압축 */}
              {selected.linked_docs && Object.values(selected.linked_docs).some(v => (Array.isArray(v) ? v.length : v)) && (
                <div style={{ marginTop: 12 }}>
                  <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>연결 문서</div>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    {Object.entries(selected.linked_docs)
                      .filter(([, v]) => (Array.isArray(v) ? v.length : v))
                      .flatMap(([k, v]) => {
                        const paths = (Array.isArray(v) ? v : [v]).filter(Boolean);
                        return paths.map((p, i) => (
                          <span
                            key={`${k}-${i}`}
                            className="artifact-item"
                            title={p}
                            style={{ width: 'auto', padding: '4px 8px' }}
                          >
                            <span className="artifact-icon">📄</span>
                            <span className="pill pill-purple" style={{ marginRight: 2 }}>{k.toUpperCase()}</span>
                            <span className="artifact-name" style={{ flex: 'none', fontSize: 12 }}>{docBaseName(p)}</span>
                            {i === 0 && docStatus[k] === 'found' && (
                              <StatusBadge tone="success">존재</StatusBadge>
                            )}
                            {i === 0 && docStatus[k] === 'unknown' && (
                              <StatusBadge tone="neutral">미확인</StatusBadge>
                            )}
                          </span>
                        ));
                      })}
                  </div>
                </div>
              )}

              {/* SCM revision info */}
              {(scmInfo || revision) && (
                <div style={{ marginTop: 12 }}>
                  <div className="divider" />
                  <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>리비전 정보</div>
                  <div className="stats-row">
                    {revision && (
                      <div className="stat-card">
                        <div className="text-muted text-sm">커밋</div>
                        <div style={{ fontFamily: 'monospace', fontSize: 13, wordBreak: 'break-all' }}>{revision}</div>
                      </div>
                    )}
                    {revBranch && (
                      <div className="stat-card">
                        <div className="text-muted text-sm">브랜치</div>
                        <div style={{ fontSize: 13 }}>{revBranch}</div>
                      </div>
                    )}
                    {revAuthor && (
                      <div className="stat-card">
                        <div className="text-muted text-sm">작성자</div>
                        <div style={{ fontSize: 13 }}>{revAuthor}</div>
                      </div>
                    )}
                  </div>
                  {revMessage && (
                    <div style={{ marginTop: 8 }}>
                      <div className="text-muted text-sm" style={{ marginBottom: 4 }}>커밋 메시지</div>
                      <div className="log-box" style={{ maxHeight: 120 }}>{revMessage}</div>
                    </div>
                  )}
                  {revDate && (
                    <div className="text-muted text-sm" style={{ marginTop: 4 }}>
                      {new Date(revDate).toLocaleString('ko-KR')}
                    </div>
                  )}
                </div>
              )}

              {/* SCM raw info */}
              {scmInfo && !(revision || revBranch || revAuthor) && (
                <div style={{ marginTop: 12 }}>
                  <div className="divider" />
                  <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>SCM 상세</div>
                  <div className="log-box" style={{ maxHeight: 200 }}>
                    {JSON.stringify(scmInfo, null, 2)}
                  </div>
                </div>
              )}

              {/* Source root info */}
              {sourceRoot && (
                <div style={{ marginTop: 12 }}>
                  <div className="divider" />
                  <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>소스 루트 정보</div>
                  {sourceRoot.source_root ? (
                    <div className="field-group">
                      {[
                        { label: '경로', value: sourceRoot.source_root },
                        { label: '타입', value: sourceRoot.project_type },
                        { label: '파일 수', value: sourceRoot.file_count },
                      ].filter(f => f.value != null).map(({ label, value }) => (
                        <div className="field" key={label}>
                          <label>{label}</label>
                          <div style={{ fontSize: 13, wordBreak: 'break-all' }}>{value}</div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="log-box" style={{ maxHeight: 200 }}>
                      {JSON.stringify(sourceRoot, null, 2)}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* Changed files with filter */}
      {changed.length > 0 && (
        <div className="panel mt-3">
          <div className="panel-header">
            <span className="panel-title">변경 파일 ({filteredFiles.length}/{changed.length})</span>
          </div>
          <div style={{ padding: '8px 12px' }}>
            <input
              type="text"
              placeholder="파일 검색 (경로/이름)..."
              value={fileFilter}
              onChange={e => setFileFilter(e.target.value)}
              style={{ width: '100%', padding: '6px 10px', fontSize: 13, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg-secondary, #f5f5f5)' }}
            />
          </div>
          <div className="artifact-list">
            {filteredFiles.map((f, i) => {
              const path = typeof f === 'string' ? f : f.path;
              const action = typeof f === 'object' ? f.action : undefined;
              return (
                <div key={i} className="artifact-item">
                  <span className="artifact-icon">
                    {action === 'A' ? '🟢' : action === 'D' ? '🔴' : '🟡'}
                  </span>
                  <span className="artifact-name">{path}</span>
                  {action && <span className="pill pill-neutral">{action}</span>}
                </div>
              );
            })}
            {filteredFiles.length === 0 && fileFilter && (
              <div className="text-muted text-sm" style={{ padding: '8px 12px' }}>
                일치하는 파일이 없습니다.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
