"""문서 내용 매칭(doc_content) 로더 — 예측 대신 실 파싱 내용을 보존/추출하는지 검증.

라운드: 함수별 상세 문서 카드가 '원본 heading 확인' 같은 예측 대신 실제 UDS/SUTS/SDS 내용을
표시하도록, impact 오케스트레이터 로더가 이미 파싱한 내용을 버리지 않고 반환하는지 확인한다.
"""
from __future__ import annotations


class _FakeResolver:
    def __init__(self, data: bytes = b"docx-bytes"):
        self._data = data

    def read_bytes(self, path: str) -> bytes:  # noqa: ARG002
        return self._data


def test_load_suts_fn_tcs_content_sink_keeps_tc_content(monkeypatch):
    """content_sink 제공 시 TC 실내용(action/precondition/inputs/expected)을 채우고,
    회귀 반환({fn:[tc_id]})은 불변임을 확인."""
    import backend.services.file_resolver as fr
    import tools.export_suts_vectorcast as ev
    from workflow.impact_orchestrator import _load_suts_fn_tcs

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    fake_model = {
        "units": [{
            "unit_name": "s_foo",
            "test_cases": [{
                "base_tc_id": "SwUTC_SwUFn_0001",
                "description": "Call s_foo with boundary x",
                "precondition": "system initialized",
                "inputs": {"x": 1, "empty": ""},   # empty 값은 스킵돼야
                "expected": {"ret": 42},
            }],
        }],
        "export_warnings": [],
    }
    monkeypatch.setattr(ev, "build_vectorcast_model", lambda *a, **k: fake_model)

    sink: dict = {}
    result = _load_suts_fn_tcs("U:/suts.xlsm", ["s_foo"], content_sink=sink)

    # 회귀 반환 불변
    assert result == {"s_foo": ["SwUTC_SwUFn_0001"]}
    # 내용 보존
    assert "s_foo" in sink
    tc = sink["s_foo"][0]
    assert tc["tc_id"] == "SwUTC_SwUFn_0001"
    assert tc["action"] == "Call s_foo with boundary x"
    assert tc["precondition"] == "system initialized"
    assert tc["inputs"] == {"x": "1"}          # 실입력, empty 스킵, 문자열화
    assert tc["expected"] == {"ret": "42"}     # 실기대값


def test_load_suts_fn_tcs_without_sink_unchanged(monkeypatch):
    """content_sink 미제공 시 종전과 동일(회귀 반환만) — 순수 additive 확인."""
    import backend.services.file_resolver as fr
    import tools.export_suts_vectorcast as ev
    from workflow.impact_orchestrator import _load_suts_fn_tcs

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(ev, "build_vectorcast_model", lambda *a, **k: {
        "units": [{"unit_name": "s_bar", "test_cases": [{"base_tc_id": "TC1"}]}],
        "export_warnings": [],
    })
    assert _load_suts_fn_tcs("U:/s.xlsm", ["s_bar"]) == {"s_bar": ["TC1"]}


def test_load_uds_fn_details_widened(monkeypatch):
    """사이드카 payload의 globals/calls/prototype 필드가 surface에 포함(widen)됨을 확인."""
    from workflow import impact_orchestrator as m
    from workflow.impact_orchestrator import _load_uds_fn_details

    monkeypatch.setattr(m, "_safe_exists", lambda p: True)
    monkeypatch.setattr(m, "_load_json", lambda p: {
        "function_details_by_name": {
            "s_foo": {
                "description": "Foo does X",
                "prototype": "void s_foo(uint8 x)",
                "globals_global": ["g_State"],
                "globals_static": ["s_Cnt"],
                "calls_list": ["s_helper"],
                "called": ["s_main"],
                "asil": "B",
            },
        },
    })
    out = _load_uds_fn_details("gen/uds.docx", ["s_foo"])
    assert out["s_foo"]["description"] == "Foo does X"
    assert out["s_foo"]["prototype"] == "void s_foo(uint8 x)"
    assert set(out["s_foo"]["globals"]) == {"g_State", "s_Cnt"}
    assert set(out["s_foo"]["calls"]) == {"s_helper", "s_main"}


def test_load_sds_fn_desc_extracts_description(monkeypatch):
    """SDS 파티션맵의 함수별 description을 영향 함수와 매칭해 반환."""
    import backend.services.file_resolver as fr
    import report_gen.requirements as rq
    from workflow.impact_orchestrator import _load_sds_fn_desc

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(rq, "_extract_sds_partition_map", lambda p: {
        "s_foo": {"description": "SDS: foo handles motor control", "kind": "function"},
        "swcom_10": {"description": "unrelated component", "kind": "component"},
    })
    out = _load_sds_fn_desc("U:/sds.docx", ["s_foo"])
    assert out == {"s_foo": "SDS: foo handles motor control"}   # 영향 함수만, 무관 컴포넌트 제외


def test_load_sds_fn_desc_empty_on_no_path():
    from workflow.impact_orchestrator import _load_sds_fn_desc
    assert _load_sds_fn_desc("", ["s_foo"]) == {}
