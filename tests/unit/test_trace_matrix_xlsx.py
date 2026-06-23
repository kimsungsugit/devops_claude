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


def test_produces_valid_xlsx_with_three_sheets():
    data = build_trace_xlsx(_matrix_with_link_table(), {"project_name": "P", "generated_at": "2026-06-23T00:00:00"})
    assert isinstance(data, bytes) and len(data) > 0
    wb = _open(data)
    assert wb.sheetnames == ["교차표", "링크테이블", "커버리지"]


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
    txt = [ws.cell(r, c).value for r in range(1, ws.max_row + 1) for c in range(1, 6)]
    assert any(v == "오참조 의심" for v in txt)   # suspect severity 셀
    assert any(v == "계층참조" for v in txt)      # foreign severity 셀
    assert ws.cell(2, 2).value and "오참조 의심 1" in ws.cell(2, 2).value


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
