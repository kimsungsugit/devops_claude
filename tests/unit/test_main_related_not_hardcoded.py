"""`main` 의 Related ID 를 코드 리터럴로 쓰지 않는다 (R52 N39).

## 왜

"SwST_01, SwCom_01, SwSTR_01, SwSTR_02, SwSTR_04, SwSTR_06, SwSTR_09" 가 `report_gen/docx_builder.py` 3곳 ·
`report_gen/function_analyzer.py` 2곳에 박혀 있었고 그중 3곳은 **정본 값이 있어도 덮었다**(Initial commit 이래).
이 문자열은 KJPDS02 정본 v3.03 의 main 블록(SwUFn_0101) Related 이자 `docs/uds_function_swcom_override.json` 의
main 항목과 같은 값 — 한 프로젝트의 값이 모든 프로젝트의 main 에 실렸다. R51 이후 KJPDS02 에선 main 이 정본 중복
이름(SwCom_35 사본과 Related 가 갈림)이라 정본 축이 막히는데, 그때 이 리터럴이 `rule` 로 들어가 갈린 판정을 조용히
결정했다. 값은 파이프라인(주석 → override → SwDS → 정본)이 정하고, 없으면 다른 함수와 같이 TBD 다.
"""
from __future__ import annotations

from pathlib import Path

from report_gen import docx_builder as DB
from report_gen import function_analyzer as FA
from report_gen.function_analyzer import _finalize_function_fields, _function_info_pairs

_LITERAL_TAIL = "SwSTR_09"


def test_no_project_id_literal_in_builder_or_analyzer():
    for mod in (DB, FA):
        src = Path(str(mod.__file__)).read_text(encoding="utf-8")
        assert _LITERAL_TAIL not in src, f"{mod.__name__}: main Related 리터럴이 남아 있다"
    assert 'info["related_source"] = "rule"' not in Path(str(DB.__file__)).read_text(encoding="utf-8"), (
        "빌더가 리터럴을 `rule` 출처로 싣던 자리가 남아 있다")


def test_main_keeps_the_value_it_was_given():
    given = {"name": "main", "related": "SwCom_07", "related_source": "reference"}
    out = _finalize_function_fields(dict(given))
    assert out["related"] == "SwCom_07" and out["related_source"] == "reference"
    pairs = dict(_function_info_pairs(dict(given)))
    assert pairs["Related ID"] == "SwCom_07"


def test_main_without_value_is_tbd_like_any_other_function():
    out = _finalize_function_fields({"name": "main"})
    other = _finalize_function_fields({"name": "Other_Fn"})
    assert out["related"] == other["related"] == "TBD"
    assert dict(_function_info_pairs({"name": "main"}))["Related ID"] == "TBD"
