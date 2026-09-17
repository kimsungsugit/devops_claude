"""R55(N27-c 후처리) 가드 — DOCX 자식이 끝난 뒤 4분이 어디서 갔나.

착수 실측(run 2085 로그 + 60MB 산출물 오프라인): 후처리 리포트 셋(accuracy·confidence·quality gate)이 **같은 60MB 문서를
각자 열어 989개 함수 표를 각자 걸었고**(각 11초), accuracy 리포트는 **소스 전체를 다시 분석**했다(라이브 ≈2분 — 그것도 첫 루트만·
기본 상한으로, 문서를 만든 분석과 다른 분석). 셀 글 접근자(`_Cell.text`)는 문단마다 xpath 를 새로 평가해 걷기의 80% 였다.

가드:
  1. `report_gen.docx_text` 가 python-docx `.text` 와 **같은 값**(탭·줄바꿈·페이지 나눔·하이퍼링크·중첩 표·빈 칸·병합).
  2. `read_back_function_info` 메모 — 같은 파일 한 번 · 바뀐 파일 다시 · 반환은 사본 · 상한 2.
  3. accuracy 리포트 — `source_sections=` 를 주면 재분석 0, 안 주면 재분석 + 경고, 머리글에 기대측 출처.
  4. 프로덕션 호출부 셋이 `source_sections=` 를 넘긴다(소스 가드).
  5. 리포트 셋이 같은 파일을 **한 번만** 판다(되읽기 호출 횟수).
  6. 구조 검증기·되읽기가 옛 접근자로 잰 값과 같다(고정 표본).
  7. 리포트 소요가 로그에 남는다.
"""
from __future__ import annotations

import copy
import logging
import re
import time
from pathlib import Path

import docx
import pytest
from docx.enum.text import WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

import report_gen.validation as V
from backend.helpers.common import _run_report_with_timeout
from report_gen.docx_text import cell_text, paragraph_text, run_text
from report_gen.requirements import _extract_function_info_from_docx

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _fresh_readback_cache():
    V.clear_readback_cache()
    yield
    V.clear_readback_cache()


# ────────────────────────────────────────── 표본 ──────────────────────────────────────────
def _raw(tag: str, **attrs):
    el = OxmlElement(tag)
    for k, v in attrs.items():
        el.set(qn(k), v)
    return el


def _hyperlink_run(paragraph, text: str):
    hl = _raw("w:hyperlink")
    r = _raw("w:r")
    t = _raw("w:t")
    t.text = text
    r.append(t)
    hl.append(r)
    paragraph._p.append(hl)


def _function_table(doc, fn_id: str, name: str, *, called: str, calling: str, logic_layout: str = "new"):
    """빌더가 내는 함수 정보 표의 최소 모양(2열: 라벨|값). 되읽기 규칙: 0행 머리 · 1행에 SwUFn_ · 2행부터 라벨|값."""
    rows = [
        ("[ Function Information ]", ""),
        ("ID", fn_id),
        ("Name", name),
        ("Prototype", f"void {name}(void)"),
        ("Description", "does\tthings"),
        ("ASIL", "B"),
        ("Related ID", "SwFn_01"),
        ("Called Function", called),
        ("Calling Function", calling),
    ]
    t = doc.add_table(rows=0, cols=2)
    for label, value in rows:
        cells = t.add_row().cells
        cells[0].text = label
        cells[1].text = value
    if logic_layout == "new":
        hdr = t.add_row().cells
        hdr[0].merge(hdr[1]).text = "[ Logic Diagram ]"
        body = t.add_row().cells
        body[0].merge(body[1]).text = ""
    else:
        r = t.add_row().cells
        r[0].text = "Logic Diagram"
        r[1].text = ""
    return t


def _build_sample(path: Path, *, n: int = 2):
    doc = docx.Document()
    doc.add_heading("SwUFn_0001: f_one", level=3)
    _function_table(doc, "SwUFn_0001", "f_one", called="f_two", calling="")
    if n >= 2:
        doc.add_heading("SwUFn_0002: f_two", level=3)
        _function_table(doc, "SwUFn_0002", "f_two", called="", calling="f_one", logic_layout="old")
    doc.save(str(path))
    return path


def _sections_for_sample():
    return {
        "function_details_by_name": {
            "f_one": {"name": "f_one", "calls_list": ["f_two"]},
            "f_two": {"name": "f_two", "calls_list": []},
        },
        "function_table_rows": [["SwCom_01", "", "", "f_one"], ["SwCom_02", "", "", "f_two"]],
    }


# ────────────────────────────── 1. 빠른 텍스트 = python-docx 텍스트 ──────────────────────────────
class TestFastTextMatchesPythonDocx:
    def _doc_with_variants(self, tmp_path: Path):
        doc = docx.Document()
        t = doc.add_table(rows=6, cols=3)
        c = t.cell(0, 0)
        p = c.paragraphs[0]
        r = p.add_run("a")
        r.add_tab()
        r.add_text("b")
        r.add_break()                      # w:br (textWrapping → "\n")
        r.add_text("c")
        r.add_break(WD_BREAK.PAGE)         # w:br type=page → ""
        r.add_text("d")
        r._r.append(_raw("w:cr"))          # "\n"
        r._r.append(_raw("w:noBreakHyphen"))   # "-"
        r._r.append(_raw("w:ptab"))        # "\t"
        r._r.append(_raw("w:sym"))         # 무시
        c.add_paragraph("second para")
        _hyperlink_run(c.paragraphs[1], " link")
        # 중첩 표 — 바깥 셀 글에 안 들어간다
        inner = c.add_table(rows=1, cols=1)
        inner.cell(0, 0).text = "nested"
        c.add_paragraph("after nested")
        # 빈 칸 · 공백만 · 여러 런
        t.cell(0, 1).text = ""
        t.cell(0, 2).text = "   "
        p2 = t.cell(1, 0).paragraphs[0]
        p2.add_run("x")
        p2.add_run("y")
        # 병합(가로) · 페이지 나눔 있는 문단 · 추적 변경(w:ins 안 런은 둘 다 안 본다)
        m = t.cell(2, 0).merge(t.cell(2, 2))
        m.text = "merged [ Logic Diagram ]"
        ins = _raw("w:ins")
        rr = _raw("w:r")
        tt = _raw("w:t")
        tt.text = "tracked"
        rr.append(tt)
        ins.append(rr)
        t.cell(3, 0).paragraphs[0]._p.append(ins)
        t.cell(4, 1).text = "한글\t탭"
        doc.add_paragraph("body paragraph")
        _hyperlink_run(doc.paragraphs[-1], " with link")
        path = tmp_path / "variants.docx"
        doc.save(str(path))
        return docx.Document(str(path))

    def test_every_cell_and_paragraph_matches(self, tmp_path):
        d = self._doc_with_variants(tmp_path)
        compared = 0
        for table in d.tables:
            for row in table.rows:
                for cell in row.cells:
                    assert cell_text(cell) == cell.text
                    assert cell_text(cell._tc) == cell.text
                    compared += 1
                    for p in cell.paragraphs:
                        assert paragraph_text(p) == p.text
                        for r in p.runs:
                            assert run_text(r) == r.text
        for p in d.paragraphs:
            assert paragraph_text(p) == p.text
        assert compared >= 18

    def test_variant_values_are_the_ones_python_docx_defines(self, tmp_path):
        d = self._doc_with_variants(tmp_path)
        c = d.tables[0].cell(0, 0)
        # 탭 · 줄바꿈 · 페이지 나눔("") · cr · noBreakHyphen · ptab · 두 번째 문단 + 하이퍼링크 · 중첩 표 제외
        # (python-docx 의 `_Cell.add_table` 은 표 뒤에 빈 문단을 하나 덧붙인다 — 그래서 빈 줄 하나)
        assert cell_text(c) == "a\tb\ncd\n-\t\nsecond para link\n\nafter nested"
        assert c.text == cell_text(c)
        assert cell_text(d.tables[0].cell(3, 0)) == ""          # w:ins 안 런은 python-docx 도 안 본다
        assert cell_text(d.tables[0].cell(2, 0)) == "merged [ Logic Diagram ]"


# ────────────────────────────── 2. 되읽기 메모 ──────────────────────────────
class TestReadBackMemo:
    def _count_extracts(self, monkeypatch):
        calls = {"n": 0}
        real = V._extract_function_info_from_docx

        def counting(doc):
            calls["n"] += 1
            return real(doc)

        monkeypatch.setattr(V, "_extract_function_info_from_docx", counting)
        return calls

    def test_same_file_is_parsed_once(self, tmp_path, monkeypatch):
        calls = self._count_extracts(monkeypatch)
        p = _build_sample(tmp_path / "a.docx")
        m1 = V.read_back_function_info(str(p))
        m2 = V.read_back_function_info(str(p))
        assert calls["n"] == 1
        assert m1 == m2 and set(m1) == {"SwUFn_0001", "SwUFn_0002"}

    def test_returns_a_copy_so_consumers_cannot_leak_edits(self, tmp_path, monkeypatch):
        self._count_extracts(monkeypatch)
        p = _build_sample(tmp_path / "a.docx")
        m1 = V.read_back_function_info(str(p))
        m1["SwUFn_0001"]["asil"] = "D"
        m1["SwUFn_0001"]["inputs"] = ["[IN] leak"]
        m2 = V.read_back_function_info(str(p))
        assert m2["SwUFn_0001"]["asil"] == "B"
        assert "inputs" not in m2["SwUFn_0001"]          # 표본 함수는 파라미터 행이 없다 — 누설이 있었다면 여기 생긴다
        # 캐시 적중으로 받은 것도 사본이어야 한다(적중 반환을 고쳐도 다음 적중은 깨끗)
        m2["SwUFn_0001"]["asil"] = "X"
        m3 = V.read_back_function_info(str(p))
        assert m3["SwUFn_0001"]["asil"] == "B"
        assert m3 is not m2

    def test_changed_file_is_parsed_again(self, tmp_path, monkeypatch):
        calls = self._count_extracts(monkeypatch)
        p = _build_sample(tmp_path / "a.docx", n=2)
        assert len(V.read_back_function_info(str(p))) == 2
        time.sleep(0.05)
        _build_sample(p, n=1)          # 같은 경로에 다른 내용(size·mtime_ns 가 바뀐다)
        m = V.read_back_function_info(str(p))
        assert calls["n"] == 2 and set(m) == {"SwUFn_0001"}

    def test_missing_file_raises_like_before(self, tmp_path):
        with pytest.raises(OSError):
            V.read_back_function_info(str(tmp_path / "nope.docx"))

    def test_cache_is_bounded(self, tmp_path, monkeypatch):
        calls = self._count_extracts(monkeypatch)
        paths = [_build_sample(tmp_path / f"{i}.docx", n=1) for i in range(3)]
        for p in paths:
            V.read_back_function_info(str(p))
        assert calls["n"] == 3
        V.read_back_function_info(str(paths[0]))     # 가장 오래된 것은 밀려났다
        assert calls["n"] == 4
        assert len(V._READBACK_CACHE) == V._READBACK_MAX == 2


# ────────────────────────────── 3. accuracy — 기대측은 문서를 만든 분석 ──────────────────────────────
class TestAccuracyReportUsesThePipelineAnalysis:
    def test_given_sections_no_reanalysis_and_head_says_so(self, tmp_path, monkeypatch):
        import report_gen.uds_generator as UG

        def boom(*a, **k):
            raise AssertionError("source_sections 를 줬는데 소스를 다시 분석했다")

        monkeypatch.setattr(UG, "generate_uds_source_sections", boom)
        p = _build_sample(tmp_path / "a.docx")
        out = tmp_path / "acc.md"
        V.generate_called_calling_accuracy_report(str(p), "C:/never/analyzed", str(out), source_sections=_sections_for_sample())
        text = out.read_text(encoding="utf-8")
        assert "- Expected side: pipeline source_sections" in text
        assert "- Expected functions (source analysis): `2`" in text
        assert "- Total functions compared: `2`" in text
        assert "- Called exact match: `2` / `2` (100.0%)" in text
        assert "- Calling exact match: `2` / `2` (100.0%)" in text
        # SwCom 귀속은 function_table_rows 에서
        assert re.search(r"## SwCom_01\n- Functions: `1`", text)

    def test_without_sections_reanalyzes_once_and_warns(self, tmp_path, monkeypatch, caplog):
        import report_gen.uds_generator as UG

        calls = []

        def fake(root, *a, **k):
            calls.append(root)
            return _sections_for_sample()

        monkeypatch.setattr(UG, "generate_uds_source_sections", fake)
        p = _build_sample(tmp_path / "a.docx")
        out = tmp_path / "acc.md"
        with caplog.at_level(logging.WARNING, logger="report_generator"):
            V.generate_called_calling_accuracy_report(str(p), "C:/some/root", str(out))
        assert calls == ["C:/some/root"]
        assert any("재분석" in r.getMessage() for r in caplog.records)
        text = out.read_text(encoding="utf-8")
        assert "- Expected side: re-analysis of source_root `C:/some/root`" in text

    def test_mismatch_is_reported_against_the_given_analysis(self, tmp_path):
        p = _build_sample(tmp_path / "a.docx")
        sections = copy.deepcopy(_sections_for_sample())
        sections["function_details_by_name"]["f_one"]["calls_list"] = ["f_two", "f_three"]
        sections["function_details_by_name"]["f_three"] = {"name": "f_three", "calls_list": []}
        out = tmp_path / "acc.md"
        V.generate_called_calling_accuracy_report(str(p), "", str(out), source_sections=sections)
        text = out.read_text(encoding="utf-8")
        assert "- Called exact match: `1` / `2` (50.0%)" in text
        assert "`f_one` | called exp=['f_three', 'f_two'] act=['f_two']" in text

    def test_summary_parser_still_reads_the_head(self, tmp_path):
        p = _build_sample(tmp_path / "a.docx")
        out = tmp_path / "acc.md"
        V.generate_called_calling_accuracy_report(str(p), "", str(out), source_sections=_sections_for_sample())
        parsed = V._parse_accuracy_summary(out.read_text(encoding="utf-8"))
        assert parsed["total_functions"] == 2
        assert parsed["called_exact_match"] == "100.0%"
        assert parsed["calling_exact_match"] == "100.0%"

    def test_empty_sections_is_document_baseline_not_a_reanalysis(self, tmp_path, monkeypatch):
        import report_gen.uds_generator as UG

        monkeypatch.setattr(UG, "generate_uds_source_sections", lambda *a, **k: pytest.fail("재분석 금지"))
        p = _build_sample(tmp_path / "a.docx")
        out = tmp_path / "acc.md"
        V.generate_called_calling_accuracy_report(str(p), "", str(out), source_sections={})
        text = out.read_text(encoding="utf-8")
        assert "source function details are empty; accuracy result is document-baseline only" in text


# ────────────────────────────── 4. 호출부 셋 ──────────────────────────────
class TestProductionCallersPassTheirAnalysis:
    # (리뷰 W1) 넷째 호출부 `tools/generate_uds_local.py`(로컬 CLI)도 같은 payload 를 들고 있다 — 빠뜨리면 그 경로만 옛 재분석이다.
    CALLERS = ("backend/helpers/uds.py", "backend/routers/jenkins.py", "backend/routers/local.py", "tools/generate_uds_local.py")

    @pytest.mark.parametrize("rel", CALLERS)
    def test_every_call_passes_source_sections(self, rel):
        src = (REPO / rel).read_text(encoding="utf-8")
        calls = [m.start() for m in re.finditer(r"generate_called_calling_accuracy_report\(", src)]
        calls = [i for i in calls if not src[max(0, i - 40):i].rstrip().endswith(("import", ","))]
        assert calls, rel
        for i in calls:
            window = src[i:i + 500]
            body = window.split("timeout_seconds", 1)[0]
            assert re.search(r"source_sections=(source_sections|uds_payload)\b", body), (rel, window[:200])

    def test_no_other_caller_in_the_repo_is_left_on_the_reanalysis_path(self):
        # 프로덕션·도구 트리 전수: `source_sections=` 없이 부르는 곳은 없어야 한다(테스트는 폴백을 일부러 쓴다 — 제외).
        offenders = []
        for base in ("backend", "report_gen", "workflow", "tools", "generators", "scripts"):
            root = REPO / base
            if not root.is_dir():
                continue
            for py in root.rglob("*.py"):
                if "venv" in py.parts or "node_modules" in py.parts:
                    continue
                src = py.read_text(encoding="utf-8", errors="ignore")
                for m in re.finditer(r"generate_called_calling_accuracy_report\(", src):
                    before = src[max(0, m.start() - 40):m.start()].rstrip()
                    if before.endswith(("import", ",", "def")):
                        continue
                    body = src[m.start():m.start() + 500].split("timeout_seconds", 1)[0]
                    if "source_sections=" not in body:
                        offenders.append(f"{py.relative_to(REPO)}:{src[:m.start()].count(chr(10)) + 1}")
        assert offenders == [], offenders

    def test_no_production_caller_re_imports_the_analyzer_for_accuracy(self):
        # validation.py 안의 재분석 import 는 폴백 한 곳뿐이어야 한다.
        src = (REPO / "report_gen/validation.py").read_text(encoding="utf-8")
        assert src.count("from report_gen.uds_generator import generate_uds_source_sections") == 1


# ────────────────────────────── 5. 리포트 셋이 한 번만 판다 ──────────────────────────────
class TestReportsShareOneReadBack:
    def test_accuracy_confidence_gate_parse_the_docx_once(self, tmp_path, monkeypatch):
        calls = {"n": 0}
        real = V._extract_function_info_from_docx

        def counting(doc):
            calls["n"] += 1
            return real(doc)

        monkeypatch.setattr(V, "_extract_function_info_from_docx", counting)
        p = _build_sample(tmp_path / "a.docx")
        payload = {
            "function_details_by_name": {
                "f_one": {"id": "SwUFn_0001", "name": "f_one", "description": "", "asil": "TBD", "related": "", "calls_list": ["f_two"]},
                "f_two": {"id": "SwUFn_0002", "name": "f_two", "description": "", "asil": "TBD", "related": "", "calls_list": []},
            },
            "function_details": {},
            "function_table_rows": _sections_for_sample()["function_table_rows"],
        }
        V.generate_called_calling_accuracy_report(str(p), "", str(tmp_path / "acc.md"), source_sections=payload)
        V.generate_asil_related_confidence_report(payload, str(tmp_path / "conf.md"), str(p))
        V.generate_uds_field_quality_gate_report(str(p), str(tmp_path / "qg.md"))
        assert calls["n"] == 1
        # 값은 여전히 문서에서 온다(관측량 고정 — 리뷰 I6)
        assert "- Document entries: `2`" in (tmp_path / "qg.md").read_text(encoding="utf-8")


    def test_confidence_fuzzy_name_fallback_still_recovers_document_asil(self, tmp_path):
        # payload 이름 `f_one_impl` 은 문서에 없고 id 도 없다 → 정규화 이름 포함 관계(`f_one` ⊂ `f_one_impl`)로 문서 행을 찾아
        # 문서 ASIL(B) 을 `generated_doc` 출처로 회수한다. (R55) 정규화를 한 번만 하도록 바꿨어도 판정은 같아야 한다.
        p = _build_sample(tmp_path / "a.docx")
        payload = {"function_details_by_name": {
            "f_one_impl": {"id": "", "name": "f_one_impl", "description": "", "asil": "TBD", "asil_source": "inference",
                           "related": "", "related_source": "inference"},
        }}
        out = tmp_path / "conf.md"
        V.generate_asil_related_confidence_report(payload, str(out), str(p))
        text = out.read_text(encoding="utf-8")
        asil_section = text.split("## ASIL Source", 1)[1].split("## ", 1)[0]
        assert "생성 문서 회수(원 유래 불명): `1` / `1`" in asil_section, asil_section
        # 입력 payload 는 건드리지 않는다(리포트가 감사할 게이트를 부풀리던 전례)
        assert payload["function_details_by_name"]["f_one_impl"]["asil"] == "TBD"


# ────────────────────────────── 6. 옛 접근자와 같은 값 ──────────────────────────────
class TestStructureAndReadBackValuesUnchanged:
    def test_structure_validator_counts(self, tmp_path):
        p = _build_sample(tmp_path / "a.docx")
        r = V.validate_uds_docx_structure(str(p))
        assert r["table_count"] == 2
        assert r["function_info_table_count"] == 2
        assert r["swufn_heading_count"] == 2
        assert r["logic_row_count"] == 2
        assert r["logic_with_image_count"] == 0
        # 머리행 키는 `.text` 로 만들던 것과 같다
        d = docx.Document(str(p))
        expected_keys = {"|".join(c.text.strip() for c in t.rows[0].cells) for t in d.tables}
        assert {h["header"] for h in r["top_headers"]} == expected_keys

    def test_read_back_values_fixed_sample(self, tmp_path):
        # (리뷰 I7) 옛 접근자와의 **대조**는 위 `TestFastTextMatchesPythonDocx` 가 한다 — 여기는 고정 표본의 값을 못박는다.
        p = _build_sample(tmp_path / "a.docx")
        got = _extract_function_info_from_docx(docx.Document(str(p)))
        assert got["SwUFn_0001"]["name"] == "f_one"
        assert got["SwUFn_0001"]["description"] == "does\tthings"
        assert got["SwUFn_0001"]["called"] == "f_two"
        assert got["SwUFn_0002"]["calling"] == "f_one"
        assert got["SwUFn_0001"]["asil"] == "B"
        assert got["SwUFn_0001"]["related"] == "SwFn_01"


# ────────────────────────────── 6b. (리뷰 W2) 기대측 정의가 이력에 남는다 ──────────────────────────────
class TestExpectedSideTravelsWithTheNumbers:
    def test_summary_parser_reads_expected_side(self, tmp_path):
        p = _build_sample(tmp_path / "a.docx")
        out = tmp_path / "acc.md"
        V.generate_called_calling_accuracy_report(str(p), "", str(out), source_sections=_sections_for_sample())
        text = out.read_text(encoding="utf-8")
        assert V._parse_accuracy_summary(text)["expected_side"] == "pipeline"
        assert "- Measures: writer fidelity" in text
        legacy = "\n".join(ln for ln in text.splitlines() if not ln.startswith("- Expected side"))
        assert V._parse_accuracy_summary(legacy)["expected_side"] == ""          # 옛 리포트 = 정의 미기록
        assert V._parse_accuracy_summary(text.replace("pipeline source_sections (the analysis that built the document)",
                                                       "re-analysis of source_root `x` (may differ …)"))["expected_side"] == "re-analysis"

    def test_helper_parser_and_recorder_meta_carry_expected_side(self, tmp_path, monkeypatch):
        from backend.helpers.uds import _parse_accuracy_report
        from workflow.quality import recorder as R

        p = _build_sample(tmp_path / "a.docx")
        out = tmp_path / "acc.md"
        V.generate_called_calling_accuracy_report(str(p), "", str(out), source_sections=_sections_for_sample())
        parsed = _parse_accuracy_report(out)
        assert parsed["called_exact_match"] == 100.0 and parsed["expected_side"] == "pipeline"
        captured = {}

        def fake_record_run(doc_type, data, **kwargs):
            captured.update({"doc_type": doc_type, "data": data, "kwargs": kwargs})
            return 7

        monkeypatch.setattr(R, "record_run", fake_record_run)
        rid = R.record_uds_run({"quick_gate": {"rates": {}, "counts": {}}, "accuracy": parsed}, meta={"entry": "t"})
        assert rid == 7
        assert captured["kwargs"]["meta"] == {"entry": "t", "accuracy_expected_side": "pipeline"}
        # 정의가 없는 옛 리포트면 키를 지어내지 않는다
        captured.clear()
        R.record_uds_run({"quick_gate": {"rates": {}, "counts": {}}, "accuracy": {"called_exact_match": 1.0, "expected_side": ""}}, meta={"entry": "t"})
        assert captured["kwargs"]["meta"] == {"entry": "t"}


# ────────────────────────────── 6c. (리뷰 W3/I1) 동시 진입 · 파싱 중 교체 ──────────────────────────────
class TestReadBackConcurrency:
    def test_concurrent_callers_on_the_same_file_parse_once(self, tmp_path, monkeypatch):
        import threading

        calls = {"n": 0}
        real = V._extract_function_info_from_docx

        def slow_counting(doc):
            calls["n"] += 1
            time.sleep(0.3)
            return real(doc)

        monkeypatch.setattr(V, "_extract_function_info_from_docx", slow_counting)
        p = _build_sample(tmp_path / "a.docx")
        results = []
        errors = []

        def worker():
            try:
                results.append(V.read_back_function_info(str(p)))
            except Exception as exc:  # noqa: BLE001 — 스레드 안 예외를 본문 단언으로 올린다
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert errors == []
        assert calls["n"] == 1, calls
        assert len(results) == 5 and all(r == results[0] for r in results)
        assert all(r is not results[0] for r in results[1:])          # 전부 사본
        assert V._READBACK_INFLIGHT == {}                              # 진행 중 락은 끝나면 비운다

    def test_file_replaced_during_parse_is_not_cached_under_the_old_signature(self, tmp_path, monkeypatch):
        real = V._extract_function_info_from_docx
        p = _build_sample(tmp_path / "a.docx", n=2)
        swapped = {"done": False}

        def swapping(doc):
            out = real(doc)
            if not swapped["done"]:
                swapped["done"] = True
                time.sleep(0.05)
                _build_sample(p, n=1)          # 파싱하는 동안 같은 경로가 새 내용으로 바뀐다
            return out

        monkeypatch.setattr(V, "_extract_function_info_from_docx", swapping)
        first = V.read_back_function_info(str(p))
        assert set(first) == {"SwUFn_0001", "SwUFn_0002"}          # 결과는 판 그대로 돌려준다
        assert V._READBACK_CACHE == {}                              # 옛 서명에 새 내용도, 새 서명에 옛 내용도 저장하지 않는다
        second = V.read_back_function_info(str(p))
        assert set(second) == {"SwUFn_0001"}                        # 다음 호출은 바뀐 파일을 새로 판다


# ────────────────────────────── 7. 소요 로그 ──────────────────────────────
class TestReportElapsedIsLogged:
    def test_success_logs_elapsed(self, caplog):
        with caplog.at_level(logging.INFO, logger="devops_api"):
            ok, err = _run_report_with_timeout(lambda: None, timeout_seconds=5, report_name="x report")
        assert ok and err == ""
        assert any(re.search(r"\[UDS_REPORT\] x report done in \d+\.\d+s", r.getMessage()) for r in caplog.records)
