"""report_gen/requirements.py 텍스트 파서 — 설명 수집은 필드 라벨에서 멈춘다(대소문자 무관).

R51 에서 STS 표 파서(`generators/sts.parse_srs_docx_tables`)가 EI 표의 `Verification Criteria`(대문자 C)를 못 읽던 것을
고쳤다. 같은 정확 일치가 이 텍스트 파서의 멈춤 키에도 있어, 설명 바로 뒤에 그 라벨이 오면 검증 기준이 설명에 섞였다.
"""
from __future__ import annotations

import pytest

from report_gen.requirements import _extract_requirement_blocks, _extract_requirements_from_doc

TEXT = "ID\tSwEI_09\nName\tX\nDescription\t전압을 읽는다.\nVerification Criteria\t입력 전원 인가 (9.0, 12.0)\nASIL\tQM\n"


@pytest.mark.parametrize("label", ["Verification Criteria", "Verification criteria", "VERIFICATION CRITERIA"])
def test_the_description_stops_at_the_label_whatever_its_case(label):
    text = TEXT.replace("Verification Criteria", label)
    (block,) = _extract_requirement_blocks(text)
    assert block["description"] == "전압을 읽는다."
    assert "인가" not in _extract_requirements_from_doc(text)[0]


def test_a_description_line_is_still_collected():
    (block,) = _extract_requirement_blocks("ID\tSwEI_09\nDescription\t첫 줄.\n둘째 줄.\nRationale\t이유\n")
    assert block["description"] == "첫 줄. 둘째 줄."
