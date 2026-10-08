r"""(R66) 입력 문서 — 다른 프로젝트 문서로 대체하지 않고, 지정했는데 못 쓴 입력을 공시한다(감사 #1 · #62 · #63 · #83).

## 무엇이 있었나 (R66 실측 — KJPDS02_PV 를 SRS · SwUDS 만 주고 생성)

- 세 생성기가 SDS 를 주지 않았거나 못 읽거나 파티션이 0 이면 저장소 `docs/` 의 SDS(이 저장소에 든 HDPDM01 문서)로 넘어갔다
  (`_load_default_sds_map`). SUTS unit 113 개가 HDPDM01 SDS 의 ASIL 을 받았고(17 개는 PV 자기 SDS 와 등급이 다름), STS 요구-함수
  링크 8,049 개가 HDPDM01 파티션에서 나왔다(요구 ID 는 프로젝트끼리 겹친다 — 114 개는 PV SDS 로는 생기지 않는 링크).
- 라우트도 SRS · SDS 를 주지 않으면 저장소 `docs/` 에서 집었고(`_discover_srs_docx` · `_discover_sds_docx` ·
  `_discover_default_req_docs`), 영향도 재생성은 등록 문서가 로컬에 안 보이면 `_discover_doc` 으로 SRS · SDS · HSIS · STP 를 집었다.
- SUTS 보강 블록은 문서를 못 열면 예외 없이 건너뛰어, 공시가 "보강 실패 0건 — 전부 끝까지 돌았다, 빈 칸은 근거가 없어서" 였다.

이 파일은 (1) 대체 경로가 다시 생기지 않게(구조 + 행동 — SDS 파티션 추출기를 부르면 실패), (2) 입력 문서 기록이 생성기 ·
라우트 · 공시까지 닿는지를 잰다.
"""
from __future__ import annotations

import ast
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from generators import suts as gsuts
from generators.suts import input_documents_record, input_skip_reason, note_input_document
from report_gen.generation_disclosures import build_disclosures

_ROOT = Path(__file__).resolve().parents[2]


def _boom_extractor(monkeypatch) -> list:
    """SDS 파티션 추출기를 부르면 실패 — 주지 않은 SDS 를 어디선가 읽으면(저장소 폴백 재발) 잡는다.

    (리뷰) 호출을 **센다** — 폴백이 넓은 except 안에서 되살아나면 던진 예외는 먹히므로, 호출부가 끝에 `calls == []` 를 단언한다."""
    import report_gen.requirements as rr

    calls: list = []

    def _boom(*a, **_k):
        calls.append(a[:1])
        raise AssertionError("SDS 를 주지 않았는데 파티션 추출기를 불렀다(저장소 docs/ 폴백 재발)")
    monkeypatch.setattr(rr, "_extract_sds_partition_map", _boom)
    monkeypatch.setattr(gsuts, "_extract_sds_partition_map", _boom)
    return calls


# ── 라우트 사유 · 문서 기록 ─────────────────────────────────────────────────────

class TestSkipReason:
    def test_label_is_matched_case_insensitively_and_first_wins(self):
        skips = ["UDS: 접근 거부", "sds: 파일 없음 — 경로가 바뀌었다", "SDS: 둘째"]
        assert input_skip_reason(skips, "SDS") == "파일 없음 — 경로가 바뀌었다"
        assert input_skip_reason(skips, "uds") == "접근 거부"

    @pytest.mark.parametrize("skips", [None, [], ["SDS 파일 없음"], ["SDSX: y"], ["KJ_SwDS.docx: 파일 없음"]])
    def test_no_reason_without_the_label(self, skips):
        """라벨 없이 파일 이름으로 적힌 사유(옛 라우트 형식)는 그 문서의 것으로 추측하지 않는다."""
        assert input_skip_reason(skips, "SDS") == ""

    def test_reason_is_capped(self):
        assert len(input_skip_reason(["SDS: " + "x" * 500], "SDS")) == 200

    @pytest.mark.parametrize("raw,want", [
        ("SDS: 접근 거부 — allowed_prefixes 밖 차단됨: U:\\연구소\\KJ 문서\\(KJ_SwDS) Arch v3.docx (권한)",
         "접근 거부 — allowed_prefixes 밖 차단됨: (KJ_SwDS) Arch v3.docx (권한)"),
        ("SDS: 읽기 실패 (OSError: D:/a/b/c_SwDS.docx)", "읽기 실패 (OSError: c_SwDS.docx)"),
        ("SDS: \\\\server\\share\\x_SwDS.DOCX 없음", "x_SwDS.DOCX 없음"),
        # (리뷰 2차 I1) 경로 뒤 글을 먹지 않는다 · 다음 경로까지 걸치지 않는다 · URL 의 `p:/` 는 경로가 아니다
        ("SDS: U:\\a\\b.docx와 U:\\c\\d.docx 둘 다", "b.docx와 d.docx 둘 다"),
        ("SDS: (OSError: U:\\a\\b) 그리고 C:\\x\\y.docx", "(OSError: b) 그리고 y.docx"),
        ("SDS: http://127.0.0.1:8765/read 실패", "http://127.0.0.1:8765/read 실패"),
    ])
    def test_paths_in_route_reasons_become_file_names(self, raw, want):
        """(리뷰 Info) 라우트 사유는 워커 · 접근 검사 문자열을 담아 경로가 들 수 있다 — 공시까지 가므로 파일 이름만."""
        assert input_skip_reason([raw], "SDS") == want


class TestNoteInputDocument:
    def test_one_failed_block_makes_the_document_unopened(self):
        docs: dict = {}
        note_input_document(docs, "UDS", "C:/d/KJ_SwUDS.docx", "uds_unit_io", {"opened": True})
        note_input_document(docs, "UDS", "C:/d/KJ_SwUDS.docx", "uds_design_id_bridge",
                            {"opened": False, "reason": "읽기 실패 (OSError)"})
        note_input_document(docs, "UDS", "C:/d/KJ_SwUDS.docx", "uds_description_design_ids", {"opened": True})
        rec = docs["UDS"]
        assert rec == {"given": True, "opened": False, "name": "KJ_SwUDS.docx", "reason": "읽기 실패 (OSError)",
                       "blocks_unopened": ["uds_design_id_bridge"]}

    def test_route_skip_without_a_path_is_given_but_unopened(self):
        docs: dict = {}
        note_input_document(docs, "SRS", None, "srs_req_ids", {}, ["SRS: 접근 거부 — 권한"])
        assert docs["SRS"]["given"] is True and docs["SRS"]["opened"] is False
        assert docs["SRS"]["reason"] == "접근 거부 — 권한" and docs["SRS"]["blocks_unopened"] == ["srs_req_ids"]

    def test_not_given_is_not_a_failure(self):
        docs: dict = {}
        note_input_document(docs, "HSIS", "", "hsis_signals", {})
        assert docs["HSIS"] == {"given": False, "opened": False, "name": "", "reason": "", "blocks_unopened": []}


class TestResolvedDocInputReport:
    def test_local_file_is_opened(self, tmp_path):
        f = tmp_path / "a.docx"
        f.write_bytes(b"x")
        rep: dict = {}
        with gsuts._resolved_doc_input(str(f), "SRS", report=rep) as p:
            assert p == str(f)
        assert rep == {"opened": True}

    def test_blank_is_not_opened_and_has_no_reason(self):
        rep: dict = {"opened": True}
        with gsuts._resolved_doc_input("", "SRS", report=rep) as p:
            assert p is None
        assert rep == {"opened": False}

    def test_missing_file_reason_names_the_access_mode(self, monkeypatch):
        import backend.services.file_resolver as fr

        class _Gone:
            mode = "cloudium"
            def is_file(self, p):
                return False
        monkeypatch.setattr(fr, "get_resolver", lambda: _Gone())
        rep: dict = {}
        with gsuts._resolved_doc_input("U:/proj/KJ_SwRS.docx", "SRS", report=rep) as p:
            assert p is None
        assert rep["opened"] is False and rep["reason"].startswith("파일 없음(접근 방식 cloudium)")
        assert "U:/proj" not in rep["reason"], "사유에 경로를 싣지 않는다(파일 이름만 — 경로는 로그에만)"

    def test_read_failure_reason(self, monkeypatch):
        import backend.services.file_resolver as fr

        class _Broken:
            mode = "cloudium"
            def is_file(self, p):
                return True
            def read_bytes(self, p):
                raise TimeoutError("worker")
        monkeypatch.setattr(fr, "get_resolver", lambda: _Broken())
        rep: dict = {}
        with gsuts._resolved_doc_input("U:/x.docx", "UDS", report=rep) as p:
            assert p is None
        assert rep == {"opened": False, "reason": "읽기 실패 (TimeoutError)"}

    def test_no_resolver_reason(self, monkeypatch):
        import backend.services.file_resolver as fr

        def _none():
            raise RuntimeError("backend 없음")
        monkeypatch.setattr(fr, "get_resolver", _none)
        rep: dict = {}
        with gsuts._resolved_doc_input("U:/x.docx", "UDS", report=rep) as p:
            assert p is None
        assert rep["opened"] is False and "resolver" in rep["reason"]


class TestInputDocumentsRecord:
    def test_existing_missing_and_skipped(self, tmp_path):
        f = tmp_path / "KJ_SwRS.docx"
        f.write_bytes(b"x")
        rec = input_documents_record({"SRS": str(f), "UDS": str(tmp_path / "gone.docx"), "STP": None},
                                     ["STP: 접근 거부"])
        assert rec["SRS"]["opened"] is True and rec["SRS"]["name"] == "KJ_SwRS.docx"
        assert rec["UDS"]["given"] is True and rec["UDS"]["opened"] is False and "파일 없음" in rec["UDS"]["reason"]
        assert rec["STP"] == {"given": True, "opened": False, "name": "", "reason": "접근 거부",
                              "blocks_unopened": ["generator_input"]}


# ── 대체 경로가 다시 생기지 않는다(구조) ─────────────────────────────────────────

class TestNoRepoDocsSubstitution:
    @pytest.mark.parametrize("mod", ["suts", "sts", "sits"])
    def test_generators_have_no_repo_docs_fallback(self, mod):
        m = __import__(f"generators.{mod}", fromlist=["x"])
        assert not hasattr(m, "_load_default_sds_map") and not hasattr(m, "_SDS_MAP_CACHE")
        src = (_ROOT / "generators" / f"{mod}.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        globs = [ast.unparse(n)[:100] for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "glob"
                 and n.args and isinstance(n.args[0], ast.Constant) and str(n.args[0].value).endswith(".docx")]
        assert globs == [], f"{mod}: docx 글롭이 생겼다 — 입력 문서는 호출자가 준 것만: {globs}"

    def test_sds_extractor_is_read_in_one_place(self):
        """SDS 파티션은 `read_sds_input` 하나로만 읽는다 — STS · SITS 가 모듈 최상위 import 로 직접 읽으면 행동 가드(패치)를 우회한다."""
        for mod in ("sts", "sits"):
            tree = ast.parse((_ROOT / "generators" / f"{mod}.py").read_text(encoding="utf-8"))
            refs = [n.lineno for n in ast.walk(tree)
                    if (isinstance(n, ast.Name) and n.id == "_extract_sds_partition_map")
                    or (isinstance(n, ast.Attribute) and n.attr == "_extract_sds_partition_map")
                    or (isinstance(n, ast.alias) and n.name == "_extract_sds_partition_map")]
            assert refs == [], (mod, refs)
        tree = ast.parse((_ROOT / "generators" / "suts.py").read_text(encoding="utf-8"))
        owners = {fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
                  for n in ast.walk(fn) if isinstance(n, ast.Name) and n.id == "_extract_sds_partition_map"}
        assert owners == {"read_sds_input"}, owners

    @pytest.mark.parametrize("rel", ["backend/routers/local.py", "backend/routers/jenkins.py"])
    def test_every_route_document_resolution_collects_its_reason(self, rel):
        """(리뷰 W1) 라우트가 문서를 로컬화하는 호출은 사유를 모은다(`reasons=`) — 빠지면 못 연 문서가 생성기에 '주지 않음' 으로 간다.
        템플릿(서식)만 예외."""
        tree = ast.parse((_ROOT / rel).read_text(encoding="utf-8"))
        aliases = {"resolve_builder_input"} | {
            a.asname for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "backend.services.resolver_helpers"
            for a in n.names if a.name == "resolve_builder_input" and a.asname}
        bad = []
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in aliases):
                continue
            label = next((k.value for k in n.keywords if k.arg == "label"), None)
            if isinstance(label, ast.Constant) and label.value == "템플릿":
                continue
            if not any(k.arg == "reasons" for k in n.keywords):
                bad.append(f"{rel}:{n.lineno} {ast.unparse(n)[:80]}")
        assert bad == [], bad

    def test_local_router_has_no_discovery_helpers(self):
        import backend.routers.local as local

        for gone in ("_discover_default_req_docs", "_discover_srs_docx", "_discover_sds_docx", "_discover_hsis_path"):
            assert not hasattr(local, gone), gone

    def test_impact_regeneration_discovers_only_templates(self):
        src = (_ROOT / "workflow" / "impact_orchestrator.py").read_text(encoding="utf-8")
        tokens = [n.args[0].value for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_discover_doc"
                  and n.args and isinstance(n.args[0], ast.Constant)]
        assert tokens and set(tokens) <= {"suts", "sits"}, tokens

    @pytest.mark.parametrize("rel,expected", [
        ("backend/routers/local.py", {"generate_suts": 3, "generate_sits": 3, "generate_sts": 3}),
        ("backend/routers/jenkins.py", {"generate_suts": 1, "generate_sts": 1}),
        ("workflow/impact_orchestrator.py", {"generate_suts": 1, "generate_sits": 1}),
    ])
    def test_every_generator_call_forwards_input_skips(self, rel, expected):
        """라우트가 못 연 입력의 사유가 생성기까지 간다 — 안 넘기면 공시가 '주지 않음 — 주면 …' 이 된다(원인은 파일인데)."""
        tree = ast.parse((_ROOT / rel).read_text(encoding="utf-8"))
        seen: dict = {}
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            name = n.func.id if isinstance(n.func, ast.Name) else ""
            if name not in expected and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id in expected:
                name = n.args[0].id     # `_run_blocking(generate_sts, …)`
            if name in expected:
                seen.setdefault(name, []).append(any(k.arg == "input_skips" for k in n.keywords))
        assert {k: len(v) for k, v in seen.items()} == expected
        assert all(all(v) for v in seen.values()), seen


# ── 생성기 · 라우트 · 공시에 닿는다(행동) ────────────────────────────────────────

def _empty_docx(path: Path) -> str:
    import docx
    d = docx.Document()
    d.add_paragraph("요구 표가 없는 문서")
    d.save(str(path))
    return str(path)


class TestSutsGeneratorRecordsInputs:
    def test_input_documents_reach_the_quality_report_and_the_disclosure(self, tmp_path, monkeypatch):
        calls = _boom_extractor(monkeypatch)
        # 저장소 override 스냅샷(`docs/uds_function_swcom_override.json`)은 따로 다룬다(백로그) — 여기선 SDS 축만 본다
        monkeypatch.setattr(gsuts, "_OVERRIDE_JSON_CANDIDATES", ())
        (tmp_path / "m.c").write_text("typedef unsigned char U8;\nU8 Fn(U8 a)\n{\n    return a;\n}\n", encoding="utf-8")
        srs = _empty_docx(tmp_path / "(P_SRS) Software Requirements Specification.docx")
        out = gsuts.generate_suts(source_root=str(tmp_path), output_path=str(tmp_path / "u.xlsm"), scope="source",
                                  srs_docx_path=srs, sds_docx_path=None, uds_path=str(tmp_path / "gone_SwUDS.docx"),
                                  input_skips=["SDS: 파일 없음 — 경로가 바뀌었거나 문서가 이동/개정됐을 수 있다"])
        q = out["quality_report"]
        docs = q["input_documents"]
        assert docs["SDS"]["given"] is True and docs["SDS"]["read"] is False and docs["SDS"]["reason"].startswith("파일 없음")
        assert docs["SRS"]["opened"] is True and docs["SRS"]["requirements"] == 0
        assert docs["SRS"]["reason"].startswith("요구 표 0 개(")
        assert docs["UDS"]["given"] is True and docs["UDS"]["opened"] is False
        assert docs["UDS"]["blocks_unopened"] == ["uds_unit_io", "uds_description_design_ids"]
        assert docs["HSIS"]["given"] is False
        # 열지 못한 SwUDS 는 '함수 표 0 개' 가 아니라 접근 사유로
        assert q["uds_reading"]["read_error"].startswith("열지 못함 — 파일 없음")
        # SDS · SwUDS · 소스 주석 어디에도 근거가 없으면 TBD(저장소 SDS 등급이 아니다)
        assert q["asil_evidence_distribution"] == {"none": 1}
        warns = " ".join(out["validation"].get("warnings") or [])
        assert "지정한 SDS 를 쓰지 못했다" in warns and "지정한 UDS 를 쓰지 못했다" in warns
        items = {i["key"]: i for i in build_disclosures("suts", q)}
        assert items["suts_input_documents"]["tone"] == "warning"
        assert items["suts_input_documents"]["value"] == "SRS 못 읽음 · SDS 못 읽음 · SwUDS 못 읽음 · HSIS 없음"
        assert "대체하지 않는다" in items["suts_input_documents"]["note"]
        assert items["suts_enrichment_errors"]["tone"] == "warning"
        assert "(SRS, SDS, SwUDS)" in items["suts_enrichment_errors"]["note"], items["suts_enrichment_errors"]["note"]
        assert calls == [], "SDS 를 주지 않았는데 파티션 추출기를 불렀다"

    def test_a_later_swuds_block_failing_is_not_an_unread_io_table(self, tmp_path, monkeypatch):
        """(리뷰 W2) 입출력 표 블록은 SwUDS 를 열었고 뒤 블록(설명 · 설계 ID)만 못 열었으면 'SwUDS 판독' 은 '읽지 못함' 이 아니다 —
        입력 문서 항목이 그 블록을 말한다."""
        import contextlib

        monkeypatch.setattr(gsuts, "_OVERRIDE_JSON_CANDIDATES", ())
        (tmp_path / "m.c").write_text("typedef unsigned char U8;\nU8 Fn(U8 a)\n{\n    return a;\n}\n", encoding="utf-8")
        uds = _empty_docx(tmp_path / "(P_SwUDS) Software Unit Design Specification.docx")
        real = gsuts._resolved_doc_input

        @contextlib.contextmanager
        def flaky(path, label, report=None):
            if label == "UDS":       # 설명 · 설계 ID 블록만 워커 일시 오류
                if report is not None:
                    report.update(opened=False, reason="읽기 실패 (TimeoutError)")
                yield None
                return
            with real(path, label, report=report) as p:
                yield p
        monkeypatch.setattr(gsuts, "_resolved_doc_input", flaky)
        q = gsuts.generate_suts(source_root=str(tmp_path), output_path=str(tmp_path / "u.xlsm"), scope="source",
                                uds_path=uds)["quality_report"]
        assert q["input_documents"]["UDS"]["opened"] is False
        assert q["input_documents"]["UDS"]["blocks_unopened"] == ["uds_description_design_ids"]
        assert not str(q["uds_reading"].get("read_error") or "").startswith("열지 못함")


class TestStsGeneratorRecordsInputs:
    def test_no_sds_means_no_sds_links_and_is_disclosed(self, tmp_path, monkeypatch):
        calls = _boom_extractor(monkeypatch)
        from generators import sts as gsts

        fd = {"f1": {"id": "f1", "name": "S_Motor_Init", "module_name": "MotorCtrl", "related": ""}}
        uds = _empty_docx(tmp_path / "not_really_SwUDS.docx")
        out = gsts.generate_sts(requirements_text=["SwTR_0101: 모터를 초기화한다"], function_details=fd,
                                output_path=str(tmp_path / "s.xlsm"), sds_docx_path=None, uds_path=uds,
                                input_skips=["SDS: 접근 거부 — 권한", "HSIS: 다른 경로가 다룬다"])
        gs = out["quality_report"]["generation_stats"]
        docs = gs["input_documents"]
        assert docs["SDS"] == {"given": True, "opened": False, "read": False, "entries": 0, "name": "",
                               "reason": "접근 거부 — 권한", "blocks_unopened": ["sds_partitions"]}
        assert docs["SRS"]["given"] is False and docs["SRS"]["requirements_from_text"] >= 1
        assert "HSIS" not in docs, "STS 의 HSIS 는 시스템 문서 기록이 다룬다"
        items = {i["key"]: i for i in build_disclosures("sts", out["quality_report"])}
        assert items["sts_input_documents"]["tone"] == "warning"
        assert items["sts_input_documents"]["value"] == "SRS 없음 · SDS 못 읽음 · SwUDS 열림 · STP 없음"
        assert "SRS 문서 없이 요구 문서 본문 글에서" in items["sts_input_documents"]["note"]
        assert calls == []


class TestSitsGeneratorRecordsInputs:
    def test_quality_report_carries_input_documents(self, tmp_path, monkeypatch):
        calls = _boom_extractor(monkeypatch)
        from generators import sits as gsits

        (tmp_path / "a.c").write_text("void B(void);\nvoid A(void)\n{\n    B();\n}\n", encoding="utf-8")
        (tmp_path / "b.c").write_text("void B(void)\n{\n}\n", encoding="utf-8")
        out = gsits.generate_sits(source_root=str(tmp_path), output_path=str(tmp_path / "i.xlsm"),
                                  input_skips=["SDS: 파일 없음 — 경로가 바뀌었다"])
        q = out.get("quality_report") or {}
        assert q, f"흐름이 없어 품질 보고서 전에 끝났다 — 이 시험이 공허해진다: {out.get('error')}"
        docs = q["input_documents"]
        assert docs["SDS"]["given"] is True and docs["SDS"]["read"] is False
        assert all(not docs[k]["given"] for k in ("SRS", "UDS", "HSIS", "STP"))
        assert q["sds_related_enrichment"]["source"] == "none"
        items = {i["key"]: i for i in build_disclosures("sits", q)}
        assert items["sits_input_documents"]["tone"] == "warning"
        assert "HSIS 없음 (쓰지 않음)" in items["sits_input_documents"]["value"]
        assert calls == [], "SDS 를 주지 않았는데 파티션 추출기를 불렀다(넓은 except 가 먹었어도 잡는다)"


class TestRoutesForwardSkips:
    def test_suts_route_passes_the_reason_and_never_a_repo_document(self, tmp_path, monkeypatch):
        import backend.routers.local as local_mod
        import suts_generator

        seen: dict = {}

        def _fake(**kw):
            seen.update(kw)
            raise RuntimeError("stop after the call")
        monkeypatch.setattr(suts_generator, "generate_suts", _fake)
        import backend.services.docgen_template_source as _tpl_src
        monkeypatch.setattr(_tpl_src, "resolve_template_for", lambda *a, **k: (None, "test"))
        monkeypatch.setattr(local_mod, "_build_local_excel_output", lambda *a, **k: ("x.xlsm", tmp_path / "x.xlsm"))

        class _Req:
            headers = {"x-req-id": "t1"}

        from fastapi import HTTPException

        with pytest.raises(HTTPException, match="stop after the call"):
            local_mod.local_suts_generate(
                request=_Req(), source_root=str(tmp_path), template_path="", scope="source", project_id="T",
                version="v1.00", asil_level="", max_sequences=24, report_dir="", srs_path="",
                sds_path=str(tmp_path / "gone" / "KJ_SwDS.docx"), uds_path="", hsis_path="", tc_profile="")
        assert seen, "generate_suts 가 호출되지 않았다"
        assert seen["srs_docx_path"] is None, "SRS 를 주지 않았는데 무언가(저장소 docs/)를 넘겼다"
        assert seen["sds_docx_path"] is None
        assert len(seen["input_skips"]) == 1 and seen["input_skips"][0].startswith("SDS: 파일 없음")

    def test_impact_regeneration_uses_registered_documents_only(self, tmp_path, monkeypatch):
        import suts_generator
        import workflow.impact_orchestrator as io
        from backend.schemas import ScmLinkedDocs

        seen: dict = {}
        monkeypatch.setattr(suts_generator, "generate_suts", lambda **kw: seen.update(kw) or {})
        monkeypatch.setattr(io, "SUTS_REPORT_DIR", tmp_path / "out")
        entry = SimpleNamespace(source_root=str(tmp_path), id="kj",
                                linked_docs=ScmLinkedDocs(sds=str(tmp_path / "gone_SwDS.docx")))
        io._run_suts_generation(entry, ["Fn"])
        assert seen["srs_docx_path"] is None and seen["hsis_path"] is None, "등록하지 않은 문서를 저장소 docs/ 에서 집었다"
        assert seen["sds_docx_path"] is None
        assert [s.split(":")[0] for s in seen["input_skips"]] == ["SDS"]


# ── 공시 문구 ───────────────────────────────────────────────────────────────

class TestDisclosure:
    @staticmethod
    def _doc(**kw):
        base = {"given": True, "opened": True, "name": "x.docx", "reason": "", "blocks_unopened": []}
        base.update(kw)
        return base

    def test_all_read_is_info(self):
        block = {"SRS": self._doc(requirements=63), "SDS": {"given": True, "read": True, "entries": 871, "name": "s.docx",
                                                            "reason": ""},
                 "UDS": self._doc(), "HSIS": self._doc()}
        it = build_disclosures("suts", {"input_documents": block})[0]
        assert it["key"] == "suts_input_documents" and it["tone"] == "info"
        assert it["value"] == "SRS 요구 63 · SDS 파티션 871 · SwUDS 열림 · HSIS 열림"

    def test_not_given_says_what_it_would_fill_and_is_info(self):
        block = {"SDS": {"given": False, "read": False, "entries": 0, "name": "", "reason": ""}}
        it = build_disclosures("sts", {"generation_stats": {"input_documents": block}})
        it = next(i for i in it if i["key"] == "sts_input_documents")
        assert it["tone"] == "info" and it["value"] == "SDS 없음"
        assert "요구-함수 연결" in it["note"] and "주면 채워진다" in it["note"]

    def test_srs_with_zero_requirements_is_a_warning(self):
        it = build_disclosures("suts", {"input_documents": {"SRS": self._doc(requirements=0, reason="요구 표 0 개")}})[0]
        assert it["tone"] == "warning" and it["value"] == "SRS 못 읽음" and "요구 표 0 개" in it["note"]

    def test_old_outputs_without_the_record_get_no_item(self):
        assert not [i for i in build_disclosures("suts", {}) if i["key"] == "suts_input_documents"]
        assert not [i for i in build_disclosures("sits", {"input_documents": {}}) if i["key"] == "sits_input_documents"]

    def test_sds_read_and_everything_opened_keeps_the_enrichment_note_info(self):
        """(리뷰) `_unread` 의 SDS 판정은 `read` — `opened` 로 바꾸면(SDS 기록엔 opened 가 없다) 여기서 warning 이 된다."""
        block = {"SDS": {"given": True, "read": True, "entries": 3, "name": "s.docx", "reason": ""}, "UDS": self._doc()}
        items = {i["key"]: i for i in build_disclosures("suts", {"input_documents": block, "enrichment_errors": []})}
        assert items["suts_enrichment_errors"]["tone"] == "info"
        assert items["suts_input_documents"]["tone"] == "info"

    def test_srs_with_zero_requirements_makes_the_enrichment_note_warn(self):
        """(리뷰 W3) 입력 문서 항목이 'SRS 못 읽음' 이면 '보강 실패 0건' 이 '빈 칸은 근거가 없어서' 라고 말하지 않는다."""
        block = {"SRS": self._doc(requirements=0, reason="요구 표 0 개")}
        items = {i["key"]: i for i in build_disclosures("suts", {"input_documents": block, "enrichment_errors": []})}
        assert items["suts_enrichment_errors"]["tone"] == "warning" and "(SRS)" in items["suts_enrichment_errors"]["note"]

    def test_override_snapshot_is_named_as_the_exception(self):
        """(리뷰 W5 · 2차 W-B) '대체하지 않는다 — 비우거나 TBD' 가 override 스냅샷이 든 unit 을 덮지 않는다 — SwUDS 와 함께 든
        `uds+override` 도 센다(더 높으면 스냅샷 등급이 이긴다)."""
        qr = {"input_documents": {"SDS": {"given": False, "read": False, "entries": 0, "name": "", "reason": ""}},
              "asil_evidence_distribution": {"override": 28, "uds+override": 200, "uds": 900, "none": 3},
              "asil_decided_by_override": 31}
        it = next(i for i in build_disclosures("suts", qr) if i["key"] == "suts_input_documents")
        assert "예외: 저장소 override 스냅샷" in it["note"] and "unit 228개" in it["note"]
        assert "그중 31개는 SwUDS 가 없거나 더 낮아" in it["note"]
        it = next(i for i in build_disclosures("suts", dict(qr, asil_evidence_distribution={"none": 3}))
                  if i["key"] == "suts_input_documents")
        assert "예외" not in it["note"]

    def test_a_document_the_generator_does_not_use_is_not_a_warning(self):
        block = {"HSIS": self._doc(opened=False, reason="파일 없음"), "SDS": {"given": True, "read": True, "entries": 1}}
        it = next(i for i in build_disclosures("sits", {"input_documents": block}) if i["key"] == "sits_input_documents")
        assert it["tone"] == "info" and "HSIS 못 읽음 (쓰지 않음)" in it["value"]

    def test_route_skip_without_a_name_is_not_a_question_mark(self):
        block = {"SDS": {"given": True, "read": False, "entries": 0, "name": "", "reason": "접근 거부"}}
        it = next(i for i in build_disclosures("sits", {"input_documents": block}) if i["key"] == "sits_input_documents")
        assert "`?`" not in it["note"] and "SDS — 접근 거부" in it["note"]

    def test_advice_matches_the_reason(self):
        """(리뷰 2차 I3) 못 연 문서는 위치 · 권한, 열었지만 내용을 못 읽은 문서(요구 표 0 · 파티션 0)는 양식 — `.docx` 단정 없음."""
        opened_empty = {"SRS": self._doc(requirements=0, reason="요구 표 0 개")}
        note = build_disclosures("suts", {"input_documents": opened_empty})[0]["note"]
        assert "양식을 확인할 것" in note and "위치 · 권한" not in note and "형식(.docx)" not in note
        sds0 = {"SDS": {"given": True, "opened": True, "read": False, "entries": 0, "name": "s.docx", "reason": "파티션 표 0 개"}}
        note = build_disclosures("suts", {"input_documents": sds0})[0]["note"]
        assert "양식을 확인할 것" in note and "위치 · 권한" not in note
        gone = {"UDS": self._doc(opened=False, reason="파일 없음")}
        note = build_disclosures("suts", {"input_documents": gone})[0]["note"]
        assert "위치 · 권한을 확인할 것" in note and "양식" not in note

    def test_all_read_says_nothing_about_substitution(self):
        """(리뷰 2차 I9) 다 읽었으면 '대체하지 않는다' 문장은 잡음이다."""
        block = {"SRS": self._doc(requirements=3), "SDS": {"given": True, "opened": True, "read": True, "entries": 2}}
        assert "대체하지 않는다" not in build_disclosures("suts", {"input_documents": block})[0]["note"]

    def test_override_sentence_without_the_substitution_sentence(self):
        """(리뷰 3차 I-b) 다 읽었으면 '예외:' 가 기댈 문장이 없다 — 앞 공백 · '예외:' 없이."""
        block = {"SRS": self._doc(requirements=3), "SDS": {"given": True, "opened": True, "read": True, "entries": 2}}
        note = next(i for i in build_disclosures("suts", {"input_documents": block,
                                                          "asil_evidence_distribution": {"override": 4}})
                    if i["key"] == "suts_input_documents")["note"]
        assert note.startswith("저장소 override 스냅샷") and "예외" not in note

    def test_specified_document_replaced_by_the_request_list_is_said(self):
        """(리뷰 2차 I5) 지정한 SRS 를 못 열고 요구 문서 목록의 SRS 가 쓰였으면 그 사실을 말한다."""
        docs: dict = {}
        note_input_document(docs, "SRS", "C:/t/list_SRS.docx", "srs_req_ids", {"opened": True}, ["SRS: 파일 없음"])
        assert docs["SRS"]["specified_unopened"] == "파일 없음"
        it = build_disclosures("sts", {"generation_stats": {"input_documents": docs}})[0]
        assert "지정한 문서를 열지 못해(파일 없음) 요구 문서 목록(또는 업로드)의 `list_SRS.docx` 를 썼다" in it["note"]
        # (리뷰 3차 W-E) 지정하지 않은 문서로 만들었다 — warning, '대체하지 않는다' 문장과 겹치지 않는다
        assert it["tone"] == "warning" and "대체하지 않는다" not in it["note"]

    def test_table_less_srs_with_text_requirements(self):
        """(리뷰 2차 I4) SRS 를 줬는데 표를 못 읽어 본문 글로 읽은 경우의 문구."""
        block = {"SRS": self._doc(requirements=0, requirements_from_text=5, reason="요구 표 0 개")}
        it = build_disclosures("sts", {"generation_stats": {"input_documents": block}})[0]
        assert "SRS 의 요구 표를 못 읽어 요구 문서 본문 글에서 요구 5개를 읽었다" in it["note"] and it["tone"] == "warning"

    def test_enrichment_zero_no_longer_claims_everything_ran(self):
        items = {i["key"]: i for i in build_disclosures("suts", {"enrichment_errors": []})}
        note = items["suts_enrichment_errors"]["note"]
        assert "전부 끝까지 돌았다" not in note and "연 문서의 보강 단계" in note
        assert items["suts_enrichment_errors"]["tone"] == "info"


def test_sds_zip_but_no_partitions_reason(tmp_path, monkeypatch):
    src = tmp_path / "KJ_SwDS.docx"
    with zipfile.ZipFile(src, "w") as z:
        z.writestr("word/document.xml", "<x/>")
    monkeypatch.setattr(gsuts, "_extract_sds_partition_map", lambda p: {})
    m, r = gsuts.read_sds_input(str(src))
    assert m == {} and r["given"] and not r["read"] and r["reason"].startswith("파티션 표 0 개")


class TestImpactCardUsesTheRegisteredSds:
    def test_one_sds_read_reaches_the_suts_and_sits_drafts(self, monkeypatch):
        """(리뷰 2차 W-C) 영향도 카드는 등록 SDS 를 한 번 읽어(`read_sds_input`) SUTS · SITS 초안 둘 다에 준다 — `sds_map=` 를
        빠뜨리면 SUTS 초안 ASIL 이 조용히 TBD 가 된다."""
        import generators.sits as gsits
        import generators.suts as gs
        from tests.unit.test_impact_doc_content import _proposal_sections, _stub_generators
        from workflow.impact_orchestrator import _build_doc_proposal

        seen: dict = {"read": []}
        _stub_generators(monkeypatch)
        the_map = {"s_foo": {"asil": "B", "related": "SwTR_0101"}}
        monkeypatch.setattr(gs, "read_sds_input",
                            lambda p, **k: (seen["read"].append(p) or dict(the_map), {"read": True, "reason": ""}))
        monkeypatch.setattr(gs, "collect_unit_functions",
                            lambda fdmap, gim=None, **k: (seen.update(suts=k.get("sds_map")) or [{"name": "s_foo"}]))
        monkeypatch.setattr(gsits, "collect_integration_flows",
                            lambda fdmap, max_flows=120, **k: (seen.update(sits=k.get("sds_map"))
                                                               or [{"entry_fn": "s_foo", "call_chain": "s_foo -> s_dep"}]))
        fd = {"f1": {"name": "s_foo", "prototype": "U16 s_foo(U16 x)", "logic_flow": [], "calls_list": []}}
        _build_doc_proposal(_proposal_sections(fd), {"s_foo"}, sds_path="U:/proj/KJ_SwDS.docx")
        assert seen["read"] == ["U:/proj/KJ_SwDS.docx"], "SDS 를 한 번, 등록 경로 그대로 읽어야 한다"
        assert seen["suts"] == the_map, "SUTS 초안이 등록 SDS 맵을 받지 않았다(ASIL 이 TBD 가 된다)"
        assert seen["sits"] == the_map

    def test_the_call_site_passes_the_raw_registered_path(self):
        """`_resolve_existing` 은 로컬 판정이라 클라우디움 등록 SDS 를 지운다 — SDS 는 원래 경로 그대로 넘긴다(워커 경유는 판독기 몫)."""
        tree = ast.parse((_ROOT / "workflow" / "impact_orchestrator.py").read_text(encoding="utf-8"))
        vals = [ast.unparse(k.value) for n in ast.walk(tree)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_build_doc_proposal"
                for k in n.keywords if k.arg == "sds_path"]
        assert vals and all("_resolve_existing" not in v for v in vals), vals


class TestAsilDecidedByOverride:
    """(리뷰 3차 W-D) '스냅샷 등급이 최종 등급을 정한 unit' 의 생산자 — 공시가 그 수를 말하므로 잘못 세면 조용히 틀린다."""

    @staticmethod
    def _fd():
        def f(name, asil, src):
            return {"name": name, "prototype": f"void {name}(void)", "asil": asil, "asil_source": src}
        return {"F1": f("only_override", "B", "override"),        # SwUDS 없음 → 스냅샷이 정함
                "F2": f("override_higher", "C", "override"),      # 스냅샷 C > SwUDS A → 정함
                "F3": f("override_lower", "A", "override"),       # 스냅샷 A < SwUDS C → 아님
                "F4": f("override_equal", "B", "override"),       # 같음 → 아님(SwUDS 만으로도 B)
                "F5": f("source_tag", "D", "source")}             # 소스 @asil → 아님

    def test_five_cases(self):
        io = {"by_name": {"override_higher": {"asil": "A"}, "override_lower": {"asil": "C"},
                          "override_equal": {"asil": "B"}, "source_tag": {"asil": "A"}}}
        units = gsuts.collect_unit_functions(self._fd(), {}, sds_map={}, uds_io_map=io)
        got = {u["name"]: (u["asil"], u["asil_by_override"]) for u in units}
        assert got == {"only_override": ("B", True), "override_higher": ("C", True), "override_lower": ("C", False),
                       "override_equal": ("B", False), "source_tag": ("D", False)}, got
        q = gsuts.generate_suts_quality_report(units, {}, len(units))
        assert q["asil_decided_by_override"] == 2


@pytest.mark.parametrize("mode", ["raise", "empty", "two"])
def test_sits_srs_requirement_count_and_parse_failure(tmp_path, monkeypatch, mode):
    """(리뷰 4차 I-1) SITS 의 SRS — 표 판독이 예외면 '열림' 이 아니라 사유(못 읽음 · warning), 표 0 개도 못 읽음, 읽었으면 요구 수.
    `_srs_reqs_n = 0` 을 빠뜨리면 조용한 'SRS 열림' 으로 돌아간다."""
    import generators.sts as gsts
    from generators import sits as gsits

    def fake(_p):
        if mode == "raise":
            raise ValueError("bad docx")
        return [] if mode == "empty" else [{"id": "SwTR_1", "text": "x"}, {"id": "SwTR_2", "text": "y"}]
    monkeypatch.setattr(gsts, "parse_srs_docx_tables", fake)
    (tmp_path / "a.c").write_text("void B(void);\nvoid A(void)\n{\n    B();\n}\n", encoding="utf-8")
    (tmp_path / "b.c").write_text("void B(void)\n{\n}\n", encoding="utf-8")
    srs = tmp_path / "srs.docx"
    srs.write_bytes(b"PK")
    out = gsits.generate_sits(source_root=str(tmp_path), output_path=str(tmp_path / "i.xlsm"), srs_docx_path=str(srs))
    q = out.get("quality_report") or {}
    assert q, out.get("error")
    rec = q["input_documents"]["SRS"]
    it = next(i for i in build_disclosures("sits", q) if i["key"] == "sits_input_documents")
    if mode == "raise":
        assert rec["requirements"] == 0 and rec["reason"] == "요구 표 판독 실패 (ValueError)"
        assert it["tone"] == "warning" and "SRS 못 읽음" in it["value"]
    elif mode == "empty":
        assert rec["requirements"] == 0 and rec["reason"].startswith("요구 표 0 개(") and it["tone"] == "warning"
    else:
        assert rec["requirements"] == 2 and "SRS 요구 2" in it["value"]
