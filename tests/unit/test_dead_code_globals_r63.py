"""R63 N70 — 죽은 `#if 0` 분기는 **함수만이 아니라** 그 루프의 모든 수집기에서 가려야 한다.

R62 는 함수 정의만 가렸다. 실측(KJPDS02 두 루트 178 파일 · PDS64 두 루트 127 파일):
- 죽은 구간에만 있는 전역 6 / 4개(`CRC32.c:crcTable` · `Comms.c:u8flashErased` …)가 전역 표에 실재 변수로 있었다(정본 UDS 엔 0개)
- 죽은 선언의 초기값이 산 전역의 Reset 근거가 됐다(`u8T1_timer` — `= 0` 은 죽은 구간, 산 쪽은 `extern` 뿐)
- 죽은 헤더 프로토타입이 first-wins 로 산 함수의 Prototype 을 이겼다(부트로더 `Comms.h` 의 옛 `lin_checksum(unsigned char length)`
  → 앱 LIN 드라이버 `lin_checksum(l_u8 *buffer, l_u8 raw_pid)` 의 Prototype·입출력 칸이 통째로 옛 시그니처)
- ⚠ 리뷰 전제 하나는 틀렸다: tree-sitter 전역 수집(`_extract_global_decls`)은 `root.children` 만 보므로 죽은 구간을 **애초에 못 본다**(0건).
"""
from __future__ import annotations

from pathlib import Path

from report_gen.uds_generator import generate_uds_source_sections
from workflow.code_parser import c_parser as cp

NL = "\n"


def _src(*lines: str) -> str:
    return NL.join(lines) + NL


def _sections(tmp_path: Path, files: dict):
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    return generate_uds_source_sections(str(tmp_path))


def _var_names(sec: dict) -> set:
    return {str(r[0]) for r in (sec["global_vars"] + sec["static_vars"])}


USER = _src("void use(void)", "{", "    g_live = 1U;", "    s_live = 2U;", "}")


class TestDeadGlobalsAreNotVariables:
    FILES = {
        "app.c": _src(
            "unsigned char g_live;",
            "static unsigned char s_live;",
            "#if 0",
            "unsigned char g_ghost = 7;",
            "static unsigned long s_ghostTable[4] = { 1, 2, 3, 4 };",
            "#endif",
            USER,
        )
    }

    def test_dead_only_globals_are_absent_everywhere(self, tmp_path):
        sec = _sections(tmp_path, self.FILES)
        names = _var_names(sec)
        assert {"g_live", "s_live"} <= names
        assert not ({"g_ghost", "s_ghostTable"} & names)
        assert not ({"g_ghost", "s_ghostTable"} & set(sec["globals_info_map"]))

    def test_the_else_branch_of_if_0_is_still_collected(self, tmp_path):
        sec = _sections(
            tmp_path,
            {"app.c": _src("#if 0", "unsigned char g_old;", "#else", "unsigned char g_new;", "#endif", "void use(void)", "{", "    g_new = 1U;", "}")},
        )
        assert "g_new" in sec["globals_info_map"] and "g_old" not in sec["globals_info_map"]

    def test_the_alternative_of_if_1_is_dead(self, tmp_path):
        sec = _sections(
            tmp_path,
            {"app.c": _src("#if 1", "unsigned char g_new;", "#else", "unsigned char g_old;", "#endif", "void use(void)", "{", "    g_new = 1U;", "}")},
        )
        assert "g_new" in sec["globals_info_map"] and "g_old" not in sec["globals_info_map"]


class TestDeadDeclarationDoesNotFeedALiveGlobal:
    def test_dead_initialiser_is_not_the_reset_evidence(self, tmp_path):
        sec = _sections(
            tmp_path,
            {
                "boot.c": _src("#if 0", "unsigned char g_timer = 5;", "#endif", "void other(void)", "{", "}"),
                "comms.c": _src("extern unsigned char g_timer;", "void tick(void)", "{", "    g_timer = 0U;", "}"),
            },
        )
        info = sec["globals_info_map"]["g_timer"]
        assert str(info.get("init") or "") == ""
        assert str(info.get("reset_source") or "") != "선언"

    def test_dead_static_declaration_does_not_make_a_live_global_static(self, tmp_path):
        sec = _sections(
            tmp_path,
            {
                "a.c": _src("#if 0", "static unsigned char g_shared;", "#endif", "void other(void)", "{", "}"),
                "b.c": _src("unsigned char g_shared;", "void use(void)", "{", "    g_shared = 1U;", "}"),
            },
        )
        assert "g_shared" in {str(r[0]) for r in sec["global_vars"]}
        assert "g_shared" not in {str(r[0]) for r in sec["static_vars"]}


class TestDeadHeaderPrototypeDoesNotWin:
    def test_live_prototype_is_the_documented_one(self, tmp_path):
        sec = _sections(
            tmp_path,
            {
                # 파일 이름순으로 죽은 쪽이 먼저 읽힌다 — first-wins 가 죽은 프로토타입을 고르던 배치.
                "a_old.h": _src("#if 0", "unsigned char checksum (unsigned char length);", "#endif"),
                "b_new.h": _src("unsigned char checksum (unsigned char *buffer, unsigned char pid);"),
                "impl.c": _src("unsigned char checksum (unsigned char *buffer, unsigned char pid)", "{", "    return buffer[0] + pid;", "}"),
            },
        )
        d = {v["name"]: v for v in sec["function_details"].values()}["checksum"]
        assert "pid" in str(d.get("prototype")) and "length" not in str(d.get("prototype"))

    def test_dead_macros_are_not_macro_rows(self, tmp_path):
        sec = _sections(
            tmp_path,
            {"cfg.h": _src("#define LIVE_SIZE 8", "#if 0", "#define GHOST_SIZE 16", "#endif"), "u.c": USER.replace("g_live", "x").replace("s_live", "y")},
        )
        names = {str(r[0]) for r in sec["macro_defs"]}
        assert "LIVE_SIZE" in names and "GHOST_SIZE" not in names


class TestDeadStructDefinitionDoesNotWin:
    def test_first_wins_picks_the_live_member_type(self, tmp_path):
        sec = _sections(
            tmp_path,
            {
                "t.h": _src(
                    "#if 0",
                    "typedef struct {", "    U32 value;", "} Rec_t;",
                    "#else",
                    "typedef struct {", "    U8 value;", "} Rec_t;",
                    "#endif",
                ),
                "u.c": _src("Rec_t g_rec;", "void use(void)", "{", "    g_rec.value = 1U;", "}"),
            },
        )
        rec = sec["struct_member_types"]["Rec_t"]["value"]
        assert str(rec.get("type")) == "U8"   # ⚠ 두 단어 타입(`unsigned long`) 멤버는 추출기가 못 읽는다(N74 관찰) — 한 단어 타입으로 잰다


class TestFunctionNameScanSkipsDeadCode:
    def test_requirement_mapping_names_exclude_dead_functions(self, tmp_path):
        from report_gen.source_parser import _scan_source_function_names

        (tmp_path / "a.c").write_text(
            _src("void alive(void)", "{", "}", "#if 0", "void ghost(void)", "{", "}", "void ghost_proto(void);", "#endif"), encoding="utf-8"
        )
        names = set(_scan_source_function_names(str(tmp_path))["names"])
        assert "alive" in names and not ({"ghost", "ghost_proto"} & names)


class TestTreeSitterGlobalsNeverSawDeadRegions:
    """리뷰 W3 의 전제("tree-sitter 쪽도 죽은 구간을 안 가린다")를 잰 결과 — 최상위 선언만 보므로 0건이다. 그 사실을 못박는다:
    누가 중첩 선언까지 훑게 고치면(N73) 죽은 구간 제외를 **같이** 넣어야 한다."""

    def test_top_level_only_collection_excludes_preproc_children(self):
        import pytest

        parser = cp._make_parser()
        if parser is None:
            pytest.skip("tree-sitter 미가용")
        data = _src("unsigned char g_live;", "#if 0", "unsigned char g_ghost;", "#endif").encode("utf-8")
        root = parser.parse(data).root_node
        assert "g_ghost" not in cp._extract_globals(root, data)
        assert "g_ghost" not in {g["name"] for g in cp._extract_global_decls(root, data)}
        assert "g_live" in cp._extract_globals(root, data)


class TestCacheSchemaMoved:
    def test_schema_version_is_past_v18(self):
        from backend.helpers.uds import _SOURCE_SECTIONS_SCHEMA_VERSION as ver

        assert int(str(ver).lstrip("v")) >= 19


class TestDisclosure:
    def test_dropped_globals_macros_prototypes_are_counted(self, tmp_path):
        sec = _sections(
            tmp_path,
            {
                "a.c": _src("#if 0", "unsigned char g_ghost;", "#define GHOST_M 1", "unsigned char ghost_fn(void);", "#endif", "void live(void)", "{", "}"),
            },
        )
        d = sec["dead_code_excluded"]
        assert (d["globals"], d["macros"], d["prototypes"]) == (1, 1, 1)
        assert list(d["decls_by_file"]["globals"].values()) == [["g_ghost"]]
        assert list(d["decls_by_file"]["prototypes"].values()) == [["ghost_fn"]]

    def test_a_commented_out_definition_inside_the_dead_block_is_not_listed(self, tmp_path):
        sec = _sections(tmp_path, {"a.c": _src("void live(void)", "{", "}", "#if 0", "/* void commented_ghost(void) { } */", "void ghost(void)", "{", "}", "#endif")})
        by_file = sec["dead_code_excluded"]["by_file"]
        assert list(by_file.values()) == [["ghost"]]


class TestReviewItems:
    """리뷰 W1·W2·W4·I1·I6 — 죽은 구간을 여전히 읽던 두 폴백과, 관측량이 어긋나 있던 가드 공백."""

    def test_static_judgement_scan_ignores_a_dead_static_declaration(self, tmp_path):
        # (W4 M1) `static_name_map` 의 유일한 관측량은 함수 detail 의 globals_static/globals_global 이다.
        sec = _sections(
            tmp_path,
            {
                "a.c": _src("#if 0", "static unsigned char g_shared;", "#endif", "void other(void)", "{", "}"),
                "b.c": _src("unsigned char g_shared;", "void use(void)", "{", "    g_shared = 1U;", "}"),
            },
        )
        f = {v["name"]: v for v in sec["function_details"].values()}["use"]
        assert any("g_shared" in str(x) for x in f.get("globals_global") or [])
        assert not any("g_shared" in str(x) for x in f.get("globals_static") or [])

    def test_header_extern_fallback_does_not_add_a_dead_extern(self, tmp_path):
        # (W4 M2) 되돌리면 `extern_added` 1 · `g_deadExtern` 이 globals_info_map 에 오른다(실험으로 도달 확인).
        sec = _sections(
            tmp_path,
            {
                "b.c": _src("unsigned char g_x;", "void use(void)", "{", "    g_x = g_deadExtern;", "}"),
                "h.h": _src("#if 0", "extern unsigned char g_deadExtern;", "#endif"),
            },
        )
        assert "g_deadExtern" not in sec["globals_info_map"]
        assert sec["globals_scan"]["extern_added"] == 0

    def test_dead_asil_tag_and_requirement_id_do_not_reach_the_live_function(self, tmp_path):
        # (I1) 하향 방향 — 산 쪽 태그는 남고 죽은 쪽 태그는 안 들어온다. 한 쌍으로 단언.
        sec = _sections(
            tmp_path,
            {
                "a.c": _src(
                    "/** @brief live", " *  @asil B", " *  REQ: SwTR_100 */", "void f(void)", "{", "}",
                    "#if 0", "/** @brief old", " *  @asil D", " *  REQ: SwTR_999 */", "void g(void)", "{", "}", "#endif",
                ),
            },
        )
        d = {v["name"]: v for v in sec["function_details"].values()}
        assert d["f"]["comment_asil"] == "B" and "g" not in d
        assert "SwTR_100" in sec["requirements"] and "SwTR_999" not in sec["requirements"]

    def test_blank_dead_code_returns_the_same_object_when_nothing_is_dead(self):
        # (I6) `_has_dead = live_raw is not raw` 는 동일성 계약에 기댄다 — 동등성 가드(R62)만으론 조용한 성능 회귀를 못 본다.
        raw = _src("unsigned char g_live;", "#ifdef X", "unsigned char g_cfg;", "#endif")
        assert cp.blank_dead_code(raw) is raw

    def test_type_fallback_skips_a_dead_declaration_that_comes_first(self, tmp_path):
        # (W1) `_infer_type_from_file` 은 첫 매치를 채택한다 — 죽은 선언이 앞에 있으면 그 타입·init 이 산 전역의 근거가 됐다.
        from report_gen.utils import _infer_type_from_file

        f = tmp_path / "x.c"
        f.write_text(_src("#if 0", "U32 g_val = 7;", "#endif", "U8 g_val;"), encoding="utf-8")
        cache: dict = {}
        assert _infer_type_from_file(str(f), "g_val", cache=cache) == ("U8", "")
        assert "g_val = 7" not in cache[str(f)]

    def test_call_fallback_does_not_read_the_dead_copy_of_a_function(self, tmp_path):
        # (W2) AST 가 호출을 못 찾은 함수는 원문 첫 매치 본문에서 호출을 긁는다 — `#if 0` 안의 옛 구현이 먼저 오면 그 호출이 Called 칸이 됐다.
        sec = _sections(
            tmp_path,
            {
                "a.c": _src(
                    "void ghost_callee(void)", "{", "}",
                    "#if 0", "void f(void)", "{", "    ghost_callee();", "}", "#endif",
                    "void f(void)", "{", "    g_x = 1U;", "}",
                    "unsigned char g_x;",
                ),
            },
        )
        f = {v["name"]: v for v in sec["function_details"].values()}["f"]
        assert "ghost_callee" not in " ".join(str(x) for x in (f.get("calls") or [])) + " ".join(sec["call_map"].get("f") or [])
