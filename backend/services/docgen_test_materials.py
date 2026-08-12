"""시험 문서(STS/SUTS/SITS)의 **생성 재료** 측정.

UDS 는 "필드를 채우는" 문서지만 시험 문서는 **시험 케이스를 합성한다**. 재료가 없으면
문서가 안 만들어지는 게 아니라 **틀린 시험값이 만들어진다** — 그래서 게이트가 더 필요하다.

## 실측이 지목한 3축 (2026-08-10)

| 축 | HDPDM01 | KJPDS02 |
|---|---|---|
| SITS 통합 흐름 | 84 (캡 120, **여유 36**) | **120 (캡 120, 여유 0)** |
| SITS SDS Related 보강 | 조회 84 → 키매칭 38 → **SwCom 0** | 맵 없음 |
| SUTS 변수 타입 근거 확정 | 157/206 (76.2%) | 873/982 (88.9%) |

### ⚠ 캡은 "절단 0" 이 아니라 **"여유 N"** 을 봐야 한다

KJPDS02 는 후보 120 / 캡 120 으로 **경계에 정확히 닿아** 있다. 지금은 절단 0 이지만
함수가 하나만 늘어도 조용히 잘리기 시작한다. "절단 0" 만 보면 안전해 보인다.

### ⚠ 타입 폴백은 반환값으로 판정할 수 없다

`infer_variable_type` 의 폴백은 `"uint8_t"` 인데(`suts.py:578`) **진짜 u8 변수도 같은 값**
이라 구분이 안 된다. 0단계 실측도 처음엔 반환값으로 세어 "100% 확정" 이라는 거짓 수치를
냈다. 그래서 **근거 유무**(전역 타입 캐시 적중 또는 이름 패턴 매칭)로 판정한다.

폴백된 변수의 실체는 더 나쁘다 — 주석에 `range: 0x00000000 ~ 0xFFFFFFFF` 가 **적혀
있는데도** 안 읽고 `uint8_t`(0~255)로 박는다. 32비트 값에 8비트 경계값으로 시험을 만든다.

## ⚠ 무겁다 — 요청 안에서 돌리지 말 것

`generate_uds_source_sections` 는 실측 41초(350함수)~368초(750함수)다. `measure()` 는
전용 엔드포인트에서만 부르고, preflight 는 `has_cached()` 로 캐시 유무만 본다
(`docgen_comment_coverage` 와 같은 규약).
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger("devops_api.docgen_test_materials")

# `function_details` 캐시. `docgen_comment_coverage` 의 것과 **다른 파서**의 산출이라
# 따로 둔다(그쪽은 `parse_c_project`, 여기는 `generate_uds_source_sections`).
_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_CACHE_LOCK = threading.RLock()
_CACHE_TTL_S = 900.0


def _key(source_root: str) -> str:
    return str(source_root or "").strip().lower()


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


def has_cached(source_root: str) -> bool:
    """측정된 결과가 있는가 — preflight 가 이걸 먼저 본다."""
    with _CACHE_LOCK:
        hit = _CACHE.get(_key(source_root))
        return bool(hit and (time.time() - hit[0]) < _CACHE_TTL_S)


def cached(source_root: str) -> Optional[Dict[str, Any]]:
    with _CACHE_LOCK:
        hit = _CACHE.get(_key(source_root))
        if hit and (time.time() - hit[0]) < _CACHE_TTL_S:
            return hit[1]
    return None


def _load_sds_map(sds_path: str) -> Tuple[Dict[str, Any], str]:
    """SwDS 파티션 맵을 **worker 경유로** 만든다. 반환 ``(맵, 사유)``.

    ⚠ `_extract_sds_partition_map` 는 Path 직독이라 cloudium U: 를 못 연다. 그래서
    `materialize_via_resolver` 로 로컬에 떨군 뒤 연다 — 이 저장소의 하드 제약
    ("모든 cloudium 파일은 워커를 통해서")을 지키는 유일한 경로다.
    """
    if not sds_path:
        return {}, "SwDS 경로가 지정되지 않았습니다"
    try:
        from backend.services.resolver_helpers import materialize_via_resolver
        local, reason = materialize_via_resolver(sds_path)
        if not local:
            return {}, reason or "SwDS 를 읽지 못했습니다"
        from report_gen.requirements import _extract_sds_partition_map
        return (_extract_sds_partition_map(str(local)) or {}), ""
    except Exception as exc:  # noqa: BLE001 — docx/IPC 계열이 광범위
        _logger.warning("test_materials: SwDS 맵 실패 — %s", exc, exc_info=True)
        return {}, f"{type(exc).__name__}: {str(exc)[:120]}"


def _measure_sits(fd: Dict[str, Any], sds_map: Dict[str, Any],
                  sds_reason: str) -> Dict[str, Any]:
    from generators.sits import _DEFAULT_MAX_FLOWS, collect_integration_flows

    stats: Dict[str, Any] = {}
    # 캡을 **걸지 않고** 후보 총량을 잰다. 결과 길이로 되짚으면 절단을 못 본다
    # (`collect_integration_flows` docstring 이 못박아 둔 계약).
    flows = collect_integration_flows(fd, max_flows=None, stats_out=stats, sds_map=sds_map)
    total = int(stats.get("total_flows_found") or len(flows))
    cap = _DEFAULT_MAX_FLOWS
    headroom = cap - total

    sample = None
    if flows:
        f0 = flows[0]
        sample = {
            "entry_fn": str(f0.get("entry_fn") or ""),
            "call_chain": str(f0.get("call_chain") or "")[:160],
            "inputs": len(f0.get("input_vars") or []),
            "expected": len(f0.get("expected_vars") or []),
            "asil": str(f0.get("asil") or ""),
        }

    return {
        "flows_total": total,
        "cap": cap,
        # ⚠ 절단 건수가 아니라 **여유**를 낸다. 0 이면 경계에 닿아 있다는 뜻이고,
        #   소스가 조금만 늘어도 조용히 잘리기 시작한다.
        "headroom": headroom,
        "at_cap_boundary": headroom <= 0,
        "sds_map_entries": len(sds_map or {}),
        "sds_reason": sds_reason,
        "sds_lookups": stats.get("sds_lookups"),
        "sds_key_hits": stats.get("sds_key_hits"),
        # 실측상 실 SwDS 를 줘도 0 이다(맵 필드가 `kind` 뿐이라 코드가 읽는
        # `swcom`/`component` 가 없다). 그 0 을 **숨기지 않고** 올린다.
        "sds_swcom_hits": stats.get("sds_swcom_hits"),
        "sample_flow": sample,
    }


def _measure_suts_types(fd: Dict[str, Any]) -> Dict[str, Any]:
    """입출력 변수 중 **근거로** 타입이 정해진 비율.

    ⚠ `infer_variable_type` 의 반환값으로 판정하면 안 된다 — 폴백도 `uint8_t` 를
    돌려주고 진짜 u8 도 같은 값이라 구분 불가다(모듈 docstring 참조).
    """
    from generators.suts import _TYPE_NAME_PATTERNS, _globals_type_cache

    total = 0
    grounded = 0
    fallbacks: List[str] = []
    for info in (fd or {}).values():
        if not isinstance(info, dict):
            continue
        for key in ("inputs", "outputs"):
            raw = info.get(key)
            items = raw if isinstance(raw, list) else ([raw] if raw else [])
            for v in items:
                name = str(v or "").strip()
                if not name:
                    continue
                total += 1
                if name in _globals_type_cache or any(
                    pat.search(name) for pat, _ in _TYPE_NAME_PATTERNS
                ):
                    grounded += 1
                elif len(fallbacks) < 10:
                    fallbacks.append(name[:120])
    return {
        "variables": total,
        "grounded": grounded,
        "fallback": total - grounded,
        # 근거 없이 `uint8_t`(0~255)로 박히는 변수들. 여기에 `range:` 주석이 있는
        # 항목이 섞여 있으면 **읽을 수 있는 근거를 안 읽는 것**이므로 조치가 싸다.
        "fallback_samples": fallbacks,
    }


_DIR_TAG_RE = re.compile(r"^\s*\[(IN|OUT|INOUT|INDIRECT)\]", re.I)


def _dir_tag(entry: Any) -> str:
    """전역 엔트리의 방향 태그. 태그가 없으면 빈 문자열(= 휴리스틱이 판정한 축)."""
    m = _DIR_TAG_RE.match(str(entry or ""))
    return m.group(1).upper() if m else ""


_RET_TYPE_RE = re.compile(r"^\s*([\w\s\*]+?)\s+\w+\s*\(")
_RET_NOISE_RE = re.compile(r"\b(static|inline|extern|const|volatile)\b")


def _returns_value(info: Dict[str, Any]) -> bool:
    """이 함수가 **반환값을 가지는가**(void 가 아닌가)."""
    m = _RET_TYPE_RE.match(str((info or {}).get("prototype") or ""))
    if not m:
        return False
    t = _RET_NOISE_RE.sub("", m.group(1)).strip()
    return bool(t) and t.lower() != "void"


def _measure_suts_inputs(fd: Dict[str, Any], sds_map: Dict[str, Any]) -> Dict[str, Any]:
    """**입력 변수가 하나도 없는 unit** 과 그 사유.

    입력이 없는 시퀀스는 넣을 값이 없어 시험이 성립하지 않는다. 실측(2026-08-12, KJPDS02):
    948 TC 중 338 건이 입력 0개였는데 평균은 2.3 이라 기존 게이트를 그대로 통과했다.

    ⚠ **0 이 전부 결함은 아니다.** 정본(1,005 unit)도 172 건이 입력 0개다 — 파라미터도
      전역도 없는 함수가 실제로 있다. 그래서 건수만 내지 않고 **사유별로** 나눈다.
      사유를 안 나누면 "정상 0" 과 "잃어버린 0" 이 한 숫자에 섞여 판단할 수가 없다.
    """
    from generators.suts import collect_unit_functions

    try:
        units = collect_unit_functions(fd, sds_map=sds_map or {})
    except Exception as exc:  # noqa: BLE001 — 생성기 계열이 광범위
        _logger.warning("test_materials: SUTS unit 수집 실패 — %s", exc, exc_info=True)
        return {"measured": False, "reason": f"unit 수집 실패 ({type(exc).__name__})"}

    by_name = {
        str(i.get("name") or ""): i for i in (fd or {}).values() if isinstance(i, dict)
    }
    causes: Dict[str, int] = {}
    samples: Dict[str, List[str]] = {}
    no_input: List[str] = []
    for u in units:
        if u.get("input_vars"):
            continue
        name = str(u.get("name") or "")
        no_input.append(name)
        info = by_name.get(name) or {}
        globs = list(info.get("globals_global") or []) + list(info.get("globals_static") or [])
        tags = {_dir_tag(g) for g in globs}
        params = list(info.get("inputs") or [])
        stub_callees = [
            c for c in (info.get("calls_list") or [])
            if _returns_value(by_name.get(str(c)) or {})
        ]
        if not params and not globs and stub_callees:
            # 파라미터도 전역도 없지만 **반환값 있는 함수를 호출**한다. 단위시험에서는
            # 그 호출을 스텁으로 막고 반환값을 시험 입력으로 쓴다 — 정본이 실제로
            # `s_UDS_RDBI_ValidateSingleFrame() return` 같은 표기로 그렇게 적는다.
            # ⚠ **자동으로 채우지 않는다.** "비-void callee 를 전부 입력으로" 규칙을
            #   정본과 대조하면 맞음 55 · 과다 148 (정밀도 27%)이다. 문서에 그 값을 박으면
            #   근거처럼 보이는 오답이 148칸 생긴다. 그래서 값이 아니라 **후보로만** 알린다.
            cause = "stub_return_candidate"
        elif not params and not globs:
            cause = "no_params_no_globals"    # 파라미터도 전역도 없다 — 정상일 수 있다
        elif "IN" in tags or "INOUT" in tags:
            # 읽는 전역이 분명히 있는데 입력 열이 비었다 = **이름 추출이 버렸다**.
            # 실측된 경로: 이름 뒤 `(idx: …)`/`(range: …)` 꼬리, 로컬 임시 프리픽스 오탐,
            # 2글자 이하 이름. 정상이 아니므로 다른 사유와 절대 섞지 않는다.
            cause = "dropped_by_name_filter"
        elif params and not tags:
            # 파라미터 문자열은 있는데 이름이 안 나온다 — 주석 블록이 통째로 파라미터로
            # 딸려온 경우가 대부분이다(Processor Expert 계열 `*_GetVal`).
            cause = "param_string_unusable"
        elif tags and tags <= {"INDIRECT"}:
            cause = "indirect_only"           # 간접 접근뿐 — 직접 넣을 값이 없다
        elif tags and tags <= {"OUT"}:
            cause = "write_only"              # 전역을 쓰기만 한다
        elif "" in tags:
            cause = "untagged"                # 방향 태그가 없어 휴리스틱이 출력으로 보냈다
        else:
            cause = "other"
        causes[cause] = causes.get(cause, 0) + 1
        bucket = samples.setdefault(cause, [])
        if len(bucket) < 8:
            # 스텁 후보는 **어느 호출을 막아야 하는지**까지 줘야 조치할 수 있다.
            bucket.append(
                f"{name} ← {', '.join(stub_callees[:3])}"
                if cause == "stub_return_candidate" else name
            )
    return {
        "measured": True,
        "units": len(units),
        "units_without_input": len(no_input),
        # 정본 대비 기준선. "정상 0" 이 어느 정도인지 없이 건수만 보면 판단이 안 된다.
        "reference_without_input": 172,
        "reference_units": 1005,
        "causes": causes,
        "cause_samples": samples,
    }


def measure(source_root: str, *, sds_path: str = "") -> Dict[str, Any]:
    """시험 문서 재료를 측정한다. **느리다** — 전용 엔드포인트에서만 부를 것."""
    if not str(source_root or "").strip():
        return {"ok": False, "reason": "소스 루트가 지정되지 않았습니다"}

    t0 = time.time()
    try:
        from report_generator import generate_uds_source_sections
        fd = (generate_uds_source_sections(source_root) or {}).get("function_details", {}) or {}
    except Exception as exc:  # noqa: BLE001 — 파서 계열이 광범위
        _logger.warning("test_materials: 소스 파싱 실패 — %s", exc, exc_info=True)
        return {"ok": False, "reason": f"소스 파싱 실패 ({type(exc).__name__}: {str(exc)[:140]})"}

    if not fd:
        # 0 함수는 "함수가 없다" 가 아니라 대개 파싱이 안 된 것이다 — 사유와 함께 낸다.
        return {"ok": False, "reason": "소스에서 함수를 찾지 못했습니다", "functions": 0}

    sds_map, sds_reason = _load_sds_map(sds_path)
    result = {
        "ok": True,
        "functions": len(fd),
        "elapsed_s": round(time.time() - t0, 1),
        "sits": _measure_sits(fd, sds_map, sds_reason),
        "suts": _measure_suts_types(fd),
        "suts_inputs": _measure_suts_inputs(fd, sds_map),
    }
    with _CACHE_LOCK:
        _CACHE[_key(source_root)] = (time.time(), result)
    return result
