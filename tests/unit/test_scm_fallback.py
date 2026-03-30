from __future__ import annotations


def test_diff_source_snapshot_first_run_marks_all_changed(tmp_path, monkeypatch):
    from workflow import scm_fallback

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.c").write_text("int a(void){return 0;}\n", encoding="utf-8")
    (src / "b.h").write_text("#define B 1\n", encoding="utf-8")

    monkeypatch.setattr(scm_fallback, "AUDIT_DIR", tmp_path / "audit")

    diff = scm_fallback.diff_source_snapshot("hdpdm01", str(src))

    assert sorted(diff["changed_files"]) == ["a.c", "b.h"]
    scm_fallback.save_source_snapshot("hdpdm01", diff["current_snapshot"])
    assert (tmp_path / "audit" / ".source_snapshot_hdpdm01.json").exists()


def test_diff_source_snapshot_detects_modified_and_removed(tmp_path, monkeypatch):
    from workflow import scm_fallback

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.c").write_text("int a(void){return 0;}\n", encoding="utf-8")
    (src / "b.h").write_text("#define B 1\n", encoding="utf-8")

    monkeypatch.setattr(scm_fallback, "AUDIT_DIR", tmp_path / "audit")

    first = scm_fallback.diff_source_snapshot("hdpdm01", str(src))
    scm_fallback.save_source_snapshot("hdpdm01", first["current_snapshot"])

    (src / "a.c").write_text("int a(void){return 1;}\n", encoding="utf-8")
    (src / "b.h").unlink()

    second = scm_fallback.diff_source_snapshot("hdpdm01", str(src))

    assert "a.c" in second["changed_files"]
    assert "b.h" in second["changed_files"]
    assert second["removed_files"] == ["b.h"]


def test_diff_source_snapshot_respects_watch_and_ignore(tmp_path, monkeypatch):
    from workflow import scm_fallback

    src = tmp_path / "src"
    (src / "keep").mkdir(parents=True)
    (src / "skip").mkdir(parents=True)
    (src / "keep" / "a.c").write_text("int a(void){return 0;}\n", encoding="utf-8")
    (src / "skip" / "b.c").write_text("int b(void){return 0;}\n", encoding="utf-8")
    (src / "keep" / "note.txt").write_text("ignore me\n", encoding="utf-8")

    monkeypatch.setattr(scm_fallback, "AUDIT_DIR", tmp_path / "audit")

    snap = scm_fallback.collect_source_snapshot(
        str(src),
        watch_patterns=["*.c"],
        ignore_patterns=["skip/*"],
    )

    assert sorted((snap.get("files") or {}).keys()) == ["keep/a.c"]
