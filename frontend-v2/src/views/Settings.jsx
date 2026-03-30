import { useState, useEffect, useCallback } from 'react';
import { useJenkinsCfg, useToast } from '../App.jsx';
import { post, api } from '../api.js';

export default function Settings() {
  return (
    <div className="settings-layout">
      <JenkinsSection />
      <ScmSection />
      <DocInputSection />
      <QualitySection />
    </div>
  );
}

/* ── Jenkins 연결 ─────────────────────────────────────────────────── */
function JenkinsSection() {
  const { cfg, update } = useJenkinsCfg();
  const toast = useToast();
  const [testing, setTesting] = useState(false);

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
      <button onClick={testConnection} disabled={testing}>
        {testing ? <><span className="spinner" /> 연결 테스트 중...</> : '연결 테스트'}
      </button>
    </div>
  );
}

/* ── SCM 레지스트리 ───────────────────────────────────────────────── */
function ScmSection() {
  const toast = useToast();
  const [list, setList] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
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
      linked_docs: { srs: '', sds: '', uds: '', sts: '', suts: '' },
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
      await post('/api/scm/register', form);
      toast('success', 'SCM 등록 완료');
      setShowForm(false);
      setForm(defaultScmForm());
      loadList();
    } catch (e) {
      toast('error', `등록 실패: ${e.message}`);
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

  return (
    <div className="settings-section">
      <div className="settings-section-title">
        🌿 SCM 레지스트리
        <div style={{ flex: 1 }} />
        <button onClick={() => setShowForm(p => !p)}>
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
            <div className="field">
              <label>소스 루트</label>
              <input value={form.source_root} onChange={e => setForm(p => ({ ...p, source_root: e.target.value }))} placeholder="/src" />
            </div>
          </div>
          <div className="settings-section-title" style={{ fontSize: 12, marginBottom: 8, paddingBottom: 8 }}>연결 문서 경로</div>
          <div className="field-group cols-3">
            {['srs', 'sds', 'uds', 'sts', 'suts'].map(k => (
              <div className="field" key={k}>
                <label>{k.toUpperCase()} 경로</label>
                <input value={form.linked_docs[k]} onChange={e => setLinked(k, e.target.value)} placeholder={`/docs/${k}.docx`} />
              </div>
            ))}
          </div>
          <button className="btn-primary" onClick={saveScm} style={{ marginTop: 8 }}>저장</button>
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
                <td><button className="btn-sm" style={{ color: 'var(--danger)', borderColor: 'var(--danger)' }} onClick={() => deleteScm(s.id)}>삭제</button></td>
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
