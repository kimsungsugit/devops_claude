"""UDS 게이트는 **문서를 만든 값**을 잰다 — 빌더의 보강본이 payload 사이드카로 되돌아온다 (R47 N27, 2026-09-10).

## 왜 생겼나

N25 로 참조 SwUDS 배선을 이은 뒤 라이브 run 2063: `gen_stats.reference_suds.safety_fields_applied` 710,
산출 DOCX 를 되읽으면 ASIL 기재 **82.8%**. 그런데 게이트는 그대로 **23.8%** 였다. 참조 보강은 서브프로세스
안의 `function_details` 에 일어나고, 게이트가 읽는 `<out>.payload.json` 은 부모가 **보강 전** 객체로 썼기
때문이다(머리글: "Scored fields source: payload — 파서 값이며 문서 셀과 다를 수 있다"). 게이트가 문서가
아니라 타이핑을 재고 있었다(`feedback_gate_judges_the_document_not_the_typing`).

## 이 파일이 고정하는 것

1. 빌더가 `<out>.docx.function_details.json` 에 보강 후 `function_details` 를 남긴다(키 = payload 키).
2. 부모의 두 트윈(`_uds_generate_from_paths` · jenkins `_write_uds_payload_sidecar`)이 그 파일을 **먼저 병합**하고
   `enrichment` 기록을 payload 에 싣는다. 부재는 `applied:false` + 사유(침묵 아님).
3. 관측량: 보강본에서 ASIL 이 채워지면 `.quality_gate.md` 의 `ASIL non-TBD` 가 그 값을 센다.

뮤테이션(2026-09-10): 병합 호출을 지우면 3 이, 빌더 기록을 지우면 1·3 이 죽는다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("docx")

from tests.unit.test_validation_report_roundtrip import _payload, _template  # noqa: E402


def _generate(tmp: Path) -> tuple[Path, dict]:
    from report_gen.docx_builder import generate_uds_docx

    tpl = _template(tmp / "(KJPDS02_SwUDS) tpl.docx")
    out = tmp / "out.docx"
    pay = _payload("keep")
    pay["function_details"]["SwUFn_001"]["asil"] = "TBD"
    pay["function_details"]["SwUFn_001"]["related"] = "TBD"
    generate_uds_docx(str(tpl), pay, str(out))
    return out, pay


class TestBuilderLeavesTheEnrichedDetails:

    def test_sidecar_exists_with_the_same_keys_as_the_payload(self, tmp_path):
        from report_gen.docx_builder import enriched_function_details_path

        out, pay = _generate(tmp_path)
        p = enriched_function_details_path(str(out))
        assert p.is_file(), p
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data["source"] == "docx_builder"
        assert set(data["function_details"]) == set(pay["function_details"])
        assert isinstance(data["reference_suds"], dict) and "identity" in data["reference_suds"]

    def test_path_is_a_sibling_next_to_gen_stats(self):
        from report_gen.docx_builder import enriched_function_details_path, gen_stats_path

        out = "X:/o/spec.docx"
        assert enriched_function_details_path(out).parent == gen_stats_path(out).parent
        assert enriched_function_details_path(out).name == "spec.docx.function_details.json"


class TestParentMergesBeforeWritingThePayload:

    def _enriched(self, out: Path, **fields) -> Path:
        from report_gen.docx_builder import enriched_function_details_path

        p = enriched_function_details_path(str(out))
        p.write_text(json.dumps({
            "source": "docx_builder",
            "reference_suds": {"identity": {"same_project": True}, "safety_fields_applied": 1},
            "function_details": {"SwUFn_001": {"name": "alpha", **fields}},
        }, ensure_ascii=False), encoding="utf-8")
        return p

    def test_merge_updates_in_place_and_reports_counts(self, tmp_path):
        from backend.helpers.uds import merge_enriched_function_details

        out = tmp_path / "out.docx"
        self._enriched(out, asil="A", asil_source="reference", related="SwFn_01")
        details = {"SwUFn_001": {"name": "alpha", "asil": "TBD", "related": "TBD", "logic": "keep me"},
                   "SwUFn_002": {"name": "bravo", "asil": "TBD"}}
        info = merge_enriched_function_details(out, details)
        assert info["applied"] is True and info["functions"] == 1
        assert details["SwUFn_001"]["asil"] == "A" and details["SwUFn_001"]["related"] == "SwFn_01"
        assert details["SwUFn_001"]["logic"] == "keep me"           # 없는 키는 지우지 않는다
        assert details["SwUFn_002"]["asil"] == "TBD"                # 보강본에 없는 함수는 그대로
        assert info["reference_suds"]["safety_fields_applied"] == 1

    def test_absent_sidecar_is_reported_not_silent(self, tmp_path):
        from backend.helpers.uds import merge_enriched_function_details

        details = {"SwUFn_001": {"asil": "TBD"}}
        info = merge_enriched_function_details(tmp_path / "out.docx", details)
        assert info["applied"] is False and "남기지 않음" in info["reason"]
        assert details["SwUFn_001"]["asil"] == "TBD"

    def test_unreadable_sidecar_is_reported(self, tmp_path):
        from backend.helpers.uds import merge_enriched_function_details
        from report_gen.docx_builder import enriched_function_details_path

        out = tmp_path / "out.docx"
        enriched_function_details_path(str(out)).write_text("{not json", encoding="utf-8")
        info = merge_enriched_function_details(out, {"SwUFn_001": {}})
        assert info["applied"] is False and "읽기 실패" in info["reason"]

    def test_jenkins_sidecar_writer_merges_and_records(self, tmp_path):
        from backend.routers.jenkins import _write_uds_payload_sidecar

        out = tmp_path / "out.docx"
        self._enriched(out, asil="B")
        payload = {"function_details": {"SwUFn_001": {"name": "alpha", "asil": "TBD"}}}
        sidecar = _write_uds_payload_sidecar(out, payload)
        data = json.loads(Path(sidecar).read_text(encoding="utf-8"))
        assert data["function_details"]["SwUFn_001"]["asil"] == "B"
        assert data["enrichment"]["applied"] is True and data["enrichment"]["functions"] == 1

    def test_both_twins_call_the_merge(self):
        from backend.helpers import uds as U
        from backend.routers import jenkins
        from tests.unit._source_probe import source_of

        assert "merge_enriched_function_details(out_path" in source_of(U._uds_generate_from_paths)
        assert "merge_enriched_function_details(out_path" in source_of(jenkins._write_uds_payload_sidecar)
        # 병합은 매핑 요약·사이드카보다 **앞**이어야 한다 — 뒤면 요약이 보강 전 값을 센다.
        src = source_of(U._uds_generate_from_paths)
        assert src.index("merge_enriched_function_details(") < src.index("_compute_uds_mapping_summary(")


class TestTheGateCountsWhatTheDocumentGot:

    def test_gate_sees_the_enriched_asil(self, tmp_path):
        """관측량 — 보강본에 ASIL 이 채워지면 게이트의 `ASIL non-TBD` 가 1/1 이고, 머리글이 '되쓴 값' 이라 말한다."""
        from backend.routers.jenkins import _write_uds_payload_sidecar
        from report_gen.docx_builder import enriched_function_details_path
        from report_gen.validation import generate_uds_field_quality_gate_report

        out, pay = _generate(tmp_path)
        # 대조군: 빌더가 남긴 보강본(기본 참조는 신원 불일치라 ASIL 은 여전히 TBD)으로 게이트를 돌리면 0/1.
        _write_uds_payload_sidecar(out, pay)
        gate = out.with_suffix(".quality_gate.md")
        generate_uds_field_quality_gate_report(str(out), str(gate))
        before = gate.read_text(encoding="utf-8")
        assert "- ASIL non-TBD: `0` / `1`" in before, before[:1500]

        # 보강본이 ASIL 을 채웠다고 하자(N25 배선 후의 실제 상태) → 부모가 병합 → 게이트가 그 값을 센다.
        p = enriched_function_details_path(str(out))
        data = json.loads(p.read_text(encoding="utf-8"))
        data["function_details"]["SwUFn_001"]["asil"] = "A"
        data["function_details"]["SwUFn_001"]["asil_source"] = "reference"
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        _write_uds_payload_sidecar(out, pay)
        generate_uds_field_quality_gate_report(str(out), str(gate))
        after = gate.read_text(encoding="utf-8")
        assert "- ASIL non-TBD: `1` / `1`" in after, after[:1500]
        assert "빌더가 되쓴 값(참조 SwUDS 보강 반영 `1` 함수)" in after

    def test_gate_says_so_when_the_builder_left_nothing(self, tmp_path):
        from backend.routers.jenkins import _write_uds_payload_sidecar
        from report_gen.docx_builder import enriched_function_details_path
        from report_gen.validation import generate_uds_field_quality_gate_report

        out, pay = _generate(tmp_path)
        enriched_function_details_path(str(out)).unlink()
        _write_uds_payload_sidecar(out, pay)
        gate = out.with_suffix(".quality_gate.md")
        generate_uds_field_quality_gate_report(str(out), str(gate))
        text = gate.read_text(encoding="utf-8")
        assert "보강 미반영(사유: 빌더가 보강본을 남기지 않음" in text
