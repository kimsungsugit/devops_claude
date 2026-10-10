"""R62 (N69) — 죽은 `#if 0` 함수가 문서에 되살아나던 것 · `@명령` 줄이 설명이던 것 · 읽히기만 하던 헤더 문서 주석.

착수 가설("문서 경로의 주석 추출이 사이에 낀 주석을 못 넘는다")은 실측에서 1건뿐이었다. 설명을 잃은 12개 중 11개는
**`#if 0` 안의 죽은 함수**였고, tree-sitter 가 일부러 뺀 그 함수를 정규식 경로 둘이 되살려 KJPDS02 24개 · PDS64 13개가
실재 함수로 올라 있었다(정본엔 0개). 살아 있는 함수 15/9개의 Calling 칸엔 그 죽은 함수가 호출자로 적혀 있었다.

여기서 묶는 것:
1. `dead_preproc_spans`/`blank_dead_preproc_regions` — tree-sitter 판(`_dead_function_nodes`)과 같은 판정, 길이 보존
2. 되살리던 세 입구(파일 전체 폴백 · AST 누락분 병합 · SUTS 경량 폴백)가 죽은 함수를 안 낸다
3. `_parse_comment_fields` — `@` 줄은 설명이 아니다 · `@brief` 가 태그 없는 줄보다 앞선다
4. 헤더 문서 주석 — 같은 루트만 · 정의 주석이 이긴다 · static 제외 · 모호하면 고르지 않되 ASIL 은 높은 쪽
5. 병합 분기가 수집해 둔 주석 필드(`@asil` 포함)를 버리지 않는다
"""
from __future__ import annotations

from pathlib import Path

import pytest

from report_gen import source_parser as sp
from workflow.code_parser import c_parser as cp

NL = "\n"


def _src(*lines: str) -> str:
    return NL.join(lines) + NL


def _scan(text: str) -> str:
    return cp.blank_dead_preproc_regions(cp.blank_c_comments(text))


def _regex_names(text: str) -> list:
    return [f.name for f in cp._extract_function_defs_regex_fallback(text, "a.c", set())]


def _ts_names(text: str) -> list:
    parser = cp._make_parser()
    if parser is None:
        pytest.skip("tree-sitter 미가용")
    data = text.encode("utf-8")
    return [f.name for f in cp._extract_function_defs(parser.parse(data).root_node, data, "a.c", set())]


FN = "void {n}(void)" + NL + "{{" + NL + "    work_{n}();" + NL + "}}"


def _fn(name: str) -> str:
    return FN.format(n=name)


class TestDeadRegions:
    def test_if0_then_branch_is_blanked_else_is_kept(self):
        text = _src("#if 0", _fn("ghost"), "#else", _fn("alive"), "#endif", _fn("after"))
        out = _scan(text)
        assert "ghost" not in out and "alive" in out and "after" in out

    def test_length_and_newlines_are_preserved(self):
        text = _src("int a;", "#if 0", _fn("ghost"), "#endif", "int b;")
        out = _scan(text)
        assert len(out) == len(text)
        assert [i for i, ch in enumerate(out) if ch == NL] == [i for i, ch in enumerate(text) if ch == NL]
        assert out.index("int b;") == text.index("int b;")

    def test_if1_alternative_is_dead_including_later_elif(self):
        text = _src("#if 1", _fn("alive"), "#elif FOO", _fn("g1"), "#else", _fn("g2"), "#endif", _fn("after"))
        assert _regex_names(text) == ["alive", "after"]

    def test_elif_after_if0_is_not_evaluated_and_survives(self):
        # 과대포함이 안전 방향 — `_dead_function_nodes` docstring 과 같은 tradeoff.
        text = _src("#if 0", _fn("ghost"), "#elif BAR", _fn("maybe"), "#else", _fn("other"), "#endif")
        assert _regex_names(text) == ["maybe", "other"]

    def test_nested_conditional_inside_dead_region_does_not_close_it(self):
        text = _src("#if 0", "#ifdef X", _fn("g1"), "#else", _fn("g2"), "#endif", _fn("g3"), "#endif", _fn("alive"))
        assert _regex_names(text) == ["alive"]

    def test_dead_region_nested_in_live_conditional(self):
        text = _src("#ifdef FEATURE", _fn("a1"), "#if 0", _fn("ghost"), "#endif", _fn("a2"), "#endif")
        assert _regex_names(text) == ["a1", "a2"]

    @pytest.mark.parametrize("cond", ["FOO", "defined(X)", "(A == 0)", "0 || X", "10"])
    def test_non_literal_conditions_are_never_dead(self, cond):
        text = _src(f"#if {cond}", _fn("alive"), "#endif")
        assert cp.dead_preproc_spans(cp.blank_c_comments(text)) == []

    @pytest.mark.parametrize("head", ["#if 0", "# if 0", "  #if 0", "#if (0)", "#if 0U", "#if FALSE", "#if 0 /* 임시 */", "#if 0 // off"])
    def test_falsy_spellings(self, head):
        assert _regex_names(_src(head, _fn("ghost"), "#endif", _fn("alive"))) == ["alive"]

    def test_ifdef_and_ifndef_are_never_dead(self):
        text = _src("#ifdef A", _fn("a"), "#endif", "#ifndef B", _fn("b"), "#endif")
        assert _regex_names(text) == ["a", "b"]

    def test_unterminated_if0_blanks_nothing(self):
        text = _src("#if 0", _fn("kept"))
        assert cp.dead_preproc_spans(cp.blank_c_comments(text)) == []
        assert _regex_names(text) == ["kept"]

    def test_if0_inside_a_comment_opens_nothing(self):
        text = _src("/*", "#if 0", "*/", _fn("alive"), "/*", "#endif", "*/")
        assert _regex_names(text) == ["alive"]

    def test_stray_else_and_endif_are_ignored(self):
        text = _src("#else", _fn("a"), "#endif", "#if 0", _fn("ghost"), "#endif")
        assert _regex_names(text) == ["a"]

    def test_no_dead_region_returns_the_same_object(self):
        text = cp.blank_c_comments(_src("#ifdef A", _fn("a"), "#endif"))
        assert cp.blank_dead_preproc_regions(text) is text

    def test_agrees_with_the_tree_sitter_rule(self):
        text = _src(
            _fn("top"),
            "#if 0", _fn("d1"), "#else", _fn("l1"), "#endif",
            "#if 1", _fn("l2"), "#else", _fn("d2"), "#endif",
            "#ifdef X", "#if 0", _fn("d3"), "#endif", _fn("l3"), "#endif",
            "#if 0", "#ifdef Y", _fn("d4"), "#else", _fn("d5"), "#endif", "#endif",
            _fn("tail"),
        )
        assert _regex_names(text) == _ts_names(text) == ["top", "l1", "l2", "l3", "tail"]


class TestNoEntranceResurrectsDeadFunctions:
    DEAD_ONLY = _src("/** @brief 옛 CRC */", "#if 0", _fn("GenerateCrc"), _fn("GetFwCrc"), "#endif")

    def test_whole_file_fallback_returns_nothing_for_an_all_dead_file(self, tmp_path):
        # 입구 ①: tree-sitter 가 0개를 내면 `parse_c_project` 가 파일 전체를 정규식으로 다시 훑는다.
        (tmp_path / "CRC32.c").write_text(self.DEAD_ONLY, encoding="utf-8")
        res = cp.parse_c_project(str(tmp_path))
        assert [f["name"] for f in res["functions"]] == []

    def _project(self, tmp_path: Path) -> Path:
        (tmp_path / "app.c").write_text(
            _src(
                "void callee(void)", "{", "    x = 1;", "}",
                "void live(void)", "{", "    callee();", "}",
                "#if 0",
                "/** @brief 죽은 호출자 */",
                "void ghost(void)", "{", "    callee();", "}",
                "#endif",
            ),
            encoding="utf-8",
        )
        return tmp_path

    def test_sections_do_not_list_dead_functions_or_dead_callers(self, tmp_path):
        # 입구 ②: "AST 가 놓친 함수" 병합 — 죽은 함수는 정의상 AST 에 없다.
        from report_gen.uds_generator import generate_uds_source_sections

        sec = generate_uds_source_sections(str(self._project(tmp_path)))
        details = {v["name"]: v for v in sec["function_details"].values()}
        assert sorted(details) == ["callee", "live"]
        assert details["callee"]["calling"].split(NL) == ["live"]
        assert "ghost" not in sec["call_map"]

    def test_suts_lightweight_fallback_skips_dead_functions(self, tmp_path):
        # 입구 ③: SUTS/SITS 경량 폴백 — 죽은 함수의 시험 케이스를 만들지 않는다.
        from generators.suts import _lightweight_parse

        names = {str(v.get("name")) for v in _lightweight_parse(str(self._project(tmp_path))).values()}
        assert names == {"callee", "live"}


class TestCommandLinesAreNotDescriptions:
    @pytest.mark.parametrize(
        "comment",
        [
            "* @addtogroup driver_cluster_group\n * @{ ",
            "* @fn void f(void)",
            "* @SDD_ID LIN_SDD_169\n* @endif",
            "* @param[in]   (UINT8) *data - LIN Raw Data for LIN Send",
        ],
    )
    def test_a_comment_of_commands_only_has_no_description(self, comment):
        desc = cp._parse_comment_fields(comment)[0]
        assert "@" not in desc and "addtogroup" not in desc and "SDD" not in desc and "LIN Raw" not in desc

    def test_unparsable_param_line_does_not_outrank_brief(self):
        comment = _src(
            " * @param[in]    (LinTpMessageType) *ReqMsg - Request Message",
            " * @brief        sf_LinUdsECUReset - LIN UDS ECUReset Function",
        )
        assert cp._parse_comment_fields(comment)[0].startswith("sf_LinUdsECUReset - LIN UDS ECUReset Function")

    def test_brief_outranks_a_stray_continuation_line(self):
        comment = _src(
            " * @brief   Check firmware version",
            " * @param[in]    (Msg) *ReqMsg - Request Message",
            " *               ReqMsg->data[0]: SID (0x31)",
        )
        assert cp._parse_comment_fields(comment)[0] == "Check firmware version"

    def test_labelled_description_is_kept_over_brief(self):
        comment = _src(" * Description: 모터를 정지한다", " * @brief stop motor")
        assert cp._parse_comment_fields(comment)[0] == "모터를 정지한다"

    def test_plain_first_line_still_describes_when_there_is_no_brief(self):
        assert cp._parse_comment_fields(" * Stops the motor immediately.")[0] == "Stops the motor immediately."

    def test_asil_and_related_are_read_as_before(self):
        comment = _src(" * @brief b", " * ASIL: D", " * Related ID: SwFn_12")
        desc, asil, related, *_ = cp._parse_comment_fields(comment)
        assert (desc, asil, related) == ("b", "D", "SwFn_12")


HEADER = _src(
    "/** @brief Starts the hash",
    " *  ASIL: B",
    " */",
    "void hash_start(void);",
    "/** just a banner */",
    "void no_fields(void);",
    "/** @brief second declaration */",
    "void hash_start(void);",
)


class TestHeaderDocs:
    def test_extracts_fields_with_the_definition_parser(self):
        docs = sp.extract_header_function_docs(HEADER)
        assert docs["hash_start"]["desc"] == "Starts the hash" and docs["hash_start"]["asil"] == "B"

    def test_first_declaration_wins_and_fieldless_comments_are_not_listed(self):
        docs = sp.extract_header_function_docs(HEADER)
        assert sorted(docs) == ["hash_start", "no_fields"]   # 태그 없는 첫 줄도 정의 쪽 파서에선 설명이다
        assert "empty" not in sp.extract_header_function_docs("/** @{ */" + NL + "void empty(void);" + NL)
        assert docs["hash_start"]["desc"] == "Starts the hash"

    def test_only_headers_of_the_same_root_are_candidates(self):
        roots = ["C:/src/APP", "C:/src/FBL"]
        cands = [{"file": "C:/src/FBL/Comms/Comms.h", "desc": "fbl text", "asil": "", "related": ""}]
        assert sp.pick_header_doc(cands, "C:/src/APP/Gen/LINPHY0.c", roots) == {}
        assert sp.pick_header_doc(cands, "C:/src/FBL/Gen/LINPHY0.c", roots)["desc"] == "fbl text"

    def test_nested_roots_resolve_to_the_longest(self):
        roots = ["C:/src", "C:/src/FBL"]
        cands = [{"file": "C:/src/FBL/a.h", "desc": "fbl", "asil": "", "related": ""}]
        assert sp.pick_header_doc(cands, "C:/src/APP/a.c", roots) == {}

    def test_closest_header_wins(self):
        cands = [
            {"file": "C:/p/Lib/x.h", "desc": "far", "asil": "", "related": ""},
            {"file": "C:/p/Sources/APP/x.h", "desc": "near", "asil": "", "related": ""},
        ]
        assert sp.pick_header_doc(cands, "C:/p/Sources/APP/x.c")["desc"] == "near"

    def test_ambiguous_text_is_not_picked_but_asil_takes_the_higher(self):
        cands = [
            {"file": "C:/p/inc/a.h", "desc": "one", "asil": "B", "related": "R1"},
            {"file": "C:/p/inc/b.h", "desc": "two", "asil": "D", "related": "R2"},
        ]
        got = sp.pick_header_doc(cands, "C:/p/src/x.c")
        assert (got["desc"], got["related"], got["asil"]) == ("", "", "D")

    def test_ambiguous_without_any_asil_picks_nothing(self):
        cands = [
            {"file": "C:/p/inc/a.h", "desc": "one", "asil": "", "related": ""},
            {"file": "C:/p/inc/b.h", "desc": "two", "asil": "", "related": ""},
        ]
        assert sp.pick_header_doc(cands, "C:/p/src/x.c") == {}

    def test_identical_duplicates_are_not_ambiguous(self):
        cands = [
            {"file": "C:/p/inc/a.h", "desc": "same", "asil": "A", "related": ""},
            {"file": "C:/p/inc/b.h", "desc": "same", "asil": "A", "related": ""},
        ]
        assert sp.pick_header_doc(cands, "C:/p/src/x.c")["desc"] == "same"


class TestSectionsUseHeaderDocs:
    def _sections(self, tmp_path: Path):
        from report_gen.uds_generator import generate_uds_source_sections

        (tmp_path / "lib.h").write_text(
            _src(
                "/** @brief Starts the hash", " *  ASIL: B", " */", "void hash_start(void);",
                "/** @brief header says this */", "void documented(void);",
                "/** @brief not yours */", "void helper(void);",
            ),
            encoding="utf-8",
        )
        (tmp_path / "lib.c").write_text(
            _src(
                "void hash_start(void)", "{", "    a = 1;", "}",
                "/* definition says this */", "void documented(void)", "{", "    b = 1;", "}",
                "static void helper(void)", "{", "    c = 1;", "}",
            ),
            encoding="utf-8",
        )
        sec = generate_uds_source_sections(str(tmp_path))
        return {v["name"]: v for v in sec["function_details"].values()}

    def test_header_doc_fills_a_definition_without_comment(self, tmp_path):
        d = self._sections(tmp_path)["hash_start"]
        assert d["comment_description"] == "Starts the hash"
        assert (d["description_source"], d["comment_origin"]) == ("comment", "header:lib.h")
        assert (d["asil"], d["asil_source"]) == ("B", "comment")

    def test_definition_comment_wins_over_the_header(self, tmp_path):
        d = self._sections(tmp_path)["documented"]
        assert d["comment_description"] == "definition says this" and d["comment_origin"] == ""

    def test_static_functions_do_not_take_header_docs(self, tmp_path):
        d = self._sections(tmp_path)["helper"]
        assert (d["comment_description"], d["description_source"], d["comment_origin"]) == ("", "inference", "")


class TestHeaderDocsStayInsideTheirSourceRoot:
    def test_another_roots_header_does_not_describe_this_roots_function(self, tmp_path):
        # 실측: 부트로더 트리의 `Comms.h` 주석이 앱 트리의 `LINPHY0.c` 로 갔다 — 이름이 같아도 다른 바이너리다.
        from report_gen.uds_generator import generate_uds_source_sections

        app, fbl = tmp_path / "APP", tmp_path / "FBL"
        app.mkdir()
        fbl.mkdir()
        (app / "phy.c").write_text(_src("void phy_init(void)", "{", "    a = 1;", "}"), encoding="utf-8")
        (fbl / "comms.h").write_text(_src("/** @brief bootloader side init */", "void phy_init(void);"), encoding="utf-8")
        (fbl / "boot.c").write_text(_src("void phy_init(void)", "{", "    b = 1;", "}"), encoding="utf-8")
        sec = generate_uds_source_sections(f"{app};{fbl}")
        by_file = {Path(v["file"]).name: v for v in sec["function_details"].values() if v["name"] == "phy_init"}
        assert by_file["phy.c"]["comment_description"] == "" and by_file["phy.c"]["comment_origin"] == ""
        assert by_file["boot.c"]["comment_description"] == "bootloader side init"
        assert by_file["boot.c"]["comment_origin"] == "header:comms.h"


class TestMergedFunctionsKeepTheirCommentFields:
    def test_a_function_the_ast_missed_keeps_brief_and_asil(self, tmp_path, monkeypatch):
        import workflow.code_parser as pkg
        from report_gen.uds_generator import generate_uds_source_sections

        (tmp_path / "isr.c").write_text(
            _src(
                "void seen(void)", "{", "    a = 1;", "}",
                "/**", " * @brief 인터럽트 진입점", " * @asil D", " */",
                "void missed(void)", "{", "    b = 1;", "}",
            ),
            encoding="utf-8",
        )
        real = pkg.parse_c_project

        def _without_missed(*args, **kwargs):
            res = real(*args, **kwargs)
            res["functions"] = [f for f in res["functions"] if f.get("name") != "missed"]
            return res

        monkeypatch.setattr(pkg, "parse_c_project", _without_missed)
        sec = generate_uds_source_sections(str(tmp_path))
        d = {v["name"]: v for v in sec["function_details"].values()}["missed"]
        assert d["comment_description"] == "인터럽트 진입점" and d["description_source"] == "comment"
        assert (d["asil"], d["asil_source"], d["comment_asil"]) == ("D", "comment", "D")


class TestCacheSchemaMoved:
    def test_schema_version_is_past_v17(self):
        from backend.helpers.uds import _SOURCE_SECTIONS_SCHEMA_VERSION as ver

        assert int(ver.lstrip("v")) >= 18

    def test_parse_derived_cell_caches_moved_too(self):
        # 리뷰 W2: 소스 섹션 캐시만 올리면 변경 매트릭스·베이스라인 diff 셀이 옛 함수 집합(죽은 함수 포함)을 계속 서빙한다.
        from backend.services.baseline_diff import BASELINE_DIFF_ALGO_VERSION
        from backend.services.change_matrix import CHANGE_MATRIX_ALGO_VERSION

        assert CHANGE_MATRIX_ALGO_VERSION >= 2 and BASELINE_DIFF_ALGO_VERSION >= 4


# ── 리뷰(standard) 반영분 ─────────────────────────────────────────────────────────────────────────────────
class TestOneRuleOneImplementation:
    # 리뷰 I1: 주석을 **지우는** 텍스트에 판정을 걸면, 줄 중간에서 시작한 블록 주석이 `#endif` 앞에서 끝날 때
    #   `#endif` 가 줄 머리를 잃어 구간이 안 닫힌다. 주석은 공백 하나로 치환되므로 `*/ #endif` 는 유효한 지시문이다.
    TRICKY = _src("#if 0", _fn("ghost"), "int tail; /* 닫는 줄이", "   다음 줄에 있다 */ #endif", _fn("alive"))

    def test_blank_dead_code_keeps_live_comments_and_length(self):
        raw = _src("/* 머리말 */", "#if 0", "/* 죽은 주석 */", _fn("ghost"), "#endif", "/* 산 주석 */", _fn("alive"))
        out = cp.blank_dead_code(raw)
        assert len(out) == len(raw) and "머리말" in out and "산 주석" in out
        assert "ghost" not in out and "죽은 주석" not in out

    def test_blank_dead_code_without_dead_regions_is_the_same_text(self):
        raw = _src("#ifdef A", _fn("a"), "#endif")
        assert cp.blank_dead_code(raw) == raw

    def test_comment_closing_in_front_of_endif_still_closes_the_region(self, tmp_path):
        from generators.suts import _lightweight_parse
        from report_gen.uds_generator import generate_uds_source_sections

        (tmp_path / "t.c").write_text(self.TRICKY, encoding="utf-8")
        assert _regex_names(self.TRICKY) == ["alive"]
        assert {str(v.get("name")) for v in _lightweight_parse(str(tmp_path)).values()} == {"alive"}
        sec = generate_uds_source_sections(str(tmp_path))
        assert sorted(v["name"] for v in sec["function_details"].values()) == ["alive"]

    def test_crlf_sources_are_judged_the_same(self):
        text = _src("#if 0", _fn("ghost"), "#else", _fn("alive"), "#endif").replace(NL, "\r\n")
        assert _regex_names(text) == ["alive"]


class TestDroppedDefinitionsAreDisclosed:
    def test_sections_report_what_the_regex_path_no_longer_collects(self, tmp_path):
        from report_gen.uds_generator import generate_uds_source_sections

        (tmp_path / "app.c").write_text(_src(_fn("live"), "#if 0", _fn("ghost1"), _fn("ghost2"), "#endif"), encoding="utf-8")
        (tmp_path / "clean.c").write_text(_fn("other") + NL, encoding="utf-8")
        got = generate_uds_source_sections(str(tmp_path))["dead_code_excluded"]
        assert (got["files"], got["functions"]) == (1, 2)
        assert {Path(k).name: v for k, v in got["by_file"].items()} == {"app.c": ["ghost1", "ghost2"]}


class TestCommentParserReviewItems:
    def test_backslash_commands_are_not_descriptions(self):
        assert cp._parse_comment_fields(" * \\addtogroup grp\n * \\ingroup x")[0] == ""

    def test_direction_written_against_param_is_read(self):
        desc, *_rest, params, _ret = cp._parse_comment_fields(" * @brief Sends\n * @param[in] len byte count\n * @param[out]buf target")
        assert [p["name"] for p in params] == ["len", "buf"] and params[0]["desc"] == "byte count"
        assert desc == "Sends (params: len, buf)"

    def test_other_commands_starting_with_param_are_not_params(self):
        assert cp._parse_comment_fields(" * @paramfoo x y")[5] == []

    def test_a_brief_that_is_only_a_name_does_not_replace_prose(self):
        comment = _src(" * 수신 프레임을 파싱해 상태를 갱신한다", " * @brief CRC32_Start")
        assert cp._parse_comment_fields(comment)[0] == "수신 프레임을 파싱해 상태를 갱신한다"

    def test_a_name_only_brief_still_describes_when_nothing_else_does(self):
        assert cp._parse_comment_fields(" * @brief CRC32_Start")[0] == "CRC32_Start"


class TestHeaderDocReviewItems:
    def test_dead_prototypes_do_not_document(self):
        hdr = _src("#if 0", "/** @brief old text */", "void f(void);", "#endif", "/** @brief live text */", "void f(void);")
        assert sp.extract_header_function_docs(hdr)["f"]["desc"] == "live text"

    def test_function_pointer_typedef_is_not_a_function_named_void(self):
        hdr = _src("/** @brief callback type */", "typedef void (*Cb)(void);")
        assert sp.extract_header_function_docs(hdr) == {}

    def test_differing_precondition_is_ambiguous_too(self):
        cands = [
            {"file": "C:/p/inc/a.h", "desc": "same", "asil": "", "related": "", "precondition": "init done"},
            {"file": "C:/p/inc/b.h", "desc": "same", "asil": "", "related": "", "precondition": "none"},
        ]
        assert sp.pick_header_doc(cands, "C:/p/src/x.c") == {}

    def test_ambiguous_asil_does_not_name_a_header(self):
        cands = [
            {"file": "C:/p/inc/a.h", "desc": "one", "asil": "B", "related": ""},
            {"file": "C:/p/inc/b.h", "desc": "two", "asil": "D", "related": ""},
        ]
        assert sp.pick_header_doc(cands, "C:/p/src/x.c")["file"] == ""

    def test_files_outside_every_root_are_matched_among_themselves(self):
        cands = [{"file": "D:/elsewhere/x.h", "desc": "d", "asil": "", "related": ""}]
        assert sp.pick_header_doc(cands, "D:/elsewhere/x.c", ["C:/src/APP"])["desc"] == "d"
        assert sp.pick_header_doc(cands, "C:/src/APP/x.c", ["C:/src/APP"]) == {}

    def test_sections_label_an_ambiguous_grade_without_naming_a_header(self, tmp_path):
        from report_gen.uds_generator import generate_uds_source_sections

        (tmp_path / "a.h").write_text(_src("/** @brief one", " *  ASIL: B */", "void f(void);"), encoding="utf-8")
        (tmp_path / "b.h").write_text(_src("/** @brief two", " *  ASIL: D */", "void f(void);"), encoding="utf-8")
        (tmp_path / "f.c").write_text(_fn("f") + NL, encoding="utf-8")
        d = {v["name"]: v for v in generate_uds_source_sections(str(tmp_path))["function_details"].values()}["f"]
        assert (d["asil"], d["asil_source"], d["comment_origin"]) == ("D", "comment", "header:ambiguous")
        assert (d["comment_description"], d["description_source"]) == ("", "inference")


class TestMergedBranchProvenance:
    def _sections(self, tmp_path, monkeypatch, header: str = ""):
        import workflow.code_parser as pkg
        from report_gen.uds_generator import generate_uds_source_sections

        (tmp_path / "isr.c").write_text(
            _src("/** @file isr.c", " *  ASIL: C", " */", _fn("seen"), "void missed(void)", "{", "    b = 1;", "}"),
            encoding="utf-8",
        )
        if header:
            (tmp_path / "isr.h").write_text(header, encoding="utf-8")
        real = pkg.parse_c_project

        def _without_missed(*args, **kwargs):
            res = real(*args, **kwargs)
            res["functions"] = [f for f in res["functions"] if f.get("name") != "missed"]
            return res

        monkeypatch.setattr(pkg, "parse_c_project", _without_missed)
        sec = generate_uds_source_sections(str(tmp_path))
        return {v["name"]: v for v in sec["function_details"].values()}["missed"]

    def test_file_header_grade_is_not_reported_as_the_functions_own_comment(self, tmp_path, monkeypatch):
        # 리뷰 W1: 수집 단계의 `comment_asil` 은 `자기 주석 or 파일 머리말` 이다 — 그대로 실으면 출처가 세탁된다.
        d = self._sections(tmp_path, monkeypatch)
        assert d["asil_source"] != "comment" and d["comment_asil"] == ""

    def test_header_doc_reaches_a_merged_function_with_origin_and_precondition(self, tmp_path, monkeypatch):
        hdr = _src("/** @brief 타이머 인터럽트", " *  ASIL: B", " *  @pre 타이머 초기화 완료", " */", "void missed(void);")
        d = self._sections(tmp_path, monkeypatch, hdr)
        assert (d["comment_description"], d["asil"], d["asil_source"]) == ("타이머 인터럽트", "B", "comment")
        assert (d["comment_origin"], d["precondition"]) == ("header:isr.h", "타이머 초기화 완료")


class TestOriginReachesTheViewPayload:
    def test_view_payload_carries_comment_origin_from_the_sidecar(self, tmp_path, monkeypatch):
        # 리뷰 W1: `comment_origin` 이 진실을 들고 있어도 하류에 전달되지 않으면 헤더 출처가 "함수 주석" 으로만 보인다.
        import json

        import backend.helpers.uds as uds

        docx = tmp_path / "out.docx"
        docx.write_bytes(b"x")
        docx.with_suffix(".payload.json").write_text(
            json.dumps({"function_details": {"SwUFn_0101": {"id": "SwUFn_0101", "name": "f", "asil_source": "comment",
                                                            "comment_origin": "header:lib.h"}}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(uds, "build_uds_view_payload", lambda *a, **k: {"functions": [{"id": "SwUFn_0101", "name": "f"}]})
        fn = uds._get_uds_view_payload_cached(docx)["functions"][0]
        assert (fn["asil_source"], fn["comment_origin"]) == ("comment", "header:lib.h")
