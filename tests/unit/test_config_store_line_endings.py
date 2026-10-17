"""`config/*.json` 저장소가 줄끝을 LF 로 쓴다 — `.gitattributes` 계약.

## 무엇이 문제였나 (2026-08-25 실측)

`.gitattributes` 는 이 저장소의 텍스트 줄끝을 명시한다:

    *.json      text eol=lf
    .githooks/* text eol=lf   # "bash on Windows refuses to execute scripts with CRLF"

그런데 `Path.write_text(...)` 는 **Windows 에서 `\\n` 을 `\\r\\n` 으로 바꾼다**(기본
`newline=None`). `config/*.json` 을 쓰는 저장소 5곳이 전부 이 형태였고, 서로 패턴을
베껴 온 탓에 한 곳만 고쳐선 소용이 없다(판정 복제).

증상: `/api/file-mode/add-allowed-prefix` 로 prefix 를 **한 번** 추가하면
`config/cloudium_extra_prefixes.json` 의 줄끝이 통째로 뒤집힌다.

JSON 자체는 CRLF 여도 파싱되므로 피해는 크지 않다. **위험한 건 같은 실수가 훅
스크립트에서 나는 경우**다 — 같은 날 `.githooks/pre-commit` 을 이 방식으로 저장해
파일 전체가 CRLF 가 됐고, 그러면 Windows bash 가 실행을 거부해 **게이트가 통째로
죽는다**(그쪽은 `test_precommit_gate_contract.py` 가 따로 잡는다).

## 왜 2층인가

- **행동 검사**(바이트에 CRLF 없음)는 Windows 에서만 진짜다. Linux CI 는 애초에
  변환이 없어 `newline` 을 지워도 통과한다 — 거기선 **공허 통과**다.
- 그래서 **구조 검사**(AST 로 `newline="\\n"` 인자 확인)를 함께 둔다. 이건 플랫폼과
  무관하므로 인자를 지우는 순간 어디서든 실패한다.
"""
from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SERVICES = _ROOT / "backend" / "services"

# (모듈, 쓰기 함수) — 다섯 곳 전부가 계약 대상이다. 하나라도 빠지면 그쪽으로 샌다.
STORES = [
    ("admin_users", "_atomic_write"),
    ("cloudium_extra_prefixes", "_atomic_write"),
    ("file_mode_store", "_atomic_write"),
    ("scm_registry", "_save_json"),
    ("users", "_atomic_write"),
]


@pytest.mark.parametrize(("modname", "funcname"), STORES)
def test_writer_emits_lf_bytes(modname, funcname, tmp_path):
    """실제로 써 보고 바이트를 본다 (Windows 에서 진짜 검사)."""
    mod = importlib.import_module(f"backend.services.{modname}")
    write = getattr(mod, funcname, None)
    assert write is not None, f"{modname}.{funcname} 가 없다 — 이름이 바뀌었으면 이 표도 갱신할 것"

    target = tmp_path / "store.json"
    payload = {"prefixes": ["a", "b"], "schema_version": 1, "한글": "값"}
    write(target, payload)

    raw = target.read_bytes()
    assert b"\r\n" not in raw, f"{modname}: CRLF 로 저장했다 (.gitattributes 는 eol=lf)"
    # 내용도 멀쩡해야 한다 — 줄끝만 보고 통과시키면 인코딩 회귀를 놓친다.
    assert json.loads(raw.decode("utf-8")) == payload


@pytest.mark.parametrize(("modname", "funcname"), STORES)
def test_writer_passes_explicit_newline(modname, funcname):
    """`newline="\\n"` 을 **명시**했는지 소스로 확인한다 (플랫폼 무관).

    위 바이트 검사는 Linux 에서 항상 통과하므로 이 검사가 없으면 CI 는 회귀를 못 본다.
    """
    src = (_SERVICES / f"{modname}.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    target_fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.FunctionDef) and n.name == funcname),
        None,
    )
    assert target_fn is not None, f"{modname}.{funcname} 정의를 못 찾았다"

    writes = [
        n for n in ast.walk(target_fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "write_text"
    ]
    assert writes, f"{modname}.{funcname} 안에 write_text 호출이 없다 — 계약이 옮겨갔는지 확인"

    for call in writes:
        kw = {k.arg: k.value for k in call.keywords}
        assert "newline" in kw, (
            f"{modname}.{funcname}: write_text 에 newline 미지정 — "
            "Windows 에서 CRLF 로 저장된다"
        )
        val = kw["newline"]
        assert isinstance(val, ast.Constant) and val.value == "\n", (
            f"{modname}.{funcname}: newline={ast.dump(val)} — '\\n' 이어야 한다"
        )
