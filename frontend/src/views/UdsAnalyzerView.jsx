import { useEffect, useMemo, useState, useCallback, useRef } from "react";
import UdsViewerWorkspace from "../components/UdsViewerWorkspace";
import TraceabilityPanel from "../components/TraceabilityPanel";
import StsGeneratorPanel from "../components/StsGeneratorPanel";
import SutsGeneratorPanel from "../components/SutsGeneratorPanel";
import SitsGeneratorPanel from "../components/SitsGeneratorPanel";
import ReportMarkdownPreview from "../components/ReportMarkdownPreview";
import SdsDocumentViewer from "../components/docs/SdsDocumentViewer";
import { LocalScmPanel } from "../components/local";

const fetchJson = async (url, options = {}) => {
  const timeoutMs = Number(options?.timeoutMs || 180000);
  const { timeoutMs: _omitTimeout, ...rest } = options || {};
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(url, { ...rest, signal: rest?.signal || controller.signal });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || `HTTP ${res.status}`);
    }
    return res.json();
  } catch (e) {
    if (e?.name === "AbortError") throw new Error(`Request timeout (${Math.round(timeoutMs / 1000)}s)`);
    throw e;
  } finally {
    clearTimeout(timer);
  }
};

const isAbsolutePath = (value) => /^[a-zA-Z]:[\\/]/.test(String(value || "")) || String(value || "").startsWith("/");

const buildQuery = (params) => {
  const qs = new URLSearchParams();
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") return;
    qs.set(key, String(value));
  });
  return qs.toString();
};

const IMPACT_TARGETS = ["uds", "suts", "sits", "sts", "sds"];

const summarizeUdsDiff = (row) => {
  const before = row?.before || {};
  const after = row?.after || {};
  return `calls ${before.calls_count || 0} -> ${after.calls_count || 0}, globals ${before.globals_count || 0} -> ${after.globals_count || 0}, outputs ${before.output_count || 0} -> ${after.output_count || 0}`;
};

const summarizeUds = (data) => {
  const mapping = data?.summary?.mapping || {};
  return {
    title: "UDS",
    filename: data?.filename || "",
    primary: [
      { label: "Total", value: mapping.total ?? 0 },
      { label: "Direct", value: mapping.direct ?? 0 },
      { label: "Fallback", value: mapping.fallback ?? 0 },
    ],
    validation: { valid: mapping.unmapped === 0 },
    generatedAt: data?.summary?.generated_at || "",
    downloadUrl: data?.download_url || "",
    validationReportPath: data?.validation_report_path || "",
    buildLabel: data?.summary?.build_label || data?.build_label || "",
  };
};

const summarizeExcel = (title, data) => {
  const primary = Array.isArray(data?.summary?.primary) ? data.summary.primary.slice(0, 3) : [];
  return {
    title,
    filename: data?.filename || "",
    primary,
    validation: data?.summary?.validation || null,
    generatedAt: data?.summary?.generated_at || "",
    downloadUrl: data?.download_url || "",
    validationReportPath: data?.validation_report_path || "",
    buildLabel: data?.summary?.build_label || data?.build_label || "",
  };
};

const summarizeSits = (overviewDetail) => ({
  title: "SITS",
  filename: "planned_workspace",
  primary: [
    { label: "Files", value: Array.isArray(overviewDetail?.changed_files) ? overviewDetail.changed_files.length : 0 },
    { label: "Functions", value: overviewDetail?.changed_functions && typeof overviewDetail.changed_functions === "object" ? Object.keys(overviewDetail.changed_functions).length : 0 },
    { label: "Status", value: "PLAN" },
  ],
  validation: null,
  generatedAt: overviewDetail?.timestamp || "",
  downloadUrl: "",
  validationReportPath: "",
  buildLabel: "Coming soon",
});

const buildReviewGuidance = (changeDetail) => {
  const entries = changeDetail?.changed_functions && typeof changeDetail.changed_functions === "object"
    ? Object.entries(changeDetail.changed_functions)
    : [];
  if (entries.length === 0) return [];

  const guidance = [];
  const kinds = new Set(entries.map(([, kind]) => String(kind || "").toUpperCase()));

  if (kinds.has("HEADER") || kinds.has("SIGNATURE")) {
    guidance.push("인터페이스가 변경되었습니다. 요구사항 연결, 입력/출력 조건, STS 테스트 명세 추적 관계를 우선 검토하세요.");
    guidance.push("입출력 값, 호출 조건, 관련 모듈 계약이 바뀌었는지 함께 확인하는 것이 좋습니다.");
  }
  if (kinds.has("BODY")) {
    guidance.push("동작 로직이 변경되었습니다. 기대 결과, 분기 커버리지, 예외 처리 assertion을 다시 검토하세요.");
  }
  if (kinds.has("VARIABLE")) {
    guidance.push("상태값 또는 데이터 사용 방식이 바뀌었습니다. global/static 상호작용과 테스트 반영 여부를 검토하세요.");
  }
  if (guidance.length === 0) {
    guidance.push("변경된 함수를 기준으로 현재 구현과 테스트 명세의 의도가 사양과 일치하는지 검토하세요.");
  }
  return guidance;
};

const buildUdsGuidance = (changeDetail) => {
  const changedRows = Array.isArray(changeDetail?.documents?.uds?.changed_functions)
    ? changeDetail.documents.uds.changed_functions
    : [];
  if (changedRows.length === 0) {
    return ["UDS 구조 diff가 기록되지 않았습니다. 변경 함수와 연결된 설계 설명, 입력/출력, 호출 관계를 직접 확인하세요."];
  }
  const fieldSet = new Set(changedRows.flatMap((row) => Array.isArray(row?.fields_changed) ? row.fields_changed : []));
  const lines = [];
  if (fieldSet.has("description")) lines.push("함수 설명이 변경되었습니다. 요구사항 문장과 구현 의도가 여전히 일치하는지 확인하세요.");
  if (fieldSet.has("inputs") || fieldSet.has("outputs")) lines.push("입력/출력 항목이 변경되었습니다. 인터페이스와 테스트 정의를 함께 검토하세요.");
  if (fieldSet.has("calls") || fieldSet.has("globals")) lines.push("호출 관계 또는 global/static 사용이 변경되었습니다. 부작용과 연계 함수 추적 관계를 확인하세요.");
  if (fieldSet.has("related") || fieldSet.has("asil")) lines.push("추적성 또는 안전 등급 정보가 변경되었습니다. 관련 문서 링크와 연결 요구사항을 확인하세요.");
  if (lines.length === 0) lines.push("변경 필드 목록을 기준으로 UDS 섹션이 현재 구현과 맞는지 검토하세요.");
  return lines;
};

const buildSutsGuidance = (changeDetail) => {
  const summary = changeDetail?.documents?.suts?.summary || {};
  const lines = [];
  if (Number(summary.changed_functions || 0) > 0) lines.push(`영향 함수 ${summary.changed_functions}개를 기준으로 테스트케이스가 재생성되었습니다. 함수별 테스트 의도를 먼저 검토하세요.`);
  if (Number(summary.changed_cases || 0) > 0 || Number(summary.changed_sequences || 0) > 0) {
    lines.push("변경된 testcase/sequence의 입력값과 기대값이 현재 구현 로직과 일치하는지 확인하세요.");
  }
  lines.push("재생성된 함수의 기존 테스트 이름, 요구사항 연결, expected 데이터 누락 여부를 함께 확인하는 것이 좋습니다.");
  return lines;
};

const buildSdsGuidance = (changeDetail) => {
  const kinds = new Set(Object.values(changeDetail?.changed_functions || {}).map((kind) => String(kind || "").toUpperCase()));
  const lines = [];
  if (kinds.has("HEADER") || kinds.has("SIGNATURE")) lines.push("인터페이스 변경이 포함되어 있습니다. 설계 구조, 모듈 경계, 인터페이스 설명을 우선 검토하세요.");
  if (kinds.has("BODY")) lines.push("동작 로직 변경이 포함되어 있습니다. 설계 설명과 실제 구현 로직이 어긋나지 않는지 확인하세요.");
  lines.push("SDS는 직접 자동 수정 대상이 아니라 review 대상입니다. 영향 모듈과 관련 함수 설명이 사양과 맞는지 검토하세요.");
  return lines;
};

const buildSitsGuidance = (overviewDetail) => {
  const changedFiles = Array.isArray(overviewDetail?.changed_files) ? overviewDetail.changed_files.length : 0;
  const changedFunctions = overviewDetail?.changed_functions && typeof overviewDetail.changed_functions === "object"
    ? Object.keys(overviewDetail.changed_functions).length
    : 0;
  return [
    `현재 최신 run 기준 변경 파일 ${changedFiles}개, 변경 함수 ${changedFunctions}개가 감지되어 있습니다.`,
    "SITS 기능이 추가되면 이 영역에서 테스트 실행 영향 요약, 생성 결과, review 사유를 같은 방식으로 보여줄 예정입니다.",
    "지금은 상단 Code Change Overview와 Impact 결과를 기준으로 SITS 연결 대상 함수를 먼저 검토하면 됩니다.",
  ];
};

const getStsGuidanceKo = (changeDetail) => {
  const entries = changeDetail?.changed_functions && typeof changeDetail.changed_functions === "object"
    ? Object.entries(changeDetail.changed_functions)
    : [];
  if (entries.length === 0) return [];

  const guidance = [];
  const kinds = new Set(entries.map(([, kind]) => String(kind || "").toUpperCase()));

  if (kinds.has("HEADER") || kinds.has("SIGNATURE")) {
    guidance.push("인터페이스가 변경되었습니다. 요구사항 연결, 입력/출력 조건, STS 테스트 명세 추적 관계를 우선 검토하세요.");
    guidance.push("입출력 값과 호출 조건, 연계 모듈 계약이 함께 바뀌었는지 확인하는 것이 좋습니다.");
  }
  if (kinds.has("BODY")) {
    guidance.push("동작 로직이 변경되었습니다. 기대 결과, 분기 커버리지, 예외 처리 assertion을 다시 검토하세요.");
  }
  if (kinds.has("VARIABLE")) {
    guidance.push("상태값 또는 데이터 사용 방식이 바뀌었습니다. global/static 상호작용과 테스트 반영 여부를 확인하세요.");
  }
  if (guidance.length === 0) {
    guidance.push("변경된 함수를 기준으로 현재 구현과 테스트 문서가 사양과 일치하는지 검토하세요.");
  }
  return guidance;
};

const getUdsGuidanceKo = (changeDetail) => {
  const changedRows = Array.isArray(changeDetail?.documents?.uds?.changed_functions)
    ? changeDetail.documents.uds.changed_functions
    : [];
  if (changedRows.length === 0) {
    return ["UDS 구조 diff가 기록되지 않았습니다. 변경 함수와 연결된 설계 설명, 입력/출력, 호출 관계를 직접 확인하세요."];
  }
  const fieldSet = new Set(changedRows.flatMap((row) => Array.isArray(row?.fields_changed) ? row.fields_changed : []));
  const lines = [];
  if (fieldSet.has("description")) lines.push("함수 설명이 변경되었습니다. 요구사항 문장과 구현 의도가 새로 맞는지 확인하세요.");
  if (fieldSet.has("inputs") || fieldSet.has("outputs")) lines.push("입력/출력 항목이 변경되었습니다. 인터페이스와 테스트 정의를 함께 검토하세요.");
  if (fieldSet.has("calls") || fieldSet.has("globals")) lines.push("호출 관계 또는 global/static 사용이 변경되었습니다. 부작용과 연계 함수 추적 관계를 확인하세요.");
  if (fieldSet.has("related") || fieldSet.has("asil")) lines.push("추적성 또는 안전 등급 정보가 변경되었습니다. 관련 문서 링크와 연결 요구사항을 확인하세요.");
  if (lines.length === 0) lines.push("변경 필드 목록을 기준으로 UDS 섹션이 현재 구현과 맞는지 검토하세요.");
  return lines;
};

const getSutsGuidanceKo = (changeDetail) => {
  const summary = changeDetail?.documents?.suts?.summary || {};
  const lines = [];
  if (Number(summary.changed_functions || 0) > 0) {
    lines.push(`영향 함수 ${summary.changed_functions}개를 기준으로 테스트케이스가 재생성되었습니다. 함수별 테스트 의도를 먼저 검토하세요.`);
  }
  if (Number(summary.changed_cases || 0) > 0 || Number(summary.changed_sequences || 0) > 0) {
    lines.push("변경된 testcase/sequence의 입력값과 기대값이 현재 구현 로직과 일치하는지 확인하세요.");
  }
  lines.push("재생성된 함수의 기존 테스트 이름, 요구사항 연결, expected 데이터 누락 여부를 함께 확인하는 것이 좋습니다.");
  return lines;
};

const getSdsGuidanceKo = (changeDetail) => {
  const kinds = new Set(Object.values(changeDetail?.changed_functions || {}).map((kind) => String(kind || "").toUpperCase()));
  const lines = [];
  if (kinds.has("HEADER") || kinds.has("SIGNATURE")) {
    lines.push("인터페이스 변경이 포함되어 있습니다. 설계 구조, 모듈 경계, 인터페이스 설명을 우선 검토하세요.");
  }
  if (kinds.has("BODY")) {
    lines.push("동작 로직 변경이 포함되어 있습니다. 설계 설명과 실제 구현 로직이 어긋나지 않는지 확인하세요.");
  }
  lines.push("SDS는 직접 자동 수정 대상이 아니라 review 대상입니다. 영향 모듈과 관련 함수 설명이 사양과 맞는지 검토하세요.");
  return lines;
};

const getSdsReviewCategoriesKo = (changeDetail) => {
  const kinds = new Set(Object.values(changeDetail?.changed_functions || {}).map((kind) => String(kind || "").toUpperCase()));
  const categories = [];
  if (kinds.has("HEADER") || kinds.has("SIGNATURE")) categories.push("인터페이스 검토");
  if (kinds.has("BODY")) categories.push("설계 일치성 검토");
  if (kinds.has("VARIABLE")) categories.push("상태/데이터 검토");
  if (categories.length === 0 && Number(changeDetail?.summary?.sds_flagged || 0) > 0) categories.push("일반 리뷰");
  return categories;
};

const getStsReviewCategoriesKo = (changeDetail) => {
  const kinds = new Set(Object.values(changeDetail?.changed_functions || {}).map((kind) => String(kind || "").toUpperCase()));
  const categories = [];
  if (kinds.has("HEADER") || kinds.has("SIGNATURE")) categories.push("인터페이스 검토");
  if (kinds.has("BODY")) categories.push("테스트 의도/설계 일치 검토");
  if (kinds.has("VARIABLE")) categories.push("상태/데이터 검토");
  if (categories.length === 0 && Number(changeDetail?.summary?.sts_flagged || 0) > 0) categories.push("일반 STS 리뷰");
  return categories;
};

const getSutsReviewCategoriesKo = (changeDetail) => {
  const kinds = new Set(Object.values(changeDetail?.changed_functions || {}).map((kind) => String(kind || "").toUpperCase()));
  const categories = [];
  if (kinds.has("HEADER") || kinds.has("SIGNATURE")) categories.push("입출력/인터페이스 재검토");
  if (kinds.has("BODY")) categories.push("기대값/시퀀스 재검토");
  if (kinds.has("VARIABLE")) categories.push("상태 기반 테스트 재검토");
  if (categories.length === 0 && Number(changeDetail?.summary?.suts_changed_cases || 0) > 0) categories.push("일반 SUTS 재검토");
  return categories;
};

const pickPreferredSdsItemId = (items, focusKeyword = "") => {
  if (!Array.isArray(items) || items.length === 0) return "";
  const focusLower = String(focusKeyword || "").trim().toLowerCase();
  const scoreItem = (item) => {
    let score = 0;
    if (focusLower) {
      const values = [
        item?.title,
        item?.functionName,
        item?.moduleName,
        ...(Array.isArray(item?.relatedFunctions) ? item.relatedFunctions : []),
        ...(Array.isArray(item?.relatedModules) ? item.relatedModules : []),
      ]
        .map((value) => String(value || "").toLowerCase())
        .filter(Boolean);
      if (values.some((value) => value === focusLower)) score += 2000;
      else if (values.some((value) => value.includes(focusLower))) score += 1200;
    }
    if (item?.reviewRequired) score += 800;
    if (item?.changed) score += 400;
    score += Math.round(Number(item?.matchConfidence || 0) * 100);
    if (item?.kind === "function") score += 120;
    else if (item?.kind === "module") score += 80;
    else if (item?.kind === "section") score -= 40;
    const title = String(item?.title || "").trim().toLowerCase();
    if (title === "contents" || title === "table of contents") score -= 1000;
    if (title.includes("software component information")) score += 220;
    if (title.includes("software function list")) score += 180;
    if (title.includes("software interface")) score += 140;
    if (title.includes("evaluation of system architecture")) score += 120;
    if (title.includes("software state transition")) score += 100;
    if (title.includes("document overview")) score -= 200;
    if (title.includes("purpose") || title.includes("scope")) score -= 140;
    return score;
  };
  const picked = [...items].sort((a, b) => {
    const diff = scoreItem(b) - scoreItem(a);
    if (diff !== 0) return diff;
    return String(a?.title || "").localeCompare(String(b?.title || ""));
  })[0];
  return String(picked?.id || "");
};

const getPreferredSdsFocusFunction = (detail) => {
  const changedFunctionNames = Object.keys(detail?.changed_functions || {}).filter(Boolean);
  if (changedFunctionNames.length > 0) return String(changedFunctionNames[0]);
  const flaggedFunctions = Array.isArray(detail?.documents?.sds?.flagged_functions)
    ? detail.documents.sds.flagged_functions.filter(Boolean)
    : [];
  if (flaggedFunctions.length > 0) return String(flaggedFunctions[0]);
  return "";
};

const matchArtifactBlocks = (text, tokens, limit = 5) => {
  const normalizedTokens = (Array.isArray(tokens) ? tokens : [])
    .map((value) => String(value || "").trim())
    .filter(Boolean);
  if (!String(text || "").trim() || normalizedTokens.length === 0) return [];
  const blocks = String(text || "")
    .split(/\r?\n\s*\r?\n/)
    .map((block) => block.trim())
    .filter(Boolean);
  return blocks
    .map((block) => {
      const lower = block.toLowerCase();
      const matchedTokens = normalizedTokens.filter((token) => lower.includes(token.toLowerCase()));
      return {
        text: block,
        score: matchedTokens.length,
        matchedTokens,
      };
    })
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score || b.text.length - a.text.length)
    .slice(0, limit)
    .map((entry) => `[${entry.matchedTokens.join(", ")}] ${entry.text}`);
};

const getReviewCategoryHintsByKind = (kind, domain = "sts") => {
  const upper = String(kind || "").toUpperCase();
  const labels = [];
  if (upper === "HEADER" || upper === "SIGNATURE") {
    labels.push(domain === "suts" ? "입출력/인터페이스 재검토" : "인터페이스 검토");
  }
  if (upper === "BODY") {
    labels.push(domain === "suts" ? "기대값/시퀀스 재검토" : "테스트 의도/설계 일치 검토");
  }
  if (upper === "VARIABLE") {
    labels.push(domain === "suts" ? "상태 기반 테스트 재검토" : "상태/데이터 검토");
  }
  if (labels.length === 0) labels.push(domain === "suts" ? "일반 SUTS 재검토" : "일반 STS 리뷰");
  return labels;
};

const buildSutsCaseGroups = (changeDetail, artifactText, focusedChangeFunction) => {
  const changedFunctions = changeDetail?.changed_functions && typeof changeDetail.changed_functions === "object"
    ? changeDetail.changed_functions
    : {};
  const changedCases = Array.isArray(changeDetail?.documents?.suts?.changed_cases)
    ? changeDetail.documents.suts.changed_cases
    : [];
  const grouped = new Map();
  changedCases.forEach((row) => {
    const key = String(row?.function || "unknown");
    const current = grouped.get(key) || {
      functionName: key,
      changeType: changedFunctions[key] || "",
      cases: [],
    };
    current.cases.push(row);
    grouped.set(key, current);
  });
  return Array.from(grouped.values())
    .map((entry) => {
      const testcaseNames = Array.from(new Set(entry.cases.map((row) => String(row?.testcase || "").trim()).filter(Boolean)));
      return {
        ...entry,
        testcaseCount: testcaseNames.length,
        sequenceCount: entry.cases.length,
        artifactMatches: matchArtifactBlocks(
          artifactText,
          [entry.functionName, ...testcaseNames, focusedChangeFunction].filter(Boolean),
          2
        ),
        isFocused: Boolean(focusedChangeFunction && entry.functionName === focusedChangeFunction),
      };
    })
    .sort((a, b) => {
      const focusDelta = Number(b.isFocused) - Number(a.isFocused);
      if (focusDelta !== 0) return focusDelta;
      const seqDelta = b.sequenceCount - a.sequenceCount;
      if (seqDelta !== 0) return seqDelta;
      return String(a.functionName).localeCompare(String(b.functionName));
    });
};

const getSitsGuidanceKo = (changeDetail) => {
  const kinds = new Set(
    Object.values(changeDetail?.changed_functions || {}).map((k) => String(k || "").toUpperCase())
  );
  const sitsSummary = changeDetail?.documents?.sits?.summary || {};
  const deltaTC = Number(sitsSummary.delta_cases ?? 0);
  const deltaSub = Number(sitsSummary.delta_sub_cases ?? 0);
  const guidance = [];

  if (kinds.has("SIGNATURE") || kinds.has("HEADER")) {
    guidance.push("모듈 인터페이스가 변경되었습니다. call chain 진입점의 입력 파라미터, 반환값, 연계 모듈 계약을 먼저 확인하세요.");
  }
  if (kinds.has("BODY")) {
    guidance.push("통합 흐름 내 로직이 변경되었습니다. sub-case의 기대값과 경계 조건이 현재 구현과 일치하는지 검토하세요.");
  }
  if (kinds.has("VARIABLE")) {
    guidance.push("global/static 변수 사용 방식이 바뀌었습니다. 통합 테스트 Precondition과 상태 초기화 조건을 확인하세요.");
  }
  if (deltaTC !== 0) {
    guidance.push(`TC 수가 ${deltaTC >= 0 ? "+" : ""}${deltaTC}개 변동되었습니다. 새로 추가되거나 삭제된 call chain을 확인하세요.`);
  }
  if (deltaSub !== 0) {
    guidance.push(`Sub-case 수가 ${deltaSub >= 0 ? "+" : ""}${deltaSub}개 변동되었습니다. 경계값 커버리지를 재검토하세요.`);
  }
  if (guidance.length === 0) {
    guidance.push("변경된 함수가 포함된 call chain을 기준으로 통합 테스트 명세와 현재 구현이 일치하는지 검토하세요.");
  }
  return guidance;
};

const getSitsReviewCategoriesKo = (changeDetail) => {
  const kinds = new Set(
    Object.values(changeDetail?.changed_functions || {}).map((k) => String(k || "").toUpperCase())
  );
  const categories = [];
  if (kinds.has("SIGNATURE") || kinds.has("HEADER")) categories.push("인터페이스 변경 — call chain 재검토");
  if (kinds.has("BODY")) categories.push("로직 변경 — 기대값/경계값 재검토");
  if (kinds.has("VARIABLE")) categories.push("상태/데이터 변경 — Precondition 재검토");
  if (kinds.has("NEW")) categories.push("신규 함수 — 통합 흐름 추가 여부 확인");
  if (kinds.has("DELETE")) categories.push("함수 삭제 — TC 유효성 확인");
  if (categories.length === 0) categories.push("일반 SITS 재검토");
  return categories;
};

const SummaryCard = ({ item, onClick }) => (
  <button
    type="button"
    className="card"
    style={{ padding: 14, textAlign: "left", cursor: "pointer", width: "100%" }}
    onClick={onClick}
  >
    <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
      <strong>{item.title}</strong>
      <span className="hint">Latest</span>
    </div>
    <div className="hint" style={{ marginTop: 6 }}>{item.filename || "No file"}</div>
    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 8, marginTop: 10 }}>
      {item.primary.map((metric) => (
        <div key={metric.label} className="card" style={{ padding: 10 }}>
          <div className="hint">{metric.label}</div>
          <div style={{ fontWeight: 700 }}>{metric.value}{metric.unit || ""}</div>
        </div>
      ))}
    </div>
  </button>
);

const AnalyzerSectionToolbar = ({ title }) => (
  <div className="analyzer-section-toolbar">
    <strong>{title}</strong>
  </div>
);

const LatestRunCard = ({ items, onOpen, onPreviewReport, groupLabel }) => {
  const rows = Array.isArray(items) ? items : [];
  const [expanded, setExpanded] = useState(false);
  if (rows.length === 0) return null;
  return (
    <div className="card" style={{ padding: 14, marginBottom: 12 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <strong>Latest Run</strong>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <span className="hint">{groupLabel ? `${groupLabel} ? ` : ""}{rows.length} artifacts</span>
          <button type="button" className="btn-outline" onClick={() => setExpanded((value) => !value)}>
            {expanded ? "Hide Latest Run" : "Open Latest Run"}
          </button>
        </div>
      </div>
      {expanded ? (
        <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
          {rows.map((item) => (
            <div
              key={item.title}
              className="latest-run-entry"
              role="button"
              tabIndex={0}
              onClick={() => typeof onOpen === "function" && onOpen(String(item.title || "").toLowerCase())}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  if (typeof onOpen === "function") onOpen(String(item.title || "").toLowerCase());
                }
              }}
            >
              <div className="latest-run-main">
                <div style={{ minWidth: 0 }} className="latest-run-content">
                  <div style={{ fontWeight: 600 }}>{item.title}</div>
                  <div className="hint" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {item.filename || "No file"}
                  </div>
                  {item.generatedAt ? <div className="hint">{item.generatedAt}</div> : null}
                  {item.buildLabel ? <div className="hint">{item.buildLabel}</div> : null}
                  <div className="latest-run-metrics-grid">
                    {item.primary.map((metric) => (
                      <div key={`${item.title}-${metric.label}`} className="latest-run-metric-chip">
                        <div className="hint">{metric.label}</div>
                        <div style={{ fontWeight: 700 }}>{metric.value}{metric.unit || ""}</div>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="latest-run-actions">
                  {item.downloadUrl ? (
                    <a
                      href={item.downloadUrl}
                      target="_blank"
                      rel="noreferrer"
                      className="btn-outline"
                      onClick={(e) => e.stopPropagation()}
                    >
                      Download
                    </a>
                  ) : null}
                  {item.validationReportPath ? (
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (typeof onPreviewReport === "function") onPreviewReport(item.validationReportPath, `${item.title} Validation`);
                      }}
                    >
                      Validation
                    </button>
                  ) : null}
                  <span className="badge">{item?.validation?.valid ? "PASS" : "CHECK"}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
};

const _CHANGE_TYPE_KO = { SIGNATURE: "인터페이스 변경", BODY: "로직 변경", NEW: "신규 추가", DELETE: "삭제", VARIABLE: "변수 변경", HEADER: "헤더 변경" };
const _DOC_STATUS_STYLE = {
  completed:  { color: "#22c55e", label: "자동 재생성 완료" },
  auto:       { color: "#22c55e", label: "자동 재생성 완료" },
  flagged:    { color: "#f59e0b", label: "검토 필요" },
  flag:       { color: "#f59e0b", label: "검토 필요" },
  skipped:    { color: "#94a3b8", label: "변경 없음" },
  error:      { color: "#ef4444", label: "오류" },
};
const _statusStyle = (s) => _DOC_STATUS_STYLE[String(s || "").toLowerCase()] || { color: "#94a3b8", label: String(s || "-") };

const _ImpactDocRow = ({ docKey, doc, open, onToggle }) => {
  const st = _statusStyle(doc?.status);
  const summary = doc?.summary || {};
  const fns = Array.isArray(doc?.flagged_functions) ? doc.flagged_functions
    : Array.isArray(doc?.changed_functions) ? doc.changed_functions.map((f) => f?.function || f?.name || String(f))
    : Array.isArray(doc?.changed_cases) ? doc.changed_cases.map((f) => f?.function || String(f))
    : [];
  const hasDetail = fns.length > 0;

  const metaItems = [];
  if (docKey === "uds") {
    if (summary.changed_functions) metaItems.push(`${summary.changed_functions}개 함수 재생성`);
  } else if (docKey === "suts") {
    if (summary.changed_cases != null) metaItems.push(`TC ${summary.before_cases ?? "?"}→${summary.changed_cases}`);
    if (summary.changed_sequences != null) metaItems.push(`Seq ${summary.before_sequences ?? "?"}→${summary.changed_sequences}`);
  } else if (docKey === "sits") {
    if (summary.test_case_count != null) metaItems.push(`TC ${summary.before_test_case_count ?? "?"}→${summary.test_case_count}`);
    if (summary.delta_cases != null) metaItems.push(`Δ${summary.delta_cases >= 0 ? "+" : ""}${summary.delta_cases} TC`);
    if (summary.delta_sub_cases != null) metaItems.push(`Δ${summary.delta_sub_cases >= 0 ? "+" : ""}${summary.delta_sub_cases} Sub`);
  } else if (docKey === "sts" || docKey === "sds") {
    if (summary.flagged_functions) metaItems.push(`${summary.flagged_functions}개 함수 수동 검토 필요`);
  }

  return (
    <div style={{ borderBottom: "1px solid var(--border, #e2e8f0)" }}>
      <div
        className="row"
        style={{ padding: "8px 4px", gap: 10, alignItems: "center", cursor: hasDetail ? "pointer" : "default" }}
        onClick={hasDetail ? onToggle : undefined}
      >
        <span style={{ fontWeight: 700, width: 48, textTransform: "uppercase", color: "var(--text)", fontSize: "0.85em" }}>{docKey}</span>
        <span style={{ width: 8, height: 8, borderRadius: "50%", background: st.color, flexShrink: 0 }} />
        <span style={{ color: st.color, fontSize: "0.82em", fontWeight: 600, minWidth: 110 }}>{st.label}</span>
        <span className="hint" style={{ flex: 1, fontSize: "0.82em" }}>{metaItems.join("  ·  ") || "-"}</span>
        {hasDetail ? <span className="hint" style={{ fontSize: "0.78em" }}>{open ? "▲" : "▼"} {fns.length}개</span> : null}
      </div>
      {open && hasDetail ? (
        <div style={{ padding: "4px 8px 10px 60px" }}>
          <div style={{ fontSize: "0.8em", color: "var(--text-muted, #64748b)", marginBottom: 4 }}>
            {docKey === "sts" || docKey === "sds" ? "검토 필요 함수" : "변경 함수"}
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {fns.slice(0, 40).map((fn, i) => (
              <span key={i} style={{ fontSize: "0.78em", background: "var(--card-bg, #f1f5f9)", border: "1px solid var(--border, #e2e8f0)", borderRadius: 4, padding: "1px 6px", fontFamily: "monospace" }}>
                {String(fn)}
              </span>
            ))}
            {fns.length > 40 ? <span className="hint" style={{ fontSize: "0.78em" }}>+{fns.length - 40}개 더</span> : null}
          </div>
        </div>
      ) : null}
    </div>
  );
};

const ImpactResultCard = ({ result }) => {
  const [openDoc, setOpenDoc] = useState(null);
  const changedFiles = Array.isArray(result?.changed_files) ? result.changed_files : [];
  const changedFunctions = result?.changed_functions && typeof result.changed_functions === "object"
    ? Object.entries(result.changed_functions) : [];
  const counts = result?.impact_counts || {};
  const docs = result?.documents && typeof result.documents === "object" ? result.documents : {};
  const warnings = Array.isArray(result?.warnings) ? result.warnings : [];
  const DOC_ORDER = ["uds", "suts", "sits", "sts", "sds"];

  return (
    <div className="card" style={{ padding: 14, marginTop: 12 }}>
      {/* 헤더 */}
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
        <strong>Impact 결과</strong>
        <div className="row" style={{ gap: 8 }}>
          <span className="badge">파일 {changedFiles.length}</span>
          <span className="badge">함수 {changedFunctions.length}</span>
          {counts.direct != null ? <span className="badge">직접 {counts.direct} / 1hop {counts.indirect_1hop || 0} / 2hop {counts.indirect_2hop || 0}</span> : null}
        </div>
      </div>

      {/* 변경 함수 목록 */}
      {changedFunctions.length > 0 ? (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: "0.82em", fontWeight: 600, marginBottom: 6, color: "var(--text-muted, #64748b)" }}>변경된 함수</div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {changedFunctions.map(([name, type]) => (
              <span key={name} style={{ fontSize: "0.78em", background: "var(--card-bg, #f1f5f9)", border: "1px solid var(--border, #e2e8f0)", borderRadius: 4, padding: "2px 7px", fontFamily: "monospace" }}>
                {name}
                <span className="hint" style={{ marginLeft: 4, fontSize: "0.9em" }}>{_CHANGE_TYPE_KO[String(type).toUpperCase()] || type}</span>
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {/* 문서별 영향 */}
      {DOC_ORDER.some((k) => docs[k]) ? (
        <div style={{ border: "1px solid var(--border, #e2e8f0)", borderRadius: 6, overflow: "hidden" }}>
          <div style={{ padding: "6px 8px", background: "var(--card-bg, #f8fafc)", fontSize: "0.8em", fontWeight: 600, color: "var(--text-muted, #64748b)", borderBottom: "1px solid var(--border, #e2e8f0)" }}>
            문서별 영향
          </div>
          {DOC_ORDER.map((k) => docs[k] ? (
            <_ImpactDocRow
              key={k}
              docKey={k}
              doc={docs[k]}
              open={openDoc === k}
              onToggle={() => setOpenDoc((prev) => prev === k ? null : k)}
            />
          ) : null)}
        </div>
      ) : null}

      {/* 경고 */}
      {warnings.length > 0 ? (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontWeight: 600, fontSize: "0.82em", marginBottom: 4 }}>경고</div>
          <div className="card" style={{ padding: 8, maxHeight: 120, overflow: "auto", fontSize: "0.8em", whiteSpace: "pre-wrap" }}>
            {warnings.join("\n")}
          </div>
        </div>
      ) : null}
    </div>
  );
};

const JenkinsImpactPanel = ({
  jenkinsJobUrl = "",
  setJenkinsJobUrl,
  jenkinsCacheRoot = "",
  setJenkinsCacheRoot,
  jenkinsBuildSelector = "",
  setJenkinsBuildSelector,
}) => {
  const [registryItems, setRegistryItems] = useState([]);
  const [registryLoading, setRegistryLoading] = useState(false);
  const [registryError, setRegistryError] = useState("");
  const [scmId, setScmId] = useState("");
  const [buildNumber, setBuildNumber] = useState("");
  const [baseRef, setBaseRef] = useState("");
  const [targets, setTargets] = useState(["uds", "suts", "sits", "sts", "sds"]);
  const [jobState, setJobState] = useState(null);
  const [impactResult, setImpactResult] = useState(null);
  const [impactError, setImpactError] = useState("");
  const [auditItems, setAuditItems] = useState([]);
  const [auditLoading, setAuditLoading] = useState(false);

  const loadRegistries = useCallback(async () => {
    setRegistryLoading(true);
    setRegistryError("");
    try {
      const data = await fetchJson("/api/scm/list", { timeoutMs: 30000 });
      const rows = Array.isArray(data?.items) ? data.items : [];
      setRegistryItems(rows);
      setScmId((prev) => prev || String(rows[0]?.id || ""));
    } catch (err) {
      setRegistryItems([]);
      setRegistryError(err?.message || String(err));
    } finally {
      setRegistryLoading(false);
    }
  }, []);

  const loadAudit = useCallback(async (entryId) => {
    if (!String(entryId || "").trim()) {
      setAuditItems([]);
      return;
    }
    setAuditLoading(true);
    try {
      const data = await fetchJson(`/api/scm/audit/${encodeURIComponent(entryId)}?limit=10`, { timeoutMs: 30000 });
      setAuditItems(Array.isArray(data?.items) ? data.items : []);
    } catch {
      setAuditItems([]);
    } finally {
      setAuditLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRegistries();
  }, [loadRegistries]);

  useEffect(() => {
    loadAudit(scmId);
  }, [loadAudit, scmId]);

  const toggleTarget = (target) => {
    setTargets((prev) => (prev.includes(target) ? prev.filter((item) => item !== target) : [...prev, target]));
  };

  const startImpact = useCallback(async (dryRun) => {
    if (!String(scmId || "").trim()) {
      setImpactError("SCM registry selection is required.");
      return;
    }
    if (!String(jenkinsJobUrl || "").trim()) {
      setImpactError("Jenkins job URL is required.");
      return;
    }
    setImpactError("");
    setImpactResult(null);
    setJobState({ status: "queued", stage: "prepare", message: "Starting impact job..." });
    try {
      const launch = await fetchJson("/api/jenkins/impact/trigger-async", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scm_id: scmId,
          build_number: Number(buildNumber || 0),
          job_url: jenkinsJobUrl,
          base_ref: baseRef,
          dry_run: Boolean(dryRun),
          targets,
        }),
        timeoutMs: 30000,
      });
      const jobId = String(launch?.job_id || "").trim();
      if (!jobId) throw new Error("impact job id missing");
      while (true) {
        await new Promise((resolve) => setTimeout(resolve, 2500));
        const statusData = await fetchJson(`/api/scm/impact-job/${encodeURIComponent(jobId)}`, { timeoutMs: 30000 });
        const job = statusData?.job || {};
        setJobState(job);
        if (job?.status === "completed") {
          const resultData = await fetchJson(`/api/scm/impact-job/${encodeURIComponent(jobId)}/result`, { timeoutMs: 30000 });
          setImpactResult(resultData?.result || {});
          await loadAudit(scmId);
          break;
        }
        if (job?.status === "failed") {
          const title = String(job?.error?.title || job?.error?.code || "Impact job failed");
          const detail = String(job?.error?.detail || "");
          throw new Error([title, detail].filter(Boolean).join(": "));
        }
      }
    } catch (err) {
      setImpactError(err?.message || String(err));
    }
  }, [baseRef, buildNumber, jenkinsJobUrl, loadAudit, scmId, targets]);

  return (
    <div className="card" style={{ padding: 14 }}>
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        <strong>Analyzer Impact (Jenkins)</strong>
        <button type="button" className="btn-outline" onClick={loadRegistries} disabled={registryLoading}>
          {registryLoading ? "Loading..." : "Refresh Registry"}
        </button>
      </div>
      <div className="hint" style={{ marginTop: 6 }}>
        Jenkins build context를 기준으로 변경 영향 분석과 문서 갱신을 실행합니다. UDS, STS, SUTS도 같은 Jenkins 컨텍스트를 그대로 사용합니다.
      </div>
      <div className="form-grid-2 compact" style={{ marginTop: 12 }}>
        <label>SCM Registry</label>
        <select value={scmId} onChange={(e) => setScmId(e.target.value)}>
          <option value="">Select registry</option>
          {registryItems.map((item) => (
            <option key={item.id} value={item.id}>{item.name || item.id}</option>
          ))}
        </select>
        <label>Jenkins Job URL</label>
        <input value={jenkinsJobUrl || ""} onChange={(e) => typeof setJenkinsJobUrl === "function" && setJenkinsJobUrl(e.target.value)} />
        <label>Cache Root</label>
        <input value={jenkinsCacheRoot || ""} onChange={(e) => typeof setJenkinsCacheRoot === "function" && setJenkinsCacheRoot(e.target.value)} />
        <label>Build Selector</label>
        <input value={jenkinsBuildSelector || ""} onChange={(e) => typeof setJenkinsBuildSelector === "function" && setJenkinsBuildSelector(e.target.value)} />
        <label>Build Number</label>
        <input value={buildNumber} onChange={(e) => setBuildNumber(e.target.value)} placeholder="0 = latest context" />
        <label>Base Ref</label>
        <input value={baseRef} onChange={(e) => setBaseRef(e.target.value)} placeholder="optional" />
      </div>
      <div className="row" style={{ gap: 8, flexWrap: "wrap", marginTop: 12 }}>
        {IMPACT_TARGETS.map((target) => (
          <label key={target} className="row" style={{ gap: 6 }}>
            <input type="checkbox" checked={targets.includes(target)} onChange={() => toggleTarget(target)} />
            {target.toUpperCase()}
          </label>
        ))}
      </div>
      <div className="row" style={{ gap: 8, marginTop: 12 }}>
        <button type="button" onClick={() => startImpact(true)}>Dry Run</button>
        <button type="button" onClick={() => startImpact(false)}>Run Impact</button>
      </div>
      {registryError ? <div className="error" style={{ marginTop: 8 }}>{registryError}</div> : null}
      {impactError ? <div className="error" style={{ marginTop: 8 }}>{impactError}</div> : null}
      {jobState ? (
        <div className="card" style={{ padding: 12, marginTop: 12 }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <strong>Job Status</strong>
            <span className="badge">{String(jobState?.status || "unknown").toUpperCase()}</span>
          </div>
          <div className="hint" style={{ marginTop: 6 }}>{jobState?.stage || "-"} {jobState?.message ? `| ${jobState.message}` : ""}</div>
          {jobState?.progress ? (
            <pre className="json" style={{ marginTop: 10 }}>{JSON.stringify(jobState.progress, null, 2)}</pre>
          ) : null}
        </div>
      ) : null}
      {impactResult ? <ImpactResultCard result={impactResult} /> : null}
      <div className="card" style={{ padding: 12, marginTop: 12 }}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <strong>Recent Jenkins Impact Runs</strong>
          <span className="hint">{auditLoading ? "Loading..." : `${auditItems.length} items`}</span>
        </div>
        <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
          {auditItems.map((item, index) => (
            <div key={`${item?.timestamp || index}`} className="card" style={{ padding: 10 }}>
              <div className="row" style={{ justifyContent: "space-between", gap: 12 }}>
                <strong>{item?.timestamp || "-"}</strong>
                <span className="hint">{String(item?.trigger || "").toUpperCase()}</span>
              </div>
              <div className="hint" style={{ marginTop: 6 }}>
                files {Array.isArray(item?.changed_files) ? item.changed_files.length : 0} / direct {Array.isArray(item?.impacted_functions?.direct) ? item.impacted_functions.direct.length : 0}
              </div>
            </div>
          ))}
          {!auditLoading && auditItems.length === 0 ? <div className="hint">No Jenkins impact runs found.</div> : null}
        </div>
      </div>
    </div>
  );
};

const UdsAnalyzerView = ({
  mode = "local",
  reportDir = "",
  jenkinsJobUrl = "",
  setJenkinsJobUrl,
  jenkinsCacheRoot = "",
  setJenkinsCacheRoot,
  jenkinsBuildSelector = "lastSuccessfulBuild",
  setJenkinsBuildSelector,
  sourceRoot = "",
  setSourceRoot,
  pickDirectory,
  pickFile,
  preferredArtifactType = "",
  scmMode,
  setScmMode,
  scmWorkdir,
  setScmWorkdir,
  scmRepoUrl,
  setScmRepoUrl,
  scmBranch,
  setScmBranch,
  scmDepth,
  setScmDepth,
  scmRevision,
  setScmRevision,
  runScm,
  scmOutput,
}) => {
  const [artifactType, setArtifactType] = useState("impact");
  const [fullscreenSection, setFullscreenSection] = useState("");
  const [udsDocMode, setUdsDocMode] = useState("current");
  const [stsDocMode, setStsDocMode] = useState("current");
  const [sutsDocMode, setSutsDocMode] = useState("current");
  const [sitsDocMode, setSitsDocMode] = useState("current");
  const [sdsDocMode, setSdsDocMode] = useState("current");
  const [docRegistryItems, setDocRegistryItems] = useState([]);
  const [docScmId, setDocScmId] = useState("");
  const [overviewHistoryItems, setOverviewHistoryItems] = useState([]);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const [overviewDetail, setOverviewDetail] = useState(null);
  const [udsChangeHistoryItems, setUdsChangeHistoryItems] = useState([]);
  const [udsChangeHistoryLoading, setUdsChangeHistoryLoading] = useState(false);
  const [udsSelectedRunId, setUdsSelectedRunId] = useState("");
  const [udsSelectedChangeDetail, setUdsSelectedChangeDetail] = useState(null);
  const [stsChangeHistoryItems, setStsChangeHistoryItems] = useState([]);
  const [stsChangeHistoryLoading, setStsChangeHistoryLoading] = useState(false);
  const [stsSelectedRunId, setStsSelectedRunId] = useState("");
  const [stsSelectedChangeDetail, setStsSelectedChangeDetail] = useState(null);
  const [stsArtifactText, setStsArtifactText] = useState("");
  const [stsArtifactLoading, setStsArtifactLoading] = useState(false);
  const [sutsChangeHistoryItems, setSutsChangeHistoryItems] = useState([]);
  const [sutsChangeHistoryLoading, setSutsChangeHistoryLoading] = useState(false);
  const [sutsSelectedRunId, setSutsSelectedRunId] = useState("");
  const [sutsSelectedChangeDetail, setSutsSelectedChangeDetail] = useState(null);
  const [sutsArtifactText, setSutsArtifactText] = useState("");
  const [sutsArtifactLoading, setSutsArtifactLoading] = useState(false);
  const [sitsChangeHistoryItems, setSitsChangeHistoryItems] = useState([]);
  const [sitsChangeHistoryLoading, setSitsChangeHistoryLoading] = useState(false);
  const [sitsSelectedRunId, setSitsSelectedRunId] = useState("");
  const [sitsSelectedChangeDetail, setSitsSelectedChangeDetail] = useState(null);
  const [sdsChangeHistoryItems, setSdsChangeHistoryItems] = useState([]);
  const [sdsChangeHistoryLoading, setSdsChangeHistoryLoading] = useState(false);
  const [sdsSelectedRunId, setSdsSelectedRunId] = useState("");
  const [sdsSelectedChangeDetail, setSdsSelectedChangeDetail] = useState(null);
  const [sdsCurrentView, setSdsCurrentView] = useState({ path: "", items: [], counts: {}, loading: false, error: "" });
  const [sdsPlannedView, setSdsPlannedView] = useState({ path: "", items: [], counts: {}, loading: false, error: "" });
  const [sdsAppliedView, setSdsAppliedView] = useState({ path: "", items: [], counts: {}, loading: false, error: "" });
  const [sdsSelectedItemId, setSdsSelectedItemId] = useState("");
  const [sdsQuery, setSdsQuery] = useState("");
  const [sdsChangedOnly, setSdsChangedOnly] = useState(false);
  const [sdsItemHistory, setSdsItemHistory] = useState([]);
  const [sdsItemHistoryLoading, setSdsItemHistoryLoading] = useState(false);
  const [sdsModuleHistory, setSdsModuleHistory] = useState([]);
  const [sdsModuleHistoryLoading, setSdsModuleHistoryLoading] = useState(false);
  const [sdsArtifactText, setSdsArtifactText] = useState("");
  const [sdsArtifactLoading, setSdsArtifactLoading] = useState(false);
  const [focusedChangeFunction, setFocusedChangeFunction] = useState("");
  const udsAppliedDiffRef = useRef(null);
  const stsAppliedReviewRef = useRef(null);
  const sutsAppliedDiffRef = useRef(null);
  const sdsAppliedReviewRef = useRef(null);

  useEffect(() => {
    if (!fullscreenSection) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") setFullscreenSection("");
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [fullscreenSection]);
  const [sourceType, setSourceType] = useState(mode === "jenkins" ? "jenkins" : "local");
  const [files, setFiles] = useState([]);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesError, setFilesError] = useState("");
  const [selectedFilename, setSelectedFilename] = useState("");
  const [selectedDocxPath, setSelectedDocxPath] = useState("");
  const [viewData, setViewData] = useState(null);
  const [viewLoading, setViewLoading] = useState(false);
  const [viewError, setViewError] = useState("");
  const [genSrsDoc, setGenSrsDoc] = useState(null);
  const [genSdsDoc, setGenSdsDoc] = useState(null);
  const [genRefUdsDoc, setGenRefUdsDoc] = useState(null);
  const [genTemplateDoc, setGenTemplateDoc] = useState(null);
  const [genTestMode, setGenTestMode] = useState(false);
  const [genShowMappingEvidence, setGenShowMappingEvidence] = useState(false);
  const [genShowAdvancedOverrides, setGenShowAdvancedOverrides] = useState(false);
  const [showUdsGeneratePanel, setShowUdsGeneratePanel] = useState(false);
  const [genLoading, setGenLoading] = useState(false);
  const [genNotice, setGenNotice] = useState("");
  const [genQualityGate, setGenQualityGate] = useState(null);
  const [opProgress, setOpProgress] = useState(0);
  const [opStep, setOpStep] = useState("Idle");
  const [opLogs, setOpLogs] = useState([]);
  const [summaryCards, setSummaryCards] = useState([]);
  const [showGlobalContext, setShowGlobalContext] = useState(false);
  const [showQaChecklist, setShowQaChecklist] = useState(false);
  const [reportPreview, setReportPreview] = useState({ title: "", path: "", text: "", loading: false, error: "" });
  const [commonSrsPath, setCommonSrsPath] = useState("");
  const [commonSdsPath, setCommonSdsPath] = useState("");
  const [commonHsisPath, setCommonHsisPath] = useState("");
  const [commonUdsPath, setCommonUdsPath] = useState("");

  // STS lifted state
  const [stsSourceRoot, setStsSourceRoot] = useState(sourceRoot || "");
  const [stsSrsPath, setStsSrsPath] = useState("");
  const [stsSdsPath, setStsSdsPath] = useState("");
  const [stsHsisPath, setStsHsisPath] = useState("");
  const [stsUdsPath, setStsUdsPath] = useState("");
  const [stsStpPath, setStsStpPath] = useState("");
  const [stsTemplatePath, setStsTemplatePath] = useState("");
  const [stsProjectId, setStsProjectId] = useState("HDPDM01");
  const [stsVersion, setStsVersion] = useState("v1.00");
  const [stsAsilLevel, setStsAsilLevel] = useState("ASIL-B");
  const [stsMaxTc, setStsMaxTc] = useState(5);
  const [stsLoading, setStsLoading] = useState(false);
  const [stsNotice, setStsNotice] = useState("");
  const [stsProgressPct, setStsProgressPct] = useState(0);
  const [stsProgressMsg, setStsProgressMsg] = useState("");
  const [stsFiles, setStsFiles] = useState([]);
  const [stsFilesLoading, setStsFilesLoading] = useState(false);
  const [stsViewData, setStsViewData] = useState(null);
  const [stsPreviewData, setStsPreviewData] = useState(null);
  const [stsPreviewLoading, setStsPreviewLoading] = useState(false);
  const [stsPreviewSheet, setStsPreviewSheet] = useState(0);
  const [showStsGeneratePanel, setShowStsGeneratePanel] = useState(true);

  // SUTS lifted state
  const [sutsSourceRoot, setSutsSourceRoot] = useState(sourceRoot || "");
  const [sutsSrsPath, setSutsSrsPath] = useState("");
  const [sutsSdsPath, setSutsSdsPath] = useState("");
  const [sutsHsisPath, setSutsHsisPath] = useState("");
  const [sutsUdsPath, setSutsUdsPath] = useState("");
  const [sutsTemplatePath, setSutsTemplatePath] = useState("");
  const [sutsProjectId, setSutsProjectId] = useState("HDPDM01");
  const [sutsVersion, setSutsVersion] = useState("v1.00");
  const [sutsAsilLevel, setSutsAsilLevel] = useState("ASIL-B");
  const [sutsMaxSeq, setSutsMaxSeq] = useState(6);
  const [sutsLoading, setSutsLoading] = useState(false);
  const [sutsNotice, setSutsNotice] = useState("");
  const [sutsProgressPct, setSutsProgressPct] = useState(0);
  const [sutsProgressMsg, setSutsProgressMsg] = useState("");
  const [sutsFiles, setSutsFiles] = useState([]);
  const [sutsFilesLoading, setSutsFilesLoading] = useState(false);
  const [sutsViewData, setSutsViewData] = useState(null);
  const [sutsPreviewData, setSutsPreviewData] = useState(null);
  const [sutsPreviewLoading, setSutsPreviewLoading] = useState(false);
  const [sutsPreviewSheet, setSutsPreviewSheet] = useState(0);
  const [showSutsGeneratePanel, setShowSutsGeneratePanel] = useState(true);

  // SITS lifted state
  const [sitsSourceRoot, setSitsSourceRoot] = useState(sourceRoot || "");
  const [sitsSrsPath, setSitsSrsPath] = useState("");
  const [sitsSdsPath, setSitsSdsPath] = useState("");
  const [sitsHsisPath, setSitsHsisPath] = useState("");
  const [sitsUdsPath, setSitsUdsPath] = useState("");
  const [sitsStpPath, setSitsStpPath] = useState("");
  const [sitsTemplatePath, setSitsTemplatePath] = useState("");
  const [sitsProjectId, setSitsProjectId] = useState("HDPDM01");
  const [sitsVersion, setSitsVersion] = useState("v1.00");
  const [sitsAsilLevel, setSitsAsilLevel] = useState("ASIL-B");
  const [sitsMaxSubcases, setSitsMaxSubcases] = useState(7);
  const [sitsLoading, setSitsLoading] = useState(false);
  const [sitsNotice, setSitsNotice] = useState("");
  const [sitsProgressPct, setSitsProgressPct] = useState(0);
  const [sitsProgressMsg, setSitsProgressMsg] = useState("");
  const [sitsFiles, setSitsFiles] = useState([]);
  const [sitsFilesLoading, setSitsFilesLoading] = useState(false);
  const [sitsViewData, setSitsViewData] = useState(null);
  const [sitsPreviewData, setSitsPreviewData] = useState(null);
  const [sitsPreviewLoading, setSitsPreviewLoading] = useState(false);
  const [sitsPreviewSheet, setSitsPreviewSheet] = useState(0);
  const [showSitsGeneratePanel, setShowSitsGeneratePanel] = useState(true);

  const previewAbsReport = useCallback(async (path, title = "Validation Report") => {
    if (!path) return;
    setReportPreview({ title, path, text: "", loading: true, error: "" });
    try {
      const res = await fetch("/api/local/editor/read-abs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, max_bytes: 200000 }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setReportPreview({
        title,
        path,
        text: String(data?.text || ""),
        loading: false,
        error: data?.truncated ? "Report truncated for preview." : "",
      });
    } catch (err) {
      setReportPreview({
        title,
        path,
        text: "",
        loading: false,
        error: err?.message || String(err),
      });
    }
  }, []);

  const loadSdsViewTo = useCallback(async (setter, path, options = {}) => {
    if (!path) {
      setter({ path: "", items: [], counts: {}, loading: false, error: "SDS 경로가 설정되지 않았습니다." });
      return;
    }
    setter({ path, items: [], counts: {}, loading: true, error: "" });
    try {
      const res = await fetch("/api/local/sds/view", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path,
          max_items: 600,
          changed_functions: options?.changedFunctions || {},
          changed_files: options?.changedFiles || [],
          flagged_modules: options?.flaggedModules || [],
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setter({
        ...(data?.view || {}),
        path,
        loading: false,
        error: "",
      });
      const preferredId = pickPreferredSdsItemId(data?.view?.items, focusedChangeFunction);
      setSdsSelectedItemId((prev) => prev || preferredId);
    } catch (err) {
      setter({
        path,
        items: [],
        counts: {},
        loading: false,
        error: err?.message || String(err),
      });
    }
  }, [focusedChangeFunction]);

  const openLocalFile = useCallback(async (path) => {
    if (!path) return;
    await fetch("/api/local/open-file", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
  }, []);

  const pushOpLog = (text) => {
    const line = `[${new Date().toLocaleTimeString()}] ${String(text || "")}`;
    setOpLogs((prev) => [line, ...prev].slice(0, 10));
  };

  const isLocal = sourceType === "local";
  const currentSourceRoot = String(sourceRoot || "").trim();

  const loadFiles = async () => {
    setOpProgress(10);
    setOpStep("Loading file list");
    setFilesLoading(true);
    setFilesError("");
    try {
      if (isLocal) {
        const qs = new URLSearchParams();
        if (String(reportDir || "").trim()) qs.set("report_dir", String(reportDir).trim());
        const query = qs.toString() ? `?${qs.toString()}` : "";
        const data = await fetchJson(`/api/local/uds/files${query}`, { timeoutMs: 120000 });
        const rows = Array.isArray(data) ? data : [];
        setFiles(rows);
        setSelectedFilename((prev) => (prev ? prev : String(rows[0]?.filename || "")));
      } else {
        const qs = buildQuery({ job_url: jenkinsJobUrl, cache_root: jenkinsCacheRoot });
        const data = await fetchJson(`/api/jenkins/uds/list?${qs}`, { timeoutMs: 120000 });
        const rows = Array.isArray(data?.items) ? data.items : [];
        setFiles(rows);
        setSelectedFilename((prev) => (prev ? prev : String(rows[0]?.filename || "")));
      }
      setOpProgress(100);
      setOpStep("File list loaded");
    } catch (e) {
      setFiles([]);
      setFilesError(e?.message || String(e));
      setOpProgress(100);
      setOpStep(`File list failed: ${e?.message || String(e)}`);
    } finally {
      setFilesLoading(false);
    }
  };

  const loadView = async (filename, params = {}) => {
    const picked = String(filename || "").trim();
    if (!picked) return;
    setSelectedFilename(picked);
    setViewLoading(true);
    setViewError("");
    try {
      if (isLocal) {
        const rows = Array.isArray(files) ? files : [];
        const hit = rows.find((row) => String(row?.filename || row?.file || "").trim() === picked);
        const docxPath = String(hit?.path || "").trim() || String(selectedDocxPath || "").trim();
        const usePathMode = isAbsolutePath(docxPath);
        const qs = new URLSearchParams();
        Object.entries(params || {}).forEach(([k, v]) => {
          if (v === null || v === undefined || v === "") return;
          qs.set(k, String(v));
        });
        let data = null;
        if (usePathMode) {
          qs.set("docx_path", docxPath);
          data = await fetchJson(`/api/local/uds/view-by-path?${qs.toString()}`, { timeoutMs: 180000 });
          setSelectedDocxPath(docxPath);
        } else {
          if (String(reportDir || "").trim()) qs.set("report_dir", String(reportDir).trim());
          const query = qs.toString() ? `?${qs.toString()}` : "";
          data = await fetchJson(`/api/local/uds/view/${encodeURIComponent(picked)}${query}`, { timeoutMs: 180000 });
          setSelectedDocxPath("");
        }
        setViewData(data || null);
      } else {
        const qs = buildQuery({ job_url: jenkinsJobUrl, cache_root: jenkinsCacheRoot, filename: picked, ...params });
        const data = await fetchJson(`/api/jenkins/uds/view?${qs}`, { timeoutMs: 180000 });
        setViewData(data || null);
      }
      setOpProgress(100);
      setOpStep("Detail loaded");
    } catch (e) {
      setViewData(null);
      setViewError(e?.message || String(e));
    } finally {
      setViewLoading(false);
    }
  };

  useEffect(() => {
    setSourceType(mode === "jenkins" ? "jenkins" : "local");
  }, [mode]);

  useEffect(() => {
    const val = String(sourceRoot || "").trim();
    if (val) {
      setStsSourceRoot(val);
      setSutsSourceRoot(val);
    }
  }, [sourceRoot]);

  useEffect(() => {
    setStsSrsPath(commonSrsPath);
    setSutsSrsPath(commonSrsPath);
  }, [commonSrsPath]);

  useEffect(() => {
    setStsSdsPath(commonSdsPath);
    setSutsSdsPath(commonSdsPath);
  }, [commonSdsPath]);

  useEffect(() => {
    setStsHsisPath(commonHsisPath);
    setSutsHsisPath(commonHsisPath);
  }, [commonHsisPath]);

  useEffect(() => {
    setStsUdsPath(commonUdsPath);
    setSutsUdsPath(commonUdsPath);
  }, [commonUdsPath]);

  const isJenkins = mode === "jenkins";
  const stsApiBase = isJenkins ? "/api/jenkins/sts" : "/api/local/sts";
  const sutsApiBase = isJenkins ? "/api/jenkins/suts" : "/api/local/suts";
  const sitsApiBase = "/api/local/sits";

  const loadStsFiles = useCallback(async () => {
    setStsFilesLoading(true);
    try {
      let data;
      if (isJenkins) {
        const qs = buildQuery({ job_url: jenkinsJobUrl, cache_root: jenkinsCacheRoot });
        data = await fetchJson(`${stsApiBase}/list?${qs}`);
        setStsFiles(Array.isArray(data?.items) ? data.items : []);
      } else {
        data = await fetchJson(`${stsApiBase}/files`);
        setStsFiles(Array.isArray(data) ? data : []);
      }
    } catch (e) {
      setStsNotice(e.message || String(e));
      setStsFiles([]);
    } finally {
      setStsFilesLoading(false);
    }
  }, [isJenkins, jenkinsCacheRoot, jenkinsJobUrl, stsApiBase]);

  const loadStsView = useCallback(async (filename) => {
    if (!filename) return;
    try {
      let data;
      if (isJenkins) {
        const qs = buildQuery({ job_url: jenkinsJobUrl, cache_root: jenkinsCacheRoot, filename });
        data = await fetchJson(`${stsApiBase}/view?${qs}`);
      } else {
        data = await fetchJson(`${stsApiBase}/view/${encodeURIComponent(filename)}`);
      }
      setStsViewData(data || null);
    } catch (e) {
      setStsNotice(e.message || String(e));
    }
  }, [isJenkins, jenkinsCacheRoot, jenkinsJobUrl, stsApiBase]);

  const loadStsPreview = useCallback(async (filename, options = {}) => {
    if (!filename) return;
    const maxRows = Number(options?.maxRows || 30);
    setStsPreviewLoading(true);
    setStsPreviewData(null);
    setStsPreviewSheet(0);
    try {
      let data;
      if (isJenkins) {
        const qs = buildQuery({ job_url: jenkinsJobUrl, cache_root: jenkinsCacheRoot, filename, max_rows: maxRows });
        data = await fetchJson(`${stsApiBase}/preview?${qs}`);
      } else {
        data = await fetchJson(`${stsApiBase}/preview/${encodeURIComponent(filename)}?max_rows=${maxRows}`);
      }
      setStsPreviewData(data || null);
    } catch (e) {
      setStsNotice(e.message || String(e));
    } finally {
      setStsPreviewLoading(false);
    }
  }, [isJenkins, jenkinsCacheRoot, jenkinsJobUrl, stsApiBase]);

  const handleStsGenerate = useCallback(async () => {
    if (!String(stsSourceRoot || "").trim()) { setStsNotice("source root is required"); return; }
    if (!String(stsSrsPath || "").trim()) { setStsNotice("SRS path is required"); return; }
    setStsLoading(true);
    setStsNotice("");
    setStsProgressPct(0);
    setStsProgressMsg("Preparing...");
    try {
      const form = new FormData();
      form.append("source_root", stsSourceRoot.trim());
      form.append("srs_path", stsSrsPath.trim());
      if (stsSdsPath.trim()) form.append("sds_path", stsSdsPath.trim());
      if (stsUdsPath.trim()) form.append("uds_path", stsUdsPath.trim());
      if (stsStpPath.trim()) form.append("stp_path", stsStpPath.trim());
      if (stsTemplatePath.trim()) form.append("template_path", stsTemplatePath.trim());
      form.append("project_id", stsProjectId);
      form.append("version", stsVersion);
      form.append("asil_level", stsAsilLevel);
      form.append("max_tc_per_req", String(stsMaxTc));
      if (isJenkins) {
        form.append("job_url", jenkinsJobUrl);
        form.append("cache_root", jenkinsCacheRoot);
        form.append("build_selector", jenkinsBuildSelector);
      }
      const launch = await fetchJson(`${stsApiBase}/generate-async`, { method: "POST", body: form });
      const jobId = launch?.job_id;
      if (!jobId) throw new Error("job id missing");
      while (true) {
        await new Promise((r) => setTimeout(r, 3000));
        const qs = isJenkins
          ? buildQuery({ job_url: jenkinsJobUrl, build_selector: jenkinsBuildSelector, job_id: jobId })
          : buildQuery({ job_id: jobId });
        const pr = await fetchJson(`${stsApiBase}/progress?${qs}`);
        const progress = pr?.progress || {};
        setStsProgressPct(progress.percent || 0);
        setStsProgressMsg(progress.message || "");
        if (progress.error) throw new Error(progress.error);
        if (progress.done) {
          const result = progress.result || null;
          setStsViewData(result);
          await loadStsFiles();
          if (result?.filename) await loadStsPreview(result.filename);
          break;
        }
      }
      setStsNotice("STS generation completed");
    } catch (e) {
      setStsNotice(e.message || String(e));
    } finally {
      setStsLoading(false);
      setStsProgressPct(0);
      setStsProgressMsg("");
    }
  }, [isJenkins, jenkinsBuildSelector, jenkinsCacheRoot, jenkinsJobUrl, loadStsFiles, loadStsPreview, stsApiBase, stsAsilLevel, stsMaxTc, stsProjectId, stsSourceRoot, stsSrsPath, stsSdsPath, stsUdsPath, stsStpPath, stsTemplatePath, stsVersion]);

  const loadSutsFiles = useCallback(async () => {
    setSutsFilesLoading(true);
    try {
      let data;
      if (isJenkins) {
        const qs = buildQuery({ job_url: jenkinsJobUrl, cache_root: jenkinsCacheRoot });
        data = await fetchJson(`${sutsApiBase}/list?${qs}`);
        setSutsFiles(Array.isArray(data?.items) ? data.items : []);
      } else {
        data = await fetchJson(`${sutsApiBase}/files`);
        setSutsFiles(Array.isArray(data) ? data : []);
      }
    } catch (e) {
      setSutsNotice(e.message || String(e));
      setSutsFiles([]);
    } finally {
      setSutsFilesLoading(false);
    }
  }, [isJenkins, jenkinsCacheRoot, jenkinsJobUrl, sutsApiBase]);

  const loadSutsView = useCallback(async (filename) => {
    if (!filename) return;
    try {
      let data;
      if (isJenkins) {
        const qs = buildQuery({ job_url: jenkinsJobUrl, cache_root: jenkinsCacheRoot, filename });
        data = await fetchJson(`${sutsApiBase}/view?${qs}`);
      } else {
        data = await fetchJson(`${sutsApiBase}/view/${encodeURIComponent(filename)}`);
      }
      setSutsViewData(data || null);
    } catch (e) {
      setSutsNotice(e.message || String(e));
    }
  }, [isJenkins, jenkinsCacheRoot, jenkinsJobUrl, sutsApiBase]);

  const loadSutsPreview = useCallback(async (filename, options = {}) => {
    if (!filename) return;
    const maxRows = Number(options?.maxRows || 30);
    setSutsPreviewLoading(true);
    setSutsPreviewData(null);
    setSutsPreviewSheet(0);
    try {
      let data;
      if (isJenkins) {
        const qs = buildQuery({ job_url: jenkinsJobUrl, cache_root: jenkinsCacheRoot, filename, max_rows: maxRows });
        data = await fetchJson(`${sutsApiBase}/preview?${qs}`);
      } else {
        data = await fetchJson(`${sutsApiBase}/preview/${encodeURIComponent(filename)}?max_rows=${maxRows}`);
      }
      setSutsPreviewData(data || null);
    } catch (e) {
      setSutsNotice(e.message || String(e));
    } finally {
      setSutsPreviewLoading(false);
    }
  }, [isJenkins, jenkinsCacheRoot, jenkinsJobUrl, sutsApiBase]);

  const handleSutsGenerate = useCallback(async () => {
    if (!String(sutsSourceRoot || "").trim()) { setSutsNotice("source root is required"); return; }
    setSutsLoading(true);
    setSutsNotice("");
    setSutsProgressPct(0);
    setSutsProgressMsg("Preparing...");
    try {
      const form = new FormData();
      form.append("source_root", sutsSourceRoot.trim());
      if (sutsTemplatePath.trim()) form.append("template_path", sutsTemplatePath.trim());
      form.append("project_id", sutsProjectId);
      form.append("version", sutsVersion);
      form.append("asil_level", sutsAsilLevel);
      form.append("max_sequences", String(sutsMaxSeq));
      if (isJenkins) {
        form.append("job_url", jenkinsJobUrl);
        form.append("cache_root", jenkinsCacheRoot);
        form.append("build_selector", jenkinsBuildSelector);
      }
      const launch = await fetchJson(`${sutsApiBase}/generate-async`, { method: "POST", body: form });
      const jobId = launch?.job_id;
      if (!jobId) throw new Error("job id missing");
      while (true) {
        await new Promise((r) => setTimeout(r, 3000));
        const qs = isJenkins
          ? buildQuery({ job_url: jenkinsJobUrl, build_selector: jenkinsBuildSelector, job_id: jobId })
          : buildQuery({ job_id: jobId });
        const pr = await fetchJson(`${sutsApiBase}/progress?${qs}`);
        const progress = pr?.progress || {};
        setSutsProgressPct(progress.percent || 0);
        setSutsProgressMsg(progress.message || "");
        if (progress.error) throw new Error(progress.error);
        if (progress.done) {
          const result = progress.result || null;
          setSutsViewData(result);
          await loadSutsFiles();
          if (result?.filename) await loadSutsPreview(result.filename);
          break;
        }
      }
      setSutsNotice("SUTS generation completed");
    } catch (e) {
      setSutsNotice(e.message || String(e));
    } finally {
      setSutsLoading(false);
      setSutsProgressPct(0);
      setSutsProgressMsg("");
    }
  }, [isJenkins, jenkinsBuildSelector, jenkinsCacheRoot, jenkinsJobUrl, loadSutsFiles, loadSutsPreview, sutsApiBase, sutsAsilLevel, sutsMaxSeq, sutsProjectId, sutsSourceRoot, sutsTemplatePath, sutsVersion]);

  const loadSitsFiles = useCallback(async () => {
    setSitsFilesLoading(true);
    try {
      const data = await fetchJson(`${sitsApiBase}/files`);
      setSitsFiles(Array.isArray(data) ? data : []);
    } catch (e) {
      setSitsNotice(e.message || String(e));
      setSitsFiles([]);
    } finally {
      setSitsFilesLoading(false);
    }
  }, [sitsApiBase]);

  const loadSitsView = useCallback(async (filename) => {
    if (!filename) return;
    try {
      const data = await fetchJson(`${sitsApiBase}/view/${encodeURIComponent(filename)}`);
      setSitsViewData(data || null);
    } catch (e) {
      setSitsNotice(e.message || String(e));
    }
  }, [sitsApiBase]);

  const loadSitsPreview = useCallback(async (filename, options = {}) => {
    if (!filename) return;
    const maxRows = Number(options?.maxRows || 30);
    setSitsPreviewLoading(true);
    setSitsPreviewData(null);
    setSitsPreviewSheet(0);
    try {
      const data = await fetchJson(`${sitsApiBase}/preview/${encodeURIComponent(filename)}?max_rows=${maxRows}`);
      setSitsPreviewData(data || null);
    } catch (e) {
      setSitsNotice(e.message || String(e));
    } finally {
      setSitsPreviewLoading(false);
    }
  }, [sitsApiBase]);

  const handleSitsGenerate = useCallback(async () => {
    if (!String(sitsSourceRoot || "").trim()) { setSitsNotice("source root is required"); return; }
    setSitsLoading(true);
    setSitsNotice("");
    setSitsProgressPct(0);
    setSitsProgressMsg("Preparing...");
    try {
      const form = new FormData();
      form.append("source_root", sitsSourceRoot.trim());
      if (sitsTemplatePath.trim()) form.append("template_path", sitsTemplatePath.trim());
      form.append("project_id", sitsProjectId);
      form.append("version", sitsVersion);
      form.append("asil_level", sitsAsilLevel);
      form.append("max_subcases", String(sitsMaxSubcases));
      if (sitsSrsPath.trim()) form.append("srs_path", sitsSrsPath.trim());
      if (sitsSdsPath.trim()) form.append("sds_path", sitsSdsPath.trim());
      if (sitsHsisPath.trim()) form.append("hsis_path", sitsHsisPath.trim());
      if (sitsUdsPath.trim()) form.append("uds_path", sitsUdsPath.trim());
      if (sitsStpPath.trim()) form.append("stp_path", sitsStpPath.trim());
      const launch = await fetchJson(`${sitsApiBase}/generate-async`, { method: "POST", body: form });
      const jobId = launch?.job_id;
      if (!jobId) throw new Error("job id missing");
      while (true) {
        await new Promise((r) => setTimeout(r, 3000));
        const pr = await fetchJson(`${sitsApiBase}/progress?${buildQuery({ job_id: jobId })}`);
        const progress = pr?.progress || {};
        setSitsProgressPct(progress.percent || 0);
        setSitsProgressMsg(progress.message || "");
        if (progress.error) throw new Error(progress.error);
        if (progress.done) {
          const result = progress.result || null;
          setSitsViewData(result);
          await loadSitsFiles();
          if (result?.filename) await loadSitsPreview(result.filename);
          break;
        }
      }
      setSitsNotice("SITS generation completed");
    } catch (e) {
      setSitsNotice(e.message || String(e));
    } finally {
      setSitsLoading(false);
      setSitsProgressPct(0);
      setSitsProgressMsg("");
    }
  }, [loadSitsFiles, loadSitsPreview, sitsApiBase, sitsAsilLevel, sitsMaxSubcases, sitsProjectId, sitsSourceRoot, sitsTemplatePath, sitsVersion, sitsSrsPath, sitsSdsPath, sitsHsisPath, sitsUdsPath, sitsStpPath]);

  useEffect(() => {
    const preferred = String(preferredArtifactType || "").trim().toLowerCase();
    if (preferred === "impact" || preferred === "uds" || preferred === "sts" || preferred === "suts") {
      setArtifactType(preferred);
    }
  }, [preferredArtifactType]);

  useEffect(() => {
    const handler = (event) => {
      const preferred = String(event?.detail?.artifact || "").trim().toLowerCase();
      if (preferred === "impact" || preferred === "uds" || preferred === "sts" || preferred === "suts") {
        setArtifactType(preferred);
      }
    };
    window.addEventListener("analyzer:preferred-artifact", handler);
    return () => window.removeEventListener("analyzer:preferred-artifact", handler);
  }, []);

  useEffect(() => {
    if (artifactType !== "uds") return;
    loadFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifactType, sourceType, reportDir, jenkinsJobUrl, jenkinsCacheRoot]);

  useEffect(() => {
    if (artifactType !== "sts") return;
    loadStsFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifactType, mode, jenkinsJobUrl, jenkinsCacheRoot]);

  useEffect(() => {
    if (artifactType !== "suts") return;
    loadSutsFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifactType, mode, jenkinsJobUrl, jenkinsCacheRoot]);

  useEffect(() => {
    if (artifactType !== "sits") return;
    loadSitsFiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifactType]);

  const loadRecentSummaries = useCallback(async () => {
    const cards = [];
    try {
      if (mode === "local") {
        const udsFiles = await fetchJson(`/api/local/uds/files${reportDir ? `?report_dir=${encodeURIComponent(reportDir)}` : ""}`);
        const latestUds = Array.isArray(udsFiles) ? udsFiles[0] : null;
        if (latestUds?.filename) {
          const udsView = await fetchJson(`/api/local/uds/view/${encodeURIComponent(latestUds.filename)}${reportDir ? `?report_dir=${encodeURIComponent(reportDir)}` : ""}`);
          cards.push(summarizeUds(udsView));
        }
        const stsFiles = await fetchJson(`/api/local/sts/files`);
        if (Array.isArray(stsFiles) && stsFiles[0]?.filename) {
          const stsView = await fetchJson(`/api/local/sts/view/${encodeURIComponent(stsFiles[0].filename)}`);
          cards.push(summarizeExcel("STS", stsView));
        }
        const sutsFiles = await fetchJson(`/api/local/suts/files`);
        if (Array.isArray(sutsFiles) && sutsFiles[0]?.filename) {
          const sutsView = await fetchJson(`/api/local/suts/view/${encodeURIComponent(sutsFiles[0].filename)}`);
          cards.push(summarizeExcel("SUTS", sutsView));
        }
        cards.push(summarizeSits(overviewDetail));
      } else {
        if (!String(jenkinsJobUrl || "").trim() || !String(jenkinsCacheRoot || "").trim()) {
          setSummaryCards([]);
          return;
        }
        const base = buildQuery({ job_url: jenkinsJobUrl, cache_root: jenkinsCacheRoot });
        const udsFiles = await fetchJson(`/api/jenkins/uds/list?${base}`);
        const latestUds = Array.isArray(udsFiles?.items) ? udsFiles.items[0] : null;
        if (latestUds?.filename) {
          const udsView = await fetchJson(`/api/jenkins/uds/view?${buildQuery({ job_url: jenkinsJobUrl, cache_root: jenkinsCacheRoot, filename: latestUds.filename })}`);
          cards.push(summarizeUds(udsView));
        }
        const stsFiles = await fetchJson(`/api/jenkins/sts/list?${base}`);
        const latestSts = Array.isArray(stsFiles?.items) ? stsFiles.items[0] : null;
        if (latestSts?.filename) {
          const stsView = await fetchJson(`/api/jenkins/sts/view?${buildQuery({ job_url: jenkinsJobUrl, cache_root: jenkinsCacheRoot, filename: latestSts.filename })}`);
          cards.push(summarizeExcel("STS", stsView));
        }
        const sutsFiles = await fetchJson(`/api/jenkins/suts/list?${base}`);
        const latestSuts = Array.isArray(sutsFiles?.items) ? sutsFiles.items[0] : null;
        if (latestSuts?.filename) {
          const sutsView = await fetchJson(`/api/jenkins/suts/view?${buildQuery({ job_url: jenkinsJobUrl, cache_root: jenkinsCacheRoot, filename: latestSuts.filename })}`);
          cards.push(summarizeExcel("SUTS", sutsView));
        }
        cards.push(summarizeSits(overviewDetail));
      }
    } catch (_) {
      // keep partial cards only
    }
    setSummaryCards(cards);
  }, [jenkinsCacheRoot, jenkinsJobUrl, mode, overviewDetail, reportDir]);

  const qaChecks = useMemo(() => {
    const documentCards = (summaryCards || []).filter((item) => item.title !== "SITS");
    const byTitle = Object.fromEntries(documentCards.map((item) => [item.title, item]));
    const hasAllArtifacts = ["UDS", "STS", "SUTS"].every((title) => byTitle[title]);
    const hasValidationLinks = documentCards.every((item) => !!item.validationReportPath);
    const latestMetricsReady = (summaryCards || []).every((item) => Array.isArray(item.primary) && item.primary.length > 0);
    const validationOk = documentCards.every((item) => item?.validation?.valid === true);
    return [
      { label: "Latest Run card shows UDS, STS, SUTS, and SITS summary.", ok: hasAllArtifacts && (summaryCards || []).some((item) => item.title === "SITS") },
      { label: "Latest Run rows can switch to the matching artifact tab.", ok: hasAllArtifacts },
      { label: "Latest Run rows have validation actions.", ok: hasValidationLinks },
      { label: "Latest Run rows expose summary metrics.", ok: latestMetricsReady },
      { label: "Current latest artifacts pass validation.", ok: validationOk },
      { label: "Preview panel is ready for report/preview review.", ok: true },
    ];
  }, [summaryCards]);

  const runGroupLabel = useMemo(() => {
    if (mode === "jenkins") return `Build ${jenkinsBuildSelector || "lastSuccessfulBuild"}`;
    return "Local latest";
  }, [jenkinsBuildSelector, mode]);

  useEffect(() => {
    loadRecentSummaries();
  }, [loadRecentSummaries]);

  const refreshOverview = useCallback(async (scmId) => {
    const id = String(scmId || docScmId || "").trim();
    if (!id) return;
    if (id !== docScmId) setDocScmId(id);
    try {
      const data = await fetchJson(`/api/scm/change-history/${encodeURIComponent(id)}?limit=10`, { timeoutMs: 30000 });
      const rows = Array.isArray(data?.items) ? data.items : [];
      setOverviewHistoryItems(rows);
      const latestRunId = String(rows[0]?.run_id || "").trim();
      if (!latestRunId) { setOverviewDetail(null); return; }
      const detail = await fetchJson(`/api/scm/change-history/detail/${encodeURIComponent(latestRunId)}`, { timeoutMs: 30000 });
      setOverviewDetail(detail?.item || null);
    } catch {
      setOverviewDetail(null);
    }
  }, [docScmId]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        const data = await fetchJson("/api/scm/list", { timeoutMs: 30000 });
        if (cancelled) return;
        const rows = Array.isArray(data?.items) ? data.items : [];
        setDocRegistryItems(rows);
        setDocScmId((prev) => prev || String(rows[0]?.id || ""));
      } catch {
        if (!cancelled) {
          setDocRegistryItems([]);
          setDocScmId("");
        }
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!String(docScmId || "").trim()) {
      setOverviewHistoryItems([]);
      setOverviewDetail(null);
      return undefined;
    }
    let cancelled = false;
    const run = async () => {
      setOverviewLoading(true);
      try {
        const data = await fetchJson(`/api/scm/change-history/${encodeURIComponent(docScmId)}?limit=10`, { timeoutMs: 30000 });
        if (cancelled) return;
        const rows = Array.isArray(data?.items) ? data.items : [];
        setOverviewHistoryItems(rows);
        const latestRunId = String(rows[0]?.run_id || "").trim();
        if (!latestRunId) {
          setOverviewDetail(null);
          return;
        }
        const detail = await fetchJson(`/api/scm/change-history/detail/${encodeURIComponent(latestRunId)}`, { timeoutMs: 30000 });
        if (!cancelled) setOverviewDetail(detail?.item || null);
      } catch {
        if (!cancelled) {
          setOverviewHistoryItems([]);
          setOverviewDetail(null);
        }
      } finally {
        if (!cancelled) setOverviewLoading(false);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [docScmId]);

  useEffect(() => {
    if (artifactType !== "uds" || udsDocMode !== "applied" || !String(docScmId || "").trim()) {
      if (udsDocMode !== "applied") {
        setUdsChangeHistoryItems([]);
        setUdsSelectedRunId("");
        setUdsSelectedChangeDetail(null);
      }
      return;
    }
    let cancelled = false;
    const run = async () => {
      setUdsChangeHistoryLoading(true);
      try {
        const data = await fetchJson(`/api/scm/change-history/${encodeURIComponent(docScmId)}?limit=20`, { timeoutMs: 30000 });
        if (cancelled) return;
        const rows = Array.isArray(data?.items) ? data.items : [];
        setUdsChangeHistoryItems(rows);
        setUdsSelectedRunId((prev) => prev || String(rows[0]?.run_id || ""));
      } catch {
        if (!cancelled) {
          setUdsChangeHistoryItems([]);
          setUdsSelectedRunId("");
        }
      } finally {
        if (!cancelled) setUdsChangeHistoryLoading(false);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [artifactType, udsDocMode, docScmId]);

  useEffect(() => {
    if (artifactType !== "uds" || udsDocMode !== "applied" || !String(udsSelectedRunId || "").trim()) {
      if (udsDocMode !== "applied") setUdsSelectedChangeDetail(null);
      return;
    }
    let cancelled = false;
    const run = async () => {
      try {
        const data = await fetchJson(`/api/scm/change-history/detail/${encodeURIComponent(udsSelectedRunId)}`, { timeoutMs: 30000 });
        if (!cancelled) setUdsSelectedChangeDetail(data?.item || null);
      } catch {
        if (!cancelled) setUdsSelectedChangeDetail(null);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [artifactType, udsDocMode, udsSelectedRunId]);

  useEffect(() => {
    if (artifactType !== "sts" || stsDocMode !== "applied" || !String(docScmId || "").trim()) {
      if (stsDocMode !== "applied") {
        setStsChangeHistoryItems([]);
        setStsSelectedRunId("");
        setStsSelectedChangeDetail(null);
      }
      return;
    }
    let cancelled = false;
    const run = async () => {
      setStsChangeHistoryLoading(true);
      try {
        const data = await fetchJson(`/api/scm/change-history/${encodeURIComponent(docScmId)}?limit=20`, { timeoutMs: 30000 });
        if (cancelled) return;
        const rows = Array.isArray(data?.items) ? data.items : [];
        setStsChangeHistoryItems(rows);
        setStsSelectedRunId((prev) => prev || String(rows[0]?.run_id || ""));
      } catch {
        if (!cancelled) {
          setStsChangeHistoryItems([]);
          setStsSelectedRunId("");
        }
      } finally {
        if (!cancelled) setStsChangeHistoryLoading(false);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [artifactType, stsDocMode, docScmId]);

  useEffect(() => {
    if (artifactType !== "sts" || stsDocMode !== "applied" || !String(stsSelectedRunId || "").trim()) {
      if (stsDocMode !== "applied") setStsSelectedChangeDetail(null);
      return;
    }
    let cancelled = false;
    const run = async () => {
      try {
        const data = await fetchJson(`/api/scm/change-history/detail/${encodeURIComponent(stsSelectedRunId)}`, { timeoutMs: 30000 });
        if (!cancelled) setStsSelectedChangeDetail(data?.item || null);
      } catch {
        if (!cancelled) setStsSelectedChangeDetail(null);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [artifactType, stsDocMode, stsSelectedRunId]);

  useEffect(() => {
    if (artifactType !== "suts" || sutsDocMode !== "applied" || !String(docScmId || "").trim()) {
      if (sutsDocMode !== "applied") {
        setSutsChangeHistoryItems([]);
        setSutsSelectedRunId("");
        setSutsSelectedChangeDetail(null);
      }
      return;
    }
    let cancelled = false;
    const run = async () => {
      setSutsChangeHistoryLoading(true);
      try {
        const data = await fetchJson(`/api/scm/change-history/${encodeURIComponent(docScmId)}?limit=20`, { timeoutMs: 30000 });
        if (cancelled) return;
        const rows = Array.isArray(data?.items) ? data.items : [];
        setSutsChangeHistoryItems(rows);
        setSutsSelectedRunId((prev) => prev || String(rows[0]?.run_id || ""));
      } catch {
        if (!cancelled) {
          setSutsChangeHistoryItems([]);
          setSutsSelectedRunId("");
        }
      } finally {
        if (!cancelled) setSutsChangeHistoryLoading(false);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [artifactType, sutsDocMode, docScmId]);

  useEffect(() => {
    if (artifactType !== "suts" || sutsDocMode !== "applied" || !String(sutsSelectedRunId || "").trim()) {
      if (sutsDocMode !== "applied") setSutsSelectedChangeDetail(null);
      return;
    }
    let cancelled = false;
    const run = async () => {
      try {
        const data = await fetchJson(`/api/scm/change-history/detail/${encodeURIComponent(sutsSelectedRunId)}`, { timeoutMs: 30000 });
        if (!cancelled) setSutsSelectedChangeDetail(data?.item || null);
      } catch {
        if (!cancelled) setSutsSelectedChangeDetail(null);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [artifactType, sutsDocMode, sutsSelectedRunId]);

  // SITS change history list
  useEffect(() => {
    if (artifactType !== "sits" || sitsDocMode !== "applied" || !String(docScmId || "").trim()) {
      if (sitsDocMode !== "applied") {
        setSitsChangeHistoryItems([]);
        setSitsSelectedRunId("");
      }
      return;
    }
    let cancelled = false;
    const run = async () => {
      setSitsChangeHistoryLoading(true);
      try {
        const data = await fetchJson(`/api/scm/change-history/${encodeURIComponent(docScmId)}?limit=20`, { timeoutMs: 30000 });
        if (cancelled) return;
        const rows = Array.isArray(data?.items) ? data.items : [];
        setSitsChangeHistoryItems(rows);
        setSitsSelectedRunId((prev) => prev || String(rows[0]?.run_id || ""));
      } catch {
        if (!cancelled) { setSitsChangeHistoryItems([]); setSitsSelectedRunId(""); }
      } finally {
        if (!cancelled) setSitsChangeHistoryLoading(false);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [artifactType, sitsDocMode, docScmId]);

  // SITS change detail
  useEffect(() => {
    if (artifactType !== "sits" || sitsDocMode !== "applied" || !String(sitsSelectedRunId || "").trim()) {
      if (sitsDocMode !== "applied") setSitsSelectedChangeDetail(null);
      return;
    }
    let cancelled = false;
    const run = async () => {
      try {
        const data = await fetchJson(`/api/scm/change-history/detail/${encodeURIComponent(sitsSelectedRunId)}`, { timeoutMs: 30000 });
        if (!cancelled) setSitsSelectedChangeDetail(data?.item || null);
      } catch {
        if (!cancelled) setSitsSelectedChangeDetail(null);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [artifactType, sitsDocMode, sitsSelectedRunId]);

  useEffect(() => {
    if (artifactType !== "sts" || stsDocMode !== "applied") {
      setStsArtifactText("");
      setStsArtifactLoading(false);
      return;
    }
    const artifactPath = String(stsSelectedChangeDetail?.documents?.sts?.artifact_path || "").trim();
    if (!artifactPath) {
      setStsArtifactText("");
      setStsArtifactLoading(false);
      return;
    }
    let cancelled = false;
    const run = async () => {
      setStsArtifactLoading(true);
      try {
        const res = await fetch("/api/local/editor/read-abs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: artifactPath, max_bytes: 200000 }),
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const data = await res.json();
        if (!cancelled) setStsArtifactText(String(data?.text || ""));
      } catch {
        if (!cancelled) setStsArtifactText("");
      } finally {
        if (!cancelled) setStsArtifactLoading(false);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [artifactType, stsDocMode, stsSelectedChangeDetail]);

  useEffect(() => {
    if (artifactType !== "suts" || sutsDocMode !== "applied") {
      setSutsArtifactText("");
      setSutsArtifactLoading(false);
      return;
    }
    const artifactPath = String(sutsSelectedChangeDetail?.documents?.suts?.validation_report_path || "").trim();
    if (!artifactPath) {
      setSutsArtifactText("");
      setSutsArtifactLoading(false);
      return;
    }
    let cancelled = false;
    const run = async () => {
      setSutsArtifactLoading(true);
      try {
        const res = await fetch("/api/local/editor/read-abs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: artifactPath, max_bytes: 200000 }),
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const data = await res.json();
        if (!cancelled) setSutsArtifactText(String(data?.text || ""));
      } catch {
        if (!cancelled) setSutsArtifactText("");
      } finally {
        if (!cancelled) setSutsArtifactLoading(false);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [artifactType, sutsDocMode, sutsSelectedChangeDetail]);

  useEffect(() => {
    if (artifactType !== "sds" || sdsDocMode !== "applied" || !String(docScmId || "").trim()) {
      if (sdsDocMode !== "applied") {
        setSdsChangeHistoryItems([]);
        setSdsSelectedRunId("");
        setSdsSelectedChangeDetail(null);
      }
      return;
    }
    let cancelled = false;
    const run = async () => {
      setSdsChangeHistoryLoading(true);
      try {
        const data = await fetchJson(`/api/scm/change-history/${encodeURIComponent(docScmId)}?limit=20`, { timeoutMs: 30000 });
        if (cancelled) return;
        const rows = Array.isArray(data?.items) ? data.items : [];
        setSdsChangeHistoryItems(rows);
        setSdsSelectedRunId((prev) => prev || String(rows[0]?.run_id || ""));
      } catch {
        if (!cancelled) {
          setSdsChangeHistoryItems([]);
          setSdsSelectedRunId("");
        }
      } finally {
        if (!cancelled) setSdsChangeHistoryLoading(false);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [artifactType, sdsDocMode, docScmId]);

  useEffect(() => {
    if (artifactType !== "sds" || sdsDocMode !== "applied" || !String(sdsSelectedRunId || "").trim()) {
      if (sdsDocMode !== "applied") setSdsSelectedChangeDetail(null);
      return;
    }
    let cancelled = false;
    const run = async () => {
      try {
        const data = await fetchJson(`/api/scm/change-history/detail/${encodeURIComponent(sdsSelectedRunId)}`, { timeoutMs: 30000 });
        if (!cancelled) setSdsSelectedChangeDetail(data?.item || null);
      } catch {
        if (!cancelled) setSdsSelectedChangeDetail(null);
      }
    };
    run();
    return () => { cancelled = true; };
  }, [artifactType, sdsDocMode, sdsSelectedRunId]);

  useEffect(() => {
    if (artifactType !== "sds" || sdsDocMode !== "applied") {
      setSdsArtifactText("");
      setSdsArtifactLoading(false);
      return;
    }
    const artifactPath = String(sdsSelectedChangeDetail?.documents?.sds?.artifact_path || "").trim();
    if (!artifactPath) {
      setSdsArtifactText("");
      setSdsArtifactLoading(false);
      return;
    }
    let cancelled = false;
    const run = async () => {
      setSdsArtifactLoading(true);
      try {
        const res = await fetch("/api/local/editor/read-abs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: artifactPath, max_bytes: 200000 }),
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const data = await res.json();
        if (!cancelled) setSdsArtifactText(String(data?.text || ""));
      } catch {
        if (!cancelled) setSdsArtifactText("");
      } finally {
        if (!cancelled) setSdsArtifactLoading(false);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [artifactType, sdsDocMode, sdsSelectedChangeDetail]);

  useEffect(() => {
    if (artifactType !== "sds" || sdsDocMode !== "current") return;
    const entry = Array.isArray(docRegistryItems) ? docRegistryItems.find((item) => String(item?.id || "") === String(docScmId || "")) : null;
    const path = String(entry?.linked_docs?.sds || commonSdsPath || "").trim();
    if (!path) {
      setSdsCurrentView({ path: "", items: [], counts: {}, loading: false, error: "SDS 경로가 설정되지 않았습니다." });
      return;
    }
    const changedFunctions = overviewDetail?.changed_functions && typeof overviewDetail.changed_functions === "object"
      ? overviewDetail.changed_functions
      : {};
    const changedFiles = Array.isArray(overviewDetail?.changed_files) ? overviewDetail.changed_files : [];
    const flaggedModules = Array.isArray(sdsSelectedChangeDetail?.documents?.sds?.flagged_modules)
      ? sdsSelectedChangeDetail.documents.sds.flagged_modules
      : [];
    loadSdsViewTo(setSdsCurrentView, path, { changedFunctions, changedFiles, flaggedModules });
  }, [artifactType, sdsDocMode, docRegistryItems, docScmId, commonSdsPath, loadSdsViewTo, overviewDetail, sdsSelectedChangeDetail]);

  useEffect(() => {
    if (artifactType !== "sds" || sdsDocMode !== "planned") return;
    const entry = Array.isArray(docRegistryItems) ? docRegistryItems.find((item) => String(item?.id || "") === String(docScmId || "")) : null;
    const path = String(entry?.linked_docs?.sds || commonSdsPath || "").trim();
    if (!path) {
      setSdsPlannedView({ path: "", items: [], counts: {}, loading: false, error: "SDS 경로가 설정되지 않았습니다." });
      return;
    }
    const changedFunctions = overviewDetail?.changed_functions && typeof overviewDetail.changed_functions === "object"
      ? overviewDetail.changed_functions
      : {};
    const changedFiles = Array.isArray(overviewDetail?.changed_files) ? overviewDetail.changed_files : [];
    loadSdsViewTo(setSdsPlannedView, path, { changedFunctions, changedFiles, flaggedModules: [] });
  }, [artifactType, sdsDocMode, docRegistryItems, docScmId, commonSdsPath, loadSdsViewTo, overviewDetail]);

  useEffect(() => {
    if (artifactType !== "sds" || sdsDocMode !== "current" || !focusedChangeFunction) return;
    const items = Array.isArray(sdsCurrentView?.items) ? sdsCurrentView.items : [];
    const matched = items.find((item) => {
      if (String(item?.functionName || "") === String(focusedChangeFunction)) return true;
      return Array.isArray(item?.relatedFunctions) && item.relatedFunctions.some((name) => String(name) === String(focusedChangeFunction));
    });
    if (matched?.id) setSdsSelectedItemId(String(matched.id));
  }, [artifactType, sdsDocMode, focusedChangeFunction, sdsCurrentView]);

  useEffect(() => {
    if (artifactType !== "sds" || sdsDocMode !== "planned" || !focusedChangeFunction) return;
    const items = Array.isArray(sdsPlannedView?.items) ? sdsPlannedView.items : [];
    const matched = items.find((item) => {
      if (String(item?.functionName || "") === String(focusedChangeFunction)) return true;
      return Array.isArray(item?.relatedFunctions) && item.relatedFunctions.some((name) => String(name) === String(focusedChangeFunction));
    });
    if (matched?.id) setSdsSelectedItemId(String(matched.id));
  }, [artifactType, sdsDocMode, focusedChangeFunction, sdsPlannedView]);

  useEffect(() => {
    if (artifactType !== "sds" || sdsDocMode !== "applied" || !focusedChangeFunction) return;
    const items = Array.isArray(sdsAppliedView?.items) ? sdsAppliedView.items : [];
    const matched = items.find((item) => {
      if (String(item?.functionName || "") === String(focusedChangeFunction)) return true;
      return Array.isArray(item?.relatedFunctions) && item.relatedFunctions.some((name) => String(name) === String(focusedChangeFunction));
    });
    if (matched?.id) setSdsSelectedItemId(String(matched.id));
  }, [artifactType, sdsDocMode, focusedChangeFunction, sdsAppliedView]);

  useEffect(() => {
    if (artifactType !== "sds" || sdsDocMode !== "applied") return;
    const entry = Array.isArray(docRegistryItems) ? docRegistryItems.find((item) => String(item?.id || "") === String(docScmId || "")) : null;
    const path = String(entry?.linked_docs?.sds || commonSdsPath || "").trim();
    if (!path) {
      setSdsAppliedView({ path: "", items: [], counts: {}, loading: false, error: "SDS 경로가 설정되지 않았습니다." });
      return;
    }
    const changedFunctions = sdsSelectedChangeDetail?.changed_functions && typeof sdsSelectedChangeDetail.changed_functions === "object"
      ? sdsSelectedChangeDetail.changed_functions
      : {};
    const changedFiles = Array.isArray(sdsSelectedChangeDetail?.changed_files) ? sdsSelectedChangeDetail.changed_files : [];
    const flaggedModules = Array.isArray(sdsSelectedChangeDetail?.documents?.sds?.flagged_modules)
      ? sdsSelectedChangeDetail.documents.sds.flagged_modules
      : [];
    setSdsAppliedView((prev) => ({ ...prev, path, loading: true, error: "" }));
    loadSdsViewTo(setSdsAppliedView, path, { changedFunctions, changedFiles, flaggedModules });
  }, [artifactType, sdsDocMode, docRegistryItems, docScmId, commonSdsPath, sdsSelectedChangeDetail, loadSdsViewTo]);

  useEffect(() => {
    if (artifactType !== "sds") {
      setSdsItemHistory([]);
      setSdsItemHistoryLoading(false);
      setSdsModuleHistory([]);
      setSdsModuleHistoryLoading(false);
      return;
    }
    const activeView = sdsDocMode === "applied" ? sdsAppliedView : sdsDocMode === "planned" ? sdsPlannedView : sdsCurrentView;
    const items = Array.isArray(activeView?.items) ? activeView.items : [];
    const selectedItem =
      items.find((item) => String(item?.id || "") === String(sdsSelectedItemId || "")) ||
      items[0] ||
      null;
    const functionName = String(
      selectedItem?.functionName ||
      (Array.isArray(selectedItem?.relatedFunctions) ? selectedItem.relatedFunctions[0] : "") ||
      ""
    ).trim();
    if (!String(docScmId || "").trim() || !functionName) {
      setSdsItemHistory([]);
      setSdsItemHistoryLoading(false);
    } else {
      let cancelled = false;
      const run = async () => {
        setSdsItemHistoryLoading(true);
        try {
          const data = await fetchJson(
            `/api/scm/change-history/function/${encodeURIComponent(docScmId)}/${encodeURIComponent(functionName)}?limit=10`,
            { timeoutMs: 30000 }
          );
          if (!cancelled) {
            setSdsItemHistory(Array.isArray(data?.items) ? data.items : []);
          }
        } catch {
          if (!cancelled) setSdsItemHistory([]);
        } finally {
          if (!cancelled) setSdsItemHistoryLoading(false);
        }
      };
      run();
      return () => {
        cancelled = true;
      };
    }
  }, [artifactType, sdsDocMode, sdsAppliedView, sdsPlannedView, sdsCurrentView, sdsSelectedItemId, docScmId]);

  useEffect(() => {
    if (artifactType !== "sds") {
      setSdsModuleHistory([]);
      setSdsModuleHistoryLoading(false);
      return;
    }
    const activeView = sdsDocMode === "applied" ? sdsAppliedView : sdsDocMode === "planned" ? sdsPlannedView : sdsCurrentView;
    const items = Array.isArray(activeView?.items) ? activeView.items : [];
    const selectedItem =
      items.find((item) => String(item?.id || "") === String(sdsSelectedItemId || "")) ||
      items[0] ||
      null;
    const moduleName = String(
      selectedItem?.moduleName ||
      (Array.isArray(selectedItem?.relatedModules) ? selectedItem.relatedModules[0] : "") ||
      ""
    ).trim();
    if (!String(docScmId || "").trim() || !moduleName) {
      setSdsModuleHistory([]);
      setSdsModuleHistoryLoading(false);
      return;
    }
    let cancelled = false;
    const run = async () => {
      setSdsModuleHistoryLoading(true);
      try {
        const data = await fetchJson(
          `/api/scm/change-history/module/${encodeURIComponent(docScmId)}/${encodeURIComponent(moduleName)}?limit=10`,
          { timeoutMs: 30000 }
        );
        if (!cancelled) {
          setSdsModuleHistory(Array.isArray(data?.items) ? data.items : []);
        }
      } catch {
        if (!cancelled) setSdsModuleHistory([]);
      } finally {
        if (!cancelled) setSdsModuleHistoryLoading(false);
      }
    };
    run();
    return () => {
      cancelled = true;
    };
  }, [artifactType, sdsDocMode, sdsAppliedView, sdsPlannedView, sdsCurrentView, sdsSelectedItemId, docScmId]);

  const analyzerTitle = useMemo(() => (isLocal ? "Analyzer (Local UDS)" : "Analyzer (Jenkins UDS)"), [isLocal]);
  const analyzerStatus = useMemo(() => {
    if (String(viewError || "").trim()) return { tone: "error", text: `Detail error: ${viewError}` };
    if (String(filesError || "").trim()) return { tone: "error", text: `File list error: ${filesError}` };
    if (filesLoading) return { tone: "loading", text: "Loading file list..." };
    if (viewLoading) return { tone: "loading", text: "Loading detail..." };
    if (String(genNotice || "").trim()) return { tone: "info", text: genNotice };
    return { tone: "idle", text: "Ready" };
  }, [filesError, filesLoading, genNotice, viewError, viewLoading]);

  const pickUdsFile = async () => {
    if (typeof pickFile !== "function") return;
    const picked = await pickFile("Select UDS file");
    if (!picked) return;
    const filename = String(picked).split(/[\\/]/).pop() || "";
    setFiles((prev) => ([{ filename, path: String(picked) }, ...(Array.isArray(prev) ? prev : [])]));
    setSelectedDocxPath(String(picked));
    await loadView(filename);
  };

  const runGenerateLocal = async () => {
    if (!isLocal) return;
    const src = String(sourceRoot || "").trim();
    const reqPaths = [commonSrsPath, commonSdsPath].map((value) => String(value || "").trim()).filter(Boolean);
    if (!src) {
      setGenNotice("Code source root is required.");
      return;
    }
    if (!genSrsDoc && !genSdsDoc && reqPaths.length === 0) {
      setGenNotice("Provide at least one requirement document through Analyzer Global Context or Advanced Overrides.");
      return;
    }
    setGenLoading(true);
    setGenNotice("UDS generation request in progress...");
    try {
      const reqId = `uds-gen-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
      const form = new FormData();
      form.append("source_root", src);
      if (reqPaths.length > 0) form.append("req_paths", reqPaths.join("\n"));
      if (genSrsDoc) form.append("req_files", genSrsDoc);
      if (genSdsDoc) form.append("req_files", genSdsDoc);
      if (genRefUdsDoc) form.append("req_files", genRefUdsDoc);
      if (genTemplateDoc) form.append("template_file", genTemplateDoc);
      form.append("ai_enable", "true");
      form.append("expand", "true");
      form.append("ai_detailed", "true");
      form.append("call_relation_mode", "code");
      form.append("rag_top_k", "12");
      form.append("globals_format_with_labels", "true");
      form.append("show_mapping_evidence", genShowMappingEvidence ? "true" : "false");
      form.append("test_mode", genTestMode ? "true" : "false");
      form.append("doc_only", genTestMode ? "false" : "true");
      if (String(reportDir || "").trim()) form.append("report_dir", String(reportDir).trim());
      const asyncRes = await fetchJson("/api/local/uds/generate-async", { method: "POST", body: form, headers: { "X-Req-Id": reqId }, timeoutMs: 30000 });
      const jobId = asyncRes?.job_id;
      if (!jobId) throw new Error("Async generation job id was not returned.");
      let data = null;
      const maxPollMs = genTestMode ? 14400000 : 600000;
      const pollStart = Date.now();
      while (Date.now() - pollStart < maxPollMs) {
        await new Promise((r) => setTimeout(r, 3000));
        const prog = await fetchJson(`/api/local/uds/progress?job_id=${jobId}`);
        const p = prog?.progress || {};
        const pct = Number(p?.percent || 0);
        if (pct > 0) {
          setOpProgress(Math.min(90, 30 + Math.round(pct * 0.6)));
          setOpStep(String(p?.message || `Progress ${pct}%`));
        }
        if (p?.done) {
          if (p?.error) throw new Error(p.error);
          data = p?.result || {};
          break;
        }
      }
      if (!data) throw new Error("UDS generation timed out.");
      const filename = String(data?.filename || "").trim();
      if (!filename) throw new Error("Generated filename is missing.");
      setGenQualityGate(data?.quick_quality_gate || null);
      setGenNotice(`Generated: ${filename}`);
      await loadFiles();
      await loadView(filename);
      await loadRecentSummaries();
    } catch (e) {
      setGenNotice(`Generation failed: ${e?.message || String(e)}`);
    } finally {
      setGenLoading(false);
      setOpProgress(100);
      setOpStep("UDS generation complete");
    }
  };

  const overviewChangedFiles = Array.isArray(overviewDetail?.changed_files) ? overviewDetail.changed_files : [];
  const overviewChangedFunctions = overviewDetail?.changed_functions && typeof overviewDetail.changed_functions === "object"
    ? Object.entries(overviewDetail.changed_functions)
    : [];
  const overviewSummary = overviewDetail?.summary || {};
  const selectedSdsArtifactMatches = useMemo(() => {
    if (!String(sdsArtifactText || "").trim()) return [];
    const activeView = sdsDocMode === "applied" ? sdsAppliedView : sdsDocMode === "planned" ? sdsPlannedView : sdsCurrentView;
    const items = Array.isArray(activeView?.items) ? activeView.items : [];
    const selectedItem =
      items.find((item) => String(item?.id || "") === String(sdsSelectedItemId || "")) ||
      items[0] ||
      null;
    if (!selectedItem) return [];
    const tokens = [
      selectedItem.title,
      selectedItem.functionName,
      selectedItem.moduleName,
      ...(Array.isArray(selectedItem.relatedFunctions) ? selectedItem.relatedFunctions : []),
      ...(Array.isArray(selectedItem.relatedModules) ? selectedItem.relatedModules : []),
    ]
      .map((value) => String(value || "").trim())
      .filter(Boolean);
    if (tokens.length === 0) return [];
    const blocks = String(sdsArtifactText || "")
      .split(/\r?\n\s*\r?\n/)
      .map((block) => block.trim())
      .filter(Boolean);
    const scored = blocks
      .map((block) => {
        const lower = block.toLowerCase();
        const matchedTokens = tokens.filter((token) => lower.includes(token.toLowerCase()));
        return {
          text: block,
          score: matchedTokens.length,
          matchedTokens,
        };
      })
      .filter((entry) => entry.score > 0)
      .sort((a, b) => b.score - a.score || b.text.length - a.text.length);
    return scored.slice(0, 5).map((entry) => {
      const prefix = entry.matchedTokens.length > 0 ? `[${entry.matchedTokens.join(", ")}] ` : "";
      return `${prefix}${entry.text}`;
    });
  }, [sdsArtifactText, sdsDocMode, sdsAppliedView, sdsPlannedView, sdsCurrentView, sdsSelectedItemId]);
  const selectedStsArtifactMatches = useMemo(() => {
    const tokens = [
      focusedChangeFunction,
      ...(stsSelectedChangeDetail?.changed_functions && typeof stsSelectedChangeDetail.changed_functions === "object"
        ? Object.keys(stsSelectedChangeDetail.changed_functions)
        : []),
      ...(Array.isArray(stsSelectedChangeDetail?.documents?.sts?.flagged_functions)
        ? stsSelectedChangeDetail.documents.sts.flagged_functions
        : []),
    ];
    return matchArtifactBlocks(stsArtifactText, Array.from(new Set(tokens)), 5);
  }, [stsArtifactText, stsSelectedChangeDetail, focusedChangeFunction]);
  const selectedSutsArtifactMatches = useMemo(() => {
    const tokens = [
      focusedChangeFunction,
      ...(sutsSelectedChangeDetail?.changed_functions && typeof sutsSelectedChangeDetail.changed_functions === "object"
        ? Object.keys(sutsSelectedChangeDetail.changed_functions)
        : []),
      ...(Array.isArray(sutsSelectedChangeDetail?.documents?.suts?.changed_cases)
        ? sutsSelectedChangeDetail.documents.suts.changed_cases.flatMap((row) => [row.function, row.testcase]).filter(Boolean)
        : []),
    ];
    return matchArtifactBlocks(sutsArtifactText, Array.from(new Set(tokens)), 5);
  }, [sutsArtifactText, sutsSelectedChangeDetail, focusedChangeFunction]);
  const stsReviewTargets = useMemo(() => {
    const changedFunctions = stsSelectedChangeDetail?.changed_functions && typeof stsSelectedChangeDetail.changed_functions === "object"
      ? stsSelectedChangeDetail.changed_functions
      : {};
    const flaggedFunctions = Array.isArray(stsSelectedChangeDetail?.documents?.sts?.flagged_functions)
      ? stsSelectedChangeDetail.documents.sts.flagged_functions
      : [];
    return Array.from(new Set([...Object.keys(changedFunctions), ...flaggedFunctions]))
      .filter(Boolean)
      .map((name) => {
        const kind = changedFunctions[name] || "";
        const flagged = flaggedFunctions.includes(name);
        return {
          name,
          kind,
          flagged,
          isFocused: Boolean(focusedChangeFunction && name === focusedChangeFunction),
          reviewCategories: getReviewCategoryHintsByKind(kind, "sts"),
          artifactMatches: matchArtifactBlocks(stsArtifactText, [name, focusedChangeFunction].filter(Boolean), 2),
        };
      })
      .sort((a, b) => {
        const focusDelta = Number(b.isFocused) - Number(a.isFocused);
        if (focusDelta !== 0) return focusDelta;
        const flaggedDelta = Number(b.flagged) - Number(a.flagged);
        if (flaggedDelta !== 0) return flaggedDelta;
        return String(a.name).localeCompare(String(b.name));
      });
  }, [stsSelectedChangeDetail, stsArtifactText, focusedChangeFunction]);
  const sutsCaseGroups = useMemo(
    () => buildSutsCaseGroups(sutsSelectedChangeDetail, sutsArtifactText, focusedChangeFunction),
    [sutsSelectedChangeDetail, sutsArtifactText, focusedChangeFunction]
  );
  const overviewFlowCards = [
    { label: "Changed Files", value: overviewChangedFiles.length, tone: "files" },
    { label: "Changed Functions", value: overviewChangedFunctions.length, tone: "functions" },
  ];
  const overviewDocumentCards = [
    { label: "SDS", value: overviewSummary.sds_flagged || 0, tone: "sds" },
    { label: "UDS", value: overviewSummary.uds_changed_functions || 0, tone: "uds" },
    { label: "STS", value: overviewSummary.sts_flagged || 0, tone: "sts" },
    { label: "SUTS", value: overviewSummary.suts_changed_cases || overviewSummary.suts_changed_functions || 0, tone: "suts" },
    { label: "SITS", value: overviewSummary.sits_changed_cases || overviewSummary.sits_flagged || 0, tone: "sits" },
  ];
  const commonContextChecks = [
    { label: "Source Root", ok: Boolean(String(sourceRoot || "").trim()) },
    { label: "SRS", ok: Boolean(String(commonSrsPath || "").trim()) },
    { label: "SDS", ok: Boolean(String(commonSdsPath || "").trim()) },
    { label: "HSIS", ok: Boolean(String(commonHsisPath || "").trim()) },
    { label: "UDS Ref", ok: Boolean(String(commonUdsPath || "").trim()) },
  ];
  const udsContextState = {
    sourceRoot: String(sourceRoot || "").trim() ? "COMMON" : "MISSING",
  };
  const stsContextState = {
    sourceRoot: String(stsSourceRoot || "").trim() === String(sourceRoot || "").trim() ? "COMMON" : "OVERRIDE",
    srs: String(stsSrsPath || "").trim() === String(commonSrsPath || "").trim() ? "COMMON" : "OVERRIDE",
    sds: String(stsSdsPath || "").trim() === String(commonSdsPath || "").trim() ? "COMMON" : "OVERRIDE",
    hsis: String(stsHsisPath || "").trim() === String(commonHsisPath || "").trim() ? "COMMON" : "OVERRIDE",
    uds: String(stsUdsPath || "").trim() === String(commonUdsPath || "").trim() ? "COMMON" : "OVERRIDE",
  };
  const sutsContextState = {
    sourceRoot: String(sutsSourceRoot || "").trim() === String(sourceRoot || "").trim() ? "COMMON" : "OVERRIDE",
    srs: String(sutsSrsPath || "").trim() === String(commonSrsPath || "").trim() ? "COMMON" : "OVERRIDE",
    sds: String(sutsSdsPath || "").trim() === String(commonSdsPath || "").trim() ? "COMMON" : "OVERRIDE",
    hsis: String(sutsHsisPath || "").trim() === String(commonHsisPath || "").trim() ? "COMMON" : "OVERRIDE",
    uds: String(sutsUdsPath || "").trim() === String(commonUdsPath || "").trim() ? "COMMON" : "OVERRIDE",
  };

  const applyCommonContextToSts = useCallback(() => {
    setStsSourceRoot(String(sourceRoot || ""));
    setStsSrsPath(String(commonSrsPath || ""));
    setStsSdsPath(String(commonSdsPath || ""));
    setStsHsisPath(String(commonHsisPath || ""));
    setStsUdsPath(String(commonUdsPath || ""));
  }, [commonHsisPath, commonSdsPath, commonSrsPath, commonUdsPath, sourceRoot]);

  const applyCommonContextToSuts = useCallback(() => {
    setSutsSourceRoot(String(sourceRoot || ""));
    setSutsSrsPath(String(commonSrsPath || ""));
    setSutsSdsPath(String(commonSdsPath || ""));
    setSutsHsisPath(String(commonHsisPath || ""));
    setSutsUdsPath(String(commonUdsPath || ""));
  }, [commonHsisPath, commonSdsPath, commonSrsPath, commonUdsPath, sourceRoot]);

  const openAppliedArtifact = useCallback((target, functionName = "") => {
    if (!overviewDetail?.run_id) return;
    const nextFocus =
      functionName ||
      (target === "sds" ? getPreferredSdsFocusFunction(overviewDetail) : "");
    setFocusedChangeFunction(nextFocus || "");
    if (target === "uds") {
      setArtifactType("uds");
      setUdsDocMode("applied");
      setUdsSelectedRunId(String(overviewDetail.run_id));
      requestAnimationFrame(() => {
        setTimeout(() => udsAppliedDiffRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 120);
      });
      return;
    }
    if (target === "sts") {
      setArtifactType("sts");
      setStsDocMode("applied");
      setStsSelectedRunId(String(overviewDetail.run_id));
      requestAnimationFrame(() => {
        setTimeout(() => stsAppliedReviewRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 120);
      });
      return;
    }
    if (target === "suts") {
      setArtifactType("suts");
      setSutsDocMode("applied");
      setSutsSelectedRunId(String(overviewDetail.run_id));
      requestAnimationFrame(() => {
        setTimeout(() => sutsAppliedDiffRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 120);
      });
      return;
    }
    if (target === "sds") {
      setSdsSelectedItemId("");
      setArtifactType("sds");
      setSdsDocMode("applied");
      setSdsSelectedRunId(String(overviewDetail.run_id));
      requestAnimationFrame(() => {
        setTimeout(() => sdsAppliedReviewRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 120);
      });
    }
  }, [overviewDetail]);

  return (
    <div className="panel">
      <h3>Analyzer</h3>
      <div className="hint">Analyzer now covers UDS, STS, and SUTS generation plus result views for Local and Jenkins modes.</div>

      <div className="card analyzer-overview-card" style={{ padding: 14, marginTop: 12, marginBottom: 12 }}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div>
            <strong>Code Change Overview</strong>
            <div className="hint analyzer-mode-banner-hint">
              최신 코드 변경이 어떤 문서에 영향을 주는지 한눈에 확인합니다.
            </div>
          </div>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <select value={docScmId} onChange={(e) => setDocScmId(e.target.value)}>
              <option value="">SCM Registry</option>
              {docRegistryItems.map((item) => (
                <option key={item.id} value={item.id}>{item.name || item.id}</option>
              ))}
            </select>
            <span className="badge">{overviewLoading ? "LOADING" : overviewDetail ? "LATEST RUN" : "NO DATA"}</span>
          </div>
        </div>

        <div className="analyzer-overview-flow">
          {overviewFlowCards.map((card, index) => (
            <button
              key={card.label}
              type="button"
              className={`analyzer-overview-node tone-${card.tone}`}
              onClick={() => {}}
            >
              <div className="hint">{card.label}</div>
              <div className="analyzer-overview-value">{card.value}</div>
              {index < overviewFlowCards.length - 1 ? <div className="analyzer-overview-arrow">→</div> : null}
            </button>
          ))}
        </div>

        <div className="analyzer-overview-docs">
          {overviewDocumentCards.map((card) => (
            <button
              key={card.label}
              type="button"
              className={`analyzer-overview-node tone-${card.tone} ${["uds", "suts", "sts", "sds", "sits"].includes(card.tone) ? "is-clickable" : ""}`}
              onClick={() => {
                if (card.tone === "uds" && Number(card.value || 0) > 0) openAppliedArtifact("uds");
                if (card.tone === "suts" && Number(card.value || 0) > 0) openAppliedArtifact("suts");
                if (card.tone === "sits") setArtifactType("sits");
                if (card.tone === "sts" && Number(card.value || 0) > 0) openAppliedArtifact("sts");
                if (card.tone === "sds" && Number(card.value || 0) > 0) openAppliedArtifact("sds");
              }}
            >
              <div className="hint">{card.label}</div>
              <div className="analyzer-overview-value">{card.value}</div>
            </button>
          ))}
        </div>

        <div className="analyzer-overview-grid">
          <div className="card" style={{ padding: 12 }}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <strong>Latest Run</strong>
              <span className="hint">{overviewDetail?.run_id || "-"}</span>
            </div>
            <div className="hint" style={{ marginTop: 6 }}>{overviewDetail?.timestamp || "No recent change history."}</div>
            <div className="hint" style={{ marginTop: 6 }}>
              {overviewDetail ? `${overviewDetail.dry_run ? "Dry Run" : "Real Run"} / ${String(overviewDetail.trigger || "-").toUpperCase()}` : "Change summary unavailable"}
            </div>
          </div>

          <div className="card" style={{ padding: 12 }}>
            <strong>Changed Files</strong>
            <div className="analyzer-overview-list">
              {overviewChangedFiles.length > 0 ? (
                overviewChangedFiles.slice(0, 6).map((file) => (
                  <div key={file} className="hint">{file}</div>
                ))
              ) : (
                <div className="empty">No changed files in the latest recorded run.</div>
              )}
            </div>
          </div>

          <div className="card" style={{ padding: 12 }}>
            <strong>Changed Functions</strong>
            <div className="analyzer-overview-list">
              {overviewChangedFunctions.length > 0 ? (
                overviewChangedFunctions.slice(0, 8).map(([name, kind]) => (
                  <button
                    key={name}
                    type="button"
                    className="row analyzer-overview-function-row"
                    style={{ justifyContent: "space-between", gap: 8 }}
                    onClick={() => openAppliedArtifact("uds", name)}
                  >
                    <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{name}</span>
                    <span className="badge">{kind}</span>
                  </button>
                ))
              ) : (
                <div className="empty">No changed functions recorded yet.</div>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="card analyzer-overview-card" style={{ padding: 14, marginBottom: 12 }}>
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div>
            <strong>Analyzer Global Context</strong>
            <div className="hint analyzer-mode-banner-hint">공통 문서 경로를 한 번만 불러오고 UDS, STS, SUTS 탭에서 같이 사용합니다.</div>
          </div>
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <span className="badge">{mode === "jenkins" ? "JENKINS CONTEXT" : "LOCAL CONTEXT"}</span>
            <button type="button" className="btn-outline" onClick={() => setShowGlobalContext((value) => !value)}>
              {showGlobalContext ? "Hide Context" : "Open Context"}
            </button>
          </div>
        </div>
        <div className="row" style={{ gap: 8, flexWrap: "wrap", marginTop: 10 }}>
          {commonContextChecks.map((item) => (
            <span key={item.label} className={`badge ${item.ok ? "qa-pass" : "qa-check"}`}>
              {item.label}: {item.ok ? "OK" : "MISSING"}
            </span>
          ))}
        </div>
        {showGlobalContext ? (
          <div className="form-grid-2 compact" style={{ marginTop: 12 }}>
            <label>Source Root</label>
            <div className="row" style={{ gap: 8 }}>
              <input value={sourceRoot || ""} onChange={(e) => (typeof setSourceRoot === "function" ? setSourceRoot(e.target.value) : null)} placeholder="Common source root" />
              {typeof pickDirectory === "function" ? (
                <button type="button" className="btn-outline" onClick={async () => {
                  const picked = await pickDirectory("Select common source root");
                  if (picked && typeof setSourceRoot === "function") setSourceRoot(picked);
                }}>Browse</button>
              ) : null}
            </div>
            <label>SRS</label>
            <div className="row" style={{ gap: 8 }}>
              <input value={commonSrsPath} onChange={(e) => setCommonSrsPath(e.target.value)} placeholder="Common SRS path" />
              {typeof pickFile === "function" ? <button type="button" className="btn-outline" onClick={async () => {
                const picked = await pickFile("Select common SRS document");
                if (picked) setCommonSrsPath(String(picked));
              }}>Browse</button> : null}
            </div>
            <label>SDS</label>
            <div className="row" style={{ gap: 8 }}>
              <input value={commonSdsPath} onChange={(e) => setCommonSdsPath(e.target.value)} placeholder="Common SDS path" />
              {typeof pickFile === "function" ? <button type="button" className="btn-outline" onClick={async () => {
                const picked = await pickFile("Select common SDS document");
                if (picked) setCommonSdsPath(String(picked));
              }}>Browse</button> : null}
            </div>
            <label>HSIS</label>
            <div className="row" style={{ gap: 8 }}>
              <input value={commonHsisPath} onChange={(e) => setCommonHsisPath(e.target.value)} placeholder="Common HSIS path" />
              {typeof pickFile === "function" ? <button type="button" className="btn-outline" onClick={async () => {
                const picked = await pickFile("Select common HSIS document");
                if (picked) setCommonHsisPath(String(picked));
              }}>Browse</button> : null}
            </div>
            <label>UDS Reference</label>
            <div className="row" style={{ gap: 8 }}>
              <input value={commonUdsPath} onChange={(e) => setCommonUdsPath(e.target.value)} placeholder="Common UDS path" />
              {typeof pickFile === "function" ? <button type="button" className="btn-outline" onClick={async () => {
                const picked = await pickFile("Select common UDS document");
                if (picked) setCommonUdsPath(String(picked));
              }}>Browse</button> : null}
            </div>
          </div>
        ) : null}
      </div>

      <div className="analyzer-top-grid">
        <LatestRunCard
          items={summaryCards}
          onOpen={(artifact) => setArtifactType(artifact)}
          onPreviewReport={previewAbsReport}
          groupLabel={runGroupLabel}
        />

        <div className="card" style={{ padding: 14, marginBottom: 12 }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
            <strong>QA Checklist</strong>
            <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              <span className="hint">{qaChecks.filter((item) => item.ok).length}/{qaChecks.length} checks</span>
              <button type="button" className="btn-outline" onClick={() => setShowQaChecklist((value) => !value)}>
                {showQaChecklist ? "Hide Checklist" : "Open Checklist"}
              </button>
            </div>
          </div>
          {showQaChecklist ? (
            <div style={{ display: "grid", gap: 8, marginTop: 10 }}>
              {qaChecks.map((item) => (
                <div key={item.label} className="row" style={{ justifyContent: "space-between", gap: 12 }}>
                  <span className="hint">{item.label}</span>
                  <span className={`badge ${item.ok ? "qa-pass" : "qa-check"}`}>{item.ok ? "PASS" : "CHECK"}</span>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <div className="analyzer-mode-banner">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div>
            <strong>Document Workspace Controls</strong>
            <div className="hint analyzer-mode-banner-hint">
              Select a tab first, then use fullscreen to expand the current workspace.
            </div>
          </div>
          <button
            type="button"
            className="btn-outline"
            onClick={() => setFullscreenSection((prev) => (prev === artifactType ? "" : artifactType))}
          >
            {fullscreenSection === artifactType ? "Exit Fullscreen" : "Fullscreen"}
          </button>
        </div>
        <div className="segmented" style={{ marginTop: 12 }}>
          <button type="button" className={`segmented-btn ${artifactType === "impact" ? "active" : ""}`} onClick={() => setArtifactType("impact")}>Impact</button>
          <button type="button" className={`segmented-btn ${artifactType === "sds" ? "active" : ""}`} onClick={() => setArtifactType("sds")}>SDS</button>
          <button type="button" className={`segmented-btn ${artifactType === "uds" ? "active" : ""}`} onClick={() => setArtifactType("uds")}>UDS</button>
          <button type="button" className={`segmented-btn ${artifactType === "sts" ? "active" : ""}`} onClick={() => setArtifactType("sts")}>STS</button>
          <button type="button" className={`segmented-btn ${artifactType === "suts" ? "active" : ""}`} onClick={() => setArtifactType("suts")}>SUTS</button>
          <button type="button" className={`segmented-btn ${artifactType === "sits" ? "active" : ""}`} onClick={() => setArtifactType("sits")}>SITS</button>
        </div>
      </div>

      <div
        className={`analyzer-section-shell ${artifactType === "impact" ? "is-active" : ""} ${fullscreenSection === "impact" ? "is-fullscreen" : ""}`}
        style={{ display: artifactType === "impact" ? "" : "none" }}
      >
        <AnalyzerSectionToolbar
          title={mode === "jenkins" ? "Impact Workspace (Jenkins)" : "Impact Workspace (Local)"}
        />
        <>
          <div className="analyzer-mode-banner">
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <strong>{mode === "jenkins" ? "Analyzer Mode: Jenkins Impact" : "Analyzer Mode: Local Impact"}</strong>
              <span className="badge">{mode === "jenkins" ? "JENKINS" : "LOCAL"}</span>
            </div>
            <div className="hint analyzer-mode-banner-hint">
              Analyzer 안에서 변경 감지, 영향 분석, AUTO/FLAG 결과 확인, 생성 이후 결과 추적까지 한 흐름으로 처리합니다.
            </div>
          </div>
          {mode === "jenkins" ? (
            <JenkinsImpactPanel
              jenkinsJobUrl={jenkinsJobUrl}
              setJenkinsJobUrl={setJenkinsJobUrl}
              jenkinsCacheRoot={jenkinsCacheRoot}
              setJenkinsCacheRoot={setJenkinsCacheRoot}
              jenkinsBuildSelector={jenkinsBuildSelector}
              setJenkinsBuildSelector={setJenkinsBuildSelector}
            />
          ) : (
            <LocalScmPanel
              scmMode={scmMode}
              setScmMode={setScmMode}
              scmWorkdir={scmWorkdir}
              setScmWorkdir={setScmWorkdir}
              scmRepoUrl={scmRepoUrl}
              setScmRepoUrl={setScmRepoUrl}
              scmBranch={scmBranch}
              setScmBranch={setScmBranch}
              scmDepth={scmDepth}
              setScmDepth={setScmDepth}
              scmRevision={scmRevision}
              setScmRevision={setScmRevision}
              runScm={runScm}
              scmOutput={scmOutput}
              onImpactComplete={refreshOverview}
            />
          )}
        </>
      </div>

      <div
        className={`analyzer-section-shell ${artifactType === "uds" ? "is-active" : ""} ${fullscreenSection === "uds" ? "is-fullscreen" : ""}`}
        style={{ display: artifactType === "uds" ? "" : "none" }}
      >
        <AnalyzerSectionToolbar
          title={`UDS Document (${udsDocMode === "applied" ? "Applied" : "Current"})`}
        />
        <>
          <div className="analyzer-mode-banner">
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <strong>UDS Context Status</strong>
              <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
                <span className={`badge ${udsContextState.sourceRoot === "COMMON" ? "qa-pass" : "qa-check"}`}>
                  Source Root: {udsContextState.sourceRoot}
                </span>
                <span className={`badge ${String(commonSrsPath || "").trim() ? "qa-pass" : "qa-check"}`}>
                  SRS: {String(commonSrsPath || "").trim() ? "COMMON" : "MISSING"}
                </span>
                <span className={`badge ${String(commonSdsPath || "").trim() ? "qa-pass" : "qa-check"}`}>
                  SDS: {String(commonSdsPath || "").trim() ? "COMMON" : "MISSING"}
                </span>
                <span className={`badge ${String(commonUdsPath || "").trim() ? "qa-pass" : "qa-check"}`}>
                  UDS Ref: {String(commonUdsPath || "").trim() ? "COMMON" : "MISSING"}
                </span>
              </div>
            </div>
          </div>
          <div className="row">
            <div className="segmented-group">
              <button type="button" className={`segmented-btn ${udsDocMode === "current" ? "active" : ""}`} onClick={() => setUdsDocMode("current")}>
                Current
              </button>
              <button type="button" className={`segmented-btn ${udsDocMode === "applied" ? "active" : ""}`} onClick={() => setUdsDocMode("applied")}>
                Applied
              </button>
            </div>
            <select value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
              <option value="local">Local UDS</option>
              <option value="jenkins">Jenkins UDS</option>
            </select>
            {udsDocMode === "applied" ? (
              <select value={docScmId} onChange={(e) => setDocScmId(e.target.value)}>
                <option value="">SCM Registry</option>
                {docRegistryItems.map((item) => (
                  <option key={item.id} value={item.id}>{item.name || item.id}</option>
                ))}
              </select>
            ) : null}
            <button
              type="button"
              className="btn-outline"
              onClick={() => setGenShowAdvancedOverrides((value) => !value)}
            >
              {genShowAdvancedOverrides ? "Hide Advanced" : "Advanced Overrides"}
            </button>
          </div>
          {genShowAdvancedOverrides ? (
            <div className="card" style={{ padding: 12, marginBottom: 12, display: "grid", gap: 10 }}>
              <div className="hint">
                Analyzer Global Context is the default. Use overrides here only when you need a different source root, Jenkins source, or uploaded legacy documents.
              </div>
              {!isLocal ? (
                <div className="form-grid-2 compact">
                  <label>Jenkins Job URL</label>
                  <input placeholder="Jenkins Job URL" value={jenkinsJobUrl} onChange={(e) => (typeof setJenkinsJobUrl === "function" ? setJenkinsJobUrl(e.target.value) : null)} />
                  <label>Jenkins Cache Root</label>
                  <input placeholder="Jenkins Cache Root" value={jenkinsCacheRoot} onChange={(e) => (typeof setJenkinsCacheRoot === "function" ? setJenkinsCacheRoot(e.target.value) : null)} />
                </div>
              ) : null}
              <div>
                <label>Code Source Root</label>
                <div className="row" style={{ gap: 6 }}>
                  <input placeholder="Code Source Root" value={sourceRoot} onChange={(e) => (typeof setSourceRoot === "function" ? setSourceRoot(e.target.value) : null)} />
                  {typeof pickDirectory === "function" ? (
                    <button type="button" className="btn-outline" onClick={async () => {
                      const picked = await pickDirectory("Select source root");
                      if (picked && typeof setSourceRoot === "function") setSourceRoot(picked);
                    }}>Browse</button>
                  ) : null}
                </div>
              </div>
            </div>
          ) : null}
          {udsDocMode === "applied" ? (
            <div className="card" style={{ padding: 14, marginBottom: 12 }}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                <strong>UDS Applied Change History</strong>
                <span className="hint">{udsChangeHistoryLoading ? "loading..." : `${udsChangeHistoryItems.length} runs`}</span>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 300px) minmax(0, 1fr)", gap: 12, marginTop: 12, alignItems: "stretch" }}>
                <div className="card" style={{ padding: 10, maxHeight: 380, overflow: "auto" }}>
                  {udsChangeHistoryItems.length > 0 ? (
                    udsChangeHistoryItems.map((item) => (
                      <button
                        key={item.run_id}
                        type="button"
                        className={`latest-run-entry ${udsSelectedRunId === item.run_id ? "is-selected" : ""}`}
                        onClick={() => setUdsSelectedRunId(item.run_id)}
                        style={{ width: "100%", textAlign: "left", marginBottom: 8 }}
                      >
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontWeight: 600 }}>{item.run_id}</div>
                          <div className="hint">{item.timestamp || "-"}</div>
                          <div className="hint">UDS {item.summary?.uds_changed_functions || 0} / SUTS {item.summary?.suts_changed_cases || 0}</div>
                        </div>
                        <span className="badge">{item.dry_run ? "DRY" : "RUN"}</span>
                      </button>
                    ))
                  ) : (
                    <div className="empty">적용된 UDS 변경 이력이 없습니다.</div>
                  )}
                </div>
              <div className="card" style={{ padding: 10 }} ref={udsAppliedDiffRef}>
                <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                  <strong>Applied Diff</strong>
                  <span className="hint">{udsSelectedChangeDetail?.run_id || "select run"}</span>
                </div>
                {udsSelectedChangeDetail ? (
                  <>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 8, marginTop: 10 }}>
                        <div className="card" style={{ padding: 10 }}>
                          <div className="hint">Changed Files</div>
                          <div style={{ fontWeight: 700 }}>{Array.isArray(udsSelectedChangeDetail.changed_files) ? udsSelectedChangeDetail.changed_files.length : 0}</div>
                        </div>
                        <div className="card" style={{ padding: 10 }}>
                          <div className="hint">UDS Functions</div>
                          <div style={{ fontWeight: 700 }}>{udsSelectedChangeDetail.summary?.uds_changed_functions || 0}</div>
                        </div>
                        <div className="card" style={{ padding: 10 }}>
                          <div className="hint">STS Flagged</div>
                          <div style={{ fontWeight: 700 }}>{udsSelectedChangeDetail.summary?.sts_flagged || 0}</div>
                        </div>
                        <div className="card" style={{ padding: 10 }}>
                          <div className="hint">SDS Flagged</div>
                          <div style={{ fontWeight: 700 }}>{udsSelectedChangeDetail.summary?.sds_flagged || 0}</div>
                        </div>
                      </div>
                      <div className="card" style={{ padding: 10, marginTop: 12 }}>
                        <div style={{ fontWeight: 600, marginBottom: 6 }}>검토 가이드</div>
                        <div style={{ display: "grid", gap: 6 }}>
                          {getUdsGuidanceKo(udsSelectedChangeDetail).map((line, idx) => (
                            <div key={`uds-guide-${idx}`} className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{line}</div>
                          ))}
                        </div>
                      </div>
                      <div className="card" style={{ padding: 10, marginTop: 12 }}>
                        <div style={{ fontWeight: 600, marginBottom: 6 }}>변경 파일</div>
                        <div style={{ display: "grid", gap: 4 }}>
                          {Array.isArray(udsSelectedChangeDetail.changed_files) && udsSelectedChangeDetail.changed_files.length > 0 ? (
                            udsSelectedChangeDetail.changed_files.map((file) => (
                              <div key={file} className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{file}</div>
                            ))
                          ) : (
                            <div className="empty">변경 파일 정보가 없습니다.</div>
                          )}
                        </div>
                      </div>
                      <div className="card" style={{ padding: 10, marginTop: 12 }}>
                        <div style={{ fontWeight: 600, marginBottom: 6 }}>변경 함수 / 유형</div>
                        <div style={{ display: "grid", gap: 8 }}>
                          {udsSelectedChangeDetail?.changed_functions && typeof udsSelectedChangeDetail.changed_functions === "object" ? (
                            Object.entries(udsSelectedChangeDetail.changed_functions).map(([name, kind]) => (
                              <div key={name} className={`card ${focusedChangeFunction && name === focusedChangeFunction ? "latest-run-entry is-focused" : ""}`} style={{ padding: 10 }}>
                                <div style={{ fontWeight: 600 }}>{name}</div>
                                <div className="hint">변경 유형: {String(kind || "-").toUpperCase()}</div>
                              </div>
                            ))
                          ) : (
                            <div className="empty">변경 함수 정보가 없습니다.</div>
                          )}
                        </div>
                      </div>
                      <div className="card" style={{ padding: 10, marginTop: 12 }}>
                        <div style={{ fontWeight: 600, marginBottom: 6 }}>변경 필드 상세</div>
                        <div style={{ display: "grid", gap: 8 }}>
                          {Array.isArray(udsSelectedChangeDetail?.documents?.uds?.changed_functions) &&
                          udsSelectedChangeDetail.documents.uds.changed_functions.length > 0 ? (
                            udsSelectedChangeDetail.documents.uds.changed_functions.map((row) => (
                              <div key={row.name} className={`card ${focusedChangeFunction && row.name === focusedChangeFunction ? "latest-run-entry is-focused" : ""}`} style={{ padding: 10, minWidth: 0 }}>
                                <div style={{ fontWeight: 600 }}>{row.name}</div>
                                <div className="hint">{Array.isArray(row.fields_changed) ? row.fields_changed.join(", ") : "-"}</div>
                                <div className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{summarizeUdsDiff(row)}</div>
                              </div>
                            ))
                          ) : (
                            <div className="empty">선택한 run에 대한 UDS diff 행이 없습니다.</div>
                          )}
                        </div>
                      </div>
                    </>
                  ) : (
                    <div className="empty" style={{ marginTop: 12 }}>run을 선택하면 적용된 UDS 변경 내용을 확인할 수 있습니다.</div>
                  )}
                </div>
              </div>
            </div>
          ) : null}
          <div className={`analyzer-status-panel tone-${analyzerStatus.tone}`}>{analyzerStatus.text}</div>
          <div className="uds-op-panel">
            <div className="uds-op-row"><span className="detail-label">Operation</span><span className="detail-value">{opStep}</span></div>
            <div className="uds-op-progress"><div className="uds-op-progress-bar" style={{ width: `${Math.max(0, Math.min(100, opProgress))}%` }} /></div>
            <div className="uds-op-log">{opLogs.length > 0 ? opLogs.join("\n") : "Operation logs will appear here."}</div>
          </div>
          {isLocal ? (
            <div className="card" style={{ padding: 14, marginBottom: 12 }}>
              <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <div>
                  <strong>Advanced UDS Generate</strong>
                  <div className="hint" style={{ marginTop: 4 }}>
                    기본 화면에서는 문서 열람에 집중하고, 생성 옵션은 필요할 때만 엽니다.
                  </div>
                </div>
                <button type="button" className="btn-outline" onClick={() => setShowUdsGeneratePanel((value) => !value)}>
                  {showUdsGeneratePanel ? "Hide Generate" : "Open Generate"}
                </button>
              </div>
              {showUdsGeneratePanel ? (
                <div className="panel" style={{ marginTop: 12 }}>
                  <div className="row" style={{ justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                    <h4 style={{ margin: 0 }}>UDS Generate</h4>
                    <button type="button" className="btn-outline" onClick={() => setGenShowAdvancedOverrides((value) => !value)}>
                      {genShowAdvancedOverrides ? "Hide Overrides" : "Advanced Overrides"}
                    </button>
                  </div>
                  <div className="hint" style={{ marginBottom: 10 }}>
                    Uses Analyzer Global Context by default. Test mode keeps full report generation and now uses much longer timeouts.
                  </div>
                  {genShowAdvancedOverrides ? (
                    <>
                      <label>SRS document override</label>
                      <input type="file" accept=".docx,.pdf,.xlsx,.xls,.txt,.md" onChange={(e) => setGenSrsDoc(e.target.files?.[0] || null)} />
                      <label>SDS document override</label>
                      <input type="file" accept=".docx,.pdf,.xlsx,.xls,.txt,.md" onChange={(e) => setGenSdsDoc(e.target.files?.[0] || null)} />
                      <label>Reference UDS override</label>
                      <input type="file" accept=".docx,.pdf,.txt,.md" onChange={(e) => setGenRefUdsDoc(e.target.files?.[0] || null)} />
                      <label>UDS template override</label>
                      <input type="file" accept=".docx" onChange={(e) => setGenTemplateDoc(e.target.files?.[0] || null)} />
                    </>
                  ) : null}
                  <label className="row" style={{ gap: 6 }}><input type="checkbox" checked={genTestMode} onChange={(e) => setGenTestMode(Boolean(e.target.checked))} />Test mode</label>
                  <label className="row" style={{ gap: 6 }}><input type="checkbox" checked={genShowMappingEvidence} onChange={(e) => setGenShowMappingEvidence(Boolean(e.target.checked))} />Show mapping evidence</label>
                  <div className="row"><button type="button" onClick={runGenerateLocal} disabled={genLoading}>{genLoading ? "Generating..." : "Generate UDS"}</button></div>
                </div>
              ) : null}
            </div>
          ) : null}
          <UdsViewerWorkspace
            title={analyzerTitle}
            files={files}
            selectedFilename={selectedFilename}
            onSelectedFilenameChange={setSelectedFilename}
            onRefreshFiles={loadFiles}
            onPickFile={pickUdsFile}
            filesLoading={filesLoading}
            filesError={filesError}
            onLoadView={loadView}
            viewData={viewData}
            viewLoading={viewLoading}
            viewError={viewError}
            urlStateKey={`analyzer_${sourceType}`}
            sourceRoot={currentSourceRoot}
          />
          <TraceabilityPanel
            sourceRoot={currentSourceRoot}
            pickDirectory={typeof pickDirectory === "function" ? async () => ({ path: await pickDirectory("Select path") }) : undefined}
            pickFile={typeof pickFile === "function" ? async (label) => pickFile(label || "Select requirement document") : undefined}
          />
        </>
      </div>

      <div
        className={`analyzer-section-shell ${artifactType === "sts" ? "is-active" : ""} ${fullscreenSection === "sts" ? "is-fullscreen" : ""}`}
        style={{ display: artifactType === "sts" ? "" : "none" }}
      >
        <AnalyzerSectionToolbar
          title={`STS Document (${stsDocMode === "applied" ? "Applied" : "Current"})`}
        />
        <div className="analyzer-mode-banner">
          <div style={{ display: "grid", gap: 10 }}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <strong>STS Context Status</strong>
              <button type="button" className="btn-outline" onClick={applyCommonContextToSts}>Apply Common Context</button>
            </div>
            <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              <span className={`badge ${stsContextState.sourceRoot === "COMMON" ? "qa-pass" : "qa-check"}`}>Source Root: {stsContextState.sourceRoot}</span>
              <span className={`badge ${stsContextState.srs === "COMMON" ? "qa-pass" : "qa-check"}`}>SRS: {stsContextState.srs}</span>
              <span className={`badge ${stsContextState.sds === "COMMON" ? "qa-pass" : "qa-check"}`}>SDS: {stsContextState.sds}</span>
              <span className={`badge ${stsContextState.hsis === "COMMON" ? "qa-pass" : "qa-check"}`}>HSIS: {stsContextState.hsis}</span>
              <span className={`badge ${stsContextState.uds === "COMMON" ? "qa-pass" : "qa-check"}`}>UDS: {stsContextState.uds}</span>
            </div>
          </div>
        </div>
        <div className="row" style={{ marginBottom: 12 }}>
          <div className="segmented-group">
            <button type="button" className={`segmented-btn ${stsDocMode === "current" ? "active" : ""}`} onClick={() => setStsDocMode("current")}>
              Current
            </button>
            <button type="button" className={`segmented-btn ${stsDocMode === "applied" ? "active" : ""}`} onClick={() => setStsDocMode("applied")}>
              Applied
            </button>
          </div>
          {stsDocMode === "applied" ? (
            <select value={docScmId} onChange={(e) => setDocScmId(e.target.value)}>
              <option value="">SCM Registry</option>
              {docRegistryItems.map((item) => (
                <option key={item.id} value={item.id}>{item.name || item.id}</option>
              ))}
            </select>
          ) : null}
        </div>
        {stsDocMode === "applied" ? (
          <div className="card" style={{ padding: 14, marginBottom: 12 }}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <strong>STS Applied Change History</strong>
              <span className="hint">{stsChangeHistoryLoading ? "loading..." : `${stsChangeHistoryItems.length} runs`}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(200px, 280px) minmax(0, 1fr)", gap: 12, marginTop: 12, alignItems: "stretch" }}>
              <div className="card" style={{ padding: 10, maxHeight: 520, minHeight: 520, overflow: "auto" }}>
                {stsChangeHistoryItems.length > 0 ? (
                  stsChangeHistoryItems.map((item) => (
                    <button
                      key={item.run_id}
                      type="button"
                      className={`latest-run-entry ${stsSelectedRunId === item.run_id ? "is-selected" : ""}`}
                      onClick={() => setStsSelectedRunId(item.run_id)}
                      style={{ width: "100%", textAlign: "left", marginBottom: 8 }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 600 }}>{item.run_id}</div>
                        <div className="hint">{item.timestamp || "-"}</div>
                        <div className="hint">STS {item.summary?.sts_flagged || 0} / SDS {item.summary?.sds_flagged || 0}</div>
                      </div>
                      <span className="badge">{item.dry_run ? "DRY" : "RUN"}</span>
                    </button>
                  ))
                ) : (
                  <div className="empty">적용된 STS 변경 이력이 없습니다.</div>
                )}
              </div>
              <div className="card" style={{ padding: 10, minWidth: 0, maxHeight: 520, minHeight: 520, overflow: "auto" }} ref={stsAppliedReviewRef}>
                <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                  <strong>Applied Review</strong>
                  <span className="hint">{stsSelectedChangeDetail?.run_id || "select run"}</span>
                </div>
                {stsSelectedChangeDetail ? (
                  <>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 8, marginTop: 10 }}>
                      <div className="card" style={{ padding: 10 }}>
                        <div className="hint">Changed Files</div>
                        <div style={{ fontWeight: 700 }}>{Array.isArray(stsSelectedChangeDetail.changed_files) ? stsSelectedChangeDetail.changed_files.length : 0}</div>
                      </div>
                      <div className="card" style={{ padding: 10 }}>
                        <div className="hint">STS Flagged</div>
                        <div style={{ fontWeight: 700 }}>{stsSelectedChangeDetail.summary?.sts_flagged || 0}</div>
                      </div>
                      <div className="card" style={{ padding: 10 }}>
                        <div className="hint">SDS Flagged</div>
                        <div style={{ fontWeight: 700 }}>{stsSelectedChangeDetail.summary?.sds_flagged || 0}</div>
                      </div>
                    </div>
                    <div className="card" style={{ padding: 10, marginTop: 12, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>Review Guidance</div>
                      <div style={{ display: "grid", gap: 6 }}>
                        {getStsGuidanceKo(stsSelectedChangeDetail).map((line, idx) => (
                          <div key={`guide-${idx}`} className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>
                            {line}
                          </div>
                        ))}
                      </div>
                    </div>
                    {getStsReviewCategoriesKo(stsSelectedChangeDetail).length > 0 ? (
                      <div className="card" style={{ padding: 10, marginTop: 12, minWidth: 0 }}>
                        <div style={{ fontWeight: 600, marginBottom: 6 }}>리뷰 분류</div>
                        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                          {getStsReviewCategoriesKo(stsSelectedChangeDetail).map((label) => (
                            <span key={`sts-category-${label}`} className="badge tone-warn">{label}</span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {focusedChangeFunction ? (
                      <div className="card" style={{ padding: 10, marginTop: 12, minWidth: 0 }}>
                        <div style={{ fontWeight: 600, marginBottom: 6 }}>점프 대상 함수</div>
                        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <div className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{focusedChangeFunction}</div>
                          <span className={`badge ${Object.keys(stsSelectedChangeDetail?.changed_functions || {}).includes(focusedChangeFunction) ? "tone-accent" : ""}`}>
                            {Object.keys(stsSelectedChangeDetail?.changed_functions || {}).includes(focusedChangeFunction) ? "현재 run과 연결됨" : "목록에서 관련 항목 확인"}
                          </span>
                        </div>
                      </div>
                    ) : null}
                    <div className="card" style={{ padding: 10, marginTop: 12, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>Changed Files</div>
                      <div style={{ display: "grid", gap: 4 }}>
                        {Array.isArray(stsSelectedChangeDetail.changed_files) && stsSelectedChangeDetail.changed_files.length > 0 ? (
                          stsSelectedChangeDetail.changed_files.map((file) => (
                            <div key={file} className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{file}</div>
                          ))
                        ) : (
                          <div className="empty">변경 파일 기록이 없습니다.</div>
                        )}
                      </div>
                    </div>
                    <div className="card" style={{ padding: 10, marginTop: 12, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>Review Targets</div>
                      <div style={{ display: "grid", gap: 8 }}>
                        {stsReviewTargets.length > 0 ? (
                          stsReviewTargets.map((target) => (
                            <div
                              key={target.name}
                              className={`card ${target.isFocused ? "latest-run-entry is-focused" : ""}`}
                              style={{ padding: 10, minWidth: 0, width: "100%", boxSizing: "border-box", overflow: "hidden" }}
                            >
                              <div style={{ display: "grid", gap: 10, minWidth: 0 }}>
                                <div style={{ minWidth: 0, overflow: "hidden" }}>
                                  <div style={{ fontWeight: 600 }}>{target.name}</div>
                                  <div className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>
                                    {target.kind ? `변경 유형: ${String(target.kind || "-").toUpperCase()}` : "변경 유형 정보 없음"}
                                  </div>
                                  <div className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>
                                    {target.flagged ? "STS 리뷰 필요" : "리뷰 대상 아님"}
                                  </div>
                                </div>
                                <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", minWidth: 0, maxWidth: "100%", overflow: "hidden" }}>
                                  {target.kind ? <span className="badge">{String(target.kind || "-").toUpperCase()}</span> : null}
                                  {target.flagged ? <span className="badge">STS</span> : null}
                                  {target.isFocused ? <span className="badge tone-accent">JUMP</span> : null}
                                </div>
                                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                                  {target.reviewCategories.map((label) => (
                                    <span key={`${target.name}-${label}`} className="badge tone-warn">{label}</span>
                                  ))}
                                </div>
                                {target.artifactMatches.length > 0 ? (
                                  <div style={{ display: "grid", gap: 6 }}>
                                    {target.artifactMatches.map((line, idx) => (
                                      <div key={`${target.name}-artifact-${idx}`} className="card" style={{ padding: 8, whiteSpace: "normal", overflowWrap: "anywhere" }}>
                                        {line}
                                      </div>
                                    ))}
                                  </div>
                                ) : null}
                              </div>
                            </div>
                          ))
                        ) : (
                          <div className="empty">선택한 run에 대한 변경 함수 메타데이터가 없습니다.</div>
                        )}
                      </div>
                    </div>
                    {stsSelectedChangeDetail?.documents?.sts?.artifact_path ? (
                      <div style={{ marginTop: 12 }}>
                        <button
                          type="button"
                          className="btn-outline"
                          onClick={() => previewAbsReport(stsSelectedChangeDetail.documents.sts.artifact_path, "STS Review Artifact")}
                        >
                          STS Review Artifact 미리보기
                        </button>
                      </div>
                    ) : null}
                    <div className="card" style={{ padding: 10, marginTop: 12, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>연결된 Review Artifact</div>
                      {stsArtifactLoading ? (
                        <div className="hint">관련 artifact 내용을 찾는 중입니다...</div>
                      ) : selectedStsArtifactMatches.length > 0 ? (
                        <div style={{ display: "grid", gap: 8 }}>
                          {selectedStsArtifactMatches.map((line, idx) => (
                            <div key={`sts-artifact-${idx}`} className="card" style={{ padding: 8, whiteSpace: "normal", overflowWrap: "anywhere" }}>
                              {line}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="hint">현재 run에서 직접 연결된 STS artifact 문장을 찾지 못했습니다.</div>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="empty" style={{ marginTop: 12 }}>run을 선택하면 적용된 STS 변경 내용을 확인할 수 있습니다.</div>
                )}
              </div>
            </div>
          </div>
        ) : null}
        <div className="card" style={{ padding: 14, marginBottom: 12 }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <div>
              <strong>Advanced STS Generate</strong>
              <div className="hint" style={{ marginTop: 4 }}>
                기본 화면에서는 문서 열람과 Applied Review에 집중하고, 생성 옵션은 필요할 때만 엽니다.
              </div>
            </div>
            <button type="button" className="btn-outline" onClick={() => setShowStsGeneratePanel((value) => !value)}>
              {showStsGeneratePanel ? "Hide Generate" : "Open Generate"}
            </button>
          </div>
          {showStsGeneratePanel ? (
            <div style={{ marginTop: 12 }}>
              <StsGeneratorPanel
                pickDirectory={pickDirectory}
                pickFile={pickFile}
                isJenkins={isJenkins}
                sourceRoot={stsSourceRoot}
                onSourceRootChange={setStsSourceRoot}
                srsPath={stsSrsPath}
                onSrsPathChange={setStsSrsPath}
                sdsPath={stsSdsPath}
                onSdsPathChange={setStsSdsPath}
                hsisPath={stsHsisPath}
                onHsisPathChange={setStsHsisPath}
                udsPath={stsUdsPath}
                onUdsPathChange={setStsUdsPath}
                stpPath={stsStpPath}
                onStpPathChange={setStsStpPath}
                templatePath={stsTemplatePath}
                onTemplatePathChange={setStsTemplatePath}
                projectId={stsProjectId}
                onProjectIdChange={setStsProjectId}
                version={stsVersion}
                onVersionChange={setStsVersion}
                asilLevel={stsAsilLevel}
                onAsilLevelChange={setStsAsilLevel}
                maxTc={stsMaxTc}
                onMaxTcChange={setStsMaxTc}
                loading={stsLoading}
                notice={stsNotice}
                progressPct={stsProgressPct}
                progressMsg={stsProgressMsg}
                files={stsFiles}
                filesLoading={stsFilesLoading}
                viewData={stsViewData}
                previewData={stsPreviewData}
                previewLoading={stsPreviewLoading}
                previewSheet={stsPreviewSheet}
                onPreviewSheetChange={setStsPreviewSheet}
                onGenerate={handleStsGenerate}
                onRefreshFiles={loadStsFiles}
                onOpenFile={loadStsView}
                onLoadPreview={loadStsPreview}
              />
            </div>
          ) : null}
        </div>
      </div>

      <div
        className={`analyzer-section-shell ${artifactType === "suts" ? "is-active" : ""} ${fullscreenSection === "suts" ? "is-fullscreen" : ""}`}
        style={{ display: artifactType === "suts" ? "" : "none" }}
      >
        <AnalyzerSectionToolbar
          title={`SUTS Document (${sutsDocMode === "applied" ? "Applied" : "Current"})`}
        />
        <div className="analyzer-mode-banner">
          <div style={{ display: "grid", gap: 10 }}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <strong>SUTS Context Status</strong>
              <button type="button" className="btn-outline" onClick={applyCommonContextToSuts}>Apply Common Context</button>
            </div>
            <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              <span className={`badge ${sutsContextState.sourceRoot === "COMMON" ? "qa-pass" : "qa-check"}`}>Source Root: {sutsContextState.sourceRoot}</span>
              <span className={`badge ${sutsContextState.srs === "COMMON" ? "qa-pass" : "qa-check"}`}>SRS: {sutsContextState.srs}</span>
              <span className={`badge ${sutsContextState.sds === "COMMON" ? "qa-pass" : "qa-check"}`}>SDS: {sutsContextState.sds}</span>
              <span className={`badge ${sutsContextState.hsis === "COMMON" ? "qa-pass" : "qa-check"}`}>HSIS: {sutsContextState.hsis}</span>
              <span className={`badge ${sutsContextState.uds === "COMMON" ? "qa-pass" : "qa-check"}`}>UDS: {sutsContextState.uds}</span>
            </div>
          </div>
        </div>
        <div className="row" style={{ marginBottom: 12 }}>
          <div className="segmented-group">
            <button type="button" className={`segmented-btn ${sutsDocMode === "current" ? "active" : ""}`} onClick={() => setSutsDocMode("current")}>
              Current
            </button>
            <button type="button" className={`segmented-btn ${sutsDocMode === "applied" ? "active" : ""}`} onClick={() => setSutsDocMode("applied")}>
              Applied
            </button>
          </div>
          {sutsDocMode === "applied" ? (
            <select value={docScmId} onChange={(e) => setDocScmId(e.target.value)}>
              <option value="">SCM Registry</option>
              {docRegistryItems.map((item) => (
                <option key={item.id} value={item.id}>{item.name || item.id}</option>
              ))}
            </select>
          ) : null}
        </div>
        {sutsDocMode === "applied" ? (
          <div className="card" style={{ padding: 14, marginBottom: 12 }}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <strong>SUTS Applied Change History</strong>
              <span className="hint">{sutsChangeHistoryLoading ? "loading..." : `${sutsChangeHistoryItems.length} runs`}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 300px) minmax(0, 1fr)", gap: 12, marginTop: 12, alignItems: "stretch" }}>
              <div className="card" style={{ padding: 10, maxHeight: 520, minHeight: 520, overflow: "auto" }}>
                {sutsChangeHistoryItems.length > 0 ? (
                  sutsChangeHistoryItems.map((item) => (
                    <button
                      key={item.run_id}
                      type="button"
                      className={`latest-run-entry ${sutsSelectedRunId === item.run_id ? "is-selected" : ""}`}
                      onClick={() => setSutsSelectedRunId(item.run_id)}
                      style={{ width: "100%", textAlign: "left", marginBottom: 8 }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 600 }}>{item.run_id}</div>
                        <div className="hint">{item.timestamp || "-"}</div>
                        <div className="hint">SUTS {item.summary?.suts_changed_cases || 0} / Seq {item.summary?.suts_changed_sequences || 0}</div>
                      </div>
                      <span className="badge">{item.dry_run ? "DRY" : "RUN"}</span>
                    </button>
                  ))
                ) : (
                  <div className="empty">적용된 SUTS 변경 이력이 없습니다.</div>
                )}
              </div>
              <div className="card" style={{ padding: 10, minWidth: 0, maxHeight: 520, minHeight: 520, overflow: "auto" }} ref={sutsAppliedDiffRef}>
                <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                  <strong>Applied Diff</strong>
                  <span className="hint">{sutsSelectedChangeDetail?.run_id || "select run"}</span>
                </div>
                {sutsSelectedChangeDetail ? (
                  <>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 8, marginTop: 10 }}>
                      <div className="card" style={{ padding: 10 }}>
                        <div className="hint">Changed Files</div>
                        <div style={{ fontWeight: 700 }}>{Array.isArray(sutsSelectedChangeDetail.changed_files) ? sutsSelectedChangeDetail.changed_files.length : 0}</div>
                      </div>
                      <div className="card" style={{ padding: 10 }}>
                        <div className="hint">Changed Cases</div>
                        <div style={{ fontWeight: 700 }}>{sutsSelectedChangeDetail.summary?.suts_changed_cases || 0}</div>
                      </div>
                      <div className="card" style={{ padding: 10 }}>
                        <div className="hint">Sequences</div>
                        <div style={{ fontWeight: 700 }}>{sutsSelectedChangeDetail.summary?.suts_changed_sequences || 0}</div>
                      </div>
                    </div>
                    <div className="card" style={{ padding: 10, marginTop: 12 }}>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>검토 가이드</div>
                      <div style={{ display: "grid", gap: 6 }}>
                        {getSutsGuidanceKo(sutsSelectedChangeDetail).map((line, idx) => (
                          <div key={`suts-guide-${idx}`} className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{line}</div>
                        ))}
                      </div>
                    </div>
                    {getSutsReviewCategoriesKo(sutsSelectedChangeDetail).length > 0 ? (
                      <div className="card" style={{ padding: 10, marginTop: 12 }}>
                        <div style={{ fontWeight: 600, marginBottom: 6 }}>리뷰 분류</div>
                        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                          {getSutsReviewCategoriesKo(sutsSelectedChangeDetail).map((label) => (
                            <span key={`suts-category-${label}`} className="badge tone-warn">{label}</span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {focusedChangeFunction ? (
                      <div className="card" style={{ padding: 10, marginTop: 12 }}>
                        <div style={{ fontWeight: 600, marginBottom: 6 }}>점프 대상 함수</div>
                        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <div className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{focusedChangeFunction}</div>
                          <span className={`badge ${Object.keys(sutsSelectedChangeDetail?.changed_functions || {}).includes(focusedChangeFunction) ? "tone-accent" : ""}`}>
                            {Object.keys(sutsSelectedChangeDetail?.changed_functions || {}).includes(focusedChangeFunction) ? "현재 run과 연결됨" : "목록에서 관련 항목 확인"}
                          </span>
                        </div>
                      </div>
                    ) : null}
                    <div className="card" style={{ padding: 10, marginTop: 12 }}>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>변경 파일</div>
                      <div style={{ display: "grid", gap: 4 }}>
                        {Array.isArray(sutsSelectedChangeDetail.changed_files) && sutsSelectedChangeDetail.changed_files.length > 0 ? (
                          sutsSelectedChangeDetail.changed_files.map((file) => (
                            <div key={file} className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{file}</div>
                          ))
                        ) : (
                          <div className="empty">변경 파일 정보가 없습니다.</div>
                        )}
                      </div>
                    </div>
                    <div className="card" style={{ padding: 10, marginTop: 12 }}>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>변경 함수 / 유형</div>
                      <div style={{ display: "grid", gap: 8 }}>
                        {sutsSelectedChangeDetail?.changed_functions && typeof sutsSelectedChangeDetail.changed_functions === "object" ? (
                          Object.entries(sutsSelectedChangeDetail.changed_functions).map(([name, kind]) => (
                            <div key={name} className={`card ${focusedChangeFunction && name === focusedChangeFunction ? "latest-run-entry is-focused" : ""}`} style={{ padding: 10 }}>
                              <div style={{ fontWeight: 600 }}>{name}</div>
                              <div className="hint">변경 유형: {String(kind || "-").toUpperCase()}</div>
                            </div>
                          ))
                        ) : (
                          <div className="empty">변경 함수 정보가 없습니다.</div>
                        )}
                      </div>
                    </div>
                    <div className="card" style={{ padding: 10, marginTop: 12 }}>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>재생성 대상 상세</div>
                      <div style={{ display: "grid", gap: 8 }}>
                        {sutsCaseGroups.length > 0 ? (
                          sutsCaseGroups.map((group) => (
                            <div key={group.functionName} className={`card ${group.isFocused ? "latest-run-entry is-focused" : ""}`} style={{ padding: 10, minWidth: 0 }}>
                              <div style={{ display: "grid", gap: 10 }}>
                                <div>
                                  <div style={{ fontWeight: 600 }}>{group.functionName || "-"}</div>
                                  <div className="hint">변경 유형: {group.changeType ? String(group.changeType).toUpperCase() : "REGENERATED"}</div>
                                  <div className="hint">테스트케이스 {group.testcaseCount}건 / 시퀀스 {group.sequenceCount}건</div>
                                </div>
                                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                                  {getReviewCategoryHintsByKind(group.changeType, "suts").map((label) => (
                                    <span key={`${group.functionName}-${label}`} className="badge tone-warn">{label}</span>
                                  ))}
                                  {group.isFocused ? <span className="badge tone-accent">JUMP</span> : null}
                                </div>
                                <div style={{ display: "grid", gap: 6 }}>
                                  {group.cases.map((row, idx) => (
                                    <div key={`${group.functionName}-${row.testcase || "tc"}-${idx}`} className="card" style={{ padding: 8 }}>
                                      <div style={{ fontWeight: 600 }}>{row.testcase || "Unnamed Testcase"}</div>
                                      <div className="hint">변경 유형: {row.change_type || "regenerated"}</div>
                                      {row.sequence_no !== undefined ? <div className="hint">Sequence: {row.sequence_no}</div> : null}
                                    </div>
                                  ))}
                                </div>
                                {group.artifactMatches.length > 0 ? (
                                  <div style={{ display: "grid", gap: 6 }}>
                                    {group.artifactMatches.map((line, idx) => (
                                      <div key={`${group.functionName}-artifact-${idx}`} className="card" style={{ padding: 8, whiteSpace: "normal", overflowWrap: "anywhere" }}>
                                        {line}
                                      </div>
                                    ))}
                                  </div>
                                ) : null}
                              </div>
                            </div>
                          ))
                        ) : (
                          <div className="empty">선택한 run에 대한 SUTS diff 행이 없습니다.</div>
                        )}
                      </div>
                    </div>
                    {sutsSelectedChangeDetail?.documents?.suts?.validation_report_path ? (
                      <div style={{ marginTop: 12 }}>
                        <button
                          type="button"
                          className="btn-outline"
                          onClick={() => previewAbsReport(sutsSelectedChangeDetail.documents.suts.validation_report_path, "SUTS Validation Report")}
                        >
                          SUTS Validation 미리보기
                        </button>
                      </div>
                    ) : null}
                    <div className="card" style={{ padding: 10, marginTop: 12 }}>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>연결된 Validation Artifact</div>
                      {sutsArtifactLoading ? (
                        <div className="hint">관련 validation 내용을 찾는 중입니다...</div>
                      ) : selectedSutsArtifactMatches.length > 0 ? (
                        <div style={{ display: "grid", gap: 8 }}>
                          {selectedSutsArtifactMatches.map((line, idx) => (
                            <div key={`suts-artifact-${idx}`} className="card" style={{ padding: 8, whiteSpace: "normal", overflowWrap: "anywhere" }}>
                              {line}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="hint">현재 run에서 직접 연결된 SUTS validation 문장을 찾지 못했습니다.</div>
                      )}
                    </div>
                  </>
                ) : (
                  <div className="empty" style={{ marginTop: 12 }}>run을 선택하면 적용된 SUTS 변경 내용을 확인할 수 있습니다.</div>
                )}
              </div>
            </div>
          </div>
        ) : null}
        <div className="card" style={{ padding: 14, marginBottom: 12 }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <div>
              <strong>Advanced SUTS Generate</strong>
              <div className="hint" style={{ marginTop: 4 }}>
                기본 화면에서는 문서 열람과 Applied Diff에 집중하고, 생성 옵션은 필요할 때만 엽니다.
              </div>
            </div>
            <button type="button" className="btn-outline" onClick={() => setShowSutsGeneratePanel((value) => !value)}>
              {showSutsGeneratePanel ? "Hide Generate" : "Open Generate"}
            </button>
          </div>
          {showSutsGeneratePanel ? (
            <div style={{ marginTop: 12 }}>
              <SutsGeneratorPanel
                pickDirectory={pickDirectory}
                pickFile={pickFile}
                isJenkins={isJenkins}
                jenkinsJobUrl={jenkinsJobUrl}
                jenkinsCacheRoot={jenkinsCacheRoot}
                jenkinsBuildSelector={jenkinsBuildSelector}
                sourceRoot={sutsSourceRoot}
                onSourceRootChange={setSutsSourceRoot}
                srsPath={sutsSrsPath}
                onSrsPathChange={setSutsSrsPath}
                sdsPath={sutsSdsPath}
                onSdsPathChange={setSutsSdsPath}
                hsisPath={sutsHsisPath}
                onHsisPathChange={setSutsHsisPath}
                udsPath={sutsUdsPath}
                onUdsPathChange={setSutsUdsPath}
                templatePath={sutsTemplatePath}
                onTemplatePathChange={setSutsTemplatePath}
                projectId={sutsProjectId}
                onProjectIdChange={setSutsProjectId}
                version={sutsVersion}
                onVersionChange={setSutsVersion}
                asilLevel={sutsAsilLevel}
                onAsilLevelChange={setSutsAsilLevel}
                maxSeq={sutsMaxSeq}
                onMaxSeqChange={setSutsMaxSeq}
                loading={sutsLoading}
                notice={sutsNotice}
                progressPct={sutsProgressPct}
                progressMsg={sutsProgressMsg}
                files={sutsFiles}
                filesLoading={sutsFilesLoading}
                viewData={sutsViewData}
                previewData={sutsPreviewData}
                previewLoading={sutsPreviewLoading}
                previewSheet={sutsPreviewSheet}
                onPreviewSheetChange={setSutsPreviewSheet}
                onGenerate={handleSutsGenerate}
                onRefreshFiles={loadSutsFiles}
                onOpenFile={loadSutsView}
                onLoadPreview={loadSutsPreview}
              />
            </div>
          ) : null}
        </div>
      </div>

      <div
        className={`analyzer-section-shell ${artifactType === "sits" ? "is-active" : ""} ${fullscreenSection === "sits" ? "is-fullscreen" : ""}`}
        style={{ display: artifactType === "sits" ? "" : "none" }}
      >
        <AnalyzerSectionToolbar
          title={`SITS Document (${sitsDocMode === "applied" ? "Applied" : "Current"})`}
        />
        <div className="row" style={{ marginBottom: 12 }}>
          <div className="segmented-group">
            <button type="button" className={`segmented-btn ${sitsDocMode === "current" ? "active" : ""}`} onClick={() => setSitsDocMode("current")}>
              Current
            </button>
            <button type="button" className={`segmented-btn ${sitsDocMode === "applied" ? "active" : ""}`} onClick={() => setSitsDocMode("applied")}>
              Applied
            </button>
          </div>
          {sitsDocMode === "applied" ? (
            <select value={docScmId} onChange={(e) => setDocScmId(e.target.value)}>
              <option value="">SCM Registry</option>
              {docRegistryItems.map((item) => (
                <option key={item.id} value={item.id}>{item.name || item.id}</option>
              ))}
            </select>
          ) : null}
        </div>

        {sitsDocMode === "applied" ? (
          <div className="card" style={{ padding: 14, marginBottom: 12 }}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <strong>SITS Applied Change History</strong>
              <span className="hint">{sitsChangeHistoryLoading ? "loading..." : `${sitsChangeHistoryItems.length} runs`}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 300px) minmax(0, 1fr)", gap: 12, marginTop: 12, alignItems: "stretch" }}>
              <div className="card" style={{ padding: 10, maxHeight: 520, minHeight: 520, overflow: "auto" }}>
                {sitsChangeHistoryItems.length > 0 ? (
                  sitsChangeHistoryItems.map((item) => (
                    <button
                      key={item.run_id}
                      type="button"
                      className={`latest-run-entry ${sitsSelectedRunId === item.run_id ? "is-selected" : ""}`}
                      onClick={() => setSitsSelectedRunId(item.run_id)}
                      style={{ width: "100%", textAlign: "left", marginBottom: 8 }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 600 }}>{item.run_id}</div>
                        <div className="hint">{item.timestamp || "-"}</div>
                        <div className="hint">
                          TC {item.summary?.sits_test_cases || 0}
                          {item.summary?.sits_delta_cases ? ` (Δ${item.summary.sits_delta_cases >= 0 ? "+" : ""}${item.summary.sits_delta_cases})` : ""}
                          {" / "}Sub {item.summary?.sits_sub_cases || 0}
                        </div>
                      </div>
                      <span className="badge">{item.dry_run ? "DRY" : "RUN"}</span>
                    </button>
                  ))
                ) : (
                  <div className="empty">적용된 SITS 변경 이력이 없습니다.</div>
                )}
              </div>
              <div className="card" style={{ padding: 10, minWidth: 0, maxHeight: 520, minHeight: 520, overflow: "auto" }} >
                <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                  <strong>Applied Diff</strong>
                  <span className="hint">{sitsSelectedChangeDetail?.run_id || "select run"}</span>
                </div>
                {sitsSelectedChangeDetail ? (
                  <>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(110px, 1fr))", gap: 8, marginTop: 10 }}>
                      <div className="card" style={{ padding: 10 }}>
                        <div className="hint">Changed Files</div>
                        <div style={{ fontWeight: 700 }}>{Array.isArray(sitsSelectedChangeDetail.changed_files) ? sitsSelectedChangeDetail.changed_files.length : 0}</div>
                      </div>
                      <div className="card" style={{ padding: 10 }}>
                        <div className="hint">TC 수</div>
                        <div style={{ fontWeight: 700 }}>{sitsSelectedChangeDetail.summary?.sits_test_cases || 0}</div>
                      </div>
                      <div className="card" style={{ padding: 10 }}>
                        <div className="hint">TC 변동</div>
                        <div style={{ fontWeight: 700 }}>
                          {sitsSelectedChangeDetail.summary?.sits_delta_cases >= 0 ? "+" : ""}
                          {sitsSelectedChangeDetail.summary?.sits_delta_cases ?? "-"}
                        </div>
                      </div>
                      <div className="card" style={{ padding: 10 }}>
                        <div className="hint">Sub-cases</div>
                        <div style={{ fontWeight: 700 }}>{sitsSelectedChangeDetail.summary?.sits_sub_cases || 0}</div>
                      </div>
                    </div>
                    <div className="card" style={{ padding: 10, marginTop: 12 }}>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>검토 가이드</div>
                      <div style={{ display: "grid", gap: 6 }}>
                        {getSitsGuidanceKo(sitsSelectedChangeDetail).map((line, idx) => (
                          <div key={`sits-guide-${idx}`} className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{line}</div>
                        ))}
                      </div>
                    </div>
                    {getSitsReviewCategoriesKo(sitsSelectedChangeDetail).length > 0 ? (
                      <div className="card" style={{ padding: 10, marginTop: 12 }}>
                        <div style={{ fontWeight: 600, marginBottom: 6 }}>리뷰 분류</div>
                        <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                          {getSitsReviewCategoriesKo(sitsSelectedChangeDetail).map((label) => (
                            <span key={`sits-category-${label}`} className="badge tone-warn">{label}</span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                    {focusedChangeFunction ? (
                      <div className="card" style={{ padding: 10, marginTop: 12 }}>
                        <div style={{ fontWeight: 600, marginBottom: 6 }}>점프 대상 함수</div>
                        <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                          <div className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{focusedChangeFunction}</div>
                          <span className={`badge ${Object.keys(sitsSelectedChangeDetail?.changed_functions || {}).includes(focusedChangeFunction) ? "tone-accent" : ""}`}>
                            {Object.keys(sitsSelectedChangeDetail?.changed_functions || {}).includes(focusedChangeFunction) ? "현재 run과 연결됨" : "목록에서 관련 항목 확인"}
                          </span>
                        </div>
                      </div>
                    ) : null}
                    <div className="card" style={{ padding: 10, marginTop: 12 }}>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>변경 함수 / 유형</div>
                      <div style={{ display: "grid", gap: 8 }}>
                        {sitsSelectedChangeDetail?.changed_functions && typeof sitsSelectedChangeDetail.changed_functions === "object" ? (
                          Object.entries(sitsSelectedChangeDetail.changed_functions).map(([name, kind]) => (
                            <div key={name} className={`card ${focusedChangeFunction && name === focusedChangeFunction ? "latest-run-entry is-focused" : ""}`} style={{ padding: 10 }}>
                              <div style={{ fontWeight: 600 }}>{name}</div>
                              <div className="hint">변경 유형: {String(kind || "-").toUpperCase()}</div>
                            </div>
                          ))
                        ) : (
                          <div className="empty">변경 함수 정보가 없습니다.</div>
                        )}
                      </div>
                    </div>
                    <div className="card" style={{ padding: 10, marginTop: 12 }}>
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>변경 파일</div>
                      <div style={{ display: "grid", gap: 4 }}>
                        {Array.isArray(sitsSelectedChangeDetail.changed_files) && sitsSelectedChangeDetail.changed_files.length > 0 ? (
                          sitsSelectedChangeDetail.changed_files.map((file) => (
                            <div key={file} className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{file}</div>
                          ))
                        ) : <div className="empty">변경 파일 기록이 없습니다.</div>}
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="empty" style={{ marginTop: 20 }}>왼쪽에서 run을 선택하세요.</div>
                )}
              </div>
            </div>
          </div>
        ) : null}

        <div className="card" style={{ padding: 14, marginBottom: 12 }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <div>
              <strong>Advanced SITS Generate</strong>
              <div className="hint" style={{ marginTop: 4 }}>
                기본 화면에서는 문서 열람에 집중하고, 생성 옵션은 필요할 때만 엽니다.
              </div>
            </div>
            <button type="button" className="btn-outline" onClick={() => setShowSitsGeneratePanel((value) => !value)}>
              {showSitsGeneratePanel ? "Hide Generate" : "Open Generate"}
            </button>
          </div>
          {showSitsGeneratePanel ? (
            <div style={{ marginTop: 12 }}>
              <SitsGeneratorPanel
                pickDirectory={pickDirectory}
                pickFile={pickFile}
                isJenkins={false}
                sourceRoot={sitsSourceRoot}
                onSourceRootChange={setSitsSourceRoot}
                srsPath={sitsSrsPath}
                onSrsPathChange={setSitsSrsPath}
                sdsPath={sitsSdsPath}
                onSdsPathChange={setSitsSdsPath}
                hsisPath={sitsHsisPath}
                onHsisPathChange={setSitsHsisPath}
                udsPath={sitsUdsPath}
                onUdsPathChange={setSitsUdsPath}
                stpPath={sitsStpPath}
                onStpPathChange={setSitsStpPath}
                templatePath={sitsTemplatePath}
                onTemplatePathChange={setSitsTemplatePath}
                projectId={sitsProjectId}
                onProjectIdChange={setSitsProjectId}
                version={sitsVersion}
                onVersionChange={setSitsVersion}
                asilLevel={sitsAsilLevel}
                onAsilLevelChange={setSitsAsilLevel}
                maxSubcases={sitsMaxSubcases}
                onMaxSubcasesChange={setSitsMaxSubcases}
                loading={sitsLoading}
                notice={sitsNotice}
                progressPct={sitsProgressPct}
                progressMsg={sitsProgressMsg}
                files={sitsFiles}
                filesLoading={sitsFilesLoading}
                viewData={sitsViewData}
                previewData={sitsPreviewData}
                previewLoading={sitsPreviewLoading}
                previewSheet={sitsPreviewSheet}
                onPreviewSheetChange={setSitsPreviewSheet}
                onGenerate={handleSitsGenerate}
                onRefreshFiles={loadSitsFiles}
                onOpenFile={loadSitsView}
                onLoadPreview={loadSitsPreview}
              />
            </div>
          ) : null}
        </div>
      </div>

      <div
        className={`analyzer-section-shell ${artifactType === "sds" ? "is-active" : ""} ${fullscreenSection === "sds" ? "is-fullscreen" : ""}`}
        style={{ display: artifactType === "sds" ? "" : "none" }}
      >
        <AnalyzerSectionToolbar
          title={`SDS Document (${sdsDocMode === "applied" ? "Applied" : sdsDocMode === "planned" ? "Planned" : "Current"})`}
        />
        <div className="analyzer-mode-banner">
          <div style={{ display: "grid", gap: 10 }}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <strong>SDS Context Status</strong>
            </div>
            <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              <span className={`badge ${String(commonSdsPath || "").trim() ? "qa-pass" : "qa-check"}`}>SDS: {String(commonSdsPath || "").trim() ? "COMMON" : "MISSING"}</span>
              <span className={`badge ${String(sourceRoot || "").trim() ? "qa-pass" : "qa-check"}`}>Source Root: {String(sourceRoot || "").trim() ? "COMMON" : "MISSING"}</span>
            </div>
          </div>
        </div>
        <div className="row" style={{ marginBottom: 12 }}>
          <div className="segmented-group">
            <button type="button" className={`segmented-btn ${sdsDocMode === "current" ? "active" : ""}`} onClick={() => setSdsDocMode("current")}>
              Current
            </button>
            <button type="button" className={`segmented-btn ${sdsDocMode === "planned" ? "active" : ""}`} onClick={() => setSdsDocMode("planned")}>
              Planned
            </button>
            <button type="button" className={`segmented-btn ${sdsDocMode === "applied" ? "active" : ""}`} onClick={() => setSdsDocMode("applied")}>
              Applied
            </button>
          </div>
          <select value={docScmId} onChange={(e) => setDocScmId(e.target.value)}>
            <option value="">SCM Registry</option>
            {docRegistryItems.map((item) => (
              <option key={item.id} value={item.id}>{item.name || item.id}</option>
            ))}
          </select>
        </div>
        {sdsDocMode === "current" ? (
          <>
            {sdsCurrentView.loading ? <div className="card" style={{ padding: 14, marginBottom: 12 }}><div className="hint">SDS 뷰를 불러오는 중입니다...</div></div> : null}
            {sdsCurrentView.error ? <div className="card" style={{ padding: 14, marginBottom: 12 }}><div className="hint">{sdsCurrentView.error}</div></div> : null}
            {!sdsCurrentView.loading && !sdsCurrentView.error ? (
              <SdsDocumentViewer
                viewModel={sdsCurrentView}
                selectedId={sdsSelectedItemId}
                onSelect={setSdsSelectedItemId}
                query={sdsQuery}
                onQueryChange={setSdsQuery}
                changedOnly={sdsChangedOnly}
                onChangedOnlyChange={setSdsChangedOnly}
                onOpenOriginal={() => openLocalFile(sdsCurrentView.path)}
                itemHistory={sdsItemHistory}
                itemHistoryLoading={sdsItemHistoryLoading}
                moduleHistory={sdsModuleHistory}
                moduleHistoryLoading={sdsModuleHistoryLoading}
                artifactMatches={[]}
                artifactLoading={false}
                focusKeyword={focusedChangeFunction}
              />
            ) : null}
          </>
        ) : null}
        {sdsDocMode === "planned" ? (
          <>
            <div className="card" style={{ padding: 12, marginBottom: 12 }}>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>Planned Review</div>
              <div className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>
                최신 영향 분석 결과를 기준으로, 실행 전에 검토가 필요한 SDS 항목을 미리 보여줍니다.
              </div>
              <div className="card" style={{ padding: 10, marginTop: 12 }}>
                <div style={{ fontWeight: 600, marginBottom: 6 }}>검토 가이드</div>
                <div style={{ display: "grid", gap: 6 }}>
                  {getSdsGuidanceKo(overviewDetail || {}).map((line, idx) => (
                    <div key={`sds-planned-guide-${idx}`} className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>
                      {line}
                    </div>
                  ))}
                </div>
              </div>
            </div>
            {sdsPlannedView.loading ? <div className="card" style={{ padding: 14, marginBottom: 12 }}><div className="hint">예상 SDS 뷰를 불러오는 중입니다...</div></div> : null}
            {sdsPlannedView.error ? <div className="card" style={{ padding: 14, marginBottom: 12 }}><div className="hint">{sdsPlannedView.error}</div></div> : null}
            {!sdsPlannedView.loading && !sdsPlannedView.error ? (
              <SdsDocumentViewer
                viewModel={sdsPlannedView}
                selectedId={sdsSelectedItemId}
                onSelect={setSdsSelectedItemId}
                query={sdsQuery}
                onQueryChange={setSdsQuery}
                changedOnly={sdsChangedOnly}
                onChangedOnlyChange={setSdsChangedOnly}
                onOpenOriginal={() => openLocalFile(sdsPlannedView.path)}
                itemHistory={sdsItemHistory}
                itemHistoryLoading={sdsItemHistoryLoading}
                moduleHistory={sdsModuleHistory}
                moduleHistoryLoading={sdsModuleHistoryLoading}
                artifactMatches={[]}
                artifactLoading={false}
                focusKeyword={focusedChangeFunction}
              />
            ) : null}
          </>
        ) : null}
        {sdsDocMode === "applied" ? (
          <div className="card" style={{ padding: 14, marginBottom: 12 }}>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <strong>SDS Applied Change History</strong>
              <span className="hint">{sdsChangeHistoryLoading ? "loading..." : `${sdsChangeHistoryItems.length} runs`}</span>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "minmax(220px, 300px) minmax(0, 1fr)", gap: 12, marginTop: 12, alignItems: "stretch" }}>
              <div className="card" style={{ padding: 10, maxHeight: 520, minHeight: 520, overflow: "auto" }}>
                {sdsChangeHistoryItems.length > 0 ? (
                  sdsChangeHistoryItems.map((item) => (
                    <button
                      key={item.run_id}
                      type="button"
                      className={`latest-run-entry ${sdsSelectedRunId === item.run_id ? "is-selected" : ""}`}
                      onClick={() => setSdsSelectedRunId(item.run_id)}
                      style={{ width: "100%", textAlign: "left", marginBottom: 8 }}
                    >
                      <div style={{ minWidth: 0 }}>
                        <div style={{ fontWeight: 600 }}>{item.run_id}</div>
                        <div className="hint">{item.timestamp || "-"}</div>
                        <div className="hint">SDS {item.summary?.sds_flagged || 0} / STS {item.summary?.sts_flagged || 0}</div>
                      </div>
                      <span className="badge">{item.dry_run ? "DRY" : "RUN"}</span>
                    </button>
                  ))
                ) : (
                  <div className="empty">No applied SDS change history.</div>
                )}
              </div>
              <div style={{ minWidth: 0 }} ref={sdsAppliedReviewRef}>
                {sdsSelectedChangeDetail ? (
                  <>
                    <div className="card" style={{ padding: 12, marginBottom: 12 }}>
                      <div className="row" style={{ justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <strong>Applied Review</strong>
                        <span className="hint">{sdsSelectedChangeDetail?.run_id || "select run"}</span>
                      </div>
                      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8, marginTop: 10 }}>
                        <div className="card" style={{ padding: 10 }}>
                          <div className="hint">Changed Files</div>
                          <div style={{ fontWeight: 700 }}>{Array.isArray(sdsSelectedChangeDetail.changed_files) ? sdsSelectedChangeDetail.changed_files.length : 0}</div>
                        </div>
                        <div className="card" style={{ padding: 10 }}>
                          <div className="hint">SDS Flagged</div>
                          <div style={{ fontWeight: 700 }}>{sdsSelectedChangeDetail.summary?.sds_flagged || 0}</div>
                        </div>
                        <div className="card" style={{ padding: 10 }}>
                          <div className="hint">STS Flagged</div>
                          <div style={{ fontWeight: 700 }}>{sdsSelectedChangeDetail.summary?.sts_flagged || 0}</div>
                        </div>
                      </div>
                      {getSdsReviewCategoriesKo(sdsSelectedChangeDetail).length > 0 ? (
                        <div className="card" style={{ padding: 10, marginTop: 12 }}>
                          <div style={{ fontWeight: 600, marginBottom: 6 }}>리뷰 분류</div>
                          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
                            {getSdsReviewCategoriesKo(sdsSelectedChangeDetail).map((label) => (
                              <span key={`sds-category-${label}`} className="badge tone-warn">{label}</span>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      <div className="card" style={{ padding: 10, marginTop: 12 }}>
                        <div style={{ fontWeight: 600, marginBottom: 6 }}>검토 가이드</div>
                        <div style={{ display: "grid", gap: 6 }}>
                          {getSdsGuidanceKo(sdsSelectedChangeDetail).map((line, idx) => (
                            <div key={`sds-guide-${idx}`} className="hint" style={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>{line}</div>
                          ))}
                        </div>
                      </div>
                      {sdsSelectedChangeDetail?.documents?.sds?.artifact_path ? (
                        <div style={{ marginTop: 12 }}>
                          <button
                            type="button"
                            className="btn-outline"
                            onClick={() => previewAbsReport(sdsSelectedChangeDetail.documents.sds.artifact_path, "SDS Review Artifact")}
                          >
                            SDS Review Artifact 미리보기
                          </button>
                        </div>
                      ) : null}
                    </div>
                    {sdsAppliedView.loading ? <div className="card" style={{ padding: 14, marginBottom: 12 }}><div className="hint">적용된 SDS 뷰를 불러오는 중입니다...</div></div> : null}
                    {sdsAppliedView.error ? <div className="card" style={{ padding: 14, marginBottom: 12 }}><div className="hint">{sdsAppliedView.error}</div></div> : null}
                    {!sdsAppliedView.loading && !sdsAppliedView.error ? (
                      <SdsDocumentViewer
                        viewModel={sdsAppliedView}
                        selectedId={sdsSelectedItemId}
                        onSelect={setSdsSelectedItemId}
                        query={sdsQuery}
                        onQueryChange={setSdsQuery}
                        changedOnly={sdsChangedOnly}
                        onChangedOnlyChange={setSdsChangedOnly}
                        onOpenOriginal={() => openLocalFile(sdsAppliedView.path)}
                        itemHistory={sdsItemHistory}
                        itemHistoryLoading={sdsItemHistoryLoading}
                        moduleHistory={sdsModuleHistory}
                        moduleHistoryLoading={sdsModuleHistoryLoading}
                        artifactMatches={selectedSdsArtifactMatches}
                        artifactLoading={sdsArtifactLoading}
                        focusKeyword={focusedChangeFunction}
                      />
                    ) : null}
                  </>
                ) : (
                  <div className="card" style={{ padding: 14 }}><div className="empty">run을 선택하면 적용된 SDS 변경 내용을 확인할 수 있습니다.</div></div>
                )}
              </div>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
};

export default UdsAnalyzerView;

