"""54차 T281 — SwUT/SwIT 라우터 공통 path resolver + ASIL 매핑 DRY 통합.

50차/49차 W4/W5에서 도입된 config fallback 로직 (`_resolve_swuds_path`,
`_resolve_c_source_root`, `_apply_function_asil_map`)이 `backend/routers/swut.py`
와 `backend/routers/swit.py`에 거의 동일하게 중복 (~70줄). 본 모듈로 통합하여
단일 진리 source 확보 — audit 추적성 향상 + 양쪽 동기화 위험 제거.

`config/swut_meta.json`의 lru_cache + mtime invalidate 패턴도 동일하게 통합.

## 정책 (32차 W28 + 50차 W4/W5 유지)

- ASIL source 우선순위: c_source_root (Doxygen @asil) > swuds_docx_path (SwUDS docx)
- 충돌 시 c_source 우선 + parse_warnings에 사유 누적 (32차 W28)
- session.parse_warnings에 source origin 누적 — "c_source N건 (req)" / "(config fallback)"
- req 비면 config fallback — 잘못된 config path도 시각화 (50차 W4)

## Backward compat

라우터 layer의 `_resolve_*` / `_apply_*` private 함수는 thin wrapper로 남기고
본 모듈의 public 함수를 호출. monkeypatch 의존 회귀가 import 경로 무영향.
"""
from __future__ import annotations

import functools
import json
import logging
import os
from typing import Any

_logger = logging.getLogger(__name__)

_META_CONFIG_PATH = "config/swut_meta.json"


@functools.lru_cache(maxsize=1)
def _read_meta_config_raw(mtime: float) -> dict[str, Any]:  # noqa: ARG001
    """lru_cache key = mtime. config 파일 수정 시 자동 cache miss → reload.

    ``mtime`` 인자는 본문에서 사용하지 않지만 ``functools.lru_cache`` 의 hash key 역할.
    """
    if not os.path.isfile(_META_CONFIG_PATH):
        return {}
    try:
        with open(_META_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f) or {}
    except (OSError, json.JSONDecodeError) as e:
        _logger.warning("swut_meta.json load failed: %s", e)
        return {}


def load_meta_from_config(project_id: str) -> dict[str, Any]:
    """config/swut_meta.json 에서 project별 fixed 메타 로드 — mtime 기반 캐시."""
    try:
        mtime = os.path.getmtime(_META_CONFIG_PATH)
    except OSError:
        return {}
    cfg = _read_meta_config_raw(mtime)
    return cfg.get("projects", {}).get(project_id, {}) or {}


def resolve_swuds_path(req: Any, project_id: str) -> str:
    """49차 — req.swuds_docx_path 우선, 비면 config의 project별 값 fallback.

    plan vs 구현 divergence (54-fix I2 / 55차):
        54차 plan에서 `kind: Literal["swut", "swit"]` 인자 명시했으나 실제 구현은
        req 객체의 `swuds_docx_path` 속성만 사용. SwUT/SwIT BuildRequest 모두
        동일한 속성명을 가지므로 덕 타이핑으로 흡수. 향후 SwUT/SwIT 라우터별
        동작이 분기 필요해질 때 kind 인자 도입 검토.

    Args:
        req: SwUTBuildRequest 또는 SwITBuildRequest (덕 타이핑 — `swuds_docx_path`
            속성 + `project_id` 속성 polymorphic 지원).
        project_id: req.project_id (caller 명시 — 검색 path와 분리하여 명시성 확보).

    Returns:
        절대/상대 path string. 둘 다 비면 빈 string.
    """
    req_value = getattr(req, "swuds_docx_path", "") or ""
    if req_value:
        return req_value
    cfg = load_meta_from_config(project_id)
    return (cfg.get("swuds_docx_path") or "").strip()


def resolve_c_source_root(req: Any, project_id: str) -> str:
    """49차 — req.c_source_root 우선, 비면 config의 project별 값 fallback.

    plan vs 구현 divergence (54-fix I2 / 55차):
        plan의 `kind` 인자는 req 객체의 `c_source_root` 속성으로 흡수 (덕 타이핑).
        SwUT/SwIT 라우터 모두 동일 속성명. 자세히는 `resolve_swuds_path` docstring 참조.

    Args:
        req: SwUTBuildRequest 또는 SwITBuildRequest (덕 타이핑).
        project_id: req.project_id.
    """
    req_value = getattr(req, "c_source_root", "") or ""
    if req_value:
        return req_value
    cfg = load_meta_from_config(project_id)
    return (cfg.get("c_source_root") or "").strip()


def resolve_swuts_path(req: Any, project_id: str) -> str:
    """60차 F6-A — req.swuts_docx_path 우선, 비면 config의 project별 값 fallback.

    field 명은 ``swuts_docx_path`` 로 유지 (사용자 mental model + 49차 swuds와
    네이밍 일관성). 실제 파일은 xlsm/docx 모두 허용 — parser가 자동 분기.

    Args:
        req: SwUTBuildRequest 또는 SwITBuildRequest (덕 타이핑 — `swuts_docx_path`
            속성).
        project_id: req.project_id.

    Returns:
        path string. req와 config 모두 비면 빈 string.
    """
    req_value = getattr(req, "swuts_docx_path", "") or ""
    if req_value:
        return req_value
    cfg = load_meta_from_config(project_id)
    return (cfg.get("swuts_docx_path") or "").strip()


def resolve_swuts_test_specs(
    req: Any, project_id: str,
) -> dict[str, Any] | None:
    """60차 F6-A — swuts_docx_path xlsm → {tc_id: SwUTSEntry} dict.

    SUTR Test Log stamp 시 caller가 tc_name (예: 'SwUTC_0121')으로 lookup하여
    description / precondition / test_method / generation_method 추출.

    Args:
        req: SwUT/SwIT BuildRequest (덕 타이핑).
        project_id: req.project_id.

    Returns:
        {tc_id: SwUTSEntry} dict 또는 None (path 비었거나 parse 실패).
        실패 시 _logger.warning만 emit (caller는 None 받고 graceful skip).
    """
    swuts_path = resolve_swuts_path(req, project_id)
    if not swuts_path:
        return None
    from backend.services.file_resolver import get_resolver
    from backend.services.swuts_excel_parser import parse_swuts_xlsm
    try:
        resolver = get_resolver()
        xlsm_bytes = resolver.read_bytes(swuts_path)
        parse_warnings: list[str] = []
        result = parse_swuts_xlsm(xlsm_bytes, parse_warnings=parse_warnings)
        if not result.ok:
            _logger.warning("SwUTS parse failed: %s", parse_warnings)
            return None
        return result.by_tc_id
    except (FileNotFoundError, PermissionError) as e:
        _logger.warning("SwUTS xlsm read failed: %s", e)
        return None


def resolve_swuds_function_ids(req: Any, project_id: str) -> set[str] | None:
    """16차 + 49차 — swuds_docx_path가 있으면 docx → function ID set 반환.

    plan vs 구현 divergence (54-fix I2 / 55차):
        plan의 `kind` 인자는 req 객체 속성으로 흡수 (덕 타이핑). 자세히는
        `resolve_swuds_path` docstring 참조.

    실패 시 None — caller는 SwUDS 비교 skip + warnings에 사유 누적.
    """
    swuds_path = resolve_swuds_path(req, project_id)
    if not swuds_path:
        return None
    # 지연 import — circular dependency 방지
    from backend.services.file_resolver import get_resolver
    from backend.services.swut_swuds_parser import parse_swuds_docx
    try:
        resolver = get_resolver()
        docx_bytes = resolver.read_bytes(swuds_path)
        parse_warnings: list[str] = []
        result = parse_swuds_docx(docx_bytes, parse_warnings=parse_warnings)
        if not result.ok:
            _logger.warning("SwUDS parse failed: %s", parse_warnings)
            return None
        return result.function_ids
    except (FileNotFoundError, PermissionError) as e:
        _logger.warning("SwUDS docx read failed: %s", e)
        return None


def resolve_swuds_function_asil_map(req: Any, project_id: str) -> dict[str, str]:
    """32차 W28 + 49차 — swuds_docx_path → SwUDS 'ASIL' 라벨 → function_asil_map.

    plan vs 구현 divergence (54-fix I2 / 55차):
        plan의 `kind` 인자는 req 객체 속성으로 흡수. 자세히는 `resolve_swuds_path`.

    Returns:
        {fn_id: "A"/"B"/"C"/"D"/"QM"} — 실패 시 빈 dict.
    """
    swuds_path = resolve_swuds_path(req, project_id)
    if not swuds_path:
        return {}
    from backend.services.file_resolver import get_resolver
    from backend.services.swut_swuds_parser import parse_swuds_docx
    try:
        resolver = get_resolver()
        docx_bytes = resolver.read_bytes(swuds_path)
        parse_warnings: list[str] = []
        result = parse_swuds_docx(docx_bytes, parse_warnings=parse_warnings)
        if not result.ok:
            _logger.warning("SwUDS ASIL parse failed: %s", parse_warnings)
            return {}
        return dict(result.function_asil_map)
    except (FileNotFoundError, PermissionError) as e:
        _logger.warning("SwUDS docx read for ASIL failed: %s", e)
        return {}


def apply_function_asil_map(req: Any, session: Any, project_id: str) -> None:
    """30차 W21 + 32차 W28 + 50차 W4/W5 — function_asil_map 주입.

    Policy:
        - c_source_root (Doxygen @asil — implementation truth) >
          swuds_docx_path (설계 문서)
        - 충돌 시 c_source 우선 + parse_warnings 누적
        - source origin 명시 ("req" vs "config fallback")

    plan vs 구현 divergence (54-fix I2 / 55차):
        plan의 `kind: Literal["swut", "swit"]` 인자는 req 객체의 `c_source_root` /
        `swuds_docx_path` 속성 polymorphic으로 흡수 (덕 타이핑). SwUT/SwIT 동일
        속성명이라 동일 함수가 두 라우터 모두 호환. 향후 분기 필요 시 kind 도입 검토.

    Args:
        req: SwUT/SwIT BuildRequest (덕 타이핑 — c_source_root + swuds_docx_path 속성).
        session: SwUTSession 또는 호환 객체 (environments + parse_warnings 속성).
        project_id: req.project_id 명시.

    Side effects:
        session.environments[0].function_asil_map 채움 + session.parse_warnings 누적.
    """
    c_source_root = resolve_c_source_root(req, project_id)
    swuds_path = resolve_swuds_path(req, project_id)
    if not (c_source_root or swuds_path):
        return

    c_source_map: dict[str, str] = {}
    if c_source_root:
        try:
            from backend.services.swut_asil_resolver import resolve_function_asil_map
            result = resolve_function_asil_map(c_source_root)
            if result.warnings:
                session.parse_warnings.extend(result.warnings)
            c_source_map = dict(result.function_asil_map)
        except Exception as e:  # pragma: no cover — top-level safety net
            _logger.warning("c_source function_asil_map resolve failed: %s", e)
            session.parse_warnings.append(
                f"c_source ASIL resolve 실패 — {type(e).__name__}"
            )

    swuds_map = resolve_swuds_function_asil_map(req, project_id)

    # Merge — c_source 우선 (swuds는 c_source 없는 키만 채움)
    merged = dict(swuds_map)
    conflicts = [
        (fid, swuds_map[fid], c_source_map[fid])
        for fid in c_source_map
        if fid in swuds_map and swuds_map[fid] != c_source_map[fid]
    ]
    merged.update(c_source_map)

    # 50차 W4/W5: source origin 시각화 — config fallback 사용 여부 노출.
    sources_used = []
    req_c_source = getattr(req, "c_source_root", "") or ""
    req_swuds = getattr(req, "swuds_docx_path", "") or ""
    if c_source_root:
        origin = "req" if req_c_source else "config fallback"
        sources_used.append(f"c_source {len(c_source_map)}건 ({origin})")
    if swuds_path:
        origin = "req" if req_swuds else "config fallback"
        sources_used.append(f"SwUDS {len(swuds_map)}건 ({origin})")
    if sources_used:
        session.parse_warnings.append(
            "function_asil_map source — "
            + ", ".join(sources_used)
            + f", merged {len(merged)}건"
        )

    for fid, swuds_val, c_val in conflicts:
        session.parse_warnings.append(
            f"ASIL 충돌 '{fid}': SwUDS={swuds_val} vs c_source={c_val} "
            "— c_source 우선 채택"
        )

    if merged and session.environments:
        session.environments[0].function_asil_map = merged


__all__ = [
    "load_meta_from_config",
    "resolve_swuds_path",
    "resolve_c_source_root",
    "resolve_swuds_function_ids",
    "resolve_swuds_function_asil_map",
    "apply_function_asil_map",
    "resolve_swuts_path",
    "resolve_swuts_test_specs",
]
