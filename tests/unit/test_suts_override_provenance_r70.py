"""R70 (N83 · N88) — SUTS 의 안전 등급 근거는 값을 준 단계가 말하고, Jenkins 라우터는 프론트가 보낸 문서를 버리지 않는다.

N83: `docs/uds_function_swcom_override.json`(정본 역추출 스냅샷, 프로젝트 확인 없음)이 준 등급을 SUTS 가 소스 `@asil`
     로 표시했다 — `collect_unit_functions` 의 근거 표지가 `asil` 진리값만 봤다(KJPDS02 실측 228 unit). 스냅샷에만 있고
     소스에 없는 함수의 자리표시 엔트리는 라벨을 아예 안 적었다.
N88: `/api/jenkins/suts/generate-async` 는 프론트가 보내는 `srs_path/sds_path/uds_path/hsis_path` 를 선언하지 않아
     FastAPI 가 조용히 버렸고, `source_root` 도 첫 루트만 넘겼다(UDS `reference_doc_path` 와 같은 결함 유형).
"""
from __future__ import annotations

import inspect
import json
import threading
import time
from pathlib import Path

import pytest

import generators.suts as suts_mod
from generators.suts import (
    _override_only_entry,
    collect_unit_functions,
    generate_suts_quality_report,
    supplement_override_only,
)

REPO = Path(__file__).resolve().parents[2]


def _details(**kw):
    return {"SwUFn_0101": {
        "id": "SwUFn_0101", "name": "Fn_Under_Test",
        "prototype": "void Fn_Under_Test(void)",
        "inputs": [], "outputs": [], "globals_global": [], "globals_static": [], "logic_flow": [],
        **kw,
    }}


# ─── 1. 자리표시 엔트리 ──────────────────────────────────────────────────────────

class TestOverrideOnlyEntry:
    def test_labels_name_the_snapshot(self):
        e = _override_only_entry("Ghost_Fn", {"asil": "A", "related": "SwCom_03", "swcom": 3}, "SwUFn_0399")
        assert (e["asil"], e["asil_source"]) == ("A", "override")
        assert (e["related"], e["related_source"]) == ("SwCom_03", "override")
        assert e["override_only"] is True
        assert e["file"] == "" and e["module_name"] == "SwCom_03"

    def test_missing_values_are_tbd_with_default_not_override(self):
        """스냅샷에 `asil: null` 인 항목이 1건 있다 — 값이 없으면 근거도 없다(`default`), `override` 라 적지 않는다."""
        e = _override_only_entry("Ghost_Fn", {"asil": None, "related": None, "swcom": 1}, "SwUFn_0199")
        assert (e["asil"], e["asil_source"]) == ("TBD", "default")
        assert (e["related"], e["related_source"]) == ("TBD", "default")
        assert e["description_source"] == "default"

    def test_vocabulary_is_the_shared_one(self):
        """라벨 철자는 UDS 소스 단계와 같은 어휘(`report_gen.provenance`)다 — 다른 철자면 점수표에서 `unknown` 이 된다."""
        from report_gen.provenance import WEAK_SOURCES, unrecorded_source

        e = _override_only_entry("Ghost_Fn", {"asil": "QM", "swcom": 2}, "SwUFn_0299")
        assert e["asil_source"] in WEAK_SOURCES
        assert e["related_source"] == unrecorded_source("TBD")


class TestSupplement:
    """보충은 생성기와 준비 게이트가 **같은 함수**로 한다(리뷰 W1) — 인라인 시절엔 게이트만 보충을 안 타서 스냅샷 전용 unit 이
    구조적으로 0 이었다."""

    def test_adds_placeholders_for_snapshot_only_names_and_reports_stats(self, tmp_path, monkeypatch):
        ovr = tmp_path / "o.json"
        ovr.write_text(json.dumps({"Seen_Fn": {"asil": "A", "related": "SwCom_01", "swcom": 1},
                                   "Ghost_A": {"asil": "QM", "related": "SwCom_03", "swcom": 3},
                                   "ghost_b": {"asil": None, "swcom": 3}}), encoding="utf-8")
        monkeypatch.setattr(suts_mod, "_OVERRIDE_JSON_CANDIDATES", (ovr,))
        fd = {"SwUFn_0101": {"name": "seen_fn", "asil": "A"}}
        st = supplement_override_only(fd)
        assert st["found"] and st["list_size"] == 3 and st["source"] == 1
        assert st["in_list"] == 1, "이름 대조는 대소문자 무시(소스 `seen_fn` ↔ 목록 `Seen_Fn`)"
        assert st["added"] == 2 and st["added_names"] == ["Ghost_A", "ghost_b"]
        assert set(fd) == {"SwUFn_0101", "SwUFn_0399", "SwUFn_0398"}, "id 는 인라인 판과 같은 규칙(SwUFn_{swcom}{99-n})"
        assert fd["SwUFn_0399"]["override_only"] and fd["SwUFn_0399"]["asil_source"] == "override"
        assert fd["SwUFn_0398"]["asil_source"] == "default"
        assert supplement_override_only(fd)["added"] == 0, "두 번 불러도 다시 보충하지 않는다"

    def test_placeholder_ids_never_overwrite_a_real_function(self, tmp_path, monkeypatch):
        """(N89) 함수 99개 이상인 모듈은 `SwUFn_1399`·`SwUFn_1398` 이 실 함수다 — 옛 식은 그 자리에 자리표시를 덮어써
        라이브 5개(`s_Ap_PreviousCtrl_ResetFlags` 등)를 SUTS 에서 지웠다. 빈 번호로 비켜 선다."""
        ovr = tmp_path / "o.json"
        ovr.write_text(json.dumps({"Ghost_A": {"asil": "A", "swcom": 13}, "Ghost_B": {"asil": "A", "swcom": 13}}),
                       encoding="utf-8")
        monkeypatch.setattr(suts_mod, "_OVERRIDE_JSON_CANDIDATES", (ovr,))
        fd = {"SwUFn_1399": {"name": "Real_99", "asil": "A"}, "SwUFn_1398": {"name": "Real_98", "asil": "A"}}
        st = supplement_override_only(fd)
        assert st["added"] == 2
        assert fd["SwUFn_1399"]["name"] == "Real_99" and fd["SwUFn_1398"]["name"] == "Real_98", "실 함수가 덮였다"
        assert len(fd) == 4, "보충은 더하기만 한다(소스 2 + 자리표시 2)"
        ghosts = {v["name"]: k for k, v in fd.items() if v.get("override_only")}
        assert set(ghosts) == {"Ghost_A", "Ghost_B"} and ghosts["Ghost_A"] == "SwUFn_1397" and ghosts["Ghost_B"] == "SwUFn_1396"

    def test_source_function_count_excludes_placeholders(self):
        """품질 리포트 분모는 소스 함수 수다 — 자리표시가 섞이면 KJPDS02 가 79.5%(게이트 80 미달)로 떨어진다."""
        from generators.suts import _source_function_count

        fd = {"a": {"name": "a"}, "b": {"name": "b", "override_only": True}, "c": "garbage"}
        assert _source_function_count(fd) == 1
        src = (REPO / "generators" / "suts.py").read_text(encoding="utf-8")
        assert "generate_suts_quality_report(units, all_sequences, _source_function_count(function_details))" in src, \
            "생성기 호출부가 자리표시를 뺀 분모를 쓰지 않는다"

    def test_missing_snapshot_file_is_reported_not_silent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(suts_mod, "_OVERRIDE_JSON_CANDIDATES", (tmp_path / "none.json",))
        fd = {"SwUFn_0101": {"name": "f"}}
        st = supplement_override_only(fd)
        assert st["found"] is False and st["added"] == 0 and set(fd) == {"SwUFn_0101"}

    def test_broken_snapshot_raises_for_the_caller_to_log(self, tmp_path, monkeypatch):
        """예전엔 `except Exception: pass` 가 보충 전체를 조용히 지웠다(리뷰 W3) — 이제 호출부가 사유를 남긴다."""
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(suts_mod, "_OVERRIDE_JSON_CANDIDATES", (bad,))
        with pytest.raises(ValueError):
            supplement_override_only({"SwUFn_0101": {"name": "f"}})

    def test_repo_snapshot_is_the_production_input(self):
        """저장소의 실제 스냅샷으로 한 번 — 함수 0개 소스면 목록 크기만큼 보충된다(현 251)."""
        fd: dict = {}
        st = supplement_override_only(fd)
        assert st["found"] and st["added"] == st["list_size"] == len(fd) >= 200


class TestMeasureParity:
    """준비 게이트 측정(`docgen_test_materials.measure`)이 생성기와 같은 unit 목록·같은 SwUDS 표로 잰다."""

    def _run(self, monkeypatch, uds_path="", uds_map=None):
        import report_generator as _rg
        from backend.services import docgen_test_materials as tm
        from backend.services import resolver_helpers as rh
        from generators import uds_unit_io as uio

        monkeypatch.setattr(_rg, "generate_uds_source_sections", lambda root: {
            "function_details": {"SwUFn_0101": {"id": "SwUFn_0101", "name": "Fn_Under_Test",
                                                "prototype": "void Fn_Under_Test(void)", "asil": "A",
                                                "asil_source": "override", "inputs": [], "outputs": [],
                                                "globals_global": [], "globals_static": [], "logic_flow": []}},
            "globals_info_map": {}})
        monkeypatch.setattr(tm, "_load_sds_map", lambda p: ({}, ""))
        monkeypatch.setattr(tm, "_measure_sits", lambda *a, **k: {})
        monkeypatch.setattr(tm, "_measure_sts_mapping", lambda *a, **k: {})
        monkeypatch.setattr(tm, "_measure_suts_types", lambda *a, **k: {})
        monkeypatch.setattr(rh, "resolve_builder_input", lambda p, **k: "local-copy" if p else None)
        monkeypatch.setattr(uio, "load_uds_unit_io", lambda p: uds_map)
        tm.clear_cache()
        try:
            return tm.measure("C:/src", uds_path=uds_path)
        finally:
            tm.clear_cache()

    def test_gate_sees_the_snapshot_only_units(self, monkeypatch):
        res = self._run(monkeypatch)
        a = res["suts_asil"]
        assert a["override_only_units"] >= 200, a
        assert a["override"] >= 1, "SwUDS 표 없이 재면 override 가 준 등급은 `override`(약함)로 잡힌다"
        assert a["uds_map"] is False
        assert a["units"] >= 201, "근거 축은 보충된 전체 목록을 본다"
        si = res["suts_inputs"]
        assert si["units"] == 1 and si["snapshot_only_excluded"] == a["override_only_units"], \
            "입력 축은 스냅샷 전용 unit 을 빼고 센다(입력 없음이 구조적이라 기준선 비교를 깨뜨린다) — 뺀 수는 공시"
        assert si["units_without_input"] == 1 and si["causes"] == {"no_params_no_globals": 1}, \
            "소스 함수 1개만 센다 — 스냅샷 전용 251개가 섞이면 이 사유가 252 로 부푼다"
        assert res["functions"] == 1, "함수 수 자체는 소스 파싱 결과다(보충은 SUTS 축에만)"

    def test_gate_uses_the_uds_table_like_the_generator(self, monkeypatch):
        ovr = json.loads((REPO / "docs" / "uds_function_swcom_override.json").read_text(encoding="utf-8"))
        n_null = sum(1 for v in ovr.values() if not (v or {}).get("asil"))
        without = self._run(monkeypatch)["suts_asil"]
        m = {"by_name": {"Fn_Under_Test": {"inputs": [], "outputs": [], "asil": "A"}}}
        res = self._run(monkeypatch, uds_path="U:/x/SwUDS.docx", uds_map=m)
        a = res["suts_asil"]
        assert a["uds_map"] is True
        # 소스 함수 1개는 uds+override(표가 결정) → 약함으로 세지 않는다. 남는 override 는 등급 있는 스냅샷 전용 unit 뿐.
        assert a["override"] == a["override_only_units"] - n_null
        assert without["override"] == a["override"] + 1, "표 없이 재면 같은 소스 함수가 override(약함)로 한 건 더 잡힌다"


class TestMaterializeIsAtomic:
    """(리뷰 W2) cloudium 문서 실체화는 임시 이름에 쓰고 원자 교체한다 — 생성 워커가 여는 도중 준비 게이트가 같은 파일을
    덮어쓰면 50MB SwUDS 가 잘린 바이트가 됐다."""

    def _resolve(self, tmp_path, monkeypatch, data=b"docx-bytes"):
        import os

        from backend.services import resolver_helpers as rh

        calls: list = []
        real_replace = os.replace

        def _spy(src, dst):
            calls.append((str(src), str(dst)))
            return real_replace(src, dst)

        class _Res:
            def exists(self, p):
                return True

            def read_bytes(self, p):
                return data

        monkeypatch.setattr(rh, "_needs_resolver_read", lambda: True)
        monkeypatch.setattr(rh, "enforce_resolver_access", lambda raw: None)
        monkeypatch.setattr(rh, "_materialize_root", lambda: tmp_path)
        import backend.services.file_resolver as fr
        monkeypatch.setattr(fr, "get_resolver", lambda: _Res())
        monkeypatch.setattr(rh.os, "replace", _spy)
        out = rh.resolve_builder_input("U:/docs/(X_SwUDS) Spec_v1.docx", label="SwUDS")
        return out, calls

    def test_writes_a_part_file_then_replaces(self, tmp_path, monkeypatch):
        out, calls = self._resolve(tmp_path, monkeypatch)
        assert out and Path(out).name == "(X_SwUDS) Spec_v1.docx", "파일명은 유지된다(문서 종류 판정에 쓴다)"
        assert Path(out).read_bytes() == b"docx-bytes"
        assert calls and calls[-1][0].endswith(".part") and calls[-1][1] == out, calls
        assert not list(Path(out).parent.glob("*.part")), "임시본이 남았다"

    def test_second_materialization_replaces_cleanly(self, tmp_path, monkeypatch):
        out1, _ = self._resolve(tmp_path, monkeypatch, data=b"v1")
        out2, _ = self._resolve(tmp_path, monkeypatch, data=b"v2")
        assert out1 == out2 and Path(out2).read_bytes() == b"v2"
        assert not list(Path(out2).parent.glob("*.part"))


class TestCacheSchemaMoved:
    def test_schema_version_is_at_least_v24(self):
        """(N84) 폴백 루프의 `related`/`related_source` 는 캐시 payload 안에 있다 — 버전을 안 올리면 소스가 안 바뀐 프로젝트에서
        옛 사슬의 값이 캐시 수명 동안 그대로 나온다(R68 의 v23 과 같은 실패 모드, 뮤테이션 M3)."""
        from backend.helpers.uds import _SOURCE_SECTIONS_SCHEMA_VERSION

        assert int(_SOURCE_SECTIONS_SCHEMA_VERSION.lstrip("v")) >= 24


# ─── 2. 근거 표지 ───────────────────────────────────────────────────────────────

class TestAsilEvidence:
    def test_override_supplied_grade_is_not_called_source(self):
        d = _details(asil="A", asil_source="override")
        u = collect_unit_functions(d, sds_map={})[0]
        assert u["asil"] == "A"
        assert u["asil_evidence"] == "override", u["asil_evidence"]

    def test_comment_supplied_grade_is_source(self):
        d = _details(asil="A", asil_source="comment")
        assert collect_unit_functions(d, sds_map={})[0]["asil_evidence"] == "source"

    def test_unlabelled_grade_stays_source_for_old_payloads(self):
        """R68 이전 캐시 payload(라벨 없음)는 종전대로 `source` — 라벨이 없다고 근거를 지어내지 않는다."""
        d = _details(asil="B")
        assert collect_unit_functions(d, sds_map={})[0]["asil_evidence"] == "source"

    def test_uds_plus_override_when_both_speak(self):
        d = _details(asil="A", asil_source="override")
        m = {"by_name": {"Fn_Under_Test": {"inputs": [], "outputs": [], "asil": "A"}}}
        assert collect_unit_functions(d, sds_map={}, uds_io_map=m)[0]["asil_evidence"] == "uds+override"

    def test_conflict_message_names_override(self, caplog):
        import logging

        d = _details(asil="QM", asil_source="override")
        m = {"by_name": {"Fn_Under_Test": {"inputs": [], "outputs": [], "asil": "A"}}}
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            u = collect_unit_functions(d, sds_map={}, uds_io_map=m)[0]
        assert u["asil"] == "A", "max 규칙은 그대로다"
        assert any("override QM vs UDS A" in r.getMessage() for r in caplog.records), \
            [r.getMessage()[:200] for r in caplog.records]

    def test_override_only_flag_travels_to_the_unit(self):
        d = {"SwUFn_0399": _override_only_entry("Ghost_Fn", {"asil": "A", "swcom": 3}, "SwUFn_0399")}
        u = collect_unit_functions(d, sds_map={})[0]
        assert u["override_only"] is True and u["asil_evidence"] == "override"
        d2 = _details(asil="A", asil_source="comment")
        assert collect_unit_functions(d2, sds_map={})[0]["override_only"] is False

    def test_summary_log_reports_distribution_and_phantoms(self, caplog):
        import logging

        d = _details(asil="A", asil_source="comment")
        d["SwUFn_0399"] = _override_only_entry("Ghost_Fn", {"asil": "A", "swcom": 3}, "SwUFn_0399")
        with caplog.at_level(logging.INFO, logger="generators.suts"):
            collect_unit_functions(d, sds_map={})
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "ASIL 근거 분포" in text and "override 1" in text and "source 1" in text, text[-600:]
        assert "override 스냅샷 전용 unit 1개" in text and "Ghost_Fn" in text


# ─── 3. 품질 리포트 ─────────────────────────────────────────────────────────────

class TestQualityReport:
    def test_distribution_and_phantom_keys(self):
        units = [
            {"fid": "a", "name": "a", "asil_evidence": "uds", "override_only": False},
            {"fid": "b", "name": "b", "asil_evidence": "override", "override_only": True},
            {"fid": "c", "name": "c", "asil_evidence": "", "override_only": False},
        ]
        q = generate_suts_quality_report(units, {}, 3)
        assert q["asil_evidence_distribution"] == {"uds": 1, "override": 1, "none": 1}
        assert q["override_only_unit_count"] == 1 and q["override_only_units"] == ["b"]

    def test_sample_is_capped_but_count_is_not(self):
        units = [{"fid": str(i), "name": f"g{i}", "asil_evidence": "override", "override_only": True} for i in range(25)]
        q = generate_suts_quality_report(units, {}, 25)
        assert q["override_only_unit_count"] == 25 and len(q["override_only_units"]) == 20

    def test_evaluator_still_accepts_the_report(self):
        from workflow.quality.evaluator import evaluate_suts

        q = generate_suts_quality_report([{"fid": "a", "name": "a", "asil_evidence": "uds"}], {}, 1)
        names = {m["metric_name"] for m in evaluate_suts(q)}
        assert "io_coverage_pct" in names


# ─── 4. 준비 게이트 측정 ─────────────────────────────────────────────────────────

class TestMaterialsMeasure:
    def test_override_alone_is_counted_separately(self):
        from backend.services import docgen_test_materials as tm

        units = [
            {"name": "a", "asil": "A", "asil_evidence": "override"},
            {"name": "b", "asil": "A", "asil_evidence": "uds+override"},
            {"name": "c", "asil": "B", "asil_evidence": "sds-fuzzy"},
            {"name": "d", "asil": "A", "asil_evidence": "override", "override_only": True},
        ]
        res = tm._measure_suts_asil(units)
        assert res["override"] == 2, "uds+override 는 표가 정한 것이라 세지 않는다"
        assert res["override_only_units"] == 1
        assert (res["fuzzy"], res["fuzzy_conflict"]) == (1, 0)
        assert "a" in res["samples"] and "d" in res["samples"]

    def test_clean_when_no_override(self):
        from backend.services import docgen_test_materials as tm

        res = tm._measure_suts_asil([{"name": "a", "asil": "A", "asil_evidence": "source"}])
        assert res["override"] == 0 and res["override_only_units"] == 0


# ─── 5. Jenkins 라우터 배선 (N88) ─────────────────────────────────────────────────

class TestJenkinsRoutePassesTheDocuments:
    """구조 검사는 배선의 **존재**만 본다. 값이 끝까지 가는지는 돌려 봐야 안다(`test_docgen_cap_activation.py` 규약)."""

    def test_form_declares_the_four_documents(self):
        from backend.routers import jenkins as jk

        params = inspect.signature(jk.jenkins_suts_generate_async).parameters
        for name in ("srs_path", "sds_path", "uds_path", "hsis_path"):
            assert name in params, f"프론트가 보내는 `{name}` 을 핸들러가 선언하지 않는다 — FastAPI 가 조용히 버린다"

    def _call(self, tmp_path: Path, monkeypatch, **form):
        from fastapi.testclient import TestClient

        import suts_generator
        from backend.main import app

        seen: dict = {}
        done = threading.Event()

        def _fake(**kwargs):
            seen.update(kwargs)
            done.set()
            return {"output_path": str(tmp_path / "o.xlsm"), "quality_report": {}, "test_case_count": 0,
                    "total_sequences": 0, "elapsed_seconds": 0.1, "validation": {}, "validation_report_path": ""}

        monkeypatch.setattr(suts_generator, "generate_suts", _fake)
        src1 = tmp_path / "src1"
        src1.mkdir()
        (src1 / "a.c").write_text("int f(void){return 0;}", encoding="utf-8")
        src2 = tmp_path / "src2"
        src2.mkdir()
        cache = tmp_path / "cache"
        cache.mkdir()
        body = {"job_url": "http://ci/job/x/", "cache_root": str(cache),
                "source_root": f"{src1},{src2}", **form}
        client = TestClient(app)
        r = client.post("/api/jenkins/suts/generate-async", data=body, headers={"X-User": "tester"})
        assert r.status_code == 200, r.text
        assert done.wait(20), "생성 워커가 시작되지 않았다"
        seen["_job_id"] = r.json().get("job_id")
        seen["_client"] = client
        return seen

    def _result_payload(self, seen) -> dict:
        deadline = time.time() + 10
        while time.time() < deadline:
            d = seen["_client"].get(f"/api/jenkins/suts/progress?job_id={seen['_job_id']}&job_url=http://ci/job/x/",
                                    headers={"X-User": "tester"}).json()
            p = d.get("progress") or d
            if p.get("done"):
                assert not p.get("error"), p
                return p.get("result") or {}
            time.sleep(0.2)
        raise AssertionError("생성 워커가 끝나지 않았다")

    def test_unused_document_reasons_reach_the_result_payload(self, tmp_path, monkeypatch):
        """(리뷰 I1) 못 읽어 뺀 문서의 사유가 로그에만 남으면 사용자는 SwUDS 없는 산출물에도 '생성 완료' 만 본다."""
        seen = self._call(tmp_path, monkeypatch, uds_path=str(tmp_path / "missing_SwUDS.docx"))
        payload = self._result_payload(seen)
        notes = payload.get("input_notes")
        assert notes is None or isinstance(notes, list)
        raw = payload.get("raw_result") or payload
        assert any("파일 없음" in n for n in (raw.get("input_notes") or [])), raw.get("input_notes")

    def test_result_payload_notes_are_empty_when_all_documents_read(self, tmp_path, monkeypatch):
        seen = self._call(tmp_path, monkeypatch)
        raw = (self._result_payload(seen)).get("raw_result") or {}
        assert raw.get("input_notes") == []

    def test_documents_reach_the_generator(self, tmp_path, monkeypatch):
        docs = {}
        for key in ("srs", "sds", "uds", "hsis"):
            p = tmp_path / f"{key}.docx"
            p.write_text(key, encoding="utf-8")
            docs[key] = str(p)
        seen = self._call(tmp_path, monkeypatch, srs_path=docs["srs"], sds_path=docs["sds"],
                          uds_path=docs["uds"], hsis_path=docs["hsis"])
        assert Path(seen["srs_docx_path"]).resolve() == Path(docs["srs"]).resolve()
        assert Path(seen["sds_docx_path"]).resolve() == Path(docs["sds"]).resolve()
        assert Path(seen["uds_path"]).resolve() == Path(docs["uds"]).resolve()
        assert Path(seen["hsis_path"]).resolve() == Path(docs["hsis"]).resolve()

    def test_unset_documents_are_none_not_discovered(self, tmp_path, monkeypatch):
        """안 준 문서는 `None` — 저장소 `docs/` 글롭으로 남의 프로젝트 문서를 끌어오지 않는다."""
        seen = self._call(tmp_path, monkeypatch)
        assert seen["srs_docx_path"] is None and seen["uds_path"] is None and seen["hsis_path"] is None

    def test_every_source_root_reaches_the_generator(self, tmp_path, monkeypatch):
        """예전엔 첫 루트만 넘겼다 — KJPDS02 의 두 번째 루트(PDS128_FBL) 함수가 SUTS 에서 조용히 빠졌다."""
        seen = self._call(tmp_path, monkeypatch)
        assert "src2" in seen["source_root"] and "src1" in seen["source_root"], seen["source_root"]

    def test_unreadable_document_is_dropped_with_a_warning_not_a_500(self, tmp_path, monkeypatch, caplog):
        import logging

        with caplog.at_level(logging.WARNING):
            seen = self._call(tmp_path, monkeypatch, srs_path=str(tmp_path / "missing.docx"))
        assert seen["srs_docx_path"] is None
        assert any("SUTS 선택 문서 미사용" in r.getMessage() for r in caplog.records)
