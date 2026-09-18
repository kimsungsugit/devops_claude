# tests/unit/test_docgen_preflight_phases.py
"""**게이트가 낸 행이 화면에 도달하는가** — phase 어휘의 드리프트 가드.

패널은 이렇게 그린다(`DocGenPreflightPanel.jsx`):

    PHASE_ORDER.map(p => [p, steps.filter(s => s.phase === p)])

즉 `PHASE_ORDER` 에 없는 phase 의 행은 **에러도 경고도 없이 통째로 사라진다**. 서버는
행을 냈고 사용자는 못 본다 — 이 저장소가 반복해 겪은 침묵 그대로다(`stage.json` 이
write-only 였던 것, `stats_out` 이 품질 리포트에서 잘리던 것과 같은 계열).

라운드 11이 `history` phase 를 새로 냈다. 그때 화면을 같이 고치지 않았다면 "직전 생성
결과" 행은 응답에는 있고 화면엔 없었을 것이다 — API 로만 보이는 결함이라 눈으로는
절대 못 잡는다. 그래서 **양쪽을 실측해서** 묶는다.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from backend.routers import docgen_preflight as pf

_ROUTER = Path("backend/routers/docgen_preflight.py")
_PANEL = Path("frontend-v2/src/components/sections/DocGenPreflightPanel.jsx")


def _emitted_phases(source: str, module=pf) -> set[str]:
    """`_step(...)` 호출이 **실제로 내는** phase 집합.

    2번째 위치 인자만 본다. 리터럴(`"input"`)과 상수 이름(`PH_HISTORY`) 둘 다 푼다 —
    한쪽만 풀면 다른 쪽으로 쓴 행이 가드를 조용히 빠져나간다.
    """
    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_step" and len(node.args) >= 2):
            continue
        arg = node.args[1]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.add(arg.value)
        elif isinstance(arg, ast.Name) and arg.id.startswith("PH_"):
            out.add(str(getattr(module, arg.id)))
        else:  # pragma: no cover - 새 표현이 생기면 여기서 드러나야 한다
            raise AssertionError(f"_step 의 phase 인자를 해석하지 못했다: {ast.dump(arg)}")
    return out


def _js_list(source: str, name: str) -> list[str]:
    m = re.search(rf"const {name} = \[(.*?)\];", source, re.S)
    assert m, f"{name} 를 찾지 못했다"
    return re.findall(r"'([^']+)'", m.group(1))


def _js_object_keys(source: str, name: str) -> set[str]:
    m = re.search(rf"const {name} = \{{(.*?)\n\}};", source, re.S)
    assert m, f"{name} 를 찾지 못했다"
    body = re.sub(r"//[^\n]*", "", m.group(1))
    return set(re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", body, re.M))


# ══════════════════════════════════════════════════════════════════════════
# 백엔드 ↔ 화면
# ══════════════════════════════════════════════════════════════════════════

def test_every_emitted_phase_is_declared() -> None:
    """행을 내면서 `PHASES` 에 등록하지 않으면 아래 대조가 무의미해진다."""
    emitted = _emitted_phases(_ROUTER.read_text(encoding="utf-8"))
    assert emitted, "_step 호출을 하나도 찾지 못했다(파서가 망가진 것)"
    assert emitted <= set(pf.PHASES), f"미등록 phase: {sorted(emitted - set(pf.PHASES))}"


def test_every_emitted_phase_is_rendered() -> None:
    """**이 파일의 본체** — 서버가 내는 phase 가 화면 목록에 전부 있는가."""
    emitted = _emitted_phases(_ROUTER.read_text(encoding="utf-8"))
    order = set(_js_list(_PANEL.read_text(encoding="utf-8"), "PHASE_ORDER"))
    missing = sorted(emitted - order)
    assert not missing, (
        f"화면이 그리지 않는 phase 가 있다 — 그 행은 조용히 사라진다: {missing}. "
        f"`PHASE_ORDER`/`PHASE_TITLES` 에 추가할 것"
    )


def test_declared_phases_all_have_a_title() -> None:
    """제목이 없으면 패널이 phase **코드 그대로**(`history`)를 소제목으로 그린다."""
    src = _PANEL.read_text(encoding="utf-8")
    titles = _js_object_keys(src, "PHASE_TITLES")
    order = _js_list(src, "PHASE_ORDER")
    assert set(order) <= titles, f"제목 없는 phase: {sorted(set(order) - titles)}"
    assert set(pf.PHASES) <= titles, f"제목 없는 phase: {sorted(set(pf.PHASES) - titles)}"


def test_screen_does_not_invent_phases_the_server_cannot_send() -> None:
    """반대 방향 — 화면에만 있는 phase 는 영원히 빈 칸이다(있으면 오래된 잔재)."""
    order = set(_js_list(_PANEL.read_text(encoding="utf-8"), "PHASE_ORDER"))
    assert order <= set(pf.PHASES), f"서버가 못 내는 phase: {sorted(order - set(pf.PHASES))}"


def test_history_phase_exists_and_is_last() -> None:
    """직전 생성은 **기록**이라 지금의 입력 흐름 뒤에 온다 — 순서가 곧 뜻이다."""
    order = _js_list(_PANEL.read_text(encoding="utf-8"), "PHASE_ORDER")
    assert order[-1] == pf.PH_HISTORY == "history"


# ══════════════════════════════════════════════════════════════════════════
# 가드 자체가 작동하는가 (음성 대조군)
# ══════════════════════════════════════════════════════════════════════════

class TestTheGuardActuallyCatches:
    """대조군이 없으면 위 네 개는 '항상 통과하는 문장' 일 수 있다."""

    def test_a_stray_literal_phase_is_caught(self) -> None:
        found = _emitted_phases('_step("x", "typo_phase", S_OK, "L")')
        assert found == {"typo_phase"}
        assert not found <= set(pf.PHASES)

    def test_a_constant_phase_is_resolved_not_skipped(self) -> None:
        """`PH_*` 를 못 풀면 상수로 쓴 행이 전부 가드를 빠져나간다."""
        assert _emitted_phases("_step('x', PH_HISTORY, S_OK, 'L')") == {"history"}

    def test_an_unparseable_phase_is_an_error_not_silence(self) -> None:
        with pytest.raises(AssertionError):
            _emitted_phases('_step("x", some_var, S_OK, "L")')

    def test_js_parsers_read_the_real_file(self) -> None:
        """정규식이 헛돌면 위 대조가 빈 집합끼리 비교하는 헛일이 된다."""
        src = _PANEL.read_text(encoding="utf-8")
        assert len(_js_list(src, "PHASE_ORDER")) >= 6
        assert "decision" in _js_object_keys(src, "PHASE_TITLES")
