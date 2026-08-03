# tests/unit/test_related_id_no_fabrication.py
"""Related ID 의 **출처를 모양만 보고 지어내지 않는다** (2026-08-03).

## 왜

`backend/helpers/uds.py::_enrich_function_quality_fields` 의 else 분기가 이랬다:

    if _normalize_field_source(related_source) == "inference" and _has_trace_token(related):
        related_source = "rule"

**값은 하나도 안 바꾼다 — 라벨만 바꾼다.** 즉 아무 근거도 새로 보지 않았는데 신뢰도
등급을 옮긴다. 판정 근거는 `related` 값이 `SwFn_\\d+` **모양이라는 것뿐**이다.

`_normalize_field_source` 화이트리스트가 `{comment, sds, srs, reference, rule, inference}`
6종뿐이라 **그 밖의 13종이 전부** 이 조건에 걸렸다:

| 방향 | 라벨 | 점수 이동 |
|---|---|---|
| 하향 | `uds`·`swcom`·`sds_match`·`hsis` | 0.95 → 0.75 |
| 하향 | `rag`·`ai` | 0.85 → 0.75 |
| 하향 | `call_graph` | 0.80 → 0.75 |
| **상향** | `default`·`unknown`·`generated_doc` | **0.30 → 0.75** |
| 상향 | `inference` / `module_inherit` | 0.60 / 0.70 → 0.75 |

`report_gen/validation.py:1391-1393` 이 **같은 패턴을 지우면서** 못박아 뒀다:
*"ID 가 `SwFn_07` 모양이라는 건 SRS 를 참조했다는 증거가 아니라 그냥 문자열 모양이다.
모양으로 출처를 지어내지 않는다."* 계층이 다른 게 아니라 같은 파이프라인이 그 규약을
어긴 것이다.

## 실측 파급

`related_trusted_fill` 0% → **100%**, 사유코드 `RELATED_ID_TRUST_LOW` 소거.
local sync 경로는 enrich(`backend/routers/local.py:1076`)가 신뢰도 리포트(`:1196`)보다
**먼저** 돌아, 납품 사이드카 `.field_confidence.md` 의 저신뢰 공시가 지워졌다.

⚠ 이 결함은 기존 테스트가 **한 건도 덮지 않았다**(196 passed 상태에서 제거해도 무변화).
그래서 살아남았다. 이 파일이 그 구멍이다.

⚠ 판정을 복제하지 않는다 — 프로덕션 함수를 실제로 태운다.
"""
from __future__ import annotations

import pytest

from report_gen.provenance import WEAK_SOURCES


def _enrich(info: dict) -> dict:
    """프로덕션 `_enrich_function_quality_fields` 를 실제로 태운다."""
    from backend.helpers.uds import _enrich_function_quality_fields

    payload = {"function_details": {"F": dict(info)}, "function_details_by_name": {}}
    _enrich_function_quality_fields(payload)
    return payload["function_details"]["F"]


# ---------------------------------------------------------------------------
# 값을 안 바꿨으면 출처도 안 바꾼다
# ---------------------------------------------------------------------------

class TestNoShapeBasedRelabel:
    # 화이트리스트 밖이라 예전에 전부 `rule` 로 덮이던 라벨들.
    RELABELLED = ["generated_doc", "default", "unknown", "inference",
                  "module_inherit", "uds", "swcom", "sds_match", "hsis",
                  "rag", "ai", "call_graph"]

    @pytest.mark.parametrize("src", RELABELLED)
    def test_existing_related_keeps_its_source(self, src):
        """이미 값이 있는 related 는 **출처가 그대로**여야 한다.

        뮤테이션: `uds.py` 의 else 분기를 되살리면 전부 `rule` 이 되어 실패한다.
        """
        out = _enrich({"name": "f", "related": "SwFn_10", "related_source": src})
        assert out["related"] == "SwFn_10", "값은 애초에 안 건드리는 분기다"
        assert out["related_source"] == src, (
            f"아무 근거도 새로 안 봤는데 {src!r} 를 재라벨했다")

    def test_weak_source_is_not_promoted(self):
        """최약체(0.30)가 모양만으로 `rule`(0.75)이 되던 것 — 가장 나쁜 방향."""
        out = _enrich({"name": "f", "related": "SwCom_03, SwFn_25",
                       "related_source": "generated_doc"})
        assert out["related_source"] == "generated_doc"

    def test_strong_source_is_not_demoted(self):
        """반대 방향 — 문서 유래(0.95)가 `rule`(0.75)로 깎이던 것."""
        out = _enrich({"name": "f", "related": "SwFn_07", "related_source": "uds"})
        assert out["related_source"] == "uds"

    def test_source_stays_weak_when_it_was_weak(self):
        """등급 이동을 점수표 대신 **약함 판정**으로도 고정한다(라벨 추가에 견디게)."""
        out = _enrich({"name": "f", "related": "SwFn_10", "related_source": "default"})
        assert out["related_source"] in WEAK_SOURCES


# ---------------------------------------------------------------------------
# 값 축 — 함수 자신의 ID 를 요구 ID 로 개명하던 것
# ---------------------------------------------------------------------------

class TestNoInventedRelatedId:
    """`_infer_related_id_simple` 이 빈 Related ID 를 **지어내던** 경로.

    실측(payload 86개, 2026-08-03): 빈 `related` **5,780건이 전부** 값을 받았고,
    **전부** 함수 자신의 `id` 후보에서 나왔으며 **전부** `SwFn_N` 형태였다.
    즉 `SwUFn_0307`(이 함수 자신의 단위설계 ID)을 `SwFn_0307`(SwDS 설계요소 ID)로
    **개명**해 추적 칸에 넣었다. 번호가 대응한다는 근거는 어디에도 없다.

    실제 `SwUDS v3.02` 의 Related ID 는 SwDS 설계요소 ID 로 1,035/1,035 채워져 있다
    (`docs/plans/UDS_RelatedID_SwFn_보강요청.md` §1). 그래서 개명은 **실재하는
    네임스페이스 안에 근거 없는 ID 를 만들어 넣는 것**이라 문서 유래와 구분되지 않는다.
    """

    def test_own_design_id_does_not_become_a_related_id(self):
        out = _enrich({"name": "f", "id": "SwUFn_0307", "related": "TBD"})
        assert out["related"] == "TBD", "함수 자신의 ID 를 요구 추적으로 둔갑시켰다"
        assert "SwFn_0307" not in str(out.get("related") or "")

    def test_own_id_is_not_a_candidate_even_when_it_looks_like_a_design_id(self):
        """`id` 후보 제거 자체를 고정한다.

        ⚠ 뮤테이션에서 드러났다: `SwUFn_` 을 정규식에서 뺀 뒤로는 `id` 후보를
        되살려도 위 테스트가 안 깨진다(`SwUFn_0307` 이 어느 패턴에도 안 맞아서).
        그래서 **`id` 가 설계 ID 모양인 경우**로 따로 못박는다 — 그때는 함수
        자신의 ID 가 곧바로 자기 Related ID 가 된다.
        """
        from backend.helpers.common import _infer_related_id_simple

        assert _infer_related_id_simple({"id": "SwCom_03", "related": "TBD"}) == ""

    def test_swufn_in_the_related_cell_is_not_renamed(self):
        """Related 칸에 단위함수 ID 가 적혀 있어도 요구 추적이 아니다."""
        from backend.helpers.common import _infer_related_id_simple

        assert _infer_related_id_simple({"related": "SwUFn_42"}) == ""

    def test_non_id_text_is_not_used_as_a_related_id(self):
        """`partition="APP_Layer"` 가 Related ID 가 되던 것."""
        from backend.helpers.common import _infer_related_id_simple

        assert _infer_related_id_simple({"partition": "APP_Layer", "related": ""}) == ""

    def test_later_candidates_are_still_examined(self):
        """⚠ 옛 코드는 첫 후보에서 **무조건 반환**해 뒤 후보를 못 봤다.

        `swcom` 이 ID 가 아니면 거기서 그 원문을 Related ID 로 돌려주고 끝냈다.
        이제 넘어가므로 뒤에 있는 진짜 ID 를 찾아낸다 — 수정이 회수를 **늘리는** 방향.
        """
        from backend.helpers.common import _infer_related_id_simple

        got = _infer_related_id_simple(
            {"swcom": "Motor Control", "partition": "SwCom_07", "related": ""})
        assert got == "SwCom_07"

    @pytest.mark.parametrize("info,expected", [
        ({"related": "SwCom_123"}, "SwCom_123"),
        ({"swcom": "SwCom_09", "related": "TBD"}, "SwCom_09"),
        ({"related": "SwSTR_11"}, "SwSTR_11"),
    ])
    def test_real_design_ids_still_flow(self, info, expected):
        """음성 대조군 — 실제 설계요소 ID 는 계속 채워져야 한다.

        이게 없으면 "아무것도 안 채우게" 과교정한 걸 아무도 못 본다.
        """
        from backend.helpers.common import _infer_related_id_simple

        assert _infer_related_id_simple(info) == expected


# ---------------------------------------------------------------------------
# 지표 축 — 재라벨이 게이트를 통과시키던 것
# ---------------------------------------------------------------------------

class TestQualityGateSeesWeakRelated:
    """`related_trusted_fill` 이 0%→100% 로 뛰며 사유코드를 지우던 것.

    프로덕션 `_compute_quick_quality_gate` + `_derive_quality_reason_codes` 를 태운다.
    """

    @staticmethod
    def _gate(infos):
        from backend.helpers.uds import (
            _compute_quick_quality_gate,
            _derive_quality_reason_codes,
            _enrich_function_quality_fields,
        )

        payload = {
            "function_details": {f"F{i}": dict(v) for i, v in enumerate(infos)},
            "function_details_by_name": {},
        }
        _enrich_function_quality_fields(payload)
        gate = _compute_quick_quality_gate(payload)
        return gate, _derive_quality_reason_codes(gate)

    def test_weak_related_is_not_counted_as_trusted(self):
        rows = [{"name": f"f{i}", "related": f"SwFn_{i:02d}",
                 "related_source": "generated_doc"} for i in range(4)]
        gate, codes = self._gate(rows)
        rate = float((gate.get("rates") or {}).get("related_trusted_fill") or 0.0)
        assert rate < 100.0, (
            f"근거가 최약체인데 신뢰 채움률이 {rate}% 다 — 모양만 보고 신뢰로 셌다")
        assert "RELATED_ID_TRUST_LOW" in codes, "저신뢰 사유코드가 지워졌다"

    def test_real_document_source_still_counts(self):
        """음성 대조군 — 진짜 문서 유래는 계속 신뢰로 세야 한다.

        이게 없으면 "전부 저신뢰로 만들었다" 는 과교정을 아무도 못 본다.
        """
        rows = [{"name": f"f{i}", "related": f"SwFn_{i:02d}",
                 "related_source": "sds"} for i in range(4)]
        gate, codes = self._gate(rows)
        rate = float((gate.get("rates") or {}).get("related_trusted_fill") or 0.0)
        assert rate > 0.0, "실제 SDS 유래까지 저신뢰로 깎였다"
        assert "RELATED_ID_TRUST_LOW" not in codes


# ---------------------------------------------------------------------------
# 산출물 축 — 납품 사이드카에서 저신뢰 공시가 사라지던 것
# ---------------------------------------------------------------------------

def _section(text: str, heading: str) -> str:
    """리포트의 한 섹션만 잘라낸다.

    ⚠ 전문 검색은 못 쓴다 — 머리말의 범례 줄(`Source categories: … / 룰 / …`)이
    항상 모든 라벨명을 담고 있어 무엇을 넣어도 매치된다(처음에 이걸로 틀렸다).
    """
    i = text.find(heading)
    assert i >= 0, f"섹션을 못 찾았다: {heading}"
    j = text.find("\n## ", i + len(heading))
    return text[i: j if j >= 0 else len(text)]


def test_confidence_sidecar_reports_the_real_related_source(tmp_path):
    """local sync 순서(enrich → 신뢰도 리포트)를 그대로 재현한다.

    `backend/routers/local.py` 는 enrich(`:1076`)를 리포트(`:1196`)보다 **먼저**
    돌린다. 그래서 재라벨된 payload 가 채점 대상이 되고, 납품 사이드카
    `.field_confidence.md` 가 **없는 근거**(`룰`)를 인쇄했다.

    ⚠ "저신뢰 목록이 통째로 사라진다" 고는 주장하지 않는다 — 반증에서 재현되지
    않았다. `rule`(0.75)로 올라도 점수는 0.55 라 임계 0.80 미만이라 목록에 남는다.
    확실한 차이는 **인쇄되는 출처 라벨과 점수**다.

    뮤테이션: `uds.py` 의 else 분기를 되살리면 라벨이 `룰` 이 되어 실패한다.
    """
    from backend.helpers.uds import _enrich_function_quality_fields
    from report_gen.validation import generate_asil_related_confidence_report

    payload = {
        "function_details": {
            f"F{i}": {"name": f"f{i}", "asil": "QM", "asil_source": "default",
                      "description": "d", "description_source": "inference",
                      "related": f"SwFn_{i:02d}", "related_source": "generated_doc"}
            for i in range(4)
        },
        "function_details_by_name": {},
    }
    _enrich_function_quality_fields(payload)
    out = tmp_path / "conf.md"
    generate_asil_related_confidence_report(payload, str(out))
    text = out.read_text(encoding="utf-8")

    rel = _section(text, "## Related ID Source")
    assert "생성 문서 회수" in rel, "실제 출처가 리포트에서 사라졌다"
    assert "룰" not in rel, "모양만 보고 붙인 '룰' 이 납품 리포트에 인쇄됐다"

    # 0.30(generated_doc) 이 0.75(rule) 로 올라가면 총점이 0.400 → 0.550 이 된다.
    assert "`0.400`" in text, "약한 근거가 점수를 부풀렸다"
