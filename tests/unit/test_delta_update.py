from __future__ import annotations


def test_classify_changed_functions_signature_body_new_delete_header(monkeypatch, tmp_path):
    from workflow import delta_update

    diffs = {
        "a.c": """@@ -10,7 +10,7 @@ Foo_Run(
-static void Foo_Run(int old_value)
+static void Foo_Run(int new_value)
     if (new_value > 0) {
         Foo_Sub();
     }
""",
        "b.c": """@@ -20,5 +20,6 @@ Bar_Run(
     counter++;
+    flag = 1;
     return;
""",
        "c.c": """@@ -0,0 +1,5 @@ Baz_New(
+static void Baz_New(void)
+{
+    Baz_Sub();
+}
""",
        "d.c": """@@ -30,5 +0,0 @@ Old_Delete(
-static void Old_Delete(void)
-{
-    return;
-}
""",
        "e.h": """@@ -4,7 +4,7 @@ Foo_Header(
-void Foo_Header(uint8 old_arg);
+void Foo_Header(uint16 new_arg);
""",
    }

    monkeypatch.setattr(
        delta_update,
        "_run_unified_diff",
        lambda project_root, *, base_ref, scm_type, file_path=None: diffs.get(file_path or "", ""),
    )

    result = delta_update.classify_changed_functions(
        str(tmp_path),
        ["a.c", "b.c", "c.c", "d.c", "e.h"],
    )

    assert result["Foo_Run"] == "SIGNATURE"
    assert result["Bar_Run"] == "BODY"
    assert result["Baz_New"] == "NEW"
    assert result["Old_Delete"] == "DELETE"
    assert result["Foo_Header"] == "HEADER"


def test_classify_from_edit_types_skips_diff(monkeypatch, tmp_path):
    """edit_types(Jenkins changeSet)가 주어지면 git/svn diff를 호출하지 않고 파일 단위로 분류한다.

    add→NEW / delete→DELETE / .c edit→BODY / .h edit→HEADER / editType 미제공→확장자 기반.
    """
    from workflow import delta_update

    def _boom(*a, **k):
        raise AssertionError("edit_types가 있으면 _run_unified_diff를 호출하면 안 된다")

    monkeypatch.setattr(delta_update, "_run_unified_diff", _boom)

    result = delta_update.classify_changed_functions(
        str(tmp_path),
        ["Sources/APP/Ap_New.c", "Sources/APP/Ap_Old.c", "Sources/APP/Ap_Edit.c", "Sources/APP/Ap_Hdr.h", "Sources/APP/Ap_NoType.c"],
        edit_types={
            "Sources/APP/Ap_New.c": "add",
            "Sources/APP/Ap_Old.c": "delete",
            "Sources/APP/Ap_Edit.c": "edit",
            "Sources/APP/Ap_Hdr.h": "edit",
            # Ap_NoType.c는 editType 미제공 → 확장자 기반(BODY)
        },
    )
    assert result["ap_new"] == "NEW"        # 키는 파일 stem(소문자)
    assert result["ap_old"] == "DELETE"
    assert result["ap_edit"] == "BODY"
    assert result["ap_hdr"] == "HEADER"
    assert result["ap_notype"] == "BODY"


def test_classify_from_edit_types_path_normalization_and_priority(monkeypatch, tmp_path):
    """경로 구분자(\\ vs /) 정규화 + 동일 stem 다중파일에서 DELETE/NEW가 edit에 덮이지 않음."""
    from workflow import delta_update

    monkeypatch.setattr(delta_update, "_run_unified_diff",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("diff 금지")))

    result = delta_update.classify_changed_functions(
        str(tmp_path),
        ["src\\APP\\Ap_Mod.c"],   # 백슬래시 경로 — edit_types는 슬래시 키
        edit_types={"src/APP/Ap_Mod.c": "delete"},
    )
    assert result["ap_mod"] == "DELETE"   # \\→/ 정규화 후 매칭


def test_classify_changed_functions_variable_change_uses_hunk_context(monkeypatch, tmp_path):
    from workflow import delta_update

    diff_text = """@@ -42,6 +42,7 @@ Door_Run(
-static uint8 s_Mode;
+static uint8 s_Mode = 1;
     Door_Sub();
"""

    monkeypatch.setattr(
        delta_update,
        "_run_unified_diff",
        lambda project_root, *, base_ref, scm_type, file_path=None: diff_text,
    )

    result = delta_update.classify_changed_functions(str(tmp_path), ["door.c"])

    assert result["Door_Run"] == "VARIABLE"


def test_get_changed_functions_supports_svn_unified_diff(monkeypatch, tmp_path):
    from workflow import delta_update

    diff_text = """@@ -12,5 +12,6 @@ Lin_Run(
     checksum++;
"""

    calls = []

    def _fake_run(project_root, *, base_ref, scm_type, file_path=None):
        calls.append((base_ref, scm_type, file_path))
        return diff_text

    monkeypatch.setattr(delta_update, "_run_unified_diff", _fake_run)

    result = delta_update.get_changed_functions(
        str(tmp_path),
        ["lin.c"],
        scm_type="svn",
        base_ref="123:124",
    )

    assert result == {"Lin_Run"}
    assert calls == [("123:124", "svn", "lin.c")]


def test_get_changed_files_supports_svn_working_copy_status(monkeypatch, tmp_path):
    from workflow import delta_update

    class _Result:
        returncode = 0
        stdout = "M       Sources/APP/Ap_BuzzerCtrl_PDS.c\n?       notes.txt\nM       Sources/APP/Ap_BuzzerCtrl_it_PDS.h\n"

    def _fake_run(cmd, cwd, capture_output, text, timeout):
        assert cmd == ["svn", "status"]
        return _Result()

    monkeypatch.setattr(delta_update.subprocess, "run", _fake_run)

    result = delta_update.get_changed_files(str(tmp_path), scm_type="svn", base_ref="")

    assert result == ["Sources/APP/Ap_BuzzerCtrl_PDS.c", "Sources/APP/Ap_BuzzerCtrl_it_PDS.h"]
