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


def test_classify_changed_functions_from_diff_text_kinds_and_line_classified():
    """svn A:B(-x -p) 통합 diff → 함수단위 kind + narrow 가능 파일 집합.

    순수 본문/시그니처 편집 .c만 line_classified(narrow 대상). 모듈스코프 var/매크로/헤더 변경
    파일은 file_scope_change/헤더로 제외되어 파일단위 보수 분류를 유지한다(안전측)."""
    from workflow.delta_update import classify_changed_functions_from_diff_text
    blob = "\n".join([
        "Index: sources/pure_body.c",
        "===================================================================",
        "--- sources/pure_body.c\t(revision 100)",
        "+++ sources/pure_body.c\t(revision 150)",
        "@@ -10,4 +10,5 @@ Foo_Run(void)",
        "     int x = 1;",
        "-    return x;",
        "+    x += 2;",
        "+    return x;",
        "Index: sources/sig.c",
        "===================================================================",
        "--- sources/sig.c\t(revision 100)",
        "+++ sources/sig.c\t(revision 150)",
        "@@ -8,3 +8,3 @@ Sig_Fn(int old)",
        "-static void Sig_Fn(int old)",
        "+static void Sig_Fn(int old, int extra)",
        "     return;",
        "Index: sources/modvar.c",
        "===================================================================",
        "--- sources/modvar.c\t(revision 100)",
        "+++ sources/modvar.c\t(revision 150)",
        "@@ -5,3 +5,3 @@ Bar_Init(void)",
        "-static uint8 s_Mode;",
        "+static uint8 s_Mode = 1;",
        "     Bar_Sub();",
        "Index: sources/macro.c",
        "===================================================================",
        "--- sources/macro.c\t(revision 100)",
        "+++ sources/macro.c\t(revision 150)",
        "@@ -1,2 +1,2 @@ Mac_Fn(void)",
        "-#define MAXVAL 10",
        "+#define MAXVAL 20",
        "Index: include/hdr.h",
        "===================================================================",
        "--- include/hdr.h\t(revision 100)",
        "+++ include/hdr.h\t(revision 150)",
        "@@ -3,2 +3,2 @@",
        "-void Hdr_Proto(void);",
        "+void Hdr_Proto(int a);",
        "",
    ])
    types, lcf = classify_changed_functions_from_diff_text(blob)
    # kind는 narrowable 여부와 독립적으로 정확 — 시그니처/신규/삭제는 fatten 파일에서도 승격됨.
    assert types.get("Foo_Run") == "BODY"
    assert types.get("Sig_Fn") == "SIGNATURE"
    assert types.get("Bar_Init") == "VARIABLE"
    assert types.get("Hdr_Proto") == "HEADER"
    # allowlist: 순수 본문편집 .c(컬럼0/전처리/top-level 변경 없음, 전 hunk 함수귀속)만 narrow 가능.
    assert "sources/pure_body.c" in lcf
    # 시그니처(컬럼0)·모듈스코프 var(컬럼0)·매크로(전처리)·헤더 → narrow 제외(fatten 유지, 안전측).
    assert "sources/sig.c" not in lcf
    assert "sources/modvar.c" not in lcf
    assert "sources/macro.c" not in lcf
    assert not any(p.endswith(".h") for p in lcf)


def test_classify_from_diff_text_reordered_proto_not_signature():
    """프로토타입 재정렬/이동으로 동일 선언이 -/+ 양쪽에 나타나도 SIGNATURE로 오판하지 않는다.
    실제 선언 원문 before==after면 본문 변경(BODY)이다 — kjpds02에서 SIGNATURE 135개 중 134개가
    이 패턴(신규 24개 삽입으로 선언 블록이 밀려 동일 프로토타입이 -/+에 동시 등장)이었다."""
    from workflow.delta_update import classify_changed_functions_from_diff_text
    blob = "\n".join([
        "Index: sources/proto.c",
        "===================================================================",
        "--- sources/proto.c\t(revision 100)",
        "+++ sources/proto.c\t(revision 150)",
        "@@ -5,6 +5,7 @@",
        " static S16 keep_fn(S16 x);",
        "-static U32 moved_fn(U16 a, U16 b);",
        "+static U32 moved_fn(U16 a, U16 b);",
        "+static void new_fn(void);",
        "",
    ])
    types, _ = classify_changed_functions_from_diff_text(blob)
    # moved_fn은 선언 원문 동일(재정렬) → SIGNATURE 아님(BODY). new_fn은 한쪽만 → NEW.
    assert types.get("moved_fn") == "BODY", types
    assert types.get("new_fn") == "NEW", types

    # unknown(멀티라인 선언 — 원문 미확보)은 보수적으로 SIGNATURE 유지(실제 시그니처 변경 놓침 방지).
    blob2 = "\n".join([
        "Index: sources/multi.c",
        "===================================================================",
        "--- sources/multi.c\t(revision 100)",
        "+++ sources/multi.c\t(revision 150)",
        "@@ -5,6 +5,7 @@",
        "-static void multi_fn(int a,",
        "-                     int b);",
        "+static void multi_fn(int a,",
        "+                     int b,",
        "+                     int c);",
        "",
    ])
    types2, _ = classify_changed_functions_from_diff_text(blob2)
    assert types2.get("multi_fn") == "SIGNATURE", types2


def test_diff_has_function_context():
    """positive-context 가드 — -x -p 컨텍스트 유무를 rc와 독립적으로 판정."""
    from workflow.delta_update import diff_has_function_context
    assert diff_has_function_context("@@ -1,2 +1,2 @@ Foo(void)\n-a\n+b\n") is True
    assert diff_has_function_context("@@ -1,2 +1,2 @@\n-a\n+b\n") is False
    assert diff_has_function_context("") is False


def test_classify_from_diff_text_initializer_context_not_narrowable():
    """W1 하드닝 — `= MACRO(` 초기화자 값-전용 편집의 hunk 컨텍스트가 함수로 오귀속돼도
    narrowable=False(파일스코프 데이터 리더 함수 누락 방지). 함수 시그니처엔 '='가 없어 무영향."""
    from workflow.delta_update import classify_changed_functions_from_diff_text
    blob = "\n".join([
        "Index: sources/cfg.c",
        "@@ -3,4 +3,4 @@ static const Cfg_t g_cfg = MK_CFG( 1,",
        "     0x10,",
        "-    0x20,",
        "+    0x21,",
        "     0x30,",
        "",
    ])
    _types, lcf = classify_changed_functions_from_diff_text(blob)
    assert "sources/cfg.c" not in lcf
