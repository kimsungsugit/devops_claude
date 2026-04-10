import React, { useState, useEffect, useCallback } from 'react';

const post = async (url, body) => {
  const res = await fetch(url, { method: 'POST', body });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
};

export default function ProjectSetupSection({ toast }) {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [sdsPath, setSdsPath] = useState('');
  const [sourceRoot, setSourceRoot] = useState('');
  const [refUdsPath, setRefUdsPath] = useState('');

  const loadStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/local/project-setup/status');
      if (res.ok) setStatus(await res.json());
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const generateComponentMap = async () => {
    if (!sdsPath || !sourceRoot) {
      toast?.('warning', 'SDS 경로와 소스 루트를 입력하세요');
      return;
    }
    setLoading(true);
    try {
      const form = new FormData();
      form.append('sds_path', sdsPath);
      form.append('source_root', sourceRoot);
      const result = await post('/api/local/project-setup/generate-component-map', form);
      toast?.('success', `component_map 생성: ${result.stats?.matched || 0}개 매핑`);
      loadStatus();
    } catch (e) {
      toast?.('error', `생성 실패: ${e.message}`);
    }
    setLoading(false);
  };

  const generateOverride = async () => {
    if (!refUdsPath) {
      toast?.('warning', '레퍼런스 UDS 경로를 입력하세요');
      return;
    }
    setLoading(true);
    try {
      const form = new FormData();
      form.append('uds_path', refUdsPath);
      const result = await post('/api/local/project-setup/generate-override', form);
      toast?.('success', `override 생성: ${result.stats?.total_functions || 0}개 함수`);
      loadStatus();
    } catch (e) {
      toast?.('error', `생성 실패: ${e.message}`);
    }
    setLoading(false);
  };

  const inputStyle = {
    width: '100%', padding: '8px 12px', fontSize: 13,
    border: '1px solid var(--border)', borderRadius: 6,
    background: 'var(--bg)', color: 'var(--fg)',
  };

  return (
    <div style={{ padding: 16 }}>
      <h3 style={{ marginBottom: 16 }}>프로젝트 설정 (ISO 26262 문서 생성 준비)</h3>

      {/* Status */}
      {status && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 20 }}>
          <div style={{ padding: 12, border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg)' }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>component_map.json</div>
            {status.component_map?.exists ? (
              <>
                <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--color-success)' }}>
                  {status.component_map.entries}개
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  verify=O: {status.component_map.verify_o} / verify=X: {status.component_map.verify_x}
                </div>
              </>
            ) : (
              <div style={{ fontSize: 14, color: 'var(--color-warning)' }}>미생성</div>
            )}
          </div>
          <div style={{ padding: 12, border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg)' }}>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>override.json (함수 단위)</div>
            {status.override?.exists ? (
              <>
                <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--color-success)' }}>
                  {status.override.functions}개
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  ASIL: {status.override.with_asil} / SwCom: {status.override.swcom_count}개
                </div>
              </>
            ) : (
              <div style={{ fontSize: 14, color: 'var(--color-warning)' }}>미생성</div>
            )}
          </div>
        </div>
      )}

      {/* Generate Component Map */}
      <div style={{ marginBottom: 20, padding: 16, border: '1px solid var(--border)', borderRadius: 8 }}>
        <h4 style={{ marginBottom: 12 }}>1. Component Map 생성 (SDS 기반)</h4>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
          SDS 문서에서 파일-to-SwCom 매핑을 자동 추출합니다. UDS/SUTS/STS/SITS 생성 시 SwCom 분배에 사용됩니다.
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <input
            style={inputStyle} placeholder="SDS 문서 경로 (예: D:\docs\SDS.docx)"
            value={sdsPath} onChange={e => setSdsPath(e.target.value)}
          />
          <input
            style={inputStyle} placeholder="소스 루트 경로 (예: D:\Project\Ados\PDS64_RD,D:\Project\Ados\PDS64_FBL)"
            value={sourceRoot} onChange={e => setSourceRoot(e.target.value)}
          />
          <button className="btn-primary" onClick={generateComponentMap} disabled={loading}>
            {loading ? '생성 중...' : 'Component Map 생성'}
          </button>
        </div>
      </div>

      {/* Generate Override */}
      <div style={{ padding: 16, border: '1px solid var(--border)', borderRadius: 8 }}>
        <h4 style={{ marginBottom: 12 }}>2. Override Map 생성 (레퍼런스 UDS 기반)</h4>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 12 }}>
          기존 UDS 문서에서 함수별 SwCom/ASIL/Related ID를 역추출합니다. 새 UDS/SUTS 생성 시 100% 정확도를 위해 사용됩니다.
          레퍼런스 UDS가 없으면 생략 가능합니다 (SDS 기반 자동 할당).
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <input
            style={inputStyle} placeholder="레퍼런스 UDS 경로 (예: D:\docs\UDS.docx)"
            value={refUdsPath} onChange={e => setRefUdsPath(e.target.value)}
          />
          <button className="btn-primary" onClick={generateOverride} disabled={loading}>
            {loading ? '생성 중...' : 'Override Map 생성'}
          </button>
        </div>
      </div>
    </div>
  );
}
