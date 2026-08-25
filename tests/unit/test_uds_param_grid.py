# tests/unit/test_uds_param_grid.py
"""UDS 함수 정보 표 — **정본 6열 파라미터 그리드**(P2-3) 계약.

## 왜 이 파일이 있나

P2-3 이전 우리 산출물은 함수 하나의 입력 전체를 **한 칸**에 몰아넣었다:

    Input Parameters | [IN] (none)
    Used Globals (Global) | Name=[OUT] REG_PTT | Type=… | Range=…

정본(HDPDM01 SUDS)은 같은 정보를 파라미터마다 한 행씩 6열로 적는다:

    [ Input Parameters ]
    No | Name | Type | Value Range | Reset Value | Description
    1  | u8s_InitiComplet_F | U8 | 0x00 ~ 0x01 | 0x00 | System Reset Flag

## 이 파일이 지키는 것

라우팅 규칙은 **정본 실측**으로 정했다(2026-08-25, 교집합 394 함수 / 태그 1,399건).
그 수치가 `function_analyzer._TAG_TO_COLUMNS` 주석에 있고, 아래 테스트가 그 결정을
행동으로 고정한다. ⚠ 특히 `INOUT` 은 **양쪽에 다 적는 것**이 정본이다(적중 329 중
234 가 둘 다) — 한쪽만 적으면 그 234 를 통째로 놓친다.

⚠ `Value Range` 는 정본과 우리가 **다른 주장을 하는 유일한 열**이다. 정본은 설계상의
의미 범위(`0x00 ~ 0x01`), 우리 `range` 는 실측 92.9%(395/425)가 타입 폭 그대로다.
표시 없이 적으면 "설계가 전 범위를 허용한다"는 우리가 세운 적 없는 주장이 되므로
`(타입 폭)` 을 함께 적는다. 그 표시가 사라지면 이 파일이 잡는다.
"""
from __future__ import annotations

import ast

import pytest

from report_gen.function_analyzer import (
    FN_ROW_FULL,
    FN_ROW_GRID,
    FN_ROW_PAIR,
    PARAM_CELL_MAX,
    PARAM_GRID_COLS,
    PARAM_GRID_HEADER,
    _build_function_info_layout,
    resolve_param_grid_entries,
    split_direction_tag,
)

_GIM = {
    "u8s_Flag": {"type": "U8", "range": "0 ~ 255", "init": "0x00", "desc": "System Reset Flag"},
    "u16s_Buf": {"type": "U16", "array": "[60]", "range": "0 ~ 65535", "init": "", "desc": ""},
    "REG_PTT": {"type": "PTTSTR", "range": "", "init": "", "desc": ""},
    "u8s_Semantic": {"type": "U8", "range": "0x00 ~ 0x01", "init": "0x00", "desc": ""},
    "u8s_Table": {"type": "U8", "array": "[256]", "range": "{0x00, 0x1D, 0x3A}",
                  "init": "{0x00, 0x1D, 0x3A}", "desc": ""},
}


def _info(**over):
    base = {
        "id": "SwUFn_0101", "name": "Motor_Init", "prototype": "void Motor_Init(void)",
        "description": "Init motor", "asil": "B", "related": "SwTR_001",
        "inputs": [], "outputs": [], "globals_global": [], "globals_static": [],
    }
    base.update(over)
    return base


def _names(rows):
    """그리드 행 목록 → 이름 열만."""
    return [r[1] for r in rows]


class TestDirectionRouting:
    """정본 실측으로 정한 태그 → 열 배정."""

    @pytest.mark.parametrize(
        ("tag", "in_expected", "out_expected"),
        [
            ("IN", True, False),
            ("OUT", False, True),
            ("INOUT", True, True),
            ("INDIRECT", False, False),
            ("INDIRECT2", False, False),
        ],
    )
    def test_tag_decides_the_column(self, tag, in_expected, out_expected):
        grid_in, grid_out = resolve_param_grid_entries(
            _info(globals_global=[f"[{tag}] u8s_Flag"]), _GIM)
        assert ("u8s_Flag" in _names(grid_in)) is in_expected, f"{tag} → 입력 배정이 틀렸다"
        assert ("u8s_Flag" in _names(grid_out)) is out_expected, f"{tag} → 기대 배정이 틀렸다"

    def test_inout_lands_in_both_not_one(self):
        """⚠ 정본 실측: INOUT 적중 329건 중 **234건이 양쪽 모두**다.
        한쪽만 적는 구현으로 되돌리면 그 234 를 놓친다."""
        grid_in, grid_out = resolve_param_grid_entries(
            _info(globals_global=["[INOUT] u8s_Flag"]), _GIM)
        assert _names(grid_in) == ["u8s_Flag"]
        assert _names(grid_out) == ["u8s_Flag"]

    def test_indirect_is_excluded_from_grids_but_kept_in_used_globals(self):
        """음성 대조군 — 정보를 **버리는 게 아니라 열을 안 배정**하는 것이다.
        정본 적중률이 INDIRECT 1.0% / INDIRECT2 0.4% 라 그리드엔 안 넣지만,
        `Used Globals` 행에는 그대로 남아야 한다."""
        info = _info(globals_global=["[INDIRECT] u16s_Buf"])
        grid_in, grid_out = resolve_param_grid_entries(info, _GIM)
        assert _names(grid_in) == ["N/A"] and _names(grid_out) == ["N/A"]

        layout = _build_function_info_layout(dict(info, _globals_info_map=_GIM), 6)
        used = [c[1] for k, c in layout if k == FN_ROW_PAIR and c[0] == "Used Globals (Global)"]
        assert used and "u16s_Buf" in used[0], "그리드에서 뺐다고 전역 목록에서도 사라졌다"

    def test_signature_params_default_by_source_when_untagged(self):
        """태그가 없으면 원천이 방향을 정한다(`inputs` → 입력, `outputs` → 기대)."""
        grid_in, grid_out = resolve_param_grid_entries(
            _info(inputs=["u8s_Flag"], outputs=["u16s_Buf"]), _GIM)
        assert _names(grid_in) == ["u8s_Flag"]
        assert _names(grid_out) == ["u16s_Buf"]


class TestPlaceholders:
    @pytest.mark.parametrize("raw", ["[IN] (none)", "[IN] N/A", "[IN] -", "[IN] void", "[IN] "])
    def test_placeholder_is_not_a_parameter(self, raw):
        """⚠ `(none)` 은 "파라미터 없음"의 **정확한 기술**이지 이름이 아니다.
        행으로 만들면 존재하지 않는 파라미터를 시험 대상으로 올린다."""
        grid_in, _ = resolve_param_grid_entries(_info(inputs=[raw]), _GIM)
        assert grid_in == [["1", "N/A", "N/A", "N/A", "N/A", "N/A"]]

    def test_no_parameters_gets_the_reference_na_row(self):
        """정본도 파라미터가 없으면 `1 | N/A × 5` 한 줄을 적는다 — 빈 그리드가 아니다."""
        grid_in, grid_out = resolve_param_grid_entries(_info(), _GIM)
        assert grid_in == grid_out == [["1"] + ["N/A"] * (PARAM_GRID_COLS - 1)]

    def test_duplicates_collapse_and_numbering_stays_sequential(self):
        grid_in, _ = resolve_param_grid_entries(
            _info(inputs=["[IN] u8s_Flag", "[IN] u8s_Flag"],
                  globals_global=["[IN] u16s_Buf"]), _GIM)
        assert [r[0] for r in grid_in] == ["1", "2"], "No 열이 어긋났다"
        assert _names(grid_in) == ["u8s_Flag", "u16s_Buf"]


class TestColumns:
    def test_array_dimension_shows_up_in_the_type_column(self):
        """정본은 배열을 `U16 Array` 로 적는다."""
        grid_in, _ = resolve_param_grid_entries(_info(inputs=["[IN] u16s_Buf"]), _GIM)
        assert grid_in[0][2] == "U16 Array"

    def test_type_width_range_is_labelled_as_such(self):
        """⚠ 출처 표시가 사라지면 타입 폭이 설계 범위로 위장한다."""
        grid_in, _ = resolve_param_grid_entries(_info(inputs=["[IN] u8s_Flag"]), _GIM)
        assert grid_in[0][3] == "0 ~ 255 (타입 폭)"

    def test_semantic_range_is_left_alone(self):
        """음성 대조군 — 타입 폭이 **아닌** 범위엔 표시를 붙이지 않는다."""
        grid_in, _ = resolve_param_grid_entries(_info(inputs=["[IN] u8s_Semantic"]), _GIM)
        assert grid_in[0][3] == "0x00 ~ 0x01"

    def test_initializer_block_is_not_a_value_range(self):
        """`{0x00, 0x1D, …}` 는 범위가 아니라 초기값이다 — Reset Value 로 간다."""
        grid_in, _ = resolve_param_grid_entries(_info(inputs=["[IN] u8s_Table"]), _GIM)
        assert grid_in[0][3] == "N/A", "초기화 블록이 Value Range 로 샜다"
        assert grid_in[0][4].startswith("{0x00"), "초기값이 Reset Value 에 없다"

    @pytest.mark.parametrize(
        ("raw", "why"),
        [
            ("( (  U8 )( 0x00U ) )", "캐스트식 — 실제 산출물에 18칸 나갔던 형태"),
            ("0x75", "단일 초기값"),
            ("LD_DIAG_IDLE", "enum 초기값"),
            ("}", "파서 조각"),
        ],
    )
    def test_non_range_values_never_reach_the_value_range_column(self, raw, why):
        """⚠ `range` 필드엔 범위를 못 구했을 때 **초기값이 대신** 들어온다
        (`uds_generator.py` 의 `if not resolved and init:` 폴백). 그걸 그대로 적으면
        Value Range 가 초기값을 범위라고 주장한다. 정본은 그 칸에 범위(92.9%)·
        허용값 열거(1.3%)·N/A(5.6%)만 쓰고 캐스트식은 **한 번도 안 쓴다**."""
        gim = {"x": {"type": "l_u8", "range": raw, "init": raw, "desc": ""}}
        grid_in, _ = resolve_param_grid_entries(_info(inputs=["[IN] x"]), gim)
        assert grid_in[0][3] == "N/A", f"{why}: {raw!r} 가 Value Range 로 샜다"
        assert grid_in[0][4] != "N/A", "정보를 버린 게 아니라 Reset Value 로 옮긴 것이어야 한다"

    def test_allowed_value_enumeration_is_kept(self):
        """음성 대조군 — 정본의 소수 표기(`0x0000, 0x08DC, 0x09A6`)까지 버리면 안 된다."""
        gim = {"x": {"type": "U16", "range": "0x0000, 0x08DC, 0x09A6", "init": "", "desc": ""}}
        grid_in, _ = resolve_param_grid_entries(_info(inputs=["[IN] x"]), gim)
        assert grid_in[0][3] == "0x0000, 0x08DC, 0x09A6"

    def test_reset_value_and_description_come_through(self):
        grid_in, _ = resolve_param_grid_entries(_info(inputs=["[IN] u8s_Flag"]), _GIM)
        assert grid_in[0][4] == "0x00"
        assert grid_in[0][5] == "System Reset Flag"

    def test_member_path_looks_up_the_base_symbol(self):
        """`REG_PTT.Bits.PTT3` 의 타입은 `REG_PTT` 에 달려 있다."""
        grid_in, _ = resolve_param_grid_entries(
            _info(inputs=["[IN] REG_PTT.Bits.PTT3"]), _GIM)
        assert grid_in[0][1] == "REG_PTT.Bits.PTT3"
        assert grid_in[0][2] == "PTTSTR"

    def test_unknown_symbol_degrades_to_na_not_to_a_guess(self):
        """근거가 없으면 `N/A` 다 — 타입을 지어내지 않는다."""
        grid_in, _ = resolve_param_grid_entries(_info(inputs=["[IN] 알수없는이름"]), {})
        assert grid_in[0] == ["1", "알수없는이름", "N/A", "N/A", "N/A", "N/A"]


class TestTruncationIsObservable:
    def test_long_cell_says_it_was_cut_and_how_long_it_was(self):
        """⚠ 이 저장소가 반복해 고쳐 온 것이 **조용한 절단**이다.
        원래 길이가 남지 않으면 소비처가 잘린 값을 온전한 값으로 읽는다."""
        long_init = "{" + ", ".join(["0x00"] * 400) + "}"
        gim = {"u8s_Big": {"type": "U8", "range": "", "init": long_init, "desc": ""}}
        grid_in, _ = resolve_param_grid_entries(_info(inputs=["[IN] u8s_Big"]), gim)
        cell = grid_in[0][4]
        assert len(cell) < len(long_init)
        assert "잘림" in cell, "절단이 침묵했다"
        assert str(len(long_init)) in cell, "원래 길이를 안 남겼다"

    def test_short_cell_is_untouched(self):
        """음성 대조군 — 상한 이하면 손대지 않는다."""
        exact = "x" * PARAM_CELL_MAX
        gim = {"u8s_Fit": {"type": "U8", "range": "", "init": exact, "desc": ""}}
        grid_in, _ = resolve_param_grid_entries(_info(inputs=["[IN] u8s_Fit"]), gim)
        assert grid_in[0][4] == exact


class TestSplitDirectionTag:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("[INOUT] REG_PTT.Bits.PTT3", ("INOUT", "REG_PTT.Bits.PTT3")),
            ("[in] x", ("IN", "x")),
            ("[INDIRECT2] y", ("INDIRECT2", "y")),
            ("no tag here", ("", "no tag here")),
            ("", ("", "")),
        ],
    )
    def test_tag_split(self, raw, expected):
        assert split_direction_tag(raw) == expected

    def test_longer_tag_wins_over_its_prefix(self):
        """⚠ 이 시리즈에서 substring 판정이 4회 데이터를 뒤집었다
        (`"IN" in "[INOUT]"` · `READY` 의 `READ` · `[INDIRECT2]` 등).

        여기서 안전을 주는 건 **대안 순서가 아니라 닫는 `\\]` 앵커**다. 순서만 바꾼
        뮤턴트(`IN|OUT|INOUT|…`)는 입력 200개 대조 결과 차이 0 인 **등가 뮤턴트**라
        생존한다 — 테스트 공백이 아니다(확인함). 실제로 깨지는 건 앵커가 사라져
        `IN` 이 `INOUT` 의 앞머리로 매치될 때이고, 그건 이 단언이 잡는다.
        """
        assert split_direction_tag("[INOUT] a") == ("INOUT", "a")
        assert split_direction_tag("[INDIRECT2] a") == ("INDIRECT2", "a")


class TestLayout:
    def test_parameters_become_section_header_plus_grid(self):
        layout = _build_function_info_layout(
            dict(_info(inputs=["[IN] u8s_Flag"]), _globals_info_map=_GIM), 6)
        kinds = [k for k, _ in layout]
        texts = [c[0] for _, c in layout]
        i = texts.index("[ Input Parameters ]")
        assert kinds[i] == FN_ROW_FULL
        assert kinds[i + 1] == FN_ROW_GRID and layout[i + 1][1] == list(PARAM_GRID_HEADER)
        assert kinds[i + 2] == FN_ROW_GRID and layout[i + 2][1][1] == "u8s_Flag"

    def test_narrow_table_keeps_the_old_packed_layout(self):
        """6열 미만은 그리드가 물리적으로 안 들어간다 — P2-3 이전 그대로여야 한다."""
        layout = _build_function_info_layout(_info(), 4)
        assert {k for k, _ in layout} == {FN_ROW_PAIR}
        assert all(len(c) == 4 for _, c in layout)

    def test_precomputed_grids_are_preferred_over_the_fallback(self):
        """호출자가 넣어 준 그리드가 있으면 그걸 쓴다 — 전역이 납작해진 뒤엔
        폴백이 아무것도 못 찾기 때문이다."""
        info = dict(_info(), _param_grid_inputs=[["1", "미리계산", "U8", "N/A", "N/A", "N/A"]],
                    _param_grid_outputs=[["1", "N/A", "N/A", "N/A", "N/A", "N/A"]])
        layout = _build_function_info_layout(info, 6)
        assert any(c[1] == "미리계산" for k, c in layout if k == FN_ROW_GRID)

    def test_reference_label_order_is_preserved(self):
        """정본 416 블록 중 405 가 이 순서다."""
        layout = _build_function_info_layout(dict(_info(), _globals_info_map=_GIM), 6)
        labels = [c[0] for k, c in layout if k in (FN_ROW_PAIR, FN_ROW_FULL)]
        expected = ["ID", "Name", "Prototype", "Description", "ASIL", "Related ID",
                    "[ Input Parameters ]", "[ Output Parameters ]", "선행조건",
                    "Used Globals (Global)", "Used Globals (Static)",
                    "Called Function", "Calling Function", "Logic Diagram"]
        assert labels == expected


class TestCallSitesStayInSync:
    """⚠ 이 표를 만드는 호출부가 **둘**이다(템플릿 / 무템플릿). 이 저장소가 반복해
    겪은 사고가 "복제본 둘 중 하나만 고침" 이라, 구조로 못박는다."""

    def _calls(self, fn_name):
        from report_gen import docx_builder
        from tests.unit._source_probe import source_of

        tree = ast.parse(source_of(docx_builder))
        found = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Name) and f.id == fn_name:
                found.append(node)
        return found

    def test_every_merge_call_in_the_builder_passes_a_layout(self):
        """`_merge_function_info_table(t, cols)` 로 부르면 그리드가 라벨/값으로 접힌다."""
        calls = self._calls("_merge_function_info_table")
        assert len(calls) >= 3, f"호출부를 {len(calls)}개만 찾았다 — 앵커가 깨졌다"
        bare = [c for c in calls if len(c.args) < 3 and not c.keywords]
        assert bare == [], f"layout 없이 부르는 곳이 {len(bare)}군데 남았다"

    def test_both_builders_size_the_table_to_the_layout(self):
        """⚠ 템플릿 경로는 예전에 템플릿이 준 행 수로 **고정**이라, 늘어난 파라미터가
        조용히 잘렸다. 무템플릿 경로는 예전부터 `max` 였다 — 같은 표를 두 경로가
        다르게 자르고 있었다."""
        from report_gen import docx_builder
        from tests.unit._source_probe import source_of

        src = source_of(docx_builder)
        assert src.count("max(len(data_rows), rows)") == 1, "템플릿 경로의 행 수 확장이 사라졌다"
        assert src.count("max(len(_data_rows), rows)") == 1, "무템플릿 경로의 행 수 확장이 사라졌다"


docx = pytest.importorskip("docx", reason="python-docx 없음")


def _write_table(doc, layout, cols=6):
    """레이아웃을 실제 표로 써서 문서에 넣는다 — 생성 경로와 같은 순서."""
    from report_gen.docx_builder import (
        _add_blank_table,
        _fill_function_info_table,
        _merge_function_info_table,
    )

    t = _add_blank_table(doc, len(layout), cols, None, None, None)
    _merge_function_info_table(t, cols, layout)
    _fill_function_info_table(t, layout)
    return t


def _sample_layout():
    return _build_function_info_layout(
        dict(_info(inputs=["[IN] u8s_Flag"], globals_global=["[OUT] u16s_Buf"]),
             _globals_info_map=_GIM),
        6,
    )


class TestRoundTrip:
    """⚠ P2-3 착수 조건(R3)이 "6열로 바꾸면 하류 파서가 함께 움직여야 한다" 였다.
    조사 결과 `_extract_function_info_from_docx` 는 **두 레이아웃을 이미 지원**한다 —
    조사만으로 끝내지 않고 실제로 써서 되읽어 확인한다."""

    def _extract(self):
        from report_gen.requirements import _extract_function_info_from_docx

        doc = docx.Document()
        layout = [(FN_ROW_FULL, ["[ Function Information ]"])] + _sample_layout()
        _write_table(doc, layout)
        return _extract_function_info_from_docx(doc)

    def test_parameters_survive_the_round_trip(self):
        info = self._extract()
        assert "SwUFn_0101" in info, f"함수 블록 자체를 못 읽었다: {list(info)}"
        block = info["SwUFn_0101"]
        assert any("u8s_Flag" in x for x in block.get("inputs") or []), block.get("inputs")
        assert any("u16s_Buf" in x for x in block.get("outputs") or []), block.get("outputs")

    def test_grid_header_row_is_not_read_as_a_parameter(self):
        """`No|Name|Type|…` 헤더가 파라미터로 새면 함수마다 유령 하나가 붙는다."""
        block = self._extract()["SwUFn_0101"]
        joined = " ".join((block.get("inputs") or []) + (block.get("outputs") or []))
        assert "Value Range" not in joined and "Reset Value" not in joined, joined

    def test_other_fields_still_read_back(self):
        """음성 대조군 — 그리드를 넣느라 나머지 행이 밀리지 않았는지."""
        block = self._extract()["SwUFn_0101"]
        assert block.get("name") == "Motor_Init"
        assert str(block.get("asil") or "").upper() == "B"


class TestPostPassDoesNotFoldTheGrid:
    """⚠ `_normalize_function_info_tables` 는 완성된 문서를 훑어 표를 **다시 병합**한다.
    행 종류를 모른 채 균일 병합하면 방금 쓴 파라미터 그리드가 라벨/값 두 칸으로 접혀
    통째로 사라진다 — 생성 마지막 단계라 아무 경고 없이 그렇게 된다."""

    def test_grid_rows_survive_normalisation(self):
        from report_gen.docx_builder import _normalize_function_info_tables

        doc = docx.Document()
        layout = [(FN_ROW_FULL, ["[ Function Information ]"])] + _sample_layout()
        t = _write_table(doc, layout)
        grid_idx = [i for i, (k, _) in enumerate(layout) if k == FN_ROW_GRID]
        assert grid_idx, "그리드 행이 아예 없다 — 표본이 잘못됐다"

        before = [[c.text for c in t.rows[i].cells] for i in grid_idx]
        _normalize_function_info_tables(doc)
        after = [[c.text for c in t.rows[i].cells] for i in grid_idx]
        assert after == before, "정규화 후처리가 그리드를 접었다"
        for i in grid_idx:
            assert len({id(c._tc) for c in t.rows[i].cells}) == PARAM_GRID_COLS

    def test_pair_rows_are_still_normalised(self):
        """음성 대조군 — 그리드를 지키느라 정규화 자체를 죽이면 안 된다.

        ⚠ 이 대조군이 실제로 잡았다: 처음엔 행 종류를 **셀 개수**로 판정했는데, 아직
        병합되지 않은 라벨/값 표도 6칸이라 전부 그리드로 오인돼 정규화가 통째로
        죽었다. 판정을 내용 기반으로 바꾼 근거가 이 테스트다.

        (행0 텍스트가 6번 이어붙는 것은 P2-3 **이전부터**인 별개 현상이다 — 셀마다
        쓴 뒤 병합하기 때문. 대조군으로 옛 로직을 재현해 확인했다. 우리가 만든 표는
        행0 이 이미 병합돼 있어 해당 없음.)
        """
        from report_gen.docx_builder import _normalize_function_info_tables

        doc = docx.Document()
        t = doc.add_table(rows=3, cols=6)
        t.rows[0].cells[0].text = "Function Information"
        _normalize_function_info_tables(doc)
        assert len({id(c._tc) for c in t.rows[0].cells}) == 1, "행0 전체폭 병합이 안 걸렸다"
        assert "[ Function Information ]" in t.rows[0].cells[0].text
        assert len({id(c._tc) for c in t.rows[1].cells}) == 2, "라벨/값 병합이 안 걸렸다"
