"""R77 — R76 에서 나온 후속 6건(N107 · N110~N114) 중 생성기·라우터 쪽 가드. 화면 공시(N110)는 `test_generation_disclosures_r77.py`.

N107 과 N112 는 **전제가 뒤집힌** 항목이다 — "보강을 태우면 못 붙는 함수가 110 → 13" 은 추측 매칭이 만든 수였고,
SUTS ASIL 폴백의 토큰 한가운데 일치는 라이브·오프라인 모두 0건이었다. 그래서 여기 가드는 "배선을 **안** 했다" 와
"추측 링크가 강한 근거로 세탁되지 않는다" 를 묶는다. 실측은 계획서 R77 절.
"""
from __future__ import annotations

import inspect

import pytest


# ── N107: 보강 매처의 추측 링크는 '자기 related' 가 아니다 ─────────────────────
class TestFuzzyEnrichmentIsNotOwnRelated:
    REQS = [{"id": "SwTR_0101"}, {"id": "SwTR_0202"}, {"id": "SwTR_0303"}]

    @pytest.mark.parametrize("info, want", [
        ({"related": "SwTR_0101", "related_source": "sds", "sds_match_mode": "related_prototype"}, True),
        ({"related": "SwTR_0101", "related_source": "sds", "sds_match_mode": "normalized_overlap"}, True),
        ({"name": "lin_get_status", "related": "SwTR_0101", "related_source": "sds", "sds_match_mode": "direct",
          "sds_match_key": "lin_get_status"}, False),
        ({"name": "x", "module_name": "LinUds", "related": "SwTR_0101", "related_source": "sds",
          "sds_match_mode": "normalized_exact", "sds_match_key": "lin_uds"}, False),
        # (리뷰 W1) 보강의 `normalized_exact` 는 한글을 버린다 — `open` 만 남아 "정확히" 맞은 것은 이름 일치가 아니다
        ({"name": "u16s_MotorOpenCircuitRun", "module_name": "Open", "related": "SwTR_0606", "related_source": "sds",
          "sds_match_mode": "normalized_exact", "sds_match_key": "차속에 따른 도어 open 방지"}, True),
        ({"name": "f", "related": "SwTR_0101", "related_source": "sds", "sds_match_mode": "direct"}, True),   # 맞았다는 키가 없다 — 확인 불가
        ({"related": "SwTR_0101", "related_source": "sds"}, False),                       # 방식 기록 없음 = 보강을 안 탄 값
        ({"related": "SwTR_0101", "related_source": "comment", "sds_match_mode": "related_prototype"}, False),
        ({"related": "SwTR_0101", "related_source": "override", "sds_match_mode": "related_prototype"}, False),
        ({"related": "SwTR_0101"}, False),
    ])
    def test_predicate(self, info, want):
        from generators.sts import _related_is_fuzzy_enrichment

        assert _related_is_fuzzy_enrichment(info) is want

    def test_the_sds_lookup_wins_over_a_fuzzy_related(self):
        """두 매처가 갈리면 이름으로 찾은 쪽이 이긴다 — 추측 값은 버려진다(실측 236 함수)."""
        from generators.sts import map_requirements_to_functions

        details = {"f1": {"name": "lin_get_status", "related": "SwTR_0303", "related_source": "sds",
                          "sds_match_mode": "related_prototype"}}
        stats: dict = {}
        got = map_requirements_to_functions(self.REQS, details, sds_map={"lin_get_status": {"related": "SwTR_0101"}}, stats_out=stats)
        assert got == {"SwTR_0101": ["f1"], "SwTR_0202": [], "SwTR_0303": []}
        assert stats["requirement_function_mapping"]["functions_by_path"] == {"own_related": 0, "sds_exact": 1}

    def test_a_fuzzy_related_links_only_when_nothing_else_does_and_says_so(self):
        from generators.sts import map_requirements_to_functions

        details = {"f1": {"name": "PP1_BUZZER_PWM_Disable", "related": "SwTR_0202", "related_source": "sds",
                          "sds_match_mode": "related_prototype"},
                   "f2": {"name": "own", "related": "SwTR_0101", "related_source": "sds", "sds_match_mode": "direct",
                          "sds_match_key": "own"},
                   "f3": {"name": "nothing_at_all"}}
        stats: dict = {}
        got = map_requirements_to_functions(self.REQS, details, sds_map={}, stats_out=stats)
        assert (got["SwTR_0202"], got["SwTR_0101"]) == (["f1"], ["f2"])
        m = stats["requirement_function_mapping"]
        assert m["functions_by_path"] == {"own_related": 1, "enrich_fuzzy": 1}
        assert (m["design_id_bridge_only"], m["unlinked"], m["functions_total"]) == (0, 1, 3)
        assert sum(m["functions_by_path"].values()) + m["design_id_bridge_only"] + m["unlinked"] == m["functions_total"]

    def test_a_fuzzy_related_outside_the_srs_does_not_count_as_a_link(self):
        from generators.sts import map_requirements_to_functions

        details = {"f1": {"name": "x", "related": "SwTR_9999", "related_source": "sds", "sds_match_mode": "related_prototype"}}
        stats: dict = {}
        map_requirements_to_functions(self.REQS, details, sds_map={}, stats_out=stats)
        m = stats["requirement_function_mapping"]
        assert m["functions_by_path"] == {"own_related": 0} and m["unlinked"] == 1

    def test_jenkins_sts_handler_does_not_feed_srs_and_sds_into_the_enrichment(self):
        """배선을 **일부러 안 했다** — 누가 '빠진 배선' 으로 읽고 이으면 이 테스트가 그 결정의 실측을 가리킨다."""
        from backend.routers import jenkins
        from tests.unit._source_probe import source_of

        src = source_of(jenkins.jenkins_sts_generate_async)
        code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
        assert "req_doc_paths.append(srs_docx_path" not in code and "sds_doc_paths.append(sds_docx_path" not in code
        assert "req_doc_paths.append(str(srs" not in code and "sds_doc_paths.append(str(sds" not in code
        assert "R77 N107" in src


class TestNormalizedMatchBeforeSubstring:
    def test_module_exact_match_beats_a_function_name_substring(self):
        """`sf_GetEepromVersionState`(모듈 `LinUds`) — 이름 속 `eeprom` 이 모듈의 정확한 파티션을 가렸다(실측 6 함수)."""
        from generators.sts import _lookup_sds_related_ids

        sds = {"eeprom": {"related": "SwNTR_0301"}, "lin_uds": {"related": "SwTR_0501"}}
        path: list = []
        got = _lookup_sds_related_ids({"name": "sf_GetEepromVersionState", "module_name": "LinUds"}, sds, path_out=path)
        assert (got, path) == (["SwTR_0501"], ["sds_normalized"])

    def test_map_order_does_not_decide(self):
        from generators.sts import _lookup_sds_related_ids

        sds = {"lin_uds": {"related": "SwTR_0501"}, "eeprom": {"related": "SwNTR_0301"}}
        assert _lookup_sds_related_ids({"name": "sf_GetEepromVersionState", "module_name": "LinUds"}, sds) == ["SwTR_0501"]

    def test_substring_still_works_when_nothing_matches_exactly(self):
        from generators.sts import _lookup_sds_related_ids

        path: list = []
        got = _lookup_sds_related_ids({"name": "sf_GetEepromVersionState", "module_name": "Other"},
                                      {"eeprom": {"related": "SwNTR_0301"}}, path_out=path)
        assert (got, path) == (["SwNTR_0301"], ["sds_substring"])

    def test_a_normalized_match_with_an_empty_related_does_not_stop_the_search(self):
        from generators.sts import _lookup_sds_related_ids

        sds = {"lin_uds": {"related": ""}, "eeprom": {"related": "SwNTR_0301"}}
        assert _lookup_sds_related_ids({"name": "sf_GetEepromVersionState", "module_name": "LinUds"}, sds) == ["SwNTR_0301"]

    def test_exact_key_is_still_first(self):
        from generators.sts import _lookup_sds_related_ids

        sds = {"lin_uds": {"related": "SwTR_0501"}, "sf_geteepromversionstate": {"related": "SwTR_0707"}}
        path: list = []
        got = _lookup_sds_related_ids({"name": "sf_GetEepromVersionState", "module_name": "LinUds"}, sds, path_out=path)
        assert (got, path) == (["SwTR_0707"], ["sds_exact"])


# ── N111: 저장소 docs/ 의 HSIS 를 어디서도 끌어오지 않는다 ────────────────────
_LOCAL_DOC_HANDLERS = ("local_sts_generate", "local_sts_generate_stream", "local_sts_generate_async",
                       "local_suts_generate", "local_suts_generate_stream", "local_suts_generate_async",
                       "local_sits_generate", "local_sits_generate_stream", "local_sits_generate_async")


class TestNoForeignHsis:
    @pytest.mark.parametrize("name", _LOCAL_DOC_HANDLERS)
    def test_every_local_handler_uses_no_discovery(self, name):
        from backend.routers import local
        from tests.unit._source_probe import source_of

        assert source_of(getattr(local, name)).count('_no_discovery, label="HSIS")') == 1, name

    def test_the_discovery_function_is_gone(self):
        from backend.routers import local
        from tests.unit._source_probe import source_of

        assert not hasattr(local, "_discover_hsis_path")
        code = "\n".join(ln for ln in source_of(local).splitlines() if "_discover_hsis_path" in ln and not ln.lstrip().startswith(("#", "Jenkins")))
        assert code == "", code

    @staticmethod
    def _hsis(path):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "2.HSIS"
        ws.append(["ID", "Signal Name", "Type", "Direction", "Characteristics", "SW Variable Name", "Related ID"])
        ws.append(["HSI_01", "VSUP", "AI", "IN", "-", "PIEL_PIEL0", "SwTR_0777"])
        wb.save(path)
        return str(path)

    @staticmethod
    def _details():
        return {"f1": {"name": "f", "related": "TBD", "related_source": "default", "description": "",
                       "globals_read": {"PIEL_PIEL0": 1}, "globals_write": {}, "inputs": [], "outputs": []}}

    @pytest.fixture
    def quiet_docs(self, monkeypatch):
        from backend.routers import local

        monkeypatch.setattr(local, "_resolve_req_doc_sets", lambda a, b: ([], []))
        monkeypatch.setattr(local, "enrich_function_details_with_docs", lambda *a, **k: None)
        return local

    def test_without_a_given_hsis_the_function_details_are_untouched_and_no_hsis_is_read(self, quiet_docs, monkeypatch):
        from generators import sts as gsts

        def _boom(_p):
            raise AssertionError("HSIS 를 읽었다 — 준 적이 없는데")

        monkeypatch.setattr(gsts, "_load_hsis_signals", _boom)
        # 경로 해석조차 시도하지 않는다 — "없는 기본 경로를 찾다가 조용히 포기" 도 남의 문서를 뒤지는 것이다(뮤턴트 C1)
        from backend.services import resolver_helpers

        monkeypatch.setattr(resolver_helpers, "resolve_builder_input", lambda *a, **k: _boom(a))
        details, _, _ = quiet_docs._enrich_function_details_map(self._details())
        assert (details["f1"]["related"], details["f1"]["related_source"]) == ("TBD", "default")

    def test_a_given_hsis_is_used(self, quiet_docs, tmp_path):
        from generators import sts as gsts

        gsts._HSIS_CACHE.clear() if hasattr(gsts, "_HSIS_CACHE") else None
        details, _, _ = quiet_docs._enrich_function_details_map(self._details(), hsis_path=self._hsis(tmp_path / "h.xlsx"))
        assert (details["f1"]["related"], details["f1"]["related_source"]) == ("SwTR_0777", "hsis")

    def test_an_unreadable_given_hsis_is_skipped_with_a_warning(self, quiet_docs, tmp_path, caplog):
        with caplog.at_level("WARNING"):
            details, _, _ = quiet_docs._enrich_function_details_map(self._details(), hsis_path=str(tmp_path / "missing.xlsx"))
        assert details["f1"]["related_source"] == "default"
        assert any("HSIS 보강을 건너뛴다" in r.getMessage() for r in caplog.records)

    @pytest.mark.parametrize("name", [n for n in _LOCAL_DOC_HANDLERS if "_sts_" in n])
    def test_sts_handlers_pass_their_own_hsis_to_the_enrichment(self, name):
        from backend.routers import local
        from tests.unit._source_probe import source_of

        assert source_of(getattr(local, name)).count("hsis_path=hsis_path,") == 1, name


# ── N113: 상충 공시는 설계서 원문을 같이 보인다 ────────────────────────────────
class TestRangeConflictShowsTheDocumentText:
    def test_parser_keeps_the_raw_cell_text(self, tmp_path):
        from generators.uds_unit_io import load_uds_unit_io, resolve_unit_io
        from tests.unit.test_uds_unit_io import _docx, _fn_table, _para, _row

        body = _fn_table(
            _row("[ Function Information ]") + _row("ID", "SwUFn_0001") + _row("Name", "f")
            + _row("[ Input Parameters ]")
            + _row("No", "Name", "Type", "Value Range", "Reset Value", "Description")
            + _row("1", "s32s_DecelPos", "S32", "0x7FFFFFF~   0x80000000", "0", "d")
            + _row("2", "u8_Ok", "U8", "N/A", "0", "d"))
        rec = resolve_unit_io(load_uds_unit_io(_docx(_para("SwUFn_0001: f") + body, tmp_path)), "f")["param_info"]
        assert rec["s32s_DecelPos"] == {"type": "S32", "range": [134217727, 2147483648], "range_text": "0x7FFFFFF~ 0x80000000"}
        assert rec["u8_Ok"] == {"type": "U8"}                     # 범위를 못 읽은 칸엔 원문도 싣지 않는다

    def test_conflict_message_carries_the_raw_text(self):
        from generators.suts import generate_sequences

        u = {"name": "f", "fid": "F", "input_vars": ["s32s_DecelPos"], "output_vars": [], "param_types": {"s32s_DecelPos": "S32"},
             "uds_param_info": {"s32s_DecelPos": {"range": [134217727, 2147483648], "range_text": "0x7FFFFFF~ 0x80000000"}}}
        generate_sequences(u, type_cache={})
        assert u["range_conflicts"] == ["s32s_DecelPos(SwUDS 134217727~2147483648 vs int32_t) ← 원문 `0x7FFFFFF~ 0x80000000`"]
        assert u["bounds_source"]["s32s_DecelPos"] == "type"

    def test_an_hsis_conflict_does_not_borrow_the_swuds_text(self):
        """설계서 범위도 HSIS 범위도 안 맞는 변수 — 원문은 **그 문서의 것**에만 붙는다."""
        from generators.suts import generate_sequences

        u = {"name": "f", "fid": "F", "input_vars": ["k"], "output_vars": [], "param_types": {"k": "U8"},
             "uds_param_info": {"k": {"range": [0, 999], "range_text": "0 ~ 999"}}, "hsis_bounds": {"k": [0, 5000]}}
        generate_sequences(u, type_cache={})
        assert u["range_conflicts"] == ["k(SwUDS 0~999 vs uint8_t) ← 원문 `0 ~ 999`", "k(HSIS 0~5000 vs uint8_t)"]

    def test_without_raw_text_the_message_is_unchanged(self):
        from generators.suts import generate_sequences

        u = {"name": "f", "fid": "F", "input_vars": ["k"], "output_vars": [], "param_types": {"k": "U8"},
             "uds_param_info": {"k": {"range": [0, 999]}}}
        generate_sequences(u, type_cache={})
        assert u["range_conflicts"] == ["k(SwUDS 0~999 vs uint8_t)"]

    @pytest.mark.parametrize("text, want", [
        ("0x80000000 ~ 0x7FFFFFFF", (-2147483648, 2147483647)),      # 정상 표기 — 2의 보수 전폭
        ("0x7FFFFFF~ 0x80000000", (134217727, 2147483648)),           # 문서의 오타(F 일곱) — 파서는 적힌 대로 읽는다
        ("0x7FFFF  ~ 0x8000", None),
    ])
    def test_the_parser_reads_what_is_written(self, text, want):
        from generators.uds_unit_io import parse_value_range

        assert parse_value_range(text) == want


# ── N114: 시트 이름의 번호 접두 · 선택 시트는 판정을 안 뒤집는다 ───────────────
class TestSheetNames:
    @pytest.mark.parametrize("a, b", [("1.Introduction", "Introduction"), ("1. Test Environment", "2.Test Environment"),
                                      (" 3.Traceability ", "traceability")])
    def test_base_name(self, a, b):
        from generators._artifact_check import sheet_base_name

        assert sheet_base_name(a) == sheet_base_name(b) != ""

    def test_a_number_inside_the_name_is_kept(self):
        from generators._artifact_check import sheet_base_name

        assert sheet_base_name("2.SW Unit Test Spec") != sheet_base_name("SW Unit Test Spec v2.1")
        assert sheet_base_name("Rev2.Notes") == "rev2.notes" and sheet_base_name("SW Unit Test Spec v2.1") == "sw unit test spec v2.1"

    @staticmethod
    def _suts(tmp_path, rename=None, drop=None):
        from openpyxl import load_workbook

        from generators.suts import generate_suts_xlsm

        units = [{"fid": "F1", "name": "f", "component": "SwCom_01", "input_vars": ["a"], "output_vars": [], "asil": "QM"}]
        seqs = {"F1": [{"seq_num": 1, "strategy": "BV_MID", "inputs": {"a": 1}, "expected": {}}]}
        out = generate_suts_xlsm(None, units, seqs, str(tmp_path / "s.xlsx"), {"project_id": "T"})
        wb = load_workbook(out)
        for old, new in (rename or {}).items():
            wb[old].title = new
        for name in drop or ():
            del wb[name]
        wb.save(out)
        return out

    def test_reference_style_sheet_name_is_found(self, tmp_path):
        from generators.suts import validate_suts_xlsm

        v = validate_suts_xlsm(self._suts(tmp_path, rename={"1.Introduction": "Introduction"}))
        assert v["valid"] is True and v["issues"] == []
        assert not any("Introduction" in w for w in v["warnings"])

    def test_a_missing_optional_sheet_warns_but_does_not_fail(self, tmp_path):
        from generators.suts import validate_suts_xlsm

        v = validate_suts_xlsm(self._suts(tmp_path, drop=["1.Introduction"]))
        assert v["valid"] is True and v["issues"] == []
        assert "Optional sheet missing: 1.Introduction" in v["warnings"]

    def test_the_required_sheet_still_fails(self, tmp_path):
        from generators.suts import validate_suts_xlsm

        v = validate_suts_xlsm(self._suts(tmp_path, rename={"2.SW Unit Test Spec": "Spec"}))
        assert v["valid"] is False and any("Missing required sheet" in i for i in v["issues"])

    def test_legacy_validator_uses_the_same_rule(self, tmp_path):
        from generators.suts import validate_suts_output

        st = validate_suts_output(self._suts(tmp_path, rename={"1.Introduction": "Introduction"}))
        assert not any("Introduction" in i for i in (st.get("issues") or []) + (st.get("warnings") or []))

    @pytest.mark.parametrize("drop", ["1.Test Environment", "1.Introduction"])
    def test_the_two_suts_validators_agree_on_a_missing_optional_sheet(self, tmp_path, drop):
        """(리뷰 W3) 같은 파일을 두 검증기가 PASS/FAIL 로 갈라 말하면 안 된다."""
        from generators.suts import validate_suts_output, validate_suts_xlsm

        out = self._suts(tmp_path, drop=[drop])
        a, b = validate_suts_xlsm(out), validate_suts_output(out)
        assert a["issues"] == [] and not [i for i in (b.get("issues") or []) if "sheet" in i.lower()]
        assert f"Optional sheet missing: {drop}" in a["warnings"] and f"Optional sheet missing: {drop}" in b["warnings"]

    def test_spec_sheet_without_the_number_prefix_is_still_validated(self, tmp_path):
        """(리뷰 I4) 명세 시트 이름이 번호만 다르면 **찾아서 검사한다** — 못 찾으면 TC·시퀀스 검사가 통째로 건너뛰어졌다."""
        from generators.suts import validate_suts_output, validate_suts_xlsm

        out = self._suts(tmp_path, rename={"2.SW Unit Test Spec": "SW Unit Test Spec"})
        v = validate_suts_xlsm(out)
        assert v["valid"] is True and v["stats"]["tc_count"] == 1 and v["stats"]["seq_count"] == 1
        assert not any("sheet" in i.lower() for i in validate_suts_output(out).get("issues") or [])

    def test_sts_validator_uses_the_same_rule(self, tmp_path):
        from openpyxl import load_workbook

        from generators.sts import generate_sts_xlsm, validate_sts_xlsm

        tc = {"id": "SwTC_001", "title": "t", "safety_related": "X", "test_environment": "SwTE_01", "test_method": "RBT",
              "gen_method": "AOR", "fs_req": "", "description": "d", "precondition": "p", "srs_id": "SwTR_0001",
              "steps": [{"action": "a1", "expected": "e1"}, {"action": "a2", "expected": "e2"}]}
        out = generate_sts_xlsm(None, [tc], {"matrix": [], "coverage": {}}, str(tmp_path / "t.xlsx"), {})
        before = [w for w in validate_sts_xlsm(out)["warnings"] if "Optional sheet missing" in w]
        wb = load_workbook(out)
        wb["1.Introduction"].title = "Introduction"
        wb.save(out)
        after = [w for w in validate_sts_xlsm(out)["warnings"] if "Optional sheet missing" in w]
        assert before == after == []


# ── N112: 코드 없이 닫은 항목의 전제를 고정한다 ───────────────────────────────
class TestSutsAsilFallbackCandidates:
    def test_candidates_come_from_the_module_name_only(self):
        """`Re[adC]ustom` ⊃ `adc` 류 오귀속은 **함수 이름**이 후보일 때 난다(STS 매퍼). SUTS ASIL 폴백은 모듈 이름만 후보라
        그 부류가 생기지 않는다 — 실측 KJPDS02: 폴백만 돌려도 토큰 한가운데 첫 매치 0건, 라이브는 폴백 사용 0/933."""
        from generators.suts import _resolve_unit_asil

        assert _resolve_unit_asil({"name": "s_ReadCustomPayload", "module_name": ""}, {"adc": {"asil": "B"}}) == ("", "")
        src = inspect.getsource(_resolve_unit_asil)  # getsource-ok: 같은 프로세스에서 방금 import 한 함수의 후보 구성을 본다
        assert 'info.get("name")' not in src and "module_name" in src
