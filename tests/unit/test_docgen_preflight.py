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
