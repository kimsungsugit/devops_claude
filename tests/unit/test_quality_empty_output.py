"""(R37 D-3) 빈 산출물 — 생성 사실은 남기고 점수는 남기지 않는다.

## 왜 이 파일이 있나

예전엔 내용이 빈 산출물이면 품질 기록을 **통째로 건너뛰었다**(`return -1`). 의도는 옳았다:
0점·FAIL 로 기록하면 재지도 않은 축이 미달로 세어져 KPI·추세가 오염된다.

그런데 라우터 12곳 중 **반환값을 보는 곳이 하나도 없다** — 응답은 그대로 200 이고 사용자는
파일을 내려받는다. 그래서 "방금 만든 문서가 생성 현황에서는 계속 미생성" 이 된다. 화면이
없다고 하니 같은 빈 문서를 다시 만들고, 왜 비었는지는 어디에도 안 나온다.

그래서 갈랐다: **run 행은 남기고(`status='empty_output'`), 요약·점수는 만들지 않는다.**
요약이 없다는 것이 곧 판정 제외다 — `/trend` 는 `join(QualitySummary)` 라 이 run 을 보지 않는다.
이 파일은 그 두 가지가 **동시에** 성립하는지 본다: 보이는가, 그리고 점수에 섞이지 않는가.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest

from workflow.quality.db import get_session, init_db
from workflow.quality.models import GenerationRun
from workflow.quality.recorder import EMPTY_OUTPUT_STATUS, empty_output_reason, record_run

_EMPTY = {"swut": {"total_tcs": 0}, "swit": {"total_tcs": 0}, "swutcr": {"total_tcs": 0},
          "switcr": {"total_tcs": 0}, "sutr": {"total": 0}, "sitr": {"total": 0},
          "sts": {"total_test_cases": 0}, "suts": {"total_test_cases": 0},
          "sits": {"total_test_cases": 0}, "swreport": {"performed_count": 0},
          "swsa": {"his_metrics": []},
          "uds": {"quick_gate": {"counts": {"total_functions": 0}}}}
_FULL = {"swut": {"total_tcs": 12, "statement_pct": 90.0}, "sutr": {"total": 12, "tested": 12, "passed": 12}}


@pytest.fixture
def qdb(monkeypatch, tmp_path):
    from workflow.quality import db as qdb_mod

    db_file = tmp_path / "q.sqlite"
    monkeypatch.setattr(qdb_mod, "_default_db_path", lambda: db_file)
    qdb_mod.reset_engine()
    qdb_mod.init_db(db_file)
    yield db_file
    qdb_mod.reset_engine()


def _run(qdb_path, run_id):
    init_db(qdb_path)
    with get_session(qdb_path) as s:
        run = s.query(GenerationRun).filter_by(id=run_id).one()
        return {
            "status": run.status,
            "has_summary": run.summary is not None,
            "score_names": sorted(sc.metric_name for sc in run.scores),
            "meta": json.loads(run.meta_json) if run.meta_json else {},
            "sha": run.output_sha256,
            "size": run.output_size_bytes,
        }


class TestTheFactIsKeptTheScoreIsNot:

    @pytest.mark.parametrize("doc_type", sorted(_EMPTY))
    def test_every_doc_type_records_the_run(self, qdb, doc_type):
        """어느 문서 종류든 '만들었다' 는 사실은 남는다 — 하나라도 빠지면 그 탭만 영영 미생성이다."""
        rid = record_run(doc_type, _EMPTY[doc_type], project_root="P", db_path=qdb)
        assert rid > 0, f"{doc_type}: 기록이 통째로 사라졌다"
        got = _run(qdb, rid)
        assert got["status"] == EMPTY_OUTPUT_STATUS
        assert got["has_summary"] is False, "요약을 만들면 판정·추세에 섞인다"
        assert got["score_names"] == [], "점수를 만들면 재지도 않은 축이 0 으로 집계된다"

    @pytest.mark.parametrize("doc_type", sorted(_EMPTY))
    def test_reason_says_which_axis_was_empty(self, qdb, doc_type):
        """'왜 점수가 없나' 에 답하지 못하면 사용자는 같은 빈 문서를 다시 만든다."""
        rid = record_run(doc_type, _EMPTY[doc_type], db_path=qdb)
        reason = _run(qdb, rid)["meta"].get("empty_output_reason")
        assert reason and reason.startswith("empty:"), f"{doc_type}: 사유가 없다"
        assert reason == empty_output_reason(doc_type, _EMPTY[doc_type])

    def test_hash_is_still_recorded(self, qdb):
        """빈 문서에도 바이트는 있다 — 검토 대상 고정(R33/R36)은 그대로 성립해야 한다."""
        payload = b"x" * 128
        rid = record_run("swut", _EMPTY["swut"], db_path=qdb,
                         output_sha256=hashlib.sha256(payload).hexdigest(), output_size_bytes=len(payload))
        got = _run(qdb, rid)
        assert got["sha"] == hashlib.sha256(payload).hexdigest()
        assert got["size"] == 128

    def test_non_empty_is_untouched(self, qdb):
        """판정 조건이 넓어져 정상 산출물까지 점수를 잃으면 게이트가 통째로 사라진다."""
        rid = record_run("swut", _FULL["swut"], db_path=qdb)
        got = _run(qdb, rid)
        assert got["status"] == "success"
        assert got["has_summary"] is True
        assert "gated_metric_count" in got["score_names"]

    def test_meta_from_caller_is_preserved(self, qdb):
        """ASIL·릴리스는 빈 산출물에서도 남아야 한다 — 어느 대상이었는지 못 되짚으면 조사할 수 없다."""
        rid = record_run("swut", _EMPTY["swut"], db_path=qdb,
                         meta={"asil_level": "ASIL D", "kind": "coverage"})
        meta = _run(qdb, rid)["meta"]
        assert meta["asil_level"] == "ASIL D"
        assert meta["kind"] == "coverage"
        assert meta["empty_output_reason"] == "empty:total_tcs"

    def test_scm_id_is_resolved_like_a_normal_run(self, qdb, monkeypatch):
        """프로젝트 축이 없으면 화면(프로젝트별 조회)이 이 run 을 못 찾아 여전히 '미생성' 이다."""
        from backend.services import scm_registry

        monkeypatch.setattr(scm_registry, "resolve_scm_id", lambda root: "kjpds02_pv")
        rid = record_run("swut", _EMPTY["swut"], project_root="KJPDS02", db_path=qdb)
        init_db(qdb)
        with get_session(qdb) as s:
            assert s.query(GenerationRun).filter_by(id=rid).one().scm_id == "kjpds02_pv"


class TestEmptyRunsStayOutOfJudgement:

    def test_trend_does_not_see_it(self, qdb):
        """추세는 `join(QualitySummary)` 다 — 요약이 없다는 것이 곧 제외라는 계약을 못 박는다."""
        record_run("swut", _FULL["swut"], project_root="P", db_path=qdb)
        record_run("swut", _EMPTY["swut"], project_root="P", db_path=qdb)
        conn = sqlite3.connect(qdb)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM generation_runs r JOIN quality_summaries s ON s.run_id = r.id"
            ).fetchone()[0]
            total = conn.execute("SELECT COUNT(*) FROM generation_runs").fetchone()[0]
        finally:
            conn.close()
        assert (total, n) == (2, 1), "빈 run 이 추세 조인에 걸렸다"

    def test_delta_of_the_next_success_survives(self, qdb):
        """**핵심 회귀**: 빈 run 이 사이에 끼어도 다음 성공 run 의 점수 변화가 사라지지 않는다.

        직전 run 조회가 status 를 안 보면 빈 run 이 `prev` 로 뽑히고, 그 run 은 요약이 없어
        `score_delta` 가 조용히 None 이 된다 — 점수는 그대로인데 화면의 `↑ +x.x` 만 없어진다.
        """
        record_run("swut", {"total_tcs": 12, "statement_pct": 50.0}, project_root="P", db_path=qdb)
        record_run("swut", _EMPTY["swut"], project_root="P", db_path=qdb)
        third = record_run("swut", {"total_tcs": 12, "statement_pct": 90.0}, project_root="P", db_path=qdb)
        init_db(qdb)
        with get_session(qdb) as s:
            summary = s.query(GenerationRun).filter_by(id=third).one().summary
            assert summary is not None
            assert summary.score_delta is not None, "빈 run 이 직전 run 자리를 차지해 delta 가 사라졌다"
            assert summary.prev_run_id is not None

    def test_not_counted_as_a_newer_success_for_review(self, qdb):
        """검토 화면의 `superseded_by` 는 '더 새로운 **성공**' 이다 — 빈 run 이 그 자리를 뺏으면
        멀쩡한 검토가 '낡았다' 로 보인다."""
        from workflow.quality.review import superseded_by

        first = record_run("swut", _FULL["swut"], project_root="P", scm_id="kj", db_path=qdb)
        record_run("swut", _EMPTY["swut"], project_root="P", scm_id="kj", db_path=qdb)
        init_db(qdb)
        with get_session(qdb) as s:
            run = s.query(GenerationRun).filter_by(id=first).one()
            assert superseded_by(s, run) is None


# ==============================================================
# (R37 리뷰) 새 상태를 만들면 그 상태를 지나치는 **모든 소비처**를 봐야 한다
# ==============================================================


class TestEveryDocTypeIsUnified:
    """UDS·SwSA 만 옛 동작으로 남으면 그 탭은 여전히 '미생성' 이다 (리뷰 W1).

    D-3 은 "생성했는데 이력이 없다" 를 없애려던 것인데, 선차단이 두 군데 더 있었다:
    `record_uds_run` 의 0함수 차단과 `swsa` 라우터의 `if _qd:`. 11 doc_type 중 9개만 고치면
    나머지 둘에서 같은 증상이 계속된다.
    """

    def test_uds_zero_functions_is_recorded_not_dropped(self, qdb):
        from workflow.quality.recorder import record_uds_run

        rid = record_uds_run({"quick_gate": {"counts": {"total_functions": 0}}}, db_path=qdb)
        assert rid > 0, "UDS 0함수가 통째로 사라졌다 — 보드는 계속 '미생성' 이다"
        got = _run(qdb, rid)
        assert got["status"] == EMPTY_OUTPUT_STATUS
        assert got["meta"]["empty_output_reason"] == "empty:total_functions"
        assert got["has_summary"] is False

    def test_uds_with_functions_is_scored(self, qdb):
        from workflow.quality.recorder import record_uds_run

        rid = record_uds_run(
            {"quick_gate": {"counts": {"total_functions": 5}, "rates": {}}, "gate_pass": True}, db_path=qdb)
        assert rid > 0
        assert _run(qdb, rid)["status"] == "success"

    def test_swsa_helper_returns_a_dict_even_with_no_metrics(self):
        """라우터가 `if _qd:` 로 건너뛰던 자리 — 판정은 recorder 한 곳이 한다(복제 금지)."""
        from backend.routers.swsa import _swsa_quality_data

        data = _swsa_quality_data(None)
        assert isinstance(data, dict)
        assert data.get("his_metrics") == []
        assert empty_output_reason("swsa", data) == "empty:his_metrics"

    def test_no_doc_type_is_left_behind(self):
        """`_EMPTY_KEYS` 가 실제 기록되는 doc_type 을 모두 덮는가 — 빠진 종류는 옛 동작으로 남는다."""
        from workflow.quality.recorder import _EMPTY_KEYS

        recorded = {"uds", "sts", "suts", "sits", "swut", "swit", "swutcr", "switcr",
                    "sutr", "sitr", "swreport", "swsa"}
        assert recorded - set(_EMPTY_KEYS) == set(), f"판정 밖에 남은 doc_type: {recorded - set(_EMPTY_KEYS)}"


class TestFailureIsNotOverwrittenByEmptiness:
    """(리뷰 W4) 둘 다 참일 때 더 중요한 쪽은 '실패' 다 — 빈 것이 실패를 덮으면 안 된다."""

    def test_explicit_failed_status_survives(self, qdb):
        rid = record_run("swut", {"total_tcs": 0}, status="failed", error_msg="빌더 예외", db_path=qdb)
        got = _run(qdb, rid)
        assert got["status"] == "failed", "실패가 empty_output 으로 갈아끼워졌다"
        assert got["meta"]["empty_output_reason"] == "empty:total_tcs", "사유는 그대로 남아야 한다"

    def test_default_status_becomes_empty_output(self, qdb):
        rid = record_run("swut", {"total_tcs": 0}, db_path=qdb)
        assert _run(qdb, rid)["status"] == EMPTY_OUTPUT_STATUS


class TestConsumersOfTheNewStatus:
    """(리뷰 C1·C2) 상태를 만들었으면 그것을 지나치는 소비처가 전부 알아야 한다."""

    def test_review_state_exposes_status_and_reason(self, qdb):
        """검토 패널이 '무엇을 승인하는가' 를 말하려면 응답에 그 사실이 있어야 한다."""
        import hashlib as _h

        from workflow.quality.review import Viewer, review_state
        rid = record_run("swut", {"total_tcs": 0}, db_path=qdb,
                         output_sha256=_h.sha256(b"x").hexdigest(), output_size_bytes=1)
        from contextlib import contextmanager

        from workflow.quality.db import get_session

        @contextmanager
        def _open():
            with get_session(qdb) as s:
                yield s

        st = review_state(_open, rid, viewer=Viewer(name="t", is_admin=True, has_bearer=True))
        assert st["status"] == EMPTY_OUTPUT_STATUS
        assert st["empty_output_reason"] == "empty:total_tcs"
        # 해시가 있으니 검토는 열린다 — 잠그는 게 아니라 **말하는** 것이 이 fix 다.
        assert st["hash_unavailable"] is False
        assert st["can_review"] is True

    def test_advisor_says_zero_items_not_missing_row(self, qdb):
        """'quality_summaries 행이 없습니다' 는 외부 삭제를 암시한다 — 여기선 일부러 안 만든 것이다."""
        from workflow.quality.advisor import suggest_improvements

        rid = record_run("swut", {"total_tcs": 0}, db_path=qdb)
        out = suggest_improvements(rid, db_path=qdb)
        assert "0건" in out["summary"], out["summary"]
        assert "empty:total_tcs" in out["summary"]
        assert "행이 없습니다" not in out["summary"], "없는 사실(삭제)을 암시한다"

    def test_advisor_keeps_the_old_message_for_a_truly_missing_summary(self, qdb):
        """빈 산출물이 아닌데 요약이 없는 경우(외부 삭제)는 종전 문구 그대로 — 뭉개지 않는다."""
        import sqlite3

        from workflow.quality.advisor import suggest_improvements

        rid = record_run("swut", {"total_tcs": 12, "statement_pct": 90.0}, db_path=qdb)
        conn = sqlite3.connect(qdb)
        try:
            conn.execute("DELETE FROM quality_summaries WHERE run_id=?", (rid,))
            conn.commit()
        finally:
            conn.close()
        out = suggest_improvements(rid, db_path=qdb)
        assert "행이 없습니다" in out["summary"], out["summary"]
