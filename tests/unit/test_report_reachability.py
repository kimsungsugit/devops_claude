# tests/unit/test_report_reachability.py
"""**보고를 추가하는 것과 보고가 도달하는 것은 다른 문제다.**

## 왜 이 파일이 생겼나 (2026-07-31 자체 감사)

앞선 라운드들에서 침묵을 없애려고 `stats_out`/sidecar 로 수치를 여러 개 내보냈다.
그 수치가 **사람이 보는 표면까지 실제로 도달하는지** 를 사후 감사했더니 두 곳이
중간에서 끊겨 있었다 — 고치려던 결함군과 정확히 같은 모양이다.

| # | 격차 | 실측 |
|---|---|---|
| R1 | SITS `sds_*` 키가 품질 리포트에 안 실림 | `generate_quality_report` 가 `flow_stats` 에서 **이름 지정한 8개 키만** 골라 담는다. `sds_source`/`sds_lookups`/`sds_swcom_hits` 는 전부 버려져 **로그에만** 남았다(품질 리포트는 API 로 나가지만 로그는 안 나간다) |
| R2 | UDS 충실도가 응답에 없음 | sidecar 와 `<out>.docx.stage.json` checkpoint 에 기록되는데 **checkpoint 를 읽는 코드가 저장소 전체에 0개**(write-only). 결과 dict 의 다른 `*_path` 리포트들과 달리 표면에 없었다 |

두 경우 모두 "수치를 남겼다" 는 사실은 맞지만, 산출물을 검토하는 사람에게는
여전히 보이지 않았다. 게이트가 있는데 발화하지 않는 것과 같다.

## 갱신 (2026-09-01, 라운드 11)

R2 의 괄호 — "checkpoint 는 write-only" — 는 **더 이상 사실이 아니다**. 준비 게이트가
`backend/services/docgen_last_run.py` 로 읽어 "직전 생성" 행으로 공시한다. 아래
`TestCheckpointIsRead` 가 그 자리를 대신하며, **옛 가드가 왜 그 변화를 놓쳤는지**를
같이 기록한다(가드가 사실이 아니라 한 줄짜리 철자를 재고 있었다).
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from backend.helpers.uds import _gen_stats_result_fields
from generators.sits import collect_integration_flows, generate_sits_quality_report


def _flow_payload():
    return {
        "F1": {"name": "Task_10ms", "module_name": "app.c",
               "calls_list": ["Sub_Read"], "inputs": ["u8 a"], "outputs": ["u8 b"],
               "asil": "B", "related": "SwTR_0101"},
        "F2": {"name": "Sub_Read", "module_name": "drv.c", "calls_list": [],
               "inputs": [], "outputs": [], "asil": "B"},
    }


# --------------------------------------------------------------
# R1 — SITS: stats_out 이 품질 리포트까지 도달하는가
# --------------------------------------------------------------

class TestSitsEnrichmentReachesQualityReport:
    def _q(self, **kw):
        stats = {}
        flows = collect_integration_flows(_flow_payload(), max_flows=10,
                                          stats_out=stats, **kw)
        return generate_sits_quality_report(flows, 2, flow_stats=stats), stats

    def test_enrichment_block_is_present(self):
        """뮤테이션: `"sds_related_enrichment": sds_enrich` 를 빼면 실패."""
        q, _ = self._q(sds_map={"Task_10ms": {"swcom": "SwCom_07"}})
        assert "sds_related_enrichment" in q

    def test_source_is_carried_through(self):
        """어느 문서로 보강했는지가 리포트에 남아야 한다 — 저장소 폴백이면 드러난다."""
        q, _ = self._q(sds_map={"Task_10ms": {"swcom": "SwCom_07"}})
        assert q["sds_related_enrichment"]["source"] == "argument"

    def test_zero_yield_is_reported_not_omitted(self):
        """**0 이야말로 실어야 하는 값이다.** 비어 있으면 "동작한다" 로 읽힌다.

        뮤테이션: `if fs.get("sds_lookups") is not None` 을 `if _hit:` 로 바꾸면 실패.
        """
        q, _ = self._q(sds_map={"없는함수": {"swcom": "S1"}})
        blk = q["sds_related_enrichment"]
        assert blk["lookups"] == 1
        assert blk["swcom_hits"] == 0
        assert blk["yield_pct"] == 0.0

    def test_no_lookup_yields_none_not_zero_pct(self):
        """조회 자체가 0이면 비율은 `None`(미측정) — 0% 로 위장하지 않는다."""
        q = generate_sits_quality_report([], 0, flow_stats={"sds_lookups": 0})
        assert q["sds_related_enrichment"]["yield_pct"] is None

    def test_absent_flow_stats_does_not_crash(self):
        """음성 대조군 — 통계를 안 준 호출자도 깨지지 않는다(additive 계약)."""
        q = generate_sits_quality_report([], 0)
        assert q["sds_related_enrichment"] == {}

    def test_quality_report_does_not_drop_named_keys_silently(self):
        """`flow_stats` 를 이름으로 골라 담는 구조 자체가 이 결함의 원인이었다.

        `collect_integration_flows` 가 내보내는 `sds_*` 키가 **전부** 리포트에
        대응 필드를 갖는지 대조한다 — 새 키를 추가하고 여기 배선을 잊으면 실패.
        """
        q, stats = self._q(sds_map={"Task_10ms": {"swcom": "SwCom_07"}})
        emitted = {k for k in stats if k.startswith("sds_")}
        blk = q["sds_related_enrichment"]
        mapped = {"sds_source": "source", "sds_map_entries": "map_entries",
                  "sds_lookups": "lookups", "sds_key_hits": "key_hits",
                  "sds_swcom_hits": "swcom_hits"}
        missing = [k for k in emitted if mapped.get(k) not in blk]
        assert not missing, f"품질 리포트에 도달하지 못하는 키: {missing}"


# --------------------------------------------------------------
# R2 — UDS: 충실도가 API 응답 표면에 오르는가
# --------------------------------------------------------------

class TestUdsFidelityReachesResult:
    def test_missing_sidecar_is_unmeasured_not_ok(self, tmp_path):
        """sidecar 부재는 **미측정** — `{}` 나 0 으로 접어 "문제 없음" 처럼 보이면 안 된다."""
        fields = _gen_stats_result_fields(tmp_path / "uds.docx")
        assert fields["gen_stats_summary"] is None
        assert fields["gen_stats_path"] == ""

    def test_sidecar_is_surfaced(self, tmp_path):
        """뮤테이션: 결과 dict 에서 `**_gen_stats_result_fields(out_path)` 를 빼면 실패."""
        from report_gen.docx_builder import gen_stats_path
        out = tmp_path / "uds.docx"
        gen_stats_path(str(out)).write_text(json.dumps({
            "mode": "template", "template_source": "argument",
            "payload_functions": 432, "matched_functions": 336, "match_pct": 77.78,
            "unmatched_payload_count": 96, "empty_heading_count": 75,
            "deleted_heading_count": 10,
            "reference_suds": {"identity": {"same_project": False}},
        }, ensure_ascii=False), encoding="utf-8")
        f = _gen_stats_result_fields(out)
        s = f["gen_stats_summary"]
        assert f["gen_stats_path"].endswith("uds.docx.gen_stats.json")
        assert s["match_pct"] == 77.78
        assert s["unmatched_payload_count"] == 96
        assert s["reference_suds"]["identity"]["same_project"] is False

    def test_null_match_pct_is_preserved(self, tmp_path):
        """분모 0 → `None`(미측정). 0.0 으로 강등하면 "0% 반영" 이라는 거짓이 된다."""
        from report_gen.docx_builder import gen_stats_path
        out = tmp_path / "uds.docx"
        gen_stats_path(str(out)).write_text(
            json.dumps({"mode": "no_template", "match_pct": None}), encoding="utf-8")
        assert _gen_stats_result_fields(out)["gen_stats_summary"]["match_pct"] is None

    def test_corrupt_sidecar_is_unmeasured_not_crash(self, tmp_path):
        from report_gen.docx_builder import gen_stats_path
        out = tmp_path / "uds.docx"
        gen_stats_path(str(out)).write_text("{ not json", encoding="utf-8")
        assert _gen_stats_result_fields(out)["gen_stats_summary"] is None

    def test_result_dict_includes_the_fields(self):
        """결과 dict 에 실제로 배선됐는지 — 헬퍼만 만들고 안 쓰면 결함은 그대로다."""
        src = Path("backend/helpers/uds.py").read_text(encoding="utf-8")
        assert "**_gen_stats_result_fields(out_path)" in src


# --------------------------------------------------------------
# R3 — checkpoint 도 읽힌다 (2026-09-01, 라운드 11에서 뒤집힘)
# --------------------------------------------------------------

class TestCheckpointIsRead:
    """`<out>.docx.stage.json` 은 **더 이상 write-only 가 아니다.**

    ## 옛 기록과 그것을 지키던 가드가 왜 틀렸나

    여기엔 원래 `test_stage_checkpoint_has_no_reader` 가 있었다 — 저장소를 훑어
    "`stage.json` 이 든 줄에 `read_text`/`json.load`/`open(`/`fetch(` 가 함께 있는가" 로
    reader 를 셌고, "나중에 reader 가 생기면 여기서 실패한다" 고 적혀 있었다.

    라운드 11이 실제로 reader 를 만들었는데 **그 가드는 그대로 통과했다.** 새 reader 가
    경로를 상수(`CHECKPOINT_SUFFIX`)로 두고 읽기는 다른 줄에서 하기 때문이다 — 실측:
    `docgen_last_run.py` 에서 `stage.json` 이 있는 줄은 3개고 그중 읽기 토큰을 가진 줄은
    **0개**다. 가드가 잰 것은 *사실*이 아니라 **한 줄짜리 철자 습관**이었다.

    그래서 대체물은 같은 방식으로 세지 않는다. **읽는 함수가 있는가**(구조)와 **그 값이
    응답에 실리는가**(행동)를 각각 단언한다 — 이 파일의 다른 두 축(R1·R2)이 쓰는 방식과
    같다. 어느 줄에 어떤 토큰이 있는지는 이제 아무것도 증명하지 않는다.
    """

    @pytest.mark.parametrize(
        "fn", ["find_last_run_checkpoint", "summarize_last_run", "last_uds_run"])
    def test_reader_functions_exist(self, fn):
        tree = ast.parse(
            Path("backend/services/docgen_last_run.py").read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert fn in names

    def test_reader_actually_reads_a_checkpoint(self, tmp_path):
        """행동 축 — 파일을 놓고 사실이 나오는지 본다(이름만 맞으면 통과하지 않게)."""
        from backend.services.docgen_last_run import CHECKPOINT_SUFFIX, summarize_last_run
        cp = tmp_path / f"uds_spec_demo_20260901_120000{CHECKPOINT_SUFFIX}"
        cp.write_text(json.dumps({
            "stage": "full", "status": "success",
            "gen_stats": {"payload_functions": 57, "matched_functions": 57},
        }), encoding="utf-8")
        run = summarize_last_run(cp)
        assert run is not None
        assert (run["status"], run["matched_functions"]) == ("success", 57)

    def test_the_gate_surfaces_it(self):
        """배선 축 — 읽기만 하고 `steps` 에 안 실으면 침묵은 그대로다."""
        src = Path("backend/routers/docgen_preflight.py").read_text(encoding="utf-8")
        assert "_last = _last_run_step(req)" in src
        assert "steps.append(_last)" in src

    @pytest.mark.parametrize("fn", ["_read_gen_stats", "_gen_stats_result_fields"])
    def test_sidecar_readers_exist(self, fn):
        """음성 대조군 — sidecar 쪽은 실제로 읽는 코드가 있다(대조군이 없으면 위 테스트가 무의미)."""
        tree = ast.parse(Path("backend/helpers/uds.py").read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert fn in names
