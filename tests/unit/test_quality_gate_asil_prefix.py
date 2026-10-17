"""ASIL 표기가 게이트를 끄고 있었다 — 분기(B+)·MC/DC(D) 커버리지 축.

## 무엇이 있었나

`evaluate_coverage` 는 등급으로 두 게이트를 켠다:

    branch_coverage_pct : ASIL B/C/D 에서 100% 필수
    mcdc_coverage_pct   : ASIL D 에서 100% 필수

판정이 `a = str(asil or "").upper().strip()` 뒤 `a in ("B","C","D")` / `a == "D"` 였다.
그런데 이 저장소에서 흐르는 값은 **전부 `"ASIL B"` 형식**이다 —
`DocGenPreflightPanel.jsx` 의 `ASIL_CHOICES`, `config/swut_meta.json`, `schemas.py`
기본값이 모두 그렇다. `reports/quality.sqlite` 실측(2026-09-20):

    asil_level 분포 = {'ASIL A': 17, 'ASIL B': 23}    단문자 **0건**

즉 두 게이트는 **프로덕션에서 한 번도 켜진 적이 없다**. ISO 26262 에서 ASIL D 의
MC/DC 100% 는 필수 요구인데, 그 축이 조용히 빠진 채 문서는 "통과" 로 보였다.

## 왜 기존 테스트가 못 잡았나 — 세 층이 동시에 비어 있었다

1. 평가기 단위 테스트가 **구현과 같은 어휘**를 쓴다(`asil="D"`). 두 분기가 다 살아
   있어 가드가 헛돌지 않는 것처럼 보인다.
2. 접두형이 `record_run` 까지 가는 테스트는 하나뿐인데(`test_quality_empty_output.py`)
   `total_tcs=0` 이라 빈-산출물 조기 반환에 걸려 **평가기에 닿지 못한다**.
3. 구조 가드(`test_gate_threshold_single_source.py`)의 `_literals()` 는 `ast.IfExp` 의
   `body`/`orelse` 만 펼치고 `test`(조건식)는 방문하지 않는다 — 설계상 관심사가
   "숫자가 표에서 오는가" 이지 "그 조건이 참이 될 수 있는가" 가 아니다.

그래서 이 파일은 **값이 아니라 게이트가 실제로 켜지는지**를, 그리고 등급이
**호출부를 통해 평가기까지 도달하는지**를 본다.
"""
from __future__ import annotations

import ast
import inspect
import json
import pathlib

import pytest

from workflow.asil_propagation import normalize_asil
from workflow.quality.db import get_session, init_db
from workflow.quality.evaluator import evaluate_coverage, evaluate_swit_coverage
from workflow.quality.models import GenerationRun
from workflow.quality.recorder import record_run

# 2026-08-26 KJPDS02 PV 실측값(run 1794) — 분기는 미달, MC/DC 는 미측정이다.
# 값을 바꾸지 말 것: 이 숫자라야 "게이트가 켜지면 FAIL 이 난다" 가 관측된다.
CANON = {
    "overall_statement_pct": 99.45,
    "overall_branch_pct": 98.64,
    "overall_mcdc_pct": 0.0,
    "passed": 6882,
    "failed": 0,
    "not_executed": 0,
    "total_tcs": 6882,
    "measured_functions": {"statement": 1014},
}


def _by(asil):
    return {m["metric_name"]: m for m in evaluate_coverage(CANON, asil=asil)}


@pytest.fixture
def qdb(monkeypatch, tmp_path):
    from workflow.quality import db as qdb_mod

    db_file = tmp_path / "q.sqlite"
    monkeypatch.setattr(qdb_mod, "_default_db_path", lambda: db_file)
    qdb_mod.reset_engine()
    qdb_mod.init_db(db_file)
    yield db_file
    qdb_mod.reset_engine()


class TestNormalizeAsilTakesBothSpellings:
    """`ASIL D` 는 비표준 표기가 아니라 **같은 등급의 다른 표기**다."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("ASIL D", "D"), ("ASIL-D", "D"), ("ASIL_D", "D"), ("ASIL:D", "D"),
            ("asil d", "D"), ("  ASIL  D  ", "D"), ("D", "D"),
            ("ASIL B", "B"), ("B", "B"), ("ASIL A", "A"), ("QM", "QM"),
            # 구분자 0개도 받는다(`*`). 형제 `swut_asil_resolver._normalize_asil` 의
            # regex 도 `*` 라 같은 완화다 — 명문화해 두지 않으면 다음 사람이 `+` 로
            # "고쳐서" 두 경로가 갈린다(뮤테이션이 이 칸 없이는 살아남았다).
            ("ASILD", "D"), ("ASILQM", "QM"),
        ],
    )
    def test_prefix_is_stripped(self, raw, expected):
        """뮤테이션: `_ASIL_PREFIX_RE.sub` 를 지우면 접두형 전부가 None 이라 실패."""
        assert normalize_asil(raw) == expected, raw

    @pytest.mark.parametrize("raw", ["C(D)", "ASIL C(D)", "Z", "ASIL Z", "ASIL", "", "  ", None, "TBD"])
    def test_nonstandard_is_still_unknown(self, raw):
        """접두를 벗긴 뒤에도 **같은 엄격함**을 유지한다 — 느슨해지면 오분류가 된다.

        뮤테이션: 벗긴 결과를 그대로 반환하면(`in _ASIL_METRIC` 검사 제거)
        `"C(D)"` 가 등급으로 통과해 실패.
        """
        assert normalize_asil(raw) is None, repr(raw)

    @pytest.mark.parametrize("raw", ["QM ASIL", "D ASIL", "NOT ASIL D", "SEE ASIL B TABLE"])
    def test_prose_containing_asil_is_not_a_grade(self, raw):
        """산문 안에 `ASIL` 이 있어도 등급이 되지 않는다.

        ⚠ 이 케이스들은 **앵커를 재지 못한다** — 앵커를 빼도 결과가 같다(`"QM ASIL"` 은
        어느 쪽이든 `"QM "` 이 남아 등급 집합에 없다). 겹쳐 막히는 입력이라
        뮤테이션이 살아남았고, 앵커 전용 케이스를 아래에 따로 뒀다.
        그래도 이 줄들은 남긴다 — 사용자가 실제로 넣을 법한 값이다.
        """
        assert normalize_asil(raw) is None, repr(raw)

    @pytest.mark.parametrize("raw", ["QMASIL", "DASIL", "ASIL ASIL D"])
    def test_prefix_must_be_at_the_front(self, raw):
        """`^` 앵커 전용 — **접두 자리가 아닌 ASIL 을 지워 등급을 만들지 않는다**.

        `re.sub` 는 기본이 전역 치환이라 앵커가 없으면 문자열 **어디의** `ASIL` 이든
        지운다: `"QMASIL"` → `"QM"`(등급!), `"ASIL ASIL D"` → `"D"`(등급!).
        형제 regex 는 `search` 라 이쪽이 더 엄격하고, 그게 의도다.

        뮤테이션: `^` 를 빼면 이 세 입력이 등급으로 통과해 실패.
        (⚠ 첫 판의 음성 목록은 전부 뒤에 공백이 남아 앵커 없이도 막혔다 —
         가드가 겹쳐 막히면 뮤턴트가 산다. 이 세 입력은 앵커 하나만 잰다.)
        """
        assert normalize_asil(raw) is None, repr(raw)

    def test_unknown_is_none_not_empty_string(self):
        """`None`(미상)과 `""` 를 같은 값으로 접지 않는다.

        모듈 docstring 의 정직성 규약("오분류보다 미상이 낫다")이 이 구분 위에 서 있다.
        뮤테이션: `return s if ... else ""` 로 바꾸면 실패.
        """
        assert normalize_asil("TBD") is None
        assert normalize_asil("TBD") != ""


class TestTheGateActuallyTurnsOn:
    """접두형과 단문자가 **같은 게이트**를 만든다 — 이게 결함의 본체다."""

    @pytest.mark.parametrize(("prefixed", "letter"), [("ASIL D", "D"), ("ASIL B", "B"), ("ASIL C", "C")])
    def test_prefixed_equals_letter(self, prefixed, letter):
        """값이 아니라 `threshold` 와 `gate_pass` **둘 다** 같아야 한다.

        뮤테이션: evaluator 가 `str(asil or "").upper().strip()` 로 되돌아가면
        접두형 쪽 threshold 가 None 이 되어 실패.
        """
        a, b = _by(prefixed), _by(letter)
        for metric in ("branch_coverage_pct", "mcdc_coverage_pct"):
            assert a[metric]["threshold"] == b[metric]["threshold"], f"{prefixed} vs {letter}: {metric}"
            assert a[metric]["gate_pass"] == b[metric]["gate_pass"], f"{prefixed} vs {letter}: {metric}"

    def test_asil_d_gates_both_axes(self):
        """ASIL D → 분기·MC/DC 둘 다 걸리고, CANON 값에서 **둘 다 미달**이다."""
        by = _by("ASIL D")
        assert by["branch_coverage_pct"]["threshold"] == 100.0
        assert by["branch_coverage_pct"]["gate_pass"] is False
        assert by["mcdc_coverage_pct"]["threshold"] == 100.0
        assert by["mcdc_coverage_pct"]["gate_pass"] is False

    def test_asil_b_gates_branch_only(self):
        """ASIL B 는 분기만 — MC/DC 를 함께 걸면 등급 구분이 사라진다."""
        by = _by("ASIL B")
        assert by["branch_coverage_pct"]["threshold"] == 100.0
        assert by["mcdc_coverage_pct"]["threshold"] is None

    def test_the_gate_is_off_for_anything_the_normalizer_rejects(self):
        """가드가 헛돌지 않음을 보인다 — **프로덕션 코드를 실제로 호출해서**.

        ⚠ 첫 판은 `str("ASIL D" or "").upper().strip()` 의 결과만 단언했다. 그건
        Python 의미론상 항상 참이라 **이 저장소의 어떤 변경으로도 실패할 수 없는**
        공허한 테스트였다(리뷰 지적). 인용했던 선례
        `test_quality_evaluator.py::test_the_old_evaluator_really_did_fail_on_it` 은
        반대로 실제 평가기를 호출해 오작동을 관측한다 — 그 형태로 맞춘다.

        옛 판정이 들고 있던 값(`"ASIL D"`)은 정규화기가 거부하는 값이 아니라
        **받아들이는 값**이므로, 여기서는 두 방향을 같이 잰다:
        정규화기가 거부하는 문자열은 게이트가 꺼지고, 접두형은 켜진다.
        """
        # 정규화기가 거부하는 값 → 두 축 모두 비게이트 (옛 판정이 접두형에 하던 일)
        assert normalize_asil("NOT-A-GRADE") is None
        off = _by("NOT-A-GRADE")
        assert off["branch_coverage_pct"]["threshold"] is None
        assert off["mcdc_coverage_pct"]["threshold"] is None

        # 접두형은 이제 등급으로 받아들여져 두 축이 켜진다
        assert normalize_asil("ASIL D") == "D"
        on = _by("ASIL D")
        assert on["branch_coverage_pct"]["threshold"] == 100.0
        assert on["mcdc_coverage_pct"]["threshold"] == 100.0

        # 옛 판정식이 왜 껐는지 — 그 식의 산출물이 등급 토큰이 아니었다
        assert str("ASIL D").upper().strip() not in ("B", "C", "D")


class TestTheGateStaysOffWhenItShould:
    """음성 대조군 — 이게 없으면 "전부 켜기" 로 바꿔도 위 클래스가 통과한다."""

    @pytest.mark.parametrize("asil", ["ASIL A", "A", "QM", "ASIL QM", "TBD", "", None, "C(D)", "Z"])
    def test_mcdc_not_gated(self, asil):
        assert _by(asil)["mcdc_coverage_pct"]["threshold"] is None, repr(asil)

    @pytest.mark.parametrize("asil", ["ASIL A", "A", "QM", "TBD", "", None, "C(D)", "Z"])
    def test_branch_not_gated(self, asil):
        assert _by(asil)["branch_coverage_pct"]["threshold"] is None, repr(asil)

    @pytest.mark.parametrize("asil", ["ASIL A", "ASIL D", "QM", "", None])
    def test_statement_is_gated_for_every_grade(self, asil):
        """구문 커버리지는 **전 ASIL 필수**라 등급과 무관하게 걸린다."""
        assert _by(asil)["statement_coverage_pct"]["threshold"] == 100.0, repr(asil)


class TestTheGradeReachesTheGateThroughTheRecorder:
    """헬퍼 단독 테스트는 **호출부가 값을 버리는 것**을 못 본다.

    이 저장소가 이미 이름 붙인 공백이다(`test_swut_router.py` 의 배선 가드 주석).
    평가기를 직접 부르는 테스트만 있으면 `recorder` 가 `meta` 를 안 넘기도록 바뀌어도
    전부 초록이다. 그래서 DB 왕복으로 확인한다.
    """

    # 빈-산출물 조기 반환(`recorder.py`)을 피해야 평가기에 닿는다 — `total_tcs>0` 필수.
    SUMMARY = {
        "total_tcs": 12, "overall_statement_pct": 100.0, "overall_branch_pct": 80.0,
        "overall_mcdc_pct": 50.0, "passed": 12, "failed": 0, "not_executed": 0,
        "measured_functions": {"statement": 5},
    }

    @staticmethod
    def _scores(db_path, run_id):
        init_db(db_path)
        with get_session(db_path) as s:
            run = s.query(GenerationRun).filter_by(id=run_id).one()
            return {sc.metric_name: {"value": sc.value, "gate_pass": sc.gate_pass,
                                     "threshold": sc.threshold} for sc in run.scores}

    def test_prefixed_grade_from_meta_gates_in_the_db(self, qdb):
        """`meta={"asil_level": "ASIL D"}` 가 DB 의 threshold 로 나타나야 한다.

        뮤테이션: `recorder` 가 `asil=_meta.get("asil_level")` 을 안 넘기면
        두 threshold 가 None 이라 실패.
        """
        rid = record_run("swut", dict(self.SUMMARY), db_path=qdb,
                         meta={"asil_level": "ASIL D", "kind": "coverage"})
        # `record_run` 은 광범위 except 로 -1 을 낸다 — 기록 실패를 통과로 읽지 않는다.
        assert rid > 0, "run 이 기록되지 않았다(-1) — 평가기까지 가지도 못했다"

        sc = self._scores(qdb, rid)
        assert sc["branch_coverage_pct"]["threshold"] == 100.0
        assert sc["branch_coverage_pct"]["gate_pass"] is False
        assert sc["mcdc_coverage_pct"]["threshold"] == 100.0
        assert sc["mcdc_coverage_pct"]["gate_pass"] is False

    def test_asil_a_from_meta_leaves_both_ungated(self, qdb):
        """음성 대조군 — 배선이 "무조건 게이트" 로 바뀌지 않았는지."""
        rid = record_run("swut", dict(self.SUMMARY), db_path=qdb,
                         meta={"asil_level": "ASIL A", "kind": "coverage"})
        assert rid > 0
        sc = self._scores(qdb, rid)
        assert sc["branch_coverage_pct"]["threshold"] is None
        assert sc["mcdc_coverage_pct"]["threshold"] is None

    def test_the_original_spelling_is_kept_in_meta(self, qdb):
        """정규화는 **판정용**이다 — 기록된 원문을 고쳐 쓰지 않는다.

        "정규화는 새 근거가 아니다. 출처는 원래 값을 그대로 둔다"
        (`backend/helpers/uds.py` 의 같은 판단).
        """
        rid = record_run("swut", dict(self.SUMMARY), db_path=qdb,
                         meta={"asil_level": "ASIL D", "kind": "coverage"})
        init_db(qdb)
        with get_session(qdb) as s:
            run = s.query(GenerationRun).filter_by(id=rid).one()
            assert run.meta_json, "meta_json 이 비었다 — 원문 보존을 잴 수 없다"
            assert json.loads(run.meta_json)["asil_level"] == "ASIL D"


class TestTheUnmeasuredAxisStaysVisible:
    """게이트를 켜면 **미측정 축도 FAIL 이 된다** — 그 사유가 보여야 한다.

    ASIL D 의 MC/DC 는 이 프로젝트에서 측정 자체가 없다(`coverage_unmeasured_axes`).
    fail-closed 는 의도이나(안전 축을 미평가로 완화하지 않는다), FAIL 의 **사유**가
    "커버리지 0%" 인지 "측정 미수행" 인지는 조치를 가른다.
    """

    BASE = {
        "total_tcs": 12, "overall_statement_pct": 100.0, "overall_branch_pct": 100.0,
        "passed": 12, "failed": 0, "not_executed": 0,
        "measured_functions": {"statement": 10, "branch": 10, "mcdc": 0},
    }

    def test_degenerate_mcdc_counts_as_unmeasured(self):
        """`overall_mcdc_pct` 가 **리터럴 0.0 으로 중화**된 경우도 미측정으로 센다.

        생산자(`swut_input_adapter.compute_coverage_rollup`)는 MC/DC 컬럼이 함수-진입
        커버리지로 퇴화하면 `None` 이 아니라 `0.0` 을 낸다(값 위조 차단). 그래서
        `is None` 검사만으로는 안 걸린다 — 생산자가 함께 싣는 `mcdc_degenerate` 로 합류.

        뮤테이션: evaluator 의 `mcdc_degenerate` 합류 분기를 지우면 이 값이 0 이 되어 실패.
        """
        by = {m["metric_name"]: m for m in evaluate_coverage(
            {**self.BASE, "overall_mcdc_pct": 0.0, "mcdc_degenerate": True}, asil="ASIL D")}
        assert by["coverage_unmeasured_axes"]["value"] == 1.0
        # 그리고 게이트는 여전히 FAIL 이다 — 사유가 보인다고 완화하지 않는다.
        assert by["mcdc_coverage_pct"]["gate_pass"] is False

    def test_real_zero_is_not_reported_as_unmeasured(self):
        """음성 대조군 — 진짜 0% 실측은 미측정이 아니다."""
        by = {m["metric_name"]: m for m in evaluate_coverage(
            {**self.BASE, "overall_mcdc_pct": 0.0, "mcdc_degenerate": False}, asil="ASIL D")}
        assert by["coverage_unmeasured_axes"]["value"] == 0.0

    def test_the_producer_actually_ships_that_flag(self):
        """**생산자 배선** — `mcdc_degenerate` 를 실제로 싣는지.

        위 두 테스트는 summary 를 손으로 만들어 넣으므로 생산자가 그 키를 안 실어도
        통과한다(뮤테이션이 그렇게 살아남았다). 평가기가 읽는 키를 **만드는 쪽**을
        직접 잰다.

        뮤테이션: `compute_coverage_rollup` 에서 `"mcdc_degenerate"` 를 빼면 실패.
        """
        from backend.services.swut_input_adapter import (
            CoverageStats,
            FunctionCoverage,
            compute_coverage_rollup,
        )

        # `_is_degenerate_pairs` 의 퇴화 지문 3조건을 **전부** 만족시켜야 한다:
        #   ① 함수 8개 이상(소표본 우연 방지) ② 전 함수 pairs.total == 1
        #   ③ branch.total 최대값 > 2(분기>2 인데 pairs=1 은 물리적 불가)
        # ⚠ 첫 판은 함수 4개라 ①에 걸려 `False` 가 나왔다 — 테스트 데이터가 축을
        #   실제로 재는지 확인하지 않으면 가드가 공허해진다.
        rows = [
            FunctionCoverage(
                unit_id=f"SwUFn_{i}", name=f"fn_{i}",
                statement=CoverageStats(covered=8, total=10),
                branch=CoverageStats(covered=3, total=2 + (i % 4)),
                mcdc=CoverageStats(covered=1, total=1),
            )
            for i in range(10)
        ]
        out = compute_coverage_rollup(rows)
        assert out["mcdc_degenerate"] is True, (
            "퇴화한 MC/DC 를 생산자가 신고하지 않는다 — 평가기가 미측정으로 셀 수 없다"
        )
        assert out["overall_mcdc_pct"] == 0.0, "퇴화 값은 0.0 으로 중화된다(값 위조 차단)"

    def test_newly_gated_axes_publish_their_denominator(self):
        """새로 게이트가 된 두 축의 **분모**도 싣는다.

        생산자는 `measured_functions.branch/mcdc` 를 이미 세는데 소비처가
        statement 만 싣고 버렸다. 백분율만 보면 "1개 함수 100%" 와
        "1014개 함수 100%" 가 같아 보인다.
        """
        by = {m["metric_name"]: m for m in evaluate_coverage(self.BASE, asil="ASIL D")}
        assert by["coverage_measured_functions"]["value"] == 10.0
        assert by["coverage_measured_functions_branch"]["value"] == 10.0
        assert by["coverage_measured_functions_mcdc"]["value"] == 0.0


class TestUnmeasuredAxisGetsADifferentInstruction:
    """**이 변경이 새로 만든 결함**의 가드 (리뷰 W1).

    게이트가 켜지기 전엔 MC/DC 제안이 아예 없었다(threshold None → skip). 켜지자
    최고 우선순위 조치로 *"복합 조건의 각 피연산자가 …테스트 조합을 보강하세요"* 가
    나갔는데, 그 축은 분모가 0 이라 **TC 를 아무리 늘려도 값이 안 변한다**.
    침묵이 틀린 지시로 바뀐 자리다.
    """

    SUMMARY = {
        "total_tcs": 12, "overall_statement_pct": 100.0, "overall_branch_pct": 100.0,
        "overall_mcdc_pct": 0.0, "mcdc_degenerate": True,
        "passed": 12, "failed": 0, "not_executed": 0,
        "measured_functions": {"statement": 10, "branch": 10, "mcdc": 0},
    }

    def _advice_for(self, qdb, metric):
        from workflow.quality.advisor import suggest_improvements

        rid = record_run("swut", dict(self.SUMMARY), db_path=qdb,
                         meta={"asil_level": "ASIL D", "kind": "coverage"})
        assert rid > 0
        out = suggest_improvements(rid, db_path=qdb)
        return next((s for s in out.get("suggestions", []) if s["metric"] == metric), None)

    def test_mcdc_advice_says_measure_not_add_tests(self, qdb):
        """뮤테이션: advisor 의 `_UNMEASURED_ADVICE` 교체를 지우면 실패."""
        s = self._advice_for(qdb, "mcdc_coverage_pct")
        assert s is not None, "ASIL D 에서 MC/DC 제안이 나와야 한다"
        assert s["unmeasured"] is True
        assert "측정" in s["advice"]
        assert "테스트 조합을 보강" not in s["advice"], (
            "분모 0 인 축에 'TC 를 늘리라' 고 지시하고 있다 — 값이 변하지 않는다"
        )

    def test_a_measured_axis_keeps_the_normal_advice(self, qdb):
        """음성 대조군 — 실측이 있는 축은 원래 문구를 유지한다.

        이게 없으면 "전부 미측정 문구로 교체" 로 바꿔도 위 테스트가 통과한다.
        """
        from workflow.quality.advisor import suggest_improvements

        measured = {**self.SUMMARY, "overall_branch_pct": 50.0,
                    "measured_functions": {"statement": 10, "branch": 10, "mcdc": 0}}
        rid = record_run("swut", measured, db_path=qdb,
                         meta={"asil_level": "ASIL D", "kind": "coverage"})
        out = suggest_improvements(rid, db_path=qdb)
        s = next((x for x in out.get("suggestions", []) if x["metric"] == "branch_coverage_pct"), None)
        assert s is not None and s["unmeasured"] is False
        assert "측정 자체가 없습니다" not in s["advice"]


class TestScoreDeltaRefusesToCompareDifferentScales:
    """척도가 바뀐 두 점수를 빼지 않는다 (리뷰 W3).

    `compute_overall_score` 는 게이트 축만 평균한다. ASIL 정규화로 축이 늘면
    **소스·문서를 한 글자도 안 바꿔도** 점수가 떨어진다(실측: 축2 74.86 → 축4 49.76).
    그 차이를 delta 로 그리면 화면이 품질 하락으로 읽는다.
    """

    S = {"total_tcs": 12, "overall_statement_pct": 100.0, "overall_branch_pct": 80.0,
         "overall_mcdc_pct": 50.0, "passed": 12, "failed": 0, "not_executed": 0,
         "measured_functions": {"statement": 10, "branch": 10, "mcdc": 10}}

    @staticmethod
    def _summary_of(db_path, rid):
        init_db(db_path)
        with get_session(db_path) as s:
            run = s.query(GenerationRun).filter_by(id=rid).one()
            assert run.summary is not None, "요약이 없다 — 점수 척도를 잴 대상이 없다"
            return (run.summary.score_delta,
                    json.loads(run.meta_json or "{}").get("score_scale_changed"))

    def test_scale_change_suppresses_delta_and_says_why(self, qdb):
        """뮤테이션: `_prev_gated != _now_gated` 분기를 지우면 delta 가 숫자로 나와 실패."""
        record_run("swut", dict(self.S), db_path=qdb, scm_id="p1",
                   meta={"asil_level": "ASIL A", "kind": "coverage"})          # 축 2
        r2 = record_run("swut", dict(self.S), db_path=qdb, scm_id="p1",
                        meta={"asil_level": "ASIL D", "kind": "coverage"})     # 축 4
        delta, changed = self._summary_of(qdb, r2)
        assert delta is None, "척도가 다른데 뺄셈을 했다"
        assert changed == {"prev_gated_metric_count": 2, "gated_metric_count": 4}

    def test_same_scale_still_computes_delta(self, qdb):
        """음성 대조군 — 축이 같으면 delta 는 정상 계산된다(기능을 죽이지 않았다)."""
        record_run("swut", dict(self.S), db_path=qdb, scm_id="p1",
                   meta={"asil_level": "ASIL D", "kind": "coverage"})
        r2 = record_run("swut", dict(self.S), db_path=qdb, scm_id="p1",
                        meta={"asil_level": "ASIL D", "kind": "coverage"})
        delta, changed = self._summary_of(qdb, r2)
        assert delta == 0.0
        assert changed is None


class TestCoverageBuildPassesTheGradeToTheRecorder:
    """호출부를 **AST 로** 확인한다 — 커버리지 빌드가 등급을 실어 보내는가.

    `test_swut_router.py::TestQualityRecordingWiring` 이 같은 일을 하지만 검사 대상이
    `_record_test_quality` 호출의 `doc_type` 하나뿐이라, `record_run` 을 직접 부르는
    커버리지 경로(`_do_coverage_build`)와 `meta` 의 `asil_level` 은 사각지대였다.
    이번 결함이 정확히 거기에 있었다.
    """

    TARGETS = [("backend/routers/swut.py", "_do_coverage_build")]

    @pytest.mark.parametrize(("path", "func_name"), TARGETS)
    def test_record_run_call_carries_asil_level(self, path, func_name):
        """뮤테이션: `meta` 에서 `asil_level` 키를 빼면 실패."""
        tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name), None)
        assert fn is not None, f"{func_name} 가 사라졌다 — 테스트가 겨눌 대상이 없다"

        metas = []
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "record_run"):
                kw = {k.arg: k.value for k in node.keywords}
                meta = kw.get("meta")
                if isinstance(meta, ast.Dict):
                    metas.append([k.value for k in meta.keys if isinstance(k, ast.Constant)])
        assert metas, f"{func_name} 가 record_run(meta=...) 을 부르지 않는다"
        for keys in metas:
            assert "asil_level" in keys, f"{func_name} 의 record_run meta 에 asil_level 이 없다: {keys}"


class TestSwitCoverageDoesNotPretendToUseAsil:
    """받지도 않는 값을 받는 척하지 않는다.

    `evaluate_swit_coverage` 는 `asil` 을 받되 본문에서 한 번도 읽지 않았고, 호출부는
    값을 넘기고 있었다. 시그니처가 형제(`evaluate_coverage`)와 같아 "ASIL 게이트가
    걸린다" 로 오독된다. SwITCV 의 두 축은 등급과 무관하다(그쪽 docstring §게이트 축).
    """

    def test_signature_has_no_asil(self):
        """뮤테이션: `asil` 인자를 되살리면 실패."""
        params = inspect.signature(evaluate_swit_coverage).parameters
        assert "asil" not in params, (
            "evaluate_swit_coverage 가 asil 을 다시 받는다 — 쓰지 않을 값이면 받지 말 것"
        )

    def test_recorder_does_not_pass_asil_to_it(self):
        """호출부도 같이 본다 — 한쪽만 고치면 TypeError 로 기록이 통째로 사라진다."""
        src = pathlib.Path("workflow/quality/recorder.py").read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(src)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "evaluate_swit_coverage"):
                kwargs = {k.arg for k in node.keywords}
                assert "asil" not in kwargs, f"recorder.py:{node.lineno} 가 asil 을 넘긴다"

    def test_it_still_produces_its_own_axes(self):
        """인자를 뺐다고 산출이 바뀌면 안 된다."""
        names = {m["metric_name"] for m in evaluate_swit_coverage({
            "swit_functions_total": 10, "swit_functions_achieved": 9,
            "swit_function_calls_total": 20, "swit_function_calls_covered": 18,
            "passed": 5, "failed": 0, "not_executed": 0, "total_tcs": 5,
        })}
        assert {"function_achievement_pct", "function_call_coverage_pct", "pass_rate_pct"} <= names


class TestSiblingNormalizersDoNotDrift:
    """형제 정규화기가 **갈리지 않는지** (리뷰 W4).

    `test_design_advisor._asil_of` 는 등급 판정을 자기 안에 복제하고 있었다. 동작이
    같아 무해해 보였지만, `normalize_asil` 이 접두를 받도록 고쳐지는 순간 둘이
    갈렸다 — 같은 함수가 한 패널에선 `D`, 다른 패널에선 미상으로 뜬다.

    복제를 만들지 않는 것과 **이미 있는 복제를 갈라 두지 않는 것**은 같은 규약이다.
    """

    @pytest.mark.parametrize("raw", ["ASIL D", "ASIL-D", "asil b", "D", "QM", "TBD", "C(D)", "", None, "QMASIL"])
    def test_advisor_agrees_with_the_single_source(self, raw):
        """뮤테이션: `_asil_of` 가 `s in _ASIL_METRIC` 을 다시 들면 접두형에서 실패."""
        from workflow.test_design_advisor import _asil_of

        assert _asil_of(raw) == normalize_asil(raw), repr(raw)

    def test_it_still_unwraps_the_dict_shape(self):
        """위임하면서 **자기 몫(dict 껍질 벗기기)은 유지**해야 한다."""
        from workflow.test_design_advisor import _asil_of

        assert _asil_of({"asil": "ASIL D", "source": "uds_link"}) == "D"
        assert _asil_of({"asil": None}) is None


class TestAsilExtractorsHandTheAggregatorLetters:
    """`swut_coverage_aggregator` 의 등급 비교가 letter 를 받는다는 **계약**.

    `_compute_asil_distribution` 은 `asil in ("B","C","D")` 로 판정하는데, 그게 맞는
    이유는 추출기(`iso26262_doc_asil_extractor`)가 `swut_asil_resolver._normalize_asil`
    로 이미 letter 를 만들어 넘기기 때문이다. 그 사실이 어디에도 적혀 있지 않아,
    추출기에서 정규화가 빠지면 이 비교가 **조용히** 빗나간다.
    """

    #: `_compute_asil_distribution` 이 받는 등급 맵 **4종 전부**의 생산자.
    #: 첫 판은 이 중 하나(추출기)만 봤고, 그것도 `"_normalize_asil" in src` 라
    #: **import 줄만으로 통과**했다(리뷰 지적). 호출이 사라져도 초록이던 가드다.
    PRODUCERS = [
        ("backend/services/swut_asil_resolver.py", "function_asil_map"),
        ("backend/services/swut_swuds_parser.py", "function_asil_from_suds"),
        ("backend/services/iso26262_doc_asil_extractor.py", "component_asil_from_sds · function_asil_from_srs"),
    ]

    def test_extractor_normalizes_to_letters(self):
        from backend.services.swut_asil_resolver import _normalize_asil

        for raw in ("ASIL D", "ASIL-D", "asil d", "D"):
            assert _normalize_asil(raw) == "D", raw

    @pytest.mark.parametrize(("path", "consumer"), PRODUCERS)
    def test_producers_actually_call_the_normalizer(self, path, consumer):
        """**호출 노드**가 있는지 AST 로 본다 — import 만 남아도 통과하면 안 된다.

        뮤테이션: 어느 파일에서든 `_normalize_asil(...)` 호출을 지우고 import 만
        남기면 실패한다(첫 판은 통과했다).
        """
        tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and (getattr(n.func, "id", None) == "_normalize_asil"
                      or getattr(n.func, "attr", None) == "_normalize_asil")]
        assert calls, (
            f"{path} 가 _normalize_asil 을 **호출**하지 않는다 — {consumer} 에 접두형이 실려 "
            f"swut_coverage_aggregator 의 등급 비교가 빗나간다"
        )

    def test_a_prefixed_grade_would_erase_the_asil_d_function_list(self):
        """계약이 깨지면 **무엇이 관측되는가** — 값으로 고정한다.

        `_compute_asil_distribution` 은 `f"ASIL_{asil}"` 로 버킷을 만들고
        `asil in ("B","C","D")` 로 등급별 ID 목록을 쌓는다. 접두형이 들어오면
        버킷 이름이 `ASIL_ASIL D` 로 깨지고 **ASIL D 함수 목록이 통째로 빈다** —
        ISO 26262 감사에서 "ASIL D 함수 없음" 으로 읽히는 침묵 손실이다.

        이 테스트는 aggregator 를 고치라는 뜻이 아니다(입력이 letter 라 현행은
        정상). 그 **전제가 깨졌을 때의 피해**를 적어 두어, 생산자에서 정규화를
        빼면 위 AST 가드와 함께 두 겹으로 잡히게 한다.
        """
        from backend.services.swut_coverage_aggregator import _compute_asil_distribution
        from backend.services.swut_input_adapter import FunctionCoverage

        rows = [FunctionCoverage(unit_id="SwUFn_0001", name="fn_a")]

        dist, ids, _ = _compute_asil_distribution(rows, {"fn_a": "D"})
        assert dist.get("ASIL_D") == 1
        assert ids["D"] == ["fn_a"], "letter 입력에서는 ASIL D 목록이 채워진다"

        dist_bad, ids_bad, _ = _compute_asil_distribution(rows, {"fn_a": "ASIL D"})
        assert dist_bad.get("ASIL_ASIL D") == 1, "접두형은 버킷 이름을 깨뜨린다"
        assert ids_bad["D"] == [], "그리고 ASIL D 함수 목록이 통째로 빈다"
