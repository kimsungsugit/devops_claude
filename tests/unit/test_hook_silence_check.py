"""scripts/_silence_check.py — broad-silent except 분류기.

이 게이트가 막는 것: `ruff`/E722 는 bare `except:` 만 보고 `except Exception: pass`
(프로젝트 침묵 except 831개[2026-08-03 실측]의 대부분)를 **구조적으로 못 본다**. 분류기는 그
사각지대를 AST 로 보강한다.

핵심 계약 — 분류기는 '침묵 **형태**'를 탐지하지 '나쁜 코드'를 판정하지 않는다
(위험/정당이 구조적으로 동일함이 실측됐다). 사각지대를 실용적으로 좁히는 **비의미적
면제 3종**이 정확해야 한다:
  1. 좁은 예외(Exception/BaseException/bare 아님) → flag 안 함
  2. body 에 raise / 로깅 호출 / 예외변수 참조 → flag 안 함
  3. `# silent-ok` 마커 → flag 안 함

아래 각 "면제" 테스트는 **mutation 게이트**다 — 면제 로직을 제거하면(예: `_is_broad`
가 항상 True, `_suppressed` 가 항상 False) FAIL 해야 진짜 회귀 방어다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from _silence_check import _iter_added_lines, silent_excepts  # noqa: E402


def _lines(src: str) -> list[int]:
    return [ln for ln, _ in silent_excepts(src)]


# ── flag 되어야 하는 것 (진짜 침묵) ────────────────────────────────────────

def test_broad_pass_only_is_flagged():
    src = "try:\n    x()\nexcept Exception:\n    pass\n"
    assert _lines(src) == [3]
    assert silent_excepts(src)[0][1] == "pass-only"


def test_bare_except_pass_is_flagged():
    src = "try:\n    x()\nexcept:\n    pass\n"
    assert _lines(src) == [3]


def test_ellipsis_body_is_flagged():
    src = "try:\n    x()\nexcept Exception:\n    ...\n"
    assert _lines(src) == [3]


def test_broad_no_raise_no_log_is_flagged():
    """broad except 가 조용히 기본값을 돌려주면(로그·raise 없음) 침묵이다."""
    src = "def f():\n    try:\n        return x()\n    except Exception:\n        return None\n"
    assert _lines(src) == [4]
    assert silent_excepts(src)[0][1] == "no-raise/no-log"


def test_bound_but_unused_exception_is_flagged():
    """`except X as e: pass` 는 바인딩해도 e 를 안 쓰면 여전히 침묵(ruff F841 도 잡음)."""
    src = "try:\n    x()\nexcept Exception as e:\n    pass\n"
    assert _lines(src) == [3]


def test_baseexception_is_broad():
    src = "try:\n    x()\nexcept BaseException:\n    pass\n"
    assert _lines(src) == [3]


def test_multiple_and_sorted():
    src = (
        "try:\n    a()\nexcept Exception:\n    pass\n"          # 3
        "try:\n    b()\nexcept Exception:\n    pass\n"          # 7
    )
    assert _lines(src) == [3, 7]


# ── 면제되어야 하는 것 (mutation 게이트) ───────────────────────────────────

def test_narrow_exception_not_flagged():
    """면제 1: 좁은 예외. `_is_broad` 를 항상 True 로 되돌리면 FAIL."""
    src = "try:\n    x()\nexcept KeyError:\n    pass\n"
    assert _lines(src) == []


def test_narrow_tuple_not_flagged():
    src = "try:\n    x()\nexcept (KeyError, ValueError):\n    pass\n"
    assert _lines(src) == []


def test_broad_tuple_with_exception_is_flagged():
    """튜플에 Exception 이 섞이면 광의 — 잡아야 한다."""
    src = "try:\n    x()\nexcept (KeyError, Exception):\n    pass\n"
    assert _lines(src) == [3]


def test_logging_call_not_flagged():
    """면제 2a: body 에 로깅 호출. 로그 힌트 매칭을 제거하면 FAIL."""
    src = "try:\n    x()\nexcept Exception:\n    logger.error('boom')\n"
    assert _lines(src) == []


def test_reraise_not_flagged():
    """면제 2b: body 에 raise."""
    src = "try:\n    x()\nexcept Exception:\n    raise\n"
    assert _lines(src) == []


def test_exception_var_referenced_not_flagged():
    """면제 2c: 예외변수 참조 = 표면화(report-and-continue 관용구). 훅 파일 오탐 방지.

    `handler.name` 참조 검사를 제거하면 FAIL — posttool_dispatch 의
    `except Exception as e: results.append(f"{type(e).__name__}")` 가 오탐된다.
    """
    src = (
        "results = []\n"
        "try:\n    x()\nexcept Exception as e:\n    results.append(str(type(e).__name__))\n"
    )
    assert _lines(src) == []


def test_suppress_marker_on_except_line_not_flagged():
    """면제 3: `# silent-ok` 마커. `_suppressed` 를 항상 False 로 되돌리면 FAIL."""
    src = "try:\n    x()\nexcept Exception:  # silent-ok\n    pass\n"
    assert _lines(src) == []


def test_suppress_marker_on_body_line_not_flagged():
    src = "try:\n    x()\nexcept Exception:\n    pass  # silent-ok\n"
    assert _lines(src) == []


# ── 방어 ──────────────────────────────────────────────────────────────────

def test_syntax_error_returns_empty_not_crash():
    """파싱 불가면 빈 목록(판정 보류) — 크래시하면 훅이 통째로 죽는다."""
    assert silent_excepts("def f(:\n    pass\n") == []


def test_no_except_returns_empty():
    assert silent_excepts("def f():\n    return 1\n") == []


# ── _iter_added_lines (ratchet 재료) ───────────────────────────────────────

def test_iter_added_lines_basic():
    diff = (
        "diff --git a/x.py b/x.py\n"
        "--- a/x.py\n+++ b/x.py\n"
        "@@ -10,0 +11,3 @@\n+a\n+b\n+c\n"
    )
    assert _iter_added_lines(diff) == {"x.py": {11, 12, 13}}


def test_iter_added_lines_single_line_no_count():
    """`+c` 에 `,count` 가 없으면 1줄. 파싱이 틀리면 ratchet 이 헛돈다."""
    diff = "--- a/x.py\n+++ b/x.py\n@@ -5 +6 @@\n+z\n"
    assert _iter_added_lines(diff) == {"x.py": {6}}


def test_iter_added_lines_deletion_is_skipped():
    """/dev/null (삭제)는 신 파일이 없으므로 건너뛴다."""
    diff = "--- a/x.py\n+++ /dev/null\n@@ -1,3 +0,0 @@\n-a\n-b\n-c\n"
    assert _iter_added_lines(diff) == {}


def test_iter_added_lines_multiple_files():
    diff = (
        "--- a/x.py\n+++ b/x.py\n@@ -1,0 +2,1 @@\n+a\n"
        "--- a/y.py\n+++ b/y.py\n@@ -1,0 +5,2 @@\n+b\n+c\n"
    )
    assert _iter_added_lines(diff) == {"x.py": {2}, "y.py": {5, 6}}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
