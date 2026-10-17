"""R60 (N64) — 소스 분석의 기본 경로는 전처리(`gcc -E`)를 거치지 않는다.

2026-09-17 까지 문서생성·영향분석은 `preprocess=True("정밀")` 로 돌았다. 실측(KJPDS02 178 파일 · PDS64 127 파일):
- include 경로를 안 넘겨 앱 코드는 전처리가 조용히 실패 → 원문 폴백. 전처리가 닿은 함수는 6%(72/1,141) · PDS64 는 0/515.
- 닿은 72개에선 설명 주석이 있던 52개가 **전부** 주석을 잃어 문서가 추론 문장을 실었고(`description_source`
  comment→inference 52), 헤더 선언이 포함한 파일의 전역으로 잡혀 전역 1,327 → 25,005 · 718개가 그 이름이 없는 파일에 귀속.
- 입력·출력·호출 칸의 이득은 0. 실패 파일 하나에 spawn 6회(179회 33.8초), 성공 도구 라벨도 틀렸다.

모든 기존 테스트는 `preprocess=False` 를 명시해 라이브 경로(True)를 한 번도 지나지 않았다 — 이 파일은 **기본 인자**로 돈다.
"""
from __future__ import annotations

import ast
import inspect
import os
import subprocess
from pathlib import Path

import pytest

from workflow.code_parser import c_parser as cp

_REPO = Path(__file__).resolve().parents[2]


def _calls_with_preprocess_true(src: str) -> list:
    """`…(preprocess=True)` 호출의 줄 번호 — 주석·docstring 속 문구는 세지 않는다(AST)."""
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "preprocess" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    out.append(node.lineno)
    return out


def _production_py_files() -> list:
    """서버가 import 하는 트리(`tools/`·`scripts/` 의 진단 도구는 뺀다 — `tools/setup_code_parsers.py` 는 일부러 True 를 쓴다)."""
    skip = {"venv", ".venv", "node_modules", "site-packages", "__pycache__"}
    files = [_REPO / "report_generator.py"]
    for top in ("backend", "workflow", "report_gen", "generators"):
        for dirpath, dirnames, filenames in os.walk(_REPO / top):
            dirnames[:] = [d for d in dirnames if d not in skip]
            files += [Path(dirpath) / fn for fn in filenames if fn.endswith(".py")]
    return files


_SRC = """\
#include "not_on_any_include_path.h"

/* Initialises the widget driver. */
void Widget_Init(void)
{
    Widget_Reset();
}

void Widget_Reset(void)
{
}
"""


@pytest.fixture()
def src_tree(tmp_path):
    d = tmp_path / "src"
    d.mkdir()
    (d / "widget.c").write_text(_SRC, encoding="utf-8")
    return d


@pytest.fixture()
def spawn_log(monkeypatch):
    """테스트 동안 **프로세스 전역** `subprocess.run` 을 기록하고 실패로 돌려준다(`cp.subprocess` 는 모듈 그 자체다).
    전처리기가 어느 파일도 못 읽는 PC 와 같은 관측."""
    calls = []

    def _fake_run(args, **_kw):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"fatal error: x.h: No such file or directory")

    monkeypatch.setattr(cp.subprocess, "run", _fake_run)
    return calls


class TestDefaultPathDoesNotPreprocess:
    def test_the_four_defaults_are_false_and_agree(self):
        from backend.helpers import uds as uds_helpers
        from report_gen.uds_generator import generate_uds_source_sections

        defaults = {
            "parse_c_project": inspect.signature(cp.parse_c_project).parameters["preprocess"].default,
            "generate_uds_source_sections": inspect.signature(generate_uds_source_sections).parameters["preprocess"].default,
            "_get_source_sections_cached": inspect.signature(uds_helpers._get_source_sections_cached).parameters["preprocess"].default,
            "_source_sections_disk_cache_path": inspect.signature(uds_helpers._source_sections_disk_cache_path).parameters["preprocess"].default,
        }
        assert defaults == dict.fromkeys(defaults, False)

    def test_preprocess_cannot_arrive_as_a_positional_argument(self):
        # 위치 인자 True 는 아래 키워드 스캔이 못 본다 — 구조적으로 막는다
        from backend.helpers import uds as uds_helpers
        from report_gen.uds_generator import generate_uds_source_sections

        for fn in (cp.parse_c_project, generate_uds_source_sections, uds_helpers._get_source_sections_cached):
            assert inspect.signature(fn).parameters["preprocess"].kind is inspect.Parameter.KEYWORD_ONLY, fn.__name__

    def test_generating_sections_with_default_arguments_spawns_nothing(self, src_tree, spawn_log):
        from report_gen.uds_generator import generate_uds_source_sections

        sections = generate_uds_source_sections(str(src_tree))
        assert spawn_log == []
        names = {d["name"] for d in sections["function_details"].values()}
        assert names == {"Widget_Init", "Widget_Reset"}

    def test_the_source_comment_reaches_the_document_description(self, src_tree, spawn_log):
        from report_gen.uds_generator import generate_uds_source_sections

        details = generate_uds_source_sections(str(src_tree))["function_details"].values()
        info = next(d for d in details if d["name"] == "Widget_Init")
        assert info["description_source"] == "comment"
        assert "Initialises the widget driver" in info["description"]

    def test_impact_analysis_loads_sections_with_the_same_arguments_as_document_generation(self, monkeypatch):
        import backend.helpers as helpers
        from workflow import impact_orchestrator as io

        seen = []

        def _fake_cached(source_root, *args, **kwargs):
            seen.append((source_root, args, kwargs))
            return {"function_details": {}}

        monkeypatch.setattr(helpers, "_get_source_sections_cached", _fake_cached)
        io._load_source_sections("X:/some/root")
        assert seen == [("X:/some/root", (), {})]

    def test_no_production_caller_opts_into_preprocessing(self):
        files = _production_py_files()
        assert len(files) > 100   # 스캔이 비면 아래 단언이 공허하게 통과한다
        probe = "; ".join(["f(preprocess=True)", "g(preprocess=False)", "h(preprocess=x)", "'preprocess=True'"])
        assert _calls_with_preprocess_true(probe) == [1]
        hits = []
        for p in files:
            src = p.read_text(encoding="utf-8", errors="ignore")
            if "preprocess" not in src:
                continue
            hits += [f"{p.relative_to(_REPO)}:{no}" for no in _calls_with_preprocess_true(src)]
        assert hits == []


class TestWhyThePreprocessedPathIsATrap:
    """`preprocess=True` 를 명시하면 여전히 돈다 — 그때 무슨 일이 생기는지를 고정해 둔다(기본값을 되돌리려는 사람이 읽을 것)."""

    def test_preprocessed_input_loses_the_function_comment(self, src_tree, monkeypatch):
        stripped = b'# 1 "widget.c"\nvoid Widget_Init(void)\n{\n    Widget_Reset();\n}\nvoid Widget_Reset(void)\n{\n}\n'

        def _fake_run(args, **_kw):
            return subprocess.CompletedProcess(args, 0, stdout=stripped, stderr=b"")

        monkeypatch.setattr(cp.subprocess, "run", _fake_run)
        raw = {f["name"]: f for f in cp.parse_c_project(str(src_tree))["functions"]}
        pre = {f["name"]: f for f in cp.parse_c_project(str(src_tree), preprocess=True)["functions"]}
        assert "Initialises the widget driver" in raw["Widget_Init"]["comment_desc"]
        assert pre["Widget_Init"]["comment_desc"] == ""

    def test_a_header_declaration_becomes_a_global_of_the_including_file(self, src_tree, monkeypatch):
        expanded = b'# 1 "io_map.h"\nextern volatile unsigned char REG_A;\n# 3 "widget.c"\nvoid Widget_Reset(void)\n{\n}\n'

        def _fake_run(args, **_kw):
            return subprocess.CompletedProcess(args, 0, stdout=expanded, stderr=b"")

        monkeypatch.setattr(cp.subprocess, "run", _fake_run)
        raw = cp.parse_c_project(str(src_tree))
        pre = cp.parse_c_project(str(src_tree), preprocess=True)
        assert "REG_A" not in {g["name"] for g in raw["globals_detailed"]}
        owners = {Path(g["file"]).name for g in pre["globals_detailed"] if g["name"] == "REG_A"}
        assert owners == {"widget.c"}

    def test_a_failed_preprocess_silently_falls_back_to_the_raw_file_and_says_so_only_in_stats(self, src_tree, spawn_log):
        res = cp.parse_c_project(str(src_tree), preprocess=True)
        assert {f["name"] for f in res["functions"]} == {"Widget_Init", "Widget_Reset"}
        assert res["preprocess_stats"]["no-preprocess"] == 1
        assert res["preprocess_stats"]["gcc"] == 0


class TestEachToolIsTriedOnce:
    def test_a_file_no_tool_can_preprocess_costs_one_spawn_per_tool(self, src_tree, spawn_log):
        data, tool = cp._run_preprocessor_fallback(src_tree / "widget.c")
        assert (data, tool) == (None, "no-preprocess")
        assert [c[0] for c in spawn_log] == ["gcc", "clang", "cl.exe"]

    def test_the_requested_tool_goes_first_and_is_not_repeated(self, src_tree, spawn_log):
        cp._run_preprocessor_fallback(src_tree / "widget.c", cpp_path="clang")
        assert [c[0] for c in spawn_log] == ["clang", "gcc", "cl.exe"]

    def test_the_label_names_the_tool_that_actually_succeeded(self, src_tree, monkeypatch):
        def _fake_run(args, **_kw):
            ok = args[0] == "clang"
            return subprocess.CompletedProcess(args, 0 if ok else 1, stdout=b"int x;\n" if ok else b"", stderr=b"")

        monkeypatch.setattr(cp.subprocess, "run", _fake_run)
        data, tool = cp._run_preprocessor_fallback(src_tree / "widget.c")
        assert (data, tool) == (b"int x;\n", "clang")

    def test_partial_output_from_a_failed_run_is_not_taken_as_the_file(self, src_tree, monkeypatch):
        # gcc 는 include 를 못 찾아 rc=1 로 끝나도 그 앞까지의 전처리본을 stdout 에 쓴다 — 그걸 파일로 읽으면 뒤쪽 함수가 사라진다
        def _fake_run(args, **_kw):
            return subprocess.CompletedProcess(args, 1, stdout=b"void Half(void)\n", stderr=b"fatal error")

        monkeypatch.setattr(cp.subprocess, "run", _fake_run)
        assert cp._run_preprocessor_fallback(src_tree / "widget.c") == (None, "no-preprocess")

    def test_an_empty_success_is_not_taken_as_the_file(self, src_tree, monkeypatch):
        monkeypatch.setattr(cp.subprocess, "run", lambda args, **_kw: subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b""))
        assert cp._run_preprocessor_fallback(src_tree / "widget.c") == (None, "no-preprocess")

    def test_a_missing_tool_moves_on_to_the_next(self, src_tree, monkeypatch):
        tried = []

        def _fake_run(args, **_kw):
            tried.append(args[0])
            if args[0] == "gcc":
                raise FileNotFoundError("gcc")
            return subprocess.CompletedProcess(args, 0, stdout=b"int y;\n", stderr=b"")

        monkeypatch.setattr(cp.subprocess, "run", _fake_run)
        assert cp._run_preprocessor_fallback(src_tree / "widget.c") == (b"int y;\n", "clang")
        assert tried == ["gcc", "clang"]

    def test_include_dirs_and_defines_reach_the_command_line(self, src_tree, spawn_log):
        cp._run_preprocessor_fallback(src_tree / "widget.c", include_dirs=["inc"], defines=["A=1"])
        gcc, _clang, cl = spawn_log
        assert gcc[1] == "-E" and gcc[-4:] == ["-I", "inc", "-D", "A=1"]
        assert cl[1:3] == ["/nologo", "/EP"] and cl[-2:] == ["/Iinc", "/DA=1"]

    def test_a_tool_that_hangs_is_bounded_and_skipped(self, src_tree, monkeypatch):
        seen = []

        def _fake_run(args, **kw):
            seen.append((args[0], kw.get("timeout")))
            if args[0] == "gcc":
                raise subprocess.TimeoutExpired(args, kw.get("timeout"))
            return subprocess.CompletedProcess(args, 0, stdout=b"int t;\n", stderr=b"")

        monkeypatch.setattr(cp.subprocess, "run", _fake_run)
        assert cp._run_preprocessor_fallback(src_tree / "widget.c") == (b"int t;\n", "clang")
        assert seen == [("gcc", cp._PREPROCESS_TIMEOUT_S), ("clang", cp._PREPROCESS_TIMEOUT_S)]
        assert 0 < cp._PREPROCESS_TIMEOUT_S <= 120

    def test_an_unexpected_error_is_not_swallowed(self, src_tree, monkeypatch):
        def _boom(args, **_kw):
            raise ValueError("embedded null byte")

        monkeypatch.setattr(cp.subprocess, "run", _boom)
        with pytest.raises(ValueError):
            cp._run_preprocessor_fallback(src_tree / "widget.c")


class TestTheOtherPreprocessingPathStaysUnused:
    """(리뷰 W3) `ast_parser.preprocess_c_file` 은 플래그 없이 **무조건** `gcc -E -P` 를 돌고 실패하면 조용히 원문으로
    돌아간다 — 위에서 끈 것과 같은 함정이고 `preprocess=True` 키워드 스캔으론 안 보인다. 지금은 호출자가 없다. 생기면 여기서 걸린다."""

    def test_nothing_outside_the_package_uses_the_unconditional_preprocessor(self):
        names = ("preprocess_c_file", "parse_source_root")
        files = _production_py_files()
        assert len(files) > 100
        hits = []
        for p in files:
            if p.parent == _REPO / "workflow" / "code_parser":
                continue
            src = p.read_text(encoding="utf-8", errors="ignore")
            hits += [f"{p.relative_to(_REPO)}: {n}" for n in names if n in src]
        assert hits == []
        assert (_REPO / "workflow" / "code_parser" / "ast_parser.py").read_text(encoding="utf-8").count("def preprocess_c_file") == 1


_DIAG_SRC = """\
void Diag_Handler(void)
{   /* DID: 0x1002 */
    U16 u16t_Did = 0xF190;   /* TIM0TC3: BIT=0x0186 */
    S32 s32t_Max = 32767;    // 0x7FFF
    /* Extract TableID from request (PCI 0x03 SID 0x22 DID_H 0xF2 DID_L 0xF2 [TableID]) */
    //u16g_Time = (U16)((0xFF00 & (u8t_Data[6]<<8U)) | (0x00FF & u8t_Data[7]));
    /* Build response header for unified
       DID 0xF2F0 */
    /* timer reload
       value 0x0BB8 */
    Diag_Send(u16t_Did);
}
"""


class TestDidsMentionedOnlyInComments:
    """(리뷰 W1) 전처리가 주석을 지우던 시절엔 가려져 있던 축 — 주석 속 16진 4자리가 DID 표에 실렸다.
    KJPDS02 실측: 124건 중 13건이 주석에만 있고, 그중 **4건은 진짜 DID**(주석이 `DID` 라고 말한다)·9건은 아니다."""

    @pytest.fixture()
    def sections(self, tmp_path):
        from report_gen.uds_generator import generate_uds_source_sections

        d = tmp_path / "diag"
        d.mkdir()
        (d / "diag.c").write_text(_DIAG_SRC, encoding="utf-8")
        return generate_uds_source_sections(str(d))

    def test_the_did_table_keeps_code_and_did_comments_and_drops_the_rest(self, sections):
        assert sorted(sections["did_entries"]) == ["0x1002", "0xF190", "0xF2F0"]
        assert sections["did_function_map"] == {"0x1002": ["Diag_Handler"], "0xF190": ["Diag_Handler"], "0xF2F0": ["Diag_Handler"]}

    def test_the_helper_counts_what_it_dropped(self):
        import re

        from report.constants import UDS_DID_PATTERNS
        from report_gen.uds_generator import _did_pattern_hits

        pats = [re.compile(p, re.I) for p in UDS_DID_PATTERNS]
        vals, dropped = _did_pattern_hits(_DIAG_SRC, pats)
        assert sorted(vals) == ["0x1002", "0xF190", "0xF2F0"]
        assert dropped == 7   # 0x0186 · 0x7FFF · DID_H · DID_L · 0xFF00 · 0x00FF · 0x0BB8(여러 줄 주석)

    def test_a_body_without_comments_is_untouched(self):
        import re

        from report_gen.uds_generator import _did_pattern_hits

        pats = [re.compile(r"\b0x[0-9A-Fa-f]{4}\b"), re.compile(r"\bDID_\w+")]
        assert _did_pattern_hits("x = 0xF190; y = DID_VIN; z = 0xF190;", pats) == (["0xF190", "0xF190", "DID_VIN"], 0)
