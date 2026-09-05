"""C 타입 경계값 테이블 드리프트 방지 — 4중 복제본의 정합 대조.

저장소에 경계값 테이블이 네 벌 있었고 성격이 둘로 갈린다:

  (1) **실 문서 산출값** — `generators/suts.py:_TYPE_BOUNDARIES`(5점 dict),
      `generators/sits.py:_BOUNDARY_SETS`(7점 list). 실제 xlsm 셀에 쓰이므로 불가침.
  (2) **표시/프롬프트 표기** — `workflow/c_type_bounds.py`(단일 출처)와
      프론트 `frontend-v2/src/impactBoundary.js`.

(2)는 `workflow/c_type_bounds.py`로 합쳤고, 프론트는 JS 런타임 사정상 별도 구현이 남아
`tests/fixtures/c_type_bounds.json`을 **양쪽이 함께 assert**한다(프론트 쪽은
`frontend-v2/src/__tests__/impactBoundary.test.js`). 이 파일은 그 픽스처 정합 + (1)과의
수치 정합을 담당한다.

⚠ **MID는 대조하지 않는다.** (1)과 (2)의 MID 정의가 실제로 다르다:
   - 표시 u16 MID = 0x8000 = 32768 (비트폭 중앙)
   - `_TYPE_BOUNDARIES["uint16_t"]["mid"]` = 32767 (max_valid - 1 계열)
   - `_BOUNDARY_SETS["uint16"][3]` = 32767
   누군가 "정합을 맞춘다"며 표시 MID를 생성기 값에 끌어다 맞추지 않도록 남긴다.

   ✅ **uint32 MID 는 해소됐다(2026-08-19, R25).** 이 자리에 원래 이렇게 적혀 있었다 —
   "`_TYPE_BOUNDARIES["uint32_t"]["mid"]`는 `2**15`(=32768)로 uint32의 중앙이 아니지만
   실 문서 산출값이라 여기서 고치지 않는다(별도 판단 필요)". 그 **별도 판단이 나왔다**:
     · 내부 규칙 — 부호 없는 mid 는 `max // 2`(255//2=127 · 65535//2=32767)
     · 형제 생성기 — `_BOUNDARY_SETS["uint32"][3]` 이 이미 `0x7FFFFFFF` 였다
     · 정본 실측 — 정본 SUTS 는 uint32 칸에 `0x7FFFFFFF` 를 쓰고(우리가 못 내던 칸 52개),
       우리가 쓰던 32768 은 정본 uint32 칸에 **0회** 등장한다
   → `2**31-1` 로 교정. 고정은 `tests/unit/test_suts_uint32_mid_boundary.py`.

따라서 대조 대상은 **MIN / MAX (+ u8의 INV)** — 세 테이블이 일치해야 하는 값들이다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "c_type_bounds.json"


def _display(type_key: str) -> dict:
    """표시 테이블의 {label: value} — 정규화 키('u16') 기준."""
    from workflow.c_type_bounds import GENERATOR_TYPE_NAME, c_type_boundaries

    assert type_key in GENERATOR_TYPE_NAME, f"미등록 타입 키: {type_key}"
    return dict(c_type_boundaries(type_key))


def _as_int(v: str) -> int:
    """'0xFFFF' / '-128' / '0x100(범위초과)' → int. 표시값은 hex 또는 10진."""
    s = str(v).split("(")[0].strip()
    return int(s, 16) if s.lower().startswith(("0x", "-0x")) else int(s)


# 표시 키 → generators/suts.py `_TYPE_BOUNDARIES` 키
_SUTS_KEYS = {
    "u8": "uint8_t", "u16": "uint16_t", "u32": "uint32_t",
    "s8": "int8_t", "s16": "int16_t", "s32": "int32_t", "bool": "bool",
}
# 표시 키 → generators/sits.py `_BOUNDARY_SETS` 키
_SITS_KEYS = {
    "u8": "uint8", "u16": "uint16", "u32": "uint32",
    "s8": "int8", "s16": "int16", "s32": "int32", "bool": "bool",
}
_SITS_MIN_IDX, _SITS_MAX_IDX = 1, 5  # min_valid, max_valid (7점 배열)


@pytest.mark.parametrize("key", sorted(_SUTS_KEYS))
def test_display_matches_suts_generator_min_max(key: str):
    """표시 MIN/MAX == generators/suts.py `_TYPE_BOUNDARIES`의 min/max (진법 무관)."""
    from generators.suts import _TYPE_BOUNDARIES

    disp = _display(key)
    gen = _TYPE_BOUNDARIES[_SUTS_KEYS[key]]
    min_label = "FALSE" if key == "bool" else "MIN"
    max_label = "TRUE" if key == "bool" else "MAX"
    assert _as_int(disp[min_label]) == gen["min"], f"{key} MIN 드리프트"
    assert _as_int(disp[max_label]) == gen["max"], f"{key} MAX 드리프트"


@pytest.mark.parametrize("key", sorted(_SITS_KEYS))
def test_display_matches_sits_generator_min_max(key: str):
    """표시 MIN/MAX == generators/sits.py `_BOUNDARY_SETS`의 min_valid/max_valid."""
    from generators.sits import _BOUNDARY_SETS

    disp = _display(key)
    gen = _BOUNDARY_SETS[_SITS_KEYS[key]]
    min_label = "FALSE" if key == "bool" else "MIN"
    max_label = "TRUE" if key == "bool" else "MAX"
    assert _as_int(disp[min_label]) == gen[_SITS_MIN_IDX], f"{key} min_valid 드리프트"
    assert _as_int(disp[max_label]) == gen[_SITS_MAX_IDX], f"{key} max_valid 드리프트"


def test_u8_inv_matches_suts_max_inv():
    """u8만 INV 라벨을 노출한다 — `_TYPE_BOUNDARIES["uint8_t"]["max_inv"]`와 일치."""
    from generators.suts import _TYPE_BOUNDARIES

    assert _as_int(_display("u8")["INV"]) == _TYPE_BOUNDARIES["uint8_t"]["max_inv"]


def test_fixture_matches_module():
    """픽스처 == 모듈. 프론트 vitest가 같은 픽스처를 읽으므로 이게 곧 프론트 정합이다."""
    from workflow.c_type_bounds import fixture_payload

    assert FIXTURE.exists(), (
        f"{FIXTURE} 부재 — 재생성: "
        r'.venv/Scripts/python.exe -c "import json,pathlib;'
        r"from workflow.c_type_bounds import fixture_payload;"
        r"pathlib.Path('tests/fixtures/c_type_bounds.json').write_text("
        r"json.dumps(fixture_payload(),ensure_ascii=False,indent=2,sort_keys=True)+chr(10),encoding='utf-8')\""
    )
    on_disk = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(fixture_payload(), ensure_ascii=False))


def test_unknown_type_yields_no_numbers():
    """미상 타입(enum/struct/typedef)은 빈 리스트 — 숫자 환각 금지(정직성 규약)."""
    from workflow.c_type_bounds import c_type_boundaries, normalize_c_type

    for t in ("MyEnum_t", "struct Foo", "", "SomeTypedef"):
        assert c_type_boundaries(t) == [], f"{t!r}에 숫자가 생성됨"
        assert normalize_c_type(t) == ""


def test_normalize_c_type_excludes_pointer_array_float():
    """`normalize_c_type`은 정수 경계 산출 대상만 키를 준다 — 포인터/배열/float는 ''."""
    from workflow.c_type_bounds import normalize_c_type

    assert normalize_c_type("U16") == "u16"
    assert normalize_c_type("const U16") == "u16"
    assert normalize_c_type("unsigned short") == "u16"
    assert normalize_c_type("U8*") == ""     # 포인터 — 경계값이 NULL/유효라 정수 축 아님
    assert normalize_c_type("U8[8]") == ""   # 배열도 동일
    assert normalize_c_type("float") == ""   # float은 특수 라벨 계열
