import { useState, useCallback, useEffect } from 'react';
import { getUsername } from '../api.js';

const API_BASE = (typeof window !== 'undefined' && window.__ARIA_API_BASE__)
  || import.meta.env?.VITE_API_BASE_URL || '';

function buildUrl(path) {
  if (!API_BASE) return path;
  return API_BASE.replace(/\/$/, '') + path;
}

// 39차: cloudium path bookmark (localStorage LRU 최대 20건)
const BOOKMARK_KEY = 'devops_v2_cloudium_path_bookmarks';
const BOOKMARK_MAX = 20;

function loadBookmarks() {
  try {
    const raw = localStorage.getItem(BOOKMARK_KEY);
    const arr = JSON.parse(raw || '[]');
    return Array.isArray(arr) ? arr.filter(p => typeof p === 'string') : [];
  } catch (e) {
    return [];
  }
}

function saveBookmark(path) {
  if (!path || typeof path !== 'string') return;
  try {
    const current = loadBookmarks();
    const filtered = current.filter(p => p !== path);
    filtered.unshift(path);
    const trimmed = filtered.slice(0, BOOKMARK_MAX);
    localStorage.setItem(BOOKMARK_KEY, JSON.stringify(trimmed));
  } catch (e) {
    console.warn('bookmark save failed:', e?.message || e);
  }
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
  const [data, setData] = useState({
    dirs: [], files: [], parent: '', truncated: false,
    file_mode: 'local', cloudium_hint: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  // 39차: bookmark + 403 자동 add prompt
  const [bookmarks, setBookmarks] = useState(() => loadBookmarks());
  const [showBookmarks, setShowBookmarks] = useState(false);
  const [pendingAddPath, setPendingAddPath] = useState(null);  // 403 시 사용자 확인 대기
  const [addPrefixLoading, setAddPrefixLoading] = useState(false);

  const fetchPath = useCallback(async (path) => {
    const user = getUsername();
    if (!user) {
      setError('사용자 이름이 설정되지 않음');
      return;
    }
    setLoading(true);
    setError(null);
    setPendingAddPath(null);
    try {
      const res = await fetch(buildUrl('/api/swut/browse'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User': user },
        body: JSON.stringify({ path, pattern }),
      });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        let code = '';
        try {
          const j = await res.json();
          msg = j?.error?.message || j?.detail || j?.message || msg;
          code = j?.error?.code || j?.code || '';
        } catch (e) { /* non-JSON */ }
        setError(msg);
        // 39차: 403 CLOUDIUM_BLOCKED 시 자동 add 제안
        if (res.status === 403 && (code === 'CLOUDIUM_BLOCKED' || /Cloudium/i.test(msg))) {
          setPendingAddPath(path);
        }
        return;
      }
      const body = await res.json();
      setData({
        dirs: body.dirs || [],
        files: body.files || [],
        parent: body.parent || '',
        truncated: body.truncated || false,
        file_mode: body.file_mode || 'local',
        cloudium_hint: body.cloudium_hint || '',
      });
      setCurrentPath(body.current || path);
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, [pattern]);

  // 39차: pendingAddPath를 allowed_prefixes에 추가 + 재시도
  const confirmAddPrefix = useCallback(async () => {
    if (!pendingAddPath) return;
    const user = getUsername();
    if (!user) {
      setError('사용자 이름이 설정되지 않음');
      return;
    }
    setAddPrefixLoading(true);
    try {
      const res = await fetch(buildUrl('/api/file-mode/add-allowed-prefix'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User': user },
        body: JSON.stringify({ prefix: pendingAddPath }),
      });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const j = await res.json();
          msg = j?.error?.message || j?.detail || msg;
        } catch (e) { /* non-JSON */ }
        setError(`prefix 추가 실패: ${msg}`);
        return;
      }
      // 성공 → 자동 재시도
      const path = pendingAddPath;
      setPendingAddPath(null);
      await fetchPath(path);
    } catch (e) {
      setError(`prefix 추가 실패: ${e?.message || e}`);
    } finally {
      setAddPrefixLoading(false);
    }
  }, [pendingAddPath, fetchPath]);

  useEffect(() => {
    if (open) {
      setCurrentPath(initialPath);
      fetchPath(initialPath);
    }
  }, [open, initialPath, fetchPath]);

  if (!open) return null;

  const handleSelect = (filePath) => {
    // 39차: 파일 선택 시 부모 디렉토리를 bookmark에 저장 (재방문 편의)
    try {
      const parentDir = filePath.replace(/[\\/][^\\/]+$/, '') || filePath;
      saveBookmark(parentDir);
      setBookmarks(loadBookmarks());
    } catch (e) { /* ignore */ }
    if (onSelect) onSelect(filePath);
    if (onClose) onClose();
  };

  const handleSelectBookmark = (path) => {
    setCurrentPath(path);
    setShowBookmarks(false);
    fetchPath(path);
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
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck="false"
            data-form-type="other"
            data-lpignore="true"
          />
          <button
            className="picker-go"
            disabled={loading}
            onClick={() => fetchPath(currentPath)}
          >
            이동
          </button>
          {/* 39차: bookmark dropdown — 자주 쓰는 경로 */}
          <button
            className="picker-bookmarks-toggle"
            data-testid="picker-bookmarks-toggle"
            disabled={loading || bookmarks.length === 0}
            onClick={() => setShowBookmarks(s => !s)}
            title="자주 쓰는 경로"
          >
            ⭐ ({bookmarks.length})
          </button>
        </div>
        {/* 39차: bookmark dropdown panel */}
        {showBookmarks && bookmarks.length > 0 && (
          <div className="picker-bookmarks-panel" data-testid="picker-bookmarks-panel">
            <div className="picker-bookmarks-title">⭐ 자주 쓰는 경로 (최근순)</div>
            <ul className="picker-bookmarks-list">
              {bookmarks.map((p, i) => (
                <li key={`bm-${i}`}>
                  <button
                    className="picker-bookmark-entry"
                    onClick={() => handleSelectBookmark(p)}
                    title={p}
                  >
                    📁 {p}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {/* 39차: Cloudium 모드 경고 카드 (worker 디렉토리 navigate 한계) */}
        {data.file_mode === 'cloudium' && (
          <div className="picker-cloudium-warning" data-testid="picker-cloudium-warning">
            ⚠️ Cloudium 모드: worker가 디렉토리 navigate를 지원하지 않습니다.
            경로를 <strong>직접 입력</strong>하거나 자주 쓰는 경로(⭐)를 활용하세요.
          </div>
        )}
        {/* 39차: 403 자동 add 제안 */}
        {pendingAddPath && (
          <div className="picker-add-prompt" data-testid="picker-add-prompt">
            🔒 이 경로가 allowed_prefixes에 등록되지 않았습니다.
            <code>{pendingAddPath}</code>
            <div className="picker-add-actions">
              <button
                className="picker-add-confirm"
                disabled={addPrefixLoading}
                onClick={confirmAddPrefix}
              >
                {addPrefixLoading ? '추가 중...' : '+ 추가 후 재시도'}
              </button>
              <button
                className="picker-add-cancel"
                disabled={addPrefixLoading}
                onClick={() => setPendingAddPath(null)}
              >
                취소
              </button>
            </div>
          </div>
        )}
        <div className="picker-body">
          {loading && <div className="picker-loading">로딩 중...</div>}
          {error && <div className="picker-error">⚠️ {error}</div>}
          {!loading && !error && (
            <>
              {data.cloudium_hint && (
                <div className="picker-cloudium-hint">ℹ️ {data.cloudium_hint}</div>
              )}
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
