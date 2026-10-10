"""R25 — defect-discrimination evidence as input documents (SCM registry ``linked_docs``).

The materials R24 found on Cloudium (system design spec, problem list, FW release records, versioned unit-test logs,
fault-injection spec / FMEA) come with every project, so they are registered input documents rather than paths handed
to scripts by hand. The fields must survive the registry round trip (an unknown field is dropped silently by pydantic's
default ``extra='ignore'`` — the saved form loses it and the user believes it was saved), an older registry file without
them must still load, and the existence check must count the list fields like ``vectorcast``.
"""
from __future__ import annotations

import json

NEW_STR = ("syds", "problem_list")
NEW_LIST = ("release_notes", "ut_log_history", "fault_injection")


def test_the_evidence_fields_exist_with_empty_defaults():
    from backend.schemas import ScmLinkedDocs
    docs = ScmLinkedDocs()
    for key in NEW_STR:
        assert getattr(docs, key) == ""
    for key in NEW_LIST:
        assert getattr(docs, key) == []


def _registry(tmp_path, monkeypatch):
    from backend.schemas import ScmRegisterRequest
    from backend.services import scm_registry
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", tmp_path / "config" / "scm_registry.json")
    scm_registry.register_entry(ScmRegisterRequest(id="p1", name="P1", source_root=str(tmp_path / "src")))
    return scm_registry


def test_the_evidence_fields_survive_the_registry_round_trip(tmp_path, monkeypatch):
    from backend.schemas import ScmLinkedDocs
    reg = _registry(tmp_path, monkeypatch)
    docs = ScmLinkedDocs(srs="U:/p/SRS.docx", syds="U:/p/SyDS.docx", problem_list="U:/p/PL.xlsx",
                         release_notes=["U:/p/06.FW 배포"], ut_log_history=["U:/p/Log/v1.02", "U:/p/Log/v1.05"],
                         fault_injection=["U:/p/FIT.xlsm", "U:/p/FMEA.xlsx"])
    reg.replace_linked_docs("p1", docs)
    stored = json.loads(reg.REGISTRY_PATH.read_text(encoding="utf-8"))["registries"][0]["linked_docs"]
    assert stored["syds"] == "U:/p/SyDS.docx" and stored["problem_list"] == "U:/p/PL.xlsx"
    assert stored["ut_log_history"] == ["U:/p/Log/v1.02", "U:/p/Log/v1.05"]          # order kept: oldest first
    assert stored["release_notes"] == ["U:/p/06.FW 배포"] and len(stored["fault_injection"]) == 2
    again = reg.get_registry_entry("p1").linked_docs
    assert again.ut_log_history == docs.ut_log_history and again.srs == "U:/p/SRS.docx"


def test_a_registry_written_before_the_fields_existed_still_loads(tmp_path, monkeypatch):
    from backend.services import scm_registry
    path = tmp_path / "config" / "scm_registry.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"registries": [{"id": "old", "name": "Old",
                                                "linked_docs": {"srs": "U:/o/SRS.docx", "vectorcast": ["U:/o/vc"]}}]}),
                    encoding="utf-8")
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", path)
    entry = scm_registry.get_registry_entry("old")
    assert entry is not None and entry.linked_docs.srs == "U:/o/SRS.docx"
    assert entry.linked_docs.ut_log_history == [] and entry.linked_docs.syds == ""
    assert not path.with_suffix(".invalid.json").exists()        # not treated as a broken registry


class _Resolver:
    def __init__(self, missing=()):
        self.missing = set(missing)

    def exists(self, path):
        return path not in self.missing


def test_the_existence_check_counts_the_evidence_lists(monkeypatch):
    from backend.routers import scm as S
    from backend.schemas import ScmLinkedDocs, ScmRegistryEntry
    entry = ScmRegistryEntry(id="e1", name="E1", linked_docs=ScmLinkedDocs(
        syds="U:/e/SyDS.docx", ut_log_history=["U:/e/Log/v1", "U:/e/Log/v2"], fault_injection=[]))
    monkeypatch.setattr(S, "get_registry_entry", lambda eid: entry)
    monkeypatch.setattr("backend.services.file_resolver.get_resolver", lambda: _Resolver(missing={"U:/e/Log/v2"}))
    items = S.scm_linked_docs_status("e1")["items"]
    assert items["syds"]["exists"] is True
    assert items["ut_log_history"]["total"] == 2 and items["ut_log_history"]["missing"] == 1
    assert items["fault_injection"]["total"] == 0                # an empty list reads as "none registered", like vectorcast


def test_a_hand_written_string_or_null_in_a_list_field_does_not_wipe_the_registry(tmp_path, monkeypatch):
    # review I2: the label says "file or folder" — ``"release_notes": "U:/…"`` or ``null`` written by hand used to fail
    # validation, and `load_registry_store` then replaced the WHOLE registry with an empty store
    from backend.services import scm_registry
    path = tmp_path / "config" / "scm_registry.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"registries": [
        {"id": "a", "name": "A", "linked_docs": {"release_notes": "U:/a/06.FW 배포", "vectorcast": None,
                                                 "ut_log_history": ""}},
        {"id": "b", "name": "B"}]}), encoding="utf-8")
    monkeypatch.setattr(scm_registry, "REGISTRY_PATH", path)
    entries = scm_registry.list_registry_entries()
    assert [e.id for e in entries] == ["a", "b"]
    docs = entries[0].linked_docs
    assert docs.release_notes == ["U:/a/06.FW 배포"] and docs.vectorcast == [] and docs.ut_log_history == []
    assert not path.with_suffix(".invalid.json").exists()


def test_the_prefix_merge_walks_every_schema_field_for_a_dict_entry(monkeypatch):
    # review I1: the dict fallback used a hand-written key tuple that had gone stale (no codesonar, no R25 fields)
    import types

    from backend.routers import scm as S
    from backend.services import file_resolver as fr
    added = {}

    class _Cloudium(fr.CloudiumFileResolver):
        def __init__(self):
            self.allowed_prefixes = []
            self.gate_process = "gate.exe"
    resolver = _Cloudium()
    monkeypatch.setattr(fr, "get_resolver", lambda: resolver)
    monkeypatch.setattr(fr, "switch_mode", lambda mode, **k: added.update(k))
    entry = types.SimpleNamespace(source_root="", linked_docs={"ut_log_history": ["U:/p/Log/v1.02"],
                                                               "problem_list": "U:/q/PL/list.xlsx"})
    S._merge_paths_to_cloudium_prefixes(entry)
    merged = added["allowed_prefixes"].split(",")
    assert "U:/p/Log" in merged and "U:/q/PL" in merged
