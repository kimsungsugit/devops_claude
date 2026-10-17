import {
  loadSharedInputs, sharedDefaultsFor, applySharedDefaults, resolveTouched,
} from './sharedInputs.js';

/**
 * Sw* 빌더(SwUT / SwIT / 통합 Summary)의 **폼 기본값과 payload 조립 단일 출처**.
 *
 * ## 왜 모았나
 *
 * 생성 현황 보드가 같은 산출물을 원클릭으로 만들게 되면서, payload 를 만드는 곳이
 * 빌더 탭과 보드 **두 곳**이 됐다. 조립 로직을 복제하면 두 경로가 서로 다른 문서를
 * 내기 시작하고, 그 차이는 xlsx 를 열어보기 전엔 보이지 않는다. 이 저장소는 같은
 * 패턴(판정/조립 복제 → 한쪽만 수정)으로 이미 여러 번 당했다.
 *
 * ## 여기 있는 것 / 없는 것
 *
 * - **있다**: 기본값, localStorage 복원, 공유 입력 prefill, UI 전용 필드 strip,
 *   줄바꿈 textarea → 배열 변환, 필수값 판정.
 * - **없다**: toast, fetch, 진행 상태. 그건 화면마다 다르므로 호출부에 남긴다.
 *
 * ## backend `extra='forbid'`
 *
 * 세 request schema 모두 unknown 키를 422 로 거절한다. 그래서 `*_text` 같은 UI 전용
 * 필드는 payload 에서 **반드시** 제거해야 한다 — 여기 한 곳에서 한다.
 */

const SWUT_DEFAULT_FORM = {
  project_id: 'HDPDM01',
  release_sw_version: '',
  test_date: '',
  test_engineer: '',
  doc_id_sequence: '',
  hw_version: '1.00',
  asil_level: 'ASIL A',
  log_folder: '',
  // UI 전용 — 한 줄당 폴더 1개(최대 8). payload 에선 log_folders 배열로 변환 후 제거.
  log_folders_text: '',
  // 51차 — Coverage / SUTR / SwUTCR 양식 분리 (이전 단일 template_path)
  coverage_template_path: '',
  sutr_template_path: '',
  swutcr_template_path: '',
  swuds_docx_path: '',
  swuts_docx_path: '',
  hmr_html_path: '',
  c_source_root: '',
  reviewer_override: '',
  approver_override: '',
  validation_date: '',
};

const SWIT_DEFAULT_FORM = {
  project_id: 'HDPDM01',
  release_sw_version: '',
  test_date: '',
  test_engineer: '',
  doc_id_sequence: '',
  hw_version: '1.00',
  asil_level: 'ASIL B',  // SwIT 통합테스트 default
  log_folder: '',
  log_folders_text: '',
  coverage_template_path: '',
  sitr_template_path: '',
  switcr_template_path: '',
  switcv_path: '',
  switr_path: '',
  fault_injection_result_path: '',
  swuds_docx_path: '',
  swuts_docx_path: '',
  hmr_html_path: '',
  c_source_root: '',
  reviewer_override: '',
  approver_override: '',
  validation_date: '',
};

const SWREPORT_DEFAULT_FORM = {
  project_id: 'ES95411',
  release_sw_version: '',
  test_date: '',
  // ES95411 마스터 양식(xlsm) 경로 — 비면 backend config fallback.
  template_path: '',
  // UI 전용 — 레벨별 산출물 경로(한 줄당 1개, 최대 16). payload 에선 source_paths 로 변환.
  source_paths_text: '',
  project_full_name: '',
  asil_level: 'ASIL B',
  phase: '',
  product: '',
  test_target: '',
  test_engineer: '',
};

export const BUILDER_SPECS = {
  swut: {
    storageKey: 'devops_v2_swut_form',
    defaultForm: SWUT_DEFAULT_FORM,
    listField: { text: 'log_folders_text', target: 'log_folders', max: 8, label: '다중 로그 폴더' },
    // 51차 양식 분리 이전의 단일 `template_path` 를 신규 키로 옮긴다(사용자 재입력 방지).
    legacyTemplate: { from: 'template_path', to: 'coverage_template_path', alt: 'sutr_template_path' },
  },
  swit: {
    storageKey: 'devops_v2_swit_form',
    defaultForm: SWIT_DEFAULT_FORM,
    listField: { text: 'log_folders_text', target: 'log_folders', max: 8, label: '다중 로그 폴더' },
    legacyTemplate: { from: 'template_path', to: 'coverage_template_path', alt: 'sitr_template_path' },
  },
  swreport: {
    storageKey: 'devops_v2_swreport_form',
    defaultForm: SWREPORT_DEFAULT_FORM,
    listField: { text: 'source_paths_text', target: 'source_paths', max: 16, label: '산출물 경로' },
    // ⚠ swreport 의 `template_path` 는 **현행 유효 필드**다(ES95411 양식 경로).
    //    swut/swit 처럼 마이그레이션 대상으로 오해해 옮기면 사용자가 지정한 양식이 사라진다.
    legacyTemplate: null,
  },
};

/** 세 schema 공통 필수 3개 — 미충족이면 backend 가 422 를 낸다. */
export const REQUIRED_FIELDS = ['project_id', 'release_sw_version', 'test_date'];

/** 오늘(YYYY-MM-DD). 기존 빌더와 동일하게 `toISOString`(UTC) 기준을 유지한다. */
export function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function specOf(kind) {
  const spec = BUILDER_SPECS[kind];
  if (!spec) throw new Error(`알 수 없는 빌더 종류: ${kind}`);
  return spec;
}

/**
 * 저장된 폼 + 기본값 + 공유 입력(설정 > 입력 자료) 을 합쳐 **실제 사용할 폼**을 만든다.
 *
 * 우선순위: 사용자가 손댄 값(localStorage) > 공유 입력 prefill > 기본값.
 * `resolveTouched` 가 "사용자가 직접 건드린 필드" 를 알려주므로, 공유 입력이 그 값을
 * 덮어쓰지 않는다(빈 문자열로 비워둔 것도 사용자의 의사다).
 */
export function loadBuilderForm(kind) {
  const spec = specOf(kind);
  try {
    const saved = JSON.parse(localStorage.getItem(spec.storageKey) || '{}');
    const lt = spec.legacyTemplate;
    if (lt && saved[lt.from] && !saved[lt.to] && !saved[lt.alt]) {
      saved[lt.to] = saved[lt.from];
    }
    if (lt) delete saved[lt.from];   // 신규 schema 에 없는 키 제거 (extra='forbid')
    const base = { ...spec.defaultForm, test_date: todayIso(), ...saved };
    const touched = resolveTouched(kind, spec.storageKey, saved);
    return applySharedDefaults(base, touched, sharedDefaultsFor(kind, loadSharedInputs()));
  } catch (_e) {
    // 저장값이 깨졌으면 기본값으로 계속 간다 — 폼이 비어 보이면 사용자가 원인을
    // 알 수 없으므로, 여기서 멈추지 않고 공유 입력 prefill 까지는 적용한다.
    const base = { ...spec.defaultForm, test_date: todayIso() };
    return applySharedDefaults(base, new Set(), sharedDefaultsFor(kind, loadSharedInputs()));
  }
}

/** textarea(줄바꿈 구분) → 배열. 빈 줄·공백 제거. */
export function parseListField(kind, form) {
  const { text } = specOf(kind).listField;
  return String(form?.[text] || '')
    .split('\n').map(s => s.trim()).filter(Boolean);
}

/**
 * 폼 → backend payload.
 *
 * UI 전용 필드를 제거하고 배열 필드를 채운다. 배열이 비면 **키 자체를 보내지 않는다** —
 * 빈 배열을 보내면 "명시적으로 0개" 가 되어 backend 의 config fallback 이 죽는다.
 */
export function toBuildPayload(kind, form) {
  const { text, target } = specOf(kind).listField;
  const payload = { ...form };
  delete payload[text];
  const items = parseListField(kind, form);
  if (items.length > 0) payload[target] = items;
  return payload;
}

/** 비어 있는 필수 필드 이름 목록. 빈 배열이면 바로 빌드 가능. */
export function missingRequiredFields(form) {
  return REQUIRED_FIELDS.filter(k => !String(form?.[k] ?? '').trim());
}
