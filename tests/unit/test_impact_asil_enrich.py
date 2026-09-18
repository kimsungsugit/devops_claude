"""impact 오케스트레이터의 UDS ASIL 보강 — 안전측 동작 검증.

C 소스에 @asil 주석이 없어도 링크된 UDS 문서(함수별 ASIL)로 보강하되,
소스 주석 ASIL이 있는 함수는 절대 덮지 않는다(우선순위: 소스 > UDS).
"""
from __future__ import annotations

import workflow.impact_orchestrator as io


def test_is_blank_asil():
    """미상 판정 — uds_generator가 넣는 placeholder(TBD/N/A/-)도 '미상'으로 취급(CRITICAL: no-op 방지)."""
    for v in ["", "  ", "TBD", "tbd", "N/A", "n/a", "-", "UNKNOWN", None]:
        assert io._is_blank_asil(v), f"{v!r} 는 미상이어야 함"
    for v in ["A", "B", "C", "D", "QM", "ASIL D", "asil c"]:
        assert not io._is_blank_asil(v), f"{v!r} 는 실 등급이어야 함"


def test_enrich_asil_fills_blank_including_tbd(monkeypatch):
    """소스 ASIL이 있는 함수는 유지, 빈/placeholder(TBD/N/A) 함수만 UDS ASIL로 채운다."""
    by_name = {
        "door_run": {"asil": "C"},      # 소스에 이미 있음 → 유지(안 덮음)
        "motor_ctrl": {"asil": ""},     # 비어있음 → 채움
        "lamp_set": {"asil": "   "},    # 공백뿐 → 채움
        "brake_cmd": {"asil": "TBD"},   # ⚠ placeholder(실제 미태그 함수의 shape) → 채움
        "wiper_ctrl": {"asil": "N/A"},  # placeholder → 채움
        "unknown_fn": {"asil": "TBD"},  # UDS에도 없음 → 미상 유지
    }
    monkeypatch.setattr(io, "_uds_name_asil_map", lambda p, warn_sink=None: {
        "door_run": "QM",   # 소스 C를 덮으면 안 됨
        "motor_ctrl": "D",
        "lamp_set": "B",
        "brake_cmd": "D",
        "wiper_ctrl": "A",
    })

    enriched, still_missing = io._enrich_asil_from_uds(by_name, "U:/연구소/SwUDS.docx")

    assert enriched == 4          # motor_ctrl, lamp_set, brake_cmd, wiper_ctrl
    assert still_missing == 1     # unknown_fn (UDS에 없음)
    assert by_name["door_run"]["asil"] == "C"        # 소스 우선 — 안 덮음
    assert "asil_source" not in by_name["door_run"]
    assert by_name["motor_ctrl"]["asil"] == "D"
    assert by_name["motor_ctrl"]["asil_source"] == "uds"
    assert by_name["brake_cmd"]["asil"] == "D"       # TBD → 실등급으로 보강됨(CRITICAL 1)
    assert by_name["wiper_ctrl"]["asil"] == "A"
    assert by_name["unknown_fn"]["asil"] == "TBD"    # 미상 유지(덮지 않음)


def test_enrich_asil_noop_when_all_have_real_asil(monkeypatch):
    """모든 함수에 실 ASIL이 있으면 UDS 문서를 아예 읽지 않는다(불필요한 워커 IPC 회피)."""
    by_name = {"a": {"asil": "A"}, "b": {"asil": "B"}}
    called = {"n": 0}

    def _map(_p, warn_sink=None):
        called["n"] += 1
        return {"a": "D"}

    monkeypatch.setattr(io, "_uds_name_asil_map", _map)
    assert io._enrich_asil_from_uds(by_name, "U:/x.docx") == (0, 0)
    assert called["n"] == 0
    assert by_name["a"]["asil"] == "A"


def test_enrich_asil_empty_path_or_no_map(monkeypatch):
    assert io._enrich_asil_from_uds({"a": {"asil": "TBD"}}, "") == (0, 0)
    monkeypatch.setattr(io, "_uds_name_asil_map", lambda p, warn_sink=None: {})
    assert io._enrich_asil_from_uds({"a": {"asil": "TBD"}}, "U:/x.docx") == (0, 1)


def test_uds_name_asil_map_permission_error_not_cached(monkeypatch):
    """⚠ 워커 다운/네트워크 블립(PermissionError/OSError)은 캐시하지 않는다 — 워커 복구 후
    재시도 가능해야 함(캐시하면 세션 내내 ASIL 안전게이트가 무력화됨)."""
    io._UDS_NAME_ASIL_CACHE.clear()
    import backend.services.file_resolver as fr

    class _Stub:
        mode = "cloudium"

        def read_bytes(self, _p):
            raise PermissionError("[WinError 5] worker down")

    monkeypatch.setattr(fr, "get_resolver", lambda *a, **k: _Stub())
    path = "U:/연구소/SwUDS_v2.08.docx"
    assert io._uds_name_asil_map(path) == {}
    assert path not in io._UDS_NAME_ASIL_CACHE  # 캐시 안 됨 → 다음 실행 재시도
    io._UDS_NAME_ASIL_CACHE.clear()


def test_uds_name_asil_map_filenotfound_not_cached_and_warns(monkeypatch):
    """진짜 부재(FileNotFoundError)는 캐시하지 않고 매 실행 경고한다 — 파일명/경로 오류(placeholder 260XXX
    등)는 사용자가 고쳐야 하므로 첫 실행 후 조용히 사라지면 안 된다(Phase 3 정책 변경)."""
    io._UDS_NAME_ASIL_CACHE.clear()
    import backend.services.file_resolver as fr

    class _Stub:
        mode = "local"

        def read_bytes(self, _p):
            raise FileNotFoundError("no such file")

    monkeypatch.setattr(fr, "get_resolver", lambda *a, **k: _Stub())
    path = "C:/x/SwUDS_260XXX.docx"
    warns: list = []
    assert io._uds_name_asil_map(path, warn_sink=warns) == {}
    assert path not in io._UDS_NAME_ASIL_CACHE  # 미캐시 → 다음 실행 재시도
    assert any("찾을 수 없습니다" in w for w in warns)
    io._UDS_NAME_ASIL_CACHE.clear()


def test_uds_name_asil_map_empty_path():
    assert io._uds_name_asil_map("") == {}
