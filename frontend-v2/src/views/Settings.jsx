import { useState, useEffect, useCallback, useId } from 'react';
import { useJenkinsCfg, useToast } from '../App.jsx';
import {
  post, api, saveServerJenkinsConfig,
  fetchServerUdsTemplate, saveServerUdsTemplate, uploadServerUdsTemplate,
} from '../api.js';
import {
  loadSharedInputs, saveSharedInputs, SHARED_FIELD_GROUPS, saveDocPaths,
} from '../sharedInputs.js';
import { notifyScmRegistryChanged } from '../scmLinkedDocs.js';

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
      linked_docs: {
        srs: '', sds: '', uds: '', sts: '', suts: '', sits: '', hsis: '', stp: '',
        // 문서별 생성 템플릿(UDS .docx / 시험 규격서 .xlsm) — 형식이 달라 키를 나눈다.
        uds_template: '', sts_template: '', suts_template: '', sits_template: '',
        vectorcast: [], codesonar: [],
      },
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
        // api() 헬퍼 사용 — X-User 헤더 자동 추가 + res.ok 검사 + 에러 throw.
        // 이전 raw fetch는 X-User 누락으로 401 silent failure 발생.
        await api(`/api/scm/update/${editMode}`, {
          method: 'PUT',
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
      // ⚠ 마운트된 프로젝트 섹션들에 통지. 없으면 Detail 이 keep-alive(display:none)라
      //   재마운트되지 않아 '입력 문서 현황'/추적성 매트릭스가 전체 새로고침 전까지
      //   옛 경로를 계속 쓴다(사용자 재보고 결함). doc_paths 쪽 saveDocPaths 와 대칭.
      notifyScmRegistryChanged();
    } catch (e) {
      toast('error', `${editMode ? '수정' : '등록'} 실패: ${e.message}`);
    }
  };

  const deleteScm = async (id) => {
    if (!confirm(`SCM '${id}'를 삭제하시겠습니까?`)) return;
    try {
      // 실제 backend endpoint는 /api/scm/delete/{id} (이전 raw fetch는 잘못된
      // 경로로 호출 + X-User 누락 — api 헬퍼로 전환하여 둘 다 해결).
      await api(`/api/scm/delete/${id}`, { method: 'DELETE' });
      toast('success', '삭제 완료');
      loadList();
      notifyScmRegistryChanged();
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

  // VectorCAST 결과 로그는 복수 경로(부트로더/FBL/APP 별도 결과). linked_docs.vectorcast
  // 는 string[] — setLinked(단일 string)와 달리 array 전체를 교체한다.
  const setVcastPaths = (arr) =>
    setForm(p => ({ ...p, linked_docs: { ...p.linked_docs, vectorcast: Array.isArray(arr) ? arr : [] } }));

  const pickVcastPath = async () => {
    try {
      // 연결 문서 경로 = 폴더(경로)만 등록. 백엔드 로더가 폴더 안의
      // vectorcast_rag.json(또는 표준 하위 경로)을 탐색하므로 directory를 고른다.
      const picked = await post('/api/file-mode/browse-file', {
        title: 'VectorCAST 결과 폴더 선택 (부트로더/FBL/APP 결과 상위 폴더)',
        kind: 'directory',
      });
      if (!picked || !picked.ok || !picked.path) {
        if (picked?.error === 'cancelled') return;
        toast('error', `다이얼로그 실패: ${picked?.error || picked?.detail || 'unknown'}`);
        return;
      }
      const cur = Array.isArray(form.linked_docs.vectorcast) ? form.linked_docs.vectorcast : [];
      if (cur.includes(picked.path)) {
        toast('info', '이미 추가된 경로입니다.');
        return;
      }
      setVcastPaths([...cur, picked.path]);
      await ensureCloudiumPrefix(picked.path);
      toast('success', 'VectorCAST 폴더 추가됨');
    } catch (e) {
      toast('error', `다이얼로그 실패: ${e.message}`);
    }
  };

  // 정적분석 폴더(codesonar)도 복수 경로 — CodeSonar/QAC HIS/CPD/CodeEye 리포트 폴더.
  // 테스트 결과 '정적분석' 패널이 linked_docs.codesonar를 읽으므로 vectorcast와 별도 필드로 관리.
  const setCodesonarPaths = (arr) =>
    setForm(p => ({ ...p, linked_docs: { ...p.linked_docs, codesonar: Array.isArray(arr) ? arr : [] } }));

  const pickCodesonarPath = async () => {
    try {
      const picked = await post('/api/file-mode/browse-file', {
        title: '정적분석 폴더 선택 (CodeSonar/QAC/CPD/CodeEye 리포트 상위 폴더)',
        kind: 'directory',
      });
      if (!picked || !picked.ok || !picked.path) {
        if (picked?.error === 'cancelled') return;
        toast('error', `다이얼로그 실패: ${picked?.error || picked?.detail || 'unknown'}`);
        return;
      }
      const cur = Array.isArray(form.linked_docs.codesonar) ? form.linked_docs.codesonar : [];
      if (cur.includes(picked.path)) { toast('info', '이미 추가된 경로입니다.'); return; }
      setCodesonarPaths([...cur, picked.path]);
      await ensureCloudiumPrefix(picked.path);
      toast('success', '정적분석 폴더 추가됨');
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
            {/* 템플릿은 **문서마다 형식이 다르다**(UDS .docx / 시험 규격서 .xlsm).
                예전엔 필드가 없어 설정의 공용 `template` 하나가 양쪽에 갔다. */}
            {['srs', 'sds', 'uds', 'sts', 'suts', 'sits', 'hsis', 'stp', 'syrs', 'syts', 'syits',
              'uds_template', 'sts_template', 'suts_template', 'sits_template'].map(k => (
              <div className="field" key={k}>
                <label>{k.toUpperCase()} 경로</label>
                <div style={{ display: 'flex', gap: 4 }}>
                  <input
                    style={{ flex: 1 }}
                    value={form.linked_docs[k] || ''}
                    onChange={e => setLinked(k, e.target.value)}
                    placeholder={['syts', 'syits', 'hsis'].includes(k) ? `/docs/${k}.xlsx` : `/docs/${k}.docx`}
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
          <div className="field span-2" style={{ marginTop: 8 }}>
            <label>VectorCAST 결과 로그 (복수 경로 — 부트로더/FBL/APP 별도 결과)</label>
            <VcastDocsEditor
              paths={form.linked_docs.vectorcast}
              onChange={setVcastPaths}
              onBrowse={pickVcastPath}
            />
          </div>
          <div className="field span-2" style={{ marginTop: 8 }}>
            <label>정적분석 폴더 (CodeSonar·QAC HIS·CPD·CodeEye 리포트 — 복수 경로)</label>
            <VcastDocsEditor
              paths={form.linked_docs.codesonar}
              onChange={setCodesonarPaths}
              onBrowse={pickCodesonarPath}
              placeholder="U:\...\09.정적분석\01.Static Analysis (폴더 경로)"
              hint="테스트 결과 '정적분석' 패널이 이 폴더에서 CodeSonar(PDF)·CPD(XML)·QAC HIS(PDF)·CodeEye(PDF)를 찾아 표시합니다. VectorCAST 결과 로그와는 다른 필드입니다."
            />
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

/* ── 입력 자료 설정 (문서 + 템플릿/로그/메타 일원화) ───────────────── */
const DOC_KEY = 'devops_v2_doc_paths';

// devops_v2_doc_paths 키. DocGenSection 생성 payload는 srs/sds/template + (백엔드 수용
// 범위 내) hsis/stp/uds를 docPaths 우선 폴백으로 사용한다. uds/sts/suts/sits는 주로
// '문서 현황' 미리보기/참조용이며 생성기별로 수용 여부가 다르다(아래 '(참조)' 표기).
const DOC_FIELDS = [
  { key: 'srs', label: 'SRS 경로', ph: 'C:/docs/SRS_v1.docx', browse: 'file' },
  { key: 'sds', label: 'SDS 경로', ph: 'C:/docs/SDS_v1.docx', browse: 'file' },
  { key: 'hsis', label: 'HSIS 경로', ph: 'C:/docs/HSIS.docx', browse: 'file' },
  { key: 'stp', label: 'STP 경로', ph: 'C:/docs/STP.docx', browse: 'file' },
  { key: 'uds', label: 'UDS 경로 (참조)', ph: 'C:/docs/UDS.docx', browse: 'file' },
  { key: 'sts', label: 'STS 경로 (참조)', ph: 'C:/docs/STS.docx', browse: 'file' },
  { key: 'suts', label: 'SUTS 경로 (참조)', ph: 'C:/docs/SUTS.docx', browse: 'file' },
  { key: 'sits', label: 'SITS 경로 (참조)', ph: 'C:/docs/SITS.docx', browse: 'file' },
  { key: 'template', label: 'UDS 템플릿 경로', ph: 'C:/templates/UDS_template.docx', browse: 'file' },
];

// 경로 입력 + 📂 찾기(파일/폴더) 한 줄 필드. onBrowse 없으면 input만.
function PathField({ label, value, ph, onChange, onBrowse, span2 = false, multiline = false }) {
  const id = useId();
  return (
    <div className={`field${span2 || multiline ? ' span-2' : ''}`}>
      <label htmlFor={id}>{label}</label>
      {multiline ? (
        <textarea id={id} rows={3} value={value} onChange={e => onChange(e.target.value)} placeholder={ph} spellCheck="false" autoComplete="off" />
      ) : (
        <div style={{ display: 'flex', gap: 4 }}>
          <input id={id} style={{ flex: 1 }} value={value} onChange={e => onChange(e.target.value)} placeholder={ph} spellCheck="false" autoComplete="off" />
          {onBrowse && (
            <button type="button" className="btn-sm" title="파일/폴더 찾기 (클라우디움이면 worker IPC, 로컬이면 backend)" onClick={onBrowse}>📂</button>
          )}
        </div>
      )}
    </div>
  );
}

// linked_docs(SCM 연결문서)에서 상속 가능한 doc_paths 키.
//
// ⚠ 템플릿은 이제 linked_docs 에 **있다**(`uds_template` 등, 문서별로 형식이 다르다).
//   다만 여기 넣지 않는 이유는 `doc_paths`(설정>입력 자료)에 대응 필드가 없기 때문이다 —
//   생성 시 `DocGenSection` 이 레지스트리를 직접 읽는다. `doc_paths` 에 템플릿 입력을
//   추가하려면 이 목록도 함께 늘릴 것.
// vectorcast/codesonar 는 복수 경로 list 라 단일 문서 필드와 매핑되지 않는다.
const SCM_INHERIT_KEYS = ['srs', 'sds', 'hsis', 'stp', 'uds', 'sts', 'suts', 'sits'];
const DOC_SCM_KEY = 'devops_v2_doc_scm';

function DocInputSection() {
  const toast = useToast();
  const [paths, setPaths] = useState(() => {
    try { return JSON.parse(localStorage.getItem(DOC_KEY) || '{}'); } catch (_) { return {}; }
  });
  const [shared, setShared] = useState(loadSharedInputs);
  // 입력 자료 = SCM 레지스트리 연결문서와 겹침 → 기준 SCM을 고르면 그 linked_docs를 상속(중복
  // 입력 제거). 빈 칸은 SCM 경로를 placeholder로 보여주고 '빈 칸 채우기'로 doc_paths에 복사
  // (생성 탭 prefill이 doc_paths를 읽으므로 그때 실제 사용됨). 직접 입력값은 항상 우선.
  const [scms, setScms] = useState([]);
  const [scmId, setScmId] = useState(() => localStorage.getItem(DOC_SCM_KEY) || '');
  useEffect(() => {
    (async () => {
      try {
        const data = await api('/api/scm/list');
        setScms(Array.isArray(data) ? data : (data.items ?? data.registries ?? []));
      } catch (_) { /* SCM 목록 없으면 상속 UI만 숨김 */ }
    })();
  }, []);
  const selectedScm = scms.find(s => s.id === scmId) || null;
  const scmLinks = selectedScm?.linked_docs || {};
  const pickScm = (id) => { setScmId(id); localStorage.setItem(DOC_SCM_KEY, id); };

  const setDoc = (k, v) => {
    const next = { ...paths, [k]: v };
    setPaths(next);
    // ⚠ 직접 setItem 하지 않는다 — saveDocPaths 가 같은 탭 구독자에게 통지한다.
    //   통지가 없으면 프로젝트 탭 섹션들이 keep-alive 라 재마운트되지 않아
    //   전체 새로고침 전까지 옛 경로를 계속 쓴다(사용자 보고 결함).
    saveDocPaths(next);
  };
  const setShr = (k, v) => {
    const next = { ...shared, [k]: v };
    setShared(next);
    saveSharedInputs(next);
  };

  // 선택 SCM의 linked_docs로 '빈 칸만' 채운다(직접 입력값은 보존). 생성 탭 prefill이
  // doc_paths를 읽으므로 한 번 채우면 같은 경로를 다시 입력할 필요가 없다.
  const fillFromScm = () => {
    if (!selectedScm) { toast('info', '기준 SCM을 먼저 선택하세요.'); return; }
    const next = { ...paths };
    let filled = 0;
    for (const k of SCM_INHERIT_KEYS) {
      const inh = (scmLinks[k] || '').trim();
      if (inh && !(next[k] || '').trim()) { next[k] = inh; filled += 1; }
    }
    if (!filled) { toast('info', '채울 빈 칸이 없습니다 (이미 입력됨 또는 SCM에 경로 없음).'); return; }
    setPaths(next);
    saveDocPaths(next);
    toast('success', `선택 SCM 연결문서로 빈 칸 ${filled}개를 채웠습니다.`);
  };

  // /api/file-mode/browse-file 재사용 (post 헬퍼 — X-User 포함). 선택 경로 반환 or null.
  const browse = async (kind) => {
    try {
      const picked = await post('/api/file-mode/browse-file', {
        title: kind === 'directory' ? '폴더 선택' : '파일 선택',
        kind: kind === 'directory' ? 'directory' : 'file',
      });
      if (!picked || !picked.ok || !picked.path) {
        if (picked?.error === 'cancelled') return null;
        toast('error', `다이얼로그 실패: ${picked?.error || picked?.detail || 'unknown'}`);
        return null;
      }
      return picked.path;
    } catch (e) {
      toast('error', `다이얼로그 실패: ${e.message}`);
      return null;
    }
  };

  return (
    <div className="settings-section">
      <div className="settings-section-title">📋 입력 자료 설정</div>
      <div className="text-sm text-muted" style={{ marginBottom: 12 }}>
        여기 등록한 문서·템플릿·로그 폴더는 <b>문서 생성</b> 탭의 각 생성기에서 칸이 비었을 때 자동으로 채워집니다(생성 탭에서 직접 입력하면 그 값이 우선).
      </div>

      {/* 기준 SCM 상속 — SCM 레지스트리 '연결 문서 경로'와 겹치는 입력을 한 번에 가져온다. */}
      {scms.length > 0 && (
        <div className="field-group" style={{ marginBottom: 10, padding: 8, border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg)' }}>
          <div className="field span-2">
            <label htmlFor="doc-scm-select">기준 SCM (연결 문서 상속)</label>
            <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
              <select id="doc-scm-select" style={{ flex: 1, minWidth: 160 }} value={scmId} onChange={e => pickScm(e.target.value)}>
                <option value="">(선택 안 함)</option>
                {scms.map(s => <option key={s.id} value={s.id}>{s.name || s.id}</option>)}
              </select>
              <button type="button" className="btn-sm" disabled={!selectedScm} onClick={fillFromScm}
                title="선택한 SCM의 연결 문서 경로(SRS/SDS/UDS/STS/SUTS/SITS/HSIS/STP)로 아래 빈 칸을 채웁니다. 직접 입력한 값은 보존됩니다.">
                빈 칸 채우기
              </button>
            </div>
            <div className="text-sm text-muted" style={{ marginTop: 4 }}>
              SCM 레지스트리의 연결 문서 경로와 중복 입력을 피합니다. 빈 칸은 선택 SCM 경로가 흐리게 표시되며, '빈 칸 채우기'로 복사합니다(직접 입력값 우선).
            </div>
          </div>
        </div>
      )}

      {/* 입력/참조 문서 (devops_v2_doc_paths) */}
      <div className="field-group cols-3">
        {DOC_FIELDS.map(f => {
          const explicit = paths[f.key] || '';
          const inherited = SCM_INHERIT_KEYS.includes(f.key) ? (scmLinks[f.key] || '').trim() : '';
          const inheritedActive = !explicit && !!inherited;
          return (
            <PathField
              key={f.key}
              label={f.label + (inheritedActive ? ' · SCM 상속' : '')}
              ph={inheritedActive ? `(상속: ${inherited})` : f.ph}
              value={explicit}
              onChange={v => setDoc(f.key, v)}
              onBrowse={async () => { const p = await browse(f.browse); if (p) setDoc(f.key, p); }}
            />
          );
        })}
      </div>

      {/* 공유 입력 그룹 — 템플릿 / 로그 폴더 / 공통 메타 (devops_v2_shared_inputs) */}
      {SHARED_FIELD_GROUPS.map(group => {
        const filled = group.keys.filter(k => shared[k.key]).length;
        return (
        <details key={group.title} open={group.open || filled > 0} style={{ marginTop: 8, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
          <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: 13, marginBottom: 8 }}>
            {group.title}
            <span className="text-muted" style={{ fontWeight: 400, fontSize: 11, marginLeft: 6 }}>
              ({filled}/{group.keys.length} 설정됨)
            </span>
          </summary>
          <div className="field-group cols-3">
            {group.keys.map(f => (
              <PathField
                key={f.key}
                label={f.label}
                ph={f.ph}
                value={shared[f.key] || ''}
                multiline={!!f.multiline}
                onChange={v => setShr(f.key, v)}
                onBrowse={f.browse ? async () => { const p = await browse(f.browse); if (p) setShr(f.key, p); } : undefined}
              />
            ))}
          </div>
        </details>
        );
      })}
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

  // 사용자가 다이얼로그 결과 path를 클립보드에 복사 — 별도 화면 자동 활용은
  // 안 하고, 사용자가 Claude/CLI 등에 직접 지시할 때 paste용.
  const copyPathToClipboard = async () => {
    if (!pickedResult?.path) return;
    try {
      await navigator.clipboard.writeText(pickedResult.path);
      toast('success', '경로 클립보드에 복사됨');
    } catch (e) {
      toast('error', `복사 실패: ${e.message}`);
    }
  };
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
                  <div style={{
                    marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border)',
                    display: 'flex', gap: 6, alignItems: 'center',
                  }}>
                    <button
                      type="button"
                      className="btn-sm"
                      onClick={copyPathToClipboard}
                      title="경로를 클립보드에 복사 — Claude/CLI에 직접 지시할 때 paste"
                    >📋 경로 복사</button>
                    <span className="text-sm text-muted" style={{ fontSize: 11 }}>
                      복사 후 Claude/CLI/다른 도구에 paste하여 활용
                    </span>
                  </div>
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

// VectorCAST 결과 로그 복수 경로 편집기. 부트로더/FBL/APP 등 결과가 별도
// vectorcast_rag.json으로 나올 수 있어 SCM별로 여러 경로를 등록한다. paths는
// string[] (SourceRootEditor의 콤마 string과 달리 array 그대로 다룸).
function VcastDocsEditor({ paths, onChange, onBrowse, placeholder, hint }) {
  const list = Array.isArray(paths) ? paths : [];
  const [draft, setDraft] = useState('');

  const addPath = () => {
    const p = draft.trim();
    if (!p) return;
    if (list.includes(p)) { setDraft(''); return; }
    onChange([...list, p]);
    setDraft('');
  };
  const removePath = (idx) => onChange(list.filter((_, i) => i !== idx));

  return (
    <div>
      {list.length > 0 && (
        <div style={{ marginBottom: 6 }}>
          {list.map((p, i) => (
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
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addPath())}
          placeholder={placeholder || "U:\\...\\report\\vectorcast_rag (폴더 경로)"}
          spellCheck="false"
          autoComplete="off"
          style={{ flex: 1, fontSize: 12 }}
        />
        <button type="button" onClick={addPath} className="btn-sm" style={{ whiteSpace: 'nowrap' }}>
          + 경로 추가
        </button>
        <button
          type="button"
          onClick={onBrowse}
          className="btn-sm"
          title="폴더 찾기 (클라우디움 모드면 worker IPC, 로컬이면 backend tkinter)"
        >📂</button>
      </div>
      {list.length === 0 && (
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
          {hint || '미등록 시 Jenkins 빌드의 VectorCAST RAG를 사용합니다. 부트로더 등 결과가 별도로 나오면 결과가 담긴 폴더 경로를 추가하세요(폴더 안의 vectorcast_rag.json을 자동 탐색).'}
        </div>
      )}
    </div>
  );
}
