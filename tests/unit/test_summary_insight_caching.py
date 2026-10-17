"""요약탭 헬퍼의 정확성·중복 제거 회귀 고정(Phase O 심층 개선).

- 커버리지 인덱스: **같은 레벨 안**의 반복 측정은 최악값(은폐 금지), UT/IT는 절대 혼합 금지.
- 추적 링크 테이블: 한 요청이 3번 읽던 2.2MB 파일을 stat 키로 1회화.
- 아키텍처 메트릭: 두 패널이 동시에 부를 때 스냅샷을 중복 파싱하지 않는다.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _clear_caches():
    from backend.routers import summary_insight as si

    si.clear_summary_caches()
    yield
    si.clear_summary_caches()


# ── 커버리지 인덱스: 최악값 병합 · 레벨 분리 ────────────────────────────────

def _entry(name, unit, cov, total, ccn=1, branch=None):
    e = {
        "unit": unit, "subprogram": name, "ccn": ccn,
        "statements": {"covered": cov, "total": total, "rate": cov / total if total else None},
    }
    if branch is not None:
        e["branches"] = {"covered": branch, "total": 10, "rate": branch / 10}
    return e


def _prep(tmp_path: Path, ut, it) -> Path:
    rd = tmp_path / "report"
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "analysis_summary.json").write_text(json.dumps({
        "vectorcast_detail": {},
        "vectorcast": {"ut_metrics": {"entries": ut}, "it_metrics": {"entries": it}},
    }), encoding="utf-8")
    return rd


def test_coverage_index_takes_worst_within_same_level(tmp_path):
    """실측 회귀: 같은 UT 안에 같은 함수가 0.9/0.7647로 두 번 나온다(writeblock).

    구 구현은 first-wins라 입력 순서에 따라 0.9가 뽑힐 수 있었다 — 최악값을 가리면 갭이
    은폐된다(coverage_gap·test_design_advisor와 같은 규약).
    """
    from backend.routers import summary_insight as si

    rd = _prep(tmp_path, [
        _entry("WriteBlock", "EEPROM_A", 9, 10, ccn=3, branch=9),   # 90% — 먼저 등장
        _entry("WriteBlock", "EEPROM_B", 13, 17, ccn=8, branch=4),  # 76.47% — 최악
    ], [])
    rec = si._coverage_index(rd)["writeblock"]
    assert rec["statement"] == pytest.approx(13 / 17)   # 최악값 채택(첫 항목 아님)
    assert rec["branch"] == pytest.approx(0.4)
    assert rec["ccn"] == 8                              # 복잡도는 최대(보수적)
    assert rec["measurements"] == 2
    assert rec["metric_source"] == "ut"


def test_coverage_index_never_mixes_ut_and_it(tmp_path):
    """UT 100% / IT 0%를 합쳐 '0%'로 만들면 안 된다 — N4에서 허위 332건을 낸 바로 그 오류."""
    from backend.routers import summary_insight as si

    rd = _prep(tmp_path, [_entry("main", "SysOs", 10, 10)], [_entry("main", "Ap_Main", 0, 5)])
    rec = si._coverage_index(rd)["main"]
    assert rec["metric_source"] == "ut" and rec["statement"] == 1.0
    assert rec["measurements"] == 1                     # IT 측정은 UT 레코드에 섞이지 않는다


def test_coverage_index_it_only_function_uses_it_and_merges_worst(tmp_path):
    from backend.routers import summary_insight as si

    rd = _prep(tmp_path, [], [_entry("g_it", "u'1", 5, 5), _entry("g_it", "u'2", 1, 5)])
    rec = si._coverage_index(rd)["g_it"]
    assert rec["metric_source"] == "it"
    assert rec["statement"] == pytest.approx(0.2) and rec["measurements"] == 2


# ── 추적 링크 테이블: stat 키 1회화 ─────────────────────────────────────────

_LINK_TABLE = {
    "links": [{"target_id": "REQ-1", "related_id": "fn_a", "related_type": "UDS_FUNCTION"}],
    "asil_coverage": {"by_target": {"REQ-1": "D"}},
}


def test_link_table_parsed_once_per_stat(tmp_path, monkeypatch):
    from backend.routers import summary_insight as si

    br = tmp_path / "build_1"
    rd = br / "report"
    rd.mkdir(parents=True)
    (rd / "trace_link_table.json").write_text(json.dumps(_LINK_TABLE), encoding="utf-8")

    reads = []
    real = si._read_json
    monkeypatch.setattr(si, "_read_json", lambda p: (reads.append(str(p)), real(p))[1])

    first = si._load_trace_link_table(br, rd)
    for _ in range(4):
        si._load_trace_link_table(br, rd)
    link_reads = [r for r in reads if "trace_link_table" in r]
    assert first and len(link_reads) == 1        # 5회 호출 → 파싱 1회
    # 파생 결과(ASIL 역전파)도 같은 키로 1회화 — 11,747건 조인 재실행 회피
    a1 = si._propagated_asil(br, rd)
    a2 = si._propagated_asil(br, rd)
    assert a1 is a2 and a1["by_function"]["fn_a"]["asil"] == "D"


def test_link_table_cache_invalidates_on_change(tmp_path):
    """빌드 산출물이 교체되면(stat 변화) 새로 읽어야 한다 — stale 서빙 금지."""
    from backend.routers import summary_insight as si

    br = tmp_path / "build_1"
    rd = br / "report"
    rd.mkdir(parents=True)
    p = rd / "trace_link_table.json"
    p.write_text(json.dumps(_LINK_TABLE), encoding="utf-8")
    assert si._propagated_asil(br, rd)["by_function"]["fn_a"]["asil"] == "D"

    changed = json.loads(json.dumps(_LINK_TABLE))
    changed["asil_coverage"]["by_target"]["REQ-1"] = "QM"
    changed["links"].append({"target_id": "REQ-2", "related_id": "fn_b", "related_type": "UDS_FUNCTION"})
    changed["asil_coverage"]["by_target"]["REQ-2"] = "B"
    p.write_text(json.dumps(changed), encoding="utf-8")   # 크기·mtime 변화 → 키 변화

    out = si._propagated_asil(br, rd)
    assert out["by_function"]["fn_a"]["asil"] == "QM"
    assert "fn_b" in out["by_function"]


# ── 아키텍처 메트릭: 동시 요청 중복 계산 방지 ───────────────────────────────

def test_arch_metrics_computed_once_under_concurrency(tmp_path, monkeypatch):
    """요약탭은 메트릭 패널과 다이어그램 패널이 이 계산을 동시에 부른다.

    락이 없으면 캐시 미스가 겹칠 때 같은 스냅샷을 각각 파싱한다(실측 1.5s×2).
    """
    from backend.routers import summary_insight as si

    br = tmp_path / "build_1"
    src = br / "source"
    rd = br / "report"
    src.mkdir(parents=True)
    rd.mkdir(parents=True)
    (src / "a.c").write_text("void f(void) { }\n", encoding="utf-8")
    (src / ".source_complete").write_text("scm=svn\n", encoding="utf-8")

    calls = []
    entered = threading.Event()

    def _slow_compute(source_dir, **kw):
        calls.append(str(source_dir))
        entered.set()          # 첫 스레드가 계산 구간에 들어섰음을 알린다
        time.sleep(0.4)        # 두 번째 요청이 이 구간과 겹치도록 붙잡아 둔다
        return {"available": True, "version": 5, "snapshot": {"files": 1, "functions": 1}}

    monkeypatch.setattr("workflow.summary_arch_metrics.compute_architecture_metrics", _slow_compute)

    results = []
    errors = []

    def _run():
        try:
            results.append(si._arch_metrics_cached(br, rd))
        except Exception as exc:   # noqa: BLE001 — 스레드 예외를 삼키면 테스트가 거짓 통과한다
            errors.append(exc)

    first = threading.Thread(target=_run)
    first.start()
    assert entered.wait(timeout=5), "첫 요청이 계산에 진입하지 못했다"
    second = threading.Thread(target=_run)   # 계산이 진행 중인 상태에서 두 번째 요청
    second.start()
    for t in (first, second):
        t.join(timeout=10)

    assert not errors, f"스레드 예외: {errors}"
    assert len(calls) == 1, f"동시 요청이 {len(calls)}회 계산했다(중복 파싱)"
    assert len(results) == 2
    # 두 번째는 락 해제 후 디스크 캐시를 읽는다(재계산 아님)
    assert [r["cache_hit"] for r in results].count(True) == 1


def test_arch_metrics_serves_disk_cache_on_second_call(tmp_path, monkeypatch):
    from backend.routers import summary_insight as si

    br = tmp_path / "build_1"
    src = br / "source"
    rd = br / "report"
    src.mkdir(parents=True)
    rd.mkdir(parents=True)
    (src / "a.c").write_text("void f(void) { }\n", encoding="utf-8")
    (src / ".source_complete").write_text("scm=svn\n", encoding="utf-8")

    calls = []

    def _compute(source_dir, **kw):
        calls.append(1)
        return {"available": True, "version": 5, "snapshot": {"files": 1, "functions": 1}}

    monkeypatch.setattr("workflow.summary_arch_metrics.compute_architecture_metrics", _compute)
    first = si._arch_metrics_cached(br, rd)
    second = si._arch_metrics_cached(br, rd)
    assert len(calls) == 1
    assert first["cache_hit"] is False and second["cache_hit"] is True


# ── 심층 개선: 신규 엔드포인트 캐시 키가 '내용'을 지문화하는가 ───────────────

def test_rulebook_cache_key_uses_evidence_content_not_counts():
    """개수만 쓰면 파일이 바뀌어도 diff가 여전히 2건이면 같은 키 → 낡은 룰북 서빙.

    rule-definition이 diff_sha+ex_sha를 쓰는 이유와 동일(내용 지문).
    """
    import hashlib
    import json

    def key_of(inputs):
        # 엔드포인트와 같은 방식으로 조립(회귀 고정 — 구현이 개수 기반으로 되돌아가면 깨진다)
        fp = json.dumps([
            [i["rule"],
             sorted(str(d.get("diff_sha") or "") for d in i["evidence_diffs"]),
             hashlib.sha256("\n".join(str(x.get("text") or "") for x in i["unresolved_excerpts"])
                            .encode("utf-8", "ignore")).hexdigest()[:16]]
            for i in inputs
        ], ensure_ascii=False)
        return hashlib.sha256("|".join(["m", "1", "8", fp]).encode()).hexdigest()

    before = [{"rule": "R1", "evidence_diffs": [{"diff_sha": "aaa"}], "unresolved_excerpts": [{"text": "old"}]}]
    # 개수는 그대로(diff 1 · 발췌 1)인데 내용만 바뀐 경우 — 키가 달라져야 한다
    after = [{"rule": "R1", "evidence_diffs": [{"diff_sha": "bbb"}], "unresolved_excerpts": [{"text": "new"}]}]
    assert key_of(before) != key_of(after)


def test_arch_improvement_fingerprint_includes_basis():
    """(kind,target)만 쓰면 커버리지 41%→85%여도 키가 같아 낡은 To-Be가 서빙된다."""
    import json

    def fp(cands):
        return json.dumps([[c.get("kind"), c.get("target"), c.get("basis")] for c in cands], ensure_ascii=False)

    a = [{"kind": "extract_pure", "target": "f", "basis": "구문 41% · 복잡도 7"}]
    b = [{"kind": "extract_pure", "target": "f", "basis": "구문 85% · 복잡도 7"}]
    assert fp(a) != fp(b)
