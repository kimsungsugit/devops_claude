"""배열을 **원소 단위로** 펼쳐 정본과 같은 입도로 맞추는 경로.

## 왜 (KJPDS02_PV 정본 실측, 2026-08-12)

정본 SUTS 는 배열을 원소마다 한 칸씩 적는다.

    입력 Inpt: 엔트리 6,014 중 `name[N]` **3,023 (50.3%)**
    기대 ExpR: 엔트리 5,389 중 `name[N]` **2,716 (50.4%)**
    base 134 중 **모든 unit 에서 같은 개수** 120 · 최대 원소 60
    입력 unit당 최대 **96 = 열 상한 정확히**(초과 0) · 기대 최대 **84 = 상한**

우리는 그 자리에 base 이름 한 칸만 냈다 — 결손이 아니라 **입도 차이**다:

    s_sha256_accumulate_state::au32_State   정본 8원소  ← 우리 ['au32_State']
    g_DrvIn_Main_Reset::u16s_AdcBuffer      정본 9원소  ← 우리 ['u16s_AdcBuffer']

(unit, base) 쌍 282 중 **181(64.2%)** 은 이미 이름을 잡고 있었다. 크기만 있으면 맞는다.

## 예산 정책

정본은 입력 96 · 기대 84 둘 다 **최대가 상한과 정확히 일치**한다(초과 0) — 즉 정본
자신이 열 수에 묶여 있다. 우리도 넘길 수 없으므로, 넘칠 배열은 **펼치지 않고 base
이름을 그대로 둔다**. 원소를 잘라 넣으면 두 가지가 동시에 망가진다:

  1. "이 배열은 앞 k칸만 시험한다"는 **없는 사실**을 문서에 적게 된다
  2. 뒤에 오는 **다른 변수**가 통째로 밀려나 사라진다

변수는 하나도 잃지 않고 입도만 낮추는 쪽이 정직하다. 건너뛴 것은
`array_expansion.skipped` 로 보고하고 로그는 WARNING 으로 올린다.
"""
from __future__ import annotations

import pytest

from generators.suts import _array_sizes, _expand_array_entries, collect_unit_functions


def _unit(name="Fn", *, inputs=None, outputs=None, gg=None, gs=None, proto="void Fn(void)"):
    return {
        "a": {
            "id": "SwUFn_0101",
            "name": name,
            "prototype": proto,
            "inputs": list(inputs or []),
            "outputs": list(outputs or []),
            "globals_global": list(gg or []),
            "globals_static": list(gs or []),
            "logic_flow": [],
        }
    }


class TestArraySizes:
    def test_size_tail_is_read(self):
        assert _array_sizes(["[IN] u16s_AdcBuffer (size: 9)"]) == {"u16s_AdcBuffer": 9}

    def test_param_declaration_dim_is_read(self):
        """파라미터 표시엔 차원이 `buf[8]` 로 이미 들어 있다 — 이 필드에선 늘 선언 크기다."""
        assert _array_sizes(["[IN] U8 buf[8]"]) == {"buf": 8}

    def test_size_survives_other_tails(self):
        got = _array_sizes(["[IN] u8s_Buf (size: 4) (idx: i) (range: 0x0 ~ 0xFF)"])
        assert got == {"u8s_Buf": 4}

    @pytest.mark.parametrize("raw", ["[IN] g_Plain", "[IN] u8s_Buf (size: 1)", "[IN] u8s_Buf (size: 0)"])
    def test_non_arrays_and_single_element_are_ignored(self, raw):
        """크기 1 을 펼치면 `x[0]` 이 되어 정본의 평범한 이름과 어긋난다."""
        assert _array_sizes([raw]) == {}

    def test_indirect_tags_are_stripped(self):
        assert _array_sizes(["[INDIRECT2] u8s_Buf (size: 3)"]) == {"u8s_Buf": 3}


class TestExpansion:
    def test_elements_are_zero_based_and_contiguous(self):
        out, info = _expand_array_entries(["a"], {"a": 3}, 96)
        assert out == ["a[0]", "a[1]", "a[2]"]
        assert info["expanded"] == ["a"] and info["skipped"] == []

    def test_non_array_names_pass_through(self):
        out, _ = _expand_array_entries(["x", "y"], {}, 96)
        assert out == ["x", "y"]

    def test_order_is_preserved(self):
        out, _ = _expand_array_entries(["x", "a", "y"], {"a": 2}, 96)
        assert out == ["x", "a[0]", "a[1]", "y"]

    def test_budget_overflow_keeps_the_base_name(self):
        """⚠ 예산이 모자라면 **자르지 않고 안 펼친다** — 변수를 잃지 않는다."""
        out, info = _expand_array_entries(["big"], {"big": 60}, 10)
        assert out == ["big"]
        assert info["skipped"] == [{"name": "big", "elements": 60, "remaining": 10}]

    def test_later_variables_are_not_crowded_out(self):
        """확장이 뒤 변수를 밀어내면 그 변수가 캡에서 잘려 **통째로 사라진다**."""
        out, info = _expand_array_entries(["big", "keep_me"], {"big": 8}, 8)
        assert "keep_me" in out, f"뒤 변수가 밀려났다: {out}"
        assert info["skipped"] and info["skipped"][0]["name"] == "big"

    def test_expansion_uses_the_budget_when_it_fits_exactly(self):
        out, info = _expand_array_entries(["a"], {"a": 4}, 4)
        assert out == ["a[0]", "a[1]", "a[2]", "a[3]"] and not info["skipped"]


class TestEndToEnd:
    def test_global_array_becomes_elements(self):
        u = collect_unit_functions(_unit(gg=["[IN] u16s_AdcBuffer (size: 9)"]), sds_map={})[0]
        assert u["input_vars"] == [f"u16s_AdcBuffer[{i}]" for i in range(9)]

    def test_param_array_becomes_elements(self):
        u = collect_unit_functions(
            _unit(inputs=["[IN] U8 buf[8]"], proto="void Fn(U8 buf[8])"), sds_map={}
        )[0]
        assert u["input_vars"] == [f"buf[{i}]" for i in range(8)]

    def test_expected_column_expands_too(self):
        """⚠ 한쪽만 펼치면 같은 행에서 같은 변수가 다른 이름으로 두 번 나온다.

        실측: 같은 unit 의 입력·기대 **양쪽에** 펼쳐진 배열이 120건이다.
        """
        u = collect_unit_functions(_unit(gg=["[OUT] u8s_Log (size: 3)"]), sds_map={})[0]
        assert u["output_vars"][:3] == ["u8s_Log[0]", "u8s_Log[1]", "u8s_Log[2]"]

    def test_plain_globals_are_untouched(self):
        """확장이 평범한 전역을 건드리면 회귀다."""
        u = collect_unit_functions(_unit(gg=["[IN] g_MotorState"]), sds_map={})[0]
        assert "g_MotorState" in u["input_vars"]

    def test_skip_is_reported_not_silent(self):
        """예산 부족으로 못 펼친 것은 산출물이 **말해야** 한다.

        조용하면 "정본과 입도가 다르다"의 원인을 짚을 수 없다.
        """
        u = collect_unit_functions(_unit(gg=["[IN] huge (size: 200)"]), sds_map={})[0]
        assert u["input_vars"] == ["huge"]
        skipped = u["array_expansion"]["input"]["skipped"]
        assert skipped and skipped[0]["name"] == "huge" and skipped[0]["elements"] == 200

    def test_never_exceeds_the_column_budget(self):
        """96열을 넘기면 뒤가 캡에서 잘려 변수가 사라진다."""
        gg = [f"[IN] arr{i} (size: 30)" for i in range(5)]
        u = collect_unit_functions(_unit(gg=gg), sds_map={})[0]
        assert len(u["input_vars"]) <= 96
        # 다섯 배열의 base 이름이 하나도 사라지지 않아야 한다
        roots = {v.split("[")[0] for v in u["input_vars"]}
        assert {f"arr{i}" for i in range(5)} <= roots


_SRC_C = """
typedef struct { U8 f; } S_T;
static U8 u8s_DataBuffer[8];
static S_T s_Buf[4];
static U8 u8s_Unk[UNKNOWN_MAX];
static U8 u8s_Sized[MAX_LEN];
static U8 u8s_Plain;
void g_ArrayUser( void )
{
    U8 u8t_i;
    u8t_i = u8s_DataBuffer[2];
    s_Buf->f = u8t_i;
    u8t_i = u8s_Unk[0];
    u8t_i = u8s_Sized[1];
    u8s_Plain = u8t_i;
    return;
}
"""
_SRC_H = "#define MAX_LEN 6\n"


@pytest.fixture(scope="module")
def array_project(tmp_path_factory):
    """**생산자 경로**(실제 파싱)를 지나는 종단 픽스처.

    ⚠ 소비처(`collect_unit_functions`)만 문자열로 테스트하면 생산자
      (`uds_generator` → `_format_param_entry`)의 결함이 통째로 생존한다 —
      실제로 뮤테이션 3건이 그렇게 살아남았다.

    ⚠ **resolver 를 직접 local 로 고정한다.** conftest 의 `_default_local_resolver`
      는 함수 스코프 autouse 라, **모듈 스코프 픽스처는 그보다 먼저 만들어진다**
      (pytest 는 session→module→function 순으로 셋업한다). 그래서 이 픽스처는
      머신의 영속 설정(`config/file_mode.json` = cloudium)을 그대로 타고,
      Cloudium worker 로 파일을 읽으러 간다 — xdist 로 18개 워커가 동시에
      두드리면 그 IPC 가 간헐적으로 실패해 픽스처가 ERROR 로 죽는다
      (전량 실행에서만, 단독으론 통과 = 재현이 어렵다).
    """
    from backend.services import file_resolver as fr
    from report_gen.uds_generator import generate_uds_source_sections

    d = tmp_path_factory.mktemp("array_src")
    (d / "cfg.h").write_text(_SRC_H, encoding="utf-8")
    (d / "m.c").write_text(_SRC_C, encoding="utf-8")
    _saved = fr._resolver
    fr._resolver = fr.LocalFileResolver()
    try:
        return generate_uds_source_sections(str(d), preprocess=False)
    finally:
        # ⚠ 원래 값 **복원**. 특정 값으로 고정하고 가면 다음 테스트가 그 값을 물려받는다
        #   (`file_resolver._resolver` 누설로 단독 16건이 깨졌던 전례 — 커밋 584833e).
        fr._resolver = _saved


def _globals_of(project, fn_name="g_ArrayUser"):
    for info in (project.get("function_details") or {}).values():
        if isinstance(info, dict) and info.get("name") == fn_name:
            return list(info.get("globals_global") or []) + list(info.get("globals_static") or [])
    pytest.fail(f"{fn_name} 를 파싱하지 못했다 — 이 테스트의 전제가 깨졌다")


class TestProducerEmitsSize:
    def test_declared_array_carries_its_size(self, array_project):
        """전역 표시에 `(size: N)` 이 실려야 소비처가 펼칠 수 있다."""
        entry = next(g for g in _globals_of(array_project) if "u8s_DataBuffer" in g)
        assert "(size: 8)" in entry, entry

    def test_member_path_does_not_carry_a_size(self, array_project):
        """⚠ `s_Buf->f` 는 배열이 아니라 그 배열 한 칸의 **필드**다.

        여기 크기를 붙이면 소비처가 `s_Buf->f[0..3]` 이라는 없는 이름을 만든다.
        """
        members = [g for g in _globals_of(array_project) if "->" in g or "." in g.split("] ")[-1]]
        for g in members:
            assert "(size:" not in g, f"멤버 경로에 크기가 붙었다: {g}"

    def test_unresolved_macro_size_is_not_emitted(self, array_project):
        """`[UNKNOWN_MAX]` 는 개수를 **모르는** 것이다 — 실으면 크기처럼 보이는 문자열만 남는다."""
        entry = next((g for g in _globals_of(array_project) if "u8s_Unk" in g), "")
        assert entry and "(size:" not in entry, entry

    def test_macro_size_is_resolved_to_a_number(self, array_project):
        """`[MAX_LEN]` 은 매크로가 접히므로 숫자로 실려야 한다."""
        entry = next((g for g in _globals_of(array_project) if "u8s_Sized" in g), "")
        assert "(size: 6)" in entry, entry

    def test_non_array_global_has_no_size(self, array_project):
        entry = next((g for g in _globals_of(array_project) if "u8s_Plain" in g), "")
        assert entry and "(size:" not in entry, entry
