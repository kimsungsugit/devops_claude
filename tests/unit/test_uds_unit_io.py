"""SwUDS `[ Input/Output Parameters ]` 표 → 시험 변수 이름.

정본 SUTS 의 Inpt/ExpR 열은 소스 파싱이 아니라 **SwUDS 의 이 표**에서 온다.
실측(2026-08-14, KJPDS02_PV · 첨자 지운 이름 집합):

                      입력 재현율·과다      기대 재현율·과다
    소스 파싱(옛 판)     84.3% · 617          84.0% · 550
    SwUDS              88.0% · **110**       83.6% · 348
    SwUDS + `return`                        **94.1%** · 358
"""
from __future__ import annotations

import zipfile

import pytest

from generators.suts import collect_unit_functions
from generators.uds_unit_io import clean_param_name, load_uds_unit_io, resolve_unit_io

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(body_xml: str, tmp_path, name: str = "uds.docx") -> str:
    """최소 docx — `word/document.xml` 만 있으면 이 파서는 읽는다."""
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("word/document.xml",
                    f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>'
                    f"{body_xml}</w:body></w:document>")
    return str(p)


def _para(text: str) -> str:
    return f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"


def _row(*cells: str) -> str:
    tcs = "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in cells)
    return f"<w:tr>{tcs}</w:tr>"


def _fn_table(rows: str) -> str:
    return f"<w:tbl>{rows}</w:tbl>"


_STD = (
    _row("[ Function Information ]")
    + _row("ID", "SwUFn_0102")
    + _row("Name", "g_SysOs_WdiCtrl")
    + _row("[ Input Parameters ]")
    + _row("No", "Name", "Type", "Value Range", "Reset Value", "Description")
    + _row("1", "u8g_SystemReset_F", "U8", "0x00 ~ 0x01", "0x00", "리셋 요청")
    + _row("2", "_PTT.Bits.PTT4", "U8", "0 ~ 1", "0", "WDI")
    + _row("[ Output Parameters ]")
    + _row("No", "Name", "Type", "Value Range", "Reset Value", "Description")
    + _row("1", "_PTT.Bits.PTT3", "U8", "0 ~ 1", "0", "WDI")
    + _row("선행조건", "N/A")
    + _row("사용 전역변수", "u8g_SystemReset_F")
    + _row("Called Function", "N/A")
    + _row("[ Logic Diagram ]", "")
)


class TestParseUnitIo:
    def test_reads_input_and_output_names(self, tmp_path):
        path = _docx(_para("SwUFn_0102: g_SysOs_WdiCtrl") + _fn_table(_STD), tmp_path)
        rec = resolve_unit_io(load_uds_unit_io(path), "g_SysOs_WdiCtrl")
        assert rec == {"inputs": ["u8g_SystemReset_F", "_PTT.Bits.PTT4"],
                       "outputs": ["_PTT.Bits.PTT3"], "asil": ""}

    def test_reads_asil_from_the_function_information_block(self, tmp_path):
        """ASIL 은 같은 표의 `ASIL` 행이다 — 안전 판정(O/X)의 근거가 된다."""
        tbl = _STD.replace(_row("Name", "g_SysOs_WdiCtrl"),
                           _row("Name", "g_SysOs_WdiCtrl") + _row("ASIL", "A"))
        path = _docx(_para("SwUFn_0102: g_SysOs_WdiCtrl") + _fn_table(tbl), tmp_path)
        rec = resolve_unit_io(load_uds_unit_io(path), "g_SysOs_WdiCtrl")
        assert rec is not None and rec["asil"] == "A"
        assert rec["inputs"] == ["u8g_SystemReset_F", "_PTT.Bits.PTT4"], (
            "ASIL 행이 파라미터 구간 판정을 흔들면 안 된다"
        )

    def test_used_globals_row_is_not_a_direction(self, tmp_path):
        """⚠ `사용 전역변수` 는 방향이 없다 — 양쪽 축에 넣으면 과다가 110→1,079 로 터진다.

        그 칸은 이름 목록으로도 **쓰지 않는다**. 여기서는 그것이 기대결과 열에
        새어 들어가지 않는지를 본다(`u8g_SystemReset_F` 는 입력에만 있어야 한다).
        """
        path = _docx(_para("SwUFn_0102: g_SysOs_WdiCtrl") + _fn_table(_STD), tmp_path)
        rec = resolve_unit_io(load_uds_unit_io(path), "g_SysOs_WdiCtrl")
        assert rec is not None
        assert "u8g_SystemReset_F" not in rec["outputs"]

    def test_duplicate_function_name_is_dropped(self, tmp_path):
        """동명이인(실측 9건: `main`·`SCI0_Init` 등)은 **채우지 않는다**.

        어느 표가 그 함수인지 이름만으로 못 정한다. 하나를 임의로 고르면 그 함수의
        시험 변수가 조용히 틀린다 — 틀린 근거는 빈칸보다 나쁘다.
        """
        two = (_para("SwUFn_0101: SCI0_Init")
               + _fn_table(_row("[ Input Parameters ]")
                           + _row("1", "u8g_A", "U8", "", "", ""))
               + _para("SwUFn_3515: SCI0_Init")
               + _fn_table(_row("[ Input Parameters ]")
                           + _row("1", "u8g_B", "U8", "", "", "")))
        got = load_uds_unit_io(_docx(two, tmp_path))
        assert got["ambiguous"] == ["SCI0_Init"]
        assert resolve_unit_io(got, "SCI0_Init") is None, "동명이인을 채우면 안 된다"

    def test_missing_file_returns_empty_not_fabricated(self, tmp_path):
        got = load_uds_unit_io(str(tmp_path / "없는파일.docx"))
        assert got["by_name"] == {}
        assert resolve_unit_io(got, "anything") is None

    @pytest.mark.parametrize(
        "raw,want",
        [
            ("DiagData. OpenFailure [3]", "DiagData.OpenFailure"),  # 공백 오타 20건 + 선언 첨자
            ("ctx->state[x]", "ctx->state"),   # `[x]` 는 자리표시자(정본 SUTS 0건)
            # ⚠ 숫자 첨자도 **선언 크기**다(원소 참조가 아니다). `CSL[9]` 를 그대로
            #   옮기면 정본에 없는 이름이 되고, 첨자가 이미 붙어 원소 확장이 죽는다.
            #   실측: 첫 판이 이것 때문에 입력 일치 5,029→2,725(사라진 맞춤의 98.8%).
            ("CSL[9]", "CSL"),
            ("ctx->buffer[64]", "ctx->buffer"),
            ("N/A", ""),
            ("-", ""),
            ("1) 설명이 이름 칸에", ""),        # 식별자로 시작 안 함
            ("u8g_Normal", "u8g_Normal"),
        ],
    )
    def test_name_cleanup(self, raw, want):
        assert clean_param_name(raw) == want

    def test_arrow_is_not_converted_here(self):
        """⚠ 포인터 표기 변환은 `suts._vc_pointer_notation` **한 곳**에만 둔다.

        여기서 또 바꾸면 규칙이 두 벌이 되고, 한쪽만 고쳐지는 실패를 이 저장소가
        `[INOUT]`·`[INDIRECT2]` 로 이미 두 번 겪었다.
        """
        assert clean_param_name("ctx->buffer[64]") == "ctx->buffer"


class TestUdsOverridesSourceNames:
    @staticmethod
    def _details(**kw):
        return {"SwUFn_0101": {
            "id": "SwUFn_0101", "name": "Fn_Under_Test",
            "prototype": kw.get("prototype", "void Fn_Under_Test(void)"),
            "inputs": [], "outputs": [],
            "globals_global": list(kw.get("globals_global") or []),
            "globals_static": list(kw.get("globals_static") or []),
            "logic_flow": [],
        }}

    def test_uds_names_replace_source_names(self):
        d = self._details(globals_static=["[IN] u8g_FromSource"])
        m = {"by_name": {"Fn_Under_Test": {"inputs": ["u8g_FromUds"], "outputs": []}}}
        u = collect_unit_functions(d, sds_map={}, uds_io_map=m)[0]
        assert u["input_vars"] == ["u8g_FromUds"]
        assert "u8g_FromSource" not in u["input_vars"], "UDS 가 적었으면 UDS 가 정본이다"

    def test_source_is_kept_when_uds_has_nothing_for_that_axis(self):
        """⚠ UDS 가 그 축에 **아무것도 안 적은 것**과 **0개라고 적은 것**은 다르다.

        빈 목록으로 덮으면 근거 없는 침묵이 값이 된다.
        """
        d = self._details(globals_static=["[IN] u8g_FromSource"])
        m = {"by_name": {"Fn_Under_Test": {"inputs": [], "outputs": ["u8s_Out"]}}}
        u = collect_unit_functions(d, sds_map={}, uds_io_map=m)[0]
        assert u["input_vars"] == ["u8g_FromSource"]
        assert u["output_vars"] == ["u8s_Out"]

    def test_unit_absent_from_uds_keeps_source(self):
        d = self._details(globals_static=["[IN] u8g_FromSource"])
        m = {"by_name": {"다른함수": {"inputs": ["x"], "outputs": []}}}
        u = collect_unit_functions(d, sds_map={}, uds_io_map=m)[0]
        assert u["input_vars"] == ["u8g_FromSource"]

    def test_return_notation_survives_the_override(self):
        """정본은 반환값을 `return` 으로 적는데 UDS 는 그 표기를 안 쓴다.

        이 한 줄이 기대 재현율 83.6% → **94.1%** 의 정체다. 지우면 안 된다.
        """
        d = self._details(prototype="U8 Fn_Under_Test(void)")
        m = {"by_name": {"Fn_Under_Test": {"inputs": [], "outputs": ["u8s_Out"]}}}
        u = collect_unit_functions(d, sds_map={}, uds_io_map=m)[0]
        assert "return" in u["output_vars"], f"반환값 표기가 사라졌다: {u['output_vars']}"
        assert "u8s_Out" in u["output_vars"]

    def test_pointer_notation_is_applied_to_uds_names(self):
        """UDS 는 `ctx->buffer` 로 적고 정본 SUTS 는 `ctx[0].buffer` 로 적는다.

        실측: 정본 `->` 1건 vs `[0].` 498건.
        """
        d = self._details()
        m = {"by_name": {"Fn_Under_Test": {"inputs": ["ctx->bitcount"], "outputs": []}}}
        u = collect_unit_functions(d, sds_map={}, uds_io_map=m)[0]
        assert u["input_vars"] == ["ctx[0].bitcount"], u["input_vars"]

    def test_uds_array_names_are_still_expanded(self):
        """⚠ 대체는 **원소 확장 전에** 일어나야 한다.

        뒤에 하면 UDS 이름이 배열이어도 안 펼쳐져 정본 입도(`buf[0]`…)와 어긋난다.
        크기는 소스 선언에서 온다(UDS 는 크기를 안 적는 경우가 있다).
        """
        d = self._details(globals_static=["[IN] u8s_Buf (size: 3)"])
        m = {"by_name": {"Fn_Under_Test": {"inputs": ["u8s_Buf"], "outputs": []}}}
        u = collect_unit_functions(d, sds_map={}, uds_io_map=m)[0]
        assert u["input_vars"] == ["u8s_Buf[0]", "u8s_Buf[1]", "u8s_Buf[2]"], u["input_vars"]

    def test_no_map_keeps_the_old_behaviour(self):
        """음성 대조군 — UDS 를 못 읽은 프로젝트가 조용히 빈 문서를 내면 안 된다."""
        d = self._details(globals_static=["[IN] u8g_FromSource"])
        assert collect_unit_functions(d, sds_map={})[0]["input_vars"] == ["u8g_FromSource"]

    def test_uds_capital_return_maps_to_the_reference_token(self):
        """UDS 는 `Return`, 정본 SUTS 는 `return` — 대소문자만 다른 **같은 것**이다.

        그대로 두면 한 행에 반환값이 두 번 실리고 하나는 정본에 없는 이름이 된다.
        실측: 이 축 신규 과다 335칸 중 **284칸(85%)** 이 `Return` 이었다.
        """
        d = self._details(prototype="U8 Fn_Under_Test(void)")
        m = {"by_name": {"Fn_Under_Test": {"inputs": [], "outputs": ["Return", "u8s_Out"]}}}
        u = collect_unit_functions(d, sds_map={}, uds_io_map=m)[0]
        assert u["output_vars"].count("return") == 1, u["output_vars"]
        assert "Return" not in u["output_vars"], f"대문자 표기가 남았다: {u['output_vars']}"


class TestAsilSourcePolicy:
    """ASIL(=`Safety Related` O/X)의 출처 — **max(소스 `@asil`, SwUDS 표) > SDS 퍼지매칭**.

    실측(2026-08-14, KJPDS02_PV · 정본이 `Safety Related` 를 **채운** 868칸):

        출처            건수   일치            방향 오류
        SDS 퍼지매칭     666    489 (73.4%)    **over 88**  ← 비안전을 안전으로
        소스 `@asil`     202    200 (99.0%)    under 2      ← 안전을 비안전으로

    같은 칸을 SwUDS ASIL 로 채우면 **방향 오류 0**. 교차표에 `A→X` · `QM→O` 가 한 건도
    없다(UDS A → 정본 O 562 · 빈칸 137 · X **0** / UDS QM → 정본 X 302 · O **0**).

    정책 실측: 현재 689(79.4%) · 소스>UDS 864 · **max 865(99.7%)** · UDS만 855.
    """

    _details = staticmethod(TestUdsOverridesSourceNames._details)

    def _asil(self, src, uds_asil, sds_map=None):
        d = self._details()
        d["SwUFn_0101"]["asil"] = src
        m = {"by_name": {"Fn_Under_Test": {"inputs": [], "outputs": [], "asil": uds_asil}}}
        return collect_unit_functions(d, sds_map=sds_map if sds_map is not None else {},
                                      uds_io_map=m)[0]["asil"]

    def test_uds_fills_asil_when_source_has_no_tag(self):
        assert self._asil("TBD", "A") == "A"

    def test_higher_grade_wins_when_they_disagree(self):
        """⚠ **under-classification 방지.** 소스 주석이 낡아 QM 인데 설계서가 A 면 A 다.

        실측 충돌 1건(`s_ApiOut_u8bit_DataUpdate_A`: 소스 QM · UDS A)에서 정본은 `O`.
        내리는 쪽으로 합의하면 안전 요구를 면제해 버린다.
        """
        assert self._asil("QM", "A") == "A"
        assert self._asil("A", "QM") == "A", "반대 방향도 내리지 않는다"

    def test_uds_na_is_not_a_grade(self):
        """`N/A` 는 등급이 아니다 — 등급으로 읽으면 근거 없는 값이 생긴다."""
        assert self._asil("TBD", "N/A") == "TBD"

    def test_sds_fuzzy_match_is_only_the_last_resort(self):
        """SDS 퍼지매칭(모듈명 **부분문자열**)은 마지막이다 — over 88건의 출처다."""
        d = self._details()
        d["SwUFn_0101"]["asil"] = "TBD"
        d["SwUFn_0101"]["module_name"] = "MotorCtrl_PDS"
        sds = {"motor control": {"asil": "QM"}}
        m = {"by_name": {"Fn_Under_Test": {"inputs": [], "outputs": [], "asil": "A"}}}
        got = collect_unit_functions(d, sds_map=sds, uds_io_map=m)[0]["asil"]
        assert got == "A", f"UDS 가 있는데 SDS 퍼지매칭이 이겼다: {got}"
        # UDS 가 없을 때만 퍼지매칭이 쓰인다(회귀 가드 — 통째로 끊으면 안 된다)
        m2 = {"by_name": {"Fn_Under_Test": {"inputs": [], "outputs": [], "asil": ""}}}
        assert collect_unit_functions(d, sds_map=sds, uds_io_map=m2)[0]["asil"] == "QM"

    def test_no_uds_map_keeps_the_old_chain(self):
        """음성 대조군 — UDS 를 못 읽으면 예전 사슬(소스 → SDS)이 그대로 돌아야 한다."""
        d = self._details()
        d["SwUFn_0101"]["asil"] = "TBD"
        d["SwUFn_0101"]["module_name"] = "MotorCtrl_PDS"
        assert collect_unit_functions(d, sds_map={"motor control": {"asil": "QM"}})[0]["asil"] == "QM"

    def test_asil_maps_to_the_safety_cell(self):
        """열에 실리는 건 등급이 아니라 O/X 다 — 그 변환까지 이어지는지 본다."""
        from generators.suts import resolve_safety_related

        assert resolve_safety_related(self._asil("QM", "A")) == "O"
        assert resolve_safety_related(self._asil("TBD", "QM")) == "X"
        assert resolve_safety_related(self._asil("TBD", "N/A")) == "", "근거 없으면 빈칸"

    def test_missing_source_tag_is_not_a_conflict(self, caplog):
        """⚠ `TBD`(근거 없음)는 **반대 주장이 아니다** — 충돌로 세면 안 된다.

        첫 판이 문자열이 비었는지만 봐서 `TBD vs A` 를 충돌로 잡았고, 경고가
        **778건**을 외쳤다(실측). 그러면 진짜 충돌 1건이 그 안에 묻힌다.
        """
        import logging

        d = self._details()
        d["SwUFn_0101"]["asil"] = "TBD"
        m = {"by_name": {"Fn_Under_Test": {"inputs": [], "outputs": [], "asil": "A"}}}
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            collect_unit_functions(d, sds_map={}, uds_io_map=m)
        assert "충돌" not in caplog.text, f"근거 없음을 충돌로 셌다: {caplog.text}"

    def test_real_conflict_is_reported_not_silently_upgraded(self, caplog):
        """진짜 충돌(양쪽 다 등급)은 **세어서 보고**한다 — 조용한 승격 금지."""
        import logging

        d = self._details()
        d["SwUFn_0101"]["asil"] = "QM"
        m = {"by_name": {"Fn_Under_Test": {"inputs": [], "outputs": [], "asil": "A"}}}
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            u = collect_unit_functions(d, sds_map={}, uds_io_map=m)[0]
        assert u["asil"] == "A"
        assert "충돌 1건" in caplog.text, caplog.text
        assert "Fn_Under_Test" in caplog.text
