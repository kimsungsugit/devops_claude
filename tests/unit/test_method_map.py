"""test_method_map 단위 테스트 (DC-4) — C# TestMethodMap.cs 시맨틱 고정."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from backend.services.test_method_map import map_test_method_note  # noqa: E402


class TestMapTestMethodNote:
    @pytest.mark.parametrize("note,method,gen", [
        ("REQ/BA", "REQ", "AOR/ABV"),
        ("REQ/FI", "FI", "AOR/ABV"),
        ("REQ/EC", "REQ", "AOR/AEC"),
        ("REQ/RA", "REQ", "AOR/ABV"),  # 오타 별칭 = REQ/BA
        ("REQ/F", "FI", "AOR/ABV"),    # 오타 별칭 = REQ/FI
    ])
    def test_mapped_notes(self, note, method, gen):
        m, g, mapped = map_test_method_note(note)
        assert (m, g, mapped) == (method, gen, True)

    def test_case_insensitive_and_trim(self):
        assert map_test_method_note("  req/ba  ") == ("REQ", "AOR/ABV", True)

    def test_unmapped_returns_original_trimmed(self):
        # 이미 정규값 → 매핑 미존재 → mapped=False, 원본 유지(회귀 0 보장)
        assert map_test_method_note("REQ") == ("REQ", "", False)
        assert map_test_method_note("ABV") == ("ABV", "", False)
        assert map_test_method_note("  Custom Note ") == ("Custom Note", "", False)

    def test_empty_and_none(self):
        assert map_test_method_note("") == ("", "", False)
        assert map_test_method_note(None) == ("", "", False)


class TestParserDefensiveNormalization:
    """swuts_excel_parser 통합 — 미정규 노트만 교정, 정규값/명시 gen_method 보존."""

    def test_raw_note_normalized_when_gen_empty(self):
        from backend.services.swuts_excel_parser import map_test_method_note as f
        m, g, mapped = f("REQ/BA")
        assert mapped and m == "REQ" and g == "AOR/ABV"

    def test_already_normalized_unchanged(self):
        from backend.services.swuts_excel_parser import map_test_method_note as f
        m, g, mapped = f("REQ")
        assert not mapped and m == "REQ" and g == ""
