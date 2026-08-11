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
