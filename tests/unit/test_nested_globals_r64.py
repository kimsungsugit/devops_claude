"""(R64 N73) tree-sitter 전역 수집이 include guard 안(어느 깊이든)의 산 선언을 본다.

옛 수집기 둘(`_extract_globals`·`_extract_global_decls`)은 `root.children` 만 봐서 `#ifndef X_H … #endif` 안을 통째로
못 봤다. 실측(KJPDS02 178 파일 · PDS64 127 파일):
- 놓친 산 선언 1,481 / 1,032개(헤더 extern 1,208 / 1,018 + `.c` 의 `#ifdef` 안 정의) → 그 파일 함수의 `used_globals`
  가 비어 KJPDS02 함수 107/681개가 전역을 하나도 안 쓰는 것으로(SwUT 조회·아키텍처 지표·UDS 본문 없는 함수의 표).
- 정본 UDS 가 싣는 `Lib_sha256.c:s_nb_ctx` 가 전역 표에 없었다.
- 리뷰 전제 하나는 틀렸다: 죽은 `#if 0` 구간은 최상위만 볼 땐 `preproc_if` 아래라 **우연히** 안 보였다 — 전체를 걸으면
  규칙으로 빼야 한다(`_dead_nodes`).
- 첫 구현의 함정: 헤더 extern 행이 정의를 덮어 정의가 `.c` 에 있는 전역 750/401개의 file 이 헤더로 바뀌었다 → `is_extern`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import workflow.code_parser.c_parser as cp
from report_gen.uds_generator import generate_uds_source_sections

USER = "hbrnd3@hyunbo.com"


def _src(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _parse(text: str):
    parser = cp._make_parser()
    if parser is None:
        pytest.skip("tree-sitter 미가용")
    data = text.encode("utf-8")
    return parser.parse(data).root_node, data


def _names(text: str) -> list:
    root, data = _parse(text)
    return cp._extract_globals(root, data)


def _rows(text: str) -> list:
    root, data = _parse(text)
    return cp._extract_global_decls(root, data)


def _sections(tmp_path: Path, files: dict) -> dict:
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    return generate_uds_source_sections(str(tmp_path), preprocess=False)


def _fn(sec: dict, name: str) -> dict:
    return {v["name"]: v for v in sec["function_details"].values()}[name]


class TestNestedLiveDeclarationsAreCollected:
    def test_include_guarded_header_extern_is_a_global_name(self):
        text = _src("#ifndef X_H", "#define X_H", "extern unsigned char g_guarded;", "#endif")
        assert "g_guarded" in _names(text)
        rows = {r["name"]: r for r in _rows(text)}
        assert rows["g_guarded"]["is_extern"] == "true"
        assert rows["g_guarded"]["type"] == "unsigned char"

    def test_ifdef_definition_in_a_c_file_is_collected_with_its_init(self):
        text = _src("#ifdef USE_NB", "static unsigned char s_nb_ctx = 3U;", "#endif")
        rows = {r["name"]: r for r in _rows(text)}
        assert rows["s_nb_ctx"]["init"] == "3U"
        assert rows["s_nb_ctx"]["is_static"] == "true"
        assert rows["s_nb_ctx"]["is_extern"] == "false"

    def test_both_branches_of_an_ifdef_are_kept(self):
        # 리터럴 0/1 만 판정한다(과대포함이 안전 방향) — `#ifdef FOO … #else …` 는 둘 다 산 후보.
        text = _src("#ifdef FOO", "unsigned char g_foo;", "#else", "unsigned char g_bar;", "#endif")
        assert set(_names(text)) >= {"g_foo", "g_bar"}

    def test_used_globals_of_a_function_sees_the_nested_definition(self, tmp_path):
        # 실측의 본체 — 전역이 전부 `#ifdef` 안인 파일(`lin_lld_sci.c`·`Ap_MotorCtrl_PDS.c`)의 함수는 used_globals 가 비어 있었다.
        (tmp_path / "a.c").write_text(
            _src("#ifdef FEATURE", "static unsigned char s_state = 0U;", "#endif", "void tick(void)", "{", "    s_state++;", "}"),
            encoding="utf-8",
        )
        res = cp.parse_c_project(str(tmp_path))
        fn = {f["name"]: f for f in res["functions"]}["tick"]
        assert fn["used_globals"] == ["s_state"]
        assert "s_state" in res["globals"]

    def test_nested_static_reaches_the_function_table(self, tmp_path):
        # 정본 UDS 의 `s_nb_ctx` 시나리오: 본문이 있는 함수는 globals_info_map 으로 판정하므로 전역 맵에 있어야 표에 선다.
        sec = _sections(
            tmp_path,
            {"a.c": _src("#ifdef USE_NB", "static unsigned char s_nb_ctx;", "#endif", "void proc(void)", "{", "    s_nb_ctx = 1U;", "}")},
        )
        assert "s_nb_ctx" in sec["globals_info_map"]
        assert any("s_nb_ctx" in str(x) for x in _fn(sec, "proc")["globals_static"])
        assert any(row[0] == "s_nb_ctx" for row in sec["static_vars"])


class TestDeadNestedDeclarationsStayExcluded:
    def test_if0_declaration_is_not_collected_even_when_walking_the_tree(self):
        text = _src("unsigned char g_live;", "#if 0", "unsigned char g_ghost;", "#endif")
        assert "g_ghost" not in _names(text)
        assert "g_ghost" not in {r["name"] for r in _rows(text)}
        assert "g_live" in _names(text)

    def test_if1_alternative_is_dead(self):
        text = _src("#if 1", "unsigned char g_on;", "#else", "unsigned char g_off;", "#endif")
        names = _names(text)
        assert "g_on" in names and "g_off" not in names

    def test_if0_nested_inside_an_include_guard_is_dead(self):
        text = _src("#ifndef X_H", "#define X_H", "#if 0", "extern unsigned char g_ghost;", "#endif", "extern unsigned char g_live;", "#endif")
        names = _names(text)
        assert "g_live" in names and "g_ghost" not in names

    def test_dead_node_rule_is_shared_with_functions(self):
        # 함수용 판정은 그대로(래퍼) — 한 규칙 두 구현을 만들지 않는다.
        root, data = _parse(_src("#if 0", "void ghost(void) { }", "unsigned char g_ghost;", "#endif"))
        dead_fn = cp._dead_function_nodes(root, data)
        dead_decl = cp._dead_nodes(root, data, ("declaration",))
        assert len(dead_fn) == 1 and len(dead_decl) == 1
        assert cp._dead_nodes(root, data, ("function_definition", "declaration")) == dead_fn | dead_decl


class TestNotEveryNestedDeclarationIsAGlobal:
    def test_local_variable_inside_ifdef_inside_a_function_is_not_a_global(self):
        text = _src("void f(void)", "{", "#ifdef DBG", "    unsigned char local_dbg = 0U;", "#endif", "    (void)local_dbg;", "}")
        assert "local_dbg" not in _names(text)

    def test_struct_member_and_prototype_are_not_globals(self):
        text = _src("#ifndef X_H", "typedef struct { unsigned char member; } S_t;", "void proto(unsigned char a);", "extern S_t g_s;", "#endif")
        names = _names(text)
        assert "g_s" in names
        assert "member" not in names and "proto" not in names

    def test_name_taken_from_an_error_node_is_rejected_but_the_real_name_survives(self):
        # `__far` 가 타입 자리를 먹으면 `U8` 이 ERROR 로 밀려나 변수명으로 잡혔다(KJPDS02 `Lib_sha256.c`). (리뷰 W1) 유령을 막는
        # 대신 선언째 버리면 그 파일의 산 static 둘이 표에서 사라진다 — 양쪽을 한 쌍으로 단언.
        text = _src("#ifdef X", "static __far const U8 *s_nb_p_data;", "#endif")
        names = _names(text)
        assert "U8" not in names
        assert "s_nb_p_data" in names

    def test_declarations_dropped_for_error_names_are_counted(self, tmp_path):
        # (리뷰 W1) 이름이 ERROR 안에서만 나오는 선언은 버리되 **센다** — 죽은 코드 제외처럼 조용하지 않게.
        (tmp_path / "a.c").write_text(_src("int = 3;", "unsigned char g_ok;"), encoding="utf-8")
        res = cp.parse_c_project(str(tmp_path))
        assert "g_ok" in res["globals"]
        assert isinstance(res["decl_error_rejected"], int)
        sec = generate_uds_source_sections(str(tmp_path), preprocess=False)
        assert sec["globals_scan"]["decl_error_rejected"] == res["decl_error_rejected"]

    def test_address_placement_error_does_not_lose_the_real_name(self):
        # 선언 어딘가에 ERROR 가 있다고 버리면 `@주소` 배치 변수(두 프로젝트 최상위 4/4행)를 잃는다 — 이름 노드의 조상만 본다.
        text = _src("#ifdef X", "static volatile unsigned char u8s_StackGuard @0x2400U;", "#endif")
        assert "u8s_StackGuard" in _names(text)
        top = _src("static volatile unsigned char u8s_TopGuard @0x2400U;")
        assert "u8s_TopGuard" in _names(top)


class TestExternDeclarationDoesNotOverrideADefinition:
    """첫 구현의 함정 — 헤더 extern 행이 뒤에 오면 정의의 file·desc 를 헤더 것으로 갈아 끼웠다(750/401개)."""

    @pytest.mark.parametrize("c_name,h_name", [("a.c", "z.h"), ("z.c", "a.h")])
    def test_definition_file_wins_regardless_of_walk_order(self, tmp_path, c_name, h_name):
        sec = _sections(
            tmp_path,
            {
                c_name: _src("unsigned char g_val = 7U;", "void use(void)", "{", "    g_val = 1U;", "}"),
                h_name: _src("#ifndef H_H", "#define H_H", "extern unsigned char g_val;   /* header note */", "#endif"),
            },
        )
        info = sec["globals_info_map"]["g_val"]
        assert Path(info["file"]).name == c_name
        assert info["init"] == "7U"

    def test_header_comment_fills_only_an_empty_description(self, tmp_path):
        sec = _sections(
            tmp_path,
            {
                "a.c": _src("unsigned char g_a = 1U;   /* defined here */", "unsigned char g_b = 2U;", "void use(void)", "{", "    g_a = g_b;", "}"),
                "z.h": _src("#ifndef H_H", "#define H_H", "extern unsigned char g_a;   /* header a */", "extern unsigned char g_b;   /* header b */", "#endif"),
            },
        )
        gim = sec["globals_info_map"]
        assert gim["g_a"]["desc"] == "defined here"
        assert gim["g_b"]["desc"] == "header b"
        # (리뷰 W3) 값은 정의 항목에 붙지만 출처는 헤더 — 출처 필드로 구분한다.
        assert gim["g_b"]["desc_source"] == "header_decl"
        assert "desc_source" not in gim["g_a"]

    @pytest.mark.parametrize("c_name,h_name", [("a.c", "z.h"), ("z.c", "a.h")])
    def test_global_data_listing_names_the_definition_file_once(self, tmp_path, c_name, h_name):
        # (리뷰 C1) 두 번째 소비 루프 — `global_data` 에 같은 이름이 두 번 서거나 헤더로 귀속되면 상한 240 안에서 진짜 전역이 밀려난다.
        sec = _sections(
            tmp_path,
            {
                c_name: _src("unsigned char g_val = 7U;", "void use(void)", "{", "    g_val = 1U;", "}"),
                h_name: _src("#ifndef H_H", "#define H_H", "extern unsigned char g_val;", "#endif"),
            },
        )
        entries = [ln for ln in sec["global_data"].splitlines() if ln.startswith("g_val")]
        assert entries == [f"g_val [{c_name}]"]

    def test_header_only_extern_is_listed_once(self, tmp_path):
        sec = _sections(
            tmp_path,
            {
                "a.h": _src("#ifndef A_H", "extern unsigned char g_lib;", "#endif"),
                "b.h": _src("#ifndef B_H", "extern unsigned char g_lib;", "#endif"),
                "c.c": _src('#include "a.h"', "void use(void)", "{", "    g_lib = 1U;", "}"),
            },
        )
        entries = [ln for ln in sec["global_data"].splitlines() if ln.startswith("g_lib")]
        assert len(entries) == 1

    def test_same_static_name_in_two_c_files_is_reported(self, tmp_path):
        # (리뷰 W2) 이름 키 맵은 한쪽만 남긴다(last-wins, 원래 한계) — 동작은 두고 충돌을 공시한다.
        sec = _sections(
            tmp_path,
            {
                "a.c": _src("static unsigned char u8s_Buf[4];", "void fa(void)", "{", "    u8s_Buf[0] = 1U;", "}"),
                "b.c": _src("#ifdef X", "static unsigned char u8s_Buf[8];", "#endif", "void fb(void)", "{", "    u8s_Buf[1] = 1U;", "}"),
            },
        )
        # 후보 순서는 텍스트 스캔이 마지막으로 본 파일이 앞이라 순회 순서에 달려 있다 — 집합으로 단언.
        # (R66 N76) 값은 `{files, kept, differs}` — 남는 쪽은 규칙(루트 순서 → 경로순)이라 같은 루트면 `a.c`.
        coll = sec["globals_scan"]["definition_collisions"]
        assert {k: sorted(f.rsplit("/", 1)[-1] for f in v["files"]) for k, v in coll.items()} == {"u8s_Buf": ["a.c", "b.c"]}
        assert coll["u8s_Buf"]["kept"].endswith("/a.c")
        assert coll["u8s_Buf"]["differs"] == ["array"]
        # 경로는 `r<루트>:상위폴더/파일` — APP·FBL 두 루트의 같은 파일명(`EEPROM.c`)이 구분돼야 한다.
        assert all("/" in f and f.startswith("r0:") for f in coll["u8s_Buf"]["files"])

    def test_name_only_rows_carry_the_extern_flag(self, tmp_path):
        # 이름-only 행(`_extract_globals` 산출)에도 표지가 없으면 소비자가 그 행의 file(헤더)로 귀속시킨다.
        (tmp_path / "z.h").write_text(_src("#ifndef H_H", "extern unsigned char g_e;", "#endif"), encoding="utf-8")
        (tmp_path / "a.c").write_text(_src("unsigned char g_d;"), encoding="utf-8")
        rows = [g for g in cp.parse_c_project(str(tmp_path))["globals_detailed"] if g["name"] in ("g_e", "g_d")]
        assert rows and all("is_extern" in g for g in rows)
        assert {g["is_extern"] for g in rows if g["name"] == "g_e"} == {"true"}
        assert {g["is_extern"] for g in rows if g["name"] == "g_d"} == {"false"}

    def test_header_only_extern_still_becomes_a_global(self, tmp_path):
        # 정의가 스캔 범위 밖(라이브러리)인 extern — 항목이 없으면 만든다(교차 파일 전역이 서야 시험 입력이 선다).
        sec = _sections(
            tmp_path,
            {
                "z.h": _src("#ifndef H_H", "extern unsigned char g_lib;", "#endif"),
                "a.c": _src('#include "z.h"', "void use(void)", "{", "    g_lib = 1U;", "}"),
            },
        )
        assert sec["globals_info_map"]["g_lib"]["type"] == "unsigned char"
        assert any("g_lib" in str(x) for x in _fn(sec, "use")["globals_global"])


class TestCacheSchemaMoved:
    def test_schema_version_is_past_v19(self):
        from backend.helpers.uds import _SOURCE_SECTIONS_SCHEMA_VERSION as ver

        assert int(ver.lstrip("v")) >= 20
