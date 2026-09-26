"""(R66 N76) 전역 정의 — 포인터 별 · 선언자 전부 · 같은 이름의 정의 충돌은 규칙이 고른다.

착수 실측(HEAD `161057db` 페이로드, KJPDS02·PDS64):
- 포인터 전역 10/10개의 타입에 별이 없었다 — 7행은 타입 칸이 `void`(`volatile void* volatile DBGAA;`), 3행은 `l_u8 *` 가 `l_u8` 로
  적혀 포인터가 `0 ~ 255` 범위를 받았다. 선언의 `type` 필드는 기본형뿐이고 별은 선언자에 있다.
- 초기값 없는 다중 선언(`static S32 s32s_En, s32s_Es, s32s_Ed;`)은 tree-sitter 이름 집합에 첫 이름만 들어갔다(문서 표는 텍스트
  스캔이 메워 안 보였고, 함수의 `used_globals` 에서 빠졌다).
- 같은 이름의 정의가 여러 `.c` 에 있는 이름 10/9개 — 이름 키 맵이라 하나만 남고, 누가 남는지는 파일 열거 순서(모드 의존)였다.
  내용이 다른 것은 PDS64 `BackupArray`(APP `U16` vs FBL `word`) 1건. 이제 첫 소스 루트의 정의가 남고 `differs` 가 게이트에 보인다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import workflow.code_parser.c_parser as cp
from backend.helpers.uds import _SOURCE_SECTIONS_SCHEMA_VERSION
from report_gen.source_parser import _definition_order, _norm_def_axis
from report_gen.uds_generator import generate_uds_source_sections

USER = "hbrnd3@hyunbo.com"


def _src(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _rows(text: str) -> dict:
    parser = cp._make_parser()
    if parser is None:
        pytest.skip("tree-sitter 미가용")
    data = text.encode("utf-8")
    root = parser.parse(data).root_node
    return {r["name"]: r for r in cp._extract_global_decls(root, data)}


def _names(text: str) -> list:
    parser = cp._make_parser()
    if parser is None:
        pytest.skip("tree-sitter 미가용")
    data = text.encode("utf-8")
    return cp._extract_globals(parser.parse(data).root_node, data)


class TestPointerStarsLiveInTheDeclarator:
    def test_qualified_void_pointer_register(self):
        # 실측의 본체 — 두 프로젝트 7행이 `void` 였다.
        rows = _rows("volatile void* volatile DBGAA;")
        assert rows["DBGAA"]["type"] == "void *"

    def test_static_pointer_keeps_base_and_star(self):
        rows = _rows("static l_u8 *ptr;")
        assert rows["ptr"]["type"] == "l_u8 *" and rows["ptr"]["is_static"] == "true"

    def test_double_pointer_counts_both_stars(self):
        assert _rows("unsigned char **pp = 0;")["pp"]["type"] == "unsigned char **"

    def test_star_is_per_declarator_not_per_declaration(self):
        rows = _rows("unsigned char a, *b, c[4];")
        assert rows["a"]["type"] == "unsigned char"
        assert rows["b"]["type"] == "unsigned char *"
        assert rows["c"]["type"] == "unsigned char"

    def test_struct_pointer(self):
        rows = _rows("struct T { int m; } s_t, *s_tp;")
        assert rows["s_t"]["type"] == "struct T" and rows["s_tp"]["type"] == "struct T *"

    def test_plain_variable_has_no_star(self):
        assert _rows("unsigned char plain;")["plain"]["type"] == "unsigned char"


class TestEveryDeclaratorIsARow:
    def test_uninitialised_multi_declarator_yields_all_names(self):
        # `init_declarator` 가 하나도 없는 문장 — 옛 판은 첫 이름 하나뿐이었다.
        text = "static S32 s32s_En, s32s_Es, s32s_Ed;"
        assert list(_rows(text)) == ["s32s_En", "s32s_Es", "s32s_Ed"]
        assert _names(text) == ["s32s_En", "s32s_Es", "s32s_Ed"]

    def test_mixed_initialised_and_plain_declarators(self):
        rows = _rows("unsigned char x = 1, y, z = 3;")
        assert {k: v["init"] for k, v in rows.items()} == {"x": "1", "y": "", "z": "3"}

    def test_used_globals_sees_the_second_declarator(self, tmp_path):
        (tmp_path / "a.c").write_text(
            _src("static long s_en, s_es;", "void tick(void)", "{", "    s_es = s_en + 1;", "}"), encoding="utf-8"
        )
        res = cp.parse_c_project(str(tmp_path))
        fn = {f["name"]: f for f in res["functions"]}["tick"]
        assert fn["used_globals"] == ["s_en", "s_es"]

    def test_anonymous_enum_variable_still_named_after_the_declarator(self):
        # R-이전 결함(열거자를 변수명으로) 재발 방지 — 선언자 열거가 타입 자리를 건너뛴다.
        rows = _rows("static enum { en_s_Stop = 1, en_s_Go } s_State;")
        assert list(rows) == ["s_State"] and rows["s_State"]["type"] == "enum"


class TestDefinitionOrderRule:
    def test_first_root_wins_then_path(self):
        roots = ["D:/app", "D:/fbl"]
        assert _definition_order("D:/fbl/x/a.c", roots) > _definition_order("D:/app/z/z.c", roots)
        assert _definition_order("D:/app/a.c", roots) < _definition_order("D:/app/b.c", roots)

    def test_outside_every_root_sorts_last(self):
        roots = ["D:/app"]
        assert _definition_order("E:/elsewhere/a.c", roots)[0] == 1

    def test_norm_axis_ignores_qualifiers_and_star_spacing(self):
        assert _norm_def_axis("const U8 *") == _norm_def_axis("U8*")
        assert _norm_def_axis("U16") != _norm_def_axis("word")
        assert _norm_def_axis("") == ""


def _twin_tree(tmp_path: Path, app_type: str = "unsigned short", fbl_type: str = "unsigned int") -> str:
    app = tmp_path / "app" / "Eeprom"
    fbl = tmp_path / "fbl" / "Eeprom"
    app.mkdir(parents=True)
    fbl.mkdir(parents=True)
    (app / "EEPROM.c").write_text(
        _src(f"static {app_type} BackupArray[2];", "void app_save(void)", "{", "    BackupArray[0] = 1U;", "}"),
        encoding="utf-8",
    )
    (fbl / "EEPROM.c").write_text(
        _src(f"static {fbl_type} BackupArray[2];", "void fbl_save(void)", "{", "    BackupArray[1] = 2U;", "}"),
        encoding="utf-8",
    )
    return f"{tmp_path / 'app'};{tmp_path / 'fbl'}"


class TestCollisionIsDecidedByRuleNotEnumeration:
    def test_first_root_definition_is_kept_and_difference_is_disclosed(self, tmp_path):
        sec = generate_uds_source_sections(_twin_tree(tmp_path), preprocess=False)
        info = sec["globals_info_map"]["BackupArray"]
        assert Path(info["file"]).parts[-3] == "app"
        assert info["type"] == "unsigned short"
        coll = sec["globals_scan"]["definition_collisions"]["BackupArray"]
        # (리뷰 I1) 루트 번호가 앞에 — 두 트리의 `Eeprom/EEPROM.c` 는 이름이 같아 번호 없이는 어느 쪽이 남았는지 모른다.
        assert coll["kept"] == "r0:Eeprom/EEPROM.c"
        assert sorted(coll["files"]) == ["r0:Eeprom/EEPROM.c", "r1:Eeprom/EEPROM.c"]
        assert coll["differs"] == ["type"]

    def test_root_order_is_the_rule(self, tmp_path):
        # 같은 트리, 루트 순서만 뒤집으면 FBL 정의가 남는다 — 파일 열거가 아니라 인자가 정한다.
        roots = _twin_tree(tmp_path)
        flipped = ";".join(reversed(roots.split(";")))
        sec = generate_uds_source_sections(flipped, preprocess=False)
        assert sec["globals_info_map"]["BackupArray"]["type"] == "unsigned int"

    def test_identical_twins_are_listed_but_not_flagged(self, tmp_path):
        sec = generate_uds_source_sections(_twin_tree(tmp_path, "unsigned short", "unsigned short"), preprocess=False)
        coll = sec["globals_scan"]["definition_collisions"]["BackupArray"]
        assert coll["differs"] == []

    def test_kept_definition_owns_its_array_size(self, tmp_path):
        # 이름-only 행이 먼저 와서 다른 파일의 배열 크기를 물려받던 경로 — 남은 정의는 자기 파일의 값을 가진다.
        (tmp_path / "a.c").write_text(_src("static unsigned char u8s_Buf[4];", "void fa(void)", "{", "    u8s_Buf[0] = 1U;", "}"), encoding="utf-8")
        (tmp_path / "b.c").write_text(_src("static unsigned char u8s_Buf[8];", "void fb(void)", "{", "    u8s_Buf[1] = 1U;", "}"), encoding="utf-8")
        sec = generate_uds_source_sections(str(tmp_path), preprocess=False)
        info = sec["globals_info_map"]["u8s_Buf"]
        assert Path(info["file"]).name == "a.c" and info["array"] == "[4]"
        assert sec["globals_scan"]["definition_collisions"]["u8s_Buf"]["differs"] == ["array"]


class TestDeclarationsAreNotDefinitions:
    def test_extern_in_a_c_file_does_not_win_the_collision(self, tmp_path):
        # (리뷰 C1 · 실측) `coreapi/lin_lin21_proto.c: extern l_u8 etf_collision_flag;` 가 경로순으로 앞서 `lowlevel/lin.c` 의
        #   정의 `= 0` 을 이겼다 — file·init·range 가 선언 파일 것으로 후퇴하고 differs 는 비어 게이트도 조용했다.
        (tmp_path / "coreapi").mkdir()
        (tmp_path / "lowlevel").mkdir()
        (tmp_path / "coreapi" / "proto.c").write_text(
            _src("typedef unsigned char l_u8;", "extern l_u8 etf_collision_flag;", "void fa(void)", "{", "    etf_collision_flag = 1;", "}"),
            encoding="utf-8",
        )
        (tmp_path / "lowlevel" / "lin.c").write_text(
            _src("typedef unsigned char l_u8;", "l_u8 etf_collision_flag = 0;", "void fb(void)", "{", "    if (etf_collision_flag) { fa(); }", "}"),
            encoding="utf-8",
        )
        sec = generate_uds_source_sections(str(tmp_path), preprocess=False)
        info = sec["globals_info_map"]["etf_collision_flag"]
        assert Path(info["file"]).name == "lin.c" and info["init"] == "0" and info["range"] == "0"
        assert "extern" not in info
        assert "etf_collision_flag" not in sec["globals_scan"]["definition_collisions"]

    def test_extern_scanned_last_does_not_steal_the_file(self, tmp_path):
        # 텍스트 스캔 순서가 반대(정의가 먼저, extern 이 나중)여도 같다.
        (tmp_path / "a_def.c").write_text(_src("unsigned char g_v = 3U;", "void f(void) { g_v++; }"), encoding="utf-8")
        (tmp_path / "z_use.c").write_text(_src("extern unsigned char g_v;", "void h(void) { g_v = 0U; }"), encoding="utf-8")
        sec = generate_uds_source_sections(str(tmp_path), preprocess=False)
        info = sec["globals_info_map"]["g_v"]
        assert Path(info["file"]).name == "a_def.c" and info["init"] == "3U"

    def test_extern_elsewhere_does_not_make_identical_twins_differ(self, tmp_path):
        # extern 행이 자기 정의 후보로 끼면 init "" 가 정의들과 달라 보여 거짓 `differs` 가 난다.
        for sub in ("a", "m", "z"):
            (tmp_path / sub).mkdir()
        (tmp_path / "a" / "x.c").write_text(_src("static unsigned char g_t = 1U;", "void fa(void) { g_t++; }"), encoding="utf-8")
        (tmp_path / "z" / "x.c").write_text(_src("static unsigned char g_t = 1U;", "void fz(void) { g_t++; }"), encoding="utf-8")
        (tmp_path / "m" / "x.c").write_text(_src("extern unsigned char g_t;", "void fm(void) { g_t = 0U; }"), encoding="utf-8")
        sec = generate_uds_source_sections(str(tmp_path), preprocess=False)
        coll = sec["globals_scan"]["definition_collisions"]["g_t"]
        assert coll["differs"] == [] and sorted(f.rsplit("/", 1)[0] for f in coll["files"]) == ["r0:a", "r0:z"]

    def test_extern_multi_declarator_flags_every_name(self, tmp_path):
        (tmp_path / "a.c").write_text(_src("extern unsigned char g_a, g_b;", "void f(void) { g_a = g_b; }"), encoding="utf-8")
        res = cp.parse_c_project(str(tmp_path))
        flags = {g["name"]: g.get("is_extern") for g in res["globals_detailed"] if "decl" not in g}
        assert flags == {"g_a": "true", "g_b": "true"}


class TestKeptDefinitionOwnsItsAbsence:
    def test_kept_without_initialiser_does_not_inherit_the_losers(self, tmp_path):
        # (리뷰 C2) kept 에 초기값이 없으면 진 파일의 `9U` 가 남아 있으면 안 되고, "한쪽만 없음" 도 차이다.
        (tmp_path / "a").mkdir()
        (tmp_path / "z").mkdir()
        (tmp_path / "a" / "x.c").write_text(_src("unsigned char g_k;", "void fa(void) { g_k = 1U; }"), encoding="utf-8")
        (tmp_path / "z" / "x.c").write_text(_src("unsigned char g_k = 9U;", "void fz(void) { g_k = 2U; }"), encoding="utf-8")
        sec = generate_uds_source_sections(str(tmp_path), preprocess=False)
        info = sec["globals_info_map"]["g_k"]
        assert Path(info["file"]).parent.name == "a" and info["init"] == ""
        assert sec["globals_scan"]["definition_collisions"]["g_k"]["differs"] == ["init"]

    def test_kept_scalar_does_not_inherit_the_losers_array_size(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "z").mkdir()
        (tmp_path / "a" / "y.c").write_text(_src("unsigned char g_m;", "void fa(void) { g_m = 1U; }"), encoding="utf-8")
        (tmp_path / "z" / "y.c").write_text(_src("unsigned char g_m[8];", "void fz(void) { g_m[0] = 2U; }"), encoding="utf-8")
        sec = generate_uds_source_sections(str(tmp_path), preprocess=False)
        info = sec["globals_info_map"]["g_m"]
        assert info["array"] == ""
        assert sec["globals_scan"]["definition_collisions"]["g_m"]["differs"] == ["array"]


class TestStatementLevelFactsStayWithTheirDeclarator:
    def test_array_size_belongs_to_the_array_sibling_only(self):
        # (리뷰 W1) 문장 꼬리로 배열을 읽으면 `p` 가 `[4]` 를 받는다.
        rows = _rows("static unsigned char u8s_p, u8s_q[4];")
        assert rows["u8s_p"]["array"] == "" and rows["u8s_q"]["array"] == "[4]"

    def test_multi_dimensional_array_keeps_source_order(self):
        assert _rows("unsigned char g_t[2][3];")["g_t"]["array"] == "[2][3]"

    def test_sibling_scalar_in_the_map_has_no_array(self, tmp_path):
        (tmp_path / "a.c").write_text(_src("static unsigned char u8s_p, u8s_q[4];", "void f(void) { u8s_p = u8s_q[0]; }"), encoding="utf-8")
        sec = generate_uds_source_sections(str(tmp_path), preprocess=False)
        assert sec["globals_info_map"]["u8s_p"]["array"] == "" and sec["globals_info_map"]["u8s_q"]["array"] == "[4]"

    def test_statement_comment_describes_every_declarator(self):
        # 실측(KJPDS02 `Ap_MotorCtrl_PDS.c`): 한 문장의 꼬리 주석이 세 변수를 함께 설명한다 — 마지막 선언자에만 주면(리뷰 W2 제안)
        #   앞의 둘이 설명을 잃는다. 앞 주석도 같다.
        rows = _rows("static long s32s_En, s32s_Es, s32s_Ed; /* Current error, integral value, derivative value */")
        assert [rows[n]["desc"] for n in ("s32s_En", "s32s_Es", "s32s_Ed")] == ["Current error, integral value, derivative value"] * 3
        rows = _rows("/* Range : 0 ~ 10 */\nstatic unsigned char u8s_a, u8s_b;")
        assert rows["u8s_a"]["range"] == "0 ~ 10" and rows["u8s_b"]["range"] == "0 ~ 10"
        assert rows["u8s_a"]["range_source"] == "comment"

    def test_previous_lines_trailing_comment_is_not_this_statements(self):
        # MCU 헤더 관용구 `U8 x; /* x 설명 */` 다음 줄의 선언은 그 꼬리 주석을 물려받지 않는다(선언자 수와 무관한 기존 규칙).
        rows = _rows("unsigned char x; /* about x */\nunsigned char y, z;")
        assert rows["x"]["desc"] == "about x" and rows["y"]["desc"] == "" and rows["z"]["desc"] == ""


class TestPointerGlobalInTheDocumentTable:
    def test_pointer_global_row_has_star_and_no_byte_range(self, tmp_path):
        (tmp_path / "a.c").write_text(
            _src("static unsigned char *response_buffer;", "void f(void)", "{", "    response_buffer = 0;", "}"), encoding="utf-8"
        )
        sec = generate_uds_source_sections(str(tmp_path), preprocess=False)
        row = {r[0]: r for r in sec["static_vars"]}["response_buffer"]
        assert row[1] == "unsigned char *"
        assert row[2] == ""   # 포인터는 `0 ~ 255` 가 아니다 — 범위를 지어내지 않는다


class TestGateDisclosesConflictingDefinitions:
    def test_warning_only_when_definitions_differ(self):
        pytest.importorskip("fastapi")
        from backend.helpers.uds import _note_source_caps
        from report_gen.gen_issues import IssueCollector

        base = {"measured": True, "c_total": 1, "c_cap": 200, "h_total": 0, "h_cap": 300}
        issues = IssueCollector()
        _note_source_caps(issues, {"globals_scan": {**base, "definition_collisions": {
            "BackupArray": {"files": ["a/EEPROM.c", "b/EEPROM.c"], "kept": "a/EEPROM.c", "differs": ["type"]},
            "same": {"files": ["a/x.c", "b/x.c"], "kept": "a/x.c", "differs": []},
        }}})
        found = [i for i in issues.as_list() if i["code"] == "global_definition_conflict"]
        assert len(found) == 1 and found[0]["facts"]["names"] == ["BackupArray"]
        assert "BackupArray(type)" in found[0]["message"] and "…" not in found[0]["message"]

        many = IssueCollector()
        _note_source_caps(many, {"globals_scan": {**base, "definition_collisions": {
            f"g{i}": {"files": [f"a/{i}.c", f"b/{i}.c", f"c/{i}.c", f"d/{i}.c", f"e/{i}.c"], "kept": f"a/{i}.c", "differs": ["init"]}
            for i in range(7)}}})
        msg = [i for i in many.as_list() if i["code"] == "global_definition_conflict"][0]
        assert msg["message"].endswith("…")   # (리뷰 I5) 5개만 잇고 생략을 표시한다
        assert all(len(v["files"]) == 4 for v in msg["facts"]["sample"].values())

        quiet = IssueCollector()
        _note_source_caps(quiet, {"globals_scan": {**base, "definition_collisions": {
            "same": {"files": ["a/x.c", "b/x.c"], "kept": "a/x.c", "differs": []}}}})
        assert not [i for i in quiet.as_list() if i["code"] == "global_definition_conflict"]


class TestCacheSchemaMoved:
    def test_schema_version_is_at_least_v22(self):
        assert int(_SOURCE_SECTIONS_SCHEMA_VERSION.lstrip("v")) >= 22
