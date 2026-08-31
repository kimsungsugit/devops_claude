"""문서 생성 preflight — **state 를 서로 접지 않는지**가 이 파일의 본체다.

계획서가 못박은 규약 중 회귀로 고정해야 하는 것:

1. `unknown`(확인 못 함)을 `missing`(확인했고 없음)으로 접지 않는다.
2. `degraded`(있지만 부족)로 **생성을 막지 않는다** — 막으면 실측상 아무도 문서를 못 만든다.
3. 재지 못한 값을 `0` 으로 그리지 않는다.
4. **칸 수를 예고하지 않는다** — 사슬은 단계별 가용성만 낸다.
"""
from __future__ import annotations

import time
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
    """API 기본값이 생성기 기본값보다 작으면 화면이 그 사실을 알 수 있어야 한다.

    SITS `max_subcases` 7 vs 14 — 버그가 아니라 의도지만(`generators/sits.py:58`)
    말하지 않으면 사용자는 후보 중 7종만 만들어진 걸 모른다.

    ⚠ 여기 두 수(7·14) 중 **어느 것도 "전량" 이 아니다.** 14 는 생성기 캡이고 후보는
    15종이다 — 오래 이 docstring 이 "14종 중 7종" 이라 적었고 게이트도 같은 오해로
    `max_subcases=14` 를 손실 없음으로 판정했다. 전량 축은 `catalog_max` 가 들고 있고
    실행 대조는 `test_generator_catalog_max.py` 가 한다.

    ⚠ SUTS 는 **더 이상 이 예시가 아니다.** 오래 `api: 6` 으로 공시했는데 핸들러는
    `jenkins.py:3420 Form(24)` 였다 — 화면이 `현재 6 · 생성기 기본 24` 라는 거짓
    공시를 했다. 라우터와의 정합은 `test_docgen_cap_wiring_parity.py` 가 본다.
    """
    data = _post({"doc_type": "sits", "source_root": str(tmp_path)})
    step = _step(data, "cap_max_subcases")
    assert step is not None
    m = step["measured"]
    assert m["api_default"] == 7
    assert m["generator_default"] == 14

    suts = _step(_post({"doc_type": "suts", "source_root": str(tmp_path)}),
                 "cap_max_sequences")
    assert suts is not None
    assert suts["measured"]["api_default"] == 24, "공시가 핸들러 Form(24) 와 같아야 한다"


def test_uds_caps_are_adjustable_and_do_not_force_needs_decision(tmp_path: Path) -> None:
    """UDS 상한은 이제 **요청으로 조정한다**. 그래도 verdict 를 밀지는 않는다.

    ⚠ 이력이 두 겹이다.
      ① 예전엔 모든 cap 을 무조건 `needed` 로 냈다 — UDS 는 조정 가능한 상한이 하나도
         없는데도 verdict 가 영원히 `needs_decision` 이라 "준비 완료" 가 한 번도 안 떴고,
         화면은 "조정할 수 없습니다" 라면서 판정은 "결정 필요" 라 **두 말**을 했다.
      ② 그 다음엔 `adjustable: False` 로 정직하게 표시만 했다. 못 고치는 **이유**였지
         못 고쳐야 할 이유는 아니었으므로, 이제 `Form(None)` 으로 받는다
         (`report_gen/uds_generator.generate_uds_source_sections(max_files=, max_items=)`).

    ①이 지키던 것은 그대로 지킨다 — 안 재봤으면 `unmeasured` 가 정직하고, 결정에 필요한
    수를 못 주면서 `needed` 를 내지 않는다.
    """
    data = _post({"doc_type": "uds", "source_root": str(tmp_path)})
    caps = [s for s in data["steps"] if s["id"].startswith("cap_")]
    assert caps, "UDS 도 절단 상한을 공시한다(그게 이 표의 존재 이유다)"
    assert all(c["state"] != "needed" for c in caps), [
        c["id"] for c in caps if c["state"] == "needed"
    ]
    assert data["verdict"] != "needs_decision", data["verdict"]
    for c in caps:
        assert c["measured"]["adjustable"] is True, c["id"]
        # 기본값의 출처는 계속 말한다. 조정 가능해졌다고 이 정보를 지우면 화면의
        # "기본 1200" 이 어디서 온 수인지 알 방법이 없다.
        assert "DEVOPS_UDS" in c["measured"]["default_from_env"], c["id"]
        assert "DEVOPS_UDS" in c["reason"], c["reason"]
        # `input_value` 는 달지 않는다. 누르면 보드가 "해당 빌더 탭에서 조정합니다" 라며
        # **그런 탭이 없는 곳**으로 사용자를 보냈다. 입력칸은 행에 직접 붙는다.
        kinds = {a.get("kind") for a in (c.get("actions") or [])}
        assert "input_value" not in kinds, c["id"]


def test_unmeasured_cap_offers_a_way_to_measure(tmp_path: Path) -> None:
    """못 잰 상한 행은 **재는 수단**을 준다.

    상태만 정직해지고 사용자가 할 수 있는 일이 없으면 `unmeasured` 는 막다른 길이다.
    실제로 UDS 가 그랬다 — `measure_source` 액션은 sts/sits/suts 재료 행에만 붙어서,
    UDS 게이트는 두 상한이 영영 `unmeasured` 로 남고 verdict 가 `unknown` 에 고착됐다.
    """
    caps = [s for s in _post({"doc_type": "uds", "source_root": str(tmp_path)})["steps"]
            if s["id"].startswith("cap_")]
    unmeasured = [c for c in caps if c["state"] == "unmeasured"]
    assert unmeasured, "이 픽스처는 측정 캐시가 없으므로 unmeasured 여야 한다"
    for c in unmeasured:
        kinds = {a.get("kind") for a in (c.get("actions") or [])}
        assert "measure_source" in kinds, f"{c['id']}: 재는 수단이 없다 — 막다른 길"


def test_measure_source_covers_uds(tmp_path: Path, monkeypatch) -> None:
    """`measure-source` 가 **uds 에서도** 소스 재료를 잰다.

    이게 빠지면 위 `measure_source` 버튼은 200 과 토스트만 내고 통계를 안 채운다 —
    눌러도 아무 일이 없는 **거짓 통제**다. UDS 상한의 절단량은 `_tm.measure` 가 내는
    `uds_category_caps`/`uds_file_scan` 에서만 나온다.
    """
    from backend.routers import docgen_preflight as dp

    called: list[str] = []
    monkeypatch.setattr(dp._cov, "measure", lambda *_a, **_k: {"ok": True})
    monkeypatch.setattr(dp._tm, "measure",
                        lambda root, **_k: called.append(root) or {"ok": True})
    out = dp.docgen_measure_source(
        dp.MeasureSourceRequest(source_root=str(tmp_path), doc_type="uds"))
    assert called, "uds 인데 소스 재료 측정을 건너뛰었다"
    assert "test_materials" in out


def test_user_chosen_cap_becomes_decided(tmp_path: Path, monkeypatch) -> None:
    """사용자가 상한을 정하면 그 캡은 더 이상 '결정 필요' 가 아니다.

    ⚠ 전량 측정이 있어야 판정이 선다 — 없으면 `unmeasured` 다(아래 별도 테스트).
    """
    _fake_cat_cache(monkeypatch, {"sts_mapping": {"max_functions_per_req": 12}})
    body = {"doc_type": "sts", "source_root": str(tmp_path)}
    before = _step(_post(body), "cap_max_tc_per_req")
    assert before["state"] == "needed"

    after = _step(_post({**body, "caps": {"max_tc_per_req": 12}}), "cap_max_tc_per_req")
    assert after["state"] == "ok"
    assert after["measured"]["user_value"] == 12

    # 0·음수는 프론트 스토어가 **키를 지우는** 값이라(`sharedInputs.js:53`) '정함' 이 아니다.
    zero = _step(_post({**body, "caps": {"max_tc_per_req": 0}}), "cap_max_tc_per_req")
    assert zero["state"] == "needed"
    assert "user_value" not in (zero["measured"] or {})

    # 같은 스토어에 문자열 선택지가 섞여 와도 죽지 않아야 한다 — `Dict[str, int]` 로
    # 받으면 `suts_scope` 하나 때문에 요청 전체가 422 가 된다.
    mixed = _step(
        _post({**body, "caps": {"max_tc_per_req": 5, "suts_scope": "source"}}),
        "cap_max_tc_per_req",
    )
    assert mixed["measured"]["user_value"] == 5


# `_measure_sits`/`_measure_suts_types` 가 내는 키의 최소 골격. 재료 스텝이 이 키들을
# 직접 인덱싱하므로, 빠뜨리면 테스트가 KeyError 로 죽고 **캡과 무관한 곳에서** 실패한다.
_TM_SKELETON = {
    "sits": {"flows_total": 0, "cap": 120, "headroom": 120, "at_cap_boundary": False,
             "uds_hits": 0, "uds": {}, "sample_flow": None},
    "suts": {"variables": 0, "grounded": 0, "fallback": 0},
}


def _fake_cat_cache(monkeypatch, payload) -> None:
    """소스 파싱 캐시를 대신한다 — 실측은 41~368초라 테스트에서 돌릴 수 없다."""
    from backend.routers import docgen_preflight as mod
    merged = None
    if payload is not None:
        merged = {**payload}
        for key, base_val in _TM_SKELETON.items():
            merged[key] = {**base_val, **(payload.get(key) or {})}
    monkeypatch.setattr(mod._tm, "has_cached", lambda *_a, **_k: merged is not None)
    monkeypatch.setattr(mod._tm, "cached", lambda *_a, **_k: merged)


def test_setting_the_default_does_not_invent_a_loss(tmp_path: Path) -> None:
    """**기본값을 직접 지정해도 손실 판정이 같아야 한다.**

    예전엔 SUTS 를 안 건드리면 손실을 한마디도 안 하다가, 기본값과 **똑같은 24** 를
    입력칸에 넣는 순간 "6개가 빠집니다" 가 튀어나왔다. 만들어지는 문서는 완전히 같다 —
    게이트가 문서가 아니라 **사용자의 타이핑**을 재고 있었다는 뜻이다.
    """
    body = {"doc_type": "suts", "source_root": str(tmp_path)}
    unset = _step(_post(body), "cap_max_sequences")
    api_default = unset["measured"]["api_default"]
    typed = _step(_post({**body, "caps": {"max_sequences": api_default}}),
                  "cap_max_sequences")

    assert unset["measured"].get("below_full") == typed["measured"].get("below_full"), (
        f"같은 산출인데 손실이 다르다: 미설정={unset['measured'].get('below_full')} "
        f"vs 직접지정={typed['measured'].get('below_full')}")
    assert unset["measured"].get("suggested") == typed["measured"].get("suggested")
    # 상태는 갈려도 된다(결정 대기 vs 받아들인 degrade) — 그러나 **손실을 아예 안
    # 말하는 쪽**이 있으면 안 된다. 기본값 상태에서 침묵하던 것이 원래 결함이다.
    assert "빠질 수 있습니다" in unset["reason"] or "빠집니다" in unset["reason"]


def test_default_that_holds_everything_is_not_a_decision(tmp_path: Path, monkeypatch) -> None:
    """기본값이 **전량을 담으면** 결정할 것이 없다 → `ok`.

    예전엔 조정 가능한 캡이면 무조건 `needed` 라, 흐름이 100개뿐(기본 120)이어도
    "결정 필요" 를 띄우고 verdict 를 `needs_decision` 에 묶어 뒀다. 사용자가 할 수 있는
    선택이 없는데 결정을 요구한 셈이다.
    """
    _fake_cat_cache(monkeypatch, {"sits": {"flows_total": 100}})
    s = _step(_post({"doc_type": "sits", "source_root": str(tmp_path)}), "cap_max_flows")
    assert s["state"] == "ok", s
    # 올릴 이유가 없으므로 "전부 N" 버튼도 내지 않는다.
    assert "suggested" not in (s["measured"] or {}), s["measured"]


def test_catalog_and_measured_totals_speak_differently(tmp_path: Path, monkeypatch) -> None:
    """전량의 **출처**가 다르면 주장 강도도 달라야 한다.

    실측 축(`max_flows`)은 이 소스를 실제로 세어 "95개가 빠진다" 가 참이지만,
    카탈로그 축(`max_sequences`)의 30 은 전략 후보의 **이론적 최대**라 그만큼 만드는
    함수가 거의 없다. 둘에 같은 단정 문장을 쓰면 손실을 부풀려 파는 것이 된다.
    """
    _fake_cat_cache(monkeypatch, {"sits": {"flows_total": 145}})
    meas = _step(_post({"doc_type": "sits", "source_root": str(tmp_path),
                        "caps": {"max_flows": 50}}), "cap_max_flows")
    assert meas["measured"]["suggested_basis"] == "measured"
    assert meas["measured"]["below_full"] == 95
    assert "95개가 빠집니다" in meas["reason"], meas["reason"]

    cat = _step(_post({"doc_type": "suts", "source_root": str(tmp_path)}),
                "cap_max_sequences")
    assert cat["measured"]["suggested_basis"] == "catalog"
    # 카탈로그 축은 **단정하지 않는다** — 상한이지 측정치가 아니다.
    assert "최대" in cat["reason"] and "빠질 수 있습니다" in cat["reason"], cat["reason"]
    assert "개가 빠집니다" not in cat["reason"], cat["reason"]


def test_adjustable_cap_without_measurement_is_not_a_demand(tmp_path: Path) -> None:
    """전량을 못 쟀으면 `needed` 가 아니다 — 결정에 필요한 수를 못 주면서 결정을
    요구하는 꼴이 된다. `unmeasured` + 재는 수단이 정직하다."""
    s = _step(_post({"doc_type": "sits", "source_root": str(tmp_path)}), "cap_max_flows")
    assert s["state"] == "unmeasured", s
    assert "measure_source" in {a.get("kind") for a in (s.get("actions") or [])}


def test_unadjustable_cap_reports_actual_truncation(tmp_path: Path, monkeypatch) -> None:
    """조정 못 하는 상한이라도 **지금 자르고 있으면** 그 사실이 상태에 나와야 한다.

    `ok` 로만 두면 "안 잘린다" 로 읽혀 상한을 공시하는 이유 자체가 사라진다.
    실측(KJPDS02_RD + PDS64_FBL): 소스의 `#define` 12,941개 vs 분류 상한 120.
    """
    _fake_cat_cache(monkeypatch, {
        "ok": True,
        "uds_category_caps": {
            "measured": True, "cap": 120, "any_truncated": True,
            "truncated": {
                "macros": {"total": 3881, "cap": 120, "dropped": 3761},
                "type_defs": {"total": 130, "cap": 120, "dropped": 10},
            },
        },
    })
    step = _step(_post({"doc_type": "uds", "source_root": str(tmp_path)}),
                 "cap_max_items_per_category")
    assert step is not None
    # degraded 는 차단이 아니다 — 막지 않되 침묵하지도 않는다.
    assert step["state"] == "degraded", step
    assert step["measured"]["dropped_total"] == 3771
    # 가장 큰 축을 지목해야 조치가 보인다. 합계만으로는 어디를 볼지 알 수 없다.
    assert "macros" in step["reason"], step["reason"]
    assert "3881" in step["reason"], step["reason"]
    # 조정 경로도 계속 말해야 한다(그게 이 캡의 유일한 조치다).
    assert "DEVOPS_UDS_MAX_ITEMS" in step["reason"], step["reason"]


def test_cap_without_measurement_does_not_invent_truncation(tmp_path: Path, monkeypatch) -> None:
    """캐시가 없으면 절단을 **지어내지 않는다** — 재지 못한 것과 없는 것은 다르다."""
    _fake_cat_cache(monkeypatch, None)
    step = _step(_post({"doc_type": "uds", "source_root": str(tmp_path)}),
                 "cap_max_items_per_category")
    # 안 잰 것을 `ok`(=확인됨)로 접지 않는다 — 이 모듈 §3 규약.
    assert step["state"] == "unmeasured", step
    assert "재지 않았습니다" in step["reason"], step["reason"]
    assert "truncated" not in (step["measured"] or {})
    assert "dropped_total" not in (step["measured"] or {})


def test_scope_row_reflects_the_user_choice(tmp_path: Path) -> None:
    """범위 행이 **고른 값**을 말해야 한다.

    안 읽으면 화면의 `<select>` 는 "소스 전체" 를 보이는데 옆 문구는 "기본은 정본
    기준입니다" 라 자기모순이 된다 — 게이트가 자기가 받은 선택을 부정하는 꼴이다.
    """
    body = {"doc_type": "suts", "source_root": str(tmp_path)}
    default = _step(_post(body), "scope")
    assert default["measured"]["value"] == "suds"
    assert "기본은 정본 기준" in default["reason"]

    picked = _step(_post({**body, "caps": {"suts_scope": "source"}}), "scope")
    assert picked["measured"]["value"] == "source"
    assert "소스 전체" in picked["reason"], picked["reason"]
    assert "기본은 정본 기준" not in picked["reason"]


def test_material_rows_follow_the_user_cap(tmp_path: Path, monkeypatch) -> None:
    """측정 행이 **사용자가 정한 상한**으로 다시 재야 한다.

    안 그러면 같은 패널의 두 행이 서로 다른 캡을 말한다. 실측 재현(흐름 145 / 기본 캡
    120): 상한을 50 으로 낮추면 실제로는 95개가 빠지는데 이 행은 계속 "25개" 라고 했다
    (**70건 과소보고**). 200 으로 올려 아무것도 안 잘려도 "빠집니다" 였다.
    """
    _fake_cat_cache(monkeypatch, {"ok": True, "sits": {
        "flows_total": 145, "cap": 120, "headroom": -25, "at_cap_boundary": True}})
    body = {"doc_type": "sits", "source_root": str(tmp_path)}

    lowered = _step(_post({**body, "caps": {"max_flows": 50}}), "sits_flows")
    assert lowered["measured"]["headroom"] == -95, lowered["measured"]
    assert "95" in lowered["reason"], lowered["reason"]

    raised = _step(_post({**body, "caps": {"max_flows": 200}}), "sits_flows")
    assert raised["measured"]["headroom"] == 55, raised["measured"]
    # 다 담기면 "빠집니다" 라고 하지 않는다.
    assert raised["state"] == "ok", raised
    assert not raised.get("reason")

    # 미설정이면 생성기 기본 캡 그대로다(없는 결정을 만들지 않는다).
    default = _step(_post(body), "sits_flows")
    assert default["measured"]["headroom"] == -25


def test_sts_tc_cap_recounts_with_user_cap(tmp_path: Path, monkeypatch) -> None:
    """요구당 상한을 올리면 무시험 함수 수가 **실제로** 줄어야 한다.

    재계산은 원래와 같은 방식이어야 한다 — 요구별 앞 `cap` 개만 남기고 **고유 함수
    집합의 차**를 센다. 분포 합으로 세면 여러 요구에 걸친 함수를 중복 계상한다.
    """
    _fake_cat_cache(monkeypatch, {"ok": True, "sts_mapping": {
        "measured": True, "requirements": 2, "mapped": 2, "causes": {}, "cause_samples": {},
        "sds_reason": "", "bridge": {"on": True}, "cap": 5,
        "mapped_functions": 9, "functions_beyond_cap": 1, "requirements_over_cap": 1,
        "max_functions_per_req": 6,
        # 요구1에 함수 6개, 요구2에 3개 — 고유 9개.
        "req_fid_lists": [[0, 1, 2, 3, 4, 5], [6, 7, 8]],
    }})
    body = {"doc_type": "sts", "source_root": str(tmp_path)}

    base_row = _step(_post(body), "sts_tc_cap")
    assert base_row["measured"]["beyond_cap"] == 1, base_row["measured"]

    raised = _step(_post({**body, "caps": {"max_tc_per_req": 6}}), "sts_tc_cap")
    assert raised["measured"]["beyond_cap"] == 0, raised["measured"]
    assert raised["state"] == "ok"

    lowered = _step(_post({**body, "caps": {"max_tc_per_req": 2}}), "sts_tc_cap")
    assert lowered["measured"]["beyond_cap"] == 5, lowered["measured"]
    assert lowered["measured"]["cap"] == 2


def test_cap_with_no_measurement_path_says_so(tmp_path: Path, monkeypatch) -> None:
    """**잴 방법이 아예 없는** 축은 `unmeasured` 로 두지 않는다.

    그러면 STS verdict 가 영구히 `unknown` 에 고착된다 — 원래 고치려던 결함의 재현이다.
    대신 측정하지 않는다는 사실을 말한다.
    """
    _fake_cat_cache(monkeypatch, None)
    step = _step(_post({"doc_type": "sts", "source_root": str(tmp_path)}),
                 "cap_max_steps_per_tc")
    assert step["state"] == "ok", step
    assert "측정하지 않습니다" in step["reason"], step["reason"]


def test_source_file_cap_truncation_is_reported(tmp_path: Path, monkeypatch) -> None:
    """소스 파일 상한에 닿으면 그 뒤 파일의 함수는 문서에 **아예 없다**.

    `max_items_per_category` 만 실측 분기가 있고 이 축은 무조건 `ok` 였다 —
    같은 침묵이 한 축 더 있었다.
    """
    _fake_cat_cache(monkeypatch, {
        "ok": True,
        "uds_file_scan": {"measured": True, "cap": 1200, "scanned": 1200, "truncated": True},
    })
    step = _step(_post({"doc_type": "uds", "source_root": str(tmp_path)}),
                 "cap_max_source_files")
    assert step["state"] == "degraded", step
    assert step["measured"]["truncated"] is True
    assert "1200" in step["reason"], step["reason"]

    # 음성 대조군 — 안 닿았으면 손실을 만들지 않는다.
    _fake_cat_cache(monkeypatch, {
        "ok": True,
        "uds_file_scan": {"measured": True, "cap": 1200, "scanned": 127, "truncated": False},
    })
    ok_step = _step(_post({"doc_type": "uds", "source_root": str(tmp_path)}),
                    "cap_max_source_files")
    assert ok_step["state"] == "ok", ok_step


def test_cap_over_suggestion_says_it_has_no_effect(tmp_path: Path, monkeypatch) -> None:
    """측정상 더 담을 것이 없는데 올린 값을 "반영됐다" 로만 두지 않는다.

    지금까지는 어떤 숫자든 '정했다' 로 처리해서 9999 를 넣은 사용자도 반영됐다고 읽었다.
    """
    _fake_cat_cache(monkeypatch, {"ok": True, "sits": {"flows_total": 145}})
    step = _step(
        _post({"doc_type": "sits", "source_root": str(tmp_path),
               "caps": {"max_flows": 9999}}),
        "cap_max_flows",
    )
    assert step["state"] == "ok"          # 막지는 않는다 — 사용자 결정이다
    assert step["measured"]["over_suggested"] is True
    assert "9999" in step["reason"] and "145" in step["reason"], step["reason"]


def test_lowering_a_cap_says_what_drops(tmp_path: Path) -> None:
    """낮추는 것도 결정이지만 **무엇이 빠지는지**는 말해야 한다.

    SUTS `max_sequences` 를 낮추면 MC/DC 부터 빠진다(`generators/suts.py:2043` 이 앞에서
    자르고 MC/DC 는 맨 끝 GAP 6). ASIL D 프로젝트에서 조용히 일어나면 안 된다.
    """
    step = _step(
        _post({"doc_type": "suts", "source_root": str(tmp_path),
               "caps": {"max_sequences": 6}}),
        "cap_max_sequences",
    )
    # "정했다" 를 "충분하다" 로 읽게 두지 않는다(degraded 는 차단이 아니다).
    assert step["state"] == "degraded", step
    # ⚠ 손실 기준은 생성기 **기본값 24** 가 아니라 전략 **카탈로그 전량 30** 이다.
    #   24 로 세면 실제 손실을 과소보고한다(24 는 카탈로그가 아니라 캡이다).
    assert step["measured"]["below_full"] == 24, step["measured"]
    assert "24" in step["reason"], step["reason"]
    # 무엇이 먼저 빠지는지가 같은 줄에서 읽혀야 한다.
    assert "MC/DC" in step["reason"], step["reason"]


def test_suggestion_comes_only_from_measurement(tmp_path: Path, monkeypatch) -> None:
    """권장값을 **지어내지 않는다** — 측정이 없으면 필드가 없다."""
    _fake_cat_cache(monkeypatch, None)
    step = _step(_post({"doc_type": "sits", "source_root": str(tmp_path)}), "cap_max_flows")
    assert "suggested" not in (step["measured"] or {})

    _fake_cat_cache(monkeypatch, {"ok": True, "sits": {"flows_total": 145}})
    step2 = _step(_post({"doc_type": "sits", "source_root": str(tmp_path)}), "cap_max_flows")
    assert step2["measured"]["suggested"] == 145


def test_measured_but_not_truncating_stays_ok(tmp_path: Path, monkeypatch) -> None:
    """쟀는데 안 잘리면 `ok` 다 — 없는 손실을 만들지 않는다(음성 대조군)."""
    _fake_cat_cache(monkeypatch, {
        "ok": True,
        "uds_category_caps": {"measured": True, "cap": 120,
                              "any_truncated": False, "truncated": {}},
    })
    step = _step(_post({"doc_type": "uds", "source_root": str(tmp_path)}),
                 "cap_max_items_per_category")
    assert step["state"] == "ok"
    assert "truncated" not in (step["measured"] or {})


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


class _ListingResolver:
    """`exists` 는 전부 False, `list_dir` 은 주어진 이름을 낸다. 호출 경로를 기록한다."""

    mode = "local"

    def __init__(self, names, raise_on_list: Exception | None = None) -> None:
        self.names = list(names)
        self.raise_on_list = raise_on_list
        self.listed: list[str] = []

    def exists(self, path: str) -> bool:
        return False

    def list_dir(self, path: str, pattern: str = "*", recursive: bool = False,
                 include_dirs: bool = False):
        self.listed.append(str(path))
        if self.raise_on_list is not None:
            raise self.raise_on_list
        return [str(Path(path) / n) for n in self.names]


class TestMissingTemplateNamesWhatIsActuallyThere:
    """양식이 없을 때 **그 폴더에 뭐가 있는지**를 화면이 말한다.

    2026-08-25 실측: `es95411_template` 이 가리키던 v1.02 산출물이 v2.01 세대로 교체되며
    파일명 자체가 바뀌어 사라졌는데, 화면은 "양식 파일을 찾지 못했습니다" 만 냈다. 그
    문장만으로는 ①이름이 바뀐 건지 ②폴더가 옮겨진 건지 ③배포된 적이 없는 건지 구분할 수
    없어, 사람이 U: 드라이브를 직접 열어야 했다. 같은 형태로 그날 두 번 걸렸다.
    """

    TPL_KEY = "coverage_report_template"          # doc_type `swut` 이 보는 키

    def _template_folder(self) -> str:
        from backend.services.swut_meta_resolver import load_meta_from_config
        meta = load_meta_from_config("HDPDM01") or {}
        return str(Path(str((meta.get("template_paths") or {})[self.TPL_KEY])).parent)

    def _reason(self, monkeypatch, resolver) -> tuple[str, str]:
        from backend.services import file_resolver as fr
        monkeypatch.setattr(fr, "get_resolver", lambda: resolver)
        data = _post({"doc_type": "swut", "form": {"project_id": "HDPDM01"}})
        step = _step(data, "report_template")
        assert step is not None, "양식 단계가 없다"
        # ⚠ `reason` 은 빈 값이면 아예 실리지 않는다(정상 단계) — `[...]` 로 읽으면 KeyError.
        return step["state"], step.get("reason", "")

    def test_reason_lists_the_actual_files(self, monkeypatch) -> None:
        r = _ListingResolver(["(KJPDS02_SwTR) Software Test Result_v2.01_260629_R.xlsx",
                              "(KJPDS02_SwTCV) Software Test Coverage Result_v2.01_R.xlsx"])
        state, reason = self._reason(monkeypatch, r)
        assert state == "missing", reason
        assert "SwTR" in reason and "SwTCV" in reason, (
            f"폴더의 실제 파일이 사유에 없다 — 사람이 드라이브를 직접 열어야 한다: {reason}")

    def test_ok_template_costs_no_extra_listing(self, monkeypatch) -> None:
        """⚠ 있을 때도 폴더를 훑으면 U: 드라이브 IPC 왕복이 **매 판정마다** 늘어난다."""
        r = _ListingResolver([])
        r.exists = lambda path: True          # type: ignore[method-assign]
        folder = self._template_folder()
        self._reason(monkeypatch, r)
        assert folder not in r.listed, f"양식이 있는데도 폴더를 훑었다: {r.listed}"

    def test_listing_failure_is_reported_not_swallowed(self, monkeypatch) -> None:
        """'폴더도 못 봤다' 와 '폴더가 비었다' 는 다른 사실이다."""
        state, reason = self._reason(
            monkeypatch, _ListingResolver([], raise_on_list=TimeoutError("U: 응답 없음")))
        assert state == "missing", reason
        assert "확인하지 못했습니다" in reason and "TimeoutError" in reason, reason

    def test_empty_listing_does_not_claim_the_folder_exists(self, monkeypatch) -> None:
        """resolver 계약상 **빈 폴더와 없는 폴더는 구분되지 않는다** — 단정하면 거짓말이다."""
        state, reason = self._reason(monkeypatch, _ListingResolver([]))
        assert state == "missing", reason
        assert "비어 있거나 폴더 자체가 없습니다" in reason, reason

    def test_long_listing_says_how_many_were_elided(self) -> None:
        """조용한 절단은 '그 폴더엔 이것뿐' 으로 오독된다."""
        from backend.routers.docgen_preflight import _folder_contents_hint
        r = _ListingResolver([f"f{i:02}.xlsm" for i in range(12)])
        hint = _folder_contents_hint(r, str(Path("U:/x/y") / "target.xlsm"), cap=8)
        assert "f00.xlsm" in hint and "f07.xlsm" in hint
        assert "f08.xlsm" not in hint, "cap 을 안 지켰다"
        assert "외 4건" in hint, f"절단을 침묵했다: {hint}"


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
    from backend.routers import swit as swit_mod
    from backend.routers import swut as swut_mod
    from tests.unit._source_probe import source_of
    for mod, fn in ((swut_mod, "_resolve_swut_log_folders"), (swit_mod, "_resolve_swit_log_folders")):
        src = source_of(getattr(mod, fn))
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
    from backend.services.swut_meta_resolver import resolve_swuts_path
    from tests.unit._source_probe import source_of
    src = source_of(resolve_swuts_path)
    assert "config_spec_path" in src
    assert 'cfg.get("swits_docx_path")' not in src


# ── SUTS 시퀀스 상한 ↔ ASIL (2026-08-30) ────────────────────────────────────
#
# `generators/suts` 는 MC/DC 전략을 목록 **맨 끝**에 붙이고 `strategies[:max_seq]` 로
# 앞에서 자른다. 상한이 후보 최대보다 작으면 MC/DC 가 가장 먼저 사라지는데, ASIL D 는
# MC/DC 가 필수(ISO 26262-6)라 그 프로젝트에선 규격 미달로 직결된다. 게이트는 이걸
# 오래 **일반론**으로만 적었다 — QM 전용 프로젝트엔 소음이고 ASIL D 프로젝트에선
# 몇 개가 걸리는지 말하지 못했다.

def _suts_with_grades(tmp_path: Path, monkeypatch, by_grade, caps=None) -> dict | None:
    _fake_cat_cache(monkeypatch, {
        "suts_asil": {"measured": True, "units": 100, "graded": sum(by_grade.values()),
                      "fuzzy": 0, "fuzzy_conflict": 0, "by_grade": by_grade, "ungraded": 0},
    })
    return _step(_post({"doc_type": "suts", "source_root": str(tmp_path),
                        "caps": caps or {}}), "cap_max_sequences")


def test_sequence_cap_names_the_asil_d_functions_at_risk(tmp_path: Path, monkeypatch) -> None:
    """ASIL D 가 있고 상한이 후보 최대보다 작으면 **그 수를 말한다**."""
    s = _suts_with_grades(tmp_path, monkeypatch, {"D": 37, "B": 12, "QM": 51})
    assert s["measured"]["asil_d"] == 37
    assert s["measured"]["mcdc_at_risk"] is True
    assert "37개" in s["reason"] and "MC/DC" in s["reason"], s["reason"]


def test_sequence_cap_does_not_cry_wolf_without_asil_d(tmp_path: Path, monkeypatch) -> None:
    """ASIL D 가 없으면 경고하지 않는다 — 없는 위험을 남기면 진짜 경고가 묻힌다."""
    s = _suts_with_grades(tmp_path, monkeypatch, {"QM": 80, "A": 20})
    assert s["measured"]["asil_d"] == 0
    assert s["measured"]["mcdc_at_risk"] is False
    assert "ASIL D 함수는 없습니다" in s["reason"], s["reason"]


def test_sequence_cap_at_full_has_no_mcdc_risk(tmp_path: Path, monkeypatch) -> None:
    """상한을 후보 최대까지 올리면 ASIL D 가 있어도 MC/DC 는 안 잘린다.

    ⚠ 그때 **앞의 정적 경고문을 그대로 두면 안 된다**. `effect` 는 기본값을 말한 문장이라
    (`MC/DC 가 맨 끝이라 잘립니다`), 사용자가 상한을 올린 `ok` 행에 살아 있는 경고로
    붙으면 같은 행이 두 말을 한다.
    """
    s = _suts_with_grades(tmp_path, monkeypatch, {"D": 37}, caps={"max_sequences": 30})
    assert s["state"] == "ok", s
    assert s["measured"]["asil_d"] == 37
    assert s["measured"]["mcdc_at_risk"] is False, s["measured"]
    assert "잘리지 않습니다" in s["reason"], s["reason"]


def test_unmeasured_asil_is_not_read_as_no_asil_d(tmp_path: Path) -> None:
    """등급을 **안 쟀다**를 "ASIL D 없음" 으로 접지 않는다.

    접으면 ASIL D 프로젝트에서 "ASIL D 함수는 없습니다" 라는 거짓 안심 문구가 뜬다.
    """
    s = _step(_post({"doc_type": "suts", "source_root": str(tmp_path)}), "cap_max_sequences")
    assert "asil_d" not in (s["measured"] or {}), s["measured"]
    assert "없습니다" not in s["reason"].replace("빠집니다", ""), s["reason"]


# ── SUTS 시험 범위: 게이트와 생성기가 같은 규칙을 쓰는가 (2026-08-31) ────────
#
# 예전엔 게이트가 `== "source"`, 생성기가 `== "suds" else 소스 전체` 라 **서로 여집합**을
# 봤다. 그래서 `sud` 같은 값 하나에 게이트는 "정본 기준", 생성기는 "소스 전체" 로 반대말을
# 했고, 틀리는 방향이 **넓은 쪽**이라 정본에 없는 함수가 ISO 26262 산출물에 들어갔다.

def _scope_step(tmp_path: Path, stored):
    return _step(_post({"doc_type": "suts", "source_root": str(tmp_path),
                        "caps": {"suts_scope": stored} if stored is not None else {}}), "scope")


@pytest.mark.parametrize("stored,expect", [
    (None, "suds"), ("", "suds"), ("suds", "suds"), ("source", "source"),
    ("SOURCE", "source"), (" source ", "source"),
])
def test_scope_row_matches_the_generator_rule(tmp_path: Path, stored, expect) -> None:
    """게이트의 판정이 생성기의 `normalize_scope` 와 **글자 그대로 같아야** 한다."""
    from generators.suts import normalize_scope

    s = _scope_step(tmp_path, stored)
    assert s["measured"]["value"] == expect
    assert normalize_scope(stored)[0] == expect, "생성기와 게이트가 갈렸다"


def test_unknown_scope_falls_back_narrow_and_says_so(tmp_path: Path) -> None:
    """모르는 값은 **좁은 쪽**(정본 기준)으로 떨어지고, 그 사실이 화면에 나온다.

    넓은 쪽으로 떨어지면 정본에 없는 함수가 규격서에 조용히 들어간다.
    """
    from generators.suts import normalize_scope

    s = _scope_step(tmp_path, "sud")
    assert s["measured"]["value"] == "suds"
    assert s["measured"]["stored"] == "sud"
    assert s["state"] == "degraded", s        # 조용히 `ok` 로 두지 않는다
    assert "알 수 없어" in s["reason"], s["reason"]
    assert normalize_scope("sud") == ("suds", "sud")


# ── 측정 ↔ 게이트 캐시 왕복 (2026-08-31) ────────────────────────────────────
#
# 캐시 키가 오래 `source_root` 하나였다. `measure()` 는 SwDS·SwRS·SwUDS 를 읽어
# `sts_mapping`·`sits` 를 만드는데, 설정에서 SwDS 를 바꿔도 소스 루트가 같으면 캐시가
# 그대로 맞아 **이미 교체된 문서로 잰 수치**를 최대 15분 동안 "지금 값" 으로 보고했다.
#
# 키에 경로를 넣으면 새 위험이 생긴다: 측정과 조회가 각자 경로를 구하면 문자열이 조금만
# 달라도 캐시가 영영 안 맞아 게이트가 **계속 `unmeasured`** 다. 그래서 왕복을 본다.

def test_measuring_then_asking_the_gate_finds_the_cache(tmp_path: Path, monkeypatch) -> None:
    """측정 한 번 → 게이트가 **그 결과를 본다**. 두 쪽이 같은 키를 써야만 성립한다."""
    from backend.routers import docgen_preflight as dp
    from backend.services import docgen_test_materials as tm

    tm.clear_cache()
    monkeypatch.setattr(dp._cov, "measure", lambda *_a, **_k: {"ok": True})

    seen: dict = {}

    def _fake_measure(root, *, sds_path="", srs_path="", uds_path=""):
        seen.update(sds=sds_path, srs=srs_path, uds=uds_path)
        res = {"ok": True, "sits": {"flows_total": 7, "cap": 120},
               "uds_category_caps": {"measured": True, "cap": 120,
                                     "any_truncated": False, "truncated": {}},
               "uds_file_scan": {"measured": True, "cap": 1200, "truncated": False}}
        with tm._CACHE_LOCK:
            tm._CACHE[tm._key(root, sds_path, srs_path, uds_path)] = (time.time(), res)
        return res

    monkeypatch.setattr(dp._tm, "measure", _fake_measure)

    # ⚠ `doc_paths` 의 키는 `srs`/`sds`/`uds`(레지스트리 어휘)이지 입력 키가 아니다.
    #   입력 키를 쓰면 세 경로가 **양쪽 다 빈 문자열**이 되어 키가 우연히 맞고, 이 테스트는
    #   아무것도 확인하지 못한 채 통과한다(실제로 그렇게 통과했다 — 뮤테이션이 잡아냈다).
    doc_paths = {"sds": "U:/d/SwDS.docx", "srs": "U:/d/SwRS.docx", "uds": "U:/d/SwUDS.docx"}
    out = dp.docgen_measure_source(dp.MeasureSourceRequest(
        source_root=str(tmp_path), doc_type="uds", doc_paths=doc_paths))
    assert seen, "측정이 아예 안 돌았다"
    # 서버가 세 경로를 **실제로 해석했는가**. 빈 문자열이면 아래 왕복이 무의미해진다.
    assert seen == {"sds": "U:/d/SwDS.docx", "srs": "U:/d/SwRS.docx",
                    "uds": "U:/d/SwUDS.docx"}, seen
    assert out["measured_with"]["sds_path"] == "U:/d/SwDS.docx"

    # 같은 두 값을 게이트에 준다 — 서버가 같은 방식으로 해석해 캐시를 찾아야 한다.
    caps = [s for s in _post({"doc_type": "uds", "source_root": str(tmp_path),
                              "doc_paths": doc_paths})["steps"]
            if s["id"].startswith("cap_")]
    assert caps and all(c["state"] != "unmeasured" for c in caps), (
        f"측정했는데 게이트가 못 찾았다 = 두 쪽 키가 갈렸다: "
        f"{[(c['id'], c['state']) for c in caps]}")


def test_changing_a_document_invalidates_the_measurement(tmp_path: Path, monkeypatch) -> None:
    """SwDS 를 다른 문서로 바꾸면 **옛 측정을 재사용하지 않는다**.

    재사용하면 게이트가 이미 교체된 문서로 잰 수치를 "지금 값" 으로 보고한다.
    """
    from backend.services import docgen_test_materials as tm

    tm.clear_cache()
    with tm._CACHE_LOCK:
        tm._CACHE[tm._key(str(tmp_path), "U:/old.docx", "", "")] = (time.time(), {"ok": True})

    assert tm.has_cached(str(tmp_path), sds_path="U:/old.docx")
    assert not tm.has_cached(str(tmp_path), sds_path="U:/new.docx"), "문서를 바꿨는데 옛 측정이 맞았다"
    # 대소문자·구분자 차이만으로 캐시를 놓치지는 않는다(윈도 경로).
    assert tm.has_cached(str(tmp_path), sds_path=r"U:\OLD.docx")


# ── 프로젝트 ASIL 등급 (2026-08-31) ─────────────────────────────────────────
#
# 상한과 달리 이 값은 **문서 내용을 바꾼다**: `generators/sts.py:1719` 가 요구별 ASIL
# 빈 칸을 이 값으로 역채움하고, `is_safety_asil` 판정이 시험 생성 갈래를 가른다.
# 백엔드는 오래 `Form("")` 로 받고 있었고 Sw* 빌더 폼엔 입력칸이 있는데, 문서 4종만
# 배선이 빠져 **항상 빈 값**으로 생성됐다.

# ⚠ UDS 는 뺀다. 그 핸들러는 `asil_level` 을 받지 않고, UDS 의 ASIL 은 함수별 증거에서
#   온다(`uds_generator:1408`). 처음엔 4종에 다 냈다가 **거짓 통제**를 만들었다 —
#   프론트가 보내도 FastAPI 가 버리고 화면만 초록이 됐다. 그 회귀는
#   `test_docgen_cap_wiring_parity.py::test_every_handmade_decision_row_reaches_its_handler`
#   가 핸들러 시그니처와 대조해 막는다.
@pytest.mark.parametrize("doc_type", ["sts", "suts", "sits"])
def test_missing_asil_is_a_decision_not_a_default(tmp_path: Path, doc_type: str) -> None:
    """비어 있으면 `needed` 이고, **QM 으로 채우지 않는다**.

    근거 없는 등급을 지어내면 하류가 그걸 사실로 쓴다 — 이 저장소가 사용자 결정으로
    못박은 규약이다("none 은 none, tbd 면 tbd").
    """
    s = _step(_post({"doc_type": doc_type, "source_root": str(tmp_path)}), "asil_level")
    assert s is not None, f"{doc_type}: ASIL 행 자체가 없다"
    assert s["state"] == "needed", s
    assert s["measured"].get("value") is None, s["measured"]
    assert "QM" in s["reason"] and "지어내지 않습니다" in s["reason"], s["reason"]


def test_chosen_asil_is_echoed_back(tmp_path: Path) -> None:
    """정하면 그 값을 되읽어 보인다 — 없으면 반영됐는지 알 수 없다."""
    s = _step(_post({"doc_type": "sts", "source_root": str(tmp_path), "asil_level": "d"}),
              "asil_level")
    assert s["state"] == "ok"
    assert s["measured"]["value"] == "D", s["measured"]     # 대소문자 정규화
    assert "**D**" in s["reason"], s["reason"]


def test_asil_row_is_absent_for_test_report_docs(tmp_path: Path) -> None:
    """음성 대조군 — 시험 결과 6종은 빌더 폼이 ASIL 을 이미 받는다(`swut_form`).
    여기에도 행을 내면 같은 값을 두 곳에서 묻는 꼴이 된다."""
    assert _step(_post({"doc_type": "swut", "source_root": str(tmp_path)}), "asil_level") is None


# ── 실제로 쓸 템플릿 (2026-08-31) ───────────────────────────────────────────
#
# 생성은 `docgen_template_source.choose_template_source` 로 템플릿을 정하고, 그 규칙은
# **정본(납품본)이 있으면 정본을 쓴다**(호출부 5곳 전부 `prefer_reference` 기본값 True).
# 그런데 게이트는 오래 설정한 표준 템플릿 경로만 보여 줬다 — 정본이 등록돼 있으면
# **쓰이지도 않을 파일**에 ✓ 를 주고, 그 표준 템플릿이 접근 불가면 막힌 것처럼 그렸다
# (실제 생성은 정본으로 멀쩡히 돈다). 템플릿은 사소하지 않다: 표지·이력·Introduction
# (표기 규약 표)이 전부 거기서 온다.

def _tpl_rows(tmp_path: Path, doc_paths: dict, monkeypatch=None) -> dict:
    if monkeypatch is not None:
        from backend.routers import docgen_preflight as mod
        monkeypatch.setattr(mod, "_probe_path",
                            lambda _r, _p: {"state": "ok", "reason": ""})
    data = _post({"doc_type": "suts", "source_root": str(tmp_path), "doc_paths": doc_paths})
    return {s["id"]: s for s in data["steps"] if s["id"] in ("template", "template_source")}


def test_reference_doc_wins_and_the_gate_says_so(tmp_path: Path, monkeypatch) -> None:
    """정본이 등록돼 있으면 **정본**을 이름 대고, 표준 템플릿이 가려졌다고 말한다."""
    rows = _tpl_rows(tmp_path, {"suts_template": "U:/tpl/std.xlsm",
                                "suts": "U:/deliv/ref.xlsm"}, monkeypatch)
    src = rows["template_source"]
    assert src["value"] == "U:/deliv/ref.xlsm", src
    assert src["measured"]["shadowed"] is True
    assert "쓰이지 않습니다" in src["reason"], src["reason"]
    # 설정한 템플릿 행은 그대로 남는다 — 두 행이 서로 다른 질문에 답한다.
    assert rows["template"]["value"] == "U:/tpl/std.xlsm"


def test_standard_template_is_not_falsely_shadowed(tmp_path: Path, monkeypatch) -> None:
    """음성 대조군 — 정본이 없으면 표준 템플릿이 그대로 쓰이고 경고하지 않는다.

    없는 경고를 남기면 진짜 경고가 묻힌다.
    """
    src = _tpl_rows(tmp_path, {"suts_template": "U:/tpl/std.xlsm"}, monkeypatch)["template_source"]
    assert src["value"] == "U:/tpl/std.xlsm"
    assert src["measured"].get("shadowed") is None
    assert "쓰이지 않습니다" not in src["reason"], src["reason"]
    # 자기 자신으로 폴백한다는 헛말을 하지 않는다.
    assert "표준 템플릿으로 한 번 더" not in src["reason"], src["reason"]


def test_unreadable_chosen_template_is_not_reported_as_fine(tmp_path: Path) -> None:
    """고른 파일을 **못 여는데** `ok` 로 그리지 않는다.

    선택만 공시하고 접근을 안 보면, 못 여는 파일을 "이걸로 만듭니다" 라고 이름 댄다.
    """
    src = _tpl_rows(tmp_path, {"suts": "U:/deliv/ref.xlsm"})["template_source"]
    assert src["state"] == "degraded", src
    assert "열지 못합니다" in src["reason"], src["reason"]


def test_no_template_at_all_is_degraded_not_ok(tmp_path: Path) -> None:
    """템플릿이 아예 없으면 서식 없이 나간다 — 그건 `ok` 가 아니다."""
    src = _tpl_rows(tmp_path, {})["template_source"]
    assert src["state"] == "degraded"
    assert src.get("value", "") == ""
    assert "서식 없이" in src["reason"]


def test_reference_lookup_matches_the_generation_request(tmp_path: Path, monkeypatch) -> None:
    """정본 경로의 우선순위가 **생성 요청과 같아야** 한다.

    프론트는 `docPaths[docType] || linkedDocs[docType]` 로 고른다. 갈리면 게이트가
    이번 생성에 쓰이지 않을 파일을 "실제로 쓸 템플릿" 이라고 이름 댄다.
    """
    from backend.routers import docgen_preflight as mod

    monkeypatch.setattr(mod, "_linked_docs", lambda _r: {"suts": "U:/reg/from_registry.xlsm"})
    # 설정(doc_paths)이 레지스트리를 이긴다.
    src = _tpl_rows(tmp_path, {"suts": "U:/cfg/from_settings.xlsm"}, monkeypatch)["template_source"]
    assert src["value"] == "U:/cfg/from_settings.xlsm", src
    # 설정이 비면 레지스트리로 떨어진다.
    src2 = _tpl_rows(tmp_path, {}, monkeypatch)["template_source"]
    assert src2["value"] == "U:/reg/from_registry.xlsm", src2


# ── 캡의 "전량" 은 카탈로그다 — 생성기 기본값이 아니다 (2026-08-31) ──────────────
#
# SITS `max_subcases` 의 `generator`(14)는 카탈로그가 아니라 **캡**이라, 그걸로 전량을
# 재면 `max_subcases=14` 가 손실 없음(ok)으로 판정된다. 실제로는 15번째 후보가 잘린다.
# 게다가 15 를 고른 사용자에게는 "14 이상은 더 담을 것이 없습니다" 라고 **틀린 말**이 나갔다.

def test_sits_subcase_cap_measures_against_the_catalog_not_the_generator_default(
        tmp_path: Path) -> None:
    """생성기 기본값(14)으로 맞춰도 **손실이 남아 있다고** 말해야 한다."""
    data = _post({"doc_type": "sits", "source_root": str(tmp_path),
                  "caps": {"max_subcases": 14}})
    step = _step(data, "cap_max_subcases")
    assert step is not None
    assert step["state"] != "ok", (
        "생성기 기본값 14 는 후보 15종 중 하나를 자른다 — ok 면 그 손실이 사라진다")
    assert step["measured"].get("below_full") == 1
    assert step["measured"].get("suggested") == 15


def test_sits_subcase_cap_is_ok_only_at_the_catalog_max(tmp_path: Path) -> None:
    """15 여야 비로소 손실이 없다 — 그 위는 '더 담을 것이 없다'."""
    ok = _step(_post({"doc_type": "sits", "source_root": str(tmp_path),
                      "caps": {"max_subcases": 15}}), "cap_max_subcases")
    assert ok is not None and ok["state"] == "ok"
    assert not ok["measured"].get("over_suggested")

    over = _step(_post({"doc_type": "sits", "source_root": str(tmp_path),
                        "caps": {"max_subcases": 16}}), "cap_max_subcases")
    assert over is not None and over["measured"].get("over_suggested") is True


# ── 템플릿 출처: 게이트가 **선택을 반영해서** 이름을 댄다 (2026-08-31) ────────
#
# 이 행은 오래 `prefer_reference=True` 하드코딩으로 계산됐고, UDS 핸들러는
# `reference_doc_path` 를 **선언조차 하지 않았다**. 그래서 게이트는 "정본을 씁니다 /
# 설정한 표준 템플릿은 쓰이지 않습니다" 라고 했는데 실제 UDS 생성은 정확히 반대로
# 했다 — 게이트가 산출물과 반대말을 한 유일한 지점이었다.


class TestTemplateSourceRow:
    _PATHS = {"uds": "D:/ref/KJ_SUDS_v1.02.docx", "uds_template": "D:/tpl/std.docx"}

    def _row(self, caps=None):
        return _step(_post({"doc_type": "uds", "source_root": "",
                            "doc_paths": self._PATHS, "caps": caps or {}}),
                     "template_source")

    def test_it_is_a_decision_not_an_input(self) -> None:
        """자료가 부족한 게 아니라 **사람이 정하는** 축이라 캡·범위와 같은 자리에 온다."""
        assert self._row()["phase"] == "decision"

    def test_the_choice_actually_changes_the_named_file(self) -> None:
        assert self._row()["value"] == self._PATHS["uds"]
        assert self._row({"template_source": "standard"})["value"] == self._PATHS["uds_template"]
        assert self._row({"template_source": "reference"})["value"] == self._PATHS["uds"]

    def test_the_row_carries_its_options_so_the_screen_does_not_invent_them(self) -> None:
        """옵션을 화면이 들고 있으면 서버가 안 받는 값을 제시할 수 있다."""
        m = self._row()["measured"]
        assert m["choice"] == "template_source"
        assert {o["value"] for o in m["options"]} == {"", "reference", "standard"}

    def test_it_reports_what_the_user_picked(self) -> None:
        assert self._row()["measured"]["picked"] == ""
        assert self._row({"template_source": "standard"})["measured"]["picked"] == "standard"

    def test_shadow_warning_follows_the_choice(self) -> None:
        """정본을 고른 경우에만 "표준 템플릿은 쓰이지 않습니다" 가 참이다."""
        assert "쓰이지 않습니다" in self._row()["reason"]
        assert "쓰이지 않습니다" not in self._row({"template_source": "standard"})["reason"]

    @pytest.mark.parametrize("doc_type", ["uds", "sts", "suts", "sits"])
    def test_every_gate_doc_gets_the_row(self, doc_type: str) -> None:
        row = _step(_post({"doc_type": doc_type, "source_root": "",
                           "doc_paths": {doc_type: "D:/ref/x.docx"}}), "template_source")
        assert row is not None and row["measured"]["choice"] == "template_source", doc_type


# ── 측정 신선도: 언제 잰 값인가 (2026-08-31) ────────────────────────────────

class TestMaterialsFreshnessRow:
    def _row(self, monkeypatch, tm_payload, tmp_path):
        _fake_cat_cache(monkeypatch, tm_payload)
        return _step(_post({"doc_type": "sits", "source_root": str(tmp_path)}),
                     "materials_freshness")

    def test_verified_measurement_says_changes_are_detected(self, tmp_path, monkeypatch):
        row = self._row(monkeypatch,
                        {"ok": True, "measured_at": time.time() - 300,
                         "freshness": "verified"}, tmp_path)
        assert row is not None and row["state"] == "ok"
        assert row["measured"]["age_minutes"] == 5
        assert "다시 잽니다" in row["reason"]

    def test_ttl_only_measurement_admits_it_cannot_tell(self, tmp_path, monkeypatch):
        """모르는 것을 최신이라고 말하지 않는다 — cloudium 은 mtime 을 못 읽는다."""
        row = self._row(monkeypatch,
                        {"ok": True, "measured_at": time.time() - 60,
                         "freshness": "ttl_only"}, tmp_path)
        assert row is not None and row["state"] == "degraded"
        assert "감지하지 못합니다" in row["reason"]
        # 해소 경로를 준다 — 못 잡는다고만 하고 끝내면 사용자가 할 일이 없다.
        assert "measure_source" in {a.get("kind") for a in (row.get("actions") or [])}

    def test_no_row_when_the_measurement_time_is_unknown(self, tmp_path, monkeypatch):
        """시각을 모르면 **행을 안 낸다** — "0분 전" 은 방금 쟀다는 거짓 주장이다."""
        assert self._row(monkeypatch, {"ok": True}, tmp_path) is None


def test_gate_does_not_walk_the_source_tree_twice_for_the_same_answer(
        tmp_path: Path, monkeypatch) -> None:
    """신선도 서명은 소스 트리를 **통째로 stat** 한다(실측 99파일 33ms).

    `has_cached()` 로 물은 뒤 `cached()` 로 또 묻던 자리가 두 곳이라 한 요청에 4번 걸었다.
    답이 같은 물음을 두 번 하지 않는다 — 성능이자, 두 물음 사이에 파일이 바뀌면
    **같은 응답 안에서 두 판정이 갈릴 수 있다**는 정합 문제이기도 하다.
    """
    from backend.routers.docgen_preflight import PreflightRequest, _compute_preflight
    from backend.services import docgen_test_materials as tm_mod

    calls = []
    real = tm_mod.signature_for
    monkeypatch.setattr(tm_mod, "signature_for",
                        lambda *a, **k: (calls.append(1), real(*a, **k))[1])
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.c").write_text("int f(void){return 0;}", encoding="utf-8")
    _compute_preflight(PreflightRequest(doc_type="sits", source_root=str(src)))
    assert len(calls) <= 2, f"한 요청에 서명을 {len(calls)}번 계산한다"
