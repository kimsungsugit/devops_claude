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
    SwIT 요청은 SwITS spec을 우선 사용한다. 기존 API field 이름은
    ``swuts_docx_path``로 유지하되 config fallback은 ``swits_docx_path`` 또는
    ``iso26262_docs.swits_xlsm_path``를 먼저 본다.

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
    iso_docs = cfg.get("iso26262_docs", {}) or {}
    req_type = type(req).__name__.lower()
    if req_type.startswith("swit"):
        return (
            cfg.get("swits_docx_path")
            or iso_docs.get("swits_xlsm_path")
            or cfg.get("swuts_docx_path")
            or iso_docs.get("swuts_xlsm_path")
            or ""
        ).strip()
    return (
        cfg.get("swuts_docx_path")
        or iso_docs.get("swuts_xlsm_path")
        or ""
    ).strip()


def resolve_swuts_test_specs(
    req: Any, project_id: str,
    *,
    out_warnings: list[str] | None = None,
) -> dict[str, Any] | None:
    """60차 F6-A — swuts_docx_path xlsm → {tc_id: SwUTSEntry} dict.

    SUTR Test Log stamp 시 caller가 tc_name (예: 'SwUTC_0121')으로 lookup하여
    description / precondition / test_method / generation_method 추출.

    F6 자체평가 Round 1 W1 + W4 fix:
        - `out_warnings` 옵션 — 사용자/audit reviewer가 spec stamp 실패 인지하도록
          parse_warnings / read 실패 사유 누적. None이면 기존 silent 동작 (backward-compat).
        - `OSError` catch 확대 — Cloudium worker 통신 오류, BadZipFile 등 견고화.

    Args:
        req: SwUT/SwIT BuildRequest (덕 타이핑).
        project_id: req.project_id.
        out_warnings: list[str] (mutable) — 실패 사유 push 받음.

    Returns:
        {tc_id: SwUTSEntry} dict 또는 None (path 비었거나 parse 실패).
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
            if out_warnings is not None:
                out_warnings.append(
                    f"[swuts] parse 실패 — spec stamp skip, 하드코딩 fallback 적용. "
                    f"사유: {'; '.join(parse_warnings) or 'unknown'}"
                )
            return None
        return result.by_tc_id
    except (FileNotFoundError, PermissionError, OSError) as e:
        _logger.warning("SwUTS xlsm read failed: %s", e)
        if out_warnings is not None:
            out_warnings.append(
                f"[swuts] read 실패 — spec stamp skip. {type(e).__name__}: {e}"
            )
        return None


def resolve_hmr_html_path(req: Any, project_id: str) -> str:
    """60차 F6-C — req.hmr_html_path 우선, 비면 config의 project별 값 fallback.

    VectorCAST aggregate metrics report (Jenkins_PDSM_UT/IT_metrics_report.html)
    경로. Coverage Report 함수별 Function Calls metric stamp source.

    Args:
        req: SwUTBuildRequest 또는 SwITBuildRequest (덕 타이핑 — `hmr_html_path` 속성).
        project_id: req.project_id.

    Returns:
        path string. req와 config 모두 비면 빈 string.
    """
    req_value = getattr(req, "hmr_html_path", "") or ""
    if req_value:
        return req_value
    cfg = load_meta_from_config(project_id)
    return (cfg.get("hmr_html_path") or "").strip()


def resolve_hmr_html_bytes(
    req: Any, project_id: str,
    *,
    out_warnings: list[str] | None = None,
) -> bytes | None:
    """60차 F6-C — hmr_html_path → HTML bytes.

    Coverage Report builder의 `hmr_html_bytes` 인자에 직접 전달. None이면 stamp
    skip (backward-compat, 기존 v2.02/v3.01 빈 cell default 유지).

    F6 자체평가 Round 1 W1 + W4 fix:
        - `out_warnings` 옵션 — read 실패 사유 누적.
        - `OSError` catch 확대.

    Returns:
        bytes 또는 None (path 비었거나 read 실패).
    """
    hmr_path = resolve_hmr_html_path(req, project_id)
    if not hmr_path:
        return None
    from backend.services.file_resolver import get_resolver
    try:
        resolver = get_resolver()
        return resolver.read_bytes(hmr_path)
    except (FileNotFoundError, PermissionError, OSError) as e:
        _logger.warning("HMR HTML read failed: %s", e)
        if out_warnings is not None:
            out_warnings.append(
                f"[hmr] read 실패 — Function Calls metric stamp skip. "
                f"{type(e).__name__}: {e}"
            )
        return None


# 라운드 89 — SwUDS docx parse 캐시. 36MB+ docx가 빌드당 2회(resolve_swuds_maps +
# resolve_swuds_function_ids) + Coverage/SUTR 각각 = 최대 4회 read+parse(파싱 ~수십초/회).
# path 키 캐시로 중복 read+parse 제거. read-only U: 설계 docx는 동일 process(세션)
# 동안 정적 가정 — 변경 시 backend 재시작으로 모듈 캐시 자연 무효. 동일 path는 1회만.
_SWUDS_PARSE_CACHE: dict[str, Any] = {}


def _cached_parse_swuds(path: str) -> Any:
    """swuds docx를 path 키 캐시로 1회만 read+parse → SwUDSParseResult 반환.

    read 예외(FileNotFoundError/PermissionError/OSError)는 caller가 처리하도록
    전파(캐시 안 함). parse 결과(ok 여부 무관, 동일 bytes 결정적)는 캐시.
    """
    cached = _SWUDS_PARSE_CACHE.get(path)
    if cached is not None:
        return cached
    from backend.services.file_resolver import get_resolver
    from backend.services.swut_swuds_parser import parse_swuds_docx
    docx_bytes = get_resolver().read_bytes(path)
    result = parse_swuds_docx(docx_bytes, parse_warnings=[])
    _SWUDS_PARSE_CACHE[path] = result
    return result


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
    try:
        result = _cached_parse_swuds(swuds_path)  # 라운드 89 — path 키 캐시
        if not result.ok:
            _logger.warning("SwUDS parse failed (function_ids)")
            return None
        return result.function_ids
    except (FileNotFoundError, PermissionError, OSError) as e:
        # F6 Round 3 NC2: OSError 확대 정책 일관성 — swuts/hmr 함수와 대칭.
        _logger.warning("SwUDS docx read failed: %s", e)
        return None


def resolve_swuds_function_asil_map(req: Any, project_id: str) -> dict[str, str]:
    """32차 W28 + 49차 — swuds_docx_path → SwUDS 'ASIL' 라벨 → function_asil_map.

    plan vs 구현 divergence (54-fix I2 / 55차):
        plan의 `kind` 인자는 req 객체 속성으로 흡수. 자세히는 `resolve_swuds_path`.

    Returns:
        {fn_id: "A"/"B"/"C"/"D"/"QM"} — 실패 시 빈 dict.
    """
    # 라운드 89: 단일 parse seam(resolve_swuds_maps)에 위임 — id→ASIL만 반환
    # (backward compat). name→id가 추가로 필요하면 resolve_swuds_maps 직접 호출.
    return resolve_swuds_maps(req, project_id)[0]


def resolve_swuds_maps(
    req: Any, project_id: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """라운드 89 — SwUDS docx 1회 parse → (function_asil_map, function_name_to_id).

    36MB+ docx를 여러 번 파싱하면 timeout/메모리 폭증 → 단일 parse로 두 맵 동시
    도출. ``apply_function_asil_map`` 이 reverse map(name→id) 구성에 사용.

    Returns:
        (``{SwUFn_id: ASIL}``, ``{name: SwUFn_id}``) — 실패 시 (빈, 빈).
    """
    swuds_path = resolve_swuds_path(req, project_id)
    if not swuds_path:
        return {}, {}
    try:
        result = _cached_parse_swuds(swuds_path)  # 라운드 89 — path 키 캐시 (중복 parse 제거)
        if not result.ok:
            _logger.warning("SwUDS ASIL parse failed")
            return {}, {}
        return dict(result.function_asil_map), dict(result.function_name_to_id)
    except (FileNotFoundError, PermissionError, OSError) as e:
        # F6 Round 3 NC2: OSError 확대 — swuts/hmr 함수와 대칭.
        _logger.warning("SwUDS docx read for ASIL failed: %s", e)
        return {}, {}


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

    # 라운드 89 — SwUDS docx를 1회만 parse (36MB docx 다중 파싱 timeout/메모리
    # 폭증 회피). resolve_swuds_maps가 id→ASIL (merge용) + name→id (reverse map)을
    # 단일 parse로 반환. 이전: id-only 함수 + iso26262 regex extractor 2개가 각각
    # 36MB docx를 별도 파싱 (~3~4회, 1.3GB×N, >200s timeout) → 단일 seam으로 통합.
    swuds_map, swuds_name_to_id = resolve_swuds_maps(req, project_id)

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

    # 라운드 89 — SUDS reverse maps 주입 (위 단일 parse 결과 재사용).
    # 이유: coverage 함수 unit_id는 빌더 순차(SwUFn_0001..)라 SwUDS 문서 id
    # (SwUFn_0101..)와 직접 매칭 실패 → `_compute_asil_distribution`의 함수명
    # reverse 경로(name_to_swufn + suds_map)가 필요. (이전엔 round 84-85 extractor가
    # 정의만 되고 미배선이라 KJPDS02 ASIL 전부 UNKNOWN.)
    if swuds_map:
        session.function_asil_from_suds = swuds_map
    if swuds_name_to_id:
        session.function_name_to_swufn_from_suds = swuds_name_to_id
    if swuds_map or swuds_name_to_id:
        session.parse_warnings.append(
            f"SUDS reverse map (라운드 89) — ASIL {len(swuds_map)}건 / "
            f"name→SwUFn {len(swuds_name_to_id)}건 주입 (단일 parse)"
        )


__all__ = [
    "load_meta_from_config",
    "resolve_swuds_path",
    "resolve_c_source_root",
    "resolve_swuds_function_ids",
    "resolve_swuds_function_asil_map",
    "resolve_swuds_maps",
    "apply_function_asil_map",
    "resolve_swuts_path",
    "resolve_swuts_test_specs",
    "resolve_hmr_html_path",
    "resolve_hmr_html_bytes",
]
