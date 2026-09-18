"""window_change_candidates — 파일 귀속 불가 규칙(RCMA류)의 구간 변경 파일 증거.

정직성 계약: 정렬은 관련 '가능성' 휴리스틱이며 후보 제외에는 쓰지 않는다(decl_touched=0인
파일도 목록에 남는다). 동일 스냅샷은 '변경 0'이 아니라 identical_snapshot으로 구분한다.
"""
from __future__ import annotations

from pathlib import Path

from backend.services.window_change_candidates import collect_window_changes


def _snap(root: Path, files: dict) -> Path:
    src = root / "source"
    for rel, text in files.items():
        p = src / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (src / ".source_complete").write_text("scm=svn\nrevision=1\n", encoding="utf-8")
    return root


def test_changed_files_sorted_by_declaration_relevance(tmp_path):
    a = _snap(tmp_path / "a", {
        "APP/decl.c": "int g_shared;\nvoid f(void) { }\n",
        "APP/body.c": "void b(void) { int x = 1; }\n",
        "APP/hdr.h": "extern int g_a;\n",
        "APP/same.c": "void s(void) { }\n",
    })
    b = _snap(tmp_path / "b", {
        # 최상위 선언 2줄 변경 → decl_touched 최대
        "APP/decl.c": "int g_shared_renamed;\nlong g_extra;\nvoid f(void) { }\n",
        "APP/body.c": "void b(void) { int x = 2; }\n",          # 본문만
        "APP/hdr.h": "extern int g_a;\ntypedef int mytype_t;\n",  # 헤더 + typedef
        "APP/same.c": "void s(void) { }\n",                       # 무변경
    })
    out = collect_window_changes(from_build_root=a, to_build_root=b)
    assert out["available"] is True
    paths = [f["path"] for f in out["changed_files"]]
    assert "APP/same.c" not in paths                     # 무변경은 제외
    assert paths[0] == "APP/decl.c"                      # 선언 변경 최다가 먼저
    assert out["totals"] == {"changed": 3, "headers": 1,
                             "decl_touched_files": 2, "typedef_touched_files": 1}
    hdr = next(f for f in out["changed_files"] if f["path"] == "APP/hdr.h")
    assert hdr["is_header"] is True and hdr["typedef_touched"] == 1
    # 인과 판정이 아님을 서버가 고정 주입한다.
    assert out["attribution"] == "observational"
    assert "인과" in out["note"]


def test_declaration_zero_files_are_kept_not_filtered(tmp_path):
    """decl_touched=0이어도 후보에서 빼지 않는다 — 휴리스틱을 판정으로 승격 금지.

    함수 본문(들여쓰기된 지역 변수)만 바뀐 파일 — 최상위 선언은 그대로다.
    """
    a = _snap(tmp_path / "a", {"APP/only_body.c": "void f(void)\n{\n    int x = 1;\n}\n"})
    b = _snap(tmp_path / "b", {"APP/only_body.c": "void f(void)\n{\n    int x = 2;\n}\n"})
    out = collect_window_changes(from_build_root=a, to_build_root=b)
    assert [f["path"] for f in out["changed_files"]] == ["APP/only_body.c"]
    # 지역 변수는 외부 링키지와 무관 — `^\s*` 정규식이던 시절엔 이게 2로 잡혔다(오검출).
    assert out["changed_files"][0]["decl_touched"] == 0
    assert out["totals"]["decl_touched_files"] == 0


def test_static_declarations_not_counted(tmp_path):
    """static은 외부 링키지가 없다 — 모듈 간 규칙 관련성 휴리스틱에서 제외."""
    a = _snap(tmp_path / "a", {"APP/s.c": "static int local_v;\n"})
    b = _snap(tmp_path / "b", {"APP/s.c": "static int local_v2;\n"})
    out = collect_window_changes(from_build_root=a, to_build_root=b)
    assert out["changed_files"][0]["decl_touched"] == 0


def test_added_and_deleted_files_classified(tmp_path):
    a = _snap(tmp_path / "a", {"APP/gone.c": "int g_gone;\n"})
    b = _snap(tmp_path / "b", {"APP/new.c": "int g_new;\n"})
    out = collect_window_changes(from_build_root=a, to_build_root=b)
    kinds = {f["path"]: f["change_kind"] for f in out["changed_files"]}
    assert kinds == {"APP/gone.c": "deleted", "APP/new.c": "added"}


def test_identical_snapshot_and_missing_source(tmp_path):
    a = _snap(tmp_path / "a", {"APP/x.c": "int g_x;\n"})
    b = _snap(tmp_path / "b", {"APP/x.c": "int g_x;\n"})
    out = collect_window_changes(from_build_root=a, to_build_root=b)
    assert out["available"] is False and out["reason"] == "identical_snapshot"
    missing = collect_window_changes(from_build_root=a, to_build_root=tmp_path / "nope")
    assert missing["available"] is False and missing["reason"] == "snapshot_missing"


def test_cap_and_omitted(tmp_path):
    a = _snap(tmp_path / "a", {f"APP/f{i}.c": f"int g_{i};\n" for i in range(8)})
    b = _snap(tmp_path / "b", {f"APP/f{i}.c": f"int g_{i}_x;\n" for i in range(8)})
    out = collect_window_changes(from_build_root=a, to_build_root=b, max_files=3)
    assert len(out["changed_files"]) == 3
    assert out["omitted"] == 5 and out["totals"]["changed"] == 8  # 총계는 절단 전 값


def test_endpoint_honest_failures(tmp_path, monkeypatch):
    from backend.routers import summary_insight as si

    monkeypatch.setattr("backend.services.build_inventory.list_cached_builds_meta", lambda **k: [])
    r = si.summary_rule_window_changes({"job_url": "http://j/", "rule": "Rule-8.6",
                                        "from_build": 1, "to_build": 2})
    assert r["available"] is False and r["reason"] == "build_not_cached"
    r2 = si.summary_rule_window_changes({"job_url": "http://j/", "rule": "Rule-8.6"})
    assert r2["available"] is False and r2["reason"] == "params_required"
