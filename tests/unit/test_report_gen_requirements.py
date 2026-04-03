"""Unit tests for report_gen.requirements — parsing, mapping, extraction."""
from __future__ import annotations

import pytest


class TestExtractTableSection:
    def test_finds_section(self):
        from report_gen.requirements import _extract_table_section

        lines = [
            "Introduction",
            "some intro text",
            "",
            "Function List",
            "FuncA  SwUFn_01",
            "FuncB  SwUFn_02",
            "",
            "Summary",
        ]
        result = _extract_table_section(lines, "Function List", ["Summary"], 10)
        assert len(result) == 2
        assert "FuncA" in result[0]

    def test_header_not_found(self):
        from report_gen.requirements import _extract_table_section

        result = _extract_table_section(["line1", "line2"], "Missing", [], 10)
        assert result == []

    def test_max_rows_limit(self):
        from report_gen.requirements import _extract_table_section

        lines = ["Header"] + [f"row{i}" for i in range(20)]
        result = _extract_table_section(lines, "Header", [], 5)
        assert len(result) == 5


class TestNormalizeTableRow:
    def test_splits_by_whitespace(self):
        from report_gen.requirements import _normalize_table_row

        result = _normalize_table_row("col1  col2\tcol3")
        assert result == ["col1", "col2", "col3"]

    def test_empty(self):
        from report_gen.requirements import _normalize_table_row

        assert _normalize_table_row("") == []


class TestExtractFunctionBlocks:
    def test_parses_blocks(self):
        from report_gen.requirements import _extract_function_blocks

        text = (
            "SwCom_01\n"
            "SwUFn_0101: Motor_Init\n"
            "ID SwUFn_0101\n"
            "Name Motor_Init\n"
            "Description Init motor module\n"
            "ASIL B\n"
            "SwUFn_0102: Motor_Run\n"
            "ID SwUFn_0102\n"
            "Name Motor_Run\n"
        )
        blocks = _extract_function_blocks(text)
        # The parser creates separate blocks for header lines and ID lines
        assert len(blocks) >= 2
        names = [b.get("name") for b in blocks if b.get("name")]
        assert "Motor_Init" in names
        assert "Motor_Run" in names
        # Verify SwCom propagation
        assert all(b.get("swcom") == "SwCom_01" for b in blocks)

    def test_empty(self):
        from report_gen.requirements import _extract_function_blocks

        assert _extract_function_blocks("") == []


class TestSplitDocFunctionBlocks:
    def test_splits_by_swufn(self):
        from report_gen.requirements import _split_doc_function_blocks

        text = (
            "SwUFn_0101: Motor_Init\n"
            "Called Function: Helper_A\n"
            "SwUFn_0102: Motor_Run\n"
            "Called Function: Helper_B\n"
        )
        blocks = _split_doc_function_blocks(text)
        assert len(blocks) == 2
        assert blocks[0]["id"] == "SwUFn_0101"
        assert "Helper_A" in blocks[0]["lines"][0]

    def test_empty(self):
        from report_gen.requirements import _split_doc_function_blocks

        assert _split_doc_function_blocks("") == []


class TestCollectSectionLines:
    def test_collects_until_next_header(self):
        from report_gen.requirements import _collect_section_lines

        lines = [
            "Called Function FuncA",
            "FuncB",
            "Calling Function FuncC",
        ]
        result = _collect_section_lines(lines, "Called Function")
        assert "FuncA" in result
        assert "FuncB" in result
        assert len(result) == 2

    def test_empty_when_no_header(self):
        from report_gen.requirements import _collect_section_lines

        result = _collect_section_lines(["line1", "line2"], "Missing")
        assert result == []


class TestExtractStateTokens:
    def test_finds_st_tokens(self):
        from report_gen.requirements import _extract_state_tokens

        lines = ["transition to ST_IDLE", "if ST_RUNNING then ST_ERROR"]
        result = _extract_state_tokens(lines)
        assert "ST_IDLE" in result
        assert "ST_RUNNING" in result
        assert "ST_ERROR" in result

    def test_deduplicates(self):
        from report_gen.requirements import _extract_state_tokens

        result = _extract_state_tokens(["ST_IDLE", "ST_IDLE again"])
        assert result.count("ST_IDLE") == 1

    def test_empty(self):
        from report_gen.requirements import _extract_state_tokens

        assert _extract_state_tokens([]) == []


class TestExtractRequirementBlocks:
    def test_parses_blocks(self):
        from report_gen.requirements import _extract_requirement_blocks

        text = (
            "ID SwTR_001\n"
            "Name Motor Safety\n"
            "Description The motor shall be safe.\n"
            "Related ID SwTR_002\n"
            "\n"
            "ID SwTR_002\n"
            "Name Sensor Check\n"
            "Description Sensors shall be checked.\n"
        )
        blocks = _extract_requirement_blocks(text)
        assert len(blocks) == 2
        assert blocks[0]["id"] == "SwTR_001"
        assert blocks[0]["name"] == "Motor Safety"
        assert "safe" in blocks[0]["description"]
        # "Related ID SwTR_002" is parsed with split(None, 1)[-1]
        assert "SwTR_002" in blocks[0].get("related_ids", "")

    def test_empty(self):
        from report_gen.requirements import _extract_requirement_blocks

        assert _extract_requirement_blocks("") == []


class TestExtractRequirementsFallback:
    def test_finds_shall_lines(self):
        from report_gen.requirements import _extract_requirements_fallback

        text = "intro\nThe system shall init.\nrandom line\nIt must stop.\n"
        result = _extract_requirements_fallback(text)
        assert len(result) == 2
        assert "shall" in result[0].lower()

    def test_finds_korean_keywords(self):
        from report_gen.requirements import _extract_requirements_fallback

        result = _extract_requirements_fallback("이 기능은 요구사항을 충족해야 한다.")
        assert len(result) >= 1

    def test_empty(self):
        from report_gen.requirements import _extract_requirements_fallback

        assert _extract_requirements_fallback("") == []


class TestExtractDocSection:
    def test_extracts_section(self):
        from report_gen.requirements import _extract_doc_section

        text = (
            "1 Introduction\nSome intro.\n"
            "2 Requirements\nReq content here.\nMore content.\n"
            "3 Summary\nEnd.\n"
        )
        result = _extract_doc_section(text, "Requirements")
        assert "Req content" in result
        assert "End" not in result

    def test_missing_section(self):
        from report_gen.requirements import _extract_doc_section

        assert _extract_doc_section("1 Intro\nText\n", "Missing") == ""

    def test_empty(self):
        from report_gen.requirements import _extract_doc_section

        assert _extract_doc_section("", "Title") == ""


class TestBuildReqMapFromTexts:
    def test_builds_map_with_asil(self):
        from report_gen.requirements import _build_req_map_from_texts

        text = (
            "ID SwTR_001\n"
            "Name Motor Safety\n"
            "Description Some desc.\n"
            "ASIL B\n"
            "Related ID SwTR_002\n"
        )
        result = _build_req_map_from_texts([text])
        assert "swtr_001" in result
        assert result["swtr_001"]["asil"] == "B"


class TestExtractDocFunctionNames:
    def test_finds_prefixed_names(self):
        from report_gen.requirements import _extract_doc_function_names

        result = _extract_doc_function_names(["call g_Motor_Init and s_Sensor_Check"])
        assert "g_Motor_Init" in result
        assert "s_Sensor_Check" in result

    def test_empty(self):
        from report_gen.requirements import _extract_doc_function_names

        assert _extract_doc_function_names([]) == []
        assert _extract_doc_function_names([""]) == []


class TestNormalizeTraceMappingEntry:
    def test_basic_entry(self):
        from report_gen.requirements import _normalize_trace_mapping_entry

        result = _normalize_trace_mapping_entry({
            "requirement_id": "SwTR_001",
            "source_ids": ["file1.c", "file2.c"],
        })
        assert result is not None
        assert result["requirement_id"] == "SwTR_001"
        assert len(result["source_ids"]) == 2

    def test_string_sources(self):
        from report_gen.requirements import _normalize_trace_mapping_entry

        result = _normalize_trace_mapping_entry({
            "requirement_id": "SwTR_001",
            "source_ids": "file1.c, file2.c",
        })
        assert result is not None
        assert len(result["source_ids"]) == 2

    def test_missing_id_returns_none(self):
        from report_gen.requirements import _normalize_trace_mapping_entry

        assert _normalize_trace_mapping_entry({"source_ids": ["x"]}) is None

    def test_no_sources_returns_none(self):
        from report_gen.requirements import _normalize_trace_mapping_entry

        assert _normalize_trace_mapping_entry({"requirement_id": "X"}) is None

    def test_alt_keys(self):
        from report_gen.requirements import _normalize_trace_mapping_entry

        result = _normalize_trace_mapping_entry({
            "req_id": "SwTR_002",
            "source": "file.c",
        })
        assert result is not None
        assert result["requirement_id"] == "SwTR_002"


class TestParseTraceabilityJson:
    def test_list_format(self):
        from report_gen.requirements import _parse_traceability_json
        import json

        data = json.dumps([
            {"requirement_id": "SwTR_001", "source_ids": ["a.c"]},
            {"requirement_id": "SwTR_002", "source_ids": ["b.c"]},
        ])
        result = _parse_traceability_json(data)
        assert len(result) == 2

    def test_mappings_wrapper(self):
        from report_gen.requirements import _parse_traceability_json
        import json

        data = json.dumps({"mappings": [
            {"requirement_id": "SwTR_001", "source_ids": ["a.c"]},
        ]})
        result = _parse_traceability_json(data)
        assert len(result) == 1

    def test_dict_format(self):
        from report_gen.requirements import _parse_traceability_json
        import json

        data = json.dumps({"SwTR_001": ["a.c", "b.c"]})
        result = _parse_traceability_json(data)
        assert len(result) == 1
        assert result[0]["requirement_id"] == "SwTR_001"

    def test_invalid_json(self):
        from report_gen.requirements import _parse_traceability_json

        assert _parse_traceability_json("not json") == []


class TestParseTraceabilityCsv:
    def test_basic_csv(self):
        from report_gen.requirements import _parse_traceability_csv

        csv_text = "requirement_id,source_ids\nSwTR_001,a.c\nSwTR_002,b.c\n"
        result = _parse_traceability_csv(csv_text)
        assert len(result) == 2

    def test_empty(self):
        from report_gen.requirements import _parse_traceability_csv

        assert _parse_traceability_csv("") == []


class TestParseTraceabilityText:
    def test_json_detected(self):
        from report_gen.requirements import _parse_traceability_text
        import json

        data = json.dumps([{"requirement_id": "SwTR_001", "source_ids": ["a.c"]}])
        result = _parse_traceability_text(data)
        assert len(result) == 1

    def test_csv_fallback(self):
        from report_gen.requirements import _parse_traceability_text

        csv_text = "requirement_id,source_ids\nSwTR_001,a.c\n"
        result = _parse_traceability_text(csv_text)
        assert len(result) == 1

    def test_empty(self):
        from report_gen.requirements import _parse_traceability_text

        assert _parse_traceability_text("") == []


class TestExtractRequirementsFromComments:
    def test_finds_req_comment(self):
        from report_gen.requirements import _extract_requirements_from_comments

        text = "// REQ: Motor shall init\n/* Requirement: Sensor check */\n"
        result = _extract_requirements_from_comments(text)
        assert len(result) == 2
        assert "Motor shall init" in result[0]

    def test_empty(self):
        from report_gen.requirements import _extract_requirements_from_comments

        assert _extract_requirements_from_comments("") == []


class TestExtractRequirementsFromDoc:
    def test_structured_doc(self):
        from report_gen.requirements import _extract_requirements_from_doc

        text = (
            "ID SwTR_001\n"
            "Name Motor Safety\n"
            "Description The motor shall be safe.\n"
            "ASIL B\n"
            "Related ID SwTR_002\n"
            "\n"
            "ID SwTR_002\n"
            "Name Sensor Monitoring\n"
            "Description Sensors shall be monitored.\n"
        )
        result = _extract_requirements_from_doc(text)
        assert len(result) == 2
        assert "SwTR_001" in result[0]
        assert "ASIL" in result[0]

    def test_inline_id_format(self):
        from report_gen.requirements import _extract_requirements_from_doc

        text = "SwTR_003: Speed Limit\nDescription Speed must be limited.\n"
        result = _extract_requirements_from_doc(text)
        assert len(result) >= 1
        assert "SwTR_003" in result[0]

    def test_empty(self):
        from report_gen.requirements import _extract_requirements_from_doc

        assert _extract_requirements_from_doc("") == []

    def test_with_stop_keys(self):
        from report_gen.requirements import _extract_requirements_from_doc

        text = (
            "ID SwTR_001\n"
            "Description Motor shall init.\n"
            "Rationale Safety requirement\n"
            "Priority High\n"
        )
        result = _extract_requirements_from_doc(text)
        assert len(result) == 1
        assert "Rationale" not in result[0]


class TestGenerateUdsRequirementsPreview:
    def test_deduplication(self):
        from report_gen.requirements import generate_uds_requirements_preview

        text = (
            "ID SwTR_001\n"
            "Name Motor\n"
            "Description Desc1.\n"
        )
        result = generate_uds_requirements_preview([text, text])
        # Should deduplicate
        items = result.get("items", [])
        assert len(items) == 1

    def test_empty(self):
        from report_gen.requirements import generate_uds_requirements_preview

        result = generate_uds_requirements_preview([])
        assert result.get("items", []) == [] or result.get("count", 0) == 0


class TestReqIdPattern:
    def test_pattern_matches_various_prefixes(self):
        from report_gen.requirements import _REQ_ID_PAT

        assert _REQ_ID_PAT.search("SwTR_001")
        assert _REQ_ID_PAT.search("SwTSR_002")
        assert _REQ_ID_PAT.search("SwNTR_003")
        assert _REQ_ID_PAT.search("SwCNF_004")
        assert _REQ_ID_PAT.search("SwFn_005")
        assert not _REQ_ID_PAT.search("random_text")


class TestExtractFunctionBlocksDetailed:
    """More thorough tests for _extract_function_blocks to cover io/logic states."""

    def test_io_params(self):
        from report_gen.requirements import _extract_function_blocks

        text = (
            "SwUFn_0101: Foo\n"
            "[ Input Parameters ]\n"
            "uint8 x\n"
            "uint16 y\n"
            "[ Output Parameters ]\n"
            "uint8 result\n"
            "[ Logic Diagram ]\n"
            "some logic\n"
        )
        blocks = _extract_function_blocks(text)
        assert len(blocks) >= 1
        # Find the block with IO data
        block = next((b for b in blocks if b.get("inputs")), None)
        assert block is not None
        assert len(block["inputs"]) == 2
        assert block.get("outputs") == ["uint8 result"]
        assert block.get("logic") == "present"

    def test_various_fields(self):
        from report_gen.requirements import _extract_function_blocks

        text = (
            "SwUFn_0201: Bar\n"
            "Prototype void Bar(uint8 x)\n"
            "Description Checks bar.\n"
            "Called Function FuncA\n"
            "Calling Function FuncB\n"
            "선행조건 g_init == TRUE\n"
            "사용 전역변수 g_state\n"
        )
        blocks = _extract_function_blocks(text)
        b = blocks[0]
        assert b.get("prototype") == "void Bar(uint8 x)"
        assert b.get("description") == "Checks bar."
        assert b.get("called") == "Function FuncA"  # "Called" prefix stripped by split
        assert b.get("globals") is not None

    def test_related_id(self):
        from report_gen.requirements import _extract_function_blocks

        text = "SwUFn_0301: Baz\nRelated ID SwTR_001, SwTR_002\n"
        blocks = _extract_function_blocks(text)
        assert any("SwTR_001" in str(b.get("related", "")) for b in blocks)


class TestDocxToText:
    def test_extracts_text(self):
        from report_gen.requirements import _docx_to_text

        class FakePara:
            def __init__(self, t): self.text = t

        class FakeCell:
            def __init__(self, t): self.paragraphs = [FakePara(t)]

        class FakeRow:
            def __init__(self, cells): self.cells = cells

        class FakeTable:
            def __init__(self, rows): self.rows = rows

        class FakeDoc:
            def __init__(self):
                self.paragraphs = [FakePara("Hello"), FakePara("World")]
                self.tables = [FakeTable([FakeRow([FakeCell("Cell1")])])]

        result = _docx_to_text(FakeDoc())
        assert "Hello" in result
        assert "World" in result
        assert "Cell1" in result

    def test_empty_doc(self):
        from report_gen.requirements import _docx_to_text

        class FakeDoc:
            paragraphs = []
            tables = []

        assert _docx_to_text(FakeDoc()) == ""


class TestGenerateUdsRequirementsMapping:
    def test_filters_to_swtr(self):
        from report_gen.requirements import generate_uds_requirements_mapping

        items = [
            {"id": "SwTR_001", "name": "Safety", "related_ids": "SwCom_01, SwFn_01"},
            {"id": "SwCNF_002", "name": "Config"},  # not SwTR/SwTSR
            {"id": "SwTR_003", "name": "Sensor"},  # no related swcom/fn
        ]
        result = generate_uds_requirements_mapping(items)
        assert len(result) == 1
        assert result[0]["requirement_id"] == "SwTR_001"
        assert "SwCom_01" in result[0]["related_swcom"]

    def test_empty(self):
        from report_gen.requirements import generate_uds_requirements_mapping

        assert generate_uds_requirements_mapping([]) == []


class TestGenerateUdsRequirementsPreviewCounts:
    def test_counts_by_prefix(self):
        from report_gen.requirements import generate_uds_requirements_preview

        text = (
            "ID SwTR_001\nName A\nDescription Desc A.\n\n"
            "ID SwTR_002\nName B\nDescription Desc B.\n\n"
            "ID SwTSR_001\nName C\nDescription Desc C.\n"
        )
        result = generate_uds_requirements_preview([text])
        assert len(result["items"]) == 3
        assert result["counts"]["SwTR"] == 2
        assert result["counts"]["SwTSR"] == 1


class TestExtractRequirementsFromDocDetails:
    def test_asil_and_related(self):
        from report_gen.requirements import _extract_requirements_from_doc

        text = (
            "ID SwTR_001\n"
            "Name Motor Safety\n"
            "Description The motor shall be safe.\n"
            "ASIL B\n"
            "Related ID SwTR_002, SwTR_003\n"
        )
        result = _extract_requirements_from_doc(text)
        assert len(result) >= 1
        assert "ASIL:B" in result[0]
        assert "Related:" in result[0]

    def test_multiline_desc(self):
        from report_gen.requirements import _extract_requirements_from_doc

        text = (
            "ID SwTR_001\n"
            "Description First line of desc.\n"
            "Second line of desc.\n"
            "\n"  # blank line stops description
            "ASIL A\n"
        )
        result = _extract_requirements_from_doc(text)
        assert len(result) >= 1
        assert "First line" in result[0]
        assert "Second line" in result[0]

    def test_safety_level_variant(self):
        from report_gen.requirements import _extract_requirements_from_doc

        text = "ID SwTR_010\nSafety Level B\n"
        result = _extract_requirements_from_doc(text)
        assert len(result) >= 1
        assert "B" in result[0]


class TestNormalizeVcastRows:
    def test_groups_by_req_id(self):
        from report_gen.requirements import _normalize_vcast_rows

        rows = [
            {"requirement_id": "SwTR_001", "testcase": "TC_01", "result": "pass"},
            {"requirement_id": "SwTR_001", "testcase": "TC_02", "result": "fail"},
            {"requirement_id": "SwTR_002", "testcase": "TC_03"},
        ]
        result = _normalize_vcast_rows(rows)
        assert len(result["SwTR_001"]) == 2
        assert len(result["SwTR_002"]) == 1

    def test_skips_invalid(self):
        from report_gen.requirements import _normalize_vcast_rows

        result = _normalize_vcast_rows([{}, "string", {"requirement_id": ""}])
        assert result == {}

    def test_empty(self):
        from report_gen.requirements import _normalize_vcast_rows

        assert _normalize_vcast_rows([]) == {}


class TestGenerateUdsTraceabilityMatrix:
    def test_basic_matrix(self):
        from report_gen.requirements import generate_uds_traceability_matrix

        items = [
            {"id": "SwTR_001"},
            {"id": "SwTR_002"},
        ]
        mappings = [
            {"requirement_id": "SwTR_001", "source_ids": ["file.c"]},
        ]
        vcast = [
            {"requirement_id": "SwTR_002", "testcase": "TC_01", "result": "pass"},
        ]
        result = generate_uds_traceability_matrix(items, mappings, vcast)
        assert result["total_requirements"] == 2
        assert result["summary"]["mapped_source_count"] == 1
        assert result["summary"]["mapped_test_count"] == 1
        assert result["has_source_mapping"] is True
        assert result["has_tests"] is True

    def test_empty(self):
        from report_gen.requirements import generate_uds_traceability_matrix

        result = generate_uds_traceability_matrix([])
        assert result["total_requirements"] == 0


class TestGenerateUdsRequirementsFromDocs:
    def test_deduplicates(self):
        from report_gen.requirements import generate_uds_requirements_from_docs

        text = "ID SwTR_001\nDescription Motor safety.\n"
        result = generate_uds_requirements_from_docs([text, text])
        assert result.count("SwTR_001") == 1

    def test_fallback_to_keywords(self):
        from report_gen.requirements import generate_uds_requirements_from_docs

        text = "The system shall initialize safely.\n"
        result = generate_uds_requirements_from_docs([text])
        assert "shall" in result.lower()

    def test_empty(self):
        from report_gen.requirements import generate_uds_requirements_from_docs

        assert generate_uds_requirements_from_docs([]) == ""
