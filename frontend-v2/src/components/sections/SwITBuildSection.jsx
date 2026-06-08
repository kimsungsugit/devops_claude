import { useState, useCallback, useEffect, useRef } from 'react';
import { getUsername, authHeaders } from '../../api.js';
import { useToast } from '../../App.jsx';
import { useAdminMode } from '../../contexts/AdminContext.jsx';
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
  // 51차 — Coverage / SITR 양식 분리 (이전 단일 template_path)
  coverage_template_path: '',
  sitr_template_path: '',
  switcr_template_path: '',
  switcv_path: '',
  switr_path: '',
  swuds_docx_path: '',
  // 60차 F6-B: SwITS spec 파일 (xlsm/docx 허용). 제공 시 SITR Test Log의
  // TC_ID/Description/Precondition/Test Method/Generation Method 컬럼에 spec stamp.
  swuts_docx_path: '',
  // 60차 F6-C: HMR (VectorCAST aggregate metrics report) HTML 경로 (옵션).
  // 제공 시 SwIT Coverage Report 3.Coverage 함수별 Function Calls metric stamp.
  hmr_html_path: '',
  c_source_root: '',
  reviewer_override: '',
  approver_override: '',
  validation_date: '',
};

// 40차: 로컬 isAdminMode helper 제거 — AdminContext.useAdminMode() 사용.
// localStorage 신뢰 제거, backend GET /api/auth/me 응답 기반.

function loadSavedForm() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    // 52차 C1 — legacy template_path key 마이그레이션: 51차 분리 시 이전 key를
    // coverage_template_path로 옮겨 사용자 재입력 부담 회피. delete로 무효 key 제거.
    if (saved.template_path && !saved.coverage_template_path && !saved.sitr_template_path) {
      saved.coverage_template_path = saved.template_path;
    }
    delete saved.template_path;
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
  // 38차 W4: log_folder dry-run preview state
  const [previewChecking, setPreviewChecking] = useState(false);
  const [previewResult, setPreviewResult] = useState(null);
  // 40차: AdminContext 기반 — localStorage 신뢰 제거, backend role 검증.
  // C3 fix (same-tab 토글): AdminProvider가 custom event 'admin-mode-changed' listen.
  const { isAdmin } = useAdminMode();
  const browseDisabledTitle = '관리자 전용 — Ctrl+Shift+A로 admin 모드 활성화';

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
    // 51차 — kind별 필수 template_path 분리.
    const kindTemplate = kind === 'coverage'
      ? form.coverage_template_path
      : kind === 'sitr'
        ? form.sitr_template_path
        : form.switcr_template_path;
    if (!form.log_folder && !kindTemplate) {
      const kindLabel = kind === 'coverage' ? 'Coverage' : kind === 'sitr' ? 'SITR' : 'SwITCR';
      toast('warning', `log_folder 또는 ${kindLabel} Template Path 중 하나는 필수`); return;
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
          ...authHeaders(),
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
        : `swit_${kind}.${kind === 'coverage' ? 'xlsx' : 'xlsm'}`;

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

  // 38차 W4: log_folder dry-run preview — 빌드 전 release 후보 + 자동 선택 미리보기
  const runLogFolderPreview = useCallback(async () => {
    if (!form.log_folder) {
      toast('warning', 'log_folder 입력 필요'); return;
    }
    const user = getUsername();
    if (!user) { toast('warning', '사용자 이름 미설정 — Settings 확인'); return; }

    setPreviewChecking(true);
    setPreviewResult(null);
    try {
      const res = await fetch(buildUrl('/api/swit/log-folder/preview'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ log_folder: form.log_folder }),
      });
      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const j = await res.json();
          if (Array.isArray(j?.detail)) msg = formatDetailMessage(j.detail);
          else if (typeof j?.detail === 'string') msg = j.detail;
        } catch (e) { /* non-JSON */ }
        if (mountedRef.current) toast('error', `미리보기 실패: ${msg}`);
        return;
      }
      const data = await res.json();
      if (!mountedRef.current) return;
      setPreviewResult(data);
      const n = (data.candidates || []).length;
      if (data.auto_resolved) {
        const latest = (data.candidates || []).find(c => c.is_latest);
        toast('success', `자동 선택: ${latest?.name || '?'} (${n}개 후보 중 latest)`);
      } else if (n === 0) {
        toast('warning', '후보 0건 — log_folder 확인');
      } else {
        toast('info', `정상 release 폴더 (${n}개 후보)`);
      }
    } catch (e) {
      if (mountedRef.current) toast('error', `미리보기 실패: ${e?.message || e}`);
    } finally {
      if (mountedRef.current) setPreviewChecking(false);
    }
  }, [form.log_folder, toast]);

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
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
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
                disabled={!isAdmin}
                title={isAdmin ? undefined : browseDisabledTitle}
                onClick={() => openPicker('log_folder', '*', 'Log 디렉토리 선택')}>
          📂 Browse
        </button>
        {/* 38차 W4: log_folder dry-run preview 버튼 */}
        <button
          className="swut-browse-btn"
          type="button"
          disabled={previewChecking || !isAdmin}
          data-testid="swit-preview-button"
          onClick={runLogFolderPreview}
          title="빌드 전 release 후보 + 자동 선택될 latest 미리보기 (38차)"
        >
          {previewChecking ? '...' : '🔎 미리보기'}
        </button>
      </div>
      {/* 38차 W4: preview 결과 inline panel */}
      {previewResult && (
        <div className="swut-preview-panel" data-testid="swit-preview-panel">
          <div className="swut-preview-title">
            🔎 log_folder 미리보기 ({previewResult.candidates?.length || 0}개 후보)
            {previewResult.auto_resolved && (
              <span className="swut-preview-badge"> 자동 선택</span>
            )}
          </div>
          <div className="swut-preview-meta">
            <strong>입력</strong>: {previewResult.input_log_folder}<br />
            <strong>실제 사용</strong>: {previewResult.resolved_log_folder}
          </div>
          {(previewResult.candidates || []).length > 0 && (
            <ul className="swut-preview-candidates">
              {previewResult.candidates.map((c) => (
                <li key={c.name} className={c.is_latest ? 'swut-preview-latest' : ''}>
                  {c.is_latest && '🎯 '}
                  <strong>{c.name}</strong>
                  {' '}<span className="swut-preview-date">({c.date_suffix})</span>
                  {c.is_latest && <em> ← 빌드 시 이 release 자동 선택</em>}
                </li>
              ))}
            </ul>
          )}
          {(previewResult.warnings || []).length > 0 && (
            <ul className="swut-preview-warnings">
              {previewResult.warnings.map((w, i) => (<li key={i}>{w}</li>))}
            </ul>
          )}
        </div>
      )}
      <div className="swut-form-row swut-field-with-browse">
        <Field
          name="coverage_template_path"
          label="Coverage Template Path (xlsx)"
          value={form.coverage_template_path}
          onChange={v => setField('coverage_template_path', v)}
          placeholder="U:\...\(HDPDM01)SwIT Coverage Report_v2.02_240219.xlsx"
          hint="Coverage 빌드 전용 — 비우면 config/swut_meta.json의 swit_coverage_template 사용"
          fullWidth
        />
        <button className="swut-browse-btn" type="button"
                disabled={!isAdmin}
                title={isAdmin ? undefined : browseDisabledTitle}
                onClick={() => openPicker('coverage_template_path', '*.xlsx', 'Coverage Template 파일 선택')}>
          📂 Browse
        </button>
      </div>
      <div className="swut-form-row swut-field-with-browse">
        <Field
          name="sitr_template_path"
          label="SITR Template Path (xlsm)"
          value={form.sitr_template_path}
          onChange={v => setField('sitr_template_path', v)}
          placeholder="U:\...\(HDPDM01_SITR) Software Integration Test Result_v2.02_240219.xlsm"
          hint="SITR 빌드 전용 — 비우면 config/swut_meta.json의 swit_sitr_template 사용"
          fullWidth
        />
        <button className="swut-browse-btn" type="button"
                disabled={!isAdmin}
                title={isAdmin ? undefined : browseDisabledTitle}
                onClick={() => openPicker('sitr_template_path', '*.xlsm', 'SITR Template 파일 선택')}>
          📂 Browse
        </button>
      </div>
      <div className="swut-form-row swut-field-with-browse">
        <Field
          name="switcr_template_path"
          label="SwITCR Template Path (xlsm)"
          value={form.switcr_template_path}
          onChange={v => setField('switcr_template_path', v)}
          placeholder="U:\...\(XXXX_SwITCR) Software Integration Test Comprehesive Result_v0.10_XXXXXX.xlsm"
          hint="SwITCR 빌드 전용 — 비우면 config/swut_meta.json의 switcr_template 사용"
          fullWidth
        />
        <button className="swut-browse-btn" type="button"
                disabled={!isAdmin}
                title={isAdmin ? undefined : browseDisabledTitle}
                onClick={() => openPicker('switcr_template_path', '*.xlsm', 'SwITCR Template 파일 선택')}>
          📂 Browse
        </button>
      </div>
      {/* 52차 — config 자동 사용 정책. override 필요 시만 펼침 */}
      <details className="swut-advanced-section" style={{ marginTop: 12 }}>
        <summary style={{ cursor: 'pointer', padding: '8px 0', fontSize: '0.92em', color: 'var(--text-muted, #888)' }}>
          ▶ 고급 설정 (config 자동 사용 — override 필요 시만)
        </summary>
        <div className="swut-form-row swut-field-with-browse">
          <Field
            name="switcv_path"
            label="SwITCV Evidence Path (xlsx)"
            value={form.switcv_path}
            onChange={v => setField('switcv_path', v)}
            placeholder="U:\...\(KJPDS02_SwITCV) Software Integration Test Coverage Result_v1.01_251205_R.xlsx"
            hint="SwITCR evidence. Empty uses config/swut_meta.json swit_coverage_template"
            fullWidth
          />
          <button className="swut-browse-btn" type="button"
                  disabled={!isAdmin}
                  title={isAdmin ? undefined : browseDisabledTitle}
                  onClick={() => openPicker('switcv_path', '*.xlsx', 'SwITCV evidence file')}>
            📂 Browse
          </button>
        </div>
        <div className="swut-form-row swut-field-with-browse">
          <Field
            name="switr_path"
            label="SwITR Evidence Path (xlsm)"
            value={form.switr_path}
            onChange={v => setField('switr_path', v)}
            placeholder="U:\...\(KJPDS02_SwITR) Software Integration Test Result_v1.01_251205_R.xlsm"
            hint="SwITCR evidence. Empty uses config/swut_meta.json swit_sitr_template"
            fullWidth
          />
          <button className="swut-browse-btn" type="button"
                  disabled={!isAdmin}
                  title={isAdmin ? undefined : browseDisabledTitle}
                  onClick={() => openPicker('switr_path', '*.xlsm', 'SwITR evidence file')}>
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
            hint="비우면 config/swut_meta.json의 swuds_docx_path 자동 사용. 제공 시 2.Consistency에 SwUDS↔SwIT 매핑 + ASIL 추출"
            fullWidth
          />
          <button className="swut-browse-btn" type="button"
                  disabled={!isAdmin}
                  title={isAdmin ? undefined : browseDisabledTitle}
                  onClick={() => openPicker('swuds_docx_path', '*.docx', 'SwUDS docx 선택')}>
            📂 Browse
          </button>
        </div>
        <div className="swut-form-row swut-field-with-browse">
          <Field
            name="swuts_docx_path"
            label="SwITS Spec Path (선택, 60차 F6-B)"
            value={form.swuts_docx_path}
            onChange={v => setField('swuts_docx_path', v)}
            placeholder="U:\...\(KJPDS02_SwITS) ... .xlsm"
            hint="비우면 config/swut_meta.json의 swuts_docx_path 자동 사용. 제공 시 SITR Test Log B/C/D + Precondition spec stamp (xlsm/docx 자동 감지)"
            fullWidth
          />
          <button className="swut-browse-btn" type="button"
                  disabled={!isAdmin}
                  title={isAdmin ? undefined : browseDisabledTitle}
                  onClick={() => openPicker('swuts_docx_path', '*.xlsm;*.xlsx;*.docx', 'SwITS spec 파일 선택')}>
            📂 Browse
          </button>
        </div>
        <div className="swut-form-row swut-field-with-browse">
          <Field
            name="hmr_html_path"
            label="HMR HTML Path (선택, 60차 F6-C)"
            value={form.hmr_html_path}
            onChange={v => setField('hmr_html_path', v)}
            placeholder="U:\...\Jenkins_PDSM_IT_metrics_report.html"
            hint="비우면 config의 hmr_html_path 자동 사용. 제공 시 SwIT Coverage Report 3.Coverage 함수별 Function Calls metric stamp (VectorCAST aggregate metrics report)"
            fullWidth
          />
          <button className="swut-browse-btn" type="button"
                  disabled={!isAdmin}
                  title={isAdmin ? undefined : browseDisabledTitle}
                  onClick={() => openPicker('hmr_html_path', '*.html;*.htm', 'HMR HTML 파일 선택')}>
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
            hint="비우면 config/swut_meta.json의 c_source_root 자동 사용. 제공 시 Doxygen @asil 추출 (SwUFn_NNNN 컨벤션)"
            fullWidth
          />
          <button className="swut-browse-btn" type="button"
                  disabled={!isAdmin}
                  title={isAdmin ? undefined : browseDisabledTitle}
                  onClick={() => openPicker('c_source_root', '*', 'C 소스 디렉토리 선택')}>
            📂 Browse
          </button>
        </div>
      </details>

      <div className="swut-actions">
        <button className="btn-primary" disabled={!!building || !isAdmin} title={isAdmin ? undefined : browseDisabledTitle}
                onClick={() => buildXlsx('coverage')}>
          {building === 'coverage' ? '빌드 중...' : '📊 Coverage Report 빌드 (xlsx)'}
        </button>
        <button className="btn-primary" disabled={!!building || !isAdmin} title={isAdmin ? undefined : browseDisabledTitle}
                onClick={() => buildXlsx('sitr')}>
          {building === 'sitr' ? '빌드 중...' : '📝 SITR 빌드 (xlsm, keep_vba)'}
        </button>
        <button className="btn-primary" disabled={!!building || !isAdmin} title={isAdmin ? undefined : browseDisabledTitle}
                onClick={() => buildXlsx('switcr')}>
          {building === 'switcr' ? '빌드 중...' : 'SwITCR 빌드 (xlsm)'}
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

      {lastSummary?.tc_stats_blocked_inferred === true && (
        <div
          className="swut-blocked-inferred-warning"
          data-testid="swit-blocked-inferred-warning"
          role="alert"
        >
          <span className="swut-blocked-inferred-icon" aria-hidden="true">⚠️</span>
          <div className="swut-blocked-inferred-content">
            <strong>TC Stats Blocked = 0 (inferred)</strong>
            <p>
              VectorCAST가 blocked TC 수를 직접 보고하지 않아 0으로 채워졌습니다 (B17 row F열).
              산출물 G열 (col+5)에 노란 강조로 안내 표시되어 있습니다 —
              실측 blocked TC 수가 있다면 audit reviewer가 명시적으로 채워야 합니다.
            </p>
          </div>
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
                  disabled={!isAdmin}
                  title={isAdmin ? undefined : browseDisabledTitle}
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
                  disabled={!isAdmin}
                  title={isAdmin ? undefined : browseDisabledTitle}
                  onClick={() => openPicker('consistency.sitr_path', '*.xlsm', 'SITR 선택')}>
            📂 Browse
          </button>
        </div>
        <div className="swut-actions">
          <button className="btn-primary" disabled={consistencyChecking || !isAdmin} title={isAdmin ? undefined : browseDisabledTitle}
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
