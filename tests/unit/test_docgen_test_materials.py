"""시험 문서 재료 측정 — **캡 여유**와 **타입 근거**가 이 파일의 본체다.

0단계 실측이 지목한 두 함정을 회귀로 고정한다:

1. **"절단 0" 은 안전하다는 뜻이 아니다.** KJPDS02 는 후보 120 / 캡 120 으로 경계에
   정확히 닿아 있어, 함수가 하나만 늘어도 조용히 잘리기 시작한다. 그래서 절단 건수가
   아니라 **여유**를 본다.
2. **타입 폴백은 반환값으로 판정할 수 없다.** `infer_variable_type` 의 폴백이
   `"uint8_t"` 인데 진짜 u8 도 같은 값이다 — 0단계 측정도 처음엔 반환값으로 세어
   "100% 확정" 이라는 거짓 수치를 냈다.
"""
from __future__ import annotations

from typing import Any, Dict

import pytest

from backend.services import docgen_test_materials as tm


def _fn(name: str, file: str, calls: list[str], *, asil: str = "QM",
        inputs: list[str] | None = None) -> Dict[str, Any]:
    return {
        "name": name, "file": file, "calls_list": list(calls),
        "asil": asil, "inputs": list(inputs or []), "outputs": [],
    }


def _cross_module_details(n_flows: int) -> Dict[str, Any]:
    """진입점 n개가 각각 **다른 모듈**의 함수를 호출하는 최소 구조."""
    fd: Dict[str, Any] = {}
    for i in range(n_flows):
        entry, callee = f"Mod{i}_Entry", f"Other{i}_Callee"
        fd[entry] = _fn(entry, f"src/Mod{i}.c", [callee])
        fd[callee] = _fn(callee, f"src/Other{i}.c", [])
    return fd


# ── SITS 흐름 / 캡 ──────────────────────────────────────────────────────────

def test_flows_total_is_measured_before_cap() -> None:
    """총량은 **캡 전** 값이어야 한다 — 결과 길이로 되짚으면 절단을 못 본다."""
    from generators.sits import _DEFAULT_MAX_FLOWS

    fd = _cross_module_details(_DEFAULT_MAX_FLOWS + 5)
    res = tm._measure_sits(fd, {}, "")
    assert res["flows_total"] == _DEFAULT_MAX_FLOWS + 5
    assert res["cap"] == _DEFAULT_MAX_FLOWS


def test_headroom_not_dropped_count() -> None:
    """캡을 안 넘겨도 **여유**를 낸다. '절단 0' 만 보면 경계 상태를 못 본다."""
    fd = _cross_module_details(10)
    res = tm._measure_sits(fd, {}, "")
    assert res["headroom"] == res["cap"] - 10
    assert res["at_cap_boundary"] is False


def test_at_cap_boundary_flags_zero_headroom() -> None:
    """후보 수 == 캡이면 지금은 절단 0 이지만 **경계**다 — 함수 하나만 늘면 잘린다."""
    from generators.sits import _DEFAULT_MAX_FLOWS

    fd = _cross_module_details(_DEFAULT_MAX_FLOWS)
    res = tm._measure_sits(fd, {}, "")
    assert res["flows_total"] == _DEFAULT_MAX_FLOWS
    assert res["headroom"] == 0
    assert res["at_cap_boundary"] is True


def test_collect_flows_accepts_none_for_uncapped() -> None:
    """`max_flows=None` 이 캡 없음 계약이다(시그니처가 이걸 막고 있었다)."""
    from generators.sits import collect_integration_flows

    fd = _cross_module_details(6)
    stats: Dict[str, Any] = {}
    flows = collect_integration_flows(fd, max_flows=None, stats_out=stats, sds_map={})
    assert len(flows) == 6
    assert stats["total_flows_found"] == 6
    assert stats["flows_dropped"] == 0


def test_sds_swcom_zero_is_surfaced_not_hidden() -> None:
    """SwDS 보강이 0건이면 **그 0을 올린다**.

    실측: 실 SwDS 763항목을 줘도 키 매칭 38건 / SwCom **0건** 이다(맵 필드가 `kind`
    뿐이라 코드가 읽는 `swcom`/`component` 가 없다). 숨기면 추적성 열이 합성 ID 만
    남는데도 화면은 정상으로 보인다.
    """
    fd = _cross_module_details(3)
    res = tm._measure_sits(fd, {}, "SwDS 경로가 지정되지 않았습니다")
    assert res["sds_swcom_hits"] in (0, None)
    assert res["sds_reason"]


def test_sample_flow_carries_call_chain() -> None:
    """콜체인이 문서 D열에 그대로 박히므로 화면도 그걸 보여야 한다."""
    fd = _cross_module_details(2)
    res = tm._measure_sits(fd, {}, "")
    assert res["sample_flow"] is not None
    assert res["sample_flow"]["entry_fn"]
    assert "->" in res["sample_flow"]["call_chain"] or res["sample_flow"]["call_chain"]


# ── SUTS 변수 타입 ──────────────────────────────────────────────────────────

def test_type_grounding_uses_evidence_not_return_value() -> None:
    """폴백과 진짜 u8 은 **반환값이 같다** — 근거 유무로 갈라야 한다."""
    from generators.suts import infer_variable_type

    fd = {
        "a": _fn("a", "src/A.c", [], inputs=["[IN] u8_Speed"]),          # 이름 패턴 O
        "b": _fn("b", "src/B.c", [], inputs=["[IN] EEPROM_TAddress Addr"]),  # 근거 X
    }
    res = tm._measure_suts_types(fd)
    assert res["variables"] == 2
    assert res["grounded"] == 1
    assert res["fallback"] == 1
    # 반환값만 보면 구분이 안 된다는 사실 자체를 고정한다.
    assert infer_variable_type("[IN] EEPROM_TAddress Addr") == "uint8_t"


def test_fallback_samples_are_reported() -> None:
    """조치하려면 **어떤 변수인지** 알아야 한다 — 건수만으로는 못 고친다."""
    fd = {
        "a": _fn("a", "src/A.c", [],
                 inputs=["[INOUT] S_SHA256_WorkState_t* pt (range: 0x0 ~ 0xFFFFFFFF)"]),
    }
    res = tm._measure_suts_types(fd)
    assert res["fallback"] == 1
    assert res["fallback_samples"], "폴백 변수 목록이 비어 있으면 조치가 불가능하다"
    assert "SHA256" in res["fallback_samples"][0]


def test_zero_variables_is_not_full_grounding() -> None:
    """변수가 0개면 100% 가 아니다 — 분모 0 을 성공으로 접지 않는다."""
    res = tm._measure_suts_types({"a": _fn("a", "src/A.c", [])})
    assert res["variables"] == 0
    assert res["grounded"] == 0


# ── 입력 변수가 없는 unit ───────────────────────────────────────────────────
#
# 입력이 없는 시퀀스는 넣을 값이 없어 시험이 성립하지 않는다. 실측(2026-08-12, KJPDS02):
# 948 TC 중 **338 건이 입력 0개**인데 평균은 2.3 이라 `avg_inp < 1` 게이트를 그대로
# 통과했다 — 평균이 0 을 숨긴 것이다.
#
# ⚠ 0 이 전부 결함은 아니다. 정본(1,005 unit)도 172 건이 입력 0개다. 그래서 건수만
#   내면 판단이 안 되고 **사유별**로 나눠야 한다.

def _unit(name: str, *, inputs=None, gg=None, gs=None) -> Dict[str, Any]:
    return {
        "id": "SwUFn_0101", "name": name, "prototype": f"void {name}(void)",
        "inputs": list(inputs or []), "outputs": [],
        "globals_global": list(gg or []), "globals_static": list(gs or []),
        "logic_flow": [],
    }


def _causes(fd: Dict[str, Any]) -> Dict[str, int]:
    res = tm._measure_suts_inputs(fd, {})
    assert res["measured"] is True
    return res["causes"]


def test_no_params_no_globals_is_its_own_cause() -> None:
    """파라미터도 전역도 없으면 입력 0 이 **정상**이다 — 결함과 섞으면 안 된다."""
    assert _causes({"a": _unit("s_SysMain_Init")}) == {"no_params_no_globals": 1}


def test_stub_return_candidate_is_split_out_of_normal() -> None:
    """반환값 있는 함수를 호출하면 **스텁 반환값을 입력으로 지정할 수 있다**.

    정본이 `s_UDS_RDBI_ValidateSingleFrame() return` 같은 표기로 실제로 그렇게 적는다.
    `no_params_no_globals`(정상)에 섞으면 시험 가능한 unit 이 "정상 0" 뒤에 숨는다.
    """
    fd = {
        "a": {**_unit("s_SystemParamRead"), "calls_list": ["u8g_Read"]},
        "b": {**_unit("s_Void_Caller"), "calls_list": ["s_DoWork"]},
        "u8g_Read": _unit("u8g_Read"),
        "s_DoWork": _unit("s_DoWork"),
    }
    fd["u8g_Read"]["prototype"] = "U8 u8g_Read(void)"
    fd["s_DoWork"]["prototype"] = "void s_DoWork(void)"
    causes = _causes(fd)
    assert causes.get("stub_return_candidate") == 1, "비-void 를 호출하는 쪽만 후보다"
    assert causes.get("no_params_no_globals") == 3, "void 호출자와 피호출자들은 정상 축"


def test_stub_candidate_sample_names_the_call_to_stub() -> None:
    """건수만으로는 조치할 수 없다 — 어느 호출을 막을지 이름이 있어야 한다."""
    fd = {
        "a": {**_unit("s_SystemParamRead"), "calls_list": ["u8g_Read"]},
        "u8g_Read": {**_unit("u8g_Read"), "prototype": "U8 u8g_Read(void)"},
    }
    res = tm._measure_suts_inputs(fd, {})
    assert any("u8g_Read" in s for s in res["cause_samples"]["stub_return_candidate"])


def test_stub_candidate_does_not_fill_the_input_column() -> None:
    """⚠ 값을 자동으로 넣지 않는다.

    '비-void callee 를 전부 입력으로' 규칙은 정본 대조상 맞음 55 · 과다 148(정밀도 27%)
    이다. 문서에 박으면 근거처럼 보이는 오답이 148칸 생긴다 — 빈 칸보다 나쁘다.
    """
    from generators.suts import collect_unit_functions

    fd = {
        "a": {**_unit("s_SystemParamRead"), "calls_list": ["u8g_Read"]},
        "u8g_Read": {**_unit("u8g_Read"), "prototype": "U8 u8g_Read(void)"},
    }
    unit = next(u for u in collect_unit_functions(fd, sds_map={})
                if u["name"] == "s_SystemParamRead")
    assert unit["input_vars"] == [], "후보 표시일 뿐 값을 지어내면 안 된다"


def test_write_only_globals_are_named_separately() -> None:
    fd = {"a": _unit("s_Init_Sys", gg=["[OUT] g_State"])}
    assert _causes(fd) == {"write_only": 1}


def test_indirect_only_is_named_separately() -> None:
    fd = {"a": _unit("s_Cfg", gg=["[INDIRECT] g_Table"])}
    assert _causes(fd) == {"indirect_only": 1}


def test_two_hop_indirect_lands_in_the_same_bucket() -> None:
    """⚠ 2홉 전파(`[INDIRECT2]`)도 간접이다.

    사유 분포가 이걸 `other` 로 흘리면 조치 가능한 축을 못 짚는다. 게다가 옛 판은
    여기 정규식을 복제해 두고 `INDIRECT` 만 알았는데, 진짜 소비처
    (`generators.suts.collect_unit_functions`)는 그 사이 같은 항목을 **입력으로
    올리고** 있었다 — 게이트가 보는 그림과 산출물이 서로 달랐다.
    """
    fd = {"a": _unit("s_Cfg", gg=["[INDIRECT2] g_Table"])}
    assert _causes(fd) == {"indirect_only": 1}
    fd2 = {"a": _unit("s_Cfg", gg=["[INDIRECT] g_A", "[INDIRECT2] g_B"])}
    assert _causes(fd2) == {"indirect_only": 1}


def test_readable_global_that_vanished_is_flagged_as_a_defect() -> None:
    """읽는 전역이 분명히 있는데 입력 열이 비면 **이름 추출이 버린 것**이다.

    정상 사유(`no_params_no_globals` 등)와 절대 같은 칸에 세지 않는다 — 섞이면
    "정상 0" 뒤에 숨는다. 여기서는 2글자 이름이라 길이 필터에 걸린다.
    """
    fd = {"a": _unit("s_Fn", gg=["[IN] gX"])}
    assert _causes(fd) == {"dropped_by_name_filter": 1}


def test_reference_baseline_is_carried_so_the_count_is_judgeable() -> None:
    """건수만 있으면 많은 건지 알 수 없다 — 정본 기준선을 함께 낸다."""
    res = tm._measure_suts_inputs({"a": _unit("s_SysMain_Init")}, {})
    assert res["reference_without_input"] and res["reference_units"]


def test_units_with_input_are_not_counted() -> None:
    fd = {"a": _unit("g_Fn", gg=["[IN] g_Speed"]), "b": _unit("s_SysMain_Init")}
    res = tm._measure_suts_inputs(fd, {})
    assert res["units_without_input"] == 1


# ── const 전역만 읽는 unit ──────────────────────────────────────────────────
#
# const 전역은 시험 입력으로 **설정할 수 없다**. 정본(KJPDS02_PV)은 const 전역을
# 입력 0칸·기대 0칸으로 한 번도 적지 않아, 산출물에서 억제한다. 그러면 그 unit 은
# 입력 0개가 되는데 — 그걸 `dropped_by_name_filter`(= 이름 추출이 버렸다, **결함**)
# 로 세면 사유 분포가 조치 가능한 축을 못 짚는다. 의도한 억제는 별도 사유다.

_CONST_GIM = {"au32_Rounds": {"type": "const U32", "array": "[4]"}}


def test_const_only_unit_is_not_reported_as_a_defect() -> None:
    fd = {"a": _unit("g_ConstOnly", gg=["[IN] au32_Rounds (size: 4)"])}
    res = tm._measure_suts_inputs(fd, {}, _CONST_GIM)
    assert res["causes"] == {"const_globals_only": 1}, res["causes"]


def test_mixed_globals_are_not_const_only() -> None:
    """⚠ const 가 아닌 전역이 **하나라도** 남으면 이 사유가 아니다.

    입력이 0 으로 남는 조합을 써야 판정이 실제로 돌아간다 — 설정 가능한 전역이 하나라도
    있으면 그 unit 은 입력이 생겨 애초에 세지 않는다(가드가 헛돌았던 자리).
    여기선 남는 전역이 쓰기 전용이라 사유는 `write_only` 여야 한다.
    """
    fd = {"a": _unit("g_Mixed", gg=["[IN] au32_Rounds (size: 4)", "[OUT] u8g_Log"])}
    res = tm._measure_suts_inputs(fd, {}, _CONST_GIM)
    assert res["causes"] == {"write_only": 1}, res["causes"]


def test_suppressed_const_does_not_leave_its_direction_tag_behind() -> None:
    """⚠ 방향 태그를 억제 **전** 목록에서 뽑으면 오분류가 난다.

    const 의 `[IN]` 이 남으면 "읽는 전역이 있는데 입력이 비었다"(= 이름 추출이 버렸다,
    **결함**)로 찍힌다. 우리가 의도적으로 뺀 것을 결함으로 세면 안 된다.
    """
    fd = {"a": _unit("g_ConstPlusWrite", gg=["[IN] au32_Rounds (size: 4)", "[OUT] u8g_Log"])}
    res = tm._measure_suts_inputs(fd, {}, _CONST_GIM)
    assert "dropped_by_name_filter" not in res["causes"], res["causes"]


def test_without_globals_info_map_the_old_cause_stands() -> None:
    """근거가 없으면 억제도 안 하므로 이 사유도 안 붙는다(둘이 같이 움직여야 한다)."""
    fd = {"a": _unit("g_ConstOnly", gg=["[IN] au32_Rounds (size: 4)"])}
    res = tm._measure_suts_inputs(fd, {})
    assert "const_globals_only" not in res["causes"], res["causes"]


def test_measure_wires_globals_info_map_through(monkeypatch) -> None:
    """⚠ 호출부 배선 앵커.

    `_measure_suts_inputs` 만 단독으로 시험하면 `measure()` 가 그 인자를 **안 넘기는**
    결함이 통째로 생존한다. 파서를 스텁으로 갈아 끼워 종단으로 확인한다.
    """
    import report_generator

    sections = {
        "function_details": {"a": _unit("g_ConstOnly", gg=["[IN] au32_Rounds (size: 4)"])},
        "globals_info_map": _CONST_GIM,
    }
    monkeypatch.setattr(
        report_generator, "generate_uds_source_sections", lambda *a, **k: sections
    )
    tm.clear_cache()
    res = tm.measure("C:/__stubbed__")
    assert res["ok"] is True, res
    assert res["suts_inputs"]["causes"] == {"const_globals_only": 1}, res["suts_inputs"]


# ── measure() 실패 경로 ─────────────────────────────────────────────────────

def test_measure_reports_reason_when_no_source() -> None:
    res = tm.measure("")
    assert res["ok"] is False
    assert res["reason"]


def test_cache_miss_is_explicit(tmp_path) -> None:
    """캐시가 없으면 `has_cached` 는 False 이고 `cached` 는 None 이다.

    preflight 가 이걸로 `unmeasured` 를 결정한다 — 값이 0 인 것과 다르다.
    """
    tm.clear_cache()
    assert tm.has_cached(str(tmp_path)) is False
    assert tm.cached(str(tmp_path)) is None


# ── 시험 결과 문서의 **양식 템플릿** ────────────────────────────────────────
#
# 이 셋의 양식은 SCM 레지스트리가 아니라 `config/swut_meta.json` 의 `template_paths` 가
# 프로젝트별로 관리한다. 게이트가 그 존재를 확인한 적이 없어서, 없으면 [생성]을 눌러야
# 알 수 있었다.

def _preflight(payload: dict) -> dict:
    from fastapi.testclient import TestClient

    from backend.main import app
    r = TestClient(app).post("/api/docgen/preflight", json=payload, headers={"X-User": "t"})
    assert r.status_code == 200, r.text
    return r.json()


def _find(data: dict, step_id: str):
    return next((s for s in data["steps"] if s["id"] == step_id), None)


@pytest.mark.parametrize("doc_type", ["sutr", "sitr", "swreport"])
def test_report_template_step_exists(doc_type: str) -> None:
    """시험 결과 3종은 **양식 확인 단계**를 갖는다."""
    data = _preflight({"doc_type": doc_type, "form": {"project_id": "KJPDS02"}})
    assert _find(data, "report_template") is not None, f"{doc_type}: 양식 단계가 없다"


def test_report_template_needs_project_id_first() -> None:
    """project_id 없이는 양식을 찾을 수 없다 — 그 사실을 말한다."""
    data = _preflight({"doc_type": "sutr", "form": {}})
    step = _find(data, "report_template")
    assert step is not None and step["state"] == "needed"
    assert "project_id" in step["reason"]


def test_unknown_project_is_reported_not_silent() -> None:
    """양식 설정에 없는 프로젝트면 **사유와 함께** 막는다.

    실측: SCM 레지스트리는 3개 프로젝트인데 `swut_meta` 에는 2개뿐이다.
    """
    data = _preflight({"doc_type": "sutr", "form": {"project_id": "__no_such_project__"}})
    step = _find(data, "report_template")
    assert step is not None and step["state"] == "missing"
    assert "swut_meta" in step["reason"] or "양식 설정" in step["reason"]


def test_missing_template_key_is_named() -> None:
    """어느 키가 없는지 말해야 등록할 수 있다.

    실측 비대칭: HDPDM01 은 통합 Summary 양식(`es95411_template`)이 **없다**.
    """
    data = _preflight({"doc_type": "swreport", "form": {"project_id": "HDPDM01"}})
    step = _find(data, "report_template")
    assert step is not None
    if step["state"] == "missing":
        assert "es95411_template" in step["reason"], "빠진 키 이름을 말하지 않는다"


def test_template_prefix_merge_is_wired() -> None:
    """양식 경로도 cloudium 접근 목록에 병합돼야 한다.

    실측: SCM 레지스트리 경로만 병합해서 `swit_sitr_template`·`es95411_template`
    (프로젝트 전용 폴더)이 **접근 거부**였다. 준비 게이트가 그걸 드러냈다.
    """
    from backend.routers.scm import (
        _merge_report_template_prefixes,
        merge_all_scm_paths_to_cloudium,
    )

    # local 모드(conftest 격리)에서는 no-op 이어야 한다 — 권한 개념이 없다.
    assert _merge_report_template_prefixes() == 0
    out = merge_all_scm_paths_to_cloudium()
    assert out["mode"] == "skipped_local"

    # cloudium 경로에서 **실제로 호출되는지**를 고정한다. local 조기 반환 때문에
    # 위 호출로는 확인할 수 없고, 배선이 빠지면 양식이 다시 '접근 거부' 가 된다.
    from pathlib import Path as _P
    src = (_P(__file__).resolve().parents[2] / "backend/routers/scm.py").read_text(
        encoding="utf-8", errors="ignore")
    assert "_merge_report_template_prefixes()" in src.split("def _merge_report_template_prefixes")[0], (
        "merge_all_scm_paths_to_cloudium 이 양식 경로를 병합하지 않는다"
    )


def test_builder_project_id_is_registrable() -> None:
    """SCM id 와 양식 project_id 는 **다른 어휘**라 매핑을 등록할 수 있어야 한다.

    실측: SCM `hdpdm01·kjpds02·kjpds02_pv` ↔ swut_meta `HDPDM01·KJPDS02`.
    매핑이 없어 빌더 폼 기본값(`HDPDM01`)이 쓰였고, KJPDS02_PV 를 보면서 [생성]하면
    **남의 프로젝트 문서**가 나왔다(사용자 보고).
    """
    from backend.schemas import ScmRegisterRequest, ScmRegistryEntry, ScmUpdateRequest

    for model in (ScmRegistryEntry, ScmRegisterRequest, ScmUpdateRequest):
        assert "builder_project_id" in model.model_fields, f"{model.__name__} 에 필드가 없다"


def test_form_project_id_wins_over_registry() -> None:
    """폼에 명시된 값이 레지스트리보다 우선이다 — 사용자가 그 자리에서 정한 값이다."""
    data = _preflight({"doc_type": "sutr", "scm_id": "kjpds02_pv",
                       "form": {"project_id": "KJPDS02"}})
    step = _find(data, "report_template")
    assert step is not None
    # KJPDS02 는 양식 설정에 있으므로 '프로젝트 없음' 사유가 나오면 안 된다.
    assert "양식 설정" not in str(step.get("reason") or "")


def test_report_template_keys_are_mapped() -> None:
    from backend.routers.docgen_preflight import _TEST_REPORT_TEMPLATE_KEY
    from backend.services.docgen_requirements import TEST_REPORT_DOC_TYPES

    assert set(_TEST_REPORT_TEMPLATE_KEY) == set(TEST_REPORT_DOC_TYPES)


def test_sits_endpoints_accept_max_flows() -> None:
    """SITS 3경로가 전부 `max_flows` 를 받아야 한다.

    실측(kjpds02_pv): 흐름 145 / 기본 캡 120 이라 **25개가 시험 규격에서 빠진다**.
    라우터가 이 값을 안 받으면 게이트가 사실을 알려줘도 고칠 수단이 없다.
    한 경로만 고치면 다른 두 경로로 만든 문서는 계속 잘린다.
    """
    from pathlib import Path as _P
    src = (_P(__file__).resolve().parents[2] / "backend/routers/local.py").read_text(
        encoding="utf-8", errors="ignore")
    assert src.count("max_flows: Optional[int] = Form(None)") == 3, "SITS 3경로 중 일부만 받는다"
    # 미지정이면 인자 자체를 넘기지 않는다 — 생성기 기본값이 단일 출처다.
    assert src.count('**({"max_flows": max_flows} if max_flows is not None else {})') == 3


def test_suts_api_default_matches_generator() -> None:
    """SUTS 시퀀스 상한의 API 기본값이 **생성기 기본값과 같아야** 한다.

    예전엔 API 가 6 이라 전략 24종(BV 6/COND 4/SWITCH 6/LOOP 3/GLOBAL 3/VOID 1/MC-DC 6)
    중 6개만 만들었고, 화면은 그 사실을 말하지 않았다. 숫자를 라우터에 복제했으므로
    생성기 상수와 갈라지지 않게 여기서 대조한다.
    """
    import re
    from pathlib import Path as _P

    from generators.suts import _DEFAULT_SEQ_COUNT

    repo = _P(__file__).resolve().parents[2]
    for rel in ("backend/routers/jenkins.py", "backend/routers/local.py"):
        src = (repo / rel).read_text(encoding="utf-8", errors="ignore")
        for got in re.findall(r"max_sequences: int = Form\((\d+)\)", src):
            assert int(got) == _DEFAULT_SEQ_COUNT, (
                f"{rel}: API 기본 {got} ≠ 생성기 기본 {_DEFAULT_SEQ_COUNT}"
            )


def test_max_flows_is_marked_adjustable() -> None:
    """게이트가 "조정할 수 없습니다" 라고 말하면 안 된다 — 이제 받는다."""
    from backend.services.docgen_requirements import requirements_for
    cap = requirements_for("sits")["caps"]["max_flows"]
    assert cap["api"] == 120
    assert cap.get("adjustable") is True


@pytest.mark.parametrize("doc_type", ["sutr", "sitr", "swreport"])
def test_test_report_form_fields_are_shared(doc_type: str) -> None:
    """시험 결과 3종의 폼 필수값은 서버 단일 출처를 쓴다(프론트 복제 제거)."""
    from backend.services.docgen_requirements import (
        TEST_REPORT_DOC_TYPES,
        TEST_REPORT_FORM_FIELDS,
    )
    assert doc_type in TEST_REPORT_DOC_TYPES
    assert "release_sw_version" in TEST_REPORT_FORM_FIELDS


# ── STS 요구-함수 매핑 ──────────────────────────────────────────────────────
#
# `generate_test_cases` 는 매핑이 빈 요구에도 TC 를 낸다(`_generate_review_steps`).
# 그래서 요구 커버리지는 100% 로 보이는데 그 TC 들은 소스 근거가 0 이다. 이 축이
# 없으면 그 사실이 어디에도 안 나온다.

def _sts_env(monkeypatch, reqs, *, srs="U:/x/SwRS.docx"):
    """SwRS 파싱을 대신한다 — docx 를 만들지 않고 매핑 규칙만 겨눈다."""
    import backend.services.resolver_helpers as _rh
    import generators.sts as _gsts
    monkeypatch.setattr(_rh, "materialize_via_resolver", lambda p: (p, ""))
    monkeypatch.setattr(_gsts, "parse_srs_docx_tables", lambda p: list(reqs))
    return srs


def test_sts_mapping_needs_the_srs_and_says_so() -> None:
    """요구 목록이 없으면 **미측정**이다 — 0 으로 그리지 않는다."""
    res = tm._measure_sts_mapping({}, {}, "", "")
    assert res["measured"] is False
    assert "SwRS" in res["reason"]


def test_sts_unmapped_splits_our_defect_from_design_gap(monkeypatch) -> None:
    """미매핑을 한 숫자로 합치면 조치 가능한 축이 안 보인다.

    실측(KJPDS02_PV): 20건 중 **16 은 SwDS 의 related 에 있다**(우리가 그 파티션에
    못 닿은 것 = 결함) · **4 는 SwDS 어디에도 없다**(설계가 안 이은 것).
    """
    srs = _sts_env(monkeypatch, [{"id": "SwTR_0001"}, {"id": "SwTR_0002"}, {"id": "SwTR_0003"}])
    fd = {"f1": {"id": "f1", "name": "S_Motor_Init", "module_name": "MotorCtrl", "related": ""}}
    sds = {
        "motorctrl": {"related": "SwTR_0001", "asil": "", "description": ""},
        # SwTR_0002 는 SwDS 가 담고 있지만 어떤 함수도 이 파티션에 못 닿는다
        "zzz_far_away": {"related": "SwTR_0002", "asil": "", "description": ""},
        # SwTR_0003 은 SwDS 어디에도 없다
    }
    res = tm._measure_sts_mapping(fd, sds, "", srs)
    assert res["measured"] is True
    assert res["mapped"] == 1 and res["requirements"] == 3
    assert res["causes"] == {"unreached_in_sds": 1, "absent_from_sds": 1}
    assert res["cause_samples"]["absent_from_sds"] == ["SwTR_0003"]


def test_sts_mapping_does_not_fall_back_to_repo_docs(monkeypatch) -> None:
    """⚠ `sds_map=None` 은 저장소 `docs/` 글롭(**프로젝트 무관**)을 쓴다.

    게이트가 그걸 쓰면 남의 프로젝트 요구 ID 로 잰 숫자를 보여 준다. 맵이 비면
    "매핑 0" 이 정답이다.
    """
    import generators.sts as _gsts
    srs = _sts_env(monkeypatch, [{"id": "SwTR_0001"}])
    called = {"n": 0}

    def _boom():
        called["n"] += 1
        return {"motorctrl": {"related": "SwTR_0001", "asil": "", "description": ""}}

    monkeypatch.setattr(_gsts, "_load_default_sds_map", _boom)
    fd = {"f1": {"id": "f1", "name": "S_Motor_Init", "module_name": "MotorCtrl", "related": ""}}
    res = tm._measure_sts_mapping(fd, {}, "SwDS 경로가 지정되지 않았습니다", srs)
    assert called["n"] == 0, "저장소 docs/ 폴백을 탔다 — 남의 프로젝트로 잰 숫자다"
    assert res["mapped"] == 0
    assert res["sds_reason"], "맵이 없는 사유를 안 실으면 0 이 결함으로만 읽힌다"


def test_sts_tc_cap_counts_functions_left_untested(monkeypatch) -> None:
    """요구당 상한이 버리는 함수를 센다. ⚠ 이 값은 **하한**이다.

    한 함수가 여러 TC 를 내면 상한이 더 일찍 차므로 실제로는 더 빠진다
    (실측: 이 계산 715 vs `generate_test_cases` 실측 887).
    """
    from generators.sts import _MAX_TC_PER_REQ

    n = _MAX_TC_PER_REQ + 3
    srs = _sts_env(monkeypatch, [{"id": "SwTR_0001"}])
    fd = {
        f"f{i}": {"id": f"f{i}", "name": f"S_Fn_{i}", "module_name": f"Mod{i}", "related": ""}
        for i in range(n)
    }
    sds = {f"mod{i}": {"related": "SwTR_0001", "asil": "", "description": ""} for i in range(n)}
    res = tm._measure_sts_mapping(fd, sds, "", srs)
    assert res["mapped_functions"] == n
    assert res["functions_beyond_cap"] == n - _MAX_TC_PER_REQ
    assert res["requirements_over_cap"] == 1


# ── SUTS 안전 등급의 근거 ───────────────────────────────────────────────────

def test_asil_denominator_excludes_tbd() -> None:
    """⚠ `asil` 은 등급을 못 찾아도 `TBD` 로 채워진다.

    진리값으로 세면 **전 unit 이 등급 있음**이 되고, "962 중 425 가 약함" 이
    "나머지는 근거가 단단하다" 로 읽힌다. 실측에서 분모가 1,157 → 962 로 바뀌었다.
    """
    units = [
        {"name": "a", "asil": "B", "asil_evidence": "sds-exact"},
        {"name": "b", "asil": "TBD", "asil_evidence": ""},
        {"name": "c", "asil": "", "asil_evidence": ""},
    ]
    assert tm._measure_suts_asil(units)["graded"] == 1


def test_fuzzy_and_conflict_are_not_merged() -> None:
    """부분문자열 매치와 **후보 등급까지 갈린 것**은 심각도가 다르다."""
    units = [
        {"name": "a", "asil": "B", "asil_evidence": "sds-fuzzy"},
        {"name": "b", "asil": "C", "asil_evidence": "sds-fuzzy-conflict"},
        {"name": "c", "asil": "D", "asil_evidence": "sds-exact"},
    ]
    res = tm._measure_suts_asil(units)
    assert (res["fuzzy"], res["fuzzy_conflict"]) == (1, 1)
    assert res["graded"] == 3


def test_exact_evidence_alone_is_clean() -> None:
    """대조군 — 근거가 정확 키뿐이면 이 축은 조용하다."""
    units = [{"name": "a", "asil": "B", "asil_evidence": "sds-exact"}]
    res = tm._measure_suts_asil(units)
    assert (res["fuzzy"], res["fuzzy_conflict"]) == (0, 0)


def test_units_are_collected_once_and_shared() -> None:
    """⚠ `collect_unit_functions` 는 이 측정에서 가장 비싼 단계다.

    입력 축과 ASIL 축이 따로 부르면 비용이 두 배고, 그 사이 규칙이 갈리면 두 패널이
    **서로 다른 unit 목록**을 보여 준다(`_dir_tag` 주석의 전례).
    """
    fd = {"a": _unit("s_SysMain_Init")}
    got: list = []
    res = tm._measure_suts_inputs(fd, {}, units_out=got)
    assert res["measured"] is True
    assert len(got) == res["units"] and got, "units_out 이 안 채워졌다"


# ── 설계-ID 브리지 — 게이트가 산출물과 **같은 조건**으로 재는가 ──────────────

def test_sts_mapping_reports_the_bridge_is_off(monkeypatch) -> None:
    """SwUDS 를 안 주면 브리지가 꺼진다 — 그 사실을 **말해야** 한다.

    안 그러면 `unreached_in_sds` 가 코드 결함처럼 읽히는데, 실제로는 입력을 안 준
    것일 수 있다(실측 KJPDS02_PV: 요구 48/68 vs 64/68 = 16 요구 차이).
    """
    srs = _sts_env(monkeypatch, [{"id": "SwTR_0001"}])
    res = tm._measure_sts_mapping({}, {}, "", srs)
    assert res["bridge"]["on"] is False
    assert "SwUDS" in res["bridge"]["reason"]


def test_sts_mapping_turns_the_bridge_on_with_uds(monkeypatch, tmp_path) -> None:
    """SwUDS 를 주면 설계 파티션에만 걸린 요구가 매핑된다."""
    docx = pytest.importorskip("docx")
    d = docx.Document()
    tb = d.add_table(rows=4, cols=3)
    for i, (label, value) in enumerate([("[ Function Information ]", ""), ("ID", "SwUFn_0101"),
                                        ("Name", "S_Motor_Init"), ("Related ID", "SwFn_30")]):
        tb.rows[i].cells[0].text = label
        tb.rows[i].cells[2].text = value
    uds = tmp_path / "uds.docx"
    d.save(str(uds))

    srs = _sts_env(monkeypatch, [{"id": "SwTR_0606"}])
    fd = {"f1": {"id": "f1", "name": "S_Motor_Init", "module_name": "MotorCtrl", "related": ""}}
    # 설계 ID 키 — 함수 이름 사슬로는 구조적으로 못 닿는다
    sds = {"swfn_30": {"kind": "design_id", "related": "SwTR_0606"}}

    off = tm._measure_sts_mapping(fd, sds, "", srs)
    assert off["mapped"] == 0 and off["causes"] == {"unreached_in_sds": 1}

    on = tm._measure_sts_mapping(fd, sds, "", srs, str(uds))
    assert on["bridge"] == {"on": True, "functions": 1}
    assert on["mapped"] == 1 and on["causes"] == {}


def test_measure_passes_uds_path_through(monkeypatch) -> None:
    """`measure()` 가 uds_path 를 흘리지 않으면 게이트만 브리지가 꺼진다.

    ⚠ 헬퍼 단독 테스트는 호출부가 값을 버리는 것을 못 본다 — 여기서 배선을 본다.
    """
    seen = {}

    def _fake(fd, sds_map, sds_reason, srs_path, uds_path=""):
        seen["uds"] = uds_path
        return {"measured": False, "reason": "stub"}

    monkeypatch.setattr(tm, "_measure_sts_mapping", _fake)
    monkeypatch.setattr(tm, "_load_sds_map", lambda p: ({}, ""))
    monkeypatch.setattr(tm, "_measure_sits", lambda *a, **k: {})
    monkeypatch.setattr(tm, "_measure_suts_types", lambda *a, **k: {})
    monkeypatch.setattr(tm, "_measure_suts_inputs", lambda *a, **k: {})
    monkeypatch.setattr(tm, "_measure_suts_asil", lambda *a, **k: {})
    import report_generator as _rg
    monkeypatch.setattr(_rg, "generate_uds_source_sections",
                        lambda root: {"function_details": {"f": {"name": "f"}}})
    tm.clear_cache()
    tm.measure("C:/src", sds_path="s.docx", srs_path="r.docx", uds_path="u.docx")
    assert seen["uds"] == "u.docx"
