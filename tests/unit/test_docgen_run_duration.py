# tests/unit/test_docgen_run_duration.py
"""직전 생성이 **얼마나 걸렸는지**를 기록하고 게이트가 그것으로 말하는가.

## 왜 이 파일이 생겼나 (2026-09-01 실측)

체크포인트는 단계마다 **덮어써진다**. 시작 시각은 `started` 레코드에만 있었고 종결
레코드(`success`/`failed`/`timeout`/`exception`)엔 `ended_at` 만 있었다 — 그래서 남아
있는 기록 3건 전부 **소요를 되살릴 수 없었다**:

    keys: ['ended_at', 'gen_stats', 'stage', 'status', 'stdout_tail', 'warnings']

"다음 생성이 예산 안에 들어오는가" 를 물을 수단 자체가 없었던 것이다.

## 같은 값을 두 곳에 두면 한쪽이 낡는다

`_generate_docx_with_retry` 는 리터럴 폴백 사다리를 달고 있었고 그 값이 `full=2400`
이었는데 config 의 실제 예산은 **7200/3600/1800** 이었다. 죽은 폴백이 문서·기억에
옮겨 적히면서 "full 예산 2400초" 라는 **3배 틀린 사실**이 돌아다녔다. 그래서 여기서는
숫자를 쓰지 않고 `config` 를 읽어 대조한다.

## 규약 — 못 잰 것은 0이 아니다

라운드 12 이전 기록엔 `elapsed_seconds` 가 아예 없다. `None` 이어야 하고, 게이트는
그럴 때 **소요를 한 마디도 하지 않는다**(0초로 그리면 "즉시 끝났다" 는 거짓이 된다).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest

import config
from backend.helpers import uds as uds_helpers
from backend.routers.docgen_preflight import PreflightRequest, _last_run_step
from backend.services import docgen_last_run as lr
from backend.services.jenkins_helpers import _job_slug

JOB = "http://192.168.110.40:7000/job/DEMO_PV/"


def _run_writer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str) -> Dict[str, Any]:
    """라이터를 **실제로 돌려** 체크포인트를 받아 온다(모양 검사 아님).

    서브프로세스만 가짜다 — 체크포인트를 쓰는 코드는 프로덕션 그대로 돈다.
    """
    out_path = tmp_path / "uds_out.docx"

    def fake_run(cmd, **kwargs):  # noqa: ANN001, ANN003
        if outcome == "timeout":
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout") or 1)
        if outcome == "exception":
            raise OSError("worker 가 죽었다")
        if outcome == "success":
            out_path.write_bytes(b"PK\x03\x04not-a-real-docx")
            return subprocess.CompletedProcess(cmd, 0, "OK\n", "")
        return subprocess.CompletedProcess(cmd, 1, "", "boom\nPackageNotFoundError: nope")

    monkeypatch.setattr(uds_helpers.subprocess, "run", fake_run)
    try:
        uds_helpers._generate_docx_with_retry(None, {"functions": []}, out_path, retries=1)
    except RuntimeError:
        pass  # 실패 갈래는 사다리 소진 후 raise 한다 — 여기서는 기록만 본다
    cp = out_path.with_suffix(lr.CHECKPOINT_SUFFIX)
    assert cp.exists(), "체크포인트가 아예 없다"
    return json.loads(cp.read_text(encoding="utf-8"))


# ══════════════════════════════════════════════════════════════════════════
# 라이터 — 종결 레코드가 소요를 싣는가
# ══════════════════════════════════════════════════════════════════════════

class TestTheWriterRecordsHowLongItTook:
    @pytest.mark.parametrize("outcome", ["success", "failed", "timeout", "exception"])
    def test_every_terminal_record_carries_start_and_elapsed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str,
    ) -> None:
        """네 갈래 **전부**. 하나라도 빠지면 그 결말만 소요를 잃는다."""
        rec = _run_writer(tmp_path, monkeypatch, outcome)
        assert rec["status"] == outcome
        for key in ("started_at", "ended_at", "elapsed_seconds", "timeout_seconds"):
            assert key in rec, f"{outcome} 레코드에 {key} 가 없다"
        assert isinstance(rec["elapsed_seconds"], (int, float))
        assert rec["elapsed_seconds"] >= 0

    def test_started_at_survives_the_overwrite(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """시작 시각은 **덮어쓴 뒤에도** 남아야 한다 — 이 파일이 존재하는 이유다."""
        rec = _run_writer(tmp_path, monkeypatch, "success")
        assert rec["started_at"] <= rec["ended_at"]

    def test_budget_comes_from_config_not_a_literal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """첫 단계의 예산은 `config` 의 값이어야 한다(옛 폴백은 2400 이었다)."""
        rec = _run_writer(tmp_path, monkeypatch, "success")
        assert rec["timeout_seconds"] == config.UDS_DOCX_RETRY_STAGES[0][2]

    def test_the_dead_literal_ladder_is_gone(self) -> None:
        """리터럴 사다리가 되살아나면 여기서 막는다.

        구조를 재는 가드지만 이 축에서는 그게 대상 그 자체다 — 결함이 **복제된 숫자**의
        존재였고, 그것은 실행으로 드러나지 않는다(폴백은 영영 안 타므로).

        ⚠ 원문 텍스트가 아니라 **AST 의 상수**를 본다. 처음엔 본문에서 문자열을 찾았는데
          그 결함을 설명하는 주석("옛 폴백은 2400 이었다")이 걸려 스스로 빨개졌다 —
          가드가 코드가 아니라 **글자**를 재고 있었다는 신호다.
        """
        import ast

        tree = ast.parse(Path(uds_helpers.__file__).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_generate_docx_with_retry")
        consts = [n.value for n in ast.walk(fn) if isinstance(n, ast.Constant)]
        assert 2400 not in consts, "옛 폴백 예산이 되살아났다"
        assert "degraded_ai_off" not in consts, (
            "단계 이름을 다시 복제했다 — config 직독이어야 한다"
        )


# ══════════════════════════════════════════════════════════════════════════
# 예산은 config 단일 출처
# ══════════════════════════════════════════════════════════════════════════

class TestBudgetIsReadNotCopied:
    def test_each_stage_budget_matches_config(self) -> None:
        for name, _level, budget in config.UDS_DOCX_RETRY_STAGES:
            assert lr.retry_stage_budget(str(name)) == int(budget)

    @pytest.mark.parametrize("stage", ["", "   ", "nope", "FULL"])
    def test_unknown_stage_is_none_not_a_guess(self, stage: str) -> None:
        """모르는 단계에 기본값을 주면 화면이 없는 예산을 이름 댄다."""
        assert lr.retry_stage_budget(stage) is None

    def test_config_without_the_ladder_yields_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delattr(config, "UDS_DOCX_RETRY_STAGES", raising=False)
        assert lr.retry_stage_budget("full") is None


# ══════════════════════════════════════════════════════════════════════════
# 리더 — 없는 소요를 0으로 접지 않는다
# ══════════════════════════════════════════════════════════════════════════

def _cp(tmp_path: Path, record: Dict[str, Any]) -> Path:
    out_dir = tmp_path / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    cp = out_dir / f"{lr.ARTIFACT_PREFIX}{_job_slug(JOB)}_20260901_120000.docx{lr.CHECKPOINT_SUFFIX}"
    cp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return cp


class TestReadingTheDuration:
    def test_elapsed_is_carried(self, tmp_path: Path) -> None:
        s = lr.summarize_last_run(_cp(tmp_path, {
            "stage": "full", "status": "success", "elapsed_seconds": 809.4,
            "timeout_seconds": 7200}))
        assert s["elapsed_seconds"] == pytest.approx(809.4)
        assert s["budget_seconds"] == 7200

    def test_old_record_without_elapsed_is_none_not_zero(self, tmp_path: Path) -> None:
        """실측 기록 3건이 전부 이 모양이다."""
        s = lr.summarize_last_run(_cp(tmp_path, {
            "stage": "full", "status": "success", "ended_at": "2026-08-07T15:46:35"}))
        assert s["elapsed_seconds"] is None
        # 예산은 기록에 없어도 **config 로 안다** — 소요와 달리 확정적이다.
        assert s["budget_seconds"] == config.UDS_DOCX_RETRY_STAGES[0][2]

    @pytest.mark.parametrize("bad", [True, False, "809", None, [1]])
    def test_non_numeric_elapsed_is_rejected(self, tmp_path: Path, bad: Any) -> None:
        """`True` 는 파이썬에서 `isinstance(x, int)` 를 통과한다 — 1초로 읽히면 안 된다."""
        s = lr.summarize_last_run(_cp(tmp_path, {
            "stage": "full", "status": "success", "elapsed_seconds": bad}))
        assert s["elapsed_seconds"] is None

    def test_stage_budget_falls_back_to_config(self, tmp_path: Path) -> None:
        s = lr.summarize_last_run(_cp(tmp_path, {
            "stage": "degraded_light", "status": "failed"}))
        assert s["budget_seconds"] == config.UDS_DOCX_RETRY_STAGES[-1][2]


# ══════════════════════════════════════════════════════════════════════════
# 게이트 — 측정된 것만 말한다
# ══════════════════════════════════════════════════════════════════════════

def _row(tmp_path: Path, record: Dict[str, Any]) -> Dict[str, Any]:
    _cp(tmp_path, record)
    step = _last_run_step(PreflightRequest(doc_type="uds", job_url=JOB,
                                           cache_root=str(tmp_path)))
    assert step is not None
    return step


_OK_STATS = {"payload_functions": 57, "matched_functions": 57}


class TestTheGateSaysHowLongItTook:
    def test_roomy_run_stays_ok_and_shows_both_numbers(self, tmp_path: Path) -> None:
        step = _row(tmp_path, {"stage": "full", "status": "success",
                               "elapsed_seconds": 809.4, "timeout_seconds": 7200,
                               "gen_stats": _OK_STATS})
        assert step["state"] == "ok"
        assert "809초" in step["reason"] and "7200초" in step["reason"]
        assert step["measured"]["elapsed_seconds"] == pytest.approx(809.4)
        assert step["measured"]["budget_seconds"] == 7200

    def test_run_that_nearly_used_the_budget_is_a_warning(self, tmp_path: Path) -> None:
        """성공이어도 예산에 닿아 있으면 다음엔 끊긴다 — 미리 말한다."""
        step = _row(tmp_path, {"stage": "full", "status": "success",
                               "elapsed_seconds": 7200 * 0.92, "timeout_seconds": 7200,
                               "gen_stats": _OK_STATS})
        assert step["state"] == "degraded"
        assert "예산" in step["reason"]

    def test_the_threshold_is_a_boundary_not_a_slope(self, tmp_path: Path) -> None:
        """임계 바로 아래는 `ok` 여야 한다 — 아니면 모든 성공이 경고가 된다."""
        from backend.routers.docgen_preflight import _TIGHT_BUDGET_RATIO
        below = _row(tmp_path, {"stage": "full", "status": "success",
                                "elapsed_seconds": 7200 * (_TIGHT_BUDGET_RATIO - 0.05),
                                "timeout_seconds": 7200, "gen_stats": _OK_STATS})
        assert below["state"] == "ok"

    def test_old_record_says_nothing_about_duration(self, tmp_path: Path) -> None:
        """못 잰 것을 0초로 그리면 '즉시 끝났다' 는 거짓이 된다."""
        step = _row(tmp_path, {"stage": "full", "status": "success",
                               "ended_at": "2026-08-07T15:46:35", "gen_stats": _OK_STATS})
        assert step["state"] == "ok"
        assert "소요" not in step["reason"]
        assert step["measured"]["elapsed_seconds"] is None

    def test_a_fast_failure_is_distinguishable_from_a_timeout(self, tmp_path: Path) -> None:
        """71초 만에 죽은 것과 1800초를 다 쓴 것은 원인이 다르다."""
        step = _row(tmp_path, {"stage": "degraded_light", "status": "failed",
                               "elapsed_seconds": 71.0, "timeout_seconds": 1800,
                               "error_tail": "PackageNotFoundError: nope"})
        assert "71초" in step["reason"]

    def test_timeout_does_not_repeat_the_limit_as_a_separate_clause(
        self, tmp_path: Path,
    ) -> None:
        """소요 문장이 이미 예산을 말하면 앞머리의 `상한 N초` 는 같은 수의 반복이다.

        ⚠ "`7200초` 가 한 번만 나온다" 로는 못 잰다 — 타임아웃은 소요와 예산이 같은
          수라서 정상 문장에서도 두 번 나온다. 재야 하는 것은 **절 하나가 사라졌는가** 다.
        """
        step = _row(tmp_path, {"stage": "full", "status": "timeout",
                               "elapsed_seconds": 7200.3, "timeout_seconds": 7200})
        assert "상한" not in step["reason"], step["reason"]
        assert "예산 7200초" in step["reason"]

    def test_timeout_without_elapsed_still_names_the_limit(self, tmp_path: Path) -> None:
        """옛 기록에서는 상한이 유일한 수치다 — 중복 제거가 그것까지 지우면 안 된다."""
        step = _row(tmp_path, {"stage": "full", "status": "timeout", "timeout_seconds": 7200})
        assert "7200초" in step["reason"]
