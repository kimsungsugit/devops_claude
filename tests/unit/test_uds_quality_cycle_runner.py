# tests/unit/test_uds_quality_cycle_runner.py
"""UDS 품질 사이클 러너(`scripts/uds/uds_quality_cycle.py`)의 **누락 방지** 계약.

## 왜 이 테스트가 있나

러너의 `_compare` 는 비교할 축 이름을 **하드코딩 목록 12개**로 들고 있었다. 생산자에
축을 더해도 그 목록에 안 적으면 러너가 조용히 빼먹는다 — 실제로 그랬다:
`input_real_fill`/`output_real_fill`(실질 인터페이스 채움)을 `_compute_quick_quality_gate`
가 내는데 러너는 한 번도 본 적이 없었다. "지표를 추가하는 것과 지표가 도달하는 것은
다른 문제" 가 이 저장소에서 반복되는 결함이라, 목록 대신 **합집합**으로 바꾸고 그 성질을
여기서 고정한다.

두 번째 축은 **미측정과 0 의 구분**이다. 한쪽에만 있는 축을 `0.0` 으로 채우면 새 축이
들어온 라운드마다 "+18.9 개선" 같은 거짓 델타가 찍힌다.

세 번째는 **산출물 충실도**다. 게이트 rates 는 전부 payload 를 재므로 payload 가
완벽하면 문서가 비어 있어도 만점이다(실측 run 660·661 = 반영 0/5 인데 점수 100.0).
그 축은 응답 본문에 없고 라이터 sidecar 에만 있어서 러너가 되읽는다.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_RUNNER = _ROOT / "scripts" / "uds" / "uds_quality_cycle.py"
_PS1 = _ROOT / "scripts" / "uds" / "run_quality_cycle.ps1"


@pytest.fixture(scope="module")
def mod():
    if not _RUNNER.is_file():
        pytest.skip(f"러너가 없다: {_RUNNER}")
    spec = importlib.util.spec_from_file_location("_uds_quality_cycle_under_test", _RUNNER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _run(rates, path=""):
    return {"status_code": 200, "response": {"path": path, "quick_quality_gate": {
        "rates": dict(rates), "counts": {"total_functions": 10}}}}


_BASE = {"called_fill": 50.0, "calling_fill": 60.0, "input_fill": 98.3,
         "output_fill": 100.0, "description_fill": 70.0, "asil_fill": 40.0,
         "related_fill": 55.0}


class TestNewAxesAreNotSilentlyDropped:
    def test_axis_present_in_both_is_compared(self, mod):
        prev = _run({**_BASE, "input_real_fill": 18.9})
        cur = _run({**_BASE, "input_real_fill": 30.0})
        row = mod._compare(prev, cur)["rates"]["input_real_fill"]
        assert (row["prev"], row["cur"], row["delta"]) == (18.9, 30.0, 11.1)

    def test_unknown_future_axis_still_appears(self, mod):
        """표시 순서 상수는 **필터가 아니다** — 모르는 축도 비교에 나와야 한다.
        이게 깨지면 '목록에 안 적으면 사라진다' 는 원래 결함으로 되돌아간 것이다."""
        prev = _run({**_BASE, "brand_new_axis_fill": 10.0})
        cur = _run({**_BASE, "brand_new_axis_fill": 12.0})
        assert "brand_new_axis_fill" in mod._compare(prev, cur)["rates"]

    def test_ordered_keys_is_display_order_only(self, mod):
        """상수에 적힌 축은 전부 실제 생산자 이름이어야 한다(오타 방지)."""
        assert "input_real_fill" in mod._ORDERED_RATE_KEYS
        assert "output_real_fill" in mod._ORDERED_RATE_KEYS
        assert len(set(mod._ORDERED_RATE_KEYS)) == len(mod._ORDERED_RATE_KEYS)


class TestMissingIsNotZero:
    def test_new_axis_gets_none_delta_not_a_fake_improvement(self, mod):
        """cur 에만 있는 축을 `0.0 → 18.9` 로 적으면 **없던 개선**이 기록된다."""
        row = mod._compare(_run(_BASE), _run({**_BASE, "input_real_fill": 18.9}))["rates"]["input_real_fill"]
        assert row["delta"] is None and "신규" in row["note"]

    def test_removed_axis_is_flagged_too(self, mod):
        row = mod._compare(_run({**_BASE, "gone_fill": 5.0}), _run(_BASE))["rates"]["gone_fill"]
        assert row["delta"] is None and row["note"] == "prev 에만 있음"

    def test_unchanged_rates_give_zero_delta(self, mod):
        """음성 대조군 — 같은 값이면 델타 0. 이걸 안 보면 '항상 None' 도 위를 통과한다."""
        rates = mod._compare(_run(_BASE), _run(_BASE))["rates"]
        assert all(r["delta"] == 0.0 for r in rates.values()), rates

    def test_regression_still_soft_fails(self, mod):
        """기존 계약 회귀 방지 — -3.0%p 초과 하락은 여전히 soft_fail 이어야 한다."""
        cmp_ = mod._compare(_run(_BASE), _run({**_BASE, "input_fill": 80.0}))
        assert cmp_["soft_fail"] and "REGRESSION_INPUT_FILL" in cmp_["soft_fail_reasons"]


class TestArtifactFidelity:
    def test_no_output_path_is_unmeasured(self, mod):
        f = mod._artifact_fidelity(_run(_BASE))
        assert f["measured"] is False and "경로" in f["reason"]

    def test_absent_sidecar_is_unmeasured(self, mod, tmp_path):
        f = mod._artifact_fidelity(_run(_BASE, path=str(tmp_path / "x.docx")))
        assert f["measured"] is False and "sidecar" in f["reason"]

    @pytest.mark.parametrize("payload,matched", [(0, 0), (None, 3), ("350", 3), (350, None)])
    def test_bad_numbers_are_unmeasured(self, mod, tmp_path, payload, matched):
        """분모/분자가 성립 안 하면 **대조 불가**다. 0% 로 적으면 거짓이 남는다."""
        out = tmp_path / "x.docx"
        (tmp_path / "x.docx.gen_stats.json").write_text(
            json.dumps({"payload_functions": payload, "matched_functions": matched}), encoding="utf-8")
        assert mod._artifact_fidelity(_run(_BASE, path=str(out)))["measured"] is False

    def test_real_run_674_is_reproduced(self, mod, tmp_path):
        """실측 run 674 재현 — 350개 중 252개 = 72.0%."""
        out = tmp_path / "x.docx"
        (tmp_path / "x.docx.gen_stats.json").write_text(json.dumps({
            "payload_functions": 350, "matched_functions": 252,
            "unmatched_payload_count": 98, "empty_heading_count": 149}), encoding="utf-8")
        f = mod._artifact_fidelity(_run(_BASE, path=str(out)))
        assert f["measured"] is True and f["artifact_match_pct"] == 72.0
        assert f["unmatched_payload_count"] == 98

    def test_compare_carries_both_sides(self, mod, tmp_path):
        out = tmp_path / "x.docx"
        (tmp_path / "x.docx.gen_stats.json").write_text(
            json.dumps({"payload_functions": 5, "matched_functions": 0}), encoding="utf-8")
        af = mod._compare(_run(_BASE), _run(_BASE, path=str(out)))["artifact_fidelity"]
        assert af["prev"]["measured"] is False
        assert af["cur"]["artifact_match_pct"] == 0.0, "실측 run 660·661 = 반영 0/5"


class TestWrapperTargetsThisRepo:
    def test_ps1_does_not_hardcode_another_repository(self):
        """`run_quality_cycle.ps1` 은 다른 저장소의 python/script 를 하드코딩했었다.
        그대로 두면 여기서 고친 게이트가 결과에 **반영되지 않는다**."""
        if not _PS1.is_file():
            pytest.skip("ps1 없음")
        src = _PS1.read_text(encoding="utf-8", errors="replace")
        live = [ln for ln in src.splitlines()
                if not ln.lstrip().startswith("#") and "260105" in ln]
        assert not live, f"다른 저장소 경로가 살아 있다: {live}"
        assert "$PSScriptRoot" in src, "저장소 루트를 파일 기준으로 잡아야 한다"


class TestBaselineIsFailClosed:
    """⚠ 예전엔 `main()` 이 응답을 **검사 없이** 베이스라인으로 저장했다.

    실측(2026-08-25): 인증이 없어 401 이 왔는데 `[baseline] created` + exit 0 이었다.
    그 뒤 모든 비교가 거짓 기준선 위에서 돌게 된다. 저장소에 남은 최신 베이스라인이
    2026-02 인 것도 같은 이유로 보인다 — 커밋 `1b6bb99`(2026-08-04) 이후 이 러너는
    한 번도 성공한 적이 없는데 아무도 몰랐다.
    """

    def test_401_is_not_usable_as_a_baseline(self, mod):
        run = {"status_code": 401, "response": {"ok": False, "error": {
            "code": "AUTH_REQUIRED", "message": "Authorization Bearer token 필요"}}}
        reasons = mod._unusable_reasons(run)
        assert reasons and "401" in reasons[0]
        assert "Bearer" in reasons[0], "사유에 원문을 실어야 다음 사람이 바로 고친다"

    def test_zero_functions_is_not_usable(self, mod):
        run = _run(_BASE)
        run["response"]["quick_quality_gate"]["counts"] = {"total_functions": 0}
        assert any("함수 0개" in r for r in mod._unusable_reasons(run))

    def test_healthy_run_is_usable(self, mod):
        """음성 대조군 — 정상 응답까지 막으면 러너가 아예 못 돈다."""
        assert mod._unusable_reasons(_run(_BASE)) == []


class TestTokenIsNotFabricated:
    def test_explicit_user_wins(self, mod):
        assert mod._resolve_user("someone") == "someone"

    def test_falls_back_to_first_admin(self, mod):
        """`--user` 를 안 주면 admin_users.json 에서 읽는다 — 사람 이름을 스크립트에
        하드코딩하지 않는다."""
        assert mod._resolve_user("").strip()

    def test_missing_user_fails_loudly(self, mod, monkeypatch):
        """사용자가 없으면 그 토큰은 `USER_REVOKED` 로 거부된다 — 401 을 받아
        기록하지 말고 **여기서** 멈춘다."""
        monkeypatch.setattr("backend.services.users.get_user", lambda _u: None)
        with pytest.raises(SystemExit) as e:
            mod._auth_headers("nobody")
        assert "USER_REVOKED" in str(e.value)

    def test_token_version_comes_from_the_store(self, mod, monkeypatch):
        """⚠ 0 으로 가정하면 로그아웃/비밀번호 변경으로 tv 가 오르는 순간
        `TOKEN_REVOKED` 로 조용히 401 이 된다. 저장소 값을 그대로 실어야 한다."""
        seen = {}
        monkeypatch.setattr("backend.services.users.get_user", lambda _u: {"token_version": 7})

        def _fake_token(username, *, token_version=0, extra_claims=None):
            seen["tv"] = token_version
            return "T"

        monkeypatch.setattr("backend.services.auth_service.create_access_token", _fake_token)
        h = mod._auth_headers("someone")
        assert seen["tv"] == 7, "저장소의 token_version 을 안 읽고 0 을 썼다"
        assert h["Authorization"] == "Bearer T"
