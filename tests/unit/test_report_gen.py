"""Unit tests for report_gen pure-logic functions (utils, uds_text, function_analyzer)."""
from __future__ import annotations


class TestExtractIssuesCounts:
    def test_from_issue_counts(self):
        from report_gen.utils import _extract_issue_counts
        summary = {"static": {"cppcheck": {"issue_counts": {"total": 5, "error": 2, "warning": 3}}}}
        result = _extract_issue_counts(summary)
        assert result == {"total": 5, "error": 2, "warning": 3}

    def test_from_issues_list(self):
        from report_gen.utils import _extract_issue_counts
        summary = {"static": {"cppcheck": {"data": {"issues": [1, 2, 3]}}}}
        result = _extract_issue_counts(summary)
        assert result["total"] == 3

    def test_empty(self):
        from report_gen.utils import _extract_issue_counts
        assert _extract_issue_counts({})["total"] == 0


class TestNormalizeSwufnId:
    def test_standard(self):
        from report_gen.utils import _normalize_swufn_id
        assert _normalize_swufn_id("swufn_0042") == "SwUFn_0042"
        assert _normalize_swufn_id("SWUFN_123") == "SwUFn_123"

    def test_passthrough(self):
        from report_gen.utils import _normalize_swufn_id
        assert _normalize_swufn_id("other_id") == "other_id"

    def test_empty(self):
        from report_gen.utils import _normalize_swufn_id
        assert _normalize_swufn_id("") == ""


class TestNormalizeCallField:
    def test_dedup_lines(self):
        from report_gen.utils import _normalize_call_field
        assert _normalize_call_field("foo\nbar\nfoo") == "foo\nbar"

    def test_empty_lines_stripped(self):
        from report_gen.utils import _normalize_call_field
        assert _normalize_call_field("a\n\n\nb") == "a\nb"


class TestDedupeMultilineText:
    def test_basic(self):
        from report_gen.utils import _dedupe_multiline_text
        assert _dedupe_multiline_text("a\nb\na") == "a\nb"

    def test_na_removal(self):
        from report_gen.utils import _dedupe_multiline_text
        assert _dedupe_multiline_text("data\nN/A\nnone", na_to_empty=True) == "data"


class TestNormalizeAsilValue:
    def test_single(self):
        from report_gen.utils import _normalize_asil_value
        assert _normalize_asil_value("ASIL-B") == "B"

    def test_multiple(self):
        from report_gen.utils import _normalize_asil_value
        result = _normalize_asil_value("A, B, QM")
        assert "A" in result and "B" in result and "QM" in result

    def test_plain_letter(self):
        from report_gen.utils import _normalize_asil_value
        assert _normalize_asil_value("D") == "D"

    def test_na_not_graded_as_a(self):
        # N/A류는 ASIL 미부여('') — split이 'N/A'→['N','A']로 쪼개 거짓 'A' 격상하던
        # 안전 결함 방지(ASIL 갭 판정 정확성).
        from report_gen.utils import _normalize_asil_value
        assert _normalize_asil_value("N/A") == ""
        assert _normalize_asil_value("n/a") == ""
        assert _normalize_asil_value("NA") == ""
        assert _normalize_asil_value("TBD") == ""
        assert _normalize_asil_value("미적용") == ""

    def test_paren_decomposition_recognized(self):
        # 'B(C)'(공백 없는 보조등급 표기)가 미상으로 탈락하지 않고 B·C 모두 인식.
        from report_gen.utils import _normalize_asil_value
        r = _normalize_asil_value("B(C)")
        assert "B" in r and "C" in r
        r2 = _normalize_asil_value("ASIL B(C)")
        assert "B" in r2 and "C" in r2


class TestNormalizeRelatedIds:
    def test_dedup(self):
        from report_gen.utils import _normalize_related_ids
        assert _normalize_related_ids("SwTR_001, SwTR_002; SwTR_001") == "SwTR_001, SwTR_002"


class TestNormalizeSwcomLabel:
    def test_normalize(self):
        from report_gen.utils import _normalize_swcom_label
        assert _normalize_swcom_label("Sw Com 1") == "SwCom_01"

    def test_empty(self):
        from report_gen.utils import _normalize_swcom_label
        assert _normalize_swcom_label("") == ""


class TestExtractCallNames:
    def test_basic(self):
        from report_gen.utils import _extract_call_names
        names = _extract_call_names("foo()\nbar(int x)\nvoid")
        assert "foo" in names
        assert "bar" in names
        assert "void" not in names

    def test_skips_keywords(self):
        from report_gen.utils import _extract_call_names
        names = _extract_call_names("if(x)\nreturn(0)")
        assert names == []


class TestTitleCaseLine:
    def test_basic(self):
        from report_gen.uds_text import _title_case_line
        assert _title_case_line("hello world") == "Hello world"

    def test_empty(self):
        from report_gen.uds_text import _title_case_line
        assert _title_case_line("") == ""


class TestSplitSentences:
    def test_basic(self):
        from report_gen.uds_text import _split_sentences
        result = _split_sentences("First. Second! Third?")
        assert len(result) == 3

    def test_empty(self):
        from report_gen.uds_text import _split_sentences
        assert _split_sentences("") == []


class TestTrimSentenceWords:
    def test_short_unchanged(self):
        from report_gen.uds_text import _trim_sentence_words
        assert _trim_sentence_words("hello world", 10) == "hello world"

    def test_truncated(self):
        from report_gen.uds_text import _trim_sentence_words
        result = _trim_sentence_words("a b c d e f", 3)
        assert result == "a b c..."


class TestSplitSignatureParamChunks:
    def test_simple(self):
        from report_gen.function_analyzer import _split_signature_param_chunks
        result = _split_signature_param_chunks("int x, float y, char *z")
        assert result == ["int x", "float y", "char *z"]

    def test_nested_parens(self):
        from report_gen.function_analyzer import _split_signature_param_chunks
        result = _split_signature_param_chunks("void (*cb)(int, int), int x")
        assert len(result) == 2

    def test_empty(self):
        from report_gen.function_analyzer import _split_signature_param_chunks
        assert _split_signature_param_chunks("") == []


class TestExtractParamSymbol:
    def test_basic(self):
        from report_gen.function_analyzer import _extract_param_symbol
        assert _extract_param_symbol("uint8_t value") == "value"

    def test_pointer(self):
        from report_gen.function_analyzer import _extract_param_symbol
        assert _extract_param_symbol("uint8_t *buf") == "buf"

    def test_func_ptr(self):
        from report_gen.function_analyzer import _extract_param_symbol
        assert _extract_param_symbol("void (*callback)(int)") == "callback"

    def test_array(self):
        from report_gen.function_analyzer import _extract_param_symbol
        assert _extract_param_symbol("uint8_t data[8]") == "data"

    def test_empty(self):
        from report_gen.function_analyzer import _extract_param_symbol
        assert _extract_param_symbol("") == ""


def test_put_by_name_preserves_identity_and_records_collisions():
    """동일 이름 다중정의: by_name은 **동일성 보존**(문서 생성의 in-place 갱신 경로), 충돌은 별도 맵.

    회귀 방지:
    - by_name에 dict 복사본을 넣으면 docx_builder의 `target[key] = ...`(참조문서 값 병합)이
      function_details 원본에 반영되지 않아 문서가 조용히 누락된다.
    - 뒤이은 콜그래프 보강 루프가 by_name을 다시 덮어써도 충돌 기록은 유지돼야 한다.
    """
    from report_gen.uds_generator import _put_by_name

    by_name = {}
    coll = {}
    boot = {"name": "eeprom_setbyte", "file": "Generated_Code/EEPROM.c", "asil": "QM"}
    app = {"name": "eeprom_setbyte", "file": "Sources/Eeprom/EEPROM.c", "asil": "B"}

    _put_by_name(by_name, "eeprom_setbyte", boot, coll)
    _put_by_name(by_name, "eeprom_setbyte", app, coll)

    # 동일성 보존 — 마지막 등록 객체 그대로(복사본 아님)
    assert by_name["eeprom_setbyte"] is app
    # 충돌은 별도 맵에 — 두 파일 전부 + 최대 ASIL
    ent = coll["eeprom_setbyte"]
    assert sorted(ent["files"]) == ["Generated_Code/EEPROM.c", "Sources/Eeprom/EEPROM.c"]
    assert ent["asil"] == "B"  # QM보다 높은 등급 유지(안전측)

    # 보강 루프가 다시 덮어써도 충돌 기록은 유지된다
    enriched = dict(app)
    enriched["calling"] = "x"
    _put_by_name(by_name, "eeprom_setbyte", enriched, coll)
    assert by_name["eeprom_setbyte"] is enriched
    assert sorted(coll["eeprom_setbyte"]["files"]) == ["Generated_Code/EEPROM.c", "Sources/Eeprom/EEPROM.c"]
    assert coll["eeprom_setbyte"]["asil"] == "B"

    # 단일 정의 함수는 충돌 맵에 기록되지 않는다
    solo = {"name": "solo_fn", "file": "a.c", "asil": "A"}
    _put_by_name(by_name, "solo_fn", solo, coll)
    assert "solo_fn" not in coll
    assert by_name["solo_fn"] is solo


class TestFunctionBodySnippets:
    """AI 2차 refinement가 읽는 body 맵. detail dict엔 body 계열 키가 없다.

    회귀 방지: 이 맵이 없으면 uds_ai의 pass 2가 조용히 no-op가 된다(생산자 부재로
    실제로 한 번도 실행된 적 없던 경로). detail 안에 넣지 않는 이유는 by_name이
    같은 객체를 참조해 캐시 JSON에 두 번 직렬화되기 때문.
    """

    _SRC = """\
void Ap_Door_Run(void)
{
    if (g_door_state > 0U)
    {
        Ap_Door_Open();
    }
    else
    {
        Ap_Door_Close();
    }
}

void Ap_Door_Open(void)
{
    g_door_state = 1U;
}
"""

    def _sections(self, tmp_path):
        from report_gen.uds_generator import generate_uds_source_sections
        (tmp_path / "Ap_Door.c").write_text(self._SRC, encoding="utf-8")
        return generate_uds_source_sections(str(tmp_path))

    def test_snippets_are_emitted_and_keyed_by_fid(self, tmp_path):
        sections = self._sections(tmp_path)
        snips = sections.get("function_body_snippets")
        assert isinstance(snips, dict) and snips, "body snippet 맵이 비었다"
        # 키는 function_details의 fid와 같은 축이어야 uds_ai가 조회할 수 있다
        assert set(snips) <= set(sections.get("function_details") or {})
        joined = "".join(snips.values())
        assert "g_door_state" in joined

    def test_snippet_is_capped(self, tmp_path):
        from report_gen.uds_generator import _BODY_SNIPPET_MAX
        snips = self._sections(tmp_path).get("function_body_snippets") or {}
        assert all(len(v) <= _BODY_SNIPPET_MAX for v in snips.values())

    def test_snippets_are_not_duplicated_into_detail(self, tmp_path):
        """detail에 실리면 by_name(별칭 포함)으로 중복 직렬화된다 — 계약상 금지."""
        sections = self._sections(tmp_path)
        for detail in (sections.get("function_details") or {}).values():
            assert "body_snippet" not in detail
            assert "body_text" not in detail
