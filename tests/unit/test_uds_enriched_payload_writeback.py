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

    def test_local_sidecar_writer_merges_and_records_too(self, tmp_path):
        """(R47-c 리뷰 I5) 세 번째 트윈 — 빠뜨리면 보드가 local 산출물을 '병합하지 않는 라이터' 로 보인다."""
        from backend.routers.local import _write_uds_payload_sidecar

        out = tmp_path / "out.docx"
        self._enriched(out, asil="C")
        payload = {"function_details": {"SwUFn_001": {"name": "alpha", "asil": "TBD"}}}
        data = json.loads(Path(_write_uds_payload_sidecar(out, payload)).read_text(encoding="utf-8"))
        assert data["function_details"]["SwUFn_001"]["asil"] == "C"
        assert data["enrichment"]["applied"] is True and data["enrichment"]["functions"] == 1

    def test_all_three_twins_call_the_merge(self):
        from backend.helpers import uds as U
        from backend.routers import jenkins, local
        from tests.unit._source_probe import source_of

        assert "merge_enriched_function_details(out_path" in source_of(U._uds_generate_from_paths)
        assert "merge_enriched_function_details(out_path" in source_of(jenkins._write_uds_payload_sidecar)
        assert "merge_enriched_function_details(out_path" in source_of(local._write_uds_payload_sidecar)
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


class TestParentRecordsEnrichmentInGenStats:
    """(R47-g N28-b) 부모는 payload 를 쓴 **뒤** 같은 `enrichment` 요약을 `<out>.docx.gen_stats.json` 에 병기한다.

    근거 리더가 네 값 때문에 2.7MB payload 를 열던 것을 5KB 통계로 옮긴다. 통계가 없거나 깨졌으면 건드리지
    않는다(리더가 payload 로 폴백 — 느릴 뿐 틀리지 않는다). 순서가 계약이다: payload 기록이 실패하면 병기도 없다.
    """

    def _stats(self, out: Path, **extra) -> Path:
        from report_gen.docx_builder import gen_stats_path

        p = gen_stats_path(str(out))
        p.write_text(json.dumps({"mode": "template", "match_pct": 81.5,
                                 "reference_suds": {"identity": {"same_project": True}, "safety_fields_applied": 1},
                                 **extra}, ensure_ascii=False), encoding="utf-8")
        return p

    def _enriched(self, out: Path, **fields) -> Path:
        from report_gen.docx_builder import enriched_function_details_path

        p = enriched_function_details_path(str(out))
        p.write_text(json.dumps({"source": "docx_builder",
                                 "reference_suds": {"identity": {"same_project": True}, "safety_fields_applied": 1},
                                 "function_details": {"SwUFn_001": {"name": "alpha", **fields}}}), encoding="utf-8")
        return p

    def test_records_the_summary_without_the_nested_reference_and_keeps_builder_keys(self, tmp_path):
        from backend.helpers.uds import record_enrichment_in_gen_stats

        out = tmp_path / "out.docx"
        gs = self._stats(out)
        rec = {"applied": True, "functions": 7, "unknown_keys": 1, "source": "out.docx.function_details.json",
               "reference_suds": {"identity": {"same_project": True}}}
        assert record_enrichment_in_gen_stats(out, rec) is True
        data = json.loads(gs.read_text(encoding="utf-8"))
        assert data["enrichment"] == {"applied": True, "functions": 7, "unknown_keys": 1, "source": "out.docx.function_details.json"}
        assert data["match_pct"] == 81.5 and data["reference_suds"]["safety_fields_applied"] == 1   # 빌더 값 보존
        assert "reference_suds" not in data["enrichment"]                                          # 세 번째 복제 없음

    def test_missing_or_broken_stats_are_left_alone(self, tmp_path):
        from backend.helpers.uds import record_enrichment_in_gen_stats
        from report_gen.docx_builder import gen_stats_path

        out = tmp_path / "out.docx"
        assert record_enrichment_in_gen_stats(out, {"applied": False, "reason": "x"}) is False
        assert not gen_stats_path(str(out)).exists()                     # 없는 통계를 만들어내지 않는다
        gs = gen_stats_path(str(out))
        gs.write_text("{ not json", encoding="utf-8")
        assert record_enrichment_in_gen_stats(out, {"applied": False, "reason": "x"}) is False
        assert gs.read_text(encoding="utf-8") == "{ not json"            # 깨진 통계를 덮어쓰지 않는다
        gs.write_text("[1, 2]", encoding="utf-8")
        assert record_enrichment_in_gen_stats(out, {"applied": False, "reason": "x"}) is False
        assert gs.read_text(encoding="utf-8") == "[1, 2]"
        assert record_enrichment_in_gen_stats(out, {}) is False

    @pytest.mark.parametrize("module_name", ["backend.routers.jenkins", "backend.routers.local"])
    def test_twin_writes_payload_then_the_stats_copy_and_the_reader_no_longer_needs_the_payload(self, tmp_path, module_name):
        import importlib

        from report_gen.evidence import read_evidence

        mod = importlib.import_module(module_name)
        out = tmp_path / "out.docx"
        out.write_bytes(b"PK\x03\x04dummy")
        self._stats(out)
        self._enriched(out, asil="B")
        payload = {"function_details": {"SwUFn_001": {"name": "alpha", "asil": "TBD"}}}
        sidecar = Path(mod._write_uds_payload_sidecar(out, payload))
        pay = json.loads(sidecar.read_text(encoding="utf-8"))
        gs = json.loads((tmp_path / "out.docx.gen_stats.json").read_text(encoding="utf-8"))
        expect = {k: v for k, v in pay["enrichment"].items() if k != "reference_suds"}
        assert gs["enrichment"] == expect and expect["functions"] == 1
        # 관측량: payload 를 지워도 근거의 enrichment 는 그대로 — 리더가 payload 를 열지 않는다는 뜻.
        sidecar.unlink()
        enr = read_evidence(str(out), sections=("reference",))["reference"]["enrichment"]
        assert enr == {"present": True, "applied": True, "functions": 1, "unknown_keys": 0, "reason": None,
                       "record_source": "gen_stats"}

    def test_stats_are_not_touched_when_the_payload_write_fails(self, tmp_path, monkeypatch):
        """순서가 계약 — payload 없이 통계만 '되쓴 값 1 함수' 라 하면 게이트(문서 자기 대조)와 근거가 어긋난다."""
        from backend.routers import jenkins

        out = tmp_path / "out.docx"
        gs = self._stats(out)
        before = gs.read_bytes()
        self._enriched(out, asil="B")

        def _boom(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr(jenkins, "atomic_write_text", _boom)
        assert jenkins._write_uds_payload_sidecar(out, {"function_details": {"SwUFn_001": {"asil": "TBD"}}}) is None
        assert gs.read_bytes() == before

    def test_all_three_twins_record_after_the_atomic_write(self):
        from backend.helpers import uds as U
        from backend.routers import jenkins, local
        from tests.unit._source_probe import source_of

        for fn in (U._uds_generate_from_paths, jenkins._write_uds_payload_sidecar, local._write_uds_payload_sidecar):
            src = source_of(fn)
            assert "record_enrichment_in_gen_stats(out_path" in src, fn.__qualname__
            # (리뷰 I3) 첫 출현 기준이 자명해지지 않게 — 이 함수 안의 원자 기록은 payload 하나뿐이어야 한다.
            assert src.count("atomic_write_text(") == 1, fn.__qualname__
            assert src.index("atomic_write_text(") < src.index("record_enrichment_in_gen_stats("), fn.__qualname__


class TestGateHeaderAppliesTheZeroMergeRule:
    """(R47-h N33) 게이트 md 머리글은 근거 리더와 **같은 판정 함수**로 `enrichment` 를 읽는다.

    R47 리뷰 W3 의 규칙("applied:true · functions:0 · unknown_keys:n>0 = 되쓰기 실패")을 근거 리더만 알았다.
    md 는 `applied` 를 날것으로 읽어 같은 run 을 "되쓴 값 0 함수 · 문서를 만든 값과 같다" 라 적었고 보드는 ⚠ 를
    그렸다 — 한 기록에 두 판정. 관측량은 md 본문이고, 대조군은 근거 API 의 `applied`/`reason` 이다.
    """

    def test_header_calls_zero_merge_a_failure_like_the_evidence_reader(self, tmp_path):
        from backend.routers.jenkins import _write_uds_payload_sidecar
        from report_gen.docx_builder import enriched_function_details_path
        from report_gen.evidence import read_evidence
        from report_gen.validation import generate_uds_field_quality_gate_report

        out, pay = _generate(tmp_path)
        p = enriched_function_details_path(str(out))
        data = json.loads(p.read_text(encoding="utf-8"))
        data["function_details"] = {"SwUFn_999": {"asil": "A"}}          # payload 키와 하나도 안 맞는 보강본
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        sidecar = Path(_write_uds_payload_sidecar(out, pay))
        rec = json.loads(sidecar.read_text(encoding="utf-8"))["enrichment"]
        assert (rec["applied"], rec["functions"], rec["unknown_keys"]) == (True, 0, 1)   # 라이터 기록은 그대로다

        gate = out.with_suffix(".quality_gate.md")
        generate_uds_field_quality_gate_report(str(out), str(gate))
        text = gate.read_text(encoding="utf-8")
        assert "⚠ 보강 미반영(사유: 보강본 키 1건이 payload 함수 키와 하나도 맞지 않아 되쓴 값 없음)" in text, text[:1500]
        assert "빌더가 되쓴 값(참조" not in text
        enr = read_evidence(str(out), sections=("reference",))["reference"]["enrichment"]
        assert enr["applied"] is False and enr["reason"] in text

    @pytest.mark.parametrize("rec, expect_applied", [
        ({"applied": True, "functions": 3, "unknown_keys": 2}, True),
        ({"applied": True, "functions": 0, "unknown_keys": 5}, False),
        ({"applied": True, "functions": 0, "unknown_keys": 0}, True),      # 0/0 은 실패가 아니다 — 대조군
        ({"applied": False, "reason": "보강본 형식이 dict 가 아님"}, False),
        ({"applied": True, "functions": "?", "unknown_keys": 7}, False),   # (리뷰 W1) 정수 아님 = 판정 불가, 성공 아님
        ({"applied": True, "functions": 0, "unknown_keys": None}, False),  # (리뷰 W1) 미기록을 0 으로 접지 않는다
        ({}, False),                                                        # (리뷰 I1) 빈 기록도 기록 — 두 표면 같은 문장
    ])
    def test_header_and_evidence_reader_agree_for_every_record_shape(self, tmp_path, rec, expect_applied):
        """같은 payload 기록을 두 표면이 읽으면 `applied` 판정과 사유가 같고, 그 판정은 기대값과도 같다.

        패리티만 단언하면 공용 규칙이 통째로 틀려도 통과한다(뮤테이션 M3 "0/0 도 실패" 가 살아남았다) — 절대값을 함께 박는다.
        """
        from backend.routers.jenkins import _write_uds_payload_sidecar
        from report_gen.docx_builder import gen_stats_path
        from report_gen.evidence import read_evidence
        from report_gen.validation import generate_uds_field_quality_gate_report

        out, pay = _generate(tmp_path)
        sidecar = Path(_write_uds_payload_sidecar(out, pay))
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        data["enrichment"] = rec
        sidecar.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        gs = gen_stats_path(str(out))
        if gs.is_file():                                                  # 리더가 같은 파일(payload)을 읽게 병기를 지운다
            stats = json.loads(gs.read_text(encoding="utf-8"))
            stats.pop("enrichment", None)
            gs.write_text(json.dumps(stats, ensure_ascii=False), encoding="utf-8")

        gate = out.with_suffix(".quality_gate.md")
        generate_uds_field_quality_gate_report(str(out), str(gate))
        text = gate.read_text(encoding="utf-8")
        enr = read_evidence(str(out), sections=("reference",))["reference"]["enrichment"]
        assert enr["record_source"] == "payload", enr
        says_applied = "빌더가 되쓴 값(참조 SwUDS 보강 반영" in text
        assert says_applied is enr["applied"] is expect_applied, (rec, text[:1500])
        if enr["applied"]:
            assert f"보강 반영 `{enr['functions']}` 함수" in text
        else:
            assert f"⚠ 보강 미반영(사유: {enr['reason']})" in text
