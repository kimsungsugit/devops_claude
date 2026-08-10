"""결과 귀속 — "이 칸이 왜 비었나" 를 사슬로 되짚는다.

## 이 파일의 본체는 드리프트 가드다

`LABEL_TO_SOURCE` 는 `report_gen/validation.py::src_labels` 의 **복제**다. 그 표가
`generate_asil_related_confidence_report` 함수 내부의 지역 변수라 import 할 수 없어서
복제할 수밖에 없었는데, 복제는 반드시 낡는다. 라벨이 하나만 바뀌어도 귀속이 조용히
틀리고(그 출처가 0건으로 보인다) 화면은 **없는 원인**을 지목한다.

그래서 소스의 리터럴과 대조한다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.services import docgen_field_sources as fs

REPO = Path(__file__).resolve().parents[2]


def _src_labels_from_source() -> dict[str, str]:
    """`validation.py` 의 `src_labels` 딕셔너리 리터럴을 읽는다(import 부작용 없이)."""
    text = (REPO / "report_gen/validation.py").read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"src_labels\s*=\s*\{(.*?)\n\s*\}", text, re.S)
    assert m, "src_labels 리터럴을 찾지 못했다 — 정규식이 낡았을 수 있다"
    body = m.group(1)
    out: dict[str, str] = {}
    for code, label in re.findall(r'"([a-z_]+)"\s*:\s*"([^"]*)"', body):
        out[code] = label
    return out


def test_label_map_matches_validation_source() -> None:
    """복제한 라벨이 정본과 **양방향으로** 일치해야 한다."""
    src = _src_labels_from_source()
    assert src, "라벨을 하나도 못 읽었다"
    mine = fs.LABEL_TO_SOURCE

    missing = {code: label for code, label in src.items() if label not in mine}
    assert not missing, (
        f"정본에 있는데 LABEL_TO_SOURCE 에 없는 라벨 {missing} — "
        "귀속이 그 출처를 0건으로 오인한다"
    )
    phantom = {label: code for label, code in mine.items() if label not in src.values()}
    assert not phantom, f"정본에 없는 라벨이 복제본에 있다 {phantom}"

    for code, label in src.items():
        assert mine[label] == code, f"{label!r} 이 {mine[label]!r} 로 매핑됐다(정본은 {code!r})"


# ── 분포 파싱 ───────────────────────────────────────────────────────────────

def test_parse_distribution_reads_sidecar_lines() -> None:
    lines = ["주석: `12` / `435` (2.8%)", "SDS: `40` / `435` (9.2%)"]
    dist = fs.parse_source_distribution(lines)
    assert dist == {"comment": 12, "sds": 40}


def test_parse_distribution_keeps_unknown_label() -> None:
    """모르는 라벨을 **버리지 않는다** — 버리면 그 출처가 0건으로 읽힌다."""
    dist = fs.parse_source_distribution(["새출처: `7` / `100` (7.0%)"])
    assert dist.get("새출처") == 7


def test_parse_distribution_ignores_non_matching() -> None:
    assert fs.parse_source_distribution(["none", "", "설명만 있는 줄"]) == {}


def test_parse_distribution_handles_empty() -> None:
    assert fs.parse_source_distribution(None) == {}
    assert fs.parse_source_distribution([]) == {}


# ── 귀속 ────────────────────────────────────────────────────────────────────

def test_attribution_marks_contributing_sources() -> None:
    res = fs.attribute_field("asil", {"sds": 40, "default": 395},
                             {fs.INPUT_SWDS: True})
    rows = {r["source"]: r for r in res["rows"]}
    assert rows["sds"]["contributed"] is True
    assert rows["sds"]["count"] == 40
    assert rows["comment"]["contributed"] is False
    # `default` 는 근거가 아니다 — 근거 합계에 들어가면 안 된다.
    assert rows["default"]["grounded"] is False
    assert res["grounded_total"] == 40
    assert res["ungrounded_total"] == 395


def test_attribution_separates_grounded_from_filler() -> None:
    """생성기 내부 산출(`module_inherit`/`inference`/`default`)은 근거가 아니다.

    합쳐 세면 "435칸 중 435칸이 채워졌다" 가 되어 **근거 없는 문서가 완성본으로 보인다**.
    """
    res = fs.attribute_field("asil", {"module_inherit": 200, "default": 235}, {})
    assert res["grounded_total"] == 0
    assert res["ungrounded_total"] == 435


def test_attribution_distinguishes_unknown_from_absent_now() -> None:
    """현재 가용성은 3상태다 — 확인 안 한 입력을 `False` 로 접지 않는다."""
    res = fs.attribute_field("asil", {}, {fs.INPUT_SWDS: False})
    rows = {r["source"]: r for r in res["rows"]}
    assert rows["sds"]["have_now"] is False       # 확인했고 없음
    assert rows["comment"]["have_now"] is None    # 확인 안 함


def test_attribution_covers_uds_source() -> None:
    """UDS 문서 직독 경로가 사슬에 있어야 한다(드리프트 가드가 3차로 잡아낸 출처)."""
    res = fs.attribute_field("asil", {"uds": 10}, {fs.INPUT_UDS_DOC: True})
    rows = {r["source"]: r for r in res["rows"]}
    assert rows["uds"]["count"] == 10
    assert rows["uds"]["input"] == fs.INPUT_UDS_DOC


@pytest.mark.parametrize("field", ["asil", "related", "description"])
def test_attribution_shape_for_every_field(field: str) -> None:
    res = fs.attribute_field(field, {}, {})
    assert res["field"] == field
    assert res["label"]
    assert res["rows"], f"{field}: 사슬이 비어 있다"
    for r in res["rows"]:
        assert set(r) >= {"source", "input", "count", "contributed", "grounded", "have_now"}
