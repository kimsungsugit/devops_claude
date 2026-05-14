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

const STORAGE_KEY = 'devops_v2_swit_form';

const DEFAULT_FORM = {
  project_id: 'HDPDM01',
  release_sw_version: '',
  test_date: '',
  test_engineer: '',
  doc_id_sequence: '',
  hw_version: '1.00',
  asil_level: 'ASIL B',  // SwIT 통합테스트 default
  log_folder: '',
  template_path: '',
  swuds_docx_path: '',
  c_source_root: '',
  reviewer_override: '',
  approver_override: '',
  validation_date: '',
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

export default function SwITBuildSection() {
  const toast = useToast();
  const [building, setBuilding] = useState(null);
  const [lastSummary, setLastSummary] = useState(null);
  const [lastWarnings, setLastWarnings] = useState([]);
  const [form, setForm] = useState(loadSavedForm);
  const [consistencyForm, setConsistencyForm] = useState({ coverage_path: '', sitr_path: '' });
  const [consistencyChecking, setConsistencyChecking] = useState(false);
  const [consistencyReport, setConsistencyReport] = useState(null);
  const [picker, setPicker] = useState(null);

  const openPicker = (target, pattern, title) => {
    let onSelect;
    if (target === 'consistency.coverage_path') {
      onSelect = v => setConsistencyForm(f => ({ ...f, coverage_path: v }));
    } else if (target === 'consistency.sitr_path') {
      onSelect = v => setConsistencyForm(f => ({ ...f, sitr_path: v }));
    } else {
      onSelect = v => setField(target, v);
    }
    setPicker({ target, pattern, title, onSelect });
  };

  const abortRef = useRef(null);
  const consistencyAbortRef = useRef(null);
  const mountedRef = useRef(true);
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
      console.warn('SwIT form persist failed:', e?.message || e);
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
      const res = await fetch(buildUrl(`/api/swit/${kind}/build`), {
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
        } catch (e) { /* non-JSON body */ }
        if (mountedRef.current) {
          toast('error', `${kind.toUpperCase()} 빌드 실패: ${msg}`);
        }
        return;
      }

      try {
        const summaryRaw = res.headers.get('X-SwIT-Summary');
        if (summaryRaw && mountedRef.current) setLastSummary(JSON.parse(summaryRaw));
        const warningsRaw = res.headers.get('X-SwIT-Warnings');
        if (warningsRaw && mountedRef.current) setLastWarnings(JSON.parse(warningsRaw));
      } catch (e) {
        console.warn('X-SwIT-* header parse failed:', e?.message || e);
      }

      const blob = await res.blob();
      const cd = res.headers.get('Content-Disposition') || '';
      const m = cd.match(/filename\*=UTF-8''([^;]+)/) || cd.match(/filename="([^"]+)"/);
      const filename = m ? decodeURIComponent(m[1])
        : `swit_${kind}.${kind === 'sitr' ? 'xlsm' : 'xlsx'}`;

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

  const runConsistencyCheck = useCallback(async () => {
    if (!consistencyForm.coverage_path) {
      toast('warning', 'coverage_path 필수'); return;
    }
    if (!consistencyForm.sitr_path) {
      toast('warning', 'sitr_path 필수'); return;
    }
    const user = getUsername();
    if (!user) { toast('warning', '사용자 이름이 설정되지 않음 — Settings 확인'); return; }

    setConsistencyChecking(true);
    setConsistencyReport(null);
    const controller = new AbortController();
    consistencyAbortRef.current = controller;

    try {
      const res = await fetch(buildUrl('/api/swit/consistency/check'), {
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
        <h2>SwIT 빌드 (Software Integration Test)</h2>
        <p className="swut-section-desc">
          Coverage Report (xlsx, v2.02) / SITR (xlsm, keep_vba) 빌드 — 33~34차.
          출력은 브라우저 다운로드. Cloudium은 read-only로 template/log만 접근.
          ISO 26262 ASIL B+ Integration test evidence (manual review 의무).
        </p>
      </div>

      <div className="swut-form-grid">
        <Field name="project_id" label="Project ID *" value={form.project_id}
               onChange={v => setField('project_id', v)} placeholder="HDPDM01"
               hint="회사 등록 project_id (예: HDPDM01)" />
        <Field name="release_sw_version" label="Release SW Version *" value={form.release_sw_version}
               onChange={v => setField('release_sw_version', v)} placeholder="2.02"
               hint="형식: N.N 또는 N.N.N (예: 2.02, 1.01.05)" />
        <Field name="test_date" label="Test Date *" value={form.test_date}
               onChange={v => setField('test_date', v)} type="date"
               hint="yyyy-mm-dd — Test Summary 시트에 기록" />
        <Field name="test_engineer" label="Test Engineer" value={form.test_engineer}
               onChange={v => setField('test_engineer', v)} placeholder="JK Kim"
               hint="비우면 산출물 Cover/Test Summary에 노란 강조" />
        <Field name="doc_id_sequence" label="Doc ID Sequence" value={form.doc_id_sequence}
               onChange={v => setField('doc_id_sequence', v)} placeholder="042"
               hint="숫자만. doc_id_base와 결합 — Coverage: HDPDM01-SwIT, SITR: HDPDM01-SITR" />
        <Field name="hw_version" label="HW Version" value={form.hw_version}
               onChange={v => setField('hw_version', v)} hint="default 1.00" />
        <Field name="asil_level" label="ASIL Level" value={form.asil_level}
               onChange={v => setField('asil_level', v)}
               hint="default ASIL B — SwIT Integration test 일반" />
        <Field name="reviewer_override" label="Reviewer" value={form.reviewer_override}
               onChange={v => setField('reviewer_override', v)} placeholder="검토자 이름"
               hint="빈 상태면 Cover 노란 강조" />
        <Field name="approver_override" label="Approver" value={form.approver_override}
               onChange={v => setField('approver_override', v)} placeholder="승인자 이름"
               hint="빈 상태면 Cover 노란 강조 (audit 필수)" />
        <Field name="validation_date" label="Validation Date" value={form.validation_date}
               onChange={v => setField('validation_date', v)} type="date"
               hint="yyyy-mm-dd — 빈 상태면 노란 강조" />
      </div>

      <div className="swut-form-row swut-field-with-browse">
        <Field
          name="log_folder"
          label="Log Folder"
          value={form.log_folder}
          onChange={v => setField('log_folder', v)}
          placeholder="U:\연구소\...\08.SW 통합테스트\03.Test Result\01.Log\v2.02_240219"
          hint="VectorCAST html report 보유 디렉토리"
          fullWidth
        />
        <button className="swut-browse-btn" type="button"
                onClick={() => openPicker('log_folder', '*', 'Log 디렉토리 선택')}>
          📂 Browse
        </button>
      </div>
      <div className="swut-form-row swut-field-with-browse">
        <Field
          name="template_path"
          label="Template Path (xlsx for Coverage / xlsm for SITR)"
          value={form.template_path}
          onChange={v => setField('template_path', v)}
          placeholder="U:\...\(HDPDM01)SwIT Coverage Report_v2.02_240219.xlsx 또는 (HDPDM01_SITR) Software Integration Test Result_v2.02_240219.xlsm"
          hint="회사 v2.02 양식 — Coverage / SITR 빌드 시 각각 알맞은 파일 선택"
          fullWidth
        />
        <button className="swut-browse-btn" type="button"
                onClick={() => openPicker('template_path', '*.xlsx,*.xlsm', 'Template 파일 선택')}>
          📂 Browse
        </button>
      </div>
      <div className="swut-form-row swut-field-with-browse">
        <Field
          name="swuds_docx_path"
          label="SwUDS Docx Path (선택)"
          value={form.swuds_docx_path}
          onChange={v => setField('swuds_docx_path', v)}
          placeholder="U:\...\(HDPDM01)SwUDS_v3.docx"
          hint="제공 시 2.Consistency에 SwUDS↔SwIT 매핑 row 추가 + (c_source 미제공 시) ASIL 추출"
          fullWidth
        />
        <button className="swut-browse-btn" type="button"
                onClick={() => openPicker('swuds_docx_path', '*.docx', 'SwUDS docx 선택')}>
          📂 Browse
        </button>
      </div>
      <div className="swut-form-row swut-field-with-browse">
        <Field
          name="c_source_root"
          label="C Source Root (선택)"
          value={form.c_source_root}
          onChange={v => setField('c_source_root', v)}
          placeholder="U:\...\HDPDM01\src\"
          hint="제공 시 Doxygen @asil에서 함수별 ASIL 추출. Hyundai SwUFn_NNNN 컨벤션 전용"
          fullWidth
        />
        <button className="swut-browse-btn" type="button"
                onClick={() => openPicker('c_source_root', '*', 'C 소스 디렉토리 선택')}>
          📂 Browse
        </button>
      </div>

      <div className="swut-actions">
        <button className="btn-primary" disabled={!!building}
                onClick={() => buildXlsx('coverage')}>
          {building === 'coverage' ? '빌드 중...' : '📊 Coverage Report 빌드 (xlsx)'}
        </button>
        <button className="btn-primary" disabled={!!building}
                onClick={() => buildXlsx('sitr')}>
          {building === 'sitr' ? '빌드 중...' : '📝 SITR 빌드 (xlsm, keep_vba)'}
        </button>
      </div>

      {lastSummary?.asil_distribution &&
       Object.keys(lastSummary.asil_distribution).some(k => k !== 'UNKNOWN') && (
        <div className="swut-asil-distribution-panel" data-testid="swit-asil-distribution">
          <div className="swut-asil-distribution-title">
            🛡️ ASIL 분포 (ISO 26262 audit reviewer 검토 우선순위)
          </div>
          {lastSummary.asil_highlight_policy && (
            <div className="swut-asil-policy-note" data-testid="swit-asil-policy-note">
              ℹ️ {lastSummary.asil_highlight_policy}
            </div>
          )}
          <ul className="swut-asil-distribution-list">
            {Object.entries(lastSummary.asil_distribution).map(([key, count]) => {
              const bucket = (count > 0 && {
                ASIL_D: 'swut-asil-d',
                ASIL_C: 'swut-asil-c',
                ASIL_B: 'swut-asil-b',
              }[key]) || 'swut-asil-other';
              const warn = (count > 0 && {
                ASIL_D: '⚠️ MC/DC 커버리지 필수',
                ASIL_C: 'ℹ️ MC/DC 커버리지 권장',
                ASIL_B: 'ℹ️ 분기 커버리지 필수',
              }[key]) || '';
              return (
                <li key={key} className={bucket} data-asil-bucket={key}>
                  <span className="swut-asil-label">{key}</span>
                  <span className="swut-asil-count">{count}</span>
                  {warn && <span className="swut-asil-d-warning">{warn}</span>}
                </li>
              );
            })}
          </ul>
          {['d', 'c', 'b'].map(grade => {
            const ids = lastSummary[`asil_${grade}_function_ids`] ?? [];
            if (ids.length === 0) return null;
            return (
              <div key={grade} className="swut-asil-d-functions" data-asil-grade={grade}>
                <strong>ASIL {grade.toUpperCase()} 함수 ID:</strong>{' '}
                {ids.join(', ')}
              </div>
            );
          })}
        </div>
      )}

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

      <div className="swut-consistency-section">
        <h3 className="swut-consistency-title">🔍 Coverage ↔ SITR 일관성 검증</h3>
        <p className="swut-consistency-desc">
          빌드한 Coverage Report (xlsx) / SITR (xlsm) 두 산출물의 path를 입력하면
          4가지 cross-validation (미커버 ↔ 미실행 / Exception ↔ Deviation / Total TC /
          Final Result) 결과 반환. ISO 26262 ASIL B+ Integration test audit evidence.
        </p>
        <div className="swut-form-row swut-field-with-browse">
          <Field
            name="coverage_path"
            label="Coverage Report Path (xlsx)"
            value={consistencyForm.coverage_path}
            onChange={v => setConsistencyForm(f => ({ ...f, coverage_path: v }))}
            placeholder="U:\...\(HDPDM01)SwIT Coverage Report_v2.02_240219.xlsx"
            hint="위에서 빌드한 xlsx 또는 기존 회사 산출물 path"
            fullWidth
          />
          <button className="swut-browse-btn" type="button"
                  onClick={() => openPicker('consistency.coverage_path', '*.xlsx', 'Coverage Report 선택')}>
            📂 Browse
          </button>
        </div>
        <div className="swut-form-row swut-field-with-browse">
          <Field
            name="sitr_path"
            label="SITR Path (xlsm)"
            value={consistencyForm.sitr_path}
            onChange={v => setConsistencyForm(f => ({ ...f, sitr_path: v }))}
            placeholder="U:\...\(HDPDM01_SITR) Software Integration Test Result_v2.02_240219.xlsm"
            hint="동일 release_sw_version의 SITR xlsm — cross-validation 4 항목"
            fullWidth
          />
          <button className="swut-browse-btn" type="button"
                  onClick={() => openPicker('consistency.sitr_path', '*.xlsm', 'SITR 선택')}>
            📂 Browse
          </button>
        </div>
        <div className="swut-actions">
          <button className="btn-primary" disabled={consistencyChecking}
                  onClick={runConsistencyCheck}>
            {consistencyChecking ? '검증 중...' : '🔍 일관성 검증 실행'}
          </button>
        </div>

        <PathPickerDialog
          open={!!picker}
          initialPath={picker?.target === 'consistency.coverage_path' ? consistencyForm.coverage_path
            : picker?.target === 'consistency.sitr_path' ? consistencyForm.sitr_path
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

function Field({
  name, label, value, onChange, placeholder = '', type = 'text',
  fullWidth = false, hint = '',
}) {
  const id = `swit-${name}`;
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
      {hint && <div className="swut-field-hint">{hint}</div>}
    </div>
  );
}
