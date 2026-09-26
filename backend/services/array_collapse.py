"""다차원 배열 컬럼 "접기" 유틸리티 (C# TResultParser ``Lib/VectorCAST/ArrayCollapse.cs`` 포팅).

다차원 배열(예: ``buffer[5][7][7]`` = 245 요소)이 VectorCAST 결과에서 요소별 컬럼으로
펼쳐지면 Excel 열 한계(16,384)를 넘거나 SUTR 변수 표기 한도(기본 10열)에서 절단되어
데이터가 silent 누락된다. 이 모듈은 C# 원본과 동일한 규칙으로 그런 배열을 1개 컬럼으로 접는다.

규칙(C# 원본 주석과 동일):
  - 인덱스 그룹이 2개 이상(다차원)이고, 경계상자가 100% 꽉 찬 배열만 1개 컬럼으로 접는다.
    접힌 헤더 = ``base[d1*d2*..]``.
  - 100% 미만(특정 셀만 사용)이면 접지 않고 개별 인덱스 컬럼을 그대로 둔다.
  - 셀 값: 모든 요소가 같으면 값 하나, 다르면 바깥(첫) 차원별 줄바꿈으로 전부 표시.
  - 실제 결과(Actual): 전부 일치 OK, 아니면 NG (k/N) + 불일치 인덱스 일부.

접기 대상이 아닌 이름(스칼라/단일차원/부분채움 배열)은 **원본 순서 그대로 통과**하므로,
다차원 full-box 배열이 없는 일반 산출물의 컬럼 구성은 본 모듈 적용 전후가 동일하다(no-op).
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Optional, Tuple

# 키 끝에 붙은 연속된 [숫자] 인덱스 그룹 분리. "A.b[0][1][2]" -> base "A.b", indices [0,1,2].
# "A[0].b" -> base "A[0].b", indices [] (끝이 인덱스 아님).
_TRAILING_INDEX = re.compile(r"^(.*?)((?:\[\d+\])+)$")
_ONE_INDEX = re.compile(r"\[(\d+)\]")
# 접힌 컬럼 헤더 인식: "base[5*7*7]".
_COLLAPSED = re.compile(r"^(.*)\[(\d+(?:\*\d+)+)\]$")


def get_base_name(key: str) -> Tuple[str, Optional[List[int]]]:
    """키에서 후행 다중 인덱스를 분리해 (base, indices) 반환. 인덱스 없으면 (key, None)."""
    if not key:
        return key, None
    m = _TRAILING_INDEX.match(key)
    if not m:
        return key, None
    indices = [int(x.group(1)) for x in _ONE_INDEX.finditer(m.group(2))]
    return m.group(1), indices


def is_collapsed_column(column_name: str) -> bool:
    """접힌 **다차원** 컬럼 이름인지("base[5*7*7]") 판별.

    주의: ``collapse_all`` 모드의 단일차원 접힌 헤더(``base[N]``, '*' 없음)는 실제
    배열 요소명과 구분 불가라 ``False``를 반환한다. collapse 여부 판별은
    ``CollapseInfo.is_collapsed()``(groups dict 조회)를 사용할 것.
    """
    return bool(column_name) and _COLLAPSED.match(column_name) is not None


class ArrayGroup:
    """base 이름이 같은 다차원 배열 요소들의 묶음."""

    def __init__(self, base_name: str, dim_count: int) -> None:
        self.base_name = base_name
        self.dim_count = dim_count
        self.member_keys: List[str] = []        # 원본 dict 키 (인덱스 정렬)
        self.member_indices: List[List[int]] = []  # member_keys 와 정렬 일치
        self._max = [0] * dim_count
        self._sorted = False

    def add(self, key: str, idx: List[int]) -> None:
        if len(idx) != self.dim_count:
            return
        self.member_keys.append(key)
        self.member_indices.append(idx)
        for i in range(self.dim_count):
            if idx[i] > self._max[i]:
                self._max[i] = idx[i]
        self._sorted = False

    def dims(self) -> List[int]:
        """각 차원 크기 (최대 인덱스 + 1)."""
        return [self._max[i] + 1 for i in range(self.dim_count)]

    def full_size(self) -> int:
        size = 1
        for d in self.dims():
            size *= d
        return size

    def is_full_box(self) -> bool:
        """경계상자가 100% 채워졌는지(모든 인덱스 조합 존재) + 다차원 + 크기>1."""
        if self.dim_count < 2:
            return False
        full = self.full_size()
        if full <= 1:
            return False
        uniq = {tuple(idx) for idx in self.member_indices}
        return len(uniq) == full

    @property
    def header(self) -> str:
        """접힌 헤더: base[d1*d2*..]."""
        return self.base_name + "[" + "*".join(str(d) for d in self.dims()) + "]"

    def _ensure_sorted(self) -> None:
        if self._sorted:
            return
        # 인덱스 사전식 정렬(키/인덱스 동기). 모든 멤버 길이 동일(dim_count)이라 tuple 비교 = 사전식.
        paired = sorted(
            zip(self.member_keys, self.member_indices), key=lambda kv: tuple(kv[1])
        )
        self.member_keys = [k for k, _ in paired]
        self.member_indices = [i for _, i in paired]
        self._sorted = True

    def format_values(self, lookup: Callable[[str], Optional[str]]) -> str:
        """입력/기대 셀 표기. lookup: 원본 키 -> 값(없으면 None).

        모든 값이 같으면 값 하나, 다르면 바깥(첫) 차원별 줄바꿈으로 전부 표시.
        """
        self._ensure_sorted()
        idxs: List[List[int]] = []
        vals: List[str] = []
        for key, idx in zip(self.member_keys, self.member_indices):
            v = lookup(key)
            if v is None:
                continue
            idxs.append(idx)
            vals.append(v)

        if not vals:
            return ""
        if all(v == vals[0] for v in vals):
            return vals[0]

        # 단일차원(collapse_all 모드): "[i]: v" 콤마 구분 compact (줄바꿈 없이).
        if self.dim_count == 1:
            return ", ".join(f"[{idx[0]}]: {v}" for idx, v in zip(idxs, vals))

        # 다차원: 바깥(첫) 차원별로 줄바꿈.
        parts: List[str] = []
        last = -1
        line: List[str] = []
        for idx, v in zip(idxs, vals):
            outer = idx[0]
            if outer != last:
                if line:
                    parts.append(f"[{last}]: " + ", ".join(line))
                    line = []
                last = outer
            line.append(v)
        if line:
            parts.append(f"[{last}]: " + ", ".join(line))
        return "\n".join(parts)

    def format_actual(
        self, match_lookup: Callable[[str], Optional[bool]]
    ) -> Tuple[str, bool]:
        """실제 결과(Actual) 셀 표기. match_lookup: 원본 키 -> 일치여부(없으면 None).

        전부 일치 OK, 아니면 NG (k/N) + 불일치 인덱스 일부. 반환: (text, all_pass).
        """
        self._ensure_sorted()
        all_pass = True
        total = 0
        fail_idx: List[str] = []
        for key, idx in zip(self.member_keys, self.member_indices):
            m = match_lookup(key)
            if m is None:
                continue
            total += 1
            if m is False:
                all_pass = False
                fail_idx.append("[" + "][".join(str(i) for i in idx) + "]")

        if total == 0:
            return "", True
        if all_pass:
            return "OK", True

        max_show = 10
        idx_text = " ".join(fail_idx[:max_show])
        if len(fail_idx) > max_show:
            idx_text += f" …(+{len(fail_idx) - max_show})"
        return f"NG ({len(fail_idx)}/{total}) {idx_text}", False


class CollapseInfo:
    """원본 키 목록 -> 접기 정보(컬럼 목록 + 그룹맵)."""

    def __init__(self) -> None:
        self.columns: List[str] = []
        self.groups: Dict[str, ArrayGroup] = {}

    def is_collapsed(self, column_name: str) -> bool:
        return column_name in self.groups

    def get_group(self, column_name: str) -> Optional[ArrayGroup]:
        return self.groups.get(column_name)


def build(raw_names: Optional[List[str]], *, collapse_all: bool = False) -> CollapseInfo:
    """원본 변수명 목록을 받아 접기 컬럼 목록/그룹맵을 산출.

    - ``collapse_all=False`` (기본, C# ArrayCollapse 충실): **다차원(>=2) full-box**
      배열만 접는다. C#의 목적(Excel 16,384열 한계 회피)과 동일.
    - ``collapse_all=True`` (확장, 2026-06-24 사용자 결정): **단일차원·sparse 포함
      모든 배열**(같은 base에 인덱스 멤버 2개 이상)을 1열로 접는다. 회사 양식의
      좁은 변수 컬럼 한도(예 10열)에서 단일차원 배열(``lin_pFrameBuf[0..21]``)이
      절단되어 silent 누락되는 것을 방지. C# gold 시각(단일차원=별도 컬럼)과는 다름.

    접기 대상이 아닌 이름(스칼라/미달 배열)은 원본 순서 그대로 ``columns``에 들어간다.
    """
    info = CollapseInfo()
    if not raw_names:
        return info

    min_dims = 1 if collapse_all else 2

    # 1) base 별로 인덱스 멤버 수집(원본 순서 유지). collapse_all이면 단일차원도 포함.
    candidates: Dict[str, ArrayGroup] = {}
    base_order: List[str] = []
    for name in raw_names:
        base_name, idx = get_base_name(name)
        if idx is None or len(idx) < min_dims:
            continue  # 스칼라(인덱스 없음) 또는 (기본 모드) 단일차원은 접기 대상 아님
        grp = candidates.get(base_name)
        if grp is None:
            grp = ArrayGroup(base_name, len(idx))
            candidates[base_name] = grp
            base_order.append(base_name)
        grp.add(name, idx)

    # 2) 접기 확정. 기본=full-box만 / collapse_all=멤버 2개 이상이면 fullness 무관.
    if collapse_all:
        collapsed_bases = {
            b for b in base_order if len(candidates[b].member_keys) >= 2
        }
    else:
        collapsed_bases = {b for b in base_order if candidates[b].is_full_box()}

    # 3) 컬럼 목록: 접힌 그룹은 첫 등장 위치에 합친 헤더 1개, 나머지는 원본 그대로.
    emitted: set[str] = set()
    for name in raw_names:
        base_name, idx = get_base_name(name)
        if idx is not None and len(idx) >= min_dims and base_name in collapsed_bases:
            grp = candidates[base_name]
            if grp.header not in emitted:
                emitted.add(grp.header)
                info.columns.append(grp.header)
                info.groups[grp.header] = grp
            continue
        info.columns.append(name)

    return info
