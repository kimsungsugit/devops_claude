# tests/unit/test_workflow_ai.py
# -*- coding: utf-8 -*-
"""
workflow/ai.py 단위 테스트
- LLM 설정 로딩 (load_oai_config, load_oai_configs)
- _strip_c_comments, _param_placeholder 순수 함수 검증
- _parse_search_replace_blocks 검증
- llm_call 모킹을 통한 반환값 구조 테스트

요구사항 추적: SRS-AI-001 (LLM 호출 안정성), SRS-AI-002 (설정 로딩 방어)
"""
from __future__ import annotations

import json
import sys

# ---------------------------------------------------------------------------
# 테스트 대상 임포트 (의존성 최소화)
# ---------------------------------------------------------------------------
# workflow/__init__.py 가 pipeline/common/ai 를 연쇄 임포트하므로
# workflow 패키지를 빈 ModuleType으로 등록하여 __init__ 실행을 방지하고,
# 외부 의존성(analysis_tools, config 등)은 개별 stub으로 처리한다.
import types  # noqa: E402
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# Snapshot of `config` attributes that this stub overwrites — restored in a
# module-scoped teardown so other tests in the suite don't observe poisoned
# values (notably resolve_oai_api_keys=None breaking test_report_gen_cross).
_CONFIG_ATTRS_TO_SNAPSHOT = (
    "DEFAULT_OAI_CONFIG_PATH",
    "DEFAULT_LLM_MODEL",
    "DEFAULT_LLM_NUM_PREDICT",
    "DEFAULT_LLM_TEMPERATURE",
    "DEFAULT_LLM_TEMPERATURE_GEMINI",
    "LLM_MODEL_POLICIES",
    "LLM_TOKEN_ESTIMATE_MARGIN_GEMINI",
    "LLM_TOKEN_ESTIMATE_MARGIN_DEFAULT",
    "resolve_oai_api_keys",
    "AGENT_PATCH_MODE_DEFAULT",
    "AGENT_PATCH_MODES",
    "AGENT_PATCH_DENY_PREFIXES",
    "AGENT_PATCH_MAX_CHANGE_LINES",
    "AGENT_PATCH_MAX_REPLACE_CHARS",
)
_SENTINEL_MISSING = object()
_CONFIG_SNAPSHOT: Dict[str, Any] = {}
# Track whether `config` was a real module before _ensure_stubs ran. If it was
# absent (and we're about to install a MagicMock), the teardown must POP the
# MagicMock from sys.modules — otherwise downstream tests that do
# `from config import X` get MagicMock children instead of the real module.
_CONFIG_WAS_REAL: bool = False


def _ensure_stubs() -> None:
    """테스트 전용 stub 모듈 등록 — workflow.__init__ 실행 방지 포함."""
    # 외부 의존성 stub
    global _CONFIG_WAS_REAL
    _existing = sys.modules.get("config")
    _CONFIG_WAS_REAL = isinstance(_existing, types.ModuleType)
    _config = _existing if _CONFIG_WAS_REAL else MagicMock()
    # Snapshot the real config's attributes before overwriting, so the
    # module-scoped fixture below can restore them at teardown. Only meaningful
    # when the real module was already imported — otherwise the snapshot is of
    # MagicMock children and gets discarded by the teardown sys.modules.pop.
    if _CONFIG_WAS_REAL:
        for _attr in _CONFIG_ATTRS_TO_SNAPSHOT:
            _CONFIG_SNAPSHOT.setdefault(
                _attr, getattr(_config, _attr, _SENTINEL_MISSING)
            )
    _config.DEFAULT_OAI_CONFIG_PATH = None  # type: ignore[attr-defined]
    _config.DEFAULT_LLM_MODEL = "gpt-4.1-mini"  # type: ignore[attr-defined]
    _config.DEFAULT_LLM_NUM_PREDICT = 8192  # type: ignore[attr-defined]
    _config.DEFAULT_LLM_TEMPERATURE = 0.3  # type: ignore[attr-defined]
    _config.DEFAULT_LLM_TEMPERATURE_GEMINI = 1.0  # type: ignore[attr-defined]
    _config.LLM_MODEL_POLICIES = {}  # type: ignore[attr-defined]
    _config.LLM_TOKEN_ESTIMATE_MARGIN_GEMINI = 1.25  # type: ignore[attr-defined]
    _config.LLM_TOKEN_ESTIMATE_MARGIN_DEFAULT = 1.1  # type: ignore[attr-defined]
    # Only force resolve_oai_api_keys=None when config is a MagicMock — calling
    # a MagicMock-returned callable would yield a MagicMock chain that breaks
    # workflow.ai.load_oai_configs. When the real config is loaded, leave its
    # resolve_oai_api_keys callable alone: pytest collects ALL test modules
    # before running, so a `_config.resolve_oai_api_keys = None` here would
    # poison the real `config` module for tests collected later but executed
    # earlier (e.g. test_report_gen_cross::test_resolve_oai_api_keys).
    if not _CONFIG_WAS_REAL:
        _config.resolve_oai_api_keys = None  # type: ignore[attr-defined]
    _config.AGENT_PATCH_MODE_DEFAULT = "auto"  # type: ignore[attr-defined]
    _config.AGENT_PATCH_MODES = ("auto", "review", "off")  # type: ignore[attr-defined]
    _config.AGENT_PATCH_DENY_PREFIXES = (  # type: ignore[attr-defined]
        "libs/pico-sdk", ".devops_pro_cache", "reports", "build",
    )
    _config.AGENT_PATCH_MAX_CHANGE_LINES = 400  # type: ignore[attr-defined]
    _config.AGENT_PATCH_MAX_REPLACE_CHARS = 80000  # type: ignore[attr-defined]
    sys.modules["config"] = _config

    sys.modules.setdefault("analysis_tools", MagicMock())
    sys.modules.setdefault("utils", MagicMock())
    sys.modules.setdefault(
        "utils.log",
        MagicMock(get_logger=MagicMock(return_value=MagicMock())),
    )

    # workflow 패키지: 빈 ModuleType으로 등록하여 __init__ 실행 방지
    if not isinstance(sys.modules.get("workflow"), types.ModuleType) or \
            getattr(sys.modules.get("workflow"), "__path__", None) is None:
        _wf = types.ModuleType("workflow")
        _wf.__path__ = [str(Path(__file__).resolve().parents[2] / "workflow")]  # type: ignore[assignment]
        _wf.__package__ = "workflow"
        sys.modules["workflow"] = _wf

    # workflow 하위 모듈 stub
    sys.modules["workflow.common"] = MagicMock(  # type: ignore[assignment]
        read_excerpt=MagicMock(return_value=""),
        create_backup=MagicMock(return_value=None),
        standardize_result=MagicMock(side_effect=lambda ok, reason="", data=None: {
            "ok": ok, "reason": reason, "data": data or {},
        }),
        PipelineStopRequested=Exception,
        check_stop=MagicMock(),
    )
    sys.modules["workflow.static"] = MagicMock()  # type: ignore[assignment]


_ensure_stubs()

import workflow.ai as ai_mod  # noqa: E402 — stubs must be registered first


@pytest.fixture(autouse=True, scope="module")
def _restore_config_after_module():
    """Restore the real `config` module's attributes after this module's tests
    finish. Without this, downstream tests (e.g. test_report_gen_cross) see
    `config.resolve_oai_api_keys = None` and fail with TypeError when calling
    the stubbed-out callable. Also pops a MagicMock-stub `config` if no real
    module existed before, so later tests can do a fresh `import config`."""
    yield
    if _CONFIG_WAS_REAL:
        _config = sys.modules.get("config")
        if _config is None:
            return
        for _attr, _orig in _CONFIG_SNAPSHOT.items():
            if _orig is _SENTINEL_MISSING:
                try:
                    delattr(_config, _attr)
                except AttributeError:
                    pass
            else:
                setattr(_config, _attr, _orig)
    else:
        # Stub MagicMock was installed in sys.modules — drop it so a real
        # `import config` later in the suite re-executes config.py.
        sys.modules.pop("config", None)


# ---------------------------------------------------------------------------
# load_oai_configs / load_oai_config
# ---------------------------------------------------------------------------

class TestLoadOaiConfigs:
    """SRS-AI-002: LLM 설정 로딩 방어 로직 검증."""

    def test_없는_경로_반환값이_리스트_형태이다(self, tmp_path: Path):
        """Arrange: 존재하지 않는 파일 경로
        Act: load_oai_configs 호출
        Assert: 빈 리스트 또는 환경변수 기반 리스트 반환 (에러 없음)
        """
        # Arrange
        missing_path = str(tmp_path / "nonexistent.json")

        # Act
        result = ai_mod.load_oai_configs(missing_path)

        # Assert
        assert isinstance(result, list)

    def test_단일_객체_json이_리스트로_변환된다(self, tmp_path: Path):
        """Arrange: 단일 객체 JSON 파일
        Act: load_oai_configs 호출
        Assert: 원소 1개짜리 리스트 반환
        """
        # Arrange
        cfg_file = tmp_path / "oai_config.json"
        cfg_file.write_text(
            json.dumps({"model": "gpt-4.1-mini", "api_key": "test-key", "api_type": "openai"}),
            encoding="utf-8",
        )

        # Act
        with patch.dict("os.environ", {}, clear=False):
            result = ai_mod.load_oai_configs(str(cfg_file))

        # Assert
        assert isinstance(result, list)
        assert any(item.get("model") == "gpt-4.1-mini" for item in result)

    def test_리스트_json이_그대로_반환된다(self, tmp_path: Path):
        """Arrange: 복수 설정 JSON 배열
        Act: load_oai_configs 호출
        Assert: 모든 항목이 포함된 리스트 반환
        """
        # Arrange
        configs = [
            {"model": "gpt-4.1-mini", "api_key": "key1", "api_type": "openai"},
            {"model": "gemini-2.0-flash", "api_key": "key2", "api_type": "gemini"},
        ]
        cfg_file = tmp_path / "oai_config.json"
        cfg_file.write_text(json.dumps(configs), encoding="utf-8")

        # Act
        with patch.dict("os.environ", {}, clear=False):
            result = ai_mod.load_oai_configs(str(cfg_file))

        # Assert
        assert isinstance(result, list)
        models = [item.get("model") for item in result]
        assert "gpt-4.1-mini" in models
        assert "gemini-2.0-flash" in models

    def test_잘못된_json_파일은_빈_리스트를_반환한다(self, tmp_path: Path):
        """Arrange: 유효하지 않은 JSON 파일
        Act: load_oai_configs 호출
        Assert: 예외 없이 빈 리스트 반환 (방어적 처리)
        """
        # Arrange
        cfg_file = tmp_path / "bad.json"
        cfg_file.write_text("{ invalid json !!!", encoding="utf-8")

        # Act
        result = ai_mod.load_oai_configs(str(cfg_file))

        # Assert
        assert result == []

    def test_경로_없음_None_전달시_리스트_반환(self):
        """Arrange: path=None
        Act: load_oai_configs(None) 호출
        Assert: 리스트 반환 (환경변수 기반 또는 빈 리스트)
        """
        # Arrange & Act
        result = ai_mod.load_oai_configs(None)

        # Assert
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# _strip_c_comments (순수 함수)
# ---------------------------------------------------------------------------

class TestStripCComments:
    """SRS-AI-010: C 주석 제거 유틸리티 검증."""

    def test_블록_주석이_제거된다(self):
        """Arrange: /* ... */ 블록 주석이 포함된 코드
        Act: _strip_c_comments 호출
        Assert: 주석 내용이 제거된다
        """
        # Arrange
        code = "int x = /* 초기값 */ 0;"

        # Act
        result = ai_mod._strip_c_comments(code)

        # Assert
        assert "초기값" not in result
        assert "int x =" in result

    def test_줄_주석이_제거된다(self):
        """Arrange: // 줄 주석이 포함된 코드
        Act: _strip_c_comments 호출
        Assert: 주석이 제거된다
        """
        # Arrange
        code = "int y = 1; // 변수 선언\nint z = 2;"

        # Act
        result = ai_mod._strip_c_comments(code)

        # Assert
        assert "변수 선언" not in result
        assert "int z = 2;" in result

    def test_주석_없는_코드는_그대로_반환된다(self):
        """Arrange: 주석 없는 순수 C 코드
        Act: _strip_c_comments 호출
        Assert: 코드가 변경되지 않는다 (공백 정규화 제외)
        """
        # Arrange
        code = "void foo(int a, int b) { return; }"

        # Act
        result = ai_mod._strip_c_comments(code)

        # Assert
        assert "foo" in result
        assert "return" in result

    def test_빈_문자열_입력시_빈_문자열_반환(self):
        """경계값: 빈 문자열 입력
        Act: _strip_c_comments("") 호출
        Assert: 빈 문자열 반환
        """
        # Arrange & Act
        result = ai_mod._strip_c_comments("")

        # Assert
        assert result == ""


# ---------------------------------------------------------------------------
# _param_placeholder (순수 함수) — 경계값 분석
# ---------------------------------------------------------------------------

class TestParamPlaceholder:
    """SRS-AI-011: C 파라미터 플레이스홀더 생성 — BVA/EP 기반.
    조건 조합:
    - void 파라미터 → (None, None)
    - 가변인자 '...' → ('0', None)
    - 포인터/배열 타입 → 버퍼 타입 반환
    - 스칼라 타입 → '0' 또는 'false'
    """

    def test_void_파라미터는_None_쌍을_반환한다(self):
        # Arrange & Act
        val, kind = ai_mod._param_placeholder("void")

        # Assert
        assert val is None
        assert kind is None

    def test_빈_문자열은_None_쌍을_반환한다(self):
        """경계값: 빈 입력"""
        # Arrange & Act
        val, kind = ai_mod._param_placeholder("")

        # Assert
        assert val is None
        assert kind is None

    def test_가변인자는_0을_반환한다(self):
        # Arrange & Act
        val, kind = ai_mod._param_placeholder("...")

        # Assert
        assert val == "0"
        assert kind is None

    def test_uint8_t_포인터는_buf_u8a를_반환한다(self):
        # Arrange & Act
        val, kind = ai_mod._param_placeholder("uint8_t *data")

        # Assert
        assert val == "buf_u8a"
        assert kind == "u8"

    def test_uint16_t_포인터는_buf_u16a를_반환한다(self):
        # Arrange & Act
        val, kind = ai_mod._param_placeholder("uint16_t *buf")

        # Assert
        assert val == "buf_u16a"
        assert kind == "u16"

    def test_bool_파라미터는_false를_반환한다(self):
        # Arrange & Act
        val, kind = ai_mod._param_placeholder("bool enable")

        # Assert
        assert val == "false"
        assert kind is None

    def test_일반_int_스칼라는_0을_반환한다(self):
        # Arrange & Act
        val, kind = ai_mod._param_placeholder("int count")

        # Assert
        assert val == "0"
        assert kind is None


# ---------------------------------------------------------------------------
# _parse_search_replace_blocks (순수 함수)
# ---------------------------------------------------------------------------

class TestParseSearchReplaceBlocks:
    """SRS-AI-012: SEARCH/REPLACE 블록 파싱 검증."""

    def test_유효한_블록_하나를_파싱한다(self):
        """Arrange: 올바른 형식의 SEARCH/REPLACE 블록
        Act: _parse_search_replace_blocks 호출
        Assert: 파일명, search, replace가 올바르게 파싱된다
        """
        # Arrange
        reply = (
            "<<<<SEARCH_BLOCK[src/main.c]\n"
            "old code\n"
            "<<<<REPLACE_BLOCK[src/main.c]\n"
            "new code\n"
        )

        # Act
        blocks = ai_mod._parse_search_replace_blocks(reply)

        # Assert
        assert len(blocks) == 1
        assert blocks[0]["file"] == "src/main.c"
        assert "old code" in blocks[0]["search"]
        assert "new code" in blocks[0]["replace"]

    def test_블록_없는_텍스트는_빈_리스트를_반환한다(self):
        """경계값: 블록이 없는 일반 텍스트
        Act: _parse_search_replace_blocks 호출
        Assert: 빈 리스트 반환
        """
        # Arrange
        reply = "일반 텍스트입니다. 블록 없음."

        # Act
        blocks = ai_mod._parse_search_replace_blocks(reply)

        # Assert
        assert blocks == []

    def test_빈_문자열은_빈_리스트를_반환한다(self):
        """경계값: 빈 입력"""
        # Arrange & Act
        blocks = ai_mod._parse_search_replace_blocks("")

        # Assert
        assert blocks == []


# ---------------------------------------------------------------------------
# llm_call — 빈 설정 방어 처리
# ---------------------------------------------------------------------------

class TestLlmCallDefensive:
    """SRS-AI-001: llm_call 방어적 처리 — 잘못된 설정 입력 시 None 반환."""

    def test_빈_설정_dict_전달시_None을_반환한다(self):
        """Arrange: cfg={}
        Act: llm_call({}, messages) 호출
        Assert: None 반환 (에러 없음)
        """
        # Arrange
        cfg: Dict[str, Any] = {}
        messages = [{"role": "user", "content": "hello"}]

        # Act
        result = ai_mod.llm_call(cfg, messages)

        # Assert
        assert result is None

    def test_None_설정_전달시_None을_반환한다(self):
        """경계값: cfg=None
        Act: llm_call(None, messages) 호출
        Assert: None 반환 (에러 없음)
        """
        # Arrange
        messages = [{"role": "user", "content": "hello"}]

        # Act
        result = ai_mod.llm_call(None, messages)

        # Assert
        assert result is None

    def test_meta_out에_에러_키가_기록된다(self):
        """Arrange: cfg={}, meta_out 딕셔너리 제공
        Act: llm_call 호출
        Assert: meta_out['error'] == 'empty_config'
        """
        # Arrange
        cfg: Dict[str, Any] = {}
        messages = [{"role": "user", "content": "ping"}]
        meta_out: Dict[str, Any] = {}

        # Act
        ai_mod.llm_call(cfg, messages, meta_out=meta_out)

        # Assert
        assert meta_out.get("error") == "empty_config"


# ---------------------------------------------------------------------------
# 입력 절단 보고 — 잘랐다는 사실을 감추지 않는다 (계획서 후보 17)
# ---------------------------------------------------------------------------

class _StopBeforeProvider(Exception):
    """provider 진입 직전에 끊기 위한 sentinel — 네트워크를 타지 않는다."""


class TestInputTrimIsReported:
    """**가장 큰 프롬프트를 내는 경로에서 절단이 완전히 침묵했다** (2026-08-03 실측).

    - 경고는 `if total >= warn_threshold and log_dir:` 라 **`log_dir` 이 없으면 안 찍힌다**.
      그런데 `workflow/uds_ai.py:341` 이 바로 `log_dir=None` 으로 부른다.
    - `meta_out["input_tokens_est"]` 는 **절단 뒤** 값이라 호출자는 원래 크기를 모른다
      ("원래 그 크기였다"와 구분 불가).
    - 절단 루프는 20회 제한이라 못 내려오면 **초과분을 그대로 보내는데** 그 사실도 안 남았다.

    ⚠ 곁가지 실측: `config.py` 의 `max_input_tokens_by_stage` 는
    `build_fix`/`syntax_fix`/`static`/`domain_tests`/`plan_repair`/`test_plan`/`test_code`
    만 담는데, `uds_ai` 가 쓰는 stage 는 `uds_analysis`·`uds_audit`·`uds_logic`·
    `uds_review`·`uds_sections` 5종이라 **stage 별 상한이 하나도 안 걸린다**(전역 상한만 적용).
    상한 **값**을 정하는 건 정책이라 여기서 정하지 않는다 — 잘랐다는 **사실**만 못박는다.
    """

    def _run(self, monkeypatch, *, stage, limit, content):
        monkeypatch.setattr(
            ai_mod, "sanitize_messages",
            lambda _m: (_ for _ in ()).throw(_StopBeforeProvider()),
        )
        meta: Dict[str, Any] = {}
        try:
            ai_mod.llm_call(
                {"provider": "gemini", "model": "gemini-3.5-flash-lite",
                 "api_key": "x", "max_input_tokens": limit},
                [{"role": "system", "content": "sys"},
                 {"role": "user", "content": content}],
                stage=stage,
                meta_out=meta,
            )
        except _StopBeforeProvider:
            pass
        return meta

    def test_절단되면_원래_크기와_함께_보고된다(self, monkeypatch):
        meta = self._run(monkeypatch, stage="uds_sections", limit=200, content="x" * 40_000)
        trim = meta.get("input_trim")
        assert trim, "input_trim 키 자체가 없다 — 절단 사실이 사라졌다"
        assert trim["applied"] is True
        assert trim["before_tokens_est"] > trim["after_tokens_est"], trim
        assert trim["limit_tokens"] == 200
        assert any("input_truncated" in w for w in meta.get("warnings", [])), meta.get("warnings")

    def test_안_잘렸으면_키는_남되_applied_는_False(self, monkeypatch):
        """키 부재를 '안 잘렸다' 로 읽으면 구/신 소비자가 갈린다 — 항상 키를 남긴다."""
        meta = self._run(monkeypatch, stage="uds_sections", limit=1_000_000, content="short")
        assert meta.get("input_trim") == {"applied": False}
        assert not [w for w in meta.get("warnings", []) if "input_truncated" in w]

    def test_예산_아래로_못_내리면_그_사실도_남는다(self, monkeypatch):
        """20회 루프로도 안 되면 초과분을 그대로 보낸다 — 조용히 보내면 안 된다."""
        meta = self._run(monkeypatch, stage="uds_sections", limit=1, content="y" * 40_000)
        trim = meta["input_trim"]
        assert trim["applied"] is True
        assert trim["gave_up_over_limit"] is True, trim
        assert any("초과분 그대로 전송" in w for w in meta.get("warnings", [])), meta.get("warnings")

    def test_uds_stage_는_stage별_상한이_안_걸린다(self):
        """실측 고정 — 이 사실이 바뀌면(=상한을 넣으면) 이 테스트가 알려 준다.

        ⚠ 이 파일은 맨 위에서 **stub config** 를 설치해 `LLM_MODEL_POLICIES = {}` 로
        만든다. 그래서 `import config` 로 읽으면 항상 빈 dict 를 보고 **아무것도
        검증하지 못한다**. 실제 `config.py` 를 경로로 직접 읽는다.
        """
        import importlib.util

        real = Path(__file__).resolve().parents[2] / "config.py"
        spec = importlib.util.spec_from_file_location("_real_config_for_test", real)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)   # type: ignore[union-attr]

        caps = mod.LLM_MODEL_POLICIES["gemini-3.5-flash-lite"]["max_input_tokens_by_stage"]
        uds_stages = {"uds_analysis", "uds_audit", "uds_logic", "uds_review", "uds_sections"}
        assert not (uds_stages & set(caps)), (
            f"uds stage 에 상한이 생겼다(정책 변경) — 계획서 후보 17 을 갱신할 것: "
            f"{sorted(uds_stages & set(caps))}"
        )
