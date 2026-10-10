"""R28 — fetch a project's registered input documents (SCM ``linked_docs``) into a local read-only copy
(`scripts/fetch_linked_docs.py`).

The registered paths are read through a resolver (the Cloudium worker for Cloudium paths, the disk otherwise) and
copied under an output folder strictly inside ``.codex_tmp`` with a manifest. The originals are never written, list
order is kept, a field is replaced all or nothing (a failed fetch keeps the previous copy — consumers read the whole
folder), and a missing path or an empty listing is an error.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import fetch_linked_docs as fld  # noqa: E402

from backend.services.file_resolver import LocalFileResolver  # noqa: E402


@pytest.fixture()
def remote(tmp_path):
    """Registered inputs on a 'remote' disk: two log folders, a release-note folder and a problem list."""
    base = tmp_path / "remote"
    for name, body in (("v1.02", "<pre>old</pre>"), ("v1.05", "<pre>new</pre>")):
        d = base / "Log" / name
        (d / "sub").mkdir(parents=True)
        (d / "report.html").write_text(body, encoding="utf-8")
        (d / "sub" / "unit.htm").write_text(body + "!", encoding="utf-8")
        (d / "notes.txt").write_text("not a report", encoding="utf-8")
    (base / "RS").mkdir()
    (base / "RS" / "sheet_v0.13.docx").write_bytes(b"docx")
    (base / "PL.xlsx").write_bytes(b"xlsx")
    docs = {"ut_log_history": [str(base / "Log" / "v1.02"), str(base / "Log" / "v1.05")],
            "release_notes": [str(base / "RS")], "problem_list": str(base / "PL.xlsx"), "syds": ""}
    return base, docs


def _fetch(tmp_path, docs, fields, resolver=None, **kw):
    allowed = tmp_path / "codex_tmp"
    out = kw.pop("out", allowed / "linked")
    local = resolver or LocalFileResolver()
    return fld.fetch(docs, fields, out, lambda path: local, allowed, **kw), out


def _tree(folder: Path) -> dict:
    return {str(p.relative_to(folder)).replace("\\", "/"): p.read_bytes() for p in sorted(folder.rglob("*"))
            if p.is_file()}


def test_registered_documents_are_copied_in_order_with_a_manifest(tmp_path, remote):
    base, docs = remote
    manifest, out = _fetch(tmp_path, docs, ["ut_log_history", "release_notes", "problem_list", "syds"], scm_id="p1")
    logs = manifest["fields"]["ut_log_history"]["entries"]
    # the registered order (oldest first) is kept in the folder names; only the reports of a log folder are copied
    assert [e["local"] for e in logs] == ["ut_log_history/01_v1.02", "ut_log_history/02_v1.05"]
    assert all(e["kind"] == "folder" and e["files"] == e["copied"] == 2 and e["pattern"] == "*.htm*" for e in logs)
    assert (out / "ut_log_history/01_v1.02/report.html").read_text(encoding="utf-8") == "<pre>old</pre>"
    assert "ut_log_history/02_v1.05/sub/unit.htm" in manifest["files"]           # '/' in keys on every platform
    assert not (out / "ut_log_history/01_v1.02/notes.txt").exists()
    assert (out / "release_notes/01_RS/sheet_v0.13.docx").read_bytes() == b"docx"
    assert manifest["fields"]["problem_list"]["entries"] == [
        {"source": str(base / "PL.xlsx"), "local": "problem_list/PL.xlsx", "kind": "file", "files": 1, "copied": 1}]
    assert manifest["fields"]["syds"]["entries"] == []           # nothing registered: nothing fetched, no error
    record = manifest["files"]["problem_list/PL.xlsx"]
    assert record["sha256"] == hashlib.sha256(b"xlsx").hexdigest() and record["bytes"] == 4
    assert json.loads((out / "manifest.json").read_text(encoding="utf-8")) == manifest
    assert manifest["errors"] == [] and manifest["scm_id"] == "p1" and manifest["dry_run"] is False
    assert manifest["format"] == 2 and "not verified" in manifest["note"]                  # N10
    assert manifest["fields"]["problem_list"]["fetched_at"]                                   # N11
    assert (out / "problem_list" / fld.MARKER).is_file()


def test_listings_are_sorted(tmp_path, remote):
    base, docs = remote

    class Reversed(LocalFileResolver):
        def list_dir(self, path, pattern="*", recursive=False, include_dirs=False):
            return list(reversed(sorted(super().list_dir(path, pattern, recursive, include_dirs))))
    manifest, _out = _fetch(tmp_path, dict(docs, ut_log_history=[str(base / "Log" / "v1.02")]), ["ut_log_history"],
                            resolver=Reversed())
    assert list(manifest["files"]) == ["ut_log_history/01_v1.02/report.html",
                                       "ut_log_history/01_v1.02/sub/unit.htm"]                 # M10


def test_a_re_run_replaces_a_field_whole_and_keeps_the_other_fields(tmp_path, remote):
    # review W1: a re-run left a deleted report on disk (read by the replay) and a second field run wiped the manifest
    base, docs = remote
    _fetch(tmp_path, docs, ["ut_log_history", "problem_list"], scm_id="p1")
    (base / "Log" / "v1.02" / "report.html").unlink()
    (base / "Log" / "v1.03").mkdir()
    (base / "Log" / "v1.03" / "report.html").write_text("<pre>mid</pre>", encoding="utf-8")
    docs = dict(docs, ut_log_history=[str(base / "Log" / d) for d in ("v1.02", "v1.03", "v1.05")])
    manifest, out = _fetch(tmp_path, docs, ["ut_log_history"], scm_id="p1")
    assert not (out / "ut_log_history/01_v1.02/report.html").exists()
    assert sorted(p.name for p in (out / "ut_log_history").iterdir()) == [fld.MARKER, "01_v1.02", "02_v1.03",
                                                                          "03_v1.05"]
    assert (out / "ut_log_history/02_v1.03/report.html").read_text(encoding="utf-8") == "<pre>mid</pre>"
    assert "problem_list/PL.xlsx" in manifest["files"] and "problem_list" in manifest["fields"]
    assert not any(k.startswith("ut_log_history/01_v1.02/report") for k in manifest["files"])
    with pytest.raises(fld.Refused, match="holds the copy of 'p1'"):
        _fetch(tmp_path, docs, ["problem_list"], scm_id="other")


def test_a_failed_fetch_keeps_the_previous_copy_and_its_record(tmp_path, remote):
    # review r2 C1: with the worker down (every listing raises) the replace used to delete the good copy; with one
    # read timing out it used to put a smaller copy in its place — silent to a consumer reading the folder
    _base, docs = remote
    first, out = _fetch(tmp_path, docs, ["ut_log_history", "problem_list"], scm_id="p1")
    before = _tree(out / "ut_log_history")

    class Down(LocalFileResolver):
        def is_dir(self, path):
            raise PermissionError("Cloudium worker not running")

    class OneSlow(LocalFileResolver):
        def read_bytes(self, path):
            if path.endswith("unit.htm"):
                raise TimeoutError("worker slow")
            return super().read_bytes(path)
    for resolver in (Down(), OneSlow()):
        manifest, _ = _fetch(tmp_path, docs, ["ut_log_history"], resolver=resolver, scm_id="p1")
        assert _tree(out / "ut_log_history") == before
        kept = {k: v for k, v in manifest["files"].items() if k.startswith("ut_log_history/")}
        assert kept == {k: v for k, v in first["files"].items() if k.startswith("ut_log_history/")}
        record = manifest["fields"]["ut_log_history"]
        assert record["last_failed_attempt"]["errors"] >= 1 and record["entries"] == first["fields"]["ut_log_history"]["entries"]
        assert not (out / ".ut_log_history.partial").exists()
    assert "problem_list/PL.xlsx" in manifest["files"]


def test_a_replace_that_cannot_rename_keeps_the_previous_copy(tmp_path, remote, monkeypatch):
    # review r2 W1(c): a file held open used to leave a half-deleted folder; a rename fails without removing anything
    _base, docs = remote
    _first, out = _fetch(tmp_path, docs, ["problem_list"], scm_id="p1")
    real_replace = fld.os.replace

    def refuse(src, dst):
        if Path(src).name == "problem_list":
            raise PermissionError("[WinError 5] held open")
        return real_replace(src, dst)
    monkeypatch.setattr(fld.os, "replace", refuse)
    manifest, _ = _fetch(tmp_path, docs, ["problem_list"], scm_id="p1")
    assert (out / "problem_list" / "PL.xlsx").read_bytes() == b"xlsx"
    assert manifest["errors"][0]["error"].startswith("replace_failed: PermissionError")
    assert not (out / ".problem_list.partial").exists()


def test_a_folder_the_tool_made_is_known_even_without_its_record(tmp_path, remote):
    # review r2 W1(d): a run stopped after moving a field in but before its manifest — the next run must not refuse it
    _base, docs = remote
    _first, out = _fetch(tmp_path, docs, ["problem_list"], scm_id="p1")
    (out / "manifest.json").unlink()
    manifest, _ = _fetch(tmp_path, docs, ["problem_list"], scm_id="p1")
    assert manifest["errors"] == [] and (out / "problem_list" / "PL.xlsx").exists()


def test_a_folder_this_tool_did_not_make_is_not_replaced(tmp_path, remote):
    _base, docs = remote
    foreign = tmp_path / "codex_tmp" / "linked" / "problem_list"
    foreign.mkdir(parents=True)
    (foreign / "mine.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(fld.Refused, match="not a folder this tool made"):
        _fetch(tmp_path, docs, ["problem_list"])
    assert (foreign / "mine.txt").read_text(encoding="utf-8") == "keep"


def test_a_stale_stage_is_cleared_by_a_run_and_left_by_a_dry_run(tmp_path, remote):
    _base, docs = remote
    stage = tmp_path / "codex_tmp" / "linked" / ".problem_list.partial"
    stage.mkdir(parents=True)
    (stage / "stale.bin").write_bytes(b"old")
    _fetch(tmp_path, docs, ["problem_list"], dry_run=True)
    assert (stage / "stale.bin").exists()                                          # N4: a dry run removes nothing
    _manifest, out = _fetch(tmp_path, docs, ["problem_list"])
    assert not (out / "problem_list" / "stale.bin").exists()                       # N3


def test_missing_empty_and_unreadable_are_errors(tmp_path, remote):
    base, docs = remote
    (base / "Log" / "zips").mkdir()
    (base / "Log" / "zips" / "old.zip").write_bytes(b"z")
    docs = dict(docs, ut_log_history=[str(base / "Log" / "gone"), str(base / "Log" / "zips"), str(base / "Log" / "v1.05")])

    class Flaky(LocalFileResolver):
        def is_dir(self, path):
            if path.endswith("RS"):
                raise PermissionError("drive not ready")
            return super().is_dir(path)

        def read_bytes(self, path):
            if path.endswith("PL.xlsx"):
                raise ValueError("Incorrect padding")                             # N9: binascii.Error
            return super().read_bytes(path)
    manifest, out = _fetch(tmp_path, docs, ["ut_log_history", "release_notes", "problem_list"], resolver=Flaky())
    attempt = manifest["fields"]["ut_log_history"]["last_failed_attempt"]
    logs = attempt["entries"]
    assert len(logs) == 3 and logs[0] == {"source": str(base / "Log" / "gone"), "local": "ut_log_history/01_gone",
                                          "kind": "missing"}
    assert logs[1]["kind"] == "folder" and logs[1]["files"] == 0 and logs[2]["copied"] == 2   # M11: nothing leaks
    assert [(e["field"], e["error"].split(":")[0]) for e in manifest["errors"]] == [
        ("ut_log_history", "missing"), ("ut_log_history", "empty_listing"),       # review W2
        ("release_notes", "PermissionError"), ("problem_list", "ValueError")]     # M3/M9
    assert manifest["fields"]["release_notes"]["last_failed_attempt"]["entries"][0]["kind"] == "unreadable"
    assert not (out / "ut_log_history").exists() and not (out / "problem_list").exists()   # all or nothing


def test_a_listed_file_outside_the_folder_is_never_written(tmp_path, remote):
    base, docs = remote

    class Wandering(LocalFileResolver):
        def list_dir(self, path, pattern="*", recursive=False, include_dirs=False):
            return [str(Path(path) / "report.html"), str(Path(path).parent / "v1.05" / "report.html")]
    manifest, out = _fetch(tmp_path, dict(docs, ut_log_history=[str(base / "Log" / "v1.02")]), ["ut_log_history"],
                           resolver=Wandering())
    entry = manifest["fields"]["ut_log_history"]["last_failed_attempt"]["entries"][0]
    assert entry["kind"] == "unreadable" and "traversal" in manifest["errors"][0]["error"]   # M2: refused unread
    assert not (out / "ut_log_history").exists()


def test_the_copy_stays_inside_the_scratch_root_and_apart_from_the_inputs(tmp_path, remote):
    base, docs = remote
    allowed = tmp_path / "codex_tmp"
    with pytest.raises(fld.Refused, match="not inside"):
        _fetch(tmp_path, docs, ["problem_list"], out=tmp_path / "elsewhere")
    with pytest.raises(fld.Refused, match="not inside"):
        _fetch(tmp_path, docs, ["problem_list"], out=allowed)                       # the root itself (review I9)
    for out in (base / "RS" / "copy", base / "RS"):                               # inside an input, or the input (M1)
        with pytest.raises(fld.Refused, match="overlap"):
            fld.fetch(docs, ["release_notes"], out, lambda p: LocalFileResolver(), base)
    # review W3: an input inside the output folder would be written over
    inner = allowed / "linked" / "syrs"
    inner.mkdir(parents=True)
    (inner / "x.docx").write_bytes(b"orig")
    with pytest.raises(fld.Refused, match="overlap"):
        _fetch(tmp_path, dict(docs, syrs=str(inner)), ["syrs"])
    assert (inner / "x.docx").read_bytes() == b"orig" and not (inner / "syrs").exists()


def test_another_run_holding_the_lock_is_a_refusal(tmp_path, remote):
    # review r2 W2: the manifest is read inside the lock; a second run waits briefly, then refuses (not a traceback)
    from filelock import FileLock
    _base, docs = remote
    out = tmp_path / "codex_tmp" / "linked"
    out.mkdir(parents=True)
    with FileLock(str(out.resolve()) + ".lock"):
        with pytest.raises(fld.Refused, match="another fetch holds"):
            _fetch(tmp_path, docs, ["problem_list"])


def test_a_dry_run_lists_and_reads_and_writes_nothing(tmp_path, remote):
    _base, docs = remote

    class NoRead(LocalFileResolver):
        def read_bytes(self, path):
            raise AssertionError("a dry run reads no file")
    manifest, out = _fetch(tmp_path, docs, ["ut_log_history"], resolver=NoRead(), dry_run=True)
    assert manifest["dry_run"] is True and len(manifest["files"]) == 4
    assert all(set(v) == {"source"} for v in manifest["files"].values())
    assert not out.exists()


@pytest.mark.parametrize("text, name", [
    (r"U:\proj\Log\v1.02", "v1.02"), ("U:/proj/Log/v1.02/", "v1.02"), ("U:/", "root"), ("..", "root"),
    ("D:/x/a:b", "a_b"), ("D:/x/CON", "_CON"), ("D:/x/nul.txt", "_nul.txt"), ("D:/x/name. ", "name"),
])
def test_a_registered_path_becomes_a_safe_folder_name(text, name):
    assert fld._safe_name(text) == name                                            # M6/M7 (review I2)


def test_cloudium_paths_go_through_the_worker_allowed_only_the_registered_paths(monkeypatch):
    from backend.services.file_resolver import CloudiumFileResolver
    monkeypatch.delenv("DEVOPS_CLOUDIUM_DRIVES", raising=False)
    resolver_for = fld.default_resolver_for(["U:/proj/10.UT/Log/v1.02", "u:/proj/a,b", "D:/local/PL.xlsx"])
    cloud = resolver_for("U:/proj/10.UT/Log/v1.02/r.html")
    assert isinstance(cloud, CloudiumFileResolver)
    assert cloud.allowed_prefixes == ["U:/proj/10.UT/Log/v1.02", "u:/proj/a,b"]   # a comma does not split (I9), M5
    assert resolver_for("u:/proj/a,b/x") is cloud
    assert isinstance(resolver_for("D:/local/PL.xlsx"), LocalFileResolver)
    assert isinstance(fld.default_resolver_for(["D:/x"])("D:/x"), LocalFileResolver)   # no worker needed at all
    monkeypatch.setenv("DEVOPS_CLOUDIUM_DRIVES", "U,V")                                # the repo's one judgement (I3)
    assert isinstance(fld.default_resolver_for(["V:/p"])("V:/p"), CloudiumFileResolver)


def _registry(tmp_path, docs):
    path = tmp_path / "scm_registry.json"
    path.write_text(json.dumps({"registries": [{"id": "p1", "name": "P1", "linked_docs": docs}]}), encoding="utf-8")
    return path


def test_the_command_reads_the_registry_without_writing_it(tmp_path, monkeypatch, remote, capsys):
    base, docs = remote
    path = _registry(tmp_path, docs)
    before = path.read_bytes()
    monkeypatch.setattr("backend.services.scm_registry.REGISTRY_PATH", path)
    monkeypatch.setattr(fld, "REPO", tmp_path)
    assert fld.main(["--scm-id", "nope"]) == 2
    assert fld.main(["--scm-id", "p1", "--fields", "no_such_field"]) == 2
    assert fld.main(["--scm-id", "p1", "--fields", "problem_list,ut_log_history,syds"]) == 0
    out = tmp_path / ".codex_tmp" / "linked_docs" / "p1"
    assert (out / "problem_list" / "PL.xlsx").read_bytes() == b"xlsx"
    text = capsys.readouterr().out
    assert "5 files" in text and "syds: (not registered)" in text
    assert fld.main(["--scm-id", "p1", "--fields", "problem_list", "--dry-run"]) == 0
    assert "— bytes" in capsys.readouterr().out                                     # review W4: not "0 bytes"
    (base / "PL.xlsx").unlink()
    assert fld.main(["--scm-id", "p1", "--fields", "problem_list"]) == 1            # M4: an error is exit 1
    captured = capsys.readouterr()
    assert "ERROR problem_list" in captured.err and "NOT REPLACED" in captured.out
    assert (out / "problem_list" / "PL.xlsx").read_bytes() == b"xlsx"             # the previous copy is kept
    # N7/N8: another field's run is clean — its exit is 0 and problem_list's recorded error stays in the manifest
    assert fld.main(["--scm-id", "p1", "--fields", "ut_log_history"]) == 0
    recorded = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["errors"]
    assert [e["field"] for e in recorded] == ["problem_list"]
    assert fld.main(["--scm-id", "p1", "--fields", "problem_list", "--out", str(tmp_path / "x")]) == 2   # refusal
    assert path.read_bytes() == before                                              # review I8: never rewritten
    path.write_text("{broken", encoding="utf-8")
    assert fld.main(["--scm-id", "p1"]) == 2                                        # review r2 I2: a refusal
    assert path.read_text(encoding="utf-8") == "{broken"                           # not replaced by an empty store


def test_the_summary_survives_a_cp949_pipe(tmp_path, monkeypatch, remote):
    # review r2 W3: "—" on a cp949 stdout used to raise UnicodeEncodeError at the end of a dry run
    _base, docs = remote
    monkeypatch.setattr("backend.services.scm_registry.REGISTRY_PATH", _registry(tmp_path, docs))
    monkeypatch.setattr(fld, "REPO", tmp_path)
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="cp949"))
    assert fld.main(["--scm-id", "p1", "--fields", "problem_list", "--dry-run"]) == 0
    sys.stdout.flush()
    assert b"bytes" in raw.getvalue()


def test_a_run_that_stops_midway_has_recorded_the_fields_it_committed(tmp_path, remote):
    # review r3 R4': the manifest is written after each committed field — a stop in the second field keeps the
    # record of the first one's new files
    base, docs = remote
    _fetch(tmp_path, docs, ["problem_list", "release_notes"], scm_id="p1")
    (base / "PL.xlsx").write_bytes(b"xlsx-v2")

    class StopsInRS(LocalFileResolver):
        def is_dir(self, path):
            if path.endswith("RS"):
                raise KeyboardInterrupt
            return super().is_dir(path)
    with pytest.raises(KeyboardInterrupt):
        _fetch(tmp_path, docs, ["problem_list", "release_notes"], resolver=StopsInRS(), scm_id="p1")
    out = tmp_path / "codex_tmp" / "linked"
    recorded = json.loads((out / "manifest.json").read_text(encoding="utf-8"))["files"]["problem_list/PL.xlsx"]
    assert recorded["sha256"] == hashlib.sha256(b"xlsx-v2").hexdigest()
    assert (out / "problem_list" / "PL.xlsx").read_bytes() == b"xlsx-v2"
    assert (out / "release_notes" / "01_RS" / "sheet_v0.13.docx").exists()       # untouched by the stopped field


def test_the_rename_swap_recovers_and_cleans_up(tmp_path, remote, monkeypatch):
    _base, docs = remote
    _first, out = _fetch(tmp_path, docs, ["problem_list"], scm_id="p1")
    old = out / ".problem_list.old"
    # R2: a leftover .old from an earlier run does not block every later replace
    old.mkdir()
    (old / "x").write_bytes(b"left")
    manifest, _ = _fetch(tmp_path, docs, ["problem_list"], scm_id="p1")
    assert manifest["errors"] == [] and not old.exists()                            # R3: cleaned after the swap
    # R1: the stage rename fails after the previous copy moved aside — the previous copy is put back
    real_replace = fld.os.replace

    def refuse_stage(src, dst):
        if Path(src).name == ".problem_list.partial":
            raise PermissionError("[WinError 5] denied")
        return real_replace(src, dst)
    monkeypatch.setattr(fld.os, "replace", refuse_stage)
    manifest, _ = _fetch(tmp_path, docs, ["problem_list"], scm_id="p1")
    assert (out / "problem_list" / "PL.xlsx").read_bytes() == b"xlsx" and not old.exists()
    assert manifest["fields"]["problem_list"]["last_failed_attempt"]["errors"] == 1     # r3 P1: counted
    monkeypatch.setattr(fld.os, "replace", real_replace)
    # r3 P2: stopped between the renames (the field folder only as .old) — the next run brings it back first
    real_replace(out / "problem_list", old)
    manifest, _ = _fetch(tmp_path, docs, ["problem_list"], scm_id="p1")
    assert (out / "problem_list" / "PL.xlsx").exists() and not old.exists() and manifest["errors"] == []


@pytest.mark.parametrize("content", ["{broken", "[1, 2]"])
def test_an_unreadable_manifest_is_a_refusal(tmp_path, remote, content):
    # review r3 R5/R6: never read as "no record" — that would let a run replace folders it cannot vouch for
    _base, docs = remote
    out = tmp_path / "codex_tmp" / "linked"
    out.mkdir(parents=True)
    (out / "manifest.json").write_text(content, encoding="utf-8")
    with pytest.raises(fld.Refused, match="manifest"):
        _fetch(tmp_path, docs, ["problem_list"])
