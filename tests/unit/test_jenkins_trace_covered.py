"""결정1: 시스템시험(SyTS/SyITS)을 SW covered에서 제외.

`_row_has_sw_tests`(백엔드 SW-시험 predicate, jenkins.py `_cache_trace_summary`에서 사용)가
프론트 `hasTestData`(SrsSdsSection.jsx)와 lockstep인지 검증한다.

핵심: row의 flat `tests`는 SyTS/SyITS 멤버를 포함하는 상위집합이므로(syts_tests/syits_tests는
거기서 source로 필터된 뷰), 단순히 syts/syits band 키만 빼면 flat/test_ids가 시스템-only 검증
행을 여전히 SW 시험으로 잡는다 → source 필터로만 정확히 제외된다.

프론트 대응 테스트: frontend-v2/src/__tests__/UncoveredTopList.test.jsx
'deriveStatus (backend 동치성)' describe 블록.
"""
from __future__ import annotations

from backend.routers.jenkins import _row_has_sw_tests


def test_sw_band_tests_are_sw():
    assert _row_has_sw_tests({"sts_tests": [{"source": "STS"}]}) is True
    assert _row_has_sw_tests({"suts_tests": [{"source": "SUTS"}]}) is True
    assert _row_has_sw_tests({"sits_tests": [{"source": "SITS"}]}) is True
    assert _row_has_sw_tests({"vcast_tests": [{"source": "VectorCAST"}]}) is True


def test_system_only_flat_is_not_sw():
    # SyTS/SyITS만 있는 flat tests는 SW 시험 아님(결정1) — 이전엔 has_tests=True였다.
    assert _row_has_sw_tests({"tests": [{"source": "SyTS"}]}) is False
    assert _row_has_sw_tests({"tests": [{"source": "SyITS"}]}) is False
    assert _row_has_sw_tests({"tests": [{"source": "SyTS"}, {"source": "SyITS"}]}) is False


def test_mixed_flat_with_sw_source_is_sw():
    # 시스템 + SW source가 섞이면 SW 시험 존재.
    assert _row_has_sw_tests({"tests": [{"source": "SyTS"}, {"source": "STS"}]}) is True
    assert _row_has_sw_tests({"tests": [{"source": "SyITS"}, {"source": "SUTS"}]}) is True


def test_sw_band_wins_even_with_system_flat():
    # band-split SUTS가 있으면 flat에 SyTS가 섞여도 SW 시험(SUTS로 검증).
    assert _row_has_sw_tests({
        "suts_tests": [{"source": "SUTS"}],
        "tests": [{"source": "SyTS"}, {"source": "SUTS"}],
    }) is True


def test_local_mode_flat_suts_no_band_keys():
    # local.py 경로: band-split 키 없이 flat tests[]만(source=SUTS) → SW 시험.
    assert _row_has_sw_tests({"tests": [{"source": "SUTS"}]}) is True


def test_empty_is_not_sw():
    assert _row_has_sw_tests({}) is False
    assert _row_has_sw_tests({"tests": []}) is False
    # flat이 리스트로 존재(빈)면 test_ids 폴백을 타지 않는다 — 빈 flat은 시험 없음.
    assert _row_has_sw_tests({"tests": [], "test_ids": ["TC1"]}) is False


def test_test_ids_fallback_only_when_no_flat_list():
    # flat tests가 리스트로 없을 때만 test_ids 폴백(source 미상 → SW로 간주).
    assert _row_has_sw_tests({"test_ids": ["TC1"]}) is True
    assert _row_has_sw_tests({"tests": None, "test_ids": ["TC1"]}) is True


def test_non_dict_flat_items_ignored():
    # malformed(비-dict) flat 항목은 SW 시험으로 세지 않는다(프론트 typeof==='object'와 lockstep).
    assert _row_has_sw_tests({"tests": ["not-a-dict"]}) is False
    assert _row_has_sw_tests({"tests": [{"source": "SyTS"}, "junk"]}) is False
