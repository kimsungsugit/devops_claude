"""Phase 3 — ASIL 손상 UDS 정직 표면화 + SDS ASIL 폴백 검증.

kjpds02_pv의 ASIL 미상 다수는 UDS 매칭 실패가 아니라 UDS 파일이 손상 ZIP이라 열리지 않기 때문.
손상을 정직 표기하고, UDS 부재/손상 시 SDS ASIL로 폴백 보강(TBD만 채움, 등급 낮추기 없음).
"""
from __future__ import annotations

import io
import zipfile


def _valid_zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("dummy.xml", "<x/>")
    return buf.getvalue()


class _Resolver:
    def __init__(self, data: bytes):
        self._d = data

    def read_bytes(self, path: str) -> bytes:  # noqa: ARG002
        return self._d


def test_uds_name_asil_map_surfaces_corruption(monkeypatch):
    """손상 ZIP(non-zip)이면 warn_sink에 손상 사유를 남기고 빈 맵 — 'heading-less' 오진단 방지."""
    import backend.services.file_resolver as fr
    from workflow.impact_orchestrator import _UDS_NAME_ASIL_CACHE, _uds_name_asil_map

    _UDS_NAME_ASIL_CACHE.clear()
    monkeypatch.setattr(fr, "get_resolver", lambda: _Resolver(b"PK\x03\x04 corrupted not a real zip"))
    warns: list = []
    out = _uds_name_asil_map("U:/broken_260XXX.docx", warn_sink=warns)
    assert out == {}
    assert any("손상" in w and "UDS" in w for w in warns)
    # 손상은 캐시하지 않는다(다음 실행 재시도) — 캐시 미기록 확인.
    assert "U:/broken_260XXX.docx" not in _UDS_NAME_ASIL_CACHE


def test_uds_name_asil_map_surfaces_file_not_found(monkeypatch):
    """UDS 경로가 없으면(미완성 placeholder 260XXX 등) warn_sink에 사유 + 빈 맵 + 미캐시(매 실행 경고).

    실 kjpds02_pv 케이스 — UDS 경로 파일명이 placeholder라 FileNotFoundError(손상 아님)."""
    import backend.services.file_resolver as fr
    from workflow.impact_orchestrator import _UDS_NAME_ASIL_CACHE, _uds_name_asil_map

    _UDS_NAME_ASIL_CACHE.clear()

    class _NF:
        def read_bytes(self, path):  # noqa: ARG002
            raise FileNotFoundError(path)

    monkeypatch.setattr(fr, "get_resolver", lambda: _NF())
    warns: list = []
    out = _uds_name_asil_map("U:/missing_260XXX.docx", warn_sink=warns)
    assert out == {}
    assert any("찾을 수 없습니다" in w for w in warns)
    # 미캐시 — 파일명 오탈자/미완성은 사용자가 고쳐야 하므로 매 실행 재경고한다.
    assert "U:/missing_260XXX.docx" not in _UDS_NAME_ASIL_CACHE


def test_sds_name_asil_map_extracts_asil(monkeypatch):
    """정상 SDS면 _extract_sds_partition_map의 함수별 asil을 {fn: asil}로 반환(blank는 제외)."""
    import backend.services.file_resolver as fr
    import report_gen.requirements as rq
    from workflow.impact_orchestrator import _SDS_NAME_ASIL_CACHE, _sds_name_asil_map

    _SDS_NAME_ASIL_CACHE.clear()
    monkeypatch.setattr(fr, "get_resolver", lambda: _Resolver(_valid_zip_bytes()))
    monkeypatch.setattr(rq, "_extract_sds_partition_map", lambda p: {
        "s_foo": {"asil": "B", "description": "x", "kind": "function"},
        "s_bar": {"asil": "TBD", "kind": "function"},   # blank asil → 제외
        "eeprom": {"asil": "D", "kind": "component"},    # ⚠ 컴포넌트 → 제외(오귀속 방지, reviewer W3)
        "s_typo": {"asil": "B(잠정)", "kind": "function"},  # 오타 등급 → 제외(_asil_rank<0, W5)
    })
    out = _sds_name_asil_map("U:/sds.docx")
    assert out == {"s_foo": "B"}   # 함수·유효등급만, blank·component·오타 제외


def test_enrich_asil_from_sds_only_tbd_no_lowering(monkeypatch):
    """SDS 폴백은 TBD 함수만 채우고 이미 등급 있는 함수는 절대 낮추지 않는다(안전측 — under-report=위험)."""
    from workflow import impact_orchestrator as m

    monkeypatch.setattr(m, "_sds_name_asil_map", lambda p, warn_sink=None: {"s_tbd": "B", "s_high": "A"})
    by_name = {
        "s_tbd": {"asil": "TBD"},      # 채워져야
        "s_high": {"asil": "C"},       # SDS가 A라도 낮추면 안 됨 → C 유지(missing 아님)
        "s_ok": {"asil": "D"},         # SDS에 없음 → 유지
    }
    enriched, still = m._enrich_asil_from_sds(by_name, "U:/sds.docx")
    assert by_name["s_tbd"]["asil"] == "B"
    assert by_name["s_tbd"]["asil_source"] == "sds"
    assert by_name["s_high"]["asil"] == "C"   # ⚠ 낮추기 없음
    assert by_name["s_ok"]["asil"] == "D"
    assert enriched == 1 and still == 0


def test_enrich_asil_from_sds_empty_path():
    from workflow.impact_orchestrator import _enrich_asil_from_sds
    assert _enrich_asil_from_sds({"s_foo": {"asil": "TBD"}}, "") == (0, 0)


# ── Phase 2 (후속): 반환형 접두사 alias — SDS 'u16g_X' ↔ 소스 순수명 'g_X' 정합 ──

def test_sds_name_asil_map_aliases_return_type_prefix(monkeypatch):
    """반환형 접두사 SDS 키(u16g_drvin_motorspeed)가 순수명 alias(g_drvin_motorspeed)로도 등록 —
    소스 by_name 키는 순수명이라 이 alias가 있어야 _enrich_asil_from_sds가 매칭(폴백 커버리지 fix)."""
    import backend.services.file_resolver as fr
    import report_gen.requirements as rq
    from workflow.impact_orchestrator import _SDS_NAME_ASIL_CACHE, _sds_name_asil_map

    _SDS_NAME_ASIL_CACHE.clear()
    monkeypatch.setattr(fr, "get_resolver", lambda: _Resolver(_valid_zip_bytes()))
    monkeypatch.setattr(rq, "_extract_sds_partition_map", lambda p: {
        "u16g_drvin_motorspeed": {"asil": "B", "kind": "function"},
    })
    out = _sds_name_asil_map("U:/sds.docx")
    assert out.get("u16g_drvin_motorspeed") == "B"   # 원 exact 키 보존
    assert out.get("g_drvin_motorspeed") == "B"        # 순수명 alias 신규 등록


def test_sds_name_asil_map_skips_alias_on_base_collision(monkeypatch):
    """u8g_/s8g_(unsigned/signed 반환형 = 별개 함수 가능)이 같은 base(g_foo)로 모이면 alias 생략 —
    서로 다른 함수에 ASIL 오union 방지(안전측 보수, 추적성 _alias_safe 미러)."""
    import backend.services.file_resolver as fr
    import report_gen.requirements as rq
    from workflow.impact_orchestrator import _SDS_NAME_ASIL_CACHE, _sds_name_asil_map

    _SDS_NAME_ASIL_CACHE.clear()
    monkeypatch.setattr(fr, "get_resolver", lambda: _Resolver(_valid_zip_bytes()))
    monkeypatch.setattr(rq, "_extract_sds_partition_map", lambda p: {
        "u8g_foo": {"asil": "B", "kind": "function"},
        "s8g_foo": {"asil": "C", "kind": "function"},
    })
    out = _sds_name_asil_map("U:/sds.docx")
    assert out.get("u8g_foo") == "B" and out.get("s8g_foo") == "C"  # exact 보존
    assert "g_foo" not in out    # ⚠ base 충돌 → alias 생략


def test_sds_name_asil_map_skips_alias_when_base_is_real_key(monkeypatch):
    """접두사형 base가 이미 별도 SDS 키(s_bar)면 alias 만들지 않고 기존 정확매칭 유지(등급 오염 방지)."""
    import backend.services.file_resolver as fr
    import report_gen.requirements as rq
    from workflow.impact_orchestrator import _SDS_NAME_ASIL_CACHE, _sds_name_asil_map

    _SDS_NAME_ASIL_CACHE.clear()
    monkeypatch.setattr(fr, "get_resolver", lambda: _Resolver(_valid_zip_bytes()))
    monkeypatch.setattr(rq, "_extract_sds_partition_map", lambda p: {
        "u16s_bar": {"asil": "B", "kind": "function"},
        "s_bar": {"asil": "D", "kind": "function"},
    })
    out = _sds_name_asil_map("U:/sds.docx")
    assert out.get("u16s_bar") == "B"
    assert out.get("s_bar") == "D"   # ⚠ 기존 실제 키 → u16s_bar의 B로 덮이지 않음(alias 생략)


# ── F3: 소스↔UDS 등급 불일치 표면화(등급 불변, 경고만) ──

def test_enrich_asil_from_uds_warns_on_source_lower_than_uds(monkeypatch):
    """소스가 비-blank인데 UDS가 더 높은 등급이면 등급은 불변(소스 권위)이나 불일치 경고 표면화(F3).

    잠재 under-report 방향(소스 QM이 UDS A를 침묵으로 이김)을 사람이 검토하도록 가시화."""
    from workflow import impact_orchestrator as m

    monkeypatch.setattr(m, "_uds_name_asil_map", lambda p, warn_sink=None: {"s_conflict": "A", "s_blank": "C"})
    by_name = {
        "s_conflict": {"asil": "QM"},   # 소스 QM < UDS A → 등급 불변(QM 유지) + 경고
        "s_blank": {"asil": "TBD"},     # blank → UDS C로 보강
        "s_ok": {"asil": "D"},          # UDS에 없음 → 유지
    }
    warns: list = []
    enriched, _still = m._enrich_asil_from_uds(by_name, "U:/uds.docx", warn_sink=warns)
    assert by_name["s_conflict"]["asil"] == "QM"        # ⚠ 등급 불변(소스 권위·자동 상향 금지)
    assert "asil_source" not in by_name["s_conflict"]   # 보강 안 됨
    assert by_name["s_blank"]["asil"] == "C"            # blank는 정상 보강
    assert enriched == 1
    assert any("소스 등급이 UDS보다 낮은" in w and "s_conflict" in w for w in warns)


def test_enrich_asil_from_uds_no_conflict_warn_when_source_ge_uds(monkeypatch):
    """소스가 UDS보다 높거나 같으면 충돌 경고 없음(정상 — 소스가 더 안전하거나 동일)."""
    from workflow import impact_orchestrator as m

    monkeypatch.setattr(m, "_uds_name_asil_map", lambda p, warn_sink=None: {"s_hi": "A", "s_eq": "B", "s_blank": "B"})
    by_name = {"s_hi": {"asil": "D"}, "s_eq": {"asil": "B"}, "s_blank": {"asil": "TBD"}}
    warns: list = []
    m._enrich_asil_from_uds(by_name, "U:/uds.docx", warn_sink=warns)
    assert by_name["s_hi"]["asil"] == "D" and by_name["s_eq"]["asil"] == "B"
    assert not any("소스 등급이 UDS보다 낮은" in w for w in warns)


# ── SwCom-상속 폴백: 함수 ASIL이 N/A인데 소속 SwCom(SDS)엔 등급 있을 때 상속(가장 약한 폴백) ──

def test_enrich_asil_from_swcom_inherits_component_grade(monkeypatch):
    """SwUDS Related ID의 소속 SwCom → SDS 컴포넌트 등급으로 상속 보강(N/A 함수만·상향만·경고)."""
    from workflow import impact_orchestrator as m

    monkeypatch.setattr(m, "_suds_fn_swcom_map", lambda p: {
        "s_antipinch_x": ["SwCom_13"],
        "s_multi": ["SwCom_11", "SwCom_13"],   # 다중 소속 → max
        "s_hasgrade": ["SwCom_13"],            # 이미 등급 → 미터치
    })
    monkeypatch.setattr(m, "_sds_com_asil_map", lambda p: {"SwCom_13": "A", "SwCom_11": "QM"})
    by_name = {
        "s_antipinch_x": {"asil": "N/A"},   # → A
        "s_multi": {"asil": "TBD"},          # QM,A → max A
        "s_hasgrade": {"asil": "C"},         # 이미 C → 유지(SwCom A라도 안 덮음)
        "s_nomap": {"asil": "N/A"},          # SwCom 없음 → 유지
    }
    warns: list = []
    enr, still = m._enrich_asil_from_swcom(by_name, "U:/uds.docx", "U:/sds.docx", warn_sink=warns)
    assert by_name["s_antipinch_x"]["asil"] == "A"
    assert by_name["s_antipinch_x"]["asil_source"] == "swcom"
    assert by_name["s_multi"]["asil"] == "A"          # max(QM,A)
    assert by_name["s_hasgrade"]["asil"] == "C"       # ⚠ 등급 낮추기 없음
    assert by_name["s_nomap"]["asil"] == "N/A"        # SwCom 매핑 없음 → 유지
    # missing=3(s_antipinch_x·s_multi·s_nomap; s_hasgrade는 C라 제외), 보강 2 → 남은 미상 1
    assert enr == 2 and still == 1
    assert any("소속 SwCom" in w and "2건" in w for w in warns)


def test_enrich_asil_from_swcom_noop_without_paths():
    from workflow.impact_orchestrator import _enrich_asil_from_swcom
    assert _enrich_asil_from_swcom({"s_x": {"asil": "TBD"}}, "", "U:/sds.docx") == (0, 0)
    assert _enrich_asil_from_swcom({"s_x": {"asil": "TBD"}}, "U:/uds.docx", "") == (0, 0)


def test_sds_com_asil_map_keeps_only_swcom_keys(monkeypatch):
    """extract_component_asil_from_sds의 이름 별칭·노이즈 키는 버리고 SwCom_NN 유효등급만(오귀속 방지)."""
    import backend.services.file_resolver as fr
    import backend.services.iso26262_doc_asil_extractor as ext
    from workflow.impact_orchestrator import _SDS_COM_ASIL_CACHE, _sds_com_asil_map

    _SDS_COM_ASIL_CACHE.clear()
    monkeypatch.setattr(fr, "get_resolver", lambda: _Resolver(_valid_zip_bytes()))
    monkeypatch.setattr(ext, "extract_component_asil_from_sds", lambda d: {
        "SwCom_13": "A",
        "System OS": "A",          # 이름 별칭 → 제외
        "85.9KBe 사용중": "A",      # 노이즈 → 제외
        "SwCom_99": "TBD",          # blank 등급 → 제외
    })
    out = _sds_com_asil_map("U:/sds.docx")
    assert out == {"SwCom_13": "A"}
