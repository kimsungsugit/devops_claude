"""시험 문서(STS/SUTS/SITS)의 **생성 재료** 측정.

UDS 는 "필드를 채우는" 문서지만 시험 문서는 **시험 케이스를 합성한다**. 재료가 없으면
문서가 안 만들어지는 게 아니라 **틀린 시험값이 만들어진다** — 그래서 게이트가 더 필요하다.

## 실측이 지목한 3축 (2026-08-10)

| 축 | HDPDM01 | KJPDS02 |
|---|---|---|
| SITS 통합 흐름 | 84 (캡 120, **여유 36**) | **120 (캡 120, 여유 0)** |
| SITS SDS Related 보강 | 조회 84 → 키매칭 38 → **SwCom 0** | 맵 없음 |
| SUTS 변수 타입 근거 확정 | 157/206 (76.2%) | 873/982 (88.9%) |

## 뒤에 붙은 2축 (2026-08-14) — **사람이 판단해야 하는 것**을 화면으로 올린다

| 축 | KJPDS02_PV 실측 |
|---|---|
| STS 요구-함수 매핑 (`sts_mapping`) | 68 중 **20 미매핑** — SwDS 엔 있는데 못 닿음 16 / SwDS 에 아예 없음 4 |
| SUTS 안전 등급의 근거 (`suts_asil`) | 등급 962개 중 **425**(퍼지 181 + 후보 갈림 244)가 부분문자열 첫 일치 |

⚠ STS 는 오래 이 파일 밖에 있었다. 그런데 STS 야말로 **재료가 없어도 TC 가 나온다** —
매핑이 빈 요구는 `_generate_review_steps` 로 소스 근거 0 인 리뷰 절차가 채워지고,
요구 커버리지는 100% 로 보인다. 안 재면 그 사실이 어디에도 안 나온다.

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
                  sds_reason: str, uds_path: str = "") -> Dict[str, Any]:
    """통합 흐름과 그 **Related/Safety 근거**를 잰다.

    ⚠ 이 칸들을 실제로 채우는 건 SwDS 가 아니라 **SwUDS** 다. SDS 파티션 맵의 값
    스키마에는 SwCom 축이 아예 없어 `sds_swcom_hits` 는 **구조적으로 0** 이고
    (`test_sits_sds_related_source.py:33-36` 이 문서화), Safety 칸의 1순위 근거도
    SwUDS 함수 ASIL 이다. 그래서 SwUDS 를 안 받으면 게이트는 **보강이 꺼진 상태**를
    재게 되고, 산출물보다 나쁜 숫자를 보고한다 — 실측으로는 "SwCom 0건, 추적성 열이
    합성 ID 만 남습니다" 를 보여주는데 라이브 생성기는 같은 프로젝트에서 SwCom
    **699 토큰**을 채운다(방향이 반대로 읽힌다).
    같은 이유로 `_measure_sts_mapping` 은 이미 `uds_path` 를 받는다 — 그 수정에서
    이 함수만 빠져 있었다.
    ⚠ `uds_path` 가 없으면 그 사실을 `uds` 로 **명시**한다(빠진 것을 0 으로 접지 않는다).
    """
    from generators.sits import (
        _DEFAULT_MAX_FLOWS,
        collect_integration_flows,
        load_uds_asil_map,
        load_uds_related_map,
        load_uds_swcom_map,
    )

    # ⚠ 없을 때 `{}` 가 아니라 **None** 을 넘긴다. `collect_integration_flows` 는
    #   `uds_related_map is None` 일 때만 swcom 맵으로 폴백하므로, 빈 dict 를 주면
    #   폴백까지 꺼져 현행보다 나쁜 조건이 된다.
    uds: Dict[str, Any] = {"on": False, "reason": "SwUDS 경로가 지정되지 않았습니다"}
    _uds_swcom = _uds_asil = _uds_related = None
    if str(uds_path or "").strip():
        try:
            from backend.services.resolver_helpers import resolve_builder_input
            _local_uds = resolve_builder_input(uds_path, label="SwUDS")
            if not _local_uds:
                uds = {"on": False, "reason": "SwUDS 를 읽지 못했습니다"}
            else:
                _uds_swcom = load_uds_swcom_map(_local_uds) or {}
                _uds_asil = load_uds_asil_map(_local_uds) or {}
                _uds_related = load_uds_related_map(_local_uds) or {}
                uds = ({"on": True, "functions": len(_uds_related),
                        "asil_functions": len(_uds_asil)}
                       if _uds_related else
                       {"on": False, "reason": "SwUDS 에서 Related ID 를 찾지 못했습니다"})
        except Exception as exc:  # noqa: BLE001 — docx/IPC 계열이 광범위
            _logger.warning("test_materials: SwUDS Related/ASIL 맵 실패 — %s", exc,
                            exc_info=True)
            uds = {"on": False,
                   "reason": f"SwUDS 파싱 실패 ({type(exc).__name__}: {str(exc)[:120]})"}

    stats: Dict[str, Any] = {}
    # 캡을 **걸지 않고** 후보 총량을 잰다. 결과 길이로 되짚으면 절단을 못 본다
    # (`collect_integration_flows` docstring 이 못박아 둔 계약).
    flows = collect_integration_flows(
        fd, max_flows=None, stats_out=stats, sds_map=sds_map,
        uds_swcom_map=_uds_swcom, uds_asil_map=_uds_asil,
        uds_related_map=_uds_related)
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
        # `swcom`/`component` 가 없다). 그 0 을 **숨기지 않고** 올린다 —
        # 다만 **판정 근거는 아니다**(구조적 0 을 결함으로 읽으면 항상 빨간불).
        "sds_swcom_hits": stats.get("sds_swcom_hits"),
        # ── Related/Safety 를 실제로 채우는 축 ──────────────────────────
        "uds": uds,
        "uds_lookups": stats.get("uds_swcom_lookups"),
        "uds_hits": stats.get("uds_swcom_hits"),
        "uds_related_ids": stats.get("uds_swcom_ids"),
        # 진입 함수 자신이 아니라 호출 트리 아래에서 온 근거(거리가 다르다)
        "related_chain_flows": stats.get("related_chain_flows"),
        "related_chain_ids": stats.get("related_chain_ids"),
        # Related 칸에는 안 실리는 SRS 유래 요구 링크(정본 어휘가 설계 ID 뿐).
        # ⚠ **이 경로의 0 은 "링크가 없다" 가 아니다** — 이 측정은 SRS enrichment
        #   (`generate_sits` 의 SwRS 설명문 매칭)를 타지 않으므로 항상 0 에 가깝다.
        #   라이브 산출물은 같은 프로젝트에서 12흐름/13개를 낸다. 화면에 이 값을 그대로
        #   띄우면 방금 SwDS 축에서 고친 것과 **같은 오독**이 한 층 위에 생기므로,
        #   패널에는 싣지 않고 여기서 사유와 함께만 남긴다.
        "req_id_flows": stats.get("req_id_flows"),
        "req_id_total": stats.get("req_id_total"),
        "req_id_scope": "source_only",   # SRS enrichment 미포함
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


def _dir_tag(entry: Any) -> str:
    """전역 엔트리의 방향 태그. 태그가 없으면 빈 문자열(= 휴리스틱이 판정한 축).

    ⚠ 판정은 `generators.suts.dir_tag` **단일 출처**를 쓴다. 여기 정규식을 복제해
      뒀다가 `[INDIRECT2]`(2홉 전파)를 못 읽어 사유 분포가 그걸 "태그 없음" 으로
      셌다 — 그 사이 진짜 소비처(`collect_unit_functions`)는 같은 항목을 입력으로
      올리고 있었으므로, **게이트가 보는 그림과 산출물이 서로 달랐다**.
    """
    from generators.suts import dir_tag

    return dir_tag(entry)


def _settable_globals(globs: List[Any], gim: Optional[Dict[str, Any]]) -> List[Any]:
    """산출물이 **실제로 넣는** 전역만 남긴다(= const 억제 후).

    ⚠ 방향 태그를 억제 **전** 목록에서 뽑으면 오분류가 난다: const 전역의 `[IN]` 이
      남아 "읽는 전역이 있는데 입력 열이 비었다"(= 이름 추출이 버렸다, **결함**)로
      찍힌다. 실제로는 우리가 의도적으로 뺀 것이다.
    ⚠ 판정과 이름 정리 둘 다 `generators.suts` **단일 출처**를 쓴다. 여기 복제해 두면
      소비처가 억제하는 집합과 이 패널이 세는 집합이 갈라진다(`_dir_tag` 주석의 전례).
    """
    from generators.suts import _clean_global_name, _is_const_global

    if not gim:
        return list(globs or [])          # 근거가 없으면 억제도 없다 — 그대로 센다
    return [g for g in (globs or []) if not _is_const_global(_clean_global_name(g), gim)]


_RET_TYPE_RE = re.compile(r"^\s*([\w\s\*]+?)\s+\w+\s*\(")
_RET_NOISE_RE = re.compile(r"\b(static|inline|extern|const|volatile)\b")


def _returns_value(info: Dict[str, Any]) -> bool:
    """이 함수가 **반환값을 가지는가**(void 가 아닌가)."""
    m = _RET_TYPE_RE.match(str((info or {}).get("prototype") or ""))
    if not m:
        return False
    t = _RET_NOISE_RE.sub("", m.group(1)).strip()
    return bool(t) and t.lower() != "void"


def _measure_suts_inputs(
    fd: Dict[str, Any],
    sds_map: Dict[str, Any],
    globals_info_map: Optional[Dict[str, Any]] = None,
    *,
    units_out: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """**입력 변수가 하나도 없는 unit** 과 그 사유.

    입력이 없는 시퀀스는 넣을 값이 없어 시험이 성립하지 않는다. 실측(2026-08-12, KJPDS02):
    948 TC 중 338 건이 입력 0개였는데 평균은 2.3 이라 기존 게이트를 그대로 통과했다.

    ⚠ **0 이 전부 결함은 아니다.** 정본(1,005 unit)도 172 건이 입력 0개다 — 파라미터도
      전역도 없는 함수가 실제로 있다. 그래서 건수만 내지 않고 **사유별로** 나눈다.
      사유를 안 나누면 "정상 0" 과 "잃어버린 0" 이 한 숫자에 섞여 판단할 수가 없다.

    Args:
        units_out: 주면 수집한 unit 목록을 여기 담는다. `collect_unit_functions` 는
            이 측정에서 가장 비싼 단계라, ASIL 근거 축(`_measure_suts_asil`)이 다시
            부르면 같은 일을 두 번 한다. 저장소의 `stats_out` 규약과 같은 모양이다.
    """
    from generators.suts import collect_unit_functions

    try:
        # ⚠ `globals_info_map` 을 빠뜨리면 이 패널이 **실제 산출물과 다른 unit 목록**을
        #   센다 — const 전역 억제가 여기서만 안 걸려 "입력 0개" 판정이 어긋난다.
        units = collect_unit_functions(fd, globals_info_map or {}, sds_map=sds_map or {})
    except Exception as exc:  # noqa: BLE001 — 생성기 계열이 광범위
        _logger.warning("test_materials: SUTS unit 수집 실패 — %s", exc, exc_info=True)
        return {"measured": False, "reason": f"unit 수집 실패 ({type(exc).__name__})"}
    if units_out is not None:
        units_out.extend(units)

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
        settable = _settable_globals(globs, globals_info_map)
        tags = {_dir_tag(g) for g in settable}
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
        elif globs and not settable:
            # 읽는 전역이 **전부 const** 다 — 설정할 값이 없으니 입력 0 이 정상이다.
            # ⚠ 이걸 안 나누면 아래 `dropped_by_name_filter`(= 이름 추출이 버렸다,
            #   **결함**)로 잘못 분류된다. 의도한 억제를 결함으로 세면 사유 분포가
            #   조치 가능한 축을 못 짚는다.
            cause = "const_globals_only"
        elif "IN" in tags or "INOUT" in tags:
            # 읽는 전역이 분명히 있는데 입력 열이 비었다 = **이름 추출이 버렸다**.
            # 실측된 경로: 이름 뒤 `(idx: …)`/`(range: …)` 꼬리, 로컬 임시 프리픽스 오탐,
            # 2글자 이하 이름. 정상이 아니므로 다른 사유와 절대 섞지 않는다.
            cause = "dropped_by_name_filter"
        elif params and not tags:
            # 파라미터 문자열은 있는데 이름이 안 나온다 — 주석 블록이 통째로 파라미터로
            # 딸려온 경우가 대부분이다(Processor Expert 계열 `*_GetVal`).
            cause = "param_string_unusable"
        elif tags and tags <= {"INDIRECT", "INDIRECT2"}:
            # 간접 접근뿐 — 직접 넣을 값이 없다.
            # ⚠ **2홉(`INDIRECT2`)도 여기 속한다.** `{"INDIRECT"}` 만 보면 2홉만 가진
            #   함수가 `other` 로 새고, 사유 분포가 조치 가능한 축을 못 짚는다.
            cause = "indirect_only"
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


def _measure_suts_asil(units: List[Any]) -> Dict[str, Any]:
    """안전 판정(`Safety Related`)이 **무엇을 근거로** 정해졌나.

    `_resolve_unit_asil` 은 SwUDS 가 침묵한 unit 의 등급을 SDS 파티션 이름의
    **부분문자열 첫 일치**로 집는다. 그 규칙은 대안 6개를 다 재본 뒤 값을 그대로
    두기로 한 것이지만(라운드 9), 그렇게 정해졌다는 사실까지 숨길 이유는 없다 —
    ISO 26262 문서에서 등급의 근거는 읽는 사람이 알아야 한다.

    실측(2026-08-14, KJPDS02_PV): 라이브 **28건**, SwUDS 를 끄면 **244건**.
    즉 UDS 가 없는 프로젝트에서는 안전 등급의 상당수가 사전 순서로 정해진다.

    ⚠ 건수를 `units_without_input` 처럼 "정상 기준선" 과 비교하지 않는다. 근거가 약한
      건 몇 건까지가 정상이라는 기준선이 없다 — 0 이 기준이고 나머지는 전부 알림이다.
    """
    from report_gen.requirements import _asil_max_of

    weak: List[str] = []
    conflict: List[str] = []
    graded = 0
    for u in units:
        if not isinstance(u, dict):
            continue
        # ⚠ 분모에 `TBD` 를 넣지 않는다. `asil` 은 등급을 못 찾아도 `TBD` 로 채워지므로
        #   `str(...)` 진리값으로 세면 **전 unit 이 등급 있음**으로 잡히고, "1,157 중
        #   425 가 약함" 이 "나머지 732 는 근거가 단단하다" 로 읽힌다. 등급 판정은
        #   `_asil_max_of` 단일 출처(TBD·빈칸 → "")를 쓴다.
        if _asil_max_of([str(u.get("asil") or "")]):
            graded += 1
        ev = str(u.get("asil_evidence") or "")
        if ev == "sds-fuzzy-conflict":
            conflict.append(str(u.get("name") or ""))
        elif ev == "sds-fuzzy":
            weak.append(str(u.get("name") or ""))
    return {
        "measured": True,
        "units": len(units),
        "graded": graded,
        # `sds-fuzzy` = 부분문자열 첫 일치 · `sds-fuzzy-conflict` = 그 위에 **후보 등급이
        # 갈리기까지** 한 것(= 사전 순서가 등급을 정했다). 둘을 합치면 심각도가 섞인다.
        "fuzzy": len(weak),
        "fuzzy_conflict": len(conflict),
        "samples": (conflict[:6] + weak[:6])[:8],
    }


def _measure_sts_mapping(fd: Dict[str, Any], sds_map: Dict[str, Any],
                         sds_reason: str, srs_path: str,
                         uds_path: str = "") -> Dict[str, Any]:
    """요구가 **함수 근거를 갖고** 시험되는가.

    `generate_test_cases` 는 매핑이 빈 요구에도 TC 를 낸다(`_generate_review_steps`).
    그래서 요구 커버리지는 100% 로 보이는데 그 TC 들은 소스 근거가 0 이다 — 이 축이
    없으면 그 사실이 어디에도 안 나온다.

    실측(2026-08-14, KJPDS02_PV · 정본 SwRS/SwDS v3.01): 68 요구 중 **20** 이 미매핑.
    그중 **16 은 SwDS 의 `related` 에는 있다**(우리가 그 파티션에 못 닿은 것 = 결함) ·
    **4 는 SwDS 어디에도 없다**(설계가 그 요구를 안 이은 것 = 문서 간 추적 부재).
    ⚠ 이 둘을 한 숫자로 합치면 조치할 수 있는 축이 안 보인다.

    ## 설계-ID 브리지 (2026-08-18)

    그 16 이 걸린 SwDS 파티션의 kind 는 `design_id` 19 · `table_row` 12 ·
    `design_element` 4 — **`function` 0** 이었다. 함수 이름으로는 구조적으로 못 닿는
    키(`swfn_35`, `차속에 따른 도어 open 방지`)라, SwUDS 의 `Related ID`(설계 ID)를
    경유해야 닿는다. 그래서 이 측정도 **SwUDS 를 받는다** — 안 받으면 브리지가 꺼진
    상태를 재게 되고, 게이트가 산출물보다 나쁜 숫자를 보고한다.
    ⚠ `uds_path` 가 없으면 그 사실을 `bridge` 로 **명시**한다(빠진 것을 0 으로 접지 않는다).
    """
    if not str(srs_path or "").strip():
        return {"measured": False, "reason": "SwRS 경로가 지정되지 않았습니다"}
    try:
        from backend.services.resolver_helpers import materialize_via_resolver
        local, reason = materialize_via_resolver(srs_path)
        if not local:
            return {"measured": False, "reason": reason or "SwRS 를 읽지 못했습니다"}
        from generators.sts import (
            _MAX_TC_PER_REQ,
            _REQ_ID_PAT,
            load_uds_design_ids,
            map_requirements_to_functions,
            parse_srs_docx_tables,
        )
        reqs = parse_srs_docx_tables(str(local)) or []
    except Exception as exc:  # noqa: BLE001 — docx/IPC 계열이 광범위
        _logger.warning("test_materials: SwRS 요구 파싱 실패 — %s", exc, exc_info=True)
        return {"measured": False,
                "reason": f"SwRS 파싱 실패 ({type(exc).__name__}: {str(exc)[:120]})"}
    if not reqs:
        return {"measured": False, "reason": "SwRS 에서 요구를 찾지 못했습니다"}

    # ⚠ SwUDS 를 실체화해서(worker 경유) 설계-ID 브리지를 **산출물과 같은 조건**으로 켠다.
    #   여기서 안 켜면 게이트가 실제 생성물보다 나쁜 숫자를 보고한다(48 vs 64).
    bridge: Dict[str, Any] = {"on": False, "reason": "SwUDS 경로가 지정되지 않았습니다"}
    uds_design_ids: Dict[str, Any] = {}
    if str(uds_path or "").strip():
        try:
            from backend.services.resolver_helpers import resolve_builder_input
            _local_uds = resolve_builder_input(uds_path, label="SwUDS")
            if not _local_uds:
                bridge = {"on": False, "reason": "SwUDS 를 읽지 못했습니다"}
            else:
                uds_design_ids = load_uds_design_ids(_local_uds) or {}
                bridge = ({"on": True, "functions": len(uds_design_ids)}
                          if uds_design_ids else
                          {"on": False, "reason": "SwUDS 에서 설계 ID 를 찾지 못했습니다"})
        except Exception as exc:  # noqa: BLE001 — docx/IPC 계열이 광범위
            _logger.warning("test_materials: SwUDS 설계-ID 브리지 실패 — %s", exc, exc_info=True)
            bridge = {"on": False,
                      "reason": f"SwUDS 파싱 실패 ({type(exc).__name__}: {str(exc)[:120]})"}

    # ⚠ `sds_map=None` 은 저장소 `docs/` 글롭(**프로젝트 무관**)을 쓴다. 게이트가 그걸
    #   쓰면 남의 프로젝트 요구 ID 로 잰 숫자를 보여 준다 — 명시적으로 `{}` 를 준다.
    req_to_fids = map_requirements_to_functions(
        reqs, fd, sds_map=sds_map or {}, uds_design_ids=uds_design_ids or None)
    mentioned = {
        m.group(1)
        for v in (sds_map or {}).values() if isinstance(v, dict)
        for m in _REQ_ID_PAT.finditer(str(v.get("related") or ""))
    }
    causes: Dict[str, int] = {}
    samples: Dict[str, List[str]] = {}
    for r in reqs:
        rid = str(r.get("id") or "")
        if req_to_fids.get(rid):
            continue
        cause = "unreached_in_sds" if rid in mentioned else "absent_from_sds"
        causes[cause] = causes.get(cause, 0) + 1
        bucket = samples.setdefault(cause, [])
        if len(bucket) < 8:
            bucket.append(rid)

    # 요구당 TC 상한이 버리는 함수. ⚠ **하한**이다 — 한 함수가 여러 TC 를 내면 상한이
    # 더 일찍 차므로 실제로는 더 빠진다(실측: 여기 계산 715 vs 실제 887).
    cap = _MAX_TC_PER_REQ
    mapped_fids = {f for v in req_to_fids.values() for f in v}
    kept_fids = {f for v in req_to_fids.values() for f in v[:cap]}
    return {
        "measured": True,
        "requirements": len(reqs),
        "mapped": sum(1 for v in req_to_fids.values() if v),
        "causes": causes,
        "cause_samples": samples,
        "sds_reason": sds_reason,
        "bridge": bridge,
        "cap": cap,
        "mapped_functions": len(mapped_fids),
        "functions_beyond_cap": len(mapped_fids - kept_fids),
        "requirements_over_cap": sum(1 for v in req_to_fids.values() if len(v) > cap),
    }


def measure(source_root: str, *, sds_path: str = "", srs_path: str = "",
            uds_path: str = "") -> Dict[str, Any]:
    """시험 문서 재료를 측정한다. **느리다** — 전용 엔드포인트에서만 부를 것."""
    if not str(source_root or "").strip():
        return {"ok": False, "reason": "소스 루트가 지정되지 않았습니다"}

    t0 = time.time()
    try:
        from report_generator import generate_uds_source_sections
        _sections = generate_uds_source_sections(source_root) or {}
        fd = _sections.get("function_details", {}) or {}
        # 전역 선언 정보(타입·배열 차원). 이걸 안 넘기면 아래 SUTS 측정이 실제
        # 산출물과 다른 규칙으로 돈다 — `collect_unit_functions` 참조.
        gim = _sections.get("globals_info_map") or {}
    except Exception as exc:  # noqa: BLE001 — 파서 계열이 광범위
        _logger.warning("test_materials: 소스 파싱 실패 — %s", exc, exc_info=True)
        return {"ok": False, "reason": f"소스 파싱 실패 ({type(exc).__name__}: {str(exc)[:140]})"}

    if not fd:
        # 0 함수는 "함수가 없다" 가 아니라 대개 파싱이 안 된 것이다 — 사유와 함께 낸다.
        return {"ok": False, "reason": "소스에서 함수를 찾지 못했습니다", "functions": 0}

    sds_map, sds_reason = _load_sds_map(sds_path)
    # ⚠ unit 수집은 이 측정에서 가장 비싼 단계다. 입력 축과 ASIL 근거 축이 **같은
    #   목록**을 봐야 하기도 한다 — 따로 두 번 부르면 비용도 두 배고, 그 사이 규칙이
    #   갈리면 두 패널이 서로 다른 그림을 보여 준다(`_dir_tag` 주석의 전례).
    _units: List[Any] = []
    result = {
        "ok": True,
        "functions": len(fd),
        "elapsed_s": round(time.time() - t0, 1),
        "sits": _measure_sits(fd, sds_map, sds_reason, uds_path),
        "suts": _measure_suts_types(fd),
        "suts_inputs": _measure_suts_inputs(fd, sds_map, gim, units_out=_units),
        "suts_asil": _measure_suts_asil(_units),
        "sts_mapping": _measure_sts_mapping(fd, sds_map, sds_reason, srs_path, uds_path),
    }
    with _CACHE_LOCK:
        _CACHE[_key(source_root)] = (time.time(), result)
    return result
