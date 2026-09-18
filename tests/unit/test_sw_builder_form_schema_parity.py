"""빌더 폼(JS) ↔ request schema(Python) **키 정합** — `extra='forbid'` 의 반대편.

## 왜 이 파일이 있나 (2026-08-21)

생성 현황 보드가 SwUT/SwIT 6종을 **한 폼**(`swBuilderForms.js` 의 `BUILDER_SPECS`)으로
만들게 됐다. 그런데 endpoint 마다 request schema 가 다르다:

    /api/swut/coverage|sutr|swutcr/build  -> SwUTBuildRequest
    /api/swit/coverage|switcr/build       -> SwITBuildRequest
    /api/swit/sitr/build                  -> SwITSitrBuildRequest (SwITBuildRequest 하위)

세 schema 모두 `extra='forbid'` 다. 폼에 필드를 하나 늘리면서 해당 schema 에 안 넣으면
**그 endpoint 만** 422 가 된다 — 다른 두 개는 멀쩡하므로 "빌더는 되는데 보드에서만
안 된다" 는 형태로 나타나고, 원인이 폼-스키마 불일치라는 건 응답 본문을 열어야 안다.

`swBuilderForms.js` 의 docstring 이 이 규약을 말로 적어 뒀지만 **언어 경계를 넘는 검사가
없었다.** 여기서 넘는다.

⚠ 정본은 JS 쪽이다(폼이 무엇을 보내는가). 이 파일은 그 키 목록을 읽어 schema 와 맞춘다.
"""
from __future__ import annotations

import pathlib
import re

import pytest

from backend.schemas import (
    SwITBuildRequest,
    SwITSitrBuildRequest,
    SwReportBuildRequest,
    SwUTBuildRequest,
)

_FORMS_JS = pathlib.Path("frontend-v2/src/swBuilderForms.js")


def _default_form_keys(const_name: str) -> set[str]:
    """`const <NAME> = { ... };` 블록의 최상위 키."""
    src = _FORMS_JS.read_text(encoding="utf-8")
    m = re.search(r"const " + const_name + r" = \{(.*?)\n\};", src, re.S)
    assert m, f"{const_name} 를 찾지 못했다 — 상수 이름이 바뀌었으면 이 테스트도 따라가야 한다"
    body = m.group(1)
    # 주석 줄 제거 후 `key:` 만 뽑는다(중첩 객체 없음 — 전부 스칼라 기본값).
    lines = [ln for ln in body.splitlines() if not ln.strip().startswith("//")]
    return set(re.findall(r"^\s{2}([a-z_][a-z0-9_]*):", "\n".join(lines), re.M))


def _list_field(kind: str) -> tuple[str, str]:
    """`BUILDER_SPECS[kind].listField` 의 (UI 전용 text 키, payload 배열 키)."""
    src = _FORMS_JS.read_text(encoding="utf-8")
    m = re.search(
        r"\n  " + kind + r": \{.*?listField: \{ text: '([a-z_]+)', target: '([a-z_]+)'",
        src, re.S,
    )
    assert m, f"BUILDER_SPECS.{kind}.listField 를 찾지 못했다"
    return m.group(1), m.group(2)


CASES = [
    # (빌더 종류, 기본 폼 상수, 이 폼이 도달하는 schema 들)
    ("swut", "SWUT_DEFAULT_FORM", [SwUTBuildRequest]),
    ("swit", "SWIT_DEFAULT_FORM", [SwITBuildRequest, SwITSitrBuildRequest]),
    ("swreport", "SWREPORT_DEFAULT_FORM", [SwReportBuildRequest]),
]


@pytest.mark.parametrize("kind,const_name,models", CASES, ids=[c[0] for c in CASES])
def test_payload_keys_are_accepted_by_every_schema_it_reaches(kind, const_name, models):
    text_key, target_key = _list_field(kind)
    keys = _default_form_keys(const_name)
    assert text_key in keys, f"{kind}: UI 전용 키 {text_key} 가 기본 폼에 없다"
    # `toBuildPayload` 는 text 키를 지우고 target 배열을 넣는다.
    payload_keys = (keys - {text_key}) | {target_key}
    for model in models:
        unknown = payload_keys - set(model.model_fields)
        assert not unknown, (
            f"{kind} 폼이 {model.__name__} 에 없는 키를 보낸다: {sorted(unknown)} "
            f"— 이 schema 를 쓰는 endpoint 만 422 가 된다"
        )


def test_regex_actually_reads_something():
    """검사 대상이 0개면 위 테스트는 **공허 통과**한다 — 파서가 살아 있는지 못 박는다."""
    for _kind, const_name, _models in CASES:
        assert len(_default_form_keys(const_name)) >= 8, const_name
    # 각 폼이 서로 다른 키 집합을 갖는다(같으면 정규식이 한 블록만 읽고 있는 것).
    swut = _default_form_keys("SWUT_DEFAULT_FORM")
    swit = _default_form_keys("SWIT_DEFAULT_FORM")
    assert "sutr_template_path" in swut and "sutr_template_path" not in swit
    assert "switcr_template_path" in swit and "switcr_template_path" not in swut


def test_required_fields_exist_in_every_schema():
    """세 schema 공통 필수 3개(`REQUIRED_FIELDS`)가 실제로 공통인가."""
    src = _FORMS_JS.read_text(encoding="utf-8")
    m = re.search(r"export const REQUIRED_FIELDS = \[(.*?)\];", src, re.S)
    assert m
    fields = set(re.findall(r"'([a-z_]+)'", m.group(1)))
    assert fields, "REQUIRED_FIELDS 가 비었다"
    for model in (SwUTBuildRequest, SwITBuildRequest, SwReportBuildRequest):
        assert fields <= set(model.model_fields), model.__name__


# ── 보드가 폼 밖에서 덧붙이는 키 ────────────────────────────────────────────
#
# `DocGenStatusBoard` 의 `payloadForm` 은 저장 폼에 세 값을 덧씌운다:
# `release_sw_version`(행 입력) · `project_id`(SCM 양식 키) · `scm_id`(프로젝트 축).
# 앞의 둘은 기본 폼에도 있어 위 테스트가 덮지만 **`scm_id` 는 기본 폼에 없다**
# (localStorage 에 굳히면 안 되는 문맥값이라 일부러 안 넣었다). 그래서 따로 못 박는다.

_BOARD_EXTRA_KEYS = ["scm_id"]


@pytest.mark.parametrize(
    "model",
    [SwUTBuildRequest, SwITBuildRequest, SwITSitrBuildRequest, SwReportBuildRequest],
    ids=lambda m: m.__name__,
)
def test_board_added_keys_are_accepted(model):
    for key in _BOARD_EXTRA_KEYS:
        assert key in model.model_fields, (
            f"{model.__name__} 이 보드가 덧붙이는 `{key}` 를 모른다 — extra='forbid' 라 422 다"
        )


def test_board_actually_sends_scm_id():
    """스키마에만 있고 화면이 안 실으면 **추측 경로가 그대로 남는다**(=고친 게 없다)."""
    src = pathlib.Path(
        "frontend-v2/src/components/sections/DocGenStatusBoard.jsx"
    ).read_text(encoding="utf-8")
    i = src.find("payloadForm:")
    assert i > 0, "payloadForm 이 사라졌다 — 테스트가 겨눌 대상이 없다"
    block = src[i:i + 400]
    assert "scm_id: scmId" in block, "payloadForm 이 scm_id 를 싣지 않는다"
