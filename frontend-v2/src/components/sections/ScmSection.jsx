import { useState, useCallback, useEffect, useMemo } from 'react';
import { post } from '../../api.js';
import { useJenkinsCfg, useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';
import { defaultCacheRoot } from '../../api.js';
import { impactConflict, mismatchText } from '../../impactGuard.js';

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

  /* --- Check linked doc existence (경로별 상태 — 배열 값도 경로 단위로 개별 확인) --- */
  const checkDocStatus = useCallback(async (docs) => {
    if (!docs || !job?.url) return;
    const paths = Object.values(docs)
      .flatMap(v => (Array.isArray(v) ? v : [v]))
      .filter(Boolean);
    if (paths.length === 0) return;
    const result = {};
    for (const docPath of paths) {
      try {
        const data = await post('/api/file-mode/check-access', { path: docPath });
        if (data?.accessible) {
          result[docPath] = 'found';
        } else if (data?.verified) {
          // 실제 검증됨(local=Path, cloudium=worker IPC exists) + 접근 불가 → 진짜 '없음'.
          // (백엔드가 cloudium에서도 worker로 존재를 검증하므로 이제 '없음'을 정확히 표시)
          result[docPath] = 'not_found';
        } else {
          // 검증 불가(cloudium gate 미실행 / worker 연결·응답 오류 등) → '미확인'(거짓 '없음' 방지).
          result[docPath] = 'unknown';
        }
      } catch {
        result[docPath] = 'unknown';
      }
    }
    setDocStatus(result);
  }, [job]);

  const selected = scmList.find(s => s.id === selectedId);
  // 변경 파일 목록이 정말 '지금 보고 있는 것'의 것인지 대조한다(impactGuard).
  // Job 축(Context의 결과가 다른 Job의 것) + SCM 축(위 드롭다운으로 고른 SCM과 결과를 만든
  // SCM이 다름 — 드롭다운은 바꿀 수 있는데 impactData는 따라오지 않는다) 둘 다 본다.
  // 표시용이라 '모순이 증명될 때만' 감춘다 — 증거 부재까지 막으면 정상 데이터를 상시로
  // 감추게 된다(impactGuard.impactConflict 주석 참조).
  const _conflict = impactConflict(analysisResult, job?.url, selectedId);
  const changed = _conflict.conflict ? [] : (analysisResult?.impactData?.changed_files ?? []);
  // 사유가 미지여도 반드시 문구가 나온다 — 감췄는데 배너가 안 뜨는 침묵 은닉 차단.
  const changedHiddenReason = mismatchText(_conflict.reason);

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

              {/* Linked docs — 표로 정리(유형·파일명·상태). 파일명만 표시하고 전체 경로는 행 title(hover)로
                  노출한다(압축 규약 유지). 배열 값(복수 경로)은 경로별로 행을 분리하고, 유형 pill은 첫 행에만
                  표기(연속 행은 ↳). 상태는 경로별 docStatus 조회. */}
              {selected.linked_docs && Object.values(selected.linked_docs).some(v => (Array.isArray(v) ? v.length : v)) && (
                <div style={{ marginTop: 12 }}>
                  <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>연결 문서</div>
                  <div style={{ overflowX: 'auto' }}>
                    <table className="impact-table" style={{ marginTop: 0 }}>
                      <thead>
                        <tr>
                          <th style={{ width: '1%', whiteSpace: 'nowrap' }}>유형</th>
                          <th>파일명</th>
                          <th style={{ width: '1%', whiteSpace: 'nowrap' }}>상태</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(selected.linked_docs)
                          .filter(([, v]) => (Array.isArray(v) ? v.length : v))
                          .flatMap(([k, v]) => {
                            const paths = (Array.isArray(v) ? v : [v]).filter(Boolean);
                            return paths.map((p, i) => {
                              const st = docStatus[p];
                              return (
                                <tr key={`${k}-${i}`} title={p}>
                                  <td style={{ whiteSpace: 'nowrap' }}>
                                    {i === 0
                                      ? <span className="pill pill-purple">{k.toUpperCase()}</span>
                                      : <span className="text-muted" style={{ paddingLeft: 6 }}>↳</span>}
                                  </td>
                                  <td>
                                    <span className="artifact-icon" style={{ marginRight: 6 }}>📄</span>
                                    <span>{docBaseName(p)}</span>
                                  </td>
                                  <td style={{ whiteSpace: 'nowrap' }}>
                                    {st === 'found' && <StatusBadge tone="success">유효</StatusBadge>}
                                    {st === 'not_found' && <StatusBadge tone="danger">없음</StatusBadge>}
                                    {st === 'unknown' && <StatusBadge tone="neutral">미확인</StatusBadge>}
                                    {!st && <span className="text-muted text-sm">–</span>}
                                  </td>
                                </tr>
                              );
                            });
                          })}
                      </tbody>
                    </table>
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
      {/* 감춘 이유를 밝힌다 — 조용히 비우면 '변경 없음'으로 오독된다. */}
      {changedHiddenReason && (
        <div className="panel mt-3">
          <div className="panel-body text-sm text-muted">
            ⚠ 변경 파일 목록을 표시하지 않았습니다 — {changedHiddenReason}
          </div>
        </div>
      )}

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
