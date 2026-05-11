import { useState, useCallback } from 'react';
import { getUsername } from '../../api.js';
import { useToast } from '../../App.jsx';

const API_BASE = (typeof window !== 'undefined' && window.__ARIA_API_BASE__)
  || import.meta.env?.VITE_API_BASE_URL || '';

function buildUrl(path) {
  if (!API_BASE) return path;
  return API_BASE.replace(/\/$/, '') + path;
}

/**
 * SwUT (Software Unit Test) Coverage Report / SUTR xlsx 빌드 UI.
 *
 * - Form 입력 (project / release / date / engineer / doc_id_sequence / log_folder / template_path)
 * - Coverage / SUTR 두 버튼 — POST /api/swut/{coverage|sutr}/build → xlsx blob 다운로드
 * - Pydantic 422 / 400 / 500 응답 명시적 에러 토스트 (raw fetch silent failure 회피)
 * - X-User 헤더 + res.ok 검사 (CLAUDE.md mini-checklist #11)
 */
export default function SwUTBuildSection() {
  const toast = useToast();
  const [building, setBuilding] = useState(null); // 'coverage' | 'sutr' | null
  const [lastSummary, setLastSummary] = useState(null);
  const [lastWarnings, setLastWarnings] = useState([]);

  const [form, setForm] = useState(() => {
    // localStorage에서 이전 입력 복원 (재방문 편의)
    try {
      const saved = JSON.parse(localStorage.getItem('devops_v2_swut_form') || '{}');
      return {
        project_id: saved.project_id || 'HDPDM01',
        release_sw_version: saved.release_sw_version || '',
        test_date: saved.test_date || new Date().toISOString().slice(0, 10),
        test_engineer: saved.test_engineer || '',
        doc_id_sequence: saved.doc_id_sequence || '',
        hw_version: saved.hw_version || '1.00',
        asil_level: saved.asil_level || 'ASIL A',
        log_folder: saved.log_folder || '',
        template_path: saved.template_path || '',
      };
    } catch (_) {
      return {
        project_id: 'HDPDM01',
        release_sw_version: '',
        test_date: new Date().toISOString().slice(0, 10),
        test_engineer: '',
        doc_id_sequence: '',
        hw_version: '1.00',
        asil_level: 'ASIL A',
        log_folder: '',
        template_path: '',
      };
    }
  });

  const setField = (k, v) => {
    const next = { ...form, [k]: v };
    setForm(next);
    try {
      localStorage.setItem('devops_v2_swut_form', JSON.stringify(next));
    } catch (_) {}
  };

  const triggerDownload = (blob, filename) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  };

  const buildXlsx = useCallback(async (kind) => {
    // Pydantic 422 직접 차단 — frontend에서도 사전 검사 (필수 3개)
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

    try {
      // CLAUDE.md mini-checklist #11: raw fetch — X-User 헤더 + res.ok 검사 명시.
      // JSON body지만 응답이 xlsx blob이라 api() 헬퍼 사용 불가 → raw fetch.
      const res = await fetch(buildUrl(`/api/swut/${kind}/build`), {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-User': user,
        },
        body: JSON.stringify(form),
      });

      if (!res.ok) {
        let msg = `HTTP ${res.status}`;
        try {
          const j = await res.json();
          msg = j?.detail || j?.message || msg;
          if (Array.isArray(j?.detail)) {
            // Pydantic 422 detail: [{loc, msg, type}]
            msg = j.detail.map(d => `${(d.loc || []).join('.')}: ${d.msg}`).join(', ');
          }
        } catch (_) {}
        toast('error', `${kind.toUpperCase()} 빌드 실패: ${msg}`);
        return;
      }

      // 응답 헤더에서 summary 추출
      try {
        const summaryRaw = res.headers.get('X-SwUT-Summary');
        if (summaryRaw) setLastSummary(JSON.parse(summaryRaw));
        const warningsRaw = res.headers.get('X-SwUT-Warnings');
        if (warningsRaw) setLastWarnings(JSON.parse(warningsRaw));
      } catch (_) {}

      const blob = await res.blob();
      // filename은 Content-Disposition에서 추출 (RFC 5987)
      const cd = res.headers.get('Content-Disposition') || '';
      const m = cd.match(/filename\*=UTF-8''([^;]+)/) || cd.match(/filename="([^"]+)"/);
      const filename = m ? decodeURIComponent(m[1]) : `swut_${kind}.xlsx`;
      triggerDownload(blob, filename);
      toast('success', `${kind.toUpperCase()} ${(blob.size / 1024).toFixed(0)} KB 다운로드 완료`);
    } catch (e) {
      toast('error', `${kind.toUpperCase()} 빌드 실패: ${e?.message || e}`);
    } finally {
      setBuilding(null);
    }
  }, [form, toast]);

  return (
    <div className="section-content">
      <div className="section-header">
        <h2>SwUT 빌드</h2>
        <p className="muted">
          Coverage Report (xlsx) / SUTR (xlsm) 빌드 — Jenkins 캐시 우선, log_folder fallback.
          출력은 브라우저 다운로드 (로컬 디스크 저장). Cloudium은 read-only로 template/log만 접근.
        </p>
      </div>

      <div className="form-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '12px', marginTop: '16px' }}>
        <Field name="project_id" label="Project ID *" value={form.project_id} onChange={v => setField('project_id', v)} placeholder="HDPDM01" />
        <Field name="release_sw_version" label="Release SW Version * (예: 2.02 또는 1.01.05)" value={form.release_sw_version} onChange={v => setField('release_sw_version', v)} placeholder="2.02" />
        <Field name="test_date" label="Test Date * (yyyy-mm-dd)" value={form.test_date} onChange={v => setField('test_date', v)} type="date" />
        <Field name="test_engineer" label="Test Engineer" value={form.test_engineer} onChange={v => setField('test_engineer', v)} placeholder="JK Kim" />
        <Field name="doc_id_sequence" label="Doc ID Sequence (digit)" value={form.doc_id_sequence} onChange={v => setField('doc_id_sequence', v)} placeholder="852" />
        <Field name="hw_version" label="HW Version" value={form.hw_version} onChange={v => setField('hw_version', v)} />
        <Field name="asil_level" label="ASIL Level" value={form.asil_level} onChange={v => setField('asil_level', v)} />
      </div>

      <div style={{ marginTop: '16px' }}>
        <Field
          name="log_folder"
          label="Log Folder (Jenkins 미사용 시 fallback)"
          value={form.log_folder}
          onChange={v => setField('log_folder', v)}
          placeholder="U:\연구소\...\01.Log\v2.02_240219"
          fullWidth
        />
        <Field
          name="template_path"
          label="Template Path (xlsx/xlsm — config default 사용 시 빈 string)"
          value={form.template_path}
          onChange={v => setField('template_path', v)}
          placeholder="U:\...\(HDPDM01)SwUT Coverage Report_v3.01_240221_R.xlsx"
          fullWidth
        />
      </div>

      <div style={{ marginTop: '24px', display: 'flex', gap: '12px' }}>
        <button
          className="primary"
          disabled={!!building}
          onClick={() => buildXlsx('coverage')}
        >
          {building === 'coverage' ? '빌드 중...' : '📊 Coverage Report 빌드 (xlsx)'}
        </button>
        <button
          className="primary"
          disabled={!!building}
          onClick={() => buildXlsx('sutr')}
        >
          {building === 'sutr' ? '빌드 중...' : '📝 SUTR 빌드 (xlsm)'}
        </button>
      </div>

      {lastSummary && (
        <div className="summary-card" style={{ marginTop: '20px', padding: '12px', border: '1px solid var(--border)', borderRadius: '6px' }}>
          <div style={{ fontWeight: 600, marginBottom: '8px' }}>마지막 빌드 결과</div>
          <pre style={{ margin: 0, fontSize: '12px', overflowX: 'auto' }}>
            {JSON.stringify(lastSummary, null, 2)}
          </pre>
        </div>
      )}

      {lastWarnings.length > 0 && (
        <div className="warnings-card" style={{ marginTop: '12px', padding: '12px', border: '1px solid #f0ad4e', borderRadius: '6px', background: '#fffaf0' }}>
          <div style={{ fontWeight: 600, marginBottom: '8px' }}>⚠️ Warnings ({lastWarnings.length})</div>
          <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '12px' }}>
            {lastWarnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Field({ name, label, value, onChange, placeholder = '', type = 'text', fullWidth = false }) {
  const id = `swut-${name}`;
  return (
    <div style={{ gridColumn: fullWidth ? '1 / -1' : undefined }}>
      <label htmlFor={id} style={{ display: 'block', fontSize: '12px', color: 'var(--muted)', marginBottom: '4px' }}>
        {label}
      </label>
      <input
        id={id}
        name={name}
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{ width: '100%', padding: '6px 10px', border: '1px solid var(--border)', borderRadius: '4px' }}
      />
    </div>
  );
}
