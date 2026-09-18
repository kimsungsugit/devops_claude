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


def test_classify_indented_local_var_is_body_not_variable():
    """들여쓴 지역변수 추가(함수 본문 내)는 BODY — VARIABLE(글로벌 변경) 오분류 아님.

    시그니처가 hunk context(무변경)인 함수에 지역변수 `+    S32 s32t_NextIdx;`가 추가되고
    본문 로직이 바뀌면, 과거 `^[+-]\\s*`가 들여쓴 지역변수를 파일 전체 var_changed로 잡아
    VARIABLE로 오분류했다(deep-review). 컬럼0 한정으로 BODY 정정. VARIABLE·BODY는 둘 다
    sds FLAG 무관이라 안전 판정 불변.
    """
    from workflow.delta_update import classify_changed_functions_from_diff_text
    diff = (
        "Index: Ap_Lookup.c\n"
        "===================================================================\n"
        "--- Ap_Lookup.c\t(revision 1018)\n"
        "+++ Ap_Lookup.c\t(revision 1075)\n"
        "@@ -4804,7 +3254,8 @@ static U16 prv_FindBracketIdx(const S16 val, const U16 len)\n"
        "     U16 u16t_NextIdx;\n"
        "-\n"
        "+    S32 s32t_NextIdx;\n"
        "     if( len >= (U16)2U )\n"
        "@@ -4819,9 +3270,9 @@ static U16 prv_FindBracketIdx(const S16 val, const U16 len)\n"
        "-            u16t_NextIdx = (U16)(u16t_SearchIdx + 1U);\n"
        "+            s32t_NextIdx = (S32)u16t_SearchIdx + (S32)1L;\n"
        "+            u16t_NextIdx = (U16)s32t_NextIdx;\n"
    )
    types, _ = classify_changed_functions_from_diff_text(diff)
    assert types.get("prv_FindBracketIdx") == "BODY", types  # 지역변수→BODY(VARIABLE 아님)


def test_classify_column0_global_var_still_variable():
    """컬럼0(모듈 레벨) 전역/정적 변경은 VARIABLE 유지 — 지역변수 fix의 무회귀 대조군."""
    from workflow.delta_update import classify_changed_functions_from_diff_text
    diff = (
        "Index: modvar.c\n"
        "===================================================================\n"
        "--- modvar.c\t(revision 100)\n"
        "+++ modvar.c\t(revision 150)\n"
        "@@ -5,3 +5,3 @@ Bar_Init(void)\n"
        "-static uint8 s_Mode;\n"
        "+static uint8 s_Mode = 1;\n"
        "     Bar_Sub();\n"
    )
    types, _ = classify_changed_functions_from_diff_text(diff)
    assert types.get("Bar_Init") == "VARIABLE", types  # 컬럼0 전역은 VARIABLE 유지


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

    # 멀티라인 선언도 _reconstruct_diff_decls로 복원 비교 — int c 추가로 -/+ 선언이 실제로 달라
    # SIGNATURE로 '정확히' 판정된다(과거엔 멀티라인을 스킵→verdict 'unknown'→보수적 SIGNATURE로
    # 우연히 통과. 동일 멀티라인은 그 경로에서 false SIGNATURE '원문 미확보'로 갇혔다 — 아래 전용 테스트).
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


def test_classify_multiline_identical_decl_is_body_not_false_signature():
    """리포맷/재정렬 churn으로 **멀티라인** 선언이 -/+ 양쪽에 '동일'하게 나타나면 SIGNATURE가
    아니라 BODY다(실측: kjpds02 r1018:HEAD에서 파일 전체 removed+added churn 시 s_sha256_expand_word·
    s_sha256_round_step·s_SysEepromCtrl_CopyTunningTables가 이 패턴). 과거엔 멀티라인 첫 줄(`(`만
    열림)을 통째 스킵→verdict 'unknown'→보수적 SIGNATURE→UI '원문 미확보'로 갇혔고, 단일라인 형제
    함수는 same→BODY로 정상 강등되던 것과 비대칭이었다. _reconstruct_diff_decls 복원으로 -/+ 동일 판정."""
    from workflow.delta_update import classify_changed_functions_from_diff_text
    blob = "\n".join([
        "Index: sources/reformat.c",
        "===================================================================",
        "--- sources/reformat.c\t(revision 100)",
        "+++ sources/reformat.c\t(revision 150)",
        "@@ -1,8 +1,8 @@",
        "-static U32 s_expand( U32 a,",
        "-                     U32 b,",
        "-                     U32 c );",
        "-static void keep_single( int x );",
        "+static U32 s_expand( U32 a,",
        "+                     U32 b,",
        "+                     U32 c );",
        "+static void keep_single( int x );",
        "",
    ])
    types, _ = classify_changed_functions_from_diff_text(blob)
    # 멀티라인·단일라인 모두 -/+ 동일 → 둘 다 BODY(false SIGNATURE '원문 미확보' 아님).
    assert types.get("s_expand") == "BODY", types
    assert types.get("keep_single") == "BODY", types


def test_extract_signature_changes_multiline_reconstructed():
    """멀티라인 선언 복원(extract_signature_changes): 실제 파라미터 변경은 before/after가 서로 다르게
    채워져 UI가 이전→이후를 렌더하고, -/+ 동일한 리포맷 churn은 before==after(호출측이 '변화 없음'으로
    change_details 미등록)다. 종전엔 멀티라인이면 여는 괄호까지만 잡혀 스킵→before/after 공백→'원문 미확보'."""
    from workflow.delta_update import extract_signature_changes
    # (a) 진짜 멀티라인 시그니처 변경(int c 추가) → before != after, 둘 다 채워짐(정규화된 단일 문자열).
    changed = "\n".join([
        "--- m.c\t(r1)", "+++ m.c\t(r2)", "@@ -1,2 +1,3 @@",
        "-static void f( int a,", "-               int b );",
        "+static void f( int a,", "+               int b,", "+               int c );",
    ])
    sig = extract_signature_changes(changed)
    assert sig.get("f", {}).get("before") == "static void f( int a, int b )", sig
    assert sig.get("f", {}).get("after") == "static void f( int a, int b, int c )", sig
    assert sig["f"]["before"] != sig["f"]["after"]
    # (b) 동일 멀티라인(리포맷 churn) → before == after(orchestrator가 미표시로 처리).
    identical = "\n".join([
        "--- m.c\t(r1)", "+++ m.c\t(r2)", "@@ -1,2 +1,2 @@",
        "-static void g( int a,", "-               int b );",
        "+static void g( int a,", "+               int b );",
    ])
    sig2 = extract_signature_changes(identical)
    assert sig2.get("g", {}).get("before") == "static void g( int a, int b )", sig2
    assert sig2["g"]["before"] == sig2["g"]["after"], sig2


def test_extract_signature_changes_cross_file_not_masked():
    """동명 static 함수가 여러 파일에 있고 한 파일은 무변화(동일 선언 -/+), 다른 파일은 실제 변경일 때,
    무변화 파일이 **먼저 와도** '진짜 바뀐' before/after를 표시한다(집합 차로 동일쌍 상쇄). 과거
    setdefault(함수당 첫 매치)는 무변화 동일쌍을 집어 before==after → orchestrator가 change_details에서
    스킵 → 분류는 SIGNATURE인데 UI '원문 미확보'로 표시됐다(멀티라인 fix와 별개인 두 번째 미확보 경로)."""
    from workflow.delta_update import (
        classify_changed_functions_from_diff_text,
        extract_signature_changes,
    )
    blob = "\n".join([
        "Index: a.c",
        "===================================================================",
        "--- a.c\t(revision 1018)",
        "+++ a.c\t(revision 1053)",
        "@@ -10,3 +10,3 @@ s_foo(void)",
        "-static U32 s_foo( U32 a );",
        "+static U32 s_foo( U32 a );",         # a.c: 무변화(동일 선언) — 먼저 등장
        " body_unchanged();",
        "Index: b.c",
        "===================================================================",
        "--- b.c\t(revision 1018)",
        "+++ b.c\t(revision 1053)",
        "@@ -20,3 +20,3 @@ s_foo(void)",
        "-static U32 s_foo( U32 a );",
        "+static U32 s_foo( U32 a, U32 b );",  # b.c: 실제 파라미터 추가
        " body();",
        "",
    ])
    types, _ = classify_changed_functions_from_diff_text(blob)
    sig = extract_signature_changes(blob)
    # 분류는 SIGNATURE(b.c 실변경) — 파일 스코프 판정이라 이전에도 정확.
    assert types.get("s_foo") == "SIGNATURE", types
    # 핵심: before/after가 '진짜 바뀐' 쌍이라 무변화 동일쌍에 가려지지 않는다(원문 미확보 소멸).
    assert sig.get("s_foo", {}).get("before") == "static U32 s_foo( U32 a )", sig
    assert sig.get("s_foo", {}).get("after") == "static U32 s_foo( U32 a, U32 b )", sig
    assert sig["s_foo"]["before"] != sig["s_foo"]["after"], sig


def test_classify_continuation_line_signature_not_underreported():
    """멀티라인 함수의 첫 줄(함수명)이 context(무변경)이고 **파라미터 연속행만** -/+로 바뀌면, 변경
    라인에 `funcname(` 토큰이 없어 과거엔 func_decl_names 공백으로 SIGNATURE→VARIABLE/BODY로
    under-report됐다(deep-review 발견1 — ACTION_MATRIX상 SDS 자동 FLAG 누락, ISO 26262 최악 방향).
    OLD/NEW 투영 복원으로 SIGNATURE 정확 판정 + before/after 표시."""
    from workflow.delta_update import (
        classify_changed_functions_from_diff_text,
        extract_signature_changes,
    )
    # (1) 끝에 파라미터 추가 (첫 줄 = context)
    add = "\n".join([
        "Index: APP/sha.c",
        "--- APP/sha.c\t(revision 1018)",
        "+++ APP/sha.c\t(revision 1053)",
        "@@ -40,7 +40,8 @@ static U32 s_expand( U32 a,",
        " static U32 s_expand( U32 a,",
        "                      U32 b,",
        "-                     U32 c )",
        "+                     U32 c,",
        "+                     U32 d )",
        " {",
        "     return a;",
    ])
    types, _ = classify_changed_functions_from_diff_text(add)
    assert types.get("s_expand") == "SIGNATURE", types  # VARIABLE/BODY under-report 아님
    sig = extract_signature_changes(add)
    assert sig.get("s_expand", {}).get("before") == "static U32 s_expand( U32 a, U32 b, U32 c )", sig
    assert sig.get("s_expand", {}).get("after") == "static U32 s_expand( U32 a, U32 b, U32 c, U32 d )", sig
    assert sig["s_expand"]["before"] != sig["s_expand"]["after"]

    # (2) 중간 파라미터 타입 변경(연속행) — U32 b → U16 b
    typ = "\n".join([
        "Index: a.c",
        "--- a.c\t(r1)",
        "+++ a.c\t(r2)",
        "@@ -1,5 +1,5 @@ void k( int a,",
        " void k( int a,",
        "-        U32 b,",
        "+        U16 b,",
        "         int c )",
        " {",
    ])
    types2, _ = classify_changed_functions_from_diff_text(typ)
    assert types2.get("k") == "SIGNATURE", types2

    # (3) -/+ 라인단위 교차(interleaved) — 투영은 순서무관 수집이라 복원됨(deep-review 발견2a 부수해결).
    inter = "\n".join([
        "Index: a.c",
        "--- a.c\t(r1)",
        "+++ a.c\t(r2)",
        "@@ -1,4 +1,5 @@",
        "-static U32 f( U32 a,",
        "+static U32 f( U32 a,",
        "-              U32 b )",
        "+              U32 b,",
        "+              U32 c )",
        " {",
    ])
    types3, _ = classify_changed_functions_from_diff_text(inter)
    sig3 = extract_signature_changes(inter)
    assert types3.get("f") == "SIGNATURE", types3
    assert sig3.get("f", {}).get("before") == "static U32 f( U32 a, U32 b )", sig3
    assert sig3.get("f", {}).get("after") == "static U32 f( U32 a, U32 b, U32 c )", sig3


def test_projection_identical_multiline_no_false_signature():
    """리포맷 churn(첫 줄 포함 전체 -/+ 동일)은 OLD/NEW 투영이 동일 → 승격 안 함(BODY 유지).
    발견1 승격이 c88f820의 무변화-멀티라인 판정을 되살리지(false SIGNATURE) 않음을 고정한다."""
    from workflow.delta_update import (
        _sig_changes_from_projections,
        classify_changed_functions_from_diff_text,
    )
    churn = "\n".join([
        "Index: a.c",
        "--- a.c\t(r1)",
        "+++ a.c\t(r2)",
        "@@ -1,4 +1,4 @@",
        "-static U32 s_x( U32 a,",
        "-                U32 b );",
        "+static U32 s_x( U32 a,",
        "+                U32 b );",
    ])
    assert _sig_changes_from_projections(churn) == {}   # old==new → 방출 안 함(over-report 없음)
    types, _ = classify_changed_functions_from_diff_text(churn)
    assert types.get("s_x") == "BODY", types


def test_classify_from_diff_text_forward_decl_plus_real_change_not_masked():
    """C1: 같은 파일에 forward-decl(재정렬·무변화)과 definition(진짜 파라미터 추가)이 공존해도
    진짜 시그니처 변경이 은폐되지 않고 SIGNATURE로 유지된다(함수별 '모든' -/+ 선언 집합 비교).
    forward-decl이 텍스트상 먼저 나와도(이 코드베이스 관행) 첫-매치 고정으로 놓치지 않아야 한다."""
    from workflow.delta_update import classify_changed_functions_from_diff_text
    blob = "\n".join([
        "Index: sources/mod.c",
        "===================================================================",
        "--- sources/mod.c\t(revision 100)",
        "+++ sources/mod.c\t(revision 150)",
        "@@ -5,6 +5,7 @@",
        " static S16 keep(S16 x);",
        "-static U32 moved_fn(U16 a, U16 b);",   # forward-decl 재정렬(무변화)
        "+static U32 moved_fn(U16 a, U16 b);",
        "+static void new_fn(void);",
        "@@ -50,3 +51,3 @@ moved_fn(U16 a, U16 b)",
        "-static U32 moved_fn(U16 a, U16 b)",     # definition — 진짜 파라미터 c 추가
        "+static U32 moved_fn(U16 a, U16 b, U16 c)",
        "     return 0;",
        "",
    ])
    types, _ = classify_changed_functions_from_diff_text(blob)
    assert types.get("moved_fn") == "SIGNATURE", types
    # hunk 순서를 반전해도(정의가 먼저) 동일해야 — 순서 의존 결함 회귀 방지.
    lines = blob.split("\n")
    idx = lines.index("@@ -50,3 +51,3 @@ moved_fn(U16 a, U16 b)")
    reordered = lines[:4] + lines[idx:idx + 4] + lines[4:idx] + lines[idx + 4:]
    types_r, _ = classify_changed_functions_from_diff_text("\n".join(reordered))
    assert types_r.get("moved_fn") == "SIGNATURE", types_r


def test_classify_from_diff_text_crossfile_homonym_static_not_masked():
    """C2: 다른 두 파일에 동명 static 함수 — fileA는 재정렬만, fileB는 진짜 변경. 파일 스코프로
    분할 분류 후 병합 시 강한 kind(SIGNATURE)가 보존된다(전체 blob 스코프 오강등 방지)."""
    from workflow.delta_update import classify_changed_functions_from_diff_text
    blob = "\n".join([
        "Index: sources/module_a.c",
        "===================================================================",
        "--- sources/module_a.c\t(revision 100)",
        "+++ sources/module_a.c\t(revision 150)",
        "@@ -5,3 +5,4 @@",
        "-static U32 moved_fn(U16 a, U16 b);",
        "+static U32 moved_fn(U16 a, U16 b);",
        "+static void new_fn(void);",
        "Index: sources/module_b.c",
        "===================================================================",
        "--- sources/module_b.c\t(revision 100)",
        "+++ sources/module_b.c\t(revision 150)",
        "@@ -10,3 +10,3 @@",
        "-static U32 moved_fn(U16 a);",
        "+static U32 moved_fn(U16 a, U16 b);",
        "",
    ])
    types, _ = classify_changed_functions_from_diff_text(blob)
    assert types.get("moved_fn") == "SIGNATURE", types


def test_extract_function_diffs_per_function_hunks():
    """함수별 본문 diff hunk를 함수 컨텍스트(@@..@@ func)로 귀속 — 소문자 키, 함수 간 미혼입."""
    from workflow.delta_update import extract_function_diffs
    diff = "\n".join([
        "Index: sources/eeprom.c",
        "===================================================================",
        "--- sources/eeprom.c\t(revision 100)", "+++ sources/eeprom.c\t(revision 150)",
        "@@ -10,4 +10,5 @@ g_Main(void)",
        "     U8 s = 0;", "-    if (a) {", "+    if (a && b) {", "         w();",
        "@@ -50,3 +51,3 @@ s_Calc(U16 addr)",
        "-    sum = addr;", "+    sum = addr ^ 0xFF;", "     return sum;", "",
    ])
    r = extract_function_diffs(diff)
    assert "g_main" in r and "s_calc" in r          # 소문자 키(조인 규약)
    assert "if (a && b)" in r["g_main"]
    assert "addr ^ 0xFF" in r["s_calc"]
    assert "addr ^ 0xFF" not in r["g_main"]         # 함수 귀속 분리(미혼입)


def test_extract_function_diffs_line_cap():
    """함수당 max_lines_per_func 절단으로 프롬프트 크기 관리 — 생략 안내 포함."""
    from workflow.delta_update import extract_function_diffs
    body = "\n".join(f"+    x{i} = {i};" for i in range(100))
    diff = "\n".join([
        "Index: sources/big.c",
        "===================================================================",
        "--- sources/big.c\t(revision 100)", "+++ sources/big.c\t(revision 150)",
        "@@ -1,1 +1,100 @@ big_fn(void)", body, "",
    ])
    r = extract_function_diffs(diff, max_lines_per_func=20)
    assert "생략" in r["big_fn"]
    assert len(r["big_fn"].splitlines()) <= 22      # 20줄 + 생략 안내


def test_diff_has_function_context():
    """positive-context 가드 — -x -p 컨텍스트 유무를 rc와 독립적으로 판정."""
    from workflow.delta_update import diff_has_function_context
    assert diff_has_function_context("@@ -1,2 +1,2 @@ Foo(void)\n-a\n+b\n") is True
    assert diff_has_function_context("@@ -1,2 +1,2 @@\n-a\n+b\n") is False
    assert diff_has_function_context("") is False


def test_classify_excludes_header_over_attribution():
    """@@ 헤더 과다귀속 정정 — 헤더는 prev_fn(주석/이웃 함수)인데 실제 변경이 real_fn 정의면,
    본문 미변경 prev_fn은 changed에서 제외되고 real_fn만 남는다(허위 evidence='line' 방지)."""
    from workflow.delta_update import classify_changed_functions_from_diff_text
    diff = "\n".join([
        "Index: sources/mod.c",
        "===================================================================",
        "--- sources/mod.c\t(revision 100)",
        "+++ sources/mod.c\t(revision 150)",
        # @@ 헤더는 prev_fn을 가리키나 hunk 본문 변경은 real_fn(주석 블록 아래 이웃 함수)
        "@@ -1200,6 +1200,6 @@ U8 prev_fn( U16 addr )",
        "     doc_ctx();",
        "-U8 real_fn( U16 a )",
        "-{ return a; }",
        "+U8 real_fn( U16 a )",
        "+{ return a + 1; }",
        "",
    ])
    types, _ = classify_changed_functions_from_diff_text(diff)
    keys = {k.lower() for k in types}
    assert "real_fn" in keys       # 실제 변경 함수는 유지
    assert "prev_fn" not in keys   # 헤더-only 과다귀속은 제외


def test_classify_keeps_enclosing_fn_on_nested_decl_in_narrowable():
    """deep-review S3 회귀 — narrowable 파일에서 함수 본문에 들여쓴 선언성 라인(nested extern)이
    단독 변경돼도 감싸는 실함수가 오제거되지 않는다(과다귀속 정정은 fatten에만 적용)."""
    from workflow.delta_update import classify_changed_functions_from_diff_text
    diff = "\n".join([
        "Index: src/app.c",
        "===================================================================",
        "--- src/app.c\t(revision 100)",
        "+++ src/app.c\t(revision 150)",
        # 순수 함수-본문 편집(컬럼0/전처리 변경 없음) → narrowable. 변경=본문 내 들여쓴 extern 선언.
        "@@ -10,4 +10,5 @@ void EnclosingFn( void )",
        "     do_a();",
        "+    extern U8 legacy_helper( U8 x );",
        "     do_b();",
        " }",
        "",
    ])
    types, lcf = classify_changed_functions_from_diff_text(diff)
    keys = {k.lower() for k in types}
    assert any("app.c" in p for p in lcf)   # narrowable(line-classified) 파일 확인
    assert "enclosingfn" in keys            # 감싸는 실함수 유지(under-report 방지)


def test_classify_keeps_header_fnptr_proto():
    """deep-review S2 회귀 — 헤더의 함수포인터-반환 프로토타입 변경이 오제거되지 않는다
    (_FUNC_DECL_LINE 미매치 → func_proto_names로 실변경 증거 보강)."""
    from workflow.delta_update import classify_changed_functions_from_diff_text
    diff = "\n".join([
        "Index: inc/sched.h",
        "===================================================================",
        "--- inc/sched.h\t(revision 100)",
        "+++ inc/sched.h\t(revision 150)",
        "@@ -5,3 +5,3 @@",
        "-void (*Sched_GetCb( U8 id ))( void );",
        "+void (*Sched_GetCb( U16 id ))( void );",
        "",
    ])
    types, _ = classify_changed_functions_from_diff_text(diff)
    keys = {k.lower() for k in types}
    assert "sched_getcb" in keys            # 헤더 fnptr proto 유지(under-report 방지)


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


def test_classify_non_allowlist_return_type_signature_delete_new_not_bodied():
    """W1(under-report): 반환타입이 프로젝트 고유(byte/UINT8/word/Std_ReturnType/typedef)여도
    SIGNATURE/NEW/DELETE가 BODY로 오분류되지 않는다. 과거엔 닫힌 allowlist라 실 kjpds02 ~9.5%
    함수가 유형 유실 → SDS FLAG 누락·삭제함수 impact 유실. 반환타입을 '제어키워드 아닌 식별자'로
    구조 인식해 해결."""
    from workflow.delta_update import classify_changed_functions_from_diff_text
    blob = "\n".join([
        "Index: sources/adc.c",
        "===================================================================",
        "--- sources/adc.c\t(revision 100)",
        "+++ sources/adc.c\t(revision 150)",
        "@@ -8,3 +8,3 @@ ADC_Measure(bool w)",
        "-byte ADC_Measure(bool w)",
        "+byte ADC_Measure(bool w, uint8 timeout)",
        "     return 0;",
        "Index: sources/reader.c",
        "===================================================================",
        "--- sources/reader.c\t(revision 100)",
        "+++ sources/reader.c\t(revision 150)",
        "@@ -20,4 +20,0 @@ Old_Reader(void)",
        "-byte Old_Reader(void)",
        "-{",
        "-    return 42;",
        "-}",
        "Index: sources/lin.c",
        "===================================================================",
        "--- sources/lin.c\t(revision 100)",
        "+++ sources/lin.c\t(revision 150)",
        "@@ -3,0 +3,4 @@ (none)",
        "+UINT8 lin_new_reader(uint8 id)",
        "+{",
        "+    return id;",
        "+}",
        "",
    ])
    types, _ = classify_changed_functions_from_diff_text(blob)
    assert types.get("ADC_Measure") == "SIGNATURE", types    # byte 반환 — 과거 BODY(SDS FLAG 유실)
    assert types.get("Old_Reader") == "DELETE", types         # byte 반환 삭제 — 과거 BODY(impact 유실)
    assert types.get("lin_new_reader") == "NEW", types        # UINT8 반환 신규 — 과거 BODY


def test_classify_call_and_assignment_not_misdetected_as_declaration():
    """반환타입 broadening의 오탐 방지: 함수 호출·대입·return문은 선언(NEW/DELETE/SIGNATURE)으로
    오인식되지 않는다(2-토큰 `<type> <name>(` 구조 + 제어키워드 negative lookahead → over-report 억제)."""
    from workflow.delta_update import classify_changed_functions_from_diff_text
    blob = "\n".join([
        "Index: sources/body_only.c",
        "===================================================================",
        "--- sources/body_only.c\t(revision 100)",
        "+++ sources/body_only.c\t(revision 150)",
        "@@ -10,4 +10,5 @@ Caller_Fn(void)",
        "     int x;",
        "-    x = compute(a);",
        "+    x = compute(a) + adjust(b);",
        "+    return helper(x);",
        "",
    ])
    types, _ = classify_changed_functions_from_diff_text(blob)
    # 본문 내 호출/대입/return만 바뀐 함수 → BODY. 호출된 compute/adjust/helper를 NEW로 오탐하지 않음.
    assert types.get("Caller_Fn") == "BODY", types
    assert "compute" not in types and "adjust" not in types and "helper" not in types, types
