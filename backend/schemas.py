"""Pydantic request/response models for the backend API."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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


class JenkinsSourceDownloadRequest(JenkinsSyncRequest):
    source_root: str = ""
    scm_type: str = ""
    scm_url: str = ""
    scm_username: str = ""
    scm_password: str = ""
    scm_branch: str = ""
    scm_revision: str = ""


class JenkinsScmInfoRequest(BaseModel):
    scm_type: str = "svn"
    scm_url: str
    scm_username: str = ""
    scm_password: str = ""


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


# ── UDS Traceability ──────────────────────────────────────────────────

class UdsTraceabilityMatrixRequest(BaseModel):
    requirement_items: List[Dict[str, Any]] = []
    mapping_pairs: List[Dict[str, Any]] = []
    vcast_rows: List[Dict[str, Any]] = []
