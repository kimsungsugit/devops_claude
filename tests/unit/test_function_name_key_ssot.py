"""`function_details_by_name` 의 **키 규칙 단일 출처** (계획서 후보 21 / C3 후속).

## 결함

같은 맵을 만드는 코드가 **4곳**에 복제돼 있었고 그중 둘이 규칙을 틀렸다(2026-08-03 실측):

    report_gen/uds_generator.py::_put_by_name   `.strip().lower()`   ← 정본
    backend/routers/jenkins.py                  `.strip().lower()`   ✓
    backend/routers/local.py                    `.strip()`           ✗ 원형 대소문자
    tools/generate_uds_local.py                 `.strip()`           ✗ 원형 대소문자

그런데 **조회는 전부 소문자**다 — `docx_builder` 13곳, `backend/routers/code.py:126`,
`backend/routers/test_gen.py:32`, `uds_generator` 4곳.

즉 local 경로로 만든 문서는 이름에 대문자가 든 함수를 **하나도 못 찾는다**.
실측 표본(`reports/uds_local/uds_local_20260803_090618.payload.json`): 함수 350개 중
**267개(76.3%)** 가 대문자를 포함한다. 잃는 것은 호출자/피호출자 **시그니처**(맨 이름으로
degrade), SwCom **파일 경로**, 그리고 `code.py`·`test_gen.py` 의 함수 본문 조회는
**404** 였다. 전부 조용하다.

맞으면 아무 일도 안 일어나고 틀리면 조용한 miss 라 눈으로 못 본다 — 그래서 규칙을
한 곳에 두고, 여기서 **복제가 다시 생기지 않는지**를 지킨다.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parents[2]
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from report_gen.utils import build_function_details_by_name, function_name_key  # noqa: E402


class TestKeyRule:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("s_BuzzerCtrl_On", "s_buzzerctrl_on"),
            ("  g_Ap_BuzzerCtrl_Reset  ", "g_ap_buzzerctrl_reset"),
            ("already_lower", "already_lower"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalization(self, raw, expected):
        assert function_name_key(raw) == expected

    def test_builder_uses_the_rule(self):
        details = {
            "SwUFn_01": {"id": "SwUFn_01", "name": "s_BuzzerCtrl_On"},
            "SwUFn_02": {"id": "SwUFn_02", "name": "g_Ap_Reset"},
        }
        out = build_function_details_by_name(details)
        assert sorted(out) == ["g_ap_reset", "s_buzzerctrl_on"]

    def test_builder_keeps_the_same_objects(self):
        """사본을 넣으면 문서 생성의 in-place 갱신이 반영되지 않는다.

        (`uds_generator._put_by_name` docstring 이 같은 이유를 적어 두고 있다.)
        """
        details = {"SwUFn_01": {"id": "SwUFn_01", "name": "Motor_Init"}}
        out = build_function_details_by_name(details)
        assert out["motor_init"] is details["SwUFn_01"]

    def test_non_dict_is_safe(self):
        assert build_function_details_by_name(None) == {}
        assert build_function_details_by_name("nope") == {}


class TestNoDuplicatedBuilders:
    """복제가 다시 생기면 또 갈라진다 — 그게 이 결함의 실제 원인이었다."""

    #: `xxx[<name-ish>] = info` 형태로 by_name 을 **직접** 조립하는 인라인 루프.
    _INLINE = re.compile(
        r'^\s*(?:rebuilt_)?by_name\s*\[[^\]]*\]\s*=\s*info\s*$', re.M
    )

    @pytest.mark.parametrize(
        "rel",
        [
            "backend/routers/local.py",
            "backend/routers/jenkins.py",
            "tools/generate_uds_local.py",
        ],
    )
    def test_routers_do_not_rebuild_by_name_inline(self, rel):
        src = (_repo_root / rel).read_text(encoding="utf-8")
        hits = self._INLINE.findall(src)
        assert not hits, (
            f"{rel} 이 by_name 을 인라인으로 다시 조립한다 — "
            f"report_gen.utils.build_function_details_by_name 을 쓸 것 (키 규칙이 갈린다)"
        )

    @pytest.mark.parametrize(
        "rel",
        [
            "backend/routers/local.py",
            "backend/routers/jenkins.py",
            "tools/generate_uds_local.py",
        ],
    )
    def test_routers_actually_call_the_shared_builder(self, rel):
        """⚠ "인라인이 없다" 만 보면 **아무도 안 만드는** 상태도 통과한다."""
        tree = ast.parse((_repo_root / rel).read_text(encoding="utf-8"))
        called = {
            n.func.id for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "build_function_details_by_name" in called, (
            f"{rel} 이 공용 빌더를 부르지 않는다 — function_details_by_name 이 안 만들어진다"
        )

    def test_canonical_put_by_name_uses_the_shared_key_rule(self):
        """정본(`_put_by_name`)도 같은 규칙 함수를 써야 SSOT 가 성립한다."""
        src = (_repo_root / "report_gen/uds_generator.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(
            (n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef) and n.name == "_put_by_name"),
            None,
        )
        assert fn is not None, "_put_by_name 을 못 찾았다 — 이 가드가 무력해졌다"
        called = {
            n.func.id for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        assert "function_name_key" in called, (
            "_put_by_name 이 자체 정규화를 쓴다 — 규칙이 두 벌이 되면 또 갈라진다"
        )


class TestLookupsAssumeLowercase:
    """조회가 소문자를 기대한다는 사실 자체를 못박는다.

    이게 깨지면(예: 조회 한 곳이 `.lower()` 를 잃으면) 키 규칙만 맞춰 놔도 다시 miss 난다.
    """

    def test_code_and_test_gen_lookups_are_lowercased(self):
        for rel, needle in [
            ("backend/routers/code.py", "by_name.get(fn_name.lower())"),
            ("backend/routers/test_gen.py", "by_name.get(fn_name.lower())"),
        ]:
            src = (_repo_root / rel).read_text(encoding="utf-8")
            assert needle in src, (
                f"{rel} 의 by_name 조회가 소문자 정규화를 잃었다 — "
                f"대문자 포함 함수(실측 76.3%)가 404 로 떨어진다"
            )
