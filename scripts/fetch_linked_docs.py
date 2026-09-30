"""Fetch a project's registered input documents (SCM registry ``linked_docs``) into a local, read-only copy (R28).

R25 registered the materials the defect-discrimination rounds use — versioned unit-test logs (``ut_log_history``),
release records (``release_notes``), the problem list, system design/requirements, fault-injection specs — as input
documents of each SCM entry, so the next project brings them along. The measurement scripts read local folders
(`scripts/history_replay.py` takes ``--old-log``/``--new-log``), and the originals usually sit on the Cloudium drive
(U:), which only the worker process may read. This script closes the gap: it reads the entry's registered paths —
through the Cloudium worker for Cloudium paths (`docgen_output.is_cloudium_path`, which also takes UNC paths and
``DEVOPS_CLOUDIUM_DRIVES``; the worker is allowed exactly those paths), directly otherwise — and copies every file under
``--out`` (strictly inside ``.codex_tmp``), with ``manifest.json`` holding each file's source path, size and sha256.

* The originals are only read (``list_dir``/``read_bytes``); the registry file is read under its lock, never rewritten.
  ``--out`` may not lie inside a registered local input, nor contain one. Every destination is sealed under ``--out``
  (`paths.safe_resolve_under`: no ``..`` part, no junction out).
* **All or nothing per field.** A field is fetched into ``.<field>.partial``; only a field with no error replaces the
  previous copy, by rename (``<field>`` → ``.<field>.old``, stage → ``<field>``, then the old one is removed) — a
  failed rename (a file held open) removes nothing. A field with an error keeps its previous copy and its previous
  manifest record; the attempt's errors are reported. A re-run leaves no stale file (a consumer reads the whole folder).
  The registry is the source: a field registered empty is fetched as empty (its previous copy is replaced by none).
* Each committed field folder carries ``.fetch_linked_docs`` (so a folder the tool made is known even if a run stopped
  before its manifest was written); a field folder without it and without a manifest record is never replaced.
  ``manifest.json`` (``format`` 2) keeps the other fields' records and is rewritten atomically after each committed
  field; one run at a time holds ``<out>.lock``, and the manifest is read inside it.
* A list field keeps its registered order (``ut_log_history`` is oldest first): ``<field>/01_<name>``, ``02_…``.
* Errors (exit 1): a registered path that is neither a file nor a folder (``missing`` — the worker lists a missing
  folder as empty and folds some network errors into "no such path"), a folder that lists no file (``empty_listing``),
  an unreadable listing or file, a failed replace. A listing's completeness (sub-folders the listing API cannot open
  are skipped silently) is not verifiable: disclosed in the manifest. Refusals exit 2 (bad ``--out``, a folder that is
  not the tool's, another project's copy, another run holding the lock, an unreadable registry or manifest).
* ``--dry-run`` lists without reading, writing or locking (sizes shown as ``—``).

Usage:
    .venv/Scripts/python.exe scripts/fetch_linked_docs.py --scm-id hdpdm01 [--fields ut_log_history,release_notes]
        [--out .codex_tmp/linked_docs/hdpdm01] [--dry-run]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# the fields R24–R27 read; any other ``ScmLinkedDocs`` field can be named with --fields
DEFAULT_FIELDS = ("ut_log_history", "release_notes", "problem_list", "syrs", "syds", "fault_injection",
                  "hwrs")   # (R49) HW 요구사항서 — STS 경계 TC 의 HW 측정 허용오차
# a unit-test log folder holds more than the aggregate coverage reports the replay reads
FIELD_PATTERNS = {"ut_log_history": "*.htm*"}
MARKER = ".fetch_linked_docs"
MANIFEST_FORMAT = 2
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
COMPLETENESS_NOTE = ("folder listings come from the worker (or the disk) recursively; sub-folders that cannot be opened "
                     "are skipped silently by the listing API, so a listing's completeness is not verified")


class Refused(Exception):
    """A guard refused the run (exit 2): nothing was read or written."""


def _paths(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    return [str(v).strip() for v in (value or []) if str(v).strip()]


def _safe_name(text: str) -> str:
    """A folder/file name for a registered path: its last part, without characters Windows refuses, never ``.``/``..``
    or a reserved device name."""
    name = os.path.basename(os.path.normpath(text.strip()).rstrip("\\/"))
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).rstrip(" .")
    if name in ("", ".", ".."):
        name = "root"
    if name.split(".")[0].upper() in _RESERVED:
        name = "_" + name
    return name


def _is_cloudium(path: str) -> bool:
    from backend.services.docgen_output import is_cloudium_path
    return is_cloudium_path(path)


def default_resolver_for(paths: list[str]) -> Callable[[str], Any]:
    """Cloudium paths through the worker, allowed exactly the registered paths; any other through the local disk."""
    from backend.services.file_resolver import CloudiumFileResolver, LocalFileResolver
    cloud = [p for p in paths if _is_cloudium(p)]
    cloudium = None
    if cloud:
        cloudium = CloudiumFileResolver(allowed_prefixes=cloud[0])
        cloudium.allowed_prefixes = list(cloud)   # set as a list: a comma inside a path must not split it
    local = LocalFileResolver()
    return lambda path: cloudium if _is_cloudium(path) else local


def read_linked_docs(scm_id: str, registry_path: Path | None = None) -> dict | None:
    """The entry's ``linked_docs`` read from the registry file under its lock, without the service loader (which
    replaces a missing or invalid registry with an empty store) — a fetch never writes the registry."""
    from backend.schemas import ScmLinkedDocs
    from backend.services import scm_registry
    path = Path(registry_path or scm_registry.REGISTRY_PATH)
    with scm_registry._REGISTRY_LOCK:
        text = path.read_text(encoding="utf-8")
    raw = json.loads(text)
    for entry in (raw.get("registries") or []) if isinstance(raw, dict) else []:
        if isinstance(entry, dict) and entry.get("id") == scm_id:
            return ScmLinkedDocs(**(entry.get("linked_docs") or {})).model_dump()
    return None


def _check_out(out: Path, allowed_root: Path, registered: list[str]) -> Path:
    out_r, root_r = out.resolve(), allowed_root.resolve()
    if out_r == root_r or not out_r.is_relative_to(root_r):
        raise Refused(f"refusing to write {out}: not inside {allowed_root}")
    for src in registered:
        if _is_cloudium(src):
            continue
        src_r = Path(src).resolve()
        if out_r.is_relative_to(src_r) or src_r.is_relative_to(out_r):
            raise Refused(f"refusing to write {out}: it and the registered input {src} overlap")
    return out_r


def _list(resolver, src: str, field: str) -> tuple[str, list[str]]:
    if resolver.is_dir(src):
        return "folder", sorted(resolver.list_dir(src, pattern=FIELD_PATTERNS.get(field, "*"), recursive=True,
                                                  include_dirs=False))
    if resolver.is_file(src):
        return "file", [src]
    return "missing", []


def _fetch_field(field: str, value: Any, stage: Path, resolver_for, dry_run: bool) -> tuple[list, dict, list]:
    from backend.services.paths import safe_resolve_under
    entries, files, errors = [], {}, []
    multiple = isinstance(value, list)
    for i, src in enumerate(_paths(value), start=1):
        resolver = resolver_for(src)
        name = f"{i:02d}_{_safe_name(src)}" if multiple else _safe_name(src)
        entry: dict[str, Any] = {"source": src, "local": f"{field}/{name}"}
        entries.append(entry)
        try:
            kind, found = _list(resolver, src, field)
            entry["kind"] = kind
            if kind == "missing":
                errors.append({"field": field, "source": src, "error": "missing"})
                continue
            if kind == "folder":
                entry["pattern"] = FIELD_PATTERNS.get(field, "*")
                if not found:
                    errors.append({"field": field, "source": src, "error": "empty_listing"})
                base = os.path.normpath(src)
                pairs = [(f, f"{name}/{os.path.relpath(os.path.normpath(f), base)}") for f in found]
            else:
                pairs = [(src, name)]
            # every destination sealed under the stage before anything is read (a listed ``..`` part refuses all)
            targets = [(f, rel, safe_resolve_under(stage, rel)) for f, rel in pairs]
        except (OSError, ValueError, TimeoutError) as exc:   # the worker raises PermissionError/TimeoutError
            entry["kind"] = "unreadable"
            errors.append({"field": field, "source": src, "error": f"{type(exc).__name__}: {exc}"})
            continue
        entry["files"] = len(targets)
        copied = 0
        for f, rel, dst in targets:
            key = f"{field}/{rel.replace(os.sep, '/')}"
            if dry_run:
                files[key] = {"source": f}   # listed, not read
                continue
            try:
                data = resolver.read_bytes(f)
            except (OSError, ValueError, TimeoutError) as exc:   # ValueError: a chunk the worker sent undecodable
                errors.append({"field": field, "source": f, "error": f"{type(exc).__name__}: {exc}"})
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            files[key] = {"source": f, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            copied += 1
        if not dry_run:
            entry["copied"] = copied
    return entries, files, errors


def _replace(stage: Path, final: Path) -> None:
    """``final`` becomes ``stage`` by rename; a rename that fails (a file held open) leaves ``final`` untouched."""
    old = final.with_name(f".{final.name}.old")
    if old.exists():
        shutil.rmtree(old)
    if final.exists():
        os.replace(final, old)
    try:
        os.replace(stage, final)
    except OSError:
        if old.exists() and not final.exists():
            os.replace(old, final)   # put the previous copy back
        raise
    if old.exists():
        shutil.rmtree(old, ignore_errors=True)   # the previous copy — its own leftovers only; retried next run


def _write_manifest(path: Path, manifest: dict) -> None:
    tmp = path.with_name(f"manifest.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _read_manifest(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refused(f"refusing to write next to an unreadable manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise Refused(f"refusing to write next to a manifest that is not an object: {path}")
    return manifest


def fetch(linked_docs: dict, fields: list[str], out: Path, resolver_for: Callable[[str], Any], allowed_root: Path,
          dry_run: bool = False, scm_id: str = "") -> dict[str, Any]:
    """Copy each registered path of ``fields`` under ``out``; returns the manifest (written unless ``dry_run``)."""
    from filelock import FileLock, Timeout
    registered = [p for f in fields for p in _paths(linked_docs.get(f))]
    out_r = _check_out(out, allowed_root, registered)
    lock = None
    if not dry_run:
        out_r.mkdir(parents=True, exist_ok=True)
        lock = FileLock(str(out_r) + ".lock")
        try:
            lock.acquire(timeout=5)
        except Timeout as exc:
            raise Refused(f"refusing to write {out}: another fetch holds {out_r}.lock") from exc
    try:
        manifest_path = out_r / "manifest.json"
        previous = _read_manifest(manifest_path)   # inside the lock: no other run can rewrite it now (review r2 W2)
        if previous.get("scm_id") and scm_id and previous["scm_id"] != scm_id:
            raise Refused(f"refusing to write {out}: it holds the copy of {previous['scm_id']!r}")
        recorded = set(previous.get("fields") or {})   # any format: a field name the tool recorded
        for field in fields:
            final = out_r / field
            old = out_r / f".{field}.old"
            if not dry_run and not final.exists() and old.is_dir():
                os.replace(old, final)   # a run stopped between the two renames: its previous copy comes back (r3 P2)
            if final.exists() and field not in recorded and not (final / MARKER).is_file():
                raise Refused(f"refusing to replace {final}: not a folder this tool made")
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        manifest = {"format": MANIFEST_FORMAT, "scm_id": scm_id or previous.get("scm_id", ""), "dry_run": dry_run,
                    "note": COMPLETENESS_NOTE, "fields": dict(previous.get("fields") or {}),
                    "files": dict(previous.get("files") or {}),
                    "errors": [e for e in (previous.get("errors") or []) if e.get("field") not in fields]}
        for field in fields:
            stage = out_r / f".{field}.partial"
            if stage.exists() and not dry_run:
                shutil.rmtree(stage)   # a previous run's unfinished stage — this tool's own, by name
            entries, files, errors = _fetch_field(field, linked_docs.get(field), stage, resolver_for, dry_run)
            attempt = {"at": now, "entries": entries, "errors": len(errors)}
            if not dry_run and not errors:
                stage.mkdir(parents=True, exist_ok=True)
                (stage / MARKER).write_text(json.dumps({"scm_id": scm_id, "field": field, "fetched_at": now}),
                                            encoding="utf-8")
                try:
                    _replace(stage, out_r / field)
                except OSError as exc:
                    errors.append({"field": field, "source": str(out_r / field),
                                   "error": f"replace_failed: {type(exc).__name__}: {exc}"})
            if dry_run or not errors:
                manifest["fields"][field] = {"fetched_at": None if dry_run else now, "entries": entries}
                manifest["files"] = {**{k: v for k, v in manifest["files"].items() if k.split("/", 1)[0] != field},
                                     **files}
            else:
                # all or nothing: the previous copy and its record stay; this attempt is reported (review r2 C1)
                attempt["errors"] = len(errors)   # with a failed replace counted (review r3 P1)
                if stage.exists():
                    shutil.rmtree(stage, ignore_errors=True)
                kept = manifest["fields"].get(field)
                manifest["fields"][field] = {**(kept if isinstance(kept, dict) else {"entries": kept or []}),
                                             "last_failed_attempt": attempt}
            manifest["errors"].extend(errors)
            if not dry_run:
                _write_manifest(manifest_path, manifest)   # after each field: the record follows the folder
        return manifest
    finally:
        if lock is not None:
            lock.release()


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")   # "—" on a cp949 pipe must not end the run (review r2 W3)
        except (AttributeError, ValueError):
            pass   # not a text stream that can be reconfigured (a test's capture) — silent-ok
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--scm-id", required=True)
    ap.add_argument("--fields", default=",".join(DEFAULT_FIELDS))
    ap.add_argument("--out", default="")
    ap.add_argument("--dry-run", action="store_true", help="list what would be copied, read and write nothing")
    args = ap.parse_args(argv)
    try:
        docs = read_linked_docs(args.scm_id)
    except (OSError, ValueError) as exc:   # a missing or broken registry: never "repaired" here
        print(f"cannot read the SCM registry: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if docs is None:
        print(f"no SCM entry {args.scm_id!r}", file=sys.stderr)
        return 2
    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    unknown = [f for f in fields if f not in docs]
    if unknown:
        print(f"unknown linked_docs fields: {unknown}", file=sys.stderr)
        return 2
    allowed_root = REPO / ".codex_tmp"
    out = Path(args.out) if args.out else allowed_root / "linked_docs" / args.scm_id
    paths = [p for f in fields for p in _paths(docs.get(f))]
    try:
        manifest = fetch(docs, fields, out, default_resolver_for(paths), allowed_root, dry_run=args.dry_run,
                         scm_id=args.scm_id)
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for field in fields:
        record = manifest["fields"].get(field) or {}
        failed = record.get("last_failed_attempt")
        entries = (failed or record).get("entries") or []
        if not entries:
            print(f"{field}: (not registered)")
        for e in entries:
            done = "" if args.dry_run else f", {e.get('copied', 0)} copied"
            print(f"{field}: {e['local']}  ({e.get('kind')}, {e.get('files', 0)} listed{done})  <- {e['source']}")
        if failed:
            print(f"{field}: NOT REPLACED — {failed['errors']} error(s); the previous copy is kept")
    errors = [e for e in manifest["errors"] if e["field"] in fields]
    for err in errors:
        print(f"ERROR {err['field']}: {err['source']}: {err['error']}", file=sys.stderr)
    fetched = [v for k, v in manifest["files"].items() if k.split("/", 1)[0] in fields]
    size = "—" if args.dry_run else str(sum(v.get("bytes", 0) for v in fetched))
    print(f"{len(fetched)} files · {size} bytes · errors {len(errors)}" + ("" if args.dry_run else f" -> {out}"))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
