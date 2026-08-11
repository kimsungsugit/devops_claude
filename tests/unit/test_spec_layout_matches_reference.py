"""생성 산출물의 시트 레이아웃 ↔ **납품 정본** 정합 가드.

## 왜 이 파일이 있나

2026-08-11 실측에서 세 산출물이 전부 정본과 어긋나 있었다. 그중 둘은 **다른 문서의
열을 쓰고 있었다**:

- SUTS 가 `Description`/`Test Environment`/`Precondition`/`Sequence` 를 가졌는데
  그건 **SwTS 정본의 열**이다 → 열이 밀려 정본 파서가 전부 잘못 읽는다.
- SITS 의 F열이 `Precondition` 이라 정본의 `Test Method` 자리를 차지했다.
- STS 는 시험 명세를 `3.SW Integration Test Spec`(= SwITS 의 시트명)에 쓰고 있었다.

전부 **조용한** 결함이다 — 파일은 열리고 값도 차 있어서 눈으로는 안 보인다. 그래서
"열 라벨 집합"과 "시트명"을 여기서 고정한다.

## 어휘도 함께 고정한다

같은 개념이라도 **문서마다 약어가 다르다**(각 문서 Introduction 1.5/1.6 실측):

| | Test Method | Generation Method |
|---|---|---|
| SwTS  | RBT · FIT       | AOR · ECA · BAA |
| SwUTS | REQ · IFT · FI  | AOR · AEC · ABV · ERG |
| SwITS | REQ, IFT · FI   | AOR, AEC · AOR/ABV |

통일하려는 리팩터가 들어오면 여기서 막힌다.
"""
from __future__ import annotations

import pytest

# ─── SUTS ────────────────────────────────────────────────────────────────────

def test_suts_columns_match_reference_layout():
    from generators.suts import (
        _COL_GEN,
        _COL_INDEX,
        _COL_METHOD,
        _COL_SAFETY,
        _COL_TC_ID,
        _COL_UNIT,
        _FIXED_HEADERS,
        _INPUT_COL_END,
        _INPUT_COL_START,
        _OUTPUT_COL_END,
        _OUTPUT_COL_START,
        _RELATED_COL,
        _SEQ_COL,
    )
    # 정본 실측: B=Index C=TC_ID D=Unit E=Safety Related F=Test Method
    #            G=TC Generation Method H=(공백) I~CZ=Inpt DA~GF=ExpR GG=SUDS
    assert (_COL_INDEX, _COL_TC_ID, _COL_UNIT, _COL_SAFETY, _COL_METHOD, _COL_GEN, _SEQ_COL) \
        == (2, 3, 4, 5, 6, 7, 8)
    assert (_INPUT_COL_START, _INPUT_COL_END) == (9, 104)      # I .. CZ  (Inpt[0..95])
    assert (_OUTPUT_COL_START, _OUTPUT_COL_END) == (105, 188)  # DA .. GF (ExpR[0..83])
    assert _RELATED_COL == 189                                  # GG
    assert _FIXED_HEADERS[_COL_INDEX] == "Index"
    assert _FIXED_HEADERS[_COL_SAFETY] == "Safety Related"
    # ⚠ SwTS 정본의 열이 SUTS 로 새어 들어오면 안 된다.
    labels = set(_FIXED_HEADERS.values())
    for leaked in ("Description", "Test Environment", "Precondition", "Sequence"):
        assert leaked not in labels, f"{leaked} 는 SwTS 정본의 열이다"


def test_suts_vocabulary_is_from_its_own_introduction():
    """SwUTS Introduction 1.5 는 REQ/IFT/FI 다 — STS 어휘(FIT/FNCT/RVW)를 쓰면 안 된다."""
    from generators.suts import (
        _GEN_BOUNDARY,
        _GEN_EQUIV,
        _METHOD_FI,
        _METHOD_REQ,
        resolve_seq_test_method,
    )
    assert (_METHOD_REQ, _METHOD_FI) == ("REQ", "FI")
    # 결합자는 슬래시 — SwITS 의 쉼표와 다르다. 통일 금지.
    assert (_GEN_BOUNDARY, _GEN_EQUIV) == ("AOR/ABV", "AOR/AEC")
    assert resolve_seq_test_method("BV_MID") == "REQ"
    assert resolve_seq_test_method("BV_MAX_INV") == "FI"   # 유효 범위 밖 = 고장 주입


# ─── STS ─────────────────────────────────────────────────────────────────────

def test_sts_sheet_name_is_not_the_integration_one():
    from generators.sts import _SPEC_SHEET_NAME, _STS_SHEET_CANDIDATES
    assert _SPEC_SHEET_NAME == "3.SW Test Spec"
    # 읽는 쪽이 writer 와 같은 상수를 봐야 한다(예전엔 문자열이 박혀 갈라졌다).
    assert _STS_SHEET_CANDIDATES[0] == _SPEC_SHEET_NAME


def test_sts_vocabulary_matches_its_introduction():
    from generators.sts import (
        _DEFAULT_GEN_METHOD_STS,
        _DEFAULT_TEST_METHOD,
        _GEN_METHODS,
        _TEST_METHODS,
        _to_sts_vocab,
    )
    assert _TEST_METHODS == {"RBT", "FIT"}
    assert _GEN_METHODS == {"AOR", "ECA", "BAA"}
    assert (_DEFAULT_TEST_METHOD, _DEFAULT_GEN_METHOD_STS) == ("RBT", "AOR")
    # 휴리스틱이 내던 어휘 밖 라벨은 전부 정본 어휘로 좁혀진다.
    for raw_m, raw_g in (("FNCT", "STA"), ("RVW", "ADF"), ("ELCT", "AFD"), ("FIT", "ERG")):
        m, g = _to_sts_vocab(raw_m, raw_g)
        assert m in _TEST_METHODS and g in _GEN_METHODS, f"{raw_m}/{raw_g} → {m}/{g}"
    # SwUTS 약어는 SwTS 약어로 옮겨진다(같은 개념, 다른 표기).
    assert _to_sts_vocab("RBT", "AEC")[1] == "ECA"
    assert _to_sts_vocab("RBT", "ABV")[1] == "BAA"


# ─── SITS ────────────────────────────────────────────────────────────────────

def test_sits_columns_match_reference_layout():
    from generators.sits import (
        _CHAIN_COL,
        _DESC_COL,
        _DETAIL_HEADERS,
        _EXP_COL_END,
        _EXP_COL_START,
        _GEN_COL,
        _INPUT_COL_END,
        _INPUT_COL_START,
        _METHOD_COL,
        _RELATED_COL,
        _SAFETY_COL,
        _SEQ_COL,
        _TCID_COL,
    )
    assert (_TCID_COL, _DESC_COL, _CHAIN_COL, _SAFETY_COL, _METHOD_COL, _GEN_COL, _SEQ_COL) \
        == (2, 3, 4, 5, 6, 7, 8)
    assert (_INPUT_COL_START, _INPUT_COL_END) == (9, 90)      # I .. CL
    assert (_EXP_COL_START, _EXP_COL_END) == (91, 203)        # CM .. GU
    assert _RELATED_COL == 204                                 # GV
    assert _DETAIL_HEADERS[_RELATED_COL] == "SwDS"             # SUTS 는 'SUDS' — 다르다
    assert "Precondition" not in set(_DETAIL_HEADERS.values())


def test_sits_vocabulary_uses_comma_not_slash():
    """SwITS 정본은 쉼표 결합(`AOR, AEC`)이다. SwUTS 는 슬래시 — 통일하면 둘 다 틀린다."""
    from generators.sits import (
        _SITS_GEN_BOUNDARY,
        _SITS_GEN_DEFAULT,
        _SITS_METHOD_DEFAULT,
        _SITS_METHOD_FAULT,
        _sits_gen_method,
        _sits_test_method,
    )
    assert (_SITS_METHOD_DEFAULT, _SITS_METHOD_FAULT) == ("REQ, IFT", "FI")
    assert (_SITS_GEN_DEFAULT, _SITS_GEN_BOUNDARY) == ("AOR, AEC", "AOR/ABV")
    assert _sits_gen_method("AEC") == "AOR, AEC"
    assert _sits_gen_method("ABV") == "AOR/ABV"
    assert _sits_test_method({"sub_cases": [{"strategy": "BV_MIN"}]}) == "REQ, IFT"
    assert _sits_test_method({"sub_cases": [{"strategy": "ERR_PROP"}]}) == "FI"


# ─── 세 문서 공통: Safety Related 표기 ───────────────────────────────────────

@pytest.mark.parametrize("module_name", ["generators.suts", "generators.sts", "generators.sits"])
def test_safety_related_is_o_for_safety_and_never_invented(module_name):
    """`O`=안전 관련 · `X`=비안전 · 빈칸=근거 없음.

    ⚠ 예전 판은 세 문서 중 둘이 `"X" if is_safety else ""` 라 **의미가 정반대**였다.
      ASIL 을 가진 TC 가 문서상 "비안전"으로 읽혔다.
    ⚠ 근거 부재를 `X` 로 단정하지 않는다 — under-classification 이다.
    """
    import importlib
    mod = importlib.import_module(module_name)
    fn = getattr(mod, "resolve_safety_related", None) or getattr(mod, "_safety_mark")
    assert fn("A") == "O" and fn("D") == "O" and fn("ASIL-B") == "O"
    assert fn("QM") == "X"
    assert fn("") == "" and fn("TBD") == "" and fn(None) == ""
