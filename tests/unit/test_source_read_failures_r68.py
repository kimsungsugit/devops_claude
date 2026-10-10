"""R68 (input loss audit #16) — a source file that could not be read is a read failure, not an empty file.

Before R68 every source read swallowed its exception into ``""``: a file the worker timed out on (Cloudium IPC) or the OS
refused looked exactly like an empty file. The functions defined there reached SUTS with no text and the unit's reason
said ``source_file_not_in_source_stage`` — a file the source stage never saw, which is false. The global scan re-read
every ``.c`` and stored what it got, so a transient failure there overwrote text the first loop had read; the cached
source sections (in-memory TTL, disk) kept the failure for the next generation; and when the worker read failed, the
local-path fallback's ``FileNotFoundError`` hid the worker's own exception (``utils._infer_type_from_file`` caches a
``FileNotFoundError`` as "no such file").

Review round 1 (C1 · W1): "a later read clears the failure" is wrong for what only one read collects — the main text loop
alone collects comments (``@asil``), macros, typedefs, enums and fallback function records, so a file it missed is counted
even when a later read gets the text, and a function record given ``source_read_failed`` stays counted.
"""
from __future__ import annotations

import os
import pathlib
from pathlib import Path

import pytest

from report_gen import source_parser as sp
from report_gen import uds_generator as ug
from report_gen.generation_disclosures import build_disclosures

NL = "\n"


def _src(*lines: str) -> str:
    return NL.join(lines) + NL


# ── the reader says why ─────────────────────────────────────────────────────────────────────────────────────────

def test_a_checked_read_names_the_failure_and_an_empty_file_is_no_failure(tmp_path):
    text, n, cut, err = sp._read_source_text_checked(tmp_path / "missing.c")
    assert (text, n, cut, err) == ("", 0, False, "FileNotFoundError")
    (tmp_path / "empty.c").write_bytes(b"")
    assert sp._read_source_text_checked(tmp_path / "empty.c") == ("", 0, False, "")
    (tmp_path / "a.c").write_bytes(b"int a;\n")
    assert sp._read_source_text_checked(tmp_path / "a.c")[3] == ""
    assert sp._read_source_text(tmp_path / "a.c") == ("int a;\n", 7, False)    # the old three-tuple contract


class _FailingWorker:
    mode = "cloudium"

    def __init__(self, exc):
        self.exc = exc

    def read_bytes(self, _path):
        raise self.exc


def test_the_workers_failure_is_not_masked_by_the_local_fallback(tmp_path, monkeypatch):
    from backend.services import file_resolver as fr
    monkeypatch.setattr(fr, "get_resolver", lambda: _FailingWorker(TimeoutError("worker did not answer")))
    with pytest.raises(TimeoutError):
        sp._read_bytes_resolver_aware(tmp_path / "on_the_worker_only.c")
    assert sp._read_source_text_checked(tmp_path / "on_the_worker_only.c")[3] == "TimeoutError"
    # a path the local disk has is still read from there (the fallback is kept)
    (tmp_path / "local.c").write_bytes(b"int x;\n")
    assert sp._read_bytes_resolver_aware(tmp_path / "local.c") == b"int x;\n"


def test_a_masked_timeout_is_no_longer_cached_as_a_missing_file(tmp_path, monkeypatch):
    from backend.services import file_resolver as fr
    from report_gen.utils import _infer_type_from_file
    monkeypatch.setattr(fr, "get_resolver", lambda: _FailingWorker(TimeoutError()))
    cache: dict = {}
    assert _infer_type_from_file(str(tmp_path / "remote.h"), "g_x", cache=cache) == ("", "")
    assert cache == {}, "a transient worker failure cached as an empty file hides every global of that file"


def test_the_summary_is_the_union_of_what_each_failure_cost():
    roots = ["/r/app", "/r/boot"]
    failed = {"/r/app/a.c": "PermissionError", "/r/app/b.c": "TimeoutError", "/r/boot/c.h": "TimeoutError"}
    texts = {"/r/app/b.c": "int b;"}                      # b.c: the last read got it — nothing lost by that read
    got = ug.summarize_read_failures(failed, texts, scan_missed={"/r/boot/main.c": "TimeoutError"},
                                     record_failed={"/r/app/a.c": "PermissionError"}, roots=roots)
    assert got["files"] == 3 and got["kinds"] == {"PermissionError": 1, "TimeoutError": 2}
    assert got["lost"] == {"scan": 1, "function_text": 1, "text": 2}
    assert got["detail"] == [
        {"file": "r0:app/a.c", "error": "PermissionError", "lost": ["function_text", "text"]},
        {"file": "r1:boot/c.h", "error": "TimeoutError", "lost": ["text"]},
        {"file": "r1:boot/main.c", "error": "TimeoutError", "lost": ["scan"]}]      # root index: APP and BOOT twins apart
    assert ug.summarize_read_failures({}, {}) == {"files": 0, "kinds": {}, "lost": {}, "headers_scan_missed": [], "detail": []}


# ── the source stage ────────────────────────────────────────────────────────────────────────────────────────────

APP = _src("unsigned char g_a;", "void app_fn(void)", "{", "    g_a = 1U;", "}")
LOST = _src("unsigned char g_b;", "void lost_one(void)", "{", "    g_b = 2U;", "}",
            "void lost_two(void)", "{", "    g_b = 3U;", "}")


def _fail_reads(monkeypatch, target: Path, *, checked=lambda n: True, src_read=lambda n: True, exc=PermissionError):
    """Fail the source stage's text reads of ``target`` — the main loop's checked read on the calls ``checked(n)`` says,
    ``_src_read`` (global scan · function-file re-read · context walk) on the calls ``src_read(n)`` says (1-based). The
    parser's byte read is untouched, so the file's functions exist. Returns the attempt counters."""
    attempts = {"checked": 0, "src_read": 0}
    real_checked = ug._read_source_text_checked
    real_read_text = pathlib.Path.read_text

    def checked_read(p, *a, **k):
        if Path(p) == target:
            attempts["checked"] += 1
            if checked(attempts["checked"]):
                return "", 0, False, exc.__name__
        return real_checked(p, *a, **k)

    def read_text(self, *a, **k):
        # `_src_read` reads with errors="replace"; the parser's comment read uses errors="ignore" — leave that one alone
        if Path(self) == target and k.get("errors") == "replace":
            attempts["src_read"] += 1
            if src_read(attempts["src_read"]):
                raise exc("denied")
        return real_read_text(self, *a, **k)

    monkeypatch.setattr(ug, "_read_source_text_checked", checked_read)
    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    return attempts


def _details(sec):
    return {d["name"]: d for d in sec["function_details"].values()}


def _tree(tmp_path, lost_body=LOST, name="lost.c"):
    (tmp_path / "app.c").write_bytes(APP.encode())
    target = tmp_path / name
    target.write_bytes(lost_body.encode())
    return target.resolve()


def test_a_file_that_cannot_be_read_says_so_in_every_function_it_defines(tmp_path, monkeypatch):
    attempts = _fail_reads(monkeypatch, _tree(tmp_path))
    sec = ug.generate_uds_source_sections(str(tmp_path))
    d = _details(sec)
    assert d["lost_one"]["source_unavailable_reason"] == "source_read_failed:PermissionError"
    assert d["lost_two"]["source_unavailable_reason"] == "source_read_failed:PermissionError"
    assert not d["lost_one"]["source_text_complete"]
    assert d["app_fn"]["source_unavailable_reason"] == "" and d["app_fn"]["source_text_complete"]
    rf = sec["source_read_failures"]
    # (the tree has no `.cproject` — a file that may or may not exist is no read failure when it is absent)
    assert (rf["files"], rf["kinds"], rf["lost"]) == (1, {"PermissionError": 1}, {"scan": 1, "function_text": 1, "text": 1})
    assert rf["detail"][0]["file"].startswith("r0:") and rf["detail"][0]["file"].endswith("/lost.c")
    assert all(Path(p).name != "lost.c" for p in sec["source_files"])
    assert attempts["checked"] == 2, "the main loop retries once — what it collects comes from no other read"


def test_a_main_scan_failure_the_retry_recovers_is_no_failure(tmp_path, monkeypatch):
    _fail_reads(monkeypatch, _tree(tmp_path), checked=lambda n: n == 1, src_read=lambda n: False)
    sec = ug.generate_uds_source_sections(str(tmp_path))
    assert sec["source_read_failures"]["files"] == 0
    assert _details(sec)["lost_one"]["source_text_complete"]


def test_a_main_scan_failure_is_counted_even_when_a_later_read_gets_the_text(tmp_path, monkeypatch):
    # review C1: the header the main scan missed loses its typedef / doc ASIL for the run, though the global scan reads it
    _fail_reads(monkeypatch, _tree(tmp_path), src_read=lambda n: False)
    sec = ug.generate_uds_source_sections(str(tmp_path))
    d = _details(sec)
    assert d["lost_one"]["source_unavailable_reason"] == "" and d["lost_one"]["source_text_complete"]
    rf = sec["source_read_failures"]
    assert (rf["files"], rf["lost"]) == (1, {"scan": 1}), "a lossy result certified clean is cached for the TTL"


def test_a_failed_function_file_is_read_once_more_and_that_read_counts(tmp_path, monkeypatch):
    # the main scan and the global scan fail; the function loop's one re-read gets the text — the records have it
    attempts = _fail_reads(monkeypatch, _tree(tmp_path), src_read=lambda n: n == 1)
    sec = ug.generate_uds_source_sections(str(tmp_path))
    d = _details(sec)
    assert d["lost_one"]["source_unavailable_reason"] == "" and d["lost_one"]["source_text_complete"]
    assert any(Path(p).name == "lost.c" for p in sec["source_files"])
    assert sec["source_read_failures"]["lost"] == {"scan": 1}
    assert attempts["src_read"] == 2


def test_a_record_given_the_failure_stays_counted_when_the_context_walk_reads_the_file(tmp_path, monkeypatch):
    # review W1: main scan, global scan and the re-read fail; the project-context walk succeeds into its own texts
    _fail_reads(monkeypatch, _tree(tmp_path), src_read=lambda n: n <= 2)
    sec = ug.generate_uds_source_sections(str(tmp_path))
    assert _details(sec)["lost_one"]["source_unavailable_reason"] == "source_read_failed:PermissionError"
    rf = sec["source_read_failures"]
    assert rf["files"] == 1 and rf["lost"] == {"scan": 1, "function_text": 1}


def test_a_header_read_failure_the_context_walk_recovers_costs_nothing(tmp_path, monkeypatch):
    # the main loop read the header; the global header scan's read fails; the context walk reads it — nothing lost
    (tmp_path / "app.c").write_bytes(('#include "types.h"\n' + APP).encode())
    hdr = tmp_path / "types.h"
    hdr.write_bytes(b"typedef unsigned char MyByte;\n")
    _fail_reads(monkeypatch, hdr.resolve(), checked=lambda n: False, src_read=lambda n: n == 1)
    sec = ug.generate_uds_source_sections(str(tmp_path))
    assert sec["source_read_failures"]["files"] == 0
    assert "MyByte" in str(sec["project_context"].get("files", {}).get(str(hdr.resolve()), ""))


def test_a_failed_reread_does_not_overwrite_the_text_already_read(tmp_path, monkeypatch):
    _fail_reads(monkeypatch, _tree(tmp_path), checked=lambda n: False)        # the first loop reads it; re-reads fail
    sec = ug.generate_uds_source_sections(str(tmp_path))
    d = _details(sec)
    assert d["lost_one"]["source_text_complete"] and d["lost_one"]["source_unavailable_reason"] == ""
    assert any(Path(p).name == "lost.c" and "lost_two" in t for p, t in sec["source_files"].items())
    assert sec["source_read_failures"]["files"] == 0


def test_a_failed_file_is_read_once_more_not_once_per_function(tmp_path, monkeypatch):
    many = _src("unsigned char g_c;", *[f"void f{i}(void)\n{{\n    g_c = {i}U;\n}}" for i in range(6)])
    counts = {}
    for name, body in (("one", LOST), ("six", many)):
        root = tmp_path / name
        root.mkdir()
        with monkeypatch.context() as m:
            attempts = _fail_reads(m, _tree(root, body))
            ug.generate_uds_source_sections(str(root))
        counts[name] = attempts["src_read"]
    assert counts["one"] == counts["six"], counts      # bounded by the file, not by its functions (60 s worker timeouts)
    assert counts["six"] <= 4, counts


# ── the cache ───────────────────────────────────────────────────────────────────────────────────────────────────

def _cache_probe(tmp_path, monkeypatch, failures, ttl=None, gap=1.0):
    """Two `_get_source_sections_cached` calls ``gap`` seconds apart (a fixed clock); returns the parses it made."""
    from backend.helpers import uds as uds_mod
    monkeypatch.setattr(uds_mod, "_source_sections_disk_cache_path", lambda *a, **k: tmp_path / "disk.json")
    if ttl is not None:
        monkeypatch.setattr(uds_mod, "_FAILED_SECTIONS_TTL", ttl)
    clock = {"now": 1000.0}
    monkeypatch.setattr(uds_mod, "time", lambda: clock["now"])
    calls = []

    def fake_generate(*a, **k):
        calls.append(1)
        return {"function_details": {}, "source_read_failures": failures}

    monkeypatch.setattr(uds_mod, "generate_uds_source_sections", fake_generate)
    src = tmp_path / "src"
    src.mkdir(parents=True)
    (src / "a.c").write_bytes(b"int a;\n")
    uds_mod._get_source_sections_cached(str(src))
    clock["now"] += gap
    uds_mod._get_source_sections_cached(str(src))
    return calls


FAILED = {"files": 1, "kinds": {"TimeoutError": 1}, "lost": {"text": 1}, "detail": []}


def test_a_result_with_read_failures_stays_in_memory_briefly_and_never_on_disk(tmp_path, monkeypatch):
    assert len(_cache_probe(tmp_path, monkeypatch, FAILED)) == 1, "a batch of generations shares one parse (review W3)"
    assert not (tmp_path / "disk.json").exists()


def test_a_result_with_read_failures_expires_by_its_own_ttl(tmp_path, monkeypatch):
    # 100 s later: past the failure TTL (90 s), well inside the ordinary one (30 min) — the next generation reads again
    assert len(_cache_probe(tmp_path, monkeypatch, FAILED, gap=100.0)) == 2
    assert len(_cache_probe(tmp_path / "x", monkeypatch, FAILED, ttl=0)) == 2      # 0: never held
    assert not (tmp_path / "disk.json").exists()


def test_a_result_without_read_failures_is_cached_on_disk(tmp_path, monkeypatch):
    assert len(_cache_probe(tmp_path, monkeypatch, {"files": 0, "kinds": {}, "lost": {}, "detail": []})) == 1
    assert (tmp_path / "disk.json").exists()


def test_the_source_stage_reports_the_failure_as_an_issue():
    from backend.helpers.uds import _note_source_caps
    from report_gen.gen_issues import IssueCollector
    issues = IssueCollector()
    _note_source_caps(issues, {"source_read_failures": {"files": 2, "kinds": {"PermissionError": 2}, "lost": {"scan": 2},
                                                        "detail": [{"file": "r0:app/a.c", "error": "PermissionError"}]}})
    got = [i for i in issues.as_list() if i["code"] == "source_read_failed"]
    assert len(got) == 1 and "2개" in got[0]["message"] and "PermissionError 2" in got[0]["message"]
    assert "워커 타임아웃" in got[0]["message"]                 # review I3: the worker's timeout arrives as PermissionError
    quiet = IssueCollector()
    _note_source_caps(quiet, {"source_read_failures": {"files": 0, "kinds": {}, "detail": []}})
    assert not [i for i in quiet.as_list() if i["code"] == "source_read_failed"]


def test_the_issue_says_reset_values_were_blanked_only_when_the_scan_missed_a_file():
    # review round 4 W2: a `.cproject` the context could not read costs no scan — its Reset Values are not blanked
    from backend.helpers.uds import _note_source_caps
    from report_gen.gen_issues import IssueCollector
    msgs = {}
    for name, lost in (("scan", {"scan": 1}), ("text", {"text": 1})):
        issues = IssueCollector()
        _note_source_caps(issues, {"source_read_failures": {"files": 1, "kinds": {"TimeoutError": 1}, "lost": lost,
                                                            "detail": []}})
        msgs[name] = next(i["message"] for i in issues.as_list() if i["code"] == "source_read_failed")
    assert "Reset Value" in msgs["scan"] and "Reset Value" not in msgs["text"]


def test_the_issue_has_a_rule_explanation():
    from backend.services.issue_explainer import rule_action
    assert "읽지 못했다" in rule_action("source_read_failed")


# ── SUTS · SITS ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_suts_keeps_the_reason_and_counts_the_units():
    from generators.suts import attach_unit_sources, summarize_source_read_failures
    units = [{"name": "lost_one", "source_path": "/r/lost.c", "source_unavailable_reason": "source_read_failed:TimeoutError"},
             {"name": "gone", "source_path": "/r/gone.c"},
             {"name": "fine", "source_path": "/r/fine.c"}]
    attach_unit_sources(units, {"/r/fine.c": "void fine(void) {}"}, None)
    assert units[0]["source_unavailable_reason"] == "source_read_failed:TimeoutError"
    assert units[1]["source_unavailable_reason"] == "source_file_not_in_source_stage"
    assert "source_unavailable_reason" not in units[2]
    block = {"files": 1, "kinds": {"TimeoutError": 1}, "lost": {"function_text": 1},
             "detail": [{"file": "r0:app/lost.c", "error": "TimeoutError", "lost": ["function_text"]}]}
    assert summarize_source_read_failures(block, units) == {**block, "headers_scan_missed": [], "units": 1,
                                                            "unit_samples": ["lost_one"]}
    assert summarize_source_read_failures(None, [])["files"] == 0


BLOCK = {"files": 1, "kinds": {"PermissionError": 1}, "lost": {"scan": 1, "function_text": 1},
         "detail": [{"file": "r0:app/lost.c", "error": "PermissionError", "lost": ["scan", "function_text"]}],
         "units": 2, "unit_samples": ["lost_one", "lost_two"]}


@pytest.mark.parametrize("doc, key, who", [("suts", "suts_source_read_failures", "unit"),
                                           ("sits", "sits_source_read_failures", "함수")])
def test_the_disclosure_names_the_file_the_kind_what_was_lost_and_the_functions(doc, key, who):
    q = {"source_read_failures": BLOCK} if doc == "suts" else {"source_read_failures": BLOCK, "integration_oracle": {}}
    item = next(i for i in build_disclosures(doc, q) if i["key"] == key)
    assert item["value"] == f"파일 1 · 원문 없는 {who} 2" and item["tone"] == "warning"
    for want in ("r0:app/lost.c(PermissionError)", "PermissionError 1", "워커 타임아웃", "lost_one", "source_read_failed",
                 "읽기 실패", "파일 머리 ASIL", "목록에 없다", "Reset Value", "소스 스캔 불완전"):
        assert want in item["note"], want
    assert "unit 정의 파일은 아니지만" not in item["note"]       # review W2: an unreadable file's functions may be missing


def test_functions_without_text_are_disclosed_even_when_no_file_is_counted():
    item = next(i for i in build_disclosures("suts", {"source_read_failures": {**BLOCK, "files": 0, "detail": [],
                                                                               "lost": {}, "kinds": {}}})
                if i["key"] == "suts_source_read_failures")
    assert "lost_one" in item["note"]
    none = {"files": 0, "kinds": {}, "lost": {}, "detail": [], "units": 0, "unit_samples": []}
    assert not [i for i in build_disclosures("suts", {"source_read_failures": none})
                if i["key"] == "suts_source_read_failures"]


# ── review round 2 ──────────────────────────────────────────────────────────────────────────────────────────────

TYPES_H = _src("/** @brief state type */", "typedef unsigned char MyByte;", "typedef enum { ST_A, ST_B } State_t;")


def test_the_deferred_retry_restores_what_only_the_main_scan_collects(tmp_path, monkeypatch):
    # W-C: the main scan misses the header once; read again after the other files, it collects the typedef / enum
    (tmp_path / "app.c").write_bytes(('#include "types.h"\n' + APP).encode())
    hdr = tmp_path / "types.h"
    hdr.write_bytes(TYPES_H.encode())
    attempts = _fail_reads(monkeypatch, hdr.resolve(), checked=lambda n: n == 1, src_read=lambda n: False)
    sec = ug.generate_uds_source_sections(str(tmp_path))
    assert "MyByte" in sec["typedef_aliases"] and "State_t" in sec["enum_domains"]
    assert sec["source_read_failures"]["files"] == 0 and attempts["checked"] == 2


def test_a_header_the_main_scan_never_read_is_counted_and_named(tmp_path, monkeypatch):
    (tmp_path / "app.c").write_bytes(('#include "types.h"\n' + APP).encode())
    hdr = tmp_path / "types.h"
    hdr.write_bytes(TYPES_H.encode())
    _fail_reads(monkeypatch, hdr.resolve(), src_read=lambda n: False)        # the global scan reads it — too late
    sec = ug.generate_uds_source_sections(str(tmp_path))
    assert "MyByte" not in sec["typedef_aliases"]
    rf = sec["source_read_failures"]
    assert rf["lost"] == {"scan": 1} and rf["detail"][0]["file"].endswith("/types.h")
    item = next(i for i in build_disclosures("suts", {"source_read_failures": {**rf, "units": 0, "unit_samples": []}})
                if i["key"] == "suts_source_read_failures")
    assert "types.h" in item["note"] and "다른 파일" in item["note"] and "TBD" in item["note"]


def test_a_record_stamped_before_a_later_read_got_the_text_is_restamped(tmp_path, monkeypatch):
    # W-A: a verify=X file is first read by the record loop — the first read fails (lost_one stamped), the one re-read for
    #   lost_two gets the text; the file is in `source_files`, so lost_one has its text too
    _fail_reads(monkeypatch, _tree(tmp_path), checked=lambda n: False, src_read=lambda n: n == 1)
    sec = ug.generate_uds_source_sections(str(tmp_path), component_map={"lost.c": {"verify": "X"}})
    d = _details(sec)
    assert (d["lost_one"]["source_unavailable_reason"], d["lost_one"]["source_text_complete"]) == ("", True)
    assert (d["lost_two"]["source_unavailable_reason"], d["lost_two"]["source_text_complete"]) == ("", True)
    assert any(Path(p).name == "lost.c" for p in sec["source_files"])
    assert "function_text" not in sec["source_read_failures"]["lost"]


def test_a_cpp_file_never_read_costs_no_c_text():
    got = ug.summarize_read_failures({"/r/app/x.cpp": "PermissionError", "/r/app/y.c": "PermissionError"}, {},
                                     roots=["/r/app"])
    assert got["files"] == 1 and got["detail"][0]["file"] == "r0:app/y.c"


def test_a_cproject_that_exists_but_cannot_be_read_is_counted(tmp_path, monkeypatch):
    # its toolchain macros are lost; an absent `.cproject` is no failure (the other tests' trees have none)
    (tmp_path / "app.c").write_bytes(APP.encode())
    cp = tmp_path / ".cproject"
    cp.write_bytes(b"<cproject/>\n")
    _fail_reads(monkeypatch, cp.resolve(), checked=lambda n: False)
    rf = ug.generate_uds_source_sections(str(tmp_path))["source_read_failures"]
    assert rf["files"] == 1 and rf["detail"][0]["file"].endswith("/.cproject") and rf["lost"] == {"text": 1}


def test_the_failure_ttl_counts_from_the_end_of_a_long_parse(tmp_path, monkeypatch):
    # W-B: a Cloudium parse takes minutes; timed from its start the result expired the moment it was stored
    from backend.helpers import uds as uds_mod
    monkeypatch.setattr(uds_mod, "_source_sections_disk_cache_path", lambda *a, **k: tmp_path / "disk.json")
    clock = {"now": 1000.0}
    monkeypatch.setattr(uds_mod, "time", lambda: clock["now"])
    calls = []

    def slow_generate(*a, **k):
        calls.append(1)
        clock["now"] += 300.0                     # a 5-minute parse
        return {"function_details": {}, "source_read_failures": FAILED}

    monkeypatch.setattr(uds_mod, "generate_uds_source_sections", slow_generate)
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.c").write_bytes(b"int a;\n")
    uds_mod._get_source_sections_cached(str(src))
    clock["now"] += 10.0
    uds_mod._get_source_sections_cached(str(src))
    assert len(calls) == 1


def test_the_failure_ttl_is_never_longer_than_the_configured_one(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "UDS_SOURCE_SECTIONS_CACHE_TTL", 5)
    assert len(_cache_probe(tmp_path, monkeypatch, FAILED, gap=10.0)) == 2


def test_suts_and_sits_carry_the_stage_failures_into_their_quality_reports(tmp_path, monkeypatch):
    # W-D: the wiring lines themselves — a real generation whose callee file cannot be read
    from generators import sits as gsits
    from generators import suts as gsuts
    monkeypatch.setattr(gsuts, "_OVERRIDE_JSON_CANDIDATES", ())
    (tmp_path / "a.c").write_bytes(b"void B(void);\nvoid A(void)\n{\n    B();\n}\n")
    b = tmp_path / "b.c"
    b.write_bytes(b"unsigned char g_b;\nvoid B(void)\n{\n    g_b = 1U;\n}\n")
    _fail_reads(monkeypatch, b.resolve())
    q = gsuts.generate_suts(source_root=str(tmp_path), output_path=str(tmp_path / "u.xlsm"), scope="source")["quality_report"]
    rf = q["source_read_failures"]
    assert rf["files"] == 1 and rf["units"] >= 1 and "B" in rf["unit_samples"]
    assert any(i["key"] == "suts_source_read_failures" for i in build_disclosures("suts", q))
    out = gsits.generate_sits(source_root=str(tmp_path), output_path=str(tmp_path / "i.xlsm"))
    qs = out.get("quality_report") or {}
    assert qs, f"no flows — the SITS half of this test would be empty: {out.get('error')}"
    assert qs["source_read_failures"]["files"] == 1 and "B" in qs["source_read_failures"]["unit_samples"]
    assert any(i["key"] == "sits_source_read_failures" for i in build_disclosures("sits", qs))


# ── review round 3 ──────────────────────────────────────────────────────────────────────────────────────────────

def _twin_headers(root: Path) -> Path:
    """Two headers that disagree (APP/BOOT-like): the same macro and the same struct member, different values/types."""
    for sub, (dim, mtype) in (("a", ("4U", "unsigned char")), ("b", ("8U", "unsigned short"))):
        (root / sub).mkdir(parents=True)
        (root / sub / f"h_{sub}.h").write_bytes(
            _src(f"#define DIM {dim}", f"typedef struct {{ {mtype} m; }} S_t;").encode())
    (root / "app.c").write_bytes(APP.encode())
    return (root / "a" / "h_a.h").resolve()


def test_a_transient_failure_does_not_change_what_order_dependent_collectors_keep(tmp_path, monkeypatch):
    # review round 3 W1: a failed file retried at the end of the loop moved its macros / members last — the winners
    #   changed and the result was cached as clean
    _twin_headers(tmp_path / "clean")
    clean = ug.generate_uds_source_sections(str(tmp_path / "clean"))
    target = _twin_headers(tmp_path / "flaky")
    attempts = _fail_reads(monkeypatch, target, checked=lambda n: n == 1, src_read=lambda n: False)
    flaky = ug.generate_uds_source_sections(str(tmp_path / "flaky"))
    assert attempts["checked"] == 2 and flaky["source_read_failures"]["files"] == 0
    assert flaky["macro_defs"] == clean["macro_defs"]
    assert flaky["struct_member_types"] == clean["struct_member_types"]


def test_a_file_listed_twice_is_not_counted_or_blanked_when_one_copy_was_read(tmp_path, monkeypatch):
    # review round 3 I1: overlapping roots list the same file twice; the first copy collects, the second fails
    target = _tree(tmp_path)
    attempts = _fail_reads(monkeypatch, target, checked=lambda n: n >= 2, src_read=lambda n: False)
    sec = ug.generate_uds_source_sections(f"{tmp_path},{tmp_path}{os.sep}.")     # two spellings of one root
    assert attempts["checked"] == 3, "the file must be listed twice (read OK · read fails · its retry fails)"
    rf = sec["source_read_failures"]
    assert "scan" not in rf["lost"], rf
    assert any(Path(p).name == "lost.c" and "lost_two" in t for p, t in sec["source_files"].items())


def test_reset_values_are_not_made_up_when_the_scan_missed_a_file(tmp_path, monkeypatch):
    # review round 3 W2: the reset function sits in the file the scan missed — 0x00 (static storage) would be invented
    (tmp_path / "app.c").write_bytes(_src("unsigned char u8g_X;", "unsigned char u8g_Y;",
                                          "void app_fn(void)", "{", "    u8g_Y = u8g_X;", "}").encode())
    lost = tmp_path / "lost.c"
    lost.write_bytes(_src("extern unsigned char u8g_X;", "void g_App_Init(void)", "{", "    u8g_X = 5U;", "}").encode())
    clean = ug.generate_uds_source_sections(str(tmp_path))["globals_info_map"]
    assert clean["u8g_X"]["reset"].startswith("0x05") and clean["u8g_Y"]["reset"].startswith("0x00")
    _fail_reads(monkeypatch, lost.resolve(), src_read=lambda n: False)
    gm = ug.generate_uds_source_sections(str(tmp_path))["globals_info_map"]
    from report_gen.c_reset import SKIP_SCAN_INCOMPLETE
    for name in ("u8g_X", "u8g_Y"):
        assert (gm[name]["reset"], gm[name]["reset_source"]) == ("", SKIP_SCAN_INCOMPLETE), (name, gm[name])


def test_resolve_reset_only_withholds_the_zero_fallback():
    from report_gen.c_reset import RESET_SRC_DECL, RESET_SRC_FUNC, SKIP_SCAN_INCOMPLETE, resolve_reset
    g = {"type": "U8"}
    assert resolve_reset(g, scan_incomplete=True) == ("", SKIP_SCAN_INCOMPLETE)
    assert resolve_reset(g, [("g_Init", "3U")], scan_incomplete=True)[1] == RESET_SRC_FUNC
    assert resolve_reset({"type": "U8", "init": "7U"}, scan_incomplete=True)[1] == RESET_SRC_DECL
    assert resolve_reset(g)[0].startswith("0x00")


def test_headers_the_scan_missed_are_listed_beyond_the_detail_cap():
    failed = {f"/r/app/a{i:02d}.c": "TimeoutError" for i in range(12)}
    got = ug.summarize_read_failures({}, {}, scan_missed={**failed, "/r/app/z_types.h": "TimeoutError"}, roots=["/r/app"])
    assert len(got["detail"]) == 10 and all(not d["file"].endswith(".h") for d in got["detail"])
    assert got["headers_scan_missed"] == ["r0:app/z_types.h"]


def test_a_header_the_scan_missed_is_named_in_the_generated_suts_disclosure(tmp_path, monkeypatch):
    # review round 4 W1: the header list must survive SUTS' own summary — B's `@asil D` doc lives in the header
    from generators import suts as gsuts
    monkeypatch.setattr(gsuts, "_OVERRIDE_JSON_CANDIDATES", ())
    hdr = tmp_path / "types.h"
    hdr.write_bytes(_src("/**", " * @brief does B", " * @asil D", " */", "void B(void);").encode())
    (tmp_path / "b.c").write_bytes(b'#include "types.h"\nunsigned char g_b;\nvoid B(void)\n{\n    g_b = 1U;\n}\n')
    _fail_reads(monkeypatch, hdr.resolve(), src_read=lambda n: False)        # only the main scan misses it
    q = gsuts.generate_suts(source_root=str(tmp_path), output_path=str(tmp_path / "u.xlsm"), scope="source")["quality_report"]
    rf = q["source_read_failures"]
    assert rf["headers_scan_missed"] and rf["headers_scan_missed"][0].endswith("/types.h")
    item = next(i for i in build_disclosures("suts", q) if i["key"] == "suts_source_read_failures")
    assert "types.h" in item["note"] and "다른 파일" in item["note"] and "UDS 의 Reset Value" in item["note"]
