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


def test_load_suts_fn_tcs_forwards_source_loc(monkeypatch):
    """content_sink 제공 시 exporter가 test_case["source"]로 부여한 시트·행 위치(loc)를
    전달하는지 — 문서 카드가 'TC(행 N)를 이렇게 수정' 앵커를 표시하게 한다.
    회귀 반환({fn:[tc_id]})은 불변(순수 additive)."""
    import backend.services.file_resolver as fr
    import tools.export_suts_vectorcast as ev
    from workflow.impact_orchestrator import _load_suts_fn_tcs

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(ev, "build_vectorcast_model", lambda *a, **k: {
        "units": [{
            "unit_name": "s_foo",
            "test_cases": [{
                "base_tc_id": "SwUTC_SwUFn_0001",
                "expected": {"ret": 42},
                "source": {"sheet": "2.SW Unit Test Spec", "tc_row": 42, "sequence_row": 43},
            }],
        }],
        "export_warnings": [],
    })

    sink: dict = {}
    result = _load_suts_fn_tcs("U:/suts.xlsm", ["s_foo"], content_sink=sink)

    assert result == {"s_foo": ["SwUTC_SwUFn_0001"]}   # 회귀 반환 불변
    assert sink["s_foo"][0]["loc"] == {
        "sheet": "2.SW Unit Test Spec", "tc_row": 42, "sequence_row": 43,
    }


def test_load_suts_fn_tcs_no_source_omits_loc(monkeypatch):
    """source가 없으면 loc 키를 만들지 않는다(행 번호 날조 금지 — 정직 표기)."""
    import backend.services.file_resolver as fr
    import tools.export_suts_vectorcast as ev
    from workflow.impact_orchestrator import _load_suts_fn_tcs

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(ev, "build_vectorcast_model", lambda *a, **k: {
        "units": [{
            "unit_name": "s_foo",
            "test_cases": [{"base_tc_id": "TC1", "expected": {"ret": 1}}],
        }],
        "export_warnings": [],
    })

    sink: dict = {}
    _load_suts_fn_tcs("U:/s.xlsm", ["s_foo"], content_sink=sink)
    assert sink["s_foo"][0]["tc_id"] == "TC1"
    assert "loc" not in sink["s_foo"][0]


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


def test_load_suts_fn_tcs_isolates_malformed_unit(monkeypatch):
    """B2: 기형 유닛(예외 유발) 하나가 전체 회귀집합을 무너뜨리지 않고 격리되며, 나머지 정상 유닛은
    집계되고 사유(N건 예외)가 warn_sink에 표면화된다(silent-0 방지)."""
    import backend.services.file_resolver as fr
    import tools.export_suts_vectorcast as ev
    from workflow.impact_orchestrator import _load_suts_fn_tcs

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(ev, "build_vectorcast_model", lambda *a, **k: {
        "units": [
            "not-a-dict",  # 기형: dict 아님 → 격리
            {"unit_name": "s_ok", "test_cases": [{"base_tc_id": "TC_OK"}]},  # 정상
        ],
        "export_warnings": [],
    })
    warns: list = []
    result = _load_suts_fn_tcs("U:/s.xlsm", ["s_ok"], warn_sink=warns)
    assert result == {"s_ok": ["TC_OK"]}                        # 정상 유닛은 유실 없이 집계
    assert any("예외로 건너뜀" in w for w in warns)              # 격리 사유 표면화(silent 아님)


def test_load_suts_fn_tcs_happy_path_no_exc_warn(monkeypatch):
    """B2: 모든 유닛 정상이면 예외 warn이 없고 결과는 종전과 byte 동일(happy-path 불변)."""
    import backend.services.file_resolver as fr
    import tools.export_suts_vectorcast as ev
    from workflow.impact_orchestrator import _load_suts_fn_tcs

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(ev, "build_vectorcast_model", lambda *a, **k: {
        "units": [{"unit_name": "s_ok", "test_cases": [{"base_tc_id": "TC_OK"}]}],
        "export_warnings": [],
    })
    warns: list = []
    assert _load_suts_fn_tcs("U:/s.xlsm", ["s_ok"], warn_sink=warns) == {"s_ok": ["TC_OK"]}
    assert not any("예외로 건너뜀" in w for w in warns)


def test_load_suts_fn_tcs_counts_malformed_row_in_good_unit(monkeypatch):
    """reviewer #4: 정상 유닛 내부의 기형 TC 행(dict 아님)은 조용히 걸러졌었다 — 이제 개수를 집계해
    '행 N건 형식 이상' warn으로 표면화한다(정직화 완성). 같은 유닛의 정상 행은 손실 없이 유지."""
    import backend.services.file_resolver as fr
    import tools.export_suts_vectorcast as ev
    from workflow.impact_orchestrator import _load_suts_fn_tcs

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(ev, "build_vectorcast_model", lambda *a, **k: {
        "units": [{"unit_name": "s_ok", "test_cases": [
            {"base_tc_id": "TC_OK"},   # 정상 행 — 유지돼야
            "not-a-dict-row",          # 기형 행 — 격리+집계
        ]}],
        "export_warnings": [],
    })
    warns: list = []
    result = _load_suts_fn_tcs("U:/s.xlsm", ["s_ok"], warn_sink=warns)
    assert result == {"s_ok": ["TC_OK"]}                           # 정상 행은 유실 없음
    assert any("행 1건 형식 이상" in w for w in warns)              # 기형 행 표면화(silent 아님)


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


def test_load_suts_fn_tcs_signature_unit_name_keyed_by_bare(monkeypatch):
    """HDPDM01: unit_name이 전체 C 시그니처면 bare 식별자로 키잉해야 프론트/스코프 필터(_direct_lc,
    bare 함수명)가 조인된다. 과거엔 시그니처 그대로 키잉→매칭 실패로 카드 '미파싱'·회귀 TC 0이 됐다.
    KJPDS02(bare)는 idempotent라 무변경."""
    import backend.services.file_resolver as fr
    import tools.export_suts_vectorcast as ev
    from workflow.impact_orchestrator import _load_suts_fn_tcs

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(ev, "build_vectorcast_model", lambda *a, **k: {
        "units": [{
            "unit_name": "void g_SysOs_WdiCtrl( void )",   # 시그니처(HDPDM01 실 doc 형태)
            "test_cases": [{"base_tc_id": "SwUTC_SwUFn_0001",
                            "inputs": {"a": 1}, "expected": {"r": 2}}],
        }],
        "export_warnings": [],
    })

    sink: dict = {}
    result = _load_suts_fn_tcs("U:/hdpdm01.xlsm", ["g_SysOs_WdiCtrl"], content_sink=sink)
    # bare 키로 저장 → _direct_lc(bare 함수명) 매칭 가능(과거 시그니처 키라 실패)
    assert result == {"g_SysOs_WdiCtrl": ["SwUTC_SwUFn_0001"]}
    assert "g_SysOs_WdiCtrl" in sink
    assert "void g_SysOs_WdiCtrl( void )" not in sink   # 시그니처 그대로 키잉하지 않음
    assert sink["g_SysOs_WdiCtrl"][0]["inputs"] == {"a": "1"}


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


def test_load_uds_fn_content_fallback_extracts_prototype(monkeypatch):
    """링크(cloudium) UDS fallback(parse_swuds_docx)이 표의 Prototype을 채운다.

    사이드카 없는 경로 — 예전엔 {description,heading}만 → prototype 조용히 빔. 이제 표에
    Prototype 행이 있으면 채워, 영향분석 UDS 카드가 실 선언 표시 + 원문→변경안 기준선 확보.
    """
    import io as _io

    import backend.services.file_resolver as fr
    from docx import Document  # type: ignore
    from workflow.impact_orchestrator import _load_uds_fn_content

    # 실제 docx: heading + 표(Name/Prototype/Description) — 사이드카 없음(fallback 경로)
    doc = Document()
    doc.add_paragraph("SwUFn_1150 — s_TunningParamRead_16bitData")
    tbl = doc.add_table(rows=3, cols=2)
    for r, (k, v) in enumerate([
        ("Name", "s_TunningParamRead_16bitData"),
        ("Prototype", "void s_TunningParamRead_16bitData(void)"),
        ("Description", "튜닝 파라미터를 16bit로 읽어 반환"),
    ]):
        tbl.cell(r, 0).text = k
        tbl.cell(r, 1).text = v
    buf = _io.BytesIO()
    doc.save(buf)
    docx_bytes = buf.getvalue()

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver(docx_bytes))
    # 고유 경로(모듈 캐시 _UDS_CONTENT_CACHE 오염 회피) + 사이드카 부재로 fallback 강제
    out = _load_uds_fn_content("U:/link_proto_test.docx", ["s_tunningparamread_16bitdata"])
    key = "s_tunningparamread_16bitdata"
    assert key in out
    assert out[key]["prototype"] == "void s_TunningParamRead_16bitData(void)"
    assert "튜닝 파라미터를 16bit" in out[key]["description"]


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


def test_load_sds_fn_desc_prefix_tolerant_match(monkeypatch):
    """flagged 's_tunningparamread' vs SDS 인터페이스명 'TunningParamRead'(접두어 없음) 매칭.

    exact miss여도 엔지니어링 접두어(s_/g_ 등) 정규화 대조로 SDS description을 찾는다.
    """
    import backend.services.file_resolver as fr
    import report_gen.requirements as rq
    from workflow.impact_orchestrator import _load_sds_fn_desc

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(rq, "_extract_sds_partition_map", lambda p: {
        "tunningparamread_16bitdata": {
            "description": "16비트 튜닝 파라미터를 읽는다", "kind": "function",
        },
    })
    out = _load_sds_fn_desc("U:/sds.docx", ["s_TunningParamRead_16bitData"])
    # 키는 flagged fn(소문자) — 프론트 docContentFor 조회 키와 일치
    assert out == {"s_tunningparamread_16bitdata": "16비트 튜닝 파라미터를 읽는다"}


def test_load_sds_fn_desc_component_description_fallback(monkeypatch):
    """인터페이스 행 description이 비면 소속 컴포넌트 설명으로 폴백(출처 라벨링)."""
    import backend.services.file_resolver as fr
    import report_gen.requirements as rq
    from workflow.impact_orchestrator import _load_sds_fn_desc

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(rq, "_extract_sds_partition_map", lambda p: {
        "s_foo": {
            "description": "", "component_description": "모터 제어 컴포넌트", "kind": "function",
        },
    })
    out = _load_sds_fn_desc("U:/sds.docx", ["s_foo"])
    assert out == {"s_foo": "(컴포넌트 설명) 모터 제어 컴포넌트"}


def test_load_sds_fn_desc_exact_match_wins_over_normalized(monkeypatch):
    """exact match가 접두어 정규화보다 우선(기존 동작 유지 — 정확 함수 설명 채택)."""
    import backend.services.file_resolver as fr
    import report_gen.requirements as rq
    from workflow.impact_orchestrator import _load_sds_fn_desc

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(rq, "_extract_sds_partition_map", lambda p: {
        "s_foo": {"description": "정확 매칭 설명", "kind": "function"},
        "foo": {"description": "정규화 매칭 설명", "kind": "function"},
    })
    out = _load_sds_fn_desc("U:/sds.docx", ["s_foo"])
    assert out == {"s_foo": "정확 매칭 설명"}


def test_load_sds_fn_desc_normalized_collision_excluded(monkeypatch):
    """정규화 후 서로 다른 원본이 겹치면 모호 → 제외(잘못된 설명 붙이지 않음)."""
    import backend.services.file_resolver as fr
    import report_gen.requirements as rq
    from workflow.impact_orchestrator import _load_sds_fn_desc

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    # 's_bar'와 'g_bar' 모두 정규화하면 'bar' → 충돌 → 접두어 매칭 포기
    monkeypatch.setattr(rq, "_extract_sds_partition_map", lambda p: {
        "s_bar": {"description": "설명 A", "kind": "function"},
        "g_bar": {"description": "설명 B", "kind": "function"},
    })
    out = _load_sds_fn_desc("U:/sds.docx", ["u8g_bar"])  # exact miss + 정규화 충돌
    assert out == {}


def test_load_sds_fn_desc_normalized_only_matches_functions(monkeypatch):
    """정규화 대조는 함수 엔트리만 — 컴포넌트 키로 오귀속하지 않는다."""
    import backend.services.file_resolver as fr
    import report_gen.requirements as rq
    from workflow.impact_orchestrator import _load_sds_fn_desc

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(rq, "_extract_sds_partition_map", lambda p: {
        "foo": {"description": "컴포넌트 설명", "kind": "component"},
    })
    out = _load_sds_fn_desc("U:/sds.docx", ["s_foo"])  # 정규화하면 'foo'지만 컴포넌트라 제외
    assert out == {}


def test_load_sds_fn_desc_domain_prefix_not_stripped(monkeypatch):
    """도메인 접두어(spi_/adc_)는 벗기지 않는다 — [sgl]_ 조건 불충족(X7 오귀속 차단).

    열린 `^[a-z]{1,4}_`였다면 spi_read·adc_read 둘 다 'read'로 정규화돼 flagged spi_read가
    adc_read 설명을 조용히 집었다. 닫힌 헝가리안 패턴은 둘 다 원형 유지 → exact miss → 미매칭.
    """
    import backend.services.file_resolver as fr
    import report_gen.requirements as rq
    from workflow.impact_orchestrator import _load_sds_fn_desc

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(rq, "_extract_sds_partition_map", lambda p: {
        "adc_read": {"description": "ADC 읽기 설명", "kind": "function"},
    })
    # flagged 'spi_read'는 adc_read와 무관 — 닫힌 패턴은 'spi_'를 접두어로 안 봄 → 오귀속 없음
    out = _load_sds_fn_desc("U:/sds.docx", ["spi_read"])
    assert out == {}


def test_load_sds_fn_desc_normalized_3way_collision_excluded(monkeypatch):
    """3개+ 원본이 같은 정규화 키로 충돌해도 정확히 제외(set 기반, 2개째부터 영구 충돌)."""
    import backend.services.file_resolver as fr
    import report_gen.requirements as rq
    from workflow.impact_orchestrator import _load_sds_fn_desc

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(rq, "_extract_sds_partition_map", lambda p: {
        "s_bar": {"description": "설명 A", "kind": "function"},
        "g_bar": {"description": "설명 B", "kind": "function"},
        "l_bar": {"description": "설명 C", "kind": "function"},  # 3번째도 'bar'로 충돌
    })
    out = _load_sds_fn_desc("U:/sds.docx", ["u8g_bar"])  # exact miss + 3-way 정규화 충돌
    assert out == {}


def test_load_sds_fn_desc_hungarian_return_type_prefix(monkeypatch):
    """반환형+저장클래스 접두어(u8g_/s16g_)도 정규화 매칭된다(닫힌 집합 내)."""
    import backend.services.file_resolver as fr
    import report_gen.requirements as rq
    from workflow.impact_orchestrator import _load_sds_fn_desc

    monkeypatch.setattr(fr, "get_resolver", lambda: _FakeResolver())
    monkeypatch.setattr(rq, "_extract_sds_partition_map", lambda p: {
        "syseepromctrl_readbyte": {"description": "EEPROM 바이트 읽기", "kind": "function"},
    })
    # u8g_SysEepromCtrl_ReadByte → 'u8g_' 제거 → syseepromctrl_readbyte 매칭
    out = _load_sds_fn_desc("U:/sds.docx", ["u8g_SysEepromCtrl_ReadByte"])
    assert out == {"u8g_syseepromctrl_readbyte": "EEPROM 바이트 읽기"}


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


# ── _build_doc_proposal: 문서 생성기(suts/sits/sts) 재사용으로 시험 초안 합성 ──
# 배선 로직(스코프/캡/graceful/예외격리/마커보존)을 생성기 스텁으로 격리 검증한다.
# (실 생성기 통합은 라이브 소스섹션 캐시로 별도 확인 — generate_sequences 실산출 검증)

def _proposal_sections(fd=None, gim=None):
    """generate_uds_source_sections 산출물 형태(function_details/globals_info_map) 최소 모사."""
    return {"function_details": fd or {}, "globals_info_map": gim or {}}


def _stub_generators(monkeypatch, *, suts_seq=None, sits_flows=None, sts_steps=None):
    """suts/sits/sts 생성기를 결정론 스텁으로 대체(배선만 격리)."""
    import generators.sits as gsits
    import generators.sts as gsts
    import generators.suts as gsuts
    monkeypatch.setattr(
        gsuts, "collect_unit_functions",
        lambda fdmap, gim=None: [{"name": info["name"]} for info in fdmap.values() if isinstance(info, dict)],
    )
    monkeypatch.setattr(
        gsuts, "generate_sequences",
        lambda unit, max_seq=6, type_cache=None: (suts_seq if suts_seq is not None
                                                  else [{"strategy": "BV_MIN", "inputs": {"x": 0}, "expected": {"ret": 0}, "description": "d"}]),
    )
    monkeypatch.setattr(
        gsits, "collect_integration_flows",
        lambda fdmap, max_flows=120: (sits_flows if sits_flows is not None
                                      else [{"entry_fn": "s_foo", "call_chain": "s_foo -> s_dep"}]),
    )
    monkeypatch.setattr(
        gsits, "generate_itc_list",
        lambda flows, **k: [{"entry_fn": f["entry_fn"], "call_chain": f["call_chain"],
                             "sub_cases": [{"inputs": {"x": 0}, "expected": {"ret": 0}, "precondition": "p"}]}
                            for f in flows],
    )
    monkeypatch.setattr(
        gsts, "_generate_steps_from_flow",
        lambda lf, info: (sts_steps if sts_steps is not None else [[{"action": "call s_foo", "expected": "ok"}]]),
    )


def test_build_doc_proposal_reuses_generators_scoped_to_changed(monkeypatch):
    """직접 변경 함수에 대해 suts/sits/sts 생성기를 재사용해 콜체인·경계값 입력·기대출력을 합성하고,
    changed_set 밖 함수(s_bar)는 초안에 포함하지 않는다(스코프)."""
    from workflow.impact_orchestrator import _build_doc_proposal

    fd = {
        "f1": {"name": "s_foo", "prototype": "U16 s_foo(U16 x)", "logic_flow": [], "calls_list": []},
        "f2": {"name": "s_bar", "prototype": "void s_bar(void)", "logic_flow": [], "calls_list": []},
    }
    # SUTS 스텁이 s_foo·s_bar 둘 다 반환해도 changed_set(s_foo) 밖은 필터돼야
    _stub_generators(monkeypatch, suts_seq=[{"strategy": "BV_MIN", "inputs": {"x": 0}, "expected": {"ret": 0}, "description": "d"}])
    out = _build_doc_proposal(_proposal_sections(fd), {"s_foo"})

    assert list(out["suts"].keys()) == ["s_foo"]                      # s_bar 제외(스코프)
    assert out["suts"]["s_foo"][0]["inputs"] == {"x": 0}
    assert out["suts"]["s_foo"][0]["expected"] == {"ret": 0}           # 기대출력 합성
    assert out["sits"]["s_foo"]["call_chain"] == "s_foo -> s_dep"      # 실 통합 콜체인
    assert out["sits"]["s_foo"]["sub_cases"][0]["expected"] == {"ret": 0}
    assert out["sts"]["s_foo"][0][0]["action"] == "call s_foo"          # 시험 절차 스텝


def test_build_doc_proposal_empty_changed_set_returns_empty(monkeypatch):
    """빈 changed_set이면 생성기를 호출하지 않고 빈 dict."""
    from workflow.impact_orchestrator import _build_doc_proposal
    called = {"n": 0}
    import generators.suts as gsuts
    monkeypatch.setattr(gsuts, "collect_unit_functions", lambda *a, **k: called.__setitem__("n", called["n"] + 1) or [])
    out = _build_doc_proposal(_proposal_sections({"f1": {"name": "s_foo"}}), set())
    assert out == {"suts": {}, "sits": {}, "sts": {}}
    assert called["n"] == 0


def test_build_doc_proposal_no_function_details_warns():
    """function_details 없음(소스 미해결)이면 빈 dict + 사유 warn(silent-0 금지)."""
    from workflow.impact_orchestrator import _build_doc_proposal
    warns: list = []
    out = _build_doc_proposal({}, {"s_foo"}, warn_sink=warns)
    assert out == {"suts": {}, "sits": {}, "sts": {}}
    assert any("function_details 없음" in w for w in warns)


def test_build_doc_proposal_caps_function_count(monkeypatch):
    """fn_cap을 초과하는 변경 함수는 초안 대상에서 제외(페이로드 억제)."""
    from workflow.impact_orchestrator import _build_doc_proposal
    fd = {f"f{i}": {"name": f"s_fn{i}", "logic_flow": [], "calls_list": []} for i in range(5)}
    _stub_generators(monkeypatch, sits_flows=[])
    changed = {f"s_fn{i}" for i in range(5)}
    out = _build_doc_proposal(_proposal_sections(fd), changed, fn_cap=2)
    # SUTS/STS는 targets(cap=2)만 — 정확히 2개
    assert len(out["suts"]) == 2
    assert len(out["sts"]) == 2


def test_build_doc_proposal_generator_exception_isolated(monkeypatch):
    """한 생성기(SUTS) 예외가 다른 생성기(SITS/STS)를 막지 않고, 사유가 warn으로 표면화된다."""
    from workflow.impact_orchestrator import _build_doc_proposal
    import generators.suts as gsuts
    fd = {"f1": {"name": "s_foo", "logic_flow": [], "calls_list": []}}
    _stub_generators(monkeypatch)

    def _boom(*a, **k):
        raise RuntimeError("suts boom")
    monkeypatch.setattr(gsuts, "collect_unit_functions", _boom)

    warns: list = []
    out = _build_doc_proposal(_proposal_sections(fd), {"s_foo"}, warn_sink=warns)
    assert out["suts"] == {}                                   # SUTS는 예외로 비었으나
    assert out["sits"]["s_foo"]["call_chain"] == "s_foo -> s_dep"   # SITS는 정상
    assert out["sts"]["s_foo"]                                  # STS도 정상
    assert any("SUTS 시퀀스 합성 예외" in w for w in warns)


def test_build_doc_proposal_preserves_verification_marker(monkeypatch):
    """생성기가 판정 불가값을 '[검증 필요]'로 표기하면 초안에 그대로 보존한다(정직성)."""
    from workflow.impact_orchestrator import _build_doc_proposal
    fd = {"f1": {"name": "s_foo", "logic_flow": [], "calls_list": []}}
    _stub_generators(monkeypatch, sits_flows=[], sts_steps=[],
                     suts_seq=[{"strategy": "BV_MAX", "inputs": {"x": 65535},
                                "expected": {"ret": "[검증 필요] saturated"}, "description": "d"}])
    out = _build_doc_proposal(_proposal_sections(fd), {"s_foo"})
    assert out["suts"]["s_foo"][0]["expected"] == {"ret": "[검증 필요] saturated"}


def test_build_doc_proposal_suts_uses_gim_types_not_global():
    """SUTS 경계값이 gim 타입(로컬 주입)으로 산출되고 프로세스 전역 타입캐시를 오염시키지 않는다.

    과거 버그: _build_doc_proposal이 set_globals_type_cache를 호출하지 않아 빈/stale 전역
    타입캐시→uint8 폴백으로 U32 변수의 경계 max를 255로 잘못 산출했다(실측 12개 변수 상이).
    이제 gim→{var:type} 로컬맵을 generate_sequences(type_cache=)로 명시 주입한다:
      (a) 실 문서생성(set_globals_type_cache→전역)과 동일한 타입으로 경계 산출,
      (b) 프로세스 전역은 일절 변이 안 함 → 동시 문서생성과 write-race/오염 차단.
    실 생성기(스텁 아님)로 두 불변식을 함께 잠근다.
    """
    import generators.suts as gsuts
    from workflow.impact_orchestrator import _build_doc_proposal

    # xfer_len 은 gim 에서 U32. 함수 input 으로 노출('[IN] TYPE name' = _parse_signature_params 형식).
    fd = {"f1": {"name": "s_xfer", "prototype": "void s_xfer(U32 xfer_len)",
                 "inputs": ["[IN] U32 xfer_len"], "outputs": [],
                 "logic_flow": [], "calls_list": []}}
    gim = {"xfer_len": {"type": "U32"}}

    # ⚠ 전역 타입캐시를 일부러 틀린 타입(uint8)으로 오염 — 주입이 전역을 '읽지' 않는지 검증
    gsuts._globals_type_cache.clear()
    gsuts._globals_type_cache["xfer_len"] = "uint8_t"
    try:
        out = _build_doc_proposal(_proposal_sections(fd, gim), {"s_xfer"})

        # (a) SUTS 시퀀스의 xfer_len 최대 입력이 U32 max(4294967295) — uint8(255) 폴백 아님
        seqs = out["suts"]["s_xfer"]
        xfer_vals = [s["inputs"]["xfer_len"] for s in seqs if "xfer_len" in (s.get("inputs") or {})]
        assert 4294967295 in xfer_vals, f"U32 경계가 반영돼야(전역 오염 무시): {xfer_vals}"
        assert 255 not in xfer_vals                          # uint8 폴백 아님

        # (b) 전역 타입캐시는 호출 후에도 오염값 그대로 — _build_doc_proposal 이 전역을 변이하지 않음
        assert gsuts._globals_type_cache.get("xfer_len") == "uint8_t"
    finally:
        gsuts._globals_type_cache.clear()   # 다른 테스트 격리(전역 싱글톤 복원)


def test_generate_sequences_type_cache_overrides_global():
    """generate_sequences(type_cache=)가 주어지면 전역 _globals_type_cache 대신 그것을 읽고,
    None(기본)이면 기존대로 전역을 읽는다(실 문서생성 경로 무변경 보증)."""
    import generators.suts as gsuts

    unit = {"name": "u", "input_vars": ["v"], "output_vars": [], "logic_flow": []}
    gsuts._globals_type_cache.clear()
    gsuts._globals_type_cache["v"] = "uint8_t"     # 전역 = uint8
    try:
        # type_cache 명시 주입(U32) → 전역(uint8) 무시하고 U32 경계
        inj = [s for s in gsuts.generate_sequences(unit, type_cache={"v": "U32"})
               if s["strategy"] == "BV_MAX"]
        assert inj and inj[0]["inputs"]["v"] == 4294967295

        # type_cache=None(기본) → 전역(uint8) 사용 = 실 문서생성 경로 무변경
        glob = [s for s in gsuts.generate_sequences(unit)
                if s["strategy"] == "BV_MAX"]
        assert glob and glob[0]["inputs"]["v"] == 255
    finally:
        gsuts._globals_type_cache.clear()


def test_extract_mcdc_conditions_threads_type_cache_into_recursion():
    """_extract_mcdc_conditions의 재귀 자기호출(중첩 if/children)에도 type_cache가 스레드된다.

    중첩 조건은 재귀 경로로만 도달하므로, 재귀에서 type_cache를 흘리면(과거 스냅샷 결함) 안쪽
    var-vs-var 조건의 MC/DC 경계값이 전역(폴백 uint8)을 읽는다. 바깥 if의 children에 안쪽 if를
    두고, 주입(U32) vs 미주입(전역 비움→uint8) 대조로 재귀 스레딩을 보증한다."""
    import generators.suts as gsuts

    gsuts._globals_type_cache.clear()   # 전역 비움 → 미주입 시 uint8 폴백(대조군)
    try:
        # 바깥 if(children) → 안쪽 if 'big > small'(var-vs-var, 재귀로만 도달)
        flow = [{"type": "if", "condition": "outer > 0", "children": [
            {"type": "if", "condition": "big > small", "children": []},
        ]}]
        ivars = ["big", "small", "outer"]

        inj = gsuts._extract_mcdc_conditions(flow, ivars, {"big": "U32"})
        big_inj = [c for c in inj if c[0] == "big"]
        assert big_inj, f"중첩 var-vs-var 조건 미추출: {inj}"
        # tuple=(var, op, rhs, true_val, false_val); '>'→true_val=bmax. U32 max면 재귀 스레드 성공.
        assert big_inj[0][3] == 4294967295, f"재귀에 type_cache 미스레드(uint8 폴백): {big_inj}"

        # 대조군: 미주입(전역 비움) → uint8 폴백(255). 재귀가 None을 흘려도 이 값이라 회귀 검출 가능.
        glob = gsuts._extract_mcdc_conditions(flow, ivars)
        big_glob = [c for c in glob if c[0] == "big"]
        assert big_glob and big_glob[0][3] == 255
    finally:
        gsuts._globals_type_cache.clear()
