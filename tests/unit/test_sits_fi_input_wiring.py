"""FI(오류 주입) 대상이 **입력으로** 생성기까지 가는가(R9-5).

R8-4 가 생성기에 FI TC 발행 경로를 냈지만 **호출부가 없었다** — `fi_design_ids` 는
`generators/sits.py` 안에서만 언급돼 있었고, 어떤 API 도 값을 넘기지 않아 프로덕션에서는
영원히 0건이었다.

⚠ 어느 통합 지점을 FI 로 시험할지는 **추론하지 않는다**. R8 에서 8가지 독립 근거(전략
  라벨·오류 경로·반환 경로·ASIL·시나리오 텍스트 등)를 전부 대조했는데 어느 것도 정본의
  5건과 맞지 않았다. 지어내는 대신 받는다.
"""
from __future__ import annotations

import pytest

from backend.routers.local import _split_fi_design_ids


class TestParsing:
    @pytest.mark.parametrize("raw,expect", [
        ("SwFn_07", ["SwFn_07"]),
        ("SwFn_07,SwFn_12", ["SwFn_07", "SwFn_12"]),
        ("SwFn_07, SwFn_12 ,SwFn_34", ["SwFn_07", "SwFn_12", "SwFn_34"]),
        ("SwFn_07;SwFn_12", ["SwFn_07", "SwFn_12"]),
        ("", []),
        ("   ", []),
        (",, ,", []),
        (None, []),
    ])
    def test_split(self, raw, expect):
        assert _split_fi_design_ids(raw) == expect, raw

    def test_unknown_ids_are_not_filtered_here(self):
        """⚠ 알 수 없는 ID 를 **여기서 거르지 않는다**.

        존재 판정은 생성기가 SwUDS Related 맵으로 하고, 못 찾으면 `fi_unresolved` 로
        보고된다. 여기서 미리 거르면 "요청했는데 못 냈다" 가 "요청이 없었다" 로 둔갑한다.
        """
        assert _split_fi_design_ids("존재하지_않는_ID") == ["존재하지_않는_ID"]


class TestItReachesTheGenerator:
    """엔드포인트가 값을 **넘기는가** — 파싱만 맞고 안 넘기면 아무 일도 안 일어난다."""

    def test_endpoint_forwards_fi_design_ids(self, monkeypatch, tmp_path):
        import backend.routers.local as local_mod

        seen: dict = {}

        def _fake_generate_sits(**kwargs):
            seen.update(kwargs)
            return {"output_path": str(tmp_path / "x.xlsm"), "test_case_count": 1,
                    "total_sub_cases": 1, "quality_report": {}}

        import sits_generator
        monkeypatch.setattr(sits_generator, "generate_sits", _fake_generate_sits)
        monkeypatch.setattr(local_mod, "_build_local_excel_output",
                            lambda *a, **k: ("x.xlsm", tmp_path / "x.xlsm"))
        monkeypatch.setattr(local_mod, "_build_excel_artifact_payload", lambda *a, **k: {})
        monkeypatch.setattr(local_mod, "_load_sts_ai_config", lambda: None)
        import backend.services.docgen_template_source as _tpl_src
        monkeypatch.setattr(_tpl_src, "resolve_template_for",
                            lambda *a, **k: (str(tmp_path / "t.xlsm"), "test"))
        import backend.services.resolver_helpers as _rh
        monkeypatch.setattr(_rh, "resolve_builder_input", lambda *a, **k: None)

        class _Req:
            headers = {"x-req-id": "t1"}

        # 이 테스트가 보려는 것은 **전달**이다. 하류 단계가 tmp 환경에서 실패해도
        # generate_sits 는 이미 불렸으므로 seen 으로 판정한다.
        # ⚠ 예외를 그냥 삼키면 실패 원인이 안 보인다 — 잡되 **보고**한다.
        err = None
        try:
            # ⚠ 엔드포인트를 직접 부르면 넘기지 않은 `Form(...)` 기본값이 **Form 객체
            #   그대로** 남는다(FastAPI 가 안 풀어준다). 전부 명시해야 한다 —
            #   [[reference_sim_harness_live_parity]]: 인자를 빠뜨린 재현은 조용히
            #   다른 것을 잰다.
            local_mod.local_sits_generate(
                request=_Req(), source_root=str(tmp_path),
                template_path="", reference_doc_path="", project_id="T",
                version="v1.00", asil_level="", max_subcases=7, max_flows=None,
                report_dir="", srs_path="", sds_path="", uds_path="",
                hsis_path="", stp_path="",
                fi_design_ids="SwFn_07, SwFn_12",
            )
        except Exception as exc:      # noqa: BLE001 - 하류 실패는 이 가드의 관심사가 아니다
            err = exc

        assert seen, (
            f"generate_sits 가 호출되지 않았다 — 이 가드가 공허 통과 중이다. "
            f"엔드포인트가 그 전에 멈췄다: {type(err).__name__}: {err}")
        assert seen.get("fi_design_ids") == ["SwFn_07", "SwFn_12"], seen.get("fi_design_ids")

    def test_empty_input_forwards_empty_not_missing(self):
        """비우면 빈 목록이 간다 — 생성기가 '요청 없음'(fi_requested=0)으로 센다."""
        assert _split_fi_design_ids("") == []
