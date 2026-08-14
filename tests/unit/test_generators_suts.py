# tests/unit/test_generators_suts.py
"""Unit tests for generators.suts core functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from generators.suts import (
    collect_unit_functions,
    determine_gen_method,
    determine_test_method,
    generate_sequences,
    generate_suts_xlsm,
    get_boundary_values,
    infer_variable_type,
)


class TestCollectUnitFunctions:
    @pytest.fixture()
    def sample_function_details(self):
        return {
            "SwUFn_001": {
                "id": "SwUFn_001",
                "name": "S_Motor_Init",
                "prototype": "void S_Motor_Init(U8 mode)",
                "inputs": ["[IN] U8 mode"],
                "outputs": [],
                "globals_global": ["g_MotorState"],
                "globals_static": ["s_MotorFlag"],
                "logic_flow": [],
            },
        }

    def test_basic_collection(self, sample_function_details):
        units = collect_unit_functions(sample_function_details)
        assert len(units) == 1
        assert units[0]["name"] == "S_Motor_Init"
        assert units[0]["fid"] == "SwUFn_001"

    def test_empty_details(self):
        units = collect_unit_functions({})
        assert units == []

    def test_ignores_invalid_entries(self):
        details = {"SwUFn_001": "not_a_dict"}
        units = collect_unit_functions(details)
        assert units == []

    def test_ignores_nameless(self):
        details = {"SwUFn_001": {"id": "SwUFn_001", "name": ""}}
        units = collect_unit_functions(details)
        assert units == []

    def test_fills_asil_from_sds_when_missing(self, monkeypatch):
        details = {
            "SwUFn_001": {
                "id": "SwUFn_001",
                "name": "S_Motor_Init",
                "prototype": "void S_Motor_Init(void)",
                "module_name": "MotorCtrl_PDS",
                "asil": "TBD",
            }
        }

        monkeypatch.setattr(
            "generators.suts._load_default_sds_map",
            lambda: {
                "motor control": {
                    "asil": "A",
                    "related": "SwTR_0101",
                    "description": "Motor control logic",
                }
            },
        )

        units = collect_unit_functions(details)

        assert units[0]["asil"] == "A"


class TestGlobalDirectionTags:
    """전역 변수의 방향 태그가 입력/기대결과 열로 어떻게 갈리는지.

    ⚠ 실제로 겪은 결함: 판정이 `"[IN]" in tag` 였는데 `"[IN]" in "[INOUT] x"` 도
      `"[OUT]" in "[INOUT] x"` 도 **둘 다 False** 다. 그래서 파서가 가장 정확하게 아는
      `[INOUT]` 이 통째로 "태그 없음" 취급돼 프리픽스 휴리스틱으로 떨어졌고, 대부분
      출력 전용이 됐다. 실측(KJPDS02 750함수): [INOUT] 305건 · 그 결과 입력 0개 TC 338건.
      `LinSend` 가 `[INOUT] s_LinFrame …` 를 받고도 입력이 비었다.
    """

    @staticmethod
    def _unit(*globals_static, prototype="void Fn_Under_Test(void)", **kw):
        details = {
            "SwUFn_0101": {
                "id": "SwUFn_0101",
                "name": "Fn_Under_Test",
                "prototype": prototype,
                "inputs": [],
                "outputs": [],
                "globals_global": list(kw.get("globals_global") or []),
                "globals_static": list(globals_static),
                "logic_flow": [],
            }
        }
        return collect_unit_functions(details)[0]

    def test_inout_lands_in_both_columns(self):
        u = self._unit("[INOUT] s_LinFrame")
        assert "s_LinFrame" in u["input_vars"], "[INOUT] 은 읽기이기도 하다 — 입력에 있어야 한다"
        assert "s_LinFrame" in u["output_vars"], "[INOUT] 은 쓰기이기도 하다"

    def test_in_tag_is_input_only(self):
        u = self._unit("[IN] s_LinFrame")
        assert u["input_vars"] == ["s_LinFrame"]
        assert "s_LinFrame" not in u["output_vars"]

    def test_out_tag_is_output_only(self):
        u = self._unit("[OUT] s_LinFrame")
        assert "s_LinFrame" not in u["input_vars"]
        assert "s_LinFrame" in u["output_vars"]

    def test_indirect_is_not_promoted_to_input(self):
        """간접 접근은 시험이 직접 넣을 수 있는 입력이 아니다 — 현행 의미 유지."""
        u = self._unit("[INDIRECT] s_LinFrame.LIN_PID")
        assert "s_LinFrame.LIN_PID" not in u["input_vars"]

    @pytest.mark.parametrize("name", ["_SPI0SR.Bits.SPIF", "g_MotorState", "r_SCI0CR2.Byte"])
    def test_two_hop_indirect_is_not_looser_than_one_hop(self, name):
        """⚠ **같은 함정의 재발.** 2홉 전파는 `[INDIRECT2]` 로 태그되는데
        `_DIR_TAG_PAT` 이 `INDIRECT` 만 알면 매칭에 실패해 "태그 없음" 으로 떨어지고,
        프리픽스 휴리스틱이 `_`·`g_`·`r_` 로 시작하는 이름을 **입력으로 올린다**.

        결과는 뒤집힌 판정이다 — 1홉은 입력에서 빼면서 2홉(= 더 먼 증거)은 넣는다.
        실측(2026-08-12, KJPDS02): SPI 레지스터가 인식되자 `g_DrvIn_DRV8706SQ_Init` ·
        `..._Left` · `s_IIM20670_Init` 3건이 정본엔 입력 0개인데 `_SPI0SR` 계열을
        입력으로 냈다(읽기는 2홉 아래 `u16g_DrvIn_SPI_DataTransfer` 안에 있다).
        """
        one = self._unit(f"[INDIRECT] {name}")
        two = self._unit(f"[INDIRECT2] {name}")
        assert name not in one["input_vars"], "1홉 간접이 입력이면 이 테스트의 전제가 깨졌다"
        assert name not in two["input_vars"], (
            f"2홉 간접이 입력으로 올라갔다: {two['input_vars']} "
            "— 증거가 멀수록 판정이 느슨해지면 안 된다"
        )

    def test_two_hop_tag_is_recognized_by_the_single_source(self):
        """판정 복제 방지 — 태그 어휘는 `dir_tag` 한 곳에서만 정의한다."""
        from generators.suts import dir_tag

        assert dir_tag("[INDIRECT2] _SPI0SR") == "INDIRECT2"
        assert dir_tag("[INDIRECT] _SPI0SR") == "INDIRECT"
        assert dir_tag("[INOUT] x") == "INOUT"
        assert dir_tag("_SPI0SR") == ""

    def test_untagged_keeps_prefix_heuristic(self):
        """무태그 529건은 기존 휴리스틱 그대로 — 태그 수정이 여길 건드리면 회귀다."""
        assert self._unit("s_LinFrame")["output_vars"] == ["s_LinFrame"]
        assert self._unit("s_LinFrame")["input_vars"] == []
        # g_ 접두사 전역은 읽기·쓰기 둘 다로 보던 기존 판정
        u = self._unit(globals_global=["g_MotorState"])
        assert "g_MotorState" in u["input_vars"] and "g_MotorState" in u["output_vars"]

    def test_keyword_fallback_survives(self):
        """READ/WRITE 폴백 — 태그를 안 붙이는 생산자용. 지우지 말 것.

        ⚠ 현재 저장소에 이 표기를 내는 생산자는 **없다**(방어용 잔존). 그래서 이 테스트는
          "동작한다"가 아니라 "지웠는지"를 지킨다. 이름은 마지막 토큰에서 뽑히므로
          (`_clean_global_name`) 키워드가 앞에 오는 형태여야 성립한다.
        """
        assert "s_LinFrame" in self._unit("READ s_LinFrame")["input_vars"]
        assert "s_LinFrame" in self._unit("WRITE s_LinFrame")["output_vars"]

    def test_member_path_is_kept_verbatim(self):
        """`s_LinFrame.LIN_data` 를 base 로 접으면 정본과 다른 이름이 된다."""
        u = self._unit("[INOUT] s_LinFrame.LIN_data")
        assert "s_LinFrame.LIN_data" in u["input_vars"]


class TestKeywordFallbackIsAnchored:
    """⚠ **substring 매칭의 세 번째 재발.**

    폴백이 엔트리 **전체**를 `str(g).upper()` 로 훑었다:

        if any(k in tag for k in ["READ", "RHS"]): role_in = True

    그래서 **변수 이름 안의 글자**가 방향을 정한다 — `_ADC0STS.Bits.READY` 의 `READY`
    안에 `READ` 가 들어 있다. 간접 억제(`is_indirect`)는 `if not role_in and not
    role_out:` 블록 **안에만** 있으므로 통째로 건너뛰고, `[INDIRECT]` 가 입력이 된다.

    실측(2026-08-13, KJPDS02 전역 엔트리 6,711): 이름 안에 키워드가 든 엔트리 **93건**
    (63 unit · 변수 18종). `[INDIRECT*]` 27건은 억제를 건너뛰고, `[OUT]`+READ ·
    `[IN]`+WRITE 29건은 파서 태그를 **뒤집어** 같은 이름이 양쪽 열에 실렸다.
    반대로 **선두 토큰 키워드는 0건**이라 앵커로 좁혀도 잃는 게 없다.

    같은 부류를 이 저장소가 이미 두 번 겪었다: `"[IN]" in "[INOUT] x"`(A-1) ·
    `[INDIRECT2]` 미인식. 판정을 substring 으로 하면 **데이터가 판정을 바꾼다**.

    ⚠ 아래 태그된 케이스들은 앵커(`^\\s*`)·토큰경계(`\\b`) **둘 중 하나만** 있어도
      통과한다(태그된 엔트리는 `[` 로 시작하니 앵커에 안 걸리고, 이 프로젝트 이름들은
      `_`·`Y` 가 뒤따라 `\\b` 에도 안 걸린다). 그래서 두 축을 **따로 겨누는** 테스트를
      아래 `test_anchor_…` · `test_…whole_token…` 으로 각각 둔다 — 안 그러면 한쪽을
      지워도 전부 초록이다.
    """

    _unit = staticmethod(TestGlobalDirectionTags._unit)

    @pytest.mark.parametrize(
        "entry,name",
        [
            ("[INDIRECT] _ADC0STS.Bits.READY", "_ADC0STS.Bits.READY"),
            ("[INDIRECT2] _ADC0STS.Bits.READY", "_ADC0STS.Bits.READY"),
            ("[INDIRECT] u8g_SleepReady_F", "u8g_SleepReady_F"),
            ("[INDIRECT] g_u8ResponsePendingReady", "g_u8ResponsePendingReady"),
        ],
    )
    def test_name_containing_read_does_not_escape_indirect_suppression(self, entry, name):
        u = self._unit(entry)
        assert name not in u["input_vars"], (
            f"이름 안의 글자가 간접 억제를 뚫었다: {u['input_vars']}"
        )

    @pytest.mark.parametrize(
        "entry,name",
        [
            ("[INDIRECT] u8g_SysUds_WriteData", "u8g_SysUds_WriteData"),
            ("[INDIRECT2] u8g_DoorCtrl_EepWriteCmd", "u8g_DoorCtrl_EepWriteCmd"),
        ],
    )
    def test_name_containing_write_does_not_escape_indirect_suppression(self, entry, name):
        u = self._unit(entry)
        assert name not in u["output_vars"], (
            f"이름 안의 글자가 간접 억제를 뚫었다: {u['output_vars']}"
        )

    def test_out_tag_is_not_flipped_by_read_in_the_name(self):
        """`[OUT] …Read…` 이 입력 열에도 실리면 한 행에서 같은 변수가 양쪽에 나온다.

        실측 19건. 파서가 방향을 아는데 이름의 글자가 그걸 뒤집으면 안 된다.
        """
        u = self._unit("[OUT] u8g_SysEepromCtrl_TunningParamRead_F")
        assert "u8g_SysEepromCtrl_TunningParamRead_F" in u["output_vars"]
        assert "u8g_SysEepromCtrl_TunningParamRead_F" not in u["input_vars"]

    def test_in_tag_is_not_flipped_by_write_in_the_name(self):
        """반대 방향 — 실측 10건."""
        u = self._unit("[IN] u8g_SysUds_WriteData")
        assert "u8g_SysUds_WriteData" in u["input_vars"]
        assert "u8g_SysUds_WriteData" not in u["output_vars"]

    @pytest.mark.parametrize(
        "keyword,column,other",
        [("READ", "input_vars", "output_vars"), ("WRITE", "output_vars", "input_vars")],
    )
    def test_leading_keyword_still_works(self, keyword, column, other):
        """음성 대조군 — 앵커로 좁혔다고 **정당한 폴백까지** 죽이면 안 된다."""
        u = self._unit(f"{keyword} s_LinFrame")
        assert "s_LinFrame" in u[column]
        assert "s_LinFrame" not in u[other]

    def test_keyword_must_be_a_whole_token_even_when_leading(self):
        """**토큰 경계 축만** 겨눈다 — 앵커가 살아 있어도 `\\b` 가 없으면 깨진다.

        `READYFLAG_s_Value` 는 선두라서 `^\\s*` 는 통과하지만 키워드가 아니라 변수
        이름이다. 경계 없이 `READ` 만 보면 이 이름이 방향을 자칭한다.
        """
        u = self._unit("READYFLAG_s_Value")
        assert "READYFLAG_s_Value" not in u["input_vars"], (
            "`\\b` 경계가 없으면 이름이 키워드로 읽힌다"
        )

    def test_anchor_is_needed_even_when_the_keyword_is_a_whole_token(self):
        """**앵커 축만** 겨눈다 — `\\b` 가 살아 있어도 `^\\s*` 가 없으면 깨진다.

        `s_Cfg.READ` 는 무태그에 마지막 마디가 `READ` 라 경계가 성립한다. 앵커가
        없으면(=엔트리 아무 데나 찾으면) 이 **이름**이 방향을 정한다. 무태그는
        프리픽스 휴리스틱이 판정해야 하고, `s_` 는 출력 축이다.
        """
        u = self._unit("s_Cfg.READ")
        assert "s_Cfg.READ" not in u["input_vars"], (
            f"앵커가 없어 이름 끝의 토큰이 입력으로 승격됐다: {u['input_vars']}"
        )
        assert "s_Cfg.READ" in u["output_vars"], "무태그 프리픽스 휴리스틱이 죽었다"

    def test_clean_name_contract_covers_every_tag(self):
        """`_clean_global_name` 의 **계약** — 어떤 태그가 붙어도 맨 이름만 남는다.

        ⚠ 이건 가드가 아니라 계약 테스트다. 태그 목록을 복제해 두든 단일 출처
        (`_DIR_TAG_PAT`)를 쓰든 **양쪽 다 통과한다** — 이름을 마지막 토큰에서 뽑기
        때문에 태그 제거가 관측에 안 드러난다. 그래서 이 저장소가 `[INDIRECT2]` 를
        여기서만 빼먹고도 오래 몰랐다. 복제 제거는 재발 방지이지 동작 수정이 아니다.
        """
        from generators.suts import _clean_global_name

        for t in ("[IN]", "[OUT]", "[INOUT]", "[INDIRECT]", "[INDIRECT2]"):
            assert _clean_global_name(f"{t} u8g_Flag") == "u8g_Flag", t
            # 타입이 앞에 붙어도(= 토큰이 여럿이어도) 이름만 남는다
            assert _clean_global_name(f"{t} volatile U8 u8g_Flag") == "u8g_Flag", t


class TestIndirectFillsNeitherColumn:
    """`[INDIRECT*]` 는 **입력도 기대결과도 아니다** — 프리픽스가 방향을 대신 정하던 축.

    간접 억제는 오래 `role_in` 쪽에만 붙어 있었다. 다섯 분기에 흩어진 `if not
    is_indirect` 가드가 전부 입력만 막고, `role_out = True` 는 가드 **밖**이었다.
    그래서 같은 `[INDIRECT]` 라도 이름 접두사가 방향을 정했다:

        [INDIRECT] u8g_X  → 어느 열에도 안 나감      (입력 접두사 → 가드에 막힘)
        [INDIRECT] u8s_X  → **기대결과로 나감**      (출력 접두사 → 가드 밖)
        [INDIRECT] REG_X  → **기대결과로 나감**
        [INDIRECT] s_Cfg  → **기대결과로 나감**      (static 스코프 폴백)

    실측(2026-08-14, KJPDS02_PV 정본 1,005 unit): 오로지 `[INDIRECT*]` 엔트리에서만
    온 기대결과 칸 **1,777개 중 정본 일치 0개**(정확·뿌리 둘 다 0). 그중 **798칸**은
    정본이 기대결과 열을 통째로 비워둔 unit 에 채운 것이다. 반대로 우리가 어느 열에도
    안 낸 간접 이름 1,648개도 정본엔 양쪽 모두 0 — 정본은 간접 전역을 **적지 않는다**.

    간접 전역이 사라지는 건 아니다. `indirect_vars` 로 가서 GLOBAL/VOID 시험 전략의
    재료가 된다(아래 `test_indirect_global_becomes_strategy_material`).
    """

    _unit = staticmethod(TestGlobalDirectionTags._unit)

    @pytest.mark.parametrize("tag", ["[INDIRECT]", "[INDIRECT2]"])
    @pytest.mark.parametrize(
        "entry_name,kwargs",
        [
            ("u8s_MotorDuty", {}),                              # 출력 접두사
            ("REG_PTT", {}),                                    # 레지스터
            ("s_Cfg", {}),                                      # static 스코프 폴백
            ("g_MotorState", {"as_global": True}),              # g_ 접두사
            ("r_SCI0CR2.Byte", {"as_global": True}),            # r_ 접두사
        ],
    )
    def test_indirect_is_in_neither_column(self, tag, entry_name, kwargs):
        """접두사가 무엇이든 `[INDIRECT*]` 는 두 열 모두에 안 들어간다.

        ⚠ 이 파라미터 목록은 `role_out = True` 를 켜던 **다섯 분기 전부**를 훑는다 —
          하나만 겨누면 나머지 넷은 가드를 되돌려도 초록이다.
        """
        u = (self._unit(globals_global=[f"{tag} {entry_name}"])
             if kwargs.get("as_global") else self._unit(f"{tag} {entry_name}"))
        assert entry_name not in u["output_vars"], (
            f"간접 접근이 기대결과가 됐다: {u['output_vars']} "
            "— 정본은 간접 전역을 기대결과로 적지 않는다(실측 1,777칸 중 일치 0)"
        )
        assert entry_name not in u["input_vars"], f"간접이 입력이 됐다: {u['input_vars']}"

    @pytest.mark.parametrize(
        "entry_name,column,kwargs",
        [
            ("u8s_MotorDuty", "output_vars", {}),
            ("REG_PTT", "output_vars", {}),
            ("REG_PTT", "input_vars", {}),
            ("s_Cfg", "output_vars", {}),
            ("g_MotorState", "input_vars", {"as_global": True}),
            ("g_MotorState", "output_vars", {"as_global": True}),
            ("u8g_SystemReset_F", "input_vars", {"as_global": True}),
        ],
    )
    def test_untagged_prefix_heuristic_is_untouched(self, entry_name, column, kwargs):
        """**음성 대조군** — 간접을 막는다고 무태그 휴리스틱까지 죽이면 안 된다.

        간접 억제를 "엔트리를 통째로 버린다"로 구현하면 이건 통과하지만, 게이트 조건을
        `not _dir_tag` 같은 걸로 잘못 쓰면 여기서 깨진다. 무태그 529건이 걸린 축이다.
        """
        u = (self._unit(globals_global=[entry_name]) if kwargs.get("as_global")
             else self._unit(entry_name))
        assert entry_name in u[column], f"무태그 프리픽스 휴리스틱이 죽었다: {u}"

    def test_indirect_global_becomes_strategy_material(self):
        """열에서 빠진 간접 전역은 **사라지는 게 아니라** `indirect_vars` 로 간다.

        ⚠ 이 단언은 이전 동작에서 **실패한다** — 예전엔 `u8s_` 가 기대결과 열에 들어가
          `gn not in out_set` 조건에 걸려 `indirect_vars` 에서 제외됐다. 즉 이 테스트는
          "재료로 남는다"를 실제로 구별한다(공허하지 않다).
        """
        u = self._unit("[INDIRECT] u8s_MotorDuty")
        assert u["indirect_vars"] == ["u8s_MotorDuty"], (
            f"간접 전역이 시험 재료로도 안 남았다: {u['indirect_vars']}"
        )

    def test_direction_tagged_entries_still_fill_columns(self):
        """음성 대조군 2 — 게이트가 `[IN]`/`[OUT]`/`[INOUT]` 까지 삼키면 안 된다."""
        assert "u8s_MotorDuty" in self._unit("[IN] u8s_MotorDuty")["input_vars"]
        assert "u8s_MotorDuty" in self._unit("[OUT] u8s_MotorDuty")["output_vars"]
        both = self._unit("[INOUT] u8s_MotorDuty")
        assert "u8s_MotorDuty" in both["input_vars"]
        assert "u8s_MotorDuty" in both["output_vars"]


class TestParamAnnotationTail:
    """이름 뒤 주석형 꼬리가 **이름을 삼키던** 경로.

    파서는 이름 뒤에 `(idx: …)` · `(range: …)` · `(divisor: …)` 를 붙이는데
    (`_format_param_entry`), 이름은 마지막 토큰에서 뽑는다. 꼬리를 안 떼면:

    - `u8g_Hash (idx: u8t_Index)` → 이름이 `u8t_Index)` → `_LOCAL_TEMP_PATS`(`u8t_`)에
      걸려 **전역이 통째로 사라진다**
    - `ctx (range: … 0xFFFFFFFF)` → 이름이 `0xFFFFFFFF)` → 식별자가 아니라
      **파라미터가 통째로 사라진다**

    실측(2026-08-12, KJPDS02 750함수): 입력 0개 unit 221 → 151 (-70).
    `s_sha256_transform` 은 정본이 입력 9개를 적는데 우리는 0개였다.
    """

    @pytest.mark.parametrize(
        "raw,name",
        [
            ("[IN] u8g_Lib_Sha256_Hash (idx: u8t_Index)", "u8g_Lib_Sha256_Hash"),
            ("[IN] g_DoorState_his (idx: u8t_i)", "g_DoorState_his"),
            ("[OUT] g_Buf (idx: i) (range: 0x0 ~ 0xFF)", "g_Buf"),   # 꼬리가 이어 붙는다
            ("[INOUT] s_LinFrame", "s_LinFrame"),                     # 꼬리 없는 것은 그대로
            # ⚠ 꼬리 키워드 목록은 정규식 **두 개**가 공유한다(`_PARAM_ANNOT_KEYS`).
            #   새 꼬리를 목록에 안 넣으면 그 꼬리가 그대로 이름이 된다 — `(size: 60)` 은
            #   배열 원소 확장이 쓸 꼬리다(정본 입력의 50.3%가 `name[N]` 원소 표기).
            ("[IN] u8s_DataBuffer (size: 60)", "u8s_DataBuffer"),
            ("[IN] u8s_DataBuffer (size: 60) (idx: u8t_Idx)", "u8s_DataBuffer"),
        ],
    )
    def test_global_name_survives_annotation_tail(self, raw, name):
        from generators.suts import _clean_global_name

        assert _clean_global_name(raw) == name

    @pytest.mark.parametrize(
        "raw,names",
        [
            ("[IN] SHA256_CTX * ctx (range: 0x00000000 ~ 0xFFFFFFFF)", ["ctx"]),
            ("[IN] const UINT8 * data (idx: bIndex) (range: 0x0 ~ 0xFF)", ["data"]),
            ("[IN] U8 mode", ["mode"]),
            ("[IN] U8 div (divisor: no 0)", ["div"]),
        ],
    )
    def test_param_name_survives_annotation_tail(self, raw, names):
        from generators.suts import _extract_var_names

        assert _extract_var_names([raw]) == names

    def test_annotation_inside_the_name_is_not_stripped(self):
        """꼬리(끝)만 뗀다 — 중간의 괄호까지 지우면 다른 이름이 된다."""
        from generators.suts import _strip_param_annotations

        assert _strip_param_annotations("g_Fn (idx: i) tail") == "g_Fn (idx: i) tail"

    @pytest.mark.parametrize(
        "raw",
        [
            # 상위 파서가 주석 블록을 파라미터 하나로 딸려보낸 실제 문자열(축약)
            "[IN] void) ** This method is implemented as a macro. */ // if (Val == (U8) TRUE"
            " (range: 0x00000000 ~ 0xFFFFFFFF)",
            # 주석 안의 콤마에서 파라미터가 쪼개져 코드 조각만 남은 것
            "[IN] if positive = 0 */ l_u8 error_code",
            "[IN] " + "A" * 200,
        ],
    )
    def test_garbage_param_string_yields_no_name(self, raw):
        """⚠ 꼬리 주석 제거를 넣자마자 **`TRUE` 를 변수명으로 지어냈다**(실측 3건).

        없는 입력을 만들면 빈 칸보다 나쁘다 — 근거처럼 보이기 때문이다. 선언이 아니면
        버리고, 버렸다는 사실은 게이트가 `param_string_unusable` 로 보고한다.
        """
        from generators.suts import _extract_var_names

        assert _extract_var_names([raw]) == []

    @pytest.mark.parametrize(
        "raw,names",
        [
            # LIN 스택 실측 — 파라미터 앞에 설명 주석이 붙는다
            ("[IN] /* [IN] Length of response data */ l_u8 msg_length", ["msg_length"]),
            ("[IN] /* [IN] data area */ const l_u8* const data (idx: i, 0)", ["data"]),
            ("[IN] U8 x /* 설명 */", ["x"]),
            # 꼬리 안에 괄호가 중첩돼도 이름은 남는다
            ("[IN] U8 buf (idx: ( ( U8 )( 2U ) ), ( ( U8 )( 8U ) ))", ["buf"]),
        ],
    )
    def test_leading_comment_is_cleaned_not_rejected(self, raw, names):
        """⚠ 이 축은 2026-08-12 에 **뒤집혔다**.

        원래는 `/*` 가 있으면 통째로 버렸다(위 garbage 가드). 그런데 실측해보니 버려진
        23개 unit 이 전부 `/* [IN] … */ l_u8 msg_length` 꼴의 **멀쩡한 선언**이었다 —
        주석만 지우면 이름이 그대로 나온다. 그래서 "주석 있으면 거절"이 아니라
        "주석을 지운 뒤 **선언 모양인지** 본다"로 바꿨다. 위 garbage 케이스들은
        주석을 지워도 `)`·`=` 가 남아 여전히 거절된다.
        """
        from generators.suts import _extract_var_names

        assert _extract_var_names([raw]) == names

    def test_indexed_global_reaches_the_input_column(self):
        """소비처 확인 — 여기서 빠지면 시퀀스에 넣을 값이 없다."""
        details = {
            "SwUFn_0101": {
                "id": "SwUFn_0101",
                "name": "s_Sha256_Hash_Init",
                "prototype": "void s_Sha256_Hash_Init(void)",
                "inputs": [],
                "outputs": [],
                "globals_global": ["[IN] u8g_Lib_Sha256_Hash (idx: u8t_Index)"],
                "globals_static": [],
                "logic_flow": [],
            }
        }
        unit = collect_unit_functions(details, sds_map={})[0]
        assert unit["input_vars"] == ["u8g_Lib_Sha256_Hash"]


class TestInferVariableType:
    def test_uint8_prefix(self):
        result = infer_variable_type("u8_MotorSpeed")
        assert "8" in result or "uint" in result.lower()

    def test_bool_prefix(self):
        result = infer_variable_type("b_IsReady")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_unknown(self):
        result = infer_variable_type("someRandomVar")
        assert isinstance(result, str)
        assert len(result) > 0


class TestGetBoundaryValues:
    def test_uint8(self):
        bv = get_boundary_values("uint8_t")
        assert "min" in bv
        assert "max" in bv
        assert bv["min"] == 0
        assert bv["max"] == 255

    def test_uint16(self):
        bv = get_boundary_values("uint16_t")
        assert bv["max"] == 65535

    def test_unknown_defaults(self):
        bv = get_boundary_values("completely_unknown_type")
        assert "min" in bv
        assert "max" in bv


class TestDetermineGenMethod:
    def test_with_logic(self):
        unit = {"logic_flow": [{"type": "if", "condition": "x > 0"}], "input_vars": ["x"]}
        method = determine_gen_method(unit)
        assert isinstance(method, str)
        assert len(method) > 0

    def test_without_logic(self):
        unit = {"logic_flow": [], "input_vars": ["x"]}
        method = determine_gen_method(unit)
        assert isinstance(method, str)


class TestDetermineTestMethod:
    def test_review_when_no_inputs_and_no_logic(self):
        unit = {"logic_flow": [], "input_vars": []}
        assert determine_test_method(unit) == "RVW"

    def test_fit_when_inputs_exist(self):
        unit = {"logic_flow": [], "input_vars": ["x"]}
        assert determine_test_method(unit) == "FIT"

    def test_fnct_when_logic_exists(self):
        unit = {"logic_flow": [{"type": "if", "condition": "x > 0"}], "input_vars": ["x"]}
        assert determine_test_method(unit) == "FNCT"


class TestGenerateSequences:
    def test_basic_sequences(self):
        unit = {
            "name": "S_Motor_Init",
            "input_vars": ["u8_mode"],
            "output_vars": ["g_MotorState"],
            "logic_flow": [],
        }
        seqs = generate_sequences(unit)
        assert len(seqs) >= 1
        for seq in seqs:
            assert "seq_num" in seq
            assert "inputs" in seq
            assert "expected" in seq
            assert "strategy" in seq

    def test_no_vars(self):
        unit = {"name": "S_Nop", "input_vars": [], "output_vars": [], "logic_flow": []}
        seqs = generate_sequences(unit)
        assert len(seqs) == 3
        assert [seq["strategy"] for seq in seqs] == ["NORMAL_CALL", "ERROR_PATH", "REPEAT_CALL"]

    def test_max_seq_limit(self):
        unit = {
            "name": "S_Motor_Init",
            "input_vars": ["u8_mode"],
            "output_vars": [],
            "logic_flow": [],
        }
        seqs = generate_sequences(unit, max_seq=2)
        assert len(seqs) <= 2


class TestGenerateSutsWorkbook:
    def test_fixed_columns_are_populated(self, tmp_path: Path):
        units = [{
            "fid": "SwUFn_001",
            "name": "S_Motor_Init",
            "prototype": "void S_Motor_Init(U8 mode)",
            "component": "SwCom_01\n(Module)",
            "input_vars": ["u8_mode"],
            "output_vars": ["u8g_status"],
            "logic_flow": [{"type": "if", "condition": "u8_mode > 0"}],
            "calls_list": [],
            "description": "Initialize motor state",
            "asil": "ASIL-B",
            "precondition": "Power on reset complete",
        }]
        all_sequences = {
            "SwUFn_001": [{
                "seq_num": 1,
                "inputs": {"u8_mode": 0},
                "expected": {"u8g_status": 1},
                "strategy": "BV_MIN",
            }]
        }
        out_path = tmp_path / "suts_test.xlsx"

        generate_suts_xlsm(None, units, all_sequences, str(out_path), {"project_id": "TEST"})

        openpyxl = pytest.importorskip("openpyxl")
        from generators.suts import (
            _COL_GEN,
            _COL_INDEX,
            _COL_METHOD,
            _COL_SAFETY,
            _COL_TC_ID,
            _COL_UNIT,
            _DATA_START_ROW,
            _SEQ_COL,
        )
        wb = openpyxl.load_workbook(str(out_path), read_only=True, data_only=True)
        ws = wb["2.SW Unit Test Spec"]
        tc_row = _DATA_START_ROW          # 변수명 행(정본 구조)
        seq_row = _DATA_START_ROW + 1     # 첫 시퀀스 행
        assert ws.cell(row=tc_row, column=_COL_INDEX).value == 1
        assert ws.cell(row=tc_row, column=_COL_TC_ID).value == "SwUTC_SwUFn_001"
        assert ws.cell(row=tc_row, column=_COL_UNIT).value == "S_Motor_Init"
        # ⚠ `O` 여야 한다. 예전엔 안전 관련에 `X` 를 찍어 **정본과 의미가 반대**였다.
        assert ws.cell(row=tc_row, column=_COL_SAFETY).value == "O"
        # Test Method / TC Gen Method 는 TC 행이 아니라 **시퀀스 그룹 행**에 온다.
        assert ws.cell(row=tc_row, column=_COL_METHOD).value is None
        assert ws.cell(row=seq_row, column=_SEQ_COL).value == 1
        assert ws.cell(row=seq_row, column=_COL_METHOD).value == "REQ"
        assert ws.cell(row=seq_row, column=_COL_GEN).value == "AOR/ABV"
        wb.close()

    def test_out_of_range_sequences_are_marked_fault_injection(self, tmp_path):
        """정본은 유효 범위 밖 시퀀스를 `FI` 로 묶는다 — 한 method 로 뭉치면 안 된다."""
        from generators.suts import _COL_METHOD, _DATA_START_ROW, generate_suts_xlsm

        units = [{
            "fid": "SwUFn_001", "name": "f", "component": "SwCom_01",
            "input_vars": ["a"], "output_vars": [], "asil": "QM",
        }]
        seqs = {"SwUFn_001": [
            {"seq_num": 1, "strategy": "BV_MID", "inputs": {"a": 1}, "expected": {}},
            {"seq_num": 2, "strategy": "BV_MAX_INV", "inputs": {"a": 256}, "expected": {}},
        ]}
        out = tmp_path / "fi.xlsx"
        generate_suts_xlsm(None, units, seqs, str(out), {"project_id": "T"})

        openpyxl = pytest.importorskip("openpyxl")
        ws = openpyxl.load_workbook(str(out), read_only=True, data_only=True)["2.SW Unit Test Spec"]
        assert ws.cell(row=_DATA_START_ROW + 1, column=_COL_METHOD).value == "REQ"
        assert ws.cell(row=_DATA_START_ROW + 2, column=_COL_METHOD).value == "FI"

    def test_safety_related_never_invents_a_verdict(self):
        """근거 없는 ASIL 을 `X`(=확인했고 비안전)로 단정하지 않는다."""
        from generators.suts import resolve_safety_related

        assert resolve_safety_related("A") == "O"
        assert resolve_safety_related("ASIL-B") == "O"
        assert resolve_safety_related("QM") == "X"
        # 모르는 것은 빈칸이다 — `X` 로 적으면 under-classification 이다.
        assert resolve_safety_related("") == ""
        assert resolve_safety_related("TBD") == ""
        assert resolve_safety_related(None) == ""


class TestResolvedDocInput:
    r"""문서 입력(SRS/UDS/HSIS)은 resolver 경유로 확보한다.

    회귀 대상: `Path(p).is_file()`만 보던 코드는 cloudium worker-only 경로(U:\ 등)에서
    항상 False라 보강 블록을 **경고 없이** 통째로 건너뛰었다.
    """

    def test_local_file_is_passed_through_without_copy(self, tmp_path):
        from generators.suts import _resolved_doc_input
        src = tmp_path / "SRS.docx"
        src.write_bytes(b"payload")
        with _resolved_doc_input(str(src), "SRS") as p:
            assert p == str(src)      # 로컬이면 임시 복사 없음

    def test_blank_path_yields_none(self):
        from generators.suts import _resolved_doc_input
        with _resolved_doc_input("", "SRS") as p:
            assert p is None
        with _resolved_doc_input(None, "UDS") as p:
            assert p is None

    def test_worker_only_path_is_materialized(self, monkeypatch, tmp_path):
        """로컬에 없지만 resolver가 읽을 수 있으면 임시 파일로 실체화한다."""
        import backend.services.file_resolver as fr
        from generators.suts import _resolved_doc_input

        remote = "U:/docs/HSIS.xlsx"

        class _Worker:
            mode = "cloudium"
            def is_file(self, p):
                return str(p) == remote
            def read_bytes(self, p):
                return b"remote-bytes"

        monkeypatch.setattr(fr, "get_resolver", lambda: _Worker())
        seen = {}
        with _resolved_doc_input(remote, "HSIS") as p:
            assert p is not None and p != remote
            assert Path(p).read_bytes() == b"remote-bytes"
            assert Path(p).suffix == ".xlsx"   # 파서가 확장자로 분기하므로 보존 필수
            seen["path"] = p
        # with 종료 시 정리
        assert not Path(seen["path"]).exists()

    def test_missing_everywhere_yields_none_with_warning(self, monkeypatch, caplog):
        import backend.services.file_resolver as fr
        from generators.suts import _resolved_doc_input

        class _Empty:
            mode = "cloudium"
            def is_file(self, p):
                return False
            def read_bytes(self, p):
                raise AssertionError("read_bytes must not be called when is_file() is False")

        monkeypatch.setattr(fr, "get_resolver", lambda: _Empty())
        with caplog.at_level("WARNING", logger="generators.suts"):
            with _resolved_doc_input("U:/nope.docx", "SRS") as p:
                assert p is None
        # 침묵 skip이 원래 결함이었다 — 사유가 반드시 남아야 한다
        assert "SRS" in caplog.text and "nope.docx" in caplog.text, caplog.text

    def test_read_failure_does_not_raise(self, monkeypatch):
        """resolver가 있다고 했는데 읽기가 깨져도 생성 자체는 계속된다(보강만 생략)."""
        import backend.services.file_resolver as fr
        from generators.suts import _resolved_doc_input

        class _Broken:
            mode = "cloudium"
            def is_file(self, p):
                return True
            def read_bytes(self, p):
                raise OSError("worker timeout")

        monkeypatch.setattr(fr, "get_resolver", lambda: _Broken())
        with _resolved_doc_input("U:/x.docx", "UDS") as p:
            assert p is None


class TestSdsMapIsProjectScoped:
    """`sds_docx_path`가 실제로 ASIL 출처가 되어야 한다.

    회귀 대상: 이 인자는 시그니처·docstring에만 있고 본문에서 쓰이지 않아, ASIL이 항상
    저장소 `docs/` 글롭(현재 HDPDM01 SDS)에서 채워졌다 — 다른 프로젝트의 SUTS를 만들어도
    HDPDM01의 안전 등급이 조용히 섞이는 경로였다.
    """

    _DETAILS = {
        "SwUFn_001": {
            "id": "SwUFn_001",
            "name": "S_Motor_Init",
            "prototype": "void S_Motor_Init(void)",
            "module_name": "MotorCtrl_PDS",
            "asil": "TBD",
        }
    }

    def test_injected_map_wins_over_repo_docs_fallback(self, monkeypatch):
        from generators import suts as gsuts

        called = {"default": 0}
        monkeypatch.setattr(gsuts, "_load_default_sds_map",
                            lambda: called.__setitem__("default", called["default"] + 1) or {
                                "motor control": {"asil": "D", "related": "", "description": ""}})

        units = gsuts.collect_unit_functions(
            self._DETAILS, None,
            sds_map={"motor control": {"asil": "A", "related": "SwTR_0101", "description": ""}},
        )
        assert units[0]["asil"] == "A", "주입한 SDS 맵이 무시되고 폴백이 쓰였다"
        assert called["default"] == 0, "sds_map을 줬는데도 저장소 docs/ 폴백을 읽었다"

    def test_no_map_still_uses_fallback(self, monkeypatch):
        """대조군: 맵을 안 주면 기존 폴백 동작이 그대로여야 한다."""
        from generators import suts as gsuts
        monkeypatch.setattr(gsuts, "_load_default_sds_map",
                            lambda: {"motor control": {"asil": "D", "related": "", "description": ""}})
        units = gsuts.collect_unit_functions(self._DETAILS, None)
        assert units[0]["asil"] == "D"

    def test_resolve_returns_none_and_warns_when_path_unusable(self, monkeypatch, caplog):
        """지정했는데 못 쓰면 폴백이 조용히 대신하면 안 된다 — 경고가 남아야 한다."""
        import backend.services.file_resolver as fr
        from generators.suts import _resolve_sds_map

        class _Empty:
            mode = "cloudium"
            def is_file(self, p):
                return False
            def read_bytes(self, p):
                raise AssertionError("호출되면 안 됨")

        monkeypatch.setattr(fr, "get_resolver", lambda: _Empty())
        with caplog.at_level("WARNING", logger="generators.suts"):
            assert _resolve_sds_map("U:/nope/SDS.docx") is None
        assert "SDS" in caplog.text and "폴백" in caplog.text, caplog.text

    def test_resolve_returns_none_and_warns_when_map_is_empty(self, monkeypatch, caplog, tmp_path):
        from generators import suts as gsuts
        src = tmp_path / "SDS.docx"
        src.write_bytes(b"x")
        monkeypatch.setattr(gsuts, "load_sds_map_from", lambda p: {})
        with caplog.at_level("WARNING", logger="generators.suts"):
            assert gsuts._resolve_sds_map(str(src)) is None
        assert "파티션 0건" in caplog.text, caplog.text

    def test_resolve_passes_map_through(self, monkeypatch, tmp_path):
        from generators import suts as gsuts
        src = tmp_path / "SDS.docx"
        src.write_bytes(b"x")
        expected = {"motor control": {"asil": "B", "related": "", "description": ""}}
        monkeypatch.setattr(gsuts, "load_sds_map_from", lambda p: expected)
        assert gsuts._resolve_sds_map(str(src)) == expected

    def test_blank_path_is_not_an_error(self):
        from generators.suts import _resolve_sds_map
        assert _resolve_sds_map(None) is None
        assert _resolve_sds_map("") is None

    def test_load_sds_map_from_survives_parse_failure(self, monkeypatch, caplog):
        from generators import suts as gsuts

        def _boom(_p):
            raise ValueError("깨진 docx")

        monkeypatch.setattr(gsuts, "_extract_sds_partition_map", _boom)
        with caplog.at_level("WARNING", logger="generators.suts"):
            assert gsuts.load_sds_map_from("x.docx") == {}
        assert "파싱 실패" in caplog.text
