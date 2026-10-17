"""R96 — 규칙(`SwUFn_NNNN: 이름`)과 표기가 다른 SwUDS 설계 머리말.

HDPDM01 SwUDS v1.07 의 머리말 13 개가 콜론 없이(`SwUFn_1343 s_GetTemperature`) 또는 대문자(`SWUFn_1133 …`)로 적혀 있었다.
판독기가 그 문단을 머리말로 보지 않아 13 함수가 설계 ID · 입출력 표를 잃었고, SUTS 의 SwUDS 기반 시험 범위에서 빠졌다.
정본 SwUTS 는 그 가운데 11 함수를 시험한다(`SwUTC_SwUFn_1343` …) — 정본 대조 판정기는 우리 쪽에 없는 함수를 분모에서 빼서
이 손실이 "정본만 잡은 결함 0" 뒤에 숨어 있었다.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from generators.uds_design_ids import canonical_design_id, load_uds_design_ids, read_design_heading, resolve_design_id
from generators.uds_unit_io import load_uds_unit_io, resolve_unit_io

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
HD_SUDS = Path(r"D:\Project\devops\260105\docs\(HDPDM01_SUDS) Software Unit Design Specification_v1.07_240213.docx")


def _docx(body_xml: str, tmp_path, name: str = "uds.docx") -> str:
    p = tmp_path / name
    with zipfile.ZipFile(p, "w") as zf:
        zf.writestr("word/document.xml",
                    f'<?xml version="1.0"?><w:document xmlns:w="{W}"><w:body>{body_xml}</w:body></w:document>')
    return str(p)


def _para(text: str) -> str:
    return f"<w:p><w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def _row(*cells: str) -> str:
    return "<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{c}</w:t></w:r></w:p></w:tc>" for c in cells) + "</w:tr>"


def _table(fid: str, name: str, var: str) -> str:
    rows = _row("[ Function Information ]") + _row("ID", fid) + _row("Name", name)
    rows += _row("[ Input Parameters ]") + _row("No", "Name", "Type", "Value Range", "Reset Value", "Description")
    rows += _row("1", var, "U8", "0x00 ~ 0x03", "0", "d")
    rows += _row("[ Output Parameters ]") + _row("No", "Name", "Type", "Value Range", "Reset Value", "Description")
    rows += _row("[ Logic Diagram ]", "")
    return f"<w:tbl>{rows}</w:tbl>"


class TestGrammar:
    @pytest.mark.parametrize("text, did, name, status, variant", [
        # HDPDM01 v1.07 원문 그대로
        ("SwUFn_1343 s_GetTemperature", "SwUFn_1343", "s_GetTemperature", "plain", ["no_colon"]),
        ("SwUFn_1342 s_AssistDeactivation_CloseChk(New)", "SwUFn_1342", "s_AssistDeactivation_CloseChk", "marked",
         ["no_colon"]),
        ("SWUFn_1133 s_TunningParamRead_8bitData (New)", "SwUFn_1133", "s_TunningParamRead_8bitData", "marked",
         ["no_colon", "case"]),
        ("SWUFn_1130: s_OverPosWrite (New)", "SwUFn_1130", "s_OverPosWrite", "marked", ["case"]),
        # 개명 꼬리 `<- 옛이름` 은 떼고 남은 표시로 판정한다(리뷰 W3) — `(New)` 는 표시
        ("SWUFn_1131: s_SystemParamRead <- g_SysEepromCtrl_SystemParamRead (New)", "SwUFn_1131", "s_SystemParamRead",
         "marked", ["case"]),
        ("SWUFn_1132 s_TunningParamRead <- g_SysEepromCtrl_TunningParamRead (New)", "SwUFn_1132", "s_TunningParamRead",
         "marked", ["no_colon", "case"]),
        ("SwUFn_0001: s_X <- g_Y", "SwUFn_0001", "s_X", "plain", None),
        ("SwUFn_0001 s_X <- g_Y (삭제)", "SwUFn_0001", "s_X", "deleted", ["no_colon"]),
        ("SwUFn_0001: s_X <- g_Y (삭제)", "SwUFn_0001", "s_X", "deleted", None),
        # (리뷰 2차 W1) 꼬리 뒤에 붙은 글은 옛 이름 쪽 — 설계는 그대로 읽는다(HEAD 와 같은 plain)
        ("SwUFn_0001: s_X <- g_Y.", "SwUFn_0001", "s_X", "plain", None),
        ("SwUFn_0001: s_X <- g_Y-old", "SwUFn_0001", "s_X", "plain", None),
        ("SwUFn_0001: s_X <- g_Y, 함수명 변경", "SwUFn_0001", "s_X", "plain", None),
        # 콜론 없는 꼴의 삭제 표시는 콜론 꼴과 같은 판정
        ("SwUFn_1007 s_Gone(삭제)", "SwUFn_1007", "s_Gone", "deleted", ["no_colon"]),
        # 규칙대로 적은 머리말은 그대로(표기 흔들림 표시 없음)
        ("SwUFn_0101: main", "SwUFn_0101", "main", "plain", None),
        ("SwUFn_0101: main 함수", "SwUFn_0101", "main", "plain", None),
    ])
    def test_reads(self, text, did, name, status, variant):
        h = read_design_heading(text)
        assert (h["id"], h["name"], h["status"], h.get("variant")) == (did, name, status, variant)

    @pytest.mark.parametrize("text", [
        "SwUFn_0101 main 함수",                       # 콜론 없이 설명 글 — 본문 문장일 수 있다
        "SwUFn_0101 g_A, SwUFn_0102 g_B",              # 나열
        "SwUFn_0101 은 main 을 부른다",
        "SwUFn_0101",
        "SwUFn_0101:",
        "SwUFn_0101 3abc",
        "참조 SwUFn_0101 main",                        # 문단 머리가 ID 가 아니다
    ])
    def test_bare_form_is_a_heading_only_when_the_whole_paragraph_is_id_name_mark(self, text):
        assert read_design_heading(text) is None

    def test_rename_tail_is_recorded(self):
        assert read_design_heading("SWUFn_1131: s_SystemParamRead <- g_SysEepromCtrl_SystemParamRead (New)")[
            "renamed_from"] == "g_SysEepromCtrl_SystemParamRead"
        assert "renamed_from" not in read_design_heading("SwUFn_0101: main")

    def test_colon_form_with_an_unreadable_name_is_still_unread_and_canonical(self):
        h = read_design_heading("SWUFn_0101: 3abc")
        assert (h["id"], h["status"]) == ("SwUFn_0101", "unread")

    @pytest.mark.parametrize("raw, want", [("SWUFn_1133", "SwUFn_1133"), ("swufn_0001", "SwUFn_0001"),
                                           ("SwUFn_0101", "SwUFn_0101"), ("SwFn_01", "SwFn_01"), ("", "")])
    def test_canonical_design_id(self, raw, want):
        assert canonical_design_id(raw) == want


class TestDocument:
    def test_variant_headings_get_their_id_and_table_in_both_loaders(self, tmp_path):
        body = (_para("SwUFn_0001: f_a") + _table("SwUFn_0001", "f_a", "a")
                + _para("SwUFn_0002 f_b") + _table("SwUFn_0002", "f_b", "b")
                + _para("SWUFn_0003 f_c (New)") + _table("SWUFn_0003", "f_c", "c"))
        path = _docx(body, tmp_path)
        ids = load_uds_design_ids(path)
        assert [resolve_design_id(ids, n) for n in ("f_a", "f_b", "f_c")] == ["SwUFn_0001", "SwUFn_0002", "SwUFn_0003"]
        io = load_uds_unit_io(path)
        for fn, var in (("f_a", "a"), ("f_b", "b"), ("f_c", "c")):
            rec = resolve_unit_io(io, fn)
            assert rec is not None and var in (rec.get("inputs") or rec.get("input_vars") or []), (fn, rec)
        want = ["SwUFn_0002 f_b", "SWUFn_0003 f_c (New)"]
        assert ids["variant_headings"] == want and io["reading"]["variant_headings"] == want

    def test_deleted_rename_does_not_make_the_new_design_ambiguous(self, tmp_path):
        """(리뷰 W3) `s_X <- g_Y (삭제)` 를 살아 있는 설계로 읽으면 같은 이름의 `(New)` 머리말과 동명이인이 돼 `s_X` 가 설계 ID 를
        잃는다(R96 전에는 그 문단을 무시해 `(New)` 쪽에 매핑됐다 — 회귀)."""
        body = (_para("SwUFn_1132 s_X &lt;- g_Y (삭제)") + _table("SwUFn_1132", "s_X", "a")
                + _para("SwUFn_2000: s_X (New)") + _table("SwUFn_2000", "s_X", "b"))
        ids = load_uds_design_ids(_docx(body, tmp_path))
        assert resolve_design_id(ids, "s_X") == "SwUFn_2000" and ids["ambiguous"] == []

    def test_unattached_function_tables_are_named_by_both_loaders(self, tmp_path):
        """(리뷰 W2) 앞 머리말을 읽지 못한 함수 표(HDPDM01 `EnUserSwUFn_2302: PP0_MOTOR_PWM_Init`)는 어느 엔트리에도 붙지 않는다 —
        조용히 버리지 않고 표 Name 행을 낸다. 함수 표가 아닌 표(개정 이력 등)는 세지 않는다."""
        other = "<w:tbl>" + _row("Version", "Date") + _row("1.0", "2024") + "</w:tbl>"
        body = (other + _para("SwUFn_0001: f_a") + _table("SwUFn_0001", "f_a", "a")
                + _para("EnUserSwUFn_0002: f_b") + _table("SwUFn_0002", "f_b", "b") + other)
        path = _docx(body, tmp_path)
        assert load_uds_design_ids(path)["unattached_tables"] == ["f_b"]
        assert load_uds_unit_io(path)["reading"]["unattached_tables"] == ["f_b"]

    def test_a_function_table_before_the_first_heading_is_unattached(self, tmp_path):
        """(리뷰 2차 I3) 첫 머리말 앞의 함수 표(머리말을 읽지 못한 첫 함수)도 이름을 낸다."""
        body = (_para("EnUserSwUFn_0001: f_a") + _table("SwUFn_0001", "f_a", "a")
                + _para("SwUFn_0002: f_b") + _table("SwUFn_0002", "f_b", "b"))
        assert load_uds_design_ids(_docx(body, tmp_path))["unattached_tables"] == ["f_a"]

    def test_unattached_tables_make_the_reading_item_a_warning(self):
        """(리뷰 2차 W2) 결손(설계 ID · 입출력 표를 못 받음)을 말하면서 info 로 두지 않는다."""
        from generators.suts import summarize_uds_reading
        from report_gen.generation_disclosures import build_disclosures

        io = {"by_name": {"f": {}}, "reading": {"headings": 1, "tables": 1, "functions": 1, "param_rows": 1,
                                                "unattached_tables": ["PP0_MOTOR_PWM_Init"]}}
        s = summarize_uds_reading(io, [{"name": "f"}], True)
        it = next(i for i in build_disclosures("suts", {"uds_reading": s}) if i["key"] == "suts_uds_reading")
        assert it["tone"] == "warning" and "PP0_MOTOR_PWM_Init" in it["note"]

    def test_a_bare_heading_takes_its_own_table_not_the_previous_one(self, tmp_path):
        """예전 판은 콜론 없는 머리말을 건너뛰어 그 표를 아무에게도 붙이지 않았다(앞 함수는 이미 자기 표가 있다). 이제는 그
        표가 그 머리말 함수의 것이고, 앞 함수의 표는 그대로다."""
        body = (_para("SwUFn_0001: f_a") + _table("SwUFn_0001", "f_a", "a")
                + _para("SwUFn_0002 f_b") + _table("SwUFn_0002", "f_b", "b"))
        io = load_uds_unit_io(_docx(body, tmp_path))
        a, b = resolve_unit_io(io, "f_a"), resolve_unit_io(io, "f_b")
        assert "a" in (a.get("inputs") or a.get("input_vars")) and "b" not in (a.get("inputs") or a.get("input_vars"))
        assert "b" in (b.get("inputs") or b.get("input_vars"))


class TestDisclosure:
    def test_variant_headings_are_disclosed_with_samples(self):
        from generators.suts import summarize_uds_reading
        from report_gen.generation_disclosures import build_disclosures

        io = {"by_name": {"s_GetTemperature": {}}, "reading": {
            "headings": 2, "tables": 2, "functions": 2, "param_rows": 2,
            "variant_headings": ["SwUFn_1343 s_GetTemperature", "SWUFn_1133 s_TunningParamRead_8bitData (New)"]}}
        s = summarize_uds_reading(io, [{"name": "s_GetTemperature"}], True)
        assert s["variant_headings"] == io["reading"]["variant_headings"]
        note = next(it["note"] for it in build_disclosures("suts", {"uds_reading": s}) if it["key"] == "suts_uds_reading")
        for want in ("표기가 규칙(`SwUFn_NNNN: 이름`)과 다른 설계 머리말 2개", "`SwUFn_1343 s_GetTemperature`",
                     "`SWUFn_1133 s_TunningParamRead_8bitData (New)`"):
            assert want in note, want

    def test_no_sentence_without_variants(self):
        from generators.suts import summarize_uds_reading
        from report_gen.generation_disclosures import build_disclosures

        io = {"by_name": {"f": {}}, "reading": {"headings": 1, "tables": 1, "functions": 1, "param_rows": 1}}
        s = summarize_uds_reading(io, [{"name": "f"}], True)
        note = next(it["note"] for it in build_disclosures("suts", {"uds_reading": s}) if it["key"] == "suts_uds_reading")
        assert "표기가 규칙" not in note


class TestTestScope:
    """시험 범위 — 실제로 적용한 범위와 뺀 함수(이름 · 사유). 예전엔 개수만 진행 메시지에 남았다(산출물 · 공시 어디에도 없음)."""

    def _units(self):
        return [{"name": "f_kept", "suds_id": "SwUFn_0001", "source_path": "/s/a.c"},
                {"name": "f_absent", "suds_id": "", "source_path": "/s/b.c"},
                {"name": "SCI0_Init", "suds_id": "", "source_path": "/app/SCI0.c"},
                {"name": "SCI0_Init", "suds_id": "", "source_path": "/fbl/SCI0.c"},
                {"name": "s_Gone", "suds_id": "", "source_path": "/s/c.c"},
                {"name": "PP0_MOTOR_PWM_Init", "suds_id": "", "source_path": "/s/PP0.c"},
                {"name": "main", "suds_id": "", "source_path": "/s/m.c"},
                {"name": "f_alias", "suds_id": "", "source_path": "/s/d.c"}]

    DESIGN = {"ambiguous": ["SCI0_Init"], "deleted": ["SwUFn_1007: s_Gone(삭제)"], "unattached_tables": ["PP0_MOTOR_PWM_Init"],
              "unread_headings": ["SwUFn_0101: main-old"], "alias_dropped_source": ["f_alias→f_head"]}

    def test_excluded_functions_are_named_with_their_reason(self):
        from generators.suts import scope_units

        kept, notes, s = scope_units(self._units(), "suds", self.DESIGN)
        assert [u["name"] for u in kept] == ["f_kept"]
        assert (s["scope"], s["applied"], s["unknown_value"]) == ("suds", True, "")
        assert (s["source_functions"], s["tested"], s["excluded"]) == (8, 1, 7)
        assert s["by_reason"] == {"absent": 1, "ambiguous": 2, "deleted": 1, "table_only": 1, "heading_unread": 1,
                                  "alias_dropped": 1}
        assert {(e["name"], e["file"], e["reason"]) for e in s["excluded_functions"]} >= {
            ("f_absent", "b.c", "absent"), ("PP0_MOTOR_PWM_Init", "PP0.c", "table_only"), ("main", "m.c", "heading_unread"),
            ("f_alias", "d.c", "alias_dropped"), ("s_Gone", "c.c", "deleted")}
        assert s["notes"] == notes and "7개 제외" in notes[0]

    def test_apply_scope_is_the_same_judgement(self):
        from generators.suts import apply_scope, scope_units

        assert apply_scope(self._units(), "suds") == scope_units(self._units(), "suds")[:2]

    def test_source_scope_says_so(self):
        from generators.suts import scope_units
        from report_gen.generation_disclosures import build_disclosures

        kept, _notes, s = scope_units(self._units(), "source")
        assert len(kept) == 8 and (s["scope"], s["applied"], s["excluded"], s["excluded_functions"]) == ("source", False, 0, [])
        it = next(i for i in build_disclosures("suts", {"test_scope": s}) if i["key"] == "suts_test_scope")
        assert it["label"] == "시험 범위(소스 전체)" and it["tone"] == "info" and "SwUDS 기반" not in it["value"]
        assert "정본(SwUDS 기반)보다 넓을 수 있다" in it["note"] and "뺀 함수 없음" not in it["note"]

    def test_suds_without_design_ids_is_not_called_the_reference_scope(self):
        """(리뷰 C1) SwUDS 를 못 읽어 설계 ID 가 0 이면 범위를 좁히지 못했다 — 소스 전체를 시험했는데 "SwUDS 기반 · 정본과 같은 범위
        · 뺀 함수 없음" 이라고 적었다."""
        from generators.suts import scope_units
        from report_gen.generation_disclosures import build_disclosures

        units = [dict(u, suds_id="") for u in self._units()]
        kept, notes, s = scope_units(units, "suds", None)
        assert len(kept) == 8 and (s["scope"], s["applied"], s["excluded"]) == ("suds", False, 0)
        it = next(i for i in build_disclosures("suts", {"test_scope": s}) if i["key"] == "suts_test_scope")
        assert it["tone"] == "warning" and "적용 못 함" in it["label"] and "정본과 같은 범위가 아니다" in it["note"]
        assert "뺀 함수 없음" not in it["note"] and "범위를 좁히지 않았습니다" in it["note"]   # 판정 문장(notes)도 싣는다

    def test_unknown_scope_value_is_disclosed(self):
        from generators.suts import scope_units
        from report_gen.generation_disclosures import build_disclosures

        _kept, _notes, s = scope_units(self._units(), "sud", self.DESIGN)
        assert s["unknown_value"] == "sud"
        it = next(i for i in build_disclosures("suts", {"test_scope": s}) if i["key"] == "suts_test_scope")
        assert "알 수 없는 시험 범위 `sud`" in it["note"] and it["tone"] == "warning"

    def test_disclosure_names_them_by_reason_with_actionable_guidance(self):
        from generators.suts import scope_units
        from report_gen.generation_disclosures import build_disclosures

        _kept, _notes, s = scope_units(self._units(), "suds", self.DESIGN)
        it = next(i for i in build_disclosures("suts", {"test_scope": s}) if i["key"] == "suts_test_scope")
        assert it["tone"] == "warning" and it["value"].startswith("소스 함수 8 중 시험 1 · 제외 7")
        note = it["note"]
        for want in ("설계서 누락 후보", "1개(예: f_absent)", "머리말 오타", "1개(예: PP0_MOTOR_PWM_Init)",
                     "2개(예: SCI0_Init ×2)", "정본은 둘 다 시험한다", "test_scope.excluded_functions",
                     "설계 삭제가 맞으면 소스에서 지울 것"):
            assert want in note, want
        assert "머리말 이름을 구별하면" not in note        # (리뷰 W4) 쌍둥이에 실행할 수 없는 안내

    def test_branch_is_on_the_count_not_the_list(self):
        """(리뷰 I3) 목록이 빠진 요약(개수만)에 "뺀 함수 없음" 을 적지 않는다."""
        from report_gen.generation_disclosures import build_disclosures

        s = {"scope": "suds", "applied": True, "source_functions": 5, "tested": 3, "excluded": 2, "by_reason": {"absent": 2}}
        it = next(i for i in build_disclosures("suts", {"test_scope": s}) if i["key"] == "suts_test_scope")
        assert "뺀 함수 없음" not in it["note"] and it["tone"] == "warning"
        assert "— ." not in it["note"] and "이름 목록 없음" in it["note"]       # (리뷰 2차 I1) 빈 문장 없음

    def test_no_item_from_an_old_report(self):
        from report_gen.generation_disclosures import build_disclosures

        assert not [i for i in build_disclosures("suts", {}) if i["key"] == "suts_test_scope"]


class TestGeneratorRecordsScope:
    """(리뷰 W1) 생성기가 범위 요약을 품질 보고서에 싣는지 — 문자열 앵커가 아니라 작은 소스 · SwUDS 로 실제 생성해서 본다."""

    def _gen(self, tmp_path, monkeypatch, body_xml, scope="suds"):
        from generators import suts as gsuts

        # (R97) 프로젝트 맵은 생성 루트가 매니페스트 루트 안일 때만 적용된다 — tmp_path 는 어느 프로젝트도 아니라 격리 patch 가 필요 없다
        (tmp_path / "m.c").write_text(
            "typedef unsigned char U8;\n"
            "U8 f_a(U8 a)\n{\n    return a;\n}\n"
            "U8 f_b(U8 a)\n{\n    return (U8)(a + 1U);\n}\n"
            "U8 f_c(U8 a)\n{\n    return (U8)(a + 2U);\n}\n"
            "U8 f_d(U8 a)\n{\n    return (U8)(a + 3U);\n}\n", encoding="utf-8")
        uds = _docx(body_xml, tmp_path, "(P_SwUDS) Software Unit Design Specification.docx")
        out = gsuts.generate_suts(source_root=str(tmp_path), output_path=str(tmp_path / "u.xlsm"), scope=scope, uds_path=uds)
        return out["quality_report"]["test_scope"]

    def test_reasons_come_from_the_design_reading(self, tmp_path, monkeypatch):
        body = (_para("SwUFn_0001: f_a") + _table("SwUFn_0001", "f_a", "a")
                + _para("EnUserSwUFn_0002: f_b") + _table("SwUFn_0002", "f_b", "a")         # 머리말 오타 → 표만
                + _para("SwUFn_0003: f_c") + _table("SwUFn_0003", "f_c", "a")
                + _para("SwUFn_0004: f_c") + _table("SwUFn_0004", "f_c", "a"))              # 동명이인
        s = self._gen(tmp_path, monkeypatch, body)
        assert (s["scope"], s["applied"], s["tested"]) == ("suds", True, 1)
        assert {(e["name"], e["reason"]) for e in s["excluded_functions"]} == {
            ("f_b", "table_only"), ("f_c", "ambiguous"), ("f_d", "absent")}

    def test_source_scope_is_recorded(self, tmp_path, monkeypatch):
        s = self._gen(tmp_path, monkeypatch, _para("SwUFn_0001: f_a") + _table("SwUFn_0001", "f_a", "a"), scope="source")
        assert (s["scope"], s["applied"], s["tested"], s["excluded"]) == ("source", False, 4, 0)


@pytest.mark.skipif(not HD_SUDS.exists(), reason="HDPDM01 SwUDS v1.07 사본 없음")
class TestHdpdm01Document:
    """실제 문서 — 놓쳤던 13 머리말이 설계 ID 를 얻고, 원래 읽던 머리말은 하나도 바뀌지 않는다."""

    OLD_PAIRS_SHA256 = "42d5c44e67872a16b570229b297b71b62e9a79347625566ec16f13bb58ba21b8"   # HEAD 4d1ed9af 판독기로 계산
    MISSED = {"s_OverPosWrite": "SwUFn_1130", "s_SystemParamRead": "SwUFn_1131", "s_TunningParamRead": "SwUFn_1132",
              "s_TunningParamRead_8bitData": "SwUFn_1133", "s_TunningParamRead_16bitData": "SwUFn_1134",
              "s_AssistDeactivation_CloseChk": "SwUFn_1342", "s_GetTemperature": "SwUFn_1343",
              "s16s_DoorStopPosition_AssistClose": "SwUFn_1344", "s_IsDoorMoving_FullLatch": "SwUFn_1345",
              "s_IsDrMov_FullLatch_StopPosChk": "SwUFn_1346", "s_IsDrMov_FullLatch_MoveChk": "SwUFn_1347",
              "s_IsDrMov_FullLatch_StopChk": "SwUFn_1348", "s_DoorState_AssistClose": "SwUFn_1413"}

    def test_missed_headings_now_map_and_nothing_else_moves(self):
        # 34 MB XML — 한 시험 안에서 세 번 파싱하지 않도록 판독기 캐시를 쓰는 두 로더 뒤에 엔트리 순회 한 번만 더 한다
        ids = load_uds_design_ids(str(HD_SUDS))
        assert {n: resolve_design_id(ids, n) for n in self.MISSED} == self.MISSED
        assert len(ids["variant_headings"]) == 13 and ids["total"] == 429
        # R95 까지의 판독(390 id) 은 (이름, ID) 값까지 그대로 — 새 13 개만 더해졌다(리뷰 I5: 개수만이 아니라 값을 고정)
        old = sorted((n, i) for n, i in ids["by_name"].items() if n not in self.MISSED)
        assert len(old) == 390 and hashlib.sha256(json.dumps(old).encode()).hexdigest() == self.OLD_PAIRS_SHA256
        assert all(v.startswith("SwUFn_") for v in ids["by_name"].values())
        io = load_uds_unit_io(str(HD_SUDS))
        assert all(resolve_unit_io(io, n) is not None for n in self.MISSED)
        # 새 13 머리말은 각자 자기 표를 받는다(표 Name 행 == 머리말 이름)
        from generators.uds_design_ids import iter_design_entries, read_docx_body, read_toc_style_ids, table_name_row

        entries = [e for e in iter_design_entries(read_docx_body(HD_SUDS), read_toc_style_ids(HD_SUDS)) if e.get("variant")]
        assert sorted((e["name"], table_name_row(e["table"])) for e in entries) == sorted((n, n) for n in self.MISSED)
        # 머리말을 읽지 못한 표 하나(`EnUserSwUFn_2302: PP0_MOTOR_PWM_Init`)는 이름을 낸다(리뷰 W2)
        assert ids["unattached_tables"] == ["PP0_MOTOR_PWM_Init"]
