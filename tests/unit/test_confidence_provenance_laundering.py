"""신뢰도 리포트가 **자기 산출물을 되읽어 출처를 만들어내면** 안 된다.

## 회귀 대상 (2026-07-31 실측)

`generate_asil_related_confidence_report` 는 `generated_docx_path` — 즉 **이 파이프라인이
방금 쓴 UDS DOCX** — 를 되읽어 payload 의 빈 필드를 채운다. 값을 채우는 것 자체는 유용하다.
문제는 **출처 라벨**이었다: 값의 실제 유래가 아니라 **문자열 모양**만 보고

    asil 이 placeholder 가 아니다        → `sds`   (0.95)
    related 가 `SwFn_\\d+` 모양이다       → `srs`   (0.95)
    related 가 `SwCom_\\d+` 모양이다      → `rule`  (0.75)
    그 외                                → `reference` (0.90)

를 붙였다. `SwFn_07` 이라는 **문자열 모양**은 "SRS 를 참조했다"는 증거가 아니다.

실측 — 같은 payload(진짜 유래 `default`/`inference`)에 생성 DOCX 만 물렸을 때:

    항목                    DOCX 미지정      DOCX 되읽음
    ---------------------  --------------   --------------
    ASIL 출처              기본값(근거 없음)  SDS
    Related 출처           추론              SRS
    점수 / 등급            0.500 / D        0.933 / B
    저신뢰 목록            1건 노출          **none**
    "정본 문서 근거"        0 / 1 (0%)       **1 / 1 (100%)**
    증거 문장              (없음)            "SDS 매핑 규칙에 의해 보강됨"

마지막 두 줄이 특히 나쁘다. 이 리포트의 **용도 자체가** "어느 필드가 근거가 약한가" 인데,
세탁된 행은 조치 대상 목록에서 사라지고 없는 증거 문장까지 붙는다.

수정: 생성 문서에서 회수한 값은 전부 `generated_doc`(0.30, "생성 문서 회수(원 유래 불명)").
모양 기반 분류는 제거. 값을 실제로 가져오지 않았으면 출처도 바꾸지 않는다.
"""
from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

MODULE = Path(__file__).resolve().parents[2] / "report_gen" / "validation.py"

# 생성 DOCX 가 담고 있는 값. 유래는 오직 "우리 출력물" 이다.
DOC_ROW = {
    "id": "SwUFn_07",
    "name": "Ecu_HandleFault",
    "description": "Handles the ECU fault state transition.",
    "asil": "D",
    "related": "SwFn_07",
}

# payload 의 진짜 유래는 약하다: 값 없음 + default/inference.
WEAK_PAYLOAD = {
    "function_details_by_name": {
        "ecu_handlefault": {
            "id": "SwUFn_07",
            "name": "Ecu_HandleFault",
            "description": "",
            "description_source": "inference",
            "asil": "",
            "asil_source": "default",
            "related": "",
            "related_source": "inference",
        }
    }
}


_WEAK_PAYLOAD_SNAPSHOT = copy.deepcopy(WEAK_PAYLOAD)


@pytest.fixture(autouse=True)
def _weak_payload_must_stay_pristine():
    """모듈 전역 픽스처가 테스트 사이에 변형되면 **순서 의존**이 생긴다.

    이 파일의 테스트 12곳이 `WEAK_PAYLOAD` 를 복사 없이 리포트에 넘긴다. 리포트가
    입력을 제자리 변경하던 시절엔 첫 테스트가 그걸 오염시켰고, 뒤 테스트는 오염된
    상태를 보면서도 통과했다(= 결함이 자기 탐지를 가림). 리포트가 더 이상 입력을
    변경하지 않으므로 이 가드는 그 회귀를 즉시 드러낸다.
    """
    yield
    assert WEAK_PAYLOAD == _WEAK_PAYLOAD_SNAPSHOT, (
        "모듈 전역 WEAK_PAYLOAD 가 테스트 중에 변형됐다 — 뒤 테스트가 순서에 의존하게 된다"
    )


class _FakeDoc:
    """`docx.Document()` 반환 스텁 — 실제 파싱은 추출기 스텁이 대신한다."""


@pytest.fixture
def report(tmp_path, monkeypatch):
    """리포트를 생성해 본문을 돌려준다.

    `doc_row=None` 이면 `generated_docx_path` 를 넘기지 않는다(= 대조군).
    """

    def _run(payload, doc_row=DOC_ROW, name="conf"):
        from report_gen.validation import generate_asil_related_confidence_report

        out = tmp_path / f"{name}.md"
        if doc_row is None:
            generate_asil_related_confidence_report(payload, str(out))
            return out.read_text(encoding="utf-8")

        fake_docx = tmp_path / f"{name}.docx"
        fake_docx.write_bytes(b"stub")
        monkeypatch.setattr("docx.Document", lambda *_a, **_k: _FakeDoc())
        monkeypatch.setattr(
            "report_gen.validation._extract_function_info_from_docx",
            lambda _doc: {doc_row["id"]: dict(doc_row)},
        )
        generate_asil_related_confidence_report(payload, str(out), str(fake_docx))
        return out.read_text(encoding="utf-8")

    return _run


def _score(text: str) -> float:
    for line in text.splitlines():
        if "Overall confidence score" in line:
            return float(line.split("`")[1])
    raise AssertionError("점수 줄을 찾지 못했다")


def _section(text: str, title: str) -> list[str]:
    out, hit = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            hit = line[3:].strip() == title
            continue
        if hit and line.strip():
            out.append(line.strip())
    return out


# ---------------------------------------------------------------------------
# 핵심 — 자기 산출물 되읽기가 점수를 올리면 안 된다
# ---------------------------------------------------------------------------

class TestSelfReadDoesNotInflate:
    def test_score_does_not_exceed_control(self, report):
        """대조군(DOCX 미지정)보다 높아지면 그 차이는 전부 세탁분이다."""
        control = _score(report(WEAK_PAYLOAD, doc_row=None, name="ctl"))
        laundered = _score(report(WEAK_PAYLOAD, name="doc"))
        assert laundered <= control, (
            f"자기 산출물을 되읽었다는 이유만으로 {control:.3f} → {laundered:.3f} 로 올랐다"
        )

    def test_grade_does_not_improve(self, report):
        control = report(WEAK_PAYLOAD, doc_row=None, name="ctl")
        laundered = report(WEAK_PAYLOAD, name="doc")
        assert "grade: `B`" not in laundered and "grade: `A`" not in laundered
        assert "grade: `D`" in control

    @pytest.mark.parametrize("section", ["ASIL Source", "Related ID Source", "Description Source"])
    def test_no_canonical_label_invented(self, report, section):
        """SDS / SRS / 레퍼런스 / 룰 — 어느 것도 자기 문서 회수에 붙어선 안 된다."""
        lines = _section(report(WEAK_PAYLOAD, name="doc"), section)
        joined = " ".join(lines)
        for forbidden in ("SDS", "SRS", "레퍼런스", "룰"):
            assert f"- {forbidden}:" not in joined, f"{section} 에 '{forbidden}' 이 날조됐다: {joined}"

    def test_labeled_as_generated_doc(self, report):
        lines = " ".join(_section(report(WEAK_PAYLOAD, name="doc"), "ASIL Source"))
        assert "생성 문서 회수" in lines, lines


# ---------------------------------------------------------------------------
# 모양 기반 출처 날조
# ---------------------------------------------------------------------------

class TestIdShapeIsNotEvidence:
    @pytest.mark.parametrize(
        ("related", "forbidden"),
        [("SwFn_07", "SRS"), ("SwTR_0608", "SRS"), ("SwCom_03", "룰"), ("무언가 다른 값", "레퍼런스")],
    )
    def test_shape_does_not_choose_source(self, report, related, forbidden):
        row = dict(DOC_ROW, related=related)
        lines = " ".join(_section(report(WEAK_PAYLOAD, doc_row=row, name="s"), "Related ID Source"))
        assert f"- {forbidden}:" not in lines, (
            f"related='{related}' 의 문자열 모양만 보고 '{forbidden}' 출처를 지어냈다: {lines}"
        )


# ---------------------------------------------------------------------------
# 리포트의 용도 자체가 무너지던 두 표면
# ---------------------------------------------------------------------------

class TestActionableSurfacesSurvive:
    def test_stays_in_low_confidence_list(self, report):
        """세탁되면 조치 대상 목록에서 사라진다 — 이 리포트의 존재 이유가 사라진다."""
        lines = _section(report(WEAK_PAYLOAD, name="doc"), "Low Confidence Samples")
        assert lines and lines != ["- none"], "저신뢰 목록이 비었다 — 회수 행이 조치 대상에서 빠졌다"
        assert "ecu_handlefault" in " ".join(lines)

    def test_excluded_from_canonical_doc_count(self, report):
        text = report(WEAK_PAYLOAD, name="doc")
        line = next(ln for ln in text.splitlines() if "Related canonical(doc-backed)" in ln)
        assert "(0.0%)" in line, f"자기 문서 회수가 '정본 문서 근거' 로 집계됐다: {line.strip()}"

    def test_no_fabricated_sds_evidence_sentence(self, report):
        text = report(WEAK_PAYLOAD, name="doc")
        assert "SDS 매핑 규칙에 의해 보강됨" not in text
        assert "SRS 요구사항 ID/ASIL 추출 규칙에 의해 보강됨" not in text

    def test_evidence_sentence_states_unknown_origin(self, report):
        text = report(WEAK_PAYLOAD, name="doc")
        assert "원 유래 미확인" in text, "회수 사실을 증거 문장이 밝히지 않는다"


# ---------------------------------------------------------------------------
# 분기 1 — payload 가 아예 비었을 때의 전면 재구축
# ---------------------------------------------------------------------------

class TestFullRebuildBranch:
    def test_rebuild_is_also_labeled_generated_doc(self, report):
        text = report({}, name="rb")
        assert "- Total functions: `1`" in text, "재구축 분기가 발동하지 않았다(측정 전제 붕괴)"
        for section in ("ASIL Source", "Related ID Source", "Description Source"):
            assert "생성 문서 회수" in " ".join(_section(text, section)), section

    def test_rebuild_score_is_not_high(self, report):
        assert _score(report({}, name="rb")) <= 0.60


# ---------------------------------------------------------------------------
# 값을 안 가져왔으면 출처도 안 바꾼다
# ---------------------------------------------------------------------------

class TestSourceUnchangedWhenValueKept:
    def test_description_source_kept_when_payload_text_survives(self, report):
        """예전엔 값을 그대로 두고 `description_source` 만 `reference` 로 올렸다."""
        payload = {
            "function_details_by_name": {
                "ecu_handlefault": {
                    "id": "SwUFn_07",
                    "name": "Ecu_HandleFault",
                    # 구체적인 문장이라 _is_generic_description 에 걸리지 않는다 → 값 유지
                    "description": "Latches the fault flag and reports it to the diagnostic manager.",
                    "description_source": "inference",
                    "asil": "D",
                    "asil_source": "comment",
                    "related": "SwFn_07",
                    "related_source": "comment",
                }
            }
        }
        lines = " ".join(_section(report(payload, name="keep"), "Description Source"))
        assert "- 추론:" in lines, f"값을 안 바꿨는데 출처가 승격됐다: {lines}"


# ---------------------------------------------------------------------------
# 음성 대조군 — 정당한 강한 출처는 보존돼야 한다
# ---------------------------------------------------------------------------

class TestLegitimateSourcePreserved:
    def test_payload_sds_survives_docx_merge(self, report):
        payload = {
            "function_details_by_name": {
                "ecu_handlefault": {
                    "id": "SwUFn_07",
                    "name": "Ecu_HandleFault",
                    "description": "Handles the ECU fault state transition in the safety monitor.",
                    "description_source": "sds",
                    "asil": "A",
                    "asil_source": "sds",
                    "related": "SwTR_0608",
                    "related_source": "sds",
                }
            }
        }
        text = report(payload, name="legit")
        assert "- SDS: `1` / `1` (100.0%)" in text, "정당한 SDS 출처가 회수 라벨에 덮였다"
        assert _score(text) >= 0.95


# ---------------------------------------------------------------------------
# 어휘 계약
# ---------------------------------------------------------------------------

class TestVocabulary:
    def test_generated_doc_is_a_known_source(self, report):
        text = report(WEAK_PAYLOAD, name="voc")
        assert "분류 불가 출처값" not in text, "generated_doc 이 미지값으로 접힌다"

    def test_generated_doc_scores_no_higher_than_inference(self):
        """자기 문서 회수가 추론보다 높으면 되읽기가 이득이 된다 — 그러면 안 된다."""
        import report_gen.validation as V

        src = MODULE.read_text(encoding="utf-8")
        tree = ast.parse(src)
        scores = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant)]
            # ⚠ `src_labels` 도 같은 키를 갖는다(문자열 값). 값이 **수치**인 표만 잡는다 —
            #   조이지 않으면 라벨 표를 먼저 집어 KeyError 로 죽는다(이 테스트가 실제로 겪었다).
            numeric = all(
                isinstance(v, ast.Constant) and isinstance(v.value, (int, float))
                for v in node.values
            )
            if numeric and {"inference", "generated_doc", "comment"} <= set(keys):
                scores = {
                    str(k.value): float(v.value)
                    for k, v in zip(node.keys, node.values)
                    if isinstance(k, ast.Constant)
                    and isinstance(v, ast.Constant)
                    and isinstance(v.value, (int, float))
                }
                break
        assert scores is not None, "src_score 테이블을 찾지 못했다"
        assert scores["generated_doc"] <= scores["inference"]
        assert V is not None


# ---------------------------------------------------------------------------
# 두 표가 갈라지지 않게 — 실제로 한 번 갈라졌다
# ---------------------------------------------------------------------------

def _src_score_table() -> dict[str, float]:
    """`validation.py::src_score` 를 AST 로 읽고 **별칭까지 펼친다**(import 부작용 없이).

    ⚠ 2026-07-31 — 이 함수가 `src_score` **리터럴 dict 만** 읽어서 별칭
    (`_src_aliases`)을 구조적으로 못 봤다. 그 결과 아래 세 계약 테스트가
    `srs_default_qm`(점수 0.30 = 최약체, 판정은 강함)이라는 실제 갈라짐을
    **3 passed 로 통과**시켰다 — 가드 자신이 fail-open 이었다.
    별칭을 대상 라벨의 점수로 펼쳐 넣어 같은 사각이 재발하지 않게 한다.
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict) or not node.keys:
            continue
        if not all(
            isinstance(v, ast.Constant) and isinstance(v.value, (int, float))
            for v in node.values
        ):
            continue
        keys = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        if {"comment", "inference", "default"} <= keys:
            table = {
                str(k.value): float(v.value)
                for k, v in zip(node.keys, node.values)
                if isinstance(k, ast.Constant)
                and isinstance(v, ast.Constant)
                and isinstance(v.value, (int, float))
            }
            from report_gen.provenance import SOURCE_ALIASES

            for alias, target in SOURCE_ALIASES.items():
                if target in table:
                    table[alias] = table[target]
            return table
    raise AssertionError("src_score 표를 찾지 못했다")


def test_contract_table_covers_alias_labels():
    """계약 테이블이 **별칭 라벨 자체**를 담아야 한다.

    ⚠ 뮤테이션에서 드러났다: `_src_score_table()` 의 별칭 확장을 지워도 아래
    세 계약 테스트가 전부 통과한다(생존). 확장이 **자기 자신을 지키지 못하는**
    것이다 — 그러면 `is_weak_source()` 가 별칭 인식을 잃는 순간 가드가 다시
    공허 통과로 돌아간다(이번 회귀가 정확히 그 상태였다). 여기서 직접 못박는다.
    """
    from report_gen.provenance import SOURCE_ALIASES

    table = _src_score_table()
    missing = sorted(a for a in SOURCE_ALIASES if a not in table)
    assert not missing, f"계약 테이블이 별칭 라벨을 못 본다: {missing}"


def test_every_alias_target_has_a_score():
    """별칭이 가리키는 정본 라벨은 점수표에 있어야 한다.

    없으면 `src_score.get(..., 0.6)` 로 조용히 접혀, 최약체(0.30)든 최강자(1.00)든
    전부 '추론' 자리인 0.60 을 받는다.
    """
    from report_gen.provenance import SOURCE_ALIASES

    scores = _src_score_table()
    missing = sorted(t for t in set(SOURCE_ALIASES.values()) if t not in scores)
    assert not missing, f"별칭 대상인데 점수가 없다: {missing}"


def test_validation_does_not_redeclare_the_alias_table():
    """별칭 표는 `provenance.SOURCE_ALIASES` 단일 출처다 — 리터럴 재선언 금지.

    복제되면 `is_weak_source()` 와 점수표가 다시 갈라진다(이번 회귀의 원인).
    """
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    offenders = [
        n.lineno for n in ast.walk(tree)
        if isinstance(n, ast.Dict) and n.keys
        and {k.value for k in n.keys if isinstance(k, ast.Constant)} & {"sds_match", "hsis"}
    ]
    assert not offenders, f"validation.py:{offenders} 에 별칭 표가 다시 리터럴로 적혔다"


class TestWeakSourceTableAgreesWithScores:
    """`WEAK_SOURCES`(판정)와 `src_score`(점수)는 함께 움직여야 한다.

    회귀: `generated_doc`(0.30)을 점수표에만 넣고 `WEAK_SOURCES` 에 빠뜨려, 최약체가
    `is_weak_source()` 에서는 **강한 출처**로 분류됐다. 이 함수는 payload 를 제자리
    변경하므로 그 값이 하류로 새고, 더 나은 근거가 와도 덮이지 않게 된다.
    """

    def test_every_low_scoring_source_is_weak(self):
        from report_gen.provenance import WEAK_SCORE_MAX, is_weak_source

        offenders = [
            (src, sc) for src, sc in _src_score_table().items()
            if sc <= WEAK_SCORE_MAX and not is_weak_source(src)
        ]
        assert not offenders, f"점수는 약한데 판정은 강하다: {offenders}"

    def test_every_high_scoring_source_is_strong(self):
        from report_gen.provenance import WEAK_SCORE_MAX, is_weak_source

        offenders = [
            (src, sc) for src, sc in _src_score_table().items()
            if sc > WEAK_SCORE_MAX and is_weak_source(src)
        ]
        assert not offenders, f"점수는 강한데 판정은 약하다: {offenders}"

    def test_every_weak_source_has_a_score(self):
        """점수표에 없는 라벨은 `src_score.get(..., 0.6)` 기본값으로 조용히 접힌다."""
        from report_gen.provenance import WEAK_SOURCES

        scores = _src_score_table()
        missing = sorted(s for s in WEAK_SOURCES if s and s not in scores)
        assert not missing, f"WEAK_SOURCES 에만 있고 점수가 없다: {missing}"


# ---------------------------------------------------------------------------
# 구조 계약 — 모양→출처 분류가 되살아나지 않게
# ---------------------------------------------------------------------------

class TestNoShapeBasedSourceAssignment:
    def test_no_regex_shape_branch_assigns_canonical_source(self):
        """`re.search(...SwFn...)` 결과로 `srs`/`rule`/`sds` 를 배정하는 구조가 없어야 한다.

        AST 로 본다 — 주석이나 문자열 안의 언급은 세지 않는다.
        """
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        fn = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == "generate_asil_related_confidence_report"
        )
        offenders = []
        for node in ast.walk(fn):
            if not isinstance(node, ast.If):
                continue
            test_src = ast.dump(node.test)
            if "re" not in test_src or "search" not in test_src:
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and sub.value in {"srs", "sds", "rule", "reference"}:
                    offenders.append(sub.value)
        assert not offenders, f"모양 기반 출처 배정이 남아 있다: {sorted(set(offenders))}"


class TestReportDoesNotMutateCallerPayload:
    """**리포트가 자기가 감사할 게이트를 부풀리고 있었다** (2026-08-03 실측).

    `details_by_name` 은 `payload["function_details_by_name"]` **그 자체**이고 그 값들은
    `function_details` 와 같은 객체다. 생성 DOCX 병합을 그 객체에 직접 하면 리포트가
    **입력을 변경**한다. 그리고 라우터는 이 리포트 **뒤에** quick gate 를 계산해 DB 에 넣는다:

        jenkins.py        L2600(confidence) -> L2634(quick gate)
        helpers/uds.py    L1827             -> L1860
        local.py          L1197             -> L1236 (두 번째 기록)

    실측(함수 5개): `asil_fill` · `description_fill` · `related_fill` 이 **0.0 -> 100.0**.
    fill 카운터는 출처를 안 보므로, §5-13 이 `generated_doc`=0.30 으로 정직화한 것과
    무관하게 100% 로 잡힌다 — 출처는 정직한데 **분량은 부풀려진다**.

    부수 효과로 계획서 후보 15(리포트 timeout 시 payload 제자리 변경 경합)도 닫힌다:
    타임아웃된 스레드가 계속 돌아도 이제 남의 payload 를 못 만진다.
    """

    def _payload(self):
        """⚠ 전역 `WEAK_PAYLOAD` 를 쓰지 않고 **리터럴로 새로 만든다.**

        옛 코드는 payload 를 제자리 변경하므로, 이 파일의 다른 테스트 12곳이
        `WEAK_PAYLOAD`(모듈 전역)를 **복사 없이** 넘기면서 그걸 오염시킨다.
        오염된 뒤엔 병합 조건이 이미 충족돼 no-op 이 되고, 여기서 그 전역을
        deepcopy 하면 **결함이 자기 탐지를 가린다** — 실제로 그랬다:
        단독 실행은 실패하는데 파일 전체 실행은 통과했다.
        """
        fn = {
            "id": "SwUFn_07", "name": "Ecu_HandleFault",
            "description": "", "description_source": "inference",
            "asil": "", "asil_source": "default",
            "related": "", "related_source": "inference",
        }
        # 라우터가 싣는 모양 — 두 맵이 **같은 객체**를 가리킨다(docx_builder 재결합 후 특히).
        return {"function_details": {"SwUFn_07": fn},
                "function_details_by_name": {"ecu_handlefault": fn}}

    def test_payload_is_untouched(self, report):
        import copy as _c

        payload = self._payload()
        before = _c.deepcopy(payload)
        report(payload)
        assert payload == before, (
            "리포트가 호출자의 payload 를 변경했다 — "
            f"변경 후: {payload['function_details_by_name']['ecu_handlefault']}"
        )

    def test_quick_gate_is_unchanged_by_running_the_report(self, report):
        """감사 도구를 돌렸다고 감사 대상 수치가 움직이면 안 된다."""
        from backend.helpers.uds import _compute_quick_quality_gate

        payload = self._payload()
        before = _compute_quick_quality_gate(payload)["rates"]
        report(payload)
        after = _compute_quick_quality_gate(payload)["rates"]

        for key in ("asil_fill", "description_fill", "related_fill"):
            assert before.get(key) == after.get(key), (
                f"{key} 가 리포트 실행만으로 {before.get(key)} -> {after.get(key)} 로 움직였다"
            )

    def test_report_still_sees_the_merged_values(self, report):
        """⚠ 음성 대조군 — 사본으로 바꾸면서 병합 자체를 죽이면 리포트가 무의미해진다.

        병합 결과는 리포트의 **자기 분석용**으로 살아 있어야 한다: 생성 문서에서 회수한
        값이므로 `generated_doc`(0.30) 로 평가되고 저신뢰로 남아야 한다.
        """
        text = report(self._payload())
        assert "생성 문서 회수" in text, "병합이 통째로 죽어 문서 유래 값을 못 봤다"
        assert _score(text) <= 0.35, f"생성 문서 유래인데 점수가 높다: {_score(text)}"
