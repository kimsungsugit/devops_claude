"""게이트 정책 조회 endpoint + run 상세 계약 — §6-1 후보 22 (G2·G4).

## 고친 계약 (실측 2026-08-04)

    GET /api/quality/runs/999999  ->  **200** {"error": "run_id 999999 not found"}

`api.js:145` 가 `if (res.ok) return res.json()` 이라 프론트가 **에러를 성공으로 삼킨다**.
이 endpoint 의 프론트 소비자가 그동안 0건이었으므로(§6-1 실측) 계약을 바로잡는 지금이
유일하게 무해한 시점이다. → 404.

## 정책 노출 (G4)

계획서는 "적용됨 / 정의만 있고 미사용" **2분법**을 지시했는데, 실측하면 부족하다:
적용되는 표 안에서도 **조정 가능(키별 env)** 인지 **코드 상수**인지가 갈린다.
축을 둘(`status`, `adjustable`) 두지 않으면 "바꾸려면 어디를 고치나" 를 오독한다.

| 표 | status | adjustable |
|---|---|---|
| `UDS_QUALITY_GATE_THRESHOLDS` | applied | env (12키 각각 전용 이름) |
| `UDS_QUALITY_WARNING_THRESHOLDS` | defined_unused | code |
| `TEST_QUALITY_GATES_BY_ASIL` | defined_unused | code |
"""
from __future__ import annotations

import pytest

pytest.importorskip("fastapi")


@pytest.fixture
def client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.dependencies.auth import require_user
    from backend.routers import quality

    app = FastAPI()
    app.include_router(quality.router)
    # 권한 계층은 이 파일의 검증 대상이 아니다 — `test_quality_evidence.py` 가 덮는다.
    # (2026-08-07: 라우터 게이트가 `require_admin` → `require_user` 로 바뀌었다.
    #  조회 전용이라 admin 이 아니라 로그인만 요구한다 — 그 결정은 저쪽에서 검증.)
    app.dependency_overrides[require_user] = lambda: "tester"
    return TestClient(app)


class TestRunDetailContract:
    def test_missing_run_is_404_not_200(self, client):
        res = client.get("/api/quality/runs/999999999")
        assert res.status_code == 404, (
            "미존재 run 이 200 이면 `api.js` 의 `res.ok` 검사를 통과해 프론트가 "
            "에러를 성공으로 삼킨다(빈 상세를 '정상' 으로 그린다)"
        )

    def test_404_body_names_the_run(self, client):
        res = client.get("/api/quality/runs/999999999")
        assert "999999999" in str(res.json())


class TestPolicyEndpoint:
    def test_returns_three_tables(self, client):
        res = client.get("/api/quality/policy")
        assert res.status_code == 200
        keys = [t["key"] for t in res.json()["tables"]]
        assert keys == [
            "UDS_QUALITY_GATE_THRESHOLDS",
            "UDS_QUALITY_WARNING_THRESHOLDS",
            "TEST_QUALITY_GATES_BY_ASIL",
        ]

    def test_status_and_adjustable_are_separate_axes(self, client):
        """2분법이면 "적용되는데 코드 상수" 같은 조합을 표현할 수 없다."""
        tables = {t["key"]: t for t in client.get("/api/quality/policy").json()["tables"]}
        gate = tables["UDS_QUALITY_GATE_THRESHOLDS"]
        assert gate["status"] == "applied"
        assert gate["adjustable"] == "env"
        for key in ("UDS_QUALITY_WARNING_THRESHOLDS", "TEST_QUALITY_GATES_BY_ASIL"):
            assert tables[key]["status"] == "defined_unused"
            assert tables[key]["adjustable"] == "code", (
                f"{key} 는 env 훅이 0개다 — 'env 로 조정 가능' 이라 하면 거짓 안내다"
            )

    def test_gate_entries_carry_their_env_names(self, client):
        tables = {t["key"]: t for t in client.get("/api/quality/policy").json()["tables"]}
        entries = {e["key"]: e for e in tables["UDS_QUALITY_GATE_THRESHOLDS"]["entries"]}
        assert entries["called_min"]["env_name"] == "UDS_CALLED_MIN"
        assert entries["asil_trusted_min"]["env_name"] == "UDS_ASIL_TRUSTED_MIN"

    def test_unused_tables_declare_no_env_name(self, client):
        tables = {t["key"]: t for t in client.get("/api/quality/policy").json()["tables"]}
        for key in ("UDS_QUALITY_WARNING_THRESHOLDS", "TEST_QUALITY_GATES_BY_ASIL"):
            for e in tables[key]["entries"]:
                assert e["env_name"] is None

    def test_env_name_map_matches_config_exactly(self):
        """`_GATE_ENV_NAMES` 와 `config.UDS_QUALITY_GATE_THRESHOLDS` 는 **한 세트**다.

        ⚠ `config.py` 는 env 이름을 `_safe_float("UDS_CALLED_MIN", 95.0)` 호출 인자로만
        갖고 있어 런타임에 되짚을 수 없다. 그래서 라우터가 리터럴로 들고 있는데,
        키가 하나만 어긋나도 화면이 **없는 환경변수를 안내**하게 된다. 여기서 잠근다.
        """
        import config
        from backend.routers.quality import _GATE_ENV_NAMES

        assert set(_GATE_ENV_NAMES) == set(config.UDS_QUALITY_GATE_THRESHOLDS), (
            "게이트 임계값 키와 env 이름 맵이 어긋났다 — "
            f"맵에만: {set(_GATE_ENV_NAMES) - set(config.UDS_QUALITY_GATE_THRESHOLDS)}, "
            f"config 에만: {set(config.UDS_QUALITY_GATE_THRESHOLDS) - set(_GATE_ENV_NAMES)}"
        )

    def test_env_names_are_the_ones_config_actually_reads(self, monkeypatch):
        """이름이 진짜 먹히는지 — 주입해서 **실효값이 바뀌는지** 확인한다.

        맵과 config 키가 같아도 이름 문자열이 틀리면 화면 안내가 거짓이 된다.
        """
        import importlib

        import config as config_mod
        from backend.routers.quality import _GATE_ENV_NAMES

        monkeypatch.setenv(_GATE_ENV_NAMES["called_min"], "12.5")
        reloaded = importlib.reload(config_mod)
        try:
            assert reloaded.UDS_QUALITY_GATE_THRESHOLDS["called_min"] == 12.5, (
                f"{_GATE_ENV_NAMES['called_min']} 로 덮이지 않는다 — 화면이 안내하는 "
                "환경변수 이름이 실제로는 먹지 않는다"
            )
        finally:
            monkeypatch.delenv(_GATE_ENV_NAMES["called_min"], raising=False)
            importlib.reload(config_mod)

    def test_values_are_effective_not_literals(self, client, monkeypatch):
        """리터럴이 아니라 지금 프로세스의 실효값을 낸다."""
        import config

        monkeypatch.setitem(config.UDS_QUALITY_GATE_THRESHOLDS, "called_min", 33.0)
        tables = {t["key"]: t for t in client.get("/api/quality/policy").json()["tables"]}
        entries = {e["key"]: e for e in tables["UDS_QUALITY_GATE_THRESHOLDS"]["entries"]}
        assert entries["called_min"]["value"] == 33.0

    def test_notes_say_it_does_not_judge(self, client):
        """화면이 판정을 하지 않는다는 사실이 응답에 있어야 한다."""
        notes = " ".join(client.get("/api/quality/policy").json()["notes"])
        assert "표시만" in notes
        assert "dotenv" in notes, "config 가 .env 를 스스로 안 읽는 사실이 빠졌다"
