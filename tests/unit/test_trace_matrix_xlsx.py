"""report_gen.trace_matrix_xlsx.build_trace_xlsx 단위 테스트.

검증: 유효한 xlsx 바이트 생성, 3시트 구성, 교차표 O마크·ASIL 열, 링크테이블 행수,
graceful(빈/asil없음), DoS 캡.
"""

import io

import pytest

openpyxl = pytest.importorskip("openpyxl")

from report_gen.trace_link_table import build_link_table  # noqa: E402
from report_gen.trace_matrix_xlsx import build_trace_xlsx  # noqa: E402


def _matrix_with_link_table():
    m = {
        "rows": [
            {
                "requirement_id": "R1", "requirement_name": "요구1", "asil": "A",
                "sds_components": ["compA", "compB"], "source_ids": ["f1"],
                "sts_tests": [{"testcase": "T1", "source": "STS"}],
                "suts_tests": [], "sits_tests": [], "tests": [],
            },
            {
                "requirement_id": "R2", "requirement_name": "요구2", "asil": "",
                "sds_components": ["compB"], "source_ids": [],
                "sts_tests": [], "suts_tests": [], "sits_tests": [], "tests": [],
            },
        ],
    }
    m["link_table"] = build_link_table(m)
    return m


def _open(data):
    return openpyxl.load_workbook(io.BytesIO(data))


def test_produces_valid_xlsx_with_base_sheets():
    data = build_trace_xlsx(_matrix_with_link_table(), {"project_name": "P", "generated_at": "2026-06-23T00:00:00"})
    assert isinstance(data, bytes) and len(data) > 0
    wb = _open(data)
    # 기본 3시트 + 갭 finding(테스트 매트릭스 R1=SITS 갭·R2=UDS 갭). integrity 없어 '정합성 감사' 시트는 생략.
    assert wb.sheetnames == ["교차표", "링크테이블", "커버리지", "추적성 갭 finding"]


def test_cross_sheet_has_asil_col_and_o_marks():
    data = build_trace_xlsx(_matrix_with_link_table())
    ws = _open(data)["교차표"]
    # 헤더행 탐색
    hr = next((r for r in range(1, 20) if ws.cell(r, 1).value == "요구사항"), None)
    assert hr is not None
    headers = [ws.cell(hr, c).value for c in range(1, ws.max_column + 1)]
    assert "ASIL" in headers          # asil 데이터 있으니 열 노출
    assert "compA" in headers and "compB" in headers  # SDS 열
    # R1 행: compA 셀이 O
    r1 = hr + 1
    ca = headers.index("compA") + 1
    assert ws.cell(r1, ca).value == "O"


def test_link_table_sheet_row_count():
    m = _matrix_with_link_table()
    data = build_trace_xlsx(m)
    ws = _open(data)["링크테이블"]
    assert ws.cell(1, 1).value == "target_id"
    assert ws.max_row - 1 == len(m["link_table"]["links"])  # 헤더 제외 = 링크 수


def test_graceful_no_asil_no_link_table():
    # asil 없고 link_table도 없는 최소 매트릭스 → ASIL 열 없이 정상 생성
    data = build_trace_xlsx({"rows": [{"requirement_id": "R1", "sds_components": ["c1"]}]})
    ws = _open(data)["교차표"]
    hr = next((r for r in range(1, 20) if ws.cell(r, 1).value == "요구사항"), None)
    headers = [ws.cell(hr, c).value for c in range(1, ws.max_column + 1)]
    assert "ASIL" not in headers


def test_empty_matrix_safe():
    data = build_trace_xlsx({})
    assert isinstance(data, bytes) and len(data) > 0
    wb = _open(data)
    assert "교차표" in wb.sheetnames


def test_accepts_wrapped_matrix():
    wrapped = {"matrix": _matrix_with_link_table()}
    data = build_trace_xlsx(wrapped)
    assert _open(data)["링크테이블"].max_row > 1


def test_integrity_sheet_rendered():
    # integrity 키가 있으면 '정합성 감사' 시트 생성 + severity 셀 표기
    m = {
        "rows": [{"requirement_id": "R1", "sds_components": ["c1"]}],
        "integrity": {
            "id_collisions": [{"canonical": "R1", "variants": ["R1", "r 1"], "variant_count": 2, "kept": "R1"}],
            "dangling_refs": {"UDS": [
                {"ref_id": "SwX_9", "normalized": "SWX_9", "namespace": "SWX", "severity": "foreign"},
                {"ref_id": "R_99", "normalized": "R_99", "namespace": "R", "severity": "suspect"},
            ]},
            "dangling_by_namespace": {"UDS": {"SWX": 1, "R": 1}},
            "placeholder_ids": {"SDS": ["c_XX"]},
            "stats": {"collision_count": 1, "collision_affected_raw": 2, "dangling_count": 2,
                      "dangling_suspect_count": 1, "dangling_foreign_count": 1,
                      "placeholder_count": 1, "clean": False},
        },
    }
    ws = _open(build_trace_xlsx(m))["정합성 감사"]
    txt = [ws.cell(r, c).value for r in range(1, ws.max_row + 1) for c in range(1, 7)]
    assert any(v == "오참조 의심" for v in txt)   # suspect severity 셀
    assert any(v == "계층참조" for v in txt)      # foreign severity 셀
    assert ws.cell(2, 2).value and "오참조 의심 1" in ws.cell(2, 2).value


def test_integrity_sheet_layer_column():
    # 설계계층 라벨(추가형): dangling 표 끝에 'V-model 계층' 열 + layer 값 렌더.
    m = {
        "rows": [{"requirement_id": "R1", "sds_components": ["c1"]}],
        "integrity": {
            "id_collisions": [],
            "dangling_refs": {"UDS": [
                {"ref_id": "SwSTR_7", "normalized": "SWSTR_7", "namespace": "SWSTR",
                 "severity": "foreign", "layer": "SwDS(설계)"},
            ]},
            "dangling_by_namespace": {"UDS": {"SWSTR": 1}},
            "dangling_layer_summary": {"SwDS(설계)": 1},
            "placeholder_ids": {},
            "stats": {"collision_count": 0, "collision_affected_raw": 0, "dangling_count": 1,
                      "dangling_suspect_count": 0, "dangling_foreign_count": 1,
                      "placeholder_count": 0, "clean": False},
        },
    }
    ws = _open(build_trace_xlsx(m))["정합성 감사"]
    txt = [ws.cell(r, c).value for r in range(1, ws.max_row + 1) for c in range(1, 7)]
    assert "V-model 계층" in txt          # 헤더 열
    assert "SwDS(설계)" in txt            # layer 값 셀 + 계층참조 분포 라인
    assert any(v and "계층참조 분포" in str(v) for v in txt)


def test_sheet4_dos_capped():
    # 조작된 대량 dangling(수만 항목 × 수백 밴드)에도 시트4 행이 상한 내로 제한
    from report_gen.trace_matrix_xlsx import _MAX_SHEET4_ROWS
    big_bands = {
        f"B{b}": [{"ref_id": f"x{i}", "normalized": f"X{i}", "namespace": "X", "severity": "foreign"}
                  for i in range(2000)]
        for b in range(50)  # 50밴드 × 2000 = 10만 항목
    }
    m = {
        "rows": [{"requirement_id": "R1", "sds_components": ["c1"]}],
        "integrity": {
            "id_collisions": [], "dangling_refs": big_bands, "dangling_by_namespace": {},
            "placeholder_ids": {},
            "stats": {"collision_count": 0, "collision_affected_raw": 0, "dangling_count": 100000,
                      "dangling_suspect_count": 0, "dangling_foreign_count": 100000,
                      "placeholder_count": 0, "clean": False},
        },
    }
    ws = _open(build_trace_xlsx(m))["정합성 감사"]
    assert ws.max_row <= _MAX_SHEET4_ROWS + 10  # 헤더 여유 포함 상한 내


def test_formula_injection_guarded():
    # 문서유래 값이 =,+,@ 로 시작하면 ' 프리픽스로 수식 해석 차단(export 보안)
    m = {"rows": [{"requirement_id": "=cmd", "requirement_name": "+evil", "sds_components": ["@x"]}]}
    m["link_table"] = build_link_table(m)
    data = build_trace_xlsx(m)
    ws = _open(data)["교차표"]
    hr = next(r for r in range(1, 20) if ws.cell(r, 1).value == "요구사항")
    assert str(ws.cell(hr + 1, 1).value).startswith("'=")   # rid
    assert str(ws.cell(hr + 1, 2).value).startswith("'+")   # name
    # 링크테이블 target_id도 가드
    ws2 = _open(data)["링크테이블"]
    assert str(ws2.cell(2, 1).value).startswith("'=")


def test_asil_cell_formula_injection_guarded():
    # CRITICAL 회귀(11a859a 적대검증): 교차표 ASIL 셀도 _cs 가드를 거쳐야 한다.
    # export 엔드포인트가 클라 matrix body를 echo하므로 ASIL 값이 신뢰 불가 입력 표면.
    # 정상 'A' 행이 has_asil을 발동시켜 ASIL 열이 노출되고, 주입 행 셀이 무력화돼야 함.
    m = {"rows": [
        {"requirement_id": "R1", "requirement_name": "n1", "asil": "A", "sds_components": ["c1"]},
        {"requirement_id": "R2", "requirement_name": "n2",
         "asil": '=HYPERLINK("http://evil")', "sds_components": ["c1"]},
    ]}
    m["link_table"] = build_link_table(m)
    ws = _open(build_trace_xlsx(m))["교차표"]
    hr = next(r for r in range(1, 20) if ws.cell(r, 1).value == "요구사항")
    headers = [ws.cell(hr, c).value for c in range(1, ws.max_column + 1)]
    assert "ASIL" in headers   # 정상 A 행이 has_asil 발동 → ASIL 열 노출
    ai = headers.index("ASIL") + 1
    r2 = next(r for r in range(hr + 1, ws.max_row + 1) if ws.cell(r, 1).value == "R2")
    assert str(ws.cell(r2, ai).value).startswith("'=")   # 수식 → ' 프리픽스로 무력화


def _finding_text(wb):
    ws = wb["추적성 갭 finding"]
    return " ".join(
        str(c) for row in ws.iter_rows(values_only=True) for c in row if c not in (None, "")
    )


def test_finding_sheet_credits_alternative_verification():
    """비기능(SyTS/STS)·인터페이스(HSIS/SyITS) 대체검증 요구는 진짜 갭에서 제외(프론트 gapStats lockstep)."""
    m = {"rows": [
        # 기능요구 SITS 갭(UDS 있어 UDS 갭은 아님)
        {"requirement_id": "SwTR_1", "sds_components": ["a"], "source_ids": ["f1"],
         "suts_tests": [{"unit": "f1"}], "sts_tests": [{"testcase": "T"}]},
        # 비기능 대체검증(SyTS) → SITS/UDS 갭 제외
        {"requirement_id": "SwNTR_1", "sds_components": ["b"], "syts_tests": [{"testcase": "T"}]},
        # 인터페이스 대체검증(HSIS) → SITS/UDS 갭 제외
        {"requirement_id": "SwEI_1", "sds_components": ["c"], "hsis_signals": ["sig"]},
    ], "link_table": {}}
    text = _finding_text(_open(build_trace_xlsx(m)))
    assert "SwTR_1" in text          # 기능요구 갭은 표시
    assert "SwNTR_1" not in text     # 비기능 대체검증은 제외(은폐 아님·정직화)
    assert "SwEI_1" not in text      # 인터페이스 대체검증은 제외


def test_finding_sheet_lists_app_leaf_with_safety():
    """unmapped_vcast의 APP_LEAF만 함수명+안전표시로 나열(BOOT/BSW/LIB은 제외)."""
    m = {"rows": [], "link_table": {}, "unmapped_vcast": [
        {"subprogram": "SwUFn_1", "layer": "APP_LEAF", "category": "suts_tested",
         "uds_funcs": ["u32s_Add_Guarded"], "safety": True, "sds_reqs": []},
        {"subprogram": "SwUFn_2", "layer": "BOOT_REPROG", "category": "vcast_only",
         "uds_funcs": ["boot_x"], "safety": False, "sds_reqs": []},
    ]}
    text = _finding_text(_open(build_trace_xlsx(m)))
    assert "u32s_Add_Guarded" in text   # APP_LEAF 함수명
    assert "★안전" in text               # 안전 강조
    assert "boot_x" not in text         # BOOT_REPROG은 finding 대상 아님


def test_finding_sheet_present_but_empty_when_clean():
    """갭 없는 매트릭스도 finding 시트는 존재하되 각 섹션 '해당 없음'(감사 positive 확인)."""
    m = {"rows": [
        {"requirement_id": "SwTR_9", "sds_components": ["a"], "source_ids": ["f"],
         "suts_tests": [{"unit": "f"}], "sits_tests": [{"testcase": "I"}]},
    ], "link_table": {}}
    wb = _open(build_trace_xlsx(m))
    assert "추적성 갭 finding" in wb.sheetnames
    assert "해당 없음" in _finding_text(wb)
