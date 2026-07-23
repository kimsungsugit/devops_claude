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


def test_load_suts_fn_tcs_warns_only_on_unit_drops(monkeypatch):
    """유닛 누락 경고는 unit을 실제로 떨어뜨리는 코드(empty_test_case_block/missing_unit_name)만
    센다. empty_expected(입력전용 시퀀스 등 무해)를 합산하면 오경보 — 전용 파서 컬럼탐지 수정으로
    empty_expected가 다수(994)가 됐을 때 '유닛 누락 가능' 허위 경보가 났던 회귀를 가드."""
    import backend.services.file_resolver as fr
    import tools.export_suts_vectorcast as ev
    from workflow.impact_orchestrator import _load_suts_fn_tcs

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())

    # (a) empty_expected만 다수 → 유닛 누락 경고 없음(오경보 방지)
    monkeypatch.setattr(ev, "build_vectorcast_model", lambda *a, **k: {
        "units": [{"unit_name": "s_foo", "test_cases": [{"base_tc_id": "TC1"}]}],
        "export_warnings": [{"code": "empty_expected", "message": "x"}] * 994,
    })
    warns_a: list = []
    _load_suts_fn_tcs("U:/s.xlsm", ["s_foo"], warn_sink=warns_a)
    assert not any("유닛 누락" in w for w in warns_a)

    # (b) 드롭 코드는 경고(개수는 무해 코드 제외 정확)
    monkeypatch.setattr(ev, "build_vectorcast_model", lambda *a, **k: {
        "units": [{"unit_name": "s_foo", "test_cases": [{"base_tc_id": "TC1"}]}],
        "export_warnings": [
            {"code": "empty_test_case_block", "message": "x"},
            {"code": "missing_unit_name", "message": "y"},
            {"code": "empty_expected", "message": "z"},  # 무해분 — 개수에서 제외돼야
        ],
    })
    warns_b: list = []
    _load_suts_fn_tcs("U:/s.xlsm", ["s_foo"], warn_sink=warns_b)
    drop_warn = [w for w in warns_b if "유닛 누락" in w]
    assert len(drop_warn) == 1
    assert "2건" in drop_warn[0]  # empty_expected 제외, 드롭 2건만


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


def test_load_sits_fn_chains_content_sink_keeps_tc_content(monkeypatch):
    """content_sink 제공 시 중간 JSON의 sub_cases(precondition/inputs/expected)를 TC-ID 키로 채우고,
    회귀 반환({entry_fn:[label]})은 flagged 함수만 유지(불변)."""
    import json
    import backend.services.file_resolver as fr
    from workflow.impact_orchestrator import _load_sits_fn_chains

    intermediate = {
        "integrations": [
            {
                "tc_id": "SwITC_SwUFn_0203",
                "entry_fn": "s_main",
                "call_chain": "s_main -> s_helper",
                "sub_cases": [
                    {"precondition": "system on", "inputs": {"a": 1, "empty": ""}, "expected": {"ret": 0}},
                ],
            },
            {   # entry_fn이 flagged 아님 — 회귀 result엔 없으나 내용(content_sink)엔 담겨야(프론트 TC-ID 조인).
                "tc_id": "SwITC_SwUFn_0999",
                "entry_fn": "s_other",
                "call_chain": "s_other -> x",
                "sub_cases": [],
            },
        ],
    }
    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver(json.dumps(intermediate).encode("utf-8")))

    sink: dict = {}
    result = _load_sits_fn_chains("U:/proj_SITS.xlsm", ["s_main"], content_sink=sink)

    # 회귀 반환: flagged(s_main)만
    assert result == {"s_main": ["SwITC_SwUFn_0203: s_main -> s_helper"]}
    # 내용: 전체 TC(entry_fn 무관), TC-ID 정규화(공백제거+대문자) 키
    assert "SWITC_SWUFN_0203" in sink
    assert "SWITC_SWUFN_0999" in sink
    c = sink["SWITC_SWUFN_0203"]
    assert c["call_chain"] == "s_main -> s_helper"
    assert c["sub_cases"][0]["precondition"] == "system on"
    assert c["sub_cases"][0]["inputs"] == {"a": "1"}    # empty 스킵, 문자열화
    assert c["sub_cases"][0]["expected"] == {"ret": "0"}


def test_load_sits_fn_chains_without_sink_unchanged(monkeypatch):
    """content_sink 미제공 시 회귀 반환만(순수 additive)."""
    import json
    import backend.services.file_resolver as fr
    from workflow.impact_orchestrator import _load_sits_fn_chains

    intermediate = {"integrations": [
        {"tc_id": "T1", "entry_fn": "s_a", "call_chain": "s_a", "sub_cases": []},
    ]}
    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver(json.dumps(intermediate).encode("utf-8")))
    assert _load_sits_fn_chains("U:/s.xlsm", ["s_a"]) == {"s_a": ["T1: s_a"]}


def test_load_testspec_by_tc_parses_and_normalizes(monkeypatch):
    """STS/SITS xlsm을 parse_swuts_xlsm로 파싱해 TC-ID 정규화 키 내용 맵을 반환."""
    import backend.services.file_resolver as fr
    import backend.services.swuts_excel_parser as sp
    from workflow.impact_orchestrator import _load_testspec_by_tc

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver(b"xlsm-bytes"))

    class _E:
        description = "STS: verify boundary"
        precondition = "init done"
        test_method = "REQ"
        unit_name = "s_foo"

    class _Res:
        ok = True
        by_tc_id = {"SwTC_ 01": _E()}   # 내부 공백 포함 — 정규화로 제거돼야

    monkeypatch.setattr(sp, "parse_swuts_xlsm", lambda *a, **k: _Res())
    out = _load_testspec_by_tc("U:/sts.xlsm", doc_label="STS")
    assert "SWTC_01" in out
    assert out["SWTC_01"]["description"] == "STS: verify boundary"
    assert out["SWTC_01"]["test_method"] == "REQ"
    assert out["SWTC_01"]["unit_name"] == "s_foo"


def test_load_testspec_by_tc_honest_miss_on_parser_fail(monkeypatch):
    """파서 미매칭(ok=False)이면 빈 dict + 사유 warn(과대추정 금지, 정직 '미파싱')."""
    import backend.services.file_resolver as fr
    import backend.services.swuts_excel_parser as sp
    from workflow.impact_orchestrator import _load_testspec_by_tc

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver(b"xlsm-bytes"))

    class _Res:
        ok = False
        by_tc_id: dict = {}

    monkeypatch.setattr(sp, "parse_swuts_xlsm", lambda *a, **k: _Res())
    warns: list = []
    out = _load_testspec_by_tc("U:/x.xlsm", warn_sink=warns, doc_label="STS")
    assert out == {}
    assert any("미파싱" in w for w in warns)


def test_load_testspec_by_tc_empty_on_no_path():
    from workflow.impact_orchestrator import _load_testspec_by_tc
    assert _load_testspec_by_tc("", doc_label="SITS") == {}
