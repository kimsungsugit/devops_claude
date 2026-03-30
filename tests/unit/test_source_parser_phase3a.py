from __future__ import annotations

from report_gen.source_parser import (
    _extract_c_global_candidates,
    _extract_local_static_candidates,
    _extract_fallback_call_names,
    _extract_macro_call_names,
    _extract_function_pointer_call_targets,
)


def test_extract_c_global_candidates_handles_multi_decl_and_function_pointer():
    text = """
    static volatile const uint8 a, *b, c[4];
    extern FooType g_state;
    STATIC void (*pfCb)(void) = 0;
    """

    items = {item["name"]: item for item in _extract_c_global_candidates(text)}

    assert "a" in items
    assert items["a"]["static"] == "true"
    assert "b" in items
    assert "c" in items
    assert "g_state" in items
    assert items["g_state"]["extern"] == "true"
    assert "pfCb" in items


def test_extract_local_static_candidates_handles_macro_and_multi_decl():
    body = """
    static uint8 s_a, s_b;
    FAST_STATIC uint16 s_counter = 0U;
    STATIC void (*pfCb)(void) = 0;
    """

    names = _extract_local_static_candidates(body)

    assert "s_a" in names
    assert "s_b" in names
    assert "s_counter" in names
    assert "pfCb" in names


def test_extract_fallback_call_names_filters_keywords_and_unknown_calls():
    source = """
    void Caller(void)
    {
        if (cond) {
            Helper();
            UNKNOWN();
        }
        return;
    }
    """

    names = _extract_fallback_call_names(
        source,
        "Caller",
        {"Caller", "Helper", "Worker"},
    )

    assert names == ["Helper"]


def test_extract_c_global_candidates_skips_typedef_aliases():
    text = """
    typedef unsigned char U8;
    typedef unsigned short l_u16;
    static U8 s_counter;
    """

    items = {item["name"]: item for item in _extract_c_global_candidates(text)}

    assert "U8" not in items
    assert "l_u16" not in items
    assert "s_counter" in items


def test_extract_macro_call_names_collects_macro_targets():
    body = """
    UPDATE_PWM(3U);
    if (flag) {
        DO_WORK();
    }
    """

    names = _extract_macro_call_names(
        body,
        {
            "UPDATE_PWM": ["MotorPwm_SetRatio"],
            "DO_WORK": ["Worker_Run", "Worker_Notify"],
        },
    )

    assert names == ["MotorPwm_SetRatio", "Worker_Run", "Worker_Notify"]


def test_extract_function_pointer_call_targets_resolves_simple_alias_assignment():
    body = """
    pfCb = MotorPwm_SetRatio;
    if (pfCb != 0) {
        pfCb();
    }
    """

    names = _extract_function_pointer_call_targets(
        body,
        {"MotorPwm_SetRatio", "OtherFunc"},
    )

    assert names == ["MotorPwm_SetRatio"]
