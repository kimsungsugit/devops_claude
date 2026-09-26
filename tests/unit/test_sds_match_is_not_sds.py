"""`sds_match` 는 `sds` 가 아니다 — §6 후보 20.

## 왜 이 파일이 생겼나 (2026-08-04)

`sds_match` 는 `report_gen/requirements.py` 의 SDS 매칭 블록에서 붙는 라벨인데,
그 자리는 *"설명을 SDS 에서 가져왔을 때"* 의 **else 분기**다:

    if (설명이 비었거나 'function...' 로 시작) and sds_info 에 설명이 있다:
        info["description"] = sds_info["description"]
        info["description_source"] = "sds"          # ← SDS 에서 가져왔다
    elif 값이 있고 출처가 약하면:
        info["description_source"] = "sds_match"    # ← SDS 에서 **안** 가져왔다

즉 이 라벨의 뜻은 *"함수는 SDS 에 매핑됐지만 이 설명 문구는 SDS 유래가 아니다"* 다.
그런데 `SOURCE_ALIASES` 가 이걸 `sds` 로 접어 **0.95(정본 문서)** 를 주고 있었다.

같은 사실이 §6 후보 19 를 기각시킨 근거였다 — 그때는 `trusted=False` 가 **정답**이라는
결론이었고, 이번엔 그 결론의 대칭편(점수도 SDS 급이면 안 된다)을 적용한다.

## 실측 이동량 — **실제 생산 함수를 두 번 돌려서** 잰 값 (2026-08-04)

`generate_asil_related_confidence_report` 를 `reports/uds_local/*.payload.json`
33개에 대해 별칭 복원본/현행본으로 각각 실행:

| 축 | 이동 |
|---|---|
| 문서 등급 | **9 / 33 파일**, 전부 **하향** (A→B 7, B→C 2) |
| Description canonical(doc-backed) | 5,805 → 4,556 (**−1,249**) |

마지막 줄이 이 변경의 요점이다: 설명이 문서에서 오지 **않았다**고 코드가 명시한
1,249행이 "정본 문서 근거" 로 계상되고 있었다. 표에도 `SDS: 209/220 (95.0%)` 로
찍혀 *"설명 95%가 SDS 유래"* 처럼 읽혔다.

⚠ 이 수치를 복제 스크립트로 재면 안 된다. `_score_for` 의 표면 선택
(`function_details_by_name` 우선)을 흉내 낸 replica 는 같은 코퍼스에서 11파일/−2,184 를
냈다 — **과대**다. 라이브 인자·표면과 어긋나면 조용히 틀린다
([[reference_sim_harness_live_parity]]).

## 하지 않은 것

- **0.75 이하로 내리지 않았다.** `WEAK_SCORE_MAX` 아래면 `is_weak_source()` 가 True 가
  되어 RAG·AI·HSIS 덮어쓰기 3경로가 새로 열린다 — 점수 정직화가 아니라 산출물 내용
  변경이고, 이번 라운드에서 측정한 범위가 아니다.
- **`function_analyzer.py:839` 의 `trusted` 리터럴은 안 건드렸다.** 조사 초안은 그걸
  `canonical_source()` 경유로 바꾸자고 했으나 반증에서 뒤집혔다 — 그 사이트는 세 표 중
  **유일하게 맞는** 표이고(설명이 SDS 유래가 아니므로 medium 이 정답), 바꾸면 `hsis`
  가 medium→high 로 뛰어 고치려던 세탁을 다른 표면에 재생산한다.
- **게이트 판정은 안 움직인다.** `confidence_gate_pass` 가 쓰는 4번째 어휘 사본
  (`backend/helpers/common.py::_normalize_field_source`)은 화이트리스트 6종뿐이라
  `sds_match` 를 이미 `inference`(untrusted)로 접는다 — 이 변경 전후 동일하다.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from report_gen.provenance import (
    SOURCE_ALIASES,
    WEAK_SCORE_MAX,
    canonical_source,
    is_weak_source,
)
from tests.unit._source_probe import source_of

VALIDATION = Path(__file__).resolve().parents[2] / "report_gen" / "validation.py"


def _literal_table(name: str) -> dict:
    """`generate_asil_related_confidence_report` 안의 리터럴 dict 를 AST 로 읽는다."""
    import report_gen.validation as validation

    source = source_of(validation.generate_asil_related_confidence_report)
    match = re.search(rf"    {name} = (\{{.*?\n    \}})\n", source, re.S)
    assert match, f"{name} 리터럴 표를 못 찾았다 — 구조가 바뀌었으면 이 헬퍼부터 고칠 것"
    return ast.literal_eval(match.group(1))


class TestSdsMatchIsItsOwnLabel:
    def test_not_an_alias_of_sds(self):
        assert "sds_match" not in SOURCE_ALIASES, (
            "`sds_match` 가 다시 별칭이 됐다 — 그러면 '설명이 SDS 유래가 아니다' 는 라벨이 "
            "SDS 급 점수를 받는다"
        )
        assert canonical_source("sds_match") == "sds_match"

    def test_has_its_own_label_and_score(self):
        labels, scores = _literal_table("src_labels"), _literal_table("src_score")
        assert "sds_match" in labels, "라벨이 없으면 `_norm_src` 가 `unknown`(0.30)으로 접는다"
        assert "sds_match" in scores

    def test_score_is_strictly_below_sds(self):
        scores = _literal_table("src_score")
        assert scores["sds_match"] < scores["sds"], (
            f"sds_match({scores['sds_match']}) 가 sds({scores['sds']}) 와 같거나 높다 — "
            "설명이 SDS 에서 오지 않았는데 SDS 급 신용이다"
        )

    def test_score_stays_above_the_weak_boundary(self):
        """0.75 이하로 내리면 **덮어쓰기 경로가 열린다** — 다른 종류의 변경이다."""
        scores = _literal_table("src_score")
        assert scores["sds_match"] > WEAK_SCORE_MAX, (
            f"sds_match({scores['sds_match']}) 가 WEAK_SCORE_MAX({WEAK_SCORE_MAX}) 이하다 — "
            "is_weak_source() 가 True 가 되어 RAG·AI·HSIS 덮어쓰기 3경로가 새로 열린다. "
            "그건 점수 정직화가 아니라 산출물 내용 변경이므로 별도 측정·결정이 필요하다"
        )

    def test_still_classified_as_strong_so_overwrite_paths_do_not_open(self):
        assert is_weak_source("sds_match") is False

    def test_label_text_says_the_description_is_not_from_sds(self):
        """라벨 문구가 뜻을 말해야 리뷰어가 표를 오독하지 않는다."""
        labels = _literal_table("src_labels")
        text = labels["sds_match"]
        assert "SDS" in text and ("아님" in text or "아니" in text), (
            f"라벨 문구 {text!r} 가 '설명은 SDS 유래가 아니다' 를 말하지 않는다"
        )


class TestCanonicalDocCountingExcludesIt:
    def test_desc_canonical_doc_set_does_not_contain_sds_match(self):
        """'정본 문서 근거' 계상에서 빠져야 한다.

        예전엔 별칭으로 `sds` 가 되어 이 집합에 **들어갔다** — 실측 2,184행이
        "문서 근거" 로 계상됐는데 코드가 명시적으로 문서 유래가 아니라고 적은 행이다.
        """
        source = VALIDATION.read_text(encoding="utf-8")
        assert 'if ds in {"sds", "comment", "reference"}:' in source, (
            "desc_canonical_doc 판정 집합의 모양이 바뀌었다 — 이 테스트를 갱신할 것"
        )
        # 별칭이 없으므로 `_norm_src("sds_match")` 는 `sds_match` 이고 집합에 없다.
        assert canonical_source("sds_match") not in {"sds", "comment", "reference"}


class TestEvidenceTextIsNotBorrowedFromSds:
    def test_evidence_for_has_a_dedicated_branch(self):
        source = VALIDATION.read_text(encoding="utf-8")
        assert 'if src == "sds_match":' in source, (
            "`_evidence_for` 에 전용 분기가 없다 — 별칭이던 시절엔 sds 의 "
            "'SDS 매핑 규칙에 의해 보강됨' 문구를 그대로 받았고 그건 거짓 근거였다"
        )


class TestLegendIsDerivedNotHardcoded:
    def test_source_categories_line_comes_from_src_labels(self):
        """범례를 하드코딩하면 새 라벨이 표엔 찍히는데 범례엔 없다."""
        source = VALIDATION.read_text(encoding="utf-8")
        assert 'src_labels.values()' in source, (
            "범례 줄이 `src_labels` 에서 파생되지 않는다 — 라벨을 추가해도 범례가 안 따라온다"
        )


class TestGateVocabularyIsUnaffected:
    """게이트가 쓰는 4번째 어휘 사본은 이 변경과 **무관**하다 — 값으로 고정한다."""

    @pytest.mark.parametrize("label", ["sds_match", "sds"])
    def test_gate_normalizer_behaviour_is_unchanged(self, label):
        from backend.helpers.common import _normalize_field_source

        expected = "sds" if label == "sds" else "inference"
        assert _normalize_field_source(label) == expected, (
            "게이트 어휘가 바뀌었다 — 그러면 confidence_gate_pass 판정이 움직이므로 "
            "후보 20 의 '게이트 이동 없음' 주장을 다시 재야 한다"
        )
