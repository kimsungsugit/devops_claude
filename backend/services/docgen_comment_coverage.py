"""C 소스 주석 커버리지 — **"주석이 있다"와 "내용이 있다"를 나눠서** 센다.

## 왜 나눠 세나 (2026-08-10 실측)

`c_parser` 기준으로 재면 주석은 부족하지 않다:

| 프로젝트 | 함수 | `comment_desc` 보유 | 그중 **내용 0자** |
|---|---|---|---|
| HDPDM01 (`PDS64_RD/Sources`) | 435 | 380 (87.4%) | **277 (73%)** |
| KJPDS02 (`NE1AW_PORTING`) | 967 | 729 (75.4%) | **287 (39%)** |

이 프로젝트들의 주석 양식은 ``* Function | ...`` 인데 내용을 안 적으면 추출 결과가
``'Function  |'``(내용 0자)이 된다. 그런데:

- `report_gen/function_analyzer.py::_is_generic_description` 이 이걸 **못 걸러낸다**
  (실측 generic 판정 **0건**). `_is_exact_generic` 의 집합은
  ``{"function","func","n/a","tbd","-","none",""}`` 인데 파이프 때문에 불일치한다.
- 그래서 `_classify_description_quality(d, "comment")` 가 **380개 전부 `high`**
  (신뢰도 1.00, 최고)를 준다.
- `backend/helpers/common.py::_has_meaningful_value` 도 ``{"N/A","TBD","-"}`` 만
  제외하므로 `description_pct`(`backend/helpers/uds.py:216`)가 **빈 껍데기를 "채워짐"**
  으로 센다.

즉 **HDPDM01 `description_pct` 는 87.4% 로 보고되지만 실질 내용 보유는 23.7%** 다.

## ⚠ 이 모듈은 판정을 **바꾸지 않는다**

생성기·게이트의 기존 판정(`_has_meaningful_value` 등)을 건드리면 공표된
`description_pct` 가 움직인다(87.4% → 23.7%). 그건 지표 정직화이지만 되돌리기 어려운
변경이라 **별건**으로 분리했다. 이 모듈은 **두 값을 나란히 내서 차이를 보이게만** 한다.

## ⚠ `scanned == 0` 을 `value: 0` 으로 그리지 말 것

"재지 못했다"와 "재봤더니 0" 은 다른 상태다. 모든 카운트가 `scanned` 를 함께 실어
호출자가 구분할 수 있게 한다(이 저장소의 반복 규약 — "미계산은 0이 아니라 —").
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 파싱 결과 캐시 — `parse_c_project` 는 실측 41초(350함수) ~ 368초(750함수)다.
# 행을 펼칠 때마다 돌릴 수 없다. 키는 (정규화 경로, max_files), 무효화는 TTL + 시그니처.
_CACHE: Dict[Tuple[str, int], Tuple[float, Any, Dict[str, Any]]] = {}
_CACHE_LOCK = threading.RLock()
_CACHE_TTL_S = 600.0

# 양식 라벨만 남고 내용이 없는 설명. 실측 사례: ``'Function  |'``.
# 구분자(`|` `:`) 앞의 머리말이 짧은 영문/공백이고 뒤가 비어 있는 형태를 잡는다.
_LABEL_ONLY = re.compile(r"^[A-Za-z ]{0,24}[|:]\s*$")

# 내용이 있다고 보기 어려운 최소 길이. 실측에서 15자 이하가 전부 라벨류였다.
_MIN_SUBSTANTIVE_LEN = 8


def is_substantive_description(text: Any) -> bool:
    """이 설명에 **실질 내용**이 있는가.

    ⚠ 기존 판정(`_is_generic_description` / `_has_meaningful_value`)을 대체하지 않는다.
    그 둘이 놓치는 "양식 라벨만 남은 값" 을 잡기 위한 **추가** 판정이다.
    """
    s = " ".join(str(text or "").split()).strip()
    if not s:
        return False
    if _LABEL_ONLY.match(s):
        return False
    # 구분자 뒤 내용만 남겨 길이를 본다 — ``'Function | x'`` 의 실내용은 ``'x'`` 다.
    tail = s
    for sep in ("|", ":"):
        if sep in tail:
            tail = tail.split(sep, 1)[1].strip()
    if not tail:
        return False
    return len(tail) >= _MIN_SUBSTANTIVE_LEN


def _signature(source_root: str, max_files: int) -> Optional[Tuple[int, int]]:
    """(파일 수, mtime 합) — 싸게 재고 변경을 감지한다. 실패하면 ``None``(캐시 미사용)."""
    try:
        root = Path(source_root.split(",")[0].strip())
        if not root.exists():
            return None
        n = 0
        mtime_sum = 0
        for p in root.rglob("*"):
            if p.suffix.lower() not in {".c", ".h"}:
                continue
            n += 1
            if n > max_files:
                break
            try:
                mtime_sum += int(p.stat().st_mtime)
            except OSError:
                # 개별 파일 stat 실패는 시그니처를 무효화하지 않는다 — 캐시가 조금
                # 둔감해질 뿐이고, 여기서 None 을 내면 매번 전량 재파싱이 된다.
                continue
        return (n, mtime_sum)
    except Exception:  # noqa: BLE001  # silent-ok
        # 시그니처를 못 구하면 캐시를 안 쓸 뿐 결과는 같다(매번 재파싱). 여기서 로깅하면
        # 경로가 없는 흔한 상태에 노이즈만 쌓인다 — 부재 사유는 `measure()` 가 보고한다.
        return None


def _parse_cached(source_root: str, max_files: int) -> Tuple[Any, Dict[str, Any]]:
    """`parse_c_project` 결과 + 메타. 메타에 `cached`/`elapsed_s`/`signature` 를 싣는다."""
    key = (str(source_root or "").strip().lower(), int(max_files))
    sig = _signature(source_root, max_files)
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and (now - hit[0]) < _CACHE_TTL_S and hit[2].get("signature") == sig:
            return hit[1], {**hit[2], "cached": True}

    from workflow.code_parser.c_parser import parse_c_project
    t0 = time.time()
    res = parse_c_project(source_root, max_files=max_files)
    meta = {
        "cached": False,
        "elapsed_s": round(time.time() - t0, 1),
        "signature": sig,
    }
    with _CACHE_LOCK:
        _CACHE[key] = (now, res, meta)
    return res, meta


def clear_cache() -> None:
    """테스트·강제 재측정용."""
    with _CACHE_LOCK:
        _CACHE.clear()


def has_cached(source_root: str, *, max_files: int = 300) -> bool:
    """이미 측정된 결과가 있는가 — **HTTP 핸들러가 이걸 먼저 본다**.

    ⚠ `parse_c_project` 는 실측 41초(350함수)~368초(750함수)다. 요청 안에서 돌리면
    화면이 그만큼 멈춘다. 그래서 preflight 는 **캐시가 있을 때만** 값을 싣고, 없으면
    `unmeasured`(사유: 아직 측정하지 않음)로 두고 측정 액션을 제안한다.
    "재지 못했다" 를 `0` 으로 그리지 않기 위한 장치이기도 하다.
    """
    key = (str(source_root or "").strip().lower(), int(max_files))
    sig = _signature(source_root, max_files)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        return bool(
            hit and (time.time() - hit[0]) < _CACHE_TTL_S and hit[2].get("signature") == sig
        )


def list_comment_targets(source_root: str, *, max_files: int = 300) -> Dict[str, Any]:
    """주석 보강 대상 함수 목록 — **두 갈래를 구분해서** 낸다.

    - `no_comment`  : 주석 자체가 없다.
    - `empty_comment`: 주석은 있는데 **내용이 비어 있다**(양식 라벨만).

    실측(HDPDM01): 380개 중 **277개가 후자**다. 둘을 합치면 "주석을 다세요" 라는 같은
    안내가 나가는데, 후자는 이미 주석 블록이 있으므로 **한 줄만 채우면 되는** 훨씬 싼
    작업이다. 조치 비용이 다르므로 섞지 않는다.

    반환은 파일·함수명을 포함한다 — 건수만으로는 아무도 못 고친다.
    """
    res, _meta = _parse_cached(source_root, max_files)
    funcs = list(res.get("functions") or [])
    no_comment: List[Dict[str, str]] = []
    empty_comment: List[Dict[str, str]] = []
    for f in funcs:
        name = str(f.get("name") or "")
        file = str(f.get("file") or "")
        d = str(f.get("comment_desc") or "").strip()
        if not d:
            no_comment.append({"file": file, "function": name})
        elif not is_substantive_description(d):
            empty_comment.append({"file": file, "function": name, "current": d[:80]})
    return {
        "functions": len(funcs),
        "no_comment": no_comment,
        "empty_comment": empty_comment,
        "total_targets": len(no_comment) + len(empty_comment),
    }


def measure(source_root: str, *, max_files: int = 300) -> Dict[str, Any]:
    """소스 주석 커버리지를 잰다.

    Returns:
        ``{"scanned_files", "functions", "partial", "elapsed_s", "cached",
           "description": {"filled", "substantive"},
           "asil": {"filled"}, "related": {"filled"},
           "substantive_gap": int, "samples": [...] }``

        - `scanned_files == 0` 이면 **재지 못한 것**이다. 호출자는 `functions` 를 `0` 으로
          그리면 안 된다.
        - `partial` 은 `max_files` 상한에 걸려 **일부만 봤다**는 뜻이다. 침묵 절단 금지
          (이 저장소가 여러 번 겪은 결함 — 상한이 총량을 조용히 줄인다).
    """
    root_first = str(source_root or "").split(",")[0].strip()
    if not root_first or not Path(root_first).exists():
        return {
            "scanned_files": 0, "functions": 0, "partial": False,
            "reason": "소스 루트를 찾을 수 없습니다",
            "description": {"filled": 0, "substantive": 0},
            "asil": {"filled": 0}, "related": {"filled": 0},
            "substantive_gap": 0, "samples": [],
        }

    res, meta = _parse_cached(source_root, max_files)
    funcs = list(res.get("functions") or [])
    scanned = list(res.get("scanned") or [])

    desc_filled = 0
    desc_substantive = 0
    asil_filled = 0
    related_filled = 0
    samples: List[str] = []
    for f in funcs:
        d = str(f.get("comment_desc") or "").strip()
        if d:
            desc_filled += 1
            if is_substantive_description(d):
                desc_substantive += 1
            elif len(samples) < 5:
                samples.append(d[:60])
        if str(f.get("comment_asil") or "").strip():
            asil_filled += 1
        if str(f.get("comment_related") or "").strip():
            related_filled += 1

    return {
        "scanned_files": len(scanned),
        "functions": len(funcs),
        # `parse_c_project` 는 파일 수가 상한에 닿으면 루프를 끊는다.
        "partial": len(scanned) >= max_files,
        "max_files": max_files,
        "elapsed_s": meta.get("elapsed_s"),
        "cached": meta.get("cached", False),
        "description": {"filled": desc_filled, "substantive": desc_substantive},
        "asil": {"filled": asil_filled},
        "related": {"filled": related_filled},
        # 기존 지표(`description_pct`)가 채워짐으로 세지만 실질 내용이 없는 칸 수.
        "substantive_gap": desc_filled - desc_substantive,
        "samples": samples,
    }
