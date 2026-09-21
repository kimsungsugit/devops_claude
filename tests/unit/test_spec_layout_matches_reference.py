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
    """시험 이름 그대로 — 생성기가 내는 코드는 **문서 1.5 범례 안**에 있어야 한다.

    ⚠ 예전 판은 이름만 그렇고 `_TEST_METHODS == {"RBT","FIT"}` 만 단언했다. 그래서
      범례가 설명하는 `RVW`(코드 리뷰)를 생성기가 한 번도 안 쓰는 상태 — 리뷰 전용 TC 에
      `RBT`(요구 기반 **시험**)를 적던 상태 — 를 아무것도 잡지 못했다.
    """
    from generators.sts import (
        _DEFAULT_GEN_METHOD_STS,
        _DEFAULT_TEST_METHOD,
        _GEN_METHODS,
        _INTRO_TEST_METHODS,
        _TEST_METHODS,
        _classify_steps,
    )
    _legend = {c for c, _d in _INTRO_TEST_METHODS}
    assert _TEST_METHODS == {"RBT", "FIT", "RVW"}
    assert _GEN_METHODS == {"AOR", "ECA", "BAA"}
    assert (_DEFAULT_TEST_METHOD, _DEFAULT_GEN_METHOD_STS) == ("RBT", "AOR")
    # ① 칸에 적는 코드는 전부 문서가 설명하는 코드다(반대 방향은 허용 — 표는 표준 어휘).
    assert _TEST_METHODS <= _legend, sorted(_TEST_METHODS - _legend)
    # 분류기(R67 — 라벨은 스텝에서 읽는다)가 내는 값은 전부 정본 어휘 안이다.
    for steps in (
        [],
        [{"action": "f() 호출", "expected": "ok"}],
        [{"action": "입력 설정 (경계 최댓값): a=255", "expected": "ok"}],
        [{"action": "입력 설정 (유효 범위 초과): a=256", "expected": "ok"}],
        [{"action": "조건 충족 설정: ( a > 0 )", "expected": "조건 분기 → True 경로 진입"}],
        [{"action": "에러 조건 설정: ( p == NULL )", "expected": "에러 처리 경로 진입"}],
        [{"action": "소스 코드에서 해당 요구사항 구현부 확인", "expected": "ok"}],
    ):
        m, g, _ = _classify_steps(steps)
        assert m in _TEST_METHODS and g in _GEN_METHODS, f"{steps} → {m}/{g}"


def test_review_only_tc_is_labelled_review_not_a_test():
    """리뷰 전용 TC 의 검증방법은 `RVW` — `RBT`/`FIT` 는 "실행했다" 는 뜻이다.

    정본(HDPDM01_STS v1.02, 59 TC)도 이 자리에 RVW 를 5건 쓴다. 문서 자신의 1.5 범례가
    `RVW = Review - 코드 리뷰` 라 적고, 커버리지 경고문도 "코드 리뷰(RVW)로만 덮였다"
    라고 말한다 — 칸만 `RBT` 였다(2026-08-11 ~ 09-21).
    """
    from generators.sts import _REVIEW_ONLY_METHODS, _classify_steps, _generate_review_steps

    for tc in _generate_review_steps({"id": "SwRS_01", "description": "요구 본문",
                                      "verification": "1) 코드 검토"}):
        method, _gen, review = _classify_steps(tc)
        assert review is True
        assert method == "RVW", tc
        # 두 축(라벨 / 플래그)이 같은 답을 낸다 — 커버리지는 이 둘을 AND 로 읽는다.
        assert method.upper() in _REVIEW_ONLY_METHODS

    # 대조군 — 고장 주입 스텝이 섞여도 리뷰가 이긴다(리뷰엔 실행 산출물이 없다).
    mixed = [{"action": "소스 코드에서 해당 요구사항 구현부 확인", "expected": "ok"},
             {"action": "에러 조건 설정: ( p == NULL )", "expected": "에러 처리 경로 진입"}]
    assert _classify_steps(mixed)[0] == "RVW"
    # 음성 대조군 — 리뷰 스텝이 없으면 종전 그대로다(뮤테이션 가드).
    assert _classify_steps(mixed[1:])[0] == "FIT"
    assert _classify_steps([{"action": "f() 호출", "expected": "ok"}])[0] == "RBT"


def test_template_path_warns_when_a_code_is_outside_the_template_legend(caplog):
    """템플릿 갈래는 범례를 **안 만든다** — 칸에 범례 밖 코드를 쓰면 경고한다.

    두 SwTS 정본의 1.5 범례가 반대라(① RBT·FIT / ② FNCT·FIT·ELCT·RVW) 어느 템플릿을
    받느냐에 따라 같은 산출물이 대조 가능하기도 불가능하기도 하다. 실측으로 둘 다
    걸린다 — ① 템플릿엔 `RVW` 가, ② 템플릿엔 `RBT` 가 범례에 없다.

    모듈 상수끼리 보는 `test_sts_vocabulary_matches_its_introduction` 은 이 경로를
    구조적으로 못 본다(템플릿은 런타임 입력이다).
    """
    import logging

    from openpyxl import Workbook

    from generators.sts import _warn_template_legend_gap

    def _wb(codes):
        wb = Workbook()
        ws = wb.active
        ws.title = "1.Introduction"
        ws["A6"] = "1.5 Test Method"
        for i, c in enumerate(codes):
            ws.cell(row=8 + i, column=1, value=c)
            ws.cell(row=8 + i, column=2, value="설명")
        return wb

    tcs = [{"test_method": "RBT"}, {"test_method": "RVW"}, {"test_method": "FIT"}]

    # ① KJPDS02 관례 — RVW 가 범례에 없다
    with caplog.at_level(logging.WARNING, logger="generators.sts"):
        caplog.clear()
        _warn_template_legend_gap(_wb(["RBT", "FIT"]), tcs)
    assert "RVW" in caplog.text and "범례에 없는" in caplog.text

    # ② HDPDM01 관례 — 이번엔 RBT 가 범례에 없다(반대 방향도 잡는다)
    with caplog.at_level(logging.WARNING, logger="generators.sts"):
        caplog.clear()
        _warn_template_legend_gap(_wb(["FNCT", "FIT", "ELCT", "RVW"]), tcs)
    assert "RBT" in caplog.text

    # 음성 대조군 — 전부 범례 안이면 조용하다(늑대소년 금지)
    with caplog.at_level(logging.WARNING, logger="generators.sts"):
        caplog.clear()
        _warn_template_legend_gap(_wb(["RBT", "FIT", "RVW"]), tcs)
    assert "범례에 없는" not in caplog.text

    # 범례를 못 읽었으면(시트 부재) 조용하다 — 0 을 "위반 없음" 으로 꾸미지 않는다
    with caplog.at_level(logging.WARNING, logger="generators.sts"):
        caplog.clear()
        _warn_template_legend_gap(Workbook(), tcs)
    assert "범례에 없는" not in caplog.text


def test_both_sts_references_are_recorded_with_their_identity():
    """SwTS 정본이 **둘**이라는 사실이 어휘 옆에 남아 있어야 한다.

    ⚠ 이 시험의 첫 판(R79 초안)은 `"102건 전부 …"` 를 **금지 문자열**로 잡았다. 그건
      틀렸다 — 102 는 실재하는 정본 ①(`HKY-[KJPDS02]-SwTS-28A4` v1.02 Approved,
      TC 102 · Test Method RBT 102 · Gen AOR 102)의 참값이다. 내가 그 문서를 못 찾고
      "정본은 HDPDM01 하나뿐" 이라고 단정하는 바람에 **참인 측정치를 영구 금지**할
      뻔했다 (`[[feedback_two_reference_docs_disagree]]`: 정본 수부터 세라).

    그래서 이 시험은 금지가 아니라 **보존**을 잰다: 두 정본의 식별자와 분포가 둘 다
    적혀 있고, 생성 문서에 인쇄되는 문장도 둘 다 말하는가.

    ⚠ 이 시험은 **행동을 재지 않는다**(소스 텍스트 검사다). 라벨 동작은
    `test_review_only_tc_is_labelled_review_not_a_test` 와
    `test_sts_vocabulary_matches_its_introduction` 이 잰다.
    """
    from pathlib import Path

    src = Path("generators/sts.py").read_text(encoding="utf-8")
    # ① KJPDS02 — 파일 식별자 + 실측
    for token in ("02d67baeadbd39d0", "KJPDS02", "TC 102", "RBT 102", "AOR 102"):
        assert token in src, "정본 ①의 기록이 사라졌다: " + token
    # ② HDPDM01 — 파일 식별자 + 실측
    for token in ("359de4ef4cf9e68d", "HDPDM01", "TC 59", "FNCT 28", "RVW 5"):
        assert token in src, "정본 ②의 기록이 사라졌다: " + token
    # 관례가 **반대**라는 사실과 두 어휘의 대응이 같이 남아 있다.
    assert "관례가 반대" in src
    assert "ECA" in src and "AEC" in src
    # 생성 문서에 인쇄되는 문장도 두 정본을 말한다(주석만 고치고 산출물을 두면 안 된다).
    assert "SwTS 정본은 **둘이고 표기 관례가 반대다**" in src


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
    # ⚠ 예전 판은 "서브케이스에 ERR 이 있으면 TC 전체가 FI" 였고 이 테스트가 그걸
    #   고정하고 있었다. 정본은 FI 를 **전용 TC** 로만 쓴다 — 실측 54건에서
    #   `REQ, IFT`↔`AOR, AEC` 49 · `FI`↔`AOR/ABV` 5, 다른 조합 **0건**이다.
    #   즉 무효 경계 서브케이스를 가진 TC 를 FI 로 올리지 않는다.
    #   게다가 옛 판정은 **살아 있는 지뢰**였다: 오류전파 서브케이스가
    #   `max_subcases=7` 에서만 예산에 막혀 안 생겼고, 기본값 14 로 부르면
    #   **전 TC 가 FI 로 뒤집혔다**(영향도 재생성 경로가 그랬다).
    #   → Test Method 는 TC 생성 시점에 확정한다(`generate_itc_list`).
    assert _sits_test_method({"test_method": _SITS_METHOD_DEFAULT}) == "REQ, IFT"
    assert _sits_test_method({"test_method": _SITS_METHOD_FAULT}) == "FI"
    assert _sits_test_method({"sub_cases": [{"strategy": "ERR_PROP"}]}) == "REQ, IFT"


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


# ─── 커버리지 분모 정직성 ────────────────────────────────────────────────────

def test_function_coverage_denominator_is_not_self():
    """분모를 TC 수로 떨어뜨리면 **언제나 100%** 가 된다.

    실측(KJPDS02_PV, 2026-08-11): 저장소 `docs/uds_function_swcom_override.json`
    251개로 함수 목록이 잘린 뒤 251/251 = "함수 커버리지 100.0%" 로 보고됐다.
    정본 SwUTS 는 1,014 함수 — **77.8% 를 버리고 완전 커버라고 말한 것**이다.
    """
    from generators.suts import generate_suts_quality_report

    units = [{"fid": "f1", "name": "a", "input_vars": ["x"], "output_vars": [], "component": "C"}]
    seqs = {"f1": [{"seq_num": 1, "inputs": {"x": 1}, "expected": {}}]}

    got = generate_suts_quality_report(units, seqs, 100)
    assert got["function_coverage_pct"] == 1.0, "1/100 은 1% 다 — 자기 자신을 분모로 쓰면 100%"

    # 소스 함수 수를 모르면 **미측정**이다. 0% 도 100% 도 아니다.
    unmeasured = generate_suts_quality_report(units, seqs, 0)
    assert unmeasured["function_coverage_pct"] is None


def test_unmeasured_coverage_is_not_drawn_as_zero():
    """미측정을 `0%` 로 내면 "한 함수도 안 덮였다" 로 읽힌다 — 지표를 아예 내지 않는다."""
    from generators.suts import generate_suts_quality_report
    from workflow.quality.evaluator import evaluate_suts

    units = [{"fid": "f1", "name": "a", "input_vars": ["x"], "output_vars": [], "component": "C"}]
    seqs = {"f1": [{"seq_num": 1, "inputs": {"x": 1}, "expected": {}}]}

    measured = evaluate_suts(generate_suts_quality_report(units, seqs, 100))
    unmeasured = evaluate_suts(generate_suts_quality_report(units, seqs, 0))
    assert len(unmeasured) == len(measured) - 1, "미측정일 때 커버리지 지표가 빠져야 한다"


def test_override_map_is_not_used_as_a_filter():
    """`docs/uds_function_swcom_override.json` 은 **보강용**이다.

    ⚠ 예전엔 이 목록에 없는 함수를 전부 버렸다. 저장소 파일이라 프로젝트가 바뀌어도
      같은 251개로 자른다 — 정본 1,014 중 782개(77.8%)가 침묵 탈락했다.
    구조 검사다: 필터 컴프리헨션이 되살아나면 깨진다.
    """
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "generators" / "suts.py"
    tree = ast.parse(src.read_text(encoding="utf-8", errors="ignore"))

    # `function_details = {… _ovr_names …}` — override 목록으로 좁히는 **재대입**이
    # 결함의 실체다. 문자열 비교는 들여쓰기 한 칸에도 깨지므로 AST 로 본다.
    #
    # ⚠ 호출자가 준 `target_function_names`(→ `target_name_set`) 로 좁히는 것은
    #   **정당한 필터**다("이 함수들만 만들어 달라"는 명시적 요청). 그건 잡지 않는다.
    def _mentions_override(node: ast.AST) -> bool:
        return any(
            isinstance(n, ast.Name) and n.id in ("_ovr_names", "_ovr_names_lower")
            for n in ast.walk(node)
        )

    narrowing = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "function_details" for t in node.targets)
        and isinstance(node.value, ast.DictComp)
        and _mentions_override(node.value)
    ]
    assert not narrowing, (
        "override 목록으로 function_details 를 좁히고 있다 — "
        f"line {[n.lineno for n in narrowing]}. override 는 보강용이지 필터가 아니다."
    )

    # 보충 기능 자체는 남아 있어야 한다(필터를 걷어내며 같이 지우면 안 된다).
    # (R70) 보충은 `supplement_override_only` 로 뽑혀 생성기와 준비 게이트가 같이 부른다 — 생성기 본체의 호출이 앵커다.
    body = src.read_text(encoding="utf-8", errors="ignore")
    assert "uds_function_swcom_override.json" in body
    gen_body = body[body.index("def generate_suts("):]
    assert "supplement_override_only(function_details)" in gen_body


def test_suts_validators_count_the_real_rows(tmp_path):
    """검증기가 **정상 산출물을 결함으로 신고**하지 않는지.

    라이브 실측(2026-08-11): 시퀀스 7,267건이 파일에 멀쩡히 있는데 검증기는
    1,576건으로 셌다(-5,691). 원인 둘:
      · `validate_suts_xlsm` 이 `min_row=7`·`max_col=149`·`row[12]` 로 **옛 레이아웃**을
        하드코딩 — 정본 레이아웃(데이터 5행 시작, Seq.No=H)과 어긋났다
      · `validate_suts_output` 이 `read_only=True` 에서 **랜덤 `.cell()`** 사용 —
        순차 스트리밍이라 되짚으면 빈 셀을 돌려준다
    행이 1,975 → 8,219 로 늘자 드러났다. 그대로 뒀으면 매 생성마다 오탐이다.
    """
    openpyxl = pytest.importorskip("openpyxl")
    from generators.suts import (
        generate_suts_xlsm,
        validate_suts_output,
        validate_suts_xlsm,
    )

    n_units, n_seq = 40, 12   # 480 시퀀스 — 헤더 오프셋이 틀리면 수치가 어긋난다
    units = [
        {"fid": f"SwUFn_{i:04d}", "name": f"fn_{i}", "component": "SwCom_01",
         "input_vars": ["a"], "output_vars": ["b"], "asil": "A"}
        for i in range(n_units)
    ]
    seqs = {
        u["fid"]: [{"seq_num": k + 1, "strategy": "BV_MID",
                    "inputs": {"a": k}, "expected": {"b": k}} for k in range(n_seq)]
        for u in units
    }
    out = str(tmp_path / "v.xlsx")
    generate_suts_xlsm(None, units, seqs, out, {"project_id": "T"})

    wb = openpyxl.load_workbook(out, read_only=True, data_only=True)
    try:
        assert wb["2.SW Unit Test Spec"].max_row == 4 + n_units * (1 + n_seq)  # 밴드3+헤더4
    finally:
        wb.close()   # ⚠ read_only 워크북은 닫아야 Windows 에서 파일 핸들이 풀린다

    for label, fn in (("xlsm", lambda q: validate_suts_xlsm(q)["stats"]),
                      ("output", validate_suts_output)):
        st = fn(out)
        assert st["tc_count"] == n_units, f"{label}: TC {st['tc_count']} != {n_units}"
        assert st["seq_count"] == n_units * n_seq, \
            f"{label}: seq {st['seq_count']} != {n_units * n_seq}"


def test_suts_validator_does_not_let_the_average_hide_empty_inputs(tmp_path):
    """⚠ 평균이 0 을 숨긴다.

    라이브 실측(2026-08-12): 948 TC 중 **338 건이 입력 0개**인데 `avg_inp` 는 2.3 이라
    `avg_inp < 1` 게이트를 그대로 통과했고 `valid: True · issues: []` 였다. 입력이 없는
    시퀀스는 넣을 값이 없어 시험이 성립하지 않으므로 **건수를 따로** 센다.

    ⚠ `issues` 가 아니라 `warnings` 다 — 입력 0개는 정상일 수도 있어(파라미터도 전역도
      없는 함수. 정본도 1,005 중 172 건) `valid` 를 뒤집으면 정상 산출물이 실패로 신고된다.
    """
    pytest.importorskip("openpyxl")
    from generators.suts import generate_suts_xlsm, validate_suts_output

    units = [
        {"fid": f"SwUFn_{i:04d}", "name": f"fn_{i}", "component": "SwCom_01",
         # 4개 중 1개만 입력이 비어 있다 → 평균은 넉넉히 1 을 넘는다
         "input_vars": [] if i == 0 else ["a", "b", "c"],
         "output_vars": ["b"], "asil": "A"}
        for i in range(4)
    ]
    seqs = {u["fid"]: [{"seq_num": 1, "strategy": "BV_MID",
                        "inputs": {"a": 1}, "expected": {"b": 1}}] for u in units}
    out = str(tmp_path / "avg.xlsx")
    generate_suts_xlsm(None, units, seqs, out, {"project_id": "T"})

    st = validate_suts_output(out)
    assert st["avg_inp"] >= 1, "이 표본은 평균 게이트를 통과해야 의미가 있다"
    assert st["issues"] == [], "평균 게이트는 여전히 통과한다"
    assert st["tc_without_input"] == 1, "건수를 안 세면 338건이 평균 뒤에 숨는다"
    assert any("입력" in w for w in st["warnings"]), "숨기지 않고 경고로 낸다"
    assert st["valid"] is True, "정상일 수 있는 축으로 valid 를 뒤집지 않는다"
