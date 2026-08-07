import { useState, useCallback, useEffect, useRef } from 'react';
import { getUsername, authHeaders, post } from '../../api.js';
import { useToast } from '../../App.jsx';
import { useAdminMode } from '../../contexts/AdminContext.jsx';
import PathPickerDialog from '../PathPickerDialog.jsx';
import { isAbortError } from '../../impactPoll.js';
import { useSharedInputSync, markTouched } from '../../sharedInputs.js';
// 폼 기본값·payload 조립은 생성 현황 보드와 **공유** (복제 시 두 경로가 다른 문서를 낸다).
import { BUILDER_SPECS, loadBuilderForm, toBuildPayload } from '../../swBuilderForms.js';

// API base 해석 — SwUTBuildSection과 동일 (raw fetch blob 전용. JSON은 api.js post() 사용).
const API_BASE = (typeof window !== 'undefined' && window.__ARIA_API_BASE__)
  || import.meta.env?.VITE_API_BASE_URL || '';

function buildUrl(path) {
  if (!API_BASE) return path;
  return API_BASE.replace(/\/$/, '') + path;
}

// 폼 기본값·localStorage 키·UI 전용 키 strip 은 swBuilderForms.js 단일 출처
// (생성 현황 보드가 같은 payload 로 원클릭 생성한다).
const STORAGE_KEY = BUILDER_SPECS.swreport.storageKey;

function loadSavedForm() {
  return loadBuilderForm('swreport');
}

// FastAPI 422 detail(배열/문자열/객체)을 사람이 읽을 한 줄로 정규화.
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

// 폼 → 백엔드 payload 변환 (preview/build 공용).
// source_paths_text(UI 전용)는 제거하고 source_paths 배열로 변환한다.
function buildPayload(form) {
  // strip + 배열 변환은 공유 모듈. 비어있으면 키 자체를 보내지 않는다 —
  // backend 는 template 자체를 source 로 refresh 한다.
  return toBuildPayload('swreport', form);
}

export default function SwReportSummarySection() {
  const toast = useToast();
  const [form, setForm] = useState(loadSavedForm);
  // 입력 일원화: Settings 공유값 변경을 같은 세션에서 미변경 필드에 즉시 반영.
  useSharedInputSync('swreport', setForm, STORAGE_KEY);
  const [previewing, setPreviewing] = useState(false);
  const [building, setBuilding] = useState(false);
  const [preview, setPreview] = useState(null);       // preview JSON {rows, warnings, summary}
  const [lastSummary, setLastSummary] = useState(null); // build 시 X-SwReport-Summary 헤더
  const [lastWarnings, setLastWarnings] = useState([]); // preview/build 공용 warnings
  const [lastIncomplete, setLastIncomplete] = useState([]); // build 시 X-SwReport-Incomplete csv
  // PathPickerDialog state: { target, pattern, title, onSelect }
  const [picker, setPicker] = useState(null);

  const { isAdmin } = useAdminMode();
  const browseDisabledTitle = '관리자 전용 — Ctrl+Shift+A로 admin 모드 활성화';

  // 라이프사이클 ref — SwUTBuildSection과 동일.
  const abortRef = useRef(null);
  const mountedRef = useRef(true);
  // blob URL + revoke timer 추적 — unmount 시 즉시 revoke + clearTimeout.
  const downloadCleanupRef = useRef([]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
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
      markTouched(STORAGE_KEY, k);   // 사용자가 손댄 필드 기록 → 공유 동기화에서 제외(freezing 방지)
    } catch (e) {
      console.warn('SwReport form persist failed:', e?.message || e);
    }
  };

  // PathPickerDialog 열기. target='template_path'는 template, 'source_append'는
  // 선택한 파일을 source_paths_text 끝에 한 줄 추가.
  const openPicker = (target, pattern, title) => {
    let onSelect;
    if (target === 'source_append') {
      onSelect = v => {
        const cur = (form.source_paths_text || '').replace(/\s*$/, '');
        const next = cur ? `${cur}\n${v}` : v;
        setField('source_paths_text', next);
      };
    } else {
      onSelect = v => setField(target, v);
    }
    setPicker({ target, pattern, title, onSelect });
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

  // 필수 입력 + 사용자 이름 공통 검증. 통과 시 user 반환, 실패 시 null.
  const validateCommon = () => {
    if (!form.project_id) { toast('warning', 'project_id 필수'); return null; }
    if (!form.release_sw_version) { toast('warning', 'release_sw_version 필수'); return null; }
    if (!form.test_date) { toast('warning', 'test_date 필수'); return null; }
    const sourcePaths = (form.source_paths_text || '')
      .split('\n').map(s => s.trim()).filter(Boolean);
    if (sourcePaths.length > 16) {
      toast('warning', `산출물 경로는 최대 16개 (현재 ${sourcePaths.length}개)`); return null;
    }
    const user = getUsername();
    if (!user) { toast('warning', '사용자 이름이 설정되지 않음 — Settings 확인'); return null; }
    return user;
  };

  // 미리보기 — JSON 응답이므로 api.js post() 헬퍼 사용 (raw fetch 금지, mini-checklist X9).
  const runPreview = useCallback(async () => {
    if (!validateCommon()) return;
    setPreviewing(true);
    setPreview(null);
    setLastWarnings([]);
    try {
      const payload = buildPayload(form);
      const data = await post('/api/swreport/summary/preview', payload);
      if (!mountedRef.current) return;
      setPreview(data);
      setLastWarnings(Array.isArray(data?.warnings) ? data.warnings : []);
      const failCount = data?.summary?.fail_count ?? 0;
      if (failCount > 0) {
        toast('warning', `미리보기 완료 — FAIL ${failCount}건 (표 강조 확인)`);
      } else {
        toast('success', `미리보기 완료 — ${data?.summary?.rows_total ?? 0}행`);
      }
    } catch (e) {
      if (!mountedRef.current) return;
      // post() 헬퍼는 Error를 throw — message에 detail 정규화 포함됨.
      const msg = formatDetailMessage(e?.detail) || e?.message || String(e);
      toast('error', `미리보기 실패: ${msg}`);
    } finally {
      if (mountedRef.current) setPreviewing(false);
    }
  }, [form, toast]);

  // Excel 빌드·다운로드 — xlsm blob 응답이므로 raw fetch + authHeaders() + res.ok 명시 검사.
  const runBuild = useCallback(async () => {
    if (!validateCommon()) return;
    setBuilding(true);
    setLastSummary(null);
    setLastWarnings([]);
    setLastIncomplete([]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const payload = buildPayload(form);
      const res = await fetch(buildUrl('/api/swreport/summary/build'), {
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
          toast('error', `Summary 빌드 실패: ${msg}`);
        }
        return;
      }

      // 응답 헤더 메타 파싱 (X-SwReport-Summary / Warnings JSON, Incomplete csv).
      try {
        const summaryRaw = res.headers.get('X-SwReport-Summary');
        if (summaryRaw && mountedRef.current) setLastSummary(JSON.parse(summaryRaw));
        const warningsRaw = res.headers.get('X-SwReport-Warnings');
        if (warningsRaw && mountedRef.current) setLastWarnings(JSON.parse(warningsRaw));
        const incompleteRaw = res.headers.get('X-SwReport-Incomplete');
        if (incompleteRaw && mountedRef.current) {
          setLastIncomplete(incompleteRaw.split(',').map(s => s.trim()).filter(Boolean));
        }
      } catch (e) {
        console.warn('X-SwReport-* header parse failed:', e?.message || e);
      }

      const blob = await res.blob();
      const cd = res.headers.get('Content-Disposition') || '';
      const m = cd.match(/filename\*=UTF-8''([^;]+)/) || cd.match(/filename="([^"]+)"/);
      const filename = m ? decodeURIComponent(m[1]) : 'swreport_summary.xlsm';

      if (!mountedRef.current) return;
      triggerDownload(blob, filename);
      toast('success', `통합 Summary ${(blob.size / 1024).toFixed(0)} KB 다운로드 완료`);
    } catch (e) {
      if (isAbortError(e)) return;
      if (mountedRef.current) {
        toast('error', `Summary 빌드 실패: ${e?.message || e}`);
      }
    } finally {
      if (mountedRef.current) setBuilding(false);
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, [form, toast]);

  const busy = previewing || building;
  const summary = preview?.summary || null;
  const rows = Array.isArray(preview?.rows) ? preview.rows : [];

  return (
    <div className="swut-section">
      <div className="swut-section-header">
        <h2>🔗 통합 결과 정리 (ES95411 마스터)</h2>
        <p className="swut-section-desc">
          전 레벨(SwUT/SwIT/SwSA 등) 산출물을 ES95411 마스터 양식에 통합한 Summary를
          미리보기(JSON)하고 .xlsm로 다운로드합니다. 미리보기로 행/매칭/FAIL을 확인한 뒤
          빌드하세요. 출력은 브라우저 다운로드 (로컬 디스크 저장).
        </p>
      </div>

      <div className="swut-form-grid">
        <Field name="project_id" label="Project ID *" value={form.project_id} onChange={v => setField('project_id', v)} placeholder="ES95411"
               hint="통합 Summary 마스터 project_id" />
        <Field name="release_sw_version" label="Release SW Version *" value={form.release_sw_version} onChange={v => setField('release_sw_version', v)} placeholder="2.02"
               hint="형식: N.N 또는 N.N.N (예: 2.02, 1.01.05)" />
        <Field name="test_date" label="Test Date *" value={form.test_date} onChange={v => setField('test_date', v)} type="date"
               hint="yyyy-mm-dd 또는 yyyy/mm/dd — Summary 시트에 기록" />
        <Field name="project_full_name" label="Project Full Name" value={form.project_full_name} onChange={v => setField('project_full_name', v)} placeholder="프로젝트 정식명"
               hint="Cover에 기록 (옵션)" />
        <Field name="asil_level" label="ASIL Level" value={form.asil_level} onChange={v => setField('asil_level', v)}
               hint="default ASIL B (config override 가능)" />
        <Field name="phase" label="Phase" value={form.phase} onChange={v => setField('phase', v)} placeholder="PV / SOP 등"
               hint="개발 단계 (옵션)" />
        <Field name="product" label="Product" value={form.product} onChange={v => setField('product', v)} placeholder="제품명"
               hint="제품 식별 (옵션)" />
        <Field name="test_target" label="Test Target" value={form.test_target} onChange={v => setField('test_target', v)} placeholder="시험 대상"
               hint="시험 대상 식별 (옵션)" />
        <Field name="test_engineer" label="Test Engineer" value={form.test_engineer} onChange={v => setField('test_engineer', v)} placeholder="JK Kim"
               hint="비우면 산출물에 노란 강조 표시" />
      </div>

      {/* ES95411 마스터 양식(xlsm) 경로 + Browse */}
      <div className="swut-form-row swut-field-with-browse">
        <Field
          name="template_path"
          label="Template Path (ES95411 양식 xlsm)"
          value={form.template_path}
          onChange={v => setField('template_path', v)}
          placeholder="U:\...\(ES95411) Integrated Summary_master.xlsm"
          hint="비우면 config 기본 양식 사용. 비면 template 자체를 source로 refresh"
          fullWidth
        />
        <button
          className="swut-browse-btn"
          type="button"
          disabled={!isAdmin}
          title={isAdmin ? undefined : browseDisabledTitle}
          onClick={() => openPicker('template_path', '*.xlsm,*.xlsx', 'ES95411 마스터 양식 선택')}
        >📂 Browse</button>
      </div>

      {/* 레벨별 산출물 경로 (UI 전용 textarea — payload 변환 시 source_paths 배열) */}
      <div className="swut-form-row">
        <div className="swut-field swut-field-full">
          <label className="swut-field-label" htmlFor="swreport-source-paths-text">
            레벨별 산출물 경로 (옵션 — 한 줄당 1개, 최대 16)
          </label>
          <textarea
            id="swreport-source-paths-text"
            data-testid="swreport-source-paths-text"
            className="swut-field-input"
            rows={4}
            value={form.source_paths_text}
            onChange={e => setField('source_paths_text', e.target.value)}
            placeholder={'U:\\...\\(HDPDM01_SUTR) Software Unit Test Result.xlsm\nU:\\...\\(HDPDM01_SwIT) Software Integration Test Result.xlsm'}
            autoComplete="off"
            autoCorrect="off"
            autoCapitalize="off"
            spellCheck="false"
            data-form-type="other"
            data-lpignore="true"
          />
          <div className="swut-field-hint">
            각 레벨(SwUT/SwIT/SwSA 등) 산출물 경로. 비우면 template 자체를 source로 refresh.
            Browse(📂)로 한 줄씩 추가하거나 직접 입력하세요.
          </div>
          <div className="swut-actions" style={{ marginTop: 6 }}>
            <button
              className="swut-browse-btn"
              type="button"
              disabled={!isAdmin}
              title={isAdmin ? undefined : browseDisabledTitle}
              onClick={() => openPicker('source_append', '*.xlsm,*.xlsx', '산출물 경로 추가')}
            >📂 Browse (행 추가)</button>
          </div>
        </div>
      </div>

      <div className="swut-actions">
        <button
          className="btn-primary"
          disabled={busy || !isAdmin}
          title={isAdmin ? undefined : browseDisabledTitle}
          onClick={runPreview}
        >
          {previewing ? '미리보기 중...' : '👁️ 미리보기 (JSON)'}
        </button>
        <button
          className="btn-primary"
          disabled={busy || !isAdmin}
          title={isAdmin ? undefined : browseDisabledTitle}
          onClick={runBuild}
        >
          {building ? '빌드 중...' : '🔗 Excel 빌드·다운로드 (xlsm)'}
        </button>
      </div>

      <PathPickerDialog
        open={!!picker}
        initialPath={picker?.target === 'template_path' ? form.template_path : ''}
        pattern={picker?.pattern || '*'}
        title={picker?.title || '경로 선택'}
        onSelect={picker?.onSelect}
        onClose={() => setPicker(null)}
      />

      {/* 미리보기 summary 카운트 카드 */}
      {summary && (
        <div className="swut-summary-card">
          <div className="swut-summary-title">미리보기 Summary</div>
          <ul className="swut-asil-distribution-list" data-testid="swreport-summary-counts">
            <li><span className="swut-asil-label">전체 행</span><span className="swut-asil-count">{summary.rows_total ?? 0}</span></li>
            <li><span className="swut-asil-label">수행</span><span className="swut-asil-count">{summary.performed_count ?? 0}</span></li>
            <li><span className="swut-asil-label">매칭</span><span className="swut-asil-count">{summary.matched_rows ?? 0}</span></li>
            <li className={summary.fail_count > 0 ? 'swut-issue-critical' : undefined}>
              <span className="swut-asil-label">FAIL</span><span className="swut-asil-count">{summary.fail_count ?? 0}</span>
            </li>
            <li><span className="swut-asil-label">총 시간</span><span className="swut-asil-count">{summary.total_hours ?? 0}</span></li>
            <li><span className="swut-asil-label">소스 수</span><span className="swut-asil-count">{summary.source_count ?? 0}</span></li>
            <li>
              <span className="swut-asil-label">종합 결과</span>
              <span className={`pill ${/fail/i.test(String(summary.overall_result || '')) ? 'pill-danger' : 'pill-success'}`}>
                {summary.overall_result || '-'}
              </span>
            </li>
          </ul>
          {Array.isArray(summary.fail_ids) && summary.fail_ids.length > 0 && (
            <div className="swut-asil-d-functions" data-testid="swreport-fail-ids">
              <strong>FAIL ID:</strong> {summary.fail_ids.join(', ')}
            </div>
          )}
        </div>
      )}

      {/* 미리보기 rows 표 — matched=false 또는 pf에 Fail 포함 행은 시각 강조 */}
      {rows.length > 0 && (
        <div className="swut-summary-card" data-testid="swreport-rows-card">
          <div className="swut-summary-title">통합 행 ({rows.length})</div>
          <div style={{ overflowX: 'auto' }}>
            <table className="impact-table">
              <thead>
                <tr>
                  <th>No</th>
                  <th>ID</th>
                  <th>이름</th>
                  <th>Category</th>
                  <th>Tool</th>
                  <th>계획</th>
                  <th>매칭</th>
                  <th>P/F</th>
                  <th>시간</th>
                  <th>Tester</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => {
                  const isFail = /fail/i.test(String(r?.pf || ''));
                  const unmatched = r?.matched === false;
                  // matched=false → warning 강조, Fail → critical 강조 (기존 swut-issue-* 클래스 재사용).
                  const rowClass = isFail ? 'swut-issue-critical'
                    : unmatched ? 'swut-issue-warning' : undefined;
                  return (
                    <tr key={`${r?.id ?? 'row'}-${r?.row ?? i}`} className={rowClass}>
                      <td>{r?.row ?? i + 1}</td>
                      <td style={{ fontFamily: 'monospace', fontSize: 11 }}>{r?.id ?? '-'}</td>
                      <td className="text-sm">{r?.name ?? '-'}</td>
                      <td className="text-sm">{r?.category ?? '-'}</td>
                      <td className="text-sm">{r?.tool ?? '-'}</td>
                      <td className="text-sm">{r?.planned ?? '-'}</td>
                      <td>
                        <span className={`pill ${unmatched ? 'pill-warning' : 'pill-success'}`}>
                          {unmatched ? '미매칭' : '매칭'}
                        </span>
                      </td>
                      <td>
                        <span className={`pill ${isFail ? 'pill-danger' : 'pill-neutral'}`}>
                          {r?.pf ?? '-'}
                        </span>
                      </td>
                      <td className="text-sm">{r?.hours ?? '-'}</td>
                      <td className="text-sm">{r?.tester ?? '-'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* 빌드 결과 헤더 summary (X-SwReport-Summary) */}
      {lastSummary && (
        <div className="swut-summary-card">
          <div className="swut-summary-title">마지막 빌드 결과</div>
          <pre className="swut-summary-pre">{JSON.stringify(lastSummary, null, 2)}</pre>
        </div>
      )}

      {/* 빌드 시 미완성(incomplete) 목록 — X-SwReport-Incomplete csv */}
      {lastIncomplete.length > 0 && (
        <div className="swut-warnings-card" data-testid="swreport-incomplete-card">
          <div className="swut-warnings-title">🟡 미완성 / 입력 필요 ({lastIncomplete.length})</div>
          <ul className="swut-warnings-list">
            {lastIncomplete.map((c, i) => (<li key={i}>{c}</li>))}
          </ul>
        </div>
      )}

      {/* preview/build 공용 warnings (swut-warnings-card 재사용) */}
      {lastWarnings.length > 0 && (
        <div className="swut-warnings-card">
          <div className="swut-warnings-title">⚠️ Warnings ({lastWarnings.length})</div>
          <ul className="swut-warnings-list">
            {lastWarnings.map((w, i) => (<li key={i}>{w}</li>))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Field({
  name, label, value, onChange, placeholder = '', type = 'text',
  fullWidth = false, hint = '',
}) {
  const id = `swreport-${name}`;
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
