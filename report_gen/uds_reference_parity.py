"""정본 SUDS ↔ 생성 UDS 대조 — **읽기 전용 측정**.

## 이 모듈이 하지 않는 것 (R1)

정본 값을 산출물에 **주입하지 않는다.** 여기는 "정본에 있는 것을 우리가 담았는가" 를
재기만 하는 별도 경로다. `docx_builder._reference_identity_verdict` 가 다른 프로젝트
정본으로 값을 채우는 걸 fail-closed 로 막고 있고, 이 모듈은 그 게이트를 우회할 수단을
제공하지 않는다 — 반환값은 전부 수치·분류이고 정본 문자열은 표본(`samples`)에만,
그것도 사람이 읽을 길이로만 실린다.

## 두 축을 섞어 인용하지 말 것

- **이름 축**: 그 칸이 존재하는가 (어떤 파라미터를 적었는가)
- **값 축**: 그 칸에 무엇을 적었는가 (Type/Value Range/Reset Value/Description)

SUTS 시리즈에서 두 축이 **30%p** 벌어졌다. UDS 도 실측(2026-08-25) 이름 축 83.1% 인데
Value Range 값 축은 27.8% 다. "UDS 83%" 만 인용하면 값 축을 통째로 숨기게 된다.

## 표기차를 불일치로 세지 말 것 (SUTS R26 교훈)

`0x00 ~ 0xFF` 와 `0 ~ 255` 는 **같은 범위**다. 문자열 비교만 하면 range 재현율이
0.0% 로 나오는데 실제로는 27.8% 다. 숫자로 정규화한 뒤 센다.

## 조인은 **함수명**으로 한다

정본의 `SwUFn` 번호와 소스 파서의 번호는 다른 체계다(STS 시리즈 실측 43쌍 중 35쌍
불일치). ID 로 조인하면 조용히 엉뚱한 쌍을 맞춘다.

## 정본의 `N/A` 는 분모에서 뺀다

정본이 "근거 없음" 이라 적은 자리를 재현 대상으로 세면, 우리가 가진 근거를 지워야
점수가 오른다. 그건 재현이 아니다.
"""

from __future__ import annotations

import re
import zipfile
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

#: `[ Function Information ]` 표를 알아보는 표식.
FUNCTION_INFO_MARKER = "Function Information"

#: 파라미터 그리드의 값 열 — 이름(1번 열)을 뺀 나머지.
VALUE_COLUMNS: Tuple[str, ...] = ("type", "range", "reset", "desc")

#: 파라미터 섹션이 **끝났음**을 알리는 라벨. 정본/우리 양쪽 표기를 다 담는다.
_SECTION_END_LABELS = frozenset({
    "선행조건", "precondition", "사용 전역변수",
    "used globals (global)", "used globals (static)",
    "called function", "calling function", "logic diagram",
})

#: 정본에 `Paramters` 오타가 19건 있다 — 표기 흔들림을 여기서 흡수한다.
_INPUT_LABELS = frozenset({"input parameters", "input paramters"})
_OUTPUT_LABELS = frozenset({"output parameters", "output paramters"})

#: "근거 없음" 표기. 정본이 이걸 적은 칸은 재현 대상이 아니다.
_NA_TOKENS = frozenset({"", "N/A", "NA", "-", "TBD", "없음"})

_IDENT = re.compile(r"[^A-Za-z0-9_]")
_MEMBER_SPLIT = re.compile(r"(?:->|\.|\[)")
_ANNOT = re.compile(r"\([^)]*\)")
_INT_TOKEN = re.compile(r"^[+-]?(?:0[xX][0-9a-fA-F]+|\d+)$")


def _norm_ident(value: Any) -> str:
    """식별자 비교용 정규형 — 기호를 지우고 소문자로."""
    return _IDENT.sub("", str(value or "")).lower()


def _norm_text(value: Any) -> str:
    """값 비교용 — 공백만 접는다(표기 성격을 보려면 대소문자를 살려야 한다)."""
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_na(value: Any) -> bool:
    return _norm_text(value).upper() in _NA_TOKENS


def base_symbol(name: Any) -> str:
    """`REG_PTT.Bits.PTT3` → `reg_ptt`. 멤버 경로·첨자를 떼고 정규화한다."""
    head = _MEMBER_SPLIT.split(str(name or "").strip(), 1)[0]
    return _norm_ident(head)


def skeleton(name: Any) -> str:
    """주석 꼬리(`(size: 8)`)까지 떼어 **뼈대**만 남긴다 — 입도차/표기차 판정용."""
    return base_symbol(_ANNOT.sub("", str(name or "")))


def _cell_text(tc) -> str:
    """⚠ `itertext()` 만 쓰면 여러 줄 셀이 한 덩어리로 뭉개진다.

    이 저장소가 같은 실수로 **전 태그 0.0%** 를 낸 적이 있다(P2-3). `<w:p>` 마다
    잘라 개행으로 잇는다.
    """
    return "\n".join("".join(p.itertext()) for p in tc.findall(f"{_W}p")).strip()


def parse_function_info(path: str) -> Dict[str, Dict[str, Any]]:
    """`[ Function Information ]` 표를 전부 읽어 함수명으로 색인한다.

    python-docx 가 아니라 lxml+zipfile 직독이다 — 정본은 40.7MB 라 python-docx 로는
    24.3초가 걸려 대조를 반복할 수 없다.

    반환: ``{fn_key: {"name": 원본표기, "params": {"in": {sym: row}, "out": {...}},
    "labels": {정규화라벨: 값}}}``. ``row`` 는 ``(name, type, range, reset, desc)``.
    """
    # 지연 import — 저장소 규약(`iso26262_doc_asil_extractor`)과 같은 형태.
    from lxml import etree  # type: ignore

    with zipfile.ZipFile(path) as zf:
        root = etree.fromstring(zf.read("word/document.xml"))
    body = root.find(f"{_W}body")
    if body is None:
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for tbl in body.iter(f"{_W}tbl"):
        trs = tbl.findall(f"{_W}tr")
        if not trs:
            continue
        rows = [[_cell_text(tc) for tc in tr.findall(f"{_W}tc")] for tr in trs]
        if not any(FUNCTION_INFO_MARKER in c for c in rows[0]):
            continue
        block = _parse_one_block(rows)
        if not block:
            continue
        key = _norm_ident(block["name"])
        merged = out.setdefault(key, {"name": block["name"], "labels": {},
                                      "params": {"in": {}, "out": {}}})
        merged["labels"].update(block["labels"])
        for axis in ("in", "out"):
            for sym, row in block["params"][axis].items():
                # ⚠ setdefault — 같은 함수가 여러 표로 쪼개진 경우 **먼저 나온 것**을
                #    남긴다. dict 덮어쓰기로 행을 침묵 소실한 전례(SUTS R25 66행)가 있다.
                merged["params"][axis].setdefault(sym, row)
    return out


def _parse_one_block(rows: Sequence[Sequence[str]]) -> Optional[Dict[str, Any]]:
    name = ""
    labels: Dict[str, str] = {}
    params: Dict[str, Dict[str, Tuple[str, ...]]] = {"in": {}, "out": {}}
    axis: Optional[str] = None
    for row in rows:
        first = (row[0] if row else "").strip()
        label = first.strip("[] ").strip().lower()
        if label == "name" and len(row) > 1 and not name:
            name = row[1].strip()
        if label in _INPUT_LABELS:
            axis = "in"
            continue
        if label in _OUTPUT_LABELS:
            axis = "out"
            continue
        if label in _SECTION_END_LABELS:
            axis = None
        if axis is None:
            if label and len(row) > 1 and row[1].strip():
                labels.setdefault(label, row[1].strip())
            continue
        if label == "no":                            # 그리드 헤더
            continue
        if len(row) < 6:
            continue
        pname = row[1].strip()
        if not pname or _is_na(pname):
            continue
        params[axis].setdefault(
            base_symbol(pname),
            (pname, row[2].strip(), row[3].strip(), row[4].strip(), row[5].strip()),
        )
    return {"name": name, "labels": labels, "params": params} if name else None


# --------------------------------------------------------------------------- 값 비교


def _int_of(token: str) -> Optional[int]:
    text = str(token).strip().rstrip("uUlL")
    if not _INT_TOKEN.match(text):
        return None
    try:
        return int(text, 16) if "x" in text.lower() else int(text, 10)
    except ValueError:
        return None


def parse_range(value: Any) -> Optional[Tuple[int, int]]:
    """`0x00 ~ 0xFF` / `0 ~ 255` → `(0, 255)`. 못 읽으면 None.

    ⚠ 꼬리 주석(` (타입 폭)`)은 떼고 읽는다 — 그게 없으면 우리 칸이 전부 못 읽는 값이
    되어 표기차가 전부 불일치로 둔갑한다.
    """
    text = _ANNOT.sub("", _norm_text(value))
    if "~" not in text:
        return None
    left, _, right = text.partition("~")
    low, high = _int_of(left.strip()), _int_of(right.strip())
    if low is None or high is None:
        return None
    return (min(low, high), max(low, high))


def _strip_array(value: str) -> str:
    return re.sub(r"\s*(?:array|\[\s*\d*\s*\])\s*", " ", value, flags=re.I).strip()


def value_verdict(column: str, ref_value: Any, our_value: Any) -> Tuple[bool, str]:
    """정본 칸과 우리 칸이 **같은 주장**인가. ``(같음, 사유)``."""
    ref, ours = _norm_text(ref_value), _norm_text(our_value)
    if ref == ours:
        return True, "정확일치"
    if column == "range":
        r_range, o_range = parse_range(ref), parse_range(ours)
        if r_range and o_range and r_range == o_range:
            return True, "표기차(16진↔10진)"
        return False, "값 불일치"
    if column == "type":
        if _strip_array(ref).lower() == _strip_array(ours).lower():
            return True, "표기차(배열/대소문자)"
        return False, "값 불일치"
    if _norm_ident(ref) and _norm_ident(ref) == _norm_ident(ours):
        return True, "표기차(공백/기호)"
    return False, "값 불일치"


# --------------------------------------------------------------------------- 대조


def _axis_cells(blocks: Dict[str, Dict[str, Any]], keys: Iterable[str], axis: str):
    return {(fn, sym): row
            for fn in keys
            for sym, row in blocks[fn]["params"][axis].items()}


def _classify_shortfall(missing, ref_cells, our_cells, our_other_cells) -> Counter:
    """미달 3분류 — 2분류로 보면 손댈 대상이 부풀려진다 (SUTS R19).

    `방향 오배치` 는 정본이 같은 이름을 반대 열에도 적은 것이라 **재현 대상이 아니다**.

    ⚠ 뼈대는 **원본 표기**에서 뽑는다. 색인 키(`base_symbol`)로 뽑으면 `(size: 8)` 이
    이미 키에 녹아 있어(`u16s_bufsize8`) 표기차가 전부 `진짜 이름부재` 로 둔갑한다 —
    손댈 대상이 실제보다 커 보이고, 없는 축을 파게 된다.
    """
    our_skeletons: Dict[str, set] = defaultdict(set)
    for (fn, _sym), row in our_cells.items():
        our_skeletons[fn].add(skeleton(row[0]))
    kinds: Counter = Counter()
    for key in missing:
        fn = key[0]
        if key in our_other_cells:
            kinds["방향 오배치"] += 1
        elif skeleton(ref_cells[key][0]) in our_skeletons[fn]:
            kinds["표기차/입도차"] += 1
        else:
            kinds["진짜 이름부재"] += 1
    return kinds


def _classify_excess(extra, ref_other_cells,
                     known_symbols: Optional[set]) -> Counter:
    """과다는 결함 수가 아니라 **정직성 축**이다 — 지어낸 이름이 있는가.

    결정 3(정본은 하한선): 정본에 없는 항목은 과다가 아니라 정보량이다. 다만 소스에
    근거가 없는 이름이 하나라도 섞이면 그건 정직성 결함이므로 성격을 갈라 센다.
    """
    kinds: Counter = Counter()
    for key in extra:
        sym = key[1]
        if key in ref_other_cells:
            kinds["정본은 반대 열에만 적음"] += 1
        elif known_symbols is not None and sym in known_symbols:
            kinds["소스에 실재하나 정본이 안 적음"] += 1
        elif known_symbols is None:
            kinds["소스 대조 안 함"] += 1
        else:
            kinds["⚠ 소스 근거 미확인"] += 1
    return kinds


def compare(ref_path: str, our_path: str,
            known_symbols: Optional[Iterable[str]] = None,
            sample_limit: int = 5) -> Dict[str, Any]:
    """정본 ↔ 생성물 대조 결과.

    `known_symbols` 는 `globals_info_map` 의 키처럼 **소스에 실재하는 이름** 집합.
    주면 과다를 "지어냈나" 로 갈라 세고, 안 주면 그 판정을 하지 않는다(모르는 것을
    "근거 있음" 으로 세지 않기 위해서다).
    """
    ref_blocks = parse_function_info(ref_path)
    our_blocks = parse_function_info(our_path)
    known = {base_symbol(s) for s in known_symbols} if known_symbols is not None else None
    common = sorted(set(ref_blocks) & set(our_blocks))

    ref_by_axis = {ax: _axis_cells(ref_blocks, common, ax) for ax in ("in", "out")}
    our_by_axis = {ax: _axis_cells(our_blocks, common, ax) for ax in ("in", "out")}

    axes: Dict[str, Any] = {}
    for axis, label in (("in", "입력"), ("out", "기대")):
        other = "out" if axis == "in" else "in"
        ref_cells, our_cells = ref_by_axis[axis], our_by_axis[axis]
        hit = set(ref_cells) & set(our_cells)
        missing = set(ref_cells) - set(our_cells)
        extra = set(our_cells) - set(ref_cells)

        columns: Dict[str, Any] = {}
        for idx, column in enumerate(VALUE_COLUMNS, start=1):
            scored = [k for k in hit if not _is_na(ref_cells[k][idx])]
            counts: Counter = Counter()
            samples: List[Dict[str, str]] = []
            for key in scored:
                if _is_na(our_cells[key][idx]):
                    counts["필드 부재"] += 1
                    continue
                same, reason = value_verdict(column, ref_cells[key][idx], our_cells[key][idx])
                counts["정확일치" if reason == "정확일치" else
                       ("표기차" if same else "값 불일치")] += 1
                if not same and len(samples) < sample_limit:
                    samples.append({
                        "name": ref_cells[key][0][:60],
                        "ref": _norm_text(ref_cells[key][idx])[:60],
                        "ours": _norm_text(our_cells[key][idx])[:60],
                    })
            reproduced = counts["정확일치"] + counts["표기차"]
            columns[column] = {
                "denominator": len(scored),
                "reference_na_excluded": len(hit) - len(scored),
                "reproduced": reproduced,
                "reproduced_pct": _pct(reproduced, len(scored)),
                "exact": counts["정확일치"],
                "notation_only": counts["표기차"],
                "missing_field": counts["필드 부재"],
                "value_mismatch": counts["값 불일치"],
                "samples": samples,
            }

        axes[axis] = {
            "label": label,
            "reference_cells": len(ref_cells),
            "our_cells": len(our_cells),
            "name_axis": {
                "hit": len(hit),
                "recall_pct": _pct(len(hit), len(ref_cells)),
                "precision_pct": _pct(len(hit), len(our_cells)),
                "shortfall": len(missing),
                "shortfall_kinds": dict(_classify_shortfall(
                    missing, ref_cells, our_cells, our_by_axis[other])),
                "excess": len(extra),
                "excess_kinds": dict(_classify_excess(extra, ref_by_axis[other], known)),
            },
            "value_axis": columns,
        }

    return {
        "measured": True,
        "reference_functions": len(ref_blocks),
        "our_functions": len(our_blocks),
        "joined_functions": len(common),
        "join_key": "function_name",          # ⚠ ID 로 조인하지 말 것 — 번호 체계가 다르다
        "axes": axes,
    }


def _pct(numerator: int, denominator: int) -> Optional[float]:
    """분모 0 은 0.0% 가 아니라 **미측정**이다.

    0.0 으로 적으면 재본 적 없는 축이 최악값으로 둔갑한다 — 이 저장소가
    `artifact_match_pct` 에서 이미 고친 형태다.
    """
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100.0, 1)


def unmeasured(reason: str) -> Dict[str, Any]:
    """대조가 성립하지 않았을 때의 표준형. 수치를 0 으로 채우지 않는다."""
    return {"measured": False, "reason": reason}
