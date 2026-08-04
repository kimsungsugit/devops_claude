"""SwUDS 읽기/parse 실패가 침묵하지 않는다 (2026-08-04).

## 왜 생겼나 — 실측

cloudium 모드 라이브 측정(2026-08-04)에서 `config/swut_meta.json` 의
`swuds_docx_path` 가 **두 프로젝트(KJPDS02·HDPDM01) 모두** allowed_prefixes 밖이라
`PermissionError` 로 차단됐다. 그 결과:

1. `resolve_swuds_function_ids` 가 `None` 을 돌려주고,
2. SwUDS↔시험 함수 ID 매핑 검증이 **통째로 건너뛰어졌으며**,
3. 산출물 2.Consistency 시트는 *"swuds_docx_path 옵션 제공 시 자동 활성화"* 라고
   적었다 — **경로를 안 줬다고 단정**하는 문구인데 실제로는 주고도 막힌 것이다.

형제 3개(`resolve_hmr_html_bytes` · `resolve_swuts_test_specs` · `resolve_swuds_maps`)
는 F6 Round 1 W1 에서 전부 `out_warnings` 를 받게 고쳐졌는데 이 함수만 빠졌고,
docstring 은 *"caller 가 warnings 에 사유 누적"* 이라고 **적어 두기까지 했다**.
4개 호출처 어디도 누적하지 않았으므로 구현되지 않은 계약이었다.

## 이 파일이 지키는 것

- 실패 사유가 `out_warnings` 로 나온다 (읽기 실패 / parse 실패 둘 다)
- **경로 미지정은 경고를 만들지 않는다** — 선택이지 결함이 아니다(소음 방지)
- 4개 빌드 호출처가 **전부** `out_warnings` 를 넘긴다 (AST 로 호출부를 직접 확인 —
  "함수에 인자가 있다" 와 "호출처가 그 인자를 쓴다" 는 다른 명제다)
- 산출물 문구가 원인을 지어내지 않는다
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# 1) resolver — 실패 사유가 out_warnings 로 나온다
# ---------------------------------------------------------------------------
class _Req:
    """덕 타이핑 req — resolve_swuds_path 가 보는 속성만 갖춘다."""

    def __init__(self, swuds_docx_path: str = ""):
        self.swuds_docx_path = swuds_docx_path


def _resolver_module():
    return pytest.importorskip("backend.services.swut_meta_resolver")


def test_read_failure_reason_reaches_out_warnings(monkeypatch):
    """PermissionError(= cloudium 차단)가 사유와 함께 out_warnings 에 담긴다."""
    mod = _resolver_module()
    monkeypatch.setattr(mod, "resolve_swuds_path", lambda *_a, **_k: "U:/blocked/x.docx")

    def _boom(_path):
        raise PermissionError("Cloudium 모드: 허용되지 않은 경로 접근 차단됨: U:/blocked/x.docx")

    monkeypatch.setattr(mod, "_cached_parse_swuds", _boom)

    warnings: list[str] = []
    out = mod.resolve_swuds_function_ids(_Req("U:/blocked/x.docx"), "KJPDS02",
                                         out_warnings=warnings)
    assert out is None
    assert len(warnings) == 1, f"사유가 누적되지 않았다: {warnings}"
    msg = warnings[0]
    assert "swuds" in msg.lower()
    assert "PermissionError" in msg, "예외 종류가 사라지면 원인 추적이 안 된다"
    assert "allowed_prefixes" in msg, "cloudium 차단일 때 조치 힌트가 있어야 한다"


def test_parse_failure_reason_reaches_out_warnings(monkeypatch):
    """ok=False(양식 문제)도 별도 사유로 누적된다 — 읽기 실패와 구분되어야 한다."""
    mod = _resolver_module()
    monkeypatch.setattr(mod, "resolve_swuds_path", lambda *_a, **_k: "U:/ok/x.docx")

    class _Bad:
        ok = False
        function_ids: set[str] = set()

    monkeypatch.setattr(mod, "_cached_parse_swuds", lambda _p: _Bad())

    warnings: list[str] = []
    assert mod.resolve_swuds_function_ids(_Req("U:/ok/x.docx"), "P",
                                          out_warnings=warnings) is None
    assert len(warnings) == 1
    assert "ok=False" in warnings[0]
    assert "PermissionError" not in warnings[0], "parse 실패를 읽기 실패로 보고하면 오진이다"


def test_missing_path_produces_no_warning(monkeypatch):
    """경로 미지정은 **결함이 아니다** — 경고를 만들면 진짜 실패가 소음에 묻힌다."""
    mod = _resolver_module()
    monkeypatch.setattr(mod, "resolve_swuds_path", lambda *_a, **_k: "")

    warnings: list[str] = []
    assert mod.resolve_swuds_function_ids(_Req(""), "P", out_warnings=warnings) is None
    assert warnings == []


def test_success_produces_no_warning(monkeypatch):
    mod = _resolver_module()
    monkeypatch.setattr(mod, "resolve_swuds_path", lambda *_a, **_k: "U:/ok/x.docx")

    class _Good:
        ok = True
        function_ids = {"SwUFn_01", "SwUFn_02"}

    monkeypatch.setattr(mod, "_cached_parse_swuds", lambda _p: _Good())
    warnings: list[str] = []
    out = mod.resolve_swuds_function_ids(_Req("U:/ok/x.docx"), "P", out_warnings=warnings)
    assert out == {"SwUFn_01", "SwUFn_02"}
    assert warnings == []


def test_out_warnings_omitted_still_returns_none(monkeypatch):
    """인자를 안 넘겨도 죽지 않는다(하위호환) — 다만 그때는 침묵이므로 호출처
    검사(아래 AST 테스트)가 그 경우를 막는다."""
    mod = _resolver_module()
    monkeypatch.setattr(mod, "resolve_swuds_path", lambda *_a, **_k: "U:/blocked/x.docx")

    def _boom(_path):
        raise PermissionError("blocked")

    monkeypatch.setattr(mod, "_cached_parse_swuds", _boom)
    assert mod.resolve_swuds_function_ids(_Req("U:/x"), "P") is None


# ---------------------------------------------------------------------------
# 2) 호출처가 실제로 사유를 받는가 — AST
# ---------------------------------------------------------------------------
#
# ⚠ 이 저장소가 반복해서 당한 함정: "함수에 out_warnings 를 달았다" 로 만족하는 것.
#    옛 docstring 이 *"caller 가 누적한다"* 고 **적어 두고도** 4개 호출처 전부가
#    안 넘기고 있었다. 그래서 **호출 노드**를 직접 본다.
_CALL_SITES = [
    ("backend/routers/swut.py", "_resolve_swuds_function_ids"),
    ("backend/routers/swit.py", "_resolve_swuds_function_ids"),
]


def _calls_named(tree: ast.AST, name: str) -> list[ast.Call]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == name:
            out.append(node)
    return out


@pytest.mark.parametrize(("rel", "fn"), _CALL_SITES)
def test_every_router_call_passes_out_warnings(rel, fn):
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    calls = _calls_named(tree, fn)
    assert len(calls) >= 2, (
        f"{rel} 에서 {fn} 호출을 {len(calls)}건만 찾았다 — 빌드 경로가 2개(coverage/보고서)"
        " 이므로 검출기가 못 보고 있을 수 있다"
    )
    for call in calls:
        kw = {k.arg for k in call.keywords}
        assert "out_warnings" in kw, (
            f"{rel}:{call.lineno} — {fn} 호출이 out_warnings 를 안 넘긴다. "
            "실패 사유가 산출물에 도달하지 못한다"
        )


@pytest.mark.parametrize("rel", ["backend/routers/swut.py", "backend/routers/swit.py"])
def test_collected_warnings_are_extended_into_result(rel):
    """모은 사유를 `result.warnings` 로 올리지 않으면 모으나 마나다.

    ⚠ `in src` 로만 보면 **경로 하나만 올려도 통과**한다(뮤테이션 M7 이 이 구멍으로
      살아남았다 — SwUT coverage 의 extend 를 지워도 SUTR/SwUTCR 것이 남아 문자열이
      존재했다). 그래서 **호출 경로 수와 같은지**를 센다.
    """
    src = (REPO / rel).read_text(encoding="utf-8")
    n_calls = len(_calls_named(ast.parse(src), "_resolve_swuds_function_ids"))
    n_extend = src.count("result.warnings.extend(_swuds_warnings)")
    assert n_extend == n_calls, (
        f"{rel}: SwUDS 해석 경로 {n_calls}개인데 result.warnings 로 올리는 곳은 "
        f"{n_extend}개다 — 빠진 경로는 사유를 모으고도 버린다"
    )


@pytest.mark.parametrize("rel", ["backend/routers/swut.py", "backend/routers/swit.py"])
def test_reason_is_forwarded_to_builder(rel):
    """산출물 문구가 사유를 실으려면 빌더까지 가야 한다."""
    src = (REPO / rel).read_text(encoding="utf-8")
    # swut.py 는 coverage / SUTR / SwUTCR 3경로, swit.py 는 coverage / SITR 2경로.
    # 하한만 두면 새 빌드 경로가 생겼을 때 위 AST 테스트가 잡는다(호출부 전수 검사).
    n_calls = len(_calls_named(ast.parse(src), "_resolve_swuds_function_ids"))
    assert src.count("swuds_skip_reason=") == n_calls, (
        f"{rel}: SwUDS 를 해석하는 빌드 경로 {n_calls}개인데 빌더로 사유를 넘기는 곳은 "
        f"{src.count('swuds_skip_reason=')}개다 — 빠진 경로의 산출물은 계속 원인을 숨긴다"
    )


# ---------------------------------------------------------------------------
# 3) 산출물 문구가 원인을 지어내지 않는다
# ---------------------------------------------------------------------------
def test_consistency_intro_does_not_blame_missing_option():
    """옛 문구는 미검증 사유를 '옵션 미제공' 으로 **단정**했다 — 감사 증거 오귀속.

    ⚠ 파일 전체 문자열 검색으로 쓰면 **이 결함을 설명하는 주석**에도 걸린다(실제로
      걸렸다). 검사 대상은 *산출물에 찍히는 문자열* 이므로 AST 로 함수 본문의
      **문자열 리터럴만** 본다 — 주석·docstring 은 ast 가 애초에 안 준다.
    """
    import ast as _ast

    src = (REPO / "backend/services/swut_coverage_aggregator.py").read_text(encoding="utf-8")
    tree = _ast.parse(src)
    target = next(
        (n for n in _ast.walk(tree)
         if isinstance(n, _ast.FunctionDef) and n.name == "_write_consistency_sheet"),
        None,
    )
    assert target is not None, "_write_consistency_sheet 를 못 찾았다"

    literals: list[str] = []
    body = list(target.body)
    # docstring 은 제외 — 산출물에 안 찍힌다
    if body and isinstance(body[0], _ast.Expr) and isinstance(body[0].value, _ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    for stmt in body:
        for node in _ast.walk(stmt):
            if isinstance(node, _ast.Constant) and isinstance(node.value, str):
                literals.append(node.value)

    joined = "".join(literals)
    assert "옵션 제공 시" not in joined, (
        "산출물 문구가 '옵션 제공 시 자동 활성화' 로 남아 있다 — swuds_function_ids=None 은 "
        "미지정/읽기실패/parse실패를 모두 접은 값이라 원인을 단정할 수 없다"
    )


def test_consistency_intro_carries_reason_when_known():
    """사유를 알면 문서에 싣는다 — 빌드 로그를 못 보는 감사자를 위해."""
    import inspect

    mod = pytest.importorskip("backend.services.swut_coverage_aggregator")
    src = inspect.getsource(mod._write_consistency_sheet)
    assert "swuds_skip_reason" in src
    assert "사유:" in src, "사유를 알 때 그 값을 문구에 넣는 분기가 있어야 한다"
    assert "수행되지 않았다" in src, "미검증 사실 자체는 두 분기 모두에서 명시돼야 한다"


@pytest.mark.parametrize("rel", [
    "backend/services/swut_coverage_aggregator.py",
    "backend/services/swut_sutr_aggregator.py",
    "backend/services/swit_coverage_aggregator.py",
    "backend/services/swit_sitr_aggregator.py",
])
def test_all_four_builders_accept_and_forward_reason(rel):
    """4개 빌더 전부 — 한쪽만 고치면 그 산출물만 계속 원인을 숨긴다."""
    src = (REPO / rel).read_text(encoding="utf-8")
    assert "swuds_skip_reason: str = \"\"" in src, f"{rel}: 빌더가 사유 인자를 안 받는다"
    assert "swuds_skip_reason=swuds_skip_reason" in src, (
        f"{rel}: 받기만 하고 _write_consistency_sheet 로 넘기지 않는다"
    )
