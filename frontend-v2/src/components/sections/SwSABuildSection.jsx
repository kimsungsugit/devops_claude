import { useState, useCallback, useEffect, useRef } from 'react';
import { getUsername, authHeaders } from '../../api.js';
import { useToast } from '../../App.jsx';
import { useAdminMode } from '../../contexts/AdminContext.jsx';
import PathPickerDialog from '../PathPickerDialog.jsx';
import { loadSharedInputs, sharedDefaultsFor, applySharedDefaults, useSharedInputSync, markTouched, resolveTouched } from '../../sharedInputs.js';

const API_BASE = (typeof window !== 'undefined' && window.__ARIA_API_BASE__)
  || import.meta.env?.VITE_API_BASE_URL || '';

function buildUrl(path) {
  if (!API_BASE) return path;
  return API_BASE.replace(/\/$/, '') + path;
}

const STORAGE_KEY = 'devops_v2_swsa_form';

// SwSABuildRequest 와 1:1 (extra='forbid' — 여분 키 전송 시 422). 키 추가 시 schema 동기.
const DEFAULT_FORM = {
  project_id: 'KJPDS02',
  release_sw_version: '',
  test_date: '',
  log_folder: '',
  template_path: '',
  doc_id_base: 'HKY-SwSA',
  doc_id_sequence: '',
  doc_version: 'v0.10',
  doc_status: 'Unspecified',
  asil_level: 'ASIL A',
  phase: '',
  platform_version: '',
  product: 'PDS',
  verification_target: 'MCU',
  compiler: '',
  mcu: '',
  analysis_round: '1',
  test_engineer: '',
  debugger: '',
  misra_rule_version: 'MISRA C 2012',
  secure_rule_version: 'HKMC 4.1',
  reviewer_override: '',
  approver_override: '',
  validation_date: '',
  history_description: '',
};

function loadSavedForm() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    const base = { ...DEFAULT_FORM, test_date: new Date().toISOString().slice(0, 10), ...saved };
    // 입력 일원화: touched가 아닌(prefill) 매핑 필드만 공유 기본값으로 채움(사용자 입력·빈값 보존).
    const touched = resolveTouched('swsa', STORAGE_KEY, saved);
    return applySharedDefaults(base, touched, sharedDefaultsFor('swsa', loadSharedInputs()));
  } catch (e) {
    const base = { ...DEFAULT_FORM, test_date: new Date().toISOString().slice(0, 10) };
    return applySharedDefaults(base, new Set(), sharedDefaultsFor('swsa', loadSharedInputs()));
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

export default function SwSABuildSection() {
  const toast = useToast();
  const [building, setBuilding] = useState(false);
  const [lastSummary, setLastSummary] = useState(null);
  const [lastWarnings, setLastWarnings] = useState([]);
  const [form, setForm] = useState(loadSavedForm);
  // 입력 일원화: Settings 공유값 변경을 같은 세션에서 미변경 필드에 즉시 반영.
  useSharedInputSync('swsa', setForm, STORAGE_KEY);
  const [picker, setPicker] = useState(null);
  const { isAdmin } = useAdminMode();
  const browseDisabledTitle = '관리자 전용 — Ctrl+Shift+A로 admin 모드 활성화';

  const abortRef = useRef(null);
  const mountedRef = useRef(true);
  const downloadCleanupRef = useRef([]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (abortRef.current) { abortRef.current.abort(); abortRef.current = null; }
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
      markTouched(STORAGE_KEY, k);   // 사용자가 손댄 필드 기록 → 공유 동기화에서 제외(freezing 방지)
    } catch (e) {
      console.warn('SwSA form persist failed:', e?.message || e);
    }
  };

  const openPicker = (target, pattern, title) => {
    setPicker({ target, pattern, title, onSelect: v => setField(target, v) });
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
      downloadCleanupRef.current = downloadCleanupRef.current.filter(item => item.timerId !== timerId);
    }, 5000);
    downloadCleanupRef.current.push({ timerId, url });
  };

  const buildReport = useCallback(async () => {
    if (!form.project_id) { toast('warning', 'project_id 필수'); return; }
    if (!form.release_sw_version) { toast('warning', 'release_sw_version (SW Ver.) 필수'); return; }
    if (!form.test_date) { toast('warning', 'test_date 필수'); return; }
    if (!form.template_path) { toast('warning', 'SwSA 양식(template_path) 경로 필수'); return; }
    if (!form.log_folder) {
      toast('info', 'log_folder 미지정 — 위반/메트릭이 노란 표시(수동 입력)로 채워집니다');
    }
    const user = getUsername();
    if (!user) { toast('warning', '사용자 이름이 설정되지 않음 — Settings 확인'); return; }

    setBuilding(true);
    setLastSummary(null);
    setLastWarnings([]);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(buildUrl('/api/swsa/report/build'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify(form),
        signal: controller.signal,
      });

      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const j = await res.json();
          if (Array.isArray(j?.detail)) msg = formatDetailMessage(j.detail);
          else if (typeof j?.detail === 'string') msg = j.detail;
          else if (j?.message) msg = j.message;
        } catch (e) { /* non-JSON body */ }
        if (mountedRef.current) toast('error', `SwSA 빌드 실패: ${msg}`);
        return;
      }

      try {
        const summaryRaw = res.headers.get('X-SwSA-Summary');
        if (summaryRaw && mountedRef.current) setLastSummary(JSON.parse(summaryRaw));
        const warningsRaw = res.headers.get('X-SwSA-Warnings');
        if (warningsRaw && mountedRef.current) setLastWarnings(JSON.parse(warningsRaw));
      } catch (e) {
        console.warn('X-SwSA-* header parse failed:', e?.message || e);
      }

      const blob = await res.blob();
      const cd = res.headers.get('Content-Disposition') || '';
      const m = cd.match(/filename\*=UTF-8''([^;]+)/) || cd.match(/filename="([^"]+)"/);
      const filename = m ? decodeURIComponent(m[1]) : 'swsa_report.xlsm';

      if (!mountedRef.current) return;
      triggerDownload(blob, filename);
      toast('success', `SwSA ${(blob.size / 1024).toFixed(0)} KB 다운로드 완료`);
    } catch (e) {
      if (e?.name === 'AbortError') return;
      if (mountedRef.current) toast('error', `SwSA 빌드 실패: ${e?.message || e}`);
    } finally {
      if (mountedRef.current) setBuilding(false);
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, [form, toast]);

  return (
    <div className="swut-section">
      <div className="swut-section-header">
        <h2>SwSA 빌드 (Software Static Analysis Report)</h2>
        <p className="swut-section-desc">
          정적분석 로그 폴더(01.Log)만 지정하면 QAC(results_data.xml)·PMD 산출물을
          자동 발견·파싱·병합해 회사 v0.10 양식(.xlsm)을 작성합니다. 셀병합/폰트/매크로
          보존. 로그에서 도출 불가한 셀(예외처리/수정대상 등)은 🟡 노란 표시(수동 입력).
          ISO 26262 ASIL A evidence (auto-generated draft — manual review 의무).
        </p>
      </div>

      <div className="swut-form-grid">
        <Field name="project_id" label="Project ID *" value={form.project_id}
               onChange={v => setField('project_id', v)} placeholder="KJPDS02"
               hint="Cover Doc ID / Summary Project" />
        <Field name="release_sw_version" label="SW Ver. *" value={form.release_sw_version}
               onChange={v => setField('release_sw_version', v)} placeholder="2631.00"
               hint="형식: N.N 또는 N.N.N — ST Test-Info SW Ver." />
        <Field name="test_date" label="Date *" value={form.test_date}
               onChange={v => setField('test_date', v)} type="date"
               hint="Cover Date (yyyy-mm-dd / yyyy.mm.dd)" />
        <Field name="phase" label="Phase" value={form.phase}
               onChange={v => setField('phase', v)} placeholder="PV"
               hint="PV / DV — Summary Phase" />
        <Field name="platform_version" label="Platform Ver." value={form.platform_version}
               onChange={v => setField('platform_version', v)} placeholder="(APP) 2631.00 / (BOOT) 1.13"
               hint="Summary Software Platform Ver." />
        <Field name="asil_level" label="ASIL" value={form.asil_level}
               onChange={v => setField('asil_level', v)} hint="default ASIL A — Summary 'A'로 기록" />
        <Field name="compiler" label="Compiler" value={form.compiler}
               onChange={v => setField('compiler', v)} placeholder="CodeWarrior HC12Z"
               hint="Summary Complier" />
        <Field name="mcu" label="MCU" value={form.mcu}
               onChange={v => setField('mcu', v)} placeholder="MC9S12ZVLA128MLF"
               hint="Summary MCU part number" />
        <Field name="analysis_round" label="분석차수" value={form.analysis_round}
               onChange={v => setField('analysis_round', v)} placeholder="1"
               hint="모든 ST 시트 Test-Info 분석차수" />
        <Field name="test_engineer" label="Tester" value={form.test_engineer}
               onChange={v => setField('test_engineer', v)} placeholder="김진경"
               hint="ST Test-Info Tester (Cover Author)" />
        <Field name="debugger" label="Debugger" value={form.debugger}
               onChange={v => setField('debugger', v)} placeholder="이재원/유영규"
               hint="ST Test-Info Debugger" />
        <Field name="doc_id_sequence" label="Doc ID Seq" value={form.doc_id_sequence}
               onChange={v => setField('doc_id_sequence', v)} placeholder="2884"
               hint="숫자만 — Cover Doc ID = {doc_id_base}-{seq}" />
      </div>

      <div className="swut-form-row swut-field-with-browse">
        <Field name="log_folder" label="Log Folder (01.Log)" value={form.log_folder}
               onChange={v => setField('log_folder', v)}
               placeholder="U:\연구소\...\08.SW 정적분석\01.Log\PV"
               hint="QAC results_data.xml / *HMR*.html / *PMD*.txt 자동 발견. 비우면 전부 노란 표시"
               fullWidth />
        <button className="swut-browse-btn" type="button" disabled={!isAdmin}
                title={isAdmin ? undefined : browseDisabledTitle}
                onClick={() => openPicker('log_folder', '*', 'Log 디렉토리 선택')}>
          📂 Browse
        </button>
      </div>

      <div className="swut-form-row swut-field-with-browse">
        <Field name="template_path" label="SwSA 양식 (template) *" value={form.template_path}
               onChange={v => setField('template_path', v)}
               placeholder="U:\...\(XXXX_SwSA) Software Static Analysis Report_v0.10.xlsm"
               hint="회사 SwSA 양식 .xlsm — 존재하는 시트만 채움"
               fullWidth />
        <button className="swut-browse-btn" type="button" disabled={!isAdmin}
                title={isAdmin ? undefined : browseDisabledTitle}
                onClick={() => openPicker('template_path', '*.xlsm', 'SwSA 양식 선택')}>
          📂 Browse
        </button>
      </div>

      <details className="swut-advanced-section" style={{ marginTop: 12 }}>
        <summary className="swut-advanced-summary">고급 메타 (Cover/Summary/코딩룰 버전)</summary>
        <div className="swut-form-grid">
          <Field name="doc_id_base" label="Doc ID Base" value={form.doc_id_base}
                 onChange={v => setField('doc_id_base', v)} placeholder="HKY-KJPDS02_PV-SwSA" />
          <Field name="doc_version" label="Doc Version" value={form.doc_version}
                 onChange={v => setField('doc_version', v)} placeholder="v0.11" />
          <Field name="doc_status" label="Doc Status" value={form.doc_status}
                 onChange={v => setField('doc_status', v)} placeholder="In Review" />
          <Field name="product" label="Product" value={form.product}
                 onChange={v => setField('product', v)} placeholder="PDS" />
          <Field name="verification_target" label="검증 대상" value={form.verification_target}
                 onChange={v => setField('verification_target', v)} placeholder="MCU" />
          <Field name="misra_rule_version" label="MISRA 룰 버전" value={form.misra_rule_version}
                 onChange={v => setField('misra_rule_version', v)} hint="ST101 코딩룰 버전" />
          <Field name="secure_rule_version" label="시큐어 룰 버전" value={form.secure_rule_version}
                 onChange={v => setField('secure_rule_version', v)} hint="ST1101 코딩룰 버전" />
          <Field name="reviewer_override" label="Reviewer" value={form.reviewer_override}
                 onChange={v => setField('reviewer_override', v)} placeholder="검토자" />
          <Field name="approver_override" label="Approver" value={form.approver_override}
                 onChange={v => setField('approver_override', v)} placeholder="승인자" />
          <Field name="validation_date" label="Validation Date" value={form.validation_date}
                 onChange={v => setField('validation_date', v)} type="date" />
        </div>
        <Field name="history_description" label="History 설명" value={form.history_description}
               onChange={v => setField('history_description', v)}
               placeholder="- (APP) 2631.00 / (BOOT) 1.13 정적분석 작성" fullWidth />
      </details>

      <div className="swut-actions">
        <button className="btn-primary" disabled={building || !isAdmin}
                title={isAdmin ? undefined : browseDisabledTitle}
                onClick={buildReport}>
          {building ? '빌드 중...' : '🔬 SwSA Report 빌드 (xlsm, keep_vba)'}
        </button>
      </div>

      {lastSummary && (
        <div className="swut-summary-card">
          <div className="swut-summary-title">마지막 빌드 결과</div>
          <ul className="swut-summary-stats">
            <li>채운 시트: <strong>{(lastSummary.sheets_filled || []).join(', ') || '-'}</strong></li>
            <li>발견 로그: <strong>{lastSummary.logs_discovered ?? 0}</strong>개
              {' '}(모듈: {(lastSummary.modules || []).join(', ') || '-'})</li>
            <li>채운 셀: <strong>{lastSummary.filled_cells ?? 0}</strong>
              {' '}/ 🟡 사용자 입력 필요: <strong>{lastSummary.user_input_cells ?? 0}</strong></li>
            <li>VBA 매크로 보존: <strong>{lastSummary.vba_preserved ? '✅' : '❌'}</strong></li>
          </ul>
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

      <PathPickerDialog
        open={!!picker}
        initialPath={picker ? form[picker.target] : ''}
        pattern={picker?.pattern || '*'}
        title={picker?.title || '경로 선택'}
        onSelect={picker?.onSelect}
        onClose={() => setPicker(null)}
      />
    </div>
  );
}

function Field({
  name, label, value, onChange, placeholder = '', type = 'text',
  fullWidth = false, hint = '',
}) {
  const id = `swsa-${name}`;
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
