"""Pydantic request/response models for the backend API."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional

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
    # 선택: 주면 빌드 목록에 per-build SVN revision을 부착한다(git 파이프라인 잡은 Jenkins에
    # 소스 revision이 없어 빌드 시각→svn 날짜-revision으로 되찾는다). 없으면 기존과 동일.
    scm_id: str = ""


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
    # 시스템 레벨 문서 — SyRS(상위 시스템요구 docx), SyTS/SyITS(시스템 시험/통합시험 결과 xlsx).
    # ScmLinkedDocs에 정의돼야 model_dump 직렬화에서 살아남아 프론트가 경로를 받고,
    # scm.py allowed_prefixes 자동병합으로 cloudium 워커 접근 prefix가 등록된다.
    syrs: str = ""
    syts: str = ""
    syits: str = ""
    # VectorCAST 결과 로그 경로(들). 부트로더/FBL/APP 등 결과가 별도 파일로 나올 수
    # 있어 단일 문자열이 아닌 복수 경로 list. 각 경로는 vectorcast_rag.json 파일 또는
    # 그 상위 폴더. SwUT/SwIT 로그처럼 SCM별로 설정의 '연결 문서 경로'에서 등록.
    vectorcast: List[str] = Field(default_factory=list)
    # 문서별 **생성 템플릿**. 형식이 서로 다르다 — UDS 는 .docx, 시험 규격서는 .xlsm 이다.
    # 예전엔 이 필드가 아예 없어서 프론트가 설정의 `docPaths.template` **하나**를
    # UDS(`uds_template_path`)와 시험문서(`template_path`) 양쪽에 같이 보냈다. 형식이
    # 다른 두 자리에 같은 경로가 가므로 한쪽은 반드시 틀린다(라이브에서 준비 게이트의
    # '템플릿' 항목이 어느 프로젝트에서도 채워지지 않은 이유이기도 하다).
    # ⚠ SwUT/SwIT 빌더 템플릿은 여기가 아니라 `config/swut_meta.json`
    #   `template_paths` 가 프로젝트별로 관리한다 — 두 곳에 두면 갈라진다.
    uds_template: str = ""
    sts_template: str = ""
    suts_template: str = ""
    sits_template: str = ""
    # 정적분석 산출물 폴더 경로(들) — 보통 회사 SCM의 '09.정적분석/01.Static Analysis' 폴더
    # 하나를 등록하면 그 안의 4종 리포트(CodeSonar PDF / QAC HIS PDF / CPD XML / CodeEye PDF)를
    # 모두 파싱한다. AnalysisSection '정적분석 불러오기'가 linked_docs.codesonar를 읽으므로,
    # 이 필드가 ScmLinkedDocs에 정의돼 있어야 model_dump 직렬화에서 살아남아 프론트가 경로를
    # 받는다(미정의 시 누락 → '등록된 정적분석 경로 없음'). scm.py의 allowed_prefixes 자동
    # 병합(linked.model_dump().values())에도 포함돼 cloudium 접근 prefix가 자동 등록된다.
    codesonar: List[str] = Field(default_factory=list)


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
    # VectorCAST 결과가 Jenkins 빌드에 없을 때(예: 부트로더/FBL 별도 산출) 읽을
    # Cloudium 경로 (vectorcast_rag.json 파일 또는 그 상위 폴더). SwUT/SwIT 로그처럼
    # 사용자가 설정의 'SCM 연결 문서 경로'에서 등록. 미지정/local 모드면 무시.
    # 부트로더/FBL/APP 등 결과가 별도로 나올 수 있어 복수 경로(vcast_log_paths)를
    # 우선 사용하고, vcast_log_path(단일)는 하위 호환을 위해 유지한다.
    vcast_log_paths: Optional[List[str]] = None
    vcast_log_path: Optional[str] = None

    @field_validator("vcast_log_paths")
    @classmethod
    def _check_vcast_log_paths(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        # rank7: 입력 표면 제한 — 개수≤16, 항목 길이≤500, 줄바꿈 금지 (DoS/주입 방어).
        if v is None:
            return v
        if len(v) > 16:
            raise ValueError("vcast_log_paths는 최대 16개까지 허용됩니다")
        for item in v:
            s = str(item or "")
            if len(s) > 500:
                raise ValueError("vcast_log_paths 항목 길이는 500자 이하여야 합니다")
            if "\n" in s or "\r" in s:
                raise ValueError("vcast_log_paths 항목에 줄바꿈 금지")
        return v

    @field_validator("vcast_log_path")
    @classmethod
    def _check_vcast_log_path(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        s = str(v)
        if len(s) > 500:
            raise ValueError("vcast_log_path 길이는 500자 이하여야 합니다")
        if "\n" in s or "\r" in s:
            raise ValueError("vcast_log_path에 줄바꿈 금지")
        return v


class CodeSonarRequest(BaseModel):
    """CodeSonar(정적분석) PDF 로드 요청 — SCM 등록 폴더(또는 PDF) 경로 목록.

    paths 각 항목은 CodeSonar PDF 파일이거나 그 상위 폴더(재귀 탐색)이다. cloudium 모드면
    worker IPC로 read. 미지정/local 모드면 빈 결과.
    """

    paths: List[str] = []

    @field_validator("paths")
    @classmethod
    def _check_paths(cls, v: List[str]) -> List[str]:
        # vcast_log_paths와 동일한 입력 표면 제한(DoS/주입 방어).
        if v is None:
            return []
        if len(v) > 16:
            raise ValueError("paths는 최대 16개까지 허용됩니다")
        for item in v:
            s = str(item or "")
            if len(s) > 500:
                raise ValueError("paths 항목 길이는 500자 이하여야 합니다")
            if "\n" in s or "\r" in s:
                raise ValueError("paths 항목에 줄바꿈 금지")
        return v


class JenkinsCallTreeRequest(JenkinsReportRequest):
    source_root: Optional[str] = None
    entry: str = Field("", max_length=4096)
    all_roots: bool = False  # True면 entry 무시하고 in-degree 0 함수(+순환 대표)를 자동 루트로 전체 forest 구성
    reverse: bool = False     # True면 호출 그래프 반전 → '누가 이 함수를 호출하나(called-by)' 역방향 트리
    max_depth: int = Field(5, ge=1, le=20)
    include_paths: List[str] = []
    exclude_paths: List[str] = []
    max_files: int = Field(2000, ge=1, le=10000)
    include_external: bool = False
    compile_commands_path: Optional[str] = None
    output_format: str = "json"
    engine: str = "precise"  # "precise"(tree-sitter) | "regex". precise 미가용 시 자동 regex 폴백.
    external_map: List[Dict[str, Any]] = []
    html_template: Optional[str] = Field(None, max_length=200000)


class CallTreePreviewRequest(BaseModel):
    call_tree: Dict[str, Any]
    html_template: Optional[str] = Field(None, max_length=200000)


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
    text: str = Field("", max_length=8000)


class ChatJenkinsConfig(BaseModel):
    job_url: str = ""
    cache_root: str = ""
    build_selector: str = "lastSuccessfulBuild"

    @field_validator("job_url")
    @classmethod
    def _validate_job_url(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            return v
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("job_url must start with http:// or https://")
        if len(v) > 2000:
            raise ValueError("job_url too long")
        return v


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
    question: str = Field(..., max_length=8000)
    session_id: Optional[str] = None
    report_dir: Optional[str] = None
    llm_model: Optional[str] = None
    oai_config_path: Optional[str] = None
    ui_context: Optional[Dict[str, Any]] = None
    history: List[ChatHistoryItem] = Field(default_factory=list, max_length=200)
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
    title: str = Field(..., max_length=500)


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


class ImpactAiGuideRequest(BaseModel):
    """POST /api/impact/ai-guide 입력 — 과거 raw Request.json()으로 무검증 수신하던 것을
    타입 계약으로 승격(analyze와 대칭). generate_impact_guide가 shape 세부는 처리하므로
    값 타입은 느슨하게 두되 최상위 필드/타입만 강제한다."""
    changed_types: Dict[str, Any] = Field(default_factory=dict)
    impact_groups: Dict[str, Any] = Field(default_factory=dict)
    by_name: Dict[str, Any] = Field(default_factory=dict)


class ImpactExplainChangeRequest(BaseModel):
    """POST /api/impact/explain-change 입력 — 단일 함수 변경의 자연어 설명(Gemini).

    선언 원문(before/after)은 UI가 change_details에서 넘긴 svn diff 원문. 값 길이는 상한을
    둬 과대 페이로드/프롬프트 남용을 막는다(선언 라인 수준이라 4000자면 충분).
    function_diff는 함수 본문 변경 hunk(BODY 함수도 실제 코드 근거 제공) — 서버에서 60줄 cap된
    값이라 8000자면 충분하다."""
    function: str = Field(default="", max_length=200)
    change_type: str = Field(default="", max_length=40)
    before: str = Field(default="", max_length=4000)
    after: str = Field(default="", max_length=4000)
    function_diff: str = Field(default="", max_length=8000)
    asil: str = Field(default="", max_length=20)
    module: str = Field(default="", max_length=200)
    requirements: List[str] = Field(default_factory=list, max_length=20)
    # 영향 함수의 현재 문서 내용(원문) — LLM이 '원문→제안'을 실제 문장 근거로 생성.
    # 프론트가 docContentFor()로 조립(uds/sds/suts + sts/sits TC). 값은 서버 파싱 단계에서
    # 이미 캡된 내용이고, 소비처(explain_function_change)가 재차 캡하므로 여기선 dict로 수용.
    doc_content: Dict[str, Any] = Field(default_factory=dict)
    # 간접영향 근거 — {hop, via, seed}. 간접(비변경) 함수가 "왜 영향받는지"(경유 노드·최초 변경함수)를
    # LLM이 콜체인 계약 유지 관점으로 설명하게 한다. 직접 함수는 빈 dict. 값은 함수명 문자열이라 소규모.
    impact_path: Dict[str, Any] = Field(default_factory=dict)
    # 비의미 변경(주석/포맷/이동 only) — True면 LLM에 '문서 수정 불필요'를 지시하고 신규 TC·문서 편집을
    # 제안하지 않게 한다(프론트 extractDiffElements.commentOnly/noSemanticChange 파생). 결정론 억제와 짝.
    no_semantic_change: bool = Field(default=False)


class ImpactDocDraftRequest(BaseModel):
    """POST /api/impact/doc-draft 입력 — 한 함수의 **전체** 문서 초안(온디맨드).

    job JSON에는 요약(SUTS 10 시퀀스 / SITS 6 서브케이스)만 싣고, 사용자가 '전체 보기'를
    누를 때만 생성기 기본값(24 / 14) 전량을 만든다 — 전부 job에 실으면 페이로드가 폭증한다.
    소스가 미해결(cloudium)이면 문서 원문 기준으로 자동 폴백하고 `source`로 근거를 밝힌다.
    """
    job_id: str = Field(default="", max_length=200)
    function: str = Field(default="", max_length=200)
    doc: str = Field(default="suts", max_length=10)


class ImpactDocProseRequest(BaseModel):
    """POST /api/impact/doc-prose 입력 — 결정론 초안에 붙일 **서술문만** 생성(선택 기능).

    값(경계값·Input/Expected·TC ID·판정)은 결정론이 소유하고 AI가 바꾸지 않는다. 여기 오는
    `deterministic`은 프론트가 이미 화면에 그린 초안 데이터 그대로이며, 서버는 그 안에 등장한
    숫자·식별자만 허용 집합으로 삼아 응답을 사후 검사한다(환각 필드 폐기).
    """
    function: str = Field(default="", max_length=200)
    signature: str = Field(default="", max_length=4000)
    function_diff: str = Field(default="", max_length=8000)
    # 결정론 초안(문서별 노드 + 표 행). 프롬프트 주입 전 12000자로 자르지만, 그 절단은 **직렬화
    # 이후**에 일어나므로 대용량 body가 그대로 파싱·직렬화된다 — 입구에서 크기를 막는다.
    deterministic: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("deterministic")
    @classmethod
    def _cap_deterministic(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """직렬화 크기 상한(256KB). 프론트가 보내는 실측은 수 KB 수준이라 정상 사용엔 무영향."""
        try:
            size = len(json.dumps(v, ensure_ascii=False))
        except (TypeError, ValueError) as exc:
            raise ValueError("deterministic must be JSON-serializable") from exc
        if size > 256_000:
            raise ValueError(f"deterministic payload too large: {size} bytes (max 256000)")
        return v


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
    # list 필드 DoS 캡 (reviewer WARNING — deviation_cases/log_folders 등 코드베이스
    # 컨벤션 일치). 인증 뒤이고 frontend가 echo하는 자기 데이터지만, 항목당 nested
    # Any + 행마다 re.findall O(n) 결합 시 단일 요청으로 worker 점유 가능. 캡은 실데이터
    # 상한(vcast 함수 ~1k, per-실행 fallback 시 ~8k)의 넉넉한 배수로 정상 회귀 없음.
    requirement_items: List[Dict[str, Any]] = Field(default_factory=list, max_length=20000)
    mapping_pairs: List[Dict[str, Any]] = Field(default_factory=list, max_length=20000)
    vcast_rows: List[Dict[str, Any]] = Field(default_factory=list, max_length=50000)
    sds_pairs: List[Dict[str, Any]] = Field(default_factory=list, max_length=20000)   # SDS component↔requirement mapping
    sits_rows: List[Dict[str, Any]] = Field(default_factory=list, max_length=50000)   # SITS TC↔requirement mapping
    # 전체 UDS 함수 인벤토리(함수명+SwUFn ID) — extract-mapping이 설계 req 참조 없는 함수까지
    # 모아 전달. SDS→UDS bridge가 전체 함수를 매칭하도록 매트릭스 uds_all_funcs를 시드.
    # UDS 함수 ~1k(이름+ID 2배=~2k) 상한의 넉넉한 배수.
    uds_function_ids: List[str] = Field(default_factory=list, max_length=20000)
    # ASIL 결합(P5) — {컴포넌트/함수명(lower): ASIL}. SDS 추출(component_asil)에서 echo.
    # 매트릭스가 요구사항별 ASIL(연결 컴포넌트 max)을 도출해 행/링크테이블에 부착.
    # 컴포넌트 ~1k(SwCom+함수)의 넉넉한 배수 상한.
    component_asil: Dict[str, str] = Field(default_factory=dict, max_length=20000)
    # SwUDS 문서 직독 함수 ASIL — {함수명(lower): ASIL}. uds extract-mapping이 v3.02 kv-표에서
    # 추출해 echo. 매트릭스가 comp_asil_map에 max-merge(SDS 컴포넌트만으론 UDS 함수 안전등급이
    # 누락돼 요구사항 ASIL under-report). 함수 ~1k의 넉넉한 배수 상한(component_asil과 동형).
    uds_function_asil: Dict[str, str] = Field(default_factory=dict, max_length=20000)
    # 시스템 레벨 인터페이스 밴드 — hsis extract가 요구사항↔인터페이스 신호(HSI_xx/SW변수)로 전달.
    # 신호 ~수백 행 상한의 넉넉한 배수.
    hsis_pairs: List[Dict[str, Any]] = Field(default_factory=list, max_length=20000)
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
      - log_folders: 최대 8개, 항목별 maxlen 500 + 줄바꿈 금지 (B2 — APP+BOOT 다중 폴더)
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
    # B2 — 다중 log_folder (예: KJPDS02 APP+BOOT 분리 폴더 통합 빌드).
    # 비어있지 않으면 log_folder(단일)보다 우선. 항목별 검증은 기존 log_folder
    # 패턴 동일 적용 (maxlen 500 + 줄바꿈 금지 — _validate_log_folders) + 최대 8개.
    log_folders: Optional[List[str]] = Field(None, max_length=8)
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

    @field_validator("log_folders")
    @classmethod
    def _validate_log_folders(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """B2 — 기존 log_folder 검증 패턴(maxlen 500 + 줄바꿈 금지)을 항목별 적용.

        최대 8개 제한은 Field(max_length=8)가 처리. 본 validator는 항목 내부 검증.
        """
        if not v:
            return v
        for i, item in enumerate(v):
            if len(item) > 500:
                raise ValueError(
                    f"log_folders[{i}]: 길이 ≤ 500 필요 (got {len(item)})"
                )
            if "\n" in item or "\r" in item:
                raise ValueError(
                    f"log_folders[{i}]: 줄바꿈 문자 금지 — 단일 라인 필요"
                )
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
    # B2 대칭 (SwIT) — 다중 log_folder (예: KJPDS02 PV APP+BOOT 분리 폴더 통합 빌드).
    # 비어있지 않으면 log_folder(단일)보다 우선. SwUTBuildRequest.log_folders와
    # 동일 정책: 최대 8개 + 항목별 maxlen 500 + 줄바꿈 금지 (_validate_swit_log_folders).
    log_folders: Optional[List[str]] = Field(None, max_length=8)
    # 51차 — Coverage / SITR 양식 분리 (이전 단일 template_path). 둘 다 비면 config fallback.
    coverage_template_path: str = Field("", max_length=500)
    sitr_template_path: str = Field("", max_length=500)
    # SwITCR comprehensive result template and optional SwITCV/SwITR evidence paths.
    switcr_template_path: str = Field("", max_length=500)
    switcv_path: str = Field("", max_length=500)
    switr_path: str = Field("", max_length=500)
    fault_injection_result_path: str = Field("", max_length=500)
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
                     "switcr_template_path", "switcv_path", "switr_path", "fault_injection_result_path",
                     "swuds_docx_path", "c_source_root", "swuts_docx_path", "hmr_html_path")
    @classmethod
    def _no_newline(cls, v):
        if v is None:
            return v
        if "\n" in v or "\r" in v:
            raise ValueError("줄바꿈 문자 금지 — 단일 라인 필요")
        return v

    @field_validator("log_folders")
    @classmethod
    def _validate_swit_log_folders(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """B2 대칭 — SwUTBuildRequest._validate_log_folders와 동일 정책.

        최대 8개 제한은 Field(max_length=8)가 처리. 본 validator는 항목 내부 검증.
        """
        if not v:
            return v
        for i, item in enumerate(v):
            if len(item) > 500:
                raise ValueError(
                    f"log_folders[{i}]: 길이 ≤ 500 필요 (got {len(item)})"
                )
            if "\n" in item or "\r" in item:
                raise ValueError(
                    f"log_folders[{i}]: 줄바꿈 문자 금지 — 단일 라인 필요"
                )
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


class SwUTDocSummaryRequest(BaseModel):
    """단일 산출물(SwUTCV Coverage .xlsx 또는 SUTR .xlsm) 직접 파싱 요청 (정합성 비교 없이).

    SwUTConsistencyCheckRequest와 달리 path 1개만 받아 해당 문서의 결과 요약만 반환.
    kind='coverage' → coverage_summary, kind='report' → sutr_summary.

    입력 표면 매트릭스:
      - path: maxlen 500, 줄바꿈 금지 (헤더 인젝션 안전), 필수
      - kind: 'coverage' | 'report' (Literal 강제)
    """
    path: str = Field(..., min_length=1, max_length=500)
    kind: Literal["coverage", "report"]

    @field_validator("path")
    @classmethod
    def _no_newline_doc_path(cls, v: str) -> str:
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


class SwITDocSummaryRequest(BaseModel):
    """단일 산출물(SwITCV Coverage .xlsx 또는 SITR .xlsm) 직접 파싱 요청 (정합성 비교 없이).

    SwUTDocSummaryRequest와 동일 패턴 — SwIT용. kind='coverage' → coverage_summary,
    kind='report' → sutr_summary(SITR 결과).

    입력 표면 매트릭스:
      - path: maxlen 500, 줄바꿈 금지 (헤더 인젝션 안전), 필수
      - kind: 'coverage' | 'report' (Literal 강제)
    """
    path: str = Field(..., min_length=1, max_length=500)
    kind: Literal["coverage", "report"]

    @field_validator("path")
    @classmethod
    def _no_newline_swit_doc_path(cls, v: str) -> str:
        if "\n" in v or "\r" in v:
            raise ValueError("줄바꿈 문자 금지 — 단일 라인 path 필요")
        return v


# ── SW Test Result Report — 전 레벨 통합 Summary (ES95411) ──────────────────
# 완성된 레벨별 산출물(SwUTCR/SwITCR/SwSA 등 — ES95411-style detail 시트 보유)을
# 파싱하여 마스터 리포트의 Summary 시트(ST/UT/IT/ET)를 채운 .xlsm을 생성. build와
# preview(JSON) 공용 request — 둘 다 동일 입력(template + source 산출물 + meta).

class SwReportBuildRequest(BaseModel):
    """ES95411 통합 Summary build/preview 요청 body.

    입력 표면 (SwUTBuildRequest 패턴 동일):
      - project_id / release_sw_version(regex) / test_date(regex) 필수
      - template_path: ES95411 양식 xlsm (비면 config 'es95411_template' fallback)
      - source_paths: 레벨별 산출물 경로 (≤16, 항목별 maxlen 500 + 줄바꿈 금지).
        비면 template 자체를 source로 사용(단일파일 Summary refresh).
      - 모든 path/문자열: maxlen 500 + 줄바꿈 금지 (헤더 인젝션 안전)

    extra='forbid': unknown 키 422 — silent wrong-pick 차단.
    """
    model_config = ConfigDict(extra="forbid")

    # 필수
    project_id: str = Field(..., min_length=1, max_length=50)
    release_sw_version: str = Field(..., pattern=r"^\d+\.\d+(\.\d+)?$")
    test_date: str = Field(..., pattern=r"^\d{2,4}[-/]\d{1,2}[-/]\d{1,2}$")

    # 입력 산출물
    template_path: str = Field("", max_length=500)
    source_paths: List[str] = Field(default_factory=list, max_length=16)

    # 헤더 블록 메타 (선택 — 비면 template 값 유지)
    project_full_name: str = Field("", max_length=200)
    asil_level: str = Field("", max_length=20)
    hw_version: str = Field("", max_length=20)
    phase: str = Field("", max_length=50)
    product: str = Field("", max_length=50)
    test_target: str = Field("", max_length=50)
    compiler: str = Field("", max_length=100)
    mcu: str = Field("", max_length=100)
    software_platform_ver: str = Field("", max_length=50)
    test_engineer: str = Field("", max_length=100)
    reviewer_override: str = Field("", max_length=100)
    approver_override: str = Field("", max_length=100)
    doc_id_sequence: str = Field("", pattern=r"^\d*$")
    validation_date: str = Field("", pattern=r"^$|^\d{2,4}[-/]\d{1,2}[-/]\d{1,2}$")

    @field_validator(
        "project_id", "template_path", "project_full_name", "asil_level",
        "hw_version", "phase", "product", "test_target", "compiler", "mcu",
        "software_platform_ver", "test_engineer", "reviewer_override",
        "approver_override",
    )
    @classmethod
    def _no_newline_swreport(cls, v: str) -> str:
        if v and ("\n" in v or "\r" in v):
            raise ValueError("줄바꿈 문자 금지 — 단일 라인 필요")
        return v

    @field_validator("source_paths")
    @classmethod
    def _validate_source_paths(cls, v: List[str]) -> List[str]:
        for i, item in enumerate(v):
            if len(item) > 500:
                raise ValueError(f"source_paths[{i}]: 길이 ≤ 500 필요 (got {len(item)})")
            if "\n" in item or "\r" in item:
                raise ValueError(f"source_paths[{i}]: 줄바꿈 문자 금지 — 단일 라인 path 필요")
        return v
