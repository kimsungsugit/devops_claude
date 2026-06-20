/**
 * 공유 입력 저장소 (입력 점진 일원화)
 * ---------------------------------------------------------------------------
 * Settings "입력 자료 설정"에서 한 번 등록한 템플릿/로그 폴더/공통 메타를
 * 모든 생성 섹션(SwUT/SwIT/SwSA/통합결과)이 빈 칸일 때 자동으로 끌어다 쓰도록 하는
 * 공유 localStorage 저장소. 백엔드 변경 없음 — 각 섹션은 기존 payload 키만 그대로
 * 채우므로 Pydantic extra='forbid' 422 위험 없음.
 *
 * 우선순위(병합): 각 섹션의 per-section 저장값(non-empty) > 공유 기본값(non-empty)
 *                > 컴포넌트 DEFAULT_FORM. (사용자가 입력한 값은 절대 덮지 않음)
 *
 * 문서 경로(srs/sds/uds/... + UDS 템플릿)는 기존 키 'devops_v2_doc_paths'를
 * 그대로 사용한다(DocGenSection이 이미 읽음). 본 모듈은 Sw* 양식/로그/메타 전용.
 */

import { useEffect } from 'react';

export const SHARED_KEY = 'devops_v2_shared_inputs';

// 공유 입력이 같은 탭에서 바뀌었음을 알리는 커스텀 이벤트(다른 탭은 'storage' 이벤트).
// 열려있는(keep-alive) 생성 섹션이 이를 구독해 미변경 필드를 즉시 갱신한다.
export const SHARED_EVENT = 'aria-shared-inputs-changed';

/** 공유 입력 객체 로드 (항상 객체 반환). */
export function loadSharedInputs() {
  try {
    const v = JSON.parse(localStorage.getItem(SHARED_KEY) || '{}');
    return v && typeof v === 'object' ? v : {};
  } catch {
    return {};
  }
}

// 쓰기는 즉시(loadSavedForm은 항상 최신 localStorage를 읽음) 하되, 같은 탭 구독자 알림은
// 디바운스 — Settings 키스트로크 폭주 시 마운트된 N개 섹션이 매 입력마다 재sync하는 낭비 완화.
let _notifyTimer = null;
function notifySharedChange() {
  if (_notifyTimer) clearTimeout(_notifyTimer);
  _notifyTimer = setTimeout(() => {
    _notifyTimer = null;
    try { window.dispatchEvent(new Event(SHARED_EVENT)); } catch { /* no-window */ }
  }, 150);
}

/** 공유 입력 전체 저장 + 같은 탭 구독자에게 변경 알림(디바운스). */
export function saveSharedInputs(obj) {
  localStorage.setItem(SHARED_KEY, JSON.stringify(obj || {}));
  notifySharedChange();
}

/** 공유 입력 단일 키 갱신 후 갱신된 객체 반환. */
export function saveSharedInput(key, val) {
  const cur = loadSharedInputs();
  cur[key] = val;
  saveSharedInputs(cur);
  return cur;
}

/**
 * Settings UI 렌더용 그룹 정의. 각 항목 key는 공유 저장소의 정규 키.
 * browse: '/api/file-mode/browse-file' kind('file'|'directory'). multiline: textarea.
 */
export const SHARED_FIELD_GROUPS = [
  {
    title: '공통 메타',
    open: true,
    keys: [
      { key: 'project_id', label: 'Project ID', ph: 'HDPDM01' },
      { key: 'hw_version', label: 'HW 버전', ph: '1.00' },
      { key: 'asil_level', label: 'ASIL 레벨', ph: 'ASIL A' },
      { key: 'test_engineer', label: '시험 엔지니어', ph: 'JK Kim' },
      { key: 'reviewer', label: '검토자', ph: '검토자 이름' },
      { key: 'approver', label: '승인자', ph: '승인자 이름' },
      { key: 'c_source_root', label: 'C 소스 루트', ph: 'D:\\Project\\...\\src', browse: 'directory' },
    ],
  },
  {
    title: '템플릿 (양식 경로)',
    keys: [
      { key: 'tpl_coverage', label: 'Coverage 템플릿 (xlsx)', ph: '...(Coverage Report).xlsx', browse: 'file' },
      { key: 'tpl_sutr', label: 'SUTR 템플릿 (xlsm)', ph: '...(SwUTR).xlsm', browse: 'file' },
      { key: 'tpl_swutcr', label: 'SwUTCR 템플릿 (xlsm)', ph: '...(SwUTCR).xlsm', browse: 'file' },
      { key: 'tpl_sitr', label: 'SITR 템플릿 (xlsm)', ph: '...(SwITR).xlsm', browse: 'file' },
      { key: 'tpl_switcr', label: 'SwITCR 템플릿 (xlsm)', ph: '...(SwITCR).xlsm', browse: 'file' },
      { key: 'tpl_swsa', label: 'SwSA 양식 (xlsm)', ph: '...(SwSA Report).xlsm', browse: 'file' },
      { key: 'tpl_es95411', label: 'ES95411 통합 마스터 (xlsm)', ph: '...(ES95411) Integrated Summary.xlsm', browse: 'file' },
    ],
  },
  {
    title: '공유 근거 문서',
    keys: [
      { key: 'swuds_docx', label: 'SwUDS docx', ph: '...(SwUDS).docx', browse: 'file' },
      { key: 'swuts_docx', label: 'SwUTS/SwITS spec (xlsm/docx)', ph: '...spec.xlsm', browse: 'file' },
      { key: 'hmr_html', label: 'HMR HTML (VectorCAST aggregate)', ph: '...HMR.html', browse: 'file' },
    ],
  },
  {
    title: '로그 폴더',
    keys: [
      { key: 'log_vectorcast', label: 'VectorCAST 로그 폴더 (한 줄당 1개, 최대 8)', ph: 'U:\\...\\01.Log\\PV', multiline: true },
      { key: 'log_qac_prqa', label: 'QAC·PRQA 리포트 폴더', ph: 'D:\\...\\PRQA\\reports', browse: 'directory' },
      { key: 'log_swsa', label: 'SwSA 정적분석 01.Log 폴더', ph: 'U:\\...\\08.SW 정적분석\\01.Log\\PV', browse: 'directory' },
    ],
  },
];

/**
 * 공유 정규 키 → 각 섹션 폼 필드명 매핑.
 * (값이 비어있는 공유 키는 sharedDefaultsFor에서 제외된다.)
 */
const FIELD_MAP = {
  swut: {
    project_id: 'project_id',
    hw_version: 'hw_version',
    asil_level: 'asil_level',
    test_engineer: 'test_engineer',
    reviewer: 'reviewer_override',
    approver: 'approver_override',
    c_source_root: 'c_source_root',
    tpl_coverage: 'coverage_template_path',
    tpl_sutr: 'sutr_template_path',
    tpl_swutcr: 'swutcr_template_path',
    swuds_docx: 'swuds_docx_path',
    swuts_docx: 'swuts_docx_path',
    hmr_html: 'hmr_html_path',
    log_vectorcast: 'log_folders_text',
  },
  swit: {
    project_id: 'project_id',
    hw_version: 'hw_version',
    asil_level: 'asil_level',
    test_engineer: 'test_engineer',
    reviewer: 'reviewer_override',
    approver: 'approver_override',
    c_source_root: 'c_source_root',
    tpl_coverage: 'coverage_template_path',
    tpl_sitr: 'sitr_template_path',
    tpl_switcr: 'switcr_template_path',
    swuds_docx: 'swuds_docx_path',
    swuts_docx: 'swuts_docx_path',
    hmr_html: 'hmr_html_path',
    log_vectorcast: 'log_folders_text',
  },
  swsa: {
    project_id: 'project_id',
    asil_level: 'asil_level',
    test_engineer: 'test_engineer',
    reviewer: 'reviewer_override',
    approver: 'approver_override',
    tpl_swsa: 'template_path',
    log_swsa: 'log_folder',
  },
  swreport: {
    project_id: 'project_id',
    asil_level: 'asil_level',
    test_engineer: 'test_engineer',
    tpl_es95411: 'template_path',
  },
};

/**
 * 섹션용 공유 기본값 산출 — { <섹션 폼 필드명>: <공유 값> } (비어있는 공유 값은 제외).
 * @param {string} sectionKey 'swut'|'swit'|'swsa'|'swreport'
 * @param {object} shared loadSharedInputs() 결과
 */
export function sharedDefaultsFor(sectionKey, shared) {
  const map = FIELD_MAP[sectionKey] || {};
  const out = {};
  for (const [canon, field] of Object.entries(map)) {
    const v = shared?.[canon];
    if (v != null && v !== '') out[field] = v;
  }
  return out;
}

/** 섹션의 모든 매핑 폼 필드명 목록. */
function mappedFieldNames(sectionKey) {
  return Object.values(FIELD_MAP[sectionKey] || {});
}

// ── '사용자가 손댄 필드(touched)' 추적 ──────────────────────────────────────
// 별도 localStorage 키(`<storageKey>__touched`)에 보관 — 폼/빌드 payload와 분리되어
// Pydantic extra='forbid' 422 위험 없음. 값(빈/비빈)으로 추론할 수 없는 '출처(사용자 vs prefill)'를
// 명시적으로 기록한다. 이로써 (1)미touched 필드는 공유값을 따라가고(freezing 방지),
// (2)사용자 입력은 보존되며, (3)사용자가 비운 필드도 빈 상태로 보존된다(RT-1).
const touchedKeyOf = (storageKey) => `${storageKey}__touched`;

function loadTouchedRaw(storageKey) {
  try {
    const raw = localStorage.getItem(touchedKeyOf(storageKey));
    return raw ? new Set(JSON.parse(raw) || []) : null;
  } catch {
    return null;
  }
}

function saveTouched(storageKey, set) {
  try { localStorage.setItem(touchedKeyOf(storageKey), JSON.stringify([...set])); } catch { /* ignore */ }
}

/** 사용자가 직접 변경한 필드를 touched로 기록(setField에서 호출). */
export function markTouched(storageKey, field) {
  const set = loadTouchedRaw(storageKey) || new Set();
  if (!set.has(field)) { set.add(field); saveTouched(storageKey, set); }
}

/**
 * touched 세트 해석. 세트가 아직 없으면(기존 사용자) saved의 non-empty 매핑값을 touched로
 * 간주해 1회 마이그레이션 — 기존에 입력해둔 값이 공유 기본값으로 덮이지 않도록 보호한다.
 */
export function resolveTouched(sectionKey, storageKey, saved) {
  const existing = loadTouchedRaw(storageKey);
  if (existing) return existing;
  const migrated = new Set(
    mappedFieldNames(sectionKey).filter(f => saved && saved[f] != null && saved[f] !== '')
  );
  saveTouched(storageKey, migrated);
  return migrated;
}

/**
 * 폼 병합 — 매핑 필드 중 'touched가 아닌'(prefill/기본값) 필드만 공유 기본값으로 채운다.
 * touched 필드는 base(=사용자 영속값, 빈값 포함) 그대로 보존. 비매핑 필드도 base 그대로.
 * @param {object} base    { ...DEFAULT_FORM, test_date, ...saved }
 * @param {Set}    touched resolveTouched() 결과
 * @param {object} mapped  sharedDefaultsFor() 결과
 */
export function applySharedDefaults(base, touched, mapped) {
  const out = { ...base };
  for (const [field, val] of Object.entries(mapped)) {
    if (!touched.has(field)) out[field] = val;
  }
  return out;
}

/**
 * keep-alive로 마운트 유지되는 생성 섹션이 Settings의 공유 입력 변경을 같은 세션에서
 * 즉시 반영하도록 하는 훅. touched가 아닌(prefill/기본값) 매핑 필드만 현재 공유값으로 갱신하고,
 * 사용자가 손댄 필드(빈값 포함)는 절대 덮지 않는다 — mount 경로(applySharedDefaults)와 동일 기준.
 * @param {string} sectionKey 'swut'|'swit'|'swsa'|'swreport'
 * @param {Function} setForm 섹션 form setState
 * @param {string} storageKey 섹션 per-section localStorage 키 (예: 'devops_v2_swut_form')
 */
export function useSharedInputSync(sectionKey, setForm, storageKey) {
  useEffect(() => {
    const sync = () => {
      const mapped = sharedDefaultsFor(sectionKey, loadSharedInputs());
      const touched = loadTouchedRaw(storageKey) || new Set();
      setForm(f => {
        let changed = false;
        const out = { ...f };
        for (const [field, val] of Object.entries(mapped)) {
          if (!touched.has(field) && out[field] !== val) {
            out[field] = val;
            changed = true;
          }
        }
        return changed ? out : f;
      });
    };
    // 다른 탭의 storage 이벤트는 SHARED_KEY 변경(또는 clear, key=null)일 때만 반응 — 무관 키 과발화 차단.
    const onStorage = (e) => { if (!e || e.key === SHARED_KEY || e.key == null) sync(); };
    window.addEventListener(SHARED_EVENT, sync);
    window.addEventListener('storage', onStorage);
    return () => {
      window.removeEventListener(SHARED_EVENT, sync);
      window.removeEventListener('storage', onStorage);
    };
  }, [sectionKey, setForm, storageKey]);
}
