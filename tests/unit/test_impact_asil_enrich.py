"""impact 오케스트레이터의 UDS ASIL 보강 — 안전측 동작 검증.

C 소스에 @asil 주석이 없어도 링크된 UDS 문서(함수별 ASIL)로 보강하되,
소스 주석 ASIL이 있는 함수는 절대 덮지 않는다(우선순위: 소스 > UDS).
"""
from __future__ import annotations

import workflow.impact_orchestrator as io


def test_enrich_asil_only_fills_empty(monkeypatch):
    """소스 ASIL이 있는 함수는 유지, 빈 함수만 UDS ASIL로 채운다."""
    by_name = {
        "door_run": {"asil": "C"},      # 소스에 이미 있음 → 유지(안 덮음)
        "motor_ctrl": {"asil": ""},     # 비어있음 → UDS로 채움
        "lamp_set": {"asil": "   "},    # 공백뿐 → 채움
        "unknown_fn": {"asil": ""},     # UDS에도 없음 → 미상 유지
    }
    monkeypatch.setattr(io, "_uds_name_asil_map", lambda p: {
        "door_run": "QM",   # 소스 C를 덮으면 안 됨
        "motor_ctrl": "D",
        "lamp_set": "B",
    })

    enriched, still_missing = io._enrich_asil_from_uds(by_name, "U:/연구소/SwUDS.docx")

    assert enriched == 2
    assert still_missing == 1  # unknown_fn
    assert by_name["door_run"]["asil"] == "C"        # 소스 우선 — 안 덮음
    assert "asil_source" not in by_name["door_run"]
    assert by_name["motor_ctrl"]["asil"] == "D"
    assert by_name["motor_ctrl"]["asil_source"] == "uds"
    assert by_name["lamp_set"]["asil"] == "B"
    assert by_name["unknown_fn"]["asil"] == ""       # 미상 유지


def test_enrich_asil_noop_when_all_have_asil(monkeypatch):
    """모든 함수에 ASIL이 있으면 UDS 문서를 아예 읽지 않는다(불필요한 워커 IPC 회피)."""
    by_name = {"a": {"asil": "A"}, "b": {"asil": "B"}}
    called = {"n": 0}

    def _map(_p):
        called["n"] += 1
        return {"a": "D"}

    monkeypatch.setattr(io, "_uds_name_asil_map", _map)
    assert io._enrich_asil_from_uds(by_name, "U:/x.docx") == (0, 0)
    assert called["n"] == 0
    assert by_name["a"]["asil"] == "A"


def test_enrich_asil_empty_path_or_no_map(monkeypatch):
    assert io._enrich_asil_from_uds({"a": {"asil": ""}}, "") == (0, 0)
    monkeypatch.setattr(io, "_uds_name_asil_map", lambda p: {})
    assert io._enrich_asil_from_uds({"a": {"asil": ""}}, "U:/x.docx") == (0, 1)


def test_uds_name_asil_map_skips_on_permission_error(monkeypatch):
    """cloudium U:\\(SMB) 접근 거부(WinError 5)여도 예외 없이 빈 맵 반환 + 캐시(재시도 폭주 방지)."""
    io._UDS_NAME_ASIL_CACHE.clear()
    import backend.services.file_resolver as fr

    class _Stub:
        mode = "cloudium"

        def read_bytes(self, _p):
            raise PermissionError("[WinError 5] 액세스가 거부되었습니다")

    monkeypatch.setattr(fr, "get_resolver", lambda *a, **k: _Stub())
    path = "U:/연구소/SwUDS_v2.08.docx"
    assert io._uds_name_asil_map(path) == {}
    assert io._UDS_NAME_ASIL_CACHE.get(path) == {}  # 접근 불가는 빈 맵으로 캐시
    io._UDS_NAME_ASIL_CACHE.clear()


def test_uds_name_asil_map_empty_path():
    assert io._uds_name_asil_map("") == {}
