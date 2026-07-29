"""영향도 문서 초안 — 타입 해상도와 문서 컬럼 골격(순수 함수).

`impact_orchestrator`가 이미 2900줄이라 분리한다. 여기 있는 함수는 전부 I/O 없는 순수
함수이고, 프론트의 판정(reconcile)에 필요한 **원재료**만 만든다.

## 왜 `generators.suts.infer_variable_type`을 그대로 쓰지 않는가

그 함수는 이름 규칙에도 globals 맵에도 없는 변수를 **조용히 `"uint8_t"`로 기본값 처리**한다
(`generators/suts.py`의 마지막 `return "uint8_t"`). 실 문서생성 경로에서는 "무언가는 써야
한다"는 요구가 있어 타당하지만, 영향도 카드에서는 다르다 — 실측 `g_sys_error_his`는 어느
패턴에도 안 걸려 U8로 둔갑하고 `MAX=0xFF`라는 **없는 경계값**을 제안하게 된다(실제 U16).

그래서 `resolve_var_type`은 **dispatch만 재사용하고 기본값 없이 `None`을 돌려준다**.
호출부(프론트)는 `None`을 받으면 숫자를 만들지 않고 `[검증 필요] 타입 미상`으로 표기한다.
이건 취향이 아니라 이 저장소의 정직성 규약이다 — 근거 없는 숫자를 내지 않는다.

## 배열 첨자

`generators/suts.py:_extract_var_names`는 `re.sub(r"\\[.*?\\]$", "", ...)`로 첨자를 벗긴다.
그건 실 문서생성 경로라 손대지 않는다. 반면 초안은 문서 컬럼(`g_sys_error_his[0]`)과 셀
단위로 대응해야 하므로 **표시·컬럼에서는 첨자를 보존하고, 타입 조회만 base로** 한다.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# 첨자(`[0]`, `[i][2]`)를 뒤에서 떼어낸다. 중첩 첨자도 한 번에.
_SUBSCRIPT_RE = re.compile(r"((?:\[[^\]]*\])+)\s*$")

# UDS payload의 어노테이션 형식: '[IN] U16 g_sys_error_his', '[OUT] return U8 (range: …)'.
# `generators/sits.py:_infer_boundary_values`가 이미 신뢰하는 형식이라 같은 토큰 집합을 쓴다.
# 소스가 안 잡히는 환경(cloudium)에서 globals_info_map 없이 타입을 얻는 보조 축.
#
# ⚠ 실측(KJPDS02_PV job, 함수 725개): 이 축은 **한 건도 발화하지 않았다** — 그 job의
#   `doc_content.uds[fn].globals`가 전부 비어 있었다(사이드카 payload 부재, cloudium 링크 문서).
#   같은 데이터에서 실제 타입 해상은 **이름 규칙으로 81%**(467/580 컬럼)였고 나머지 19%는
#   `[검증 필요] 타입 미상`으로 남았다(숫자 날조 없음). 즉 이 축은 UDS 사이드카가 있는 프로젝트용
#   보조 경로이지 주 경로가 아니다 — 해상률을 더 올리려면 소스 해결(globals_info_map)이 필요하다.
_ANNOT_TYPE_RE = re.compile(
    r"\b(U8|U16|U32|U64|S8|S16|S32|S64|BOOL|BOOLEAN|FLOAT|FLOAT32|DOUBLE)\b", re.I)
_ANNOT_TAG_RE = re.compile(r"^\s*\[(?:IN|OUT|INOUT|INDIRECT)\]\s*", re.I)
_ANNOT_TYPE_TO_C = {
    "U8": "uint8_t", "U16": "uint16_t", "U32": "uint32_t", "U64": "uint32_t",
    "S8": "int8_t", "S16": "int16_t", "S32": "int32_t", "S64": "int32_t",
    "BOOL": "bool", "BOOLEAN": "bool",
    "FLOAT": "float", "FLOAT32": "float", "DOUBLE": "float",
}


def parse_annotated_types(annotated: Any) -> Dict[str, str]:
    """`['[IN] U16 g_sys_error_his', ...]` → `{'g_sys_error_his': 'uint16_t'}`.

    타입 토큰과 식별자가 **둘 다** 있을 때만 인정한다 — `'[OUT] return U8 (range: …)'`
    처럼 변수명이 없는 항목은 어디에 귀속할지 모르므로 버린다(오귀속이 환각보다 낫지 않다).
    """
    out: Dict[str, str] = {}
    for raw in (annotated or []):
        s = _ANNOT_TAG_RE.sub("", str(raw or "")).strip()
        if not s:
            continue
        m = _ANNOT_TYPE_RE.search(s)
        if not m:
            continue
        ctype = _ANNOT_TYPE_TO_C.get(m.group(1).upper())
        if not ctype:
            continue
        # 타입 토큰 뒤의 첫 식별자 = 변수명. 괄호 주석('(range: …)')은 식별자로 치지 않는다.
        tail = s[m.end():].split("(", 1)[0]
        toks = [t.strip("*&;,") for t in tail.replace("*", " ").split()]
        name = next((t for t in toks if re.match(r"^[A-Za-z_]\w*$", t)), "")
        base, _sub = base_var(name)
        if base and base not in out:
            out[base] = ctype
    return out


def base_var(name: Any) -> tuple[str, str]:
    """`'g_sys_error_his[0]'` → `('g_sys_error_his', '[0]')`. 첨자 없으면 `(name, '')`.

    표시용 이름은 호출부가 원문 컬럼을 그대로 쓰고, 여기서 얻은 base는 **타입 조회에만** 쓴다.
    """
    s = str(name or "").strip()
    if not s:
        return "", ""
    m = _SUBSCRIPT_RE.search(s)
    if not m:
        return s, ""
    return s[: m.start()].strip(), m.group(1)


def resolve_var_type(
    name: Any,
    type_cache: Optional[Dict[str, str]] = None,
    *,
    annot_types: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, str]]:
    """변수명 → `{'type': 'uint16_t', 'source': ...}` 또는 `None`(미상).

    우선순위 (근거가 강한 순 — `source`가 그 근거를 밝힌다):
      1. `globals_map`   — `globals_info_map` 실측(소스 파싱). 가장 강함.
      2. `doc_annotation` — UDS payload의 `[IN] U16 g_x` 어노테이션. 소스가 없는
         cloudium 환경에서 **문서가 직접 말하는** 타입이라 이름 규칙보다 신뢰도가 높다.
      3. `name_pattern`   — 헝가리안 이름 규칙(u16t_Data → uint16_t). 관례일 뿐이라 최약.
      4. 없음 → `None`.

    `type_cache`는 `generators.suts._gim_to_type_map(globals_info_map)` 산출({var: raw_type}).
    **항상 명시 주입**한다 — 프로세스 전역 `_globals_type_cache`를 읽으면 동시 문서생성과
    write-race가 나고 타 프로젝트 타입에 오염된다(기존 `type_cache=` 격리 패턴과 동일).

    ⚠ 미상은 반드시 `None`. `uint8_t` 기본값으로 떨어뜨리지 않는다(모듈 docstring 참조).
    """
    raw_name = str(name or "").strip()
    if not raw_name:
        return None
    from generators.suts import _TYPE_NAME_PATTERNS, _normalize_type

    base, _ = base_var(raw_name)
    cache = type_cache if isinstance(type_cache, dict) else {}
    # 1) globals_info_map 실측 — 첨자 포함 원문 키가 있을 수도 있으니 둘 다 본다.
    for key in (raw_name, base):
        if key and key in cache:
            mapped = _normalize_type(str(cache[key] or ""))
            if mapped:
                return {"type": mapped, "source": "globals_map"}
    # 2) 문서 어노테이션(`[IN] U16 g_x`) — 소스 미해결 환경의 주 근거.
    annots = annot_types if isinstance(annot_types, dict) else {}
    for key in (raw_name, base):
        if key and annots.get(key):
            return {"type": str(annots[key]), "source": "doc_annotation"}
    # 3) 이름 규칙 폴백. 여기서도 못 찾으면 미상.
    for pat, typename in _TYPE_NAME_PATTERNS:
        if pat.search(base or raw_name):
            return {"type": typename, "source": "name_pattern"}
    return None


def build_var_types(
    var_names: Any,
    type_cache: Optional[Dict[str, str]] = None,
    *,
    annotated: Any = None,
    cap: int = 200,
) -> Dict[str, Dict[str, str]]:
    """변수명 목록 → `{base_var: {type, source}}`. 미상 변수는 **키 자체를 넣지 않는다**.

    키가 base_var인 이유: 배열 원소 5개(`g_arr[0..4]`)가 같은 타입이므로 base 하나로 접는다
    (페이로드 절감 + 프론트가 `baseVar()`로 조회). 키 부재 = 미상 = 숫자 제안 금지.

    `annotated`: UDS payload의 어노테이션 문자열 목록(`['[IN] U16 g_x', ...]`).
    `type_cache`(소스 실측)가 없는 cloudium 경로에서 타입을 얻는 축.
    """
    out: Dict[str, Dict[str, str]] = {}
    annots = parse_annotated_types(annotated)
    seen: set = set()
    for raw in (var_names or []):
        base, _ = base_var(raw)
        if not base or base in seen:
            continue
        seen.add(base)
        info = resolve_var_type(raw, type_cache, annot_types=annots)
        if info:
            out[base] = info
        if len(seen) >= cap:
            break
    return out


def collect_var_names(rows: Any, columns: Any = None) -> List[str]:
    """문서 원문(TC 행 목록 + 컬럼 메타)에서 등장하는 변수명을 **열 순서 보존**해 모은다.

    `columns`(시트 헤더 원문)를 우선한다 — 그게 문서의 권위 있는 열 순서다. 행의 키는
    보완용(헤더가 비어 있거나 캡에 잘린 경우). 시그니처 파라미터는 **여기 넣지 않는다**:
    문서에 없는 컬럼을 원문 컬럼과 섞으면 "원문은 g_sys_error_his인데 제안은 u16t_Data"
    같은 불일치가 그대로 재발한다(호출부가 '신규 컬럼 추가 제안'으로 따로 표기).
    """
    out: List[str] = []
    seen: set = set()

    def _add(v: Any) -> None:
        s = str(v or "").strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)

    cols = columns if isinstance(columns, dict) else {}
    for side in ("inputs", "expected"):
        for c in (cols.get(side) or []):
            _add(c)
    for r in (rows or []):
        if not isinstance(r, dict):
            continue
        for side in ("inputs", "expected"):
            kv = r.get(side)
            if isinstance(kv, dict):
                for k in kv:
                    _add(k)
    return out


def canonical_suts_columns() -> Dict[str, Any]:
    """SUTS 시트의 고정 컬럼 라벨(열 순서). 문서 메타가 없을 때의 폴백 골격.

    라벨은 `generators.suts._FIXED_HEADERS`/`_RELATED_HEADER`에서 가져온다 — 하드코딩하면
    실 문서 템플릿이 바뀔 때 조용히 갈라진다(TSV 붙여넣기 열이 밀린다).
    개행이 든 라벨(`"Safety\\nRelated"`)은 한 줄로 편다 — TSV 셀 구분자와 충돌한다.
    """
    from generators.suts import _FIXED_HEADERS, _RELATED_COL, _RELATED_HEADER

    fixed = [(c, str(h).replace("\n", " ")) for c, h in sorted(_FIXED_HEADERS.items())]
    return {
        "fixed": [h for _c, h in fixed],
        "related": str(_RELATED_HEADER),
        "related_col": int(_RELATED_COL),
        "sheet": "",   # 시트명은 문서 메타(loc.sheet)에서만 — 템플릿별로 달라 하드코딩 금지
    }


def canonical_sits_columns() -> Dict[str, Any]:
    """SITS 시트의 상세 컬럼 라벨(열 순서). `generators.sits._DETAIL_HEADERS`가 출처."""
    from generators.sits import _DETAIL_HEADERS, _RELATED_COL

    detail = [(c, str(h).replace("\n", " ")) for c, h in sorted(_DETAIL_HEADERS.items())]
    return {
        "fixed": [h for c, h in detail if c != _RELATED_COL],
        "related": next((h for c, h in detail if c == _RELATED_COL), "SwDS"),
        "related_col": int(_RELATED_COL),
        "sheet": "",
    }
