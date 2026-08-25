"""문서 생성 preflight — **state 를 서로 접지 않는지**가 이 파일의 본체다.

계획서가 못박은 규약 중 회귀로 고정해야 하는 것:

1. `unknown`(확인 못 함)을 `missing`(확인했고 없음)으로 접지 않는다.
2. `degraded`(있지만 부족)로 **생성을 막지 않는다** — 막으면 실측상 아무도 문서를 못 만든다.
3. 재지 못한 값을 `0` 으로 그리지 않는다.
4. **칸 수를 예고하지 않는다** — 사슬은 단계별 가용성만 낸다.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.services import docgen_comment_coverage as cov
from backend.services import docgen_requirements as req

client = TestClient(app)
HEADERS = {"X-User": "tester"}


def _post(payload: dict) -> dict:
    r = client.post("/api/docgen/preflight", json=payload, headers=HEADERS)
    assert r.status_code == 200, r.text
    return r.json()


def _step(data: dict, step_id: str) -> dict | None:
    return next((s for s in data["steps"] if s["id"] == step_id), None)


# ── 입력 요구 표 ────────────────────────────────────────────────────────────

def test_every_doc_type_has_requirements() -> None:
    for dt in req.doc_types():
        spec = req.requirements_for(dt)
        assert spec["label"], f"{dt}: 라벨 없음"
        assert spec["handler"], f"{dt}: 핸들러 경로 없음"
        assert not spec.get("unknown_doc_type")


def test_unknown_doc_type_is_reported_not_invented() -> None:
    """모르는 종류를 아는 척하지 않는다."""
    data = _post({"doc_type": "nonexistent"})
    assert data["unknown_doc_type"] is True
    assert data["steps"] == [] or all(s["phase"] != "input" for s in data["steps"])


def test_optional_inputs_carry_their_effect() -> None:
    """선택 입력은 **없으면 무슨 일이 생기는지** 를 반드시 달고 있어야 한다.

    사유 없는 '선택 항목' 은 사용자에게 아무 정보도 주지 않는다.
    """
    for dt in req.doc_types():
        spec = req.requirements_for(dt)
        for key, effect in (spec["optional"] or {}).items():
            assert effect.strip(), f"{dt}/{key}: 영향 문장이 비어 있다"


# ── state 비접힘 ────────────────────────────────────────────────────────────

def test_missing_source_root_blocks(tmp_path: Path) -> None:
    data = _post({"doc_type": "uds", "source_root": str(tmp_path / "nope")})
    step = _step(data, req.IN_SOURCE_ROOT)
    assert step is not None
    assert step["state"] == "missing"
    assert data["verdict"] == "blocked"


def test_present_source_root_is_ok(tmp_path: Path) -> None:
    data = _post({"doc_type": "suts", "source_root": str(tmp_path)})
    step = _step(data, req.IN_SOURCE_ROOT)
    assert step is not None and step["state"] == "ok"
    # SUTS 는 소스만 필수 → 필수 결핍으로 막히지 않는다.
    assert data["verdict"] != "blocked"


def test_degraded_does_not_block(tmp_path: Path) -> None:
    """`degraded` 는 차단이 아니다 — 막으면 주석·타입이 완전한 프로젝트가 없어 아무도 못 만든다."""
    data = _post({"doc_type": "suts", "source_root": str(tmp_path)})
    assert data["verdict"] != "blocked"


def test_unmeasured_is_not_zero(tmp_path: Path) -> None:
    """소스 주석을 아직 안 쟀으면 `unmeasured` 이고 **측정값을 싣지 않는다**.

    `0` 으로 그리면 "주석이 하나도 없다" 로 읽힌다 — 실제로는 안 재봤을 뿐이다.
    """
    cov.clear_cache()
    data = _post({"doc_type": "suts", "source_root": str(tmp_path)})
    step = _step(data, "comment_coverage")
    assert step is not None
    assert step["state"] == "unmeasured"
    assert "measured" not in step, "재지 못했는데 측정값을 실었다"
    assert step["reason"], "사유 없이 unmeasured 로만 두면 화면이 이유를 말할 수 없다"


# ── 사슬 ────────────────────────────────────────────────────────────────────

def test_chain_reports_availability_not_cell_counts(tmp_path: Path) -> None:
    """사슬은 **단계별 가용성**만 낸다. 칸 수를 예고하면 거짓이 된다.

    출처는 '후보 집합 + 강도 우선 덮어쓰기' 구조이고 `module_inherit` 이 모듈 전체로
    번지므로 입력 유무만으로 최종 칸 수를 계산할 수 없다.
    """
    data = _post({"doc_type": "uds", "source_root": str(tmp_path)})
    step = _step(data, "chain_asil")
    assert step is not None
    assert "chain" in step
    for row in step["chain"]:
        assert row["grounded"] is True, "근거 없는 출처가 사슬 표시에 섞였다"
        assert "have" in row
    # 예측 칸 수를 뜻하는 키가 없어야 한다.
    assert not {"expected_cells", "predicted", "estimate"} & set(step)


def test_chain_marks_unconfirmed_as_none(tmp_path: Path) -> None:
    """확인하지 않은 입력은 `have=None` — `False` 로 접으면 없는 결핍을 말한다."""
    data = _post({"doc_type": "uds", "source_root": str(tmp_path)})
    step = _step(data, "chain_asil")
    assert step is not None
    have_values = {r["source"]: r["have"] for r in step["chain"]}
    # SwDS 경로를 안 줬으므로 '확인했고 없음'(False) 이다.
    assert have_values["sds"] is False
    # 소스 주석은 측정 자체를 안 했으므로 '모름'(None) 이어야 한다.
    assert have_values["comment"] is None


# ── 캡 ──────────────────────────────────────────────────────────────────────

def test_caps_are_decisions_not_deficiencies(tmp_path: Path) -> None:
    """캡은 자료 부족이 아니라 사용자 결정이므로 `decision` phase 여야 한다."""
    data = _post({"doc_type": "sits", "source_root": str(tmp_path)})
    caps = [s for s in data["steps"] if s["id"].startswith("cap_")]
    assert caps, "SITS 는 max_subcases·max_flows 캡이 있다"
    for c in caps:
        assert c["phase"] == "decision"
        assert c["reason"], "캡이 무슨 영향을 주는지 말해야 한다"


def test_cap_exposes_api_vs_generator_default(tmp_path: Path) -> None:
    """API 기본값이 생성기 기본값보다 작다는 사실을 화면이 알 수 있어야 한다.

    SUTS 6 vs 24, SITS 7 vs 14 — 버그가 아니라 의도지만 지금까지 아무도 말하지 않았다.
    """
    data = _post({"doc_type": "suts", "source_root": str(tmp_path)})
    step = _step(data, "cap_max_sequences")
    assert step is not None
    m = step["measured"]
    assert m["api_default"] == 6
    assert m["generator_default"] == 24


# ── verdict 순서 ────────────────────────────────────────────────────────────

def test_verdict_precedence_blocked_over_others(tmp_path: Path) -> None:
    """필수 결핍이 있으면 다른 상태가 뭐든 `blocked` 다."""
    data = _post({"doc_type": "uds", "source_root": str(tmp_path / "missing")})
    assert data["verdict"] == "blocked"


@pytest.mark.parametrize("doc_type", ["uds", "sts", "suts", "sits"])
def test_verdict_never_ready_when_something_unmeasured(doc_type: str, tmp_path: Path) -> None:
    """`unknown`·`degraded` 를 `ready` 로 승격하지 않는다."""
    cov.clear_cache()
    data = _post({"doc_type": doc_type, "source_root": str(tmp_path)})
    states = {s["state"] for s in data["steps"]}
    if "unmeasured" in states or "degraded" in states:
        assert data["verdict"] != "ready"


# ── 주석 실질 판정 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("Function  |", False),                                   # 실측: 양식 라벨만
    ("Function  | #4", False),                                # 구분자 뒤가 너무 짧다
    ("Function  | Executes the buzzer control main function.", True),
    ("", False),
    ("   ", False),
    ("Initializes the EEPROM driver and clears the cache.", True),
])
def test_substantive_description(text: str, expected: bool) -> None:
    """`_is_generic_description` 이 놓치는 '양식 라벨만' 을 잡는다.

    실측(2026-08-10): HDPDM01 은 `comment_desc` 380개 중 **277개가 `'Function  |'`**
    인데 기존 판정이 전부 `high`(신뢰도 1.00)를 줬다.
    """
    assert cov.is_substantive_description(text) is expected


def test_measure_reports_scanned_zero_distinctly(tmp_path: Path) -> None:
    """소스가 없으면 `scanned_files=0` + 사유. `functions=0` 만 보면 구분할 수 없다."""
    res = cov.measure(str(tmp_path / "nope"))
    assert res["scanned_files"] == 0
    assert res["reason"], "사유 없이 0 만 내면 '함수가 없다' 로 읽힌다"


# ── 라이브 검증(2026-08-10)에서 드러난 것들 ────────────────────────────────

@pytest.mark.parametrize("headroom,expect", [
    (-25, "빠집니다"),      # 이미 잘리는 중 — 현재형
    (0, "여유가 없습니다"),   # 경계 — 예고형
])
def test_flow_loss_is_present_tense_when_already_cut(
    headroom: int, expect: str, tmp_path: Path,
) -> None:
    """이미 잘리는 것과 곧 잘릴 것은 다른 말이다.

    라이브(kjpds02_pv)에서 여유가 **-25**(25개가 이미 빠지는 중)인데 "함수가 늘면
    잘리기 시작한다" 는 미래형이 나왔다 — 현재 손실을 예고로 읽게 한다.
    """
    from backend.services import docgen_test_materials as tm

    fake = {
        "ok": True, "functions": 10, "elapsed_s": 0.1,
        "sits": {"flows_total": 145 if headroom < 0 else 120, "cap": 120,
                 "headroom": headroom, "at_cap_boundary": headroom <= 0,
                 "sds_map_entries": 0, "sds_reason": "", "sds_lookups": 0,
                 "sds_key_hits": 0, "sds_swcom_hits": 0, "sample_flow": None},
        "suts": {"variables": 0, "grounded": 0, "fallback": 0, "fallback_samples": []},
    }
    import time as _time

    root = str(tmp_path)          # 실재해야 재료 단계까지 간다(조건부 스킵 = 공허 통과)
    tm.clear_cache()
    # 실제 preflight 를 태운다 — 문구 생성 로직을 테스트가 복제하면 가드가 못 된다.
    tm._CACHE[tm._key(root)] = (_time.time(), fake)
    try:
        data = _post({"doc_type": "sits", "source_root": root})
    finally:
        tm.clear_cache()
    step = _step(data, "sits_flows")
    assert step is not None, "재료 단계에 도달하지 못했다 — 이 테스트가 아무것도 검증하지 못한다"
    assert expect in str(step.get("reason") or "")


def _sits_materials(**over) -> dict:
    base = {
        "ok": True, "functions": 10, "elapsed_s": 0.1,
        "sits": {"flows_total": 10, "cap": 120, "headroom": 110,
                 "at_cap_boundary": False,
                 "sds_map_entries": 763, "sds_reason": "", "sds_lookups": 10,
                 "sds_key_hits": 38, "sds_swcom_hits": 0,   # ← 구조적으로 0
                 "uds": {"on": True, "functions": 1026, "asil_functions": 1003},
                 "uds_lookups": 10, "uds_hits": 9, "uds_related_ids": 27,
                 "related_chain_flows": 5, "related_chain_ids": 12,
                 "req_id_flows": 0, "req_id_total": 0,
                 "sample_flow": None},
        "suts": {"variables": 0, "grounded": 0, "fallback": 0, "fallback_samples": []},
    }
    base["sits"].update(over)
    return base


def test_related_step_judges_on_the_axis_that_fills_the_column(tmp_path: Path) -> None:
    """SwDS 축은 **구조적으로 0** 이라 그걸로 판정하면 영구 빨간불이다.

    실측: 실 SwDS 763항목을 줘도 SwCom 0건인데, 라이브 생성기는 같은 프로젝트에서
    SwUDS 경유로 SwCom **699 토큰**을 채운다. 판정을 SwDS 에 두면 게이트가
    "추적성 열이 합성 ID 만 남습니다" 로 산출물과 **정반대**를 말한다.
    """
    data = _with_materials(tmp_path, _sits_materials(), doc_type="sits")
    step = _step(data, "sits_related_source")
    assert step is not None, "재료 단계에 도달하지 못했다 — 이 테스트가 아무것도 검증 못 한다"
    assert step["state"] == "ok", step
    assert not str(step.get("reason") or ""), step
    # SwDS 0 은 **숨기지 않는다** — 판정에서 뺐을 뿐이다.
    assert step["measured"]["sds_swcom_hits"] == 0, step
    assert step["measured"]["value"] == 9, step


def test_related_step_degrades_and_names_swuds_when_the_axis_is_dark(
        tmp_path: Path) -> None:
    """사유가 **SwUDS** 를 가리켜야 한다 — 예전엔 엉뚱하게 SwDS 를 가리켰다."""
    data = _with_materials(
        tmp_path,
        _sits_materials(uds={"on": False, "reason": "SwUDS 경로가 지정되지 않았습니다"},
                        uds_hits=0, uds_related_ids=0),
        doc_type="sits")
    step = _step(data, "sits_related_source")
    assert step is not None
    assert step["state"] == "degraded", step
    reason = str(step.get("reason") or "")
    assert "SwUDS" in reason, reason
    assert "SwDS 를 읽었지만" not in reason, reason


def test_chain_checks_inputs_beyond_the_requirement_table(tmp_path: Path) -> None:
    """사슬이 참조하는 입력은 **요구 표보다 넓다** — 그래도 확인은 해야 한다.

    UDS 의 요구 표에는 HSIS·UDS문서가 없지만 사슬에는 있다(`local.py:603` HSIS 승격,
    `requirements.py:1660` UDS 직독). 스텝을 안 만든다고 가용성 확인까지 건너뛰면
    사슬이 전부 `?`(모름)로 그려진다 — 실제 사용자 보고: "UDS 부터 보면 ? 가 굉장히 많다".
    """
    hsis = tmp_path / "sig.xlsx"
    udsdoc = tmp_path / "unit.docx"
    hsis.write_bytes(b"x")
    udsdoc.write_bytes(b"x")
    data = _post({
        "doc_type": "uds", "source_root": str(tmp_path),
        "doc_paths": {"hsis": str(hsis), "uds": str(udsdoc)},
    })
    # 스텝은 요구 표대로 — HSIS/UDS 는 UDS 문서의 입력 항목이 아니다.
    assert _step(data, req.IN_HSIS) is None

    chain = {r["source"]: r["have"]
             for s in data["steps"] if s["id"] == "chain_related"
             for r in s["chain"]}
    assert chain.get("hsis") is True, "레지스트리에 있는데 '모름' 으로 그렸다"
    asil = {r["source"]: r["have"]
            for s in data["steps"] if s["id"] == "chain_asil"
            for r in s["chain"]}
    assert asil.get("uds") is True


def test_ai_source_is_resolved_from_config(tmp_path: Path) -> None:
    """AI 출처는 문서가 아니라 **설정**이다 — 확인 가능하면 `?` 로 두지 않는다."""
    data = _post({"doc_type": "uds", "source_root": str(tmp_path)})
    desc = {r["source"]: r["have"]
            for s in data["steps"] if s["id"] == "chain_description"
            for r in s["chain"]}
    # 환경에 따라 True/False 지만 **모름(None)이면 안 된다** — 설정은 읽을 수 있다.
    assert "ai" in desc


@pytest.mark.parametrize("doc_type,key,ext", [
    # ⚠ 확장자가 문서마다 다르다 — UDS 는 python-docx, 시험 규격서는 openpyxl.
    ("uds", "uds_template", ".docx"),
    ("sts", "sts_template", ".xlsm"),
    ("suts", "suts_template", ".xlsm"),
    ("sits", "sits_template", ".xlsm"),
])
def test_template_is_per_document(doc_type: str, key: str, ext: str, tmp_path: Path) -> None:
    """템플릿은 **문서마다 형식이 다르다**(UDS .docx / 시험 규격서 .xlsm).

    예전엔 `ScmLinkedDocs` 에 템플릿 필드가 아예 없어서 프론트가 설정의 공용
    `template` 하나를 UDS 자리와 시험문서 자리에 **같이** 보냈다. 형식이 다르므로
    한쪽은 반드시 틀린다.
    """
    from backend.schemas import ScmLinkedDocs

    assert key in ScmLinkedDocs.model_fields, f"{key} 필드가 없다"

    tpl = tmp_path / f"{key}{ext}"
    tpl.write_bytes(b"x")
    data = _post({"doc_type": doc_type, "source_root": str(tmp_path),
                  "doc_paths": {key: str(tpl)}})
    step = _step(data, "template")
    assert step is not None
    assert step["state"] == "ok", f"{doc_type} 이 {key} 를 못 찾았다"
    assert step["value"] == str(tpl)


def test_uds_requires_a_cached_build(tmp_path: Path) -> None:
    """UDS 는 Jenkins **빌드 캐시**가 있어야 시작한다.

    `_uds_generate_from_paths`(`helpers/uds.py:1504`)가 맨 첫 줄에서 캐시를 찾고 없으면
    `404: cached build not found` 로 즉시 죽는다 — `source_only=True` 여도 마찬가지다.
    실측: 소스·요구문서·템플릿이 다 갖춰져 있어도 **0.0초 만에** 실패했다.
    게이트가 이 전제를 모르면 '준비 완료' 라고 그린다.
    """
    data = _post({"doc_type": "uds", "source_root": str(tmp_path)})
    step = _step(data, "build_cache")
    assert step is not None, "UDS 에 빌드 캐시 단계가 없다"
    assert step["required"] is True
    assert step["state"] != "ok"
    assert data["verdict"] in ("blocked", "needs_decision")


@pytest.mark.parametrize("doc_type", ["sts", "suts", "sits"])
def test_other_docs_do_not_require_a_build(doc_type: str, tmp_path: Path) -> None:
    """STS/SUTS/SITS 는 그 전제가 없다 — 같은 세션에서 캐시 없이 생성에 성공했다.

    없는 조건을 요구하면 만들 수 있는 문서를 못 만들게 막는다.
    """
    data = _post({"doc_type": doc_type, "source_root": str(tmp_path)})
    assert _step(data, "build_cache") is None


def test_template_format_must_match_the_generator(tmp_path: Path) -> None:
    """템플릿은 **존재만으로 부족하다** — 생성기가 여는 형식이어야 한다.

    실측: 회사 표준 폴더에 같은 이름의 `.xlsm` 과 `.docx` 가 **둘 다** 있어서 `.docx` 를
    고르기 쉬운데, 시험 규격서 생성기(openpyxl)는 그걸 열다가
    `InvalidFileException: openpyxl does not support .docx` 로 죽는다. 실제로 그렇게
    실패했고, 게이트는 그걸 **생성 전에** 잡아야 한다.
    """
    wrong = tmp_path / "spec.docx"
    wrong.write_bytes(b"x")
    data = _post({"doc_type": "suts", "source_root": str(tmp_path),
                  "doc_paths": {"suts_template": str(wrong)}})
    step = _step(data, "template")
    assert step is not None
    assert step["state"] != "ok", "형식이 틀린 템플릿을 통과시켰다"
    assert ".xlsm" in str(step.get("reason") or ""), "어떤 형식을 원하는지 말하지 않는다"


def test_template_suggestion_only_when_the_file_exists(tmp_path: Path) -> None:
    """같은 이름의 올바른 형식이 **실재할 때만** 제안한다 — 없는 파일을 권하면 안 된다."""
    wrong = tmp_path / "spec.docx"
    wrong.write_bytes(b"x")
    # (1) 대체본이 없다 → 제안 없음
    d1 = _post({"doc_type": "suts", "source_root": str(tmp_path),
                "doc_paths": {"suts_template": str(wrong)}})
    s1 = _step(d1, "template")
    assert s1 is not None and "suggestion" not in s1

    # (2) 대체본을 만들어 두면 → 그 파일명을 제안
    (tmp_path / "spec.xlsm").write_bytes(b"x")
    d2 = _post({"doc_type": "suts", "source_root": str(tmp_path),
                "doc_paths": {"suts_template": str(wrong)}})
    s2 = _step(d2, "template")
    assert s2 is not None
    assert s2["state"] == "stale_path"
    assert s2["suggestion"] == "spec.xlsm"
    assert any(a["kind"] == "adopt_suggestion" for a in (s2.get("actions") or []))


def test_uds_template_wants_docx(tmp_path: Path) -> None:
    """UDS 는 python-docx 라 `.docx` 가 맞다 — 시험문서와 반대다."""
    ok_tpl = tmp_path / "unit.docx"
    ok_tpl.write_bytes(b"x")
    data = _post({"doc_type": "uds", "source_root": str(tmp_path),
                  "doc_paths": {"uds_template": str(ok_tpl)}})
    step = _step(data, "template")
    assert step is not None and step["state"] == "ok"

    bad = tmp_path / "unit.xlsm"
    bad.write_bytes(b"x")
    data2 = _post({"doc_type": "uds", "source_root": str(tmp_path),
                   "doc_paths": {"uds_template": str(bad)}})
    step2 = _step(data2, "template")
    assert step2 is not None and step2["state"] != "ok"


def test_shared_template_still_works_as_fallback(tmp_path: Path) -> None:
    """구 설정(공용 `template`)도 계속 동작해야 한다 — 회귀를 만들지 않는다."""
    tpl = tmp_path / "legacy.docx"
    tpl.write_bytes(b"x")
    data = _post({"doc_type": "uds", "source_root": str(tmp_path),
                  "doc_paths": {"template": str(tpl)}})
    step = _step(data, "template")
    assert step is not None and step["state"] == "ok"


def test_specific_template_wins_over_shared(tmp_path: Path) -> None:
    """전용 키가 공용보다 우선이다 — 그게 이 분리의 목적이다."""
    shared = tmp_path / "shared.docx"
    specific = tmp_path / "uds_only.docx"
    shared.write_bytes(b"x")
    specific.write_bytes(b"x")
    data = _post({"doc_type": "uds", "source_root": str(tmp_path),
                  "doc_paths": {"template": str(shared), "uds_template": str(specific)}})
    step = _step(data, "template")
    assert step is not None
    assert step["value"] == str(specific)


def test_multi_root_source_is_parsed(tmp_path: Path) -> None:
    """`source_root` 는 **콤마 구분 복수 경로**일 수 있다.

    실측 레지스트리: `C:\\…\\NE1AW_PORTING,C:\\…\\PDS128_FBL`. 콤마 문자열을 그대로
    파서에 넘기면 존재하지 않는 경로가 되어 **함수 0개**가 나오고, 화면은 그걸
    "주석이 하나도 없다" 로 그렸다.
    """
    a, b = tmp_path / "A", tmp_path / "B"
    a.mkdir()
    b.mkdir()
    (a / "one.c").write_text("void fa(void) { }\n", encoding="utf-8")
    (b / "two.c").write_text("void fb(void) { }\n", encoding="utf-8")
    cov.clear_cache()
    res = cov.measure(f"{a},{b}")
    assert res["scanned_files"] >= 2, "둘째 루트를 스캔하지 않았다"
    assert not res.get("reason")


def test_empty_scan_is_unmeasured_not_zero(tmp_path: Path) -> None:
    """파일을 하나도 못 읽으면 **재지 못한 것**이지 "함수 0개" 가 아니다."""
    empty = tmp_path / "empty"
    empty.mkdir()
    cov.clear_cache()
    res = cov.measure(str(empty))
    assert res["scanned_files"] == 0
    assert res["reason"], "빈 스캔에 사유가 없다"


def test_unmeasurable_source_does_not_mark_comment_absent(tmp_path: Path) -> None:
    """측정 실패를 "주석 없음" 으로 접지 않는다 — 사슬에서 `?`(모름)이어야 한다.

    라이브에서 `comment=X`(확인했고 없음)로 그려졌는데 실제로는 파싱이 안 된 것이었다.
    """
    empty = tmp_path / "src"
    empty.mkdir()
    cov.clear_cache()
    cov.measure(str(empty))          # 캐시에 '못 쟀음' 을 넣는다
    data = _post({"doc_type": "uds", "source_root": str(empty)})
    step = _step(data, "comment_coverage")
    assert step is not None and step["state"] == "unmeasured"
    assert "measured" not in step
    chain = _step(data, "chain_asil")
    assert chain is not None
    have = {r["source"]: r["have"] for r in chain["chain"]}
    assert have["comment"] is None, "측정 실패인데 '확인했고 없음' 으로 그렸다"


# ── STS 재료 게이트 (2026-08-14 신설) ───────────────────────────────────────
#
# STS 는 오래 이 게이트 밖에 있었다(`doc_type in ("sits","suts")`). 그런데 STS 야말로
# 재료가 없어도 TC 가 나온다 — 매핑이 빈 요구는 `_generate_review_steps` 로 **소스
# 근거 0** 인 리뷰 절차가 채워지고, 요구 커버리지는 100% 로 보인다.

def _sts_materials(**over) -> dict:
    base = {
        "ok": True, "functions": 10, "elapsed_s": 0.1,
        "sits": {"flows_total": 0, "cap": 120, "headroom": 120, "at_cap_boundary": False,
                 "sds_map_entries": 0, "sds_reason": "", "sds_lookups": 0,
                 "sds_key_hits": 0, "sds_swcom_hits": 0, "sample_flow": None},
        "suts": {"variables": 0, "grounded": 0, "fallback": 0, "fallback_samples": []},
        "sts_mapping": {
            "measured": True, "requirements": 68, "mapped": 48,
            "causes": {"unreached_in_sds": 16, "absent_from_sds": 4},
            "cause_samples": {"unreached_in_sds": ["SwTR_0108"],
                              "absent_from_sds": ["SwNTSR_0101"]},
            "sds_reason": "", "cap": 5, "mapped_functions": 1028,
            "functions_beyond_cap": 925, "requirements_over_cap": 42,
        },
    }
    base["sts_mapping"].update(over)
    return base


def _with_materials(tmp_path: Path, materials: dict, doc_type: str = "sts") -> dict:
    import time as _time

    from backend.services import docgen_test_materials as tm
    root = str(tmp_path)           # 실재해야 재료 단계까지 간다(조건부 스킵 = 공허 통과)
    tm.clear_cache()
    tm._CACHE[tm._key(root)] = (_time.time(), materials)
    try:
        return _post({"doc_type": doc_type, "source_root": root})
    finally:
        tm.clear_cache()


def test_sts_reaches_the_material_gate_at_all(tmp_path: Path) -> None:
    """회귀 대상 — 이 조건이 `("sits","suts")` 였을 때 STS 는 단계 자체가 없었다."""
    data = _with_materials(tmp_path, _sts_materials())
    assert _step(data, "sts_req_mapping") is not None, "STS 가 재료 게이트에 못 들어왔다"


def test_unmapped_requirements_are_named_with_their_cause(tmp_path: Path) -> None:
    """건수만으로는 조치할 수 없다 — **누가 고칠 문제인지**가 사유로 갈려야 한다."""
    step = _step(_with_materials(tmp_path, _sts_materials()), "sts_req_mapping")
    assert step["state"] == "degraded"
    assert step["measured"]["causes"] == {"unreached_in_sds": 16, "absent_from_sds": 4}
    assert "리뷰 절차" in step["reason"], "근거 0 인 TC 가 나온다는 사실이 안 적혔다"


def test_fully_mapped_requirements_are_quiet(tmp_path: Path) -> None:
    """대조군 — 다 붙으면 조용하다(경고를 상시 켜 두면 아무도 안 본다)."""
    step = _step(
        _with_materials(tmp_path, _sts_materials(mapped=68, causes={}, cause_samples={})),
        "sts_req_mapping")
    # ⚠ `_step` 은 빈 값을 아예 안 싣는다 — `step["reason"]` 은 KeyError 다.
    assert step["state"] == "ok" and not step.get("reason")


def test_tc_cap_says_it_is_a_lower_bound_and_order_decides(tmp_path: Path) -> None:
    """⚠ 두 가지를 반드시 말해야 한다.

    ① 이 값은 **하한**이다(한 함수가 여러 TC 를 내면 상한이 더 일찍 찬다 —
       실측 계산 715 vs `generate_test_cases` 실측 887).
    ② 남는 5개가 무엇인지는 관련성이 아니라 **함수 순서**가 정한다.
    """
    step = _step(_with_materials(tmp_path, _sts_materials()), "sts_tc_cap")
    assert step is not None and step["state"] == "degraded"
    assert "최소" in step["reason"], "하한이라는 사실이 안 적혔다"
    assert "순서" in step["reason"], "무엇이 남는지를 순서가 정한다는 사실이 안 적혔다"


def test_sts_material_gate_never_blocks(tmp_path: Path) -> None:
    """`degraded` 로 생성을 막지 않는다 — 막으면 실측상 아무도 문서를 못 만든다.

    ⚠ verdict 자체는 다른 이유(필수 입력 미확보)로 blocked 일 수 있다. 그래서 전체
    verdict 이 아니라 **이 두 단계가 차단 상태를 내는지**를 본다 — 안 그러면 이
    테스트는 남의 실패에 얹혀 초록이 되거나 빨개진다.
    """
    data = _with_materials(tmp_path, _sts_materials())
    for sid in ("sts_req_mapping", "sts_tc_cap"):
        st = _step(data, sid)
        assert st is not None, f"{sid} 단계가 없다"
        assert st["state"] in ("ok", "degraded", "unmeasured"),             f"{sid} 가 차단 상태({st['state']})를 냈다"


def test_unmeasured_sts_mapping_is_not_drawn_as_zero(tmp_path: Path) -> None:
    """재지 못한 값을 0 으로 그리지 않는다(모듈 docstring 규약 3)."""
    mats = _sts_materials()
    mats["sts_mapping"] = {"measured": False, "reason": "SwRS 경로가 지정되지 않았습니다"}
    step = _step(_with_materials(tmp_path, mats), "sts_req_mapping")
    assert step["state"] == "unmeasured"
    assert "SwRS" in step["reason"]
    assert not step.get("measured"), "미측정인데 숫자를 실었다"


def test_asil_evidence_axis_is_surfaced_for_suts(tmp_path: Path) -> None:
    """안전 등급이 **부분문자열 첫 일치**로 정해졌다는 사실을 숨기지 않는다.

    값을 바꾸자는 게 아니다(대안 6개가 다 더 나빴다 — `suts._resolve_unit_asil`).
    ISO 26262 문서에서 등급의 근거는 읽는 사람이 알아야 한다.
    """
    mats = _sts_materials()
    mats["suts_inputs"] = {"measured": False, "reason": "n/a"}
    mats["suts_asil"] = {"measured": True, "units": 1157, "graded": 962,
                         "fuzzy": 181, "fuzzy_conflict": 244, "samples": ["g_DrvIn_Main"]}
    step = _step(_with_materials(tmp_path, mats, doc_type="suts"), "suts_asil_evidence")
    assert step is not None and step["state"] == "degraded"
    assert step["measured"] == {"value": 425, "of": 962, "units": 1157, "conflict": 244}
    assert "갈립니다" in step["reason"], "충돌 건수를 따로 말하지 않았다"


def test_asil_evidence_is_quiet_when_all_exact(tmp_path: Path) -> None:
    mats = _sts_materials()
    mats["suts_inputs"] = {"measured": False, "reason": "n/a"}
    mats["suts_asil"] = {"measured": True, "units": 10, "graded": 10,
                         "fuzzy": 0, "fuzzy_conflict": 0, "samples": []}
    step = _step(_with_materials(tmp_path, mats, doc_type="suts"), "suts_asil_evidence")
    assert step["state"] == "ok" and not step.get("reason")


# ── 설계-ID 브리지 상태가 화면에 나오는가 ────────────────────────────────────

def test_bridge_off_is_named_in_the_reason(tmp_path: Path) -> None:
    """브리지가 꺼진 채로 잰 숫자를 그냥 내면 결함으로 오독된다.

    실측(KJPDS02_PV): SwUDS 없이 48/68 · 주면 64/68. 즉 `unreached_in_sds` 16 은
    **코드 결함이 아니라 입력 부재**일 수 있다 — 어느 쪽인지 화면이 말해야 한다.
    """
    step = _step(
        _with_materials(tmp_path, _sts_materials(
            bridge={"on": False, "reason": "SwUDS 경로가 지정되지 않았습니다"})),
        "sts_req_mapping")
    assert step["measured"]["bridge"]["on"] is False
    assert "설계-ID 브리지 꺼짐" in step["reason"]
    assert "SwUDS" in step["reason"]


def test_bridge_on_does_not_add_the_hint(tmp_path: Path) -> None:
    """대조군 — 브리지가 켜져 있으면 그 문구가 안 붙는다(상시 경고 금지)."""
    step = _step(
        _with_materials(tmp_path, _sts_materials(bridge={"on": True, "functions": 1157})),
        "sts_req_mapping")
    assert step["measured"]["bridge"]["on"] is True
    assert "브리지 꺼짐" not in step["reason"]
    assert "리뷰 절차" in step["reason"], "미매핑 자체는 여전히 보고돼야 한다"


def test_measure_source_forwards_uds_path(monkeypatch, tmp_path: Path) -> None:
    """엔드포인트가 uds_path 를 흘리지 않으면 게이트만 브리지가 꺼진다."""
    from backend.routers import docgen_preflight as dp
    seen = {}
    monkeypatch.setattr(dp._tm, "measure",
                        lambda root, **kw: seen.update(kw) or {"ok": True})
    monkeypatch.setattr(dp._cov, "measure", lambda root, **kw: {"ok": True})
    r = client.post("/api/docgen/measure-source", headers=HEADERS, json={
        "source_root": str(tmp_path), "doc_type": "sts",
        "sds_path": "s.docx", "srs_path": "r.docx", "uds_path": "u.docx"})
    assert r.status_code == 200
    assert seen.get("uds_path") == "u.docx"


# ── 시험 결과 6종 + 통합 1종 — 양식 키가 라우터와 **같은가** ──────────────────
#
# `_TEST_REPORT_TEMPLATE_KEY` 는 라우터 `_read_template_bytes` 의 config fallback 키를
# 손으로 옮겨 적은 **복제**다. 갈라지면 증상이 고약하다: 게이트는 "양식 있음"이라 하고
# 빌드는 400 을 낸다 — 사용자는 준비 점검을 통과한 뒤에 실패를 본다.
#
# 그래서 소스를 읽어 비교하지 않고 **라우터에게 직접 물어본다**: 빈 config 로 부르면
# 400 detail 에 자기가 찾던 키 이름을 적어 준다. 그 값이 정본이다.


class TestReportTemplateKeyParity:
    # doc_type → (라우터 모듈, `_read_template_bytes` 의 kind 인자)
    ROUTES = {
        "swut": ("swut", "coverage"),
        "sutr": ("swut", "sutr"),
        "swutcr": ("swut", "swutcr"),
        "swit": ("swit", "coverage"),
        "sitr": ("swit", "sitr"),
        "switcr": ("swit", "switcr"),
    }

    @pytest.mark.parametrize("doc_type", sorted(ROUTES))
    def test_key_matches_router(self, doc_type, monkeypatch) -> None:
        import importlib

        from fastapi import HTTPException

        from backend.routers.docgen_preflight import _TEST_REPORT_TEMPLATE_KEY

        mod_name, kind = self.ROUTES[doc_type]
        mod = importlib.import_module(f"backend.routers.{mod_name}")
        monkeypatch.setattr(mod, "_load_meta_from_config", lambda _pid: {"template_paths": {}})
        with pytest.raises(HTTPException) as ei:
            mod._read_template_bytes("", "HDPDM01", kind)
        detail = str(ei.value.detail)
        expected = _TEST_REPORT_TEMPLATE_KEY[doc_type]
        assert f"'{expected}'" in detail, (
            f"{doc_type}: preflight 는 '{expected}' 를 보는데 라우터는 다른 키를 찾는다 — {detail}"
        )

    def test_swreport_key_is_the_first_router_fallback(self) -> None:
        """통합 Summary 만 라우터가 **키 여러 개를 순서대로** 본다 — 첫 키가 정본이다."""
        from backend.routers.docgen_preflight import _TEST_REPORT_TEMPLATE_KEY
        from backend.routers.swreport import _TEMPLATE_CONFIG_KEYS
        assert _TEST_REPORT_TEMPLATE_KEY["swreport"] == _TEMPLATE_CONFIG_KEYS[0]

    def test_every_test_report_doc_type_has_a_key(self) -> None:
        """키가 없으면 `.get(..., "")` 이 빈 문자열을 주고, 게이트는 '등록 안 됨'을
        **모든 프로젝트에** 보고한다(거짓 차단)."""
        from backend.routers.docgen_preflight import _TEST_REPORT_TEMPLATE_KEY
        for dt in req.TEST_REPORT_DOC_TYPES:
            assert _TEST_REPORT_TEMPLATE_KEY.get(dt), f"{dt}: 양식 키 미등록"


# ── 시험 결과 6종이 실제로 게이트를 받는가 ───────────────────────────────────

@pytest.mark.parametrize("doc_type", ["swut", "sutr", "swutcr", "swit", "sitr", "switcr"])
def test_test_report_doc_types_get_form_and_template_steps(doc_type) -> None:
    """커버리지 2종(`swut`/`swit`)이 빠져 있으면 보드의 [준비] 가 빈 패널을 연다."""
    data = _post({"doc_type": doc_type})
    assert data["unknown_doc_type"] is False
    ids = {s["id"] for s in data["steps"]}
    assert "report_template" in ids, f"{doc_type}: 양식 단계 없음"
    for field in req.TEST_REPORT_FORM_FIELDS:
        assert f"form_{field}" in ids, f"{doc_type}: {field} 단계 없음"


def test_form_values_are_read_not_ignored() -> None:
    """폼을 실으면 판정이 **바뀌어야** 한다 — 안 바뀌면 `form` 이 버려진 것이다."""
    without = _post({"doc_type": "swutcr"})
    with_form = _post({
        "doc_type": "swutcr",
        "form": {"project_id": "HDPDM01", "release_sw_version": "1.02", "test_date": "2026-08-24"},
    })
    for field in req.TEST_REPORT_FORM_FIELDS:
        assert _step(without, f"form_{field}")["state"] == "needed", field
        assert _step(with_form, f"form_{field}")["state"] == "ok", field


def test_coverage_doc_type_keeps_the_quality_db_vocabulary() -> None:
    """커버리지 키를 `swutcv` 로 바꾸면 그동안 쌓인 이력이 전부 '미생성' 이 된다.

    Quality DB 는 `record_run("swut", …)` 으로 쌓아 왔고 보드는 그 doc_type 으로 조회한다.
    """
    assert "swut" in req.DOC_REQUIREMENTS
    assert "swit" in req.DOC_REQUIREMENTS
    assert "swutcv" not in req.DOC_REQUIREMENTS
    assert "switcv" not in req.DOC_REQUIREMENTS
    assert "커버리지" in req.DOC_REQUIREMENTS["swut"]["label"]
    assert "커버리지" in req.DOC_REQUIREMENTS["swit"]["label"]


def test_handlers_point_at_real_endpoints() -> None:
    """`handler` 문자열이 실재하는 라우트여야 한다 — 없는 경로를 안내하면 조치가 막힌다."""
    routes = {f"{m} {r.path}" for r in app.routes
              for m in (getattr(r, "methods", None) or set())}
    for dt in req.doc_types():
        handler = req.requirements_for(dt)["handler"]
        assert handler in routes, f"{dt}: {handler} 라우트가 없다"


# ── VectorCAST 로그: 게이트가 **라우터와 같은 곳**을 보는가 ──────────────────
#
# 2026-08-24 라이브 실측: 보드에서 SwUTCR 이 정상 생성되는데 준비 점검은
# "VectorCAST 결과 경로가 지정되지 않았습니다 → 진행 불가" 였다. 라우터는
# `config/swut_meta.json` 의 `swut_log_folders` 로 폴백하는데 게이트가 그 출처를 몰랐다.
# **거짓 차단은 게이트를 무시하게 만든다** — 없느니만 못하다.


class TestVectorcastSourceParity:
    SERIES = {"swut": "swut", "sutr": "swut", "swutcr": "swut",
              "swit": "swit", "sitr": "swit", "switcr": "swit"}

    def test_series_map_covers_the_six(self) -> None:
        from backend.routers.docgen_preflight import _TEST_REPORT_LOG_SERIES
        assert _TEST_REPORT_LOG_SERIES == self.SERIES
        # 통합 Summary 는 로그가 아니라 레벨별 산출물을 읽는다 — 넣으면 없는 단계가 생긴다.
        assert "swreport" not in _TEST_REPORT_LOG_SERIES

    @pytest.mark.parametrize("doc_type", sorted(SERIES))
    def test_config_fallback_is_the_same_source_the_router_uses(
        self, doc_type, monkeypatch, tmp_path,
    ) -> None:
        """게이트가 본 경로 == 라우터가 빌드에 쓸 경로."""
        from backend.services import swut_meta_resolver as res
        series = self.SERIES[doc_type]
        folder = tmp_path / f"{series}_log"
        folder.mkdir()
        monkeypatch.setattr(
            res, "config_log_folders_for",
            lambda pid, s: [str(folder)] if (pid == "PRJ" and s == series) else [],
        )
        data = _post({
            "doc_type": doc_type, "scm_id": "",
            "form": {"project_id": "PRJ", "release_sw_version": "1.0", "test_date": "2026-08-24"},
        })
        step = _step(data, "vectorcast")
        assert step is not None, f"{doc_type}: vectorcast 단계가 없다"
        assert step["state"] == "ok", f"{doc_type}: {step.get('reason')}"
        assert str(folder) in str(step.get("value", ""))

    def test_partial_missing_is_degraded_not_ok(self, monkeypatch, tmp_path) -> None:
        """APP+BOOT 중 하나만 없으면 **부분 결손**이다 — 첫 개만 보고 '확인됨' 하면
        산출물이 절반만 담긴 채로 나간다."""
        from backend.services import swut_meta_resolver as res
        good = tmp_path / "APP"
        good.mkdir()
        gone = tmp_path / "BOOT_없음"
        monkeypatch.setattr(res, "config_log_folders_for", lambda pid, s: [str(good), str(gone)])
        data = _post({
            "doc_type": "swutcr", "scm_id": "",
            "form": {"project_id": "PRJ", "release_sw_version": "1.0", "test_date": "2026-08-24"},
        })
        step = _step(data, "vectorcast")
        assert step["state"] == "degraded", step
        assert step["measured"] == {"folders": 2, "missing": 1}
        assert "BOOT_없음" in step["reason"]

    def test_all_missing_is_missing(self, monkeypatch, tmp_path) -> None:
        from backend.services import swut_meta_resolver as res
        monkeypatch.setattr(
            res, "config_log_folders_for",
            lambda pid, s: [str(tmp_path / "없음1"), str(tmp_path / "없음2")],
        )
        data = _post({
            "doc_type": "swutcr", "scm_id": "",
            "form": {"project_id": "PRJ", "release_sw_version": "1.0", "test_date": "2026-08-24"},
        })
        assert _step(data, "vectorcast")["state"] == "missing"


def test_router_and_preflight_share_one_config_reader() -> None:
    """라우터가 config 를 **직접** 읽으면 세 번째 복제가 되살아난다."""
    import inspect

    from backend.routers import swit as swit_mod
    from backend.routers import swut as swut_mod
    for mod, fn in ((swut_mod, "_resolve_swut_log_folders"), (swit_mod, "_resolve_swit_log_folders")):
        src = inspect.getsource(getattr(mod, fn))
        assert "config_log_folders" in src, f"{fn} 이 단일 출처를 안 쓴다"
        for key in ("swut_log_folders", "swit_log_folder", "log_folders\", {}"):
            assert f'cfg.get("{key}' not in src, f"{fn} 이 config 를 직접 읽는다: {key}"


# ── 대응 시험 규격서: 출처 · 필수 여부 ──────────────────────────────────────
#
# 2026-08-24 실측으로 드러난 두 결함:
#   B. 규격서가 `swut_meta.json` 에 **등록돼 있는데** 게이트는 SCM 만 보고
#      "경로가 지정되지 않았습니다" 라고 했다 (VectorCAST 와 같은 결함).
#   A. `sutr_spec_based=true` 프로젝트에서 규격서가 없으면 라우터가 **400** 을 내는데
#      표는 `optional` 이라 게이트가 "없어도 됩니다" 라고 **거짓말**을 했다.


class TestSpecDocSourceAndRequirement:
    @pytest.mark.parametrize(
        "doc_type,series",
        [("swut", "swut"), ("sutr", "swut"), ("swutcr", "swut"),
         ("swit", "swit"), ("sitr", "swit"), ("switcr", "swit")],
    )
    def test_config_registered_spec_is_found(self, doc_type, series, monkeypatch, tmp_path):
        """B — config 에 등록된 규격서를 게이트가 찾는다."""
        from backend.services import swut_meta_resolver as res
        spec = tmp_path / f"{series}_spec.xlsm"
        spec.write_bytes(b"x")
        monkeypatch.setattr(res, "config_log_folders_for", lambda pid, s: [])
        monkeypatch.setattr(
            res, "config_spec_path_for",
            lambda pid, s: str(spec) if (pid == "PRJ" and s == series) else "",
        )
        monkeypatch.setattr(res, "config_spec_is_required_for", lambda pid, s: False)
        data = _post({
            "doc_type": doc_type, "scm_id": "",
            "form": {"project_id": "PRJ", "release_sw_version": "1.0", "test_date": "2026-08-24"},
        })
        step = _step(data, "spec_doc")
        assert step is not None, f"{doc_type}: spec_doc 단계가 없다"
        assert step["state"] == "ok", f"{doc_type}: {step.get('reason')}"
        assert str(spec) == step.get("value")

    @pytest.mark.parametrize("doc_type,series", [("sutr", "swut"), ("sitr", "swit")])
    def test_spec_based_project_marks_it_required(self, doc_type, series, monkeypatch, tmp_path):
        """A — spec-based 프로젝트에서는 규격서가 required 다(없으면 라우터가 400)."""
        from backend.services import swut_meta_resolver as res
        monkeypatch.setattr(res, "config_log_folders_for", lambda pid, s: [])
        monkeypatch.setattr(res, "config_spec_path_for", lambda pid, s: "")
        monkeypatch.setattr(res, "config_spec_is_required_for", lambda pid, s: True)
        data = _post({
            "doc_type": doc_type, "scm_id": "",
            "form": {"project_id": "PRJ", "release_sw_version": "1.0", "test_date": "2026-08-24"},
        })
        step = _step(data, "spec_doc")
        assert step["required"] is True, step
        # 필수인데 없으면 **막아야** 한다 — needs_decision 으로 접으면 400 을 예고 못 한다.
        assert step["state"] == "missing", step
        assert data["verdict"] == "blocked"

    @pytest.mark.parametrize("doc_type,series", [("sutr", "swut"), ("sitr", "swit")])
    def test_non_spec_based_project_keeps_it_optional(self, doc_type, series, monkeypatch):
        """HDPDM01 처럼 꺼진 프로젝트에서는 그대로 선택 입력 — 반대 방향 거짓말 금지."""
        from backend.services import swut_meta_resolver as res
        monkeypatch.setattr(res, "config_log_folders_for", lambda pid, s: [])
        monkeypatch.setattr(res, "config_spec_path_for", lambda pid, s: "")
        monkeypatch.setattr(res, "config_spec_is_required_for", lambda pid, s: False)
        data = _post({
            "doc_type": doc_type, "scm_id": "",
            "form": {"project_id": "PRJ", "release_sw_version": "1.0", "test_date": "2026-08-24"},
        })
        step = _step(data, "spec_doc")
        assert not step.get("required"), step
        assert step["effect"], "선택 입력은 **없으면 무슨 일이 생기는지** 를 달고 있어야 한다"

    @pytest.mark.parametrize("doc_type", ["swut", "swutcr", "swit", "switcr"])
    def test_coverage_and_comprehensive_never_promote(self, doc_type, monkeypatch):
        """커버리지·종합결과는 규격서 없이도 빌드가 성공한다 — 막을 이유가 없다."""
        from backend.services import swut_meta_resolver as res
        monkeypatch.setattr(res, "config_log_folders_for", lambda pid, s: [])
        monkeypatch.setattr(res, "config_spec_path_for", lambda pid, s: "")
        # spec_based 가 켜져 있어도 이 넷은 승격되면 안 된다.
        monkeypatch.setattr(res, "config_spec_is_required_for", lambda pid, s: True)
        data = _post({
            "doc_type": doc_type, "scm_id": "",
            "form": {"project_id": "PRJ", "release_sw_version": "1.0", "test_date": "2026-08-24"},
        })
        assert not _step(data, "spec_doc").get("required"), doc_type

    def test_promotion_map_is_only_the_two_spec_based_docs(self):
        from backend.routers.docgen_preflight import _SPEC_REQUIRED_SERIES
        assert _SPEC_REQUIRED_SERIES == {"sutr": "swut", "sitr": "swit"}


def test_router_uses_the_shared_spec_path_judgment() -> None:
    """`resolve_swuts_path` 가 config 를 직접 파면 판정이 두 벌이 된다."""
    import inspect

    from backend.services.swut_meta_resolver import resolve_swuts_path
    src = inspect.getsource(resolve_swuts_path)
    assert "config_spec_path" in src
    assert 'cfg.get("swits_docx_path")' not in src
