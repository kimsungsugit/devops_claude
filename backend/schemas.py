"""Pydantic request/response models for the backend API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Session ───────────────────────────────────────────────────────────

class SessionNamePayload(BaseModel):
    name: str


class SessionConfigPayload(BaseModel):
    config: Dict[str, Any]


class RunRequest(BaseModel):
    project_root: str
    config: Dict[str, Any]


class PreflightRequest(BaseModel):
    project_root: Optional[str] = None
    config: Dict[str, Any]


class StopRequest(BaseModel):
    pid: int
    status_path: Optional[str] = None


# ── Jenkins ───────────────────────────────────────────────────────────

class JenkinsJobsRequest(BaseModel):
    base_url: str
    username: str
    api_token: str
    recursive: bool = True
    max_depth: int = 2
    verify_tls: bool = True


class JenkinsBuildsRequest(BaseModel):
    job_url: str
    username: str
    api_token: str
    limit: int = 30
    verify_tls: bool = True


class JenkinsBuildInfoRequest(BaseModel):
    job_url: str
    username: str
    api_token: str
    build_selector: str = "lastSuccessfulBuild"
    verify_tls: bool = True


class JenkinsSyncRequest(BaseModel):
    job_url: str
    username: str
    api_token: str
    cache_root: str
    build_selector: str = "lastSuccessfulBuild"
    patterns: List[str] = []
    verify_tls: bool = True
    scan_mode: Optional[str] = None
    scan_max_files: Optional[int] = None
    # Optional SCM override — password is resolved via env (DEVOPS_SCM_PASSWORD
    # or scm_registry entry's scm_password_env), never accepted as plaintext.
    scm_username: str = ""
    scm_id: str = ""
    # Force a fresh SCM checkout even if the source cache is complete.
    # Useful when the remote revision changed but the Jenkins build number
    # has not, or when a previous partial checkout must be discarded.
    force: bool = False


class JenkinsSourceDownloadRequest(JenkinsSyncRequest):
    source_root: str = ""
    scm_type: str = ""
    scm_url: str = ""
    scm_username: str = ""
    # scm_password removed for security — use DEVOPS_SCM_PASSWORD env var
    scm_branch: str = ""
    scm_revision: str = ""


class JenkinsScmInfoRequest(BaseModel):
    scm_type: str = "svn"
    scm_url: str
    scm_username: str = ""
    # scm_password removed for security — use DEVOPS_SCM_PASSWORD env var


class JenkinsImpactTriggerRequest(BaseModel):
    scm_id: str
    build_number: int = 0
    job_url: str = ""
    base_ref: str = ""
    dry_run: bool = False
    targets: List[str] = Field(default_factory=list)


class ScmLinkedDocs(BaseModel):
    uds: str = ""
    sts: str = ""
    suts: str = ""
    sits: str = ""
    srs: str = ""
    sds: str = ""
    hsis: str = ""
    stp: str = ""


class ScmRegistryEntry(BaseModel):
    id: str
    name: str
    scm_type: str = "git"
    scm_url: str = ""
    scm_username: str = ""
    scm_password_env: str = ""
    branch: str = ""
    base_ref: str = "HEAD~1"
    source_root: str = ""
    watch_patterns: List[str] = Field(default_factory=lambda: ["*.c", "*.h"])
    ignore_patterns: List[str] = Field(default_factory=list)
    webhook_secret_env: str = ""
    linked_docs: ScmLinkedDocs = Field(default_factory=ScmLinkedDocs)
    created_at: str = ""
    updated_at: str = ""
    last_triggered: str = ""
    last_revision: str = ""


class ScmRegistryStore(BaseModel):
    registries: List[ScmRegistryEntry] = Field(default_factory=list)


class ScmRegisterRequest(BaseModel):
    id: str
    name: str
    scm_type: str = "git"
    scm_url: str = ""
    scm_username: str = ""
    scm_password_env: str = ""
    branch: str = ""
    base_ref: str = "HEAD~1"
    source_root: str = ""
    watch_patterns: List[str] = Field(default_factory=lambda: ["*.c", "*.h"])
    ignore_patterns: List[str] = Field(default_factory=list)
    webhook_secret_env: str = ""
    linked_docs: ScmLinkedDocs = Field(default_factory=ScmLinkedDocs)


class ScmUpdateRequest(BaseModel):
    name: Optional[str] = None
    scm_type: Optional[str] = None
    scm_url: Optional[str] = None
    scm_username: Optional[str] = None
    scm_password_env: Optional[str] = None
    branch: Optional[str] = None
    base_ref: Optional[str] = None
    source_root: Optional[str] = None
    watch_patterns: Optional[List[str]] = None
    ignore_patterns: Optional[List[str]] = None
    webhook_secret_env: Optional[str] = None
    linked_docs: Optional[ScmLinkedDocs] = None


class JenkinsSyncLocalRequest(BaseModel):
    job_url: str
    local_reports_dir: str


class JenkinsCacheRequest(BaseModel):
    job_url: str
    cache_root: str


class JenkinsReportRequest(BaseModel):
    job_url: str
    cache_root: str
    build_selector: str = "lastSuccessfulBuild"


class JenkinsCallTreeRequest(JenkinsReportRequest):
    source_root: Optional[str] = None
    entry: str = ""
    max_depth: int = 5
    include_paths: List[str] = []
    exclude_paths: List[str] = []
    max_files: int = 2000
    include_external: bool = False
    compile_commands_path: Optional[str] = None
    output_format: str = "json"
    external_map: List[Dict[str, Any]] = []
    html_template: Optional[str] = None


class CallTreePreviewRequest(BaseModel):
    call_tree: Dict[str, Any]
    html_template: Optional[str] = None


class JenkinsPublishRequest(JenkinsReportRequest):
    source_dir: Optional[str] = None


class JenkinsReportZipRequest(JenkinsReportRequest):
    include_paths: List[str] = []
    exclude_paths: List[str] = []
    exts: List[str] = []
    scope: str = "all"


class JenkinsServerFilesRequest(BaseModel):
    root: str
    rel_path: str = ""
    exts: List[str] = []
    max_files: int = 5000


class JenkinsRagQueryRequest(JenkinsReportRequest):
    query: str
    top_k: int = 5
    categories: List[str] = []


# ── UDS ───────────────────────────────────────────────────────────────

class UdsLabelRequest(BaseModel):
    job_url: str
    cache_root: str = ""
    filename: str
    label: str = ""


class UdsDeleteRequest(BaseModel):
    job_url: str
    cache_root: str = ""
    filename: str


class UdsDiffRequest(BaseModel):
    job_url: str
    cache_root: str = ""
    filename_a: str
    filename_b: str


class UdsPublishRequest(BaseModel):
    job_url: str
    cache_root: str = ""
    filename: str
    target_dir: str = "docs"


# ── Chat ──────────────────────────────────────────────────────────────

class ChatHistoryItem(BaseModel):
    role: str
    text: str


class ChatJenkinsConfig(BaseModel):
    job_url: str = ""
    cache_root: str = ""
    build_selector: str = "lastSuccessfulBuild"


class ApprovalRequestPayload(BaseModel):
    approval_id: str
    action_type: str
    title: str
    summary: str
    tool_name: str
    input_preview: Dict[str, Any] = Field(default_factory=dict)
    risk_level: str = "medium"


class ApprovalResolutionRequest(BaseModel):
    approval_id: str
    decision: str
    comment: str = ""


class ChatCitation(BaseModel):
    source_type: str
    label: str
    uri: str = ""
    path: str = ""
    section: str = ""
    snippet: str = ""
    score: Optional[float] = None


class ChatEvidenceItem(BaseModel):
    id: str
    title: str
    source_type: str
    uri: str = ""
    path: str = ""
    snippet: str = ""
    source: str = ""


class ChatStructuredPayload(BaseModel):
    answer: str = ""
    evidence: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)


class ChatStreamEvent(BaseModel):
    type: str
    request_id: str = ""
    thread_id: str = ""
    ts: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    ok: bool
    request_id: str = ""
    thread_id: str = ""
    answer: str = ""
    sources: List[str] = Field(default_factory=list)
    citations: List[ChatCitation] = Field(default_factory=list)
    evidence: List[ChatEvidenceItem] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
    structured: Optional[ChatStructuredPayload] = None
    approval_required: bool = False
    approval_request: Optional[ApprovalRequestPayload] = None


class ChatRequest(BaseModel):
    mode: str = "local"
    question: str
    session_id: Optional[str] = None
    report_dir: Optional[str] = None
    llm_model: Optional[str] = None
    oai_config_path: Optional[str] = None
    ui_context: Optional[Dict[str, Any]] = None
    history: List[ChatHistoryItem] = Field(default_factory=list)
    jenkins: Optional[ChatJenkinsConfig] = None
    thread_id: Optional[str] = None  # 기존 대화 이어하기 (서버 이력 로드)
    save_history: bool = True  # 서버측 이력 저장 여부


class ChatHistoryMessageItem(BaseModel):
    seq: int
    role: str
    text: str
    request_id: Optional[str] = None
    llm_model: Optional[str] = None
    created_at: str = ""


class ChatHistoryResponse(BaseModel):
    thread_id: str
    session_id: Optional[str] = None
    mode: str = "local"
    title: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    total_messages: int = 0
    messages: List[ChatHistoryMessageItem] = Field(default_factory=list)


class ChatConversationSummary(BaseModel):
    thread_id: str
    session_id: Optional[str] = None
    mode: str = "local"
    title: Optional[str] = None
    message_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class ChatConversationListResponse(BaseModel):
    total: int = 0
    conversations: List[ChatConversationSummary] = Field(default_factory=list)


class ChatTitleUpdateRequest(BaseModel):
    title: str


# ── Local ─────────────────────────────────────────────────────────────

class LocalReportGenerateRequest(BaseModel):
    report_dir: str = ""
    formats: List[str] = ["docx", "xlsx"]


class ScmRequest(BaseModel):
    project_root: str
    workdir_rel: str = "."
    action: str
    repo_url: str = ""
    branch: str = ""
    depth: int = 0
    revision: str = ""
    timeout_sec: int = 900
    mode: str = "git"


class LocalImpactTriggerRequest(BaseModel):
    scm_id: str
    base_ref: str = ""
    dry_run: bool = False
    auto_generate: bool = False
    targets: List[str] = Field(default_factory=list)
    manual_changed_files: List[str] = Field(default_factory=list)


class KBRequest(BaseModel):
    project_root: str
    report_dir: str
    entry_key: Optional[str] = None


class PickerRequest(BaseModel):
    title: Optional[str] = None


class OpenFileRequest(BaseModel):
    path: str


class EditorReadAbsRequest(BaseModel):
    path: str
    max_bytes: int = 2 * 1024 * 1024


class TextPreviewRequest(BaseModel):
    path: str
    max_chars: int = 20000


class SdsViewRequest(BaseModel):
    path: str
    max_items: int = 500
    changed_functions: Dict[str, str] = {}
    changed_files: List[str] = []
    flagged_modules: List[str] = []


class OpenFolderRequest(BaseModel):
    path: str


class ListDirRequest(BaseModel):
    project_root: str
    rel_path: str = "."


class GitRequest(BaseModel):
    project_root: str
    workdir_rel: str = "."
    paths: List[str] = []
    message: str = ""
    branch: str = ""
    staged: bool = False
    path: str = ""
    max_count: int = 30


class SearchRequest(BaseModel):
    project_root: str
    rel_path: str = "."
    query: str
    max_results: int = 200


class ReplaceTextRequest(BaseModel):
    project_root: str
    rel_path: str
    search: str
    replace: str


class EditorReadRequest(BaseModel):
    project_root: str
    rel_path: str
    max_bytes: int = 2 * 1024 * 1024


class EditorWriteRequest(BaseModel):
    project_root: str
    rel_path: str
    content: str
    make_backup: bool = True


class EditorReplaceRequest(BaseModel):
    project_root: str
    rel_path: str
    start_line: int
    end_line: int
    content: str


class FormatCodeRequest(BaseModel):
    text: str
    filename: str = "temp.c"


class ReportZipRequest(BaseModel):
    paths: List[str] = []


# ── RAG ───────────────────────────────────────────────────────────────

class RagStatusRequest(BaseModel):
    config: Dict[str, Any] = {}
    report_dir: str = ""


class RagIngestRequest(BaseModel):
    config: Dict[str, Any] = {}
    report_dir: str = ""


class RagStorageRequest(BaseModel):
    storage: str = "sqlite"
    pgvector_dsn: str = ""
    pgvector_url: str = ""
    report_dir: str = ""


class RagQueryRequest(BaseModel):
    query: str
    top_k: int = 5
    categories: List[str] = []
    report_dir: str = ""
    config: Dict[str, Any] = {}


# ── Tools ─────────────────────────────────────────────────────────────

class ImpactAnalyzeRequest(BaseModel):
    source_root: str
    changed_files: List[str] = []
    changed_raw: str = ""
    include_ai_guide: bool = False


class TestGenerateRequest(BaseModel):
    source_root: str
    target_function: str
    strategy: str = "boundary"
    max_cases: int = 20
    include_edge_cases: bool = True


class QACParseRequest(BaseModel):
    old_version: bool = False


class ExcelCompareRequest(BaseModel):
    path_source: str
    path_target: str
    sheet_source: int = 1
    sheet_target: int = 1


# ── VectorCAST ────────────────────────────────────────────────────────

class VCastParseRequest(BaseModel):
    report_type: str
    version: str = "Ver2025"


class VCastGenerateExcelRequest(BaseModel):
    parsed_data: Dict[str, Any]
    mode: str = "TestCase"
    output_filename: Optional[str] = None
    unit_bank: Optional[Dict[str, str]] = None


class VCastProcessJenkinsRequest(BaseModel):
    job_url: str
    cache_root: str
    build_selector: str = "lastSuccessfulBuild"
    report_type: str = "TestCaseData"
    version: str = "Ver2025"


# ── Test Summary ──────────────────────────────────────────────────────

class TestSummaryRequest(BaseModel):
    report_dir: str
    previous_report_dir: Optional[str] = None
    gates: Optional[Dict[str, float]] = None


class QualityGateResult(BaseModel):
    name: str
    actual: float
    threshold: float
    status: str  # pass, warn, fail


# ── UDS Traceability ──────────────────────────────────────────────────

class UdsTraceabilityMatrixRequest(BaseModel):
    requirement_items: List[Dict[str, Any]] = []
    mapping_pairs: List[Dict[str, Any]] = []
    vcast_rows: List[Dict[str, Any]] = []
    sds_pairs: List[Dict[str, Any]] = []   # SDS component↔requirement mapping
    sits_rows: List[Dict[str, Any]] = []   # SITS TC↔requirement mapping
    # Optional cache-persist hints (for dashboard summary quick-load)
    job_url: Optional[str] = None
    cache_root: Optional[str] = None
    build_selector: Optional[str] = None


# ── SwUT Builder (8차 라운드) ─────────────────────────────────────────

class SwUTBuildRequest(BaseModel):
    """SwUT Coverage Report / SUTR 빌드 공통 request body.

    입력 표면 매트릭스 (deep-reviewer X3) endpoint 단에서 차단:
      - release_sw_version: regex ^\\d+\\.\\d+(\\.\\d+)?$ 필수
      - test_engineer / reviewer / approver: maxlen 100, 줄바꿈 금지
      - doc_id_sequence: digit only
      - test_date / validation_date: yyyy-mm-dd / yyyy/mm/dd ($ anchor)
      - cache_root / log_folder / coverage_template_path / sutr_template_path: maxlen 500, 줄바꿈 금지 (51차 분리)
      - jenkins_build_number: 1 ≤ n ≤ 99999 (Jenkins 운영 한도)
      - deviation_cases: 최대 200 items, 합산 256KB (13차 C3 — DoS 차단)

    53차 C1 — extra='forbid': 외부 호출자가 51차 이전 schema의 `template_path` 등 unknown
    필드 보내면 422 raise. silent wrong-pick (config fallback 양식 사용) 차단.
    """
    model_config = ConfigDict(extra="forbid")

    # 필수
    project_id: str = Field(..., min_length=1, max_length=50)
    release_sw_version: str = Field(..., pattern=r"^\d+\.\d+(\.\d+)?$")
    # 13차 W7: $ anchor 추가 — garbage suffix 차단
    test_date: str = Field(..., pattern=r"^\d{2,4}[-/]\d{1,2}[-/]\d{1,2}$")

    # 선택 (default 또는 config fallback)
    test_engineer: str = Field("", max_length=100)
    doc_id_sequence: str = Field("", pattern=r"^\d*$")
    hw_version: str = Field("1.00", max_length=20)
    asil_level: str = Field("ASIL A", max_length=20)

    # 입력 소스 (Jenkins 우선, log_folder fallback)
    # 13차 W9: build number 범위 1..99999 (Jenkins 운영 한도)
    jenkins_build_number: Optional[int] = Field(None, ge=1, le=99999)
    # 13차 W8: path maxlen 500 + 줄바꿈 금지 (validator)
    cache_root: str = Field("", max_length=500)
    log_folder: Optional[str] = Field(None, max_length=500)
    # 51차 — Coverage / SUTR 양식 분리 (이전 단일 template_path). 둘 다 비면 config fallback.
    coverage_template_path: str = Field("", max_length=500)
    sutr_template_path: str = Field("", max_length=500)
    swutcr_template_path: str = Field("", max_length=500)
    # 16차: SwUDS docx (옵션) — 제공 시 2.Consistency에 SwUDS↔SwUTS 매핑 row 추가
    swuds_docx_path: str = Field("", max_length=500)
    # 30차 W21: C 소스 디렉토리 (옵션) — 제공 시 Doxygen @asil 태그에서 함수별
    # ASIL 등급 추출 → summary.asil_distribution + 3.Coverage 시트 ASIL D row 강조.
    c_source_root: str = Field("", max_length=500)
    # 60차 F6-A: SwUTS spec 파일 (옵션, xlsm/docx 허용). 제공 시 SUTR Test Log의
    # TC_ID / Description / Precondition / Test Method / Generation Method 컬럼에
    # spec 데이터 stamp. 양식 자동 감지 (KJPDS02 SwUTS v1.01 / HDPDM01 SUTS v3.01).
    swuts_docx_path: str = Field("", max_length=500)
    # 60차 F6-C: HMR (VectorCAST aggregate metrics report) HTML 경로 (옵션).
    # 제공 시 Coverage Report 함수별 Function Calls metric stamp
    # (Jenkins_PDSM_UT_metrics_report.html 양식). KJPDS02 v1.01 양식의 row 6.
    hmr_html_path: str = Field("", max_length=500)

    # 인사 메타 (선택)
    reviewer_override: str = Field("", max_length=100)
    approver_override: str = Field("", max_length=100)
    # 13차 W7: validation_date pattern 추가 (빈 string 허용)
    validation_date: str = Field("", pattern=r"^$|^\d{2,4}[-/]\d{1,2}[-/]\d{1,2}$")

    # Deviation cases (선택, swut_deviation_generator 사전 호출 결과 주입 가능)
    # 13차 C3: list 길이 + 합산 byte 제한 (DoS)
    deviation_cases: List[Dict[str, Any]] = Field(default_factory=list, max_length=200)

    @field_validator("test_engineer", "reviewer_override", "approver_override",
                     "cache_root", "log_folder", "coverage_template_path", "sutr_template_path",
                     "swutcr_template_path",
                     "swuds_docx_path", "c_source_root", "swuts_docx_path", "hmr_html_path")
    @classmethod
    def _no_newline(cls, v):
        if v is None:
            return v
        if "\n" in v or "\r" in v:
            raise ValueError("줄바꿈 문자 금지 — 단일 라인 필요")
        return v

    @field_validator("deviation_cases")
    @classmethod
    def _validate_deviation_cases(cls, v: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """13차 C3: deviation_cases 합산 byte ≤ 256KB, 각 item key ≤ 20개.

        max_length=200은 Pydantic이 처리. 본 validator는 item 내부 크기.
        """
        if not v:
            return v
        import json as _json
        total_bytes = 0
        for i, item in enumerate(v):
            if not isinstance(item, dict):
                raise ValueError(f"deviation_cases[{i}]: dict 필요")
            if len(item) > 20:
                raise ValueError(f"deviation_cases[{i}]: key 수 ≤ 20 필요 (got {len(item)})")
            try:
                total_bytes += len(_json.dumps(item, ensure_ascii=False).encode("utf-8"))
            except (TypeError, ValueError) as e:
                raise ValueError(f"deviation_cases[{i}]: JSON 직렬화 불가 — {e}") from e
        if total_bytes > 256 * 1024:
            raise ValueError(
                f"deviation_cases 합산 크기 {total_bytes:,} bytes — 256KB 한도 초과"
            )
        return v


# ── SwIT Coverage Report (33차 라운드) ─────────────────────────────────
# SwUTBuildRequest와 동일 17 필드 + 입력 표면 정책 (maxlen 500 + _no_newline +
# regex anchors + deviation_cases DoS 한도). 본 schema는 SwITBuildRequest로
# 신규 정의 — SwUTBuildRequest를 그대로 alias 하지 않고 별도 class로 분리해
# 향후 Integration test 도구별 필드 추가 (HiL/MiL 환경 등) 시 단방향 변경.

class SwITBuildRequest(BaseModel):
    """SwIT Coverage Report 빌드 요청 (33차 라운드).

    SwUTBuildRequest 패턴 동일 — 17 공통 필드 + validator. SwIT 도구별
    필드는 향후 33-fix 또는 34차에서 추가.

    53차 C1 — extra='forbid': legacy template_path 등 unknown 키 422 차단.
    """
    model_config = ConfigDict(extra="forbid")

    # 필수
    project_id: str = Field(..., min_length=1, max_length=50)
    release_sw_version: str = Field(..., pattern=r"^\d+\.\d+(\.\d+)?$")
    test_date: str = Field(..., pattern=r"^\d{2,4}[-/]\d{1,2}[-/]\d{1,2}$")

    # 선택 (default 또는 config fallback)
    test_engineer: str = Field("", max_length=100)
    doc_id_sequence: str = Field("", pattern=r"^\d*$")
    hw_version: str = Field("1.00", max_length=20)
    asil_level: str = Field("ASIL B", max_length=20)  # SwIT는 Integration — ASIL B 일반

    # 입력 소스 (Jenkins 우선, log_folder fallback)
    jenkins_build_number: Optional[int] = Field(None, ge=1, le=99999)
    cache_root: str = Field("", max_length=500)
    log_folder: Optional[str] = Field(None, max_length=500)
    # 51차 — Coverage / SITR 양식 분리 (이전 단일 template_path). 둘 다 비면 config fallback.
    coverage_template_path: str = Field("", max_length=500)
    sitr_template_path: str = Field("", max_length=500)
    # SwUDS docx (옵션) — 2.Consistency 매핑 + 32차 W28 ASIL 추출
    swuds_docx_path: str = Field("", max_length=500)
    # 30차 W21 + 32차 W28: C 소스 디렉토리 (옵션) — Doxygen @asil 추출
    c_source_root: str = Field("", max_length=500)
    # 60차 F6-B: SwITS spec 파일 (xlsm/docx 허용). 제공 시 SITR Test Log의
    # TC_ID/Description/Precondition/Test Method/Generation Method 컬럼에 spec stamp.
    # field 명은 swuts_docx_path로 통일 (SwUT와 대칭 — resolver `getattr` 호환).
    swuts_docx_path: str = Field("", max_length=500)
    # 60차 F6-C: HMR (VectorCAST aggregate metrics report) HTML 경로 (옵션).
    # 제공 시 SwIT Coverage Report 함수별 Function Calls metric stamp
    # (Jenkins_PDSM_IT_metrics_report.html 양식). KJPDS02 v1.01 SwIT 양식의 row 6.
    hmr_html_path: str = Field("", max_length=500)

    # 인사 메타 (선택)
    reviewer_override: str = Field("", max_length=100)
    approver_override: str = Field("", max_length=100)
    validation_date: str = Field("", pattern=r"^$|^\d{2,4}[-/]\d{1,2}[-/]\d{1,2}$")

    @field_validator("test_engineer", "reviewer_override", "approver_override",
                     "cache_root", "log_folder", "coverage_template_path", "sitr_template_path",
                     "swuds_docx_path", "c_source_root", "swuts_docx_path", "hmr_html_path")
    @classmethod
    def _no_newline(cls, v):
        if v is None:
            return v
        if "\n" in v or "\r" in v:
            raise ValueError("줄바꿈 문자 금지 — 단일 라인 필요")
        return v


# ── SwIT SITR Build (34차 라운드) ─────────────────────────────────────
# SwITBuildRequest 17 필드 + deviation_cases (SwUTBuildRequest._validate_deviation_cases
# 패턴 동일 — 256KB / item key ≤ 20 / DoS 한도). xlsm 산출물 (keep_vba=True).

class SwITSitrBuildRequest(SwITBuildRequest):
    """SwIT SITR (Software Integration Test Result) 빌드 요청 (34차).

    SwITBuildRequest 17 필드를 그대로 상속 + deviation_cases 추가.
    SwUTBuildRequest의 deviation_cases 정책 (max 200 / 256KB / item key ≤ 20)
    재활용.

    ISO 26262: ASIL B+ Integration test evidence — Deviation 항목은 audit
    reviewer가 직접 검토 (자동 reviewer 평가 금지).
    """
    deviation_cases: List[Dict[str, Any]] = Field(default_factory=list, max_length=200)

    @field_validator("deviation_cases")
    @classmethod
    def _validate_deviation_cases_sitr(cls, v: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """SwUTBuildRequest._validate_deviation_cases 정책 차용 (13차 C3)."""
        import json as _json
        total_bytes = 0
        for i, item in enumerate(v):
            if not isinstance(item, dict):
                raise ValueError(f"deviation_cases[{i}]: dict 필요")
            if len(item) > 20:
                raise ValueError(f"deviation_cases[{i}]: key 수 ≤ 20 필요 (got {len(item)})")
            try:
                total_bytes += len(_json.dumps(item, ensure_ascii=False).encode("utf-8"))
            except (TypeError, ValueError) as e:
                raise ValueError(f"deviation_cases[{i}]: JSON 직렬화 불가 — {e}") from e
        if total_bytes > 256 * 1024:
            raise ValueError(
                f"deviation_cases 합산 크기 {total_bytes:,} bytes — 256KB 한도 초과"
            )
        return v


# ── SwSA Software Static Analysis Report 빌드 요청 ───────────────────────

class SwSABuildRequest(BaseModel):
    """SwSA(Software Static Analysis Report) 빌드 요청.

    웹에서 로그 폴더 + 템플릿 경로 + 메타만 제공하면 자동 빌드.
    입력 표면(deep-reviewer X3): path maxlen 500 + 줄바꿈 금지, extra='forbid'.
    SwSA Cover 날짜는 점 구분(2026.04.24)도 허용.
    """
    model_config = ConfigDict(extra="forbid")

    # 필수
    project_id: str = Field(..., min_length=1, max_length=50)
    # SW Ver. (ST Test-Info). 예: 2631.00
    release_sw_version: str = Field(..., pattern=r"^\d+\.\d+(\.\d+)?$")
    # Cover Date — yyyy.mm.dd / yyyy-mm-dd / yyyy/mm/dd
    test_date: str = Field(..., pattern=r"^\d{2,4}[-/.]\d{1,2}[-/.]\d{1,2}$")

    # 입력 소스 (자동 발견)
    log_folder: str = Field("", max_length=500)       # 01.Log/PV — QAC/PMD 자동 스캔
    template_path: str = Field("", max_length=500)    # 회사 v0.10 SwSA 양식 (비면 config fallback)

    # Cover / Summary 메타
    doc_id_base: str = Field("HKY-SwSA", max_length=80)
    doc_id_sequence: str = Field("", pattern=r"^\d*$")
    doc_version: str = Field("v0.10", max_length=20)
    doc_status: str = Field("Unspecified", max_length=40)
    asil_level: str = Field("ASIL A", max_length=20)
    phase: str = Field("", max_length=20)
    platform_version: str = Field("", max_length=120)   # (APP) ... / (BOOT) ...
    product: str = Field("PDS", max_length=50)
    verification_target: str = Field("MCU", max_length=20)
    compiler: str = Field("", max_length=80)
    mcu: str = Field("", max_length=80)

    # ST Test-Information (모든 실행 시트 공통)
    analysis_round: str = Field("1", max_length=10)
    test_engineer: str = Field("", max_length=100)
    debugger: str = Field("", max_length=100)
    misra_rule_version: str = Field("MISRA C 2012", max_length=40)
    secure_rule_version: str = Field("HKMC 4.1", max_length=40)

    # 인사 메타 (선택)
    reviewer_override: str = Field("", max_length=100)
    approver_override: str = Field("", max_length=100)
    validation_date: str = Field("", pattern=r"^$|^\d{2,4}[-/.]\d{1,2}[-/.]\d{1,2}$")
    history_description: str = Field("", max_length=300)

    @field_validator("project_id", "log_folder", "template_path", "test_engineer", "debugger",
                     "compiler", "mcu", "platform_version", "reviewer_override",
                     "approver_override", "doc_id_base", "doc_version", "doc_status",
                     "phase", "product", "verification_target", "history_description")
    @classmethod
    def _no_newline(cls, v):
        # M1: project_id/doc_version 등은 Content-Disposition filename 유입 → CRLF 차단 필수
        if v is None:
            return v
        if "\n" in v or "\r" in v:
            raise ValueError("줄바꿈 문자 금지 — 단일 라인 필요")
        return v


# ── SwUT Browse (21차 라운드) ─────────────────────────────────────────

class SwUTBrowseRequest(BaseModel):
    """Path picker dialog용 디렉토리 list 요청 (21차 T185).

    file_resolver.list_dir로 cloudium / local 통합 navigate. 파일/디렉토리 분리 반환.

    입력 표면:
      - path: maxlen 500, 줄바꿈 금지, 빈 string은 사용자 home 또는 일반 root
      - pattern: maxlen 50, glob pattern (예: '*.xlsx', '*.xlsm,*.docx')
    """
    path: str = Field("", max_length=500)
    pattern: str = Field("*", max_length=50)

    @field_validator("path", "pattern")
    @classmethod
    def _no_newline_browse(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("줄바꿈 문자 금지")
        return v


# ── SwUT Consistency Check (18차 라운드) ──────────────────────────────

class SwUTConsistencyCheckRequest(BaseModel):
    """Coverage Report ↔ SUTR cross-validation 요청 body (18차 T176).

    두 산출물 path를 받아 ``swut_consistency_checker.check_swut_consistency`` 호출.
    file_resolver로 cloudium / local 모두 해결.

    입력 표면 매트릭스:
      - coverage_path / sutr_path: maxlen 500, 줄바꿈 금지 (헤더 인젝션 안전)
      - 두 path 모두 필수 (min_length=1)
    """
    coverage_path: str = Field(..., min_length=1, max_length=500)
    sutr_path: str = Field(..., min_length=1, max_length=500)

    @field_validator("coverage_path", "sutr_path")
    @classmethod
    def _no_newline_paths(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("줄바꿈 문자 금지 — 단일 라인 path 필요")
        return v


# ── SwIT Consistency Check (35차 라운드) ──────────────────────────────

class AddAllowedPrefixRequest(BaseModel):
    """39차 — Cloudium allowed_prefixes 동적 추가 요청.

    영구 저장 (config/cloudium_extra_prefixes.json) + 즉시 file_resolver 갱신.
    cloudium 모드 전용 — local 모드는 endpoint에서 400.
    """
    prefix: str = Field(..., min_length=1, max_length=500)

    @field_validator("prefix")
    @classmethod
    def _no_newline_add_prefix(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("줄바꿈 문자 금지 — 단일 라인 path 필요")
        return v


class RemoveAllowedPrefixRequest(BaseModel):
    """39차 — Cloudium allowed_prefixes 제거 요청."""
    prefix: str = Field(..., min_length=1, max_length=500)

    @field_validator("prefix")
    @classmethod
    def _no_newline_remove_prefix(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("줄바꿈 문자 금지 — 단일 라인 path 필요")
        return v


class LogFolderPreviewRequest(BaseModel):
    """38차 W4 — log_folder dry-run preview 요청 body.

    사용자가 빌드 전에 자동 선택될 release release를 확인 가능.
    SwUT/SwIT 공통 — env_prefix kwarg로 분기 (default "SWTE").
    """
    log_folder: str = Field(..., min_length=1, max_length=500)

    @field_validator("log_folder")
    @classmethod
    def _no_newline_preview(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("줄바꿈 문자 금지 — 단일 라인 path 필요")
        return v


class SwITConsistencyCheckRequest(BaseModel):
    """SwIT Coverage Report ↔ SITR cross-validation 요청 body (35차).

    SwUT 18차 ConsistencyCheckRequest와 동일 패턴 — coverage_path + sitr_path.

    입력 표면 매트릭스:
      - coverage_path / sitr_path: maxlen 500, 줄바꿈 금지 (헤더 인젝션 안전)
      - 두 path 모두 필수 (min_length=1)
    """
    coverage_path: str = Field(..., min_length=1, max_length=500)
    sitr_path: str = Field(..., min_length=1, max_length=500)

    @field_validator("coverage_path", "sitr_path")
    @classmethod
    def _no_newline_swit_paths(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("줄바꿈 문자 금지 — 단일 라인 path 필요")
        return v
