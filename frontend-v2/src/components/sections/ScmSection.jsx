import { useState, useCallback, useEffect } from 'react';
import { api, post } from '../../api.js';
import { useToast } from '../../App.jsx';
import StatusBadge from '../StatusBadge.jsx';

export default function ScmSection({ job, analysisResult }) {
  const toast = useToast();
  const [scmList, setScmList] = useState(analysisResult?.scmList ?? []);
  const [selectedId, setSelectedId] = useState('');
  const [status, setStatus] = useState(null);
  const [loadingStatus, setLoadingStatus] = useState(false);

  useEffect(() => {
    if (analysisResult?.scmList) setScmList(analysisResult.scmList);
  }, [analysisResult]);

  useEffect(() => {
    if (scmList.length > 0 && !selectedId) setSelectedId(scmList[0].id);
  }, [scmList]);

  const loadStatus = useCallback(async () => {
    if (!selectedId) return;
    setLoadingStatus(true);
    try {
      const data = await api(`/api/scm/${selectedId}/status`);
      setStatus(data);
    } catch (e) {
      toast('error', `SCM 상태 조회 실패: ${e.message}`);
    } finally {
      setLoadingStatus(false);
    }
  }, [selectedId, toast]);

  const selected = scmList.find(s => s.id === selectedId);
  const changed = analysisResult?.impactData?.changed_files ?? [];

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
              <select value={selectedId} onChange={e => { setSelectedId(e.target.value); setStatus(null); }}>
                {scmList.map(s => <option key={s.id} value={s.id}>{s.name} ({s.scm_type})</option>)}
              </select>
            </div>
          )}

          {selected && (
            <div className="panel">
              <div className="panel-header">
                <span className="panel-title">🌿 {selected.name}</span>
                <StatusBadge tone="info">{selected.scm_type?.toUpperCase()}</StatusBadge>
                <button className="btn-sm" onClick={loadStatus} disabled={loadingStatus}>
                  {loadingStatus ? <span className="spinner" /> : '상태 확인'}
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

              {/* Linked docs */}
              {selected.linked_docs && Object.values(selected.linked_docs).some(Boolean) && (
                <div style={{ marginTop: 12 }}>
                  <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>연결 문서</div>
                  {Object.entries(selected.linked_docs).filter(([, v]) => v).map(([k, v]) => (
                    <div key={k} className="artifact-item">
                      <span className="artifact-icon">📄</span>
                      <span className="pill pill-purple" style={{ marginRight: 4 }}>{k.toUpperCase()}</span>
                      <span className="artifact-name">{v}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* SCM status */}
              {status && (
                <div style={{ marginTop: 12 }}>
                  <div className="divider" />
                  <div className="text-sm" style={{ fontWeight: 700, marginBottom: 6 }}>SCM 상태</div>
                  <div className="log-box" style={{ maxHeight: 200 }}>
                    {typeof status === 'string' ? status : JSON.stringify(status, null, 2)}
                  </div>
                </div>
              )}
            </div>
          )}
        </>
      )}

      {/* Changed files */}
      {changed.length > 0 && (
        <div className="panel mt-3">
          <div className="panel-header">
            <span className="panel-title">변경 파일 ({changed.length})</span>
          </div>
          <div className="artifact-list">
            {changed.map((f, i) => {
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
          </div>
        </div>
      )}
    </div>
  );
}
