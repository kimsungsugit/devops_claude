"""generators/sits.py — 합성 SwCom과 실제 요구 추적성의 분리.

배경: `_infer_swcom_id`는 모듈 **등장 순번**으로 `SwCom_XX`를 만든다(실제 SDS component ID가
아니다). 이 값이 모든 flow의 related_ids에 무조건 삽입되므로 "Related ID 보유율"은 사실상
항상 100%다. 그 수치를 요구 추적성으로 쓰면 요구 링크가 0건이어도 게이트를 통과한다.
"""
from __future__ import annotations

from generators.sits import (
    collect_integration_flows,
    generate_sits_quality_report,
)


def _fd(*, related_by_name=None):
    """cross-module 호출 1건을 갖는 최소 function_details."""
    related_by_name = related_by_name or {}
    return {
        "F1": {
            "name": "Ap_Door_Run",
            "file": "Ap_Door.c",
            "calls_list": ["Drv_Motor_Set"],
            "inputs": [], "outputs": [], "globals_global": [], "globals_static": [],
            "asil": "B",
            "related": related_by_name.get("Ap_Door_Run", ""),
        },
        "F2": {
            "name": "Drv_Motor_Set",
            "file": "Drv_Motor.c",
            "calls_list": [],
            "inputs": [], "outputs": [], "globals_global": [], "globals_static": [],
            "asil": "B",
            "related": related_by_name.get("Drv_Motor_Set", ""),
        },
    }


class TestSyntheticSwComIsMarked:
    def test_synthetic_id_is_recorded_at_insertion(self):
        """합성 여부는 삽입 지점에서 기록된다 — 소비자가 문자열 prefix로 추측하지 않도록."""
        flows = collect_integration_flows(_fd())
        assert flows, "cross-module flow가 생성되지 않았다"
        f = flows[0]
        assert f["related_ids"], "합성 ID가 항상 들어간다는 전제가 깨졌다"
        assert f["synthetic_related_ids"] == [f["swcom_id"]]
        assert f["swcom_id"] in f["related_ids"]


class TestQualityReportSeparatesAxes:
    @staticmethod
    def _itcs(*, real_ids):
        """related_ids = 합성 1개 + real_ids."""
        return [{
            "tc_id": "SwITC_01",
            "related_ids": ["SwCom_01", *real_ids],
            "synthetic_related_ids": ["SwCom_01"],
            "sub_cases": [], "input_vars": [], "expected_vars": [],
            "gen_method": "ABV",
        }]

    def test_synthetic_only_is_not_traceability(self):
        """합성 ID만 있으면 Related 보유율 100%, 요구 추적성 0%."""
        qr = generate_sits_quality_report(self._itcs(real_ids=[]), total_source_functions=2)
        assert qr["related_coverage_pct"] == 100.0
        assert qr["requirement_traceability_pct"] == 0.0
        assert qr["synthetic_only_related_count"] == 1

    def test_real_id_counts_as_traceability(self):
        qr = generate_sits_quality_report(
            self._itcs(real_ids=["SwTR_012"]), total_source_functions=2,
        )
        assert qr["requirement_traceability_pct"] == 100.0
        assert qr["with_requirement_trace_count"] == 1
        assert qr["synthetic_only_related_count"] == 0

    def test_sds_sourced_swcom_is_not_treated_as_synthetic(self):
        """문서(SDS)에서 온 SwCom ID는 합성이 아니다 — prefix로 뭉뚱그리지 않는다."""
        itcs = [{
            "tc_id": "SwITC_01",
            "related_ids": ["SwCom_07"],       # SDS 유래
            "synthetic_related_ids": [],       # 삽입 지점이 합성으로 기록하지 않았다
            "sub_cases": [], "input_vars": [], "expected_vars": [], "gen_method": "ABV",
        }]
        qr = generate_sits_quality_report(itcs, total_source_functions=1)
        assert qr["requirement_traceability_pct"] == 100.0
        assert qr["synthetic_only_related_count"] == 0

    def test_legacy_itc_without_marker_is_not_silently_credited(self):
        """marker 필드가 없는 구 데이터는 related_ids를 그대로 신뢰한다(하위호환).

        구 경로에서 만들어진 ITC는 합성 여부를 알 수 없다. 여기서 임의로 prefix 추측을
        하면 SDS 유래 ID까지 깎아내리므로, 판정은 생산 지점 기록에만 의존한다.
        """
        itcs = [{
            "tc_id": "SwITC_01", "related_ids": ["SwCom_01"],
            "sub_cases": [], "input_vars": [], "expected_vars": [], "gen_method": "ABV",
        }]
        qr = generate_sits_quality_report(itcs, total_source_functions=1)
        assert qr["requirement_traceability_pct"] == 100.0
