"""`_source_probe.source_of` 계약 + 저장소 전역 사용 규약.

## 왜 있나

`inspect.getsource(fn)` 은 **import 당시** 줄 번호를 **지금 파일**에 적용한다. 게이트가
도는 동안 다른 세션이 그 `.py` 를 저장하면 **다른 함수의 소스**가 조용히 돌아온다.
2026-08-25 실측으로 두 번 겪었다(`test_sds_and_uds_reads_are_not_confined` 외 1건).

거짓 실패는 거짓 통과의 쌍둥이다 — 사람이 게이트를 안 믿게 만들고 `--no-verify` 로 가는
길을 낸다. 그래서 ①대체 헬퍼를 두고 ②테스트가 맨 `inspect.getsource` 를 쓰지 못하게 한다.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import os
import sys
from pathlib import Path

import pytest

from tests.unit._source_probe import SourceProbeError, source_of

REPO = Path(__file__).resolve().parents[2]

# --------------------------------------------------------------------------- #
# 임시 모듈 하네스
# --------------------------------------------------------------------------- #


def _layout(pad: int, n: int = 6) -> str:
    """함수 하나가 정확히 4줄(빈줄·빈줄·def·return)인 모듈. `pad` 만큼 위에서 민다."""
    parts = ['"""임시 모듈."""\n', "# 채움\n" * pad]
    for i in range(n):
        parts.append(f"\n\ndef fn_{i}():\n    return \"BODY_{i}\"\n")
    return "".join(parts)


@pytest.fixture
def temp_module(tmp_path):
    """텍스트를 주면 그 내용으로 모듈을 만들어 import 해 준다. 다시 부르면 **다시 쓴다**."""
    created: list[str] = []

    def make(text: str, name: str = "probe_tmp"):
        path = tmp_path / f"{name}.py"
        path.write_text(text, encoding="utf-8", newline="\n")
        if name in sys.modules:
            return sys.modules[name]          # 재기록만 — 옛 줄번호를 그대로 둔다
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        created.append(name)
        spec.loader.exec_module(mod)
        return mod

    try:
        yield make
    finally:
        for name in created:
            sys.modules.pop(name, None)


# --------------------------------------------------------------------------- #


class TestLineShiftImmunity:
    """이 클래스가 이 모듈의 존재 이유다."""

    def test_source_of_survives_a_shift(self, temp_module):
        mod = temp_module(_layout(0))
        temp_module(_layout(8))               # 게이트 도중 다른 세션이 저장한 상황
        assert "BODY_2" in source_of(mod.fn_2)
        assert "BODY_0" not in source_of(mod.fn_2)

    def test_inspect_getsource_really_is_wrong_here(self, temp_module):
        """음성 대조군 — 밀림이 실제로 **다른 함수**를 내놓는다는 증거.

        4줄짜리 함수에 8줄을 밀어 넣었으므로 `fn_2` 의 저장된 시작줄은 정확히 `fn_0` 의
        `def` 줄에 떨어진다. 이 단언이 깨지면 CPython 동작이 바뀐 것이니, 그때
        `source_of` 가 여전히 필요한지 **다시 판단**할 것(지우기 전에 재라).
        """
        mod = temp_module(_layout(0))
        temp_module(_layout(8))
        wrong = inspect.getsource(mod.fn_2)   # getsource-ok: 결함 자체를 실증하는 대조군
        assert "BODY_0" in wrong and "BODY_2" not in wrong, (
            "밀림이 재현되지 않았다 — 이 하네스가 결함을 더는 만들지 못한다")


class TestNameResolution:
    def test_method_is_not_confused_with_a_module_function(self, temp_module):
        """같은 이름이 모듈에도 클래스에도 있으면 **스코프로** 갈라야 한다."""
        mod = temp_module(
            "def dispatch():\n    return \"MODULE_LEVEL\"\n\n\n"
            "class M:\n    def dispatch(self):\n        return \"IN_CLASS\"\n",
            name="probe_scope",
        )
        assert "IN_CLASS" in source_of(mod.M.dispatch)
        assert "MODULE_LEVEL" not in source_of(mod.M.dispatch)
        assert "MODULE_LEVEL" in source_of(mod.dispatch)

    def test_decorator_lines_are_included(self, temp_module):
        """`@router.post(...)` 를 보는 가드가 있다 — 데코레이터가 빠지면 그게 죽는다."""
        mod = temp_module(
            "def deco(f):\n    return f\n\n\n@deco\ndef target():\n    return 1\n",
            name="probe_deco",
        )
        assert source_of(mod.target).startswith("@deco")

    def test_definition_inside_a_conditional_is_found(self, temp_module):
        """`if TYPE_CHECKING:` / `try: … except ImportError:` 안의 정의도 잡는다."""
        mod = temp_module(
            "import os\n\nif os.sep:\n    def conditional():\n        return \"INSIDE_IF\"\n",
            name="probe_cond",
        )
        assert "INSIDE_IF" in source_of(mod.conditional)

    def test_module_returns_the_current_whole_file(self, temp_module):
        mod = temp_module(_layout(0))
        temp_module(_layout(3))
        text = source_of(mod)
        assert text.count("# 채움") == 3, "모듈 조회가 낡은 내용을 냈다"
        assert all(f"BODY_{i}" in text for i in range(6))

    def test_module_read_is_not_served_from_a_stale_cache(self, temp_module):
        """모듈 단위 조회를 **왜** 바꿨는지 — 줄밀림이 아니라 `linecache` 때문이다.

        `linecache.checkcache` 는 (크기, mtime) 로만 판단한다. 같은 크기로 같은 시각에
        다시 쓰이면 캐시가 그대로 살아 **낡은 파일**이 돌아온다. 파일을 직접 읽는
        `source_of` 는 이 창이 없다.
        """
        mod = temp_module(_layout(0))
        path = Path(mod.__file__)
        before = path.stat()
        inspect.getsource(mod)                # getsource-ok: 캐시를 채우는 대조군 준비
        swapped = path.read_text(encoding="utf-8").replace("BODY_0", "BODY_X")  # 길이 동일
        path.write_text(swapped, encoding="utf-8", newline="\n")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert path.stat().st_size == before.st_size, "하네스가 크기를 바꿨다 — 창이 안 열린다"

        assert "BODY_X" in source_of(mod)
        stale = inspect.getsource(mod)        # getsource-ok: 낡은 캐시를 실증하는 대조군
        assert "BODY_X" not in stale, (
            "캐시가 재확인되지 않았다 — CPython 이 바뀌었으면 이 축을 다시 판단할 것")


class TestItFailsLoudlyInsteadOfGuessing:
    """조용한 폴백은 '검사한 줄 알았는데 안 한' 상태를 만든다."""

    def test_ambiguous_name_raises(self, temp_module):
        mod = temp_module(
            "def twin():\n    return 1\n\n\ndef twin():\n    return 2\n",
            name="probe_twin",
        )
        with pytest.raises(SourceProbeError, match="2개"):
            source_of(mod.twin)

    def test_vanished_name_raises(self, temp_module):
        mod = temp_module("def gone():\n    return 1\n", name="probe_gone")
        temp_module("def other():\n    return 1\n", name="probe_gone")
        with pytest.raises(SourceProbeError, match="정의가 없다"):
            source_of(mod.gone)

    def test_nested_definition_raises(self, temp_module):
        mod = temp_module(
            "def outer():\n    def inner():\n        return 1\n    return inner\n",
            name="probe_nested",
        )
        with pytest.raises(SourceProbeError, match="중첩"):
            source_of(mod.outer())

    def test_unparsable_file_raises_with_the_real_cause(self, temp_module):
        mod = temp_module("def ok():\n    return 1\n", name="probe_broken")
        temp_module("def ok(:\n", name="probe_broken")
        with pytest.raises(SourceProbeError, match="파싱이 안 된다"):
            source_of(mod.ok)


# --------------------------------------------------------------------------- #
# 저장소 전역 규약
# --------------------------------------------------------------------------- #

# 다른 세션이 **지금 편집 중인** 파일이라 이번에 안 건드렸다. 그 작업이 커밋되면
# 변환하고 이 항목을 지울 것 — 아래 테스트가 필요 없어진 면제를 스스로 잡는다.
#
# ⚠ 남의 미커밋 작업을 내가 고치면 그쪽 저장이 내 쓰기를 덮거나 반대가 된다. 그래서
#   "지금은 안 고친다" 를 침묵이 아니라 **목록**으로 남긴다. 침묵하면 사각이 된다.
_DEFERRED = {
    "tests/unit/test_router_status_and_write_confinement.py":
        "2026-08-25 동시 세션이 편집 중(미커밋). 그 작업이 들어오면 변환할 것",
    # `test_uds_param_grid.py` 는 커밋 `7539713` 으로 들어온 뒤 변환하고 여기서 뺐다 —
    # 아래 `test_deferred_entries_retire_themselves` 가 실패로 그 시점을 알려 준 것이다.
}


def _getsource_hits(path: Path) -> list[int]:
    """`inspect.getsource` / `from inspect import getsource` 호출 줄번호. 마커는 면제."""
    text = path.read_text(encoding="utf-8")
    if "getsource" not in text:
        return []
    tree = ast.parse(text)
    lines = text.splitlines()
    hits: list[int] = []
    for node in ast.walk(tree):
        lineno = None
        if (isinstance(node, ast.Attribute) and node.attr == "getsource"
                and isinstance(node.value, ast.Name) and node.value.id == "inspect"):
            lineno = node.lineno
        elif (isinstance(node, ast.ImportFrom) and node.module == "inspect"
              and any(a.name == "getsource" for a in node.names)):
            lineno = node.lineno
        if lineno and "getsource-ok:" not in lines[lineno - 1]:
            hits.append(lineno)
    return hits


class TestTestsDoNotUseBareGetsource:
    """규약: `tests/` 는 `source_of` 를 쓴다. 예외는 `# getsource-ok: <사유>` 로 남긴다."""

    @pytest.fixture(scope="class")
    def scan(self):
        files = sorted(p for p in (REPO / "tests").rglob("*.py")
                       if "__pycache__" not in p.parts)
        return {p.relative_to(REPO).as_posix(): _getsource_hits(p) for p in files}

    def test_the_scan_is_not_vacuous(self, scan):
        """⚠ 파일을 하나도 못 읽으면 아래 두 테스트가 조용히 통과한다."""
        assert len(scan) > 100, f"tests/ 를 {len(scan)}개밖에 못 봤다 — 스캔 경로 확인"

    def test_no_new_bare_getsource(self, scan):
        offenders = {f: n for f, n in scan.items() if n and f not in _DEFERRED}
        assert not offenders, (
            "맨 `inspect.getsource` 는 import 시점 줄번호를 지금 파일에 적용한다 — 다른 "
            "세션이 저장하면 **다른 함수**를 보고 거짓 실패한다.\n"
            "  `from tests.unit._source_probe import source_of` 를 쓸 것.\n"
            "  런타임에 로드된 코드를 봐야 하면 그 줄에 `# getsource-ok: <사유>`.\n"
            f"  위반: {offenders}")

    def test_deferred_entries_retire_themselves(self, scan):
        """면제가 필요 없어졌는데 남아 있으면 잡는다 — 낡은 면제는 사각을 만든다."""
        for path, why in _DEFERRED.items():
            assert path in scan, f"_DEFERRED 의 {path} 가 없어졌다 — 항목을 지울 것"
            assert scan[path], (
                f"_DEFERRED 의 {path} 에 더는 맨 getsource 가 없다 — 면제를 지울 것 ({why})")
