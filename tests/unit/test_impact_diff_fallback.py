"""Phase 1 — 로컬 diff 경로의 function_diffs 폴백("원문 절단" 해소) 검증.

evidence='line'인데 _precise_diff_text가 없는 로컬 경로에서, per-file svn diff에 -x -p(show-c-function)를
붙여 함수 컨텍스트를 얻고, 그 원문을 diff_sink로 모아 function_diffs 추출에 공유한다.
"""
from __future__ import annotations


def test_run_unified_diff_svn_uses_p_flag(monkeypatch, tmp_path):
    """svn diff는 -x -p(show-c-function)를 붙이고 외부 --diff-cmd를 쓰지 않는다(svn_diff_unified 동형)."""
    from workflow import delta_update

    captured = {}

    class _R:
        returncode = 0
        stdout = "Index: a.c\n@@ -1,1 +1,1 @@ void foo(void)\n-x\n+y\n"

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        return _R()

    monkeypatch.setattr(delta_update.subprocess, "run", _fake_run)
    out = delta_update._run_unified_diff(str(tmp_path), base_ref="1000", scm_type="svn", file_path="a.c")

    assert "-x" in captured["cmd"] and "-p" in captured["cmd"]   # 함수 컨텍스트
    assert "--diff-cmd" not in captured["cmd"]                    # svn 내부 diff로 전환
    assert "foo" in out


def test_extract_function_diffs_attributes_from_context():
    """@@…@@ func 컨텍스트가 있으면 함수별 본문 diff를 귀속한다(원문 절단 해소의 핵심 소비자)."""
    from workflow.delta_update import extract_function_diffs

    diff = (
        "Index: DrvIn.c\n"
        "@@ -10,3 +10,4 @@ void g_drvin_drv8706sq_init(void)\n"
        "     spi_init();\n"
        "+    reg_write(0x1);\n"
        "     return;\n"
    )
    out = extract_function_diffs(diff)
    assert "g_drvin_drv8706sq_init" in out
    assert "reg_write" in out["g_drvin_drv8706sq_init"]


def test_collect_signature_changes_shares_local_diff_via_sink(monkeypatch, tmp_path):
    """로컬 경로에서 받은 per-file diff 원문을 diff_sink에 모아 function_diffs 소비자와 공유(재-diff 없음)."""
    from workflow import delta_update
    from workflow import impact_orchestrator as m

    fake_diff = (
        "Index: DrvIn.c\n"
        "@@ -1,2 +1,3 @@ void g_drvin_drv8706sq_init(void)\n"
        "     a;\n"
        "+    b;\n"
    )
    # _collect_signature_changes 로컬 분기는 delta_update._run_unified_diff를 함수 내부에서 import.
    monkeypatch.setattr(delta_update, "_run_unified_diff", lambda *a, **k: fake_diff)

    class _T:
        scm_type = "svn"
        changed_files = ["DrvIn.c"]
        base_ref = ""
        scm_id = "x"

    class _E:
        source_root = str(tmp_path)
        scm_url = ""

    sink: list = []
    m._collect_signature_changes(_T(), {}, _E(), diff_text="", diff_sink=sink)

    assert sink and "g_drvin_drv8706sq_init" in sink[0]
    # 공유된 원문으로 function_diffs 귀속이 가능해야 "원문 절단"이 사라진다.
    fd = delta_update.extract_function_diffs("".join(sink))
    assert "g_drvin_drv8706sq_init" in fd


# ── extract_function_diffs 귀속 정렬(분류기 func_decl_names 미러) 회복 케이스 ──────────
# 근본: @@ 헤더로만 귀속하던 추출기가, 분류기(evidence='line')가 본문 +/- 선언 라인으로 잡은
# 함수를 못 담아 "원문 절단"이 떴다. 아래는 그 회복(NEW/DELETE/이동시그니처)과 안전성(미혼입·
# 가비지 없음)을 검증한다.


def test_extract_function_diffs_recovers_new_function_via_decl():
    """NEW: @@ 헤더가 이전 함수를 가리켜도 본문 +선언 라인으로 재귀속해 신규 함수 원문을 회복.

    prev_fn은 실변경(+/-) 없이 컨텍스트뿐 → 방출 게이트에 걸려 키가 생기지 않는다(미혼입).
    """
    from workflow.delta_update import extract_function_diffs

    diff = "\n".join([
        "Index: mod.c",
        "@@ -20,2 +20,7 @@ void prev_fn(void)",
        "     prev_body();",
        "     return;",
        "+void new_fn(U16 a)",
        "+{",
        "+    do_work(a);",
        "+}",
        "",
    ])
    out = extract_function_diffs(diff)
    assert "new_fn" in out
    assert "do_work(a)" in out["new_fn"]
    assert "prev_fn" not in out  # 컨텍스트-only → 미방출(가짜 귀속 없음)


def test_extract_function_diffs_recovers_deleted_function_via_decl():
    """DELETE: 삭제된 함수(-선언)를 본문 선언 라인으로 재귀속(by_name 부재라도 회복)."""
    from workflow.delta_update import extract_function_diffs

    diff = "\n".join([
        "Index: mod.c",
        "@@ -30,7 +30,2 @@ void keep_fn(void)",
        "     keep_body();",
        "     return;",
        "-void old_fn(void)",
        "-{",
        "-    legacy_call();",
        "-}",
        "",
    ])
    out = extract_function_diffs(diff)
    assert "old_fn" in out
    assert "legacy_call" in out["old_fn"]
    assert "keep_fn" not in out


def test_extract_function_diffs_recovers_body_via_moved_signature():
    """BODY: 이동/재포맷된 시그니처(-/+ 동일 선언)가 다른 함수의 @@ 헤더 아래 있어도 재귀속.

    g_DrvIn_MotorSpeed류(라이브에서 원문 절단으로 뜨던 실 케이스)의 대표 회복 시나리오.
    """
    from workflow.delta_update import extract_function_diffs

    diff = "\n".join([
        "Index: DrvIn_Main.c",
        "@@ -50,6 +50,7 @@ void other_fn(void)",
        "     other_body();",
        "-void g_DrvIn_MotorSpeed(void)",
        "+void g_DrvIn_MotorSpeed(void)",
        " {",
        "-    speed = raw;",
        "+    speed = raw * 2;",
        " }",
        "",
    ])
    out = extract_function_diffs(diff)
    assert "g_drvin_motorspeed" in out  # 소문자 키
    assert "speed = raw * 2" in out["g_drvin_motorspeed"]
    assert "speed = raw * 2" not in out.get("other_fn", "")  # 미혼입


def test_extract_function_diffs_multi_function_hunk_splits():
    """한 hunk가 헤더 함수 + 본문 신규 선언 함수를 포함 → 각각 분리 귀속(미혼입)."""
    from workflow.delta_update import extract_function_diffs

    diff = "\n".join([
        "Index: mod.c",
        "@@ -10,4 +10,9 @@ void a_fn(void)",
        "-    a_val = 1;",
        "+    a_val = 2;",
        " }",
        "+void b_fn(void)",
        "+{",
        "+    b_val = 4;",
        "+}",
        "",
    ])
    out = extract_function_diffs(diff)
    assert "a_fn" in out and "b_fn" in out
    assert "a_val = 2" in out["a_fn"] and "b_val = 4" in out["b_fn"]
    assert "b_val = 4" not in out["a_fn"]
    assert "a_val = 2" not in out["b_fn"]


def test_extract_function_diffs_no_spurious_key_from_non_defs():
    """본문 +/- 라인이 제어문/함수 호출/함수포인터면 재귀속하지 않는다(가비지 키·미혼입 방지)."""
    from workflow.delta_update import extract_function_diffs

    diff = "\n".join([
        "Index: mod.c",
        "@@ -5,5 +5,6 @@ void host_fn(void)",
        "-    if (ready()) {",
        "+    if (ready() && ok()) {",
        "+    result = compute(a, b);",
        "     void (*cb)(int) = handler;",
        "     done();",
        "",
    ])
    out = extract_function_diffs(diff)
    assert set(out.keys()) == {"host_fn"}  # 오직 헤더 함수만 — 가비지 키 없음
    assert "compute(a, b)" in out["host_fn"]  # 변경은 host_fn에 귀속(미혼입 없음)


def test_extract_function_diffs_stats_report_decl_reattribution():
    """stats에 본문 선언 재귀속 수(attributed_via_decl)를 보고한다(관찰성)."""
    from workflow.delta_update import extract_function_diffs

    diff = "\n".join([
        "Index: mod.c",
        "@@ -1,2 +1,6 @@ void prev(void)",
        "     x();",
        "+void added(void)",
        "+{",
        "+    y();",
        "+}",
        "",
    ])
    st: dict = {}
    out = extract_function_diffs(diff, stats=st)
    assert "added" in out
    assert st.get("attributed_via_decl", 0) >= 1
    assert st.get("truncated") is False


def test_extract_function_diffs_blank_line_not_counted_as_change():
    """방출 게이트: 실변경(+/-) 없이 0-length 빈 줄만 있는 세그먼트는 방출하지 않는다.

    회귀 — 과거 `s[:1] in "+-"`는 s=""일 때 True가 돼(빈문자열 부분문자열) 컨텍스트-only 조각이
    스푸리어스 키로 샜다. host_fn은 컨텍스트+빈줄뿐, 실변경은 real_fn에만 → host_fn 미방출.
    """
    from workflow.delta_update import extract_function_diffs

    diff = "\n".join([
        "Index: mod.c",
        "@@ -1,4 +1,7 @@ void host_fn(void)",
        "     ctx_a();",
        "",              # 0-length 빈 줄(이중 개행) — 실변경 아님
        "     ctx_b();",
        "+void real_fn(void)",
        "+{",
        "+    work();",
        "+}",
        "",
    ])
    out = extract_function_diffs(diff)
    assert "real_fn" in out
    assert "work()" in out["real_fn"]
    assert "host_fn" not in out  # 컨텍스트+빈줄만 → 미방출(빈문자열 오판정 회귀)


# ── extract_file_diffs (#3 파일레벨 원문 폴백) ──────────────────────────────────────
def test_extract_file_diffs_basic_and_key_normalization():
    """파일별 diff 블록 분할 + 정규화 상대경로 키(역슬래시→슬래시·소문자)."""
    from workflow.delta_update import extract_file_diffs
    diff = "\n".join([
        "Index: Sources\\APP\\Foo.c",
        "===================================================================",
        "--- Sources/APP/Foo.c\t(revision 100)",
        "+++ Sources/APP/Foo.c\t(revision 150)",
        "@@ -1,1 +1,1 @@ void f(void)",
        "-    a = 1;",
        "+    a = 2;",
        "Index: Lib/Bar.h",
        "===================================================================",
        "--- Lib/Bar.h\t(revision 100)",
        "+++ Lib/Bar.h\t(revision 150)",
        "@@ -1,1 +1,1 @@",
        "-#define X 1",
        "+#define X 2",
        "",
    ])
    out = extract_file_diffs(diff)
    assert "sources/app/foo.c" in out
    assert "lib/bar.h" in out
    assert "a = 2" in out["sources/app/foo.c"]
    assert "#define X 2" in out["lib/bar.h"]


def test_extract_file_diffs_per_file_line_cap():
    """파일당 라인 캡 초과 시 절단 + '…줄 생략' 마커(프론트 파서 호환)."""
    from workflow.delta_update import extract_file_diffs
    body = "\n".join(f"+    x{i} = {i};" for i in range(300))
    diff = "Index: src/big.c\n@@ -1,1 +1,300 @@ big(void)\n" + body + "\n"
    out = extract_file_diffs(diff, max_lines_per_file=20)
    assert "생략" in out["src/big.c"]
    assert len(out["src/big.c"].splitlines()) <= 22


def test_extract_file_diffs_total_cap_omits():
    """전체 char 캡 초과 시 이후 파일 생략(stats.omitted)."""
    from workflow.delta_update import extract_file_diffs
    blocks = [f"Index: src/f{n}.c\n@@ -1,1 +1,1 @@ f{n}(void)\n-    a = {n};\n+    a = {n + 1};" for n in range(5)]
    st: dict = {}
    out = extract_file_diffs("\n".join(blocks), max_total_chars=120, stats=st)
    assert len(out) < 5
    assert st.get("omitted", 0) >= 1


def test_extract_file_diffs_empty_and_no_index():
    """빈/Index 없는 diff는 빈 맵."""
    from workflow.delta_update import extract_file_diffs
    assert extract_file_diffs("") == {}
    assert extract_file_diffs("@@ -1,1 +1,1 @@ f(void)\n-a\n+b") == {}


def test_is_noop_function_diff():
    """포맷/이동만(의미 변경 없음) 판정 — 프론트 noSemanticChange 동형(순서 보존·trim)."""
    from workflow.delta_update import is_noop_function_diff
    assert is_noop_function_diff("@@ -1,2 +9,2 @@ f(void)\n-    a();\n-    b();\n+    a();\n+    b();") is True   # 블록 이동
    assert is_noop_function_diff("@@ -1,1 +1,1 @@ f(void)\n-    x = 1;\n+  x = 1;") is True                     # 재들여쓰기
    assert is_noop_function_diff("@@ -1,1 +1,1 @@ f(void)\n-    return a;\n+    return a + 1;") is False        # 실 로직
    assert is_noop_function_diff("@@ -1,2 +1,2 @@ f(void)\n-    a = 1;\n-    b = a;\n+    b = a;\n+    a = 1;") is False  # 재정렬
    assert is_noop_function_diff("@@ -1,1 +1,1 @@ f(void)\n-    x = 1;\n+    x = 1;\n… (+40줄 생략)") is False    # truncated 보류
    assert is_noop_function_diff("@@ -1,1 +1,1 @@ f(void)\n     ctx();") is False                              # +/- 없음
    assert is_noop_function_diff("") is False
