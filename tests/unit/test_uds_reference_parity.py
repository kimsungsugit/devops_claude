"""정본 대조 모듈 가드 — **측정이 거짓말하지 않는지**가 이 파일의 본체다.

대조 지표는 그 자체가 판단 근거가 되므로, 틀린 지표는 틀린 코드보다 오래 산다.
이 파일이 막는 세 가지:

1. **표기차를 불일치로 세지 않기** — `0x00 ~ 0xFF` 와 `0 ~ 255` 는 같은 범위다.
   문자열만 비교하면 range 재현율이 **0.0%** 로 나오는데 실제는 27.8% 다.
   SUTS R26 이 `SYMBOL(N)` 에서 정확히 같은 덫에 걸려 재현율을 낮게 보고했다.
2. **분모 0 을 0.0% 로 적지 않기** — 재본 적 없는 축이 최악값으로 둔갑한다.
   이 저장소가 `artifact_match_pct` 에서 이미 고친 형태다.
3. **모르는 것을 "근거 있음" 으로 세지 않기** — `known_symbols` 를 안 주면 과다를
   "지어냈나" 로 판정하지 **않는다**(판정 자체를 생략하고 그렇다고 적는다).

⚠ 미달을 2분류로 보면 손댈 대상이 부풀려진다(SUTS R19). `방향 오배치` 는 정본이 같은
이름을 반대 열에도 적은 것이라 재현 대상이 아니다.
"""

from __future__ import annotations

import zipfile

import pytest

from report_gen import uds_reference_parity as parity
from tests.unit._source_probe import source_of

_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _cell(text: str) -> str:
    lines = "".join(f"<w:p><w:r><w:t>{ln}</w:t></w:r></w:p>" for ln in str(text).split("\n"))
    return f"<w:tc>{lines}</w:tc>"


def _row(cells) -> str:
    return "<w:tr>" + "".join(_cell(c) for c in cells) + "</w:tr>"


def _make_docx(path, tables) -> str:
    """`[ Function Information ]` 표만 든 최소 docx.

    ⚠ 라이터(`docx_builder`)를 쓰지 않는다 — 측정기를 라이터로 검증하면 둘이 같이
    틀렸을 때 통과한다. XML 을 직접 만들어 **독립 경로**로 대조한다.
    """
    body = "".join(f"<w:tbl>{''.join(_row(r) for r in t)}</w:tbl>" for t in tables)
    doc = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:document {_W}><w:body>{body}</w:body></w:document>'
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="word/document.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"/>'
            "</Relationships>")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", doc)
    return str(path)


_HEADER = ["No", "Name", "Type", "Value Range", "Reset Value", "Description"]


def _block(fn, inputs=(), outputs=(), input_label="Input Parameters"):
    rows = [["[ Function Information ]"] * 6, ["Name", fn, "", "", "", ""]]
    for label, items in ((input_label, inputs), ("Output Parameters", outputs)):
        rows.append([f"[ {label} ]"] * 6)
        rows.append(list(_HEADER))
        for i, item in enumerate(items, start=1):
            rows.append([str(i)] + list(item))
    rows.append(["선행조건", "N/A", "", "", "", ""])
    return rows


class TestParseRange:
    @pytest.mark.parametrize("text,expected", [
        ("0x00 ~ 0xFF", (0, 255)),
        ("0 ~ 255", (0, 255)),
        ("0x0000 ~ 0xFFFF", (0, 65535)),
        ("-32768 ~ 32767", (-32768, 32767)),
        ("0x00~ 0x03", (0, 3)),
        ("255 ~ 0", (0, 255)),                       # 뒤집힌 표기도 같은 범위다
        ("0 ~ 255 (타입 폭)", (0, 255)),             # ⚠ 꼬리 주석을 떼고 읽어야 한다
        ("0x00U ~ 0xFFU", (0, 255)),
    ])
    def test_reads_a_range(self, text, expected):
        assert parity.parse_range(text) == expected

    @pytest.mark.parametrize("text", ["N/A", "", "( ( U8 )( 0x00U ) )", "0x00", "enum"])
    def test_rejects_a_non_range(self, text):
        assert parity.parse_range(text) is None


class TestValueVerdict:
    def test_hex_and_decimal_are_the_same_range(self):
        """⚠ 이걸 놓치면 range 재현율이 27.8% 대신 0.0% 로 보고된다."""
        same, reason = parity.value_verdict("range", "0x00 ~ 0xFF", "0 ~ 255 (타입 폭)")
        assert same and reason == "표기차(16진↔10진)"

    def test_a_narrower_design_range_is_a_real_mismatch(self):
        """정본 `0x00 ~ 0x03` 은 설계 범위다 — 타입 폭으로 덮으면 틀린 주장이다."""
        same, _ = parity.value_verdict("range", "0x00 ~ 0x03", "0 ~ 255 (타입 폭)")
        assert same is False

    def test_array_notation_on_type_is_notation_only(self):
        same, reason = parity.value_verdict("type", "U8", "U8 Array")
        assert same and reason == "표기차(배열/대소문자)"

    def test_different_type_is_a_mismatch(self):
        assert parity.value_verdict("type", "U16", "S16")[0] is False

    def test_exact_match_is_reported_as_exact(self):
        assert parity.value_verdict("desc", "Motor state", "Motor state") == (True, "정확일치")

    def test_punctuation_only_difference_on_free_text(self):
        same, reason = parity.value_verdict("desc", "Motor state.", "Motor state")
        assert same and reason.startswith("표기차")


class TestPercentIsUnmeasuredNotZero:
    def test_zero_denominator_is_none(self):
        """0.0 으로 적으면 재본 적 없는 축이 최악값으로 둔갑한다."""
        assert parity._pct(0, 0) is None

    def test_real_denominator_is_a_number(self):
        assert parity._pct(1, 4) == 25.0

    def test_unmeasured_helper_carries_a_reason(self):
        out = parity.unmeasured("정본 없음")
        assert out["measured"] is False and out["reason"] == "정본 없음"


class TestSymbolNormalisation:
    @pytest.mark.parametrize("raw,expected", [
        ("REG_PTT.Bits.PTT3", "reg_ptt"),
        ("u8g_State", "u8g_state"),
        ("buf[3]", "buf"),
        ("p->field", "p"),
    ])
    def test_base_symbol_drops_member_paths(self, raw, expected):
        assert parity.base_symbol(raw) == expected

    def test_skeleton_also_drops_annotations(self):
        assert parity.skeleton("u16s_AdcBuffer (size: 8)") == parity.skeleton("u16s_AdcBuffer")


class TestParseFunctionInfo:
    def test_reads_the_six_column_grid(self, tmp_path):
        path = _make_docx(tmp_path / "a.docx", [
            _block("Foo", inputs=[["u8g_A", "U8", "0x00 ~ 0x01", "0x00", "Flag"]]),
        ])
        blocks = parity.parse_function_info(path)
        assert set(blocks) == {"foo"}
        assert blocks["foo"]["params"]["in"]["u8g_a"] == (
            "u8g_A", "U8", "0x00 ~ 0x01", "0x00", "Flag")

    def test_tolerates_the_reference_typo(self, tmp_path):
        """정본에 `Paramters` 오타가 19건 있다 — 놓치면 그 함수의 입력이 통째로 0 이다."""
        path = _make_docx(tmp_path / "b.docx", [
            _block("Foo", inputs=[["u8g_A", "U8", "N/A", "N/A", ""]],
                   input_label="Input Paramters"),
        ])
        assert "u8g_a" in parity.parse_function_info(path)["foo"]["params"]["in"]

    def test_placeholder_rows_are_not_parameters(self, tmp_path):
        path = _make_docx(tmp_path / "c.docx", [
            _block("Foo", inputs=[["N/A", "N/A", "N/A", "N/A", "N/A"]]),
        ])
        assert parity.parse_function_info(path)["foo"]["params"]["in"] == {}

    def test_section_end_label_stops_parameter_collection(self, tmp_path):
        """`선행조건` 뒤의 행을 파라미터로 세면 없는 입력을 지어낸다."""
        rows = _block("Foo", inputs=[["u8g_A", "U8", "N/A", "N/A", ""]])
        rows.append(["Used Globals (Global)", "x", "y", "z", "w", "v"])
        path = _make_docx(tmp_path / "d.docx", [rows])
        assert list(parity.parse_function_info(path)["foo"]["params"]["in"]) == ["u8g_a"]

    def test_a_table_without_the_marker_is_ignored(self, tmp_path):
        path = _make_docx(tmp_path / "e.docx", [[["Something else"] * 6]])
        assert parity.parse_function_info(path) == {}

    def test_multiline_cells_are_not_mashed_together(self, tmp_path):
        """⚠ `itertext()` 만 쓰면 여러 줄이 한 덩어리가 된다 — P2-3 이 이걸로 0.0% 를 냈다."""
        path = _make_docx(tmp_path / "f.docx", [
            _block("Foo", inputs=[["u8g_A", "U8", "N/A", "N/A", "line1\nline2"]]),
        ])
        desc = parity.parse_function_info(path)["foo"]["params"]["in"]["u8g_a"][4]
        assert desc == "line1\nline2"


class TestCompare:
    def _pair(self, tmp_path, ref_spec, our_spec):
        ref = _make_docx(tmp_path / "ref.docx", ref_spec)
        ours = _make_docx(tmp_path / "ours.docx", our_spec)
        return ref, ours

    def test_identical_documents_reproduce_fully(self, tmp_path):
        """음성 대조군 — 완전 일치가 100% 가 아니면 지표 자체가 못 쓴다."""
        spec = [_block("Foo", inputs=[["u8g_A", "U8", "0x00 ~ 0x01", "0x00", "Flag"]],
                       outputs=[["u8g_B", "U8", "0x00 ~ 0x01", "0x00", "Out"]])]
        ref, ours = self._pair(tmp_path, spec, spec)
        result = parity.compare(ref, ours)
        for axis in ("in", "out"):
            assert result["axes"][axis]["name_axis"]["recall_pct"] == 100.0
            for col in parity.VALUE_COLUMNS:
                assert result["axes"][axis]["value_axis"][col]["reproduced_pct"] == 100.0

    def test_join_is_by_function_name(self, tmp_path):
        """⚠ ID 로 조인하면 조용히 엉뚱한 쌍을 맞춘다(STS 실측 43쌍 중 35쌍 불일치)."""
        ref = _make_docx(tmp_path / "r.docx",
                         [_block("Foo", inputs=[["u8g_A", "U8", "N/A", "N/A", ""]])])
        ours = _make_docx(tmp_path / "o.docx",
                          [_block("Bar", inputs=[["u8g_A", "U8", "N/A", "N/A", ""]])])
        result = parity.compare(ref, ours)
        assert result["join_key"] == "function_name"
        assert result["joined_functions"] == 0

    def test_reference_na_is_excluded_from_the_value_denominator(self, tmp_path):
        """정본이 `N/A` 라 적은 칸을 재현 대상으로 세면, 우리 근거를 지워야 점수가 오른다."""
        ref = _make_docx(tmp_path / "r.docx",
                         [_block("Foo", inputs=[["u8g_A", "U8", "N/A", "N/A", ""]])])
        ours = _make_docx(tmp_path / "o.docx",
                          [_block("Foo", inputs=[["u8g_A", "U8", "0 ~ 255", "0x00", "Flag"]])])
        rng = parity.compare(ref, ours)["axes"]["in"]["value_axis"]["range"]
        assert rng["denominator"] == 0 and rng["reference_na_excluded"] == 1
        assert rng["reproduced_pct"] is None

    def test_shortfall_splits_three_ways(self, tmp_path):
        """2분류로 보면 손댈 대상이 부풀려진다 (SUTS R19)."""
        ref = _make_docx(tmp_path / "r.docx", [_block(
            "Foo",
            inputs=[["u8g_Dir", "U8", "N/A", "N/A", ""],       # 우리는 기대 열에 적음
                    ["u16s_Buf", "U16", "N/A", "N/A", ""],     # 우리는 주석 붙은 표기
                    ["u8g_Gone", "U8", "N/A", "N/A", ""]],     # 진짜 없음
        )])
        ours = _make_docx(tmp_path / "o.docx", [_block(
            "Foo",
            inputs=[["u16s_Buf (size: 8)", "U16", "N/A", "N/A", ""]],
            outputs=[["u8g_Dir", "U8", "N/A", "N/A", ""]],
        )])
        kinds = parity.compare(ref, ours)["axes"]["in"]["name_axis"]["shortfall_kinds"]
        assert kinds == {"방향 오배치": 1, "표기차/입도차": 1, "진짜 이름부재": 1}

    def test_excess_without_known_symbols_makes_no_honesty_claim(self, tmp_path):
        """모르는 것을 '근거 있음' 으로 세지 않는다 — 판정을 생략하고 그렇다고 적는다."""
        ref = _make_docx(tmp_path / "r.docx", [_block("Foo")])
        ours = _make_docx(tmp_path / "o.docx",
                          [_block("Foo", inputs=[["u8g_New", "U8", "N/A", "N/A", ""]])])
        kinds = parity.compare(ref, ours)["axes"]["in"]["name_axis"]["excess_kinds"]
        assert kinds == {"소스 대조 안 함": 1}

    def test_excess_is_flagged_when_the_symbol_is_not_in_the_source(self, tmp_path):
        ref = _make_docx(tmp_path / "r.docx", [_block("Foo")])
        ours = _make_docx(tmp_path / "o.docx", [_block(
            "Foo", inputs=[["u8g_Real", "U8", "N/A", "N/A", ""],
                           ["u8g_Made", "U8", "N/A", "N/A", ""]])])
        kinds = parity.compare(ref, ours, known_symbols=["u8g_Real"])["axes"]["in"] \
            ["name_axis"]["excess_kinds"]
        assert kinds["소스에 실재하나 정본이 안 적음"] == 1
        assert kinds["⚠ 소스 근거 미확인"] == 1

    def test_notation_difference_counts_as_reproduced_not_mismatch(self, tmp_path):
        ref = _make_docx(tmp_path / "r.docx",
                         [_block("Foo", inputs=[["u8g_A", "U8", "0x00 ~ 0xFF", "N/A", ""]])])
        ours = _make_docx(tmp_path / "o.docx",
                          [_block("Foo", inputs=[["u8g_A", "U8", "0 ~ 255 (타입 폭)", "N/A", ""]])])
        rng = parity.compare(ref, ours)["axes"]["in"]["value_axis"]["range"]
        assert (rng["reproduced"], rng["notation_only"], rng["value_mismatch"]) == (1, 1, 0)

    def test_our_na_is_a_missing_field_not_a_mismatch(self, tmp_path):
        """'적을 게 없었다' 와 '틀리게 적었다' 는 대응이 다르다."""
        ref = _make_docx(tmp_path / "r.docx",
                         [_block("Foo", inputs=[["u8g_A", "U8", "0x00 ~ 0x01", "N/A", ""]])])
        ours = _make_docx(tmp_path / "o.docx",
                          [_block("Foo", inputs=[["u8g_A", "U8", "N/A", "N/A", ""]])])
        rng = parity.compare(ref, ours)["axes"]["in"]["value_axis"]["range"]
        assert (rng["missing_field"], rng["value_mismatch"]) == (1, 0)


class TestReadOnlyByConstruction:
    """R1 — 대조는 **읽기 전용 별도 경로**다. 정본 값이 산출물로 새면 안 된다."""

    def test_module_never_writes(self):
        src = source_of(parity)
        for forbidden in ("open(", ".write(", "shutil", "os.replace", "Document("):
            assert forbidden not in src, f"대조 모듈이 쓰기 수단을 갖고 있다: {forbidden}"

    def test_writer_does_not_import_the_comparator(self):
        """라이터가 이걸 import 하면 정본 값을 채우는 경로가 열린다."""
        from pathlib import Path

        writer = Path(parity.__file__).with_name("docx_builder.py").read_text(encoding="utf-8")
        assert "uds_reference_parity" not in writer

    def test_samples_are_length_capped(self, tmp_path):
        """표본에 정본 원문이 통째로 실리면 그것 자체가 주입 경로가 된다."""
        long_text = "X" * 500
        ref = _make_docx(tmp_path / "r.docx",
                         [_block("Foo", inputs=[["u8g_A", "U8", "N/A", "N/A", long_text]])])
        ours = _make_docx(tmp_path / "o.docx",
                          [_block("Foo", inputs=[["u8g_A", "U8", "N/A", "N/A", "other"]])])
        samples = parity.compare(ref, ours)["axes"]["in"]["value_axis"]["desc"]["samples"]
        assert samples and all(len(s["ref"]) <= 60 for s in samples)


class TestSurvivedMutantsClosed:
    """뮤테이션 생존 2건이 가리킨 **내 테스트 공백**.

    - 섹션 종료를 `in` 축에서만 확인해, 종료를 무시해도 `out` 축으로 새는 걸 못 봤다.
    - 같은 함수가 여러 표로 쪼개진 경우를 아예 안 만들어, `setdefault` 를 덮어쓰기로
      바꿔도 통과했다(SUTS R25 가 dict 덮어쓰기로 66행을 침묵 소실한 그 형태).
    """

    def test_rows_after_the_section_end_leak_into_neither_axis(self, tmp_path):
        rows = _block("Foo", inputs=[["u8g_A", "U8", "N/A", "N/A", ""]])
        rows.append(["Used Globals (Global)", "u8g_Leak", "U8", "N/A", "N/A", "x"])
        rows.append(["Called Function", "u8g_Leak2", "U8", "N/A", "N/A", "x"])
        path = _make_docx(tmp_path / "leak.docx", [rows])
        params = parity.parse_function_info(path)["foo"]["params"]
        assert list(params["in"]) == ["u8g_a"]
        assert params["out"] == {}, "섹션이 끝난 뒤의 행이 기대 축으로 샜다"

    def test_first_table_wins_when_a_function_spans_two_tables(self, tmp_path):
        """덮어쓰기면 뒤 표가 이기고, 앞 표의 값이 조용히 사라진다."""
        first = _block("Foo", inputs=[["u8g_A", "U8", "0x00 ~ 0x01", "0x00", "first"]])
        second = _block("Foo", inputs=[["u8g_A", "U16", "0 ~ 65535", "0xFF", "second"]])
        path = _make_docx(tmp_path / "split.docx", [first, second])
        row = parity.parse_function_info(path)["foo"]["params"]["in"]["u8g_a"]
        assert row[1] == "U8" and row[4] == "first", "뒤 표가 앞 표를 덮었다"
