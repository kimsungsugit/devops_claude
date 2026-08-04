"""LLM 실패 사유가 뒤 블록에 덮여 거짓 진단이 되지 않는가 — §6 후보 16.

## 실측한 비대칭 (2026-08-04)

`llm_call` 의 Gemini 경로는 3단이다(신 SDK → legacy SDK → SDK 없음). 세 곳이 전부
`meta_out["error"]` 를 쓰는데 규약이 갈려 있었다:

    신 SDK   `meta_out["error"] = meta_out.get("error") or last_err`   ← 보존
    legacy   `meta_out["error"] = last_err`                            ← 덮어씀
    SDK 없음 `meta_out["error"] = "gemini_sdk_missing"`                ← 무조건 덮어씀

세 번째가 특히 나쁘다. 그건 시도의 **실패 사유가 아니라 상태 서술**이라, 신 SDK 가
재시도를 소진하고 legacy 가 설치돼 있지 않은 환경에서는 실제 사유(429/timeout/500)가
사라지고 **"SDK 가 설치돼 있는데 설치 안 됨"** 이라는 거짓 진단이 남는다.

소비처가 있다: `ai.py::_agent_once` 가 `reason = f"llm_error:{llm_meta.get('error')}"`
로 만들어 attempt meta 에 싣고, 그게 UDS 생성 실패 사유로 표시된다.

## 이 파일이 고정하는 계약

**먼저 난 실제 실패 사유가 이긴다.** 세 지점 모두 `meta_out.get("error") or …`.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import workflow.ai as ai


def _gemini_error_assignments() -> list[str]:
    """`llm_call` 안에서 `meta_out["error"] = …` 우변 텍스트를 순서대로 모은다."""
    tree = ast.parse(inspect.getsource(ai.llm_call))
    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for tgt in node.targets:
            if (
                isinstance(tgt, ast.Subscript)
                and isinstance(tgt.value, ast.Name)
                and tgt.value.id == "meta_out"
                and isinstance(tgt.slice, ast.Constant)
                and tgt.slice.value == "error"
            ):
                out.append(ast.unparse(node.value))
    return out


class TestErrorLabelIsNeverSilentlyReplaced:
    def test_sdk_missing_label_has_an_or_guard(self):
        """`gemini_sdk_missing` 은 상태 서술이라 실제 사유를 덮으면 안 된다."""
        assigns = _gemini_error_assignments()
        hits = [a for a in assigns if "gemini_sdk_missing" in a]
        assert hits, "`gemini_sdk_missing` 대입을 못 찾았다 — 구조가 바뀌었으면 이 테스트부터 갱신할 것"
        for expr in hits:
            assert "meta_out.get('error')" in expr.replace('"', "'"), (
                f"`or` 가드가 없다: {expr} — 신 SDK 의 429/timeout 이 "
                "'SDK 설치 안 됨' 이라는 거짓 진단으로 바뀐다"
            )

    def test_legacy_sdk_label_has_an_or_guard(self):
        """legacy 블록도 신 SDK 블록과 같은 규약이어야 한다.

        ⚠ `meta_out["sdk"] = "google-generativeai"` 는 파일에 **3번** 나온다(성공 /
        network_denied / 재시도 소진). `find()` 로 첫 매치를 잡으면 성공 경로를 보게 되어
        영원히 통과하거나 영원히 실패한다 — 재시도 소진 블록을 앵커로 특정한다.
        """
        source = inspect.getsource(ai.llm_call)
        anchor = 'Gemini(Legacy SDK) failed after retries'
        idx = source.find(anchor)
        assert idx > 0, "legacy 재시도 소진 블록을 못 찾았다"
        window = source[idx : idx + 500]
        assert 'meta_out["error"] = meta_out.get("error") or last_err' in window, (
            "legacy 블록이 실패 사유를 무조건 덮어쓴다 — 신 SDK 의 사유가 사라진다"
        )

    def test_block_terminal_assignments_all_preserve(self):
        """**블록 종단** 3지점이 전부 보존 규약인지.

        ⚠ 종단이 아닌 대입은 대상이 아니다:
          - `network_denied`(:1214·:1345) 는 실제 시도가 낸 **구체 진단**이고 즉시
            return 하므로 덮어쓸 앞선 사유가 없다.
          - `empty_config`·`missing_api_key` 는 시도 이전의 입력 검증이다.
          - 함수 최종 `last_err or "llm_call_failed"` 는 Gemini 가 아니라 **전체 경로**
            (OpenAI/Ollama 포함)의 마지막 줄이다.
        이걸 구분하지 않고 전수로 걸면 정당한 대입을 오탐한다(실제로 한 번 걸렸다).
        """
        source = inspect.getsource(ai.llm_call)
        terminals = [
            ("Gemini(New SDK) failed after retries", 'meta_out.get("error") or last_err'),
            ("Gemini(Legacy SDK) failed after retries", 'meta_out.get("error") or last_err'),
            ("Gemini SDK not available", 'meta_out.get("error") or "gemini_sdk_missing"'),
        ]
        for anchor, expected in terminals:
            idx = source.find(anchor)
            assert idx > 0, f"블록 종단 앵커를 못 찾았다: {anchor}"
            window = source[idx : idx + 900]
            assert expected in window, (
                f"`{anchor}` 블록이 보존 규약을 안 지킨다 — 기대: {expected}"
            )


class TestLegacyFallbackRemovalIsRecorded:
    """제거 **보류** 결정과 그 사유가 코드에 남아 있어야 한다.

    "왜 수명 종료 패키지가 아직 있나" 를 다음 사람이 다시 조사하지 않도록,
    그리고 되살릴 때 무엇을 먼저 재야 하는지 알도록.
    """

    def test_decision_and_blocker_are_documented_at_the_fallback(self):
        source = Path(ai.__file__).read_text(encoding="utf-8")
        idx = source.find("# 1-b) Legacy SDK")
        assert idx > 0, "legacy 폴백 진입 주석을 못 찾았다"
        block = source[idx : idx + 2500]
        assert "제거 보류 확정" in block, "제거 보류 결정이 기록돼 있지 않다"
        assert "safety_settings" in block, "제거를 막은 사유(safety 비대칭)가 기록돼 있지 않다"
        assert "측정 실패" in block, "미측정 사실이 명시돼 있지 않다 — clean 으로 읽힐 수 있다"

    def test_safety_settings_asymmetry_still_holds(self):
        """비대칭이 실제로 남아 있는지 — 없어지면 위 사유가 낡은 것이 된다.

        legacy 블록은 `HarmCategory`/`HarmBlockThreshold` 로 BLOCK_NONE 4종을 걸고,
        신 SDK 경로(`GenerateContentConfig`)에는 safety 인자가 없다. 신 SDK 쪽에
        safety 가 생기면 제거 결정을 다시 열 수 있으므로 이 테스트가 알려 준다.
        """
        source = Path(ai.__file__).read_text(encoding="utf-8")
        assert "HARM_CATEGORY_DANGEROUS_CONTENT" in source, "legacy safety 설정이 사라졌다"
        idx = source.find("GenerateContentConfig")
        assert idx > 0, "신 SDK config 생성 지점을 못 찾았다"
        window = source[idx : idx + 600]
        assert "safety" not in window.lower(), (
            "신 SDK 경로에 safety 설정이 생겼다 — 비대칭이 해소됐으므로 §6 후보 16 "
            "(legacy 폴백 제거)을 다시 판단할 것"
        )


class TestSdkLoadingStaysLazy:
    """지연 로딩이 되돌려지지 않았는지 — 되돌리면 기동·테스트가 46초를 다시 문다."""

    def test_importing_ai_does_not_load_either_sdk(self):
        import subprocess
        import sys

        code = (
            "import sys, workflow.ai;"
            "print('legacy', 'google.generativeai' in sys.modules);"
            "print('new', 'google.genai' in sys.modules)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code],
            cwd=Path(ai.__file__).resolve().parents[1],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        ).stdout
        assert "legacy False" in out, f"legacy SDK 가 import 시점에 로드된다: {out!r}"
        assert "new False" in out, f"신 SDK 가 import 시점에 로드된다: {out!r}"


@pytest.mark.parametrize("name", ["genai_new", "genai_legacy", "HarmCategory", "HarmBlockThreshold"])
def test_sdk_names_still_resolvable_as_attributes(name):
    """`workflow/pipeline.py:2246` 이 `getattr(ai, "genai_new", None)` 로 가용성을 묻는다."""
    getattr(ai, name, None)   # 예외 없이 끝나면 계약 유지 (None 이어도 정상)
