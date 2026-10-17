"""R87 — 세 시험 규격서(STS · SUTS · SITS)의 기본 시험 물량 프로파일은 확장이다(사용자 결정 2026-10-15: "행 수를
넉넉하게 늘려버려 … 정본 변이를 다잡을 수 있으면 그렇게 진행해야지 제한은 안둬도 된다" · "이제 디폴트는 정본 정도가
아니라 확장이야").

세 스위트 한 분모 판정(R86): 정본 규모 문서는 정본이 잡는 변이를 다 잡지 못하고(KJPDS02_PV 163 · HDPDM01 146 — 24 행 안에
들지 못한 탐색 행이 잡는 것), 확장 문서는 다 잡는다(0 · 0). 미설정은 세 문서 모두 확장이고(표에 없는 문서도 확장),
정본 규모는 이름(`reference`)으로 고른다(`generators.tc_profile.DOC_DEFAULT_PROFILE`). 생성기 · 준비 게이트 · 공시가 같은
규칙을 쓴다."""
from __future__ import annotations

import pytest

from generators import suts
from generators.tc_profile import (
    TC_PROFILE_EXTENDED,
    TC_PROFILE_RECOMMENDED,
    TC_PROFILE_REFERENCE,
    default_tc_profile,
    is_evidence_enriched,
    is_extended,
    normalize_tc_profile,
)
from report_gen.generation_disclosures import build_disclosures


@pytest.mark.parametrize("doc_type, want", [("suts", TC_PROFILE_EXTENDED), ("SUTS", TC_PROFILE_EXTENDED),
                                            ("sts", TC_PROFILE_EXTENDED), ("sits", TC_PROFILE_EXTENDED),
                                            ("", TC_PROFILE_EXTENDED), ("uds", TC_PROFILE_EXTENDED)])
def test_each_document_has_its_own_default(doc_type, want):
    assert default_tc_profile(doc_type) == want
    assert normalize_tc_profile("", doc_type) == (want, "")
    assert normalize_tc_profile(None, doc_type) == (want, "")
    # an unknown value goes to the document's default, and is reported
    assert normalize_tc_profile("refrence", doc_type) == (want, "refrence")


def test_a_named_profile_is_taken_as_named_in_every_document():
    for doc_type in ("suts", "sts", "sits", ""):
        for value in (TC_PROFILE_REFERENCE, TC_PROFILE_RECOMMENDED, TC_PROFILE_EXTENDED):
            assert normalize_tc_profile(value, doc_type) == (value, "")


def test_the_predicates_follow_the_document():
    # (R87) 기본은 확장 — 세 문서 모두, 문서 종류 없이도
    for doc_type in ("suts", "sts", "sits", ""):
        assert is_extended("", doc_type) and is_evidence_enriched("", doc_type), doc_type
        assert not is_extended("reference", doc_type) and not is_evidence_enriched("reference", doc_type), doc_type
        assert not is_extended("recommended", doc_type) and is_evidence_enriched("recommended", doc_type), doc_type
    assert is_extended("") and is_evidence_enriched("")


def _src(tmp_path):
    (tmp_path / "m.c").write_text("typedef unsigned char U8;\nU8 g_lim;\nU8 Fn(U8 a)\n{\n    if (a > g_lim) { return 1U; }\n"
                                  "    return 0U;\n}\n", encoding="utf-8")


def test_generate_suts_makes_the_extended_document_by_default(tmp_path):
    _src(tmp_path)
    dflt = suts.generate_suts(source_root=str(tmp_path), output_path=str(tmp_path / "d.xlsm"), scope="source")[
        "quality_report"]
    ref = suts.generate_suts(source_root=str(tmp_path), output_path=str(tmp_path / "r.xlsm"), scope="source",
                             tc_profile="reference")["quality_report"]
    assert dflt["tc_profile"] == TC_PROFILE_EXTENDED and dflt["extended_sequences"] > 0
    assert dflt["caps_effective"] == {"max_sequences": None} and "reference_columns" not in dflt
    assert ref["tc_profile"] == TC_PROFILE_REFERENCE and ref["extended_sequences"] == 0
    assert ref["caps_effective"] == {"max_sequences": 24} and "reference_columns" in ref
    bad = suts.generate_suts(source_root=str(tmp_path), output_path=str(tmp_path / "b.xlsm"), scope="source",
                             tc_profile="extnded")["quality_report"]
    assert bad["tc_profile"] == TC_PROFILE_EXTENDED and bad["tc_profile_unknown_value"] == "extnded"


def _labels(doc_type, qr):
    return {i["key"]: i for i in build_disclosures(doc_type, qr)}


def test_the_disclosure_names_the_default_per_document():
    # (R87) 기본은 확장 — 세 문서 모두, 문서 종류가 없는 보고서도(표에 없는 문서도 확장)
    for doc_type in ("suts", "sts", "sits", ""):
        assert _labels(doc_type, {"tc_profile": "extended"})["tc_profile"]["value"] == "확장(기본)", doc_type
        ref = _labels(doc_type, {"tc_profile": "reference"})["tc_profile"]
        assert ref["value"] == "정본 규모" and "이 문서의 기본은 확장" in ref["note"], doc_type
        bad = _labels(doc_type, {"tc_profile": "extended",
                                 "tc_profile_unknown_value": "x"})["tc_profile_unknown_value"]
        assert "기본(확장)" in bad["note"] and "기본(정본 규모)" not in bad["note"], doc_type
    # SUTS 만 정본 규모가 무엇을 놓치는지 실측으로 말한다
    assert "정본이 잡는 변이를 다 잡지 못한다" in _labels("suts", {"tc_profile": "reference"})["tc_profile"]["note"]


def test_the_impact_draft_takes_the_default_documents_path(monkeypatch):
    # the doc-proposal drafts follow the default document (리뷰 R87 W-R2-2): SUTS picks its generation by the default table
    #   (extended now — R86 was the reference path), STS takes the default's evidence axis
    from tests.unit._source_probe import source_of
    from workflow import impact_orchestrator as io

    src = source_of(io._build_doc_proposal)
    assert '_suts_gen = extended_unit_sequences if is_extended("", "suts") else reference_unit_sequences' in src
    assert "_suts_gen(_unit, _DEFAULT_SEQ_COUNT, type_cache=_local_tc)" in src
    assert '_sts_enrich = is_evidence_enriched("", "sts")' in src and "enrich=_sts_enrich" in src


def test_every_consumer_reads_its_documents_default(monkeypatch, tmp_path):
    # (리뷰 R87 W2) the table exists so a document may default otherwise — every consumer must take the document's default
    #   (a generator call without its doc type would follow the shared fallback instead)
    from generators import sits
    from generators import tc_profile as tp
    from tests.unit.test_tc_profile_r75 import _sts

    monkeypatch.setattr(tp, "DOC_DEFAULT_PROFILE", {"sts": "reference", "suts": "reference", "sits": "reference"})
    monkeypatch.setattr(tp, "TC_PROFILE_DEFAULT", TC_PROFILE_EXTENDED)   # the shared fallback stays extended
    _tcs, stats = _sts("")
    assert stats["tc_profile"] == TC_PROFILE_REFERENCE
    assert not stats.get("expected_enriched"), "the evidence axis follows the same default (sts.py is_evidence_enriched)"
    assert sits.resolve_profile_caps("", 7, 120)[:4] == (TC_PROFILE_REFERENCE, "", 7, 120)
    _src(tmp_path)
    qr = suts.generate_suts(source_root=str(tmp_path), output_path=str(tmp_path / "d.xlsm"), scope="source")[
        "quality_report"]
    assert qr["tc_profile"] == TC_PROFILE_REFERENCE and qr["extended_sequences"] == 0


def test_an_old_documents_unknown_value_is_told_by_its_recorded_profile():
    # (리뷰 R87 W-R3-1) a document made before R87 with a typo was built as 정본 규모 — the note must agree with its label
    items = _labels("suts", {"tc_profile": "reference", "tc_profile_unknown_value": "refrence"})
    assert items["tc_profile"]["value"] == "정본 규모"
    note = items["tc_profile_unknown_value"]["note"]
    assert "기본(정본 규모)" in note and "기본(확장)" not in note and "확장을 원했다면" in note
    new = _labels("suts", {"tc_profile": "extended", "tc_profile_unknown_value": "x"})["tc_profile_unknown_value"]["note"]
    assert "기본(확장)" in new and "정본 규모를 원했다면" in new
