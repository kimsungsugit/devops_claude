import { useState, useCallback, useEffect, useRef } from 'react';
import { getUsername, authHeaders } from '../../api.js';
import { useToast } from '../../App.jsx';
import { useAdminMode } from '../../contexts/AdminContext.jsx';
import PathPickerDialog from '../PathPickerDialog.jsx';
import { isAbortError } from '../../impactPoll.js';
import { loadSharedInputs, sharedDefaultsFor, applySharedDefaults, useSharedInputSync, markTouched, resolveTouched } from '../../sharedInputs.js';

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
  // 라운드 96-보강: 다중 log_folders 입력 (한 줄당 폴더 1개, 최대 8 — B2).
  // UI 전용 필드 — 빌드 payload에서는 제거 후 log_folders 배열로 변환
  // (backend extra='forbid' 422 회피). 입력 시 단일 log_folder보다 우선.
  log_folders_text: '',
  // 51차 — Coverage / SUTR 양식 분리 (이전 단일 template_path)
  coverage_template_path: '',
  sutr_template_path: '',
  swutcr_template_path: '',
  swuds_docx_path: '',
  // 60차 F6-A: SwUTS spec 파일 (xlsm/docx 허용). 제공 시 SUTR Test Log의
  // TC_ID/Description/Precondition/Test Method/Generation Method 컬럼에 spec stamp.
  swuts_docx_path: '',
  // 60차 F6-C: HMR (VectorCAST aggregate metrics report) HTML 경로 (옵션).
  // 제공 시 Coverage Report 3.Coverage 함수별 Function Calls metric stamp.
  hmr_html_path: '',
  // 30차 W21: C 소스 디렉토리 (옵션) — Doxygen @asil 태그에서 함수별 ASIL 추출.
  c_source_root: '',
  // 26차 W16: backend schema에 이미 있던 3 옵션 필드를 frontend에서도 입력
  reviewer_override: '',
  approver_override: '',
  validation_date: '',
};

// 40차: 로컬 isAdminMode helper 제거 — AdminContext.useAdminMode() 사용.

function loadSavedForm() {
  try {
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    // 52차 C1 — legacy template_path key 마이그레이션: 51차 schema 분리 시 이전 key
    // 그대로 보내면 backend 무시. 신규 양식 field가 비어있고 legacy template_path만
    // 있으면 coverage_template_path로 일단 채워서 사용자가 다시 입력하지 않도록 함.
    if (saved.template_path && !saved.coverage_template_path && !saved.sutr_template_path) {
      saved.coverage_template_path = saved.template_path;
    }
    delete saved.template_path;  // 신규 schema에 없는 key 제거
    const base = { ...DEFAULT_FORM, test_date: new Date().toISOString().slice(0, 10), ...saved };
    // 입력 일원화: touched가 아닌(prefill) 매핑 필드만 공유 기본값으로 채움(사용자 입력·빈값 보존).
    const touched = resolveTouched('swut', STORAGE_KEY, saved);
    return applySharedDefaults(base, touched, sharedDefaultsFor('swut', loadSharedInputs()));
  } catch (e) {
    const base = { ...DEFAULT_FORM, test_date: new Date().toISOString().slice(0, 10) };
    return applySharedDefaults(base, new Set(), sharedDefaultsFor('swut', loadSharedInputs()));
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
  // 입력 일원화: Settings 공유값 변경을 같은 세션에서 미변경 필드에 즉시 반영.
  useSharedInputSync('swut', setForm, STORAGE_KEY);
  // 19차: 일관성 검증 state
  const [consistencyForm, setConsistencyForm] = useState({ coverage_path: '', sutr_path: '' });
  const [consistencyChecking, setConsistencyChecking] = useState(false);
  const [consistencyReport, setConsistencyReport] = useState(null);
  // 21차: PathPickerDialog state
  const [picker, setPicker] = useState(null);  // { target, pattern, title, onSelect }
  // 40차: AdminContext 기반.
  const { isAdmin } = useAdminMode();
  const browseDisabledTitle = '관리자 전용 — Ctrl+Shift+A로 admin 모드 활성화';

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
      markTouched(STORAGE_KEY, k);   // 사용자가 손댄 필드 기록 → 공유 동기화에서 제외(freezing 방지)
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
    // 51차 — kind별 필수 template_path 분리. 둘 다 비면 config fallback 시도 (backend가 400 raise).
    const kindTemplate = kind === 'coverage'
      ? form.coverage_template_path
      : kind === 'swutcr'
        ? form.swutcr_template_path
        : form.sutr_template_path;
    // 라운드 96-보강: 다중 log_folders (한 줄당 1개, 최대 8 — backend max_length=8).
    const logFolders = (form.log_folders_text || '')
      .split('\n').map(s => s.trim()).filter(Boolean);
    if (logFolders.length > 8) {
      toast('warning', `다중 로그 폴더는 최대 8개 (현재 ${logFolders.length}개)`); return;
    }
    if (!form.log_folder && logFolders.length === 0 && !kindTemplate) {
      // 라운드 96-보강: 이전엔 차단했으나 backend가 config fallback
      // (swut_log_folders/swut_log_folder + 양식 template 키)을 지원하므로
      // 안내 후 진행. config에도 없으면 backend가 400으로 사유 반환.
      const templateLabel = kind === 'coverage' ? 'Coverage'
        : kind === 'swutcr' ? 'SwUTCR'
          : 'SUTR';
      toast('info', `log_folder/${templateLabel} Template 미입력 — config 기본값(fallback)으로 빌드 시도 (KJPDS02는 APP+BOOT 병합 기본, config에도 없으면 오류 안내)`);
    }

    const user = getUsername();
    if (!user) { toast('warning', '사용자 이름이 설정되지 않음 — Settings 확인'); return; }

    setBuilding(kind);
    setLastSummary(null);
    setLastWarnings([]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      // 라운드 96-보강: log_folders_text(UI 전용)는 payload에서 제거하고
      // (주의: 향후 UI 전용 키 추가 시 동일하게 strip — backend extra='forbid' 422)
      // 비어있지 않으면 log_folders 배열로 변환 (backend 우선순위:
      // log_folders > log_folder > config swut_log_folders > 단수).
      const { log_folders_text: _lfText, ...payload } = form;
      if (logFolders.length > 0) payload.log_folders = logFolders;
      const res = await fetch(buildUrl(`/api/swut/${kind}/build`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...authHeaders(),
        },
        body: JSON.stringify(payload),
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
      const filename = m ? decodeURIComponent(m[1])
        : `swut_${kind}.${kind === 'coverage' ? 'xlsx' : 'xlsm'}`;

      if (!mountedRef.current) return;
      triggerDownload(blob, filename);
      toast('success', `${kind.toUpperCase()} ${(blob.size / 1024).toFixed(0)} KB 다운로드 완료`);
    } catch (e) {
      if (isAbortError(e)) return;
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
      if (isAbortError(e)) return;
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
        <Field name="project_id" label="Project ID *" value={form.project_id} onChange={v => setField('project_id', v)} placeholder="HDPDM01"
               hint="config/swut_meta.json에 등록된 project_id" />
        <Field name="release_sw_version" label="Release SW Version *" value={form.release_sw_version} onChange={v => setField('release_sw_version', v)} placeholder="2.02"
               hint="형식: N.N 또는 N.N.N (예: 2.02, 1.01.05)" />
        <Field name="test_date" label="Test Date *" value={form.test_date} onChange={v => setField('test_date', v)} type="date"
               hint="yyyy-mm-dd 또는 yyyy/mm/dd — Test Summary 시트에 기록" />
        <Field name="test_engineer" label="Test Engineer" value={form.test_engineer} onChange={v => setField('test_engineer', v)} placeholder="JK Kim"
               hint="비우면 산출물 Cover/Test Summary에 노란 강조 표시" />
        <Field name="doc_id_sequence" label="Doc ID Sequence" value={form.doc_id_sequence} onChange={v => setField('doc_id_sequence', v)} placeholder="852"
               hint="숫자만 (예: 852). config의 doc_id_base와 결합" />
        <Field name="hw_version" label="HW Version" value={form.hw_version} onChange={v => setField('hw_version', v)}
               hint="default 1.00" />
        <Field name="asil_level" label="ASIL Level" value={form.asil_level} onChange={v => setField('asil_level', v)}
               hint="default ASIL A (config override 가능)" />
        {/* 26차 W16: Cover/Test Summary에 자동 채움 가능한 옵션 메타 (빈 상태면 산출물 노란 강조) */}
        <Field name="reviewer_override" label="Reviewer" value={form.reviewer_override} onChange={v => setField('reviewer_override', v)} placeholder="검토자 이름"
               hint="빈 상태면 산출물 Cover에 노란 강조 — config의 default_reviewer 우선 활용" />
        <Field name="approver_override" label="Approver" value={form.approver_override} onChange={v => setField('approver_override', v)} placeholder="승인자 이름"
               hint="빈 상태면 산출물 Cover에 노란 강조 — config의 default_approver 우선 활용 (audit 필수)" />
        <Field name="validation_date" label="Validation Date" value={form.validation_date} onChange={v => setField('validation_date', v)} type="date"
               hint="yyyy-mm-dd 또는 yyyy/mm/dd — 빈 상태면 노란 강조" />
      </div>

      <div className="swut-form-row swut-field-with-browse">
        <Field
          name="log_folder"
          label="Log Folder (Jenkins 미사용 시 fallback)"
          value={form.log_folder}
          onChange={v => setField('log_folder', v)}
          placeholder="U:\연구소\...\01.Log\v2.02_240219"
          hint="VectorCAST html report (.html) 보유 디렉토리. Jenkins build_number 제공 시 자동 우선 — 비우면 config 기본 (다중 등록 시 병합)"
          fullWidth
        />
        <button
          className="swut-browse-btn"
          type="button"
          disabled={!isAdmin}
          title={isAdmin ? undefined : browseDisabledTitle}
          onClick={() => openPicker('log_folder', '*', 'Log 디렉토리 선택')}
        >📂 Browse</button>
      </div>
      {/* 라운드 96-보강: 단일 폴더 입력 시 분리 로그 프로젝트 누락 경고 */}
      {(form.log_folder || '').trim() && !(form.log_folders_text || '').trim() && (
        <div className="swut-field-hint" data-testid="swut-single-folder-note">
          ℹ️ 단일 Log Folder만 빌드됩니다 — APP+BOOT 분리 로그 프로젝트(예: KJPDS02 PV)는
          아래 다중 로그 폴더를 사용하거나, 둘 다 비워 config 병합 기본
          (swut_log_folders)을 사용하세요.
        </div>
      )}
      {/* 라운드 96-보강: 다중 log_folders 입력 (B2 — APP+BOOT 병합 빌드) */}
      <div className="swut-form-row">
        <div className="swut-field swut-field-full">
          <label className="swut-field-label" htmlFor="swut-log-folders-text">
            다중 로그 폴더 (옵션 — 한 줄당 1개, 최대 8)
          </label>
          <textarea
            id="swut-log-folders-text"
            data-testid="swut-log-folders-text"
            className="swut-field-input"
            rows={3}
            value={form.log_folders_text}
            onChange={e => setField('log_folders_text', e.target.value)}
            placeholder={'U:\\...\\01.Log\\PV\\1.APP_UT_report_260604\nU:\\...\\01.Log\\PV\\2.BOOT_UT_report_260604\\Report_sort'}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck="false"
            data-form-type="other"
            data-lpignore="true"
          />
          <div className="swut-field-hint">
            입력 시 단일 Log Folder보다 우선 — 분리 로그(APP+BOOT)를 한 산출물로 병합
            빌드. env 중복은 첫 폴더 우선 + 경고 누적 (이중 집계 방지).
          </div>
        </div>
      </div>
      <div className="swut-form-row swut-field-with-browse">
        <Field
          name="coverage_template_path"
          label="Coverage Template Path (xlsx)"
          value={form.coverage_template_path}
          onChange={v => setField('coverage_template_path', v)}
          placeholder="U:\...\(HDPDM01)SwUT Coverage Report_v3.01_240221_R.xlsx"
          hint="Coverage 빌드 전용 — 비우면 config/swut_meta.json의 coverage_report_template 사용"
          fullWidth
        />
        <button
          className="swut-browse-btn"
          type="button"
          disabled={!isAdmin}
          title={isAdmin ? undefined : browseDisabledTitle}
          onClick={() => openPicker('coverage_template_path', '*.xlsx', 'Coverage Template 파일 선택')}
        >📂 Browse</button>
      </div>
      <div className="swut-form-row swut-field-with-browse">
        <Field
          name="sutr_template_path"
          label="SUTR Template Path (xlsm)"
          value={form.sutr_template_path}
          onChange={v => setField('sutr_template_path', v)}
          placeholder="U:\...\(HDPDM01_SUTR) Software Unit Test Result_v3.01_240221_R.xlsm"
          hint="SUTR 빌드 전용 — 비우면 config/swut_meta.json의 sutr_template 사용"
          fullWidth
        />
        <button
          className="swut-browse-btn"
          type="button"
          disabled={!isAdmin}
          title={isAdmin ? undefined : browseDisabledTitle}
          onClick={() => openPicker('sutr_template_path', '*.xlsm', 'SUTR Template 파일 선택')}
        >📂 Browse</button>
      </div>
      <div className="swut-form-row swut-field-with-browse">
        <Field
          name="swutcr_template_path"
          label="SwUTCR Template Path (xlsm)"
          value={form.swutcr_template_path}
          onChange={v => setField('swutcr_template_path', v)}
          placeholder="U:\...\(XXXX_SwUTCR) Software Unit Test Comprehesive Result_v0.10_2XXXXX.xlsm"
          hint="SwUTCR build only. Empty uses config/swut_meta.json swutcr_template"
          fullWidth
        />
        <button
          className="swut-browse-btn"
          type="button"
          disabled={!isAdmin}
          title={isAdmin ? undefined : browseDisabledTitle}
          onClick={() => openPicker('swutcr_template_path', '*.xlsm', 'SwUTCR Template file')}
        >📂 Browse</button>
      </div>
      {/* 52차 — config 자동 사용 정책. SwUDS / C Source는 config의 swuds_docx_path / c_source_root에 등록되면 자동 사용. 사용자 override 필요 시만 펼침. */}
      <details className="swut-advanced-section" style={{ marginTop: 12 }}>
        <summary style={{ cursor: 'pointer', padding: '8px 0', fontSize: '0.92em', color: 'var(--text-muted, #888)' }}>
          ▶ 고급 설정 (config 자동 사용 — override 필요 시만)
        </summary>
        <div className="swut-form-row swut-field-with-browse">
          <Field
            name="swuds_docx_path"
            label="SwUDS Docx Path (선택)"
            value={form.swuds_docx_path}
            onChange={v => setField('swuds_docx_path', v)}
            placeholder="U:\...\(HDPDM01)SwUDS_v3.docx"
            hint="비우면 config/swut_meta.json의 swuds_docx_path 자동 사용. 제공 시 2.Consistency 시트에 SwUDS↔SwUTS 매핑 row + ASIL 추출"
            fullWidth
          />
          <button
            className="swut-browse-btn"
            type="button"
            disabled={!isAdmin}
            title={isAdmin ? undefined : browseDisabledTitle}
            onClick={() => openPicker('swuds_docx_path', '*.docx', 'SwUDS docx 선택')}
          >📂 Browse</button>
        </div>
        <div className="swut-form-row swut-field-with-browse">
          <Field
            name="swuts_docx_path"
            label="SwUTS Spec Path (선택, 60차 F6-A)"
            value={form.swuts_docx_path}
            onChange={v => setField('swuts_docx_path', v)}
            placeholder="U:\...\(KJPDS02_SwUTS) ... .xlsm"
            hint="비우면 config/swut_meta.json의 swuts_docx_path 자동 사용. 제공 시 SUTR Test Log B/C/D + Precondition spec stamp (xlsm/docx 자동 감지)"
            fullWidth
          />
          <button
            className="swut-browse-btn"
            type="button"
            disabled={!isAdmin}
            title={isAdmin ? undefined : browseDisabledTitle}
            onClick={() => openPicker('swuts_docx_path', '*.xlsm;*.xlsx;*.docx', 'SwUTS spec 파일 선택')}
          >📂 Browse</button>
        </div>
        <div className="swut-form-row swut-field-with-browse">
          <Field
            name="hmr_html_path"
            label="HMR HTML Path (선택, 60차 F6-C)"
            value={form.hmr_html_path}
            onChange={v => setField('hmr_html_path', v)}
            placeholder="U:\...\Jenkins_PDSM_UT_metrics_report.html"
            hint="비우면 config의 hmr_html_path 자동 사용. 제공 시 Coverage Report 3.Coverage 함수별 Function Calls metric stamp (VectorCAST aggregate metrics report)"
            fullWidth
          />
          <button
            className="swut-browse-btn"
            type="button"
            disabled={!isAdmin}
            title={isAdmin ? undefined : browseDisabledTitle}
            onClick={() => openPicker('hmr_html_path', '*.html;*.htm', 'HMR HTML 파일 선택')}
          >📂 Browse</button>
        </div>
        <div className="swut-form-row swut-field-with-browse">
          <Field
            name="c_source_root"
            label="C Source Root (선택)"
            value={form.c_source_root}
            onChange={v => setField('c_source_root', v)}
            placeholder="U:\...\HDPDM01\src\"
            hint="비우면 config/swut_meta.json의 c_source_root 자동 사용. 제공 시 Doxygen @asil 추출 — ASIL D 빨강 강조"
            fullWidth
          />
          <button
            className="swut-browse-btn"
            type="button"
            disabled={!isAdmin}
            title={isAdmin ? undefined : browseDisabledTitle}
            onClick={() => openPicker('c_source_root', '*', 'C 소스 디렉토리 선택')}
          >📂 Browse</button>
        </div>
      </details>

      <div className="swut-actions">
        <button
          className="btn-primary"
          disabled={!!building || !isAdmin}
          title={isAdmin ? undefined : browseDisabledTitle}
          onClick={() => buildXlsx('coverage')}
        >
          {building === 'coverage' ? '빌드 중...' : '📊 Coverage Report 빌드 (xlsx)'}
        </button>
        <button
          className="btn-primary"
          disabled={!!building || !isAdmin}
          title={isAdmin ? undefined : browseDisabledTitle}
          onClick={() => buildXlsx('sutr')}
        >
          {building === 'sutr' ? '빌드 중...' : '📝 SUTR 빌드 (xlsm)'}
        </button>
        <button
          className="btn-primary"
          disabled={!!building || !isAdmin}
          title={isAdmin ? undefined : browseDisabledTitle}
          onClick={() => buildXlsx('swutcr')}
        >
          {building === 'swutcr' ? '빌드 중...' : '📚 SwUTCR 빌드 (xlsm)'}
        </button>
      </div>

      {/* 30차 W21 + 31-fix D14: UNKNOWN만 있을 때 panel 숨김 — 사용자에게 의미 부재 */}
      {lastSummary?.asil_distribution &&
       Object.keys(lastSummary.asil_distribution).some(k => k !== 'UNKNOWN') && (
        <div className="swut-asil-distribution-panel" data-testid="swut-asil-distribution">
          <div className="swut-asil-distribution-title">
            🛡️ ASIL 분포 (ISO 26262 audit reviewer 검토 우선순위)
          </div>
          {/* 31-fix D15: audit 정책 공지 노트 — 회사 v3.01 양식 외 색상 확장 명시 */}
          {lastSummary.asil_highlight_policy && (
            <div className="swut-asil-policy-note" data-testid="swut-asil-policy-note">
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
          {/* 31차 W29: B/C/D 각 등급 함수 ID 노출 — null guard 통일 (?? for 30차 캐시 호환) */}
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
          data-testid="swut-blocked-inferred-warning"
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
            hint="위에서 빌드한 xlsx 또는 기존 회사 산출물 path"
            fullWidth
          />
          <button
            className="swut-browse-btn"
            type="button"
            disabled={!isAdmin}
            title={isAdmin ? undefined : browseDisabledTitle}
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
            hint="동일 release_sw_version의 SUTR xlsm — cross-validation 4 항목 비교"
            fullWidth
          />
          <button
            className="swut-browse-btn"
            type="button"
            disabled={!isAdmin}
            title={isAdmin ? undefined : browseDisabledTitle}
            onClick={() => openPicker('consistency.sutr_path', '*.xlsm', 'SUTR 선택')}
          >📂 Browse</button>
        </div>
        <div className="swut-actions">
          <button
            className="btn-primary"
            disabled={consistencyChecking || !isAdmin}
            title={isAdmin ? undefined : browseDisabledTitle}
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

function Field({
  name, label, value, onChange, placeholder = '', type = 'text',
  fullWidth = false, hint = '',
}) {
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
      {hint && <div className="swut-field-hint">{hint}</div>}
    </div>
  );
}
