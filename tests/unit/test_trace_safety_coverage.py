"""안전 요구(ASIL A~D) 커버리지 — 분모 0 은 **0% 가 아니라 미측정**이다.

배경: 이 지표는 원래 `/api/local/traceability`(호출자 0인 죽은 경로 — 2026-09-03 R27 에서 제거) 안에만 있었고
분모가 `max(safety_total, 1)` 이었다. 그대로 화면에 배선했으면 ASIL 등급이 붙은 요구가
하나도 없는 프로젝트에서 **"안전 요구 커버리지 0%"** 라는 없는 경보가 떴을 것이다.
사실은 잴 대상이 없다는 뜻이다(저장소 규약: 미측정 ≠ 0 ≠ 통과).

판정 출처는 둘이고 **같은 규칙**이어야 한다:
  · 백엔드  `backend/routers/jenkins.py::_cache_trace_summary` (대시보드 캐시)
  · 프론트  `frontend-v2/src/asilCoverage.js::deriveSafetyCoverage` (두 표면 공용)
프론트 쪽 행동 검증은 `frontend-v2/src/__tests__/asilCoverage.test.js`.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backend.routers.jenkins import _cache_trace_summary
from backend.schemas import UdsTraceabilityMatrixRequest
from tests.unit._source_probe import source_of

JOB_URL = "http://ci.example/job/SAFETY_TEST"


def _row(rid: str, asil: str, *, covered: bool) -> dict:
    """행 하나. `covered` 면 설계(SDS)와 SW 시험(STS)을 둘 다 채운다."""
    row: dict = {"requirement_id": rid, "asil": asil}
    if covered:
        row["sds_components"] = ["SwCom_01"]
        row["sts_tests"] = [{"source": "STS", "testcase": f"TC_{rid}"}]
    return row


def _payload(tmp_path: Path, rows: list) -> dict:
    """`_cache_trace_summary` 를 실제로 태우고 기록된 JSON 을 돌려준다."""
    from backend.routers.jenkins import _job_slug

    build = tmp_path / "jenkins" / _job_slug(JOB_URL) / "build_1"
    build.mkdir(parents=True)
    req = UdsTraceabilityMatrixRequest(job_url=JOB_URL, cache_root=str(tmp_path))
    _cache_trace_summary({"rows": rows, "summary": {}, "total_requirements": len(rows)}, req)
    written = build / "report" / "trace_matrix_summary.json"
    assert written.exists(), "요약이 기록되지 않았다 — 픽스처가 빌드 루트를 못 찾았다"
    return json.loads(written.read_text(encoding="utf-8"))


# ── 분모 0 ────────────────────────────────────────────────────────────────────

def test_no_asil_requirements_is_unmeasured_not_zero(tmp_path):
    """ASIL A~D 가 0건이면 `safety_pct` 는 **None** — 0.0 이면 없는 경보를 만든다."""
    data = _payload(tmp_path, [
        _row("SwR_01", "QM", covered=True),
        _row("SwR_02", "", covered=False),
    ])
    assert data["safety_total"] == 0
    assert data["safety_covered"] == 0
    assert data["safety_pct"] is None, "분모 0 을 0.0 으로 접으면 '안전 커버리지 0%' 로 읽힌다"


def test_zero_denominator_is_not_confused_with_a_real_zero(tmp_path):
    """진짜 0%(안전 요구는 있는데 하나도 추적 안 됨)와 **구별**된다."""
    real_zero = _payload(tmp_path / "a", [_row("SwR_01", "C", covered=False)])
    assert real_zero["safety_total"] == 1
    assert real_zero["safety_pct"] == 0.0          # 이건 진짜 0%

    no_target = _payload(tmp_path / "b", [_row("SwR_01", "QM", covered=True)])
    assert no_target["safety_pct"] is None         # 이건 잴 대상 없음
    assert real_zero["safety_pct"] != no_target["safety_pct"]


# ── 무엇을 세고 무엇을 빼는가 ────────────────────────────────────────────────

def test_only_asil_a_to_d_counts(tmp_path):
    """QM(비안전)과 미상(판단 불가)은 분모에서 빠진다."""
    data = _payload(tmp_path, [
        _row("SwR_01", "D", covered=True),
        _row("SwR_02", "A", covered=False),
        _row("SwR_03", "QM", covered=True),      # 비안전 — 제외
        _row("SwR_04", "", covered=True),        # 미상 — 제외
        _row("SwR_05", "ASIL D", covered=True),  # 정규화 실패 → 미상 — 제외
    ])
    assert data["safety_total"] == 2, "QM·미상이 분모에 섞였다"
    assert data["safety_covered"] == 1
    assert data["safety_pct"] == 50.0


def test_unknown_is_excluded_but_still_reported(tmp_path):
    """미상을 분모에서 뺐다는 사실이 화면에 닿을 수 있어야 한다.

    안 그러면 "안전 요구 100%" 가 **"안전 요구는 전부 검증됨"** 으로 읽힌다 —
    실측 KJPDS02_PV 가 정확히 그 형태다(A 62/62 = 100%, 미상 4건).
    """
    data = _payload(tmp_path, [
        _row("SwR_01", "A", covered=True),
        _row("SwR_02", "", covered=True),
        _row("SwR_03", "", covered=False),
    ])
    assert data["safety_pct"] == 100.0
    assert (data["asil_distribution"].get("UNKNOWN") or {}).get("total") == 2, \
        "미상 건수가 어디에도 안 남으면 100% 가 '전부 검증됨' 으로 오독된다"


def test_derived_from_the_same_distribution_not_a_second_count(tmp_path):
    """판정을 늘리지 않는다 — 같은 payload 의 `asil_distribution` 과 산술적으로 일치."""
    data = _payload(tmp_path, [
        _row("SwR_01", "D", covered=True),
        _row("SwR_02", "C", covered=True),
        _row("SwR_03", "B", covered=False),
        _row("SwR_04", "A", covered=True),
        _row("SwR_05", "QM", covered=True),
    ])
    dist = data["asil_distribution"]
    assert data["safety_total"] == sum(dist[g]["total"] for g in ("D", "C", "B", "A") if g in dist)
    assert data["safety_covered"] == sum(dist[g]["covered"] for g in ("D", "C", "B", "A") if g in dist)


# ── 프론트 ↔ 백엔드 lockstep ─────────────────────────────────────────────────

_JS = Path(__file__).resolve().parents[2] / "frontend-v2" / "src" / "asilCoverage.js"


def _js_array(name: str) -> list:
    m = re.search(rf"export const {name} = \[(.*?)\];", _JS.read_text(encoding="utf-8"), re.S)
    assert m, f"{name} 을 asilCoverage.js 에서 못 찾았다"
    return re.findall(r"'([^']+)'", m.group(1))


def _py_tuple(src: str, name: str) -> list:
    m = re.search(rf"{name} = \((.*?)\)", src, re.S)
    assert m, f"{name} 을 못 찾았다"
    return re.findall(r'"([^"]+)"', m.group(1))


def test_safety_grades_match_between_backend_and_frontend():
    """두 판정이 **같은 등급 집합**을 쓴다 — 갈리면 같은 문서가 표면마다 다른 값을 낸다."""
    backend = _py_tuple(source_of(_cache_trace_summary), "_SAFETY_GRADES")
    assert backend == _js_array("SAFETY_GRADES"), \
        f"등급 집합 불일치 — backend={backend} frontend={_js_array('SAFETY_GRADES')}"


def test_ai_input_uses_the_same_grade_set_as_the_screen():
    """AI 입력(`summary_ai_insight`)도 같은 등급 집합이다 — 판정 자리가 셋이 됐다.

    파이썬↔JS 경계라 리터럴을 공유할 수 없다. 갈리면 화면은 "안전 62/62" 인데
    AI 는 다른 분모로 권고를 쓴다 — 같은 프로젝트를 두고 두 값이 도는 형태.
    """
    from workflow.summary_ai_insight import _SAFETY_GRADES, _UNKNOWN_GRADE_KEYS

    assert list(_SAFETY_GRADES) == _js_array("SAFETY_GRADES"), \
        f"AI 입력 등급 집합이 화면과 다르다 — ai={list(_SAFETY_GRADES)}"
    assert list(_SAFETY_GRADES) == _py_tuple(source_of(_cache_trace_summary), "_SAFETY_GRADES"), \
        "AI 입력 등급 집합이 백엔드 캐시와 다르다"
    # 미상 철자도 같이 안다 — 하나만 알면 그 축에서 미상 건수가 조용히 0 이 된다.
    assert set(_UNKNOWN_GRADE_KEYS) == set(_js_array("UNKNOWN_GRADE_KEYS")) == {"UNKNOWN", "미상"}


def test_ai_input_derives_instead_of_reading_the_cached_percent():
    """AI 입력은 `safety_pct` 를 읽지 않고 **분포에서 다시 판정**한다.

    옛 캐시엔 `safety_*` 가 없다(실측: 저장소 캐시 6건 중 KJPDS02_PV 4건 포함 전부).
    캐시 값을 읽는 구현이면 화면엔 보이는 지표가 AI 입력에선 통째로 사라진다.
    """
    from workflow.summary_ai_insight import derive_safety_coverage

    old_cache = {  # safety_* 없음 — 2026-09-02 이전 캐시 shape
        "has_data": True,
        "asil_distribution": {"A": {"total": 62, "covered": 62}, "UNKNOWN": {"total": 4, "covered": 4}},
    }
    s = derive_safety_coverage(old_cache)
    assert s is not None and s["pct"] == 100.0 and s["unknown"] == 4


def test_frontend_knows_both_unknown_spellings():
    """백엔드는 'UNKNOWN', 상세탭 파생은 '미상' 을 쓴다 — 헬퍼가 **둘 다** 알아야 한다.

    하나만 알면 그 표면에서 미상 건수가 조용히 0 이 되고, 경고 문구가 사라진다.
    """
    assert set(_js_array("UNKNOWN_GRADE_KEYS")) == {"UNKNOWN", "미상"}


# ── 죽은 경로도 같은 규칙 ────────────────────────────────────────────────────

def test_dead_local_endpoint_is_gone_and_no_bad_formula_survives():
    """죽은 `/api/local/traceability` 는 **제거됐다**(2026-09-03 R27 B-2, 계획서 §8 #4).

    호출자가 없더라도 틀린 공식을 남겨 두면 다음 사람이 그걸 정본으로 읽는다 — 이 사태가
    정확히 그렇게 시작했다. 예전 이 가드는 죽은 사본의 공식이 옳은지 봤는데, 사본 자체를
    없앴으므로 이제 ①엔드포인트가 되살아나지 않고 ②`max(safety_total, 1)` 접기가 라우터
    어디에도 없다는 것을 본다.
    """
    routers = Path(__file__).resolve().parents[2] / "backend" / "routers"
    local_src = (routers / "local.py").read_text(encoding="utf-8")
    from backend.main import app
    assert "/api/local/traceability" not in {getattr(r, "path", "") for r in app.routes}, (
        "제거한 죽은 엔드포인트가 되살아났다")
    assert '"safety_pct"' not in local_src, "safety_* 사본이 local.py 에 다시 생겼다 — 정본은 jenkins.py 다"
    for p in routers.glob("*.py"):
        assert "max(safety_total, 1)" not in p.read_text(encoding="utf-8", errors="ignore"), (
            f"{p.name}: 분모 0 을 1 로 바꾸면 미측정이 0% 가 된다")


@pytest.mark.parametrize("grade", ["D", "C", "B", "A"])
def test_every_safety_grade_is_counted(tmp_path, grade):
    """등급 하나가 집합에서 빠지면 그 등급 요구가 통째로 분모에서 사라진다."""
    data = _payload(tmp_path / grade, [_row("SwR_01", grade, covered=True)])
    assert data["safety_total"] == 1, f"ASIL {grade} 가 안전 등급으로 안 세어졌다"
    assert data["safety_pct"] == 100.0

# ── 판정 복제 금지 ────────────────────────────────────────────────────────────

_SURFACES = {
    "대시보드 카드": "frontend-v2/src/components/ResultPanel.jsx",
    "추적성 상세탭": "frontend-v2/src/components/sections/SrsSdsSection.jsx",
    "개요 KPI": "frontend-v2/src/components/sections/SummaryOverviewTab.jsx",
}
_REPO = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("label,rel", sorted(_SURFACES.items()))
def test_every_surface_uses_the_shared_helper(label, rel):
    """세 표면이 전부 `asilCoverage.js` 를 쓴다 — 각자 계산하면 값이 갈린다.

    렌더 자체는 ResultPanel 만 행동 테스트로 덮인다(`TraceExtraSummary` 는 export 가
    없어 단독 마운트 불가). 남는 위험은 **그 자리에서 직접 세는 것**이라 여기서 막는다.
    """
    src = (_REPO / rel).read_text(encoding="utf-8")

    # ⚠ `"asilCoverage.js" in src` 로는 안 된다 — 그 문자열은 **주석**에도 있어서
    #   import 를 통째로 지운 뮤턴트가 생존했다(2026-09-02 실측). import 문 자체를 본다.
    imports = [
        L for L in src.splitlines()
        if L.lstrip().startswith("import ") and "asilCoverage.js" in L
    ]
    assert imports, f"{label}: asilCoverage.js 를 import 하는 **문장**이 없다"
    assert any("deriveSafetyCoverage" in L for L in imports), \
        f"{label}: deriveSafetyCoverage 를 들여오지 않는다 — {imports}"

    # 호출도 실제로 한다(주석이 아니라 코드에서).
    calls = [
        L for L in src.splitlines()
        if "deriveSafetyCoverage(" in L and not L.lstrip().startswith(("//", "*", "/*"))
    ]
    assert calls, f"{label}: 공용 파생을 호출하는 코드가 없다(주석만 있다)"
    # 자체 계산의 흔적 — **안전 등급만** 담은 완결된 배열이 있으면 그 자리에서 세고 있다.
    # ⚠ 첫 판은 부분문자열 "'D', 'C', 'B', 'A'" 를 봤는데, 그건 등급 칩의 **표시 순서**
    #   배열(['D','C','B','A','QM','UNKNOWN'])에도 들어 있어 멀쩡한 코드를 결함으로
    #   신고했다. 가드가 사실이 아니라 철자를 재면 그렇게 된다 — 닫는 괄호까지 본다.
    for smell in ("['D', 'C', 'B', 'A']", '("D", "C", "B", "A")'):
        assert smell not in src, f"{label}: 안전 등급 집합을 직접 나열한다 — 판정이 둘이 된다"


def test_helper_is_the_only_place_that_names_safety_grades():
    """안전 등급 집합이 프론트에 **한 곳**만 있어야 한다."""
    hits = [
        p.relative_to(_REPO).as_posix()
        for p in (_REPO / "frontend-v2" / "src").rglob("*.js*")
        if "SAFETY_GRADES" in p.read_text(encoding="utf-8")
    ]
    non_test = [h for h in hits if "__tests__" not in h]
    assert non_test == ["frontend-v2/src/asilCoverage.js"],         f"안전 등급 집합이 여러 곳에 있다 — {non_test}"
