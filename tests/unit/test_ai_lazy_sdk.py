# tests/unit/test_ai_lazy_sdk.py
"""Gemini SDK 지연 로딩 계약.

## 실측 (2026-07-31)

`workflow/ai.py` 가 Gemini SDK **두 개를 모듈 레벨에서 즉시** import 했다:

| 대상 | 비용(3회 재현, warm cache) |
|---|---|
| `google.genai` | **≈ 36초** |
| `google.generativeai` (**수명 종료**) | **≈ 10초** |
| 합계 여파: `backend.helpers.uds` import | **52.7초** |

그 결과 **백엔드 기동**·**모든 pytest 워커**·`workflow.ai` 를 스치는 모든 스크립트가
LLM 을 한 번도 호출하지 않아도 46초를 지불했다. 게다가 `google.generativeai` 는
*"All support for the google.generativeai package has ended"* 를 매 실행마다 찍는
**수명이 끝난 패키지**이고, 실제 사용처는 legacy fallback 한 곳뿐이다.

같은 저장소의 `workflow/llm_adapters.py:111` 은 **이미 함수 안에서 지연 import** 한다 —
여기만 즉시 로드였다(판정/패턴 불일치).

## 유지해야 하는 계약

`workflow/pipeline.py` 는 `getattr(ai, "genai_new", None) is None` 으로 **가용성**을
묻는다. 그래서 이름을 없앨 수 없다 → PEP 562 모듈 `__getattr__` 로 이름은 유지하되
접근 시점에 로드한다(가용성 판단은 LLM 을 쓰기 직전이므로 그때 내는 비용이 맞다).

⚠ 모듈 `__getattr__` 은 **모듈 밖** 접근에만 불린다. 모듈 **내부**의 전역 조회에는
안 걸리므로 내부 참조는 전부 `_sdk("...")` 를 쓴다 — 이 파일이 그것도 고정한다.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import workflow.ai as ai

_AI_SRC = Path(ai.__file__)


# --------------------------------------------------------------
# 1. 즉시 로드가 되살아나지 않아야 한다
# --------------------------------------------------------------

class TestNotEagerlyImported:
    def test_importing_workflow_ai_does_not_load_the_sdks(self):
        """**이 라운드의 본체.** 별도 프로세스에서 확인한다 — 같은 프로세스는 다른
        테스트가 이미 SDK 를 끌어왔을 수 있어 판정이 오염된다.

        뮤테이션: 모듈 레벨 `from google import genai as genai_new` 를 되살리면 실패.
        """
        code = (
            "import sys; import workflow.ai; "
            "print(','.join(m for m in ('google.genai','google.generativeai') "
            "if m in sys.modules))"
        )
        r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True, timeout=300, cwd=str(Path.cwd()))
        assert r.returncode == 0, r.stderr[-800:]
        leaked = r.stdout.strip()
        assert not leaked, f"import 만으로 SDK 가 로드됐다: {leaked}"

    def test_no_module_level_sdk_import_in_source(self):
        """AST 계약 — 빠르고 정확한 회귀 방지(위 subprocess 테스트의 보조가 아니라 짝)."""
        tree = ast.parse(_AI_SRC.read_text(encoding="utf-8"))
        offenders = []
        for node in tree.body:          # **모듈 최상위만** — 함수 안 지연 import 는 정상
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("google"):
                        offenders.append(f"L{node.lineno}: import {a.name}")
            elif isinstance(node, ast.ImportFrom):
                if str(node.module or "").startswith("google"):
                    offenders.append(f"L{node.lineno}: from {node.module}")
            elif isinstance(node, ast.Try):
                for sub in ast.walk(node):
                    if isinstance(sub, ast.ImportFrom) and str(sub.module or "").startswith("google"):
                        offenders.append(f"L{sub.lineno}: try/from {sub.module}")
                    elif isinstance(sub, ast.Import):
                        for a in sub.names:
                            if a.name.startswith("google"):
                                offenders.append(f"L{sub.lineno}: try/import {a.name}")
        assert not offenders, f"모듈 레벨 SDK import 가 되살아났다: {offenders}"


# --------------------------------------------------------------
# 2. 외부 계약(PEP 562) — pipeline 의 가용성 probe 가 계속 동작해야 한다
# --------------------------------------------------------------

@pytest.fixture
def stub_sdks(monkeypatch):
    """캐시를 **미리 채워** 실제 SDK 로드를 유발하지 않는다.

    ⚠ 이 fixture 가 없으면 `getattr(ai, "genai_new")` 하나가 실제 로드를 걸어
    **40.77초**가 든다(실측). 이 라운드가 없애려는 바로 그 비용을 테스트가 도로
    지불하는 셈이다. 여기서 검증할 것은 "`__getattr__` 이 캐시로 라우팅되는가" 이지
    "SDK 가 설치돼 있는가" 가 아니다(후자는 환경 사실이고 실호출로 확인했다).
    """
    sentinels = {n: object() for n in ai._SDK_NAMES}
    monkeypatch.setattr(ai, "_sdk_cache", dict(sentinels))
    return sentinels


class TestModuleGetattrContract:
    @pytest.mark.parametrize("name", ["genai_new", "genai_legacy",
                                      "HarmCategory", "HarmBlockThreshold"])
    def test_names_still_resolve(self, name, stub_sdks):
        """`pipeline.py` 의 `getattr(ai, "genai_new", None)` 이 계속 성립해야 한다.

        뮤테이션: `__getattr__` 을 지우면 AttributeError 로 실패.
        """
        assert getattr(ai, name, "MISSING") is stub_sdks[name]

    def test_unknown_attribute_still_raises(self):
        """음성 대조군 — `__getattr__` 이 아무 이름이나 삼키면 오타가 조용히 None 이 된다."""
        with pytest.raises(AttributeError):
            ai.definitely_not_a_real_symbol

    def test_pipeline_probe_pattern_works(self, stub_sdks):
        """`pipeline.py:2246` 이 쓰는 정확한 식."""
        available = not (getattr(ai, "genai_new", None) is None
                         and getattr(ai, "genai_legacy", None) is None)
        assert available is True

    def test_probe_reports_unavailable_when_both_missing(self, monkeypatch):
        """양쪽 다 없으면 probe 가 '미가용' 으로 읽혀야 한다(스텁 폴백 판정의 근거)."""
        monkeypatch.setattr(ai, "_sdk_cache", dict.fromkeys(ai._SDK_NAMES))
        assert getattr(ai, "genai_new", None) is None
        assert getattr(ai, "genai_legacy", None) is None

    def test_sdk_accessor_is_idempotent(self, stub_sdks):
        """로더는 한 번만 돈다 — 실패 시 36초짜리 import 를 매 접근마다 재시도하면 안 된다."""
        calls = {"n": 0}
        real = ai._load_gemini_sdks

        def _counted():
            calls["n"] += 1
            return real()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(ai, "_load_gemini_sdks", _counted)
            ai._sdk("genai_new")
            ai._sdk("genai_legacy")
        # 캐시가 이미 차 있으면 로더는 즉시 반환한다(재-import 없음)
        assert dict(ai._sdk_cache) == stub_sdks


# --------------------------------------------------------------
# 3. 내부 참조는 전부 지연 접근자를 거쳐야 한다
# --------------------------------------------------------------

class TestInternalReferencesUseAccessor:
    def test_no_bare_global_sdk_names_in_functions(self):
        """모듈 `__getattr__` 은 **내부** 전역 조회에 안 걸린다 — bare 이름은 NameError 다.

        뮤테이션: 아무 내부 참조든 `_sdk("genai_new")` 를 `genai_new` 로 되돌리면 실패.
        """
        tree = ast.parse(_AI_SRC.read_text(encoding="utf-8"))
        watched = {"genai_new", "genai_legacy", "HarmCategory", "HarmBlockThreshold"}
        offenders = []
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name in {"_load_gemini_sdks", "_sdk", "__getattr__"}:
                continue
            local = {a.arg for a in fn.args.args}
            for n in ast.walk(fn):
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                    if n.id in watched and n.id not in local:
                        offenders.append(f"{fn.name}:L{n.lineno} {n.id}")
        assert not offenders, f"지연 접근자를 안 거치는 내부 참조: {offenders}"


# --------------------------------------------------------------
# 4. 로드 실패는 조용하지 않아야 한다
# --------------------------------------------------------------

class TestFailureIsRecorded:
    def test_errors_dict_exists(self):
        """실패 사유를 담을 자리가 있어야 한다 — `None` 만 남기면 왜 없는지 알 수 없다."""
        assert isinstance(ai._sdk_errors, dict)

    def test_missing_sdk_records_reason(self, monkeypatch):
        """SDK 가 없을 때 사유가 남는지 — 실패를 `None` 으로만 접지 않는다.

        뮤테이션: `_sdk_errors[...] = ...` 를 지우면 실패.
        """
        import builtins
        real_import = builtins.__import__

        def _boom(name, *a, **kw):
            if name.startswith("google"):
                raise ImportError("시뮬레이션: SDK 미설치")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(ai, "_sdk_cache", {})
        monkeypatch.setattr(ai, "_sdk_errors", {})
        monkeypatch.setattr(builtins, "__import__", _boom)
        ai._load_gemini_sdks()
        assert ai._sdk_cache["genai_new"] is None
        assert "시뮬레이션" in ai._sdk_errors.get("genai_new", "")
        assert "시뮬레이션" in ai._sdk_errors.get("genai_legacy", "")

    def test_all_four_names_present_even_on_failure(self, monkeypatch):
        """실패해도 4개 키가 다 있어야 `_sdk()` 가 KeyError 대신 None 을 낸다."""
        import builtins
        real_import = builtins.__import__

        def _boom(name, *a, **kw):
            if name.startswith("google"):
                raise ImportError("no sdk")
            return real_import(name, *a, **kw)

        monkeypatch.setattr(ai, "_sdk_cache", {})
        monkeypatch.setattr(ai, "_sdk_errors", {})
        monkeypatch.setattr(builtins, "__import__", _boom)
        ai._load_gemini_sdks()
        assert set(ai._sdk_cache) == set(ai._SDK_NAMES)
        assert ai._sdk("HarmCategory") is None
