from __future__ import annotations


def test_build_function_module_index_prefers_source_file():
    from workflow.function_module_map import build_function_module_index

    index = build_function_module_index(
        {"ap_doorctrl_pds": "HEADER"},
        changed_files=["Sources/APP/Ap_DoorCtrl_PDS.c"],
    )

    info = index["ap_doorctrl_pds"]
    assert info["best_module"] == "DoorCtrl"
    assert info["best_confidence"] >= 0.88


def test_build_function_module_index_handles_buzzer_function():
    from workflow.function_module_map import build_function_module_index

    index = build_function_module_index(
        {"s_buzzerctrl_on": "BODY"},
        changed_files=["Sources/APP/Ap_BuzzerCtrl_PDS.c"],
    )

    info = index["s_buzzerctrl_on"]
    assert info["best_module"] == "BuzzerCtrl"
