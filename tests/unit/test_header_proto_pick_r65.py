"""(R65 N74) 헤더 프로토타입은 **이 정의의** 헤더에서 — 이름 first-wins 가 아니다.

옛 `_header_proto_map` 은 `name → 먼저 읽힌 헤더의 프로토타입` 이었다. 같은 이름의 함수가 APP/FBL 두 트리에 따로 있으면
(실측 충돌 이름 KJPDS02 14 · PDS64 11) 두 정의가 한 프로토타입을 나눠 가졌고, 어느 헤더가 먼저인지는 파일 열거 순서
(local `os.walk` 와 cloudium 워커 목록이 다르다)가 정했다. 실측(HEAD 페이로드):
- `lin_lld_sci.c:lin_lld_sci_init(l_ifc_handle iii)` 이 부트로더 `Comms.h` 의 `(void)` 를 달고 있었다(KJPDS02·PDS64 각 1).
  LIN 헤더는 verify=X 계층이라 텍스트 루프가 읽지도 않으므로 다른 트리의 같은 이름이 유일한 후보였다.
- PDS64 FBL `EEPROM_GetByte(const EEPROM_TAddress …)` 가 APP 헤더의 `const` 없는 프로토타입을 달고 있었다.
- 부수: 구조체 멤버 정규식이 두 단어 이상 타입(`unsigned long long bitcount`)을 못 읽어 `SHA256_CTX.bitcount` 가 빠졌다.

규칙은 `pick_header_prototype` 한 곳: static 은 정의 · 같은 루트만 · 경로 최장 공유 · 동률은 경로순 · 인자 수 불일치 제외 ·
남은 후보가 서로 다르면 정의. 정의를 지킨 이유는 `prototype_scan` 으로 공시한다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from report_gen.source_parser import (
    extract_struct_member_types,
    pick_header_prototype,
    prototype_param_count,
    resolve_struct_member,
)
from report_gen.uds_generator import generate_uds_source_sections

USER = "hbrnd3@hyunbo.com"


def _src(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def _fn(sec: dict, name: str, file_part: str) -> dict:
    rows = [v for v in sec["function_details"].values() if v["name"] == name and file_part in str(v["file"]).replace("\\", "/")]
    assert len(rows) == 1, rows
    return rows[0]


class TestParamCount:
    @pytest.mark.parametrize(
        "sig,n",
        [
            ("void f(void)", 0),
            ("void f()", -1),   # 인자 미지정 — 0개가 아니라 모름(리뷰 W5)
            ("U8 f( U8 a, U8 *b )", 2),
            ("void f(void (*cb)(int, int), U8 x)", 2),
            ("static void f(U8 a)", 1),
            ("U8 f(U8 arr[2], U8 b)", 2),
            ("no_parens_here", -1),
        ],
    )
    def test_counts(self, sig, n):
        assert prototype_param_count(sig) == n


ROOTS = ["C:/proj/app", "C:/proj/fbl"]
APP_DEF = "C:/proj/app/Sources/Comms/Comms.c"


def _c(file: str, sig: str) -> dict:
    return {"file": file, "sig": sig}


class TestPickHeaderPrototype:
    def test_no_candidates_keeps_definition(self):
        assert pick_header_prototype([], APP_DEF, ROOTS, "void f(U8 a)") == ("void f(U8 a)", "definition:no_header")

    def test_static_function_never_takes_a_header(self):
        cands = [_c("C:/proj/app/Sources/Comms/Comms.h", "void f( U8 hdr )")]
        assert pick_header_prototype(cands, APP_DEF, ROOTS, "void f(U8 a)", is_static=True) == ("void f(U8 a)", "definition:static")

    def test_header_only_in_the_other_root_is_not_mine(self):
        # 실측의 본체 — LIN 정의의 유일한 후보가 부트로더 Comms.h 였다.
        cands = [_c("C:/proj/fbl/Sources/Comms/Comms.h", "void lin_lld_sci_init( void )")]
        sig, src = pick_header_prototype(cands, "C:/proj/app/Sources/LIN/bsp/lin_lld_sci.c", ROOTS, "void lin_lld_sci_init(l_ifc_handle iii)")
        assert (sig, src) == ("void lin_lld_sci_init(l_ifc_handle iii)", "definition:other_root")

    def test_same_root_header_wins_over_the_twin_regardless_of_order(self):
        app = _c("C:/proj/app/Sources/Comms/Comms.h", "void twin( U8 x_app )")
        fbl = _c("C:/proj/fbl/Sources/Comms/Comms.h", "void twin( U8 y_fbl )")
        for cands in ([app, fbl], [fbl, app]):
            assert pick_header_prototype(cands, APP_DEF, ROOTS, "void twin(U8 x)") == ("void twin( U8 x_app )", "header")
            assert pick_header_prototype(cands, "C:/proj/fbl/Sources/Comms/Comms.c", ROOTS, "void twin(U8 y)") == ("void twin( U8 y_fbl )", "header")

    def test_closest_path_wins_inside_one_root(self):
        near = _c("C:/proj/app/Sources/Comms/Comms.h", "void f( U8 near_ )")
        far = _c("C:/proj/app/Include/api.h", "void f( U8 far_ )")
        assert pick_header_prototype([far, near], APP_DEF, ROOTS, "void f(U8 a)")[0] == "void f( U8 near_ )"

    def test_same_depth_different_candidates_are_a_conflict_in_either_order(self):
        # (리뷰 W3) 결과가 열거 순서에 기대지 않는다는 것을 **다른** 두 후보로 단언한다 — 정책은 "고르지 않는다".
        a = _c("C:/proj/app/Sources/Comms/a.h", "void f( U8 from_a )")
        b = _c("C:/proj/app/Sources/Comms/b.h", "void f( U8 from_b )")
        for cands in ([a, b], [b, a]):
            assert pick_header_prototype(cands, APP_DEF, ROOTS, "void f(U8 a)") == ("void f(U8 a)", "definition:conflict")

    def test_identical_candidates_at_the_same_depth_are_one_header(self):
        a = _c("C:/proj/app/Sources/Comms/a.h", "void f( U8 from_a )")
        b = _c("C:/proj/app/Sources/Comms/b.h", "void f( U8 from_a )")
        assert pick_header_prototype([b, a], APP_DEF, ROOTS, "void f(U8 a)") == ("void f( U8 from_a )", "header")

    def test_definition_outside_every_root_keeps_its_own_signature(self):
        # (리뷰 W2) `_root_index_of` 는 못 찾으면 -1 — 후보의 -1 과 "같은 루트" 가 되면 안 된다.
        cands = [_c("C:/elsewhere/x.h", "void f( U8 hdr )")]
        assert pick_header_prototype(cands, "D:/other/tree/f.c", ROOTS, "void f(U8 a)") == ("void f(U8 a)", "definition:other_root")

    def test_root_written_with_dotdot_still_matches_the_resolved_file(self):
        # (리뷰 W1, 실측 재현) cloudium 모드의 루트는 resolve 하지 않고 tree-sitter 경로는 resolve 한다 — `..` 가 섞이면 전량 other_root.
        cands = [_c("C:/proj/app/Sources/Comms/Comms.h", "void f( U8 hdr )")]
        roots = ["C:/proj/app/Sources/../", "C:/proj/fbl"]
        assert pick_header_prototype(cands, APP_DEF, roots, "void f(U8 a)") == ("void f( U8 hdr )", "header")

    def test_different_arity_is_someone_else(self):
        cands = [_c("C:/proj/app/Sources/Comms/Comms.h", "void f( void )")]
        assert pick_header_prototype(cands, APP_DEF, ROOTS, "void f(U8 a)") == ("void f(U8 a)", "definition:arity")

    def test_conflicting_same_root_candidates_are_not_picked(self):
        a = _c("C:/proj/app/Sources/Comms/a.h", "void f( U8 one )")
        b = _c("C:/proj/app/Sources/Comms/b.h", "U16 f( U8 two )")
        assert pick_header_prototype([a, b], APP_DEF, ROOTS, "void f(U8 a)") == ("void f(U8 a)", "definition:conflict")

    def test_arity_filter_runs_before_conflict(self):
        ok = _c("C:/proj/app/Sources/Comms/a.h", "void f( U8 one )")
        other = _c("C:/proj/app/Sources/Comms/b.h", "void f( void )")
        assert pick_header_prototype([other, ok], APP_DEF, ROOTS, "void f(U8 a)") == ("void f( U8 one )", "header")

    def test_macro_form_definition_does_not_trip_the_arity_guard(self):
        # 첫 구현의 회귀 — `ISR(Cpu_Interrupt) {…}` 를 tree-sitter 는 `ISR` 선언자·인자 1개로 읽는다. 헤더 `(void)` 와 인자 수가 다르다고
        # 정의를 지키면 Prototype 이 `ISR (Cpu_Interrupt)` 가 되고 입력 칸에 `[IN] Cpu_Interrupt` 가 선다(실측 KJPDS02 15 · PDS64 14).
        cands = [_c("C:/proj/app/Sources/Comms/Cpu.h", "__interrupt void Cpu_Interrupt( void )")]
        assert pick_header_prototype(cands, "C:/proj/app/Sources/Comms/Cpu.c", ROOTS, "ISR (Cpu_Interrupt)", name="Cpu_Interrupt") == (
            "__interrupt void Cpu_Interrupt( void )", "header:macro_def")

    def test_macro_form_relaxation_needs_the_name(self):
        # 이름 없이는 매크로형을 판별할 근거가 없다 — 완화하지 않는다(리뷰 W4: 후보 하나의 모양에 기대지 않는다).
        cands = [_c("C:/proj/app/Sources/Comms/Cpu.h", "__interrupt void Cpu_Interrupt( void )")]
        assert pick_header_prototype(cands, "C:/proj/app/Sources/Comms/Cpu.c", ROOTS, "ISR (Cpu_Interrupt)")[1] == "definition:arity"

    def test_macro_form_definition_accepts_a_header_of_any_arity(self):
        # 정책 고정(리뷰 W4③): 매크로형 정의는 인자 수를 모르므로 같은 트리 헤더가 유일한 정보다 — 받되 `header:macro_def` 로 남긴다.
        cands = [_c("C:/proj/app/Sources/Comms/Cpu.h", "void Foo( U8 irq )")]
        assert pick_header_prototype(cands, "C:/proj/app/Sources/Comms/Cpu.c", ROOTS, "ISR (Foo)", name="Foo") == ("void Foo( U8 irq )", "header:macro_def")

    def test_real_definition_with_a_different_arity_is_still_rejected(self):
        # 위 완화가 진짜 불일치까지 통과시키면 안 된다 — 괄호 앞 식별자가 이름이면 인자 수를 그대로 비교한다.
        cands = [_c("C:/proj/app/Sources/Comms/Cpu.h", "void f( void )")]
        assert pick_header_prototype(cands, APP_DEF, ROOTS, "void f(U8 a)", name="f") == ("void f(U8 a)", "definition:arity")

    def test_without_roots_every_candidate_is_eligible(self):
        cands = [_c("C:/elsewhere/x.h", "void f( U8 hdr )")]
        assert pick_header_prototype(cands, APP_DEF, None, "void f(U8 a)") == ("void f( U8 hdr )", "header")


class TestEndToEnd:
    @pytest.fixture(scope="class")
    def sec(self, tmp_path_factory) -> dict:
        base: Path = tmp_path_factory.mktemp("r65")
        app = base / "app" / "Sources" / "Comms"
        lin = base / "app" / "Sources" / "LIN"
        fbl = base / "fbl" / "Sources" / "Comms"
        for d in (app, lin, fbl):
            d.mkdir(parents=True)
        (app / "Comms.h").write_text(_src("void twin(U8 x_app);", "void solo(U8 a_hdr);", "__interrupt void Cpu_Interrupt(void);"), encoding="utf-8")
        (app / "Comms.c").write_text(
            _src(
                "void twin(U8 x)", "{", "    (void)x;", "}", "void solo(U8 a)", "{", "    (void)a;", "}",
                "ISR(Cpu_Interrupt)", "{", "    (void)0;", "}", "static void helper(U8 h)", "{", "    (void)h;", "}",
            ),
            encoding="utf-8",
        )
        (lin / "lin_lld.c").write_text(_src("void lin_only(l_handle iii)", "{", "    (void)iii;", "}"), encoding="utf-8")
        (fbl / "Comms.h").write_text(_src("void twin(U8 y_fbl);", "void lin_only(void);"), encoding="utf-8")
        (fbl / "Comms.c").write_text(_src("void twin(U8 y)", "{", "    (void)y;", "}"), encoding="utf-8")
        return generate_uds_source_sections(f"{base / 'app'};{base / 'fbl'}", preprocess=False)

    def test_each_twin_carries_its_own_header_prototype(self, sec):
        assert "x_app" in _fn(sec, "twin", "/app/")["prototype"]
        assert "y_fbl" in _fn(sec, "twin", "/fbl/")["prototype"]

    def test_header_from_the_other_tree_does_not_override_a_definition(self, sec):
        # 정의 시그니처는 tree-sitter 판 그대로(`normalize_prototype_text` — 괄호 안 여백 없음). 헤더 판(`f( a )`)과 표기가 다른 것은
        # 이전부터의 관례(static 함수 전부가 이 형태)라 이 라운드는 손대지 않는다.
        assert _fn(sec, "lin_only", "/app/")["prototype"] == "void lin_only(l_handle iii)"

    def test_single_root_header_still_wins(self, sec):
        assert "a_hdr" in _fn(sec, "solo", "/app/")["prototype"]

    def test_isr_macro_definition_takes_the_header_prototype(self, sec):
        row = _fn(sec, "Cpu_Interrupt", "/app/")
        assert row["prototype"] == "__interrupt void Cpu_Interrupt( void )"
        assert row["inputs"] == []

    def test_prototype_scan_discloses_what_was_kept(self, sec):
        scan = sec["prototype_scan"]
        # 전체 dict 동등 — 라벨 하나가 바뀌거나 빠져도 보인다(리뷰 뮤테이션 후보 2·3).
        assert scan["counts"] == {"header": 3, "header:macro_def": 1, "definition:static": 1, "definition:other_root": 1}
        assert scan["definition_kept"] == {"definition:other_root": [{"name": "lin_only", "file": "LIN/lin_lld.c"}]}
        assert _fn(sec, "helper", "/app/")["prototype"] == "static void helper(U8 h)"

    def test_gate_reports_only_the_suspicious_reasons(self):
        pytest.importorskip("fastapi")
        from backend.helpers import uds as U
        from report_gen.gen_issues import IssueCollector

        c = IssueCollector()
        U._note_source_caps(c, {"prototype_scan": {"counts": {"header": 10, "definition:static": 5, "definition:no_header": 3, "definition:other_root": 1}, "definition_kept": {}}})
        assert [i["code"] for i in c.as_list()] == []
        c = IssueCollector()
        U._note_source_caps(c, {"prototype_scan": {
            "counts": {"header": 2, "definition:arity": 1, "definition:conflict": 2, "definition:other_root": 7},
            "definition_kept": {"definition:arity": [{"name": "f", "file": "a/b.c"}], "definition:other_root": [{"name": "g", "file": "c/d.c"}]},
        }})
        items = {i["code"]: i for i in c.as_list()}
        assert set(items) == {"prototype_header_mismatch", "prototype_roots_mismatch"}
        assert items["prototype_header_mismatch"]["facts"]["arity"] == [{"name": "f", "file": "a/b.c"}]
        assert items["prototype_roots_mismatch"]["facts"] == {"header": 2, "other_root": 7, "sample": [{"name": "g", "file": "c/d.c"}]}


class TestMultiWordMemberTypes:
    def test_unsigned_long_long_member_is_read(self):
        t = extract_struct_member_types(_src("typedef struct {", "    unsigned long long bitcount;", "    U8 data[64];", "} SHA256_CTX;"))
        assert t["SHA256_CTX"]["bitcount"] == {"type": "unsigned long long", "array": "", "bits": "", "desc": "", "parent": "struct"}
        assert t["SHA256_CTX"]["data"]["array"] == "[64]"

    def test_struct_tag_member_resolves_by_its_last_word(self):
        t = extract_struct_member_types(_src("typedef struct {", "    struct inner_t inner;", "} outer_t;", "typedef struct {", "    U8 v;", "} inner_t;"))
        assert t["outer_t"]["inner"]["type"] == "struct inner_t"
        assert resolve_struct_member(t, "outer_t", "inner.v")["type"] == "U8"

    def test_single_word_members_unchanged(self):
        t = extract_struct_member_types(_src("typedef union {", "    U8 Byte;", "    struct {", "        U8 READY :1;", "    } Bits;", "} R;"))
        assert t["R"]["Byte"]["type"] == "U8"
        assert t["R"]["Bits.READY"]["bits"] == "1"


class TestCacheSchemaMoved:
    def test_schema_version_is_past_v20(self):
        from backend.helpers.uds import _SOURCE_SECTIONS_SCHEMA_VERSION as ver

        assert int(ver.lstrip("v")) >= 21
