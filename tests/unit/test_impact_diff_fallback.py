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
    from workflow import delta_update, impact_orchestrator as m

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
