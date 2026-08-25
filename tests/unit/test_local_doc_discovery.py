# tests/unit/test_local_doc_discovery.py
r"""`_doc_or_discovered` — 지정 입력을 저장소 docs/ 문서로 조용히 바꿔치기하지 않는다.

회귀 대상: 라우터 17곳이 `if not <resolved>:` 하나로 "사용자가 아무것도 안 줌" 과
"사용자가 줬는데 해석 실패" 를 묶어 처리했다. cloudium worker-only 경로(`U:\…`)는
로컬 `Path.exists()` 가 항상 False 라 후자에 해당하는데, 그때 저장소 `docs/` 에 들어있는
**다른 프로젝트 문서**(현재 HDPDM01)로 대체됐고 로그는 "auto-discovered" 라 기능처럼
읽혔다. SDS 는 요구-함수 매핑 전체를 좌우하므로(링크 5,992건 전량) 산출물이 통째로
남의 프로젝트 설계 기준이 됐다.
"""

from __future__ import annotations

import pytest

from backend.routers.local import _doc_or_discovered


class TestDocOrDiscovered:
    @staticmethod
    def _discover():
        return "/repo/docs/(HDPDM01_SDS) other project.docx"

    def test_resolved_path_wins(self):
        assert _doc_or_discovered("/user/real.docx", "U:/x.docx",
                                  self._discover, label="SDS") == "/user/real.docx"

    def test_unresolvable_user_input_is_not_substituted(self, caplog):
        """지정했는데 못 읽으면 None — 저장소 문서로 바꿔치기 금지."""
        with caplog.at_level("WARNING", logger="backend.routers.local"):
            got = _doc_or_discovered(None, "U:/연구소/KJPDS02_SwDS.docx",
                                     self._discover, label="SDS")
        assert got is None, "다른 프로젝트 문서로 대체됐다"
        assert "SDS" in caplog.text and "대체" in caplog.text, caplog.text

    def test_absent_user_input_falls_back_to_discovery(self, caplog):
        """대조군: 아무것도 안 주면 자동 탐색은 정당한 편의다(기존 동작 유지)."""
        with caplog.at_level("INFO", logger="backend.routers.local"):
            got = _doc_or_discovered(None, "", self._discover, label="SDS")
        assert got == self._discover()
        assert "자동 탐색" in caplog.text

    @pytest.mark.parametrize("supplied", ["", None, False, 0, []])
    def test_falsy_inputs_count_as_not_supplied(self, supplied):
        assert _doc_or_discovered(None, supplied, self._discover, label="SRS") == self._discover()

    @pytest.mark.parametrize("supplied", ["U:/a.docx", True, ["u.docx"], "   x"])
    def test_truthy_inputs_count_as_supplied(self, supplied):
        assert _doc_or_discovered(None, supplied, self._discover, label="SRS") is None

    def test_discovery_returning_none_is_fine(self):
        assert _doc_or_discovered(None, "", lambda: None, label="HSIS") is None

    def test_tag_is_prefixed_in_log(self, caplog):
        with caplog.at_level("WARNING", logger="backend.routers.local"):
            _doc_or_discovered(None, "U:/x", self._discover, label="SRS", tag="[STS_GENERATE] ")
        assert "[STS_GENERATE]" in caplog.text


class TestAllSitesUseTheHelper:
    """라우터에 침묵 대체 잔재가 남아 있으면 안 된다(한 곳만 고치면 다른 곳이 잠복)."""

    def test_no_bare_auto_discover_fallback_remains(self):
        """옛 형태는 `_logger.info(... auto-discovered ...)` 로 끝났다 — 그 호출이 0이어야 한다.

        docstring 안의 '경위 설명' 은 코드가 아니므로 AST 로 실제 호출만 본다.
        """
        import ast

        import backend.routers.local as mod
        from tests.unit._source_probe import source_of

        tree = ast.parse(source_of(mod))
        offenders = [
            ast.unparse(node)[:120]
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for arg in node.args
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            and "auto-discovered" in arg.value
        ]
        assert offenders == [], offenders

    def test_every_discovery_helper_is_reached_through_the_gate(self):
        """`_discover_srs_docx`/`_discover_sds_docx`/`_discover_hsis_path` 는
        `_doc_or_discovered` 인자로만 넘겨져야 한다(직접 호출하면 게이트를 우회한다).

        예외: `_enrich_function_details_map` 은 사용자 HSIS 입력 파라미터 자체가 없어
        자동 탐색이 유일한 출처다 — 대체가 아니므로 허용.
        """
        import ast

        import backend.routers.local as mod
        from tests.unit._source_probe import source_of

        gated = {"_discover_srs_docx", "_discover_sds_docx", "_discover_hsis_path"}
        tree = ast.parse(source_of(mod))
        # _doc_or_discovered 에 **인자로** 넘어간 이름은 호출이 아니라 참조다.
        direct_calls = [
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in gated
        ]
        # 허용 1건: _enrich_function_details_map 내부 _discover_hsis_path()
        assert direct_calls.count("_discover_hsis_path") <= 1, direct_calls
        assert "_discover_srs_docx" not in direct_calls
        assert "_discover_sds_docx" not in direct_calls
