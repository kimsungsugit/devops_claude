import { useState, useEffect, useCallback } from 'react';
import { useJenkinsCfg, useToast } from '../App.jsx';
import {
  post, api, saveServerJenkinsConfig,
  fetchServerUdsTemplate, saveServerUdsTemplate, uploadServerUdsTemplate,
} from '../api.js';

export default function Settings() {
  return (
    <div className="settings-layout">
      <JenkinsSection />
      <ScmSection />
      <DocInputSection />
      <QualitySection />
      <FileModeSection />
      <AdminSection />
    </div>
  );
}

/* ── Jenkins 연결 ─────────────────────────────────────────────────── */
function JenkinsSection() {
  const { cfg, update } = useJenkinsCfg();
  const toast = useToast();
  const [testing, setTesting] = useState(false);
  const [savingServer, setSavingServer] = useState(false);

  const testConnection = async () => {
    if (!cfg.baseUrl || !cfg.username || !cfg.token) {
      toast('warning', 'Jenkins URL, 사용자명, API Token을 모두 입력하세요.');
      return;
    }
    setTesting(true);
    try {
      await post('/api/jenkins/jobs', {
        base_url: cfg.baseUrl,
        username: cfg.username,
        api_token: cfg.token,
        recursive: false,
        max_depth: 1,
        verify_tls: cfg.verifyTls,
      });
      toast('success', 'Jenkins 연결 성공!');
    } catch (e) {
      toast('error', `연결 실패: ${e.message}`);
    } finally {
      setTesting(false);
    }
  };

  const saveToServer = async () => {
    if (!cfg.baseUrl || !cfg.username || !cfg.token) {
      toast('warning', '저장할 값을 모두 입력하세요 (URL, 사용자명, 토큰).');
      return;
    }
    if (!window.confirm('현재 Jenkins 설정을 서버에 저장하시겠습니까?\n모든 사용자가 이 설정을 사용하게 됩니다.')) {
      return;
    }
    setSavingServer(true);
    try {
      await saveServerJenkinsConfig(cfg);
      toast('success', '서버에 저장됐습니다. 모든 사용자가 이 설정을 사용합니다.');
    } catch (e) {
      toast('error', `서버 저장 실패: ${e.message}`);
    } finally {
      setSavingServer(false);
    }
  };

  return (
    <div className="settings-section">
      <div className="settings-section-title">🔧 Jenkins 연결</div>
      <div className="field-group">
        <div className="field span-2">
          <label>Jenkins Base URL</label>
          <input
            type="text"
            placeholder="http://jenkins.example.com:8080"
            value={cfg.baseUrl}
            onChange={e => update({ baseUrl: e.target.value })}
          />
        </div>
        <div className="field">
          <label>사용자명</label>
          <input
            type="text"
            placeholder="admin"
            value={cfg.username}
            onChange={e => update({ username: e.target.value })}
          />
        </div>
        <div className="field">
          <label>API Token</label>
          <input
            type="password"
            placeholder="••••••••••••"
            value={cfg.token}
            onChange={e => update({ token: e.target.value })}
          />
        </div>
        <div className="field">
          <label>캐시 루트 디렉토리</label>
          <input
            type="text"
            placeholder=".devops_pro_cache"
            value={cfg.cacheRoot}
            onChange={e => update({ cacheRoot: e.target.value })}
          />
        </div>
        <div className="field">
          <label>빌드 선택 기준</label>
          <select value={cfg.buildSelector} onChange={e => update({ buildSelector: e.target.value })}>
            <option value="lastSuccessfulBuild">마지막 성공 빌드</option>
            <option value="lastBuild">마지막 빌드</option>
            <option value="lastStableBuild">마지막 안정 빌드</option>
          </select>
        </div>
        <div className="field" style={{ justifyContent: 'flex-end', flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <label style={{ margin: 0, textTransform: 'none', letterSpacing: 0 }}>TLS 검증</label>
          <input
            type="checkbox"
            style={{ width: 'auto' }}
            checked={cfg.verifyTls}
            onChange={e => update({ verifyTls: e.target.checked })}
          />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 'var(--sp-2)', flexWrap: 'wrap', marginTop: 'var(--sp-2)' }}>
        <button onClick={testConnection} disabled={testing}>
          {testing ? <><span className="spinner" /> 연결 테스트 중...</> : '연결 테스트'}
        </button>
        <button className="btn-primary" onClick={saveToServer} disabled={savingServer} title="모든 사용자가 공유할 Jenkins 설정을 서버에 저장합니다">
          {savingServer ? <><span className="spinner" /> 저장 중...</> : '서버에 저장 (모든 사용자 공유)'}
        </button>
      </div>
    </div>
  );
}

/* ── SCM 레지스트리 ───────────────────────────────────────────────── */
function ScmSection() {
  const toast = useToast();
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editMode, setEditMode] = useState(null); // null = new, string = editing id
  const [form, setForm] = useState(defaultScmForm());

  function defaultScmForm() {
    return {
      id: '',
      name: '',
      scm_type: 'git',
      scm_url: '',
      scm_username: '',
      scm_password_env: '',
      branch: '',
      base_ref: 'HEAD~1',
      source_root: '',
      linked_docs: { srs: '', sds: '', uds: '', sts: '', suts: '', sits: '', hsis: '', stp: '' },
    };
  }

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api('/api/scm/list');
      setList(Array.isArray(data) ? data : (data.items ?? data.registries ?? []));
    } catch (e) {
      toast('error', `SCM 목록 조회 실패: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { loadList(); }, [loadList]);

  const saveScm = async () => {
    if (!form.id || !form.name) {
      toast('warning', 'ID와 이름을 입력하세요.');
      return;
    }
    try {
      if (editMode) {
        // Update existing
        await fetch(`/api/scm/update/${editMode}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(form),
        });
        toast('success', 'SCM 수정 완료');
      } else {
        await post('/api/scm/register', form);
        toast('success', 'SCM 등록 완료');
      }
      setShowForm(false);
      setEditMode(null);
      setForm(defaultScmForm());
      loadList();
    } catch (e) {
      toast('error', `${editMode ? '수정' : '등록'} 실패: ${e.message}`);
    }
  };

  const deleteScm = async (id) => {
    if (!confirm(`SCM '${id}'를 삭제하시겠습니까?`)) return;
    try {
      const res = await fetch(`/api/scm/${id}`, { method: 'DELETE' });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      toast('success', '삭제 완료');
      loadList();
    } catch (e) {
      toast('error', `삭제 실패: ${e.message}`);
    }
  };

  const setLinked = (key, val) =>
    setForm(p => ({ ...p, linked_docs: { ...p.linked_docs, [key]: val } }));

  // path 정규화 — 슬래시 방향 통일 + 끝의 슬래시 제거 (W3 fix)
  const normalizePath = (p) => (p || '').replace(/\\/g, '/').replace(/\/+$/, '');

  // 클라우디움 모드일 때 선택한 파일의 부모 디렉토리를 allowed_prefixes에 자동 추가
  const ensureCloudiumPrefix = async (filePath) => {
    try {
      const cfg = await api('/api/file-mode');
      if (cfg.mode !== 'cloudium') return;
      const lastSlash = Math.max(filePath.lastIndexOf('/'), filePath.lastIndexOf('\\'));
      const parent = lastSlash >= 0 ? filePath.slice(0, lastSlash) : filePath;
      const parentNorm = normalizePath(parent);
      const existing = Array.isArray(cfg.allowed_prefixes) ? cfg.allowed_prefixes : [];
      const existingNorm = existing.map(normalizePath);
      if (existingNorm.some(p => parentNorm === p || parentNorm.startsWith(p + '/'))) return;
      await post('/api/file-mode', {
        mode: 'cloudium',
        allowed_prefixes: [...existing, parent].join(', '),
        gate_process: cfg.gate_process || 'excel_rename_gui_v2.exe',
      });
      toast('info', `클라우디움 허용 디렉토리에 추가: ${parent}`);
    } catch (e) {
      console.warn('allowed_prefixes 자동 갱신 실패:', e.message);
      toast('warning', `자동 권한 갱신 실패 — 수동으로 "허용 prefix"에 추가하세요. (${e.message})`);
    }
  };

  const pickLinkedDoc = async (key) => {
    try {
      const picked = await post('/api/file-mode/browse-file', {
        title: `${key.toUpperCase()} 문서 선택`,
        kind: 'file',
      });
      if (!picked || !picked.ok || !picked.path) {
        if (picked?.error === 'cancelled') return;
        toast('error', `다이얼로그 실패: ${picked?.error || picked?.detail || 'unknown'}`);
        return;
      }
      setLinked(key, picked.path);
      await ensureCloudiumPrefix(picked.path);
      toast('success', `${key.toUpperCase()} 경로 선택됨`);
    } catch (e) {
      toast('error', `다이얼로그 실패: ${e.message}`);
    }
  };

  return (
    <div className="settings-section">
      <div className="settings-section-title">
        🌿 SCM 레지스트리
        <div style={{ flex: 1 }} />
        <button onClick={() => { setShowForm(p => !p); if (showForm) { setEditMode(null); setForm(defaultScmForm()); } }}>
          {showForm ? '취소' : '+ 새 SCM 등록'}
        </button>
        <button onClick={loadList} disabled={loading} style={{ marginLeft: 4 }}>
          {loading ? <span className="spinner" /> : '↺'}
        </button>
      </div>

      {showForm && (
        <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 8, padding: 16, marginBottom: 16 }}>
          <div className="field-group">
            <div className="field">
              <label>ID (고유값)</label>
              <input value={form.id} onChange={e => setForm(p => ({ ...p, id: e.target.value }))} placeholder="my-project" />
            </div>
            <div className="field">
              <label>이름</label>
              <input value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))} placeholder="My Project" />
            </div>
            <div className="field">
              <label>SCM 타입</label>
              <select value={form.scm_type} onChange={e => setForm(p => ({ ...p, scm_type: e.target.value }))}>
                <option value="git">Git</option>
                <option value="svn">SVN</option>
              </select>
            </div>
            <div className="field">
              <label>브랜치 (Git)</label>
              <input value={form.branch} onChange={e => setForm(p => ({ ...p, branch: e.target.value }))} placeholder="main" />
            </div>
            <div className="field span-2">
              <label>SCM URL</label>
              <input value={form.scm_url} onChange={e => setForm(p => ({ ...p, scm_url: e.target.value }))} placeholder="https://github.com/org/repo.git" />
            </div>
            <div className="field">
              <label>사용자명</label>
              <input value={form.scm_username} onChange={e => setForm(p => ({ ...p, scm_username: e.target.value }))} />
            </div>
            <div className="field">
              <label>비밀번호 환경변수명</label>
              <input value={form.scm_password_env} onChange={e => setForm(p => ({ ...p, scm_password_env: e.target.value }))} placeholder="SCM_PASSWORD" />
            </div>
            <div className="field">
              <label>Base Ref</label>
              <input value={form.base_ref} onChange={e => setForm(p => ({ ...p, base_ref: e.target.value }))} placeholder="HEAD~1" />
            </div>
            <div className="field span-2">
              <label>소스 루트 (복수 경로 지원)</label>
              <SourceRootEditor
                value={form.source_root}
                onChange={v => setForm(p => ({ ...p, source_root: v }))}
              />
            </div>
          </div>
          <div className="settings-section-title" style={{ fontSize: 12, marginBottom: 8, paddingBottom: 8 }}>연결 문서 경로</div>
          <div className="field-group cols-3">
            {['srs', 'sds', 'uds', 'sts', 'suts', 'sits', 'hsis', 'stp'].map(k => (
              <div className="field" key={k}>
                <label>{k.toUpperCase()} 경로</label>
                <div style={{ display: 'flex', gap: 4 }}>
                  <input
                    style={{ flex: 1 }}
                    value={form.linked_docs[k] || ''}
                    onChange={e => setLinked(k, e.target.value)}
                    placeholder={`/docs/${k}.docx`}
                  />
                  <button
                    type="button"
                    className="btn-sm"
                    title="파일 찾기 (클라우디움 모드면 worker IPC, 로컬이면 backend tkinter)"
                    onClick={() => pickLinkedDoc(k)}
                  >📂</button>
                </div>
              </div>
            ))}
          </div>
          <button className="btn-primary" onClick={saveScm} style={{ marginTop: 8 }}>{editMode ? '수정 저장' : '등록'}</button>
        </div>
      )}

      {list.length === 0 ? (
        <div className="text-muted text-sm">등록된 SCM이 없습니다.</div>
      ) : (
        <table className="impact-table">
          <thead>
            <tr><th>ID</th><th>이름</th><th>타입</th><th>URL</th><th></th></tr>
          </thead>
          <tbody>
            {list.map(s => (
              <tr key={s.id}>
                <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{s.id}</td>
                <td>{s.name}</td>
                <td><span className="pill pill-info">{s.scm_type?.toUpperCase()}</span></td>
                <td className="text-sm" style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.scm_url}</td>
                <td style={{ display: 'flex', gap: 4 }}>
                  <button className="btn-sm" onClick={() => { setForm({ ...defaultScmForm(), ...s, linked_docs: { ...defaultScmForm().linked_docs, ...(s.linked_docs || {}) } }); setShowForm(true); setEditMode(s.id); }}>편집</button>
                  <button className="btn-sm" style={{ color: 'var(--danger)', borderColor: 'var(--danger)' }} onClick={() => deleteScm(s.id)}>삭제</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/* ── 입력 문서 설정 ───────────────────────────────────────────────── */
const DOC_KEY = 'devops_v2_doc_paths';

function DocInputSection() {
  const toast = useToast();
  const [paths, setPaths] = useState(() => {
    try { return JSON.parse(localStorage.getItem(DOC_KEY) || '{}'); } catch (_) { return {}; }
  });

  const set = (k, v) => {
    const next = { ...paths, [k]: v };
    setPaths(next);
    localStorage.setItem(DOC_KEY, JSON.stringify(next));
  };

  return (
    <div className="settings-section">
      <div className="settings-section-title">📋 입력 문서 설정</div>
      <div className="field-group">
        {[
          { key: 'srs', label: 'SRS 파일 경로', ph: 'C:/docs/SRS_v1.docx' },
          { key: 'sds', label: 'SDS 파일 경로', ph: 'C:/docs/SDS_v1.docx' },
          { key: 'template', label: 'UDS 템플릿 경로', ph: 'C:/templates/UDS_template.docx' },
        ].map(({ key, label, ph }) => (
          <div className="field span-2" key={key}>
            <label>{label}</label>
            <input value={paths[key] || ''} onChange={e => set(key, e.target.value)} placeholder={ph} />
          </div>
        ))}
      </div>
    </div>
  );
}

/* ── 품질 기준 ───────────────────────────────────────────────────── */
const QUALITY_KEY = 'devops_v2_quality';

function QualitySection() {
  const [q, setQ] = useState(() => {
    try { return JSON.parse(localStorage.getItem(QUALITY_KEY) || '{}'); } catch (_) { return {}; }
  });

  const set = (k, v) => {
    const next = { ...q, [k]: v };
    setQ(next);
    localStorage.setItem(QUALITY_KEY, JSON.stringify(next));
  };

  return (
    <div className="settings-section">
      <div className="settings-section-title">⚙️ 품질 기준</div>
      <div className="field-group cols-3">
        <div className="field">
          <label>복잡도 임계값</label>
          <input type="number" value={q.complexity ?? 15} onChange={e => set('complexity', Number(e.target.value))} min={1} max={50} />
        </div>
        <div className="field">
          <label>커버리지 기준 (%)</label>
          <input type="number" value={q.coverage ?? 80} onChange={e => set('coverage', Number(e.target.value))} min={0} max={100} />
        </div>
        <div className="field">
          <label>Quality Preset</label>
          <select value={q.preset ?? 'high'} onChange={e => set('preset', e.target.value)}>
            <option value="high">High</option>
            <option value="balanced">Balanced</option>
            <option value="fast">Fast</option>
          </select>
        </div>
      </div>
    </div>
  );
}

/* ── File Mode Section ── */
function FileModeSection() {
  const toast = useToast();
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(false);
  const [picking, setPicking] = useState(false);
  const [gateStatus, setGateStatus] = useState(null);
  const [pickedResult, setPickedResult] = useState(null);
  const [cloudiumCfg, setCloudiumCfg] = useState({
    allowed_prefixes: '',
    gate_process: '',
  });

  const loadConfig = useCallback(async () => {
    try {
      const data = await api('/api/file-mode');
      setConfig(data);
      if (data.mode === 'cloudium') {
        setCloudiumCfg({
          allowed_prefixes: (data.allowed_prefixes || []).join(', '),
          gate_process: data.gate_process || '',
        });
        setGateStatus({
          gate_process: data.gate_process || '',
          gate_running: !!data.gate_running,
        });
      } else {
        setGateStatus(null);
      }
    } catch (e) {
      console.warn('File mode config load failed:', e.message);
    }
  }, []);

  useEffect(() => { loadConfig(); }, [loadConfig]);

  // cloudium 모드일 때 게이트 프로세스 실행 상태 5초 폴링
  useEffect(() => {
    if (config?.mode !== 'cloudium') return;
    let cancelled = false;
    const poll = async () => {
      try {
        const data = await post('/api/file-mode/check-access', {});
        if (cancelled) return;
        if (typeof data?.gate_running === 'boolean') {
          setGateStatus({
            gate_process: data.gate_process || '',
            gate_running: data.gate_running,
          });
        }
      } catch {
        // 무시 (다음 틱 재시도)
      }
    };
    poll();
    const id = setInterval(poll, 5000);
    return () => { cancelled = true; clearInterval(id); };
  }, [config?.mode]);

  const switchMode = async (mode) => {
    setLoading(true);
    try {
      const body = mode === 'cloudium' ? { mode, ...cloudiumCfg } : { mode };
      const data = await post('/api/file-mode', body);
      setConfig(data);
      toast('success', `파일 모드 변경: ${mode.toUpperCase()}`);
    } catch (e) {
      toast('error', `모드 전환 실패: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  // 클라우디움 모드용 — worker IPC를 통해 다이얼로그를 띄움 (worker가 권한 보유)
  // → 클라우디움 폴더가 다이얼로그에 보임. local 모드면 backend 자체 tkinter fallback.
  const pickAndPreview = async () => {
    setPicking(true);
    setPickedResult(null);
    try {
      // 1. cloudium이면 worker IPC, local이면 backend tkinter — 통합 진입점
      const picked = await post('/api/file-mode/browse-file', {
        title: 'Cloudium에서 파일 선택',
        kind: 'file',
      });
      if (!picked.ok || !picked.path) {
        if (picked.error === 'cancelled') {
          toast('info', '파일 선택 취소됨');
        } else {
          toast('error', `다이얼로그 실패: ${picked.error || 'unknown'}`);
        }
        return;
      }
      const filePath = picked.path;

      // 2. 부모 디렉토리 자동으로 allowed_prefixes에 추가
      const lastSlash = Math.max(filePath.lastIndexOf('/'), filePath.lastIndexOf('\\'));
      const parent = lastSlash >= 0 ? filePath.slice(0, lastSlash) : filePath;
      const existing = (cloudiumCfg.allowed_prefixes || '')
        .split(',').map(s => s.trim()).filter(Boolean);
      let newPrefixes = cloudiumCfg.allowed_prefixes;
      if (!existing.some(p => parent === p || parent.startsWith(p + '/') || parent.startsWith(p + '\\'))) {
        const merged = [...existing, parent];
        newPrefixes = merged.join(', ');
        setCloudiumCfg(prev => ({ ...prev, allowed_prefixes: newPrefixes }));
        await post('/api/file-mode', {
          mode: 'cloudium',
          allowed_prefixes: newPrefixes,
          gate_process: cloudiumCfg.gate_process || 'excel_rename_gui_v2.exe',
        });
      }

      // 3. preview-excel 호출 (파일 형식별 자동 판별 — 같은 endpoint가 xlsx/csv/txt 모두 처리)
      try {
        const data = await post('/api/preview-excel', { path: filePath, page: 0, page_size: 5 });
        setPickedResult({ ok: true, path: filePath, parent, data });
        toast('success', `읽기 성공: 시트 ${data.sheet_names?.length || 0}개`);
      } catch (readErr) {
        setPickedResult({ ok: false, path: filePath, parent, error: readErr.message });
        toast('error', `읽기 실패: ${readErr.message.slice(0, 100)}`);
      }
    } catch (e) {
      toast('error', `처리 실패: ${e.message}`);
    } finally {
      setPicking(false);
    }
  };

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">파일 접근 모드</span>
        {config && (
          <span className={`pill ${config.mode === 'local' ? 'pill-success' : 'pill-info'}`}>
            {config.mode?.toUpperCase()}
          </span>
        )}
      </div>

      <div className="field-group">
        <div className="field">
          <label>모드 선택</label>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              className={config?.mode === 'local' ? 'btn-primary btn-sm' : 'btn-sm'}
              onClick={() => switchMode('local')}
              disabled={loading}
            >
              Local (로컬 파일시스템)
            </button>
            <button
              className={config?.mode === 'cloudium' ? 'btn-primary btn-sm' : 'btn-sm'}
              onClick={() => switchMode('cloudium')}
              disabled={loading}
            >
              Cloudium (원격 접근)
            </button>
          </div>
        </div>

        {config?.mode === 'local' && (
          <div className="text-sm text-muted" style={{ padding: 8, background: 'var(--bg)', borderRadius: 6 }}>
            로컬 파일시스템에서 직접 파일을 읽습니다. 서버와 같은 PC에 파일이 있어야 합니다.
          </div>
        )}

        {config?.mode === 'cloudium' && (
          <div style={{ padding: 8, background: 'var(--bg)', borderRadius: 6 }}>
            <div className="text-sm" style={{ marginBottom: 8, color: 'var(--text-muted)' }}>
              클라우디움 모드는 <b>읽기 전용</b>이며, 게이트 프로세스가 실행 중일 때만 파일을 로드할 수 있습니다.
              로컬 경로(C:/, D:/ 등)는 차단됩니다.
            </div>

            {gateStatus && (
              <div
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: 8, marginBottom: 8, borderRadius: 6,
                  background: gateStatus.gate_running ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)',
                  border: `1px solid ${gateStatus.gate_running ? 'rgba(34,197,94,0.4)' : 'rgba(239,68,68,0.4)'}`,
                }}
              >
                <span
                  style={{
                    width: 10, height: 10, borderRadius: '50%',
                    background: gateStatus.gate_running ? '#22c55e' : '#ef4444',
                    boxShadow: gateStatus.gate_running ? '0 0 6px #22c55e' : 'none',
                  }}
                />
                <div className="text-sm" style={{ flex: 1 }}>
                  {gateStatus.gate_running ? (
                    <>
                      <b>게이트 실행 중</b> — <code>{gateStatus.gate_process}</code> 권한으로 파일 로드 가능
                    </>
                  ) : (
                    <>
                      <b>게이트 미실행</b> — <code>{gateStatus.gate_process || 'excel_rename_gui_v2.exe'}</code> 를 실행해야 파일을 로드할 수 있습니다
                    </>
                  )}
                </div>
              </div>
            )}

            {/* 파일 찾기 — OS 다이얼로그로 선택 후 자동 prefix 등록 + read 테스트 */}
            <div style={{
              padding: 12, marginBottom: 8, borderRadius: 6,
              background: 'var(--bg-elevated, rgba(59,130,246,0.06))',
              border: '1px dashed rgba(59,130,246,0.4)',
            }}>
              <div className="text-sm" style={{ marginBottom: 8 }}>
                📁 <b>클라우디움 파일 검증</b> — 다이얼로그에서 파일을 선택하면 부모 폴더가 자동으로 허용 경로에 추가되고, 읽기를 시도합니다.
              </div>
              <button
                className="btn-primary"
                onClick={pickAndPreview}
                disabled={picking || loading}
                style={{ width: '100%' }}
              >
                {picking ? '⏳ 처리 중...' : '📂 파일 찾기 + 자동 읽기 테스트'}
              </button>

              {pickedResult && (
                <div style={{
                  marginTop: 8, padding: 8, borderRadius: 6,
                  background: pickedResult.ok ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
                  border: `1px solid ${pickedResult.ok ? 'rgba(34,197,94,0.4)' : 'rgba(239,68,68,0.4)'}`,
                }}>
                  <div className="text-sm" style={{ wordBreak: 'break-all', marginBottom: 4 }}>
                    <b>선택 경로:</b> <code style={{ fontSize: 11 }}>{pickedResult.path}</code>
                  </div>
                  <div className="text-sm" style={{ wordBreak: 'break-all', marginBottom: 4, color: 'var(--text-muted)' }}>
                    <b>등록된 부모:</b> <code style={{ fontSize: 11 }}>{pickedResult.parent}</code>
                  </div>
                  {pickedResult.ok ? (
                    <div className="text-sm">
                      ✅ <b>읽기 성공</b> — 시트 <code>{pickedResult.data?.sheet_names?.join(', ') || '(없음)'}</code> ({pickedResult.data?.sheets?.length || 0}개)
                    </div>
                  ) : (
                    <div className="text-sm" style={{ color: '#dc2626' }}>
                      ❌ <b>읽기 실패</b>: {pickedResult.error}
                    </div>
                  )}
                </div>
              )}
            </div>

            <details style={{ marginTop: 8 }}>
              <summary className="text-sm" style={{ cursor: 'pointer', color: 'var(--text-muted)' }}>
                고급 설정 (게이트 프로세스명 / 허용 경로 직접 편집)
              </summary>
              <div style={{ marginTop: 8 }}>
                <div className="field">
                  <label>게이트 프로세스명</label>
                  <input
                    type="text"
                    value={cloudiumCfg.gate_process}
                    onChange={e => setCloudiumCfg({ ...cloudiumCfg, gate_process: e.target.value })}
                    placeholder="excel_rename_gui_v2.exe"
                  />
                </div>
                <div className="field">
                  <label>허용 경로 (콤마로 구분)</label>
                  <input
                    type="text"
                    value={cloudiumCfg.allowed_prefixes}
                    onChange={e => setCloudiumCfg({ ...cloudiumCfg, allowed_prefixes: e.target.value })}
                    placeholder="//cloudium-server/project, Z:/shared"
                  />
                </div>
                <button
                  className="btn-primary btn-sm"
                  onClick={() => switchMode('cloudium')}
                  disabled={loading}
                  style={{ marginTop: 8 }}
                >
                  {loading ? '저장 중...' : '수동 저장'}
                </button>
              </div>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── 관리자 모드 ─────────────────────────────────────────────────── */
const _AH = 'a2d1c5b8e4f7'; // obfuscated hash fragment
function _vp(pw) {
  // simple hash check (not crypto-grade, but sufficient for UI gate)
  let h = 0;
  for (let i = 0; i < pw.length; i++) h = ((h << 5) - h + pw.charCodeAt(i)) | 0;
  return h === 1974483555;
}

function AdminSection() {
  const toast = useToast();
  const [admin, setAdmin] = useState(localStorage.getItem('devops_admin_mode') === 'true');
  const [pwInput, setPwInput] = useState('');
  const [showPwForm, setShowPwForm] = useState(false);

  const activate = () => {
    if (!_vp(pwInput)) {
      toast('error', '비밀번호가 올바르지 않습니다.');
      return;
    }
    localStorage.setItem('devops_admin_mode', 'true');
    setAdmin(true);
    setPwInput('');
    setShowPwForm(false);
    window.dispatchEvent(new Event('storage'));
    toast('success', '관리자 모드가 활성화되었습니다.');
  };

  const deactivate = () => {
    localStorage.removeItem('devops_admin_mode');
    setAdmin(false);
    window.dispatchEvent(new Event('storage'));
    toast('info', '관리자 모드가 비활성화되었습니다.');
  };

  return (
    <div className="settings-section">
      <div className="settings-section-title">🔒 관리자 모드</div>
      {admin ? (
        <div className="field-group">
          <div className="field">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="pill pill-success" style={{ fontSize: 11 }}>활성화됨</span>
              <span className="text-sm">Quality 대시보드 등 관리자 전용 탭이 표시됩니다.</span>
            </div>
            <button className="btn-sm" style={{ marginTop: 8 }} onClick={deactivate}>
              관리자 모드 해제
            </button>
          </div>
          <UdsTemplateAdminBlock />
        </div>
      ) : (
        <div className="field-group">
          <div className="field">
            <div className="text-sm text-muted" style={{ marginBottom: 8 }}>
              관리자 비밀번호를 입력하여 활성화하세요.
            </div>
            {showPwForm ? (
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="password"
                  value={pwInput}
                  onChange={e => setPwInput(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && activate()}
                  placeholder="비밀번호"
                  style={{ maxWidth: 200 }}
                  autoFocus
                />
                <button className="btn-primary btn-sm" onClick={activate}>확인</button>
                <button className="btn-sm" onClick={() => { setShowPwForm(false); setPwInput(''); }}>취소</button>
              </div>
            ) : (
              <button className="btn-sm" onClick={() => setShowPwForm(true)}>
                관리자 모드 활성화
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ── UDS 템플릿 서버 설정 (관리자 전용) ──────────────────────────── */
function UdsTemplateAdminBlock() {
  const toast = useToast();
  const [info, setInfo] = useState(null);
  const [pathInput, setPathInput] = useState('');
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);

  const reload = useCallback(async () => {
    const data = await fetchServerUdsTemplate();
    setInfo(data);
    setPathInput(data?.template_path || '');
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const savePath = async () => {
    setSaving(true);
    try {
      const res = await saveServerUdsTemplate(pathInput.trim());
      toast('success', `저장됨: ${res.effective_path || '(기본값)'}`);
      await reload();
    } catch (e) {
      toast('error', `저장 실패: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const clearPath = async () => {
    if (!window.confirm('서버 저장 경로를 지워 환경변수 기본값으로 되돌립니다. 진행할까요?')) return;
    setSaving(true);
    try {
      await saveServerUdsTemplate('');
      setPathInput('');
      toast('info', '경로가 초기화되어 환경 기본값을 사용합니다.');
      await reload();
    } catch (e) {
      toast('error', `초기화 실패: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const onUpload = async (ev) => {
    const file = ev.target.files?.[0];
    ev.target.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.docx')) {
      toast('warning', '.docx 파일만 업로드할 수 있습니다.');
      return;
    }
    setUploading(true);
    try {
      const res = await uploadServerUdsTemplate(file);
      toast('success', `업로드 완료: ${res.template_path}`);
      await reload();
    } catch (e) {
      toast('error', `업로드 실패: ${e.message}`);
    } finally {
      setUploading(false);
    }
  };

  const effective = info?.effective_path || '';
  const saved = info?.template_path || '';
  const fallback = info?.default_path || '';

  return (
    <div className="field" style={{ marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
      <div style={{ fontWeight: 600, marginBottom: 6 }}>📄 UDS docx 템플릿 (서버 공통)</div>
      <div className="text-sm text-muted" style={{ marginBottom: 8 }}>
        UDS 생성 시 사용할 기본 템플릿입니다. 프론트엔드에서 요청할 때 별도 경로를 지정하지 않으면 이 값이 사용됩니다.
      </div>
      <div style={{ display: 'grid', gap: 4, fontSize: 12, marginBottom: 10 }}>
        <div>현재 사용 경로: <code>{effective || '(없음)'}</code> {info?.exists ? <span className="pill pill-success" style={{ fontSize: 10 }}>OK</span> : <span className="pill pill-warning" style={{ fontSize: 10 }}>파일 없음</span>}</div>
        <div>서버 저장 경로: <code>{saved || '(비어있음 → 환경변수 사용)'}</code></div>
        <div>환경 기본값: <code>{fallback || '(미설정)'}</code></div>
        {info?.last_saved_at && (
          <div className="text-muted">마지막 변경: {info.last_saved_at} — {info.last_saved_by || 'unknown'}</div>
        )}
      </div>

      <div className="text-sm" style={{ marginBottom: 4 }}>경로 지정 (서버 내 절대경로 또는 repo 상대경로)</div>
      <div style={{ display: 'flex', gap: 6, marginBottom: 10 }}>
        <input
          type="text"
          value={pathInput}
          onChange={(e) => setPathInput(e.target.value)}
          placeholder="docs/(HDPDM01_SUDS)_template_tokenized.docx"
          style={{ flex: 1, minWidth: 0 }}
        />
        <button className="btn-primary btn-sm" onClick={savePath} disabled={saving}>
          {saving ? '저장 중…' : '저장'}
        </button>
        <button className="btn-sm" onClick={clearPath} disabled={saving} title="서버 경로 지움 → 환경 기본값 사용">
          초기화
        </button>
      </div>

      <div className="text-sm" style={{ marginBottom: 4 }}>또는 docx 파일 업로드</div>
      <div className="text-sm text-muted" style={{ marginBottom: 6 }}>
        ⚠ 업로드 즉시 서버 공통 기본 템플릿으로 적용됩니다. 동일한 파일명이 이미 있으면 덮어쓰기됩니다.
      </div>
      <div>
        <label className="btn-sm" style={{ cursor: uploading ? 'wait' : 'pointer', display: 'inline-block' }}>
          {uploading ? '업로드 중…' : '파일 선택 (.docx)'}
          <input type="file" accept=".docx" onChange={onUpload} disabled={uploading} style={{ display: 'none' }} />
        </label>
      </div>
    </div>
  );
}

/* ── Source Root Editor (복수 경로 지원) ──────────────────────────── */
function SourceRootEditor({ value, onChange }) {
  const paths = (value || '').split(',').map(p => p.trim()).filter(Boolean);
  const [newPath, setNewPath] = useState('');

  const addPath = () => {
    const p = newPath.trim();
    if (!p) return;
    const updated = [...paths, p];
    onChange(updated.join(','));
    setNewPath('');
  };

  const removePath = (idx) => {
    const updated = paths.filter((_, i) => i !== idx);
    onChange(updated.join(','));
  };

  return (
    <div>
      {paths.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          {paths.map((p, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 6, padding: '3px 0',
              borderBottom: '1px solid var(--border-light, var(--border))',
            }}>
              <span style={{ fontSize: 11, fontFamily: 'monospace', flex: 1, wordBreak: 'break-all' }}>{p}</span>
              <button
                type="button"
                onClick={() => removePath(i)}
                style={{
                  background: 'none', border: 'none', color: 'var(--color-danger, red)',
                  cursor: 'pointer', fontSize: 14, padding: '0 4px', lineHeight: 1,
                }}
                title="경로 제거"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          value={newPath}
          onChange={e => setNewPath(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addPath())}
          placeholder="D:\Project\Sources\APP"
          style={{ flex: 1, fontSize: 12 }}
        />
        <button type="button" onClick={addPath} className="btn-sm" style={{ whiteSpace: 'nowrap' }}>
          + 경로 추가
        </button>
      </div>
      {paths.length === 0 && (
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
          소스 코드 경로를 추가하세요. 부트/어플 분리 프로젝트는 여러 경로를 추가할 수 있습니다.
        </div>
      )}
    </div>
  );
}
