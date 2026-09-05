"""준비 게이트 R28 — 게이트↔생성 파일 정합(P-4) · 죽은 공시(P-5) · 실측 후 판정(P-6).

2026-09-03 감사가 찾은 것을 회귀로 고정한다. 셋 다 "게이트가 이름 대는 것 ≠ 실제로
쓰이는 것" 또는 "미측정을 0/통과로 접기" 의 결함이다:

- P-4① 통합 Summary 양식: 라우터는 3키를 **읽힐 때까지** 순회하는데 게이트는 첫 키만
  봤다 — 1순위만 낡으면 거짓 차단(생성은 성공).
- P-4② 템플릿 우선순위: 게이트는 `doc_paths` 전 키 → 레지스트리 전 키, 생성 요청은
  전용키(설정→레지스트리) → 공용키. `doc_paths.template=A` + `linked.uds_template=B` 면
  게이트 A ✓, 생성 B.
- P-5① 직전 실행 모드를 `dropped>0` 로 **추론** — `drop` 인데 지운 게 0이면 keep 처럼 읽힘.
  ② 화면이 안 읽는 키를 "화면이 읽는 키로 낸다" 는 주석 아래에서 냈다.
  ③ 패널의 `key_hits`/`map_entries` 줄은 서버 발행 0 이라 영구 dead.
- P-6① UDS 분류 상한은 사용자 값으로 재계산하지 않았다(STS/SITS 는 한다).
  ② `by_grade=={}` 를 "ASIL D 없음" 으로 단언. ③ `@asil` 1건이면 ✓.
  ④ `max(units,1)` 로 unit 0개가 ✓. ⑤ "상한 None 으로 잰 것입니다" 문장.
  ⑦ `doc_type` 날것 비교 — `"UDS"` 면 행이 조용히 사라짐.
  ⑨ 종류 미판정 파일에도 같은 확장자 아무 파일이나 개정본으로 제안.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routers import docgen_preflight as pf
from backend.routers import swreport
from backend.schemas import ScmLinkedDocs
from backend.services import docgen_last_run as lr
from backend.services import docgen_test_materials as tmod
from backend.services import file_resolver as fr
from backend.services import scm_registry as reg
from backend.services import swut_meta_resolver as meta

client = TestClient(app)
HEADERS = {"X-User": "tester"}
ROOT = Path(__file__).resolve().parents[2]


def _post(payload: dict) -> dict:
    r = client.post("/api/docgen/preflight", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    return r.json()


def _step(data: dict, step_id: str) -> dict | None:
    return next((s for s in data["steps"] if s["id"] == step_id), None)


def _entry(tmp_path: Path, **linked: str):
    return SimpleNamespace(linked_docs=ScmLinkedDocs(**linked), source_root=str(tmp_path),
                           builder_project_id="")


_TM_SKELETON = {
    "sits": {"flows_total": 0, "cap": 120, "headroom": 120, "at_cap_boundary": False,
             "uds_hits": 0, "uds": {}, "sample_flow": None},
    "suts": {"variables": 0, "grounded": 0, "fallback": 0},
}


def _fake_cat_cache(monkeypatch, payload: dict | None) -> None:
    merged = None
    if payload is not None:
        merged = {**payload}
        for key, base_val in _TM_SKELETON.items():
            merged[key] = {**base_val, **(payload.get(key) or {})}
    monkeypatch.setattr(pf._tm, "has_cached", lambda *_a, **_k: merged is not None)
    monkeypatch.setattr(pf._tm, "cached", lambda *_a, **_k: merged)


def _with_materials(tmp_path: Path, materials: dict, doc_type: str) -> dict:
    import time as _time
    root = str(tmp_path)
    tmod.clear_cache()
    tmod._CACHE[tmod._key(root)] = (_time.time(), materials)
    try:
        return _post({"doc_type": doc_type, "source_root": root})
    finally:
        tmod.clear_cache()


class _ProbeResolver:
    """`exists` 는 주어진 집합만 True. 게이트가 어느 경로를 물었는지 기록한다."""

    mode = "local"

    def __init__(self, existing: set[str]) -> None:
        self.existing = {str(Path(p)) for p in existing}
        self.asked: list[str] = []

    def exists(self, path: str) -> bool:
        self.asked.append(str(path))
        return str(Path(path)) in self.existing

    def is_dir(self, path: str) -> bool:
        return False

    def list_dir(self, path: str, pattern: str = "*", recursive: bool = False,
                 include_dirs: bool = False):
        return []


# ── P-4①: 통합 Summary 양식은 라우터와 같은 3키를 같은 순서로 ─────────────────

def test_report_template_keys_come_from_the_router_constant() -> None:
    """복제가 아니라 **가져온다** — 라우터가 키를 늘리면 게이트도 같이 는다."""
    assert pf._report_template_keys("swreport") == tuple(swreport._TEMPLATE_CONFIG_KEYS)
    assert pf._report_template_keys("SwReport ") == tuple(swreport._TEMPLATE_CONFIG_KEYS)
    assert pf._report_template_keys("swut") == (pf._TEST_REPORT_TEMPLATE_KEY["swut"],)
    assert pf._report_template_keys("uds") == ()


def _swreport_template_step(monkeypatch, tmp_path: Path, template_paths: dict,
                            existing: set[str]) -> dict:
    monkeypatch.setattr(meta, "load_meta_from_config_strict",
                        lambda _pid: {"template_paths": template_paths})
    resolver = _ProbeResolver(existing)
    monkeypatch.setattr(fr, "get_resolver", lambda: resolver)
    data = _post({"doc_type": "swreport", "form": {"project_id": "P1"}})
    step = _step(data, "report_template")
    assert step is not None, "양식 단계가 없다"
    return step


def test_swreport_falls_through_to_the_second_key_like_the_router(monkeypatch, tmp_path) -> None:
    """1순위 `es95411_template` 이 낡고 2순위가 멀쩡하면 **ok** — 예전엔 `missing` 차단."""
    k1, k2, _k3 = swreport._TEMPLATE_CONFIG_KEYS
    stale = tmp_path / "old_es95411.xlsm"
    good = tmp_path / "tr_report.xlsm"
    step = _swreport_template_step(monkeypatch, tmp_path,
                                   {k1: str(stale), k2: str(good)}, {str(good)})
    assert step["state"] == "ok", step
    assert step["value"] == str(good)
    assert k2 in step.get("reason", ""), "어느 폴백 키를 썼는지 말하지 않았다"


def test_swreport_first_key_readable_needs_no_fallback_note(monkeypatch, tmp_path) -> None:
    k1, k2, _k3 = swreport._TEMPLATE_CONFIG_KEYS
    good = tmp_path / "es.xlsm"
    other = tmp_path / "tr.xlsm"
    step = _swreport_template_step(monkeypatch, tmp_path,
                                   {k1: str(good), k2: str(other)}, {str(good), str(other)})
    assert step["state"] == "ok" and step["value"] == str(good)
    assert not step.get("reason"), step


def test_swreport_all_three_stale_is_missing_with_the_first_key_named(monkeypatch, tmp_path) -> None:
    k1, k2, k3 = swreport._TEMPLATE_CONFIG_KEYS
    step = _swreport_template_step(
        monkeypatch, tmp_path,
        {k1: str(tmp_path / "a.xlsm"), k2: str(tmp_path / "b.xlsm"), k3: str(tmp_path / "c.xlsm")},
        set())
    assert step["state"] == "missing", step
    assert step["value"] == str(tmp_path / "a.xlsm")


def test_swreport_nothing_registered_names_the_fallback_keys(monkeypatch, tmp_path) -> None:
    k1, k2, k3 = swreport._TEMPLATE_CONFIG_KEYS
    step = _swreport_template_step(monkeypatch, tmp_path, {}, set())
    assert step["state"] == "missing", step
    reason = step.get("reason", "")
    assert k1 in reason and k2 in reason and k3 in reason, reason


def test_form_template_wins_over_missing_config_keys(monkeypatch, tmp_path) -> None:
    """(a) 폼 지정 + config 전무 → **ok**(라우터는 폼 경로를 연다). 실측 HDPDM01 이 이 경우다."""
    good = tmp_path / "form_es95411.xlsm"
    monkeypatch.setattr(meta, "load_meta_from_config_strict",
                        lambda _pid: {"template_paths": {}})
    monkeypatch.setattr(fr, "get_resolver", lambda: _ProbeResolver({str(good)}))
    step = _step(_post({"doc_type": "swreport",
                        "form": {"project_id": "P1", "template_path": str(good)}}), "report_template")
    assert step["state"] == "ok", step
    assert step["value"] == str(good)
    assert "template_path" in step["reason"], step["reason"]


def test_form_template_wins_over_registered_config_keys(monkeypatch, tmp_path) -> None:
    """(b) 폼 지정 + config 존재 → 폼이 이긴다. config 키를 이름 대면 라우터와 다른 파일이다."""
    k1 = swreport._TEMPLATE_CONFIG_KEYS[0]
    cfg = tmp_path / "config_es.xlsm"
    form = tmp_path / "form_es.xlsm"
    monkeypatch.setattr(meta, "load_meta_from_config_strict",
                        lambda _pid: {"template_paths": {k1: str(cfg)}})
    monkeypatch.setattr(fr, "get_resolver", lambda: _ProbeResolver({str(cfg), str(form)}))
    step = _step(_post({"doc_type": "swreport",
                        "form": {"project_id": "P1", "template_path": str(form)}}), "report_template")
    assert step["state"] == "ok" and step["value"] == str(form), step
    assert k1 not in step["reason"]


def test_missing_form_template_is_reported_as_the_form_value(monkeypatch, tmp_path) -> None:
    """폼 경로가 없는 파일이면 그 사실을 **폼 값**으로 말한다 — config 로 폴백하지 않는다(라우터도 안 한다)."""
    k1 = swreport._TEMPLATE_CONFIG_KEYS[0]
    cfg = tmp_path / "config_es.xlsm"
    monkeypatch.setattr(meta, "load_meta_from_config_strict",
                        lambda _pid: {"template_paths": {k1: str(cfg)}})
    monkeypatch.setattr(fr, "get_resolver", lambda: _ProbeResolver({str(cfg)}))
    gone = tmp_path / "gone.xlsm"
    step = _step(_post({"doc_type": "swreport",
                        "form": {"project_id": "P1", "template_path": str(gone)}}), "report_template")
    assert step["state"] == "missing", step
    assert step["value"] == str(gone)
    assert "template_path" in step["reason"]


@pytest.mark.parametrize("doc_type,field", sorted(pf._REPORT_TEMPLATE_FORM_KEY.items()))
def test_form_template_key_is_a_real_request_field(doc_type, field) -> None:
    """폼 키 표는 라우터 request schema 의 실제 필드여야 한다 — 이름이 갈리면 폼 값이 조용히 무시된다."""
    from backend import schemas as S
    model = {"swut": S.SwUTBuildRequest, "sutr": S.SwUTBuildRequest, "swutcr": S.SwUTBuildRequest,
             "swit": S.SwITBuildRequest, "sitr": S.SwITBuildRequest, "switcr": S.SwITBuildRequest,
             "swreport": S.SwReportBuildRequest}[doc_type]
    assert field in model.model_fields, (doc_type, field)


def test_all_candidates_are_named_when_every_key_fails(monkeypatch, tmp_path) -> None:
    """라우터는 "시도한 후보" 전부를 말한다 — 게이트가 첫 것만 보고하면 덜 말하는 것(리뷰 W4)."""
    k1, k2, _k3 = swreport._TEMPLATE_CONFIG_KEYS
    step = _swreport_template_step(monkeypatch, tmp_path,
                                   {k1: str(tmp_path / "a.xlsm"), k2: str(tmp_path / "b.xlsm")}, set())
    assert step["state"] == "missing"
    assert "시도한 후보" in step["reason"] and k2 in step["reason"], step["reason"]


def test_swut_single_key_is_unchanged(monkeypatch, tmp_path) -> None:
    """키가 하나인 문서는 폴백 문구가 없다 — 없는 폴백을 있는 것처럼 말하지 않는다."""
    monkeypatch.setattr(meta, "load_meta_from_config_strict",
                        lambda _pid: {"template_paths": {}})
    monkeypatch.setattr(fr, "get_resolver", lambda: _ProbeResolver(set()))
    step = _step(_post({"doc_type": "swut", "form": {"project_id": "P1"}}), "report_template")
    assert step["state"] == "missing"
    assert "폴백 키" not in step.get("reason", "")


# ── P-4②: 템플릿 우선순위는 생성 요청(프론트)과 lockstep ─────────────────────

def test_registry_specific_template_beats_configured_shared_template(tmp_path, monkeypatch) -> None:
    """`doc_paths.template=A` + 레지스트리 `uds_template=B` → 게이트도 **B** 를 본다.

    생성 요청은 `docPaths[tplKey] || linkedDocs[tplKey] || docPaths.template || …` 이라
    B 를 연다. 예전 게이트는 doc_paths 를 전부 먼저 봐 A 에 ✓ 를 줬다.
    """
    shared = tmp_path / "A_shared.docx"
    specific = tmp_path / "B_uds.docx"
    shared.write_bytes(b"x")
    specific.write_bytes(b"x")
    monkeypatch.setattr(reg, "get_registry_entry",
                        lambda _id: _entry(tmp_path, uds_template=str(specific)))
    data = _post({"doc_type": "uds", "scm_id": "t", "source_root": str(tmp_path),
                  "doc_paths": {"template": str(shared)}})
    step = _step(data, "template")
    assert step is not None and step["value"] == str(specific), step


def test_configured_specific_template_still_beats_registry_specific(tmp_path, monkeypatch) -> None:
    a = tmp_path / "cfg_uds.docx"
    b = tmp_path / "reg_uds.docx"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    monkeypatch.setattr(reg, "get_registry_entry",
                        lambda _id: _entry(tmp_path, uds_template=str(b)))
    data = _post({"doc_type": "uds", "scm_id": "t", "source_root": str(tmp_path),
                  "doc_paths": {"uds_template": str(a)}})
    assert _step(data, "template")["value"] == str(a)


def test_shared_template_is_used_only_when_no_specific_anywhere(tmp_path, monkeypatch) -> None:
    shared = tmp_path / "shared.docx"
    shared.write_bytes(b"x")
    monkeypatch.setattr(reg, "get_registry_entry", lambda _id: _entry(tmp_path))
    data = _post({"doc_type": "uds", "scm_id": "t", "source_root": str(tmp_path),
                  "doc_paths": {"template": str(shared)}})
    assert _step(data, "template")["value"] == str(shared)


def test_frontend_template_priority_is_the_documented_order() -> None:
    """프론트가 순서를 바꾸면 여기서 드러난다 — 게이트 `_pick` 분기와 lockstep."""
    src = (ROOT / "frontend-v2/src/components/sections/DocGenSection.jsx").read_text(encoding="utf-8")
    assert ("(tplKey && (docPaths[tplKey] || linkedDocs[tplKey]))\n"
            "        || docPaths.template || linkedDocs.template") in src, (
        "생성 요청의 템플릿 우선순위가 바뀌었다 — docgen_preflight `_pick` 분기를 같이 고칠 것")


# ── P-5①②: 직전 실행 — 모드는 기록값, 미독 키는 발행하지 않는다 ────────────────

def _fake_last_run(monkeypatch, **over):
    run = {
        "when": "2026-09-01", "stage": "docx", "status": "success", "artifact": "x.docx",
        "artifact_exists": True, "elapsed_seconds": 40.0, "budget_seconds": 7200,
        "timeout_seconds": None, "cause": "", "measurable": True,
        "payload_functions": 10, "matched_functions": 10,
        "empty_heading_count": 0, "dropped_heading_count": 0,
        "unmatched_headings_mode": "drop", "unmatched_payload_count": 0,
        "checkpoint": "x.docx.stage.json",
    }
    run.update(over)
    monkeypatch.setattr(lr, "last_uds_run", lambda *_a, **_k: run)


def test_drop_mode_with_zero_dropped_is_still_reported_as_drop(tmp_path, monkeypatch) -> None:
    """`drop` 인데 지운 게 0개 — 추론(`dropped>0`)으로는 keep 처럼 읽히던 케이스."""
    _fake_last_run(monkeypatch, unmatched_headings_mode="drop", dropped_heading_count=0)
    data = _post({"doc_type": "uds", "source_root": str(tmp_path),
                  "cache_root": str(tmp_path), "job_url": "http://j/job/x/"})
    step = _step(data, "unmatched_headings")
    assert step is not None
    assert "`drop`" in step["reason"], step["reason"]
    assert "0개" in step["reason"], step["reason"]
    last = _step(data, "last_run")
    assert last is not None and last["measured"]["unmatched_mode"] == "drop"


def test_drop_mode_without_a_count_does_not_invent_zero(tmp_path, monkeypatch) -> None:
    """모드는 기록됐는데 지운 수가 없다(옛/부분 기록) — "0개를 지웠습니다" 는 지어낸 수다(리뷰 W3)."""
    _fake_last_run(monkeypatch, unmatched_headings_mode="drop", dropped_heading_count=None,
                   empty_heading_count=3)
    data = _post({"doc_type": "uds", "source_root": str(tmp_path),
                  "cache_root": str(tmp_path), "job_url": "http://j/job/x/"})
    reason = _step(data, "unmatched_headings")["reason"]
    assert "지운 수는 기록되지 않았습니다" in reason, reason
    assert "0개" not in reason, reason
    assert "**3개**" in reason, reason          # drop 이어도 남은 빈 서식은 말한다(리뷰 I6)


def test_keep_mode_reports_empty_headings_not_drop(tmp_path, monkeypatch) -> None:
    _fake_last_run(monkeypatch, unmatched_headings_mode="keep", empty_heading_count=7,
                   dropped_heading_count=None)
    data = _post({"doc_type": "uds", "source_root": str(tmp_path),
                  "cache_root": str(tmp_path), "job_url": "http://j/job/x/"})
    step = _step(data, "unmatched_headings")
    assert "**7개**" in step["reason"], step["reason"]
    assert "`drop`" not in step["reason"]


def test_last_run_measured_carries_only_keys_someone_reads(tmp_path, monkeypatch) -> None:
    """`status`/`stage`/`artifact`/`artifact_exists` 는 아무도 안 읽던 쓰기 전용 관측량이었다."""
    _fake_last_run(monkeypatch)
    data = _post({"doc_type": "uds", "source_root": str(tmp_path),
                  "cache_root": str(tmp_path), "job_url": "http://j/job/x/"})
    m = _step(data, "last_run")["measured"]
    assert not {"status", "stage", "artifact", "artifact_exists"} & set(m), m
    assert {"empty_headings", "dropped_headings", "unmatched_mode",
            "elapsed_seconds", "budget_seconds"} <= set(m), m


# ── P-5③: SITS 추적성 재료 — 패널이 그리는 이름으로 낸다 ──────────────────────

def test_sits_related_source_emits_key_hits_and_map_entries(tmp_path) -> None:
    mats = {
        "ok": True, "functions": 10, "elapsed_s": 0.1,
        "sits": {"flows_total": 9, "cap": 120, "headroom": 111, "at_cap_boundary": False,
                 "sds_map_entries": 763, "sds_reason": "", "sds_lookups": 84,
                 "sds_key_hits": 38, "sds_swcom_hits": 0, "uds_hits": 9,
                 "uds": {"on": True}, "uds_lookups": 84, "uds_related_ids": 12,
                 "sample_flow": None},
        "suts": {"variables": 0, "grounded": 0, "fallback": 0, "fallback_samples": []},
    }
    step = _step(_with_materials(tmp_path, mats, "sits"), "sits_related_source")
    assert step is not None
    assert step["measured"]["key_hits"] == 38, step["measured"]
    assert step["measured"]["map_entries"] == 763, step["measured"]


# ── P-6①: UDS 분류 상한은 사용자 값으로 재계산 ──────────────────────────────────

_CAT = {
    "ok": True,
    "uds_category_caps": {
        "measured": True, "cap": 120, "any_truncated": True,
        "truncated": {
            "macros": {"total": 3881, "cap": 120, "dropped": 3761},
            "type_defs": {"total": 130, "cap": 120, "dropped": 10},
        },
    },
}


def test_raising_the_category_cap_past_every_total_is_ok(tmp_path, monkeypatch) -> None:
    _fake_cat_cache(monkeypatch, _CAT)
    step = _step(_post({"doc_type": "uds", "source_root": str(tmp_path),
                        "caps": {"max_items_per_category": 4000}}), "cap_max_items_per_category")
    assert step["state"] == "ok", step
    assert step["measured"]["dropped_total"] == 0
    # `truncated` 도 같은 상한으로 다시 세어 실린다 — 한 응답에 옛 dropped 와 새 dropped_total 이
    # 갈리면 안 된다(리뷰 X6). 캐시 객체가 아니라 **새 dict** 다(리뷰 I2).
    assert step["measured"]["truncated"]["macros"] == {"total": 3881, "cap": 4000, "dropped": 0}
    assert "suggested" not in step["measured"]
    assert "4000" in step["reason"] and "120" in step["reason"], step["reason"]


def test_raising_the_category_cap_partway_recounts_what_still_drops(tmp_path, monkeypatch) -> None:
    """상한 200: macros 3881-200=3681, type_defs 130 은 전부 담긴다 → 3681."""
    _fake_cat_cache(monkeypatch, _CAT)
    step = _step(_post({"doc_type": "uds", "source_root": str(tmp_path),
                        "caps": {"max_items_per_category": 200}}), "cap_max_items_per_category")
    assert step["state"] == "degraded", step
    assert step["measured"]["dropped_total"] == 3681, step["measured"]
    assert step["measured"]["truncated"]["macros"]["dropped"] == 3681
    assert step["measured"]["truncated"]["type_defs"]["dropped"] == 0
    assert "3681" in step["reason"] and "3771" not in step["reason"], step["reason"]


def test_lowering_the_category_cap_is_not_recounted(tmp_path, monkeypatch) -> None:
    """내리면 절단되지 않던 분류의 총수를 몰라 재계산 불가 — 옛 상한으로 잰 사실만 말한다."""
    _fake_cat_cache(monkeypatch, _CAT)
    step = _step(_post({"doc_type": "uds", "source_root": str(tmp_path),
                        "caps": {"max_items_per_category": 50}}), "cap_max_items_per_category")
    assert step["state"] == "degraded"
    assert step["measured"]["dropped_total"] == 3771
    assert step["measured"]["truncated"]["macros"]["dropped"] == 3761   # 옛 실측 그대로
    assert "상한 120 으로 잰" in step["reason"], step["reason"]


def test_same_cap_as_measured_keeps_the_measurement_verbatim(tmp_path, monkeypatch) -> None:
    """`picked == _at` 은 재계산도 부가 문장도 없다 — 실측이 곧 답이다(리뷰 C2 회귀·I5 노이즈)."""
    _fake_cat_cache(monkeypatch, _CAT)
    step = _step(_post({"doc_type": "uds", "source_root": str(tmp_path),
                        "caps": {"max_items_per_category": 120}}), "cap_max_items_per_category")
    assert step["measured"]["dropped_total"] == 3771
    assert "재계산" not in step["reason"] and "으로 잰" not in step["reason"], step["reason"]


def test_recount_respects_per_category_cap_multiplier(tmp_path, monkeypatch) -> None:
    """생성기는 `global_data`/`macro_defs` 에 `max_items * 2` 를 쓴다 — 배수를 무시하면 3배 과대보고.

    리뷰 C2 실증: total 300 / cap 240 / dropped 60 (측정 상한 120) 에 사용자 150 →
    실제 cap 300 → 0개. 옛 산식은 150개.
    """
    cat = {"ok": True, "uds_category_caps": {
        "measured": True, "cap": 120, "any_truncated": True,
        "truncated": {"macro_defs": {"total": 300, "cap": 240, "dropped": 60}}}}
    _fake_cat_cache(monkeypatch, cat)
    step = _step(_post({"doc_type": "uds", "source_root": str(tmp_path),
                        "caps": {"max_items_per_category": 150}}), "cap_max_items_per_category")
    assert step["state"] == "ok", step
    assert step["measured"]["dropped_total"] == 0
    assert step["measured"]["truncated"]["macro_defs"] == {"total": 300, "cap": 300, "dropped": 0}
    step = _step(_post({"doc_type": "uds", "source_root": str(tmp_path),
                        "caps": {"max_items_per_category": 130}}), "cap_max_items_per_category")
    assert step["state"] == "degraded"
    assert step["measured"]["dropped_total"] == 40          # 300 - 130*2


def test_unmeasured_total_is_not_folded_into_zero(tmp_path, monkeypatch) -> None:
    """`total: None` 인 분류가 있으면 재계산을 **포기**한다 — 0 으로 접으면 false green(리뷰 W1)."""
    cat = {"ok": True, "uds_category_caps": {
        "measured": True, "cap": 120, "any_truncated": True,
        "truncated": {"macros": {"total": None, "cap": 120, "dropped": 3761}}}}
    _fake_cat_cache(monkeypatch, cat)
    step = _step(_post({"doc_type": "uds", "source_root": str(tmp_path),
                        "caps": {"max_items_per_category": 200}}), "cap_max_items_per_category")
    assert step["state"] == "degraded", step
    assert step["measured"]["dropped_total"] == 3761
    assert "상한 120 으로 잰" in step["reason"], step["reason"]


def test_recount_helper_contract() -> None:
    tr = {"a": {"total": 300, "cap": 240, "dropped": 60}, "b": {"total": 130, "cap": 120, "dropped": 10}}
    assert pf._recount_category_truncation(tr, 120, 150) == (
        {"a": {"total": 300, "cap": 300, "dropped": 0}, "b": {"total": 130, "cap": 150, "dropped": 0}}, 0)
    assert pf._recount_category_truncation(tr, 120, 125)[1] == 50 + 5
    assert pf._recount_category_truncation({}, 120, 150) is None
    assert pf._recount_category_truncation(tr, None, 150) is None
    assert pf._recount_category_truncation(tr, 0, 150) is None
    assert pf._recount_category_truncation({"a": {"total": "300", "cap": 240}}, 120, 150) is None
    assert pf._recount_category_truncation({"a": {"total": True, "cap": 240}}, 120, 150) is None


# ── P-6⑤: 어느 상한으로 쟀는지 모르면 그 문장을 쓰지 않는다 ───────────────────

def test_unknown_measured_cap_never_prints_none(tmp_path, monkeypatch) -> None:
    box = {**_CAT["uds_category_caps"]}
    box.pop("cap")
    _fake_cat_cache(monkeypatch, {"ok": True, "uds_category_caps": box})
    step = _step(_post({"doc_type": "uds", "source_root": str(tmp_path),
                        "caps": {"max_items_per_category": 4000}}), "cap_max_items_per_category")
    assert step["state"] == "degraded"
    assert "None" not in step["reason"], step["reason"]


# ── P-6②: 등급 0건은 "ASIL D 없음" 이 아니다 ──────────────────────────────────

def test_mcdc_risk_is_unknown_when_no_grade_was_read() -> None:
    assert pf._mcdc_risk({"suts_asil": {"measured": True, "by_grade": {}}}, 24, 30) is None
    assert pf._mcdc_risk({"suts_asil": {"measured": True, "by_grade": None}}, 24, 30) is None
    assert pf._mcdc_risk({"suts_asil": {"measured": False}}, 24, 30) is None
    got = pf._mcdc_risk({"suts_asil": {"measured": True, "by_grade": {"QM": 3}}}, 24, 30)
    assert got is not None and got["asil_d"] == 0


# ── P-6③: @asil 태그는 비율로 판정 ───────────────────────────────────────────

def _fake_cov(monkeypatch, functions: int, asil_filled: int) -> None:
    res = {
        "scanned_files": 3, "functions": functions, "partial": False, "max_files": 300,
        "elapsed_s": 0.1, "cached": True,
        "description": {"filled": functions, "substantive": functions},
        "asil": {"filled": asil_filled}, "related": {"filled": 0},
        "substantive_gap": 0, "samples": [],
    }
    monkeypatch.setattr(pf._cov, "has_cached", lambda *_a, **_k: True)
    monkeypatch.setattr(pf._cov, "measure", lambda *_a, **_k: res)


@pytest.mark.parametrize("functions,filled,state", [
    (435, 1, "degraded"),      # 실측 형태 — 1건이면 ✓ 였다
    (10, 4, "degraded"),
    (10, 5, "ok"),
    (10, 10, "ok"),
    (0, 0, "unmeasured"),      # 함수 0개 = 모름 — "0/0 결함" 이 아니다(리뷰 W6)
])
def test_asil_tags_judged_by_ratio(tmp_path, functions, filled, state, monkeypatch) -> None:
    _fake_cov(monkeypatch, functions, filled)
    step = _step(_post({"doc_type": "uds", "source_root": str(tmp_path)}), "asil_tags")
    assert step is not None
    assert step["state"] == state, step
    assert step["measured"] == {"value": filled, "of": functions}
    if state == "degraded":
        assert f"{filled}/{functions}" in step["reason"], step["reason"]


# ── P-6④: unit 0개는 ✓ 가 아니다 ───────────────────────────────────────────

def _suts_inputs_step(tmp_path, units: int, without: int) -> dict:
    mats = {
        "ok": True, "functions": 10, "elapsed_s": 0.1,
        "sits": {"flows_total": 0, "cap": 120, "headroom": 120, "at_cap_boundary": False,
                 "sds_map_entries": 0, "sds_reason": "", "sds_lookups": 0,
                 "sds_key_hits": 0, "sds_swcom_hits": 0, "sample_flow": None},
        "suts": {"variables": 0, "grounded": 0, "fallback": 0, "fallback_samples": []},
        "suts_inputs": {"measured": True, "units": units, "units_without_input": without,
                        "reference_without_input": 30, "reference_units": 100,
                        "causes": {}, "cause_samples": {}},
    }
    step = _step(_with_materials(tmp_path, mats, "suts"), "suts_inputs")
    assert step is not None
    return step


def test_zero_units_is_unmeasured_not_ok(tmp_path) -> None:
    step = _suts_inputs_step(tmp_path, units=0, without=0)
    assert step["state"] == "unmeasured", step
    assert "unit 을 하나도" in step["reason"], step["reason"]


def test_zero_variables_is_unmeasured_with_a_reason(tmp_path) -> None:
    """`suts_types` — 변수 0개는 침묵 degraded 가 아니라 사유 있는 unmeasured(리뷰 W6)."""
    mats = {
        "ok": True, "functions": 10, "elapsed_s": 0.1,
        "sits": {"flows_total": 0, "cap": 120, "headroom": 120, "at_cap_boundary": False,
                 "sds_map_entries": 0, "sds_reason": "", "sds_lookups": 0,
                 "sds_key_hits": 0, "sds_swcom_hits": 0, "sample_flow": None},
        "suts": {"variables": 0, "grounded": 0, "fallback": 0, "fallback_samples": []},
    }
    step = _step(_with_materials(tmp_path, mats, "suts"), "suts_types")
    assert step is not None and step["state"] == "unmeasured", step
    assert "하나도" in step["reason"], step["reason"]


def test_units_present_keeps_the_ratio_judgement(tmp_path) -> None:
    assert _suts_inputs_step(tmp_path, units=100, without=10)["state"] == "ok"
    assert _suts_inputs_step(tmp_path, units=100, without=50)["state"] == "degraded"


# ── P-6⑦: doc_type 은 입구에서 정규화 ──────────────────────────────────────────

@pytest.mark.parametrize("raw", ["UDS", " uds ", "Uds"])
def test_doc_type_case_and_whitespace_do_not_drop_rows(tmp_path, raw) -> None:
    canonical = {s["id"] for s in _post({"doc_type": "uds", "source_root": str(tmp_path)})["steps"]}
    got = _post({"doc_type": raw, "source_root": str(tmp_path)})
    assert got["unknown_doc_type"] is False
    assert {s["id"] for s in got["steps"]} == canonical


def test_questions_endpoint_reports_the_normalized_doc_type(tmp_path) -> None:
    """`/questions` 도 같은 정규화 — 아니면 응답 `doc_type` 과 캐시 키가 두 벌(리뷰 I1)."""
    r = client.post("/api/docgen/questions", json={"doc_type": "UDS", "source_root": str(tmp_path)},
                    headers=HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["doc_type"] == "uds"


# ── W7: `_pick` 은 단일 키다 — 다중키 시맨틱이 되돌아오면 P-4② 결함이 재도입된다 ──

def test_pick_is_single_key_only() -> None:
    from tests.unit._source_probe import source_of
    src = source_of(pf._resolve_inputs_with_origin)
    assert "def _pick(key: str)" in src, "_pick 이 다시 다중 키를 받는다 — 우선순위 결함(P-4②) 재도입 위험"
    assert "def _pick(*keys" not in src


# ── P-6⑨: 종류를 못 가르는 파일엔 개정본을 제안하지 않는다 ─────────────────────

class _ListingResolver:
    mode = "local"

    def __init__(self, names):
        self.names = list(names)

    def exists(self, path: str) -> bool:
        return False

    def list_dir(self, path: str, pattern: str = "*", recursive: bool = False,
                 include_dirs: bool = False):
        return [str(Path(path) / n) for n in self.names]


def test_no_revision_suggested_for_unclassifiable_files() -> None:
    r = _ListingResolver(["(KJPDS02_SwTP) Software Test Plan_v2.01_R.docx"])
    assert pf._suggest_revision(r, "U:/x/(KJPDS02_SwTP) Software Test Plan_v1.04.docx") == ""
    assert pf._suggest_revision(r, "U:/x/uds_template.docx") == ""


def test_revision_is_still_suggested_for_srs_and_sds() -> None:
    r = _ListingResolver(["(KJPDS02_SwRS) Software Requirements Specification_v3.01_R.docx"])
    got = pf._suggest_revision(r, "U:/x/(KJPDS02_SwRS) Software Requirements Specification_v2.03.docx")
    assert got == "(KJPDS02_SwRS) Software Requirements Specification_v3.01_R.docx"
