"""SwUT/SwIT 빌더 공통 helper (38차 W1 — DRY 해결).

37차에서 도입된 `warnings: list[str] = list(session.parse_warnings or [])`
패턴이 빌더 4개 (swut_coverage / swut_sutr / swit_coverage / swit_sitr)에서
동일하게 반복되어 DRY 위반. 본 모듈로 추출해 단일 출처 보장.

향후 input_adapter ↔ 빌더 warning 통합 정책 변경 시 한 곳에서만 수정.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.services.swut_input_adapter import SwUTSession


def extract_warnings_from_session(session: "SwUTSession") -> list[str]:
    """input_adapter 단계 parse_warnings를 빌더 응답 warnings의 초기값으로 반환.

    37차 fix로 도입된 통합 정책 — env_prefix mismatch / auto-resolved release
    / sub-folder missing 등 input adapter 단계 메시지가 X-SwUT-Warnings /
    X-SwIT-Warnings 헤더에 노출되도록.

    Args:
        session: SwUT/SwIT 입력 어댑터 결과

    Returns:
        session.parse_warnings의 shallow copy. None이면 빈 list.
    """
    return list(session.parse_warnings or [])


def diagnose_asset_usage(
    swuts_map: dict | None = None,
    swits_map: dict | None = None,
    c_function_map: dict | None = None,
    swuds_function_map: dict | None = None,
    hmr_metric_count: int | None = None,
    hmr_matched_count: int | None = None,
) -> list[str]:
    """라운드 73 T816 — 입력 자산 활용도 진단 메시지 누적.

    각 자산이 제공됐는지 + 활용 entry 수를 audit reviewer에게 가시화. None인 자산은
    skip (메시지 없음). 빌더 응답 warnings에 통합되어 X-SwUT/SwIT-Warnings 헤더로 노출.

    Args:
        swuts_map: SwUTS xlsm parse 결과 (parse_swuts_xlsm.by_tc_id).
        swits_map: SwITS xlsm parse 결과 (동일 형식).
        c_function_map: C source parse 결과 (unit_id → CFunction dict).
        swuds_function_map: SwUDS docx parse 결과 (function_id → {heading, description, asil}).
        hmr_metric_count: HMR parsed metrics 총 수.
        hmr_matched_count: HMR matched (stamp) functions 수.

    Returns:
        list of "[stamp] ..." 형식 진단 메시지.
    """
    diag: list[str] = []
    if swuts_map is not None:
        n = len(swuts_map)
        # 활용 필드 수 측정 (precondition / test_method / generation_method)
        n_pre = sum(1 for v in swuts_map.values() if getattr(v, "precondition", ""))
        n_method = sum(1 for v in swuts_map.values() if getattr(v, "test_method", ""))
        n_gen = sum(1 for v in swuts_map.values() if getattr(v, "generation_method", ""))
        diag.append(
            f"[stamp] SwUTS spec 활용: {n} TC entries (precondition {n_pre}, "
            f"test_method {n_method}, generation_method {n_gen})"
        )
    if swits_map is not None:
        n = len(swits_map)
        n_pre = sum(1 for v in swits_map.values() if getattr(v, "precondition", ""))
        diag.append(
            f"[stamp] SwITS spec 활용: {n} TC entries (precondition {n_pre})"
        )
    if c_function_map is not None:
        n = len(c_function_map)
        n_sig = sum(1 for v in c_function_map.values() if v.get("signature"))
        n_desc = sum(1 for v in c_function_map.values() if v.get("comment_desc"))
        diag.append(
            f"[stamp] C source 활용: {n} functions (signature {n_sig}, comment_desc {n_desc})"
        )
    if swuds_function_map is not None:
        n = len(swuds_function_map)
        n_head = sum(1 for v in swuds_function_map.values() if v.get("heading_text"))
        n_desc = sum(1 for v in swuds_function_map.values() if v.get("description"))
        diag.append(
            f"[stamp] SwUDS 활용: {n} functions (heading {n_head}, description {n_desc})"
        )
    if hmr_metric_count is not None:
        matched = hmr_matched_count if hmr_matched_count is not None else 0
        match_pct = (matched / hmr_metric_count * 100) if hmr_metric_count > 0 else 0.0
        diag.append(
            f"[stamp] HMR 활용: {hmr_metric_count} metrics, {matched} matched ({match_pct:.1f}%)"
        )
    return diag


__all__ = ["extract_warnings_from_session", "diagnose_asset_usage"]
