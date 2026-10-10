"""'ID 정합성' 문제 수의 두 표면 lockstep — 상세 패널 기준 == 요약/AI 기준.

`dangling` 은 두 축이다:
  suspect  SRS 에 쓰이는 namespace 인데 그 ID 만 부재 → 오타/오참조 **결함**
  foreign  SRS 에 없는 namespace(SwFn_/SwST_ 같은 설계ID) → V-model 상 **정상, 정보성**

상세 패널(`SrsSdsSection.jsx` `integNoDefect`)은 처음부터 suspect 만으로 '정합성 ✓'를
판정했는데, 요약 배너·KPI·AI 프롬프트는 `dangling_count` 전량을 셌다. 같은 문서를
6건(요약) vs 3건(상세)으로 보고하던 것 — 저장소 동봉 HDPDM01 실측은 dangling 4건 중
3건이 설계ID(75% 허위)였다.

AI 경로는 특히 나쁘다. 없는 결함이 tester 조치 항목("추적성 ID 정합성 정리")으로
그대로 생성됐다.
"""
from __future__ import annotations

import pytest

from workflow.summary_ai_insight import curate_trace_summary


def _trace(**over):
    base = {
        "has_data": True,
        "total_requirements": 68, "covered": 68, "uncovered": 0, "coverage_pct": 100.0,
        "asil_gap_count": 0, "asil_unknown_count": 0,
        "integrity_clean": False,
        "integrity_collision_count": 0,
        "integrity_dangling_count": 4,            # 전량(suspect 1 + foreign 3)
        "integrity_dangling_suspect_count": 1,    # 결함인 것만
        "integrity_placeholder_count": 0,
    }
    base.update(over)
    return base


def _gaps(trace):
    """curate → build_detail 의 gaps 축만 뽑는다(전체 파이프라인 구동 없이)."""
    from workflow.summary_ai_insight import (
        SummaryInsightInput,
        build_deterministic_insight,
    )

    inp = SummaryInsightInput(headline={"coverage_line": 90.0},
                              trace_summary=curate_trace_summary(trace))
    det = build_deterministic_insight(inp)
    return {g["kind"]: g for g in det["gaps"]}


def test_curate_carries_suspect_axis():
    """정제 축이 큐레이션 결과에 남아야 소비처가 결함만 셀 수 있다."""
    cur = curate_trace_summary(_trace())
    assert cur["integrity"]["dangling_suspect_count"] == 1
    assert cur["integrity"]["dangling_count"] == 4      # 관측치는 유지(정보 손실 없음)


def test_ai_gap_counts_suspect_not_total():
    """AI 조치 축은 suspect 1건 — 전량 4를 넘기면 없는 결함 3건을 LLM 이 근거로 쓴다."""
    g = _gaps(_trace())["integrity_dangling"]
    assert g["count"] == 1
    assert not g.get("unrefined")


def test_ai_gap_absent_when_only_foreign():
    """foreign 만 있으면 조치 항목 자체가 없어야 한다(결함 0 = 침묵이 아니라 정상)."""
    gaps = _gaps(_trace(integrity_dangling_count=3, integrity_dangling_suspect_count=0))
    assert "integrity_dangling" not in gaps


def test_stale_cache_falls_back_but_marks_unrefined():
    """구 캐시엔 suspect 축이 없다 — 조용히 빼면 결함 침묵, 그냥 쓰면 부풀린 수치가
    정확한 척한다. 전량을 쓰되 `unrefined` 로 표시해 소비처가 구분할 수 있어야 한다."""
    stale = _trace()
    del stale["integrity_dangling_suspect_count"]
    g = _gaps(stale)["integrity_dangling"]
    assert g["count"] == 4
    assert g["unrefined"] is True


def test_unrefined_basis_text_says_so():
    """정제 전 수치가 tester 근거 문구에서 정확한 값처럼 보이면 안 된다."""
    from workflow.summary_ai_insight import (
        SummaryInsightInput,
        _deterministic_role_guidance,
        build_deterministic_insight,
    )

    def _basis(trace):
        inp = SummaryInsightInput(headline={"coverage_line": 90.0},
                                  trace_summary=curate_trace_summary(trace))
        guide = _deterministic_role_guidance(build_deterministic_insight(inp), inp)
        return " ".join(r.get("basis", "") for r in (guide.get("tester") or []))

    stale = _trace()
    del stale["integrity_dangling_suspect_count"]
    assert "정제 전" in _basis(stale) and "계층참조 포함" in _basis(stale)

    fresh_basis = _basis(_trace())
    assert "오참조 의심 1건" in fresh_basis
    assert "정제 전" not in fresh_basis


def test_cache_payload_exposes_suspect_axis():
    """백엔드 캐시가 suspect 축을 실어야 프론트 두 표면이 같은 기준을 쓸 수 있다.

    필드가 빠지면 프론트는 `?? integrity_dangling_count` 로 폴백해 예전(부풀린) 값으로
    조용히 되돌아간다 — 그래서 생산 지점을 구조로 고정한다.
    """
    import re
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "backend" / "routers" / "jenkins.py"
    text = src.read_text(encoding="utf-8", errors="ignore")
    assert re.search(r'"integrity_dangling_suspect_count":\s*int\(\s*integ_stats\.get\(\s*"dangling_suspect_count"',
                     text), "trace_matrix_summary 캐시에 suspect 축이 없다"


@pytest.mark.parametrize("collision,suspect,expect_defect", [
    (0, 0, False),   # foreign 만 → 결함 아님
    (0, 1, True),
    (2, 0, True),
])
def test_defect_criterion_matches_detail_panel(collision, suspect, expect_defect):
    """상세 패널의 '정합성 ✓' 판정식(collision·suspect·placeholder)과 같은 축인지."""
    cur = curate_trace_summary(_trace(
        integrity_collision_count=collision, integrity_dangling_suspect_count=suspect))
    integ = cur["integrity"]
    has_defect = bool(integ["collision_count"] or integ["dangling_suspect_count"]
                      or integ["placeholder_count"])
    assert has_defect is expect_defect
