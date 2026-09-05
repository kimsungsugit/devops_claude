"""`docgen_field_sources` 드리프트 가드 + 사슬 판정 회귀.

## 왜 이 가드가 필요한가

`FIELD_SOURCES` 는 **코드의 복제**다. 실제 출처 라벨은 `report_gen/docx_builder.py` 등이
`info["asil_source"] = "sds"` 처럼 대입하는 리터럴이고, 그게 늘거나 줄면 이 표가 조용히
낡는다. 설계 라운드에서 실제로 두 번 낡았다:

- 1차: ASIL 을 `comment → sds` 로만 적었다 → 실제로는 `srs` 와 **`module_inherit`** 이 더 있었다.
- 2차: 정정했더니 이번엔 설명의 **`ai`**, Related 의 **`call_graph`·`reference`·`rule`**,
  양쪽의 **`hsis`** 가 빠져 있었다.

두 번 다 "화면이 없는 결핍을 말하는" 결함으로 이어졌을 것이다. 그래서 소스와 대조한다.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from backend.services import docgen_field_sources as fs

REPO = Path(__file__).resolve().parents[2]

# `info["<field>_source"] = "<literal>"` 형태만 잡는다. 함수 호출 대입
# (`unrecorded_source(...)`)은 리터럴이 아니라 여기 안 걸리는데, 그 함수의 반환값
# (`default`/`inference`/`unknown`)은 별도로 아래 `KNOWN_NON_LITERAL` 에 고정한다.
_ASSIGN = re.compile(
    r"""\[["'](asil|related|description)_source["']\]\s*=\s*["']([a-z_]+)["']"""
)

# 사슬을 만드는 파일 전부. 한 파일만 보면 놓친다 — 2차 드리프트가 정확히 그랬다.
_SOURCE_FILES = [
    "report_gen/docx_builder.py",
    "report_gen/validation.py",
    "report_gen/requirements.py",
    "report_gen/function_analyzer.py",
    "backend/routers/local.py",
    "backend/helpers/uds.py",
]

# `unrecorded_source()` 가 돌려주는 값 — 리터럴 대입이 아니라 regex 에 안 걸린다.
KNOWN_NON_LITERAL = {"default", "inference", "unknown"}


def _literals_in_source() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {"asil": set(), "related": set(), "description": set()}
    for rel in _SOURCE_FILES:
        p = REPO / rel
        if not p.exists():
            continue
        for field, label in _ASSIGN.findall(p.read_text(encoding="utf-8", errors="ignore")):
            found[field].add(label)
    return found


@pytest.mark.parametrize("field", ["asil", "related", "description"])
def test_field_sources_covers_every_literal_in_code(field: str) -> None:
    """소스가 대입하는 라벨이 **전부** 표에 있어야 한다(표가 좁으면 결핍을 못 본다)."""
    in_code = _literals_in_source()[field]
    assert in_code, f"{field}_source 리터럴을 하나도 못 찾았다 — 정규식이 낡았을 수 있다"
    missing = in_code - set(fs.FIELD_SOURCES[field])
    assert not missing, (
        f"{field}: 코드에는 있는데 FIELD_SOURCES 에 없는 출처 {sorted(missing)} — "
        "표가 낡았다. 그대로 두면 화면이 '없는 결핍'을 말한다"
    )


@pytest.mark.parametrize("field", ["asil", "related", "description"])
def test_field_sources_has_no_phantom_entry(field: str) -> None:
    """표에만 있고 코드엔 없는 출처가 없어야 한다(표가 넓으면 없는 경로를 안내한다)."""
    in_code = _literals_in_source()[field] | KNOWN_NON_LITERAL
    phantom = set(fs.FIELD_SOURCES[field]) - in_code
    assert not phantom, f"{field}: 코드에 없는 출처가 표에 있다 {sorted(phantom)}"


def test_every_source_has_input_mapping() -> None:
    """표의 모든 출처가 `SOURCE_REQUIRED_INPUT` 에 등록돼 있어야 한다.

    빠지면 `source_input()` 이 `None`(= 입력 불필요)을 돌려주고, 게이트는 그 출처를
    **근거 없는 자리 채움**으로 분류한다 — 실제로는 문서가 필요한데 "필요 없음" 이 된다.
    """
    for field, sources in fs.FIELD_SOURCES.items():
        for src in sources:
            assert (
                src in fs.PRE_ALIAS_SOURCE_INPUT
                or fs.canonical_source(src) in fs.SOURCE_REQUIRED_INPUT
            ), f"{field}/{src} 의 입력 매핑이 없다"


def test_hsis_is_not_folded_into_swds() -> None:
    """`hsis` 는 별칭으로 `sds` 가 되지만 **입력 축은 HSIS 문서**다.

    접고 나서 조회하면 "SwDS 가 있으니 채워진다" 는 틀린 안내가 된다.
    """
    assert fs.canonical_source("hsis") == "sds", "전제가 깨졌다 — provenance 별칭 확인"
    assert fs.source_input("hsis") == fs.INPUT_HSIS
    assert fs.source_input("sds") == fs.INPUT_SWDS


def test_internal_sources_are_not_grounded() -> None:
    """`module_inherit`/`rule`/`inference`/`default` 는 근거가 아니다.

    이걸 "확보" 로 세면 입력이 하나도 없는 프로젝트가 '준비 완료' 로 보인다.
    """
    rows = {r["source"]: r for r in fs.chain_state("asil", {})}
    assert rows["module_inherit"]["grounded"] is False
    assert rows["comment"]["grounded"] is True


def test_unknown_input_is_none_not_false() -> None:
    """확인하지 못한 입력은 `have=None` 이지 `False` 가 아니다.

    ⚠ 이 구분이 무너지면 "확인 실패" 가 "없음" 으로 보고된다 — IPC 한 번 실패에
    멀쩡한 문서가 사라지던 결함이 정확히 그 형태였다.
    """
    rows = {r["source"]: r for r in fs.chain_state("asil", {fs.INPUT_SWDS: False})}
    assert rows["sds"]["have"] is False          # 확인했고 없다
    assert rows["comment"]["have"] is None       # 아예 안 봤다
    assert rows["srs"]["have"] is None


def test_missing_grounded_inputs_only_when_all_empty() -> None:
    """하나라도 확보되면 결핍 목록은 비어야 한다 — 정상 구성을 결함으로 그리지 않는다."""
    all_empty = {fs.INPUT_SOURCE_COMMENT: False, fs.INPUT_SWDS: False,
                 fs.INPUT_SWRS: False, fs.INPUT_UDS_DOC: False}
    assert set(fs.missing_grounded_inputs("asil", all_empty)) == {
        fs.INPUT_SOURCE_COMMENT, fs.INPUT_SWDS, fs.INPUT_SWRS, fs.INPUT_UDS_DOC,
    }
    one_present = {**all_empty, fs.INPUT_SWDS: True}
    assert fs.missing_grounded_inputs("asil", one_present) == []


def test_unconfirmed_input_is_not_counted_as_missing() -> None:
    """`have=None`(확인 못 함)을 결핍으로 세면 안 된다."""
    assert fs.missing_grounded_inputs("asil", {}) == []


def test_module_does_not_use_normalize_field_source() -> None:
    """`_normalize_field_source` 는 6개 라벨만 알고 나머지를 `inference` 로 접는다.

    출처를 사람에게 보여주는 경로에서 그걸 쓰면 `default`(0.30)와 실제 추론(0.60)이
    같은 라벨이 된다 — `provenance.py` 가 고친 결함의 잔재다.
    """
    src = (REPO / "backend/services/docgen_field_sources.py").read_text(encoding="utf-8")
    assert "_normalize_field_source" not in src.split('"""')[-1], (
        "코드 본문에서 _normalize_field_source 를 쓰고 있다"
    )
