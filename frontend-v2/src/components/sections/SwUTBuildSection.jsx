import { useState, useCallback, useEffect, useRef } from 'react';
import { getUsername } from '../../api.js';
import { useToast } from '../../App.jsx';
import PathPickerDialog from '../PathPickerDialog.jsx';

const API_BASE = (typeof window !== 'undefined' && window.__ARIA_API_BASE__)
  || import.meta.env?.VITE_API_BASE_URL || '';

function buildUrl(path) {
  if (!API_BASE) return path;
  return API_BASE.replace(/\/$/, '') + path;
}

const STORAGE_KEY = 'devops_v2_swut_form';

const DEFAULT_FORM = {
  project_id: 'HDPDM01',
  release_sw_version: '',
  test_date: '',
  test_engineer: '',
  doc_id_sequence: '',
  hw_version: '1.00',
  asil_level: 'ASIL A',
  log_folder: '',
  template_path: '',
  swuds_docx_path: '',
};

function loadSavedForm() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    return {
      ...DEFAULT_FORM,
      test_date: new Date().toISOString().slice(0, 10),
      ...saved,
    };
  } catch (e) {
    return { ...DEFAULT_FORM, test_date: new Date().toISOString().slice(0, 10) };
  }
}

function formatDetailMessage(detail) {
  if (Array.isArray(detail)) {
    return detail
      .map(d => {
        const loc = (d?.loc || []).filter(x => x !== 'body').join('.');
        const msg = d?.msg || d?.type || JSON.stringify(d);
        return loc ? `${loc}: ${msg}` : msg;
      })
      .join(', ');
  }
  if (typeof detail === 'string') return detail;
  if (detail && typeof detail === 'object') return JSON.stringify(detail);
  return '';
}

export default function SwUTBuildSection() {
  const toast = useToast();
  const [building, setBuilding] = useState(null);
  const [lastSummary, setLastSummary] = useState(null);
  const [lastWarnings, setLastWarnings] = useState([]);
  const [form, setForm] = useState(loadSavedForm);
  // 19차: 일관성 검증 state
  const [consistencyForm, setConsistencyForm] = useState({ coverage_path: '', sutr_path: '' });
  const [consistencyChecking, setConsistencyChecking] = useState(false);
  const [consistencyReport, setConsistencyReport] = useState(null);
  // 21차: PathPickerDialog state
  const [picker, setPicker] = useState(null);  // { target, pattern, title, onSelect }

  const openPicker = (target, pattern, title) => {
    let onSelect;
    if (target === 'consistency.coverage_path') {
      onSelect = v => setConsistencyForm(f => ({ ...f, coverage_path: v }));
    } else if (target === 'consistency.sutr_path') {
      onSelect = v => setConsistencyForm(f => ({ ...f, sutr_path: v }));
    } else {
      onSelect = v => setField(target, v);
    }
    setPicker({ target, pattern, title, onSelect });
  };

  const abortRef = useRef(null);
  const consistencyAbortRef = useRef(null);
  const mountedRef = useRef(true);
  // F5: 활성 blob URL + timer 추적 — unmount 시 즉시 revoke + clearTimeout.
  const downloadCleanupRef = useRef([]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      if (consistencyAbortRef.current) {
        consistencyAbortRef.current.abort();
        consistencyAbortRef.current = null;
      }
      // F5: 보류 중인 revoke timer를 정리하고, blob URL을 즉시 revoke
      downloadCleanupRef.current.forEach(({ timerId, url }) => {
        clearTimeout(timerId);
        try { URL.revokeObjectURL(url); } catch (e) { /* ignore */ }
      });
      downloadCleanupRef.current = [];
    };
  }, []);

  const setField = (k, v) => {
    const next = { ...form, [k]: v };
    setForm(next);
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch (e) {
      console.warn('SwUT form persist failed:', e?.message || e);
    }
  };

  const triggerDownload = (blob, filename) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    // F5: timer + url을 ref에 저장 — unmount 시 cleanup
    const timerId = setTimeout(() => {
      try { URL.revokeObjectURL(url); } catch (e) { /* ignore */ }
      downloadCleanupRef.current = downloadCleanupRef.current.filter(
        item => item.timerId !== timerId,
      );
    }, 5000);
    downloadCleanupRef.current.push({ timerId, url });
  };

  const buildXlsx = useCallback(async (kind) => {
    if (!form.project_id) { toast('warning', 'project_id 필수'); return; }
    if (!form.release_sw_version) { toast('warning', 'release_sw_version 필수'); return; }
    if (!form.test_date) { toast('warning', 'test_date 필수'); return; }
    if (!form.log_folder && !form.template_path) {
      toast('warning', 'log_folder 또는 template_path 중 하나는 필수'); return;
    }

    const user = getUsername();
    if (!user) { toast('warning', '사용자 이름이 설정되지 않음 — Settings 확인'); return; }

    setBuilding(kind);
    setLastSummary(null);
    setLastWarnings([]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(buildUrl(`/api/swut/${kind}/build`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-User': user,
        },
        body: JSON.stringify(form),
        signal: controller.signal,
      });

      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const j = await res.json();
          if (Array.isArray(j?.detail)) {
            msg = formatDetailMessage(j.detail);
          } else if (typeof j?.detail === 'string') {
            msg = j.detail;
          } else if (j?.message) {
            msg = j.message;
          }
        } catch (e) {
          // body가 JSON이 아닌 경우 (예: 502 HTML) — HTTP status만 표시
        }
        if (mountedRef.current) {
          toast('error', `${kind.toUpperCase()} 빌드 실패: ${msg}`);
        }
        return;
      }

      try {
        const summaryRaw = res.headers.get('X-SwUT-Summary');
        if (summaryRaw && mountedRef.current) setLastSummary(JSON.parse(summaryRaw));
        const warningsRaw = res.headers.get('X-SwUT-Warnings');
        if (warningsRaw && mountedRef.current) setLastWarnings(JSON.parse(warningsRaw));
      } catch (e) {
        console.warn('X-SwUT-* header parse failed:', e?.message || e);
      }

      const blob = await res.blob();
      const cd = res.headers.get('Content-Disposition') || '';
      const m = cd.match(/filename\*=UTF-8''([^;]+)/) || cd.match(/filename="([^"]+)"/);
      const filename = m ? decodeURIComponent(m[1]) : `swut_${kind}.xlsx`;

      if (!mountedRef.current) return;
      triggerDownload(blob, filename);
      toast('success', `${kind.toUpperCase()} ${(blob.size / 1024).toFixed(0)} KB 다운로드 완료`);
    } catch (e) {
      if (e?.name === 'AbortError') return;
      if (mountedRef.current) {
        toast('error', `${kind.toUpperCase()} 빌드 실패: ${e?.message || e}`);
      }
    } finally {
      if (mountedRef.current) setBuilding(null);
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, [form, toast]);

  // 19차: Coverage ↔ SUTR cross-validation 호출.
  const runConsistencyCheck = useCallback(async () => {
    if (!consistencyForm.coverage_path) {
      toast('warning', 'coverage_path 필수'); return;
    }
    if (!consistencyForm.sutr_path) {
      toast('warning', 'sutr_path 필수'); return;
    }
    const user = getUsername();
    if (!user) { toast('warning', '사용자 이름이 설정되지 않음 — Settings 확인'); return; }

    setConsistencyChecking(true);
    setConsistencyReport(null);
    const controller = new AbortController();
    consistencyAbortRef.current = controller;

    try {
      const res = await fetch(buildUrl('/api/swut/consistency/check'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-User': user },
        body: JSON.stringify(consistencyForm),
        signal: controller.signal,
      });

      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const j = await res.json();
          if (Array.isArray(j?.detail)) msg = formatDetailMessage(j.detail);
          else if (typeof j?.detail === 'string') msg = j.detail;
          else if (j?.error?.message) msg = j.error.message;
          else if (j?.message) msg = j.message;
        } catch (e) { /* non-JSON body */ }
        if (mountedRef.current) toast('error', `일관성 검증 실패: ${msg}`);
        return;
      }

      const report = await res.json();
      if (!mountedRef.current) return;
      setConsistencyReport(report);
      const issues = report?.issues || [];
      if (issues.length === 0) {
        toast('success', '일관성 검증 통과 — issue 0건');
      } else {
        toast('warning', `일관성 검증: issue ${issues.length}건 — 카드 확인`);
      }
    } catch (e) {
      if (e?.name === 'AbortError') return;
      if (mountedRef.current) toast('error', `일관성 검증 실패: ${e?.message || e}`);
    } finally {
      if (mountedRef.current) setConsistencyChecking(false);
      if (consistencyAbortRef.current === controller) consistencyAbortRef.current = null;
    }
  }, [consistencyForm, toast]);

  return (
    <div className="swut-section">
      <div className="swut-section-header">
        <h2>SwUT 빌드</h2>
        <p className="swut-section-desc">
          Coverage Report (xlsx) / SUTR (xlsm) 빌드 — Jenkins 캐시 우선, log_folder fallback.
          출력은 브라우저 다운로드 (로컬 디스크 저장). Cloudium은 read-only로 template/log만 접근.
        </p>
      </div>

      <div className="swut-form-grid">
        <Field name="project_id" label="Project ID *" value={form.project_id} onChange={v => setField('project_id', v)} placeholder="HDPDM01" />
        <Field name="release_sw_version" label="Release SW Version * (예: 2.02 또는 1.01.05)" value={form.release_sw_version} onChange={v => setField('release_sw_version', v)} placeholder="2.02" />
        <Field name="test_date" label="Test Date * (yyyy-mm-dd)" value={form.test_date} onChange={v => setField('test_date', v)} type="date" />
        <Field name="test_engineer" label="Test Engineer" value={form.test_engineer} onChange={v => setField('test_engineer', v)} placeholder="JK Kim" />
        <Field name="doc_id_sequence" label="Doc ID Sequence (digit)" value={form.doc_id_sequence} onChange={v => setField('doc_id_sequence', v)} placeholder="852" />
        <Field name="hw_version" label="HW Version" value={form.hw_version} onChange={v => setField('hw_version', v)} />
        <Field name="asil_level" label="ASIL Level" value={form.asil_level} onChange={v => setField('asil_level', v)} />
      </div>

      <div className="swut-form-row swut-field-with-browse">
        <Field
          name="log_folder"
          label="Log Folder (Jenkins 미사용 시 fallback)"
          value={form.log_folder}
          onChange={v => setField('log_folder', v)}
          placeholder="U:\연구소\...\01.Log\v2.02_240219"
          fullWidth
        />
        <button
          className="swut-browse-btn"
          type="button"
          onClick={() => openPicker('log_folder', '*', 'Log 디렉토리 선택')}
        >📂 Browse</button>
      </div>
      <div className="swut-form-row swut-field-with-browse">
        <Field
          name="template_path"
          label="Template Path (xlsx/xlsm — config default 사용 시 빈 string)"
          value={form.template_path}
          onChange={v => setField('template_path', v)}
          placeholder="U:\...\(HDPDM01)SwUT Coverage Report_v3.01_240221_R.xlsx"
          fullWidth
        />
        <button
          className="swut-browse-btn"
          type="button"
          onClick={() => openPicker('template_path', '*.xlsx,*.xlsm', 'Template 파일 선택')}
        >📂 Browse</button>
      </div>
      <div className="swut-form-row swut-field-with-browse">
        <Field
          name="swuds_docx_path"
          label="SwUDS Docx Path (선택 — 2.Consistency SwUDS↔SwUTS 매핑 자동화)"
          value={form.swuds_docx_path}
          onChange={v => setField('swuds_docx_path', v)}
          placeholder="U:\...\(HDPDM01)SwUDS_v3.docx"
          fullWidth
        />
        <button
          className="swut-browse-btn"
          type="button"
          onClick={() => openPicker('swuds_docx_path', '*.docx', 'SwUDS docx 선택')}
        >📂 Browse</button>
      </div>

      <div className="swut-actions">
        <button
          className="btn-primary"
          disabled={!!building}
          onClick={() => buildXlsx('coverage')}
        >
          {building === 'coverage' ? '빌드 중...' : '📊 Coverage Report 빌드 (xlsx)'}
        </button>
        <button
          className="btn-primary"
          disabled={!!building}
          onClick={() => buildXlsx('sutr')}
        >
          {building === 'sutr' ? '빌드 중...' : '📝 SUTR 빌드 (xlsm)'}
        </button>
      </div>

      {lastSummary && (
        <div className="swut-summary-card">
          <div className="swut-summary-title">마지막 빌드 결과</div>
          <pre className="swut-summary-pre">{JSON.stringify(lastSummary, null, 2)}</pre>
        </div>
      )}

      {lastWarnings.length > 0 && (
        <div className="swut-warnings-card">
          <div className="swut-warnings-title">⚠️ Warnings ({lastWarnings.length})</div>
          <ul className="swut-warnings-list">
            {lastWarnings.map((w, i) => (<li key={i}>{w}</li>))}
          </ul>
        </div>
      )}

      {/* 19차: Coverage ↔ SUTR cross-validation 섹션 */}
      <div className="swut-consistency-section">
        <h3 className="swut-consistency-title">🔍 Coverage ↔ SUTR 일관성 검증</h3>
        <p className="swut-consistency-desc">
          빌드한 Coverage Report (xlsx) / SUTR (xlsm) 두 산출물의 path를 입력하면
          4가지 cross-validation (미커버 ↔ 미실행 / Exception ↔ Deviation / Total TC /
          Final Result) 결과 반환. ISO 26262 audit evidence.
        </p>
        <div className="swut-form-row swut-field-with-browse">
          <Field
            name="coverage_path"
            label="Coverage Report Path (xlsx)"
            value={consistencyForm.coverage_path}
            onChange={v => setConsistencyForm(f => ({ ...f, coverage_path: v }))}
            placeholder="U:\...\(HDPDM01)SwUT Coverage Report_v3.01_240221_R.xlsx"
            fullWidth
          />
          <button
            className="swut-browse-btn"
            type="button"
            onClick={() => openPicker('consistency.coverage_path', '*.xlsx', 'Coverage Report 선택')}
          >📂 Browse</button>
        </div>
        <div className="swut-form-row swut-field-with-browse">
          <Field
            name="sutr_path"
            label="SUTR Path (xlsm)"
            value={consistencyForm.sutr_path}
            onChange={v => setConsistencyForm(f => ({ ...f, sutr_path: v }))}
            placeholder="U:\...\(HDPDM01_SUTR) Software Unit Test Result_v3.01_240221_R.xlsm"
            fullWidth
          />
          <button
            className="swut-browse-btn"
            type="button"
            onClick={() => openPicker('consistency.sutr_path', '*.xlsm', 'SUTR 선택')}
          >📂 Browse</button>
        </div>
        <div className="swut-actions">
          <button
            className="btn-primary"
            disabled={consistencyChecking}
            onClick={runConsistencyCheck}
          >
            {consistencyChecking ? '검증 중...' : '🔍 일관성 검증 실행'}
          </button>
        </div>

        <PathPickerDialog
          open={!!picker}
          initialPath={picker?.target === 'consistency.coverage_path' ? consistencyForm.coverage_path
            : picker?.target === 'consistency.sutr_path' ? consistencyForm.sutr_path
            : picker ? form[picker.target] : ''}
          pattern={picker?.pattern || '*'}
          title={picker?.title || '경로 선택'}
          onSelect={picker?.onSelect}
          onClose={() => setPicker(null)}
        />

        {consistencyReport && (
          <div className="swut-consistency-result">
            <div className="swut-consistency-status">
              결과: <strong>{consistencyReport.ok ? '✅ PASS' : '⚠️ FAIL'}</strong>
              {' '}— issue {(consistencyReport.issues || []).length}건,
              warning {(consistencyReport.parse_warnings || []).length}건
            </div>
            {(consistencyReport.issues || []).length > 0 && (
              <ul className="swut-issues-list">
                {consistencyReport.issues.map((iss, i) => (
                  <li key={i} className={`swut-issue swut-issue-${iss.severity || 'info'}`}>
                    <span className="swut-issue-cat">[{iss.category}]</span>{' '}
                    {iss.message}
                  </li>
                ))}
              </ul>
            )}
            {(consistencyReport.parse_warnings || []).length > 0 && (
              <ul className="swut-warnings-list">
                {consistencyReport.parse_warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ name, label, value, onChange, placeholder = '', type = 'text', fullWidth = false }) {
  const id = `swut-${name}`;
  return (
    <div className={`swut-field${fullWidth ? ' swut-field-full' : ''}`}>
      <label className="swut-field-label" htmlFor={id}>{label}</label>
      <input
        id={id}
        name={name}
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="swut-field-input"
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        spellCheck="false"
        data-form-type="other"
        data-lpignore="true"
      />
    </div>
  );
}
