# tests/unit/test_docgen_last_run.py
"""**직전 생성이 어떻게 끝났는지**를 게이트가 읽는가.

## 이 파일이 지키는 것 (2026-09-01 실측 근거)

사용자 캐시에 남아 있던 UDS 생성 기록 3건 — 게이트는 셋 다 몰랐다:

| 시각 | 결말 | 실제 |
|---|---|---|
| 2026-08-07 | success | payload 함수 **0개**, 빈 heading 419개 — 문서는 템플릿 서식뿐 |
| 2026-08-10 | failed | 재시도 사다리 **끝까지** 실패, 산출물 없음 |
| 2026-08-11 | failed | 〃 |

체크포인트(`<out>.docx.stage.json`)에 전부 적혀 있었지만 **읽는 코드가 저장소에 없었다**
(`test_report_reachability.py::TestCheckpointIsRead` — R11 이전 이름은 `TestCheckpointIsWriteOnly`
였고 리더가 생기며 뒤집혔다).

## 규약 — 접지 않는다

- **기록 없음 ≠ 실패.** 행 자체를 내지 않는다(내면 첫 생성 전 프로젝트가 영구 `unknown`).
- **분모 0 ≠ 반영률 0%.** `payload_functions == 0` 이면 반영률을 재지 않는다.
- **`started` ≠ 성공.** 결말이 기록되지 않은 것이다.
- **반영률이 낮다 ≠ 실패.** 뒤집지 않는다. 다만 **한 개도 안 실린 것**은 전무다.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.routers.docgen_preflight import PreflightRequest, _last_run_step
from backend.services import docgen_last_run as lr
from backend.services.jenkins_helpers import _job_slug

JOB = "http://192.168.110.40:7000/job/DEMO_PV/"
OTHER_JOB = "http://192.168.110.40:7000/job/OTHER_DV/"
client = TestClient(app)
HEADERS = {"X-User": "tester"}


def _write(cache_root: Path, *, job_url: str = JOB, ts: str = "20260901_120000",
           record: dict | None = None, artifact: bool = False) -> Path:
    """라이터와 **같은 방식**으로 체크포인트를 놓는다.

    `_run_docx_in_subprocess` 는 `out_path.with_suffix(CHECKPOINT_SUFFIX)` 로 만든다 —
    여기서도 같은 상수를 써야 접미사가 갈렸을 때 이 픽스처가 먼저 깨진다.
    """
    out_dir = cache_root / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{lr.ARTIFACT_PREFIX}{_job_slug(job_url)}_{ts}.docx"
    if artifact:
        out_path.write_bytes(b"PK\x03\x04")
    cp = out_path.with_suffix(lr.CHECKPOINT_SUFFIX)
    cp.write_text(json.dumps(record if record is not None else {"status": "success"},
                             ensure_ascii=False), encoding="utf-8")
    return cp


def _req(cache_root: Path, *, doc_type: str = "uds", job_url: str = JOB) -> PreflightRequest:
    return PreflightRequest(doc_type=doc_type, job_url=job_url, cache_root=str(cache_root))


SUCCESS_57 = {
    "stage": "full", "status": "success", "ended_at": "2026-09-01T12:03:00",
    "gen_stats": {"payload_functions": 57, "matched_functions": 57,
                  "empty_heading_count": 8, "unmatched_payload_count": 0},
}
# 실측 기록(2026-08-07)을 그대로 옮긴 모양 — 분모가 0인 성공이다.
SUCCESS_EMPTY = {
    "stage": "full", "status": "success", "ended_at": "2026-08-07T15:46:35",
    "gen_stats": {"payload_functions": 0, "matched_functions": 0,
                  "empty_heading_count": 419, "match_pct": None},
}
# 실측 기록(2026-08-11) — traceback 의 마지막 줄이 곧 원인이다.
FAILED_LAST_STAGE = {
    "stage": "degraded_light", "status": "failed", "returncode": 1,
    "ended_at": "2026-08-11T09:35:27",
    "error_tail": (
        "참조 SUDS 의 프로젝트 신원을 확인하지 못했다(token_mismatch)\n"
        "Traceback (most recent call last):\n"
        '  File "<string>", line 1, in <module>\n'
        "docx.opc.exceptions.PackageNotFoundError: Package not found at 'U:/…/tpl.docx'"
    ),
}


# ══════════════════════════════════════════════════════════════════════════
# 기록을 찾는다
# ══════════════════════════════════════════════════════════════════════════

class TestFindingTheRecord:
    def test_newest_wins(self, tmp_path: Path) -> None:
        """단계마다 덮어쓰이므로 **마지막으로 기록된 것**이 결말이다."""
        old = _write(tmp_path, ts="20260810_170008", record={"status": "failed"})
        time.sleep(0.02)
        new = _write(tmp_path, ts="20260811_093505", record={"status": "success"})
        # mtime 을 명시적으로 벌려 파일시스템 해상도에 의존하지 않게 한다.
        os.utime(old, (1_700_000_000, 1_700_000_000))
        assert lr.find_last_run_checkpoint(str(tmp_path), JOB) == new

    def test_other_projects_record_is_not_picked(self, tmp_path: Path) -> None:
        """슬러그가 다르면 남의 기록이다 — 집으면 다른 프로젝트 결말을 공시한다."""
        _write(tmp_path, job_url=OTHER_JOB, record={"status": "failed"})
        assert lr.find_last_run_checkpoint(str(tmp_path), JOB) is None

    @pytest.mark.parametrize("hostile", ["*", "?", "a[b]c", "job/**/x", "../../../etc"])
    def test_job_url_cannot_smuggle_glob_metacharacters(self, tmp_path: Path,
                                                        hostile: str) -> None:
        """`job_url` 은 사용자 입력이고 곧장 **글로브 패턴**이 된다.

        `_job_slug` 이 화이트리스트(`[a-zA-Z0-9_.-]`)라 `*`·`?`·`[`·경로 구분자가 전부
        `_` 로 접힌다 — 그래서 남의 파일을 훑거나 상위로 올라갈 수 없다. 그 사실이
        **이 조회의 유일한 방벽**이므로 여기서 고정한다(슬러그 규칙이 느슨해지면 실패).
        """
        _write(tmp_path, record=SUCCESS_57)
        assert lr.find_last_run_checkpoint(str(tmp_path), hostile) is None

    def test_without_job_url_nothing_is_read(self, tmp_path: Path) -> None:
        """슬러그가 없으면 조회 자체를 하지 않는다(아무거나 집으면 남의 것을 집는다)."""
        _write(tmp_path)
        assert lr.find_last_run_checkpoint(str(tmp_path), "") is None

    def test_lookup_does_not_create_the_cache_dir(self, tmp_path: Path) -> None:
        """읽기 조회가 폴더를 만들면 **없는 캐시가 조회만으로 생겨난다**."""
        root = tmp_path / "brand_new"
        assert lr.find_last_run_checkpoint(str(root), JOB) is None
        assert not root.exists(), "조회가 캐시 루트를 만들었다"
        assert not (root / "exports").exists()


# ══════════════════════════════════════════════════════════════════════════
# 기록을 읽는다
# ══════════════════════════════════════════════════════════════════════════

class TestReadingTheRecord:
    def test_success_with_fidelity(self, tmp_path: Path) -> None:
        cp = _write(tmp_path, record=SUCCESS_57, artifact=True)
        run = lr.summarize_last_run(cp)
        assert run is not None
        assert (run["measurable"], run["payload_functions"], run["matched_functions"]) \
            == (True, 57, 57)
        assert run["artifact_exists"] is True
        assert run["when"] == "09/01 12:03"

    def test_zero_denominator_is_not_zero_percent(self, tmp_path: Path) -> None:
        """payload 0 은 '반영률 0%' 가 아니라 **잴 수 없음**이다."""
        run = lr.summarize_last_run(_write(tmp_path, record=SUCCESS_EMPTY))
        assert run is not None
        assert run["measurable"] is False
        # 잴 수 있는 축은 그대로 남는다 — 미측정이라고 전부 버리지 않는다.
        assert run["empty_heading_count"] == 419

    def test_cause_is_the_last_traceback_line(self, tmp_path: Path) -> None:
        """앞은 잘려 있어도 **끝은 온전**하다 — 예외 그 자체가 마지막 줄이다."""
        run = lr.summarize_last_run(_write(tmp_path, record=FAILED_LAST_STAGE))
        assert run is not None
        assert run["cause"].startswith("docx.opc.exceptions.PackageNotFoundError")
        assert "Traceback" not in run["cause"]

    def test_missing_artifact_is_reported(self, tmp_path: Path) -> None:
        run = lr.summarize_last_run(_write(tmp_path, record=FAILED_LAST_STAGE))
        assert run is not None and run["artifact_exists"] is False

    @pytest.mark.parametrize("blob", ["{ not json", '"a string"', "[]", "null"])
    def test_unreadable_record_is_none_not_success(self, tmp_path: Path, blob: str) -> None:
        """깨진 기록은 결말이 아니다 — `{}` 로 접으면 '성공' 가지로 흘러간다."""
        cp = _write(tmp_path)
        cp.write_text(blob, encoding="utf-8")
        assert lr.summarize_last_run(cp) is None

    def test_round9_and_round10_counters_are_carried(self, tmp_path: Path) -> None:
        """앞 라운드가 심은 관측량이 게이트까지 온다 — 중간에서 끊기면 침묵이 되살아난다."""
        cp = _write(tmp_path, record={
            "status": "success",
            "gen_stats": {"payload_functions": 57, "matched_functions": 57,
                          "restored_template_blocks": 1, "preserved_template_tables": 2,
                          "table_rows_recovered": 103, "table_rows_blank_trimmed": 2566,
                          "swcom_globals_unattributed": 24},
        })
        run = lr.summarize_last_run(cp)
        assert run is not None
        assert run["table_rows_recovered"] == 103
        assert run["swcom_globals_unattributed"] == 24
        assert run["preserved_template_tables"] == 2

    def test_old_records_without_the_counters_stay_none(self, tmp_path: Path) -> None:
        """옛 기록엔 그 키가 없다 — 0 으로 채우면 '없었다' 는 거짓이 된다."""
        run = lr.summarize_last_run(_write(tmp_path, record=SUCCESS_57))
        assert run is not None
        assert run["table_rows_recovered"] is None
        assert run["swcom_globals_unattributed"] is None


# ══════════════════════════════════════════════════════════════════════════
# 게이트 행
# ══════════════════════════════════════════════════════════════════════════

class TestTheGateRow:
    def test_no_record_means_no_row(self, tmp_path: Path) -> None:
        """한 번도 생성한 적 없는 프로젝트를 `unmeasured` 로 내면 **영구 `unknown`** 이다."""
        assert _last_run_step(_req(tmp_path)) is None

    @pytest.mark.parametrize("doc_type", ["sts", "suts", "sits", "swut"])
    def test_only_uds_writes_this_checkpoint(self, tmp_path: Path, doc_type: str) -> None:
        """다른 종류엔 이 축이 없다 — 행을 내면 '기록 없음' 이 '생성한 적 없음' 으로 읽힌다."""
        _write(tmp_path, record=SUCCESS_57)
        assert _last_run_step(_req(tmp_path, doc_type=doc_type)) is None

    def test_failure_is_degraded_and_names_the_cause(self, tmp_path: Path) -> None:
        _write(tmp_path, record=FAILED_LAST_STAGE)
        step = _last_run_step(_req(tmp_path))
        assert step is not None
        assert step["state"] == "degraded", "실패를 차단(missing/error)으로 올리지 않는다"
        assert step["phase"] == "history"
        assert "PackageNotFoundError" in step["reason"]
        assert "산출물 파일도 남지 않았습니다" in step["reason"]

    def test_exhausted_ladder_is_said_out_loud(self, tmp_path: Path) -> None:
        """마지막 단계까지 실패한 것은 같은 '실패' 라도 무게가 다르다."""
        _write(tmp_path, record=FAILED_LAST_STAGE)
        step = _last_run_step(_req(tmp_path))
        assert step is not None and "마지막 단계" in step["reason"]

    def test_failure_at_the_first_stage_does_not_claim_exhaustion(self, tmp_path: Path) -> None:
        """뮤테이션 방어 — 조건 없이 늘 '마지막 단계' 라고 쓰면 거짓 문장이 된다."""
        _write(tmp_path, record={**FAILED_LAST_STAGE, "stage": "full"})
        step = _last_run_step(_req(tmp_path))
        assert step is not None and "마지막 단계" not in step["reason"]

    def test_timeout_names_the_limit(self, tmp_path: Path) -> None:
        _write(tmp_path, record={"stage": "full", "status": "timeout",
                                 "timeout_seconds": 2400, "ended_at": "2026-09-01T13:00:00"})
        step = _last_run_step(_req(tmp_path))
        assert step is not None
        assert step["state"] == "degraded"
        assert "시간이 초과" in step["reason"] and "2400초" in step["reason"]

    def test_started_is_unmeasured_not_success(self, tmp_path: Path) -> None:
        """프로세스가 중단되면 이 상태로 남는다 — 성공으로 읽으면 정반대다."""
        _write(tmp_path, record={"stage": "full", "status": "started",
                                 "started_at": "2026-09-01T12:00:00"})
        step = _last_run_step(_req(tmp_path))
        assert step is not None
        assert step["state"] == "unmeasured"
        assert "끝이 기록되지 않았습니다" in step["reason"]

    def test_unknown_status_is_shown_verbatim(self, tmp_path: Path) -> None:
        """모르는 결말을 좋게도 나쁘게도 접지 않는다 — 코드를 그대로 보인다."""
        _write(tmp_path, record={"status": "who_knows", "stage": "full"})
        step = _last_run_step(_req(tmp_path))
        assert step is not None
        assert step["state"] == "unmeasured" and "who_knows" in step["reason"]

    def test_good_run_is_ok_and_shows_the_ratio(self, tmp_path: Path) -> None:
        _write(tmp_path, record=SUCCESS_57, artifact=True)
        step = _last_run_step(_req(tmp_path))
        assert step is not None
        assert step["state"] == "ok"
        # `Measured` 가 이미 아는 두 키 — 화면이 새 키를 배우지 않아도 숫자가 보인다.
        assert (step["measured"]["value"], step["measured"]["of"]) == (57, 57)
        assert "57개" in step["reason"]

    def test_nothing_landed_is_degraded(self, tmp_path: Path) -> None:
        """반영률이 낮은 것은 부분집합일 수 있지만 **0 은 전무**다."""
        _write(tmp_path, record={
            "stage": "full", "status": "success",
            "gen_stats": {"payload_functions": 57, "matched_functions": 0,
                          "empty_heading_count": 8},
        }, artifact=True)
        step = _last_run_step(_req(tmp_path))
        assert step is not None
        assert step["state"] == "degraded"
        assert "하나도 실리지 않았습니다" in step["reason"]

    def test_partial_fill_is_not_called_a_failure(self, tmp_path: Path) -> None:
        """뮤테이션 방어 — 낮은 반영률까지 degraded 로 올리면 대량 오탐이 된다."""
        _write(tmp_path, record={
            "stage": "full", "status": "success",
            "gen_stats": {"payload_functions": 432, "matched_functions": 336,
                          "empty_heading_count": 75},
        }, artifact=True)
        step = _last_run_step(_req(tmp_path))
        assert step is not None and step["state"] == "ok"

    @pytest.mark.parametrize("stats", [
        {},                                                   # gen_stats 자체가 없다
        {"payload_functions": 57},                            # 분자가 없다
        {"matched_functions": 57},                            # 분모가 없다
    ])
    def test_missing_numbers_are_unmeasured_not_zero(self, tmp_path: Path,
                                                     stats: dict) -> None:
        """**'잴 수 없다' 에는 두 가지가 있고 뜻이 정반대다.**

        payload 가 `0` 이라고 *기록된* 것은 사실(결함)이고, 수치가 *없는* 것은 미측정이다.
        둘을 한 문장으로 합치면 후자에 대고 "실을 함수가 0개" 라는 거짓을 말하게 된다.
        """
        _write(tmp_path, record={"stage": "full", "status": "success",
                                 "gen_stats": stats}, artifact=True)
        step = _last_run_step(_req(tmp_path))
        assert step is not None
        assert step["state"] == "unmeasured"
        assert "기록되지 않았습니다" in step["reason"]
        assert "0개" not in step["reason"], "미측정을 '0개' 로 말하면 거짓이다"

    def test_zero_denominator_success_says_what_it_can(self, tmp_path: Path) -> None:
        """실측 2026-08-07 — 파일은 생겼는데 실을 함수가 0개였다."""
        _write(tmp_path, record=SUCCESS_EMPTY, artifact=True)
        step = _last_run_step(_req(tmp_path))
        assert step is not None
        assert step["state"] == "degraded"
        assert "실을 함수가 0개" in step["reason"]
        assert "419" in step["reason"], "잴 수 있는 축까지 버리면 진단이 사라진다"
        # 분모가 없으므로 반영률은 그리지 않는다.
        assert "value" not in step["measured"] and "of" not in step["measured"]


# ══════════════════════════════════════════════════════════════════════════
# 응답 표면까지 도달하는가
# ══════════════════════════════════════════════════════════════════════════

class TestItReachesTheResponse:
    def _post(self, payload: dict) -> dict:
        r = client.post("/api/docgen/preflight", json=payload, headers=HEADERS)
        assert r.status_code == 200, r.text
        return r.json()

    def test_the_row_is_in_the_api_response(self, tmp_path: Path) -> None:
        """행을 만들기만 하고 `steps` 에 안 넣으면 결함은 그대로다."""
        _write(tmp_path, record=FAILED_LAST_STAGE)
        data = self._post({"doc_type": "uds", "job_url": JOB,
                           "cache_root": str(tmp_path)})
        row = next((s for s in data["steps"] if s["id"] == "last_run"), None)
        assert row is not None, "직전 생성 행이 응답에 없다"
        assert row["state"] == "degraded"

    def test_absent_record_adds_no_row(self, tmp_path: Path) -> None:
        data = self._post({"doc_type": "uds", "job_url": JOB,
                           "cache_root": str(tmp_path)})
        assert all(s["id"] != "last_run" for s in data["steps"])


# ══════════════════════════════════════════════════════════════════════════
# 읽는 쪽이 쓰는 쪽에 묶여 있는가
# ══════════════════════════════════════════════════════════════════════════

class TestNamingIsBoundToTheWriters:
    """이름 규칙이 갈리면 글로브가 아무것도 못 찾고, 그건 **'생성한 적 없음'** 과 구분되지
    않는다 — 행이 조용히 사라지는 것이므로 화면으로는 절대 알 수 없다."""

    def test_writer_uses_the_shared_suffix_constant(self) -> None:
        src = Path("backend/helpers/uds.py").read_text(encoding="utf-8")
        assert "out_path.with_suffix(CHECKPOINT_SUFFIX)" in src
        assert '.with_suffix(".docx.stage.json")' not in src, "리터럴이 되살아났다"

    def test_no_checkpoint_literal_anywhere_but_the_constant(self) -> None:
        """이름 규칙 리터럴은 **정의 한 곳**에만 있다 — 저장소 전체(도구 포함)를 센다.

        예전 가드는 `helpers/uds.py` 만 봐서 `tools/generate_uds_local.py` 의 리터럴 3곳이
        계약 밖에서 살았다(2026-09-03 R27 H-2). 세 번째 복제였다.
        """
        import subprocess
        # **파이썬 문자열 리터럴**만 센다(`".docx.stage.json"` / `'.docx.stage.json'`) —
        # docstring 산문의 `` `<out>.docx.stage.json` `` 은 규칙 복제가 아니다.
        # `-F` 고정 문자열(`.` 이 임의 문자가 되지 않게) · `--untracked` 로 훅 시점의 신규 파일도
        # 본다 · **rc 를 검사한다** — git 이 실패하면 stdout 이 비어 `offenders=[]` 로 거짓
        # 통과하던 fail-open 이 있었다(R27 리뷰 W1).
        proc = subprocess.run(
            ["git", "grep", "-n", "-F", "--untracked",
             "-e", '".docx.stage.json"', "-e", "'.docx.stage.json'", "--",
             "backend", "tools", "scripts", "report_gen", "workflow", "generators"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        assert proc.returncode in (0, 1), f"git grep 실패(rc={proc.returncode}) — 판정 불가: {proc.stderr[:200]}"
        out = proc.stdout.splitlines()
        offenders = [ln for ln in out
                     if not ln.startswith("backend/services/docgen_last_run.py:")
                     and not ln.split(":", 2)[-1].lstrip().startswith("#")]
        assert not offenders, "체크포인트 이름 규칙 리터럴이 정의 밖에 있다:\n" + "\n".join(offenders)

    @pytest.mark.parametrize("path", ["backend/helpers/uds.py",
                                      "backend/routers/jenkins.py"])
    def test_both_writers_use_the_artifact_prefix(self, path: str) -> None:
        """쌍둥이 라이터 둘 다 같은 접두사를 쓴다(실측: 글자까지 같은 f-string)."""
        src = Path(path).read_text(encoding="utf-8")
        hits = re.findall(r'f"([a-z_]+)\{job_slug\}_\{ts\}\.docx"', src)
        assert hits, f"{path}: UDS 산출물 이름 규칙을 찾지 못했다"
        assert all(h == lr.ARTIFACT_PREFIX for h in hits), \
            f"{path}: 접두사가 {set(hits)} — 읽는 쪽은 {lr.ARTIFACT_PREFIX!r} 을 찾는다"

    def test_the_writers_path_is_actually_found(self, tmp_path: Path) -> None:
        """라이터가 만드는 그 경로를 리더가 찾는가 — 규칙이 아니라 **왕복**을 잰다."""
        out_dir = tmp_path / "exports"
        out_dir.mkdir(parents=True)
        out_path = out_dir / f"{lr.ARTIFACT_PREFIX}{_job_slug(JOB)}_20260901_120000.docx"
        out_path.with_suffix(lr.CHECKPOINT_SUFFIX).write_text("{}", encoding="utf-8")
        found = lr.find_last_run_checkpoint(str(tmp_path), JOB)
        assert found is not None
        assert lr._artifact_of(found) == out_path

    def test_retry_ladder_is_read_not_copied(self) -> None:
        """사다리 이름을 복제하면 바꿀 때 한쪽만 고쳐지고 문장이 조용히 틀려진다."""
        import config
        assert lr.last_retry_stage() == str(config.UDS_DOCX_RETRY_STAGES[-1][0])
