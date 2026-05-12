import { useState, useCallback, useEffect } from 'react';
import { getUsername } from '../api.js';

const API_BASE = (typeof window !== 'undefined' && window.__ARIA_API_BASE__)
  || import.meta.env?.VITE_API_BASE_URL || '';

function buildUrl(path) {
  if (!API_BASE) return path;
  return API_BASE.replace(/\/$/, '') + path;
}

/**
 * 21차 라운드 — 경로 선택 모달 (Cloudium / Local 통합 navigate).
 *
 * Props:
 *   - open: boolean — 표시 여부
 *   - initialPath: string — 시작 경로 (사용자 home / cwd)
 *   - pattern: string — glob (예: '*.xlsx', '*.xlsm,*.docx')
 *   - title: string — 상단 제목
 *   - onSelect: (path: string) => void — 파일 선택 시 콜백 (선택 후 자동 close 호출)
 *   - onClose: () => void
 */
export default function PathPickerDialog({
  open,
  initialPath = '',
  pattern = '*',
  title = '경로 선택',
  onSelect,
  onClose,
}) {
  const [currentPath, setCurrentPath] = useState(initialPath);
  const [data, setData] = useState({ dirs: [], files: [], parent: '', truncated: false });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchPath = useCallback(async (path) => {
    const user = getUsername();
    if (!user) {
      setError('사용자 이름이 설정되지 않음');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(buildUrl('/api/swut/browse'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User': user },
        body: JSON.stringify({ path, pattern }),
      });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const j = await res.json();
          msg = j?.error?.message || j?.detail || j?.message || msg;
        } catch (e) { /* non-JSON */ }
        setError(msg);
        return;
      }
      const body = await res.json();
      setData({
        dirs: body.dirs || [],
        files: body.files || [],
        parent: body.parent || '',
        truncated: body.truncated || false,
      });
      setCurrentPath(body.current || path);
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [pattern]);

  useEffect(() => {
    if (open) {
      setCurrentPath(initialPath);
      fetchPath(initialPath);
    }
  }, [open, initialPath, fetchPath]);

  if (!open) return null;

  const handleSelect = (filePath) => {
    if (onSelect) onSelect(filePath);
    if (onClose) onClose();
  };

  const handleNavigate = (dirPath) => {
    fetchPath(dirPath);
  };

  return (
    <div className="picker-overlay" role="dialog" aria-label={title}>
      <div className="picker-dialog">
        <div className="picker-header">
          <h3 className="picker-title">{title}</h3>
          <button className="picker-close" onClick={onClose} aria-label="닫기">✕</button>
        </div>
        <div className="picker-toolbar">
          <button
            className="picker-up"
            disabled={!data.parent || data.parent === currentPath || loading}
            onClick={() => handleNavigate(data.parent)}
          >
            ⬆ 상위 디렉토리
          </button>
          <input
            className="picker-path"
            value={currentPath}
            onChange={e => setCurrentPath(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') fetchPath(currentPath); }}
            placeholder="경로 직접 입력 + Enter"
            autoComplete="off"
            spellCheck="false"
          />
          <button
            className="picker-go"
            disabled={loading}
            onClick={() => fetchPath(currentPath)}
          >
            이동
          </button>
        </div>
        <div className="picker-body">
          {loading && <div className="picker-loading">로딩 중...</div>}
          {error && <div className="picker-error">⚠️ {error}</div>}
          {!loading && !error && (
            <>
              {data.dirs.length === 0 && data.files.length === 0 && (
                <div className="picker-empty">(비어있음)</div>
              )}
              {data.dirs.length > 0 && (
                <ul className="picker-list">
                  {data.dirs.map((d, i) => (
                    <li key={`d-${i}`}>
                      <button
                        className="picker-entry picker-entry-dir"
                        onClick={() => handleNavigate(d)}
                      >
                        📁 {d.split(/[\\/]/).pop()}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {data.files.length > 0 && (
                <ul className="picker-list">
                  {data.files.map((f, i) => (
                    <li key={`f-${i}`}>
                      <button
                        className="picker-entry picker-entry-file"
                        onClick={() => handleSelect(f)}
                      >
                        📄 {f.split(/[\\/]/).pop()}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              {data.truncated && (
                <div className="picker-truncated">
                  ⚠️ 결과가 2000건 초과 — 일부만 표시. pattern으로 필터 좁히세요.
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
