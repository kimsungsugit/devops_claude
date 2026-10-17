# -*- coding: utf-8 -*-
"""(R97) 프로젝트 맵 — 저장소의 프로젝트 고유 자료를 **그 프로젝트의 생성에만** 쓴다.

## 왜 (실측 2026-10-17)

저장소 `docs/component_map.json` · `docs/uds_function_swcom_override.json` 은 HDPDM01(PDS64) 자료인데 모든 프로젝트에 파일 ·
함수 이름으로 걸렸다. KJPDS02_PV 를 만들면 PV 소스 178 파일 중 110 이 HD 맵에 이름으로 맞고 35 가 HD 의 verify=X 를 받았으며
(그 파일의 함수 중 PV SwUDS 가 설계한 25 개가 문서 범위 밖), HD override 가 PV 함수 223 개에 Related · ASIL 을 줬다.

## 이 파일이 묶는 것

- 판정 행렬: 루트 ⊆ 매니페스트 루트 · SCM id 우선 · 섞인 루트 · 두 매니페스트(모호) · 옛 루트 파일 무시 · 형식 오류 · 빈 루트 ·
  경로 정규화(레지스트리와 같은 함수).
- 지문: 읽은 바이트가 바뀌면 바뀐다(소스 단계 캐시 키 · 서명에 든다).
- 소스 단계 끝까지: 맵이 걸린 루트에서만 SwCom 번호 · override 값이 바뀐다.
- SDS 구조 표 판독기(합성 docx): 세로 병합 · 한 칸 여러 파일 · 소스에 없는 표 파일 · 표에 없는 소스 파일 · 충돌.
- 설정 엔드포인트: 400 · 409 · overwrite(.prev) · 봉인.
- 실 자료(없으면 skip): HD 맵은 PDS64 루트에만 걸리고 PV 루트엔 안 걸린다 · PV 구조 표는 소스 101 파일을 적는다.
"""
from __future__ import annotations

import json
import os
import re
import zipfile
from pathlib import Path

import pytest

import report_gen.project_maps as pmod
from report_gen.project_maps import (
    describe_for_report,
    list_projects,
    resolve_project_maps,
    roots_key,
    write_project_map,
)
from report_gen.source_roots import normalize_root_key

REPO = Path(__file__).resolve().parents[2]

CM = [
    {"structure": "S", "file": "main.c", "component": "Main Comp (SwCom_07)", "verify": "O"},
    {"structure": "L", "file": "lin.c", "component": "LIN", "verify": "X"},
]
OV = {"main": {"swcom": 7, "related": "SwFn_77", "asil": "B"}}


def _project(base: Path, key: str, *, roots=(), scm_id: str = "", project: str = "", cm=None, ov=None,
             manifest: bool = True) -> Path:
    d = base / key
    d.mkdir(parents=True, exist_ok=True)
    maps = {}
    for kind, data, fname in (("component_map", cm, "component_map.json"),
                              ("override", ov, "uds_function_swcom_override.json")):
        if data is None:
            continue
        raw = data if isinstance(data, (bytes, str)) else json.dumps(data, ensure_ascii=False)
        (d / fname).write_bytes(raw.encode("utf-8") if isinstance(raw, str) else raw)
        maps[kind] = {"file": fname, "origin": f"test {kind}"}
    if manifest:
        (d / "project.json").write_text(json.dumps({
            "schema": 1, "scm_id": scm_id, "project": project or key.upper(),
            "source_roots": [str(r) for r in roots], "maps": maps}), encoding="utf-8")
    return d


@pytest.fixture()
def maps_dir(tmp_path, monkeypatch):
    base = tmp_path / "project_maps"
    base.mkdir()
    monkeypatch.setattr(pmod, "PROJECT_MAPS_DIR", base)
    return base


# ── 판정 행렬 ───────────────────────────────────────────────────────────────
class TestResolution:
    def test_roots_subset_applies_both_maps(self, maps_dir, tmp_path):
        a, b = tmp_path / "A", tmp_path / "B"
        _project(maps_dir, "hd", roots=[a, b], scm_id="hd", cm=CM, ov=OV)
        pm = resolve_project_maps(str(a))           # 한 루트만 줘도(⊆) 그 프로젝트
        assert pm.component_map.status == "applied" and pm.component_map.data == CM
        assert pm.override.status == "applied" and pm.override.data == OV
        assert pm.component_map.project == "HD"
        both = resolve_project_maps(f"{a},{b}")
        assert both.fingerprint == pm.fingerprint

    def test_scm_id_settles_an_ambiguous_root_and_is_case_insensitive(self, maps_dir, tmp_path):
        """루트가 두 매니페스트에 다 들면 루트로는 모호 — 항목을 아는 호출자의 id 가 고른다(대소문자 무시). 루트 없이 id 만 줘도 고른다."""
        a = tmp_path / "A"
        _project(maps_dir, "hd", roots=[a], scm_id="hdpdm01", cm=CM, ov=OV)
        _project(maps_dir, "other", roots=[a, tmp_path / "B"], scm_id="other", cm=CM)
        assert resolve_project_maps(str(a)).component_map.status == "ambiguous"
        pm = resolve_project_maps(str(a), scm_id="HDPDM01")
        assert pm.component_map.applied and pm.override.applied and pm.component_map.project == "HD"
        assert resolve_project_maps("", scm_id="hdpdm01").override.applied

    def test_id_with_stale_manifest_roots_fails_closed_exactly_like_the_roots_path(self, maps_dir, tmp_path):
        """(리뷰2 W1) 관리자가 레지스트리 루트만 바꿨다(매니페스트는 옛 루트). 허브(루트)는 `not_this_project` 인데 게이트 · 측정 ·
        영향 분석 재생성(id)이 `applied` 면 게이트가 잰 문서 ≠ 허브가 만든 문서다. 두 경로가 **같은 상태 · 같은 데이터 · 같은 지문**
        이어야 하고, id 경로는 `roots_moved` 문제와 루트 재등록 안내(관리자)를 싣는다."""
        old, new = tmp_path / "old", tmp_path / "new"
        _project(maps_dir, "hd", roots=[old], scm_id="hdpdm01", cm=CM, ov=OV)
        _project(maps_dir, "pv", roots=[tmp_path / "PV"], scm_id="pv", cm=CM)
        by_roots = resolve_project_maps(str(new))
        by_id = resolve_project_maps(str(new), scm_id="hdpdm01")
        for kind in ("component_map", "override"):
            r, i = getattr(by_roots, kind), getattr(by_id, kind)
            assert (r.status, r.data, r.project, r.sha1) == (i.status, i.data, i.project, i.sha1), kind
            assert i.status == "not_this_project" and i.data is None
            assert any(p.startswith("roots_moved") for p in i.problems), i.problems
            assert "루트를 다시 등록" in i.reason and "관리자" in i.reason
            assert pmod.needs_attention(i.describe()) and pmod.needs_attention(r.describe())
        assert by_roots.fingerprint == by_id.fingerprint, "두 경로가 다른 캐시를 쓴다"

    def test_id_and_roots_that_point_at_different_projects_apply_nothing(self, maps_dir, tmp_path):
        """id 는 HD 인데 루트는 PV 매니페스트에 든다 — 루트만 보면 PV 맵이지만 id 가 아니라고 한다. 고르지 않는다(fail-closed)."""
        _project(maps_dir, "hd", roots=[tmp_path / "HD"], scm_id="hdpdm01", cm=CM, ov=OV)
        _project(maps_dir, "pv", roots=[tmp_path / "PV"], scm_id="pv", cm=CM)
        assert resolve_project_maps(str(tmp_path / "PV")).component_map.applied
        pm = resolve_project_maps(str(tmp_path / "PV"), scm_id="hdpdm01")
        assert pm.component_map.status == "not_this_project" and pm.component_map.data is None
        assert any(p.startswith("roots_moved") for p in pm.component_map.problems)

    def test_the_reviewer_stale_registry_scenario_on_the_real_maps(self, tmp_path):
        """리뷰 재현(`r2_idroots.py`) 그대로 — 실 맵 폴더 사본, 레지스트리 루트만 `E:/Moved/…` 로 바뀐 HD."""
        import shutil

        base = tmp_path / "project_maps"
        shutil.copytree(REPO / "docs" / "project_maps", base)
        moved = "E:/Moved/PDS64_RD,E:/Moved/PDS64_FBL"
        by_roots = resolve_project_maps(moved, base_dir=base)
        by_id = resolve_project_maps(moved, scm_id="hdpdm01", base_dir=base)
        assert by_roots.fingerprint == by_id.fingerprint
        assert by_id.component_map.status == by_roots.component_map.status == "not_this_project"
        assert by_id.override.data is None and pmod.needs_attention(by_id.override.describe())

    def test_unknown_scm_id_is_not_rescued_by_roots(self, maps_dir, tmp_path):
        """id 를 줬는데 그 id 의 매니페스트가 없으면 루트로 되돌아가지 않는다(fail-closed)."""
        _project(maps_dir, "hd", roots=[tmp_path / "A"], scm_id="hdpdm01", cm=CM, ov=OV)
        pm = resolve_project_maps(str(tmp_path / "A"), scm_id="kjpds02_pv")
        assert pm.component_map.status == "not_this_project" and pm.component_map.data is None
        assert pm.override.status == "not_this_project"
        assert pm.component_map.others == ("hd",)

    def test_mixed_roots_are_not_this_project(self, maps_dir, tmp_path):
        """한 루트만 맞고 다른 루트는 어느 매니페스트에도 없다 — 이름으로 걸던 옛 동작이 남의 맵을 걸던 바로 그 자리."""
        _project(maps_dir, "hd", roots=[tmp_path / "A"], cm=CM, ov=OV)
        pm = resolve_project_maps(f"{tmp_path / 'A'},{tmp_path / 'PV'}")
        assert not pm.component_map.applied and not pm.override.applied
        assert pm.component_map.status == "not_this_project"
        assert "hd" in pm.component_map.reason

    def test_two_manifests_matching_is_ambiguous(self, maps_dir, tmp_path):
        a = tmp_path / "A"
        _project(maps_dir, "p1", roots=[a], cm=CM)
        _project(maps_dir, "p2", roots=[a, tmp_path / "B"], ov=OV)
        pm = resolve_project_maps(str(a))
        assert pm.component_map.status == "ambiguous" and pm.override.status == "ambiguous"
        assert pm.component_map.others == ("p1", "p2")
        assert pm.component_map.data is None

    def test_project_without_that_kind_is_none(self, maps_dir, tmp_path):
        """PV 는 override 를 등록하지 않는다 — 남의(HD) override 가 있어도 `none`(정보)이지 `not_this_project` 가 아니다."""
        _project(maps_dir, "hd", roots=[tmp_path / "A"], cm=CM, ov=OV)
        _project(maps_dir, "pv", roots=[tmp_path / "PV"], cm=CM)
        pm = resolve_project_maps(str(tmp_path / "PV"))
        assert pm.component_map.applied and pm.component_map.project == "PV"
        assert pm.override.status == "none" and pm.override.project == "PV"

    def test_old_root_files_are_never_read(self, maps_dir, tmp_path):
        """옛 위치(맵 폴더 바로 아래 · 저장소 docs/)의 파일은 매니페스트가 없으면 어떤 경우에도 안 쓴다."""
        (maps_dir / "component_map.json").write_text(json.dumps(CM), encoding="utf-8")
        (maps_dir / "uds_function_swcom_override.json").write_text(json.dumps(OV), encoding="utf-8")
        pm = resolve_project_maps(str(tmp_path / "A"))
        assert pm.component_map.status == "none" and pm.override.status == "none"
        assert pm.component_map.data is None and pm.override.data is None
        assert not (REPO / "docs" / "component_map.json").exists(), "옛 전역 맵이 저장소 docs/ 에 되살아났다"
        assert not (REPO / "docs" / "uds_function_swcom_override.json").exists()

    def test_no_code_reads_the_old_global_paths(self):
        """코드(주석 제외)가 `docs/component_map.json` · `docs/uds_function_swcom_override.json` 경로를 짓지 않는다."""
        pat = re.compile(r'''["']docs["']\s*\)?\s*/\s*["'](component_map|uds_function_swcom_override)\.json["']'''
                         r'''|["']docs/(component_map|uds_function_swcom_override)\.json["']''')
        hits = []
        for sub in ("backend", "generators", "report_gen", "workflow"):
            for py in (REPO / sub).rglob("*.py"):
                for n, ln in enumerate(py.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    code = ln.split("#", 1)[0]
                    if pat.search(code):
                        hits.append(f"{py.relative_to(REPO)}:{n}")
        assert hits == [], hits

    def test_invalid_maps_are_not_applied(self, maps_dir, tmp_path):
        a = tmp_path / "A"
        _project(maps_dir, "p", roots=[a], cm={"main.c": "dict, not list"}, ov="{not json")
        pm = resolve_project_maps(str(a))
        assert pm.component_map.status == "invalid" and pm.component_map.data is None
        assert pm.override.status == "invalid" and pm.override.data is None
        assert pm.component_map.sha1, "읽은 바이트의 지문은 남겨야 캐시가 고친 뒤를 안다"

    def test_missing_map_file_is_invalid(self, maps_dir, tmp_path):
        d = _project(maps_dir, "p", roots=[tmp_path / "A"], cm=CM)
        (d / "component_map.json").unlink()
        assert resolve_project_maps(str(tmp_path / "A")).component_map.status == "invalid"

    def test_map_file_outside_project_folder_is_invalid(self, maps_dir, tmp_path):
        d = _project(maps_dir, "p", roots=[tmp_path / "A"], cm=CM)
        (tmp_path / "evil.json").write_text(json.dumps(CM), encoding="utf-8")
        man = json.loads((d / "project.json").read_text(encoding="utf-8"))
        man["maps"]["component_map"]["file"] = "../../evil.json"
        (d / "project.json").write_text(json.dumps(man), encoding="utf-8")
        assert resolve_project_maps(str(tmp_path / "A")).component_map.status == "invalid"

    def test_empty_roots_and_no_id_is_no_roots(self, maps_dir, tmp_path):
        _project(maps_dir, "p", roots=[tmp_path / "A"], cm=CM, ov=OV)
        pm = resolve_project_maps("")
        assert pm.component_map.status == "no_roots" and pm.override.status == "no_roots"
        assert resolve_project_maps(" , ;").component_map.status == "no_roots"

    def test_unreadable_manifest_is_reported_not_raised(self, maps_dir, tmp_path):
        """(리뷰 W3) 읽지 못한 매니페스트가 있으면 '맵 없음' 을 말할 수 없다 — `invalid`(경고)로, 예외 없이."""
        bad = maps_dir / "broken"
        bad.mkdir()
        (bad / "project.json").write_text("{oops", encoding="utf-8")
        pm = resolve_project_maps(str(tmp_path / "A"))
        assert pm.component_map.status == "invalid" and pm.override.status == "invalid"
        assert "broken" in pm.component_map.reason and pm.component_map.problems

    @pytest.mark.parametrize("damage", ["truncated", "schema2", "no_manifest"])
    def test_damaged_hd_manifest_is_a_warning_not_a_quiet_none(self, tmp_path, monkeypatch, damage):
        """(리뷰 W3) 실 HD 맵 폴더 사본에서 매니페스트를 망가뜨린다(잘림 · schema≠1 · 없음) — HD 루트의 override 가 `none`(정보)
        이면 ASIL override 가 조용히 사라진다. `invalid` + 공시 warning + UDS 생성 항목이어야 한다."""
        import shutil

        from backend.helpers.uds import _note_project_maps
        from report_gen.gen_issues import IssueCollector
        from report_gen.generation_disclosures import build_disclosures

        base = tmp_path / "project_maps"
        shutil.copytree(REPO / "docs" / "project_maps", base)
        mf = base / "hdpdm01" / "project.json"
        if damage == "truncated":
            mf.write_bytes(mf.read_bytes()[:-5])
        elif damage == "schema2":
            mf.write_text(json.dumps({"schema": 2, "scm_id": "hdpdm01", "source_roots": ["D:/Project/Ados/PDS64_RD"]}),
                          encoding="utf-8")
        else:
            mf.unlink()
        monkeypatch.setattr(pmod, "PROJECT_MAPS_DIR", base)
        pm = resolve_project_maps(_HD_ROOTS)
        for use in (pm.component_map, pm.override):
            assert use.status == "invalid" and use.data is None, (use.kind, use.status, use.reason)
            assert any("hdpdm01" in p for p in use.problems)
        items = {i["key"]: i for i in build_disclosures("suts", {"project_maps": pm.describe()})}
        assert items["project_maps_override"]["tone"] == "warning"
        c = IssueCollector()
        _note_project_maps(c, {"project_maps": pm.describe()})
        assert {i["code"] for i in c.as_list()} == {"project_map_not_applied"} and len(c.as_list()) == 2

    def test_applied_with_a_broken_sibling_manifest_still_warns(self, maps_dir, tmp_path):
        """맞는 매니페스트가 있어도 옆 매니페스트를 못 읽으면 그게 같은 루트를 주장했을 수 있다 — 적용은 하되 경고로 말한다."""
        from report_gen.generation_disclosures import build_disclosures

        _project(maps_dir, "p", roots=[tmp_path / "A"], cm=CM)
        _project(maps_dir, "stray", cm=CM, manifest=False)
        pm = resolve_project_maps(str(tmp_path / "A"))
        assert pm.component_map.applied and pm.component_map.problems
        items = {i["key"]: i for i in build_disclosures("sits", {"project_maps": pm.describe()})}
        assert items["project_maps_component_map"]["tone"] == "warning" and "stray" in items["project_maps_component_map"]["note"]

    def test_an_empty_folder_is_not_a_problem_on_the_real_maps(self, tmp_path):
        """(리뷰2 I-a) 매니페스트도 맵도 없는 **빈 폴더**(중단된 쓰기 · 손으로 만든 자리)는 문제가 아니다 — 문제로 세면 그 폴더 하나가
        HD · PV 맵 전부를 경고로, PV override(`none`, 정보)를 `invalid`(경고)로 바꾼다. 맵 파일이 든 폴더는 여전히 문제다."""
        import shutil

        base = tmp_path / "project_maps"
        shutil.copytree(REPO / "docs" / "project_maps", base)
        clean = {r: resolve_project_maps(r, base_dir=base) for r in (_HD_ROOTS, _PV_ROOTS)}
        (base / "stray_empty").mkdir()
        (base / "stray_empty" / "notes.txt").write_text("not a map", encoding="utf-8")
        for r, before in clean.items():
            now = resolve_project_maps(r, base_dir=base)
            assert now.fingerprint == before.fingerprint, r
            for use in (now.component_map, now.override):
                assert not use.problems and not pmod.needs_attention(use.describe()), use.describe()
        assert resolve_project_maps(_PV_ROOTS, base_dir=base).override.status == "none"
        (base / "stray_empty" / "component_map.json").write_text("[]", encoding="utf-8")
        pv = resolve_project_maps(_PV_ROOTS, base_dir=base)
        assert pv.override.status == "invalid" and any("stray_empty" in p for p in pv.override.problems), \
            "맵 파일이 든 매니페스트 없는 폴더는 여전히 문제다"

    def test_trailing_separator_is_the_same_root(self, maps_dir, tmp_path):
        a = tmp_path / "A"
        _project(maps_dir, "p", roots=[str(a) + os.sep], cm=CM)
        assert resolve_project_maps(str(a)).component_map.applied

    @pytest.mark.skipif(os.name != "nt", reason="normcase 는 Windows 에서만 대소문자 · 구분자를 접는다(레지스트리와 같은 함수)")
    def test_windows_case_and_separator_equivalence(self, maps_dir):
        _project(maps_dir, "p", roots=["D:/A"], cm=CM)
        assert normalize_root_key("D:/A") == normalize_root_key("d:\\a\\")
        assert resolve_project_maps("d:\\a\\").component_map.applied

    def test_registry_delegates_to_the_same_normalisation(self):
        from backend.services.scm_registry import _normalize_path_key

        for s in ("D:/Project/Ados/PDS64_RD", "d:\\project\\ados\\pds64_rd\\", ' "C:\\x\\y" ', "", "a\x00b", "rel/./x/../y"):
            assert _normalize_path_key(s) == normalize_root_key(s), s


# ── 지문 ────────────────────────────────────────────────────────────────────
class TestFingerprint:
    def test_changes_with_the_bytes_read(self, maps_dir, tmp_path):
        a = tmp_path / "A"
        d = _project(maps_dir, "p", roots=[a], cm=CM, ov=OV)
        fp1 = resolve_project_maps(str(a)).fingerprint
        (d / "component_map.json").write_text(json.dumps(CM, indent=1), encoding="utf-8")   # 값은 같고 바이트만 다르다
        fp2 = resolve_project_maps(str(a)).fingerprint
        assert fp1 != fp2
        assert resolve_project_maps(str(a)).fingerprint == fp2, "같은 바이트면 같은 지문"
        (d / "uds_function_swcom_override.json").unlink()
        assert resolve_project_maps(str(a)).fingerprint != fp2

    def test_names_status_project_and_sha1_per_kind(self, maps_dir, tmp_path):
        a = tmp_path / "A"
        _project(maps_dir, "p", roots=[a], cm=CM)
        fp = resolve_project_maps(str(a)).fingerprint
        assert fp.startswith("component_map=applied:P:") and "|override=none:P:" in fp

    def test_source_sections_cache_is_keyed_by_the_map(self, maps_dir, tmp_path, monkeypatch):
        """맵을 고치면 소스 단계 캐시(메모리 · 디스크)가 다시 판다 — 지문이 키 · 서명에 든다. 같은 맵이면 한 번만 판다."""
        from backend.helpers import uds as uds_mod

        uds_mod.clear_source_sections_cache()
        monkeypatch.setattr(uds_mod, "_source_sections_disk_cache_path", lambda *a, **k: tmp_path / "disk.json")
        calls = []

        def _fake(root, **kw):
            calls.append(kw.get("scm_id"))
            return {"function_details": {}}

        monkeypatch.setattr(uds_mod, "generate_uds_source_sections", _fake)
        src = tmp_path / "src"
        src.mkdir()
        (src / "a.c").write_bytes(b"int a;\n")
        d = _project(maps_dir, "p", roots=[src], scm_id="p", cm=CM)
        try:
            uds_mod._get_source_sections_cached(str(src))
            uds_mod._get_source_sections_cached(str(src))
            assert len(calls) == 1, "같은 맵이면 캐시가 맞아야 한다"
            uds_mod._get_source_sections_cached(str(src), scm_id="P")
            assert len(calls) == 1, "id 로 골라도 같은 맵이면 같은 캐시"
            (d / "component_map.json").write_text(json.dumps(CM[:1]), encoding="utf-8")
            uds_mod._get_source_sections_cached(str(src))
            assert len(calls) == 2, "맵을 고쳤는데 옛 맵의 결과를 돌려줬다"
            uds_mod.clear_source_sections_cache()          # 메모리를 비워도 디스크 서명이 옛 맵 결과를 거부해야 한다
            (d / "component_map.json").write_text(json.dumps(CM), encoding="utf-8")
            uds_mod._get_source_sections_cached(str(src))
            assert len(calls) == 3, "디스크 캐시가 맵 지문 없이 옛 결과를 돌려줬다"
            # cloudium(원격) 루트는 서명이 None 이라 메모리 TTL 캐시를 **키**만으로 판정한다 — 키에 지문이 없으면 옛 맵이 30분 남는다
            monkeypatch.setattr(uds_mod, "_source_root_signature", lambda *a, **k: None)
            uds_mod._get_source_sections_cached(str(src))
            assert len(calls) == 3, "서명이 없으면 같은 키의 메모리 항목을 TTL 로 쓴다(기존 cloudium 동작)"
            (d / "component_map.json").write_text(json.dumps(CM[:1]), encoding="utf-8")
            uds_mod._get_source_sections_cached(str(src))
            assert len(calls) == 4, "서명 없는 루트에서 맵을 고쳤는데 메모리 캐시가 옛 결과를 돌려줬다(키에 지문 없음)"
        finally:
            uds_mod.clear_source_sections_cache()

    def test_test_materials_key_and_signature_follow_the_map(self, maps_dir, tmp_path):
        """준비 게이트 측정 캐시도 같은 축 — 맵을 고치면 키 · 서명이 바뀌고, id 로 고르든 루트로 고르든 같은 맵이면 같은 키."""
        from backend.services import docgen_test_materials as tm

        src = tmp_path / "src"
        src.mkdir()
        (src / "a.c").write_bytes(b"int a;\n")
        d = _project(maps_dir, "p", roots=[src], scm_id="p", cm=CM)
        k1, s1 = tm._key(str(src)), tm.signature_for(str(src))
        assert s1 is not None and tm._key(str(src), scm_id="P") == k1
        (d / "component_map.json").write_text(json.dumps(CM[:1]), encoding="utf-8")
        assert tm._key(str(src)) != k1 and tm.signature_for(str(src)) != s1

    def test_report_marks_a_source_stage_that_differs(self, maps_dir, tmp_path):
        a = tmp_path / "A"
        _project(maps_dir, "p", roots=[a], cm=CM)
        pm = resolve_project_maps(str(a))
        same = describe_for_report(pm, pm.describe())
        assert same["component_map"]["source_stage"] == "same"
        stale = pm.describe()
        stale["component_map"]["sha1"] = "old"
        assert describe_for_report(pm, stale)["component_map"]["source_stage"] == "differs"
        assert describe_for_report(pm, None)["override"]["source_stage"] == "absent"


# ── 소스 단계 끝까지 ─────────────────────────────────────────────────────────
class TestSourceStage:
    @staticmethod
    def _tree(root: Path) -> Path:
        root.mkdir(parents=True)
        (root / "main.c").write_text("void helper(void);\nint main(void)\n{\n    helper();\n    return 0;\n}\n",
                                     encoding="utf-8")
        (root / "lin.c").write_text("void helper(void)\n{\n}\n", encoding="utf-8")
        return root

    def test_map_reaches_only_its_own_roots(self, maps_dir, tmp_path):
        from report_gen.uds_generator import generate_uds_source_sections

        mine = self._tree(tmp_path / "mine")
        other = self._tree(tmp_path / "other")
        _project(maps_dir, "proj", roots=[mine], scm_id="proj", cm=CM, ov=OV)

        got = generate_uds_source_sections(str(mine))
        by = {d["name"]: (fid, d) for fid, d in got["function_details"].items()}
        assert by["main"][0].startswith("SwUFn_07"), "component_map 의 SwCom 번호가 안 걸렸다"
        assert (by["main"][1]["asil"], by["main"][1]["asil_source"]) == ("B", "override")
        assert by["main"][1]["related"] == "SwFn_77"
        assert got["project_maps"]["component_map"]["status"] == "applied"
        assert got["project_maps"]["override"]["project"] == "PROJ"

        not_mine = generate_uds_source_sections(str(other))
        by2 = {d["name"]: (fid, d) for fid, d in not_mine["function_details"].items()}
        assert not by2["main"][0].startswith("SwUFn_07"), "남의 프로젝트 맵이 이름으로 걸렸다"
        assert by2["main"][1]["asil"] == "TBD" and by2["main"][1]["asil_source"] != "override"
        assert not_mine["project_maps"]["component_map"]["status"] == "not_this_project"

        # (리뷰2 W1) id 를 줘도 루트가 매니페스트에 안 들면 맵을 쓰지 않는다 — 허브(루트 판정)와 같은 결론
        by_id = generate_uds_source_sections(str(other), scm_id="PROJ")
        assert by_id["project_maps"]["override"]["status"] == "not_this_project"
        assert any(p.startswith("roots_moved") for p in by_id["project_maps"]["override"]["problems"])

    def test_source_stage_path_key_rows_follow_the_os_path_rules(self, maps_dir, tmp_path):
        """(리뷰2 I-c) 소스 단계 두 루프도 `resolve_component_entry` 와 같은 경로 키 판정 — 대소문자만 다른 경로 키 행이 SwCom
        번호를 준다(Windows). 라벨 · 범위가 같은 맵에서 갈리지 않게."""
        from report_gen.uds_generator import generate_uds_source_sections

        mine = tmp_path / "mine"
        (mine / "APP" / "Gen").mkdir(parents=True)
        (mine / "APP" / "Gen" / "main.c").write_text("int main(void)\n{\n    return 0;\n}\n", encoding="utf-8")
        cm = [{"structure": "S", "file": "app/gen/MAIN.C", "component": "Main Comp (SwCom_07)", "verify": "O",
               "match": "path"}]
        _project(maps_dir, "proj", roots=[mine], scm_id="proj", cm=cm)
        got = generate_uds_source_sections(str(mine))
        fid = next(f for f, d in got["function_details"].items() if d["name"] == "main")
        insensitive = os.path.normcase("A") == os.path.normcase("a")
        assert fid.startswith("SwUFn_07") is insensitive, fid

    def test_both_source_stage_loops_share_the_path_key_rule(self):
        """(리뷰2 I-c) 위 행동 시험은 AST 경로 루프만 닿는다 — tree-sitter 가 놓친 함수의 폴백 루프는 작은 트리로 재현이 어렵다. 두 곳이
        같이 움직여야 한다는 규칙(코드 주석)을 구조로 지킨다: 옛 문자열 `endswith` 판정이 남아 있지 않고, 공유 판정을 두 번 쓴다."""
        src = (REPO / "report_gen" / "uds_generator.py").read_text(encoding="utf-8")
        assert "fp_norm.endswith(cm_key)" not in src
        assert src.count("component_path_key_matches(fp_norm, cm_key)") == 2

    def test_explicit_component_map_argument_wins(self, maps_dir, tmp_path):
        from report_gen.uds_generator import generate_uds_source_sections

        mine = self._tree(tmp_path / "mine")
        _project(maps_dir, "proj", roots=[mine], cm=CM)
        got = generate_uds_source_sections(str(mine), component_map={})
        assert got["project_maps"]["component_map"]["used"] == "argument"
        by = {d["name"]: fid for fid, d in got["function_details"].items()}
        assert not by["main"].startswith("SwUFn_07")

    def test_load_component_map_wrapper(self, maps_dir, tmp_path):
        from report_gen.requirements import _load_component_map

        _project(maps_dir, "proj", roots=[tmp_path / "A"], scm_id="proj", cm=CM)
        assert _load_component_map() == {}, "인자 없는 호출은 프로젝트를 모른다 — 전역 파일로 돌아가지 않는다"
        m = _load_component_map(str(tmp_path / "A"))
        assert m["lin.c"]["verify"] == "X" and m["main"]["component"] == "Main Comp(SwCom_07)"
        assert _load_component_map("", scm_id="PROJ")["main.c"]["verify"] == "O"
        assert _load_component_map(str(tmp_path / "B")) == {}


# ── 쓰기 ────────────────────────────────────────────────────────────────────
class TestWrite:
    def test_write_registers_and_refuses_silent_overwrite(self, maps_dir, tmp_path):
        out = write_project_map("component_map", CM, key="kj", project="KJ", scm_id="kj", source_roots=[str(tmp_path)],
                                origin="SwDS 구조 표 — 한글 출처")
        man = json.loads(Path(out["manifest"]).read_bytes().decode("utf-8"))
        assert man["maps"]["component_map"]["origin"] == "SwDS 구조 표 — 한글 출처"
        assert resolve_project_maps(str(tmp_path)).component_map.applied
        with pytest.raises(FileExistsError):
            write_project_map("component_map", CM[:1], key="kj", project="KJ")
        out2 = write_project_map("component_map", CM[:1], key="kj", project="KJ", overwrite=True)
        assert Path(out2["backup"]).is_file() and json.loads(Path(out2["backup"]).read_text(encoding="utf-8")) == CM
        assert json.loads(Path(out2["path"]).read_text(encoding="utf-8")) == CM[:1]
        assert Path(out2["path"]).read_bytes().count(b"\r\n") == 0, "LF 로 쓴다(.gitattributes eol=lf)"

    @pytest.mark.parametrize("key", ["../x", "a/b", "..", "", "a\\b"])
    def test_bad_keys_are_refused(self, maps_dir, key):
        with pytest.raises(ValueError):
            write_project_map("override", OV, key=key, project="X")
        assert not any(maps_dir.parent.glob("x*")), "키가 맵 폴더 밖으로 나갔다"

    def test_wrong_data_type_is_refused(self, maps_dir):
        with pytest.raises(ValueError):
            write_project_map("component_map", {"a": 1}, key="k", project="K")

    def test_roots_key_is_order_and_spelling_stable(self, tmp_path):
        a, b = str(tmp_path / "A"), str(tmp_path / "B")
        assert roots_key(f"{a},{b}") == roots_key(f"{b};{a}")
        assert roots_key(a).startswith("roots-") and roots_key(a) != roots_key(b)

    def test_list_projects_counts(self, maps_dir, tmp_path):
        _project(maps_dir, "hd", roots=[tmp_path / "A"], scm_id="hd", cm=CM, ov=OV)
        listed = list_projects()
        (p,) = listed["projects"]
        assert p["maps"]["component_map"]["verify_x"] == 1 and p["maps"]["override"]["with_asil"] == 1


# ── SDS 구조 표 판독기 (합성 docx) ──────────────────────────────────────────
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _tc(text: str = "", *, vmerge: str | None = None) -> str:
    pr = ""
    if vmerge is not None:
        pr = f'<w:tcPr><w:vMerge w:val="{vmerge}"/></w:tcPr>' if vmerge else "<w:tcPr><w:vMerge/></w:tcPr>"
    paras = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in (text.split("\n") if text else [""]))
    return f"<w:tc>{pr}{paras}</w:tc>"


def _docx(path: Path, rows: list) -> Path:
    head = "<w:tr>" + "".join(_tc(h) for h in ("Layer1", "Layer2", "Layer3", "Layer4", "Component Name")) + "</w:tr>"
    other = "<w:tbl><w:tr>" + _tc("Revision") + _tc("Date") + "</w:tr></w:tbl>"
    body = other + "<w:tbl>" + head + "".join("<w:tr>" + "".join(r) + "</w:tr>" for r in rows) + "</w:tbl>"
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{_W_NS}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", xml)
    return path


class TestStructureTable:
    def test_reads_rows_vmerge_multi_file_and_reports_gaps(self, tmp_path):
        from report_gen.project_setup import component_map_from_structure_table

        sds = _docx(tmp_path / "sds.docx", [
            [_tc("Root"), _tc("Lib"), _tc("Lib_it.h\nLib.c"), _tc(), _tc()],                       # 컴포넌트 빈 행
            [_tc(), _tc("Source"), _tc("APP", vmerge="restart"), _tc("a.c / a.h"), _tc("Alpha\n(SwCom_1)")],
            [_tc(), _tc(), _tc(vmerge=""), _tc("b.c"), _tc("Beta (SwCom_02)", vmerge="restart")],
            [_tc(), _tc(), _tc(vmerge=""), _tc("c.c"), _tc(vmerge="")],                              # 위 컴포넌트를 잇는다
            [_tc(), _tc(), _tc(vmerge=""), _tc("d.c\ne.c\nghost.c"), _tc("Delta (SwCom_04)")],
            [_tc(), _tc(), _tc("IF"), _tc("x.c"), _tc("One (SwCom_05)")],
            [_tc(), _tc(), _tc("IF"), _tc("x.c"), _tc("Two (SwCom_06)")],                             # 충돌
            [_tc(), _tc(), _tc("System"), _tc("SysDiag_PDS.c"), _tc("Diag (SwCom_12)")],              # 문서 오기 후보
        ])
        src = tmp_path / "src"
        for d in ("APP", "Lib", "IF", "SYSTEM", "FBL/Sources"):
            (src / d).mkdir(parents=True)
        for n in ("a.c", "b.c", "c.c", "d.c", "E.c"):
            (src / "APP" / n).write_text("int v;\n", encoding="utf-8")
        (src / "Lib" / "Lib.c").write_text("int v;\n", encoding="utf-8")
        (src / "IF" / "x.c").write_text("int v;\n", encoding="utf-8")
        (src / "SYSTEM" / "SysDiagCtrl_PDS.c").write_text("int v;\n", encoding="utf-8")
        (src / "FBL" / "Sources" / "a.c").write_text("int w;\n", encoding="utf-8")     # 같은 이름 — 다른 트리
        (src / "unlisted.c").write_text("int v;\n", encoding="utf-8")
        (src / ".svn").mkdir()
        (src / ".svn" / "skip.c").write_text("", encoding="utf-8")

        got = component_map_from_structure_table(str(sds), str(src))
        assert got["found"]
        rows = {r["file"]: r for r in got["rows"]}
        assert rows["Lib.c"]["component"] == "Lib" and rows["Lib.c"]["structure"] == "Lib"
        assert rows["b.c"]["component"] == "Beta(SwCom_02)" and rows["b.c"]["structure"] == "APP", "Layer3 병합 잇기"
        assert rows["c.c"]["component"] == "Beta(SwCom_02)", "컴포넌트 칸 병합 잇기"
        assert rows["d.c"]["component"] == "Delta(SwCom_04)"
        assert "E.c" in rows and "e.c" not in rows, "행의 file 은 소스 철자여야 조회가 맞는다"
        assert set(r["verify"] for r in got["rows"]) == {"O"}, "문서가 면제 근거를 주지 않는다 — X 를 만들지 않는다"
        assert "x.c" not in rows
        # (리뷰 W8a) 같은 이름 `a.c` — 표가 적은 구조(`APP`)의 사본만 경로 키 행, FBL 사본은 행 없음
        assert "a.c" not in rows, "이름만으로 행을 만들면 FBL 사본도 APP 라벨을 받는다"
        assert rows["src/APP/a.c"]["component"] == "Alpha(SwCom_01)" and rows["src/APP/a.c"]["match"] == "path"
        st = got["stats"]
        assert st["twins_path_keyed"] == {"a.c": ["src/APP/a.c"]}
        assert st["twins_left_unmapped"] == {"a.c": ["src/FBL/Sources/a.c"]}
        from report_gen.requirements import component_map_from_rows, resolve_component_entry
        m = component_map_from_rows(got["rows"])
        assert resolve_component_entry(str(src / "APP" / "a.c"), m)["component"] == "Alpha(SwCom_01)"
        assert resolve_component_entry(str(src / "FBL" / "Sources" / "a.c"), m) == {}, "경로 키 행이 이름 · stem 으로 샜다"
        assert st["conflicting_files"] == {"x.c": ["One(SwCom_05)", "Two(SwCom_06)"]}
        # (리뷰 W8b) 문서 결함 후보는 이름으로, 비슷한 소스 이름은 힌트로만(행 없음)
        assert sorted(st["table_files_not_in_source"]) == ["Lib_it.h", "SysDiag_PDS.c", "a.h", "ghost.c"]
        assert st["table_files_not_in_source_hints"] == {"SysDiag_PDS.c": ["SysDiagCtrl_PDS.c"]}
        assert "SysDiagCtrl_PDS.c" not in rows, "비슷한 이름을 자동으로 대응시켰다"
        assert st["source_files_not_listed"] == 2      # unlisted.c · SysDiagCtrl_PDS.c
        assert st["component_from_structure"] == 1
        assert st["source_files"] == 10, ".svn 은 세지 않는다"

    @pytest.mark.parametrize("dirs", [("one", "two"), ("one/APP", "two/APP")], ids=["neither_copy", "both_copies"])
    def test_a_twin_the_table_does_not_place_gets_no_row(self, tmp_path, dirs):
        """두 사본 다 구조 이름과 안 맞거나(**또는 둘 다 맞으면** — 리뷰2 R1) 어느 쪽인지 표가 말하지 않는다 — 행 없이
        `twins_unresolved`. 둘 다 맞는 경우에 경로 키 행을 둘 다 만들면 표가 한 파일에 준 컴포넌트를 두 사본이 다 받는다."""
        from report_gen.project_setup import component_map_from_structure_table

        sds = _docx(tmp_path / "sds.docx", [[_tc(), _tc(), _tc("APP"), _tc("t.c"), _tc("T (SwCom_09)")]])
        src = tmp_path / "src"
        for d in dirs:
            (src / d).mkdir(parents=True)
            (src / d / "t.c").write_text("int v;\n", encoding="utf-8")
        got = component_map_from_structure_table(str(sds), str(src))
        assert got["rows"] == [] and set(got["stats"]["twins_unresolved"]) == {"t.c"}
        assert not got["stats"]["twins_path_keyed"]

    def test_path_keys_follow_the_os_path_rules(self, tmp_path):
        """(리뷰2 I-c) 경로 키 행은 OS 경로 규칙으로 맞춘다 — Windows 는 대소문자 무시. 레지스트리 루트 철자만 다른 경로
        (`ne1aw_porting` vs `NE1AW_PORTING`)에서 맵은 `applied` 인데 PV 의 경로 키 행만 조용히 놓쳤다. 조회
        (`resolve_component_entry`)와 소스 단계 라벨이 같은 판정이어야 한다."""
        from report_gen.requirements import component_map_from_rows, component_path_key_matches, resolve_component_entry

        insensitive = os.path.normcase("A") == os.path.normcase("a")
        rows = [{"structure": "APP", "file": "NE1AW_PORTING/Generated_Code/EEPROM.c", "component": "Ee (SwCom_03)",
                 "verify": "O", "match": "path"}]
        m = component_map_from_rows(rows)
        variant = "C:/Project/Ados/ne1aw_porting/generated_code/eeprom.c"
        assert bool(resolve_component_entry(variant, m)) is insensitive
        assert resolve_component_entry("C:\\Project\\Ados\\NE1AW_PORTING\\Generated_Code\\EEPROM.c", m)["component"] \
            == "Ee(SwCom_03)"                       # 라벨은 정규화된다(`_normalize_swcom_label`)
        assert component_path_key_matches(variant, "NE1AW_PORTING/Generated_Code/EEPROM.c") is insensitive
        assert not component_path_key_matches(variant, "EEPROM.c"), "경로가 아닌 키는 경로 키 판정에 끼지 않는다"
        assert not component_path_key_matches("C:/x/OTHER_PORTING/Generated_Code/EEPROM.c",
                                              "NE1AW_PORTING/Generated_Code/EEPROM.c")

    def test_a_file_that_is_not_a_docx_is_a_reason_not_a_crash(self, tmp_path):
        """(리뷰 W9) .docx 가 아닌 SDS — 예전엔 BadZipFile 이 그대로 올라가 500 이었다."""
        from report_gen.project_setup import component_map_from_structure_table

        p = tmp_path / "SwDS.docx"
        p.write_bytes(b"%PDF-1.4 not a zip")
        got = component_map_from_structure_table(str(p), str(tmp_path))
        assert got["found"] is False and got["rows"] == [] and "BadZipFile" in got["error"]

    def test_no_structure_table(self, tmp_path):
        from report_gen.project_setup import component_map_from_structure_table

        p = tmp_path / "plain.docx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("word/document.xml", f'<w:document xmlns:w="{_W_NS}"><w:body><w:p/></w:body></w:document>')
        got = component_map_from_structure_table(str(p), str(tmp_path))
        assert got["found"] is False and got["rows"] == []


# ── 설정 엔드포인트 ─────────────────────────────────────────────────────────
class TestSetupEndpoints:
    @pytest.fixture()
    def env(self, maps_dir, tmp_path, monkeypatch):
        from backend.routers import local as L

        monkeypatch.setattr(L, "_materialize_setup_doc", lambda p, label: Path(p))
        monkeypatch.setattr("backend.services.scm_registry.resolve_scm_entry", lambda v: None)
        src = tmp_path / "src"
        src.mkdir()
        for n in ("a.c", "b.c"):
            (src / n).write_text("int v;\n", encoding="utf-8")
        sds = _docx(tmp_path / "sds.docx", [
            [_tc(), _tc("Source"), _tc("APP"), _tc("a.c\nb.c"), _tc("Alpha (SwCom_01)")]])
        return L, src, sds

    @staticmethod
    def _call(L, **kw):
        args = {"sds_path": "", "source_root": "", "output_dir": "", "scm_id": "", "overwrite": False, **kw}
        return L.local_generate_component_map(**args)

    def test_400_without_inputs(self, env):
        from fastapi import HTTPException

        L, src, sds = env
        for kw in ({"source_root": str(src)}, {"sds_path": str(sds)}):
            with pytest.raises(HTTPException) as ei:
                self._call(L, **kw)
            assert ei.value.status_code == 400
        with pytest.raises(HTTPException) as ei:
            L.local_generate_override(uds_path=str(sds), source_root="", output_dir="", scm_id="", overwrite=False)
        assert ei.value.status_code == 400 and "source_root" in str(ei.value.detail)

    def test_writes_project_map_then_409_then_overwrite(self, env, maps_dir):
        from fastapi import HTTPException

        L, src, sds = env
        out = self._call(L, sds_path=str(sds), source_root=str(src))
        assert out["method"] == "structure_table" and out["registered"] is True
        key = roots_key(str(src))
        assert out["project_map"]["key"] == key and Path(out["output_path"]).parent == maps_dir / key
        pm = resolve_project_maps(str(src))
        assert pm.component_map.applied and {r["file"] for r in pm.component_map.data} == {"a.c", "b.c"}
        man = json.loads((maps_dir / key / "project.json").read_text(encoding="utf-8"))
        assert "sha256" in man["maps"]["component_map"]["origin"]
        with pytest.raises(HTTPException) as ei:
            self._call(L, sds_path=str(sds), source_root=str(src))
        assert ei.value.status_code == 409
        # (리뷰2 I-i) 화면은 문구가 아니라 표지로 갈래를 고른다 — 루트가 그대로면 `roots_moved` 는 거짓
        assert ei.value.detail["reason_code"] == "map_exists" and ei.value.detail["roots_moved"] is False
        assert "이미 있다" in ei.value.detail["message"]
        again = self._call(L, sds_path=str(sds), source_root=str(src), overwrite=True)
        assert Path(again["project_map"]["backup"]).is_file()

    def test_status_reports_this_projects_maps(self, env):
        L, src, sds = env
        self._call(L, sds_path=str(sds), source_root=str(src))
        st = L.local_project_setup_status(source_root=str(src), scm_id="")
        assert st["component_map"]["exists"] is True and st["component_map"]["entries"] == 2
        assert st["override"]["exists"] is False and st["override"]["status"] == "none"
        assert [p["key"] for p in st["projects"]] == [roots_key(str(src))]
        bare = L.local_project_setup_status(source_root="", scm_id="")
        assert bare["component_map"]["exists"] is False and bare["component_map"]["status"] == "no_roots"

    def test_output_dir_outside_is_403_and_writes_nothing(self, env, tmp_path):
        from fastapi import HTTPException

        L, src, sds = env
        outside = Path(os.environ.get("SystemDrive", "C:") + os.sep) if os.name == "nt" else Path("/")
        with pytest.raises(HTTPException) as ei:
            self._call(L, sds_path=str(sds), source_root=str(src), output_dir=str(outside / "r97_not_here"))
        assert ei.value.status_code == 403

    def test_export_into_the_project_maps_folder_is_refused(self, env, maps_dir, tmp_path, monkeypatch):
        """(리뷰 W1) 봉인(신뢰 루트)은 맵 폴더 안을 허용한다 — 내보내기로 HD override 를 409 · `.prev` · 매니페스트 없이 덮던 길.
        맵 폴더 안(대소문자만 다른 경로 포함)은 403, 밖의 신뢰 폴더는 내보내고 없는 폴더는 만든다(리뷰 I3)."""
        from fastapi import HTTPException

        from backend.services import paths as paths_mod

        L, src, sds = env
        monkeypatch.setattr(paths_mod, "trusted_roots", lambda: [tmp_path.resolve()])   # tmp 맵 폴더가 봉인을 통과하게
        d = _project(maps_dir, "hd", roots=[tmp_path / "HD"], scm_id="hd", cm=CM, ov=OV)
        before = {p.name: p.read_bytes() for p in d.iterdir()}
        targets = [d, maps_dir, Path(str(d).upper()) if os.name == "nt" else d / "sub"]
        for out in targets:
            with pytest.raises(HTTPException) as ei:
                self._call(L, sds_path=str(sds), source_root=str(src), output_dir=str(out))
            assert ei.value.status_code == 403, out
            with pytest.raises(HTTPException) as ei:
                L.local_generate_override(uds_path=str(sds), source_root=str(src), output_dir=str(out), scm_id="",
                                          overwrite=False)
            assert ei.value.status_code == 403, out
        assert {p.name: p.read_bytes() for p in d.iterdir()} == before, "맵 폴더가 바뀌었다"
        fresh = tmp_path / "export" / "new" / "dir"
        got = self._call(L, sds_path=str(sds), source_root=str(src), output_dir=str(fresh))
        assert got["registered"] is False and (fresh / "component_map.json").is_file()

    def test_export_into_the_repository_docs_folder_is_refused(self, env, maps_dir, tmp_path, monkeypatch):
        """(리뷰2 I-g) 저장소 `docs/`(= 맵 폴더의 부모) 자체로 내보내면 옛 전역 맵 파일 이름(`docs/component_map.json` ·
        `docs/uds_function_swcom_override.json`)이 되살아난다 — 어느 코드도 읽지 않는 파일이 '맵' 처럼 보인다. 403, 아무것도 안 쓴다.
        (tmp 배치: 맵 폴더 = `tmp/project_maps` 라 그 부모 `tmp` 가 '저장소 docs/' 자리다.)"""
        from fastapi import HTTPException

        from backend.services import paths as paths_mod

        L, src, sds = env
        monkeypatch.setattr(paths_mod, "trusted_roots", lambda: [tmp_path.resolve()])
        assert maps_dir.parent == tmp_path
        targets = [tmp_path, Path(str(tmp_path).upper())] if os.name == "nt" else [tmp_path]
        for out in targets:
            with pytest.raises(HTTPException) as ei:
                self._call(L, sds_path=str(sds), source_root=str(src), output_dir=str(out))
            assert ei.value.status_code == 403, out
            with pytest.raises(HTTPException) as ei:
                L.local_generate_override(uds_path=str(sds), source_root=str(src), output_dir=str(out), scm_id="",
                                          overwrite=False)
            assert ei.value.status_code == 403, out
        assert not (tmp_path / "component_map.json").exists()
        assert not (tmp_path / "uds_function_swcom_override.json").exists()
        sub = tmp_path / "exports"                      # docs/ 아래 다른 폴더는 내보내기 자리로 괜찮다
        assert self._call(L, sds_path=str(sds), source_root=str(src), output_dir=str(sub))["registered"] is False

    def test_a_non_docx_sds_is_a_422_with_the_reason_not_a_500(self, env, tmp_path):
        """(리뷰 W9) .docx 가 아닌 SDS — 구조 표 판독기 BadZipFile 이 그대로 올라가 500 이었다. 옛 매칭으로 폴백하고, 그것도 0행이면 422."""
        from fastapi import HTTPException

        L, src, _sds = env
        bad = tmp_path / "SwDS.docx"
        bad.write_bytes(b"%PDF-1.4 not a zip")
        with pytest.raises(HTTPException) as ei:
            self._call(L, sds_path=str(bad), source_root=str(src))
        assert ei.value.status_code == 422 and "BadZipFile" in ei.value.detail["message"]
        assert ei.value.detail["reason_code"] == "unreadable_document"

    @pytest.mark.parametrize("name", ["SwUDS.pdf", "SwUDS.docx"])
    def test_a_pdf_reference_uds_is_a_422_not_a_500(self, env, tmp_path, name):
        """(리뷰2 I-d) 레퍼런스 UDS 로 PDF 를 주면 python-docx 가 `PackageNotFoundError` 를 낸다(BadZipFile 이 아니다) — 500 이었다.
        HTTP 경로 그대로(TestClient · admin 의존성만 통과) 422 + 사유, 아무것도 안 쓴다."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from backend.dependencies.admin import require_admin

        L, src, _sds = env
        pdf = tmp_path / name
        pdf.write_bytes(b"%PDF-1.4 not a zip")
        app = FastAPI()                     # 라우터만 — 인증 미들웨어 없이 admin 의존성만 통과시킨다
        app.include_router(L.router)
        app.dependency_overrides[require_admin] = lambda: None
        res = TestClient(app, raise_server_exceptions=False).post(
            "/api/local/project-setup/generate-override", data={"uds_path": str(pdf), "source_root": str(src)})
        assert res.status_code == 422, res.text[:300]
        det = res.json()["detail"]
        assert det["reason_code"] == "unreadable_document" and ".docx" in det["message"]

    def test_document_defect_candidates_are_named_in_the_manifest(self, env, maps_dir, tmp_path):
        """(리뷰 W8b) 표에는 있는데 소스에 없는 파일은 매니페스트에 **이름으로** 남고(공시가 읽는다), 비슷한 소스 이름은 힌트일 뿐이다."""
        L, src, _sds = env
        (src / "ghosts.c").write_text("int v;\n", encoding="utf-8")       # 비슷한 이름(힌트 대상) — 행은 안 생긴다
        sds = _docx(tmp_path / "sds2.docx", [
            [_tc(), _tc(), _tc("APP"), _tc("a.c\nghost.c"), _tc("Alpha (SwCom_01)")]])
        out = self._call(L, sds_path=str(sds), source_root=str(src))
        man = json.loads((maps_dir / out["project_map"]["key"] / "project.json").read_text(encoding="utf-8"))
        spec = man["maps"]["component_map"]
        assert spec["table_files_not_in_source"] == ["ghost.c"] and spec["method"] == "structure_table"
        assert spec["table_files_not_in_source_hints"] == {"ghost.c": ["ghosts.c"]}
        use = resolve_project_maps(str(src)).component_map
        assert use.details["table_files_not_in_source"] == ["ghost.c"]
        assert {r["file"] for r in use.data} == {"a.c"}, "힌트 파일에 행이 생겼다"

    def test_a_write_clears_the_source_stage_and_measurement_caches(self, env):
        """(리뷰 M11) 쓴 뒤 두 캐시를 비운다 — 지문이 달라 어차피 안 맞지만 옛 맵의 큰 payload 를 TTL 동안 붙잡지 않게."""
        from backend import state
        from backend.services import docgen_test_materials as tm

        L, src, sds = env
        with state.source_sections_cache_lock:
            state.source_sections_cache["r97-probe"] = {"payload": {}, "cached_at": 0.0}
        with tm._CACHE_LOCK:
            tm._CACHE["r97-probe"] = (0.0, {"ok": True}, None)
        out = self._call(L, sds_path=str(sds), source_root=str(src))
        assert out["project_map"]["caches_cleared"] >= 1
        assert "r97-probe" not in state.source_sections_cache and "r97-probe" not in tm._CACHE


class TestSetupRootsMoved:
    """(리뷰 W7) 레지스트리 루트가 바뀌어 맵이 안 걸릴 때 — 안내가 '맵을 다시 만들라' 로 이어지면 HD 의 손으로 정한 verify=X 맵이
    자동 생성물(전부 O)로 덮인다. 루트만 다시 등록하는 길이 있어야 하고, 409 · 상태가 그 길을 먼저 말해야 한다."""

    @pytest.fixture()
    def env(self, maps_dir, tmp_path, monkeypatch):
        from types import SimpleNamespace

        from backend.routers import local as L
        from backend.services import scm_registry as sr

        old, new = tmp_path / "old_root", tmp_path / "new_root"
        new.mkdir()
        (new / "a.c").write_text("int v;\n", encoding="utf-8")
        entry = SimpleNamespace(id="hd", name="HD", source_root=str(new))
        monkeypatch.setattr(sr, "resolve_scm_entry", lambda v: entry)
        monkeypatch.setattr(sr, "get_registry_entry", lambda i: entry if str(i).lower() == "hd" else None)
        monkeypatch.setattr(L, "_materialize_setup_doc", lambda p, label: Path(p))
        d = _project(maps_dir, "hd", roots=[old], scm_id="hd", cm=CM)        # 손으로 정한 X 행이 든 맵
        sds = _docx(tmp_path / "sds.docx", [[_tc(), _tc(), _tc("APP"), _tc("a.c"), _tc("Alpha (SwCom_01)")]])
        return L, d, new, sds

    def test_status_says_roots_moved_and_409_points_to_update_roots(self, env):
        from fastapi import HTTPException

        L, d, new, sds = env
        st = L.local_project_setup_status(source_root=str(new), scm_id="")
        assert st["component_map"]["exists"] is False
        assert st["roots_moved"]["key"] == "hd" and "update-roots" in st["roots_moved"]["hint"]
        assert next(p for p in st["projects"] if p["key"] == "hd")["roots_covered"] is False
        cm_before = (d / "component_map.json").read_bytes()
        with pytest.raises(HTTPException) as ei:
            L.local_generate_component_map(sds_path=str(sds), source_root=str(new), output_dir="", scm_id="",
                                           overwrite=False)
        assert ei.value.status_code == 409 and "루트를 다시 등록" in ei.value.detail["message"]
        assert ei.value.detail["roots_moved"] is True and ei.value.detail["reason_code"] == "map_exists"
        assert "관리자" in ei.value.detail["message"], "(리뷰2 I-f) 루트 재등록은 관리자 전용이라고 말한다"
        assert (d / "component_map.json").read_bytes() == cm_before

    def test_update_roots_keeps_the_map_and_makes_it_apply(self, env):
        L, d, new, sds = env
        cm_before = (d / "component_map.json").read_bytes()
        res = L.local_update_project_roots(source_root=str(new), scm_id="")
        assert res["roots_after"] == [str(new)] and (d / "component_map.json").read_bytes() == cm_before
        pm = resolve_project_maps(str(new))
        assert pm.component_map.applied and any(r["verify"] == "X" for r in pm.component_map.data), "손으로 정한 X 가 남는다"
        assert L.local_project_setup_status(source_root=str(new), scm_id="")["roots_moved"] is None

    def test_update_roots_refuses_other_projects_and_unregistered_roots(self, env, maps_dir, monkeypatch):
        from fastapi import HTTPException

        from backend.services import scm_registry as sr

        L, d, new, sds = env
        man = json.loads((d / "project.json").read_text(encoding="utf-8"))
        man["scm_id"] = "someone_else"
        (d / "project.json").write_text(json.dumps(man), encoding="utf-8")
        with pytest.raises(HTTPException) as ei:
            L.local_update_project_roots(source_root=str(new), scm_id="")
        assert ei.value.status_code == 409
        monkeypatch.setattr(sr, "resolve_scm_entry", lambda v: None)
        with pytest.raises(HTTPException) as ei:
            L.local_update_project_roots(source_root=str(new), scm_id="")
        assert ei.value.status_code == 400

    def test_overwrite_by_the_same_project_moves_the_manifest_roots(self, env):
        L, d, new, sds = env
        out = L.local_generate_component_map(sds_path=str(sds), source_root=str(new), output_dir="", scm_id="",
                                             overwrite=True)
        assert out["roots_covered"] is True and Path(out["project_map"]["backup"]).is_file()
        assert resolve_project_maps(str(new)).component_map.applied

    def test_overwrite_never_moves_the_roots_of_another_projects_manifest(self, env):
        """(리뷰2 R2) 폴더 키는 레지스트리 id(`hd`)인데 매니페스트 `scm_id` 가 다른 프로젝트다(손으로 옮긴 폴더 · 옛 기록). 덮어쓰기가
        그 매니페스트 루트를 레지스트리 루트로 바꾸면 **남의 프로젝트**가 이 루트를 주장하게 된다 — 루트는 그대로여야 한다."""
        L, d, new, sds = env
        man = json.loads((d / "project.json").read_text(encoding="utf-8"))
        man["scm_id"] = "someone_else"
        (d / "project.json").write_text(json.dumps(man), encoding="utf-8")
        before = man["source_roots"]
        out = L.local_generate_component_map(sds_path=str(sds), source_root=str(new), output_dir="", scm_id="",
                                             overwrite=True)
        after = json.loads((d / "project.json").read_text(encoding="utf-8"))
        assert after["source_roots"] == before and after["scm_id"] == "someone_else"
        assert out["roots_covered"] is False and not resolve_project_maps(str(new)).component_map.applied


def _through_app_handler(exc):
    """(리뷰3 W1) 앱에 **등록된** HTTPException 핸들러로 예외를 응답 본문으로 — 화면이 실제로 받는 것.

    전역 핸들러(`backend/error_handler.py` `http_exception_handler`)는 dict detail 을 `{ok:false, error:{code, message,
    detail:{…}}}` 봉투로 바꾼다. 화면(`frontend-v2/src/api.js` `toApiError`)은 `error.message` · `error.detail.reason_code` ·
    `error.detail.roots_moved` · `error.detail.key` 를 읽는다 — 핸들러나 등록이 바뀌면 덮어쓰기 가드 대신 이 시험이 깨져야 한다.
    """
    import asyncio

    from fastapi import HTTPException

    from backend.main import app

    handler = app.exception_handlers.get(HTTPException)
    assert handler is not None, "HTTPException 핸들러가 등록되지 않았다 — 화면이 기대하는 봉투가 아니다"
    resp = asyncio.run(handler(None, exc))
    return resp.status_code, json.loads(resp.body)


class TestSetupErrorEnvelope:
    """(리뷰3 W1) 설정 엔드포인트가 **실제로 던지는** 예외를 앱 핸들러에 통과시켜, 화면이 읽는 봉투 키를 고정한다. vitest mock 은
    이 키 이름을 그대로 쓴다(`ProjectSetupSection.test.jsx` `envelope`)."""

    def test_roots_moved_409(self, maps_dir, tmp_path, monkeypatch):
        from types import SimpleNamespace

        from fastapi import HTTPException

        from backend.routers import local as L
        from backend.services import scm_registry as sr

        new = tmp_path / "new_root"
        new.mkdir()
        (new / "a.c").write_text("int v;\n", encoding="utf-8")
        entry = SimpleNamespace(id="hd", name="HD", source_root=str(new))
        monkeypatch.setattr(sr, "resolve_scm_entry", lambda v: entry)
        monkeypatch.setattr(sr, "get_registry_entry", lambda i: entry if str(i).lower() == "hd" else None)
        monkeypatch.setattr(L, "_materialize_setup_doc", lambda p, label: Path(p))
        d = _project(maps_dir, "hd", roots=[tmp_path / "old_root"], scm_id="hd", cm=CM)
        sds = _docx(tmp_path / "sds.docx", [[_tc(), _tc(), _tc("APP"), _tc("a.c"), _tc("Alpha (SwCom_01)")]])
        with pytest.raises(HTTPException) as ei:
            L.local_generate_component_map(sds_path=str(sds), source_root=str(new), output_dir="", scm_id="", overwrite=False)
        status, body = _through_app_handler(ei.value)
        assert status == 409 and body["ok"] is False
        assert "루트를 다시 등록" in body["error"]["message"] and "관리자" in body["error"]["message"]
        assert body["error"]["detail"] == {"reason_code": "map_exists", "roots_moved": True, "key": "hd"}

        (d / "project.json").write_text("{oops", encoding="utf-8")          # 덮어쓰기로 풀리지 않는 409
        with pytest.raises(HTTPException) as ei:
            L.local_generate_component_map(sds_path=str(sds), source_root=str(new), output_dir="", scm_id="", overwrite=True)
        status, body = _through_app_handler(ei.value)
        assert status == 409 and body["error"]["detail"] == {"reason_code": "manifest_unreadable"}
        assert "매니페스트를 읽지 못했다" in body["error"]["message"]

    def test_unreadable_document_422(self, maps_dir, tmp_path, monkeypatch):
        from fastapi import HTTPException

        from backend.routers import local as L

        monkeypatch.setattr(L, "_materialize_setup_doc", lambda p, label: Path(p))
        pdf = tmp_path / "SwUDS.pdf"
        pdf.write_bytes(b"%PDF-1.4 not a zip")
        with pytest.raises(HTTPException) as ei:
            L.local_generate_override(uds_path=str(pdf), source_root=str(tmp_path), output_dir="", scm_id="", overwrite=False)
        status, body = _through_app_handler(ei.value)
        assert status == 422 and body["error"]["detail"] == {"reason_code": "unreadable_document"}
        assert ".docx 인지 확인할 것" in body["error"]["message"]


class TestSetupEndpointsAreAdminOnly:
    """(리뷰 W6) 맵 쓰기는 admin 전용 — 레지스트리 쓰기(`/api/scm/*`)와 같은 등급. 상태는 누구나 읽는다.
    ⚠ 게이트만 본다 — 비관리자 요청이 핸들러에 닿으면 안 되므로 핸들러 부작용은 실행되지 않는다(`test_scm_write_requires_admin` 교훈)."""

    @pytest.fixture()
    def client(self, maps_dir):
        from fastapi.testclient import TestClient

        from backend.main import app

        return TestClient(app, raise_server_exceptions=False)

    @pytest.mark.parametrize("path,form", [
        ("/api/local/project-setup/generate-component-map", {"sds_path": "x.docx", "source_root": "C:/nowhere"}),
        ("/api/local/project-setup/generate-override", {"uds_path": "x.docx", "source_root": "C:/nowhere"}),
        ("/api/local/project-setup/update-roots", {"source_root": "C:/nowhere"}),
    ])
    def test_non_admin_cannot_write(self, client, path, form, maps_dir):
        res = client.post(path, data=form, headers={"X-User": "nobody_not_admin_zzz"})
        assert res.status_code in (401, 403), (path, res.status_code, res.text[:200])
        assert list(maps_dir.iterdir()) == []

    def test_status_stays_readable(self, client):
        res = client.get("/api/local/project-setup/status", headers={"X-User": "nobody_not_admin_zzz"})
        assert res.status_code == 200, res.text[:200]


# ── 공시 · 생성 항목 ────────────────────────────────────────────────────────
class TestDisclosure:
    @staticmethod
    def _items(qr, doc="suts"):
        from report_gen.generation_disclosures import build_disclosures

        return {i["key"]: i for i in build_disclosures(doc, qr) if i["key"].startswith("project_maps_")}

    def test_applied_is_one_info_line_naming_the_project(self):
        pm = {"component_map": {"status": "applied", "project": "HDPDM01", "file": "hdpdm01/component_map.json",
                                "entries": 153, "origin": "SDS v1.04", "source_stage": "same"},
              "override": {"status": "applied", "project": "HDPDM01", "file": "hdpdm01/uds_function_swcom_override.json",
                           "entries": 251}}
        items = self._items({"project_maps": pm})
        assert items["project_maps_component_map"]["tone"] == "info"
        assert items["project_maps_component_map"]["value"] == "HDPDM01 153행"
        assert "docs/project_maps/hdpdm01/component_map.json" in items["project_maps_component_map"]["note"]
        assert items["project_maps_override"]["value"] == "HDPDM01 251개"

    def test_not_this_project_is_a_warning_with_guidance(self):
        pm = {"component_map": {"status": "not_this_project", "reason": "다른 프로젝트(hdpdm01) 것이라 쓰지 않는다"},
              "override": {"status": "none", "project": "KJPDS02_PV", "reason": "override 맵을 등록하지 않았다"}}
        items = self._items({"project_maps": pm})
        cm = items["project_maps_component_map"]
        assert cm["tone"] == "warning" and "hdpdm01" in cm["note"]
        assert "프로젝트 설정에서 이 프로젝트의 SDS 로 맵을 만들면 SwCom 라벨 · 시험 범위 판정이 생긴다" in cm["note"]
        assert items["project_maps_override"]["tone"] == "info", "맵을 등록하지 않은 것은 정보다"

    @pytest.mark.parametrize("status", ["ambiguous", "invalid"])
    def test_ambiguous_and_invalid_warn(self, status):
        items = self._items({"project_maps": {"component_map": {"status": status, "reason": "r"}}})
        assert items["project_maps_component_map"]["tone"] == "warning"

    def test_applied_with_document_defect_candidates_warns_and_names_them(self):
        """(리뷰2 R7) 맵은 걸렸지만 매니페스트가 문서 결함 후보(구조 표에는 있는데 소스에 없는 파일)를 적어 뒀다 — 사람이 SDS 를 고칠
        일이라 경고다(정보로 내리면 아무도 안 본다). 후보 이름과 힌트가 문구에 실린다. 후보가 없으면 정보."""
        base = {"status": "applied", "project": "KJPDS02_PV", "file": "kjpds02_pv/component_map.json", "entries": 99}
        flagged = {**base, "details": {"table_files_not_in_source": ["ghost.c"],
                                       "table_files_not_in_source_hints": {"ghost.c": ["ghosts.c"]}}}
        item = self._items({"project_maps": {"component_map": flagged}})["project_maps_component_map"]
        assert item["tone"] == "warning" and "`ghost.c`" in item["note"] and "ghosts.c" in item["note"]
        assert pmod.needs_attention(flagged) is False, "경고는 결함 후보에서 왔다 — 판정 상태 · 문제가 아니다"
        clean = self._items({"project_maps": {"component_map": {**base, "details": {"table_files_not_in_source": []}}}})
        assert clean["project_maps_component_map"]["tone"] == "info"

    def test_guidance_says_map_setup_is_admin_only(self):
        """(리뷰2 I-f) 맵 만들기 · 루트 다시 등록은 관리자 전용 — 공시 · UDS 생성 항목 설명이 그 사실을 말한다(일반 사용자가 403 을 헤매지 않게)."""
        from backend.services.issue_explainer import rule_action

        for kind in ("component_map", "override"):
            item = self._items({"project_maps": {kind: {"status": "not_this_project", "reason": "r"}}})[f"project_maps_{kind}"]
            assert "관리자 전용" in item["note"], kind
        assert "관리자 전용" in rule_action("project_map_not_applied")

    def test_source_stage_that_differs_warns(self):
        pm = {"component_map": {"status": "applied", "project": "P", "file": "p/c.json", "source_stage": "differs",
                                "source_stage_status": "not_this_project"}}
        assert self._items({"project_maps": pm})["project_maps_component_map"]["tone"] == "warning"

    def test_old_artifact_without_the_block_gets_no_item(self):
        assert self._items({"tc_profile": "extended"}) == {}

    def test_sts_reads_it_from_generation_stats(self):
        pm = {"component_map": {"status": "none", "reason": "등록된 맵이 없다"}}
        assert "project_maps_component_map" in self._items({"generation_stats": {"project_maps": pm}}, doc="sts")

    def test_uds_issue_for_maps_that_need_a_person(self):
        from backend.helpers.uds import _note_project_maps
        from report_gen.gen_issues import IssueCollector

        c = IssueCollector()
        _note_project_maps(c, {"project_maps": {
            "component_map": {"status": "not_this_project", "reason": "남의 맵", "others": ["hdpdm01"]},
            "override": {"status": "none", "reason": "등록 안 함"}}})
        got = c.as_list()
        assert [i["code"] for i in got] == ["project_map_not_applied"] and "component_map" in got[0]["message"]
        c2 = IssueCollector()
        _note_project_maps(c2, {"project_maps": {"component_map": {"status": "invalid", "used": "argument"}}})
        assert c2.as_list() == [], "업로드 목록을 썼으면 프로젝트 맵 판정은 사람이 볼 일이 아니다"


# ── 배선 — 판정이 생성기 · 게이트 · 재생성 · UDS 경로까지 닿는가 (리뷰 W4 · W2 · I1) ─────────────────────
_WIRE_CM = [
    {"structure": "APP", "file": "a.c", "component": "Alpha (SwCom_01)", "verify": "O"},
    {"structure": "APP", "file": "b.c", "component": "Beta (SwCom_02)", "verify": "O"},
    {"structure": "Lib", "file": "c.c", "component": "Lib", "verify": "X"},
]


def _wire_tree(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.c").write_bytes(b"void B(void);\nvoid A(void)\n{\n    B();\n}\n")
    (root / "b.c").write_bytes(b"unsigned char g_b;\nvoid B(void)\n{\n    g_b = 1U;\n}\n")
    (root / "c.c").write_bytes(b"unsigned char g_c;\nvoid C(void)\n{\n    g_c = 2U;\n}\n")
    return root


@pytest.fixture()
def wire(maps_dir, tmp_path, monkeypatch):
    """작은 트리 + 그 트리를 등록한 tmp 프로젝트 맵. 디스크 캐시 · 메모리 캐시는 이 테스트 것만."""
    from backend.helpers import uds as uds_mod

    monkeypatch.setattr(uds_mod, "_source_sections_disk_cache_path", lambda *a, **k: tmp_path / "disk.json")
    uds_mod.clear_source_sections_cache()
    src = _wire_tree(tmp_path / "src")
    _project(maps_dir, "proj", roots=[src], scm_id="proj", cm=_WIRE_CM)
    yield src
    uds_mod.clear_source_sections_cache()


class TestWiring:
    def test_suts_and_sits_report_the_map_and_suts_scopes_with_it(self, wire, tmp_path, caplog):
        """M5 · M6 · M7 — SUTS 는 프로젝트 component_map 으로 시험 범위(verify=X)를 판정하고, SUTS · SITS 품질 리포트가 어느 맵을
        썼는지 싣는다. 세 배선 중 하나만 빠져도 여기서 깨진다(실 생성, 작은 트리)."""
        import logging

        from generators import sits as gsits
        from generators import suts as gsuts

        with caplog.at_level(logging.INFO, logger="generators.suts"):
            q = gsuts.generate_suts(source_root=str(wire), output_path=str(tmp_path / "u.xlsm"), scope="source")["quality_report"]
        assert q["project_maps"]["component_map"]["status"] == "applied" and q["project_maps"]["component_map"]["project"] == "PROJ"
        logs = " ".join(r.getMessage() for r in caplog.records)
        assert "verify=X) 파일 유래 unit 1개" in logs, "SUTS 가 프로젝트 맵으로 시험 범위를 판정하지 않았다"
        assert "component_map 없음" not in logs
        qs = gsits.generate_sits(source_root=str(wire), output_path=str(tmp_path / "i.xlsm")).get("quality_report") or {}
        assert qs.get("project_maps", {}).get("component_map", {}).get("status") == "applied", "SITS 리포트에 맵 기록이 없다"

    def test_impact_regeneration_picks_the_map_by_scm_id(self, wire, maps_dir, tmp_path, monkeypatch):
        """M10 — 영향 분석 재생성은 등록 항목 id 로 맵을 고른다: 루트가 두 매니페스트에 다 들어 루트로는 모호한 경우 id 가 고른다.
        (리뷰2 W1 이후 id 는 루트 밖을 구하지 않는다 — 모호 해소가 id 의 몫이다.)"""
        from types import SimpleNamespace

        import sits_generator
        import suts_generator
        import workflow.impact_orchestrator as io
        from backend.schemas import ScmLinkedDocs

        _project(maps_dir, "other", roots=[wire, tmp_path / "B"], scm_id="other", cm=CM)
        assert resolve_project_maps(str(wire)).component_map.status == "ambiguous"
        checkout = wire
        seen: dict = {}
        real_suts, real_sits = suts_generator.generate_suts, sits_generator.generate_sits
        monkeypatch.setattr(suts_generator, "generate_suts", lambda **kw: seen.setdefault("suts", real_suts(**kw)))
        monkeypatch.setattr(sits_generator, "generate_sits", lambda **kw: seen.setdefault("sits", real_sits(**kw)))
        monkeypatch.setattr(io, "SUTS_REPORT_DIR", tmp_path / "out_suts")
        monkeypatch.setattr(io, "SITS_REPORT_DIR", tmp_path / "out_sits", raising=False)
        entry = SimpleNamespace(source_root=str(checkout), id="proj", linked_docs=ScmLinkedDocs())
        io._run_suts_generation(entry, [])
        io._run_sits_generation(entry)
        assert seen["suts"]["quality_report"]["project_maps"]["component_map"]["status"] == "applied"
        assert (seen["sits"].get("quality_report") or {}).get("project_maps", {}).get("component_map", {}).get(
            "status") == "applied"

    def test_uds_route_resolves_by_roots_like_suts_for_mixed_roots(self, wire, tmp_path, monkeypatch):
        """W2 · M8 — `PDS64_RD,<미등록>` 같은 섞인 루트에서 참조 SwUDS 해석은 id 를 준다(루트 조각 하나만 맞아도). 그 id 로 맵을
        고르면 UDS 는 맵을 쓰고 SUTS · SITS · STS 는 `not_this_project` 라 같은 입력에서 SwUFn · 모듈이 갈린다. UDS 도 루트로 고르고,
        안 걸린 사실을 생성 항목으로 말해야 한다(실 경로 `_uds_generate_from_paths`, docx 쓰기만 가짜)."""
        import docx

        from backend.helpers import uds as U

        other = tmp_path / "unregistered"
        other.mkdir()
        (other / "z.c").write_text("int z(void){return 0;}\n", encoding="utf-8")
        mixed = f"{wire},{other}"
        suts_view = resolve_project_maps(mixed).component_map.status
        assert suts_view == "not_this_project"
        build = tmp_path / "build"
        build.mkdir()

        def _fake_docx(tpl, payload, out_path, retries=3, **_kw):  # noqa: ANN001
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            docx.Document().save(str(out_path))

        monkeypatch.setattr(U, "_resolve_cached_build_root", lambda *a, **k: build)
        monkeypatch.setattr(U, "_generate_docx_with_retry", _fake_docx)
        monkeypatch.setattr(U, "_record_uds_run", lambda *a, **k: None)
        seen: dict = {}
        real = U.generate_uds_source_sections

        def _spy(root, **kw):
            out = real(root, **kw)
            seen["project_maps"] = out.get("project_maps")
            return out

        monkeypatch.setattr(U, "generate_uds_source_sections", _spy)
        ref = {"raw": "", "why": "", "origin": "", "scm_id": "proj", "basis": "path", "registry_uds": "",
               "compare": "", "mismatch": None}
        # 완료 결과의 `issues`(이 실행의 수집기)를 본다 — ⚠ 바깥 `use_collector()` 는 쓰지 않는다: 빈 수집기는 `__len__` 이 0 이라
        #   `current_collector() or IssueCollector()` 가 그것을 버리고 지역 수집기를 연다(기존 동작, 이 라운드 범위 밖)
        result = U._uds_generate_from_paths(
            job_url="http://ci/job/x/", cache_root=str(tmp_path), build_selector="", template_path="",
            source_root=mixed, source_only=True, req_file_paths=[], note_file_paths=[], logic_file_paths=[],
            req_paths=[], reference_source=ref)
        assert seen["project_maps"]["component_map"]["status"] == suts_view, "UDS 가 SUTS 와 다른 맵 판정을 썼다"
        msgs = [i for i in (result.get("issues") or []) if i["code"] == "project_map_not_applied"]
        assert msgs and any("component_map" in i["message"] for i in msgs), "맵이 안 걸린 사실을 UDS 가 말하지 않았다"

    def test_preflight_finds_the_measurement_made_with_the_same_scm_id(self, wire, maps_dir, tmp_path):
        """M14 — 준비 게이트는 측정과 같은 SCM id 로 측정 캐시를 찾는다(키는 그 id 로 고른 맵의 지문). 루트가 두 매니페스트에 다
        들어 루트로는 모호한데 id 를 빼고 찾으면 모호 판정의 지문이라 영영 `unmeasured` 다."""
        import time

        from backend.routers import docgen_preflight as dp
        from backend.services import docgen_test_materials as tm

        _project(maps_dir, "other", roots=[wire, tmp_path / "B"], scm_id="other", cm=CM)
        checkout = wire
        req = dp.PreflightRequest(doc_type="sts", scm_id="proj", source_root=str(checkout))
        paths = dp._tm_lookup_paths(dp._resolve_inputs(req))
        res = {"ok": True, "sits": {"flows_total": 7, "cap": 120},
               "uds_category_caps": {"measured": True, "cap": 120, "any_truncated": False, "truncated": {}},
               "uds_file_scan": {"measured": True, "cap": 1200, "truncated": False}}
        assert tm._key(str(checkout), **paths, scm_id="proj") != tm._key(str(checkout), **paths), "전제: id 가 키를 바꾼다"
        tm.clear_cache()
        try:
            with tm._CACHE_LOCK:
                tm._CACHE[tm._key(str(checkout), **paths, scm_id="proj")] = (time.time(), res)
            steps = dp._compute_preflight(req)["steps"]
        finally:
            tm.clear_cache()
        assert not [s for s in steps if s["id"] == "test_materials" and s["state"] == "unmeasured"], \
            "측정해 둔 결과를 게이트가 못 찾았다 — 조회가 SCM id 를 버렸다"

    def test_the_maps_are_resolved_once_per_measurement_and_per_cache_fill(self, wire, monkeypatch):
        """I1 — 측정 · 소스 단계 캐시는 판정을 **한 번** 하고 그 판정으로 파싱 · 키를 다 한다(두 번 고르면 그 사이 바뀐 맵의
        결과가 옛 지문에 저장된다)."""
        import report_generator as _rg
        from backend.helpers import uds as uds_mod
        from backend.services import docgen_test_materials as tm

        calls: list = []
        real = pmod.resolve_project_maps

        def _count(*a, **k):
            calls.append(1)
            return real(*a, **k)

        monkeypatch.setattr(pmod, "resolve_project_maps", _count)
        got: dict = {}

        def _fake_gen(root, **kw):
            got["pm"] = kw.get("project_maps")
            # 함수가 하나는 있어야 측정이 캐시 저장(서명 · 키)까지 간다 — 빈 결과는 일찍 돌아가 두 번째 판정을 못 본다(리뷰2 I-h)
            return {"function_details": {"f": {"name": "f"}}}

        monkeypatch.setattr(uds_mod, "generate_uds_source_sections", _fake_gen)
        uds_mod._get_source_sections_cached(str(wire))
        assert len(calls) == 1 and got["pm"] is not None and got["pm"].component_map.applied
        calls.clear()
        monkeypatch.setattr(_rg, "generate_uds_source_sections", _fake_gen)
        tm.clear_cache()
        try:
            res = tm.measure(str(wire))
            assert len(calls) == 1, f"측정이 맵을 {len(calls)}번 골랐다"
            assert got["pm"] is not None, "측정이 고른 판정을 소스 단계에 넘기지 않았다(소스 단계가 다시 고른다)"
            assert res.get("ok") is not False and tm.cached(str(wire)) is not None, "측정이 캐시 저장까지 가지 않았다"
        finally:
            tm.clear_cache()

    def test_a_map_written_mid_measurement_does_not_label_old_results_as_new(self, wire, maps_dir, tmp_path, monkeypatch):
        """I1 — 리뷰가 지목한 경합 그대로: 측정 · 캐시 채움 **도중** 맵이 바뀐다. 옛 맵으로 판 결과는 옛 지문 키에 남아야 하고, 새 맵
        지문으로 조회하면 **못 찾아야** 한다(찾으면 새 맵 이름으로 옛 결과를 내준다)."""
        import report_generator as _rg
        from backend.helpers import uds as uds_mod
        from backend.services import docgen_test_materials as tm

        cm_file = maps_dir / "proj" / "component_map.json"

        def _gen_and_change_map(root, **kw):
            cm_file.write_text(json.dumps(_WIRE_CM[:1]), encoding="utf-8")      # 생성 중에 누군가 맵을 고쳤다
            return {"function_details": {"f": {"name": "f"}}}

        monkeypatch.setattr(uds_mod, "generate_uds_source_sections", _gen_and_change_map)
        uds_mod._get_source_sections_cached(str(wire))
        parsed: list = []
        monkeypatch.setattr(uds_mod, "generate_uds_source_sections", lambda root, **kw: parsed.append(1) or {})
        uds_mod._get_source_sections_cached(str(wire))
        assert parsed == [1], "새 맵 지문으로 조회했는데 옛 맵으로 판 결과가 돌아왔다"

        monkeypatch.setattr(_rg, "generate_uds_source_sections", _gen_and_change_map)
        # 서명이 있는 로컬 루트와, 서명이 없어(cloudium) **키만** 판정하는 경우 둘 다 — 후자에서는 키가 유일한 방어선이다
        for no_signature in (False, True):
            if no_signature:
                monkeypatch.setattr(uds_mod, "_source_root_signature", lambda *a, **k: None)
            cm_file.write_text(json.dumps(_WIRE_CM), encoding="utf-8")
            tm.clear_cache()
            try:
                tm.measure(str(wire))
                assert tm.cached(str(wire)) is None, f"측정 중 바뀐 맵의 지문으로 옛 결과가 저장됐다(서명 없음={no_signature})"
            finally:
                tm.clear_cache()


# ── 실 자료 (없으면 skip) ───────────────────────────────────────────────────
_HD_ROOTS = "D:/Project/Ados/PDS64_RD,D:\\Project\\Ados\\PDS64_FBL"
_PV_ROOTS = "C:\\Project\\Ados\\NE1AW_PORTING,C:\\Project\\Ados\\PDS128_FBL"
_PV_SDS = Path(r"D:\Project\devops\Release_claude\.codex_tmp\pv_docs"
               r"\(KJPDS02_SwDS) Software Architecture Design Specification_v3.01_20260410_R_변경내역반영.docx")


class TestRepositoryMaps:
    def test_hd_maps_apply_to_pds64_roots_only(self):
        hd = resolve_project_maps(_HD_ROOTS)
        assert hd.component_map.applied and hd.override.applied
        assert hd.component_map.project == hd.override.project == "HDPDM01"
        assert len(hd.component_map.data) == 153 and len(hd.override.data) == 251
        assert sum(1 for r in hd.component_map.data if r.get("verify") == "X") == 49
        pv = resolve_project_maps(_PV_ROOTS)
        assert pv.component_map.project != "HDPDM01" and pv.override.project != "HDPDM01"
        assert pv.override.status == "none", "PV 는 override 를 등록하지 않았다"

    def test_hd_maps_are_byte_identical_to_the_moved_files(self):
        """옮기기만 했다 — 내용이 옮기기 전 저장소 파일(커밋 blob, LF)과 같다(HDPDM01 산출물 불변의 근거).

        ⚠ (리뷰 W5) 작업 트리의 바이트가 아니라 **줄끝을 LF 로 접은** 바이트의 sha1 을 본다 — 메인 체크아웃은 이 JSON 들이 CRLF
          (`git ls-files --eol` 의 `w/crlf`)라 작업 트리 sha1 을 박으면 그 체크아웃에서만 깨진다. 생성이 쓰는 지문
          (`MapUse.sha1`)은 체크아웃마다 다를 수 있다(캐시 키일 뿐 판정에는 안 쓴다) — 그래서 그 값은 단언하지 않는다.
        """
        import hashlib

        hd = resolve_project_maps(_HD_ROOTS)
        for use, want in ((hd.component_map, "9d12c3297aa0e4d6c4eabc1018c03cdce450b635"),
                          (hd.override, "2edb4e0e428d2231138d36f73356c58ef659bb35")):
            raw = (REPO / "docs" / "project_maps" / use.file).read_bytes().replace(b"\r\n", b"\n")
            assert hashlib.sha1(raw).hexdigest() == want, use.file

    def test_pv_map_from_its_own_structure_table(self):
        pv = resolve_project_maps(_PV_ROOTS)
        assert pv.component_map.applied and pv.component_map.project == "KJPDS02_PV"
        assert pv.component_map.scm_id == "kjpds02_pv"
        assert {r["verify"] for r in pv.component_map.data} == {"O"}
        assert "f665012a3c935d2a41e80ecaa9db81cd1d2dc603b813f0eefb023271afaf1da6" in pv.component_map.origin
        assert not any(r["file"].lower() == "lin.c" for r in pv.component_map.data), "PV 표는 FBL lin.c 를 적지 않는다"
        assert resolve_project_maps(_PV_ROOTS, scm_id="kjpds02_pv").fingerprint == pv.fingerprint
        assert not resolve_project_maps("X:/cache", scm_id="kjpds02_pv").component_map.applied, \
            "(리뷰2 W1) 매니페스트 루트 밖의 체크아웃에는 id 로도 걸지 않는다"
        # (리뷰 W8) APP · FBL 에 다 있는 EEPROM.c/.h — 표가 적은 `Generated_Code` 사본만 경로 키, FBL 사본은 라벨 없음
        from report_gen.requirements import component_map_from_rows, resolve_component_entry
        m = component_map_from_rows(pv.component_map.data)
        assert resolve_component_entry("C:/Project/Ados/NE1AW_PORTING/Generated_Code/EEPROM.c", m)["component"] == \
            "EEPROM(SwCom_21)"
        assert resolve_component_entry("C:/Project/Ados/PDS128_FBL/Sources/Eeprom/EEPROM.c", m) == {}
        # 문서 결함 후보 4개가 매니페스트에 **이름으로** 있다(공시가 읽는다) — 비슷한 이름은 힌트일 뿐 행이 아니다
        det = pv.component_map.details
        assert sorted(det["table_files_not_in_source"]) == [
            "Ap_BuzzerCtrl_it_PDS.c", "Ap_DoorCtrl_it.PDS.h", "SysDiag_PDS.c", "SysDiag_it_PDS.h"]
        assert det["table_files_not_in_source_hints"]["SysDiag_PDS.c"] == ["SysDiagCtrl_PDS.c"]
        assert resolve_component_entry("C:/Project/Ados/NE1AW_PORTING/Sources/SYSTEM/SysDiagCtrl_PDS.c", m) == {}
        from report_gen.generation_disclosures import build_disclosures
        note = next(i for i in build_disclosures("suts", {"project_maps": pv.describe()})
                    if i["key"] == "project_maps_component_map")["note"]
        assert "`SysDiag_PDS.c`(비슷한 소스: SysDiagCtrl_PDS.c)" in note

    @pytest.mark.skipif(not (_PV_SDS.is_file() and Path("C:/Project/Ados/NE1AW_PORTING").is_dir()),
                        reason="PV SwDS 사본 · PV 소스가 이 머신에 없다")
    def test_pv_structure_table_lists_101_source_files(self):
        from report_gen.project_setup import component_map_from_structure_table

        got = component_map_from_structure_table(str(_PV_SDS), _PV_ROOTS)
        st = got["stats"]
        assert st["source_files"] == 178 and st["source_files_listed"] == 101
        assert "SysDiag_PDS.c" in st["table_files_not_in_source"] and len(st["table_files_not_in_source"]) == 4
        committed = resolve_project_maps(_PV_ROOTS).component_map.data
        assert got["rows"] == committed, "커밋된 PV 맵이 문서에서 다시 만든 것과 다르다"
