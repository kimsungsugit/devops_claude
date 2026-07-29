"""generators/sits.py — 합성 SwCom과 실제 요구 추적성의 분리.

배경: `_infer_swcom_id`는 모듈 **등장 순번**으로 `SwCom_XX`를 만든다(실제 SDS component ID가
아니다). 이 값이 모든 flow의 related_ids에 무조건 삽입되므로 "Related ID 보유율"은 사실상
항상 100%다. 그 수치를 요구 추적성으로 쓰면 요구 링크가 0건이어도 게이트를 통과한다.
"""
from __future__ import annotations

from generators.sits import (
    _DESC_COL,
    _TCID_COL,
    collect_integration_flows,
    generate_sits_quality_report,
    validate_sits_xlsm,
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


# ---------------------------------------------------------------------------
# max_flows 캡 — 침묵 절단 + 안전등급 무관 선별
# ---------------------------------------------------------------------------

def _fd_many(n: int, *, asil_of=None):
    """entry n개(각각 cross-module 호출 1건)를 갖는 function_details.

    이름은 `Ap_F000`… 형태라 알파벳순 = 번호순이다(경계 확인이 쉬워진다).
    """
    asil_of = asil_of or (lambda i: "QM")
    fd = {}
    for i in range(n):
        fd[f"E{i:03d}"] = {
            "name": f"Ap_F{i:03d}",
            "file": f"Ap_Mod{i:03d}.c",
            "calls_list": ["Drv_Common"],
            "inputs": [], "outputs": [], "globals_global": [], "globals_static": [],
            "asil": asil_of(i),
            "related": "",
        }
    fd["DRV"] = {
        "name": "Drv_Common",
        "file": "Drv_Common.c",
        "calls_list": [],
        "inputs": [], "outputs": [], "globals_global": [], "globals_static": [],
        "asil": "QM", "related": "",
    }
    return fd


class TestFlowCapIsSurfaced:
    """캡이 물면 **몇 개가 잘렸는지** 남아야 한다.

    회귀 대상: 수집 루프가 `len(flows) >= max_flows` 에서 그냥 break 했다. 캡 이후
    후보는 세어지지도 않아 소비처에서 결과 길이로 되짚어도 절단을 알 수 없었다.
    실측(KJPDS02 계열 900함수): 145개 중 25개가 조용히 사라졌고 7개가 ASIL A였다.
    """

    def test_stats_out_reports_pre_cap_total(self):
        stats = {}
        flows = collect_integration_flows(_fd_many(10), max_flows=4, stats_out=stats)
        assert len(flows) == 4
        assert stats["total_flows_found"] == 10, "캡 **전** 총량이 안 남았다"
        assert stats["flows_emitted"] == 4
        assert stats["flows_dropped"] == 6
        assert stats["flow_emit_pct"] == 40.0
        assert len(stats["dropped_entry_fns"]) == 6

    def test_no_truncation_reports_zero(self):
        """대조군: 캡에 안 닿으면 제외 0건이고 경고도 없다."""
        stats = {}
        collect_integration_flows(_fd_many(3), max_flows=100, stats_out=stats)
        assert stats["flows_dropped"] == 0
        assert stats["dropped_entry_fns"] == []
        assert stats["dropped_safety_related_count"] == 0

    def test_truncation_is_logged(self, caplog):
        with caplog.at_level("WARNING", logger="generators.sits"):
            collect_integration_flows(_fd_many(10), max_flows=4)
        assert "max_flows" in caplog.text and "제외" in caplog.text, caplog.text

    def test_stats_out_is_optional(self):
        """기존 호출부(stats_out 없음)는 그대로 동작해야 한다."""
        assert len(collect_integration_flows(_fd_many(5), max_flows=2)) == 2


class TestFlowCapKeepsSafetyFirst:
    """자를 때 ASIL 높은 흐름을 먼저 버리면 안 된다 (ISO 26262).

    회귀 대상: 정렬 키가 함수명 알파벳순뿐이라 어느 흐름이 살아남는지가 안전등급과
    완전히 무관했다. 실측에서 ASIL A 7건이 QM 보다 먼저 잘려나갔다.
    """

    @staticmethod
    def _asil_of(i):
        # 알파벳 뒤쪽(번호 큰 쪽)에 안전등급을 몰아둔다 — 옛 로직이면 전부 잘린다.
        return {7: "D", 8: "C", 9: "A"}.get(i, "QM")

    def test_safety_flows_survive_the_cap(self):
        stats = {}
        flows = collect_integration_flows(
            _fd_many(10, asil_of=self._asil_of), max_flows=4, stats_out=stats)
        kept = {f["entry_fn"]: f["asil"] for f in flows}
        assert kept.get("Ap_F007") == "D", f"ASIL D가 잘렸다: {kept}"
        assert kept.get("Ap_F008") == "C", f"ASIL C가 잘렸다: {kept}"
        assert kept.get("Ap_F009") == "A", f"ASIL A가 잘렸다: {kept}"
        assert stats["dropped_safety_related_count"] == 0
        assert stats["dropped_asil_distribution"] == {"QM": 6}

    def test_higher_asil_wins_when_cap_is_tighter_than_safety_count(self):
        """캡이 안전관련 수보다 작으면 D > C > A 순으로 남는다."""
        flows = collect_integration_flows(
            _fd_many(10, asil_of=self._asil_of), max_flows=2)
        assert sorted(f["asil"] for f in flows) == ["C", "D"]

    def test_output_order_stays_alphabetical(self):
        """선별만 안전우선이고 **출력 순서는 알파벳 그대로** — 문서 행 순서를 흔들지 않는다."""
        flows = collect_integration_flows(
            _fd_many(10, asil_of=self._asil_of), max_flows=5)
        names = [f["entry_fn"] for f in flows]
        assert names == sorted(names), names

    def test_unknown_asil_ranks_after_qm(self):
        """미상 등급을 QM 보다 우대하면 근거 없는 우선순위가 된다."""
        flows = collect_integration_flows(
            _fd_many(4, asil_of=lambda i: "???" if i == 3 else "QM"), max_flows=3)
        assert "Ap_F003" not in {f["entry_fn"] for f in flows}


class TestSwComIdIsCapIndependent:
    """같은 모듈은 캡 값이 달라도 같은 SwCom ID 를 받아야 한다.

    회귀 대상: `_infer_swcom_id` 가 캡 안쪽 루프에서 호출돼 ID 가 캡에 의존했다.
    (실측: 이 저장소 실 프로젝트에서는 모듈 29개·변동 0건이라 무해한 변경)
    """

    def test_same_module_same_id_across_caps(self):
        fd = _fd_many(10)
        tight = {f["entry_fn"]: f["swcom_id"]
                 for f in collect_integration_flows(fd, max_flows=3)}
        loose = {f["entry_fn"]: f["swcom_id"]
                 for f in collect_integration_flows(fd, max_flows=100)}
        for name, sid in tight.items():
            assert loose[name] == sid, f"{name}: 캡에 따라 SwCom 이 바뀐다 {sid} != {loose[name]}"


class TestQualityReportExposesFlowCap:
    @staticmethod
    def _itc():
        return [{
            "tc_id": "SwITC_01", "related_ids": ["SwCom_01"],
            "synthetic_related_ids": ["SwCom_01"],
            "sub_cases": [], "input_vars": [], "expected_vars": [], "gen_method": "ABV",
        }]

    def test_flow_stats_are_carried_into_report(self):
        stats = {}
        collect_integration_flows(_fd_many(10), max_flows=4, stats_out=stats)
        qr = generate_sits_quality_report(self._itc(), 10, flow_stats=stats)
        cov = qr["integration_flow_coverage"]
        assert cov["total_flows_found"] == 10
        assert cov["flows_dropped"] == 6
        assert cov["flow_emit_pct"] == 40.0

    def test_report_without_flow_stats_stays_backward_compatible(self):
        """구 호출부(flow_stats 없음)는 키가 비어 있을 뿐 깨지지 않는다."""
        qr = generate_sits_quality_report(self._itc(), 1)
        assert qr["integration_flow_coverage"] == {}
        assert qr["total_test_cases"] == 1

    def test_tc_count_alone_would_hide_the_loss(self):
        """total_test_cases 는 캡에 잘려도 줄지 않는다 — 그래서 별도 축이 필요하다."""
        stats = {}
        collect_integration_flows(_fd_many(10), max_flows=4, stats_out=stats)
        qr = generate_sits_quality_report(self._itc(), 10, flow_stats=stats)
        assert qr["total_test_cases"] == 1
        assert qr["integration_flow_coverage"]["flows_dropped"] == 6


# ---------------------------------------------------------------------------
# validate_sits_xlsm — sub-case 계수를 desc 프리픽스로 추측하지 않는다
# ---------------------------------------------------------------------------

def _write_min_sits(path, sub_labels):
    """TC 1건 + 주어진 라벨의 sub-case 행을 갖는 최소 SITS 시트."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "4.SW Integration Test Spec"
    ws.cell(row=7, column=_TCID_COL, value="SwITC_01")
    ws.cell(row=7, column=_DESC_COL, value="Verify integration: Ap_Door_Run → Drv_Motor_Set")
    for i, label in enumerate(sub_labels, start=8):
        ws.cell(row=i, column=_DESC_COL, value=label)   # sub-case 행엔 TC ID 없음
    wb.save(str(path))
    return str(path)


class TestValidatorCountsLabelledSubCases:
    r"""회귀 대상: 검증기가 `re.match(r"^\d", desc)` 로 sub-case 를 셌다.

    라이터는 `case_label or case_num` 을 쓰고 case_label 은 `COND_1 [...]` 처럼 **문자**로
    시작한다 — 라이터 포맷이 바뀌었는데 리더 휴리스틱이 안 따라갔다. 실측(실 프로젝트
    120 TC): 파일에 1288행이 있는데 840 만 세어 34.8% 과소, avg 7.0(실제 10.7).
    그런데도 valid 는 True 였다.
    """

    def test_letter_prefixed_labels_are_counted(self, tmp_path):
        labels = ["COND_1 [g_u8State=최솟값]", "ERR_PROP_1 [하한 초과]", "GLOBAL_2 [x]"]
        p = _write_min_sits(tmp_path / "s.xlsx", labels)
        st = validate_sits_xlsm(p)["stats"]
        assert st["sub_case_count"] == 3, "문자로 시작하는 sub-case 가 누락됐다"
        assert st["tc_count"] == 1

    def test_digit_prefixed_labels_still_counted(self, tmp_path):
        """대조군: 기존에 세던 숫자 시작 라벨도 그대로 세어야 한다(회귀 방지)."""
        p = _write_min_sits(tmp_path / "s.xlsx", ["1", "2", "3", "4"])
        assert validate_sits_xlsm(p)["stats"]["sub_case_count"] == 4

    def test_mixed_labels_are_all_counted(self, tmp_path):
        p = _write_min_sits(tmp_path / "s.xlsx", ["1", "COND_1 [a]", "2", "ERR_PROP_1 [b]"])
        st = validate_sits_xlsm(p)["stats"]
        assert st["sub_case_count"] == 4
        assert st["avg_sub_per_tc"] == 4.0

    def test_blank_rows_are_not_counted(self, tmp_path):
        """빈 desc 를 세면 반대 방향으로 거짓말한다."""
        p = _write_min_sits(tmp_path / "s.xlsx", ["COND_1 [a]", "", "   ", "COND_2 [b]"])
        assert validate_sits_xlsm(p)["stats"]["sub_case_count"] == 2

    def test_tc_row_is_not_double_counted_as_subcase(self, tmp_path):
        """TC 행도 desc 를 갖는다 — 구조 판정이 TC 를 sub 로 겹쳐 세면 안 된다."""
        p = _write_min_sits(tmp_path / "s.xlsx", ["COND_1 [a]"])
        st = validate_sits_xlsm(p)["stats"]
        assert (st["tc_count"], st["sub_case_count"]) == (1, 1)
